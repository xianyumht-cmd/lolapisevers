import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests


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
    1750: "斗魂竞技场",
    1900: "无限火力",
    2400: "海克斯乱斗",
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

SPELL_NAMES = {
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


def resolve_region_display(region: str, basic_obj: Dict[str, Any], history_list: List[Dict[str, Any]]) -> str:
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


def load_gtimg(path: str) -> Dict[str, Any]:
    resp = requests.get(f"https://game.gtimg.cn{path}", timeout=10)
    resp.raise_for_status()
    text = resp.text.strip().lstrip("\ufeff")
    try:
        return resp.json()
    except Exception:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        return json.loads(match.group(0))


def get_static_lol_data(cache=None, logger: Optional[logging.Logger] = None) -> Dict[str, Dict[str, str]]:
    if cache is not None:
        cached = cache.get("lol_static_zh_cn")
        if isinstance(cached, dict):
            return cached
    log = logger or logging.getLogger("LOLDataSystem")
    result: Dict[str, Dict[str, str]] = {"champions": {}, "items": {}, "spells": {}, "runes": {}}
    try:
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

        result["spells"].update(SPELL_NAMES)
        if cache is not None:
            cache.set("lol_static_zh_cn", result)
    except Exception as exc:
        log.warning("failed to load lolso gtimg static data: %s", exc)
    return result


def queue_display(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        queue_id = int(value)
        return QUEUE_NAMES.get(queue_id, str(queue_id))
    except (TypeError, ValueError):
        text = str(value)
        return RANK_QUEUE_NAMES.get(text, text)


def rank_display(queue: Dict[str, Any]) -> str:
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


def format_last_online(basic_obj: Dict[str, Any]) -> str:
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
