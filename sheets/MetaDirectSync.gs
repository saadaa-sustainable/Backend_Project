/**
 * Supabase snapshots -> six Google Sheets tabs. See sheets/README.md for setup.
 * Requires the advanced Google Sheets service. Credentials stay in Script Properties.
 * Public entry points: syncMetaDirect, resumeMetaDirect, restartMetaDirect,
 * setupNightlyTrigger, removeNightlyTrigger, showMetaDirectStatus.
 */
var META_DIRECT = {
  views: [
    { view: 'meta_direct_active_30d', tab: 'Active 30d', keys: ['ad_id'] },
    { view: 'meta_direct_active_90d', tab: 'Active 90d', keys: ['ad_id'] },
    { view: 'meta_direct_adset_30d', tab: 'Ad Sets 30d', keys: ['adset_id'] },
    { view: 'meta_direct_campaign_30d', tab: 'Campaigns 30d', keys: ['campaign_id'] },
    { view: 'meta_direct_daily_30d', tab: 'Daily 30d', keys: ['ad_id', 'date'] },
    { view: 'meta_direct_daily_90d', tab: 'Daily 90d', keys: ['ad_id', 'date'] }
  ],
  // Rows per PostgREST request. The server may return fewer -- Supabase
  // caps this with db-max-rows -- which costs nothing: pagination is by
  // cursor, so a short page just advances less far.
  pageRows: 1000,
  // Rows accumulated across REST pages before ONE Sheets write. The old
  // code wrote every REST page, so a 43-column view wrote 930 rows at a
  // time (40000/43) and paid a 1.2s throttle sleep plus a round trip for
  // each. Measured 2026-10-29 the six views are 100,430 rows and ~53MB,
  // which is 111 writes and 133s of pure sleeping. At ~553 bytes a row
  // those 930 rows are 514KB against a 1.5MB budget, so two thirds of
  // every request was wasted. Filling the budget takes it to ~42.
  // Bounded on purpose. Bytes bind first on the real views (~2,700 rows
  // of a 43-column daily page fills 1.5MB), so this only caps narrow
  // ones -- and it bounds what a mid-batch failure throws away, since
  // the cursor advances only on a committed write.
  writeRows: 5000,
  // Conservative UTF-8 bound: 3 bytes per UTF-16 code unit, including JSON escaping.
  writeBytes: 1500000,
  // Cells per write, a second ceiling for very wide views. Sheets rejects
  // an oversized request outright, and bytes alone would not catch a view
  // of mostly short columns.
  writeCells: 300000,
  workMs: 150000, // Leave room for a slow final request inside the 6-minute limit.
  writeIntervalMs: 1200, // Under the Sheets per-user quota of 60 writes/minute.
  maxCells: 20000000,
  maxRunHours: 12,
  statusTab: 'Status',
  stateKey: 'META_DIRECT_SYNC_V2',
  markerKey: 'meta_direct_published_run',
  resumeHandler: 'continueMetaDirect',
  dailyHandler: 'dailyMetaDirect',
  lastWriteAt: 0
};

/** Manual start; resumes an incomplete run. Errors require an explicit resume. */
function syncMetaDirect() { mdRun_(true, true); }
function resumeMetaDirect() { mdRun_(true, false); }
/** Trigger entry points. Never silently retry a failed run. */
function continueMetaDirect() { mdRun_(false, false); }
function dailyMetaDirect() { mdRun_(false, true); }

function mdProperties_() { return PropertiesService.getScriptProperties(); }
function mdLoad_() {
  var raw = mdProperties_().getProperty(META_DIRECT.stateKey);
  return raw ? JSON.parse(raw) : null;
}
function mdSave_(state) {
  state.updatedAt = new Date().toISOString();
  mdProperties_().setProperty(META_DIRECT.stateKey, JSON.stringify(state));
}
function mdConfig_() {
  var p = mdProperties_();
  var url = (p.getProperty('SUPABASE_URL') || '').trim().replace(/\/+$/, '');
  var key = (p.getProperty('SUPABASE_KEY') || '').trim();
  var spreadsheetId = (p.getProperty('SPREADSHEET_ID') || '').trim();
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url) || !key || !spreadsheetId) {
    throw new Error('Set SUPABASE_URL (https://PROJECT.supabase.co), SUPABASE_KEY and SPREADSHEET_ID in Script Properties.');
  }
  if (key.indexOf('sb_publishable_') === 0) throw new Error('These private views require a server secret key, not a publishable key.');
  return { url: url, key: key, spreadsheetId: spreadsheetId };
}

function mdRun_(manual, mayStart) {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) { Logger.log('Another Meta Direct sync is running.'); return; }
  var state, cfg;
  var started = Date.now();
  META_DIRECT.lastWriteAt = started;
  try {
    state = mdLoad_();
    if (state && state.status === 'ERROR' && !manual) {
      mdDeleteTriggers_([META_DIRECT.resumeHandler]);
      throw new Error('Sync is stopped: ' + state.error + ' Run resumeMetaDirect or restartMetaDirect after correcting it.');
    }
    if (!state || state.status === 'DONE' || state.status === 'CANCELLED') {
      if (!mayStart) return;
      var previousReports = state ? state.reports : [];
      state = {
        runId: Utilities.getUuid(), startedAt: new Date().toISOString(), status: 'RUNNING',
        jobs: META_DIRECT.views, index: 0, current: null, sourceThrough: null,
        reports: META_DIRECT.views.map(function (v) {
          var old = previousReports.filter(function (r) { return r.view === v.view; })[0];
          return { view: v.view, tab: v.tab, status: 'PENDING', rows: 0, total: '', publishedAt: old ? old.publishedAt : '' };
        })
      };
    }
    cfg = mdConfig_();
    if (state.spreadsheetId && (state.spreadsheetId !== cfg.spreadsheetId || state.sourceUrl !== cfg.url)) {
      throw new Error('Connection properties changed during this run. Restore them, then restartMetaDirect before changing the destination.');
    }
    state.spreadsheetId = cfg.spreadsheetId;
    state.sourceUrl = cfg.url;
    if (Date.now() - Date.parse(state.startedAt) > META_DIRECT.maxRunHours * 3600000) {
      throw new Error('Checkpoint is over ' + META_DIRECT.maxRunHours + ' hours old. Run restartMetaDirect for a fresh snapshot.');
    }
    state.status = 'RUNNING';
    state.error = '';
    mdSave_(state);
    // A watchdog survives a hard Apps Script timeout. Caught failures remove it.
    mdScheduleResume_(7 * 60000);
    mdEnsureStatus_(cfg, state);
    if (state.sourceThrough === null) {
      state.sourceThrough = mdThrough_(cfg);
      mdSave_(state);
    } else {
      mdCheckThrough_(cfg, state);
    }
    mdWriteStatus_(cfg, state);
    while (state.index < state.jobs.length && Date.now() - started < META_DIRECT.workMs) {
      var spec = state.jobs[state.index];
      if (!state.current) mdPrepare_(cfg, state, spec);
      else if (state.current.phase === 'prepare') mdCreateStage_(cfg, state);
      else if (state.current.phase === 'fetch') mdPage_(cfg, state, spec);
      else { mdPublish_(cfg, state, spec); mdWriteStatus_(cfg, state); }
    }
    state.status = state.index === state.jobs.length ? 'DONE' : 'WAITING';
    mdSave_(state);
    mdWriteStatus_(cfg, state);
    if (state.status === 'DONE') mdDeleteTriggers_([META_DIRECT.resumeHandler]);
    else mdScheduleResume_(60000);
    Logger.log(state.status + ': ' + state.index + '/' + state.jobs.length + ' tabs published.');
  } catch (error) {
    var message = mdSafeError_(error, cfg);
    if (state) {
      state.status = 'ERROR';
      state.error = message;
      mdSave_(state);
    }
    mdDeleteTriggers_([META_DIRECT.resumeHandler]);
    Logger.log('STOPPED: ' + message);
    // No retry of a failed Sheets connection. Properties + Executions retain the error.
    if (cfg && state && state.statusId !== undefined && error.service !== 'Sheets') {
      try { mdWriteStatus_(cfg, state); } catch (statusError) { Logger.log('Status tab unavailable; see Executions / showMetaDirectStatus.'); }
    }
    throw new Error(message);
  } finally { lock.releaseLock(); }
}

function mdSafeError_(error, cfg) {
  var message = String(error && error.message || error);
  if (cfg && cfg.key) message = message.split(cfg.key).join('[redacted]');
  return message.slice(0, 600);
}
function mdService_(name, fn) {
  try { return fn(); }
  catch (error) { var wrapped = new Error(name + ': ' + error.message); wrapped.service = name; throw wrapped; }
}
function mdWrite_(fn) {
  var wait = META_DIRECT.writeIntervalMs - (Date.now() - META_DIRECT.lastWriteAt);
  if (wait > 0) Utilities.sleep(wait);
  META_DIRECT.lastWriteAt = Date.now();
  return mdService_('Sheets', fn);
}
function mdBatch_(cfg, requests) {
  return mdWrite_(function () { return Sheets.Spreadsheets.batchUpdate({ requests: requests }, cfg.spreadsheetId); });
}
function mdSheets_(cfg) {
  var result = mdService_('Sheets', function () {
    return Sheets.Spreadsheets.get(cfg.spreadsheetId, { fields: 'sheets(properties,developerMetadata)' });
  });
  return result.sheets || [];
}
function mdFind_(sheets, name) {
  return sheets.filter(function (s) { return s.properties.title === name; })[0];
}
function mdCells_(sheets) {
  return sheets.reduce(function (n, s) {
    var g = s.properties.gridProperties;
    return n + (g ? g.rowCount * g.columnCount : 0);
  }, 0);
}
function mdCapacity_(cells) {
  if (cells > META_DIRECT.maxCells) throw new Error('Sync needs ' + cells.toLocaleString() + ' allocated cells including the temporary copy; budget is ' + META_DIRECT.maxCells.toLocaleString() + '. Remove unused rows/columns, or place the largest tab in a separate spreadsheet/script. Published data has been kept.');
}
function mdA1_(name, row) { return "'" + name.replace(/'/g, "''") + "'!A" + row; }

function mdRest_(cfg, path, count) {
  var headers = { apikey: cfg.key, Accept: path ? 'application/json' : 'application/openapi+json', 'Accept-Profile': 'public' };
  // New sb_secret keys are not JWTs. Only legacy JWT keys use Bearer auth.
  if (cfg.key.indexOf('sb_secret_') !== 0) headers.Authorization = 'Bearer ' + cfg.key;
  if (count) headers.Prefer = 'count=exact';
  var response = mdService_('Supabase', function () {
    return UrlFetchApp.fetch(cfg.url + '/rest/v1/' + path, {
      method: 'get', headers: headers, muteHttpExceptions: true, followRedirects: false
    });
  });
  var code = response.getResponseCode();
  if (code !== 200 && code !== 206) {
    // Do not log response bodies, which may contain sensitive query details.
    var failure = new Error('Supabase HTTP ' + code + ' for ' + path.split('?')[0] + '. Check API key/grants (401/403), view name (404), quotas (429), or database health (5xx).');
    failure.service = 'Supabase';
    throw failure;
  }
  var rows = JSON.parse(response.getContentText());
  var total = null;
  if (count) {
    var h = response.getAllHeaders();
    Object.keys(h).forEach(function (k) {
      if (k.toLowerCase() === 'content-range') {
        var m = String(h[k]).match(/\/(\d+)$/);
        if (m) total = Number(m[1]);
      }
    });
    if (total === null) throw new Error('Missing exact Content-Range count; refusing to publish an unverified export.');
  }
  return { rows: rows, total: total };
}
function mdThrough_(cfg) {
  var rows = mdRest_(cfg, 'meta_direct_data_through?select=data_through&limit=1', false).rows;
  if (!Array.isArray(rows) || !rows[0] || !rows[0].data_through) throw new Error('Meta data-through date is missing. Wait for the backend refresh.');
  return String(rows[0].data_through);
}
function mdCheckThrough_(cfg, state) {
  if (mdThrough_(cfg) !== state.sourceThrough) throw new Error('Source date changed while exporting. Wait for the backend refresh to finish, then run restartMetaDirect.');
}
function mdLiteral_(value) { return '"' + String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"'; }
function mdQuery_(spec, cursor, limit) {
  var params = ['select=*', 'order=' + spec.keys.map(function (k) { return k + '.asc'; }).join(','), 'limit=' + limit];
  if (cursor) {
    // Scalar filters use the literal value after gt./gte. Adding logical-filter
    // quotes here makes them part of the text ID and can repeat previous pages.
    if (spec.keys.length === 1) params.push(spec.keys[0] + '=' + encodeURIComponent('gt.' + String(cursor[0])));
    else {
      // Matches the existing UNIQUE (ad_id, date) index; no growing OFFSET scans.
      var a = spec.keys[0], b = spec.keys[1];
      var filter = '(' + a + '.gt.' + mdLiteral_(cursor[0]) + ',and(' + a + '.eq.' + mdLiteral_(cursor[0]) + ',' + b + '.gt.' + mdLiteral_(cursor[1]) + '))';
      params.push(a + '=' + encodeURIComponent('gte.' + String(cursor[0])));
      params.push('or=' + encodeURIComponent(filter));
    }
  }
  return spec.view + '?' + params.join('&');
}

function mdPrepare_(cfg, state, spec) {
  mdCheckThrough_(cfg, state);
  var first = mdRest_(cfg, mdQuery_(spec, null, 1), true);
  if (!Array.isArray(first.rows)) throw new Error('Unexpected response for ' + spec.view);
  var headers;
  if (first.rows.length) headers = Object.keys(first.rows[0]);
  else {
    // Empty views still need a real schema; never keep yesterday's rows as today's.
    var schema = mdRest_(cfg, '', false).rows;
    var definition = schema.definitions && schema.definitions[spec.view];
    if (!definition || !definition.properties) throw new Error('No schema for empty ' + spec.view + '. Enable the PostgREST OpenAPI endpoint.');
    headers = Object.keys(definition.properties);
  }
  if (!headers.length || spec.keys.some(function (key) { return headers.indexOf(key) < 0; })) throw new Error('Missing pagination columns in ' + spec.view);
  state.current = {
    phase: 'prepare', headers: headers, total: first.total, written: 0, cursor: null,
    stageName: '__md_stage_' + state.runId.replace(/-/g, '') + '_' + state.index
  };
  var report = state.reports[state.index];
  report.total = first.total;
  report.status = 'FETCHING';
  mdSave_(state);
}
function mdCreateStage_(cfg, state) {
  var c = state.current, spec = state.jobs[state.index];
  var sheets = mdSheets_(cfg), stage = mdFind_(sheets, c.stageName), target = mdFind_(sheets, spec.tab);
  var rows = Math.max(2, c.total + 1), cols = c.headers.length;
  var oldCells = target ? target.properties.gridProperties.rowCount * target.properties.gridProperties.columnCount : 0;
  // Check peak: the stage and resized live tab coexist during the atomic publish.
  mdCapacity_(mdCells_(sheets) + (stage ? 0 : rows * cols) + (target ? Math.max(0, rows * cols - oldCells) : 0));
  if (!stage) {
    var result = mdBatch_(cfg, [{ addSheet: { properties: {
      title: c.stageName, hidden: true, gridProperties: { rowCount: rows, columnCount: cols }
    } } }]);
    c.stageId = result.replies[0].addSheet.properties.sheetId;
  } else c.stageId = stage.properties.sheetId;
  c.targetId = target ? target.properties.sheetId : null;
  // If a timeout happened after creation but before saving, the unique title recovers it.
  mdWriteValues_(cfg, c.stageName, 1, [c.headers]);
  c.phase = c.total ? 'fetch' : 'publish';
  mdSave_(state);
}
function mdValue_(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('Non-finite number in source data.');
  var result = typeof value === 'object' ? JSON.stringify(value) : value;
  if (typeof result === 'string' && result.length > 50000) throw new Error('A source cell exceeds 50,000 characters; no truncation was performed.');
  return result;
}
function mdWriteValues_(cfg, tab, row, values) {
  mdWrite_(function () {
    return Sheets.Spreadsheets.Values.update({ values: values, majorDimension: 'ROWS' }, cfg.spreadsheetId, mdA1_(tab, row), { valueInputOption: 'RAW' });
  });
}
function mdPage_(cfg, state, spec) {
  var c = state.current;
  var values = [], bytes = 64, cursor = c.cursor, seen = {};
  if (cursor) seen[JSON.stringify(cursor)] = true;
  // Fetch until the write budget is full, then write once. Decoupling
  // the two is the whole optimisation: a REST page is cheap and may be
  // capped server-side, a Sheets write costs a round trip and a 1.2s
  // throttle sleep, so the second should not be paid per the first.
  var budgetRows = Math.min(META_DIRECT.writeRows,
                            Math.max(1, Math.floor(META_DIRECT.writeCells / c.headers.length)));
  var full = false;
  while (!full && values.length < budgetRows && c.written + values.length < c.total) {
    var want = Math.min(META_DIRECT.pageRows, budgetRows - values.length,
                        c.total - c.written - values.length);
    var rows = mdRest_(cfg, mdQuery_(spec, cursor, want), false).rows;
    if (!Array.isArray(rows) || !rows.length) throw new Error('Unexpected end of ' + spec.view + ' after ' + (c.written + values.length) + '/' + c.total + ' rows. Run restartMetaDirect after refresh.');
    if (rows.length > want) throw new Error('Supabase returned more rows than requested.');
    var before = values.length;
    var result = mdCollect_(rows, c, spec, values, bytes, cursor, seen);
    bytes = result.bytes; cursor = result.cursor; full = result.full;
    // A short page means the server has no more to give at this cursor;
    // only an exhausted budget or a genuinely empty tail stops the loop.
    if (!full && values.length === before) break;
    if (rows.length < want) {
      // Server-side cap, not the end of the view: keep going from the
      // new cursor unless the budget is now full.
      if (values.length >= budgetRows) break;
    }
  }
  if (!values.length) throw new Error('No rows accumulated for ' + spec.view + '.');
  // Deterministic range: replay after an uncertain write overwrites, never appends.
  mdWriteValues_(cfg, c.stageName, c.written + 2, values);
  c.written += values.length;
  c.cursor = cursor;
  state.reports[state.index].rows = c.written;
  if (c.written === c.total) c.phase = 'publish';
  mdSave_(state);
}

/** Validate and append one REST page onto the pending write batch.
 *  Returns the running byte count, the last accepted key, and whether
 *  the byte budget filled mid-page -- in which case the remaining rows
 *  are simply re-fetched next time from the last COMMITTED cursor. */
function mdCollect_(rows, c, spec, values, bytes, cursor, seen) {
  var full = false;
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    if (Object.keys(row).length !== c.headers.length || c.headers.some(function (h) { return !Object.prototype.hasOwnProperty.call(row, h); })) {
      throw new Error('Columns changed during export. Run restartMetaDirect.');
    }
    var key = spec.keys.map(function (k) {
      if (row[k] === null || row[k] === undefined) throw new Error('Null pagination key: ' + k);
      if (typeof row[k] === 'number' && !Number.isSafeInteger(row[k])) throw new Error('Unsafe numeric ID. Expose IDs as text in Supabase.');
      return row[k];
    });
    var signature = JSON.stringify(key);
    if (seen[signature]) throw new Error('Duplicate pagination key in ' + spec.view + '.');
    seen[signature] = true;
    var cells = c.headers.map(function (h) { return mdValue_(row[h]); });
    var size = JSON.stringify(cells).length * 3 + 3;
    if (bytes + size > META_DIRECT.writeBytes) {
      if (!values.length) throw new Error('One row exceeds the configured write payload. Reduce exported text sizes.');
      full = true;
      break; // Fetch the unwritten tail again using the last COMMITTED key.
    }
    values.push(cells); bytes += size; cursor = key;
  }
  return { bytes: bytes, cursor: cursor, full: full };
}
function mdPublish_(cfg, state, spec) {
  var c = state.current;
  var sheets = mdSheets_(cfg), target = mdFind_(sheets, spec.tab);
  var marker = state.runId + ':' + state.index;
  // If the final request succeeded but its response/checkpoint was lost, do not copy twice.
  if (target && (target.developerMetadata || []).some(function (m) { return m.metadataKey === META_DIRECT.markerKey && m.metadataValue === marker; })) {
    mdFinishView_(state); return;
  }
  var stage = mdFind_(sheets, c.stageName);
  if (!stage || stage.properties.sheetId !== c.stageId) throw new Error('Temporary tab is missing. Run restartMetaDirect.');
  if ((target ? target.properties.sheetId : null) !== c.targetId) throw new Error('Destination tab changed during sync. Run restartMetaDirect.');
  mdCheckThrough_(cfg, state);
  var check = mdRest_(cfg, mdQuery_(spec, null, 1), true);
  if (check.total !== c.total) throw new Error('Source row count changed. Wait for refresh, then run restartMetaDirect.');
  var rows = Math.max(2, c.total + 1), cols = c.headers.length, requests = [];
  var targetId = target ? c.targetId : c.stageId;
  if (!target) {
    // First import: the complete temporary tab can become the output directly.
    requests.push({ updateSheetProperties: { properties: {
      sheetId: targetId, title: spec.tab, hidden: false, gridProperties: { frozenRowCount: 1 }
    }, fields: 'title,hidden,gridProperties.frozenRowCount' } });
  } else {
    var g = target.properties.gridProperties;
    mdCapacity_(mdCells_(sheets) + Math.max(0, rows * cols - g.rowCount * g.columnCount));
    requests.push({ updateSheetProperties: { properties: {
      sheetId: targetId, gridProperties: { rowCount: rows, columnCount: cols, frozenRowCount: 1 }
    }, fields: 'gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenRowCount' } });
    requests.push({ updateCells: { range: { sheetId: targetId }, fields: 'userEnteredValue' } });
    requests.push({ copyPaste: {
      source: { sheetId: c.stageId, startRowIndex: 0, endRowIndex: c.total + 1, startColumnIndex: 0, endColumnIndex: cols },
      destination: { sheetId: targetId, startRowIndex: 0, endRowIndex: c.total + 1, startColumnIndex: 0, endColumnIndex: cols },
      pasteType: 'PASTE_VALUES'
    } });
    requests.push({ deleteSheet: { sheetId: c.stageId } });
  }
  requests.push({ repeatCell: { range: { sheetId: targetId, startRowIndex: 0, endRowIndex: 1 },
    cell: { userEnteredFormat: { textFormat: { bold: true } } }, fields: 'userEnteredFormat.textFormat.bold' } });
  requests.push({ deleteDeveloperMetadata: { dataFilter: { developerMetadataLookup: {
    metadataKey: META_DIRECT.markerKey, metadataLocation: { sheetId: targetId }, locationMatchingStrategy: 'EXACT_LOCATION'
  } } } });
  requests.push({ createDeveloperMetadata: { developerMetadata: {
    metadataKey: META_DIRECT.markerKey, metadataValue: marker, location: { sheetId: targetId }, visibility: 'DOCUMENT'
  } } });
  // One atomic request preserves the existing sheet ID and references. Old data is
  // replaced only here, once all rows have been fetched. The marker commits with it.
  mdBatch_(cfg, requests);
  mdFinishView_(state);
}
function mdFinishView_(state) {
  var report = state.reports[state.index];
  report.status = 'OK';
  report.rows = state.current.total;
  report.publishedAt = new Date().toISOString();
  state.index += 1;
  state.current = null;
  mdSave_(state);
}

function mdEnsureStatus_(cfg, state) {
  var sheets = mdSheets_(cfg), status = mdFind_(sheets, META_DIRECT.statusTab);
  if (!status) {
    mdCapacity_(mdCells_(sheets) + 30 * 7);
    var result = mdBatch_(cfg, [{ addSheet: { properties: { title: META_DIRECT.statusTab, gridProperties: { rowCount: 30, columnCount: 7 } } } }]);
    state.statusId = result.replies[0].addSheet.properties.sheetId;
  } else {
    state.statusId = status.properties.sheetId;
    var g = status.properties.gridProperties;
    if (g.rowCount < 15 || g.columnCount < 7) {
      mdCapacity_(mdCells_(sheets) - g.rowCount * g.columnCount + Math.max(30, g.rowCount) * Math.max(7, g.columnCount));
      mdBatch_(cfg, [{ updateSheetProperties: { properties: { sheetId: state.statusId, gridProperties: {
        rowCount: Math.max(30, g.rowCount), columnCount: Math.max(7, g.columnCount)
      } }, fields: 'gridProperties.rowCount,gridProperties.columnCount' } }]);
    }
  }
  mdSave_(state);
}
function mdWriteStatus_(cfg, state) {
  var values = [
    ['Run status', state.status], ['Started (UTC)', state.startedAt],
    ['Updated (UTC)', state.updatedAt], ['Meta source data through', state.sourceThrough || ''],
    ['Error', state.error || ''],
    ['Note', 'Source date is not proof that every snapshot refreshed. See per-tab publication times.'],
    ['', ''], ['View', 'Tab', 'Status', 'Rows staged', 'Expected rows', 'Published (UTC)', 'Run ID']
  ];
  state.reports.forEach(function (r, i) {
    values.push([r.view, r.tab, i === state.index && state.status === 'ERROR' ? 'ERROR' : r.status,
      r.rows, r.total, r.publishedAt, state.runId]);
  });
  mdWriteValues_(cfg, META_DIRECT.statusTab, 1, values.map(function (row) {
    while (row.length < 7) row.push('');
    return row;
  }));
}
function showMetaDirectStatus() {
  var state = mdLoad_();
  Logger.log(state ? JSON.stringify(state, null, 2) : 'No sync has started.');
}
function mdDeleteTriggers_(handlers) {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (handlers.indexOf(trigger.getHandlerFunction()) >= 0) ScriptApp.deleteTrigger(trigger);
  });
}
function mdScheduleResume_(delay) {
  mdDeleteTriggers_([META_DIRECT.resumeHandler]);
  ScriptApp.newTrigger(META_DIRECT.resumeHandler).timeBased().after(delay).create();
}
/** Set SYNC_HOUR_IST to a slot AFTER the backend snapshot refresh completes. */
function setupNightlyTrigger() {
  mdConfig_();
  var hour = mdProperties_().getProperty('SYNC_HOUR_IST');
  if (hour === null || !/^\d{1,2}$/.test(hour) || Number(hour) > 23) {
    throw new Error('Set SYNC_HOUR_IST (0-23) after the backend refresh completion time. The backend starts at 07:00 IST; do not schedule both together.');
  }
  // Also removes this owner's trigger from the previous version of the script.
  mdDeleteTriggers_(['syncMetaDirect', META_DIRECT.dailyHandler]);
  ScriptApp.newTrigger(META_DIRECT.dailyHandler).timeBased().atHour(Number(hour)).everyDays(1).inTimezone('Asia/Kolkata').create();
  Logger.log('Daily sync installed in the ' + hour + ':00-' + hour + ':59 IST window.');
}
function removeNightlyTrigger() { mdDeleteTriggers_(['syncMetaDirect', META_DIRECT.dailyHandler]); }
/** Discard ONLY this run's hidden staging tab; keep every published tab. Then start fresh. */
function restartMetaDirect() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) throw new Error('A sync is running. Wait for it to finish this execution.');
  try {
    var state = mdLoad_();
    mdDeleteTriggers_([META_DIRECT.resumeHandler]);
    if (state && state.current) {
      var cfg = mdConfig_();
      if (cfg.spreadsheetId !== state.spreadsheetId || cfg.url !== state.sourceUrl) throw new Error('Restore the connection properties used by the saved run before restarting.');
      var stage = mdFind_(mdSheets_(cfg), state.current.stageName);
      if (stage && stage.properties.hidden && stage.properties.title.indexOf('__md_stage_') === 0) {
        mdBatch_(cfg, [{ deleteSheet: { sheetId: stage.properties.sheetId } }]);
      }
    }
    mdProperties_().deleteProperty(META_DIRECT.stateKey);
  } finally { lock.releaseLock(); }
  syncMetaDirect();
}
