"""Repository for :class:`app.models.sync.SyncBatch` — the ingestion run
ledger backing ``/status`` and ``/logs``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import BatchStatus, SyncBatch
from app.utils.time import utcnow


class BatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        endpoint: str,
        sync_type: str,
        request_params: dict[str, Any] | None = None,
        triggered_by: str = "manual",
        account_key: str | None = None,
        account_name: str | None = None,
    ) -> SyncBatch:
        batch = SyncBatch(
            id=uuid.uuid4(),
            endpoint=endpoint,
            account_key=account_key,
            account_name=account_name,
            sync_type=sync_type,
            status=BatchStatus.RUNNING,
            request_params=request_params,
            triggered_by=triggered_by,
        )
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def complete(
        self, batch_id: uuid.UUID, *, records_fetched: int, records_failed: int = 0
    ) -> None:
        batch = await self.get(batch_id)
        if batch is None:
            return
        batch.records_fetched = records_fetched
        batch.records_failed = records_failed
        batch.status = BatchStatus.PARTIAL_FAILURE if records_failed else BatchStatus.SUCCESS
        batch.finished_at = utcnow()
        await self.session.flush()

    async def fail(self, batch_id: uuid.UUID, *, error_message: str) -> None:
        batch = await self.get(batch_id)
        if batch is None:
            return
        batch.status = BatchStatus.FAILED
        batch.error_message = error_message[:4000]
        batch.finished_at = utcnow()
        await self.session.flush()

    async def get(self, batch_id: uuid.UUID) -> SyncBatch | None:
        result = await self.session.execute(select(SyncBatch).where(SyncBatch.id == batch_id))
        return result.scalar_one_or_none()

    async def list_recent(
        self,
        *,
        endpoint: str | None = None,
        account_key: str | None = None,
        limit: int = 50,
    ) -> list[SyncBatch]:
        stmt = select(SyncBatch).order_by(SyncBatch.started_at.desc()).limit(limit)
        if endpoint:
            stmt = stmt.where(SyncBatch.endpoint == endpoint)
        if account_key:
            stmt = stmt.where(SyncBatch.account_key == account_key)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
