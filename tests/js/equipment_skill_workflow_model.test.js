"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  actionDefaults,
  actionSummary,
  adjustCropBox,
  cropOutputSize,
  cropPixelRect,
  deleteStep,
  duplicateStep,
  durationBounds,
  insertStep,
  moveStep,
  normalizeWorkflowState,
  updateStepField,
} = require("../../web/static/equipment_skill_workflow_model.js");


function sampleWorkflow() {
  return {
    schema: "atr.equipment_skill.v1",
    skill_id: "demo_skill",
    version: "1.0.0",
    program_ids: ["stale-program"],
    steps: [
      {step_id: "step-001", label: "Pause", action: {action: "wait", seconds: 2}, checkpoint_after: false},
      {step_id: "step-002", label: "Ready", action: {action: "wait_until_image", target: "ready", timeout_s: 10}, checkpoint_after: true},
    ],
  };
}


test("normalize clears stale compiled identity without mutating input", () => {
  const source = sampleWorkflow();
  const normalized = normalizeWorkflowState(source);
  assert.deepEqual(normalized.program_ids, []);
  assert.deepEqual(source.program_ids, ["stale-program"]);
});


test("move and duplicate preserve unique stable step IDs", () => {
  const moved = moveStep(sampleWorkflow(), "step-002", 0);
  const duplicated = duplicateStep(moved, "step-002");
  assert.deepEqual(moved.steps.map((item) => item.step_id), ["step-002", "step-001"]);
  assert.deepEqual(duplicated.steps.map((item) => item.step_id), ["step-002", "step-003", "step-001"]);
});


test("insert and delete preserve at least one step", () => {
  const inserted = insertStep(sampleWorkflow(), "step-001", "after", "wait");
  assert.equal(inserted.steps[1].action.action, "wait");
  const one = { ...sampleWorkflow(), steps: [sampleWorkflow().steps[0]] };
  assert.throws(() => deleteStep(one, "step-001"), /at least one step/i);
});


test("duration bounds include fixed and deadline waits", () => {
  assert.deepEqual(durationBounds(sampleWorkflow()), {minimum_s: 2, maximum_s: 12});
});


test("nested field updates are immutable and summaries stay concise", () => {
  const source = sampleWorkflow();
  const updated = updateStepField(source, "step-001", ["action", "seconds"], 4);
  assert.equal(source.steps[0].action.seconds, 2);
  assert.equal(updated.steps[0].action.seconds, 4);
  assert.equal(actionSummary(updated.steps[1]), "Wait for image · ready · 10s");
});


test("new action defaults use the canonical bridge field names", () => {
  assert.equal(actionDefaults("move_to").duration_sec, 0.2);
  assert.equal(actionDefaults("wait_for_file").pattern, "");
  assert.equal(actionDefaults("screenshot").checkpoint, "checkpoint");
});


test("target crop movement and resize stay inside normalized source bounds", () => {
  const box = [0.4, 0.4, 0.2, 0.2];
  assert.deepEqual(adjustCropBox(box, "move", 0.7, -0.7), [0.8, 0, 0.2, 0.2]);
  assert.deepEqual(adjustCropBox(box, "se", 0.7, 0.7), [0.4, 0.4, 0.6, 0.6]);
  assert.deepEqual(adjustCropBox(box, "nw", 0.3, 0.3), [0.59, 0.59, 0.01, 0.01]);
});


test("target crop output preserves aspect ratio and caps its longest side", () => {
  assert.deepEqual(cropOutputSize([0.1, 0.1, 0.5, 0.5], 1920, 1080), {
    source_width: 960,
    source_height: 540,
    output_width: 512,
    output_height: 288,
  });
  assert.deepEqual(cropOutputSize([0.1, 0.1, 0.1, 0.2], 200, 100), {
    source_width: 20,
    source_height: 20,
    output_width: 20,
    output_height: 20,
  });
});


test("target crop snaps source coordinates to exact pixels without resampling", () => {
  assert.deepEqual(cropPixelRect([0.860047, 0, 0.023851, 0.045437], 1920, 1080), {
    source_x: 1651,
    source_y: 0,
    source_width: 46,
    source_height: 49,
    output_width: 46,
    output_height: 49,
  });
});
