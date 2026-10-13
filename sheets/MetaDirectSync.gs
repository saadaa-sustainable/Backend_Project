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
// ownRun: this view is synced by its OWN trigger, in its OWN execution,
// instead of sharing the 6-minute budget with the other three.
//
// Measured 2026-10-13, actual row counts:
//
//     meta_direct_active_30d     1,569 rows =  2 pages
//     meta_direct_active_90d     1,583 rows =  2 pages
//     meta_direct_daily_30d     26,113 rows = 27 pages
//     meta_direct_daily_90d     65,810 rows = 66 pages
//     ----------------------------------------------------
//     one execution            95,075 rows = 96 sequential requests
//
// PAGE cannot be raised to cut that down: Supabase pins PostgREST's
// db-max-rows at 1000, so limit=20000 still returns 1000 rows --
// verified live against this project.
//
// daily_90d was LAST in this list and is two thirds of the work, so it
// ran on whatever time the other three left it and was cut off partway.
// And because it is ordered by date ASCENDING, being cut off means
// keeping the OLDEST rows: the tab filled from 2026-07-15 forward and
// never reached the current day, which is exactly how the failure was
// reported -- "not fetching up to 12 Oct".
//
// Its own execution gets its own 6-minute budget (30 on Workspace),
// which 66 pages fits inside comfortably; sharing one did not.
var VIEWS = [
  { view: 'meta_direct_active_30d', tab: 'Active 30d', order: 'ad_id',      enabled: true  },
  { view: 'meta_direct_active_90d', tab: 'Active 90d', order: 'ad_id',      enabled: true  },
  { view: 'meta_direct_daily_30d',  tab: 'Daily 30d',  order: 'date,ad_id', enabled: true  },
  { view: 'meta_direct_daily_90d',  tab: 'Daily 90d',  order: 'date,ad_id', enabled: true,
    ownRun: true }
];

var PAGE = 1000;          // PostgREST's own maximum per request
var WRITE_CHUNK = 20000;  // rows per Sheets API write

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

/** Resize a tab's grid in ONE call, before any data is written.
 *
 *  The old code grew the sheet with insertRowsAfter() once per 1,000-row
 *  page. For the 90-day view that is 63 structural row insertions on a
 *  grid on its way to 63,000 rows, and a structural edit costs more the
 *  bigger the grid already is. That, not the volume of data, is what
 *  made the document stop responding: the Spreadsheet service ended up
 *  timing out on any access, including a nine-cell status write.
 *
 *  Setting rowCount and columnCount once is a single API call whatever
 *  the size, and it shrinks as readily as it grows, so it doubles as
 *  the tail trim the old deleteRows() pass did.
 */
function _setGrid(ssId, sh, rows, cols) {
  Sheets.Spreadsheets.batchUpdate({
    requests: [{
      updateSheetProperties: {
        properties: {
          sheetId: sh.getSheetId(),
          gridProperties: { rowCount: Math.max(rows, 2), columnCount: Math.max(cols, 1) }
        },
        fields: 'gridProperties.rowCount,gridProperties.columnCount'
      }
    }]
  }, ssId);
}

/** Replace one tab with the full contents of one view.
 *
 *  Pages are still STREAMED from PostgREST -- holding 100k objects in
 *  memory and rows.concat(page) per page reallocates the whole array
 *  every time, which is what made the 90-day view unsafe to enable --
 *  but they are buffered into large blocks before being written.
 *
 *  Writes go through the Sheets API rather than Range.setValues().
 *  setValues is a per-call round trip through the Spreadsheet service,
 *  so 63 of them plus 63 grid resizes is 126 interactions with a
 *  document that gets heavier each time. Values.update takes the whole
 *  block in one request, and the grid is sized once up front.
 */
function _syncView(cfg, spec) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ssId = ss.getId();
  var sh = ss.getSheetByName(spec.tab) || ss.insertSheet(spec.tab);

  var headers = null;
  var written = 0;
  var buf = [];

  function flushBuf() {
    if (!buf.length) return;
    // A1 is the header row, so data starts at row 2.
    var a1 = "'" + spec.tab.replace(/'/g, "''") + "'!A" + (written + 2);
    Sheets.Spreadsheets.Values.update(
      { values: buf }, ssId, a1, { valueInputOption: 'RAW' });
    written += buf.length;
    buf = [];
  }

  for (var offset = 0; ; offset += PAGE) {
    var page = _fetchPage(cfg, spec.view, spec.order, offset);

    if (page.length) {
      if (!headers) {
        headers = Object.keys(page[0]);
        // Clear by VALUE, not Sheet.clear(): clearing values leaves the
        // grid alone, and the grid is about to be set deliberately.
        Sheets.Spreadsheets.Values.clear({}, ssId,
          "'" + spec.tab.replace(/'/g, "''") + "'");
        // Generous up front so no second resize is needed mid-write;
        // trimmed to the real count once the row total is known.
        _setGrid(ssId, sh, 100000, headers.length);
        Sheets.Spreadsheets.Values.update(
          { values: [headers] }, ssId,
          "'" + spec.tab.replace(/'/g, "''") + "'!A1",
          { valueInputOption: 'RAW' });
        sh.setFrozenRows(1);
        sh.getRange(1, 1, 1, headers.length).setFontWeight('bold');
      }
      buf = buf.concat(page.map(function (r) {
        return headers.map(function (h) { return r[h] === null ? '' : r[h]; });
      }));
      if (buf.length >= WRITE_CHUNK) flushBuf();
    }

    if (page.length < PAGE) break;       // short page means the last one
    if (offset > 500000) throw new Error(spec.view + ': runaway pagination');
  }
  flushBuf();

  if (!written) {
    sh.getRange(1, 1).setValue('No rows returned for ' + spec.view);
  } else {
    // Shrink to fit. Same single call that grew it.
    _setGrid(ssId, sh, written + 1, headers.length);
  }
  return written;
}

/** The entry point. This is what the nightly trigger calls. */
function syncMetaDirect() {
  _run(function (s) { return !s.ownRun; }, 'Status');
}

/**
 * The 90-day daily view, on its own. Its own trigger calls this, so it
 * gets a whole execution budget rather than the remainder of one --
 * see the ownRun note on VIEWS for why that was the difference between
 * reaching the current day and stopping in July.
 */
function syncDaily90() {
  _run(function (s) { return !!s.ownRun; }, 'Status 90d');
}

/** Everything, in one execution. Only worth it on Workspace, where the
 *  cap is 30 minutes rather than 6. */
function syncMetaDirectAll() {
  _run(function () { return true; }, 'Status');
}

function _run(pick, statusTab) {
  // One run at a time. Two executions writing the same document is
  // contention the Spreadsheet service reports as a timeout. The lock
  // is shared across both entry points on purpose -- the two triggers
  // are scheduled apart, but a manual run must not land on top of
  // either.
  //
  // Returning rather than waiting: the other run is doing this work
  // already, so a second one has nothing to add.
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30 * 1000)) {
    Logger.log('Another sync is already running; skipping this one.');
    return;
  }
  try {
    _syncMetaDirect(pick, statusTab);
  } finally {
    lock.releaseLock();
  }
}

function _syncMetaDirect(pick, statusTab) {
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

  VIEWS.filter(pick).forEach(function (spec) {
    if (!spec.enabled) { log.push([spec.view, 'skipped', 'disabled in VIEWS']); return; }
    try {
      var n = _syncView(cfg, spec);
      // Drain this view's writes before starting the next one.
      //
      // Apps Script queues Spreadsheet operations and flushes them
      // lazily, so without this the four views pile ~90,000 rows of
      // pending work into one queue and the FIRST call that forces a
      // flush pays for all of it. That call was _writeStatus, which is
      // why a timeout kept being reported there -- against a function
      // that writes nine cells. Flushing per view bounds the queue and
      // makes a timeout name the view that actually caused it.
      SpreadsheetApp.flush();
      log.push([spec.view, 'ok', n + ' rows']);
    } catch (e) {
      // One view failing must not cost the others.
      log.push([spec.view, 'FAILED', String(e).slice(0, 200)]);
    }
  });

  // The data is already in the sheet by this point. A failure writing
  // the status tab must not turn a good run into a red one -- that is
  // what made the timeout look like the sync had failed outright.
  try {
    _writeStatus(started, through, log, statusTab);
  } catch (e) {
    Logger.log('Status tab not written: ' + e);
  }
}

function _writeStatus(started, through, log, statusTab) {
  // Each entry point writes its OWN status tab. Sharing one meant the
  // second run of the night cleared the first run's report, so a tab
  // that had synced fine looked like it had never run.
  var name = statusTab || 'Status';
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
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
 * TWO triggers now: 07:00 for the three small views, 08:00 for the
 * 90-day daily view on its own. See the ownRun note on VIEWS.
 *
 * Safe to run more than once -- it clears its own triggers first.
 */
var HANDLERS = ['syncMetaDirect', 'syncDaily90', 'syncMetaDirectAll'];

function setupNightlyTrigger() {
  removeNightlyTrigger();
  // Two triggers, an hour apart. Apps Script time-based triggers fire
  // within the hour you name, not on the minute, so the gap has to be
  // wide enough that the second cannot start while the first is still
  // going -- the shared lock would make it skip rather than queue.
  ScriptApp.newTrigger('syncMetaDirect').timeBased().atHour(7).everyDays(1).create();
  ScriptApp.newTrigger('syncDaily90').timeBased().atHour(8).everyDays(1).create();
  Logger.log('Triggers set: syncMetaDirect 07:00, syncDaily90 08:00 ' +
             Session.getScriptTimeZone());
}

function removeNightlyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (HANDLERS.indexOf(t.getHandlerFunction()) !== -1) ScriptApp.deleteTrigger(t);
  });
}
