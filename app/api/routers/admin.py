"""Backend for the Next.js admin app (``admin/`` in the repo root) --
schema introspection and on-demand ingestion triggering.

Two routes make up the first slice (schema browser + fetch trigger):

* ``GET /admin/tables`` -- every table in the ``public`` schema, its
  columns/types, and an approximate row count (from ``pg_stat_user_tables``,
  not ``COUNT(*)`` -- instant regardless of table size, at the cost of being
  an estimate rather than exact). Requires a real ``DATABASE_URL`` --
  unlike every ``scripts/*.py`` ingestion script, which deliberately never
  needed one, this uses the async SQLAlchemy engine directly since
  PostgREST has no generic schema-introspection endpoint worth relying on.

* ``POST /admin/ingest`` + ``GET /admin/ingest/{run_id}`` -- trigger
  ingestion for a chosen set of sources over a chosen date range. Meta is
  fully wired (the existing insights engine already supports arbitrary
  date ranges natively -- this just calls the same
  :class:`~app.services.meta.orchestrator.MultiAccountSyncCoordinator`
  the ``/sync/insights`` route uses). Shopify and Instagram are
  deliberately reported as ``skipped`` rather than silently run with the
  date range ignored -- neither ``scripts/ingest_shopify.py`` nor
  ``scripts/ingest_instagram.py`` filters by date today. Wire those up
  (add ``--since``/``--until``, call them here as subprocesses) before
  flipping them to ``supports_date_range: true``.

Run tracking is an in-memory dict -- fine for a single-worker admin panel,
not safe across multiple uvicorn workers or process restarts. Move to a
real table (mirroring ``sync_batches``) before this runs in anything but a
single local/admin process.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import CoordinatorDep
from app.core.meta_registry import InsightsLevel
from app.database.session import get_engine

router = APIRouter(prefix="/admin", tags=["admin"])

# scripts/ never imports from app/ (kept standalone/Python-3.9-compatible
# deliberately, see that script's own docstring) -- this is the one
# accepted exception in the other direction: importing its already-async,
# argparse-free _run() core is far less work and risk than duplicating
# ~700 lines of Meta/Instagram fetch logic into app/services/. If this
# grows beyond Instagram, revisit whether that logic should move into
# app/services/ instead of scripts/ importing back and forth.
_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import ingest_instagram_chronological as ig_chronological  # noqa: E402


# ----------------------------------------------------------------------
# GET /admin/tables
# ----------------------------------------------------------------------

ColumnKind = Literal["identity", "numeric", "jsonb", "other"]

_NUMERIC_TYPES = {
    "numeric", "integer", "bigint", "smallint", "double precision", "real", "decimal",
}
_JSONB_TYPES = {"jsonb", "json"}
_IDENTITY_NAME_HINTS = ("_id", "_name", "id", "date_start", "date_stop", "_at", "_time")


def _classify_column(name: str, data_type: str) -> ColumnKind:
    dt = data_type.lower()
    if dt in _JSONB_TYPES:
        return "jsonb"
    if dt in _NUMERIC_TYPES:
        return "numeric"
    if name == "id" or any(name.endswith(hint) for hint in _IDENTITY_NAME_HINTS):
        return "identity"
    return "other"


class ColumnOut(BaseModel):
    name: str
    data_type: str
    is_nullable: bool
    kind: ColumnKind


class TableOut(BaseModel):
    name: str
    row_count: int | None
    columns: list[ColumnOut]


class TablesResponse(BaseModel):
    source: Literal["information_schema"] = "information_schema"
    tables: list[TableOut]


_COLUMNS_SQL = text(
    """
    SELECT table_name, column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema = 'public'
    ORDER BY table_name, ordinal_position
    """
)

_ROW_COUNTS_SQL = text(
    """
    SELECT relname AS table_name, n_live_tup AS row_count
    FROM pg_stat_user_tables
    WHERE schemaname = 'public'
    """
)


@router.get("/tables", response_model=TablesResponse)
async def list_tables() -> TablesResponse:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            columns_result = await conn.execute(_COLUMNS_SQL)
            row_count_result = await conn.execute(_ROW_COUNTS_SQL)
    except Exception as exc:  # noqa: BLE001 -- surface as a clear admin-panel error, not a 500 stack trace
        raise HTTPException(
            status_code=503,
            detail=(
                "Could not reach the database. Confirm DATABASE_URL in .env is a real "
                f"Postgres connection string (postgresql+asyncpg://...), not the Supabase REST "
                f"URL. Underlying error: {exc}"
            ),
        ) from exc

    row_counts = {row.table_name: row.row_count for row in row_count_result}

    tables_by_name: dict[str, list[ColumnOut]] = {}
    for row in columns_result:
        tables_by_name.setdefault(row.table_name, []).append(
            ColumnOut(
                name=row.column_name,
                data_type=row.data_type,
                is_nullable=row.is_nullable == "YES",
                kind=_classify_column(row.column_name, row.data_type),
            )
        )

    tables = [
        TableOut(name=name, row_count=row_counts.get(name), columns=columns)
        for name, columns in sorted(tables_by_name.items())
    ]
    return TablesResponse(tables=tables)


# ----------------------------------------------------------------------
# GET /admin/tables/{table}/object-types
# GET /admin/tables/{table}/jsonb-keys
#
# The schema browser above only sees the Bronze envelope -- raw_payload
# itself is one opaque jsonb column, and a single Bronze table mixes
# multiple object_types with completely different JSON shapes inside it.
# These two routes make that discoverable: first list the distinct
# object_type values in a table, then, for one of them, scan every
# matching row and report every key actually present inside raw_payload,
# its inferred type(s), and how often it shows up -- the complete set,
# not a sample (a capped sample can silently miss rarely-populated
# fields). This is what lets an admin build a
# custom Silver table from a source that has no hand-maintained field
# registry the way Meta does (app/core/meta_registry.py) -- Shopify and
# Instagram have nothing like it, so discovery from real data is the only
# option for them.
#
# table/column/filter_column arrive as user input but get interpolated
# into SQL as identifiers (not values -- those can't be parameterized the
# normal way), so every one of them is checked against
# information_schema.columns first and rejected with a 404 if it isn't a
# real, existing identifier. Only filter_value is a genuine value and goes
# through a bound parameter.
# ----------------------------------------------------------------------


async def _get_columns(conn, table: str) -> dict[str, str]:
    """column name -> data_type for one table, or {} if the table doesn't exist."""
    result = await conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table},
    )
    return {row.column_name: row.data_type for row in result}


class ObjectTypeCount(BaseModel):
    value: str
    row_count: int


class ObjectTypesResponse(BaseModel):
    table: str
    column: str
    values: list[ObjectTypeCount]


@router.get("/tables/{table}/object-types", response_model=ObjectTypesResponse)
async def list_object_types(table: str, column: str = "object_type") -> ObjectTypesResponse:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            columns = await _get_columns(conn, table)
            if not columns:
                raise HTTPException(status_code=404, detail=f"No table named '{table}'.")
            if column not in columns:
                raise HTTPException(
                    status_code=404, detail=f"Table '{table}' has no column named '{column}'."
                )
            result = await conn.execute(
                text(f'SELECT "{column}" AS value, COUNT(*) AS row_count FROM "{table}" GROUP BY "{column}" ORDER BY row_count DESC')
            )
            values = [ObjectTypeCount(value=row.value, row_count=row.row_count) for row in result if row.value is not None]
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not reach the database: {exc}") from exc

    return ObjectTypesResponse(table=table, column=column, values=values)


class JsonbKeyOut(BaseModel):
    key: str
    types: list[str]
    presence_count: int
    presence_pct: float


class JsonbKeysResponse(BaseModel):
    table: str
    column: str
    filter_column: str | None
    filter_value: str | None
    rows_scanned: int
    keys: list[JsonbKeyOut]


@router.get("/tables/{table}/jsonb-keys", response_model=JsonbKeysResponse)
async def discover_jsonb_keys(
    table: str,
    column: str = "raw_payload",
    filter_column: str | None = "object_type",
    filter_value: str | None = None,
) -> JsonbKeysResponse:
    # An explicit empty string means "no filter" (the admin/ frontend
    # always sends this param; omitting it would fall back to the
    # "object_type" default above, which is wrong for tables that don't
    # have one).
    if filter_column == "":
        filter_column = None

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            columns = await _get_columns(conn, table)
            if not columns:
                raise HTTPException(status_code=404, detail=f"No table named '{table}'.")
            if column not in columns:
                raise HTTPException(
                    status_code=404, detail=f"Table '{table}' has no column named '{column}'."
                )
            if columns[column] != "jsonb":
                raise HTTPException(
                    status_code=400, detail=f"Column '{column}' on '{table}' is {columns[column]}, not jsonb."
                )
            if filter_column and filter_column not in columns:
                raise HTTPException(
                    status_code=404, detail=f"Table '{table}' has no column named '{filter_column}'."
                )

            where_clause = ""
            params: dict[str, object] = {}
            if filter_column and filter_value is not None:
                where_clause = f'WHERE "{filter_column}" = :filter_value'
                params["filter_value"] = filter_value

            # Scans every matching row, not a capped sample -- a sample can
            # silently miss keys that only show up in rarely-populated
            # fields past the sample window. These tables are small enough
            # (tens to low thousands of rows) that this is cheap; revisit
            # with a real sampling strategy only if a table grows enough
            # for this to become slow.
            count_result = await conn.execute(
                text(f'SELECT COUNT(*) AS n FROM "{table}" {where_clause}'), params
            )
            rows_scanned = count_result.scalar_one()

            if rows_scanned == 0:
                return JsonbKeysResponse(
                    table=table, column=column, filter_column=filter_column,
                    filter_value=filter_value, rows_scanned=0, keys=[],
                )

            key_sql = text(
                f"""
                SELECT kv.key AS key, jsonb_typeof(kv.value) AS value_type, COUNT(*) AS occurrences
                FROM "{table}", jsonb_each("{column}") AS kv(key, value)
                {where_clause}
                GROUP BY kv.key, value_type
                ORDER BY occurrences DESC, kv.key
                """
            )
            key_result = await conn.execute(key_sql, params)

            by_key: dict[str, dict[str, object]] = {}
            for row in key_result:
                entry = by_key.setdefault(row.key, {"types": set(), "occurrences": 0})
                entry["types"].add(row.value_type)
                entry["occurrences"] += row.occurrences

            keys = [
                JsonbKeyOut(
                    key=k,
                    types=sorted(v["types"]),
                    presence_count=v["occurrences"],
                    presence_pct=round(100.0 * v["occurrences"] / rows_scanned, 1),
                )
                for k, v in by_key.items()
            ]
            keys.sort(key=lambda k: (-k.presence_count, k.key))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not reach the database: {exc}") from exc

    return JsonbKeysResponse(
        table=table, column=column, filter_column=filter_column,
        filter_value=filter_value, rows_scanned=rows_scanned, keys=keys,
    )


# ----------------------------------------------------------------------
# POST /admin/tables/custom -- the table builder.
#
# Deliberately NOT a computation/aggregation step -- this is a pure field
# projection: pick which columns (or "column.jsonb_key" discovered
# fields) to carry into a new table, optionally scoped to one
# object_type, nothing more. No GROUP BY, no SUM/AVG/etc. Computed
# metrics belong to a later step (when the table is flattened into
# Silver, or at Gold view time), not here -- confirmed with the user
# 2026-08-06, superseding the first version of this endpoint, which did
# entity+time-bucket aggregation inline. Kept as CREATE TABLE ... AS
# SELECT (not a VIEW) since that's still the simplest thing that lets the
# admin panel show the result as a real, listed table immediately.
#
# dry_run=true returns the generated SQL and preview column list without
# executing anything, for the confirmation/schema-visualization step;
# dry_run=false attempts real execution and falls back to
# status="failed" + the SQL to run manually if it doesn't succeed --
# never a generic 500, since a data-shape failure here is expected
# sometimes, not exceptional.
#
# Every identifier (table names, column names, jsonb key names) is
# resolved and validated against information_schema BEFORE it's
# interpolated into SQL -- jsonb inner keys specifically go through a
# bound parameter (`col ->> :param`), not string interpolation, since
# those are admin-typed strings discovered from live data, not schema
# metadata.
# ----------------------------------------------------------------------

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class FieldSpec(BaseModel):
    field: str  # "column" or "jsonb_column.inner_key"
    output_name: str | None = None


class CustomTableRequest(BaseModel):
    source_table: str
    object_type: str | None = None
    fields: list[FieldSpec] = Field(min_length=1)
    table_name: str
    dry_run: bool = False
    #: When table_name already exists: false (default) -- reject with 409,
    #: same as always. true -- replace it (DROP + CREATE in one
    #: transaction, so a bad new definition rolls back to the untouched
    #: original rather than leaving the table dropped with nothing in its
    #: place). Lets the admin re-run a table's definition to pick up fresh
    #: data after a fetch, not just create brand-new tables.
    overwrite: bool = False


class CustomTableResponse(BaseModel):
    status: Literal["preview", "created", "failed"]
    table_name: str
    sql: str
    preview_columns: list[str]
    row_count: int | None = None
    error: str | None = None


def _build_field_expr(
    field: str,
    columns: dict[str, str],
    params: dict[str, object],
    counter: list[int],
    alias: str | None = None,
) -> str:
    """Returns a SQL expression for `field`. Raises 400 if it doesn't
    resolve to a real column (or a jsonb column, for the "col.key" form)
    on the source table. `alias`, when given, qualifies the column
    reference (e.g. "t0"."col") -- needed once more than one table is in
    play, so an unqualified column name can't be ambiguous."""
    prefix = f"{alias}." if alias else ""
    if "." in field:
        jsonb_col, inner_key = field.split(".", 1)
        if jsonb_col not in columns:
            raise HTTPException(400, f"'{field}': no column '{jsonb_col}' on the source table.")
        if columns[jsonb_col] != "jsonb":
            raise HTTPException(400, f"'{field}': column '{jsonb_col}' is {columns[jsonb_col]}, not jsonb.")
        counter[0] += 1
        pname = f"key_{counter[0]}"
        params[pname] = inner_key
        return f'{prefix}"{jsonb_col}" ->> :{pname}'
    if field not in columns:
        raise HTTPException(400, f"No column '{field}' on the source table.")
    return f'{prefix}"{field}"'


def _safe_output_name(raw: str, fallback: str, seen: set[str]) -> str:
    name = re.sub(r"[^a-z0-9_]", "_", raw.lower()).strip("_") or fallback
    if not re.match(r"^[a-z]", name):
        name = f"f_{name}"
    base, i = name, 1
    while name in seen:
        i += 1
        name = f"{base}_{i}"
    seen.add(name)
    return name


@router.post("/tables/custom", response_model=CustomTableResponse)
async def create_custom_table(body: CustomTableRequest) -> CustomTableResponse:
    if not _IDENTIFIER_RE.match(body.table_name):
        raise HTTPException(
            400,
            "table_name must start with a lowercase letter and contain only lowercase "
            "letters, digits, and underscores (max 63 chars).",
        )

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            columns = await _get_columns(conn, body.source_table)
            if not columns:
                raise HTTPException(404, f"No table named '{body.source_table}'.")

            existing = await _get_columns(conn, body.table_name)
            if existing and not body.overwrite:
                raise HTTPException(409, f"A table named '{body.table_name}' already exists.")
            replacing = bool(existing) and body.overwrite

            params: dict[str, object] = {}
            counter = [0]
            seen_names: set[str] = set()

            select_parts: list[str] = []
            preview_columns: list[str] = []
            for fs in body.fields:
                expr = _build_field_expr(fs.field, columns, params, counter)
                out_name = _safe_output_name(fs.output_name or fs.field.replace(".", "_"), "field", seen_names)
                select_parts.append(f'{expr} AS "{out_name}"')
                preview_columns.append(out_name)

            where_clause = ""
            if body.object_type is not None:
                if "object_type" not in columns:
                    raise HTTPException(400, "source_table has no object_type column to filter on.")
                where_clause = 'WHERE "object_type" = :object_type_filter\n'
                params["object_type_filter"] = body.object_type

            create_sql = (
                f'CREATE TABLE "{body.table_name}" AS\n'
                "SELECT\n  " + ",\n  ".join(select_parts) + "\n"
                f'FROM "{body.source_table}"\n'
                f"{where_clause}".rstrip()
            )
            sql = f'DROP TABLE "{body.table_name}";\n{create_sql}' if replacing else create_sql

            if body.dry_run:
                return CustomTableResponse(
                    status="preview", table_name=body.table_name, sql=sql, preview_columns=preview_columns
                )

            try:
                if replacing:
                    await conn.execute(text(f'DROP TABLE "{body.table_name}"'))
                await conn.execute(text(create_sql), params)
                await conn.commit()
                count_result = await conn.execute(text(f'SELECT COUNT(*) AS n FROM "{body.table_name}"'))
                row_count = count_result.scalar_one()
            except Exception as exc:  # noqa: BLE001 -- expected fallback path, not a server error
                await conn.rollback()
                return CustomTableResponse(
                    status="failed", table_name=body.table_name, sql=sql,
                    preview_columns=preview_columns, error=str(exc)[:1000],
                )

            return CustomTableResponse(
                status="created", table_name=body.table_name, sql=sql,
                preview_columns=preview_columns, row_count=row_count,
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not reach the database: {exc}") from exc


# ----------------------------------------------------------------------
# POST /admin/tables/join -- pick raw metrics from DIFFERENT tables and
# join them into one table. /admin/tables/custom stays single-table/pure
# projection on purpose; this is the deliberately separate multi-table
# sibling, sharing the same field-expression/validation/execute-with-
# fallback machinery rather than complicating that endpoint's contract.
#
# Star join, not a general chain: tables[0] is the anchor, and every
# other table joins directly against the anchor (not against each other,
# and not against a table other than the anchor). Covers the common case
# (one fact-ish table + several others joined to it) without the UI/SQL
# complexity of an arbitrary join graph. The SAME physical table can
# appear more than once (e.g. one Bronze table filtered to two different
# object_types) -- aliases are assigned by position (t0, t1, ...), never
# by table name, specifically to make that safe.
#
# Join keys must be fields the admin already selected in the schema
# browser (same "column" / "column.jsonb_key" syntax as everywhere else
# in this file) -- there's no separate "pick any column as a join key"
# affordance, consistent with the rest of this admin panel only ever
# working from what was explicitly checked.
# ----------------------------------------------------------------------

JoinType = Literal["inner", "left", "right", "full"]
_JOIN_SQL = {"inner": "JOIN", "left": "LEFT JOIN", "right": "RIGHT JOIN", "full": "FULL JOIN"}


class JoinTableSpec(BaseModel):
    table: str
    object_type: str | None = None
    fields: list[FieldSpec] = Field(default_factory=list)
    # Ignored for tables[0] (the anchor) -- required for every other entry.
    join_type: JoinType = "inner"
    join_field: str | None = None  # field on THIS table
    anchor_join_field: str | None = None  # field on tables[0]


class JoinedTableRequest(BaseModel):
    tables: list[JoinTableSpec] = Field(min_length=2)
    table_name: str
    dry_run: bool = False


class JoinedTableResponse(BaseModel):
    status: Literal["preview", "created", "failed"]
    table_name: str
    sql: str
    preview_columns: list[str]
    row_count: int | None = None
    error: str | None = None


@router.post("/tables/join", response_model=JoinedTableResponse)
async def create_joined_table(body: JoinedTableRequest) -> JoinedTableResponse:
    if not _IDENTIFIER_RE.match(body.table_name):
        raise HTTPException(
            400,
            "table_name must start with a lowercase letter and contain only lowercase "
            "letters, digits, and underscores (max 63 chars).",
        )

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            columns_per_spec: list[dict[str, str]] = []
            for ts in body.tables:
                cols = await _get_columns(conn, ts.table)
                if not cols:
                    raise HTTPException(404, f"No table named '{ts.table}'.")
                columns_per_spec.append(cols)

            if not body.dry_run:
                existing = await _get_columns(conn, body.table_name)
                if existing:
                    raise HTTPException(409, f"A table named '{body.table_name}' already exists.")

            params: dict[str, object] = {}
            counter = [0]
            seen_names: set[str] = set()

            select_parts: list[str] = []
            preview_columns: list[str] = []
            from_parts: list[str] = []
            where_parts: list[str] = []

            anchor_alias = "t0"
            anchor_columns = columns_per_spec[0]

            for i, ts in enumerate(body.tables):
                alias = f"t{i}"
                cols = columns_per_spec[i]

                if ts.object_type is not None:
                    if "object_type" not in cols:
                        raise HTTPException(400, f"'{ts.table}' has no object_type column to filter on.")
                    where_parts.append(f'{alias}."object_type" = :obj_type_{i}')
                    params[f"obj_type_{i}"] = ts.object_type

                for fs in ts.fields:
                    expr = _build_field_expr(fs.field, cols, params, counter, alias=alias)
                    default_name = f"{ts.table}_{fs.field}".replace(".", "_")
                    out_name = _safe_output_name(fs.output_name or default_name, "field", seen_names)
                    select_parts.append(f'{expr} AS "{out_name}"')
                    preview_columns.append(out_name)

                if i == 0:
                    from_parts.append(f'"{ts.table}" AS {alias}')
                else:
                    if not ts.join_field or not ts.anchor_join_field:
                        raise HTTPException(
                            400, f"'{ts.table}' (position {i}) needs both join_field and anchor_join_field."
                        )
                    left_expr = _build_field_expr(
                        ts.anchor_join_field, anchor_columns, params, counter, alias=anchor_alias
                    )
                    right_expr = _build_field_expr(ts.join_field, cols, params, counter, alias=alias)
                    join_kw = _JOIN_SQL[ts.join_type]
                    from_parts.append(f'{join_kw} "{ts.table}" AS {alias} ON {left_expr} = {right_expr}')

            if not select_parts:
                raise HTTPException(400, "At least one table needs at least one selected field.")

            where_sql = f"WHERE {' AND '.join(where_parts)}\n" if where_parts else ""
            sql = (
                f'CREATE TABLE "{body.table_name}" AS\n'
                "SELECT\n  " + ",\n  ".join(select_parts) + "\n"
                "FROM " + "\n".join(from_parts) + "\n"
                f"{where_sql}".rstrip()
            )

            if body.dry_run:
                return JoinedTableResponse(
                    status="preview", table_name=body.table_name, sql=sql, preview_columns=preview_columns
                )

            try:
                await conn.execute(text(sql), params)
                await conn.commit()
                count_result = await conn.execute(text(f'SELECT COUNT(*) AS n FROM "{body.table_name}"'))
                row_count = count_result.scalar_one()
            except Exception as exc:  # noqa: BLE001 -- expected fallback path, not a server error
                await conn.rollback()
                return JoinedTableResponse(
                    status="failed", table_name=body.table_name, sql=sql,
                    preview_columns=preview_columns, error=str(exc)[:1000],
                )

            return JoinedTableResponse(
                status="created", table_name=body.table_name, sql=sql,
                preview_columns=preview_columns, row_count=row_count,
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not reach the database: {exc}") from exc


# ----------------------------------------------------------------------
# GET /admin/tables/{table}/columns
# POST /admin/tables/{table}/custom-metric
#
# This is the deferred "computed metric" step flagged when /admin/tables/
# custom got simplified to a pure projection: it operates on a table that
# ALREADY EXISTS (built by /build, or anything else), adding a formula
# column to it directly -- modeled on Meta Ads Manager's own "Customise
# columns -> Create custom metric" panel (ratio/product/sum/difference of
# two existing columns, or a column and a constant, with an optional
# "show as percentage" x100). Implemented as ALTER TABLE ADD COLUMN +
# UPDATE ... SET in one transaction (both roll back together if the
# UPDATE fails, so a bad formula never leaves an orphaned empty column).
#
# dry_run=true returns the generated SQL without touching the table,
# matching the same preview-then-confirm pattern as /admin/tables/custom.
# ----------------------------------------------------------------------

Operation = Literal["divide", "multiply", "add", "subtract"]
OperandBType = Literal["column", "constant"]


class CustomMetricRequest(BaseModel):
    name: str
    operation: Operation
    column_a: str
    operand_b_type: OperandBType
    operand_b_column: str | None = None
    operand_b_constant: float | None = None
    as_percentage: bool = False
    dry_run: bool = False


class CustomMetricResponse(BaseModel):
    status: Literal["preview", "created", "failed"]
    table: str
    column_name: str
    sql: str
    error: str | None = None


_OP_SQL = {"divide": "/", "multiply": "*", "add": "+", "subtract": "-"}


@router.get("/tables/{table}/columns", response_model=list[ColumnOut])
async def get_table_columns(table: str) -> list[ColumnOut]:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :table ORDER BY ordinal_position"
                ),
                {"table": table},
            )
            rows = list(result)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not reach the database: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=404, detail=f"No table named '{table}'.")
    return [
        ColumnOut(
            name=r.column_name, data_type=r.data_type, is_nullable=r.is_nullable == "YES",
            kind=_classify_column(r.column_name, r.data_type),
        )
        for r in rows
    ]


@router.post("/tables/{table}/custom-metric", response_model=CustomMetricResponse)
async def create_custom_metric(table: str, body: CustomMetricRequest) -> CustomMetricResponse:
    column_name = re.sub(r"[^a-z0-9_]", "_", body.name.lower()).strip("_")
    if not _IDENTIFIER_RE.match(column_name):
        raise HTTPException(
            400,
            "metric name must reduce to a valid column name: start with a lowercase letter, "
            "letters/digits/underscores only.",
        )
    if body.operand_b_type == "column" and not body.operand_b_column:
        raise HTTPException(400, "operand_b_column is required when operand_b_type is 'column'.")
    if body.operand_b_type == "constant" and body.operand_b_constant is None:
        raise HTTPException(400, "operand_b_constant is required when operand_b_type is 'constant'.")

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            columns = await _get_columns(conn, table)
            if not columns:
                raise HTTPException(404, f"No table named '{table}'.")
            if column_name in columns:
                raise HTTPException(409, f"Column '{column_name}' already exists on '{table}'.")
            if body.column_a not in columns:
                raise HTTPException(400, f"No column '{body.column_a}' on '{table}'.")

            params: dict[str, object] = {}
            expr_a = f'"{body.column_a}"::numeric'
            if body.operand_b_type == "column":
                if body.operand_b_column not in columns:
                    raise HTTPException(400, f"No column '{body.operand_b_column}' on '{table}'.")
                expr_b = f'"{body.operand_b_column}"::numeric'
            else:
                params["operand_b"] = body.operand_b_constant
                # CAST(...), not ":operand_b::numeric" -- a bind param
                # immediately followed by a `::` cast doesn't parse
                # cleanly through SQLAlchemy's param substitution
                # (confirmed live: Postgres saw a literal ":operand_b" and
                # raised a syntax error at ":").
                expr_b = "CAST(:operand_b AS NUMERIC)"

            if body.operation == "divide":
                formula = f"({expr_a} / NULLIF({expr_b}, 0))"
                if body.as_percentage:
                    formula = f"{formula} * 100"
            else:
                formula = f"({expr_a} {_OP_SQL[body.operation]} {expr_b})"

            alter_sql = f'ALTER TABLE "{table}" ADD COLUMN "{column_name}" NUMERIC'
            update_sql = f'UPDATE "{table}" SET "{column_name}" = {formula}'
            sql = f"{alter_sql};\n{update_sql};"

            if body.dry_run:
                return CustomMetricResponse(status="preview", table=table, column_name=column_name, sql=sql)

            try:
                await conn.execute(text(alter_sql))
                await conn.execute(text(update_sql), params)
                await conn.commit()
            except Exception as exc:  # noqa: BLE001 -- expected fallback path, not a server error
                await conn.rollback()
                return CustomMetricResponse(
                    status="failed", table=table, column_name=column_name, sql=sql, error=str(exc)[:1000]
                )

            return CustomMetricResponse(status="created", table=table, column_name=column_name, sql=sql)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not reach the database: {exc}") from exc


# ----------------------------------------------------------------------
# POST /admin/tables/raw + GET /admin/tables/raw
#
# A "raw table" is an empty table with the shared Bronze envelope schema
# (id/source_id/raw_payload/api_endpoint/api_version/batch_id/
# request_params/extracted_at/ingested_at/sync_type/payload_hash/
# processing_status/object_type/parent_ids/is_nested -- identical across
# raw_dump_instagram.sql and raw_dump_shopify.sql) plus the partial unique
# index the upsert-based ingest scripts need. Lets an admin create a
# fresh, empty target table from the Fetch Trigger page, then fetch real
# data into it -- distinct from /admin/tables/custom, which projects
# fields OUT of already-fetched data into a new derived table.
#
# No overwrite option here on purpose, unlike /admin/tables/custom --
# this table holds primary source data, not a rebuildable projection, so
# silently replacing one would be destructive in a way that endpoint's
# `overwrite` flag isn't. A name collision always 409s; pick a new name
# or use the existing table via the "select existing" path instead.
# ----------------------------------------------------------------------

RawTableSource = Literal["instagram", "shopify", "meta"]

#: Every raw-envelope table shares the same shape EXCEPT its id column --
#: Instagram/Shopify use source_id (raw_dump_instagram.sql/raw_dump_shopify.sql),
#: Meta uses meta_id (BronzeMixin, app/models/base.py) since RawDumpMeta
#: predates this generic endpoint. Parameterizing on this one column name
#: covers all three without a separate DDL template per source.
_ID_COLUMN_BY_SOURCE: dict[RawTableSource, str] = {
    "instagram": "source_id", "shopify": "source_id", "meta": "meta_id",
}


def _raw_table_indexes(table: str, id_column: str, *, unique_per_entity: bool) -> list[str]:
    indexes = [
        f'CREATE INDEX "ix_{table}_{id_column}" ON "{table}" ({id_column})',
        f'CREATE INDEX "ix_{table}_batch_id" ON "{table}" (batch_id)',
        f'CREATE INDEX "ix_{table}_payload_hash" ON "{table}" (payload_hash)',
        f'CREATE INDEX "ix_{table}_object_type" ON "{table}" (object_type)',
        f'CREATE INDEX "ix_{table}_raw_payload_gin" ON "{table}" USING GIN (raw_payload)',
    ]
    if unique_per_entity:
        indexes.append(
            f'CREATE UNIQUE INDEX "ux_{table}_object_type_{id_column}" ON "{table}" '
            f"(object_type, {id_column}) WHERE {id_column} IS NOT NULL"
        )
    return indexes


class RawTableRequest(BaseModel):
    table_name: str
    source: RawTableSource = "instagram"


class RawTableResponse(BaseModel):
    status: Literal["created", "failed"]
    table_name: str
    error: str | None = None


@router.post("/tables/raw", response_model=RawTableResponse)
async def create_raw_table(body: RawTableRequest) -> RawTableResponse:
    if not _IDENTIFIER_RE.match(body.table_name):
        raise HTTPException(
            400,
            "table_name must start with a lowercase letter and contain only lowercase "
            "letters, digits, and underscores (max 63 chars).",
        )

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            existing = await _get_columns(conn, body.table_name)
            if existing:
                raise HTTPException(409, f"A table named '{body.table_name}' already exists.")

            table = body.table_name
            id_column = _ID_COLUMN_BY_SOURCE[body.source]
            try:
                await conn.execute(
                    text(
                        f'CREATE TABLE "{table}" ('
                        f"id UUID PRIMARY KEY, {id_column} VARCHAR(64), raw_payload JSONB NOT NULL, "
                        "api_endpoint VARCHAR(255) NOT NULL, api_version VARCHAR(16) NOT NULL, "
                        "batch_id UUID NOT NULL, request_params JSONB, "
                        "extracted_at TIMESTAMPTZ NOT NULL, ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                        "sync_type VARCHAR(32) NOT NULL, payload_hash VARCHAR(64) NOT NULL, "
                        "processing_status VARCHAR(16) NOT NULL, object_type VARCHAR(64) NOT NULL, "
                        "parent_ids JSONB, is_nested BOOLEAN NOT NULL DEFAULT false)"
                    )
                )
                # Meta ingestion (both entities and Insights) always appends --
                # the same entity legitimately gets re-fetched into multiple Bronze
                # rows across syncs, deduped later in Silver (see
                # app/services/meta/entity_flatten.py's DISTINCT ON ... ORDER BY
                # extracted_at DESC) -- matching raw_dump_meta's own schema, which
                # has no such constraint. Instagram/Shopify's ingest scripts
                # genuinely upsert (ON CONFLICT DO UPDATE), so they need it.
                # Confirmed live 2026-08-21: a Meta target table WITH this
                # constraint hard-crashed a legitimate re-fetch with a
                # UniqueViolation.
                for index_sql in _raw_table_indexes(table, id_column, unique_per_entity=body.source != "meta"):
                    await conn.execute(text(index_sql))
                await conn.commit()
            except Exception as exc:  # noqa: BLE001 -- expected fallback path, not a server error
                await conn.rollback()
                return RawTableResponse(status="failed", table_name=table, error=str(exc)[:1000])

            return RawTableResponse(status="created", table_name=table)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not reach the database: {exc}") from exc


class RawTableOut(BaseModel):
    name: str
    row_count: int
    last_updated: datetime | None


@router.get("/tables/raw", response_model=list[RawTableOut])
async def list_raw_tables(source: RawTableSource = "instagram") -> list[RawTableOut]:
    """Tables with the raw Bronze envelope shape for the given source
    (checked by column names, not by name pattern) -- these are the
    tables an admin can pick to "update" an existing fetch, as opposed to
    creating a new one. last_updated is MAX(ingested_at) -- informational
    ("when was this table last touched"), not the actual resume-date
    computation used when fetching (see _meta_last_covered_date for Meta,
    which uses the insights data's own date_stop instead)."""
    id_column = _ID_COLUMN_BY_SOURCE[source]
    required_columns = {
        "id", id_column, "raw_payload", "object_type", "parent_ids",
        "extracted_at", "ingested_at", "batch_id",
    }
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            columns_result = await conn.execute(_COLUMNS_SQL)
            by_table: dict[str, set[str]] = {}
            for row in columns_result:
                by_table.setdefault(row.table_name, set()).add(row.column_name)

            raw_tables = [name for name, cols in by_table.items() if required_columns.issubset(cols)]
            if not raw_tables:
                return []

            out: list[RawTableOut] = []
            for name in sorted(raw_tables):
                stats = await conn.execute(
                    text(f'SELECT COUNT(*) AS n, MAX(ingested_at) AS last_updated FROM "{name}"')
                )
                row = stats.one()
                out.append(RawTableOut(name=name, row_count=row.n, last_updated=row.last_updated))
            return out
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not reach the database: {exc}") from exc


async def _meta_level_breakdown(
    conn, table: str, batch_id: uuid.UUID, account_key: str, account_name: str
) -> list["LevelStatus"]:
    """Reconstructs per-level pass/fail for one account's batch after the
    fact, rather than threading a live callback through
    InsightsSyncService/SyncOrchestrator/MultiAccountSyncCoordinator (a
    much larger, riskier change to code the daily/hourly scheduler
    depends on). Succeeded levels: any level that has rows in target_table
    for this batch_id (per-level fault isolation, see insights.py's
    sync(), means a batch can have some levels succeed and others fail).
    Failed levels: failed_jobs rows for this batch_id, whose
    request_params carries the level that failed (see
    _build_request_params in insights.py)."""
    succeeded = await conn.execute(
        text(f"SELECT DISTINCT parent_ids ->> 'level' AS level FROM \"{table}\" WHERE batch_id = :batch_id"),
        {"batch_id": batch_id},
    )
    failed = await conn.execute(
        text(
            "SELECT request_params ->> 'level' AS level, error_message "
            "FROM failed_jobs WHERE batch_id = :batch_id"
        ),
        {"batch_id": batch_id},
    )
    out = [
        LevelStatus(account_key=account_key, account_name=account_name, label=row.level, status="succeeded")
        for row in succeeded
        if row.level
    ]
    out += [
        LevelStatus(
            account_key=account_key, account_name=account_name, label=row.level,
            status="failed", error=row.error_message,
        )
        for row in failed
        if row.level
    ]
    return out


async def _meta_last_covered_date(conn, table: str) -> date | None:
    """The latest Insights date actually covered by an existing Meta raw
    table -- the semantically correct "resume from here" signal for a
    date-range-based service (unlike ingested_at, which only says when a
    row was physically written, not what performance date it covers)."""
    result = await conn.execute(
        text(f"SELECT MAX((raw_payload ->> 'date_stop')::date) AS d FROM \"{table}\" WHERE object_type = 'insights'")
    )
    return result.scalar_one_or_none()


# ----------------------------------------------------------------------
# POST /admin/ingest + GET /admin/ingest/{run_id}
# ----------------------------------------------------------------------

IngestSource = Literal["meta", "shopify", "instagram"]


class IngestRequest(BaseModel):
    sources: list[IngestSource] = Field(min_length=1)
    #: Meta: optional -- omit date_start to auto-resume from target_table's
    #: last covered insights date (+1 day), or provide it to fetch/backfill
    #: from an explicit start; required (no auto-discovery) when target_table
    #: is a brand-new/empty table. date_end defaults to today if omitted.
    #: Ignored for instagram, which uses `since` below instead.
    date_start: date | None = None
    date_end: date | None = None
    #: Required for both "meta" and "instagram" -- which raw table to fetch
    #: into (create it first via POST /admin/tables/raw, or pick one from
    #: GET /admin/tables/raw). None only when neither source is present.
    target_table: str | None = None
    #: Instagram only, optional. When set, fetching starts from this date
    #: for every account instead of auto-discovering the true oldest post
    #: (new table) or auto-resuming from the table's own last-updated
    #: point (existing table) -- an explicit override of both.
    since: date | None = None
    #: Meta only, optional. Which Insights levels to fetch -- omit for all
    #: four (account/campaign/adset/ad, existing default behavior).
    #: Regardless of the order given here, execution always follows
    #: META_LEVEL_FETCH_ORDER (ad -> adset -> campaign -> account) -- an
    #: explicit user policy ("this should be the flow of fetching meta ads
    #: related data", 2026-08-24), not a per-request choice.
    meta_levels: list[Literal["account", "campaign", "adset", "ad"]] | None = None


class IngestSourceResult(BaseModel):
    source: IngestSource
    status: Literal["started", "skipped", "error"]
    supports_date_range: bool
    detail: str


class IngestRunResponse(BaseModel):
    run_id: str
    started_at: datetime
    results: list[IngestSourceResult]


class LevelStatus(BaseModel):
    """Per-(account, fetch unit) breakdown shown under the progress bar --
    "fetch unit" is a Meta insights level (account/campaign/adset/ad) or
    an Instagram edge (media/collaborative_media/collaboration_invites),
    whichever the source uses as its actual unit of failure. Keyed by
    (account_key, label) so a re-attempt overwrites its own prior entry
    rather than appending duplicates."""

    account_key: str | None = None
    account_name: str | None = None
    label: str
    status: Literal["succeeded", "failed"]
    error: str | None = None


class SourceStatus(BaseModel):
    status: Literal["running", "succeeded", "failed", "skipped", "stopped"]
    rows_ingested: int | None = None
    error: str | None = None
    levels: list[LevelStatus] = Field(default_factory=list)


class IngestRunStatus(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None
    sources: dict[IngestSource, SourceStatus]


# Module-level, in-process only -- see module docstring.
_RUNS: dict[str, IngestRunStatus] = {}
#: Task handles for cancellable (stoppable) runs -- Meta and Instagram are
#: both started via asyncio.create_task() (see trigger_ingest below)
#: rather than BackgroundTasks, specifically so a stop endpoint has a
#: handle to call .cancel() on.
_TASKS: dict[str, asyncio.Task[None]] = {}

_NOT_YET_DYNAMIC = (
    "scripts/ingest_{script}.py doesn't filter by date yet -- add --since/--until there and "
    "wire it into this route as a subprocess call before enabling this source here."
)


def _all_finished(run: IngestRunStatus) -> bool:
    return all(s.status in ("succeeded", "failed", "skipped", "stopped") for s in run.sources.values())


#: Fixed execution order for the Fetch UI's Meta level selection --
#: explicit user policy, not a per-request choice ("the fetching should
#: include all the ads data, followed by adset data and then campaign
#: level data -- this should be the flow of fetching meta ads related
#: data", 2026-08-24). Account level (not part of that stated flow) sorts
#: last if selected at all. Whatever subset the UI's checkboxes send comes
#: back through this order, regardless of the order they arrive in.
META_LEVEL_FETCH_ORDER: list[InsightsLevel] = [
    InsightsLevel.AD,
    InsightsLevel.ADSET,
    InsightsLevel.CAMPAIGN,
    InsightsLevel.ACCOUNT,
]


async def _run_meta(
    run_id: str,
    coordinator: CoordinatorDep,
    target_table: str,
    date_start: date | None,
    date_end: date | None,
    meta_levels: list[str] | None = None,
) -> None:
    """target_table is always passed to coordinator.sync_insights() now --
    threads through to InsightsSyncService's dynamic model resolution (see
    app/services/meta/insights.py's _resolve_model). date_start omitted
    means "auto-resume": computed from target_table's own last covered
    insights date (+1 day) via _meta_last_covered_date -- fails clearly if
    the table has no existing insights data and no date_start was given,
    rather than silently defaulting to something arbitrary. Cancellable
    (started via asyncio.create_task(), see trigger_ingest) same as
    _run_instagram.

    meta_levels: None means "every level, existing default behavior"
    (passed straight through as levels=None, which InsightsSyncService.sync()
    itself defaults to list(InsightsLevel)). A given subset is always
    reordered to META_LEVEL_FETCH_ORDER before being sent -- the level
    loop inside sync() runs levels in the order given, so this is what
    actually produces the ad -> adset -> campaign -> account sequencing,
    not just a display convention."""
    run = _RUNS[run_id]
    try:
        resolved_start = date_start
        if resolved_start is None:
            engine = get_engine()
            async with engine.connect() as conn:
                last_covered = await _meta_last_covered_date(conn, target_table)
            if last_covered is None:
                raise RuntimeError(
                    f"'{target_table}' has no existing insights data to resume from -- "
                    "provide a start date."
                )
            resolved_start = last_covered + timedelta(days=1)
        resolved_end = date_end or datetime.now(timezone.utc).date()

        resolved_levels = (
            [lvl for lvl in META_LEVEL_FETCH_ORDER if lvl.value in meta_levels] if meta_levels else None
        )

        results = await coordinator.sync_insights(
            date_range=(resolved_start, resolved_end),
            sync_type="manual",
            triggered_by="admin_panel",
            target_table=target_table,
            levels=resolved_levels,
        )
        total_fetched = sum(r.batch.records_fetched for r in results)
        total_failed = sum(r.batch.records_failed for r in results)

        levels: list[LevelStatus] = []
        engine = get_engine()
        async with engine.connect() as conn:
            for r in results:
                levels += await _meta_level_breakdown(conn, target_table, r.batch.id, r.account_key, r.account_name)

        run.sources["meta"] = SourceStatus(
            status="failed" if total_failed and not total_fetched else "succeeded",
            rows_ingested=total_fetched,
            error=(f"{total_failed} records failed across {len(results)} account(s)" if total_failed else None),
            levels=levels,
        )
    except asyncio.CancelledError:
        run.sources["meta"] = SourceStatus(status="stopped", rows_ingested=None, error="Stopped by user.")
    except Exception as exc:  # noqa: BLE001 -- reported to the admin panel, not raised into a background task void
        run.sources["meta"] = SourceStatus(status="failed", rows_ingested=None, error=str(exc)[:500])
    finally:
        if _all_finished(run):
            run.finished_at = datetime.now(timezone.utc)
        _TASKS.pop(run_id, None)


async def _run_instagram(run_id: str, target_table: str, since_override: date | None) -> None:
    """Awaits ingest_instagram_chronological.py's already-async _run() core
    directly (no subprocess) -- see the module-level import comment for
    why importing across the scripts/->app/ boundary is the accepted
    exception here. use_checkpoint_file=False makes this resume from
    target_table's own data (via _resume_state_from_db) rather than the
    account-only-keyed JSON checkpoint file the CLI script otherwise
    trusts -- correct regardless of which table is targeted.

    Started via asyncio.create_task() (not BackgroundTasks) specifically
    so POST /admin/ingest/{run_id}/stop has a Task to call .cancel() on --
    cancellation raises asyncio.CancelledError at whatever await point
    _run() is currently at (an HTTP call or a sleep), which propagates up
    through here; caught below and reported as a clean "stopped" status
    rather than a crash, same partial-progress numbers preserved."""
    run = _RUNS[run_id]
    stats = {"items_so_far": 0, "inserted_so_far": 0}
    levels: dict[tuple[str, str], LevelStatus] = {}

    def on_progress(info: dict[str, Any]) -> None:
        # Failure calls only carry account/edge/status/error -- no
        # items_so_far/inserted_so_far, since nothing new was fetched.
        if "items_so_far" in info:
            stats.update(items_so_far=info["items_so_far"], inserted_so_far=info["inserted_so_far"])
        levels[(info["account"], info["edge"])] = LevelStatus(
            account_key=info["account"], label=info["edge"],
            status=info["status"], error=info.get("error"),
        )
        run.sources["instagram"] = SourceStatus(
            status="running", rows_ingested=stats["items_so_far"], levels=list(levels.values())
        )

    try:
        # discover_ig_accounts()/os.environ.get() below read raw process env
        # vars (IG_USER_ID_N/IG_USERNAME_N/META_ACCESS_TOKEN), same as the
        # script's own main() -- but main() isn't in this call path (see
        # the module-level import comment), so .env needs loading here too.
        # pydantic-settings reads .env internally per-Settings-instance
        # without necessarily populating os.environ process-wide, which is
        # why this was needed (confirmed live: omitting it 404s on "No
        # Instagram accounts configured").
        from dotenv import load_dotenv

        load_dotenv(_SCRIPTS_DIR.parent / ".env")

        accounts_by_key = ig_chronological.discover_ig_accounts()
        if not accounts_by_key:
            raise RuntimeError("No Instagram accounts configured -- set IG_USER_ID_1/IG_USERNAME_1 in .env.")
        accounts = [accounts_by_key[k] for k in sorted(accounts_by_key, key=int)]

        access_token = os.environ.get("META_ACCESS_TOKEN")
        if not access_token:
            raise RuntimeError("META_ACCESS_TOKEN is not set in .env.")
        api_version = os.environ.get("META_API_VERSION", ig_chronological.DEFAULT_API_VERSION)
        base_url = f"https://graph.facebook.com/{api_version}"
        database_url = os.environ.get("DATABASE_URL")

        args = argparse.Namespace(
            table=target_table, window_days=30, max_windows=None,
            discover_only=False, no_insert=False, refresh_existing=False, include_insights=False,
        )
        since_dt = datetime.combine(since_override, time.min, tzinfo=timezone.utc) if since_override else None
        exit_code = await ig_chronological._run(
            args, accounts, base_url, access_token, database_url,
            use_checkpoint_file=False, on_progress=on_progress, since_override=since_dt,
        )
        run.sources["instagram"] = SourceStatus(
            status="failed" if exit_code != 0 else "succeeded",
            rows_ingested=stats["items_so_far"],
            error=(
                "One or more accounts/edges failed -- see logs/instagram_ingest_errors.log"
                if exit_code != 0 else None
            ),
            levels=list(levels.values()),
        )
    except asyncio.CancelledError:
        run.sources["instagram"] = SourceStatus(
            status="stopped", rows_ingested=stats["items_so_far"] or None, error="Stopped by user.",
            levels=list(levels.values()),
        )
    except Exception as exc:  # noqa: BLE001 -- reported to the admin panel, not raised into a background task void
        run.sources["instagram"] = SourceStatus(
            status="failed", rows_ingested=stats["items_so_far"] or None, error=str(exc)[:500],
            levels=list(levels.values()),
        )
    finally:
        if _all_finished(run):
            run.finished_at = datetime.now(timezone.utc)
        _TASKS.pop(run_id, None)


@router.post("/ingest", response_model=IngestRunResponse)
async def trigger_ingest(body: IngestRequest, coordinator: CoordinatorDep) -> IngestRunResponse:
    if "meta" in body.sources and not body.target_table:
        raise HTTPException(400, "target_table is required when 'meta' is in sources.")
    if "instagram" in body.sources and not body.target_table:
        raise HTTPException(400, "target_table is required when 'instagram' is in sources.")

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    results: list[IngestSourceResult] = []
    # Registered in _RUNS before any task is created, not after the loop --
    # asyncio.create_task() below schedules _run_instagram to start as
    # soon as this coroutine next yields, and its very first line does
    # `run = _RUNS[run_id]`; registering late would race it.
    run = IngestRunStatus(run_id=run_id, started_at=started_at, finished_at=None, sources={})
    _RUNS[run_id] = run

    for source in body.sources:
        if source == "meta":
            assert body.target_table is not None  # validated above
            results.append(
                IngestSourceResult(
                    source="meta",
                    status="started",
                    supports_date_range=True,
                    detail=(
                        (
                            f"Fetching {', '.join(lvl.value for lvl in META_LEVEL_FETCH_ORDER if lvl.value in body.meta_levels)}"
                            if body.meta_levels
                            else "Fetching all 4 levels"
                        )
                        + f" into '{body.target_table}'"
                        + (f" from {body.date_start}" if body.date_start else ", resuming from its own last-covered date")
                        + "."
                    ),
                )
            )
            run.sources["meta"] = SourceStatus(status="running")
            _TASKS[run_id] = asyncio.create_task(
                _run_meta(
                    run_id, coordinator, body.target_table, body.date_start, body.date_end, body.meta_levels
                )
            )
        elif source == "instagram":
            assert body.target_table is not None  # validated above
            results.append(
                IngestSourceResult(
                    source="instagram",
                    status="started",
                    supports_date_range=False,
                    detail=(
                        f"Fetching into '{body.target_table}'"
                        + (f" from {body.since}" if body.since else ", resuming from its own last-updated point")
                        + "."
                    ),
                )
            )
            run.sources["instagram"] = SourceStatus(status="running")
            _TASKS[run_id] = asyncio.create_task(_run_instagram(run_id, body.target_table, body.since))
        else:
            results.append(
                IngestSourceResult(
                    source=source,
                    status="skipped",
                    supports_date_range=False,
                    detail=_NOT_YET_DYNAMIC.format(script="shopify"),
                )
            )
            run.sources[source] = SourceStatus(status="skipped")

    if _all_finished(run):
        run.finished_at = datetime.now(timezone.utc)
    return IngestRunResponse(run_id=run_id, started_at=started_at, results=results)


@router.get("/ingest/{run_id}", response_model=IngestRunStatus)
async def get_ingest_status(run_id: str) -> IngestRunStatus:
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id '{run_id}'.")
    return run


@router.post("/ingest/{run_id}/stop", response_model=IngestRunStatus)
async def stop_ingest(run_id: str) -> IngestRunStatus:
    """Only cancels sources started via asyncio.create_task() (currently
    just Instagram -- see _TASKS' docstring). No-op, not an error, for a
    run with no cancellable task (e.g. Meta-only, or already finished) --
    the caller just gets the run's current state back either way."""
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id '{run_id}'.")
    task = _TASKS.get(run_id)
    if task and not task.done():
        task.cancel()
    return run
