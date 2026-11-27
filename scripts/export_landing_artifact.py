#!/usr/bin/env python
"""Dump the landing-page tracker as flat JSON for the Claude artifact.

The artifact is a page on claude.ai, so it cannot call this machine's
API: the browser would be going from https to a private address, which
mixed-content and private-network rules both refuse. The data therefore
travels as files that get re-uploaded, which is what makes this a
script rather than a fetch in the page.

Run it after refresh_hourly_landing.py; it only reads.

    .venv/bin/python scripts/export_landing_artifact.py --days 2
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.dbq import connect  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))

#: Top pages only. Every page would be ~1,200 rows of fifteen columns
#: for a table nobody scrolls past the first screen of, and the file is
#: re-uploaded every hour.
PAGE_LIMIT = 40

MEASURES = """
       COALESCE(SUM(sessions), 0)               AS sessions,
       COALESCE(SUM(visitors), 0)               AS visitors,
       COALESCE(SUM(bounces), 0)                AS bounces,
       COALESCE(SUM(cart_additions), 0)         AS cart_additions,
       COALESCE(SUM(orders), 0)                 AS orders,
       COALESCE(SUM(revenue), 0)                AS revenue,
       COALESCE(SUM(new_customer_sales), 0)     AS new_customer_sales,
       COALESCE(SUM(repeat_customer_sales), 0)  AS repeat_customer_sales,
       COALESCE(SUM(meta_spend), 0)             AS meta_spend,
       COALESCE(SUM(order_spend), 0)            AS order_spend,
       COALESCE(SUM(meta_conv_value), 0)        AS meta_conv_value,
       COALESCE(SUM(ncp), 0)                    AS ncp
"""


def rows(cur, sql, params):
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    out = []
    for r in cur.fetchall():
        d = {}
        for k, v in zip(cols, r):
            d[k] = float(v) if hasattr(v, "quantize") else v
        out.append(d)
    return out


def rate(part, whole):
    return round(part / whole, 4) if whole else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--out", default=str(ROOT / "exports" / "artifact"))
    args = ap.parse_args()

    hi_day = datetime.now(IST).date()
    lo_day = hi_day - timedelta(days=args.days - 1)
    lo = datetime.combine(lo_day, datetime.min.time(), IST)
    hi = datetime.combine(hi_day + timedelta(days=1), datetime.min.time(), IST)
    bounds = {"lo": lo, "hi": hi, "lo_day": lo_day, "hi_day": hi_day}

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with connect() as conn, conn.cursor() as cur:
        src = rows(cur, f"""
            SELECT source, {MEASURES}
              FROM public.hourly_landing_tracker
             WHERE hour >= %(lo)s AND hour < %(hi)s
             GROUP BY source ORDER BY 2 DESC""", bounds)

        pages = rows(cur, f"""
            SELECT landing_page_path AS page, {MEASURES}
              FROM public.hourly_landing_tracker
             WHERE hour >= %(lo)s AND hour < %(hi)s
             GROUP BY landing_page_path
             ORDER BY SUM(revenue) DESC NULLS LAST, SUM(sessions) DESC
             LIMIT {PAGE_LIMIT}""", bounds)

        hours = rows(cur, f"""
            SELECT EXTRACT(HOUR FROM hour AT TIME ZONE 'Asia/Kolkata')::int AS hour_of_day,
                   {MEASURES}
              FROM public.hourly_landing_tracker
             WHERE hour >= %(lo)s AND hour < %(hi)s
             GROUP BY 1 ORDER BY 1""", bounds)

        store = rows(cur, """
            SELECT COALESCE(SUM(total_sales), 0) AS total_sales,
                   COALESCE(SUM(gross_sales), 0) AS gross_sales,
                   COALESCE(SUM(orders), 0)      AS store_orders,
                   MAX(refreshed_at)             AS refreshed_at
              FROM public.landing_store_totals
             WHERE day >= %(lo_day)s AND day <= %(hi_day)s""", bounds)[0]

        spend = rows(cur, """
            SELECT COALESCE(SUM(meta_spend), 0) AS all_spend
              FROM public.hourly_campaign_tracker
             WHERE hour >= %(lo)s AND hour < %(hi)s""", bounds)[0]

        fresh = rows(cur, """
            SELECT MAX(orders_refreshed_at) AS orders_at
              FROM public.hourly_landing_tracker
             WHERE hour >= %(lo)s AND hour < %(hi)s""", bounds)[0]

    # Rates computed from summed counts, never averaged across rows.
    for r in src + pages + hours:
        r["bounce_rate"] = rate(r["bounces"], r["sessions"])
        r["atc_rate"] = rate(r["cart_additions"], r["sessions"])
        r["rev_per_session"] = round(r["revenue"] / r["sessions"], 2) if r["sessions"] else None
        # ROAS only against order_spend: that is the only one of the two
        # spend figures keyed the same way as the revenue beside it.
        r["roas"] = round(r["revenue"] / r["order_spend"], 2) if r["order_spend"] else None

    tot = {k: sum(r[k] for r in src) for k in
           ("sessions", "visitors", "orders", "revenue", "new_customer_sales",
            "repeat_customer_sales", "meta_spend", "order_spend",
            "meta_conv_value", "ncp", "bounces", "cart_additions")}
    tot["bounce_rate"] = rate(tot["bounces"], tot["sessions"])
    tot["atc_rate"] = rate(tot["cart_additions"], tot["sessions"])
    tot["store_total_sales"] = store["total_sales"]
    tot["store_gross_sales"] = store["gross_sales"]
    tot["store_orders"] = store["store_orders"]
    tot["all_spend"] = spend["all_spend"]
    tot["spend_share"] = rate(tot["meta_spend"], spend["all_spend"])
    tot["order_spend_share"] = rate(tot["order_spend"], spend["all_spend"])
    tot["from_day"] = lo_day.isoformat()
    tot["to_day"] = hi_day.isoformat()
    tot["orders_refreshed_at"] = (fresh["orders_at"].isoformat()
                                  if fresh["orders_at"] else None)
    tot["exported_at"] = datetime.now(timezone.utc).isoformat()

    for name, payload in (("sources", src), ("pages", pages),
                          ("hours", hours), ("totals", [tot])):
        path = out / f"{name}.json"
        path.write_text(json.dumps(payload, separators=(",", ":"), default=str))
        print(f"  {path.name:<13} {len(payload):>5} rows  {path.stat().st_size / 1024:6.1f} KB")

    print(f"window {lo_day} .. {hi_day} | {tot['sessions']:,.0f} sessions | "
          f"{tot['orders']:,.0f} orders | store total {tot['store_total_sales']:,.0f}")


if __name__ == "__main__":
    main()
