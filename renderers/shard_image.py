import io
import logging
import time
from typing import Any, Dict, Optional

import requests
from fastapi.responses import JSONResponse, Response

from core.context import AppContext
from renderers.image_utils import fit_text, load_image_font
from utils.formatters import pct

logger = logging.getLogger("LOLDataSystem")


def download_hero_icon(ctx: AppContext, alias: str) -> Optional[bytes]:
    cache_key = f"hero_icon:{alias}"
    cached = ctx.shard_cache.get(cache_key)
    if isinstance(cached, bytes):
        return cached
    for url in [
        f"https://game.gtimg.cn/images/lol/act/img/champion/{alias}.png",
        f"https://ddragon.leagueoflegends.com/cdn/15.12.1/img/champion/{alias}.png",
    ]:
        try:
            response = requests.get(url, timeout=5, headers={"Accept": "image/*,*/*"})
            if response.ok and response.content:
                ctx.shard_cache.set(cache_key, response.content)
                return response.content
        except Exception:
            continue
    return None


def build_shard_image_response(ctx: AppContext, payload: Dict[str, Any]) -> Response:
    render_started = time.perf_counter()
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
        title_font = load_image_font(30, bold=True)
        metric_font = load_image_font(18, bold=True)
        head_font = load_image_font(17, bold=True)
        body_font = load_image_font(17)
        small_font = load_image_font(13)
        cyan = (27, 214, 238)
        green = (43, 174, 91)
        white = (242, 248, 255)
        muted = (166, 184, 207)
        row_bg = (20, 63, 106)
        row_alt = (19, 59, 99)
        line = (14, 47, 81)

        draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=12, fill=(23, 34, 61), outline=(14, 94, 126), width=1)
        icon_size = 96
        icon_x = (width - icon_size) // 2
        icon_y = 46
        asset_started = time.perf_counter()
        shard_cache = getattr(ctx, "shard_cache", None) if ctx is not None else None
        cache_get = getattr(shard_cache, "get", None)
        icon_cache_hit = bool(
            alias and callable(cache_get) and isinstance(cache_get(f"hero_icon:{alias}"), bytes)
        )
        icon_bytes = download_hero_icon(ctx, alias) if alias else None
        asset_ms = (time.perf_counter() - asset_started) * 1000
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
            ("总体选率", pct(payload.get("pick_rate"))),
            ("总体胜率", pct(payload.get("win_rate"))),
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
            draw.text((table_x + 240, y + 24), fit_text(draw, row.get("name"), body_font, 260), fill=white, font=body_font, anchor="mm")
            draw.text((table_x + 480, y + 24), pct(row.get("pick_rate")), fill=white, font=body_font, anchor="mm")
            draw.text((table_x + 616, y + 24), pct(row.get("win_rate")), fill=green, font=body_font, anchor="mm")

        footer = f"本数据由 GroupGuardKing GGK 提供 | {payload.get('updated_at')}"
        footer_box = draw.textbbox((0, 0), footer, font=small_font)
        draw.text(((width - (footer_box[2] - footer_box[0])) // 2, height - 48), footer, fill=muted, font=small_font)
        encode_started = time.perf_counter()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        encoded = buffer.getvalue()
        encode_ms = (time.perf_counter() - encode_started) * 1000
        return Response(
            content=encoded,
            media_type="image/png",
            headers={
                "X-Image-Bytes": str(len(encoded)),
                "X-Image-Cache": "asset-hit" if icon_cache_hit else "asset-miss",
                "X-Image-Assets": "complete" if (not alias or icon_bytes) else "warming",
                "X-Image-Asset-Ms": f"{asset_ms:.1f}",
                "X-Image-Asset-Count": "1" if icon_bytes else "0",
                "X-Image-Expected-Asset-Count": "1" if alias else "0",
                "X-Image-Encode-Ms": f"{encode_ms:.1f}",
                "X-Image-Render-Ms": f"{(time.perf_counter() - render_started) * 1000:.1f}",
                "X-Image-Width": str(width),
                "X-Image-Height": str(height),
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        logger.exception("shard_query image generation failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"合集图片生成失败: {exc}"})
