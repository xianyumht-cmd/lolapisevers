import io
import logging
from typing import Any, Dict, List, Optional

import requests
from fastapi.responses import JSONResponse, Response

from core.context import AppContext
from renderers.image_utils import fit_text, load_image_font
from services.aram_augments_service import rarity_label
from utils.formatters import pct

logger = logging.getLogger("LOLDataSystem")


def download_image_cached(ctx: AppContext, cache_key: str, url: str, timeout: int = 6) -> Optional[bytes]:
    cached = ctx.aram_augment_cache.get(cache_key)
    if isinstance(cached, bytes):
        return cached
    try:
        response = requests.get(url, timeout=timeout, headers={"Accept": "image/*,*/*", "User-Agent": "Mozilla/5.0"})
        if response.ok and response.content:
            ctx.aram_augment_cache.set(cache_key, response.content)
            return response.content
    except Exception:
        return None
    return None


def build_aram_augment_image_response(ctx: AppContext, payload: Dict[str, Any]) -> Response:
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
        section_gap = 18
        table_header_height = 44
        row_height = 50
        footer_height = 96
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
        title_font = load_image_font(30, bold=True)
        metric_font = load_image_font(17, bold=True)
        head_font = load_image_font(16, bold=True)
        body_font = load_image_font(17)
        small_font = load_image_font(13)
        tiny_font = load_image_font(12)
        cyan = (27, 214, 238)
        green = (43, 174, 91)
        white = (242, 248, 255)
        muted = (166, 184, 207)
        row_bg = (20, 63, 106)
        row_alt = (19, 59, 99)
        line = (14, 47, 81)

        def paste_icon(icon_url: str, cache_prefix: str, x: int, y: int, size: int) -> None:
            icon_bytes = download_image_cached(ctx, f"{cache_prefix}:{icon_url}", icon_url) if icon_url else None
            if not icon_bytes:
                return
            try:
                icon = Image.open(io.BytesIO(icon_bytes)).convert("RGBA").resize((size, size))
                image.paste(icon, (x, y), icon)
            except Exception:
                pass

        def draw_icon_items(label: str, items: List[Dict[str, Any]], x: int, y: int, max_items: int = 5) -> int:
            if not items:
                return y
            draw.text((x, y), label, fill=muted, font=tiny_font)
            icon_x = x
            icon_y = y + 20
            for item in items[:max_items]:
                if not isinstance(item, dict):
                    continue
                paste_icon(str(item.get("icon") or ""), label, icon_x, icon_y, 28)
                if not item.get("icon"):
                    draw.rounded_rectangle((icon_x, icon_y, icon_x + 28, icon_y + 28), radius=4, fill=(18, 54, 92), outline=cyan, width=1)
                icon_x += 34
            return y + 54

        draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=12, fill=(23, 34, 61), outline=(14, 94, 126), width=1)
        hero_icon = f"https://game.gtimg.cn/images/lol/act/img/champion/{alias}.png" if alias else ""
        icon_size = 82
        icon_x = (width - icon_size) // 2
        icon_y = 42
        paste_icon(hero_icon, "hero", icon_x, icon_y, icon_size)
        draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_size, icon_y + icon_size), radius=8, outline=cyan, width=2)
        title_box = draw.textbbox((0, 0), display_title, font=title_font)
        draw.text(((width - (title_box[2] - title_box[0])) // 2, 136), display_title, fill=white, font=title_font)
        metric_text = f"海克斯大乱斗强化推荐  TOP {len(rows)}"
        metric_box = draw.textbbox((0, 0), metric_text, font=metric_font)
        draw.text(((width - (metric_box[2] - metric_box[0])) // 2, 174), metric_text, fill=cyan, font=metric_font)

        y = header_height
        if quick_height:
            table_x = padding
            table_w = width - padding * 2
            draw.rounded_rectangle((table_x, y, table_x + table_w, y + quick_height), radius=8, fill=(20, 36, 68))
            col_y = y + 14
            draw_icon_items("出门", starter_items[0].get("items", []) if starter_items and isinstance(starter_items[0], dict) else [], table_x + 18, col_y, 3)
            draw_icon_items("鞋子", boots[0].get("items", []) if boots and isinstance(boots[0], dict) else [], table_x + 190, col_y, 2)
            draw_icon_items("技能", summoner_spells, table_x + 320, col_y, 2)
            draw_icon_items("加点", skill_order, table_x + 470, col_y, 3)
            y += quick_height + section_gap

        if build_height:
            table_x = padding
            table_w = width - padding * 2
            draw.rounded_rectangle((table_x, y, table_x + table_w, y + build_height), radius=8, fill=(20, 36, 68))
            draw.text((table_x + 18, y + 12), "核心出装", fill=cyan, font=head_font)
            row_y = y + 44
            for build in item_builds[:3]:
                if not isinstance(build, dict):
                    continue
                draw.text((table_x + 22, row_y + 8), f"#{build.get('rank') or '-'}", fill=white, font=body_font)
                icon_x = table_x + 72
                for item in (build.get("items") or [])[:5]:
                    if isinstance(item, dict):
                        paste_icon(str(item.get("icon") or ""), "build", icon_x, row_y, 30)
                        icon_x += 36
                row_y += 38
            y += build_height + section_gap

        table_x = padding
        table_w = width - padding * 2
        draw.rounded_rectangle((table_x, y - 8, table_x + table_w, y + max(len(rows), 1) * row_height + 38), radius=7, fill=(20, 36, 68))
        columns = [("排名", table_x + 34), ("强化", table_x + 230), ("品质", table_x + 420), ("强度", table_x + 540), ("热度", table_x + 650)]
        for label, x in columns:
            draw.text((x, y + 8), label, fill=cyan, font=head_font, anchor="mm")
        draw.line((table_x, y + 34, table_x + table_w, y + 34), fill=cyan, width=2)
        row_start = y + 36
        if not rows:
            draw.text((width // 2, row_start + 22), "暂无可用强化数据", fill=muted, font=body_font, anchor="mm")
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            ry = row_start + (idx - 1) * row_height
            draw.rectangle((table_x, ry, table_x + table_w, ry + row_height), fill=row_bg if idx % 2 else row_alt)
            draw.line((table_x, ry + row_height, table_x + table_w, ry + row_height), fill=line, width=1)
            draw.text((table_x + 34, ry + 25), str(idx), fill=white, font=body_font, anchor="mm")
            paste_icon(str(row.get("icon") or ""), "augment", table_x + 76, ry + 9, 32)
            draw.text((table_x + 230, ry + 25), fit_text(draw, row.get("name"), body_font, 250), fill=white, font=body_font, anchor="mm")
            draw.text((table_x + 420, ry + 25), rarity_label(row.get("rarity")), fill=white, font=body_font, anchor="mm")
            draw.text((table_x + 540, ry + 25), pct(row.get("performance")), fill=green, font=body_font, anchor="mm")
            draw.text((table_x + 650, ry + 25), pct(row.get("popular")), fill=white, font=body_font, anchor="mm")

        footer = f"本数据由 GroupGuardKing GGK 提供 | {payload.get('updated_at')}"
        footer_box = draw.textbbox((0, 0), footer, font=small_font)
        draw.text(((width - (footer_box[2] - footer_box[0])) // 2, height - 48), footer, fill=muted, font=small_font)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return Response(content=buffer.getvalue(), media_type="image/png")
    except Exception as exc:
        logger.exception("aram_augments image generation failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"海符榜图片生成失败: {exc}"})
