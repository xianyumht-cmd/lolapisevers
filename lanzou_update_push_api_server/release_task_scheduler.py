from __future__ import annotations

import os
import re
import subprocess as _subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import release_updater as core


_TASK_NAME = "LOLDataSystem-ReleaseDeploy"
_PID_FILE = "deployment.pid"
_TASK_LAUNCHER = "Task-VerifiedReleaseUpdate.ps1"
_HELPER_NAME = "Start-VerifiedReleaseUpdate.ps1"


def _is_windows() -> bool:
    return os.name == "nt"


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _powershell_executable() -> str:
    if _is_windows():
        system_root = Path(os.getenv("SystemRoot") or r"C:\Windows")
        candidate = (
            system_root
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        if candidate.is_file():
            return str(candidate)
    return "powershell.exe"


def _schtasks_executable() -> str:
    if _is_windows():
        system_root = Path(os.getenv("SystemRoot") or r"C:\Windows")
        candidate = system_root / "System32" / "schtasks.exe"
        if candidate.is_file():
            return str(candidate)
    return "schtasks.exe"


def _decode_console_output(raw: bytes | None) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "gb18030", "cp936"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def _process_alive(pid: int) -> bool:
    try:
        process_id = int(pid)
    except (TypeError, ValueError):
        return False
    if process_id <= 0:
        return False

    if _is_windows():
        try:
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                process_query_limited_information,
                False,
                process_id,
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return int(exit_code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False

    try:
        os.kill(process_id, 0)
    except (OSError, ProcessLookupError, PermissionError):
        return False
    return True


def _is_verified_helper_command(command: Any) -> tuple[bool, Path | None]:
    if not _is_windows() or not isinstance(command, (list, tuple)):
        return False, None
    values = [str(item) for item in command]
    try:
        index = next(i for i, value in enumerate(values) if value.lower() == "-file")
    except StopIteration:
        return False, None
    if index + 1 >= len(values):
        return False, None
    helper = Path(values[index + 1])
    if helper.name.lower() != _HELPER_NAME.lower():
        return False, None
    try:
        helper_resolved = helper.resolve()
        update_home = core._UPDATE_HOME.resolve()
        if not helper_resolved.is_relative_to(update_home):
            return False, None
    except (OSError, RuntimeError, ValueError):
        return False, None
    return True, helper_resolved


def _task_launcher_script(
    *,
    helper: Path,
    launch_log: Path,
    pid_file: Path,
) -> str:
    helper_q = _ps_quote(str(helper))
    launch_log_q = _ps_quote(str(launch_log))
    pid_file_q = _ps_quote(str(pid_file))
    return f'''$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
$helperPath = {helper_q}
$launchLog = {launch_log_q}
$pidPath = {pid_file_q}
Set-Content -LiteralPath $pidPath -Value ([string]$PID) -Encoding ASCII -Force
Start-Sleep -Milliseconds 750
function Write-Launch([string]$Message) {{
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss.fff")
    Add-Content -LiteralPath $launchLog -Value ("[" + $stamp + "] " + $Message) -Encoding UTF8
}}
Write-Launch ("Task Scheduler launcher started. PID=" + $PID + "; User=" + $env:USERNAME)
try {{
    & $helperPath *>> $launchLog
    $code = $LASTEXITCODE
    if ($null -eq $code) {{ $code = 0 }}
    Write-Launch ("Verified helper exited. ExitCode=" + $code)
    exit $code
}} catch {{
    Write-Launch ("Launcher exception: " + ($_ | Out-String))
    exit 1
}}
'''


def _write_task_launcher(helper: Path, launch_log: Path, pid_file: Path) -> Path:
    launcher = helper.parent / _TASK_LAUNCHER
    launcher.write_text(
        _task_launcher_script(
            helper=helper,
            launch_log=launch_log,
            pid_file=pid_file,
        ),
        encoding="utf-8-sig",
    )
    return launcher


def _task_action(launcher: Path) -> str:
    powershell = _powershell_executable()
    return (
        f'"{powershell}" -NoProfile -ExecutionPolicy Bypass '
        f'-File "{launcher}"'
    )


def _run_schtasks(arguments: list[str], *, timeout: float = 12.0) -> None:
    completed = _subprocess.run(
        [_schtasks_executable(), *arguments],
        stdin=_subprocess.DEVNULL,
        stdout=_subprocess.PIPE,
        stderr=_subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )
    if completed.returncode == 0:
        return
    detail = _decode_console_output(completed.stdout)
    if len(detail) > 500:
        detail = detail[-500:]
    suffix = f"：{detail}" if detail else ""
    raise OSError(f"Task Scheduler 命令失败 ExitCode={completed.returncode}{suffix}")


def _register_and_run_task(launcher: Path) -> None:
    # /Run starts the task immediately; /ST only needs to make the ONCE task
    # definition valid. A short future time avoids locale-dependent /SD dates.
    start_time = (datetime.now() + timedelta(minutes=2)).strftime("%H:%M")
    _run_schtasks(
        [
            "/Create",
            "/TN",
            _TASK_NAME,
            "/TR",
            _task_action(launcher),
            "/SC",
            "ONCE",
            "/ST",
            start_time,
            "/RU",
            "SYSTEM",
            "/RL",
            "HIGHEST",
            "/F",
        ]
    )
    _run_schtasks(["/Run", "/TN", _TASK_NAME])


def _wait_for_pid(pid_file: Path, *, timeout: float = 6.0) -> int:
    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        try:
            last_text = pid_file.read_text(encoding="ascii").strip()
        except OSError:
            last_text = ""
        if re.fullmatch(r"\d+", last_text or ""):
            pid = int(last_text)
            if pid > 0:
                return pid
        time.sleep(0.1)
    raise OSError("Task Scheduler 已接受部署任务，但 6 秒内未收到 PowerShell 启动握手。")


class _ScheduledTaskProcess:
    def __init__(self, pid: int) -> None:
        self.pid = int(pid)

    def poll(self) -> int | None:
        return None if _process_alive(self.pid) else 1


class SchedulerSubprocessProxy:
    """Delegate subprocess except for the verified Release helper launch.

    LOLDataSystem runs under NSSM. A grandchild created with DETACHED_PROCESS can
    still disappear before the service switch on some Windows service/job
    configurations. The Task Scheduler service owns this one-shot SYSTEM task,
    so the verified deployer survives 6178/NSSM process-tree changes.
    """

    def __init__(self, original: Any) -> None:
        self._original = original

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)

    def Popen(self, command: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
        intercepted, helper = _is_verified_helper_command(command)
        if not intercepted or helper is None:
            return self._original.Popen(command, *args, **kwargs)

        staging = helper.parent
        launch_stream = kwargs.get("stdout")
        stream_name = str(getattr(launch_stream, "name", "") or "").strip()
        launch_log = Path(stream_name) if stream_name else staging / "launch.log"
        pid_file = staging / _PID_FILE
        try:
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass

        launcher = _write_task_launcher(helper, launch_log, pid_file)
        _register_and_run_task(launcher)
        pid = _wait_for_pid(pid_file)
        return _ScheduledTaskProcess(pid)


def install(controller_module: Any) -> None:
    current = controller_module.subprocess
    if isinstance(current, SchedulerSubprocessProxy):
        return
    controller_module.subprocess = SchedulerSubprocessProxy(current)


__all__ = [
    "SchedulerSubprocessProxy",
    "install",
]
