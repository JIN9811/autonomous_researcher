const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("web/static/planning.js", "utf8");

function display(events = [{ agent: "specimen", status: "done" }], messages = []) {
  const context = vm.createContext({
    currentRunEventSources: () => events,
    LIVE_AGENTS: ["orchestrator", "design", "specimen", "vision", "manipulation", "equipment", "analysis", "knowledge", "bo", "guardian"].map(id => ({ id, stage: id })),
    planningMessagesCache: messages, liveApprovals: { pending: [] },
    eventRequiresOperatorInput: () => false, eventPayload: e => e.payload || {},
    isResolvedEmergencyLifecycleEvent: () => false,
  });
  for (const name of ["knownLiveAgent", "agentIdFromStage", "agentIdFromRole", "agentIdFromFreeText", "agentIdFromMessage", "agentIdFromEvent", "nestedPrinterRuntimeObjects", "isTransientPrinterCommunicationEvent", "specimenPrinterRuntimeState", "specimenExecutionDisplayState", "eventStatusForAgent"]) {
    const start = source.indexOf(`function ${name}(`);
    if (start >= 0) vm.runInContext(source.slice(start, source.indexOf("\n}", start) + 2), context);
  }
  const render = (state, running = true) => context.eventStatusForAgent("specimen", state, running);
  render.classifyEvent = event => context.agentIdFromEvent(event);
  return render;
}

function state(phase = "running") {
  return { run_id: "r1", loop_count: 0, stage: "vision", current_experiment_spec: { specimen_id: "s1" },
    agent_status: { specimen_agent: { state: phase, success: phase === "done" ? true : null } },
    run_metadata: { specimen_execution: { run_id: "r1", loop_id: 0, specimen_id: "s1", state: phase, success: phase === "done" ? true : null } } };
}

test("SPC submission is not done while ActiveCam verification is pending", () => {
  assert.equal(display()(state()), "running");
  assert.equal(display()(state(), false), "waiting");
  assert.equal(display()({ ...state(), is_paused: true }), "waiting");
});
test("unrelated printer events cannot override current verified SPC state", () => {
  assert.equal(display([{ agent: "vision", status: "running" }])(state("done")), "done");
});
test("incomplete success and previous loop/specimen cannot display done", () => {
  const incomplete = state("done");
  incomplete.run_metadata.specimen_execution.success = null;
  assert.equal(display()(incomplete), "waiting");
  for (const [key, value] of [["run_id", "old"], ["loop_id", 1], ["specimen_id", "old"]]) {
    const snapshot = state("done");
    snapshot.run_metadata.specimen_execution[key] = value;
    assert.equal(display()(snapshot), "idle");
  }
});
test("failure and a restarted SPC call override an earlier successful display", () => {
  const snapshot = state("done");
  snapshot.agent_status.specimen_agent = { state: "error", success: false };
  assert.equal(display()(snapshot), "error");
  snapshot.stage = "specimen";
  snapshot.agent_status.specimen_agent = { state: "running", success: null };
  assert.equal(display()(snapshot), "running");
  assert.equal(display()({ ...snapshot, is_paused: true }), "waiting");
  assert.equal(display()(snapshot, false), "waiting");
});
test("virtual completion without an execution record retains the existing display", () => {
  const snapshot = state("done");
  delete snapshot.run_metadata.specimen_execution;
  assert.equal(display()(snapshot), "done");
});
test("a next-loop SPC exception cannot be hidden by the previous execution record", () => {
  const snapshot = state("done");
  snapshot.loop_count = 1;
  snapshot.agent_status.specimen_agent = { state: "error", success: false };
  for (const stage of ["specimen", "error", "guardian", "complete"]) {
    assert.equal(display()({ ...snapshot, stage }, stage !== "complete"), "error");
  }
});
test("approval for a new SPC invocation is waiting, not prior success", () => {
  const snapshot = state("done");
  snapshot.stage = "specimen";
  snapshot.agent_status.specimen_agent = { state: "waiting_approval", success: null };
  assert.equal(display()(snapshot), "waiting");
});

test("orchestrator bootstrap mentioning printers is not an SPC event or completion", () => {
  const event = { event_type: "planning_bootstrap", level: "INFO",
    message: "Live GUI orchestrator_plan call completed.",
    payload: { latest: { content: "Design Agent -> Specimen Making Agent; Bambu printer readiness" } } };
  const render = display([event]);
  assert.equal(render.classifyEvent(event), "orchestrator");
  assert.equal(render({ run_id: "r1", stage: "idle", loop_count: 0, agent_status: {}, run_metadata: {} }, false), "idle");
});

test("SPC diagnostic events and messages are not completion evidence", () => {
  const snapshot = { run_id: "r1", stage: "idle", loop_count: 0, agent_status: {}, run_metadata: {} };
  assert.equal(display([{ agent: "specimen", level: "INFO", message: "Printer profile inspected" }])(snapshot, false), "idle");
  assert.equal(display([], [{ role: "specimen_ai", content: "Select printer settings" }])(snapshot, false), "idle");
});

test("SPC without a scoped execution needs explicit successful runtime completion", () => {
  const snapshot = state("done");
  delete snapshot.run_metadata.specimen_execution;
  const render = display();
  assert.equal(render(snapshot), "done");
  snapshot.agent_status.specimen_agent.success = null;
  assert.equal(render(snapshot), "idle");
  snapshot.agent_status.specimen_agent = { state: "waiting_approval", success: null };
  assert.equal(render(snapshot), "waiting");
  snapshot.agent_status.specimen_agent = { state: "running", success: null };
  assert.equal(render(snapshot), "running");
  assert.equal(render(snapshot, false), "waiting");
});

test("a completed run cannot promote a nonterminal SPC status from success alone", () => {
  const snapshot = { stage: "complete", agent_status: { specimen_agent: { state: "waiting", success: true } }, run_metadata: {} };
  assert.equal(display()(snapshot, false), "waiting");
});

test("SPC diagnostic error and actual printer progress remain visible without completion evidence", () => {
  const snapshot = { run_id: "r1", stage: "idle", agent_status: {}, run_metadata: {} };
  assert.equal(display([{ agent: "specimen", level: "ERROR", message: "Printer connection failed" }])(snapshot), "error");
  assert.equal(display([{ agent: "specimen", status: "PRINTING" }])(snapshot), "running");
});

test("actual specimen events keep their ownership when their text mentions another agent", () => {
  const render = display([]);
  assert.equal(render.classifyEvent({ event_type: "planning_specimen_result", payload: { agent_id: "specimen", detail: "Next: Vision Agent" } }), "specimen");
});
