"""Turn raw webhook_events into tables you can actually query.

webhook_events is an append-only log: one row per delivery, payload
verbatim, nothing derived. That is right for custody and wrong for
answering questions. This folds it into three tables and marks each
source row processed.

    easyecom_shipments       one row per shipment, CURRENT state
    easyecom_returns         one row per credit note
    easyecom_return_items    one row per returned line

Plus a view, easyecom_delivery_attributed, joining shipments to
shopify_order_attribution so a delivery outcome carries the utm_term
and the ad that produced it.

Re-runnable. Default pass takes only rows with processed_at IS NULL;
--rebuild reprocesses the whole log, which is safe because every write
is an upsert keyed on EasyEcom's own ids.


GRAIN
-----
invoice_id. Verified against the live feed: 1,522 events resolve to
1,522 distinct invoiceId, awbNumber, suborder_id AND reference_code,
with no invoice carrying two AWBs and no AWB spanning two invoices.
order_id is deliberately NOT the key -- EasyEcom splits an order across
invoices (its own sample has one order arriving as three), so keying on
it would collapse separate shipments into one.

A shipment emits an event per status change, so the table keeps the
LATEST by last_status_update and the log keeps the trail.


STATUS
------
shipping_status_id is the key, not the label: ids are stable, the
strings are display text.

     19  Out For Pickup        in flight
      2  In Transit            in flight
     20  Out For Delivery      in flight
      3  Delivered             terminal, good
     16  Undelivered           a failed attempt, often retried
     17  RTO initiated         going back
      9  Delivered To Origin   terminal, bad -- it physically returned

An unknown id maps to 'unknown' and is counted rather than guessed at,
so a new EasyEcom status shows up as a number to look into instead of
being silently filed as in-flight.


WHAT IS NOT PROVEN YET
----------------------
No mark_return has arrived, so the return tables are built from
EasyEcom's documented payloads only. They are exercised by
tests/test_easyecom_events.py against those samples; the first real
delivery is what will confirm them.

Exchanges need `replacement_order`, which rides on mark_return and on
the order events. Until the Create Order trigger is enabled, an
exchange is visible as a return but its replacement leg is not.

Usage:
    ./.venv/bin/python scripts/refresh_easyecom_events.py
    ./.venv/bin/python scripts/refresh_easyecom_events.py --rebuild
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

DEST = os.environ["DATABASE_URL_SYNC"].replace(
    "postgresql+psycopg2://", "postgresql://").split("?")[0]

#: shipping_status_id -> (label, delivery_state). See the docstring.
STATUS = {
    19: ("Out For Pickup",      "in_flight"),
    2:  ("In Transit",          "in_flight"),
    20: ("Out For Delivery",    "in_flight"),
    3:  ("Delivered",           "delivered"),
    16: ("Undelivered",         "undelivered"),
    17: ("RTO initiated",       "rto_initiated"),
    9:  ("Delivered To Origin", "rto_returned"),
}

DDL = """
CREATE TABLE IF NOT EXISTS public.easyecom_shipments (
    invoice_id            bigint PRIMARY KEY,
    order_id              bigint,
    suborder_id           bigint,
    reference_code        text,
    order_name            text,
    awb_number            text,
    carrier_name          text,
    carrier_id            bigint,
    shipping_status_id    integer,
    shipping_status       text,
    delivery_state        text,
    is_delivered          boolean,
    is_rto                boolean,
    rto_returned          boolean,
    is_terminal           boolean,
    order_status          text,
    order_date            timestamptz,
    invoice_date          timestamptz,
    expected_delivery     timestamptz,
    status_updated_at     timestamptz,
    invoice_amount        double precision,
    tax                   double precision,
    city                  text,
    state                 text,
    location_key          text,
    event_count           integer NOT NULL DEFAULT 1,
    first_seen_at         timestamptz,
    last_seen_at          timestamptz,
    updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ees_ref    ON public.easyecom_shipments(reference_code);
CREATE INDEX IF NOT EXISTS ix_ees_name   ON public.easyecom_shipments(order_name);
CREATE INDEX IF NOT EXISTS ix_ees_state  ON public.easyecom_shipments(delivery_state);
CREATE INDEX IF NOT EXISTS ix_ees_awb2   ON public.easyecom_shipments(awb_number);
CREATE INDEX IF NOT EXISTS ix_ees_upd    ON public.easyecom_shipments(status_updated_at);

CREATE TABLE IF NOT EXISTS public.easyecom_returns (
    credit_note_id        bigint PRIMARY KEY,
    invoice_id            bigint,
    order_id              bigint,
    reference_code        text,
    order_name            text,
    credit_note_number    text,
    credit_note_date      timestamptz,
    return_date           date,
    return_type           text,
    replacement_order     integer,
    is_exchange           boolean,
    credit_note_amount    double precision,
    credit_note_tax       double precision,
    total_invoice_amount  double precision,
    payment_mode          text,
    marketplace           text,
    return_awb_number     text,
    reverse_carrier_name  text,
    order_date            timestamptz,
    location_key          text,
    updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_eer_inv  ON public.easyecom_returns(invoice_id);
CREATE INDEX IF NOT EXISTS ix_eer_name ON public.easyecom_returns(order_name);
CREATE INDEX IF NOT EXISTS ix_eer_date ON public.easyecom_returns(return_date);

CREATE TABLE IF NOT EXISTS public.easyecom_return_items (
    credit_note_id        bigint NOT NULL,
    suborder_id           bigint NOT NULL,
    invoice_id            bigint,
    sku                   text,
    product_name          text,
    category              text,
    returned_quantity     integer,
    return_reason         text,
    inventory_status      text,
    item_selling_price    double precision,
    credit_note_item_ex_tax double precision,
    mrp                   double precision,
    cost                  double precision,
    updated_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (credit_note_id, suborder_id)
);
CREATE INDEX IF NOT EXISTS ix_eeri_sku    ON public.easyecom_return_items(sku);
CREATE INDEX IF NOT EXISTS ix_eeri_reason ON public.easyecom_return_items(return_reason);
"""

# The payoff: a delivery outcome with the ad that caused it. Left joins
# throughout -- a shipment with no attribution is still a shipment, and
# dropping it would quietly understate every failure rate.
VIEW = """
CREATE OR REPLACE VIEW public.easyecom_delivery_attributed AS
SELECT s.invoice_id,
       s.order_name,
       s.reference_code,
       s.awb_number,
       s.carrier_name,
       s.delivery_state,
       s.shipping_status,
       s.is_delivered,
       s.is_rto,
       s.rto_returned,
       s.is_terminal,
       s.order_date,
       s.status_updated_at,
       s.invoice_amount,
       s.city,
       s.state,
       a.order_id            AS shopify_order_gid,
       a.utm_source,
       a.utm_medium,
       a.utm_campaign,
       a.utm_term,
       a.utm_content,
       a.matched_ad_name,
       a.matched_campaign_name,
       o.financial_status,
       -- COD is inferred, not known: Shopify leaves COD orders PENDING.
       -- Replace with easyecom payment_mode once Create Order is on.
       CASE WHEN o.financial_status = 'PENDING' THEN 'COD'
            WHEN o.financial_status IS NULL     THEN NULL
            ELSE 'Prepaid' END AS payment_type_inferred,
       r.credit_note_id,
       r.credit_note_amount,
       r.return_date,
       r.is_exchange
  FROM public.easyecom_shipments s
  LEFT JOIN public.shopify_order_attribution a
         ON regexp_replace(a.name, '\\D', '', 'g') = s.reference_code
  LEFT JOIN public.shopify_orders o  ON o.order_id = a.order_id
  LEFT JOIN public.easyecom_returns r ON r.invoice_id = s.invoice_id;
"""

ENVELOPE = ("orders", "credit_notes", "data")


def records(payload):
    """Yield every order-ish object, whatever the payload is wrapped in.

    Mirrors firstObject() in the edge function, but yields ALL records:
    a V1 envelope can carry several, and [[a, b]] is two returns, not
    one. Taking only the first would silently drop the rest."""
    def walk(node, depth=0):
        if depth > 5:
            return
        if isinstance(node, list):
            for x in node:
                yield from walk(x, depth + 1)
        elif isinstance(node, dict):
            key = next((k for k in ENVELOPE if isinstance(node.get(k), list)), None)
            if key:
                yield from walk(node[key], depth + 1)
            else:
                yield node
    yield from walk(payload)


BLANK = {None, "", "NA", "N/A", "null", "0000-00-00 00:00:00", "0000-00-00", "-"}


def _t(v):
    if v in BLANK:
        return None
    s = str(v).strip()
    return s or None


def _n(v):
    s = _t(v)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(v):
    f = _n(v)
    return None if f is None else int(f)


def _ts(v):
    s = _t(v)
    return s if s and s[:4].isdigit() else None


def _name(ref):
    """reference_code is the Shopify order name without the '#'."""
    s = _t(ref)
    return f"#{s}" if s and s.isdigit() else s


def shipment_row(r, seen_at):
    ssid = _i(r.get("shipping_status_id"))
    label, state = STATUS.get(ssid, (_t(r.get("currentShippingStatus")), "unknown"))
    return (
        _i(r.get("invoiceId")), _i(r.get("orderId")), _i(r.get("suborder_id")),
        _t(r.get("reference_code")), _name(r.get("reference_code")),
        _t(r.get("awbNumber")), _t(r.get("carrierName")), _i(r.get("carrier_id")),
        ssid, label or _t(r.get("currentShippingStatus")), state,
        state == "delivered",
        state in ("rto_initiated", "rto_returned"),
        state == "rto_returned",
        state in ("delivered", "rto_returned"),
        _t(r.get("orderStatus")),
        _ts(r.get("orderDate")), _ts(r.get("invoiceDate")),
        _ts(r.get("expectedDeliveryDate")), _ts(r.get("last_status_update")),
        _n(r.get("invoiceAmount")), _n(r.get("tax")),
        _t(r.get("city")), _t(r.get("state")), _t(r.get("location_key")),
        seen_at,
    )


SHIP_COLS = [
    "invoice_id", "order_id", "suborder_id", "reference_code", "order_name",
    "awb_number", "carrier_name", "carrier_id", "shipping_status_id",
    "shipping_status", "delivery_state", "is_delivered", "is_rto",
    "rto_returned", "is_terminal", "order_status", "order_date",
    "invoice_date", "expected_delivery", "status_updated_at",
    "invoice_amount", "tax", "city", "state", "location_key", "_seen",
]

# A shipment's events can arrive out of order, so a row is replaced only
# when the incoming status is genuinely newer. COALESCE on the incoming
# side keeps an older-but-populated value rather than nulling it.
SHIP_UPSERT = """
INSERT INTO public.easyecom_shipments (
    invoice_id, order_id, suborder_id, reference_code, order_name,
    awb_number, carrier_name, carrier_id, shipping_status_id,
    shipping_status, delivery_state, is_delivered, is_rto, rto_returned,
    is_terminal, order_status, order_date, invoice_date, expected_delivery,
    status_updated_at, invoice_amount, tax, city, state, location_key,
    event_count, first_seen_at, last_seen_at
) VALUES %s
ON CONFLICT (invoice_id) DO UPDATE SET
    order_id           = COALESCE(EXCLUDED.order_id, easyecom_shipments.order_id),
    suborder_id        = COALESCE(EXCLUDED.suborder_id, easyecom_shipments.suborder_id),
    reference_code     = COALESCE(EXCLUDED.reference_code, easyecom_shipments.reference_code),
    order_name         = COALESCE(EXCLUDED.order_name, easyecom_shipments.order_name),
    awb_number         = COALESCE(EXCLUDED.awb_number, easyecom_shipments.awb_number),
    carrier_name       = COALESCE(EXCLUDED.carrier_name, easyecom_shipments.carrier_name),
    carrier_id         = COALESCE(EXCLUDED.carrier_id, easyecom_shipments.carrier_id),
    order_date         = COALESCE(EXCLUDED.order_date, easyecom_shipments.order_date),
    invoice_date       = COALESCE(EXCLUDED.invoice_date, easyecom_shipments.invoice_date),
    invoice_amount     = COALESCE(EXCLUDED.invoice_amount, easyecom_shipments.invoice_amount),
    tax                = COALESCE(EXCLUDED.tax, easyecom_shipments.tax),
    city               = COALESCE(EXCLUDED.city, easyecom_shipments.city),
    state              = COALESCE(EXCLUDED.state, easyecom_shipments.state),
    location_key       = COALESCE(EXCLUDED.location_key, easyecom_shipments.location_key),
    event_count        = easyecom_shipments.event_count + EXCLUDED.event_count,
    first_seen_at      = LEAST(easyecom_shipments.first_seen_at, EXCLUDED.first_seen_at),
    last_seen_at       = GREATEST(easyecom_shipments.last_seen_at, EXCLUDED.last_seen_at),
    updated_at         = now(),
    shipping_status_id = CASE WHEN EXCLUDED.status_updated_at >= easyecom_shipments.status_updated_at
                              THEN EXCLUDED.shipping_status_id ELSE easyecom_shipments.shipping_status_id END,
    shipping_status    = CASE WHEN EXCLUDED.status_updated_at >= easyecom_shipments.status_updated_at
                              THEN EXCLUDED.shipping_status ELSE easyecom_shipments.shipping_status END,
    delivery_state     = CASE WHEN EXCLUDED.status_updated_at >= easyecom_shipments.status_updated_at
                              THEN EXCLUDED.delivery_state ELSE easyecom_shipments.delivery_state END,
    is_delivered       = CASE WHEN EXCLUDED.status_updated_at >= easyecom_shipments.status_updated_at
                              THEN EXCLUDED.is_delivered ELSE easyecom_shipments.is_delivered END,
    is_rto             = CASE WHEN EXCLUDED.status_updated_at >= easyecom_shipments.status_updated_at
                              THEN EXCLUDED.is_rto ELSE easyecom_shipments.is_rto END,
    rto_returned       = CASE WHEN EXCLUDED.status_updated_at >= easyecom_shipments.status_updated_at
                              THEN EXCLUDED.rto_returned ELSE easyecom_shipments.rto_returned END,
    is_terminal        = CASE WHEN EXCLUDED.status_updated_at >= easyecom_shipments.status_updated_at
                              THEN EXCLUDED.is_terminal ELSE easyecom_shipments.is_terminal END,
    order_status       = CASE WHEN EXCLUDED.status_updated_at >= easyecom_shipments.status_updated_at
                              THEN EXCLUDED.order_status ELSE easyecom_shipments.order_status END,
    expected_delivery  = CASE WHEN EXCLUDED.status_updated_at >= easyecom_shipments.status_updated_at
                              THEN EXCLUDED.expected_delivery ELSE easyecom_shipments.expected_delivery END,
    status_updated_at  = GREATEST(easyecom_shipments.status_updated_at, EXCLUDED.status_updated_at)
"""

RET_COLS = [
    "credit_note_id", "invoice_id", "order_id", "reference_code", "order_name",
    "credit_note_number", "credit_note_date", "return_date", "return_type",
    "replacement_order", "is_exchange", "credit_note_amount", "credit_note_tax",
    "total_invoice_amount", "payment_mode", "marketplace", "return_awb_number",
    "reverse_carrier_name", "order_date", "location_key",
]
ITEM_COLS = [
    "credit_note_id", "suborder_id", "invoice_id", "sku", "product_name",
    "category", "returned_quantity", "return_reason", "inventory_status",
    "item_selling_price", "credit_note_item_ex_tax", "mrp", "cost",
]


def return_rows(r):
    cn = _i(r.get("credit_note_id"))
    if cn is None:
        return None, []
    repl = _i(r.get("replacement_order"))
    head = (
        cn, _i(r.get("invoice_id")), _i(r.get("order_id")),
        _t(r.get("reference_code")), _name(r.get("reference_code")),
        _t(r.get("credit_note_number")), _ts(r.get("credit_note_date")),
        _ts(r.get("return_date")), _t(r.get("return_type")),
        repl, bool(repl),
        _n(r.get("credit_note_amount")), _n(r.get("credit_note_tax_amount")),
        _n(r.get("total_invoice_amount")), _t(r.get("payment_mode")),
        _t(r.get("marketplace")), _t(r.get("return_awb_number")),
        _t(r.get("reverse_carrier_name")), _ts(r.get("order_date")),
        _t(r.get("location_key")),
    )
    # V2 calls the line array order_items; V1 calls it items. The dict
    # guard matters: `items` on a TRACKING payload is a list of
    # formatted strings, and this must never try to read fields off one.
    items = []
    lines = (r.get("order_items") or r.get("return_items")
             or r.get("items") or [])
    for it in lines:
        if not isinstance(it, dict):
            continue
        sid = _i(it.get("suborder_id"))
        if sid is None:
            continue
        items.append((
            cn, sid, _i(r.get("invoice_id")),
            _t(it.get("sku")), _t(it.get("productName")), _t(it.get("category")),
            _i(it.get("returned_item_quantity")) or _i(it.get("returned_quantity")),
            _t(it.get("return_reason")), _t(it.get("inventory_status")),
            _n(it.get("total_item_selling_price")),
            _n(it.get("credit_note_total_item_excluding_tax")),
            _n(it.get("mrp")), _n(it.get("cost")),
        ))
    return head, items


def collapse(rows):
    """One row per invoice_id, newest status wins.

    A batch routinely holds several events for one shipment -- 110 of
    the first 1,522 had already moved through more than one status --
    and Postgres rejects a statement whose ON CONFLICT would touch the
    same row twice:

        CardinalityViolation: ON CONFLICT DO UPDATE command cannot
        affect row a second time

    Collapsing here rather than upserting one row at a time keeps the
    write batched. event_count carries the number folded in, so the
    running total stays right; first/last seen take the extremes.
    """
    INV, UPD, CNT, FIRST, LAST = 0, 19, 25, 26, 27
    best: dict[int, tuple] = {}
    for r in rows:
        k = r[INV]
        cur = best.get(k)
        if cur is None:
            best[k] = r
            continue
        # newest status_updated_at wins; None sorts oldest
        newer = (r[UPD] or "") >= (cur[UPD] or "")
        keep = list(r if newer else cur)
        keep[CNT] = cur[CNT] + r[CNT]
        keep[FIRST] = min(x for x in (cur[FIRST], r[FIRST]) if x is not None)
        keep[LAST] = max(x for x in (cur[LAST], r[LAST]) if x is not None)
        best[k] = tuple(keep)
    return list(best.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rebuild", action="store_true",
                    help="reprocess every row, not only unprocessed ones")
    ap.add_argument("--chunk", type=int, default=5000)
    args = ap.parse_args()

    t0 = time.time()
    db = psycopg2.connect(DEST)
    ships = rets = items = skipped = 0
    unknown: dict[int, int] = {}
    try:
        with db.cursor() as c:
            c.execute("SET statement_timeout = '900s'")
            c.execute(DDL)
            c.execute(VIEW)
        db.commit()

        where = "" if args.rebuild else "AND processed_at IS NULL"
        last = 0
        while True:
            with db.cursor() as c:
                c.execute(f"""SELECT id, event, payload, received_at
                                FROM public.webhook_events
                               WHERE source='easyecom' AND id > %s {where}
                               ORDER BY id LIMIT %s""", (last, args.chunk))
                batch = c.fetchall()
            if not batch:
                break

            ship_vals, ret_vals, item_vals, done = [], [], [], []
            for rid, event, payload, seen in batch:
                last, n_before = rid, len(ship_vals) + len(ret_vals)
                for rec in records(payload):
                    if event == "tracking" or "currentShippingStatus" in rec:
                        if _i(rec.get("invoiceId")) is None:
                            continue
                        row = shipment_row(rec, seen)
                        ssid = row[8]
                        if ssid is not None and ssid not in STATUS:
                            unknown[ssid] = unknown.get(ssid, 0) + 1
                        ship_vals.append(row[:-1] + (1, seen, seen))
                    elif "credit_note_id" in rec:
                        head, its = return_rows(rec)
                        if head:
                            ret_vals.append(head)
                            item_vals.extend(its)
                if len(ship_vals) + len(ret_vals) == n_before:
                    skipped += 1          # order/cancel/unknown: not folded yet
                done.append(rid)

            with db.cursor() as c:
                if ship_vals:
                    folded = collapse(ship_vals)
                    psycopg2.extras.execute_values(c, SHIP_UPSERT, folded, page_size=500)
                    ships += len(ship_vals)
                if ret_vals:
                    psycopg2.extras.execute_values(
                        c, "INSERT INTO public.easyecom_returns (" + ", ".join(RET_COLS)
                        + ") VALUES %s ON CONFLICT (credit_note_id) DO UPDATE SET "
                        + ", ".join(f"{k}=EXCLUDED.{k}" for k in RET_COLS[1:])
                        + ", updated_at=now()", ret_vals, page_size=500)
                    rets += len(ret_vals)
                if item_vals:
                    psycopg2.extras.execute_values(
                        c, "INSERT INTO public.easyecom_return_items (" + ", ".join(ITEM_COLS)
                        + ") VALUES %s ON CONFLICT (credit_note_id, suborder_id) DO UPDATE SET "
                        + ", ".join(f"{k}=EXCLUDED.{k}" for k in ITEM_COLS[2:])
                        + ", updated_at=now()", item_vals, page_size=500)
                    items += len(item_vals)
                c.execute("""UPDATE public.webhook_events SET processed_at = now()
                              WHERE id = ANY(%s)""", (done,))
            db.commit()
            print(f"  ...{last:>7}  ships={ships:,} returns={rets:,} "
                  f"items={items:,}  ({time.time()-t0:.0f}s)", flush=True)

        with db.cursor() as c:
            c.execute("""SELECT delivery_state, COUNT(*), COUNT(*) FILTER (WHERE is_terminal)
                           FROM public.easyecom_shipments GROUP BY 1 ORDER BY 2 DESC""")
            states = c.fetchall()
            c.execute("SELECT COUNT(*) FROM public.webhook_events WHERE processed_at IS NULL")
            pending = c.fetchone()[0]
    finally:
        db.close()

    print(f"\n[OK] in {time.time()-t0:.1f}s")
    print(f"    shipment events folded : {ships:,}")
    print(f"    returns / lines        : {rets:,} / {items:,}")
    print(f"    rows not folded        : {skipped:,}   (order/cancel events)")
    print(f"    still unprocessed      : {pending:,}")
    if unknown:
        print(f"    UNKNOWN shipping_status_id: {unknown}  <- add to STATUS")
    print("\n    shipments by state:")
    for s, n, term in states:
        print(f"      {str(s):<16} {n:>6,}   ({term:,} terminal)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
