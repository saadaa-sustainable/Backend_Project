"""Rebuild public.ad_history_milestones -- what an ad looked like THEN,
not what it looks like now.

ad_lifecycle.category is a live verdict: it re-evaluates F1-F4 against
whatever ad_insights currently holds, so an ad that was a Winner in its
first fortnight and has since decayed reads "Discarded" today, and there
is no way to see it was ever anything else. Two columns fix that, both
computed here from the (ad_id, day) grain in insights_daily_by_ad:

  category_at_day_14   the category the ad WOULD have been given on the
                       14th day of its life, from metrics cumulative
                       over creation_day .. creation_day + 13.

  impressions_50k_date the first day the ad's cumulative impressions
                       crossed 50,000 -- the F1 gate every category
                       above "P2 analysis" depends on. days_to_50k is
                       the same fact as an age.

The category CASE is copied verbatim from
app/services/silver/ad_lifecycle.py so the historical verdict and the
live one are the same function of the same inputs -- only the window
differs. If you change the thresholds there, change them here.

The 'Result Awaited' branch is deliberately absent. It fires in
ad_lifecycle when created_time > now() - 14 days, i.e. "too early to
judge". At the day-14 mark the ad is exactly 14 days old, so that branch
is false by construction and the ad falls through to 'Discarded'. An ad
that has not YET reached day 14 gets no row's worth of verdict at all --
see history_status below.

WHAT THIS CANNOT TELL YOU (measured live 2026-09-04)
----------------------------------------------------
raw_dump_meta insights begin 2026-01-01. There is nothing earlier in
bronze, so for an ad created before that there is no first-fortnight
data to reconstruct from -- this is a data floor, not a bug, and no
amount of SQL fixes it. Of 14,866 ads in ad_lifecycle:

    5,089  created 2026-01-01 or later  -> day-14 verdict computable
    9,773  created earlier              -> mostly 'no_history', no verdict

Note that "no daily rows in the first fortnight" is NOT the same thing
as "no history". An ad created inside the range that served nothing for
two weeks gets 'no_delivery' and a real verdict ('Discarded'); only an
ad created before the floor is genuinely unjudgeable.

Same floor on the 50k date: 208 ads have ever passed 50,000 impressions
lifetime, but only 115 were created inside the daily range, so only
those can be given a trustworthy crossing DATE. For the rest the
cumulative sum starts mid-life and would date the crossing too late;
they are marked 'partial_history' and the date is left NULL rather than
published wrong.

Fixing the floor means a Meta backfill fetch (Meta retains ~37 months of
insights) -- a separate ingest job, not a change to this script. Once
bronze goes back further, re-running this fills the gap with no code
change.

SECOND CAVEAT, smaller but real: 447,265 of 498,371 bronze insight rows
(90%) cover multi-day ranges, which refresh_insights_daily_by_ad.py
pro-rates evenly across their days. So a cumulative-to-day-14 figure is
exact only where Meta returned true daily rows, and an even
approximation elsewhere. That is good enough for a threshold verdict
(the F1 gate is 50,000 impressions, not 50,001) but it is why
days_to_50k should be read as "about this many days", not to the day.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_ad_history_milestones.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402


DSN = (os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL") or "").replace(
    "postgresql+psycopg2://", "postgresql://"
).replace("postgresql+asyncpg://", "postgresql://")

#: The F1 gate, and the impressions milestone the dashboard asks for.
#: Same constant as ad_lifecycle.py's f1_pass.
F1_IMPRESSIONS = 50000

#: The verdict horizon, in days INCLUSIVE of the creation day: an ad
#: created on the 2nd is judged on metrics through the 15th.
HORIZON_DAYS = 14


DDL = """
CREATE TABLE IF NOT EXISTS public.ad_history_milestones (
    ad_id                   text PRIMARY KEY,
    ad_created_date         date,

    -- The day-14 verdict and the numbers behind it, so a merchant can
    -- see WHY it was a Winner and not just that it was.
    category_at_day_14      text,
    day_14_date             date,
    impressions_at_day_14   numeric,
    spend_at_day_14         numeric,
    conv_value_at_day_14    numeric,
    ncp_at_day_14           numeric,
    ftewv_at_day_14         numeric,
    roas_at_day_14          numeric,
    f1_at_day_14            boolean,
    f2_at_day_14            boolean,
    f3_at_day_14            boolean,
    f4_at_day_14            boolean,

    -- 'ok'              full first fortnight inside the daily range
    -- 'not_yet_14_days' younger than the horizon -- no verdict yet
    -- 'no_delivery'     fortnight IS in range, the ad just served
    --                   nothing in it. Scored, and the answer is
    --                   'Discarded' -- a real verdict, not a gap.
    -- 'partial_history' created before the data floor, so the fortnight
    --                   is only partly covered. Scored, approximate.
    -- 'no_history'      created before the floor with nothing at all to
    --                   go on. The only status with no verdict.
    history_status          text NOT NULL,

    -- First day cumulative impressions crossed F1_IMPRESSIONS. NULL
    -- when it never did, or when history_status makes the running sum
    -- untrustworthy (see the module docstring).
    impressions_50k_date    date,
    days_to_50k             integer,

    computed_at             timestamptz
)
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_ahm_cat14 ON public.ad_history_milestones (category_at_day_14)",
    "CREATE INDEX IF NOT EXISTS ix_ahm_50k   ON public.ad_history_milestones (impressions_50k_date)",
]

REFRESH = f"""
WITH bounds AS (
    SELECT MIN(day) AS floor_day, MAX(day) AS latest_day FROM public.insights_daily_by_ad
),
ads AS (
    SELECT al.ad_id,
           al.ad_created_time::date AS created_date,
           al.ad_created_time::date + ({HORIZON_DAYS} - 1) AS day_14_date
    FROM ad_lifecycle al
    WHERE al.ad_created_time IS NOT NULL
),
-- Cumulative over the ad's first fortnight only.
win AS (
    SELECT a.ad_id,
           SUM(d.impressions) AS impressions,
           SUM(d.spend)       AS spend,
           SUM(d.conv_value)  AS conv_value,
           SUM(d.ncp_count)   AS ncp_count,
           SUM(d.ftewv_count) AS ftewv_count,
           COUNT(*)           AS days_with_data
    FROM ads a
    JOIN public.insights_daily_by_ad d
      ON d.ad_id = a.ad_id
     AND d.day  >= a.created_date
     AND d.day  <= a.day_14_date
    GROUP BY a.ad_id
),
-- First day the running impression total crosses the F1 gate. Runs over
-- the ad's WHOLE life, not just the fortnight -- an ad can cross on day
-- 40 and that is exactly the fact being asked for.
cume AS (
    SELECT d.ad_id, d.day,
           SUM(d.impressions) OVER (
               PARTITION BY d.ad_id ORDER BY d.day
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS cume_impressions
    FROM public.insights_daily_by_ad d
),
crossed AS (
    SELECT ad_id, MIN(day) AS impressions_50k_date
    FROM cume
    WHERE cume_impressions >= {F1_IMPRESSIONS}
    GROUP BY ad_id
),
scored AS (
    SELECT
      a.ad_id, a.created_date, a.day_14_date,
      COALESCE(w.impressions, 0) AS impressions,
      COALESCE(w.spend, 0)       AS spend,
      COALESCE(w.conv_value, 0)  AS conv_value,
      COALESCE(w.ncp_count, 0)   AS ncp_count,
      COALESCE(w.ftewv_count, 0) AS ftewv_count,
      w.days_with_data,
      x.impressions_50k_date,
      b.floor_day, b.latest_day,
      -- ORDER MATTERS, and getting it wrong is not cosmetic. The first
      -- draft tested "no rows in the fortnight" before anything else,
      -- which collapsed two unrelated situations into one label: an ad
      -- we CANNOT judge (created before the data floor) and an ad that
      -- simply DID NOT RUN in its first fortnight. Measured on live
      -- data that mislabelled 3,280 ads and, worse, withheld a verdict
      -- from every one of them -- an ad that served zero impressions in
      -- its first two weeks has a perfectly good day-14 verdict, and it
      -- is 'Discarded'. The giveaway was 83 supposedly "no history" ads
      -- carrying a valid 50k crossing date.
      --
      -- Age first (it is a fact about the calendar, independent of what
      -- data we hold), then the data floor, then delivery.
      CASE
        WHEN a.day_14_date > b.latest_day  THEN 'not_yet_14_days'
        WHEN a.created_date < b.floor_day
             THEN CASE WHEN w.ad_id IS NULL THEN 'no_history'
                       ELSE 'partial_history' END
        WHEN w.ad_id IS NULL               THEN 'no_delivery'
        ELSE 'ok'
      END AS history_status
    FROM ads a
    CROSS JOIN bounds b
    LEFT JOIN win w     ON w.ad_id = a.ad_id
    LEFT JOIN crossed x ON x.ad_id = a.ad_id
)
INSERT INTO public.ad_history_milestones (
    ad_id, ad_created_date, category_at_day_14, day_14_date,
    impressions_at_day_14, spend_at_day_14, conv_value_at_day_14,
    ncp_at_day_14, ftewv_at_day_14, roas_at_day_14,
    f1_at_day_14, f2_at_day_14, f3_at_day_14, f4_at_day_14,
    history_status, impressions_50k_date, days_to_50k, computed_at
)
SELECT
    s.ad_id, s.created_date,
    -- Verbatim from ad_lifecycle.py, minus the 'Result Awaited' branch
    -- (see the module docstring). Scored wherever the fortnight is
    -- judgeable -- including 'no_delivery', where zero impressions and
    -- zero spend fall through to 'Discarded', which is the correct
    -- answer rather than a missing one. Only 'no_history' goes
    -- unscored: publishing 'Discarded' for an ad whose data we simply
    -- do not hold would be a lie, not a verdict.
    CASE WHEN s.history_status IN ('ok', 'partial_history', 'no_delivery') THEN
      CASE
        WHEN s.impressions >= {F1_IMPRESSIONS}
         AND ((s.spend > 0 AND s.conv_value / s.spend >= 3.0)
              OR (s.ncp_count > 0 AND s.spend / s.ncp_count <= 525))
         AND s.ftewv_count > 0 AND s.spend / s.ftewv_count <= 12
            THEN 'Incremental Winner'
        WHEN s.impressions >= {F1_IMPRESSIONS}
         AND ((s.spend > 0 AND s.conv_value / s.spend >= 3.0)
              OR (s.ncp_count > 0 AND s.spend / s.ncp_count <= 525))
            THEN 'Winner'
        WHEN s.impressions >= {F1_IMPRESSIONS}
         AND s.ftewv_count > 0 AND s.spend / s.ftewv_count <= 12
            THEN 'P0 analysis'
        WHEN s.impressions >= {F1_IMPRESSIONS}
            THEN 'P1 analysis'
        WHEN s.spend > 0 AND s.conv_value / s.spend >= 3.0
            THEN 'P2 analysis'
        ELSE 'Discarded'
      END
    END AS category_at_day_14,
    s.day_14_date,
    s.impressions, s.spend, s.conv_value, s.ncp_count, s.ftewv_count,
    CASE WHEN s.spend > 0 THEN s.conv_value / s.spend END AS roas_at_day_14,
    (s.impressions >= {F1_IMPRESSIONS})                             AS f1_at_day_14,
    (s.spend > 0 AND s.conv_value / s.spend >= 3.0)                 AS f2_at_day_14,
    (s.ncp_count > 0 AND s.spend / s.ncp_count <= 525)              AS f3_at_day_14,
    (s.ftewv_count > 0 AND s.spend / s.ftewv_count <= 12)           AS f4_at_day_14,
    s.history_status,
    -- Only publish a crossing date when the running sum genuinely
    -- started at the ad's beginning. For an ad that predates the daily
    -- range the sum starts mid-life, so it would date the crossing
    -- LATER than it happened -- worse than saying nothing.
    CASE WHEN s.created_date >= s.floor_day THEN s.impressions_50k_date END,
    CASE WHEN s.created_date >= s.floor_day
         THEN (s.impressions_50k_date - s.created_date) END,
    now()
FROM scored s
"""


def main() -> int:
    if not DSN:
        raise SystemExit("Set DATABASE_URL_SYNC (or DATABASE_URL) first.")
    t0 = time.time()
    conn = psycopg2.connect(DSN)
    try:
        with conn, conn.cursor() as cur:
            # The window function runs over all 1.75M daily rows; the DB
            # default 120s ceiling is close enough to the measured time
            # to be worth raising. SET LOCAL -- Supavisor pools in
            # transaction mode.
            cur.execute("SET LOCAL statement_timeout = '900s'")
            cur.execute("SET LOCAL work_mem = '128MB'")
            cur.execute(DDL)
            for statement in INDEXES:
                cur.execute(statement)
            # One transaction, so a failure leaves the previous snapshot
            # rather than an empty table.
            cur.execute("TRUNCATE public.ad_history_milestones")
            cur.execute(REFRESH)
            written = cur.rowcount
            cur.execute("""
                SELECT history_status, COUNT(*),
                       COUNT(*) FILTER (WHERE impressions_50k_date IS NOT NULL)
                FROM public.ad_history_milestones GROUP BY history_status ORDER BY 2 DESC
            """)
            breakdown = cur.fetchall()
        print(f"ad_history_milestones: {written} rows in {time.time() - t0:.1f}s")
        for status, n, with_50k in breakdown:
            print(f"    {status:18s} {n:>6}  ({with_50k} with a 50k date)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
