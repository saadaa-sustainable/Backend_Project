# Creative Testing Dashboard — computation logic reference

Source of truth for this document: `https://github.com/saadaa-sustainable/Creative_Testing_Dashboard`
(cloned and read directly — not reconstructed from memory). This is the exact SQL and Python
logic currently running in production against the live `Meta_ads_data` / `Saada_Shopify_Data`
Supabase projects. It exists so the new medallion service's Silver (Python) and Gold
(SQL-via-RPC) layers can reproduce this faithfully instead of guessing at it.

Every code block below is a verbatim quote from the source repo, not a paraphrase.

---

## Open items requiring a ruling before anything here gets ported

1. **F4 threshold (₹ cost per FTEWV) has three different live values, not two:**
   - `12` — `refresh_ae_table.py`'s actual SQL, and `GUIDEBOOK.md`'s toolbar-default spec (`#ctF4`/`#aeF4`)
   - `25` — `refresh_summary_table.py`'s SQL, and `qa/test_03_ae_table_view.py`'s `F4_CPF` constant
   - `≤₹25` — `GUIDEBOOK.md`'s own prose description (contradicting its own toolbar spec of `12`)
   - The QA suite already knows about this: its F4 check is downgraded from `fail` to `warn` with the
     comment *"likely `ae_raw_view` uses different upstream thresholds."* Production has been running
     with this drift, unresolved, for a while.
2. **F2 threshold**: `3.2` in both DB-baked SQL paths (`refresh_ae_table.py` and `refresh_summary_table.py`)
   vs `3` in `GUIDEBOOK.md` prose / the dashboard toolbar's editable default. Matches the earlier
   project-memory finding — reconfirmed here from source, line-accurate.
3. **The actual `ae_table_view` SQL (the view the dashboard reads, with the category `CASE` and
   Shopify joins) is not in this repo.** `refresh_ae_table.py` states outright that it no longer runs
   table/view DDL — that view definition lived in `_consolidate_ae_views.py`, which does not exist in
   this clone. It was evidently run once, by hand, directly against Supabase, and never checked in.
   The category logic below is reconstructed from `refresh_summary_table.py`'s `CASE` (which computes
   the same categories from a different table) plus `qa/test_02_category_logic.py`'s reference
   implementation — both agree with each other and with `GUIDEBOOK.md` on rule ordering.
4. **`rebuild_new_incr_table()` / `rebuild_new_incr_adset_table()` / `rebuild_new_incr_camp_table()`
   RPC bodies are not in the repo** — only their names and call sites. The closest full-SQL analog
   that *is* checked in is `get_ireach_incremental_analysis` (§7), which computes the same
   cumulative-minus-previous-cumulative incremental-reach formula at ad/adset/campaign/account level.
5. **`ad_results`'s migration is incomplete** vs. what `result_classifier.py` actually writes —
   `impressions`, `impressions_last_seen`, `total_spend` columns exist in production but aren't in
   the checked-in migration file, meaning a later `ALTER TABLE` was run by hand and never committed.

Don't silently pick a number for #1/#2 when porting — ask first, same as the standing rule for any
F2/F4 threshold decision on this project.

---

## Pipeline order

Per `GUIDEBOOK.md`'s documented run order (the computationally-relevant subset — the full 16-step
list including Google Ads / thumbnail / asset-sheet steps is in project memory, not repeated here):

```
1. primary_sync.py                 fetch latest Meta insights -> primary_table
2. propagate_primary_to_backfill   mirror last 15 days of primary_table into backfill_table
3. apply_ctp_unique_ids            enrich summary_table from an external Excel mapping
4. refresh_ae_table                rebuild ae_raw_view (+ shopify_ad_agg), refresh ae_reach_recent
5. refresh_summary_table           rebuild summary_table (category CASE lives here)
6. result_classifier               re-tag ad_results (separate 3-state lifecycle model)
7. results_sync                    rebuild results_table cache
8. rebuild_attribution_orders      rebuild shopify_ad_attribution (5-tier order matching)
```

---

## 1. `primary_table` — base ingestion (`backend/primary_sync.py`)

Fetches Meta `/insights` at `level=ad` and writes one row per `(account_name, ad_id, date)`.
Below is the computation logic only — HTTP/pagination boilerplate omitted.

**Custom-conversion resolution** — NCP and FTEWV are Meta custom conversions, resolved by display
name to a numeric ID per ad account, then matched against `action_type` in the response:

```python
CUSTOM_METRIC_FTEWV = "First-time EWV"   # custom-conversion name in Meta Business Manager
CUSTOM_METRIC_NCP   = "NCP"

ftewv_count = _action_val(actions, f"offsite_conversion.custom.{ftewv_id}") if ftewv_id else 0.0
ncp_count   = _action_val(actions, f"offsite_conversion.custom.{ncp_id}")   if ncp_id   else 0.0

def _action_val(lst: list, *types) -> float:
    if not lst:
        return 0.0
    for item in lst:
        if item.get("action_type") in types:
            return float(item.get("value", 0) or 0)
    return 0.0
```

**Cost-per metrics — deliberately spend/count, not Meta's own field:**

```python
# NOT Meta's cost_per_action_type -- comment in source: "causes Meta 400/500
# errors on large accounts"
cost_per_ftewv = round(spend / ftewv_count, 2) if ftewv_count > 0 else 0.0
cost_per_ncp   = round(spend / ncp_count, 2)   if ncp_count   > 0 else 0.0
```

**Purchases / conversion value / funnel actions:**

```python
purchases     = _action_val(actions, "omni_purchase", "purchase")
conv_value    = _action_val(row.get("action_values") or [], "omni_purchase", "purchase")
checkout_ini  = _action_val(actions, "omni_initiated_checkout", "initiate_checkout")
add_to_cart   = _action_val(actions, "omni_add_to_cart", "add_to_cart")
```

**Engagement rate numerator** ("Simran Jadon formula" per source comment):

```python
engagement_meta = (thruplays + post_comments + post_reactions + post_saves
                    + post_shares + page_likes + link_clicks)
```

**Computed rates:**

```python
cpm               = spend / impressions * 1000       if impressions  > 0 else 0.0
cost_per_purchase = spend / purchases                if purchases    > 0 else 0.0
checkout_compl    = purchases / checkout_ini * 100    if checkout_ini > 0 else 0.0
atc_rate          = add_to_cart / link_clicks * 100   if link_clicks  > 0 else 0.0
ci_atc_rate       = checkout_ini / add_to_cart * 100  if add_to_cart  > 0 else 0.0
purchase_rate     = purchases / link_clicks * 100     if link_clicks  > 0 else 0.0
```

**Grain and upsert:** `ON CONFLICT (account_name, ad_id, date) DO UPDATE SET <all columns> =
EXCLUDED.<col>, updated_at = NOW()` — every sync fully overwrites with Meta's latest numbers, no
dedup logic beyond the natural key.

**Placeholder rows:** for every ad in an "active-like" status (`ACTIVE, PAUSED, ADSET_PAUSED,
CAMPAIGN_PAUSED, WITH_ISSUES, PENDING_REVIEW, PREAPPROVED, IN_PROCESS, PENDING_BILLING_INFO,
DISAPPROVED`) that Meta's `/insights` didn't return for the sync window, a zero-metric row is
upserted for every date in the window — keeps the dashboard's ad count matching Meta Ads Manager's
UI count (which includes non-delivering active ads). `ARCHIVED`/`DELETED` ads are excluded by
design.

---

## 2. `backfill_table` — lifetime mirror (`backend/propagate_primary_to_backfill.py`)

`primary_table` only covers a rolling ~6–9 month window; `backfill_table` is the full lifetime
store since 2023. After every `primary_sync.py` run, the last `WINDOW_DAYS = 15` days of
`primary_table` get mirrored in:

```sql
-- UPDATE: rows that exist in both tables for the same key
UPDATE backfill_table b
SET impressions = p.impressions, reach = p.reach, frequency = p.frequency,
    amount_spent_inr = p.amount_spent_inr, ad_status = p.ad_status,
    purchase_roas = p.purchase_roas, outbound_clicks = p.outbound_clicks,
    thruplays = p.thruplays, three_sec_video_plays = p.three_sec_video_plays,
    post_engagements = p.post_engagements, conversion_value = p.conversion_value,
    video_play_time = p.video_play_time, ftewv_count = p.ftewv_count,
    cost_per_ftewv = p.cost_per_ftewv, ncp_count = p.ncp_count,
    cost_per_ncp = p.cost_per_ncp, ltv_reach = p.ltv_reach,
    ltv_frequency = p.ltv_frequency, campaign_name = p.campaign_name,
    campaign_id = p.campaign_id,
    ad_created_date = COALESCE(p.ad_created_date, b.ad_created_date)
FROM primary_table p
WHERE p.account_name = b.account_name
  AND p.ad_id        = b.ad_id
  AND p.date         = b.date
  AND p.date >= CURRENT_DATE - INTERVAL '15 days'
```

```sql
-- INSERT: rows primary_table has that backfill_table doesn't yet
INSERT INTO backfill_table (
  account_name, date, ad_id, ad_name, campaign_name, campaign_id,
  ad_status, ad_created_date, impressions, reach, frequency,
  amount_spent_inr, purchase_roas, outbound_clicks, thruplays,
  three_sec_video_plays, post_engagements, conversion_value,
  video_play_time, ftewv_count, cost_per_ftewv, ncp_count, cost_per_ncp,
  ltv_reach, ltv_frequency
)
SELECT p.account_name, p.date, p.ad_id, p.ad_name, p.campaign_name, p.campaign_id,
       p.ad_status, p.ad_created_date, p.impressions, p.reach, p.frequency,
       p.amount_spent_inr, p.purchase_roas, p.outbound_clicks, p.thruplays,
       p.three_sec_video_plays, p.post_engagements, p.conversion_value,
       p.video_play_time, p.ftewv_count, p.cost_per_ftewv, p.ncp_count, p.cost_per_ncp,
       p.ltv_reach, p.ltv_frequency
FROM primary_table p
WHERE p.date >= CURRENT_DATE - INTERVAL '15 days'
  AND NOT EXISTS (
    SELECT 1 FROM backfill_table b
    WHERE b.account_name = p.account_name AND b.ad_id = p.ad_id AND b.date = p.date
  )
```

---

## 3. `ae_raw_view` — per-ad lifetime aggregation (`backend/refresh_ae_table.py`)

Despite the name, this is a table rebuilt nightly (not a live view), aggregating `primary_table` ∪
`backfill_table` per ad, over its full lifetime.

### F1–F4 pass flags (as written here — see the open-items section for why F2/F4 disagree elsewhere)

```sql
(e.impressions >= 50000),                                          -- F1
(amount_spent > 0 AND conv_value / amount_spent >= 3.2),           -- F2
(ncp_count   > 0 AND amount_spent / ncp_count <= 525),              -- F3
(ftewv_count > 0 AND amount_spent / ftewv_count <= 12)              -- F4 (12 here, 25 in §4)
```

### F1-hit date — first date cumulative impressions cross 50,000

Deduped across `backfill_table` ∪ `primary_table` by `MAX(impressions)` per `(ad_id, date)` before
the running sum, so a day covered by both tables isn't double-counted:

```sql
WITH f1_hit AS (
    SELECT ad_id, MIN(date) AS date_target_imp_achieved
    FROM (
        SELECT ad_id, date, cum_imp
        FROM (
            SELECT
                ad_id, date,
                SUM(impressions) OVER (PARTITION BY ad_id ORDER BY date ROWS UNBOUNDED PRECEDING) AS cum_imp
            FROM (
                SELECT ad_id, date, MAX(impressions) AS impressions
                FROM (
                    SELECT ad_id, date, impressions FROM backfill_table WHERE ad_id IS NOT NULL
                    UNION ALL
                    SELECT ad_id, date, impressions FROM primary_table  WHERE ad_id IS NOT NULL
                ) u
                GROUP BY ad_id, date
            ) d
        ) c
        WHERE cum_imp >= 50000
    ) h
    GROUP BY ad_id
)
```

### Result-timing — falls back to `first_seen_date + 14 days` if F1 never hit

```sql
CASE
    WHEN f.date_target_imp_achieved IS NOT NULL THEN f.date_target_imp_achieved
    WHEN e.first_seen_date IS NOT NULL          THEN (e.first_seen_date + INTERVAL '14 days')::date
    WHEN e.ad_created IS NOT NULL                THEN (e.ad_created + INTERVAL '14 days')::date
    ELSE NULL
END AS date_of_result,
CASE
    WHEN e.first_seen_date IS NULL THEN NULL
    ELSE GREATEST(0,
        (COALESCE(f.date_target_imp_achieved, (e.first_seen_date + INTERVAL '14 days')::date)
         - e.first_seen_date)::int)
END AS days_to_result,
CASE
    WHEN f.date_target_imp_achieved IS NULL OR e.first_seen_date IS NULL THEN NULL
    ELSE GREATEST(0, (f.date_target_imp_achieved - e.first_seen_date)::int)
END AS days_to_target_f1
```

### Reach — must use Meta's lifetime-deduplicated `ltv_reach`, not `SUM(reach)`

This is a hard-won bugfix worth preserving verbatim, including the reasoning:

```sql
-- Reach: prefer Meta's lifetime-deduplicated reach (`ltv_reach`).
-- The bare `SUM(b.reach)` from backfill_table double-counts a person
-- who saw the ad on multiple days (Meta dedupes per day, not across
-- days). Validated against Meta Admin API: SUM(reach) overstates
-- true lifetime reach by 30-75% on average. ltv_reach is correct.
COALESCE(NULLIF(b.ltv_reach, 0), b.reach, 0)::bigint AS reach
```

### Core ratio formulas (`calc` CTE)

```
frequency          = impressions / reach                       (reach > 0)
cpr_1000           = amount_spent / reach * 1000                (reach > 0)
cpc_link            = amount_spent / link_clicks                 (link_clicks > 0)
ctr_pct             = link_clicks / impressions * 100            (impressions > 0)
checkout_compl_pct  = purchases / ci * 100                       (ci > 0)
cr_lc_pct           = purchases / link_clicks * 100              (link_clicks > 0)
atc_lc_pct          = atc / link_clicks * 100                    (link_clicks > 0)
ci_atc_pct          = ci / atc * 100                             (atc > 0)
roas_ma             = conv_value / amount_spent, ELSE 0          (amount_spent > 0)
cost_per_ftewv      = amount_spent / ftewv_count                 (ftewv_count > 0)
cost_per_ncp        = amount_spent / ncp_count                   (ncp_count > 0)
pct_reach_ftewv     = ftewv_count / reach * 100                  (reach > 0)
reach_weight_pct    = reach / SUM(reach over all ads) * 100
profit_efficiency   = conv_value - amount_spent
contrib_margin_pct  = CASE WHEN amount_spent>0 AND conv_value>0
                        THEN (1 - amount_spent/conv_value) * 100
                        ELSE -100 END
```

### Fleet-wide "anchor" metrics — every ad's efficiency is relative to the whole account

```
anchor_cpr        = SUM(amount_spent) / SUM(reach) * 1000     (global)
anchor_roas       = SUM(conv_value)  / SUM(amount_spent)      (global)
anchor_ftewv_pct  = SUM(ftewv_count) / SUM(reach)              (global)
anchor_cpftewv    = SUM(amount_spent) / SUM(ftewv_count)       (global)
med_ftewv         = percentile_cont(0.5) WITHIN GROUP (ORDER BY ftewv_count)             (global median)
med_profit        = percentile_cont(0.5) WITHIN GROUP (ORDER BY (conv_value - amount_spent))  (global median)
```

```sql
-- efficiency CTE (all default to 0 when the guard condition fails)
x_cpr_eff         = anchor_cpr / cpr_1000                          (cpr_1000 > 0)
y_ftv_contrib_eff = (ftewv_count/reach) / anchor_ftewv_pct          (reach > 0 AND anchor_ftewv_pct > 0)
z_ftev_volume     = ftewv_count / med_ftewv                         (med_ftewv > 0)
aa_ncp_cost_eff   = (g_spend/g_ncp) / cost_per_ncp                   (cost_per_ncp > 0 AND g_ncp > 0)
ab_roas_eff       = roas_ma / anchor_roas                           (roas_ma > 0 AND anchor_roas > 0)
ac_profit_vol_eff = profit_efficiency / med_profit                  (med_profit <> 0)
```

### `shopify_ad_agg` rebuild — tiered order-to-ad spend spread

3-tier spread for orders that only matched at adset/campaign granularity (see §8 for how an order
gets to T3/T4 in the first place): spend-weighted proportional split across the ads in that
adset/campaign.

```sql
t3_spread AS (
  SELECT ad_id,
         spend / SUM(spend) OVER (PARTITION BY order_id)                AS orders,
         total_price * (spend / SUM(spend) OVER (PARTITION BY order_id)) AS total_price,
         order_created_at, 'T3_adset_id' AS matched_tier
  FROM t3_filtered
)
-- t4_spread is identical but partitioned by campaign_name spend instead of adset spend
```

Gated by an asset-code match extracted from `ad_name` via regex (same code set used again in §8):

```sql
BOOL_OR(ad_name ILIKE '%IFAD%')                     AS has_ifad,
BOOL_OR(ad_name ILIKE '%GAD%')                      AS has_gad,
BOOL_OR(ad_name ILIKE '%BST%')                      AS has_bst,
BOOL_OR(ad_name ILIKE '%UGC%')                      AS has_ugc,
BOOL_OR(ad_name ILIKE '%ADB%')                      AS has_adb,
BOOL_OR(ad_name ~ '(^|[^A-Za-z])VID([^A-Za-z]|$)')  AS has_vid,
BOOL_OR(ad_name ILIKE '%BR\_%' ESCAPE '\')          AS has_br,
BOOL_OR(ad_name ILIKE '%BI\_%' ESCAPE '\')          AS has_bi
```

---

## 4. `summary_table` — 6/7-category classification (`backend/refresh_summary_table.py`)

**The only file in the repo where the full category `CASE` statement actually exists in SQL.** One
row per ad, lifetime aggregates from `backfill_table` only.

Thresholds per this file's own docstring:

```
F1 = impressions >= 50,000
F2 = conv_value / spend >= 3.2
F3 = spend / ncp     <= 525  (positive)
F4 = spend / ftewv   <= 25   (positive)   <-- 25 here, 12 in ae_raw_view (§3)
```

### Category assignment (exact)

```sql
CASE
    -- Incremental Winner = F1 AND (F2 OR F3) AND F4
    WHEN a.total_impressions >= 50000
     AND ((a.total_spend > 0 AND a.total_conv_value / a.total_spend >= 3.2)
          OR (a.total_ncp > 0 AND a.total_spend / a.total_ncp <= 525))
     AND a.total_ftewv > 0 AND a.total_spend / a.total_ftewv <= 25
        THEN 'Incremental Winner'
    -- Winner = F1 AND (F2 OR F3)
    WHEN a.total_impressions >= 50000
     AND ((a.total_spend > 0 AND a.total_conv_value / a.total_spend >= 3.2)
          OR (a.total_ncp > 0 AND a.total_spend / a.total_ncp <= 525))
        THEN 'Winner'
    -- P0 analysis (was "Priority") = F1 AND F4
    WHEN a.total_impressions >= 50000
     AND a.total_ftewv > 0 AND a.total_spend / a.total_ftewv <= 25
        THEN 'P0 analysis'
    -- P1 analysis (was "Analyze 1") = F1 only
    WHEN a.total_impressions >= 50000
        THEN 'P1 analysis'
    -- P2 analysis (was "Analyze 2") = F2 only
    WHEN a.total_spend > 0 AND a.total_conv_value / a.total_spend >= 3.2
        THEN 'P2 analysis'
    -- Result Awaited = 14-day grace period
    WHEN a.created_date > CURRENT_DATE - INTERVAL '14 days'
        THEN 'Result Awaited'
    ELSE 'Discarded'
END AS status,
```

This is **7 statuses** (adds "Result Awaited" as a 14-day grace bucket before "Discarded"); the
reconstructed `ae_table_view`/QA-test version only recognizes 6 (no "Result Awaited" — see
`expected_category()` in §6). The `f1_pass..f4_pass` columns written alongside:

```sql
(a.total_impressions >= 50000)                                    AS f1_pass,
(a.total_spend > 0 AND a.total_conv_value / a.total_spend >= 3.2) AS f2_pass,
(a.total_ncp   > 0 AND a.total_spend / a.total_ncp   <= 525)      AS f3_pass,
(a.total_ftewv > 0 AND a.total_spend / a.total_ftewv <= 25)       AS f4_pass,
```

### Verdict-history upsert — only rewrite history when status actually changes

```sql
status              = EXCLUDED.status,
status_at           = CASE
    WHEN summary_table.status IS DISTINCT FROM EXCLUDED.status
    THEN EXCLUDED.status_at
    ELSE summary_table.status_at
END,
prev_status         = CASE
    WHEN summary_table.status IS DISTINCT FROM EXCLUDED.status
    THEN summary_table.status
    ELSE summary_table.prev_status
END,
prev_status_at      = CASE
    WHEN summary_table.status IS DISTINCT FROM EXCLUDED.status
    THEN summary_table.status_at
    ELSE summary_table.prev_status_at
END;
```

### Shopify aggregation for `summary_table` — simple sums, not the tiered spread from §3

```sql
shopify_agg AS (
    SELECT ad_id,
           COUNT(*)                          AS shopify_orders,
           ROUND(SUM(total_price), 2)        AS shopify_sales,
           ROUND(AVG(total_price), 2)        AS shopify_aov,
           MIN(order_created_at)::date       AS shopify_first_order,
           MAX(order_created_at)::date       AS shopify_last_order
    FROM shopify_ad_attribution
    WHERE has_match AND ad_id IS NOT NULL AND ad_id <> ''
    GROUP BY ad_id
),
shopify_top_tier AS (
    SELECT DISTINCT ON (ad_id) ad_id, matched_tier AS shopify_top_tier
    FROM (
        SELECT ad_id, matched_tier, SUM(total_price) AS tier_sales
        FROM shopify_ad_attribution
        WHERE has_match AND ad_id IS NOT NULL AND ad_id <> ''
        GROUP BY ad_id, matched_tier
    ) t
    ORDER BY ad_id, tier_sales DESC
)
-- shopify_roas = ROUND(shopify_sales / total_spend, 3)  when total_spend > 0 AND shopify_sales IS NOT NULL
```

### Current `ad_status` — sourced only from `primary_table`, never `backfill_table`

`backfill_table`'s status freezes on the last-delivery day, so current status always comes from the
most recent `primary_table` row:

```sql
latest_status AS (
    SELECT a.ad_id, p.ad_status
    FROM agg a
    LEFT JOIN LATERAL (
        SELECT ad_status FROM primary_table p2
        WHERE p2.ad_id = a.ad_id AND p2.ad_status IS NOT NULL
        ORDER BY p2.date DESC LIMIT 1
    ) p ON TRUE
)
```

---

## 5. `ae_reach_recent` — materialized view (`backend/refresh_ae_reach_recent.py`)

The script itself is a thin refresh driver — the view body isn't in the repo, only its documented
intent (migration `ae_reach_recent_dedup`, 2026-07-13):

```
* UNION primary_table + backfill_table
* DISTINCT ON (ad_id, date) with primary_table winning -- same dedup rule as ae_daily_agg_mat,
  so consumers of both stay in agreement
* row_number() DESC over date -> pick each ad's latest & previous delivered days
* incremental_reach = latest_reach - previous_reach (signed; negative means reach
  dropped between the two anchor days)
```

```sql
SET LOCAL statement_timeout = '600s';
REFRESH MATERIALIZED VIEW public.ae_reach_recent;
SELECT COUNT(*) FROM public.ae_reach_recent;
```

Worth preserving: the *previous* version of this view used `UNION ALL` without the `DISTINCT ON`
dedup, which made `latest_date` and `previous_date` land on the same calendar day for ~40% of ads
whenever the primary/backfill overlap window covered both tables — silently zeroing out
`incremental_reach` for those ads.

---

## 6. Category logic — ground-truth reference (`backend/qa/test_02_category_logic.py`)

The QA suite's own reference implementation (matches `refresh_summary_table.py`'s `CASE`, minus
"Result Awaited"):

```python
VALID = {"Incremental Winner", "Winner", "P0 analysis",
         "P1 analysis", "P2 analysis", "Discarded"}

def expected_category(f1, f2, f3, f4) -> str:
    if f1 and (f2 or f3) and f4: return "Incremental Winner"
    if f1 and (f2 or f3):        return "Winner"
    if f1 and f4:                return "P0 analysis"
    if f1:                       return "P1 analysis"
    if f2:                       return "P2 analysis"
    return "Discarded"
```

Invariants it asserts: no `Discarded` row has `f1_pass OR f2_pass` true; every `Winner` /
`Incremental Winner` row satisfies `f1_pass AND (f2_pass OR f3_pass)`.

`qa/test_03_ae_table_view.py`'s constants (checked against `ae_table_view` directly):

```python
F1_IMP  = 50_000
F2_ROAS = 3.2
F3_CPN  = 525
F4_CPF  = 25        # comment claims "copied from refresh_ae_table.py" -- but that
                     # file's actual SQL uses 12, not 25 (see §3)
```

Its flag checks run as `WHERE {expr} IS DISTINCT FROM {flag_col}` and are downgraded to
`suite.warn(...)` rather than `fail` on mismatch — i.e. the test suite already tolerates this exact
F4 drift. Also asserts `SUM(amount_spent_inr) FROM backfill_table` reconciles to within 0.01% of
`SUM(amount_spent) FROM ae_table_view`, and that `ae_raw_view.refreshed_at` freshness is ≤30h (warn
≤48h, fail beyond).

---

## 7. Incremental reach — `get_ireach_incremental_analysis` RPC (full SQL, quoted in full)

This is the one incremental-reach RPC whose complete body **is** checked into the repo (in
`backend/_migrate_ireach_rpc_add_ad_level.sql`), and the best available full-SQL analog for the
missing `rebuild_new_incr_table` family (§ open items, item 4).

Upstream ingestion feeding this function is pure pass-through (no computation) from three scripts:

- `fetch_meta_ireach_daily.py` — daily unique reach at campaign/adset level, fetched directly from
  `/insights` (not summed from ad-level `primary_table.reach`, because *"the same user seeing two
  ads in the same campaign is counted twice"*). Writes `ireach_campaign_daily` / `ireach_adset_daily`.
- `fetch_adset_camp_reach.py` — writes `primary_adset_table` / `primary_camp_table` (the "primary
  window" source, vs. `ireach_*_daily`'s long-history source).
- `fetch_ireach_cumulative.py` — writes `ireach_cumulative_daily`: **cumulative** (not daily) unique
  reach per `(level, entity_id, date)`, computed by calling `/insights` with a growing
  `time_range` window `[2025-01-01, date]`. This growing-window trick is what turns incremental
  reach into a pure subtraction downstream.

```sql
CREATE OR REPLACE FUNCTION public.get_ireach_incremental_analysis(
  from_date date,
  to_date   date,
  level_arg text DEFAULT 'campaign'
)
RETURNS TABLE(
  entity_id         text,
  entity_name       text,
  account_name      text,
  n_days            integer,
  cum_at_start_prev bigint,
  cum_at_end        bigint,
  incr_reach        bigint,
  spend             numeric,
  cost_per_1k_incr  numeric
)
LANGUAGE sql STABLE AS $$
  WITH
  cum_start AS (
    SELECT DISTINCT ON (entity_id)
      entity_id, entity_name, account_name,
      cumulative_reach AS cum_at_start_prev
    FROM public.ireach_cumulative_daily
    WHERE level = level_arg AND date < from_date
    ORDER BY entity_id, date DESC
  ),
  cum_end AS (
    SELECT DISTINCT ON (entity_id)
      entity_id, entity_name, account_name,
      cumulative_reach AS cum_at_end,
      date             AS end_date
    FROM public.ireach_cumulative_daily
    WHERE level = level_arg AND date >= from_date AND date <= to_date
    ORDER BY entity_id, date DESC
  ),
  spend_camp AS (
    SELECT campaign_id::text AS entity_id,
           SUM(spend_daily)::numeric AS spend,
           COUNT(DISTINCT date)::int AS n_days
    FROM public.ireach_campaign_daily
    WHERE level_arg = 'campaign' AND date BETWEEN from_date AND to_date
    GROUP BY campaign_id
  ),
  spend_adset AS (
    SELECT adset_id::text AS entity_id,
           SUM(spend_daily)::numeric AS spend,
           COUNT(DISTINCT date)::int AS n_days
    FROM public.ireach_adset_daily
    WHERE level_arg = 'adset' AND date BETWEEN from_date AND to_date
    GROUP BY adset_id
  ),
  spend_account AS (
    SELECT account_id::text AS entity_id,
           SUM(spend_daily)::numeric AS spend,
           COUNT(DISTINCT date)::int AS n_days
    FROM public.ireach_campaign_daily
    WHERE level_arg = 'account' AND date BETWEEN from_date AND to_date
    GROUP BY account_id
  ),
  spend_ad_union AS (
    SELECT ad_id::text AS entity_id, date,
           amount_spent_inr::numeric AS spend, 1 AS priority
      FROM public.primary_table
     WHERE level_arg = 'ad' AND ad_id IS NOT NULL AND ad_id <> ''
       AND date BETWEEN from_date AND to_date
    UNION ALL
    SELECT ad_id::text, date, amount_spent_inr::numeric, 2
      FROM public.backfill_table
     WHERE level_arg = 'ad' AND ad_id IS NOT NULL AND ad_id <> ''
       AND date BETWEEN from_date AND to_date
  ),
  spend_ad_dedup AS (
    SELECT DISTINCT ON (entity_id, date) entity_id, date, spend
      FROM spend_ad_union ORDER BY entity_id, date, priority
  ),
  spend_ad AS (
    SELECT entity_id, SUM(spend)::numeric AS spend, COUNT(DISTINCT date)::int AS n_days
      FROM spend_ad_dedup GROUP BY entity_id
  ),
  spend_all AS (
    SELECT * FROM spend_camp
    UNION ALL SELECT * FROM spend_adset
    UNION ALL SELECT * FROM spend_account
    UNION ALL SELECT * FROM spend_ad
  )
  SELECT
    e.entity_id, e.entity_name, e.account_name,
    COALESCE(sp.n_days, 0)                                               AS n_days,
    COALESCE(s.cum_at_start_prev, 0)::bigint                             AS cum_at_start_prev,
    e.cum_at_end::bigint                                                 AS cum_at_end,
    GREATEST(0, e.cum_at_end - COALESCE(s.cum_at_start_prev, 0))::bigint AS incr_reach,
    COALESCE(sp.spend, 0)::numeric                                       AS spend,
    CASE
      WHEN GREATEST(0, e.cum_at_end - COALESCE(s.cum_at_start_prev, 0)) > 0
      THEN (COALESCE(sp.spend, 0) * 1000.0
           / GREATEST(0, e.cum_at_end - COALESCE(s.cum_at_start_prev, 0)))::numeric
      ELSE NULL
    END                                                                  AS cost_per_1k_incr
  FROM cum_end e
  LEFT JOIN cum_start  s USING (entity_id)
  LEFT JOIN spend_all sp USING (entity_id);
$$;

GRANT EXECUTE ON FUNCTION public.get_ireach_incremental_analysis(date, date, text) TO anon, authenticated, service_role;
```

Formula in plain terms: `incr_reach = MAX(0, cumulative_reach_at_end - cumulative_reach_just_before_from_date)`,
`cost_per_1k_incr = spend * 1000 / incr_reach` (NULL when `incr_reach = 0`).

---

## 8. `shopify_ad_attribution` — order-to-ad attribution (`backend/rebuild_attribution_orders.py`)

One row per Shopify order. A 5-tier cascade attributes each order to a Meta ad (legacy T1–T4
terminology survives as internal variable/comment names).

### Cascade order (exact — order matters)

1. **T0 override** (checked before Step 1): manual `utm_content` substring → `target_ad_id` from an
   `ad_attribution_overrides` table, sorted longest-pattern-first, logged as `"Step 1"`.
2. **Step 1**: `utm_content` is a numeric string equal to a known `ad_id`.
3. **Step 3 EARLY**: if `utm_term`/`AdSetID` custom attribute names a known adset, try a
   scoped match within it *before* falling through to the global Step 2 — prevents a
   globally-named clone of an ad from beating the real active ad in that adset.
4. **Step 2**: `utm_content`/`Ad` custom attribute matches an `ad_name` globally — tried in order:
   exact → `norm_name()` fuzzy (suffix-stripped, lowercased) → substring (plain and
   separator-normalized, minimum match length 10 chars), ties broken by highest lifetime spend then
   closest name-length.
5. **Step 3 (global asset-id)**: `utm_content` contains a user-managed `asset_id` (from
   `ad_asset_ids`) as a substring — longest `asset_id` wins, ties broken by lifetime spend.
6. **Step 3 (adset-scoped, base)**: `utm_term`/`AdSetID` names a known adset but couldn't narrow to
   one ad — attributed to the adset only (`ad_id=''`); the tiered spread in §3 (`t3_spread`)
   distributes it by spend.
7. **Step 4 (campaign-scoped)**: same as Step 3 but at campaign level (`utm_campaign` numeric →
   `campaign_id`, or `Campaign` custom attribute / `utm_campaign` → `campaign_name`).
8. **Step 5**: no match — all attribution fields empty, `has_match = false`.

### Fuzzy name matching

```python
SUFFIX_RE = re.compile(r"(?:[\s_-]+(?:copy(?:\s*\d+)?|[hc]\d+))+\s*$", re.IGNORECASE)

def norm_name(n):
    if not n:
        return ""
    n = n.strip()
    while True:
        new = SUFFIX_RE.sub("", n).strip()
        if new == n:
            break
        n = new
    return re.sub(r"\s+", " ", n).strip().lower()
```

`_scoped_match()` (the inner cascade used within a known adset/campaign) tries, in order: exact name
→ asset-id substring (unique / spend-tiebreak) → fuzzy `norm_name` → substring → separator-normalized
substring → token-subset match. The token-subset match requires ≥3 utm tokens with at least 1
"distinctive" token (length ≥5, non-numeric), scored as `|utm ∩ ad_tokens| / |ad_tokens|`, accepted
only if the top ratio is ≥0.6 and beats the runner-up by ≥0.15.

**Global substring-match minimum-length guard** (prevents an unrelated 2-character coincidence from
counting as a match):

```python
# matched substring (whichever side is shorter) must be >= 10 chars
if (cand_l in nl) or (nl in cand_l):
    if min(cand_l_len, nlen) >= 10:
        matched = True
```

**Ad universe**: `DISTINCT` union of `primary_table` ∪ `backfill_table`
(`ad_id, ad_name, adset_id, adset_name, campaign_name, campaign_id, ad_created_date`), enriched with
`ad_name_history` (Meta bakes the *original* ad name into `utm_content` at ad-launch time, so
historical renames must be matchable too) and `ad_asset_ids` (manual asset-id mapping).

---

## 9. `ad_results` — separate 3-state lifecycle model (`backend/result_classifier.py`)

Per `(account_name, ad_id)`. Runs independently of the 6/7-category model in §4/§6, writes a
different table, and shares only the F1 impression threshold and the 14-day window concept.

```python
WINDOW_DAYS = 14
IMPRESSION_THRESHOLD = 50_000

eval_end = created + timedelta(days=WINDOW_DAYS)   # created = ad_created_date
impr_14d = sum(imp for _, imp, _ in window_rows)   # primary_table rows, created <= date <= eval_end

if impr_14d >= IMPRESSION_THRESHOLD:
    status = "Winner"
elif today <= eval_end:
    status = "Result Pending"
else:
    status = "Failed"
```

**Crossed-threshold date** — first date within the 14-day window where cumulative impressions
(within-window only) hit 50,000:

```python
crossed = None
cum = 0
for d, imp, _ in window_rows:   # sorted ascending by date, filtered to [created, eval_end]
    cum += imp
    if cum >= IMPRESSION_THRESHOLD:
        crossed = d
        break
```

Lifetime totals (`impressions_total`, `impressions_last_day`, `spend_total`) are also computed,
independent of the 14-day window, for reporting only — they don't affect `status`.

`ad_results` table (per the checked-in migration — see open items, item 5, for the columns this
migration is missing):

```sql
CREATE TABLE IF NOT EXISTS ad_results (
    account_name         TEXT        NOT NULL,
    ad_id                TEXT        NOT NULL,
    ad_name              TEXT,
    campaign_name        TEXT,
    ad_status            TEXT,
    ad_created_date      DATE,
    evaluation_end_date  DATE,
    impressions_14d      BIGINT      DEFAULT 0,
    crossed_threshold_at DATE,
    result_status        TEXT        NOT NULL,
    last_computed_at     TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (account_name, ad_id)
);

CREATE INDEX IF NOT EXISTS idx_ad_results_status         ON ad_results (result_status);
CREATE INDEX IF NOT EXISTS idx_ad_results_account_status  ON ad_results (account_name, result_status);
CREATE INDEX IF NOT EXISTS idx_ad_results_eval_end         ON ad_results (evaluation_end_date);
CREATE INDEX IF NOT EXISTS idx_ad_results_created           ON ad_results (ad_created_date);
```

---

## 10. `summary_table` Excel enrichment (`backend/apply_ctp_unique_ids.py`)

Periodic enrichment from an external file (`CTP unique ids.xlsx`), mirroring a legacy Google Apps
Script (`SubsheetMatch.gs`).

**Rank scale**, used to pick the displayed result label when Excel says "Tested":

```python
RANK = {
    "incremental winner": 5,
    "winner":             4,
    "iteration":          3,
    "priority":           3,   # alias
    "analyse":            2,
    "analyze 1":          2,   # alias
    "analyze 2":          2,   # alias
    "discarded":          1,
}
LABEL = {5: "Incremental Winner", 4: "Winner", 3: "Iteration", 2: "Analyse", 1: "Discarded"}
```

**Matching guard** — prevents a short ID like `"GAD-Apr-4"` from matching inside `"GAD-Apr-48"`:

```python
def _matches_with_boundary(hay_lower, needle_lower):
    pos = 0
    L = len(needle_lower)
    while True:
        p = hay_lower.find(needle_lower, pos)
        if p < 0:
            return False
        next_ch = hay_lower[p + L] if (p + L) < len(hay_lower) else ""
        if not next_ch.isdigit():
            return True
        pos = p + 1
```

IDs are tried longest-first; first hit wins per ad (nested IDs are ruled out by the boundary guard,
so it's naturally single-ID-per-ad).

**Result derivation once matched** — Excel is authoritative for whether an ad is "Tested"/"Pending",
but if "Tested", the *displayed result label* is re-derived from the ad's own `summary_table.status`
via `RANK`/`LABEL`, not taken verbatim from Excel's own "Result" column:

```python
excel_st = (info["status"] or "").strip()
derived_status = excel_st if excel_st else None
if excel_st.lower() == "tested":
    ad_rank = _rank(db_status)   # db_status = summary_table.status
    derived_result = LABEL.get(ad_rank) if ad_rank else (info["result"] or None)
else:
    derived_result = info["result"] or None
```

```sql
ALTER TABLE summary_table
  ADD COLUMN IF NOT EXISTS excel_id_matched TEXT,
  ADD COLUMN IF NOT EXISTS excel_status     TEXT,
  ADD COLUMN IF NOT EXISTS excel_result     TEXT;
```

---

## 11. Migrations (verbatim, both short)

```sql
-- migrations/2026_05_09_add_link_columns.sql
ALTER TABLE primary_table
  ADD COLUMN IF NOT EXISTS preview_link TEXT,
  ADD COLUMN IF NOT EXISTS ad_link      TEXT;

-- preview_link -> Meta /<ad_id>?fields=preview_shareable_link
-- ad_link      -> Meta /<ad_id>?fields=creative{link_url, object_story_spec{link_data{link}}, object_url}
--                 picks the first non-empty in that order
```

(`migrations/2026_05_09_ad_results.sql` is quoted in full in §9.)

---

## Formula quick-reference (all in one place)

| Metric | Formula | Guard |
|---|---|---|
| ROAS | `conv_value / amount_spent` | `amount_spent > 0`, else 0 |
| Cost per NCP | `amount_spent / ncp_count` | `ncp_count > 0` |
| Cost per FTEWV | `amount_spent / ftewv_count` | `ftewv_count > 0` |
| CTR | `link_clicks / impressions * 100` | `impressions > 0` |
| CPM | `spend / impressions * 1000` | `impressions > 0` |
| Cost per 1000 reach | `amount_spent / reach * 1000` | `reach > 0` |
| Cost per purchase | `spend / purchases` | `purchases > 0` |
| Checkout completion % | `purchases / checkout_initiated * 100` | `checkout_initiated > 0` |
| Add-to-cart rate | `add_to_cart / link_clicks * 100` | `link_clicks > 0` |
| Profit efficiency | `conv_value - amount_spent` | — |
| Contribution margin % | `(1 - amount_spent/conv_value) * 100` | else `-100` |
| Incremental reach | `MAX(0, cum_reach_at_end - cum_reach_just_before_window)` | — |
| Cost per 1k incremental reach | `spend * 1000 / incr_reach` | `incr_reach > 0`, else NULL |

| Filter | Formula | Value used in `refresh_ae_table.py` | Value used in `refresh_summary_table.py` | GUIDEBOOK.md |
|---|---|---|---|---|
| F1 (impressions) | `impressions >= X` | 50,000 | 50,000 | 50,000 |
| F2 (ROAS) | `conv_value/spend >= X` | 3.2 | 3.2 | 3 (prose/UI default) |
| F3 (₹/NCP) | `spend/ncp <= X` | 525 | 525 | 525 |
| F4 (₹/FTEWV) | `spend/ftewv <= X` | **12** | **25** | **25** (prose) / **12** (toolbar default) |

---

## Category rule ordering (6-category reference; `summary_table` adds a 7th, "Result Awaited")

```
Incremental Winner    F1 AND (F2 OR F3) AND F4    scale aggressively, top-tier proven
Winner                F1 AND (F2 OR F3)           scale; iterate on F4/creative quality
P0 analysis           F1 AND F4                    impressions + cheap FTEWV; iteration target
P1 analysis            F1 only                       hit impressions, no ROAS/NCP/FTEWV signal yet
P2 analysis            F2 only                       strong ROAS but still building impressions
Discarded               else                            no signal -- cut spend or rework creative
```
