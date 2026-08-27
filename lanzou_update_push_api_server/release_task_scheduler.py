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
_EXIT_CODE_FILE = "deployment.exitcode"
_STARTED_FILE = "deployment.started"
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


def _tasklist_executable() -> str:
    if _is_windows():
        system_root = Path(os.getenv("SystemRoot") or r"C:\Windows")
        candidate = system_root / "System32" / "tasklist.exe"
        if candidate.is_file():
            return str(candidate)
    return "tasklist.exe"


def _decode_console_output(raw: bytes | None) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "gb18030", "cp936"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def _tasklist_has_pid(pid: int) -> bool:
    if not _is_windows() or pid <= 0:
        return False
    try:
        completed = _subprocess.run(
            [
                _tasklist_executable(),
                "/FI",
                f"PID eq {pid}",
                "/FO",
                "CSV",
                "/NH",
            ],
            stdin=_subprocess.DEVNULL,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.STDOUT,
            check=False,
            timeout=4.0,
        )
    except (OSError, _subprocess.SubprocessError):
        return False
    if completed.returncode != 0:
        return False
    text = _decode_console_output(completed.stdout)
    # CSV field 2 is PID.  This regex intentionally avoids localized headings.
    return bool(re.search(rf'(?:^|,)\s*"?{int(pid)}"?\s*(?:,|$)', text))


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
            if handle:
                try:
                    exit_code = ctypes.c_ulong()
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        return int(exit_code.value) == still_active
                finally:
                    kernel32.CloseHandle(handle)
        except Exception:
            pass
        # A service account may fail OpenProcess against a SYSTEM-owned task
        # even when the process exists. tasklist is a second independent probe.
        return _tasklist_has_pid(process_id)

    try:
        os.kill(process_id, 0)
    except (OSError, ProcessLookupError, PermissionError):
        return False
    return True


def _read_int(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    if not re.fullmatch(r"-?\d+", text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _deployment_dir_for_pid(pid: int) -> Path | None:
    try:
        wanted = int(pid)
    except (TypeError, ValueError):
        return None
    if wanted <= 0:
        return None
    try:
        candidates = list(core._UPDATE_HOME.glob(f"release-*/{_PID_FILE}"))
    except OSError:
        return None
    for pid_file in candidates:
        if _read_int(pid_file) == wanted:
            return pid_file.parent
    return None


def deployment_process_alive(pid: int) -> bool:
    """Task-aware liveness probe used by WebUI deployment reconciliation.

    After the 6178 service restarts, Python loses its in-memory Popen wrapper.
    The persisted deployment.pid + deployment.exitcode files let the new process
    still classify the Task Scheduler-owned launcher correctly.
    """

    staging = _deployment_dir_for_pid(pid)
    if staging is not None:
        exit_code = _read_int(staging / _EXIT_CODE_FILE)
        if exit_code is not None:
            return False
    return _process_alive(pid)


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
    exit_code_file: Path,
    started_file: Path,
) -> str:
    helper_q = _ps_quote(str(helper))
    launch_log_q = _ps_quote(str(launch_log))
    pid_file_q = _ps_quote(str(pid_file))
    exit_code_q = _ps_quote(str(exit_code_file))
    started_q = _ps_quote(str(started_file))
    return f'''$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
$helperPath = {helper_q}
$launchLog = {launch_log_q}
$pidPath = {pid_file_q}
$exitCodePath = {exit_code_q}
$startedPath = {started_q}
Remove-Item -LiteralPath $exitCodePath -Force -ErrorAction SilentlyContinue
Set-Content -LiteralPath $pidPath -Value ([string]$PID) -Encoding ASCII -Force
Set-Content -LiteralPath $startedPath -Value ((Get-Date).ToString("o")) -Encoding ASCII -Force
function Write-Launch([string]$Message) {{
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss.fff")
    Add-Content -LiteralPath $launchLog -Value ("[" + $stamp + "] " + $Message) -Encoding UTF8
}}
Write-Launch ("Task Scheduler launcher started. PID=" + $PID + "; User=" + $env:USERNAME)
$code = 1
try {{
    & $helperPath *>> $launchLog
    $code = $LASTEXITCODE
    if ($null -eq $code) {{ $code = 0 }}
    Write-Launch ("Verified helper exited. ExitCode=" + $code)
}} catch {{
    $code = 1
    Write-Launch ("Launcher exception: " + ($_ | Out-String))
}} finally {{
    try {{
        Set-Content -LiteralPath $exitCodePath -Value ([string]$code) -Encoding ASCII -Force
    }} catch {{
        Write-Launch ("Failed to persist deployment.exitcode: " + ($_ | Out-String))
    }}
}}
exit $code
'''


def _write_task_launcher(
    helper: Path,
    launch_log: Path,
    pid_file: Path,
    exit_code_file: Path,
    started_file: Path,
) -> Path:
    launcher = helper.parent / _TASK_LAUNCHER
    launcher.write_text(
        _task_launcher_script(
            helper=helper,
            launch_log=launch_log,
            pid_file=pid_file,
            exit_code_file=exit_code_file,
            started_file=started_file,
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
    # /Run starts the task immediately; /ST only makes the ONCE definition valid.
    # Using a short future clock time avoids locale-dependent /SD dates.
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


def _wait_for_pid(pid_file: Path, *, timeout: float = 8.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = _read_int(pid_file)
        if pid is not None and pid > 0:
            return pid
        time.sleep(0.1)
    raise OSError("Task Scheduler 已接受部署任务，但 8 秒内未收到 PowerShell PID 握手。")


class _ScheduledTaskProcess:
    def __init__(self, pid: int, exit_code_file: Path) -> None:
        self.pid = int(pid)
        self._exit_code_file = Path(exit_code_file)

    def poll(self) -> int | None:
        exit_code = _read_int(self._exit_code_file)
        if exit_code is not None:
            return exit_code
        return None if _process_alive(self.pid) else 1


def launch_verified_helper(helper: Path, launch_log: Path) -> _ScheduledTaskProcess:
    """Start a verified Release helper under Task Scheduler and require handshake."""

    helper = Path(helper).resolve()
    launch_log = Path(launch_log)
    intercepted, verified = _is_verified_helper_command(
        [_powershell_executable(), "-File", str(helper)]
    )
    if not intercepted or verified is None:
        raise OSError("拒绝启动：Release helper 不在受信任的 updater staging 目录。")

    staging = verified.parent
    pid_file = staging / _PID_FILE
    exit_code_file = staging / _EXIT_CODE_FILE
    started_file = staging / _STARTED_FILE
    for path in (pid_file, exit_code_file, started_file):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    launcher = _write_task_launcher(
        verified,
        launch_log,
        pid_file,
        exit_code_file,
        started_file,
    )
    _register_and_run_task(launcher)
    pid = _wait_for_pid(pid_file)
    process = _ScheduledTaskProcess(pid, exit_code_file)

    # PID handshake is necessary but not enough: reject a task that wrote the
    # handshake and died immediately before the helper had a chance to start.
    time.sleep(0.35)
    immediate = process.poll()
    if immediate is not None:
        raise OSError(f"Task Scheduler 部署进程握手后立即退出：ExitCode={immediate}")
    return process


class SchedulerSubprocessProxy:
    """Compatibility bridge for the existing controller Popen call.

    The formal Windows path is Task Scheduler.  Non-Release subprocess calls are
    still delegated to the stdlib subprocess module unchanged.
    """

    def __init__(self, original: Any) -> None:
        self._original = original

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)

    def Popen(self, command: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
        intercepted, helper = _is_verified_helper_command(command)
        if not intercepted or helper is None:
            return self._original.Popen(command, *args, **kwargs)

        launch_stream = kwargs.get("stdout")
        stream_name = str(getattr(launch_stream, "name", "") or "").strip()
        launch_log = Path(stream_name) if stream_name else helper.parent / "launch.log"

        # The controller opens launch.log before calling Popen so a normal child
        # process can inherit that handle.  The Task Scheduler path does not
        # inherit the handle; its PowerShell launcher opens the same file with
        # *>>.  Keeping the controller handle open races Out-File on Windows and
        # can make a verified deployment die with FileOpenFailure before the
        # helper starts.  Release that caller-owned stream before scheduling.
        if stream_name and launch_stream is not None:
            try:
                flush = getattr(launch_stream, "flush", None)
                if callable(flush):
                    flush()
            except (OSError, ValueError):
                pass
            try:
                close = getattr(launch_stream, "close", None)
                if callable(close):
                    close()
            except (OSError, ValueError) as exc:
                raise OSError("无法释放 Release launch.log 文件句柄。") from exc

        return launch_verified_helper(helper, launch_log)


def install(controller_module: Any) -> None:
    current = controller_module.subprocess
    if not isinstance(current, SchedulerSubprocessProxy):
        controller_module.subprocess = SchedulerSubprocessProxy(current)

    # The controller persists only a PID across its own service restart.  Make
    # its reconciliation task-aware as well, so a SYSTEM-owned process is not
    # declared dead merely because OpenProcess visibility differs by account.
    if getattr(controller_module, "_process_alive", None) is not deployment_process_alive:
        controller_module._process_alive = deployment_process_alive


__all__ = [
    "SchedulerSubprocessProxy",
    "deployment_process_alive",
    "install",
    "launch_verified_helper",
]
