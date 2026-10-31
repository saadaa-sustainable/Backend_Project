"""Google Ads daily campaign metrics, straight from the API.

WHY, WHEN MAPLEMONK ALREADY LANDS THIS
--------------------------------------
Spend is not the reason. Checked day by day against the API on
2026-10-21, MapleMonk's spend is exact: 28 of 30 days to the rupee,
Rs 1,159,946 against Rs 1,159,942 over the month, 0.0003% apart.

CONVERSIONS are the reason. Google keeps attributing for days after the
fact, and MapleMonk's copy is a snapshot of whatever had landed when it
synced. Over the same 30 days its conversion VALUE was short by Rs
39,332, and all of it sat in the most recent eight days:

    2026-10-12 and earlier   exact, every day
    2026-10-13   +788        2026-10-17   +7,504
    2026-10-15   +4,321      2026-10-19   +6,366
    2026-10-16   +2,443      2026-10-20  +17,076

That is the shape of a conversion lag, not a sync bug -- and it falls
hardest on the newest days, which are the ones anybody is looking at.
Re-reading a trailing window from the API lets those days settle.

The API is also a day fresher (21 Oct against MapleMonk's 20 Oct) and
does not depend on an Airbyte connector that has already died once --
`Saadaa_Google_ads_Product_Level_Stream` stopped syncing 2025-11-21 and
nobody noticed for eleven months.

WHOLE ROWS, NOT JUST CONVERSIONS
--------------------------------
It would be possible to update only the conversion columns and leave
MapleMonk's spend. That is worse: a row would then mix two sources
measured at different moments, and `conv_value / spend` across the seam
would not be any one system's number. One source per row, marked in
`source`, and the rows stay internally consistent.

THE FIELD TRAP
--------------
`metrics.conversions_value` is PRIMARY conversion actions only, and is
what the media plan and `meta.conv_value` are comparable with.
`metrics.all_conversions_value` counts every secondary action and read
Rs 456,427,216 against Rs 7,053,096 over the same 30 days -- 65x. Using
it would put a fictional number into Platform MER.

Usage:
    ./.venv/bin/python scripts/fetch_google_ads_api.py
    ./.venv/bin/python scripts/fetch_google_ads_api.py --days 90
    ./.venv/bin/python scripts/fetch_google_ads_api.py --from 2026-01-01 --to 2026-10-21
    ./.venv/bin/python scripts/fetch_google_ads_api.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg2.extras  # noqa: E402

from scripts.dbq import connect as db_connect  # noqa: E402
from scripts.google_ads_auth import GoogleAdsAuthError, connect as ads_connect  # noqa: E402

#: 30 days by default. Conversions were still moving 8 days back when
#: measured, so a shorter window would freeze days that are not final;
#: a much longer one re-reads history that has not changed in months.
DEFAULT_DAYS = 30

#: `source` distinguishes an API row from MapleMonk's. The table is
#: created by scripts/fetch_google_ads_spend.py with CREATE TABLE IF NOT
#: EXISTS, so a new column needs its own ALTER -- the DDL will not add
#: it to a table that already exists.
MIGRATIONS = [
    "ALTER TABLE public.google_ads_spend_daily "
    "  ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'maplemonk'",
]

GAQL = """
SELECT campaign.id,
       campaign.name,
       campaign.status,
       campaign.advertising_channel_type,
       segments.date,
       metrics.cost_micros,
       metrics.clicks,
       metrics.impressions,
       metrics.conversions,
       metrics.conversions_value
FROM campaign
WHERE segments.date BETWEEN '{since}' AND '{until}'
"""

UPSERT = """
INSERT INTO public.google_ads_spend_daily
  (day, campaign_id, campaign_name, campaign_status, channel_type,
   spend, clicks, impressions, conversions, conv_value, fetched_at, source,
   data_as_of)
VALUES %s
ON CONFLICT (day, campaign_id) DO UPDATE SET
  campaign_name   = EXCLUDED.campaign_name,
  campaign_status = EXCLUDED.campaign_status,
  channel_type    = EXCLUDED.channel_type,
  spend           = EXCLUDED.spend,
  clicks          = EXCLUDED.clicks,
  impressions     = EXCLUDED.impressions,
  conversions     = EXCLUDED.conversions,
  conv_value      = EXCLUDED.conv_value,
  fetched_at      = EXCLUDED.fetched_at,
  source          = EXCLUDED.source,
  -- The API answers LIVE, so the data is current as of the moment we
  -- asked. MapleMonk's copy is current as of its morning sync, which
  -- is what data_as_of carries for its rows.
  --
  -- Without this the stale MapleMonk value survived on rows the API had
  -- already overwritten with fresher numbers: measured 2026-10-31, a
  -- row fetched 11:42 still claimed 11:03, and the hourly tracker reads
  -- that column to decide how many hours a day's spend covers. It was
  -- holding back forty minutes of Google spend for no reason.
  data_as_of      = EXCLUDED.data_as_of
"""


def _rows(results: list[dict]) -> list[tuple]:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    out = []
    for r in results:
        c, m, seg = r.get("campaign", {}), r.get("metrics", {}), r.get("segments", {})
        out.append((
            seg["date"], str(c["id"]), c.get("name"), c.get("status"),
            c.get("advertisingChannelType"),
            int(m.get("costMicros", 0)) / 1e6,
            int(m.get("clicks", 0)),
            int(m.get("impressions", 0)),
            float(m.get("conversions", 0)),
            float(m.get("conversionsValue", 0)),
            # fetched_at and data_as_of are the same instant here, and
            # that is the claim: the API answered live.
            now, "google_ads_api", now,
        ))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to", dest="to_date")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and summarise, write nothing.")
    args = ap.parse_args()

    until = date.fromisoformat(args.to_date) if args.to_date else date.today()
    since = (date.fromisoformat(args.from_date) if args.from_date
             else until - timedelta(days=args.days - 1))

    try:
        ads = ads_connect()
    except GoogleAdsAuthError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"API:       {ads.version}, customer {ads.customer_id}")
    print(f"Window:    {since} .. {until}")

    try:
        results = ads.search_stream(GAQL.format(since=since, until=until))
    except GoogleAdsAuthError as exc:
        print(exc, file=sys.stderr)
        return 1

    rows = _rows(results)
    if not rows:
        print("No rows returned.", file=sys.stderr)
        return 1

    days = {r[0] for r in rows}
    spend = sum(r[5] for r in rows)
    conv = sum(r[8] for r in rows)
    value = sum(r[9] for r in rows)
    print(f"Fetched:   {len(rows):,} campaign-days, {len(days)} days, "
          f"{len({r[1] for r in rows})} campaigns")
    print(f"           spend Rs {spend:,.0f}  conversions {conv:,.1f}  "
          f"value Rs {value:,.0f}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    with db_connect(autocommit=False, statement_timeout="120s") as conn:
        with conn.cursor() as cur:
            for stmt in MIGRATIONS:
                cur.execute(stmt)
            # What the API is about to change, measured before it does,
            # so the run says whether it actually mattered.
            cur.execute(
                "SELECT COALESCE(SUM(conv_value), 0), COALESCE(SUM(spend), 0) "
                "  FROM public.google_ads_spend_daily "
                " WHERE day BETWEEN %s AND %s", (since, until))
            old_value, old_spend = cur.fetchone()
            psycopg2.extras.execute_values(cur, UPSERT, rows, page_size=500)
            cur.execute(
                "SELECT COALESCE(SUM(conv_value), 0), COALESCE(SUM(spend), 0) "
                "  FROM public.google_ads_spend_daily "
                " WHERE day BETWEEN %s AND %s", (since, until))
            new_value, new_spend = cur.fetchone()
            cur.execute(
                "SELECT source, count(*) FROM public.google_ads_spend_daily "
                " GROUP BY source ORDER BY source")
            by_source = cur.fetchall()
        conn.commit()

    print(f"\n[OK] {len(rows):,} rows upserted")
    print(f"     conv_value  {float(old_value):,.0f} -> {float(new_value):,.0f}  "
          f"({float(new_value) - float(old_value):+,.0f})")
    print(f"     spend       {float(old_spend):,.0f} -> {float(new_spend):,.0f}  "
          f"({float(new_spend) - float(old_spend):+,.0f})")
    print("     rows by source: "
          + ", ".join(f"{s}={n:,}" for s, n in by_source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
