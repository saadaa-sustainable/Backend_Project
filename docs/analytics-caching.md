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

## Verification

- `cd admin && npm test`
- `cd admin && ./node_modules/.bin/tsc --noEmit --incremental false`
- With the admin frontend running locally and Python Playwright installed:
  `.venv/bin/python scripts/verify_analytics_navigation.py`

The browser check intercepts analytics APIs with illustrative fixtures and
blocks external requests. It covers lazy loading, filters, loaded-more rows,
Explorer results, hash navigation, mobile layout, in-flight requests, manual
refresh and nested dialog cleanup. Its timings are local UI measurements,
not production database benchmarks.
