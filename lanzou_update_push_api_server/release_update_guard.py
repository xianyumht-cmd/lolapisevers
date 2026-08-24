from __future__ import annotations

from typing import Any

import requests

from core.build_info import load_build_info

from . import release_update_controller as controller
from . import release_updater as core


ReleaseUpdateError = core.ReleaseUpdateError

_IDLE_RESUMABLE = {"paused", "interrupted", "stalled", "failed"}
_DEPLOY = {"scheduled", "deploying"}


def _compare_release_relation(current: str, target: str, token: str) -> str:
    current = str(current or "").strip().lower()
    target = str(target or "").strip().lower()
    if current == target and current:
        return "same"
    if not core._FULL_SHA_RE.fullmatch(current) or not core._FULL_SHA_RE.fullmatch(target):
        return "unknown"

    url = f"https://api.github.com/repos/{core.REPOSITORY}/compare/{current}...{target}"
    try:
        response = requests.get(
            url,
            headers=core._headers(token),
            timeout=(3.0, 8.0),
        )
    except requests.RequestException:
        return "unknown"
    if not response.ok:
        return "unknown"
    try:
        data = response.json()
    except ValueError:
        return "unknown"
    status = str(data.get("status") or "").strip().lower()
    if status == "identical":
        return "same"
    if status == "ahead":
        return "forward"
    if status == "behind":
        return "release_behind"
    if status == "diverged":
        return "diverged"
    return "unknown"


def _fresh_remote_status(previous_state: dict[str, Any]) -> dict[str, Any]:
    result = core.release_update_status()
    if str(result.get("status") or "").lower() == "unavailable":
        result["worker_alive"] = False
        result["heartbeat_age_seconds"] = None
        result["controls"] = {
            "can_pause": False,
            "can_resume": False,
            "can_reconnect": False,
            "can_reset": False,
        }
        result["update_state"] = {}
        if previous_state:
            result["last_update_state"] = previous_state
        return result

    current = str(result.get("current_commit") or "").strip().lower()
    target = str(result.get("target_commit") or "").strip().lower()
    relation = _compare_release_relation(current, target, core._read_token())
    result["release_relation"] = relation
    result["worker_alive"] = False
    result["heartbeat_age_seconds"] = None
    result["controls"] = {
        "can_pause": False,
        "can_resume": False,
        "can_reconnect": False,
        "can_reset": False,
    }
    if previous_state:
        result["last_update_state"] = previous_state

    # Do not let an old persisted failed/interrupted task override the freshly
    # queried Release or the top-level status label.
    result["update_state"] = {}

    if relation == "same":
        result.update(
            {
                "status": "current",
                "available": False,
                "release_notice": "当前提交与 GitHub Release 一致。",
            }
        )
        result.pop("error", None)
        return result

    if relation == "forward":
        result.update(
            {
                "status": "update_available",
                "available": True,
                "release_notice": "GitHub Release 位于当前提交之后，可安全前向升级。",
            }
        )
        result.pop("error", None)

        previous_status = str(previous_state.get("status") or "").lower()
        previous_target = str(previous_state.get("target_commit") or "").lower()
        if previous_status in _IDLE_RESUMABLE and previous_target == target:
            local = controller._local_status_base(previous_state)
            result["update_state"] = previous_state
            result["controls"] = local.get("controls") or result["controls"]
        return result

    if relation == "release_behind":
        notice = "当前生产版本已经包含该 GitHub Release；Release 尚未追上当前版本，已禁止降级。"
        result.update(
            {
                "status": "current",
                "available": False,
                "release_notice": notice,
                "error": notice,
            }
        )
        return result

    if relation == "diverged":
        notice = "当前提交与 GitHub Release 发生分叉，无法证明为安全前向升级，已禁止一键升级。"
    else:
        notice = "无法确认当前提交与 GitHub Release 的祖先关系，为防止误降级已禁止一键升级。"
    result.update(
        {
            "status": "unavailable",
            "available": False,
            "release_notice": notice,
            "error": notice,
        }
    )
    return result


def release_update_status() -> dict[str, Any]:
    raw_state = core._read_state()
    raw_status = str(raw_state.get("status") or "").lower()

    # Only active/paused/deploy states need controller reconciliation. Idle,
    # failed and completed states go straight to one fresh GitHub check, avoiding
    # the old double metadata request on every manual status refresh.
    if (
        raw_status in controller._ACTIVE_STATUSES
        or raw_status in _DEPLOY
        or raw_status == "paused"
    ):
        local = controller.release_update_status()
        state = local.get("update_state") if isinstance(local.get("update_state"), dict) else {}
        state_status = str(state.get("status") or "").lower()
        if bool(local.get("worker_alive")) or state_status in _DEPLOY:
            return local
        return _fresh_remote_status(state)

    return _fresh_remote_status(raw_state)


def _guard_start() -> dict[str, Any]:
    status = release_update_status()
    relation = str(status.get("release_relation") or "").lower()
    if relation == "release_behind":
        raise ReleaseUpdateError("当前版本已经领先 GitHub Release，已禁止降级。")
    if relation in {"diverged", "unknown"}:
        raise ReleaseUpdateError(str(status.get("release_notice") or "无法确认安全前向升级关系"))
    if relation == "same" or status.get("status") == "current":
        return {
            "ok": True,
            "started": False,
            "background": False,
            "message": str(status.get("release_notice") or "当前已经是最新版本"),
        }
    if not bool(status.get("available")):
        raise ReleaseUpdateError(str(status.get("error") or "当前没有可安全升级的 Release"))
    return status


def start_release_update() -> dict[str, Any]:
    status = _guard_start()
    if not status.get("available"):
        return status
    return controller.start_release_update()


def _saved_target_relation() -> str:
    state = core._read_state()
    target = str(state.get("target_commit") or "").strip().lower()
    current = str(load_build_info().get("commit_sha") or "").strip().lower()
    if not target or not current:
        return "unknown"
    return _compare_release_relation(current, target, core._read_token())


def _guard_saved_action(action: str) -> dict[str, Any] | None:
    relation = _saved_target_relation()
    if relation == "forward":
        return None
    if relation == "same":
        return {"ok": False, "error": f"旧任务目标已经是当前生产版本，无需{action}。"}
    if relation == "release_behind":
        return {"ok": False, "error": f"旧任务目标落后于当前生产版本，禁止{action}以避免降级。"}
    if relation == "diverged":
        return {"ok": False, "error": f"旧任务与当前生产版本发生分叉，禁止{action}。"}
    return {"ok": False, "error": f"无法确认旧任务与当前生产版本的提交关系，禁止{action}。"}


def pause_release_update() -> dict[str, Any]:
    return controller.pause_release_update()


def resume_release_update() -> dict[str, Any]:
    blocked = _guard_saved_action("继续下载")
    return blocked if blocked is not None else controller.resume_release_update()


def reconnect_release_update() -> dict[str, Any]:
    blocked = _guard_saved_action("重新连接")
    return blocked if blocked is not None else controller.reconnect_release_update()


def reset_release_update() -> dict[str, Any]:
    blocked = _guard_saved_action("清空断点重下")
    return blocked if blocked is not None else controller.reset_release_update()


__all__ = [
    "ReleaseUpdateError",
    "pause_release_update",
    "reconnect_release_update",
    "release_update_status",
    "reset_release_update",
    "resume_release_update",
    "start_release_update",
]
