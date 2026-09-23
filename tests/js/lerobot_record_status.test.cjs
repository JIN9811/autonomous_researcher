const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../web/static/lerobot.js'), 'utf8');

function fixture() {
  const timers = new Map(), statuses = [], results = [], requests = [];
  let id = 0;
  const context = vm.createContext({
    window: {setInterval(fn) { timers.set(++id, fn); return id; }, clearInterval(key) { timers.delete(key); }},
    $: () => ({}), sessionPayload: (_, payload) => payload,
    postJson: (_, payload) => new Promise((resolve, reject) => requests.push({payload, resolve, reject})),
    setActionStatus: (_, state, label, data) => statuses.push({state, label, data}),
    renderResult: (_, data) => results.push(data), syncFieldsFromWorkflowResponse() {},
    handleIsaacRgbdRenderResponse() {}, refreshConfig: async () => {},
  });
  vm.runInContext('let recordStatusTimer = null; let recordStatusGeneration = 0;\n' +
    source.slice(source.indexOf('function recordIsActive('), source.indexOf('async function runTrainAction(')), context);
  vm.runInContext(source.slice(source.indexOf('async function runAction('), source.indexOf('function renderTeleopHandoff(')), context);
  return {context, timers, statuses, results, requests, tick: () => [...timers.values()][0]()};
}
const active = (id) => ({ok: true, workflow: 'record', session_id: id, status: 'RECORDING', returncode: null});

test('temporary status transport failure keeps retrying and recovers', async () => {
  const f = fixture(); f.context.startRecordStatusPolling('new');
  let pending = f.tick(); f.requests[0].reject(new Error('timeout')); await pending;
  assert.notEqual(f.statuses.at(-1).state, 'error'); assert.equal(f.timers.size, 1);
  pending = f.tick(); f.requests[1].resolve(active('new')); await pending;
  assert.equal(f.statuses.at(-1).state, 'ok'); assert.equal(f.timers.size, 1);
});
test('HTTP and malformed responses are unavailable status, not failed recording', async () => {
  for (const status of ['http_error', 'invalid_json']) {
    const f = fixture(); f.context.startRecordStatusPolling('new');
    const pending = f.tick(); f.requests[0].resolve({ok: false, status}); await pending;
    assert.notEqual(f.statuses.at(-1).state, 'error'); assert.equal(f.timers.size, 1);
    assert.equal(f.results.length, 0);
  }
});
test('late prior-session success or failure cannot overwrite or stop new polling', async () => {
  for (const reject of [false, true]) {
    const f = fixture(); f.context.startRecordStatusPolling('old'); const old = f.tick();
    f.context.startRecordStatusPolling('new'); const current = f.tick();
    f.requests[1].resolve(active('new')); await current;
    if (reject) f.requests[0].reject(new Error('old timeout'));
    else f.requests[0].resolve({...active('old'), ok: false, status: 'FAILED', returncode: 1});
    await old;
    assert.equal(f.statuses.length, 1); assert.equal(f.results[0].session_id, 'new');
    assert.equal(f.timers.size, 1);
  }
});
test('status requests do not overlap', async () => {
  const f = fixture(); f.context.startRecordStatusPolling('new'); const pending = f.tick();
  const second = f.tick(); assert.equal(f.requests.length, 1); await second;
  f.requests[0].resolve(active('new')); await pending;
});
test('actual process failure remains an error and ends polling', async () => {
  const f = fixture(); f.context.startRecordStatusPolling('new'); const pending = f.tick();
  f.requests[0].resolve({...active('new'), status: 'FAILED', returncode: 1}); await pending;
  assert.equal(f.statuses.at(-1).state, 'error'); assert.equal(f.timers.size, 0);
});

test('starting a new recording invalidates old polling before the start response', async () => {
  const f = fixture(); f.context.startRecordStatusPolling('old'); const old = f.tick();
  const start = f.context.runAction('record start', '/api/lerobot/record/start', {}, {});
  f.requests[0].resolve({...active('old'), ok: false, status: 'FAILED'}); await old;
  assert.equal(f.statuses.length, 1); assert.equal(f.statuses[0].state, 'running');
  f.requests[1].resolve(active('new')); await start;
  assert.equal(f.statuses.at(-1).state, 'ok'); assert.equal(f.timers.size, 1);
  assert.equal(f.results.at(-1).session_id, 'new');
});
