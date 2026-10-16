#!/usr/bin/env python
"""ARPU from GA4, daily, split by device category.

ONE ROW PER DAY PER DEVICE, and a `(all)` device row beside them.
Daily is the finest grain GA4 will give without a per-user export, and
it is exact for the day it describes.

WHAT A MULTI-DAY TOTAL FROM THESE ROWS MEANS
--------------------------------------------
`activeUsers` is DEDUPLICATED over whatever window GA4 is asked for. A
person who visits on eight days is one active user in a 30-day query
and eight across eight daily queries. Measured on this property,
2026-09-16..10-15:

    GA4's own 30-day query    1,164,394 users   ARPU 37.52
    sum of the 30 daily rows  1,390,380 users   ARPU 31.42

Revenue is additive and matches to the rupee; only the denominator
differs. So summing these rows answers "revenue per active user-DAY",
which is a real and stable figure, and NOT the same question as GA4's
own window ARPU. The dashboard says which one it is showing.

That trade is deliberate: a window table would match GA4 exactly but
only for the windows it stored, and a custom date range got no answer
at all. Daily answers every range.

NEXT DIMENSION
--------------
`newVsReturning` is the dimension the "ARPU - New vs Repeat"
exploration segments on, and it is ready to add here. It does NOT sum:
new + returning came to 1,291,289 users against 1,164,394 overall,
126,895 double-counted, because someone whose first visit and a later
return both fall in the window belongs to both. When it is added it
needs its own `(all)` row for the same reason device does.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402

PROPERTY = "383126449"
METRICS = ("activeUsers", "totalRevenue", "sessions", "ecommercePurchases")
ALL = "(all)"

DDL = """
CREATE TABLE IF NOT EXISTS public.ga4_arpu_daily (
    day             date    NOT NULL,
    device_category text    NOT NULL,
    active_users    bigint  NOT NULL,
    total_revenue   numeric NOT NULL,
    sessions        bigint  NOT NULL,
    purchases       bigint  NOT NULL,
    fetched_at      timestamptz NOT NULL,
    PRIMARY KEY (day, device_category)
);
CREATE INDEX IF NOT EXISTS ix_ga4_arpu_daily_day ON public.ga4_arpu_daily(day);

"""

UPSERT_DAILY = """
INSERT INTO public.ga4_arpu_daily
  (day, device_category, active_users, total_revenue, sessions, purchases, fetched_at)
VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
ON CONFLICT (day, device_category) DO UPDATE SET
  active_users = EXCLUDED.active_users, total_revenue = EXCLUDED.total_revenue,
  sessions = EXCLUDED.sessions, purchases = EXCLUDED.purchases,
  fetched_at = EXCLUDED.fetched_at
"""



def _client():
    """Reuse fetch_ga4_daily's credential chain: service account, then a
    cached OAuth token, then ADC. One place decides how we authenticate."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ga4_daily", ROOT / "scripts" / "fetch_ga4_daily.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    return BetaAnalyticsDataClient(credentials=mod._credentials())


def _report(client, dims, lo: date, hi: date):
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest)
    resp = client.run_report(RunReportRequest(
        property=f"properties/{PROPERTY}",
        date_ranges=[DateRange(start_date=lo.isoformat(), end_date=hi.isoformat())],
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name=m) for m in METRICS]))
    for row in resp.rows:
        dim = [d.value for d in row.dimension_values]
        m = [v.value for v in row.metric_values]
        yield dim, int(float(m[0])), float(m[1]), int(float(m[2])), int(float(m[3]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=35,
                    help="trailing days of DAILY rows to refresh (default 35)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # GA4 lands the current day incomplete, so yesterday is the last
    # day worth storing -- the same cutoff fetch_ga4_daily uses.
    hi = date.today() - timedelta(days=1)
    lo = hi - timedelta(days=args.days - 1)
    client = _client()

    daily: list[tuple] = []
    for dim, users, rev, sess, pur in _report(client, ["date", "deviceCategory"], lo, hi):
        d = date(int(dim[0][:4]), int(dim[0][4:6]), int(dim[0][6:]))
        daily.append((d, dim[1] or "(not set)", users, rev, sess, pur))
    # The per-day undimensioned total. Not the sum of the device rows:
    # a person on phone and laptop is in both, and GA4 dedups this.
    for dim, users, rev, sess, pur in _report(client, ["date"], lo, hi):
        d = date(int(dim[0][:4]), int(dim[0][4:6]), int(dim[0][6:]))
        daily.append((d, ALL, users, rev, sess, pur))

    print(f"GA4 ARPU  property {PROPERTY}  daily {lo}..{hi}")
    print(f"  {len(daily):,} daily rows "
          f"({len({d for d, *_ in daily})} days x {len({c for _, c, *_ in daily})} categories)")
    tot_u = sum(u for _, c, u, *_ in daily if c == ALL)
    tot_r = sum(r for _, c, _, r, *_ in daily if c == ALL)
    if tot_u:
        print(f"    summed over the fetched range: {tot_u:,} user-days, "
              f"revenue {tot_r:,.0f}, ARPU {tot_r/tot_u:.2f} per active user-day")
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    with connect(autocommit=False, statement_timeout="600s") as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.executemany(UPSERT_DAILY, daily)
            cur.execute("ANALYZE public.ga4_arpu_daily")
        conn.commit()
    print(f"\n[OK] wrote {len(daily):,} daily rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
