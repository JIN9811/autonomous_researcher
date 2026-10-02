const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("web/static/planning.js", "utf8");

function display() {
  const context = vm.createContext({
    currentRunEventSources: () => [{agent: "manipulation", status: "done"}],
    agentIdFromEvent: e => e.agent, agentIdFromStage: s => s,
    planningMessagesCache: [], liveApprovals: {pending: []},
    eventRequiresOperatorInput: () => false, eventPayload: e => e,
    isResolvedEmergencyLifecycleEvent: () => false, isTransientPrinterCommunicationEvent: () => false,
    agentIdFromMessage: m => m.agent, agentIdFromFreeText: t => t,
  });
  for (const name of ["manipulationExecutionDisplayState", "eventStatusForAgent"]) {
    const start = source.indexOf(`function ${name}(`);
    if (start >= 0) vm.runInContext(source.slice(start, source.indexOf("\n}", start) + 2), context);
  }
  return context.eventStatusForAgent;
}

function state(phase = "running") {
  return {run_id: "run-1", loop_count: 0, stage: "vision", current_experiment_spec: {specimen_id: "s-1"},
    agent_status: {manipulation_agent: {state: phase, success: phase === "done" ? true : null}},
    run_metadata: {manipulation_execution: {run_id: "run-1", loop_id: 0, specimen_id: "s-1",
      session_id: "rollout-1", state: phase, success: phase === "done" ? true : null}}};
}

test("returned agent call does not mark an active rollout done during Vision", () => {
  assert.equal(display()("manipulation", state(), true), "running");
});
test("stopping or interrupted unverified transfer remains pending", () => {
  assert.equal(display()("manipulation", state("waiting"), true), "waiting");
  assert.equal(display()("manipulation", state(), false), "waiting");
});
test("only verified transfer can display done", () => {
  assert.equal(display()("manipulation", state("done"), true), "done");
  const incomplete = state("done");
  incomplete.run_metadata.manipulation_execution.success = null;
  assert.equal(display()("manipulation", incomplete, true), "waiting");
});
test("prior run, loop, and specimen execution cannot show as active in this cycle", () => {
  for (const [key, value] of [["run_id", "other"], ["loop_id", 1], ["specimen_id", "other"]]) {
    const snapshot = state();
    snapshot.run_metadata.manipulation_execution[key] = value;
    assert.equal(display()("manipulation", snapshot, true), "idle");
  }
});
test("current runtime error takes precedence over a previously successful execution", () => {
  const snapshot = state("done");
  snapshot.agent_status.manipulation_agent = {state: "error", success: false};
  assert.equal(display()("manipulation", snapshot, true), "error");
});
test("a newly started manipulation call does not reuse an earlier done badge", () => {
  const snapshot = state("done");
  snapshot.stage = "manipulation";
  snapshot.agent_status.manipulation_agent = {state: "running", success: null};
  assert.equal(display()("manipulation", snapshot, true), "running");
});

test("paused, stopped, or approval-pending new calls do not reuse earlier done", () => {
  for (const [runtimeState, running, paused] of [
    ["running", true, true], ["running", false, false],
    ["waiting", true, false], ["waiting_approval", true, false],
  ]) {
    const snapshot = state("done");
    snapshot.stage = "manipulation";
    snapshot.is_paused = paused;
    snapshot.agent_status.manipulation_agent = {state: runtimeState, success: null};
    assert.equal(display()("manipulation", snapshot, running), "waiting");
  }
});
