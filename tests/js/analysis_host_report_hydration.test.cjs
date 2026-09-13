"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const planningSource = fs.readFileSync(path.resolve(__dirname, "../../web/static/planning.js"), "utf8");

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

test("active Analysis falls back to its installed descriptors when the owner asset is unavailable", () => {
  const calls = { cards: 0, sections: 0, workcell: 0 };
  const context = {
    liveSelectedAgent: "analysis",
    liveAgentNeedsChatPanel: () => false,
    agentSpecificReportProfile: () => ({checklist: []}),
    liveAgentRendererProfile: () => ({id: "module", dashboardAgent: "", reportAgent: ""}),
    liveAgentModuleHost: {get: () => null},
    knownLiveAgent: () => true,
    renderAgentDescriptorCards: () => { calls.cards += 1; return "<descriptor-cards/>"; },
    renderAgentDescriptorReportSections: (_report, _agentId, options = {}) => { calls.sections += 1; calls.academic = Boolean(options.academic); return "<descriptor-sections/>"; },
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
  const html = vm.runInContext("renderAgentSpecializedDashboardSections({}, {}, 'idle', 'Analysis Agent')", context);
  assert.equal(calls.cards, 1);
  assert.equal(calls.sections, 1);
  assert.equal(calls.workcell, 1);
  assert.match(html, /descriptor-cards/);
  assert.match(html, /descriptor-sections/);

  Object.assign(context, {
    runtimeRows: () => "<rows/>",
    renderReportList: () => "<checklist/>",
    escapeHtml: String,
    renderOrchestratorReportDetails: () => "",
    renderDesignReportDetails: () => "",
    renderSpecimenReportDetails: () => "",
    renderVisionReportDetails: () => "",
    renderManipulationReportDetails: () => "",
    renderEquipmentReportDetails: () => "",
    renderAnalysisReportDetails: () => { throw new Error("must not delegate to the missing module twice"); },
    renderKnowledgeReportDetails: () => "",
    renderBoReportDetails: () => "",
    renderGuardianReportDetails: () => "",
  });
  vm.runInContext(declaration("renderAgentSpecificReportSection"), context);
  const reportHtml = vm.runInContext("renderAgentSpecificReportSection({}, 'idle', 'Analysis Agent')", context);
  assert.match(reportHtml, /descriptor-sections/);
  assert.equal(calls.academic, true);

  context.knownLiveAgent = () => false;
  calls.cards = 0;
  calls.sections = 0;
  vm.runInContext("renderAgentSpecializedDashboardSections({}, {}, 'idle', 'Analysis Agent')", context);
  assert.equal(calls.cards, 0, "an inactive owner must not be resurrected from fallback descriptors");
  assert.equal(calls.sections, 0, "an inactive owner must not regain report sections");
});

test("the existing planning refresh hydrates the current Analysis owner report with production response shape", async () => {
  assert.match(declaration("refreshPlanningState"), /await hydrateLiveSelectedAgentReport\(session, liveAgentManifestRequestGeneration\)/);
  const fullAnalysis = {
    source: {path: "runs/current/utm.csv", fingerprint: {sha256: "full-fingerprint"}, column_mapping: {force: "Force"}},
    utm_curve: {preview: [{displacement_mm: 1, force_N: 20}]},
    cae_result: {solver: "CalculiX"},
    fem_result: {status: "completed"},
    fem_agentic_loop: {attempts: [{attempt_id: "a1"}]},
    multifidelity_comparison: {rmse: 0.04},
    failure_tags: ["none"],
    closed_loop_sources: ["measurement", "cae"],
  };
  const response = {ok: true, report: {
    agent_id: "analysis",
    run_id: "run-current",
    sections: {analysis_report: fullAnalysis, bo_handoff: {next_agent: "bo"}},
  }};
  const requested = [];
  const context = {
    LIVE_AGENTS: [{id: "analysis", implementation: {frontend: {
      report_api: "/api/agents/analysis/report",
    }}}],
    liveSelectedAgent: "analysis",
    liveAgentManifestRequestGeneration: 4,
    liveLastSnapshot: {},
    knownLiveAgent: (id) => id === "analysis",
    fetchJsonOrThrowWithTimeout: async (url) => { requested.push(url); return response; },
    selectedMessages: () => [{role: "analysis", content: "Analysis completed", analysis: {objective_score: 0.7}}],
    selectedEvents: () => [],
    eventPayload: (event) => event.payload || {},
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
  for (const name of ["liveAgentReportApi", "liveOwnerReportForSession", "hydrateLiveSelectedAgentReport", "selectedReportModel", "latestReportPayload", "latestAnalysisPayload"]) {
    vm.runInContext(declaration(name), context);
  }
  const session = {state: {run_id: "run-current", latest_analysis: {objective_score: 0.7}}, runtime: {}};
  context.session = session;
  await vm.runInContext("hydrateLiveSelectedAgentReport(session)", context);
  assert.deepEqual(requested, ["/api/agents/analysis/report?run_id=run-current"]);
  const selected = vm.runInContext("latestAnalysisPayload(selectedReportModel(session))", context);
  assert.equal(selected.source.fingerprint.sha256, "full-fingerprint");
  assert.equal(selected.utm_curve.preview.length, 1);
  assert.equal(selected.fem_agentic_loop.attempts[0].attempt_id, "a1");

  response.report.run_id = "run-stale";
  const staleSession = {state: {run_id: "run-current", latest_analysis: {objective_score: 0.8}}, runtime: {}};
  context.staleSession = staleSession;
  await vm.runInContext("hydrateLiveSelectedAgentReport(staleSession)", context);
  assert.equal(Object.hasOwn(staleSession, "ownerReport"), false, "stale report identity must be rejected");

  response.report.run_id = "run-current";
  let release;
  context.fetchJsonOrThrowWithTimeout = () => new Promise((resolve) => { release = () => resolve(response); });
  const switchedSession = {state: {run_id: "run-current", latest_analysis: {objective_score: 0.9}}, runtime: {}};
  context.switchedSession = switchedSession;
  const pending = vm.runInContext("hydrateLiveSelectedAgentReport(switchedSession)", context);
  context.liveSelectedAgent = "bo";
  release();
  await pending;
  assert.equal(Object.hasOwn(switchedSession, "ownerReport"), false, "a late response must not overwrite a switched owner");

  context.liveSelectedAgent = "analysis";
  const supersededSession = {state: {run_id: "run-current", latest_analysis: {objective_score: 1.0}}, runtime: {}};
  context.supersededSession = supersededSession;
  const superseded = vm.runInContext("hydrateLiveSelectedAgentReport(supersededSession)", context);
  context.liveAgentManifestRequestGeneration += 1;
  release();
  await superseded;
  assert.equal(Object.hasOwn(supersededSession, "ownerReport"), false, "a superseded refresh must not accept its late report");
});

function hydrationSandbox(fetcher) {
  const context = {
    LIVE_AGENTS: [{id: "analysis", implementation: {frontend: {report_api: "/api/agents/analysis/report"}}}],
    liveSelectedAgent: "analysis",
    liveAgentManifestRequestGeneration: 8,
    knownLiveAgent: (id) => id === "analysis",
    fetchJsonOrThrowWithTimeout: fetcher,
  };
  vm.createContext(context);
  for (const name of ["liveAgentReportApi", "hydrateLiveSelectedAgentReport"]) vm.runInContext(declaration(name), context);
  return context;
}

test("a current-run Analysis projection keeps its own prior-loop identity after the live loop advances", async () => {
  const priorAnalysis = {
    source: {path: "runs/run-current/loop-1/utm.csv"},
    fem_job: {loop_key: "run-current:loop-1", specimen_id: "specimen-prior"},
    bo_observation: {
      run_id: "run-current",
      candidate_id: "specimen-prior",
      observation_id: "run-current:experiment:loop-1:analysis",
    },
  };
  const context = hydrationSandbox(async () => ({ok: true, report: {
    agent_id: "analysis",
    run_id: "run-current",
    sections: {analysis_report: priorAnalysis},
  }}));
  const session = {state: {
    run_id: "run-current",
    loop_count: 2,
    current_experiment_spec: {specimen_id: "specimen-current"},
  }};
  context.session = session;
  await vm.runInContext("hydrateLiveSelectedAgentReport(session)", context);
  assert.equal(session.ownerReport.sections.analysis_report.fem_job.loop_key, "run-current:loop-1");
  assert.equal(session.ownerReport.sections.analysis_report.bo_observation.candidate_id, "specimen-prior");
});

test("same-session Analysis hydration rejects an older response that arrives after the newest one", async () => {
  const pending = [];
  const context = hydrationSandbox(() => new Promise((resolve) => pending.push(resolve)));
  const session = {state: {run_id: "run-current", loop_count: 1}};
  context.session = session;
  const first = vm.runInContext("hydrateLiveSelectedAgentReport(session)", context);
  const second = vm.runInContext("hydrateLiveSelectedAgentReport(session)", context);
  const report = (fingerprint) => ({ok: true, report: {
    agent_id: "analysis",
    run_id: "run-current",
    sections: {analysis_report: {source: {fingerprint: {sha256: fingerprint}}}},
  }});
  pending[1](report("newest"));
  await second;
  pending[0](report("older"));
  await first;
  assert.equal(session.ownerReport.sections.analysis_report.source.fingerprint.sha256, "newest");
  assert.equal(Object.prototype.propertyIsEnumerable.call(session, "ownerReport"), false);
});
