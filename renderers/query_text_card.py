from __future__ import annotations

from typing import Any, Mapping

from fastapi.responses import Response

from renderers.image_utils import (
    encode_png_limited,
    image_footer_left,
    image_footer_right,
    load_image_font,
    wrap_draw_text,
)


_TITLES = {
    "lolban": "账号封禁查询",
    "scammer": "骗子信息查询",
    "peer": "同行信息查询",
    "dynamic": "动态查询结果",
}


def build_query_text_card_response(
    feature: str,
    text: str,
    payload: Mapping[str, Any],
) -> Response:
    """Render an API-owned final query result into a compact PNG card."""
    from PIL import Image, ImageDraw

    width = 920
    outer = 26
    content_width = width - outer * 2 - 44
    title_font = load_image_font(30, bold=True)
    body_font = load_image_font(18)
    small_font = load_image_font(13)

    measure_image = Image.new("RGB", (1, 1))
    measure_draw = ImageDraw.Draw(measure_image)
    logical_lines = []
    for raw_line in str(text or "").splitlines() or [""]:
        logical_lines.extend(
            wrap_draw_text(measure_draw, raw_line, body_font, content_width) or [""]
        )
    logical_lines = logical_lines[:60]

    line_height = 31
    body_height = max(150, len(logical_lines) * line_height + 42)
    header_height = 118
    footer_height = 58
    height = outer + header_height + 14 + body_height + footer_height + outer

    background = (13, 17, 30)
    panel = (24, 30, 49)
    panel_soft = (29, 37, 59)
    border = (52, 65, 91)
    primary = (241, 245, 252)
    muted = (158, 171, 193)
    accent = (70, 207, 224)

    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (outer, outer, width - outer, outer + header_height),
        radius=18,
        fill=panel,
        outline=border,
    )
    draw.text(
        (outer + 24, outer + 24),
        _TITLES.get(feature, "查询结果"),
        fill=primary,
        font=title_font,
    )
    source = str(payload.get("source") or payload.get("provider") or "接口结果").strip()
    draw.text(
        (outer + 24, outer + 75),
        f"结果格式：图片  ·  数据来源：{source}",
        fill=muted,
        font=small_font,
    )
    draw.rounded_rectangle(
        (width - outer - 132, outer + 31, width - outer - 24, outer + 67),
        radius=18,
        fill=(24, 82, 92),
    )
    draw.text(
        (width - outer - 78, outer + 49),
        "查询完成",
        fill=accent,
        font=small_font,
        anchor="mm",
    )

    body_top = outer + header_height + 14
    draw.rounded_rectangle(
        (outer, body_top, width - outer, body_top + body_height),
        radius=18,
        fill=panel_soft,
        outline=border,
    )
    y = body_top + 22
    for line in logical_lines:
        draw.text(
            (outer + 22, y),
            line or " ",
            fill=primary if line else muted,
            font=body_font,
        )
        y += line_height

    footer_y = body_top + body_height
    draw.line(
        (outer + 8, footer_y + 22, width - outer - 8, footer_y + 22),
        fill=border,
        width=1,
    )
    draw.text(
        (outer + 12, footer_y + 34),
        image_footer_left(),
        fill=muted,
        font=small_font,
    )
    draw.text(
        (width - outer - 12, footer_y + 34),
        image_footer_right(),
        fill=muted,
        font=small_font,
        anchor="ra",
    )

    return Response(content=encode_png_limited(image), media_type="image/png")
