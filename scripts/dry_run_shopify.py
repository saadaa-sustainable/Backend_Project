"""Dry run: confirm Shopify credentials work and show the shape of the
data before building anything bigger on top -- the Shopify counterpart to
scripts/dry_run_meta.py. Fetches the shop record plus a small page of
products (default 3) for every configured store. No database writes.

Reads SHOPIFY_STORE_<N>_DOMAIN / _NAME / _ACCESS_TOKEN from .env at
runtime (see scripts/shopify_client.py's docstring for the exact format).
The access token is never printed, not even partially.

Usage:
    python3 scripts/dry_run_shopify.py                 # every configured store
    python3 scripts/dry_run_shopify.py --store 1         # just one store
    python3 scripts/dry_run_shopify.py --limit 10         # more sample products
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
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
from shopify_client import (  # noqa: E402
    ShopifyStore,
    describe_store_safely,
    discover_stores,
    graphql_request,
)

SHOP_AND_PRODUCTS_QUERY = """
query DryRun($first: Int!) {
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
  }
  products(first: $first) {
    edges {
      node {
        id
        title
        handle
        status
        vendor
        productType
        createdAt
        updatedAt
        totalInventory
      }
    }
    pageInfo {
      hasNextPage
    }
  }
}
"""


async def _dry_run_one_store(client: httpx.AsyncClient, store: ShopifyStore, limit: int) -> dict[str, Any]:
    try:
        data = await graphql_request(client, store, SHOP_AND_PRODUCTS_QUERY, {"first": limit})
        return {"store": store, "data": data, "error": None}
    except RuntimeError as exc:
        return {"store": store, "data": None, "error": str(exc)}


async def _run(stores: list[ShopifyStore], limit: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        tasks = [_dry_run_one_store(client, store, limit) for store in stores]
        return await asyncio.gather(*tasks)


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=None, help="Restrict to one store key. Default: every configured store.")
    parser.add_argument("--limit", type=int, default=3, help="Number of sample products to fetch (default 3).")
    args = parser.parse_args()

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

    print("Stores: " + ", ".join(describe_store_safely(s) for s in stores))
    print("Access token(s): [redacted, not printed] -- loaded, present, not shown.\n")

    results = asyncio.run(_run(stores, args.limit))

    any_error = False
    for r in results:
        store = r["store"]
        if r["error"]:
            any_error = True
            print(f"[{store.key}] {store.name}: FAILED\n  {r['error']}\n")
            continue
        shop = r["data"]["shop"]
        products = [e["node"] for e in r["data"]["products"]["edges"]]
        has_more = r["data"]["products"]["pageInfo"]["hasNextPage"]
        print(f"[{store.key}] {store.name}: OK")
        print(f"  shop: {json.dumps(shop, indent=2)}")
        print(f"  sample products ({len(products)}{', more available' if has_more else ''}):")
        for p in products:
            print(f"    - {p['id']}  {p['title']!r}  status={p['status']}  inventory={p['totalInventory']}")
        print()

    return 1 if any_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
