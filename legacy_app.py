import asyncio
import html
import io
import json
import logging
import os
import re
import requests
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
import uvicorn

from cache import TTLCache
from collector import DataCollector
from db import Database
from lcu_client import LCUClient, LCUConnectionError
from so1_client import So1Client, So1ClientError


CACHE_SECONDS = 300
SHARD_CACHE_SECONDS = int(os.getenv("SHARD_CACHE_SECONDS", "600"))
ARAM_AUGMENT_CACHE_SECONDS = int(os.getenv("ARAM_AUGMENT_CACHE_SECONDS", "1800"))
DEFAULT_SHARD_DATA_URL = os.getenv(
    "SHARD_DATA_URL",
    "https://raw.githubusercontent.com/badspacebar/release/master/files/shards.json",
)
DEFAULT_SHARD_HERO_URL = os.getenv(
    "SHARD_HERO_URL",
    "https://game.gtimg.cn/images/lol/act/img/js/heroList/hero_list.js",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger = logging.getLogger("LOLDataSystem")
    try:
        # 获取全局单例客户端并初始化浏览器
        client = app.state.so1_client
        await client.init_browser()
    except Exception as e:
        logger.error(f"启动时初始化浏览器失败: {e}")
    yield
    # Shutdown
    try:
        client = app.state.so1_client
        await client.close_browser()
    except Exception as e:
        logger.error(f"关闭时关闭浏览器失败: {e}")

def build_app() -> FastAPI:
    """创建并配置FastAPI应用。"""
    app = FastAPI(lifespan=lifespan)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    logger = logging.getLogger("LOLDataSystem")

    db_config = {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", "123456"),
        "database": os.getenv("MYSQL_DATABASE", "lol_data"),
    }
    db: Optional[Database] = None
    db_error_message = ""
    try:
        db = Database(**db_config)
    except Exception as exc:
        db_error_message = str(exc)
        logger.error("数据库初始化失败: %s", exc)
        
    lcu = LCUClient(timeout=3)
    collector = DataCollector(db, lcu)
    collect_cache = TTLCache(ttl_seconds=CACHE_SECONDS)
    cross_cache = TTLCache(ttl_seconds=CACHE_SECONDS)
    shard_cache = TTLCache(ttl_seconds=SHARD_CACHE_SECONDS)
    aram_augment_cache = TTLCache(ttl_seconds=ARAM_AUGMENT_CACHE_SECONDS)
    
    # 初始化单例 So1Client 并保存到 app.state
    username = os.getenv("SO1_USERNAME", "mengxin1").strip()
    password = os.getenv("SO1_PASSWORD", "mengxin").strip()
    so1_client = So1Client(
        username=username,
        password=password,
        headless=os.getenv("SO1_HEADLESS", "1") != "0",
        timeout_ms=int(os.getenv("SO1_TIMEOUT_MS", "20000")),
    )
    app.state.so1_client = so1_client

    def _ensure_db() -> Optional[Database]:
        """确保数据库可用，失败时返回None。"""
        nonlocal db
        nonlocal db_error_message
        if db is not None:
            return db
        try:
            db = Database(**db_config)
            db_error_message = ""
            return db
        except Exception as exc:
            db_error_message = str(exc)
            logger.error("数据库重连失败: %s", exc)
            return None

    def _is_expired(last_update: datetime) -> bool:
        """判断数据是否超过缓存时效。"""
        return (datetime.now() - last_update).total_seconds() > CACHE_SECONDS

    def _kda(kills: int, deaths: int, assists: int) -> float:
        """计算KDA。"""
        return round((kills + assists) / max(deaths, 1), 2)

    def _build_recent_matches(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """格式化最近比赛输出结构。"""
        result = []
        for row in rows:
            kills = int(row.get("kills") or 0)
            deaths = int(row.get("deaths") or 0)
            assists = int(row.get("assists") or 0)
            result.append(
                {
                    "match_id": row.get("match_id"),
                    "game_time": row.get("game_time").strftime("%Y-%m-%d %H:%M:%S") if row.get("game_time") else "",
                    "champion": row.get("champion", ""),
                    "kills": kills,
                    "deaths": deaths,
                    "assists": assists,
                    "kda": _kda(kills, deaths, assists),
                    "win": bool(row.get("win")),
                    "damage": row.get("damage"),
                    "gold": row.get("gold"),
                }
            )
        return result

    def _safe_int(value: Any, default: int = 0) -> int:
        """安全整数转换。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _format_ts_ms(ts_ms: Any) -> str:
        """毫秒时间戳转可读时间。"""
        if ts_ms is None:
            return ""
        try:
            ts = float(ts_ms) / 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return ""

    REGION_CODE_NAMES = {
        "HN1": "艾欧尼亚",
        "HN10": "黑色玫瑰",
        "TJ100": "联盟四区",
        "TJ101": "联盟五区",
        "NJ100": "联盟一区",
        "GZ100": "联盟二区",
        "CQ100": "联盟三区",
        "BGP2": "峡谷之巅",
    }

    QUEUE_NAMES = {
        -1: "全部模式",
        0: "训练模式",
        2: "匹配模式",
        4: "单双排位",
        31: "人机对战",
        32: "人机对战",
        33: "人机对战",
        65: "极地乱斗",
        70: "克隆作战",
        76: "无限火力",
        100: "极地乱斗",
        318: "火力",
        400: "征召模式",
        420: "单双排位",
        430: "匹配模式",
        440: "灵活组排",
        450: "极地大乱斗",
        480: "快速模式",
        700: "冠军杯赛",
        900: "无限火力",
        1010: "无限火力",
        1020: "克隆模式",
        1200: "极限闪击",
        1300: "极限闪击",
        1400: "终极魔典",
        1700: "斗魂竞技场",
        1900: "无限火力",
        2400: "海克斯乱斗",
        1750: "斗魂竞技场",
    }

    POSITION_NAMES = {
        "TOP": "上路",
        "JUNGLE": "打野",
        "MIDDLE": "中路",
        "MID": "中路",
        "BOTTOM": "下路",
        "UTILITY": "辅助",
        "SUPPORT": "辅助",
        "INVALID": "未分路",
        "NONE": "未分路",
    }

    RANK_QUEUE_NAMES = {
        "RANKED_SOLO_5x5": "单双排",
        "RANKED_FLEX_SR": "灵活组排",
        "RANKED_TFT": "云顶之弈",
        "RANKED_TFT_TURBO": "云顶狂暴",
        "RANKED_TFT_DOUBLE_UP": "云顶双人",
    }

    TIER_NAMES = {
        "IRON": "坚韧黑铁",
        "BRONZE": "英勇黄铜",
        "SILVER": "不屈白银",
        "GOLD": "荣耀黄金",
        "PLATINUM": "华贵铂金",
        "EMERALD": "流光翡翠",
        "DIAMOND": "璀璨钻石",
        "MASTER": "超凡大师",
        "GRANDMASTER": "傲世宗师",
        "CHALLENGER": "最强王者",
    }

    def _resolve_region_display(region: str, basic_obj: Dict[str, Any], history_list: List[Dict[str, Any]]) -> str:
        explicit = (region or "").strip()
        if explicit:
            return f"{explicit}（{REGION_CODE_NAMES.get(explicit, explicit)}）" if explicit in REGION_CODE_NAMES else explicit
        for key in ("region", "serverName", "server_name", "areaName", "area", "serverId"):
            value = str(basic_obj.get(key) or "").strip()
            if value:
                return f"{value}（{REGION_CODE_NAMES.get(value, value)}）" if value in REGION_CODE_NAMES else value
        for item in history_list:
            if not isinstance(item, dict):
                continue
            platform = str(item.get("platformId") or "").strip()
            if platform:
                return f"{platform}（{REGION_CODE_NAMES.get(platform, '未知大区')}）"
        return "未指定"

    def _get_static_lol_data() -> Dict[str, Dict[str, str]]:
        cached = cross_cache.get("lol_static_zh_cn")
        if isinstance(cached, dict):
            return cached
        result: Dict[str, Dict[str, str]] = {"champions": {}, "items": {}, "spells": {}, "runes": {}}
        try:
            import requests

            def load_gtimg(path: str) -> Dict[str, Any]:
                resp = requests.get(f"https://game.gtimg.cn{path}", timeout=10)
                resp.raise_for_status()
                text = resp.text.strip().lstrip("\ufeff")
                try:
                    return resp.json()
                except Exception:
                    import json
                    import re

                    match = re.search(r"\{[\s\S]*\}", text)
                    if not match:
                        return {}
                    return json.loads(match.group(0))

            champion_res = load_gtimg("/images/lol/act/img/js/heroList/hero_list.js")
            for champ in champion_res.get("hero") or []:
                hero_id = str(champ.get("heroId") or "")
                alias = str(champ.get("alias") or "")
                name = str(champ.get("name") or alias or hero_id)
                if hero_id:
                    result["champions"][hero_id] = name
                if alias:
                    result["champions"][alias] = name

            item_res = load_gtimg("/images/lol/act/img/js/items/items.js")
            for item in item_res.get("items") or []:
                item_id = str(item.get("itemId") or item.get("id") or "")
                if item_id:
                    result["items"][item_id] = str(item.get("name") or item_id)

            rune_res = load_gtimg("/images/lol/act/img/js/runeList/rune_list.js")
            for rune_id, rune in (rune_res.get("rune") or {}).items():
                result["runes"][str(rune_id)] = str(rune.get("name") or rune_id)

            # lolso bundles summoner spell metadata in its frontend chunk; these names mirror that source.
            result["spells"].update(
                {
                    "1": "净化",
                    "3": "虚弱",
                    "4": "闪现",
                    "6": "幽灵疾步",
                    "7": "治疗术",
                    "11": "惩戒",
                    "12": "传送",
                    "13": "清晰术",
                    "14": "引燃",
                    "21": "屏障",
                    "30": "护驾！",
                    "31": "魄罗投掷",
                    "32": "标记",
                    "39": "标记",
                    "54": "占位",
                    "55": "占位和攻击惩戒",
                }
            )
            cross_cache.set("lol_static_zh_cn", result)
        except Exception as exc:
            logger.warning("failed to load lolso gtimg static data: %s", exc)
        return result

    def _queue_display(value: Any) -> str:
        if value is None or value == "":
            return ""
        try:
            queue_id = int(value)
            return QUEUE_NAMES.get(queue_id, str(queue_id))
        except (TypeError, ValueError):
            text = str(value)
            return RANK_QUEUE_NAMES.get(text, text)

    def _rank_display(queue: Dict[str, Any]) -> str:
        tier = str(queue.get("tier") or "").strip()
        if not tier:
            return ""
        division = str(queue.get("rank") or queue.get("division") or "").strip()
        lp = queue.get("leaguePoints")
        queue_name = RANK_QUEUE_NAMES.get(str(queue.get("queueType") or ""), str(queue.get("queueType") or ""))
        rank_text = f"{TIER_NAMES.get(tier, tier)} {division}".strip()
        if lp is not None:
            rank_text = f"{rank_text} {lp}LP".strip()
        return f"{queue_name} {rank_text}".strip()

    def _format_last_online(basic_obj: Dict[str, Any]) -> str:
        """格式化最后上线时间。"""
        for field in ("lastGameDate", "revisionDate"):
            value = basic_obj.get(field)
            if value is None:
                continue
            try:
                ts = float(value) / 1000
                return datetime.fromtimestamp(ts).strftime("%Y年%m月%d日%H时")
            except (TypeError, ValueError, OSError):
                continue
        return ""

    def _build_cross_pretty(name: str, region: str, basic: Any, rank: Any, history: Any, errors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构建跨区查询可视化输出。"""
        basic_obj = basic if isinstance(basic, dict) else {}
        rank_obj = rank if isinstance(rank, dict) else {}
        history_list = history if isinstance(history, list) else []
        input_game_name = name.split("#", 1)[0].strip() if "#" in name else name.strip()
        input_tag = name.split("#", 1)[1].strip() if "#" in name else ""
        target_puuid = str(basic_obj.get("puuid") or "").strip()
        static_data = _get_static_lol_data()

        def _pick_player(game_item: Dict[str, Any]) -> Dict[str, Any]:
            participants = game_item.get("participants") if isinstance(game_item.get("participants"), list) else []
            if not participants:
                return game_item
            for p in participants:
                if not isinstance(p, dict):
                    continue
                if target_puuid and str(p.get("puuid") or "").strip() == target_puuid:
                    return p
            for p in participants:
                if not isinstance(p, dict):
                    continue
                game_name = str(p.get("riotIdGameName") or p.get("summonerName") or "").strip()
                tag = str(p.get("riotIdTagline") or "").strip()
                if input_game_name and game_name == input_game_name:
                    if not input_tag or tag == input_tag:
                        return p
            return participants[0] if isinstance(participants[0], dict) else game_item

        recent_matches: List[Dict[str, Any]] = []
        for item in history_list[:10]:
            if not isinstance(item, dict):
                continue
            player = _pick_player(item)
            stats = player.get("stats") if isinstance(player.get("stats"), dict) else {}
            kills = _safe_int(player.get("kills", stats.get("kills", 0)))
            deaths = _safe_int(player.get("deaths", stats.get("deaths", 0)))
            assists = _safe_int(player.get("assists", stats.get("assists", 0)))
            champion_id = player.get("championID", player.get("championId", stats.get("championId")))
            champion_raw = player.get("championName") or player.get("champion") or champion_id or ""
            champion_name = (
                static_data.get("champions", {}).get(str(champion_id))
                or static_data.get("champions", {}).get(str(champion_raw))
                or str(champion_raw)
            )
            item_ids = [_safe_int(player.get(f"item{i}", 0)) for i in range(7)]
            item_names = [static_data.get("items", {}).get(str(item_id), str(item_id)) for item_id in item_ids if item_id]
            spell_ids = [_safe_int(player.get("spell1Id", 0)), _safe_int(player.get("spell2Id", 0))]
            spell_names = [static_data.get("spells", {}).get(str(spell_id), str(spell_id)) for spell_id in spell_ids if spell_id]
            perks = player.get("perks") if isinstance(player.get("perks"), dict) else {}
            styles = perks.get("styles") if isinstance(perks.get("styles"), list) else []
            primary_style = styles[0] if styles and isinstance(styles[0], dict) else {}
            sub_style = styles[1] if len(styles) > 1 and isinstance(styles[1], dict) else {}
            primary_runes = primary_style.get("selections") if isinstance(primary_style.get("selections"), list) else []
            main_rune_id = primary_runes[0].get("perk") if primary_runes and isinstance(primary_runes[0], dict) else None
            rune_names = [
                static_data.get("runes", {}).get(str(primary_style.get("style")), str(primary_style.get("style") or "")),
                static_data.get("runes", {}).get(str(main_rune_id), str(main_rune_id or "")),
                static_data.get("runes", {}).get(str(sub_style.get("style")), str(sub_style.get("style") or "")),
            ]
            rune_names = [r for r in rune_names if r]
            queue_id = item.get("queueId", item.get("queueType", item.get("gameMode", "")))
            position_raw = str(player.get("individualPosition") or player.get("lane") or "")
            teams = item.get("teams") if isinstance(item.get("teams"), list) else []
            team_obj: Dict[str, Any] = {}
            for team in teams:
                if isinstance(team, dict) and team.get("teamId") == player.get("teamId"):
                    team_obj = team
                    break
            objectives = team_obj.get("objectives") if isinstance(team_obj.get("objectives"), dict) else {}
            objective_summary = {
                key: _safe_int((objectives.get(key) or {}).get("kills", 0)) if isinstance(objectives.get(key), dict) else 0
                for key in ("tower", "dragon", "baron", "riftHerald", "horde", "inhibitor")
            }
            recent_matches.append(
                {
                    "match_id": item.get("gameId"),
                    "game_time": _format_ts_ms(item.get("gameCreation")),
                    "champion": champion_name,
                    "champion_raw": champion_raw,
                    "champion_id": _safe_int(champion_id, 0),
                    "kills": kills,
                    "deaths": deaths,
                    "assists": assists,
                    "kda": round((kills + assists) / max(deaths, 1), 2),
                    "win": bool(player.get("win", stats.get("win", False))),
                    "duration": _safe_int(item.get("gameDuration", 0)),
                    "queue": _queue_display(queue_id),
                    "queue_id": queue_id,
                    "mode": item.get("gameMode") or "",
                    "platform_id": item.get("platformId") or "",
                    "position": POSITION_NAMES.get(position_raw.upper(), position_raw),
                    "champ_level": _safe_int(player.get("champLevel", 0)),
                    "gold": _safe_int(player.get("goldEarned", 0)),
                    "gold_spent": _safe_int(player.get("goldSpent", 0)),
                    "cs": _safe_int(player.get("totalMinionsKilled", 0)),
                    "jungle_cs": _safe_int(player.get("neutralMinionsKilled", 0)),
                    "damage": _safe_int(player.get("totalDamageDealtToChampions", 0)),
                    "damage_taken": _safe_int(player.get("totalDamageTaken", 0)),
                    "damage_mitigated": _safe_int(player.get("damageSelfMitigated", 0)),
                    "objective_damage": _safe_int(player.get("damageDealtToObjectives", 0)),
                    "turret_damage": _safe_int(player.get("damageDealtToTurrets", 0)),
                    "vision_score": _safe_int(player.get("visionScore", 0)),
                    "control_wards": _safe_int(player.get("detectorWardsPlaced", 0)),
                    "items": item_names,
                    "item_ids": item_ids,
                    "spells": spell_names,
                    "spell_ids": spell_ids,
                    "runes": rune_names,
                    "multi_kills": {
                        "double": _safe_int(player.get("doubleKills", 0)),
                        "triple": _safe_int(player.get("tripleKills", 0)),
                        "quadra": _safe_int(player.get("quadraKills", 0)),
                        "penta": _safe_int(player.get("pentaKills", 0)),
                    },
                    "first_blood": bool(player.get("firstBloodKill", False)),
                    "first_tower": bool(player.get("firstTowerKill", False)),
                    "dragon_kills": _safe_int(player.get("dragonKills", 0)),
                    "baron_kills": _safe_int(player.get("baronKills", 0)),
                    "team_objectives": objective_summary,
                }
            )
        wins = sum(1 for m in recent_matches if m.get("win"))
        total = len(recent_matches)
        winrate = round((wins / total) * 100, 2) if total else 0.0
        avg_kda = round(sum(m["kda"] for m in recent_matches) / total, 2) if total else 0.0
        rank_text = ""
        queues = rank_obj.get("queues") if isinstance(rank_obj.get("queues"), list) else []
        ranked_queues: List[Dict[str, Any]] = []
        for queue_type in ("RANKED_SOLO_5x5", "RANKED_FLEX_SR"):
            for q in queues:
                if isinstance(q, dict) and q.get("queueType") == queue_type:
                    text = _rank_display(q)
                    ranked_queues.append(
                        {
                            "queue_type": q.get("queueType"),
                            "queue_name": RANK_QUEUE_NAMES.get(str(q.get("queueType") or ""), str(q.get("queueType") or "")),
                            "rank": text or "未定级",
                            "wins": _safe_int(q.get("wins", 0)),
                            "losses": _safe_int(q.get("losses", 0)),
                        }
                    )
                    if text and not rank_text:
                        rank_text = text
                    break
        display_name = basic_obj.get("name") or basic_obj.get("displayName") or name
        return {
            "name": display_name,
            "region": _resolve_region_display(region, basic_obj, history_list),
            "level": _safe_int(basic_obj.get("level", 0)),
            "profile_icon": _safe_int(basic_obj.get("profileIconId", 0)),
            "rank": rank_text,
            "ranked_queues": ranked_queues,
            "last_online_time": _format_last_online(basic_obj),
            "winrate_recent": f"{winrate}%",
            "avg_kda_recent": avg_kda,
            "recent_matches": recent_matches,
            "errors": errors,
            "raw_ok": basic is not None or history is not None or rank is not None,
        }

    def _format_duration(seconds: Any) -> str:
        total = _safe_int(seconds)
        if total <= 0:
            return "-"
        minutes, secs = divmod(total, 60)
        return f"{minutes}:{secs:02d}"

    def _load_image_font(size: int, bold: bool = False):
        try:
            from PIL import ImageFont

            candidates = [
                r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
                r"C:\Windows\Fonts\simhei.ttf",
                r"C:\Windows\Fonts\arial.ttf",
            ]
            for font_path in candidates:
                if font_path and os.path.exists(font_path):
                    return ImageFont.truetype(font_path, size)
            return ImageFont.load_default()
        except Exception:
            return None

    def _wrap_draw_text(draw: Any, text: str, font: Any, max_width: int) -> List[str]:
        if not text:
            return [""]
        lines: List[str] = []
        current = ""
        for ch in text:
            trial = current + ch
            try:
                width = draw.textbbox((0, 0), trial, font=font)[2]
            except Exception:
                width = len(trial) * 12
            if current and width > max_width:
                lines.append(current)
                current = ch
            else:
                current = trial
        if current:
            lines.append(current)
        return lines

    def _pct(value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "-"
        return f"{number * 100:.2f}".rstrip("0").rstrip(".") + "%"

    def _normalize_search_text(value: Any) -> str:
        return str(value or "").strip().lower().replace(" ", "")

    def _fetch_json_url(url: str, timeout: int = 10) -> Any:
        response = requests.get(url, timeout=timeout, headers={"Accept": "application/json,text/plain,*/*"})
        response.raise_for_status()
        text = response.text.replace("\x00", "").strip()
        return response.json() if text else {}

    def _load_shard_sources() -> Dict[str, Any]:
        cached = shard_cache.get("sources")
        if isinstance(cached, dict):
            return cached
        shard_data = _fetch_json_url(DEFAULT_SHARD_DATA_URL)
        hero_data = _fetch_json_url(DEFAULT_SHARD_HERO_URL)
        shards = shard_data if isinstance(shard_data, dict) else {}
        hero_list = hero_data.get("hero") if isinstance(hero_data, dict) else []
        champions = []
        if isinstance(hero_list, list):
            for item in hero_list:
                if not isinstance(item, dict):
                    continue
                alias = str(item.get("alias") or "").strip()
                if not alias:
                    continue
                champions.append(
                    {
                        "alias": alias,
                        "name": str(item.get("name") or "").strip(),
                        "title": str(item.get("title") or "").strip(),
                        "keywords": str(item.get("keywords") or "").strip(),
                    }
                )
        payload = {
            "shards": shards,
            "champions": champions,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        shard_cache.set("sources", payload)
        return payload

    def _find_shard_champion(query: str, champions: List[Dict[str, Any]], shards: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        needle = _normalize_search_text(query)
        if not needle:
            return None
        with_data = [hero for hero in champions if hero.get("alias") in shards]
        for hero in with_data:
            if needle in {
                _normalize_search_text(hero.get("alias")),
                _normalize_search_text(hero.get("title")),
                _normalize_search_text(hero.get("name")),
            }:
                return hero
        for hero in with_data:
            haystack = _normalize_search_text(",".join(str(hero.get(k) or "") for k in ("alias", "title", "name", "keywords")))
            if needle in haystack:
                return hero
        return None

    def _build_shard_payload(query: str) -> Dict[str, Any]:
        sources = _load_shard_sources()
        shards = sources.get("shards") if isinstance(sources.get("shards"), dict) else {}
        champions = sources.get("champions") if isinstance(sources.get("champions"), list) else []
        hero = _find_shard_champion(query, champions, shards)
        if not hero:
            raise HTTPException(status_code=404, detail=f"未找到英雄：{query}")
        stat = shards.get(hero.get("alias")) if isinstance(shards, dict) else None
        if not isinstance(stat, dict):
            raise HTTPException(status_code=404, detail=f"暂无 {hero.get('title') or hero.get('alias')} 的合集数据")
        rows = stat.get("shards") if isinstance(stat.get("shards"), list) else []
        clean_rows = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            clean_rows.append(
                {
                    "name": str(item.get("name") or item.get("id") or "未知合集").strip(),
                    "id": str(item.get("id") or "").strip(),
                    "pick_rate": item.get("pick_rate"),
                    "win_rate": item.get("win_rate"),
                }
            )
        clean_rows.sort(key=lambda row: float(row.get("pick_rate") or 0), reverse=True)
        return {
            "hero": hero,
            "query": query,
            "pick_rate": stat.get("pick_rate"),
            "win_rate": stat.get("win_rate"),
            "count": len(clean_rows),
            "rows": clean_rows,
            "source": "badspacebar",
            "updated_at": sources.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cache_expires_in": SHARD_CACHE_SECONDS,
        }

    def _download_hero_icon(alias: str) -> Optional[bytes]:
        cache_key = f"hero_icon:{alias}"
        cached = shard_cache.get(cache_key)
        if isinstance(cached, bytes):
            return cached
        for url in [
            f"https://game.gtimg.cn/images/lol/act/img/champion/{alias}.png",
            f"https://ddragon.leagueoflegends.com/cdn/15.12.1/img/champion/{alias}.png",
        ]:
            try:
                response = requests.get(url, timeout=5, headers={"Accept": "image/*,*/*"})
                if response.ok and response.content:
                    shard_cache.set(cache_key, response.content)
                    return response.content
            except Exception:
                continue
        return None

    def _build_shard_image_response(payload: Dict[str, Any]) -> Response:
        try:
            from PIL import Image, ImageDraw

            hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
            rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
            alias = str(hero.get("alias") or "")
            title = str(hero.get("title") or alias or "-")
            name = str(hero.get("name") or "")
            display_title = f"{title} - {name}" if name else title
            max_rows = min(len(rows), 24)
            width = 760
            padding = 26
            header_height = 244
            row_height = 46
            table_header_height = 44
            footer_height = 96
            height = header_height + table_header_height + max(max_rows, 1) * row_height + footer_height
            image = Image.new("RGB", (width, height), (22, 30, 55))
            draw = ImageDraw.Draw(image)
            title_font = _load_image_font(30, bold=True)
            metric_font = _load_image_font(18, bold=True)
            head_font = _load_image_font(17, bold=True)
            body_font = _load_image_font(17)
            small_font = _load_image_font(13)
            cyan = (27, 214, 238)
            green = (43, 174, 91)
            white = (242, 248, 255)
            muted = (166, 184, 207)
            row_bg = (20, 63, 106)
            row_alt = (19, 59, 99)
            line = (14, 47, 81)

            def fit_text(text: Any, font: Any, max_width: int) -> str:
                value = str(text or "")
                if not value:
                    return ""
                try:
                    if draw.textbbox((0, 0), value, font=font)[2] <= max_width:
                        return value
                    ellipsis = "..."
                    current = value
                    while current and draw.textbbox((0, 0), current + ellipsis, font=font)[2] > max_width:
                        current = current[:-1]
                    return (current + ellipsis) if current else ellipsis
                except Exception:
                    return value[: max(max_width // 12, 1)]

            draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=12, fill=(23, 34, 61), outline=(14, 94, 126), width=1)
            icon_size = 96
            icon_x = (width - icon_size) // 2
            icon_y = 46
            icon_bytes = _download_hero_icon(alias) if alias else None
            if icon_bytes:
                try:
                    icon = Image.open(io.BytesIO(icon_bytes)).convert("RGB").resize((icon_size, icon_size))
                    image.paste(icon, (icon_x, icon_y))
                except Exception:
                    draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_size, icon_y + icon_size), radius=8, fill=(18, 54, 92), outline=cyan, width=2)
            else:
                draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_size, icon_y + icon_size), radius=8, fill=(18, 54, 92), outline=cyan, width=2)
            draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_size, icon_y + icon_size), radius=8, outline=cyan, width=2)

            title_box = draw.textbbox((0, 0), display_title, font=title_font)
            draw.text(((width - (title_box[2] - title_box[0])) // 2, 154), display_title, fill=white, font=title_font)
            metrics = [
                ("总体选率", _pct(payload.get("pick_rate"))),
                ("总体胜率", _pct(payload.get("win_rate"))),
                ("合集数量", str(payload.get("count") or 0)),
            ]
            metric_text = "  ".join(f"{label}: {value}" for label, value in metrics)
            metric_box = draw.textbbox((0, 0), metric_text, font=metric_font)
            draw.text(((width - (metric_box[2] - metric_box[0])) // 2, 198), metric_text, fill=cyan, font=metric_font)
            draw.line((padding, header_height - 18, width - padding, header_height - 18), fill=(31, 64, 102), width=1)

            table_x = padding
            table_y = header_height + 8
            table_w = width - padding * 2
            draw.rounded_rectangle((table_x, table_y - 8, table_x + table_w, table_y + max(max_rows, 1) * row_height + 38), radius=7, fill=(20, 36, 68))
            columns = [("排名", table_x + 34), ("合集", table_x + 240), ("选率", table_x + 480), ("胜率", table_x + 616)]
            for label, x in columns:
                draw.text((x, table_y + 8), label, fill=cyan, font=head_font, anchor="mm")
            draw.line((table_x, table_y + 34, table_x + table_w, table_y + 34), fill=cyan, width=2)
            row_start = table_y + 36
            if not rows:
                draw.text((width // 2, row_start + 22), "暂无可用合集数据", fill=muted, font=body_font, anchor="mm")
            for idx, row in enumerate(rows[:max_rows], start=1):
                y = row_start + (idx - 1) * row_height
                draw.rectangle((table_x, y, table_x + table_w, y + row_height), fill=row_bg if idx % 2 else row_alt)
                draw.line((table_x, y + row_height, table_x + table_w, y + row_height), fill=line, width=1)
                draw.text((table_x + 34, y + 24), str(idx), fill=white, font=body_font, anchor="mm")
                draw.text((table_x + 240, y + 24), fit_text(row.get("name"), body_font, 260), fill=white, font=body_font, anchor="mm")
                draw.text((table_x + 480, y + 24), _pct(row.get("pick_rate")), fill=white, font=body_font, anchor="mm")
                draw.text((table_x + 616, y + 24), _pct(row.get("win_rate")), fill=green, font=body_font, anchor="mm")

            footer = f"本数据由 GroupGuardKing GGK 提供 | {payload.get('updated_at')}"
            footer_box = draw.textbbox((0, 0), footer, font=small_font)
            draw.text(((width - (footer_box[2] - footer_box[0])) // 2, height - 48), footer, fill=muted, font=small_font)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return Response(content=buffer.getvalue(), media_type="image/png")
        except Exception as exc:
            logger.exception("shard_query image generation failed: %s", exc)
            return JSONResponse(status_code=500, content={"error": f"合集图片生成失败: {exc}"})

    def _get_champion_lookup_sources() -> List[Dict[str, Any]]:
        cached = aram_augment_cache.get("champions")
        if isinstance(cached, list):
            return cached
        hero_data = _fetch_json_url(DEFAULT_SHARD_HERO_URL)
        hero_list = hero_data.get("hero") if isinstance(hero_data, dict) else []
        champions: List[Dict[str, Any]] = []
        if isinstance(hero_list, list):
            for item in hero_list:
                if not isinstance(item, dict):
                    continue
                alias = str(item.get("alias") or "").strip()
                if not alias:
                    continue
                champions.append(
                    {
                        "alias": alias,
                        "slug": alias.lower(),
                        "name": str(item.get("name") or "").strip(),
                        "title": str(item.get("title") or "").strip(),
                        "keywords": str(item.get("keywords") or "").strip(),
                        "heroId": str(item.get("heroId") or "").strip(),
                    }
                )
        aram_augment_cache.set("champions", champions)
        return champions

    def _find_champion_for_opgg(query: str) -> Optional[Dict[str, Any]]:
        needle = _normalize_search_text(query)
        if not needle:
            return None
        champions = _get_champion_lookup_sources()
        for hero in champions:
            if needle in {
                _normalize_search_text(hero.get("alias")),
                _normalize_search_text(hero.get("slug")),
                _normalize_search_text(hero.get("title")),
                _normalize_search_text(hero.get("name")),
            }:
                return hero
        for hero in champions:
            haystack = _normalize_search_text(",".join(str(hero.get(k) or "") for k in ("alias", "slug", "title", "name", "keywords")))
            if needle in haystack:
                return hero
        return None

    def _extract_json_array_after(decoded: str, marker: str) -> List[Dict[str, Any]]:
        start_marker = decoded.find(marker)
        if start_marker < 0:
            return []
        arr_start = decoded.find("[", start_marker)
        if arr_start < 0:
            return []
        depth = 0
        in_string = False
        escaped = False
        arr_end = -1
        for idx in range(arr_start, len(decoded)):
            ch = decoded[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        arr_end = idx + 1
                        break
        if arr_end < 0:
            return []
        try:
            data = json.loads(decoded[arr_start:arr_end])
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _extract_opgg_augments(html_text: str) -> List[Dict[str, Any]]:
        scripts = re.findall(r"self\.__next_f\.push\(\[1,\"(.*?)\"\]\)</script>", html_text, re.S)
        for raw_script in scripts:
            if '\\"data\\":[{\\"id\\"' not in raw_script or "largeIcon" not in raw_script:
                continue
            try:
                decoded = json.loads(f'"{raw_script}"')
            except Exception:
                continue
            data = _extract_json_array_after(decoded, '"data":')
            rows: List[Dict[str, Any]] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                icon = str(item.get("largeIcon") or item.get("smallIcon") or "").strip()
                if not name or not icon:
                    continue
                rows.append(
                    {
                        "name": name,
                        "icon": icon,
                        "rarity": item.get("rarity"),
                        "performance": item.get("performance"),
                        "popular": item.get("popular"),
                        "desc": re.sub(r"<[^>]+>", "", str(item.get("desc") or "")).strip(),
                    }
                )
            if rows:
                return rows
        return []

    def _extract_opgg_core_builds(html_text: str) -> List[Dict[str, Any]]:
        return _extract_opgg_item_rows(html_text, "core_items", limit=3, max_items=5)

    def _extract_opgg_item_rows(html_text: str, prefix: str, limit: int = 3, max_items: int = 5) -> List[Dict[str, Any]]:
        builds: List[Dict[str, Any]] = []
        seen = set()
        for idx in range(limit):
            key = f"{prefix}_{idx}"
            start = html_text.find(key)
            if start < 0:
                continue
            next_start = html_text.find(f"{prefix}_{idx + 1}", start + 1)
            row = html_text[start: next_start if next_start > start else start + 9000]
            items = []
            for item_id, src, name in re.findall(r'metaId\\":(\d+).*?src\\":\\"([^\\"]+)\\".*?alt\\":\\"([^\\"]+)\\"', row, re.S):
                items.append(
                    {
                        "id": item_id,
                        "name": name,
                        "icon": src,
                    }
                )
                if len(items) >= max_items:
                    break
            if not items:
                continue
            key = tuple(item.get("id") for item in items)
            if key in seen:
                continue
            seen.add(key)
            builds.append({"rank": idx + 1, "items": items})
        return builds

    def _extract_opgg_summoner_spells(html_text: str) -> List[Dict[str, str]]:
        marker = "SummonerSpells Table"
        start = html_text.find(marker)
        if start < 0:
            return []
        segment = html_text[start:start + 5000]
        spells = []
        seen = set()
        for src, name in re.findall(r'src="([^"]*/spell/Summoner[^"]+).*?alt="([^"]+)"', segment, re.S):
            clean_src = src.split("?image=", 1)[0]
            if clean_src in seen:
                continue
            seen.add(clean_src)
            spells.append({"name": name, "icon": clean_src})
            if len(spells) >= 2:
                break
        return spells

    def _extract_opgg_skill_order(html_text: str) -> List[Dict[str, str]]:
        marker = "SkillOrder Table"
        start = html_text.find(marker)
        if start < 0:
            return []
        segment = html_text[start:start + 18000]
        skills = []
        seen = set()

        for name, src, key in re.findall(r'<img alt="([^"]+)"[^>]+src="([^"]*/spell/[^"]+)".*?<strong[^>]*>([QWER])</strong>', segment, re.S):
            key_text = key.strip()
            if key_text in seen or key_text == "R":
                continue
            seen.add(key_text)
            skills.append({
                "key": key_text,
                "name": html.unescape(name),
                "icon": html.unescape(src).split("?image=", 1)[0],
            })
            if len(skills) >= 3:
                break
        if len(skills) >= 3:
            return skills

        for idx in range(3):
            key_marker = f"skill_{idx}"
            item_start = segment.find(key_marker)
            if item_start < 0:
                continue
            next_item = segment.find(f"skill_{idx + 1}", item_start + 1)
            part = segment[item_start: next_item if next_item > item_start else item_start + 2600]
            key_match = re.search(r'extraData\\?":\\?"([QWER])\\?"', part)
            icon_match = re.search(r'src\\?":\\?"([^"\\]+/spell/[^"\\]+)\\?".*?alt\\?":\\?"([^"\\]+)\\?"', part, re.S)
            if not key_match or not icon_match:
                continue
            key_text = key_match.group(1)
            if key_text in seen or key_text == "R":
                continue
            seen.add(key_text)
            skills.append({
                "key": key_text,
                "name": html.unescape(icon_match.group(2)),
                "icon": icon_match.group(1).split("?image=", 1)[0],
            })
            if len(skills) >= 3:
                break
        if len(skills) >= 3:
            return skills

        for src, name, key in re.findall(r'src\\?":\\?"([^"\\]+/spell/[^"\\]+)\\?".*?alt\\?":\\?"([^"\\]+)\\?".*?children\\?":\\?"([QWER])\\?"', segment, re.S):
            key_text = key.strip()
            if key_text in seen or key_text == "R":
                continue
            seen.add(key_text)
            skills.append({"key": key_text, "name": html.unescape(name), "icon": src.split("?image=", 1)[0]})
            if len(skills) >= 3:
                break
        return skills

    def _opgg_request(url: str) -> requests.Response:
        last_exc: Optional[Exception] = None
        for _ in range(2):
            try:
                return requests.get(
                    url,
                    timeout=25,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
            except Exception as exc:
                last_exc = exc
        raise last_exc or RuntimeError("OP.GG request failed")

    def _build_aram_augment_payload(query: str) -> Dict[str, Any]:
        hero = _find_champion_for_opgg(query)
        if not hero:
            raise HTTPException(status_code=404, detail=f"未找到英雄：{query}")
        slug_candidates = []
        for value in [hero.get("slug"), hero.get("alias")]:
            slug = str(value or "").strip().lower()
            if slug and slug not in slug_candidates:
                slug_candidates.append(slug)
        if hero.get("alias") == "MonkeyKing" and "wukong" not in slug_candidates:
            slug_candidates.insert(0, "wukong")

        last_error = ""
        rows: List[Dict[str, Any]] = []
        item_builds: List[Dict[str, Any]] = []
        starter_items: List[Dict[str, Any]] = []
        boots: List[Dict[str, Any]] = []
        summoner_spells: List[Dict[str, str]] = []
        skill_order: List[Dict[str, str]] = []
        used_url = ""
        for slug in slug_candidates:
            url = f"https://op.gg/zh-cn/lol/modes/aram-mayhem/{slug}/augments"
            try:
                response = _opgg_request(url)
                used_url = response.url
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}"
                    continue
                rows = _extract_opgg_augments(response.text)
                if rows:
                    break
                last_error = "页面中未找到强化符文数据"
            except Exception as exc:
                last_error = str(exc)
        if not rows:
            raise HTTPException(status_code=503, detail=f"OP.GG 强化符文数据不可用：{last_error or '未知错误'}")
        for slug in slug_candidates:
            build_url = f"https://op.gg/zh-cn/lol/modes/aram-mayhem/{slug}/build"
            try:
                response = _opgg_request(build_url)
                if response.status_code >= 400:
                    continue
                item_builds = _extract_opgg_core_builds(response.text)
                starter_items = _extract_opgg_item_rows(response.text, "starter_items", limit=2, max_items=3)
                boots = _extract_opgg_item_rows(response.text, "boots", limit=2, max_items=1)
                summoner_spells = _extract_opgg_summoner_spells(response.text)
                skill_order = _extract_opgg_skill_order(response.text)
                if item_builds or starter_items or boots or summoner_spells or skill_order:
                    break
            except Exception:
                continue
        top_rows = rows[:10]
        return {
            "hero": hero,
            "query": query,
            "rows": top_rows,
            "item_builds": item_builds,
            "starter_items": starter_items,
            "boots": boots,
            "summoner_spells": summoner_spells,
            "skill_order": skill_order,
            "total": len(rows),
            "source": "opgg",
            "source_url": used_url,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cache_expires_in": ARAM_AUGMENT_CACHE_SECONDS,
        }

    def _download_image_cached(cache: TTLCache, cache_key: str, url: str, timeout: int = 6) -> Optional[bytes]:
        cached = cache.get(cache_key)
        if isinstance(cached, bytes):
            return cached
        try:
            response = requests.get(url, timeout=timeout, headers={"Accept": "image/*,*/*", "User-Agent": "Mozilla/5.0"})
            if response.ok and response.content:
                cache.set(cache_key, response.content)
                return response.content
        except Exception:
            return None
        return None

    def _rarity_label(value: Any) -> str:
        try:
            rarity = int(value)
        except (TypeError, ValueError):
            return "-"
        return {1: "银", 2: "金", 3: "金", 4: "棱镜", 8: "金"}.get(rarity, str(rarity))

    def _build_aram_augment_image_response(payload: Dict[str, Any]) -> Response:
        try:
            from PIL import Image, ImageDraw

            hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
            rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
            item_builds = payload.get("item_builds") if isinstance(payload.get("item_builds"), list) else []
            starter_items = payload.get("starter_items") if isinstance(payload.get("starter_items"), list) else []
            boots = payload.get("boots") if isinstance(payload.get("boots"), list) else []
            summoner_spells = payload.get("summoner_spells") if isinstance(payload.get("summoner_spells"), list) else []
            skill_order = payload.get("skill_order") if isinstance(payload.get("skill_order"), list) else []
            alias = str(hero.get("alias") or "")
            title = str(hero.get("title") or alias or "-")
            name = str(hero.get("name") or "")
            display_title = f"{title} - {name}" if name else title
            width = 760
            padding = 26
            header_height = 190
            quick_height = 118 if (starter_items or boots or summoner_spells or skill_order) else 0
            build_height = 168 if item_builds else 0
            table_header_height = 44
            row_height = 50
            footer_height = 96
            section_gap = 18
            height = (
                header_height
                + quick_height
                + (section_gap if quick_height else 0)
                + build_height
                + (section_gap if build_height else 0)
                + table_header_height
                + max(len(rows), 1) * row_height
                + footer_height
            )
            image = Image.new("RGB", (width, height), (22, 30, 55))
            draw = ImageDraw.Draw(image)
            title_font = _load_image_font(30, bold=True)
            metric_font = _load_image_font(17, bold=True)
            head_font = _load_image_font(16, bold=True)
            body_font = _load_image_font(17)
            small_font = _load_image_font(13)
            tiny_font = _load_image_font(12)
            cyan = (27, 214, 238)
            green = (43, 174, 91)
            white = (242, 248, 255)
            muted = (166, 184, 207)
            row_bg = (20, 63, 106)
            row_alt = (19, 59, 99)
            line = (14, 47, 81)
            table_x = padding
            table_w = width - padding * 2

            def fit_text(text: Any, font: Any, max_width: int) -> str:
                value = str(text or "")
                try:
                    if draw.textbbox((0, 0), value, font=font)[2] <= max_width:
                        return value
                    ellipsis = "..."
                    current = value
                    while current and draw.textbbox((0, 0), current + ellipsis, font=font)[2] > max_width:
                        current = current[:-1]
                    return (current + ellipsis) if current else ellipsis
                except Exception:
                    return value[: max(max_width // 12, 1)]

            def paste_icon(icon_url: str, cache_prefix: str, x: int, y: int, size: int) -> None:
                icon_bytes = _download_image_cached(aram_augment_cache, f"{cache_prefix}:{icon_url}", icon_url) if icon_url else None
                if not icon_bytes:
                    return
                try:
                    icon = Image.open(io.BytesIO(icon_bytes)).convert("RGBA").resize((size, size))
                    image.paste(icon, (x, y), icon)
                except Exception:
                    pass

            def draw_icon_items(label: str, items: List[Dict[str, Any]], x: int, y: int, max_count: int = 4, key_field: str = "") -> None:
                draw.text((x, y), label, fill=muted, font=small_font)
                icon_x = x
                icon_y = y + 22
                if not items:
                    draw.text((icon_x, icon_y + 18), "-", fill=muted, font=body_font, anchor="lm")
                    return
                for item in items[:max_count]:
                    paste_icon(str(item.get("icon") or ""), "quick_icon", icon_x, icon_y, 36)
                    if key_field and item.get(key_field):
                        draw.rounded_rectangle((icon_x + 20, icon_y + 20, icon_x + 36, icon_y + 36), radius=4, fill=(14, 47, 81))
                        draw.text((icon_x + 28, icon_y + 28), str(item.get(key_field)), fill=white, font=tiny_font, anchor="mm")
                    icon_x += 42

            draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=12, fill=(23, 34, 61), outline=(14, 94, 126), width=1)
            icon_size = 82
            icon_x = (width - icon_size) // 2
            icon_y = 34
            icon_url = f"https://game.gtimg.cn/images/lol/act/img/champion/{alias}.png" if alias else ""
            icon_bytes = _download_image_cached(aram_augment_cache, f"champion_icon:{alias}", icon_url) if icon_url else None
            if icon_bytes:
                try:
                    icon = Image.open(io.BytesIO(icon_bytes)).convert("RGB").resize((icon_size, icon_size))
                    image.paste(icon, (icon_x, icon_y))
                except Exception:
                    draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_size, icon_y + icon_size), radius=8, fill=(18, 54, 92), outline=cyan, width=2)
            else:
                draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_size, icon_y + icon_size), radius=8, fill=(18, 54, 92), outline=cyan, width=2)
            draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_size, icon_y + icon_size), radius=8, outline=cyan, width=2)
            title_text = f"{display_title} 海符榜"
            title_box = draw.textbbox((0, 0), title_text, font=title_font)
            draw.text(((width - (title_box[2] - title_box[0])) // 2, 126), title_text, fill=white, font=title_font)
            sub = f"海克斯大乱斗 · 强化符文 Top {len(rows)} · 出装与技能速览"
            sub_box = draw.textbbox((0, 0), sub, font=metric_font)
            draw.text(((width - (sub_box[2] - sub_box[0])) // 2, 164), sub, fill=cyan, font=metric_font)

            cursor_y = header_height
            if quick_height:
                quick_y = cursor_y
                draw.rounded_rectangle((table_x, quick_y, table_x + table_w, quick_y + quick_height), radius=8, fill=(20, 42, 78), outline=(19, 81, 113), width=1)
                first_starter = starter_items[0].get("items") if starter_items and isinstance(starter_items[0].get("items"), list) else []
                first_boots = boots[0].get("items") if boots and isinstance(boots[0].get("items"), list) else []
                draw.text((table_x + 18, quick_y + 16), "对局速览", fill=cyan, font=head_font)
                draw_icon_items("召唤师技能", summoner_spells, table_x + 20, quick_y + 48, max_count=2)
                draw_icon_items("加点优先级", skill_order, table_x + 202, quick_y + 48, max_count=3, key_field="key")
                draw_icon_items("出门装", first_starter, table_x + 410, quick_y + 48, max_count=3)
                draw_icon_items("鞋子", first_boots, table_x + 598, quick_y + 48, max_count=1)
                cursor_y += quick_height + section_gap

            if item_builds:
                build_y = cursor_y
                draw.rounded_rectangle((table_x, build_y, table_x + table_w, build_y + build_height), radius=8, fill=(20, 36, 68))
                draw.text((table_x + 18, build_y + 14), "核心出装 Top 3", fill=cyan, font=head_font)
                row_y = build_y + 44
                for build in item_builds[:3]:
                    draw.rounded_rectangle((table_x + 14, row_y - 4, table_x + table_w - 14, row_y + 34), radius=6, fill=(20, 63, 106))
                    draw.text((table_x + 40, row_y + 16), str(build.get("rank") or ""), fill=white, font=body_font, anchor="mm")
                    x = table_x + 82
                    items = build.get("items") if isinstance(build.get("items"), list) else []
                    names = []
                    for item in items[:5]:
                        paste_icon(str(item.get("icon") or ""), "item_icon", x, row_y, 34)
                        names.append(str(item.get("name") or "").strip())
                        x += 42
                    draw.text((x + 8, row_y + 17), fit_text(" > ".join(n for n in names if n), small_font, table_x + table_w - x - 26), fill=muted, font=small_font, anchor="lm")
                    row_y += 39
                cursor_y += build_height + section_gap

            table_y = cursor_y
            draw.rounded_rectangle((table_x, table_y, table_x + table_w, table_y + table_header_height + max(len(rows), 1) * row_height), radius=8, fill=(20, 36, 68))
            draw.text((table_x + 18, table_y + 14), "强化符文 Top 10", fill=cyan, font=head_font)
            header_y = table_y + 40
            for label, x in [("排名", table_x + 34), ("强化符文", table_x + 250), ("品质", table_x + 500), ("推荐", table_x + 628)]:
                draw.text((x, header_y - 10), label, fill=muted, font=small_font, anchor="mm")
            draw.line((table_x, header_y + 6, table_x + table_w, header_y + 6), fill=cyan, width=2)
            row_start = table_y + table_header_height
            if not rows:
                draw.text((width // 2, row_start + 22), "暂无可用强化符文数据", fill=muted, font=body_font, anchor="mm")
            for idx, row in enumerate(rows, start=1):
                y = row_start + (idx - 1) * row_height
                draw.rectangle((table_x, y, table_x + table_w, y + row_height), fill=row_bg if idx % 2 else row_alt)
                draw.line((table_x, y + row_height, table_x + table_w, y + row_height), fill=line, width=1)
                paste_icon(str(row.get("icon") or ""), "augment_icon", table_x + 74, y + 7, 36)
                draw.text((table_x + 34, y + 25), str(idx), fill=white, font=body_font, anchor="mm")
                draw.text((table_x + 250, y + 25), fit_text(row.get("name"), body_font, 280), fill=white, font=body_font, anchor="mm")
                draw.text((table_x + 500, y + 25), _rarity_label(row.get("rarity")), fill=cyan, font=body_font, anchor="mm")
                perf = row.get("performance")
                perf_text = f"{float(perf):.2f}" if isinstance(perf, (int, float)) else "-"
                draw.text((table_x + 628, y + 25), perf_text, fill=green, font=body_font, anchor="mm")

            footer = f"数据由 GroupGuardKing GGK 整理提供 | {payload.get('updated_at')}"
            footer_box = draw.textbbox((0, 0), footer, font=small_font)
            footer_y = height - footer_height + 38
            draw.line((padding + 20, footer_y - 18, width - padding - 20, footer_y - 18), fill=(34, 53, 86), width=1)
            draw.text(((width - (footer_box[2] - footer_box[0])) // 2, footer_y), footer, fill=muted, font=small_font)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return Response(content=buffer.getvalue(), media_type="image/png")
        except Exception as exc:
            logger.exception("aram_augments image generation failed: %s", exc)
            return JSONResponse(status_code=500, content={"error": f"海符榜图片生成失败: {exc}"})

    def _build_cross_image_response(payload: Dict[str, Any]) -> Response:
        rows = payload.get("recent_matches") if isinstance(payload.get("recent_matches"), list) else []
        name_text = str(payload.get("name") or "-")
        region_text = str(payload.get("region") or "未指定")
        level_text = str(payload.get("level") if payload.get("level") is not None else "-")
        rank_text = str(payload.get("rank") or "未知")
        last_online = str(payload.get("last_online_time") or "未知")
        winrate = str(payload.get("winrate_recent") or "未知")
        avg_kda = payload.get("avg_kda_recent")
        avg_kda_text = f"{avg_kda:.2f}" if isinstance(avg_kda, (int, float)) else "未知"
        watermark = "战绩图由GroupGuardKing(GGK)生成"

        try:
            from PIL import Image, ImageDraw

            width = 1180
            padding = 44
            row_height = 112
            header_height = 282
            footer_height = 36
            height = header_height + max(len(rows[:10]), 1) * row_height + footer_height
            image = Image.new("RGB", (width, height), (246, 248, 251))
            draw = ImageDraw.Draw(image)
            title_font = _load_image_font(34, bold=True)
            label_font = _load_image_font(22, bold=True)
            body_font = _load_image_font(20)
            small_font = _load_image_font(18)
            tiny_font = _load_image_font(16)

            def fit_text(text: Any, font: Any, max_width: int) -> str:
                value = str(text or "")
                if not value:
                    return ""
                try:
                    if draw.textbbox((0, 0), value, font=font)[2] <= max_width:
                        return value
                    ellipsis = "..."
                    current = value
                    while current and draw.textbbox((0, 0), current + ellipsis, font=font)[2] > max_width:
                        current = current[:-1]
                    return (current + ellipsis) if current else ellipsis
                except Exception:
                    return value[: max(max_width // 12, 1)]

            def num_text(value: Any) -> str:
                number = _safe_int(value, 0)
                return f"{number:,}" if number else "0"

            draw.rounded_rectangle((22, 22, width - 22, height - 22), radius=18, fill=(255, 255, 255), outline=(218, 225, 235), width=2)
            draw.text((padding, 38), "战绩查询（跨区）", fill=(28, 36, 52), font=title_font)
            stat_x = width - 330
            draw.rounded_rectangle((stat_x, 82, width - padding, 196), radius=12, fill=(239, 246, 255), outline=(197, 218, 247))
            draw.text((stat_x + 22, 102), f"近10场胜率  {winrate}", fill=(24, 84, 154), font=label_font)
            draw.text((stat_x + 22, 146), f"平均 KDA    {avg_kda_text}", fill=(24, 84, 154), font=label_font)

            info_width = stat_x - padding - 30
            draw.text((padding, 92), fit_text(f"玩家：{name_text}", body_font, info_width), fill=(45, 54, 72), font=body_font)
            draw.text((padding, 128), fit_text(f"大区：{region_text}    等级：{level_text}", body_font, info_width), fill=(45, 54, 72), font=body_font)
            draw.text((padding, 164), fit_text(f"段位：{rank_text}", body_font, info_width), fill=(45, 54, 72), font=body_font)
            draw.text((padding, 200), fit_text(f"最后在线：{last_online}", small_font, info_width), fill=(93, 103, 122), font=small_font)

            y = header_height - 18
            draw.line((padding, y, width - padding, y), fill=(224, 229, 237), width=2)
            y += 20
            if not rows:
                draw.text((padding, y), "最近战绩：暂无可用数据", fill=(120, 128, 142), font=body_font)
            for idx, match in enumerate(rows[:10], start=1):
                if not isinstance(match, dict):
                    continue
                win = bool(match.get("win"))
                result = "胜" if win else "负"
                color = (22, 132, 75) if win else (190, 55, 65)
                champion = str(match.get("champion") or "-")
                game_time = str(match.get("game_time") or "-")
                kills = _safe_int(match.get("kills", 0))
                deaths = _safe_int(match.get("deaths", 0))
                assists = _safe_int(match.get("assists", 0))
                kda = match.get("kda")
                kda_text = f"{kda:.2f}" if isinstance(kda, (int, float)) else "-"
                queue = str(match.get("queue") or "")
                duration = _format_duration(match.get("duration"))
                position = str(match.get("position") or "")
                draw.text((padding, y), f"{idx}.", fill=(93, 103, 122), font=body_font)
                draw.text((padding + 42, y), result, fill=color, font=label_font)
                draw.text((padding + 88, y), fit_text(champion, label_font, 185), fill=(28, 36, 52), font=label_font)

                left_detail = f"{position}  {kills}/{deaths}/{assists}  KDA {kda_text}  {duration}".strip()
                draw.text((padding + 286, y + 2), fit_text(left_detail, body_font, 330), fill=(45, 54, 72), font=body_font)
                draw.text((padding + 630, y + 2), fit_text(queue, body_font, 170), fill=(45, 54, 72), font=body_font)
                draw.text((width - 222, y + 4), fit_text(game_time, tiny_font, 178), fill=(120, 128, 142), font=tiny_font)

                spell_text = " / ".join(str(x) for x in (match.get("spells") or [])[:2])
                rune_text = " / ".join(str(x) for x in (match.get("runes") or [])[:3])
                item_text = "、".join(str(x) for x in (match.get("items") or [])[:6])
                combat = (
                    f"伤害 {num_text(match.get('damage'))}  承伤 {num_text(match.get('damage_taken'))}  "
                    f"金币 {num_text(match.get('gold'))}  补刀 {num_text(match.get('cs'))}+{num_text(match.get('jungle_cs'))}  "
                    f"视野 {num_text(match.get('vision_score'))}"
                )
                draw.text((padding + 42, y + 36), fit_text(combat, small_font, width - padding * 2 - 42), fill=(93, 103, 122), font=small_font)
                more_parts = []
                if spell_text:
                    more_parts.append(f"技能 {spell_text}")
                if rune_text:
                    more_parts.append(f"符文 {rune_text}")
                if item_text:
                    more_parts.append(f"装备 {item_text}")
                draw.text((padding + 42, y + 66), fit_text("  ".join(more_parts), tiny_font, width - padding * 2 - 42), fill=(93, 103, 122), font=tiny_font)
                draw.line((padding + 42, y + row_height - 16, width - padding, y + row_height - 16), fill=(238, 242, 247), width=1)
                y += row_height

            watermark_box = draw.textbbox((0, 0), watermark, font=tiny_font)
            watermark_width = watermark_box[2] - watermark_box[0]
            draw.text((width - padding - watermark_width, height - 44), watermark, fill=(154, 164, 181), font=tiny_font)

            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return Response(content=buffer.getvalue(), media_type="image/png")
        except Exception as exc:
            logger.warning("cross_query image png generation failed, falling back to svg: %s", exc)

        return _build_cross_svg_response(payload)

    def _build_cross_svg_response(payload: Dict[str, Any]) -> Response:
        rows = payload.get("recent_matches") if isinstance(payload.get("recent_matches"), list) else []
        name_text = str(payload.get("name") or "-")
        region_text = str(payload.get("region") or "未指定")
        level_text = str(payload.get("level") if payload.get("level") is not None else "-")
        rank_text = str(payload.get("rank") or "未知")
        last_online = str(payload.get("last_online_time") or "未知")
        winrate = str(payload.get("winrate_recent") or "未知")
        avg_kda = payload.get("avg_kda_recent")
        avg_kda_text = f"{avg_kda:.2f}" if isinstance(avg_kda, (int, float)) else "未知"
        watermark = "战绩图由GroupGuardKing(GGK)生成"

        width = 1180
        padding = 44
        row_height = 112
        header_height = 282
        footer_height = 36
        height = header_height + max(len(rows[:10]), 1) * row_height + footer_height

        def esc(value: Any) -> str:
            return html.escape(str(value or ""))

        def clip(value: Any, max_len: int) -> str:
            text = str(value or "")
            return text if len(text) <= max_len else text[: max_len - 3] + "..."

        def num_text(value: Any) -> str:
            number = _safe_int(value, 0)
            return f"{number:,}" if number else "0"

        nodes = [
            f'<rect width="100%" height="100%" fill="#f6f8fb"/>',
            f'<rect x="22" y="22" width="{width - 44}" height="{height - 44}" rx="18" fill="#fff" stroke="#dae1eb" stroke-width="2"/>',
            f'<text x="{padding}" y="72" font-size="34" font-weight="700" fill="#1c2434">战绩查询（跨区）</text>',
            f'<rect x="{width - 330}" y="82" width="{330 - padding}" height="114" rx="12" fill="#eff6ff" stroke="#c5daf7"/>',
            f'<text x="{width - 308}" y="126" font-size="22" font-weight="700" fill="#18549a">近10场胜率  {esc(winrate)}</text>',
            f'<text x="{width - 308}" y="170" font-size="22" font-weight="700" fill="#18549a">平均 KDA    {esc(avg_kda_text)}</text>',
            f'<text x="{padding}" y="114" font-size="20" fill="#2d3648">玩家：{esc(name_text)}</text>',
            f'<text x="{padding}" y="150" font-size="20" fill="#2d3648">大区：{esc(region_text)}    等级：{esc(level_text)}</text>',
            f'<text x="{padding}" y="186" font-size="20" fill="#2d3648">段位：{esc(rank_text)}</text>',
            f'<text x="{padding}" y="222" font-size="18" fill="#5d677a">最后在线：{esc(last_online)}</text>',
            f'<line x1="{padding}" y1="{header_height - 18}" x2="{width - padding}" y2="{header_height - 18}" stroke="#e0e5ed" stroke-width="2"/>',
        ]
        if not rows:
            nodes.append(f'<text x="{padding}" y="{header_height + 24}" font-size="20" fill="#78808e">最近战绩：暂无可用数据</text>')

        y = header_height + 20
        for idx, match in enumerate(rows[:10], start=1):
            if not isinstance(match, dict):
                continue
            result = "胜" if match.get("win") else "负"
            result_color = "#16844b" if match.get("win") else "#be3741"
            kills = _safe_int(match.get("kills", 0))
            deaths = _safe_int(match.get("deaths", 0))
            assists = _safe_int(match.get("assists", 0))
            kda = match.get("kda")
            kda_text = f"{kda:.2f}" if isinstance(kda, (int, float)) else "-"
            detail = f"{match.get('position') or ''}  {kills}/{deaths}/{assists}  KDA {kda_text}"
            duration = _format_duration(match.get("duration"))
            spell_text = " / ".join(str(x) for x in (match.get("spells") or [])[:2])
            rune_text = " / ".join(str(x) for x in (match.get("runes") or [])[:3])
            item_text = "、".join(str(x) for x in (match.get("items") or [])[:6])
            combat = (
                f"伤害 {num_text(match.get('damage'))}  承伤 {num_text(match.get('damage_taken'))}  "
                f"金币 {num_text(match.get('gold'))}  补刀 {num_text(match.get('cs'))}+{num_text(match.get('jungle_cs'))}  "
                f"视野 {num_text(match.get('vision_score'))}"
            )
            more = "  ".join(part for part in [f"技能 {spell_text}" if spell_text else "", f"符文 {rune_text}" if rune_text else "", f"装备 {item_text}" if item_text else ""] if part)
            nodes.extend(
                [
                    f'<text x="{padding}" y="{y + 20}" font-size="20" fill="#5d677a">{idx}.</text>',
                    f'<text x="{padding + 42}" y="{y + 20}" font-size="22" font-weight="700" fill="{result_color}">{result}</text>',
                    f'<text x="{padding + 88}" y="{y + 20}" font-size="22" font-weight="700" fill="#1c2434">{esc(clip(match.get("champion") or "-", 8))}</text>',
                    f'<text x="{padding + 286}" y="{y + 20}" font-size="20" fill="#2d3648">{esc(clip(detail, 30))}</text>',
                    f'<text x="{padding + 548}" y="{y + 20}" font-size="20" fill="#2d3648">{esc(duration)}</text>',
                    f'<text x="{padding + 630}" y="{y + 20}" font-size="20" fill="#2d3648">{esc(clip(match.get("queue") or "", 8))}</text>',
                    f'<text x="{width - 222}" y="{y + 20}" font-size="16" fill="#78808e">{esc(match.get("game_time") or "-")}</text>',
                    f'<text x="{padding + 42}" y="{y + 56}" font-size="18" fill="#5d677a">{esc(clip(combat, 62))}</text>',
                    f'<text x="{padding + 42}" y="{y + 86}" font-size="16" fill="#5d677a">{esc(clip(more, 88))}</text>',
                    f'<line x1="{padding + 42}" y1="{y + row_height - 16}" x2="{width - padding}" y2="{y + row_height - 16}" stroke="#eef2f7"/>',
                ]
            )
            y += row_height

        nodes.append(f'<text x="{width - padding}" y="{height - 30}" text-anchor="end" font-size="16" fill="#9aa4b5">{esc(watermark)}</text>')
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>text {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }}</style>
{chr(10).join(nodes)}
</svg>'''
        return Response(content=svg.encode("utf-8"), media_type="image/svg+xml")

    async def _run_blocking(func, *args, **kwargs):
        """在线程池中执行阻塞型数据库或本地客户端调用。"""
        return await asyncio.to_thread(func, *args, **kwargs)

    @app.get("/query")
    async def query(name: str = Query(..., description="召唤师名称")):
        """常规战绩查询接口。"""
        name = name.strip()
        if not name:
            return JSONResponse(status_code=400, content={"error": "缺少参数 name"})
        db_instance = _ensure_db()
        if db_instance is None:
            return JSONResponse(status_code=503, content={"error": f"MySQL不可用: {db_error_message}"})
        logger.info("收到查询请求 name=%s", name)
        try:
            # Note: 本地 DB 操作和 LCU 调用目前仍为同步，为了避免阻塞事件循环，可以考虑放入线程池，这里暂时保持原样或简单封装
            # 为简单起见，这里假设它们执行很快
            summoner = await _run_blocking(db_instance.get_summoner_by_name, name)
            need_collect = True
            if summoner and summoner.get("last_update"):
                need_collect = _is_expired(summoner["last_update"])
            if need_collect:
                cache_key = f"collect:{name}"
                if not collect_cache.contains(cache_key):
                    logger.info("触发LCU采集 name=%s", name)
                    collector.db = db_instance
                    collected = await _run_blocking(collector.collect_player, name)
                    collect_cache.set(cache_key, True)
                    summoner_id = collected.get("summoner_id")
                    resolved_name = collected.get("name") or name
                else:
                    logger.info("命中采集缓存，跳过重复采集 name=%s", name)
                    resolved_name = name
                    summoner_id = None
            else:
                resolved_name = summoner.get("name", name)
                summoner_id = None
            newest = await _run_blocking(db_instance.get_summoner_by_name, resolved_name) or await _run_blocking(db_instance.get_summoner_by_name, name)
            puuid = newest.get("puuid") if newest else None
            recent_rows = await _run_blocking(db_instance.get_recent_matches_for_player, name=resolved_name, puuid=puuid, limit=10)
            if not recent_rows and resolved_name != name:
                recent_rows = await _run_blocking(db_instance.get_recent_matches_for_player, name=name, puuid=puuid, limit=10)
            recent_matches = _build_recent_matches(recent_rows)
            wins = sum(1 for item in recent_matches if item["win"])
            total = len(recent_matches)
            winrate = round((wins / total) * 100, 2) if total > 0 else 0.0
            rank = ""
            try:
                rank = await _run_blocking(lcu.get_rank, summoner_id)
            except (LCUConnectionError, Exception):
                rank = ""
            return {
                "name": resolved_name,
                "rank": rank,
                "winrate": f"{winrate}%",
                "recent_matches": recent_matches,
            }
        except LCUConnectionError as exc:
            logger.error("LCU连接异常: %s", exc)
            return JSONResponse(status_code=503, content={"error": str(exc)})
        except Exception as exc:
            logger.exception("查询失败 name=%s", name)
            return JSONResponse(status_code=500, content={"error": f"查询失败: {exc}"})

    @app.get("/hidden_query")
    async def hidden_query(name: str = Query(..., description="召唤师名称")):
        """隐藏战绩碎片还原接口。"""
        name = name.strip()
        if not name:
            return JSONResponse(status_code=400, content={"error": "缺少参数 name"})
        db_instance = _ensure_db()
        if db_instance is None:
            return JSONResponse(status_code=503, content={"error": f"MySQL不可用: {db_error_message}"})
        logger.info("收到隐藏战绩查询 name=%s", name)
        try:
            data = await _run_blocking(db_instance.get_hidden_query_data, name, 10)
            if int(data.get("found_matches") or 0) == 0 and "#" in name:
                base_name = name.split("#", 1)[0].strip()
                if base_name:
                    data = await _run_blocking(db_instance.get_hidden_query_data, base_name, 10)
            recent_matches = []
            for row in data.get("recent_matches", []):
                kills = int(row.get("kills") or 0)
                deaths = int(row.get("deaths") or 0)
                assists = int(row.get("assists") or 0)
                recent_matches.append(
                    {
                        "match_id": row.get("match_id"),
                        "game_time": row.get("game_time").strftime("%Y-%m-%d %H:%M:%S") if row.get("game_time") else "",
                        "champion": row.get("champion", ""),
                        "kda": _kda(kills, deaths, assists),
                        "win": bool(row.get("win")),
                    }
                )
            return {
                "found_matches": int(data.get("found_matches") or 0),
                "recent_heroes": [item.get("champion") for item in data.get("recent_heroes", [])],
                "kda_estimate": round(float(data.get("kda_estimate") or 0.0), 2),
                "recent_matches": recent_matches,
            }
        except Exception as exc:
            logger.exception("隐藏战绩查询失败 name=%s", name)
            return JSONResponse(status_code=500, content={"error": f"查询失败: {exc}"})

    @app.get("/health")
    async def health():
        """健康检查接口。"""
        db_instance = _ensure_db()
        so1_client = app.state.so1_client
        browser_ok = bool(so1_client._browser is not None and so1_client._browser.is_connected())
        return {
            "status": "ok",
            "mysql": "up" if db_instance else "down",
            "mysql_error": db_error_message if db_instance is None else "",
            "so1_browser": "up" if browser_ok else "down",
            "so1_max_concurrent_pages": getattr(so1_client, "_max_concurrent_pages", 0),
        }

    @app.get("/cross_query")
    async def cross_query(
        request: Request,
        name: str = Query(..., description="召唤师名称"),
        region: Optional[str] = Query(None, description="大区名称"),
        output: str = Query("pretty", description="输出格式：pretty 或 raw")
    ):
        """跨区查询接口（so1站点驱动）。"""
        name = name.strip()
        region_str = region.strip() if region else None
        output_format = output.strip().lower()
        region_key = region_str or "AUTO"
        if not name:
            return JSONResponse(status_code=400, content={"error": "缺少参数 name"})
            
        cache_key = f"cross:{name}:{region_key}:{output_format}"
        cache_hit, cache_ttl = cross_cache.get_with_remaining_ttl(cache_key)
        if isinstance(cache_hit, dict):
            cache_hit["source"] = "cache"
            cache_hit["cache_expires_in"] = cache_ttl
            if output_format == "image":
                return _build_cross_image_response(cache_hit)
            if output_format == "svg":
                return _build_cross_svg_response(cache_hit)
            return cache_hit
            
        logger.info("收到跨区查询请求 name=%s region=%s", name, region_str or "")
        db_instance = _ensure_db()
        upstream_error = ""
        try:
            client = request.app.state.so1_client
            # 异步调用 query_summoner
            raw = await client.query_summoner(name, region_name=region_str)
            basic = None
            rank = None
            history = None
            errors: List[Dict[str, Any]] = []

            def _consume(raw_payload: Dict[str, Any]) -> None:
                nonlocal basic
                nonlocal rank
                nonlocal history
                for url, payload in raw_payload.items():
                    data_obj = payload.get("data") if isinstance(payload, dict) else payload
                    success = bool(payload.get("success")) if isinstance(payload, dict) else data_obj is not None
                    if not success:
                        err = payload.get("error") if isinstance(payload, dict) else None
                        errors.append(
                            {
                                "endpoint": url,
                                "code": (err or {}).get("errCode") if isinstance(err, dict) else None,
                                "message": (err or {}).get("message") if isinstance(err, dict) else "查询失败",
                                "trace": (err or {}).get("trace") if isinstance(err, dict) else None,
                                "request": payload.get("_request") if isinstance(payload, dict) else None,
                            }
                        )
                    if "/customize-summoner-basic-by-name-region" in url and success:
                        basic = data_obj
                    elif "/origin-summoner-ranked-stats" in url and success:
                        rank = data_obj
                    elif "/customize-normal-match-history-simplified" in url and success:
                        history = data_obj

            _consume(raw)
            if basic is None and "#" in name:
                base_name = name.split("#", 1)[0].strip()
                if base_name:
                    fallback_raw = await client.query_summoner(base_name, region_name=region_str)
                    _consume(fallback_raw)
                    raw.update(fallback_raw)
                    
            pretty_payload = _build_cross_pretty(name=name, region=region_str or "", basic=basic, rank=rank, history=history, errors=errors)
            pretty_payload["source"] = "live"
            pretty_payload["is_stale"] = False
            pretty_payload["snapshot_updated_at"] = ""
            pretty_payload["cache_expires_in"] = CACHE_SECONDS
            raw_payload = {
                "name": name,
                "region": region_str or "",
                "basic": basic,
                "ranked": rank,
                "history": history,
                "raw_endpoint_count": len(raw),
                "errors": errors,
                "source": "live",
                "is_stale": False,
                "snapshot_updated_at": "",
                "cache_expires_in": CACHE_SECONDS,
            }
            response_payload = raw_payload if output_format == "raw" else pretty_payload
            cross_cache.set(cache_key, response_payload)
            if db_instance is not None:
                display_name = str((basic or {}).get("name") or (basic or {}).get("displayName") or name)
                await _run_blocking(
                    db_instance.upsert_cross_snapshot,
                    query_name=name,
                    region=region_key,
                    display_name=display_name,
                    payload_pretty=pretty_payload,
                    payload_raw=raw_payload,
                    is_success=True,
                    updated_at=datetime.now(),
                )
            if output_format == "image":
                return _build_cross_image_response(pretty_payload)
            if output_format == "svg":
                return _build_cross_svg_response(pretty_payload)
            return response_payload
        except So1ClientError as exc:
            upstream_error = str(exc)
            logger.error("跨区查询失败: %s", exc)
        except Exception as exc:
            upstream_error = str(exc)
            logger.exception("跨区查询异常 name=%s", name)
            
        snapshot = await _run_blocking(db_instance.get_cross_snapshot, query_name=name, region=region_key) if db_instance is not None else None
        if snapshot and bool(snapshot.get("is_success")):
            pretty_payload = snapshot.get("payload_pretty") if isinstance(snapshot.get("payload_pretty"), dict) else {}
            raw_payload = snapshot.get("payload_raw") if isinstance(snapshot.get("payload_raw"), dict) else None
            updated_at = snapshot.get("updated_at")
            updated_text = updated_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(updated_at, "strftime") else ""
            if not isinstance(pretty_payload, dict):
                pretty_payload = {}
            pretty_payload["source"] = "snapshot"
            pretty_payload["is_stale"] = True
            pretty_payload["snapshot_updated_at"] = updated_text
            pretty_payload["fallback_reason"] = upstream_error
            pretty_payload["cache_expires_in"] = CACHE_SECONDS
            if not isinstance(raw_payload, dict):
                raw_payload = {
                    "name": snapshot.get("query_name") or name,
                    "region": snapshot.get("region") or (region_str or ""),
                    "source": "snapshot",
                    "is_stale": True,
                    "snapshot_updated_at": updated_text,
                    "fallback_reason": upstream_error,
                    "cache_expires_in": CACHE_SECONDS,
                }
            else:
                raw_payload["source"] = "snapshot"
                raw_payload["is_stale"] = True
                raw_payload["snapshot_updated_at"] = updated_text
                raw_payload["fallback_reason"] = upstream_error
                raw_payload["cache_expires_in"] = CACHE_SECONDS
            response_payload = raw_payload if output_format == "raw" else pretty_payload
            cross_cache.set(cache_key, response_payload)
            if output_format == "image":
                return _build_cross_image_response(pretty_payload)
            if output_format == "svg":
                return _build_cross_svg_response(pretty_payload)
            return response_payload
            
        return JSONResponse(status_code=503, content={"error": f"跨区查询失败: {upstream_error or '未知错误'}"})

    @app.get("/shard_query")
    async def shard_query(
        hero: str = Query(..., description="英雄中文名、称号或英文名"),
        output: str = Query("image", description="输出格式：image 或 json")
    ):
        """英雄合集榜单查询。"""
        hero = hero.strip()
        output_format = output.strip().lower()
        if not hero:
            return JSONResponse(status_code=400, content={"error": "缺少参数 hero"})
        cache_key = f"shard:{hero}"
        cache_hit, cache_ttl = shard_cache.get_with_remaining_ttl(cache_key)
        if isinstance(cache_hit, dict):
            cache_hit["source"] = "cache"
            cache_hit["cache_expires_in"] = cache_ttl
            if output_format == "image":
                return await _run_blocking(_build_shard_image_response, cache_hit)
            return cache_hit
        try:
            payload = await _run_blocking(_build_shard_payload, hero)
            shard_cache.set(cache_key, payload)
            if output_format == "image":
                return await _run_blocking(_build_shard_image_response, payload)
            return payload
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
        except Exception as exc:
            logger.exception("合集查询失败 hero=%s", hero)
            return JSONResponse(status_code=503, content={"error": f"合集查询失败: {exc}"})

    @app.get("/aram_augments")
    async def aram_augments(
        hero: str = Query(..., description="英雄中文名、称号或英文名"),
        output: str = Query("image", description="输出格式：image 或 json")
    ):
        """海克斯大乱斗强化符文推荐榜。"""
        hero = hero.strip()
        output_format = output.strip().lower()
        if not hero:
            return JSONResponse(status_code=400, content={"error": "缺少参数 hero"})
        cache_key = f"aram_augments:{hero}"
        cache_hit, cache_ttl = aram_augment_cache.get_with_remaining_ttl(cache_key)
        if isinstance(cache_hit, dict):
            cache_hit["source"] = "cache"
            cache_hit["cache_expires_in"] = cache_ttl
            if output_format == "image":
                return await _run_blocking(_build_aram_augment_image_response, cache_hit)
            return cache_hit
        try:
            payload = await _run_blocking(_build_aram_augment_payload, hero)
            aram_augment_cache.set(cache_key, payload)
            if output_format == "image":
                return await _run_blocking(_build_aram_augment_image_response, payload)
            return payload
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
        except Exception as exc:
            logger.exception("海符榜查询失败 hero=%s", hero)
            return JSONResponse(status_code=503, content={"error": f"海符榜查询失败: {exc}"})

    @app.post("/cross_session_init")
    async def cross_session_init(request: Request, wait_seconds: int = Query(180)):
        """初始化so1登录会话（人工完成验证码时使用）。"""
        try:
            client = request.app.state.so1_client
            await client.bootstrap_manual_login(wait_seconds=wait_seconds)
            return {"status": "ok", "message": "so1会话初始化完成"}
        except So1ClientError as exc:
            logger.error("so1会话初始化失败: %s", exc)
            return JSONResponse(status_code=503, content={"error": str(exc)})
        except Exception as exc:
            logger.exception("so1会话初始化异常")
            return JSONResponse(status_code=500, content={"error": f"so1会话初始化失败: {exc}"})

    return app


if __name__ == "__main__":
    application = build_app()
    uvicorn.run(
        application,
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "5001")),
    )
