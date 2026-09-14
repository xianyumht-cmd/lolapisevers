import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.target_file_watch_runtime import target_file_watch_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("LOLDataSystem")
    ctx = getattr(app.state, "ctx", None)
    client = getattr(ctx, "so1_client", None) or getattr(app.state, "so1_client", None)
    if ctx is not None:
        try:
            await asyncio.to_thread(ctx.start)
        except Exception as exc:
            logger.error("startup application context failed: %s", type(exc).__name__)
    try:
        if client is not None:
            await client.init_browser()
    except Exception as exc:
        logger.error("startup browser init failed: %s", exc)
    try:
        await target_file_watch_service.start()
    except Exception as exc:
        logger.error("startup target file watch failed: %s", type(exc).__name__)
    try:
        yield
    finally:
        try:
            await target_file_watch_service.stop()
        except Exception as exc:
            logger.error("shutdown target file watch failed: %s", type(exc).__name__)
        try:
            if client is not None:
                await client.close_browser()
        except Exception as exc:
            logger.error("shutdown browser close failed: %s", exc)
