"""Verify Ads Analyse request sequencing with local browser fixtures.

Run the admin frontend locally, then:
    .venv/bin/python scripts/verify_ads_initial_load.py
All analytics requests are intercepted; no production data is fetched.
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:3000")
    args = parser.parse_args()
    origin = urlparse(args.url)
    assert origin.hostname in {"localhost", "127.0.0.1"}
    source = (Path(__file__).parents[1] / "admin/src/lib/api.ts").read_text()
    fields = re.search(r"export interface AdsAnalyseTotals \{(.*?)\n\}", source, re.S).group(1)
    totals = dict.fromkeys(re.findall(r"^\s+(\w+)\??:", fields, re.M), 0)
    row_fields = re.search(r"export interface AdsAnalyseRow \{(.*?)\n\}", source, re.S).group(1)
    defaults = dict.fromkeys(re.findall(r"^\s+(\w+)\??:", row_fields, re.M))
    ads = [{**defaults, "ad_id": f"fixture-{i}", "ad_name": f"Illustrative ad {i}",
            "spend": 1000-i, "category": "Winner"} for i in range(101)]
    requests, held, unexpected, errors = [], [], [], []
    headers = {"access-control-allow-origin": "*", "access-control-allow-headers": "content-type",
               "access-control-allow-methods": "GET,POST,OPTIONS", "content-type": "application/json"}
    freshness = {"max_meta_day": "2026-09-26", "max_orders_day": "2026-09-26",
                 "max_daily_day": "2026-09-26", "distinct_skus": 1,
                 "computed_at": "2026-10-01T00:00:00Z"}

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
                    if parsed.netloc == origin.netloc:
                        route.continue_()
                    else:
                        route.abort()
                    return
                if request.method == "OPTIONS":
                    route.fulfill(status=204, headers=headers)
                    return
                requests.append({"path": parsed.path, "query": parse_qs(parsed.query)})
                if parsed.path.endswith("/data-freshness"):
                    held.append(route)
                    return
                if parsed.path == "/admin/analytics/ads-analyse":
                    query = parse_qs(parsed.query)
                    offset, limit = int(query.get("offset", [0])[0]), int(query.get("limit", [100])[0])
                    result = {"rows": ads[offset:offset+limit], "total": len(ads),
                              "totals": totals, "category_counts": {"Winner": len(ads)}}
                elif parsed.path == "/admin/analytics/ads-analyse/rollup":
                    result = {"rows": [], "total": 0, "decision_counts": {}}
                elif parsed.path == "/admin/analytics/meta-explorer/schema":
                    result = {"datasets": []}
                else:
                    unexpected.append(parsed.path)
                    route.fulfill(status=501, headers=headers, body='{"detail":"Missing fixture"}')
                    return
                route.fulfill(status=200, headers=headers, body=json.dumps(result))

            page.route("**/*", route_request)
            with page.expect_request(lambda req: "/data-freshness" in req.url):
                page.goto(args.url + "/user/analytics#ads-analyse", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(500)
            assert len(held) == 1, "Freshness probe duplicated"
            assert not any(r["path"].endswith("/ads-analyse") for r in requests), requests
            held.pop().fulfill(status=200, headers=headers, body=json.dumps(freshness))
            expect(page.get_by_text("Illustrative ad 0", exact=True)).to_be_visible()
            ad_requests = [r for r in requests if r["path"].endswith("/ads-analyse")]
            assert len(ad_requests) == 1, ad_requests
            assert ad_requests[0]["query"]["to_date"] == ["2026-09-26"], ad_requests

            panel = page.locator('[data-analytics-section="ads-analyse"]')
            panel.get_by_role("button", name="Fetch next 500 (100/101)", exact=True).click()
            expect(panel.get_by_role("button", name="Next", exact=True)).to_be_enabled()
            panel.get_by_role("button", name="Next", exact=True).click()
            expect(page.get_by_text("Illustrative ad 100", exact=True)).to_be_visible()
            panel.get_by_role("button", name="Campaigns", exact=True).click()
            expect(page.get_by_text("No campaigns found.", exact=True)).to_be_visible()
            panel.get_by_placeholder("Contains…").fill("Illustrative")
            with page.expect_request(lambda req: "/rollup?" in req.url and "Illustrative" in req.url):
                page.wait_for_timeout(500)
            expect(page.get_by_text("No campaigns found.", exact=True)).to_be_visible()
            assert len([r for r in requests if r["path"].endswith("/ads-analyse")]) == 2
            panel.get_by_role("button", name="Ads", exact=True).click()
            expect(page.get_by_text("Illustrative ad 100", exact=True)).to_be_visible()

            nav = page.get_by_role("navigation", name="Analytics sections")
            with page.expect_response(lambda response: "/meta-explorer/schema" in response.url):
                nav.get_by_role("button", name="Meta Explorer", exact=True).click()
            expect(page.locator('[data-analytics-section="meta-explorer"]')).to_be_visible()
            page.wait_for_timeout(200)
            before = len(requests)
            nav.get_by_role("button", name="Ads Analyse", exact=True).click()
            expect(page.get_by_text("Illustrative ad 100", exact=True)).to_be_visible()
            page.wait_for_timeout(200)
            assert len(requests) == before, {"return_requests": requests[before:]}
            page.screenshot(path="/tmp/ads-optimization-desktop.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator('[data-analytics-section]:visible')).to_have_count(1)
            page.screenshot(path="/tmp/ads-optimization-mobile.png", full_page=True)
            assert not errors and not unexpected, {"errors": errors, "unexpected": unexpected}
            print(json.dumps({"initial_ads_requests": 1, "date_anchor": "2026-09-26",
                              "unselected_grain_requests": 0, "return_requests": 0,
                              "loaded_pages_preserved": True,
                              "errors": errors}), flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
