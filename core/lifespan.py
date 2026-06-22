import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("LOLDataSystem")
    ctx = getattr(app.state, "ctx", None)
    client = getattr(ctx, "so1_client", None) or getattr(app.state, "so1_client", None)
    try:
        if client is not None:
            await client.init_browser()
    except Exception as exc:
        logger.error("startup browser init failed: %s", exc)
    yield
    try:
        if client is not None:
            await client.close_browser()
    except Exception as exc:
        logger.error("shutdown browser close failed: %s", exc)
