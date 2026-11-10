#!/usr/bin/env python
"""Fill the Total sales breakdown columns on days already ingested.

WHY A SEPARATE SCRIPT
---------------------
`shopify_gross_sales`, `shopify_discounts`, `shopify_shipping`,
`shopify_return_fees`, `shopify_taxes`, `shopify_duties` and
`shopify_additional_fees` were added after the table had two months in
it, so every existing hour reads NULL for them and the dashboard's
breakdown has nothing to draw.

Re-running `fetch_hourly_tracker.py` over those days would fill them,
but it would also re-pull Meta, GA4 and every order of every day to
rewrite forty other columns that are already correct -- and on this
store that has twice now overwritten good data with a worse snapshot.
This touches ONLY the seven new columns, with `fetch_sales` doing the
reading, so there is one definition of what the breakdown means.

The two identities are checked per day before anything is written:

    gross + discounts + returns                 = net sales
    net + shipping + return fees + taxes
        + duties + additional fees              = total sales

Both sides come from the same ShopifyQL row, so a mismatch means the
dataset changed shape, not that a day is odd -- the day is reported and
skipped rather than written half-right.

Usage:
    ./.venv/bin/python scripts/backfill_sales_breakdown.py            # every NULL day
    ./.venv/bin/python scripts/backfill_sales_breakdown.py --days 7
    ./.venv/bin/python scripts/backfill_sales_breakdown.py --from 2026-09-16 --to 2026-11-10
    ./.venv/bin/python scripts/backfill_sales_breakdown.py --all --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from scripts.dbq import connect  # noqa: E402
from scripts.fetch_hourly_tracker import (  # noqa: E402
    MIGRATIONS, TABLE, fetch_sales,
)

#: The columns added for the breakdown, and the only ones whose
#: migrations this script is allowed to run.
NEW_COLS = ("shopify_gross_sales", "shopify_discounts", "shopify_shipping",
            "shopify_return_fees", "shopify_taxes", "shopify_duties",
            "shopify_additional_fees")

#: THE WHOLE RECONCILING SET IS WRITTEN, not just the new columns.
#:
#: The three older ones -- total sales, returns and net sales -- are on
#: the far side of the two identities, and on a day still running they
#: move between one read and the next. Writing only the new columns
#: left today's gross from this minute sitting beside a headline from
#: the last hourly run, the identity short by the sales made in
#: between, and the dashboard (rightly) refusing to draw a breakdown
#: that does not add up.
#:
#: Safe because all ten come from ONE ShopifyQL row of the same query
#: the hourly ingest runs: on a settled day a later read is identical,
#: and on a live one it is strictly newer. Nothing outside this set is
#: touched -- the order-derived columns beside it answer a different
#: question and are none of this script's business.
UPDATE = f"""
UPDATE {TABLE} SET
  shopify_gross_sales = %s, shopify_discounts = %s, shopify_shipping = %s,
  shopify_return_fees = %s, shopify_taxes = %s, shopify_duties = %s,
  shopify_additional_fees = %s,
  shopify_total_sales = %s, shopify_returns = %s, ql_net_sales = %s
WHERE hour = %s
"""

#: Rupee. Both identities are exact to the paisa on every day checked,
#: so this is a guard against a changed dataset, not a tolerance.
EPS = 1.0


def _targets(args) -> list[date]:
    """Which days to pull, oldest first."""
    with connect() as conn, conn.cursor() as cur:
        if args.from_day or args.to_day:
            lo = args.from_day or date(2000, 1, 1)
            hi = args.to_day or date.today()
            cur.execute(f"SELECT DISTINCT day_ist FROM {TABLE} "
                        "WHERE day_ist BETWEEN %s AND %s ORDER BY 1", (lo, hi))
        elif args.days:
            cur.execute(f"SELECT DISTINCT day_ist FROM {TABLE} "
                        "WHERE day_ist > (now() AT TIME ZONE 'Asia/Kolkata')::date - %s "
                        "ORDER BY 1", (args.days,))
        elif args.all:
            cur.execute(f"SELECT DISTINCT day_ist FROM {TABLE} ORDER BY 1")
        else:
            # The default: any day whose reconciling set is INCOMPLETE,
            # not merely absent.
            #
            # "Has no gross yet" was the first version of this and it
            # was too narrow twice over. A day can carry gross and be
            # missing `ql_net_sales` (2026-10-28 was), or carry the new
            # columns and be missing the headline they have to reach
            # (every day before Total sales was stored). Either way the
            # two identities cannot close and the dashboard draws
            # nothing -- so the test is per COLUMN, per hour.
            #
            # count(col) < count(*) rather than a sum compared against
            # a sum: a column that is NULL for every hour of a day sums
            # to NULL, and `NULL > 1` is NULL, so a HAVING written that
            # way silently drops exactly the days that need this most.
            cols = ", ".join(f"count({c}) < count(*)" for c in
                             (*NEW_COLS, "shopify_total_sales",
                              "shopify_returns", "ql_net_sales"))
            cur.execute(f"SELECT day_ist FROM {TABLE} GROUP BY day_ist "
                        f"HAVING {cols.replace(', ', ' OR ')} ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


async def pull(days: list[date]) -> tuple[list[tuple], list[str]]:
    import httpx  # noqa: PLC0415

    from shopify_client import discover_stores  # noqa: PLC0415

    stores = discover_stores()
    if not stores:
        raise SystemExit("No Shopify store configured -- check .env")
    store = list(stores.values())[0]

    rows: list[tuple] = []
    problems: list[str] = []
    async with httpx.AsyncClient() as client:
        for day in days:
            try:
                hours = await fetch_sales(client, store, day)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{day}: fetch failed: {type(exc).__name__}: {exc}")
                continue
            kept = 0
            for hour, h in sorted(hours.items()):
                gross = h["shopify_gross_sales"]
                disc = h["shopify_discounts"]
                rets = h["shopify_returns"]
                net = h["ql_net_sales"]
                tail = (h["shopify_shipping"] + h["shopify_return_fees"]
                        + h["shopify_taxes"] + h["shopify_duties"]
                        + h["shopify_additional_fees"])
                total = h["shopify_total_sales"]
                if abs((gross + disc + rets) - net) > EPS:
                    problems.append(
                        f"{day} {hour:%H:%M}: gross+discounts+returns does not "
                        f"reach net sales -- off by {(gross + disc + rets) - net:,.2f}")
                    continue
                if abs((net + tail) - total) > EPS:
                    problems.append(
                        f"{day} {hour:%H:%M}: net+shipping+fees+taxes does not "
                        f"reach total sales -- off by {(net + tail) - total:,.2f}")
                    continue
                rows.append((gross, disc, h["shopify_shipping"],
                             h["shopify_return_fees"], h["shopify_taxes"],
                             h["shopify_duties"], h["shopify_additional_fees"],
                             total, rets, net, hour))
                kept += 1
            print(f"  {day}  {kept:2d} hours  gross {sum(h['shopify_gross_sales'] for h in hours.values()):>14,.2f}")
    return rows, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=None,
                    help="trailing N days instead of every unfilled day")
    ap.add_argument("--from", dest="from_day", type=date.fromisoformat, default=None)
    ap.add_argument("--to", dest="to_day", type=date.fromisoformat, default=None)
    ap.add_argument("--all", action="store_true",
                    help="every day in the table, filled or not")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # The columns have to exist before the days can be looked up by
    # them. Only the ALTERs this script's columns need -- the rest of
    # the ingest's migrations are its own business.
    alters = [m for m in MIGRATIONS if any(c in m for c in NEW_COLS)]
    if len(alters) != len(NEW_COLS):
        raise SystemExit("fetch_hourly_tracker.MIGRATIONS is missing a "
                         "breakdown column -- the two have drifted apart.")
    with connect(autocommit=False) as conn:
        with conn.cursor() as cur:
            for stmt in alters:
                cur.execute(stmt)
        conn.commit()

    days = _targets(args)
    if not days:
        print("Nothing to do: every day already has a breakdown.")
        return 0
    print(f"{len(days)} day(s): {days[0]} .. {days[-1]}")

    rows, problems = asyncio.run(pull(days))

    if problems:
        print(f"\n{len(problems)} hour(s) skipped -- the breakdown did not reconcile:")
        for p in problems[:20]:
            print(f"  {p}")
        if len(problems) > 20:
            print(f"  ... and {len(problems) - 20} more")
    if not rows:
        print("\nNothing written.")
        return 1
    print(f"\n{len(rows):,} hours ready.")
    if args.dry_run:
        print("--dry-run: nothing written.")
        return 0

    import psycopg2.extras  # noqa: PLC0415
    with connect(autocommit=False, statement_timeout="600s") as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, UPDATE, rows, page_size=200)
            written = cur.rowcount
        conn.commit()
    print(f"[OK] {len(rows):,} hours updated "
          f"(last statement touched {written} row(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
