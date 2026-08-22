---                                                                                                                                                                    
  # CARRY-FORWARD CONTEXT — Creative Testing Dashboard backend rewrite (medallion)
                                                                                                                                                                         
  ## Project one-liner                                  
  Full-stack analytics dashboard for saadaa.in — a D2C women/men/unisex apparel
  brand — covering Meta Ads (3 accounts) × Shopify orders × Instagram organic ×
  Google Ads. Frontend is a single-page vanilla-JS dashboard reading Supabase
  via PostgREST. Backend today is 40+ imperative Python scripts writing directly
  into 55 tables in a Supabase Postgres called Meta_ads_data (project ref
  `rtkohjfzyzhizkebdsuy`). You are being asked to design a clean rewrite as a
  BRONZE → SILVER → GOLD medallion pipeline. Preserve every business rule
  below; the numbers must reconcile row-for-row with the current dashboard.

  ## Repo layout (only what matters)
  D:/Creative_Testing_Dashboard/
  ├── backend/
  │   ├── primary_sync.py                    ← Meta insights pull (BRONZE)
  │   ├── propagate_primary_to_backfill.py   ← backfill mirror
  │   ├── refresh_ae_table.py                ← Ads Analyse rollup (SILVER)
  │   ├── refresh_summary_table.py           ← per-ad lifetime rollup (SILVER)
  │   ├── refresh_ae_reach_recent.py         ← latest 2-day reach snapshot
  │   ├── refresh_new_incr_table.py          ← per-ad incremental reach + camp/adset rollups
  │   ├── fetch_meta_ireach_daily.py         ← Meta unique-reach per day per campaign/adset
  │   ├── fetch_ireach_cumulative.py         ← 3-year cumulative reach backfill (--level account/campaign/adset/ad)
  │   ├── _refresh_ireach_ad_daily.py        ← ad-level spend helper for reach RPC
  │   ├── fetch_google_ads_daily.py          ← Google Ads → google_ads_primary
  │   ├── refresh_google_ads_summary.py      ← Google Ads rollup
  │   ├── result_classifier.py               ← writes ad_results (F1-F4 category)
  │   ├── fetch_shopify_sessions.py          ← ShopifyQL sessions per landing page (daily)
  │   ├── sync_shopify_customers.py          ← Shopify customer table
  │   ├── sync_orders_via_rest.py            ← Shopify orders → sibling project (Saada_Shopify_Data siymyhhrpzzbowfqtauf)
  │   ├── import_asset_id_sheet.py           ← CTP-Asset_Sheet_v1 External tab → ad_asset_ids
  │   ├── apply_ctp_unique_ids.py            ← writes summary_table.excel_id_matched
  │   ├── rebuild_attribution_orders.py      ← FULL attribution rebuild (INTENTIONALLY skipped from daily runner)
  │   ├── reattribute_all.py                 ← alt entrypoint used to trigger from CLI
  │   ├── reattribute_t3_t4_unmatched.py     ← reattribute rows that ended up at coarse tiers
  │   ├── recover_t3_global_substr.py        ← fill in obvious global-substring recoveries
  │   ├── results_sync.py                    ← dashboard fast-path cache into results_table (GOLD-ish)
  │   ├── fetch_ad_thumbnails.py             ← Meta creative thumbnails (slow, 5h under throttle)
  │   ├── _build_ad_utm_mode.py              ← MODE() aggregate helper for Google Sheets
  │   ├── _build_ae_daily_30d.py             ← 30-day per-day per-ad rollup
  │   ├── _refresh_ireach_ad_daily.py        ← spend at ad-level for reach RPC
  │   ├── refresh_product_doq.py             ← product-level daily order quantity
  │   ├── fetch_content_asset_register.py    ← mirrors external content_workflow_optimiser (npxpywozmrptzzytzdmg) asset_register + brief join
  │   ├── fetch_graphic_sheet.py             ← mirrors CTP-Asset_Sheet_v1 Graphic tab (gid 655330043)
  │   ├── fetch_historic_video_assets.py     ← 3 deprecated tabs of CTP-Asset_Sheet_v1
  │   ├── fetch_cpis_by_sku.py               ← per-master-SKU sales × inventory × Meta cost + daily rollups + RPC
  │   ├── fetch_ig_media.py + fetch_ig_media_posts.py + fetch_ig_profiles_min.py
  │   ├── ingest_bq_inventory.py + sync_shopify_products.py
  │   ├── _run_meta_update_preserve_attr.py  ← THE canonical pipeline runner (see step list below)
  │   ├── supabase_config.py                 ← loads SUPABASE_DB_URL from .env
  │   ├── .env                               ← DO NOT read directly; launch scripts that use dotenv
  │   └── logs/, migrations/, apps_script/
  ├── assets/dashboard.js  (9k lines)
  ├── index_v2.html   (v2 sidebar dashboard — the one users hit)
  ├── index.html      (legacy v1, still deployed at /index.html)
  └── ads_analyse_static.html (embed)

  ## Environments (all in backend/.env, BOM-free — python-dotenv silently breaks on BOM)
  SUPABASE_DB_URL              # postgres pooler for Meta_ads_data
  SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY
  SHOPIFY_DATA_URL             # https://siymyhhrpzzbowfqtauf.supabase.co
  SHOPIFY_DATA_ANON            # anon key for the Shopify project
  SHOPIFY_DATA_DB_URL          # pooler for Shopify project
  ADMIN_ACCESS_TOKEN + SHOP_DOMAIN + SHOPIFY_API_VERSION   # Shopify Admin GraphQL
  META_ACCESS_TOKEN + META_API_VERSION                     # Meta Graph v22.0 (throttle bucket X-App-Usage)
  GOOGLE_ADS_DEVELOPER_TOKEN + GOOGLE_ADS_LOGIN_CUSTOMER_ID
  CONTENT_WORKFLOW_URL + CONTENT_ANON_KEY + CONTENT_SERVICE_KEY  # external content_workflow_optimiser Supabase

  ## The 3 Meta ad accounts (hard-coded fallback in primary_sync)
  Raho Saadaa            act_1136644150469466
  Fourth Ad Account - SD act_1349767139294217
  Third Ad Account - SD  act_264868699479122       # frequently returns Meta 500s

  ## Two Supabase projects, five domains
  Meta_ads_data (rtkohjfzyzhizkebdsuy) — everything ads / attribution / dashboard reads
  Saada_Shopify_Data (siymyhhrpzzbowfqtauf) — raw Shopify orders + sessions
  + external content_workflow_optimiser (npxpywozmrptzzytzdmg) — content register mirrored in
  + Google BigQuery for the Shopify inventory dataset (ingest_bq_inventory.py)
  + Google Ads API for GAds

  ## Bronze / raw ingestion tables (write-once per sync)
  primary_table                one row per (account_name, ad_id, date) from Meta insights (~600k rows)
  backfill_table               UNION of primary_table + historical dump, refreshed by propagate_primary_to_backfill
  google_ads_primary + google_ads_daily
  ireach_ad_daily / ireach_adset_daily / ireach_campaign_daily / ireach_cumulative_daily
                               Meta unique-reach at 4 grains, populated by fetch_meta_ireach_daily + fetch_ireach_cumulative
  ad_thumbnails                creative preview URLs per ad (fetch_ad_thumbnails)
  ad_asset_ids                 ad_id → asset_id from CTP-Asset_Sheet_v1 External tab (via import_asset_id_sheet)
  ad_ctype_overrides + ad_attribution_overrides
                               manual T0 overrides driving the attribution cascade
  ad_name_history              Meta ad rename activity log
  active_ads_meta              latest metadata per ad_id (name/status)
  ig_media + ig_media_tagged_by  Instagram organic
  shopify_products + inventory_snapshot + bq_inventory_daily
                               Shopify catalog + BigQuery inventory
  content_asset_register (mirror of external asset_register + joined briefs.shoot_required/aspect_ratio)
  content_graphic_register (mirror of CTP-Asset_Sheet_v1 Graphic tab, gid 655330043)
  content_historic_video_register (mirror of 3 deprecated video tabs)

  ## Silver / derived rollup tables (recomputed each pipeline pass)
  ae_table_view                one row per ad; 66 cols; result of refresh_ae_table (drops+recreates the table)
  ae_raw_view                  same-grain intermediate used by refresh_ae_table
  summary_table                per-ad lifetime aggregate (total_impressions/spend/conv_value/etc.) + shopify_orders/sales/roas + Excel matching flags
  ae_shopify_enriched          per-ad shopify aggregate; joined into ae_table_view for shopify_orders/sales
  shopify_ad_agg               per-ad shopify aggregate feeding ae_shopify_enriched
  ae_reach_recent              per-ad latest 2-day unique reach snapshot (yesterday vs day-before)
  ae_freq_lifecycle_mat        frequency-lifecycle materialised
  new_incr_table (~330k) + new_incr_adset_table + new_incr_camp_table  incremental reach rollups
  primary_adset_table + primary_camp_table  group-by-adset/campaign rollups of primary_table
  ad_results                   F1-F4 filter pass/fail + category (Winner/Priority/Analyse/Discarded/Result Awaited/Incremental Winner)
  google_ads_summary           per-Google-campaign aggregate
  ad_utm_mode                  MODE() WITHIN GROUP aggregate for Google Sheet helper
  ae_daily_30d                 30-day per-day per-ad rollup for the Sheet
  product_doq_daily            daily order-quantity per product
  landing_page_analysis_30d + landing_page_ad_breakdown_30d + landing_page_sessions_daily
                               Landing page rollups joined with primary_table.ad_link
  rck_daily_30d + rck_last30   RCK-specific rollups
  _v2_*                        materialised join tables used by rebuild_attribution_orders

  ## Gold / consumer tables (what the browser reads)
  results_table                dashboard fast-path snapshot (30d rolling per account); if stale the frontend does slow live 180k-row aggregate — DO NOT skip results_sync
  shopify_ad_attribution       ONE row per shopify order after cascade attribution — the truth table
  shopify_ad_attribution_l30   30-day slice used by the Sheet
  shopify_ad_attribution_v2    experimental v2 rebuild
  cpis_by_sku                  per-master-SKU × window (1d/7d/30d) × level (master/color)
  cpis_daily_sales             (day, product_title) — sales per day for CPIS live filter
  cpis_daily_ad_stats          (day, master_sku, ad_id) — per-master ad spend for CPIS
  + RPC get_cpis_ad_stats(from,to) returns per-master aggregates (arithmetic-mean per-ad Cost/NCP)
  + RPC get_ae_metrics_by_window(from,to) returns per-ad windowed metrics (used by AE + CPIS reconciliation)
  + RPC get_ireach_incremental_analysis(...)

  ## Canonical pipeline (from _run_meta_update_preserve_attr.py — 22 steps, ~7-8 hrs full run)
   1. primary_sync.py daily            15-day Meta insights pull, upsert into primary_table  (~5-30 min)
   2. propagate_primary_to_backfill    UPDATE backfill_table from primary_table (last 15d) + INSERT missing
   3. apply_ctp_unique_ids             read CTP unique-ids xlsx, set summary_table.excel_id_matched
   4. refresh_ae_table                 drop+recreate ae_table_view from primary_table (~2 min, 17k ads)
   5. refresh_summary_table            per-ad lifetime aggregate
   6. refresh_ae_reach_recent          latest 2-day reach snapshot from primary_table
   7. refresh_new_incr_table           per-ad incremental reach (row=333k) + camp/adset rollups
   8. fetch_meta_ireach_daily          per-day unique reach for each account × campaign + adset
   9. fetch_ireach_cumulative account  3-year cumulative reach backfill (1097 days × 3 accts ≈ 60 min @ 0.86/s under Meta throttle)
  10. fetch_ireach_cumulative campaign same, campaign grain
  11. fetch_ireach_cumulative adset    same, adset grain
  12. _refresh_ireach_ad_daily         ad-level spend for the Incremental Analysis RPC
  13. fetch_google_ads_daily           Google Ads API pull → google_ads_primary
  14. refresh_google_ads_summary       rebuild google_ads_summary
  15. result_classifier                writes ad_results with F1/F2/F3/F4 pass flags + category
  16. fetch_shopify_sessions           7 days of ShopifyQL sessions per landing_page_path
  17. sync_shopify_customers           full customer list ~1.2M+ customers (this ONE step took 7.5h in our last run — the script has no incremental mode)
  18. import_asset_id_sheet            cross-check every (ad_id, asset_id) pair against summary_table.ad_name; keep only mappings where the asset_id string appears in the
   ad's own name
  19. results_sync                     dashboard fast-path cache into results_table (~10 min)
  20. rebuild_attribution_orders       *** INTENTIONALLY SKIPPED *** would clobber manual T0 overrides
  21. fetch_ad_thumbnails              Meta creative previews (~5 h under throttle, resumable)
  22. _build_ad_utm_mode + _build_ae_daily_30d   Google Sheet helpers

  ## Shopify orders sync — separate cadence
  sync_orders_via_rest.py --since <ISO>  fetches orders from Shopify Admin GraphQL and upserts into Saada_Shopify_Data.public.orders (project siymyhhrpzzbowfqtauf) at ~25
   rows/sec. Default --since is 2026-05-19 (this must be swapped to an incremental delta in production). Older 6-month backfill was `fetch_shopify_orders_6m.py`.

  ## ORDER ATTRIBUTION — the crown jewel logic (rebuild_attribution_orders.py::attribute_order)

  Every Shopify order carries customAttributes and UTM params captured at checkout: {utm_source, utm_medium, utm_campaign, utm_content, utm_term, Ad, Campaign, AdSetID}.
  We attribute each order to at most one Meta ad_id via a strict cascade. TIERS ARE ORDERED — first hit wins.

    T0  OVERRIDE (public.ad_attribution_overrides — pattern → target_ad_id)
        Runs BEFORE Step 1. Sorted longest-pattern-first. utm_content LOWER-CONTAINS pattern → route to target_ad_id (if target exists in primary_table universe). Emits
  tier = "Step 1", matched_value = pattern. Used to consolidate paused-clone attribution back to the active creative.

    T1  utm_content is a NUMERIC ad_id present in by_id → Step 1 direct.

    T3-early  ADSET-SCOPED override of Step 2
        For adset_cand in (customAttributes.AdSetID, utm_term):
          if adset_cand ∈ adset_ads and _scoped_match(ads_in_adset, name_cand, order_date, "adset") narrows to one ad → attribute there.
        Purpose: prevents a globally-named clone (archived "Copy" ad with 0 spend) from beating the real active ad in the user-tagged adset. Falls through to Step 2 if
  adset scope can't narrow.

    T2  Global ad_name match
        For cand in (customAttributes.Ad, utm_content):
         (a) exact match against by_name
         (b) fuzzy match (suffix-stripped, lowercased — norm_name)
         (c) global substring / sep-normalised substring — MUST have min-length 10 on shorter side to avoid coincidental short matches like "ER". Tiebreak: highest
  lifetime spend WINS (Meta actually delivered it); secondary tiebreak = smallest ad_name length gap.

    T3  Global asset_id substring (backed by ad_asset_ids)
        For each (asset_id_lower, ad_id, spend) in asset_index:
          if asset_id in utm_content.lower() → candidate. Longest asset_id wins; tie broken by highest lifetime spend.

    T3.x  ADSET-SCOPED match (utm_term / AdSetID → adset; narrow within)
        Same as T3-early but runs after T3 global. If narrowing to one ad fails → return the adset's first ad with ad_id=NULL emitting matched_value = adset_cand and
  tier="Step 3" (downstream Step-3-spread aggregator handles it).

    T4  CAMPAIGN-SCOPED match (utm_campaign → campaign; narrow within)
        Same shape as T3.x but scoped to campaign. If narrowing fails → return the campaign's first ad with ad_id=NULL emitting tier="Step 4".

    T5 / NULL  Nothing pinned. Returns empty strings, tier stays NULL.

  Substring guards:
    * min-length 10 on the shorter side for Step-2 substring (prevents "ER" catching)
    * asset_id substring uses raw lowercase (asset_ids are unique per-creative, rename-stable, so shorter allowed)
    * Numeric ad_id check requires isdigit() AND presence in by_id

  Manual reweight / reassign scripts (kept as one-off SQL migrations, NOT in the daily pipeline):
    _reassign_megha_to_divya_post_cutoff.py     BR_IFAD_MEGHA_20/02/25 orders after 2025-04-22 → active DIVYA ad 120222271965800422 (creative was renamed)
    _reassign_foundersad_post_cutoff.py         FoundersAd renames after cutoff → new active ad
    _reassign_ravi_utm_term_null.py             null utm_term Ravi-tagged orders reassigned
    _reweight_smcp_step1_first.py               SMCP Step-1-first weighting fix
    _reweight_smcp_hashed.py                    SMCP_VRP_UB_US_916_Sep-682 4-ad pool re-split hash-based, weights = lifetime-spend-proportional
    _reweight_smcp_vrp_ub.py                    same adset (120233707955260431) alternate weighting
    _reweight_sdamk_hashed.py                   SDAMK_VRP_CR hashed
    _reweight_sdamk_vrp_cr.py                   SDAMK_VRP_CR non-hashed
    _unmatch_jan845_plus_campaign.py            manual unmatch of stale campaign orders
    _unmatch_step4_no_term.py                   step4 no-term orders unmatched
    All these run inside a single transaction and re-sync shopify_ad_agg + summary_table + ae_shopify_enriched for the source AND target ad_ids they touched.

  CANONICAL WARNING: rebuild_attribution_orders.py is DELIBERATELY SKIPPED from _run_meta_update_preserve_attr.py because it re-derives every row from raw UTMs and
  CLOBBERS every manual reweight/reassign above. If your medallion rewrite recomputes attribution from bronze, you MUST replay the manual reassign rules on top (they are
  effectively additional T0 rules) — either by moving them into ad_attribution_overrides as substring→target_ad_id patterns (preferred) or by keeping a
  "manual_overrides_ledger" that gets applied after the cascade.

  ## Where the manual attribution work lives
  public.ad_attribution_overrides (pattern TEXT, target_ad_id TEXT) — used by T0
  public.ad_ctype_overrides — content-type override
  Various `matched_value` markers in shopify_ad_attribution flag the source: 'spend-weight', 'spend-weight-hashed', 'slug-inherit'.

  ## Frequently-used business rules embedded in scripts
    * "Excl. copy" toggle — hides ads whose name contains word "copy" (frontend Multi-Filter)
    * F1 = impressions ≥ 50k, F2 = ROAS ≥ 3 OR Cost/NCP ≤ 525, F3 = Cost/FTEWV ≤ 12, F4 = pass either shopify or Meta cost benchmarks
    * Incremental Winner = F1 ∧ F2 ∧ F3 ∧ F4  (all four)
    * Winner = F1 ∧ (F2 ∨ F3)                  (three pass, F4 optional)
    * P0/P1/P2 Analysis / Discarded / Result Awaited derived downstream
    * Master SKU rule: ^(SD|SM|SU)[A-Z]{1,4}$   — SD=women, SM=men, SU=unisex, +1-4 chars
    * Colour variant SKU = master + 2-char colour code (SDCPBL, SMCPGR)
    * Size variant SKU = color + _<size> (SDCPBL_L, SMCPBL_XL)
    * Ad name conventions vary per account — regex-based parsing lives in refresh_ae_table.py

  ## Idempotence + failure modes (learned the hard way)
    * primary_sync is idempotent per (ad_id, date) via ON CONFLICT UPSERT. Placeholders inserted for non-delivering active ads so ae_table_view has a row for every ACTIVE
   ad even on days with 0 impressions.
    * Meta 500 / 400 retry logic is INSIDE primary_sync (3 retries, 15s/30s backoff, then skip page). Do not double-retry.
    * fetch_ireach_cumulative uses per-day cursor and can be resumed by rerunning; each account × level is independent.
    * fetch_ad_thumbnails is resumable via last-fetched-ad checkpoint.
    * sync_orders_via_rest writes a cursor file `.shopify_orders_6m_progress.json` — DO NOT trust it blindly, it can hold state from a prior run.
    * Every SQL migration touching shopify_ad_attribution ALSO re-syncs shopify_ad_agg + summary_table + ae_shopify_enriched for the source AND target ad_ids. If you skip
   this, the AE table shows stale attribution.
    * Unicode box-drawing chars (── / ═) in log lines crash on Windows cp1252 consoles. Every summary print must go through `sys.stdout =
  io.TextIOWrapper(...encoding='utf-8', errors='backslashreplace')` (this is why several scripts have that boilerplate at top).
    * .env MUST NOT have a UTF-8 BOM — python-dotenv silently ignores BOM'd files. Write env with byte-level Python, not PowerShell Set-Content/Out-File.

  ## Frontend contract (what the medallion output has to serve)
    * assets/dashboard.js reads from Supabase PostgREST + a handful of RPCs
    * Views: Home / Creative Testing / Creative Lifecycle / Ads Analyse / Incremental Analysis / Last Click UTM / Landing Page / Active / Inventory / CPIS (Catalog) /
  Untested Assets (Content Workflow) / Historic Untested / Historic Ads Analysis / Historic UTM / Historic Reach
    * Each view has its own idempotent loader (loadAE, loadAdIntel, loadCogsBySku, loadUntestedAssets, loadHistoricVideoAssets, loadLandingPageTable, loadInventory,
  etc.).
    * CPIS section requires public.cpis_by_sku + public.cpis_daily_sales + public.cpis_daily_ad_stats + get_cpis_ad_stats RPC + get_ae_metrics_by_window RPC +
  primary_table (for the Ads Explorer modal reconciliation).

  ## Medallion rewrite design principles I want you to follow
    1. BRONZE = one raw table per external source, append-only, no derivations. Keep ingestion timestamp + source URL/API call. Sources: Meta insights, Meta activities
  (ad_name_history), Meta reach cumulative, Google Ads, ShopifyQL sales, Shopify orders, Shopify customers, Shopify products/inventory, BigQuery inventory, IG media, IG
  media insights, content_workflow_optimiser asset_register/briefs, CTP-Asset_Sheet_v1 (External + Graphic + 3 deprecated tabs), CTP unique-ids xlsx, ad_asset_ids
  external sheet.
    2. SILVER = deduplicated, typed, per-entity current state. One row per entity (per ad, per campaign, per adset, per product variant, per customer, per order, per
  asset). Rebuilds are idempotent from bronze.
    3. GOLD = pre-aggregated for specific dashboard queries. Every RPC the frontend calls should be a thin wrapper over a gold table (or an on-demand materialised view).
  Reconciliation columns (matched_ad_id/matched_ad_name in cpis_daily_ad_stats, AE-same-window column in CPIS Ads Explorer) exist BECAUSE past bugs came from "two sources
   agreeing to disagree" — bake row-provenance into gold.
    4. Attribution belongs in silver.attribution_orders (one row per Shopify order). T0..T5 cascade must reproduce today's output byte-identically on the same input.
  Manual overrides ledger sits in silver.attribution_overrides with (effective_from, pattern, target_ad_id, reason). The cascade READS this ledger; the medallion pipeline
   NEVER hand-rewrites the output.
    5. Everything runs on a scheduled DAG (Prefect / Dagster / Airflow — user's choice). No 7-hr monolithic bash loops. Each step declares its bronze inputs + silver/gold
   outputs so the DAG can skip unaffected downstream when nothing changed.
    6. Reconciliation harness: for a fixed date window, the medallion output for shopify_ad_attribution, ae_table_view, summary_table, results_table, cpis_by_sku must
  match the legacy output within 0.1% or the rewrite fails CI.

  ## Known open issues today
    * Ireach cumulative adset was killed at throttle 93% during our last pipeline run — needs manual resume: `python backend/fetch_ireach_cumulative.py --level adset`
    * sync_shopify_customers has no incremental mode; iterates full customer list (7h for 1.2M+ rows)
    * primary_table's `date` column is UTC-based (Meta reports); Shopify orders are stored as timestamptz. Watch this when joining.
    * SUPABASE_ANON_KEY is NOT in backend/.env — dashboard reads it from URL params. Backend scripts use SUPABASE_DB_URL (postgres pooler) instead.
    * User is on Windows / PowerShell shell. Bash tool available via Git Bash.

  ## Deliverable for your new session
  Design and prototype a medallion-architecture backend that:
    (a) ingests every bronze source above,
    (b) derives every silver table with the exact business rules preserved,
    (c) serves every gold table + RPC the dashboard currently reads,
    (d) preserves the T0..T5 attribution cascade AND all manual reweight/reassign scripts as first-class T0 override ledger entries,
    (e) replaces the 22-step imperative runner with a DAG,
    (f) ships a reconciliation harness that proves the new outputs match the legacy tables row-for-row on a fixed date window.