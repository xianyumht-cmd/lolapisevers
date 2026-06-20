import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
import uvicorn

from cache import TTLCache
from collector import DataCollector
from db import Database
from lcu_client import LCUClient, LCUConnectionError
from so1_client import So1Client, So1ClientError


CACHE_SECONDS = 300

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
            recent_matches.append(
                {
                    "game_time": _format_ts_ms(item.get("gameCreation")),
                    "champion": player.get("championName") or player.get("champion") or player.get("championId") or "",
                    "kills": kills,
                    "deaths": deaths,
                    "assists": assists,
                    "kda": round((kills + assists) / max(deaths, 1), 2),
                    "win": bool(player.get("win", stats.get("win", False))),
                    "duration": _safe_int(item.get("gameDuration", 0)),
                    "queue": item.get("queueType") or item.get("queueId") or item.get("gameMode") or "",
                }
            )
        wins = sum(1 for m in recent_matches if m.get("win"))
        total = len(recent_matches)
        winrate = round((wins / total) * 100, 2) if total else 0.0
        avg_kda = round(sum(m["kda"] for m in recent_matches) / total, 2) if total else 0.0
        rank_text = ""
        queues = rank_obj.get("queues") if isinstance(rank_obj.get("queues"), list) else []
        queue_pick = None
        for queue_type in ("RANKED_SOLO_5x5", "RANKED_FLEX_SR"):
            for q in queues:
                if isinstance(q, dict) and q.get("queueType") == queue_type:
                    queue_pick = q
                    break
            if queue_pick:
                break
        if not queue_pick and queues:
            queue_pick = queues[0] if isinstance(queues[0], dict) else None
        if queue_pick:
            tier = queue_pick.get("tier") or ""
            division = queue_pick.get("rank") or queue_pick.get("division") or ""
            lp = queue_pick.get("leaguePoints")
            if tier:
                rank_text = f"{tier} {division} {lp}LP".strip() if lp is not None else f"{tier} {division}".strip()
                # 去除多余空格
                rank_text = " ".join(rank_text.split())
        display_name = basic_obj.get("name") or basic_obj.get("displayName") or name
        return {
            "name": display_name,
            "region": region,
            "level": _safe_int(basic_obj.get("level", 0)),
            "profile_icon": _safe_int(basic_obj.get("profileIconId", 0)),
            "rank": rank_text,
            "last_online_time": _format_last_online(basic_obj),
            "winrate_recent": f"{winrate}%",
            "avg_kda_recent": avg_kda,
            "recent_matches": recent_matches,
            "errors": errors,
            "raw_ok": basic is not None or history is not None or rank is not None,
        }

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
            response_payload = pretty_payload if output_format != "raw" else raw_payload
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
            response_payload = pretty_payload if output_format != "raw" else raw_payload
            cross_cache.set(cache_key, response_payload)
            return response_payload
            
        return JSONResponse(status_code=503, content={"error": f"跨区查询失败: {upstream_error or '未知错误'}"})

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
