const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require('node:path').join(__dirname, '../../web/static/planning.js'), 'utf8');
const resources = () => ({updated_at: '2026-09-14T10:00:00Z',
  ram: {used_gb: 60, total_gb: 120},
  gpu: {aggregate: {utilization_percent: 12, memory_used_gb: 40, memory_total_gb: null}}});

test('utilization colors progress independently from green through yellow to red', () => {
  const ctx = harness();
  for (const [percent,color] of [[0,'rgb(52,211,153)'],[50,'rgb(250,204,21)'],[100,'rgb(248,113,113)']]) {
    ctx.liveLastSnapshot.system_resources.gpu.aggregate.utilization_percent = percent;
    ctx.renderLiveResourceStatus();
    assert.ok(ctx.liveResourceChip.innerHTML.includes(`color:${color}">GPU`));
    assert.ok(ctx.liveResourceChip.innerHTML.includes('color:rgb(250,204,21)">RAM'));
  }
  ctx.liveResourceRefreshFailed = true;
  ctx.renderLiveResourceStatus();
  assert.ok(ctx.liveResourceChip.innerHTML.includes('color:#94a3b8'));
});

function harness() {
  const noop = () => {};
  const ctx = vm.createContext({
    liveResourceChip: {textContent: '', title: '', classList: {toggle: noop}},
    liveDeviceStrip: {innerHTML: '', dataset: {}, querySelectorAll: () => []}, liveLastSnapshot: {system_resources: resources()},
    liveLastSession: {}, liveGuardianStatus: null, liveRefreshInFlight: null,
    document: {hidden: false}, refreshLivePrinterMonitorStatus: async () => {},
    liveSetupTransportVersion: 0, liveAgentManifestRequestGeneration: 0,
    liveResourceRefreshInFlight: null, liveResourceRefreshedAt: 0, liveResourceRefreshFailed: false,
    now: 10000, Date: {now: () => ctx.now}, requests: [], fail: false,
    fetchJsonOrThrowWithTimeout: async url => {
      ctx.requests.push(url);
      if (ctx.fail) throw new Error('telemetry unavailable');
      return {system_resources: resources()};
    },
    renderBridgeContractDeviceCards: () => [], liveBridgeContracts: () => [],
    renderResourceStatusCard: () => '', renderPrinterDeviceStatusCard: () => '',
    renderDeviceStatusCard: () => '', renderUtmRuntimeDeviceCard: () => '', latestRuntimeEvent: () => null,
    fetch: async () => ({ok: true, json: async () => ({state: {stage: 'idle'}, runtime: {}})}),
    refreshLiveAgentManifest: async () => {}, hydrateLiveSelectedAgentReport: async () => {},
    ensurePlanningSessionId: () => 'fixture', shouldFreezeCompletedTestRun: () => true,
    markLiveSyncRefreshStart: noop, markLiveSyncComplete: noop, markLiveSyncError: e => {throw e;},
    applyPlanningSession: noop,
    tickLiveRuntimeClock: noop, updateLiveConnectionChips: noop, updateVisionSpecimenCountdowns: noop,
    refreshActiveEquipmentProcess: noop, refreshLivePLCStatus: async () => {},
    refreshLiveAnalysisFemEvidence: async () => {}, liveSelectedAgent: 'orchestrator',
    setInterval: fn => {ctx.tick = fn;},
  });
  for (const name of ['renderRuntimeValue', 'setCompactTextWithTitle', 'renderLiveResourceStatus',
    'refreshLiveResources', 'renderDeviceStrip', 'refreshPlanningState']) {
    const start = source.search(new RegExp('(?:async )?function ' + name + '\\('));
    if (start >= 0) vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), ctx);
  }
  const interval = source.indexOf('setInterval(() => {\n  tickLiveRuntimeClock();');
  vm.runInContext(source.slice(interval, source.indexOf('}, 1000);', interval) + 9), ctx);
  return ctx;
}

test('top resource chip shows compact GPU/RAM percentages without duplicated labels', () => {
  const ctx = harness();
  ctx.renderDeviceStrip({});
  assert.equal(ctx.liveResourceChip.textContent, 'GPU 12% / RAM 50%');
  assert.match(ctx.liveResourceChip.title, /40\/n\/a GB/); // shared-memory GPU has no dedicated total
});

test('missing telemetry is unavailable, never a fictitious zero percent', () => {
  const ctx = harness();
  ctx.liveLastSnapshot.system_resources = {gpu: {aggregate: {utilization_percent: null}}, ram: {used_gb: null, total_gb: 120}};
  ctx.renderDeviceStrip({});
  assert.equal(ctx.liveResourceChip.textContent, 'GPU - / RAM -');
});

test('resource header renders even without the optional device strip', () => {
  const ctx = harness();
  ctx.liveDeviceStrip = null;
  ctx.renderDeviceStrip({});
  assert.equal(ctx.liveResourceChip.textContent, 'GPU 12% / RAM 50%');
});

test('session refresh preserves host telemetry rather than replacing it with empty session data', async () => {
  const ctx = harness();
  await ctx.refreshPlanningState();
  ctx.renderDeviceStrip({});
  assert.equal(ctx.liveResourceChip.textContent, 'GPU 12% / RAM 50%');
});

test('timer refreshes telemetry even for a frozen completed run, throttles, and recovers after failure', async () => {
  const ctx = harness();
  const tick = async () => {ctx.tick(); await new Promise(resolve => setImmediate(resolve));};
  await tick();
  assert.deepEqual(ctx.requests, ['/api/devices/state']);
  assert.equal(ctx.liveResourceChip.textContent, 'GPU 12% / RAM 50%');
  await tick();
  assert.equal(ctx.requests.length, 1);
  ctx.now += 5000;
  ctx.fail = true;
  await tick();
  assert.equal(ctx.requests.length, 2);
  assert.match(ctx.liveResourceChip.textContent, /GPU 12% \/ RAM 50%.*\*/);
  assert.match(ctx.liveResourceChip.title, /cached/i);
  ctx.now += 5000;
  ctx.fail = false;
  await tick();
  assert.equal(ctx.requests.length, 3);
  assert.equal(ctx.liveResourceChip.textContent, 'GPU 12% / RAM 50%');
});

test('a slow telemetry request is not duplicated and legitimate zero utilization remains visible', async () => {
  const ctx = harness();
  let resolve;
  ctx.fetchJsonOrThrowWithTimeout = url => {
    ctx.requests.push(url);
    return new Promise(done => {resolve = done;});
  };
  const first = ctx.refreshLiveResources();
  ctx.now += 9000;
  const second = ctx.refreshLiveResources();
  assert.deepEqual(ctx.requests, ['/api/devices/state']);
  const zero = resources();
  zero.gpu.aggregate.utilization_percent = 0;
  zero.ram.used_gb = 0;
  resolve({system_resources: zero});
  await Promise.all([first, second]);
  assert.equal(ctx.liveResourceChip.textContent, 'GPU 0% / RAM 0%');
});

test('malformed telemetry preserves the last successful reading and marks it cached', async () => {
  const ctx = harness();
  ctx.fetchJsonOrThrowWithTimeout = async () => ({});
  await ctx.refreshLiveResources();
  assert.equal(ctx.liveResourceChip.textContent, 'GPU 12% / RAM 50% *');
  assert.match(ctx.liveResourceChip.title, /cached/);
});
