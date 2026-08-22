from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.meta_registry import DatePreset
from app.schemas.sync import DateRange, InsightsSyncRequest


def test_insights_request_defaults_date_preset_when_neither_given() -> None:
    request = InsightsSyncRequest()
    assert request.date_preset == DatePreset.LAST_30D
    assert request.date_range is None


def test_insights_request_rejects_both_preset_and_range() -> None:
    with pytest.raises(ValidationError, match="at most one"):
        InsightsSyncRequest(
            date_preset=DatePreset.LAST_7D,
            date_range=DateRange(since="2026-01-01", until="2026-01-31"),
        )


def test_insights_request_rejects_preset_and_time_ranges() -> None:
    with pytest.raises(ValidationError, match="at most one"):
        InsightsSyncRequest(
            date_preset=DatePreset.LAST_7D,
            time_ranges=[DateRange(since="2026-01-01", until="2026-01-31")],
        )


def test_date_range_rejects_until_before_since() -> None:
    with pytest.raises(ValidationError, match="must not be before"):
        DateRange(since="2026-02-01", until="2026-01-01")


def test_insights_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        InsightsSyncRequest(not_a_real_field=True)
