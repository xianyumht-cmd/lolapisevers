from __future__ import annotations

import io
import logging
import math
from typing import Any, Dict, List

from fastapi.responses import Response

from renderers.aram_augments_rich_image import build_aram_augment_image_response
from renderers.image_utils import encode_png_limited, fit_text, load_image_font


logger = logging.getLogger("LOLDataSystem")

_RENDERABLE_STATUSES = {
    "ok",
    "none",
    "snapshot",
    "stale",
    "syncing",
    "unverified",
}


def _layer_is_renderable(layer: Dict[str, Any]) -> bool:
    return str(layer.get("status") or "").strip().lower() in _RENDERABLE_STATUSES


def _layer_changes(layer: Dict[str, Any]) -> List[Dict[str, Any]]:
    values = layer.get("changes") if isinstance(layer.get("changes"), list) else []
    return [item for item in values[:8] if isinstance(item, dict)]


def _status_label(layer: Dict[str, Any]) -> str:
    status = str(layer.get("status") or "").strip().lower()
    if status == "syncing":
        return "同步中"
    if layer.get("stale") or status in {"snapshot", "stale"}:
        return "快照"
    if status == "unverified":
        return "未校验"
    if status == "none":
        return "无专属修正"
    if layer.get("current_patch_verified"):
        return "已校验"
    if status == "unavailable":
        return "不可用"
    return "来源页"


def _patch_label(layer: Dict[str, Any]) -> str:
    patch = str(
        layer.get("display_patch")
        or layer.get("patch")
        or layer.get("page_patch")
        or ""
    ).strip()
    status = _status_label(layer)
    return f"版本 {patch} · {status}" if patch else status


def _empty_message(layer: Dict[str, Any], *, kind: str) -> str:
    status = str(layer.get("status") or "").strip().lower()
    if status == "syncing":
        page_patch = str(
            layer.get("page_patch") or layer.get("patch") or "旧版本"
        ).strip()
        return f"{page_patch} 数据仍在同步，旧数值已隐藏"
    if status == "unavailable":
        return f"{kind}数据暂不可用（不等于无修正）"
    if status == "unverified":
        return f"{kind}版本暂未校验"
    if status == "none":
        return f"当前无英雄专属{kind}修正"
    return f"当前未发现英雄专属{kind}修正"


def _layer_height(layer: Dict[str, Any]) -> int:
    changes = _layer_changes(layer)
    rows = max(1, math.ceil(len(changes) / 4))
    return 28 + rows * 32


def build_aram_augment_image_with_balance(ctx: Any, payload: Dict[str, Any]) -> Response:
    base_response = build_aram_augment_image_response(ctx, payload)
    if base_response.status_code >= 400 or not str(base_response.media_type or "").startswith("image/"):
        return base_response

    balance = payload.get("balance") if isinstance(payload.get("balance"), dict) else {}
    base_balance = balance.get("base") if isinstance(balance.get("base"), dict) else {}
    if not (_layer_is_renderable(balance) or _layer_is_renderable(base_balance)):
        return base_response

    try:
        from PIL import Image, ImageDraw

        source = Image.open(io.BytesIO(bytes(base_response.body))).convert("RGB")
        width, old_height = source.size
        if width < 500 or old_height < 220:
            return base_response

        outer = 22
        hero_height = 154
        gap = 12
        top_cut = outer + hero_height + gap
        header_height = 42
        layer_gap = 8
        base_height = _layer_height(base_balance)
        mayhem_height = _layer_height(balance)
        panel_height = header_height + base_height + layer_gap + mayhem_height + 10
        insert_height = panel_height + gap
        panel_y = top_cut
        remainder_y = top_cut + insert_height

        bg = (12, 17, 30)
        panel = (23, 31, 51)
        pill = (28, 39, 64)
        text = (241, 246, 252)
        muted = (155, 170, 193)
        line = (48, 63, 88)
        green = (62, 211, 151)
        red = (248, 113, 113)
        cyan = (63, 207, 225)
        gold = (247, 190, 76)

        image = Image.new("RGB", (width, old_height + insert_height), bg)
        image.paste(source.crop((0, 0, width, top_cut)), (0, 0))
        image.paste(source.crop((0, top_cut, width, old_height)), (0, remainder_y))
        draw = ImageDraw.Draw(image)

        title_font = load_image_font(15, bold=True)
        body_font = load_image_font(13, bold=True)
        small_font = load_image_font(11)
        tiny_font = load_image_font(10, bold=True)

        draw.rounded_rectangle(
            (outer, panel_y, width - outer, panel_y + panel_height),
            radius=14,
            fill=panel,
            outline=line,
        )
        draw.text(
            (outer + 20, panel_y + 17),
            "英雄平衡修正 · 完整状态",
            fill=text,
            font=title_font,
        )
        note = "基础 ARAM / Mayhem 分层展示，不做数值相加"
        draw.text(
            (width - outer - 20, panel_y + 18),
            note,
            fill=muted,
            font=small_font,
            anchor="ra",
        )

        available_width = width - outer * 2 - 40
        columns = 4
        column_gap = 8
        pill_width = (available_width - column_gap * (columns - 1)) // columns
        pill_height = 26
        start_x = outer + 20

        def draw_layer(
            layer: Dict[str, Any],
            *,
            layer_y: int,
            title: str,
            empty_kind: str,
        ) -> None:
            draw.text(
                (start_x, layer_y + 10),
                title,
                fill=cyan if empty_kind == "基础平衡" else gold,
                font=body_font,
                anchor="lm",
            )
            draw.text(
                (width - outer - 20, layer_y + 10),
                _patch_label(layer),
                fill=muted,
                font=small_font,
                anchor="rm",
            )
            changes = _layer_changes(layer)
            if not changes:
                draw.text(
                    (start_x, layer_y + 38),
                    fit_text(
                        draw,
                        _empty_message(layer, kind=empty_kind),
                        small_font,
                        available_width,
                    ),
                    fill=muted,
                    font=small_font,
                    anchor="lm",
                )
                return

            start_y = layer_y + 24
            for index, item in enumerate(changes):
                row = index // columns
                col = index % columns
                x = start_x + col * (pill_width + column_gap)
                y = start_y + row * 32
                direction = str(item.get("direction") or "neutral").lower()
                accent = green if direction == "buff" else red if direction == "debuff" else cyan
                kind = "增益" if direction == "buff" else "削弱" if direction == "debuff" else "调整"
                draw.rounded_rectangle(
                    (x, y, x + pill_width, y + pill_height),
                    radius=8,
                    fill=pill,
                    outline=line,
                )
                label = fit_text(draw, str(item.get("label") or "调整"), small_font, 72)
                value = fit_text(draw, str(item.get("value") or "-"), body_font, 58)
                draw.text((x + 8, y + 13), label, fill=text, font=small_font, anchor="lm")
                draw.text((x + pill_width - 47, y + 13), value, fill=accent, font=body_font, anchor="mm")
                draw.text((x + pill_width - 7, y + 13), kind, fill=accent, font=tiny_font, anchor="rm")

        base_y = panel_y + header_height
        draw_layer(
            base_balance,
            layer_y=base_y,
            title="基础 ARAM（完整）",
            empty_kind="基础平衡",
        )
        mayhem_y = base_y + base_height + layer_gap
        draw_layer(
            balance,
            layer_y=mayhem_y,
            title="Mayhem 专属状态",
            empty_kind="Mayhem 专属",
        )

        encoded = encode_png_limited(image)
        return Response(
            content=encoded,
            media_type="image/png",
            headers={
                "X-Image-Bytes": str(len(encoded)),
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        logger.exception("aram balance overlay generation failed: %s", exc)
        return base_response
