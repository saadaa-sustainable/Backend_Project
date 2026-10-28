/**
 * Price-change impact -> one tab per repriced SKU, plus three page-type
 * tabs and a summary. See sheets/README.md for setup.
 *
 * Credentials stay in Script Properties: SUPABASE_URL, SUPABASE_KEY,
 * SPREADSHEET_ID. The anon key is enough -- verified by reading every
 * view as the `anon` role.
 *
 * Public entry points: syncPriceImpact, setupPriceImpactTrigger,
 * removePriceImpactTrigger.
 *
 * Layout
 * ------
 *   Summary     one row per price direction, including the untouched
 *               control group
 *   Product     every repriced SKU x its product pages
 *   Collection  every repriced SKU x the collection pages it sits on
 *   Other       everything else, site level and with no SKU column
 *   <SKU>       one tab per repriced SKU: every page it appears on
 *
 * The SKU tabs are discovered from the data, not listed here, so a later
 * repricing needs no edit to this file.
 */
var PRICE_IMPACT = {
  // Fixed tabs, in reading order.
  fixed: [
    { view: 'sku_price_impact_summary', tab: 'Summary', order: 'direction.asc' },
    { view: 'sku_page_compare', tab: 'Product', order: 'sessions_today.desc.nullslast',
      filter: 'page_type=eq.Product&direction=neq.Unchanged&hidden=is.false' },
    { view: 'sku_page_compare', tab: 'Collection', order: 'sessions_today.desc.nullslast',
      filter: 'page_type=eq.Collection&direction=neq.Unchanged&hidden=is.false' },
    // No SKU column on purpose. Of 111 Shopify custom pages, ZERO name a
    // product or collection anywhere in their HTML -- they are built from
    // dynamic blocks, so nothing stored says what they merchandise. The
    // tab carries the traffic and the reason, rather than dropping both.
    { view: 'other_page_compare', tab: 'Other', order: 'sessions_today.desc.nullslast',
      allowEmpty: true }
  ],
  // The per-SKU tabs come from this: every SKU whose price actually moved.
  skuSource: {
    view: 'sku_page_compare',
    filter: 'direction=neq.Unchanged&hidden=is.false',
    order: 'master_sku.asc'
  },
  pageRows: 1000,
  writeIntervalMs: 1200,  // under the Sheets quota of 60 writes/minute
  statusTab: 'Status',
  lastWriteAt: 0
};

/** Rewrites every tab from the current view contents. */
function syncPriceImpact() {
  var cfg = priConfig_();
  var ss = SpreadsheetApp.openById(cfg.spreadsheetId);
  var summary = [];

  PRICE_IMPACT.fixed.forEach(function (spec) {
    var rows = priFetchAll_(cfg, spec);
    priWriteTab_(ss, spec.tab, rows);
    summary.push([spec.tab, rows.length]);
  });

  // One tab per repriced SKU. Every row is a page that SKU appears on,
  // so the reader sees its own product pages beside the collections it
  // shares with others.
  var skuRows = priFetchAll_(cfg, PRICE_IMPACT.skuSource);
  var bySku = {};
  skuRows.forEach(function (r) {
    (bySku[r.master_sku] = bySku[r.master_sku] || []).push(r);
  });
  Object.keys(bySku).sort().forEach(function (sku) {
    var rows = bySku[sku].sort(function (a, b) {
      return (b.sessions_today || 0) - (a.sessions_today || 0);
    });
    priWriteTab_(ss, sku, rows);
    summary.push([sku, rows.length]);
  });

  priRemoveStaleSkuTabs_(ss, Object.keys(bySku));
  priWriteStatus_(ss, summary);
}

function priConfig_() {
  var p = PropertiesService.getScriptProperties();
  var url = (p.getProperty('SUPABASE_URL') || '').trim().replace(/\/+$/, '');
  var key = (p.getProperty('SUPABASE_KEY') || '').trim();
  var spreadsheetId = (p.getProperty('SPREADSHEET_ID') || '').trim();
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url) || !key || !spreadsheetId) {
    throw new Error('Set SUPABASE_URL (https://PROJECT.supabase.co), SUPABASE_KEY and SPREADSHEET_ID in Script Properties.');
  }
  return { url: url, key: key, spreadsheetId: spreadsheetId };
}

/** Walk a view to exhaustion; PostgREST caps each response. */
function priFetchAll_(cfg, spec) {
  var all = [];
  var offset = 0;
  while (true) {
    var qs = ['select=*', 'order=' + encodeURIComponent(spec.order),
              'limit=' + PRICE_IMPACT.pageRows, 'offset=' + offset];
    if (spec.filter) qs.push(spec.filter);
    var res = UrlFetchApp.fetch(cfg.url + '/rest/v1/' + spec.view + '?' + qs.join('&'), {
      method: 'get',
      headers: { apikey: cfg.key, Authorization: 'Bearer ' + cfg.key },
      muteHttpExceptions: true
    });
    if (res.getResponseCode() !== 200) {
      throw new Error(spec.view + ' returned ' + res.getResponseCode() + ': ' +
                      res.getContentText().slice(0, 300));
    }
    var page = JSON.parse(res.getContentText());
    all = all.concat(page);
    if (page.length < PRICE_IMPACT.pageRows) break;
    offset += PRICE_IMPACT.pageRows;
  }
  // An empty result is a failure unless the caller allows it: the base
  // tables have row-level security, so a key without the right grants
  // returns 200 with zero rows -- indistinguishable from a genuinely
  // empty view. Refuse rather than publish blanks over a tab somebody is
  // about to read.
  if (!all.length && !spec.allowEmpty) {
    throw new Error(spec.view + ' returned no rows' +
      (spec.filter ? ' for ' + spec.filter : '') +
      '. Check SUPABASE_KEY can read it.');
  }
  return all;
}

/** Columns a per-SKU tab leads with. The SKU is the tab name, and the
 *  price is the same on every row, so neither earns a column; what the
 *  reader wants first is which page, how shared it is, and whether its
 *  add-to-cart rate moved. */
var SKU_TAB_COLUMNS = [
  'page_type', 'page_path', 'page_title', 'skus_on_page',
  'sessions_today', 'sessions_prev_day', 'sessions_prev_week', 'sessions_prev_month',
  'atc_rate_today', 'atc_rate_prev_day', 'atc_rate_prev_week', 'atc_rate_prev_month',
  'atc_delta_vs_prev_week', 'product_status', 'anchor_day'
];

function priWriteTab_(ss, tabName, rows) {
  var sheet = ss.getSheetByName(tabName) || ss.insertSheet(tabName);
  if (!rows.length) {
    sheet.clearContents();
    sheet.getRange(1, 1).setValue('No rows for this group.');
    return;
  }
  // A per-SKU tab uses the curated order; everything else keeps the
  // view's own columns.
  var headers = rows[0].hasOwnProperty('master_sku') && SKU_TAB_RE.test(tabName)
    ? SKU_TAB_COLUMNS.filter(function (h) { return rows[0].hasOwnProperty(h); })
    : Object.keys(rows[0]);

  var values = [headers];
  rows.forEach(function (r) {
    values.push(headers.map(function (h) {
      var v = r[h];
      return (v === null || v === undefined) ? '' : v;
    }));
  });

  priPace_();
  sheet.clearContents();
  sheet.getRange(1, 1, values.length, headers.length).setValues(values);
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
}

/** Keep the write rate under the Sheets per-user quota. */
function priPace_() {
  var wait = PRICE_IMPACT.writeIntervalMs - (Date.now() - PRICE_IMPACT.lastWriteAt);
  if (wait > 0) Utilities.sleep(wait);
  PRICE_IMPACT.lastWriteAt = Date.now();
}

/** The catalogue's master-SKU shape, the same pattern the pipeline
 *  validates against: SD/SM/SU plus one to four letters.
 *
 *  Deliberately NOT a loose /^[A-Z]+$/ -- this function DELETES what it
 *  matches, and a tab somebody named NOTES or TODO would match that.
 *  Anchored to the real prefixes, a hand-made tab cannot collide. */
var SKU_TAB_RE = /^(SD|SM|SU)[A-Z]{1,4}$/;

/** A SKU that is no longer repriced should not leave a tab behind
 *  showing numbers from a decision that has been reversed. */
function priRemoveStaleSkuTabs_(ss, currentSkus) {
  var keep = {};
  currentSkus.forEach(function (s) { keep[s] = true; });
  PRICE_IMPACT.fixed.forEach(function (f) { keep[f.tab] = true; });
  keep[PRICE_IMPACT.statusTab] = true;
  ss.getSheets().forEach(function (sheet) {
    var name = sheet.getName();
    if (!keep[name] && SKU_TAB_RE.test(name) && ss.getSheets().length > 1) {
      ss.deleteSheet(sheet);
    }
  });
}

function priWriteStatus_(ss, summary) {
  var sheet = ss.getSheetByName(PRICE_IMPACT.statusTab) ||
              ss.insertSheet(PRICE_IMPACT.statusTab);
  var notes = [
    ['Last sync', new Date()],
    ['Anchor day', 'the latest COMPLETE day. Today is partial until the nightly runs, ' +
                   'so comparing it against full days would show every SKU down ~80%.'],
    ['Headline metric', 'product-page add-to-cart rate (%)'],
    ['There is no conversion rate',
     'sessions_that_completed_checkout sees 4.5-8.8% of real orders because GoKwik owns ' +
     'the checkout. units_sold and revenue come from real orders instead.'],
    ['Collection pages are shared',
     'skus_on_page says how many SKUs sit on a collection. Its sessions are not one ' +
     'SKU\'s sessions - do not add a collection row to a product row.'],
    ['Why Other has no SKU column',
     'Of 111 Shopify custom pages, zero name a product or collection in their HTML. ' +
     'They are built from dynamic blocks, so no product-to-page link exists to report.'],
    ['Control group', 'the Unchanged SKUs in Summary moved too. If add-to-cart shifts ' +
                      'there as well, the shift is not about price.'],
    ['', ''],
    ['Tab', 'Rows']
  ];
  var all = notes.concat(summary);
  sheet.clearContents();
  sheet.getRange(1, 1, all.length, 2).setValues(all);
  sheet.setColumnWidth(1, 210);
  sheet.setColumnWidth(2, 660);
}

/** Refresh each morning, after the nightly has rebuilt the source tables. */
function setupPriceImpactTrigger() {
  removePriceImpactTrigger();
  ScriptApp.newTrigger('syncPriceImpact').timeBased().atHour(7).everyDays(1).create();
}

function removePriceImpactTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncPriceImpact') ScriptApp.deleteTrigger(t);
  });
}
