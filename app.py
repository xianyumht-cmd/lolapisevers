import logging

from fastapi import FastAPI
import uvicorn

import legacy_app
from core.config import load_config
from core.context import create_app_context
from core.lifespan import lifespan
from routers.cross_query import router as cross_query_router
from routers.cross_session import router as cross_session_router
from routers.health import router as health_router
from routers.lolban import router as lolban_router


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


def _remove_legacy_routes(app: FastAPI) -> None:
    removed_paths = {"/query", "/hidden_query", "/health", "/cross_session_init", "/cross_query"}
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
    config = load_config()
    app.state.config = config
    app.state.ctx = create_app_context(config=config, so1_client=getattr(app.state, "so1_client", None))
    app.state.so1_client = app.state.ctx.so1_client
    app.state.db_config = config.db_config

    app.router.lifespan_context = lifespan
    _remove_legacy_routes(app)
    app.include_router(health_router)
    app.include_router(cross_session_router)
    app.include_router(cross_query_router)
    app.include_router(lolban_router)

    logger.info("API routers mounted; legacy health/session/cross and deprecated LCU routes removed")
    return app


if __name__ == "__main__":
    application = build_app()
    config = load_config()
    uvicorn.run(
        application,
        host=config.app_host,
        port=config.app_port,
    )
