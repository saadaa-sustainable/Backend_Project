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

All six are enabled. Column names come from Supabase automatically. The order
of daily rows is **ad ID, then date**, matching the existing unique index.

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
