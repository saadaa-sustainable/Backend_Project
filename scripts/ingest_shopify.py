"""Fetch Shopify data (shop, products, orders, customers) via the Admin
GraphQL API, across every configured store, and write it into
``raw_dump_shopify`` in Supabase via the REST Data API -- the Shopify
counterpart to scripts/ingest_last_15_days.py / dump_test_table.py, kept
structurally identical: same Bronze row envelope, same REST-write path,
same "log batch/item errors instead of hand-pruning" philosophy, same
safety rules (access token never printed, never stored in request_params).

Why GraphQL changes the shape of this script vs the Meta ones: Shopify
has no equivalent of Meta's per-field 400 rejections -- there's no
"fields" list to prune. The two real constraints are (1) each object type
needs its own query string (not a flat field list) since GraphQL requires
you to describe nested shape up front, and (2) Shopify's cost-based
throttle (see scripts/shopify_client.py) governs pacing, not field
validity. So instead of dump_test_table.py's field-batching, this script
paginates each object type's connection and logs any page/store that
errors (same log-and-continue philosophy, still never touches a
registry -- there isn't one to prune here).

KNOWN CAVEAT (well-documented Shopify behavior, not a bug found here):
the `orders` query only returns orders from roughly the last 60 days
unless the app has the `read_all_orders` access scope. If older orders
are missing, this is almost certainly why -- check the access token's
granted scopes, not this script's query.

PostgREST can't run DDL, so ``raw_dump_shopify`` must already exist --
run ``scripts/sql/raw_dump_shopify.sql`` once in the Supabase SQL Editor
first (see scripts/dump_test_table.py's docstring for the same pattern
and why REST instead of a direct Postgres connection).

Reads SHOPIFY_STORE_<N>_DOMAIN / _NAME / _ACCESS_TOKEN and
DATABASE_URL / DATABASE_SERVICE_KEY (or SUPABASE_URL / SUPABASE_KEY as a
fallback) from .env at runtime -- see scripts/shopify_client.py's
docstring for the exact Shopify env var format.

Usage:
    python3 scripts/ingest_shopify.py                      # every store, all object types, writes to Supabase
    python3 scripts/ingest_shopify.py --store 1               # just one store
    python3 scripts/ingest_shopify.py --object-types products,orders
    python3 scripts/ingest_shopify.py --no-insert                # fetch + time only
    python3 scripts/ingest_shopify.py --page-size 100 --max-pages 5  # cap a large store for a quick trial
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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

import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shopify_client import (  # noqa: E402
    DEFAULT_API_VERSION,
    ShopifyStore,
    describe_store_safely,
    discover_stores,
    graphql_request,
    paginate_connection,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DDL_PATH = REPO_ROOT / "scripts" / "sql" / "raw_dump_shopify.sql"
ERROR_LOG_PATH = REPO_ROOT / "logs" / "shopify_ingest_errors.log"

DEFAULT_PAGE_SIZE = 50
DEFAULT_OBJECT_TYPES = ["shop", "products", "orders", "customers"]

# ----------------------------------------------------------------------
# GraphQL queries -- one per object type. Deliberately a starter field
# set (mirrors how the Meta trial scripts used trimmed field lists, not
# the full registry) -- extend here as real needs surface, same as the
# Meta side grew CAMPAIGN_FIELDS/ADSET_FIELDS/AD_FIELDS incrementally.
# ----------------------------------------------------------------------

SHOP_QUERY = """
query Shop {
  shop {
    id
    name
    myshopifyDomain
    email
    currencyCode
    ianaTimezone
    plan {
      displayName
    }
    createdAt
  }
}
"""

PRODUCTS_QUERY = """
query Products($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    edges {
      node {
        id
        title
        handle
        description
        status
        vendor
        productType
        tags
        createdAt
        updatedAt
        publishedAt
        totalInventory
        isGiftCard
        priceRangeV2 {
          minVariantPrice { amount currencyCode }
          maxVariantPrice { amount currencyCode }
        }
        variants(first: 25) {
          edges {
            node {
              id
              title
              sku
              price
              inventoryQuantity
              barcode
            }
          }
        }
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

ORDERS_QUERY = """
query Orders($first: Int!, $after: String) {
  orders(first: $first, after: $after) {
    edges {
      node {
        id
        name
        email
        createdAt
        updatedAt
        processedAt
        displayFinancialStatus
        displayFulfillmentStatus
        currentTotalPriceSet {
          shopMoney { amount currencyCode }
        }
        subtotalPriceSet {
          shopMoney { amount currencyCode }
        }
        totalPriceSet {
          shopMoney { amount currencyCode }
        }
        customer {
          id
          email
        }
        lineItems(first: 25) {
          edges {
            node {
              id
              title
              quantity
              sku
              originalUnitPriceSet {
                shopMoney { amount currencyCode }
              }
            }
          }
        }
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

CUSTOMERS_QUERY = """
query Customers($first: Int!, $after: String) {
  customers(first: $first, after: $after) {
    edges {
      node {
        id
        firstName
        lastName
        defaultEmailAddress {
          emailAddress
        }
        defaultPhoneNumber {
          phoneNumber
        }
        verifiedEmail
        state
        numberOfOrders
        amountSpent {
          amount
          currencyCode
        }
        taxExempt
        tags
        createdAt
        updatedAt
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

OBJECT_TYPE_QUERIES = {
    "products": (PRODUCTS_QUERY, ["products"]),
    "orders": (ORDERS_QUERY, ["orders"]),
    "customers": (CUSTOMERS_QUERY, ["customers"]),
}


# ----------------------------------------------------------------------
# Fetch orchestration
# ----------------------------------------------------------------------


@dataclass
class FetchResult:
    store: ShopifyStore
    object_type: str
    items: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    error: str | None = None


async def _fetch_shop(client: httpx.AsyncClient, store: ShopifyStore) -> FetchResult:
    t0 = time.monotonic()
    result = FetchResult(store=store, object_type="shop")
    try:
        data = await graphql_request(client, store, SHOP_QUERY)
        result.items = [data["shop"]]
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _fetch_object_type(
    client: httpx.AsyncClient, store: ShopifyStore, object_type: str, *, page_size: int, max_pages: int | None
) -> FetchResult:
    query, path = OBJECT_TYPE_QUERIES[object_type]
    t0 = time.monotonic()
    result = FetchResult(store=store, object_type=object_type)
    try:
        result.items = await paginate_connection(
            client, store, query, path, page_size=page_size, max_pages=max_pages
        )
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _run(
    stores: list[ShopifyStore],
    object_types: list[str],
    *,
    page_size: int,
    max_pages: int | None,
) -> list[FetchResult]:
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = []
        for store in stores:
            if "shop" in object_types:
                tasks.append(_fetch_shop(client, store))
            for object_type in object_types:
                if object_type == "shop":
                    continue
                tasks.append(
                    _fetch_object_type(client, store, object_type, page_size=page_size, max_pages=max_pages)
                )
        return await asyncio.gather(*tasks)


# ----------------------------------------------------------------------
# Bronze row shaping (same envelope as raw_dump_meta / test_table -- see
# scripts/sql/raw_dump_shopify.sql)
# ----------------------------------------------------------------------


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_rows(
    result: FetchResult, *, batch_id: uuid.UUID, api_version: str, extracted_at: datetime
) -> list[dict[str, Any]]:
    rows = []
    for item in result.items:
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "source_id": item.get("id"),
                "raw_payload": item,
                "api_endpoint": result.object_type,
                "api_version": api_version,
                "batch_id": str(batch_id),
                "request_params": {"object_type": result.object_type},
                "extracted_at": extracted_at.isoformat(),
                "sync_type": "manual",
                "payload_hash": _hash_payload(item),
                "processing_status": "pending",
                "object_type": result.object_type,
                "parent_ids": {
                    "store_key": result.store.key,
                    "store_name": result.store.name,
                    "store_domain": result.store.domain,
                },
                "is_nested": False,
            }
        )
    return rows


def _log_fetch_error(result: FetchResult) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    block = (
        f"=== {timestamp} | store={result.store.key} ({result.store.name}) | "
        f"object_type={result.object_type} ===\nError: {result.error}\n\n"
    )
    print(f"    [error] store={result.store.key} object_type={result.object_type} -- logged to {ERROR_LOG_PATH.relative_to(REPO_ROOT)}")
    ERROR_LOG_PATH.parent.mkdir(exist_ok=True)
    with open(ERROR_LOG_PATH, "a") as f:
        f.write(block)


# ----------------------------------------------------------------------
# Supabase REST Data API writes (identical pattern to dump_test_table.py)
# ----------------------------------------------------------------------


def _resolve_supabase_creds() -> tuple[str, str] | None:
    supabase_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_URL")
    service_role_key = (
        os.environ.get("DATABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not supabase_url or not service_role_key:
        print(
            "A Supabase project URL (DATABASE_URL or SUPABASE_URL) and a service-role key "
            "(DATABASE_SERVICE_KEY, SUPABASE_KEY, or SUPABASE_SERVICE_ROLE_KEY) must both be set in .env.",
            file=sys.stderr,
        )
        return None
    if not supabase_url.startswith("http"):
        print(f"'{supabase_url}' doesn't look like a Supabase project URL.", file=sys.stderr)
        return None
    return supabase_url, service_role_key


async def _check_table_exists(client: httpx.AsyncClient, supabase_url: str, service_role_key: str, table: str) -> bool:
    headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
    resp = await client.get(
        f"{supabase_url.rstrip('/')}/rest/v1/{table}", headers=headers, params={"limit": "0"}, timeout=30.0
    )
    return resp.status_code == 200


async def _insert_rows_supabase(
    client: httpx.AsyncClient, supabase_url: str, service_role_key: str, table: str,
    rows: list[dict[str, Any]], *, chunk_size: int,
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
        resp = await client.post(endpoint, headers=headers, json=chunk, timeout=60.0)
        if resp.status_code >= 300:
            raise RuntimeError(f"Supabase insert failed ({resp.status_code}): {resp.text[:500]}")
        inserted += len(chunk)
    return inserted


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=None, help="Restrict to one store key. Default: every configured store.")
    parser.add_argument(
        "--object-types", default=",".join(DEFAULT_OBJECT_TYPES),
        help=f"Comma-separated object types to fetch (default: all -- {','.join(DEFAULT_OBJECT_TYPES)}).",
    )
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help=f"Items per GraphQL page (default {DEFAULT_PAGE_SIZE}).")
    parser.add_argument("--max-pages", type=int, default=None, help="Cap pages per (store, object_type) -- useful for a quick trial on a large store.")
    parser.add_argument("--table", default="raw_dump_shopify", help="Target Supabase table (default: raw_dump_shopify).")
    parser.add_argument("--chunk-size", type=int, default=200, help="Rows per Supabase REST insert request (default 200).")
    parser.add_argument("--no-insert", action="store_true", help="Fetch and time only -- skip the Supabase write.")
    args = parser.parse_args()

    object_types = [t.strip() for t in args.object_types.split(",") if t.strip()]
    unknown = set(object_types) - set(DEFAULT_OBJECT_TYPES)
    if unknown:
        print(f"Unknown object type(s): {sorted(unknown)}. Valid: {DEFAULT_OBJECT_TYPES}", file=sys.stderr)
        return 1

    if load_dotenv is not None:
        load_dotenv()

    stores_by_key = discover_stores()
    if not stores_by_key:
        print(
            "No Shopify stores configured. Set at least SHOPIFY_STORE_1_DOMAIN and "
            "SHOPIFY_STORE_1_ACCESS_TOKEN in .env (see scripts/shopify_client.py's docstring).",
            file=sys.stderr,
        )
        return 1
    if args.store:
        if args.store not in stores_by_key:
            print(f"No store with key '{args.store}'. Configured: {', '.join(sorted(stores_by_key, key=int))}", file=sys.stderr)
            return 1
        stores = [stores_by_key[args.store]]
    else:
        stores = [stores_by_key[k] for k in sorted(stores_by_key, key=int)]

    supabase_url = service_role_key = None
    if not args.no_insert:
        creds = _resolve_supabase_creds()
        if creds is None:
            return 1
        supabase_url, service_role_key = creds

    api_version = os.environ.get("SHOPIFY_API_VERSION", DEFAULT_API_VERSION)

    print("Stores: " + ", ".join(describe_store_safely(s) for s in stores))
    print(f"Object types: {object_types}")
    print(f"Page size: {args.page_size}" + (f"  max_pages: {args.max_pages}" if args.max_pages else ""))
    if supabase_url:
        print(f"Target Supabase project: {supabase_url}")
        print(f"Target table: {args.table}")
    else:
        print("--no-insert set: fetching and timing only, no Supabase write.")
    print("Access token(s): [redacted, not printed] -- loaded, present, not shown.\n")

    fetch_start = time.monotonic()
    results = asyncio.run(
        _run(stores, object_types, page_size=args.page_size, max_pages=args.max_pages)
    )
    fetch_wall_time = time.monotonic() - fetch_start

    print("Fetch results:")
    total_rows = 0
    any_error = False
    for r in results:
        status = "OK" if not r.error else "FAILED"
        print(f"  [{r.store.key}] {r.store.name:<24} {r.object_type:<10} {status:<7} {len(r.items):>6} rows  {r.duration_seconds:6.2f}s")
        if r.error:
            any_error = True
            _log_fetch_error(r)
        total_rows += len(r.items)

    print(f"\nShopify fetch wall time (all {len(results)} calls in parallel): {fetch_wall_time:.2f}s")
    print(f"Total rows fetched: {total_rows}")

    if args.no_insert:
        print("\n--no-insert set -- stopping before any Supabase write.")
        return 1 if any_error else 0

    async def _write() -> tuple[int, bool]:
        async with httpx.AsyncClient() as client:
            exists = await _check_table_exists(client, supabase_url, service_role_key, args.table)
            if not exists:
                print(
                    f"\nTable '{args.table}' doesn't exist yet (or the service-role key can't see it). "
                    f"Run {DDL_PATH.relative_to(REPO_ROOT)} once in the Supabase SQL Editor, then re-run this.",
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
                print(f"  [{r.store.key}] {r.store.name:<24} {r.object_type:<10} inserted {inserted} rows")
            return total_inserted, write_any_error

    write_start = time.monotonic()
    total_inserted, write_any_error = asyncio.run(_write())
    write_wall_time = time.monotonic() - write_start

    print(f"\nSupabase write time: {write_wall_time:.2f}s")
    print(f"Total rows inserted into {args.table}: {total_inserted}")
    print(f"\nGrand total (Shopify fetch + Supabase write): {fetch_wall_time + write_wall_time:.2f}s")

    return 1 if (any_error or write_any_error) else 0


if __name__ == "__main__":
    raise SystemExit(main())
