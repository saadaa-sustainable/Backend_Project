"""Print one order's whole life, from checkout to whatever ended it.

Four sources, one timeline:

    shopify_orders / shopify_order_attribution   placed, paid, the ad
    webhook_events  tracking                     each courier movement
    webhook_events  cancel_order / mark_return   how it ended
    easyecom_order_history (inside order events) EasyEcom's own trail

Accepts whichever id you have. They are not interchangeable and looking
up the wrong one in the wrong system returns nothing, which reads as
missing data and is not -- see docs/easyecom_webhooks.md:

    #1542926 / 1542926   Shopify order name, and EasyEcom's
                         reference_code. THE ONLY ID THAT CROSSES.
    621950008            EasyEcom order_id, internal
    744713615            EasyEcom invoice_id, internal

Usage:
    ./.venv/bin/python scripts/order_journey.py 1542926
    ./.venv/bin/python scripts/order_journey.py '#1542926'
    ./.venv/bin/python scripts/order_journey.py 621950008
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402

DEST = os.environ["DATABASE_URL_SYNC"].replace(
    "postgresql+psycopg2://", "postgresql://").split("?")[0]

# Flatten any payload shape to its records: [{}], [[{}]], {"orders":[{}]}.
FLATTEN = """
  CROSS JOIN LATERAL jsonb_array_elements(
      CASE jsonb_typeof(e.payload) WHEN 'array' THEN e.payload
           ELSE jsonb_build_array(COALESCE(e.payload->'orders',
                                           e.payload->'credit_notes',
                                           e.payload)) END) l1
  CROSS JOIN LATERAL jsonb_array_elements(
      CASE jsonb_typeof(l1) WHEN 'array' THEN l1 ELSE jsonb_build_array(l1) END) rec
"""


def resolve(cur, token: str) -> str | None:
    """Work out the reference_code from whatever the user typed."""
    digits = re.sub(r"\D", "", token)
    if not digits:
        return None
    # An EasyEcom internal id? Translate it to the reference_code.
    cur.execute(f"""SELECT DISTINCT rec->>'reference_code'
                      FROM public.webhook_events e {FLATTEN}
                     WHERE rec->>'order_id'   = %s OR rec->>'orderId'   = %s
                        OR rec->>'invoice_id' = %s OR rec->>'invoiceId' = %s
                     LIMIT 1""", (digits,) * 4)
    row = cur.fetchone()
    return row[0] if row and row[0] else digits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("order", help="Shopify name, reference_code, order_id or invoice_id")
    args = ap.parse_args()

    db = psycopg2.connect(DEST)
    cur = db.cursor()
    cur.execute("SET statement_timeout = '120s'")

    ref = resolve(cur, args.order)
    if not ref:
        print(f"'{args.order}' has no digits in it."); return 2
    name = f"#{ref}"
    print(f"\n{'='*72}\nORDER {name}   (EasyEcom reference_code {ref})\n{'='*72}")

    # 1. checkout ------------------------------------------------------
    cur.execute("""SELECT o.name, o.order_id, o.financial_status,
                          a.utm_source, a.utm_medium, a.utm_term,
                          a.matched_ad_name, a.matched_campaign_name
                     FROM public.shopify_order_attribution a
                     LEFT JOIN public.shopify_orders o ON o.order_id = a.order_id
                    WHERE regexp_replace(a.name,'\\D','','g') = %s LIMIT 1""", (ref,))
    s = cur.fetchone()
    print("\n-- CHECKOUT (Shopify) " + "-"*50)
    if not s:
        print("   not found in shopify_order_attribution")
    else:
        print(f"   shopify id        {s[1]}")
        print(f"   financial_status  {s[2]}    ({'COD' if s[2]=='PENDING' else 'prepaid'} by inference)")
        print(f"   utm               {s[3]} / {s[4]} / term={s[5]}")
        print(f"   ad                {s[6]}")
        print(f"   campaign          {s[7]}")

    # 2. what EasyEcom knows about the order itself --------------------
    cur.execute(f"""SELECT e.event, e.received_at, rec
                      FROM public.webhook_events e {FLATTEN}
                     WHERE rec->>'reference_code' = %s
                       AND e.event NOT IN ('tracking')
                     ORDER BY e.id""", (ref,))
    orders = cur.fetchall()

    print("\n-- ORDER / FULFILMENT (EasyEcom) " + "-"*39)
    if not orders:
        print("   no order-level event yet (Create Order trigger is off;")
        print("   cancel_order and mark_return only fire when they happen)")
    for ev, at, rec in orders:
        print(f"   [{ev}] received {at:%d %b %H:%M:%S}")
        for k in ("order_id", "invoice_id", "payment_mode", "order_status",
                  "total_amount", "collectable_amount", "return_type",
                  "credit_note_amount", "replacement_order", "originalOrderId"):
            if rec.get(k) is not None:
                print(f"       {k:<20} {rec[k]}")
        for it in (rec.get("order_items") or []):
            if not isinstance(it, dict):
                continue
            tags = [c.get("field_value") for c in (it.get("custom_fields") or [])]
            print(f"       line  {it.get('sku')}  qty={it.get('item_quantity') or it.get('suborder_quantity')}"
                  f"  sell={it.get('selling_price')}  cost={it.get('cost')}")
            if tags:
                print(f"             tags: {', '.join(str(t) for t in tags)}")
            if it.get("return_reason"):
                print(f"             reason: {it['return_reason']}  qc={it.get('inventory_status')}")
        for h in (rec.get("easyecom_order_history") or []):
            print(f"       history  {h.get('date_time')}  {h.get('status')}")

    # 3. the courier ---------------------------------------------------
    cur.execute(f"""SELECT rec->>'last_status_update', rec->>'currentShippingStatus',
                           rec->>'shipping_status_id', rec->>'awbNumber',
                           rec->>'carrierName', rec->>'expectedDeliveryDate',
                           rec->>'invoiceAmount', e.received_at
                      FROM public.webhook_events e {FLATTEN}
                     WHERE rec->>'reference_code' = %s AND e.event='tracking'
                     ORDER BY rec->>'last_status_update'""", (ref,))
    tr = cur.fetchall()
    print("\n-- COURIER (tracking) " + "-"*50)
    if not tr:
        print("   no tracking event -- not shipped, or shipped before the webhook was on")
    else:
        print(f"   awb {tr[0][3]} via {tr[0][4]}   expected {tr[0][5]}")
        seen = set()
        for upd, st, sid, _awb, _car, _edd, amt, got in tr:
            if (upd, st) in seen:
                continue
            seen.add((upd, st))
            print(f"     {upd}   {str(st):<22} (id {sid})   webhook +{got:%H:%M:%S}")

    # 4. the settled view ----------------------------------------------
    cur.execute("""SELECT delivery_state, is_terminal, invoice_amount, event_count,
                          first_seen_at, status_updated_at
                     FROM public.easyecom_shipments WHERE reference_code = %s""", (ref,))
    sh = cur.fetchone()
    cur.execute("""SELECT return_type, return_date, credit_note_amount, payment_mode,
                          is_exchange FROM public.easyecom_returns WHERE reference_code = %s""", (ref,))
    rt = cur.fetchone()
    print("\n-- OUTCOME " + "-"*61)
    if sh:
        print(f"   delivery_state    {sh[0]}   terminal={sh[1]}   after {sh[3]} event(s)")
        print(f"   invoice_amount    Rs {sh[2]:,.0f}" if sh[2] else "")
    if rt:
        print(f"   RETURN            {rt[0]} on {rt[1]}   credit note Rs {rt[2]:,.0f}"
              f"   {rt[3]}   exchange={rt[4]}")
    if not sh and not rt:
        print("   nothing settled yet")
    print()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
