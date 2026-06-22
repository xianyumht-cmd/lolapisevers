from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    ctx = getattr(request.app.state, "ctx", None)
    db_instance = ctx.ensure_db() if ctx is not None else None
    db_error_message = getattr(ctx, "db_error_message", "") if ctx is not None else ""
    so1_client = getattr(ctx, "so1_client", None) or getattr(request.app.state, "so1_client", None)
    browser_ok = bool(
        so1_client is not None
        and getattr(so1_client, "_browser", None) is not None
        and so1_client._browser.is_connected()
    )
    return {
        "status": "ok",
        "mysql": "up" if db_instance else "down",
        "mysql_error": db_error_message if db_instance is None else "",
        "so1_browser": "up" if browser_ok else "down",
        "so1_max_concurrent_pages": getattr(so1_client, "_max_concurrent_pages", 0) if so1_client is not None else 0,
    }
