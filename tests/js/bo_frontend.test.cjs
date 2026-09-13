"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const asset = path.join(root, "agents/bo/frontend/live_report.js");
const hostSource = fs.readFileSync(path.join(root, "web/static/agent_module_host.js"), "utf8");
const planningSource = fs.readFileSync(path.join(root, "web/static/planning.js"), "utf8");
const manifest = {
  id: "bo",
  implementation: {version: "1.0.0", frontend: {
    asset_url: "/module-assets/bo/live_report.js",
    namespace: "AX4LABBOUI",
    factory: "createFrontend",
  }},
};

function declaration(name) {
  const candidates = [`function ${name}(`, `async function ${name}(`];
  const start = candidates.map((token) => planningSource.indexOf(token)).filter((index) => index >= 0).sort((a, b) => a - b)[0];
  assert.notEqual(start, undefined, `${name} integration is missing`);
  const openParen = planningSource.indexOf("(", start);
  let parenDepth = 0;
  let parametersEnd = -1;
  for (let index = openParen; index < planningSource.length; index += 1) {
    if (planningSource[index] === "(") parenDepth += 1;
    if (planningSource[index] === ")" && --parenDepth === 0) { parametersEnd = index; break; }
  }
  const brace = planningSource.indexOf("{", parametersEnd);
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let index = brace; index < planningSource.length; index += 1) {
    const char = planningSource[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === "\"" || char === "'" || char === "`") { quote = char; continue; }
    if (char === "{") depth += 1;
    if (char === "}" && --depth === 0) return planningSource.slice(start, index + 1);
  }
  throw new Error(`unterminated function ${name}`);
}

function value(input, fallback = "-") {
  return input === undefined || input === null || input === "" ? fallback : String(input);
}

function services() {
  const visualization = {
    isValid: (item) => item && item.schema === "bo_visualization.v1",
    renderEquationCard: () => '<div id="equation">objective equation</div>',
    renderPlot: () => '<div id="posterior">posterior acquisition plot</div>',
    renderDecision: () => '<div id="decision">accepted exact candidate</div>',
  };
  return {
    latestReportBoResult: (report) => report.bo_result || {},
    latestAnalysisPayload: (report) => report.analysis || {},
    latestKnowledgeReport: () => ({}),
    latestKnowledgeEvolutionProposal: () => ({}),
    latestReportPayload: () => null,
    resolveLiveBoVisualization: (_report, boResult) => boResult.visualization || {},
    boOptimizationPhase: (boResult) => {
      const trace = boResult.benchmark?.strategies?.bo?.surrogate_trace?.at(-1) || {};
      return boResult.optimization_phase || trace.phase || boResult.visualization?.backend?.phase
        || (boResult.visualization?.backend?.active === "lhs" ? "initial_design" : "");
    },
    boInitialDesignStatus: (boResult) => {
      const trace = boResult.benchmark?.strategies?.bo?.surrogate_trace?.at(-1) || {};
      const initial = boResult.initial_design || trace.initial_design || boResult.visualization?.initial_design || {};
      const completed = Number(initial.completed || 0);
      const target = Number(initial.target || 8);
      return {sampler: initial.sampler || "latin_hypercube", completed, target, nextIndex: Number(initial.next_index || Math.min(completed + 1, target))};
    },
    boVisualization: visualization,
    renderBoInitialDesignBoard: (report) => `<div id="lhs">${value(report.bo_result?.lhs_visualization?.step)}</div>`,
    renderBoGateState: () => '<div id="gate">waiting</div>',
    renderBoRankingBoard: (boResult) => `<div id="ranking">${value(boResult.candidate_ranking?.[0]?.candidate_id)}</div>`,
    renderBoParameterChips: (candidate) => `<div id="params">${value(candidate.parameters?.cell_size_mm)}</div>`,
    compactBoParams: (parameters) => Object.entries(parameters || {}).map(([key, item]) => `${key}=${item}`).join(", "),
    renderRuntimeValue: value,
    runtimeRows: (rows) => `<dl>${rows.map(([key, item]) => `<dt>${key}</dt><dd>${value(item)}</dd>`).join("")}</dl>`,
    renderReportList: (items, empty) => items.length ? `<ul>${items.map((item) => `<li>${value(item)}</li>`).join("")}</ul>` : `<p>${empty}</p>`,
    renderDashboardRows: (rows) => `<dl>${rows.map(([key, item]) => `<dt>${key}</dt><dd>${value(item)}</dd>`).join("")}</dl>`,
    renderDashboardCard: (title, body, options = {}) => `<section data-title="${title}" data-span="${options.span}">${body}</section>`,
    dashboardList: (items, empty) => items.length ? items.join("|") : empty,
  };
}

function sandbox() {
  const context = vm.createContext({window: {}, Object, JSON, URL, Promise});
  vm.runInContext(hostSource, context);
  return context;
}

test("installed BO owner renders initial design, posterior, decision and handoff evidence", async () => {
  assert.ok(fs.existsSync(asset), "BO must own its frontend composition");
  const context = sandbox();
  const host = context.window.AX4LABAgentModuleHost.createModuleHost({
    globalObject: context.window,
    loadAsset: async () => vm.runInContext(fs.readFileSync(asset, "utf8"), context),
  });
  assert.deepEqual(Array.from((await host.reconcile([manifest], services())).errors), []);
  const frontend = host.get("bo");
  assert.ok(Object.isFrozen(frontend));
  assert.equal(frontend.renderReport({}), "");

  const report = {bo_result: {
    run_id: "run-current",
    optimization_phase: "acquisition",
    strategy: "bo",
    acquisition: "expected_improvement",
    prior_summary: {prior_count: 4, measured_count: 3, failed_count: 1},
    decision: {schema: "bo_decision.v1", status: "accepted"},
    reasoning: {
      strategy_recommendation: {strategy: "bo", acquisition: "expected_improvement", exploration_weight: 0.4, exploitation_weight: 0.6},
      hypotheses: [{id: "h-parameter", confidence: 0.73, claim: "density may improve response"}],
    },
    candidate_ranking: [{candidate_id: "candidate-current", combined_score: 0.81, parameters: {cell_size_mm: 7.2}}],
    recommendation: {candidate_id: "candidate-current", parameters: {cell_size_mm: 7.2}, why_not_best_exploitation_only: "uncertainty-aware selection"},
    next_design_request: {schema: "next_design_request.v1", status: "ready", consumer_agent: "design_agent", priority: "normal"},
    lhs_visualization: {schema: "lhs_design_visualization.v1", step: 4},
    visualization: {schema: "bo_visualization.v1", step: 9},
    artifacts: {bo_decision: "/runs/current/bo/bo_decision.json"},
  }};
  const detail = frontend.renderReport(report);
  for (const token of [
    "candidate-current", "cell_size_mm=7.2", "h-parameter", "density may improve response",
    "0.4 / 0.6", "uncertainty-aware selection", "expected_improvement",
    "ready", "/runs/current/bo/bo_decision.json",
  ]) {
    assert.ok(detail.includes(token), `report retains ${token}`);
  }
  const dashboard = frontend.renderDashboard(report, "completed", "BO Agent", {});
  for (const title of ["BO Objective Equation", "Live Posterior", "Initial Design / LHS", "BO Decision / Tool Audit", "Candidate Ranking", "Next Design Request"]) {
    assert.ok(dashboard.includes(`data-title="${title}"`), `${title} remains owner-composed`);
  }
  for (const mount of ['data-live-bo-equation', 'data-live-bo-posterior', 'id="lhs"']) {
    assert.ok(dashboard.includes(mount), `${mount} remains mounted`);
  }
  assert.ok(dashboard.includes("normal"), "Design handoff priority remains visible");

  await host.reconcile([], services());
  assert.equal(host.get("bo"), null);
});

test("BO owner keeps the initial LHS phase contract visible before acquisition", async () => {
  const context = sandbox();
  const host = context.window.AX4LABAgentModuleHost.createModuleHost({
    globalObject: context.window,
    loadAsset: async () => vm.runInContext(fs.readFileSync(asset, "utf8"), context),
  });
  await host.reconcile([manifest], services());
  const detail = host.get("bo").renderReport({bo_result: {
    run_id: "run-lhs",
    backend_active: "lhs",
    benchmark: {strategies: {bo: {surrogate_trace: [{
      phase: "initial_design",
      initial_design: {sampler: "latin_hypercube", completed: 2, target: 8},
    }]}}},
    recommendation: {candidate_id: "lhs-003", selection_method: "latin_hypercube", parameters: {cell_size_mm: 6.5}},
  }});
  for (const token of ["Initial Design / LHS", "2/8", "3/8", "Candidate ranking is disabled", "lhs-003"]) {
    assert.ok(detail.includes(token), `initial report retains ${token}`);
  }
  const visualOnly = host.get("bo").renderReport({bo_result: {
    run_id: "run-lhs-visual",
    visualization: {
      backend: {active: "lhs"},
      initial_design: {sampler: "latin_hypercube", completed: 4, target: 8},
    },
    recommendation: {candidate_id: "lhs-005", parameters: {cell_size_mm: 6.9}},
  }});
  for (const token of ["Initial Design / LHS", "4/8", "5/8", "lhs-005"]) {
    assert.ok(visualOnly.includes(token), `visualization-only LHS report retains ${token}`);
  }
});

test("active BO falls back to descriptors when the owner asset is unavailable", () => {
  const calls = {cards: 0, sections: 0, workcell: 0};
  const context = {
    liveSelectedAgent: "bo",
    liveAgentNeedsChatPanel: () => false,
    agentSpecificReportProfile: () => ({checklist: []}),
    liveAgentRendererProfile: () => ({id: "module", dashboardAgent: "", reportAgent: ""}),
    liveAgentModuleHost: {get: () => null},
    knownLiveAgent: (id) => id === "bo",
    renderAgentDescriptorCards: () => { calls.cards += 1; return "<descriptor-cards/>"; },
    renderAgentDescriptorReportSections: () => { calls.sections += 1; return "<descriptor-sections/>"; },
    renderAgentWorkcellCard: () => { calls.workcell += 1; return "<workcell/>"; },
    renderAgentVisualizationCard: () => "",
    renderDashboardCard: () => "",
    dashboardList: () => "",
  };
  for (const name of ["Objective", "Orchestrator", "Design", "Specimen", "Vision", "Manipulation", "Equipment", "Analysis", "Knowledge", "Bo", "Guardian"]) {
    context[`render${name}DashboardCards`] = () => "";
  }
  vm.createContext(context);
  vm.runInContext(declaration("activeModuleDescriptorFallback"), context);
  vm.runInContext(declaration("renderAgentSpecializedDashboardSections"), context);
  const html = vm.runInContext("renderAgentSpecializedDashboardSections({}, {}, 'idle', 'BO Agent')", context);
  assert.equal(calls.cards, 1);
  assert.equal(calls.sections, 1);
  assert.equal(calls.workcell, 1);
  assert.match(html, /descriptor-cards/);
  assert.match(html, /descriptor-sections/);

  context.knownLiveAgent = () => false;
  calls.cards = 0;
  calls.sections = 0;
  vm.runInContext("renderAgentSpecializedDashboardSections({}, {}, 'idle', 'BO Agent')", context);
  assert.equal(calls.cards, 0);
  assert.equal(calls.sections, 0);
});

test("BO owner report hydration keeps same-run evidence and rejects stale identities", async () => {
  const fullBO = {run_id: "run-current", candidate_ranking: [{candidate_id: "prior-loop-candidate"}], visualization: {step: 8}};
  const response = {ok: true, report: {agent_id: "bo", run_id: "run-current", sections: {bo_result: fullBO}}};
  const requested = [];
  const context = {
    LIVE_AGENTS: [{id: "bo", implementation: {frontend: {report_api: "/api/agents/bo/report"}}}],
    liveSelectedAgent: "bo",
    liveAgentManifestRequestGeneration: 4,
    liveLastSnapshot: {},
    knownLiveAgent: (id) => id === "bo",
    fetchJsonOrThrowWithTimeout: async (url) => { requested.push(url); return response; },
    selectedMessages: () => [],
    selectedEvents: () => [],
    eventPayload: () => ({}),
    backendField: () => null,
    reportEventLabel: () => "event",
    renderRuntimeValue: String,
    roleLabel: String,
    formatTime: String,
    compactText: String,
    eventTimelineKind: () => "info",
    reportEventText: () => "event",
  };
  vm.createContext(context);
  for (const name of ["liveAgentReportApi", "liveOwnerReportForSession", "hydrateLiveSelectedAgentReport", "selectedReportModel", "latestReportPayload", "latestReportBoResult"]) {
    vm.runInContext(declaration(name), context);
  }
  const session = {state: {run_id: "run-current", run_metadata: {bo_agent: {run_id: "run-current", candidate_ranking: []}}}, runtime: {}};
  context.session = session;
  await vm.runInContext("hydrateLiveSelectedAgentReport(session)", context);
  assert.deepEqual(requested, ["/api/agents/bo/report?run_id=run-current"]);
  const selected = vm.runInContext("latestReportBoResult(selectedReportModel(session))", context);
  assert.equal(selected.candidate_ranking[0].candidate_id, "prior-loop-candidate");

  response.report.sections.bo_result.run_id = "run-stale";
  const stale = {state: {run_id: "run-current", run_metadata: {}}, runtime: {}};
  context.stale = stale;
  await vm.runInContext("hydrateLiveSelectedAgentReport(stale)", context);
  assert.equal(Object.hasOwn(stale, "ownerReport"), false);
});
