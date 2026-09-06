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

test("a compact batch preserves every curve point and applies its latest pose and grasp once", () => {
  const context = viewer();
  const { api } = context;
  const status = { textContent: "idle" };
  const container = { dataset: {}, querySelector: s => s === "[data-atr-grasp-status]" ? status : null };
  let graspUpdates = 0;
  context.document.querySelectorAll = selector => {
    if (selector === "[data-atr-grasp-outcome]") { graspUpdates++; return [container]; }
    return [];
  };
  api.appendSample(sample(1));
  graspUpdates = 0;
  const samples = Array.from({ length: 128 }, (_, i) => sample(i + 2));
  const latest = { ...samples.at(-1), actual_rad: { Joint1: 0.4 }, target_rad: { Joint1: 0.5 },
    motion_state: { grasp_outcome: { status: "failed", attempt_index: 2 },
      grasp_achievement: { achieved: true, first_success: { status: "success", attempt_index: 1 } } } };
  api.consumePacket({ type: "joint_samples", sample_format: "compact-v1", samples, latest_sample: latest });
  assert.equal(api.runtime.history.length, 129);
  assert.equal(api.runtime.latestSequence, 129);
  assert.equal(api.runtime.latestActualRad.Joint1, 0.4);
  assert.equal(api.runtime.latestTargetRad.Joint1, 0.5);
  assert.equal(status.textContent, "success");
  assert.equal(graspUpdates, 1);
  assert.equal(api.runtime.latestMotionState.grasp_outcome.attempt_index, 2);
  api.runtime.selectedJoint = "Gripper";
  assert.equal(api.chartOption().series[0].data.length, 129);
  assert.deepEqual(Array.from(api.chartOption().series[0].data.at(-1)), [128, 29]);
  // Re-delivery must neither duplicate chart points nor reapply an older pose.
  api.consumePacket({ type: "joint_samples", samples: [sample(128)],
    latest_sample: { ...sample(128), actual_rad: { Joint1: 99 } } });
  assert.equal(api.runtime.history.length, 129);
  assert.equal(api.runtime.latestActualRad.Joint1, 0.4);
  assert.equal(graspUpdates, 1);
});

test("legacy full-sample history also updates status only once per batch", () => {
  const context = viewer();
  context.api.appendSample(sample(1));
  let updates = 0;
  context.document.querySelectorAll = selector => {
    if (selector === "[data-atr-grasp-outcome]") updates++;
    return [];
  };
  context.api.consumePacket({ type: "joint_history", samples: [sample(1), sample(2), sample(3)] });
  assert.equal(context.api.runtime.history.length, 3);
  assert.equal(updates, 1);
});

test("compact execution rollover keeps the new pose and runtime view without old curve points", () => {
  const { api } = viewer();
  api.appendSample({ ...sample(100), execution_index: 1 });
  const point = { ...sample(1, 0), execution_index: 2 };
  api.consumePacket({ type: "joint_samples", samples: [point],
    latest_sample: { ...point, actual_rad: { Gripper: 0.2 } },
    runtime_view: { execution: { status: "running" } } });
  assert.equal(api.runtime.executionIndex, 2);
  assert.deepEqual(Array.from(api.runtime.history, p => p.sequence), [1]);
  assert.equal(api.runtime.latestActualRad.Gripper, 0.2);
  assert.equal(api.runtime.runtimeView.execution.status, "running");
  const nextSession = { ...sample(1, 0), session_id: "next-rollout", execution_index: 1 };
  api.consumePacket({ type: "joint_history", session: { session_id: "next-rollout" },
    samples: [nextSession], latest_sample: { ...nextSession, actual_rad: { Gripper: 0.3 } } });
  assert.equal(api.runtime.sessionId, "next-rollout");
  assert.equal(api.runtime.history.length, 1);
  assert.equal(api.runtime.latestActualRad.Gripper, 0.3);
});

test("detail for a different sample cannot advance a compact batch's pose", () => {
  const { api } = viewer();
  api.consumePacket({ type: "joint_history", samples: [sample(1), sample(2)],
    latest_sample: { ...sample(100), actual_rad: { Joint1: 99 } } });
  assert.equal(api.runtime.latestSequence, 2);
  assert.notEqual(api.runtime.latestActualRad.Joint1, 99);
  assert.equal(api.runtime.history.length, 2);
});

for (const compact of [false, true]) {
  test(`release followed by idle in one ${compact ? "compact" : "legacy"} batch stays released`, () => {
    const context = viewer();
    const { api } = context;
    api.appendSample(sample(1));
    // Only replace geometry calculations; exercise the actual grasp/release latch.
    vm.runInContext(`
      specimenObject = () => ({});
      syncHeldSpecimenPose = () => true;
      settleSpecimenOnSupport = () => true;
      runtime.viewer = { environmentGroup: {},
        specimenGraspState: { held: true, attemptIndex: 1, releasedAttemptIndex: null } };
    `, context);
    const points = ["ungrasping", "idle"].map((gripper_state, index) => ({
      ...sample(index + 2),
      ...(compact ? { grasp_visual: { status: "success", attempt_index: 1, gripper_state } }
        : { motion_state: { grasp_outcome: { status: "success", attempt_index: 1 }, measured: { gripper_state } } }),
    }));
    api.consumePacket({ type: "joint_samples", samples: points,
      latest_sample: { ...sample(3), motion_state: {
        grasp_outcome: { status: "success", attempt_index: 1 }, measured: { gripper_state: "idle" } } } });
    assert.equal(api.runtime.viewer.specimenGraspState.held, false);
    assert.equal(api.runtime.viewer.specimenGraspState.releasedAttemptIndex, 1);
    assert.equal(api.runtime.history.length, 3);
  });
}

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
