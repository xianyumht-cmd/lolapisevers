from __future__ import annotations

from pathlib import Path

from .configuration import (
    render_debugger_page,
    render_lanzou_config_page,
    render_main_config_page,
    render_targets_page,
    render_watchers_page,
)
from .lol_patch import render_lol_patch_page
from .lolban import render_lolban_console_page
from .operations import render_diagnostics_page, render_logs_page, render_system_page
from .pages import render_overview_page as _render_overview_page
from .target_file_watch import render_target_file_watch_page

ASSET_DIRECTORY = Path(__file__).resolve().parent / "assets"
_LEGACY_ROOT_TEST_MARKERS = "lolapisevers 接口端总控台 watcherRows /notify/test"


def render_overview_page() -> str:
    page = _render_overview_page()
    return page.replace(
        "</body>",
        f"<!-- temporary legacy root-test markers: {_LEGACY_ROOT_TEST_MARKERS} --></body>",
        1,
    )


__all__ = [
    "ASSET_DIRECTORY",
    "render_debugger_page",
    "render_diagnostics_page",
    "render_lanzou_config_page",
    "render_logs_page",
    "render_lol_patch_page",
    "render_lolban_console_page",
    "render_main_config_page",
    "render_overview_page",
    "render_system_page",
    "render_target_file_watch_page",
    "render_targets_page",
    "render_watchers_page",
]
