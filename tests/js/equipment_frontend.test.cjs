const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const asset = path.join(root, "agents/equipment/frontend/live_report.js");
const manifest = {
  id: "equipment",
  implementation: {
    version: "1.0.0",
    frontend: {
      asset_url: "/module-assets/equipment/live_report.js",
      namespace: "AX4LABEquipmentUI",
      factory: "createFrontend",
    },
  },
};

function services() {
  const value = (input, fallback = "-") => input === undefined || input === null || input === "" ? fallback : String(input);
  return {
    latestEquipmentReport: (report) => report.equipment_report,
    latestEquipmentResult: (report) => report.equipment_result,
    latestEquipmentSkillExecution: (report) => report.equipment_skill_execution,
    latestEquipmentSkillException: (report) => report.equipment_skill_exception,
    latestUtmDataReadyPacket: (report) => report.utm_data_ready,
    latestEquipmentHandoffPacket: (report) => report.equipment_handoff,
    runtimeRows: (rows) => `<dl>${rows.map(([key, item]) => `<dt>${key}</dt><dd>${value(item)}</dd>`).join("")}</dl>`,
    renderReportList: (items, empty) => items.length ? `<ul>${items.map((item) => `<li>${value(item)}</li>`).join("")}</ul>` : `<p>${empty}</p>`,
    renderRuntimeValue: value,
    renderDashboardRows: (rows) => `<dl>${rows.map(([key, item]) => `<dt>${key}</dt><dd>${value(item)}</dd>`).join("")}</dl>`,
    renderDashboardMetric: (label, item, meta) => `<div><b>${label}</b><strong>${value(item)}</strong><small>${meta}</small></div>`,
    renderDashboardCard: (title, body, options = {}) => `<section data-title="${title}" data-span="${options.span}">${options.action || ""}${body}</section>`,
    renderVisionCardDetails: (title, body) => `<details><summary>${title}</summary>${body}</details>`,
    renderGateStatusBars: (items, options) => items.length ? JSON.stringify(items) : options.emptyText,
    renderVizEmpty: (text) => `<p>${text}</p>`,
    escapeHtml: value,
    compactText: value,
    formatTime: value,
    numberText: (item) => String(item),
    dashboardPercent: (item) => Number(item),
    visionProgressTone: value,
    equipmentAgenticTaskModel: null,
    equipmentCycleContext: () => ({available: false}),
    equipmentRuntimeState: () => ({
      snapshot: {}, skillFlowSnapshot: null, refreshedAt: 0, error: "", actionInFlight: "",
      currentRunId: "run-current", runArtifacts: [],
    }),
  };
}

function sandbox() {
  const context = vm.createContext({window: {}, URL, Promise, Date, Map, Set, JSON});
  vm.runInContext(fs.readFileSync(path.join(root, "web/static/agent_module_host.js"), "utf8"), context);
  return context;
}

function progressItems(html) {
  const body = html.match(/data-title="Agentic Progress"[^>]*>([\s\S]*?)<\/section>/)[1];
  return [...body.matchAll(/class="ar-vis-agentic-step is-([^\"]+)"[\s\S]*?<strong>(.*?)<\/strong>/g)]
    .map((match) => ({status: match[1], label: match[2]}));
}

test("Equipment progress keeps the cycle steps while runtime data arrives", () => {
  const context = sandbox();
  vm.runInContext(fs.readFileSync(asset, "utf8"), context);
  const host = services();
  let snapshot = {};
  host.equipmentRuntimeState = () => ({snapshot, currentRunId: "run-current"});
  const frontend = context.window.AX4LABEquipmentUI.createFrontend(host);
  const render = () => frontend.renderDashboard({}, "running", "Equipment", {});
  const initial = progressItems(render());
  assert.equal(initial.length, 8);
  assert.equal(new Set(initial.map((item) => item.label)).size, 8);
  assert.ok(initial.every((item) => item.status === "waiting"));
  snapshot = {
    canonicalProjection: {execution_id: "skill-1", lifecycle: "EXECUTING", status: "running"},
    canonicalExecution: {lifecycle_contract: {RESOLVING: ["BLOCKED", "EXECUTING"], EXECUTING: ["RECOVERING", "COMPLETED"]}},
  };
  assert.deepEqual(progressItems(render()), initial, "internal lifecycle must not replace cycle steps");
  snapshot.canonicalExecution.metadata = {agentic_progress: "RECORDING"};
  assert.deepEqual(progressItems(render()), initial, "authoring stages must not replace cycle steps");
  snapshot.canonicalSkillFlow = {blocks: [
    {id: "prepare_next_specimen", label: "Move Jigs for Next Specimen"},
    {id: "start_test", label: "Start Test"},
  ]};
  snapshot.canonicalSkillFlowExecution = {
    run_id: "run-current", active_node: "start_test.skill",
    transitions: [{node_id: "prepare_next_specimen.skill", success: true, outcome: "completed"}],
  };
  assert.deepEqual(progressItems(render()), [
    {label: "Move Jigs for Next Specimen", status: "complete"},
    {label: "Start Test", status: "active"},
  ], "received profile steps and current-run evidence remain authoritative");
  snapshot.canonicalSkillFlowExecution.run_id = "old-run";
  assert.ok(progressItems(render()).every((item) => item.status === "waiting"));
  assert.equal((render().match(/data-title="Agentic Progress"/g) || []).length, 1);
});

test("installed Equipment owner renders the existing evidence and dashboard action contract", async () => {
  assert.ok(fs.existsSync(asset), "Equipment must own its frontend composition");
  const context = sandbox();
  let loads = 0;
  const host = context.window.AX4LABAgentModuleHost.createModuleHost({
    globalObject: context.window,
    loadAsset: async () => {
      loads += 1;
      vm.runInContext(fs.readFileSync(asset, "utf8"), context);
    },
  });
  assert.deepEqual(Array.from((await host.reconcile([manifest], services())).errors), []);
  const frontend = host.get("equipment");
  assert.equal(loads, 1);
  assert.ok(Object.isFrozen(frontend));
  assert.equal(frontend.renderReport({}), "");

  const report = {
    equipment_report: {
      schema: "atr.equipment.report.v1",
      task_id: "utm-cycle-current",
      bridge: {provider: "windows_pyautogui", connection_status: "connected"},
      screen_checks: [{checkpoint: "after_test", ok: true, screenshot_artifact: "utm-after-frame.png"}],
      artifact_records: [{kind: "raw_csv", artifact_id: "raw-current", linux_path: "/runs/current/raw.csv", row_count_probe: 42}],
      data_acquisition: {status: "ready", linux_path: "/runs/current/raw.csv", row_count_probe: 42},
      cross_checks: {data_parse_probe_ok: true},
      decision: {handoff_status: "ready_for_analysis", recommended_next_agent: "analysis"},
    },
    equipment_result: {status: "ok", result_file: "/runs/current/raw.csv"},
    equipment_handoff: {status: "ready_for_analysis", next_agent: "analysis"},
    equipment_skill_execution: {skill_id: "utm_compression", state: "completed", completed_segments: ["test"]},
    events: [{event_type: "equipment.completed", message: "evidence ready", ts: "2026-09-13T00:00:00Z"}],
  };
  const detail = frontend.renderReport(report);
  for (const token of ["utm-cycle-current", "utm-after-frame.png", "raw-current", "/runs/current/raw.csv", "ready_for_analysis"]) {
    assert.ok(detail.includes(token), `report retains ${token}`);
  }

  const dashboard = frontend.renderDashboard(report, "completed", "Lab Equipment Agent", {});
  const titles = ["Bridge / Runtime", "Active Program / Skill", "Recovery Boundary", "Agentic Progress", "Execution Evidence", "Handoff"];
  let cursor = -1;
  for (const title of titles) {
    const next = dashboard.indexOf(`data-title="${title}"`);
    assert.ok(next > cursor, `${title} remains in card order`);
    cursor = next;
  }
  for (const action of ["test", "open", "refresh"]) {
    assert.ok(dashboard.includes(`data-equipment-live-action="${action}"`), `${action} action remains delegated`);
  }
  assert.ok(!dashboard.includes('data-equipment-live-action="execute"'));
});

test("inactive Equipment owner has no current frontend cards and disposes without timers or listeners", async () => {
  assert.ok(fs.existsSync(asset), "Equipment frontend asset is required");
  const context = sandbox();
  const host = context.window.AX4LABAgentModuleHost.createModuleHost({
    globalObject: context.window,
    loadAsset: async () => vm.runInContext(fs.readFileSync(asset, "utf8"), context),
  });
  await host.reconcile([manifest], services());
  assert.ok(host.get("equipment").renderDashboard({}, "idle", "Equipment", {}).includes("Bridge / Runtime"));
  await host.reconcile([], services());
  const current = host.get("equipment");
  assert.equal(current, null);
  assert.equal(current && current.renderDashboard({}, "idle", "Equipment", {}), null);
});
