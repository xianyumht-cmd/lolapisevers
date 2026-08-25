import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lanzou_update_push_api_server import release_task_scheduler as launcher


class ReleaseTaskSchedulerTests(unittest.TestCase):
    def test_task_launcher_writes_pid_started_and_exitcode_markers(self):
        helper = Path(r"C:\ProgramData\LOLDataSystem\updates\release-1\Start-VerifiedReleaseUpdate.ps1")
        log = helper.parent / "launch.log"
        pid_file = helper.parent / "deployment.pid"
        exit_file = helper.parent / "deployment.exitcode"
        started_file = helper.parent / "deployment.started"
        script = launcher._task_launcher_script(
            helper=helper,
            launch_log=log,
            pid_file=pid_file,
            exit_code_file=exit_file,
            started_file=started_file,
        )
        self.assertLess(script.index("Set-Content -LiteralPath $pidPath"), script.index("Task Scheduler launcher started"))
        self.assertIn("Set-Content -LiteralPath $startedPath", script)
        self.assertIn("Set-Content -LiteralPath $exitCodePath", script)
        self.assertIn("& $helperPath *>> $launchLog", script)
        self.assertIn("Launcher exception", script)

    def test_non_release_popen_delegates_to_original(self):
        original = SimpleNamespace(Popen=Mock(return_value="delegated"))
        proxy = launcher.SchedulerSubprocessProxy(original)
        with patch.object(launcher, "_is_windows", return_value=True):
            result = proxy.Popen(["powershell.exe", "-File", "other.ps1"], cwd="x")
        self.assertEqual(result, "delegated")
        original.Popen.assert_called_once()

    def test_verified_helper_proxy_calls_explicit_scheduler_api(self):
        with tempfile.TemporaryDirectory() as temp:
            update_home = Path(temp)
            staging = update_home / "release-123-aabbccddeeff"
            staging.mkdir()
            helper = staging / "Start-VerifiedReleaseUpdate.ps1"
            helper.write_text("Write-Host ok", encoding="utf-8-sig")
            launch_log = staging / "launch.log"
            launch_log.touch()

            original = SimpleNamespace(Popen=Mock())
            proxy = launcher.SchedulerSubprocessProxy(original)
            fake_stream = SimpleNamespace(name=str(launch_log))
            fake_process = SimpleNamespace(pid=4321, poll=Mock(return_value=None))

            with (
                patch.object(launcher, "_is_windows", return_value=True),
                patch.object(launcher.core, "_UPDATE_HOME", update_home),
                patch.object(launcher, "launch_verified_helper", return_value=fake_process) as launch,
            ):
                process = proxy.Popen(
                    ["powershell.exe", "-NoProfile", "-File", str(helper)],
                    stdout=fake_stream,
                )

            self.assertIs(process, fake_process)
            launch.assert_called_once()
            called_helper, called_log = launch.call_args.args
            self.assertEqual(called_helper.resolve(), helper.resolve())
            self.assertEqual(Path(called_log), launch_log)
            original.Popen.assert_not_called()

    def test_explicit_launch_requires_pid_handshake_and_live_process(self):
        with tempfile.TemporaryDirectory() as temp:
            update_home = Path(temp)
            staging = update_home / "release-123-aabbccddeeff"
            staging.mkdir()
            helper = staging / "Start-VerifiedReleaseUpdate.ps1"
            helper.write_text("Write-Host ok", encoding="utf-8-sig")
            launch_log = staging / "launch.log"

            with (
                patch.object(launcher, "_is_windows", return_value=True),
                patch.object(launcher.core, "_UPDATE_HOME", update_home),
                patch.object(launcher, "_register_and_run_task") as register,
                patch.object(launcher, "_wait_for_pid", return_value=4321),
                patch.object(launcher, "_process_alive", return_value=True),
                patch.object(launcher.time, "sleep"),
            ):
                process = launcher.launch_verified_helper(helper, launch_log)

            self.assertEqual(process.pid, 4321)
            self.assertIsNone(process.poll())
            register.assert_called_once()
            task_launcher = staging / "Task-VerifiedReleaseUpdate.ps1"
            self.assertTrue(task_launcher.is_file())
            rendered = task_launcher.read_text(encoding="utf-8-sig")
            self.assertIn("Start-VerifiedReleaseUpdate.ps1", rendered)
            self.assertIn("deployment.exitcode", rendered)
            self.assertIn("deployment.started", rendered)

    def test_explicit_launch_rejects_immediate_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            update_home = Path(temp)
            staging = update_home / "release-123-aabbccddeeff"
            staging.mkdir()
            helper = staging / "Start-VerifiedReleaseUpdate.ps1"
            helper.write_text("Write-Host ok", encoding="utf-8-sig")
            launch_log = staging / "launch.log"

            with (
                patch.object(launcher, "_is_windows", return_value=True),
                patch.object(launcher.core, "_UPDATE_HOME", update_home),
                patch.object(launcher, "_register_and_run_task"),
                patch.object(launcher, "_wait_for_pid", return_value=4321),
                patch.object(launcher, "_process_alive", return_value=False),
                patch.object(launcher.time, "sleep"),
            ):
                with self.assertRaisesRegex(OSError, "握手后立即退出"):
                    launcher.launch_verified_helper(helper, launch_log)

    def test_deployment_process_alive_prefers_persisted_exit_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            update_home = Path(temp)
            staging = update_home / "release-123-aabbccddeeff"
            staging.mkdir()
            (staging / "deployment.pid").write_text("4321", encoding="ascii")
            (staging / "deployment.exitcode").write_text("1", encoding="ascii")
            with (
                patch.object(launcher.core, "_UPDATE_HOME", update_home),
                patch.object(launcher, "_process_alive", return_value=True),
            ):
                self.assertFalse(launcher.deployment_process_alive(4321))

    def test_deployment_process_alive_survives_service_restart_by_pid_file(self):
        with tempfile.TemporaryDirectory() as temp:
            update_home = Path(temp)
            staging = update_home / "release-123-aabbccddeeff"
            staging.mkdir()
            (staging / "deployment.pid").write_text("4321", encoding="ascii")
            with (
                patch.object(launcher.core, "_UPDATE_HOME", update_home),
                patch.object(launcher, "_process_alive", return_value=True),
            ):
                self.assertTrue(launcher.deployment_process_alive(4321))

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

    def test_install_is_idempotent_and_patches_controller_liveness(self):
        fake_subprocess = SimpleNamespace(Popen=Mock())
        original_alive = Mock(return_value=False)
        controller = SimpleNamespace(subprocess=fake_subprocess, _process_alive=original_alive)
        launcher.install(controller)
        first = controller.subprocess
        launcher.install(controller)
        self.assertIs(controller.subprocess, first)
        self.assertIsInstance(first, launcher.SchedulerSubprocessProxy)
        self.assertIs(controller._process_alive, launcher.deployment_process_alive)

    def test_wait_for_pid_times_out_when_task_never_handshakes(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "deployment.pid"
            with (
                patch.object(launcher.time, "monotonic", side_effect=[0.0, 0.0, 9.0]),
                patch.object(launcher.time, "sleep"),
            ):
                with self.assertRaises(OSError):
                    launcher._wait_for_pid(missing, timeout=8.0)


if __name__ == "__main__":
    unittest.main()
