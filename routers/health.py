import asyncio
from typing import Any

from fastapi import APIRouter, Request, Response, status

from core.build_info import load_build_info
from services.lolban_runtime import get_lolban_service
from services.so1_readiness_service import ensure_so1_readiness


router = APIRouter()


def _build_info(request: Request) -> dict[str, Any]:
    value = getattr(request.app.state, "build_info", None)
    return dict(value) if isinstance(value, dict) else load_build_info()


async def _so1_dependency(so1_client: Any) -> dict[str, Any]:
    if so1_client is None:
        return {
            "required": True,
            "status": "down",
            "browser_status": "down",
            "session_authenticated": False,
            "reason": "client_unavailable",
            "max_concurrent_pages": 0,
        }
    try:
        result = await asyncio.wait_for(
            ensure_so1_readiness(so1_client),
            timeout=20.0,
        )
        browser_up = bool(result.get("browser_up"))
        authenticated = bool(result.get("session_authenticated"))
        reason = str(result.get("reason") or "")
        error_class = str(result.get("error_class") or "")
    except Exception as exc:
        browser_up = False
        authenticated = False
        reason = "probe_failed"
        error_class = type(exc).__name__
        result = {}
    payload = {
        "required": True,
        "status": "up" if browser_up and authenticated else "down",
        "browser_status": "up" if browser_up else "down",
        "session_authenticated": authenticated,
        "reason": reason,
        "max_concurrent_pages": getattr(so1_client, "_max_concurrent_pages", 0),
    }
    if error_class:
        payload["error_class"] = error_class
    for key in (
        "recovery",
        "recovery_retry_after_seconds",
        "original_reason",
    ):
        if key in result:
            payload[key] = result[key]
    return payload


def _lolban_dependency() -> dict[str, Any]:
    try:
        health = get_lolban_service().health()
    except Exception as exc:
        return {
            "required": False,
            "status": "degraded",
            "configured": False,
            "provider_count": 0,
            "error_class": type(exc).__name__,
        }

    configured = bool(health.get("configured"))
    last_error_class = str(health.get("last_error_class") or "")
    configuration_error_code = str(
        health.get("configuration_error_code") or ""
    )
    configuration_error_class = str(
        health.get("configuration_error_class") or ""
    )
    return {
        "required": False,
        "status": (
            "degraded"
            if configuration_error_code
            else "disabled"
            if not configured
            else ("degraded" if last_error_class else "configured")
        ),
        "configured": configured,
        "provider_count": int(health.get("provider_count") or 0),
        "fresh_cache_entries": int(health.get("fresh_cache_entries") or 0),
        "stale_cache_entries": int(health.get("stale_cache_entries") or 0),
        "last_success_at": str(health.get("last_success_at") or ""),
        "last_error_at": str(health.get("last_error_at") or ""),
        "last_error_class": last_error_class,
        "configuration_error_code": configuration_error_code,
        "configuration_error_class": configuration_error_class,
    }


async def _mysql_dependency(ctx: Any) -> dict[str, Any]:
    if ctx is None:
        return {
            "required": True,
            "status": "down",
            "check": "select_1",
            "error_class": "context_unavailable",
        }

    try:
        db_instance = await asyncio.to_thread(ctx.ensure_db)
        if db_instance is None:
            return {
                "required": True,
                "status": "down",
                "check": "select_1",
                "error_class": "database_unavailable",
            }
        ping_ok = await asyncio.to_thread(db_instance.ping)
        if not ping_ok:
            return {
                "required": True,
                "status": "down",
                "check": "select_1",
                "error_class": "empty_ping_result",
            }
    except Exception as exc:
        return {
            "required": True,
            "status": "down",
            "check": "select_1",
            "error_class": type(exc).__name__,
        }

    return {
        "required": True,
        "status": "up",
        "check": "select_1",
    }


async def _readiness_payload(request: Request) -> dict[str, Any]:
    ctx = getattr(request.app.state, "ctx", None)
    so1_client = (
        getattr(ctx, "so1_client", None)
        or getattr(request.app.state, "so1_client", None)
    )
    mysql = await _mysql_dependency(ctx)
    so1 = await _so1_dependency(so1_client)
    dependencies = {
        "mysql": mysql,
        "so1_browser": so1,
        "lolban": _lolban_dependency(),
    }
    ready = mysql["status"] == "up" and so1["status"] == "up"
    mysql_error = "" if mysql["status"] == "up" else str(
        mysql.get("error_class") or "database_unavailable"
    )
    return {
        "status": "ok" if ready else "degraded",
        "liveness": "up",
        "ready": ready,
        # Legacy fields are kept for existing admin and supervisor clients.
        "mysql": mysql["status"],
        "mysql_error": mysql_error,
        "so1_browser": so1["browser_status"],
        "so1_session": "authenticated" if so1["session_authenticated"] else "down",
        "so1_max_concurrent_pages": so1["max_concurrent_pages"],
        "dependencies": dependencies,
        "build": _build_info(request),
    }


@router.get("/health")
async def health(request: Request):
    """Backward-compatible combined health response; always returns HTTP 200."""
    return await _readiness_payload(request)


@router.get("/livez")
async def livez(request: Request):
    """Process liveness only; dependency failures must never make this fail."""
    return {
        "status": "ok",
        "liveness": "up",
        "build": _build_info(request),
    }


@router.get("/readyz")
async def readyz(request: Request, response: Response):
    """Dependency readiness; returns HTTP 503 when a required check fails."""
    payload = await _readiness_payload(request)
    if not payload["ready"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


@router.get("/build-info")
async def build_info(request: Request):
    return _build_info(request)
