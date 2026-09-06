const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const planningSource = fs.readFileSync("web/static/planning.js", "utf8");
const telemetrySource = fs.readFileSync("web/frontend/omx_telemetry_viewer/src/index.js", "utf8");

function functionSource(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `missing production function ${name}`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === "\"" || char === "'" || char === "`") {
      quote = char;
      continue;
    }
    if (char === "{") depth += 1;
    if (char === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated production function ${name}`);
}

function eventListenerSource(source, eventName) {
  const start = source.indexOf(`document.addEventListener("${eventName}",`);
  assert.notEqual(start, -1, `missing ${eventName} listener`);
  const end = source.indexOf("\n});", start);
  assert.notEqual(end, -1, `unterminated ${eventName} listener`);
  return source.slice(start, end + 4);
}

function report(overrides = {}) {
  const base = {
    state: {
      run_id: "run-1",
      loop_count: 0,
      current_experiment_spec: { specimen_id: "specimen-1" },
      run_metadata: {
        utm_verifications: {
          run_id: "run-1",
          loop_id: 0,
          specimen_id: "specimen-1",
          verification_1: {
            verification_index: 1,
            status: "confirmed",
            confirmed: true,
            captured_at: "2026-09-06T01:00:00Z",
            artifact: { path: "/evidence/placement.png", url: "/placement.png" },
            evidence: { detector: "red_specimen" },
          },
          verification_2: {
            verification_index: 2,
            status: "clear",
            confirmed: true,
            captured_at: "2026-09-06T01:05:00Z",
            artifact: { path: "/evidence/clear.png", url: "/clear.png" },
            evidence: { simulated: false, residual_red_area_px: 0 },
          },
        },
        utm_clear_execution: {
          run_id: "run-1",
          loop_id: 0,
          specimen_id: "specimen-1",
          state: "done",
          success: true,
          process_exit_code: 0,
        },
        manipulation_execution: {
          run_id: "run-1",
          loop_id: 0,
          specimen_id: "specimen-1",
          state: "done",
          success: true,
        },
      },
      agent_status: { manipulation_agent: { state: "done", success: true } },
    },
  };
  return Object.assign(base, overrides);
}

function planningContext(extra = {}) {
  const context = vm.createContext({
    escapeHtml: value => String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;"),
    compactText: value => String(value ?? ""),
    renderRuntimeValue: value => value === undefined || value === null || value === "" ? "-" : String(value),
    renderDashboardMetric: (label, value, meta) => `<div><small>${label}</small><strong>${value}</strong><span>${meta}</span></div>`,
    renderDashboardRows: rows => rows.map(([key, value]) => `<div><dt>${key}</dt><dd>${value}</dd></div>`).join(""),
    renderVisionCardDetails: (label, body) => `<details><summary>${label}</summary>${body}</details>`,
    ...extra,
  });
  return context;
}

function loadPlanningFunctions(names, extra = {}) {
  const context = planningContext(extra);
  for (const name of names) vm.runInContext(functionSource(planningSource, name), context);
  return context;
}

test("both snapshot selectors stay visible and missing Verification 2 is Pending without a V1 fallback", () => {
  const context = loadPlanningFunctions([
    "utmVerificationScope",
    "utmVerificationScopeKey",
    "selectVerification",
    "renderVisionUtmVerificationTabs",
    "renderVisionUtmVerification",
  ]);
  const snapshot = report();
  delete snapshot.state.run_metadata.utm_verifications.verification_2;
  const scope = context.utmVerificationScope(snapshot);
  const selected = context.selectVerification(scope, 2);
  const tabs = context.renderVisionUtmVerificationTabs(scope, 2);
  const rendered = context.renderVisionUtmVerification(selected);

  assert.match(tabs, /Verification 1/);
  assert.match(tabs, /Verification 2/);
  assert.match(tabs, /aria-selected="true"/);
  assert.equal(selected.status, "pending");
  assert.equal(selected.imageUrl, "");
  assert.doesNotMatch(rendered, /placement\.png/);
  assert.match(rendered, /No image — Pending/);
});

test("Verification 2 title, image, and status all come from its selected record", () => {
  const context = loadPlanningFunctions([
    "utmVerificationScope",
    "selectVerification",
    "renderVisionUtmVerification",
  ]);
  const selected = context.selectVerification(context.utmVerificationScope(report()), 2);
  const rendered = context.renderVisionUtmVerification(selected);

  assert.equal(selected.title, "Verification 2 — UTM clear");
  assert.equal(selected.status, "clear");
  assert.equal(selected.imageUrl, "/clear.png");
  assert.match(rendered, /Verification 2 — UTM clear/);
  assert.match(rendered, /src="\/clear\.png"/);
  assert.match(rendered, />clear</);
  assert.doesNotMatch(rendered, /placement\.png/);
});

test("explicitly simulated Verification 2 is not presented as a physical photograph", () => {
  const context = loadPlanningFunctions([
    "utmVerificationScope",
    "selectVerification",
    "renderVisionUtmVerification",
  ]);
  const snapshot = report();
  snapshot.state.run_metadata.utm_verifications.verification_2.artifact = {
    path: "", url: "", raw_frame_path: "", annotated_frame_path: "", evidence_path: "",
  };
  snapshot.state.run_metadata.utm_verifications.verification_2.evidence.simulated = true;
  const rendered = context.renderVisionUtmVerification(
    context.selectVerification(context.utmVerificationScope(snapshot), 2),
  );

  assert.match(rendered, /Explicit simulation/);
  assert.match(rendered, /no physical photograph/i);
  assert.doesNotMatch(rendered, /<img/);
});

test("selector interaction survives a same-scope poll and resets when any scope field changes", () => {
  const context = loadPlanningFunctions([
    "utmVerificationScopeKey",
    "updateUtmVerificationSelection",
    "handleUtmVerificationSelectionClick",
  ], { liveUtmVerificationSelection: { scopeKey: "", index: 1 } });
  const firstScope = { run_id: "run-1", loop_id: 0, specimen_id: "specimen-1" };
  const button = { dataset: { utmVerificationSelect: "2", utmVerificationScope: context.utmVerificationScopeKey(firstScope) } };

  assert.equal(context.handleUtmVerificationSelectionClick(button), true);
  assert.equal(context.liveUtmVerificationSelection.index, 2);
  context.updateUtmVerificationSelection(firstScope);
  assert.equal(context.liveUtmVerificationSelection.index, 2, "poll retains selected tab");

  for (const changed of [
    { ...firstScope, run_id: "run-2" },
    { ...firstScope, loop_id: 1 },
    { ...firstScope, specimen_id: "specimen-2" },
  ]) {
    context.liveUtmVerificationSelection = { scopeKey: context.utmVerificationScopeKey(firstScope), index: 2 };
    context.updateUtmVerificationSelection(changed);
    assert.equal(context.liveUtmVerificationSelection.index, 1);
  }
});

test("the actual keydown listener activates a nested UTM tab instead of selecting its report card", () => {
  for (const key of ["Enter", " "]) {
    let keydownHandler = null;
    let sectionSelections = 0;
    let renders = 0;
    const button = { dataset: { utmVerificationSelect: "2", utmVerificationScope: '["run-1",0,"specimen-1"]' } };
    const section = { dataset: { reportSectionTitle: "UTM Verification" } };
    const context = planningContext({
      document: { addEventListener(type, handler) { if (type === "keydown") keydownHandler = handler; } },
      liveDesignCaptureViewerOpen: false,
      liveReportPanel: { contains: node => node === button },
      liveLastSession: { state: {} },
      liveUtmVerificationSelection: { scopeKey: "", index: 1 },
      selectLiveReportSection() { sectionSelections += 1; },
      renderLiveRuntime() { renders += 1; },
      runLiveKeyboardShortcut() {},
    });
    vm.runInContext(functionSource(planningSource, "handleUtmVerificationSelectionClick"), context);
    vm.runInContext(eventListenerSource(planningSource, "keydown"), context);
    const event = {
      key,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      stopPropagation() {},
      target: {
        closest(selector) {
          if (selector === "[data-utm-verification-select]") return button;
          if (selector === ".live-report-section[data-report-section-title]") return section;
          return null;
        },
      },
    };

    keydownHandler(event);

    assert.equal(event.defaultPrevented, true);
    assert.equal(context.liveUtmVerificationSelection.index, 2);
    assert.equal(renders, 1);
    assert.equal(sectionSelections, 0);
  }
});

test("stale verification maps cannot supply either retained V1 or new V2 images", () => {
  const context = loadPlanningFunctions(["utmVerificationScope", "selectVerification"]);
  const snapshot = report();
  snapshot.state.run_metadata.utm_verifications.run_id = "stale-run";

  const scope = context.utmVerificationScope(snapshot);
  assert.equal(scope.scope_established, false);
  for (const index of [1, 2]) {
    const selected = context.selectVerification(scope, index);
    assert.equal(selected.status, "pending");
    assert.equal(selected.imageUrl, "");
  }
});

test("completion row advances from clear execution and Verification 2, never process exit alone", () => {
  const context = loadPlanningFunctions(["utmVerificationScope", "selectVerification", "utmClearCompletionView"]);
  const successful = report().state;
  assert.equal(context.utmClearCompletionView(successful).status, "done");

  const exitOnly = report().state;
  exitOnly.run_metadata.utm_clear_execution.success = null;
  exitOnly.run_metadata.utm_clear_execution.state = "waiting";
  exitOnly.run_metadata.utm_verifications.verification_2.confirmed = false;
  exitOnly.run_metadata.utm_verifications.verification_2.status = "unknown";
  assert.equal(exitOnly.run_metadata.utm_clear_execution.process_exit_code, 0);
  assert.equal(context.utmClearCompletionView(exitOnly).status, "waiting");
});

test("planning owns the preserved UTM completion row across polling while telemetry ignores it", () => {
  const clearRow = {
    dataset: { status: "waiting" },
    strong: { textContent: "waiting" },
    small: { textContent: "" },
    querySelector(selector) { return selector === "strong" ? this.strong : this.small; },
  };
  const document = {
    querySelectorAll(selector) {
      if (selector === "[data-utm-clear-verification-step]") return [clearRow];
      if (selector === "[data-atr-runtime-step]") return [];
      return [];
    },
  };
  const context = loadPlanningFunctions([
    "utmVerificationScope",
    "selectVerification",
    "utmClearCompletionView",
    "applyUtmClearCompletionVerification",
  ], { document });
  context.applyUtmClearCompletionVerification(report().state);
  assert.equal(clearRow.dataset.status, "done");
  assert.equal(clearRow.strong.textContent, "done");

  const telemetryContext = vm.createContext({
    document,
    setNodeTextIfChanged(node, value) { if (node) node.textContent = String(value); },
  });
  vm.runInContext(functionSource(telemetrySource, "applyCompletionVerification"), telemetryContext);
  telemetryContext.applyCompletionVerification({ steps: [], current_step: "" });
  assert.equal(clearRow.dataset.status, "done", "telemetry refresh must not reset the separately owned row");
});

test("matching UTM clear lifecycle takes sidebar priority over the completed transfer", () => {
  const context = loadPlanningFunctions(["manipulationExecutionDisplayState"]);
  const expected = [
    ["requested", null, "waiting"],
    ["starting", null, "running"],
    ["running", null, "running"],
    ["waiting", null, "waiting"],
    ["error", false, "error"],
    ["done", true, "done"],
  ];
  for (const [state, success, wanted] of expected) {
    const snapshot = report().state;
    snapshot.run_metadata.utm_clear_execution.state = state;
    snapshot.run_metadata.utm_clear_execution.success = success;
    assert.equal(context.manipulationExecutionDisplayState(snapshot, true), wanted);
  }
});
