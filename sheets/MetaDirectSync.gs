/**
 * Pulls the meta_direct_* snapshots from Supabase into this sheet and
 * keeps them current on a nightly trigger.
 *
 * SETUP (once)
 *   1. Extensions > Apps Script, paste this file.
 *   2. Project Settings > Script Properties, add:
 *        SUPABASE_URL  https://gtcdyfmlvglzpiwzklhx.supabase.co
 *        SUPABASE_KEY  <the service_role key from Supabase >
 *                      Settings > API > service_role>
 *      Script Properties, NOT a constant in the code: anyone with edit
 *      access to the sheet can read the code, and the service_role key
 *      bypasses row-level security on the whole project.
 *   3. Project Settings > set the timezone to Asia/Kolkata.
 *   4. Run setupNightlyTrigger() once, and authorise when prompted.
 *
 * WHY service_role AND NOT anon
 *   anon was deliberately revoked on these views. That key ships in
 *   client-side code, and the views carry full spend and revenue per
 *   ad. Apps Script runs on Google's servers, so a key held here never
 *   reaches whoever opens the sheet -- but it DOES reach anyone who can
 *   open the script editor. Share the sheet as Viewer, not Editor.
 */

// Which snapshots to pull, and the key each is sorted by.
//
// A stable sort is not decoration: PostgREST paginates with
// limit/offset, and without an ORDER BY the server may return rows in a
// different order between pages, which silently duplicates some rows
// and drops others.
//
// daily_90d is the big one: 100,816 rows x 36 columns = 3.6M cells
// over ~101 API pages. It is enabled because _syncView streams each
// page straight to the sheet instead of accumulating every row first,
// so memory stays flat and the time is roughly linear.
//
// Two ceilings still apply. Apps Script caps a single execution at 6
// minutes on a consumer Google account and 30 on Workspace, and a
// spreadsheet holds 10M cells -- all four tabs come to about 5.2M. If
// this run starts timing out, set enabled:false here rather than
// letting it fail every night.
var VIEWS = [
  { view: 'meta_direct_active_30d', tab: 'Active 30d', order: 'ad_id',      enabled: true  },
  { view: 'meta_direct_active_90d', tab: 'Active 90d', order: 'ad_id',      enabled: true  },
  { view: 'meta_direct_daily_30d',  tab: 'Daily 30d',  order: 'date,ad_id', enabled: true  },
  { view: 'meta_direct_daily_90d',  tab: 'Daily 90d',  order: 'date,ad_id', enabled: true  }
];

var PAGE = 1000;          // PostgREST's own maximum per request
var WRITE_CHUNK = 5000;   // rows per setValues call

function _cfg() {
  var p = PropertiesService.getScriptProperties();
  var url = p.getProperty('SUPABASE_URL');
  var key = p.getProperty('SUPABASE_KEY');
  if (!url || !key) {
    throw new Error('Set SUPABASE_URL and SUPABASE_KEY in Project Settings > Script Properties.');
  }
  return { url: url.replace(/\/+$/, ''), key: key };
}

/** One page of a view. Returns an array of plain objects. */
function _fetchPage(cfg, view, order, offset) {
  var u = cfg.url + '/rest/v1/' + view +
          '?select=*&order=' + encodeURIComponent(order) +
          '&limit=' + PAGE + '&offset=' + offset;
  var res = UrlFetchApp.fetch(u, {
    method: 'get',
    muteHttpExceptions: true,
    headers: { apikey: cfg.key, Authorization: 'Bearer ' + cfg.key }
  });
  var code = res.getResponseCode();
  if (code !== 200 && code !== 206) {
    // The body carries PostgREST's reason; the key is never in it.
    throw new Error(view + ' HTTP ' + code + ' - ' + res.getContentText().slice(0, 300));
  }
  return JSON.parse(res.getContentText());
}

/** Make sure the sheet is physically big enough to be written to.
 *
 *  A new sheet is 1000 rows x 26 columns and clear() does not change
 *  that, so getRange() past those bounds throws "The coordinates or
 *  dimensions of the range are invalid". Daily 30d is 41,807 rows x 36
 *  columns, so every daily view needs this before its first write.
 */
function _ensureSize(sh, rows, cols) {
  var needRows = rows + 1;                       // +1 for the header
  if (sh.getMaxRows() < needRows) {
    sh.insertRowsAfter(sh.getMaxRows(), needRows - sh.getMaxRows());
  }
  if (sh.getMaxColumns() < cols) {
    sh.insertColumnsAfter(sh.getMaxColumns(), cols - sh.getMaxColumns());
  }
}

/** Replace one tab with the full contents of one view.
 *
 *  Each page is written as it arrives rather than accumulated and
 *  written at the end. Holding 100k objects in memory and then
 *  rows.concat(page) per page -- which reallocates the whole array
 *  every time -- is what made the 90-day view unsafe to enable.
 *  Streaming keeps memory flat and the wall time roughly linear.
 */
function _syncView(cfg, spec) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(spec.tab) || ss.insertSheet(spec.tab);
  sh.clear();

  var headers = null;
  var written = 0;

  for (var offset = 0; ; offset += PAGE) {
    var page = _fetchPage(cfg, spec.view, spec.order, offset);

    if (page.length) {
      if (!headers) {
        headers = Object.keys(page[0]);
        _ensureSize(sh, PAGE, headers.length);
        sh.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
        sh.setFrozenRows(1);
      }
      // Grow before the write, not after: the range has to exist first.
      _ensureSize(sh, written + page.length, headers.length);
      var values = page.map(function (r) {
        return headers.map(function (h) { return r[h] === null ? '' : r[h]; });
      });
      sh.getRange(written + 2, 1, values.length, headers.length).setValues(values);
      written += values.length;
    }

    if (page.length < PAGE) break;       // short page means the last one
    if (offset > 500000) throw new Error(spec.view + ': runaway pagination');
  }

  if (!written) {
    sh.getRange(1, 1).setValue('No rows returned for ' + spec.view);
  } else {
    // Trim the empty tail a previous, larger run may have left behind.
    var extra = sh.getMaxRows() - (written + 1);
    if (extra > 0) sh.deleteRows(written + 2, extra);
  }
  return written;
}

/** The entry point. This is what the nightly trigger calls. */
function syncMetaDirect() {
  var cfg = _cfg();
  var started = new Date();
  var log = [];

  // The newest day the underlying data covers. Written to the status
  // tab so a stale night is visible in the sheet instead of looking
  // like a quiet day of trading.
  var through = '';
  try {
    var t = _fetchPage(cfg, 'meta_direct_data_through', 'data_through', 0);
    through = (t[0] && t[0].data_through) || '';
  } catch (e) {
    log.push(['meta_direct_data_through', 'FAILED', String(e).slice(0, 200)]);
  }

  VIEWS.forEach(function (spec) {
    if (!spec.enabled) { log.push([spec.view, 'skipped', 'disabled in VIEWS']); return; }
    try {
      var n = _syncView(cfg, spec);
      log.push([spec.view, 'ok', n + ' rows']);
    } catch (e) {
      // One view failing must not cost the others.
      log.push([spec.view, 'FAILED', String(e).slice(0, 200)]);
    }
  });

  _writeStatus(started, through, log);
}

function _writeStatus(started, through, log) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName('Status') || ss.insertSheet('Status');
  sh.clear();
  var tz = Session.getScriptTimeZone();
  var rows = [
    ['Last refreshed', Utilities.formatDate(started, tz, 'yyyy-MM-dd HH:mm:ss')],
    ['Data through', through || '(unknown)'],
    ['Seconds taken', Math.round((new Date() - started) / 1000)],
    ['', ''],
    ['View', 'Status', 'Detail']
  ];
  sh.getRange(1, 1, rows.length, 3).setValues(rows.map(function (r) {
    return [r[0], r[1], r[2] === undefined ? '' : r[2]];
  }));
  if (log.length) sh.getRange(rows.length + 1, 1, log.length, 3).setValues(log);
  sh.getRange(5, 1, 1, 3).setFontWeight('bold');
  sh.autoResizeColumns(1, 3);
}

/**
 * Nightly trigger, 07:00 in the script's timezone.
 *
 * The backend cron starts about 01:39 and has been finishing around
 * 05:24, and the snapshot refresh is its LAST step. 07:00 leaves
 * roughly 90 minutes of headroom; if that pipeline starts running
 * longer, move this later rather than letting the sheet pull a
 * half-refreshed snapshot.
 *
 * Safe to run more than once -- it clears its own triggers first.
 */
function setupNightlyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncMetaDirect') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncMetaDirect').timeBased().atHour(7).everyDays(1).create();
  Logger.log('Nightly trigger set for 07:00 ' + Session.getScriptTimeZone());
}

function removeNightlyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncMetaDirect') ScriptApp.deleteTrigger(t);
  });
}
