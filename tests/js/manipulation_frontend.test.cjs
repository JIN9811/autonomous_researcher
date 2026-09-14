const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = require('node:path').resolve(__dirname, '../..');

function sharedContext() {
  const context = vm.createContext({window: {}, URL, Promise, liveSelectedReportSectionTitle: ''});
  const source = fs.readFileSync(`${root}/web/static/planning.js`, 'utf8');
  for (const name of ['escapeHtml', 'renderRuntimeValue', 'normalizeDisplayText', 'compactText', 'renderDashboardValue',
    'runtimeRows', 'renderReportList', 'reportSectionKey', 'dashboardSectionClass', 'renderDashboardCard',
    'backendField', 'latestReportPayload', 'latestManipulationReport', 'latestRobotTaskResult']) {
    const start = source.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `${name} exists`);
    vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
  }
  return context;
}

test('installed Manipulation renders real report evidence and preserves eight telemetry card consumers', async () => {
  const context = sharedContext();
  vm.runInContext(fs.readFileSync(`${root}/web/static/agent_module_host.js`, 'utf8'), context);
  const asset = `${root}/agents/manipulation/frontend/live_report.js`;
  assert.ok(fs.existsSync(asset), 'Manipulation must own its frontend composition');
  let loads = 0;
  const host = context.window.AX4LABAgentModuleHost.createModuleHost({globalObject: context.window,
    loadAsset: async () => { loads++; vm.runInContext(fs.readFileSync(asset, 'utf8'), context); }});
  const manifest = {id: 'manipulation', implementation: {version: '1.0.0', frontend: {
    asset_url: '/module-assets/manipulation/live_report.js', namespace: 'AX4LABManipulationUI', factory: 'createFrontend'}}};
  assert.equal(host.get('manipulation'), null);
  assert.deepEqual(Array.from((await host.reconcile([manifest], context)).errors), []);
  const ui = host.get('manipulation');
  await host.reconcile([manifest], context);
  assert.equal(host.get('manipulation'), ui);
  assert.equal(loads, 1);
  assert.equal(ui.renderReport({}), '');
  for (const [status, stage, completed, reason] of [
    ['running', 'approach', ['observe'], 'Vision verification required'],
    ['completed', 'place', ['observe', 'approach', 'place'], 'Verified handoff'],
    ['blocked', 'observe', [], 'operator confirmation required'],
  ]) {
    const report = {state: {run_metadata: {robot_task_result: {task_id: 'transfer_to_utm', handoff_status: status},
      manipulation_report: {task: {task_id: 'transfer_to_utm', specimen_id: 'specimen-current'},
        policy_plan: {policy_ref: 'registered-policy'}, preflight: {robot_ready: false, blocking_reasons: status === 'blocked' ? [reason] : []},
        stage_machine: {current_stage: stage, completed_stages: completed, stage_taxonomy: ['observe', 'approach', 'place']},
        rollout_runtime: {status, session_id: 'rollout-current', duration_s: 0, events: [{step: stage, status}]},
        decision: {reason}, knowledge_payload: {evidence_paths: ['runs/current/action.jsonl']}}}}};
    const details = ui.renderReport(report);
    for (const value of [reason, stage, status, `${completed.length}/3`, 'specimen-current', 'registered-policy', 'rollout-current', 'runs/current/action.jsonl']) assert.ok(details.includes(value), value);
    assert.match(details, /duration_s<\/span>\s*<strong>0<\/strong>/);
    assert.match(details, /robot_ready<\/span>\s*<strong>false<\/strong>/);
    assert.doesNotMatch(details, /progress_score|failure_precursor|nominal/);
    const html = ui.renderDashboard(report, status, 'Manipulation', {});
    const names = Array.from(html.matchAll(/<h4>(.*?)<\/h4>/g), match => match[1]);
    assert.deepEqual(names, ['Live Robot Pose', 'Policy Tracking', 'Motion &amp; Grasp', 'Completion &amp; Handoff', 'Run Metrics', 'Runtime Execution', 'Interlocks']);
    for (const label of ['Grasp diagnostics', 'Home thresholds', 'Result evidence']) assert.ok(html.includes(`<div class="ar-man-visible-section"><h5>${label}</h5>`));
    assert.doesNotMatch(html, /<summary>(Task counts|Grasp counts|Grasp diagnostics|Home thresholds|Result evidence)<\/summary>/);
    assert.match(html, /ar-man-grasp-single-column/);
    for (const selector of ['data-atr-robot-pose', 'data-atr-joint-selector', 'data-atr-grasp-measured', 'data-atr-runtime-field="execution.run_id"', 'data-atr-runtime-step="ready_for_equipment"', 'data-utm-clear-verification-step']) assert.ok(html.includes(selector));
    assert.match(html, /data-atr-runtime-gate="camera_lease" data-status="unknown"/);
    // Bind the real shared telemetry updater to fields from the owner markup.
    const fields = new Map(Array.from(html.matchAll(/<strong data-atr-runtime-field="([^"]+)">([^<]*)<\/strong>/g),
      match => [match[1], {dataset: {atrRuntimeField: match[1]}, textContent: match[2]}]));
    const telemetry = vm.createContext({document: {querySelectorAll: selector => {
      const prefix = selector.match(/\^="([^"]+)"/)[1];
      return Array.from(fields.values()).filter(node => node.dataset.atrRuntimeField.startsWith(prefix));
    }}});
    const viewerSource = fs.readFileSync(`${root}/web/frontend/omx_telemetry_viewer/src/index.js`, 'utf8');
    for (const name of ['setNodeTextIfChanged', 'runtimeDisplayValue', 'applyRuntimeFields']) {
      const start = viewerSource.indexOf(`function ${name}(`);
      vm.runInContext(viewerSource.slice(start, viewerSource.indexOf('\n}', start) + 2), telemetry);
    }
    telemetry.applyRuntimeFields('execution', {run_id: 'run-current', runtime_status: status, elapsed_s: 1.5});
    telemetry.applyRuntimeFields('result', {status, reason});
    telemetry.applyRuntimeFields('metrics', {sample_count: 0, duration_s: 0, effective_action_rate_hz: 20});
    for (const [key, value] of [['execution.run_id', 'run-current'], ['execution.runtime_status', status],
      ['execution.elapsed_s', '1.5 s'], ['result.reason', reason], ['result.status', status],
      ['metrics.sample_count', '0'], ['metrics.duration_s', '0.0 s'], ['metrics.effective_action_rate_hz', '20.0 Hz']]) {
      assert.equal(fields.get(key)?.textContent, value, key);
    }
  }
  context.liveAgentModuleHost = host;
  const source = fs.readFileSync(`${root}/web/static/planning.js`, 'utf8');
  for (const name of ['renderManipulationReportDetails', 'renderManipulationDashboardCards', 'renderAgentSpecializedDashboardSections']) {
    const start = source.indexOf(`function ${name}(`);
    vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
  }
  await host.reconcile([], context);
  assert.equal(host.get('manipulation'), null);
  assert.equal(context.renderManipulationDashboardCards({}, 'running', 'Manipulation', {}), '');
  assert.equal(context.renderManipulationReportDetails({}), '');
  Object.assign(context, {activeModuleDescriptorFallback: () => '', liveSelectedAgent: 'manipulation', agentSpecificReportProfile: () => ({}),
    liveAgentNeedsChatPanel: () => false, liveAgentRendererProfile: () => ({id: 'manipulation', dashboardAgent: 'manipulation'})});
  assert.equal(context.renderAgentSpecializedDashboardSections({}, {}, 'running', 'Manipulation'), '');
  await host.reconcile([manifest], context);
  assert.notEqual(host.get('manipulation'), ui);
});

module.exports = {sharedContext};
