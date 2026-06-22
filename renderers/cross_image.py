import io
import logging
from typing import Any, Dict

from fastapi.responses import Response

from renderers.cross_svg import build_cross_svg_response
from renderers.image_utils import fit_text, load_image_font
from utils.convert import safe_int
from utils.time_utils import format_duration

logger = logging.getLogger("LOLDataSystem")


def build_cross_image_response(payload: Dict[str, Any]) -> Response:
    try:
        from PIL import Image, ImageDraw

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
        footer_height = 60
        height = header_height + max(len(rows[:10]), 1) * row_height + footer_height
        image = Image.new("RGB", (width, height), (246, 248, 251))
        draw = ImageDraw.Draw(image)
        title_font = load_image_font(34, bold=True)
        label_font = load_image_font(22, bold=True)
        body_font = load_image_font(20)
        small_font = load_image_font(18)
        tiny_font = load_image_font(16)

        def num_text(value: Any) -> str:
            number = safe_int(value, 0)
            return f"{number:,}" if number else "0"

        draw.rounded_rectangle((22, 22, width - 22, height - 22), radius=18, fill=(255, 255, 255), outline=(218, 225, 235), width=2)
        draw.text((padding, 38), "战绩查询（跨区）", fill=(28, 36, 52), font=title_font)
        stat_x = width - 330
        draw.rounded_rectangle((stat_x, 82, width - padding, 196), radius=12, fill=(239, 246, 255), outline=(197, 218, 247))
        draw.text((stat_x + 22, 102), f"近10场胜率  {winrate}", fill=(24, 84, 154), font=label_font)
        draw.text((stat_x + 22, 146), f"平均 KDA    {avg_kda_text}", fill=(24, 84, 154), font=label_font)

        info_width = stat_x - padding - 30
        draw.text((padding, 92), fit_text(draw, f"玩家：{name_text}", body_font, info_width), fill=(45, 54, 72), font=body_font)
        draw.text((padding, 128), fit_text(draw, f"大区：{region_text}    等级：{level_text}", body_font, info_width), fill=(45, 54, 72), font=body_font)
        draw.text((padding, 164), fit_text(draw, f"段位：{rank_text}", body_font, info_width), fill=(45, 54, 72), font=body_font)
        draw.text((padding, 200), fit_text(draw, f"最后在线：{last_online}", small_font, info_width), fill=(93, 103, 122), font=small_font)

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
            kills = safe_int(match.get("kills", 0))
            deaths = safe_int(match.get("deaths", 0))
            assists = safe_int(match.get("assists", 0))
            kda = match.get("kda")
            kda_text = f"{kda:.2f}" if isinstance(kda, (int, float)) else "-"
            queue = str(match.get("queue") or "")
            duration = format_duration(match.get("duration"))
            position = str(match.get("position") or "")
            draw.text((padding, y), f"{idx}.", fill=(93, 103, 122), font=body_font)
            draw.text((padding + 42, y), result, fill=color, font=label_font)
            draw.text((padding + 88, y), fit_text(draw, champion, label_font, 185), fill=(28, 36, 52), font=label_font)

            left_detail = f"{position}  {kills}/{deaths}/{assists}  KDA {kda_text}  {duration}".strip()
            draw.text((padding + 286, y + 2), fit_text(draw, left_detail, body_font, 330), fill=(45, 54, 72), font=body_font)
            draw.text((padding + 630, y + 2), fit_text(draw, queue, body_font, 170), fill=(45, 54, 72), font=body_font)
            draw.text((width - 222, y + 4), fit_text(draw, game_time, tiny_font, 178), fill=(120, 128, 142), font=tiny_font)

            spell_text = " / ".join(str(x) for x in (match.get("spells") or [])[:2])
            rune_text = " / ".join(str(x) for x in (match.get("runes") or [])[:3])
            item_text = "、".join(str(x) for x in (match.get("items") or [])[:6])
            combat = (
                f"伤害 {num_text(match.get('damage'))}  承伤 {num_text(match.get('damage_taken'))}  "
                f"金币 {num_text(match.get('gold'))}  补刀 {num_text(match.get('cs'))}+{num_text(match.get('jungle_cs'))}  "
                f"视野 {num_text(match.get('vision_score'))}"
            )
            draw.text((padding + 42, y + 36), fit_text(draw, combat, small_font, width - padding * 2 - 42), fill=(93, 103, 122), font=small_font)
            more_parts = []
            if spell_text:
                more_parts.append(f"技能 {spell_text}")
            if rune_text:
                more_parts.append(f"符文 {rune_text}")
            if item_text:
                more_parts.append(f"装备 {item_text}")
            draw.text((padding + 42, y + 66), fit_text(draw, "  ".join(more_parts), tiny_font, width - padding * 2 - 42), fill=(93, 103, 122), font=tiny_font)
            draw.line((padding + 42, y + row_height - 16, width - padding, y + row_height - 16), fill=(238, 242, 247), width=1)
            y += row_height

        try:
            watermark_box = draw.textbbox((0, 0), watermark, font=tiny_font)
            watermark_width = watermark_box[2] - watermark_box[0]
        except Exception:
            watermark_width = 260
        draw.text((width - padding - watermark_width, height - 44), watermark, fill=(154, 164, 181), font=tiny_font)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return Response(content=buffer.getvalue(), media_type="image/png")
    except Exception as exc:
        logger.warning("cross_query image png generation failed, falling back to svg: %s", exc)
        return build_cross_svg_response(payload)
