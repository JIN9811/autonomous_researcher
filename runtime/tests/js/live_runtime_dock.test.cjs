const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../web/static/planning.js'), 'utf8');

function harness() {
  const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  const ctx = vm.createContext({
    liveLastSnapshot: {}, liveLastSession: {}, liveApprovals: {pending: []},
    liveBottomTab: 'events', liveBridgeRegistry: null,
    liveRunningFlag: (s, _snapshot, state) => Boolean(s.is_running || state.is_running),
    liveAgentLabel: id => ({design: 'Design', equipment: 'Lab Equipment', analysis: 'Analysis'}[id] || id),
    agentIdFromStage: id => id, escapeHtml: escape, compactText: value => value,
    liveMissionProgressSlim: {innerHTML: ''}, liveEventCount: {}, liveTimelineDetailPanel: null,
    liveTimelineStrip: {innerHTML: ''}, liveSelectedEventKey: '',
    renderTimelineFilters: () => {},
    timelineSourceEvents: () => [], filteredTimelineEvents: () => [],
    eventTimelineKind: e => e.kind, eventStableKey: e => e.id,
    formatTime: v => v, agentIdFromEvent: e => e.agent,
    bridgeContractSafeActions: b => (b.actions || []).filter(a => a.read_only),
    bridgeContractWorkspaceHandoffActions: () => [],
  });
  for (const name of ['liveContractStageLabel', 'liveDockSummary', 'renderLiveMissionProgressSlim', 'liveBridgeContracts',
    'bridgeContractStatus', 'bridgeContractActionSummary', 'renderBridgeContractDeviceCards',
    'formatDockTime', 'renderTimelinePanels', 'setLiveBottomTab']) {
    const start = source.indexOf(`function ${name}(`);
    if (start >= 0) vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), ctx);
  }
  return ctx;
}
test('dock time uses English AM/PM and rows have one centered track',()=>{
  const ctx=harness();
  assert.match(ctx.formatDockTime('2026-09-14T21:35:53'), /09:35:53 PM/);
  assert.match(ctx.formatDockTime('2026-09-14T09:35:53'), /09:35:53 AM/);
  const css=fs.readFileSync(require('node:path').join(__dirname,'../../web/static/live_runtime_dock.css'),'utf8');
  assert.match(css,/grid-template-rows:\s*minmax\(0,\s*1fr\)\s*!important/);
});

function printingState() {
  return {stage:'vision', run_id:'r', loop_count:1, current_experiment_spec:{specimen_id:'s'},
    agent_status:{vision_agent:{run_id:'r',loop_id:0,state:'idle',success:true}},
    run_metadata:{specimen_execution:{run_id:'r',loop_id:1,specimen_id:'s',state:'running'},
      specimen_result:{run_id:'r',loop_id:1,specimen_id:'s',printer_path:'physical_print',
        print_result:{published:true}}}};
}

test('Contract shows SPC during this cycle physical print wait without changing execution stage', () => {
  const ctx=harness(); const state=printingState(); const before=JSON.stringify(state);
  assert.equal(ctx.liveContractStageLabel(state),'specimen');
  assert.equal(JSON.stringify(state),before);
});

test('Contract preserves Vision after job completion or actual Vision invocation, and ignores stale evidence', () => {
  const ctx=harness();
  for (const fault of ['completed','vision_running','vision_finished','old_run','old_cycle','other_specimen','virtual','unpublished']) {
    const state=printingState();
    const meta=state.run_metadata;
    if(fault==='completed') meta.specimen_result.printer_completion_wait={status:'complete',run_id:'r',loop_id:1,specimen_id:'s',completion_scope:'printer_job_only'};
    if(fault==='vision_running') state.agent_status.vision_agent={run_id:'r',loop_id:1,state:'running',success:null};
    if(fault==='vision_finished') state.agent_status.vision_agent={run_id:'r',loop_id:1,state:'idle',success:true};
    if(fault==='old_run') meta.specimen_execution.run_id='old';
    if(fault==='old_cycle') meta.specimen_execution.loop_id=0;
    if(fault==='other_specimen') meta.specimen_result.specimen_id='old';
    if(fault==='virtual') meta.specimen_result.printer_path='virtual';
    if(fault==='unpublished') meta.specimen_result.print_result.published=false;
    assert.equal(ctx.liveContractStageLabel(state),'vision',fault);
  }
  const state=printingState(); state.stage='equipment';
  assert.equal(ctx.liveContractStageLabel(state),'equipment');
});

test('idle dock never presents a historical recommendation or selected report as the active handoff', () => {
  const ctx = harness();
  const result = ctx.liveDockSummary({state: {stage: 'idle', run_metadata: {
    latest_orchestrator_control_plane: {next_action: {next_stage: 'design'}},
    orchestrator_handoff_packets: [{from: 'bo', to: 'guardian'}],
  }}});
  assert.equal(result.current, 'Awaiting experiment');
  assert.equal(result.next, 'Not scheduled');
  assert.equal(result.attention, 0);
});

test('running dock uses current state and explicitly planned next stage, not last completed handoff', () => {
  const ctx = harness();
  const result = ctx.liveDockSummary({is_running: true, state: {stage: 'equipment', run_metadata: {
    latest_orchestrator_control_plane: {next_action: {next_stage: 'analysis'}},
  }}});
  assert.equal(result.current, 'Lab Equipment');
  assert.equal(result.next, 'Analysis');
  assert.equal(result.phase, 'Running');
});

test('terminal run suppresses next-stage recommendations', () => {
  const ctx = harness();
  for (const stage of ['complete', 'error', 'stopped']) {
    const result = ctx.liveDockSummary({state: {stage, run_metadata: {
      latest_orchestrator_control_plane: {next_action: {next_stage: 'design'}},
    }}});
    assert.equal(result.next, 'Not scheduled');
  }
});

test('dock advances past the current entry in the same-cycle planned route without changing the plan', () => {
  const ctx = harness();
  for (const [stage, next] of [['knowledge', 'bo'], ['equipment', 'analysis'], ['design', 'specimen']]) {
    const control = {run_id: 'r', loop_id: 2, stage,
      next_action: {next_stage: stage}, route_state: {next_recommended_stage: stage,
        route: [{stage, status: 'active'}, {stage: next, status: 'planned'}]}};
    const before = JSON.stringify(control);
    const session = {is_running: true, state: {run_id: 'r', loop_count: 2, stage,
      run_metadata: {latest_orchestrator_control_plane: control}}};
    ctx.renderLiveMissionProgressSlim(session);
    assert.equal(ctx.liveDockSummary(session).next, next === 'analysis' ? 'Analysis' : next);
    assert.equal(JSON.stringify(control), before);
    assert.match(ctx.liveMissionProgressSlim.innerHTML, /live-dock-next/);
  }
});

test('missing successor and stale run/cycle plans never repeat Current as Next', () => {
  const ctx = harness();
  for (const fault of ['no_route', 'last_entry', 'other_run', 'other_cycle', 'other_experiment']) {
    const control = {run_id: 'r', experiment_id: 'e', loop_id: 2, stage: 'knowledge',
      next_action: {next_stage: 'knowledge'}, route_state: {route: [{stage:'knowledge'}, {stage:'bo'}]}};
    if (fault === 'no_route') delete control.route_state;
    if (fault === 'last_entry') control.route_state.route.pop();
    if (fault === 'other_run') control.run_id = 'old';
    if (fault === 'other_cycle') control.loop_id = 1;
    if (fault === 'other_experiment') control.experiment_id = 'old';
    assert.equal(ctx.liveDockSummary({state: {run_id:'r', experiment_id:'e', loop_count:2,
      stage:'knowledge', run_metadata:{latest_orchestrator_control_plane:control}}}).next, 'Not scheduled');
  }
});

test('canonical planning pending input is visible without assuming experiment execution', () => {
  const ctx = harness();
  const result = ctx.liveDockSummary({state: {stage: 'idle', pending_request: {kind: 'research_input'}}});
  assert.equal(result.current, 'Awaiting input');
  assert.equal(result.phase, 'Waiting');
  assert.equal(result.attention, 1);
});

test('no health observation is unknown, not connected merely because an endpoint exists', () => {
  const ctx = harness();
  assert.equal(ctx.bridgeContractStatus({health_endpoint: '/api/status'}), 'unknown');
  assert.equal(ctx.bridgeContractStatus({health: {status: 'connected'}}), 'ready');
});

test('bridge discovery uses the existing device snapshot and honors an explicitly empty graph list', () => {
  const ctx = harness();
  ctx.liveBridgeRegistry = [{id: 'printer', label: 'Printer', workspace: '/printer'}];
  assert.equal(ctx.liveBridgeContracts().length, 1);
  assert.equal(ctx.liveBridgeContracts({runtime_ide_contract: {device_bridges: []}}).length, 0);
});

test('bridge details fold endpoints away while retaining existing action routing attributes', () => {
  const ctx = harness();
  const [card] = ctx.renderBridgeContractDeviceCards([{id: 'printer', label: 'Printer', workspace: '/printer',
    actions: [{id: 'health_check', read_only: true, endpoint: '/api/printer/status', method: 'GET'}]}]);
  assert.match(card, /<details/);
  assert.match(card, /<summary/);
  assert.match(card, /data-bridge-action="open_workspace"/);
  assert.match(card, /data-bridge-action="health_check"/);
  assert.match(card, /data-bridge-endpoint="\/api\/printer\/status"/);
});

test('events are readable newest-first rows with agent and unchanged trace keys', () => {
  const ctx = harness();
  const events = [{id: 'old', agent: 'design', kind: 'info', ts: '10:00', message: 'Candidate ready'},
    {id: 'new', agent: 'analysis', kind: 'artifact', ts: '10:01', message: 'Analysis saved'}];
  ctx.timelineSourceEvents = ctx.filteredTimelineEvents = () => events;
  ctx.renderTimelinePanels();
  const html = ctx.liveTimelineStrip.innerHTML;
  assert.ok(html.indexOf('data-event-key="new"') < html.indexOf('data-event-key="old"'));
  assert.match(html, /live-event-agent[^>]*>Analysis</);
  assert.match(html, /Analysis saved/);
});

test('dock tabs switch panel visibility and ARIA selection without invoking runtime actions', () => {
  const ctx = harness();
  const tabs = ['events', 'devices'].map(name => ({dataset: {dockTab: name}, attrs: {},
    setAttribute(k, v) {this.attrs[k] = v;}, classList: {toggle() {}}, tabIndex: 0}));
  const panels = ['events', 'devices'].map(name => ({dataset: {dockPanel: name}, hidden: false}));
  ctx.document = {querySelectorAll: selector => selector === '[data-dock-tab]' ? tabs : panels};
  ctx.setLiveBottomTab('devices');
  assert.equal(panels[0].hidden, true);
  assert.equal(panels[1].hidden, false);
  assert.equal(tabs[1].attrs['aria-selected'], 'true');
  ctx.setLiveBottomTab('events');
  assert.equal(panels[0].hidden, false);
  assert.equal(panels[1].hidden, true);
});
