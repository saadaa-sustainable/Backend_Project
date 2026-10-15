# meta_direct_* → Google Sheet

`MetaDirectSync.gs` pulls the six snapshot views into a sheet and
keeps them current nightly.

## Tabs

| tab | view | grain | rows |
|---|---|---|---|
| Active 30d | `meta_direct_active_30d` | ad | ~1.7k |
| Active 90d | `meta_direct_active_90d` | ad | ~1.7k |
| Daily 30d | `meta_direct_daily_30d` | ad × day | ~26k |
| Daily 90d | `meta_direct_daily_90d` | ad × day | ~66k |
| Ad Sets 30d | `meta_direct_adset_30d` | ad set | ~440 |
| Campaigns 30d | `meta_direct_campaign_30d` | campaign | ~90 |

The script pulls `select=*` and takes its headers from the first row, so
a column added to a view appears in the sheet on the next sync with no
change here.

### Columns that must not be summed

`repeat_customers` is DISTINCT people, counted per row. One person who
buys through two ad sets is one customer and two rows, so a SUM down
that column overstates. `repeat_customer_orders` sits beside it and is
additive — total that instead. Same hazard, and the same remedy, as
`reach_daily_sum` vs `reach_unique_to_date`.

`acq_mer` is a ratio — **new-customer sales ÷ spend**, money over money,
so it reads like the ROAS columns beside it. A ratio cannot be averaged
down a column: total `new_customer_sales` and total `spend` separately
and divide those. Blank when nothing was spent, never zero.

### d3 / d7 ROAS

Only on the ad set and campaign tabs. Last-click revenue over spend,
both summed across the same trailing window ending on the newest day of
data. **Blank, not zero, when nothing was spent in that window** — about
half the rows on any given day — so a sheet sorted by d3 ROAS does not
bury a paused entity at the bottom as though it performed badly.

At ad grain a three-day window is mostly noise, which is why the two
ad-level tabs do not carry it.

## Setup

1. In the sheet: **Extensions → Apps Script**, paste `MetaDirectSync.gs`.
2. **Services → + → Google Sheets API → Add.** Required: the write path
   uses `Sheets.Spreadsheets.Values.update` rather than
   `Range.setValues()`. Without the advanced service added, the script
   fails on the first write with `Sheets is not defined`.

   Why it is not optional: `setValues()` is one round trip through the
   Spreadsheet service per call, and growing a tab with
   `insertRowsAfter()` costs more the bigger the grid already is. The
   90-day view is 63,194 rows x 36 columns; writing it a page at a time
   meant 63 writes plus 63 structural resizes against a document that
   got heavier with each one, until the service timed out on ANY access
   to it -- including the nine-cell Status write, which is where the
   error surfaced and where it was not.
3. **Project Settings → tick "Show `appsscript.json` manifest file in
   editor"**, open it, and make it match `sheets/appsscript.json`.

   The manifest carries a `urlFetchWhitelist`, and UrlFetch to anything
   not listed there fails with *"the URL has not been whitelisted in the
   script manifest"* — which is what adding the Sheets advanced service
   surfaces, because adding a service rewrites the manifest.

   The whitelist is worth keeping rather than deleting. This script
   holds a `service_role` key, and the entry pins the only host it is
   allowed to send that key to. Entries are prefix matches, must be
   https, and must end with `/`.
4. **Project Settings → Script Properties**:

   | Property | Value |
   |---|---|
   | `SUPABASE_URL` | `https://gtcdyfmlvglzpiwzklhx.supabase.co` |
   | `SUPABASE_KEY` | the **service_role** key (Supabase → Settings → API) |

5. **Project Settings → Timezone → Asia/Kolkata.**
6. Run `setupNightlyTrigger()` once and authorise it.
7. Run `syncMetaDirect()` once by hand to confirm it works.

## Why service_role rather than anon

`anon` is revoked on these views on purpose. That key is published in
client-side code, and the views carry full spend and revenue per ad.
Apps Script runs on Google's servers, so a key stored here never
reaches whoever opens the sheet — but it **is** visible to anyone who
can open the script editor.

**Share the sheet as Viewer, not Editor.** An Editor can read the key,
and `service_role` bypasses row-level security across the entire
project, not just these four views.

## Timing

The backend cron starts ~01:39 IST and has been finishing ~05:24. The
snapshot refresh is its last step, so the trigger is set for **07:00**,
leaving about 90 minutes of headroom. If the pipeline starts running
longer, move the trigger later rather than letting the sheet pull a
half-refreshed snapshot.

The **Status** tab records when the sheet last refreshed and the
`Data through` date from the database — so a night where the pipeline
failed shows up as a stale date rather than looking like a quiet day
of trading.

## Sizes, and why Daily 90d is off by default

| View | Rows | Cols | Cells |
|---|---:|---:|---:|
| Active 30d | 1,039 | 40 | 41,560 |
| Active 90d | 1,047 | 40 | 41,880 |
| Daily 30d | 41,807 | 36 | 1,505,052 |
| Daily 90d | 100,816 | 36 | 3,629,376 |

A Google Sheet holds 10M cells; all four come to ~5.2M.

All four are enabled. `_syncView` writes each page to the sheet as it
arrives rather than accumulating every row first, so memory stays flat
and the time is roughly linear in row count.

Two ceilings still apply: Apps Script caps one execution at **6
minutes** on a consumer account and **30 minutes** on Workspace, and a
spreadsheet holds 10M cells. If `Daily 90d` starts timing out, set
`enabled: false` for it rather than letting it fail nightly.

100k raw rows is also awkward to actually read. A pivot over
`Daily 30d` plus `Active 90d` usually answers the same questions more
legibly.

## Notes

- Pagination is `limit`/`offset` with an explicit `order`. The sort is
  load-bearing: without it PostgREST can return rows in a different
  order between pages, silently duplicating some and dropping others.
- Each page is written as it arrives. Accumulating 100k objects and
  calling `setValues` once is the usual way this kind of script dies.
- The sheet is grown before each write. A new sheet is 1000 rows × 26
  columns and `clear()` does not change that, so writing 36–40 columns
  fails with *"The coordinates or dimensions of the range are invalid"*
  unless the sheet is expanded first.
- One view failing does not stop the others; failures land in **Status**.
