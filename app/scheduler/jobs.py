"""Job bodies invoked by APScheduler (and directly by the manual-sync API
routes). Each job owns its full lifecycle: opens a DB session, runs the
work across every configured Meta ad account, and cleanly tears down —
jobs never share state with the request that may have triggered them.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.core.meta_registry import DatePreset, InsightsLevel
from app.core.security import get_meta_credentials
from app.database.session import session_scope
from app.logging.setup import get_logger
from app.repositories.failed_job_repository import FailedJobRepository
from app.services.meta.client import MetaAPIClient
from app.services.meta.insights import insights_retry_kwargs
from app.services.meta.live_refresh import last_fetch_epoch, refresh_changed_since
from app.services.meta.webhook_processor import process_pending_meta_events
from app.services.meta.orchestrator import MultiAccountSyncCoordinator, SyncOrchestrator
from app.services.silver.runner import run_auto_enabled_jobs

logger = get_logger(__name__)


async def run_daily_sync() -> None:
    """Full-breadth daily sync: every entity endpoint plus Insights over a
    rolling 30-day window (wide enough to absorb late-arriving attribution
    updates without re-pulling all of history every day), across every
    configured Meta ad account, in parallel."""
    logger.info("scheduled_daily_sync_started")
    coordinator = MultiAccountSyncCoordinator()
    results = await coordinator.sync_all(sync_type="incremental", triggered_by="scheduler_daily")
    logger.info("scheduled_daily_sync_completed", batch_count=len(results))


async def run_hourly_sync() -> None:
    """Lightweight hourly pulse: refresh entity metadata (status/budget
    changes) and Insights for the last 3 days, so intraday dashboards stay
    current without the cost of a full daily sync, across every configured
    Meta ad account, in parallel."""
    logger.info("scheduled_hourly_sync_started")
    coordinator = MultiAccountSyncCoordinator()
    for endpoint in ("campaigns", "adsets", "ads"):
        await coordinator.sync_endpoint(
            endpoint, sync_type="incremental", triggered_by="scheduler_hourly"
        )
    await coordinator.sync_insights(
        levels=list(InsightsLevel),
        date_preset=DatePreset.LAST_3D,
        sync_type="incremental",
        triggered_by="scheduler_hourly",
    )
    logger.info("scheduled_hourly_sync_completed")


async def _delta_sync_one_account(account_key: str, *, overlap: int, lookback: int) -> None:
    """One account's delta refresh, in its own session."""
    async with session_scope() as session:
        try:
            since = await last_fetch_epoch(
                session,
                account_key=account_key,
                overlap_seconds=overlap,
                max_lookback_days=lookback,
            )
            written = await refresh_changed_since(
                session, account_key=account_key, since_epoch=since
            )
        except Exception as exc:  # noqa: BLE001 - one account must not stop the rest
            logger.error("meta_delta_sync_failed", account_key=account_key, error=str(exc))
            return
    logger.info("meta_delta_sync_completed", account_key=account_key, **written)


async def run_meta_delta_sync() -> None:
    """Near-real-time entity refresh: ask Meta which campaigns/ad sets/ads
    changed since we last looked, re-read just those, and re-flatten just
    those rows into Silver.

    This is what carries a status flip or an edit onto the dashboard within
    minutes. It is not the webhook: Meta's `ad_account` webhook topic has
    six fields and none of them fires on ACTIVE/PAUSED or on an ordinary
    edit (see docs/meta-webhooks.md), so the webhook can only ever cover
    review outcomes and issue flags. Filtering the account edge on
    `updated_time` is the only mechanism that sees the rest.

    Accounts run concurrently, and that is not an optimisation. Each
    account has its own rate-limit budget, but a throttled one is slow in
    a way that has to be seen to be believed: against an account already
    over its CPU budget, the client's own backoff spent 37 minutes across
    six attempts (117% -> 106% -> 107% -> 107% -> 102% -> 97%, then a
    200). Sequentially, that one account would hold the healthy ones
    behind it for longer than the whole interval, and `max_instances: 1`
    would then coalesce away the runs that were supposed to cover them.
    """
    settings = get_settings()

    # Any webhook whose background task was lost to a restart. Same work,
    # so it belongs here rather than on a timer of its own.
    try:
        await process_pending_meta_events()
    except Exception as exc:  # noqa: BLE001 - the delta refresh still has to run
        logger.error("meta_webhook_backlog_failed", error=str(exc))

    overlap = settings.scheduler.meta_delta_overlap_seconds
    lookback = settings.scheduler.meta_delta_max_lookback_days
    # return_exceptions, because the per-account handler cannot catch
    # everything -- a failure opening the session happens outside it, and
    # without this one account's connection problem cancels the others
    # mid-flight.
    results = await asyncio.gather(*(
        _delta_sync_one_account(account.key, overlap=overlap, lookback=lookback)
        for account in settings.meta.accounts
    ), return_exceptions=True)
    for account, result in zip(settings.meta.accounts, results, strict=True):
        if isinstance(result, BaseException):
            logger.error(
                "meta_delta_sync_crashed", account_key=account.key, error=str(result)
            )


async def run_historical_backfill() -> None:
    """One-off (or manually re-triggered) pull of every configured
    account's entire available history across every entity and Insights
    level, in parallel across accounts."""
    logger.info("historical_backfill_started")
    coordinator = MultiAccountSyncCoordinator()
    results = await coordinator.sync_all(sync_type="backfill", triggered_by="backfill")
    await coordinator.sync_insights(
        levels=list(InsightsLevel),
        date_preset=DatePreset.MAXIMUM,
        sync_type="backfill",
        triggered_by="backfill",
    )
    logger.info("historical_backfill_completed", batch_count=len(results))


async def run_retry_failed_jobs(*, max_jobs: int = 100) -> None:
    """Replay unresolved :class:`FailedJob` rows against their original
    endpoint + request params, using the *same account* each job originally
    failed on (``job.account_key``) — not just whichever account happens to
    be configured first, which would silently retry against the wrong
    account in a multi-account setup. A job is marked resolved on success;
    on repeated failure its attempt counter increments and it stays queued.
    """
    logger.info("retry_failed_jobs_started")
    resolved = 0
    still_failing = 0

    async with session_scope() as session:
        repo = FailedJobRepository(session)
        jobs = await repo.list_unresolved(limit=max_jobs)

    if not jobs:
        logger.info("retry_failed_jobs_none_pending")
        return

    for job in jobs:
        async with session_scope() as session:
            repo = FailedJobRepository(session)
            try:
                credentials = get_meta_credentials(job.account_key)
                async with MetaAPIClient(credentials) as client:
                    orchestrator = SyncOrchestrator(session, client)
                    if job.endpoint == "insights":
                        await orchestrator.sync_insights(
                            sync_type="manual",
                            triggered_by="retry",
                            **insights_retry_kwargs(job.request_params or {}),
                        )
                    else:
                        await orchestrator.sync_endpoint(
                            job.endpoint,
                            request_params=job.request_params,
                            sync_type="manual",
                            triggered_by="retry",
                        )
                await repo.mark_resolved(job.id)
                resolved += 1
            except Exception as exc:  # noqa: BLE001 - keep retrying other jobs
                await repo.increment_attempt(job.id, error_message=str(exc))
                still_failing += 1
                logger.warning("retry_failed_job_still_failing", job_id=str(job.id), error=str(exc))

    logger.info("retry_failed_jobs_completed", resolved=resolved, still_failing=still_failing)


async def run_flatten_poll() -> None:
    """Checks every Schema Browser flatten job with auto-flatten switched on
    (see app/services/silver/registry.py) and re-runs any whose source table
    has newer data than what was last flattened. Runs on its own interval —
    deliberately not hooked into sync completion — so it catches staleness
    from any ingestion path (scheduler jobs, admin-panel manual fetches,
    ad-hoc scripts), not just the ones explicitly wired to call it."""
    async with session_scope() as session:
        await run_auto_enabled_jobs(session)
