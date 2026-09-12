"""Isolated static Setup/Chat audit: real template, CSS and planning hooks; no server.

All requests are intercepted. No application import, model, service or hardware.
The approved fallback is installed Playwright after Browser discovery was empty.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import mimetypes
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
URL = "https://setup-fixture.invalid/planning"


def block(index=1, **changes):
    return {"block_id": f"block-{index}", "topic_key": f"owner.topic.{index}",
            "title": f"Research setting {index}", "owners": ["orchestrator_agent"],
            "revision": 3, "draft_values": {"research.goal": "Improve absorption"},
            "confirmed_values": {"research.goal": "Confirmed goal"},
            "effective_values": {"research.goal": "Currently running goal"},
            "agreement_status": "draft", "application_status": "not_applied", "receipts": {},
            "proposal_ids": [f"proposal-{index}"], "current_draft_proposal_id": f"proposal-{index}",
            "active": True, "editable": True, "target": "next_run",
            "fields": [{"id": "research.goal", "field": "active_goal", "type": "string", "required": True}],
            **changes}


def session(count=3):
    return {"planning_session_id": "canonical-server-a", "is_running": False,
            "messages": [], "message_total": 0, "has_more_messages": False,
            "state": {"run_id": "fixture-run", "stage": "idle", "mode": "test",
                      "active_goal": "Static fixture; no execution", "run_metadata": {},
                      "pending_request": None,
                      "setup": {"schema": "experimental_setup.v1", "session_id": "canonical-server-a",
                                "revision": 9, "event_seq": 9, "projection_id": "projection-initial",
                                "blocks": [block(i) for i in range(1, count + 1)],
                                "owners": [{"node_id": "plugin-node", "step_id": None,
                                            "module_id": "modules/third-party", "stage": None,
                                            "handler": "agent.plugin", "owner": "third_party_agent",
                                            "role": "overlay", "executable": False, "contract": {},
                                            "contract_version": "unknown", "contract_status": "unknown",
                                            "setup": {"write_enabled": False, "fields": []},
                                            "availability": {"owner": "third_party_agent", "capability": "inspect", "status": "unknown"}}]}}}


HOOKS = [
    "syncLiveSetupSession", "acceptLiveSetupSnapshot", "onEditSetupBlock", "exitLiveSetupEditing",
    "renderLiveSetupEditContext", "renderLiveExperimentSetupPanel", "refreshLiveSetupState", "onSetupBlockAction",
    "applyPlanningSession", "collectPlanningPayload", "collectOptionalConstraints", "sendPlanningMessage",
    "connectPlanningEventStream", "setLiveChatCollapsed", "applyLiveAgentLayoutMode", "setLiveChatTargetMode",
    "renderLiveChatContextStrip", "liveChatContextSummary", "liveRunningFlag", "shouldFreezeCompletedTestRun",
    "persistPlanningSessionId", "ensurePlanningSessionId", "liveSessionStorage", "validLiveChatTarget",
    "liveAgentNeedsChatPanel", "liveChatCanManualCollapse", "liveAgentChatMode", "knownLiveAgent",
]


def extract(source, name):
    match = re.search(r"(?:async )?function " + name + r"\(", source)
    assert match, f"Missing actual planning hook: {name}"
    end = source.index("\n}", match.start()) + 2
    return source[match.start():end]


def fixture_script():
    source = (ROOT / "web/static/planning.js").read_text()
    # Keep declarations of the new production state, not a separate implementation.
    declarations = "\n".join(re.findall(r"^(?:let|const) liveSetup\w+[^\n]+", source, re.M))
    dom_names = ["planningGoalInput", "planningMessageInput", "planningChatStatus", "planningStageLabel",
                 "planningCycleLabel", "planningRunDetail", "liveExperimentSetupPanel", "liveChatContextStrip",
                 "liveChatTarget", "liveChatMode", "btnLiveChatCollapse", "btnLiveChatRestore"]
    dom = "\n".join(re.search(r"^const " + name + r" = [^\n]+", source, re.M).group() for name in dom_names)
    hooks = "\n".join(extract(source, name) for name in HOOKS)
    return declarations + "\n" + dom + r"""
let planningSessionId='tab-local-id', liveLastSession={}, liveLastSnapshot={};
let planningFreshSessionInitialized=false, liveChatCollapsed=false, liveChatUnreadInitialized=true;
let liveSelectedAgent='orchestrator', liveReportPage='agent', liveCurrentView='report';
let liveSelectedGraphNodeId='', liveSelectedEventKey='', liveTimelineFilter='all', livePinnedFindings=[];
let planningMaterialInput=null, planningSizeInput=null, planningTimeInput=null;
let queryGoal='', queryBackend='test', planningHistorySessionId='', planningHistoryHasMore=false;
let planningHistoryTotal=0, planningMessagesCache=[], planningPendingSpecimenInput=null;
let planningMessageSubmitInFlight=false, liveBackendPlanningBusy=false, planningThinkingCount=0, liveQuickActionBusy=false;
let liveRecentEvents=[], liveSyncState='', liveStreamState='';
const LIVE_AGENTS=[{id:'orchestrator',stage:'orchestrator',chat:{mode:'persistent'}}];
const LIVE_CHAT_TARGET_SPECIALS=new Set(['current_agent','selected_agent']);
const LIVE_CHAT_PERSISTENT_MODES=new Set(['persistent','always','required']);
const noop=()=>{};
const markLiveChatMessagesRead=noop, scheduleLiveGraphScaleRefresh=noop, renderLiveReportToolbar=noop;
const syncLiveChatUnreadIndicators=noop, persistLiveUiState=noop, resetLiveRunScopedStateForAuthoritativeSession=()=>false;
const openPendingOperatorTeleopHandoff=noop, ensureEquipmentRuntimeSnapshot=noop, syncLiveBoVisualizationFromState=noop;
const setLiveBackendPlanningBusy=noop, setPlanningDot=noop, scheduleLiveMissionMarquee=noop;
const formatPlanningCycleLabel=()=> 'Cycle —', liveRunTopbarLabel=()=> 'Static fixture';
const renderSpecSummary=noop, resetPlanningMessageDisplayState=noop, persistLivePlanningCache=noop;
const mergePlanningMessages=(a,b)=>b, updatePlanningControls=noop;
const pushPlanningThinking=()=>{planningThinkingCount++;},popPlanningThinking=()=>{planningThinkingCount--;};
const selectedTimelineEvent=()=>null, selectedReportSectionLabel=()=>'',selectedReportSectionText=()=>'';
const resolveLiveChatTarget=t=>t, liveAgentLabel=t=>t, liveAgentShort=t=>t;
const liveViewShort=t=>t,liveModeShort=t=>t,compactRunId=t=>t,compactText=t=>String(t);
const liveChatUnreadLabel=()=>'', liveCurrentRunId=()=>liveLastSession.state?.run_id||'';
const eventPayload=e=>e.payload||{}, agentIdFromEvent=()=> 'orchestrator';
const shouldRefreshPlanningForRuntimeEvent=()=>false, schedulePlanningRefresh=noop;
const updateLiveBoVisualizationCards=noop,hydrateLiveBoVisualization=noop;
const setCompactTextWithTitle=(el,text,title)=>{if(el){el.textContent=text;el.title=title;}};
const setChatStatus=(label,cls,title)=>{planningChatStatus.textContent=label;planningChatStatus.title=title||label;};
const markLiveStreamState=(s)=>{liveStreamState=s;};
function renderLiveRuntime(){renderLiveExperimentSetupPanel();renderLiveChatContextStrip();}
function renderPlanningMessages(messages){planningMessagesCache=messages; document.getElementById('planning-chat-log').textContent=messages.map(m=>m.content).join('\n');}
class FixtureEventSource {constructor(url){if(url!='/api/events/stream')throw Error('Unexpected SSE');window.fixtureStream=this;this.listeners={};}addEventListener(name,fn){this.listeners[name]=fn;}}
window.EventSource=FixtureEventSource;
window.emitSetup=(setup)=>fixtureStream.listeners.update({data:JSON.stringify({event_type:'planning_setup_changed',payload:{setup}})});
""" + hooks + r"""
liveChatTarget.innerHTML='<option value="selected_agent">Selected agent</option><option value="orchestrator">Orchestrator</option>';
btnLiveChatCollapse.addEventListener('click',()=>setLiveChatCollapsed(true));
document.getElementById('btn-planning-send').addEventListener('click',()=>sendPlanningMessage(planningMessageInput.value));
planningMessageInput.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();sendPlanningMessage(planningMessageInput.value);}});
// The existing report toolbar is present; its unrelated report renderer is not run.
const toggle=document.createElement('button');toggle.type='button';toggle.className='btn';toggle.textContent='Toggle Chat';
toggle.addEventListener('click',()=>setLiveChatCollapsed(!liveChatCollapsed));document.getElementById('live-report-toolbar').append(toggle);
document.getElementById('live-report-panel').textContent='Static surrounding report · graph/camera/plot behaviors are not run.';
connectPlanningEventStream();
"""


class Fixture:
    def __init__(self):
        self.state = session()
        self.requests = []
        self.unexpected = []
        self.results = {}
        self.normalize_next = False
        self.hold_next_action = False
        self.held_action = None

    def route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != "setup-fixture.invalid":
            self.unexpected.append(request.url)
            route.fulfill(status=403, body="External access blocked by fixture")
            return
        if parsed.path == "/planning":
            template = (ROOT / "web/templates/planning.html").read_text().replace("{{ title }}", "Experimental Setup isolated audit")
            # Only new Setup script is allowed. All startup/service scripts are excluded.
            template = re.sub(r'<script\b[^>]*src="(?!/static/experimental_setup\.js)[^"]+"[^>]*>\s*</script>', '', template)
            route.fulfill(content_type="text/html", body=template)
        elif parsed.path.startswith("/static/"):
            asset = ROOT / "web" / parsed.path.lstrip("/")
            if asset.is_file():
                route.fulfill(content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream", body=asset.read_bytes())
            else:
                self.unexpected.append(request.url)
                route.fulfill(status=404, body="Missing fixture asset")
        elif parsed.path == "/api/planning/session" and request.method == "GET":
            self.requests.append((request.method, parsed.path, None))
            route.fulfill(json=self.state)
        elif parsed.path == "/api/planning/setup/actions" and request.method == "POST":
            if self.hold_next_action:
                self.hold_next_action = False
                self.held_action = route
                return
            body = request.post_data_json
            self.requests.append((request.method, parsed.path, body))
            assert set(body) == {"action", "proposal_id", "expected_revision", "request_id", "session_id", "target"}
            assert body["session_id"] == self.state["planning_session_id"] and body["target"] == "next_run"
            if body["request_id"] in self.results:
                original, result = self.results[body["request_id"]]
                assert body == original
                route.fulfill(json=result)
                return
            setup = self.state["state"]["setup"]
            current = next((b for b in setup["blocks"] if b["current_draft_proposal_id"] == body["proposal_id"]), None)
            if not current or current["revision"] != body["expected_revision"]:
                route.fulfill(status=409, json={"detail": "stale block revision"})
                return
            current["revision"] += 1
            if self.normalize_next:
                self.normalize_next = False
                current["current_draft_proposal_id"] = "normalized-proposal"
                current["draft_values"] = {"research.goal": "Owner-normalized goal"}
                current["validation_status"] = "requires_confirmation"
                message = "Owner-normalized values are shown in a new draft. Review and confirm again."
            else:
                current["current_draft_proposal_id"] = None
                if body["action"] == "confirm":
                    current["confirmed_values"] = deepcopy(current["draft_values"])
                    current["agreement_status"] = "confirmed"
                    current["application_status"] = "scheduled"
                else:
                    current["draft_values"] = deepcopy(current["confirmed_values"] or {})
                message = "Setup updated for the next new run. No run was started."
            self.advance()
            result = {"ok": True, "setup": deepcopy(setup), "message": message}
            self.results[body["request_id"]] = (body, result)
            route.fulfill(json=result)
        elif parsed.path == "/api/planning/message" and request.method == "POST":
            body = request.post_data_json
            self.requests.append((request.method, parsed.path, body))
            setup = self.state["state"]["setup"]
            context = body.get("setup_context")
            if context:
                current = next(b for b in setup["blocks"] if b["block_id"] == context["block_id"])
                if current["revision"] != context["revision"]:
                    route.fulfill(status=409, json={"detail": "stale block revision"})
                    return
                assert set(context) == {"block_id", "revision"}
                assert body["session_id"] == self.state["planning_session_id"]
                current["draft_values"] = {"research.goal": body["message"]}
                current["revision"] += 1
                current["current_draft_proposal_id"] = "chat-proposal"
                self.advance()
                # The real server can emit Setup SSE before completing Chat HTTP.
                request.frame.page.evaluate("emitSetup", setup)
                self.state["messages"] = [{"role": "operator", "content": body["message"]},
                                          {"role": "orchestrator", "content": "Draft proposed; no run started."}]
                self.state["message_total"] = 2
            route.fulfill(json={"ok": True, "decision": {"status": "proposed"}, "session": self.state})
        else:
            self.unexpected.append((request.method, request.url))
            route.fulfill(status=403, body="Operating API blocked by fixture")

    def advance(self):
        setup = self.state["state"]["setup"]
        setup["revision"] += 1
        setup["event_seq"] += 1
        setup["projection_id"] = f"projection-{setup['revision']}"


def open_page(context, fixture):
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # Expected HTTP409 console messages are collected separately, not hidden.
    console = []
    page.on("console", lambda message: console.append((message.type, message.text)) if message.type in {"error", "warning"} else None)
    page.goto(URL)
    page.add_script_tag(content=fixture_script())
    page.evaluate("state=>applyPlanningSession(state)", fixture.state)
    page.evaluate("setLiveChatCollapsed(true)")
    page.evaluate("Promise.all(document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})))")
    assert page.url == URL and page.title() == "Experimental Setup isolated audit"
    expect(page.locator("#live-experiment-setup-panel")).to_contain_text("Research setting 1")
    return page, errors, console


def screenshot(page, out, name):
    dest = out / f"{name}.png"
    page.screenshot(path=str(dest), full_page=False)
    return str(dest)


def audit(out):
    out.mkdir(parents=True, exist_ok=True)
    fixture = Fixture()
    screenshots, checks = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        context.route("**/*", fixture.route)
        try:
            page, errors, console = open_page(context, fixture)
            panel = page.locator("#live-experiment-setup-panel")
            first = panel.locator('[data-block-id="block-1"]')
            first.locator("summary").click()
            expect(first).to_contain_text("Currently running goal")
            screenshots.append(screenshot(page, out, "desktop-values"))
            # Real renderer receives another state: DOM identity/details/focus stay intact.
            first.get_by_role("button", name="Confirm Research setting 1", exact=True).focus()
            page.evaluate("window.auditCard=document.querySelector('[data-block-id=\"block-1\"]');window.auditFocus=document.activeElement")
            changed = deepcopy(fixture.state["state"]["setup"])
            changed["projection_id"] = "a-new-graph-hash"
            changed["blocks"][1]["editable"] = False
            changed["owners"][0]["availability"]["status"] = "unavailable"
            page.evaluate("emitSetup", changed)
            assert page.evaluate("auditCard===document.querySelector('[data-block-id=\"block-1\"]') && auditFocus===document.activeElement && auditCard.querySelector('details').open")
            expect(panel).to_contain_text("unavailable")
            assert panel.locator('[data-block-id="block-2"] button').first.is_disabled()
            checks.append("Equal-revision graph/status event; stable card/detail/focus")
            # Old and foreign events cannot corrupt the canonical projection.
            old = deepcopy(changed); old["revision"] = 1
            old["blocks"][0]["title"] = "WRONG OLD TITLE"
            page.evaluate("emitSetup", old)
            old["revision"] = 999; old["session_id"] = "foreign-session"
            page.evaluate("emitSetup", old)
            expect(first).to_contain_text("Research setting 1")
            # An in-flight snapshot older than that graph event is not authoritative.
            page.evaluate("state=>applyPlanningSession(state,{setupVersion:0})", fixture.state)
            expect(panel).to_contain_text("unavailable")
            checks.append("Old revision/foreign session/stale equal-revision HTTP response ignored")
            page.evaluate("planningMessageInput.value='Unsent idea preserved'")
            before = len(fixture.requests)
            first.get_by_role("button", name="Edit Research setting 1", exact=True).click()
            expect(page.locator("#planning-message-input")).to_be_focused()
            expect(page.locator("#planning-message-input")).to_have_value("Unsent idea preserved")
            assert len(fixture.requests) == before
            expect(page.locator("#live-chat-context-strip")).to_contain_text("Editing: Research setting 1")
            assert page.locator("#live-chat-target").input_value() == "orchestrator"
            screenshots.append(screenshot(page, out, "desktop-editing-chat"))
            # Runtime status update does not replace the active composer or its selection.
            page.evaluate("planningMessageInput.setSelectionRange(3,8)")
            page.evaluate("emitSetup", changed)
            assert page.evaluate("document.activeElement===planningMessageInput && planningMessageInput.selectionStart===3 && planningMessageInput.selectionEnd===8")
            expect(page.locator("#planning-message-input")).to_have_value("Unsent idea preserved")
            # Historical report selection is deliberately hostile; Setup never consults it.
            page.evaluate("window.selectedReportModel=()=>({state:{setup:{revision:0,blocks:[]}}});renderLiveExperimentSetupPanel()")
            page.locator("#planning-message-input").fill("Change only the next run goal")
            page.locator("#planning-message-input").press("Control+Enter")
            expect(page.locator("#planning-chat-status")).to_have_text("READY")
            expect(page.locator("#planning-chat-log")).to_contain_text("Draft proposed; no run started.")
            sent = [r[2] for r in fixture.requests if r[1] == "/api/planning/message"][-1]
            assert sent["setup_context"] == {"block_id": "block-1", "revision": 3}
            assert sent["session_id"] == "canonical-server-a" and "setup_context" not in sent["constraints"]
            page.locator("#btn-live-chat-collapse").click()
            expect(first).to_contain_text("Change only the next run goal")
            assert first.locator("details").evaluate("el=>el.open")
            checks.append("Edit is nonexecuting, canonical contextual Chat, unsent text/selection and hidden Setup persist")
            # Second tab is stale after the first confirms. Actual action rejects and refreshes.
            second, errors2, console2 = open_page(context, fixture)
            # A later-dispatched GET observes the pre-commit state while the
            # earlier action is still pending; its newer transport marker must
            # not suppress the action's eventual higher server revision.
            fixture.hold_next_action = True
            first.get_by_role("button", name="Confirm Research setting 1", exact=True).click()
            page.evaluate("refreshLiveSetupState()")
            assert fixture.held_action is not None
            watermark = page.evaluate("liveSetupAppliedVersion")
            before_revision = page.evaluate("liveSetupSnapshot.revision")
            fixture.route(fixture.held_action)
            fixture.held_action = None
            expect(first).to_contain_text("Application: scheduled")
            assert page.evaluate("liveSetupSnapshot.revision") == before_revision + 1
            assert page.evaluate("liveLastSession.state.setup.revision") == before_revision + 1
            assert page.evaluate("liveSetupAppliedVersion") == watermark
            checks.append("Earlier action response with higher server revision wins over later GET; watermark stays monotonic")
            second.locator('[data-block-id="block-1"]').get_by_role("button", name="Confirm Research setting 1", exact=True).click()
            expect(second.locator("#live-experiment-setup-panel")).to_contain_text("Setup 409")
            expect(second.locator('[data-block-id="block-1"]')).to_contain_text("Application: scheduled")
            # Stale contextual Chat is preserved on 409 and canonical refresh.
            page.evaluate("setLiveChatCollapsed(false)")
            page.locator("#planning-message-input").fill("Stale text must survive")
            page.locator("#btn-planning-send").click()
            expect(page.locator("#planning-chat-status")).to_have_text("ERROR")
            expect(page.locator("#planning-message-input")).to_have_value("Stale text must survive")
            expect(page.locator("#live-chat-context-strip")).to_contain_text("Changed")
            page.get_by_role("button", name="Exit editing", exact=True).click()
            assert page.evaluate("liveSetupEditContext===null")
            expect(page.locator("#planning-message-input")).to_have_value("Stale text must survive")
            checks.append("Two-tab conflict refresh and stale409 unsent text; Exit editing clears context only")
            # Reconnect recovers graph-only changes, no replayed action or start.
            fixture.state["state"]["setup"]["projection_id"] = "reconnected-graph"
            fixture.state["state"]["setup"]["blocks"][1]["editable"] = False
            post_count = len([r for r in fixture.requests if r[0] == "POST"])
            page.evaluate("fixtureStream.onopen()")
            page.wait_for_function("liveSetupSnapshot.projection_id==='reconnected-graph'")
            assert len([r for r in fixture.requests if r[0] == "POST"]) == post_count
            # Normalization returns a visible new draft. Only a second click may confirm.
            page.evaluate("setLiveChatCollapsed(true)")
            fixture.normalize_next = True
            third = panel.locator('[data-block-id="block-3"]')
            third.get_by_role("button", name="Confirm Research setting 3", exact=True).click()
            expect(panel).to_contain_text("Review and confirm again")
            expect(third).to_contain_text("Agreement: draft")
            third.locator("summary").click()
            expect(third).to_contain_text("Owner-normalized goal")
            normalized_body = [r[2] for r in fixture.requests if r[1].endswith("actions")][-1]
            third.get_by_role("button", name="Confirm Research setting 3", exact=True).click()
            expect(third).to_contain_text("Agreement: confirmed")
            second_body = [r[2] for r in fixture.requests if r[1].endswith("actions")][-1]
            assert second_body["proposal_id"] == "normalized-proposal" and second_body["request_id"] != normalized_body["request_id"]
            checks.append("Reconnect GET only; owner normalization needs a distinct second explicit confirmation")
            # Low height/many blocks: preserve existing grid allocation, internally scroll.
            for width, height, label in [(1440, 480, "short-many-blocks"), (390, 640, "narrow-many-blocks")]:
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("setLiveChatCollapsed(true)")
                page.evaluate("Promise.all(document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})))")
                before_rects = page.evaluate("['.live-chat-panel','.live-center-panel','.live-runtime-bottom'].map(s=>{let r=document.querySelector(s).getBoundingClientRect();return [r.x+scrollX,r.y+scrollY,r.width,r.height].map(Math.round)})")
                fixture.state["state"]["setup"]["blocks"] = [block(i) for i in range(1, 31)]
                fixture.advance()
                page.evaluate("emitSetup", fixture.state["state"]["setup"])
                after_rects = page.evaluate("['.live-chat-panel','.live-center-panel','.live-runtime-bottom'].map(s=>{let r=document.querySelector(s).getBoundingClientRect();return [r.x+scrollX,r.y+scrollY,r.width,r.height].map(Math.round)})")
                assert before_rects == after_rects, (label, before_rects, after_rects)
                metrics = panel.evaluate("el=>({height:el.clientHeight,scroll:el.scrollHeight,width:el.clientWidth,scrollWidth:el.scrollWidth,overflow:getComputedStyle(el).overflowY})")
                assert metrics["scroll"] > metrics["height"] > 0 and metrics["overflow"] == "auto", metrics
                assert metrics["scrollWidth"] <= metrics["width"] + 1, metrics
                last = panel.locator('[data-block-id="block-30"]')
                edit = last.get_by_role("button", name="Edit Research setting 30", exact=True)
                edit.focus()
                page.keyboard.press("Tab")
                expect(last.get_by_role("button", name="Confirm Research setting 30", exact=True)).to_be_focused()
                page.keyboard.press("Tab")
                expect(last.get_by_role("button", name="Discard Research setting 30", exact=True)).to_be_focused()
                assert panel.evaluate("el=>el.scrollTop>0")
                screenshots.append(screenshot(page, out, label))
                page.keyboard.press("Enter")
                expect(last.get_by_role("button", name="Discard Research setting 30", exact=True)).to_be_disabled()
                edit.click()
                expect(page.locator("#planning-message-input")).to_be_focused()
                checks.append(f"{width}x{height}: 30 blocks, internal scroll, stable surrounding bounds, last Edit/Confirm/Discard keyboard reachable")
            # New canonical session clears old edit context despite smaller revision.
            replacement = session(1)
            replacement["planning_session_id"] = "canonical-server-b"
            replacement["state"]["setup"].update(session_id="canonical-server-b", revision=1)
            page.evaluate("state=>applyPlanningSession(state)", replacement)
            assert page.evaluate("liveSetupEditContext===null && planningSessionId==='canonical-server-b' && liveSetupSnapshot.revision===1")
            expect(page.locator("#planning-message-input")).to_have_value("Stale text must survive")
            checks.append("Canonical session replacement clears context without losing unsent text")
            assert not errors + errors2, errors + errors2
            assert not fixture.unexpected, fixture.unexpected
            unexpected_console = [entry for entry in console + console2 if "409" not in entry[1]]
            assert not unexpected_console, unexpected_console
            report = {"passed": True, "url": URL, "browser": "installed Playwright Chromium; approved fallback after Browser discovery empty",
                      "hooks": HOOKS, "checks": checks, "screenshots": screenshots,
                      "console": console + console2, "unexpected_requests": fixture.unexpected,
                      "request_count": len(fixture.requests), "note": "Static fixtures only; surrounding behavior not executed; no operating GUI."}
            (out / "results.json").write_text(json.dumps(report, indent=2))
            return report
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    destination = args.out_dir or Path(tempfile.mkdtemp(prefix="experimental-setup-audit-"))
    print(json.dumps(audit(destination), indent=2))
