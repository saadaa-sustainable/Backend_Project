"""The Insights ingestion engine.

The single most important — and highest-volume — endpoint in the Meta
Marketing API. Supports every combination of:

* **level**: account / campaign / adset / ad
* **date range**: any ``date_preset`` (including ``maximum`` for full
  history), an explicit ``since``/``until`` range, or multiple comparison
  ``time_ranges``
* **time_increment**: aggregate the whole range (``all_days``), bucket by
  calendar month (``monthly``), or bucket into any number of days from 1
  to 90 (e.g. ``1`` = daily, ``7`` = weekly, ``14`` = fortnightly)
* **breakdowns**: any number of breakdown *combinations*, each fetched as
  its own request (Meta returns one breakdown combination per call)
* **action_breakdowns**: how the nested actions/action_values/
  cost_per_action_type arrays are sliced (separate axis from ``breakdowns``)
* **attribution windows**: the exact set of click/view windows (or the
  account's DDA default) applied to every action/conversion metric, plus
  ``use_unified_attribution_setting`` / ``use_account_attribution_setting``
  / ``action_report_time`` for full control over how Meta counts actions
* **filtering / sort / summary**: object-level filters, result ordering,
  and an aggregate totals row, exactly as the Insights endpoint supports
* **fields**: defaults to the full metric registry in
  :mod:`app.core.meta_registry` — delivery, spend, clicks, conversions,
  revenue/ROAS, catalog segments, SKAdNetwork postbacks, video, engagement,
  messaging, Marketing Messages, estimated ad recall, quality/relevance,
  Instant Experience, and every action/cost/value array Meta exposes.
* **async reports**: ``use_async=True`` submits the request via
  ``POST`` and polls ``report_run_id`` instead of paginating a synchronous
  ``GET`` — recommended for very large pulls (e.g. ``date_preset=maximum``)
  that risk timing out synchronously.

Because this is a combinatorial fan-out (levels × breakdown combos), it does
not fit the simple one-edge-per-service template in
:class:`~app.services.meta.base.BaseMetaSyncService` and instead implements
its own batch lifecycle, reusing the same repositories.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Boolean, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import mapped_column

from app.core.exceptions import IngestionError
from app.core.meta_registry import (
    LEVEL_EXCLUDED_FIELDS,
    LEVEL_RESTRICTED_METRICS,
    ActionReportTime,
    DatePreset,
    InsightsLevel,
    TimeIncrement,
    get_insights_fields,
    resolve_action_breakdowns,
    resolve_attribution_windows,
    resolve_time_increment,
    validate_breakdown_combination,
    validate_breakdown_level_compatibility,
    validate_field_breakdown_compatibility,
)
from app.logging.setup import get_logger
from app.models.base import Base, BronzeMixin
from app.models.raw_dump import MetaObjectType, RawDumpMeta
from app.models.sync import SyncBatch
from app.repositories.base import DEFAULT_CHUNK_SIZE, BronzeRepository
from app.repositories.batch_repository import BatchRepository
from app.repositories.failed_job_repository import FailedJobRepository
from app.services.meta.client import MetaAPIClient
from app.utils.hashing import hash_payload
from app.utils.time import utcnow

logger = get_logger(__name__)

#: Meta's default page_size (META_PAGE_SIZE, normally 250) intermittently
#: fails ("Please reduce the amount of data you're asking for") a few pages
#: into ad/adset-level pagination on larger accounts once combined with the
#: full ~169-field default set -- confirmed live 2026-08-21, isolated to
#: pagination depth (same account/fields/date-range succeeds cleanly at 50,
#: verified past 800 items with zero failures where 250 failed repeatedly
#: around item 500). Used as sync()'s default so every caller (scheduler
#: jobs, admin-panel manual fetches, retries) gets the reliable value
#: without having to know to ask for it; pass an explicit page_size to
#: override for a specific call.
DEFAULT_INSIGHTS_PAGE_SIZE = 50

#: Levels that default to async (POST + poll, see MetaAPIClient.start_async_report)
#: when sync()'s `use_async` param is left at its default (None). Confirmed live
#: 2026-08-25: the full ~169-field default set deterministically fails with
#: "Please reduce the amount of data you're asking for" on ad/adset-level requests
#: at ANY date range (even a single month) -- entity count (ads/adsets vastly
#: outnumber campaigns per account) is what triggers it, not field count or date
#: range breadth in isolation, since campaign-level succeeds with the SAME full
#: field set across the SAME account's full 8-month history. The same full-field
#: adset request that fails deterministically under sync succeeded under async on
#: the first attempt (proving async raises the ceiling) -- but async is NOT
#: perfectly reliable either: of 3 back-to-back identical async attempts, 1
#: succeeded and 2 failed with DIFFERENT symptoms each time (a random "nonexisting
#: summary field" error naming a different field each run, and a bare "Job
#: Failed" with no detail) -- the same class of genuine Meta-side intermittency
#: already documented for sync requests elsewhere in this file, not a
#: deterministic field-identity problem. This means async is a real improvement
#: (turns an ALWAYS-fails case into a SOMETIMES-fails one) but still leans on
#: this project's existing retry infrastructure (failed_jobs + the scheduled
#: retry job) to eventually succeed, not a one-shot fix.
_ASYNC_BY_DEFAULT_LEVELS = frozenset({InsightsLevel.AD, InsightsLevel.ADSET})


#: Explicit date_range spans longer than this get split into multiple
#: sub-requests within sync() (see _date_chunks below). NOT the fix for the
#: "reduce the amount of data" failures diagnosed 2026-08-25 -- those were
#: driven by entity count (ad/adset level), not date-range breadth: even a
#: single MONTH of full-field-set adset data failed under sync mode, so
#: chunking alone wouldn't have helped without Change 1 (async) first. This
#: is a secondary reliability layer for genuinely wide ranges (e.g. a
#: multi-year historical date_range) -- smaller async report jobs are less
#: likely to hit Meta's own internal processing-complexity failures than
#: one giant one. Scoped to explicit date_range only, not date_preset
#: (resolving e.g. DatePreset.MAXIMUM to real dates needs Meta-side account-
#: creation-date knowledge this client doesn't have, and date_preset wasn't
#: implicated in any diagnosed failure -- LAST_30D and smaller presets are
#: already under this threshold).
DATE_CHUNK_DAYS = 15

#: Fixed-size field-count batching, added 2026-08-25 as the deterministic fix
#: for "reduce the amount of data" -- confirmed live that async (Change 1) +
#: date-chunking (Change 2) + lower concurrency (Change 4) do NOT eliminate
#: this error on their own: a real post-fix re-test (adset level, full
#: 169-field set, one month split into 3 date-chunks by Change 2) still
#: failed all 3/3 chunks. The actual trigger is FIELD COUNT combined with
#: entity count at ad/adset level (confirmed live 2026-08-21: the identical
#: request succeeds with ~19 fields, fails with all 169, independent of date
#: range -- even a single month failed). Splitting the full field set into
#: fixed-size batches and running each as its own request keeps every
#: individual request under the threshold that actually causes the failure,
#: rather than hoping async/retries route around it after the fact.
#:
#: 40 is a starting point, not a value verified against Meta's real
#: threshold -- the confirmed-working case used ~19 fields, the confirmed-
#: failing case used 169; 40 sits well inside that gap but hasn't itself
#: been live-tested at time of writing. Revisit if batches still fail.
INSIGHTS_FIELD_BATCH_SIZE = 40

#: Included in EVERY field batch (not split across batches) so each batch's
#: response rows can be correctly matched up and merged back into one
#: complete row per entity -- these are exactly the fields _build_row()
#: itself reads (meta_id via f"{level.value}_id", and parent_ids' account_id/
#: campaign_id/adset_id/ad_id/date_start/date_stop), not the much larger
#: INSIGHTS_FIELD_GROUPS['identity'] group (which bundles in objective/
#: buying_type/etc -- fine as ordinary batched fields, not needed for
#: merging itself).
_MERGE_KEY_FIELDS: frozenset[str] = frozenset(
    {"account_id", "campaign_id", "adset_id", "ad_id", "date_start", "date_stop"}
)


def _should_batch_fields(level: InsightsLevel, field_count: int) -> bool:
    """Auto-enable field-count batching for ad/adset levels once the field
    set is large enough to need it -- same shape as _should_use_async, and
    orthogonal to it (a batched sub-request can itself go through async or
    sync depending on _should_use_async's own per-level decision)."""
    return level in _ASYNC_BY_DEFAULT_LEVELS and field_count > INSIGHTS_FIELD_BATCH_SIZE


def _batch_fields(fields: list[str], batch_size: int = INSIGHTS_FIELD_BATCH_SIZE) -> list[list[str]]:
    """Split `fields` into fixed-size batches, with _MERGE_KEY_FIELDS present
    in every batch (added on top of, not counted against, `batch_size` --
    keeps each batch's actual payload-field count consistent regardless of
    how many merge keys happen to already be in the caller's field list)."""
    merge_keys = [f for f in fields if f in _MERGE_KEY_FIELDS]
    payload_fields = [f for f in fields if f not in _MERGE_KEY_FIELDS]
    if not payload_fields:
        return [fields]
    batches = []
    for i in range(0, len(payload_fields), batch_size):
        chunk = payload_fields[i : i + batch_size]
        batches.append(merge_keys + chunk)
    return batches


def _date_chunks(start: date, end: date, chunk_days: int = DATE_CHUNK_DAYS) -> list[tuple[date, date]]:
    """Split [start, end] into consecutive <=chunk_days windows. Returns a single
    (start, end) chunk unchanged if the range is already <=chunk_days -- callers
    don't need to special-case the common (small-range) case."""
    if (end - start).days < chunk_days:
        return [(start, end)]
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _should_use_async(level: InsightsLevel, combo: list[str], explicit: bool | None) -> bool:
    """Resolves sync()'s `use_async=None` (auto) into a concrete bool for one
    (level, breakdown-combo) request. An explicit True/False from the caller
    always wins -- this heuristic only fills in the default."""
    if explicit is not None:
        return explicit
    if level in _ASYNC_BY_DEFAULT_LEVELS:
        return True
    # Breakdowns multiply row count the same way high entity-count levels do
    # (age x gender, placement x device, etc.) -- same risk, any level.
    return bool(combo)


#: target_table=None (the overwhelming majority of calls -- every scheduler
#: job, every /sync/insights request) must resolve to the literal RawDumpMeta
#: class, not a clone -- verified via `is` identity, not just matching
#: schema, since anything else would be a behavior change for existing
#: callers. Only an admin-panel-picked custom table name builds a new
#: class, cloning RawDumpMeta's own three extra columns + BronzeMixin under
#: a different __tablename__ -- reuses the exact same envelope an admin
#: creates via POST /admin/tables/raw?source=meta (see admin.py), so a row
#: built by _build_row() below inserts identically either way. Cached so
#: SQLAlchemy is never asked to map the same table name to two different
#: classes within one process.
_MODEL_CACHE: dict[str, type[RawDumpMeta]] = {"raw_dump_meta": RawDumpMeta}


def _resolve_model(target_table: str | None) -> type[RawDumpMeta]:
    table = target_table or "raw_dump_meta"
    if table not in _MODEL_CACHE:
        _MODEL_CACHE[table] = type(
            f"RawDumpMeta_{table}",
            (Base, BronzeMixin),
            {
                "__tablename__": table,
                "object_type": mapped_column(String(32), nullable=False, index=True),
                "parent_ids": mapped_column(JSONB),
                "is_nested": mapped_column(Boolean, nullable=False, default=False),
                "__table_args__": (
                    Index(f"ix_{table}_batch_meta", "batch_id", "meta_id"),
                    Index(f"ix_{table}_object_type_meta_id", "object_type", "meta_id"),
                    Index(f"ix_{table}_raw_payload_gin", "raw_payload", postgresql_using="gin"),
                ),
            },
        )
    return _MODEL_CACHE[table]


def _retry_request_params(
    *,
    level: InsightsLevel,
    date_preset: DatePreset | None,
    date_range: tuple[date, date] | None,
    time_ranges: list[tuple[date, date]] | None,
    resolved_time_increment: str,
    combo: list[str],
    action_breakdowns: list[str] | None,
    attribution_windows: list[str] | None,
    use_unified_attribution_setting: bool | None,
    use_account_attribution_setting: bool | None,
    action_report_time: ActionReportTime | None,
    field_groups: list[str] | None,
    extra_fields: list[str] | None,
    filtering: list[dict[str, Any]] | None,
    sort: list[str] | None,
    summary: list[str] | None,
    default_summary: bool | None,
    summary_action_breakdowns: list[str] | None,
    product_id_limit: int | None,
    locale: str | None,
    use_async: bool,
    chunk_size: int,
    page_size: int | None,
) -> dict[str, Any]:
    """JSON-safe kwargs matching :meth:`InsightsSyncService.sync`'s OWN parameter
    names -- deliberately NOT Meta's wire-format request params (what
    ``_build_request_params`` returns, e.g. singular ``level``, comma-joined
    ``fields``), which cannot be fed back into ``sync()`` at all. This is what
    gets stored on a ``failed_jobs`` row so a retry can reconstruct a call that
    repeats exactly this one (level, breakdown-combo) pair. Pair with
    :func:`insights_retry_kwargs`, which reconstructs the enums/dates this loses
    in the JSONB round-trip."""
    return {
        "levels": [level.value],
        "date_preset": date_preset.value if date_preset else None,
        "date_range": (
            {"since": date_range[0].isoformat(), "until": date_range[1].isoformat()}
            if date_range
            else None
        ),
        "time_ranges": (
            [{"since": s.isoformat(), "until": u.isoformat()} for s, u in time_ranges]
            if time_ranges
            else None
        ),
        "time_increment": resolved_time_increment,
        "breakdowns": [combo] if combo else None,
        "action_breakdowns": action_breakdowns,
        "attribution_windows": attribution_windows,
        "use_unified_attribution_setting": use_unified_attribution_setting,
        "use_account_attribution_setting": use_account_attribution_setting,
        "action_report_time": action_report_time.value if action_report_time else None,
        "field_groups": field_groups,
        "extra_fields": extra_fields,
        "filtering": filtering,
        "sort": sort,
        "summary": summary,
        "default_summary": default_summary,
        "summary_action_breakdowns": summary_action_breakdowns,
        "product_id_limit": product_id_limit,
        "locale": locale,
        "use_async": use_async,
        "chunk_size": chunk_size,
        "page_size": page_size,
    }


def insights_retry_kwargs(stored: dict[str, Any]) -> dict[str, Any]:
    """Reconstructs real ``sync()``-ready kwargs (enums, ``date`` objects) from a
    ``failed_jobs`` row's ``request_params``. JSONB only round-trips
    JSON-safe primitives, so callers (see ``app/scheduler/jobs.py``'s
    ``run_retry_failed_jobs``) must run stored params through this before
    spreading them into ``sync()`` -- passing the raw dict straight through
    crashes the moment ``sync()`` touches ``level.value``/``date_preset.value``
    on what's actually still a plain ``str``."""
    kwargs = dict(stored)
    if kwargs.get("levels") is not None:
        kwargs["levels"] = [InsightsLevel(v) for v in kwargs["levels"]]
    if kwargs.get("date_preset") is not None:
        kwargs["date_preset"] = DatePreset(kwargs["date_preset"])
    if kwargs.get("date_range") is not None:
        dr = kwargs["date_range"]
        kwargs["date_range"] = (date.fromisoformat(dr["since"]), date.fromisoformat(dr["until"]))
    if kwargs.get("time_ranges") is not None:
        kwargs["time_ranges"] = [
            (date.fromisoformat(tr["since"]), date.fromisoformat(tr["until"]))
            for tr in kwargs["time_ranges"]
        ]
    if kwargs.get("action_report_time") is not None:
        kwargs["action_report_time"] = ActionReportTime(kwargs["action_report_time"])
    return kwargs


class InsightsSyncService:
    """Ingestion engine for the ``/insights`` edge."""

    endpoint_name = "insights"
    object_type = MetaObjectType.INSIGHTS
    model = RawDumpMeta

    def __init__(
        self, session: AsyncSession, client: MetaAPIClient, target_table: str | None = None
    ) -> None:
        self.session = session
        self.client = client
        self.model = _resolve_model(target_table)
        self.repository = BronzeRepository(session, self.model)
        self.batch_repository = BatchRepository(session)
        self.failed_job_repository = FailedJobRepository(session)

    async def sync(
        self,
        *,
        levels: list[InsightsLevel] | None = None,
        date_preset: DatePreset | None = None,
        date_range: tuple[date, date] | None = None,
        time_ranges: list[tuple[date, date]] | None = None,
        time_increment: TimeIncrement | int = TimeIncrement.ALL_DAYS,
        breakdowns: list[list[str]] | None = None,
        action_breakdowns: list[str] | None = None,
        attribution_windows: list[str] | None = None,
        use_unified_attribution_setting: bool | None = None,
        use_account_attribution_setting: bool | None = None,
        action_report_time: ActionReportTime | None = None,
        field_groups: list[str] | None = None,
        extra_fields: list[str] | None = None,
        filtering: list[dict[str, Any]] | None = None,
        sort: list[str] | None = None,
        summary: list[str] | None = None,
        default_summary: bool | None = None,
        summary_action_breakdowns: list[str] | None = None,
        product_id_limit: int | None = None,
        locale: str | None = None,
        use_async: bool | None = None,
        sync_type: str = "manual",
        triggered_by: str = "api",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        page_size: int | None = DEFAULT_INSIGHTS_PAGE_SIZE,
    ) -> SyncBatch:
        """Run Insights ingestion across every requested (level, breakdown
        combination) pair and return the completed :class:`SyncBatch`.

        ``use_async``: ``None`` (the default) auto-decides per (level, combo)
        via :func:`_should_use_async` -- ad/adset levels and any breakdown
        combo go async, campaign/account stay sync (both proven reliable at
        the full field set). Pass an explicit ``True``/``False`` to force one
        mode for every request this call makes, overriding the per-level
        heuristic.

        ``page_size``: overrides ``META_PAGE_SIZE`` (default 250) for this
        call's Meta API pagination. Confirmed live 2026-08-21: large
        accounts combined with the full ~169-field default set intermittently
        fail ("Please reduce the amount of data you're asking for") once
        pagination goes a few pages deep at the default page size, but the
        SAME data succeeds cleanly at ``page_size=50`` (verified past 800
        items with zero failures where 250 failed repeatedly around item
        500) -- smaller pages, more requests, each response small enough
        Meta's backend doesn't choke on it. Worth trying first for any
        account that keeps hitting this error deep into an ad/adset-level
        pull.

        Raises :class:`ValueError` up front (before any HTTP calls) if the
        date/breakdown/attribution-window selection is invalid, so bad
        requests fail fast instead of burning API quota.
        """
        resolved_time_increment = resolve_time_increment(time_increment)
        levels = levels or list(InsightsLevel)
        breakdown_combos = breakdowns if breakdowns is not None else [[]]
        for combo in breakdown_combos:
            if combo:
                validate_breakdown_combination(combo)
                for level in levels:
                    validate_breakdown_level_compatibility(combo, level.value)

        fields = get_insights_fields(include_groups=field_groups, extra_fields=extra_fields)
        for combo in breakdown_combos:
            if combo:
                validate_field_breakdown_compatibility(fields, combo)

        resolved_windows = resolve_attribution_windows(attribution_windows)
        resolved_action_breakdowns = (
            resolve_action_breakdowns(action_breakdowns) if action_breakdowns else None
        )

        date_selection_count = sum(bool(x) for x in (date_preset, date_range, time_ranges))
        if date_selection_count > 1:
            raise ValueError("Provide at most one of date_preset, date_range, time_ranges.")
        if date_selection_count == 0:
            date_preset = DatePreset.LAST_30D

        # Split a wide explicit date_range into <=DATE_CHUNK_DAYS windows -- see
        # DATE_CHUNK_DAYS' docstring for why this is scoped to date_range only
        # (not date_preset/time_ranges) and what it does/doesn't fix. A single-
        # element list for the common case keeps the loop below unconditional.
        date_range_chunks: list[tuple[date, date] | None] = (
            _date_chunks(date_range[0], date_range[1]) if date_range else [None]
        )

        request_params: dict[str, Any] = {
            "levels": [level.value for level in levels],
            "date_preset": date_preset.value if date_preset else None,
            "date_range": (
                {"since": date_range[0].isoformat(), "until": date_range[1].isoformat()}
                if date_range
                else None
            ),
            "time_ranges": (
                [{"since": s.isoformat(), "until": u.isoformat()} for s, u in time_ranges]
                if time_ranges
                else None
            ),
            "time_increment": resolved_time_increment,
            "breakdowns": breakdown_combos,
            "action_breakdowns": action_breakdowns,
            "attribution_windows": attribution_windows,
            "use_unified_attribution_setting": use_unified_attribution_setting,
            "use_account_attribution_setting": use_account_attribution_setting,
            "action_report_time": action_report_time.value if action_report_time else None,
            # field_groups/extra_fields (not the resolved flat `fields` list) --
            # this dict doubles as retry kwargs for the whole-method catch-all
            # failure below, and "fields" isn't one of sync()'s own parameter
            # names (see insights_retry_kwargs() / _retry_request_params()).
            "field_groups": field_groups,
            "extra_fields": extra_fields,
            "filtering": filtering,
            "sort": sort,
            "summary": summary,
            "default_summary": default_summary,
            "summary_action_breakdowns": summary_action_breakdowns,
            "product_id_limit": product_id_limit,
            "locale": locale,
            "use_async": use_async,
            "chunk_size": chunk_size,
            "page_size": page_size,
        }

        batch = await self.batch_repository.create(
            endpoint=self.endpoint_name,
            sync_type=sync_type,
            request_params=request_params,
            triggered_by=triggered_by,
            account_key=self.client.credentials.account_key,
            account_name=self.client.credentials.account_name,
        )
        log = logger.bind(endpoint=self.endpoint_name, batch_id=str(batch.id))
        log.info("insights_sync_started", **request_params)

        fetched = 0
        failed = 0

        try:
            for level in levels:
                for metric in fields:
                    allowed_levels = LEVEL_RESTRICTED_METRICS.get(metric)
                    if allowed_levels and level.value not in allowed_levels:
                        log.warning(
                            "insights_metric_not_meaningful_at_level",
                            metric=metric,
                            level=level.value,
                            meaningful_at=allowed_levels,
                        )

                # Unlike LEVEL_RESTRICTED_METRICS (soft -- Meta returns
                # null/0, just log a warning), LEVEL_EXCLUDED_FIELDS fields
                # get the WHOLE request hard-rejected at this level if left
                # in, so they're dropped from what's actually sent rather
                # than merely warned about.
                excluded_at_level = LEVEL_EXCLUDED_FIELDS.get(level.value, frozenset())
                level_fields = [f for f in fields if f not in excluded_at_level] if excluded_at_level else fields

                for combo in breakdown_combos:
                    for chunk_range in date_range_chunks:
                        params = self._build_request_params(
                            level=level,
                            fields=level_fields,
                            date_preset=date_preset,
                            date_range=chunk_range,
                            time_ranges=time_ranges,
                            time_increment=resolved_time_increment,
                            breakdown_combo=combo,
                            resolved_action_breakdowns=resolved_action_breakdowns,
                            resolved_windows=resolved_windows,
                            use_unified_attribution_setting=use_unified_attribution_setting,
                            use_account_attribution_setting=use_account_attribution_setting,
                            action_report_time=action_report_time,
                            filtering=filtering,
                            sort=sort,
                            summary=summary,
                            default_summary=default_summary,
                            summary_action_breakdowns=summary_action_breakdowns,
                            product_id_limit=product_id_limit,
                            locale=locale,
                        )
                        effective_use_async = _should_use_async(level, combo, use_async)
                        try:
                            fetched, failed = await self._sync_one(
                                level=level,
                                combo=combo,
                                params=params,
                                level_fields=level_fields,
                                attribution_windows=attribution_windows,
                                time_increment=resolved_time_increment,
                                batch_id=batch.id,
                                sync_type=sync_type,
                                chunk_size=chunk_size,
                                use_async=effective_use_async,
                                page_size=page_size,
                                fetched=fetched,
                                failed=failed,
                                log=log,
                            )
                        except Exception as exc:  # noqa: BLE001 -- isolated per (level, combo, date-chunk) on
                            # purpose: one chunk exhausting its retries (confirmed live 2026-08-20 that Meta's
                            # "reduce the amount of data" error on the /insights edge is genuinely
                            # intermittent -- ~1-in-5 on an identical isolated retry with zero
                            # concurrent load, not a fixable request-size/concurrency threshold)
                            # must not discard every OTHER level/chunk that already succeeded. Mirrors
                            # _flush's existing per-chunk failure handling below, one level up.
                            breakdowns_label = ",".join(combo) if combo else None
                            log.error(
                                "insights_level_failed",
                                level=level.value,
                                breakdowns=breakdowns_label,
                                date_chunk=(
                                    f"{chunk_range[0]}..{chunk_range[1]}" if chunk_range else None
                                ),
                                error=str(exc),
                            )
                            await self.failed_job_repository.record_failure(
                                batch_id=batch.id,
                                endpoint=self.endpoint_name,
                                error_message=str(exc),
                                request_params=_retry_request_params(
                                    level=level,
                                    date_preset=date_preset,
                                    date_range=chunk_range,
                                    time_ranges=time_ranges,
                                    resolved_time_increment=resolved_time_increment,
                                    combo=combo,
                                    action_breakdowns=action_breakdowns,
                                    attribution_windows=attribution_windows,
                                    use_unified_attribution_setting=use_unified_attribution_setting,
                                    use_account_attribution_setting=use_account_attribution_setting,
                                    action_report_time=action_report_time,
                                    field_groups=field_groups,
                                    extra_fields=extra_fields,
                                    filtering=filtering,
                                    sort=sort,
                                    summary=summary,
                                    default_summary=default_summary,
                                    summary_action_breakdowns=summary_action_breakdowns,
                                    product_id_limit=product_id_limit,
                                    locale=locale,
                                    use_async=effective_use_async,
                                    chunk_size=chunk_size,
                                    page_size=page_size,
                                ),
                                account_key=self.client.credentials.account_key,
                                account_name=self.client.credentials.account_name,
                            )
                            failed += 1

            await self.batch_repository.complete(
                batch.id, records_fetched=fetched, records_failed=failed
            )
            log.info("insights_sync_completed", records_fetched=fetched, records_failed=failed)
        except Exception as exc:  # noqa: BLE001
            log.error("insights_sync_failed", error=str(exc))
            await self.batch_repository.fail(batch.id, error_message=str(exc))
            await self.failed_job_repository.record_failure(
                batch_id=batch.id,
                endpoint=self.endpoint_name,
                error_message=str(exc),
                request_params=request_params,
                account_key=self.client.credentials.account_key,
                account_name=self.client.credentials.account_name,
            )
            raise IngestionError(f"Insights ingestion failed: {exc}") from exc

        refreshed = await self.batch_repository.get(batch.id)
        assert refreshed is not None
        return refreshed

    # ------------------------------------------------------------------

    def _build_request_params(
        self,
        *,
        level: InsightsLevel,
        fields: list[str],
        date_preset: DatePreset | None,
        date_range: tuple[date, date] | None,
        time_ranges: list[tuple[date, date]] | None,
        time_increment: str,
        breakdown_combo: list[str],
        resolved_action_breakdowns: list[str] | None,
        resolved_windows: list[str],
        use_unified_attribution_setting: bool | None,
        use_account_attribution_setting: bool | None,
        action_report_time: ActionReportTime | None,
        filtering: list[dict[str, Any]] | None,
        sort: list[str] | None,
        summary: list[str] | None,
        default_summary: bool | None,
        summary_action_breakdowns: list[str] | None,
        product_id_limit: int | None,
        locale: str | None,
    ) -> dict[str, Any]:
        # Per the Ads Insights reference: `fields`, `breakdowns`,
        # `action_breakdowns`, `summary`, and `summary_action_breakdowns`
        # are comma-separated strings; `time_range`/`time_ranges`/
        # `filtering`/`action_attribution_windows` are JSON objects/arrays
        # (the client's `_normalize_params` JSON-encodes any list/dict
        # value automatically, so those are passed through as native
        # Python lists/dicts here).
        params: dict[str, Any] = {
            "level": level.value,
            "fields": ",".join(fields),
            "time_increment": time_increment,
        }
        if date_preset:
            params["date_preset"] = date_preset.value
        elif date_range:
            params["time_range"] = {
                "since": date_range[0].isoformat(),
                "until": date_range[1].isoformat(),
            }
        elif time_ranges:
            params["time_ranges"] = [
                {"since": s.isoformat(), "until": u.isoformat()} for s, u in time_ranges
            ]

        if breakdown_combo:
            params["breakdowns"] = ",".join(breakdown_combo)
        if resolved_action_breakdowns:
            params["action_breakdowns"] = ",".join(resolved_action_breakdowns)
        if resolved_windows:
            params["action_attribution_windows"] = resolved_windows
        if use_unified_attribution_setting is not None:
            params["use_unified_attribution_setting"] = use_unified_attribution_setting
        if use_account_attribution_setting is not None:
            params["use_account_attribution_setting"] = use_account_attribution_setting
        if action_report_time:
            params["action_report_time"] = action_report_time.value
        if filtering:
            params["filtering"] = filtering
        if sort:
            params["sort"] = ",".join(sort)
        if summary:
            params["summary"] = ",".join(summary)
        if default_summary is not None:
            params["default_summary"] = default_summary
        if summary_action_breakdowns:
            params["summary_action_breakdowns"] = ",".join(summary_action_breakdowns)
        if product_id_limit is not None:
            params["product_id_limit"] = product_id_limit
        if locale:
            params["locale"] = locale
        return params

    async def _fetch_insights_page(
        self, params: dict[str, Any], *, use_async: bool, page_size: int | None, log: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """Runs ONE Insights request (a single field-set / date-range /
        breakdown combination) to completion and yields its result rows.
        Factored out of _sync_one so both the single-request path and the
        batched-fields path (_sync_one_batched) share the exact same async-
        report-vs-sync-pagination logic."""
        insights_path = f"{self.client.credentials.ad_account_id_prefixed}/insights"
        if use_async:
            report_run_id = await self.client.start_async_report(insights_path, params=params)
            log.info("insights_async_report_started", report_run_id=report_run_id)
            await self.client.poll_async_report(report_run_id)
            async for item in self.client.paginate_async_report(report_run_id):
                yield item
        else:
            async for item in self.client.paginate(insights_path, params=params, page_size=page_size):
                yield item

    async def _sync_one_batched(
        self,
        *,
        level: InsightsLevel,
        level_fields: list[str],
        params: dict[str, Any],
        page_size: int | None,
        log: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Splits level_fields into INSIGHTS_FIELD_BATCH_SIZE-sized batches,
        runs each as its own complete request, merges results back into one
        dict per entity keyed by that entity's own id field (e.g. `ad_id` at
        ad level), then yields the merged rows -- see
        INSIGHTS_FIELD_BATCH_SIZE's docstring for why this exists. An async
        generator so _sync_one's own loop stays unified with the
        single-request path (`async for item in item_iterator`), but it
        can't actually stream/flush incrementally the way that path can: an
        entity's row isn't complete until EVERY batch has been merged in, so
        the full per-(level, date-chunk) entity set is held in memory until
        all batches finish, THEN yielded one at a time. Bounded by one
        date-chunk's worth of entities (DATE_CHUNK_DAYS already caps
        date-range breadth), not the account's full history.

        Always sync mode (use_async=False), never the outer call's
        _should_use_async result -- confirmed live 2026-08-25 that a
        batch-sized (~46 field) request succeeds cleanly under sync (1775
        real rows, no error) where the full 169-field set never does, so
        batching alone already solves the problem async was routing around.
        Using async here too would ADD its own separate, unrelated failure
        mode for no benefit: confirmed live the same day that async result
        retrieval intermittently fails with "(#100) Tried accessing
        nonexisting summary field" on a DIFFERENT field each attempt
        (adset_end, then adset_start, on identical requests) -- genuine
        Meta-side async flakiness, not something excluding one field fixes."""
        id_field = f"{level.value}_id"
        merged: dict[str, dict[str, Any]] = {}
        field_batches = _batch_fields(level_fields)
        log.info(
            "insights_field_batching_started",
            level=level.value,
            batch_count=len(field_batches),
            total_fields=len(level_fields),
        )
        for batch_num, field_batch in enumerate(field_batches):
            batch_params = {**params, "fields": ",".join(field_batch)}
            async for item in self._fetch_insights_page(
                batch_params, use_async=False, page_size=page_size, log=log
            ):
                key = item.get(id_field)
                if key is None:
                    # No entity id on this row (shouldn't happen -- id_field is
                    # always in _MERGE_KEY_FIELDS, present in every batch) --
                    # keep it standalone rather than silently dropping data.
                    key = f"__unkeyed_{batch_num}_{len(merged)}"
                if key in merged:
                    merged[key].update(item)
                else:
                    merged[key] = item
        log.info("insights_field_batching_merged", level=level.value, entity_count=len(merged))
        for item in merged.values():
            yield item

    async def _sync_one(
        self,
        *,
        level: InsightsLevel,
        combo: list[str],
        params: dict[str, Any],
        level_fields: list[str],
        attribution_windows: list[str] | None,
        time_increment: str,
        batch_id: uuid.UUID,
        sync_type: str,
        chunk_size: int,
        use_async: bool,
        page_size: int | None,
        fetched: int,
        failed: int,
        log: Any,
    ) -> tuple[int, int]:
        buffer: list[dict[str, Any]] = []
        breakdowns_label = ",".join(combo) if combo else None
        attribution_label = ",".join(attribution_windows) if attribution_windows else "dda"

        if _should_batch_fields(level, len(level_fields)):
            item_iterator = self._sync_one_batched(
                level=level,
                level_fields=level_fields,
                params=params,
                page_size=page_size,
                log=log,
            )
        else:
            item_iterator = self._fetch_insights_page(
                params, use_async=use_async, page_size=page_size, log=log
            )

        async for item in item_iterator:
            buffer.append(
                self._build_row(
                    item,
                    batch_id=batch_id,
                    level=level,
                    breakdowns_label=breakdowns_label,
                    attribution_label=attribution_label,
                    time_increment=time_increment,
                    request_params=params,
                    sync_type=sync_type,
                )
            )
            if len(buffer) >= chunk_size:
                fetched, failed = await self._flush(buffer, batch_id, fetched, failed, log)
                buffer = []

        if buffer:
            fetched, failed = await self._flush(buffer, batch_id, fetched, failed, log)

        return fetched, failed

    def _build_row(
        self,
        item: dict[str, Any],
        *,
        batch_id: uuid.UUID,
        level: InsightsLevel,
        breakdowns_label: str | None,
        attribution_label: str,
        time_increment: str,
        request_params: dict[str, Any],
        sync_type: str,
    ) -> dict[str, Any]:
        now = utcnow()
        return {
            "id": uuid.uuid4(),
            # Insights rows have no Meta-assigned id of their own — the
            # level's own object id is the closest thing, and is already
            # present in raw_payload for anything that actually needs it.
            "meta_id": item.get(f"{level.value}_id"),
            "raw_payload": item,
            "api_endpoint": self.endpoint_name,
            "api_version": self.client.credentials.api_version,
            "batch_id": batch_id,
            "request_params": request_params,
            "extracted_at": now,
            "sync_type": sync_type,
            "payload_hash": hash_payload(item),
            "processing_status": "pending",
            "object_type": self.object_type,
            "is_nested": False,
            "parent_ids": {
                "account_key": self.client.credentials.account_key,
                "account_name": self.client.credentials.account_name,
                "account_id": item.get("account_id"),
                "campaign_id": item.get("campaign_id"),
                "adset_id": item.get("adset_id"),
                "ad_id": item.get("ad_id"),
                "level": level.value,
                "date_start": item.get("date_start"),
                "date_stop": item.get("date_stop"),
                "time_increment": time_increment,
                "breakdowns": breakdowns_label,
                "attribution_window": attribution_label,
            },
        }

    async def _flush(
        self,
        buffer: list[dict[str, Any]],
        batch_id: uuid.UUID,
        fetched: int,
        failed: int,
        log: Any,
    ) -> tuple[int, int]:
        try:
            inserted = await self.repository.bulk_insert(buffer)
            return fetched + inserted, failed
        except Exception as exc:  # noqa: BLE001
            log.error("insights_chunk_failed", chunk_size=len(buffer), error=str(exc))
            # A DB-level failure (e.g. a unique-constraint violation) leaves this
            # session's transaction in a poisoned state -- any further statement on
            # it, including the record_failure() insert below, raises
            # PendingRollbackError and crashes the whole sync instead of isolating
            # just this chunk. Confirmed live 2026-08-21 against a target table with
            # a stray (object_type, meta_id) unique index. Roll back first so the
            # failure gets recorded instead of compounding into a bigger crash.
            await self.session.rollback()
            # NOTE: {"chunk_size": N} is not retry-able via sync_insights(**params) --
            # it's missing levels/date_range/etc, so a retry would silently run a full
            # default-shaped sync instead of anything related to this chunk. No live
            # failures have hit this path yet (unlike the per-level fetch failures
            # below, which _did_ -- see _retry_request_params/insights_retry_kwargs);
            # fix the same way (thread level/date_preset/date_range/combo into
            # _flush) if this ever actually fires.
            await self.failed_job_repository.record_failure(
                batch_id=batch_id,
                endpoint=self.endpoint_name,
                error_message=str(exc),
                request_params={"chunk_size": len(buffer)},
                account_key=self.client.credentials.account_key,
                account_name=self.client.credentials.account_name,
            )
            return fetched, failed + len(buffer)
