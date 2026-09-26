"""Materialise raw_dump_meta insights into a flat (ad_id, day, spend,
conv_value, ncp_count, ftewv_count, impressions, clicks) table so CPIS + Creative Testing endpoints can
read windowed metrics without paying the per-row JSONB extraction cost
that made the /cpis-utm endpoint hit 60+ seconds at 50-row pagination.

Refresh cadence: run after every daily meta ingestion. Idempotent, and
built into a side table that is swapped in at the end, so readers are
never blocked for longer than the rename (see main() for what the old
TRUNCATE cost once an endpoint depended on this table).

The columns are DERIVED here from Meta's actions[] / action_values[]
JSONB arrays -- ncp_count comes from actions[first_time_customer_purchase]
and conv_value from action_values[omni_purchase], matching what
ad_lifecycle.py extracts for the lifetime rollup.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_insights_daily_by_ad.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402


DSN = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")


DDL = """
CREATE TABLE IF NOT EXISTS public.insights_daily_by_ad (
    ad_id         text NOT NULL,
    day           date NOT NULL,
    spend         numeric,
    conv_value    numeric,
    ncp_count     numeric,
    -- Added 2026-09-04 for the historical day-14 category. F4
    -- (spend/ftewv <= 12) is what separates Incremental Winner from
    -- Winner and P0 from P1, so without a daily ftewv the reconstructed
    -- category could not tell those pairs apart. Same global
    -- custom-conversion match ad_lifecycle.py uses for the lifetime
    -- rollup, so the two agree by construction.
    ftewv_count   numeric,
    impressions   numeric,
    clicks        numeric,
    -- Added 2026-09-05. ad_lifecycle used to take these from
    -- ad_insights, which holds ONE arbitrary fetched date range per ad
    -- (measured: 73% of 14,866 ads had a window under 30 days, from 6
    -- days to 234) and presented it as lifetime. Summing the daily grain
    -- instead gives a real total over the whole range bronze covers, and
    -- gives every ad the SAME range so two ads can be compared at all.
    purchases          numeric,
    add_to_cart        numeric,
    checkout_initiate  numeric,
    thruplays          numeric,
    three_sec_plays    numeric,
    outbound_clicks    numeric,
    post_engagements   numeric,
    video_play_time    numeric,
    reach              numeric,
    all_clicks         numeric,
    refreshed_at  timestamptz DEFAULT NOW(),
    PRIMARY KEY (ad_id, day)
);
ALTER TABLE public.insights_daily_by_ad
    ADD COLUMN IF NOT EXISTS ftewv_count       numeric,
    ADD COLUMN IF NOT EXISTS purchases         numeric,
    ADD COLUMN IF NOT EXISTS add_to_cart       numeric,
    ADD COLUMN IF NOT EXISTS checkout_initiate numeric,
    ADD COLUMN IF NOT EXISTS thruplays         numeric,
    ADD COLUMN IF NOT EXISTS three_sec_plays   numeric,
    ADD COLUMN IF NOT EXISTS outbound_clicks   numeric,
    ADD COLUMN IF NOT EXISTS post_engagements  numeric,
    ADD COLUMN IF NOT EXISTS video_play_time   numeric,
    ADD COLUMN IF NOT EXISTS reach             numeric,
    ADD COLUMN IF NOT EXISTS all_clicks        numeric;
CREATE INDEX IF NOT EXISTS ix_idba_ad_day ON public.insights_daily_by_ad(ad_id, day);
CREATE INDEX IF NOT EXISTS ix_idba_day    ON public.insights_daily_by_ad(day);
"""


# 2026-09-03 rewrite: guarantees ONE row per (ad_id, day) whose value
# reflects that day's ACTUAL Meta spend, no over-count. Three-stage
# CTE chain:
#
#   raw_dedup   Meta's fetches often duplicate the same insight row (we
#               ingest as fresh rows instead of upserting on
#               (ad_id, date_start, date_stop)). DISTINCT ON keeps ONE
#               canonical copy per period, preferring most-recent
#               ingested so a late correction wins over an earlier estimate.
#
#   expanded    Meta returns a mix of granularities in the same dump:
#               true daily rows (date_start = date_stop), plus weekly
#               and monthly summaries. generate_series expands each row
#               into per-day slices, pro-rating spend / conv_value / ncp
#               / impressions / clicks evenly across the range's days.
#
#   best        For each (ad_id, day) multiple sources may exist -- the
#               true daily row AND a weekly summary that includes that
#               day. DISTINCT ON keeps the highest-granularity slice
#               (shortest range_days) so a daily row always beats the
#               weekly slice it would double with. Pro-rated weekly
#               slices only survive on days that had no daily row.
#
# Result: row count = distinct (ad_id, day) tuples. A day with a true
# daily row carries Meta's own figure for it; a day without carries its
# share of whatever the covering summary did not already account for.
REBUILD_SQL = """
WITH ncp_ids AS (
    SELECT DISTINCT raw_payload ->> 'id' AS id
    FROM raw_dump_meta
    WHERE object_type = 'custom_conversion' AND raw_payload ->> 'name' = 'NCP'
),
ftewv_ids AS (
    SELECT DISTINCT raw_payload ->> 'id' AS id
    FROM raw_dump_meta
    WHERE object_type = 'custom_conversion' AND raw_payload ->> 'name' = 'First-time EWV'
),
raw_dedup AS (
    SELECT DISTINCT ON (
      raw_payload->>'ad_id',
      raw_payload->>'date_start',
      raw_payload->>'date_stop'
    )
      raw_payload
    FROM raw_dump_meta
    WHERE object_type = 'insights'
      AND raw_payload->>'ad_id' IS NOT NULL
      AND raw_payload->>'date_start' IS NOT NULL
      AND raw_payload->>'date_stop' IS NOT NULL
    ORDER BY
      raw_payload->>'ad_id',
      raw_payload->>'date_start',
      raw_payload->>'date_stop',
      ingested_at DESC
),
extracted AS (
    SELECT
      raw_payload->>'ad_id' AS ad_id,
      (raw_payload->>'date_start')::date AS ds,
      (raw_payload->>'date_stop')::date  AS de,
      NULLIF(raw_payload->>'spend','')::numeric AS spend,
      -- conv_value: prefer omni_purchase (aggregated web + app + offline),
      -- fall back to plain purchase.
      COALESCE(
        (SELECT (av->>'value')::numeric
           FROM jsonb_array_elements(raw_payload->'action_values') av
           WHERE av->>'action_type' = 'omni_purchase' LIMIT 1),
        (SELECT (av->>'value')::numeric
           FROM jsonb_array_elements(raw_payload->'action_values') av
           WHERE av->>'action_type' = 'purchase' LIMIT 1),
        0
      ) AS conv_value,
      -- ncp_count: SUM(actions[].value) where action_type matches the
      -- Business-Manager-global 'offsite_conversion.custom.<ncp_id>'.
      COALESCE(
        (SELECT SUM((act->>'value')::numeric)
           FROM jsonb_array_elements(raw_payload->'actions') act
           WHERE act->>'action_type' = ANY (
             SELECT 'offsite_conversion.custom.' || id FROM ncp_ids
           )),
        0
      ) AS ncp_count,
      -- Same shape as ncp_count above, against the 'First-time EWV'
      -- custom conversion.
      COALESCE(
        (SELECT SUM((act->>'value')::numeric)
           FROM jsonb_array_elements(raw_payload->'actions') act
           WHERE act->>'action_type' = ANY (
             SELECT 'offsite_conversion.custom.' || id FROM ftewv_ids
           )),
        0
      ) AS ftewv_count,
      NULLIF(raw_payload->>'impressions','')::numeric AS impressions,
      -- LINK clicks. Sparse until the fetch started asking for
      -- inline_link_clicks (2026-09-17); rows older than that carry NULL
      -- here and the all_clicks column below is what they have.
      NULLIF(raw_payload->>'inline_link_clicks','')::numeric AS clicks,
      -- ALL clicks, which Meta has always returned. A different metric
      -- from link clicks -- it counts every click on the ad, not just
      -- the ones that went to the site -- so it gets its own column
      -- rather than being COALESCEd into `clicks` and quietly changing
      -- what a CTR built on that column means.
      NULLIF(raw_payload->>'clicks','')::numeric AS all_clicks,
      NULLIF(raw_payload->>'reach','')::numeric AS reach,
      -- omni_* first, plain second -- byte-for-byte ad_lifecycle.py's
      -- _first_match() ordering, so the summed value and the lifetime
      -- rollup agree on what counts as a purchase.
      COALESCE(
        (SELECT (a->>'value')::numeric FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = 'omni_purchase' LIMIT 1),
        (SELECT (a->>'value')::numeric FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = 'purchase' LIMIT 1), 0) AS purchases,
      COALESCE(
        (SELECT (a->>'value')::numeric FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = 'omni_add_to_cart' LIMIT 1),
        (SELECT (a->>'value')::numeric FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = 'add_to_cart' LIMIT 1), 0) AS add_to_cart,
      COALESCE(
        (SELECT (a->>'value')::numeric FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = 'omni_initiated_checkout' LIMIT 1),
        (SELECT (a->>'value')::numeric FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = 'initiate_checkout' LIMIT 1), 0) AS checkout_initiate,
      COALESCE((raw_payload->'video_thruplay_watched_actions'->0->>'value')::numeric, 0) AS thruplays,
      COALESCE(
        (SELECT (a->>'value')::numeric FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = 'video_view' LIMIT 1), 0) AS three_sec_plays,
      COALESCE((raw_payload->'outbound_clicks'->0->>'value')::numeric, 0) AS outbound_clicks,
      COALESCE(NULLIF(raw_payload->>'inline_post_engagement','')::numeric, 0) AS post_engagements,
      COALESCE((raw_payload->'video_avg_time_watched_actions'->0->>'value')::numeric, 0) AS video_play_time
    FROM raw_dedup
),
-- A true daily row is authoritative for its day. Anything longer is a
-- SUMMARY OVER ITS WHOLE RANGE, so it may only supply the days no
-- daily row covers -- and only the spend those days actually account
-- for.
--
-- This used to divide a summary by its full range and hand every
-- uncovered day that flat average. When 10 of a 15-day summary's days
-- already had daily rows, the remaining 5 each still received
-- total/15, so the same spend was counted twice: once as itself, once
-- inside the summary's average.
--
-- Measured 2026-08-28..09-24 against Ads Manager at ad level across
-- both live accounts (Rs 1,16,28,012):
--
--     true daily rows only        Rs 1,11,21,641   -4.4%
--     flat-average fill (old)     Rs 1,21,88,770   +4.8%
--
-- The fill is right in principle -- the uncovered days did carry real
-- spend -- but it injected Rs 10,67,129 where the gap was Rs 5,06,371,
-- roughly double. The residual is now the summary MINUS whatever its
-- own daily rows already account for, spread across the uncovered days
-- alone.
daily AS (
    SELECT ad_id, ds AS day, spend, conv_value, ncp_count, ftewv_count, impressions, clicks, all_clicks, purchases, add_to_cart, checkout_initiate, thruplays, three_sec_plays, outbound_clicks, post_engagements, reach, video_play_time
    FROM extracted WHERE de = ds
),
summaries AS (
    SELECT *, (de - ds + 1) AS range_days FROM extracted WHERE de > ds
),
summary_cov AS (
    -- The LATERAL already aggregates to one row per summary, so this
    -- is a plain projection -- no GROUP BY.
    SELECT s.*,
           COALESCE(c.cov_days, 0) AS cov_days,
           COALESCE(c.s_spend, 0) AS cov_spend,
           COALESCE(c.s_conv_value, 0) AS cov_conv_value,
           COALESCE(c.s_ncp_count, 0) AS cov_ncp_count,
           COALESCE(c.s_ftewv_count, 0) AS cov_ftewv_count,
           COALESCE(c.s_impressions, 0) AS cov_impressions,
           COALESCE(c.s_clicks, 0) AS cov_clicks,
           COALESCE(c.s_all_clicks, 0) AS cov_all_clicks,
           COALESCE(c.s_purchases, 0) AS cov_purchases,
           COALESCE(c.s_add_to_cart, 0) AS cov_add_to_cart,
           COALESCE(c.s_checkout_initiate, 0) AS cov_checkout_initiate,
           COALESCE(c.s_thruplays, 0) AS cov_thruplays,
           COALESCE(c.s_three_sec_plays, 0) AS cov_three_sec_plays,
           COALESCE(c.s_outbound_clicks, 0) AS cov_outbound_clicks,
           COALESCE(c.s_post_engagements, 0) AS cov_post_engagements
    FROM summaries s
    LEFT JOIN LATERAL (
      SELECT COUNT(*) AS cov_days, SUM(d.spend) AS s_spend, SUM(d.conv_value) AS s_conv_value, SUM(d.ncp_count) AS s_ncp_count, SUM(d.ftewv_count) AS s_ftewv_count, SUM(d.impressions) AS s_impressions, SUM(d.clicks) AS s_clicks, SUM(d.all_clicks) AS s_all_clicks, SUM(d.purchases) AS s_purchases, SUM(d.add_to_cart) AS s_add_to_cart, SUM(d.checkout_initiate) AS s_checkout_initiate, SUM(d.thruplays) AS s_thruplays, SUM(d.three_sec_plays) AS s_three_sec_plays, SUM(d.outbound_clicks) AS s_outbound_clicks, SUM(d.post_engagements) AS s_post_engagements
        FROM daily d
       WHERE d.ad_id = s.ad_id AND d.day BETWEEN s.ds AND s.de
    ) c ON TRUE
),
summary_fill AS (
    SELECT
      m.ad_id,
      gs::date AS day,
      m.range_days,
      GREATEST(m.spend - m.cov_spend, 0) / NULLIF(m.range_days - m.cov_days, 0) AS spend,
      GREATEST(m.conv_value - m.cov_conv_value, 0) / NULLIF(m.range_days - m.cov_days, 0) AS conv_value,
      GREATEST(m.ncp_count - m.cov_ncp_count, 0) / NULLIF(m.range_days - m.cov_days, 0) AS ncp_count,
      GREATEST(m.ftewv_count - m.cov_ftewv_count, 0) / NULLIF(m.range_days - m.cov_days, 0) AS ftewv_count,
      GREATEST(m.impressions - m.cov_impressions, 0) / NULLIF(m.range_days - m.cov_days, 0) AS impressions,
      GREATEST(m.clicks - m.cov_clicks, 0) / NULLIF(m.range_days - m.cov_days, 0) AS clicks,
      GREATEST(m.all_clicks - m.cov_all_clicks, 0) / NULLIF(m.range_days - m.cov_days, 0) AS all_clicks,
      GREATEST(m.purchases - m.cov_purchases, 0) / NULLIF(m.range_days - m.cov_days, 0) AS purchases,
      GREATEST(m.add_to_cart - m.cov_add_to_cart, 0) / NULLIF(m.range_days - m.cov_days, 0) AS add_to_cart,
      GREATEST(m.checkout_initiate - m.cov_checkout_initiate, 0) / NULLIF(m.range_days - m.cov_days, 0) AS checkout_initiate,
      GREATEST(m.thruplays - m.cov_thruplays, 0) / NULLIF(m.range_days - m.cov_days, 0) AS thruplays,
      GREATEST(m.three_sec_plays - m.cov_three_sec_plays, 0) / NULLIF(m.range_days - m.cov_days, 0) AS three_sec_plays,
      GREATEST(m.outbound_clicks - m.cov_outbound_clicks, 0) / NULLIF(m.range_days - m.cov_days, 0) AS outbound_clicks,
      GREATEST(m.post_engagements - m.cov_post_engagements, 0) / NULLIF(m.range_days - m.cov_days, 0) AS post_engagements,
      m.reach / NULLIF(m.range_days, 0) AS reach,
      m.video_play_time                 AS video_play_time
    FROM summary_cov m,
         generate_series(m.ds, m.de, '1 day'::interval) gs
    WHERE m.range_days > m.cov_days
      AND NOT EXISTS (
        SELECT 1 FROM daily d WHERE d.ad_id = m.ad_id AND d.day = gs::date)
),
best AS (
    SELECT DISTINCT ON (ad_id, day) ad_id, day, spend, conv_value, ncp_count, ftewv_count, impressions, clicks, all_clicks, purchases, add_to_cart, checkout_initiate, thruplays, three_sec_plays, outbound_clicks, post_engagements, reach, video_play_time
    FROM (
      SELECT ad_id, day, 1 AS range_days, spend, conv_value, ncp_count, ftewv_count, impressions, clicks, all_clicks, purchases, add_to_cart, checkout_initiate, thruplays, three_sec_plays, outbound_clicks, post_engagements, reach, video_play_time FROM daily
      UNION ALL
      SELECT ad_id, day, range_days, spend, conv_value, ncp_count, ftewv_count, impressions, clicks, all_clicks, purchases, add_to_cart, checkout_initiate, thruplays, three_sec_plays, outbound_clicks, post_engagements, reach, video_play_time FROM summary_fill
    ) u
    ORDER BY ad_id, day, range_days ASC
)
INSERT INTO public.insights_daily_by_ad (
    ad_id, day, spend, conv_value, ncp_count, ftewv_count, impressions, clicks, all_clicks, reach, purchases, add_to_cart, checkout_initiate, thruplays, three_sec_plays, outbound_clicks, post_engagements, video_play_time
)
SELECT ad_id, day, spend, conv_value, ncp_count, ftewv_count, impressions, clicks, all_clicks, reach, purchases, add_to_cart, checkout_initiate, thruplays, three_sec_plays, outbound_clicks, post_engagements, video_play_time
FROM best
"""


# 3600s, raised from 1200s on 2026-09-05.
#
# The Meta history backfill landed 174,625 rows in raw_dump_meta, taking
# it to 708,780 insights rows, and this rebuild expands each one across
# every day of its date range before deduplicating -- 1,752,382 output
# rows. At 1200s it died mid-INSERT, exactly 1200.2s in:
#
#     [pg] rebuilding from raw_dump_meta ...
#     psycopg2.errors.QueryCanceled: canceling statement due to
#     statement timeout
#
# and because this step failed, every step after it in the workflow was
# skipped -- so the metric mirrors were never synced and the dashboard
# saw none of it. The fetch had worked; only the flatten was too slow
# for its own limit.
#
# The job's own ceiling is 350 minutes, so an hour here is still a
# safety net rather than an expectation. If it ever approaches this,
# the rebuild wants to go incremental rather than get a bigger number.
_TIMEOUT = "SET statement_timeout = '3600s'"


def main() -> None:
    t0 = time.time()
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(_TIMEOUT)
            cur.execute(DDL)
            conn.commit()

            # The DDL commit above ended that transaction, and a session
            # SET does not reliably survive one under Supavisor's
            # transaction pooling -- the connection goes back to the pool
            # and the next statement can land on a different backend.
            # Re-apply inside the transaction that actually matters, so
            # the rebuild cannot inherit the server default. Same lesson
            # as app/services/silver/shopify_ad_attribution.py, where a
            # single SET let a 34-minute job die on the 2-minute default.
            cur.execute(_TIMEOUT)

            # BUILD INTO A SIDE TABLE, THEN SWAP.
            #
            # This used to TRUNCATE and re-INSERT in one transaction.
            # That kept the data safe -- a failed rebuild rolled the
            # truncate back with it -- but TRUNCATE takes an ACCESS
            # EXCLUSIVE lock, so every reader of this table blocked for
            # the WHOLE rebuild, not just the commit. Once Creative
            # Testing started reading it for windowed spend, that turned
            # a routine nightly refresh into a visibly broken section:
            # the endpoint sat on the lock and died on its statement
            # timeout, HTTP 500 after 121 seconds.
            #
            # Building into a side table and swapping keeps the same
            # all-or-nothing guarantee -- readers see the old rows until
            # the swap and the new rows after -- while holding the
            # exclusive lock only for the rename, which is instant.
            print("[pg] building insights_daily_by_ad_new ...", flush=True)
            cur.execute("DROP TABLE IF EXISTS public.insights_daily_by_ad_new")
            cur.execute(
                "CREATE TABLE public.insights_daily_by_ad_new "
                "(LIKE public.insights_daily_by_ad INCLUDING DEFAULTS)"
            )
            cur.execute(REBUILD_SQL.replace(
                "INSERT INTO public.insights_daily_by_ad (",
                "INSERT INTO public.insights_daily_by_ad_new (",
            ))
            # Indexes AFTER the insert -- building them once over the
            # finished table beats maintaining them row by row.
            print("[pg] indexing ...", flush=True)
            cur.execute("ALTER TABLE public.insights_daily_by_ad_new "
                        "ADD PRIMARY KEY (ad_id, day)")
            cur.execute("CREATE INDEX ix_idba_ad_day_new "
                        "ON public.insights_daily_by_ad_new(ad_id, day)")
            cur.execute("CREATE INDEX ix_idba_day_new "
                        "ON public.insights_daily_by_ad_new(day)")

            # Renaming a table does NOT rename its indexes, so the old
            # table's indexes keep the canonical names and would collide
            # the moment the new ones claim them. Move the old names out
            # of the way first, inside the same transaction as the swap.
            print("[pg] swapping ...", flush=True)
            cur.execute("DROP TABLE IF EXISTS public.insights_daily_by_ad_old")
            cur.execute("ALTER TABLE public.insights_daily_by_ad "
                        "RENAME TO insights_daily_by_ad_old")
            for name in ("ix_idba_ad_day", "ix_idba_day", "insights_daily_by_ad_pkey"):
                cur.execute(f"ALTER INDEX IF EXISTS {name} RENAME TO {name}_old")

            cur.execute("ALTER TABLE public.insights_daily_by_ad_new "
                        "RENAME TO insights_daily_by_ad")
            # And claim the canonical names for the new table's indexes,
            # PK included: leaving it as insights_daily_by_ad_new_pkey
            # would make the NEXT run's ADD PRIMARY KEY collide with it.
            cur.execute("ALTER INDEX ix_idba_ad_day_new RENAME TO ix_idba_ad_day")
            cur.execute("ALTER INDEX ix_idba_day_new RENAME TO ix_idba_day")
            cur.execute("ALTER INDEX IF EXISTS insights_daily_by_ad_new_pkey "
                        "RENAME TO insights_daily_by_ad_pkey")
            conn.commit()

            # Outside the swap transaction: the old table is unreferenced
            # now, and dropping it is not worth holding the swap open for.
            cur.execute("DROP TABLE IF EXISTS public.insights_daily_by_ad_old")
            conn.commit()

            cur.execute(
                "SELECT COUNT(*), COUNT(DISTINCT ad_id), MIN(day), MAX(day) "
                "FROM public.insights_daily_by_ad"
            )
            n, distinct_ads, mn, mx = cur.fetchone()
    finally:
        conn.close()

    dt = time.time() - t0
    print(f"\n[OK] insights_daily_by_ad refreshed in {dt:.1f}s")
    print(f"    rows          : {n:,}")
    print(f"    distinct ads  : {distinct_ads:,}")
    print(f"    date range    : {mn} -> {mx}")


if __name__ == "__main__":
    main()
