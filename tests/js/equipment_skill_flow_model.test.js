const test = require("node:test");
const assert = require("node:assert/strict");
const model = require("../../web/static/equipment_skill_flow_model.js");

test("adding a block does not require a deployed Skill", () => {
  let flow = model.empty("utm_windows_v1");
  flow = model.addBlock(flow);

  assert.equal(flow.blocks.length, 1);
  assert.equal(flow.blocks[0].label, "Equipment Task");
  assert.deepEqual(flow.blocks[0].skill, { skill_id: "", skill_version: "" });
  assert.equal(flow.blocks[0].agentic.task, "Equipment Task");
  assert.equal(flow.blocks[0].agentic.completed, "__complete__");
  assert.equal(flow.blocks[0].vision.enabled, false);
  assert.equal(model.addVisionGate, undefined);
});

test("Agentic Task is the canonical block name and is independent of Skill binding", () => {
  let flow = model.addBlock(model.empty("utm_windows_v1"), { skill_id: "program1", version: "1.0.0", name: "Program 1" });
  flow = model.updateBlock(flow, "block_01", "agentic.task", "Run tensile test");
  flow = model.updateBlock(flow, "block_01", "skill.skill_id", "program2");

  assert.equal(flow.blocks[0].agentic.task, "Run tensile test");
  assert.equal(flow.blocks[0].label, "Run tensile test");
  assert.equal(flow.blocks[0].skill.skill_id, "program2");
});

test("reordering blocks rebuilds bounded next routes", () => {
  let flow = model.empty("utm_windows_v1");
  flow = model.addBlock(flow, { skill_id: "prepare", version: "1.0.0" });
  flow = model.addBlock(flow, { skill_id: "test", version: "2.0.0" });
  flow = model.moveBlock(flow, "block_02", -1);

  assert.equal(flow.blocks[0].id, "block_02");
  assert.equal(flow.blocks[0].agentic.completed, "next");
  assert.equal(flow.blocks[1].agentic.completed, "__complete__");
});

test("Vision is edited inside its owning Skill block", () => {
  let flow = model.addBlock(model.empty("utm_windows_v1"), { skill_id: "prepare", version: "1.0.0" });
  flow = model.updateBlock(flow, "block_01", "vision.enabled", true);
  flow = model.updateBlock(flow, "block_01", "vision.task_id", "utm_motion_confirm");
  flow = model.updateBlock(flow, "block_01", "vision.blocking", false);

  assert.equal(flow.blocks[0].vision.enabled, true);
  assert.equal(flow.blocks[0].vision.task_id, "utm_motion_confirm");
  assert.equal(flow.blocks[0].vision.blocking, false);
  assert.equal(flow.blocks[0].vision.condition, undefined);
});

test("removing a block keeps the remaining sequence valid", () => {
  let flow = model.empty("utm_windows_v1");
  flow = model.addBlock(flow, { skill_id: "prepare", version: "1.0.0" });
  flow = model.addBlock(flow, { skill_id: "test", version: "2.0.0" });
  flow = model.removeBlock(flow, "block_01");

  assert.equal(flow.blocks.length, 1);
  assert.equal(flow.blocks[0].agentic.completed, "__complete__");
});

test("applying the UTM cycle template preserves the selected Profile identity", () => {
  const current = model.empty("utm_windows_v1");
  const template = {
    schema: "atr.equipment_skill_flow.v1",
    flow_id: "template-source",
    profile_id: "template-source",
    agentic_task_id: "run_utm_compression_cycle",
    blocks: [
      {
        id: "prepare_next_specimen",
        label: "Move Jigs for Next Specimen",
        skill: { skill_id: "", skill_version: "" },
        agentic: { task: "Move Jigs for Next Specimen", completed: "__complete__", failed: "__blocked__" },
        vision: { enabled: false, task_id: "", detected: "__complete__", not_detected: "__blocked__", timeout: "__blocked__", error: "__blocked__" },
      },
    ],
  };

  const next = model.applyTemplate(current, template);

  assert.equal(next.profile_id, "utm_windows_v1");
  assert.equal(next.flow_id, "utm_windows_v1");
  assert.equal(next.agentic_task_id, "run_utm_compression_cycle");
  assert.equal(next.blocks[0].id, "prepare_next_specimen");
  assert.notEqual(next.blocks, template.blocks);
});
