"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const asset = path.join(root, "agents/analysis/frontend/live_report.js");
const manifest = {
  id: "analysis",
  implementation: {
    version: "1.0.0",
    frontend: {
      asset_url: "/module-assets/analysis/live_report.js",
      namespace: "AX4LABAnalysisUI",
      factory: "createFrontend",
    },
  },
};

function value(input, fallback = "-") {
  return input === undefined || input === null || input === "" ? fallback : String(input);
}

function services(fem) {
  return {
    latestAnalysisPayload: (report) => report.analysis,
    latestAnalysisBoHandoff: (report) => report.bo_handoff,
    renderRuntimeValue: value,
    runtimeRows: (rows) => `<dl>${rows.map(([key, item]) => `<dt>${key}</dt><dd>${value(item)}</dd>`).join("")}</dl>`,
    renderReportList: (items, empty) => items.length ? `<ul>${items.map((item) => `<li>${value(item)}</li>`).join("")}</ul>` : `<p>${empty}</p>`,
    renderDashboardRows: (rows) => `<dl>${rows.map(([key, item]) => `<dt>${key}</dt><dd>${value(item)}</dd>`).join("")}</dl>`,
    renderDashboardMetric: (label, item, meta) => `<div><b>${label}</b><strong>${value(item)}</strong><small>${meta}</small></div>`,
    renderDashboardCard: (title, body, options = {}) => `<section data-title="${title}" data-span="${options.span}">${options.action || ''}${body}</section>`,
    renderAnalysisTrustScore: () => "trust evidence",
    renderAnalysisCurveOverlay: () => "curve evidence",
    renderAnalysisFieldLink: () => "field evidence",
    renderAnalysisMetricBars: () => "metric evidence",
    renderAnalysisQualityDonut: () => "quality evidence",
    renderAnalysisProvenance: () => "provenance evidence",
    renderAnalysisFemEvidence: (analysis) => fem.render(analysis),
  };
}

function sandbox() {
  const context = vm.createContext({window: {}, Object, JSON});
  vm.runInContext(fs.readFileSync(path.join(root, "web/static/agent_module_host.js"), "utf8"), context);
  return context;
}

test("installed Analysis owner retains measured evidence without reviving historical FEM panels", async () => {
  assert.ok(fs.existsSync(asset), "Analysis must own its frontend composition");
  const context = sandbox();
  const fem = { calls: [], render(analysis) { this.calls.push(analysis); return '<div class="analysis-fem-live">four evidence cards</div>'; } };
  const host = context.window.AX4LABAgentModuleHost.createModuleHost({
    globalObject: context.window,
    loadAsset: async () => vm.runInContext(fs.readFileSync(asset, "utf8"), context),
  });
  assert.deepEqual(Array.from((await host.reconcile([manifest], services(fem))).errors), []);
  const frontend = host.get("analysis");
  assert.ok(Object.isFrozen(frontend));
  assert.match(frontend.renderReport({}), /Awaiting data/);

  const report = {analysis: {
    source: {source: "equipment_result", path: "/runs/current/utm.csv", fingerprint: {sha256: "sha-current"}},
    utm_metrics: {peak_force_N: 512, compressive_strength_MPa: 1.28},
    quality_gate: {ok_for_bo: true, score: 0.96},
    trust_score: {schema: "analysis_admissibility.v1", gate: "allow_bo"},
    fem_agentic_loop: {status: "queued", execution: "background"},
    analysis_artifacts: {canonical_curve: "/runs/current/curve.json", experiment_evaluation: "/runs/current/evaluation.json"},
  }, bo_handoff: {schema_version: "analysis_bo_handoff_v2", ok_for_bo: true, next_agent: "BO"}};
  const detail = frontend.renderReport(report);
  for (const token of ["/runs/current/utm.csv", "sha-current", "512", "analysis_bo_handoff_v2", "/runs/current/curve.json"]) {
    assert.ok(detail.includes(token), `report retains ${token}`);
  }
  const dashboard = frontend.renderDashboard(report, "completed", "Analysis Agent", {});
  assert.match(dashboard, /ar-spm-progress-node-rail/);
  assert.match(dashboard, /ar-spm-progress-edge/);
  assert.match(dashboard, /ar-design-handoff-layout/);
  assert.match(dashboard, /ar-design-metric-strip/);
  assert.doesNotMatch(dashboard + detail, /analysis-fem-live|FEM|CAE|Solver Field/);
  for (const title of ["Objective", "Measured Response", "Key Metrics", "Agentic Progress", "Data Quality & BO Handoff"]) {
    assert.ok(dashboard.includes(`data-title="${title}"`), `${title} remains owner-composed`);
  }
});

test("objective comes from saved handoff, preserves zero, and empty data retains the same cards", async () => {
  const context = sandbox();
  vm.runInContext(fs.readFileSync(asset, "utf8"), context);
  const ui = context.window.AX4LABAnalysisUI.createFrontend(services({render: () => ''}));
  const empty = ui.renderDashboard({}, 'idle');
  const actual = ui.renderDashboard({analysis: {utm_metrics: {evaluation_strain: 0.4}, bo_handoff: {
    objective: {metric_name:'custom_energy', unit:'J/g', score:0, direction:'minimize'}, ok_for_bo:false
  }}}, 'done');
  assert.match(actual, /custom energy/i);
  assert.match(actual, /J\/g/);
  assert.match(actual, /40%/);
  assert.doesNotMatch(actual, /Awaiting objective/);
  assert.deepEqual([...empty.matchAll(/data-title="([^"]+)"/g)].map(x=>x[1]), [...actual.matchAll(/data-title="([^"]+)"/g)].map(x=>x[1]));
  assert.match(empty, /Awaiting data/);
  assert.doesNotMatch(empty, /Completed|100%/);
});

test("truncated summary hydrates both plots from the same specimen archive without replacing metrics", async () => {
  const context = sandbox();
  context.AbortController = AbortController;
  Object.assign(context.window, {setTimeout, clearTimeout});
  const calls = [], plots = [];
  let refreshes = 0;
  const curve = {preview: [
    {displacement_mm: 0, strain_pct: 0, force_N: 0, stress_MPa: 0},
    {displacement_mm: 16, strain_pct: 160 / 3, force_N: 900, stress_MPa: 1},
  ]};
  context.window.fetch = async url => {
    if (url.includes('/artifacts?')) return {ok: true, json: async () => ({})};
    calls.push(url);
    return {ok: true, json: async () => ({source: {sha256: 'hash-a'}, stress_strain_curve: curve, utm_metrics: {peak_force_N: 999}})};
  };
  vm.runInContext(fs.readFileSync(asset, 'utf8'), context);
  const ui = context.window.AX4LABAnalysisUI.createFrontend({...services({render: () => ''}),
    refreshAnalysisReport: () => refreshes++,
    renderAnalysisCurveOverlay: (a, mode) => {plots.push({a,mode});return 'curve';},
  });
  const report = {state: {run_id: 'run-a'}, analysis: {
    analysis_artifacts: {analysis_report: '/repo/runs/run-a/analysis/spec-8/analysis_report.json'},
    stress_strain_curve: {preview: [{strain_pct: 0}, {_truncated_items: 120}]},
    utm_metrics: {peak_force_N: 900},
  }};
  ui.renderDashboard(report);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(refreshes, 1);
  ui.renderDashboard(report);
  assert.equal(calls.length, 1);
  assert.match(calls[0], /^\/api\/runs\/run-a\/artifact-file\/analysis\/spec-8\//);
  for (const p of plots.slice(-2)) {
    assert.equal(p.a.stress_strain_curve, curve);
    assert.equal(p.a.utm_metrics.peak_force_N, 900);
  }
  assert.deepEqual(plots.slice(-2).map(p => p.mode), ['ss','fd']);
  const foreign = {...report, state: {run_id:'run-b'}};
  ui.renderDashboard(foreign);
  assert.equal(calls.length, 1, 'no reads from another run');
  assert.notEqual(plots.at(-1).a.stress_strain_curve, curve);
  report.analysis.source = {sha256: 'different-hash'};
  ui.renderDashboard(report);
  await new Promise(resolve => setImmediate(resolve));
  ui.renderDashboard(report);
  assert.notEqual(plots.at(-1).a.stress_strain_curve, curve, 'mismatched source rejected');
  ui.dispose();
});

test("inactive Analysis owner disappears from the module host", async () => {
  assert.ok(fs.existsSync(asset), "Analysis frontend asset is required");
  const context = sandbox();
  const fem = { calls: 0, render() { this.calls += 1; return '<div class="analysis-fem-live"></div>'; } };
  const host = context.window.AX4LABAgentModuleHost.createModuleHost({
    globalObject: context.window,
    loadAsset: async () => vm.runInContext(fs.readFileSync(asset, "utf8"), context),
  });
  await host.reconcile([manifest], services(fem));
  host.get("analysis").renderDashboard({analysis: {}}, "idle", "Analysis", {});
  await host.reconcile([], services(fem));
  assert.equal(host.get("analysis"), null);
});

test('Analysis cycle arrows keep archived curves, metrics and handoff together', async () => {
  const context = sandbox();
  context.AbortController = AbortController;
  Object.assign(context.window, {setTimeout, clearTimeout});
  const item = (cycle, attempt=1) => ({run_id:'run-a', agent:'analysis_agent', loop_number:cycle,
    attempt_index:attempt, name:'hash_analysis_report.json',
    url:`/api/runs/run-a/artifact-file/runtime/cycle-${cycle}/attempt-${attempt}/analysis_report.json`});
  let reads=0;
  context.window.fetch = async url => ({ok:true, json:async () => {
    if (url.includes('/artifacts?')) return {run_id:'run-a', artifacts:[item(1),item(2),item(2,2),item(3)]};
    reads++;
    assert.match(url, /cycle-2\/attempt-2/);
    return {stress_strain_curve:{preview:[{displacement_mm:12,strain_pct:40}]},
      utm_metrics:{peak_force_N:222}, bo_handoff:{run_id:'run-a',candidate_id:'old-candidate',
        objective:{name:'Old objective',score:2}}, objective_evaluation:{score:2}};
  }});
  vm.runInContext(fs.readFileSync(asset,'utf8'),context);
  const curves=[];
  const ui=context.window.AX4LABAnalysisUI.createFrontend({...services({render:()=>''}),
    renderAnalysisCurveOverlay:(a,mode)=>{curves.push({a,mode});return 'curve';}});
  const report={state:{run_id:'run-a'},analysis:{utm_metrics:{peak_force_N:333}},
    bo_handoff:{candidate_id:'current-candidate',objective:{name:'Current objective',score:3}}};
  ui.renderDashboard(report);
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(ui.renderDashboard(report),/Cycle 3 · 3\/3/);
  assert.equal(ui.moveHistory(-1),true);
  assert.match(ui.renderDashboard(report),/Loading saved analysis/);
  await new Promise(resolve=>setImmediate(resolve));
  const previous=ui.renderDashboard(report);
  assert.match(previous,/Cycle 2 · 2\/3 · Archived/);
  assert.match(previous,/222|Old objective/);
  assert.match(previous,/old-candidate/);
  assert.doesNotMatch(previous,/current-candidate|Current objective/);
  assert.equal(curves.at(-1).a.stress_strain_curve.preview[0].displacement_mm,12);
  ui.renderDashboard(report);
  assert.equal(reads,1);
  ui.moveHistory(1);
  assert.match(ui.renderDashboard(report),/Current objective/);
  ui.renderDashboard({state:{run_id:'run-b'}});
  assert.equal(ui.moveHistory(-1),false);
  ui.dispose();
});

test('Analysis history stays on the selected cycle when newer results arrive', () => {
  const context=sandbox();
  vm.runInContext(fs.readFileSync(asset,'utf8'),context);
  const history=context.window.AX4LABAnalysisUI.createHistory();
  history.sync('run-a');
  const item=cycle=>({run_id:'run-a',agent:'analysis_agent',loop_number:cycle,
    name:'analysis_report.json',url:`/api/runs/run-a/artifact-file/cycle-${cycle}/analysis_report.json`});
  history.accept([item(1),item(2),item(3)]);
  history.move(-1);
  history.accept([item(1),item(2),item(3),item(4),{...item(5),run_id:'foreign'}]);
  assert.equal(history.status().item.cycle,2);
  assert.equal(history.status().total,4);
  history.move(1);
  assert.equal(history.status().item.cycle,3);
  history.move(1);
  assert.equal(history.status().pinned,false);
  history.sync('run-b');
  assert.equal(history.status().total,0);
});
