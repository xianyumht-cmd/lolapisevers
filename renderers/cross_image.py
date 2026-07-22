import io
import logging
from typing import Any, Dict, List, Optional

from fastapi.responses import Response

from core.context import AppContext
from renderers.cross_svg import build_cross_svg_response
from renderers.image_utils import (
    encode_png_limited,
    fit_text,
    image_footer_left,
    image_footer_right,
    load_image_font,
    prefetch_image_urls,
)
from utils.convert import safe_int
from utils.time_utils import format_duration

logger = logging.getLogger("LOLDataSystem")

CDRAGON_BASE = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1"
GTIMG_BASE = "https://game.gtimg.cn/images/lol/act/img"


def _profile_icon_url(profile_icon_id: Any) -> str:
    icon_id = safe_int(profile_icon_id, 0)
    return f"{GTIMG_BASE}/profileicon/{icon_id}.png" if icon_id else ""


def _champion_icon_url(champion_id: Any) -> str:
    icon_id = safe_int(champion_id, 0)
    return f"{CDRAGON_BASE}/champion-icons/{icon_id}.png" if icon_id else ""


def _item_icon_url(item_id: Any) -> str:
    icon_id = safe_int(item_id, 0)
    return f"{GTIMG_BASE}/item/{icon_id}.png" if icon_id else ""


def build_cross_image_response(ctx: AppContext, payload: Dict[str, Any]) -> Response:
    try:
        from PIL import Image, ImageDraw, ImageOps

        rows = payload.get("recent_matches") if isinstance(payload.get("recent_matches"), list) else []
        rows = [row for row in rows[:10] if isinstance(row, dict)]
        ranked_queues = payload.get("ranked_queues") if isinstance(payload.get("ranked_queues"), list) else []
        ranked_queues = [row for row in ranked_queues[:2] if isinstance(row, dict)]
        name_text = str(payload.get("name") or "-")
        region_text = str(payload.get("region") or "未指定")
        level_text = str(payload.get("level") if payload.get("level") is not None else "-")
        rank_text = str(payload.get("rank") or "未定级")
        last_online = str(payload.get("last_online_time") or "未知")
        winrate = str(payload.get("winrate_recent") or "未知")
        avg_kda = payload.get("avg_kda_recent")
        avg_kda_text = f"{avg_kda:.2f}" if isinstance(avg_kda, (int, float)) else "未知"
        source_text = "历史快照" if payload.get("is_stale") else "实时数据"

        width = 980
        outer = 22
        header_height = 176
        section_height = 54
        row_height = 94
        row_gap = 8
        footer_height = 54
        row_count = max(len(rows), 1)
        height = (
            outer
            + header_height
            + 14
            + section_height
            + row_count * row_height
            + max(row_count - 1, 0) * row_gap
            + footer_height
            + outer
        )

        bg = (13, 17, 30)
        panel = (24, 30, 49)
        panel_soft = (28, 36, 58)
        text = (240, 244, 251)
        muted = (156, 168, 188)
        cyan = (69, 207, 224)
        green = (52, 211, 153)
        red = (248, 113, 113)
        gold = (245, 192, 84)
        line = (47, 58, 82)

        image = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(image)
        title_font = load_image_font(29, bold=True)
        heading_font = load_image_font(18, bold=True)
        result_font = load_image_font(17, bold=True)
        body_font = load_image_font(15)
        body_bold_font = load_image_font(15, bold=True)
        small_font = load_image_font(13)
        tiny_font = load_image_font(11)
        kda_font = load_image_font(19, bold=True)

        profile_url = _profile_icon_url(payload.get("profile_icon"))
        asset_urls: List[str] = [profile_url] if profile_url else []
        for match in rows:
            champion_url = _champion_icon_url(match.get("champion_id"))
            if champion_url:
                asset_urls.append(champion_url)
            for item_id in [x for x in (match.get("item_ids") or []) if safe_int(x, 0)][:6]:
                item_url = _item_icon_url(item_id)
                if item_url:
                    asset_urls.append(item_url)
        asset_cache = getattr(ctx, "image_asset_cache", getattr(ctx, "aram_augment_cache", None))
        assets = prefetch_image_urls(asset_cache, asset_urls, timeout=3.5, max_workers=8, max_assets=72)

        def paste_icon(
            url: str,
            x: int,
            y: int,
            size: int,
            *,
            radius: int = 7,
            border: Optional[tuple] = None,
            placeholder: str = "",
        ) -> None:
            icon_bytes = assets.get(url)
            if icon_bytes:
                try:
                    icon = Image.open(io.BytesIO(icon_bytes)).convert("RGBA")
                    icon = ImageOps.fit(icon, (size, size), method=Image.Resampling.LANCZOS)
                    mask = Image.new("L", (size, size), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
                    image.paste(icon, (x, y), mask)
                except Exception:
                    icon_bytes = None
            if not icon_bytes:
                draw.rounded_rectangle((x, y, x + size, y + size), radius=radius, fill=(41, 51, 76))
                if placeholder:
                    draw.text(
                        (x + size // 2, y + size // 2),
                        placeholder[:1],
                        fill=muted,
                        font=heading_font,
                        anchor="mm",
                    )
            if border:
                draw.rounded_rectangle((x, y, x + size, y + size), radius=radius, outline=border, width=2)

        def pill(x: int, y: int, value: str, fill: tuple, foreground: tuple = text, width_hint: int = 0) -> int:
            try:
                box = draw.textbbox((0, 0), value, font=small_font)
                measured = box[2] - box[0]
            except Exception:
                measured = len(value) * 13
            pill_width = max(width_hint, measured + 22)
            draw.rounded_rectangle((x, y, x + pill_width, y + 26), radius=13, fill=fill)
            draw.text((x + pill_width // 2, y + 13), value, fill=foreground, font=small_font, anchor="mm")
            return pill_width

        draw.rounded_rectangle(
            (outer, outer, width - outer, outer + header_height),
            radius=16,
            fill=panel,
            outline=line,
            width=1,
        )
        avatar_x = outer + 22
        avatar_y = outer + 26
        paste_icon(profile_url, avatar_x, avatar_y, 88, radius=12, border=cyan, placeholder=name_text)
        draw.rounded_rectangle((avatar_x + 54, avatar_y + 68, avatar_x + 92, avatar_y + 94), radius=12, fill=(13, 150, 139))
        draw.text((avatar_x + 73, avatar_y + 81), f"Lv{level_text}", fill=text, font=tiny_font, anchor="mm")

        name_x = avatar_x + 112
        draw.text((name_x, outer + 28), fit_text(draw, name_text, title_font, 400), fill=text, font=title_font)
        draw.text((name_x, outer + 70), fit_text(draw, region_text, body_font, 400), fill=muted, font=body_font)
        draw.text((name_x, outer + 98), fit_text(draw, f"当前段位：{rank_text}", small_font, 400), fill=(197, 207, 224), font=small_font)
        pill_x = name_x
        pill_x += pill(pill_x, outer + 126, f"近10场 {winrate}", (31, 85, 83), green) + 8
        pill_x += pill(pill_x, outer + 126, f"平均KDA {avg_kda_text}", (42, 63, 94), cyan) + 8
        pill(pill_x, outer + 126, source_text, (57, 48, 79), gold)

        card_w = 176
        card_h = 88
        rank_start_x = width - outer - 22 - card_w * 2 - 12
        queue_defaults = [
            {"queue_name": "单双排", "rank": rank_text, "wins": 0, "losses": 0},
            {"queue_name": "灵活组排", "rank": "未定级", "wins": 0, "losses": 0},
        ]
        display_queues = ranked_queues + queue_defaults[len(ranked_queues):]
        for idx, queue in enumerate(display_queues[:2]):
            x = rank_start_x + idx * (card_w + 12)
            y = outer + 42
            draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=12, fill=panel_soft, outline=(55, 68, 95))
            draw.text((x + 14, y + 14), str(queue.get("queue_name") or "排位"), fill=muted, font=small_font)
            draw.text((x + 14, y + 40), fit_text(draw, queue.get("rank") or "未定级", body_bold_font, card_w - 28), fill=text, font=body_bold_font)
            wins = safe_int(queue.get("wins"), 0)
            losses = safe_int(queue.get("losses"), 0)
            draw.text((x + 14, y + 66), f"{wins}胜  {losses}负", fill=cyan, font=tiny_font)

        section_y = outer + header_height + 14
        draw.rounded_rectangle((outer, section_y, width - outer, section_y + section_height), radius=13, fill=panel)
        draw.text((outer + 20, section_y + 17), "近期战绩", fill=text, font=heading_font)
        draw.text((outer + 122, section_y + 19), f"最近{len(rows)}场 · 最后在线 {last_online}", fill=muted, font=small_font)

        rows_y = section_y + section_height
        if not rows:
            draw.rounded_rectangle((outer, rows_y, width - outer, rows_y + row_height), radius=13, fill=panel, outline=line)
            draw.text((width // 2, rows_y + row_height // 2), "暂无可用战绩数据", fill=muted, font=heading_font, anchor="mm")
        for index, match in enumerate(rows):
            y = rows_y + index * (row_height + row_gap)
            win = bool(match.get("win"))
            accent = green if win else red
            card_fill = (27, 55, 55) if win else (62, 42, 49)
            draw.rounded_rectangle((outer, y, width - outer, y + row_height), radius=13, fill=card_fill, outline=accent, width=1)
            draw.rounded_rectangle((outer, y, outer + 6, y + row_height), radius=3, fill=accent)

            champion = str(match.get("champion") or "-")
            champion_url = _champion_icon_url(match.get("champion_id"))
            paste_icon(champion_url, outer + 18, y + 17, 60, radius=10, border=(91, 105, 130), placeholder=champion)
            champ_level = safe_int(match.get("champ_level"), 0)
            if champ_level:
                draw.ellipse((outer + 60, y + 59, outer + 82, y + 81), fill=(10, 14, 25))
                draw.text((outer + 71, y + 70), str(champ_level), fill=text, font=tiny_font, anchor="mm")

            info_x = outer + 92
            result_text = "胜利" if win else "失败"
            draw.text((info_x, y + 16), result_text, fill=accent, font=result_font)
            draw.text((info_x + 48, y + 16), fit_text(draw, champion, body_bold_font, 150), fill=text, font=body_bold_font)
            queue_position = " · ".join(filter(None, [str(match.get("queue") or ""), str(match.get("position") or "")]))
            draw.text((info_x, y + 47), fit_text(draw, queue_position, small_font, 205), fill=muted, font=small_font)
            draw.text((info_x, y + 68), fit_text(draw, str(match.get("mode") or ""), tiny_font, 205), fill=(126, 140, 163), font=tiny_font)

            kills = safe_int(match.get("kills"), 0)
            deaths = safe_int(match.get("deaths"), 0)
            assists = safe_int(match.get("assists"), 0)
            kda = match.get("kda")
            kda_text = f"{kda:.2f}" if isinstance(kda, (int, float)) else "-"
            kda_x = outer + 310
            draw.text((kda_x, y + 20), f"{kills} / {deaths} / {assists}", fill=text, font=kda_font)
            draw.text((kda_x, y + 55), f"KDA {kda_text}", fill=cyan, font=small_font)

            stat_x = outer + 458
            damage = safe_int(match.get("damage"), 0)
            gold_value = safe_int(match.get("gold"), 0)
            cs_value = safe_int(match.get("cs"), 0) + safe_int(match.get("jungle_cs"), 0)
            vision = safe_int(match.get("vision_score"), 0)
            draw.text((stat_x, y + 18), f"伤害 {damage:,}", fill=text, font=small_font)
            draw.text((stat_x, y + 40), f"金币 {gold_value:,}", fill=muted, font=small_font)
            draw.text((stat_x, y + 62), f"补刀 {cs_value} · 视野 {vision}", fill=muted, font=tiny_font)

            items_x = outer + 602
            item_ids = [x for x in (match.get("item_ids") or []) if safe_int(x, 0)][:6]
            for item_index in range(6):
                icon_x = items_x + item_index * 30
                if item_index < len(item_ids):
                    item_url = _item_icon_url(item_ids[item_index])
                    paste_icon(item_url, icon_x, y + 18, 26, radius=5, border=(73, 86, 112))
                else:
                    draw.rounded_rectangle((icon_x, y + 18, icon_x + 26, y + 44), radius=5, fill=(38, 45, 62), outline=(62, 70, 90))
            spells = " / ".join(str(x) for x in (match.get("spells") or [])[:2])
            runes = " / ".join(str(x) for x in (match.get("runes") or [])[:2])
            lower_text = " · ".join(filter(None, [spells, runes]))
            draw.text((items_x, y + 57), fit_text(draw, lower_text, tiny_font, 184), fill=muted, font=tiny_font)

            time_x = width - outer - 18
            duration = format_duration(match.get("duration"))
            game_time = str(match.get("game_time") or "-")
            draw.text((time_x, y + 20), duration, fill=text, font=small_font, anchor="ra")
            draw.text((time_x, y + 48), fit_text(draw, game_time, tiny_font, 114), fill=muted, font=tiny_font, anchor="ra")
            draw.text((time_x, y + 69), f"#{index + 1}", fill=(119, 132, 155), font=tiny_font, anchor="ra")

        footer_y = height - footer_height - outer + 12
        draw.line((outer + 10, footer_y - 10, width - outer - 10, footer_y - 10), fill=line, width=1)
        draw.text((outer + 14, footer_y + 5), image_footer_left(), fill=muted, font=small_font)
        draw.text(
            (width - outer - 14, footer_y + 5),
            image_footer_right(),
            fill=(112, 126, 148),
            font=small_font,
            anchor="ra",
        )

        encoded = encode_png_limited(image)
        return Response(
            content=encoded,
            media_type="image/png",
            headers={"X-Image-Bytes": str(len(encoded)), "Cache-Control": "no-store"},
        )
    except Exception as exc:
        logger.warning("cross_query image png generation failed, falling back to svg: %s", exc)
        return build_cross_svg_response(payload)
