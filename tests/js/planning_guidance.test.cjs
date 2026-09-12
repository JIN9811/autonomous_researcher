const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Execute production send/session/chat-filter hooks. Only unrelated page widgets
// and the final DOM paint are seams; the API packet is the canonical chat contract.
function harness(response) {
  const noop = () => {};
  const context = vm.createContext({
    console, planningMessageSubmitInFlight: false, liveBackendPlanningBusy: false,
    planningThinkingCount: 0, liveQuickActionBusy: false, planningPendingSpecimenInput: null,
    planningMessageInput: {value: ''}, planningMessagesCache: [], planningDisplayedMessages: [],
    liveSetupTransportVersion: 0, liveSetupAppliedVersion: 0, liveSetupSessionId: 'canonical',
    liveLastSession: {}, liveLastSnapshot: {}, planningSessionId: 'canonical',
    planningHistorySessionId: 'canonical', planningHistoryHasMore: false, planningHistoryTotal: 0,
    planningChatLog: {}, planningStageLabel: null, planningCycleLabel: null, planningRunDetail: null,
    queryGoal: '', painted: [], requestCount: 0,
    updatePlanningControls: noop, setChatStatus: noop, pushPlanningThinking: noop, popPlanningThinking: noop,
    collectPlanningPayload: message => ({message, session_id: 'canonical'}),
    fetch: async () => { context.requestCount++; return {ok: true, json: async () => response}; },
    resetLiveRunScopedStateForAuthoritativeSession: () => false,
    persistPlanningSessionId: noop, syncLiveSetupSession: noop, openPendingOperatorTeleopHandoff: noop,
    ensureEquipmentRuntimeSnapshot: noop, syncLiveBoVisualizationFromState: noop, liveRunningFlag: () => false,
    setLiveBackendPlanningBusy: noop, setPlanningDot: noop, setCompactTextWithTitle: noop,
    scheduleLiveMissionMarquee: noop, formatPlanningCycleLabel: () => '0', liveRunTopbarLabel: () => 'idle',
    renderSpecSummary: noop, resetPlanningMessageDisplayState: noop,
    mergePlanningMessages: (_old, incoming) => incoming, renderLiveRuntime: noop, persistLivePlanningCache: noop,
    isPlanningChatNearBottom: () => true, planningMessageKey: (m, i) => m.message_id || String(i),
    limitPlanningMessageCache: messages => messages, updateLiveChatUnreadFromMessages: noop,
    updatePlanningDisplayedMessages: messages => messages,
    renderPlanningMessageDom: messages => { context.painted = messages.map(m => ({role: m.role, content: m.content})); },
  });
  const source = fs.readFileSync(path.join(__dirname, '../../web/static/planning.js'), 'utf8');
  for (const name of ['messageSurfaces', 'parsePlanningSystemEvent', 'isPlanningSystemMessage',
    'isChatSurfaceMessage', 'renderPlanningMessages', 'applyPlanningSession', 'sendPlanningMessage']) {
    const start = source.search(new RegExp('(?:async )?function ' + name + '\\('));
    assert.ok(start >= 0);
    vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
  }
  return context;
}

for (const [message, guidance] of [
  ['yes', 'Please clarify the request and the pending action you intend to confirm.'],
  ['Tell me a joke', 'This chat supports the current research workflow.'],
]) {
  test(`canonical guidance reaches production Chat paint after ${message}`, async () => {
    const messages = [
      {role: 'operator', content: message, surface: ['chat'], visibility: 'user', message_id: 'operator'},
      {role: 'orchestrator', content: guidance, surface: ['chat'], visibility: 'user', message_id: 'guidance'},
    ];
    const ctx = harness({ok: true, session: {planning_session_id: 'canonical', message_total: 2,
      state: {run_id: 'unchanged', stage: 'idle', mode: 'test'}, messages}});
    await ctx.sendPlanningMessage(message);
    assert.equal(ctx.requestCount, 1);
    assert.deepEqual(JSON.parse(JSON.stringify(ctx.painted)), messages.map(({role, content}) => ({role, content})));
    assert.equal(ctx.planningMessageSubmitInFlight, false);
    assert.equal(ctx.planningHistoryTotal, 2);
  });
}
