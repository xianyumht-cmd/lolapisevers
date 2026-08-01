from __future__ import annotations

from .parser_center_ui import render_parser_center_page as _render_parser_center_page


def render_parser_center_page() -> str:
    page = _render_parser_center_page()
    marker = "*{box-sizing:border-box}"
    if marker not in page:
        raise RuntimeError("parser center style marker is missing")
    return page.replace(
        marker,
        ".hidden{display:none!important}" + marker,
        1,
    )
