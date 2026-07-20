from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ServiceLogIsolationTests(unittest.TestCase):
    def test_child_and_supervisor_logs_are_separate(self):
        run_service = (PROJECT_ROOT / "ops" / "run_service.ps1").read_text(encoding="utf-8-sig")
        install_service = (PROJECT_ROOT / "ops" / "install_persistence.ps1").read_text(encoding="utf-8-sig")

        self.assertIn('"main_api.stdout.log"', run_service)
        self.assertIn('"main_api.stderr.log"', run_service)
        self.assertIn('"lanzou_monitor.stdout.log"', run_service)
        self.assertIn('"lanzou_monitor.stderr.log"', run_service)

        self.assertIn('"supervisor.stdout.log"', install_service)
        self.assertIn('"supervisor.stderr.log"', install_service)

        self.assertIsNone(
            re.search(r"\$mainStdout\s*=.*service\.stdout\.log", run_service, re.IGNORECASE),
            "main API must not write to the NSSM supervisor stdout log",
        )
        self.assertIsNone(
            re.search(r"\$mainStderr\s*=.*service\.stderr\.log", run_service, re.IGNORECASE),
            "main API must not write to the NSSM supervisor stderr log",
        )

    def test_locked_log_rotation_has_a_fallback(self):
        run_service = (PROJECT_ROOT / "ops" / "run_service.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("function Prepare-LogPath", run_service)
        self.assertIn("Could not rotate locked log", run_service)
        self.assertIn("return $fallbackPath", run_service)

    def test_webui_log_catalog_exposes_all_process_layers(self):
        log_facade = (PROJECT_ROOT / "lanzou_update_push_api_server" / "log_facade.py").read_text(
            encoding="utf-8-sig"
        )
        for name in [
            "supervisor_stdout",
            "supervisor_stderr",
            "main_stdout",
            "main_stderr",
            "lanzou_stdout",
            "lanzou_stderr",
        ]:
            self.assertIn(f'"{name}"', log_facade)


if __name__ == "__main__":
    unittest.main()
