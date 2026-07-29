from __future__ import annotations

from typing import Any, Dict, Mapping


def _text(value: Any, fallback: str = "-") -> str:
    rendered = str(value or "").strip()
    return rendered or fallback


def format_hidden_text(payload: Mapping[str, Any]) -> str:
    rows = payload.get("recent_matches") if isinstance(payload.get("recent_matches"), list) else []
    rows = [row for row in rows[:10] if isinstance(row, Mapping)]
    heroes = []
    for row in rows:
        champion = _text(row.get("champion"), "")
        if champion and champion not in heroes:
            heroes.append(champion)
    found = len(rows)
    lines = [
        f"隐藏战绩｜{_text(payload.get('name'), '未知召唤师')}",
        f"大区：{_text(payload.get('region'), '未指定')}",
        f"等级：{_text(payload.get('level'))}",
        f"单双排/当前段位：{_text(payload.get('rank'), '未定级')}",
        f"最后在线：{_text(payload.get('last_online_time'), '未知')}",
        f"识别场次：{found}",
        f"近场胜率：{_text(payload.get('winrate_recent'), '未知')}",
        f"估算平均 KDA：{_text(payload.get('avg_kda_recent'), '未知')}",
        f"近期英雄：{'、'.join(heroes[:8]) if heroes else '暂无'}",
    ]
    if rows:
        lines.append("")
        lines.append("近期隐藏战绩碎片：")
        for index, row in enumerate(rows[:5], start=1):
            result = "胜" if bool(row.get("win")) else "负"
            lines.append(
                f"{index}. {_text(row.get('champion'), '未知英雄')}｜{result}｜"
                f"{_text(row.get('kills'), '0')}/{_text(row.get('deaths'), '0')}/{_text(row.get('assists'), '0')}"
            )
    else:
        lines.extend(["", "暂无可用隐藏战绩碎片"])
    if bool(payload.get("is_stale")) or str(payload.get("source") or "") == "snapshot":
        lines.extend([
            "",
            f"数据状态：上游暂不可用，正在使用历史快照（{_text(payload.get('snapshot_updated_at'), '时间未知')}）",
        ])
    return "\n".join(lines).strip()


def hidden_meta(payload: Mapping[str, Any]) -> Dict[str, Any]:
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
        },
    }
