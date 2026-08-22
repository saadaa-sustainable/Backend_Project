"""Schemas for ``/failed-jobs``."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FailedJobSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    endpoint: str
    account_key: str | None = None
    account_name: str | None = None
    error_message: str
    attempt_count: int
    resolved: bool
    created_at: datetime
    last_attempted_at: datetime


class RetryFailedJobsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retried: int
    resolved: int
    still_failing: int
