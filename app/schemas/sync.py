"""Request/response schemas for the ``/sync/*`` endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.meta_registry import (
    ActionReportTime,
    DatePreset,
    FilterOperator,
    InsightsLevel,
    TimeIncrement,
    resolve_time_increment,
)


class SyncRequest(BaseModel):
    """Common options accepted by every simple object-sync endpoint
    (accounts, campaigns, adsets, ads, creatives, assets, audiences,
    pixels, activities, business assets, catalogs, products, labels)."""

    model_config = ConfigDict(extra="forbid")

    account: str | None = Field(
        default=None,
        description=(
            "Which configured Meta ad account to sync (the numeric suffix from "
            "META_ACCOUNT_<N>_ID, e.g. '1'). Omit to sync every configured account."
        ),
    )
    sync_type: str = Field(default="manual", description="manual | full | incremental | backfill")
    triggered_by: str = Field(default="api", description="Who/what triggered this sync.")


class CampaignTreeSyncRequest(BaseModel):
    """Options for the nested campaign->adset->ad throttling-optimized
    fetch (see ``app/services/meta/nested_tree.py``)."""

    model_config = ConfigDict(extra="forbid")

    nested_limit: int = Field(
        default=100, ge=1, le=1000, description="Max ad sets per campaign / ads per ad set embedded."
    )
    page_size: int = Field(default=25, ge=1, le=500, description="Campaigns fetched per top-level page.")
    include_insights: bool = Field(
        default=False,
        description=(
            "Embed a nested insights connection per ad. Off by default — verify the "
            "nested-insights modifier syntax against your API version before enabling; "
            "prefer /sync/insights for anything production-critical."
        ),
    )
    insights_date_preset: str = Field(default="last_30d")
    account: str | None = Field(
        default=None, description="Numeric account key (e.g. '1'); omit for every account."
    )
    sync_type: str = Field(default="manual")
    triggered_by: str = Field(default="api")


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    since: date
    until: date

    @model_validator(mode="after")
    def _validate_range(self) -> "DateRange":
        if self.until < self.since:
            raise ValueError("`until` must not be before `since`.")
        return self


class FilterCondition(BaseModel):
    """One entry of the Insights ``filtering`` parameter, e.g.
    ``{"field": "spend", "operator": "GREATER_THAN", "value": 100}``."""

    model_config = ConfigDict(extra="forbid")

    field: str
    operator: FilterOperator
    value: Any


class InsightsSyncRequest(BaseModel):
    """Full set of options for the Insights ingestion engine."""

    model_config = ConfigDict(extra="forbid")

    account: str | None = Field(
        default=None,
        description=(
            "Which configured Meta ad account to sync (numeric suffix from "
            "META_ACCOUNT_<N>_ID). Omit to sync every configured account."
        ),
    )
    levels: list[InsightsLevel] = Field(default_factory=lambda: list(InsightsLevel))
    date_preset: DatePreset | None = Field(
        default=None, description="Mutually exclusive with `date_range` and `time_ranges`."
    )
    date_range: DateRange | None = Field(default=None)
    time_ranges: list[DateRange] | None = Field(
        default=None,
        description=(
            "Multiple date ranges to compare in one request (Meta's `time_ranges` "
            "param). Mutually exclusive with `date_preset` and `date_range`."
        ),
    )
    time_increment: TimeIncrement | int = Field(
        default=TimeIncrement.ALL_DAYS,
        description=(
            "`all_days`, `monthly`, or any integer number of days from 1 to 90 "
            "(e.g. 1 = daily, 7 = weekly)."
        ),
    )

    @field_validator("time_increment")
    @classmethod
    def _validate_time_increment(cls, value: "TimeIncrement | int") -> "TimeIncrement | int":
        resolve_time_increment(value)  # raises ValueError for an out-of-range int
        return value
    breakdowns: list[list[str]] = Field(
        default_factory=list,
        description=(
            "List of breakdown combinations to fetch, e.g. "
            '[["age", "gender"], ["publisher_platform", "platform_position"]]. '
            "An empty list means \"no breakdown\" is also fetched."
        ),
    )
    action_breakdowns: list[str] | None = Field(
        default=None,
        description="Slices the actions/action_values arrays. Defaults to ['action_type'].",
    )
    attribution_windows: list[str] | None = Field(
        default=None, description="Defaults to the registry's DEFAULT_ATTRIBUTION_WINDOWS."
    )
    use_unified_attribution_setting: bool | None = Field(
        default=None, description="Set true to match what Ads Manager displays."
    )
    use_account_attribution_setting: bool | None = Field(
        default=None, description="Use the ad account's configured default attribution window."
    )
    action_report_time: ActionReportTime | None = Field(
        default=None, description="When an action is counted: impression | conversion | mixed."
    )
    field_groups: list[str] | None = Field(
        default=None, description="Restrict to specific registry groups; omit for all fields."
    )
    extra_fields: list[str] | None = Field(default=None)
    filtering: list[FilterCondition] | None = Field(
        default=None, description="e.g. campaign.effective_status IN ['ACTIVE']."
    )
    sort: list[str] | None = Field(
        default=None, description="e.g. ['spend_descending']."
    )
    summary: list[str] | None = Field(
        default=None, description="Fields to also return as an aggregate totals row."
    )
    default_summary: bool | None = Field(default=None)
    summary_action_breakdowns: list[str] | None = Field(default=None)
    product_id_limit: int | None = Field(default=None, ge=1)
    locale: str | None = Field(default=None, description="e.g. 'en_US' — affects name strings.")
    use_async: bool = Field(
        default=False,
        description=(
            "Use the async report-run flow (POST -> poll -> GET) instead of a "
            "synchronous paginated GET. Recommended for very large pulls (e.g. "
            "date_preset=maximum across a long-lived account) that risk timing "
            "out as a single synchronous request."
        ),
    )
    sync_type: str = Field(default="manual")
    triggered_by: str = Field(default="api")

    @model_validator(mode="after")
    def _validate_date_selection(self) -> "InsightsSyncRequest":
        provided = [bool(self.date_preset), bool(self.date_range), bool(self.time_ranges)]
        if sum(provided) > 1:
            raise ValueError(
                "Provide at most one of `date_preset`, `date_range`, `time_ranges`."
            )
        if not any(provided):
            self.date_preset = DatePreset.LAST_30D
        return self


class SyncResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_key: str
    account_name: str
    batch_id: uuid.UUID
    endpoint: str
    status: str
    records_fetched: int
    records_failed: int
    started_at: datetime
    finished_at: datetime | None = None


class MultiSyncResponse(BaseModel):
    """One entry per account a sync ran against — every ``/sync/*`` route
    returns this shape now, whether it touched one account (``account=``
    given) or every configured account (the default)."""

    model_config = ConfigDict(extra="forbid")

    batches: list[SyncResponse]
