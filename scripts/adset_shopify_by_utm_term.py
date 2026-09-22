"""Shopify orders and sales per ad set, mapped on `utm_term`.

WHY utm_term RATHER THAN THE MATCHED AD
---------------------------------------
`utm_term` IS the Meta ad set id -- verified against the roster: of 850
distinct numeric values, 842 are real `adset_id`s, 0 are ad ids and 0
are campaign ids. It is written at click time by the ad set the click
actually came from, so it needs no matching step at all and cannot be
wrong about which ad set was involved.

The Ads Analyse rollup currently resolves ad-set Shopify figures the
long way round:

    JOIN public.meta_ads m ON m.ad_id = a.matched_ad_id

which only counts an order if the cascade first resolved an AD, and then
credits whichever ad set that ad belongs to. Measured over
2026-01-01..09-22 the two disagree on 272 of 842 shared ad sets, net
-7,300 orders: the ad join over-assigns, because an order whose
utm_content names an ad living in a different ad set gets credited
there rather than where the click came from. The account-wide override
mappings do this deliberately ("orders from ad set A naming an ad in
B"), so the drift is by construction, not a bug in the overrides.

Both readings are defensible; they answer different questions. This one
answers "which ad set did this click come from", which is what an
ad-set row should say.

TWO FILTERS THAT ARE NOT OPTIONAL
---------------------------------
  * META ONLY. The cascade indexes the Meta ad universe, and non-Meta
    traffic carries its own values in utm_term -- Google Ads puts the
    KEYWORD/criterion id there, which is a 12-digit number that looks
    like an id and is not one. Without this filter `148136693402`
    (5,496 orders) and `150646720953` (1,869) appear as if they were
    ad sets.
  * KNOWN AD SETS ONLY. utm_term also carries literal junk on some
    orders -- `cta` (1,238 orders), base64-ish tokens, campaign names.
    Requiring the value to exist in `meta_adsets` drops all of it.

Usage:
    ./.venv/bin/python scripts/adset_shopify_by_utm_term.py
    ./.venv/bin/python scripts/adset_shopify_by_utm_term.py --from 2026-01-01 --to 2026-09-22
    ./.venv/bin/python scripts/adset_shopify_by_utm_term.py --limit 50 --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402

#: Same family test the analytics router's `_classify_channel` uses, so
#: "Meta" means the same thing here as it does on the dashboard.
META_SOURCE = r"(meta|facebook|fb|instagram|ig)"

QUERY = f"""
SELECT a.utm_term                                   AS adset_id,
       s.adset_name,
       s.campaign_name,
       COUNT(*)                                     AS shopify_orders,
       COALESCE(SUM(a.total_price), 0)              AS shopify_sales,
       COALESCE(SUM(a.total_price), 0) / NULLIF(COUNT(*), 0) AS aov,
       COUNT(*) FILTER (WHERE a.matched_ad_id IS NOT NULL)   AS also_matched_to_an_ad,
       MIN(a.created_at)::date                      AS first_order,
       MAX(a.created_at)::date                      AS last_order
  FROM public.shopify_order_attribution a
  JOIN public.meta_adsets s ON s.adset_id = a.utm_term
 WHERE a.utm_term IS NOT NULL AND BTRIM(a.utm_term) <> ''
   AND LOWER(COALESCE(a.utm_source, '')) ~ '{META_SOURCE}'
   AND (CAST(%(from_date)s AS date) IS NULL OR a.created_at >= CAST(%(from_date)s AS date))
   AND (CAST(%(to_date)s   AS date) IS NULL OR a.created_at <  CAST(%(to_date)s AS date) + 1)
 GROUP BY a.utm_term, s.adset_name, s.campaign_name
 ORDER BY shopify_sales DESC
"""

TOTALS = f"""
SELECT COUNT(DISTINCT a.utm_term)   AS adsets,
       COUNT(*)                     AS orders,
       COALESCE(SUM(a.total_price), 0) AS sales
  FROM public.shopify_order_attribution a
  JOIN public.meta_adsets s ON s.adset_id = a.utm_term
 WHERE a.utm_term IS NOT NULL AND BTRIM(a.utm_term) <> ''
   AND LOWER(COALESCE(a.utm_source, '')) ~ '{META_SOURCE}'
   AND (CAST(%(from_date)s AS date) IS NULL OR a.created_at >= CAST(%(from_date)s AS date))
   AND (CAST(%(to_date)s   AS date) IS NULL OR a.created_at <  CAST(%(to_date)s AS date) + 1)
"""

#: What the filters removed, so the number is auditable rather than
#: merely smaller than the unfiltered one.
EXCLUDED = f"""
SELECT
  COUNT(*) FILTER (WHERE LOWER(COALESCE(utm_source,'')) !~ '{META_SOURCE}')        AS non_meta_source,
  COUNT(*) FILTER (WHERE LOWER(COALESCE(utm_source,'')) ~ '{META_SOURCE}'
                     AND NOT EXISTS (SELECT 1 FROM public.meta_adsets s
                                      WHERE s.adset_id = shopify_order_attribution.utm_term)) AS meta_unknown_adset,
  COUNT(*) FILTER (WHERE COALESCE(BTRIM(utm_term),'') = '')                        AS blank_utm_term
  FROM public.shopify_order_attribution
 WHERE (CAST(%(from_date)s AS date) IS NULL OR created_at >= CAST(%(from_date)s AS date))
   AND (CAST(%(to_date)s   AS date) IS NULL OR created_at <  CAST(%(to_date)s AS date) + 1)
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="from_date", default="2026-01-01")
    ap.add_argument("--to", dest="to_date", default=None)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--csv", help="Write every row to this file as well.")
    args = ap.parse_args()
    params = {"from_date": args.from_date, "to_date": args.to_date}

    dsn = (os.environ["DATABASE_URL_SYNC"]
           .replace("postgresql+psycopg2://", "postgresql://").split("?")[0])
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = '600s'")
        cur.execute(TOTALS, params)
        adsets, orders, sales = cur.fetchone()
        cur.execute(EXCLUDED, params)
        non_meta, unknown, blank = cur.fetchone()
        cur.execute(QUERY, params)
        rows = cur.fetchall()

    win = f"{args.from_date or 'start'} .. {args.to_date or 'today'}"
    print(f"Meta-sourced Shopify orders by AD SET (utm_term), {win}\n")
    print(f"  ad sets {adsets:>7,}   orders {orders:>9,}   sales Rs{sales:>14,.0f}")
    print(f"  excluded: {non_meta:,} non-Meta source, {unknown:,} Meta rows whose "
          f"utm_term is not a known ad set, {blank:,} with no utm_term\n")

    print(f"  {'adset_id':<21}{'orders':>8}{'sales':>14}{'AOV':>8}{'w/ad':>7}  ad set / campaign")
    for aid, aname, cname, n, rev, aov, matched, _f, _l in rows[:args.limit]:
        print(f"  {aid:<21}{n:>8,}{rev:>14,.0f}{aov:>8,.0f}{matched:>7,}  "
              f"{(aname or '?')[:30]}  |  {(cname or '?')[:24]}")
    if len(rows) > args.limit:
        print(f"  ... and {len(rows) - args.limit:,} more ad sets")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["adset_id", "adset_name", "campaign_name", "shopify_orders",
                        "shopify_sales", "aov", "also_matched_to_an_ad",
                        "first_order", "last_order"])
            w.writerows(rows)
        print(f"\n  wrote {len(rows):,} rows to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
