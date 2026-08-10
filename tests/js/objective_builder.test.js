"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { createState } = require("../../web/static/objective_builder.js");

function manifest() {
  return {
    schema_version: "objective_authoring_manifest.v1",
    limits: { max_depth: 16, max_nodes: 256 },
    units: ["1", "MPa", "mm"],
    operators: [
      { op: "literal", enabled: true, kind: "leaf", result_kind: "number", children: { mode: "none" }, fields: [] },
      { op: "metric", enabled: true, kind: "leaf", result_kind: "number", children: { mode: "none" }, fields: [] },
      { op: "reference", enabled: false, kind: "leaf", result_kind: "number", children: { mode: "none" }, fields: [] },
      { op: "add", enabled: true, kind: "expression", result_kind: "number", children: { mode: "args", minimum: 2 }, fields: [] },
      { op: "square", enabled: true, kind: "expression", result_kind: "number", children: { mode: "arg", slots: ["arg"] }, fields: [] },
      { op: "weighted_sum", enabled: true, kind: "expression", result_kind: "number", children: { mode: "terms", minimum: 1 }, fields: [] },
      { op: "greater_equal", enabled: true, kind: "expression", result_kind: "boolean", children: { mode: "args", minimum: 2 }, fields: [] },
      { op: "and", enabled: true, kind: "expression", result_kind: "boolean", children: { mode: "args", minimum: 1 }, fields: [] },
    ],
  };
}

function metrics() {
  return [
    { metric_id: "compressive_strength_mpa", unit: "MPa", dimension: "stress" },
    { metric_id: "displacement_at_peak_mm", unit: "mm", dimension: "length" },
  ];
}

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
    dump() {
      return Object.fromEntries(values);
    },
  };
}

test("visual mutation updates canonical JSON without mutating prior snapshot", () => {
  const state = createState({ manifest: manifest(), metrics: metrics(), storage: memoryStorage() });
  const before = state.snapshot();

  state.replaceNode("expression", { op: "metric", metric_id: "compressive_strength_mpa" });
  const after = state.snapshot();

  assert.equal(JSON.parse(after.jsonBuffer).expression.metric_id, "compressive_strength_mpa");
  assert.equal(after.lastValidSpec.expression.op, "metric");
  assert.equal(before.lastValidSpec.expression.op, "literal");
  assert.equal(after.dirty, true);
});

test("invalid JSON preserves the last valid visual tree", () => {
  const state = createState({ manifest: manifest(), metrics: metrics(), storage: memoryStorage() });
  state.replaceNode("expression", { op: "metric", metric_id: "compressive_strength_mpa" });
  const before = state.snapshot().lastValidSpec;

  const result = state.applyJson('{"expression":');

  assert.equal(result.ok, false);
  assert.match(result.errors[0].message, /JSON|Unexpected|position|end/i);
  assert.deepEqual(state.snapshot().lastValidSpec, before);
  assert.equal(state.snapshot().jsonBuffer, '{"expression":');
  state.restoreLastValid();
  assert.deepEqual(JSON.parse(state.snapshot().jsonBuffer), before);
});

test("valid JSON applies nested expressions and rejects unavailable sources", () => {
  const state = createState({ manifest: manifest(), metrics: metrics(), storage: memoryStorage() });
  const valid = {
    schema_version: "objective_spec.v1",
    objective_id: "operator-objective",
    version: 1,
    direction: "maximize",
    expression: {
      op: "square",
      arg: { op: "metric", metric_id: "compressive_strength_mpa" },
    },
    constraints: [],
  };

  assert.equal(state.applyJson(JSON.stringify(valid)).ok, true);
  const unknownMetric = structuredClone(valid);
  unknownMetric.expression.arg.metric_id = "not_registered";
  const metricResult = state.applyJson(JSON.stringify(unknownMetric));
  assert.equal(metricResult.ok, false);
  assert.equal(metricResult.errors[0].path, "$.expression.arg.metric_id");
  const disabled = structuredClone(valid);
  disabled.expression = { op: "reference", name: "unsafe" };
  assert.equal(state.applyJson(JSON.stringify(disabled)).ok, false);
});

test("tree operations add reorder duplicate and remove variadic children", () => {
  const state = createState({ manifest: manifest(), metrics: metrics(), storage: memoryStorage() });
  state.replaceNode("expression", {
    op: "add",
    args: [
      { op: "literal", value: 1, unit: "1" },
      { op: "literal", value: 2, unit: "1" },
    ],
  });

  state.addChild("expression", { op: "literal", value: 3, unit: "1" });
  state.moveNode("expression.args.2", -1);
  state.duplicateNode("expression.args.0");
  state.removeNode("expression.args.3");
  const args = state.snapshot().lastValidSpec.expression.args;

  assert.deepEqual(args.map((item) => item.value), [1, 1, 3]);
});

test("weighted terms and boolean constraint roots keep their required shape", () => {
  const state = createState({ manifest: manifest(), metrics: metrics(), storage: memoryStorage() });
  state.replaceNode("expression", { op: "weighted_sum", terms: [] });
  state.addChild("expression", { op: "metric", metric_id: "compressive_strength_mpa" });
  state.addConstraint({
    op: "greater_equal",
    args: [
      { op: "metric", metric_id: "compressive_strength_mpa" },
      { op: "literal", value: 5, unit: "MPa" },
    ],
  });
  const spec = state.snapshot().lastValidSpec;

  assert.deepEqual(spec.expression.terms[0], {
    name: "term_1",
    weight: 1,
    expression: { op: "metric", metric_id: "compressive_strength_mpa" },
  });
  assert.equal(spec.constraints[0].op, "greater_equal");
  assert.throws(
    () => state.addConstraint({ op: "metric", metric_id: "compressive_strength_mpa" }),
    /boolean/i,
  );
});

test("saved server state clears dirty flag and browser storage restores unsaved work", () => {
  const storage = memoryStorage();
  const first = createState({ manifest: manifest(), metrics: metrics(), storage });
  first.setMetadata({ objective_id: "manual-restored", name: "Restored" });
  assert.equal(first.snapshot().dirty, true);

  const restored = createState({ manifest: manifest(), metrics: metrics(), storage });
  assert.equal(restored.snapshot().lastValidSpec.objective_id, "manual-restored");
  assert.equal(restored.snapshot().dirty, true);
  const saved = restored.snapshot().lastValidSpec;
  saved.version = 4;
  saved.created_by = "operator:JIN";
  restored.markSaved(saved);

  assert.equal(restored.snapshot().dirty, false);
  assert.equal(restored.snapshot().selectedObjective.version, 4);
  assert.equal(storage.dump()["atr.objective-builder.v1"], undefined);
});
