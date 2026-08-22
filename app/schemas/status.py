"""Schemas for ``/status``, ``/health``, and ``/logs``."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    app_name: str
    app_env: str
    database_ok: bool
    meta_api_ok: bool


class BatchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: uuid.UUID
    endpoint: str
    account_key: str | None = None
    account_name: str | None = None
    sync_type: str
    status: str
    records_fetched: int
    records_failed: int
    started_at: datetime
    finished_at: datetime | None
    triggered_by: str
    error_message: str | None = None


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_batches: int
    running: int
    succeeded: int
    partial_failures: int
    failed: int
    recent_batches: list[BatchSummary]
