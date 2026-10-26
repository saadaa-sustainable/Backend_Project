"""Browser regression for retained dashboard sections and expired results.

Run against an existing local Next.js server (all analytics APIs are mocked):
    DASHBOARD_TEST_URL=http://localhost:3000 .venv/bin/pytest tests/browser/test_dashboard_cache.py -q
"""

import json
import os
from urllib.parse import urlparse

import pytest

playwright = pytest.importorskip("playwright.sync_api")
BASE_URL = os.environ.get("DASHBOARD_TEST_URL")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="Set DASHBOARD_TEST_URL to a local Next.js server")


@pytest.fixture
def dashboard():
    assert urlparse(BASE_URL).hostname in {"localhost", "127.0.0.1"}
    state = {"orders": 100, "fail": False, "calls": 0}
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.clock.install()
        page.add_init_script("""
            localStorage.setItem('analytics-dashboard-date-range', JSON.stringify({
                preset: 'custom', from: '2026-10-24', to: '2026-10-25'
            }));
        """)

        def api(route):
            path = urlparse(route.request.url).path
            if path.endswith("/dashboard/kpis"):
                state["calls"] += 1
                if state["fail"]:
                    route.fulfill(status=503, content_type="application/json",
                                  body='{"detail":"Test backend unavailable"}')
                    return
                payload = {
                    "total_spend": 10000, "total_impressions": 100000,
                    "total_shopify_revenue": 200000, "total_shopify_orders": state["orders"],
                    "new_customers": 50, "new_customer_revenue": 100000,
                }
            elif path.endswith("/dashboard/sessions"):
                payload = {
                    "total_sessions": 10000, "all_sessions": 12000,
                    "session_data_from": "2026-10-24", "session_data_to": "2026-10-25",
                    "available_days": 2,
                }
            elif path.endswith("/dashboard/session-trend"):
                payload = {"points": [], "spend_data_from": "2026-01-01", "spend_data_to": "2026-10-25"}
            else:
                payload = []
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        page.route("**/admin/analytics/**", api)
        try:
            page.goto(f"{BASE_URL}/user/analytics#dashboard", wait_until="domcontentloaded")
            value = page.locator("dt", has_text="Conversion rate (attributed)").locator("..").locator("dd").first
            playwright.expect(value).to_have_text("1.00%")
            yield page, value, state
        finally:
            browser.close()


def switch(page, section):
    page.evaluate("section => { location.hash = section; }", section)
    playwright.expect(page.locator(f'[data-analytics-section="{section}"]')).to_be_visible()


def test_expiry_refreshes_visible_dashboard_and_returning_sections(dashboard):
    page, value, state = dashboard
    switch(page, "help")
    switch(page, "dashboard")
    assert state["calls"] == 1  # An unexpired return still reuses the cache.

    state["orders"] = 200
    page.clock.fast_forward(301000)
    playwright.expect(value).to_have_text("2.00%")
    assert state["calls"] == 2

    switch(page, "help")
    state["orders"] = 300
    page.clock.fast_forward(301000)
    assert state["calls"] == 2  # Hidden sections do not poll the backend.
    switch(page, "dashboard")
    playwright.expect(value).to_have_text("3.00%")
    assert state["calls"] == 3

    # A background browser tab defers its refresh until visible again.
    page.evaluate("""() => {
        window.testHidden = true;
        Object.defineProperty(document, 'visibilityState', {
            configurable: true, get: () => window.testHidden ? 'hidden' : 'visible'
        });
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    state["orders"] = 400
    page.clock.fast_forward(301000)
    assert state["calls"] == 3
    page.evaluate("""() => {
        window.testHidden = false;
        document.dispatchEvent(new Event('visibilitychange'));
        window.dispatchEvent(new Event('focus'));
    }""")
    playwright.expect(value).to_have_text("4.00%")
    assert state["calls"] == 4  # Focus + visibility share the same request.


def test_failed_refresh_waits_for_explicit_retry(dashboard):
    page, value, state = dashboard
    state["fail"] = True
    page.clock.fast_forward(301000)
    retry = page.get_by_role("button", name="Retry session metrics")
    playwright.expect(retry).to_be_visible()
    assert state["calls"] == 2

    page.clock.fast_forward(601000)
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    switch(page, "help")
    switch(page, "dashboard")
    assert state["calls"] == 2

    state.update(fail=False, orders=300)
    retry.click()
    playwright.expect(value).to_have_text("3.00%")
    assert state["calls"] == 3
