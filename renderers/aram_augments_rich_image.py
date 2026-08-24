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
)
from services.aram_augments_service import rarity_label
from utils.formatters import pct


logger = logging.getLogger("LOLDataSystem")

ARAM_IMAGE_WIDTH = 840
ARAM_IMAGE_MAX_BYTES = 180_000
ARAM_IMAGE_MAX_HEIGHT = 1450
ARAM_IMAGE_ASSET_BUDGET_SECONDS = 1.5


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number / 100.0 if number > 1 else number


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
        "胜率与热度兼顾",
        lambda row: _number(row.get("performance")) * 0.72 + _number(row.get("popular")) * 0.28,
    )
    take(
        "高胜上限",
        "优先当前单符胜率",
        lambda row: _number(row.get("performance")),
    )
    take(
        "热门容错",
        "优先高选用率",
        lambda row: _number(row.get("popular")),
    )
    return routes


def _compact_build_data(payload: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    item_builds = payload.get("item_builds") if isinstance(payload.get("item_builds"), list) else []
    starter_rows = payload.get("starter_items") if isinstance(payload.get("starter_items"), list) else []
    boot_rows = payload.get("boots") if isinstance(payload.get("boots"), list) else []
    spells = payload.get("summoner_spells") if isinstance(payload.get("summoner_spells"), list) else []
    skills = payload.get("skill_order") if isinstance(payload.get("skill_order"), list) else []

    def row_items(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        if not rows or not isinstance(rows[0], dict):
            return []
        values = rows[0].get("items")
        if not isinstance(values, list):
            return []
        return [item for item in values[:limit] if isinstance(item, dict)]

    return {
        "core": [row for row in item_builds[:2] if isinstance(row, dict)],
        "starter": row_items(starter_rows, 3),
        "boots": row_items(boot_rows, 1),
        "spells": [item for item in spells[:2] if isinstance(item, dict)],
        "skills": [item for item in skills[:3] if isinstance(item, dict)],
    }


def _has_build_data(build_data: Dict[str, List[Dict[str, Any]]]) -> bool:
    return any(build_data.get(key) for key in ("core", "starter", "boots", "spells", "skills"))


def _build_status_text(payload: Dict[str, Any]) -> str:
    timing = payload.get("timing") if isinstance(payload.get("timing"), dict) else {}
    status = str(timing.get("build_status") or "").strip().lower()
    if status == "snapshot":
        age = int(timing.get("optional_snapshot_age_seconds") or 0)
        return f"出装快照 {age // 60}m" if age else "出装快照"
    if status == "ok":
        return "OP.GG 实时出装"
    if status in {"empty", "unavailable"}:
        return "出装数据暂缺"
    return "OP.GG 出装"


def _collect_asset_urls(
    alias: str,
    rows: List[Dict[str, Any]],
    build_data: Dict[str, List[Dict[str, Any]]],
) -> List[str]:
    hero_icon = f"https://game.gtimg.cn/images/lol/act/img/champion/{alias}.png" if alias else ""
    urls: List[str] = [hero_icon] if hero_icon else []

    def add(values: Any, *, nested_items: bool = False, limit: int = 12) -> None:
        if not isinstance(values, list):
            return
        for item in values[:limit]:
            if not isinstance(item, dict):
                continue
            if nested_items:
                add(item.get("items"), limit=5)
                continue
            icon = str(item.get("icon") or "").strip()
            if icon:
                urls.append(icon)

    add(build_data.get("core"), nested_items=True, limit=2)
    add(build_data.get("starter"), limit=3)
    add(build_data.get("boots"), limit=1)
    add(build_data.get("spells"), limit=2)
    add(build_data.get("skills"), limit=3)
    add(rows, limit=10)
    return urls


def build_aram_augment_image_response(ctx: Any, payload: Dict[str, Any]) -> Response:
    try:
        from PIL import Image, ImageDraw, ImageOps

        hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        rows = [row for row in rows[:10] if isinstance(row, dict)]
        alias = str(hero.get("alias") or "").strip()
        title = str(hero.get("title") or alias or "-").strip()
        name = str(hero.get("name") or "").strip()
        display_title = f"{title} · {name}" if name else title
        build_data = _compact_build_data(payload)
        show_build = _has_build_data(build_data) or any(
            key in payload for key in ("item_builds", "starter_items", "boots", "summoner_spells", "skill_order")
        )

        grouped: List[Tuple[str, List[Dict[str, Any]]]] = []
        for label in ("棱镜", "金", "银"):
            items = [row for row in rows if rarity_label(row.get("rarity")) == label]
            if items:
                grouped.append((label, items))
        other = [row for row in rows if rarity_label(row.get("rarity")) not in {"棱镜", "金", "银"}]
        if other:
            grouped.append(("其他", other))

        width = ARAM_IMAGE_WIDTH
        outer = 16
        hero_height = 118
        gap = 8
        build_height = 142 if show_build else 0
        section_header = 28
        card_height = 64
        card_gap = 6
        route_height = 96 if rows else 0
        footer_height = 38

        sections_height = 0
        for _label, items in grouped:
            card_rows = (len(items) + 1) // 2
            sections_height += (
                section_header
                + card_rows * card_height
                + max(0, card_rows - 1) * card_gap
                + 8
                + gap
            )
        if not grouped:
            sections_height = 82

        height = outer + hero_height + gap
        if build_height:
            height += build_height + gap
        height += sections_height
        if route_height:
            height += route_height + gap
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
        title_font = load_image_font(24, bold=True)
        subtitle_font = load_image_font(14, bold=True)
        head_font = load_image_font(13, bold=True)
        body_font = load_image_font(12)
        body_bold_font = load_image_font(12, bold=True)
        small_font = load_image_font(10)
        tiny_font = load_image_font(9)
        metric_font = load_image_font(14, bold=True)

        hero_icon = f"https://game.gtimg.cn/images/lol/act/img/champion/{alias}.png" if alias else ""
        asset_cache = getattr(ctx, "image_asset_cache", getattr(ctx, "aram_augment_cache", None))
        assets = prefetch_image_urls(
            asset_cache,
            _collect_asset_urls(alias, rows, build_data),
            timeout=1.0,
            max_workers=12,
            max_assets=42,
            overall_timeout=ARAM_IMAGE_ASSET_BUDGET_SECONDS,
        )

        def paste_icon(
            url: str,
            x: int,
            y: int,
            size: int,
            *,
            radius: int = 7,
            border=None,
            placeholder: str = "",
            placeholder_font=None,
        ) -> None:
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
                    draw.text(
                        (x + size // 2, y + size // 2),
                        placeholder[:1],
                        fill=muted,
                        font=placeholder_font or small_font,
                        anchor="mm",
                    )
            if border:
                draw.rounded_rectangle((x, y, x + size, y + size), radius=radius, outline=border, width=1)

        def rarity_color(label: str):
            if label == "棱镜":
                return purple
            if label == "金":
                return gold
            return silver

        def draw_metric(x: int, y: int, label: str, value: str, accent) -> None:
            draw.rounded_rectangle((x, y, x + 94, y + 36), radius=9, fill=card, outline=line)
            draw.text((x + 9, y + 7), label, fill=muted, font=tiny_font)
            draw.text((x + 9, y + 20), fit_text(draw, value, metric_font, 78), fill=accent, font=metric_font)

        # Hero summary.
        draw.rounded_rectangle((outer, outer, width - outer, outer + hero_height), radius=14, fill=panel, outline=line)
        paste_icon(hero_icon, outer + 18, outer + 21, 76, radius=12, border=cyan, placeholder=title, placeholder_font=head_font)
        title_x = outer + 112
        draw.text((title_x, outer + 19), fit_text(draw, display_title, title_font, 470), fill=text, font=title_font)
        draw.text((title_x, outer + 52), "海克斯大乱斗 · 海符决策", fill=cyan, font=subtitle_font)
        draw.text(
            (title_x, outer + 77),
            f"TOP {len(rows)} / {payload.get('total') or len(rows)} · 强化 + 出装 + 技能",
            fill=muted,
            font=small_font,
        )
        updated = str(payload.get("updated_at") or "-")
        source = str(payload.get("source") or payload.get("provider") or "opgg").upper()
        draw.text((title_x, outer + 97), fit_text(draw, f"{source} · {updated}", tiny_font, 470), fill=(122, 139, 164), font=tiny_font)

        metric_x = width - outer - 204
        draw_metric(metric_x, outer + 20, "榜单", f"TOP {len(rows)}", cyan)
        draw_metric(metric_x + 102, outer + 20, "来源", source, green)
        draw_metric(metric_x, outer + 62, "品质", str(len(grouped)), purple)
        draw_metric(metric_x + 102, outer + 62, "缓存", f"{payload.get('cache_expires_in') or '-'}s", gold)

        y = outer + hero_height + gap

        # Equipment + skill panel. Kept dense so it adds useful information without
        # returning to the oversized legacy layout.
        if show_build:
            draw.rounded_rectangle((outer, y, width - outer, y + build_height), radius=12, fill=panel, outline=line)
            draw.text((outer + 14, y + 17), "出装与技能", fill=text, font=head_font, anchor="lm")
            draw.text((width - outer - 14, y + 17), _build_status_text(payload), fill=muted, font=tiny_font, anchor="rm")

            core_y = y + 31
            draw.text((outer + 14, core_y + 16), "核心", fill=cyan, font=small_font, anchor="lm")
            core_start = outer + 54
            scheme_width = 344
            if not build_data["core"]:
                draw.text((core_start, core_y + 16), "暂无核心出装", fill=muted, font=tiny_font, anchor="lm")
            for scheme_index, build in enumerate(build_data["core"][:2]):
                bx = core_start + scheme_index * scheme_width
                label = f"#{build.get('rank') or scheme_index + 1}"
                draw.text((bx, core_y + 16), label, fill=gold if scheme_index == 0 else silver, font=tiny_font, anchor="lm")
                icon_x = bx + 24
                build_items = build.get("items") if isinstance(build.get("items"), list) else []
                for item in [value for value in build_items[:5] if isinstance(value, dict)]:
                    paste_icon(
                        str(item.get("icon") or ""),
                        icon_x,
                        core_y + 1,
                        30,
                        radius=5,
                        border=line,
                        placeholder=str(item.get("name") or ""),
                    )
                    icon_x += 34
                if not build_items:
                    draw.text((bx + 24, core_y + 16), "暂无", fill=muted, font=tiny_font, anchor="lm")

            divider_y = y + 70
            draw.line((outer + 14, divider_y, width - outer - 14, divider_y), fill=line, width=1)

            group_y = y + 80
            group_specs = [
                ("出门", build_data["starter"], 3, outer + 14, 184),
                ("鞋子", build_data["boots"], 1, outer + 202, 92),
                ("召唤师", build_data["spells"], 2, outer + 300, 150),
            ]
            for label, values, limit, gx, group_width in group_specs:
                draw.text((gx, group_y + 10), label, fill=muted, font=tiny_font)
                icon_x = gx
                for item in values[:limit]:
                    paste_icon(
                        str(item.get("icon") or ""),
                        icon_x,
                        group_y + 22,
                        26,
                        radius=5,
                        border=line,
                        placeholder=str(item.get("name") or ""),
                    )
                    icon_x += 30
                    if icon_x > gx + group_width - 24:
                        break

            skill_x = outer + 462
            draw.text((skill_x, group_y + 10), "技能加点", fill=muted, font=tiny_font)
            skills = build_data["skills"]
            if skills:
                icon_x = skill_x
                order_parts: List[str] = []
                for index, skill in enumerate(skills[:3]):
                    key = str(skill.get("key") or skill.get("name") or "?").upper()
                    order_parts.append(key)
                    paste_icon(
                        str(skill.get("icon") or ""),
                        icon_x,
                        group_y + 22,
                        26,
                        radius=5,
                        border=cyan,
                        placeholder=key,
                    )
                    draw.text((icon_x + 13, group_y + 52), key, fill=cyan, font=tiny_font, anchor="mm")
                    icon_x += 42
                    if index < len(skills[:3]) - 1:
                        draw.text((icon_x - 9, group_y + 35), ">", fill=muted, font=tiny_font, anchor="mm")
                order = " > ".join(order_parts)
                draw.text((width - outer - 14, group_y + 35), order, fill=text, font=small_font, anchor="rm")
            else:
                draw.text((skill_x, group_y + 35), "暂无", fill=muted, font=tiny_font)

            y += build_height + gap

        if not grouped:
            draw.rounded_rectangle((outer, y, width - outer, y + 72), radius=12, fill=panel, outline=line)
            draw.text((width // 2, y + 36), "暂无可用强化数据", fill=muted, font=body_font, anchor="mm")
            y += 82
        else:
            inner_width = width - outer * 2 - 28
            column_gap = 8
            card_width = (inner_width - column_gap) // 2
            for label, items in grouped:
                accent = rarity_color(label)
                card_rows = (len(items) + 1) // 2
                section_height = section_header + card_rows * card_height + max(0, card_rows - 1) * card_gap + 8
                draw.rounded_rectangle((outer, y, width - outer, y + section_height), radius=12, fill=panel, outline=line)
                draw.text((outer + 14, y + 16), f"{label}强化", fill=accent, font=head_font, anchor="lm")
                draw.text((width - outer - 14, y + 16), f"{len(items)} 项", fill=muted, font=tiny_font, anchor="rm")
                base_y = y + section_header
                for idx, row in enumerate(items):
                    row_index = idx // 2
                    col = idx % 2
                    x = outer + 14 + col * (card_width + column_gap)
                    cy = base_y + row_index * (card_height + card_gap)
                    draw.rounded_rectangle((x, cy, x + card_width, cy + card_height), radius=10, fill=card, outline=line)
                    paste_icon(
                        str(row.get("icon") or ""),
                        x + 9,
                        cy + 12,
                        40,
                        radius=7,
                        border=accent,
                        placeholder=str(row.get("name") or ""),
                    )
                    name_width = card_width - 164
                    draw.text(
                        (x + 58, cy + 10),
                        fit_text(draw, row.get("name"), body_bold_font, name_width),
                        fill=text,
                        font=body_bold_font,
                    )
                    desc = fit_text(draw, str(row.get("desc") or ""), tiny_font, name_width)
                    draw.text((x + 58, cy + 32), desc, fill=muted, font=tiny_font)
                    games = row.get("games")
                    sample_text = f"样本 {games}" if games not in {None, ""} else f"#{row.get('rank') or idx + 1}"
                    draw.text((x + 58, cy + 50), fit_text(draw, sample_text, tiny_font, name_width), fill=(122, 139, 164), font=tiny_font)

                    stat_x = x + card_width - 10
                    draw.text((stat_x - 60, cy + 14), "胜率", fill=muted, font=tiny_font, anchor="ra")
                    draw.text((stat_x, cy + 14), pct(row.get("performance")), fill=green, font=body_bold_font, anchor="ra")
                    draw.text((stat_x - 60, cy + 38), "热度", fill=muted, font=tiny_font, anchor="ra")
                    draw.text((stat_x, cy + 38), pct(row.get("popular")), fill=accent, font=small_font, anchor="ra")
                y += section_height + gap

        routes = _decision_routes(rows)
        if routes:
            draw.rounded_rectangle((outer, y, width - outer, y + route_height), radius=12, fill=panel, outline=line)
            draw.text((outer + 14, y + 16), "选符方向", fill=text, font=head_font, anchor="lm")
            draw.text((width - outer - 14, y + 16), "单符数据推导 · 非三符组合实测", fill=muted, font=tiny_font, anchor="rm")
            inner_width = width - outer * 2 - 28
            route_gap = 8
            route_width = (inner_width - route_gap * 2) // 3
            for idx, (label, selected, description) in enumerate(routes[:3]):
                x = outer + 14 + idx * (route_width + route_gap)
                ry = y + 29
                draw.rounded_rectangle((x, ry, x + route_width, ry + 54), radius=9, fill=card, outline=line)
                draw.text((x + 9, ry + 12), label, fill=(cyan, green, gold)[idx], font=tiny_font)
                draw.text((x + 9, ry + 29), fit_text(draw, selected, body_bold_font, route_width - 18), fill=text, font=body_bold_font)
                draw.text((x + 9, ry + 45), fit_text(draw, description, tiny_font, route_width - 18), fill=muted, font=tiny_font)
            y += route_height + gap

        footer_y = height - footer_height - outer
        draw.line((outer, footer_y, width - outer, footer_y), fill=line, width=1)
        draw.text((outer, footer_y + 19), image_footer_left(), fill=muted, font=tiny_font, anchor="lm")
        draw.text((width - outer, footer_y + 19), image_footer_right(), fill=muted, font=tiny_font, anchor="rm")

        encoded = encode_png_limited(
            image,
            max_bytes=ARAM_IMAGE_MAX_BYTES,
            max_width=ARAM_IMAGE_WIDTH,
            max_height=ARAM_IMAGE_MAX_HEIGHT,
        )
        return Response(
            content=encoded,
            media_type="image/png",
            headers={"X-Image-Bytes": str(len(encoded)), "Cache-Control": "no-store"},
        )
    except Exception as exc:
        logger.exception("rich ARAM augment image generation failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": "海符榜图片生成失败"})
