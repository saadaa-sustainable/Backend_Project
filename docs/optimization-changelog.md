# Optimisation change log

Branch `perf/code-optimization`, started 12 Nov 2026. Follows the audit
report (findings are numbered as in that report).

Scope of this round: code only. No SQL statement that the app runs was
rewritten, and no index or table was touched. The goals are fewer
requests from the browser, less work on the database, and less code.

Net effect: 183 lines added, 700 removed, 3 dependencies removed. About
110 of the added lines are code that only moved into two helpers.

## Round 1 — 12 Nov 2026

### 1. Search boxes wait for typing to pause (finding 15)

| | |
| --- | --- |
| Files | `CustomerJourney.tsx`, `LastClickUtm.tsx`, `LandingPageAnalysis.tsx`, `Instagram.tsx`, `CampaignTracker.tsx` (all in `admin/src/app/user/analytics/`) |
| Before | The `filters` object was rebuilt on every keystroke, and each rebuild started a new request. The old requests could not be cancelled, so they all ran to the end on the database. |
| After | `filters` is wrapped in the existing `useDebouncedValue` hook (300 ms). One request is sent when typing stops. |
| Effect | Typing a five-letter word sends 1 request, not 5. The API has 5 database connections, so before this one user typing could hold all of them. |
| Side effect | Dropdown and date changes in these five sections now also wait 300 ms before the request starts. In Last Click UTM the four Advanced text filters are covered too, because they are part of the same object. |
| Lines | +4 −2 in each file |

### 2. Nightly data is kept for one hour in the browser, not five minutes (finding 15)

| | |
| --- | --- |
| Files | `admin/src/lib/useCachedFetch.ts`, comment in `acquisitionMer.ts` |
| Before | `DEFAULT_TTL_MS` was 5 minutes. An open Dashboard re-sent its 7 requests every 5 minutes. |
| After | `DEFAULT_TTL_MS` is 60 minutes. |
| Who is affected | Only the three sections that use this hook: Dashboard (7 tiles), Comparative Analysis and Blended MER. All three read tables that the nightly job rebuilds once a day. Checked on 12 Nov: the newest order in `shopify_orders` was from the morning rebuild, about 6.5 hours old. |
| Not affected | Hourly Tracker and Live P&L do not use this hook. They still use the 5-minute cache in `api.ts`, which was left as it is. |
| Still fresh when needed | A Kwikchat upload already calls `refetch()` on Blended MER. Retry buttons still force a new request. A page reload after one hour fetches again. |
| Effect | An open Dashboard sends 7 requests per hour instead of 84. |

### 3. Second Ads Analyse cache deleted (finding 15)

| | |
| --- | --- |
| File | `admin/src/app/user/analytics/AdsAnalyse.tsx` |
| Before | The section stored every first page (up to 100 rows with all columns) in `sessionStorage` under a key per filter set. Entries were never removed, so the storage could fill up. This was a second cache on top of the one in `api.ts`. |
| After | The read block, the write block and the `Cached` type are gone. The request still goes through the shared 5-minute cache in `api.ts`. |
| Behaviour change | A hard refresh (F5) of Ads Analyse now fetches again. Switching tabs inside the app is still instant. |
| Lines | +1 −59 |

### 4. Two startup warmers deleted (finding 13)

| | |
| --- | --- |
| Files | `app/api/routers/analytics.py` (`warm_ads_analyse_cache`), `tests/test_ads_cache_warmup.py` |
| Before | At every start the API ran `/last-click-utm` with no dates and `limit=100`, and `/landing-pages` with no dates. |
| Why they were useless | The cache key is built from all parameters. The UI always sends a date range, and Last Click UTM asks for 500 rows. So the warmed entries could never be the ones a browser asked for. They were two heavy queries on every deploy and restart that nobody read. |
| After | Both blocks are deleted. The three warmers that do match the UI (Ads Analyse, Creative Testing, CPIS) stay. |
| Lines | −37 |

### 5. Dead endpoint `/cpis-utm/spend-trend` deleted (finding 20)

| | |
| --- | --- |
| Files | `app/api/routers/analytics.py`, `admin/src/lib/api.ts` |
| Checked | Nothing in `admin/src`, `tracker/`, `tests/`, `app/` or `scripts/` calls it. The UI uses the batch endpoint `/cpis-utm/spend-trends` (plural), which stays. |
| Removed | The route and its handler (93 lines) and the client function `fetchCpisSpendTrend`. The response model stays because the batch endpoint uses it. |
| Bonus | This was one of the six copies of the SKU-to-ad matching rule (finding 11). Five are left. |

### 6. Deprecated endpoint `/overview-summary` deleted (finding 20)

| | |
| --- | --- |
| Files | `app/api/routers/analytics.py`, `admin/src/lib/api.ts` |
| Checked | Marked `deprecated=True` in the code. No caller in the repo. The Dashboard uses the five `/dashboard/*` endpoints. |
| Removed | The route, its handler, the `OverviewSummaryResponse` model, and in the client the type and `fetchOverviewSummary`. |
| Risk | An outside tool that still calls this URL would now get 404. None is known. |

### 7. Unused component deleted (finding 20)

| | |
| --- | --- |
| File | `admin/src/app/user/analytics/AnalyticsDashboard.tsx` (333 lines) |
| Checked | Not imported anywhere. The type check passes without it. |

### 8. Three unused dependencies removed (finding 20)

| | |
| --- | --- |
| Files | `requirements.txt`, `pyproject.toml` |
| Removed | `tenacity`, `orjson`, `aiosqlite` |
| Checked | No import of any of them in `app/`, `utils/`, `scripts/`, `tests/` or `alembic/`. The full test suite passes. |
| Effect | Smaller install on every deploy and every nightly run. |

### 9. Customer Journey counts once per filter, not once per page (finding 13)

| | |
| --- | --- |
| Files | `app/api/routers/analytics.py` (`_customer_journey_counts`, `get_customer_journey`), new `tests/test_page_independent_counts.py` |
| Before | Every request ran three statements: the page of rows, the total, and the count per RFM group. The two counts read the whole joined table and do not depend on the page. "Load more" and a re-sort ran them again each time. In the `EXPLAIN` run the two counts cost 39,438 blocks and the page itself 166. |
| After | The two counts moved, unchanged, into a helper with its own 5-minute cache. Its key is the filter only (`where_sql` and its parameters), not `sort`, `limit` or `offset`. |
| Effect | The first page of a filter costs the same as before. Each further page, and each re-sort, costs only the page query. |
| SQL | Not changed. The same two statements run, less often. |
| Test | Three pages of one filter run 2 count statements, not 6. A new filter counts again. |

### 10. Last Click UTM: tiles cached per date window, counts per filter (finding 13)

| | |
| --- | --- |
| Files | `app/api/routers/analytics.py` (`_last_click_tiles`, `_last_click_counts`, `get_last_click_utm`), `tests/test_last_click_loading.py` |
| Before | Every request ran four statements: the tile summary, the page of rows, the total, and the per-tab counts. The tile summary depends only on the two dates. The total and the per-tab counts depend only on the filters. All of them ran again for every filter change, sort change and page. |
| After | The tile block moved, unchanged, into `_last_click_tiles`, cached on `from_date` and `to_date`. The total and per-tab counts moved into `_last_click_counts`, cached on the filter. Both use the endpoint's 15-minute lifetime. |
| Effect | Changing a filter inside the same date window runs 3 statements, not 4. "Load more" and a re-sort run 1, not 4. |
| SQL | Not changed. |
| Test | The existing cache test now expects 7 statements, not 8, when the second request keeps the date window. The fixture also clears the two new caches. |
| Memory | Each helper keeps at most 4 small answers, the same limit as every other cache. |

## Repo cleanup — 12 Nov 2026

Files that no deploy, job or test uses were removed, so the repo holds
only what the dashboard needs. 146 files, about 15,000 lines.

| Removed | Note |
| --- | --- |
| `sheets/` | Google Sheets scripts. They keep running inside Google; edits now happen there. |
| `alembic/`, `alembic.ini`, the `alembic` dependency | No deploy or job ran them. The repo can no longer build a fresh database; the Bronze table definitions stay in `scripts/sql/`. |
| `docs/schema/` and `scripts/gen_schema_docs.py` | Generated table descriptions and their generator. |
| Nine reference files in `docs/` | Some code comments still name them. |
| `PRODUCT.md`, `Context.md`, two `HANDOFF` notes, `.env.example` | Old notes and the env template. |
| `exports/` spreadsheets and `scripts/validate_all_insights_fields.py` | The script needed one of the spreadsheets as input. |
| `sql/gokwik_match_*.sql` | One-off files for the old project. |
| `supabase/.temp/` | No longer tracked; now ignored. |

Kept in `docs/`: `mcp-connector.*`, `first-click-guide.*` and `img/`,
because the frontend build copies them for its Docs page.

On GitHub: 82 stale branches deleted and two month-old pull requests
closed without merging. `master` is the only branch.

## How it was verified

| Check | Result |
| --- | --- |
| Backend tests (`pytest tests`) | 1042 passed, 11 skipped |
| SQL syntax check (`scripts/check_sql_syntax.py`) | 71 constants parsed, 0 failures |
| Frontend type check (`tsc --noEmit`) | clean |
| Frontend tests (`npm test`) | 112 passed |
| Lint on edited files | No new message. `ruff` reports the same 5 old warnings in `analytics.py` as on master. `eslint` reports only messages that were there before. |

Not verified: the changes were not clicked through in a running browser.

## Looked at and left alone

| Item from the report | Why it was not changed |
| --- | --- |
| "14 unreferenced scripts" (finding 20) | Withdrawn. Each one was opened. They are manual tools (exports, probes, one-off backfills, key minting) that are run by hand, not dead code. Deleting them saves nothing at run time. |
| Two scheduler jobs (finding 20) | They are switched by environment settings. Whether production has them on cannot be seen from the repo, so removing them could change behaviour. |
| `app/services/gold/cpis_utm.py` (finding 20) | Still registered behind the "Flatten now" button. Removing it changes what a button does, so it needs a decision first. |
| 44 scripts that build the database URL by hand (finding 20) | A mechanical change to 44 scripts the nightly runs, with no test per script. Better as its own change, a few scripts at a time. |
| Moving dev tools to `requirements-dev.txt` (finding 20) | Every workflow installs `requirements.txt` and then runs `pytest`. Splitting the file means editing each workflow. |
| Landing Pages totals per filter (finding 13) | Its totals and its page come from one SQL statement, so separating them means changing the query. Out of scope for this round. Customer Journey and Last Click UTM were done (changes 9 and 10). |
| The 5-minute cache in `api.ts` | Shared by Hourly Tracker and Live P&L, which change every hour. |

## Next rounds (not started)

1. Query round: Landing Pages totals, the name-miss panel, date filters as ranges, the date bound on `/dashboard/mer-by-period`.
2. Three small indexes, each tested with `EXPLAIN` before and after.
3. Database round: Meta duplicate rows, unused indexes, incremental nightly rebuild.
