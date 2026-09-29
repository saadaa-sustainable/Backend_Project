"""Verify section navigation with illustrative browser fixtures, never production data.

Run a local admin frontend, then:
    .venv/bin/python scripts/verify_analytics_navigation.py --baseline
    .venv/bin/python scripts/verify_analytics_navigation.py
Requires the locally installed Playwright Python package and Chromium.
"""

import argparse
import json
import re
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    assert urlparse(args.url).hostname in {"localhost", "127.0.0.1"}
    source = (Path(__file__).parents[1] / "admin/src/lib/api.ts").read_text()
    def row_defaults(name):
        fields = re.search(r"export interface " + name + r" \{(.*?)\n\}", source, re.S).group(1)
        return dict.fromkeys(re.findall(r"^\s+(\w+)\??:", fields, re.M))

    defaults = row_defaults("InstagramPostRow")
    posts = [{**defaults, "id": str(i), "caption": f"Illustrative post {i}",
              "username": "illustrative", "media_type": "IMAGE", "like_count": 5}
             for i in range(80)]
    requests, unexpected, errors = [], [], []
    pending = []
    asset = {**row_defaults("UntestedAssetRow"), "id": "fixture-asset", "media": "video",
             "title": "Illustrative asset", "origin": "database", "matched_ads": 1,
             "link": "https://example.test/fixture.mp4", "links": []}
    ad = {**row_defaults("CreativeTestingAdRow"), "ad_id": "fixture-ad",
          "ad_name": "Illustrative ad", "iteration_index": 0, "is_copy": False,
          "ad_preview_url": "https://example.test/fixture.mp4"}
    totals = dict.fromkeys(row_defaults("ShopifyDayRow"), 0)
    totals.pop("day")
    totals["customers_coverage_pct"] = 100
    schema = {"datasets": [{"key": "ads", "label": "Illustrative ads", "date_dimension": "day",
                            "dimensions": [{"key": "day", "label": "Test day"}],
                            "metrics": [{"key": "spend", "label": "Test spend"}]}]}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.set_default_timeout(12_000)
            page.on("pageerror", lambda error: errors.append(str(error)))

            def route_request(route):
                request = route.request
                parsed = urlparse(request.url)
                if not parsed.path.startswith("/admin/"):
                    if parsed.netloc == urlparse(args.url).netloc:
                        route.continue_()
                    else:
                        route.abort()
                    return
                headers = {"access-control-allow-origin": "*", "access-control-allow-headers": "content-type",
                           "access-control-allow-methods": "GET,POST,OPTIONS", "content-type": "application/json"}
                if request.method == "OPTIONS":
                    route.fulfill(status=204, headers=headers)
                    return
                query = parse_qs(parsed.query)
                requests.append({"path": parsed.path, "query": query, "method": request.method})
                if parsed.path == "/admin/analytics/instagram":
                    offset = int(query.get("offset", [0])[0])
                    limit = int(query.get("limit", [60])[0])
                    result = {"rows": posts[offset:offset+limit], "total": len(posts), "summary": {
                        "total_posts": len(posts), "total_reach": 800, "total_views": 800,
                        "total_likes": 400, "total_comments": 0, "avg_engagement_rate_pct": 50,
                        "media_type_counts": {}, "profiles": [], "silver_last_ingested_at": None}}
                elif parsed.path == "/admin/analytics/meta-explorer/schema":
                    result = schema
                elif parsed.path == "/admin/analytics/meta-explorer/query":
                    result = {"columns": ["day", "spend"], "rows": [{"day": "2026-09-01", "spend": 123}]}
                elif parsed.path == "/admin/analytics/shopify-analytics":
                    result = {"rows": [], "totals": totals, "previous": totals, "channels": [],
                              "excluded_channels": [], "source": "shopify_daily",
                              "sales_through": None, "orders_through": None}
                elif parsed.path == "/admin/analytics/untested":
                    result = {"media": "video", "rows": [asset], "total_rows": 1, "with_sku_match": 0,
                              "without_sku_match": 1, "from_database": 1, "from_historical": 0,
                              "register_total": 1, "matched_assets": 1, "matched_ads": 1,
                              "dam_total": 1, "dam_tested": 1, "dam_untested": 0, "without_link": 0,
                              "computed_at": "2026-09-01T00:00:00Z"}
                elif parsed.path == "/admin/analytics/creative-testing/fixture-asset/ads":
                    result = {"asset_id": asset["id"], "media": "video", "ads": [ad]}
                else:
                    unexpected.append(parsed.path)
                    route.fulfill(status=501, headers=headers, body='{"detail":"Missing fixture"}')
                    return
                if parsed.path.endswith("/instagram") and query.get("search") == ["pending"]:
                    pending.append((route, headers, result))
                    return
                route.fulfill(status=200, headers=headers, body=json.dumps(result))

            page.route("**/*", route_request)
            page.goto(args.url + "/user/analytics#instagram", wait_until="domcontentloaded", timeout=30_000)
            expect(page.get_by_text("Illustrative post 59", exact=True)).to_be_visible()
            assert all(r["path"].endswith("/instagram") for r in requests), "Unvisited sections fetched data"
            page.get_by_placeholder("Search caption…").fill("Illustrative")
            expect(page.get_by_text("Illustrative post 59", exact=True)).to_be_visible()
            page.get_by_role("button", name="Load more (60 of 80)").click()
            expect(page.get_by_text("Illustrative post 79", exact=True)).to_be_visible()
            nav = page.get_by_role("navigation", name="Analytics sections")
            nav.get_by_role("button", name="Meta Explorer", exact=True).click()
            page.get_by_role("button", name="Test day", exact=True).click()
            page.get_by_role("button", name="Test spend", exact=True).click()
            page.locator('input[type="date"]').first.fill("2026-09-01")
            page.get_by_role("button", name="Generate", exact=True).click()
            expect(page.get_by_role("cell", name="123", exact=True)).to_be_visible()

            before = len(requests)
            start = perf_counter()
            nav.get_by_role("button", name="Instagram", exact=True).click()
            expect(page.get_by_placeholder("Search caption…")).to_be_visible()
            restored_filter = page.get_by_placeholder("Search caption…").input_value()
            restored_more = page.get_by_text("Illustrative post 79", exact=True).is_visible()
            elapsed = round((perf_counter()-start)*1000)
            nav.get_by_role("button", name="Meta Explorer", exact=True).click()
            expect(page.get_by_role("button", name="Generate", exact=True)).to_be_visible()
            restored_query = page.get_by_role("cell", name="123", exact=True).is_visible()
            # Give effects a chance to start requests; DOM snapshots alone can
            # miss a reload that races immediately after the navigation.
            page.wait_for_timeout(200)
            report = {"baseline": args.baseline, "return_ms": elapsed,
                      "filters_preserved": restored_filter == "Illustrative",
                      "load_more_preserved": restored_more, "explorer_result_preserved": restored_query,
                      "return_requests": len(requests)-before, "errors": errors, "unexpected": unexpected}
            if not args.baseline:
                assert report["filters_preserved"] and restored_more and restored_query, report
                assert report["return_requests"] == 0, report
                expect(page.locator('[data-analytics-section]:visible')).to_have_count(1)
                expect(page.locator('[data-analytics-section]')).to_have_count(2)
                assert not unexpected and not errors, report
                # Switching using the URL hash must share the same retained state.
                page.evaluate("location.hash = 'instagram'")
                expect(page.get_by_placeholder("Search caption…")).to_have_value("Illustrative")
                expect(page.get_by_text("Illustrative post 79", exact=True)).to_be_visible()
                # Retention also works at mobile widths; hidden panels cannot
                # appear in the layout or keyboard focus order.
                page.set_viewport_size({"width": 390, "height": 844})
                nav.get_by_role("button", name="Meta Explorer", exact=True).click()
                expect(page.get_by_role("cell", name="123", exact=True)).to_be_visible()
                expect(page.locator('[data-analytics-section]:visible')).to_have_count(1)
                assert page.locator('[data-analytics-section="instagram"]').get_attribute("inert") is not None
                page.screenshot(path="/tmp/analytics-cache-mobile.png", full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.screenshot(path="/tmp/analytics-cache-desktop.png", full_page=True)

                # An in-flight load survives hiding its section without duplication.
                nav.get_by_role("button", name="Instagram", exact=True).click()
                with page.expect_request(lambda req: "search=pending" in req.url):
                    page.get_by_placeholder("Search caption…").fill("pending")
                nav.get_by_role("button", name="Meta Explorer", exact=True).click()
                nav.get_by_role("button", name="Instagram", exact=True).click()
                page.wait_for_timeout(200)
                assert len(pending) == 1, "Navigation restarted an in-flight request"
                held_route, held_headers, held_result = pending.pop()
                held_route.fulfill(status=200, headers=held_headers, body=json.dumps(held_result))
                expect(page.get_by_text("Illustrative post 59", exact=True)).to_be_visible()

                nav.get_by_role("button", name="Shopify Analytics", exact=True).click()
                refresh = page.get_by_role("button", name="↻ Refresh", exact=True)
                expect(refresh).to_be_enabled()
                page.get_by_label("Include returns", exact=True).check()
                expect(refresh).to_be_enabled()
                before_refresh = len(requests)
                refresh.click()
                expect(refresh).to_be_enabled()
                assert len(requests) == before_refresh + 1, "Refresh reused the browser cache"
                nav.get_by_role("button", name="Instagram", exact=True).click()
                nav.get_by_role("button", name="Shopify Analytics", exact=True).click()
                expect(page.get_by_label("Include returns", exact=True)).to_be_checked()
                assert len(requests) == before_refresh + 1, "Shopify reloaded on return"

                # A nested ad preview must leave no portal or scroll lock behind.
                nav.get_by_role("button", name="Untested Assets", exact=True).click()
                page.get_by_role("button", name="View matched ads for asset fixture-asset").click()
                page.get_by_role("button", name="Preview ad fixture-ad", exact=True).click()
                expect(page.locator("dialog[open]")).to_have_count(2)
                page.evaluate("location.hash = 'instagram'")
                expect(page.locator("dialog[open]")).to_have_count(0)
                expect(page.locator("body")).not_to_have_css("overflow", "hidden")
                nav.get_by_role("button", name="Untested Assets", exact=True).click()
                expect(page.get_by_role("button", name="View matched ads for asset fixture-asset")).to_be_visible()
                expect(page.locator("dialog[open]")).to_have_count(0)
                assert not unexpected and not errors, {"unexpected": unexpected, "errors": errors}
                report.update(in_flight_preserved=True, refresh_bypasses_cache=True, popups_closed=True)
            print(json.dumps(report), flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
