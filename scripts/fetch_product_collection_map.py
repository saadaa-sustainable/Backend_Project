"""Fetch every product's handle, variant SKUs and collection membership.

Why one pass over products rather than over collections: a product knows
which collections it belongs to, and we already need its handle and SKUs
to resolve a master SKU. Walking collections instead would mean a nested
products connection per collection, which multiplies Shopify's query
cost and still has to be joined back to SKUs afterwards.

The result is the join the landing-page analysis cannot make on its own:

    /products/<handle>     -> master SKU   (exact, the URL IS the handle)
    /collections/<handle>  -> master SKUs  (actual membership, not a guess)

Collection membership is a MANY-to-many fact: one collection page sells
many SKUs and one SKU sits in many collections. So a collection page's
sessions are NOT a SKU's sessions -- they are shared. Anything reading
this table has to say which it means.

Usage:
    ./.venv/bin/python scripts/fetch_product_collection_map.py
    ./.venv/bin/python scripts/fetch_product_collection_map.py --limit-pages 2
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.gold.cpis import parse_master_sku  # noqa: E402
from scripts.dbq import connect  # noqa: E402
from scripts.shopify_client import (  # noqa: E402
    discover_stores,
    paginate_connection,
)

# Nested connections multiply Shopify's query cost, so the OUTER page is
# deliberately small. 25 products x (100 variants + 50 collections) sits
# inside the cost ceiling; 250 does not.
PAGE_SIZE = 25

QUERY = """
query Products($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    edges {
      node {
        id
        handle
        title
        status
        onlineStoreUrl
        variants(first: 100) { edges { node { sku price } } }
        collections(first: 50) { edges { node { handle title } } }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

DDL = """
CREATE TABLE IF NOT EXISTS public.sku_page_map (
    master_sku        text NOT NULL,
    page_path         text NOT NULL,
    page_type         text NOT NULL,   -- 'Product' | 'Collection'
    page_title        text,
    -- How many master SKUs share this page. 1 for a product page; a
    -- collection page is shared, and a reader that ignores this will
    -- credit one collection's whole traffic to every SKU on it.
    skus_on_page      integer,
    product_handle    text,            -- the product that carries the SKU
    product_status    text,
    refreshed_at      timestamptz DEFAULT now(),
    PRIMARY KEY (master_sku, page_path)
);
CREATE INDEX IF NOT EXISTS ix_spm_path ON public.sku_page_map (page_path);
CREATE INDEX IF NOT EXISTS ix_spm_type ON public.sku_page_map (page_type);
"""


async def fetch() -> list[dict]:
    load_dotenv()
    stores = discover_stores()
    if not stores:
        raise SystemExit("No Shopify store configured. Set SHOP_DOMAIN / ADMIN_ACCESS_TOKEN.")
    store = stores[sorted(stores)[0]]
    async with httpx.AsyncClient() as client:
        return await paginate_connection(
            client, store, QUERY, ["products"], page_size=PAGE_SIZE
        )


def build_rows(products: list[dict]) -> list[tuple]:
    """One row per (master SKU, page). Product pages and collection pages
    both land here; the caller tells them apart by page_type."""
    # master_sku -> product handles, and collection handle -> its SKUs
    product_rows: dict[tuple[str, str], tuple] = {}
    collection_skus: dict[str, set[str]] = {}
    collection_titles: dict[str, str] = {}

    for p in products:
        handle, status = p.get("handle"), p.get("status")
        if not handle:
            continue
        masters = {
            parse_master_sku((e.get("node") or {}).get("sku"))
            for e in (p.get("variants") or {}).get("edges", [])
        }
        masters.discard(None)
        if not masters:
            continue

        for m in masters:
            product_rows[(m, f"/products/{handle}")] = (
                m, f"/products/{handle}", "Product", p.get("title"),
                1, handle, status,
            )
        for e in (p.get("collections") or {}).get("edges", []):
            node = e.get("node") or {}
            ch = node.get("handle")
            if not ch:
                continue
            collection_titles[ch] = node.get("title")
            collection_skus.setdefault(ch, set()).update(masters)

    rows = list(product_rows.values())
    for ch, skus in collection_skus.items():
        for m in skus:
            rows.append((
                m, f"/collections/{ch}", "Collection", collection_titles.get(ch),
                len(skus), None, None,
            ))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    products = asyncio.run(fetch())
    print(f"  fetched {len(products)} products in {time.time() - t0:.0f}s")

    rows = build_rows(products)
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r[2]] = by_type.get(r[2], 0) + 1
    print(f"  {len(rows)} (sku, page) rows: {by_type}")
    print(f"  distinct master SKUs: {len({r[0] for r in rows})}")
    print(f"  distinct collection pages: {len({r[1] for r in rows if r[2] == 'Collection'})}")
    if args.dry_run:
        for r in rows[:5]:
            print("   ", r)
        return 0

    # connect() yields the connection and closes it on exit -- it is a
    # context manager, not a raw psycopg2 connection.
    from psycopg2.extras import execute_values
    with connect(autocommit=False, statement_timeout="300s") as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute("TRUNCATE public.sku_page_map")
            execute_values(cur, """
                INSERT INTO public.sku_page_map
                  (master_sku, page_path, page_type, page_title,
                   skus_on_page, product_handle, product_status)
                VALUES %s
                ON CONFLICT (master_sku, page_path) DO NOTHING
            """, rows, page_size=1000)
        conn.commit()
    print(f"  wrote sku_page_map in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
