"""fetch_ad_product_insights.py — pull Meta Insights sliced by
``breakdowns=product_id`` for the ~362 DPA / Advantage+ catalog adsets
in the account, and land the raw payloads in
``raw_dump_meta.object_type='insights_product'``.

Only DPA adsets (adset.promoted_object.product_set_id present) return
product_id rows from Meta -- regular image/video adsets get zero back.
So the scope is naturally narrow (~773 ads, 15 product sets across 2
accounts), and each account is fetched with a
``filtering=[{'field':'ad.adset_id','operator':'IN','value':[...]}]``
clause chunked in groups of 50 to stay under Meta's ~200-value cap.

Usage:
    python scripts/fetch_ad_product_insights.py                # last 30 days, all accounts
    python scripts/fetch_ad_product_insights.py --days 15
    python scripts/fetch_ad_product_insights.py --account 1
    python scripts/fetch_ad_product_insights.py --dry-run       # fetch + count only
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
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)


# ─── fields ─────────────────────────────────────────────────────────────
# Keep the field list minimal -- Meta's product-breakdown responses are
# already large (one row per ad × day × product_id), and every extra
# field multiplies row size.
INSIGHTS_FIELDS = [
    "ad_id", "adset_id", "campaign_id", "account_id",
    "date_start", "date_stop",
    "spend", "impressions", "clicks",
    "actions", "action_values",
]

PAGE_SIZE = 100  # tighter than the default 250 to reduce per-page failure risk
REQUEST_TIMEOUT_SECONDS = 90.0
MAX_RETRIES = 4
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
RATE_LIMIT_ERROR_CODES = {
    4, 17, 32, 613, 80000, 80001, 80002, 80003, 80004, 80005, 80006, 80008, 80009, 80014,
}
FILTER_CHUNK_SIZE = 50  # adset_ids per filtering clause
DATE_CHUNK_DAYS = 30    # date-range chunk (Meta 400s on very wide windows)

_ACCOUNT_ID_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_ID$")
_ACCOUNT_NAME_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_NAME$")


@dataclass
class AccountConfig:
    key: str
    name: str
    account_id: str


def _discover_accounts() -> dict[str, AccountConfig]:
    raw: dict[str, dict[str, str]] = {}
    for k, v in os.environ.items():
        if not v:
            continue
        if m := _ACCOUNT_ID_PATTERN.match(k):
            raw.setdefault(m.group(1), {})["id"] = v.removeprefix("act_")
        elif m := _ACCOUNT_NAME_PATTERN.match(k):
            raw.setdefault(m.group(1), {})["name"] = v
    return {
        k: AccountConfig(key=k, name=f.get("name", f"account_{k}"), account_id=f["id"])
        for k, f in raw.items() if "id" in f
    }


def _to_psycopg2_dsn(url: str) -> str:
    for prefix in ("postgresql+psycopg2://", "postgresql+asyncpg://",
                   "postgres+psycopg2://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    else:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
    p = urlsplit(url)
    q = dict(parse_qsl(p.query))
    q.setdefault("sslmode", "require")
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


# ─── Meta client ────────────────────────────────────────────────────────
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
        for e in entries:
            if isinstance(e, dict):
                w = e.get("estimated_time_to_regain_access")
                if isinstance(w, (int, float)):
                    best = max(best or 0.0, float(w) * 60)
    return best


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict | None) -> dict:
    attempt = 0
    while True:
        attempt += 1
        try:
            r = await client.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except httpx.HTTPError as e:
            if attempt > MAX_RETRIES:
                raise RuntimeError(f"network error after {MAX_RETRIES} retries: {e}") from e
            await asyncio.sleep(min(2 ** attempt, 30))
            continue
        try:
            body = r.json()
        except ValueError:
            body = None
        err_code = (body or {}).get("error", {}).get("code") if isinstance(body, dict) else None
        rate_limited = r.status_code == 429 or err_code in RATE_LIMIT_ERROR_CODES
        retryable = r.status_code in RETRYABLE_STATUSES
        if (rate_limited or retryable) and attempt <= MAX_RETRIES:
            ra = r.headers.get("Retry-After")
            delay = float(ra) if ra else (_usage_estimated_wait_seconds(r.headers) or min(2 ** attempt, 30))
            print(f"    rate-limited (status={r.status_code}, code={err_code}), sleeping {delay:.1f}s")
            await asyncio.sleep(delay)
            continue
        safe = url.split("?")[0]
        if body is None:
            raise RuntimeError(f"non-JSON ({r.status_code}) from {safe}: {r.text[:300]!r}")
        if r.status_code >= 400:
            raise RuntimeError(f"Meta API {r.status_code} from {safe}: {body.get('error')}")
        return body


async def _paginate(client: httpx.AsyncClient, path: str, params: dict) -> list[dict]:
    request_params = {**params, "limit": PAGE_SIZE}
    next_target: str | None = path
    next_params: dict | None = request_params
    items: list[dict] = []
    while next_target is not None:
        body = await _get_with_retry(client, next_target, next_params)
        data = body.get("data", [])
        items.extend(data)
        paging = body.get("paging", {})
        nu = paging.get("next")
        ca = paging.get("cursors", {}).get("after")
        if nu:
            next_target, next_params = nu, None
        elif ca and len(data) == request_params["limit"]:
            next_params, next_target = {**request_params, "after": ca}, path
        else:
            next_target = None
    return items


# ─── DPA adset discovery ───────────────────────────────────────────────
def _dpa_adsets_by_account(dsn: str, spending_only: bool = True) -> dict[str, list[str]]:
    """Return {account_id: [adset_id, ...]} for DPA (product_set_id-bearing)
    adsets. With spending_only=True (the default), further restrict to adsets
    that have ANY lifetime spend in raw_dump_meta insights -- otherwise we
    waste Meta rate-limit budget on 361 permanently-zero adsets to discover
    that only 1 ever spent."""
    where_spend = ""
    if spending_only:
        where_spend = """
            AND raw_payload ->> 'id' IN (
                SELECT DISTINCT raw_payload ->> 'adset_id'
                FROM raw_dump_meta
                WHERE object_type = 'insights'
                  AND NULLIF(raw_payload ->> 'spend', '')::numeric > 0
            )
        """
    out: dict[str, list[str]] = {}
    with psycopg2.connect(dsn) as c, c.cursor() as cur:
        cur.execute(f"""
            SELECT parent_ids ->> 'account_id' AS account_id,
                   raw_payload ->> 'id'         AS adset_id
            FROM raw_dump_meta
            WHERE object_type = 'adset'
              AND raw_payload -> 'promoted_object' ? 'product_set_id'
              {where_spend}
        """)
        for account_id, adset_id in cur.fetchall():
            out.setdefault(account_id, []).append(adset_id)
    return out


def _chunk(xs: list[str], n: int) -> list[list[str]]:
    return [xs[i:i + n] for i in range(0, len(xs), n)]


def _date_chunks(start: date, end: date, chunk_days: int = DATE_CHUNK_DAYS) -> list[tuple[date, date]]:
    if (end - start).days < chunk_days:
        return [(start, end)]
    out: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        out.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return out


# ─── one insights fetch per (account, adset-chunk) ─────────────────────
async def _fetch_product_insights_chunk(
    client: httpx.AsyncClient,
    base_url: str,
    account: AccountConfig,
    access_token: str,
    adset_ids: list[str],
    since: date,
    until: date,
) -> tuple[AccountConfig, list[dict], dict, str | None]:
    params = {
        "access_token": access_token,
        "level": "ad",
        "fields": ",".join(INSIGHTS_FIELDS),
        "breakdowns": "product_id",
        "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        "time_increment": "1",
        "filtering": json.dumps([{
            "field": "adset.id",
            "operator": "IN",
            "value": adset_ids,
        }]),
    }
    safe_params = {k: v for k, v in params.items() if k != "access_token"}
    try:
        items = await _paginate(client, f"{base_url}/act_{account.account_id}/insights", params)
        return account, items, safe_params, None
    except RuntimeError as e:
        return account, [], safe_params, str(e)


# ─── Bronze row shaping ────────────────────────────────────────────────
def _hash_payload(p: dict) -> str:
    canonical = json.dumps(p, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_rows(
    account: AccountConfig, items: list[dict], request_params: dict,
    *, batch_id: uuid.UUID, api_version: str, extracted_at: datetime,
) -> list[dict]:
    rows = []
    for item in items:
        parent_ids = {
            "account_key": account.key,
            "account_name": account.name,
            "account_id": item.get("account_id"),
            "campaign_id": item.get("campaign_id"),
            "adset_id": item.get("adset_id"),
            "ad_id": item.get("ad_id"),
            "date_start": item.get("date_start"),
            "date_stop": item.get("date_stop"),
            "product_id": item.get("product_id"),
        }
        rows.append({
            "id": str(uuid.uuid4()),
            "meta_id": item.get("ad_id"),
            "raw_payload": json.dumps(item),
            "api_endpoint": "insights",
            "api_version": api_version,
            "batch_id": str(batch_id),
            "request_params": json.dumps(request_params),
            "extracted_at": extracted_at,
            "sync_type": "manual",
            "payload_hash": _hash_payload(item),
            "processing_status": "pending",
            "object_type": "insights_product",
            "parent_ids": json.dumps(parent_ids),
            "is_nested": False,
        })
    return rows


def _bulk_insert(conn, rows: list[dict], *, chunk_size: int = 500) -> int:
    if not rows:
        return 0
    cols = ["id", "meta_id", "raw_payload", "api_endpoint", "api_version",
            "batch_id", "request_params", "extracted_at", "sync_type",
            "payload_hash", "processing_status", "object_type",
            "parent_ids", "is_nested"]
    inserted = 0
    with conn.cursor() as cur:
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start:start + chunk_size]
            values = [tuple(row[c] for c in cols) for row in chunk]
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO raw_dump_meta ({', '.join(cols)}) VALUES %s",
                values, template=None, page_size=chunk_size,
            )
            inserted += len(chunk)
            conn.commit()
    return inserted


# ─── main ──────────────────────────────────────────────────────────────
async def _run(tasks: list) -> list[tuple]:
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    async with httpx.AsyncClient(limits=limits) as client:
        return await asyncio.gather(*[t(client) for t in tasks])


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--account", default=None, help="Restrict to one account key")
    ap.add_argument("--dry-run", action="store_true", help="Fetch + count only, no DB writes")
    ap.add_argument("--all-dpa", action="store_true",
                    help="Fetch every DPA adset (default: only those with lifetime spend > 0)")
    args = ap.parse_args()

    access_token = os.environ.get("META_ACCESS_TOKEN")
    api_version = os.environ.get("META_API_VERSION", "v21.0")
    if not access_token:
        print("META_ACCESS_TOKEN missing", file=sys.stderr); return 1

    accounts_by_key = _discover_accounts()
    if args.account:
        if args.account not in accounts_by_key:
            print(f"unknown account key {args.account}; have {sorted(accounts_by_key)}", file=sys.stderr)
            return 1
        accounts = [accounts_by_key[args.account]]
    else:
        accounts = [accounts_by_key[k] for k in sorted(accounts_by_key, key=int)]

    raw_dsn = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not raw_dsn:
        print("DATABASE_URL_SYNC missing", file=sys.stderr); return 1
    dsn = _to_psycopg2_dsn(raw_dsn)
    # 2026-09-04: DPA adset discovery scans raw_dump_meta with a
    # spend-filter EXISTS subquery -- 2+ min on a warm cache, well past
    # pgbouncer's transaction-mode 8s statement timeout. Swap to the
    # session-mode pooler port so we get the (much longer) session-role
    # statement_timeout instead. Same DB, different pool.
    dsn = dsn.replace(":6543/", ":5432/")

    dpa = _dpa_adsets_by_account(dsn, spending_only=not args.all_dpa)
    print("== DPA adsets available per account ==")
    for a in accounts:
        n = len(dpa.get(a.account_id, []))
        print(f"  {a.key:>2} {a.name:<28} account_id={a.account_id}  dpa_adsets={n}")

    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=args.days - 1)
    print(f"\nWindow: {since} .. {until} ({args.days} days), breakdowns=product_id")

    base_url = f"https://graph.facebook.com/{api_version}"
    tasks = []
    plan: list[tuple[AccountConfig, list[str], date, date]] = []
    for a in accounts:
        adset_ids = dpa.get(a.account_id, [])
        if not adset_ids:
            continue
        for id_chunk in _chunk(adset_ids, FILTER_CHUNK_SIZE):
            for d_since, d_until in _date_chunks(since, until):
                plan.append((a, id_chunk, d_since, d_until))
                tasks.append(
                    lambda cli, acc=a, ids=id_chunk, s=d_since, u=d_until:
                        _fetch_product_insights_chunk(cli, base_url, acc, access_token, ids, s, u)
                )

    if not tasks:
        print("No DPA adsets to fetch."); return 0

    print(f"Firing {len(tasks)} chunked fetches (adset-id chunks x date-chunks)")
    t0 = time.monotonic()
    results = asyncio.run(_run(tasks))
    dt = time.monotonic() - t0

    total_rows = 0
    errors = 0
    print("\n== fetch results ==")
    for account, items, _params, err in results:
        status = "OK" if not err else "ERR"
        print(f"  [{account.key}] {account.name:<24} {status}  {len(items):>6} rows")
        if err:
            errors += 1
            print(f"      error: {err[:400]}", file=sys.stderr)
        total_rows += len(items)
    print(f"\ntotal rows: {total_rows:,}  wall={dt:.1f}s  errors={errors}")

    if args.dry_run:
        print("--dry-run set, no DB writes."); return 0 if errors == 0 else 1

    conn = psycopg2.connect(dsn)
    try:
        extracted_at = datetime.now(timezone.utc)
        inserted_total = 0
        for account, items, params, err in results:
            if err or not items:
                continue
            batch_id = uuid.uuid4()
            rows = _build_rows(account, items, params, batch_id=batch_id,
                               api_version=api_version, extracted_at=extracted_at)
            inserted_total += _bulk_insert(conn, rows)
        print(f"\n[ok] inserted {inserted_total:,} rows into raw_dump_meta (object_type='insights_product')")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*), COUNT(DISTINCT meta_id),
                       COUNT(DISTINCT parent_ids ->> 'product_id')
                FROM raw_dump_meta
                WHERE object_type='insights_product'
            """)
            n, dad, dpid = cur.fetchone()
            print(f"[verify] total rows={n:,}  distinct ads={dad:,}  distinct product_ids={dpid:,}")
    finally:
        conn.close()
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
