#!/usr/bin/env node
/**
 * Verify Creative Testing asset/ad previews and destinations with browser-only fixtures.
 * Start the local admin frontend, then run:
 *   DASHBOARD_PLAYWRIGHT_MODULE=/tmp/browser/node_modules/playwright-core/index.mjs \
 *     node scripts/verify_asset_previews.mjs http://127.0.0.1:3008
 * Optional: DASHBOARD_BROWSER_EXECUTABLE, ASSET_PREVIEW_SCREENSHOT.
 * All API and provider requests are mocked; no analytics service is contacted.
 */
import assert from "node:assert/strict";
import { stat } from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const frontend = new URL(process.argv[2] ?? "http://127.0.0.1:3008");
assert(["localhost", "127.0.0.1", "[::1]"].includes(frontend.hostname), "Use a local frontend URL.");
let modulePath = process.env.DASHBOARD_PLAYWRIGHT_MODULE ?? "playwright-core";
if (isAbsolute(modulePath) || modulePath.startsWith(".")) {
  let resolved = resolve(modulePath);
  if ((await stat(resolved)).isDirectory()) resolved = join(resolved, "index.mjs");
  modulePath = pathToFileURL(resolved).href;
}
const { chromium } = await import(modulePath);
const screenshot = process.env.ASSET_PREVIEW_SCREENSHOT ?? "/tmp/saadaa-asset-previews.png";
const fixtureOrigin = "https://assets.preview.test";
const originalAd = {
  ad_id: "AD-ORIGINAL", ad_name: "Fixture original outing",
  ad_preview_url: "https://www.instagram.com/p/fixture-original/",
  destination_url: "https://website.preview.test/products/original?utm_source=facebook&utm_content=original%20ad",
};
const iterationAd = {
  ad_id: "AD-ITERATION", ad_name: "Fixture first iteration",
  ad_preview_url: "https://www.facebook.com/123/posts/456",
  destination_url: "https://website.preview.test/products/iteration?variant=123&utm_content=iteration%2Fone",
};
const unsafeAd = {
  ad_id: "AD-UNSAFE", ad_name: "Fixture unavailable links",
  ad_preview_url: "javascript:alert('unsafe-preview')",
  destination_url: "data:text/html,unsafe-destination",
};
const adRows = [originalAd, iterationAd, unsafeAd].map((fixture, index) => ({
  ad_status: "ACTIVE", category: "Winner", ad_created_date: `2026-09-${10 + index}`,
  is_copy: index > 0, iteration_index: index, spend: index === 1 ? 2000 : 1000,
  impressions: 2000, purchases: 4, conv_value: 4000, ncp_count: 3,
  ftewv_count: 2, roas: 4, cost_per_ncp: 333, cost_per_ftewv: 500,
  ctr_pct: 2, f1_pass: true, f2_pass: true, f3_pass: null, f4_pass: null,
  ...fixture,
}));
const fixtures = [
  {
    asset_id: "ASSET-IMAGE", media: "graphic", preview_url: `${fixtureOrigin}/image.jpg`,
    preview_ad_id: iterationAd.ad_id, ad_preview_url: iterationAd.ad_preview_url,
    destination_url: iterationAd.destination_url, kind: "iteration", ads: 3, iteration_count: 2,
  },
  { asset_id: "ASSET-VIDEO", media: "video", preview_url: `${fixtureOrigin}/video.mp4` },
  { asset_id: "ASSET-DRIVE", media: "video", preview_url: "https://drive.google.com/file/d/fixture-drive-file/view?resourcekey=fixture-key" },
  { asset_id: "ASSET-INSTAGRAM", media: "influencer", preview_url: "https://www.instagram.com/reel/fixture-reel/" },
  { asset_id: "ASSET-MISSING", media: "graphic", preview_url: null },
  { asset_id: "ASSET-BROKEN-THUMB", media: "graphic", preview_url: `${fixtureOrigin}/image.jpg`, thumbnail_url: `${fixtureOrigin}/broken-thumbnail.jpg` },
  { asset_id: "ASSET-BROKEN-IMAGE", media: "graphic", preview_url: `${fixtureOrigin}/broken-image.jpg` },
  { asset_id: "ASSET-WEBSITE", media: "video", preview_url: `${fixtureOrigin}/creative-page` },
  { asset_id: "ASSET-FOLDER", media: "graphic", preview_url: "https://drive.google.com/drive/folders/fixture-folder" },
  { asset_id: "ASSET-THUMB-ONLY", media: "graphic", preview_url: null, thumbnail_url: `${fixtureOrigin}/thumbnail.jpg` },
  {
    asset_id: "ASSET-UNSAFE", media: "graphic", preview_url: null,
    preview_ad_id: unsafeAd.ad_id, ad_preview_url: unsafeAd.ad_preview_url,
    destination_url: unsafeAd.destination_url,
  },
];
const rows = fixtures.map((fixture, index) => ({
  asset_created: "2026-09-10", category: "Winner", sample_ad_name: "PDP Fixture creative",
  kind: "new", iteration_count: 0, ads: 1, copy_ads: 0, ads_in_window: 1,
  first_ad_date: "2026-09-10", last_ad_date: "2026-09-15", account_name: "Fixture account",
  name_conflict: false, spend: 1000 + index, impressions: 2000, purchases: 4,
  conv_value: 4000, ncp_count: 3, ftewv_count: 2, roas: 4,
  cost_per_ncp: 333, cost_per_ftewv: 500, ctr_pct: 2, thumbnail_url: null,
  preview_ad_id: null, ad_preview_url: null, destination_url: null,
  ...fixture,
}));
const totals = {
  assets: rows.length, new_creatives: rows.length, iterations: 0,
  spend: 10_000, impressions: 20_000, purchases: 40, conv_value: 40_000,
  ncp_count: 30, ftewv_count: 20, roas: 4, cost_per_ncp: 333,
  cost_per_ftewv: 500, thruplays: 100, three_sec_plays: 300,
  outbound_clicks: 100, post_engagements: 200,
};
const imageSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="300" viewBox="0 0 240 300"><rect width="240" height="300" fill="#e8ddc9"/><path d="M83 45 L54 73 L66 111 L79 99 L77 179 L91 261 L116 261 L120 187 L127 261 L153 261 L165 178 L162 99 L176 111 L187 74 L155 45 Z" fill="#668573"/><text x="120" y="287" text-anchor="middle" fill="#3a362e" font-family="sans-serif" font-size="11">Fixture creative</text></svg>';
const apiRequests = [];
const providerRequests = [];
const unexpected = [];
const pageErrors = [];
const consoleErrors = [];
const mainPath = "/admin/analytics/creative-testing";
const adsRequests = () => apiRequests.filter((request) => request.path.endsWith("/ads"));
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
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
await context.route("**/*", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  if (url.pathname.startsWith("/admin/")) {
    const headers = {
      "access-control-allow-origin": "*", "access-control-allow-methods": "GET,OPTIONS",
      "access-control-allow-headers": "content-type", "content-type": "application/json",
    };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers, body: "" });
    apiRequests.push({ path: url.pathname, method: request.method() });
    assert.equal(request.method(), "GET", "Preview verification should perform no mutations.");
    let result;
    if (url.pathname === mainPath) {
      result = { rows, total: rows.length, totals, kind_counts: { new: rows.length, iteration: 0 }, category_counts: { Winner: rows.length } };
    } else if (url.pathname === `${mainPath}/ASSET-IMAGE/ads`) {
      result = { asset_id: "ASSET-IMAGE", media: "graphic", ads: adRows };
    } else {
      unexpected.push(request.url());
      return route.fulfill({ status: 501, headers, body: JSON.stringify({ detail: "No API fixture" }) });
    }
    return route.fulfill({ status: 200, headers, body: JSON.stringify(result) });
  }
  if (url.origin === frontend.origin) return route.continue();
  providerRequests.push({ url: url.href, type: request.resourceType() });
  if (["assets.preview.test", "website.preview.test", "drive.google.com", "www.instagram.com", "www.facebook.com"].includes(url.hostname)) {
    if (request.resourceType() === "image") {
      // Successful HTTP with invalid image bytes tests decode failure without a deliberate network error.
      const broken = url.pathname.startsWith("/broken-");
      return route.fulfill({ status: 200, contentType: broken ? "image/jpeg" : "image/svg+xml", body: broken ? "not-an-image" : imageSvg });
    }
    if (request.resourceType() === "document") {
      return route.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><html><body><p>Fixture asset provider preview</p></body></html>" });
    }
    if (request.resourceType() === "media") return route.fulfill({ status: 200, contentType: "video/mp4", body: "" });
  }
  unexpected.push(request.url());
  return route.abort();
});

try {
  await page.goto(new URL("/user/analytics#creative-testing", frontend).href, { waitUntil: "domcontentloaded" });
  const table = page.locator("table").filter({ has: page.getByRole("button", { name: "Preview asset ASSET-IMAGE", exact: true }) });
  await waitFor(async () => await table.locator("tbody > tr").count() === fixtures.length, "asset fixture rows");
  const previewButton = (id) => table.getByRole("button", { name: `Preview asset ${id}`, exact: true });
  const assetRow = (id) => table.locator("tbody > tr").filter({ has: page.getByRole("button", { name: `Preview asset ${id}`, exact: true }) });
  for (const fixture of fixtures) {
    assert.equal(await previewButton(fixture.asset_id).count(), 1, "Every asset should have one preview box.");
    const link = assetRow(fixture.asset_id).getByRole("link", { name: `Open preview for ${fixture.asset_id}`, exact: true });
    if (fixture.preview_url || fixture.thumbnail_url) {
      assert.equal(await link.getAttribute("href"), fixture.preview_url ?? fixture.thumbnail_url);
      assert.equal(await link.getAttribute("target"), "_blank");
      assert.match(await link.getAttribute("rel"), /noopener/);
      assert.equal(await previewButton(fixture.asset_id).isEnabled(), true);
    } else {
      assert.equal(await link.count(), 0);
      assert.equal(await previewButton(fixture.asset_id).isDisabled(), true);
      assert.equal(await assetRow(fixture.asset_id).getByText("No preview link", { exact: true }).count(), 1);
    }
  }
  async function assertOutbound(link, href) {
    assert.equal(await link.getAttribute("href"), href, "Keep the full source URL and its query parameters.");
    assert.equal(await link.getAttribute("target"), "_blank");
    assert.match(await link.getAttribute("rel"), /noopener/);
  }
  const representativeRow = assetRow("ASSET-IMAGE");
  await assertOutbound(representativeRow.getByRole("link", { name: `Open ad preview for ${iterationAd.ad_id}`, exact: true }), iterationAd.ad_preview_url);
  await assertOutbound(representativeRow.getByRole("link", { name: `Open website destination for ${iterationAd.ad_id}`, exact: true }), iterationAd.destination_url);
  assert.equal(await representativeRow.getByRole("button", { name: `Preview ad ${iterationAd.ad_id}`, exact: true }).count(), 1);
  for (const id of ["ASSET-MISSING", "ASSET-UNSAFE"]) {
    const row = assetRow(id);
    assert.equal(await row.getByRole("link", { name: /^Open ad preview for / }).count(), 0, "Missing or unsafe ad previews must not be clickable.");
    assert.equal(await row.getByRole("link", { name: /^Open website destination for / }).count(), 0, "Missing or unsafe website URLs must not be clickable.");
    assert.equal(await row.getByRole("button", { name: /^Preview ad / }).evaluateAll((buttons) => buttons.filter((button) => !button.disabled).length), 0);
  }
  assert.equal(await table.locator('a[href^="javascript:"], a[href^="data:"], a[href="#"]').count(), 0, "Never render unsafe URLs or clickable placeholders.");
  await assetRow("ASSET-THUMB-ONLY").scrollIntoViewIfNeeded();
  await waitFor(async () => await previewButton("ASSET-BROKEN-THUMB").locator("img").count() === 0, "broken thumbnail fallback");
  assert.equal(await page.locator("dialog, iframe, video").count(), 0, "Table must not eagerly mount preview players.");
  assert.equal(providerRequests.filter((request) => ["document", "media"].includes(request.type)).length, 0, "Table must not fetch embeds or video media.");
  assert.equal(adsRequests().length, 0);
  await representativeRow.scrollIntoViewIfNeeded();
  await page.screenshot({ path: screenshot, fullPage: true });

  async function openOutbound(link, expectedUrl, expectedAdsRequests = 0) {
    const popupPromise = context.waitForEvent("page");
    await link.click();
    const popup = await popupPromise;
    await popup.waitForLoadState("domcontentloaded");
    assert.equal(popup.url(), expectedUrl);
    assert.equal(adsRequests().length, expectedAdsRequests, "Opening an external link must not request ad details.");
    await popup.close();
  }

  async function openAdPreview(scope, ad, expectedAdsRequests = 0) {
    await scope.getByRole("button", { name: `Preview ad ${ad.ad_id}`, exact: true }).click();
    const adDialog = page.getByRole("dialog", { name: `Ad preview · ${ad.ad_id}`, exact: true });
    await adDialog.waitFor({ state: "visible" });
    assert.equal(await adDialog.evaluate((element) => element.matches(":modal")), true);
    assert.equal(adsRequests().length, expectedAdsRequests, "Previewing an ad must not request ad details.");
    await assertOutbound(adDialog.locator(`a[href="${ad.ad_preview_url}"]`), ad.ad_preview_url);
    assert.equal(await adDialog.locator("iframe").count(), 1, "Supported ad permalinks should render an on-demand provider preview.");
    return adDialog;
  }

  let adDialog = await openAdPreview(representativeRow, iterationAd);
  await adDialog.getByRole("button", { name: "Close ad preview", exact: true }).click();
  await adDialog.waitFor({ state: "detached" });
  await openOutbound(representativeRow.getByRole("link", { name: `Open ad preview for ${iterationAd.ad_id}`, exact: true }), iterationAd.ad_preview_url);
  await openOutbound(representativeRow.getByRole("link", { name: `Open website destination for ${iterationAd.ad_id}`, exact: true }), iterationAd.destination_url);
  assert.equal(await page.locator("dialog").count(), 0);

  async function openPreview(id) {
    await previewButton(id).click();
    const dialog = page.getByRole("dialog", { name: `Asset preview · ${id}`, exact: true });
    await dialog.waitFor({ state: "visible" });
    assert.equal(await dialog.evaluate((element) => element.matches(":modal")), true, "Preview should be a native modal dialog.");
    assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden");
    assert.equal(adsRequests().length, 0, "Preview clicks must not trigger the asset ads modal.");
    return dialog;
  }
  async function expectClosed() {
    await page.locator("dialog").waitFor({ state: "detached" });
    assert.equal(await page.evaluate(() => document.body.style.overflow), "");
    assert.equal(adsRequests().length, 0);
  }

  let dialog = await openPreview("ASSET-IMAGE");
  await waitFor(async () => await dialog.getByAltText("Creative asset ASSET-IMAGE").evaluate((element) => element.complete && element.naturalWidth > 0), "direct image preview");
  assert.equal(await dialog.getByRole("button", { name: "Close asset preview" }).evaluate((element) => element === document.activeElement), true);
  await page.screenshot({ path: screenshot.replace(/\.png$/, "-dialog.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expectClosed();

  dialog = await openPreview("ASSET-VIDEO");
  const video = dialog.locator("video");
  assert.equal(await video.getAttribute("src"), `${fixtureOrigin}/video.mp4`);
  assert.equal(await video.getAttribute("preload"), "none");
  assert.equal(await video.getAttribute("autoplay"), null);
  assert.equal(await video.evaluate((element) => element.controls), true);
  assert.equal(providerRequests.filter((request) => request.type === "media").length, 0, "Video bytes should wait until playback.");
  await video.evaluate((element) => element.dispatchEvent(new Event("error")));
  await dialog.getByText(/This preview could not be loaded/).waitFor();
  assert.equal(await dialog.getByRole("link", { name: "Open preview ↗" }).getAttribute("href"), `${fixtureOrigin}/video.mp4`);
  await dialog.getByRole("button", { name: "Close asset preview" }).click();
  await expectClosed();

  dialog = await openPreview("ASSET-DRIVE");
  assert.equal(await dialog.locator("iframe").getAttribute("src"), "https://drive.google.com/file/d/fixture-drive-file/preview?resourcekey=fixture-key");
  await waitFor(() => providerRequests.some((request) => request.type === "document" && request.url.includes("fixture-drive-file/preview")), "on-demand Drive embed");
  await page.mouse.click(3, 3);
  await expectClosed();

  dialog = await openPreview("ASSET-INSTAGRAM");
  assert.equal(await dialog.locator("iframe").getAttribute("src"), "https://www.instagram.com/reel/fixture-reel/embed/captioned/");
  await dialog.getByRole("button", { name: "Close asset preview" }).click();
  await expectClosed();

  for (const id of ["ASSET-WEBSITE", "ASSET-FOLDER"]) {
    dialog = await openPreview(id);
    await dialog.getByText(/This asset opens on its source website/).waitFor();
    assert.equal(await dialog.locator("iframe, video, img").count(), 0, "Unknown pages and folders should retain their source link without embedding.");
    await page.keyboard.press("Escape");
    await expectClosed();
  }

  dialog = await openPreview("ASSET-BROKEN-IMAGE");
  await dialog.getByText(/This preview could not be loaded/).waitFor();
  assert.equal(await dialog.getByRole("link", { name: "Open preview ↗" }).getAttribute("href"), `${fixtureOrigin}/broken-image.jpg`);
  await page.keyboard.press("Escape");
  await expectClosed();

  await openOutbound(assetRow("ASSET-WEBSITE").getByRole("link", { name: "Open preview for ASSET-WEBSITE", exact: true }), `${fixtureOrigin}/creative-page`);
  assert.equal(await page.locator("dialog").count(), 0);
  assert.equal(adsRequests().length, 0, "External preview links must not open the ads modal.");

  // Existing row drill-down remains available outside the preview cell.
  await assetRow("ASSET-IMAGE").getByText("ASSET-IMAGE", { exact: true }).click();
  const selectedAd = page.getByRole("region", { name: "Selected ad", exact: true });
  await selectedAd.getByText(originalAd.ad_name, { exact: true }).waitFor();
  assert.equal(adsRequests().length, 1);
  assert.equal(await page.locator("dialog").count(), 0);

  async function assertSelected(ad) {
    await selectedAd.getByText(ad.ad_name, { exact: true }).waitFor();
    await assertOutbound(selectedAd.getByRole("link", { name: `Open ad preview for ${ad.ad_id}`, exact: true }), ad.ad_preview_url);
    await assertOutbound(selectedAd.getByRole("link", { name: `Open website destination for ${ad.ad_id}`, exact: true }), ad.destination_url);
  }
  await assertSelected(originalAd);
  const outingsTable = page.locator("table").filter({ has: page.getByRole("columnheader", { name: "Outing", exact: true }) });
  for (const ad of [originalAd, iterationAd]) {
    await assertOutbound(outingsTable.getByRole("link", { name: `Open ad preview for ${ad.ad_id}`, exact: true }), ad.ad_preview_url);
    await assertOutbound(outingsTable.getByRole("link", { name: `Open website destination for ${ad.ad_id}`, exact: true }), ad.destination_url);
  }
  assert.equal(await outingsTable.getByRole("link", { name: new RegExp(unsafeAd.ad_id) }).count(), 0);
  await openOutbound(outingsTable.getByRole("link", { name: `Open website destination for ${iterationAd.ad_id}`, exact: true }), iterationAd.destination_url, 1);
  await assertSelected(originalAd);
  await openOutbound(selectedAd.getByRole("link", { name: `Open website destination for ${originalAd.ad_id}`, exact: true }), originalAd.destination_url, 1);
  adDialog = await openAdPreview(selectedAd, originalAd, 1);
  await page.keyboard.press("Escape");
  await adDialog.waitFor({ state: "detached" });
  await assertSelected(originalAd);
  assert.equal(adsRequests().length, 1, "Closing the nested preview must retain the underlying ads modal.");
  await page.getByRole("button", { name: /^1st iteration/ }).click();
  await assertSelected(iterationAd);
  await page.screenshot({ path: screenshot.replace(/\.png$/, "-ad-details.png"), fullPage: true });
  assert.equal(await selectedAd.getByRole("link", { name: `Open website destination for ${originalAd.ad_id}`, exact: true }).count(), 0);
  adDialog = await openAdPreview(selectedAd, iterationAd, 1);
  await adDialog.getByRole("button", { name: "Close ad preview", exact: true }).click();
  await adDialog.waitFor({ state: "detached" });
  await assertSelected(iterationAd);
  await page.getByRole("button", { name: /^2nd iteration/ }).click();
  await selectedAd.getByText(unsafeAd.ad_name, { exact: true }).waitFor();
  assert.equal(await selectedAd.getByRole("link", { name: /^Open ad preview for / }).count(), 0);
  assert.equal(await selectedAd.getByRole("link", { name: /^Open website destination for / }).count(), 0);
  assert.equal(await selectedAd.locator("a").count(), 0, "The unavailable outing should contain no clickable URL placeholders.");
  assert.equal(await selectedAd.getByRole("button", { name: /^Preview ad / }).evaluateAll((buttons) => buttons.filter((button) => !button.disabled).length), 0);
  assert.equal(adsRequests().length, 1, "Switching outings should use the existing detail response.");
  await page.keyboard.press("Escape");
  await selectedAd.waitFor({ state: "detached" });
  assert.deepEqual(unexpected, [], "Every external request should be explicitly mocked.");
  assert.deepEqual(pageErrors, [], "No uncaught browser errors expected.");
  assert.deepEqual(consoleErrors, [], "No console errors expected, including deliberate image decode failures.");
  console.log(JSON.stringify({
    status: "passed", screenshot,
    checks: ["preview boxes and source links", "representative ad and destination URLs", "missing and unsafe URL states", "lazy media and embeds", "native modal and close controls", "image/video/Drive/Instagram previews", "media failure fallback", "unknown website/folder fallback", "preview click isolation", "external links open new tabs", "per-outing ad and destination links", "nested ad-preview Escape isolation"],
    apiRequests, providerRequestCount: providerRequests.length,
  }, null, 2));
} catch (error) {
  await page.screenshot({ path: screenshot.replace(/\.png$/, "-failed.png"), fullPage: true }).catch(() => {});
  console.error(JSON.stringify({ apiRequests, providerRequests, unexpected, pageErrors, consoleErrors }, null, 2));
  throw error;
} finally {
  await browser.close();
}
