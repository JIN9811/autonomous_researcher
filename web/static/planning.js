/*
File purpose:
- Frontend behavior for the live-mode GUI conversation workspace.

Key classes/functions:
- refreshPlanningState
- sendPlanningMessage
- renderPlanningMessages

Inputs/outputs:
- Input: query string goal, /api/planning/session, and /api/planning/message
- Output: Live GUI state labels, orchestrator transcript, Design Agent handoff artifacts

Dependencies:
- Fetch API

Modification guide:
- Safe places to edit: chat behavior and rendering
- Risky places to edit: API paths and IDs consumed by planning.html
- Related files: web/templates/planning.html, app/main.py
*/

const planningGoalInput = document.getElementById("planning-goal-input");
const planningMaterialInput = document.getElementById("planning-material-input");
const planningSizeInput = document.getElementById("planning-size-input");
const planningTimeInput = document.getElementById("planning-time-input");
const planningStageLabel = document.getElementById("planning-stage-label");
const planningRunDetail = document.getElementById("planning-run-detail");
const planningStateDot = document.getElementById("planning-state-dot");
const planningSpecSummary = document.getElementById("planning-spec-summary");
const planningChatLog = document.getElementById("planning-chat-log");
const planningChatStatus = document.getElementById("planning-chat-status");
const planningMessageInput = document.getElementById("planning-message-input");
const btnPlanningRefresh = document.getElementById("btn-planning-refresh");
const btnPlanningGenerate = document.getElementById("btn-planning-generate");
const btnPlanningSend = document.getElementById("btn-planning-send");

const liveAgentBinderList = document.getElementById("live-agent-binder-list");
const liveCenterTitle = document.getElementById("live-center-title");
const liveFocusStrip = document.getElementById("live-focus-strip");
const liveReportPanel = document.getElementById("live-report-panel");
const liveBackendPanel = document.getElementById("live-backend-panel");
const liveGraphPanel = document.getElementById("live-graph-panel");
const liveArtifactPanel = document.getElementById("live-artifact-panel");
const liveTimelineDetailPanel = document.getElementById("live-timeline-detail-panel");
const liveViewTabs = Array.from(document.querySelectorAll(".live-view-tab"));
const liveQuickActions = document.getElementById("live-quick-actions");
const liveTimelineFilters = Array.from(document.querySelectorAll(".live-timeline-filter"));
const liveChatTarget = document.getElementById("live-chat-target");
const liveChatMode = document.getElementById("live-chat-mode");
const liveChatContextStrip = document.getElementById("live-chat-context-strip");
const liveApprovalPanel = document.getElementById("live-approval-panel");
const liveTimelineStrip = document.getElementById("live-timeline-strip");
const liveDeviceStrip = document.getElementById("live-device-strip");
const liveActiveAgentChip = document.getElementById("live-active-agent-chip");
const liveStreamChip = document.getElementById("live-stream-chip");
const liveSyncChip = document.getElementById("live-sync-chip");
const liveFaultChip = document.getElementById("live-fault-chip");
const liveResourceChip = document.getElementById("live-resource-chip");
const liveTokenChip = document.getElementById("live-token-chip");
const liveRuntimeClock = document.getElementById("live-runtime-clock");
const liveEventCount = document.getElementById("live-event-count");
const btnLiveBottomCollapse = document.getElementById("btn-live-bottom-collapse");
const btnLiveSafeStop = document.getElementById("btn-live-safe-stop");
const liveQuickActionButtons = Array.from(document.querySelectorAll(".live-quick-action"));
const liveHoverTooltip = document.getElementById("live-hover-tooltip");
const liveShortcutOverlay = document.getElementById("live-shortcut-overlay");
const btnLiveShortcutsClose = document.getElementById("btn-live-shortcuts-close");
const LIVE_UI_STATE_KEY = "autonomousLiveGuiUiState";
const LIVE_VIEW_IDS = new Set(["report", "backend", "graph", "artifacts", "timeline"]);
const LIVE_TIMELINE_FILTER_IDS = new Set(["all", "info", "warning", "error", "tool", "artifact", "handoff"]);

const LIVE_AGENTS = [
  { id: "objective", label: "Objective", short: "OBJ", stage: "idle", icon: "◎", iconPath: "/static/live_gui_icons/objective.svg" },
  { id: "orchestrator", label: "Orchestrator", short: "ORC", stage: "orchestrator", icon: "◇", iconPath: "/static/live_gui_icons/orchestrator.svg" },
  { id: "design", label: "Design Agent", short: "DSN", stage: "design", icon: "D", iconPath: "/static/live_gui_icons/design_agent.svg" },
  { id: "specimen", label: "Specimen Agent", short: "SPC", stage: "specimen", icon: "S", iconPath: "/static/live_gui_icons/specimen_agent.svg" },
  { id: "vision", label: "Vision Agent", short: "VIS", stage: "vision", icon: "V", iconPath: "/static/live_gui_icons/vision_agent.svg" },
  { id: "manipulation", label: "Manipulation Agent", short: "MAN", stage: "manipulation", icon: "M", iconPath: "/static/live_gui_icons/manipulation_agent.svg" },
  { id: "equipment", label: "Lab Equipment Agent", short: "EQP", stage: "equipment", icon: "E", iconPath: "/static/live_gui_icons/equipment_agent.svg" },
  { id: "analysis", label: "Analysis Agent", short: "ANL", stage: "analysis", icon: "A", iconPath: "/static/live_gui_icons/analysis_agent.svg" },
  { id: "knowledge", label: "Knowledge Agent", short: "KNW", stage: "knowledge", icon: "K", iconPath: "/static/live_gui_icons/knowledge_agent.svg" },
  { id: "bo", label: "BO Agent", short: "BO", stage: "bo", icon: "B", iconPath: "/static/live_gui_icons/bo_agent.svg" },
  { id: "guardian", label: "Guardian Agent", short: "GRD", stage: "guardian", icon: "G", iconPath: "/static/live_gui_icons/guardian_agent.svg" },
];

let liveSelectedAgent = "orchestrator";
let liveCurrentView = "report";
let liveLastSession = {};
let liveLastSnapshot = {};
let liveRecentEvents = [];
let liveRunEvents = [];
let liveRunArtifacts = [];
let liveGraphPayload = null;
let liveGraphActionStatus = null;
let liveSelectedGraphNodeId = "";
let liveSelectedEventKey = "";
let liveGraphSelectionCleared = false;
let liveSelectedReportSectionTitle = "Overview / Summary";
let liveTimelineFilter = "all";
let liveApprovals = { approvals: [], pending: [], resolved: [] };
let liveResolvedApprovalIds = new Set();
let liveReadQuestionKeys = {};
let liveReadFaultKeys = {};
let liveReadMarkers = {};
let liveReviewedAgents = {};
let livePinnedFindings = [];
let liveOperatorReportStateRunId = "";
let liveRuntimeStartedAt = Date.now();
let liveStreamState = "connecting";
let liveSyncState = "idle";
let liveLastSyncAt = null;
let liveLastEventAt = null;
let liveSyncFailureCount = 0;
let liveRefreshInFlight = null;
const LIVE_AUTO_REFRESH_MS = 5000;
const LIVE_SYNC_STALE_MS = 15000;
const LIVE_SYNC_ERROR_MS = 60000;
let liveRuntimeRenderQueued = false;
let liveRuntimeRenderQueuedSession = null;
const liveCenterRenderKeys = new Map();

let queryGoal = "Design and validate a live-mode specimen plan before hardware execution.";
let queryBackend = "vllm";
let planningMessagesCache = [];
const BO_EXPANDED_STORAGE_KEY = "atr_live_bo_expanded_cards";
function loadExpandedBoCards() {
  try {
    const raw = sessionStorage.getItem(BO_EXPANDED_STORAGE_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(list) ? list.filter((item) => typeof item === "string") : []);
  } catch (_err) {
    return new Set();
  }
}
function saveExpandedBoCards() {
  try {
    liveExpandedBoCards = new Set([...liveExpandedBoCards].slice(-40));
    sessionStorage.setItem(BO_EXPANDED_STORAGE_KEY, JSON.stringify([...liveExpandedBoCards]));
  } catch (_err) {
    // Session storage can be unavailable in hardened browser contexts.
  }
}
let liveExpandedBoCards = loadExpandedBoCards();
let planningSessionId = "";
let planningThinkingCount = 0;
let liveQuickActionBusy = false;
let liveSafeStopArmedUntil = 0;
let liveSafeStopArmTimer = null;
let liveBackendPlanningBusy = false;
let liveBottomCollapsed = false;
let planningBootstrapStarted = false;
let planningRefreshTimer = null;
let planningFreshSessionInitialized = false;
let planningPendingSpecimenInput = null;

function liveSessionStorage() {
  try {
    return window.localStorage || window.sessionStorage;
  } catch (err) {
    try {
      return window.sessionStorage;
    } catch (fallbackErr) {
      return null;
    }
  }
}

function knownLiveAgent(agentId) {
  return LIVE_AGENTS.some((agent) => agent.id === agentId);
}

const LIVE_CHAT_TARGET_SPECIALS = new Set(["current_agent", "selected_agent"]);

function validLiveChatTarget(target) {
  const value = String(target || "");
  return LIVE_CHAT_TARGET_SPECIALS.has(value) || (knownLiveAgent(value) && value !== "objective");
}

function liveChatTargetForAgent(agentId) {
  return validLiveChatTarget(agentId) ? String(agentId) : "selected_agent";
}

function setLiveChatTargetMode(target = "selected_agent") {
  if (!liveChatTarget) return;
  liveChatTarget.value = validLiveChatTarget(target) ? target : "selected_agent";
}

function setLiveBottomCollapsed(collapsed, options = {}) {
  liveBottomCollapsed = Boolean(collapsed);
  const shell = document.querySelector(".planning-runtime-shell");
  if (shell) shell.classList.toggle("live-bottom-collapsed", liveBottomCollapsed);
  document.body.classList.toggle("live-bottom-collapsed", liveBottomCollapsed);
  if (btnLiveBottomCollapse) {
    btnLiveBottomCollapse.setAttribute("aria-expanded", liveBottomCollapsed ? "false" : "true");
    setCompactTextWithTitle(
      btnLiveBottomCollapse,
      liveBottomCollapsed ? "Show Dock" : "Hide Dock",
      liveBottomCollapsed ? "Expand bottom event and IO dock" : "Collapse bottom event and IO dock"
    );
  }
  if (options.persist !== false) persistLiveUiState();
}

function currentRuntimeAgent() {
  const state = (liveLastSession && liveLastSession.state) || (liveLastSnapshot && liveLastSnapshot.state) || {};
  return agentIdFromStage(state.stage || "") || liveSelectedAgent || "orchestrator";
}

function selectedRuntimeContextAgent() {
  const event = typeof selectedTimelineEvent === "function" ? selectedTimelineEvent() : null;
  const eventAgent = event ? agentIdFromEvent(event) : "";
  return knownLiveAgent(eventAgent) ? eventAgent : (knownLiveAgent(liveSelectedAgent) ? liveSelectedAgent : "orchestrator");
}

function resolveLiveChatTarget(target = liveChatTarget ? liveChatTarget.value : "selected_agent") {
  const value = String(target || "selected_agent");
  if (value === "current_agent") return currentRuntimeAgent();
  if (value === "selected_agent") return selectedRuntimeContextAgent();
  return knownLiveAgent(value) ? value : selectedRuntimeContextAgent();
}

function liveUiStatePayload() {
  return {
    selectedAgent: knownLiveAgent(liveSelectedAgent) ? liveSelectedAgent : "orchestrator",
    currentView: LIVE_VIEW_IDS.has(liveCurrentView) ? liveCurrentView : "report",
    selectedGraphNodeId: String(liveSelectedGraphNodeId || ""),
    selectedEventKey: String(liveSelectedEventKey || ""),
    graphSelectionCleared: Boolean(liveGraphSelectionCleared),
    selectedReportSectionTitle: String(liveSelectedReportSectionTitle || ""),
    timelineFilter: LIVE_TIMELINE_FILTER_IDS.has(liveTimelineFilter) ? liveTimelineFilter : "all",
    chatTarget: liveChatTarget && validLiveChatTarget(liveChatTarget.value) ? String(liveChatTarget.value) : "selected_agent",
    chatMode: liveChatMode ? String(liveChatMode.value || "ask") : "ask",
    bottomCollapsed: Boolean(liveBottomCollapsed),
    planningSessionId: planningSessionId || "",
    updatedAt: new Date().toISOString(),
  };
}

function persistLiveUiState() {
  const storage = liveSessionStorage();
  if (!storage) return;
  try {
    storage.setItem(LIVE_UI_STATE_KEY, JSON.stringify(liveUiStatePayload()));
  } catch (err) {
    // Runtime operation must continue even when browser storage is unavailable.
  }
}

function restoreLiveUiState() {
  const params = new URLSearchParams(window.location.search);
  const storage = liveSessionStorage();
  if (!storage) return;
  try {
    if (params.get("fresh") === "1") {
      storage.removeItem(LIVE_UI_STATE_KEY);
      return;
    }
    const saved = JSON.parse(storage.getItem(LIVE_UI_STATE_KEY) || "{}");
    if (knownLiveAgent(saved.selectedAgent)) liveSelectedAgent = saved.selectedAgent;
    if (LIVE_VIEW_IDS.has(saved.currentView)) liveCurrentView = saved.currentView;
    if (LIVE_TIMELINE_FILTER_IDS.has(saved.timelineFilter)) liveTimelineFilter = saved.timelineFilter;
    liveSelectedGraphNodeId = String(saved.selectedGraphNodeId || "");
    liveSelectedEventKey = String(saved.selectedEventKey || "");
    liveGraphSelectionCleared = Boolean(saved.graphSelectionCleared);
    liveSelectedReportSectionTitle = String(saved.selectedReportSectionTitle || liveSelectedReportSectionTitle || "Overview / Summary");
    if (liveChatMode && saved.chatMode) liveChatMode.value = String(saved.chatMode);
    if (liveChatTarget && validLiveChatTarget(saved.chatTarget)) liveChatTarget.value = saved.chatTarget;
    setLiveBottomCollapsed(Boolean(saved.bottomCollapsed), { persist: false });
    setLiveView(liveCurrentView);
  } catch (err) {
    // Ignore malformed or stale UI state.
  }
}

const LIVE_TOOLTIP_SELECTOR = [
  ".live-quick-action",
  ".live-report-action",
  ".live-view-tab",
  ".live-selected-event-action",
  ".live-selected-node-action",
  ".live-question-action",
  ".live-fault-action",
  ".live-device-card",
  ".live-timeline-filter",
  ".live-timeline-item",
  ".binder-tab",
  ".runtime-chip",
  ".runtime-chip[title]",
  ".live-runtime-metrics span[title]",
  ".live-runtime-metrics span",
  ".planning-composer-actions .btn",
  ".planning-trigger-hint",
].join(", ");

function liveTooltipTarget(target) {
  if (!target || !target.closest || !document.body.classList.contains("planning-live-body")) return null;
  return target.closest(LIVE_TOOLTIP_SELECTOR);
}

function liveTooltipText(element) {
  if (!element) return "";
  return String(element.dataset.liveTooltip || element.getAttribute("aria-label") || element.getAttribute("title") || "").trim();
}

function syncLiveTooltipAttributes(root = document) {
  if (!root || !root.querySelectorAll) return;
  for (const element of root.querySelectorAll(LIVE_TOOLTIP_SELECTOR)) {
    if (!(element instanceof Element)) continue;
    const title = String(element.getAttribute("title") || "").trim();
    if (!title) continue;
    if (!element.dataset.liveTooltip) element.dataset.liveTooltip = title;
    element.removeAttribute("title");
  }
}

function showLiveHoverTooltip(target) {
  if (!liveHoverTooltip) return;
  const element = liveTooltipTarget(target);
  const text = liveTooltipText(element);
  if (!element || !text) {
    hideLiveHoverTooltip();
    return;
  }
  liveHoverTooltip.textContent = text;
  liveHoverTooltip.hidden = false;
  const rect = element.getBoundingClientRect();
  const tipRect = liveHoverTooltip.getBoundingClientRect();
  const gap = 10;
  const maxLeft = Math.max(8, window.innerWidth - tipRect.width - 8);
  let left = rect.left + rect.width / 2 - tipRect.width / 2;
  let top = rect.bottom + gap;
  left = Math.min(maxLeft, Math.max(8, left));
  if (top + tipRect.height + 8 > window.innerHeight) {
    top = Math.max(8, rect.top - tipRect.height - gap);
  }
  liveHoverTooltip.style.left = `${Math.round(left)}px`;
  liveHoverTooltip.style.top = `${Math.round(top)}px`;
}

function hideLiveHoverTooltip() {
  if (!liveHoverTooltip) return;
  liveHoverTooltip.hidden = true;
  liveHoverTooltip.textContent = "";
}

const liveTooltipMutationObserver = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    for (const node of mutation.addedNodes || []) {
      if (!(node instanceof Element)) continue;
      syncLiveTooltipAttributes(node);
      for (const element of node.querySelectorAll ? node.querySelectorAll(LIVE_TOOLTIP_SELECTOR) : []) {
        if (element instanceof Element) syncLiveTooltipAttributes(element);
      }
    }
    if (mutation.target instanceof Element) syncLiveTooltipAttributes(mutation.target);
  }
});

function isLiveEditableTarget(target) {
  if (!target || !target.closest) return false;
  return Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
}

function toggleLiveShortcutOverlay(force) {
  if (!liveShortcutOverlay) return false;
  const shouldShow = typeof force === "boolean" ? force : liveShortcutOverlay.hidden;
  liveShortcutOverlay.hidden = !shouldShow;
  if (shouldShow) hideLiveHoverTooltip();
  return shouldShow;
}

function liveShortcutKey(event) {
  return String(event.key || "").toLowerCase();
}

function runLiveKeyboardShortcut(event) {
  const key = liveShortcutKey(event);
  const editable = isLiveEditableTarget(event.target);
  if (key === "escape") {
    hideLiveHoverTooltip();
    toggleLiveShortcutOverlay(false);
    closeBinderContextMenu();
    return false;
  }
  if (!editable && key === "?" && !event.altKey && !event.ctrlKey && !event.metaKey) {
    event.preventDefault();
    toggleLiveShortcutOverlay();
    return true;
  }
  const modified = event.altKey && event.shiftKey && !event.ctrlKey && !event.metaKey;
  if (!modified) return false;
  const safetyShortcut = key === "x";
  if (editable && !safetyShortcut) return false;
  const viewByKey = { r: "report", b: "backend", g: "graph", a: "artifacts", t: "timeline" };
  const actionByKey = { d: "dry_run", n: "run_node_test", p: "pause_run", o: "resume_run", x: "safe_stop" };
  if (viewByKey[key]) {
    event.preventDefault();
    setLiveView(viewByKey[key]);
    renderLiveRuntime(liveLastSession);
    setChatStatus(String(viewByKey[key]).toUpperCase(), "idle");
    return true;
  }
  if (key === "u") {
    event.preventDefault();
    refreshPlanningState();
    setChatStatus("REFRESH", "running");
    return true;
  }
  const action = actionByKey[key];
  if (action) {
    event.preventDefault();
    const useBusyLock = LIVE_BUSY_QUICK_ACTIONS.has(action);
    if (liveQuickActionBusy && action !== "safe_stop") return true;
    if (useBusyLock) setLiveQuickActionBusy(true);
    runLiveQuickAction(action).catch((err) => {
      setChatStatus("SHORTCUT ERROR", "warning");
      renderPlanningMessages([...planningMessagesCache, { role: "system", content: `Shortcut action failed: ${err}` }]);
    }).finally(() => {
      if (useBusyLock) setLiveQuickActionBusy(false);
    });
    return true;
  }
  return false;
}

function persistPlanningSessionId(sessionId) {
  const clean = String(sessionId || "").trim();
  if (!clean) return planningSessionId;
  planningSessionId = clean;
  const storage = liveSessionStorage();
  if (storage) {
    try {
      storage.setItem("autonomousLivePlanningSessionId", clean);
    } catch (err) {
      // Keep the in-memory id when storage is unavailable.
    }
  }
  return clean;
}

function ensurePlanningSessionId() {
  const key = "autonomousLivePlanningSessionId";
  const params = new URLSearchParams(window.location.search);
  const storage = liveSessionStorage();
  try {
    if (params.get("fresh") === "1" && !planningFreshSessionInitialized) {
      if (storage) storage.removeItem(key);
      planningFreshSessionInitialized = true;
    }
    let existing = storage ? storage.getItem(key) : "";
    if (!existing) {
      existing = planningSessionId || `live-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      if (storage) storage.setItem(key, existing);
    }
    planningSessionId = existing;
    return existing;
  } catch (err) {
    if (!planningSessionId) {
      planningSessionId = `live-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
    return planningSessionId;
  }
}

function applyQueryGoal() {
  const params = new URLSearchParams(window.location.search);
  queryGoal = params.get("goal") || queryGoal;
  queryBackend = params.get("backend") || queryBackend;
  if (planningGoalInput) {
    planningGoalInput.value = queryGoal;
  }
  if (planningMaterialInput && params.get("material")) {
    planningMaterialInput.value = params.get("material");
  }
  if (planningSizeInput && params.get("size")) {
    planningSizeInput.value = params.get("size");
  }
  if (planningTimeInput && params.get("max_print_time_min")) {
    planningTimeInput.value = params.get("max_print_time_min");
  }
}

function setPlanningDot(isRunning) {
  if (!planningStateDot) return;
  planningStateDot.className = "status-dot";
  planningStateDot.classList.add(isRunning ? "busy" : "idle");
}

function renderSpecSummary(state) {
  if (!planningSpecSummary) return;
  const spec = state.current_experiment_spec || {};
  if (!Object.keys(spec).length) {
    planningSpecSummary.innerHTML = "";
    return;
  }
  planningSpecSummary.innerHTML = `
    <div class="log-entry">
      <small>current_experiment_spec</small>
      <pre>${escapeHtml(JSON.stringify(spec, null, 2))}</pre>
    </div>
  `;
}

function parseSize(value, fallback = [30, 30, 30]) {
  const parts = String(value || "")
    .split(/[,xX×\s]+/)
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
  return parts.length === 3 ? parts : fallback;
}

function collectOptionalConstraints() {
  const selectedEvent = typeof selectedTimelineEvent === "function" ? selectedTimelineEvent() : null;
  const selectedPayload = selectedEvent ? eventPayload(selectedEvent) : {};
  const session = liveLastSession || {};
  const snapshot = liveLastSnapshot || {};
  const state = session.state || snapshot.state || {};
  const chatTargetMode = liveChatTarget && validLiveChatTarget(liveChatTarget.value) ? liveChatTarget.value : "selected_agent";
  const chatTargetResolved = resolveLiveChatTarget(chatTargetMode);
  const constraints = {
    require_operator_approval: true,
    runtime_contract: "existing_stage_enum_only",
    live_run_id: state.run_id || "",
    live_mode: state.mode || "",
    live_stage: state.stage || "",
    live_is_running: liveRunningFlag(session, snapshot, state),
    live_active_goal: state.active_goal || "",
    live_chat_target: chatTargetResolved,
    live_chat_target_mode: chatTargetMode,
    live_chat_target_resolved: chatTargetResolved,
    live_chat_mode: liveChatMode ? liveChatMode.value : "ask",
    live_selected_agent: liveSelectedAgent,
    live_selected_view: liveCurrentView,
    live_selected_graph_node_id: liveSelectedGraphNodeId,
    live_selected_event_key: liveSelectedEventKey,
    live_selected_event_id: selectedEvent ? (selectedEvent.event_id || selectedEvent.id || selectedPayload.event_id || "") : "",
    live_selected_trace_id: selectedEvent ? (selectedEvent.trace_id || selectedPayload.trace_id || "") : "",
    live_selected_node_id: selectedEvent ? (selectedEvent.node_id || selectedPayload.node_id || "") : "",
    live_selected_event_type: selectedEvent ? (selectedEvent.event_type || selectedEvent.type || "") : "",
    live_selected_report_section: selectedReportSectionLabel(),
    live_selected_report_section_text: selectedReportSectionText(),
    live_timeline_filter: liveTimelineFilter,
    live_pinned_findings: livePinnedFindings.slice(0, 5),
  };
  if (planningMaterialInput && planningMaterialInput.value.trim()) {
    constraints.material = planningMaterialInput.value.trim();
  }
  if (planningSizeInput && planningSizeInput.value.trim()) {
    const size = parseSize(planningSizeInput.value, null);
    if (size) {
      constraints.max_specimen_size_mm = size;
      constraints.specimen_size_mm = size;
    }
  }
  if (planningTimeInput && planningTimeInput.value.trim()) {
    constraints.max_print_time_min = Number(planningTimeInput.value);
  }
  return constraints;
}

function collectPlanningPayload(message) {
  return {
    message,
    goal: planningGoalInput ? planningGoalInput.value : queryGoal,
    backend: queryBackend,
    session_id: ensurePlanningSessionId(),
    constraints: collectOptionalConstraints(),
  };
}

function setChatStatus(label, cls = "idle", title = null) {
  if (!planningChatStatus) return;
  planningChatStatus.textContent = label;
  planningChatStatus.className = `badge ${cls}`;
  planningChatStatus.title = title || label;
}

function relativeTimeLabel(value) {
  const date = value instanceof Date ? value : new Date(value || "");
  const ms = date.getTime();
  if (!Number.isFinite(ms)) return "-";
  const diff = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (diff < 2) return "now";
  if (diff < 60) return `${diff}s ago`;
  const minutes = Math.floor(diff / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

function setRuntimeChip(chip, label, cls, title) {
  if (!chip) return;
  chip.textContent = label;
  chip.className = `runtime-chip ${cls || "idle"}`;
  if (title) chip.title = title;
}

function updateLiveConnectionChips() {
  const streamClass = liveStreamState === "live" ? "ok" : liveStreamState === "error" ? "warning" : "idle";
  const eventLabel = liveLastEventAt ? ` · ${relativeTimeLabel(liveLastEventAt)}` : "";
  const streamTitle = liveLastEventAt
    ? `Runtime event stream: ${liveStreamState}. Last event ${new Date(liveLastEventAt).toLocaleString()}`
    : `Runtime event stream: ${liveStreamState}. Waiting for first event.`;
  setRuntimeChip(liveStreamChip, `SSE ${liveStreamState}${eventLabel}`, streamClass, streamTitle);

  const syncTimestamp = liveLastSyncAt ? new Date(liveLastSyncAt).getTime() : NaN;
  const syncAgeMs = Number.isFinite(syncTimestamp) ? Date.now() - syncTimestamp : Infinity;
  let displayedSyncState = liveSyncState;
  if (liveSyncState !== "refreshing" && liveSyncState !== "error") {
    if (!Number.isFinite(syncTimestamp)) displayedSyncState = "idle";
    else if (syncAgeMs > LIVE_SYNC_ERROR_MS) displayedSyncState = "error";
    else if (syncAgeMs > LIVE_SYNC_STALE_MS) displayedSyncState = "stale";
    else displayedSyncState = "ok";
  }
  const syncAge = liveLastSyncAt ? relativeTimeLabel(liveLastSyncAt) : "-";
  const syncClass = displayedSyncState === "ok" ? "ok" : displayedSyncState === "refreshing" ? "running" : displayedSyncState === "stale" ? "warning" : displayedSyncState === "error" ? "error" : "idle";
  const failureText = liveSyncFailureCount ? ` Failures: ${liveSyncFailureCount}.` : "";
  const syncTitle = liveLastSyncAt
    ? `Last state sync ${new Date(liveLastSyncAt).toLocaleString()}. State: ${displayedSyncState}.${failureText}`
    : `No state sync completed yet. State: ${displayedSyncState}.${failureText}`;
  setRuntimeChip(liveSyncChip, displayedSyncState === "refreshing" ? `Sync ...` : `Sync ${syncAge}`, syncClass, syncTitle);
}

function markLiveSyncRefreshStart() {
  liveSyncState = "refreshing";
  updateLiveConnectionChips();
}

function markLiveSyncComplete() {
  liveSyncState = "ok";
  liveSyncFailureCount = 0;
  liveLastSyncAt = new Date().toISOString();
  updateLiveConnectionChips();
}

function markLiveSyncError(err) {
  liveSyncState = "error";
  liveSyncFailureCount += 1;
  if (err && liveSyncChip) liveSyncChip.dataset.lastError = String(err);
  updateLiveConnectionChips();
}

function liveSyncIsStale() {
  if (!liveLastSyncAt) return true;
  const last = new Date(liveLastSyncAt).getTime();
  return !Number.isFinite(last) || Date.now() - last > LIVE_AUTO_REFRESH_MS;
}

function markLiveStreamState(state, eventTs = null) {
  liveStreamState = state || liveStreamState;
  if (eventTs) liveLastEventAt = eventTs;
  updateLiveConnectionChips();
}

function updatePlanningControls() {
  const isBusy = planningThinkingCount > 0 || liveQuickActionBusy || liveBackendPlanningBusy;
  if (btnPlanningSend) {
    btnPlanningSend.disabled = isBusy;
    btnPlanningSend.title = liveBackendPlanningBusy ? "Backend orchestrator is still reasoning in this session" : "Send message (Ctrl+Enter)";
  }
  if (btnPlanningGenerate) {
    btnPlanningGenerate.disabled = isBusy;
    btnPlanningGenerate.title = liveBackendPlanningBusy ? "Backend orchestrator is still reasoning in this session" : "Draft Plan";
  }
}

function setLiveBackendPlanningBusy(isBusy) {
  liveBackendPlanningBusy = Boolean(isBusy);
  if (planningChatStatus) {
    planningChatStatus.dataset.backendBusy = liveBackendPlanningBusy ? "1" : "0";
  }
  if (liveBackendPlanningBusy && planningThinkingCount === 0) {
    setChatStatus("BUSY", "running");
  } else if (!liveBackendPlanningBusy && planningChatStatus && planningChatStatus.textContent === "BUSY") {
    setChatStatus("READY", "idle");
  }
  updatePlanningControls();
}

function setLiveQuickActionBusy(isBusy) {
  liveQuickActionBusy = Boolean(isBusy);
  liveQuickActionButtons.forEach((button) => {
    const isSafeStop = button.dataset.quickAction === "safe_stop";
    button.disabled = liveQuickActionBusy && !isSafeStop;
    button.classList.toggle("is-busy", liveQuickActionBusy && !isSafeStop);
  });
  updatePlanningControls();
}

function resetLiveSafeStopArm() {
  liveSafeStopArmedUntil = 0;
  if (liveSafeStopArmTimer) {
    window.clearTimeout(liveSafeStopArmTimer);
    liveSafeStopArmTimer = null;
  }
  if (btnLiveSafeStop) {
    btnLiveSafeStop.classList.remove("is-armed");
    btnLiveSafeStop.textContent = "STOP";
    btnLiveSafeStop.title = "Safe Stop (Alt+Shift+X)";
    btnLiveSafeStop.setAttribute("aria-label", "Safe Stop");
  }
  liveQuickActionButtons.forEach((button) => {
    if (button.dataset.quickAction === "safe_stop") {
      button.classList.remove("is-armed");
      button.title = "Safe Stop (Alt+Shift+X)";
      button.setAttribute("aria-label", "Safe Stop");
    }
  });
}

function armLiveSafeStop() {
  liveSafeStopArmedUntil = Date.now() + 6000;
  if (liveSafeStopArmTimer) window.clearTimeout(liveSafeStopArmTimer);
  liveSafeStopArmTimer = window.setTimeout(resetLiveSafeStopArm, 6000);
  if (btnLiveSafeStop) {
    btnLiveSafeStop.classList.add("is-armed");
    btnLiveSafeStop.textContent = "CONFIRM";
    btnLiveSafeStop.title = "Safe Stop armed. Click again within 6 seconds to request safe stop.";
    btnLiveSafeStop.setAttribute("aria-label", "Confirm Safe Stop");
  }
  liveQuickActionButtons.forEach((button) => {
    if (button.dataset.quickAction === "safe_stop") {
      button.classList.add("is-armed");
      button.title = "Safe Stop armed. Click again within 6 seconds to request safe stop.";
      button.setAttribute("aria-label", "Confirm Safe Stop");
    }
  });
  setChatStatus("SAFE STOP?", "warning");
}

async function fetchJsonOrThrow(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.detail || data.message || `HTTP ${res.status}`);
  }
  return data;
}

function pushPlanningThinking() {
  planningThinkingCount += 1;
  updatePlanningControls();
}

function popPlanningThinking() {
  planningThinkingCount = Math.max(0, planningThinkingCount - 1);
  updatePlanningControls();
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalizeDisplayText(value) {
  return String(value || "")
    .replace(/\$\\leftrightarrow\$/g, "<->")
    .replace(/\$\\Leftarrow\$/g, "<=")
    .replace(/\$\\leftarrow\$/g, "<-")
    .replace(/\$\\Rightarrow\$/g, "=>")
    .replace(/\$\\rightarrow\$/g, "->")
    .replace(/\$\\to\$/g, "->")
    .replace(/\$\\dashrightarrow\$/g, "->")
    .replace(/\\leftrightarrow/g, "<->")
    .replace(/\\Leftarrow/g, "<=")
    .replace(/\\leftarrow/g, "<-")
    .replace(/\\Rightarrow/g, "=>")
    .replace(/\\rightarrow/g, "->")
    .replace(/\\to/g, "->")
    .replace(/\\dashrightarrow/g, "->");
}

function safeUrl(value) {
  const url = String(value || "");
  return url.startsWith("/api/planning/artifacts/") ? url : "";
}

function roleLabel(role) {
  const labels = {
    orchestrator: "Orchestrator",
    operator: "Operator",
    design_ai: "Design Agent",
    specimen_ai: "Specimen Making Agent",
    printer_ai: "Specimen Making Agent",
    vision_ai: "Vision Agent",
    manipulation_ai: "Manipulation Agent",
    equipment_ai: "Lab Equipment Agent",
    analysis_ai: "Analysis Agent",
    knowledge_ai: "Knowledge Agent",
    bo_ai: "BO Agent",
    guardian: "Guardian Agent",
    system: "System",
  };
  return labels[role] || role || "Orchestrator";
}

function renderSingleArtifactCard(artifacts, spec, label = "", options = {}) {
  const previewUrl = safeUrl(artifacts.preview_url);
  const stlUrl = safeUrl(artifacts.stl_url);
  const specUrl = safeUrl(artifacts.experiment_spec_url);
  if (!previewUrl && !stlUrl && !specUrl) return "";
  const showStlViewer = options.showStlViewer !== false;
  const showStlLink = options.showStlLink !== false;

  const specimenId = escapeHtml(spec.specimen_id || "specimen");
  const geometry = escapeHtml(spec.geometry_type || "geometry");
  const size = escapeHtml(JSON.stringify(spec.specimen_size_mm || []));

  return `
    <div class="artifact-card">
      ${previewUrl ? `<img class="artifact-preview" src="${escapeHtml(previewUrl)}" alt="STL preview for ${specimenId}" />` : ""}
      <div class="artifact-meta">
        ${label ? `<em>${escapeHtml(label)}</em>` : ""}
        <strong>${specimenId}</strong>
        <span>${geometry} / size=${size}</span>
        <div class="artifact-links">
          ${stlUrl && showStlLink ? `<a href="${escapeHtml(stlUrl)}" target="_blank" rel="noreferrer">Open STL</a>` : ""}
          ${specUrl ? `<a href="${escapeHtml(specUrl)}" target="_blank" rel="noreferrer">experiment_spec.json</a>` : ""}
        </div>
      </div>
      ${stlUrl && showStlViewer ? `
        <div class="stl-viewer-wrap">
          <canvas class="stl-viewer" data-stl-url="${escapeHtml(stlUrl)}" width="720" height="420"></canvas>
          <div class="stl-viewer-hint">drag to rotate / wheel to zoom</div>
        </div>
      ` : ""}
    </div>
  `;
}

function renderArtifactCard(msg) {
  if (msg.render_artifacts === false || msg.role === "printer_ai") return "";
  if (msg.role === "analysis_ai" && msg.fem_artifacts) return "";
  const artifactOptions = { showStlViewer: msg.role !== "design_ai", showStlLink: msg.role !== "design_ai" };
  const pair = msg.artifact_pair || {};
  if (pair.previous || pair.next) {
    const previous = pair.previous || {};
    const next = pair.next || {};
    const previousCard = renderSingleArtifactCard(
      previous.artifacts || {},
      previous.experiment_spec || {},
      previous.label || "Previous shape",
      artifactOptions
    );
    const nextCard = renderSingleArtifactCard(
      next.artifacts || {},
      next.experiment_spec || msg.experiment_spec || {},
      next.label || "Next shape",
      artifactOptions
    );
    return `<div class="artifact-pair">${previousCard}${nextCard}</div>`;
  }
  return renderSingleArtifactCard(msg.artifacts || {}, msg.experiment_spec || {}, "", artifactOptions);
}

function renderFemContourCard(msg) {
  const fem = msg.fem_artifacts || {};
  const contourUrl = safeUrl(fem.contour_url);
  const reportUrl = safeUrl(fem.report_url);
  if (!contourUrl && !reportUrl) return "";
  return `
    <div class="fem-contour-card">
      <div class="fem-contour-head">
        <strong>FEM / CAE Contour</strong>
        ${reportUrl ? `<a href="${escapeHtml(reportUrl)}" target="_blank" rel="noreferrer">CAE report</a>` : ""}
      </div>
      ${contourUrl ? `<img class="fem-contour-preview" src="${escapeHtml(contourUrl)}" alt="FEM contour visualization" />` : ""}
    </div>
  `;
}

function numberText(value, digits = 4) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "n/a";
  return String(Number(num.toFixed(digits)));
}

function finiteRange(values, fallback = [0, 1]) {
  const nums = values.map(Number).filter(Number.isFinite);
  if (!nums.length) return fallback;
  let min = Math.min(...nums);
  let max = Math.max(...nums);
  if (Math.abs(max - min) < 1e-9) {
    min -= 0.5;
    max += 0.5;
  }
  return [min, max];
}

function scaleLinear(value, domain, range) {
  const v = Number(value);
  if (!Number.isFinite(v)) return range[0];
  const t = (v - domain[0]) / Math.max(1e-9, domain[1] - domain[0]);
  return range[0] + Math.max(0, Math.min(1, t)) * (range[1] - range[0]);
}

function polyline(points) {
  return points.map(([x, y]) => `${numberText(x, 2)},${numberText(y, 2)}`).join(" ");
}

function compactBoParamValue(value) {
  const num = Number(value);
  if (Number.isFinite(num)) return numberText(num, 4);
  if (value === null || value === undefined || value === "") return "n/a";
  return String(value);
}

function compactBoParams(params) {
  const p = params || {};
  const keys = ["geometry_type", "relative_density", "wall_thickness_mm", "cell_size_mm", "tpms_thickness", "orientation_deg", "anisotropy_ratio"];
  return keys
    .filter((key) => p[key] !== undefined && p[key] !== null)
    .map((key) => `${key}=${compactBoParamValue(p[key])}`)
    .join(", ");
}

function boStrategyFromBenchmark(benchmark) {
  const strategies = benchmark && benchmark.strategies ? benchmark.strategies : {};
  if (strategies.bo) return strategies.bo;
  const firstKey = Object.keys(strategies)[0];
  return firstKey ? strategies[firstKey] : null;
}

function renderBoTraceSvg(trace) {
  const candidates = Array.isArray(trace.candidates) ? trace.candidates : [];
  if (!candidates.length) {
    return `<div class="bo-plot-empty">BO candidate landscape가 없습니다.</div>`;
  }

  const width = 840;
  const height = 320;
  const pad = { left: 52, right: 24, top: 28, bottom: 48 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const xDomain = finiteRange(candidates.map((item) => item.x), [1, candidates.length || 1]);
  const meanValues = candidates.flatMap((item) => [
    Number(item.surrogate_mean) - Number(item.uncertainty || 0) * 0.12,
    Number(item.surrogate_mean),
    Number(item.surrogate_mean) + Number(item.uncertainty || 0) * 0.12,
  ]);
  const acqValues = candidates.map((item) => item.acquisition_value);
  const scoreValues = (trace.evaluated_points || []).map((item) => item.score);
  const meanDomain = finiteRange(meanValues, [0, 1]);
  const acqDomain = finiteRange(acqValues, [0, 1]);
  const scoreDomain = finiteRange(scoreValues.length ? scoreValues : meanValues, meanDomain);
  const xScale = (value) => pad.left + scaleLinear(value, xDomain, [0, plotW]);
  const yMean = (value) => pad.top + scaleLinear(value, meanDomain, [plotH, 0]);
  const yAcq = (value) => pad.top + scaleLinear(value, acqDomain, [plotH, 0]);
  const yScore = (value) => pad.top + scaleLinear(value, scoreDomain, [plotH, 0]);
  const meanLine = candidates.map((item) => [xScale(item.x), yMean(item.surrogate_mean)]);
  const acqLine = candidates.map((item) => [xScale(item.x), yAcq(item.acquisition_value)]);
  const upper = candidates.map((item) => [xScale(item.x), yMean(Number(item.surrogate_mean) + Number(item.uncertainty || 0) * 0.12)]);
  const lower = candidates
    .slice()
    .reverse()
    .map((item) => [xScale(item.x), yMean(Number(item.surrogate_mean) - Number(item.uncertainty || 0) * 0.12)]);
  const selected = trace.selected || {};
  const selectedX = Number(selected.x);
  const selectedY = yAcq(selected.acquisition_value);
  const observed = Array.isArray(trace.evaluated_points) ? trace.evaluated_points.filter((item) => Number.isFinite(Number(item.x))) : [];
  const candidateCount = Number(trace.candidate_count || candidates.length);
  const xTicks = [1, Math.max(1, Math.round(candidateCount / 2)), candidateCount].filter((v, i, arr) => arr.indexOf(v) === i);
  const yTicks = [0, 0.5, 1];

  return `
    <svg class="bo-trace-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="BO surrogate and acquisition trace step ${escapeHtml(trace.step)}">
      <rect x="0" y="0" width="${width}" height="${height}" rx="18" class="bo-svg-bg"></rect>
      <line x1="${pad.left}" y1="${pad.top + plotH}" x2="${pad.left + plotW}" y2="${pad.top + plotH}" class="bo-axis"></line>
      <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${pad.top + plotH}" class="bo-axis"></line>
      ${xTicks.map((tick) => `
        <g>
          <line x1="${xScale(tick)}" y1="${pad.top}" x2="${xScale(tick)}" y2="${pad.top + plotH}" class="bo-grid"></line>
          <text x="${xScale(tick)}" y="${height - 18}" text-anchor="middle" class="bo-axis-label">${tick}</text>
        </g>
      `).join("")}
      ${yTicks.map((tick) => `
        <g>
          <line x1="${pad.left}" y1="${pad.top + plotH * (1 - tick)}" x2="${pad.left + plotW}" y2="${pad.top + plotH * (1 - tick)}" class="bo-grid"></line>
          <text x="${pad.left - 12}" y="${pad.top + plotH * (1 - tick) + 4}" text-anchor="end" class="bo-axis-label">${tick}</text>
        </g>
      `).join("")}
      <polygon points="${polyline([...upper, ...lower])}" class="bo-uncertainty-band"></polygon>
      <polyline points="${polyline(meanLine)}" class="bo-mean-line"></polyline>
      <polyline points="${polyline(acqLine)}" class="bo-acq-line"></polyline>
      ${observed.map((point) => `
        <circle cx="${xScale(point.x)}" cy="${yScore(point.score)}" r="5.8" class="bo-observed-point">
          <title>${escapeHtml(point.candidate_id || point.source || "observed")} score=${escapeHtml(numberText(point.score, 5))} ${escapeHtml(compactBoParams(point.parameters))}</title>
        </circle>
      `).join("")}
      ${Number.isFinite(selectedX) ? `
        <line x1="${xScale(selectedX)}" y1="${pad.top}" x2="${xScale(selectedX)}" y2="${pad.top + plotH}" class="bo-selected-line"></line>
        <circle cx="${xScale(selectedX)}" cy="${selectedY}" r="8" class="bo-selected-point">
          <title>${escapeHtml(selected.candidate_id || "selected")} acquisition=${escapeHtml(numberText(selected.acquisition_value, 5))} ${escapeHtml(compactBoParams(selected.parameters))}</title>
        </circle>
      ` : ""}
      <text x="${pad.left}" y="20" class="bo-svg-title">step ${escapeHtml(trace.step)} · ${escapeHtml(trace.acquisition || "acquisition")} · candidate pool index</text>
      <g class="bo-legend">
        <line x1="${width - 330}" y1="20" x2="${width - 300}" y2="20" class="bo-mean-line"></line>
        <text x="${width - 294}" y="24">surrogate mean</text>
        <line x1="${width - 190}" y1="20" x2="${width - 160}" y2="20" class="bo-acq-line"></line>
        <text x="${width - 154}" y="24">acquisition</text>
      </g>
    </svg>
  `;
}

function boCardKey(msg, index = "") {
  const boResult = msg.bo_result && typeof msg.bo_result === "object" ? msg.bo_result : {};
  const benchmark = boResult.benchmark || {};
  const strategyPayload = boStrategyFromBenchmark(benchmark);
  const trace = strategyPayload && Array.isArray(strategyPayload.surrogate_trace) ? strategyPayload.surrogate_trace : [];
  const recommendation = boResult.recommendation && typeof boResult.recommendation === "object" ? boResult.recommendation : {};
  const parts = [
    index,
    msg.created_at || msg.timestamp || msg.run_id || "",
    boResult.strategy || "",
    boResult.acquisition || "",
    recommendation.candidate_id || "",
    trace.length,
  ];
  return parts.map((item) => String(item || "").replace(/[^a-zA-Z0-9_.:-]+/g, "-")).join("::");
}

function renderBoExpandedBody(trace) {
  const visibleTrace = trace.length > 12 ? trace.slice(-12) : trace;
  const selectedRows = trace
    .map((item) => {
      const selected = item.selected || {};
      return `
        <div class="bo-selected-row">
          <strong>#${escapeHtml(item.step || "")}</strong>
          <span>${escapeHtml(selected.candidate_id || "candidate")}</span>
          <code>${escapeHtml(compactBoParams(selected.parameters))}</code>
          <em>score=${escapeHtml(numberText(selected.score, 5))} · acq=${escapeHtml(numberText(selected.acquisition_value, 5))}</em>
        </div>
      `;
    })
    .join("");

  return `
    <div class="bo-plot-stack">
      ${trace.length > visibleTrace.length ? `<p class="hint">최근 ${visibleTrace.length}/${trace.length} step만 표시합니다.</p>` : ""}
      ${visibleTrace.length
        ? visibleTrace.map((item) => `<article class="bo-trace-card">${renderBoTraceSvg(item)}</article>`).join("")
        : `<div class="bo-plot-empty">BO surrogate/acquisition trace가 없습니다. BO/MBO strategy 결과가 들어오면 여기에 표시됩니다.</div>`}
    </div>
    ${selectedRows ? `<div class="bo-selected-points">${selectedRows}</div>` : ""}
  `;
}

function renderBoCollapsedBody(trace, latestSelected) {
  return `
    <div class="bo-plot-collapsed">
      <strong>그래프 접힘</strong>
      <span>BO surrogate/acquisition 그래프 ${escapeHtml(trace.length || 0)}개는 메모리 절약을 위해 아직 렌더링하지 않았습니다.</span>
      ${latestSelected && latestSelected.candidate_id ? `<code>latest=${escapeHtml(latestSelected.candidate_id)} · ${escapeHtml(compactBoParams(latestSelected.parameters))}</code>` : ""}
    </div>
  `;
}

function renderBoResultCard(msg, index = "") {
  const boResult = msg.bo_result && typeof msg.bo_result === "object" ? msg.bo_result : {};
  if (msg.role !== "bo_ai" || !Object.keys(boResult).length) return "";
  const benchmark = boResult.benchmark || {};
  const strategyPayload = boStrategyFromBenchmark(benchmark);
  const trace = strategyPayload && Array.isArray(strategyPayload.surrogate_trace) ? strategyPayload.surrogate_trace : [];
  const recommendation = boResult.recommendation && typeof boResult.recommendation === "object" ? boResult.recommendation : {};
  const latestTrace = trace.length ? trace[trace.length - 1] : {};
  const latestSelected = latestTrace.selected || {};
  const cardKey = boCardKey(msg, index);
  const expanded = liveExpandedBoCards.has(cardKey);

  return `
    <div class="bo-live-card" data-bo-card-key="${escapeHtml(cardKey)}">
      <div class="runtime-card-section bo-card-summary">
        <div class="bo-card-head">
          <h4>BO Surrogate / Acquisition Trace</h4>
          <button class="btn small bo-graph-toggle" type="button" data-bo-card-key="${escapeHtml(cardKey)}" aria-expanded="${expanded ? "true" : "false"}">${expanded ? "그래프 접기" : "그래프 보기"}</button>
        </div>
        ${runtimeRows([
          ["strategy", boResult.strategy],
          ["acquisition", boResult.acquisition],
          ["budget", boResult.budget],
          ["trace_steps", trace.length],
          ["latest_candidate", latestSelected.candidate_id],
          ["recommended_candidate", recommendation.candidate_id],
          ["recommended_score", recommendation.objective_score],
        ])}
      </div>
      <div class="bo-graph-body">
        ${expanded ? renderBoExpandedBody(trace) : renderBoCollapsedBody(trace, latestSelected)}
      </div>
    </div>
  `;
}

function renderRuntimeValue(value, fallback = "n/a") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value) || typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderCompactMemoryGb(value, fallback = "n/a") {
  if (value === null || value === undefined || value === "") return fallback;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  const absValue = Math.abs(numeric);
  if (absValue >= 10) return String(Math.round(numeric));
  return String(Math.round(numeric * 10) / 10);
}

function runtimeRows(rows) {
  return rows
    .filter((row) => row && row.length >= 2)
    .map(([label, value]) => `
      <div class="runtime-row">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(renderRuntimeValue(value))}</strong>
      </div>
    `)
    .join("");
}

function renderStepTrace(trace) {
  if (!Array.isArray(trace) || !trace.length) return "";
  return `
    <ol class="runtime-steps">
      ${trace.map((step) => {
        const detail = step && step.detail ? ` · ${step.detail}` : "";
        return `<li><span>${escapeHtml(renderRuntimeValue(step.step, "STEP"))}</span><strong>${escapeHtml(renderRuntimeValue(step.status, "unknown"))}${escapeHtml(detail)}</strong></li>`;
      }).join("")}
    </ol>
  `;
}

function renderSpecimenRuntimeCard(msg) {
  if (msg.role !== "printer_ai" && msg.role !== "specimen_ai") return "";
  const specimen = msg.specimen || {};
  const toolResult = specimen.tool_result || {};
  const settings = specimen.slicer_settings || toolResult.slicer_settings || {};
  const prusalink = specimen.prusalink || toolResult.prusalink || {};
  const printer = specimen.printer || toolResult.printer || {};
  const slicerResult = specimen.slicer_result || toolResult.slicer_result || {};
  const gcodeValidation = specimen.gcode_validation || toolResult.gcode_validation || {};
  const printResult = specimen.print_result || toolResult.print_result || {};
  const setReady = printResult.set_ready || specimen.set_ready || toolResult.set_ready || {};
  const uploadResult = printResult.upload || {};
  const transferWait = printResult.transfer_wait || {};
  const startResult = printResult.start || {};
  const ejectionResult = specimen.ejection_result || toolResult.ejection_result || {};
  const trace = specimen.step_trace || toolResult.step_trace || [];
  if (!Object.keys(settings).length && !trace.length) return "";

  const command = Array.isArray(settings.resolved_command) ? settings.resolved_command.join(" ") : "";
  return `
    <div class="printer-runtime-card">
      <div class="runtime-card-section">
        <h4>PrusaSlicer Settings</h4>
        ${runtimeRows([
          ["printer_profile", settings.printer_profile],
          ["material", settings.material],
          ["slicer_profile_hint", settings.slicer_profile_hint],
          ["layer_height_mm", settings.layer_height_mm],
          ["first_layer_height_mm", settings.first_layer_height_mm],
          ["nozzle_diameter_mm", settings.nozzle_diameter_mm],
          ["bed_temperature_c", settings.bed_temperature_c],
          ["first_layer_bed_temperature_c", settings.first_layer_bed_temperature_c],
          ["slow_first_layer_enabled", settings.slow_first_layer_enabled],
          ["first_layer_speed_mm_s", settings.first_layer_speed_mm_s],
          ["wall_thickness_mm", settings.wall_thickness_mm],
          ["cell_size_mm", settings.cell_size_mm],
          ["relative_density", settings.relative_density],
          ["skirt_enabled", settings.skirt_enabled],
          ["bottom_cap_enabled", settings.bottom_cap_enabled],
          ["top_cap_enabled", settings.top_cap_enabled],
          ["top_bottom_cap", settings.top_bottom_cap],
          ["skin_thickness_mm", settings.skin_thickness_mm],
          ["expected_mass_g", settings.expected_mass_g || specimen.expected_mass_g],
          ["input_model_path", settings.input_model_path],
          ["output_gcode_path", settings.output_gcode_path],
          ["simulated", settings.simulated],
        ])}
        ${command ? `<pre class="runtime-command">${escapeHtml(command)}</pre>` : ""}
      </div>
      <div class="runtime-card-section">
        <h4>PrusaLink / Bridge</h4>
        ${runtimeRows([
          ["prepare_status", specimen.printer_prepare_status],
          ["printer_mode", specimen.printer_mode],
          ["printer_path", specimen.printer_path],
          ["printer_state", printer.state],
          ["transport", prusalink.transport],
          ["storage", prusalink.storage],
          ["storage_status", summarizeStorage(printer.storage, prusalink.storage)],
          ["set_ready", setReady.status || setReady.failure_code || (setReady.ok ? "ok" : "")],
          ["set_ready_job_id", setReady.job && setReady.job.job_id],
          ["set_ready_job_progress", setReady.job && setReady.job.progress],
          ["upload_endpoint", prusalink.upload_endpoint],
          ["upload_status", uploadResult.status || uploadResult.failure_code],
          ["upload_http_status", uploadResult.status_code],
          ["upload_elapsed_sec", uploadResult.elapsed_sec],
          ["upload_timeout_sec", uploadResult.timeout_sec],
          ["upload_bytes", uploadResult.bytes],
          ["transfer_wait_status", transferWait.status || transferWait.failure_code || (transferWait.ok ? "ok" : "")],
          ["transfer_wait_attempts", transferWait.attempts],
          ["transfer_last", transferWait.last_transfer],
          ["start_status", startResult.status || startResult.failure_code || (startResult.ok ? "ok" : "")],
          ["start_http_status", startResult.status_code],
          ["start_attempts", startResult.attempts],
          ["start_retry_history", startResult.retry_history],
          ["slicer_result", slicerResult.failure_code || (slicerResult.ok ? "ok" : "")],
          ["gcode_validation", gcodeValidation.failure_code || (gcodeValidation.ok ? "ok" : "")],
          ["print_result", printResult.status],
          ["ejection_result", ejectionResult.status],
          ["ejection_head_x_mm", ejectionResult.resolved && ejectionResult.resolved.head_x_mm],
          ["ejection_head_x_source", ejectionResult.resolved && ejectionResult.resolved.head_x_source],
          ["ejection_object_center_x_mm", ejectionResult.object_bounds && ejectionResult.object_bounds.center_x_mm],
        ])}
      </div>
      <div class="runtime-card-section runtime-card-wide">
        <h4>Step Trace</h4>
        ${renderStepTrace(trace)}
      </div>
    </div>
  `;
}

function summarizeStorage(storageResult, selectedStorage = "usb") {
  const selected = String(selectedStorage || "usb");
  if (!storageResult || typeof storageResult !== "object") return selected;
  if (storageResult.ok === false) return `${selected} (${storageResult.failure_code || "status_failed"})`;
  const payload = storageResult.payload && typeof storageResult.payload === "object" ? storageResult.payload : storageResult;
  const entries = Array.isArray(payload.storage_list) ? payload.storage_list : [];
  const item = entries.find((entry) => {
    if (!entry || typeof entry !== "object") return false;
    return String(entry.name || entry.path || "").replaceAll("/", "") === selected;
  });
  if (!item) return selected;
  return `${selected} available=${renderRuntimeValue(item.available)} read_only=${renderRuntimeValue(item.read_only)}`;
}

function renderReasoningBlock(msg) {
  if (msg.pendingReasoning) {
    return `
      <div class="reasoning-block reasoning-pending" aria-live="polite">
        <span class="reasoning-spinner" aria-hidden="true"></span>
        <span>reasoning</span>
      </div>
    `;
  }

  const reasoning = normalizeDisplayText(msg.reasoning).trim();
  if (!reasoning) return "";
  return `
    <details class="reasoning-block">
      <summary>
        <span class="reasoning-dot" aria-hidden="true"></span>
        <span>reasoning 보기 / 닫기</span>
      </summary>
      <pre>${escapeHtml(reasoning)}</pre>
    </details>
  `;
}

function scrollPlanningChatToBottom() {
  if (!planningChatLog) return;
  planningChatLog.scrollTop = planningChatLog.scrollHeight;
  window.requestAnimationFrame(() => {
    if (!planningChatLog) return;
    planningChatLog.scrollTop = planningChatLog.scrollHeight;
  });
}

function renderPlanningMessages(messages) {
  if (!planningChatLog) return;
  planningMessagesCache = Array.isArray(messages) ? messages : [];
  if (!messages || !messages.length) {
    planningChatLog.innerHTML = `
      <article class="planning-chat-item orchestrator">
        <small>Orchestrator</small>
        <div>실험 목표, 시편 조건, Design Agent 설계 후 Specimen Making Agent handoff 및 Guardian 확인을 여기서 정리하세요.</div>
      </article>
    `;
    scrollPlanningChatToBottom();
    return;
  }

  planningChatLog.innerHTML = "";
  for (const [messageIndex, msg] of messages.entries()) {
    const item = document.createElement("article");
    const role = msg.role || "orchestrator";
    item.className = `planning-chat-item ${role}`;
    const model = msg.model ? ` • ${msg.model}` : "";
    const content = msg.content
      ? escapeHtml(normalizeDisplayText(msg.content)).replaceAll("\n", "<br />")
      : msg.pendingReasoning
        ? "응답을 준비하고 있습니다."
        : "";
    item.innerHTML = `
      <small>${escapeHtml(roleLabel(role))}${escapeHtml(model)}</small>
      ${renderReasoningBlock(msg)}
      ${content ? `<div class="message-content">${content}</div>` : ""}
      ${renderSpecimenRuntimeCard(msg)}
      ${renderFemContourCard(msg)}
      ${renderBoResultCard(msg, `chat-${messageIndex}`)}
      ${renderArtifactCard(msg)}
    `;
    planningChatLog.appendChild(item);
  }
  scrollPlanningChatToBottom();
  initStlViewers();
}

const planningChatAutoScrollObserver = new MutationObserver(() => {
  scrollPlanningChatToBottom();
});

function parseAsciiStlVertices(text) {
  const vertices = [];
  const pattern = /vertex\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)/g;
  let match = pattern.exec(text);
  while (match) {
    vertices.push(Number(match[1]), Number(match[2]), Number(match[3]));
    match = pattern.exec(text);
  }
  return vertices;
}

function parseBinaryStlVertices(buffer) {
  const view = new DataView(buffer);
  if (view.byteLength < 84) return [];
  const triangleCount = view.getUint32(80, true);
  if (view.byteLength < 84 + triangleCount * 50) return [];
  const vertices = [];
  let offset = 84;
  for (let i = 0; i < triangleCount; i += 1) {
    offset += 12;
    for (let vertex = 0; vertex < 3; vertex += 1) {
      vertices.push(
        view.getFloat32(offset, true),
        view.getFloat32(offset + 4, true),
        view.getFloat32(offset + 8, true),
      );
      offset += 12;
    }
    offset += 2;
  }
  return vertices;
}

function parseStlVertices(buffer) {
  if (buffer.byteLength >= 84) {
    const view = new DataView(buffer);
    const triangleCount = view.getUint32(80, true);
    if (84 + triangleCount * 50 === buffer.byteLength) {
      return parseBinaryStlVertices(buffer);
    }
  }
  const text = new TextDecoder("utf-8").decode(buffer);
  return parseAsciiStlVertices(text);
}

function normalizeMesh(vertices) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < vertices.length; i += 3) {
    min[0] = Math.min(min[0], vertices[i]);
    min[1] = Math.min(min[1], vertices[i + 1]);
    min[2] = Math.min(min[2], vertices[i + 2]);
    max[0] = Math.max(max[0], vertices[i]);
    max[1] = Math.max(max[1], vertices[i + 1]);
    max[2] = Math.max(max[2], vertices[i + 2]);
  }
  const center = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
  const scale = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 1);
  return vertices.map((value, idx) => (value - center[idx % 3]) / scale * 2.2);
}

function computeNormals(vertices) {
  const faceNormals = [];
  const smoothSums = new Map();
  const smoothFaces = new Set();

  function keyAt(index) {
    return `${vertices[index].toFixed(5)},${vertices[index + 1].toFixed(5)},${vertices[index + 2].toFixed(5)}`;
  }

  const normals = new Array(vertices.length).fill(0);
  for (let i = 0; i < vertices.length; i += 9) {
    const ax = vertices[i];
    const ay = vertices[i + 1];
    const az = vertices[i + 2];
    const bx = vertices[i + 3];
    const by = vertices[i + 4];
    const bz = vertices[i + 5];
    const cx = vertices[i + 6];
    const cy = vertices[i + 7];
    const cz = vertices[i + 8];
    const ux = bx - ax;
    const uy = by - ay;
    const uz = bz - az;
    const vx = cx - ax;
    const vy = cy - ay;
    const vz = cz - az;
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const length = Math.hypot(nx, ny, nz) || 1;
    nx /= length;
    ny /= length;
    nz /= length;
    faceNormals.push([nx, ny, nz]);
    const absNormal = [Math.abs(nx), Math.abs(ny), Math.abs(nz)];
    const axisCount = absNormal.filter((value) => value > 1e-4).length;
    const axisAligned = Math.max(...absNormal) > 0.999 && axisCount === 1;
    if (!axisAligned) {
      smoothFaces.add(i);
      for (let j = 0; j < 3; j += 1) {
        const offset = i + j * 3;
        const key = keyAt(offset);
        const sum = smoothSums.get(key) || [0, 0, 0];
        sum[0] += nx;
        sum[1] += ny;
        sum[2] += nz;
        smoothSums.set(key, sum);
      }
    }
  }

  for (let i = 0; i < vertices.length; i += 9) {
    const faceNormal = faceNormals[i / 9] || [0, 0, 1];
    for (let j = 0; j < 3; j += 1) {
      const offset = i + j * 3;
      let normal = faceNormal;
      if (smoothFaces.has(i)) {
        const sum = smoothSums.get(keyAt(offset));
        if (sum) {
          const length = Math.hypot(sum[0], sum[1], sum[2]) || 1;
          normal = [sum[0] / length, sum[1] / length, sum[2] / length];
        }
      }
      normals[offset] = normal[0];
      normals[offset + 1] = normal[1];
      normals[offset + 2] = normal[2];
    }
  }
  return normals;
}

function compileShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) || "shader compile failed");
  }
  return shader;
}

function createProgram(gl) {
  const vertexSource = `
    attribute vec3 aPosition;
    attribute vec3 aNormal;
    uniform float uRotX;
    uniform float uRotY;
    uniform float uZoom;
    varying float vLight;

    vec3 rotateX(vec3 p, float a) {
      float s = sin(a);
      float c = cos(a);
      return vec3(p.x, p.y * c - p.z * s, p.y * s + p.z * c);
    }

    vec3 rotateY(vec3 p, float a) {
      float s = sin(a);
      float c = cos(a);
      return vec3(p.x * c + p.z * s, p.y, -p.x * s + p.z * c);
    }

    void main() {
      vec3 p = rotateY(rotateX(aPosition, uRotX), uRotY);
      vec3 n = normalize(rotateY(rotateX(aNormal, uRotX), uRotY));
      float light = max(dot(n, normalize(vec3(0.35, 0.55, 0.9))), 0.0);
      vLight = 0.34 + 0.66 * light;
      float depth = p.z + 4.2 / uZoom;
      gl_Position = vec4(p.x * 1.65 / depth, p.y * 1.65 / depth, (depth - 2.0) / 5.0, 1.0);
    }
  `;
  const fragmentSource = `
    precision mediump float;
    varying float vLight;
    void main() {
      vec3 base = vec3(0.08, 0.29, 0.86);
      vec3 edge = vec3(0.70, 0.84, 1.0);
      gl_FragColor = vec4(mix(edge, base, vLight), 1.0);
    }
  `;
  const program = gl.createProgram();
  gl.attachShader(program, compileShader(gl, gl.VERTEX_SHADER, vertexSource));
  gl.attachShader(program, compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) || "shader link failed");
  }
  return program;
}

function setViewerHint(canvas, text) {
  const hint = canvas.parentElement ? canvas.parentElement.querySelector(".stl-viewer-hint") : null;
  if (hint) hint.textContent = text;
}

function initWebglStlViewer(canvas, vertices) {
  const gl = canvas.getContext("webgl", { antialias: true }) || canvas.getContext("experimental-webgl");
  if (!gl) {
    setViewerHint(canvas, "WebGL unavailable");
    return;
  }
  const positions = new Float32Array(normalizeMesh(vertices));
  const normals = new Float32Array(computeNormals(Array.from(positions)));
  const program = createProgram(gl);
  const posBuffer = gl.createBuffer();
  const normalBuffer = gl.createBuffer();
  const aPosition = gl.getAttribLocation(program, "aPosition");
  const aNormal = gl.getAttribLocation(program, "aNormal");
  const uRotX = gl.getUniformLocation(program, "uRotX");
  const uRotY = gl.getUniformLocation(program, "uRotY");
  const uZoom = gl.getUniformLocation(program, "uZoom");
  let rotX = -0.55;
  let rotY = 0.72;
  let zoom = 1.0;
  let dragging = false;
  let lastX = 0;
  let lastY = 0;

  function resize() {
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(320, Math.floor(canvas.clientWidth * ratio));
    const height = Math.max(220, Math.floor(canvas.clientHeight * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  function render() {
    resize();
    gl.clearColor(0.965, 0.98, 1.0, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.useProgram(program);
    gl.uniform1f(uRotX, rotX);
    gl.uniform1f(uRotY, rotY);
    gl.uniform1f(uZoom, zoom);
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(aPosition);
    gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, normalBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, normals, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(aNormal);
    gl.vertexAttribPointer(aNormal, 3, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLES, 0, positions.length / 3);
  }

  canvas.addEventListener("pointerdown", (event) => {
    dragging = true;
    lastX = event.clientX;
    lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    rotY += (event.clientX - lastX) * 0.012;
    rotX += (event.clientY - lastY) * 0.012;
    lastX = event.clientX;
    lastY = event.clientY;
    render();
  });
  canvas.addEventListener("pointerup", () => {
    dragging = false;
  });
  canvas.addEventListener("pointercancel", () => {
    dragging = false;
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom = Math.max(0.55, Math.min(2.4, zoom + (event.deltaY < 0 ? 0.08 : -0.08)));
    render();
  }, { passive: false });
  window.addEventListener("resize", render);
  setViewerHint(canvas, "drag to rotate / wheel to zoom");
  render();
}

async function loadStlViewer(canvas) {
  try {
    setViewerHint(canvas, "loading STL viewer...");
    const response = await fetch(canvas.dataset.stlUrl);
    const buffer = await response.arrayBuffer();
    const vertices = parseStlVertices(buffer);
    if (vertices.length < 9) {
      throw new Error("STL has no triangles");
    }
    initWebglStlViewer(canvas, vertices);
  } catch (err) {
    setViewerHint(canvas, `viewer failed: ${err}`);
  }
}

function initStlViewers() {
  document.querySelectorAll(".stl-viewer[data-stl-url]:not([data-stl-loaded])").forEach((canvas) => {
    canvas.dataset.stlLoaded = "1";
    loadStlViewer(canvas);
  });
}


function liveAgentById(agentId) {
  return LIVE_AGENTS.find((agent) => agent.id === agentId) || LIVE_AGENTS[1];
}

function liveAgentLabel(agentId) {
  return liveAgentById(agentId).label;
}

function evolutionTargetForAgent(agentId) {
  const clean = String(agentId || liveSelectedAgent || "orchestrator").toLowerCase();
  const promptTargets = new Set(["design", "specimen", "vision", "manipulation", "equipment", "analysis", "knowledge", "bo", "guardian"]);
  if (promptTargets.has(clean)) return { target_type: "prompt", target_id: clean };
  if (clean === "objective" || clean === "orchestrator") return { target_type: "graph", target_id: "atr_closed_loop" };
  return { target_type: "prompt", target_id: clean || "design" };
}

function evolutionObjectiveForAgent(agentId) {
  const state = liveLastSession.state || {};
  const event = selectedTimelineEvent();
  const payload = eventPayload(event);
  const trace = event ? ` trace_id=${event.trace_id || payload.trace_id || "-"}` : "";
  const agentLabel = liveAgentLabel(agentId);
  return `Improve ${agentLabel} behavior for the next ATR closed-loop run using selected Live GUI report, backend trace, and runtime events.${trace} Preserve hardware safety gates and require human approval before activation.`;
}

function evolutionLabUrl(agentId = liveSelectedAgent) {
  const state = liveLastSession.state || {};
  const target = evolutionTargetForAgent(agentId);
  const params = new URLSearchParams({
    target_type: target.target_type,
    target_id: target.target_id,
    agent_id: agentId || liveSelectedAgent,
    objective: evolutionObjectiveForAgent(agentId || liveSelectedAgent),
    source: "live_gui",
  });
  if (state.run_id) params.set("run_id", state.run_id);
  if (liveSelectedEventKey) params.set("event_key", liveSelectedEventKey);
  return `/evolution-lab?${params.toString()}`;
}

function openEvolutionLab(agentId = liveSelectedAgent) {
  const url = evolutionLabUrl(agentId);
  window.open(url, "_blank", "noopener");
  setChatStatus("EVOLUTION", "idle");
}

function agentIdFromStage(stage) {
  const clean = String(stage || "").toLowerCase();
  const direct = LIVE_AGENTS.find((agent) => agent.stage === clean || agent.id === clean);
  return direct ? direct.id : clean === "complete" || clean === "error" ? "guardian" : "orchestrator";
}

function agentIdFromRole(role) {
  const clean = String(role || "").toLowerCase();
  const roleMap = {
    orchestrator: "orchestrator",
    design_ai: "design",
    specimen_ai: "specimen",
    printer_ai: "specimen",
    vision_ai: "vision",
    manipulation_ai: "manipulation",
    equipment_ai: "equipment",
    analysis_ai: "analysis",
    knowledge_ai: "knowledge",
    bo_ai: "bo",
    guardian: "guardian",
  };
  return roleMap[clean] || "orchestrator";
}

function agentIdFromFreeText(value) {
  const text = String(value || "").toLowerCase();
  const matchers = [
    ["specimen", /specimen|printer|prusa|3dp|making/],
    ["manipulation", /manipulation|lerobot|robot|rollout/],
    ["equipment", /equipment|utm|pyautogui|windows/],
    ["analysis", /analysis|cae|fem|utm|contour/],
    ["knowledge", /knowledge|memory|report/],
    ["guardian", /guardian|approval|safety|gate/],
    ["design", /design|tpms|gyroid|lattice/],
    ["vision", /vision|camera|capture/],
    ["bo", /\bbo\b|bayesian|acquisition/],
  ];
  const hit = matchers.find(([, pattern]) => pattern.test(text));
  return hit ? hit[0] : "orchestrator";
}

function agentIdFromMessage(msg) {
  if (!msg || typeof msg !== "object") return "orchestrator";
  if (msg.role && msg.role !== "system") return agentIdFromRole(msg.role);
  const content = String(msg.content || "");
  const handoff = content.match(/to=([A-Za-z0-9_]+)/i) || content.match(/agent=([A-Za-z0-9_]+)/i);
  return handoff ? agentIdFromFreeText(handoff[1]) : agentIdFromFreeText(content);
}

function agentIdFromEvent(event) {
  const payload = event && typeof event.payload === "object" ? event.payload : {};
  const candidates = [
    payload.agent_id,
    payload.agent,
    payload.selected_agent,
    payload.selected_agent_id,
    event.agent_id,
    event.agent,
    payload.module_id,
    event.module_id,
    payload.node_id,
    event.node_id,
    payload.stage,
    event.timestamp_stage,
    payload.device,
    payload.tool,
    payload.failure_code,
  ];
  for (const candidate of candidates) {
    const value = String(candidate || "");
    if (!value) continue;
    const direct = agentIdFromStage(value);
    if ((direct !== "orchestrator" || value.toLowerCase() === "orchestrator") && knownLiveAgent(direct)) return direct;
    const inferred = agentIdFromFreeText(value);
    if (inferred !== "orchestrator" && knownLiveAgent(inferred)) return inferred;
  }
  const haystack = `${event.event_type || event.type || ""} ${event.message || ""} ${event.status || ""} ${JSON.stringify(payload)}`;
  const inferred = agentIdFromFreeText(haystack);
  return knownLiveAgent(inferred) ? inferred : "orchestrator";
}

function selectedMessages() {
  return planningMessagesCache.filter((msg) => agentIdFromMessage(msg) === liveSelectedAgent);
}

function selectedEvents() {
  const events = liveRunEvents.length ? liveRunEvents : liveRecentEvents;
  return events.filter((event) => agentIdFromEvent(event) === liveSelectedAgent);
}

function formatTime(value) {
  const text = String(value || "");
  if (!text) return "-";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function compactText(value, limit = 460) {
  const text = normalizeDisplayText(value).trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function compactRunId(value) {
  const text = String(value || "").trim();
  if (!text) return "-";
  if (text.length <= 18) return text;
  return `${text.slice(0, 4)}…${text.slice(-7)}`;
}

function liveAgentShort(agentId) {
  const agent = LIVE_AGENTS.find((item) => item.id === agentId || item.stage === agentId);
  return agent ? agent.short : compactText(agentId || "-", 8);
}

function setCompactTextWithTitle(element, text, title) {
  if (!element) return;
  element.textContent = text;
  element.title = title || text;
}

function liveTokenCount(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.round(number) : 0;
}

function liveTokenUsageFromObject(value) {
  if (!value || typeof value !== "object") return { prompt: 0, completion: 0, total: 0 };
  const usage = value.token_usage && typeof value.token_usage === "object" ? value.token_usage : value.usage && typeof value.usage === "object" ? value.usage : value;
  const prompt = liveTokenCount(usage.prompt_tokens || usage.input_tokens || usage.prompt_eval_count);
  const completion = liveTokenCount(usage.completion_tokens || usage.output_tokens || usage.eval_count);
  const total = liveTokenCount(usage.total_tokens) || prompt + completion;
  return { prompt, completion, total };
}

function addLiveTokenUsage(acc, usage) {
  if (!usage || !usage.total) return acc;
  acc.prompt += usage.prompt || 0;
  acc.completion += usage.completion || 0;
  acc.total += usage.total || 0;
  acc.calls += 1;
  return acc;
}

function compactTokenCount(value) {
  const number = liveTokenCount(value);
  if (!number) return "-";
  if (number >= 1000000) return `${(number / 1000000).toFixed(number >= 10000000 ? 0 : 1)}M`;
  if (number >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}k`;
  return String(number);
}

function collectLiveTokenUsage(session = liveLastSession) {
  const acc = { prompt: 0, completion: 0, total: 0, calls: 0 };
  const messages = Array.isArray(session && session.messages) ? session.messages : planningMessagesCache;
  messages.forEach((msg) => addLiveTokenUsage(acc, liveTokenUsageFromObject(msg)));
  return acc;
}

function updateLiveTokenChip(session = liveLastSession) {
  const usage = collectLiveTokenUsage(session);
  if (!usage.total) {
    setCompactTextWithTitle(liveTokenChip, "Tok -", "No token usage recorded for this Live GUI session yet.");
    return;
  }
  setCompactTextWithTitle(
    liveTokenChip,
    `Tok ${compactTokenCount(usage.total)}`,
    `LLM token usage: total=${usage.total}, prompt=${usage.prompt}, completion=${usage.completion}, calls=${usage.calls}`
  );
}

function messageCountsByAgent(messages) {
  const counts = Object.fromEntries(LIVE_AGENTS.map((agent) => [agent.id, 0]));
  for (const msg of messages || []) {
    const agentId = agentIdFromMessage(msg);
    counts[agentId] = (counts[agentId] || 0) + 1;
  }
  return counts;
}

function liveNotificationCountsByAgent(session = liveLastSession) {
  const counts = messageCountsByAgent((session && session.messages) || planningMessagesCache || []);
  const seen = new Set();
  const eventSources = [];
  if (Array.isArray(liveRunEvents)) eventSources.push(...liveRunEvents);
  if (Array.isArray(liveRecentEvents)) eventSources.push(...liveRecentEvents);
  eventSources.forEach((event, index) => {
    const payload = eventPayload(event);
    const eventKey = String(event.event_id || event.id || payload.event_id || `${event.event_type || event.type || "event"}:${event.ts || event.timestamp || index}`);
    if (seen.has(eventKey)) return;
    seen.add(eventKey);
    const agentId = eventAgentId(event);
    counts[agentId] = (counts[agentId] || 0) + 1;
  });
  for (const approval of liveApprovals.pending || []) {
    const agentId = agentIdFromFreeText(`${approval.stage || ""} ${approval.title || ""} ${approval.reason || ""}`);
    counts[agentId] = (counts[agentId] || 0) + 1;
  }
  return counts;
}

function markLiveAgentRead(agentId = liveSelectedAgent, session = liveLastSession) {
  const safeAgent = knownLiveAgent(agentId) ? agentId : liveSelectedAgent;
  const counts = liveNotificationCountsByAgent(session);
  liveReadMarkers[safeAgent] = counts[safeAgent] || 0;
}

function eventStatusForAgent(agentId, state, running) {
  const events = liveRunEvents.length ? liveRunEvents : liveRecentEvents;
  const agentEvents = events.filter((event) => agentIdFromEvent(event) === agentId);
  const hasError = agentEvents.some((event) => String(event.level || event.severity || "").toLowerCase() === "error" || String(event.status || "").toLowerCase() === "failed");
  if (hasError) return "error";
  const pendingApproval = (liveApprovals.pending || []).some((item) => agentIdFromFreeText(`${item.stage || ""} ${item.title || ""} ${item.reason || ""}`) === agentId);
  if (pendingApproval) return "waiting";
  const activeAgent = agentIdFromStage(state.stage || "");
  if (running && activeAgent === agentId) return "running";
  const agentMessages = planningMessagesCache.filter((msg) => agentIdFromMessage(msg) === agentId);
  if (agentEvents.length || agentMessages.length) return "done";
  return "idle";
}

function liveAgentIconHtml(agent) {
  const fallback = escapeHtml(agent.icon || agent.short || "?");
  if (!agent.iconPath) return fallback;
  return `<img src="${escapeHtml(agent.iconPath)}" alt="" aria-hidden="true" loading="lazy" onerror="this.replaceWith(document.createTextNode('${fallback}'))">`;
}

function renderAgentBinder(session) {
  if (!liveAgentBinderList) return;
  const snapshot = liveLastSnapshot || {};
  const state = session.state || snapshot.state || {};
  const running = liveRunningFlag(session, snapshot, state);
  const counts = liveNotificationCountsByAgent(session);
  if (liveChatTarget) {
    const current = validLiveChatTarget(liveChatTarget.value) ? liveChatTarget.value : "selected_agent";
    const specificOptions = LIVE_AGENTS
      .filter((agent) => agent.id !== "objective")
      .map((agent) => `<option value="${agent.id}">${escapeHtml(agent.label)}</option>`)
      .join("");
    liveChatTarget.innerHTML = `
      <option value="current_agent">Current Agent</option>
      <option value="selected_agent">Selected Agent</option>
      <optgroup label="Specific Agent">${specificOptions}</optgroup>
    `;
    liveChatTarget.value = validLiveChatTarget(current) ? current : "selected_agent";
  }
  liveAgentBinderList.innerHTML = LIVE_AGENTS.map((agent) => {
    const status = eventStatusForAgent(agent.id, state, running);
    const count = counts[agent.id] || 0;
    const unread = Math.max(0, count - (liveReadMarkers[agent.id] || 0));
    return `
      <button class="binder-tab ${agent.id === liveSelectedAgent ? "active" : ""} status-${status}" data-agent-id="${agent.id}" title="${escapeHtml(`${agent.label} · click report · double-click backend · Ctrl/Cmd-click pin`)}">
        <span class="binder-icon">${liveAgentIconHtml(agent)}</span>
        <span class="binder-short">${escapeHtml(agent.short)}</span>
        <span class="binder-state-dot" aria-label="${status}"></span>
        ${unread ? `<span class="binder-unread">${unread > 9 ? "9+" : unread}</span>` : ""}
      </button>
    `;
  }).join("");
}

function liveCenterRenderKey(session = liveLastSession) {
  const snapshot = liveLastSnapshot || {};
  const state = session?.state || snapshot.state || {};
  const runId = state.run_id || liveCurrentRunId() || "none";
  const stage = state.stage || "idle";
  const messageCount = Array.isArray(session?.messages) ? session.messages.length : planningMessagesCache.length;
  const approvalCount = (liveApprovals.pending || []).length + (liveApprovals.resolved || []).length;
  return [runId, stage, liveSelectedAgent, liveRunEvents.length, liveRecentEvents.length, liveRunArtifacts.length, messageCount, approvalCount].join("|");
}

function renderActiveLiveCenterPanel(session = liveLastSession, options = {}) {
  if (!session) return;
  const key = liveCenterRenderKey(session);
  if (!options.force && liveCenterRenderKeys.get(liveCurrentView) === key) return;
  if (liveCurrentView === "report") renderReportPanel(session);
  else if (liveCurrentView === "backend") renderBackendPanel(session);
  else if (liveCurrentView === "graph") renderGraphMiniPanel(session);
  else if (liveCurrentView === "artifacts") renderArtifactPanel();
  else if (liveCurrentView === "timeline") renderTimelinePanels();
  liveCenterRenderKeys.set(liveCurrentView, key);
}

function setLiveView(view, options = {}) {
  liveCurrentView = LIVE_VIEW_IDS.has(view) ? view : "report";
  const panelByView = {
    report: "live-report-panel",
    backend: "live-backend-panel",
    graph: "live-graph-panel",
    artifacts: "live-artifact-panel",
    timeline: "live-timeline-detail-panel",
  };
  document.querySelectorAll(".live-center-view").forEach((panel) => panel.classList.toggle("active", panel.id === panelByView[liveCurrentView]));
  liveViewTabs.forEach((button) => button.classList.toggle("active", button.dataset.liveView === liveCurrentView));
  renderLiveChatContextStrip();
  persistLiveUiState();
  if (options.render !== false) renderActiveLiveCenterPanel(liveLastSession);
}


function reportEventLabel(event) {
  return `${formatTime(event.ts || event.timestamp)} · ${event.event_type || event.type || "event"}`;
}

function reportEventText(event, limit = 180) {
  const payload = eventPayload(event);
  const tail = event.message || event.status || payload.message || payload.status || "";
  return compactText(`${reportEventLabel(event)}${tail ? ` · ${tail}` : ""}`, limit);
}

function renderReportList(items, emptyText = "No evidence.") {
  const clean = (items || []).filter(Boolean).slice(0, 8);
  if (!clean.length) return `<p class="hint">${escapeHtml(emptyText)}</p>`;
  const rows = clean.map((item) => `    <li>${escapeHtml(item)}</li>`).join("\n");
  return `<ul class="live-report-list">\n${rows}\n  </ul>`;
}

function reportSectionKey(title) {
  return String(title || "section")
    .toLowerCase()
    .replace(/[^a-z0-9가-힣]+/g, "-")
    .replace(/^-+|-+$/g, "") || "section";
}

function selectedReportSectionText(limit = 1200) {
  const title = String(liveSelectedReportSectionTitle || "");
  if (!title || !liveReportPanel) return "";
  const sections = Array.from(liveReportPanel.querySelectorAll(".live-report-section[data-report-section-title]"));
  const section = sections.find((item) => item.dataset.reportSectionTitle === title);
  return compactText((section && section.textContent) || "", limit);
}

function selectedReportSectionLabel() {
  return liveSelectedReportSectionTitle || "Overview / Summary";
}

function selectedReportSectionPayload(limit = 1200) {
  const sectionTitle = selectedReportSectionLabel();
  return {
    selected_report_section: sectionTitle,
    selected_report_section_key: reportSectionKey(sectionTitle),
    selected_report_section_text: selectedReportSectionText(limit),
  };
}

function safeReportFilenamePart(value) {
  return String(value || "section")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "section";
}

function updateSelectedReportSectionDom() {
  if (!liveReportPanel) return;
  liveReportPanel.querySelectorAll(".live-report-section[data-report-section-title]").forEach((section) => {
    const selected = section.dataset.reportSectionTitle === liveSelectedReportSectionTitle;
    section.classList.toggle("selected", selected);
    section.setAttribute("aria-selected", selected ? "true" : "false");
  });
}

function selectLiveReportSection(title, options = {}) {
  const clean = String(title || "").trim();
  if (!clean) return;
  liveSelectedReportSectionTitle = clean;
  updateSelectedReportSectionDom();
  renderLiveChatContextStrip();
  persistLiveUiState();
  if (options.status !== false) setChatStatus(`SECTION: ${compactText(clean, 22)}`, "idle");
}

function renderReportSection(title, body, options = {}) {
  const content = String(body || `<p class="hint">No evidence.</p>`);
  const wideClass = options.wide ? " runtime-card-wide" : "";
  const sectionTitle = String(title || "Section");
  const selected = sectionTitle === liveSelectedReportSectionTitle;
  const sectionKey = reportSectionKey(sectionTitle);
  return `
    <section class="runtime-card-section live-report-section${wideClass}${selected ? " selected" : ""}" data-report-section-title="${escapeHtml(sectionTitle)}" data-report-section-key="${escapeHtml(sectionKey)}" tabindex="0" role="button" aria-selected="${selected ? "true" : "false"}" title="Select report section: ${escapeHtml(sectionTitle)}">
      <h4>${escapeHtml(title)}</h4>
      <div class="live-report-section-body">
${content}
      </div>
    </section>
  `;
}

function selectedReportModel(session) {
  const snapshot = liveLastSnapshot || {};
  const state = session.state || snapshot.state || {};
  const spec = state.current_experiment_spec || {};
  const messages = selectedMessages();
  const events = selectedEvents();
  const payloadEvents = events.map((event) => ({ event, payload: eventPayload(event) }));
  const latestMessage = messages[messages.length - 1] || null;
  const toolItems = [];
  for (const { event, payload } of payloadEvents) {
    const toolValue = backendField(payload, ["tool_calls", "tools", "tool", "tool_name", "tool_result", "tool_results"]);
    if (toolValue) toolItems.push(`${reportEventLabel(event)} · ${renderRuntimeValue(toolValue)}`);
  }
  const artifactItems = [];
  for (const msg of messages) {
    const artifacts = msg.artifacts || msg.fem_artifacts || msg.bo_result || msg.specimen || null;
    if (artifacts) artifactItems.push(`${roleLabel(msg.role)} · ${renderRuntimeValue(artifacts)}`);
  }
  for (const { event, payload } of payloadEvents) {
    const artifactValue = backendField(payload, ["artifacts", "artifact", "artifact_paths", "artifact_ids", "stl_path", "gcode_path", "report_url"]);
    if (artifactValue) artifactItems.push(`${reportEventLabel(event)} · ${renderRuntimeValue(artifactValue)}`);
  }
  const warnings = events
    .filter((event) => ["warning", "error"].includes(eventTimelineKind(event)))
    .map((event) => reportEventText(event));
  const handoffs = events
    .filter((event) => {
      const text = `${event.event_type || event.type || ""} ${event.message || ""}`.toLowerCase();
      return text.includes("handoff") || text.includes("stage_changed") || text.includes("next_stage");
    })
    .map((event) => reportEventText(event));
  const validationItems = payloadEvents
    .map(({ event, payload }) => {
      const value = backendField(payload, ["validation", "quality_check", "gate", "gate_results", "errors", "warnings", "ok", "status"]);
      return value === null || value === undefined ? "" : `${reportEventLabel(event)} · ${renderRuntimeValue(value)}`;
    })
    .filter(Boolean);
  const processItems = events.slice(-8).map((event) => reportEventText(event));
  const decisionItems = messages.slice(-6).map((msg) => `${formatTime(msg.timestamp)} · ${roleLabel(msg.role)} · ${compactText(msg.content || "", 220)}`);
  const nextAction = handoffs[handoffs.length - 1]
    || (state.stage ? `Continue from current stage '${state.stage}' after checking required approvals and failed gates.` : "Wait for the next orchestrator instruction or operator command.");
  return {
    state,
    spec,
    messages,
    events,
    latestMessage,
    toolItems,
    artifactItems,
    warnings,
    handoffs,
    validationItems,
    processItems,
    decisionItems,
    nextAction,
  };
}


function latestReportPayload(report, keys) {
  const sources = [];
  for (const msg of report.messages || []) sources.push(msg);
  for (const event of report.events || []) sources.push(eventPayload(event));
  for (let index = sources.length - 1; index >= 0; index -= 1) {
    const value = backendField(sources[index], keys);
    if (value !== null && value !== undefined && value !== "") return value;
  }
  return null;
}

function latestReportBoResult(report) {
  for (let index = (report.messages || []).length - 1; index >= 0; index -= 1) {
    const value = report.messages[index].bo_result;
    if (value) return value;
  }
  return latestReportPayload(report, ["bo_result", "bayesian_optimization", "optimization_result"]);
}

function latestReportArtifacts(report) {
  const artifacts = [];
  for (const msg of report.messages || []) {
    if (msg.artifacts) artifacts.push(msg.artifacts);
    if (msg.fem_artifacts) artifacts.push(msg.fem_artifacts);
    if (msg.specimen) artifacts.push(msg.specimen);
  }
  for (const event of report.events || []) {
    const payload = eventPayload(event);
    const value = backendField(payload, ["artifacts", "artifact", "artifact_paths", "stl_path", "gcode_path", "report_url", "preview_url"]);
    if (value) artifacts.push(value);
  }
  return artifacts;
}

function agentSpecificReportProfile(report, status, agentLabel) {
  const state = report.state || {};
  const spec = report.spec || {};
  const boResult = latestReportBoResult(report) || {};
  const boRecommendation = boResult.recommendation || boResult.selected || {};
  const artifacts = latestReportArtifacts(report);
  const latestTool = report.toolItems && report.toolItems.length ? report.toolItems[report.toolItems.length - 1] : "not recorded";
  const latestWarning = report.warnings && report.warnings.length ? report.warnings[report.warnings.length - 1] : "none recorded";
  const commonRows = [
    ["runtime_status", status],
    ["active_stage", state.stage || "-"],
    ["evidence_events", report.events.length],
    ["latest_tool", latestTool],
  ];
  const profiles = {
    objective: {
      title: "Objective Intake / Experiment Contract",
      summary: "Tracks the operator goal, required variables, and whether the experiment contract is complete enough to enter the agent loop.",
      rows: [
        ["active_goal", state.active_goal || "-"],
        ["experiment_id", state.experiment_id || "-"],
        ["mode", state.mode || "-"],
        ["missing_inputs", latestReportPayload(report, ["missing_fields", "required_inputs", "missing_inputs"]) || "none recorded"],
      ],
      checklist: ["Confirm objective", "Check required variables", "Lock trigger phrase / operator approval"],
    },
    orchestrator: {
      title: "Orchestration Plan / Handoff Control",
      summary: "Shows the active closed-loop route, missing operator inputs, and next handoff decision before downstream agents execute.",
      rows: [
        ["current_stage", state.stage || "-"],
        ["next_action", report.nextAction],
        ["handoffs", report.handoffs.length],
        ["pending_warnings", report.warnings.length],
      ],
      checklist: ["Validate objective completeness", "Select next agent", "Preserve live/test safety gates", "Ask user before running incomplete plans"],
    },
    design: {
      title: "Design Geometry / Manufacturability",
      summary: "Focuses on specimen geometry, TPMS/lattice parameters, printable bounds, and generated design artifacts.",
      rows: [
        ["geometry_type", spec.geometry_type || spec.structure_type || "-"],
        ["specimen_size_mm", spec.specimen_size_mm || spec.size_mm || "-"],
        ["cell_size_mm", spec.cell_size_mm || "-"],
        ["unit_cells", spec.unit_cells || spec.cell_num || "-"],
        ["relative_density", spec.relative_density || "-"],
        ["stl_artifacts", artifacts.length],
      ],
      checklist: ["Validate geometry parameters", "Check FDM printability", "Generate/update STL preview", "Prepare BO-controllable variables"],
    },
    specimen: {
      title: "Print Preparation / Prusa Bridge",
      summary: "Tracks slicing settings, PrusaLink/virtual bridge mode, upload/start readiness, and print safety options.",
      rows: [
        ["bridge_mode", latestReportPayload(report, ["bridge_mode", "printer_path", "mode"]) || "operator selection required if missing"],
        ["printer_profile", latestReportPayload(report, ["printer_profile", "printer_model", "profile"]) || "Prusa MK4S default"],
        ["layer_height_mm", spec.layer_height_mm || latestReportPayload(report, ["layer_height_mm"]) || "-"],
        ["gcode_path", latestReportPayload(report, ["gcode_path", "output_gcode", "gcode"]) || "-"],
        ["autoeject", latestReportPayload(report, ["autoeject", "auto_eject", "allow_ejection"]) || "configured in 3DP GUI"],
      ],
      checklist: ["Slice with current print profile", "Show PrusaSlicer settings", "Upload or virtual-bridge verify", "Report start/ready state"],
    },
    vision: {
      title: "Vision Capture / Pickup Observation",
      summary: "Summarizes camera readiness, captured observations, localization confidence, and whether the object is safe to hand off.",
      rows: [
        ["camera_status", latestReportPayload(report, ["camera_status", "camera", "capture_status"]) || "-"],
        ["observation", latestReportPayload(report, ["observation", "detection", "vision_result"]) || "-"],
        ["confidence", latestReportPayload(report, ["confidence", "score", "detection_confidence"]) || "-"],
        ["artifacts", artifacts.length],
      ],
      checklist: ["Confirm camera stream", "Detect printed specimen", "Estimate pickup pose", "Gate manipulation handoff"],
    },
    manipulation: {
      title: "Robot Policy / Transfer Execution",
      summary: "Shows robot profile, policy path, rollout state, and transfer completion evidence for 3DP-to-UTM movement.",
      rows: [
        ["robot_profile", latestReportPayload(report, ["robot_profile", "profile_id", "robot_id"]) || "-"],
        ["policy_path", latestReportPayload(report, ["policy_path", "checkpoint_path", "policy_repo_id"]) || "-"],
        ["rollout_status", latestReportPayload(report, ["rollout_status", "status", "session_status"]) || "-"],
        ["safety_limit", latestReportPayload(report, ["max_relative_target", "speed_limit", "action_clamp"]) || "-"],
      ],
      checklist: ["Resolve robot/camera ports", "Start policy rollout", "Monitor safe motion", "Confirm placement before UTM"],
    },
    equipment: {
      title: "Lab Equipment / Bridge Commands",
      summary: "Collects UTM, printer, Windows PyAutoGUI bridge, and device command status in one equipment-control report.",
      rows: [
        ["device", latestReportPayload(report, ["device", "equipment", "tool"]) || "-"],
        ["bridge", latestReportPayload(report, ["bridge", "bridge_name", "connection", "host"]) || "-"],
        ["command_status", latestReportPayload(report, ["command_status", "status", "result"]) || "-"],
        ["safety_state", latestReportPayload(report, ["safety_state", "gate", "allow_start_print", "allow_ejection"]) || "-"],
      ],
      checklist: ["Check bridge health", "Issue device command", "Log response", "Block unsafe equipment state"],
    },
    analysis: {
      title: "UTM / FEM / Objective Evaluation",
      summary: "Highlights measured or simulated response, contour artifacts, objective score, and whether the result is usable for BO.",
      rows: [
        ["objective_score", latestReportPayload(report, ["objective_score", "score", "utility"]) || "-"],
        ["utm_result", latestReportPayload(report, ["utm_result", "force_displacement", "stress_strain"]) || "-"],
        ["fem_artifacts", latestReportPayload(report, ["fem_artifacts", "contour_url", "cae_report"]) || "-"],
        ["validation", report.validationItems.length],
      ],
      checklist: ["Load UTM/FEM data", "Compute metrics", "Generate contour/evidence", "Package objective for knowledge/BO"],
    },
    knowledge: {
      title: "Knowledge Memory / Evidence Update",
      summary: "Shows what was written to short-term/long-term memory and which evidence should inform the next optimization step.",
      rows: [
        ["memory_update", latestReportPayload(report, ["memory_update", "memory", "knowledge_entry"]) || "-"],
        ["retrieval", latestReportPayload(report, ["retrieval", "query", "similar_cases"]) || "-"],
        ["evidence_count", report.events.length + report.messages.length],
        ["handoff_to_bo", report.handoffs.length ? "ready" : "not recorded"],
      ],
      checklist: ["Summarize experiment evidence", "Update memory", "Retrieve comparable cases", "Pass structured data to BO"],
    },
    bo: {
      title: "Bayesian Optimization / Candidate Selection",
      summary: "Shows the surrogate/acquisition state, evaluated points, and the next candidate proposed for the closed loop.",
      rows: [
        ["strategy", boResult.strategy || "-"],
        ["acquisition", boResult.acquisition || latestReportPayload(report, ["acquisition", "acquisition_function"]) || "-"],
        ["budget", boResult.budget || "-"],
        ["recommended_candidate", boRecommendation.candidate_id || boRecommendation.id || "-"],
        ["objective_score", boRecommendation.objective_score || boRecommendation.score || "-"],
      ],
      checklist: ["Update surrogate", "Plot acquisition trace", "Select next candidate", "Record benchmark/evidence"],
    },
    guardian: {
      title: "Safety Gate / Continue-Stop Decision",
      summary: "Summarizes approval state, recent warnings/errors, and whether the autonomous loop may continue, stop, or recover.",
      rows: [
        ["warnings", report.warnings.length],
        ["latest_warning", latestWarning],
        ["approval_state", latestReportPayload(report, ["approval", "approval_status", "requires_human_approval", "status"]) || "-"],
        ["decision", latestReportPayload(report, ["guardian_decision", "decision", "next_stage"]) || report.nextAction],
      ],
      checklist: ["Review safety gates", "Check device faults", "Require human approval when needed", "Decide continue/stop/error"],
    },
  };
  const profile = profiles[liveSelectedAgent] || {
    title: `${agentLabel} Runtime Role`,
    summary: "Summarizes role-specific runtime evidence for the selected agent.",
    rows: commonRows,
    checklist: ["Review latest messages", "Open backend trace if unclear", "Confirm next handoff"],
  };
  return {
    ...profile,
    rows: [...commonRows, ...(profile.rows || [])],
  };
}

function renderAgentSpecificReportSection(report, status, agentLabel) {
  const profile = agentSpecificReportProfile(report, status, agentLabel);
  const rows = runtimeRows(profile.rows || []);
  const checklist = renderReportList(profile.checklist || [], "No role-specific checklist recorded.");
  return `
    <section class="runtime-card-section live-report-section live-agent-specific-report">
      <h4>${escapeHtml(profile.title)}</h4>
      <p class="live-agent-specific-summary">${escapeHtml(profile.summary || "")}</p>
      ${rows}
      <div class="live-agent-specific-checklist">${checklist}</div>
    </section>
  `;
}

function liveCurrentRunId() {
  const state = (liveLastSession && liveLastSession.state) || (liveLastSnapshot && liveLastSnapshot.state) || {};
  return String(state.run_id || "");
}

function ensureOperatorReportStateRun(runId = liveCurrentRunId()) {
  const safeRunId = String(runId || "");
  if (safeRunId && safeRunId !== liveOperatorReportStateRunId) {
    livePinnedFindings = [];
    liveReviewedAgents = {};
    liveOperatorReportStateRunId = safeRunId;
  } else if (!liveOperatorReportStateRunId && safeRunId) {
    liveOperatorReportStateRunId = safeRunId;
  }
}

function runtimeEventTimestamp(event) {
  const payload = eventPayload(event);
  return String(payload.timestamp || payload.ts || event.ts || event.timestamp || event.created_at || new Date().toISOString());
}

function eventAgentId(event) {
  return agentIdFromEvent(event);
}

function normalizePinnedFindingFromEvent(event, runId) {
  const payload = eventPayload(event);
  const agentId = eventAgentId(event);
  const finding = payload.pinned_finding || payload.finding || {};
  const timestamp = String(finding.pinned_at || payload.pinned_at || runtimeEventTimestamp(event));
  return {
    agent_id: agentId,
    label: finding.label || payload.selected_agent_label || liveAgentLabel(agentId),
    pinned_at: timestamp,
    text: compactText(finding.text || payload.finding_text || event.message || "Operator pinned this report.", 320),
    run_id: String(finding.run_id || payload.run_id || runId || ""),
    trace_id: finding.trace_id || payload.trace_id || event.trace_id || "",
    event_key: finding.event_key || payload.event_key || "",
    source_event_id: event.event_id || event.id || "",
  };
}

function syncOperatorReportStateFromEvents(options = {}) {
  const runId = liveCurrentRunId();
  ensureOperatorReportStateRun(runId);
  const preserveLocal = options.preserveLocal !== false;
  const pinnedByAgent = new Map();
  const reviewedFromEvents = {};
  for (const event of liveRunEvents || []) {
    const eventType = String(event.event_type || event.type || "");
    if (!eventType.startsWith("operator.report.") && !eventType.startsWith("operator.binder.")) continue;
    const agentId = eventAgentId(event);
    if (eventType === "operator.report.pinned" || eventType === "operator.binder.report_pinned") {
      pinnedByAgent.set(agentId, normalizePinnedFindingFromEvent(event, runId));
    } else if (eventType === "operator.report.reviewed") {
      reviewedFromEvents[agentId] = runtimeEventTimestamp(event);
    }
  }
  const mergedPins = [...pinnedByAgent.values()];
  if (preserveLocal) {
    for (const finding of livePinnedFindings || []) {
      const agentId = finding.agent_id || "";
      const sameRun = !finding.run_id || !runId || finding.run_id === runId;
      if (agentId && sameRun && !pinnedByAgent.has(agentId)) mergedPins.push(finding);
    }
  }
  livePinnedFindings = mergedPins
    .sort((left, right) => Date.parse(right.pinned_at || 0) - Date.parse(left.pinned_at || 0))
    .slice(0, 12);
  const nextReviewed = {};
  if (preserveLocal) {
    for (const [agentId, reviewedAt] of Object.entries(liveReviewedAgents || {})) {
      if (knownLiveAgent(agentId)) nextReviewed[agentId] = reviewedAt;
    }
  }
  for (const [agentId, reviewedAt] of Object.entries(reviewedFromEvents)) {
    nextReviewed[agentId] = reviewedAt;
  }
  liveReviewedAgents = nextReviewed;
}

function selectedAgentReportText(session) {
  const report = selectedReportModel(session);
  const state = report.state;
  const spec = report.spec;
  const section = (title, rows) => [title, ...(rows.length ? rows.map((item) => `- ${normalizeDisplayText(item)}`) : ["- No evidence recorded."]), ""].join("\n");
  const running = liveRunningFlag(session, liveLastSnapshot || {}, state);
  const profile = agentSpecificReportProfile(report, eventStatusForAgent(liveSelectedAgent, state, running), liveAgentLabel(liveSelectedAgent));
  const lines = [
    `${liveAgentLabel(liveSelectedAgent)} Report`,
    `run_id: ${state.run_id || "-"}`,
    `stage: ${state.stage || "-"}`,
    `mode: ${state.mode || "-"}`,
    `specimen_id: ${spec.specimen_id || "-"}`,
    `geometry_type: ${spec.geometry_type || "-"}`,
    "",
    section(`1. ${profile.title}`, [profile.summary, ...(profile.rows || []).map(([key, value]) => `${key}: ${renderRuntimeValue(value)}`), ...(profile.checklist || []).map((item) => `check: ${item}`)]),
    section("2. Overview", [`status=${eventStatusForAgent(liveSelectedAgent, state, running)}`, `messages=${report.messages.length}`, `events=${report.events.length}`]),
    section("3. Received Inputs", Object.entries(spec).map(([key, value]) => `${key}: ${renderRuntimeValue(value)}`)),
    section("4. Key Decisions", report.decisionItems),
    section("5. Process Steps", report.processItems),
    section("6. Tool Calls Summary", report.toolItems),
    section("7. Artifacts", report.artifactItems),
    section("8. Validation / Quality Check", report.validationItems),
    section("9. Warnings", report.warnings),
    section("10. Handoff", report.handoffs),
    section("11. Next Action", [report.nextAction]),
  ];
  return lines.join("\n");
}

function downloadTextFile(filename, text) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 300);
}

function selectedReportSectionExportText(session) {
  const state = (session && session.state) || {};
  const sectionTitle = selectedReportSectionLabel();
  const sectionText = selectedReportSectionText(5000) || selectedAgentReportText(session || liveLastSession);
  return [
    "ATR Live GUI Report Section Export",
    `run_id: ${state.run_id || "-"}`,
    `agent: ${liveAgentLabel(liveSelectedAgent)} (${liveSelectedAgent})`,
    `view: ${liveCurrentView}`,
    `section: ${sectionTitle}`,
    `exported_at: ${new Date().toISOString()}`,
    "",
    sectionText,
  ].join("\n");
}

function exportSelectedReport() {
  const state = liveLastSession.state || {};
  const runId = state.run_id || "live-session";
  const sectionSlug = safeReportFilenamePart(selectedReportSectionLabel());
  const filename = `${runId}_${liveSelectedAgent}_${sectionSlug}_section.txt`;
  downloadTextFile(filename, selectedReportSectionExportText(liveLastSession));
  return filename;
}

function liveSelectedTraceContext() {
  const event = typeof selectedTimelineEvent === "function" ? selectedTimelineEvent() : null;
  const payload = event ? eventPayload(event) : {};
  return {
    selected_event_key: liveSelectedEventKey,
    selected_event_id: event ? (event.event_id || event.id || payload.event_id || "") : "",
    trace_id: event ? (event.trace_id || payload.trace_id || "") : "",
    event_type: event ? (event.event_type || event.type || "") : "",
  };
}

function liveViewShort(view = liveCurrentView) {
  const map = { report: "RPT", backend: "BCK", graph: "GRF", artifacts: "ART", timeline: "TLN" };
  return map[view] || String(view || "-").slice(0, 3).toUpperCase();
}

function liveModeShort(mode = "") {
  const map = { live: "LIV", test: "TST", virtual: "VRT", dry_run: "DRY" };
  const key = String(mode || "").toLowerCase();
  return map[key] || String(mode || "-").slice(0, 3).toUpperCase();
}

function liveRunningFlag(session = {}, snapshot = {}, state = {}) {
  if (typeof session.is_running === "boolean") return session.is_running;
  if (typeof snapshot.is_running === "boolean") return snapshot.is_running;
  if (typeof state.is_running === "boolean") return state.is_running;
  return false;
}

function liveChatContextSummary() {
  const session = liveLastSession || {};
  const snapshot = liveLastSnapshot || {};
  const state = session.state || snapshot.state || {};
  const event = typeof selectedTimelineEvent === "function" ? selectedTimelineEvent() : null;
  const payload = event ? eventPayload(event) : {};
  const eventAgent = event ? agentIdFromEvent(event) : "";
  const contextAgent = knownLiveAgent(eventAgent) ? eventAgent : liveSelectedAgent;
  return {
    run_id: state.run_id || "",
    mode: state.mode || "",
    is_running: liveRunningFlag(session, snapshot, state),
    active_goal: state.active_goal || "",
    stage: state.stage || "",
    selected_agent: contextAgent,
    selected_agent_label: liveAgentLabel(contextAgent),
    selected_view: liveCurrentView,
    selected_graph_node_id: liveSelectedGraphNodeId,
    selected_event_key: liveSelectedEventKey,
    selected_event_id: event ? (event.event_id || event.id || payload.event_id || "") : "",
    trace_id: event ? (event.trace_id || payload.trace_id || "") : "",
    node_id: event ? (event.node_id || payload.node_id || "") : "",
    event_type: event ? (event.event_type || event.type || "") : "",
    selected_report_section: selectedReportSectionLabel(),
    selected_report_section_text: selectedReportSectionText(700),
    chat_target: resolveLiveChatTarget(liveChatTarget ? liveChatTarget.value : "selected_agent"),
    chat_target_mode: liveChatTarget && validLiveChatTarget(liveChatTarget.value) ? liveChatTarget.value : "selected_agent",
    chat_mode: liveChatMode ? liveChatMode.value : "ask",
  };
}

function renderLiveChatContextStrip() {
  if (!liveChatContextStrip) return;
  const ctx = liveChatContextSummary();
  const anchor = ctx.trace_id || ctx.selected_event_id || ctx.selected_graph_node_id || compactRunId(ctx.run_id || "-");
  const text = [
    "CTX",
    `A:${liveAgentShort(ctx.selected_agent)}`,
    `C:${liveAgentShort(ctx.chat_target)}`,
    `R:${liveModeShort(ctx.mode)}:${ctx.is_running ? "ON" : "IDLE"}`,
    `V:${liveViewShort(ctx.selected_view)}`,
    `M:${String(ctx.chat_mode || "ask").slice(0, 3).toUpperCase()}`,
    `Ref:${compactText(anchor || "-", 14)}`,
  ].join(" · ");
  const title = [
    `agent=${ctx.selected_agent_label || ctx.selected_agent || "-"}`,
    `view=${ctx.selected_view || "-"}`,
    `chat_target=${ctx.chat_target || "-"}`,
    `chat_target_mode=${ctx.chat_target_mode || "-"}`,
    `chat_mode=${ctx.chat_mode || "-"}`,
    `mode=${ctx.mode || "-"}`,
    `running=${ctx.is_running ? "true" : "false"}`,
    `goal=${ctx.active_goal || "-"}`,
    `run=${ctx.run_id || "-"}`,
    `stage=${ctx.stage || "-"}`,
    `node=${ctx.node_id || ctx.selected_graph_node_id || "-"}`,
    `trace=${ctx.trace_id || "-"}`,
    `event=${ctx.selected_event_id || "-"}`,
    `report_section=${ctx.selected_report_section || "-"}`,
  ].join(" | ");
  setCompactTextWithTitle(liveChatContextStrip, text, title);
}

function liveFocusChip(label, value, title = "", tone = "") {
  const safeTone = tone ? ` ${escapeHtml(tone)}` : "";
  return `<span class="live-focus-chip${safeTone}" title="${escapeHtml(title || `${label}: ${value}`)}"><em>${escapeHtml(label)}</em><strong>${escapeHtml(value || "-")}</strong></span>`;
}

function renderLiveFocusStrip() {
  if (!liveFocusStrip) return;
  const ctx = liveChatContextSummary();
  const anchor = ctx.trace_id || ctx.selected_event_id || ctx.selected_graph_node_id || compactRunId(ctx.run_id || "-");
  const runState = `${liveModeShort(ctx.mode)}:${ctx.is_running ? "ON" : "IDLE"}`;
  const focusTitle = [
    `agent=${ctx.selected_agent_label || ctx.selected_agent || "-"}`,
    `view=${ctx.selected_view || "-"}`,
    `target=${ctx.chat_target || "-"}`,
    `mode=${ctx.mode || "-"}`,
    `running=${ctx.is_running ? "true" : "false"}`,
    `run=${ctx.run_id || "-"}`,
    `stage=${ctx.stage || "-"}`,
    `reference=${anchor || "-"}`,
    `report_section=${ctx.selected_report_section || "-"}`,
  ].join(" | ");
  liveFocusStrip.title = focusTitle;
  liveFocusStrip.innerHTML = [
    liveFocusChip("Agent", liveAgentShort(ctx.selected_agent), ctx.selected_agent_label || ctx.selected_agent, "primary"),
    liveFocusChip("View", liveViewShort(ctx.selected_view), `Current center view: ${ctx.selected_view || "-"}`),
    liveFocusChip("Target", liveAgentShort(ctx.chat_target), `Runtime Chat target: ${ctx.chat_target || "-"}`),
    liveFocusChip("Run", runState, `mode=${ctx.mode || "-"}; running=${ctx.is_running ? "true" : "false"}`, ctx.is_running ? "running" : "idle"),
    liveFocusChip("Stage", compactText(ctx.stage || "-", 14), `Current runtime stage: ${ctx.stage || "-"}`),
    liveFocusChip("Ref", compactText(anchor || "-", 18), `Selected trace/event/node/run reference: ${anchor || "-"}`),
    liveFocusChip("Section", compactText(ctx.selected_report_section || "-", 24), `Selected report section: ${ctx.selected_report_section || "-"}`),
  ].join("");
}


async function recordLiveOperatorEvent(action, message, payload = {}, namespace = "operator.report") {
  const snapshot = liveLastSnapshot || {};
  const state = liveLastSession.state || snapshot.state || {};
  const trace = liveSelectedTraceContext();
  const nodeId = graphNodeIdForAgent(liveSelectedAgent) || liveSelectedAgent;
  const safeNamespace = String(namespace || "operator.report").replace(/[^a-zA-Z0-9_.:-]+/g, "_") || "operator.report";
  const body = {
    event_type: `${safeNamespace}.${action}`,
    message: message || `Live GUI report action: ${action}`,
    action,
    agent_id: liveSelectedAgent,
    node_id: nodeId,
    trace_id: trace.trace_id,
    event_key: trace.selected_event_key,
    level: "INFO",
    payload: {
      ...selectedReportSectionPayload(900),
      ...payload,
      selected_agent: liveSelectedAgent,
      selected_agent_label: liveAgentLabel(liveSelectedAgent),
      selected_view: liveCurrentView,
      selected_graph_node_id: liveSelectedGraphNodeId,
      run_id: state.run_id || "",
      mode: state.mode || "",
      stage: state.stage || "",
      ...trace,
    },
  };
  const endpoint = state.run_id
    ? `/api/runs/${encodeURIComponent(state.run_id)}/operator-events`
    : "/api/runtime/operator-event";
  const requestOptions = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  let data;
  try {
    data = await fetchJsonOrThrow(endpoint, requestOptions);
  } catch (err) {
    if (!state.run_id) throw err;
    data = await fetchJsonOrThrow("/api/runtime/operator-event", requestOptions);
  }
  if (data.event) {
    liveRunEvents.push(data.event);
    liveRunEvents = liveRunEvents.slice(-160);
    syncOperatorReportStateFromEvents({ preserveLocal: true });
    renderLiveRuntime(liveLastSession);
  }
  return data;
}

async function recordLiveIntentEvent(eventType, action, message, payload = {}) {
  const snapshot = liveLastSnapshot || {};
  const state = liveLastSession.state || snapshot.state || {};
  const trace = liveSelectedTraceContext();
  const nodeId = graphNodeIdForAgent(liveSelectedAgent) || liveSelectedAgent;
  const cleanEventType = String(eventType || "runtime_command_requested").replace(/[^a-zA-Z0-9_.:-]+/g, "_") || "runtime_command_requested";
  const body = {
    event_type: cleanEventType,
    message: message || `Live GUI intent recorded: ${action || cleanEventType}`,
    action: action || cleanEventType,
    agent_id: liveSelectedAgent,
    node_id: nodeId,
    trace_id: trace.trace_id,
    event_key: trace.selected_event_key,
    level: "INFO",
    payload: {
      ...selectedReportSectionPayload(900),
      intent_event_type: cleanEventType,
      selected_agent: liveSelectedAgent,
      selected_agent_label: liveAgentLabel(liveSelectedAgent),
      selected_view: liveCurrentView,
      selected_graph_node_id: liveSelectedGraphNodeId,
      run_id: state.run_id || "",
      mode: state.mode || "",
      runtime_mode: state.mode || "",
      stage: state.stage || "",
      ...trace,
      ...payload,
    },
  };
  const endpoint = state.run_id
    ? `/api/runs/${encodeURIComponent(state.run_id)}/operator-events`
    : "/api/runtime/operator-event";
  const requestOptions = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  let data;
  try {
    data = await fetchJsonOrThrow(endpoint, requestOptions);
  } catch (err) {
    if (!state.run_id) throw err;
    data = await fetchJsonOrThrow("/api/runtime/operator-event", requestOptions);
  }
  if (data.event) {
    liveRunEvents.push(data.event);
    liveRunEvents = liveRunEvents.slice(-160);
    renderLiveRuntime(liveLastSession);
  }
  return data;
}

function pinSelectedFinding() {
  const messages = selectedMessages();
  const events = selectedEvents();
  const latest = messages[messages.length - 1] || null;
  const fallbackEvent = events[events.length - 1] || null;
  const trace = liveSelectedTraceContext();
  const section = selectedReportSectionPayload(360);
  const sectionText = section.selected_report_section_text || "";
  const fallbackText = latest ? compactText(latest.content || "", 320) : compactText((fallbackEvent && fallbackEvent.message) || "No report message yet.", 320);
  const finding = {
    agent_id: liveSelectedAgent,
    label: liveAgentLabel(liveSelectedAgent),
    pinned_at: new Date().toISOString(),
    text: sectionText || fallbackText,
    selected_report_section: section.selected_report_section,
    selected_report_section_key: section.selected_report_section_key,
    run_id: liveCurrentRunId(),
    trace_id: trace.trace_id,
    event_key: trace.selected_event_key,
  };
  livePinnedFindings = [finding, ...livePinnedFindings.filter((item) => item.agent_id !== liveSelectedAgent)].slice(0, 12);
  renderLiveRuntime(liveLastSession);
  return finding;
}

async function focusPinnedFinding(item) {
  if (!item) return null;
  const agentId = knownLiveAgent(item.agent_id) ? item.agent_id : liveSelectedAgent;
  liveSelectedAgent = agentId;
  const sectionTitle = String(item.selected_report_section || "Overview / Summary").trim() || "Overview / Summary";
  selectLiveReportSection(sectionTitle, { status: false });
  if (item.event_key) {
    selectTimelineEventByKey(item.event_key, agentId);
  }
  setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));
  setLiveView("report");
  await recordLiveOperatorEvent(
    "pinned_focused",
    `${liveAgentLabel(liveSelectedAgent)} pinned finding focused from report.`,
    {
      source_action: "report.pinned_focus",
      target_agent: liveSelectedAgent,
      selected_report_section: sectionTitle,
      trace_id: item.trace_id || "",
      event_key: item.event_key || "",
      pinned_at: item.pinned_at || "",
    },
    "operator.report"
  );
  renderLiveRuntime(liveLastSession);
  return item;
}

function renderPinnedFindingComparison() {
  if (!livePinnedFindings.length) return "";
  const pinned = livePinnedFindings[0];
  const currentSection = selectedReportSectionLabel();
  const currentText = selectedReportSectionText(280) || compactText(selectedAgentReportText(liveLastSession || {}), 280);
  const currentStatus = `${liveAgentLabel(liveSelectedAgent)} · ${selectedAgentReviewLabel()} · ${selectedAgentPinLabel()}`;
  const pinnedStatus = `${pinned.label || liveAgentLabel(pinned.agent_id)} · ${formatTime(pinned.pinned_at || new Date().toISOString())}${pinned.selected_report_section ? ` · ${pinned.selected_report_section}` : ""}`;
  return `
    <section class="runtime-card-section runtime-card-wide live-pinned-compare">
      <div class="live-pinned-compare-head">
        <div>
          <h4>Selected vs Pinned</h4>
          <p class="hint">Compare the current report context with the latest pinned finding.</p>
        </div>
        <span class="badge idle">${escapeHtml(livePinnedFindings.length)} pinned</span>
      </div>
      <div class="live-pinned-compare-grid">
        <article class="live-pinned-compare-card current">
          <small>Current</small>
          <strong>${escapeHtml(liveAgentLabel(liveSelectedAgent))}</strong>
          <span>${escapeHtml(currentStatus)}</span>
          <p><em>${escapeHtml(currentSection)}</em></p>
          <p>${escapeHtml(currentText || "No current section content.")}</p>
        </article>
        <article class="live-pinned-compare-card pinned">
          <small>Pinned</small>
          <strong>${escapeHtml(pinned.label || liveAgentLabel(pinned.agent_id))}</strong>
          <span>${escapeHtml(pinnedStatus)}</span>
          <p><em>${escapeHtml(pinned.selected_report_section || "Overview / Summary")}</em></p>
          <p>${escapeHtml(compactText(pinned.text || "No pinned finding text.", 280))}</p>
          <button class="btn live-pinned-finding-action" data-pinned-index="0" title="Focus pinned finding" aria-label="Focus pinned finding"><span class="live-card-action-icon" aria-hidden="true">↗</span><span class="live-card-action-label">Focus Pinned</span></button>
        </article>
      </div>
    </section>
  `;
}

function renderPinnedFindings() {
  if (!livePinnedFindings.length) return "";
  return `
    <section class="runtime-card-section runtime-card-wide live-pinned-findings">
      <h4>Pinned Findings</h4>
      <div class="live-pinned-list">
        ${livePinnedFindings.map((item, index) => `
          <article class="live-pinned-finding-item" data-pinned-index="${index}">
            <strong>${escapeHtml(item.label)}</strong>
            <small>${escapeHtml(formatTime(item.pinned_at))}${item.selected_report_section ? ` · ${escapeHtml(item.selected_report_section)}` : ""}</small>
            <p>${escapeHtml(item.text)}</p>
            <button class="btn live-pinned-finding-action" data-pinned-index="${index}" title="Focus pinned finding" aria-label="Focus pinned finding"><span class="live-card-action-icon" aria-hidden="true">↗</span><span class="live-card-action-label">Focus Pinned</span></button>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function markSelectedAgentReviewed() {
  const reviewedAt = new Date().toISOString();
  liveReviewedAgents[liveSelectedAgent] = reviewedAt;
  markLiveAgentRead(liveSelectedAgent, liveLastSession);
  renderLiveRuntime(liveLastSession);
  return reviewedAt;
}

function selectedAgentReviewLabel() {
  const reviewedAt = liveReviewedAgents[liveSelectedAgent];
  return reviewedAt ? `reviewed ${formatTime(reviewedAt)}` : "unreviewed";
}

function selectedAgentPinLabel() {
  return livePinnedFindings.some((item) => item.agent_id === liveSelectedAgent) ? "pinned" : "not pinned";
}

async function runLiveReportAction(action) {
  if (action === "backend") {
    await recordLiveOperatorEvent("backend_opened", `${liveAgentLabel(liveSelectedAgent)} backend trace opened from report.`);
    setLiveView("backend");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "export") {
    const filename = exportSelectedReport();
    await recordLiveOperatorEvent("exported", `${liveAgentLabel(liveSelectedAgent)} report section exported from Live GUI.`, { export_format: "txt", export_scope: "selected_report_section", filename, ...selectedReportSectionPayload(1200) });
    return;
  }
  if (action === "pin") {
    const finding = pinSelectedFinding();
    await recordLiveOperatorEvent("pinned", `${liveAgentLabel(liveSelectedAgent)} report finding pinned.`, { pinned_finding: finding, pinned_at: finding.pinned_at });
    return;
  }
  if (action === "ask") {
    const section = selectedReportSectionLabel();
    const sectionText = selectedReportSectionText(900);
    draftRuntimeChat(`${liveAgentLabel(liveSelectedAgent)} 보고서의 [${section}] 섹션과 최근 backend trace를 기준으로 주요 판단과 다음 위험요소를 설명해줘.${sectionText ? `\n\n선택 섹션 내용:\n${sectionText}` : ""}`, "ask");
    await recordLiveOperatorEvent("ask_drafted", `${liveAgentLabel(liveSelectedAgent)} report section follow-up drafted in Runtime Chat.`, { ask_scope: "selected_report_section", ...selectedReportSectionPayload(900) });
    return;
  }
  if (action === "reviewed") {
    const reviewedAt = markSelectedAgentReviewed();
    await recordLiveOperatorEvent("reviewed", `${liveAgentLabel(liveSelectedAgent)} report marked reviewed.`, { reviewed_at: reviewedAt });
    return;
  }
  if (action === "rerun") {
    if (await blockLiveExecutionForPendingApproval("report.rerun", `${liveAgentLabel(liveSelectedAgent)} report re-run`, { source_action: "report.rerun", target_agent: liveSelectedAgent, target_node_id: graphNodeIdForAgent(liveSelectedAgent) || liveSelectedAgent })) return;
    await recordLiveOperatorEvent("rerun_requested", `${liveAgentLabel(liveSelectedAgent)} report requested a safe node re-run check.`);
    await recordLiveIntentEvent("node_rerun_requested", "rerun_from_report", `${liveAgentLabel(liveSelectedAgent)} node rerun requested from report.`, { source_action: "report.rerun", target_agent: liveSelectedAgent, target_node_id: graphNodeIdForAgent(liveSelectedAgent) || liveSelectedAgent });
    await runSelectedNodeTest(liveLastSession.state || {});
    return;
  }
  if (action === "evolve") {
    openEvolutionLab(liveSelectedAgent);
    await recordLiveOperatorEvent("evolution_opened", `${liveAgentLabel(liveSelectedAgent)} self-evolution workspace opened from report.`);
  }
}

function renderAcademicReportSections(session, report, status, agentLabel) {
  const state = report.state;
  const spec = report.spec;
  const overviewRows = runtimeRows([
    ["status", status],
    ["selected_agent", agentLabel],
    ["messages", report.messages.length],
    ["events", report.events.length],
    ["review", selectedAgentReviewLabel()],
    ["pin", selectedAgentPinLabel()],
  ]);
  const inputRows = runtimeRows([
    ["run_id", state.run_id],
    ["experiment_id", state.experiment_id],
    ["stage", state.stage],
    ["mode", state.mode],
    ["active_goal", state.active_goal],
    ["specimen_id", spec.specimen_id],
    ["geometry_type", spec.geometry_type],
    ["specimen_size_mm", spec.specimen_size_mm],
  ]);
  return `
    ${renderReportSection("Overview / Summary", overviewRows)}
    ${renderAgentSpecificReportSection(report, status, agentLabel)}
    ${renderReportSection("Received Inputs", inputRows || "<p class='hint'>No experiment spec has been produced yet.</p>")}
    ${renderReportSection("Key Decisions", renderReportList(report.decisionItems))}
    ${renderReportSection("Process Steps", renderReportList(report.processItems))}
    ${renderReportSection("Tool Calls Summary", renderReportList(report.toolItems))}
    ${renderReportSection("Artifacts", renderReportList(report.artifactItems))}
    ${renderReportSection("Validation / Quality Check", renderReportList(report.validationItems))}
    ${renderReportSection("Warnings", renderReportList(report.warnings, "No warnings/errors."))}
    ${renderReportSection("Handoff", renderReportList(report.handoffs))}
    ${renderReportSection("Next Action", renderReportList([report.nextAction]))}
  `;
}

function renderReportPanel(session) {
  if (!liveReportPanel) return;
  const report = selectedReportModel(session);
  const messages = report.messages;
  const latestMessage = report.latestMessage;
  const agentLabel = liveAgentLabel(liveSelectedAgent);
  const status = eventStatusForAgent(liveSelectedAgent, report.state, liveRunningFlag(session, liveLastSnapshot || {}, report.state));
  const profile = agentSpecificReportProfile(report, status, agentLabel);
  const messageCards = messages.slice(-4).map((msg, index) => `
    <article class="live-report-message">
      <small>${escapeHtml(formatTime(msg.timestamp))} · ${escapeHtml(roleLabel(msg.role))}${msg.model ? ` · ${escapeHtml(msg.model)}` : ""}</small>
      ${renderReasoningBlock(msg)}
      <p>${escapeHtml(compactText(msg.content || "", 720)).replaceAll("\n", "<br />")}</p>
      ${renderArtifactCard(msg)}
      ${renderFemContourCard(msg)}
      ${renderBoResultCard(msg, `report-card-${index}`)}
    </article>
  `).join("");
  liveReportPanel.innerHTML = `
    <div class="live-report-page">
      <div class="live-report-head">
        <div>
          <h3>${escapeHtml(agentLabel)} Report</h3>
          <p><span class="live-report-role-tag">${escapeHtml(profile.title)}</span>${escapeHtml(latestMessage ? ` · ${compactText(latestMessage.content, 220)}` : " · No report yet. Backend/Timeline remain available.")}</p>
        </div>
        <div class="live-report-actions" aria-label="report actions">
          <button class="btn live-report-action" data-report-action="backend" type="button" title="Open backend trace" aria-label="Open backend trace"><span class="live-report-action-icon" aria-hidden="true">{}</span><span class="live-report-action-label">BACKEND</span></button>
          <button class="btn live-report-action" data-report-action="export" type="button" title="Export selected report section" aria-label="Export selected report section"><span class="live-report-action-icon" aria-hidden="true">⇩</span><span class="live-report-action-label">Export Section</span></button>
          <button class="btn live-report-action" data-report-action="pin" type="button" title="Pin finding" aria-label="Pin finding"><span class="live-report-action-icon" aria-hidden="true">★</span><span class="live-report-action-label">Pin Finding</span></button>
          <button class="btn live-report-action" data-report-action="ask" type="button" title="Ask in Runtime Chat" aria-label="Ask in Runtime Chat"><span class="live-report-action-icon" aria-hidden="true">?</span><span class="live-report-action-label">Ask in Chat</span></button>
          <button class="btn live-report-action" data-report-action="reviewed" type="button" title="Mark reviewed" aria-label="Mark reviewed"><span class="live-report-action-icon" aria-hidden="true">✓</span><span class="live-report-action-label">Mark Reviewed</span></button>
          <button class="btn live-report-action" data-report-action="rerun" type="button" title="Re-run from here" aria-label="Re-run from here"><span class="live-report-action-icon" aria-hidden="true">↻</span><span class="live-report-action-label">Re-run From Here</span></button>
          <button class="btn live-report-action" data-report-action="evolve" type="button" title="Open Evolution Lab for this agent" aria-label="Open Evolution Lab for this agent"><span class="live-report-action-icon" aria-hidden="true">Δ</span><span class="live-report-action-label">Evolve Agent</span></button>
        </div>
      </div>
      <div class="live-report-grid live-report-academic-grid">
        ${renderAcademicReportSections(session, report, status, agentLabel)}
        ${renderPinnedFindingComparison()}
        ${renderPinnedFindings()}
        ${renderReportSection("Source Messages", messageCards || "<p class='hint'>No messages yet.</p>", { wide: true })}
      </div>
    </div>
  `;
}

function backendField(payload, keys) {
  if (!payload || typeof payload !== "object") return null;
  for (const key of keys) {
    if (payload[key] !== undefined && payload[key] !== null && payload[key] !== "") return payload[key];
  }
  return null;
}

function eventPayload(event) {
  return event && typeof event.payload === "object" ? event.payload : {};
}

function renderBackendRawSection(title, value, className = "") {
  if (value === null || value === undefined || value === "") return "";
  const printable = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return `
    <section class="live-raw-section backend-trace-section ${className}">
      <h5>${escapeHtml(title)}</h5>
      <pre>${escapeHtml(printable)}</pre>
    </section>
  `;
}

function renderBackendStructuredTrace(event) {
  const payload = eventPayload(event);
  const model = backendField(payload, ["model", "model_name", "llm_model"]) || event.model || "";
  const handler = backendField(payload, ["handler", "handler_id", "node_handler", "tool", "tool_name"]) || "";
  const prompt = backendField(payload, ["raw_prompt", "prompt", "system_prompt", "messages"]);
  const response = backendField(payload, ["raw_response", "llm_response", "response", "completion", "text"]);
  const toolCalls = backendField(payload, ["tool_calls", "tools", "tool_call", "tool_result", "tool_results"]);
  const input = backendField(payload, ["input", "input_json", "request", "state_before", "node_input"]);
  const output = backendField(payload, ["output", "output_json", "result", "state_after", "node_output"]);
  const logs = backendField(payload, ["logs", "log", "step_trace", "trace"]);
  const artifacts = backendField(payload, ["artifacts", "artifact", "artifact_paths"]);
  const error = backendField(payload, ["error", "exception", "traceback", "failure_code", "error_stack", "stack"]);
  const compileContext = {
    graph_id: event.graph_id || payload.graph_id || "atr_closed_loop",
    graph_version: event.graph_version || payload.graph_version || payload.compile_version || "not recorded",
    node_id: event.node_id || payload.node_id || "not recorded",
    module_id: event.module_id || payload.module_id || "not recorded",
    handler: handler || "not recorded",
    trace_id: event.trace_id || payload.trace_id || "not recorded",
  };
  const sections = [
    renderBackendRawSection("Graph / Compile Context", compileContext, "raw-compile-context"),
    renderBackendRawSection("Raw Prompt / Messages", prompt, "raw-prompt"),
    renderBackendRawSection("Raw LLM Response", response, "raw-response"),
    renderBackendRawSection("Tool Calls / Results", toolCalls, "raw-tools"),
    renderBackendRawSection("Node Input JSON", input, "raw-input"),
    renderBackendRawSection("Node Output JSON", output, "raw-output"),
    renderBackendRawSection("Logs / Step Trace", logs, "raw-logs"),
    renderBackendRawSection("Artifacts", artifacts, "raw-artifacts"),
    renderBackendRawSection("Error / Failure", error, "raw-error"),
  ].filter(Boolean).join("");
  return `
    <div class="live-backend-structured">
      ${runtimeRows([
        ["model", model],
        ["handler/tool", handler],
        ["node_id", event.node_id || payload.node_id],
        ["module_id", event.module_id || payload.module_id],
        ["graph_version", compileContext.graph_version],
        ["status", event.status || payload.status],
      ])}
      ${sections || "<p class='hint'>No raw I/O fields recorded. Full JSON below.</p>"}
    </div>
  `;
}

function renderBackendTraceSections(event) {
  return renderBackendStructuredTrace(event);
}


function eventStableKey(event) {
  if (!event || typeof event !== "object") return "";
  const payload = eventPayload(event);
  return String(
    event.event_id
    || event.id
    || event.trace_id
    || payload.event_id
    || payload.trace_id
    || [event.ts || event.timestamp || "", event.event_type || event.type || "", event.node_id || payload.node_id || "", event.message || ""].join("|")
  );
}

function findEventByKey(key) {
  if (!key) return null;
  return timelineSourceEvents().find((event) => eventStableKey(event) === key) || null;
}

function selectedTimelineEvent() {
  return findEventByKey(liveSelectedEventKey);
}

function eventTraceRows(event) {
  if (!event) return "";
  const payload = eventPayload(event);
  return runtimeRows([
    ["event_id", event.event_id || event.id || payload.event_id],
    ["trace_id", event.trace_id || payload.trace_id],
    ["type", event.event_type || event.type],
    ["severity", event.level || event.severity || eventTimelineKind(event)],
    ["agent", agentIdFromEvent(event)],
    ["node_id", event.node_id || payload.node_id],
    ["graph", event.graph_id || payload.graph_id],
    ["graph_version", event.graph_version || payload.graph_version],
    ["failure_code", payload.failure_code || payload.code || payload.error_code],
    ["device", payload.device],
    ["tool", payload.tool],
    ["status", event.status || payload.status],
    ["time", event.ts || event.timestamp],
  ]);
}

function renderSelectedEventCard(context = "backend") {
  const event = selectedTimelineEvent();
  if (!event) {
    return `
      <section class="runtime-card-section live-selected-event-card empty" data-selected-event="none">
        <h4>Selected Timeline Event</h4>
        <p class="hint">Click an event to inspect trace/actions.</p>
      </section>
    `;
  }
  const payload = eventPayload(event);
  const agentId = agentIdFromEvent(event);
  return `
    <section class="runtime-card-section live-selected-event-card" data-selected-event="${escapeHtml(eventStableKey(event))}" data-context="${escapeHtml(context)}">
      <div class="live-selected-event-head">
        <div>
          <h4>Selected Timeline Event</h4>
          <strong>${escapeHtml(event.event_type || event.type || "event")}</strong>
        </div>
        <span class="badge ${escapeHtml(eventTimelineKind(event))}">${escapeHtml(agentId)}</span>
      </div>
      <p>${escapeHtml(event.message || payload.message || "No event message recorded.")}</p>
      ${eventTraceRows(event)}
      <div class="button-row live-selected-event-actions">
        <button class="btn live-selected-event-action" data-event-action="open_backend" title="Open backend trace for this event" aria-label="Open backend trace for this event"><span class="live-card-action-icon" aria-hidden="true">{}</span><span class="live-card-action-label">Open Backend</span></button>
        <button class="btn live-selected-event-action" data-event-action="open_report" title="Open agent report for this event" aria-label="Open agent report for this event"><span class="live-card-action-icon" aria-hidden="true">R</span><span class="live-card-action-label">Open Report</span></button>
        <button class="btn live-selected-event-action" data-event-action="ask_chat" title="Ask Runtime Chat about this event" aria-label="Ask Runtime Chat about this event"><span class="live-card-action-icon" aria-hidden="true">?</span><span class="live-card-action-label">Ask in Chat</span></button>
        <button class="btn live-selected-event-action" data-event-action="replay_prep" title="Prepare replay or node test from this event" aria-label="Prepare replay or node test from this event"><span class="live-card-action-icon" aria-hidden="true">↻</span><span class="live-card-action-label">Replay Prep</span></button>
        <button class="btn live-selected-event-action" data-event-action="copy_trace" title="Copy selected trace JSON" aria-label="Copy selected trace JSON"><span class="live-card-action-icon" aria-hidden="true">⧉</span><span class="live-card-action-label">Copy Trace</span></button>
      </div>
    </section>
  `;
}

function renderBackendPanel(session) {
  if (!liveBackendPanel) return;
  const events = selectedEvents().slice(-30).reverse();
  const state = session.state || {};
  liveBackendPanel.innerHTML = `
    <div class="live-backend-view">
      <div class="runtime-card-section">
        <h4>Handler / Runtime Context</h4>
        ${runtimeRows([
          ["selected_agent", liveAgentLabel(liveSelectedAgent)],
          ["run_id", state.run_id],
          ["stage", state.stage],
          ["mode", state.mode],
          ["planning_session_id", session.planning_session_id],
        ])}
      </div>
      ${renderSelectedEventCard("backend")}
      <div class="live-backend-list">
        ${events.length ? events.map((event) => `
          <details class="live-backend-event">
            <summary><strong>${escapeHtml(event.event_type || event.type || "event")}</strong><span>${escapeHtml(formatTime(event.ts || event.timestamp))}</span><em>${escapeHtml(event.level || event.severity || "")}</em></summary>
            ${renderBackendTraceSections(event)}
            <details class="live-full-json"><summary>Full Event JSON</summary><pre>${escapeHtml(JSON.stringify(event, null, 2))}</pre></details>
          </details>
        `).join("") : "<p class='hint'>No backend events yet.</p>"}
      </div>
    </div>
  `;
}

function liveGraphNodeClass(node, state) {
  const activeStage = String(state.stage || "").toLowerCase();
  const nodeStage = String(node.stage || node.id || "").toLowerCase();
  const kind = String(node.kind || "agent").toLowerCase();
  const hasError = liveRunEvents.some((event) => agentIdFromEvent(event) === agentIdFromStage(nodeStage) && String(event.level || event.severity || "").toLowerCase() === "error");
  if (hasError) return "node-error";
  if (activeStage && nodeStage === activeStage) return "node-active";
  if (kind === "runtime") return "node-secondary";
  if (kind === "terminal") return "node-terminal";
  return "node-primary";
}

function graphNodePosition(node, index, total) {
  const pos = node.position || {};
  const x = Number(pos.x);
  const y = Number(pos.y);
  if (Number.isFinite(x) && Number.isFinite(y)) {
    return { left: Math.max(4, Math.min(94, x / 22)), top: Math.max(8, Math.min(88, y / 10)) };
  }
  const cols = Math.max(1, Math.ceil(Math.sqrt(total)));
  const row = Math.floor(index / cols);
  const col = index % cols;
  return { left: 10 + (col / Math.max(1, cols - 1)) * 78, top: 16 + row * 18 };
}

function renderGraphEdges(graph, nodesById, state = {}) {
  const edges = Array.isArray(graph.edges) ? graph.edges.filter((edge) => edge && edge.metadata && edge.metadata.runtime_edge === "logical_transition") : [];
  const activeStage = String(state.stage || "").toLowerCase();
  return edges.slice(0, 28).map((edge) => {
    const sourceId = edge.source || edge.metadata.from_stage;
    const targetId = edge.target || edge.metadata.to_stage;
    const source = nodesById[sourceId] || nodesById[edge.metadata.from_stage];
    const target = nodesById[targetId] || nodesById[edge.metadata.to_stage];
    if (!source || !target) return "";
    const x1 = source.left;
    const y1 = source.top;
    const x2 = target.left;
    const y2 = target.top;
    const edgeStageIds = [sourceId, targetId, edge.metadata.from_stage, edge.metadata.to_stage].map((value) => String(value || "").toLowerCase());
    const activeClass = activeStage && edgeStageIds.includes(activeStage) ? " edge-active" : "";
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="live-graph-edge${activeClass}" marker-end="url(#live-arrow)"><title>${escapeHtml(edge.label || `${sourceId} -> ${targetId}`)}</title></line>`;
  }).join("");
}

function graphEdgesForNode(graph, nodeId) {
  const edges = Array.isArray(graph.edges) ? graph.edges : [];
  return edges.filter((edge) => (edge.source || edge.metadata?.from_stage) === nodeId || (edge.target || edge.metadata?.to_stage) === nodeId);
}

function renderSelectedGraphNodeView(graph, state) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const activeStage = String(state.stage || "").toLowerCase();
  const fallbackNode = nodes.find((node) => String(node.stage || node.id || "").toLowerCase() === activeStage) || nodes[0] || null;
  const selectedNode = liveGraphSelectionCleared ? null : (nodes.find((node) => node.id === liveSelectedGraphNodeId) || fallbackNode);
  if (!selectedNode) {
    return `<aside class="live-selected-node-view empty" data-selected-graph-node=""><h4>Selected Node</h4><p class="hint">No node selected. Click a graph node to inspect it.</p></aside>`;
  }
  liveSelectedGraphNodeId = selectedNode.id;
  const edges = graphEdgesForNode(graph, selectedNode.id);
  const incoming = edges.filter((edge) => (edge.target || edge.metadata?.to_stage) === selectedNode.id).length;
  const outgoing = edges.filter((edge) => (edge.source || edge.metadata?.from_stage) === selectedNode.id).length;
  const agentId = agentIdFromStage(selectedNode.stage || selectedNode.id);
  return `
    <aside class="live-selected-node-view" data-selected-graph-node="${escapeHtml(selectedNode.id)}">
      <div class="live-selected-node-head">
        <div>
          <h4>Selected Node</h4>
          <strong>${escapeHtml(selectedNode.label || selectedNode.id)}</strong>
        </div>
        <span class="badge ${agentId === agentIdFromStage(state.stage || "") ? "running" : "idle"}">${escapeHtml(agentId)}</span>
      </div>
      ${runtimeRows([
        ["node_id", selectedNode.id],
        ["stage", selectedNode.stage || selectedNode.id],
        ["handler", selectedNode.handler],
        ["kind", selectedNode.kind || "agent"],
        ["incoming_edges", incoming],
        ["outgoing_edges", outgoing],
        ["current_stage", state.stage],
      ])}
      <div class="button-row live-selected-node-actions">
        <button class="btn live-context-action live-selected-node-action" data-context-action="open_report" data-agent-id="${escapeHtml(agentId)}" title="Open selected node report" aria-label="Open selected node report"><span class="live-card-action-icon" aria-hidden="true">R</span><span class="live-card-action-label">Open Report</span></button>
        <button class="btn live-context-action live-selected-node-action" data-context-action="open_backend" data-agent-id="${escapeHtml(agentId)}" title="Open selected node backend trace" aria-label="Open selected node backend trace"><span class="live-card-action-icon" aria-hidden="true">{}</span><span class="live-card-action-label">Open Backend</span></button>
        <button class="btn live-context-action live-selected-node-action" data-context-action="run_node_test" data-agent-id="${escapeHtml(agentId)}" title="Run selected node test" aria-label="Run selected node test"><span class="live-card-action-icon" aria-hidden="true">T</span><span class="live-card-action-label">Run Node Test</span></button>
      </div>
    </aside>
  `;
}

function liveGraphActionStatusHtml() {
  if (!liveGraphActionStatus) return `<p class="hint">No graph gate action has run in this Live GUI session.</p>`;
  const status = liveGraphActionStatus;
  const className = status.ok ? "ok" : "warning";
  return `
    <div class="live-graph-action-status ${className}">
      <strong>${escapeHtml(status.label || status.action || "graph action")}</strong>
      <span>${escapeHtml(status.message || "-")}</span>
      ${runtimeRows([
        ["graph_id", status.graph_id],
        ["compiled", status.compiled],
        ["version", status.version_id],
        ["activated", status.activated],
        ["run_id", status.run_id],
        ["mode", status.mode],
        ["errors", status.errors && status.errors.length ? status.errors.join(" | ") : "none"],
      ])}
    </div>
  `;
}

function renderGraphGateControls(graph) {
  const graphId = graph.id || "atr_closed_loop";
  return `
    <section class="runtime-card-section live-graph-gate-card">
      <div class="live-graph-gate-head">
        <div>
          <h4>Graph Gates</h4>
          <p class="hint">Validate, compile, or save a version of the active graph without editing it inside Live mode.</p>
        </div>
        <span class="badge idle">${escapeHtml(graphId)}</span>
      </div>
      <div class="button-row live-graph-gate-actions">
        <button class="btn live-graph-action" data-graph-action="validate" title="Validate the active graph through /api/graphs/{graph_id}/validate" aria-label="Validate graph"><span class="live-card-action-icon" aria-hidden="true">V</span><span class="live-card-action-label">Validate</span></button>
        <button class="btn live-graph-action" data-graph-action="compile" title="Compile the active graph through /api/graphs/{graph_id}/compile" aria-label="Compile graph"><span class="live-card-action-icon" aria-hidden="true">C</span><span class="live-card-action-label">Compile</span></button>
        <button class="btn live-graph-action" data-graph-action="save_version" title="Save a version-only graph snapshot through /api/graphs/{graph_id}/save-version" aria-label="Save graph version"><span class="live-card-action-icon" aria-hidden="true">S</span><span class="live-card-action-label">Save Version</span></button>
        <button class="btn live-graph-action" data-graph-action="run_test" title="Run the active graph through /api/graphs/{graph_id}/run in test mode" aria-label="Run graph in test mode"><span class="live-card-action-icon" aria-hidden="true">▶</span><span class="live-card-action-label">Run Test</span></button>
      </div>
      ${liveGraphActionStatusHtml()}
    </section>
  `;
}

async function runLiveGraphGateAction(action) {
  const graph = (liveGraphPayload && liveGraphPayload.graph) || liveGraphPayload || {};
  const graphId = graph.id || "atr_closed_loop";
  const labelMap = { validate: "Graph Validate", compile: "Graph Compile", save_version: "Graph Save Version", run_test: "Graph Run Test" };
  if (!Object.prototype.hasOwnProperty.call(labelMap, action)) return;
  if (action === "run_test" && firstPendingApproval()) {
    liveGraphActionStatus = { action, label: labelMap[action], graph_id: graphId, ok: false, message: "blocked: approval required", errors: ["Pending operator approval"] };
    renderGraphMiniPanel(liveLastSession);
    await blockLiveExecutionForPendingApproval("live_graph.run_test", labelMap[action], { graph_id: graphId, mode: "test", source_action: "live_graph.run_test" });
    renderGraphMiniPanel(liveLastSession);
    return;
  }
  setChatStatus(labelMap[action].toUpperCase(), "running");
  liveGraphActionStatus = { action, label: labelMap[action], graph_id: graphId, ok: false, message: "running", errors: [] };
  renderGraphMiniPanel(liveLastSession);
  let graphIntentEvent = null;
  try {
    if (action === "save_version") {
      const intent = await recordLiveIntentEvent("graph_change_requested", "graph_save_version", "Live GUI graph version save requested.", { graph_id: graphId, activate: false, source_action: "live_graph.save_version" });
      graphIntentEvent = intent && intent.event ? intent.event : null;
    }
    if (action === "run_test") {
      const intent = await recordLiveIntentEvent("graph_run_requested", "graph_run_test", "Live GUI graph test run requested.", { graph_id: graphId, mode: "test", source_action: "live_graph.run_test" });
      graphIntentEvent = intent && intent.event ? intent.event : null;
    }
    const options = action === "save_version"
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "live_gui_graph_gate_save_version", author: "live_gui", activate: false }) }
      : action === "run_test"
        ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "test", goal: `Live GUI graph gate test run: ${graphId}`, backend: queryBackend }) }
        : { method: "POST" };
    const endpoint = action === "validate"
      ? `/api/graphs/${encodeURIComponent(graphId)}/validate`
      : action === "compile"
        ? `/api/graphs/${encodeURIComponent(graphId)}/compile`
        : action === "run_test"
          ? `/api/graphs/${encodeURIComponent(graphId)}/run`
          : `/api/graphs/${encodeURIComponent(graphId)}/save-version`;
    const data = await fetchJsonOrThrow(endpoint, options);
    const version = data.version && typeof data.version === "object" ? data.version : {};
    liveGraphActionStatus = {
      action,
      label: labelMap[action],
      graph_id: data.graph_id || graphId,
      ok: Boolean(data.ok),
      compiled: Boolean(data.compiled || data.compiled_graph),
      version_id: version.version_id || version.id || "",
      activated: Boolean(data.activated),
      run_id: data.run && typeof data.run === "object" ? (data.run.run_id || "") : "",
      mode: action === "run_test" ? "test" : "",
      message: data.ok ? (action === "run_test" ? `started ${data.run && data.run.run_id ? data.run.run_id : "test run"}` : "ok") : "failed",
      errors: Array.isArray(data.errors) ? data.errors : [],
    };
    await refreshPlanningState({ background: true });
    if (graphIntentEvent && action === "run_test") {
      const intentId = String(graphIntentEvent.event_id || graphIntentEvent.id || "");
      const isSameIntent = (event) => {
        const eventId = String(event.event_id || event.id || "");
        const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
        return (intentId && eventId === intentId) || (String(event.event_type || event.type || "") === "graph_run_requested" && payload.source_action === "live_graph.run_test");
      };
      if (!liveRecentEvents.some(isSameIntent)) liveRecentEvents.push(graphIntentEvent);
      if (!liveRunEvents.some(isSameIntent)) liveRunEvents.push(graphIntentEvent);
      liveRecentEvents = liveRecentEvents.slice(-160);
      liveRunEvents = liveRunEvents.slice(-160);
    }
    setChatStatus(data.ok ? "GRAPH OK" : "GRAPH ISSUE", data.ok ? "idle" : "warning");
  } catch (err) {
    liveGraphActionStatus = { action, label: labelMap[action], graph_id: graphId, ok: false, message: String(err), errors: [String(err)] };
    appendLiveRuntimeEvent({
      event_type: "graph_gate_failed",
      level: "ERROR",
      node_id: liveSelectedAgent || "orchestrator",
      message: `${labelMap[action]} failed: ${String(err)}`,
      payload: { graph_id: graphId, action, error: String(err) },
    });
    setChatStatus("GRAPH ERROR", "warning");
  }
  renderGraphMiniPanel(liveLastSession);
}

function renderGraphMiniPanel(session) {
  if (!liveGraphPanel) return;
  const state = session.state || {};
  const graph = (liveGraphPayload && liveGraphPayload.graph) || liveGraphPayload || {};
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const activeStage = String(state.stage || "").toLowerCase();
  if (!liveSelectedGraphNodeId && !liveGraphSelectionCleared) {
    const activeNode = nodes.find((node) => String(node.stage || node.id || "").toLowerCase() === activeStage) || nodes[0];
    liveSelectedGraphNodeId = activeNode ? activeNode.id : "";
  }
  const nodesById = {};
  nodes.forEach((node, index) => {
    nodesById[node.id] = { ...graphNodePosition(node, index, nodes.length), node };
  });
  const graphId = graph.id || "atr_closed_loop";
  const ideNodeRef = liveSelectedGraphNodeId || state.stage || "";
  const runtimeIdeHref = `/ide?graph=${encodeURIComponent(graphId)}${ideNodeRef ? `&node=${encodeURIComponent(ideNodeRef)}` : ""}&source=live_graph`;
  const nodeHtml = nodes.map((node, index) => {
    const pos = nodesById[node.id] || graphNodePosition(node, index, nodes.length);
    const stage = node.stage || node.id;
    const selectedClass = node.id === liveSelectedGraphNodeId ? "node-selected" : "";
    return `
      <button class="live-graph-mini-node ${selectedClass} ${liveGraphNodeClass(node, state)}" style="left:${pos.left}%; top:${pos.top}%" data-agent-id="${escapeHtml(agentIdFromStage(stage))}" data-graph-node-id="${escapeHtml(node.id)}" title="${escapeHtml(node.handler || "")}">
        <span class="node-light"></span>
        <strong>${escapeHtml(node.label || node.id)}</strong>
        <em>${escapeHtml(stage || node.kind || "node")}</em>
      </button>
    `;
  }).join("");
  liveGraphPanel.innerHTML = `
    <div class="live-graph-mini-wrap">
      <div class="runtime-card-section">
        <h4>Active Graph</h4>
        ${runtimeRows([
          ["graph_id", graphId],
          ["version", graph.version],
          ["entry_node", graph.entry_node],
          ["current_stage", state.stage],
          ["nodes", nodes.length],
          ["logical_edges", (graph.edges || []).filter((edge) => edge.metadata && edge.metadata.runtime_edge === "logical_transition").length],
        ])}
        <div class="artifact-links">
          <a data-live-ide-link href="${escapeHtml(runtimeIdeHref)}" target="_blank" rel="noreferrer" title="Open Runtime IDE focused on graph=${escapeHtml(graphId)} node=${escapeHtml(ideNodeRef || "")}">Open Runtime IDE</a>
          <a href="/api/graphs/${encodeURIComponent(graphId)}" target="_blank" rel="noreferrer">Graph JSON</a>
        </div>
      </div>
      ${renderGraphGateControls(graph)}
      <div class="live-graph-mini-body">
        <div class="live-graph-mini-canvas">
          <svg class="live-graph-mini-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <defs><marker id="live-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z"></path></marker></defs>
            ${renderGraphEdges(graph, nodesById, state)}
          </svg>
          ${nodeHtml || "<p class='hint'>Graph not loaded.</p>"}
        </div>
        ${renderSelectedGraphNodeView(graph, state)}
      </div>
    </div>
  `;
}

function planningArtifactSummaries() {
  return planningMessagesCache
    .map((msg, index) => ({ msg, html: renderArtifactCard(msg) + renderFemContourCard(msg) + renderBoResultCard(msg, `artifact-${index}`) }))
    .filter((item) => item.html.trim());
}

function renderArtifactPanel() {
  if (!liveArtifactPanel) return;
  const runArtifacts = (liveRunArtifacts || []).map((artifact) => `
    <article class="live-file-artifact">
      <strong>${escapeHtml(artifact.name || artifact.path)}</strong>
      <span>${escapeHtml(artifact.path || "")} · ${escapeHtml(artifact.preview_kind || artifact.suffix || "file")} · ${escapeHtml(renderRuntimeValue(artifact.size_bytes))} bytes</span>
      <div class="artifact-links">
        ${artifact.url ? `<a href="${escapeHtml(artifact.url)}" target="_blank" rel="noreferrer">Open</a>` : ""}
        ${artifact.download_url ? `<a href="${escapeHtml(artifact.download_url)}" target="_blank" rel="noreferrer">Download</a>` : ""}
      </div>
    </article>
  `).join("");
  const planningArtifacts = planningArtifactSummaries().map((item) => `
    <section class="live-planning-artifact">
      <h4>${escapeHtml(roleLabel(item.msg.role))}</h4>
      ${item.html}
    </section>
  `).join("");
  liveArtifactPanel.innerHTML = `
    <div class="live-artifact-grid">
      <section class="runtime-card-section runtime-card-wide">
        <h4>Run Directory Artifacts</h4>
        <div class="live-file-artifact-list">${runArtifacts || "<p class='hint'>No run artifacts.</p>"}</div>
      </section>
      <section class="runtime-card-section runtime-card-wide">
        <h4>Chat-Linked Artifacts</h4>
        ${planningArtifacts || "<p class='hint'>Agent artifacts appear here.</p>"}
      </section>
    </div>
  `;
  initStlViewers();
}

function timelineSourceEvents() {
  return (liveRunEvents.length ? liveRunEvents : liveRecentEvents).slice(-80);
}

function eventTimelineKind(event) {
  const type = String(event.event_type || event.type || "").toLowerCase();
  const level = String(event.level || event.severity || "").toLowerCase();
  const msg = String(event.message || "").toLowerCase();
  if (level.includes("error") || type.includes("error") || type.includes("failed") || msg.includes("failed")) return "error";
  if (level.includes("warn") || type.includes("warning") || type.includes("approval")) return "warning";
  if (type.includes("tool") || msg.includes("tool")) return "tool";
  if (type.includes("artifact") || msg.includes("artifact") || msg.includes("stl") || msg.includes("gcode")) return "artifact";
  if (type.includes("handoff") || type.includes("stage_changed") || msg.includes("handoff")) return "handoff";
  return "info";
}

function filteredTimelineEvents() {
  const source = timelineSourceEvents();
  if (liveTimelineFilter === "all") return source.slice(-40);
  return source.filter((event) => eventTimelineKind(event) === liveTimelineFilter).slice(-40);
}

function renderTimelineFilters(sourceCount, filteredCount) {
  liveTimelineFilters.forEach((button) => {
    const filter = button.dataset.timelineFilter || "all";
    button.classList.toggle("active", filter === liveTimelineFilter);
    button.title = `${filter}: ${filteredCount}/${sourceCount} visible`;
  });
}

function renderTimelinePanels() {
  const source = timelineSourceEvents();
  const events = filteredTimelineEvents();
  if (liveEventCount) liveEventCount.textContent = `${events.length}/${source.length}`;
  renderTimelineFilters(source.length, events.length);
  const stripItems = events.slice(-12).map((event) => {
    const kind = eventTimelineKind(event);
    const key = eventStableKey(event);
    const selected = key && key === liveSelectedEventKey ? "selected" : "";
    const eventTitle = `${formatTime(event.ts || event.timestamp)} · ${event.event_type || event.type || "event"} · ${event.message || event.status || ""}`;
    return `
      <button class="live-timeline-item ${selected} severity-${escapeHtml(kind)}" data-agent-id="${escapeHtml(agentIdFromEvent(event))}" data-event-kind="${escapeHtml(kind)}" data-event-key="${escapeHtml(key)}" title="${escapeHtml(eventTitle)}" aria-label="${escapeHtml(eventTitle)}">
        <span>${escapeHtml(formatTime(event.ts || event.timestamp))}</span>
        <strong>${escapeHtml(event.event_type || event.type || "event")}</strong>
        <em>${escapeHtml(compactText(event.message || event.status || "", 80))}</em>
      </button>
    `;
  }).join("");
  if (liveTimelineStrip) liveTimelineStrip.innerHTML = stripItems || "<p class='hint'>No events.</p>";
  if (liveTimelineDetailPanel) {
    liveTimelineDetailPanel.innerHTML = `
      <div class="live-timeline-detail">
        ${renderSelectedEventCard("timeline")}
        ${events.slice().reverse().map((event) => {
          const key = eventStableKey(event);
          const selected = key && key === liveSelectedEventKey ? "selected" : "";
          return `
            <article class="live-timeline-detail-item ${selected} severity-${escapeHtml(eventTimelineKind(event))}" data-event-key="${escapeHtml(key)}">
              <small>${escapeHtml(formatTime(event.ts || event.timestamp))} · ${escapeHtml(agentIdFromEvent(event))} · ${escapeHtml(eventTimelineKind(event))}</small>
              <strong>${escapeHtml(event.event_type || event.type || "event")}</strong>
              <p>${escapeHtml(event.message || "")}</p>
            </article>
          `;
        }).join("") || "<p class='hint'>No detail.</p>"}
      </div>
    `;
  }
}

function isAgentQuestionEvent(event) {
  const payload = eventPayload(event);
  const type = String(event.event_type || event.type || "").toLowerCase();
  if (type.includes("approval")) return false;
  const text = `${type} ${event.message || ""} ${payload.question || ""} ${payload.message || ""}`.toLowerCase();
  return type === "agent_question"
    || type.includes("agent_question")
    || type.includes("user_input")
    || type.includes("clarification")
    || Boolean(payload.requires_user_input || payload.requires_operator_input || payload.needs_operator_input || payload.question || payload.missing_fields)
    || text.includes("missing input")
    || text.includes("clarification");
}

function pendingAgentQuestions() {
  return timelineSourceEvents()
    .filter(isAgentQuestionEvent)
    .filter((event) => !liveReadQuestionKeys[eventStableKey(event)])
    .slice(-8)
    .reverse();
}

function questionText(event) {
  const payload = eventPayload(event);
  const missing = Array.isArray(payload.missing_fields) && payload.missing_fields.length ? ` Missing fields: ${payload.missing_fields.join(", ")}.` : "";
  return payload.question || payload.message || event.message || `Agent ${agentIdFromEvent(event)} requested operator input.${missing}`;
}

function renderQuestionCard(event) {
  const key = eventStableKey(event);
  const payload = eventPayload(event);
  const agentId = agentIdFromEvent(event);
  return `
    <article class="live-approval-card live-question-card" data-question-key="${escapeHtml(key)}">
      <strong>${escapeHtml(payload.title || `${liveAgentLabel(agentId)} Question`)}</strong>
      <p>${escapeHtml(questionText(event))}</p>
      ${Array.isArray(payload.missing_fields) && payload.missing_fields.length ? `<small>Missing: ${escapeHtml(payload.missing_fields.join(", "))}</small>` : ""}
      <div class="button-row live-question-actions">
        <button class="btn primary live-question-action" data-question-key="${escapeHtml(key)}" data-question-action="answer" title="Answer this agent question in Runtime Chat" aria-label="Answer this agent question in Runtime Chat"><span class="live-card-action-icon" aria-hidden="true">↵</span><span class="live-card-action-label">Answer in Chat</span></button>
        <button class="btn live-question-action" data-question-key="${escapeHtml(key)}" data-question-action="backend" title="Open backend trace for this question" aria-label="Open backend trace for this question"><span class="live-card-action-icon" aria-hidden="true">{}</span><span class="live-card-action-label">Open Backend</span></button>
        <button class="btn live-question-action" data-question-key="${escapeHtml(key)}" data-question-action="read" title="Mark this question as read" aria-label="Mark this question as read"><span class="live-card-action-icon" aria-hidden="true">✓</span><span class="live-card-action-label">Mark Read</span></button>
      </div>
    </article>
  `;
}


function isRuntimeFaultEvent(event) {
  if (isAgentQuestionEvent(event)) return false;
  const payload = eventPayload(event);
  const kind = eventTimelineKind(event);
  const text = `${event.event_type || event.type || ""} ${event.message || ""} ${event.status || ""} ${event.level || event.severity || ""} ${payload.device || ""} ${payload.tool || ""} ${payload.failure_code || ""} ${JSON.stringify(payload)}`.toLowerCase();
  const devicePattern = /device|printer|prusa|slicer|gcode|robot|lerobot|teleop|rollout|camera|vision|utm|bridge|windows|pyautogui|equipment|gpu|llm|stream|sync|sensor|fault|unsafe|failed|error|timeout|connection|disconnect/;
  if (kind === "error") return true;
  return kind === "warning" && devicePattern.test(text);
}

function liveFaultEvents(limit = 8) {
  return timelineSourceEvents()
    .filter(isRuntimeFaultEvent)
    .slice(-limit)
    .reverse();
}

function pendingRuntimeFaults() {
  return liveFaultEvents(8).filter((event) => !liveReadFaultKeys[eventStableKey(event)]);
}

function faultText(event) {
  const payload = eventPayload(event);
  const code = payload.failure_code || payload.code || payload.error_code || "";
  const message = payload.message || event.message || event.status || "Runtime fault requires operator review.";
  return compactText(`${code ? `${code}: ` : ""}${message}`, 180);
}

function recordLiveAttentionAction(kind, action, event) {
  if (!event) return Promise.resolve(null);
  const payload = eventPayload(event);
  const agentId = agentIdFromEvent(event) || liveSelectedAgent;
  const eventType = event.event_type || event.type || "event";
  const traceId = event.trace_id || payload.trace_id || payload.selected_trace_id || "";
  const nodeId = event.node_id || payload.node_id || payload.selected_node_id || graphNodeIdForAgent(agentId) || agentId;
  const key = eventStableKey(event);
  return recordLiveOperatorEvent(
    `${kind}_${action}`,
    `${liveAgentLabel(agentId)} ${kind} ${action} from Operator Attention.`,
    {
      attention_kind: kind,
      attention_action: action,
      attention_event_key: key,
      attention_event_type: eventType,
      attention_agent_id: agentId,
      attention_node_id: nodeId,
      attention_trace_id: traceId,
      attention_message: event.message || payload.message || payload.question || "",
      attention_payload_excerpt: compactText(JSON.stringify(payload || {}), 700),
    },
    "operator.attention"
  );
}

function renderFaultCard(event) {
  const key = eventStableKey(event);
  const payload = eventPayload(event);
  const agentId = agentIdFromEvent(event);
  const kind = eventTimelineKind(event);
  const title = payload.title || `${liveAgentLabel(agentId)} ${kind === "error" ? "Error" : "Warning"}`;
  return `
    <article class="live-approval-card live-fault-card severity-${escapeHtml(kind)}" data-fault-key="${escapeHtml(key)}">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(faultText(event))}</p>
      <small>${escapeHtml(formatTime(event.ts || event.timestamp))} · ${escapeHtml(agentId)} · ${escapeHtml(event.event_type || event.type || "event")}</small>
      <div class="button-row live-fault-actions">
        <button class="btn live-fault-action" data-fault-key="${escapeHtml(key)}" data-fault-action="backend" title="Open backend trace for this fault" aria-label="Open backend trace for this fault"><span class="live-card-action-icon" aria-hidden="true">{}</span><span class="live-card-action-label">Open Backend</span></button>
        <button class="btn live-fault-action" data-fault-key="${escapeHtml(key)}" data-fault-action="read" title="Mark this fault as read" aria-label="Mark this fault as read"><span class="live-card-action-icon" aria-hidden="true">✓</span><span class="live-card-action-label">Mark Read</span></button>
      </div>
    </article>
  `;
}

function updateLiveFaultChip() {
  const faults = liveFaultEvents(12);
  if (!faults.length) {
    setRuntimeChip(liveFaultChip, "F:0", "idle", "No runtime faults detected");
    return;
  }
  const errors = faults.filter((event) => eventTimelineKind(event) === "error").length;
  const warnings = Math.max(0, faults.length - errors);
  const latest = faults[0];
  const label = errors ? `E:${errors}${warnings ? ` W:${warnings}` : ""}` : `W:${warnings}`;
  const cls = errors ? "error" : "warning";
  setRuntimeChip(
    liveFaultChip,
    label,
    cls,
    `Runtime faults: ${errors} errors, ${warnings} warnings. Latest: ${faultText(latest)}`
  );
}

function handleFaultAction(action, key) {
  const event = findEventByKey(key);
  if (!event) return;
  if (action === "backend") {
    selectTimelineEventByKey(key, agentIdFromEvent(event));
    recordLiveAttentionAction("fault", "backend", event).catch(() => {});
    setLiveView("backend");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "read") {
    liveReadFaultKeys[key] = true;
    recordLiveAttentionAction("fault", "read", event).catch(() => {});
    renderLiveRuntime(liveLastSession);
  }
}

function applyLiveAttentionStatus() {
  if (!planningChatStatus) return;
  if (planningThinkingCount > 0 || liveBackendPlanningBusy || liveQuickActionBusy) return;
  const pending = liveApprovals.pending || [];
  const questions = pendingAgentQuestions();
  const faults = pendingRuntimeFaults();
  const errors = faults.filter((event) => eventTimelineKind(event) === "error");
  if (pending.length || questions.length) {
    planningChatStatus.dataset.attentionStatus = "1";
    setChatStatus(
      "WAITING_USER",
      "warning",
      `Waiting for operator input: ${pending.length} approvals, ${questions.length} questions, ${faults.length} faults.`
    );
    return;
  }
  if (errors.length || faults.length) {
    planningChatStatus.dataset.attentionStatus = "1";
    setChatStatus(
      errors.length ? "ERROR" : "WARNING",
      errors.length ? "warning" : "warning",
      `Runtime attention required: ${errors.length} errors, ${Math.max(0, faults.length - errors.length)} warnings.`
    );
    return;
  }
  if (planningChatStatus.dataset.attentionStatus === "1") {
    planningChatStatus.dataset.attentionStatus = "0";
    setChatStatus("READY", "idle", "No pending operator attention.");
  }
}

function renderApprovalPanel(session) {
  if (!liveApprovalPanel) return;
  const pending = liveApprovals.pending || [];
  const questions = pendingAgentQuestions();
  const faults = pendingRuntimeFaults();
  if (!pending.length && !questions.length && !faults.length) {
    liveApprovalPanel.hidden = true;
    liveApprovalPanel.innerHTML = "";
    return;
  }
  liveApprovalPanel.hidden = false;
  const runId = (session.state || {}).run_id || "";
  liveApprovalPanel.innerHTML = `
    <div class="live-approval-head"><strong>Operator Attention</strong><span>${pending.length} approvals · ${questions.length} questions · ${faults.length} faults</span></div>
    ${pending.map((item) => `
      <article class="live-approval-card">
        <strong>${escapeHtml(item.title || "Approval required")}</strong>
        <p>${escapeHtml(item.reason || item.stage || "Operator review required.")}</p>
        <div class="button-row">
          <button class="btn primary live-approval-action" data-run-id="${escapeHtml(runId)}" data-approval-id="${escapeHtml(item.approval_id)}" data-decision="approved">Approve</button>
          <button class="btn live-approval-action" data-run-id="${escapeHtml(runId)}" data-approval-id="${escapeHtml(item.approval_id)}" data-decision="cancelled">Revise</button>
          <button class="btn warning live-approval-action" data-run-id="${escapeHtml(runId)}" data-approval-id="${escapeHtml(item.approval_id)}" data-decision="rejected">Reject</button>
        </div>
      </article>
    `).join("")}
    ${questions.map(renderQuestionCard).join("")}
    ${faults.map(renderFaultCard).join("")}
  `;
}

function answerAgentQuestion(key) {
  const event = findEventByKey(key);
  if (!event) return;
  selectTimelineEventByKey(key, agentIdFromEvent(event));
  const payload = eventPayload(event);
  const missing = Array.isArray(payload.missing_fields) && payload.missing_fields.length ? `\n필수 입력값: ${payload.missing_fields.join(", ")}\n답변: ` : "\n답변: ";
  draftRuntimeChat(`${liveAgentLabel(liveSelectedAgent)} 질문에 대한 응답입니다.\n질문: ${questionText(event)}${missing}`, "command");
  recordLiveAttentionAction("question", "answer", event).catch(() => {});
  setLiveChatTargetMode("selected_agent");
  setLiveView("backend");
  renderLiveRuntime(liveLastSession);
}

function handleQuestionAction(action, key) {
  const event = findEventByKey(key);
  if (!event) return;
  if (action === "answer") {
    answerAgentQuestion(key);
    return;
  }
  if (action === "backend") {
    selectTimelineEventByKey(key, agentIdFromEvent(event));
    recordLiveAttentionAction("question", "backend", event).catch(() => {});
    setLiveView("backend");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "read") {
    liveReadQuestionKeys[key] = true;
    recordLiveAttentionAction("question", "read", event).catch(() => {});
    renderLiveRuntime(liveLastSession);
  }
}


function latestRuntimeEvent(patterns) {
  const events = timelineSourceEvents().slice().reverse();
  return events.find((event) => {
    const haystack = `${event.event_type || event.type || ""} ${event.message || ""} ${event.node_id || ""} ${event.module_id || ""} ${JSON.stringify(event.payload || {})}`.toLowerCase();
    return patterns.some((pattern) => pattern.test(haystack));
  }) || null;
}

function eventBridgeStatus(event, fallback = "idle") {
  if (!event) return fallback;
  const kind = eventTimelineKind(event);
  if (kind === "error") return "error";
  if (kind === "warning") return "waiting";
  return "active";
}

function eventLastCommand(event) {
  if (!event) return "no event";
  return compactText(`${event.event_type || event.type || "event"}: ${event.message || event.status || ""}`, 96);
}

function renderDeviceStatusCard(title, event, fallbackStatus = "idle") {
  const status = eventBridgeStatus(event, fallbackStatus);
  const command = eventLastCommand(event);
  const heartbeat = event ? formatTime(event.ts || event.timestamp) : "-";
  const safeState = status === "error" ? "unsafe/review" : status === "waiting" ? "operator review" : status === "active" ? "safe/active" : "unknown";
  const eventKey = event ? eventStableKey(event) : "";
  const agentId = event ? agentIdFromEvent(event) : "";
  const eventType = event ? (event.event_type || event.type || "") : "";
  const clickHint = eventKey ? "\nclick: focus backend trace" : "";
  const tooltip = `${title}\nbridge: ${status}\nlast command: ${command}\nheartbeat: ${heartbeat}\nsafety: ${safeState}${clickHint}`;
  const eventAttrs = eventKey
    ? ` role="button" data-device-event-key="${escapeHtml(eventKey)}" data-agent-id="${escapeHtml(agentId)}" data-device-name="${escapeHtml(title)}" data-device-event-type="${escapeHtml(eventType)}" aria-label="${escapeHtml(`${title}: ${status}. Click to inspect backend trace.`)}"`
    : "";
  return `
    <article class="live-device-card status-${escapeHtml(status)}${eventKey ? " has-event" : ""}" title="${escapeHtml(tooltip)}" tabindex="0"${eventAttrs}>
      <span>${escapeHtml(title)}</span>
      <strong>${escapeHtml(status)}</strong>
      <dl>
        <div class="live-device-field"><dt>bridge</dt><dd>${escapeHtml(status)}</dd></div>
        <div class="live-device-field"><dt>last command</dt><dd>${escapeHtml(command)}</dd></div>
        <div class="live-device-field"><dt>heartbeat</dt><dd>${escapeHtml(heartbeat)}</dd></div>
        <div class="live-device-field"><dt>safety</dt><dd>${escapeHtml(safeState)}</dd></div>
      </dl>
    </article>
  `;
}

async function focusDeviceEventFromCard(card) {
  if (!card) return;
  const eventKey = card.dataset.deviceEventKey || "";
  if (!eventKey) return;
  const agentId = card.dataset.agentId || "";
  const deviceName = card.dataset.deviceName || "device";
  const eventType = card.dataset.deviceEventType || "";
  selectTimelineEventByKey(eventKey, agentId);
  setLiveView("backend");
  renderLiveRuntime(liveLastSession);
  setChatStatus(`DEVICE ${liveAgentShort(liveSelectedAgent)}`, "idle", `${deviceName} trace focused`);
  await recordLiveOperatorEvent(
    "trace_focused",
    `${deviceName} device card focused backend trace from Live GUI.`,
    {
      source_action: "device_card.focus_trace",
      device_name: deviceName,
      device_event_key: eventKey,
      device_event_type: eventType,
      target_agent: liveSelectedAgent,
    },
    "operator.device"
  );
}

function renderResourceStatusCard(title, value, detail, status = "ready") {
  const heartbeat = formatTime(new Date().toISOString());
  const safeState = status === "error" ? "unsafe/review" : "safe/ready";
  const tooltip = `${title}\nbridge: ${status}\nlast command: ${detail}\nheartbeat: ${heartbeat}\nsafety: ${safeState}`;
  return `
    <article class="live-device-card status-${escapeHtml(status)}" title="${escapeHtml(tooltip)}" tabindex="0">
      <span>${escapeHtml(title)}</span>
      <strong>${escapeHtml(value)}</strong>
      <dl>
        <div class="live-device-field"><dt>bridge</dt><dd>${escapeHtml(status)}</dd></div>
        <div class="live-device-field"><dt>last command</dt><dd>${escapeHtml(detail)}</dd></div>
        <div class="live-device-field"><dt>heartbeat</dt><dd>${escapeHtml(heartbeat)}</dd></div>
        <div class="live-device-field"><dt>safety</dt><dd>${escapeHtml(safeState)}</dd></div>
      </dl>
    </article>
  `;
}

function renderDeviceStrip(session) {
  if (!liveDeviceStrip) return;
  const snapshot = liveLastSnapshot || {};
  const state = session.state || snapshot.state || {};
  const resources = snapshot.system_resources || {};
  const gpu = resources.gpu || {};
  const ram = resources.ram || {};
  const runtime = session.runtime || snapshot.runtime || {};
  const backend = runtime.backend || {};
  const gpuAgg = gpu.aggregate || {};
  const gpuValue = `${renderRuntimeValue(gpuAgg.memory_used_gb)}/${renderRuntimeValue(gpuAgg.memory_total_gb)} GB`;
  const ramValue = `${renderRuntimeValue(ram.used_gb)}/${renderRuntimeValue(ram.total_gb)} GB`;
  const cards = [
    renderResourceStatusCard("Run", state.run_id || "-", `mode=${state.mode || "-"} · paused=${Boolean(state.is_paused)}`, state.is_paused ? "waiting" : "ready"),
    renderResourceStatusCard("GPU", gpuValue, `util=${renderRuntimeValue(gpuAgg.utilization_percent)}% · ${gpu.status || "unknown"}`, gpu.status || "ready"),
    renderResourceStatusCard("LLM", backend.label || backend.name || "-", `backend=${backend.name || "configured"}`, backend.status || "ready"),
    renderDeviceStatusCard("3D Printer", latestRuntimeEvent([/printer/, /prusa/, /slicer/, /gcode/, /specimen/]), "idle"),
    renderDeviceStatusCard("Robot Arm", latestRuntimeEvent([/robot/, /lerobot/, /manipulation/, /rollout/, /teleop/]), "idle"),
    renderDeviceStatusCard("UTM", latestRuntimeEvent([/utm/, /tensile/, /compression/, /equipment/]), "idle"),
    renderDeviceStatusCard("Camera", latestRuntimeEvent([/camera/, /vision/, /capture/, /image/]), "idle"),
    renderDeviceStatusCard("Windows Bridge", latestRuntimeEvent([/windows/, /pyautogui/, /bridge/, /equipment/]), "idle"),
    renderDeviceStatusCard("Environment Sensor", latestRuntimeEvent([/environment/, /sensor/, /humidity/, /temperature/]), "idle"),
  ];
  liveDeviceStrip.innerHTML = cards.join("");
  setCompactTextWithTitle(
    liveResourceChip,
    `GPU/RAM ${renderCompactMemoryGb(gpuAgg.memory_used_gb)}/${renderCompactMemoryGb(gpuAgg.memory_total_gb)} · ${renderCompactMemoryGb(ram.used_gb)}/${renderCompactMemoryGb(ram.total_gb)}`,
    `GPU ${gpuValue}; RAM ${ramValue}; GPU util=${renderRuntimeValue(gpuAgg.utilization_percent)}%`
  );
}

function renderLiveRuntime(session) {
  if (!session) return;
  const snapshot = liveLastSnapshot || {};
  const state = session.state || snapshot.state || {};
  ensureOperatorReportStateRun(state.run_id || liveCurrentRunId());
  const activeAgent = agentIdFromStage(state.stage || "");
  setCompactTextWithTitle(liveActiveAgentChip, `A:${liveAgentShort(activeAgent)}`, `Active agent: ${liveAgentLabel(activeAgent)}`);
  if (liveCenterTitle) liveCenterTitle.textContent = `${liveAgentLabel(liveSelectedAgent)} · ${liveCurrentView}`;
  renderAgentBinder(session);
  renderApprovalPanel(session);
  renderDeviceStrip(session);
  updateLiveFaultChip();
  applyLiveAttentionStatus();
  renderLiveChatContextStrip();
  renderLiveFocusStrip();
  updateLiveTokenChip(session);
  setLiveBottomCollapsed(liveBottomCollapsed, { persist: false });
  setLiveView(liveCurrentView, { render: false });
  renderActiveLiveCenterPanel(session);
  setLiveQuickActionBusy(liveQuickActionBusy);
  persistLiveUiState();
}

async function refreshLiveRunDetails(session) {
  const state = session.state || {};
  const runId = state.run_id || "";
  if (!runId) {
    renderLiveRuntime(session);
    return;
  }
  const endpoints = [
    fetch(`/api/runs/${encodeURIComponent(runId)}/events`).then((res) => (res.ok ? res.json() : { events: [] })).catch(() => ({ events: [] })),
    fetch(`/api/runs/${encodeURIComponent(runId)}/artifacts`).then((res) => (res.ok ? res.json() : { artifacts: [] })).catch(() => ({ artifacts: [] })),
    fetch(`/api/runs/${encodeURIComponent(runId)}/approvals`).then((res) => (res.ok ? res.json() : { approvals: [], pending: [], resolved: [] })).catch(() => ({ approvals: [], pending: [], resolved: [] })),
  ];
  const [events, artifacts, approvals] = await Promise.all(endpoints);
  liveRunEvents = Array.isArray(events.events) ? events.events : [];
  syncOperatorReportStateFromEvents({ preserveLocal: false });
  liveRunArtifacts = Array.isArray(artifacts.artifacts) ? artifacts.artifacts : [];
  liveApprovals = normalizedLiveApprovals({
    approvals: Array.isArray(approvals.approvals) ? approvals.approvals : [],
    pending: Array.isArray(approvals.pending) ? approvals.pending : [],
    resolved: Array.isArray(approvals.resolved) ? approvals.resolved : [],
  });
  renderLiveRuntime(session);
}

async function resolveLiveApproval(runId, approvalId, decision) {
  if (!runId || !approvalId) return;
  setChatStatus("APPROVAL", "running");
  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, operator: "live_gui", note: `Resolved from Live GUI: ${decision}` }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      throw new Error(data.detail || data.message || `HTTP ${res.status}`);
    }
    liveResolvedApprovalIds.add(String(approvalId));
    const previousApprovals = liveApprovals || { approvals: [], pending: [], resolved: [] };
    const resolvedItems = Array.isArray(data.resolved) ? data.resolved : [];
    liveApprovals = normalizedLiveApprovals({
      approvals: Array.isArray(data.approvals) ? data.approvals : (Array.isArray(previousApprovals.approvals) ? previousApprovals.approvals : []),
      pending: Array.isArray(data.pending)
        ? data.pending
        : (Array.isArray(previousApprovals.pending) ? previousApprovals.pending.filter((item) => String(item.approval_id || "") !== String(approvalId)) : []),
      resolved: resolvedItems.length
        ? resolvedItems
        : [...(Array.isArray(previousApprovals.resolved) ? previousApprovals.resolved : []), { approval_id: approvalId, decision }],
    });
    appendLiveRuntimeEvent({
      event_type: "approval.resolved",
      level: "INFO",
      node_id: liveSelectedAgent || "guardian",
      message: `Approval ${decision}: ${approvalId}`,
      payload: data,
    });
    const detailSession = (liveLastSession && liveLastSession.state && String(liveLastSession.state.run_id || "") === String(runId))
      ? liveLastSession
      : { ...(liveLastSession || {}), state: { ...((liveLastSession && liveLastSession.state) || {}), run_id: runId } };
    await refreshLiveRunDetails(detailSession);
    setChatStatus("READY", "idle");
    return data;
  } catch (err) {
    appendLiveRuntimeEvent({
      event_type: "approval.resolve_failed",
      level: "ERROR",
      node_id: liveSelectedAgent || "guardian",
      message: `Approval resolve failed: ${String(err)}`,
      payload: { run_id: runId, approval_id: approvalId, decision, error: String(err) },
    });
    setChatStatus("APPROVAL ERROR", "warning");
    throw err;
  }
}

function tickLiveRuntimeClock() {
  if (!liveRuntimeClock) return;
  const elapsed = Math.max(0, Math.floor((Date.now() - liveRuntimeStartedAt) / 1000));
  const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const seconds = String(elapsed % 60).padStart(2, "0");
  liveRuntimeClock.textContent = `${minutes}:${seconds}`;
}

function setLiveGuiDebugState(payload = {}) {
  const session = payload.session || liveLastSession || {};
  liveLastSnapshot = payload.snapshot || liveLastSnapshot || {};
  liveRunEvents = Array.isArray(payload.events) ? payload.events : liveRunEvents;
  liveRunArtifacts = Array.isArray(payload.artifacts) ? payload.artifacts : liveRunArtifacts;
  liveGraphPayload = payload.graph || liveGraphPayload;
  liveApprovals = normalizedLiveApprovals(payload.approvals || liveApprovals || { approvals: [], pending: [], resolved: [] });
  applyPlanningSession(session);
  syncOperatorReportStateFromEvents({ preserveLocal: Boolean(payload.preserve_operator_report_state) });
  renderLiveRuntime(session);
}

window.__liveGuiDebugSetState = setLiveGuiDebugState;
window.__liveGuiDebugSnapshot = function liveGuiDebugSnapshot() {
  return {
    selected_agent: liveSelectedAgent,
    current_view: liveCurrentView,
    selected_event_key: liveSelectedEventKey,
    selected_report_section: liveSelectedReportSectionTitle,
    planning_session_id: planningSessionId,
    session: liveLastSession,
    recent_events: liveRecentEvents,
    run_events: liveRunEvents,
    run_artifacts: liveRunArtifacts,
    pinned_findings: livePinnedFindings,
    reviewed_agents: liveReviewedAgents,
    operator_report_state_run_id: liveOperatorReportStateRunId,
    approvals: liveApprovals,
    graph_loaded: Boolean(liveGraphPayload),
    stream_state: liveStreamState,
    sync_state: liveSyncState,
    sync_failure_count: liveSyncFailureCount,
    last_sync_at: liveLastSyncAt,
    last_event_at: liveLastEventAt,
    chat_status: planningChatStatus ? planningChatStatus.textContent : "",
    backend_planning_busy: liveBackendPlanningBusy,
    chat_context: liveChatContextSummary(),
    token_usage: collectLiveTokenUsage(liveLastSession),
    fault_events: liveFaultEvents(12),
    read_fault_keys: liveReadFaultKeys,
  };
};

window.__liveGuiDebugRestoreOperatorReportState = function liveGuiDebugRestoreOperatorReportState(agentId = "", view = "") {
  livePinnedFindings = [];
  liveReviewedAgents = {};
  syncOperatorReportStateFromEvents({ preserveLocal: false });
  if (knownLiveAgent(agentId)) liveSelectedAgent = agentId;
  if (LIVE_VIEW_IDS.has(view)) liveCurrentView = view;
  renderLiveRuntime(liveLastSession);
  return window.__liveGuiDebugSnapshot();
};

function applyPlanningSession(session) {
  liveLastSession = session || {};
  if (liveLastSession.planning_session_id) {
    persistPlanningSessionId(liveLastSession.planning_session_id);
  }
  const snapshot = liveLastSnapshot || {};
  const state = liveLastSession.state || snapshot.state || {};
  const metadata = state.run_metadata || {};
  planningPendingSpecimenInput = metadata.pending_specimen_input || null;
  const running = liveRunningFlag(liveLastSession, snapshot, state);
  setLiveBackendPlanningBusy(Boolean(liveLastSession.is_planning_busy));
  setPlanningDot(running);
  const stageLabel = String(state.stage || "idle");
  const runId = String(state.run_id || "-");
  const modeLabel = String(state.mode || "-");
  setCompactTextWithTitle(planningStageLabel, `S:${stageLabel}`, `Stage: ${stageLabel}`);
  setCompactTextWithTitle(
    planningRunDetail,
    `${compactRunId(runId)} · ${modeLabel} · ${running ? "on" : "idle"}`,
    `run=${runId} mode=${modeLabel} running=${running}`
  );
  renderSpecSummary(state);
  renderPlanningMessages(liveLastSession.messages || []);
  renderLiveRuntime(liveLastSession);
}

async function refreshLiveGraphPayload() {
  try {
    const graphRes = await fetch("/api/graphs/atr_closed_loop");
    if (graphRes.ok) {
      liveGraphPayload = await graphRes.json();
    }
  } catch (err) {
    // Keep the last known graph if a transient refresh fails.
  }
  return liveGraphPayload;
}

async function refreshPlanningState(options = {}) {
  if (liveRefreshInFlight) return liveRefreshInFlight;
  const background = Boolean(options.background);
  markLiveSyncRefreshStart();
  liveRefreshInFlight = (async () => {
    try {
      const sessionId = encodeURIComponent(ensurePlanningSessionId());
      const [sessionRes, snapshotRes, eventsRes] = await Promise.all([
        fetch(`/api/planning/session?session_id=${sessionId}`),
        fetch("/api/state"),
        fetch("/api/events/recent"),
      ]);
      if (!sessionRes.ok) throw new Error(`session HTTP ${sessionRes.status}`);
      const session = await sessionRes.json();
      liveLastSnapshot = snapshotRes.ok ? await snapshotRes.json() : {};
      const recentPayload = eventsRes.ok ? await eventsRes.json() : { events: [] };
      await refreshLiveGraphPayload();
      liveRecentEvents = Array.isArray(recentPayload.events) ? recentPayload.events : [];
      markLiveSyncComplete();
      if (!session.state && liveLastSnapshot.state) session.state = liveLastSnapshot.state;
      if (!session.runtime && liveLastSnapshot.runtime) session.runtime = liveLastSnapshot.runtime;
      applyPlanningSession(session);
      await refreshLiveRunDetails(session);
      return session;
    } catch (err) {
      markLiveSyncError(err);
      if (!background) throw err;
      return liveLastSession;
    } finally {
      liveRefreshInFlight = null;
    }
  })();
  return liveRefreshInFlight;
}

function schedulePlanningRefresh() {
  if (planningRefreshTimer) return;
  planningRefreshTimer = window.setTimeout(async () => {
    planningRefreshTimer = null;
    try {
      await refreshPlanningState({ background: true });
    } catch (err) {
      setChatStatus("SYNC ERROR", "warning");
    }
  }, 300);
}

async function sendPlanningMessage(message) {
  const clean = String(message || "").trim();
  if (!clean) return;
  if (planningThinkingCount > 0 || liveBackendPlanningBusy) {
    setChatStatus("BUSY", "running");
    return;
  }
  if (planningMessageInput) planningMessageInput.value = "";

  const baseMessages = [...planningMessagesCache];
  const pendingRole = planningPendingSpecimenInput ? "printer_ai" : "orchestrator";
  const pendingModel = planningPendingSpecimenInput ? "specimen_agent" : "orchestrator_plan";
  setChatStatus("REASONING", "running");
  pushPlanningThinking();
  renderPlanningMessages([
    ...baseMessages,
    {
      role: "operator",
      content: clean,
    },
    {
      role: pendingRole,
      content: "",
      pendingReasoning: true,
      model: pendingModel,
    },
  ]);

  try {
    const res = await fetch("/api/planning/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPlanningPayload(clean)),
    });
    const data = await res.json();
    applyPlanningSession(data.session || {});
    setChatStatus(data.ok ? "READY" : "ERROR", data.ok ? "idle" : "warning");
  } catch (err) {
    try {
      await refreshPlanningState();
      setChatStatus("READY", "idle");
    } catch (refreshErr) {
      setChatStatus("ERROR", "warning");
      renderPlanningMessages([
        ...baseMessages,
        {
          role: "operator",
          content: clean,
        },
        {
          role: "system",
          content: `Live GUI request failed: ${err}`,
        },
      ]);
    }
  } finally {
    popPlanningThinking();
  }
}

function collectPlanningContextPayload() {
  return {
    goal: planningGoalInput ? planningGoalInput.value : queryGoal,
    backend: queryBackend,
    session_id: ensurePlanningSessionId(),
    constraints: collectOptionalConstraints(),
  };
}

async function bootstrapLiveOrchestrator() {
  const params = new URLSearchParams(window.location.search);
  const shouldAutoStart = params.get("auto") === "1" || params.get("fresh") === "1";
  if (planningBootstrapStarted || !shouldAutoStart) return;
  planningBootstrapStarted = true;

  const baseMessages = [...planningMessagesCache];
  setChatStatus("REASONING", "running");
  pushPlanningThinking();
  renderPlanningMessages([
    ...baseMessages,
    {
      role: "orchestrator",
      content: "",
      pendingReasoning: true,
      model: "orchestrator_plan",
    },
  ]);

  try {
    const res = await fetch("/api/planning/bootstrap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPlanningContextPayload()),
    });
    const data = await res.json();
    applyPlanningSession(data.session || {});
    setChatStatus(data.ok ? "READY" : "ERROR", data.ok ? "idle" : "warning");
  } catch (err) {
    setChatStatus("ERROR", "warning");
    renderPlanningMessages([
      ...baseMessages,
      {
        role: "system",
        content: `Live GUI bootstrap failed: ${err}`,
      },
    ]);
  } finally {
    popPlanningThinking();
  }
}

function connectPlanningEventStream() {
  if (!window.EventSource) {
    markLiveStreamState("unsupported");
    return;
  }
  markLiveStreamState("connecting");
  const source = new EventSource("/api/events/stream");
  source.onopen = () => {
    markLiveStreamState("live");
  };
  source.addEventListener("update", (event) => {
    try {
      const data = JSON.parse(event.data || "{}");
      const eventType = String(data.event_type || data.type || "");
      const eventTime = data.ts || data.timestamp || new Date().toISOString();
      markLiveStreamState("live", eventTime);
      if (eventType) {
        liveRecentEvents.push(data);
        liveRecentEvents = liveRecentEvents.slice(-160);
      }
      if (eventType.startsWith("planning_") || eventType === "planning_message" || eventType.startsWith("approval.") || eventType.includes("agent") || eventType.includes("run") || eventType.includes("device") || eventType.includes("evolution")) {
        schedulePlanningRefresh();
      } else {
        renderLiveRuntime(liveLastSession);
      }
    } catch (err) {
      markLiveStreamState("error");
      setChatStatus("ERROR", "warning");
    }
  });
  source.onerror = () => {
    markLiveStreamState("error");
    setChatStatus("STREAM", "warning");
  };
}


function closeBinderContextMenu() {
}

function openBinderContextMenu(agentId, x, y) {
  void agentId; void x; void y;
}

function graphNodeIdForAgent(agentId) {
  const graph = (liveGraphPayload && liveGraphPayload.graph) || liveGraphPayload || {};
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const node = nodes.find((item) => agentIdFromStage(item.stage || item.id) === agentId) || nodes.find((item) => item.id === agentId);
  return node ? node.id : "";
}

function recordLiveContextAction(action, agentId, payload = {}) {
  return recordLiveOperatorEvent(
    action,
    `${liveAgentLabel(agentId || liveSelectedAgent)} context action: ${action}`,
    { ...payload, context_action: action, context_agent: agentId || liveSelectedAgent },
    "operator.context"
  );
}

function handleContextAction(action, agentId) {
  liveSelectedAgent = agentId || liveSelectedAgent;
  setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));
  closeBinderContextMenu();
  recordLiveContextAction(action, liveSelectedAgent).catch(() => {});
  if (action === "open_report") {
    setLiveView("report");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "open_backend" || action === "show_tool_calls") {
    setLiveView("backend");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "show_artifacts") {
    setLiveView("artifacts");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "open_graph") {
    liveSelectedGraphNodeId = graphNodeIdForAgent(liveSelectedAgent) || liveSelectedGraphNodeId;
    setLiveView("graph");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "open_evolution") {
    openEvolutionLab(liveSelectedAgent);
    return;
  }
  if (action === "mark_read") {
    markLiveAgentRead(liveSelectedAgent, liveLastSession);
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "run_node_test" || action === "rerun_from_here") {
    blockLiveExecutionForPendingApproval(action, `${liveAgentLabel(liveSelectedAgent)} context node test`, { source_action: `context.${action}`, target_agent: liveSelectedAgent, target_node_id: graphNodeIdForAgent(liveSelectedAgent) || liveSelectedAgent })
      .then((blocked) => {
        if (blocked) return;
        recordLiveIntentEvent("node_rerun_requested", action, `${liveAgentLabel(liveSelectedAgent)} node test requested from binder context.`, { source_action: `context.${action}`, target_agent: liveSelectedAgent, target_node_id: graphNodeIdForAgent(liveSelectedAgent) || liveSelectedAgent }).catch(() => {});
        runSelectedNodeTest(liveLastSession.state || {}).catch((err) => setChatStatus(`NODE TEST ERROR: ${err}`, "warning"));
      })
      .catch((err) => setChatStatus(`NODE TEST ERROR: ${err}`, "warning"));
  }
}


async function pinAgentReportFromBinder(agentId) {
  if (!knownLiveAgent(agentId)) return;
  liveSelectedAgent = agentId;
  markLiveAgentRead(liveSelectedAgent, liveLastSession);
  setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));
  const finding = pinSelectedFinding();
  setChatStatus(`PINNED ${liveAgentShort(liveSelectedAgent)}`, "idle");
  await recordLiveOperatorEvent(
    "report_pinned",
    `${liveAgentLabel(liveSelectedAgent)} report pinned from Agent Binder.`,
    { pinned_finding: finding, pinned_at: finding.pinned_at, source_action: "binder.ctrl_click" },
    "operator.binder"
  );
}

if (liveAgentBinderList) {
  liveAgentBinderList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-agent-id]");
    if (!button) return;
    liveSelectedAgent = button.dataset.agentId || "orchestrator";
    markLiveAgentRead(liveSelectedAgent, liveLastSession);
    setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      pinAgentReportFromBinder(liveSelectedAgent).catch((err) => {
        setChatStatus("PIN ERROR", "warning");
        appendLiveRuntimeEvent({
          event_type: "operator.binder.report_pin_failed",
          level: "ERROR",
          node_id: liveSelectedAgent || "orchestrator",
          message: `Binder report pin failed: ${String(err)}`,
          payload: { source_action: "binder.ctrl_click", error: String(err) },
        });
      });
      return;
    }
    setLiveView("report");
    renderLiveRuntime(liveLastSession);
  });
  liveAgentBinderList.addEventListener("dblclick", (event) => {
    const button = event.target.closest("[data-agent-id]");
    if (!button) return;
    liveSelectedAgent = button.dataset.agentId || "orchestrator";
    markLiveAgentRead(liveSelectedAgent, liveLastSession);
    setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));
    setLiveView("backend");
    renderLiveRuntime(liveLastSession);
  });
}

if (liveChatTarget) {
  liveChatTarget.addEventListener("change", () => {
    const target = liveChatTarget.value || "selected_agent";
    if (knownLiveAgent(target)) {
      liveSelectedAgent = target;
      markLiveAgentRead(liveSelectedAgent, liveLastSession);
    }
    renderLiveChatContextStrip();
    renderLiveRuntime(liveLastSession);
  });
}

if (btnLiveBottomCollapse) {
  btnLiveBottomCollapse.addEventListener("click", () => {
    setLiveBottomCollapsed(!liveBottomCollapsed);
  });
}

liveViewTabs.forEach((button) => {
  button.addEventListener("click", () => {
    setLiveView(button.dataset.liveView || "report");
    renderLiveRuntime(liveLastSession);
  });
});

if (liveChatMode) {
  liveChatMode.addEventListener("change", () => {
    renderLiveChatContextStrip();
    persistLiveUiState();
  });
}

liveTimelineFilters.forEach((button) => {
  button.addEventListener("click", () => {
    liveTimelineFilter = LIVE_TIMELINE_FILTER_IDS.has(button.dataset.timelineFilter) ? button.dataset.timelineFilter : "all";
    renderTimelinePanels();
    persistLiveUiState();
  });
});

const LIVE_NODE_TEST_MODULES = new Set(["design", "specimen", "vision", "manipulation", "equipment", "analysis", "knowledge", "bo", "guardian"]);
const LIVE_BUSY_QUICK_ACTIONS = new Set(["pause_run", "resume_run", "dry_run", "run_node_test", "explain_current_node"]);

function firstPendingApproval() {
  const pending = liveApprovals && Array.isArray(liveApprovals.pending) ? liveApprovals.pending : [];
  return pending[0] || null;
}

function normalizedLiveApprovals(value = liveApprovals) {
  const approvals = value && typeof value === "object" ? value : {};
  const resolved = Array.isArray(approvals.resolved) ? approvals.resolved : [];
  for (const item of resolved) {
    const approvalId = String((item && item.approval_id) || "");
    if (approvalId) liveResolvedApprovalIds.add(approvalId);
  }
  const pending = Array.isArray(approvals.pending) ? approvals.pending : [];
  return {
    approvals: Array.isArray(approvals.approvals) ? approvals.approvals : [],
    pending: pending.filter((item) => !liveResolvedApprovalIds.has(String((item && item.approval_id) || ""))),
    resolved,
  };
}

async function blockLiveExecutionForPendingApproval(action, label, payload = {}) {
  const pending = firstPendingApproval();
  if (!pending) return false;
  const approvalId = pending.approval_id || "";
  const reason = pending.reason || pending.title || pending.stage || "Operator approval required.";
  setChatStatus("APPROVAL REQUIRED", "warning", `${label} blocked until approval is resolved: ${reason}`);
  await recordLiveIntentEvent(
    "approval.blocked_execution",
    action,
    `${label} blocked because operator approval is pending.`,
    {
      ...payload,
      blocked_action: action,
      blocked_label: label,
      pending_approval_id: approvalId,
      pending_approval_title: pending.title || "",
      pending_approval_stage: pending.stage || "",
      pending_approval_reason: reason,
      requires_operator_approval: true,
    }
  );
  return true;
}

function draftRuntimeChat(text, mode = "command") {
  if (liveChatMode) liveChatMode.value = mode;
  if (planningMessageInput) {
    planningMessageInput.value = text;
    planningMessageInput.focus();
  }
}

function appendLiveRuntimeEvent(event) {
  liveRunEvents.push({ ts: new Date().toISOString(), ...event });
  liveRunEvents = liveRunEvents.slice(-160);
  syncOperatorReportStateFromEvents({ preserveLocal: true });
  renderLiveRuntime(liveLastSession);
}

async function runSelectedNodeTest(state) {
  const selected = liveSelectedAgent || agentIdFromStage(state.stage || "") || "orchestrator";
  if (await blockLiveExecutionForPendingApproval("run_node_test", `${liveAgentLabel(selected)} node test`, { target_agent: selected, target_node_id: graphNodeIdForAgent(selected) || selected })) return;
  setChatStatus("NODE TEST", "running");
  let data;
  if (LIVE_NODE_TEST_MODULES.has(selected)) {
    const res = await fetch(`/api/modules/${encodeURIComponent(selected)}/dry-run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    data = await res.json();
    await recordLiveIntentEvent(
      "module.node_test",
      "module_node_test_result",
      data.ok ? `Node test ok: ${selected} / ${((data.sequence || []).length)} steps` : `Node test failed: ${(data.errors || []).join(", ")}`,
      { target_agent: selected, target_node_id: selected, result: data }
    );
  } else {
    const res = await fetch("/api/graphs/atr_closed_loop/dry-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_stage: state.stage || "idle", max_steps: 6 }),
    });
    data = await res.json();
    await recordLiveIntentEvent(
      "graph.node_test",
      "graph_node_test_result",
      data.ok ? `Graph node test ok: ${((data.sequence || []).length)} steps` : `Graph node test failed: ${(data.errors || []).join(", ")}`,
      { target_agent: selected, target_node_id: selected, result: data }
    );
  }
  setChatStatus(data && data.ok ? "READY" : "ERROR", data && data.ok ? "idle" : "warning");
}

async function runLiveQuickAction(action) {
  const state = liveLastSession.state || {};
  const pending = firstPendingApproval();
  if (action === "open_backend") {
    setLiveView("backend");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "open_graph") {
    setLiveView("graph");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "open_evolution") {
    openEvolutionLab(liveSelectedAgent);
    return;
  }
  if (action === "approve_next_step") {
    if (pending && state.run_id) {
      await resolveLiveApproval(state.run_id, pending.approval_id, "approved");
      return;
    }
    draftRuntimeChat("현재 선택된 단계의 다음 진행 조건, 승인 필요 여부, 안전 리스크를 검토해줘.", "approval");
    return;
  }
  if (action === "reject_next_step") {
    if (pending && state.run_id) {
      await resolveLiveApproval(state.run_id, pending.approval_id, "rejected");
      return;
    }
    draftRuntimeChat("현재 선택된 단계 진행을 보류하고 대체 경로와 필요한 추가 입력을 제시해줘.", "approval");
    return;
  }
  if (action === "revise") {
    if (pending && state.run_id) {
      await resolveLiveApproval(state.run_id, pending.approval_id, "cancelled");
      return;
    }
    draftRuntimeChat(`${liveAgentLabel(liveSelectedAgent)}의 현재 보고서/계획을 다음 조건으로 수정해줘: `, "edit_report");
    return;
  }
  if (action === "rewrite_report_section") {
    const section = selectedReportSectionLabel();
    const sectionText = selectedReportSectionText(900);
    const prompt = `${liveAgentLabel(liveSelectedAgent)} 보고서의 [${section}] 섹션을 현재 runtime evidence 기준으로 더 명확하게 다시 작성해줘.${sectionText ? `

현재 섹션 내용:
${sectionText}` : ""}`;
    draftRuntimeChat(prompt, "edit_report");
    await recordLiveIntentEvent("report_rewrite_requested", "rewrite_report_section", `${liveAgentLabel(liveSelectedAgent)} report section rewrite requested.`, { rewrite_scope: "selected_report_section", draft_prompt: compactText(prompt, 1200), ...selectedReportSectionPayload(1200) });
    renderLiveChatContextStrip();
    persistLiveUiState();
    return;
  }
  if (action === "safe_stop") {
    if (btnLiveSafeStop) btnLiveSafeStop.click();
    return;
  }
  if (action === "pause_run") {
    setChatStatus("PAUSE", "warning");
    await recordLiveIntentEvent("runtime_command_requested", "pause_run", "Live GUI pause command requested.", { command: "pause_run" });
    const endpoint = state.run_id ? `/api/runs/${encodeURIComponent(state.run_id)}/pause` : "/api/run/pause";
    await fetchJsonOrThrow(endpoint, { method: "POST" });
    await refreshPlanningState();
    setChatStatus("PAUSED", "warning");
    return;
  }
  if (action === "resume_run") {
    setChatStatus("RESUME", "running");
    await recordLiveIntentEvent("runtime_command_requested", "resume_run", "Live GUI resume command requested.", { command: "resume_run" });
    const endpoint = state.run_id ? `/api/runs/${encodeURIComponent(state.run_id)}/resume` : "/api/run/resume";
    await fetchJsonOrThrow(endpoint, { method: "POST" });
    await refreshPlanningState();
    setChatStatus("READY", "idle");
    return;
  }
  if (action === "dry_run") {
    setLiveView("graph");
    setChatStatus("DRY RUN", "running");
    const dryRunPayload = { start_stage: state.stage || "idle", max_steps: 12 };
    await recordLiveIntentEvent("runtime_command_requested", "dry_run", "Live GUI graph dry-run command requested.", { command: "graph_dry_run", graph_id: "atr_closed_loop", ...dryRunPayload });
    try {
      const res = await fetch("/api/graphs/atr_closed_loop/dry-run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(dryRunPayload) });
      const data = await res.json();
      await recordLiveIntentEvent(
        "graph.dry_run",
        "graph_dry_run_result",
        data.ok ? `Dry-run ok: ${(data.sequence || []).length} steps` : `Dry-run failed: ${(data.errors || []).join(", ")}`,
        { command: "graph_dry_run", graph_id: "atr_closed_loop", result: data }
      );
      setChatStatus(data.ok ? "READY" : "ERROR", data.ok ? "idle" : "warning");
    } catch (err) {
      await recordLiveIntentEvent("graph.dry_run", "graph_dry_run_failed", String(err), { command: "graph_dry_run", graph_id: "atr_closed_loop", error: String(err) }).catch(() => {});
      setChatStatus("ERROR", "warning");
    }
    return;
  }
  if (action === "run_node_test") {
    if (await blockLiveExecutionForPendingApproval("run_node_test", `${liveAgentLabel(liveSelectedAgent)} Runtime Chat node test`, { source_action: "quick.run_node_test", target_agent: liveSelectedAgent, target_node_id: graphNodeIdForAgent(liveSelectedAgent) || liveSelectedAgent })) return;
    await recordLiveIntentEvent("node_rerun_requested", "run_node_test", `${liveAgentLabel(liveSelectedAgent)} node test requested from Runtime Chat.`, { source_action: "quick.run_node_test", target_agent: liveSelectedAgent, target_node_id: graphNodeIdForAgent(liveSelectedAgent) || liveSelectedAgent });
    await runSelectedNodeTest(state);
    return;
  }
  if (action === "explain_current_node") {
    const selected = liveAgentLabel(liveSelectedAgent);
    const stage = state.stage || "idle";
    sendPlanningMessage(`현재 Live GUI에서 선택된 ${selected}와 runtime stage=${stage}의 역할, 최근 backend trace, 다음 handoff를 간단히 설명해줘.`);
  }
}

async function runSelectedEventAction(action) {
  const event = selectedTimelineEvent();
  if (!event) return;
  const agentId = agentIdFromEvent(event);
  liveSelectedAgent = agentId || liveSelectedAgent;
  setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));
  const payload = eventPayload(event);
  await recordLiveOperatorEvent(
    action,
    `${liveAgentLabel(liveSelectedAgent)} timeline action: ${action}`,
    {
      timeline_action: action,
      timeline_event_id: event.event_id || event.id || payload.event_id || "",
      timeline_event_type: event.event_type || event.type || "",
      timeline_trace_id: event.trace_id || payload.trace_id || "",
    },
    "operator.timeline"
  );
  if (action === "open_backend") {
    setLiveView("backend");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "open_report") {
    setLiveView("report");
    renderLiveRuntime(liveLastSession);
    return;
  }
  if (action === "ask_chat") {
    draftRuntimeChat(`선택한 runtime trace event를 기준으로 원인, 영향, 다음 조치를 설명해줘. trace_id=${event.trace_id || payload.trace_id || "-"}, event=${event.event_type || event.type || "event"}, agent=${agentId}`, "ask");
    return;
  }
  if (action === "replay_prep") {
    if (await blockLiveExecutionForPendingApproval("timeline.replay_prep", `${liveAgentLabel(liveSelectedAgent)} timeline replay prep`, { source_action: "timeline.replay_prep", target_agent: liveSelectedAgent, target_event_key: liveSelectedEventKey })) return;
    await runSelectedNodeTest(liveLastSession.state || {});
    return;
  }
  if (action === "copy_trace") {
    const text = JSON.stringify(event, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      setChatStatus("TRACE COPIED", "idle");
    } catch (err) {
      downloadTextFile(`${event.event_id || event.trace_id || "selected_event"}.json`, text);
      setChatStatus("TRACE EXPORTED", "idle");
    }
  }
}

function selectTimelineEventByKey(key, fallbackAgent = "") {
  liveSelectedEventKey = key || liveSelectedEventKey;
  const event = selectedTimelineEvent();
  liveSelectedAgent = fallbackAgent || (event ? agentIdFromEvent(event) : liveSelectedAgent);
  if (event) {
    const graphNodeId = graphNodeIdForAgent(liveSelectedAgent);
    if (graphNodeId) {
      liveSelectedGraphNodeId = graphNodeId;
      liveGraphSelectionCleared = false;
    }
    setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));
  } else if (liveChatTarget && !validLiveChatTarget(liveChatTarget.value)) {
    setLiveChatTargetMode("selected_agent");
  }
  persistLiveUiState();
}

function clearLiveGraphSelection() {
  liveSelectedGraphNodeId = "";
  liveGraphSelectionCleared = true;
  persistLiveUiState();
  renderLiveRuntime(liveLastSession);
}

function clearLiveTimelineSelection() {
  liveSelectedEventKey = "";
  persistLiveUiState();
  renderLiveRuntime(liveLastSession);
}


syncLiveTooltipAttributes();
if (document.body) {
  liveTooltipMutationObserver.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["title"] });
}

document.addEventListener("mouseover", (event) => showLiveHoverTooltip(event.target));
document.addEventListener("focusin", (event) => showLiveHoverTooltip(event.target));
document.addEventListener("mouseout", (event) => {
  const element = liveTooltipTarget(event.target);
  if (element && (!event.relatedTarget || !element.contains(event.relatedTarget))) hideLiveHoverTooltip();
});
document.addEventListener("focusout", (event) => {
  const element = liveTooltipTarget(event.target);
  if (element && (!event.relatedTarget || !element.contains(event.relatedTarget))) hideLiveHoverTooltip();
});
document.addEventListener("keydown", (event) => {
  const section = event.target.closest && event.target.closest(".live-report-section[data-report-section-title]");
  if (section && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    selectLiveReportSection(section.dataset.reportSectionTitle || "");
    return;
  }
  const deviceCard = event.target.closest && event.target.closest(".live-device-card[data-device-event-key]");
  if (deviceCard && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    focusDeviceEventFromCard(deviceCard).catch((err) => setChatStatus(`DEVICE TRACE ERROR: ${err}`, "warning"));
    return;
  }
  runLiveKeyboardShortcut(event);
});

if (btnLiveShortcutsClose) {
  btnLiveShortcutsClose.addEventListener("click", () => toggleLiveShortcutOverlay(false));
}

document.addEventListener("click", (event) => {
  const boToggle = event.target.closest(".bo-graph-toggle[data-bo-card-key]");
  if (boToggle) {
    closeBinderContextMenu();
    const key = boToggle.dataset.boCardKey || "";
    if (key) {
      if (liveExpandedBoCards.has(key)) liveExpandedBoCards.delete(key);
      else liveExpandedBoCards.add(key);
      saveExpandedBoCards();
      renderPlanningMessages(planningMessagesCache);
      if (liveLastSession) renderLiveRuntime(liveLastSession);
    }
    return;
  }
  const questionButton = event.target.closest(".live-question-action[data-question-action]");
  if (questionButton) {
    closeBinderContextMenu();
    handleQuestionAction(questionButton.dataset.questionAction || "", questionButton.dataset.questionKey || "");
    return;
  }
  const faultButton = event.target.closest(".live-fault-action[data-fault-action]");
  if (faultButton) {
    closeBinderContextMenu();
    handleFaultAction(faultButton.dataset.faultAction || "", faultButton.dataset.faultKey || "");
    return;
  }
  const selectedEventButton = event.target.closest(".live-selected-event-action[data-event-action]");
  if (selectedEventButton) {
    closeBinderContextMenu();
    runSelectedEventAction(selectedEventButton.dataset.eventAction || "").catch((err) => {
      setChatStatus("EVENT ACTION ERROR", "warning");
      renderPlanningMessages([...planningMessagesCache, { role: "system", content: `Selected event action failed: ${err}` }]);
    });
    return;
  }
  const pinnedFindingButton = event.target.closest(".live-pinned-finding-action[data-pinned-index]");
  if (pinnedFindingButton) {
    const index = Number(pinnedFindingButton.dataset.pinnedIndex || 0);
    const item = Number.isFinite(index) ? livePinnedFindings[index] : null;
    focusPinnedFinding(item).catch((err) => setChatStatus(`PINNED FOCUS ERROR: ${err}`, "warning"));
    return;
  }
  const deviceCard = event.target.closest(".live-device-card[data-device-event-key]");
  if (deviceCard) {
    closeBinderContextMenu();
    focusDeviceEventFromCard(deviceCard).catch((err) => setChatStatus(`DEVICE TRACE ERROR: ${err}`, "warning"));
    return;
  }
  const quickButton = event.target.closest(".live-quick-action[data-quick-action]");
  if (quickButton) {
    closeBinderContextMenu();
    const action = quickButton.dataset.quickAction || "";
    const useBusyLock = LIVE_BUSY_QUICK_ACTIONS.has(action);
    if (liveQuickActionBusy && action !== "safe_stop") return;
    if (useBusyLock) setLiveQuickActionBusy(true);
    runLiveQuickAction(action).catch((err) => {
      setChatStatus("ERROR", "warning");
      renderPlanningMessages([...planningMessagesCache, { role: "system", content: `Quick action failed: ${err}` }]);
    }).finally(() => {
      if (useBusyLock) setLiveQuickActionBusy(false);
    });
    return;
  }
  const reportButton = event.target.closest(".live-report-action[data-report-action]");
  if (reportButton) {
    closeBinderContextMenu();
    runLiveReportAction(reportButton.dataset.reportAction || "").catch((err) => {
      setChatStatus("REPORT ACTION ERROR", "warning");
      appendLiveRuntimeEvent({
        event_type: "operator.report.action_failed",
        level: "ERROR",
        node_id: liveSelectedAgent || "orchestrator",
        message: `Report action failed: ${String(err)}`,
        payload: { action: reportButton.dataset.reportAction || "", error: String(err) },
      });
    });
    return;
  }
  const reportSection = event.target.closest(".live-report-section[data-report-section-title]");
  if (reportSection && !event.target.closest("button, a, input, select, textarea")) {
    closeBinderContextMenu();
    selectLiveReportSection(reportSection.dataset.reportSectionTitle || "");
    return;
  }
  const graphActionButton = event.target.closest(".live-graph-action[data-graph-action]");
  if (graphActionButton) {
    closeBinderContextMenu();
    graphActionButton.disabled = true;
    runLiveGraphGateAction(graphActionButton.dataset.graphAction || "").catch((err) => {
      setChatStatus("GRAPH ERROR", "warning");
      appendLiveRuntimeEvent({
        event_type: "graph_gate_failed",
        level: "ERROR",
        node_id: liveSelectedAgent || "orchestrator",
        message: `Graph action failed: ${String(err)}`,
        payload: { action: graphActionButton.dataset.graphAction || "", error: String(err) },
      });
    }).finally(() => {
      graphActionButton.disabled = false;
    });
    return;
  }
  const contextButton = event.target.closest(".live-context-action[data-context-action]");
  if (contextButton) {
    handleContextAction(contextButton.dataset.contextAction || "", contextButton.dataset.agentId || liveSelectedAgent);
    return;
  }
  const graphNode = event.target.closest(".live-graph-mini-node[data-agent-id]");
  if (graphNode) {
    liveSelectedAgent = graphNode.dataset.agentId || liveSelectedAgent;
    liveSelectedGraphNodeId = graphNode.dataset.graphNodeId || liveSelectedGraphNodeId;
    liveGraphSelectionCleared = false;
    setLiveChatTargetMode(liveChatTargetForAgent(liveSelectedAgent));
    setLiveView("graph");
    renderLiveRuntime(liveLastSession);
    return;
  }
  const graphCanvas = event.target.closest(".live-graph-mini-canvas");
  if (graphCanvas && !event.target.closest(".live-graph-mini-node, .live-graph-action, button, a, input, select, textarea")) {
    closeBinderContextMenu();
    clearLiveGraphSelection();
    return;
  }
  const timelineBlankArea = event.target.closest("#live-timeline-strip, .live-timeline-detail");
  if (timelineBlankArea && !event.target.closest(".live-timeline-item, .live-timeline-detail-item, .live-selected-event-card, .live-selected-event-action, button, a, input, select, textarea")) {
    closeBinderContextMenu();
    clearLiveTimelineSelection();
    return;
  }
  const backendButton = event.target.closest(".live-open-backend");
  if (backendButton) {
    setLiveView("backend");
    renderLiveRuntime(liveLastSession);
    return;
  }
  const approvalButton = event.target.closest(".live-approval-action");
  if (approvalButton) {
    resolveLiveApproval(approvalButton.dataset.runId, approvalButton.dataset.approvalId, approvalButton.dataset.decision).catch((err) => {
      setChatStatus("ERROR", "warning");
      renderPlanningMessages([
        ...planningMessagesCache,
        { role: "system", content: `Approval resolve failed: ${err}` },
      ]);
    });
    return;
  }
  const timelineButton = event.target.closest(".live-timeline-item[data-agent-id]");
  if (timelineButton) {
    selectTimelineEventByKey(timelineButton.dataset.eventKey || "", timelineButton.dataset.agentId || "");
    setLiveView("backend");
    renderLiveRuntime(liveLastSession);
  }
});

async function confirmOrRequestLiveSafeStop() {
  const now = Date.now();
  if (!liveSafeStopArmedUntil || now > liveSafeStopArmedUntil) {
    armLiveSafeStop();
    return;
  }
  resetLiveSafeStopArm();
  try {
    setChatStatus("SAFE STOP", "warning");
    await recordLiveIntentEvent("runtime_command_requested", "safe_stop", "Live GUI safe-stop command confirmed and requested.", { command: "safe_stop", confirmation: "double_click_within_6s" });
    await fetchJsonOrThrow("/api/run/safe-stop", { method: "POST" });
    await refreshPlanningState();
    setChatStatus("SAFE STOP REQUESTED", "warning");
  } catch (err) {
    appendLiveRuntimeEvent({
      event_type: "run_safe_stop_failed",
      level: "ERROR",
      node_id: liveSelectedAgent || "guardian",
      message: `Safe stop failed: ${String(err)}`,
      payload: { error: String(err) },
    });
    setChatStatus("SAFE STOP ERROR", "warning");
  }
}

document.addEventListener("click", (event) => {
  if (!event.target.closest || !event.target.closest("#btn-live-safe-stop")) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  confirmOrRequestLiveSafeStop().catch((err) => setChatStatus(`SAFE STOP ERROR: ${err}`, "warning"));
}, true);

setInterval(() => {
  tickLiveRuntimeClock();
  updateLiveConnectionChips();
  if (liveSyncIsStale() && !liveRefreshInFlight && planningThinkingCount === 0) {
    refreshPlanningState({ background: true }).catch(() => setChatStatus("SYNC ERROR", "warning"));
  }
}, 1000);
tickLiveRuntimeClock();
updateLiveConnectionChips();

if (btnPlanningRefresh) {
  btnPlanningRefresh.addEventListener("click", refreshPlanningState);
}

if (btnPlanningGenerate) {
  btnPlanningGenerate.addEventListener("click", () => {
    sendPlanningMessage(
      "기존 Project_guide와 현재 runtime contract를 지키면서 실가동 전 실험 설계 계획을 만들어줘. "
        + "시편 디자인 후보, 필요한 experiment_spec 필드, Specimen Making Agent 실행/핸드오프 흐름, Guardian 체크, operator approval 전 금지사항을 정리해줘."
    );
  });
}

if (btnPlanningSend) {
  btnPlanningSend.addEventListener("click", () => {
    sendPlanningMessage(planningMessageInput ? planningMessageInput.value : "");
  });
}

if (planningMessageInput) {
  planningMessageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) {
      event.preventDefault();
      sendPlanningMessage(planningMessageInput.value);
    }
  });
}

applyQueryGoal();
ensurePlanningSessionId();
restoreLiveUiState();
if (planningChatLog && !planningChatLog.dataset.autoScrollObserved) {
  planningChatLog.dataset.autoScrollObserved = "1";
  planningChatAutoScrollObserver.observe(planningChatLog, { childList: true, subtree: false });
}
connectPlanningEventStream();
refreshPlanningState()
  .then(bootstrapLiveOrchestrator)
  .catch(() => setChatStatus("ERROR", "warning"));
