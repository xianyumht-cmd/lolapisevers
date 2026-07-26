import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")


@unittest.skipUnless(POWERSHELL, "PowerShell is required")
class RuntimeSourceManifestTests(unittest.TestCase):
    def _run(self, root: Path, script: str, *, expect_ok: bool = True):
        completed = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if expect_ok and completed.returncode != 0:
            self.fail(
                f"PowerShell failed ({completed.returncode}):\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
        return completed

    def _create_repository(self, root: Path):
        (root / "ops").mkdir()
        (root / "scripts").mkdir()
        (root / "core").mkdir()
        (root / "app.py").write_text("print('release')\n", encoding="utf-8")
        (root / "cache.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "db.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "so1_client.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "requirements.txt").write_text("example==1.0\n", encoding="utf-8")
        (root / "README.md").write_text("release docs\n", encoding="utf-8")
        shutil.copy2(
            PROJECT_ROOT / "scripts" / "RuntimeSourceManifest.ps1",
            root / "scripts" / "RuntimeSourceManifest.ps1",
        )
        shutil.copy2(
            PROJECT_ROOT / "scripts" / "Generate-BuildInfo.ps1",
            root / "scripts" / "Generate-BuildInfo.ps1",
        )
        shutil.copy2(
            PROJECT_ROOT / "ops" / "run_service.ps1",
            root / "ops" / "run_service.ps1",
        )
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Runtime Manifest Test",
                "-c",
                "user.email=runtime-manifest@example.invalid",
                "commit",
                "-m",
                "fixture",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )

    def test_manifest_ignores_docs_but_detects_runtime_drift(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._create_repository(root)
            generator = root / "scripts" / "Generate-BuildInfo.ps1"
            self._run(root, f"& '{generator}' -OutputPath '{root / 'build-info.json'}'")
            payload = json.loads((root / "build-info.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["config_schema_version"], "5")
            paths = {entry["path"] for entry in payload["source_manifest"]["files"]}
            self.assertIn("app.py", paths)
            self.assertIn("ops/run_service.ps1", paths)
            self.assertNotIn("README.md", paths)
            self.assertRegex(
                payload["source_manifest"]["aggregate_sha256"],
                r"^[0-9a-f]{64}$",
            )

            (root / "README.md").write_text("docs-only change\n", encoding="utf-8")
            helper = root / "scripts" / "RuntimeSourceManifest.ps1"
            validation = (
                f". '{helper}'; "
                f"$b=Get-Content -Raw '{root / 'build-info.json'}'|ConvertFrom-Json; "
                f"Assert-RuntimeSourceManifest -RepositoryRoot '{root}' "
                "-ExpectedManifest $b.source_manifest | Out-Null"
            )
            self._run(root, validation)

            (root / "app.py").write_text("print('drift')\n", encoding="utf-8")
            failed = self._run(root, validation, expect_ok=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("Runtime source manifest mismatch: app.py", failed.stderr)

    def test_untracked_executable_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._create_repository(root)
            (root / "unexpected.py").write_text("VALUE = 2\n", encoding="utf-8")
            generator = root / "scripts" / "Generate-BuildInfo.ps1"
            failed = self._run(
                root,
                f"& '{generator}' -OutputPath '{root / 'build-info.json'}'",
                expect_ok=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("Untracked executable source files", failed.stderr)


if __name__ == "__main__":
    unittest.main()
