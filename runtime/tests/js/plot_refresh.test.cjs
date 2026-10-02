const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/planning.js', 'utf8');
function install(context, names) {
  vm.createContext(context);
  for (const name of names) {
    const index = source.indexOf(`function ${name}(`);
    const start = source.slice(index - 6, index) === 'async ' ? index - 6 : index;
    vm.runInContext(source.slice(start, source.indexOf('\n}', index) + 2), context);
  }
  return context;
}
test('GP plot notifications coalesce in flight and re-read a newer completed step', async () => {
  let release, calls = 0, trailing = 0, run = 'r';
  const delivered = [];
  const context = install({
    liveCurrentRunId: () => run,
    fetchJsonOrThrowWithTimeout: (url, options, timeout) => {
      assert.equal(url, '/api/bo/config?visualization_only=true');
      assert.equal(timeout, 10000);
      calls++;
      return new Promise(resolve => { release = resolve; });
    },
    updateLiveLhsVisualization: () => false,
    updateLiveBoVisualizationCards: payload => { delivered.push(payload.step); return true; },
    scheduleLiveBoVisualizationHydration: () => { trailing++; },
  }, ['hydrateLiveBoVisualization']);
  const first = context.hydrateLiveBoVisualization();
  const second = context.hydrateLiveBoVisualization();
  const third = context.hydrateLiveBoVisualization();
  assert.equal(calls, 1);
  release({run_id: 'r', recent_visualization: {step: 8}});
  await Promise.all([first, second, third]);
  assert.deepEqual(delivered, [8]);
  assert.equal(trailing, 1);
  const next = context.hydrateLiveBoVisualization();
  release({run_id: 'r', recent_visualization: {step: 9}});
  await next;
  assert.deepEqual(delivered, [8, 9]);
  const old = context.hydrateLiveBoVisualization();
  run = 'new-run';
  release({run_id: 'r', recent_visualization: {step: 10}});
  assert.equal(await old, false);
  assert.deepEqual(delivered, [8, 9]);
});
test('ANL archive/report latency does not block fresh session paint, and old reads cannot repaint', async () => {
  const releases = [], paints = [];
  let serial = 0;
  const context = install({
    window: {}, liveSelectedAgent: 'analysis', liveRefreshInFlight: null, liveSetupTransportVersion: 0,
    liveLastSession: {}, liveLastSnapshot: {}, liveGuardianStatus: {}, liveAgentManifestRequestGeneration: 1,
    shouldFreezeCompletedTestRun: () => false, markLiveSyncRefreshStart: () => {},
    refreshLiveAgentManifest: async () => {}, ensurePlanningSessionId: () => 'session',
    fetch: async () => ({ok: true, json: async () => ({state: {run_id: 'r', loop_count: serial++}, serial})}),
    applyPlanningSession: session => { context.liveLastSession = session; paints.push(`compact-${session.serial}`); },
    hydrateLiveSelectedAgentReport: session => new Promise(resolve => releases.push(() => {
      session.ownerReport = {}; resolve(session);
    })),
    liveOwnerReportForSession: session => session.ownerReport,
    invalidateLiveCenterRender: () => {}, renderLiveRuntime: session => paints.push(`full-${session.serial}`),
    markLiveSyncComplete: () => {}, refreshPlanningAuxiliaryState: () => {},
    markLiveSyncError: err => { throw err; },
  }, ['scheduleLiveOwnerReportHydration', 'refreshPlanningState']);
  await context.refreshPlanningState();
  assert.equal(releases.length, 1, 'report requests cannot pile up behind compact refreshes');
  assert.deepEqual(paints, ['compact-1']);
  await context.refreshPlanningState();
  releases[0]();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(paints, ['compact-1', 'compact-2']);
  releases[1]();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(paints, ['compact-1', 'compact-2', 'full-2']);
});
