from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from lanzou_update_push_api_server.config import AppConfig, WatcherConfig
from lanzou_update_push_api_server.control_ui.lol_patch import render_lol_patch_page
from lanzou_update_push_api_server.server import create_app


ROOT = Path(__file__).resolve().parents[1]
RELEASE_UPDATE_JS = (
    ROOT
    / "lanzou_update_push_api_server"
    / "control_ui"
    / "assets"
    / "release-update.js"
)


class LolPatchWebUiTests(unittest.TestCase):
    def make_config(self, temp_dir: str) -> AppConfig:
        return AppConfig(
            scan_on_start=False,
            state_path=Path(temp_dir) / "state.json",
            watchers=[WatcherConfig(id="demo", title="Demo", url="https://example.test")],
        )

    def test_renderer_uses_patch_service_calendar_and_existing_update_controls(self) -> None:
        status = {
            "date": "2026-09-10",
            "patch": "26.18",
            "is_update_today": True,
            "next_update_date": "2026-09-23",
            "next_patch": "26.19",
            "source": "riot_patch_schedule_snapshot_2026",
            "source_url": "https://support-leagueoflegends.riotgames.com/hc/en-us/articles/360018987893-Patch-Schedule-League-of-Legends",
            "checked_at": "2026-09-10T12:30:00+08:00",
            "event_id": "lol-patch-26.18-2026-09-10",
            "schedule_timezone": "Asia/Shanghai",
        }
        with patch(
            "lanzou_update_push_api_server.control_ui.lol_patch.get_patch_status",
            return_value=status,
        ):
            page = render_lol_patch_page()

        self.assertIn('data-console-ui="lol-patch"', page)
        self.assertIn('href="/lol-patch" class="nav-link is-active"', page)
        self.assertIn("LOL 更新日", page)
        self.assertIn("26.18", page)
        self.assertIn("2026-09-10", page)
        self.assertIn("26.19", page)
        self.assertIn("2026-09-23", page)
        self.assertIn("lol-patch-26.18-2026-09-10", page)
        self.assertIn("Asia/Shanghai", page)
        self.assertIn("今天更新", page)
        self.assertIn("下一次", page)
        self.assertIn('/control-assets/operations.js', page)
        self.assertIn('/control-assets/release-update.js', page)
        for element_id in (
            "releaseUpdateCheckButton",
            "releaseUpdateStartButton",
            "releaseCurrentCommit",
            "releaseLatestName",
            "releaseTargetCommit",
            "releaseUpdateState",
            "releaseTokenInput",
            "releaseTokenSaveButton",
            "releaseUpdateResult",
            "releaseUpdateConfirmDialog",
            "releaseUpdateConfirmForm",
        ):
            self.assertIn(f'id="{element_id}"', page)

    def test_shared_release_updater_supports_system_and_lol_patch_pages(self) -> None:
        text = RELEASE_UPDATE_JS.read_text(encoding="utf-8")
        self.assertIn("['system', 'lol-patch'].includes(page)", text)
        for endpoint in (
            "/admin/update/status",
            "/admin/update/token",
            "/admin/update/start",
            "/admin/update/pause",
            "/admin/update/resume",
            "/admin/update/reconnect",
            "/admin/update/reset",
        ):
            self.assertIn(endpoint, text)
        self.assertNotIn("document.body.dataset.consoleUi !== 'system'", text)

    def test_lol_patch_route_and_shell_are_public_with_admin_token_enabled(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"WEBUI_ADMIN_TOKEN": "configured-token"},
            clear=False,
        ):
            app = create_app(self.make_config(temp_dir))
            with TestClient(app) as client:
                page = client.get("/lol-patch")
                legacy_tab = client.get("/?tab=lolpatch", follow_redirects=False)
                protected = client.get("/admin/update/status")

        self.assertEqual(page.status_code, 200)
        self.assertIn('data-console-ui="lol-patch"', page.text)
        self.assertIn("LOL 更新日", page.text)
        self.assertIn('href="/lol-patch" class="nav-link is-active"', page.text)
        self.assertEqual(legacy_tab.status_code, 307)
        self.assertEqual(legacy_tab.headers.get("location"), "/lol-patch")
        self.assertEqual(protected.status_code, 401)


if __name__ == "__main__":
    unittest.main()
