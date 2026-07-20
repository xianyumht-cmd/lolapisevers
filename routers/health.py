import asyncio

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    ctx = getattr(request.app.state, "ctx", None)
    db_instance = await asyncio.to_thread(ctx.ensure_db) if ctx is not None else None
    db_error_message = getattr(ctx, "db_error_message", "") if ctx is not None else ""
    so1_client = getattr(ctx, "so1_client", None) or getattr(request.app.state, "so1_client", None)
    browser_ok = bool(
        so1_client is not None
        and getattr(so1_client, "_browser", None) is not None
        and so1_client._browser.is_connected()
    )
    mysql_ok = db_instance is not None
    ready = mysql_ok and browser_ok
    return {
        # Keep returning HTTP 200 so callers can distinguish a live process from
        # one whose required dependencies are not ready yet.
        "status": "ok" if ready else "degraded",
        "liveness": "up",
        "ready": ready,
        "mysql": "up" if mysql_ok else "down",
        "mysql_error": db_error_message if not mysql_ok else "",
        "so1_browser": "up" if browser_ok else "down",
        "so1_max_concurrent_pages": getattr(so1_client, "_max_concurrent_pages", 0) if so1_client is not None else 0,
    }
