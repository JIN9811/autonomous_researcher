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
let liveGuardianStatus = null;
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
          ["strategy", `${boResult.strategy || "-"} / benchmark=${boResult.benchmark_strategy || "-"}`],
          ["acquisition", boResult.acquisition],
          ["budget", boResult.budget],
          ["trace_steps", trace.length],
          ["latest_candidate", latestSelected.candidate_id],
          ["recommended_candidate", recommendation.candidate_id],
          ["combined_score", recommendation.combined_score],
          ["recommended_score", recommendation.objective_score],
          ["reasoning", boResult.reasoning && boResult.reasoning.operator_summary ? boResult.reasoning.operator_summary : "-"],
        ])}
        ${Array.isArray(boResult.candidate_ranking) && boResult.candidate_ranking.length ? `<div class="bo-candidate-mini-list">${boResult.candidate_ranking.slice(0, 5).map((item) => `<div><strong>${escapeHtml(item.candidate_id || "candidate")}</strong><span>score=${escapeHtml(numberText(item.combined_score, 5))}</span><code>${escapeHtml(compactBoParams(item.parameters || {}))}</code></div>`).join("")}</div>` : ""}
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

function renderEquipmentRuntimeCard(msg) {
  if (msg.role !== "equipment_ai" && msg.model !== "equipment_agent") return "";
  const event = msg.equipment_runtime_event || {};
  const macro = msg.macro_command || {};
  const visual = msg.visual_assertion || {};
  const physical = msg.physical_cross_check || {};
  const data = msg.data_acquisition || {};
  const recovery = msg.recovery || {};
  const hasCard = Object.keys(event).length || Object.keys(macro).length || Object.keys(visual).length || Object.keys(physical).length || Object.keys(data).length || Object.keys(recovery).length || msg.command_id || msg.data_file_ref;
  if (!hasCard) return "";
  return `
    <div class="printer-runtime-card equipment-runtime-card">
      <div class="runtime-card-section">
        <h4>Lab Equipment Runtime Event</h4>
        ${runtimeRows([
          ["message_type", msg.message_type],
          ["tool", msg.tool || event.tool],
          ["command_id", msg.command_id || event.sequence_id],
          ["program_id", msg.program_id || event.program_id],
          ["windows_host", msg.windows_host || event.bridge_host || event.host],
          ["step", event.step],
          ["status", event.status],
        ])}
      </div>
      ${Object.keys(macro).length ? `
        <div class="runtime-card-section">
          <h4>Macro Command</h4>
          ${runtimeRows([
            ["command_id", macro.command_id || msg.command_id],
            ["program_id", macro.program_id || msg.program_id || event.program_id],
            ["target_ui", macro.target_ui],
            ["step", macro.step],
            ["status", macro.status],
            ["detail", macro.detail],
          ])}
        </div>` : ""}
      ${Object.keys(visual).length ? `
        <div class="runtime-card-section">
          <h4>Visual Assertion</h4>
          ${runtimeRows([
            ["checkpoint", visual.checkpoint],
            ["status", visual.status],
            ["ok", visual.ok],
            ["target_ui", visual.target_ui],
            ["confidence", visual.confidence],
            ["screenshot_artifact", visual.screenshot_artifact],
            ["detail", visual.detail],
          ])}
        </div>` : ""}
      ${Object.keys(physical).length ? `
        <div class="runtime-card-section">
          <h4>Physical Cross-Check</h4>
          ${runtimeRows([
            ["status", physical.status],
            ["ok", physical.ok],
            ["check_id", physical.check_id],
            ["target_ui", physical.target_ui],
            ["detail", physical.detail],
          ])}
        </div>` : ""}
      ${Object.keys(data).length || msg.data_file_ref ? `
        <div class="runtime-card-section">
          <h4>Data Acquisition</h4>
          ${runtimeRows([
            ["status", data.status],
            ["artifact_or_path", data.artifact_or_path || msg.data_file_ref],
            ["windows_path", data.windows_path],
            ["linux_path", data.linux_path],
            ["sha256", data.sha256],
            ["row_count_probe", data.row_count_probe],
            ["save_method", data.save_method],
            ["artifact_pull_status", data.artifact_pull_status],
            ["parse_probe", data.parse_probe],
            ["detail", data.detail],
          ])}
        </div>` : ""}
      ${Object.keys(recovery).length ? `
        <div class="runtime-card-section runtime-card-wide">
          <h4>Recovery</h4>
          ${runtimeRows([
            ["status", recovery.status],
            ["failure_step", recovery.failure_step],
            ["failure_code", recovery.failure_code],
            ["failure_detail", recovery.failure_detail],
            ["recommended_action", recovery.recommended_action],
          ])}
        </div>` : ""}
    </div>
  `;
}

function renderSpecimenRuntimeCard(msg) {
  if (msg.role !== "printer_ai" && msg.role !== "specimen_ai") return "";
  const specimen = msg.specimen || {};
  const fabricationReport = specimen.fabrication_report || {};
  const fabricationIntent = fabricationReport.fabrication_intent || {};
  const digitalThread = fabricationReport.digital_thread || {};
  const processPlan = fabricationReport.process_plan || {};
  const fabricationOutcome = fabricationReport.fabrication_outcome || {};
  const qualityGates = Array.isArray(fabricationReport.quality_gates) ? fabricationReport.quality_gates : [];
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
  if (!Object.keys(settings).length && !trace.length && !Object.keys(fabricationReport).length) return "";

  const command = Array.isArray(settings.resolved_command) ? settings.resolved_command.join(" ") : "";
  const gateSummary = qualityGates.length
    ? `${qualityGates.filter((gate) => gate.status === "pass").length}/${qualityGates.length} pass · blocked=${qualityGates.filter((gate) => gate.status === "blocked").length} · fail=${qualityGates.filter((gate) => gate.status === "fail").length}`
    : "-";
  const gateItems = qualityGates.slice(0, 9).map((gate) => `<li>${escapeHtml(gate.gate || "gate")} · <strong>${escapeHtml(gate.status || "unknown")}</strong>${gate.repair ? ` · ${escapeHtml(renderRuntimeValue(gate.repair))}` : ""}</li>`).join("");
  return `
    <div class="printer-runtime-card">
      <div class="runtime-card-section runtime-card-wide">
        <h4>Fabrication Digital Thread</h4>
        ${runtimeRows([
          ["fabrication_schema", fabricationReport.schema],
          ["intent", `${fabricationIntent.mode || "-"} / ${fabricationIntent.printer_path || specimen.printer_path || "-"}`],
          ["physical_intent", fabricationIntent.physical_intent],
          ["specimen_id", digitalThread.specimen_id || specimen.specimen_id],
          ["design_hash", digitalThread.design_hash],
          ["geometry_hash", digitalThread.geometry_hash || specimen.geometry_hash],
          ["stl_path", digitalThread.stl_path || specimen.stl_path],
          ["gcode_path", digitalThread.gcode_path || specimen.sliced_path],
          ["handoff_package", digitalThread.handoff_package_path || specimen.handoff_package_path],
          ["outcome", fabricationOutcome.status],
          ["location", fabricationOutcome.location],
          ["quality_gates", gateSummary],
        ])}
        ${gateItems ? `<ul class="report-list compact">${gateItems}</ul>` : ""}
      </div>
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
      ${renderEquipmentRuntimeCard(msg)}
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
  const guardianStatus = liveGuardianStatusPayload({ state });
  const guardianSummary = guardianStatus && guardianStatus.summary ? guardianStatus.summary : {};
  const guardianKey = guardianStatus
    ? [guardianStatus.status || "", guardianSummary.risk_score || 0, guardianSummary.gate_count || 0, guardianSummary.incident_count || 0, guardianSummary.blocked_action_count || 0, guardianSummary.pending_approval_count || 0].join(":")
    : "no-guardian-status";
  return [runId, stage, liveSelectedAgent, liveRunEvents.length, liveRecentEvents.length, liveRunArtifacts.length, messageCount, approvalCount, guardianKey].join("|");
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

function renderReportList(items, emptyText = "No evidence.", limit = 8) {
  const filtered = (items || []).filter(Boolean);
  const clean = Number.isFinite(limit) && limit > 0 ? filtered.slice(0, limit) : filtered;
  if (!clean.length) return `<p class="hint">${escapeHtml(emptyText)}</p>`;
  const rows = clean.map((item) => `    <li>${escapeHtml(item)}</li>`).join("\n");
  return `<ul class="live-report-list">\n${rows}\n  </ul>`;
}


function normalizeGuardianStatusPayload(payload) {
  return payload && typeof payload === "object" && payload.schema === "guardian_status_report.v1" ? payload : null;
}

function liveGuardianStatusPayload(report = null) {
  const snapshot = liveLastSnapshot || {};
  const state = (report && report.state) || (liveLastSession && liveLastSession.state) || snapshot.state || {};
  return normalizeGuardianStatusPayload(liveGuardianStatus)
    || normalizeGuardianStatusPayload(snapshot.guardian_status)
    || normalizeGuardianStatusPayload(state.guardian_status)
    || normalizeGuardianStatusPayload(report && report.guardian_status)
    || null;
}

function guardianRiskLevel(score) {
  const value = Number(score) || 0;
  if (value >= 0.9) return "critical";
  if (value >= 0.75) return "blocked";
  if (value >= 0.55) return "approval";
  if (value >= 0.35) return "warning";
  return "allow";
}

function renderGuardianRiskMap(status) {
  const risks = Array.isArray(status && status.graph_wide_risk_map) ? status.graph_wide_risk_map : [];
  if (!risks.length) return `<p class="hint">No graph-wide Guardian risk map is available yet.</p>`;
  return `
    <div class="live-guardian-risk-grid">
      ${risks.map((item) => {
        const score = Math.max(0, Math.min(1, Number(item.score) || 0));
        const percent = Math.round(score * 100);
        const level = guardianRiskLevel(score);
        return `
          <article class="live-guardian-risk-card risk-${escapeHtml(level)}">
            <div class="live-guardian-risk-head"><strong>${escapeHtml(item.risk_class || "risk")}</strong><span>${percent}%</span></div>
            <div class="live-guardian-risk-meter" aria-label="${escapeHtml(item.risk_class || "risk")} risk ${percent}%"><span style="width:${percent}%"></span></div>
            <p>${escapeHtml(item.stage || "-")} · ${escapeHtml(item.phase || "-")} · ${escapeHtml(item.decision || "allow")}</p>
            <small>${escapeHtml(item.reason_code || "OK")}</small>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderGuardianApprovalQueue(status) {
  const queue = status && status.approval_queue && typeof status.approval_queue === "object" ? status.approval_queue : {};
  const pending = Array.isArray(queue.pending) ? queue.pending : [];
  const resolved = Array.isArray(queue.resolved) ? queue.resolved : [];
  const runId = status.run_id || liveCurrentRunId();
  const pendingMarkup = pending.slice(-8).reverse().map((item) => `
    <article class="live-guardian-approval-card">
      <strong>${escapeHtml(item.title || item.stage || "Approval required")}</strong>
      <p>${escapeHtml(item.reason || item.reason_code || item.status || "Operator review required.")}</p>
      <div class="button-row">
        <button class="btn primary live-approval-action" data-run-id="${escapeHtml(runId)}" data-approval-id="${escapeHtml(item.approval_id || "")}" data-decision="approved" ${item.approval_id ? "" : "disabled"}>Approve</button>
        <button class="btn live-approval-action" data-run-id="${escapeHtml(runId)}" data-approval-id="${escapeHtml(item.approval_id || "")}" data-decision="cancelled" ${item.approval_id ? "" : "disabled"}>Revise</button>
        <button class="btn warning live-approval-action" data-run-id="${escapeHtml(runId)}" data-approval-id="${escapeHtml(item.approval_id || "")}" data-decision="rejected" ${item.approval_id ? "" : "disabled"}>Reject</button>
      </div>
    </article>
  `).join("");
  const resolvedItems = resolved.slice(-6).reverse().map((item) => `${item.approval_id || "approval"} · ${item.status || item.decision || "resolved"}`);
  return `
    ${pendingMarkup || `<p class="hint">No pending Guardian approval interrupts.</p>`}
    <h5>Resolved Approval History</h5>
    ${renderReportList(resolvedItems, "No resolved approvals recorded.", 6)}
  `;
}

function renderGuardianBlockedActions(status) {
  const blocked = status && status.blocked_actions && typeof status.blocked_actions === "object" ? status.blocked_actions : {};
  const gates = Array.isArray(blocked.gates) ? blocked.gates : [];
  const tools = Array.isArray(blocked.tool_calls) ? blocked.tool_calls : [];
  const hardware = Array.isArray(blocked.hardware_alerts) ? blocked.hardware_alerts : [];
  const gateItems = gates.slice(-10).reverse().map((item) => `${item.stage || "stage"}.${item.phase || "gate"} · ${item.decision || "blocked"} · ${item.reason_code || "-"} · risk=${renderRuntimeValue(item.risk_score)}`);
  const toolItems = tools.slice(-10).reverse().map((item) => `${item.stage || "stage"} · ${item.tool || "tool"} · ${item.status || "failed"} · ${item.failure_code || item.guardian_reason_code || "-"}`);
  const hardwareItems = hardware.slice(-10).reverse().map((item) => `${item.stage || "stage"} · ${item.device_class || "device"}/${item.component || "component"} · ${item.severity || ""} · ${item.failure_code || "-"}`);
  return `
    <h5>Blocked Gate Decisions</h5>
    ${renderReportList(gateItems, "No blocked Guardian gate decisions.", 10)}
    <h5>Blocked Tool Calls</h5>
    ${renderReportList(toolItems, "No blocked tool-call records.", 10)}
    <h5>Hardware Alerts</h5>
    ${renderReportList(hardwareItems, "No blocking hardware alerts.", 10)}
  `;
}

function renderGuardianIncidentLedger(status) {
  const ledger = status && status.incident_ledger && typeof status.incident_ledger === "object" ? status.incident_ledger : {};
  const records = Array.isArray(ledger.records) ? ledger.records : [];
  if (!records.length) return `<p class="hint">No incident or near-miss records have been written for this run.</p>`;
  return records.slice(-10).reverse().map((item) => {
    const incidentId = item.incident_id || item.id || "incident";
    return `
      <article class="live-guardian-incident-card">
        <div><strong>${escapeHtml(incidentId)}</strong><span>${escapeHtml(item.severity || "near_miss")}</span></div>
        <p>${escapeHtml(item.message || item.summary || item.reason_code || "Guardian incident recorded.")}</p>
        <small>${escapeHtml(item.stage || "-")} · ${escapeHtml(item.risk_class || item.component || "-")} · ${escapeHtml(item.corrective_action || item.recommended_action || "No corrective action recorded.")}</small>
        <button class="btn live-guardian-note-action" type="button" data-incident-id="${escapeHtml(incidentId)}" data-reason-code="${escapeHtml(item.reason_code || item.failure_code || "")}">Add Note</button>
      </article>
    `;
  }).join("");
}

function renderGuardianSafetyBudget(status) {
  const budget = status && status.safety_budget && typeof status.safety_budget === "object" ? status.safety_budget : {};
  const items = Array.isArray(budget.items) ? budget.items : [];
  const rows = items.map((item) => {
    const used = renderRuntimeValue(item.used);
    const limit = renderRuntimeValue(item.limit);
    const unit = item.unit || "";
    const pct = Math.round((Number(item.used_ratio) || 0) * 100);
    return `${item.resource || "budget"} · ${used}/${limit} ${unit} · ${pct}% · ${item.status || "within_budget"}`;
  });
  return `
    ${runtimeRows([
      ["schema", budget.schema || "guardian_safety_budget.v1"],
      ["status", budget.status || "within_budget"],
      ["source", budget.source || "runtime"],
    ])}
    ${renderReportList(rows, "No safety budget items have been computed yet.", 10)}
  `;
}

function renderGuardianLiveHeartbeat(status) {
  const deviceData = status && status.device_data_integrity && typeof status.device_data_integrity === "object" ? status.device_data_integrity : {};
  const heartbeats = Array.isArray(deviceData.live_device_heartbeat) ? deviceData.live_device_heartbeat : [];
  const rows = heartbeats.map((item) => `${item.device_id || "device"} · ${item.heartbeat_status || "review"} · ${item.bridge_state || "unknown"} · ${item.last_command || "runtime snapshot"}`);
  return renderReportList(rows, "No device heartbeat rows are available yet.", 12);
}

function renderGuardianSafeStopVerification(status) {
  const safeStop = status && status.safe_stop_verification && typeof status.safe_stop_verification === "object" ? status.safe_stop_verification : {};
  const latestGate = safeStop.latest_gate && typeof safeStop.latest_gate === "object" ? safeStop.latest_gate : {};
  return runtimeRows([
    ["schema", safeStop.schema || "guardian_safe_stop_verification.v1"],
    ["requested", safeStop.requested === undefined ? false : safeStop.requested],
    ["verified", safeStop.verified === undefined ? false : safeStop.verified],
    ["status", safeStop.status || "not_requested"],
    ["verification_basis", safeStop.verification_basis || "none"],
    ["latest_gate", latestGate.gate_id || "-"],
  ]);
}

function renderGuardianEvidenceCompleteness(status) {
  const evidence = status && status.evidence_completeness && typeof status.evidence_completeness === "object" ? status.evidence_completeness : {};
  return runtimeRows([
    ["schema", evidence.schema || "guardian_evidence_completeness.v1"],
    ["status", evidence.status || "missing"],
    ["score", evidence.score ?? "-"],
    ["artifact_ref_count", evidence.artifact_ref_count ?? 0],
    ["provenance_ref_count", evidence.provenance_ref_count ?? 0],
    ["checks", evidence.checks || {}],
  ]);
}

function renderGuardianSelfEvolutionGate(status) {
  const gate = status && status.self_evolution_gate && typeof status.self_evolution_gate === "object" ? status.self_evolution_gate : {};
  const pending = Array.isArray(gate.pending_variants) ? gate.pending_variants : [];
  const active = Array.isArray(gate.active_variants) ? gate.active_variants : [];
  const pendingItems = pending.slice(-8).reverse().map((item) => `${item.variant_id || "variant"} · ${item.target_type || "target"}:${item.target_id || "-"} · ${item.status || "pending"}`);
  const activeItems = active.slice(-8).reverse().map((item) => `${item.variant_id || "variant"} · ${item.target_type || "target"}:${item.target_id || "-"} · ${item.status || "active"}`);
  return `
    ${runtimeRows([
      ["schema", gate.schema || "guardian_self_evolution_gate.v1"],
      ["status", gate.status || "idle"],
      ["variant_count", gate.variant_count ?? 0],
      ["error", gate.error || "-"],
    ])}
    <h5>Pending Variants</h5>
    ${renderReportList(pendingItems, "No self-evolution variants pending Guardian activation gate.", 8)}
    <h5>Active / Next-Run Variants</h5>
    ${renderReportList(activeItems, "No active self-evolution variants recorded.", 8)}
  `;
}

function renderGuardianReportDetails(report) {
  const status = liveGuardianStatusPayload(report);
  if (!status) return `<p class="hint">Guardian status report is not available yet. Refresh the active run state after a run starts.</p>`;
  const summary = status.summary && typeof status.summary === "object" ? status.summary : {};
  const deviceData = status.device_data_integrity && typeof status.device_data_integrity === "object" ? status.device_data_integrity : {};
  const policy = status.policy_version_panel && typeof status.policy_version_panel === "object" ? status.policy_version_panel : {};
  const handoff = status.handoff_packet && typeof status.handoff_packet === "object" ? status.handoff_packet : {};
  const latestDecision = handoff.latest_guardian_decision && typeof handoff.latest_guardian_decision === "object" ? handoff.latest_guardian_decision : {};
  const latestContract = handoff.latest_guardian_contract && typeof handoff.latest_guardian_contract === "object" ? handoff.latest_guardian_contract : {};
  const corrective = Array.isArray(handoff.corrective_actions) ? handoff.corrective_actions : [];
  const correctiveItems = corrective.slice(-8).reverse().map((item) => `${item.action_id || item.action || "corrective_action"} · ${item.status || "open"} · ${item.description || item.message || item.owner || "-"}`);
  return `
    <div class="live-agent-specific-guardian-details">
      <h5>Graph-Wide Risk Map</h5>
      ${renderGuardianRiskMap(status)}
      <h5>Guardian Status Summary</h5>
      ${runtimeRows([
        ["schema", status.schema || "guardian_status_report.v1"],
        ["run_id", status.run_id || "-"],
        ["stage", status.stage || "-"],
        ["status", status.status || "-"],
        ["risk_score", summary.risk_score ?? "-"],
        ["dominant_risks", summary.dominant_risks || []],
        ["gate_count", summary.gate_count ?? "-"],
        ["incident_count", summary.incident_count ?? "-"],
        ["blocked_action_count", summary.blocked_action_count ?? "-"],
        ["pending_approval_count", summary.pending_approval_count ?? "-"],
        ["safety_budget_status", summary.safety_budget_status || "-"],
        ["safe_stop_status", summary.safe_stop_status || "-"],
        ["evidence_completeness_status", summary.evidence_completeness_status || "-"],
        ["self_evolution_gate_status", summary.self_evolution_gate_status || "-"],
        ["latest_decision", latestDecision.decision || "-"],
        ["latest_reason", latestDecision.reason_code || latestContract.failure_code || "-"],
        ["ok_for_next_stage", latestContract.ok_for_next_stage === undefined ? "-" : latestContract.ok_for_next_stage],
        ["ok_for_bo", latestContract.ok_for_bo === undefined ? "-" : latestContract.ok_for_bo],
      ])}
      <h5>Safety Budget</h5>
      ${renderGuardianSafetyBudget(status)}
      <h5>Live Device Heartbeat</h5>
      ${renderGuardianLiveHeartbeat(status)}
      <h5>Safe-Stop Verification</h5>
      ${renderGuardianSafeStopVerification(status)}
      <h5>Evidence Completeness</h5>
      ${renderGuardianEvidenceCompleteness(status)}
      <h5>Self-Evolution Gate</h5>
      ${renderGuardianSelfEvolutionGate(status)}
      <h5>Gate Timeline</h5>
      ${renderReportList((Array.isArray(status.gate_timeline) ? status.gate_timeline : []).slice(-14).reverse().map((item) => `${item.stage || "stage"}.${item.phase || "gate"}${item.tool ? `/${item.tool}` : ""} · ${item.decision || "allow"} · ${item.reason_code || "OK"} · risk=${renderRuntimeValue(item.risk_score)}`), "No Guardian gate timeline recorded.", 14)}
      <h5>Blocked Actions</h5>
      ${renderGuardianBlockedActions(status)}
      <h5>Approval Queue</h5>
      ${renderGuardianApprovalQueue(status)}
      <h5>Incident / Near-Miss Ledger</h5>
      ${renderGuardianIncidentLedger(status)}
      <h5>Policy / Version Panel</h5>
      ${runtimeRows([
        ["guardian_gate_schema", policy.guardian_gate_schema || "-"],
        ["contract_schema", policy.contract_schema || "-"],
        ["decision_schema", policy.decision_schema || "-"],
        ["incident_schema", policy.incident_schema || "-"],
        ["tool_call_schema", policy.tool_call_schema || "-"],
        ["source_doc", policy.source_doc || "-"],
      ])}
      <h5>Device / Data Integrity</h5>
      ${runtimeRows([
        ["device_health", deviceData.device_health || {}],
        ["live_device_heartbeat", deviceData.live_device_heartbeat || []],
        ["hardware_alert_count", deviceData.hardware_alert_count ?? "-"],
        ["tool_call_counts", deviceData.tool_call_counts || {}],
        ["data_related_incident_count", deviceData.data_related_incident_count ?? "-"],
      ])}
      <h5>Corrective Actions</h5>
      ${renderReportList(correctiveItems, "No corrective actions recorded.", 8)}
    </div>
  `;
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
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata) {
    sources.push(metadata);
    if (metadata.last_stage_payload) sources.push(metadata.last_stage_payload);
    if (metadata.last_stage_payload && metadata.last_stage_payload.data) sources.push(metadata.last_stage_payload.data);
    for (const value of Object.values(metadata)) {
      if (value && typeof value === "object" && !Array.isArray(value)) sources.push(value);
    }
  }
  for (const msg of report.messages || []) sources.push(msg);
  for (const event of report.events || []) sources.push(eventPayload(event));
  for (let index = sources.length - 1; index >= 0; index -= 1) {
    const value = backendField(sources[index], keys);
    if (value !== null && value !== undefined && value !== "") return value;
  }
  return null;
}

function latestDesignReport(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  const direct = metadata.design_report;
  if (direct && typeof direct === "object") return direct;
  const designPayload = metadata.design_agent_payload;
  if (designPayload && typeof designPayload === "object" && designPayload.design_report) return designPayload.design_report;
  return latestReportPayload(report, ["design_report", "data.design_report", "latest.design_report"]);
}

function latestSpecimenFabricationReport(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.fabrication_report && typeof metadata.fabrication_report === "object") return metadata.fabrication_report;
  if (metadata.specimen_fabrication_report && typeof metadata.specimen_fabrication_report === "object") return metadata.specimen_fabrication_report;
  const specimen = metadata.specimen_result;
  if (specimen && typeof specimen === "object" && specimen.fabrication_report) return specimen.fabrication_report;
  const payload = metadata.specimen_agent_payload;
  if (payload && typeof payload === "object") {
    if (payload.fabrication_report) return payload.fabrication_report;
    if (payload.specimen_result && payload.specimen_result.fabrication_report) return payload.specimen_result.fabrication_report;
  }
  return latestReportPayload(report, ["fabrication_report", "specimen_result.fabrication_report", "data.fabrication_report", "latest.fabrication_report"]);
}

function latestSpecimenFabricatedPacket(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.specimen_fabricated && typeof metadata.specimen_fabricated === "object") return metadata.specimen_fabricated;
  const specimen = metadata.specimen_result;
  if (specimen && typeof specimen === "object" && specimen.specimen_fabricated) return specimen.specimen_fabricated;
  const payload = metadata.specimen_agent_payload;
  if (payload && typeof payload === "object") {
    if (payload.specimen_fabricated) return payload.specimen_fabricated;
    if (payload.handoff_packet) return payload.handoff_packet;
  }
  return latestReportPayload(report, ["specimen_fabricated", "handoff_packet", "specimen_result.specimen_fabricated"]);
}

function latestVisionReport(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.vision_report && typeof metadata.vision_report === "object") return metadata.vision_report;
  if (metadata.latest_vision_observation && typeof metadata.latest_vision_observation === "object" && metadata.latest_vision_observation.vision_report) return metadata.latest_vision_observation.vision_report;
  if (state.latest_observations && typeof state.latest_observations === "object" && state.latest_observations.vision_report) return state.latest_observations.vision_report;
  const payload = metadata.vision_agent_payload;
  if (payload && typeof payload === "object") {
    if (payload.vision_report) return payload.vision_report;
    if (payload.observation && payload.observation.vision_report) return payload.observation.vision_report;
  }
  return latestReportPayload(report, ["vision_report", "observation.vision_report", "latest_vision_observation.vision_report", "sections.vision_report"]);
}

function latestVisionSignalPacket(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.vision_signal && typeof metadata.vision_signal === "object") return metadata.vision_signal;
  if (metadata.latest_vision_observation && typeof metadata.latest_vision_observation === "object" && metadata.latest_vision_observation.vision_signal) return metadata.latest_vision_observation.vision_signal;
  if (state.latest_observations && typeof state.latest_observations === "object" && state.latest_observations.vision_signal) return state.latest_observations.vision_signal;
  const payload = metadata.vision_agent_payload;
  if (payload && typeof payload === "object") {
    if (payload.vision_signal) return payload.vision_signal;
    if (payload.handoff_packet) return payload.handoff_packet;
  }
  return latestReportPayload(report, ["vision_signal", "handoff_packet", "observation.vision_signal"]);
}

function latestManipulationReport(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.manipulation_report && typeof metadata.manipulation_report === "object") return metadata.manipulation_report;
  const payload = metadata.manipulation_agent_payload;
  if (payload && typeof payload === "object" && payload.manipulation_report) return payload.manipulation_report;
  if (metadata.last_stage_payload && metadata.last_stage_payload.data && metadata.last_stage_payload.data.manipulation_report) return metadata.last_stage_payload.data.manipulation_report;
  return latestReportPayload(report, ["manipulation_report", "data.manipulation_report", "sections.manipulation_report"]);
}

function latestRobotTaskResult(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.robot_task_result && typeof metadata.robot_task_result === "object") return metadata.robot_task_result;
  const payload = metadata.manipulation_agent_payload;
  if (payload && typeof payload === "object") {
    if (payload.robot_task_result) return payload.robot_task_result;
    if (payload.handoff_packet) return payload.handoff_packet;
  }
  if (metadata.last_stage_payload && metadata.last_stage_payload.data) {
    const data = metadata.last_stage_payload.data;
    if (data.robot_task_result) return data.robot_task_result;
    if (data.handoff_packet) return data.handoff_packet;
  }
  return latestReportPayload(report, ["robot_task_result", "handoff_packet", "data.robot_task_result", "sections.robot_task_result"]);
}


function latestEquipmentReport(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.equipment_report && typeof metadata.equipment_report === "object") return metadata.equipment_report;
  const payload = metadata.equipment_agent_payload;
  if (payload && typeof payload === "object" && payload.equipment_report) return payload.equipment_report;
  if (metadata.last_stage_payload && metadata.last_stage_payload.data && metadata.last_stage_payload.data.equipment_report) return metadata.last_stage_payload.data.equipment_report;
  return latestReportPayload(report, ["equipment_report", "data.equipment_report", "sections.equipment_report"]);
}

function latestEquipmentResult(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.equipment_result && typeof metadata.equipment_result === "object") return metadata.equipment_result;
  const payload = metadata.equipment_agent_payload;
  if (payload && typeof payload === "object" && payload.equipment_result) return payload.equipment_result;
  if (metadata.last_stage_payload && metadata.last_stage_payload.data && metadata.last_stage_payload.data.equipment_result) return metadata.last_stage_payload.data.equipment_result;
  return latestReportPayload(report, ["equipment_result", "data.equipment_result"]);
}

function latestUtmDataReadyPacket(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.utm_data_ready && typeof metadata.utm_data_ready === "object") return metadata.utm_data_ready;
  const payload = metadata.equipment_agent_payload;
  if (payload && typeof payload === "object" && payload.utm_data_ready) return payload.utm_data_ready;
  if (metadata.last_stage_payload && metadata.last_stage_payload.data && metadata.last_stage_payload.data.utm_data_ready) return metadata.last_stage_payload.data.utm_data_ready;
  return latestReportPayload(report, ["utm_data_ready", "data.utm_data_ready"]);
}

function latestEquipmentHandoffPacket(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.equipment_handoff && typeof metadata.equipment_handoff === "object") return metadata.equipment_handoff;
  const payload = metadata.equipment_agent_payload;
  if (payload && typeof payload === "object") {
    if (payload.equipment_handoff) return payload.equipment_handoff;
    if (payload.handoff_packet) return payload.handoff_packet;
  }
  if (metadata.last_stage_payload && metadata.last_stage_payload.data) {
    const data = metadata.last_stage_payload.data;
    if (data.equipment_handoff) return data.equipment_handoff;
    if (data.handoff_packet) return data.handoff_packet;
  }
  return latestReportPayload(report, ["equipment_handoff", "handoff_packet", "data.equipment_handoff"]);
}

function latestAnalysisPayload(report) {
  const state = report && report.state ? report.state : {};
  if (state.latest_analysis && typeof state.latest_analysis === "object" && Object.keys(state.latest_analysis).length) return state.latest_analysis;
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.latest_analysis && typeof metadata.latest_analysis === "object") return metadata.latest_analysis;
  const payload = metadata.last_stage_payload && metadata.last_stage_payload.data ? metadata.last_stage_payload.data : {};
  if (payload && typeof payload === "object" && payload.analysis) return payload.analysis;
  return latestReportPayload(report, ["analysis", "data.analysis", "latest_analysis", "sections.analysis"]);
}

function latestAnalysisBoHandoff(report) {
  const analysis = latestAnalysisPayload(report) || {};
  if (analysis.bo_handoff && typeof analysis.bo_handoff === "object") return analysis.bo_handoff;
  return latestReportPayload(report, ["bo_handoff", "data.bo_handoff", "analysis.bo_handoff"]);
}


function latestKnowledgePayload(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  if (metadata.knowledge && typeof metadata.knowledge === "object") return metadata.knowledge;
  const payload = metadata.knowledge_agent_payload;
  if (payload && typeof payload === "object") {
    if (payload.knowledge && typeof payload.knowledge === "object") return payload.knowledge;
    return payload;
  }
  if (metadata.last_stage_payload && metadata.last_stage_payload.data) {
    const data = metadata.last_stage_payload.data;
    if (data.knowledge && typeof data.knowledge === "object") return data.knowledge;
  }
  return latestReportPayload(report, ["knowledge", "data.knowledge", "sections.knowledge"] ) || {};
}

function latestKnowledgeReport(report) {
  const payload = latestKnowledgePayload(report) || {};
  if (payload.knowledge_report && typeof payload.knowledge_report === "object") return payload.knowledge_report;
  return latestReportPayload(report, ["knowledge_report", "sections.knowledge_report", "data.knowledge_report"] ) || {};
}

function latestKnowledgeContext(report) {
  const payload = latestKnowledgePayload(report) || {};
  if (payload.knowledge_context && typeof payload.knowledge_context === "object") return payload.knowledge_context;
  return latestReportPayload(report, ["knowledge_context", "data.knowledge_context"] ) || {};
}

function latestKnowledgeEvolutionProposal(report) {
  const payload = latestKnowledgePayload(report) || {};
  const knowledgeReport = latestKnowledgeReport(report) || {};
  const reportEvolution = knowledgeReport.self_evolution && typeof knowledgeReport.self_evolution === "object" ? knowledgeReport.self_evolution : null;
  const payloadEvolution = payload.evolution_proposal && typeof payload.evolution_proposal === "object" ? payload.evolution_proposal : null;
  const reportPacks = reportEvolution && Array.isArray(reportEvolution.evidence_packs) ? reportEvolution.evidence_packs.length : 0;
  const payloadPacks = payloadEvolution && Array.isArray(payloadEvolution.evidence_packs) ? payloadEvolution.evidence_packs.length : 0;
  if (reportPacks || !payloadPacks) {
    if (reportEvolution) return reportEvolution;
  }
  if (payloadEvolution) return payloadEvolution;
  return latestReportPayload(report, ["evolution_proposal", "self_evolution", "data.evolution_proposal"] ) || {};
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
  const boReasoning = boResult.reasoning || {};
  const boPriorSummary = boResult.prior_summary || {};
  const boCandidateRanking = Array.isArray(boResult.candidate_ranking) ? boResult.candidate_ranking : Array.isArray(boResult.candidate_pool) ? boResult.candidate_pool.slice(0, 5) : [];
  const artifacts = latestReportArtifacts(report);
  const latestTool = report.toolItems && report.toolItems.length ? report.toolItems[report.toolItems.length - 1] : "not recorded";
  const latestWarning = report.warnings && report.warnings.length ? report.warnings[report.warnings.length - 1] : "none recorded";
  const commonRows = [
    ["runtime_status", status],
    ["active_stage", state.stage || "-"],
    ["evidence_events", report.events.length],
    ["latest_tool", latestTool],
  ];
  const designReport = latestDesignReport(report) || {};
  const designObjective = designReport.objective || {};
  const designHypothesis = designReport.hypothesis || {};
  const designGeneration = designReport.candidate_generation || {};
  const designEvaluation = designReport.candidate_evaluation || {};
  const designPrior = designReport.prior_context || {};
  const designHandoff = designReport.handoff_to_specimen || {};
  const specimenFabricationReport = latestSpecimenFabricationReport(report) || {};
  const specimenPacket = latestSpecimenFabricatedPacket(report) || {};
  const specimenIntent = specimenFabricationReport.fabrication_intent || {};
  const specimenThread = specimenFabricationReport.digital_thread || {};
  const specimenPlan = specimenFabricationReport.process_plan || {};
  const specimenOutcome = specimenFabricationReport.fabrication_outcome || {};
  const specimenFeedback = specimenFabricationReport.feedback_to_design || {};
  const specimenGates = Array.isArray(specimenFabricationReport.quality_gates) ? specimenFabricationReport.quality_gates : [];
  const specimenGateSummary = specimenGates.length
    ? `${specimenGates.filter((gate) => gate.status === "pass").length}/${specimenGates.length} pass · blocked=${specimenGates.filter((gate) => gate.status === "blocked").length} · fail=${specimenGates.filter((gate) => gate.status === "fail").length}`
    : "-";
  const visionReport = latestVisionReport(report) || {};
  const visionPacket = latestVisionSignalPacket(report) || {};
  const visionCamera = visionReport.camera_source || {};
  const visionSignals = Array.isArray(visionReport.signal_board) ? visionReport.signal_board : Array.isArray(visionReport.agent_signals) ? visionReport.agent_signals : [];
  const visionZones = visionReport.scene_map || visionReport.zones || {};
  const visionZoneCount = visionZones && typeof visionZones === "object" ? Object.keys(visionZones).length : 0;
  const pickupSignal = visionSignals.find((signal) => signal.signal === "pickup_ready") || {};
  const visionAnomaly = visionReport.safety_anomaly || {};
  const manipulationReport = latestManipulationReport(report) || {};
  const robotTaskResult = latestRobotTaskResult(report) || {};
  const manipulationTask = manipulationReport.task || {};
  const manipulationPolicy = manipulationReport.policy_plan || {};
  const manipulationPreflight = manipulationReport.preflight || {};
  const manipulationVision = manipulationReport.vision_context || {};
  const manipulationStage = manipulationReport.stage_machine || {};
  const manipulationSarm = manipulationReport.sarm || {};
  const manipulationDecision = manipulationReport.decision || {};
  const equipmentReport = latestEquipmentReport(report) || {};
  const equipmentResult = latestEquipmentResult(report) || {};
  const equipmentPacket = latestUtmDataReadyPacket(report) || {};
  const equipmentHandoff = latestEquipmentHandoffPacket(report) || {};
  const equipmentBridge = equipmentReport.bridge || {};
  const equipmentControlPlan = equipmentReport.control_plan || {};
  const equipmentControlProfile = equipmentControlPlan.profile || {};
  const equipmentScreenChecks = Array.isArray(equipmentReport.screen_checks) ? equipmentReport.screen_checks : [];
  const equipmentScreenPassed = equipmentScreenChecks.filter((item) => item && item.ok).length;
  const equipmentVisionChecks = equipmentReport.vision_cross_checks || {};
  const equipmentPhysical = equipmentReport.physical_checks || {};
  const equipmentData = equipmentReport.data_acquisition || {};
  const equipmentCross = equipmentReport.cross_checks || {};
  const equipmentDecision = equipmentReport.decision || {};
  const equipmentLinuxPath = equipmentData.linux_path || equipmentResult.result_file || equipmentResult.utm_csv_path || equipmentPacket.result_file || equipmentHandoff.result_file || "";
  const equipmentFailure = equipmentDecision.failure_code || equipmentResult.failure_code || equipmentHandoff.failure_code || "";
  const analysisPayload = latestAnalysisPayload(report) || {};
  const analysisMetrics = analysisPayload.utm_metrics || {};
  const analysisQuality = analysisPayload.quality_gate || analysisPayload.data_quality_gate || {};
  const analysisComparison = analysisPayload.fem_utm_comparison || {};
  const analysisArtifacts = analysisPayload.analysis_artifacts || {};
  const analysisFemLoop = analysisPayload.fem_agentic_loop || {};
  const analysisBoHandoff = latestAnalysisBoHandoff(report) || {};
  const knowledgePayload = latestKnowledgePayload(report) || {};
  const knowledgeReport = latestKnowledgeReport(report) || {};
  const knowledgeContext = latestKnowledgeContext(report) || {};
  const knowledgeEvolution = latestKnowledgeEvolutionProposal(report) || {};
  const knowledgeMemoryIntake = knowledgeReport.memory_intake || {};
  const knowledgeEvidenceQuality = knowledgeReport.evidence_quality || knowledgeContext.evidence_quality || {};
  const knowledgeFailures = Array.isArray(knowledgeReport.failure_patterns) ? knowledgeReport.failure_patterns : [];
  const knowledgeSuccesses = Array.isArray(knowledgeReport.success_patterns) ? knowledgeReport.success_patterns : [];
  const knowledgePerformance = Array.isArray(knowledgeReport.agent_performance_records) ? knowledgeReport.agent_performance_records : [];
  const knowledgePacks = Array.isArray(knowledgeEvolution.evidence_packs) ? knowledgeEvolution.evidence_packs : [];
  const knowledgeOutcomes = Array.isArray(knowledgeEvolution.outcomes) ? knowledgeEvolution.outcomes : Array.isArray(knowledgeReport.evolution_outcomes) ? knowledgeReport.evolution_outcomes : [];
  const guardianStatus = liveGuardianStatusPayload(report);
  const guardianSummary = guardianStatus && guardianStatus.summary ? guardianStatus.summary : {};
  const guardianLatestDecisionRaw = latestReportPayload(report, ["latest_guardian_decision", "guardian_decision", "data.guardian_decision"]);
  const guardianLatestDecision = guardianLatestDecisionRaw && typeof guardianLatestDecisionRaw === "object" ? guardianLatestDecisionRaw : {};
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
      summary: "Shows mission contract, supervisor follow-up opinions, route decisions, handoff registry, and loop reflection for the active autonomous run.",
      rows: [
        ["current_stage", state.stage || "-"],
        ["next_action", report.nextAction],
        ["plan_route", (state.run_metadata && state.run_metadata.latest_orchestration_plan && Array.isArray(state.run_metadata.latest_orchestration_plan.route)) ? state.run_metadata.latest_orchestration_plan.route.length : 0],
        ["parallel_check_status", (state.run_metadata && state.run_metadata.latest_orchestrator_parallel_checks) ? state.run_metadata.latest_orchestrator_parallel_checks.status || "unknown" : "not_run"],
        ["followups", (state.run_metadata && Array.isArray(state.run_metadata.orchestrator_followups)) ? state.run_metadata.orchestrator_followups.length : 0],
        ["decisions", (state.run_metadata && Array.isArray(state.run_metadata.orchestrator_decision_register)) ? state.run_metadata.orchestrator_decision_register.length : 0],
        ["handoffs", (state.run_metadata && Array.isArray(state.run_metadata.orchestrator_handoff_packets)) ? state.run_metadata.orchestrator_handoff_packets.length : report.handoffs.length],
        ["loop_reflections", (state.run_metadata && Array.isArray(state.run_metadata.loop_reflections)) ? state.run_metadata.loop_reflections.length : 0],
        ["pending_warnings", report.warnings.length],
      ],
      checklist: ["Check mission contract", "Review latest follow-up", "Confirm next handoff packet", "Resolve operator questions", "Preserve Guardian authority"],
    },
    design: {
      title: "Design Decision / Candidate Evidence",
      summary: "Shows objective contract, hypothesis, candidate pool, deterministic selection rationale, rejected/repair log, and Specimen Agent handoff readiness.",
      rows: [
        ["objective", designObjective.primary_metric || spec.objective_type || "-"],
        ["direction", designObjective.direction || spec.objective_direction || "-"],
        ["hypothesis", designHypothesis.statement || "-"],
        ["geometry_type", spec.geometry_type || spec.structure_type || "-"],
        ["cell_size_mm", spec.cell_size_mm || "-"],
        ["relative_density", spec.relative_density || "-"],
        ["candidate_count", designGeneration.candidate_count || (spec.candidate_pool_summary && spec.candidate_pool_summary.generated_count) || "-"],
        ["valid/rejected", `${designGeneration.valid_count || 0}/${designGeneration.rejected_count || 0}`],
        ["selected_score", designEvaluation.selected_score || spec.expected_objective_proxy_score || "-"],
        ["uncertainty", designEvaluation.uncertainty || spec.uncertainty || "-"],
        ["info_gain", designEvaluation.information_gain_score || spec.information_gain_score || "-"],
        ["risk", designEvaluation.risk_score || spec.risk_score || "-"],
        ["prior_count", designPrior.prior_count || 0],
        ["handoff_ready", designHandoff.required_fields_present === undefined ? "-" : designHandoff.required_fields_present],
      ],
      checklist: ["Review objective/hypothesis", "Inspect candidate ledger", "Check rejected/repair reasons", "Confirm experiment_spec handoff"],
    },
    specimen: {
      title: "Manufacturing Digital Thread / Printer Runtime",
      summary: "Tracks fabrication intent, STL-to-G-code digital thread, process plan, quality gates, PrusaLink runtime evidence, monitoring handoff, and feedback to the next loop.",
      rows: [
        ["fabrication_schema", specimenFabricationReport.schema || "-"],
        ["intent", `${specimenIntent.mode || "-"} / ${specimenIntent.printer_path || latestReportPayload(report, ["printer_path", "mode"]) || "-"}`],
        ["physical_intent", specimenIntent.physical_intent === undefined ? "-" : specimenIntent.physical_intent],
        ["specimen_id", specimenThread.specimen_id || spec.specimen_id || "-"],
        ["stl_path", specimenThread.stl_path || latestReportPayload(report, ["stl_path"]) || "-"],
        ["gcode_path", specimenThread.gcode_path || latestReportPayload(report, ["sliced_path", "gcode_path", "output_gcode"]) || "-"],
        ["printer_profile", specimenThread.printer_profile || spec.printer_profile || "Prusa MK4S default"],
        ["layer/nozzle", `${specimenPlan.layer_height_mm || spec.layer_height_mm || "-"} / ${specimenPlan.nozzle_diameter_mm || spec.nozzle_diameter_mm || "-"}`],
        ["quality_gates", specimenGateSummary],
        ["outcome", specimenOutcome.status || "-"],
        ["location", specimenOutcome.location || "-"],
        ["handoff_packet", specimenPacket.schema || "-"],
        ["feedback_score", specimenFeedback.quality_score === undefined ? "-" : specimenFeedback.quality_score],
      ],
      checklist: ["Confirm fabrication intent", "Inspect digital thread", "Review quality gates", "Check printer runtime trace", "Confirm Vision/Manipulation handoff"],
    },
    vision: {
      title: "Lab Perception Signal Bus / Visual Evidence",
      summary: "Shows camera source, lab zone states, freshness-bounded agent signals, visual evidence artifacts, and downstream safety handoff context.",
      rows: [
        ["vision_schema", visionReport.schema || "-"],
        ["task", visionReport.task || "-"],
        ["camera", `${visionCamera.camera_key || "-"} / ${visionCamera.source || "-"}`],
        ["frame_age_ms", visionCamera.frame_age_ms === undefined ? "-" : visionCamera.frame_age_ms],
        ["zones", visionZoneCount],
        ["signals", visionSignals.length],
        ["pickup_ready", pickupSignal.status ? `${pickupSignal.status} · conf=${renderRuntimeValue(pickupSignal.confidence)} · ttl=${renderRuntimeValue(pickupSignal.expires_at)}` : "-"],
        ["anomaly", visionAnomaly.anomaly === undefined ? "-" : visionAnomaly.anomaly],
        ["handoff_packet", visionPacket.schema || "-"],
      ],
      checklist: ["Check camera heartbeat", "Inspect zone state", "Verify signal freshness", "Review visual evidence", "Gate manipulation handoff"],
    },
    manipulation: {
      title: "Manipulation Agent / Pi0.5 Skill Supervision",
      summary: "Shows bounded manipulation task selection, Pi0.5/LeRobot execution boundary, preflight gates, SARM-lite stage/risk state, Vision dependency, and robot_task_result handoff.",
      rows: [
        ["task", manipulationTask.task_id || robotTaskResult.task_id || "-"],
        ["route", `${manipulationTask.source_location || "-"} -> ${manipulationTask.target_location || "-"}`],
        ["policy_backend", manipulationPolicy.policy_backend || "-"],
        ["policy_type", manipulationPolicy.policy_type || latestReportPayload(report, ["policy_type"]) || "-"],
        ["policy_ref", manipulationPolicy.policy_ref || latestReportPayload(report, ["policy_path", "checkpoint_path", "policy_repo_id"]) || "-"],
        ["preflight", manipulationPreflight.status || "-"],
        ["current_stage", manipulationStage.current_stage || "-"],
        ["sarm_progress", manipulationSarm.progress_score === undefined ? "-" : manipulationSarm.progress_score],
        ["failure_precursor", manipulationSarm.failure_precursor === undefined ? "-" : manipulationSarm.failure_precursor],
        ["handoff_status", robotTaskResult.handoff_status || manipulationDecision.handoff_status || "-"],
        ["next_agent", robotTaskResult.next_action || manipulationDecision.recommended_next_agent || "-"],
      ],
      checklist: ["Confirm Vision signal freshness", "Check robot/profile/policy preflight", "Run bounded LeRobot/Pi0.5 rollout", "Use SARM risk/recovery gate", "Require post-place Vision verification"],
    },
    equipment: {
      title: "Lab Equipment / UTM Visual Control",
      summary: "Shows registered UTM protocol execution, Windows screen-state assertions, Vision physical cross-checks, exported CSV artifact ledger, and the Analysis handoff gate.",
      rows: [
        ["program_id", equipmentControlPlan.program_id || equipmentResult.program_id || equipmentHandoff.program_id || "-"],
        ["bridge", `${equipmentBridge.provider || "-"} / ${equipmentBridge.connection_status || "unknown"}`],
        ["control_profile", equipmentControlProfile.program_id ? `${equipmentControlProfile.program_id} · locators=${renderRuntimeValue(equipmentControlProfile.locator_count, "0")}` : "-"],
        ["screen_assertions", `${equipmentScreenPassed}/${equipmentScreenChecks.length} passed · screen_started=${renderRuntimeValue(equipmentCross.screen_started)}`],
        ["vision_physical_gate", `${equipmentVisionChecks.all_required_ok === true ? "ok" : "blocked/unknown"} · motion=${renderRuntimeValue(equipmentPhysical.vision_motion_confirmed)}`],
        ["data_artifact", `${equipmentData.status || equipmentResult.status || "-"} · rows=${renderRuntimeValue(equipmentData.row_count_probe, "0")} · parse=${renderRuntimeValue(equipmentCross.data_parse_probe_ok)}`],
        ["save_export", `${equipmentData.save_method || "-"} · responsibility=${renderRuntimeValue(equipmentCross.save_export_responsibility_ok)}`],
        ["linux_csv", equipmentLinuxPath || "-"],
        ["handoff_gate", `${equipmentDecision.handoff_status || equipmentHandoff.status || "-"}${equipmentFailure ? ` · ${equipmentFailure}` : ""}`],
      ],
      checklist: ["Confirm registered UTM profile", "Verify screen state transitions", "Verify Vision physical motion/alignment checks", "Confirm pulled CSV checksum and parse probe", "Only hand off when all gates pass"],
    },
    analysis: {
      title: "Analysis Agent / UTM-FEM-BO Handoff",
      summary: "Shows raw UTM ingestion, canonical curve artifacts, quality gate, FEniCSx/CAE simulation evidence, FEM-UTM residuals, and BO-ready handoff status.",
      rows: [
        ["objective_score", analysisPayload.objective_score ?? latestReportPayload(report, ["objective_score", "score", "utility"]) ?? "-"],
        ["uncertainty", analysisPayload.uncertainty ?? "-"],
        ["peak_force_N", analysisMetrics.peak_force_N ?? "-"],
        ["strength_MPa", analysisMetrics.compressive_strength_MPa ?? "-"],
        ["quality_ok_for_bo", analysisQuality.ok_for_bo === undefined ? "-" : analysisQuality.ok_for_bo],
        ["quality_score", analysisQuality.score === undefined ? "-" : analysisQuality.score],
        ["fem_agreement", analysisComparison.agreement_score === undefined ? "-" : analysisComparison.agreement_score],
        ["fem_agentic_loop", analysisFemLoop.status || "-"],
        ["fem_selected_iteration", analysisFemLoop.selected_iteration === undefined ? "-" : analysisFemLoop.selected_iteration],
        ["bo_handoff", analysisBoHandoff.ok_for_bo === undefined ? "-" : analysisBoHandoff.ok_for_bo],
        ["canonical_curve", analysisArtifacts.canonical_curve || "-"],
        ["fem_result", analysisArtifacts.fem_result || "-"],
        ["experiment_evaluation", analysisArtifacts.experiment_evaluation || "-"],
      ],
      checklist: ["Verify raw file fingerprint", "Check column/unit confidence", "Review quality gate", "Inspect FEM/UTM comparison", "Confirm BO handoff provenance"],
    },
    knowledge: {
      title: "Knowledge Memory / Self-Evolution Evidence",
      summary: "Shows typed research memory, provenance health, failure/success patterns, agent performance ledger, and evidence packs prepared for Self-Evolution review.",
      rows: [
        ["experiment_record", knowledgeMemoryIntake.experiment_record_id || "-"],
        ["agent_performance", knowledgeMemoryIntake.agent_performance_count ?? knowledgePerformance.length ?? "-"],
        ["failure/success_patterns", `${knowledgeMemoryIntake.failure_pattern_count ?? knowledgeFailures.length ?? 0}/${knowledgeMemoryIntake.success_pattern_count ?? knowledgeSuccesses.length ?? 0}`],
        ["evolution_packs", knowledgeMemoryIntake.evolution_pack_count ?? knowledgePacks.length ?? "-"],
        ["evolution_outcomes", knowledgeMemoryIntake.evolution_outcome_count ?? knowledgeOutcomes.length ?? "-"],
        ["retrieval_coverage", knowledgePayload.retrieval_coverage ?? knowledgeContext.retrieval?.coverage ?? "-"],
        ["artifact_coverage", knowledgeEvidenceQuality.artifact_link_coverage ?? "-"],
        ["top_evolution_target", knowledgePacks[0] ? `${knowledgePacks[0].target_type || "target"}:${knowledgePacks[0].target_id || "unknown"}` : "not recorded"],
      ],
      checklist: ["Write provenance-backed memory", "Update failure/success pattern library", "Refresh agent performance ledger", "Prepare evidence packs", "Keep activation behind Self-Evolution/Guardian/operator gates"],
    },
    bo: {
      title: "Bayesian Optimization / Candidate Selection",
      summary: "Shows measured priors, failure-memory penalties, numeric acquisition, LLM preference reasoning, top-k candidate ranking, and the next Design Agent handoff.",
      rows: [
        ["strategy", `${boResult.strategy || "-"} / benchmark=${boResult.benchmark_strategy || "-"}`],
        ["acquisition", boResult.acquisition || latestReportPayload(report, ["acquisition", "acquisition_function"]) || "-"],
        ["budget", boResult.budget || "-"],
        ["priors", `measured=${renderRuntimeValue(boPriorSummary.measured_count, "0")} failed=${renderRuntimeValue(boPriorSummary.failed_count, "0")}`],
        ["reasoning_source", boReasoning.source || "-"],
        ["ranked_candidates", boCandidateRanking.length],
        ["recommended_candidate", boRecommendation.candidate_id || boRecommendation.id || "-"],
        ["combined_score", boRecommendation.combined_score || "-"],
        ["objective_score", boRecommendation.objective_score || boRecommendation.score || "-"],
      ],
      checklist: ["Ingest Analysis handoff", "Run LLM reasoning pass", "Score numeric acquisition", "Apply failure/constraint penalties", "Hand off next_design_request.v1"],
    },
    guardian: {
      title: "Safety Gate / Continue-Stop Decision",
      summary: "Shows graph-wide risk, gate timeline, blocked actions, approval interrupts, incidents, policy schema, and device/data integrity for the active run.",
      rows: [
        ["guardian_status", guardianStatus ? guardianStatus.status || "-" : "not_loaded"],
        ["risk_score", guardianSummary.risk_score ?? "-"],
        ["dominant_risks", guardianSummary.dominant_risks || []],
        ["gate_count", guardianSummary.gate_count ?? "-"],
        ["blocked_actions", guardianSummary.blocked_action_count ?? "-"],
        ["pending_approvals", guardianSummary.pending_approval_count ?? "-"],
        ["incidents", guardianSummary.incident_count ?? "-"],
        ["latest_decision", guardianLatestDecision.decision || latestReportPayload(report, ["guardian_decision", "decision", "next_stage"]) || report.nextAction],
        ["latest_reason", guardianLatestDecision.reason_code || latestWarning],
      ],
      checklist: ["Review graph-wide risk map", "Resolve approval queue before physical actions", "Inspect incidents and corrective actions", "Verify device/data integrity", "Confirm loop continue/recover/stop decision"],
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



function renderOrchestratorReportDetails(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && typeof state.run_metadata === "object" && state.run_metadata ? state.run_metadata : {};
  const followups = Array.isArray(metadata.orchestrator_followups) ? metadata.orchestrator_followups.slice(-12) : [];
  const decisions = Array.isArray(metadata.orchestrator_decision_register) ? metadata.orchestrator_decision_register.slice(-12) : [];
  const handoffs = Array.isArray(metadata.orchestrator_handoff_packets) ? metadata.orchestrator_handoff_packets.slice(-12) : [];
  const reflections = Array.isArray(metadata.loop_reflections) ? metadata.loop_reflections.slice(-5) : [];
  const latestFollowup = metadata.latest_orchestrator_followup || followups[followups.length - 1] || {};
  const latestHandoff = metadata.latest_orchestrator_handoff || handoffs[handoffs.length - 1] || {};
  const orchestrationPlan = metadata.latest_orchestration_plan && typeof metadata.latest_orchestration_plan === "object" ? metadata.latest_orchestration_plan : {};
  const missionContract = metadata.latest_mission_contract && typeof metadata.latest_mission_contract === "object" ? metadata.latest_mission_contract : metadata.mission_contract && typeof metadata.mission_contract === "object" ? metadata.mission_contract : {};
  const routeItems = Array.isArray(orchestrationPlan.route) ? orchestrationPlan.route.map((item) => `${item.order || "-"}. ${item.stage || "-"} · ${item.agent || "-"} · ${item.status || "pending"}`) : [];
  const parallelItems = Array.isArray(orchestrationPlan.parallelizable_checks) ? orchestrationPlan.parallelizable_checks : [];
  const latestParallelChecks = metadata.latest_orchestrator_parallel_checks && typeof metadata.latest_orchestrator_parallel_checks === "object" ? metadata.latest_orchestrator_parallel_checks : {};
  const parallelResultItems = Array.isArray(latestParallelChecks.checks) ? latestParallelChecks.checks.map((item) => `${item.name || "check"} · ${item.status || "unknown"} · ${item.summary || ""}`) : [];
  const serialItems = Array.isArray(orchestrationPlan.serial_physical_actions) ? orchestrationPlan.serial_physical_actions : [];
  const artifactItems = Array.isArray(orchestrationPlan.expected_artifacts) ? orchestrationPlan.expected_artifacts : [];
  const followupItems = followups.map((item) => `${item.stage || "-"} · ${item.trigger || "-"} · conf=${renderRuntimeValue(item.confidence)} · ${item.recommendation || item.opinion || ""}`);
  const decisionItems = decisions.map((item) => `${item.stage || "-"} · ${item.decision || "decision"} -> ${renderRuntimeValue(item.selected)} · ${item.reason || ""}`);
  const handoffItems = handoffs.map((item) => `${item.from_stage || "-"} -> ${item.to_stage || "-"} · ${item.consumer_agent || "-"} · ${item.packet_id || ""}`);
  const reflectionItems = reflections.map((item) => `${item.loop_id ?? "-"} · ${item.guardian_decision || "-"} · ${item.next_loop_recommendation || item.operator_visible_summary || ""}`);
  return `
    <div class="live-agent-specific-report-detail live-agent-specific-orchestrator-details">
      <h5>Mission Contract</h5>
      ${runtimeRows([
        ["mission_id", missionContract.mission_id || "-"],
        ["run_id", missionContract.run_id || state.run_id || "-"],
        ["mode", missionContract.mode || state.mode || "-"],
        ["stage", missionContract.stage || state.stage || "-"],
        ["operator_intent", missionContract.operator_intent || "-"],
        ["active_goal", missionContract.goal || state.active_goal || "-"],
        ["loop_count", missionContract.loop_id ?? state.loop_count ?? "-"],
        ["specimen_id", missionContract.specimen_id || (state.current_experiment_spec || {}).specimen_id || "-"],
        ["requires_guardian_gate", missionContract.requires_guardian_gate === undefined ? true : missionContract.requires_guardian_gate],
      ])}
      <h5>Orchestration Plan</h5>
      ${runtimeRows([
        ["plan_id", orchestrationPlan.plan_id || "-"],
        ["graph_id", orchestrationPlan.graph_id || "atr_closed_loop"],
        ["current_stage", orchestrationPlan.current_stage || state.stage || "-"],
        ["next_recommended_stage", orchestrationPlan.next_recommended_stage || "-"],
      ])}
      ${renderReportList(routeItems, "No compiled Orchestrator route recorded yet.", 16)}
      <h5>Parallel Read-only Checks</h5>
      ${renderReportList(parallelItems, "No parallelizable check plan recorded yet.", 12)}
      <h5>Latest Parallel Check Results</h5>
      ${runtimeRows([
        ["batch_id", latestParallelChecks.batch_id || "-"],
        ["status", latestParallelChecks.status || "not_run"],
        ["execution_mode", latestParallelChecks.execution_mode || "-"],
        ["check_count", latestParallelChecks.check_count ?? "-"],
        ["status_counts", latestParallelChecks.status_counts || {}],
      ])}
      ${renderReportList(parallelResultItems, "No executed parallel check results recorded yet.", 12)}
      <h5>Serial Physical Actions</h5>
      ${renderReportList(serialItems, "No serial physical action plan recorded yet.", 12)}
      <h5>Expected Artifacts</h5>
      ${renderReportList(artifactItems, "No expected artifact ledger recorded yet.", 12)}
      <h5>Latest Supervisor Opinion</h5>
      ${runtimeRows([
        ["stage", latestFollowup.stage || "-"],
        ["trigger", latestFollowup.trigger || "-"],
        ["opinion", latestFollowup.opinion || "-"],
        ["recommendation", latestFollowup.recommendation || "-"],
        ["concerns", latestFollowup.concerns || []],
        ["requires_response", latestFollowup.requires_response === undefined ? false : latestFollowup.requires_response],
      ])}
      <h5>Follow-up Timeline</h5>
      ${renderReportList(followupItems, "No Orchestrator follow-up recorded yet.", 16)}
      <h5>Decision Register</h5>
      ${renderReportList(decisionItems, "No Orchestrator decisions recorded yet.", 16)}
      <h5>Handoff Registry</h5>
      ${runtimeRows([
        ["latest_from", latestHandoff.from_stage || "-"],
        ["latest_to", latestHandoff.to_stage || "-"],
        ["consumer", latestHandoff.consumer_agent || "-"],
        ["required_outputs", latestHandoff.required_outputs || []],
      ])}
      ${renderReportList(handoffItems, "No Orchestrator handoff packet recorded yet.", 14)}
      <h5>Loop Reflection</h5>
      ${renderReportList(reflectionItems, "No loop reflection recorded yet.", 12)}
    </div>
  `;
}

function renderDesignReportDetails(report) {
  const designReport = latestDesignReport(report);
  if (!designReport || typeof designReport !== "object") return "";
  const hypothesis = designReport.hypothesis || {};
  const objective = designReport.objective || {};
  const generation = designReport.candidate_generation || {};
  const evaluation = designReport.candidate_evaluation || {};
  const prior = designReport.prior_context || {};
  const handoff = designReport.handoff_to_specimen || {};
  const topCandidates = Array.isArray(generation.top_candidates) ? generation.top_candidates.slice(0, 5) : [];
  const rejected = Array.isArray(designReport.rejected_candidates) ? designReport.rejected_candidates.slice(0, 6) : [];
  const decisions = Array.isArray(designReport.decision_register) ? designReport.decision_register.slice(0, 6) : [];
  const topList = topCandidates.map((item) => `${item.candidate_id || "candidate"} · ${item.geometry_type || "-"} · score=${renderRuntimeValue(item.expected_objective_proxy_score || item.predicted_objective)} · risk=${renderRuntimeValue(item.risk_score)}`);
  const rejectedList = rejected.map((item) => `${item.candidate_id || "candidate"} · ${item.reason || "rejected"}`);
  const decisionList = decisions.map((item) => `${item.decision_id || item.decision || "decision"} · ${item.status || "-"} · ${item.rationale || ""}`);
  return `
    <div class="live-agent-specific-design-details">
      ${runtimeRows([
        ["report_id", designReport.report_id || "-"],
        ["primary_metric", objective.primary_metric || "-"],
        ["direction", objective.direction || "-"],
        ["variables", hypothesis.variables_under_test || "-"],
        ["selected_candidate", evaluation.selected_candidate_id || "-"],
        ["manufacturability", evaluation.manufacturability_score || "-"],
        ["knowledge_prior", prior.knowledge_summary || "-"],
        ["bo_recommendation", prior.bo_recommendation || "-"],
        ["handoff_missing", handoff.missing_required_fields || []],
      ])}
      <h5>Candidate Board</h5>
      ${renderReportList(topList, "No candidate board recorded.")}
      <h5>Rejected / Repair Log</h5>
      ${renderReportList(rejectedList, "No rejected candidates recorded.")}
      <h5>Decision Register</h5>
      ${renderReportList(decisionList, "No design decisions recorded.")}
    </div>
  `;
}

function renderSpecimenReportDetails(report) {
  const fabricationReport = latestSpecimenFabricationReport(report);
  if (!fabricationReport || typeof fabricationReport !== "object") return "";
  const packet = latestSpecimenFabricatedPacket(report) || {};
  const intent = fabricationReport.fabrication_intent || {};
  const thread = fabricationReport.digital_thread || {};
  const plan = fabricationReport.process_plan || {};
  const cap = plan.cap_skin_policy || {};
  const adhesion = plan.adhesion_policy || {};
  const ejection = plan.ejection_policy || {};
  const monitoring = fabricationReport.monitoring_plan || {};
  const runtime = fabricationReport.printer_runtime || {};
  const outcome = fabricationReport.fabrication_outcome || {};
  const feedback = fabricationReport.feedback_to_design || {};
  const gates = Array.isArray(fabricationReport.quality_gates) ? fabricationReport.quality_gates : [];
  const gateItems = gates.map((gate) => `${gate.gate || "gate"} · ${gate.status || "unknown"}${gate.repair ? ` · repair=${renderRuntimeValue(gate.repair)}` : ""}`);
  const defectClasses = Array.isArray(monitoring.defect_classes) ? monitoring.defect_classes.join(", ") : "-";
  return `
    <div class="live-agent-specific-specimen-details">
      <h5>Fabrication Intent</h5>
      ${runtimeRows([
        ["mode", intent.mode || "-"],
        ["printer_path", intent.printer_path || "-"],
        ["physical_intent", intent.physical_intent === undefined ? "-" : intent.physical_intent],
        ["specimen_purpose", intent.specimen_purpose || "-"],
        ["live_gui_test_spec", intent.live_gui_test_spec === undefined ? "-" : intent.live_gui_test_spec],
      ])}
      <h5>Digital Thread</h5>
      ${runtimeRows([
        ["candidate_id", thread.candidate_id || "-"],
        ["specimen_id", thread.specimen_id || "-"],
        ["design_hash", thread.design_hash || "-"],
        ["geometry_hash", thread.geometry_hash || "-"],
        ["stl_path", thread.stl_path || "-"],
        ["gcode_path", thread.gcode_path || "-"],
        ["handoff_package_path", thread.handoff_package_path || "-"],
        ["printer_job_id", thread.printer_job_id || "-"],
      ])}
      <h5>Process Plan</h5>
      ${runtimeRows([
        ["material", thread.material || "-"],
        ["printer_profile", thread.printer_profile || "-"],
        ["slicer_profile_hint", thread.slicer_profile_hint || "-"],
        ["layer_height_mm", plan.layer_height_mm || "-"],
        ["first_layer_height_mm", plan.first_layer_height_mm || "-"],
        ["nozzle_diameter_mm", plan.nozzle_diameter_mm || "-"],
        ["bed_temperature_c", plan.bed_temperature_c || "-"],
        ["first_layer_bed_temperature_c", plan.first_layer_bed_temperature_c || "-"],
        ["slow_first_layer", adhesion.slow_first_layer_enabled === undefined ? "-" : adhesion.slow_first_layer_enabled],
        ["first_layer_speed_mm_s", adhesion.first_layer_speed_mm_s || "-"],
        ["cap_skin", `top=${renderRuntimeValue(cap.top_cap_enabled)} bottom=${renderRuntimeValue(cap.bottom_cap_enabled)} thickness=${renderRuntimeValue(cap.skin_thickness_mm)}`],
        ["ejection_policy", `${ejection.status || "-"} requested=${renderRuntimeValue(ejection.requested)}`],
        ["estimated_mass_g", plan.estimated_mass_g || "-"],
        ["estimated_print_time_min", plan.estimated_print_time_min || "-"],
      ])}
      <h5>Quality Gates</h5>
      ${renderReportList(gateItems, "No manufacturing quality gates recorded.")}
      <h5>Printer Runtime</h5>
      ${runtimeRows([
        ["prepare_status", runtime.prepare_status || "-"],
        ["mode", runtime.mode || "-"],
        ["path", runtime.path || "-"],
        ["upload", runtime.upload && (runtime.upload.status || runtime.upload.failure_code || (runtime.upload.ok ? "ok" : "-"))],
        ["transfer_wait", runtime.transfer_wait && (runtime.transfer_wait.status || runtime.transfer_wait.failure_code || (runtime.transfer_wait.ok ? "ok" : "-"))],
        ["start", runtime.start && (runtime.start.status || runtime.start.failure_code || (runtime.start.ok ? "ok" : "-"))],
        ["ejection", runtime.ejection && (runtime.ejection.status || runtime.ejection.failure_code || "-")],
      ])}
      ${Array.isArray(runtime.step_trace) && runtime.step_trace.length ? renderStepTrace(runtime.step_trace) : ""}
      <h5>Monitoring / Feedback</h5>
      ${runtimeRows([
        ["observe_prusalink_status", monitoring.observe_prusalink_status],
        ["observe_transfer_idle", monitoring.observe_transfer_idle],
        ["observe_camera_after_print", monitoring.observe_camera_after_print],
        ["layerwise_monitoring_available", monitoring.layerwise_monitoring_available],
        ["defect_classes", defectClasses],
        ["outcome", outcome.status || "-"],
        ["location", outcome.location || "-"],
        ["failure_code", outcome.failure_code || "-"],
        ["quality_score", feedback.quality_score === undefined ? "-" : feedback.quality_score],
        ["uncertainty", feedback.uncertainty === undefined ? "-" : feedback.uncertainty],
        ["packet", packet.schema || "-"],
        ["next_action", packet.next_action || "-"],
      ])}
    </div>
  `;
}

function renderVisionReportDetails(report) {
  const visionReport = latestVisionReport(report);
  if (!visionReport || typeof visionReport !== "object") return "";
  const packet = latestVisionSignalPacket(report) || {};
  const camera = visionReport.camera_source || {};
  const backend = visionReport.model_backend || {};
  const zones = visionReport.scene_map || visionReport.zones || {};
  const zoneItems = Object.entries(zones).map(([zoneId, zone]) => {
    const item = zone && typeof zone === "object" ? zone : {};
    const state = item.state || (item.specimen_present ? "present" : item.clear ? "clear" : "unknown");
    return `${zoneId} · ${state} · conf=${renderRuntimeValue(item.confidence)}`;
  });
  const signals = Array.isArray(visionReport.signal_board) ? visionReport.signal_board : Array.isArray(visionReport.agent_signals) ? visionReport.agent_signals : [];
  const signalItems = signals.map((signal) => `${signal.signal || "signal"} · ${signal.status || "-"} · ${signal.zone_id || "-"} · conf=${renderRuntimeValue(signal.confidence)} · expires=${renderRuntimeValue(signal.expires_at)}${signal.blocking_reason ? ` · ${signal.blocking_reason}` : ""}`);
  const events = Array.isArray(visionReport.events) ? visionReport.events : [];
  const eventItems = events.map((event) => `${event.event_type || "event"} · ${event.status || "-"} · conf=${renderRuntimeValue(event.confidence)}${event.blocking ? " · blocking" : ""}`);
  const detections = Array.isArray(visionReport.detections) ? visionReport.detections : [];
  const detectionItems = detections.map((det) => `${det.label || "object"} · ${det.zone || "-"} · conf=${renderRuntimeValue(det.confidence)} · bbox=${renderRuntimeValue(det.bbox_xyxy || [])}`);
  const artifacts = visionReport.artifacts || {};
  const safety = visionReport.safety_anomaly || {};
  const dataset = visionReport.dataset_ledger || {};
  const knowledge = visionReport.knowledge_payload || {};
  return `
    <div class="live-agent-specific-vision-details">
      <h5>Scene Task / Camera Source</h5>
      ${runtimeRows([
        ["task", visionReport.task || "-"],
        ["camera_key", camera.camera_key || "-"],
        ["source", camera.source || "-"],
        ["frame_id", camera.frame_id || "-"],
        ["timestamp", camera.timestamp || "-"],
        ["calibration_id", camera.calibration_id || "-"],
        ["model_backend", `${backend.mode || "-"} / detector=${backend.detector || "-"} / pose=${backend.pose_backend || "-"}`],
      ])}
      <h5>Zone State</h5>
      ${renderReportList(zoneItems, "No zone states recorded.")}
      <h5>Detection / Tracking</h5>
      ${renderReportList(detectionItems, "No detections recorded.")}
      <h5>Agent Signal Board</h5>
      ${renderReportList(signalItems, "No agent signals recorded.", 32)}
      <h5>Evidence Timeline</h5>
      ${renderReportList(eventItems, "No visual events recorded.")}
      <h5>Evidence Artifacts / Dataset Ledger</h5>
      ${runtimeRows([
        ["annotated_frame_path", artifacts.annotated_frame_path || "-"],
        ["detection_json_path", artifacts.detection_json_path || "-"],
        ["episode_id", dataset.episode_id || "-"],
        ["candidate_for_lerobot_dataset", dataset.candidate_for_lerobot_dataset === undefined ? "-" : dataset.candidate_for_lerobot_dataset],
        ["success_labels", knowledge.success_labels || []],
        ["failure_labels", knowledge.failure_labels || []],
      ])}
      <h5>Safety / Handoff</h5>
      ${runtimeRows([
        ["anomaly", safety.anomaly === undefined ? "-" : safety.anomaly],
        ["low_confidence", safety.low_confidence === undefined ? "-" : safety.low_confidence],
        ["blocking_reason", safety.blocking_reason || "-"],
        ["packet", packet.schema || "-"],
        ["primary_signal", packet.signal_id || "-"],
        ["next_action", packet.next_action || "-"],
      ])}
    </div>
  `;
}

function renderManipulationReportDetails(report) {
  const manipulationReport = latestManipulationReport(report);
  if (!manipulationReport || typeof manipulationReport !== "object") return "";
  const packet = latestRobotTaskResult(report) || manipulationReport.handoff_packet || {};
  const task = manipulationReport.task || {};
  const policy = manipulationReport.policy_plan || {};
  const preflight = manipulationReport.preflight || {};
  const vision = manipulationReport.vision_context || {};
  const runtime = manipulationReport.rollout_runtime || {};
  const stage = manipulationReport.stage_machine || {};
  const sarm = manipulationReport.sarm || {};
  const decision = manipulationReport.decision || {};
  const knowledge = manipulationReport.knowledge_payload || {};
  const blockers = [...(preflight.blocking_reasons || []), ...(preflight.warnings || [])];
  const completedStages = Array.isArray(stage.completed_stages) ? stage.completed_stages : [];
  const taxonomy = Array.isArray(stage.stage_taxonomy) ? stage.stage_taxonomy : [];
  const runtimeEvents = Array.isArray(runtime.events) ? runtime.events.slice(-8).map((event) => `${event.step || event.event_type || "event"} · ${event.status || "-"}${event.detail ? ` · ${event.detail}` : ""}`) : [];
  const evidencePaths = Array.isArray(knowledge.evidence_paths) ? knowledge.evidence_paths : Array.isArray(packet.evidence_refs) ? packet.evidence_refs.map((ref) => ref.path || ref.type || JSON.stringify(ref)) : [];
  return `
    <div class="live-agent-specific-manipulation-details">
      <h5>Skill Episode Board</h5>
      ${runtimeRows([
        ["task_id", task.task_id || packet.task_id || "-"],
        ["skill_id", packet.skill_id || task.task_id || "-"],
        ["episode_id", packet.episode_id || manipulationReport.session_id || "-"],
        ["specimen_id", task.specimen_id || packet.specimen_id || "-"],
        ["route", `${task.source_location || "-"} -> ${task.target_location || "-"}`],
        ["terminal_pose", packet.terminal_pose || task.intended_terminal_pose || "-"],
      ])}
      <h5>Pi0.5 / LeRobot Boundary</h5>
      ${runtimeRows([
        ["policy_backend", policy.policy_backend || "-"],
        ["policy_type", policy.policy_type || "-"],
        ["policy_ref", policy.policy_ref || "-"],
        ["device", policy.device || "-"],
        ["inference", policy.inference_type || "-"],
        ["rtc_horizon", policy.rtc_execution_horizon === undefined ? "-" : policy.rtc_execution_horizon],
        ["rtc_guidance", policy.rtc_max_guidance_weight === undefined ? "-" : policy.rtc_max_guidance_weight],
        ["max_duration_s", policy.max_duration_s === undefined ? "-" : policy.max_duration_s],
      ])}
      <h5>Preflight / Vision Dependency</h5>
      ${runtimeRows([
        ["preflight_status", preflight.status || "-"],
        ["robot_ready", preflight.robot_ready === undefined ? "-" : preflight.robot_ready],
        ["camera_ready", preflight.camera_ready === undefined ? "-" : preflight.camera_ready],
        ["policy_ready", preflight.policy_ready === undefined ? "-" : preflight.policy_ready],
        ["operator_confirmed", preflight.operator_confirmed === undefined ? "-" : preflight.operator_confirmed],
        ["vision_observation", vision.observation_id || "-"],
        ["vision_freshness", vision.freshness && vision.freshness.reason ? vision.freshness.reason : "-"],
        ["pickup_ready", vision.pickup_target_ready === undefined ? "-" : vision.pickup_target_ready],
        ["fixture_visible", vision.fixture_visible === undefined ? "-" : vision.fixture_visible],
      ])}
      <h5>Blocking / Warning Signals</h5>
      ${renderReportList(blockers, "No Manipulation preflight blockers recorded.", 16)}
      <h5>SARM-lite Stage Machine</h5>
      ${runtimeRows([
        ["current_stage", stage.current_stage || "-"],
        ["completed", `${completedStages.length}/${taxonomy.length || "?"}`],
        ["next_expected", stage.next_expected_stage || "-"],
        ["progress_score", sarm.progress_score === undefined ? "-" : sarm.progress_score],
        ["failure_precursor", sarm.failure_precursor === undefined ? "-" : sarm.failure_precursor],
        ["recovery", sarm.recovery_suggested === undefined ? "-" : sarm.recovery_suggested],
      ])}
      <h5>Rollout Runtime / Evidence</h5>
      ${runtimeRows([
        ["tool", runtime.tool || "-"],
        ["status", runtime.status || "-"],
        ["session_id", runtime.session_id || "-"],
        ["duration_s", runtime.duration_s === undefined ? "-" : runtime.duration_s],
        ["handoff", packet.handoff_status || decision.handoff_status || "-"],
        ["next_agent", packet.next_action || decision.recommended_next_agent || "-"],
        ["reason", decision.reason || "-"],
      ])}
      ${renderReportList(runtimeEvents, "No rollout event trace recorded.", 12)}
      <h5>Knowledge / Dataset Evidence</h5>
      ${renderReportList(evidencePaths, "No rollout evidence path recorded.", 12)}
    </div>
  `;
}


function renderEquipmentReportDetails(report) {
  const equipmentReport = latestEquipmentReport(report);
  if (!equipmentReport || typeof equipmentReport !== "object") return "";
  const equipmentResult = latestEquipmentResult(report) || {};
  const packet = latestUtmDataReadyPacket(report) || {};
  const handoff = latestEquipmentHandoffPacket(report) || {};
  const bridge = equipmentReport.bridge || {};
  const preconditions = equipmentReport.preconditions || {};
  const control = equipmentReport.control_plan || {};
  const profile = control.profile || {};
  const vision = equipmentReport.vision_cross_checks || {};
  const physical = equipmentReport.physical_checks || {};
  const data = equipmentReport.data_acquisition || {};
  const cross = equipmentReport.cross_checks || {};
  const decision = equipmentReport.decision || {};
  const screenChecks = Array.isArray(equipmentReport.screen_checks) ? equipmentReport.screen_checks : [];
  const artifactRecords = Array.isArray(equipmentReport.artifact_records) ? equipmentReport.artifact_records : [];
  const screenEvidenceRefs = Array.isArray(equipmentReport.screen_evidence_refs) ? equipmentReport.screen_evidence_refs : [];
  const dataEvidenceRefs = Array.isArray(equipmentReport.data_evidence_refs) ? equipmentReport.data_evidence_refs : [];
  const artifactRefs = Array.isArray(equipmentReport.artifact_refs) ? equipmentReport.artifact_refs : [];
  const failureRetryTable = Array.isArray(equipmentReport.failure_retry_table) ? equipmentReport.failure_retry_table : [];
  const recovery = equipmentReport.recovery && typeof equipmentReport.recovery === "object" ? equipmentReport.recovery : {};
  const liveAudit = equipmentReport.live_evidence_audit && typeof equipmentReport.live_evidence_audit === "object" ? equipmentReport.live_evidence_audit : {};
  const liveScreenAudit = liveAudit.screen_evidence && typeof liveAudit.screen_evidence === "object" ? liveAudit.screen_evidence : {};
  const livePullAudit = liveAudit.linux_artifact_pull && typeof liveAudit.linux_artifact_pull === "object" ? liveAudit.linux_artifact_pull : {};
  const liveVisionAudit = liveAudit.vision_evidence && typeof liveAudit.vision_evidence === "object" ? liveAudit.vision_evidence : {};
  const liveSaveAudit = liveAudit.save_export && typeof liveAudit.save_export === "object" ? liveAudit.save_export : {};
  const liveRequestAudit = liveAudit.request_audit_log && typeof liveAudit.request_audit_log === "object" ? liveAudit.request_audit_log : {};
  const hardwareAlert = equipmentReport.hardware_alert && typeof equipmentReport.hardware_alert === "object" ? equipmentReport.hardware_alert : packet.hardware_alert && typeof packet.hardware_alert === "object" ? packet.hardware_alert : equipmentResult.hardware_alert && typeof equipmentResult.hardware_alert === "object" ? equipmentResult.hardware_alert : {};
  const guardianDecision = hardwareAlert.guardian_decision && typeof hardwareAlert.guardian_decision === "object" ? hardwareAlert.guardian_decision : {};
  const guardianContract = hardwareAlert.guardian_contract && typeof hardwareAlert.guardian_contract === "object" ? hardwareAlert.guardian_contract : {};
  const incidentRecords = Array.isArray(equipmentReport.incident_records) ? equipmentReport.incident_records : hardwareAlert.incident_record ? [hardwareAlert.incident_record] : [];
  const screenItems = screenChecks.map((item) => `${item.checkpoint || "screen"} · ok=${renderRuntimeValue(item.ok)} · state=${item.state || "-"} · artifact=${item.screenshot_artifact || "-"}`);
  const artifactItems = artifactRecords.map((item) => {
    const kind = item.kind || "artifact";
    const artifactId = item.artifact_id || "-";
    const ref = item.local_path || item.linux_path || item.path || item.windows_path || "-";
    const rows = item.row_count_probe === undefined ? "" : ` · rows=${renderRuntimeValue(item.row_count_probe)}`;
    return `${kind} · id=${artifactId} · ref=${ref}${rows}`;
  });
  const retryItems = failureRetryTable.map((item) => {
    const fallback = item.fallback_macro ? ` · fallback=${item.fallback_macro}` : "";
    return `${item.step || "step"} · status=${item.status || "-"} · code=${item.failure_code || "-"}${fallback} · action=${item.recommended_action || "-"}`;
  });
  const visionChecks = vision.checks && typeof vision.checks === "object" ? Object.entries(vision.checks) : [];
  const visionItems = visionChecks.map(([checkId, item]) => {
    const check = item && typeof item === "object" ? item : {};
    return `${checkId} · ok=${renderRuntimeValue(check.ok)} · source=${check.source || "-"} · conf=${renderRuntimeValue(check.confidence)}`;
  });
  const blockingReasons = Array.isArray(decision.blocking_reasons) ? decision.blocking_reasons : Array.isArray(vision.blocking_reasons) ? vision.blocking_reasons : [];
  const riskFlags = Array.isArray(guardianContract.risk_flags) ? guardianContract.risk_flags : Array.isArray(hardwareAlert.risk_flags) ? hardwareAlert.risk_flags : [];
  const evidenceRefs = Array.isArray(packet.evidence_refs) ? packet.evidence_refs : [];
  return `
    <div class="live-agent-specific-equipment-details">
      <h5>Bridge / Protocol Profile</h5>
      ${runtimeRows([
        ["schema", equipmentReport.schema || "-"],
        ["report_version", equipmentReport.report_version || "-"],
        ["task_id", equipmentReport.task_id || "-"],
        ["provider", bridge.provider || "-"],
        ["connection_status", bridge.connection_status || "-"],
        ["bridge_host", bridge.bridge_url_host || bridge.host || "-"],
        ["remote_server_version", bridge.remote_server_version || "-"],
        ["remote_script_version", bridge.remote_script_version || "-"],
        ["client_latency_ms", bridge.client_latency_ms === undefined || bridge.client_latency_ms === "" ? "-" : bridge.client_latency_ms],
        ["pyautogui_available", bridge.pyautogui_available === undefined ? "-" : bridge.pyautogui_available],
        ["pyautogui_failsafe", bridge.pyautogui_failsafe === undefined || bridge.pyautogui_failsafe === "" ? "-" : bridge.pyautogui_failsafe],
        ["pyautogui_pause", bridge.pyautogui_pause === undefined || bridge.pyautogui_pause === "" ? "-" : bridge.pyautogui_pause],
        ["pyautogui_error", bridge.pyautogui_error || "-"],
        ["live_execute_enabled", bridge.live_execute_enabled === undefined ? "-" : bridge.live_execute_enabled],
        ["program_id", control.program_id || equipmentResult.program_id || handoff.program_id || "-"],
        ["macro_version", control.macro_version || "-"],
        ["locator_backend", control.locator_backend || "-"],
        ["profile_memory", profile.profile_memory_path || "-"],
        ["profile_applied", profile.profile_memory_applied === undefined ? "-" : profile.profile_memory_applied],
        ["locator_count", profile.locator_count === undefined ? "-" : profile.locator_count],
      ])}
      <h5>Preconditions</h5>
      ${runtimeRows(Object.entries(preconditions))}
      <h5>Screen-State Assertions</h5>
      ${renderReportList(screenItems, "No UTM screen checks recorded.", 24)}
      <h5>Vision Physical Cross-Checks</h5>
      ${runtimeRows([
        ["all_required_ok", vision.all_required_ok === undefined ? "-" : vision.all_required_ok],
        ["required", vision.required || []],
        ["vision_motion_confirmed", physical.vision_motion_confirmed === undefined ? "-" : physical.vision_motion_confirmed],
        ["specimen_alignment_ok", physical.specimen_alignment_ok === undefined ? "-" : physical.specimen_alignment_ok],
        ["fixture_safe_to_access", physical.fixture_safe_to_access === undefined ? "-" : physical.fixture_safe_to_access],
        ["evidence_frame_ids", physical.evidence_frame_ids || vision.evidence_frame_ids || []],
      ])}
      ${renderReportList(visionItems, "No Vision cross-check result recorded.", 24)}
      <h5>UTM Data Ledger</h5>
      ${runtimeRows([
        ["status", data.status || equipmentResult.status || "-"],
        ["save_method", data.save_method || "-"],
        ["save_attempted_by_agent", data.save_attempted_by_agent === undefined ? "-" : data.save_attempted_by_agent],
        ["save_confirmation_screen_ok", data.save_confirmation_screen_ok === undefined ? "-" : data.save_confirmation_screen_ok],
        ["save_export_responsibility_ok", cross.save_export_responsibility_ok === undefined ? (liveSaveAudit.ok === undefined ? "-" : liveSaveAudit.ok) : cross.save_export_responsibility_ok],
        ["recognized_save_method", liveSaveAudit.recognized_save_method === undefined ? "-" : liveSaveAudit.recognized_save_method],
        ["windows_path", data.windows_path || liveSaveAudit.windows_path || "-"],
        ["linux_path", data.linux_path || liveSaveAudit.linux_path || equipmentResult.result_file || equipmentResult.utm_csv_path || packet.result_file || handoff.result_file || "-"],
        ["sha256", data.sha256 || "-"],
        ["size_bytes", data.size_bytes === undefined ? "-" : data.size_bytes],
        ["row_count_probe", data.row_count_probe === undefined ? "-" : data.row_count_probe],
        ["columns_probe", data.columns_probe || []],
      ])}
      <h5>Save/Export Responsibility</h5>
      ${runtimeRows([
        ["responsibility_ok", cross.save_export_responsibility_ok === undefined ? (liveSaveAudit.ok === undefined ? "-" : liveSaveAudit.ok) : cross.save_export_responsibility_ok],
        ["save_method", data.save_method || liveSaveAudit.save_method || "-"],
        ["save_attempted_by_agent", data.save_attempted_by_agent === undefined ? (liveSaveAudit.save_attempted_by_agent === undefined ? "-" : liveSaveAudit.save_attempted_by_agent) : data.save_attempted_by_agent],
        ["save_confirmation_screen_ok", data.save_confirmation_screen_ok === undefined ? (liveSaveAudit.save_confirmation_screen_ok === undefined ? "-" : liveSaveAudit.save_confirmation_screen_ok) : data.save_confirmation_screen_ok],
        ["recognized_save_method", liveSaveAudit.recognized_save_method === undefined ? "-" : liveSaveAudit.recognized_save_method],
        ["windows_path", data.windows_path || liveSaveAudit.windows_path || "-"],
        ["linux_path", data.linux_path || liveSaveAudit.linux_path || equipmentResult.result_file || equipmentResult.utm_csv_path || packet.result_file || handoff.result_file || "-"],
      ])}
      <h5>Handoff Gate / Blocking Reasons</h5>
      ${runtimeRows([
        ["screen_started", cross.screen_started === undefined ? "-" : cross.screen_started],
        ["physical_motion_started", cross.physical_motion_started === undefined ? "-" : cross.physical_motion_started],
        ["save_completed", cross.save_completed === undefined ? "-" : cross.save_completed],
        ["data_file_created", cross.data_file_created === undefined ? "-" : cross.data_file_created],
        ["data_parse_probe_ok", cross.data_parse_probe_ok === undefined ? "-" : cross.data_parse_probe_ok],
        ["screen_evidence_complete", cross.screen_evidence_complete === undefined ? "-" : cross.screen_evidence_complete],
        ["linux_artifact_pulled", cross.linux_artifact_pulled === undefined ? "-" : cross.linux_artifact_pulled],
        ["save_export_responsibility_ok", cross.save_export_responsibility_ok === undefined ? (liveSaveAudit.ok === undefined ? "-" : liveSaveAudit.ok) : cross.save_export_responsibility_ok],
        ["vision_evidence_complete", cross.vision_evidence_complete === undefined ? "-" : cross.vision_evidence_complete],
        ["equipment_status", decision.equipment_status || equipmentResult.status || "-"],
        ["handoff_status", decision.handoff_status || handoff.status || packet.status || "-"],
        ["failure_code", decision.failure_code || equipmentResult.failure_code || handoff.failure_code || "-"],
        ["next_agent", decision.recommended_next_agent || packet.next_action || "-"],
      ])}
      ${renderReportList(blockingReasons, "No blocking reasons recorded.", 24)}
      <h5>Safety Gate / Guardian</h5>
      ${runtimeRows([
        ["guardian_status", packet.guardian_status || (hardwareAlert.failure_code ? "block" : "-")],
        ["blocks_workflow", hardwareAlert.blocks_workflow === undefined ? (guardianContract.ok_for_next_stage === false ? true : "-") : hardwareAlert.blocks_workflow],
        ["requires_human_approval", hardwareAlert.requires_ack === undefined ? (guardianDecision.requires_human_approval === undefined ? guardianContract.requires_human_approval ?? "-" : guardianDecision.requires_human_approval) : hardwareAlert.requires_ack],
        ["guardian_route_hint", hardwareAlert.guardian_route_hint || guardianDecision.recommended_action || "-"],
        ["guardian_decision", guardianDecision.decision || "-"],
        ["risk_score", hardwareAlert.risk_score === undefined ? guardianDecision.risk_score ?? "-" : hardwareAlert.risk_score],
        ["active_failure_code", hardwareAlert.failure_code || decision.failure_code || equipmentResult.failure_code || "-"],
        ["incident_count", incidentRecords.length],
      ])}
      ${renderReportList(riskFlags, "No Guardian risk flags recorded.", 16)}
      <h5>Live Evidence Audit</h5>
      ${runtimeRows([
        ["required_for_handoff", liveAudit.required_for_handoff === undefined ? "-" : liveAudit.required_for_handoff],
        ["screen_evidence_ok", liveScreenAudit.ok === undefined ? "-" : liveScreenAudit.ok],
        ["missing_screen_checkpoints", liveScreenAudit.missing_checkpoints || []],
        ["linux_artifact_pull_ok", livePullAudit.ok === undefined ? "-" : livePullAudit.ok],
        ["linux_pull_status", livePullAudit.status || "-"],
        ["linux_path", livePullAudit.linux_path || "-"],
        ["save_export_ok", liveSaveAudit.ok === undefined ? "-" : liveSaveAudit.ok],
        ["save_export_method", liveSaveAudit.save_method || "-"],
        ["save_export_windows_path", liveSaveAudit.windows_path || "-"],
        ["vision_evidence_ok", liveVisionAudit.ok === undefined ? "-" : liveVisionAudit.ok],
        ["vision_frame_ids", liveVisionAudit.evidence_frame_ids || []],
        ["request_log_ok", liveRequestAudit.ok === undefined ? "-" : liveRequestAudit.ok],
        ["request_log_path", liveRequestAudit.path || "-"],
        ["request_log_execute_seen", liveRequestAudit.execute_event_seen === undefined ? "-" : liveRequestAudit.execute_event_seen],
        ["request_log_execute_count", liveRequestAudit.execute_event_count === undefined ? "-" : liveRequestAudit.execute_event_count],
        ["request_log_last_execute_at", liveRequestAudit.last_execute_at || "-"],
      ])}
      <h5>Artifact / Evidence Ledger</h5>
      ${runtimeRows([
        ["artifact_refs", artifactRefs.length ? artifactRefs : evidenceRefs],
        ["screen_evidence_refs", screenEvidenceRefs],
        ["data_evidence_refs", dataEvidenceRefs],
      ])}
      ${renderReportList(artifactItems, "No bridge artifacts recorded.", 24)}
      <h5>Failure / Recovery</h5>
      ${runtimeRows([
        ["status", recovery.status || "-"],
        ["operator_intervention_required", recovery.operator_intervention_required === undefined ? "-" : recovery.operator_intervention_required],
        ["retry_count", recovery.retry_count === undefined ? "-" : recovery.retry_count],
        ["fallback_macros", recovery.fallback_macros || []],
        ["recommended_action", recovery.recommended_action || "-"],
      ])}
      ${renderReportList(retryItems, "No failure or retry table recorded.", 24)}
      <h5>Evidence Refs</h5>
      ${renderReportList(evidenceRefs, "No UTM data evidence refs recorded.", 12)}
    </div>
  `;
}

function renderAnalysisReportDetails(report) {
  const analysis = latestAnalysisPayload(report) || {};
  const source = analysis.source || {};
  const fingerprint = source.fingerprint || {};
  const columnMapping = source.column_mapping || {};
  const metrics = analysis.utm_metrics || {};
  const quality = analysis.quality_gate || analysis.data_quality_gate || {};
  const comparison = analysis.comparison || {};
  const femComparison = analysis.fem_utm_comparison || {};
  const femResult = analysis.fem_result || {};
  const femMetrics = analysis.fem_metrics || {};
  const femLoop = analysis.fem_agentic_loop || {};
  const caeResult = analysis.cae_result || {};
  const artifacts = analysis.analysis_artifacts || {};
  const boHandoff = latestAnalysisBoHandoff(report) || {};
  const failureTags = Array.isArray(analysis.failure_tags) ? analysis.failure_tags : [];
  const closedLoopSources = Array.isArray(analysis.closed_loop_sources) ? analysis.closed_loop_sources : [];
  const artifactRows = Object.entries(artifacts).map(([key, value]) => `${key} · ${renderRuntimeValue(value)}`);
  return `
    <div class="live-agent-specific-report-detail">
      <h5>Raw Data Ledger</h5>
      ${runtimeRows([
        ["source", source.source || "-"],
        ["parser_id", source.parser_id || source.format || "-"],
        ["path", source.path || "-"],
        ["sha256", fingerprint.sha256 || "-"],
        ["size_bytes", fingerprint.size_bytes === undefined ? "-" : fingerprint.size_bytes],
        ["column_mapping_confidence", columnMapping.column_mapping_confidence === undefined ? "-" : columnMapping.column_mapping_confidence],
        ["unit_mapping_confidence", columnMapping.unit_mapping_confidence === undefined ? "-" : columnMapping.unit_mapping_confidence],
      ])}
      <h5>UTM Metrics / Quality Gate</h5>
      ${runtimeRows([
        ["peak_force_N", metrics.peak_force_N ?? "-"],
        ["initial_stiffness_N_per_mm", metrics.initial_stiffness_N_per_mm ?? "-"],
        ["compressive_strength_MPa", metrics.compressive_strength_MPa ?? "-"],
        ["apparent_modulus_MPa", metrics.apparent_modulus_MPa ?? "-"],
        ["energy_absorption_mJ", metrics.energy_absorption_mJ ?? "-"],
        ["specific_energy_absorption_J_per_g", metrics.specific_energy_absorption_J_per_g ?? "-"],
        ["ok_for_metrics", quality.ok_for_metrics === undefined ? "-" : quality.ok_for_metrics],
        ["ok_for_bo", quality.ok_for_bo === undefined ? "-" : quality.ok_for_bo],
        ["quality_score", quality.score === undefined ? "-" : quality.score],
        ["quality_warnings", quality.warnings || []],
      ])}
      <h5>FEM / FEniCSx / CAE Evidence</h5>
      ${runtimeRows([
        ["closed_loop_sources", closedLoopSources],
        ["fenicsx_status", femResult.status || "-"],
        ["fenicsx_backend", femResult.solver_backend || "-"],
        ["fem_cache", femResult.cache_status || "-"],
        ["predicted_peak_force_N", femMetrics.predicted_peak_force_N ?? "-"],
        ["predicted_stiffness_N_per_mm", femMetrics.predicted_initial_stiffness_N_per_mm ?? "-"],
        ["cae_status", caeResult.status || "-"],
        ["fem_utm_agreement", femComparison.agreement_score === undefined ? "-" : femComparison.agreement_score],
        ["fem_utm_tags", femComparison.discrepancy_tags || []],
      ])}
      <h5>LLM Agentic FEM Loop</h5>
      ${runtimeRows([
        ["loop_status", femLoop.status || "-"],
        ["llm_plan_source", femLoop.llm_plan && femLoop.llm_plan.source ? femLoop.llm_plan.source : "-"],
        ["selected_iteration", femLoop.selected_iteration === undefined ? "-" : femLoop.selected_iteration],
        ["acceptance_threshold", femLoop.acceptance_threshold === undefined ? "-" : femLoop.acceptance_threshold],
        ["tool_sequence", femLoop.tool_sequence || []],
        ["safety_rule", femLoop.safety_rule || "-"],
      ])}
      ${renderReportList((femLoop.iterations || []).map((item) => `iter=${item.iteration} · mesh=${item.mesh_size_mm} mm · agreement=${renderRuntimeValue(item.agreement_score)} · accepted=${renderRuntimeValue(item.accepted)} · cache=${item.cache_status || "-"}`), "No FEM agentic iterations recorded.", 12)}
      <h5>BO Handoff / Loop Comparison</h5>
      ${runtimeRows([
        ["bo_schema", boHandoff.schema_version || "-"],
        ["ok_for_bo", boHandoff.ok_for_bo === undefined ? "-" : boHandoff.ok_for_bo],
        ["objective", boHandoff.objective || {}],
        ["comparison_mode", comparison.mode || "-"],
        ["comparison_summary", comparison.summary || "-"],
        ["failure_tags", failureTags],
      ])}
      <h5>Analysis Artifact Ledger</h5>
      ${renderReportList(artifactRows, "No Analysis artifact paths recorded.", 28)}
    </div>
  `;
}


function renderKnowledgeReportDetails(report) {
  const payload = latestKnowledgePayload(report) || {};
  const knowledgeReport = latestKnowledgeReport(report) || {};
  const context = latestKnowledgeContext(report) || {};
  const evolution = latestKnowledgeEvolutionProposal(report) || {};
  const intake = knowledgeReport.memory_intake || {};
  const quality = knowledgeReport.evidence_quality || context.evidence_quality || {};
  const dataQuality = knowledgeReport.data_quality_map || {};
  const failures = Array.isArray(knowledgeReport.failure_patterns) ? knowledgeReport.failure_patterns : [];
  const successes = Array.isArray(knowledgeReport.success_patterns) ? knowledgeReport.success_patterns : [];
  const performance = Array.isArray(knowledgeReport.agent_performance_records) ? knowledgeReport.agent_performance_records : [];
  const packs = Array.isArray(evolution.evidence_packs) ? evolution.evidence_packs : [];
  const prefill = Array.isArray(evolution.prefill_tasks) ? evolution.prefill_tasks : [];
  const outcomes = Array.isArray(evolution.outcomes) ? evolution.outcomes : Array.isArray(knowledgeReport.evolution_outcomes) ? knowledgeReport.evolution_outcomes : [];
  const graphStatus = knowledgeReport.graph_backend_status || context.graph_backend_status || payload.graph_backend_status || {};
  const memoryRows = runtimeRows([
    ["experiment_record_id", intake.experiment_record_id || "-"],
    ["agent_performance_count", intake.agent_performance_count ?? performance.length ?? 0],
    ["failure_pattern_count", intake.failure_pattern_count ?? failures.length ?? 0],
    ["success_pattern_count", intake.success_pattern_count ?? successes.length ?? 0],
    ["evolution_pack_count", intake.evolution_pack_count ?? packs.length ?? 0],
    ["retrieval_coverage", payload.retrieval_coverage ?? context.retrieval?.coverage ?? "-"],
    ["artifact_link_coverage", quality.artifact_link_coverage ?? "-"],
    ["agent_report_coverage", quality.agent_report_coverage ?? "-"],
  ]);
  const failureItems = failures.map((item) => `${item.pattern_id || item.failure_type || "failure"} · recurrence=${renderRuntimeValue(item.recurrence_count, "1")} · ${compactText(item.root_cause_hypothesis || item.failure_type || "", 160)}`);
  const successItems = successes.map((item) => `${item.skill_id || item.scope || "success"} · agent=${item.agent_id || "-"} · ${compactText(item.procedure_summary || item.scope || "", 160)}`);
  const performanceItems = performance.map((item) => `${item.agent_id || item.stage || "agent"} · status=${item.status || "-"} · score=${renderRuntimeValue(item.score)} · missing=${renderRuntimeValue((item.signals || {}).missing_required_fields || [])}`);
  const packItems = packs.map((pack) => `${pack.pack_id || "pack"} · ${pack.target_type || "target"}:${pack.target_id || "-"} · priority=${renderRuntimeValue(pack.priority)} · ${compactText(pack.objective || (pack.why_this_target || []).join("; "), 180)}`);
  const prefillItems = prefill.map((task) => `${task.target_type || "target"}:${task.target_id || "-"} · ${compactText(task.objective || renderRuntimeValue(task.constraints || {}), 180)}`);
  const outcomeItems = outcomes.map((item) => `${item.variant_id || item.outcome_id || "variant"} · ${item.target_type || "target"}:${item.target_id || "-"} · verdict=${item.verdict || "observe"} · rollback=${renderRuntimeValue(item.rollback_recommended)}`);
  const missingArtifacts = Array.isArray(dataQuality.missing_artifacts) ? dataQuality.missing_artifacts : [];
  return `
    <div class="live-agent-specific-report-detail live-agent-specific-knowledge-details">
      <h5>Memory Ledger</h5>
      ${memoryRows}
      <h5>Failure Pattern Memory</h5>
      ${renderReportList(failureItems, "No failure pattern recorded.", 12)}
      <h5>Success / Skill Library</h5>
      ${renderReportList(successItems, "No reusable success pattern recorded.", 12)}
      <h5>Agent Performance Ledger</h5>
      ${renderReportList(performanceItems, "No agent performance record available.", 16)}
      <h5>Self-Evolution Evidence Packs</h5>
      ${renderReportList(packItems, "No evidence pack prepared.", 10)}
      <h5>Evolution Lab Prefill</h5>
      ${renderReportList(prefillItems, "No Evolution Lab prefill task prepared.", 8)}
      <h5>Evolution Outcome Attribution</h5>
      ${renderReportList(outcomeItems, "No activated variant outcome attribution recorded yet.", 8)}
      <h5>Optional Graph Backend</h5>
      ${runtimeRows([
        ["enabled", graphStatus.enabled === undefined ? false : graphStatus.enabled],
        ["backend", graphStatus.backend || "disabled"],
        ["ok", graphStatus.ok === undefined ? "-" : graphStatus.ok],
        ["nodes_written", graphStatus.nodes_written ?? graphStatus.node_count ?? "-"],
        ["edges_written", graphStatus.edges_written ?? graphStatus.edge_count ?? "-"],
        ["error", graphStatus.error || ""],
      ])}
      <h5>Data Quality / Missing Evidence</h5>
      ${renderReportList(missingArtifacts.map((item) => renderRuntimeValue(item)), "No missing artifact recorded.", 12)}
    </div>
  `;
}

function renderBoReportDetails(report) {
  const boResult = latestReportBoResult(report) || {};
  if (!boResult || typeof boResult !== "object" || !Object.keys(boResult).length) return "";
  const reasoning = boResult.reasoning || {};
  const strategy = reasoning.strategy_recommendation || {};
  const recommendation = boResult.recommendation || {};
  const nextDesign = boResult.next_design_request || {};
  const prior = boResult.prior_summary || {};
  const hypotheses = Array.isArray(reasoning.hypotheses) ? reasoning.hypotheses.slice(0, 6) : [];
  const ranking = Array.isArray(boResult.candidate_ranking) ? boResult.candidate_ranking.slice(0, 8) : Array.isArray(boResult.candidate_pool) ? boResult.candidate_pool.slice(0, 8) : [];
  const artifacts = boResult.artifacts || {};
  const hypothesisItems = hypotheses.map((item) => `${item.id || "h"} · conf=${renderRuntimeValue(item.confidence)} · ${item.claim || ""}`);
  const rankingItems = ranking.map((item) => {
    const constraints = item.constraints || {};
    const llm = item.llm || {};
    return `${item.candidate_id || "candidate"} · combined=${renderRuntimeValue(item.combined_score)} · acq=${renderRuntimeValue((item.numeric || {}).acquisition_value)} · llm=${renderRuntimeValue(llm.preference_score)} · risk=${renderRuntimeValue(constraints.risk_score)} · valid=${renderRuntimeValue(constraints.valid)} · ${compactBoParams(item.parameters || {})}`;
  });
  const artifactRows = Object.entries(artifacts).map(([key, value]) => `${key} · ${renderRuntimeValue(value)}`);
  return `
    <div class="live-agent-specific-report-detail live-agent-specific-bo-details">
      <h5>Evidence / Prior Intake</h5>
      ${runtimeRows([
        ["prior_count", prior.prior_count ?? "-"],
        ["measured_count", prior.measured_count ?? "-"],
        ["failed_count", prior.failed_count ?? "-"],
        ["best_score", prior.best_score ?? "-"],
        ["knowledge_context", boResult.knowledge_context || {}],
      ])}
      <h5>Reasoning Audit</h5>
      ${runtimeRows([
        ["reasoning_schema", reasoning.schema_version || "-"],
        ["source", reasoning.source || "-"],
        ["strategy_recommendation", `${strategy.strategy || "-"} / ${strategy.acquisition || "-"}`],
        ["explore_exploit", `${renderRuntimeValue(strategy.exploration_weight)} / ${renderRuntimeValue(strategy.exploitation_weight)}`],
        ["operator_summary", reasoning.operator_summary || "-"],
      ])}
      ${renderReportList(hypothesisItems, "No BO hypotheses recorded.", 12)}
      <h5>Candidate Ranking</h5>
      ${renderReportList(rankingItems, "No candidate ranking recorded.", 16)}
      <h5>Recommendation / Handoff</h5>
      ${runtimeRows([
        ["candidate_id", recommendation.candidate_id || "-"],
        ["combined_score", recommendation.combined_score ?? "-"],
        ["why_this_candidate", recommendation.why_this_candidate || recommendation.reason || "-"],
        ["why_not_best_exploitation_only", recommendation.why_not_best_exploitation_only || "-"],
        ["next_design_schema", nextDesign.schema || "-"],
        ["next_design_status", nextDesign.status || "-"],
        ["constraints", nextDesign.constraints || recommendation.parameters || {}],
      ])}
      <h5>Artifacts</h5>
      ${renderReportList(artifactRows, "No BO artifact paths recorded.", 8)}
    </div>
  `;
}

function renderAgentSpecificReportSection(report, status, agentLabel) {
  const profile = agentSpecificReportProfile(report, status, agentLabel);
  const rows = runtimeRows(profile.rows || []);
  const checklist = renderReportList(profile.checklist || [], "No role-specific checklist recorded.");
  const orchestratorDetails = liveSelectedAgent === "orchestrator" ? renderOrchestratorReportDetails(report) : "";
  const designDetails = liveSelectedAgent === "design" ? renderDesignReportDetails(report) : "";
  const specimenDetails = liveSelectedAgent === "specimen" ? renderSpecimenReportDetails(report) : "";
  const visionDetails = liveSelectedAgent === "vision" ? renderVisionReportDetails(report) : "";
  const manipulationDetails = liveSelectedAgent === "manipulation" ? renderManipulationReportDetails(report) : "";
  const equipmentDetails = liveSelectedAgent === "equipment" ? renderEquipmentReportDetails(report) : "";
  const analysisDetails = liveSelectedAgent === "analysis" ? renderAnalysisReportDetails(report) : "";
  const knowledgeDetails = liveSelectedAgent === "knowledge" ? renderKnowledgeReportDetails(report) : "";
  const boDetails = liveSelectedAgent === "bo" ? renderBoReportDetails(report) : "";
  const guardianDetails = liveSelectedAgent === "guardian" ? renderGuardianReportDetails(report) : "";
  return `
    <section class="runtime-card-section live-report-section live-agent-specific-report">
      <h4>${escapeHtml(profile.title)}</h4>
      <p class="live-agent-specific-summary">${escapeHtml(profile.summary || "")}</p>
      ${rows}
      ${orchestratorDetails}
      ${designDetails}
      ${specimenDetails}
      ${visionDetails}
      ${manipulationDetails}
      ${equipmentDetails}
      ${analysisDetails}
      ${knowledgeDetails}
      ${boDetails}
      ${guardianDetails}
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
  const designEvidence = liveSelectedAgent === "design" ? latestDesignReport(report) : null;
  const specimenEvidence = liveSelectedAgent === "specimen" ? latestSpecimenFabricationReport(report) : null;
  const visionEvidence = liveSelectedAgent === "vision" ? latestVisionReport(report) : null;
  const manipulationEvidence = liveSelectedAgent === "manipulation" ? latestManipulationReport(report) : null;
  const reportSubtitle = latestMessage
    ? ` · ${compactText(latestMessage.content, 220)}`
    : designEvidence
      ? " · Candidate evidence, selection rationale, and handoff packet are available."
      : specimenEvidence
        ? " · Fabrication digital thread, process plan, quality gates, and handoff evidence are available."
        : visionEvidence
          ? " · Scene map, signal board, visual evidence, and freshness-gated handoff are available."
          : manipulationEvidence
            ? " · Pi0.5/LeRobot preflight, SARM progress, and robot_task_result handoff are available."
            : " · No report yet. Backend/Timeline remain available.";
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
          <p><span class="live-report-role-tag">${escapeHtml(profile.title)}</span>${escapeHtml(reportSubtitle)}</p>
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
    if (typeof key === "string" && key.includes(".")) {
      let cursor = payload;
      let found = true;
      for (const part of key.split(".")) {
        if (!cursor || typeof cursor !== "object" || cursor[part] === undefined || cursor[part] === null || cursor[part] === "") {
          found = false;
          break;
        }
        cursor = cursor[part];
      }
      if (found) return cursor;
    }
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
  const devicePattern = /guardian|incident|gate|device|printer|prusa|slicer|gcode|robot|lerobot|teleop|rollout|camera|vision|utm|bridge|windows|pyautogui|equipment|gpu|llm|stream|sync|sensor|fault|unsafe|failed|error|timeout|connection|disconnect/;
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

async function requestLiveGuardianStatus(runId, options = {}) {
  const endpoint = runId ? `/api/runs/${encodeURIComponent(runId)}/guardian/status` : "/api/guardian/status";
  try {
    const payload = await fetchJsonOrThrow(endpoint);
    liveGuardianStatus = normalizeGuardianStatusPayload(payload) || liveGuardianStatus;
    return liveGuardianStatus;
  } catch (err) {
    if (!options.silent) setChatStatus(`GUARDIAN STATUS ERROR: ${err}`, "warning");
    return null;
  }
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
    fetch(`/api/runs/${encodeURIComponent(runId)}/guardian/status`).then((res) => (res.ok ? res.json() : null)).catch(() => null),
  ];
  const [events, artifacts, approvals, guardianStatus] = await Promise.all(endpoints);
  liveRunEvents = Array.isArray(events.events) ? events.events : [];
  syncOperatorReportStateFromEvents({ preserveLocal: false });
  liveRunArtifacts = Array.isArray(artifacts.artifacts) ? artifacts.artifacts : [];
  liveApprovals = normalizedLiveApprovals({
    approvals: Array.isArray(approvals.approvals) ? approvals.approvals : [],
    pending: Array.isArray(approvals.pending) ? approvals.pending : [],
    resolved: Array.isArray(approvals.resolved) ? approvals.resolved : [],
  });
  liveGuardianStatus = normalizeGuardianStatusPayload(guardianStatus) || normalizeGuardianStatusPayload(liveLastSnapshot.guardian_status) || liveGuardianStatus;
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
  liveGuardianStatus = normalizeGuardianStatusPayload(payload.guardian_status) || normalizeGuardianStatusPayload(liveLastSnapshot.guardian_status) || liveGuardianStatus;
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
    guardian_status: liveGuardianStatusPayload(),
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
      liveGuardianStatus = normalizeGuardianStatusPayload(liveLastSnapshot.guardian_status) || liveGuardianStatus;
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
      if (eventType.startsWith("planning_") || eventType === "planning_message" || eventType.startsWith("approval.") || eventType.includes("agent") || eventType.includes("run") || eventType.includes("device") || eventType.includes("guardian") || eventType.includes("incident") || eventType.includes("evolution")) {
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
  const guardianNoteButton = event.target.closest(".live-guardian-note-action");
  if (guardianNoteButton) {
    const incidentId = guardianNoteButton.dataset.incidentId || "incident";
    const reasonCode = guardianNoteButton.dataset.reasonCode || "";
    liveSelectedAgent = "guardian";
    setLiveChatTargetMode(liveChatTargetForAgent("guardian"));
    const noteText = window.prompt(`Guardian incident note for ${incidentId}${reasonCode ? ` (${reasonCode})` : ""}`, "");
    if (noteText && noteText.trim()) {
      const runId = liveCurrentRunId();
      const endpoint = runId
        ? `/api/runs/${encodeURIComponent(runId)}/guardian/incidents/${encodeURIComponent(incidentId)}/notes`
        : `/api/guardian/incidents/${encodeURIComponent(incidentId)}/notes`;
      fetchJsonOrThrow(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: noteText.trim(), operator: "live_gui", source: "guardian_report" }),
      })
        .then((data) => {
          if (data.event) liveRunEvents.push(data.event);
          setChatStatus("GUARDIAN NOTE SAVED", "ok");
          requestLiveGuardianStatus(liveCurrentRunId(), { silent: true }).finally(() => renderLiveRuntime(liveLastSession));
        })
        .catch((err) => setChatStatus(`GUARDIAN NOTE ERROR: ${err}`, "warning"));
    } else {
      draftRuntimeChat(`Guardian incident note for ${incidentId}${reasonCode ? ` (${reasonCode})` : ""}: `, "guardian_note");
      recordLiveOperatorEvent(
        "incident_note_requested",
        `Guardian incident note requested for ${incidentId}.`,
        { incident_id: incidentId, reason_code: reasonCode, source_action: "guardian.incident_note" },
        "operator.guardian"
      ).catch(() => {});
      setChatStatus("GUARDIAN NOTE", "idle");
    }
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
