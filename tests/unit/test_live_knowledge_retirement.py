"""Execute the Live GUI refresh with non-actuating transport boundaries."""
from pathlib import Path
import subprocess


def test_auxiliary_refresh_does_not_request_retired_knowledge_graph():
    source = Path("web/static/planning.js").read_text()
    function = source.split("async function refreshPlanningAuxiliaryState(session) {", 1)[1].split(
        "async function refreshPlanningState(", 1
    )[0]
    script = """
const assert = require('node:assert/strict');
let liveAuxRefreshInFlight = null, liveGuardianStatus = null, liveRecentEvents = [];
let liveLastSnapshot = null, liveLastSession = {}, liveKnowledgeRelationSummary = {};
const requests = [], errors = [];
const fetch = async url => { requests.push(url); return {ok: true, json: async () => ({events: []})}; };
const normalizeGuardianStatusPayload = x => x;
const refreshLivePrinterMonitorStatus = async () => null;
const refreshLiveObjectiveState = async () => {};
const refreshLiveUtmRuntimeStatus = () => {};
const refreshLiveGraphPayload = async () => {};
const refreshLiveRunDetails = async () => {};
const renderLiveRuntime = () => {};
const persistLivePlanningCache = () => {};
const markLiveSyncError = e => errors.push(String(e));
""" + "async function refreshPlanningAuxiliaryState(session) {" + function + """
(async () => {
  await refreshPlanningAuxiliaryState({state: {run_id: 'test'}});
  await refreshPlanningAuxiliaryState({state: {run_id: 'test'}});
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, ['/api/guardian/status', '/api/events/recent',
                              '/api/guardian/status', '/api/events/recent']);
  assert.equal(liveAuxRefreshInFlight, null);
})().catch(e => { console.error(e); process.exitCode = 1; });
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_attention_retains_runtime_gates_without_retired_relation_reviews():
    source = Path("web/static/planning.js").read_text()
    function = source.split("function liveAttentionCounts() {", 1)[1].split("\n}\n", 1)[0]
    script = """
const assert = require('node:assert/strict');
const liveApprovals = {pending: [{}, {}]};
const pendingAgentQuestions = () => [{}];
const pendingRuntimeFaults = () => [{kind: 'error'}, {kind: 'warning'}];
const eventTimelineKind = e => e.kind;
const liveKnowledgeRelationSummary = {pending: 12};
""" + "function liveAttentionCounts() {" + function + "\n}\n" + """
assert.deepEqual(liveAttentionCounts(), {approvals: 2, questions: 1, faults: 2, errors: 1, total: 5});
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
