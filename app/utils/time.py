"""Timezone-aware time helpers. Always use :func:`utcnow` instead of
``datetime.utcnow()`` (deprecated / naive) or ``datetime.now()``."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
