const test = require("node:test");
const assert = require("node:assert/strict");

const model = require("../../web/static/equipment_agentic_task_model.js");


test("projects workflow blocks and keeps disabled equipment Vision optional", () => {
  const ctx = model.cycleContext({
    workflow_agentic_task: {
      task_id: "run_utm_compression_cycle",
      profile_id: "utm_windows_v1",
      block_order: ["prepare_next_specimen", "start_test"],
      entry_gate: { locked: true, ok: true },
      status: "running",
    },
    block_executions: [
      {
        block_id: "prepare_next_specimen",
        phase: "skill",
        outcome: "completed",
        skill_id: "prepare",
        skill_version: "1.0.0",
      },
      {
        block_id: "prepare_next_specimen",
        phase: "vision",
        outcome: "bypass",
        vision_link_enabled: false,
      },
      {
        block_id: "start_test",
        phase: "skill",
        outcome: "running",
        skill_id: "start",
        skill_version: "2.0.0",
      },
    ],
  });

  const steps = model.progressSteps(ctx);

  assert.equal(ctx.available, true);
  assert.deepEqual(steps.map((step) => step.status), ["complete", "active"]);
  assert.equal(steps[0].vision.optional, true);
  assert.equal(steps[0].vision.enabled, false);
  assert.equal(steps[0].skill, "prepare@1.0.0");
});


test("projects observed equipment values separately from method targets", () => {
  const ctx = model.cycleContext({
    workflow_agentic_task: { task_id: "run_utm_compression_cycle", block_order: [] },
    method_values: {
      Force: { observed: 6.2, target: 7.0 },
      Stroke: { observed: 19.8, target: null },
      Height: { observed: 118.4, target: 118.4 },
    },
  });

  assert.deepEqual(model.methodRows(ctx), [
    { label: "Force", observed: 6.2, target: 7.0 },
    { label: "Stroke", observed: 19.8, target: null },
    { label: "Height", observed: 118.4, target: 118.4 },
  ]);
});


test("projects Raw Data and next-specimen readiness without inventing defaults", () => {
  const ctx = model.cycleContext({
    workflow_agentic_task: { task_id: "run_utm_compression_cycle", block_order: [] },
    raw_data_export: { path: "/tmp/raw.csv", validated: true, row_count: 50 },
    next_specimen_readiness: {
      ready: true,
      next_test_completed: true,
      save_current_test: false,
      clearance_restored: true,
    },
  });

  assert.deepEqual(model.rawData(ctx), { path: "/tmp/raw.csv", validated: true, row_count: 50 });
  assert.equal(model.readiness(ctx).ready, true);
  assert.equal(model.readiness(ctx).save_current_test, false);
});


test("returns unavailable context for legacy reports", () => {
  assert.deepEqual(model.cycleContext({}), { available: false });
});
