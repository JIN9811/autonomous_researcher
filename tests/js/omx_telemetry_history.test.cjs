const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function viewer() {
  const source = fs.readFileSync("web/frontend/omx_telemetry_viewer/src/index.js", "utf8")
    .replace(/^import .*;$/gm, "").split("window.ATRRobotTelemetryCards =")[0];
  const context = vm.createContext({
    THREE: { Vector3: class {}, Quaternion: class {}, Euler: class {} },
    document: { querySelector: () => null, querySelectorAll: () => [] },
    window: { requestAnimationFrame: () => 1 },
  });
  vm.runInContext(source + `
    const originalApplyMotionState = applyMotionState;
    scheduleChartRender = () => {};
    applyMotionState = () => {};
    globalThis.api = { runtime, appendSample, consumePacket, chartOption, loadSnapshot,
      applyMotionState: originalApplyMotionState, applyArtifacts };
  `, context);
  return context;
}

const sample = (sequence, elapsed_s = sequence - 1) => ({
  type: "joint_sample", session_id: "test", sequence, elapsed_s,
  actual_source: { Joint1: sequence, Gripper: sequence % 100 },
  target_source: { Joint1: sequence + 1, Gripper: sequence % 100 + 1 },
});

test("all recorded samples survive live updates and reconnect history replacement", () => {
  const { api } = viewer();
  for (let i = 1; i <= 1501; i++) api.appendSample(sample(i));
  assert.equal(api.runtime.history.length, 1501);
  api.consumePacket({ type: "joint_history", samples: [sample(1), sample(2)] });
  api.consumePacket({ type: "joint_samples", samples: [sample(3), sample(4)] });
  assert.deepEqual(Array.from(api.runtime.history, s => s.sequence), [1, 2, 3, 4]);
});

test("joint chart uses session time, never rebases a partial history to zero", () => {
  const { api } = viewer();
  api.appendSample(sample(20, 24.5));
  api.appendSample(sample(21, 24.6));
  for (const joint of ["Joint1", "Gripper"]) {
    api.runtime.selectedJoint = joint;
    assert.equal(api.chartOption().series[0].data[0][0], 24.5);
  }
});

test("late snapshot cannot advance the history cursor and discard backfill", async () => {
  const context = viewer();
  const { api } = context;
  api.consumePacket({ type: "joint_history", samples: [sample(1), sample(2)] });
  context.fetch = async () => ({ ok: true, json: async () => ({ packet: sample(100), status: "live" }) });
  await api.loadSnapshot();
  api.appendSample(sample(3));
  assert.deepEqual(Array.from(api.runtime.history, s => s.sequence), [1, 2, 3]);
});

test("first success stays on result card while 3D uses the latest raw attempt", () => {
  const context = viewer();
  const status = { textContent: "idle" };
  const container = { dataset: {}, querySelector: s => s === "[data-atr-grasp-status]" ? status : null };
  context.document.querySelectorAll = s => s === "[data-atr-grasp-outcome]" ? [container] : [];
  vm.runInContext("applySpecimenGraspVisualization = outcome => { globalThis.rawVisualization = outcome; };", context);
  const first = { status: "success", attempt_index: 1, contact_gap: 3.5 };
  const latest = { status: "failed", attempt_index: 2, contact_gap: 0.1 };
  const achievement = { achieved: true, first_success: first };
  context.api.applyMotionState({ grasp_outcome: latest, grasp_achievement: achievement });
  assert.equal(status.textContent, "success");
  assert.equal(context.rawVisualization.attempt_index, 2);
  assert.equal(context.rawVisualization.status, "failed");
  context.api.applyArtifacts({ latest_grasp_outcome: latest, grasp_achievement: achievement });
  assert.equal(status.textContent, "success");
  context.api.applyMotionState({ grasp_outcome: { status: "idle" }, grasp_achievement: { achieved: false, first_success: null } });
  assert.equal(status.textContent, "idle");
});

test("reusing a rollout name starts fresh history when the logger execution changes", () => {
  const { api } = viewer();
  api.appendSample({ ...sample(100), execution_index: 1 });
  api.appendSample({ ...sample(1, 0), execution_index: 2 });
  assert.deepEqual(Array.from(api.runtime.history, s => s.sequence), [1]);
  api.consumePacket({ type: "joint_history", samples: [
    { ...sample(1), execution_index: 1 }, { ...sample(2), execution_index: 1 },
    { ...sample(1), execution_index: 2 }, { ...sample(2), execution_index: 2 },
  ] });
  assert.deepEqual(Array.from(api.runtime.history, s => s.sequence), [1, 2]);
  assert.ok(api.runtime.history.every(s => s.execution_index === 2));
});
