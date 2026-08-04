from __future__ import annotations

from pathlib import Path

from .pages import render_overview_page

ASSET_DIRECTORY = Path(__file__).resolve().parent / "assets"

__all__ = ["ASSET_DIRECTORY", "render_overview_page"]
