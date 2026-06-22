import html
from typing import Any, Dict

from fastapi.responses import Response

from utils.convert import safe_int
from utils.time_utils import format_duration


def build_cross_svg_response(payload: Dict[str, Any]) -> Response:
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
        number = safe_int(value, 0)
        return f"{number:,}" if number else "0"

    nodes = [
        '<rect width="100%" height="100%" fill="#f6f8fb"/>',
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
        kills = safe_int(match.get("kills", 0))
        deaths = safe_int(match.get("deaths", 0))
        assists = safe_int(match.get("assists", 0))
        kda = match.get("kda")
        kda_text = f"{kda:.2f}" if isinstance(kda, (int, float)) else "-"
        detail = f"{match.get('position') or ''}  {kills}/{deaths}/{assists}  KDA {kda_text}"
        duration = format_duration(match.get("duration"))
        spell_text = " / ".join(str(x) for x in (match.get("spells") or [])[:2])
        rune_text = " / ".join(str(x) for x in (match.get("runes") or [])[:3])
        item_text = "、".join(str(x) for x in (match.get("items") or [])[:6])
        combat = (
            f"伤害 {num_text(match.get('damage'))}  承伤 {num_text(match.get('damage_taken'))}  "
            f"金币 {num_text(match.get('gold'))}  补刀 {num_text(match.get('cs'))}+{num_text(match.get('jungle_cs'))}  "
            f"视野 {num_text(match.get('vision_score'))}"
        )
        more = "  ".join(
            part
            for part in [
                f"技能 {spell_text}" if spell_text else "",
                f"符文 {rune_text}" if rune_text else "",
                f"装备 {item_text}" if item_text else "",
            ]
            if part
        )
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
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">' + "".join(nodes) + "</svg>"
    return Response(content=svg.encode("utf-8"), media_type="image/svg+xml; charset=utf-8")
