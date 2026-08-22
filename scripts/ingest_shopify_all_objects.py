"""Fetch ONE sample row from EVERY fetchable Shopify object type (per
scripts/shopify_object_manifest.json, built by shopify_discover_objects.py
via live schema introspection -- 86 object types as of the last discovery
run: products, orders, customers, collections, draftOrders, locations,
inventoryItems, giftCards, shop, and 77 more) and insert each one into
``raw_dump_shopify`` in Supabase -- the comprehensive-sweep counterpart to
ingest_shopify.py's focused (shop/products/orders/customers) ingestion,
mirroring how scripts/validate_all_insights_fields.py complemented
scripts/dump_test_table.py on the Meta side.

Purpose: prove every manifested object type actually returns real data
and has the row shape you'd expect, in one pass, before committing to a
full production ingestion scope. Connections are queried with `first: 1`
(one API call each, no pagination) -- this is NOT a real data pull, just
a structural + access-scope sanity check across the whole catalog of
fetchable objects.

Reuses row-shaping and the Supabase REST write path directly from
ingest_shopify.py (same Bronze envelope, same env vars, same
log-and-continue philosophy on a per-object-type basis -- an object type
your access token isn't scoped for shows up as a logged error, not a
crash, and every other object type still gets its sample row).

PostgREST can't run DDL, so ``raw_dump_shopify`` must already exist --
run ``scripts/sql/raw_dump_shopify.sql`` once in the Supabase SQL Editor
first if you haven't already (see ingest_shopify.py's docstring).

Usage:
    python3 scripts/ingest_shopify_all_objects.py                 # every object type, one sample row each, writes to Supabase
    python3 scripts/ingest_shopify_all_objects.py --no-insert        # fetch + time only
    python3 scripts/ingest_shopify_all_objects.py --store 1
    python3 scripts/ingest_shopify_all_objects.py --concurrency 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shopify_client import ShopifyStore, describe_store_safely, discover_stores, graphql_request  # noqa: E402
from ingest_shopify import (  # noqa: E402
    REPO_ROOT,
    DDL_PATH,
    ERROR_LOG_PATH,
    FetchResult,
    _build_rows,
    _resolve_supabase_creds,
    _check_table_exists,
    _insert_rows_supabase,
    _log_fetch_error,
)

MANIFEST_PATH = REPO_ROOT / "scripts" / "shopify_object_manifest.json"
DEFAULT_CONCURRENCY = 8


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        print(
            f"{MANIFEST_PATH.relative_to(REPO_ROOT)} not found -- run "
            "scripts/shopify_discover_objects.py first to generate it.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return json.loads(MANIFEST_PATH.read_text())


async def _fetch_one_sample(
    client: httpx.AsyncClient, store: ShopifyStore, object_type: str, entry: dict[str, Any], semaphore: asyncio.Semaphore
) -> FetchResult:
    t0 = time.monotonic()
    result = FetchResult(store=store, object_type=object_type)
    async with semaphore:
        try:
            if entry["kind"] == "connection":
                data = await graphql_request(client, store, entry["query"], {"first": 1, "after": None})
                node = data
                for key in entry["path"]:
                    node = node.get(key) or {}
                edges = node.get("edges", [])
                result.items = [e["node"] for e in edges[:1]]
            else:
                data = await graphql_request(client, store, entry["query"])
                node = data
                for key in entry["path"]:
                    node = node.get(key)
                result.items = [node] if node else []
        except RuntimeError as exc:
            result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _run(
    store: ShopifyStore, manifest: dict[str, Any], concurrency: int
) -> list[FetchResult]:
    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency + 5, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [
            _fetch_one_sample(client, store, object_type, entry, semaphore)
            for object_type, entry in manifest.items()
        ]
        results = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            done += 1
            if done % 20 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} object types fetched...")
            results.append(result)
        return results


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=None, help="Restrict to one store key. Default: first configured store.")
    parser.add_argument("--table", default="raw_dump_shopify", help="Target Supabase table (default: raw_dump_shopify).")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help=f"Concurrent requests (default {DEFAULT_CONCURRENCY}).")
    parser.add_argument("--no-insert", action="store_true", help="Fetch and time only -- skip the Supabase write.")
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv()

    stores_by_key = discover_stores()
    if not stores_by_key:
        print("No Shopify store configured (need SHOP_DOMAIN + ADMIN_ACCESS_TOKEN or SHOPIFY_STORE_1_*).", file=sys.stderr)
        return 1
    store_key = args.store or sorted(stores_by_key, key=int)[0]
    if store_key not in stores_by_key:
        print(f"No store with key '{store_key}'. Configured: {', '.join(sorted(stores_by_key, key=int))}", file=sys.stderr)
        return 1
    store = stores_by_key[store_key]

    manifest = _load_manifest()

    supabase_url = service_role_key = None
    if not args.no_insert:
        creds = _resolve_supabase_creds()
        if creds is None:
            return 1
        supabase_url, service_role_key = creds

    print(f"Store: {describe_store_safely(store)}")
    print(f"Object types: {len(manifest)} (from {MANIFEST_PATH.relative_to(REPO_ROOT)})")
    if supabase_url:
        print(f"Target Supabase project: {supabase_url}")
        print(f"Target table: {args.table}")
    else:
        print("--no-insert set: fetching and timing only, no Supabase write.")
    print("Access token: [redacted, not printed] -- loaded, present, not shown.\n")

    fetch_start = time.monotonic()
    results = asyncio.run(_run(store, manifest, args.concurrency))
    fetch_wall_time = time.monotonic() - fetch_start

    results.sort(key=lambda r: r.object_type)
    ok_results = [r for r in results if not r.error]
    empty_results = [r for r in ok_results if not r.items]
    error_results = [r for r in results if r.error]

    print(f"\nDone fetching in {fetch_wall_time:.2f}s.")
    print(f"  OK with data: {len(ok_results) - len(empty_results)}")
    print(f"  OK but empty (no rows of this type in the store): {len(empty_results)}")
    print(f"  Errored: {len(error_results)}")

    for r in error_results:
        _log_fetch_error(r)
    if error_results:
        print(f"\n{len(error_results)} object type(s) errored (logged to {ERROR_LOG_PATH.relative_to(REPO_ROOT)}):")
        for r in error_results:
            print(f"  {r.object_type}: {r.error[:150]}")

    if empty_results:
        print(f"\n{len(empty_results)} object type(s) had zero items (nothing of that type exists in this store yet):")
        print("  " + ", ".join(r.object_type for r in empty_results))

    if args.no_insert:
        print("\n--no-insert set -- stopping before any Supabase write.")
        return 1 if error_results else 0

    async def _write() -> tuple[int, int]:
        async with httpx.AsyncClient() as client:
            exists = await _check_table_exists(client, supabase_url, service_role_key, args.table)
            if not exists:
                print(
                    f"\nTable '{args.table}' doesn't exist yet. Run {DDL_PATH.relative_to(REPO_ROOT)} "
                    "once in the Supabase SQL Editor, then re-run this.",
                    file=sys.stderr,
                )
                return 0, 0

            extracted_at = datetime.now(timezone.utc)
            total_inserted = 0
            object_types_inserted = 0
            for r in ok_results:
                if not r.items:
                    continue
                batch_id = uuid.uuid4()
                rows = _build_rows(r, batch_id=batch_id, api_version=os.environ.get("SHOPIFY_API_VERSION", "2026-07"), extracted_at=extracted_at)
                inserted = await _insert_rows_supabase(
                    client, supabase_url, service_role_key, args.table, rows, chunk_size=50
                )
                total_inserted += inserted
                object_types_inserted += 1
            return total_inserted, object_types_inserted

    write_start = time.monotonic()
    total_inserted, object_types_inserted = asyncio.run(_write())
    write_wall_time = time.monotonic() - write_start

    print(f"\nSupabase write time: {write_wall_time:.2f}s")
    print(f"Inserted {total_inserted} sample row(s) covering {object_types_inserted} object type(s) into {args.table}")
    print(f"\nGrand total (Shopify fetch + Supabase write): {fetch_wall_time + write_wall_time:.2f}s")

    return 1 if error_results else 0


if __name__ == "__main__":
    raise SystemExit(main())
