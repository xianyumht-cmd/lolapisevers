import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.query_observability import build_query_observability


router = APIRouter()


@router.get("/api/v1/operations/query-observability")
async def query_observability(request: Request):
    """Return sanitized query source, cache, snapshot, and circuit state.

    The endpoint performs no public-network probes and never returns upstream
    URLs, local paths, raw errors, credentials, or user query identifiers.
    """

    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        payload = build_query_observability(None)
        return JSONResponse(status_code=503, content=payload)
    payload = await asyncio.to_thread(build_query_observability, ctx)
    return JSONResponse(content=payload)
