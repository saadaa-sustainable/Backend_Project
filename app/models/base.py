"""Declarative base and shared Bronze-layer column mixin.

Every raw ingestion table inherits :class:`BronzeMixin`, guaranteeing a
consistent audit trail (batch id, extraction/ingestion timestamps, payload
hash, processing status, ...) across all Meta object types without
duplicating column definitions. The Bronze layer stores data exactly as
Meta returned it — ``raw_payload`` is never mutated after insert.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Project-wide declarative base. Import this (not per-model bases)."""

    type_annotation_map = {
        dict: JSONB,
    }


class ProcessingStatus:
    """Allowed values for :attr:`BronzeMixin.processing_status`."""

    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SyncType:
    """Allowed values for :attr:`BronzeMixin.sync_type`."""

    FULL = "full"
    INCREMENTAL = "incremental"
    BACKFILL = "backfill"
    MANUAL = "manual"


class BronzeMixin:
    """Common columns for every raw (Bronze) ingestion table.

    Columns
    -------
    id: surrogate primary key for this row (one row per API object per fetch).
    meta_id: the Meta-assigned identifier of the object (campaign_id, ad_id, ...).
    raw_payload: the complete, unmodified JSON object as returned by the Graph API.
    api_endpoint: the Graph API path/edge that produced this row (e.g. "/campaigns").
    api_version: the Graph API version used for the request (e.g. "v21.0").
    batch_id: FK-like reference to the ``sync_batches.id`` run that produced this row.
    request_params: the exact query parameters sent to Meta for this request.
    extracted_at: timestamp when the record was read from the Meta API response.
    ingested_at: timestamp when the record was persisted to PostgreSQL.
    sync_type: one of :class:`SyncType` — how this row was produced.
    payload_hash: sha256 of the canonicalized raw payload, for change detection.
    processing_status: Bronze -> Silver promotion status, one of :class:`ProcessingStatus`.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meta_id: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    api_endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    api_version: Mapped[str] = mapped_column(String(16), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    request_params: Mapped[dict | None] = mapped_column(JSONB)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False, default=SyncType.MANUAL)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    processing_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ProcessingStatus.PENDING, index=True
    )

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return (
            Index(f"ix_{cls.__tablename__}_batch_meta", "batch_id", "meta_id"),
        )
