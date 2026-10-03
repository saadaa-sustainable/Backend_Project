"""Materialise raw_dump_meta insights into a flat (ad_id, day, spend,
conv_value, ncp_count, ftewv_count, impressions, clicks) table so CPIS + Creative Testing endpoints can
read windowed metrics without paying the per-row JSONB extraction cost
that made the /cpis-utm endpoint hit 60+ seconds at 50-row pagination.

Refresh cadence: run after every daily meta ingestion. Build in a temporary
table, then reconcile rows in one transaction. The live table keeps its OID,
views, indexes and permissions, and ordinary dashboard reads remain available.

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

import psycopg2  # noqa: E402


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
ALTER TABLE public.insights_daily_by_ad ENABLE ROW LEVEL SECURITY;
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
      AND raw_payload->>'date_start' = raw_payload->>'date_stop'
    ORDER BY
      raw_payload->>'ad_id',
      raw_payload->>'date_start',
      raw_payload->>'date_stop',
      ingested_at DESC, id DESC
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


# Keep the live relation stable. Renaming it strands existing views on the
# predecessor's OID, and a later DROP fails because those views still use it.
# Only changed rows are rewritten; a normal SELECT never waits on these DML
# locks. The temporary stage is private to this transaction/pool connection.
METRIC_COLUMNS = (
    "spend", "conv_value", "ncp_count", "ftewv_count", "impressions", "clicks",
    "all_clicks", "reach", "purchases", "add_to_cart", "checkout_initiate",
    "thruplays", "three_sec_plays", "outbound_clicks", "post_engagements",
    "video_play_time",
)
_COLUMNS = ", ".join(("ad_id", "day", *METRIC_COLUMNS, "refreshed_at"))
_UPDATES = ", ".join(f"{c} = EXCLUDED.{c}" for c in (*METRIC_COLUMNS, "refreshed_at"))
_CURRENT = ", ".join(f"live.{c}" for c in METRIC_COLUMNS)
_INCOMING = ", ".join(f"EXCLUDED.{c}" for c in METRIC_COLUMNS)

STAGE_DDL = """
CREATE TEMP TABLE insights_daily_by_ad_stage
    (LIKE public.insights_daily_by_ad INCLUDING DEFAULTS) ON COMMIT DROP
"""
STAGE_SQL = REBUILD_SQL.replace(
    "INSERT INTO public.insights_daily_by_ad (",
    "INSERT INTO pg_temp.insights_daily_by_ad_stage (",
)
PUBLISH_SQL = f"""
INSERT INTO public.insights_daily_by_ad AS live ({_COLUMNS})
SELECT {_COLUMNS} FROM pg_temp.insights_daily_by_ad_stage
ON CONFLICT (ad_id, day) DO UPDATE SET {_UPDATES}
WHERE ROW({_CURRENT}) IS DISTINCT FROM ROW({_INCOMING})
"""
DELETE_MISSING_SQL = """
DELETE FROM public.insights_daily_by_ad AS live
WHERE NOT EXISTS (
    SELECT 1 FROM pg_temp.insights_daily_by_ad_stage staged
    WHERE staged.ad_id = live.ad_id AND staged.day = live.day
)
"""
LIVE_MAX_DAY_SQL = "SELECT MAX(day) FROM public.insights_daily_by_ad"
STAGE_STATS_SQL = """
SELECT COUNT(*), COUNT(DISTINCT ad_id), MIN(day), MAX(day)
FROM pg_temp.insights_daily_by_ad_stage
"""


def publish_stage(cur) -> tuple[int, int, tuple]:
    """Publish a complete snapshot atomically; caller owns commit/rollback."""
    cur.execute(STAGE_STATS_SQL)
    stats = cur.fetchone()
    cur.execute(LIVE_MAX_DAY_SQL)
    live_through = cur.fetchone()[0]
    if not stats[0]:
        raise RuntimeError("Daily insight rebuild is empty; preserving the live table")
    if live_through is not None and stats[3] < live_through:
        raise RuntimeError(
            f"Daily insight coverage regressed: {stats[3]} < {live_through}; "
            "preserving the live table"
        )
    cur.execute(PUBLISH_SQL)
    changed = cur.rowcount
    cur.execute(DELETE_MISSING_SQL)
    removed = cur.rowcount
    return changed, removed, stats


def ensure_table(conn) -> None:
    # Avoid running ALTER TABLE on every refresh: even ADD IF NOT EXISTS
    # takes an exclusive lock and can queue behind a dashboard query.
    with conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'insights_daily_by_ad'
            """)
            columns = {r[0] for r in cur.fetchall()}
            if not set(("ad_id", "day", "refreshed_at", *METRIC_COLUMNS)) <= columns:
                cur.execute(DDL)


def refresh(conn) -> tuple:
    ensure_table(conn)
    with conn:
        with conn.cursor() as cur:
            # LOCAL settings and the temporary stage live inside ONE transaction,
            # so they also work through Supabase's transaction pooler.
            cur.execute("SET LOCAL statement_timeout = '3600s'")
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtext('refresh_insights_daily_by_ad'))")
            if not cur.fetchone()[0]:
                raise RuntimeError("Another daily ad metrics refresh is already running")
            print("[pg] building daily ad metrics in a temporary table ...", flush=True)
            cur.execute(STAGE_DDL)
            cur.execute(STAGE_SQL)
            cur.execute("ALTER TABLE pg_temp.insights_daily_by_ad_stage ADD PRIMARY KEY (ad_id, day)")
            cur.execute("ANALYZE pg_temp.insights_daily_by_ad_stage")
            print("[pg] publishing daily ad metrics ...", flush=True)
            changed, removed, stats = publish_stage(cur)
            # Reconciliation can remove old synthetic rows. Refresh planner
            # estimates before downstream analytics read the smaller table.
            cur.execute("ANALYZE public.insights_daily_by_ad")
            print(f"[pg] {changed:,} inserted/changed; {removed:,} obsolete rows removed", flush=True)
    return stats


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    dsn = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")
    t0 = time.monotonic()
    conn = psycopg2.connect(dsn, connect_timeout=15, application_name="daily_ad_metrics_refresh")
    try:
        n, distinct_ads, mn, mx = refresh(conn)
    finally:
        conn.close()
    print(f"\n[OK] insights_daily_by_ad refreshed in {time.monotonic() - t0:.1f}s")
    print(f"    rows          : {n:,}")
    print(f"    distinct ads  : {distinct_ads:,}")
    print(f"    date range    : {mn} -> {mx}")


if __name__ == "__main__":
    main()
