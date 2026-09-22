"""How many ads carry correct Shopify orders/sales, and against what?

Ads Analyse builds its Shopify columns as

    COALESCE(ext.shopify_orders, soa.shopify_orders, 0)

where `ext` is public.ad_metrics_external (mirrored from the legacy
Meta_ads_data project) and `soa` is this project's own cascade over
shopify_order_attribution. Two attribution systems with very different
coverage feed one column, row by row, so "some ads look wrong" can mean
several different things.

This script settles which. For every ad it compares three numbers:

    legacy   shopify_ad_agg on the source (the reference the business
             already reconciles against -- 100% of its orders carry an
             ad id)
    ext      what we mirrored from it, and what Ads Analyse actually
             shows when present
    ours     what this project's cascade resolves today

and classifies each ad:

    exact          ours == legacy
    under          ours < legacy   -- our cascade missed orders
    over           ours > legacy   -- we credit orders legacy does not
    no_legacy      legacy has no row (ad never sold, or predates it)
    ext_stale      ext disagrees with legacy -- the mirror is out of date

Read-only. Touches the local database and, for the legacy figures,
SUPABASE_DB_URL.

Usage:
    ./.venv/bin/python scripts/check_shopify_attribution_coverage.py
    ./.venv/bin/python scripts/check_shopify_attribution_coverage.py --limit 20
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402


def _dsn(raw: str) -> str:
    return (raw.replace("postgresql+psycopg2://", "postgresql://")
               .replace("postgresql+asyncpg://", "postgresql://")
               .split("?")[0])


LOCAL_SQL = """
SELECT g.ad_id,
       COALESCE(g.ad_name, '')                AS ad_name,
       COALESCE(g.spend, 0)                   AS spend,
       e.shopify_orders                       AS ext_orders,
       e.shopify_revenue                      AS ext_revenue,
       COALESCE(s.orders, 0)                  AS our_orders,
       COALESCE(s.revenue, 0)                 AS our_revenue
  FROM public.ad_performance_summary g
  LEFT JOIN public.ad_metrics_external e ON e.ad_id = g.ad_id
  LEFT JOIN (
      SELECT matched_ad_id AS ad_id,
             COUNT(*)      AS orders,
             SUM(total_price) AS revenue
        FROM public.shopify_order_attribution
       WHERE matched_ad_id IS NOT NULL
       GROUP BY matched_ad_id
  ) s ON s.ad_id = g.ad_id
"""

LEGACY_SQL = "SELECT ad_id, shopify_orders, shopify_sales FROM public.shopify_ad_agg"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=12,
                    help="How many worst-gap ads to list (default 12).")
    args = ap.parse_args()

    local_raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    legacy_raw = os.environ.get("SUPABASE_DB_URL")
    if not local_raw:
        print("DATABASE_URL_SYNC is not set.", file=sys.stderr)
        return 2

    legacy: dict[str, tuple[float, float]] = {}
    if legacy_raw:
        with psycopg2.connect(_dsn(legacy_raw)) as lc, lc.cursor() as cur:
            cur.execute(LEGACY_SQL)
            legacy = {r[0]: (float(r[1] or 0), float(r[2] or 0)) for r in cur.fetchall()}
        print(f"legacy shopify_ad_agg: {len(legacy):,} ads")
    else:
        print("SUPABASE_DB_URL not set -- comparing against ext only.")

    with psycopg2.connect(_dsn(local_raw)) as c, c.cursor() as cur:
        cur.execute(LOCAL_SQL)
        rows = cur.fetchall()
    print(f"local ad_performance_summary: {len(rows):,} ads\n")

    buckets: dict[str, int] = {}
    orders = {"legacy": 0.0, "ext": 0.0, "ours": 0.0}
    gaps: list[tuple[float, str, str, float, float, float]] = []
    ext_stale = 0

    for ad_id, ad_name, spend, ext_o, ext_r, our_o, our_r in rows:
        leg_o, _leg_r = legacy.get(ad_id, (None, None))
        our_o = float(our_o or 0)
        ext_o_f = None if ext_o is None else float(ext_o)

        orders["ours"] += our_o
        if ext_o_f is not None:
            orders["ext"] += ext_o_f
        if leg_o is not None:
            orders["legacy"] += leg_o

        # Is the mirror keeping up with its own source?
        if leg_o is not None and ext_o_f is not None and abs(leg_o - ext_o_f) > 0.5:
            ext_stale += 1

        if leg_o is None:
            key = "no_legacy_row"
        elif abs(our_o - leg_o) < 0.5:
            key = "exact"
        elif our_o < leg_o:
            key = "under_attributed"
            gaps.append((leg_o - our_o, ad_id, ad_name, leg_o, our_o,
                         float(ext_o_f or 0)))
        else:
            key = "over_attributed"
            gaps.append((our_o - leg_o, ad_id, ad_name, leg_o, our_o,
                         float(ext_o_f or 0)))
        buckets[key] = buckets.get(key, 0) + 1

    total = len(rows)
    print(f"{'bucket':<20}{'ads':>9}{'share':>9}")
    for key in ("exact", "under_attributed", "over_attributed", "no_legacy_row"):
        n = buckets.get(key, 0)
        print(f"{key:<20}{n:>9,}{n * 100 / max(total, 1):>8.1f}%")

    print(f"\nads whose legacy row exists at all        : "
          f"{total - buckets.get('no_legacy_row', 0):,}")
    print(f"ext disagrees with its own legacy source  : {ext_stale:,}")
    print("\ntotal Shopify orders credited to ads:")
    for k in ("legacy", "ext", "ours"):
        print(f"   {k:<8}{orders[k]:>14,.0f}")
    if orders["legacy"]:
        print(f"\n   our coverage vs legacy: "
              f"{orders['ours'] * 100 / orders['legacy']:.1f}%")

    if gaps:
        gaps.sort(reverse=True)
        print(f"\nworst {args.limit} gaps (legacy vs ours):")
        print(f"   {'ad_id':<21}{'legacy':>9}{'ours':>9}{'ext':>9}  ad_name")
        for _d, ad_id, ad_name, leg_o, our_o, ext_o_f in gaps[:args.limit]:
            print(f"   {ad_id:<21}{leg_o:>9,.0f}{our_o:>9,.0f}{ext_o_f:>9,.0f}  {ad_name[:38]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
