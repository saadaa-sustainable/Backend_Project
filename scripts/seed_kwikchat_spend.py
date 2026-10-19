"""Kwikchat spend, per day. A PLACEHOLDER until the real figures land.

WHY THIS EXISTS AT ALL
----------------------
Kwikchat is the third D2C channel in the media plan's spend block, and
the only one of the three this warehouse cannot source. Meta comes from
the Insights API, Google from the MapleMonk BigQuery export; Kwikchat
has no feed here.

Leaving it out is not neutral. Every figure that divides by spend reads
HIGH without it, always in the flattering direction. Measured over
September 2026:

    spend                     MER     A-MER    Blended CAC
    Meta + Google             3.58x   2.10x    Rs 530.71
    + Kwikchat at 30k/day     3.35x   1.96x    Rs 567.05
    media plan's own figure   3.22x   1.89x    Rs 588.52

So an explicit, labelled estimate lands closer to the truth than a
silent omission does.

WHY 30,000 A DAY
----------------
Given as an interim figure, to be replaced when the real data arrives.
It is NOT an attempt to reproduce the media plan's own Kwikchat row:
that row runs Rs 40k-87k a day across 2026 and carries a comment from
the team saying "Please change this data, this is incorrect", so it is
not a number to anchor on either.

WHY A TABLE AND NOT A CONSTANT
------------------------------
Because this has to be easy to kill. A constant in the endpoint would
be invisible at the point of use, would need a code change and a deploy
to correct, and would quietly outlive the assumption. A row carries
`is_estimate`, so:

  * the endpoints can count estimated days in the window and the UI can
    say so on the face of the card;
  * real figures overwrite the same primary key and flip the flag,
    with no code change at all;
  * `SELECT ... WHERE is_estimate` answers "what are we still guessing"
    at any time.

Usage:
    ./.venv/bin/python scripts/seed_kwikchat_spend.py
    ./.venv/bin/python scripts/seed_kwikchat_spend.py --daily 45000
    ./.venv/bin/python scripts/seed_kwikchat_spend.py --from 2026-01-01 --to 2026-10-19
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402

DEFAULT_DAILY = 30000.0

DDL = """
CREATE TABLE IF NOT EXISTS public.kwikchat_spend_daily (
    day         date    NOT NULL PRIMARY KEY,
    -- Rupees, same unit as insights_daily_by_ad.spend and
    -- google_ads_spend_daily.spend, so the three add without conversion.
    spend       numeric NOT NULL DEFAULT 0,
    -- TRUE while this is the flat placeholder. Real figures set it
    -- FALSE, and every consumer counts the TRUE rows in its window so
    -- a reader is never shown an assumption without being told.
    is_estimate boolean NOT NULL DEFAULT true,
    source      text,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_kwikchat_spend_daily_estimate
    ON public.kwikchat_spend_daily(is_estimate);
"""

#: Only ever overwrites a row that is ITSELF an estimate. Once a real
#: figure lands for a day, re-running this script leaves it alone --
#: otherwise the placeholder would silently undo the real data every
#: time somebody re-seeded a range.
UPSERT = """
INSERT INTO public.kwikchat_spend_daily (day, spend, is_estimate, source, fetched_at)
VALUES (%s, %s, true, %s, now())
ON CONFLICT (day) DO UPDATE SET
  spend = EXCLUDED.spend,
  source = EXCLUDED.source,
  fetched_at = EXCLUDED.fetched_at
WHERE public.kwikchat_spend_daily.is_estimate
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--daily", type=float, default=DEFAULT_DAILY,
                    help=f"Rupees per day (default {DEFAULT_DAILY:,.0f}).")
    ap.add_argument("--from", dest="from_date", default="2026-01-01",
                    help="First day (default 2026-01-01, where shopify_sales_daily starts).")
    ap.add_argument("--to", dest="to_date", default=None, help="Last day (default today).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lo = date.fromisoformat(args.from_date)
    hi = date.fromisoformat(args.to_date) if args.to_date else date.today()
    days = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
    note = f"placeholder {args.daily:,.0f}/day"

    print(f"Kwikchat spend placeholder: Rs {args.daily:,.0f}/day")
    print(f"Range:  {lo} .. {hi}  ({len(days):,} days, Rs {args.daily * len(days):,.0f} total)")
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    with connect(autocommit=False, statement_timeout="120s") as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.executemany(UPSERT, [(d, args.daily, note) for d in days])
            cur.execute("SELECT count(*) FILTER (WHERE is_estimate), count(*) "
                        "FROM public.kwikchat_spend_daily")
            est, total = cur.fetchone()
        conn.commit()

    print(f"\n[OK] {total:,} rows in public.kwikchat_spend_daily, {est:,} still estimated")
    if est:
        print("     Replace with real figures by UPDATEing those days and "
              "setting is_estimate = false.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
