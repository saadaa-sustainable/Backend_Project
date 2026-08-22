"""Operational tables: sync batch tracking and failed-job retry queue.

These are not Bronze data tables — they record *metadata about ingestion
runs* so the API can expose ``/status``, ``/logs`` and ``/failed-jobs``, and
so the scheduler can retry failed batches without re-fetching everything.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BatchStatus:
    """Allowed values for :attr:`SyncBatch.status`."""

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class SyncBatch(Base):
    """One row per ingestion run of a single endpoint/service.

    ``id`` is the ``batch_id`` referenced by every Bronze row produced during
    this run, giving full lineage from a raw record back to the sync job
    that created it.
    """

    __tablename__ = "sync_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Which configured Meta ad account this batch ran against — nullable
    #: only for business-scoped endpoints (business_assets, catalogs,
    #: products) where "account" isn't really the right dimension.
    account_key: Mapped[str | None] = mapped_column(String(16), index=True)
    account_name: Mapped[str | None] = mapped_column(String(128))
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=BatchStatus.RUNNING, index=True
    )
    request_params: Mapped[dict | None] = mapped_column(JSONB)
    records_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)


class FailedJob(Base):
    """A retryable unit of work (single page/request) that failed permanently
    within a batch's retry budget, queued for later replay by the
    ``retry_failed_batches`` scheduler job."""

    __tablename__ = "failed_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Which configured account this failure happened on — the retry job
    #: needs this to resolve the right credentials, not just any account's.
    account_key: Mapped[str | None] = mapped_column(String(16), index=True)
    account_name: Mapped[str | None] = mapped_column(String(128))
    request_params: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
