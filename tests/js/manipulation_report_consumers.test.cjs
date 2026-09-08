const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function loadFunctions(path, names, context) {
  const source = fs.readFileSync(path, "utf8");
  for (const name of names) {
    const start = source.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `${name} exists`);
    vm.runInContext(source.slice(start, source.indexOf("\n}", start) + 2), context);
  }
}

const report = {
  preflight: { status: "blocked", robot_ready: false, blocking_reasons: ["operator confirmation required"] },
  stage_machine: { current_stage: "approach", completed_stages: ["observe"], stage_taxonomy: ["observe", "approach", "place"] },
  decision: { completion_status: "pending", reason: "Vision verification required" },
};

test("LeRobot report shows actual stages and blockers without inventing nominal safety or progress", () => {
  const context = vm.createContext({
    manipulationReportEl: { innerHTML: "" },
    escapeHtml: value => String(value ?? "-"),
    boolStatus: (value, yes, no) => value ? yes : no,
    reportRowsHtml: rows => JSON.stringify(rows),
    reportListHtml: rows => JSON.stringify(rows),
  });
  const source = fs.readFileSync("web/static/lerobot.js", "utf8");
  const names = ["manipulationReportFromResponse", "robotTaskResultFromResponse", "manipulationResponseFromData",
    "rerunTelemetryFromReport", "compactValue", "statusPillClass", "runtimeCardHtml", "renderManipulationAgentReport"];
  if (source.includes("function executionSafetyFromReport(")) names.unshift("executionSafetyFromReport");
  loadFunctions("web/static/lerobot.js", names, context);
  context.renderManipulationAgentReport({ manipulation_report: report });
  const html = context.manipulationReportEl.innerHTML;
  assert.match(html, /approach/);
  assert.match(html, /operator confirmation required/);
  assert.match(html, /Vision verification required/);
  assert.doesNotMatch(html, /nominal|Execution Safety|Failure Precursor|\["Progress"|\["Recovery"/);
});

test("planning manipulation details render stage evidence without empty reward metrics", () => {
  const context = vm.createContext({
    latestManipulationReport: () => report,
    latestRobotTaskResult: () => ({}),
    runtimeRows: rows => JSON.stringify(rows),
    renderReportList: rows => JSON.stringify(rows),
  });
  loadFunctions("web/static/planning.js", ["renderManipulationReportDetails"], context);
  const html = context.renderManipulationReportDetails({});
  assert.match(html, /approach/);
  assert.match(html, /1\/3/);
  assert.match(html, /operator confirmation required/);
  assert.doesNotMatch(html, /progress_score|failure_precursor|\["recovery"|next_expected/);
});

test("manipulation visualization reports actual preflight facts without score charts", () => {
  const context = vm.createContext({
    liveSelectedAgent: "manipulation",
    latestManipulationReport: () => ({ preflight: { robot_ready: false, camera_ready: true, policy_ready: true, operator_confirmed: false } }),
    dashboardGateItemCount: rows => rows.length,
    dashboardMiniBarItemCount: rows => rows.length,
    dashboardFiniteNumber: value => value == null ? null : Number(value),
    renderGateStatusBars: rows => JSON.stringify(rows),
    renderDashboardCard: (title, body) => title + body,
    escapeHtml: String,
  });
  loadFunctions("web/static/planning.js", ["renderAgentVisualizationCard"], context);
  const html = context.renderAgentVisualizationCard({}, {}, "Manipulation");
  assert.match(html, /"label":"robot_ready","status":false/);
  assert.match(html, /"label":"camera_ready","status":true/);
  assert.match(html, /"label":"operator_confirmed","status":false/);
  assert.doesNotMatch(html, /score|nominal/);
});

test("pose handoff displays available rotation evidence without a removed pose-error estimate", () => {
  const context = vm.createContext({
    escapeHtml: String,
    compactText: String,
    numberText: String,
    renderDashboardRows: rows => JSON.stringify(rows),
  });
  loadFunctions("web/static/planning.js", ["renderManipulationPoseTable"], context);
  const html = context.renderManipulationPoseTable({ frames: [{ frame: "place_target" }], rotation_error_deg: 0.2 });
  assert.match(html, /place_target/);
  assert.match(html, /rotation_error_deg/);
  assert.doesNotMatch(html, /pose_error_mm/);
});

test("reachability renders the existing readiness status without relying on removed hotspot scores", () => {
  const context = vm.createContext({
    renderDashboardRows: rows => JSON.stringify(rows),
    renderVizEmpty: String,
  });
  loadFunctions("web/static/planning.js", ["renderManipulationReachabilityMap"], context);
  assert.match(context.renderManipulationReachabilityMap({ status: "blocked" }), /blocked/);
});
