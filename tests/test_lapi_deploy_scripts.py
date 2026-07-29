from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "ops" / "Launch-LapiQueryHardening.ps1"
DEPLOY = ROOT / "ops" / "Deploy-LapiQueryHardening.ps1"
ROLLBACK = ROOT / "ops" / "Rollback-LapiQueryHardening.ps1"
VERIFY = ROOT / "ops" / "Test-LapiQueryHardening.ps1"
RELEASE_SCRIPTS = (LAUNCH, DEPLOY, ROLLBACK, VERIFY)


class LapiDeployScriptTests(unittest.TestCase):
    def test_release_scripts_exist_are_utf8_and_ascii_safe(self):
        for path in RELEASE_SCRIPTS:
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("param("), path)
            self.assertNotIn("\ufeff", text)
            self.assertTrue(text.isascii(), path)

    def test_windows_powershell_51_parser_accepts_release_scripts(self):
        if os.name != "nt":
            self.skipTest("Windows PowerShell 5.1 is available only on Windows CI")
        command = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            "$env:LAPI_SCRIPT_PATH,[ref]$tokens,[ref]$errors) | Out-Null; "
            "if ($errors -and $errors.Count -gt 0) { "
            "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
        )
        for path in RELEASE_SCRIPTS:
            env = os.environ.copy()
            env["LAPI_SCRIPT_PATH"] = str(path)
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"{path}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}",
            )

    def test_launcher_exports_raw_scripts_and_parses_before_execution(self):
        text = LAUNCH.read_text(encoding="utf-8")
        self.assertIn("git archive", text)
        self.assertIn("--format=zip", text)
        self.assertIn("Expand-Archive", text)
        self.assertIn("Language.Parser", text)
        self.assertIn("Assert-PowerShellSyntax", text)
        self.assertIn("ExpectedCommit", text)
        self.assertIn("Pinned release commit", text)
        self.assertIn("Patch-WindowsPowerShellGitStderr", text)
        self.assertNotIn("WriteAllLines", text)
        self.assertNotIn("git show", text.lower())

    def test_git_archive_preserves_release_script_bytes(self):
        relative_paths = [
            "ops/Deploy-LapiQueryHardening.ps1",
            "ops/Rollback-LapiQueryHardening.ps1",
            "ops/Test-LapiQueryHardening.ps1",
        ]
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "release-scripts.zip"
            completed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "archive",
                    "--format=zip",
                    f"--output={archive}",
                    "HEAD",
                    *relative_paths,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with zipfile.ZipFile(archive, "r") as bundle:
                for relative_path in relative_paths:
                    archived = bundle.read(relative_path)
                    working_tree = (ROOT / relative_path).read_bytes()
                    self.assertEqual(archived, working_tree, relative_path)
                    self.assertTrue(archived.decode("utf-8").isascii())

    def test_deploy_is_commit_pinned_and_rejects_unsafe_workspace(self):
        text = DEPLOY.read_text(encoding="utf-8")
        self.assertIn("ExpectedCommit", text)
        self.assertIn("merge-base", text)
        self.assertIn("--is-ancestor", text)
        self.assertIn("--untracked-files=no", text)
        self.assertIn('checkout", "--detach', text)
        self.assertNotIn("git reset --hard", text.lower())
        self.assertNotIn("git clean", text.lower())
        self.assertNotIn("pull --force", text.lower())
        self.assertNotIn("WriteAllLines", text)
        self.assertNotIn('("show",', text)
        self.assertIn("$PSScriptRoot", text)

    def test_deploy_requires_backup_acl_tests_build_info_and_rollback(self):
        text = DEPLOY.read_text(encoding="utf-8")
        for marker in (
            "icacls.exe",
            "deployment-record.json",
            "app_env.local.ps1",
            "config.json",
            "upstream_snapshots",
            "unittest discover",
            "Generate-BuildInfo.ps1",
            "Test-LapiQueryHardening.ps1",
            "Rollback-LapiQueryHardening.ps1",
        ):
            self.assertIn(marker, text)

    def test_verifier_covers_old_and_new_contracts(self):
        text = VERIFY.read_text(encoding="utf-8")
        for marker in (
            "/livez",
            "/readyz",
            "/build-info",
            "/shard_query",
            "/aram_augments",
            "/api/v1/groupguard/query",
            "/api/v1/operations/query-observability",
            "groupguard-query-delivery.v1",
            "query-observability.v1",
            "lol-shard-data.json",
            "lol-hero-list.json",
            "aram-mayhem-*.json",
        ):
            self.assertIn(marker, text)

    def test_rollback_restores_exact_previous_commit_and_runtime_files(self):
        text = ROLLBACK.read_text(encoding="utf-8")
        self.assertIn("previous_commit", text)
        self.assertIn('checkout", "--detach', text)
        self.assertIn("Restore-BackupItems", text)
        self.assertIn("build-info mismatch", text)
        self.assertIn("Start-ReleaseService", text)
        self.assertNotIn("git clean", text.lower())

    def test_scripts_do_not_embed_runtime_credentials(self):
        joined = "\n".join(path.read_text(encoding="utf-8") for path in RELEASE_SCRIPTS)
        forbidden = (
            "authorization: bearer",
            "cookie:",
            "mysql_password=",
            "so1_password=",
            "webui_admin_token=",
        )
        lowered = joined.lower()
        for value in forbidden:
            self.assertNotIn(value, lowered)
        self.assertIsNone(
            re.search(r"(?i)(token|password)\s*=\s*['\"][^'\"]+['\"]", joined)
        )

    def test_release_manifest_is_machine_readable_when_present(self):
        path = ROOT / "docs" / "releases" / "LAPI_DEPLOY_001_20260729.json"
        if not path.exists():
            self.skipTest("release manifest is added in a later commit")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["step_id"], "LAPI-DEPLOY-001")
        self.assertEqual(
            data["implementation_commit"],
            "cdebd3643c8f359c1f6dbed8bb3dcecfe6916240",
        )
        self.assertEqual(
            data["production_previous_commit"],
            "bbc8ea2d2687820e4c4a3b400c7568a771f10519",
        )
        self.assertEqual(data["status"], "operator_execution_required")


if __name__ == "__main__":
    unittest.main()
