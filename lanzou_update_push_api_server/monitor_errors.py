from __future__ import annotations

import json
import re
from typing import Any

import requests


_SAFE_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_ERROR_CONTEXT_KEYS = {
    "body",
    "exception",
    "exception_message",
    "headers",
    "message",
    "query",
    "request_body",
    "request_headers",
    "request_query",
    "request_url",
    "response_body",
    "response_headers",
    "response_url",
    "url",
}


def safe_code(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if _SAFE_CODE_PATTERN.fullmatch(candidate) else fallback


def safe_class_name(value: Any, fallback: str) -> str:
    candidate = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return candidate[:64] or fallback


def safe_failure(exc: Exception, fallback_code: str) -> dict[str, Any]:
    status_code = None
    configured_code = getattr(exc, "error_code", "")
    configured_retryable = getattr(exc, "retryable", None)
    configured_status_code = getattr(exc, "status_code", None)
    if isinstance(configured_status_code, int):
        status_code = configured_status_code
    if configured_code:
        error_code = safe_code(configured_code, fallback_code)
    elif isinstance(exc, requests.ConnectTimeout):
        error_code = "connect_timeout"
    elif isinstance(exc, requests.ReadTimeout):
        error_code = "read_timeout"
    elif isinstance(exc, requests.Timeout):
        error_code = "timeout"
    elif isinstance(exc, requests.ConnectionError):
        error_code = "connection_error"
    elif isinstance(exc, requests.HTTPError):
        error_code = "http_status"
        response = getattr(exc, "response", None)
        candidate = getattr(response, "status_code", None)
        status_code = int(candidate) if isinstance(candidate, int) else None
    elif isinstance(exc, (json.JSONDecodeError, ValueError)):
        error_code = "invalid_response"
    else:
        error_code = fallback_code

    if configured_retryable is None:
        retryable = not isinstance(exc, (json.JSONDecodeError, ValueError))
        if status_code is not None:
            retryable = status_code == 429 or status_code >= 500
    else:
        retryable = bool(configured_retryable)
    result: dict[str, Any] = {
        "error_code": error_code,
        "error_class": safe_class_name(type(exc).__name__, "MonitorError"),
        "retryable": retryable,
    }
    if status_code is not None:
        result["status_code"] = status_code
    return result


def sanitize_persisted_errors(value: Any) -> bool:
    """Remove legacy free-form exception data from persisted monitor state."""
    changed = False
    if isinstance(value, list):
        for item in value:
            changed = sanitize_persisted_errors(item) or changed
        return changed
    if not isinstance(value, dict):
        return False

    is_error_record = value.get("ok") is False or any(
        key in value
        for key in ("error", "error_code", "error_class", "exception")
    )
    if "error" in value:
        value.pop("error", None)
        value.setdefault("error_code", "legacy_error_redacted")
        value.setdefault("error_class", "LegacyPersistedError")
        value.setdefault("retryable", True)
        changed = True
        is_error_record = True
    if is_error_record:
        for key in list(value):
            if str(key).strip().lower() in _ERROR_CONTEXT_KEYS:
                value.pop(key, None)
                changed = True
    for item in list(value.values()):
        changed = sanitize_persisted_errors(item) or changed
    return changed
