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
/** The four dates the columns cover, filled in as the first tab is
 *  written and reported on Status. Derived from the data's own anchor,
 *  so it cannot disagree with the headers. */
var priCoverage_ = '(not yet determined)';

var PRICE_IMPACT = {
  // Fixed tabs, in reading order.
  fixed: [
    { view: 'sku_price_impact_summary', tab: 'Summary', order: 'direction.asc' },
    { view: 'sku_page_compare', tab: 'Product', grouped: true,
      order: 'master_sku.asc,sessions_today.desc.nullslast',
      filter: 'page_type=eq.Product&direction=neq.Unchanged&hidden=is.false' },
    { view: 'sku_page_compare', tab: 'Collection', grouped: true,
      order: 'master_sku.asc,sessions_today.desc.nullslast',
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
    if (spec.grouped) priWriteGroupedTab_(ss, spec.tab, rows);
    else priWriteTab_(ss, spec.tab, rows);
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
  'atc_delta_vs_prev_week',
  // Revenue of the orders whose converting session landed on this page,
  // from real orders rather than the landing-page table's own count.
  'revenue_today', 'revenue_prev_day', 'revenue_prev_week', 'revenue_prev_month',
  'orders_today', 'orders_prev_week',
  'revenue_per_1k_today', 'revenue_per_1k_prev_week',
  'product_status', 'anchor_day'
];

function priWriteTab_(ss, tabName, rows) {
  var sheet = ss.getSheetByName(tabName) || ss.insertSheet(tabName);
  if (!rows.length) {
    sheet.clear();  // clear() not clearContents(): formats must go too
    sheet.getRange(1, 1).setValue('No rows for this group.');
    return;
  }
  // A per-SKU tab uses the curated order; everything else keeps the
  // view's own columns.
  // `keys` addresses the data; `headers` is what the reader sees. They
  // stop being the same list once the slot names carry their dates.
  var keys = rows[0].hasOwnProperty('master_sku') && SKU_TAB_RE.test(tabName)
    ? SKU_TAB_COLUMNS.filter(function (h) { return rows[0].hasOwnProperty(h); })
    : Object.keys(rows[0]);
  var headers = priDateHeaders_(keys, rows);

  var values = [headers];
  rows.forEach(function (r) {
    values.push(keys.map(function (h) {
      var v = r[h];
      return (v === null || v === undefined) ? '' : v;
    }));
  });

  priPace_();
  sheet.clear();  // clear() not clearContents(): formats must go too
  sheet.getRange(1, 1, values.length, headers.length).setValues(values);
  priApplyFormats_(sheet, keys, values.length);
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
}

/** Columns on a grouped tab. The SKU block header carries the identity
 *  and the block's totals; the page rows beneath carry only what varies
 *  between them. */
var GROUP_SKU_COLUMNS = ['master_sku', 'direction', 'old_price', 'new_price', 'price_change'];
var GROUP_PAGE_COLUMNS = [
  'page_type', 'page_path', 'page_title', 'skus_on_page',
  'sessions_today', 'sessions_prev_day', 'sessions_prev_week', 'sessions_prev_month',
  'atc_rate_today', 'atc_rate_prev_day', 'atc_rate_prev_week', 'atc_rate_prev_month',
  'atc_delta_vs_prev_week',
  'revenue_today', 'revenue_prev_day', 'revenue_prev_week', 'revenue_prev_month',
  'orders_today', 'orders_prev_week'
];

/** One header row per SKU, then its pages beneath it.
 *
 *  The flat version repeated the SKU, its direction and both prices on
 *  every row and ordered the whole tab by sessions, so one SKU's five
 *  pages landed on rows 58, 84, 101, 136 and 223 with the same five
 *  values restated each time. Grouping puts a SKU's pages together and
 *  states what they share exactly once.
 *
 *  The header's totals are summed over the pages listed beneath it and
 *  nothing else. On the Collection tab that is a SHARED figure -- those
 *  pages sell other SKUs too -- which is why the rate is labelled as
 *  the block's own and `skus_on_page` stays on every row. */
function priWriteGroupedTab_(ss, tabName, rows) {
  var sheet = ss.getSheetByName(tabName) || ss.insertSheet(tabName);
  if (!rows.length) {
    sheet.clear();  // clear() not clearContents(): formats must go too
    sheet.getRange(1, 1).setValue('No rows for this group.');
    return;
  }

  var groups = [];
  var index = {};
  rows.forEach(function (r) {
    if (!(r.master_sku in index)) {
      index[r.master_sku] = groups.length;
      groups.push({ sku: r.master_sku, head: r, pages: [] });
    }
    groups[index[r.master_sku]].pages.push(r);
  });

  // Biggest SKU first, by the traffic of the pages in its own block.
  groups.forEach(function (g) {
    g.sessions = g.pages.reduce(function (t, r) { return t + (r.sessions_today || 0); }, 0);
  });
  groups.sort(function (a, b) { return b.sessions - a.sessions; });

  var keys = GROUP_SKU_COLUMNS.concat(GROUP_PAGE_COLUMNS);
  var headers = priDateHeaders_(keys, rows);
  var values = [headers];
  var headerRows = [];

  groups.forEach(function (g) {
    headerRows.push(values.length + 1);
    values.push(
      [g.sku, g.head.direction, g.head.old_price, g.head.new_price, g.head.price_change]
        .concat(priBlockTotals_(g.pages, tabName)));

    g.pages.forEach(function (r) {
      values.push(['', '', '', '', ''].concat(GROUP_PAGE_COLUMNS.map(function (h) {
        var v = r[h];
        return (v === null || v === undefined) ? '' : v;
      })));
    });
  });

  priPace_();
  sheet.clear();  // clear() not clearContents(): formats must go too
  sheet.getRange(1, 1, values.length, headers.length).setValues(values);
  priApplyFormats_(sheet, keys, values.length);
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  // Bold each SKU header so the blocks are findable while scrolling.
  headerRows.forEach(function (row) {
    sheet.getRange(row, 1, 1, headers.length).setFontWeight('bold');
  });
}

/** The block header's cells, derived from GROUP_PAGE_COLUMNS rather
 *  than hand-listed.
 *
 *  Hand-listing is what broke it: the first version spelt out
 *  `sessions, '', prevWeek, ''` and so filled only today and prev_week,
 *  leaving sessions_prev_day, sessions_prev_month, atc_rate_prev_day
 *  and atc_rate_prev_month permanently blank on every header row.
 *  Deriving each cell from the column name means a column added to
 *  GROUP_PAGE_COLUMNS is totalled automatically instead of silently
 *  arriving empty.
 *
 *  Each kind of column gets the aggregate it deserves: counts and money
 *  are summed, a rate is re-derived from its own slot's sessions, and
 *  the delta is recomputed from the two weighted rates rather than
 *  summed. */
function priBlockTotals_(pages, tabName) {
  return GROUP_PAGE_COLUMNS.map(function (h) {
    if (h === 'page_type') return pages.length + ' pages';
    if (h === 'page_path') {
      // Spelt out per tab, because the two totals do not mean the same
      // thing. Product pages belong to this SKU; collection pages are
      // shared with every other SKU on them, so the block total is not
      // this SKU's traffic or revenue and must not be read as if it were.
      return tabName === 'Collection'
        ? 'ALL COLLECTIONS - SHARED TRAFFIC AND REVENUE, NOT THIS SKU ALONE'
        : 'ALL PRODUCT PAGES FOR THIS SKU';
    }
    if (/^sessions_|^revenue_|^orders_/.test(h)) return priSum_(pages, h);
    if (/^atc_rate_/.test(h)) {
      return priBlendedAtc_(pages, h.replace('atc_rate_', 'sessions_'), h);
    }
    if (h === 'atc_delta_vs_prev_week') {
      var now = priBlendedAtc_(pages, 'sessions_today', 'atc_rate_today');
      var wk = priBlendedAtc_(pages, 'sessions_prev_week', 'atc_rate_prev_week');
      return (now === '' || wk === '') ? '' : Math.round((now - wk) * 1000) / 1000;
    }
    return '';  // page_title, skus_on_page: nothing to total
  });
}

/** Total of one numeric column across a block, blank when the block
 *  has none of it at all -- a zero would claim the pages were measured
 *  and returned nothing. */
function priSum_(pages, key) {
  var any = false, total = 0;
  pages.forEach(function (r) {
    if (r[key] !== null && r[key] !== undefined && r[key] !== '') {
      any = true; total += Number(r[key]);
    }
  });
  return any ? Math.round(total * 100) / 100 : '';
}

/** Sessions-weighted add-to-cart rate across a block's pages.
 *  Weighted, never an average of the rates: a page with 66 sessions
 *  would otherwise weigh as much as one with 6,787. */
function priBlendedAtc_(pages, sessionKey, rateKey) {
  var sess = 0, adds = 0;
  pages.forEach(function (r) {
    var s = r[sessionKey], rate = r[rateKey];
    if (s && rate !== null && rate !== undefined) { sess += s; adds += s * rate / 100; }
  });
  return sess ? Math.round(adds / sess * 100 * 1000) / 1000 : '';
}

/** Rewrite slot names into the dates they actually mean.
 *
 *  `sessions_prev_month` tells a reader nothing about which day it is,
 *  and the answer moves every morning as the anchor rolls forward.
 *  Headers therefore carry the date itself -- `sessions 27 Sep (Sun)`
 *  -- so a tab copied into a deck or mailed on is still legible a week
 *  later, when "prev_month" would mean a different day.
 *
 *  The anchor comes from the rows themselves, never from the script's
 *  clock: the sheet is written from whatever day the pipeline last
 *  completed, which is not always yesterday. */
function priDateHeaders_(headers, rows) {
  var anchor = null;
  for (var i = 0; i < rows.length && !anchor; i++) {
    if (rows[i].anchor_day) anchor = rows[i].anchor_day;
  }
  if (!anchor) return headers.slice();

  var d = new Date(anchor + 'T00:00:00Z');
  function shift(days, months) {
    var x = new Date(d.getTime());
    if (months) x.setUTCMonth(x.getUTCMonth() - months);
    if (days) x.setUTCDate(x.getUTCDate() - days);
    return Utilities.formatDate(x, 'UTC', 'dd MMM (EEE)');
  }
  var label = {
    today: shift(0, 0), prev_day: shift(1, 0),
    prev_week: shift(7, 0), prev_month: shift(0, 1)
  };
  // Stashed for the Status tab, which otherwise would have to re-derive
  // the anchor and could disagree with the headers it is describing.
  priCoverage_ = 'anchor ' + label.today + '  ·  vs ' + label.prev_day +
                 '  ·  vs ' + label.prev_week + '  ·  vs ' + label.prev_month;

  return headers.map(function (h) {
    // The delta is checked FIRST: it ends in `_prev_week` and would
    // otherwise be caught by the generic rule below and come out as
    // "atc delta vs · 20 Oct", with a separator where a word belongs.
    if (h === 'atc_delta_vs_prev_week') return 'atc delta vs ' + label.prev_week;
    var m = h.match(/^(.*)_(today|prev_day|prev_week|prev_month)$/);
    if (m) return m[1].replace(/_/g, ' ') + ' · ' + label[m[2]];
    if (h === 'anchor_day') return 'anchor day';
    return h.replace(/_/g, ' ');
  });
}

/** Number format per column, applied explicitly on every write.
 *
 *  clearContents() clears VALUES and leaves formats behind, so when the
 *  column layout changed a revenue figure landed in a cell still
 *  carrying a date format from the previous run: 4132 rendered as
 *  1911-04-24, which is exactly 4,132 days after the Sheets epoch.
 *  clear() fixes the inherited case; setting formats explicitly means a
 *  tab no longer depends on whatever it happened to hold before. */
function priNumberFormat_(header) {
  if (/^anchor_day$|_date$/.test(header)) return 'yyyy-mm-dd';
  if (/^revenue/.test(header)) return '#,##0.00';
  if (/_rate_|^atc_delta|_per_1k/.test(header)) return '0.000';
  if (/^sessions|^orders|^units|skus_on_page|^old_price$|^new_price$|^price_change$/.test(header)) {
    return '#,##0';
  }
  return '@';  // text, so a SKU code or a path is never guessed at
}

/** Apply formats column by column, over the data rows only.
 *  Keyed on the ORIGINAL column names, never the date-labelled ones. */
function priApplyFormats_(sheet, keys, rowCount) {
  if (rowCount < 2) return;
  keys.forEach(function (h, i) {
    sheet.getRange(2, i + 1, rowCount - 1, 1).setNumberFormat(priNumberFormat_(h));
  });
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
    ['Columns cover', priCoverage_],
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
  sheet.clear();  // clear() not clearContents(): formats must go too
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
