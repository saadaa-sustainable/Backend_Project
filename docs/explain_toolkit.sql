-- ===========================================================================
-- SAADAA DASHBOARD -- EXPLAIN TOOLKIT
-- Paste into the Supabase SQL editor. Run section 0 FIRST in every session.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 0. SESSION SETUP -- run this first, every time.
--    Without track_io_timing, EXPLAIN cannot tell you whether the time went
--    to CPU or to disk, which is the whole question. It is off by default
--    and resets when the session ends.
-- ---------------------------------------------------------------------------
SET track_io_timing = on;
SET statement_timeout = '600s';   -- several of these exceed the 120s default
SHOW work_mem;                    -- expect 3500kB today


-- ---------------------------------------------------------------------------
-- 1. WHO ARE THE WORST OFFENDERS?  (cheap, run anytime)
-- ---------------------------------------------------------------------------
SELECT left(regexp_replace(query, '\s+', ' ', 'g'), 70)              AS query,
       calls,
       round(total_exec_time/1000)::int                             AS total_s,
       round(mean_exec_time)::int                                   AS mean_ms,
       round(temp_blks_written*8192/1024.0/1024/1024, 1)            AS temp_gb,
       round(100.0*shared_blks_hit
             / NULLIF(shared_blks_hit + shared_blks_read, 0), 1)    AS cache_hit_pct
  FROM pg_stat_statements
 WHERE calls > 2
 ORDER BY total_exec_time DESC
 LIMIT 20;


-- ---------------------------------------------------------------------------
-- 2. WHICH QUERIES SPILL TO DISK?  (sorts/hashes that exceed work_mem)
--    temp_mb_per_call is roughly how much sort space the query wanted.
--    Multiply by 3-4x for the work_mem it would actually need in memory.
-- ---------------------------------------------------------------------------
SELECT left(regexp_replace(query, '\s+', ' ', 'g'), 60)             AS query,
       calls,
       round(temp_blks_written*8192/1024.0/1024/1024, 1)            AS temp_gb,
       round(temp_blks_written*8192/1024.0/1024
             / GREATEST(calls,1))::int                              AS temp_mb_per_call,
       round(mean_exec_time)::int                                   AS mean_ms
  FROM pg_stat_statements
 WHERE temp_blks_written > 0
 ORDER BY temp_blks_written DESC
 LIMIT 15;


-- ---------------------------------------------------------------------------
-- 3. WHERE IS THE CACHE MISSING?  (per table)
-- ---------------------------------------------------------------------------
SELECT s.relname,
       pg_size_pretty(pg_total_relation_size(s.relid))              AS size,
       pg_size_pretty(sum(s.heap_blks_read)*8192)                   AS read_from_disk,
       round(100.0*sum(s.heap_blks_hit)
             / NULLIF(sum(s.heap_blks_hit + s.heap_blks_read), 0), 1) AS cache_hit_pct
  FROM pg_statio_user_tables s
 GROUP BY s.relname, s.relid
 ORDER BY sum(s.heap_blks_read) DESC
 LIMIT 15;


-- ===========================================================================
-- 4. THE ACTUAL PLANS
--
-- !! SAFETY !! EXPLAIN ANALYZE on an INSERT REALLY RUNS THE INSERT.
--    Every statement below has had its INSERT stripped, leaving only the
--    SELECT. They are read-only and safe to run as written.
--    If you ever want to explain the INSERT itself, wrap it:
--        BEGIN; EXPLAIN (ANALYZE, BUFFERS) <insert...>; ROLLBACK;
--    -- that still does all the work and all the I/O, it just discards it.
--
-- These are the real production queries, parameters filled in.
-- Each is slow by definition. Run them when the dashboard is NOT in use.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 4a. THE WORST ONE: landing-page rollup. 16 calls, 9,691s total,
--     mean 605 SECONDS per call. Full GROUP BY over shopify_sessions (719 MB)
--     joined to meta_campaigns. Look for: HashAggregate vs GroupAggregate,
--     and whether the Sort below it says "external merge".
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS)
SELECT s.day, s.landing_page_path, s.landing_page_type, s.referrer_source,
       c.campaign_id  AS matched_campaign_id,
       c.campaign_name AS matched_campaign_name,
       SUM(s.sessions)                           AS sessions,
       SUM(s.pageviews)                          AS pageviews,
       SUM(s.sessions_with_cart_additions)       AS sessions_with_cart_additions,
       SUM(s.sessions_that_reached_checkout)     AS sessions_that_reached_checkout,
       SUM(s.sessions_that_completed_checkout)   AS sessions_that_completed_checkout
  FROM shopify_sessions s
  LEFT JOIN meta_campaigns c ON c.campaign_id = s.utm_campaign
 GROUP BY s.day, s.landing_page_path, s.landing_page_type, s.referrer_source,
          c.campaign_id, c.campaign_name;


-- ---------------------------------------------------------------------------
-- 4b. THE BIGGEST SPILLER: sessions flatten. 19 calls, 31.3 GB of temp files,
--     mean 394s. This is the DISTINCT ON over raw_dump_shopify (14 GB).
--     Look for: "Sort Method: external merge  Disk: NNNNNkB" under the
--     Unique node, and Buffers "read=" far exceeding "hit=".
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS)
WITH latest AS (
    SELECT DISTINCT ON (source_id) source_id, id
      FROM raw_dump_shopify
     WHERE object_type = 'sessions' AND source_id IS NOT NULL
     ORDER BY source_id, extracted_at DESC, id DESC
)
SELECT a.source_id, a.extracted_at
  FROM raw_dump_shopify a
  JOIN latest ON latest.id = a.id
 WHERE a.object_type = 'sessions';


-- ---------------------------------------------------------------------------
-- 4c. THE META SIDE: DISTINCT ON over raw_dump_meta (9.4 GB, 38% cache hit).
--     I measured this one at 74s. Note it pulls raw_payload (large jsonb),
--     which is what makes the sort enormous.
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS)
SELECT DISTINCT ON (meta_id) meta_id, raw_payload
  FROM raw_dump_meta
 WHERE object_type = 'ad'
 ORDER BY meta_id, extracted_at DESC;

-- 4c-lite: the same shape WITHOUT raw_payload. Compare the two -- the
-- difference is the cost of dragging the jsonb through the sort, and it is
-- the single clearest argument for selecting ids first and joining the
-- payload back afterwards.
EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
SELECT DISTINCT ON (meta_id) meta_id
  FROM raw_dump_meta
 WHERE object_type = 'ad'
 ORDER BY meta_id, extracted_at DESC;


-- ---------------------------------------------------------------------------
-- 5. A/B A SETTING WITHOUT CHANGING ANYTHING GLOBALLY.
--    SET applies to your session only and dies with it. Safe.
--    Re-run any plan above between these to compare.
-- ---------------------------------------------------------------------------
SET work_mem = '256MB';          -- try 64MB / 256MB / 512MB
-- ... re-run a plan from section 4 here ...
RESET work_mem;

SET max_parallel_workers_per_gather = 4;   -- currently 1
-- ... re-run a plan from section 4 here ...
RESET max_parallel_workers_per_gather;
