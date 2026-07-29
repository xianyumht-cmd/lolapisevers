import logging

from fastapi import FastAPI
import uvicorn

from core.build_info import load_build_info
from core.config import load_config
from core.context import create_app_context
from core.lifespan import lifespan
from routers.aram_augments import router as aram_augments_router
from routers.cross_query import router as cross_query_router
from routers.cross_session import router as cross_session_router
from routers.groupguard_delivery import router as groupguard_delivery_router
from routers.health import router as health_router
from routers.lolban import router as lolban_router
from routers.query_observability import router as query_observability_router
from routers.shard_query import router as shard_query_router


def build_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    logger = logging.getLogger("LOLDataSystem")
    config = load_config()

    build_info = load_build_info()
    app = FastAPI(
        title="LOL API Services",
        version=str(build_info.get("release") or "unknown"),
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.build_info = build_info
    app.state.ctx = create_app_context(config=config)
    app.state.so1_client = app.state.ctx.so1_client
    app.state.db_config = config.db_config

    app.include_router(health_router)
    app.include_router(cross_session_router)
    app.include_router(cross_query_router)
    app.include_router(shard_query_router)
    app.include_router(aram_augments_router)
    app.include_router(lolban_router)
    app.include_router(groupguard_delivery_router)
    app.include_router(query_observability_router)

    logger.info("API routers mounted without legacy_app dependency")
    return app


if __name__ == "__main__":
    application = build_app()
    config = load_config()
    uvicorn.run(
        application,
        host=config.app_host,
        port=config.app_port,
    )
