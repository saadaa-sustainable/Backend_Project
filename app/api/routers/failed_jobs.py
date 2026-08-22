"""``/failed-jobs`` endpoints: inspect and manually retry the retry queue."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.repositories.failed_job_repository import FailedJobRepository
from app.schemas.failed_jobs import FailedJobSchema, RetryFailedJobsResponse
from app.scheduler.jobs import run_retry_failed_jobs

router = APIRouter(prefix="/failed-jobs", tags=["failed-jobs"])


@router.get("", response_model=list[FailedJobSchema])
async def list_failed_jobs(
    session: SessionDep,
    endpoint: str | None = Query(default=None),
    account: str | None = Query(default=None, description="Filter to one account's key."),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[FailedJobSchema]:
    repo = FailedJobRepository(session)
    jobs = await repo.list_unresolved(endpoint=endpoint, account_key=account, limit=limit)
    return [FailedJobSchema.model_validate(job) for job in jobs]


@router.post("/retry", response_model=RetryFailedJobsResponse)
async def retry_failed_jobs(
    session: SessionDep, max_jobs: int = Query(default=100, ge=1, le=1000)
) -> RetryFailedJobsResponse:
    """Synchronously replay unresolved failed jobs against their original
    endpoint + params. For large backlogs, prefer letting the scheduler's
    periodic retry job (see ``SCHEDULER_RETRY_INTERVAL_MINUTES``) handle it
    in the background instead of blocking this request.
    """
    repo = FailedJobRepository(session)
    before = await repo.list_unresolved(limit=max_jobs)

    await run_retry_failed_jobs(max_jobs=max_jobs)

    after = await repo.list_unresolved(limit=max_jobs)
    resolved = len(before) - len(after) if len(after) <= len(before) else 0
    return RetryFailedJobsResponse(
        retried=len(before), resolved=max(resolved, 0), still_failing=len(after)
    )
