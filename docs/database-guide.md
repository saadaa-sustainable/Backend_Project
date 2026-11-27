# The SAADAA analytics database, for an AI reading it through MCP

One e-commerce business, four sources, 112 relations in `public`
(94 tables, 9 views, 9 materialized views). This file is the map. The
per-table detail lives in [`docs/schema/`](schema/README.md), one file
per relation, generated from the live database by
`scripts/gen_schema_docs.py`.

Read sections 1 and 2 before writing a query. They are where the wrong
answers come from — not from the SQL, but from joining two things that
measure different populations and reporting the result as one number.

---

## 0. Access is READ ONLY

**You cannot write to this database. Not a row, not a column, not a
table.**

No `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `COPY`, `ALTER`, `CREATE`,
`DROP`, `GRANT`, `REFRESH MATERIALIZED VIEW`, or `VACUUM`. No calling a
function that writes. No starting, retrying or stopping a job. No
changing a campaign, a budget or a schedule.

Every MCP tool is declared `readOnlyHint`, `destructiveHint: false`,
`idempotentHint`, and the connection runs inside a read-only
transaction guard, so a write does not merely fail policy — it fails at
the database.

**What this means in practice:**

- If a number is wrong, you **report** it. You do not correct it. The
  fix belongs in the pipeline that produced it, not in the row.
- If a table is stale, you **say so and say how stale**. You cannot
  refresh it, and you must not imply that you did or could.
- If a question can only be answered by writing — "mark these orders
  as…", "fix the campaign name…" — the answer is that you cannot, and
  who to ask.
- You are also **not** running arbitrary SQL the user hands you. The
  tools expose the dashboard's *sections*, with their definitions
  already applied. If a number is wrong on the dashboard it is wrong
  here too, identically. That is the point of it.

Reading is not free of consequence either. This instance has 256 MB of
shared buffers against ~32 GB of data (§6); an expensive scan degrades
the dashboard for everyone using it. Prefer the narrowest window that
answers the question.

---

## 1. Seven rules that override intuition

**1. There are no foreign keys. None.** Every join is inferred from
column names and must be confirmed against real data before it is
trusted. A join that returns rows is not a join that is correct.

**2. `order_id` does not join orders to fulfilments.** It looks like it
should and it returns **zero** rows. `shopify_orders.name` ↔
`shopify_fulfillments.order_name` is the working key — both hold the
display number, `#1601142`. `shopify_orders.order_id` is the Shopify
GID (`gid://shopify/Order/…`), which matches `raw_dump_shopify.source_id`
and nothing else.

**3. `ga4_order_attribution.transaction_id` IS `shopify_orders.name`.**
That is the only bridge between GA4 and the order book, and it is how a
first click is reached at all.

**4. GA4 sees about 76% of orders.** GoKwik owns the checkout, so GA4's
`purchase` event does not fire for roughly a quarter of them. Any total
taken from `ga4_order_attribution` is a quarter light against the real
book. Ratios survive this; absolute totals do not.

**5. Reach is never additive.** Not across days, not across accounts,
not across gender or region buckets. Meta dedupes within one query and
one account. Summing a 7-day window overstates true reach by 27–69%.
Impressions and spend are additive; reach, frequency and every unique\_
metric are not.

**6. Meta's own conversion figures are not the order book.** Meta's
`conv_value` runs roughly **69% above** Shopify's recorded sales for the
same campaigns and days. Both are "revenue". They are different
measurements with different attribution windows. Never mix them inside
one calculation, and always say which one a number is.

**7. Everything is Asia/Kolkata.** Meta reports in the ad account's
timezone (IST on all three accounts), orders are windowed
`(created_at AT TIME ZONE 'Asia/Kolkata')::date`, and a day boundary
taken in UTC misaligns spend against the revenue it earned by 5.5 hours.

---

## 2. The attribution model

This is the part most likely to be got wrong, because two plausible
answers exist for the same question and only one is correct here.

### Last click is OURS, never GA4's

The last click is **the UTM the order itself carries**, mapped to an ad:

```
shopify_order_attribution.utm_content  ->  matched_ad_id
```

GA4's last-click columns (`last_source`, `last_medium`, `last_campaign`,
`last_campaign_id`, `last_ad_id`, `last_adset_id`) were **dropped from
`ga4_order_attribution` on 2026-10-30** and are not coming back. If a
query references them it is written against a schema that no longer
exists.

Why: they are different measurements. GA4's last click is the ad clicked
on the *converting visit*. Ours is the UTM stamped on the order, which
can persist from a session days earlier. Carrying both meant every
reader had to know which to trust, and they disagreed — on one ad,
across dozens of orders.

`last_landing` survives in `ga4_order_attribution`. It is a **page**, not
an attribution, and the landing-page section keys on it.

### First click is GA4's, and only GA4's

`ga4_order_attribution.first_ad_id` / `first_source` / `first_campaign`,
reached by `transaction_id` = the order number. GA4 is consulted for
this and nothing else.

### Resolve `utm_content` before trusting it

That field holds four different things: real ad ids, **ad names**,
third-party tokens (`AI_…` kwikengage, `sag_organic`, `link_in_bio`),
Google ad ids, and the occasional unexpanded `{{ad.id}}`.
`ad_token_resolution` (a view) maps a name back to its id where that is
unambiguous — `name_unique`, or `name_spend` where exactly one candidate
actually spent — and deliberately resolves nothing else. A name shared
by 13 live ads stays unresolved, because guessing moves real revenue
onto the wrong SKU.

### Both sides take the FULL order value

An order worth ₹1,000 that ad X opened and ad Y closed adds ₹1,000 to
X's first-click revenue **and** ₹1,000 to Y's last-click revenue. The
same holds up the hierarchy: ₹1,000 to the ad, ₹1,000 to its adset,
₹1,000 to its campaign. Reading a column down is valid. Adding a row
across is double counting.

### `shopify_order_clicks` is the view that settles it

One row per Shopify order, first click from GA4, last click from our
mapping, revenue from `shopify_orders.total_price`. Anything crediting
an ad, adset, source or campaign should start here rather than at
`ga4_order_attribution`.

---

## 3. The layers

```
  BRONZE          raw_dump_shopify     6.9M rows   15 GB
  (raw payloads)  raw_dump_meta        4.9M rows   11 GB
                  raw_dump_meta_daily  236k rows  1297 MB
                  raw_dump_google_ads / raw_dump_instagram
                        |
                        |  flatten (TRUNCATE + INSERT, full rebuild)
                        v
  SILVER          shopify_orders, shopify_order_attribution,
  (typed, joined) shopify_sessions, shopify_fulfillments,
                  meta_ads / meta_adsets / meta_campaigns,
                  insights_daily_by_ad / _adset / _campaign,
                  ga4_order_attribution, ga4_daily_landing
                        |
                        v
  GOLD            cpis_by_sku_daily, ad_performance_summary,
  (business logic)landing_page_*, order_customer_type,
                  hourly_campaign_tracker
                        |
                        v
  VIEWS / MATVIEWS  meta_direct_* (6 matviews, the sheet reads these)
                    sku_price_impact_* , sku_page_compare
                    shopify_order_clicks, ad_token_resolution
```

**Silver is rebuilt by TRUNCATE from bronze.** Anything inserted
directly into a silver or gold table is erased by the next refresh,
including the nightly. Data must enter through bronze to persist.

**Materialized views do not update themselves.** `meta_direct_daily_30d`
will serve stale rows indefinitely after the data behind it is corrected
— `scripts/refresh_snapshot_views.py` is what moves them. This has
caused real confusion: a sheet showing yesterday's numbers while the
database held today's.

---

## 4. Table catalogue

### Orders and customers (Shopify)

| relation | rows | what it is |
|---|---|---|
| `shopify_orders` | 440k | one row per order. `name` is the display number and the join key. Carries `utm_*`, `line_items` (jsonb), and since 2026-11-02 `shipping_state` / `shipping_city` / `shipping_zip` taken at order time |
| `shopify_order_attribution` | 440k | the last-click mapping: `utm_content` → `matched_ad_id`, with `tier` describing how it matched |
| `shopify_fulfillments` | 414k | one row per fulfilment. 92 columns. `shipping_region` exists only once a parcel moves — on day-old orders that covered 1.6% of them, which is why the address now lives on the order |
| `shopify_customers` | 984k | customer records |
| `shopify_customer_analytics` | 258k | Shopify's own customer rollup |
| `order_customer_type` | 440k | new vs returning, per order |
| `shopify_sales` / `shopify_sales_daily` | 448k / 310 | Shopify's own sales report, order and day grain |
| `shopify_discounts` | 326k | discount usage |
| `gokwik_orders` | 328k | GoKwik checkout records. **Stops 2026-09-20.** Has `billing_state` on 100% of rows |

### Sessions and landing pages

| relation | rows | what it is |
|---|---|---|
| `shopify_sessions` | 2.2M | session-level, day × path × referrer |
| `shopify_landing_page_analysis` | 897k | day × path × referrer × campaign. `sessions_that_completed_checkout` **sees only 4.5–8.8% of real orders** — GoKwik owns checkout. Use add-to-cart rate instead |
| `ga4_daily_landing` | 784k | GA4 Data API: day × landing page × channel group, with sessions, purchases and revenue. The only source of per-page revenue |
| `landing_page_sessions_daily` | 414k | day × path session rollup |
| `landing_page_analysis_30d` | 2.9k | 30-day page rollup vs ad spend, keyed on the ad **creative's own link**, not UTMs |
| `landing_page_ad_breakdown_30d` | 13k | the same, one row per (page, ad) |

### Meta advertising

| relation | rows | what it is |
|---|---|---|
| `insights_daily_by_ad` | 237k | **the canonical ad × day spend table.** Everything costing an ad should read this |
| `insights_daily_by_adset` / `_by_campaign` | 69k / 12k | same at coarser grain |
| `meta_ads` / `meta_adsets` / `meta_campaigns` | 26k / 3.8k / 711 | the entity roster: names, status, parentage. No spend |
| `ad_lifecycle` | 25k | per-ad lifetime rollup; the usual source of `ad_name` |
| `ad_performance_summary` | 25k | gold per-ad summary |
| `ad_media` | 26k | creative media per ad, incl. `effective_object_story_id` |
| `ad_insights` | 19k | all-days insights per ad. **Windows overlap and disagree** — its total is a small fraction of the daily table's. Prefer `insights_daily_by_ad` |
| `ad_reach_cumulative` | 1.06M | cumulative reach curves |
| `ad_token_resolution` | view | `utm_content` → resolved ad id. See §2 |
| `meta_direct_*` | 6 matviews | ad / adset / campaign / daily, Meta delivery joined to Shopify revenue. **What the "New Active Data" sheet reads** |

### Google advertising

| relation | rows | what it is |
|---|---|---|
| `google_ads_spend_daily` | 9.1k | **campaign × day spend.** Google's finest reported grain — there is no per-ad spend |
| `google_ads` / `google_campaigns` / `google_ad_groups` | 440 / 192 / 174 | roster. Needs `GOOGLE_ADS_API`, which is not configured — these go stale while spend stays current |

### Cost per item sold (CPIS)

| relation | rows | what it is |
|---|---|---|
| `cpis_by_sku_daily` | 10.1k | **(master_sku, day), additive across any window.** Allocates ad spend to SKUs from Shopify line items. Carries `order_units` / `order_revenue` (real orders) beside `attributed_*` (ad-driven) |
| `cpis_by_sku_utm` | 259 | the same for preset 7d / 30d / 90d windows. Uses an ad-set fallback the daily table does not, so **the two do not reconcile** |
| `cpis_sku_ad_daily` | 76k | (sku, ad, day) |
| `cpis_value_weighted_daily` | 107k | value-weighted allocation variant |
| `cpis_sku_context` | 100 | per-SKU catalogue context |

Allocation: an ad's spend for a day is split equally across the orders
it drove that day, then within each order by line-item revenue.
`_vw` columns use value weighting instead. Google is allocated the same
way but from **campaign**-day spend, so it is kept in its own columns.

### Price impact

`sku_price_change` (93 SKUs repriced 2026-10-28), `sku_page_map`,
`sku_price_impact_daily` (matview), `sku_page_compare` /
`other_page_compare` (matviews), plus summary and compare views.
The anchor is **the latest complete day**, never today — a partial day
against full ones shows every SKU down ~80%.

### Operational

`cron_run_log` (one row per nightly run, `steps` jsonb per step),
`sync_batches`, `failed_jobs`, `webhook_events`, `flatten_runs`.

---

## 5. Things that look like bugs and are not

**A campaign showing full spend and zero revenue.** Almost always a
partial day: spend is recorded in near-real-time, orders arrive later.
Judge a campaign on complete days only.

**`(referral)`, `(organic)`, `(direct)` as campaign names.** GA4's own
placeholders for traffic it classified itself, not our data being
broken.

**Two campaigns with the same name.** The accounts run near-mirror
campaigns, and date suffixes vary (`30/10/2026` vs `30102026`). Always
group by account as well as name, or spend is split across rows that
look unrelated.

**Sales in a state that got no spend.** Meta's region is where the
**impression** was served; Shopify's is where the **parcel ships**.
Different populations. They will never reconcile exactly.

**A CPV or engagement campaign with zero purchases.** Check
`meta_campaigns.objective`. `OUTCOME_ENGAGEMENT` has no purchase intent;
report its ROAS as undefined, not 0.00.

**Reach smaller than yesterday's.** See rule 5.

---

## 6. Operating constraints

**256 MB of shared buffers against ~32 GB of data.** Cache hit ratio
sits near 66%. Wall-clock timings swing **10–25x** with load, so judge
query cost in **blocks, not milliseconds** (`scripts/dbq.py --explain`).

**`statement_timeout` defaults to 2 minutes** and the Supavisor pooler
**drops startup parameters** — `server_settings` is silently ignored.
Raise it with `SET statement_timeout = '900s'` on the session.

**The pooler drops long operations.** Bulk reads and writes must be
chunked and retried.

**Connect through `scripts/dbq.py`,** which owns the
`postgresql+psycopg2://` → `postgresql://` rewrite and scrubs
credentials from every error. This repository is public. A `PreToolUse`
hook denies hand-rolled DSNs.

**The nightly runs `origin/master`,** not your branch. Code that is not
merged does not run, and a schema change made ahead of its code will
make the nightly fail against it.

---

## 7. Freshness

`cron_run_log` holds the truth: `run_started`, `status`, and a `steps`
jsonb with one entry per step. A `partial` status is normal — several
steps fail nightly for known reasons (absent Google credentials, Meta's
rate limiter on one ad account exceeding the 1800s step budget).

Typical state: Shopify orders, sessions and attribution current to
today; Meta insights to yesterday; GA4 landing to yesterday; the Meta
roster a few days behind; the Google roster stale while Google spend is
current.

**A cached API response is not an ingestion timestamp, and a successful
cron run is not proof of complete data.** Check the table's own date
column.
