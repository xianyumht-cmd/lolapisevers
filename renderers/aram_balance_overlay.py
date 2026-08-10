from __future__ import annotations

import io
import logging
from typing import Any, Dict

from fastapi.responses import Response

from renderers.aram_augments_image import build_aram_augment_image_response
from renderers.image_utils import encode_png_limited, fit_text, load_image_font


logger = logging.getLogger("LOLDataSystem")


def _balance_is_renderable(balance: Dict[str, Any]) -> bool:
    return str(balance.get("status") or "").strip().lower() in {
        "ok",
        "snapshot",
        "stale",
        "syncing",
        "unverified",
    }


def build_aram_augment_image_with_balance(ctx: Any, payload: Dict[str, Any]) -> Response:
    base_response = build_aram_augment_image_response(ctx, payload)
    if base_response.status_code >= 400 or not str(base_response.media_type or "").startswith("image/"):
        return base_response

    balance = payload.get("balance") if isinstance(payload.get("balance"), dict) else {}
    if not _balance_is_renderable(balance):
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
        panel_height = 104
        top_cut = outer + hero_height + gap
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
            "英雄平衡修正 · Buff / Debuff",
            fill=text,
            font=title_font,
        )
        status = str(balance.get("status") or "").strip().lower()
        patch = str(balance.get("patch") or "").strip()
        if status == "syncing":
            source_label = "同步中"
        elif balance.get("stale"):
            source_label = "快照"
        elif status == "unverified":
            source_label = "未校验"
        elif balance.get("current_patch_verified"):
            source_label = "已校验"
        else:
            source_label = "来源页"
        patch_text = f"版本 {patch} · {source_label}" if patch else source_label
        draw.text(
            (width - outer - 20, panel_y + 18),
            patch_text,
            fill=muted,
            font=small_font,
            anchor="ra",
        )

        changes = balance.get("changes") if isinstance(balance.get("changes"), list) else []
        changes = [item for item in changes[:8] if isinstance(item, dict)]
        if not changes:
            if status == "syncing":
                page_patch = str(balance.get("page_patch") or "旧版本").strip()
                message = f"平衡页仍为 {page_patch}，旧 Buff / Debuff 已隐藏，等待当前版本同步"
            elif status == "unverified":
                message = "平衡页版本无法校验，当前未发现可展示的英雄专属修正"
            else:
                message = "当前版本未发现英雄专属平衡修正"
            draw.text(
                (outer + 20, panel_y + 63),
                fit_text(draw, message, body_font, width - outer * 2 - 40),
                fill=muted,
                font=body_font,
                anchor="lm",
            )
        else:
            available_width = width - outer * 2 - 40
            columns = 4
            column_gap = 8
            pill_width = (available_width - column_gap * (columns - 1)) // columns
            pill_height = 26
            start_x = outer + 20
            start_y = panel_y + 44
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
