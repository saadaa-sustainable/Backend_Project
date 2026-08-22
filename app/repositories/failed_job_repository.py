"""Repository for :class:`app.models.sync.FailedJob` — the retry queue
backing ``/failed-jobs`` and the scheduler's retry job."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import FailedJob
from app.utils.time import utcnow


class FailedJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_failure(
        self,
        *,
        batch_id: uuid.UUID,
        endpoint: str,
        error_message: str,
        request_params: dict[str, Any] | None = None,
        account_key: str | None = None,
        account_name: str | None = None,
    ) -> FailedJob:
        job = FailedJob(
            id=uuid.uuid4(),
            batch_id=batch_id,
            endpoint=endpoint,
            account_key=account_key,
            account_name=account_name,
            request_params=request_params,
            error_message=error_message[:4000],
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def list_unresolved(
        self,
        *,
        endpoint: str | None = None,
        account_key: str | None = None,
        limit: int = 100,
    ) -> list[FailedJob]:
        stmt = (
            select(FailedJob)
            .where(FailedJob.resolved.is_(False))
            .order_by(FailedJob.created_at.desc())
            .limit(limit)
        )
        if endpoint:
            stmt = stmt.where(FailedJob.endpoint == endpoint)
        if account_key:
            stmt = stmt.where(FailedJob.account_key == account_key)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_resolved(self, job_id: uuid.UUID) -> None:
        job = await self._get(job_id)
        if job is None:
            return
        job.resolved = True
        await self.session.flush()

    async def increment_attempt(self, job_id: uuid.UUID, *, error_message: str) -> None:
        job = await self._get(job_id)
        if job is None:
            return
        job.attempt_count += 1
        job.error_message = error_message[:4000]
        job.last_attempted_at = utcnow()
        await self.session.flush()

    async def _get(self, job_id: uuid.UUID) -> FailedJob | None:
        result = await self.session.execute(select(FailedJob).where(FailedJob.id == job_id))
        return result.scalar_one_or_none()
