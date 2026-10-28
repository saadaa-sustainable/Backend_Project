# Supabase → Google Sheets: Meta Direct sync

[MetaDirectSync.gs](MetaDirectSync.gs) exports all six existing Supabase snapshot
views into separate tabs. It replaces the previous clear-and-reload script.
Copy the script and [appsscript.json](appsscript.json) into Google Apps Script;
no database migration or package installation is required.

| Supabase view | Sheet tab | Unique pagination key |
|---|---|---|
| `meta_direct_active_30d` | Active 30d | `ad_id` |
| `meta_direct_active_90d` | Active 90d | `ad_id` |
| `meta_direct_adset_30d` | Ad Sets 30d | `adset_id` |
| `meta_direct_campaign_30d` | Campaigns 30d | `campaign_id` |
| `meta_direct_daily_30d` | Daily 30d | `ad_id`, `date` |
| `meta_direct_daily_90d` | Daily 90d | `ad_id`, `date` |

## Campaign Tracker (separate script)

`CampaignTracker.gs` adds **three** tabs for a hard-coded list of
campaigns, all from the same three requests:

| Tab | One row per | Columns |
|---|---|---|
| Campaign Tracker | campaign | running/total ad sets and ads, latest ad created, days since |
| Ad Sets | ad set | campaign, name, status, ads in it, ads running, created, id |
| Ads | ad | campaign, ad set, name, status, **created date**, id |

Ad Sets and Ads are sorted newest first. The per-ad-set ad counts are
derived from the ad rows already in memory, so an ad set with no ads
shows `0` rather than disappearing.

No database view. It reads `meta_campaigns`, `meta_adsets` and `meta_ads`
directly and aggregates in the script -- 142 ad sets and 611 ads for the
four campaigns currently listed. Edit `CAMPAIGN_TRACKER.campaigns` to
track different ones.

**It needs a service-role key.** Those three tables have ROW LEVEL
SECURITY enabled with no policies, so `anon` and `authenticated` read
zero rows while PostgREST still answers `200` -- indistinguishable from
"these campaigns have no ads". A `service_role` / `sb_secret_` key
bypasses RLS. The six views `MetaDirectSync` reads do not need one
because RLS is off on those materialized views; base tables are not the
same thing. The script refuses to write the tab when the campaign lookup
returns nothing, so this fails loudly rather than publishing zeros.

Setup, alongside `MetaDirectSync`:

1. **Extensions → Apps Script**, add `CampaignTracker.gs` as a new file.
2. Script Properties: it reuses `SUPABASE_URL`, `SUPABASE_KEY` and
   `SPREADSHEET_ID`; add `CAMPAIGN_SYNC_HOUR_IST` (0-23). Schedule it
   **after** the backend refresh -- that starts 07:00 IST, so use 9 or
   later, otherwise the sheet copies yesterday's numbers silently.
3. Run `syncCampaignTracker` once to approve scopes.
4. Run `setupCampaignTrackerTrigger` to install the nightly run.

Re-running `setupCampaignTrackerTrigger` replaces its own trigger rather
than stacking a second one. A **Campaign Tracker** menu appears in the
sheet with Sync now / Install / Remove.

## Install

1. Open the destination spreadsheet → **Extensions → Apps Script**. Replace
   the old sync code with the complete contents of `MetaDirectSync.gs`. Remove
   duplicate copies of the old functions from other `.gs` files in that project.
2. In **Project Settings**, enable **Show appsscript.json manifest file in
   editor**. Replace that file with this directory's `appsscript.json`.
   It enables the advanced **Google Sheets API**, sets Asia/Kolkata, and includes
   permission to create continuation/daily triggers. If using a standard Google
   Cloud project, also enable the **Google Sheets API** in that project's API
   Library. You can verify the Sheets service appears under **Services**.
3. Add these **Script Properties** in Project Settings:

   | Property | Value |
   |---|---|
   | `SUPABASE_URL` | `https://gtcdyfmlvglzpiwzklhx.supabase.co` |
   | `SUPABASE_KEY` | A server-side `sb_secret_…` key; the existing legacy `service_role` JWT also works |
   | `SPREADSHEET_ID` | The part between `/d/` and `/edit` in the Sheet URL |
   | `SYNC_HOUR_IST` | An integer `0`–`23`, **after** the backend snapshot refresh finishes; for example `13` means the 1–2 PM IST window |

   Do not paste credentials into cells, source code, or GitHub. The included
   manifest pins URL fetching to this Supabase project. If using another
   project, update both `SUPABASE_URL` and the manifest's `urlFetchWhitelist`.
4. Run **`syncMetaDirect`** manually and authorize it. Keep one Google account
   responsible for the script and its triggers. The browser may be closed once
   the execution starts; later executions use the stored spreadsheet ID.
5. Check the **Status** tab. Large exports may show `WAITING` between executions.
   The script creates a one-time continuation trigger and resumes from saved
   progress. Completion means **run status `DONE` and all six rows `OK`**.
6. Run **`setupNightlyTrigger`** once after the first successful export. This
   replaces this account's previous `syncMetaDirect` daily trigger and avoids
   duplicate triggers for the new daily handler. Delete any old triggers in
   other script projects or owned by other accounts separately.

These output tabs are managed exports: all their cell values are replaced on
successful publication, and their grids are resized to the source dimensions.
Keep manual calculations and annotations on other tabs. Existing output sheet
IDs are retained; references within the retained grid remain valid. References
to rows/columns removed by a shrinking export can be affected.

### Key access

The views intentionally do not allow public `anon` access. Use a backend secret
key from **Supabase → Project Settings → API Keys**, or the existing legacy
service-role key. New secret keys are sent only in the `apikey` header; legacy
JWT keys also use Bearer authorization.

Both have elevated database privileges. Script Properties keep the key out of
sheet cells but **do not hide it from Apps Script editors**. A bound script is
accessible to spreadsheet editors. Share this export as Viewer with consumers,
or put this code in a separately owned standalone Apps Script project (using
the same `SPREADSHEET_ID`) if the spreadsheet needs other editors. Do not expose
these private views publicly to make an `anon` key work.

## Why this version is more reliable

- **Resumes instead of restarting everything.** Fetches and writes in bounded
  chunks, checkpoints each successful write, and yields after roughly 2.5
  minutes of work. Both consumer and Workspace Apps Script executions have a
  **6-minute** limit. A one-time watchdog also covers an abrupt timeout.
- **Preserves the last published data.** One hidden staging tab holds the current
  export. Once complete, a single atomic Sheets request copies values into the
  existing output tab and removes staging. A failed download leaves the previous
  output intact. On the first import, the completed staging tab is renamed.
- **Replays safely after uncertain writes.** Writes target a fixed row range;
  resuming overwrites that range rather than appending duplicates. Publication
  has an atomic marker so a lost response does not cause a second publication.
- **Avoids deep OFFSET scans.** Pagination uses the last successfully written
  unique key. It continues even when Supabase returns fewer rows than requested.
  It never treats a short page as proof that the export is complete.
- **Bounds memory and requests.** At most 1,000 rows and 40,000 cells per data
  write, reduced further to keep the estimated UTF-8 request below 1.5 MB.
  Writes are spaced at least 1.2 seconds apart. There is no 20,000-row buffer.
- **Allocates actual dimensions.** An exact count at the start sizes staging;
  another count before publication checks completeness. It does not run a count
  on every page or preallocate 100,000 rows for every tab.
- **Handles empty results correctly.** Fetches the empty view's column schema
  from PostgREST's OpenAPI endpoint, then replaces old data with headers only.
  A missing schema stops publication instead of retaining stale rows as current.
- **Keeps values literal.** Uses `RAW` writes: names starting with `=` stay text,
  text IDs keep their digits, nulls become blank cells, and numeric measures stay
  numeric. Source date strings remain ISO text. It does not recalculate ROAS or
  change attribution logic.
- **Stops on failures.** Connection/API errors stop the run, cancel continuation,
  and record the error. No repeated connection attempts or silent partial
  success. Correct the problem and explicitly resume or restart.

Google's documented limits are [6 minutes per Apps Script execution](https://developers.google.com/apps-script/guides/services/quotas),
[60 Sheets writes/minute/user and a recommended 2 MB request payload](https://developers.google.com/workspace/sheets/api/limits).
Pagination follows [PostgREST's documented range/count behavior](https://postgrest.org/en/stable/references/api/pagination_count.html).

## Daily timing and data freshness

The repository's daily backend workflow **starts at 07:00 IST**; that is not its
completion time. Snapshot refresh is near the end. The previous script's claim
that the backend starts at 01:39 IST was incorrect. Choose a Sheet trigger hour
that follows the actual completion time in GitHub Actions, with a margin.
The example `13` is a configurable slot, **not a guarantee** that the pipeline
will be finished. Google runs hourly triggers within the selected hour rather
than at an exact minute.

This script reads the materialized views; **it does not refresh them**. New
bronze/silver data alone is insufficient: `scripts/refresh_snapshot_views.py`
must finish successfully for all six views first.

The Status tab distinguishes:

- **Meta source data through:** `meta_direct_data_through`, the newest date in
  the underlying Meta insights. This is not a timestamp proving that each
  materialized view has refreshed.
- **Published (UTC):** the last successful export time for that tab; pending
  tabs retain their prior publication time during a subsequent run.
- **Rows staged / Expected rows:** progress for the current run. `WAITING` means
  the next execution is scheduled; `ERROR` requires action.

The script checks the source date at startup/resume and around each table, and
compares source row counts before publication. **These checks are not a database
snapshot lock:** an in-place refresh that changes values without changing date
or count cannot be detected. The six tabs also publish one at a time, so their
refresh is not atomic as a group. Keep the snapshot views unchanged for the
whole export. If strict consistency during concurrent backend refreshes becomes
necessary, add a backend export-generation/readiness API or immutable exports;
a series of REST requests alone cannot guarantee it.

## Operating commands

| Run in Apps Script | Effect |
|---|---|
| `syncMetaDirect` | Start a new run, or explicitly resume an incomplete/failed one |
| `resumeMetaDirect` | Resume an existing run only; no new export after `DONE` |
| `showMetaDirectStatus` | Log the saved checkpoint/error without contacting Supabase or Sheets |
| `restartMetaDirect` | Discard only the current run's hidden staging tab and start again; published tabs remain |
| `setupNightlyTrigger` | Install/replace this account's daily trigger using `SYNC_HOUR_IST` |
| `removeNightlyTrigger` | Remove this account's daily trigger; an in-progress continuation is not cancelled |

Do not manually edit `META_DIRECT_SYNC_V2` or hidden `__md_stage_…` tabs. If you
change the configured view list/tab names, restart the run first. Do not change
connection properties while a run is incomplete. Checkpoints older than 12
hours require `restartMetaDirect` so yesterday's partial download cannot be
silently continued into today's export.

For errors, check **Apps Script → Executions** and the Status tab. If Sheets
itself is unavailable, the script does not retry writing the error there;
`showMetaDirectStatus` and Executions still contain it. Configure trigger failure
notifications in the Apps Script trigger UI if you want Google's email alerts.
Scheduled runs remain stopped after a failure until an explicit manual resume
or restart.

### Updating the script after "Duplicate pagination key"

The initial version incorrectly added quotation marks to scalar cursor filters
(`ad_id=gt."123"`). PostgREST treats those quotes as part of the scalar text
value, so a later page can return earlier IDs again. The corrected version uses
`ad_id=gt.123`, URL-encoding the value without adding quotes. Quoting inside the
daily views' logical `or=(...)` expression is separate and remains intentional.

Replace the old code with the updated `MetaDirectSync.gs` (or replace just its
`mdQuery_` function), save, then run **`resumeMetaDirect`**. The failed page was
not checkpointed, so it resumes from the last successful write. If the run is
older than 12 hours or the source date changed, use **`restartMetaDirect`**.
Keep the duplicate-key check; removing it would risk publishing repeated rows.

## Capacity and remaining limits

The default cell budget is **20,000,000**, matching [Google's published Sheets
limit](https://support.google.com/drive/answer/37603) checked on 2026-10-17. Google
also documents a 100 MB file limit there. A cell count alone does not predict
file size, calculation cost, API duration, or every account-specific limit.
You can lower `META_DIRECT.maxCells` if your spreadsheet needs a smaller budget.

Allocated blank rows/columns count too. During publication the workbook must
fit **all existing tabs + one temporary copy + any growth of the destination**.
The script checks that peak before staging; unrelated tabs are never trimmed.
If capacity is exceeded, remove genuinely unused rows/columns manually, or run
Daily 90d in a separate spreadsheet/script with only that view configured.
The script fails explicitly rather than dropping rows or clearing live data.

Sheets can also time out on a very large server-side copy or a workbook with
expensive formulas. A saved publication marker permits recovery after an
uncertain response, but there is no promise that any spreadsheet size will
finish within a fixed number of seconds. For repeated copy timeouts, split the
largest tab into another workbook or reduce the export columns/window.

## Metric interpretation (unchanged)

- `repeat_customers` counts distinct people per row. Summing it across ads or ad
  sets can count a person more than once; `repeat_customer_orders` is additive.
- `reach_daily_sum` and unique reach have different meanings. Unique reach
  cannot be summed across ads to calculate total unique people.
- `acq_mer` is `new_customer_sales / spend`. Aggregate the numerator and
  denominator, then divide; do not average row ratios. A zero denominator is
  blank, not zero.
- The ad-set/campaign `d3_lc_roas` and `d7_lc_roas` compare last-click revenue
  and spend over matching trailing windows anchored to the newest data day.

## Verification

Run locally, without any credentials or network requests:

```sh
node --test sheets/tests/meta-direct-sync.test.mjs
```

The tests execute the actual `.gs` file against mocked Apps Script,
PostgREST and Sheets APIs. They cover all six tabs, more than 100,000 rows,
server pagination caps, composite keys, pause/resume, lost write/publication
responses, empty views, source changes, cell budgets, API failures, locks,
triggers, and literal value handling. These are not a substitute for the first
manual run in your Google account; Google runtime latency and workbook-specific
limits cannot be measured by local mocks.

## Price-change impact (separate script)

[PriceImpactSync.gs](PriceImpactSync.gs) writes three tabs for the
2026-10-28 repricing. Same Script Properties as above
(`SUPABASE_URL`, `SUPABASE_KEY`, `SPREADSHEET_ID`); the **anon key is
enough** — verified by reading all three views as the `anon` role.

| Tab | Supabase view | Rows | One row per |
|---|---|---|---|
| Summary | `sku_price_impact_summary` | 4 | price direction — **read this first** |
| Product | `sku_page_compare` | 326 | repriced SKU × one of its product pages |
| Collection | `sku_page_compare` | 1,043 | repriced SKU × a collection it sits on |
| Other | `other_page_compare` | 63 | page — **no SKU column, see below** |
| *one per SKU* | `sku_page_compare` | 43 tabs | every page that SKU appears on |

48 tabs in all. The per-SKU tabs are **discovered from the data**, not
listed in the script, so a later repricing needs no edit: whatever has a
direction other than Unchanged gets a tab, and a SKU that stops being
repriced has its tab removed rather than left showing a reversed
decision. The removal is anchored to the catalogue's own master-SKU
pattern (`SD|SM|SU` + 1–4 letters) so a tab you named yourself cannot be
caught by it.

A SKU tab reads as that SKU's whole surface. `SDCP`, for instance:

| page_type | page_path | skus_on_page | sessions_today |
|---|---|---|---|
| Collection | `/collections/cotton-trousers` | 1 | 6,787 |
| Collection | `/collections/best-sellers-women` | 58 | 535 |
| Collection | `/collections/shop-all-bottoms` | 22 | 521 |
| Product | `/products/beige-solid-regular-fit-cotton-trouser` | 1 | 498 |

`skus_on_page` is what stops that table being misread. `cotton-trousers`
is SDCP's own collection; `best-sellers-women` is shared with 57 other
SKUs and its traffic is not SDCP's.

`setupPriceImpactTrigger()` refreshes at 07:00 daily, after the nightly
has rebuilt the source tables. Writes are paced to stay under the Sheets
quota of 60 per minute.

### Why the Other tab has no SKU column

Checked directly rather than assumed: of **111 Shopify custom pages,
zero** reference a product or a collection anywhere in their HTML body.
They are assembled from dynamic blocks, so nothing stored in Shopify
says what any of them merchandises, and the homepage belongs to no SKU
in the first place.

The tab therefore carries the pages and their traffic — 63 pages, ~8,100
sessions on the anchor day — with the reason printed on the Status tab,
rather than dropping the traffic or inventing an attribution for it.

### Unchanged is the control, not filler

Those 41 SKUs were reviewed in the same exercise and deliberately left
at their old price, so they carry every site-wide influence the repriced
ones do — campaigns, weather, a slow Tuesday — and none of the price
change. **If add-to-cart moves the same way on Unchanged, the move is
not about price.**

The first anchor day shows exactly why that matters. Every group rose
together against the same weekday a week earlier:

| Group | SKUs | ATC rate | vs last week |
|---|---|---|---|
| Decreased | 27 | 6.62% | **+1.91** |
| Increased | 16 | 8.65% | +1.10 |
| Unchanged | 41 | 9.42% | **+1.64** |
| Hidden | 9 | 12.31% | +3.17 |

Read the Decreased row alone and the price cut looks like it worked.
Read it beside Unchanged and it is a site-wide lift that the repriced
SKUs happened to share — and the cut actually *underperformed* the
control. That comparison is the whole point of the Summary tab.

### The three things a reader has to know

**The anchor is the latest COMPLETE day, never today.**
`shopify_landing_page_analysis` is rebuilt once by the nightly, so today
holds only the hours before that run — 10,918 sessions against a full
day's ~65,000. Read today against a full yesterday and every SKU looks
80% down for reasons that have nothing to do with price. So tomorrow
morning the anchor is today, and `anchor_at_new_price` flips to true on
its own.

**Add-to-cart rate is the headline, and there is no conversion rate.**
`sessions_that_completed_checkout` captured **4.5%–8.8%** of real Shopify
orders over ten days — GoKwik owns the checkout, so Shopify never sees
most conversions, and the swing in what it captures is larger than any
price effect. Add-to-cart is measured on the same sessions and holds
6.9%–7.9%, and it is the step where the shopper has just seen the price.
The real outcome comes from `cpis_by_sku_daily` instead: `units_sold`
and `revenue` from actual orders.

**Collection pages are shared.** `/collections/men-cotton-pant` carries
100,869 sessions and belongs to no single SKU. Collection and product
columns are kept apart so the two are never summed, and `skus_on_page`
says how many SKUs share each one.

### Why there is no "other pages" split

Measured over 30 days, everything outside product and collection pages
is either not merchandising or not material:

| Page | Sessions 30d | |
|---|---|---|
| `/` homepage | 228,051 | not SKU-specific |
| `/pages/knit-wear-collection` | 2,026 | merchandising |
| `/pages/behtar-cotton` | 646 | merchandising |
| `/pages/shop-all-kurta-sets` | 405 | merchandising |
| contact-us, returns, shipping, our-store | ~3,900 | policy pages |

The merchandising custom pages come to roughly 3,400 sessions against
4.2M on product pages and 12.4M on collection pages. Product presence on
them is also not recorded anywhere — it would have to be inferred by
reading each page's HTML, which misses anything rendered by a dynamic
block. Not worth the inference for 0.02% of the traffic.
