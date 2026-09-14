"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const modulePath = path.resolve(__dirname, "../../agents/design/frontend/live_report.js");
const source = fs.readFileSync(modulePath, "utf8");

let timerCalls = 0;
let subscriptionCalls = 0;
const context = {
  window: {},
  setTimeout() { timerCalls += 1; },
  setInterval() { timerCalls += 1; },
  addEventListener() { subscriptionCalls += 1; },
};
vm.createContext(context);
vm.runInContext(source, context, { filename: modulePath });

const api = context.window.AX4LABDesignUI;
assert.equal(Object.isFrozen(api), true);
assert.deepEqual(Object.keys(api), ["createLiveReportRenderer", "createFrontend"]);

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
}[character]));
const compactText = (value, limit) => String(value ?? "").slice(0, limit);
const renderRuntimeValue = (value) => value === null || value === undefined ? "-" : String(value);
const renderer = api.createLiveReportRenderer({
  escapeHtml,
  compactText,
  renderRuntimeValue,
  renderDashboardRows: (rows) => JSON.stringify(rows),
  dashboardList: (rows, emptyText) => rows.length ? rows.join("|") : emptyText,
  orcChartPayloadAttr: (payload) => escapeHtml(JSON.stringify(payload)),
  designImageUrlFromSource: (item) => item.viewer_capture_url || "",
  designCandidateDirectCaptureUrl: () => "",
});

const adaptedEvidence = {
  schema: "design_evaluation.v1",
  scope: "adapted_spec_unassessed",
  validity: { status: "pass", reasons: [] },
  performance: { status: "unassessed", value: null },
  cost: {
    mass: { value: 0, unit: "g", status: "estimated" },
    duration: { value: 32, unit: "min", status: "rough_heuristic" },
  },
  constraint_margins: [{ constraint: "minimum_wall", margin: 0.2, unit: "mm", status: "pass" }],
};
const populated = renderer.renderExpectedPerformance({}, { design_evaluation: adaptedEvidence }, {
  expected_objective_proxy_score: 0.9988,
});
assert.match(populated, /Unassessed/);
assert.match(populated, /<td>0 g<\/td>/);
assert.doesNotMatch(populated, /0\.9988/);

const detailed = renderer.renderEvidence(adaptedEvidence, true);
assert.match(detailed, /minimum_wall: 0\.2 mm margin · pass/);

const empty = renderer.renderExpectedPerformance({}, {}, {});
const space = renderer.renderDesignSpace({parameter_sweep:{heatmap_cells:[
  {candidate_id:'a',x_relative_density:0.3,y_wall_thickness_mm:1.2,value:0.9988},
  {candidate_id:'b',x_relative_density:0.4,y_wall_thickness_mm:1.5}
]}},{candidate_id:'a'});
assert.match(space, /Design candidate positions/);
const selectedComparison = renderer.renderExpectedPerformance({candidate_evaluations:[{candidate_id:'a'},{candidate_id:'b'}]}, {}, {candidate_id:'b'});
assert.match(selectedComparison, /dsn-comparison-scroll/);
assert.match(selectedComparison, /class="dsn-selected-candidate"[^>]*><td>b · Selected/);
assert.doesNotMatch(renderer.renderExpectedPerformance({candidate_evaluations:[{candidate_id:'a'}]}, {}, {}), /dsn-selected-candidate/);
assert.match(renderer.renderManufacturabilityCard({}, {}, {}, {}), /<details class="dsn-variable-details"><summary>Constraint details<\/summary>/);
assert.match(space, /<details class="dsn-variable-details"><summary>Variables & ranges<\/summary>/);
assert.doesNotMatch(space, /0\.9988/);
assert.match(renderer.renderManufacturabilityCard({}, {design_evaluation:{constraint_margins:[
  {constraint:'wall',actual:1.4,limit:1.2,relation:'>=',margin:0.2,unit:'mm',status:'pass'}
]}}, {}, {}), /Constraint value relative to limit/);
assert.match(empty, /No recorded evidence/);
assert.doesNotMatch(empty, /dsn-scatter|OBJ/);

assert.deepEqual(
  JSON.parse(JSON.stringify(renderer.scatterRows([
    { candidate_id: "missing", y_predicted_objective: 0.5 },
    { candidate_id: "null", x_mass_g: null, y_predicted_objective: 0.5 },
    { candidate_id: "empty", x_mass_g: "", y_predicted_objective: 0.5 },
    { candidate_id: "zero", x_mass_g: 0, y_predicted_objective: 0.5 },
  ]))),
  [{ candidate_id: "zero", geometry_type: "", x: 0, y: 0.5, r: 0, score: null, status: "" }],
);
assert.deepEqual(
  JSON.parse(JSON.stringify(renderer.radarRows([
    { axis: "missing" },
    { axis: "null", value: null },
    { axis: "empty", value: "" },
    { axis: "zero", value: 0 },
  ]))),
  [{ label: "zero", value: 0, max: 1 }],
);

const decimals = renderer.renderExpectedPerformance({}, { candidate_evaluation: { selected_score: 1.20 } }, {
  manufacturability_score: 1.234,
});
assert.match(decimals, /No recorded evidence/);
assert.doesNotMatch(decimals, /1\.234|dsn-scatter/);
assert.doesNotMatch(decimals, /1\.20/);

const handoff = renderer.renderHandoffCard(
  { required_fields_present: false, missing_required_fields: ["stl_path"] },
  { candidate_id: "cand-&-1" },
  {},
  {},
  [],
);
assert.match(handoff, /Needs Input/);
assert.match(handoff, /cand-&amp;-1/);
assert.match(handoff, /stl_path/);

const zeroManufacturing = renderer.renderManufacturabilityCard(
  { manufacturability: { expected_mass_g: 0, expected_print_time_min: 0 } },
  {},
  {},
  {},
  { nozzle_diameter_mm: 0 },
  [],
);
assert.match(zeroManufacturing, /No recorded evidence/);
assert.doesNotMatch(zeroManufacturing, /dsn-radar/);
const missingManufacturing = renderer.renderManufacturabilityCard({}, {}, {}, {}, {}, []);
assert.match(missingManufacturing, /No recorded evidence/);

const frontend = api.createFrontend({
  escapeHtml,
  compactText,
  renderRuntimeValue,
  renderDashboardRows: (rows) => JSON.stringify(rows),
  dashboardList: (rows, emptyText) => rows.length ? rows.join("|") : emptyText,
  orcChartPayloadAttr: (payload) => escapeHtml(JSON.stringify(payload)),
  designImageUrlFromSource: (item) => item.viewer_capture_url || "",
  designCandidateDirectCaptureUrl: () => "",
  latestDesignAgentReport: () => ({}),
  latestDesignReport: (report) => report.design_report || {},
  designSelectedCandidate: () => ({}),
  designCandidateRows: () => [],
  designActualSpecimenRows: () => [],
  renderDesignCandidateCards: () => "<div>candidate cards</div>",
  renderDesignParameterSweep: () => "<div>parameter sweep</div>",
  renderDashboardCard: (title, body) => `<section><h4>${escapeHtml(title)}</h4>${body}</section>`,
  runtimeRows: (rows) => JSON.stringify(rows),
  renderReportList: (rows, emptyText) => rows.length ? rows.join("|") : emptyText,
});
assert.equal(frontend.renderDashboard.length, 4);
assert.equal(frontend.renderReport.length, 1);
assert.equal(frontend.dispose.length, 0);
const dashboard = frontend.renderDashboard({ design_report: {} }, "idle", "Design Agent", {});
assert.match(dashboard, /Experiment Contract/);
assert.match(dashboard, /Generated Specimens/);
const reportDetails = frontend.renderReport({
  design_report: {
    report_id: "design-1",
    objective: { primary_metric: "strength" },
    candidate_generation: { top_candidates: [{ candidate_id: "cand-1", geometry_type: "gyroid" }] },
    candidate_evaluation: { selected_candidate_id: "cand-1" },
  },
});
assert.match(reportDetails, /design-1/);
assert.match(reportDetails, /cand-1/);
assert.equal(frontend.dispose(), undefined);

renderer.renderEvidence(adaptedEvidence, true);
renderer.renderExpectedPerformance({}, {}, {});
assert.equal(timerCalls, 0);
assert.equal(subscriptionCalls, 0);

console.log("design live report module contract: ok");
