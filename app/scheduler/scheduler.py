"""APScheduler lifecycle: build, start, and cleanly shut down the
process-wide async scheduler from FastAPI's lifespan context."""

from __future__ import annotations

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.logging.setup import get_logger
from app.scheduler.jobs import run_daily_sync, run_flatten_poll, run_hourly_sync, run_retry_failed_jobs

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        settings = get_settings().scheduler
        _scheduler = AsyncIOScheduler(
            executors={"default": AsyncIOExecutor()},
            timezone=settings.timezone,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
        )
    return _scheduler


def start_scheduler() -> AsyncIOScheduler:
    """Register jobs per settings and start the scheduler. Safe to call
    once at FastAPI startup; a no-op if scheduling is disabled."""
    settings = get_settings().scheduler
    scheduler = get_scheduler()

    if not settings.enabled:
        logger.info("scheduler_disabled_by_config")
        return scheduler

    scheduler.add_job(
        run_daily_sync,
        trigger=CronTrigger(hour=settings.daily_sync_hour, minute=settings.daily_sync_minute),
        id="daily_sync",
        name="Daily full-breadth Meta sync",
        replace_existing=True,
    )

    if settings.hourly_sync_enabled:
        scheduler.add_job(
            run_hourly_sync,
            trigger=IntervalTrigger(hours=1),
            id="hourly_sync",
            name="Hourly lightweight Meta sync",
            replace_existing=True,
        )

    scheduler.add_job(
        run_retry_failed_jobs,
        trigger=IntervalTrigger(minutes=settings.retry_interval_minutes),
        id="retry_failed_jobs",
        name="Retry failed ingestion batches",
        replace_existing=True,
    )

    scheduler.add_job(
        run_flatten_poll,
        trigger=IntervalTrigger(minutes=settings.flatten_poll_interval_minutes),
        id="flatten_poll",
        name="Auto-flatten stale Silver tables",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        daily_sync_hour=settings.daily_sync_hour,
        hourly_sync_enabled=settings.hourly_sync_enabled,
        retry_interval_minutes=settings.retry_interval_minutes,
        flatten_poll_interval_minutes=settings.flatten_poll_interval_minutes,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler_shutdown")
    _scheduler = None
