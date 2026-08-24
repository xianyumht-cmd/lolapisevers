import json
import tempfile
import unittest
import zipfile
from pathlib import Path

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
        self.assertIn("$command.Parameters.ContainsKey(\"ProjectRoot\")", script)
        self.assertIn("Updater cannot resolve mandatory deploy parameters", script)
        self.assertNotIn("Get-Command -LiteralPath", script)


if __name__ == "__main__":
    unittest.main()
