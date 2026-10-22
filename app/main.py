"""FastAPI application factory and entrypoint.

Run locally with:

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

or simply ``python -m app.main``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_error_handlers
from app.api.middleware import AnalyticsGZipMiddleware, AssistantAPIBoundary
from app.api.routers.admin import router as admin_router
from app.api.routers.analytics import router as analytics_router
from app.api.routers.webhooks import router as webhooks_router
from app.api.routers.assistant import router as assistant_router
from app.api.routers.chatgpt import router as chatgpt_router
from app.api.routers.assistant_api import router as assistant_api_router
from app.api.routers.failed_jobs import router as failed_jobs_router
from app.api.routers.flatten import router as flatten_router
from app.api.routers.ops import router as ops_router
from app.api.routers.status import router as status_router
from app.api.routers.sync import router as sync_router
from app.config import get_settings
from app.database.session import dispose_engine
from app.logging.setup import configure_logging, get_logger
from app.scheduler.scheduler import shutdown_scheduler, start_scheduler
from app.services.assistant_mcp import AnalyticsMCP
from starlette.routing import Route

settings = get_settings()
configure_logging(level=settings.log_level, json_output=settings.log_json)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("application_startup", app_env=settings.app_env)
    start_scheduler()
    # Warm default dashboard reads without blocking startup. Concurrent
    # visitors share the same cache fill and its database work.
    import asyncio as _asyncio

    from app.api.routers.analytics import warm_ads_analyse_cache
    warmup = _asyncio.create_task(warm_ads_analyse_cache())
    try:
        async with app.state.analytics_mcp.manager.run():
            yield
    finally:
        warmup.cancel()
        with suppress(_asyncio.CancelledError):
            await warmup
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

    # Analytics responses contain many repeated field names. Compress large
    # JSON bodies to reduce download time, with modest CPU cost on Render.
    app.add_middleware(AnalyticsGZipMiddleware, minimum_size=1000, compresslevel=3)
    app.add_middleware(AssistantAPIBoundary)

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
    app.include_router(chatgpt_router)
    app.include_router(assistant_api_router)
    app.include_router(ops_router)
    app.include_router(flatten_router)
    app.include_router(analytics_router)
    app.include_router(webhooks_router)

    app.state.analytics_mcp = AnalyticsMCP()
    app.router.routes.append(Route("/mcp", app.state.analytics_mcp, methods=["GET", "POST", "DELETE"]))
    _mount_mcp_oauth(app)

    return app


def _mount_mcp_oauth(app: FastAPI) -> None:
    """OAuth endpoints, so connector UIs that cannot set a header can attach.

    Mounted only when the URLs are configured and valid: without them the
    issuer would be wrong and a connector would silently fail discovery
    rather than report a misconfiguration. Bearer-key clients are
    unaffected either way -- this is a second door onto the same principal.
    """
    from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
    from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
    from pydantic import AnyHttpUrl
    from starlette.routing import Route as _Route

    from app.api.routers.mcp_oauth_routes import authorize_page, authorize_submit
    from app.services import assistant_api_auth as _auth
    from app.services.mcp_oauth import SCOPE, SaadaaOAuthProvider

    try:
        settings = _auth.settings()
        settings.require_configured()
        mcp_url = settings.mcp_url
    except Exception:
        get_logger(__name__).info("mcp_oauth_not_mounted", reason="assistant API not configured")
        return

    issuer = mcp_url.removesuffix("/mcp") or mcp_url
    provider = SaadaaOAuthProvider()
    app.router.routes.extend(create_auth_routes(
        provider=provider,
        issuer_url=AnyHttpUrl(issuer),
        # Open registration is what lets a connector add itself without the
        # user copying a client id and secret. The authorization page is the
        # gate, not registration -- see app/services/mcp_oauth.py.
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
        revocation_options=RevocationOptions(enabled=True),
    ))
    app.router.routes.extend(create_protected_resource_routes(
        resource_url=AnyHttpUrl(mcp_url),
        authorization_servers=[AnyHttpUrl(issuer)],
        scopes_supported=[SCOPE],
        resource_name="SAADAA Analytics",
    ))
    app.router.routes.append(_Route("/mcp/authorize", authorize_page, methods=["GET"]))
    app.router.routes.append(_Route("/mcp/authorize", authorize_submit, methods=["POST"]))


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )
