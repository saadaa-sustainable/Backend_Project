# meta_direct_* → Google Sheet

`MetaDirectSync.gs` pulls the four snapshot views into a sheet and
keeps them current nightly.

## Setup

1. In the sheet: **Extensions → Apps Script**, paste `MetaDirectSync.gs`.
2. **Project Settings → Script Properties**:

   | Property | Value |
   |---|---|
   | `SUPABASE_URL` | `https://gtcdyfmlvglzpiwzklhx.supabase.co` |
   | `SUPABASE_KEY` | the **service_role** key (Supabase → Settings → API) |

3. **Project Settings → Timezone → Asia/Kolkata.**
4. Run `setupNightlyTrigger()` once and authorise it.
5. Run `syncMetaDirect()` once by hand to confirm it works.

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

`Daily 90d` is disabled in the `VIEWS` array. It is ~101 API pages and
3.6M cells, which will usually exceed the **6-minute** execution cap on
a consumer Google account. On Workspace the cap is 30 minutes and it
should complete — flip `enabled: true` to try.

If you need 90-day history on a consumer account, the better answer is
a pivot off `Daily 30d` plus `Active 90d`, rather than 100k raw rows in
a spreadsheet.

## Notes

- Pagination is `limit`/`offset` with an explicit `order`. The sort is
  load-bearing: without it PostgREST can return rows in a different
  order between pages, silently duplicating some and dropping others.
- Each view is written in 5,000-row chunks. A single `setValues` call
  with 100k rows is the usual way this kind of script dies.
- One view failing does not stop the others; failures land in **Status**.
