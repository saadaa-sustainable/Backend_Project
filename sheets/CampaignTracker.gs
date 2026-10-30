/**
 * Campaign Tracker: four named campaigns -> one Sheet tab, nightly.
 *
 * Reads meta_campaigns / meta_adsets / meta_ads straight over PostgREST
 * and aggregates in here. No database view, because only four campaigns
 * are wanted and their names are known: roughly 150 ad sets and 650 ads
 * come back in three requests.
 *
 * ---------------------------------------------------------------------
 * THIS NEEDS A SERVICE-ROLE KEY. Read this before wondering why the tab
 * is empty.
 *
 * meta_campaigns, meta_adsets and meta_ads all have ROW LEVEL SECURITY
 * enabled and NO policies. `anon` and `authenticated` hold the SELECT
 * grant, so PostgREST answers 200 with an empty array rather than an
 * error -- which looks exactly like "these campaigns have no ads".
 *
 * A service_role / `sb_secret_` key bypasses RLS and returns rows. The
 * six views MetaDirectSync reads do not need one because RLS is off on
 * those materialized views; these base tables are not the same thing.
 *
 * If you would rather not put a service-role key in a spreadsheet, the
 * alternative is a materialized view with RLS off, which is what the
 * other tabs use.
 *
 * The code below REFUSES to write a tab when the campaign lookup comes
 * back empty, so this failure announces itself instead of publishing
 * zeros.
 * ---------------------------------------------------------------------
 *
 * SETUP, in the destination spreadsheet:
 *   1. Extensions -> Apps Script, add this file.
 *   2. Script Properties: SUPABASE_URL, SUPABASE_KEY (service role),
 *      SPREADSHEET_ID, CAMPAIGN_SYNC_HOUR_IST (0-23).
 *   3. Run `syncCampaignTracker` once and approve the scopes.
 *   4. Run `setupCampaignTrackerTrigger` to install the nightly run.
 */

var CAMPAIGN_TRACKER = {
  tab: 'Campaign Tracker',
  dailyHandler: 'syncCampaignTracker',
  hourProperty: 'CAMPAIGN_SYNC_HOUR_IST',
  pageSize: 1000,

  /** Edit this list to track different campaigns. Exact names. */
  campaigns: [
    'NCP_MW-Kurta_WC-Scale_7C_CBO_EX-P(90)',
    'NCP_CBO_SMCP_EX-P(30)_1C_Oct-2025',
    'NCP+Kurta+Scale+WC+7C+29082026',
    'NCP+NCA+SCALE-WC-ULTD+HV+7C1E+CBO+3/08/26'
  ],

  // Three tabs from the SAME three requests. The ad set and ad rows are
  // already in memory for the summary counts, so listing them costs
  // nothing extra at the API.
  summaryTab: 'Campaign Tracker',
  adsetTab: 'Ad Sets',
  adTab: 'Ads',

  header: [
    'Campaign', 'Status', 'Account',
    'Ad sets running', 'Ad sets total',
    'Ads running', 'Ads total',
    'Latest ad created', 'Days since new ad'
  ],
  adsetHeader: [
    'Campaign', 'Ad set', 'Status', 'Ads in ad set', 'Ads running',
    'Created', 'Ad set ID'
  ],
  adHeader: [
    'Campaign', 'Ad set', 'Ad', 'Status', 'Created', 'Ad ID'
  ]
};

function ctProperties_() { return PropertiesService.getScriptProperties(); }

function ctConfig_() {
  var p = ctProperties_();
  var url = (p.getProperty('SUPABASE_URL') || '').trim().replace(/\/+$/, '');
  var key = (p.getProperty('SUPABASE_KEY') || '').trim();
  var spreadsheetId = (p.getProperty('SPREADSHEET_ID') || '').trim();
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url) || !key || !spreadsheetId) {
    throw new Error('Set SUPABASE_URL (https://PROJECT.supabase.co), SUPABASE_KEY and SPREADSHEET_ID in Script Properties.');
  }
  return { url: url, key: key, spreadsheetId: spreadsheetId };
}

/** One PostgREST GET, paged. `path` is everything after /rest/v1/. */
function ctGet_(cfg, path) {
  var headers = { apikey: cfg.key, Accept: 'application/json', 'Accept-Profile': 'public' };
  if (cfg.key.indexOf('sb_secret_') !== 0) headers.Authorization = 'Bearer ' + cfg.key;

  var rows = [], offset = 0;
  for (var guard = 0; guard < 50; guard++) {
    headers.Range = offset + '-' + (offset + CAMPAIGN_TRACKER.pageSize - 1);
    var res = UrlFetchApp.fetch(cfg.url + '/rest/v1/' + path, {
      method: 'get', headers: headers, muteHttpExceptions: true, followRedirects: false
    });
    var code = res.getResponseCode();
    if (code !== 200 && code !== 206) {
      throw new Error('Supabase returned ' + code + ' for ' + path + '. ' +
                      res.getContentText().slice(0, 300));
    }
    var page = JSON.parse(res.getContentText());
    rows = rows.concat(page);
    if (page.length < CAMPAIGN_TRACKER.pageSize) return rows;
    offset += CAMPAIGN_TRACKER.pageSize;
  }
  throw new Error('Stopped after 50 pages reading ' + path + '.');
}

/**
 * A PostgREST `in.(...)` list.
 *
 * encodeURIComponent is not optional here. Three of the four campaign
 * names contain '+', and a raw '+' in a query string decodes to a SPACE
 * -- the filter would then match nothing and the tab would come back
 * empty with no error at all. Each value is also double-quoted because
 * the names carry '(', ')', '/', '<' and '>'.
 */
function ctInList_(values) {
  return 'in.(' + values.map(function (v) {
    return encodeURIComponent('"' + String(v).replace(/"/g, '""') + '"');
  }).join(',') + ')';
}

function syncCampaignTracker() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) throw new Error('A Campaign Tracker sync is already running.');
  try {
    var cfg = ctConfig_();
    var tz = 'Asia/Kolkata';
    var wanted = CAMPAIGN_TRACKER.campaigns;

    // 1. The campaigns themselves.
    var campaigns = ctGet_(cfg,
      'meta_campaigns?select=campaign_id,campaign_name,campaign_effective_status,account_name' +
      '&campaign_name=' + ctInList_(wanted));

    if (!campaigns.length) {
      throw new Error(
        'No campaigns came back. The most likely cause is the key: ' +
        'meta_campaigns has RLS enabled with no policies, so anon and ' +
        'authenticated keys read zero rows and PostgREST still answers 200. ' +
        'Use a service_role key, or switch this tab to a materialized view. ' +
        'The other possibility is a renamed campaign -- check the names in ' +
        'CAMPAIGN_TRACKER.campaigns against Ads Manager.');
    }

    var ids = campaigns.map(function (c) { return c.campaign_id; });

    // 2. Ad sets and ads for exactly those campaigns.
    var adsets = ctGet_(cfg,
      'meta_adsets?select=campaign_id,adset_id,adset_name,adset_effective_status,created_time' +
      '&campaign_id=' + ctInList_(ids) + '&order=created_time.desc');
    // meta_ads already carries adset_name and campaign_name, so the Ads
    // tab needs no join and no second lookup.
    var ads = ctGet_(cfg,
      'meta_ads?select=campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,' +
      'ad_effective_status,created_time' +
      '&campaign_id=' + ctInList_(ids) + '&order=created_time.desc');

    // 3. Aggregate per campaign.
    var byId = {};
    campaigns.forEach(function (c) {
      byId[c.campaign_id] = {
        name: c.campaign_name,
        status: c.campaign_effective_status,
        account: c.account_name,
        adsetsRunning: 0, adsetsTotal: 0,
        adsRunning: 0, adsTotal: 0,
        newestAd: null
      };
    });
    adsets.forEach(function (s) {
      var r = byId[s.campaign_id];
      if (!r) return;
      r.adsetsTotal++;
      if (s.adset_effective_status === 'ACTIVE') r.adsetsRunning++;
    });
    ads.forEach(function (a) {
      var r = byId[a.campaign_id];
      if (!r) return;
      r.adsTotal++;
      if (a.ad_effective_status === 'ACTIVE') r.adsRunning++;
      if (a.created_time && (!r.newestAd || a.created_time > r.newestAd)) r.newestAd = a.created_time;
    });

    // 4. Rows, in the order the names are listed above, so the tab does
    //    not reshuffle when a count changes.
    var todayKey = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
    var body = wanted.map(function (name) {
      var r = null;
      for (var id in byId) { if (byId[id].name === name) { r = byId[id]; break; } }
      if (!r) return [name, 'NOT FOUND', '', '', '', '', '', '', ''];
      var newest = r.newestAd
        ? Utilities.formatDate(new Date(r.newestAd), tz, 'yyyy-MM-dd') : '';
      var days = newest
        ? Math.round((new Date(todayKey) - new Date(newest)) / 86400000) : '';
      return [r.name, r.status, r.account,
              r.adsetsRunning, r.adsetsTotal,
              r.adsRunning, r.adsTotal,
              newest, days];
    });

    var ss = SpreadsheetApp.openById(cfg.spreadsheetId);
    var stamp = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm') + ' IST';

    ctWriteTab_(ss, CAMPAIGN_TRACKER.summaryTab, CAMPAIGN_TRACKER.header, body,
      'Synced ' + stamp + ' \u00b7 ' + adsets.length + ' ad sets, ' + ads.length + ' ads read');

    // --- Ad Sets tab -------------------------------------------------
    // Ad counts per ad set come from the `ads` rows already fetched, so
    // an ad set with no ads still shows as 0 rather than going missing.
    var adsBySet = {}, runningBySet = {};
    ads.forEach(function (a) {
      adsBySet[a.adset_id] = (adsBySet[a.adset_id] || 0) + 1;
      if (a.ad_effective_status === 'ACTIVE') {
        runningBySet[a.adset_id] = (runningBySet[a.adset_id] || 0) + 1;
      }
    });
    var adsetRows = adsets.map(function (s2) {
      var c = byId[s2.campaign_id];
      return [
        c ? c.name : s2.campaign_id,
        s2.adset_name,
        s2.adset_effective_status,
        adsBySet[s2.adset_id] || 0,
        runningBySet[s2.adset_id] || 0,
        s2.created_time ? Utilities.formatDate(new Date(s2.created_time), tz, 'yyyy-MM-dd') : '',
        s2.adset_id
      ];
    });
    ctWriteTab_(ss, CAMPAIGN_TRACKER.adsetTab, CAMPAIGN_TRACKER.adsetHeader, adsetRows,
      'Synced ' + stamp + ' \u00b7 ' + adsetRows.length + ' ad sets, newest first');

    // --- Ads tab -----------------------------------------------------
    var adRows = ads.map(function (a) {
      return [
        a.campaign_name,
        a.adset_name,
        a.ad_name,
        a.ad_effective_status,
        a.created_time ? Utilities.formatDate(new Date(a.created_time), tz, 'yyyy-MM-dd') : '',
        a.ad_id
      ];
    });
    ctWriteTab_(ss, CAMPAIGN_TRACKER.adTab, CAMPAIGN_TRACKER.adHeader, adRows,
      'Synced ' + stamp + ' \u00b7 ' + adRows.length + ' ads, newest first');

    Logger.log('Campaign Tracker: ' + body.length + ' campaigns, ' +
               adsetRows.length + ' ad sets, ' + adRows.length + ' ads across three tabs.');
    return { campaigns: body.length, adsets: adsetRows.length, ads: adRows.length };
  } finally {
    lock.releaseLock();
  }
}

/** Clear and rewrite one tab in a single setValues. */
function ctWriteTab_(ss, name, header, body, note) {
  var sheet = ss.getSheetByName(name) || ss.insertSheet(name);
  sheet.clear();
  var block = [header].concat(body.length ? body : [header.map(function () { return ''; })]);
  sheet.getRange(1, 1, block.length, header.length).setValues(block);
  sheet.getRange(1, 1, 1, header.length).setFontWeight('bold');
  sheet.setFrozenRows(1);
  if (note) sheet.getRange(1, 1).setNote(note);
  sheet.autoResizeColumns(1, header.length);
}

function ctDeleteTriggers_() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === CAMPAIGN_TRACKER.dailyHandler) ScriptApp.deleteTrigger(t);
  });
}

/**
 * Nightly, in IST. Schedule it AFTER the backend refreshes the entity
 * tables -- the backend nightly starts 07:00 IST, so use 9 or later.
 * Earlier and the sheet copies yesterday's numbers with nothing to show
 * for it.
 */
function setupCampaignTrackerTrigger() {
  ctConfig_();
  var hour = ctProperties_().getProperty(CAMPAIGN_TRACKER.hourProperty);
  if (hour === null || !/^\d{1,2}$/.test(hour) || Number(hour) > 23) {
    throw new Error('Set ' + CAMPAIGN_TRACKER.hourProperty + ' (0-23) to an hour AFTER the ' +
                    'backend refresh. It starts at 07:00 IST, so 9 or later.');
  }
  ctDeleteTriggers_();
  ScriptApp.newTrigger(CAMPAIGN_TRACKER.dailyHandler)
    .timeBased().atHour(Number(hour)).everyDays(1).inTimezone('Asia/Kolkata').create();
  Logger.log('Campaign Tracker daily sync installed in the ' + hour + ':00-' + hour + ':59 IST window.');
}

function removeCampaignTrackerTrigger() { ctDeleteTriggers_(); }

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Campaign Tracker')
    .addItem('Sync now', CAMPAIGN_TRACKER.dailyHandler)
    .addItem('Install nightly sync', 'setupCampaignTrackerTrigger')
    .addItem('Remove nightly sync', 'removeCampaignTrackerTrigger')
    .addToUi();
}
