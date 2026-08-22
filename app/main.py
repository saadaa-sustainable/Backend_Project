"""FastAPI application factory and entrypoint.

Run locally with:

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

or simply ``python -m app.main``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_error_handlers
from app.api.routers.admin import router as admin_router
from app.api.routers.assistant import router as assistant_router
from app.api.routers.failed_jobs import router as failed_jobs_router
from app.api.routers.flatten import router as flatten_router
from app.api.routers.ops import router as ops_router
from app.api.routers.status import router as status_router
from app.api.routers.sync import router as sync_router
from app.config import get_settings
from app.database.session import dispose_engine
from app.logging.setup import configure_logging, get_logger
from app.scheduler.scheduler import shutdown_scheduler, start_scheduler

settings = get_settings()
configure_logging(level=settings.log_level, json_output=settings.log_json)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("application_startup", app_env=settings.app_env)
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        await dispose_engine()
        logger.info("application_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Meta Marketing API Ingestion Service",
        description=(
            "Ingests raw data from every major Meta Marketing API endpoint into "
            "a PostgreSQL Bronze layer, exactly as returned by Meta."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    register_error_handlers(app)

    # The Next.js admin app (admin/) runs on a different origin in dev
    # (localhost:3000 -> localhost:8000) -- restricted to the admin app's
    # own origin, not a wildcard, since this API can trigger ingestion.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.admin_app_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    app.include_router(sync_router)
    app.include_router(status_router)
    app.include_router(failed_jobs_router)
    app.include_router(admin_router)
    app.include_router(assistant_router)
    app.include_router(ops_router)
    app.include_router(flatten_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )
