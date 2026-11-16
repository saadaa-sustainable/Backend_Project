# Optimisation phase 2 — plan

Status: plan only. Nothing here is built yet. Written 16 Nov 2026.

## The idea in one line

The big dashboard tables change once a day, when the nightly finishes.
So the backend should work out each answer once a day, not every 5 to
15 minutes.

Scope: code only. No SQL statement is rewritten, and no table or index
is touched. First Click "by Ad" stays broken until the query round.

## Why this is the right lever

| Measured fact | What it means |
| --- | --- |
| The nightly runs 07:05 to about 11:00 IST and is the only job that rebuilds the big tables | Most answers stay valid for about 24 hours |
| Backend answers are kept for 1 to 15 minutes | Almost every visit recomputes them |
| Ads Analyse "Ad Sets" took 35 s, then 39 s a few minutes later | The cached answer had already expired |
| Only the nightly writes to `cron_run_log` | The API can read one small row to learn that the data changed |
| The API and the nightly never talk to each other | Today nothing tells the API to drop old answers |

## The changes

### 1. A "valid until the next nightly" cache mode

| | |
| --- | --- |
| File | `app/services/analytics_cache.py` |
| What | `cached_analytics` gets one new option, `until_nightly=True`. An endpoint with it keeps its answers for up to 24 hours and is cleared when the nightly finishes. |
| Memory | Unchanged. Each endpoint still keeps at most 4 answers. They only stop expiring early. |

### 2. A watcher that notices the nightly finished

| | |
| --- | --- |
| File | `app/main.py` (the startup task that already runs the warmer) |
| What | Once a minute, one small query reads the newest finish time from `cron_run_log`. When it changes, every `until_nightly` cache is cleared and the warmer runs. |
| Killed runs | A run that hits the 240-minute limit never writes a finish time (this happened on 7 Nov). The watcher treats a run with no finish time as finished once 250 minutes have passed since its start. Without this, the caches would never clear that day. |
| Cost | One single-row query per minute. |

### 3. Which endpoints switch, and which do not

Rule: an endpoint switches only if every table it reads is written by
the nightly alone. Each one is checked against its tables before it is
switched.

| Switch to `until_nightly` | Keep the short lifetime |
| --- | --- |
| Ads Analyse (Ads, Ad Sets, Campaigns, Analytics) | Hourly Tracker, Live P&L |
| Last Click UTM (table, tiles, counts, name-miss panel) | Coins, inventory, quantity |
| First Click | Blended MER, MER by period (Kwikchat uploads) |
| Customer Journey, Landing Pages | Dashboard tiles (read hourly ARPU and spend) |
| CPIS (table, trends, daily series, data freshness) | Comparative Analysis |
| Creative Testing, Asset Analysis, Untested Assets | Meta Hypothesis (has its own clear-on-write) |
| Instagram, Campaign Tracker, Shopify Analytics | |

### 4. Warm the default views

| | |
| --- | --- |
| File | `app/api/routers/analytics.py` (`warm_ads_analyse_cache`) |
| Today | Warms the Ads Analyse opening view, Creative Testing and CPIS, at startup only. |
| Adds | Ad Sets, Campaigns, Last Click UTM (table and name-miss panel) and First Click by Ad set, each with the exact parameters the UI sends. |
| When | At startup, when the nightly finishes, and at midnight IST. |
| Why midnight | Last Click UTM, First Click and Landing Pages default to "last 30 days ending today". At midnight "today" changes, so the request is a new one and yesterday's cached answer no longer matches. Warming at midnight covers the hours before the nightly finishes. |
| Cost | Roughly two minutes of database work, twice a day and once per restart. |

### 5. Stop the "data freshness" wait

| | |
| --- | --- |
| File | `app/api/routers/analytics.py` (`/cpis-utm/data-freshness`) |
| Today | Kept for 60 seconds. It took 10 seconds in one measured run. CPIS requests it on open, and Ads Analyse waits for it before sending its main request. |
| After | Covered by change 3: its answer only changes with the nightly. |

### 6. Make hand-run refreshes visible

| | |
| --- | --- |
| Problem | A refresh run by hand (for example the Google refresh) does not write to `cron_run_log`, so the watcher cannot see it. The dashboard would show the old answer until the next nightly. |
| Plan | Have the hand-run Google refresh write a row to `cron_run_log` through the existing `CronRun` helper, and have the "Flatten now" button clear the caches when its job ends. |
| To confirm | I have not yet read `scripts/refresh_google.py` or the flatten runner. If either does not fit, the fallback is a shorter lifetime (a few hours) for the endpoints they feed. |

### 7. First Click opens on "Ad set" (optional)

| | |
| --- | --- |
| File | `admin/src/app/user/analytics/FirstClick.tsx` |
| What | Change the default grain from Ad to Ad set. One line. |
| Why | "By Ad" never returns, even after 170 seconds. "By Ad set" loads in 26 seconds and would be warmed. People would see data, not an error. |
| Limit | Choosing "Ad" would still fail until the query is fixed. |

## Expected effect

"Today" is measured on the deployed site. "After" is an estimate from
how fast cached answers came back in the same runs (0.2 to 1 second,
plus download time for the larger answers).

| View | Today | After, typical visit | First visit after the nightly |
| --- | --- | --- | --- |
| Ads Analyse, opening view | 17–20 s | 1–2 s | warmed |
| Ads Analyse, Ad Sets | 35–39 s | 1–2 s | warmed |
| Ads Analyse, Campaigns | 20–21 s | about 1 s | warmed |
| Ads Analyse, status = ACTIVE | 13–14 s | about 1 s | 13–14 s once |
| Last Click UTM, opening view | 13–15 s | about 1 s | warmed |
| CPIS, opening view | 8–9 s | 1–2 s | warmed |
| First Click by Ad set | 26 s | under 1 s | warmed |
| First Click by Ad | fails at 90 s | fails at 90 s | fails |
| Instagram, @saadaadesigns | 14–16 s | about 1 s | 14–16 s once |
| Shopify Analytics | 6–10 s | about 1 s | 6–10 s once |
| Dashboard | 5–6 s | 5–6 s | not in this phase |

## Limits

- **Four answers per endpoint.** A fifth filter combination pushes out
  the oldest, so unusual filters stay slow. Raising the limit to 8 for
  Ads Analyse would cost roughly 6 MB; decide after watching memory.
- **The cache lives in the API's memory.** A deploy or restart empties
  it. The startup warmer refills the default views.
- **A failed nightly is cached too.** The caches clear when the run
  ends, whatever its result. A day with missing data (13 Nov, no Raho
  Saadaa spend) shows the incomplete numbers all day, as it does now.
- **07:05 to 11:00 IST.** Yesterday's answers are served while tables
  are rebuilt. This is the same as today, but it lasts longer.
- **Dashboard tiles are not in this phase.** They read tables that
  change during the day, so they keep their short lifetime.

## How it will be verified

- Unit tests for the new cache mode: an answer survives past the old
  lifetime, and is dropped when the finish time changes.
- A unit test for the killed-run rule (no finish time, 250 minutes old).
- The full backend and frontend test suites.
- After the merge, the same timing script is run again on the deployed
  site and the before and after figures are reported.

## Decisions needed

1. Change 7: open First Click on "Ad set", or leave it failing until
   the query round?
2. Change 6: if a hand-run refresh cannot be made visible, accept
   stale-until-nightly for those views, or cap their lifetime at a few
   hours? A cap means they get slow again once it passes.

## Order of work

1. Changes 1 and 2 (cache mode and watcher), with tests.
2. Change 3, one group of endpoints at a time, each checked against its
   tables.
3. Changes 4 and 5 (warmer).
4. Change 6, after reading the two files named there.
5. Change 7, if approved.
6. One pull request, then the timing run on the deployed site.

## Not in this phase

- Any query rewrite: First Click by Ad, the name-miss panel, the Ads
  Analyse roll-ups themselves.
- New indexes.
- The nightly's own failures and its 240-minute limit.
