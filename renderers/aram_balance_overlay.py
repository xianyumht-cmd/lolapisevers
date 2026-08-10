import io
import logging
from typing import Any, Dict, List

from fastapi.responses import Response

from renderers.aram_augments_image import build_aram_augment_image_response
from renderers.image_utils import encode_png_limited, fit_text, load_image_font

logger = logging.getLogger("LOLDataSystem")


def _balance_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    balance = payload.get("balance")
    if not isinstance(balance, dict):
        return []
    items = balance.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)][:8]


def build_aram_augment_image_with_balance_response(ctx, payload: Dict[str, Any]) -> Response:
    base_response = build_aram_augment_image_response(ctx, payload)
    if base_response.status_code >= 400 or not str(base_response.media_type or "").startswith("image/"):
        return base_response

    try:
        from PIL import Image, ImageDraw

        base = Image.open(io.BytesIO(bytes(base_response.body))).convert("RGB")
        balance = payload.get("balance") if isinstance(payload.get("balance"), dict) else {}
        items = _balance_items(payload)
        status = str(balance.get("status") or "unavailable")

        # The base renderer is designed at 900px wide with a 154px hero card
        # starting at y=22. Derive all insertion coordinates from the rendered
        # width so this remains safe when image limits scale the base image.
        scale = max(base.width / 900.0, 0.1)
        header_bottom = max(1, min(base.height - 1, int(round(176 * scale))))
        outer = max(8, int(round(22 * scale)))
        gap = max(6, int(round(12 * scale)))
        row_count = 2 if len(items) > 4 else 1
        panel_height = int(round((84 + (row_count - 1) * 36) * scale))
        insert_height = panel_height + gap * 2

        bg = base.getpixel((0, 0)) if base.width and base.height else (12, 17, 30)
        image = Image.new("RGB", (base.width, base.height + insert_height), bg)
        image.paste(base.crop((0, 0, base.width, header_bottom)), (0, 0))
        image.paste(
            base.crop((0, header_bottom, base.width, base.height)),
            (0, header_bottom + insert_height),
        )
        draw = ImageDraw.Draw(image)

        panel = (23, 31, 51)
        panel_soft = (28, 39, 64)
        text = (241, 246, 252)
        muted = (155, 170, 193)
        line = (48, 63, 88)
        green = (62, 211, 151)
        red = (239, 112, 122)
        gold = (247, 190, 76)

        title_font = load_image_font(max(12, int(round(15 * scale))), bold=True)
        body_font = load_image_font(max(11, int(round(13 * scale))), bold=True)
        tiny_font = load_image_font(max(9, int(round(10 * scale))))

        panel_top = header_bottom + gap
        panel_bottom = panel_top + panel_height
        draw.rounded_rectangle(
            (outer, panel_top, base.width - outer, panel_bottom),
            radius=max(8, int(round(14 * scale))),
            fill=panel,
            outline=line,
        )

        title_x = outer + int(round(18 * scale))
        title_y = panel_top + int(round(14 * scale))
        draw.text((title_x, title_y), "英雄平衡修正 · 完整状态", fill=text, font=title_font)

        patch = str(balance.get("patch") or "").strip()
        source_label = "OP.GG ARAM"
        if status == "snapshot":
            source_label += " · 缓存"
        if patch:
            source_label += f" · Patch {patch}"
        source_width = draw.textbbox((0, 0), source_label, font=tiny_font)[2]
        draw.text(
            (base.width - outer - int(round(18 * scale)) - source_width, title_y + int(round(2 * scale))),
            source_label,
            fill=muted,
            font=tiny_font,
        )

        chips_top = panel_top + int(round(42 * scale))
        chip_height = max(24, int(round(28 * scale)))
        chip_gap = max(6, int(round(8 * scale)))
        max_x = base.width - outer - int(round(18 * scale))
        x = title_x
        y = chips_top

        if items:
            for item in items:
                label = str(item.get("label") or item.get("key") or "").strip()
                value = str(item.get("value") or "").strip()
                chip_text = f"{label} {value}".strip()
                direction = str(item.get("direction") or "neutral")
                accent = green if direction == "buff" else red if direction == "debuff" else gold
                text_width = draw.textbbox((0, 0), chip_text, font=body_font)[2]
                chip_width = min(
                    max(int(round(104 * scale)), text_width + int(round(24 * scale))),
                    int(round(205 * scale)),
                )
                if x + chip_width > max_x and y == chips_top:
                    x = title_x
                    y += chip_height + chip_gap
                draw.rounded_rectangle(
                    (x, y, x + chip_width, y + chip_height),
                    radius=max(8, chip_height // 2),
                    fill=panel_soft,
                    outline=accent,
                )
                draw.text(
                    (x + int(round(12 * scale)), y + chip_height // 2),
                    fit_text(draw, chip_text, body_font, chip_width - int(round(24 * scale))),
                    fill=accent,
                    font=body_font,
                    anchor="lm",
                )
                x += chip_width + chip_gap
        else:
            if status == "none":
                message = "当前无英雄专属平衡修正"
                accent = green
            elif status == "snapshot":
                message = str(balance.get("summary") or "正在使用缓存中的完整平衡状态")
                accent = gold
            else:
                message = "平衡数据暂不可用（不等于无修正）"
                accent = gold
            draw.text((title_x, chips_top + chip_height // 2), message, fill=accent, font=body_font, anchor="lm")

        encoded = encode_png_limited(image)
        return Response(
            content=encoded,
            media_type="image/png",
            headers={"X-Image-Bytes": str(len(encoded)), "Cache-Control": "no-store"},
        )
    except Exception as exc:
        # Balance is supplementary. Never turn a healthy sea-rune image into a
        # 500 just because the overlay itself fails to render.
        logger.exception("aram balance image overlay failed; returning base image: %s", exc)
        return base_response
