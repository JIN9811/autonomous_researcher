const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js', 'utf8');
const start = Date.parse('2026-09-18T10:52:39Z');
function windowAt(now, page = null) {
  const context = vm.createContext({ window: {}, URLSearchParams, Number, Math,
    Date: class extends Date { static now() { return now; } },
    fetch: async () => ({ok: true, json: async () => page}),
    liveRuntimeClock: { textContent: '' }, liveRuntimeStartedAt: null,
    liveRuntimeClockRunId: '', liveRuntimeClockRequest: '', liveRuntimeClockRetryAt: 0,
  });
  for (const name of ['liveWorkflowStartedAt', 'syncLiveRuntimeClock', 'tickLiveRuntimeClock']) {
    const index = source.indexOf(`function ${name}(`);
    vm.runInContext(source.slice(index, source.indexOf('\n}', index) + 2), context);
  }
  return context;
}
const session = {state: {run_id: 'r1', run_metadata: {run_clock: {
  run_id: 'r1', started_at: new Date(start).toISOString()}}}};
test('refresh and independent windows keep the server experiment start', () => {
  for (const seconds of [90, 150]) {
    const context = windowAt(start + seconds * 1000);
    context.syncLiveRuntimeClock(session);
    assert.equal(context.liveRuntimeClock.textContent, seconds === 90 ? '0d 00h 01m 30s' : '0d 00h 02m 30s');
    context.syncLiveRuntimeClock({...session, state: {...session.state, is_paused: true}});
    assert.equal(context.liveRuntimeStartedAt, start);
  }
});
test('new run clears old clock instead of starting at browser arrival', () => {
  const context = windowAt(start + 90000);
  context.syncLiveRuntimeClock(session);
  context.syncLiveRuntimeClock({state: {run_id: 'r2'}});
  assert.equal(context.liveRuntimeClock.textContent, '--:--');
});
test('legacy live run reads saved execution approval, not welcome or resume time', async () => {
  const context = windowAt(start + 90000, {transcript_path: '/runs/r1/live_planning_transcript.jsonl', messages: [
    {timestamp: new Date(start - 600000).toISOString(), content: 'Hello'},
    {timestamp: new Date(start).toISOString(), event_type: 'planning.workflow_trigger_accepted'},
    {timestamp: new Date(start + 60000).toISOString(), event_type: 'run_resume'},
  ]});
  context.syncLiveRuntimeClock({state: {run_id: 'r1'}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(context.liveRuntimeClock.textContent, '0d 00h 01m 30s');
});
test('late transcript response cannot overwrite a switched run', async () => {
  const context = windowAt(start + 90000, {transcript_path: '/runs/r1/live_planning_transcript.jsonl', messages: [
    {timestamp: new Date(start).toISOString(), event_type: 'planning.workflow_trigger_accepted'},
  ]});
  context.syncLiveRuntimeClock({state: {run_id: 'r1'}});
  context.syncLiveRuntimeClock({state: {run_id: 'r2'}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(context.liveRuntimeClock.textContent, '--:--');
});
test('replay does not use the wall clock', () => {
  const context = windowAt(start + 90000);
  context.window.AX4LABReplay = {};
  context.syncLiveRuntimeClock(session);
  assert.equal(context.liveRuntimeStartedAt, null);
});
test('elapsed time rolls over into English day and hour units', () => {
  const context = windowAt(start + (86400 + 2 * 3600 + 3 * 60 + 4) * 1000);
  context.syncLiveRuntimeClock(session);
  assert.equal(context.liveRuntimeClock.textContent, '1d 02h 03m 04s');
});
