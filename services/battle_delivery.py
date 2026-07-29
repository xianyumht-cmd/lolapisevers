from __future__ import annotations

from typing import Any, Dict, Mapping

from utils.time_utils import format_duration


def _text(value: Any, fallback: str = "-") -> str:
    rendered = str(value or "").strip()
    return rendered or fallback


def _number(value: Any, fallback: str = "-") -> str:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return str(value)
    rendered = str(value or "").strip()
    return rendered or fallback


def format_battle_text(payload: Mapping[str, Any]) -> str:
    rows = payload.get("recent_matches") if isinstance(payload.get("recent_matches"), list) else []
    rows = [row for row in rows[:10] if isinstance(row, Mapping)]
    lines = [
        f"战绩查询｜{_text(payload.get('name'), '未知召唤师')}",
        f"大区：{_text(payload.get('region'), '未指定')}",
        f"等级：{_number(payload.get('level'))}",
        f"段位：{_text(payload.get('rank'), '未定级')}",
        f"近期胜率：{_text(payload.get('winrate_recent'), '未知')}",
        f"近期平均 KDA：{_number(payload.get('avg_kda_recent'))}",
        f"最后在线：{_text(payload.get('last_online_time'), '未知')}",
        "",
    ]
    if not rows:
        lines.append("暂无可用对局记录")
    for index, row in enumerate(rows, start=1):
        result = "胜利" if bool(row.get("win")) else "失败"
        champion = _text(row.get("champion"), "未知英雄")
        kills = _number(row.get("kills"), "0")
        deaths = _number(row.get("deaths"), "0")
        assists = _number(row.get("assists"), "0")
        kda = _number(row.get("kda"), "0")
        queue = _text(row.get("queue"), "未知模式")
        duration = format_duration(row.get("duration"))
        game_time = _text(row.get("game_time"), "未知时间")
        lines.append(
            f"{index}. {result}｜{champion}｜{kills}/{deaths}/{assists}｜KDA {kda}"
        )
        lines.append(f"   {queue}｜{duration}｜{game_time}")

    if bool(payload.get("is_stale")) or str(payload.get("source") or "") == "snapshot":
        updated = _text(payload.get("snapshot_updated_at"), "最近有效时间未知")
        lines.extend(["", f"数据状态：上游暂不可用，正在使用历史快照（{updated}）"])
    return "\n".join(lines).strip()


def battle_meta(payload: Mapping[str, Any], *, delivery_fallback: str = "") -> Dict[str, Any]:
    rows = payload.get("recent_matches") if isinstance(payload.get("recent_matches"), list) else []
    return {
        "source": str(payload.get("source") or ""),
        "stale": bool(payload.get("is_stale") or str(payload.get("source") or "") == "snapshot"),
        "updated_at": str(payload.get("snapshot_updated_at") or ""),
        "cache_expires_in": int(payload.get("cache_expires_in") or 0),
        "count": len(rows),
        "player": {
            "name": str(payload.get("name") or ""),
            "region": str(payload.get("region") or ""),
            "rank": str(payload.get("rank") or ""),
        },
        "delivery_fallback": str(delivery_fallback or ""),
    }
