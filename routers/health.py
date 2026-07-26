import asyncio
from typing import Any

from fastapi import APIRouter, Request, Response, status

from core.build_info import load_build_info
from services.lolban_service import get_lolban_health


router = APIRouter()


def _build_info(request: Request) -> dict[str, Any]:
    value = getattr(request.app.state, "build_info", None)
    return dict(value) if isinstance(value, dict) else load_build_info()


def _browser_dependency(so1_client: Any) -> dict[str, Any]:
    browser = getattr(so1_client, "_browser", None) if so1_client is not None else None
    try:
        connected = bool(browser is not None and browser.is_connected())
        error_class = ""
    except Exception as exc:
        connected = False
        error_class = type(exc).__name__
    result = {
        "required": True,
        "status": "up" if connected else "down",
        "max_concurrent_pages": (
            getattr(so1_client, "_max_concurrent_pages", 0)
            if so1_client is not None
            else 0
        ),
    }
    if error_class:
        result["error_class"] = error_class
    return result


def _lolban_dependency() -> dict[str, Any]:
    try:
        health = get_lolban_health()
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
    browser = _browser_dependency(so1_client)
    dependencies = {
        "mysql": mysql,
        "so1_browser": browser,
        "lolban": _lolban_dependency(),
    }
    ready = mysql["status"] == "up" and browser["status"] == "up"
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
        "so1_browser": browser["status"],
        "so1_max_concurrent_pages": browser["max_concurrent_pages"],
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
