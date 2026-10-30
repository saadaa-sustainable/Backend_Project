import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../MetaDirectSync.gs', import.meta.url), 'utf8');
const clone = value => JSON.parse(JSON.stringify(value));

// Small in-memory implementations of the external contracts. No credentials/network.
function harness(options = {}) {
  let clock = Date.parse('2026-10-17T06:00:00Z'), sequence = 10, locked = false;
  const properties = new Map(Object.entries({
    SUPABASE_URL: 'https://example.supabase.co', SUPABASE_KEY: 'sb_secret_test',
    SPREADSHEET_ID: 'test-sheet', ...options.properties
  }));
  const api = { rest: [], writes: [], batches: [], triggers: [], logs: [], sheets: [], failures: {}, through: '2026-10-16', cap: options.cap || 1000 };
  function sheet(name, data = [], rows = 10, cols = 7) {
    const s = { properties: { sheetId: sequence++, title: name, hidden: false,
      gridProperties: { rowCount: rows, columnCount: cols } }, developerMetadata: [], data: clone(data) };
    api.sheets.push(s); return s;
  }
  sheet('Notes', [['leave alone']]);
  api.addSheet = sheet;
  api.byName = name => api.sheets.find(s => s.properties.title === name);
  api.fail = (phase, how = 'before') => { api.failures[phase] = how; };
  function inject(phase, moment) {
    if (api.failures[phase] === moment) {
      delete api.failures[phase];
      throw new Error('Simulated connection failure: ' + phase);
    }
  }
  class FakeDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock])); }
    static now() { return clock; }
  }
  const props = {
    getProperty: key => properties.get(key) ?? null,
    setProperty: (key, value) => { assert.ok(Buffer.byteLength(value) < 9000, 'checkpoint must fit Script Properties'); properties.set(key, value); },
    deleteProperty: key => properties.delete(key)
  };
  const context = vm.createContext({
    Date: FakeDate,
    Logger: { log: s => api.logs.push(s) },
    PropertiesService: { getScriptProperties: () => props },
    Utilities: { getUuid: () => 'run-' + sequence++, sleep: ms => { clock += ms; } },
    LockService: { getScriptLock: () => ({ tryLock: () => { if (locked) return false; locked = true; return true; }, releaseLock: () => { locked = false; } }) },
    ScriptApp: {
      getProjectTriggers: () => [...api.triggers],
      deleteTrigger: trigger => { api.triggers = api.triggers.filter(t => t !== trigger); },
      newTrigger: handler => {
        const t = { getHandlerFunction: () => handler };
        const b = { timeBased: () => b, after: delay => { t.delay = delay; return b; },
          atHour: hour => { t.hour = hour; return b; }, everyDays: days => { t.days = days; return b; },
          inTimezone: tz => { t.tz = tz; return b; }, create: () => { api.triggers.push(t); return t; } };
        return b;
      }
    },
    UrlFetchApp: { fetch: (url, request) => {
      inject('rest', 'before');
      const u = new URL(url), view = u.pathname.split('/').at(-1);
      api.rest.push({ url, view, request: clone(request) }); clock += options.restMs || 0;
      if (options.onFetch) options.onFetch(api, view, u);
      if (api.httpError) return { getResponseCode: () => api.httpError };
      let rows, total;
      if (!view) rows = { definitions: Object.fromEntries(context.META_DIRECT.views.map(spec => [spec.view, {
        properties: Object.fromEntries((api.schemas[spec.view] || spec.keys).map(k => [k, {}]))
      }])) };
      else if (view === 'meta_direct_data_through') rows = [{ data_through: api.through }];
      else {
        let data = api.data[view] || [];
        total = data.length;
        const keys = u.searchParams.get('order').split(',').map(s => s.split('.')[0]);
        data = [...data].sort((a, b) => {
          for (const k of keys) { if (a[k] < b[k]) return -1; if (a[k] > b[k]) return 1; }
          return 0;
        });
        const or = u.searchParams.get('or');
        // PostgREST scalar filters keep the URL-decoded value literal. Quotes
        // are syntax only inside logical expressions such as or=(...).
        if (u.searchParams.has(keys[0])) {
          const filter = u.searchParams.get(keys[0]);
          const dot = filter.indexOf('.'), op = filter.slice(0, dot), cursor = filter.slice(dot + 1);
          assert.ok(op === 'gt' || op === 'gte');
          data = data.filter(r => op === 'gt' ? r[keys[0]] > cursor : r[keys[0]] >= cursor);
        }
        if (or) {
          const literals = or.match(/"(?:\\.|[^"\\])*"/g).map(JSON.parse);
          data = data.filter(r => r[keys[0]] > literals[0] || (r[keys[0]] === literals[1] && r[keys[1]] > literals[2]));
        }
        rows = data.slice(0, Math.min(api.cap, Number(u.searchParams.get('limit'))));
      }
      return { getResponseCode: () => 200, getContentText: () => JSON.stringify(rows),
        getAllHeaders: () => api.noCount ? {} : { 'Content-Range': '0-' + Math.max(0, rows.length - 1) + '/' + total } };
    } },
    Sheets: { Spreadsheets: {
      get: () => { inject('get', 'before'); return { sheets: api.sheets.map(s => ({ properties: clone(s.properties), developerMetadata: clone(s.developerMetadata) })) }; },
      batchUpdate: ({ requests }) => {
        const publishing = requests.some(r => r.createDeveloperMetadata);
        const phase = publishing ? 'publish' : 'batch';
        inject(phase, 'before');
        const before = clone(api.sheets), replies = [];
        try {
          for (const r of requests) {
            if (r.addSheet) {
              const p = r.addSheet.properties;
              assert.ok(!api.byName(p.title));
              const s = sheet(p.title, [], p.gridProperties.rowCount, p.gridProperties.columnCount);
              s.properties.hidden = !!p.hidden;
              replies.push({ addSheet: { properties: clone(s.properties) } });
            } else if (r.updateSheetProperties) {
              const p = r.updateSheetProperties.properties, s = api.sheets.find(s => s.properties.sheetId === p.sheetId);
              const g = { ...s.properties.gridProperties, ...p.gridProperties };
              s.properties = { ...s.properties, ...clone(p), gridProperties: g };
              s.data = s.data.slice(0, g.rowCount).map(row => row.slice(0, g.columnCount)); replies.push({});
            } else if (r.updateCells) {
              api.sheets.find(s => s.properties.sheetId === r.updateCells.range.sheetId).data = []; replies.push({});
            } else if (r.copyPaste) {
              assert.equal(r.copyPaste.pasteType, 'PASTE_VALUES');
              const src = api.sheets.find(s => s.properties.sheetId === r.copyPaste.source.sheetId);
              const dst = api.sheets.find(s => s.properties.sheetId === r.copyPaste.destination.sheetId);
              dst.data = clone(src.data.slice(0, r.copyPaste.source.endRowIndex)); replies.push({});
            } else if (r.deleteSheet) { api.sheets = api.sheets.filter(s => s.properties.sheetId !== r.deleteSheet.sheetId); replies.push({}); }
            else if (r.deleteDeveloperMetadata) {
              const lookup = r.deleteDeveloperMetadata.dataFilter.developerMetadataLookup;
              const s = api.sheets.find(s => s.properties.sheetId === lookup.metadataLocation.sheetId);
              s.developerMetadata = s.developerMetadata.filter(m => m.metadataKey !== lookup.metadataKey); replies.push({});
            } else if (r.createDeveloperMetadata) {
              const m = r.createDeveloperMetadata.developerMetadata;
              api.sheets.find(s => s.properties.sheetId === m.location.sheetId).developerMetadata.push(clone(m)); replies.push({});
            } else if (r.repeatCell) replies.push({});
            else throw new Error('Unhandled request: ' + JSON.stringify(r));
          }
        } catch (e) { api.sheets = before; throw e; }
        api.batches.push(clone(requests));
        inject(phase, 'after');
        return { replies };
      },
      Values: { update: (body, id, range, params) => {
        const m = range.match(/^'((?:[^']|'')+)'!A(\d+)$/), name = m[1].replace(/''/g, "'"), start = Number(m[2]) - 1;
        const phase = name.startsWith('__md_stage_') ? (start > 0 ? 'pageWrite' : 'stageHeader') : 'valueWrite';
        inject(phase, 'before');
        const s = api.byName(name); assert.ok(s, 'tab exists'); assert.equal(id, 'test-sheet');
        assert.equal(params.valueInputOption, 'RAW');
        assert.ok(start + body.values.length <= s.properties.gridProperties.rowCount);
        for (const row of body.values) assert.ok(row.length <= s.properties.gridProperties.columnCount);
        body.values.forEach((row, i) => { s.data[start + i] = clone(row); });
        api.writes.push({ name, start, rows: body.values.length, bytes: Buffer.byteLength(JSON.stringify(body)), cells: body.values.reduce((n, r) => n + r.length, 0), time: clock });
        inject(phase, 'after'); return {};
      } }
    } }
  });
  vm.runInContext(source, context);
  api.data = {}; api.schemas = {};
  for (const spec of context.META_DIRECT.views) {
    api.data[spec.view] = [{ ...Object.fromEntries(spec.keys.map(k => [k, k === 'date' ? '2026-10-16' : '99999999999999999'])), name: '=SUM(1,2)', spend: 12.5, empty: null }];
    api.schemas[spec.view] = Object.keys(api.data[spec.view][0]);
  }
  api.state = () => JSON.parse(properties.get(context.META_DIRECT.stateKey) || 'null');
  api.finish = () => { for (let i = 0; i < 100 && api.state()?.status !== 'DONE'; i++) context.continueMetaDirect(); assert.equal(api.state().status, 'DONE'); };
  api.only = (index = 0) => { context.META_DIRECT.views = [context.META_DIRECT.views[index]]; return context.META_DIRECT.views[0]; };
  api.set = (key, value) => properties.set(key, value);
  api.advance = ms => { clock += ms; };
  api.lock = value => { locked = value; };
  return { c: context, api };
}

test('all six tabs, literal text/IDs, nulls and measures; unrelated sheets untouched', () => {
  const { c, api } = harness(); c.syncMetaDirect(); api.finish();
  assert.equal(api.state().reports.length, 6);
  for (const spec of c.META_DIRECT.views) {
    const s = api.byName(spec.tab);
    assert.equal(s.data.length, 2); assert.equal(s.properties.gridProperties.frozenRowCount, 1);
    assert.ok(s.data[1].includes('99999999999999999')); assert.ok(s.data[1].includes('=SUM(1,2)'));
    assert.ok(s.data[1].includes(12.5)); assert.ok(s.data[1].includes(''));
  }
  assert.deepEqual(api.byName('Notes').data, [['leave alone']]);
  assert.equal(api.triggers.length, 0);
  assert.equal(api.rest[0].request.headers.Authorization, undefined);
});

test('server row cap smaller than page size does not truncate; compound keys continue within an ad', () => {
  const { c, api } = harness({ cap: 2 }); const spec = api.only(4);
  api.data[spec.view] = Array.from({ length: 9 }, (_, i) => ({ ad_id: 'ad' + Math.floor(i / 3), date: '2026-10-' + (10 + i % 3), spend: i }));
  c.syncMetaDirect(); api.finish();
  assert.equal(api.byName(spec.tab).data.length, 10);
  assert.equal(new Set(api.byName(spec.tab).data.slice(1).map(r => r.slice(0, 2).join('|'))).size, 9);
  assert.ok(api.rest.some(r => r.url.includes('or='))); assert.ok(api.rest.every(r => !r.url.includes('offset=')));
});

test('scalar cursor URLs preserve the raw value without introducing quote characters', () => {
  const { c } = harness();
  for (const value of ['120252362990490431', 'ad & name+with/characters,"quoted"']) {
    for (const spec of c.META_DIRECT.views.slice(0, 4)) {
      const query = c.mdQuery_(spec, [value], 2);
      assert.equal(new URL('https://example.test/' + query).searchParams.get(spec.keys[0]), 'gt.' + value);
    }
    const query = c.mdQuery_(c.META_DIRECT.views[4], [value, '2026-10-16'], 2);
    const params = new URL('https://example.test/' + query).searchParams;
    assert.equal(params.get('ad_id'), 'gte.' + value);
    assert.ok(params.get('or').includes('date.gt."2026-10-16"'));
  }
});

test('all six views traverse multiple pages with no repeated or missing IDs', () => {
  const { c, api } = harness({ cap: 2 });
  for (const spec of c.META_DIRECT.views) {
    api.data[spec.view] = Array.from({ length: 7 }, (_, i) => ({
      ...Object.fromEntries(spec.keys.map(k => [k, k === 'date' ? '2026-10-16' : '12025236299049043' + i])), spend: i
    }));
  }
  c.syncMetaDirect(); api.finish();
  for (const spec of c.META_DIRECT.views) {
    const rows = api.byName(spec.tab).data.slice(1);
    assert.equal(rows.length, 7);
    assert.equal(new Set(rows.map(r => r[0])).size, 7);
  }
});

test('a checkpoint stopped by the previous quoted cursor resumes without restarting or duplicating rows', () => {
  const { c, api } = harness({ cap: 2 }); const spec = api.only();
  api.data[spec.view] = Array.from({ length: 7 }, (_, i) => ({ ad_id: '12025236299049043' + i, spend: i }));
  const fixedQuery = c.mdQuery_;
  c.mdQuery_ = (...args) => fixedQuery(...args).replace(/(ad_id=gt\.)([^&]+)/, '$1%22$2%22');
  assert.throws(() => c.syncMetaDirect(), /Duplicate pagination key/);
  const checkpoint = api.state();
  // Nothing committed: REST pages accumulate into one Sheets write, so a
  // failure mid-batch discards the batch rather than half-writing it.
  // The cursor advances only on a committed write, which is what makes
  // the replay below exact instead of duplicating.
  assert.equal(checkpoint.current.written, 0);
  c.mdQuery_ = fixedQuery;
  c.resumeMetaDirect(); api.finish();
  assert.equal(api.state().runId, checkpoint.runId);
  assert.equal(api.byName(spec.tab).data.length, 8);
  assert.equal(new Set(api.byName(spec.tab).data.slice(1).map(r => r[0])).size, 7);
});

test('100,816 rows resume across executions, exact grid sizing and bounded requests', () => {
  const { c, api } = harness(); const spec = api.only(5);
  api.data[spec.view] = Array.from({ length: 100816 }, (_, i) => ({ ad_id: String(i).padStart(8, '0'), date: '2026-10-16', spend: i }));
  // Tight enough that batching has to work for this to land at all:
  // one write per ~5,000 rows instead of per 930 is what gets 100,816
  // rows through a 25-second budget.
  c.META_DIRECT.workMs = 25000; c.syncMetaDirect();
  api.finish();
  assert.equal(api.byName(spec.tab).data.length, 100817);
  assert.equal(api.byName(spec.tab).properties.gridProperties.rowCount, 100817);
  for (const w of api.writes.filter(w => w.name.startsWith('__md_stage_'))) {
    assert.ok(w.cells <= 300000, 'cells ' + w.cells);
    assert.ok(w.bytes < 1500000, 'bytes ' + w.bytes);
  }
  // The point of the change: far fewer Sheets round trips, each of which
  // costs a 1.2s throttle sleep. At the old 930-row page this view alone
  // was 109 writes.
  const stageWrites = api.writes.filter(w => w.name.startsWith('__md_stage_') && w.start > 0);
  assert.ok(stageWrites.length <= 25, 'stage writes: ' + stageWrites.length);
});

for (const moment of ['before', 'after']) test('failed page write ' + moment + ' commit preserves old tab and replays without duplicates', () => {
  const { c, api } = harness({ cap: 2 }); const spec = api.only();
  const old = api.addSheet(spec.tab, [['ad_id'], ['OLD'], ['OLD2']], 20, 8); const id = old.properties.sheetId;
  api.data[spec.view] = Array.from({ length: 5 }, (_, i) => ({ ad_id: String(i), spend: i }));
  api.fail('pageWrite', moment);
  assert.throws(() => c.syncMetaDirect(), /connection failure/);
  assert.deepEqual(api.byName(spec.tab).data, [['ad_id'], ['OLD'], ['OLD2']]);
  assert.equal(api.state().current.written, 0); assert.equal(api.state().status, 'ERROR'); assert.equal(api.triggers.length, 0);
  const requests = api.rest.length; assert.throws(() => c.continueMetaDirect(), /stopped/); assert.equal(api.rest.length, requests);
  c.resumeMetaDirect(); api.finish();
  assert.equal(api.byName(spec.tab).properties.sheetId, id);
  assert.equal(api.byName(spec.tab).data.length, 6);
});

for (const existing of [true, false]) for (const moment of ['before', 'after']) test('publish ' + moment + ' commit, existing=' + existing + ', recovers atomic response ambiguity', () => {
  const { c, api } = harness(); const spec = api.only();
  if (existing) api.addSheet(spec.tab, [['old']]);
  api.fail('publish', moment); assert.throws(() => c.syncMetaDirect(), /connection failure/);
  if (moment === 'before') assert.deepEqual(api.byName(spec.tab)?.data, existing ? [['old']] : undefined);
  c.resumeMetaDirect(); api.finish();
  assert.equal(api.byName(spec.tab).data.length, 2);
  assert.equal(api.sheets.filter(s => s.properties.title.startsWith('__md_stage_')).length, 0);
  assert.equal(api.batches.filter(b => b.some(r => r.createDeveloperMetadata)).length, 1);
});

test('empty view clears old rows while preserving schema and sheet identity', () => {
  const { c, api } = harness(); const spec = api.only();
  api.data[spec.view] = []; const old = api.addSheet(spec.tab, [['ad_id', 'spend'], ['stale', 100]], 500, 10);
  c.syncMetaDirect(); api.finish();
  assert.equal(api.byName(spec.tab).properties.sheetId, old.properties.sheetId);
  assert.equal(api.byName(spec.tab).data.length, 1); assert.ok(api.byName(spec.tab).data[0].includes('ad_id'));
  assert.equal(api.state().reports[0].total, 0);
});

test('source row count changes before publication: stop and retain live data', () => {
  let pages = 0;
  const { c, api } = harness({ onFetch: (a, view, u) => {
    if (view === 'meta_direct_active_30d' && u.searchParams.get('limit') === '1' && ++pages === 3) a.data[view].push({ ad_id: 'z', spend: 1 });
  } }); const spec = api.only(); api.addSheet(spec.tab, [['old']]);
  assert.throws(() => c.syncMetaDirect(), /row count changed/);
  assert.deepEqual(api.byName(spec.tab).data, [['old']]); assert.equal(api.triggers.length, 0);
});

test('source date changes during pause: stop without publishing incomplete data', () => {
  const { c, api } = harness(); const spec = api.only(); c.META_DIRECT.workMs = 1;
  c.syncMetaDirect(); assert.equal(api.state().status, 'WAITING'); api.through = '2026-10-17';
  assert.throws(() => c.resumeMetaDirect(), /Source date changed/); assert.equal(api.byName(spec.tab), undefined);
});

test('capacity failure preserves data; no huge preallocation', () => {
  const { c, api } = harness(); const spec = api.only(); api.addSheet(spec.tab, [['old']], 20, 5);
  c.META_DIRECT.maxCells = 380;
  assert.throws(() => c.syncMetaDirect(), /allocated cells/);
  assert.deepEqual(api.byName(spec.tab).data, [['old']]);
  assert.equal(api.sheets.filter(s => s.properties.title.startsWith('__md_stage_')).length, 0);
});

test('HTTP errors stop immediately, without retrying or fetching other tables', () => {
  const { c, api } = harness(); api.httpError = 503;
  assert.throws(() => c.syncMetaDirect(), /HTTP 503/);
  assert.equal(api.rest.length, 1); assert.equal(api.state().status, 'ERROR'); assert.equal(api.triggers.length, 0);
});

test('network exception and Sheets metadata failure stop immediately', () => {
  for (const phase of ['rest', 'get']) {
    const { c, api } = harness(); api.fail(phase);
    assert.throws(() => c.syncMetaDirect(), /connection failure/);
    assert.equal(api.state().status, 'ERROR'); assert.equal(api.triggers.length, 0);
  }
});

test('missing count cannot publish an apparently successful truncated export', () => {
  const { c, api } = harness(); api.only(); api.noCount = true;
  assert.throws(() => c.syncMetaDirect(), /Content-Range/);
});

test('wide multilingual rows split by bytes, preserving unwritten tail', () => {
  const { c, api } = harness(); const spec = api.only(); c.META_DIRECT.writeBytes = 20000;
  api.data[spec.view] = Array.from({ length: 8 }, (_, i) => ({ ad_id: String(i), name: '你好'.repeat(1000) }));
  c.syncMetaDirect(); api.finish();
  assert.equal(api.byName(spec.tab).data.length, 9);
  const writes = api.writes.filter(w => w.start > 0 && w.name.startsWith('__md_stage_'));
  assert.ok(writes.length > 1);
  for (const w of writes) assert.ok(w.bytes < 20000);
});

test('46-column source respects the cell budget without omitting rows', () => {
  const { c, api } = harness(); const spec = api.only();
  api.data[spec.view] = Array.from({ length: 2200 }, (_, i) => ({
    ad_id: String(i).padStart(5, '0'),
    ...Object.fromEntries(Array.from({ length: 45 }, (_, j) => ['metric_' + j, i + j]))
  }));
  c.syncMetaDirect(); api.finish();
  assert.equal(api.byName(spec.tab).data.length, 2201);
  assert.equal(api.byName(spec.tab).data[0].length, 46);
  const writes = api.writes.filter(w => w.start > 0 && w.name.startsWith('__md_stage_'));
  for (const w of writes) assert.ok(w.cells <= 300000, 'cells ' + w.cells);
  for (let i = 1; i < api.writes.length; i++) assert.ok(api.writes[i].time - api.writes[i - 1].time >= 1200);
});

test('lost staging header response reuses the same temporary tab', () => {
  const { c, api } = harness(); const spec = api.only();
  // A failed header write can follow successful tab creation. The title is the recovery key.
  api.fail('stageHeader', 'after');
  assert.throws(() => c.syncMetaDirect(), /connection failure/);
  assert.equal(api.state().current.phase, 'prepare');
  assert.equal(api.sheets.filter(s => s.properties.title.startsWith('__md_stage_')).length, 1);
  c.resumeMetaDirect(); api.finish();
  assert.equal(api.byName(spec.tab).data.length, 2);
  assert.equal(api.sheets.filter(s => s.properties.title.startsWith('__md_stage_')).length, 0);
});

test('only one trigger per handler; explicit IST slot; old trigger removed', () => {
  const { c, api } = harness(); assert.throws(() => c.setupNightlyTrigger(), /SYNC_HOUR_IST/);
  api.set('SYNC_HOUR_IST', '13'); c.ScriptApp.newTrigger('syncMetaDirect').timeBased().atHour(7).create();
  c.setupNightlyTrigger(); c.setupNightlyTrigger();
  assert.equal(api.triggers.length, 1); assert.equal(api.triggers[0].hour, 13); assert.equal(api.triggers[0].tz, 'Asia/Kolkata');
  c.removeNightlyTrigger(); assert.equal(api.triggers.length, 0);
});

test('lock skips overlapping run without any API requests', () => {
  const { c, api } = harness(); api.lock(true); c.syncMetaDirect(); assert.equal(api.rest.length, 0); assert.equal(api.state(), null);
});

test('restart discards only owned temporary data and starts fresh', () => {
  const { c, api } = harness(); const spec = api.only(); api.addSheet(spec.tab, [['old']]); api.fail('pageWrite');
  assert.throws(() => c.syncMetaDirect());
  const firstRun = api.state().runId; c.restartMetaDirect(); api.finish();
  assert.notEqual(api.state().runId, firstRun); assert.deepEqual(api.byName('Notes').data, [['leave alone']]);
});

test('stale checkpoint does not mix data across days', () => {
  const { c, api } = harness(); api.only(); c.META_DIRECT.workMs = 1; c.syncMetaDirect(); api.advance(13 * 3600000);
  assert.throws(() => c.resumeMetaDirect(), /over 12 hours/);
});

test('legacy keys send Bearer; new secrets never do', () => {
  const { c, api } = harness({ properties: { SUPABASE_KEY: 'eyJ.legacy.jwt' } }); api.only(); c.syncMetaDirect();
  assert.equal(api.rest[0].request.headers.Authorization, 'Bearer eyJ.legacy.jwt');
});

test('schema drift and null keys stop without publishing', () => {
  for (const data of [
    [{ ad_id: '1', name: 'a' }, { ad_id: '2', spend: 3 }],
    [{ ad_id: null, name: 'a' }],
    [{ ad_id: '1', name: 'a' }, { ad_id: '1', name: 'b' }]
  ]) {
    const { c, api } = harness(); const spec = api.only(); api.data[spec.view] = data;
    assert.throws(() => c.syncMetaDirect(), /Columns changed|Null pagination|Duplicate pagination/);
    assert.equal(api.byName(spec.tab), undefined);
  }
});
