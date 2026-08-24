from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Tuple

from fastapi.responses import JSONResponse, Response

from renderers.image_utils import (
    encode_png_limited,
    fit_text,
    image_footer_left,
    image_footer_right,
    load_image_font,
    prefetch_image_urls,
    wrap_draw_text,
)
from services.aram_augments_service import rarity_label
from utils.formatters import pct


logger = logging.getLogger("LOLDataSystem")


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number / 100.0 if number > 1 else number


def _rarity_rank(value: Any) -> int:
    label = rarity_label(value)
    if label == "棱镜":
        return 0
    if label == "金":
        return 1
    return 2


def _decision_routes(rows: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
    if not rows:
        return []
    candidates = list(rows)
    routes: List[Tuple[str, str, str]] = []
    used: set[str] = set()

    def take(label: str, description: str, scorer) -> None:
        ranked = sorted(candidates, key=scorer, reverse=True)
        for row in ranked:
            name = str(row.get("name") or "").strip()
            if name and name not in used:
                used.add(name)
                routes.append((label, name, description))
                return

    take(
        "稳健首选",
        "兼顾单符胜率与选用率",
        lambda row: _number(row.get("performance")) * 0.72 + _number(row.get("popular")) * 0.28,
    )
    take(
        "高胜上限",
        "优先当前单符胜率",
        lambda row: _number(row.get("performance")),
    )
    take(
        "热门容错",
        "优先高选用率与普适性",
        lambda row: _number(row.get("popular")),
    )
    return routes


def build_aram_augment_image_response(ctx: Any, payload: Dict[str, Any]) -> Response:
    try:
        from PIL import Image, ImageDraw, ImageOps

        hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        rows = [row for row in rows[:12] if isinstance(row, dict)]
        alias = str(hero.get("alias") or "").strip()
        title = str(hero.get("title") or alias or "-").strip()
        name = str(hero.get("name") or "").strip()
        display_title = f"{title} · {name}" if name else title

        grouped: List[Tuple[str, List[Dict[str, Any]]]] = []
        for label in ("棱镜", "金", "银"):
            items = [row for row in rows if rarity_label(row.get("rarity")) == label]
            if items:
                grouped.append((label, items))
        other = [row for row in rows if rarity_label(row.get("rarity")) not in {"棱镜", "金", "银"}]
        if other:
            grouped.append(("其他", other))

        width = 900
        outer = 22
        hero_height = 154
        gap = 12
        section_header = 34
        card_height = 88
        card_gap = 10
        route_height = 142 if rows else 0
        footer_height = 54

        sections_height = 0
        for _label, items in grouped:
            card_rows = (len(items) + 1) // 2
            sections_height += section_header + card_rows * card_height + max(0, card_rows - 1) * card_gap + 12
        if not grouped:
            sections_height = 110

        height = outer + hero_height + gap + sections_height
        if route_height:
            height += gap + route_height
        height += footer_height + outer

        bg = (12, 17, 30)
        panel = (23, 31, 51)
        card = (28, 39, 64)
        text = (241, 246, 252)
        muted = (155, 170, 193)
        line = (48, 63, 88)
        cyan = (63, 207, 225)
        green = (62, 211, 151)
        gold = (247, 190, 76)
        purple = (192, 132, 252)
        silver = (173, 188, 209)

        image = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(image)
        title_font = load_image_font(28, bold=True)
        subtitle_font = load_image_font(17, bold=True)
        head_font = load_image_font(15, bold=True)
        body_font = load_image_font(14)
        body_bold_font = load_image_font(14, bold=True)
        small_font = load_image_font(12)
        tiny_font = load_image_font(10)
        metric_font = load_image_font(18, bold=True)

        hero_icon = f"https://game.gtimg.cn/images/lol/act/img/champion/{alias}.png" if alias else ""
        urls: List[str] = [hero_icon] if hero_icon else []
        for row in rows:
            icon = str(row.get("icon") or "").strip()
            if icon:
                urls.append(icon)
        asset_cache = getattr(ctx, "image_asset_cache", getattr(ctx, "aram_augment_cache", None))
        assets = prefetch_image_urls(asset_cache, urls, timeout=3.0, max_workers=8, max_assets=24)

        def paste_icon(url: str, x: int, y: int, size: int, *, radius: int = 8, border=None, placeholder: str = "") -> None:
            raw = assets.get(str(url or ""))
            if raw:
                try:
                    icon = Image.open(io.BytesIO(raw)).convert("RGBA")
                    icon = ImageOps.fit(icon, (size, size), method=Image.Resampling.LANCZOS)
                    mask = Image.new("L", (size, size), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
                    image.paste(icon, (x, y), mask)
                except Exception:
                    raw = None
            if not raw:
                draw.rounded_rectangle((x, y, x + size, y + size), radius=radius, fill=(43, 54, 78))
                if placeholder:
                    draw.text((x + size // 2, y + size // 2), placeholder[:1], fill=muted, font=head_font, anchor="mm")
            if border:
                draw.rounded_rectangle((x, y, x + size, y + size), radius=radius, outline=border, width=2)

        def rarity_color(label: str):
            if label == "棱镜":
                return purple
            if label == "金":
                return gold
            return silver

        draw.rounded_rectangle((outer, outer, width - outer, outer + hero_height), radius=16, fill=panel, outline=line)
        paste_icon(hero_icon, outer + 22, outer + 26, 96, radius=14, border=cyan, placeholder=title)
        title_x = outer + 142
        draw.text((title_x, outer + 27), fit_text(draw, display_title, title_font, 430), fill=text, font=title_font)
        draw.text((title_x, outer + 72), "海克斯大乱斗 · 强化决策榜", fill=cyan, font=subtitle_font)
        draw.text((title_x, outer + 104), f"收录 {payload.get('total') or len(rows)} 项 · 展示 TOP {len(rows)}", fill=muted, font=small_font)
        updated = str(payload.get("updated_at") or "-")
        source = str(payload.get("source") or payload.get("provider") or "opgg").upper()
        draw.text((title_x, outer + 127), fit_text(draw, f"数据 {source} · {updated}", tiny_font, 430), fill=(122, 139, 164), font=tiny_font)

        metric_x = width - outer - 280
        for idx, (label, value, accent) in enumerate(
            (
                ("榜单", f"TOP {len(rows)}", cyan),
                ("品质", str(len(grouped)), purple),
                ("来源", source, green),
                ("缓存", f"{payload.get('cache_expires_in') or '-'}s", gold),
            )
        ):
            col = idx % 2
            row = idx // 2
            x = metric_x + col * 138
            y = outer + 28 + row * 58
            draw.rounded_rectangle((x, y, x + 126, y + 48), radius=12, fill=card, outline=line)
            draw.text((x + 12, y + 10), label, fill=muted, font=tiny_font)
            draw.text((x + 12, y + 27), fit_text(draw, value, metric_font, 100), fill=accent, font=metric_font)

        y = outer + hero_height + gap
        if not grouped:
            draw.rounded_rectangle((outer, y, width - outer, y + 100), radius=14, fill=panel, outline=line)
            draw.text((width // 2, y + 50), "暂无可用强化数据", fill=muted, font=body_font, anchor="mm")
            y += 110
        else:
            inner_width = width - outer * 2 - 40
            column_gap = 12
            card_width = (inner_width - column_gap) // 2
            for label, items in grouped:
                accent = rarity_color(label)
                card_rows = (len(items) + 1) // 2
                section_height = section_header + card_rows * card_height + max(0, card_rows - 1) * card_gap + 12
                draw.rounded_rectangle((outer, y, width - outer, y + section_height), radius=14, fill=panel, outline=line)
                draw.text((outer + 20, y + 20), f"{label}强化", fill=accent, font=head_font, anchor="lm")
                draw.text((width - outer - 20, y + 20), f"{len(items)} 项", fill=muted, font=small_font, anchor="rm")
                base_y = y + section_header
                for idx, row in enumerate(items):
                    row_index = idx // 2
                    col = idx % 2
                    x = outer + 20 + col * (card_width + column_gap)
                    cy = base_y + row_index * (card_height + card_gap)
                    draw.rounded_rectangle((x, cy, x + card_width, cy + card_height), radius=12, fill=card, outline=line)
                    paste_icon(str(row.get("icon") or ""), x + 12, cy + 12, 48, radius=8, border=accent, placeholder=str(row.get("name") or ""))
                    name_text = fit_text(draw, row.get("name"), body_bold_font, card_width - 180)
                    draw.text((x + 72, cy + 13), name_text, fill=text, font=body_bold_font)
                    draw.text((x + card_width - 102, cy + 15), "胜率", fill=muted, font=tiny_font)
                    draw.text((x + card_width - 14, cy + 15), pct(row.get("performance")), fill=green, font=body_bold_font, anchor="ra")
                    draw.text((x + card_width - 102, cy + 38), "热度", fill=muted, font=tiny_font)
                    draw.text((x + card_width - 14, cy + 38), pct(row.get("popular")), fill=accent, font=small_font, anchor="ra")
                    desc = str(row.get("desc") or "").strip()
                    lines = wrap_draw_text(draw, desc, tiny_font, card_width - 92)[:2]
                    for line_no, line_text in enumerate(lines):
                        draw.text((x + 72, cy + 38 + line_no * 15), fit_text(draw, line_text, tiny_font, card_width - 190), fill=muted, font=tiny_font)
                y += section_height + gap

        routes = _decision_routes(rows)
        if routes:
            draw.rounded_rectangle((outer, y, width - outer, y + route_height), radius=14, fill=panel, outline=line)
            draw.text((outer + 20, y + 20), "推荐选符方向", fill=text, font=head_font, anchor="lm")
            draw.text((width - outer - 20, y + 20), "由单符数据推导 · 不是实测三符组合胜率", fill=muted, font=tiny_font, anchor="rm")
            inner_width = width - outer * 2 - 40
            route_gap = 10
            route_width = (inner_width - route_gap * 2) // 3
            for idx, (label, selected, description) in enumerate(routes[:3]):
                x = outer + 20 + idx * (route_width + route_gap)
                ry = y + 40
                draw.rounded_rectangle((x, ry, x + route_width, ry + 82), radius=12, fill=card, outline=line)
                draw.text((x + 12, ry + 15), label, fill=(cyan, green, gold)[idx], font=small_font)
                draw.text((x + 12, ry + 39), fit_text(draw, selected, body_bold_font, route_width - 24), fill=text, font=body_bold_font)
                draw.text((x + 12, ry + 63), fit_text(draw, description, tiny_font, route_width - 24), fill=muted, font=tiny_font)
            y += route_height + gap

        footer_y = height - footer_height - outer
        draw.line((outer, footer_y, width - outer, footer_y), fill=line, width=1)
        draw.text((outer, footer_y + 25), image_footer_left(), fill=muted, font=tiny_font, anchor="lm")
        draw.text((width - outer, footer_y + 25), image_footer_right(), fill=muted, font=tiny_font, anchor="rm")

        encoded = encode_png_limited(image)
        return Response(content=encoded, media_type="image/png", headers={"X-Image-Bytes": str(len(encoded)), "Cache-Control": "no-store"})
    except Exception as exc:
        logger.exception("rich ARAM augment image generation failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": "海符榜图片生成失败"})
