"""Export the unmatched utm_content values as a fill-in-the-blank sheet.

The cascade refuses to guess when a name is ambiguous or absent, which
leaves a finite worklist: for each unresolved utm_content, which ad did
it actually come from? This writes that list in exactly the shape
scripts/load_ad_name_overrides.py reads back, so the loop is:

    export -> fill the ad_name (or ad_id) column -> load -> re-attribute

Columns are ordered so the two that need filling come first, and rows
are ordered by orders lost, so the top of the file is where the money
is. `candidates` lists ads whose name is close enough to be worth
checking -- a suggestion to verify, never something applied on its own.

Usage:
    ./.venv/bin/python scripts/export_utm_worklist.py --days 30
    ./.venv/bin/python scripts/export_utm_worklist.py --days 90 --out data/worklist.tsv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import difflib
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.database.session import session_scope, dispose_engine  # noqa: E402
from app.services.silver import shopify_ad_attribution as A  # noqa: E402

#: Tiers that did NOT resolve to a specific ad. These are the rows a
#: human can still rescue; everything else is already attributed.
UNRESOLVED = ("adset_name_miss", "campaign_only", "unmatched")

SQL = """
SELECT COALESCE(o.utm_content, '')  AS utm_content,
       COALESCE(o.utm_term, '')     AS utm_term,
       a.tier                       AS tier,
       COUNT(*)                     AS orders,
       COALESCE(SUM(o.total_price), 0)::float AS sales
  FROM shopify_order_attribution a
  JOIN shopify_orders o USING (order_id)
 WHERE a.created_at >= :since
   AND a.tier = ANY(:tiers)
   AND COALESCE(o.utm_content, '') <> ''
   -- An unrendered macro is an ads-team fix, not a mapping decision.
   AND o.utm_content NOT LIKE '%%{{%%'
 GROUP BY 1, 2, 3
HAVING COUNT(*) >= :min_orders
 ORDER BY COUNT(*) DESC
"""

HEADER = ["utm_content", "ad_name", "ad_id", "adset_id", "adset_name",
          "tier", "orders", "sales", "candidates"]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30, help="Window size (default 30).")
    ap.add_argument("--min-orders", type=int, default=1,
                    help="Skip values below this many orders (default 1).")
    ap.add_argument("--tiers", default=",".join(UNRESOLVED),
                    help=f"Tiers to export (default {','.join(UNRESOLVED)}).")
    ap.add_argument("--out", default=None, help="Output path (default data/utm_worklist_<date>.tsv).")
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]

    async with session_scope() as session:
        universe = await A._load_ad_universe(session)
        rows = (await session.execute(
            text(SQL), {"since": since, "tiers": tiers, "min_orders": args.min_orders}
        )).all()
    await dispose_engine()

    live_names = sorted({a.ad_name for a in universe.by_id.values() if a.ad_name})
    out_path = Path(args.out) if args.out else (
        ROOT / "data" / f"utm_worklist_{date.today().isoformat()}.tsv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(HEADER)
        for r in rows:
            adset_id = r.utm_term.strip()
            adset_name = ""
            if adset_id in universe.roster_adsets:
                adset_name = universe.roster_adsets[adset_id][1] or ""
            ads = universe.adset_ads.get(adset_id, [])

            # Prefer candidates from the very ad set the click came from:
            # those need no cross-ad-set judgement at all.
            pool = [a.ad_name for a in ads if a.ad_name] or live_names
            close = difflib.get_close_matches(r.utm_content, pool, n=3, cutoff=0.6)
            w.writerow([r.utm_content, "", "", adset_id, adset_name,
                        r.tier, r.orders, f"{r.sales:.0f}", " | ".join(close)])
            written += 1

    total_orders = sum(r.orders for r in rows)
    total_sales = sum(r.sales for r in rows)
    print(f"{written:,} unresolved utm_content value(s) over {args.days} days")
    print(f"   {total_orders:,} orders, Rs {total_sales:,.0f}")
    print(f"   -> {out_path}")
    print("\nFill in ad_name (or ad_id where a name is ambiguous), then:")
    print(f"   ./.venv/bin/python scripts/load_ad_name_overrides.py --file {out_path} --dry-run")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
