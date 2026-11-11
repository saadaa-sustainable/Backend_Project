"""Pull RETURN requests from Return Prime into the warehouse.

WHY THIS EXISTS
---------------
Returns on this store are settled through Return Prime, outside
Shopify's native returns API, so nothing in the Shopify data says what
came back. Sales reversals in Shopify's own breakdown are cancellation,
not returns. This is the only place the value of returned goods is
measured.

WHAT IS KEPT
------------
Return requests only. Exchanges come through the same endpoint and are
filtered out at the API (`request_type=return`): an exchange swaps for
equal value, so the money stayed.

No customer details. The API sends name, phone, email, address and bank
fields with every request; none of them are stored, only the state.

THE VALUE OF A RETURN
---------------------
`shop_price.actual_amount` and `total_discount` are PER UNIT. A line
returning two pieces reports the price of one, so the line value is

    (actual_amount - total_discount) x quantity

Summing actual_amount alone, as a first sketch of this did, both halves
a two-piece return and ignores the discount the customer never paid.

WHICH DAY A RETURN BELONGS TO
-----------------------------
Both dates are stored. `created_at` is when the customer asked;
`order_created_at` is when the order was placed, and it is the one the
P&L uses -- a return on a three-week-old order must not land on this
afternoon's hour.

RE-RUNNING
----------
Upsert by request id, so a re-run moves a request along its stages
(requested -> approved -> received -> inspected, or rejected) and picks
up the refund once it is issued. The API lists newest first by
`created_at`, so the walk stops at the first page that is wholly older
than the window. Returns arrive up to a few weeks after the order and
then take days to settle, hence the long default window.

Usage:
    ./.venv/bin/python scripts/fetch_return_prime.py              # last 45 days
    ./.venv/bin/python scripts/fetch_return_prime.py --days 120
    ./.venv/bin/python scripts/fetch_return_prime.py --dry-run

Needs RP_TOKEN in the environment or in .env.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402

BASE = os.environ.get("RP_BASE", "https://admin.returnprime.com/return-exchange/v2/")
#: The API refuses anything above 100 with a 412.
PAGE_SIZE = 100
MAX_PAGES = 2000
#: Rows per write. The Supabase pooler drops long statements.
CHUNK = 500

DDL = """
CREATE TABLE IF NOT EXISTS public.return_prime_requests (
    id               text PRIMARY KEY,
    request_number   text,
    request_type     text NOT NULL,
    status           text,
    -- The furthest stage reached: rejected, archived, inspected,
    -- received, approved or requested.
    stage            text NOT NULL,
    manual_request   boolean,
    order_id         bigint,
    -- Shopify order name, '#1611193', the join to shopify_orders.name.
    order_name       text,
    order_created_at timestamptz,
    province         text,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz,
    approved_at      timestamptz,
    received_at      timestamptz,
    inspected_at     timestamptz,
    rejected_at      timestamptz,
    total_qty        integer NOT NULL DEFAULT 0,
    -- Rupees, discount out, tax in: the same basis as an order total.
    return_value     numeric NOT NULL DEFAULT 0,
    -- What has actually been handed back so far. Zero until refunded.
    refunded_amount  numeric NOT NULL DEFAULT 0,
    refund_status    text,
    first_seen_at    timestamptz NOT NULL DEFAULT now(),
    fetched_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_return_prime_requests_order_at
    ON public.return_prime_requests(order_created_at);
CREATE INDEX IF NOT EXISTS ix_return_prime_requests_created
    ON public.return_prime_requests(created_at);
CREATE INDEX IF NOT EXISTS ix_return_prime_requests_order_name
    ON public.return_prime_requests(order_name);

CREATE TABLE IF NOT EXISTS public.return_prime_items (
    item_id         bigint NOT NULL,
    request_id      text   NOT NULL REFERENCES public.return_prime_requests(id) ON DELETE CASCADE,
    sku             text,
    product_title   text,
    variant_title   text,
    quantity        integer NOT NULL DEFAULT 0,
    -- All three per unit, as the API reports them.
    unit_price      numeric,
    unit_discount   numeric,
    unit_tax        numeric,
    line_value      numeric NOT NULL DEFAULT 0,
    reason          text,
    refund_status   text,
    refund_mode     text,
    refunded_amount numeric NOT NULL DEFAULT 0,
    refunded_at     timestamptz,
    return_fee      numeric NOT NULL DEFAULT 0,
    shipment_status text,
    PRIMARY KEY (item_id, request_id)
);
CREATE INDEX IF NOT EXISTS ix_return_prime_items_sku ON public.return_prime_items(sku);
"""

REQUEST_COLS = [
    "id", "request_number", "request_type", "status", "stage", "manual_request",
    "order_id", "order_name", "order_created_at", "province", "created_at", "updated_at",
    "approved_at", "received_at", "inspected_at", "rejected_at",
    "total_qty", "return_value", "refunded_amount", "refund_status",
]
ITEM_COLS = [
    "item_id", "request_id", "sku", "product_title", "variant_title", "quantity",
    "unit_price", "unit_discount", "unit_tax", "line_value", "reason",
    "refund_status", "refund_mode", "refunded_amount", "refunded_at",
    "return_fee", "shipment_status",
]


def _upsert_sql(table: str, cols: list[str], keys: list[str]) -> str:
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in keys)
    extra = ", fetched_at = now()" if table.endswith("requests") else ""
    return (f"INSERT INTO public.{table} ({', '.join(cols)}) VALUES %s "
            f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {sets}{extra}")


def token() -> str:
    tok = os.environ.get("RP_TOKEN")
    if not tok:
        try:
            from dotenv import dotenv_values
            tok = dotenv_values(ROOT / ".env").get("RP_TOKEN")
        except ImportError:
            tok = None
    if not tok:
        raise SystemExit("RP_TOKEN is not set in the environment or in .env")
    return tok


def fetch_page(tok: str, page: int, retries: int = 5) -> dict:
    url = f"{BASE}?page={page}&limit={PAGE_SIZE}&request_type=return"
    for attempt in range(retries):
        try:
            req = urlrequest.Request(url, headers={"x-rp-token": tok})
            with urlrequest.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except urlerror.HTTPError as e:
            # A bad token or a bad request will not get better by waiting.
            if e.code in (400, 401, 403, 404, 412):
                raise SystemExit(f"Return Prime refused the request: HTTP {e.code}") from None
            wait = float(e.headers.get("Retry-After") or 2 ** attempt)
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError):
            wait = 2 ** attempt
        print(f"  page {page}: attempt {attempt + 1} failed, retrying in {wait:.0f}s",
              file=sys.stderr)
        time.sleep(wait)
    raise SystemExit(f"page {page} failed after {retries} attempts")


def stage(rec: dict) -> str:
    """The furthest stage reached. An un-archived request is live again."""
    flag = lambda k: bool((rec.get(k) or {}).get("status"))  # noqa: E731
    if flag("rejected"):
        return "rejected"
    if flag("archived") and not flag("unarchived"):
        return "archived"
    for key in ("inspected", "received", "approved"):
        if flag(key):
            return key
    return rec.get("status") or "requested"


def _money(node: dict | None) -> float:
    """`{shop_money: {amount}}`, or 0 when the API leaves it empty."""
    try:
        return float(((node or {}).get("shop_money") or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def flatten(rec: dict) -> tuple[tuple, list[tuple]]:
    rid = rec["id"]
    order = rec.get("order") or {}
    address = (rec.get("customer") or {}).get("address") or {}
    items, qty, value, refunded = [], 0, 0.0, 0.0
    statuses = set()
    for it in rec.get("line_items") or []:
        price = it.get("shop_price") or {}
        refund = it.get("refund") or {}
        product = it.get("original_product") or {}
        ship = (it.get("shipping") or [{}])[0] or {}
        n = int(it.get("quantity") or 0)
        unit = float(price.get("actual_amount") or 0)
        disc = float(price.get("total_discount") or 0)
        line = (unit - disc) * n
        back = _money(refund.get("refunded_amount"))
        qty, value, refunded = qty + n, value + line, refunded + back
        if refund.get("status"):
            statuses.add(refund["status"])
        items.append((
            it.get("id"), rid, product.get("sku"), product.get("title"),
            product.get("variant_title"), n, unit, disc, price.get("total_tax"),
            round(line, 2), it.get("reason"), refund.get("status"),
            refund.get("actual_mode") or refund.get("requested_mode"),
            back, refund.get("refunded_at"),
            _money((it.get("return_fee") or {}).get("price_set")),
            ship.get("shipment_status"),
        ))
    at = lambda k: (rec.get(k) or {}).get("created_at")  # noqa: E731
    row = (
        rid, rec.get("request_number"), rec.get("request_type"), rec.get("status"),
        stage(rec), bool(rec.get("manual_request")),
        order.get("id"), order.get("name"), order.get("created_at"),
        address.get("province"), rec.get("created_at"), rec.get("updated_at"),
        at("approved"), at("received"), at("inspected"), at("rejected"),
        qty, round(value, 2), round(refunded, 2),
        # One word for the request: mixed when its lines disagree.
        (statuses.pop() if len(statuses) == 1 else "mixed") if statuses else None,
    )
    return row, items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=45,
                    help="Requests created in the last N days (default 45).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and count, write nothing.")
    args = ap.parse_args()

    from psycopg2.extras import execute_values

    tok = token()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"Return Prime returns created since {cutoff:%Y-%m-%d} ({args.days} days)")

    rows: dict[str, tuple] = {}
    items: list[tuple] = []
    for page in range(1, MAX_PAGES + 1):
        data = (fetch_page(tok, page).get("data") or {})
        batch = data.get("list") or []
        in_window = 0
        for rec in batch:
            created = datetime.fromisoformat(rec["created_at"].replace("Z", "+00:00"))
            if created < cutoff or rec.get("request_type") != "return":
                continue
            in_window += 1
            row, its = flatten(rec)
            # A request can repeat across pages when one is filed mid-walk.
            if row[0] not in rows:
                rows[row[0]] = row
                items.extend(its)
        if page % 10 == 0:
            print(f"  page {page}: {len(rows):,} returns so far")
        # Newest first: a page with nothing in the window ends the walk.
        if not batch or not in_window or not data.get("hasNextPage"):
            break

    print(f"Fetched: {len(rows):,} returns, {len(items):,} lines")
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    req_sql = _upsert_sql("return_prime_requests", REQUEST_COLS, ["id"])
    item_sql = _upsert_sql("return_prime_items", ITEM_COLS, ["item_id", "request_id"])
    all_rows = list(rows.values())
    with connect(autocommit=False, statement_timeout="120s") as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            conn.commit()
            for i in range(0, len(all_rows), CHUNK):
                execute_values(cur, req_sql, all_rows[i:i + CHUNK])
                conn.commit()
            for i in range(0, len(items), CHUNK):
                execute_values(cur, item_sql, items[i:i + CHUNK])
                conn.commit()
            cur.execute("SELECT count(*), min(created_at)::date, max(created_at)::date "
                        "FROM public.return_prime_requests")
            total, first, last = cur.fetchone()
            cur.execute("SELECT stage, count(*) FROM public.return_prime_requests "
                        "GROUP BY 1 ORDER BY 2 DESC")
            stages = cur.fetchall()

    print(f"\n[OK] {total:,} returns in public.return_prime_requests, {first} .. {last}")
    for name, n in stages:
        print(f"     {name:<10} {n:>7,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
