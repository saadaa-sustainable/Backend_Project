"""Trial run: fetch the last N days (default 15) of Meta ad-level daily
Insights across every configured account, concurrently, and write it into
the real ``raw_dump_meta`` Bronze table in Postgres.

Insights-only by default — campaigns/ad sets/ads are current-state object
rosters, not time-windowed data, so they don't belong in a "last 15 days"
fetch; pass ``--include-roster`` to fetch them too (matching what a real
full sync would cover), at the cost of spending a chunk of the shared
per-app rate-limit budget on non-time-boxed data before Insights even
starts (confirmed live: this pushed the very first trial run of this
script into Meta's app-level rate limiter).

This is a standalone, Python-3.9-compatible stand-in for the full FastAPI
service's ingestion path (which needs Python 3.12+ and isn't runnable in
this environment): it reimplements just enough of ``MetaAPIClient``
(cursor pagination, retry on both HTTP 429/5xx *and* Meta's in-body
rate-limit error codes) and the Bronze row shape
(``app/models/raw_dump.py`` / the Alembic migration) to prove the pipeline
works end-to-end against your actual Supabase database, and to report real
timing.

Schema: creates ``sync_batches`` / ``failed_jobs`` / ``raw_dump_meta`` if
they don't already exist yet, using ``CREATE TABLE IF NOT EXISTS`` with the
exact DDL from ``alembic/versions/0001_initial_bronze_schema.py``. Never
drops or alters anything. The DDL is printed before it runs.

Reads ``META_ACCESS_TOKEN`` / ``META_ACCOUNT_*`` and
``DATABASE_URL_SYNC``/``DATABASE_URL`` from ``.env`` at runtime — the
access token and the DB connection string (which embeds a password) are
never printed. Only the DB host/database name (not credentials) and the
Meta account names/ids (not the token) are shown, for confirmation.
``DATABASE_URL_SYNC``/``DATABASE_URL`` must be a real Postgres connection
string (e.g. from Supabase's Project Settings -> Database -> Connection
string) — a Supabase *project URL* (``https://xxx.supabase.co``) is a
different thing and will not work here.

Usage:
    python3 scripts/ingest_last_15_days.py                 # all accounts, 15 days, writes to Postgres
    python3 scripts/ingest_last_15_days.py --days 7          # a different window
    python3 scripts/ingest_last_15_days.py --account 2        # just one account
    python3 scripts/ingest_last_15_days.py --no-insert         # fetch + time only, skip DB writes
    python3 scripts/ingest_last_15_days.py --include-roster     # also fetch campaigns/adsets/ads
    python3 scripts/ingest_last_15_days.py --time-increment all_days  # one row per ad for the whole window
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Missing dependency: pip install psycopg2-binary", file=sys.stderr)
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


# ----------------------------------------------------------------------
# Field sets — mirror app/core/meta_registry.py's defaults, trimmed for a
# manageable trial-run payload (not the full 141-metric Insights registry).
# ----------------------------------------------------------------------

CAMPAIGN_FIELDS = [
    "id", "account_id", "name", "objective", "status", "effective_status",
    "buying_type", "daily_budget", "lifetime_budget", "bid_strategy",
    "start_time", "stop_time", "created_time", "updated_time",
]
ADSET_FIELDS = [
    "id", "account_id", "campaign_id", "name", "status", "effective_status",
    "billing_event", "optimization_goal", "daily_budget", "lifetime_budget",
    "start_time", "end_time", "created_time", "updated_time",
]
AD_FIELDS = [
    "id", "account_id", "campaign_id", "adset_id", "name", "status",
    "effective_status", "created_time", "updated_time",
]
INSIGHTS_FIELDS = [
    "ad_id", "ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name",
    "account_id", "date_start", "date_stop", "spend", "impressions", "reach",
    "frequency", "clicks", "unique_clicks", "ctr", "cpc", "cpm", "actions",
    "action_values", "conversions", "purchase_roas",
]

# Mirrors the exact default `effective_status` filters used by
# app/services/meta/{campaigns,adsets,ads}.py, for 1:1 parity with what a
# real sync would fetch. "DELETED" is deliberately excluded — confirmed
# live that Meta now rejects it outright ("Cannot Request for Deleted
# Objects", error code 100 / subcode 1815001) rather than silently
# ignoring it, which fails the whole request. Found and fixed in both
# places by this same trial run.
CAMPAIGN_STATUSES = ["ACTIVE", "PAUSED", "ARCHIVED", "IN_PROCESS", "WITH_ISSUES"]
ADSET_STATUSES = CAMPAIGN_STATUSES + ["CAMPAIGN_PAUSED"]
AD_STATUSES = ADSET_STATUSES + ["ADSET_PAUSED"]

_ACCOUNT_ID_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_ID$")
_ACCOUNT_NAME_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_NAME$")
PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 4
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


# ----------------------------------------------------------------------
# Config discovery (same pattern as the other scripts/ dry-run tools)
# ----------------------------------------------------------------------


@dataclass
class AccountConfig:
    key: str
    name: str
    account_id: str


def _discover_accounts() -> dict[str, AccountConfig]:
    raw: dict[str, dict[str, str]] = {}
    for key, value in os.environ.items():
        if not value:
            continue
        if m := _ACCOUNT_ID_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["id"] = value.removeprefix("act_")
        elif m := _ACCOUNT_NAME_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["name"] = value
    return {
        k: AccountConfig(key=k, name=f.get("name", f"account_{k}"), account_id=f["id"])
        for k, f in raw.items()
        if "id" in f
    }


def _to_psycopg2_dsn(url: str) -> str:
    """Strip SQLAlchemy dialect suffixes (+psycopg2 / +asyncpg) psycopg2
    itself doesn't understand, and force sslmode=require if not already
    set (Supabase's direct Postgres endpoint requires TLS)."""
    for prefix in (
        "postgresql+psycopg2://", "postgresql+asyncpg://",
        "postgres+psycopg2://", "postgres+asyncpg://",
    ):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    else:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.setdefault("sslmode", "require")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _describe_dsn_safely(dsn: str) -> str:
    """Host + database name only — never credentials — for confirmation
    output."""
    parts = urlsplit(dsn)
    host = parts.hostname or "?"
    port = parts.port or "?"
    dbname = parts.path.lstrip("/") or "?"
    return f"{host}:{port}/{dbname}"


# ----------------------------------------------------------------------
# Minimal async Meta client: pagination + basic retry (a trimmed-down
# stand-in for app/services/meta/client.py's MetaAPIClient).
# ----------------------------------------------------------------------


#: Meta rate-limit signals that arrive as HTTP 400/403 with a JSON error
#: body, NOT as HTTP 429 — checking status_code alone (as this script's
#: first draft did) misses these entirely and treats them as hard
#: failures. Trimmed from app/services/meta/client.py's
#: RATE_LIMIT_ERROR_CODES/PLATFORM_RATE_LIMIT_ERROR_CODES /
#: BUC_RATE_LIMIT_ERROR_CODES (see that module for the full, sourced list
#: and the Business Use Case rate-limiting reference).
RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613, 80000, 80001, 80002, 80003, 80004, 80005, 80006, 80008, 80009, 80014}


def _usage_estimated_wait_seconds(headers: httpx.Headers) -> float | None:
    """Pull `estimated_time_to_regain_access` (minutes) out of
    X-Business-Use-Case-Usage if present, converted to seconds — Meta's
    own recommended value for backoff timing when actually throttled."""
    raw = headers.get("x-business-use-case-usage")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    best: float | None = None
    for value in parsed.values() if isinstance(parsed, dict) else []:
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            wait = entry.get("estimated_time_to_regain_access")
            if isinstance(wait, (int, float)):
                best = max(best or 0.0, float(wait) * 60)
    return best


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict[str, Any] | None
) -> dict[str, Any]:
    attempt = 0
    while True:
        attempt += 1
        try:
            response = await client.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            if attempt > MAX_RETRIES:
                raise RuntimeError(f"Network error after {MAX_RETRIES} retries: {exc}") from exc
            await asyncio.sleep(min(2 ** attempt, 30))
            continue

        try:
            body = response.json()
        except ValueError:
            body = None

        error_code = None
        if isinstance(body, dict):
            error_code = (body.get("error") or {}).get("code")

        is_rate_limited = response.status_code == 429 or error_code in RATE_LIMIT_ERROR_CODES
        is_retryable_status = response.status_code in RETRYABLE_STATUSES

        if (is_rate_limited or is_retryable_status) and attempt <= MAX_RETRIES:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                delay = float(retry_after)
            else:
                delay = _usage_estimated_wait_seconds(response.headers) or min(2 ** attempt, 30)
            print(
                f"    rate-limited/retryable (status={response.status_code}, "
                f"error_code={error_code}), attempt {attempt}/{MAX_RETRIES}, "
                f"sleeping {delay:.1f}s: {url.split('?')[0]}"
            )
            await asyncio.sleep(delay)
            continue

        # Meta's own `paging.next` URLs embed access_token in their query
        # string -- always strip it before it reaches an error message
        # that could end up in a stored failed_jobs row or on stdout.
        safe_url = url.split("?")[0]
        if body is None:
            raise RuntimeError(f"Non-JSON response ({response.status_code}) from {safe_url}: {response.text[:300]!r}")
        if response.status_code >= 400:
            raise RuntimeError(f"Meta API error {response.status_code} from {safe_url}: {body.get('error')}")
        return body


async def _paginate(
    client: httpx.AsyncClient, path: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    request_params = {**params, "limit": PAGE_SIZE}
    next_target: str | None = path
    next_params: dict[str, Any] | None = request_params
    items: list[dict[str, Any]] = []

    while next_target is not None:
        body = await _get_with_retry(client, next_target, next_params)
        data = body.get("data", [])
        items.extend(data)

        paging = body.get("paging", {})
        next_url = paging.get("next")
        cursors_after = paging.get("cursors", {}).get("after")

        if next_url:
            next_target = next_url
            next_params = None
        elif cursors_after and len(data) == request_params["limit"]:
            next_params = {**request_params, "after": cursors_after}
            next_target = path
        else:
            next_target = None

    return items


# ----------------------------------------------------------------------
# Bronze row shaping
# ----------------------------------------------------------------------


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class FetchResult:
    account: AccountConfig
    object_type: str
    api_endpoint: str
    items: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    request_params: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _build_rows(
    result: FetchResult, *, batch_id: uuid.UUID, api_version: str, extracted_at: datetime
) -> list[dict[str, Any]]:
    rows = []
    for item in result.items:
        if result.object_type == "insights":
            meta_id = item.get("ad_id")
            parent_ids = {
                "account_key": result.account.key,
                "account_name": result.account.name,
                "account_id": item.get("account_id"),
                "campaign_id": item.get("campaign_id"),
                "adset_id": item.get("adset_id"),
                "ad_id": item.get("ad_id"),
                "date_start": item.get("date_start"),
                "date_stop": item.get("date_stop"),
            }
        else:
            meta_id = item.get("id")
            parent_ids = {
                "account_key": result.account.key,
                "account_name": result.account.name,
                "account_id": item.get("account_id", result.account.account_id),
                "campaign_id": item.get("campaign_id"),
                "adset_id": item.get("adset_id"),
            }
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "meta_id": meta_id,
                "raw_payload": json.dumps(item),
                "api_endpoint": result.api_endpoint,
                "api_version": api_version,
                "batch_id": str(batch_id),
                "request_params": json.dumps(result.request_params),
                "extracted_at": extracted_at,
                "sync_type": "manual",
                "payload_hash": _hash_payload(item),
                "processing_status": "pending",
                "object_type": result.object_type,
                "parent_ids": json.dumps(parent_ids),
                "is_nested": False,
            }
        )
    return rows


# ----------------------------------------------------------------------
# Fetch orchestration — one task per (account, object_type), all
# concurrent, mirroring MultiAccountSyncCoordinator's "every account in
# parallel" behavior plus per-account object-type concurrency.
# ----------------------------------------------------------------------


async def _fetch_campaigns(client: httpx.AsyncClient, base_url: str, account: AccountConfig, access_token: str) -> FetchResult:
    params = {
        "access_token": access_token,
        "fields": ",".join(CAMPAIGN_FIELDS),
        "effective_status": json.dumps(CAMPAIGN_STATUSES),
    }
    t0 = time.monotonic()
    result = FetchResult(account=account, object_type="campaign", api_endpoint="campaigns", request_params={k: v for k, v in params.items() if k != "access_token"})
    try:
        result.items = await _paginate(client, f"{base_url}/act_{account.account_id}/campaigns", params)
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _fetch_adsets(client: httpx.AsyncClient, base_url: str, account: AccountConfig, access_token: str) -> FetchResult:
    params = {
        "access_token": access_token,
        "fields": ",".join(ADSET_FIELDS),
        "effective_status": json.dumps(ADSET_STATUSES),
    }
    t0 = time.monotonic()
    result = FetchResult(account=account, object_type="adset", api_endpoint="adsets", request_params={k: v for k, v in params.items() if k != "access_token"})
    try:
        result.items = await _paginate(client, f"{base_url}/act_{account.account_id}/adsets", params)
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _fetch_ads(client: httpx.AsyncClient, base_url: str, account: AccountConfig, access_token: str) -> FetchResult:
    params = {
        "access_token": access_token,
        "fields": ",".join(AD_FIELDS),
        "effective_status": json.dumps(AD_STATUSES),
    }
    t0 = time.monotonic()
    result = FetchResult(account=account, object_type="ad", api_endpoint="ads", request_params={k: v for k, v in params.items() if k != "access_token"})
    try:
        result.items = await _paginate(client, f"{base_url}/act_{account.account_id}/ads", params)
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _fetch_insights(
    client: httpx.AsyncClient,
    base_url: str,
    account: AccountConfig,
    access_token: str,
    *,
    since: date,
    until: date,
    time_increment: str,
) -> FetchResult:
    params = {
        "access_token": access_token,
        "level": "ad",
        "fields": ",".join(INSIGHTS_FIELDS),
        "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        "time_increment": time_increment,
    }
    t0 = time.monotonic()
    result = FetchResult(account=account, object_type="insights", api_endpoint="insights", request_params={k: v for k, v in params.items() if k != "access_token"})
    try:
        result.items = await _paginate(client, f"{base_url}/act_{account.account_id}/insights", params)
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


# ----------------------------------------------------------------------
# Postgres: schema (idempotent) + writes
# ----------------------------------------------------------------------

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS sync_batches (
        id UUID PRIMARY KEY,
        endpoint VARCHAR(64) NOT NULL,
        account_key VARCHAR(16),
        account_name VARCHAR(128),
        sync_type VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL,
        request_params JSONB,
        records_fetched INTEGER NOT NULL DEFAULT 0,
        records_failed INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ,
        triggered_by VARCHAR(32) NOT NULL DEFAULT 'manual'
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_sync_batches_endpoint ON sync_batches (endpoint)",
    "CREATE INDEX IF NOT EXISTS ix_sync_batches_status ON sync_batches (status)",
    "CREATE INDEX IF NOT EXISTS ix_sync_batches_account_key ON sync_batches (account_key)",
    """
    CREATE TABLE IF NOT EXISTS failed_jobs (
        id UUID PRIMARY KEY,
        batch_id UUID NOT NULL,
        endpoint VARCHAR(64) NOT NULL,
        account_key VARCHAR(16),
        account_name VARCHAR(128),
        request_params JSONB,
        error_message TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 1,
        resolved BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_attempted_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_failed_jobs_batch_id ON failed_jobs (batch_id)",
    "CREATE INDEX IF NOT EXISTS ix_failed_jobs_endpoint ON failed_jobs (endpoint)",
    "CREATE INDEX IF NOT EXISTS ix_failed_jobs_resolved ON failed_jobs (resolved)",
    "CREATE INDEX IF NOT EXISTS ix_failed_jobs_account_key ON failed_jobs (account_key)",
    """
    CREATE TABLE IF NOT EXISTS raw_dump_meta (
        id UUID PRIMARY KEY,
        meta_id VARCHAR(64),
        raw_payload JSONB NOT NULL,
        api_endpoint VARCHAR(255) NOT NULL,
        api_version VARCHAR(16) NOT NULL,
        batch_id UUID NOT NULL,
        request_params JSONB,
        extracted_at TIMESTAMPTZ NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        sync_type VARCHAR(32) NOT NULL,
        payload_hash VARCHAR(64) NOT NULL,
        processing_status VARCHAR(16) NOT NULL,
        object_type VARCHAR(32) NOT NULL,
        parent_ids JSONB,
        is_nested BOOLEAN NOT NULL DEFAULT false
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_meta_id ON raw_dump_meta (meta_id)",
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_batch_id ON raw_dump_meta (batch_id)",
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_payload_hash ON raw_dump_meta (payload_hash)",
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_processing_status ON raw_dump_meta (processing_status)",
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_object_type ON raw_dump_meta (object_type)",
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_batch_meta ON raw_dump_meta (batch_id, meta_id)",
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_object_type_meta_id ON raw_dump_meta (object_type, meta_id)",
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_raw_payload_gin ON raw_dump_meta USING GIN (raw_payload)",
]


def _ensure_schema(conn) -> None:
    # Bump the per-statement timeout for schema DDL. Supabase's pooler
    # defaults to something like 120s for query timeouts; recreating the
    # GIN index (`CREATE INDEX IF NOT EXISTS ... USING GIN`) on the
    # existing 400k-row raw_dump_meta table takes ~3-4 min and blows
    # past that. Session-scope SET is safe here -- we're on a fresh
    # per-invocation psycopg2 conn, not a shared session.
    #
    # Also: skip the schema check entirely if raw_dump_meta already
    # exists. Nothing in DDL_STATEMENTS ever mutates existing tables
    # (all IF NOT EXISTS), so if the table is there, everything else is
    # too from prior runs. Avoids ~7 seconds and any timeout risk on
    # repeat invocations.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('public.raw_dump_meta') IS NOT NULL"
        )
        already_exists = bool(cur.fetchone()[0])
    if already_exists:
        print("Schema already provisioned (raw_dump_meta exists) -- skipping DDL.\n")
        return

    print("Ensuring schema exists (CREATE TABLE/INDEX IF NOT EXISTS -- never drops or alters):")
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '600s'")
        for stmt in DDL_STATEMENTS:
            first_line = " ".join(stmt.split())[:90]
            print(f"  -> {first_line}...")
            cur.execute(stmt)
    conn.commit()
    print("Schema OK.\n")


def _insert_batch_row(conn, *, batch_id: uuid.UUID, endpoint: str, account: AccountConfig, request_params: dict, records_fetched: int, records_failed: int, status: str, error_message: str | None, started_at: datetime, finished_at: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_batches
                (id, endpoint, account_key, account_name, sync_type, status,
                 request_params, records_fetched, records_failed, error_message,
                 started_at, finished_at, triggered_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(batch_id), endpoint, account.key, account.name, "manual", status,
                json.dumps(request_params), records_fetched, records_failed, error_message,
                started_at, finished_at, "manual_trial_script",
            ),
        )
    conn.commit()


def _bulk_insert_rows(conn, rows: list[dict[str, Any]], *, chunk_size: int = 500) -> int:
    if not rows:
        return 0
    columns = [
        "id", "meta_id", "raw_payload", "api_endpoint", "api_version", "batch_id",
        "request_params", "extracted_at", "sync_type", "payload_hash",
        "processing_status", "object_type", "parent_ids", "is_nested",
    ]
    inserted = 0
    with conn.cursor() as cur:
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start:start + chunk_size]
            values = [tuple(row[col] for col in columns) for row in chunk]
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO raw_dump_meta ({', '.join(columns)}) VALUES %s",
                values,
                template=None,
                page_size=chunk_size,
            )
            inserted += len(chunk)
            conn.commit()
    return inserted


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


async def _run(accounts: list[AccountConfig], *, base_url: str, access_token: str, since: date, until: date, time_increment: str, include_roster: bool) -> list[FetchResult]:
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = []
        for account in accounts:
            if include_roster:
                tasks.append(_fetch_campaigns(client, base_url, account, access_token))
                tasks.append(_fetch_adsets(client, base_url, account, access_token))
                tasks.append(_fetch_ads(client, base_url, account, access_token))
            tasks.append(
                _fetch_insights(
                    client, base_url, account, access_token,
                    since=since, until=until, time_increment=time_increment,
                )
            )
        return await asyncio.gather(*tasks)


def _write_results(dsn: str, results, *, api_version: str) -> int:
    """Persist one chunk's fetch results. Returns rows inserted.

    Lifted verbatim out of main() so a chunked backfill can commit each
    window before starting the next one. Before this, main() fetched
    EVERY account for the WHOLE window and only then wrote, so a 250-day
    run that got throttled at hour two had nothing to show for it.
    """
    write_start = time.monotonic()
    conn = psycopg2.connect(dsn)
    try:
        _ensure_schema(conn)

        extracted_at = datetime.now(timezone.utc)
        batch_ids: list[str] = []
        total_inserted = 0
        for r in results:
            batch_id = uuid.uuid4()
            batch_ids.append(str(batch_id))
            batch_start = datetime.now(timezone.utc)
            if r.error:
                _insert_batch_row(
                    conn, batch_id=batch_id, endpoint=r.api_endpoint, account=r.account,
                    request_params=r.request_params, records_fetched=0, records_failed=len(r.items),
                    status="failed", error_message=r.error[:4000],
                    started_at=batch_start, finished_at=datetime.now(timezone.utc),
                )
                continue
            rows = _build_rows(r, batch_id=batch_id, api_version=api_version, extracted_at=extracted_at)
            inserted = _bulk_insert_rows(conn, rows)
            total_inserted += inserted
            _insert_batch_row(
                conn, batch_id=batch_id, endpoint=r.api_endpoint, account=r.account,
                request_params=r.request_params, records_fetched=inserted, records_failed=0,
                status="success", error_message=None,
                started_at=batch_start, finished_at=datetime.now(timezone.utc),
            )

        print(f"  wrote {total_inserted} raw_dump_meta rows in "
              f"{time.monotonic() - write_start:.1f}s", flush=True)
        return total_inserted
    finally:
        conn.close()


def _chunks(since: date, until: date, chunk_days: int) -> list[tuple[date, date]]:
    """Consecutive [start, end] windows covering since..until inclusive."""
    if chunk_days <= 0:
        return [(since, until)]
    out: list[tuple[date, date]] = []
    start = since
    while start <= until:
        end = min(start + timedelta(days=chunk_days - 1), until)
        out.append((start, end))
        start = end + timedelta(days=1)
    return out


def main() -> int:
    # Force line-buffered stdout even when piped/redirected to a file, so
    # progress (including the rate-limit retry messages from
    # _get_with_retry) is visible during a multi-minute run instead of
    # sitting in a buffer until exit.
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=15, help="Size of the trailing window, in days (default 15).")
    parser.add_argument("--account", default=None, help="Restrict to one account key. Default: every configured account.")
    parser.add_argument("--time-increment", default="1", choices=["1", "all_days"], help="'1' = one row per ad per day (default); 'all_days' = one row per ad for the whole window.")
    parser.add_argument("--no-insert", action="store_true", help="Fetch and time only — skip all DB writes.")
    parser.add_argument("--chunk-days", type=int, default=0,
                        help="Split the window into consecutive chunks of this many days, fetching "
                             "AND WRITING each before starting the next. 0 (default) = one request "
                             "per account for the whole window, which is fine for 15 days and wrong "
                             "for 250 -- see the module docstring.")
    parser.add_argument("--include-roster", action="store_true", help="Also fetch campaigns/adsets/ads (current-state rosters, not time-windowed — off by default, see module docstring).")
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv()

    access_token = os.environ.get("META_ACCESS_TOKEN")
    api_version = os.environ.get("META_API_VERSION", "v21.0")
    if not access_token:
        print("META_ACCESS_TOKEN is not set.", file=sys.stderr)
        return 1

    accounts_by_key = _discover_accounts()
    if not accounts_by_key:
        print("No Meta ad accounts configured — set META_ACCOUNT_1_ID in .env.", file=sys.stderr)
        return 1
    if args.account:
        if args.account not in accounts_by_key:
            print(f"No account with key '{args.account}'. Configured: {', '.join(sorted(accounts_by_key, key=int))}", file=sys.stderr)
            return 1
        accounts = [accounts_by_key[args.account]]
    else:
        accounts = [accounts_by_key[k] for k in sorted(accounts_by_key, key=int)]

    dsn = None
    if not args.no_insert:
        raw_dsn = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
        if not raw_dsn:
            print("DATABASE_URL_SYNC / DATABASE_URL is not set (needed unless --no-insert).", file=sys.stderr)
            return 1
        dsn = _to_psycopg2_dsn(raw_dsn)

    until = date.today() - timedelta(days=1)  # yesterday: today's data is still accumulating
    since = until - timedelta(days=args.days - 1)
    base_url = f"https://graph.facebook.com/{api_version}"

    object_types = (["campaign", "adset", "ad", "insights"] if args.include_roster else ["insights"])

    print(f"Accounts: {', '.join(f'{a.key} ({a.name})' for a in accounts)}")
    print(f"Window: {since.isoformat()} .. {until.isoformat()}  ({args.days} days, time_increment={args.time_increment})")
    print(f"Object types per account: {', '.join(object_types)}  ({len(accounts) * len(object_types)} concurrent fetches)")
    if dsn:
        print(f"Target database: {_describe_dsn_safely(dsn)}")
    else:
        print("--no-insert set: fetching and timing only, no DB writes.")
    print("Token: [redacted, not printed] — loaded, present, not shown.\n")

    windows = _chunks(since, until, args.chunk_days)
    if len(windows) > 1:
        print(f"Chunked into {len(windows)} window(s) of up to {args.chunk_days} days. "
              f"Each is fetched AND WRITTEN before the next starts, so a throttle "
              f"or timeout keeps everything already done.\n")

    fetch_start = time.monotonic()
    any_error = False
    failed_windows: list[tuple] = []
    grand_total_rows = 0
    grand_total_inserted = 0

    for i, (w_since, w_until) in enumerate(windows, 1):
        label = f"[{i}/{len(windows)}] {w_since} .. {w_until}"
        print(f"{label}  fetching ...", flush=True)
        results = asyncio.run(
            _run(
                accounts, base_url=base_url, access_token=access_token,
                since=w_since, until=w_until,
                time_increment=args.time_increment, include_roster=args.include_roster,
            )
        )
        for r in results:
            status = "OK" if not r.error else "FAILED"
            print(f"  [{r.account.key}] {r.account.name:<24} {r.object_type:<10} "
                  f"{status:<7} {len(r.items):>6} rows  {r.duration_seconds:6.2f}s", flush=True)
            if r.error:
                any_error = True
                failed_windows.append((w_since, w_until, r.account.key))
                print(f"      error: {r.error}", file=sys.stderr, flush=True)
            grand_total_rows += len(r.items)

        if args.no_insert:
            continue
        # Written per chunk, deliberately: partial progress survives a
        # throttle. A failed account inside this chunk still records a
        # failed_jobs row and the other accounts still commit.
        grand_total_inserted += _write_results(dsn, results, api_version=api_version)

    fetch_wall_time = time.monotonic() - fetch_start
    print(f"\nTotal rows fetched: {grand_total_rows}")
    if failed_windows:
        # `any_error` is sticky across every chunk, so ONE bad account in
        # ONE window makes the process exit 1 even when every other window
        # wrote fine. Name them, or a red run looks like a total loss when
        # it may have landed almost everything.
        print(f"{len(failed_windows)} of {len(windows)} window(s) had a failed account:")
        for w_since, w_until, account_key in failed_windows:
            print(f"  {w_since} .. {w_until}  account {account_key}")
        print("Rows from every OTHER window are committed and usable -- "
              "the downstream rebuild does not need this run to be clean.")
    if args.no_insert:
        print("--no-insert set — nothing written.")
        return 1 if any_error else 0
    print(f"Total rows written: {grand_total_inserted}")
    print(f"Wall time (fetch + write, {len(windows)} chunk(s)): {fetch_wall_time:.1f}s")

    return 1 if any_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
