const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js', 'utf8');

function context() {
  const ctx = vm.createContext({
    Date, Promise, liveLastSession: {}, livePrinterMonitorInFlight: null,
    livePrinterMonitorLastRefresh: 0, liveAuxRefreshInFlight: null,
    run: 'run-a', renders: 0, calls: 0, applied: [],
    liveSpecimenAgentWorking: () => true,
  });
  vm.runInContext(`
    function liveCurrentRunId() { return run; }
    function renderLiveRuntime() { renders++; }
    function applyLivePrinterMonitorStatus(status, runId) { applied.push({status, runId}); }
    function fetchJsonOrThrow() { calls++; return new Promise(resolve => { reply = resolve; }); }
    function fetch() { return new Promise(() => {}); }
    function refreshLiveObjectiveState() { return new Promise(() => {}); }
  `, ctx);
  for (const name of ['refreshLivePrinterMonitorStatus', 'refreshPlanningAuxiliaryState']) {
    const start = source.indexOf(`async function ${name}(`);
    vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), ctx);
  }
  return ctx;
}

test('printer response renders without waiting for auxiliary requests', async () => {
  const ctx = context();
  ctx.refreshPlanningAuxiliaryState({});
  ctx.reply({ok: true});
  await ctx.livePrinterMonitorInFlight;
  assert.equal(ctx.renders, 1);
  assert.equal(ctx.applied.length, 1);
  assert.notEqual(ctx.liveAuxRefreshInFlight, null);
});

test('in-flight requests are shared and rapid refreshes throttled', async () => {
  const ctx = context();
  const first = ctx.refreshLivePrinterMonitorStatus({});
  const second = ctx.refreshLivePrinterMonitorStatus({});
  assert.equal(ctx.calls, 1);
  ctx.reply({ok: true});
  await Promise.all([first, second]);
  await ctx.refreshLivePrinterMonitorStatus({});
  assert.equal(ctx.calls, 1);
});

test('late response cannot contaminate a different run', async () => {
  const ctx = context();
  const pending = ctx.refreshLivePrinterMonitorStatus({});
  ctx.run = 'run-b';
  ctx.reply({ok: true});
  await pending;
  assert.equal(ctx.applied.length, 0);
  assert.equal(ctx.renders, 0);
});

test('video-play snapshot cannot pin an older printer state over new telemetry', () => {
  const old = {ts: '2026-09-17T01:00:00Z', payload: {tool: 'printer.status'}};
  const fresh = {ts: '2026-09-17T01:00:02Z', payload: {tool: 'printer.status'}};
  const ctx = vm.createContext({livePrinterMonitorOverride: old, livePrinterMonitorEvent: fresh,
    liveCurrentRunId: () => 'run-a', eventMatchesCurrentRun: () => true,
    timelineSourceEvents: () => [old], eventPayload: e => e.payload,
    eventTimestampMs: e => Date.parse(e.ts)});
  const start = source.indexOf('function latestPrinterMonitorEvent(');
  vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), ctx);
  assert.equal(ctx.latestPrinterMonitorEvent(), fresh);
});
