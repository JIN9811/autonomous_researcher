const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const model = require('../../web/static/equipment_agentic_task_model.js');
const source = fs.readFileSync('web/static/planning.js', 'utf8');

function load(context, names) {
  for (const name of names) {
    const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
    assert.ok(start >= 0, name);
    vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
  }
}

function harness() {
  let execution = { run_id: 'r1', flow_execution_id: 'f1', updated_at: 't1', active_block: 'start_test' };
  const requests = [], renders = [];
  const c = vm.createContext({
    window: { ATREquipmentAgenticTaskModel: model, setTimeout, clearTimeout }, Date, AbortController,
    liveEquipmentRuntimeSnapshot: null, liveEquipmentSkillFlowSnapshot: null,
    liveEquipmentRuntimeRefreshInFlight: null, liveEquipmentRuntimeRefreshSeq: 0,
    liveEquipmentRuntimeRefreshPending: false,
    liveEquipmentRuntimeRefreshedAt: 0, liveEquipmentRuntimeError: '',
    liveLastSession: { state: { run_id: 'r1', current_experiment_spec: { specimen_id: 's1' } } },
    liveCurrentRunId: () => c.liveLastSession.state.run_id,
    activeEquipmentProfileId: () => 'utm_windows_v1',
    fetchJsonOrThrow: async url => {
      requests.push(url);
      if (url.includes('/skill-flow')) return { flow: { version: 3 }, execution: structuredClone(execution) };
      if (url.includes('/runtime/current')) return { execution: { status: 'running' } };
      return { connection: { status: 'ready' } };
    },
    invalidateLiveCenterRender: () => {},
    renderLiveRuntime: () => renders.push(c.liveEquipmentRuntimeSnapshot?.canonicalSkillFlowExecution?.updated_at),
  });
  load(c, ['fetchJsonOrThrowWithTimeout', 'refreshEquipmentRuntimeSnapshot', 'ensureEquipmentRuntimeSnapshot', 'equipmentCycleContext']);
  return { c, requests, renders, setExecution: value => { execution = value; } };
}

test('process refresh advances the cached checkpoint without a tab click and skips unchanged repaint', async () => {
  const h = harness();
  h.c.ensureEquipmentRuntimeSnapshot();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  h.setExecution({ run_id: 'r1', flow_execution_id: 'f1', updated_at: 't2', active_block: 'save_raw_data' });
  h.c.ensureEquipmentRuntimeSnapshot();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  assert.equal(h.c.liveEquipmentRuntimeSnapshot.canonicalSkillFlowExecution.active_block, 'save_raw_data');
  h.c.ensureEquipmentRuntimeSnapshot();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  assert.deepEqual(h.renders, ['t1', 't2']);
  assert.equal(h.requests.filter(url => url.includes('/windows/config')).length, 1);
});

test('in-flight reads coalesce and an old run response cannot overwrite the new run', async () => {
  const h = harness();
  let release;
  const read = h.c.fetchJsonOrThrow;
  h.c.fetchJsonOrThrow = url => url.includes('/skill-flow')
    ? new Promise(resolve => { release = () => resolve({ execution: { run_id: 'r1' } }); }) : read(url);
  h.c.ensureEquipmentRuntimeSnapshot();
  const pending = h.c.liveEquipmentRuntimeRefreshInFlight;
  h.c.ensureEquipmentRuntimeSnapshot();
  assert.equal(h.c.liveEquipmentRuntimeRefreshInFlight, pending);
  h.c.liveLastSession.state.run_id = 'r2';
  release();
  await pending;
  assert.equal(h.c.liveEquipmentRuntimeSnapshot, null);
  if (h.c.liveEquipmentRuntimeRefreshInFlight) {
    release();
    await h.c.liveEquipmentRuntimeRefreshInFlight;
  }
});

test('a terminal update during an in-flight read gets a trailing refresh', async () => {
  const h = harness();
  h.c.ensureEquipmentRuntimeSnapshot();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  let release;
  const read = h.c.fetchJsonOrThrow;
  h.c.fetchJsonOrThrow = () => new Promise(resolve => { release = () => resolve({ execution: { run_id: 'r1', updated_at: 't2', status: 'running' } }); });
  h.c.ensureEquipmentRuntimeSnapshot();
  const pending = h.c.liveEquipmentRuntimeRefreshInFlight;
  h.setExecution({ run_id: 'r1', updated_at: 't3', status: 'completed', terminal: '__complete__' });
  h.c.ensureEquipmentRuntimeSnapshot();
  h.c.fetchJsonOrThrow = read;
  release();
  await pending;
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  assert.equal(h.c.liveEquipmentRuntimeSnapshot.canonicalSkillFlowExecution.terminal, '__complete__');
});

test('a failed refresh retains evidence and retries on the next process update', async () => {
  const h = harness();
  h.c.ensureEquipmentRuntimeSnapshot();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  const read = h.c.fetchJsonOrThrow;
  h.c.fetchJsonOrThrow = async () => { throw new Error('temporarily unavailable'); };
  h.c.ensureEquipmentRuntimeSnapshot();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  assert.match(h.c.liveEquipmentRuntimeError, /temporarily unavailable/);
  assert.equal(h.c.liveEquipmentRuntimeSnapshot.canonicalSkillFlowExecution.updated_at, 't1');
  h.c.fetchJsonOrThrow = read;
  h.c.ensureEquipmentRuntimeSnapshot();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  assert.equal(h.c.liveEquipmentRuntimeError, '');
});

for (const [terminal, outcome, expected] of [['__complete__', 'completed', 'complete'], ['__blocked__', 'failed', 'blocked']]) {
  test(`same-run ${terminal} preserves step evidence even when the compact report has no blocks`, () => {
    const { c } = harness();
    const flow = { run_id: 'r1', terminal, workflow_agentic_task: { task_id: 'run_utm_compression_cycle', specimen_id: 's1', block_order: ['start_test'] }, transitions: [{ block_id: 'start_test', phase: 'skill', outcome }] };
    const cycle = c.equipmentCycleContext({ equipment: { status: 'completed' }, skillFlowExecution: flow });
    assert.equal(model.progressSteps(cycle)[0]?.status, expected);
    flow.run_id = 'old-run';
    assert.equal(c.equipmentCycleContext({ skillFlowExecution: flow }).available, false);
  });
}

test('authoritative session updates refresh equipment while another agent page is selected', () => {
  const h = harness();
  const c = h.c;
  Object.assign(c, {
    liveSelectedAgent: 'analysis', liveLastSnapshot: {}, planningSessionId: '',
    planningStageLabel: null, planningCycleLabel: null, planningRunDetail: null,
    planningHistorySessionId: '', planningMessagesCache: [], queryGoal: '',
    resetLiveRunScopedStateForAuthoritativeSession: () => false,
    liveRunningFlag: () => true, formatPlanningCycleLabel: () => '1', liveRunTopbarLabel: () => '',
    mergePlanningMessages: () => [],
  });
  for (const name of ['persistPlanningSessionId', 'openPendingOperatorTeleopHandoff', 'syncLiveBoVisualizationFromState', 'setLiveBackendPlanningBusy', 'setPlanningDot', 'setCompactTextWithTitle', 'scheduleLiveMissionMarquee', 'renderSpecSummary', 'resetPlanningMessageDisplayState', 'renderPlanningMessages', 'persistLivePlanningCache']) c[name] = () => {};
  load(c, ['applyPlanningSession']);
  c.applyPlanningSession(c.liveLastSession);
  assert.ok(c.liveEquipmentRuntimeRefreshInFlight, 'state receipt must initiate progress synchronization');
});

test('running equipment checkpoints refresh independently of slow planning synchronization', async () => {
  const h = harness();
  load(h.c, ['refreshActiveEquipmentProcess']);
  h.c.liveLastSession.state.agent_status = { equipment_agent: { state: 'running' } };
  h.c.liveSelectedAgent = 'analysis';
  h.c.refreshActiveEquipmentProcess();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  assert.equal(h.c.liveEquipmentRuntimeSnapshot.canonicalSkillFlowExecution.updated_at, 't1');
  h.c.liveEquipmentRuntimeRefreshedAt = Date.now() - 3000;
  h.setExecution({ run_id: 'r1', updated_at: 't2', active_block: 'save_raw_data' });
  h.c.refreshActiveEquipmentProcess();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  assert.equal(h.c.liveEquipmentRuntimeSnapshot.canonicalSkillFlowExecution.active_block, 'save_raw_data');
  const requests = h.requests.length;
  h.c.refreshActiveEquipmentProcess();
  assert.equal(h.requests.length, requests, 'do not poll before the cadence expires');
  h.c.liveLastSession.state.agent_status.equipment_agent.state = 'done';
  h.c.liveEquipmentRuntimeRefreshedAt = 0;
  h.c.refreshActiveEquipmentProcess();
  assert.equal(h.requests.length, requests, 'no active polling after completion');
});

test('the final failed read retries on the timer even after the completed session freezes', async () => {
  const h = harness();
  load(h.c, ['refreshActiveEquipmentProcess']);
  h.c.ensureEquipmentRuntimeSnapshot();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  const read = h.c.fetchJsonOrThrow;
  h.c.liveLastSession.state.agent_status = { equipment_agent: { state: 'done' } };
  h.c.fetchJsonOrThrow = async () => { throw new Error('temporary 503'); };
  h.c.ensureEquipmentRuntimeSnapshot();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  h.setExecution({ run_id: 'r1', terminal: '__complete__', updated_at: 't3' });
  h.c.fetchJsonOrThrow = read;
  h.c.liveEquipmentRuntimeRefreshedAt = Date.now() - 3000;
  h.c.refreshActiveEquipmentProcess();
  await h.c.liveEquipmentRuntimeRefreshInFlight;
  assert.equal(h.c.liveEquipmentRuntimeSnapshot.canonicalSkillFlowExecution.terminal, '__complete__');
  assert.equal(h.c.liveEquipmentRuntimeError, '');
});

test('an unresponsive progress read is aborted and releases the synchronization lock', async () => {
  const h = harness(), timers = [];
  h.c.window.setTimeout = fn => { timers.push(fn); return timers.length; };
  h.c.window.clearTimeout = () => {};
  h.c.fetchJsonOrThrow = (_url, options = {}) => new Promise((_resolve, reject) => {
    options.signal?.addEventListener('abort', () => reject(new Error('request timed out')));
  });
  h.c.ensureEquipmentRuntimeSnapshot();
  const pending = h.c.liveEquipmentRuntimeRefreshInFlight;
  assert.equal(timers.length, 3, 'all initial reads need a deadline');
  timers.forEach(expire => expire());
  await pending;
  assert.equal(h.c.liveEquipmentRuntimeRefreshInFlight, null);
  assert.match(h.c.liveEquipmentRuntimeError, /timed out/);
});
