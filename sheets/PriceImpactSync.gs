/**
 * Price-change impact -> three Google Sheets tabs. See sheets/README.md.
 * Credentials stay in Script Properties: SUPABASE_URL, SUPABASE_KEY, SPREADSHEET_ID.
 * Public entry points: syncPriceImpact, setupPriceImpactTrigger, removePriceImpactTrigger.
 *
 * No resume state, unlike MetaDirectSync: the three views total about
 * 16,000 rows and finish inside one execution. The pagination is still
 * here because PostgREST caps a response regardless of how small the
 * view is.
 */
var PRICE_IMPACT = {
  views: [
    { view: 'sku_price_impact_compare', tab: 'Price Impact', order: 'sessions_today.desc.nullslast' },
    { view: 'sku_price_impact_daily',   tab: 'Daily',        order: 'day.desc,master_sku.asc',
      filter: 'day=gte.' + priDaysAgo_(60) },
    { view: 'sku_price_impact_pages',   tab: 'Pages',        order: 'sessions_7d.desc.nullslast' }
  ],
  pageRows: 1000,
  statusTab: 'Status'
};

function priDaysAgo_(n) {
  var d = new Date(Date.now() - n * 86400000);
  return d.toISOString().slice(0, 10);
}

/** Manual run. Rewrites all three tabs from the current view contents. */
function syncPriceImpact() {
  var cfg = priConfig_();
  var ss = SpreadsheetApp.openById(cfg.spreadsheetId);
  var summary = [];
  PRICE_IMPACT.views.forEach(function (spec) {
    var rows = priFetchAll_(cfg, spec);
    priWriteTab_(ss, spec.tab, rows);
    summary.push(spec.tab + ': ' + rows.length);
  });
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

/** Walk a view to exhaustion. PostgREST caps each response, so a view
 *  that fits in one logical read still arrives in pages. */
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
  // An empty view is a failure here, not a quiet "nothing to report":
  // the base tables have row-level security, so a key without the right
  // grants returns 200 with zero rows, which is indistinguishable from
  // a genuinely empty result. Refuse rather than publish blanks over a
  // tab somebody is about to read.
  if (!all.length) {
    throw new Error(spec.view + ' returned no rows. Check SUPABASE_KEY can read it.');
  }
  return all;
}

function priWriteTab_(ss, tabName, rows) {
  var sheet = ss.getSheetByName(tabName) || ss.insertSheet(tabName);
  var headers = Object.keys(rows[0]);
  var values = [headers];
  rows.forEach(function (r) {
    values.push(headers.map(function (h) {
      var v = r[h];
      return (v === null || v === undefined) ? '' : v;
    }));
  });
  sheet.clearContents();
  sheet.getRange(1, 1, values.length, headers.length).setValues(values);
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
}

function priWriteStatus_(ss, summary) {
  var sheet = ss.getSheetByName(PRICE_IMPACT.statusTab) ||
              ss.insertSheet(PRICE_IMPACT.statusTab);
  sheet.clearContents();
  sheet.getRange(1, 1, 5 + summary.length, 2).setValues([
    ['Last sync', new Date()],
    ['Anchor', 'latest COMPLETE day; today is partial until the nightly runs'],
    ['Headline metric', 'product-page add-to-cart rate (%)'],
    ['Not a conversion rate',
     'sessions_that_completed_checkout sees 4.5-8.8% of real orders (GoKwik checkout). ' +
     'units_sold / revenue come from real orders instead.'],
    ['Collection pages', 'shared across SKUs - see skus_on_page before reading as one SKU\'s traffic']
  ].concat(summary.map(function (s) { return [s.split(': ')[0] + ' rows', s.split(': ')[1]]; })));
  sheet.setColumnWidth(1, 180);
  sheet.setColumnWidth(2, 640);
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
