"""Pull EasyEcom's order book into this database.

EasyEcom sits behind the sales channels and holds the one thing neither
Shopify nor Meta can tell us: what happened to the parcel AFTER the
order was counted. Shipped, returned, cancelled, which courier, which
AWB, COD or prepaid. That is the input to the RTO correction -- the
36% gap between revenue the dashboard reports and revenue that was
actually collected.

    GET https://api.easyecom.io/orders/V2/getAllOrders
        ?start_date=YYYY-MM-DD HH:MM:SS
        &end_date=YYYY-MM-DD HH:MM:SS
    x-api-key:     <account key>
    Authorization: Bearer <jwt>      scripts/mint_easyecom_jwt.py

Both headers are mandatory; either one missing is a flat 401 "Invalid
Api token." Paged by an opaque cursor returned as data.nextUrl, followed
until it stops coming back.

The window and the token's location_key are the ONLY things that decide
which orders come back -- V2.1 getAllOrders has no marketplace
parameter. A channel that appears to be missing is usually one of those
two, not a broken key. See mint_easyecom_jwt.py.


THE GRAIN IS invoice_id, NOT order_id
-------------------------------------
One EasyEcom order splits into several invoices, each with its own
status and its own money. In EasyEcom's own sample, order_id 143576499
arrives three times (Open / Cancelled / Open) and 143578420 twice
(Open 474.91 / Cancelled 231.36). SUM(total_amount) GROUP BY order_id
therefore double counts, which is the same failure that made
raw_dump_meta report 7.31x the real spend. invoice_id is the primary
key here for that reason, and any revenue figure has to decide
explicitly which invoices of an order it means.

Line grain is suborder_id. suborder_num is NOT unique -- the same
suborder_num shows up under two different suborder_ids when an order is
re-invoiced.


THE TYPES ARE NOT STABLE
------------------------
This is a loosely typed JSON API and the same field changes type
between rows:

    "Package Weight"  2      and  "2"        (and the key has a space
                                              and capitals)
    suborder_count    1      and  "NA"
    customer_code     95265  and  "NA"
    invoice_date      ""     rather than null

So every value goes through a coercer. "NA" and "" both mean absent and
both become NULL, the way GoKwik's literal 'NA' UTMs had to be
normalised before they stopped counting as data.

order_status_id does not agree with order_status: one sample row is
Cancelled with order_status_id 2, which is Open elsewhere. Trust the
string.


CUSTOMER PII IS DELIBERATELY NOT COPIED
---------------------------------------
The payload carries customer_name, contact_num, email, both address
lines, pin_code, lat/long and the billing block. None of it is needed
to correct ROAS for returns, this repo is public, and copying it would
widen its exposure for no gain. City and state do come across, because
RTO varies sharply by region. This follows ingest_gokwik_orders.py.

The verbatim order object is kept in `raw` minus those fields, so a
mis-mapped column can be recovered without re-fetching.

Usage:
    # answer "what marketplaces are even in here" without writing
    ./.venv/bin/python scripts/ingest_easyecom_orders.py --probe \
        --since 2026-08-01 --until 2026-09-25

    # real ingest (run it in the background, it is a paged API)
    ./.venv/bin/python scripts/ingest_easyecom_orders.py \
        --since 2026-01-01 --until 2026-09-25
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

DEST = os.environ["DATABASE_URL_SYNC"].replace(
    "postgresql+psycopg2://", "postgresql://").split("?")[0]

BASE = "https://api.easyecom.io"
FIRST = "/orders/V2/getAllOrders"

#: Dropped before `raw` is stored, and never given a column. See the
#: PII note in the module docstring.
PII = (
    "customer_name", "contact_num", "email", "address_line_1",
    "address_line_2", "pin_code", "latitude", "longitude",
    "billing_name", "billing_address_1", "billing_address_2",
    "billing_mobile", "billing_pin_code",
    # presigned links to the customer's own invoice PDFs
    "documents",
)

DDL = """
CREATE TABLE IF NOT EXISTS public.easyecom_orders (
    invoice_id              bigint PRIMARY KEY,
    order_id                bigint,
    reference_code          text,
    reference_base          text,
    marketplace             text,
    marketplace_id          integer,
    order_type              text,
    replacement_order       integer,
    order_date              timestamptz,
    import_date             timestamptz,
    invoice_date            timestamptz,
    last_update_date        timestamptz,
    manifest_date           timestamptz,
    delivery_date           timestamptz,
    order_status            text,
    order_status_id         integer,
    shipping_status         text,
    shipping_status_id      integer,
    payment_mode            text,
    courier                 text,
    courier_aggregator_name text,
    awb_number              text,
    invoice_number          text,
    order_quantity          integer,
    total_amount            double precision,
    total_tax               double precision,
    total_shipping_charge   double precision,
    total_discount          double precision,
    collectable_amount      double precision,
    city                    text,
    state                   text,
    country                 text,
    warehouse_id            integer,
    location_key            text,
    raw                     jsonb,
    ingested_at             timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ee_order      ON public.easyecom_orders(order_id);
CREATE INDEX IF NOT EXISTS ix_ee_refbase    ON public.easyecom_orders(reference_base);
CREATE INDEX IF NOT EXISTS ix_ee_orderdate  ON public.easyecom_orders(order_date);
CREATE INDEX IF NOT EXISTS ix_ee_market     ON public.easyecom_orders(marketplace);
CREATE INDEX IF NOT EXISTS ix_ee_status     ON public.easyecom_orders(order_status);
CREATE INDEX IF NOT EXISTS ix_ee_awb        ON public.easyecom_orders(awb_number);

CREATE TABLE IF NOT EXISTS public.easyecom_suborders (
    suborder_id         bigint PRIMARY KEY,
    invoice_id          bigint NOT NULL,
    order_id            bigint,
    suborder_num        text,
    item_status         text,
    shipment_type       text,
    suborder_quantity   integer,
    item_quantity       integer,
    shipped_quantity    integer,
    returned_quantity   integer,
    cancelled_quantity  integer,
    sku                 text,
    marketplace_sku     text,
    product_name        text,
    product_id          bigint,
    category            text,
    brand               text,
    size                text,
    selling_price       double precision,
    tax                 double precision,
    tax_rate            double precision,
    cost                double precision,
    mrp                 double precision,
    ingested_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ees_invoice ON public.easyecom_suborders(invoice_id);
CREATE INDEX IF NOT EXISTS ix_ees_sku     ON public.easyecom_suborders(sku);
CREATE INDEX IF NOT EXISTS ix_ees_status  ON public.easyecom_suborders(item_status);
"""

ORDER_COLS = [
    "invoice_id", "order_id", "reference_code", "reference_base",
    "marketplace", "marketplace_id", "order_type", "replacement_order",
    "order_date", "import_date", "invoice_date", "last_update_date",
    "manifest_date", "delivery_date",
    "order_status", "order_status_id", "shipping_status", "shipping_status_id",
    "payment_mode", "courier", "courier_aggregator_name", "awb_number",
    "invoice_number", "order_quantity",
    "total_amount", "total_tax", "total_shipping_charge", "total_discount",
    "collectable_amount",
    "city", "state", "country", "warehouse_id", "location_key", "raw",
]

SUB_COLS = [
    "suborder_id", "invoice_id", "order_id", "suborder_num", "item_status",
    "shipment_type", "suborder_quantity", "item_quantity", "shipped_quantity",
    "returned_quantity", "cancelled_quantity",
    "sku", "marketplace_sku", "product_name", "product_id", "category",
    "brand", "size", "selling_price", "tax", "tax_rate", "cost", "mrp",
]

#: Anything in this set means "no value", whatever the declared type.
BLANK = {None, "", "NA", "na", "N/A", "null", "0000-00-00 00:00:00",
         "0000-00-00", "-"}


def _txt(v):
    if v in BLANK:
        return None
    s = str(v).strip()
    return s or None


def _num(v):
    s = _txt(v)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(v):
    f = _num(v)
    return None if f is None else int(f)


def _ts(v):
    """Timestamps arrive as 'YYYY-MM-DD HH:MM:SS', or as '' for absent."""
    s = _txt(v)
    if s is None:
        return None
    return s if re.match(r"^\d{4}-\d{2}-\d{2}", s) else None


def _ref_base(code):
    """Strip EasyEcom's re-invoice suffix.

    A split or re-issued order gets the marketplace's reference with
    _OR1 / _RE1 appended ("Test_12" -> "Test_12_OR1"), so the bare
    reference is what joins back to the sales channel. Deliberately NOT
    reduced to digits: that turns "Test_12_OR1" into "121".
    """
    s = _txt(code)
    if s is None:
        return None
    return re.sub(r"_(OR|RE)\d+$", "", s, flags=re.I)


def flatten(o: dict) -> tuple[tuple, list[tuple]]:
    inv = _int(o.get("invoice_id"))
    oid = _int(o.get("order_id"))

    keep = {k: v for k, v in o.items() if k not in PII and k != "suborders"}

    row = (
        inv, oid,
        _txt(o.get("reference_code")), _ref_base(o.get("reference_code")),
        _txt(o.get("marketplace")), _int(o.get("marketplace_id")),
        _txt(o.get("order_type")), _int(o.get("replacement_order")),
        _ts(o.get("order_date")), _ts(o.get("import_date")),
        _ts(o.get("invoice_date")), _ts(o.get("last_update_date")),
        _ts(o.get("manifest_date")), _ts(o.get("delivery_date")),
        _txt(o.get("order_status")), _int(o.get("order_status_id")),
        _txt(o.get("shipping_status")), _int(o.get("shipping_status_id")),
        _txt(o.get("payment_mode")), _txt(o.get("courier")),
        _txt(o.get("courier_aggregator_name")), _txt(o.get("awb_number")),
        _txt(o.get("invoice_number")), _int(o.get("order_quantity")),
        _num(o.get("total_amount")), _num(o.get("total_tax")),
        _num(o.get("total_shipping_charge")), _num(o.get("total_discount")),
        _num(o.get("collectable_amount")),
        _txt(o.get("city")), _txt(o.get("state")), _txt(o.get("country")),
        _int(o.get("warehouseId")), _txt(o.get("location_key")),
        json.dumps(keep, ensure_ascii=False),
    )

    subs = []
    for s in (o.get("suborders") or []):
        subs.append((
            _int(s.get("suborder_id")), inv, oid,
            _txt(s.get("suborder_num")), _txt(s.get("item_status")),
            _txt(s.get("shipment_type")),
            _int(s.get("suborder_quantity")), _int(s.get("item_quantity")),
            _int(s.get("shipped_quantity")), _int(s.get("returned_quantity")),
            _int(s.get("cancelled_quantity")),
            _txt(s.get("sku")), _txt(s.get("marketplace_sku")),
            _txt(s.get("productName")), _int(s.get("product_id")),
            _txt(s.get("category")), _txt(s.get("brand")), _txt(s.get("size")),
            _num(s.get("selling_price")), _num(s.get("tax")),
            _num(s.get("tax_rate")), _num(s.get("cost")), _num(s.get("mrp")),
        ))
    return row, subs


def fetch(path: str, key: str, jwt: str | None, *, tries: int = 4) -> dict:
    """One page. The cursor in nextUrl is opaque and already encoded, so
    it is appended verbatim -- re-quoting it corrupts the '/' inside."""
    url = BASE + path
    headers = {"x-api-key": key, "Accept": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"

    for attempt in range(1, tries + 1):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = (e.read().decode(errors="replace") or "")[:400]
            if e.code in (401, 403):
                raise SystemExit(
                    f"[auth] HTTP {e.code} from EasyEcom.\n  {body}\n"
                    "  EasyEcom needs BOTH headers -- x-api-key AND a\n"
                    "  Bearer JWT. Mint the JWT (valid 90 days) with:\n"
                    "      ./.venv/bin/python scripts/mint_easyecom_jwt.py"
                )
            if e.code == 429 or e.code >= 500:
                if attempt == tries:
                    raise SystemExit(f"[http] HTTP {e.code} after {tries} tries\n  {body}")
                wait = 5 * attempt
                print(f"  HTTP {e.code}, retrying in {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise SystemExit(f"[http] HTTP {e.code}\n  {body}")
        except (TimeoutError, urllib.error.URLError) as e:
            if attempt == tries:
                raise SystemExit(f"[net] {e}")
            time.sleep(5 * attempt)
    raise SystemExit("[http] unreachable")


def census(orders: list[dict]) -> None:
    """What is actually in the account. This is the output that answers
    'why do I only see Amazon' -- it is a fact about the data, not about
    the endpoint, which returns every marketplace it has."""
    def show(title, c):
        print(f"\n  {title}")
        for k, n in c.most_common():
            print(f"    {str(k):<28} {n:>7,}")

    show("marketplace", Counter(o.get("marketplace") or "(none)" for o in orders))
    show("order_status", Counter(o.get("order_status") or "(none)" for o in orders))
    show("payment_mode", Counter(o.get("payment_mode") or "(none)" for o in orders))
    show("location_key", Counter(o.get("location_key") or "(none)" for o in orders))

    ids = Counter(o.get("order_id") for o in orders)
    dupes = sum(1 for n in ids.values() if n > 1)
    print(f"\n  rows                      {len(orders):>7,}")
    print(f"  distinct order_id         {len(ids):>7,}")
    print(f"  order_ids with >1 invoice {dupes:>7,}"
          "   <- summing total_amount by order_id double counts these")
    with_awb = sum(1 for o in orders if _txt(o.get("awb_number")))
    with_del = sum(1 for o in orders if _ts(o.get("delivery_date")))
    print(f"  with awb_number           {with_awb:>7,}")
    print(f"  with delivery_date        {with_del:>7,}"
          "   <- RTO work needs this populated")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", required=True, help="YYYY-MM-DD")
    ap.add_argument("--until", required=True, help="YYYY-MM-DD")
    ap.add_argument("--probe", action="store_true",
                    help="fetch one page, print a census, write nothing")
    ap.add_argument("--max-pages", type=int, default=0, help="0 = all")
    ap.add_argument("--sleep", type=float, default=0.4,
                    help="pause between pages, to stay under the rate limit")
    args = ap.parse_args()

    key = os.environ.get("EASYECOM_API_KEY")
    jwt = os.environ.get("EASYECOM_JWT")
    if not key:
        print("EASYECOM_API_KEY is not set in .env", file=sys.stderr)
        return 2

    q = urllib.parse.urlencode({
        "start_date": f"{args.since} 00:00:00",
        "end_date": f"{args.until} 23:59:59",
    })
    path = f"{FIRST}?{q}"

    t0 = time.time()
    seen: list[dict] = []
    pages = 0
    dest = None
    n_ord = n_sub = 0

    if not args.probe:
        dest = psycopg2.connect(DEST)
        with dest.cursor() as c:
            c.execute("SET statement_timeout = '1800s'")
            c.execute(DDL)
        dest.commit()

    try:
        while path:
            body = fetch(path, key, jwt)
            if body.get("code") not in (200, None):
                print(f"[api] code={body.get('code')} "
                      f"message={body.get('message')!r}", file=sys.stderr)
                return 1

            data = body.get("data") or {}
            orders = data.get("orders") or []
            pages += 1

            if args.probe:
                seen.extend(orders)
            elif orders:
                rows, subs = [], []
                for o in orders:
                    r, s = flatten(o)
                    if r[0] is None:          # no invoice_id, no primary key
                        continue
                    rows.append(r)
                    subs.extend(t for t in s if t[0] is not None)

                # Upsert, not rebuild. The API is queried by window, but
                # an order's status keeps changing after it -- Shipped
                # becomes Returned weeks later. A swap would drop every
                # invoice outside the window.
                with dest.cursor() as c:
                    psycopg2.extras.execute_values(
                        c,
                        "INSERT INTO public.easyecom_orders ("
                        + ", ".join(ORDER_COLS) + ") VALUES %s "
                        "ON CONFLICT (invoice_id) DO UPDATE SET "
                        + ", ".join(f"{k}=EXCLUDED.{k}" for k in ORDER_COLS[1:])
                        + ", ingested_at=now()",
                        rows, page_size=500,
                    )
                    if subs:
                        psycopg2.extras.execute_values(
                            c,
                            "INSERT INTO public.easyecom_suborders ("
                            + ", ".join(SUB_COLS) + ") VALUES %s "
                            "ON CONFLICT (suborder_id) DO UPDATE SET "
                            + ", ".join(f"{k}=EXCLUDED.{k}" for k in SUB_COLS[1:])
                            + ", ingested_at=now()",
                            subs, page_size=500,
                        )
                dest.commit()
                n_ord += len(rows)
                n_sub += len(subs)
                print(f"  page {pages:>4}  {n_ord:>7,} invoices  "
                      f"{n_sub:>7,} lines  ({time.time() - t0:>5.0f}s)",
                      flush=True)

            nxt = data.get("nextUrl")
            if not nxt or not orders:
                break
            if args.probe or (args.max_pages and pages >= args.max_pages):
                break
            path = nxt if nxt.startswith("/") else "/" + nxt
            time.sleep(args.sleep)
    finally:
        if dest is not None:
            dest.close()

    if args.probe:
        print(f"\n[probe] {args.since} -> {args.until}, page 1 of the feed")
        if not seen:
            print("  no orders returned for this window at all.\n"
                  "  That is the most common reason a marketplace looks\n"
                  "  'missing' -- check the dates before the credentials.")
            return 0
        census(seen)
        print("\n  top-level keys present:")
        keys = sorted({k for o in seen for k in o})
        print("    " + ", ".join(keys))
        return 0

    print(f"\n[OK] easyecom orders ingested in {time.time() - t0:.1f}s")
    print(f"    pages            : {pages}")
    print(f"    invoices upserted: {n_ord:,}")
    print(f"    lines upserted   : {n_sub:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
