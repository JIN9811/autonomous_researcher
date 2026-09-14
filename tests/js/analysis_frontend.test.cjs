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
    renderDashboardCard: (title, body, options = {}) => `<section data-title="${title}" data-span="${options.span}">${body}</section>`,
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
