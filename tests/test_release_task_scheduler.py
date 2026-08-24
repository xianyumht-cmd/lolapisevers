import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lanzou_update_push_api_server import release_task_scheduler as launcher


class ReleaseTaskSchedulerTests(unittest.TestCase):
    def test_task_launcher_writes_pid_before_log_and_invokes_helper(self):
        helper = Path(r"C:\ProgramData\LOLDataSystem\updates\release-1\Start-VerifiedReleaseUpdate.ps1")
        log = helper.parent / "launch.log"
        pid_file = helper.parent / "deployment.pid"
        script = launcher._task_launcher_script(
            helper=helper,
            launch_log=log,
            pid_file=pid_file,
        )
        self.assertLess(script.index("Set-Content -LiteralPath $pidPath"), script.index("Start-Sleep"))
        self.assertIn("Task Scheduler launcher started", script)
        self.assertIn("& $helperPath *>> $launchLog", script)
        self.assertIn("Launcher exception", script)

    def test_non_release_popen_delegates_to_original(self):
        original = SimpleNamespace(Popen=Mock(return_value="delegated"))
        proxy = launcher.SchedulerSubprocessProxy(original)
        with patch.object(launcher, "_is_windows", return_value=True):
            result = proxy.Popen(["powershell.exe", "-File", "other.ps1"], cwd="x")
        self.assertEqual(result, "delegated")
        original.Popen.assert_called_once()

    def test_verified_helper_uses_task_scheduler_and_returns_handshake_pid(self):
        with tempfile.TemporaryDirectory() as temp:
            update_home = Path(temp)
            staging = update_home / "release-123-aabbccddeeff"
            staging.mkdir()
            helper = staging / "Start-VerifiedReleaseUpdate.ps1"
            helper.write_text("Write-Host ok", encoding="utf-8-sig")
            launch_log = staging / "launch.log"
            launch_log.touch()
            expected_helper = str(helper.resolve())

            original = SimpleNamespace(Popen=Mock())
            proxy = launcher.SchedulerSubprocessProxy(original)
            fake_stream = SimpleNamespace(name=str(launch_log))

            with (
                patch.object(launcher, "_is_windows", return_value=True),
                patch.object(launcher.core, "_UPDATE_HOME", update_home),
                patch.object(launcher, "_register_and_run_task") as register,
                patch.object(launcher, "_wait_for_pid", return_value=4321),
                patch.object(launcher, "_process_alive", return_value=True),
            ):
                process = proxy.Popen(
                    ["powershell.exe", "-NoProfile", "-File", str(helper)],
                    stdout=fake_stream,
                )
                self.assertEqual(process.pid, 4321)
                self.assertIsNone(process.poll())

            register.assert_called_once()
            original.Popen.assert_not_called()
            task_launcher = staging / "Task-VerifiedReleaseUpdate.ps1"
            self.assertTrue(task_launcher.is_file())
            rendered = task_launcher.read_text(encoding="utf-8-sig")
            self.assertIn(expected_helper, rendered)
            self.assertIn(str(launch_log), rendered)

    def test_verified_helper_outside_update_home_is_not_intercepted(self):
        original = SimpleNamespace(Popen=Mock(return_value="delegated"))
        proxy = launcher.SchedulerSubprocessProxy(original)
        with tempfile.TemporaryDirectory() as temp:
            update_home = Path(temp) / "updates"
            update_home.mkdir()
            outside = Path(temp) / "outside" / "Start-VerifiedReleaseUpdate.ps1"
            outside.parent.mkdir()
            outside.write_text("Write-Host no", encoding="utf-8-sig")
            with (
                patch.object(launcher, "_is_windows", return_value=True),
                patch.object(launcher.core, "_UPDATE_HOME", update_home),
            ):
                result = proxy.Popen(["powershell.exe", "-File", str(outside)])
        self.assertEqual(result, "delegated")
        original.Popen.assert_called_once()

    def test_install_is_idempotent(self):
        fake_subprocess = SimpleNamespace(Popen=Mock())
        controller = SimpleNamespace(subprocess=fake_subprocess)
        launcher.install(controller)
        first = controller.subprocess
        launcher.install(controller)
        self.assertIs(controller.subprocess, first)
        self.assertIsInstance(first, launcher.SchedulerSubprocessProxy)

    def test_wait_for_pid_times_out_when_task_never_handshakes(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "deployment.pid"
            with (
                patch.object(launcher.time, "monotonic", side_effect=[0.0, 0.0, 7.0]),
                patch.object(launcher.time, "sleep"),
            ):
                with self.assertRaises(OSError):
                    launcher._wait_for_pid(missing, timeout=6.0)


if __name__ == "__main__":
    unittest.main()
