import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from lanzou_update_push_api_server import release_updater


class ReleaseUpdaterTests(unittest.TestCase):
    def metadata(self, target="a" * 40):
        name = f"LOLDataSystem-full-bug-repair-safe-deploy-{target[:12]}-py311-py314-winps51-v3.zip"
        return name, {
            "schema_version": "lolapisevers-safe-deployment-artifact.v1",
            "filename": name,
            "target_commit": target,
            "zip_sha256": "b" * 64,
            "package_revision": 3,
            "powershell_utf8_parse_input": True,
            "baseline_aware_readiness": True,
        }

    def test_metadata_requires_v3_and_matching_commit_prefix(self):
        name, metadata = self.metadata()
        self.assertEqual(release_updater._validate_metadata(metadata, name), "a" * 40)
        bad = dict(metadata, target_commit="c" * 40)
        with self.assertRaises(release_updater.ReleaseUpdateError):
            release_updater._validate_metadata(bad, name)

    def test_safe_extract_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../escape.txt", "bad")
            with self.assertRaises(release_updater.ReleaseUpdateError):
                release_updater._safe_extract(archive, root / "out")

    def test_manifest_requires_all_deployment_safety_flags(self):
        target = "a" * 40
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "package"
            package.mkdir()
            manifest = {
                "target_commit": target,
                "package_revision": 3,
                "deployment": {
                    key: True for key in release_updater._REQUIRED_MANIFEST_FLAGS
                },
            }
            (package / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            path = release_updater._validate_embedded_manifest(root, target)
            self.assertEqual(path, package / "manifest.json")
            manifest["deployment"]["automatic_rollback"] = False
            (package / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with self.assertRaises(release_updater.ReleaseUpdateError):
                release_updater._validate_embedded_manifest(root, target)

    def test_helper_uses_safe_powershell_quotes_and_external_deployer(self):
        deployer = Path(r"D:\stage\Deploy-FullBugRepairSafe.ps1")
        log_path = Path(r"D:\stage\update.log")
        script = release_updater._helper_script(deployer, log_path)
        self.assertIn("Get-Command -Name $deployPath", script)
        self.assertIn('$command.Parameters.ContainsKey("ProjectRoot")', script)
        self.assertIn("Updater cannot resolve mandatory deploy parameters", script)
        self.assertNotIn("Get-Command -LiteralPath", script)

    def test_default_mirrors_include_multiple_current_accelerators(self):
        with patch.dict("os.environ", {"LOLAPI_RELEASE_MIRRORS": ""}, clear=False):
            values = release_updater._mirror_prefixes()
        labels = [label for label, _prefix in values]
        self.assertIn("gh-proxy.com", labels)
        self.assertIn("ghproxy.net", labels)
        self.assertIn("ghfast.top", labels)
        self.assertIn("gh.ddlc.top", labels)
        self.assertGreaterEqual(len(labels), 4)

    def test_mirror_candidates_never_receive_github_authorization(self):
        asset = {
            "url": "https://api.github.com/repos/xianyumht-cmd/lolapisevers/releases/assets/123",
            "browser_download_url": (
                "https://github.com/xianyumht-cmd/lolapisevers/releases/download/"
                "lolapi-test/package.zip"
            ),
        }
        candidates = release_updater._download_candidates(asset, "secret-token")
        mirrors = [item for item in candidates if item["mirror"]]
        self.assertGreaterEqual(len(mirrors), 4)
        self.assertTrue(all("Authorization" not in item["headers"] for item in mirrors))
        api = next(item for item in candidates if item["label"] == "github-api")
        self.assertEqual(api["headers"]["Authorization"], "Bearer secret-token")

    def test_rank_download_candidates_prefers_fast_success_and_keeps_fallbacks(self):
        candidates = [
            {"label": "slow", "url": "https://slow", "headers": {}, "mirror": True},
            {"label": "fast", "url": "https://fast", "headers": {}, "mirror": True},
            {"label": "failed", "url": "https://failed", "headers": {}, "mirror": False},
        ]

        def fake_probe(candidate):
            values = {
                "slow": {"label": "slow", "ok": True, "elapsed_ms": 500, "error": ""},
                "fast": {"label": "fast", "ok": True, "elapsed_ms": 80, "error": ""},
                "failed": {"label": "failed", "ok": False, "elapsed_ms": 20, "error": "HTTP 502"},
            }
            return values[candidate["label"]]

        with patch.object(release_updater, "_probe_candidate", side_effect=fake_probe):
            ranked, probes = release_updater._rank_download_candidates(candidates)
        self.assertEqual([item["label"] for item in ranked], ["fast", "slow", "failed"])
        self.assertEqual(len(probes), 3)

    def test_status_poll_during_update_stays_local(self):
        running_state = {
            "status": "downloading",
            "phase": "download",
            "release": "lolapi-test",
            "target_commit": "a" * 40,
            "package": "package.zip",
            "package_bytes": 123,
        }
        with (
            patch.object(release_updater, "_read_state", return_value=running_state),
            patch.object(
                release_updater,
                "load_build_info",
                return_value={"commit_sha": "b" * 40, "release": "old"},
            ),
            patch.object(release_updater, "_request_json") as request_json,
        ):
            result = release_updater.release_update_status()
        request_json.assert_not_called()
        self.assertEqual(result["status"], "updating")
        self.assertEqual(result["target_commit"], "a" * 40)
        self.assertEqual(result["package_bytes"], 123)


if __name__ == "__main__":
    unittest.main()
