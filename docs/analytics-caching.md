# Analytics navigation and caching

The analytics page keeps each visited section mounted until the user leaves
the page or reloads it. Returning to a section restores its selected dates,
filters, pagination, loaded rows and generated Explorer results without a
new request. Unvisited sections remain lazy loaded. Inactive sections are
hidden and inert; asset dialogs close on navigation and release scroll locks.

The shared API response cache is browser-local, holds up to 64 results, and
reuses successful analytics reads for five minutes. Its keys include endpoint,
filters, POST body, headers and timeout. Concurrent identical requests share
one fetch; failed requests are not cached. Read-only Explorer POSTs and CPIS
spend-trend POSTs are cached without invalidating other sections. Successful
writes invalidate the response cache.

Shopify Analytics and Last Click UTM Refresh buttons clear the browser
response cache before requesting data again. Existing refresh controls in
other sections retain their behavior. Server-side cache policies still apply.

The five-minute limit applies to request reuse, not automatic updates of an
already displayed section. Returning restores that section's snapshot; use
its Refresh control or reload the page for an updated view. UI selections are
not persisted across a full page reload or navigation outside Analytics.
Existing Dashboard and Ads Analyse session caches retain their own policies.

This removes repeated work when navigating. It does not guarantee the speed
of a first backend request after deployment or a cold start.

## Ads Analyse, CPIS and Creative Testing optimization (2026-10-01)

Ads Analyse waits for the source-date probe before requesting a preset range,
so opening it no longer requests both today's window and the latest available
window. Custom dates remain independent of that probe. Campaign and Ad Set
views fetch their selected grain; returning to Ads retains loaded pages.
The startup warm-up uses the same source date as the browser and also warms
CPIS's default published 30-day window.

The Ads row query selects a bounded page before joining wide lifecycle rows.
Counts, category tiles and totals share one cached summary, reusable across
pages. Delivery summaries aggregate the daily table once. Category tiles still
ignore the selected category; table totals still include it.

Creative Testing limits metric joins to assets in the selected creation
window, retaining all ads belonging to those assets. CPIS reuses per-ad
window totals and shared reconciliation inputs instead of expanding and
scanning the same daily/order data repeatedly. CPIS reads and trend responses
now use a five-minute backend cache, matching the browser's reuse interval.

### Database maintenance

Migration `20261001110743_analytics_order_lookup_cover.sql` adds a partial
covering index on attribution `(matched_ad_id, created_at)`, including order
ID and price. It was built concurrently on `media_data_saadaa`, verified as
valid, and recorded as a migration. Normal `VACUUM (ANALYZE)` was also run on
`shopify_order_attribution`; this let order lookups use index-only reads.
The application changes still require deployment separately.

For another live database, prebuild the index with `CREATE INDEX CONCURRENTLY`
outside a transaction before applying the migration. Run ordinary
`VACUUM (ANALYZE) public.shopify_order_attribution` outside a transaction after
the build. Attribution refresh truncates/reloads this table, so ongoing
autovacuum/analyze must maintain its visibility map and statistics after
refreshes; an index alone does not guarantee index-only reads.

### Measured results

These are local endpoint executions against Supabase with empty application
response caches, not deployed browser load times. Database buffers were not
flushed. Network and shared database load varied between runs.

| Endpoint and filters | Before | Final implementation |
| --- | ---: | ---: |
| Ads Analyse, delivery Jan 1–Sep 26, first 100 ads | 72.4s | 25.2s |
| Creative Testing, Sep 2–Oct 1, 781 assets | 12.1s | 6.2s |
| CPIS, published 30-day window, 90 SKUs | 32.2s | 8.7s |

Full response comparisons found no differences, allowing normal floating-point
rounding. Repeating each identical endpoint call used its cache and executed
zero SQL statements. Ads Analyse's uncached response remains above the
10-second target; deployment and a production browser measurement are still
needed before claiming that target is met.

## Verification

- `cd admin && npm test`
- `cd admin && ./node_modules/.bin/tsc --noEmit --incremental false`
- With the admin frontend running locally and Python Playwright installed:
  `.venv/bin/python scripts/verify_analytics_navigation.py`
- Ads request sequencing and retained pagination:
  `.venv/bin/python scripts/verify_ads_initial_load.py`
- Backend regression checks:
  `.venv/bin/python -m pytest tests/test_analytics_loading.py tests/test_ads_timing_loading.py tests/test_ads_efficiency_loading.py tests/test_analytics_trends.py tests/test_ads_cache_warmup.py -q`
- SQL syntax checks: `.venv/bin/python scripts/check_sql_syntax.py`

The browser check intercepts analytics APIs with illustrative fixtures and
blocks external requests. It covers lazy loading, filters, loaded-more rows,
Explorer results, hash navigation, mobile layout, in-flight requests, manual
refresh and nested dialog cleanup. Its timings are local UI measurements,
not production database benchmarks.
