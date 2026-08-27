"""Flatten job execution + the staleness check that decides whether a run
is even necessary.

Two small tables back this (created lazily, same "safe to call every
time" pattern as `app/services/meta/entity_flatten.py`):

- ``flatten_settings`` — one row per registered job, holding the
  Schema Browser's per-table auto-flatten toggle. Mutable, small.
- ``flatten_runs`` — append-only log of every flatten attempt (the "logs
  table" the automatic trigger reads from), recording ``source_covered_at``
  (``MAX(extracted_at)`` in the source table *at the time of that run*) so
  a later check can tell "has the source moved past what I last flattened"
  without re-scanning the target table.

The automatic trigger (a scheduled poll — see ``app/scheduler/jobs.py``)
and the manual "Flatten now" button in the Schema Browser both call
``check_and_maybe_run``; the only difference is ``force`` and
``triggered_by``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger
from app.services.silver.registry import FLATTEN_REGISTRY, FlattenJob

logger = get_logger(__name__)

_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS flatten_settings (
        job_key text PRIMARY KEY,
        auto_enabled boolean NOT NULL DEFAULT false,
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS flatten_runs (
        id uuid PRIMARY KEY,
        job_key text NOT NULL,
        status text NOT NULL,
        triggered_by text NOT NULL,
        source_covered_at timestamptz,
        rows_written jsonb,
        error_message text,
        started_at timestamptz NOT NULL,
        finished_at timestamptz
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_flatten_runs_job_key_finished_at ON flatten_runs (job_key, finished_at DESC)",
]


async def ensure_flatten_tables(session: AsyncSession) -> None:
    for statement in _DDL_STATEMENTS:
        await session.execute(text(statement))
    await session.commit()


@dataclass(frozen=True)
class JobState:
    job: FlattenJob
    auto_enabled: bool
    source_max_extracted_at: datetime | None
    last_run_status: str | None
    last_run_at: datetime | None
    last_run_triggered_by: str | None
    last_source_covered_at: datetime | None
    last_rows_written: dict[str, int] | None
    last_error: str | None

    @property
    def is_stale(self) -> bool:
        if self.source_max_extracted_at is None:
            return False  # source has no data at all yet -- nothing to flatten
        if self.last_source_covered_at is None:
            return True  # never successfully flattened
        return self.source_max_extracted_at > self.last_source_covered_at


async def get_job_state(session: AsyncSession, job: FlattenJob) -> JobState:
    await ensure_flatten_tables(session)

    source_max = (
        await session.execute(text(f"SELECT MAX(extracted_at) FROM {job.source_table}"))
    ).scalar_one_or_none()

    settings_row = (
        await session.execute(
            text("SELECT auto_enabled FROM flatten_settings WHERE job_key = :key"),
            {"key": job.key},
        )
    ).fetchone()
    auto_enabled = bool(settings_row.auto_enabled) if settings_row else False

    last_run = (
        await session.execute(
            text(
                "SELECT status, triggered_by, source_covered_at, rows_written, error_message, finished_at "
                "FROM flatten_runs WHERE job_key = :key AND status = 'succeeded' "
                "ORDER BY finished_at DESC LIMIT 1"
            ),
            {"key": job.key},
        )
    ).fetchone()
    # asyncpg decodes jsonb at the driver level regardless of whether the
    # query went through a typed Column or raw text() -- already a dict.
    rows_written = last_run.rows_written if last_run else None

    return JobState(
        job=job,
        auto_enabled=auto_enabled,
        source_max_extracted_at=source_max,
        last_run_status=last_run.status if last_run else None,
        last_run_at=last_run.finished_at if last_run else None,
        last_run_triggered_by=last_run.triggered_by if last_run else None,
        last_source_covered_at=last_run.source_covered_at if last_run else None,
        last_rows_written=rows_written,
        last_error=last_run.error_message if last_run else None,
    )


async def set_auto_enabled(session: AsyncSession, job_key: str, enabled: bool) -> None:
    await ensure_flatten_tables(session)
    await session.execute(
        text(
            "INSERT INTO flatten_settings (job_key, auto_enabled, updated_at) "
            "VALUES (:key, :enabled, now()) "
            "ON CONFLICT (job_key) DO UPDATE SET auto_enabled = :enabled, updated_at = now()"
        ),
        {"key": job_key, "enabled": enabled},
    )
    await session.commit()


async def check_and_maybe_run(
    session: AsyncSession, job: FlattenJob, *, force: bool = False, triggered_by: str = "manual"
) -> JobState:
    """Runs `job.refresh()` if the source has newer data than the last successful run covered
    (or unconditionally, if `force`), logs the attempt to `flatten_runs`, and returns the
    resulting state either way -- callers that just want "is this stale" without running
    anything should call `get_job_state` instead."""
    state = await get_job_state(session, job)
    if not force and not state.is_stale:
        return state

    run_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)
    await session.execute(
        text(
            "INSERT INTO flatten_runs (id, job_key, status, triggered_by, source_covered_at, started_at) "
            "VALUES (:id, :key, 'running', :triggered_by, :covered, :started)"
        ),
        {
            "id": run_id,
            "key": job.key,
            "triggered_by": triggered_by,
            "covered": state.source_max_extracted_at,
            "started": started_at,
        },
    )
    await session.commit()

    try:
        rows_written = await job.refresh(session)
    except Exception as exc:  # noqa: BLE001 -- logged to flatten_runs, not swallowed
        # A failure inside job.refresh() (e.g. a statement timeout mid-INSERT)
        # leaves the session's transaction aborted -- asyncpg refuses every
        # further command on it until a ROLLBACK, which would otherwise make
        # the "record the failure" UPDATE below itself raise
        # InFailedSQLTransactionError and mask the real error.
        await session.rollback()
        await session.execute(
            text(
                "UPDATE flatten_runs SET status = 'failed', error_message = :error, finished_at = now() "
                "WHERE id = :id"
            ),
            {"error": str(exc)[:500], "id": run_id},
        )
        await session.commit()
        logger.error("flatten_job_failed", job_key=job.key, error=str(exc))
        raise

    await session.execute(
        text(
            "UPDATE flatten_runs SET status = 'succeeded', rows_written = CAST(:rows AS jsonb), finished_at = now() "
            "WHERE id = :id"
        ),
        {"rows": json.dumps(rows_written), "id": run_id},
    )
    await session.commit()
    logger.info("flatten_job_succeeded", job_key=job.key, **rows_written)

    return await get_job_state(session, job)


async def run_auto_enabled_jobs(session: AsyncSession) -> None:
    """Poller entry point (see app/scheduler/jobs.py) -- checks every job with
    auto_enabled=true and runs any that are stale. Errors in one job never block the rest."""
    for job in FLATTEN_REGISTRY.values():
        state = await get_job_state(session, job)
        if not state.auto_enabled:
            continue
        try:
            await check_and_maybe_run(session, job, force=False, triggered_by="auto_poll")
        except Exception as exc:  # noqa: BLE001 -- one job's failure shouldn't block the others
            logger.error("flatten_auto_poll_job_failed", job_key=job.key, error=str(exc))
