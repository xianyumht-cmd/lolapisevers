from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from core.build_info import load_build_info

from . import release_updater as core


ReleaseUpdateError = core.ReleaseUpdateError

_ACTIVE_STATUSES = {
    "queued",
    "running",
    "downloading",
    "verifying",
    "extracting",
    "scheduling",
    "reconnecting",
    "resetting",
}
_DEPLOY_STATUSES = {"scheduled", "deploying"}
_RESUMABLE_STATUSES = {"paused", "interrupted", "stalled", "failed"}
_TERMINAL_STATUSES = {"current", "complete"}
_RESETTABLE_STATUSES = {
    "queued",
    "running",
    "downloading",
    "reconnecting",
    "resetting",
    "paused",
    "interrupted",
    "stalled",
    "failed",
}

_LOCK = threading.RLock()
_WORKER: threading.Thread | None = None
_WORKER_RUN_ID = ""
_PAUSE_EVENT = threading.Event()
_RECONNECT_EVENT = threading.Event()
_RESET_EVENT = threading.Event()


class _ReconnectRequested(RuntimeError):
    pass


class _ResetRequested(RuntimeError):
    pass


class _LowSpeed(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _worker_alive() -> bool:
    with _LOCK:
        worker = _WORKER
        return bool(worker is not None and worker.is_alive())


def _iso_age_seconds(raw: Any) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(
            0.0,
            (datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds(),
        )
    except (TypeError, ValueError):
        return None


def _state_age_seconds(state: dict[str, Any]) -> float | None:
    return _iso_age_seconds(state.get("updated_at"))


def _process_alive(pid: int) -> bool:
    try:
        process_id = int(pid)
    except (TypeError, ValueError):
        return False
    if process_id <= 0:
        return False

    if os.name == "nt":
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


def _file_exists(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return Path(text).is_file()
    except OSError:
        return False


def _write_runtime_state(
    *,
    status: str,
    phase: str,
    message: str = "",
    **fields: Any,
) -> dict[str, Any]:
    with _LOCK:
        run_id = _WORKER_RUN_ID
    if status != "failed" and "error" not in fields:
        # _update_state intentionally preserves old fields.  Explicitly clear an
        # earlier failure once the state machine has made forward progress so a
        # successful 100%/deploying state can never keep a stale ConnectTimeout.
        fields["error"] = ""
    return core._update_state(
        status=status,
        phase=phase,
        message=message,
        worker_pid=os.getpid(),
        run_id=run_id,
        heartbeat_at=_utc_now(),
        **fields,
    )


def _reconcile_deployment_state(state: dict[str, Any]) -> dict[str, Any]:
    status = str(state.get("status") or "").lower()
    if status not in _DEPLOY_STATUSES:
        return state

    target = str(state.get("target_commit") or "").strip().lower()
    current_info = load_build_info()
    current_commit = str(current_info.get("commit_sha") or "unknown").strip().lower()
    pid = int(state.get("deployment_pid") or state.get("pid") or 0)
    process_alive = _process_alive(pid)
    scheduled_age = _iso_age_seconds(state.get("scheduled_at"))
    log_exists = _file_exists(state.get("log"))
    launch_log_exists = _file_exists(state.get("launch_log"))

    reconciled = dict(state)
    reconciled.update(
        {
            "deployment_pid": pid,
            "deployment_process_alive": process_alive,
            "deployment_log_exists": log_exists,
            "deployment_launch_log_exists": launch_log_exists,
        }
    )

    if process_alive:
        reconciled["status"] = "deploying"
        if target and current_commit == target:
            reconciled["phase"] = "post_switch_verification"
            reconciled["message"] = "生产代码已切到目标提交，独立部署进程正在执行后置验证。"
        else:
            reconciled["phase"] = "deploying"
            reconciled["message"] = "独立部署进程运行中，正在执行候选验证与生产切换。"
        reconciled["error"] = ""
        return reconciled

    if target and current_commit == target:
        reconciled.update(
            {
                "status": "complete",
                "phase": "complete",
                "message": "独立部署进程已结束，当前生产提交已切换到目标版本。",
                "completed_at": _utc_now(),
                "updated_at": _utc_now(),
                "error": "",
            }
        )
        core._write_state(reconciled)
        return reconciled

    # Give Windows a short process-table visibility grace period immediately
    # after Popen.  After that, a dead PID + unchanged commit is a real failed
    # deployment, not a perpetual "scheduled" success state.
    if scheduled_age is None or scheduled_age < 8.0:
        reconciled.update(
            {
                "status": "deploying",
                "phase": "deployment_starting",
                "message": "独立部署进程已启动，正在等待进程状态与生产提交确认。",
                "error": "",
            }
        )
        return reconciled

    if launch_log_exists:
        diagnostic = "独立部署进程已退出且生产提交未切换；请查看启动日志和升级日志。"
    elif log_exists:
        diagnostic = "独立部署进程已退出且生产提交未切换；请查看升级日志。"
    else:
        diagnostic = "独立部署进程在 update.log 初始化前退出，未检测到生产版本切换。"
    reconciled.update(
        {
            "status": "failed",
            "phase": "deployment_failed",
            "message": "独立部署进程已结束，但生产提交仍不是目标版本。",
            "deployment_failed_at": _utc_now(),
            "updated_at": _utc_now(),
            "error": diagnostic,
        }
    )
    core._write_state(reconciled)
    return reconciled


def _interrupt_or_stall_persisted_state(state: dict[str, Any]) -> dict[str, Any]:
    status = str(state.get("status") or "").lower()
    if status not in _ACTIVE_STATUSES and status != "paused":
        return state

    worker_alive = _worker_alive()
    worker_pid = int(state.get("worker_pid") or 0)
    same_process = worker_pid == os.getpid()
    if worker_alive and same_process:
        age = _state_age_seconds(state)
        if age is not None and age > 45 and status != "paused":
            stale = dict(state)
            stale["status"] = "stalled"
            stale["phase"] = "stalled"
            stale["message"] = "升级 worker 仍存在，但状态心跳超过 45 秒未更新；可重新连接。"
            stale["heartbeat_age_seconds"] = round(age, 1)
            return stale
        return state

    interrupted = dict(state)
    interrupted.update(
        {
            "status": "interrupted",
            "phase": "interrupted",
            "message": "升级任务已因服务重启或进程退出中断，可从现有 .part 断点继续。",
            "interrupted_at": _utc_now(),
            "updated_at": _utc_now(),
            "worker_alive": False,
        }
    )
    core._write_state(interrupted)
    return interrupted


def _controls_for(state: dict[str, Any], worker_alive: bool) -> dict[str, bool]:
    status = str(state.get("status") or "").lower()
    has_target = bool(state.get("target_commit") or state.get("package"))
    return {
        "can_pause": worker_alive
        and status in _ACTIVE_STATUSES
        and status not in {"scheduling"},
        "can_resume": (worker_alive and status == "paused")
        or (not worker_alive and has_target and status in _RESUMABLE_STATUSES),
        "can_reconnect": has_target
        and status not in _DEPLOY_STATUSES
        and (
            (worker_alive and status in (_ACTIVE_STATUSES | {"paused", "stalled"}))
            or (not worker_alive and status in _RESUMABLE_STATUSES)
        ),
        "can_reset": has_target and status in _RESETTABLE_STATUSES,
    }


def _local_status_base(state: dict[str, Any]) -> dict[str, Any]:
    current = load_build_info()
    current_commit = str(current.get("commit_sha") or "unknown").lower()
    token = core._read_token()
    worker_alive = _worker_alive()
    age = _state_age_seconds(state)
    status = str(state.get("status") or "").lower()
    public_status = status
    if status in _ACTIVE_STATUSES or status in _DEPLOY_STATUSES:
        public_status = "updating"
    elif status in _TERMINAL_STATUSES:
        public_status = "current"
    return {
        "ok": True,
        "repository": core.REPOSITORY,
        "current_commit": current_commit,
        "current_release": str(current.get("release") or "unknown"),
        "token_configured": bool(token),
        "token_source": "environment"
        if os.getenv("LOLAPI_UPDATE_GITHUB_TOKEN")
        else ("file" if core._TOKEN_PATH.exists() else "none"),
        "platform_supported": os.name == "nt",
        "update_state": state,
        "mirrors": [label for label, _prefix in core._mirror_prefixes()],
        "latest_release": str(state.get("release") or ""),
        "latest_release_name": str(state.get("release") or ""),
        "published_at": "",
        "target_commit": str(state.get("target_commit") or ""),
        "package_name": str(state.get("package") or ""),
        "package_bytes": int(state.get("package_bytes") or 0),
        "available": status not in _TERMINAL_STATUSES and status not in _DEPLOY_STATUSES,
        "status": public_status,
        "worker_alive": worker_alive,
        "heartbeat_age_seconds": round(age, 1) if age is not None else None,
        "controls": _controls_for(state, worker_alive),
    }


def release_update_status() -> dict[str, Any]:
    state = _reconcile_deployment_state(core._read_state())
    state = _interrupt_or_stall_persisted_state(state)
    status = str(state.get("status") or "").lower()
    if status in (
        _ACTIVE_STATUSES
        | _DEPLOY_STATUSES
        | _RESUMABLE_STATUSES
        | {"paused"}
    ):
        return _local_status_base(state)

    result = core.release_update_status()
    state = result.get("update_state") if isinstance(result.get("update_state"), dict) else {}
    worker_alive = _worker_alive()
    result["worker_alive"] = worker_alive
    result["heartbeat_age_seconds"] = _state_age_seconds(state)
    result["controls"] = _controls_for(state, worker_alive)
    return result


def _min_speed_bps() -> int:
    try:
        value = int(os.getenv("LOLAPI_UPDATE_MIN_BPS", "32768"))
    except ValueError:
        value = 32768
    return max(4 * 1024, min(value, 8 * 1024 * 1024))


def _low_speed_window_seconds() -> float:
    try:
        value = float(os.getenv("LOLAPI_UPDATE_LOW_SPEED_WINDOW", "30"))
    except ValueError:
        value = 30.0
    return max(10.0, min(value, 120.0))


def _pause_if_requested(*, source: str, total: int, expected_bytes: int, offset: int) -> None:
    if not _PAUSE_EVENT.is_set():
        return
    _write_runtime_state(
        status="paused",
        phase="paused",
        message="下载已暂停；断点文件已保留。",
        download_source=source,
        downloaded_bytes=total,
        package_bytes=expected_bytes,
        progress_percent=(round(total * 100.0 / expected_bytes, 1) if expected_bytes else 0.0),
        resumed_bytes=offset,
    )
    last_heartbeat = 0.0
    while _PAUSE_EVENT.is_set():
        if _RESET_EVENT.is_set():
            raise _ResetRequested()
        if _RECONNECT_EVENT.is_set():
            _RECONNECT_EVENT.clear()
            _PAUSE_EVENT.clear()
            raise _ReconnectRequested()
        now = time.monotonic()
        if now - last_heartbeat >= 2.0:
            _write_runtime_state(
                status="paused",
                phase="paused",
                message="下载已暂停；断点文件已保留。",
                download_source=source,
                downloaded_bytes=total,
                package_bytes=expected_bytes,
                progress_percent=(round(total * 100.0 / expected_bytes, 1) if expected_bytes else 0.0),
                resumed_bytes=offset,
            )
            last_heartbeat = now
        time.sleep(0.25)


def _download_one_connection(
    candidate: dict[str, Any],
    destination: Path,
    expected_bytes: int,
) -> int:
    temp = destination.with_suffix(destination.suffix + ".part")
    if _RESET_EVENT.is_set():
        _RESET_EVENT.clear()
        destination.unlink(missing_ok=True)
        temp.unlink(missing_ok=True)

    offset = temp.stat().st_size if temp.exists() else 0
    if expected_bytes and offset > expected_bytes:
        temp.unlink(missing_ok=True)
        offset = 0

    _pause_if_requested(
        source=candidate["label"],
        total=offset,
        expected_bytes=expected_bytes,
        offset=offset,
    )
    if _RECONNECT_EVENT.is_set():
        _RECONNECT_EVENT.clear()
        raise _ReconnectRequested()

    headers = dict(candidate["headers"])
    if offset:
        headers["Range"] = f"bytes={offset}-"

    started = time.perf_counter()
    window_started = started
    window_bytes = 0
    last_state_at = 0.0
    try:
        with requests.get(
            candidate["url"],
            headers=headers,
            timeout=(3.0, 12.0),
            allow_redirects=True,
            stream=True,
        ) as response:
            if response.status_code not in {200, 206}:
                raise ReleaseUpdateError(
                    f"{candidate['label']} 下载失败：HTTP {response.status_code}"
                )
            append = bool(offset and response.status_code == 206)
            if offset and not append:
                offset = 0
            mode = "ab" if append else "wb"
            total = offset
            with temp.open(mode) as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if _RESET_EVENT.is_set():
                        raise _ResetRequested()
                    if _RECONNECT_EVENT.is_set():
                        _RECONNECT_EVENT.clear()
                        raise _ReconnectRequested()
                    _pause_if_requested(
                        source=candidate["label"],
                        total=total,
                        expected_bytes=expected_bytes,
                        offset=offset,
                    )
                    if not chunk:
                        continue
                    total += len(chunk)
                    window_bytes += len(chunk)
                    if total > 1_500_000_000:
                        raise ReleaseUpdateError("Release ZIP 超过允许大小")
                    if expected_bytes and total > expected_bytes:
                        raise ReleaseUpdateError(
                            f"{candidate['label']} 返回大小超过 metadata"
                        )
                    handle.write(chunk)
                    handle.flush()
                    now_perf = time.perf_counter()
                    window_elapsed = max(now_perf - window_started, 0.001)
                    if window_elapsed >= _low_speed_window_seconds():
                        window_speed = window_bytes / window_elapsed
                        if window_bytes > 0 and window_speed < _min_speed_bps():
                            raise _LowSpeed(
                                f"{candidate['label']} 连续 {window_elapsed:.0f}s 仅 {window_speed / 1024:.1f} KB/s"
                            )
                        window_started = now_perf
                        window_bytes = 0

                    now = time.monotonic()
                    if now - last_state_at >= 0.6:
                        elapsed = max(now_perf - started, 0.001)
                        transferred = max(total - offset, 0)
                        percent = (
                            round(total * 100.0 / expected_bytes, 1)
                            if expected_bytes
                            else 0.0
                        )
                        _write_runtime_state(
                            status="downloading",
                            phase="download",
                            message=f"正在从 {candidate['label']} 下载 V3 包",
                            download_source=candidate["label"],
                            downloaded_bytes=total,
                            package_bytes=expected_bytes,
                            progress_percent=percent,
                            speed_mbps=round(transferred / elapsed / 1024 / 1024, 2),
                            resumed_bytes=offset,
                        )
                        last_state_at = now
    except requests.RequestException as exc:
        raise ReleaseUpdateError(
            f"{candidate['label']} 下载失败：{exc.__class__.__name__}"
        ) from exc

    total = temp.stat().st_size if temp.exists() else 0
    if expected_bytes and total != expected_bytes:
        raise ReleaseUpdateError(
            f"{candidate['label']} 大小校验失败：{total} != {expected_bytes}"
        )
    os.replace(temp, destination)
    return total


def _controlled_download_zip(
    asset: dict[str, Any],
    token: str,
    destination: Path,
    expected_bytes: int,
) -> tuple[str, list[dict[str, Any]]]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidates = core._download_candidates(asset, token)
    _write_runtime_state(
        status="running",
        phase="mirror_probe",
        message="正在并行测速 GitHub 与镜像源",
        mirror_candidates=[candidate["label"] for candidate in candidates],
        package_bytes=expected_bytes,
    )
    ranked, probes = core._rank_download_candidates(candidates)
    _write_runtime_state(
        status="running",
        phase="mirror_selected",
        message=f"测速完成，优先使用 {ranked[0]['label']}",
        mirror_probes=probes,
        download_source=ranked[0]["label"],
    )

    errors: list[dict[str, Any]] = []
    for candidate in ranked:
        automatic_attempts = 0
        while automatic_attempts < 3:
            try:
                _write_runtime_state(
                    status="downloading",
                    phase="download",
                    message=f"正在从 {candidate['label']} 下载 V3 包",
                    download_source=candidate["label"],
                    download_errors=errors,
                )
                _download_one_connection(candidate, destination, expected_bytes)
                return candidate["label"], errors
            except _ResetRequested:
                part = destination.with_suffix(destination.suffix + ".part")
                destination.unlink(missing_ok=True)
                part.unlink(missing_ok=True)
                _RESET_EVENT.clear()
                _PAUSE_EVENT.clear()
                _write_runtime_state(
                    status="resetting",
                    phase="resetting",
                    message="已清空当前断点，正在从 0 重新连接下载源。",
                    download_source=candidate["label"],
                    downloaded_bytes=0,
                    progress_percent=0.0,
                )
                continue
            except _ReconnectRequested:
                _PAUSE_EVENT.clear()
                _write_runtime_state(
                    status="reconnecting",
                    phase="reconnecting",
                    message=f"正在重新连接 {candidate['label']}，保留现有断点。",
                    download_source=candidate["label"],
                )
                continue
            except _LowSpeed as exc:
                automatic_attempts += 1
                errors.append({"source": candidate["label"], "error": str(exc)[:240]})
                _write_runtime_state(
                    status="reconnecting",
                    phase="low_speed_reconnect",
                    message=f"{candidate['label']} 持续低速，自动断开并从断点重连（{automatic_attempts}/3）。",
                    download_source=candidate["label"],
                    download_errors=errors,
                )
                continue
            except ReleaseUpdateError as exc:
                automatic_attempts = 3
                errors.append({"source": candidate["label"], "error": str(exc)[:240]})

        _write_runtime_state(
            status="running",
            phase="source_fallback",
            message=f"{candidate['label']} 失败，自动切换下一下载源",
            download_source=candidate["label"],
            download_errors=errors,
        )

    raise ReleaseUpdateError(
        "所有 Release 下载源均失败：" + "；".join(
            f"{item['source']}={item['error']}" for item in errors[-4:]
        )
    )


def _powershell_executable() -> str:
    if os.name == "nt":
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


def _run_update() -> dict[str, Any]:
    if os.name != "nt":
        raise ReleaseUpdateError("一键升级只允许在 Windows 生产机执行")

    _write_runtime_state(
        status="running",
        phase="release_check",
        message="正在检查最新 Release",
        started_at=_utc_now(),
        downloaded_bytes=0,
        progress_percent=0,
        download_errors=[],
    )
    token = core._read_token()
    release = core._request_json(core.LATEST_RELEASE_URL, token)
    zip_asset, metadata_asset = core._select_assets(release)
    zip_name = str(zip_asset.get("name") or "")
    release_name = str(release.get("tag_name") or release.get("name") or "")
    _write_runtime_state(
        status="running",
        phase="metadata",
        message="正在读取并验证官方 metadata",
        release=release_name,
        package=zip_name,
    )
    metadata = core._load_metadata(metadata_asset, token)
    target = core._validate_metadata(metadata, zip_name)
    expected_bytes = int(metadata.get("bytes") or zip_asset.get("size") or 0)
    expected_sha = str(metadata.get("zip_sha256") or "").lower()
    _write_runtime_state(
        status="running",
        phase="metadata_verified",
        message="metadata 已校验，准备测速下载源",
        release=release_name,
        target_commit=target,
        package=zip_name,
        package_bytes=expected_bytes,
    )

    current = str(load_build_info().get("commit_sha") or "unknown").lower()
    if target == current:
        return _write_runtime_state(
            status="current",
            phase="complete",
            message="当前已经是最新版本",
            release=release_name,
            target_commit=target,
            package=zip_name,
        )

    release_id = str(release.get("id") or int(time.time()))
    staging = core._UPDATE_HOME / f"release-{release_id}-{target[:12]}"
    staging.mkdir(parents=True, exist_ok=True)
    zip_path = staging / zip_name
    part_path = zip_path.with_suffix(zip_path.suffix + ".part")

    if _RESET_EVENT.is_set():
        _RESET_EVENT.clear()
        zip_path.unlink(missing_ok=True)
        part_path.unlink(missing_ok=True)
        _write_runtime_state(
            status="resetting",
            phase="resetting",
            message="已清空当前目标版本的本地包与断点。",
            downloaded_bytes=0,
            progress_percent=0.0,
        )

    download_source = "local-cache"
    download_errors: list[dict[str, Any]] = []
    cached_ok = False
    if zip_path.is_file():
        try:
            cached_ok = (
                (not expected_bytes or zip_path.stat().st_size == expected_bytes)
                and core._sha256(zip_path) == expected_sha
            )
        except OSError:
            cached_ok = False
    if cached_ok:
        _write_runtime_state(
            status="verifying",
            phase="local_cache",
            message="命中已校验的本地 V3 包，跳过重新下载",
            download_source=download_source,
            downloaded_bytes=zip_path.stat().st_size,
            package_bytes=expected_bytes,
            progress_percent=100.0,
        )
    else:
        zip_path.unlink(missing_ok=True)
        download_source, download_errors = _controlled_download_zip(
            zip_asset,
            token,
            zip_path,
            expected_bytes,
        )

    _write_runtime_state(
        status="verifying",
        phase="sha256",
        message="下载完成，正在校验 SHA-256",
        download_source=download_source,
        downloaded_bytes=zip_path.stat().st_size,
        package_bytes=expected_bytes,
        progress_percent=100.0,
        download_errors=download_errors,
    )
    actual_sha = core._sha256(zip_path)
    if actual_sha != expected_sha:
        zip_path.unlink(missing_ok=True)
        raise ReleaseUpdateError("Release ZIP SHA-256 校验失败")

    extract_root = staging / "extracted"
    _write_runtime_state(
        status="extracting",
        phase="extract",
        message="SHA-256 已通过，正在安全解压并检查 manifest",
        package_sha256=actual_sha,
    )
    core._safe_extract(zip_path, extract_root)
    manifest_path = core._validate_embedded_manifest(extract_root, target)
    deployer = core._find_deployer(extract_root, manifest_path)
    helper = staging / "Start-VerifiedReleaseUpdate.ps1"
    log_path = staging / "update.log"
    launch_log_path = staging / "launch.log"
    helper.write_text(core._helper_script(deployer, log_path), encoding="utf-8-sig")

    _write_runtime_state(
        status="scheduling",
        phase="schedule",
        message="校验全部通过，正在启动独立部署进程",
        staging=str(staging),
        log=str(log_path),
        launch_log=str(launch_log_path),
    )
    creationflags = 0
    for flag_name in ["CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"]:
        creationflags |= int(getattr(subprocess, flag_name, 0))

    with launch_log_path.open("ab", buffering=0) as launch_stream:
        process = subprocess.Popen(
            [
                _powershell_executable(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper),
            ],
            cwd=str(staging),
            stdin=subprocess.DEVNULL,
            stdout=launch_stream,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=True,
        )
        deployment_pid = int(process.pid)
        # Catch the exact production failure we observed: CreateProcess succeeds
        # but PowerShell exits before Start-Transcript/update.log is created.
        time.sleep(0.25)
        immediate_exit_code = process.poll()

    common_state = {
        "release": release_name,
        "target_commit": target,
        "package": zip_name,
        "package_bytes": expected_bytes,
        "package_sha256": actual_sha,
        "download_source": download_source,
        "download_errors": download_errors,
        "downloaded_bytes": zip_path.stat().st_size,
        "progress_percent": 100.0,
        "staging": str(staging),
        "log": str(log_path),
        "launch_log": str(launch_log_path),
        "pid": deployment_pid,
        "deployment_pid": deployment_pid,
    }
    if immediate_exit_code is not None:
        return _write_runtime_state(
            status="failed",
            phase="deployment_launch_failed",
            message="独立部署进程启动后立即退出，生产版本未切换。",
            scheduled_at=_utc_now(),
            error=f"PowerShell 部署进程立即退出：ExitCode={immediate_exit_code}；请查看 launch.log。",
            deployment_process_alive=False,
            **common_state,
        )

    return _write_runtime_state(
        status="scheduled",
        phase="scheduled",
        message="独立部署进程已启动，正在等待进程终态与生产提交切换。",
        scheduled_at=_utc_now(),
        deployment_process_alive=True,
        **common_state,
    )


def _worker_main(run_id: str) -> None:
    try:
        _run_update()
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, ReleaseUpdateError)
            else f"{type(exc).__name__}: {exc}"
        )
        _write_runtime_state(
            status="failed",
            phase="failed",
            message="一键升级任务已停止；保留可用断点。",
            error=message[:500],
        )
    finally:
        with _LOCK:
            global _WORKER, _WORKER_RUN_ID
            if _WORKER_RUN_ID == run_id:
                _WORKER = None
                _WORKER_RUN_ID = ""
        _PAUSE_EVENT.clear()
        _RECONNECT_EVENT.clear()
        _RESET_EVENT.clear()


def start_release_update() -> dict[str, Any]:
    if os.name != "nt":
        raise ReleaseUpdateError("一键升级只允许在 Windows 生产机执行")
    with _LOCK:
        global _WORKER, _WORKER_RUN_ID
        deployment_state = _reconcile_deployment_state(core._read_state())
        if str(deployment_state.get("status") or "").lower() in _DEPLOY_STATUSES:
            return {
                "ok": True,
                "started": False,
                "background": True,
                "message": "独立部署进程仍在运行，等待部署终态确认",
                "worker_alive": False,
                **deployment_state,
            }
        if _WORKER is not None and _WORKER.is_alive():
            state = core._read_state()
            return {
                "ok": True,
                "started": False,
                "background": True,
                "message": "升级任务已经在运行",
                "worker_alive": True,
                **state,
            }
        _PAUSE_EVENT.clear()
        _RECONNECT_EVENT.clear()
        run_id = f"{int(time.time())}-{os.getpid()}-{threading.get_ident()}"
        _WORKER_RUN_ID = run_id
        previous_state = core._read_state()
        core._update_state(
            status="queued",
            phase="queued",
            message="升级任务已进入后台队列",
            started_at=_utc_now(),
            updated_at=_utc_now(),
            heartbeat_at=_utc_now(),
            worker_pid=os.getpid(),
            run_id=run_id,
            downloaded_bytes=int(previous_state.get("downloaded_bytes") or 0),
            error="",
        )
        worker = threading.Thread(
            target=_worker_main,
            args=(run_id,),
            name="release-update-worker",
            daemon=True,
        )
        _WORKER = worker
        worker.start()
    return {
        "ok": True,
        "started": True,
        "background": True,
        "worker_alive": True,
        "run_id": run_id,
        "message": "升级任务已在后台启动",
    }


def pause_release_update() -> dict[str, Any]:
    if not _worker_alive():
        return {"ok": False, "error": "当前没有可暂停的升级 worker"}
    _PAUSE_EVENT.set()
    return {"ok": True, "message": "已请求暂停；当前网络读结束后会保留断点并暂停。"}


def resume_release_update() -> dict[str, Any]:
    if _worker_alive():
        if not _PAUSE_EVENT.is_set():
            return {
                "ok": True,
                "message": "升级 worker 正在运行",
                "worker_alive": True,
            }
        _PAUSE_EVENT.clear()
        return {"ok": True, "message": "已继续下载", "worker_alive": True}
    state = _reconcile_deployment_state(core._read_state())
    state_status = str(state.get("status") or "").lower()
    if state_status in _DEPLOY_STATUSES:
        return {"ok": False, "error": "独立部署进程正在运行，不能启动新的下载任务"}
    if state_status not in _RESUMABLE_STATUSES | {"paused"}:
        return {"ok": False, "error": "当前状态不支持继续下载"}
    return start_release_update()


def reconnect_release_update() -> dict[str, Any]:
    if _worker_alive():
        _PAUSE_EVENT.clear()
        _RECONNECT_EVENT.set()
        return {"ok": True, "message": "已请求断开当前连接并从现有断点重连"}
    state = _reconcile_deployment_state(core._read_state())
    if str(state.get("status") or "").lower() in _DEPLOY_STATUSES:
        return {"ok": False, "error": "独立部署进程正在运行，不能重新连接下载"}
    if not (state.get("target_commit") or state.get("package")):
        return {"ok": False, "error": "没有可重新连接的升级任务"}
    return start_release_update()


def reset_release_update() -> dict[str, Any]:
    _RESET_EVENT.set()
    _PAUSE_EVENT.clear()
    if _worker_alive():
        return {"ok": True, "message": "已请求清空当前目标版本断点并从 0 重新下载"}
    state = _reconcile_deployment_state(core._read_state())
    if str(state.get("status") or "").lower() in _DEPLOY_STATUSES:
        _RESET_EVENT.clear()
        return {"ok": False, "error": "独立部署进程正在运行，禁止删除已验证部署包"}
    package = Path(str(state.get("package") or "")).name
    if package and re.fullmatch(
        r"LOLDataSystem-full-bug-repair-safe-deploy-[0-9a-f]{12}-py311-py314-winps51-v3\.zip",
        package,
    ):
        for candidate in (
            core._UPDATE_HOME.rglob(package + ".part")
            if core._UPDATE_HOME.exists()
            else []
        ):
            try:
                candidate.resolve().relative_to(core._UPDATE_HOME.resolve())
            except ValueError:
                continue
            candidate.unlink(missing_ok=True)
        for candidate in (
            core._UPDATE_HOME.rglob(package)
            if core._UPDATE_HOME.exists()
            else []
        ):
            try:
                candidate.resolve().relative_to(core._UPDATE_HOME.resolve())
            except ValueError:
                continue
            candidate.unlink(missing_ok=True)
    return start_release_update()
