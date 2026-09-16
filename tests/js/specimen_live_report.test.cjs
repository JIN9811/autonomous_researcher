"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function frontend() {
  const sandbox = { window: {} };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, "../../agents/specimen/frontend/live_report.js"), "utf8"), sandbox);
  const render = (value) => String(value ?? "-");
  const row = (rows) => rows.map(([key, value]) => `${key}=${render(value)}`).join(";");
  const context = { progressPanel: { progress_percent: 42, state: "printing" },
    printerStatus: {}, outcome: {}, packet: {}, monitor: { snapshot: {} } };
  return sandbox.window.AX4LABSpecimenUI.createFrontend({
    latestSpecimenFabricationReport: report => report.fabrication,
    latestSpecimenFabricatedPacket: report => report.packet,
    renderRuntimeValue: render, runtimeRows: row,
    renderReportList: items => items.join(";"), renderStepTrace: items => JSON.stringify(items),
    specimenRuntimeContext: () => context,
    specimenProgressPercent: (...values) => values.find(value => value != null),
    specimenFirstValue: (...values) => values.find(value => value != null),
    specimenStatusTone: () => "specimen",
    renderDashboardCard: (title, content) => `<article>${title}:${content}</article>`,
    renderDashboardMetric: (title, value) => `${title}=${value}`,
    renderSpecimenProgressBar: value => `progress=${value}`,
    renderSpecimenNowPrintingBody: () => "existing STL helper",
    renderSpecimenPrintMonitoringBody: () => "existing camera helper",
    renderSpecimenVideoHeaderControls: () => "existing video control",
    renderSpecimenPrinterStatusBody: () => "existing thermal helper",
    renderSpecimenPrintConnectionBody: () => "existing connection helper",
    renderSpecimenConnectionTestHeaderAction: () => "existing connection action",
    renderSpecimenAgenticProgressBody: () => "existing progress helper",
  });
}

test("Specimen owner report retains blocked gates, printer state and digital thread", () => {
  const ui = frontend();
  assert.equal(ui.renderReport({}), "");
  const html = ui.renderReport({ fabrication: {
    digital_thread: { specimen_id: "specimen-current", stl_path: "current.stl" },
    fabrication_intent: { physical_intent: false },
    quality_gates: [{ gate: "slicing", status: "blocked", repair: "review profile" }],
    printer_runtime: { prepare_status: "waiting", step_trace: [{ step: "cooling", status: "pending" }] },
  }, packet: { next_action: "review_printer" } });
  assert.match(html, /specimen_id=specimen-current/);
  assert.match(html, /physical_intent=false/);
  assert.match(html, /slicing · blocked · repair=review profile/);
  assert.match(html, /prepare_status=waiting/);
  assert.match(html, /cooling/);
  assert.match(html, /next_action=review_printer/);
  ui.dispose();
});

test("Specimen owner composes six existing cards using shared host inputs", () => {
  const html = frontend().renderDashboard({}, "running", "Specimen", {});
  assert.equal((html.match(/<article>/g) || []).length, 6);
  for (const title of ["Now printing", "Printing Progress", "Print Monitoring", "Printer Status", "Print Connection", "Agentic Progress"]) assert.match(html, new RegExp(title));
  assert.match(html, /progress=42/);
  assert.match(html, /State=printing/);
  assert.match(html, /existing STL helper/);
  assert.match(html, /existing camera helper/);
});

test("Mesh wall evidence replaces unknown values without fabricated success", () => {
  const ui = frontend();
  const measured = ui.renderReport({fabrication:{quality_gates:[{gate:"manufacturability",status:"fail",
    evidence:{wall_thickness_verification:{status:"fail",required_minimum_mm:0.4,minimum_sampled_mm:0.2968,sample_count:128}}}]}});
  assert.match(measured,/Actual mesh wall check=fail/);
  assert.match(measured,/Sampled minimum \(mm\)=0.2968/);
  assert.match(ui.renderReport({fabrication:{}}),/Actual mesh wall check=Not measured/);
});
