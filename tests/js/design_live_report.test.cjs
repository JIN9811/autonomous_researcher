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
  {candidate_id:'a',x_wall_thickness_mm:0.8,y_cell_size_mm:7.1,value:0.9988},
  {candidate_id:'b',x_wall_thickness_mm:1.6,y_cell_size_mm:9.5}
]}},{candidate_id:'a'});
assert.match(space, /Design candidate positions/);
assert.match(space, /dsn-space-legend/);
assert.match(space, /dsn-space-axis-label" x="250"[^>]*>Cell size \(mm\)/);
assert.match(space, /rotate\(-90\)"[^>]*>Wall thickness \(mm\)/);
assert.match(space, /class="dsn-space-selected" transform="translate\(/);
assert.doesNotMatch(space, /lhs-viz|relative_density|NaN|Infinity/);
const boundedSpace = renderer.renderDesignSpace({parameter_sweep:{parameters:[
  {parameter:'cell_size_mm',min:5,max:10},
  {parameter:'wall_thickness_mm',min:0.8,max:1.6}
],heatmap_cells:[
  {candidate_id:'lower',x_wall_thickness_mm:0.8,y_cell_size_mm:5},
  {candidate_id:'upper',x_wall_thickness_mm:1.6,y_cell_size_mm:10}
]}});
const coords = [...boundedSpace.matchAll(/class="dsn-space-candidate" cx="([\d.]+)" cy="([\d.]+)"/g)].map(m=>m.slice(1).map(Number));
assert.equal(coords.length, 2);
assert.ok(coords[0][0] < coords[1][0] && coords[0][1] > coords[1][1]);
assert.ok(coords.every(([x,y])=>x>66 && x<434 && y>56 && y<224));
assert.match(renderer.renderDesignSpace({}), /Candidate coordinates not recorded/);
const mergedSpace = renderer.renderDesignSpace({},
  {candidate_id:'dsn-current',cell_size_mm:5,wall_thickness_mm:0.6}, [
    {candidate_id:'lhs-1',parameters:{cell_size_mm:5,wall_thickness_mm:0.6}},
    {candidate_id:'lhs-2',parameters:{cell_size_mm:10,wall_thickness_mm:1.2}},
    {candidate_id:'bo-next',parameters:{cell_size_mm:7.5,wall_thickness_mm:0.9}},
  ]);
assert.equal((mergedSpace.match(/class="dsn-space-candidate" cx=/g)||[]).length,3);
assert.match(mergedSpace,/bo-next/);
assert.match(mergedSpace,/dsn-current/);
assert.match(mergedSpace,/class="dsn-space-selected" transform="translate\(/);
assert.doesNotMatch(mergedSpace,/NaN|Infinity/);
assert.doesNotMatch(renderer.renderDesignSpace({parameter_sweep:{heatmap_cells:[
  {x_wall_thickness_mm:null,y_cell_size_mm:5},
  {x_wall_thickness_mm:0.8,y_cell_size_mm:''}
]}}), /<svg|NaN/);
const selectedComparison = renderer.renderExpectedPerformance({candidate_evaluations:[{candidate_id:'a'},{candidate_id:'b'}]}, {}, {candidate_id:'b'});
assert.match(selectedComparison, /dsn-comparison-scroll/);
assert.match(selectedComparison, /class="dsn-selected-candidate"[^>]*><td>b · Selected/);
assert.doesNotMatch(renderer.renderExpectedPerformance({candidate_evaluations:[{candidate_id:'a'}]}, {}, {}), /dsn-selected-candidate/);
const allCandidates = renderer.renderExpectedPerformance({candidate_evaluations:[
  {candidate_id:'current',validity:{status:'pass'}}
]}, {}, {candidate_id:'current',design_evaluation:{candidate_id:'current',validity:{status:'unassessed'}}}, [
  {candidate_id:'lhs-a',parameters:{cell_size_mm:5,wall_thickness_mm:0.6},status:'planned'},
  {candidate_id:'lhs-b',parameters:{cell_size_mm:10,wall_thickness_mm:1.2},status:'measured'},
  {candidate_id:'old-built',__actual_specimen:true},
  {candidate_id:'bo-next',parameters:{cell_size_mm:8,wall_thickness_mm:0.9},status:'planned'},
  {candidate_id:'current'}, {candidate_id:'current'}
]);
for (const id of ['lhs-a','lhs-b','old-built','bo-next','current']) assert.match(allCandidates,new RegExp(id));
assert.equal((allCandidates.match(/<td>current · Selected<\/td>/g)||[]).length,1);
assert.match(allCandidates,/Cell size \(mm\)/);
assert.match(allCandidates,/unassessed/);
assert.match(allCandidates,/Not evaluated/);
assert.doesNotMatch(allCandidates,/<td>pass<\/td>/);
const retainedSelection = {candidate_id:'current',validity:{status:'pass'},constraint_margins:[
  {constraint:'minimum_wall',actual:null,limit:0.4,relation:'>=',unit:'mm',status:'unmeasured'},
  {constraint:'envelope_x',actual:30,limit:30,relation:'<=',margin:0,unit:'mm',status:'pass'}
]};
const adaptedSelection = {candidate_id:'current',validity:{status:'unassessed'},constraint_margins:[],
  adapted_fields:['tpms_thickness'],selection_evaluation:retainedSelection};
const before = JSON.stringify(adaptedSelection);
const adaptedConstraint = renderer.renderManufacturabilityCard({design_evaluation:retainedSelection}, {}, {},
  {candidate_id:'current',design_evaluation:adaptedSelection});
assert.match(adaptedConstraint,/Current design: unassessed/);
assert.match(adaptedConstraint,/Selection-time evidence — before adaptation/);
assert.match(adaptedConstraint,/Constraint value relative to limit/);
assert.match(adaptedConstraint,/minimum_wall: unmeasured/);
assert.match(adaptedConstraint,/not a pass verdict for the current geometry/);
assert.equal(JSON.stringify(adaptedSelection),before);
const candidateSpecific = renderer.renderManufacturabilityCard({candidate_evaluations:[
  {candidate_id:'wrong',constraint_margins:[{constraint:'wrong-candidate'}]},retainedSelection
]}, {}, {candidate_id:'current'}, {candidate_id:'current'});
assert.match(candidateSpecific,/envelope_x/);
assert.doesNotMatch(candidateSpecific,/wrong-candidate/);
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
