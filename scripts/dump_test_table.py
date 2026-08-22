"""Trial run: fetch YESTERDAY's ad-level Meta Insights, using every field
in the full Insights registry (``INSIGHTS_FIELD_GROUPS`` in
``app/core/meta_registry.py`` -- currently 141 fields), across every
configured account, and write it into a throwaway ``test_table`` in
Supabase via the REST Data API (PostgREST), authenticated with a
service-role key.

Why REST instead of a direct Postgres connection (as
``scripts/ingest_last_15_days.py`` uses): this project's ``.env`` has a
working ``SUPABASE_URL`` / service-role key pair but no valid Postgres
connection string yet (``DATABASE_URL_SYNC`` is still a placeholder, and
``DATABASE_URL`` is a dashboard URL, not a DSN) -- see that script's
docstring for the same caveat. The REST Data API only needs the project
URL and a key, so it works today without a DB password.

PostgREST can't run DDL, so ``test_table`` must already exist -- run
``scripts/sql/test_table.sql`` once in the Supabase SQL Editor first. The
script checks for the table up front and prints that same guidance (with
the exact file path) if it's missing, rather than failing confusingly
mid-run.

Scope is deliberately narrow (yesterday only, insights only, no
campaign/adset/ad roster): a full historical roster pull burned the
shared per-app rate-limit budget in an earlier trial
(see ``ingest_last_15_days.py``'s docstring) -- ``date_preset=yesterday``
naturally bounds this to only ads with delivery yesterday, with no
separate roster call needed at all.

Reads ``META_ACCESS_TOKEN`` / ``META_ACCOUNT_*`` / ``SUPABASE_URL`` /
``SUPABASE_KEY`` from ``.env`` at runtime -- the access token and the
service-role key are never printed, not even partially.

Usage:
    python3 scripts/dump_test_table.py                  # all accounts, yesterday, full fields, writes to Supabase
    python3 scripts/dump_test_table.py --account 2        # just one account
    python3 scripts/dump_test_table.py --no-insert          # fetch + time only, skip the REST write
    python3 scripts/dump_test_table.py --date-preset last_7d # override the time window if needed
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import csv
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


REPO_ROOT = Path(__file__).resolve().parent.parent
META_REGISTRY_PATH = REPO_ROOT / "app" / "core" / "meta_registry.py"
TEST_TABLE_DDL_PATH = REPO_ROOT / "scripts" / "sql" / "test_table.sql"
FIELD_ERROR_LOG_PATH = REPO_ROOT / "logs" / "insights_field_batch_errors.log"
FIELD_ERROR_LOG_CSV_PATH = REPO_ROOT / "logs" / "insights_field_batch_errors.csv"
FIELD_ERROR_LOG_JSONL_PATH = REPO_ROOT / "logs" / "insights_field_batch_errors.jsonl"
CSV_COLUMNS = [
    "timestamp", "account_key", "account_name", "batch_index", "batch_count",
    "field_count", "fields", "error_code", "error_subcode", "error_type",
    "error_message", "raw_error",
]

_ACCOUNT_ID_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_ID$")
_ACCOUNT_NAME_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_NAME$")
PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 4
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
#: Default number of `fields` per Insights request when batching. The
#: registry itself is never pruned on a rejected/erroring field anymore --
#: instead each batch is requested independently, and a batch that errors
#: is logged (to FIELD_ERROR_LOG_PATH and stdout) and skipped, while every
#: other batch still completes and contributes its data to the merged row.
DEFAULT_FIELD_BATCH_SIZE = 200

#: Mirrors app/services/meta/client.py's RATE_LIMIT_ERROR_CODES -- Meta's
#: rate-limit signals arrive as HTTP 400/403 with a JSON error body, not
#: HTTP 429, so status_code alone isn't enough to detect them.
RATE_LIMIT_ERROR_CODES = {
    4, 17, 32, 613,
    80000, 80001, 80002, 80003, 80004, 80005, 80006, 80008, 80009, 80014,
}


# ----------------------------------------------------------------------
# Pull the full Insights field registry out of meta_registry.py's source
# via the AST, without importing the module -- this script runs under
# Python 3.9 but the app package requires 3.12 (StrEnum, PEP 604 unions
# evaluated at runtime). Mirrors the same technique already used to build
# exports/meta_insights_registry.xlsx.
# ----------------------------------------------------------------------


def _load_all_insights_fields(registry_path: Path) -> list[str]:
    """Mirrors meta_registry.py's own ``ALL_INSIGHTS_FIELDS`` computation
    exactly: every field from every group, EXCEPT groups listed in
    ``FIELD_GROUPS_REQUIRING_ISOLATION`` (fields Meta rejects outright if
    combined with anything else, e.g. the SKAdNetwork postback group)."""
    tree = ast.parse(registry_path.read_text())
    groups: dict[str, list[str]] | None = None
    isolation_groups: frozenset[str] = frozenset()
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target == "INSIGHTS_FIELD_GROUPS":
            groups = ast.literal_eval(node.value)
        elif target == "FIELD_GROUPS_REQUIRING_ISOLATION":
            value_node = node.value
            # Written as `frozenset({...})` in the source -- literal_eval
            # can't evaluate the call itself, only the set literal inside it.
            if isinstance(value_node, ast.Call):
                value_node = value_node.args[0]
            isolation_groups = frozenset(ast.literal_eval(value_node))
    if groups is None:
        raise RuntimeError(f"INSIGHTS_FIELD_GROUPS not found in {registry_path}")
    return sorted(
        {f for name, fields in groups.items() if name not in isolation_groups for f in fields}
    )


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


# ----------------------------------------------------------------------
# Minimal async Meta client: pagination + retry (trimmed-down stand-in
# for app/services/meta/client.py's MetaAPIClient — see
# ingest_last_15_days.py for the same logic, reused here verbatim).
# ----------------------------------------------------------------------


def _usage_estimated_wait_seconds(headers: httpx.Headers) -> float | None:
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
            await asyncio.sleep(min(2**attempt, 30))
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
            delay = (
                float(retry_after)
                if retry_after
                else _usage_estimated_wait_seconds(response.headers) or min(2**attempt, 30)
            )
            print(
                f"    rate-limited/retryable (status={response.status_code}, "
                f"error_code={error_code}), attempt {attempt}/{MAX_RETRIES}, "
                f"sleeping {delay:.1f}s: {url.split('?')[0]}"
            )
            await asyncio.sleep(delay)
            continue

        # Meta's own `paging.next` URLs embed access_token in their query
        # string -- always strip it before this ever reaches an error
        # message, a log line, or (via an exception message) a stored row.
        safe_url = url.split("?")[0]
        if body is None:
            raise RuntimeError(
                f"Non-JSON response ({response.status_code}) from {safe_url}: {response.text[:300]!r}"
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Meta API error {response.status_code} from {safe_url}: {body.get('error')}")
        return body


async def _paginate(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
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


@dataclass
class FetchResult:
    account: AccountConfig
    items: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    request_params: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    #: Per-batch failures that didn't abort the overall fetch -- see
    #: BatchError. Empty when every field batch succeeded.
    batch_errors: list["BatchError"] = field(default_factory=list)


@dataclass
class BatchError:
    account_key: str
    account_name: str
    batch_index: int
    batch_count: int
    fields: list[str]
    error: str


def _chunk_fields(fields: list[str], batch_size: int) -> list[list[str]]:
    return [fields[i : i + batch_size] for i in range(0, len(fields), batch_size)]


def _parse_meta_error(error_str: str) -> dict[str, Any]:
    """Pull Meta's structured error dict (code/subcode/type/message) out of
    a "Meta API error NNN from URL: {...}" message for the CSV/JSONL
    columns. Falls back to empty fields if the shape doesn't match (e.g. a
    network error with no Meta error body at all)."""
    match = re.search(r": (\{.*\})\s*$", error_str, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = ast.literal_eval(match.group(1))
    except (ValueError, SyntaxError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        "error_code": parsed.get("code", ""),
        "error_subcode": parsed.get("error_subcode", ""),
        "error_type": parsed.get("type", ""),
        "error_message": parsed.get("message", ""),
    }


def _log_batch_error(err: BatchError) -> None:
    """Append a batch failure to the human-readable .log, a structured
    .csv, and a .jsonl (creating logs/ if needed), and print it -- so a
    bad field surfaces for review/sharing without ever requiring the
    registry itself to be hand-pruned."""
    timestamp = datetime.now(timezone.utc).isoformat()
    parsed_error = _parse_meta_error(err.error)

    block = (
        f"=== {timestamp} | account={err.account_key} ({err.account_name}) | "
        f"batch {err.batch_index}/{err.batch_count} ({len(err.fields)} fields) ===\n"
        f"Fields in this batch: {', '.join(err.fields)}\n"
        f"Error: {err.error}\n\n"
    )
    print(
        f"    [batch error] account={err.account_key} batch {err.batch_index}/{err.batch_count} "
        f"({len(err.fields)} fields) -- logged to {FIELD_ERROR_LOG_PATH.relative_to(REPO_ROOT)}, "
        f"{FIELD_ERROR_LOG_CSV_PATH.relative_to(REPO_ROOT)}"
    )
    FIELD_ERROR_LOG_PATH.parent.mkdir(exist_ok=True)
    with open(FIELD_ERROR_LOG_PATH, "a") as f:
        f.write(block)

    row = {
        "timestamp": timestamp,
        "account_key": err.account_key,
        "account_name": err.account_name,
        "batch_index": err.batch_index,
        "batch_count": err.batch_count,
        "field_count": len(err.fields),
        "fields": ", ".join(err.fields),
        "error_code": parsed_error.get("error_code", ""),
        "error_subcode": parsed_error.get("error_subcode", ""),
        "error_type": parsed_error.get("error_type", ""),
        "error_message": parsed_error.get("error_message", ""),
        "raw_error": err.error,
    }
    csv_is_new = not FIELD_ERROR_LOG_CSV_PATH.exists()
    with open(FIELD_ERROR_LOG_CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if csv_is_new:
            writer.writeheader()
        writer.writerow(row)

    with open(FIELD_ERROR_LOG_JSONL_PATH, "a") as f:
        f.write(json.dumps({**row, "fields": err.fields}) + "\n")


async def _fetch_insights_yesterday(
    client: httpx.AsyncClient,
    base_url: str,
    account: AccountConfig,
    access_token: str,
    *,
    fields: list[str],
    date_preset: str,
    batch_size: int = DEFAULT_FIELD_BATCH_SIZE,
) -> FetchResult:
    """Fetch every field in `fields`, split across one or more requests of
    at most `batch_size` fields each. Rows from every successful batch are
    merged by `ad_id` into one combined row per ad. A batch that errors is
    logged (see BatchError/_log_batch_error) and skipped -- it does NOT
    abort the other batches, so one bad field costs you only the fields in
    its own batch, not the whole fetch."""
    batches = _chunk_fields(fields, batch_size)
    merged: dict[str, dict[str, Any]] = {}
    batch_errors: list[BatchError] = []
    # Representative request_params for the row's audit trail -- the full
    # field list actually requested (across all batches), not just one.
    request_params = {
        "level": "ad",
        "fields": ",".join(fields),
        "date_preset": date_preset,
        "field_batch_size": batch_size,
        "field_batch_count": len(batches),
    }

    t0 = time.monotonic()
    for batch_index, batch_fields in enumerate(batches, start=1):
        params = {
            "access_token": access_token,
            "level": "ad",
            "fields": ",".join(batch_fields),
            "date_preset": date_preset,
        }
        try:
            items = await _paginate(client, f"{base_url}/act_{account.account_id}/insights", params)
        except RuntimeError as exc:
            err = BatchError(
                account_key=account.key,
                account_name=account.name,
                batch_index=batch_index,
                batch_count=len(batches),
                fields=batch_fields,
                error=str(exc),
            )
            batch_errors.append(err)
            _log_batch_error(err)
            continue
        for item in items:
            key = item.get("ad_id") or f"__no_ad_id__{batch_index}"
            merged.setdefault(key, {}).update(item)

    result = FetchResult(
        account=account,
        items=list(merged.values()),
        request_params=request_params,
        batch_errors=batch_errors,
    )
    result.duration_seconds = time.monotonic() - t0
    return result


async def _fetch_single_sample_row(
    client: httpx.AsyncClient,
    base_url: str,
    account: AccountConfig,
    access_token: str,
    *,
    fields: list[str],
    date_preset: str,
) -> FetchResult:
    """Fetch AT MOST one Insights row -- a single API call, no pagination
    follow-up regardless of what Meta's `paging` block says -- purely to
    inspect row structure before running a real (possibly large) fetch."""
    params = {
        "access_token": access_token,
        "level": "ad",
        "fields": ",".join(fields),
        "date_preset": date_preset,
        "limit": 1,
    }
    t0 = time.monotonic()
    result = FetchResult(account=account, request_params={k: v for k, v in params.items() if k != "access_token"})
    try:
        body = await _get_with_retry(client, f"{base_url}/act_{account.account_id}/insights", params)
        result.items = body.get("data", [])[:1]
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _run(
    accounts: list[AccountConfig],
    *,
    base_url: str,
    access_token: str,
    fields: list[str],
    date_preset: str,
    batch_size: int = DEFAULT_FIELD_BATCH_SIZE,
) -> list[FetchResult]:
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [
            _fetch_insights_yesterday(
                client, base_url, account, access_token,
                fields=fields, date_preset=date_preset, batch_size=batch_size,
            )
            for account in accounts
        ]
        return await asyncio.gather(*tasks)


# ----------------------------------------------------------------------
# Bronze row shaping (same shape as raw_dump_meta -- see
# alembic/versions/0001_initial_bronze_schema.py / scripts/sql/test_table.sql)
# ----------------------------------------------------------------------


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_rows(
    result: FetchResult, *, batch_id: uuid.UUID, api_version: str, extracted_at: datetime
) -> list[dict[str, Any]]:
    rows = []
    for item in result.items:
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
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "meta_id": item.get("ad_id"),
                "raw_payload": item,
                "api_endpoint": "insights",
                "api_version": api_version,
                "batch_id": str(batch_id),
                "request_params": result.request_params,
                "extracted_at": extracted_at.isoformat(),
                "sync_type": "manual",
                "payload_hash": _hash_payload(item),
                "processing_status": "pending",
                "object_type": "insights",
                "parent_ids": parent_ids,
                "is_nested": False,
            }
        )
    return rows


# ----------------------------------------------------------------------
# Supabase REST Data API (PostgREST) writes -- authenticated with the
# service-role key, which bypasses Row Level Security. No DDL capability,
# so the table must already exist (see scripts/sql/test_table.sql).
# ----------------------------------------------------------------------


async def _check_table_exists(client: httpx.AsyncClient, supabase_url: str, service_role_key: str, table: str) -> bool:
    headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
    resp = await client.get(
        f"{supabase_url.rstrip('/')}/rest/v1/{table}",
        headers=headers,
        params={"limit": "0"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code == 200:
        return True
    # PostgREST reports an undefined table as 404 with a PGRST205 body.
    return False


def _resolve_supabase_creds() -> tuple[str, str] | None:
    """DATABASE_URL / DATABASE_SERVICE_KEY take precedence -- the
    project-specific pair set up for this dump's target project. Falls
    back to the SUPABASE_URL / SUPABASE_KEY pair (a different Supabase
    project) if those aren't set. Prints a clear error and returns None
    if neither pair is fully present."""
    supabase_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_URL")
    service_role_key = (
        os.environ.get("DATABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not supabase_url or not service_role_key:
        print(
            "A Supabase project URL (DATABASE_URL or SUPABASE_URL) and a "
            "service-role key (DATABASE_SERVICE_KEY, SUPABASE_KEY, or "
            "SUPABASE_SERVICE_ROLE_KEY) must both be set in .env for the target project.",
            file=sys.stderr,
        )
        return None
    if not supabase_url.startswith("http"):
        print(
            f"'{supabase_url}' doesn't look like a Supabase project URL "
            "(expected https://<ref>.supabase.co) -- check DATABASE_URL/SUPABASE_URL.",
            file=sys.stderr,
        )
        return None
    return supabase_url, service_role_key


async def _insert_rows_supabase(
    client: httpx.AsyncClient,
    supabase_url: str,
    service_role_key: str,
    table: str,
    rows: list[dict[str, Any]],
    *,
    chunk_size: int,
) -> int:
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/{table}"
    inserted = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        attempt = 0
        while True:
            attempt += 1
            resp = await client.post(endpoint, headers=headers, json=chunk, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code < 300:
                break
            if resp.status_code in RETRYABLE_STATUSES and attempt <= MAX_RETRIES:
                delay = min(2**attempt, 30)
                print(f"    Supabase insert retryable ({resp.status_code}), attempt {attempt}/{MAX_RETRIES}, sleeping {delay}s")
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(f"Supabase insert failed ({resp.status_code}): {resp.text[:500]}")
        inserted += len(chunk)
    return inserted


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", default=None, help="Restrict to one account key. Default: every configured account.")
    parser.add_argument("--date-preset", default="yesterday", help="Meta date_preset for the Insights pull (default: yesterday).")
    parser.add_argument("--table", default="test_table", help="Target Supabase table name (default: test_table).")
    parser.add_argument("--chunk-size", type=int, default=200, help="Rows per Supabase REST insert request (default 200).")
    parser.add_argument(
        "--field-batch-size", type=int, default=DEFAULT_FIELD_BATCH_SIZE,
        help=(
            f"Max Insights `fields` per API request (default {DEFAULT_FIELD_BATCH_SIZE}). The "
            "field list is split into batches of this size; a batch that errors is logged to "
            f"{FIELD_ERROR_LOG_PATH.relative_to(REPO_ROOT)} and skipped -- other batches still run."
        ),
    )
    parser.add_argument("--no-insert", action="store_true", help="Fetch and time only -- skip the Supabase write.")
    parser.add_argument(
        "--sample",
        action="store_true",
        help=(
            "Fetch exactly ONE Insights row (single API call, capped with limit=1, no "
            "pagination) from one account and print its full raw JSON structure. No "
            "Supabase interaction unless --insert is also given."
        ),
    )
    parser.add_argument(
        "--insert",
        action="store_true",
        help="Combined with --sample: also insert that one row into the target table.",
    )
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
        print("No Meta ad accounts configured -- set META_ACCOUNT_1_ID in .env.", file=sys.stderr)
        return 1
    if args.account:
        if args.account not in accounts_by_key:
            print(f"No account with key '{args.account}'. Configured: {', '.join(sorted(accounts_by_key, key=int))}", file=sys.stderr)
            return 1
        accounts = [accounts_by_key[args.account]]
    else:
        accounts = [accounts_by_key[k] for k in sorted(accounts_by_key, key=int)]

    if args.sample:
        fields = _load_all_insights_fields(META_REGISTRY_PATH)
        sample_account = accounts[0]
        print(f"Sample mode: fetching ONE insights row from account {sample_account.key} ({sample_account.name}), date_preset={args.date_preset}")
        print(f"Insights fields requested: {len(fields)}\n")
        base_url = f"https://graph.facebook.com/{api_version}"

        async def _run_sample() -> FetchResult:
            async with httpx.AsyncClient() as client:
                return await _fetch_single_sample_row(
                    client, base_url, sample_account, access_token, fields=fields, date_preset=args.date_preset
                )

        result = asyncio.run(_run_sample())
        print(f"Meta fetch time: {result.duration_seconds:.3f}s")
        if result.error:
            print(f"FAILED: {result.error}", file=sys.stderr)
            return 1
        if not result.items:
            print("No insights rows returned (no ad had delivery in this window) -- nothing to show.")
            return 0

        row = _build_rows(
            result, batch_id=uuid.uuid4(), api_version=api_version, extracted_at=datetime.now(timezone.utc)
        )[0]
        print(f"Row structure (as it would be written to Supabase -- {len(row['raw_payload'])} fields in raw_payload):")
        print(json.dumps(row, indent=2, default=str))

        if not args.insert:
            print("\n--insert not set -- not written anywhere. Pass --sample --insert to write just this one row.")
            return 0

        creds = _resolve_supabase_creds()
        if creds is None:
            return 1
        supabase_url, service_role_key = creds

        async def _write_sample() -> tuple[bool, int]:
            async with httpx.AsyncClient() as client:
                exists = await _check_table_exists(client, supabase_url, service_role_key, args.table)
                if not exists:
                    print(
                        f"\nTable '{args.table}' doesn't exist yet (or the service-role key can't "
                        f"see it). Run {TEST_TABLE_DDL_PATH.relative_to(REPO_ROOT)} once in the "
                        "Supabase SQL Editor, then re-run this.",
                        file=sys.stderr,
                    )
                    return False, 0
                inserted = await _insert_rows_supabase(
                    client, supabase_url, service_role_key, args.table, [row], chunk_size=1
                )
                return True, inserted

        ok, inserted = asyncio.run(_write_sample())
        if not ok:
            return 1
        print(f"\nInserted {inserted} row into {args.table} (project {supabase_url}).")
        return 0

    creds = None
    if not args.no_insert:
        creds = _resolve_supabase_creds()
        if creds is None:
            return 1
    supabase_url, service_role_key = creds if creds else (None, None)

    fields = _load_all_insights_fields(META_REGISTRY_PATH)

    print(f"Accounts: {', '.join(f'{a.key} ({a.name})' for a in accounts)}")
    print(f"Insights fields: {len(fields)} (full registry from {META_REGISTRY_PATH.relative_to(REPO_ROOT)})")
    print(f"date_preset: {args.date_preset}")
    if supabase_url:
        print(f"Target Supabase project: {supabase_url}")
        print(f"Target table: {args.table}")
    else:
        print("--no-insert set: fetching and timing only, no Supabase write.")
    print("Meta access token / Supabase service-role key: [redacted, not printed] -- loaded, present, not shown.\n")

    base_url = f"https://graph.facebook.com/{api_version}"

    field_batches = len(_chunk_fields(fields, args.field_batch_size))
    print(f"Field batching: {args.field_batch_size} fields/request -> {field_batches} request(s) per account\n")

    fetch_start = time.monotonic()
    results = asyncio.run(
        _run(
            accounts, base_url=base_url, access_token=access_token, fields=fields,
            date_preset=args.date_preset, batch_size=args.field_batch_size,
        )
    )
    fetch_wall_time = time.monotonic() - fetch_start

    print("Fetch results:")
    total_rows = 0
    total_batch_errors = 0
    any_error = False
    for r in results:
        status = "OK" if not r.error else "FAILED"
        print(f"  [{r.account.key}] {r.account.name:<24} {status:<7} {len(r.items):>6} rows  {r.duration_seconds:6.2f}s")
        if r.error:
            any_error = True
            print(f"      error: {r.error}", file=sys.stderr)
        if r.batch_errors:
            total_batch_errors += len(r.batch_errors)
            print(f"      {len(r.batch_errors)}/{field_batches} field batch(es) errored (logged, other batches still ran)")
        total_rows += len(r.items)

    print(f"\nMeta fetch wall time (all {len(results)} accounts in parallel): {fetch_wall_time:.2f}s")
    print(f"Total insights rows fetched: {total_rows}")
    if total_batch_errors:
        print(f"Total field-batch errors this run: {total_batch_errors} -- see {FIELD_ERROR_LOG_PATH.relative_to(REPO_ROOT)}")

    if args.no_insert:
        print("\n--no-insert set -- stopping before any Supabase write.")
        return 1 if any_error else 0

    async def _write() -> tuple[int, bool]:
        async with httpx.AsyncClient() as client:
            exists = await _check_table_exists(client, supabase_url, service_role_key, args.table)
            if not exists:
                print(
                    f"\nTable '{args.table}' doesn't exist yet in this Supabase project (or the "
                    f"service-role key can't see it). Run {TEST_TABLE_DDL_PATH.relative_to(REPO_ROOT)} "
                    "once in the Supabase SQL Editor, then re-run this script.",
                    file=sys.stderr,
                )
                return 0, True

            extracted_at = datetime.now(timezone.utc)
            total_inserted = 0
            write_any_error = False
            for r in results:
                if r.error:
                    write_any_error = True
                    continue
                batch_id = uuid.uuid4()
                rows = _build_rows(r, batch_id=batch_id, api_version=api_version, extracted_at=extracted_at)
                inserted = await _insert_rows_supabase(
                    client, supabase_url, service_role_key, args.table, rows, chunk_size=args.chunk_size
                )
                total_inserted += inserted
                print(f"  [{r.account.key}] {r.account.name:<24} inserted {inserted} rows into {args.table}")
            return total_inserted, write_any_error

    write_start = time.monotonic()
    total_inserted, write_any_error = asyncio.run(_write())
    write_wall_time = time.monotonic() - write_start

    print(f"\nSupabase write time: {write_wall_time:.2f}s")
    print(f"Total rows inserted into {args.table}: {total_inserted}")
    print(f"\nGrand total (Meta fetch + Supabase write): {fetch_wall_time + write_wall_time:.2f}s")

    return 1 if (any_error or write_any_error) else 0


if __name__ == "__main__":
    raise SystemExit(main())
