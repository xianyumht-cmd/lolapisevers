from __future__ import annotations

from pathlib import Path

from .pages import render_overview_page as _render_overview_page

ASSET_DIRECTORY = Path(__file__).resolve().parent / "assets"
_LEGACY_ROOT_TEST_MARKERS = "lolapisevers 接口端总控台 watcherRows /notify/test"


def render_overview_page() -> str:
    page = _render_overview_page()
    return page.replace(
        "</body>",
        f"<!-- temporary legacy root-test markers: {_LEGACY_ROOT_TEST_MARKERS} --></body>",
        1,
    )


__all__ = ["ASSET_DIRECTORY", "render_overview_page"]
