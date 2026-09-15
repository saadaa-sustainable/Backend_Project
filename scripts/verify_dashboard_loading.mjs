#!/usr/bin/env node
/**
 * Verify CPIS loading against browser-only fixtures; no database is needed.
 * Start the local admin frontend separately, then run:
 *   DASHBOARD_PLAYWRIGHT_MODULE=/tmp/browser/node_modules/playwright-core/index.mjs \
 *     node scripts/verify_dashboard_loading.mjs http://127.0.0.1:3000
 * Optional: DASHBOARD_BROWSER_EXECUTABLE, DASHBOARD_SCREENSHOT.
 */
import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const frontend = new URL(process.argv[2] ?? process.env.DASHBOARD_FRONTEND_URL ?? "http://127.0.0.1:3000");
assert(["localhost", "127.0.0.1", "[::1]"].includes(frontend.hostname), "Use a local frontend URL.");
const target = new URL("/user/analytics#cpis", frontend);
let modulePath = process.env.DASHBOARD_PLAYWRIGHT_MODULE ?? "playwright-core";
if (isAbsolute(modulePath) || modulePath.startsWith(".")) {
  let resolved = resolve(modulePath);
  if ((await stat(resolved)).isDirectory()) resolved = join(resolved, "index.mjs");
  modulePath = pathToFileURL(resolved).href;
}
const { chromium } = await import(modulePath);
const screenshot = process.env.DASHBOARD_SCREENSHOT ?? "/tmp/saadaa-dashboard-loading.png";
const apiSource = await readFile(new URL("../admin/src/lib/api.ts", import.meta.url), "utf8");
const rowInterface = apiSource.match(/export interface CpisUtmRow \{([\s\S]*?)^\}/m)?.[1];
assert(rowInterface, "CpisUtmRow interface must exist for complete nullable fixture defaults.");
const fields = [...rowInterface.matchAll(/^\s+([a-zA-Z_]\w*)\??\s*:/gm)].map((match) => match[1]);
assert(fields.length > 70, "Fixture schema extraction unexpectedly omitted CPIS fields.");
const cap = "2026-09-10";
const initialFrom = "2026-08-12";
const allRows = Array.from({ length: 80 }, (_, index) => ({
  ...Object.fromEntries(fields.map((field) => [field, null])),
  master_sku: `SDT${String(index + 1).padStart(3, "0")}`,
  product_name: `Fixture product ${index + 1}`,
  category: "Womenswear",
  window_key: "30d",
  window_from: initialFrom,
  window_to: cap,
  variant_count: 4,
  available_variant_count: 4,
  units_in_stock: 20,
  attributed_orders: 3,
  attributed_units: 4,
  attributed_revenue: 400,
  ad_spend: 100,
  name_matched_ads: 2,
  name_matched_spend: 100,
  utm_matched_ncp: 2,
  roas: 4,
}));

const requests = [];
const unexpected = [];
const pageErrors = [];
const consoleErrors = [];
const blockedExternal = [];
let releaseFreshness;
const freshnessGate = new Promise((resolveGate) => { releaseFreshness = resolveGate; });
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const mainPath = "/admin/analytics/cpis-utm";
const batchPath = `${mainPath}/spend-trends`;
const matching = (path) => requests.filter((request) => request.path === path);
const batches = () => matching(batchPath);
const mains = () => matching(mainPath);

async function waitFor(check, label, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await sleep(25);
  }
  assert.fail(`Timed out waiting for ${label}`);
}

const browser = await chromium.launch({
  headless: true,
  ...(process.env.DASHBOARD_BROWSER_EXECUTABLE ? { executablePath: process.env.DASHBOARD_BROWSER_EXECUTABLE } : {}),
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, serviceWorkers: "block" });
const page = await context.newPage();
page.setDefaultTimeout(30_000);
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });

// Catch every API request even when NEXT_PUBLIC_API_BASE_URL names another host.
// Only frontend assets may reach the network; analytics never reach a server.
await context.route("**/*", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  if (!url.pathname.startsWith("/admin/")) {
    if (url.origin === frontend.origin) return route.continue();
    blockedExternal.push(request.url());
    return route.abort();
  }
  const headers = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "content-type",
    "content-type": "application/json",
  };
  if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers, body: "" });
  const body = request.postData() ? JSON.parse(request.postData()) : null;
  const record = { path: url.pathname, method: request.method(), params: Object.fromEntries(url.searchParams), body };
  requests.push(record);
  let result;
  if (url.pathname === `${mainPath}/data-freshness`) {
    await freshnessGate;
    result = { max_meta_day: cap, max_orders_day: cap, max_daily_day: cap, distinct_skus: 80, computed_at: `${cap}T00:00:00Z` };
  } else if (url.pathname === mainPath) {
    const search = (url.searchParams.get("search") ?? "").toLowerCase();
    const filtered = allRows.filter((row) => row.master_sku.toLowerCase().includes(search));
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const limit = Number(url.searchParams.get("limit") ?? 500);
    result = {
      rows: filtered.slice(offset, offset + limit).map((row) => ({ ...row,
        window_from: url.searchParams.get("from_date") ?? initialFrom,
        window_to: url.searchParams.get("to_date") ?? cap,
      })),
      total: filtered.length,
      meta_total_spend: 8000,
      attributed_spend: 8000,
      untethered_spend: 0,
      untethered_ad_unknown: 0,
      untethered_lag: 0,
      untethered_no_conversion: 0,
    };
    // Makes loading behavior observable without a slow external service.
    await sleep(100);
  } else if (url.pathname === batchPath) {
    result = { rows: body.master_skus.map((sku) => ({
      master_sku: sku,
      window_key: body.window,
      window_from: body.from_date ?? initialFrom,
      window_to: body.to_date ?? cap,
      spend_trend_current: [10, 20, 30],
      spend_trend_prev_total: 40,
    })) };
  } else if (url.pathname === "/admin/analytics/saturation-curve") {
    result = { y_metric: "ncp_count", y_label: "NCP", points: [], fit: null, excluded_zero_or_missing: 0 };
  } else if (url.pathname === "/admin/analytics/untested") {
    result = { media: "video", rows: [], total_rows: 0, with_sku_match: 0, without_sku_match: 0, computed_at: `${cap}T00:00:00Z` };
  } else {
    unexpected.push(record);
    return route.fulfill({ status: 501, headers, body: JSON.stringify({ detail: "No fixture for this API request" }) });
  }
  return route.fulfill({ status: 200, headers, body: JSON.stringify(result) });
});

try {
  await page.goto(target.href, { waitUntil: "domcontentloaded" });
  await waitFor(() => matching(`${mainPath}/data-freshness`).length === 1, "freshness request");
  await sleep(100);
  assert.equal(mains().length, 0, "Full CPIS query must wait for freshness.");
  releaseFreshness();

  const table = page.locator("table").filter({ has: page.getByRole("columnheader", { name: "SKU Code", exact: true }) });
  const tableRows = table.locator("tbody > tr");
  const navigation = page.getByRole("navigation", { name: "Analytics sections" });
  await waitFor(async () => await tableRows.count() === 50 && batches().length === 1, "first 50 rows and one trend batch");
  await sleep(100);
  assert.equal(mains().length, 1, "Stale freshness must still produce exactly one initial full query.");
  assert.equal(mains()[0].params.from_date, initialFrom);
  assert.equal(mains()[0].params.to_date, cap);
  assert.deepEqual(batches()[0].body.master_skus, allRows.slice(0, 50).map((row) => row.master_sku));
  assert.equal(batches()[0].body.from_date, initialFrom);
  assert.equal(batches()[0].body.to_date, cap);
  assert.equal(matching(`${mainPath}/spend-trend`).length, 0, "Per-row trend requests must be gone.");
  assert.equal(requests.filter((request) => request.path.includes("/dashboard/")).length, 0, "#cpis must not mount Dashboard.");
  assert.equal(await page.getByRole("button", { name: "Export CSV", exact: true }).getAttribute("title"), "Export 80 rows as CSV");

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV", exact: true }).click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  assert(stream, "CSV download should be readable.");
  let csv = "";
  for await (const chunk of stream) csv += chunk.toString();
  assert.equal(csv.trim().split("\n").length, 81, "CSV must contain all 80 rows plus its header.");
  await page.screenshot({ path: screenshot, fullPage: true });

  await page.getByRole("button", { name: "Next", exact: true }).click();
  await waitFor(async () => await tableRows.count() === 30 && batches().length === 2, "second page's 30 rows");
  assert.deepEqual(batches()[1].body.master_skus, allRows.slice(50).map((row) => row.master_sku));
  assert.equal(mains().length, 1, "Local table pagination must not refetch the main dataset.");

  // Revisit before 60-second cache TTL, after deliberately leaving the second page.
  await navigation.getByRole("button", { name: "Untested Assets", exact: true }).click();
  await page.getByRole("heading", { name: "Untested Assets", exact: true }).waitFor();
  await navigation.getByRole("button", { name: "CPIS", exact: true }).click();
  await waitFor(async () => await tableRows.count() === 50, "cached CPIS revisit");
  await sleep(150);
  assert.equal(mains().length, 1, "Tab revisit must reuse the cached main response.");
  assert.equal(batches().length, 2, "Revisit must reuse the first page's cached trend batch.");
  assert.equal(matching(`${mainPath}/data-freshness`).length, 1);

  const search = page.getByPlaceholder("Search master SKU…");
  await search.pressSequentially("SDT080", { delay: 30 });
  assert.equal(mains().length, 1, "Search should not issue requests for individual keystrokes.");
  await waitFor(async () => mains().length === 2 && await tableRows.count() === 1, "debounced search result");
  assert.equal(mains()[1].params.search, "SDT080");
  assert.equal(await tableRows.first().locator("td").first().innerText(), "SDT080");
  await waitFor(() => batches().length === 3, "single-row search trend batch");

  await search.fill("");
  await waitFor(async () => await tableRows.count() === 50, "cached unfiltered response");
  assert.equal(mains().length, 2, "Clearing search should reuse the original cached dataset.");

  const dateInputs = page.locator('input[type="date"]');
  await dateInputs.nth(0).fill("2026-08-20");
  await dateInputs.nth(1).fill("2026-09-05");
  await waitFor(() => batches().some((request) => request.body.from_date === "2026-08-20" && request.body.to_date === "2026-09-05"), "custom-date trend batch");
  assert(mains().some((request) => request.params.from_date === "2026-08-20" && request.params.to_date === "2026-09-05"));
  assert.equal(matching(`${mainPath}/spend-trend`).length, 0);
  assert.deepEqual(unexpected, [], "Every API request should match an explicit fixture.");
  assert.deepEqual(pageErrors, [], "Browser should have no uncaught runtime errors.");
  assert.deepEqual(consoleErrors, [], "Browser should have no console errors, including invalid table nesting.");

  console.log(JSON.stringify({
    status: "passed", screenshot,
    checks: ["freshness gate", "50/30 pagination", "one batch per page", "full 80-row CSV", "search debounce", "cached revisit", "deep-link isolation", "custom dates"],
    counts: Object.fromEntries([...new Set(requests.map((request) => request.path))].map((path) => [path, matching(path).length])),
    trendBatchSizes: batches().map((request) => request.body.master_skus.length),
    blockedExternal,
  }, null, 2));
} catch (error) {
  await page.screenshot({ path: screenshot.replace(/\.png$/, "-failed.png"), fullPage: true }).catch(() => {});
  console.error(JSON.stringify({ requests, unexpected, pageErrors, consoleErrors, blockedExternal }, null, 2));
  throw error;
} finally {
  releaseFreshness();
  await browser.close();
}
