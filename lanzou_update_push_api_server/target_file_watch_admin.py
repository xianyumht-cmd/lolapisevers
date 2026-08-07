from __future__ import annotations

import os
from typing import Any

import requests


class TargetFileWatchAdminError(RuntimeError):
    pass


def _control_headers() -> dict[str, str]:
    token = str(
        os.getenv("GROUPGUARD_WRITE_TOKEN")
        or os.getenv("WEBUI_ADMIN_TOKEN")
        or ""
    ).strip()
    headers = {"accept": "application/json"}
    if token:
        headers["x-groupguard-token"] = token
    return headers


def _request(
    main_base_url: str,
    path: str,
    *,
    method: str = "GET",
    timeout: float = 20.0,
) -> dict[str, Any]:
    url = f"{main_base_url.rstrip('/')}{path}"
    try:
        response = requests.request(
            method,
            url,
            headers=_control_headers(),
            json={} if method != "GET" else None,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise TargetFileWatchAdminError(
            f"5001 定向文件监控接口不可达：{type(exc).__name__}"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise TargetFileWatchAdminError(
            f"5001 定向文件监控接口返回非 JSON：HTTP {response.status_code}"
        ) from exc

    if not response.ok:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("error") or "").strip()
        suffix = f"：{detail[:240]}" if detail else ""
        raise TargetFileWatchAdminError(
            f"5001 定向文件监控接口 HTTP {response.status_code}{suffix}"
        )
    if not isinstance(payload, dict):
        raise TargetFileWatchAdminError("5001 定向文件监控接口返回结构异常")
    return payload


def read_target_file_watch_overview(main_base_url: str) -> dict[str, Any]:
    status = _request(
        main_base_url,
        "/api/v1/target-file-watch/status",
        timeout=15.0,
    )
    return {
        "ok": True,
        "source": "LOLDataSystem 5001",
        "configAuthority": "GroupGuard 6108",
        "status": status,
    }


def check_target_file_watch_now(main_base_url: str) -> dict[str, Any]:
    result = _request(
        main_base_url,
        "/api/v1/target-file-watch/check",
        method="POST",
        timeout=150.0,
    )
    return {"ok": True, "result": result}


def rebaseline_target_file_watch(main_base_url: str) -> dict[str, Any]:
    result = _request(
        main_base_url,
        "/api/v1/target-file-watch/rebaseline",
        method="POST",
        timeout=30.0,
    )
    return {"ok": True, "result": result}


__all__ = [
    "TargetFileWatchAdminError",
    "check_target_file_watch_now",
    "read_target_file_watch_overview",
    "rebaseline_target_file_watch",
]
