"""``/status``, ``/health``, and ``/logs`` endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.api.deps import MetaClientDep, SessionDep
from app.config import get_settings
from app.logging.setup import get_logger
from app.models.sync import BatchStatus, SyncBatch
from app.repositories.batch_repository import BatchRepository
from app.schemas.status import BatchSummary, HealthResponse, StatusResponse

router = APIRouter(tags=["status"])
logger = get_logger(__name__)


def _to_batch_summary(b: SyncBatch) -> BatchSummary:
    return BatchSummary(
        batch_id=b.id,
        endpoint=b.endpoint,
        account_key=b.account_key,
        account_name=b.account_name,
        sync_type=b.sync_type,
        status=b.status,
        records_fetched=b.records_fetched,
        records_failed=b.records_failed,
        started_at=b.started_at,
        finished_at=b.finished_at,
        triggered_by=b.triggered_by,
        error_message=b.error_message,
    )


@router.get("/live")
async def live(session: SessionDep) -> dict:
    """Cheap liveness probe for the platform's health checker (Render
    pings this every ~30s). DB reachability only -- deliberately does
    NOT call Meta, because every ping there would burn ~2,880 requests/
    day against the shared app-level rate-limit budget (confirmed live
    2026-09-02). Use ``/health`` for the deeper connectivity check."""
    settings = get_settings()
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "app_env": settings.app_env}
    except Exception as exc:  # noqa: BLE001
        logger.error("live_check_database_failed", error=str(exc))
        return {"status": "degraded", "app_env": settings.app_env, "database_ok": False}


@router.get("/health", response_model=HealthResponse)
async def health(session: SessionDep, client: MetaClientDep) -> HealthResponse:
    """Deep readiness probe: verifies both the database AND the Meta API
    are reachable with the configured credentials. Costs one Meta
    Graph-API call per invocation, so NOT wired to the platform's
    health-check loop (use ``/live`` there instead)."""
    settings = get_settings()

    database_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.error("health_check_database_failed", error=str(exc))
        database_ok = False

    meta_api_ok = True
    try:
        await client.get("me", params={"fields": "id"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_check_meta_api_failed", error=str(exc))
        meta_api_ok = False

    status = "ok" if (database_ok and meta_api_ok) else "degraded"
    return HealthResponse(
        status=status,
        app_name=settings.app_name,
        app_env=settings.app_env,
        database_ok=database_ok,
        meta_api_ok=meta_api_ok,
    )


@router.get("/status", response_model=StatusResponse)
async def get_status(
    session: SessionDep,
    endpoint: str | None = Query(default=None),
    account: str | None = Query(default=None, description="Filter to one account's key."),
    limit: int = Query(default=50, ge=1, le=500),
) -> StatusResponse:
    """Summary of ingestion batch health across every endpoint/account."""
    repo = BatchRepository(session)
    recent = await repo.list_recent(endpoint=endpoint, account_key=account, limit=limit)

    return StatusResponse(
        total_batches=len(recent),
        running=sum(1 for b in recent if b.status == BatchStatus.RUNNING),
        succeeded=sum(1 for b in recent if b.status == BatchStatus.SUCCESS),
        partial_failures=sum(1 for b in recent if b.status == BatchStatus.PARTIAL_FAILURE),
        failed=sum(1 for b in recent if b.status == BatchStatus.FAILED),
        recent_batches=[_to_batch_summary(b) for b in recent],
    )


@router.get("/logs", response_model=list[BatchSummary])
async def get_logs(
    session: SessionDep,
    endpoint: str | None = Query(default=None),
    account: str | None = Query(default=None, description="Filter to one account's key."),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[BatchSummary]:
    """Chronological ingestion run log, most recent first. Each entry is a
    :class:`~app.models.sync.SyncBatch` — the structured record of one
    endpoint's sync attempt, including any error message."""
    repo = BatchRepository(session)
    recent = await repo.list_recent(endpoint=endpoint, account_key=account, limit=limit)
    return [_to_batch_summary(b) for b in recent]
