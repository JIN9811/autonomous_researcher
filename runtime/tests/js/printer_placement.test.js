"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../web/static/printer.js"), "utf8");

test("placement fields enable only custom coordinates and reject empty input", () => {
  const context = vm.createContext({
    placementModeInput: { value: "auto" },
    placementXInput: { value: "110", checkValidity: () => true },
    placementYInput: { value: "145", checkValidity: () => true },
  });
  const start = source.indexOf("function syncPlacementFields()");
  vm.runInContext(source.slice(start, source.indexOf("function fillProfile", start)), context);
  context.syncPlacementFields();
  assert.equal(context.placementXInput.disabled, true);
  context.placementModeInput.value = "custom";
  context.syncPlacementFields();
  assert.equal(context.placementYInput.disabled, false);
  assert.deepEqual(JSON.parse(JSON.stringify(context.readPlacement())), {mode: "custom", center_x_mm: 110, center_y_mm: 145});
  context.placementXInput.value = "";
  assert.throws(() => context.readPlacement(), /Specimen center/);
});

test("remaining standalone artifact handler always requests no motion", async () => {
  const requests = [];
  const context = vm.createContext({
    setBusy() {}, setDotState() {}, statusDot: {}, ejectionObjectSizeInput: null,
    currentTestSpecimenSize: () => [30, 30, 30], parseVector3: (_value, fallback) => fallback,
    bambuPublicBaseUrlInput: null, gateDetail: {}, refreshStatus: async () => {},
    renderAutoejectionStatus() {}, writeLog() {},
    apiJson: async (url, request) => { requests.push({url, body: JSON.parse(request.body)}); return {ok: true}; },
  });
  const start = source.indexOf("async function generateEjectionTestArtifact(");
  vm.runInContext(source.slice(start, source.indexOf("async function runBambuSweepTestArtifact", start)), context);
  await context.generateEjectionTestArtifact("center", {}, {mode: "live", startImmediately: true});
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/printer/autoejection-test");
  assert.equal(requests[0].body.mode, "test");
  assert.equal(requests[0].body.start_immediately, false);
});
