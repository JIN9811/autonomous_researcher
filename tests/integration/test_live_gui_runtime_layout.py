"""Integration checks for the Live GUI Runtime IDE shell."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, controller, _package_runtime_event


def test_live_gui_runtime_shell_contains_operational_panels() -> None:
    client = TestClient(app)
    response = client.get("/live")

    assert response.status_code == 200
    html = response.text
    required_ids = [
        "live-agent-binder-list",
        "live-binder-context-menu",
        "live-report-panel",
        "live-backend-panel",
        "live-graph-panel",
        "live-artifact-panel",
        "live-timeline-detail-panel",
        "live-chat-target",
        "live-chat-mode",
        "live-chat-context-strip",
        "live-focus-strip",
        "live-stream-chip",
        "live-sync-chip",
        "live-fault-chip",
        "live-approval-panel",
        "live-quick-actions",
        "live-hover-tooltip",
        "live-shortcut-overlay",
        "btn-live-shortcuts-close",
        "live-timeline-strip",
        "live-device-strip",
        "btn-live-safe-stop",
        "btn-live-bottom-collapse",
        "planning-chat-log",
        "planning-message-input",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html
    assert "planning-live-body" in html
    assert "/static/styles.css?v=20260527-live-focus" in html
    assert "/static/planning.js?v=20260527-live-focus" in html
    assert "Runtime Chat" in html
    assert "Safe Stop" in html
    assert "Pause Run" in html
    assert "Resume Run" in html
    assert "Handoff" in html
    assert "Graph" in html
    script_text = client.get("/static/planning.js").text
    for label in ["Overview / Summary", "Key Decisions", "Tool Calls Summary", "Validation / Quality Check", "Next Action"]:
        assert label in script_text
    for role_label in [
        "Orchestration Plan / Handoff Control",
        "Design Geometry / Manufacturability",
        "Print Preparation / Prusa Bridge",
        "Bayesian Optimization / Candidate Selection",
        "Safety Gate / Continue-Stop Decision",
    ]:
        assert role_label in script_text


def test_gui_favicon_is_available_to_all_runtime_pages() -> None:
    client = TestClient(app)
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in response.content

    for route in ["/", "/live", "/ide", "/evolution-lab", "/module-management"]:
        page = client.get(route)
        assert page.status_code == 200
        assert 'rel="icon" type="image/svg+xml" href="/static/favicon.svg"' in page.text


def test_live_gui_static_script_exposes_runtime_ide_adapters() -> None:
    client = TestClient(app)
    response = client.get("/static/planning.js")

    assert response.status_code == 200
    script = response.text
    for symbol in [
        "LIVE_AGENTS",
        "renderAgentBinder",
        "renderReportPanel",
        "renderBackendPanel",
        "renderBackendTraceSections",
        "renderGraphMiniPanel",
        "renderSelectedGraphNodeView",
        "renderArtifactPanel",
        "renderTimelinePanels",
        "eventTimelineKind",
        "eventStableKey",
        "renderSelectedEventCard",
        "runSelectedEventAction",
        "renderApprovalPanel",
        "pendingAgentQuestions",
        "handleQuestionAction",
        "answerAgentQuestion",
        "isRuntimeFaultEvent",
        "liveFaultEvents",
        "renderFaultCard",
        "updateLiveFaultChip",
        "handleFaultAction",
        "recordLiveAttentionAction",
        "clearLiveGraphSelection",
        "clearLiveTimelineSelection",
        "renderDeviceStrip",
        "refreshLiveRunDetails",
        "resolveLiveApproval",
        "refreshLiveGraphPayload",
        "runLiveQuickAction",
        "setLiveQuickActionBusy",
        "setLiveBackendPlanningBusy",
        "liveBackendPlanningBusy",
        "fetchJsonOrThrow",
        "relativeTimeLabel",
        "compactRunId",
        "liveAgentShort",
        "setCompactTextWithTitle",
        "liveTokenUsageFromObject",
        "collectLiveTokenUsage",
        "updateLiveTokenChip",
        "setRuntimeChip",
        "updateLiveConnectionChips",
        "liveChatTargetForAgent",
        "markLiveSyncRefreshStart",
        "markLiveSyncComplete",
        "markLiveSyncError",
        "liveSyncIsStale",
        "markLiveStreamState",
        "LIVE_AUTO_REFRESH_MS",
        "LIVE_SYNC_STALE_MS",
        "LIVE_SYNC_ERROR_MS",
        "runLiveReportAction",
        "blockLiveExecutionForPendingApproval",
        "recordLiveOperatorEvent",
        "recordLiveIntentEvent",
        "liveNotificationCountsByAgent",
        "markLiveAgentRead",
        "syncOperatorReportStateFromEvents",
        "normalizePinnedFindingFromEvent",
        "operator_report_state_run_id",
        "liveSelectedTraceContext",
        "liveChatContextSummary",
        "liveModeShort",
        "liveRunningFlag",
        "renderLiveChatContextStrip",
        "renderLiveFocusStrip",
        "liveFocusChip",
        "focusDeviceEventFromCard",
        "selectLiveReportSection",
        "selectedReportSectionText",
        "selectedReportSectionPayload",
        "selectedReportSectionExportText",
        "selected_report_section",
        "live_selected_trace_id",
        "renderAcademicReportSections",
        "renderReportSection",
        "renderAgentSpecificReportSection",
        "agentSpecificReportProfile",
        "latestReportBoResult",
        "latestReportArtifacts",
        "selectedReportModel",
        "handleContextAction",
        "openBinderContextMenu",
        "pinAgentReportFromBinder",
        "evolutionTargetForAgent",
        "evolutionLabUrl",
        "openEvolutionLab",
        "liveSessionStorage",
        "persistPlanningSessionId",
        "LIVE_UI_STATE_KEY",
        "knownLiveAgent",
        "validLiveChatTarget",
        "resolveLiveChatTarget",
        "LIVE_CHAT_TARGET_SPECIALS",
        "liveUiStatePayload",
        "persistLiveUiState",
        "restoreLiveUiState",
        "LIVE_TOOLTIP_SELECTOR",
        "liveTooltipTarget",
        "liveTooltipText",
        "showLiveHoverTooltip",
        "hideLiveHoverTooltip",
        "isLiveEditableTarget",
        "toggleLiveShortcutOverlay",
        "setLiveBottomCollapsed",
        "liveShortcutKey",
        "runLiveKeyboardShortcut",
        "__liveGuiDebugSetState",
        "__liveGuiDebugSnapshot",
        "__liveGuiDebugRestoreOperatorReportState",
    ]:
        assert symbol in script
    assert "window.localStorage || window.sessionStorage" in script
    assert "autonomousLiveGuiUiState" in script
    assert 'new EventSource("/api/events/stream")' in script
    assert 'source.onopen = () => {' in script
    assert 'markLiveStreamState("live", eventTime);' in script
    assert 'markLiveSyncComplete();' in script
    assert 'markLiveSyncError(err);' in script
    assert 'refreshPlanningState({ background: true })' in script
    assert 'liveSyncIsStale()' in script
    assert 'liveRefreshInFlight' in script
    assert "restoreLiveUiState();" in script
    assert "persistLiveUiState();" in script
    assert 'setCompactTextWithTitle(planningStageLabel, `S:${stageLabel}`' in script
    assert 'setCompactTextWithTitle(liveActiveAgentChip, `A:${liveAgentShort(activeAgent)}`' in script
    assert 'setLiveBackendPlanningBusy(Boolean(liveLastSession.is_planning_busy));' in script
    assert 'planningThinkingCount > 0 || liveBackendPlanningBusy' in script
    assert 'backend_planning_busy: liveBackendPlanningBusy' in script
    assert "chat_context: liveChatContextSummary()" in script
    assert "`R:${liveModeShort(ctx.mode)}:${ctx.is_running ? \"ON\" : \"IDLE\"}`" in script
    assert "`Ref:${compactText(anchor || \"-\", 14)}`" in script
    assert "const snapshot = liveLastSnapshot || {};" in script
    assert "const state = session.state || snapshot.state || {};" in script
    assert "const state = liveLastSession.state || snapshot.state || {};" in script
    assert "is_running: liveRunningFlag(session, snapshot, state)" in script
    assert "active_goal: state.active_goal ||" in script
    assert "running=${ctx.is_running ? \"true\" : \"false\"}" in script
    assert "goal=${ctx.active_goal ||" in script
    assert "live_chat_target_mode" in script
    assert "live_chat_target_resolved" in script
    assert "live_run_id" in script
    assert "live_mode" in script
    assert "live_stage" in script
    assert "live_is_running" in script
    assert "live_is_running: liveRunningFlag(session, snapshot, state)" in script
    assert "Boolean(session.is_running || snapshot.is_running)" not in script
    assert "const running = liveRunningFlag(liveLastSession, snapshot, state);" in script
    assert "live_active_goal" in script
    assert "setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));" in script
    assert "event.ctrlKey || event.metaKey" in script
    assert "operator.binder.report_pinned" in script
    assert "binder.ctrl_click" in script
    assert "approval.blocked_execution" in script
    assert "requires_operator_approval" in script
    assert "live_graph.run_test" in script
    assert "liveNotificationCountsByAgent(session)" in script
    assert "if (Array.isArray(liveRunEvents)) eventSources.push(...liveRunEvents);" in script
    assert "if (Array.isArray(liveRecentEvents)) eventSources.push(...liveRecentEvents);" in script
    assert "markLiveAgentRead(liveSelectedAgent, liveLastSession);" in script
    assert '<option value="current_agent">Current Agent</option>' in script
    assert '<option value="selected_agent">Selected Agent</option>' in script
    assert '<optgroup label="Specific Agent">' in script
    assert 'updateLiveTokenChip(session);' in script
    assert 'token_usage: collectLiveTokenUsage(liveLastSession)' in script
    assert '".runtime-chip[title]"' in script
    assert '".live-runtime-metrics span[title]"' in script
    assert 'document.addEventListener("mouseover", (event) => showLiveHoverTooltip(event.target));' in script
    assert 'document.addEventListener("keydown", (event) => {' in script
    assert 'runLiveKeyboardShortcut(event);' in script
    assert 'if (editable && !safetyShortcut) return false;' in script
    assert "persistPlanningSessionId(liveLastSession.planning_session_id)" in script
    assert "/api/events/recent" in script
    app_source = Path("app/main.py").read_text(encoding="utf-8")
    assert "stream.connected" in app_source
    assert "stream.heartbeat" in app_source
    assert "asyncio.wait_for(queue.get(), timeout=15.0)" in app_source
    assert "/api/runs/" in script
    assert "/api/run/safe-stop" in script
    assert "liveQuickActionBusy && action !== \"safe_stop\"" in script
    assert "setLiveQuickActionBusy(liveQuickActionBusy)" in script
    assert "armLiveSafeStop" in script
    assert "resetLiveSafeStopArm" in script
    assert "double_click_within_6s" in script
    assert "SAFE STOP ERROR" in script
    assert "/api/runtime/operator-event" in script
    assert "operator.report." in script
    assert "operator.context" in script
    assert "operator.attention" in script
    assert "attention_event_key" in script
    assert "recordLiveAttentionAction(\"question\", \"answer\", event)" in script
    assert "recordLiveAttentionAction(\"fault\", \"backend\", event)" in script
    assert "operator.timeline" in script
    assert "report_rewrite_requested" in script
    assert "runtime_command_requested" in script
    assert "node_rerun_requested" in script
    assert "renderGraphGateControls" in script
    assert "runLiveGraphGateAction" in script
    assert "graph_change_requested" in script
    assert "graph_run_requested" in script
    assert "graph_run_test" in script
    assert "live_graph.run_test" in script
    assert "live_gui_graph_gate_save_version" in script
    assert "/api/graphs/${encodeURIComponent(graphId)}/validate" in script
    assert "/api/graphs/${encodeURIComponent(graphId)}/compile" in script
    assert "/api/graphs/${encodeURIComponent(graphId)}/save-version" in script
    assert "/api/graphs/${encodeURIComponent(graphId)}/run" in script
    assert "data-live-ide-link" in script
    assert "source=live_graph" in script
    assert "encodeURIComponent(ideNodeRef)" in script
    assert "recordLiveContextAction" in script
    assert "pinned_finding" in script
    assert "reviewed_at" in script
    assert "pinned_findings" in script
    assert "reviewed_agents" in script
    assert "iconPath" in script
    assert "/static/live_gui_icons/orchestrator.svg" in script
    assert "liveAgentIconHtml" in script
    assert 'join("\\n")' in script
    assert 'class="live-report-list">\\n' in script
    assert "live-report-section-body" in script
    assert "data-report-section-title" in script
    assert "live_selected_report_section" in script
    assert "live_selected_report_section_text" in script
    assert 'export_scope: "selected_report_section"' in script
    assert 'ask_scope: "selected_report_section"' in script
    assert "selected_report_section_key" in script
    assert 'renderReportSection("Artifacts"' in script
    styles = Path("web/static/styles.css").read_text(encoding="utf-8")
    assert "live-ide-sheen" in styles
    assert "live-ide-chip-sweep" in styles
    assert "live-report-section.selected" in styles
    assert "live-pinned-compare" in styles
    assert "live-pinned-compare-grid" in styles
    assert "live-pinned-finding-action" in styles
    assert "Runtime IDE visual effects" in styles or "IDE-effect unification" in styles
    icon_response = client.get("/static/live_gui_icons/orchestrator.svg")
    assert icon_response.status_code == 200
    assert "<svg" in icon_response.text
    live_html = client.get("/live").text
    assert "planning-live-body" in live_html
    assert "live-hover-tooltip" in live_html
    assert 'role="tooltip"' in live_html
    assert "live-shortcut-overlay" in live_html
    assert "live-chat-context-strip" in live_html
    assert "live-focus-strip" in live_html
    assert "selected runtime focus" in live_html
    assert "runtime chat context" in live_html
    assert "live-stream-chip" in live_html
    assert "live-sync-chip" in live_html
    assert "live-fault-chip" in live_html
    assert "SSE ..." in live_html
    assert "Sync -" in live_html
    assert "btn-live-bottom-collapse" in live_html
    assert "aria-keyshortcuts" in live_html
    assert 'aria-keyshortcuts="Alt+Shift+X"' in live_html
    assert 'aria-keyshortcuts="Control+Enter"' in live_html
    assert 'live-timeline-filter-label' in live_html
    assert 'data-timeline-filter="warning" title="Warning and approval events"' in live_html
    required_quick_actions = [
        "approve_next_step",
        "revise",
        "reject_next_step",
        "pause_run",
        "resume_run",
        "safe_stop",
        "dry_run",
    ]
    for action in required_quick_actions:
        assert f'data-quick-action="{action}"' in live_html
    removed_debug_quick_actions = [
        "explain_current_node",
        "rewrite_report_section",
        "open_backend",
        "run_node_test",
        "open_graph",
        "open_evolution",
    ]
    for action in removed_debug_quick_actions:
        assert f'data-quick-action="{action}"' not in live_html
    assert 'data-decision="cancelled">Revise' in script
    assert 'resolveLiveApproval(state.run_id, pending.approval_id, "cancelled")' in script
    assert 'data-report-action="evolve"' in script
    live_css = client.get("/static/styles.css").text
    assert "live-bottom-collapsed" in live_css
    assert "Live bottom dock containment" in live_css
    assert "Runtime Focus Strip" in live_css
    assert "Device trace focus" in live_css
    audit_script_for_layout = Path("tests/ui/live_runtime_ide_browser_audit.py").read_text(encoding="utf-8")
    assert "bottomDockContainment" in audit_script_for_layout
    assert "blankGraphSelection" in audit_script_for_layout
    assert "focusContextText" in audit_script_for_layout
    assert "deviceFocus" in audit_script_for_layout
    assert "pinnedCompareText" in audit_script_for_layout
    assert "pinnedFocusProbe" in audit_script_for_layout
    assert "blankTimelineSelection" in audit_script_for_layout
    assert "graphSelectionCleared" in script
    assert "live-fault-card" in live_css
    assert "live-ide-edge-dash" in live_css


    audit_script = Path("tests/ui/live_runtime_ide_browser_audit.py").read_text(encoding="utf-8")
    for symbol in ["LIVE_REFERENCE_IMAGE", "image_visual_metrics", "rgb_distance", "titleContrastOnPanel", "bright_ratio"]:
        assert symbol in audit_script


def test_evolution_lab_supports_live_gui_query_prefill() -> None:
    client = TestClient(app)
    response = client.get("/evolution-lab?target_type=prompt&target_id=design&run_id=run-demo&source=live_gui")
    assert response.status_code == 200
    assert "ATR Self-Evolution Lab" in response.text
    assert "evolution-pipeline-output" in response.text
    assert "evolution-leaderboard-output" in response.text
    assert "evolution-history-output" in response.text
    assert "evolution-lineage-output" in response.text
    assert "Candidate Leaderboard" in response.text

    script = client.get("/static/evolution_lab.js").text
    for symbol in [
        "queryParams",
        "applyQueryPrefill",
        "renderTaskHistory",
        "renderLineage",
        "renderPipeline",
        "renderLeaderboard",
        "refreshVariantsForTarget",
        "gateChecklistMarkup",
        "loadTaskVariants",
        "loadVariant",
        "target_type",
        "target_id",
        "run_id",
        "No hardware is executed",
    ]:
        assert symbol in script

    variants = client.get("/api/evolution/variants?target_type=prompt&target_id=design").json()
    assert variants["ok"] is True
    assert variants["target_type"] == "prompt"
    assert variants["target_id"] == "design"
    assert isinstance(variants["variants"], list)


def test_live_gui_package_compatibility_endpoints_expose_existing_runtime_contract() -> None:
    client = TestClient(app)

    route_paths = {getattr(route, "path", "") for route in app.routes}
    for path in [
        "/api/runtime/state",
        "/api/runtime/events",
        "/api/runtime/start",
        "/api/runtime/pause",
        "/api/runtime/resume",
        "/api/runtime/stop",
        "/api/runtime/safe-stop",
        "/api/devices/state",
        "/api/agents",
        "/api/agents/{agent_id}/report",
        "/api/agents/{agent_id}/backend-trace",
        "/api/agents/{agent_id}/message",
        "/api/artifacts",
        "/api/artifacts/{artifact_id:path}",
        "/api/graphs/{graph_id}/save-version",
        "/api/approvals/{approval_id}/approve",
        "/api/approvals/{approval_id}/revise",
        "/api/approvals/{approval_id}/reject",
    ]:
        assert path in route_paths

    runtime_state = client.get("/api/runtime/state").json()
    assert runtime_state["ok"] is True
    assert runtime_state["compatibility"] == "atr_live_gui_package"
    assert "state" in runtime_state
    assert "system_resources" in runtime_state
    run_id = runtime_state["state"]["run_id"]

    devices = client.get("/api/devices/state").json()
    assert devices["ok"] is True
    assert devices["run_id"] == run_id
    assert any(item["device_id"] == "gpu" for item in devices["devices"])

    agents = client.get("/api/agents").json()
    assert agents["ok"] is True
    assert len(agents["agents"]) >= 11
    assert any(item["agent_id"] == "design" for item in agents["agents"])
    equipment_agent = next(item for item in agents["agents"] if item["agent_id"] == "equipment")
    assert equipment_agent["stage"] == "equipment"
    assert equipment_agent["module_id"] == "equipment"
    assert "Lab Equipment" in equipment_agent["label"]

    report = client.get("/api/agents/design/report").json()
    assert report["ok"] is True
    assert report["report"]["agent_id"] == "design"
    assert "sections" in report["report"]
    assert report["report"]["role_specific"]["title"] == "Design Geometry / Manufacturability"
    assert report["report"]["sections"]["role_specific"]["title"] == "Design Geometry / Manufacturability"
    assert any(row["label"] == "Geometry" for row in report["report"]["role_specific"]["focus_rows"])
    assert isinstance(report["report"]["process_steps"], list)
    assert isinstance(report["report"]["tool_calls"], list)
    assert isinstance(report["report"]["artifacts"], list)
    assert report["report"]["handoff"]["agent_stage"] == "design"

    specimen_report = client.get("/api/agents/specimen/report").json()["report"]
    assert specimen_report["role_specific"]["title"] == "Print Preparation / Prusa Bridge"
    bo_report = client.get("/api/agents/bo/report").json()["report"]
    assert bo_report["role_specific"]["title"] == "Bayesian Optimization / Candidate Selection"
    guardian_report = client.get("/api/agents/guardian/report").json()["report"]
    assert guardian_report["role_specific"]["title"] == "Safety Gate / Continue-Stop Decision"

    trace = client.get("/api/agents/design/backend-trace").json()
    assert trace["ok"] is True
    assert trace["agent"]["agent_id"] == "design"
    assert isinstance(trace["events"], list)

    artifacts = client.get("/api/artifacts").json()
    assert artifacts["ok"] is True
    assert artifacts["run_id"] == run_id
    assert isinstance(artifacts["artifacts"], list)

    graph_payload = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    saved_graph = client.post(
        "/api/graphs/atr_closed_loop/save-version",
        json={"graph": graph_payload, "activate": False, "reason": "compatibility_test", "author": "pytest"},
    ).json()
    assert saved_graph["ok"] is True
    assert saved_graph["compatibility"] == "atr_live_gui_package"
    assert saved_graph["save_version_endpoint"] is True
    assert saved_graph["activated"] is False
    assert saved_graph["version"]["version_id"]

    approval = client.post(
        f"/api/runs/{run_id}/approvals",
        json={"title": "Compat approval", "reason": "package endpoint", "stage": "guardian", "safety_class": "compat"},
    ).json()
    approval_id = approval["approval_id"]
    package_request_event = _package_runtime_event(approval["event"])
    assert package_request_event["type"] == "approval_requested"
    assert package_request_event["event_type_internal"] == "approval.requested"
    assert package_request_event["timestamp"]
    assert package_request_event["stage"] == "guardian"
    assert package_request_event["graph_id"] == "atr_closed_loop"

    resolved = client.post(f"/api/approvals/{approval_id}/approve", json={"note": "compat route"}).json()
    assert resolved["ok"] is True
    assert resolved["approval_id"] == approval_id
    assert any(item["approval_id"] == approval_id for item in resolved["resolved"])
    package_resolved_event = _package_runtime_event(resolved["event"])
    assert package_resolved_event["type"] == "approval_granted"
    assert package_resolved_event["event_type_internal"] == "approval.resolved"
    assert package_resolved_event["severity"] == "info"

    rejected_approval = client.post(
        f"/api/runs/{run_id}/approvals",
        json={"title": "Compat reject approval", "reason": "package reject endpoint", "stage": "guardian", "safety_class": "compat"},
    ).json()
    rejected = client.post(f"/api/approvals/{rejected_approval['approval_id']}/reject", json={"note": "compat reject route"}).json()
    package_rejected_event = _package_runtime_event(rejected["event"])
    assert package_rejected_event["type"] == "approval_rejected"
    assert package_rejected_event["event_type_internal"] == "approval.resolved"
    assert package_rejected_event["severity"] == "warning"



def test_live_graph_run_records_graph_version_hash_evidence() -> None:
    client = TestClient(app)
    pre_state = client.get("/api/state").json()
    if pre_state.get("is_running"):
        pre_run_id = pre_state.get("state", {}).get("run_id")
        if pre_run_id:
            client.post(f"/api/runs/{pre_run_id}/stop")

    result = client.post(
        "/api/graphs/atr_closed_loop/run",
        json={"mode": "test", "goal": "pytest graph evidence run", "backend": None},
    ).json()
    run_id = str((result.get("run") or {}).get("run_id") or "")
    try:
        assert result["ok"] is True
        assert run_id
        assert result["graph_id"] == "atr_closed_loop"
        assert result["graph_hash"]
        assert result["graph_version"]
        assert (result["run"] or {}).get("graph_hash") == result["graph_hash"]
        assert (result["run"] or {}).get("graph_version") == result["graph_version"]

        snapshot = client.get("/api/state").json()
        runtime_graph = snapshot["state"]["run_metadata"]["runtime_graph"]
        assert runtime_graph["graph_id"] == "atr_closed_loop"
        assert runtime_graph["graph_hash"] == result["graph_hash"]
        assert runtime_graph["graph_version"] == result["graph_version"]

        events = client.get(f"/api/runs/{run_id}/events").json()["events"]
        created = next(event for event in events if event.get("event_type") == "run.created")
        compiled = next(event for event in events if event.get("event_type") == "graph.compiled")
        assert created["payload"]["graph_hash"] == result["graph_hash"]
        assert created["payload"]["graph_version"] == result["graph_version"]
        assert compiled["payload"]["graph_hash"] == result["graph_hash"]
        assert compiled["payload"]["graph_version"] == result["graph_version"]

        package_compiled = _package_runtime_event(compiled)
        assert package_compiled["type"] == "graph_compiled"
        assert package_compiled["graph_id"] == "atr_closed_loop"
        assert package_compiled["graph_version"] == result["graph_version"]
    finally:
        if run_id:
            client.post(f"/api/runs/{run_id}/stop")


def test_live_gui_operator_report_action_is_recorded_as_runtime_trace_event() -> None:
    client = TestClient(app)
    run_id = client.get("/api/state").json()["state"]["run_id"]

    response = client.post(
        f"/api/runs/{run_id}/operator-events",
        json={
            "event_type": "operator.report.exported",
            "message": "Design Agent report exported from Live GUI.",
            "action": "exported",
            "agent_id": "design",
            "node_id": "design",
            "trace_id": "trace-report-action-test",
            "event_key": "evt-report-action-test",
            "payload": {"selected_view": "report", "export_format": "txt"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["event"]["event_type"] == "operator.report.exported"
    assert payload["event"]["payload"]["operator_source"] == "live_gui"

    trace = client.get(f"/api/agents/design/backend-trace?run_id={run_id}").json()
    assert trace["ok"] is True
    assert any(event["event_type"] == "operator.report.exported" for event in trace["events"])


def test_live_gui_operator_report_pin_review_payloads_are_auditable() -> None:
    client = TestClient(app)
    run_id = client.get("/api/state").json()["state"]["run_id"]

    pin_response = client.post(
        f"/api/runs/{run_id}/operator-events",
        json={
            "event_type": "operator.report.pinned",
            "message": "Design Agent report finding pinned.",
            "action": "pinned",
            "agent_id": "design",
            "node_id": "design",
            "payload": {
                "pinned_finding": {
                    "agent_id": "design",
                    "label": "Design Agent",
                    "pinned_at": "2026-05-26T10:00:00Z",
                    "text": "Printable TPMS candidate selected.",
                    "run_id": run_id,
                },
                "pinned_at": "2026-05-26T10:00:00Z",
            },
        },
    )
    review_response = client.post(
        f"/api/runs/{run_id}/operator-events",
        json={
            "event_type": "operator.report.reviewed",
            "message": "Design Agent report marked reviewed.",
            "action": "reviewed",
            "agent_id": "design",
            "node_id": "design",
            "payload": {"reviewed_at": "2026-05-26T10:01:00Z"},
        },
    )

    assert pin_response.status_code == 200
    assert review_response.status_code == 200
    trace = client.get(f"/api/agents/design/backend-trace?run_id={run_id}").json()
    events = trace["events"]
    pinned = [event for event in events if event.get("event_type") == "operator.report.pinned"]
    reviewed = [event for event in events if event.get("event_type") == "operator.report.reviewed"]
    assert pinned
    assert reviewed
    assert pinned[-1]["payload"]["pinned_finding"]["text"] == "Printable TPMS candidate selected."
    assert reviewed[-1]["payload"]["reviewed_at"] == "2026-05-26T10:01:00Z"


def test_live_gui_operator_reply_is_recorded_as_runtime_trace_event() -> None:
    client = TestClient(app)
    cursor = len(controller.recent_events())

    response = client.post(
        "/api/planning/message",
        json={
            "message": "실험 수행",
            "session_id": "trace-contract-test",
            "constraints": {
                "live_chat_target": "specimen",
                "live_selected_agent": "specimen",
                "live_chat_mode": "command",
                "live_selected_trace_id": "trace-question-contract",
                "live_selected_event_key": "evt-question-contract",
            },
        },
    )

    assert response.status_code == 200
    new_events = controller.recent_events()[cursor:]
    user_reply_events = [event for event in new_events if event.get("event_type") == "user_reply"]
    assert user_reply_events
    event = user_reply_events[-1]
    assert event["payload"]["source"] == "live_gui"
    assert event["payload"]["agent_id"] == "specimen"
    assert event["payload"]["trace_id"] == "trace-question-contract"
    assert event["payload"]["event_key"] == "evt-question-contract"
    assert event["payload"]["latest"]["content"] == "실험 수행"

    trace = client.get("/api/agents/specimen/backend-trace").json()
    assert trace["ok"] is True
    assert any(item.get("event_type") == "user_reply" for item in trace["events"])
    assert event["payload"]["target_agent_id"] == "specimen"
    assert event["payload"]["selected_agent_id"] == "specimen"
    assert event["payload"]["selected_trace_id"] == "trace-question-contract"
    assert event["payload"]["selected_event_key"] == "evt-question-contract"


def test_live_gui_operator_reply_separates_target_agent_from_selected_context() -> None:
    client = TestClient(app)
    cursor = len(controller.recent_events())

    response = client.post(
        "/api/planning/message",
        json={
            "message": "테스트 모드",
            "session_id": "trace-target-context-test",
            "constraints": {
                "live_chat_target": "specimen",
                "live_chat_target_resolved": "specimen",
                "live_chat_target_mode": "selected_agent",
                "live_selected_agent": "orchestrator",
                "live_selected_graph_node_id": "specimen",
                "live_selected_node_id": "specimen",
                "live_selected_trace_id": "trace-specimen-question",
                "live_selected_event_key": "evt-specimen-question",
                "live_selected_event_id": "evt-specimen-question",
                "live_selected_event_type": "agent_question",
                "live_selected_report_section": "Specimen Bridge Prompt",
                "live_selected_report_section_text": "Specimen bridge mode required. Options: virtual bridge, installed printer, or actual print.",
                "live_run_id": "run-context-contract",
                "live_mode": "live",
                "live_stage": "specimen",
                "live_is_running": True,
                "live_active_goal": "Verify run-state preservation",
                "live_chat_mode": "command",
            },
        },
    )

    assert response.status_code == 200
    new_events = controller.recent_events()[cursor:]
    user_reply_events = [event for event in new_events if event.get("event_type") == "user_reply"]
    assert user_reply_events
    event = user_reply_events[-1]
    payload = event["payload"]
    assert payload["agent_id"] == "specimen"
    assert payload["target_agent_id"] == "specimen"
    assert payload["selected_agent_id"] == "orchestrator"
    assert payload["node_id"] == "specimen"
    assert payload["selected_node_id"] == "specimen"
    assert payload["selected_graph_node_id"] == "specimen"
    assert payload["trace_id"] == "trace-specimen-question"
    assert payload["selected_trace_id"] == "trace-specimen-question"
    assert payload["event_key"] == "evt-specimen-question"
    assert payload["selected_event_key"] == "evt-specimen-question"
    assert payload["selected_event_type"] == "agent_question"
    assert payload["selected_report_section"] == "Specimen Bridge Prompt"
    assert payload["selected_report_section_text"] == "Specimen bridge mode required. Options: virtual bridge, installed printer, or actual print."
    assert payload["selected_report_section_text_excerpt"] == "Specimen bridge mode required. Options: virtual bridge, installed printer, or actual print."
    assert payload["run_context"] == {
        "run_id": "run-context-contract",
        "mode": "live",
        "stage": "specimen",
        "is_running": True,
        "active_goal": "Verify run-state preservation",
    }
    assert payload["live_run_id"] == "run-context-contract"
    assert payload["live_mode"] == "live"
    assert payload["live_stage"] == "specimen"
    assert payload["live_is_running"] is True
    assert payload["live_active_goal"] == "Verify run-state preservation"
    assert payload["chat_target_mode"] == "selected_agent"

    trace = client.get("/api/agents/specimen/backend-trace").json()
    assert trace["ok"] is True
    assert any(
        item.get("event_type") == "user_reply"
        and (item.get("payload") or {}).get("trace_id") == "trace-specimen-question"
        for item in trace["events"]
    )
