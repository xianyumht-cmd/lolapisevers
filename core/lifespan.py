import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.context import create_app_context
from services.target_file_watch_runtime import create_target_file_watch_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("LOLDataSystem")
    ctx = None
    client = None
    target_file_watch_service = None

    try:
        ctx = create_app_context(config=app.state.config)
        app.state.ctx = ctx
        app.state.so1_client = ctx.so1_client
        client = ctx.so1_client
    except Exception as exc:
        logger.error("startup application context creation failed: %s", type(exc).__name__)

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
        target_file_watch_service = create_target_file_watch_service()
        app.state.target_file_watch_service = target_file_watch_service
        await target_file_watch_service.start()
    except Exception as exc:
        logger.error("startup target file watch failed: %s", type(exc).__name__)

    try:
        yield
    finally:
        try:
            if target_file_watch_service is not None:
                await target_file_watch_service.stop()
        except Exception as exc:
            logger.error("shutdown target file watch failed: %s", type(exc).__name__)
        try:
            if client is not None:
                await client.close_browser()
        except Exception as exc:
            logger.error("shutdown browser close failed: %s", exc)
