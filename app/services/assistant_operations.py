"""Bounded operational reads. No table contents, raw logs, secrets or generated SQL."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.services.analytics_cache import cached_analytics

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")
WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
# Only these fixed table/column identifiers can be used in freshness SQL.
DATASETS = {
    "meta_ads": ("insights_daily_by_ad", "day"),
    "shopify_orders": ("shopify_orders", "created_at"),
    "sku_daily": ("cpis_by_sku_daily", "day"),
    "shopify_sessions": ("shopify_sessions_daily", "day"),
    "landing_page_sessions": ("landing_page_sessions_daily", "session_date"),
    "shopify_sales": ("shopify_sales_daily", "day"),
}


class OperationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RefreshInput(OperationsInput):
    limit: int = Field(default=5, ge=1, le=20)


class FreshnessInput(OperationsInput):
    dataset: Literal["all", "meta_ads", "shopify_orders", "sku_daily", "shopify_sessions",
                     "landing_page_sessions", "shopify_sales"] = "all"


class TablesInput(OperationsInput):
    table: str | None = Field(default=None, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$",
                              description="Exact public table name to inspect columns; omit to list tables.")
    search: str = Field(default="", max_length=100, description="Literal substring of a table name.")
    limit: int = Field(default=25, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10000)


OPERATION_SPECS = {
    "get_refresh_status": (RefreshInput,
        "Read recent backend_project cron-run records with safe step outcomes, checked-out GitHub "
        "workflow schedules, and the backend process scheduler. A recorded running status is NOT "
        "proof a GitHub job is still live. Does not start, retry or modify jobs."),
    "get_data_freshness": (FreshnessInput,
        "Check latest available reporting dates for Meta ads, Shopify orders, SKU daily, sessions "
        "and sales, against yesterday in IST. Uses indexed or small-table reads. Missing data stays "
        "unknown. A latest date is not proof that all rows for that day were ingested."),
    "get_table_info": (TablesInput,
        "List public tables/views with estimated row counts, or inspect one table's columns and "
        "types. Supports bounded pagination and literal name search. Returns metadata only, not "
        "raw records, personal data, exact counts or arbitrary SQL results."),
}


def sourced(label: str, url: str, params: BaseModel, data: dict) -> dict:
    return {"source": {"label": label, "url": url, "filters": params.model_dump(mode="json"),
            "basis": "read-only operational observation", "retrieved_at": datetime.now(UTC).isoformat(),
            "cache_note": "Operational reads are cached for up to 60 seconds; observation time is not ingestion time.",
            "link_note": "Opens the related dashboard page; this response includes the specific evidence and filters."},
            "data": data}


def workflow_definitions() -> list[dict]:
    definitions = []
    for filename in ("daily-refresh.yml", "shopify-refresh.yml"):
        path = WORKFLOWS / filename
        if not path.is_file():
            definitions.append({"file": filename, "available": False})
            continue
        content = path.read_text()
        name = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
        crons = re.findall(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", content, re.MULTILINE)
        definitions.append({"file": filename, "name": name.group(1) if name else filename,
                            "available": True, "cron_utc": crons,
                            "manual_dispatch": bool(re.search(r"^\s+workflow_dispatch:", content, re.MULTILINE)),
                            "source": "workflow file in this backend deployment, not live GitHub API"})
    return definitions


@cached_analytics(ttl=60)
async def refresh_status(params: RefreshInput, session: Any) -> dict:
    from app.api.routers.ops import get_scheduler_status

    present = (await session.execute(text("SELECT to_regclass('public.cron_run_log') IS NOT NULL"))).scalar()
    runs = []
    if present:
        result = await session.execute(text("""
            SELECT id, run_started, run_finished, duration_s, status, workflow_run,
                   n_steps_ok, n_steps_fail, (error IS NOT NULL) AS error_present,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object(
                       'name', left(s.key, 160), 'status', s.value->>'status',
                       'duration_s', s.value->'duration_s',
                       'error_present', COALESCE(s.value->>'error', '') <> ''))
                     FROM (SELECT key, value FROM jsonb_each(
                       CASE WHEN jsonb_typeof(steps) = 'object' THEN steps ELSE '{}'::jsonb END)
                       LIMIT 100) AS s), '[]'::jsonb) AS steps
            FROM public.cron_run_log WHERE project = :project
            ORDER BY run_started DESC, id DESC LIMIT :limit
        """), {"project": "backend_project", "limit": params.limit})
        for row in result.mappings():
            run = dict(row)
            for key in ("run_started", "run_finished"):
                run[key] = run[key].isoformat() if run[key] else None
            run["duration_s"] = float(run["duration_s"]) if run["duration_s"] is not None else None
            run["live_execution_verified"] = False
            runs.append(run)
    scheduler = await get_scheduler_status()
    return sourced("Refresh and scheduler status", "/cron", params, {
        "project": "backend_project", "ledger_available": bool(present), "runs": runs,
        "workflows": workflow_definitions(), "process_scheduler": scheduler.model_dump(mode="json"),
        "notes": ["The process scheduler is separate from GitHub Actions.",
                  "Run records may remain running after an interrupted process. Live GitHub queue/execution was not checked.",
                  "Step records update after a step ends. A successful run does not prove every dataset is current.",
                  "Raw errors and logs are omitted; error_present reports whether a failure was recorded."],
    })


def coverage(latest: str | None, today: date) -> dict:
    expected = today - timedelta(days=1)
    if latest is None:
        return {"latest_date": None, "expected_through": expected.isoformat(), "status": "no_data", "lag_days": None}
    if len(latest) == 10:
        day = date.fromisoformat(latest)
    else:
        timestamp = datetime.fromisoformat(latest)
        day = timestamp.astimezone(IST).date() if timestamp.tzinfo else timestamp.date()
    return {"latest_date": day.isoformat(), "expected_through": expected.isoformat(),
            "status": "future_date" if day > today else "lagging" if day < expected else "current",
            "lag_days": max(0, (expected - day).days)}


@cached_analytics(ttl=60)
async def data_freshness(params: FreshnessInput, session: Any) -> dict:
    selected = DATASETS if params.dataset == "all" else {params.dataset: DATASETS[params.dataset]}
    # Exclude partial/invalid indexes and indexes with expression keys. A large unindexed
    # table is reported unknown instead of scanning it for a chat question.
    result = await session.execute(text("""
        SELECT c.relname AS table_name, a.attname AS column_name, c.reltuples AS estimated_rows,
               EXISTS (SELECT 1 FROM pg_index i JOIN pg_class idx ON idx.oid = i.indexrelid
                       JOIN pg_am am ON am.oid = idx.relam
                       WHERE i.indrelid = c.oid AND i.indisvalid AND i.indisready
                         AND i.indpred IS NULL AND i.indkey[0] = a.attnum AND am.amname = 'btree') AS indexed
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        WHERE n.nspname = 'public' AND c.relkind IN ('r','m','p')
          AND c.relname = ANY(:tables) AND a.attname = ANY(:columns)
    """), {"tables": [value[0] for value in selected.values()], "columns": [value[1] for value in selected.values()]})
    metadata = {(row["table_name"], row["column_name"]): row for row in result.mappings()}
    entries, queries = {}, []
    for dataset, (table, column) in selected.items():
        entry = entries[dataset] = {"dataset": dataset, "table": table, "date_column": column,
                                    "latest_date": None, "lag_days": None, "status": "unknown"}
        meta = metadata.get((table, column))
        if meta is None:
            entry["reason"] = "Table or date column is unavailable."
        elif not meta["indexed"] and not 0 <= meta["estimated_rows"] <= 50000:
            entry["reason"] = "Skipped an unindexed large or unanalyzed table to avoid a heavy scan."
        else:
            # Identifiers and dataset names come exclusively from DATASETS, never model input.
            queries.append(f"SELECT '{dataset}' AS dataset, MAX(\"{column}\")::text AS latest FROM public.\"{table}\"")
    if queries:
        result = await session.execute(text(" UNION ALL ".join(queries)))
        today = datetime.now(IST).date()
        for row in result.mappings():
            entries[row["dataset"]].update(coverage(row["latest"], today))
    return sourced("Data freshness", "/user/analytics", params, {
        "timezone": "Asia/Kolkata", "datasets": list(entries.values()),
        "notes": ["Latest reporting/event date is not ingestion time or proof of complete coverage for that date.",
                  "Lag compares with yesterday in IST, not a guaranteed dataset refresh SLA.",
                  "Shopify orders use order creation time; late orders, updates and historical gaps need separate validation."],
    })


@cached_analytics(ttl=60)
async def table_info(params: TablesInput, session: Any) -> dict:
    result = await session.execute(text("""
        SELECT c.relname AS name, CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized_view'
                   WHEN 'p' THEN 'partitioned_table' ELSE 'table' END AS kind,
               CASE WHEN c.relkind = 'v' OR c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END AS estimated_rows
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m')
          AND (CAST(:table AS text) IS NULL OR c.relname = :table)
          AND position(lower(:search) in lower(c.relname)) > 0
        ORDER BY c.relname LIMIT :limit OFFSET :offset
    """), {"table": params.table, "search": "" if params.table else params.search,
           "limit": 1 if params.table else params.limit + 1, "offset": 0 if params.table else params.offset})
    rows = [dict(row) for row in result.mappings()]
    more = not params.table and len(rows) > params.limit
    rows = rows[:params.limit]
    if params.table and rows:
        result = await session.execute(text("""
            SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type,
                   NOT a.attnotnull AS nullable
            FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = :table AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum LIMIT 201
        """), {"table": params.table})
        columns = [dict(row) for row in result.mappings()]
        rows[0].update(columns=columns[:200], columns_truncated=len(columns) > 200)
    return sourced("Table schema", "/user/schema", params, {
        "schema": "public", "tables": rows, "has_more": more,
        "next_offset": params.offset + params.limit if more else None,
        "notes": ["Row counts are planner estimates, not exact or guaranteed current; views/unanalyzed tables may be unknown.",
                  "Only schema metadata is returned. No raw table records or stored defaults are exposed."],
    })


async def read_operation(name: str, params: BaseModel, session: Any) -> dict:
    return await {"get_refresh_status": refresh_status, "get_data_freshness": data_freshness,
                  "get_table_info": table_info}[name](params, session)
