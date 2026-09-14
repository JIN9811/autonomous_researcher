"""Run the real chat refresh and accordion handlers without a server or devices."""
from pathlib import Path
import subprocess
import pytest


def test_first_chat_opens_once_with_inline_controls():
    source = (Path(__file__).resolve().parents[2] / "web/static/planning.js").read_text()
    render = "function renderPlanningChatGroup(" + source.split(
        "function renderPlanningChatGroup(", 1
    )[1].split("function syncPlanningChatBubbleHeights(", 1)[0]
    script = """
const assert = require('node:assert/strict');
let planningInitialChatOpened = false;
const planningExpandedChatGroups = new Set();
const liveLastSession = null;
const planningLoopArtifactCache = new Map();
const escapeHtml = x => String(x ?? '');
const formatTime = () => '12:00';
const chatMessageSummaryLine = () => 'Greeting';
const chatGroupAgentDescriptor = () => ({label:'Orchestrator'});
const renderChatGroupIcon = () => '<img alt="agent">';
const renderChatGroupProgress = () => '';
const renderPlanningChatMessageDetail = (m, i, controls) => controls;
const group = {key:'greeting',role:'orchestrator',messages:[{content:'Hello'}]};
""" + render + """
const html = renderPlanningChatGroup(group, 0);
assert.match(html, /is-expanded/);
assert.match(html, /planning-agent-chat-hide/);
assert.match(html, /<img alt="agent">/);
assert.ok(!html.includes('planning-agent-chat-expanded-tools'));
planningExpandedChatGroups.delete('greeting');
assert.match(renderPlanningChatGroup(group, 0), /is-collapsed/);
assert.match(renderPlanningChatGroup({...group,key:'second'}, 1), /is-collapsed/);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("immediate", [False, True])
def test_chat_expansion_survives_refresh_and_preserves_accordion_rules(immediate):
    source = (Path(__file__).resolve().parents[2] / "web/static/planning.js").read_text()

    def function(name, next_name):
        return "function " + name + source.split("function " + name, 1)[1].split(
            "function " + next_name, 1
        )[0]

    refresh = function("updatePlanningDisplayedMessages(", "renderPlanningMessages(")
    reveal = function("planningChatItemRevealKey(", "flattenPlanningChatItems(")
    handlers = source.split('  planningChatLog.querySelectorAll(".planning-agent-chat-open', 1)[1]
    handlers = '  planningChatLog.querySelectorAll(".planning-agent-chat-open' + handlers.split("\n}\n", 1)[0]
    script = """
const assert = require('node:assert/strict');
const item = key => ({type: 'group', group: {key, kind: key.startsWith('loop:') ? 'loop_summary' : 'agent', messages: [key]}});
const limitPlanningMessageCache = x => x;
const buildPlanningChatItems = x => x.map(item);
const flattenPlanningChatItems = xs => xs.flatMap(x => x.group.messages);
const syncPlanningDisplayedMessageKeys = () => {};
const schedulePlanningMessageReveal = () => {};
const compactPlanningRevealBacklog = xs => xs;
const window = {clearTimeout() {}};
let planningDisplayInitialized = true, planningHistoryLoading = false;
let planningDisplayedMessages = ['first', 'second'];
let planningMessageRevealQueue = [], planningMessageRevealTimer = null;
const planningDisplayedChatItemKeys = new Set(['group:first', 'group:second']);
const planningExpandedChatGroups = new Set(['first']);
""" + reveal + refresh + """
updatePlanningDisplayedMessages(['first', 'second']);
assert.deepEqual([...planningExpandedChatGroups], ['first'], 'unchanged refresh must preserve expansion');
updatePlanningDisplayedMessages(['first', 'second', 'third']);
assert.deepEqual([...planningExpandedChatGroups], ['first'], 'new messages must not collapse an existing group');
planningExpandedChatGroups.add('removed');
updatePlanningDisplayedMessages(['first', 'second']);
assert.deepEqual([...planningExpandedChatGroups], ['first'], 'removed groups must be pruned');
const callbacks = {};
const planningChatLog = {querySelectorAll(selector) {
  const kind = selector.includes('chat-open') ? 'open' : 'hide';
  return ['first', 'second', 'third', 'fourth', 'loop:1'].map(key => ({dataset: {chatGroupKey: key}, disabled: false,
           addEventListener(event, callback) { callbacks[`${kind}:${key}`] = callback; }}));
}};
let planningMessagesCache = ['first', 'second', 'third', 'fourth'];
const liveLastSession = {};
const renderPlanningMessages = (messages, options) => updatePlanningDisplayedMessages(messages, options);
const persistLiveUiState = () => {};
const persistLivePlanningCache = () => {};
""" + handlers + """
const event = {preventDefault() {}, stopPropagation() {}};
callbacks['open:second'](event);
callbacks['open:third'](event);
assert.deepEqual([...planningExpandedChatGroups], ['first', 'second', 'third']);
callbacks['open:first'](event);
callbacks['open:fourth'](event);
assert.deepEqual([...planningExpandedChatGroups], ['second', 'third', 'fourth'], 'fourth closes oldest; clicking an open group does not reorder it');
callbacks['hide:third'](event);
assert.deepEqual([...planningExpandedChatGroups], ['second', 'fourth']);
// Completed-loop grouping replaces its detailed bubbles with a new summary key.
planningMessagesCache = ['loop:1', 'fourth'];
updatePlanningDisplayedMessages(planningMessagesCache, {immediate: IMMEDIATE});
assert.deepEqual([...planningExpandedChatGroups], ['fourth'], 'compression closes only replaced groups, including immediate refresh');
callbacks['open:loop:1'](event);
updatePlanningDisplayedMessages(planningMessagesCache);
updatePlanningDisplayedMessages(planningMessagesCache, {immediate: true});
assert.deepEqual([...planningExpandedChatGroups], ['fourth', 'loop:1'], 'reopened summary survives repeated completion refresh');
planningMessagesCache = ['loop:1', 'fourth', 'first', 'second'];
callbacks['open:first'](event);
callbacks['open:second'](event);
assert.deepEqual([...planningExpandedChatGroups], ['loop:1', 'first', 'second'], 'summaries follow the same three-group limit');
"""
    script = script.replace("IMMEDIATE", str(immediate).lower())
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
