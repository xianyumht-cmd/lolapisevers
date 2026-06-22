import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

import legacy_app
from routers.lolban import router as lolban_router
from so1_client import So1Client


class DisabledLCUClient:
    def __init__(self, *args, **kwargs):
        pass

    def get_rank(self, *args, **kwargs):
        return ""


class DisabledCollector:
    def __init__(self, *args, **kwargs):
        pass

    def collect_player(self, *args, **kwargs):
        raise RuntimeError("LCU query has been removed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("LOLDataSystem")
    try:
        client = app.state.so1_client
        await client.init_browser()
    except Exception as exc:
        logger.error("startup browser init failed: %s", exc)
    yield
    try:
        client = app.state.so1_client
        await client.close_browser()
    except Exception as exc:
        logger.error("shutdown browser close failed: %s", exc)


def _remove_deprecated_lcu_routes(app: FastAPI) -> None:
    removed_paths = {"/query", "/hidden_query"}
    app.router.routes = [route for route in app.router.routes if getattr(route, "path", "") not in removed_paths]


def build_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    logger = logging.getLogger("LOLDataSystem")

    legacy_app.LCUClient = DisabledLCUClient
    legacy_app.DataCollector = DisabledCollector
    legacy_app.LCUConnectionError = RuntimeError

    app = legacy_app.build_app()
    app.router.lifespan_context = lifespan
    _remove_deprecated_lcu_routes(app)
    app.include_router(lolban_router)

    if not hasattr(app.state, "so1_client"):
        username = os.getenv("SO1_USERNAME", "mengxin1").strip()
        password = os.getenv("SO1_PASSWORD", "mengxin").strip()
        app.state.so1_client = So1Client(
            username=username,
            password=password,
            headless=os.getenv("SO1_HEADLESS", "1") != "0",
            timeout_ms=int(os.getenv("SO1_TIMEOUT_MS", "20000")),
        )
    app.state.db_config = {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", "123456"),
        "database": os.getenv("MYSQL_DATABASE", "lol_data"),
    }
    logger.info("API routers mounted; deprecated LCU routes removed")
    return app


if __name__ == "__main__":
    application = build_app()
    uvicorn.run(
        application,
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "5001")),
    )
