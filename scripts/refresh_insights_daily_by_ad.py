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
#   daily       Meta returns a mix of granularities in the same dump:
#               true daily rows (date_start = date_stop) from
#               meta_insights_15d, plus all_days summaries from
#               meta_insights_lifetime. Keep only the daily rows, at
#               face value. See the long note on the CTE itself for why
#               the summaries must not be spread across their days.
#
#   best        Belt and braces. raw_dedup already keys on
#               (ad_id, date_start, date_stop), so restricting to
#               date_start = date_stop leaves at most one row per
#               (ad_id, day) already.
#
# Result: row count = distinct (ad_id, day) tuples, each carrying Meta's
# own figure for that day and nothing else.
#
# ONE statement, and it must stay that way by being cheap rather than by
# being split up. The version that pro-rated summaries expanded 17,986
# blocks across 15 days each and then deduplicated; it ran past the
# 3600s statement timeout, Postgres cancelled it, and the client never
# noticed -- it sat on a half-open socket at 0% CPU until killed. The
# pooler dropping long-running connections is a known property of this
# database (it did the same to the GoKwik ingest). Reading only daily
# rows does no expansion at all and finishes in ~165s.
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
-- ONE ROW PER AD PER DAY, TAKEN ONLY FROM META'S OWN DAILY ROWS.
--
-- Bronze holds two kinds of insights row and they are not two views of
-- the same thing:
--
--   date_start = date_stop   meta_insights_15d, time_increment=1.
--                            Meta's figure FOR THAT DAY.
--   date_start < date_stop   meta_insights_lifetime, all_days. The
--                            same days aggregated, fetched for
--                            ad_lifecycle's lifetime rollup.
--
-- This used to read both and spread every multi-day row across its
-- days. That counts each day twice -- once as itself, once inside
-- every all_days block covering it -- and Meta returns those blocks as
-- ROLLING trailing windows (7-21, 8-22, 9-23 Sep), so the overlap
-- compounds. Worked example, ad 120228929233370422: a 15-day block of
-- Rs 10.96 whose only delivering day already had a daily row of Rs
-- 10.96 became Rs 21.19, a 93% overstatement.
--
-- Dropping the all_days rows loses no coverage: every month from
-- 2025-12 onward carries daily rows, and an ad-day with no daily row
-- is a day Meta reported no delivery for -- time_increment=1 returns a
-- row per day the ad actually ran. Spreading a summary onto those days
-- invents spend rather than recovering it. Measured directly: the
-- residual the summaries hold beyond what daily rows already account
-- for is Rs 26 across 33,888 of them, against the Rs 10,70,455 the
-- spreading was adding.
--
-- VERIFIED against Meta rather than against a screenshot. Ads Manager
-- readings moved between sittings (Rs 1,14,80,107, then Rs
-- 1,16,28,012, for what was described as the same view), so the check
-- is /act_<id>/insights at level=account for the identical window --
-- the figure Ads Manager renders, straight from the API. For
-- 2026-08-28..09-24 over the two live accounts:
--
--     Meta, level=account       Rs 1,11,21,647
--     Meta, level=ad            Rs 1,11,21,647   (1,891 ads)
--     this table                Rs 1,11,21,641   (-Rs 6, rounding)
--     old pro-rated version     Rs 1,21,92,096   (+9.6%)
--
-- refresh_insights_daily_by_entity.py carries the same fix, and adset
-- and campaign grain now land on the same Rs 1,11,21,641.
--
-- It is also why this step stopped finishing. Expanding 17,986 blocks
-- across 15 days each, then deduplicating, ran past the 3600s
-- statement timeout; the pooler dropped the socket and the client sat
-- on it at 0% CPU. Reading only daily rows does no expansion at all.
daily AS (
    SELECT ad_id, ds AS day, spend, conv_value, ncp_count, ftewv_count, impressions, clicks, all_clicks, purchases, add_to_cart, checkout_initiate, thruplays, three_sec_plays, outbound_clicks, post_engagements, reach, video_play_time
    FROM extracted
    WHERE de = ds
),
best AS (
    -- raw_dedup already keeps one row per (ad_id, date_start,
    -- date_stop); with only same-day rows left that is one row per
    -- (ad_id, day). This guards the invariant rather than doing work.
    SELECT DISTINCT ON (ad_id, day) ad_id, day, spend, conv_value, ncp_count, ftewv_count, impressions, clicks, all_clicks, purchases, add_to_cart, checkout_initiate, thruplays, three_sec_plays, outbound_clicks, post_engagements, reach, video_play_time
    FROM daily
    ORDER BY ad_id, day
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
