import io
import logging
from typing import Any, Dict, List, Optional

from fastapi.responses import JSONResponse, Response

from core.context import AppContext
from renderers.image_utils import (
    encode_png_limited,
    fit_text,
    image_footer_left,
    image_footer_right,
    load_image_font,
    prefetch_image_urls,
)
from services.aram_augments_service import rarity_label
from utils.formatters import pct

logger = logging.getLogger("LOLDataSystem")


def build_aram_augment_image_response(ctx: AppContext, payload: Dict[str, Any]) -> Response:
    try:
        from PIL import Image, ImageDraw, ImageOps

        hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        rows = [row for row in rows[:10] if isinstance(row, dict)]
        item_builds = payload.get("item_builds") if isinstance(payload.get("item_builds"), list) else []
        starter_items = payload.get("starter_items") if isinstance(payload.get("starter_items"), list) else []
        boots = payload.get("boots") if isinstance(payload.get("boots"), list) else []
        summoner_spells = payload.get("summoner_spells") if isinstance(payload.get("summoner_spells"), list) else []
        skill_order = payload.get("skill_order") if isinstance(payload.get("skill_order"), list) else []
        alias = str(hero.get("alias") or "")
        title = str(hero.get("title") or alias or "-")
        name = str(hero.get("name") or "")
        display_title = f"{title} · {name}" if name else title

        width = 900
        outer = 22
        hero_height = 154
        quick_height = 100 if (starter_items or boots or summoner_spells or skill_order) else 0
        core_height = 104 if item_builds else 0
        gap = 12
        table_header_height = 42
        row_height = 62
        footer_height = 54
        row_count = max(len(rows), 1)
        height = outer + hero_height
        if quick_height:
            height += gap + quick_height
        if core_height:
            height += gap + core_height
        height += gap + table_header_height + row_count * row_height + footer_height + outer

        bg = (12, 17, 30)
        panel = (23, 31, 51)
        panel_soft = (28, 39, 64)
        text = (241, 246, 252)
        muted = (155, 170, 193)
        cyan = (63, 207, 225)
        green = (62, 211, 151)
        gold = (247, 190, 76)
        purple = (192, 132, 252)
        line = (48, 63, 88)

        image = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(image)
        title_font = load_image_font(28, bold=True)
        subtitle_font = load_image_font(17, bold=True)
        head_font = load_image_font(15, bold=True)
        body_font = load_image_font(15)
        body_bold_font = load_image_font(15, bold=True)
        small_font = load_image_font(12)
        tiny_font = load_image_font(10)
        metric_font = load_image_font(18, bold=True)

        hero_icon = f"https://game.gtimg.cn/images/lol/act/img/champion/{alias}.png" if alias else ""
        asset_urls: List[str] = [hero_icon] if hero_icon else []

        def add_item_urls(items: Any, limit: int) -> None:
            if not isinstance(items, list):
                return
            for item in items[:limit]:
                if isinstance(item, dict) and item.get("icon"):
                    asset_urls.append(str(item.get("icon")))

        if starter_items and isinstance(starter_items[0], dict):
            add_item_urls(starter_items[0].get("items"), 3)
        if boots and isinstance(boots[0], dict):
            add_item_urls(boots[0].get("items"), 2)
        add_item_urls(summoner_spells, 2)
        add_item_urls(skill_order, 3)
        for build in item_builds[:3]:
            if isinstance(build, dict):
                add_item_urls(build.get("items"), 5)
        add_item_urls(rows, 10)

        asset_cache = getattr(ctx, "image_asset_cache", ctx.aram_augment_cache)
        assets = prefetch_image_urls(asset_cache, asset_urls, timeout=3.5, max_workers=8, max_assets=56)

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
            icon_bytes = assets.get(str(url or ""))
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
                draw.rounded_rectangle((x, y, x + size, y + size), radius=radius, fill=(43, 54, 78))
                if placeholder:
                    draw.text((x + size // 2, y + size // 2), placeholder[:1], fill=muted, font=head_font, anchor="mm")
            if border:
                draw.rounded_rectangle((x, y, x + size, y + size), radius=radius, outline=border, width=2)

        def draw_metric_pill(x: int, y: int, label: str, value: str, accent: tuple, width_hint: int = 126) -> None:
            draw.rounded_rectangle((x, y, x + width_hint, y + 48), radius=12, fill=panel_soft, outline=line)
            draw.text((x + 12, y + 10), label, fill=muted, font=tiny_font)
            draw.text((x + 12, y + 27), value, fill=accent, font=metric_font)

        def draw_icon_group(label: str, items: List[Dict[str, Any]], x: int, y: int, max_items: int, width_hint: int) -> None:
            draw.text((x, y), label, fill=muted, font=small_font)
            icon_x = x
            for item in items[:max_items]:
                if not isinstance(item, dict):
                    continue
                paste_icon(str(item.get("icon") or ""), icon_x, y + 22, 32, radius=6, border=(65, 81, 108), placeholder=str(item.get("name") or item.get("key") or ""))
                icon_x += 38
                if icon_x > x + width_hint - 32:
                    break

        def rarity_style(value: Any) -> tuple:
            label = rarity_label(value)
            if label == "棱镜":
                return purple, (65, 42, 92)
            if label == "金":
                return gold, (78, 58, 27)
            return cyan, (28, 66, 78)

        def draw_bar(x: int, y: int, width_value: int, ratio: Any, accent: tuple) -> None:
            try:
                numeric = float(ratio)
            except (TypeError, ValueError):
                numeric = 0.0
            normalized = max(0.0, min(numeric, 1.0))
            if numeric > 1.0:
                normalized = max(0.0, min(numeric / 100.0, 1.0))
            draw.rounded_rectangle((x, y, x + width_value, y + 6), radius=3, fill=(45, 54, 72))
            if normalized > 0:
                draw.rounded_rectangle((x, y, x + max(4, int(width_value * normalized)), y + 6), radius=3, fill=accent)

        draw.rounded_rectangle((outer, outer, width - outer, outer + hero_height), radius=16, fill=panel, outline=line)
        paste_icon(hero_icon, outer + 22, outer + 26, 96, radius=14, border=cyan, placeholder=title)
        title_x = outer + 142
        draw.text((title_x, outer + 28), fit_text(draw, display_title, title_font, 430), fill=text, font=title_font)
        draw.text((title_x, outer + 72), "海克斯大乱斗强化榜", fill=cyan, font=subtitle_font)
        draw.text((title_x, outer + 104), f"共收录 {payload.get('total') or len(rows)} 项 · 当前展示 TOP {len(rows)}", fill=muted, font=small_font)
        draw.text((title_x, outer + 127), "强化、出装、技能信息集中展示", fill=(122, 139, 164), font=tiny_font)

        metrics_x = width - outer - 284
        draw_metric_pill(metrics_x, outer + 28, "榜单", f"TOP {len(rows)}", cyan)
        draw_metric_pill(metrics_x + 138, outer + 28, "数据源", "OP.GG", green)
        draw_metric_pill(metrics_x, outer + 86, "缓存", f"{payload.get('cache_expires_in') or '-'}s", gold)
        draw_metric_pill(metrics_x + 138, outer + 86, "收录", str(payload.get("total") or len(rows)), purple)

        y = outer + hero_height
        if quick_height:
            y += gap
            draw.rounded_rectangle((outer, y, width - outer, y + quick_height), radius=14, fill=panel, outline=line)
            inner_x = outer + 20
            col_width = (width - outer * 2 - 40) // 4
            starter = starter_items[0].get("items", []) if starter_items and isinstance(starter_items[0], dict) else []
            boot_items = boots[0].get("items", []) if boots and isinstance(boots[0], dict) else []
            draw_icon_group("推荐出门装", starter, inner_x, y + 16, 3, col_width)
            draw_icon_group("鞋子", boot_items, inner_x + col_width, y + 16, 2, col_width)
            draw_icon_group("召唤师技能", summoner_spells, inner_x + col_width * 2, y + 16, 2, col_width)
            draw_icon_group("技能优先级", skill_order, inner_x + col_width * 3, y + 16, 3, col_width)
            y += quick_height

        if core_height:
            y += gap
            draw.rounded_rectangle((outer, y, width - outer, y + core_height), radius=14, fill=panel, outline=line)
            draw.text((outer + 20, y + 14), "核心出装", fill=text, font=head_font)
            available_width = width - outer * 2 - 40
            build_width = available_width // 3
            for idx, build in enumerate(item_builds[:3]):
                if not isinstance(build, dict):
                    continue
                bx = outer + 20 + idx * build_width
                if idx:
                    draw.line((bx - 10, y + 16, bx - 10, y + core_height - 16), fill=line, width=1)
                draw.text((bx, y + 40), f"方案 {build.get('rank') or idx + 1}", fill=cyan, font=small_font)
                icon_x = bx
                for item in (build.get("items") or [])[:5]:
                    if not isinstance(item, dict):
                        continue
                    paste_icon(str(item.get("icon") or ""), icon_x, y + 61, 30, radius=5, border=(65, 81, 108), placeholder=str(item.get("name") or ""))
                    icon_x += 35
            y += core_height

        y += gap
        table_x = outer
        table_w = width - outer * 2
        draw.rounded_rectangle((table_x, y, table_x + table_w, y + table_header_height + row_count * row_height), radius=14, fill=panel, outline=line)
        draw.text((table_x + 20, y + 21), "排名", fill=muted, font=head_font, anchor="lm")
        draw.text((table_x + 94, y + 21), "强化符文", fill=muted, font=head_font, anchor="lm")
        draw.text((table_x + 540, y + 21), "品质", fill=muted, font=head_font, anchor="mm")
        draw.text((table_x + 650, y + 21), "强度", fill=muted, font=head_font, anchor="mm")
        draw.text((table_x + 792, y + 21), "热度", fill=muted, font=head_font, anchor="mm")
        draw.line((table_x + 12, y + table_header_height, table_x + table_w - 12, y + table_header_height), fill=line, width=1)

        row_start = y + table_header_height
        if not rows:
            draw.text((width // 2, row_start + row_height // 2), "暂无可用强化数据", fill=muted, font=body_font, anchor="mm")
        for idx, row in enumerate(rows, start=1):
            ry = row_start + (idx - 1) * row_height
            if idx % 2 == 0:
                draw.rectangle((table_x + 1, ry, table_x + table_w - 1, ry + row_height), fill=(26, 35, 57))
            rank_fill = gold if idx <= 3 else cyan
            draw.ellipse((table_x + 18, ry + 17, table_x + 46, ry + 45), fill=(64, 52, 35) if idx <= 3 else (28, 64, 75))
            draw.text((table_x + 32, ry + 31), str(idx), fill=rank_fill, font=head_font, anchor="mm")

            icon_url = str(row.get("icon") or "")
            paste_icon(icon_url, table_x + 62, ry + 10, 42, radius=8, border=(70, 87, 116), placeholder=str(row.get("name") or ""))
            name_text = fit_text(draw, row.get("name"), body_bold_font, 330)
            desc_text = fit_text(draw, row.get("desc"), tiny_font, 360)
            draw.text((table_x + 116, ry + 13), name_text, fill=text, font=body_bold_font)
            draw.text((table_x + 116, ry + 38), desc_text, fill=muted, font=tiny_font)

            rarity_fg, rarity_bg = rarity_style(row.get("rarity"))
            rarity_text = rarity_label(row.get("rarity"))
            draw.rounded_rectangle((table_x + 510, ry + 18, table_x + 570, ry + 44), radius=13, fill=rarity_bg)
            draw.text((table_x + 540, ry + 31), rarity_text, fill=rarity_fg, font=small_font, anchor="mm")

            performance = pct(row.get("performance"))
            popular = pct(row.get("popular"))
            draw.text((table_x + 650, ry + 22), performance, fill=green, font=body_bold_font, anchor="mm")
            draw_bar(table_x + 608, ry + 46, 84, row.get("performance"), green)
            draw.text((table_x + 792, ry + 22), popular, fill=text, font=body_bold_font, anchor="mm")
            draw_bar(table_x + 750, ry + 46, 84, row.get("popular"), cyan)
            draw.line((table_x + 16, ry + row_height, table_x + table_w - 16, ry + row_height), fill=(39, 50, 72), width=1)

        footer_y = height - footer_height - outer + 12
        draw.line((outer + 10, footer_y - 10, width - outer - 10, footer_y - 10), fill=line, width=1)
        draw.text((outer + 14, footer_y + 5), image_footer_left(), fill=muted, font=small_font)
        draw.text(
            (width - outer - 14, footer_y + 5),
            image_footer_right(),
            fill=(113, 128, 151),
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
        logger.exception("aram_augments image generation failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"海符榜图片生成失败: {exc}"})
