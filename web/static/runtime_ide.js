/*
File purpose:
- Runtime IDE frontend logic for graph/module config validation, versioning, and live node dashboard.

Key classes/functions:
- loadGraph
- renderGraph
- selectNode
- applyTransitionEdit
- connectEventStream

Inputs/outputs:
- Input: Runtime graph/module API responses and SSE runtime events
- Output: graph/module validation, compile, dry-run, versioned saves, and active-node visualization

Dependencies:
- Fetch API
- EventSource

Modification guide:
- Safe places to edit: rendering details and log labels.
- Risky places to edit: endpoint paths and payload shapes.
*/

const statusDot = document.getElementById("ide-status-dot");
const statusLabel = document.getElementById("ide-status-label");
const statusDetail = document.getElementById("ide-status-detail");
const graphIdBadge = document.getElementById("ide-graph-id");
const graphSelect = document.getElementById("ide-graph-select");
const graphCanvas = document.getElementById("ide-graph-canvas");
const draftSafetyStrip = document.getElementById("ide-draft-safety-strip");
const graphTabsOutput = document.getElementById("ide-graph-tabs");
const minimapOutput = document.getElementById("ide-minimap");
const graphJson = document.getElementById("ide-graph-json");
const dryRunOutput = document.getElementById("ide-dry-run-output");
const moduleSelect = document.getElementById("ide-module-select");
const moduleTabsOutput = document.getElementById("ide-module-tabs");
const moduleJson = document.getElementById("ide-module-json");
const moduleSummary = document.getElementById("ide-module-summary");
const moduleGraphOutput = document.getElementById("ide-module-graph");
const handlersOutput = document.getElementById("ide-handlers-output");
const logOutput = document.getElementById("ide-log-output");
const eventFilterButtons = Array.from(document.querySelectorAll("[data-event-filter]"));
const selectedNodeBadge = document.getElementById("ide-selected-node");
const nodeInspector = document.getElementById("ide-node-inspector");
const transitionSource = document.getElementById("ide-transition-source");
const transitionTarget = document.getElementById("ide-transition-target");
const transitionConditionPreset = document.getElementById("ide-transition-condition-preset");
const transitionConditionInput = document.getElementById("ide-transition-condition");
const transitionApplyBtn = document.getElementById("ide-transition-apply-btn");
const edgeConnectBtn = document.getElementById("ide-edge-connect-btn");
const edgeDeleteBtn = document.getElementById("ide-edge-delete-btn");
const edgeRoutePreview = document.getElementById("ide-edge-route-preview");
const edgeEditStatus = document.getElementById("ide-edge-edit-status");
const liveStatusOutput = document.getElementById("ide-live-status");
const runTimelineOutput = document.getElementById("ide-run-timeline");
const artifactLineageOutput = document.getElementById("ide-artifact-lineage");
const artifactPreviewOutput = document.getElementById("ide-artifact-preview");
const agentStatusOutput = document.getElementById("ide-agent-status");
const deviceStatusOutput = document.getElementById("ide-device-status");
const metricsPanelOutput = document.getElementById("ide-metrics-panel");
const runtimeReadinessOutput = document.getElementById("ide-runtime-readiness");
const approvalQueueOutput = document.getElementById("ide-approval-queue");
const replayOutput = document.getElementById("ide-replay-output");
const eventDetailOutput = document.getElementById("ide-event-detail");
const zoomOutBtn = document.getElementById("ide-zoom-out-btn");
const zoomResetBtn = document.getElementById("ide-zoom-reset-btn");
const fitGraphBtn = document.getElementById("ide-fit-graph-btn");
const zoomInBtn = document.getElementById("ide-zoom-in-btn");
const exportYamlBtn = document.getElementById("ide-export-yaml-btn");
const importYamlBtn = document.getElementById("ide-import-yaml-btn");
const graphVersionsBtn = document.getElementById("ide-versions-btn");
const graphVersionPanel = document.getElementById("ide-version-panel");
const graphVersionOutput = document.getElementById("ide-version-output");
const activationChecklistOutput = document.getElementById("ide-activation-checklist");
const activationOverallBadge = document.getElementById("ide-activation-overall");
const yamlImportFile = document.getElementById("ide-yaml-import-file");
const runStatusLabel = document.getElementById("ide-run-status");
const runIdLabel = document.getElementById("ide-run-id");
const elapsedLabel = document.getElementById("ide-elapsed");
const objectiveSummary = document.getElementById("ide-objective-summary");
const activeAgentLabel = document.getElementById("ide-active-agent");
const currentStageLabel = document.getElementById("ide-current-stage");
const runtimeHealthLabel = document.getElementById("ide-runtime-health");
const runLauncherBadge = document.getElementById("ide-run-launcher-badge");
const runTargetSummaryOutput = document.getElementById("ide-run-target-summary");
const runLauncherDrawer = document.getElementById("ide-run-launcher-drawer");
const runModeSelect = document.getElementById("ide-run-mode");
const runBackendSelect = document.getElementById("ide-run-backend");
const runFaultStageInput = document.getElementById("ide-run-fault-stage");
const runFaultInput = document.getElementById("ide-run-fault");
const runGoalInput = document.getElementById("ide-run-goal");
const runLiveConfirmInput = document.getElementById("ide-run-live-confirm");
const livePreflightOutput = document.getElementById("ide-live-preflight");
const recordLiveGateBtn = document.getElementById("ide-record-live-gate-btn");
const runTestBtn = document.getElementById("ide-run-test-btn");
const runLiveBtn = document.getElementById("ide-run-live-btn");
const runLaunchOutput = document.getElementById("ide-run-launch-output");
const pauseRunBtn = document.getElementById("ide-pause-run-btn");
const resumeRunBtn = document.getElementById("ide-resume-run-btn");
const stopRunBtn = document.getElementById("ide-stop-run-btn");
const settingsBtn = document.getElementById("ide-settings-btn");
const nodeSearchInput = document.getElementById("ide-node-search");
const nodeListOutput = document.getElementById("ide-node-list");
const infraListOutput = document.getElementById("ide-infra-list");
const templateListOutput = document.getElementById("ide-template-list");
const moduleManagementOpenBtn = document.getElementById("ide-module-management-open-btn");
const moduleManagementInlineBtn = document.getElementById("ide-module-management-inline-btn");
const trashZone = document.getElementById("ide-trash-zone");
const designerModuleIdInput = document.getElementById("ide-designer-module-id");
const designerLabelInput = document.getElementById("ide-designer-label");
const designerCategoryInput = document.getElementById("ide-designer-category");
const designerHandlerSelect = document.getElementById("ide-designer-handler");
const designerLlmRoleInput = document.getElementById("ide-designer-llm-role");
const designerPythonFileInput = document.getElementById("ide-designer-python-file");
const designerNotesInput = document.getElementById("ide-designer-notes");
const designerCreateBtn = document.getElementById("ide-designer-create-btn");
const designerStatus = document.getElementById("ide-designer-status");

const GRAPH_GRID = 16;
const GRAPH_NODE_WIDTH = 184;
const GRAPH_NODE_HEIGHT = 76;
const MODULE_GRAPH_COLUMN_GAP = 560;
const MODULE_GRAPH_ROW_GAP = 256;
const MODULE_GRAPH_START_X = 56;
const MODULE_GRAPH_PRE_Y = 64;
const MODULE_GRAPH_INTERNAL_Y = 220;
const MAIN_GRAPH_TAB_ID = "main-system";
const MODULE_TAB_PREFIX = "module:";
const PORT_SIDES = ["top", "right", "bottom", "left"];

const ICON_MAP = {
  orchestrator: "/static/runtime_icons/orchestrator.svg",
  play: "/static/runtime_icons/play.svg",
  design_agent: "/static/runtime_icons/design_agent.svg",
  specimen_maker: "/static/runtime_icons/specimen_maker.svg",
  vision_agent: "/static/runtime_icons/vision_agent.svg",
  manipulation_agent: "/static/runtime_icons/manipulation_agent.svg",
  equipment_agent: "/static/runtime_icons/equipment_agent.svg",
  analysis_agent: "/static/runtime_icons/analysis_agent.svg",
  knowledge_agent: "/static/runtime_icons/knowledge_agent.svg",
  bo_agent: "/static/runtime_icons/bo_agent.svg",
  guardian_agent: "/static/runtime_icons/guardian_agent.svg",
  complete: "/static/runtime_icons/complete.svg",
  error: "/static/runtime_icons/error.svg",
  artifact: "/static/runtime_icons/artifact.svg",
  mcp_tools: "/static/runtime_icons/mcp_tools.svg",
  nemoclaw_ollama: "/static/runtime_icons/nemoclaw_ollama.svg",
  memory_logs: "/static/runtime_icons/memory_logs.svg",
  device_bridges: "/static/runtime_icons/device_bridges.svg",
};

let activeGraph = null;
let availableGraphs = [];
let availableModules = [];
let availableTools = [];
let graphTabs = [];
let activeGraphTabId = MAIN_GRAPH_TAB_ID;
let modulePayloadCache = new Map();
let modulePayloadFetches = new Set();
let activeModuleId = "";
let availableHandlers = [];
let availableHandlerMetadata = new Map();
let latestStateSnapshot = null;
let nodeSearchQuery = "";
let selectedNodeId = "";
let visitedRuntimeStages = new Set();
let activeRuntimeStage = "";
let activeRuntimeEdge = null;
let recentRuntimeEvents = [];
let currentRunId = "";
let currentArtifacts = [];
let currentApprovals = { approvals: [], pending: [], resolved: [] };
let selectedTimelineEventIndex = -1;
let graphZoom = 1;
let nodeDrag = null;
let trashZoneHover = false;
let suppressNextNodeClick = false;
let edgeConnectMode = false;
let edgeConnectSource = "";
let edgeConnectDraft = null;
let edgeDrag = null;
let edgeDragHoverNodeId = "";
let nodeClickTimer = null;
let activationEvidence = { validation: null, compile: null, dry_run: null, save: null, dirty: false, reason: "initial" };
let modulePreflightEvidence = new Map();
let liveGateSnapshot = { graph_id: "", gate_ok: false, has_record: false, dry_run_record: {}, checking: false };
let ideActionLogs = [];
let eventLogFilter = "all";

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function runtimeIdeUrlParams() {
  return new URLSearchParams(window.location.search || "");
}

function deepLinkGraphId() {
  const params = runtimeIdeUrlParams();
  return params.get("graph") || params.get("graph_id") || "";
}

function deepLinkNodeRef() {
  const params = runtimeIdeUrlParams();
  return params.get("node") || params.get("node_id") || params.get("stage") || "";
}


function cloneConfig(value) {
  if (value === undefined || value === null) return value;
  return JSON.parse(JSON.stringify(value));
}

function stableConfigValue(value) {
  if (Array.isArray(value)) return value.map((item) => stableConfigValue(item));
  if (!value || typeof value !== "object") return value;
  return Object.keys(value)
    .sort()
    .reduce((acc, key) => {
      acc[key] = stableConfigValue(value[key]);
      return acc;
    }, {});
}

function graphConfigFingerprint(graph) {
  if (!graph || typeof graph !== "object") return "";
  const normalized = cloneConfig(graph);
  if (normalized?.nodes) normalizeNodePositions(normalized);
  return JSON.stringify(stableConfigValue(normalized));
}

function slugify(value, fallback = "module") {
  const clean = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return clean || fallback;
}

function titleFromSlug(value) {
  return String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function moduleIconName(module) {
  const explicitIcon = String(module?.icon || module?.metadata?.icon || "").trim();
  if (explicitIcon) return explicitIcon;
  const id = String(module?.id || "").toLowerCase();
  const category = String(module?.category || "").toLowerCase();
  if (id.includes("design") || category.includes("design")) return "design_agent";
  if (id.includes("specimen") || category.includes("fabrication") || category.includes("printer")) return "specimen_maker";
  if (id.includes("vision") || category.includes("vision")) return "vision_agent";
  if (id.includes("manip") || category.includes("manipulation") || category.includes("robot")) return "manipulation_agent";
  if (id.includes("equipment") || category.includes("equipment")) return "equipment_agent";
  if (id.includes("analysis") || category.includes("analysis") || category.includes("cae")) return "analysis_agent";
  if (id.includes("knowledge") || category.includes("knowledge")) return "knowledge_agent";
  if (id.includes("bo") || category.includes("optimization")) return "bo_agent";
  if (id.includes("guardian") || category.includes("guardian")) return "guardian_agent";
  if (id.includes("orchestrator") || category.includes("orchestration")) return "orchestrator";
  return "artifact";
}

function runtimeNodeIconMarkup(iconName) {
  const key = String(iconName || "").trim();
  const url = ICON_MAP[key];
  if (url) {
    return `<span class="runtime-ide-node-icon"><img src="${escapeHtml(url)}" alt="${escapeHtml(key)}" loading="lazy" /></span>`;
  }
  return `<span class="runtime-ide-node-icon">${escapeHtml(String(key || "node").slice(0, 2).toUpperCase())}</span>`;
}

function compiledGraphSummaryMarkup(compiledGraph) {
  if (!compiledGraph || typeof compiledGraph !== "object") return "";
  const edges = Array.isArray(compiledGraph.executable_edges) ? compiledGraph.executable_edges : [];
  const logicalEdges = Array.isArray(compiledGraph.logical_edges) ? compiledGraph.logical_edges : [];
  const edgeRows = edges
    .slice(0, 10)
    .map((edge) => {
      const condition = edge.condition ? ` <small>if ${escapeHtml(edge.condition)}</small>` : "";
      return `<div>${escapeHtml(edge.source)} -> ${escapeHtml(edge.target)}${condition}</div>`;
    })
    .join("");
  return `
    <div class="runtime-compiled-summary">
      <strong>Compiled executable graph</strong>
      <small>entry=${escapeHtml(compiledGraph.entry_node)} · nodes=${escapeHtml(compiledGraph.node_count)} · runtime_edges=${escapeHtml(compiledGraph.edge_count)} · logical_edges=${escapeHtml(compiledGraph.logical_edge_count ?? logicalEdges.length)}</small>
      <div class="runtime-compiled-edge-list">${edgeRows || "<div>No executable edges.</div>"}</div>
    </div>
  `;
}

function moduleValidationResultMarkup(result, moduleId = "") {
  const errors = Array.isArray(result?.errors) ? result.errors : [];
  const ok = Boolean(result?.ok);
  return `
    <div class="runtime-module-evidence-card ${ok ? "ok" : "error"}">
      <div class="runtime-module-evidence-head">
        <strong>Module validation ${ok ? "passed" : "failed"}</strong>
        <small>${escapeHtml(moduleId || "module")} · handler/tool/safety schema check</small>
      </div>
      ${
        errors.length
          ? `<ul>${errors.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
          : `<p>Module config is schema-valid and uses allowlisted runtime handlers/tools.</p>`
      }
    </div>
  `;
}

function moduleDryRunResultMarkup(result, moduleId = "") {
  const sequence = Array.isArray(result?.sequence) ? result.sequence : [];
  const summary = result?.summary && typeof result.summary === "object" ? result.summary : {};
  const ok = Boolean(result?.ok);
  const rows = sequence
    .map((item) => {
      const executable = item.executable ? "handler-backed" : "checkpoint";
      const handler = item.handler || item.kind || "checkpoint";
      return `
        <div class="runtime-module-evidence-step">
          <strong>${escapeHtml(item.step)}. ${escapeHtml(item.label || item.id || "step")}</strong>
          <small>${escapeHtml(item.phase || "internal_graph")} · ${escapeHtml(handler)} · ${escapeHtml(executable)}</small>
        </div>
      `;
    })
    .join("");
  return `
    <div class="runtime-module-evidence-card ${ok ? "ok" : "error"}">
      <div class="runtime-module-evidence-head">
        <strong>Module dry-run ${ok ? "passed" : "failed"}</strong>
        <small>${escapeHtml(moduleId || "module")} · ${escapeHtml(sequence.length)} step(s) · no hardware calls</small>
      </div>
      <div class="runtime-module-evidence-metrics">
        <span><strong>${escapeHtml(summary.pre_execution_count ?? 0)}</strong><small>pre</small></span>
        <span><strong>${escapeHtml(summary.internal_graph_count ?? 0)}</strong><small>internal</small></span>
        <span><strong>${escapeHtml(summary.executable_count ?? 0)}</strong><small>executable</small></span>
        <span><strong>${escapeHtml(summary.checkpoint_count ?? 0)}</strong><small>checkpoint</small></span>
      </div>
      <div class="runtime-module-evidence-steps">${rows || "<div>No configured module steps.</div>"}</div>
    </div>
  `;
}

function setStatus(kind, label, detail) {
  statusDot.className = `status-dot ${kind}`;
  statusLabel.textContent = label;
  statusDetail.textContent = detail;
}

function eventConsoleSeverity(kind) {
  const value = String(kind || "info").toLowerCase();
  if (value.includes("error") || value.includes("fail")) return "error";
  if (value.includes("warn") || value.includes("blocked") || value.includes("pending")) return "warn";
  return "info";
}

function eventConsoleTimestampLabel(value, fallbackMs = Date.now()) {
  const raw = String(value || "").trim();
  const date = raw ? new Date(raw) : new Date(fallbackMs);
  if (!Number.isNaN(date.getTime())) return date.toLocaleTimeString();
  return raw || new Date(fallbackMs).toLocaleTimeString();
}

function eventConsoleSortValue(row) {
  const parsed = Date.parse(row.timestamp || "");
  return Number.isNaN(parsed) ? Number(row.createdMs || 0) : parsed;
}

function runtimeEventConsoleRows() {
  return recentRuntimeEvents.slice(0, 80).map((event, index) => {
    const severity = eventConsoleSeverity(eventSeverity(event));
    const stage = eventStage(event) || event.node_id || "runtime";
    const node = eventNode(event);
    const handler = node?.handler || event.agent || event.payload?.agent || "runtime";
    return {
      source: "runtime",
      severity,
      type: eventTypeName(event),
      timestamp: eventTimestamp(event),
      createdMs: Date.now() - index,
      stage,
      detail: `${stage} · ${handler}`,
      message: eventPayloadSummary(event),
      event_id: event.event_id || "",
    };
  });
}

function renderEventLog() {
  if (!logOutput) return;
  const rows = [...runtimeEventConsoleRows(), ...ideActionLogs]
    .sort((a, b) => eventConsoleSortValue(b) - eventConsoleSortValue(a))
    .slice(0, 120);
  const filtered = eventLogFilter === "all" ? rows : rows.filter((row) => row.severity === eventLogFilter);
  eventFilterButtons.forEach((button) => {
    const active = button.getAttribute("data-event-filter") === eventLogFilter;
    button.classList.toggle("active", active);
  });
  if (!filtered.length) {
    logOutput.innerHTML = `<div class="runtime-event-console-empty">No ${escapeHtml(eventLogFilter)} events in the current buffer.</div>`;
    return;
  }
  const counts = rows.reduce((acc, row) => {
    acc[row.severity] = (acc[row.severity] || 0) + 1;
    acc.total += 1;
    return acc;
  }, { total: 0, info: 0, warn: 0, error: 0 });
  logOutput.innerHTML = `
    <div class="runtime-event-console-summary">
      <span><strong>${escapeHtml(counts.total)}</strong><small>all</small></span>
      <span class="info"><strong>${escapeHtml(counts.info)}</strong><small>info</small></span>
      <span class="warn"><strong>${escapeHtml(counts.warn)}</strong><small>warn</small></span>
      <span class="error"><strong>${escapeHtml(counts.error)}</strong><small>error</small></span>
    </div>
    <div class="runtime-event-console-list">
      ${filtered.map((row) => `
        <div class="runtime-event-console-row ${escapeHtml(row.severity)}">
          <span class="runtime-event-source ${escapeHtml(row.source)}">${escapeHtml(row.source)}</span>
          <span class="runtime-timeline-severity-dot ${escapeHtml(row.severity === "info" ? "ok" : row.severity)}"></span>
          <div>
            <strong>${escapeHtml(row.type || "event")}</strong>
            <small>${escapeHtml(eventConsoleTimestampLabel(row.timestamp, row.createdMs))} · ${escapeHtml(row.detail || "runtime")}</small>
            <p>${escapeHtml(row.message || "no message")}</p>
          </div>
          ${row.source === "runtime" && row.event_id ? `<button type="button" class="btn tiny runtime-event-console-inspect" data-event-log-event-id="${escapeHtml(row.event_id)}">Inspect</button>` : ""}
        </div>
      `).join("")}
    </div>
  `;
  logOutput.querySelectorAll("[data-event-log-event-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = timelineIndexForEventId(button.getAttribute("data-event-log-event-id") || "");
      if (index >= 0) inspectTimelineEvent(index).catch((err) => log(String(err), "error"));
    });
  });
}

function log(message, kind = "info") {
  const severity = eventConsoleSeverity(kind);
  ideActionLogs.unshift({
    source: "ide",
    severity,
    type: `ide.${severity}`,
    timestamp: new Date().toISOString(),
    createdMs: Date.now(),
    detail: "operator action",
    message: String(message || ""),
  });
  ideActionLogs = ideActionLogs.slice(0, 80);
  renderEventLog();
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || data.message || `${res.status} ${res.statusText}`);
  }
  return data;
}

function graphStages(graph) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const stages = nodes.map((node) => node.stage).filter(Boolean);
  const terminal = Array.isArray(graph?.terminal_stages) ? graph.terminal_stages : ["complete", "error"];
  return Array.from(new Set([...stages, ...terminal]));
}

function findNodeById(nodeId) {
  const nodes = Array.isArray(activeGraph?.nodes) ? activeGraph.nodes : [];
  return nodes.find((node) => node.id === nodeId) || null;
}

function findNodeByStage(stage) {
  const nodes = Array.isArray(activeGraph?.nodes) ? activeGraph.nodes : [];
  return nodes.find((node) => node.stage === stage || node.id === stage) || null;
}

function snapToGrid(value) {
  return Math.max(0, Math.round(Number(value || 0) / GRAPH_GRID) * GRAPH_GRID);
}

function defaultNodePosition(index) {
  const columns = 5;
  return { x: 36 + (index % columns) * 220, y: 36 + Math.floor(index / columns) * 156 };
}

function defaultModuleNodePosition(record) {
  const columns = 5;
  const row = Math.floor(Number(record?.index || 0) / columns);
  const column = Number(record?.index || 0) % columns;
  const baseY = record?.phase === "pre_execution" ? MODULE_GRAPH_PRE_Y : MODULE_GRAPH_INTERNAL_Y;
  return {
    x: MODULE_GRAPH_START_X + column * MODULE_GRAPH_COLUMN_GAP,
    y: baseY + row * MODULE_GRAPH_ROW_GAP,
  };
}

function normalizeNodePositions(graph) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  nodes.forEach((node, index) => {
    const fallback = defaultNodePosition(index);
    const source = node.position || node.metadata?.position || fallback;
    node.position = {
      x: snapToGrid(source.x ?? fallback.x),
      y: snapToGrid(source.y ?? fallback.y),
    };
  });
  return graph;
}

function graphBounds(nodes) {
  const maxX = Math.max(...nodes.map((node, index) => (node.position?.x ?? defaultNodePosition(index).x) + GRAPH_NODE_WIDTH), GRAPH_NODE_WIDTH);
  const maxY = Math.max(...nodes.map((node, index) => (node.position?.y ?? defaultNodePosition(index).y) + GRAPH_NODE_HEIGHT), GRAPH_NODE_HEIGHT);
  return { width: maxX + 96, height: maxY + 96 };
}

function nodeStage(node) {
  return node?.stage || node?.id || "";
}

function nodeMapByStageOrId(nodes) {
  const map = new Map();
  for (const node of nodes) {
    map.set(node.id, node);
    if (node.stage) map.set(node.stage, node);
  }
  return map;
}

function inferPortPair(source, target) {
  const sourceSides = PORT_SIDES || ["top", "right", "bottom", "left"];
  const targetSides = PORT_SIDES || ["top", "right", "bottom", "left"];
  const point = (node, side) => {
    const x = Number(node?.position?.x || 0);
    const y = Number(node?.position?.y || 0);
    if (side === "left") return { x, y: y + GRAPH_NODE_HEIGHT / 2 };
    if (side === "right") return { x: x + GRAPH_NODE_WIDTH, y: y + GRAPH_NODE_HEIGHT / 2 };
    if (side === "top") return { x: x + GRAPH_NODE_WIDTH / 2, y };
    if (side === "bottom") return { x: x + GRAPH_NODE_WIDTH / 2, y: y + GRAPH_NODE_HEIGHT };
    return { x: x + GRAPH_NODE_WIDTH, y: y + GRAPH_NODE_HEIGHT / 2 };
  };
  let best = { sourceSide: "right", targetSide: "left", distance: Number.POSITIVE_INFINITY };
  for (const sourceSide of sourceSides) {
    const sourcePoint = point(source, sourceSide);
    for (const targetSide of targetSides) {
      const targetPoint = point(target, targetSide);
      const distance = Math.hypot(targetPoint.x - sourcePoint.x, targetPoint.y - sourcePoint.y);
      if (distance < best.distance) best = { sourceSide, targetSide, distance };
    }
  }
  return { sourceSide: best.sourceSide, targetSide: best.targetSide };
}


function portPoint(node, side = "right") {
  const x = Number(node?.position?.x || 0);
  const y = Number(node?.position?.y || 0);
  if (side === "left") return { x, y: y + GRAPH_NODE_HEIGHT / 2 };
  if (side === "right") return { x: x + GRAPH_NODE_WIDTH, y: y + GRAPH_NODE_HEIGHT / 2 };
  if (side === "top") return { x: x + GRAPH_NODE_WIDTH / 2, y };
  if (side === "bottom") return { x: x + GRAPH_NODE_WIDTH / 2, y: y + GRAPH_NODE_HEIGHT };
  return { x: x + GRAPH_NODE_WIDTH, y: y + GRAPH_NODE_HEIGHT / 2 };
}


function stageDisplayLabel(stage = "") {
  const raw = String(stage || "");
  const parts = raw.split(":");
  if (parts.length >= 2 && parts[0] === "pre_execution") return `pre:${parts[1]}`;
  if (parts.length >= 2 && parts[0] === "internal_graph") return `step:${parts[1]}`;
  return raw;
}

function edgeDisplayLabel(edge = {}) {
  const raw = String(edge.condition || "").trim();
  if (!raw || raw === "default" || raw === "continue" || raw === "always") return "default";
  if (raw.startsWith("next_stage:")) return `next:${raw.split(":", 2)[1] || edge.targetStage || "stage"}`;
  if (raw.startsWith("guardian_decision:")) return `guard:${raw.split(":", 2)[1] || "decision"}`;
  if (raw.startsWith("decision:")) return `decision:${raw.split(":", 2)[1] || "value"}`;
  return raw;
}

function edgeTitle(edge = {}) {
  const condition = String(edge.condition || "default").trim() || "default";
  const kind = edge.isDefault ? "default" : "candidate";
  return `${kind} ${edge.sourceStage || edge.source?.id || "source"} -> ${edge.targetStage || edge.target?.id || "target"} · ${condition}`;
}

function logicalGraphEdges(graph) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const transitions = graph.transitions || {};
  const nodeByKey = nodeMapByStageOrId(nodes);
  const edges = [];
  const seen = new Set();
  const pushEdge = (sourceStage, targetStage, source, target, metadata = {}, label = "", condition = "", sourceNodeId = "", targetNodeId = "") => {
    if (!source || !target) return;
    const cleanCondition = String(condition || metadata.condition || metadata.transition_condition || "").trim();
    const conditionDefaultLike = ["", "default", "continue", "always"].includes(cleanCondition || "");
    const metadataDefault = metadata.default_transition === true;
    const isDefault = Boolean(transitions[sourceStage]) && transitions[sourceStage] === targetStage && (metadataDefault || conditionDefaultLike);
    const displayCondition = cleanCondition || (isDefault ? "default" : "candidate");
    const key = `${sourceNodeId || source.id}:${targetNodeId || target.id}:${sourceStage}->${targetStage}:${displayCondition}`;
    if (seen.has(key)) return;
    seen.add(key);
    const inferred = inferPortPair(source, target);
    const autoPorts = metadata.auto_ports !== false && metadata.lock_ports !== true;
    edges.push({
      sourceStage,
      targetStage,
      source,
      target,
      label,
      condition: displayCondition,
      isDefault,
      sourceSide: autoPorts ? inferred.sourceSide : (metadata.source_port || metadata.source_side || inferred.sourceSide),
      targetSide: autoPorts ? inferred.targetSide : (metadata.target_port || metadata.target_side || inferred.targetSide),
      metadata,
      sourceNodeId: source.id,
      targetNodeId: target.id,
    });
  };

  for (const edge of Array.isArray(graph.edges) ? graph.edges : []) {
    if (edge?.metadata?.runtime_edge !== "logical_transition" && graph.metadata?.ide_tab_kind !== "module") continue;
    const source = nodeByKey.get(edge.source);
    const target = nodeByKey.get(edge.target);
    const sourceStage = edge.metadata?.from_stage || nodeStage(source);
    const targetStage = edge.metadata?.to_stage || nodeStage(target);
    pushEdge(sourceStage, targetStage, source, target, edge.metadata || {}, edge.label || "", edge.condition || edge.metadata?.condition || edge.metadata?.transition_condition || "", edge.source, edge.target);
  }

  for (const [sourceStage, targetStage] of Object.entries(transitions)) {
    const source = nodeByKey.get(sourceStage);
    const target = nodeByKey.get(targetStage);
    const defaultTargetAlreadyRepresented = edges.some((edge) => edge.sourceStage === sourceStage && edge.targetStage === targetStage);
    if (defaultTargetAlreadyRepresented) continue;
    pushEdge(sourceStage, targetStage, source, target, { default_transition: true, auto_ports: true }, `default transition: ${sourceStage} -> ${targetStage}`, "default");
  }

  const groups = new Map();
  for (const edge of edges) {
    const groupKey = `${edge.source.id}->${edge.target.id}`;
    if (!groups.has(groupKey)) groups.set(groupKey, []);
    groups.get(groupKey).push(edge);
  }
  for (const group of groups.values()) {
    group.forEach((edge, index) => {
      edge.parallelIndex = index;
      edge.parallelTotal = group.length;
    });
  }
  return edges;
}


function offsetPointForParallel(point, edge, axis = "target") {
  const total = Number(edge.parallelTotal || 1);
  if (total <= 1) return point;
  const index = Number(edge.parallelIndex || 0);
  const offset = (index - (total - 1) / 2) * 18;
  const sourcePoint = portPoint(edge.source, edge.sourceSide);
  const targetPoint = portPoint(edge.target, edge.targetSide);
  const dx = targetPoint.x - sourcePoint.x;
  const dy = targetPoint.y - sourcePoint.y;
  const length = Math.max(1, Math.hypot(dx, dy));
  const nx = -dy / length;
  const ny = dx / length;
  return { x: point.x + nx * offset, y: point.y + ny * offset };
}

function edgeControlPoints(edge) {
  const rawSourcePoint = portPoint(edge.source, edge.sourceSide);
  const rawTargetPoint = portPoint(edge.target, edge.targetSide);
  const sourcePoint = offsetPointForParallel(rawSourcePoint, edge, "source");
  const targetPoint = offsetPointForParallel(rawTargetPoint, edge, "target");
  const horizontal = edge.sourceSide === "left" || edge.sourceSide === "right" || edge.targetSide === "left" || edge.targetSide === "right";
  const dx = Math.abs(targetPoint.x - sourcePoint.x);
  const dy = Math.abs(targetPoint.y - sourcePoint.y);
  const bend = Math.max(54, Math.min(220, (horizontal ? dx : dy) / 2));
  if (edge.sourceSide === "top" || edge.sourceSide === "bottom" || edge.targetSide === "top" || edge.targetSide === "bottom") {
    const syBend = sourcePoint.y + (edge.sourceSide === "top" ? -bend : edge.sourceSide === "bottom" ? bend : 0);
    const tyBend = targetPoint.y + (edge.targetSide === "top" ? -bend : edge.targetSide === "bottom" ? bend : 0);
    return { sourcePoint, targetPoint, c1: { x: sourcePoint.x, y: syBend }, c2: { x: targetPoint.x, y: tyBend } };
  }
  const sxBend = sourcePoint.x + (edge.sourceSide === "left" ? -bend : bend);
  const txBend = targetPoint.x + (edge.targetSide === "left" ? -bend : bend);
  return { sourcePoint, targetPoint, c1: { x: sxBend, y: sourcePoint.y }, c2: { x: txBend, y: targetPoint.y } };
}

function edgePath(edge) {
  const { sourcePoint, targetPoint, c1, c2 } = edgeControlPoints(edge);
  return `M ${sourcePoint.x} ${sourcePoint.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${targetPoint.x} ${targetPoint.y}`;
}

function edgeLabelPoint(edge) {
  const { sourcePoint, targetPoint, c1, c2 } = edgeControlPoints(edge);
  const t = 0.5;
  const mt = 1 - t;
  return {
    x: mt ** 3 * sourcePoint.x + 3 * mt ** 2 * t * c1.x + 3 * mt * t ** 2 * c2.x + t ** 3 * targetPoint.x,
    y: mt ** 3 * sourcePoint.y + 3 * mt ** 2 * t * c1.y + 3 * mt * t ** 2 * c2.y + t ** 3 * targetPoint.y,
  };
}


function setGraphJson(graph) {
  graphJson.value = JSON.stringify(graph, null, 2);
}

function setModuleJson(payload) {
  moduleJson.value = JSON.stringify(payload, null, 2);
  const normalized = payload?.module ? payload : { module: payload || {} };
  const moduleId = normalized.module?.id || activeModuleId;
  if (moduleId) modulePayloadCache.set(moduleId, normalized);
}

function parseRunCreatedAt(runId) {
  const match = String(runId || "").match(/run-(\d{8})T(\d{6})Z/);
  if (!match) return null;
  const [, date, time] = match;
  return Date.UTC(
    Number(date.slice(0, 4)),
    Number(date.slice(4, 6)) - 1,
    Number(date.slice(6, 8)),
    Number(time.slice(0, 2)),
    Number(time.slice(2, 4)),
    Number(time.slice(4, 6)),
  );
}

function formatElapsed(runId) {
  const created = parseRunCreatedAt(runId);
  if (!created) return "n/a";
  const totalSec = Math.max(0, Math.floor((Date.now() - created) / 1000));
  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}` : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function stageAgentLabel(stage) {
  const node = findNodeByStage(stage);
  if (!node?.handler) return "none";
  return node.handler.startsWith("agent.") ? node.handler.replace("agent.", "") : node.handler;
}

function statusFromSnapshot(snapshot) {
  const state = snapshot?.state || {};
  if (state.stop_requested || state.safe_stop_requested) return "STOPPING";
  if (state.stage === "error") return "FAILED";
  if (state.stage === "complete") return "COMPLETE";
  if (state.is_paused) return "PAUSED";
  return snapshot?.is_running ? "RUNNING" : "IDLE";
}

function renderRuntimeHeader(snapshot = latestStateSnapshot) {
  if (!snapshot) return;
  latestStateSnapshot = snapshot;
  const state = snapshot.state || {};
  const stage = activeRuntimeStage || state.stage || "idle";
  const runId = state.run_id || currentRunId || "n/a";
  const status = statusFromSnapshot(snapshot);
  if (runStatusLabel) {
    runStatusLabel.textContent = status;
    runStatusLabel.className = `runtime-status-pill ${status.toLowerCase()}`;
  }
  if (runIdLabel) runIdLabel.textContent = `run: ${runId}`;
  if (elapsedLabel) elapsedLabel.textContent = formatElapsed(runId);
  if (objectiveSummary) objectiveSummary.textContent = `objective: ${state.active_goal || "not set"}`;
  if (activeAgentLabel) activeAgentLabel.textContent = stageAgentLabel(stage);
  if (currentStageLabel) currentStageLabel.textContent = stage;
  if (runtimeHealthLabel) {
    const health = state.device_health || {};
    const resources = systemResources(snapshot);
    const bad = Object.entries(health).filter(([, value]) => String(value) !== "ready");
    const warningCount = bad.length + resourceWarningCount(resources);
    const ramLabel = formatResourcePercent(resources.ram?.used_percent);
    const vramLabel = formatResourcePercent(gpuAggregate(resources).memory_used_percent);
    runtimeHealthLabel.textContent = `${warningCount ? `${warningCount} warning` : "ready"} · RAM ${ramLabel} · VRAM ${vramLabel}`;
  }
}


function graphViewportCoverage(bounds, zoom = graphZoom) {
  const width = Math.max(1, Number(bounds?.width || 1) * zoom);
  const height = Math.max(1, Number(bounds?.height || 1) * zoom);
  const visibleWidth = Math.min(1, (graphCanvas?.clientWidth || width) / width);
  const visibleHeight = Math.min(1, (graphCanvas?.clientHeight || height) / height);
  return { width: visibleWidth, height: visibleHeight, area: visibleWidth * visibleHeight };
}

function readableFitMinZoom() {
  const width = Number(window.innerWidth || graphCanvas?.clientWidth || 0);
  if (width >= 1500) return 0.72;
  if (width >= 1100) return 0.64;
  return 0.54;
}

function updateCanvasViewHint(bounds) {
  const hint = document.getElementById("ide-canvas-view-hint");
  if (!hint || !bounds) return;
  const coverage = graphViewportCoverage(bounds);
  const percent = Math.round(coverage.area * 100);
  const zoomPercent = Math.round(graphZoom * 100);
  const needsFit = coverage.width < 0.82 || coverage.height < 0.82;
  const readableFit = graphFitZoom(bounds);
  const canImproveWithFit = Math.abs(graphZoom - readableFit) > 0.04;
  const tab = activeGraphTab();
  const context = tab?.kind === "module"
    ? `module: ${tab.moduleId || activeGraph?.metadata?.module_id || "internal"}`
    : "main system";
  const action = needsFit ? (canImproveWithFit ? "use Fit" : "scroll/map") : "ready";
  hint.textContent = `${context} · view: ${percent}% · zoom: ${zoomPercent}%${needsFit ? ` · ${action}` : ""}`;
  hint.className = `runtime-canvas-view-hint${needsFit ? " warn" : " ok"}`;
}

function graphFitZoom(bounds) {
  if (!bounds || !graphCanvas) return 1;
  const availableWidth = Math.max(320, graphCanvas.clientWidth - 32);
  const availableHeight = Math.max(220, graphCanvas.clientHeight - 32);
  const scaleX = availableWidth / Math.max(1, Number(bounds.width || availableWidth));
  const scaleY = availableHeight / Math.max(1, Number(bounds.height || availableHeight));
  const fitScale = Math.min(scaleX, scaleY);
  return Math.max(readableFitMinZoom(), Math.min(1.15, fitScale));
}

function fitGraphToCanvas(options = {}) {
  const graph = normalizeNodePositions(parseGraphEditor());
  const bounds = graphBounds(Array.isArray(graph.nodes) ? graph.nodes : []);
  graphZoom = graphFitZoom(bounds);
  renderGraph(graph);
  requestAnimationFrame(() => {
    graphCanvas.scrollLeft = 0;
    graphCanvas.scrollTop = 0;
    updateCanvasViewHint(bounds);
  });
  if (!options.silent) log(`Fit graph viewport to readable ${Math.round(graphZoom * 100)}%. Scroll or use the minimap for off-screen nodes.`, "ok");
}

function renderGraphExplorer(graph = activeGraph) {
  if (!nodeListOutput || !graph) return;
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const query = nodeSearchQuery.trim().toLowerCase();
  const filtered = nodes.filter((node) => {
    const haystack = `${node.id} ${node.label || ""} ${node.stage || ""} ${node.handler || ""}`.toLowerCase();
    return !query || haystack.includes(query);
  });
  nodeListOutput.innerHTML = filtered.length
    ? filtered.map((node) => {
        const stage = node.stage || node.id;
        const stateClass = stage === activeRuntimeStage ? " active" : visitedRuntimeStages.has(stage) ? " visited" : "";
        return `
          <button type="button" class="runtime-explorer-node${stateClass}" data-explorer-node="${escapeHtml(node.id)}">
            <strong>${escapeHtml(node.label || node.id)}</strong>
            <small>${escapeHtml(stage)} · ${escapeHtml(node.handler || "no-handler")}</small>
          </button>
        `;
      }).join("")
    : "<div>No nodes match the filter.</div>";
  nodeListOutput.querySelectorAll("[data-explorer-node]").forEach((el) => {
    el.addEventListener("click", () => selectNode(el.getAttribute("data-explorer-node") || ""));
  });
  renderModuleCatalog();
}

function renderModuleCatalog() {
  if (!templateListOutput) return;
  if (!availableModules.length) {
    templateListOutput.innerHTML = "<div>No module library entries found.</div>";
    return;
  }
  const groups = new Map();
  for (const module of availableModules) {
    const category = String(module.category || "runtime");
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(module);
  }
  templateListOutput.innerHTML = Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([category, modules]) => `
      <section class="runtime-module-catalog-group">
        <div class="runtime-module-catalog-heading">
          <strong>${escapeHtml(category)}</strong>
          <small>${escapeHtml(modules.length)} module(s)</small>
        </div>
        ${modules
          .sort((a, b) => String(a.label || a.id).localeCompare(String(b.label || b.id)))
          .map((module) => `
            <button type="button" draggable="true" class="runtime-module-catalog-item" data-module-catalog-id="${escapeHtml(module.id)}">
              ${runtimeNodeIconMarkup(moduleIconName(module))}
              <span>
                <strong>${escapeHtml(module.label || module.id)}</strong>
                <small>${escapeHtml(module.handler || "runtime.step_complete")} · tools ${escapeHtml(module.tool_count || 0)}${module.pending_handler_registration ? " · registration pending" : ""}</small>
              </span>
            </button>
          `)
          .join("")}
      </section>
    `)
    .join("");
  templateListOutput.querySelectorAll("[data-module-catalog-id]").forEach((el) => {
    el.addEventListener("dragstart", (event) => {
      const moduleId = el.getAttribute("data-module-catalog-id") || "";
      event.dataTransfer.setData("application/x-atr-module", moduleId);
      event.dataTransfer.setData("text/plain", moduleId);
      event.dataTransfer.effectAllowed = "copy";
      log(`Dragging module ${moduleId}; drop it on the canvas to add it to the active draft.`, "ok");
    });
  });
}

function uniqueName(base, existing) {
  const clean = slugify(base, "module");
  if (!existing.has(clean)) return clean;
  let index = 2;
  while (existing.has(`${clean}_${index}`)) index += 1;
  return `${clean}_${index}`;
}

function addCatalogModuleAsGraphNode(module, event) {
  const graph = parseGraphEditor();
  normalizeNodePositions(graph);
  graph.nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  graph.stage_dispatch = graph.stage_dispatch || {};
  const existingIds = new Set(graph.nodes.map((node) => node.id));
  const existingStages = new Set(graph.nodes.map((node) => node.stage || node.id));
  const base = slugify(module.id || module.label, "module");
  const nodeId = uniqueName(base, existingIds);
  const stage = uniqueName(base, existingStages);
  const point = clientToWorldPoint(event);
  const node = {
    id: nodeId,
    label: module.label || titleFromSlug(base),
    handler: module.handler || "runtime.step_complete",
    stage,
    kind: "module",
    description: `Catalog module: ${module.category || "runtime"}`,
    module_id: `modules/${module.id}`,
    position: { x: snapToGrid(point.x), y: snapToGrid(point.y) },
    metadata: {
      icon: moduleIconName(module),
      category: module.category || "runtime",
      added_from_catalog: true,
    },
  };
  graph.nodes.push(node);
  graph.stage_dispatch[stage] = nodeId;
  selectedNodeId = nodeId;
  setGraphJson(graph);
  markActiveTabDirty(graph);
  renderGraph(graph);
  log(`Added module ${module.id} as graph node ${nodeId}. Connect ports, validate, then save.`, "ok");
}

function addCatalogModuleAsInternalStep(module, event) {
  const graph = parseGraphEditor();
  const moduleId = graph.metadata?.module_id || activeModuleId;
  const payload = normalizedModulePayload(modulePayloadCache.get(moduleId) || parseModuleEditor());
  const targetModule = payload.module || {};
  targetModule.internal_graph = Array.isArray(targetModule.internal_graph) ? targetModule.internal_graph : [];
  const existing = new Set(targetModule.internal_graph.map((step) => step.id));
  const base = slugify(module.id || module.label, "module_step");
  const stepId = uniqueName(base, existing);
  const point = clientToWorldPoint(event);
  targetModule.internal_graph.push({
    id: stepId,
    label: module.label || titleFromSlug(base),
    kind: `${module.category || "runtime"}_module`,
    handler: module.handler || "runtime.step_complete",
    metadata: {
      linked_module_id: module.id,
      category: module.category || "runtime",
      position: { x: snapToGrid(point.x), y: snapToGrid(point.y) },
    },
  });
  modulePayloadCache.set(moduleId, payload);
  markModulePreflightDirty(moduleId, "module internal step added");
  setModuleJson(payload);
  updateModuleSummary(targetModule);
  renderModuleGraph(payload);
  const nextGraph = modulePayloadToGraph(payload);
  const tab = activeGraphTab();
  if (tab) {
    tab.graph = nextGraph;
    tab.dirty = true;
  }
  renderGraph(nextGraph);
  log(`Added catalog module ${module.id} as internal step ${stepId}. Validate and save the module.`, "ok");
}

function addCatalogModuleToCanvas(moduleId, event) {
  const module = availableModules.find((item) => item.id === moduleId);
  if (!module) {
    log(`Module catalog item not found: ${moduleId}`, "error");
    return;
  }
  const graph = parseGraphEditor();
  if (graph.metadata?.ide_tab_kind === "module") addCatalogModuleAsInternalStep(module, event);
  else addCatalogModuleAsGraphNode(module, event);
}

function handleCanvasCatalogDrop(event) {
  const moduleId = event.dataTransfer?.getData("application/x-atr-module") || "";
  if (!moduleId) return;
  event.preventDefault();
  addCatalogModuleToCanvas(moduleId, event);
}

function removeGraphNodeFromDraft(nodeId) {
  const graph = parseGraphEditor();
  normalizeNodePositions(graph);
  const node = (Array.isArray(graph.nodes) ? graph.nodes : []).find((item) => item.id === nodeId);
  if (!node) return false;
  const stage = nodeStage(node);
  graph.nodes = graph.nodes.filter((item) => item.id !== nodeId);
  graph.stage_dispatch = Object.fromEntries(
    Object.entries(graph.stage_dispatch || {}).filter(([key, value]) => key !== stage && key !== nodeId && value !== nodeId),
  );
  graph.transitions = Object.fromEntries(
    Object.entries(graph.transitions || {}).filter(([source, target]) => source !== stage && source !== nodeId && target !== stage && target !== nodeId),
  );
  graph.edges = Array.isArray(graph.edges)
    ? graph.edges.filter((edge) => {
        const from = edge.metadata?.from_stage;
        const to = edge.metadata?.to_stage;
        return edge.source !== nodeId && edge.target !== nodeId && from !== stage && to !== stage && from !== nodeId && to !== nodeId;
      })
    : [];
  if (graph.entry_node === nodeId) graph.entry_node = graph.nodes[0]?.id || "";
  selectedNodeId = graph.nodes[0]?.id || "";
  setGraphJson(graph);
  markActiveTabDirty(graph);
  renderGraph(graph);
  log(`Removed node ${nodeId} from graph draft. Validate before saving.`, "ok");
  return true;
}

function removeModuleStepNodeFromDraft(nodeId) {
  const graph = parseGraphEditor();
  const node = (Array.isArray(graph.nodes) ? graph.nodes : []).find((item) => item.id === nodeId);
  if (!node) return false;
  const phase = node.metadata?.module_step_phase || "internal_graph";
  const index = Number(node.metadata?.module_step_index);
  const moduleId = graph.metadata?.module_id || activeModuleId;
  const payload = normalizedModulePayload(modulePayloadCache.get(moduleId) || parseModuleEditor());
  const module = payload.module || {};
  const steps = moduleStepsForPhase(module, phase);
  if (index < 0 || index >= steps.length) return false;
  const [removed] = steps.splice(index, 1);
  modulePayloadCache.set(moduleId, payload);
  markModulePreflightDirty(moduleId, "module step removed");
  setModuleJson(payload);
  updateModuleSummary(module);
  renderModuleGraph(payload);
  const nextGraph = modulePayloadToGraph(payload);
  const tab = activeGraphTab();
  if (tab) {
    tab.graph = nextGraph;
    tab.dirty = true;
  }
  selectedNodeId = nextGraph.nodes[0]?.id || "";
  renderGraph(nextGraph);
  log(`Removed ${phase} step ${removed?.id || nodeId} from module draft. Validate before saving.`, "ok");
  return true;
}

function removeNodeById(nodeId) {
  const graph = parseGraphEditor();
  if (graph.metadata?.ide_tab_kind === "module") return removeModuleStepNodeFromDraft(nodeId);
  return removeGraphNodeFromDraft(nodeId);
}

function safeNumber(value, fallback = null) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function formatMetricValue(value, unit = "") {
  const number = safeNumber(value);
  if (number === null) return "n/a";
  const abs = Math.abs(number);
  const digits = abs >= 100 ? 1 : abs >= 10 ? 2 : 3;
  return `${number.toFixed(digits).replace(/\.?0+$/, "")}${unit ? ` ${unit}` : ""}`;
}

function compactJson(value) {
  if (value === undefined || value === null || value === "") return "n/a";
  if (typeof value === "object") return JSON.stringify(value).slice(0, 160);
  return String(value);
}

function formatVersionTimestamp(value) {
  if (!value) return "no timestamp";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function versionLabel(version) {
  return `${version.version_id || "version"}${version.author ? ` · ${version.author}` : ""}`;
}

function activationEvidenceSummary(evidence) {
  if (!evidence) return "not run";
  if (evidence.ok === false) return evidence.errors?.join("; ") || "failed";
  return evidence.detail || evidence.timestamp || "ok";
}

function compiledGraphEvidenceText(compiledGraph) {
  if (!compiledGraph || typeof compiledGraph !== "object") return "no compiled graph summary";
  const transitions = compiledGraph.transitions || {};
  const transitionCount = Object.keys(transitions).length;
  const logicalCount = compiledGraph.logical_edge_count ?? (Array.isArray(compiledGraph.logical_edges) ? compiledGraph.logical_edges.length : 0);
  const candidateCount = compiledGraph.transition_candidates && typeof compiledGraph.transition_candidates === "object"
    ? Object.values(compiledGraph.transition_candidates).reduce((acc, items) => acc + (Array.isArray(items) ? items.length : 0), 0)
    : 0;
  return `entry=${compiledGraph.entry_node || "n/a"} · nodes=${compiledGraph.node_count ?? "n/a"} · runtime_edges=${compiledGraph.edge_count ?? "n/a"} · logical_edges=${logicalCount} · transitions=${transitionCount} · candidates=${candidateCount}`;
}

function activationShortDigest(value) {
  if (!value) return "none";
  return String(value).slice(0, 12);
}

function activationKeyValueMarkup(items) {
  return `
    <div class="runtime-activation-kv-grid">
      ${items.map((item) => `
        <span>
          <small>${escapeHtml(item.label)}</small>
          <strong>${escapeHtml(item.value ?? "n/a")}</strong>
        </span>
      `).join("")}
    </div>
  `;
}

function activationRouteListMarkup(title, routes, emptyText = "none") {
  const normalized = Array.isArray(routes) ? routes.filter(Boolean) : [];
  const visible = normalized.slice(0, 10);
  const overflow = Math.max(0, normalized.length - visible.length);
  return `
    <div class="runtime-activation-route-list">
      <strong>${escapeHtml(title)}</strong>
      ${visible.length ? visible.map((route) => `<span>${escapeHtml(route)}</span>`).join("") : `<span class="muted">${escapeHtml(emptyText)}</span>`}
      ${overflow ? `<small>+${escapeHtml(overflow)} more</small>` : ""}
    </div>
  `;
}

function activationCompiledGraphDetailMarkup(compiledGraph) {
  if (!compiledGraph || typeof compiledGraph !== "object") {
    return `<div class="runtime-activation-detail-note warn">No compiled graph summary returned by backend.</div>`;
  }
  const transitions = compiledGraph.transitions || {};
  const candidates = compiledGraph.transition_candidates || {};
  const logicalEdges = Array.isArray(compiledGraph.logical_edges) ? compiledGraph.logical_edges : [];
  const executableEdges = Array.isArray(compiledGraph.executable_edges) ? compiledGraph.executable_edges : [];
  const candidateRoutes = Object.entries(candidates).flatMap(([stage, items]) => (
    Array.isArray(items)
      ? items.map((item) => `${stage} -- ${item.condition || "candidate"} -> ${item.next_stage || item.target || "?"}`)
      : []
  ));
  const defaultRoutes = Object.entries(transitions).map(([stage, target]) => `${stage} -> ${target}`);
  const dispatchRoutes = Object.entries(compiledGraph.stage_dispatch || {}).map(([stage, node]) => `${stage} => ${node}`);
  return `
    ${activationKeyValueMarkup([
      { label: "graph", value: compiledGraph.graph_id || "n/a" },
      { label: "entry", value: compiledGraph.entry_node || "n/a" },
      { label: "nodes", value: compiledGraph.node_count ?? "n/a" },
      { label: "runtime edges", value: compiledGraph.edge_count ?? executableEdges.length },
      { label: "logical edges", value: compiledGraph.logical_edge_count ?? logicalEdges.length },
      { label: "finish", value: Array.isArray(compiledGraph.finish_nodes) ? compiledGraph.finish_nodes.join(", ") : "n/a" },
    ])}
    ${activationRouteListMarkup("Default Runtime Routes", defaultRoutes, "no default transitions")}
    ${activationRouteListMarkup("Conditional Candidate Routes", candidateRoutes, "no conditional candidate routes")}
    ${activationRouteListMarkup("Stage Dispatch", dispatchRoutes, "no stage dispatch mapping")}
  `;
}

function dryRunEvidenceText(evidence) {
  const sequence = Array.isArray(evidence?.sequence) ? evidence.sequence : [];
  const record = evidence?.dry_run_record || {};
  const route = sequence.slice(0, 10).map((item) => item.stage).filter(Boolean).join(" -> ") || "no sequence";
  const gate = record.live_gate_recorded === false ? "draft only" : record.digest ? "active gate recorded" : "not recorded";
  return `${sequence.length} step(s) · ${gate} · ${route}`;
}

function activationDryRunDetailMarkup(evidence) {
  const sequence = Array.isArray(evidence?.sequence) ? evidence.sequence : [];
  const record = evidence?.dry_run_record || {};
  const mode = evidence?.draft === true || record.draft === true || record.live_gate_recorded === false ? "draft payload" : "active config";
  const gate = record.live_gate_recorded === false ? "draft only, not a live gate" : record.digest ? "active live gate recorded" : "not recorded";
  const rows = sequence.slice(0, 14).map((item) => `
    <tr>
      <td>${escapeHtml(item.step ?? "-")}</td>
      <td>${escapeHtml(item.stage || "-")}</td>
      <td>${escapeHtml(item.next_stage || "-")}</td>
      <td>${escapeHtml(item.node_id || "-")}</td>
      <td>${escapeHtml(item.effective_handler || item.graph_handler || "-")}</td>
    </tr>
  `).join("");
  return `
    ${activationKeyValueMarkup([
      { label: "payload", value: mode },
      { label: "gate", value: gate },
      { label: "steps", value: record.step_count ?? sequence.length },
      { label: "start", value: record.start_stage || sequence[0]?.stage || "n/a" },
      { label: "digest", value: activationShortDigest(record.digest) },
      { label: "time", value: record.dry_run_at || evidence?.timestamp || "n/a" },
    ])}
    <div class="runtime-activation-table-wrap">
      <table class="runtime-activation-table">
        <thead><tr><th>#</th><th>stage</th><th>next</th><th>node</th><th>handler</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="5">No dry-run sequence returned.</td></tr>`}</tbody>
      </table>
    </div>
    ${sequence.length > 14 ? `<small class="runtime-activation-overflow">${escapeHtml(sequence.length - 14)} additional step(s) hidden in checklist; use Dry Run output for the full trace.</small>` : ""}
  `;
}

function activationValidationDetailMarkup(validation) {
  if (!validation) return "";
  if (validation.ok) {
    return `
      <div class="runtime-activation-detail-note ok">Draft schema, handler allowlist, module references, and compile check passed.</div>
      ${activationCompiledGraphDetailMarkup(validation.compiled_graph)}
    `;
  }
  const errors = Array.isArray(validation.errors) ? validation.errors : [];
  return `
    <div class="runtime-activation-detail-note error">Validation failed. Fix these before compile/run.</div>
    ${activationRouteListMarkup("Validation Errors", errors, "no explicit error returned")}
  `;
}

function activationSaveDetailMarkup(save) {
  const version = save?.version || {};
  return `
    ${activationKeyValueMarkup([
      { label: "version", value: save?.version_id || version.version_id || save?.detail || "n/a" },
      { label: "activated", value: save?.activated === false ? "no" : "yes" },
      { label: "author", value: version.author || "runtime_ide" },
      { label: "saved", value: version.created_at || save?.timestamp || "n/a" },
    ])}
    ${activationCompiledGraphDetailMarkup(save?.compiled_graph)}
  `;
}

function activationEvidenceDetailsMarkup() {
  const rows = [];
  const validation = activationEvidence.validation;
  if (validation) {
    rows.push({
      title: "Validation Evidence",
      status: validation.ok ? "ok" : "error",
      summary: validation.ok ? "Draft config passed schema, handler, module, and compile checks." : (validation.errors || []).join("; ") || "validation failed",
      body: activationValidationDetailMarkup(validation),
    });
  }
  const compile = activationEvidence.compile;
  if (compile) {
    rows.push({
      title: "Compile Evidence",
      status: compile.ok ? "ok" : "error",
      summary: compiledGraphEvidenceText(compile.compiled_graph),
      body: activationCompiledGraphDetailMarkup(compile.compiled_graph),
    });
  }
  const dryRun = activationEvidence.dry_run;
  if (dryRun) {
    rows.push({
      title: "Dry-run Evidence",
      status: dryRun.ok ? "ok" : "error",
      summary: dryRunEvidenceText(dryRun),
      body: activationDryRunDetailMarkup(dryRun),
    });
  }
  const save = activationEvidence.save;
  if (save) {
    rows.push({
      title: "Version Activation Evidence",
      status: save.ok ? "ok" : "error",
      summary: `${save.version_id || save.detail || "versioned"}${save.activated === false ? " · draft only" : " · active config updated"}`,
      body: activationSaveDetailMarkup(save),
    });
  }
  if (!rows.length) return `<div class="runtime-activation-evidence empty">No validation, compile, dry-run, or save evidence yet.</div>`;
  return `
    <div class="runtime-activation-evidence">
      ${rows.map((row) => `
        <details class="runtime-activation-evidence-row ${escapeHtml(row.status)}" open>
          <summary>
            <strong>${escapeHtml(row.title)}</strong>
            <span>${escapeHtml(row.summary)}</span>
          </summary>
          <div class="runtime-activation-evidence-body">${row.body}</div>
        </details>
      `).join("")}
    </div>
  `;
}

function setActivationEvidence(key, payload = {}) {
  activationEvidence[key] = { ...payload, timestamp: new Date().toLocaleTimeString() };
  if (["validation", "compile", "dry_run", "save"].includes(key)) {
    activationEvidence.dirty = false;
    activationEvidence.reason = "checked";
  }
  renderActivationChecklist();
  renderRuntimeReadinessPanel();
}

function markActivationDirty(reason = "draft changed") {
  activationEvidence = { validation: null, compile: null, dry_run: null, save: null, dirty: true, reason };
  renderActivationChecklist();
  renderRuntimeReadinessPanel();
}

function modulePayloadFingerprint(payload) {
  return JSON.stringify(stableConfigValue(normalizedModulePayload(payload)));
}

function moduleEvidenceRecord(moduleId) {
  const key = String(moduleId || activeModuleId || "module");
  if (!modulePreflightEvidence.has(key)) {
    modulePreflightEvidence.set(key, { validation: null, dry_run: null, save: null, dirty: false, reason: "not checked" });
  }
  return modulePreflightEvidence.get(key);
}

function setModulePreflightEvidence(moduleId, key, payload = {}) {
  const record = moduleEvidenceRecord(moduleId);
  record[key] = { ...payload, timestamp: new Date().toLocaleTimeString() };
  if (["validation", "dry_run", "save"].includes(key)) {
    record.dirty = false;
    record.reason = "checked";
  }
  renderActivationChecklist();
  renderRuntimeReadinessPanel();
}

function markModulePreflightDirty(moduleId = activeModuleId, reason = "module draft changed") {
  const record = moduleEvidenceRecord(moduleId);
  record.validation = null;
  record.dry_run = null;
  record.save = null;
  record.dirty = true;
  record.reason = reason;
  renderActivationChecklist();
  renderRuntimeReadinessPanel();
}

function moduleSavePreflightStatus(moduleId, payload) {
  const record = moduleEvidenceRecord(moduleId);
  const fingerprint = modulePayloadFingerprint(payload);
  const validationOk = Boolean(record.validation?.ok && record.validation?.fingerprint === fingerprint);
  const dryRunOk = Boolean(record.dry_run?.ok && record.dry_run?.fingerprint === fingerprint);
  return { ok: validationOk && dryRunOk, validationOk, dryRunOk, dirty: Boolean(record.dirty), reason: record.reason || "not checked", fingerprint, record };
}

function moduleSavePreflightBlockedMarkup(moduleId, status) {
  const rows = [
    { label: "Validate module draft", ok: status.validationOk },
    { label: "Dry-run module draft", ok: status.dryRunOk },
  ];
  return `
    <div class="runtime-module-evidence-card error">
      <div class="runtime-module-evidence-head">
        <strong>Module save blocked</strong>
        <small>${escapeHtml(moduleId || "module")} · validate and dry-run this exact draft before saving</small>
      </div>
      <div class="runtime-module-save-gate-list">
        ${rows.map((row) => `<span class="${row.ok ? "ok" : "warn"}">${escapeHtml(row.ok ? "ok" : "missing")} · ${escapeHtml(row.label)}</span>`).join("")}
      </div>
      <p>Current draft evidence is ${escapeHtml(status.reason || "not checked")}. Run Validate and Dry Run from this module tab, then save the module version.</p>
    </div>
  `;
}

function moduleActivationEvidenceDetailsMarkup(moduleId, preflight) {
  const record = preflight.record || {};
  const rows = [];
  if (record.validation) {
    rows.push({
      title: "Module Validation Evidence",
      status: preflight.validationOk ? "ok" : record.validation.ok === false ? "error" : "warn",
      summary: preflight.validationOk ? "Current module draft passed schema and allowlist checks." : "Validation evidence does not match the current draft.",
      body: moduleValidationResultMarkup({ ok: Boolean(record.validation.ok), errors: record.validation.errors || [] }, moduleId),
    });
  }
  if (record.dry_run) {
    rows.push({
      title: "Module Dry-run Evidence",
      status: preflight.dryRunOk ? "ok" : record.dry_run.ok === false ? "error" : "warn",
      summary: preflight.dryRunOk ? record.dry_run.detail || "current draft dry-run passed" : "Dry-run evidence does not match the current draft.",
      body: moduleDryRunResultMarkup({ ok: Boolean(record.dry_run.ok), sequence: record.dry_run.sequence || [], summary: record.dry_run.summary || {} }, moduleId),
    });
  }
  if (record.save) {
    rows.push({
      title: "Module Save Evidence",
      status: record.save.ok && record.save.fingerprint === preflight.fingerprint ? "ok" : "warn",
      summary: record.save.detail || record.save.version_id || "module version saved",
      body: activationKeyValueMarkup([
        { label: "module", value: moduleId },
        { label: "version", value: record.save.version_id || record.save.detail || "n/a" },
        { label: "fingerprint", value: activationShortDigest(record.save.fingerprint || "") },
        { label: "time", value: record.save.timestamp || "n/a" },
      ]),
    });
  }
  if (!rows.length) return `<div class="runtime-activation-evidence empty">No module validation, dry-run, or save evidence yet.</div>`;
  return `
    <div class="runtime-activation-evidence runtime-module-activation-evidence">
      ${rows.map((row) => `
        <details class="runtime-activation-evidence-row ${escapeHtml(row.status)}" open>
          <summary>
            <strong>${escapeHtml(row.title)}</strong>
            <span>${escapeHtml(row.summary)}</span>
          </summary>
          <div class="runtime-activation-evidence-body">${row.body}</div>
        </details>
      `).join("")}
    </div>
  `;
}

function renderModuleActivationChecklist(graph) {
  const payload = modulePayloadForGraphDraft(graph);
  const module = payload.module || {};
  const moduleId = module.id || graph?.metadata?.module_id || activeModuleId || "module";
  const preflight = moduleSavePreflightStatus(moduleId, payload);
  const record = preflight.record || {};
  const saveOk = Boolean(record.save?.ok && record.save?.fingerprint === preflight.fingerprint);
  const checks = [
    { label: "Validate Module Draft", detail: "schema + handler/tool allowlist", status: preflight.validationOk ? "ok" : record.validation?.ok === false ? "error" : preflight.dirty ? "warn" : "idle", summary: preflight.validationOk ? "current draft validated" : activationEvidenceSummary(record.validation) },
    { label: "Dry-run Module Draft", detail: "pre/internal step sequence, no hardware", status: preflight.dryRunOk ? "ok" : record.dry_run?.ok === false ? "error" : preflight.dirty ? "warn" : "idle", summary: preflight.dryRunOk ? record.dry_run?.detail || "current draft dry-run passed" : activationEvidenceSummary(record.dry_run) },
    { label: "Save Module Version", detail: "blocked until validate + dry-run match", status: saveOk ? "ok" : preflight.ok ? "warn" : "idle", summary: saveOk ? record.save?.detail || "saved" : preflight.ok ? "ready to save" : "blocked" },
  ];
  const allReady = preflight.ok;
  if (activationOverallBadge) {
    activationOverallBadge.textContent = saveOk ? "saved" : allReady ? "ready to save" : preflight.dirty ? "draft changed" : "pending";
    activationOverallBadge.className = `badge ${saveOk || allReady ? "ok" : preflight.dirty ? "warn" : "idle"}`;
  }
  activationChecklistOutput.innerHTML = `
    <div class="runtime-activation-context">
      <span><strong>${escapeHtml(moduleId)}</strong><small>${escapeHtml(module.label || "Module draft")}</small></span>
      <span><strong>${escapeHtml(checks.filter((item) => item.status === "ok").length)}/${escapeHtml(checks.length)}</strong><small>module gates</small></span>
      <span><strong>${escapeHtml(preflight.reason || "pending")}</strong><small>check state</small></span>
    </div>
    <div class="runtime-activation-detail-note ${preflight.ok ? "ok" : "warn"}">${escapeHtml(preflight.ok ? "This module draft has matching validation and dry-run evidence." : "Validate and dry-run this exact module draft before saving a module version.")}</div>
    <div class="runtime-activation-steps runtime-module-activation-steps">
      ${checks.map((item) => `
        <div class="runtime-activation-step ${escapeHtml(item.status)}">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.detail)}</span>
          <small>${escapeHtml(item.summary || "pending")}</small>
        </div>
      `).join("")}
    </div>
    ${moduleActivationEvidenceDetailsMarkup(moduleId, preflight)}
  `;
  renderLivePreflight();
}


function livePreflightStatus(graph = null, mode = runModeSelect?.value || "test") {
  const draft = graph || activeGraph || (() => { try { return parseGraphEditor(); } catch { return {}; } })();
  const graphId = draft?.id || graphIdForRunLauncher();
  const normalizedMode = mode || "test";
  const liveMode = normalizedMode === "live";
  const tab = activeGraphTab();
  const diff = activeDraftRouteDiff(draft);
  const configDiff = activeDraftConfigDiff(draft);
  const draftClean = !tab?.dirty && !diff.changed && !configDiff.changed && !activationEvidence.dirty;
  const gateRecord = liveGateSnapshot?.dry_run_record || {};
  const gateForGraph = liveGateSnapshot?.graph_id === graphId;
  const gateOk = Boolean(gateForGraph && liveGateSnapshot?.gate_ok && gateRecord.digest && gateRecord.live_gate_recorded !== false);
  const confirmed = Boolean(runLiveConfirmInput?.checked);
  const moduleTab = draft?.metadata?.ide_tab_kind === "module";
  const issues = [];
  if (moduleTab) issues.push("Run is only available from the Main System graph tab.");
  if (!draftClean) issues.push("Unsaved draft route/config changes are present. Validate and Save Version first.");
  if (liveMode && !gateOk) issues.push("Active dry-run gate is missing or stale. Click Record Active Dry-run Gate.");
  if (liveMode && !confirmed) issues.push("Live device execution confirmation is unchecked.");
  return {
    ready: issues.length === 0,
    graphId,
    mode: normalizedMode,
    liveMode,
    draftClean,
    gateOk,
    confirmed,
    moduleTab,
    issues,
    diff,
    configDiff,
    gateRecord,
    checking: Boolean(liveGateSnapshot?.checking),
  };
}

function runPreflightTargetStripMarkup(status = livePreflightStatus()) {
  const digest = activationShortDigest(status.gateRecord?.digest);
  const targetState = status.moduleTab
    ? "Module tab selected"
    : status.draftClean
      ? "Saved active graph"
      : "Unsaved editor draft present";
  const gateState = status.gateOk
    ? `gate ${digest}`
    : status.checking
      ? "gate checking"
      : "gate missing/stale";
  return `
    <div class="runtime-run-target-strip ${status.ready ? "ok" : "warn"}">
      <span><strong>Execution Target</strong><em>${escapeHtml(targetState)}</em></span>
      <span><strong>Graph</strong><em>${escapeHtml(status.graphId || "graph")}</em></span>
      <span><strong>Mode</strong><em>${escapeHtml(status.mode || "test")}</em></span>
      <span><strong>Live Gate</strong><em>${escapeHtml(status.liveMode ? gateState : "not required")}</em></span>
    </div>
  `;
}

function runTargetSummaryMarkup(status = livePreflightStatus()) {
  const modeLabel = status.liveMode ? "live" : status.mode || "test";
  const targetLabel = status.moduleTab
    ? "Module tab cannot launch runs"
    : status.draftClean
      ? "Saved active graph"
      : "Blocked by unsaved editor draft";
  const requiredAction = status.ready
    ? `Run Saved ${modeLabel}`
    : status.moduleTab
      ? "Return to Main System tab"
      : !status.draftClean
        ? "Save Version or discard draft changes"
        : status.liveMode && !status.gateOk
          ? "Record Active Dry-run Gate"
          : status.liveMode && !status.confirmed
            ? "Confirm live device execution"
            : "Resolve run preflight issues";
  const issueText = status.issues.length ? status.issues.join("; ") : "Ready. This will execute the saved active graph config, not the editor draft.";
  return `
    <div class="runtime-run-target-summary-card ${status.ready ? "ok" : "warn"}">
      <div class="runtime-run-target-summary-head">
        <span>
          <strong>Saved active graph execution</strong>
          <small>Run buttons never execute unsaved editor JSON. Save Version first when the draft changes.</small>
        </span>
        <em>${escapeHtml(status.ready ? "ready" : "blocked")}</em>
      </div>
      <div class="runtime-run-target-summary-grid">
        <span><small>Execution Target</small><strong>${escapeHtml(targetLabel)}</strong></span>
        <span><small>Graph</small><strong>${escapeHtml(status.graphId || "graph")}</strong></span>
        <span><small>Selected Mode</small><strong>${escapeHtml(modeLabel)}</strong></span>
        <span><small>Required Action</small><strong>${escapeHtml(requiredAction)}</strong></span>
      </div>
      <p>${escapeHtml(issueText)}</p>
    </div>
  `;
}

function livePreflightMarkup(status = livePreflightStatus()) {
  const gateTime = status.gateRecord?.dry_run_at || "not recorded";
  const digest = activationShortDigest(status.gateRecord?.digest);
  const draftDetail = status.moduleTab
    ? "module tab"
    : status.draftClean
      ? "active config clean"
      : status.diff?.changed
        ? routeDiffSummaryText(status.diff)
        : configDiffSummaryText(status.configDiff);
  const items = [
    { label: "Mode", ok: true, detail: status.mode || "test" },
    { label: "Draft", ok: status.draftClean && !status.moduleTab, detail: draftDetail },
  ];
  if (status.liveMode) {
    items.push(
      { label: "Dry-run Gate", ok: status.gateOk, detail: status.gateOk ? `${digest} · ${gateTime}` : (status.checking ? "checking" : "missing/stale") },
      { label: "Live Confirm", ok: status.confirmed, detail: status.confirmed ? "operator confirmed" : "unchecked" },
    );
  }
  return `
    <div class="runtime-live-preflight-card ${status.ready ? "ok" : "warn"}">
      <div class="runtime-live-preflight-head">
        <strong>${escapeHtml(status.ready ? "Run preflight ready" : "Run preflight blocked")}</strong>
        <span>${escapeHtml(status.graphId || "graph")}</span>
      </div>
      ${runPreflightTargetStripMarkup(status)}
      <div class="runtime-live-preflight-items ${status.liveMode ? "live" : "standard"}">
        ${items.map((item) => `
          <span class="${item.ok ? "ok" : "warn"}">
            <strong>${escapeHtml(item.ok ? "OK" : "BLOCK")}</strong>
            <small>${escapeHtml(item.label)}</small>
            <em>${escapeHtml(item.detail)}</em>
          </span>
        `).join("")}
      </div>
      ${status.issues.length ? `<ul>${status.issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>` : `<p>${escapeHtml(status.liveMode ? "Live run will execute the saved active graph config after the recorded active dry-run gate." : "Run will execute the saved active graph config, not unsaved editor drafts.")}</p>`}
    </div>
  `;
}

function syncRunLauncherControls() {
  const selectedMode = runModeSelect?.value || "test";
  const selectedStatus = livePreflightStatus(null, selectedMode);
  const testStatus = livePreflightStatus(null, "test");
  const liveStatus = livePreflightStatus(null, "live");
  if (runLauncherBadge) {
    const label = selectedStatus.ready ? "ready" : "blocked";
    runLauncherBadge.textContent = selectedMode === "live" ? `live ${label}` : label;
    runLauncherBadge.className = `badge ${selectedStatus.ready ? "ok" : "warn"}`;
  }
  if (runTestBtn) {
    runTestBtn.disabled = !testStatus.ready;
    runTestBtn.title = testStatus.ready ? "Run saved active graph in test mode." : testStatus.issues.join("; ");
  }
  if (runLiveBtn) {
    runLiveBtn.disabled = !liveStatus.ready;
    runLiveBtn.title = liveStatus.ready ? "Run saved active graph in live mode." : liveStatus.issues.join("; ");
  }
  if (recordLiveGateBtn) {
    const canRecordGate = !selectedStatus.moduleTab && selectedStatus.draftClean;
    recordLiveGateBtn.disabled = !canRecordGate;
    recordLiveGateBtn.title = canRecordGate ? "Record active-config dry-run gate." : "Save or discard editor draft changes before recording an active gate.";
  }
}

function renderLivePreflight(mode = runModeSelect?.value || "test") {
  const status = livePreflightStatus(null, mode);
  if (runTargetSummaryOutput) runTargetSummaryOutput.innerHTML = runTargetSummaryMarkup(status);
  if (livePreflightOutput) livePreflightOutput.innerHTML = livePreflightMarkup(status);
  syncRunLauncherControls();
  renderDraftSafetyStrip();
}

async function loadGraphDryRunGate(graphId = graphIdForRunLauncher()) {
  if (!graphId) return;
  liveGateSnapshot = { graph_id: graphId, gate_ok: false, has_record: false, dry_run_record: {}, checking: true };
  renderLivePreflight();
  try {
    const result = await requestJson(`/api/graphs/${graphId}/dry-run-gate`);
    liveGateSnapshot = {
      graph_id: result.graph_id || graphId,
      gate_ok: Boolean(result.gate_ok),
      has_record: Boolean(result.has_record),
      dry_run_record: result.dry_run_record || {},
      checking: false,
    };
  } catch (err) {
    liveGateSnapshot = { graph_id: graphId, gate_ok: false, has_record: false, dry_run_record: {}, checking: false, error: String(err?.message || err) };
  }
  renderLivePreflight();
}

function setRunLauncherStatus(kind, label, detail = "") {
  if (runLaunchOutput) {
    runLaunchOutput.innerHTML = detail || `<div class="runtime-run-message ${escapeHtml(kind)}">${escapeHtml(label)}</div>`;
  }
  syncRunLauncherControls();
}

function runLauncherPayload(modeOverride = "") {
  const mode = modeOverride || runModeSelect?.value || "test";
  const backend = runBackendSelect?.value || "";
  const goal = runGoalInput?.value?.trim() || undefined;
  const fault = runFaultInput?.value?.trim() || "none";
  const fault_stage = runFaultStageInput?.value?.trim() || "";
  return {
    mode,
    ...(goal ? { goal } : {}),
    ...(backend ? { backend } : {}),
    ...(fault ? { fault } : {}),
    ...(fault_stage ? { fault_stage } : {}),
  };
}

function graphIdForRunLauncher() {
  const graph = parseGraphEditor();
  return graph.id || activeGraph?.id || graphSelect?.value || "atr_closed_loop";
}

function runStartResultMarkup(result, mode) {
  const dryRunRecord = result.dry_run_record || {};
  const run = result.run || {};
  return `
    <div class="runtime-run-result ${escapeHtml(result.ok ? "ok" : "warn")}">
      <strong>${escapeHtml(mode)} run ${escapeHtml(result.ok ? "started" : "failed")}</strong>
      <span>graph=${escapeHtml(result.graph_id || graphIdForRunLauncher())}</span>
      <span>run_id=${escapeHtml(run.run_id || run.id || currentRunId || "n/a")}</span>
      <small>dry_run_gate=${escapeHtml(dryRunRecord.dry_run_at || "not required/none")}</small>
    </div>
    <pre>${escapeHtml(JSON.stringify(result, null, 2).slice(0, 1800))}</pre>
  `;
}

async function recordActiveDryRunGate() {
  const graphId = graphIdForRunLauncher();
  setRunLauncherStatus("warn", "recording", "<div>Running active-config dry-run gate...</div>");
  const result = await requestJson(`/api/graphs/${graphId}/dry-run`, {
    method: "POST",
    body: JSON.stringify({ start_stage: "idle", max_steps: 24 }),
  });
  const record = result.dry_run_record || {};
  liveGateSnapshot = {
    graph_id: graphId,
    gate_ok: Boolean(result.ok && record.digest && record.live_gate_recorded !== false),
    has_record: Boolean(record.digest),
    dry_run_record: record,
    checking: false,
  };
  renderLivePreflight(runModeSelect?.value || "test");
  setRunLauncherStatus(result.ok ? "ok" : "warn", result.ok ? "gate recorded" : "gate failed", `
    <div class="runtime-run-result ${escapeHtml(result.ok ? "ok" : "warn")}">
      <strong>Active dry-run gate ${escapeHtml(result.ok ? "recorded" : "failed")}</strong>
      <span>graph=${escapeHtml(graphId)}</span>
      <span>steps=${escapeHtml(record.step_count ?? (result.sequence || []).length)}</span>
      <small>${escapeHtml(record.dry_run_at || "no dry-run timestamp")}</small>
    </div>
  `);
  await loadRecentEvents().catch(() => undefined);
}

async function startRuntimeGraphFromIde(modeOverride = "") {
  const graphId = graphIdForRunLauncher();
  const payload = runLauncherPayload(modeOverride);
  const preflight = livePreflightStatus(null, payload.mode);
  renderLivePreflight(payload.mode);
  if (!preflight.ready) {
    setRunLauncherStatus("warn", "run blocked", livePreflightMarkup(preflight));
    log(`${payload.mode} run blocked: ${preflight.issues.join("; ")}`, "warn");
    return;
  }
  setRunLauncherStatus("warn", "starting", `<div>Starting ${escapeHtml(payload.mode)} run for ${escapeHtml(graphId)}...</div>`);
  try {
    const result = await requestJson(`/api/graphs/${graphId}/run`, { method: "POST", body: JSON.stringify(payload) });
    setRunLauncherStatus(result.ok ? "ok" : "warn", result.ok ? "run started" : "run failed", runStartResultMarkup(result, payload.mode));
    await loadRunContext();
  } catch (err) {
    const message = String(err?.message || err);
    setRunLauncherStatus("warn", "run blocked", `<div><strong>Run blocked</strong></div><pre>${escapeHtml(message)}</pre>`);
    log(message, "error");
  }
}

function renderActivationChecklist() {
  if (!activationChecklistOutput) return;
  const graph = (() => { try { return parseGraphEditor(); } catch { return activeGraph || {}; } })();
  renderDraftSafetyStrip(graph);
  if (graph?.metadata?.ide_tab_kind === "module") {
    renderModuleActivationChecklist(graph);
    return;
  }
  const checks = [
    { key: "validation", label: "Validate Draft", detail: "schema + handler allowlist + compile check" },
    { key: "compile", label: "Compile Evidence", detail: "compiled graph summary available" },
    { key: "dry_run", label: "Dry-run Simulation", detail: "uses current editor draft payload" },
    { key: "save", label: "Saved Version", detail: "versioned config activation step" },
  ];
  const statuses = checks.map((item) => {
    const evidence = activationEvidence[item.key];
    if (evidence?.ok) return "ok";
    if (evidence?.ok === false) return "error";
    return activationEvidence.dirty ? "warn" : "idle";
  });
  const allReady = statuses.slice(0, 3).every((status) => status === "ok");
  if (activationOverallBadge) {
    activationOverallBadge.textContent = allReady ? "ready to save" : activationEvidence.dirty ? "draft changed" : "pending";
    activationOverallBadge.className = `badge ${allReady ? "ok" : activationEvidence.dirty ? "warn" : "idle"}`;
  }
  activationChecklistOutput.innerHTML = `
    <div class="runtime-activation-context">
      <span><strong>${escapeHtml(graph.id || "graph")}</strong><small>${escapeHtml(graph.name || "Runtime graph draft")}</small></span>
      <span><strong>${escapeHtml(graph.version || "draft")}</strong><small>config version</small></span>
      <span><strong>${escapeHtml(activationEvidence.reason || "pending")}</strong><small>check state</small></span>
    </div>
    ${routeDiffMarkup(activeDraftRouteDiff(graph))}
    ${configDiffMarkup(activeDraftConfigDiff(graph))}
    <div class="runtime-activation-steps">
      ${checks.map((item, index) => {
        const status = statuses[index];
        const evidence = activationEvidence[item.key];
        return `
          <div class="runtime-activation-step ${escapeHtml(status)}">
            <strong>${escapeHtml(item.label)}</strong>
            <span>${escapeHtml(item.detail)}</span>
            <small>${escapeHtml(activationEvidenceSummary(evidence))}</small>
          </div>
        `;
      }).join("")}
    </div>
    ${activationEvidenceDetailsMarkup()}
  `;
  renderLivePreflight();
}

function lastEventOfType(type) {
  return recentRuntimeEvents.find((event) => (event.type || event.event_type) === type) || null;
}

function latestEvaluation() {
  const evaluations = Array.isArray(latestStateSnapshot?.state?.experiment_evaluations) ? latestStateSnapshot.state.experiment_evaluations : [];
  return evaluations.length ? evaluations[evaluations.length - 1] : {};
}

function latestAnalysisPayload() {
  const stateAnalysis = latestStateSnapshot?.state?.latest_analysis;
  if (stateAnalysis && Object.keys(stateAnalysis).length) return stateAnalysis;
  const evaluation = latestEvaluation();
  return evaluation.analysis || evaluation.result || evaluation || {};
}

function metricCard(label, value, detail = "", level = "info") {
  return `
    <div class="runtime-metric-card ${escapeHtml(level)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
  `;
}

function systemResources(snapshot = latestStateSnapshot) {
  const resources = snapshot?.system_resources || snapshot?.runtime?.system_resources || {};
  return resources && typeof resources === "object" ? resources : {};
}

function resourceMetricLevel(status) {
  const clean = String(status || "unknown").toLowerCase();
  if (["ready", "ok", "active", "running"].includes(clean)) return "ok";
  if (["warn", "warning", "blocked", "pending"].includes(clean)) return "warn";
  if (["error", "failed", "offline", "stopped"].includes(clean)) return "error";
  return "idle";
}

function isFiniteMetricValue(value) {
  return value !== undefined && value !== null && value !== "" && Number.isFinite(Number(value));
}

function formatResourcePercent(value) {
  const number = Number(value);
  return isFiniteMetricValue(value) ? `${number.toFixed(1)}%` : "n/a";
}

function formatGb(value) {
  const number = Number(value);
  return isFiniteMetricValue(value) ? `${number.toFixed(1)} GB` : "n/a";
}

function formatRamDetail(ram = {}) {
  if (!ram || typeof ram !== "object") return "RAM metrics unavailable";
  if (isFiniteMetricValue(ram.used_gb) && isFiniteMetricValue(ram.total_gb)) {
    return `${formatGb(ram.used_gb)} / ${formatGb(ram.total_gb)} used`;
  }
  return ram.message || "RAM metrics unavailable";
}

function gpuAggregate(resources = systemResources()) {
  const gpu = resources.gpu || {};
  return gpu.aggregate && typeof gpu.aggregate === "object" ? gpu.aggregate : {};
}

function formatGpuDetail(gpu = {}) {
  if (!gpu || typeof gpu !== "object") return "GPU metrics unavailable";
  const aggregate = gpu.aggregate && typeof gpu.aggregate === "object" ? gpu.aggregate : {};
  const util = isFiniteMetricValue(aggregate.utilization_percent) ? ` · util ${Number(aggregate.utilization_percent).toFixed(0)}%` : "";
  if (isFiniteMetricValue(aggregate.memory_used_gb) && isFiniteMetricValue(aggregate.memory_total_gb)) {
    return `${formatGb(aggregate.memory_used_gb)} / ${formatGb(aggregate.memory_total_gb)} VRAM${util}`;
  }
  if (isFiniteMetricValue(aggregate.memory_used_gb)) {
    return `${formatGb(aggregate.memory_used_gb)} process VRAM${util}`;
  }
  return gpu.message || "GPU metrics unavailable";
}

function resourceWarningCount(resources = systemResources()) {
  const ramStatus = String(resources.ram?.status || "").toLowerCase();
  const gpuStatus = String(resources.gpu?.status || "").toLowerCase();
  return [ramStatus, gpuStatus].filter((status) => ["warn", "warning", "error", "failed", "offline"].includes(status)).length;
}

function statusBadgeClass(status) {
  const clean = String(status || "unknown").toLowerCase();
  if (["ready", "ok", "done", "completed", "success", "running", "active"].includes(clean)) return "ok";
  if (["warning", "warn", "blocked", "paused", "pending", "waiting_approval"].includes(clean)) return "warn";
  if (["error", "failed", "failure", "offline", "stopped"].includes(clean)) return "error";
  return "idle";
}

function renderInfraList(snapshot = latestStateSnapshot) {
  if (!infraListOutput || !snapshot) return;
  const state = snapshot.state || {};
  const runtime = snapshot.runtime || state.run_metadata || {};
  const backend = runtime.backend || state.run_metadata?.backend || {};
  const health = state.device_health || {};
  const models = runtime.models || state.run_metadata?.models || {};
  const modelLines = Object.entries(models).slice(0, 4).map(([key, value]) => {
    const item = value || {};
    return `<div><strong>${escapeHtml(key)}</strong><small>${escapeHtml(item.primary || "n/a")}</small></div>`;
  }).join("");
  infraListOutput.innerHTML = `
    <div class="runtime-infra-item"><strong>Backend</strong><small>${escapeHtml(backend.label || backend.name || "n/a")}</small></div>
    <div class="runtime-infra-item"><strong>MCP Tools</strong><small>ToolRegistry / agent context</small></div>
    <div class="runtime-infra-item"><strong>Memory / Logs</strong><small>${escapeHtml(snapshot.logs?.run_dir || "n/a")}</small></div>
    <div class="runtime-infra-item"><strong>Device Bridges</strong><small>${escapeHtml(Object.entries(health).map(([k, v]) => `${k}:${v}`).join(" · ") || "n/a")}</small></div>
    <div class="runtime-infra-models">${modelLines}</div>
  `;
}

function handlerOptions(selected = "") {
  const clean = String(selected || "");
  const values = Array.from(new Set([...availableHandlers, clean].filter(Boolean))).sort();
  return values
    .map((handler) => `<option value="${escapeHtml(handler)}"${handler === clean ? " selected" : ""}>${escapeHtml(handler)}</option>`)
    .join("");
}

function handlerMetadata(handlerId = "") {
  const clean = String(handlerId || "").trim();
  return clean ? availableHandlerMetadata.get(clean) || null : null;
}

function handlerMetadataStatus(handlerId = "") {
  const clean = String(handlerId || "").trim();
  if (!clean) return { kind: "idle", label: "not configured", detail: "No handler id configured.", errors: [] };
  if (!availableHandlers.length) return { kind: "idle", label: "catalog loading", detail: "Handler catalog has not loaded yet.", errors: [] };
  const meta = handlerMetadata(clean);
  if (!meta) return { kind: "error", label: "not allowlisted", detail: `${clean} is not present in /api/handlers.`, errors: [] };
  const errors = Array.isArray(meta.errors) ? meta.errors : [];
  if (errors.length || meta.accepts_runtime_state === false) {
    return { kind: "error", label: "signature invalid", detail: errors[0] || "Handler cannot be called as handler(runtime_state).", errors };
  }
  return { kind: "ok", label: "runtime-callable", detail: meta.signature || "handler(runtime_state)", errors: [] };
}

function handlerSignatureText(handlerId = "") {
  const meta = handlerMetadata(handlerId);
  return meta?.signature || (handlerId ? "metadata unavailable" : "not configured");
}

function handlerOriginText(handlerId = "") {
  const meta = handlerMetadata(handlerId);
  if (!meta) return handlerId ? "metadata unavailable" : "not configured";
  return `${meta.module || "module"}.${meta.qualname || "handler"}`;
}

function handlerStatusPillMarkup(handlerId = "") {
  const status = handlerMetadataStatus(handlerId);
  return `<span class="runtime-node-status-pill ${escapeHtml(status.kind)}">${escapeHtml(status.label)}</span>`;
}

function handlerErrorListMarkup(handlerId = "") {
  const status = handlerMetadataStatus(handlerId);
  if (!status.errors.length) return "";
  return `<ul class="runtime-handler-error-list">${status.errors.map((error) => `<li>${escapeHtml(error)}</li>`).join("")}</ul>`;
}

function moduleTextLines(value) {
  if (Array.isArray(value)) return value.join("\n");
  if (value === undefined || value === null) return "";
  return String(value);
}

function moduleLlm(module) {
  return module.llm && typeof module.llm === "object" && !Array.isArray(module.llm) ? module.llm : {};
}

function modulePrompt(module) {
  if (typeof module.prompt === "string") return { system: module.prompt };
  return module.prompt && typeof module.prompt === "object" && !Array.isArray(module.prompt) ? module.prompt : {};
}

function moduleToolGroups(selectedTools = []) {
  const selected = new Set((Array.isArray(selectedTools) ? selectedTools : []).map((tool) => String(tool || "").trim()).filter(Boolean));
  const known = Array.from(new Set([...availableTools, ...selected].filter(Boolean))).sort();
  const groups = new Map();
  for (const tool of known) {
    const prefix = tool.includes(".") ? tool.split(".")[0] : "custom";
    if (!groups.has(prefix)) groups.set(prefix, []);
    groups.get(prefix).push(tool);
  }
  return { selected, groups };
}

function renderModuleToolPicker(selectedTools = []) {
  const { selected, groups } = moduleToolGroups(selectedTools);
  const customTools = Array.from(selected).filter((tool) => availableTools.length && !availableTools.includes(tool));
  const manualValue = availableTools.length ? customTools.join("\n") : Array.from(selected).join("\n");
  if (!groups.size) {
    return `
      <p class="hint">ToolRegistry 목록을 읽지 못했습니다. 수동 입력값으로 allowlist를 유지합니다.</p>
      <textarea id="ide-module-tools" class="runtime-module-small-textarea" spellcheck="false">${escapeHtml(manualValue)}</textarea>
    `;
  }
  return `
    <div class="runtime-module-tool-groups">
      ${Array.from(groups.entries()).map(([group, tools]) => `
        <div class="runtime-module-tool-group">
          <strong>${escapeHtml(group)}</strong>
          <div class="runtime-module-tool-list">
            ${tools.map((tool) => `
              <label class="runtime-module-tool-chip">
                <input type="checkbox" data-module-tool-checkbox value="${escapeHtml(tool)}" ${selected.has(tool) ? "checked" : ""} />
                <span>${escapeHtml(tool)}</span>
              </label>
            `).join("")}
          </div>
        </div>
      `).join("")}
    </div>
    <details class="runtime-module-custom-tools">
      <summary><span>Custom / unregistered tools</span><small>one per line</small></summary>
      <textarea id="ide-module-tools" class="runtime-module-small-textarea" spellcheck="false">${escapeHtml(manualValue)}</textarea>
    </details>
  `;
}

function renderModuleTabs() {
  if (!moduleTabsOutput) return;
  if (!availableModules.length) {
    moduleTabsOutput.innerHTML = `<div class="runtime-module-tab-empty">No modules loaded.</div>`;
    return;
  }
  moduleTabsOutput.innerHTML = availableModules.map((module) => {
    const active = module.id === activeModuleId ? " active" : "";
    return `<button class="runtime-module-tab${active}" type="button" data-module-tab="${escapeHtml(module.id)}">
      ${runtimeNodeIconMarkup(moduleIconName(module))}
      <span class="runtime-module-tab-copy">
        <strong>${escapeHtml(module.label || module.id)}</strong>
        <small>${escapeHtml(module.category || "runtime")} · ${escapeHtml(module.handler || "handler")}</small>
      </span>
    </button>`;
  }).join("");
  moduleTabsOutput.querySelectorAll("[data-module-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const moduleId = button.getAttribute("data-module-tab") || "";
      if (!moduleId || moduleId === activeModuleId) return;
      moduleSelect.value = moduleId;
      loadModule().catch((err) => log(String(err), "error"));
    });
  });
}

function updateModuleSummary(module) {
  const llm = moduleLlm(module);
  const prompt = modulePrompt(module);
  const retry = module.retry && typeof module.retry === "object" && !Array.isArray(module.retry) ? module.retry : {};
  const safety = module.safety && typeof module.safety === "object" && !Array.isArray(module.safety) ? module.safety : {};
  const preCount = Array.isArray(module.pre_execution) ? module.pre_execution.length : 0;
  const internalCount = Array.isArray(module.internal_graph) ? module.internal_graph.length : 0;
  const toolCount = Array.isArray(module.tools) ? module.tools.length : 0;
  moduleSummary.innerHTML = `
    <div class="runtime-module-agent-head">
      <div class="runtime-module-agent-title">
        ${runtimeNodeIconMarkup(moduleIconName(module))}
        <div>
          <span class="runtime-module-id-pill">${escapeHtml(module.id || activeModuleId || "module")}</span>
          <h3>${escapeHtml(module.label || module.id || "Module")}</h3>
          <p>${escapeHtml(module.handler || "runtime.step_complete")} · ${escapeHtml(module.llm_role || "inherit llm route")}</p>
        </div>
      </div>
      <div class="runtime-module-health-strip">
        <span><strong>${escapeHtml(preCount)}</strong><small>pre</small></span>
        <span><strong>${escapeHtml(internalCount)}</strong><small>steps</small></span>
        <span><strong>${escapeHtml(toolCount)}</strong><small>tools</small></span>
      </div>
    </div>
    <div class="runtime-module-config-cards">
      <section class="runtime-module-config-card">
        <div class="runtime-module-card-title"><strong>Basic Routing</strong><small>actual runtime handler</small></div>
        <label class="runtime-handler-select-label">Module Handler
          <select id="ide-module-handler-select" class="text-input">${handlerOptions(module.handler || "")}</select>
        </label>
        <label class="runtime-handler-select-label">LLM Role
          <input id="ide-module-llm-role" class="text-input" value="${escapeHtml(module.llm_role || "")}" placeholder="inherit route" />
        </label>
      </section>
      <section class="runtime-module-config-card">
        <div class="runtime-module-card-title"><strong>LLM Runtime</strong><small>backend/model override</small></div>
        <label class="runtime-handler-select-label">Backend
          <select id="ide-module-llm-backend" class="text-input">
            ${["", "vllm", "ollama", "nemoclaw", "mock"].map((item) => `<option value="${item}"${item === (llm.backend || "") ? " selected" : ""}>${item || "inherit"}</option>`).join("")}
          </select>
        </label>
        <label class="runtime-handler-select-label">Model
          <input id="ide-module-llm-model" class="text-input" value="${escapeHtml(llm.model || llm.primary || "")}" placeholder="inherit router default" />
        </label>
      </section>
      <section class="runtime-module-config-card">
        <div class="runtime-module-card-title"><strong>Execution Policy</strong><small>retry, timeout, approval</small></div>
        <div class="runtime-module-two-col">
          <label class="runtime-handler-select-label">Timeout seconds
            <input id="ide-module-timeout" class="text-input" type="number" min="0" step="1" value="${escapeHtml(module.timeout_s ?? "")}" />
          </label>
          <label class="runtime-handler-select-label">Retry max attempts
            <input id="ide-module-retry" class="text-input" type="number" min="0" max="10" step="1" value="${escapeHtml(retry.max_attempts ?? "")}" />
          </label>
        </div>
        <div class="runtime-module-checkboxes">
          <label><input id="ide-module-live-validation" type="checkbox" ${safety.live_requires_validation ? "checked" : ""} /> live validation</label>
          <label><input id="ide-module-dry-run-supported" type="checkbox" ${safety.dry_run_supported !== false ? "checked" : ""} /> dry-run</label>
          <label><input id="ide-module-human-approval" type="checkbox" ${safety.requires_human_approval ? "checked" : ""} /> human approval</label>
        </div>
      </section>
      <section class="runtime-module-config-card wide">
        <div class="runtime-module-card-title"><strong>Tool Allowlist</strong><small>checked tools are callable by this module</small></div>
        ${renderModuleToolPicker(module.tools || [])}
      </section>
      <section class="runtime-module-config-card wide prompt-card">
        <div class="runtime-module-card-title"><strong>Prompt Overrides</strong><small>leave empty to inherit defaults</small></div>
        <label class="runtime-handler-select-label">Prompt path
          <input id="ide-module-prompt-path" class="text-input" value="${escapeHtml(prompt.path || "")}" placeholder="docs/... or prompts/..." />
        </label>
        <div class="runtime-module-two-col prompt-columns">
          <label class="runtime-handler-select-label">System prompt override
            <textarea id="ide-module-prompt-system" class="runtime-module-small-textarea" spellcheck="false">${escapeHtml(prompt.system || "")}</textarea>
          </label>
          <label class="runtime-handler-select-label">Developer prompt override
            <textarea id="ide-module-prompt-developer" class="runtime-module-small-textarea" spellcheck="false">${escapeHtml(prompt.developer || "")}</textarea>
          </label>
        </div>
      </section>
    </div>
    <div class="runtime-module-config-footer">
      <button id="ide-module-config-apply-btn" class="btn primary" type="button">Apply Config Draft</button>
      <span id="ide-module-config-status" class="hint">draft ready · pre ${escapeHtml(preCount)} · internal ${escapeHtml(internalCount)}</span>
    </div>
  `;
  const select = document.getElementById("ide-module-handler-select");
  if (select) {
    select.addEventListener("change", () => updateModuleHandler(select.value));
  }
  moduleSummary.querySelectorAll("input, textarea, select").forEach((el) => {
    if (el.id === "ide-module-handler-select") return;
    const eventName = el.getAttribute("type") === "checkbox" ? "change" : "input";
    el.addEventListener(eventName, () => {
      const status = document.getElementById("ide-module-config-status");
      if (status) status.textContent = "draft has unapplied form edits";
    });
  });
  document.getElementById("ide-module-config-apply-btn")?.addEventListener("click", updateModuleConfigFromForm);
}


function logicalRouteRecords(graph) {
  const records = new Map();
  const transitions = graph?.transitions && typeof graph.transitions === "object" ? graph.transitions : {};
  for (const [source, target] of Object.entries(transitions)) {
    if (!source || !target) continue;
    const key = `${source}|${target}|default`;
    records.set(key, { key, source, target, condition: "default", type: "default" });
  }
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  for (const edge of edges) {
    if (edge.metadata?.runtime_edge !== "logical_transition") continue;
    const source = edge.metadata?.from_stage || edge.source || "";
    const target = edge.metadata?.to_stage || edge.target || "";
    if (!source || !target) continue;
    const condition = logicalEdgeCondition(edge) || (edge.metadata?.default_transition ? "default" : `candidate:${target}`);
    const normalizedCondition = ["", "continue", "always"].includes(condition) ? "default" : condition;
    const type = normalizedCondition === "default" || edge.metadata?.default_transition ? "default" : "candidate";
    const key = `${source}|${target}|${normalizedCondition}`;
    records.set(key, { key, source, target, condition: normalizedCondition, type });
  }
  return records;
}

function graphRouteDiff(baselineGraph, draftGraph) {
  const base = logicalRouteRecords(baselineGraph || {});
  const draft = logicalRouteRecords(draftGraph || {});
  const added = [];
  const removed = [];
  const unchanged = [];
  for (const [key, route] of draft.entries()) {
    if (base.has(key)) unchanged.push(route);
    else added.push(route);
  }
  for (const [key, route] of base.entries()) {
    if (!draft.has(key)) removed.push(route);
  }
  return { added, removed, unchanged, changed: Boolean(added.length || removed.length) };
}

function routeRecordText(route) {
  const condition = route.condition === "default" ? "default" : route.condition;
  return `${route.source} -> ${route.target} (${condition})`;
}

function activeDraftRouteDiff(graph = null) {
  const tab = activeGraphTab();
  const draft = graph || activeGraph || (() => { try { return parseGraphEditor(); } catch { return {}; } })();
  return graphRouteDiff(tab?.baselineGraph || tab?.activeGraph || null, draft);
}

function graphConfigDiff(baselineGraph, draftGraph) {
  const baselineFingerprint = graphConfigFingerprint(baselineGraph || {});
  const draftFingerprint = graphConfigFingerprint(draftGraph || {});
  return {
    changed: Boolean(baselineFingerprint && draftFingerprint && baselineFingerprint !== draftFingerprint),
    baselineFingerprint,
    draftFingerprint,
  };
}

function activeDraftConfigDiff(graph = null) {
  const tab = activeGraphTab();
  const draft = graph || activeGraph || (() => { try { return parseGraphEditor(); } catch { return {}; } })();
  return graphConfigDiff(tab?.baselineGraph || tab?.activeGraph || null, draft);
}

function configDiffSummaryText(diff) {
  if (!diff?.changed) return "Full graph config matches active baseline.";
  return "Full graph config differs from active baseline.";
}

function configDiffMarkup(diff = activeDraftConfigDiff()) {
  const changed = Boolean(diff?.changed);
  return `
    <div class="runtime-route-diff ${changed ? "changed" : "clean"}">
      <div class="runtime-route-diff-head">
        <strong>${escapeHtml(changed ? "Draft config changes" : "Config baseline clean")}</strong>
        <span>${escapeHtml(configDiffSummaryText(diff))}</span>
      </div>
      <p>${escapeHtml(changed ? "Non-route settings such as handler, module, model, timeout, retry, safety, metadata, or node position changed. Save Version before running any mode." : "The editor draft fingerprint matches the last loaded/saved active graph config.")}</p>
    </div>
  `;
}

function routeDiffSummaryText(diff) {
  if (!diff?.changed) return "No route changes from active baseline.";
  return `${diff.added.length} added · ${diff.removed.length} removed`;
}

function routeDiffMarkup(diff = activeDraftRouteDiff()) {
  const changed = Boolean(diff?.changed);
  const added = diff?.added || [];
  const removed = diff?.removed || [];
  const visibleAdded = added.slice(0, 5);
  const visibleRemoved = removed.slice(0, 5);
  return `
    <div class="runtime-route-diff ${changed ? "changed" : "clean"}">
      <div class="runtime-route-diff-head">
        <strong>${escapeHtml(changed ? "Draft route changes" : "Route baseline clean")}</strong>
        <span>${escapeHtml(routeDiffSummaryText(diff))}</span>
      </div>
      ${changed ? `
        <div class="runtime-route-diff-columns">
          <div>
            <small>Added / updated in draft</small>
            ${visibleAdded.length ? visibleAdded.map((route) => `<span class="added">+ ${escapeHtml(routeRecordText(route))}</span>`).join("") : `<span class="muted">none</span>`}
            ${added.length > visibleAdded.length ? `<em>+${escapeHtml(added.length - visibleAdded.length)} more</em>` : ""}
          </div>
          <div>
            <small>Removed from active baseline</small>
            ${visibleRemoved.length ? visibleRemoved.map((route) => `<span class="removed">- ${escapeHtml(routeRecordText(route))}</span>`).join("") : `<span class="muted">none</span>`}
            ${removed.length > visibleRemoved.length ? `<em>+${escapeHtml(removed.length - visibleRemoved.length)} more</em>` : ""}
          </div>
        </div>
      ` : `<p>Draft routes match the last loaded/saved active graph config.</p>`}
    </div>
  `;
}

function draftSafetyItemMarkup(item) {
  return `
    <span class="runtime-draft-safety-item ${escapeHtml(item.status || "idle")}" title="${escapeHtml(item.detail || "")}">
      <small>${escapeHtml(item.label || "Status")}</small>
      <strong>${escapeHtml(item.value || "pending")}</strong>
      <em>${escapeHtml(item.detail || "")}</em>
    </span>
  `;
}

function draftSafetyStripStatus(graph = null) {
  const draft = graph || activeGraph || (() => { try { return parseGraphEditor(); } catch { return {}; } })();
  const tab = activeGraphTab();
  const graphId = draft?.id || tab?.graphId || graphSelect?.value || "graph";
  const routeDiff = activeDraftRouteDiff(draft);
  const configDiff = activeDraftConfigDiff(draft);
  const routeChanged = Boolean(routeDiff?.changed);
  const configChanged = Boolean(configDiff?.changed);
  const tabDirty = Boolean(tab?.dirty);
  const isModule = tab?.kind === "module" || draft?.metadata?.ide_tab_kind === "module";

  if (isModule) {
    const moduleId = draft?.metadata?.module_id || tab?.moduleId || activeModuleId || "module";
    let preflight = { ok: false, validationOk: false, dryRunOk: false, dirty: true, reason: "not checked", record: {} };
    try {
      preflight = moduleSavePreflightStatus(moduleId, modulePayloadForGraphDraft(draft));
    } catch (err) {
      preflight = { ...preflight, reason: String(err?.message || err || "module draft unavailable") };
    }
    const saveOk = Boolean(preflight.record?.save?.ok && preflight.record.save.fingerprint === preflight.fingerprint);
    const draftChanged = Boolean(tabDirty || routeChanged || configChanged || preflight.dirty);
    const nextAction = draftChanged && !(preflight.validationOk && preflight.dryRunOk)
      ? "Validate Module + Dry Run, then Save Module Version"
      : draftChanged
        ? "Save Module Version to activate checked module draft"
        : saveOk
          ? "Module version saved; return to Main System when ready"
          : preflight.validationOk && preflight.dryRunOk
            ? "Save Module Version"
            : !preflight.validationOk
              ? "Validate Module Draft"
              : "Dry-run Module Draft";
    const primaryAction = !preflight.validationOk
      ? { id: "validate", label: "Validate Module" }
      : !preflight.dryRunOk
        ? { id: "dry-run", label: "Dry Run Module" }
        : !saveOk || draftChanged
          ? { id: "save", label: "Save Module" }
          : { id: "focus-main", label: "Return Main" };
    const secondaryAction = draftChanged ? { id: "discard-draft", label: "Discard Draft" } : null;
    return {
      mode: "module",
      status: saveOk && !draftChanged ? "ok" : draftChanged || preflight.ok ? "warn" : "idle",
      title: `${moduleId} module draft`,
      summary: draftChanged ? "Internal module config differs from its saved baseline." : "Internal module graph matches its saved baseline.",
      nextAction,
      primaryAction,
      secondaryAction,
      items: [
        { label: "Draft", value: draftChanged ? "changed" : "clean", status: draftChanged ? "warn" : "ok", detail: tabDirty ? "tab has unsaved local edits" : preflight.reason || "module baseline check" },
        { label: "Routes", value: routeChanged ? `${routeDiff.added.length}+/${routeDiff.removed.length}-` : "clean", status: routeChanged ? "warn" : "ok", detail: routeChanged ? "module step routes changed" : "module step routes match baseline" },
        { label: "Config", value: configChanged ? "changed" : "clean", status: configChanged ? "warn" : "ok", detail: configChanged ? "module node/config fingerprint changed" : "module fingerprint matches baseline" },
        { label: "Validate", value: preflight.validationOk ? "ok" : "missing", status: preflight.validationOk ? "ok" : preflight.record?.validation?.ok === false ? "error" : "idle", detail: preflight.validationOk ? "current module draft validated" : "validate exact module draft" },
        { label: "Dry-run", value: preflight.dryRunOk ? "ok" : "missing", status: preflight.dryRunOk ? "ok" : preflight.record?.dry_run?.ok === false ? "error" : "idle", detail: preflight.dryRunOk ? "current module draft dry-run passed" : "dry-run exact module draft" },
        { label: "Save", value: saveOk && !draftChanged ? "active" : "needed", status: saveOk && !draftChanged ? "ok" : preflight.ok ? "warn" : "idle", detail: saveOk && !draftChanged ? "saved module version matches draft" : "save only after matching validate + dry-run" },
      ],
    };
  }

  const draftChanged = Boolean(tabDirty || routeChanged || configChanged || activationEvidence.dirty);
  const validationOk = Boolean(activationEvidence.validation?.ok && !activationEvidence.dirty);
  const compileOk = Boolean(activationEvidence.compile?.ok && !activationEvidence.dirty);
  const dryRunOk = Boolean(activationEvidence.dry_run?.ok && !activationEvidence.dirty);
  const liveGateOk = Boolean(liveGateSnapshot?.graph_id === graphId && liveGateSnapshot?.gate_ok && liveGateSnapshot?.dry_run_record?.digest);
  const nextAction = draftChanged && !(validationOk && dryRunOk)
    ? "Validate + Dry Run, then Save Version"
    : draftChanged
      ? "Save Version to activate checked graph draft"
      : !validationOk
        ? "Validate Draft"
        : !dryRunOk
          ? "Dry Run"
          : !liveGateOk
            ? "Record Active Dry-run Gate before live"
            : "Ready to run saved active graph";
  const primaryAction = !validationOk
    ? { id: "validate", label: "Validate Draft" }
    : !dryRunOk
      ? { id: "dry-run", label: "Dry Run Draft" }
      : draftChanged
        ? { id: "save", label: "Save Version" }
        : !liveGateOk
          ? { id: "record-gate", label: "Record Gate" }
          : { id: "open-run-launcher", label: "Open Run Launcher" };
  const secondaryAction = draftChanged ? { id: "discard-draft", label: "Discard Draft" } : null;
  return {
    mode: "graph",
    status: draftChanged ? "warn" : validationOk && dryRunOk ? "ok" : "idle",
    title: `${graphId} graph draft`,
    summary: draftChanged ? "Editor draft differs from the saved active graph." : "Editor matches the saved active graph.",
    nextAction,
    primaryAction,
    secondaryAction,
    items: [
      { label: "Draft", value: draftChanged ? "changed" : "clean", status: draftChanged ? "warn" : "ok", detail: tabDirty ? "tab has unsaved local edits" : activationEvidence.reason || "graph baseline check" },
      { label: "Routes", value: routeChanged ? `${routeDiff.added.length}+/${routeDiff.removed.length}-` : "clean", status: routeChanged ? "warn" : "ok", detail: routeChanged ? "runtime route table changed" : "routes match active baseline" },
      { label: "Config", value: configChanged ? "changed" : "clean", status: configChanged ? "warn" : "ok", detail: configChanged ? "full graph fingerprint changed" : "full graph fingerprint matches active baseline" },
      { label: "Validate", value: validationOk ? "ok" : "missing", status: validationOk ? "ok" : activationEvidence.validation?.ok === false ? "error" : "idle", detail: validationOk ? "draft validation evidence is present" : "validate exact graph draft" },
      { label: "Dry-run", value: dryRunOk ? "ok" : "missing", status: dryRunOk ? "ok" : activationEvidence.dry_run?.ok === false ? "error" : "idle", detail: dryRunOk ? "draft dry-run evidence is present" : "simulate exact graph draft" },
      { label: "Live Gate", value: liveGateOk ? "ready" : "needed", status: liveGateOk ? "ok" : "idle", detail: liveGateOk ? "active config has dry-run gate" : "record active dry-run gate before live mode" },
    ],
  };
}

function renderDraftSafetyStrip(graph = null) {
  if (!draftSafetyStrip) return;
  let status;
  try {
    status = draftSafetyStripStatus(graph);
  } catch (err) {
    status = {
      mode: "error",
      status: "error",
      title: "Draft safety unavailable",
      summary: String(err?.message || err || "unknown error"),
      nextAction: "Fix graph JSON before operating",
      primaryAction: null,
      items: [],
    };
  }
  const action = status.primaryAction || null;
  const secondaryAction = status.secondaryAction || null;
  draftSafetyStrip.className = `runtime-draft-safety-strip ${escapeHtml(status.status || "idle")}`;
  draftSafetyStrip.innerHTML = `
    <div class="runtime-draft-safety-head">
      <span>
        <strong>${escapeHtml(status.title)}</strong>
        <small>${escapeHtml(status.summary)}</small>
      </span>
      <em>${escapeHtml(status.mode === "module" ? "module gate" : "graph gate")}</em>
    </div>
    <div class="runtime-draft-safety-items">
      ${(status.items || []).map(draftSafetyItemMarkup).join("")}
    </div>
    <div class="runtime-draft-safety-next">
      <span>
        <small>Next action</small>
        <strong>${escapeHtml(status.nextAction || "Review draft evidence")}</strong>
      </span>
      <span class="runtime-draft-safety-actions">
        ${secondaryAction ? `<button type="button" class="btn tiny runtime-draft-safety-action" data-draft-safety-action="${escapeHtml(secondaryAction.id)}">${escapeHtml(secondaryAction.label)}</button>` : ""}
        ${action ? `<button type="button" class="btn tiny primary runtime-draft-safety-action" data-draft-safety-action="${escapeHtml(action.id)}">${escapeHtml(action.label)}</button>` : ""}
      </span>
    </div>
  `;
  draftSafetyStrip.querySelectorAll("[data-draft-safety-action]").forEach((button) => {
    button.addEventListener("click", () => executeDraftSafetyAction(button.getAttribute("data-draft-safety-action") || "").catch((err) => log(String(err), "error")));
  });
}


async function discardActiveDraft() {
  const tab = activeGraphTab();
  if (!tab) return;
  if (tab.kind === "module") {
    const moduleId = tab.moduleId || activeModuleId || activeGraph?.metadata?.module_id || "module";
    let payload = tab.baselineModulePayload ? cloneConfig(tab.baselineModulePayload) : null;
    if (!payload) {
      try {
        const result = await requestJson(`/api/modules/${moduleId}`);
        payload = result.module;
      } catch (_err) {
        payload = null;
      }
    }
    const normalized = normalizedModulePayload(payload || tab.modulePayload || modulePayloadCache.get(moduleId) || { module: { id: moduleId } });
    const graph = modulePayloadToGraph(normalized);
    activeModuleId = moduleId;
    if (moduleSelect) moduleSelect.value = moduleId;
    tab.modulePayload = cloneConfig(normalized);
    tab.baselineModulePayload = cloneConfig(normalized);
    tab.graph = graph;
    tab.baselineGraph = cloneConfig(graph);
    tab.dirty = false;
    modulePayloadCache.set(moduleId, cloneConfig(normalized));
    modulePreflightEvidence.set(moduleId, { validation: null, dry_run: null, save: null, dirty: false, reason: "discarded" });
    setModuleJson(normalized);
    updateModuleSummary(normalized.module || {});
    renderModuleGraph(normalized);
    setStatus("busy", "Module Draft Discarded", `${moduleId}: restored saved module baseline.`);
    renderGraph(graph);
    log(`Discarded module draft ${moduleId}; restored saved module baseline.`, "ok");
    return;
  }

  const baseline = cloneConfig(tab.baselineGraph || tab.graph || activeGraph || {});
  tab.graph = baseline;
  tab.baselineGraph = cloneConfig(baseline);
  tab.dirty = false;
  activationEvidence = { validation: null, compile: null, dry_run: null, save: null, dirty: false, reason: "discarded" };
  selectedNodeId = "";
  activeRuntimeEdge = null;
  edgeConnectMode = false;
  edgeConnectSource = "";
  edgeConnectDraft = null;
  renderGraph(baseline);
  renderLivePreflight(runModeSelect?.value || "test");
  if (baseline.id) loadGraphDryRunGate(baseline.id).catch((err) => log(String(err), "error"));
  setStatus("busy", "Draft Discarded", `${baseline.id || "graph"}: restored saved active baseline.`);
  log(`Discarded graph draft ${baseline.id || "graph"}; restored saved active baseline.`, "ok");
}

async function executeDraftSafetyAction(action) {
  if (!action) return;
  if (action === "validate") {
    await validateGraph();
    return;
  }
  if (action === "dry-run") {
    await dryRunGraph("idle", dryRunOutput);
    return;
  }
  if (action === "save") {
    await saveGraph();
    return;
  }
  if (action === "record-gate") {
    await recordActiveDryRunGate();
    return;
  }
  if (action === "discard-draft") {
    await discardActiveDraft();
    return;
  }
  if (action === "open-run-launcher") {
    if (runLauncherDrawer) runLauncherDrawer.open = true;
    runLauncherDrawer?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    renderLivePreflight(runModeSelect?.value || "test");
    return;
  }
  if (action === "focus-main") {
    activateGraphTab(MAIN_GRAPH_TAB_ID);
  }
}

function updateEdgeEditStatus(message = "") {
  if (!edgeEditStatus) return;
  if (message) {
    edgeEditStatus.textContent = message;
    renderEdgeRoutePreview();
    return;
  }
  edgeEditStatus.textContent = edgeConnectDraft
    ? `port connect: ${edgeConnectDraft.sourceStage || edgeConnectDraft.sourceNodeId}:${edgeConnectDraft.sourceSide}; choose target port`
    : edgeConnectMode
      ? edgeConnectSource
        ? `chain connect source=${edgeConnectSource}; click target node or port`
        : "connect mode: choose source node or port"
      : activeRuntimeEdge
        ? `selected edge ${activeRuntimeEdge.source} -> ${activeRuntimeEdge.target} · ${activeRuntimeEdge.condition || "default"}`
        : "select edge, or drag from node port";
  renderEdgeRoutePreview();
}

function conditionPresetFromCondition(condition = "") {
  const clean = String(condition || "default").trim();
  if (["", "default", "continue", "always"].includes(clean)) return "default";
  if (clean.startsWith("next_stage:")) return "next_stage";
  if (clean.startsWith("decision:")) return "decision";
  if (clean.startsWith("guardian_decision:")) return "guardian_decision";
  return "custom";
}

function transitionConditionSpec() {
  const source = transitionSource?.value || "";
  const target = transitionTarget?.value || "";
  const preset = transitionConditionPreset?.value || "default";
  const rawValue = String(transitionConditionInput?.value || "").trim();
  if (preset === "default") return { source, target, condition: "default", makeDefault: true, label: "default" };
  if (preset === "next_stage") {
    const stage = rawValue.replace(/^next_stage:/, "").trim() || target;
    return { source, target, condition: `next_stage:${stage}`, makeDefault: false, label: `next_stage:${stage}` };
  }
  if (preset === "decision") {
    const decision = rawValue.replace(/^decision:/, "").trim() || target;
    return { source, target, condition: `decision:${decision}`, makeDefault: false, label: `decision:${decision}` };
  }
  if (preset === "guardian_decision") {
    const decision = rawValue.replace(/^guardian_decision:/, "").trim() || target;
    return { source, target, condition: `guardian_decision:${decision}`, makeDefault: false, label: `guardian_decision:${decision}` };
  }
  const custom = rawValue || `next_stage:${target}`;
  const makeDefault = ["", "default", "continue", "always"].includes(custom);
  return { source, target, condition: custom, makeDefault, label: custom };
}

function setTransitionConditionControls(condition = "default", target = "") {
  if (!transitionConditionPreset || !transitionConditionInput) return;
  const clean = String(condition || "default").trim();
  const preset = conditionPresetFromCondition(clean);
  transitionConditionPreset.value = preset;
  if (preset === "default") transitionConditionInput.value = "default";
  else if (preset === "next_stage") transitionConditionInput.value = clean || `next_stage:${target}`;
  else if (preset === "decision") transitionConditionInput.value = clean;
  else if (preset === "guardian_decision") transitionConditionInput.value = clean;
  else transitionConditionInput.value = clean;
}

function updateTransitionConditionPlaceholder() {
  if (!transitionConditionInput || !transitionConditionPreset) return;
  const target = transitionTarget?.value || "target";
  const preset = transitionConditionPreset.value || "default";
  const placeholders = {
    default: "default",
    next_stage: `next_stage:${target}`,
    decision: "decision:retry",
    guardian_decision: "guardian_decision:stop",
    custom: `next_stage:${target}`,
  };
  transitionConditionInput.placeholder = placeholders[preset] || `next_stage:${target}`;
  if (preset === "default") transitionConditionInput.value = "default";
  renderEdgeRoutePreview();
}

function routeConditionExplanation(condition = "", target = "") {
  const clean = String(condition || "default").trim();
  if (["", "default", "continue", "always"].includes(clean)) {
    return `Default route from the source stage. The runtime uses it when no candidate condition is selected.`;
  }
  if (clean.startsWith("next_stage:")) {
    const stage = clean.split(":", 2)[1] || target;
    return `Candidate route selected when state/run metadata or agent_result requests next_stage=${stage}.`;
  }
  if (clean.startsWith("decision:")) {
    const decision = clean.split(":", 2)[1] || "value";
    return `Candidate route selected when transition_decision or routing_decision equals ${decision}.`;
  }
  if (clean.startsWith("guardian_decision:")) {
    const decision = clean.split(":", 2)[1] || "value";
    return `Candidate route selected when the Guardian decision equals ${decision}.`;
  }
  return `Custom route condition. Confirm GraphConfig.next_stage can evaluate this condition or add condition_key metadata.`;
}

function edgeRecordsForRoute(graph, source = "", target = "") {
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  return edges.filter((edge) => {
    if (edge.metadata?.runtime_edge !== "logical_transition") return false;
    const from = edge.metadata?.from_stage || edge.source;
    const to = edge.metadata?.to_stage || edge.target;
    return (!source || from === source) && (!target || to === target);
  });
}

function routeInventoryMarkup(graph, source = "") {
  if (!source) return "";
  let outgoing = [];
  try {
    outgoing = logicalGraphEdges(graph).filter((edge) => edge.sourceStage === source);
  } catch (_err) {
    outgoing = [];
  }
  if (!outgoing.length) {
    return `
      <div class="runtime-edge-route-inventory empty">
        <strong>No outgoing route candidates</strong>
        <small>Add a default route before live execution, then add conditional candidates if needed.</small>
      </div>
    `;
  }
  const sorted = outgoing.slice().sort((a, b) => Number(b.isDefault) - Number(a.isDefault) || String(a.targetStage).localeCompare(String(b.targetStage)));
  return `
    <div class="runtime-edge-route-inventory">
      <div class="runtime-edge-route-inventory-head">
        <strong>Outgoing routes from ${escapeHtml(source)}</strong>
        <small>${escapeHtml(sorted.length)} runtime candidate(s)</small>
      </div>
      ${sorted.map((edge) => {
        const selected = activeRuntimeEdge?.source === edge.sourceStage && activeRuntimeEdge?.target === edge.targetStage && (!activeRuntimeEdge.condition || activeRuntimeEdge.condition === edge.condition);
        return `
          <button type="button" class="runtime-edge-route-row ${edge.isDefault ? "default" : "candidate"}${selected ? " selected" : ""}" data-route-source="${escapeHtml(edge.sourceStage)}" data-route-target="${escapeHtml(edge.targetStage)}" data-route-condition="${escapeHtml(edge.condition || "")}">
            <span><strong>${escapeHtml(edge.sourceStage)} -> ${escapeHtml(edge.targetStage)}</strong><small>${escapeHtml(edgeTitle(edge))}</small></span>
            <em>${escapeHtml(edge.isDefault ? "default" : edgeDisplayLabel(edge))}</em>
          </button>
        `;
      }).join("")}
    </div>
  `;
}

function bindRouteInventoryActions() {
  edgeRoutePreview?.querySelectorAll?.("[data-route-source]").forEach((button) => {
    button.addEventListener("click", () => {
      const source = button.getAttribute("data-route-source") || "";
      const target = button.getAttribute("data-route-target") || "";
      const condition = button.getAttribute("data-route-condition") || "";
      if (transitionSource) transitionSource.value = source;
      if (transitionTarget) transitionTarget.value = target;
      setTransitionConditionControls(condition || "default", target);
      activeRuntimeEdge = { source, target, condition: condition || "default" };
      updateEdgeEditStatus();
      renderGraph(parseGraphEditor());
    });
  });
}

function renderEdgeRoutePreview(graph = null) {
  if (!edgeRoutePreview || !transitionSource || !transitionTarget) return;
  let parsedGraph = graph;
  if (!parsedGraph) {
    try {
      parsedGraph = parseGraphEditor();
    } catch (_err) {
      parsedGraph = activeGraph || {};
    }
  }
  const { source, target, condition, makeDefault } = transitionConditionSpec();
  if (!source || !target) {
    edgeRoutePreview.innerHTML = "Select source and target stages to preview route behavior.";
    return;
  }
  const transitions = parsedGraph?.transitions || {};
  const currentDefault = transitions[source] || "none";
  const effectiveMakeDefault = makeDefault || transitions[source] === target;
  const routeType = effectiveMakeDefault ? "default transition" : "candidate route";
  const sameRoute = edgeRecordsForRoute(parsedGraph, source, target);
  const sameCondition = sameRoute.filter((edge) => (logicalEdgeCondition(edge) || (edge.metadata?.default_transition ? "default" : "candidate")) === condition);
  const selectedCondition = String(activeRuntimeEdge?.condition || "").trim();
  const replaceNote = activeRuntimeEdge?.source === source && activeRuntimeEdge?.target === target && selectedCondition && selectedCondition !== condition
    ? `Will replace selected condition ${selectedCondition}.`
    : sameCondition.length
      ? "Will update the existing matching logical edge."
      : "Will create a new logical edge.";
  const transitionEffect = effectiveMakeDefault
    ? makeDefault
      ? `graph.transitions[${source}] becomes ${target}.`
      : `graph.transitions[${source}] already targets ${target}; this logical edge remains the default runtime route.`
    : `graph.transitions[${source}] remains ${currentDefault}; candidate is evaluated by GraphConfig.next_stage().`;
  const warnings = [];
  if (!effectiveMakeDefault && currentDefault === "none") warnings.push("No default route is configured for this source; consider setting a default first.");
  if (!effectiveMakeDefault && ["", "default", "continue", "always"].includes(condition)) warnings.push("Candidate route has a default-like condition; it may behave like a default.");
  edgeRoutePreview.innerHTML = `
    <div class="runtime-edge-route-preview-grid">
      <span><strong>${escapeHtml(routeType)}</strong><small>route type</small></span>
      <span><strong>${escapeHtml(source)} -> ${escapeHtml(target)}</strong><small>selected route</small></span>
      <span><strong>${escapeHtml(condition)}</strong><small>condition</small></span>
      <span><strong>${escapeHtml(currentDefault)}</strong><small>current source default</small></span>
    </div>
    <p>${escapeHtml(routeConditionExplanation(condition, target))}</p>
    <p>${escapeHtml(transitionEffect)}</p>
    <p>${escapeHtml(replaceNote)}</p>
    ${routeInventoryMarkup(parsedGraph, source)}
    ${routeDiffMarkup(activeDraftRouteDiff(parsedGraph))}
    ${configDiffMarkup(activeDraftConfigDiff(parsedGraph))}
    ${warnings.length ? `<ul>${warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
  `;
  bindRouteInventoryActions();
}

function activeGraphTab() {
  return graphTabs.find((tab) => tab.id === activeGraphTabId) || graphTabs[0] || null;
}

function currentGraphTabKind() {
  return activeGraphTab()?.kind || activeGraph?.metadata?.ide_tab_kind || "main";
}

function runtimeIdeStateSnapshot() {
  const tab = activeGraphTab();
  const tabKind = tab?.kind || currentGraphTabKind();
  const currentModuleId = tabKind === "module" ? (tab?.moduleId || activeModuleId || activeGraph?.metadata?.module_id || "") : "";
  const tabDirtyState = (item) => {
    const routeDiff = graphRouteDiff(item?.baselineGraph || null, item?.graph || {});
    const configDiff = graphConfigDiff(item?.baselineGraph || null, item?.graph || {});
    return Boolean(item?.dirty || routeDiff.changed || configDiff.changed);
  };
  const activeTabDirty = tabDirtyState(tab);
  return {
    activeGraphTabId,
    activeGraphTabKind: tabKind,
    activeGraphId: activeGraph?.id || "",
    activeModuleId: currentModuleId,
    activeTabDirty,
    selectedNodeId,
    edgeConnectSource,
    graphTabCount: graphTabs.length,
    graphTabs: graphTabs.map((item) => ({
      id: item.id,
      kind: item.kind || "main",
      title: item.title || item.id,
      moduleId: item.moduleId || "",
      dirty: tabDirtyState(item),
      active: item.id === activeGraphTabId,
    })),
    nodeCount: Array.isArray(activeGraph?.nodes) ? activeGraph.nodes.length : 0,
    logicalRouteCount: logicalGraphEdges(activeGraph || {}).length,
  };
}

function syncRuntimeIdeState() {
  const snapshot = runtimeIdeStateSnapshot();
  window.atrRuntimeIdeState = snapshot;
  window.activeGraphTabId = activeGraphTabId;
  window.graphTabs = snapshot.graphTabs;
  window.activeGraph = cloneConfig(activeGraph);
  if (graphTabsOutput) {
    graphTabsOutput.dataset.activeGraphTab = snapshot.activeGraphTabId || "";
    graphTabsOutput.dataset.activeGraphKind = snapshot.activeGraphTabKind || "";
    graphTabsOutput.dataset.activeModuleId = snapshot.activeModuleId || "";
  }
  return snapshot;
}

function rememberActiveGraphDraft() {
  const tab = activeGraphTab();
  if (!tab || !graphJson.value.trim()) return;
  try {
    tab.graph = parseGraphEditor();
  } catch (_error) {
    // Keep the last valid tab graph while the editor contains invalid JSON.
  }
}

function upsertGraphTab(tab) {
  const existing = graphTabs.findIndex((item) => item.id === tab.id);
  if (existing >= 0) graphTabs[existing] = { ...graphTabs[existing], ...tab };
  else graphTabs.push(tab);
}

function normalizeGraphTabId(tabId = "") {
  const clean = String(tabId || "").trim();
  if (!clean || clean === "main" || clean === MAIN_GRAPH_TAB_ID) return MAIN_GRAPH_TAB_ID;
  if (graphTabs.some((tab) => tab.id === clean)) return clean;
  const moduleCandidate = clean.startsWith(MODULE_TAB_PREFIX) ? clean : `${MODULE_TAB_PREFIX}${clean}`;
  if (graphTabs.some((tab) => tab.id === moduleCandidate)) return moduleCandidate;
  const byModule = graphTabs.find((tab) => tab.moduleId === clean);
  return byModule?.id || clean;
}

function renderGraphTabs() {
  if (!graphTabsOutput) return;
  if (!graphTabs.length && activeGraph) {
    graphTabs = [{ id: MAIN_GRAPH_TAB_ID, kind: "main", title: "Main System", subtitle: activeGraph.id || "active graph", fixed: true, graph: activeGraph, baselineGraph: cloneConfig(activeGraph) }];
    activeGraphTabId = MAIN_GRAPH_TAB_ID;
  }
  graphTabsOutput.setAttribute("role", "tablist");
  graphTabsOutput.setAttribute("aria-label", "Open runtime graph tabs");
  graphTabsOutput.innerHTML = graphTabs
    .map((tab) => {
      const isActive = tab.id === activeGraphTabId;
      const active = isActive ? " active" : "";
      const diff = graphRouteDiff(tab.baselineGraph || null, tab.graph || {});
      const isDirty = Boolean(tab.dirty || diff.changed);
      const dirty = isDirty ? " dirty" : "";
      const routeState = diff.changed ? ` · routes ${diff.added.length}+/${diff.removed.length}-` : "";
      const tabState = isActive ? "ACTIVE" : isDirty ? "DRAFT" : "";
      const stateBadge = tabState ? `<em class="runtime-ide-tab-state ${isActive ? "active" : "dirty"}">${tabState}</em>` : "";
      const close = tab.fixed ? "" : `<span class="runtime-ide-tab-close" data-close-graph-tab="${escapeHtml(tab.id)}" aria-label="Close ${escapeHtml(tab.title || tab.id)} tab">x</span>`;
      return `
        <button type="button" role="tab" aria-selected="${isActive ? "true" : "false"}" aria-current="${isActive ? "page" : "false"}" tabindex="${isActive ? "0" : "-1"}" class="runtime-ide-tab${active}${dirty}" data-graph-tab="${escapeHtml(tab.id)}" data-tab-kind="${escapeHtml(tab.kind || "main")}" data-tab-active="${isActive ? "true" : "false"}">
          <strong>${escapeHtml(tab.title || tab.id)}</strong>
          <small>${escapeHtml(tab.subtitle || (tab.kind === "module" ? "agent internal map" : "runtime graph"))}${escapeHtml(routeState)}</small>
          ${stateBadge}
          ${close}
        </button>
      `;
    })
    .join("");
  syncRuntimeIdeState();
  graphTabsOutput.querySelectorAll("[data-graph-tab]").forEach((el) => {
    el.addEventListener("click", (event) => {
      if (event.target.closest("[data-close-graph-tab]")) return;
      activateGraphTab(el.getAttribute("data-graph-tab") || MAIN_GRAPH_TAB_ID);
    });
  });
  graphTabsOutput.querySelectorAll("[data-close-graph-tab]").forEach((el) => {
    el.addEventListener("click", (event) => {
      event.stopPropagation();
      closeGraphTab(el.getAttribute("data-close-graph-tab") || "");
    });
  });
}

function activateGraphTab(tabId) {
  rememberActiveGraphDraft();
  const targetTabId = normalizeGraphTabId(tabId);
  const tab = graphTabs.find((item) => item.id === targetTabId);
  if (!tab) return;
  activeGraphTabId = tab.id;
  selectedNodeId = "";
  activeRuntimeEdge = null;
  edgeConnectDraft = null;
  edgeConnectSource = "";
  if (tab.kind === "module" && tab.moduleId) {
    activeModuleId = tab.moduleId;
    if (moduleSelect) moduleSelect.value = tab.moduleId;
    const payload = tab.modulePayload || modulePayloadCache.get(tab.moduleId);
    if (payload) {
      const normalized = normalizedModulePayload(cloneConfig(payload));
      tab.modulePayload = normalized;
      modulePayloadCache.set(tab.moduleId, normalized);
      setModuleJson(normalized);
      updateModuleSummary((normalized.module ? normalized.module : normalized) || {});
      renderModuleGraph(normalized);
    }
  }
  renderGraph(tab.graph);
}

function closeGraphTab(tabId) {
  const targetTabId = normalizeGraphTabId(tabId);
  const tab = graphTabs.find((item) => item.id === targetTabId);
  if (!tab || tab.fixed) return;
  const index = graphTabs.findIndex((item) => item.id === targetTabId);
  graphTabs.splice(index, 1);
  if (activeGraphTabId === targetTabId) {
    activeGraphTabId = graphTabs[Math.max(0, index - 1)]?.id || MAIN_GRAPH_TAB_ID;
  }
  renderGraphTabs();
  const next = activeGraphTab();
  if (next?.graph) renderGraph(next.graph);
}

function markActiveTabDirty(graph = activeGraph) {
  const tab = activeGraphTab();
  if (!tab) return;
  tab.graph = graph;
  tab.dirty = true;
  const isModule = tab.kind === "module" || graph?.metadata?.ide_tab_kind === "module";
  const label = isModule ? "Module Draft Changed" : "Graph Draft Changed";
  const target = isModule ? (tab.moduleId || graph?.metadata?.module_id || "module") : (graph?.id || tab.graphId || "graph");
  if (isModule) markModulePreflightDirty(target, "module draft changed");
  setStatus("warn", label, `${target}: validate and dry-run before saving.`);
  markActivationDirty("draft changed");
  renderGraphTabs();
}

function normalizedModulePayload(payload) {
  return payload?.module ? payload : { module: payload || {} };
}

function moduleGraphNodeId(phase, step, index) {
  const cleanId = String(step?.id || `step_${index + 1}`).replace(/[^A-Za-z0-9_.:-]/g, "_");
  return `${phase}:${cleanId}:${index}`;
}

function modulePayloadToGraph(modulePayload) {
  const payload = normalizedModulePayload(modulePayload);
  const module = payload.module || {};
  const preSteps = Array.isArray(module.pre_execution) ? module.pre_execution : [];
  const internalSteps = Array.isArray(module.internal_graph) ? module.internal_graph : [];
  const records = [
    ...preSteps.map((step, index) => ({ phase: "pre_execution", step, index, phaseIndex: index })),
    ...internalSteps.map((step, index) => ({ phase: "internal_graph", step, index: preSteps.length + index, phaseIndex: index })),
  ];
  const nodes = records.map((record) => {
    const fallback = defaultModuleNodePosition(record);
    const pos = record.step?.metadata?.position || fallback;
    return {
      id: moduleGraphNodeId(record.phase, record.step, record.phaseIndex),
      label: record.step?.label || record.step?.id || `${record.phase} ${record.phaseIndex + 1}`,
      handler: record.step?.handler || module.handler || "module.step",
      stage: moduleGraphNodeId(record.phase, record.step, record.phaseIndex),
      kind: record.phase === "pre_execution" ? "pre_stage" : "internal_step",
      description: record.step?.kind || "",
      module_id: `modules/${module.id || activeModuleId || "module"}`,
      position: { x: snapToGrid(pos.x ?? fallback.x), y: snapToGrid(pos.y ?? fallback.y) },
      metadata: {
        ...(record.step?.metadata || {}),
        icon: record.phase === "pre_execution" ? "orchestrator" : "artifact",
        module_step_phase: record.phase,
        module_step_index: record.phaseIndex,
        module_step_id: record.step?.id || "",
      },
    };
  });
  const transitions = {};
  for (let index = 0; index < nodes.length - 1; index += 1) {
    transitions[nodes[index].stage] = nodes[index + 1].stage;
  }
  const edges = Object.entries(transitions).map(([sourceStage, targetStage]) => {
    const source = nodes.find((node) => node.stage === sourceStage);
    const target = nodes.find((node) => node.stage === targetStage);
    const ports = inferPortPair(source, target);
    return {
      source: source?.id || sourceStage,
      target: target?.id || targetStage,
      condition: null,
      label: `${source?.label || sourceStage} -> ${target?.label || targetStage}`,
      metadata: { runtime_edge: "logical_transition", from_stage: sourceStage, to_stage: targetStage, source_port: ports.sourceSide, target_port: ports.targetSide },
    };
  });
  const finishNode = nodes[nodes.length - 1] || null;
  return {
    id: `${MODULE_TAB_PREFIX}${module.id || activeModuleId || "module"}`,
    name: `${module.label || module.id || "Module"} Internal Graph`,
    version: "draft",
    entry_node: nodes[0]?.id || "module_empty",
    finish_nodes: finishNode ? [finishNode.id] : [],
    nodes,
    edges,
    stage_dispatch: Object.fromEntries(nodes.map((node) => [node.stage, node.id])),
    transitions,
    terminal_stages: finishNode ? [finishNode.stage] : [],
    metadata: { ide_tab_kind: "module", module_id: module.id || activeModuleId || "", module_label: module.label || "" },
  };
}

function orderModuleNodesForPhase(graph, phase) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes.filter((node) => node.metadata?.module_step_phase === phase) : [];
  if (!nodes.length) return [];
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const outgoing = new Map();
  const incoming = new Set();
  for (const [sourceStage, targetStage] of Object.entries(graph.transitions || {})) {
    const source = nodes.find((node) => node.stage === sourceStage || node.id === sourceStage);
    const target = nodes.find((node) => node.stage === targetStage || node.id === targetStage);
    if (!source || !target) continue;
    outgoing.set(source.id, target.id);
    incoming.add(target.id);
  }
  const byPosition = [...nodes].sort((a, b) => Number(a.position?.y || 0) - Number(b.position?.y || 0) || Number(a.position?.x || 0) - Number(b.position?.x || 0));
  const starts = byPosition.filter((node) => !incoming.has(node.id));
  const ordered = [];
  const seen = new Set();
  for (const start of starts.length ? starts : byPosition) {
    let current = start;
    while (current && !seen.has(current.id)) {
      ordered.push(current);
      seen.add(current.id);
      current = nodeById.get(outgoing.get(current.id));
    }
  }
  for (const node of byPosition) {
    if (!seen.has(node.id)) ordered.push(node);
  }
  return ordered;
}

function refreshOpenModuleGraphTab(moduleId = activeModuleId, options = {}) {
  const tab = graphTabs.find((item) => item.id === `${MODULE_TAB_PREFIX}${moduleId}`);
  if (!tab) return;
  let payload = modulePayloadCache.get(moduleId) || tab.modulePayload || parseModuleEditor();
  payload = normalizedModulePayload(cloneConfig(payload));
  if ((payload.module?.id || "") !== moduleId) payload = modulePayloadForGraphDraft(tab.graph || activeGraph);
  const graph = modulePayloadToGraph(payload);
  tab.modulePayload = cloneConfig(payload);
  if (options.dirty === false) tab.baselineModulePayload = cloneConfig(payload);
  tab.graph = graph;
  tab.dirty = options.dirty !== false;
  if (options.renderIfActive !== false && activeGraphTabId === tab.id) renderGraph(graph);
  else renderGraphTabs();
}

function modulePayloadForGraphDraft(graph = activeGraph) {
  const moduleId = graph?.metadata?.module_id || activeGraphTab()?.moduleId || activeModuleId;
  const tab = activeGraphTab();
  const tabPayload = tab?.kind === "module" && tab.moduleId === moduleId ? tab.modulePayload : null;
  const cachedPayload = modulePayloadCache.get(moduleId);
  let editorPayload = null;
  try {
    const parsed = normalizedModulePayload(parseModuleEditor());
    if ((parsed.module?.id || "") === moduleId) editorPayload = parsed;
  } catch (_error) {
    editorPayload = null;
  }
  const source = tabPayload || cachedPayload || editorPayload || { module: { id: moduleId } };
  return normalizedModulePayload(cloneConfig(source));
}

function persistModuleTabPayload(moduleId, payload, graph = activeGraph) {
  const normalized = normalizedModulePayload(payload);
  activeModuleId = moduleId;
  if (moduleSelect) moduleSelect.value = moduleId;
  modulePayloadCache.set(moduleId, normalized);
  const tab = graphTabs.find((item) => item.id === `${MODULE_TAB_PREFIX}${moduleId}`);
  if (tab) {
    tab.modulePayload = cloneConfig(normalized);
    if (graph?.metadata?.ide_tab_kind === "module") tab.graph = graph;
  }
  setModuleJson(normalized);
  updateModuleSummary(normalized.module || {});
  renderModuleGraph(normalized);
}

function applyModuleGraphDraftToEditor(graph = activeGraph) {
  if (!graph || graph.metadata?.ide_tab_kind !== "module") return;
  const moduleId = graph.metadata?.module_id || activeModuleId;
  const payload = modulePayloadForGraphDraft(graph);
  const module = payload.module || {};
  module.id = module.id || moduleId;
  module.pre_execution = Array.isArray(module.pre_execution) ? module.pre_execution : [];
  module.internal_graph = Array.isArray(module.internal_graph) ? module.internal_graph : [];
  const phaseSteps = { pre_execution: module.pre_execution, internal_graph: module.internal_graph };
  for (const node of Array.isArray(graph.nodes) ? graph.nodes : []) {
    const phase = node.metadata?.module_step_phase;
    const index = Number(node.metadata?.module_step_index);
    const steps = phaseSteps[phase];
    if (!steps || index < 0 || index >= steps.length) continue;
    steps[index].metadata = { ...(steps[index].metadata || {}), position: { x: Number(node.position?.x || 0), y: Number(node.position?.y || 0) } };
  }
  for (const phase of ["pre_execution", "internal_graph"]) {
    const orderedNodes = orderModuleNodesForPhase(graph, phase);
    if (!orderedNodes.length) continue;
    const sourceSteps = [...phaseSteps[phase]];
    const reordered = [];
    for (const node of orderedNodes) {
      const index = Number(node.metadata?.module_step_index);
      if (index >= 0 && index < sourceSteps.length && sourceSteps[index]) reordered.push(sourceSteps[index]);
    }
    for (const step of sourceSteps) {
      if (!reordered.includes(step)) reordered.push(step);
    }
    phaseSteps[phase].splice(0, phaseSteps[phase].length, ...reordered);
  }
  persistModuleTabPayload(moduleId, payload, graph);
}

async function openModuleGraphTab(moduleId) {
  if (!moduleId) return;
  rememberActiveGraphDraft();
  let payload = modulePayloadCache.get(moduleId);
  if (!payload) {
    const result = await requestJson(`/api/modules/${moduleId}`);
    payload = result.module;
    modulePayloadCache.set(moduleId, payload);
  }
  const normalized = normalizedModulePayload(payload);
  const module = normalized.module || {};
  activeModuleId = moduleId;
  if (moduleSelect) moduleSelect.value = moduleId;
  setModuleJson(normalized);
  updateModuleSummary(module);
  renderModuleGraph(normalized);
  const graph = modulePayloadToGraph(normalized);
  upsertGraphTab({
    id: `${MODULE_TAB_PREFIX}${moduleId}`,
    kind: "module",
    title: module.label || moduleId,
    subtitle: "agent internal map",
    moduleId,
    modulePayload: cloneConfig(normalized),
    baselineModulePayload: cloneConfig(normalized),
    graph,
    baselineGraph: cloneConfig(graph),
    fixed: false,
    dirty: false,
  });
  activeGraphTabId = `${MODULE_TAB_PREFIX}${moduleId}`;
  renderGraph(graph);
  log(`Opened ${moduleId} internal graph tab. Save Module Version to activate changes.`, "ok");
}

function focusModuleForNode(nodeId) {
  const node = findNodeById(nodeId);
  if (!node?.module_id) return;
  const moduleId = String(node.module_id).split("/").pop();
  if (!moduleId) return;
  const hasModuleOption = moduleSelect ? Array.from(moduleSelect.options).some((option) => option.value === moduleId) : false;
  if (hasModuleOption) moduleSelect.value = moduleId;
  openModuleGraphTab(moduleId).catch((err) => log(String(err), "error"));
}

function populateTransitionEditor(graph) {
  const stages = graphStages(graph);
  const options = stages.map((stage) => `<option value="${escapeHtml(stage)}">${escapeHtml(stage)}</option>`).join("");
  transitionSource.innerHTML = options;
  transitionTarget.innerHTML = options;
  if (activeRuntimeEdge?.source) {
    transitionSource.value = activeRuntimeEdge.source;
    transitionTarget.value = activeRuntimeEdge.target || graph.transitions?.[activeRuntimeEdge.source] || transitionTarget.value;
    setTransitionConditionControls(activeRuntimeEdge.condition || "default", transitionTarget.value);
    updateTransitionConditionPlaceholder();
    renderEdgeRoutePreview(graph);
    return;
  }
  const selected = findNodeById(selectedNodeId);
  if (selected?.stage) {
    transitionSource.value = selected.stage;
    transitionTarget.value = graph.transitions?.[selected.stage] || transitionTarget.value;
  } else {
    const source = transitionSource.value || stages[0] || "";
    transitionSource.value = source;
    transitionTarget.value = graph.transitions?.[source] || transitionTarget.value;
  }
  setTransitionConditionControls("default", transitionTarget.value);
  updateTransitionConditionPlaceholder();
  renderEdgeRoutePreview(graph);
}

function handleTransitionSourceChange() {
  let graph = activeGraph;
  try {
    graph = parseGraphEditor();
  } catch (_err) {
    graph = activeGraph || {};
  }
  const source = transitionSource?.value || "";
  if (source && transitionTarget && graph?.transitions?.[source]) {
    transitionTarget.value = graph.transitions[source];
  }
  setTransitionConditionControls("default", transitionTarget?.value || "");
  updateTransitionConditionPlaceholder();
}

function renderGraph(graph) {
  activeGraph = normalizeNodePositions(graph);
  const tab = activeGraphTab();
  if (tab) tab.graph = activeGraph;
  graphIdBadge.textContent = activeGraph.metadata?.ide_tab_kind === "module"
    ? `${activeGraph.metadata?.module_id || "module"} internal`
    : activeGraph.id || "graph";
  setGraphJson(activeGraph);
  renderGraphTabs();
  const nodes = Array.isArray(activeGraph.nodes) ? activeGraph.nodes : [];
  const selectedNodeExists = nodes.some((node) => node.id === selectedNodeId);
  if ((!selectedNodeId || !selectedNodeExists) && nodes.length) {
    selectedNodeId = nodes[0].id;
  }
  const transitions = activeGraph.transitions || {};
  const bounds = graphBounds(nodes);
  const edges = logicalGraphEdges(activeGraph);
  const moduleGraph = activeGraph.metadata?.ide_tab_kind === "module";
  const readiness = runtimeReadinessStatus(activeGraph);
  const nodeReadinessIssues = runtimeReadinessNodeIssueMap(readiness);
  const edgeMarkup = edges
    .map((edge, index) => {
      const activeClass = activeRuntimeEdge?.source === edge.sourceStage && activeRuntimeEdge?.target === edge.targetStage && (!activeRuntimeEdge.condition || activeRuntimeEdge.condition === edge.condition) ? " edge-active" : "";
      const defaultClass = edge.isDefault ? " edge-default" : " edge-candidate";
      const moduleClass = moduleGraph ? " edge-module-flow" : "";
      const path = edgePath(edge);
      const labelPoint = edgeLabelPoint(edge);
      const label = moduleGraph && edge.isDefault
        ? `${stageDisplayLabel(edge.sourceStage)} → ${stageDisplayLabel(edge.targetStage)}`
        : edgeDisplayLabel(edge);
      const simpleDefaultLabel = edge.isDefault && ["", "default", "continue", "always"].includes(String(edge.condition || "").trim());
      const showLabel = moduleGraph || !simpleDefaultLabel || Boolean(activeClass);
      const maxLabelChars = moduleGraph ? 42 : 28;
      const labelText = label.length > maxLabelChars ? `${label.slice(0, maxLabelChars - 1)}…` : label;
      const labelWidth = Math.max(moduleGraph ? 168 : 74, Math.min(moduleGraph ? 340 : 158, labelText.length * (moduleGraph ? 7.4 : 7.2) + 28));
      const labelHeight = moduleGraph ? 24 : 22;
      const edgeData = `data-edge-index="${index}" data-edge-source="${escapeHtml(edge.sourceStage)}" data-edge-target="${escapeHtml(edge.targetStage)}" data-edge-condition="${escapeHtml(edge.condition || "")}" data-edge-default="${edge.isDefault ? "true" : "false"}"`;
      return `
        <path class="runtime-ide-edge-hitbox" d="${path}" ${edgeData} />
        <path class="runtime-ide-edge${activeClass}${defaultClass}${moduleClass}${simpleDefaultLabel ? " edge-simple-default" : ""}" d="${path}" ${edgeData}>
          <title>${escapeHtml(edgeTitle(edge))}</title>
        </path>
        ${showLabel ? `<g class="runtime-ide-edge-label${activeClass}${defaultClass}${moduleGraph ? " edge-module-flow" : ""}" ${edgeData}>
          <title>${escapeHtml(edgeTitle(edge))}</title>
          <rect x="${labelPoint.x - labelWidth / 2}" y="${labelPoint.y - labelHeight / 2}" width="${labelWidth}" height="${labelHeight}" rx="9"></rect>
          <text x="${labelPoint.x}" y="${labelPoint.y + 4}">${escapeHtml(labelText)}</text>
        </g>` : ""}
      `;
    })
    .join("");
  const nodeMarkup = nodes
    .map((node) => {
      const stage = nodeStage(node);
      const next = transitions[stage] || transitions[node.stage] || "";
      const outgoing = edges.filter((edgeItem) => edgeItem.sourceStage === stage);
      const stateClass = stage === activeRuntimeStage ? " active" : visitedRuntimeStages.has(stage) ? " visited" : "";
      const selectedClass = node.id === selectedNodeId ? " selected" : "";
      const edgeActiveClass = activeRuntimeEdge?.source === stage ? " edge-active" : "";
      const connectSourceClass = edgeConnectSource === stage || edgeConnectDraft?.sourceNodeId === node.id ? " connect-source" : "";
      const readinessIssue = nodeReadinessIssues.get(node.id) || null;
      const readinessClass = readinessIssue ? ` readiness-${readinessIssue.level}` : " readiness-ok";
      const extraRouteCount = Math.max(0, outgoing.length - (next ? 1 : 0));
      const edge = next
        ? `${stageDisplayLabel(stage)} -> ${stageDisplayLabel(next)}${extraRouteCount > 0 ? ` · +${extraRouteCount}` : ""}`
        : outgoing.length
          ? `${outgoing.length} route candidate${outgoing.length > 1 ? "s" : ""}`
          : node.handler;
      const routeBadge = outgoing.length > 1 ? `<em class="runtime-ide-node-route-count" title="${escapeHtml(outgoing.length)} outgoing runtime routes">${escapeHtml(outgoing.length)} routes</em>` : "";
      const readinessBadge = readinessIssue ? `<em class="runtime-node-readiness-badge ${escapeHtml(readinessIssue.level)}" title="${escapeHtml(runtimeReadinessIssueTitle(readinessIssue))}">${escapeHtml(runtimeReadinessIssueLabel(readinessIssue))}</em>` : "";
      const icon = node.metadata?.icon || node.kind || "node";
      const x = Number(node.position?.x || 0);
      const y = Number(node.position?.y || 0);
      const ports = PORT_SIDES.map((side) => `<span class="runtime-ide-port runtime-ide-port-${side}" data-port-node="${escapeHtml(node.id)}" data-port-stage="${escapeHtml(stage)}" data-port-side="${side}" title="${escapeHtml(stage)} ${side} port"></span>`).join("");
      return `
        <button class="runtime-ide-node${stateClass}${selectedClass}${edgeActiveClass}${connectSourceClass}${readinessClass}" data-node-id="${escapeHtml(node.id)}" data-node-stage="${escapeHtml(stage)}" type="button" style="left:${x}px;top:${y}px;">
          ${ports}
          ${runtimeNodeIconMarkup(icon)}
          ${routeBadge}
          ${readinessBadge}
          <span class="runtime-ide-node-copy">
            <strong>${escapeHtml(node.label || node.id)}</strong>
            <small>${escapeHtml(edge)}</small>
          </span>
        </button>
      `;
    })
    .join("");
  graphCanvas.innerHTML = `
    <div class="runtime-ide-canvas-world" style="width:${bounds.width}px;height:${bounds.height}px;transform:scale(${graphZoom});">
      <svg class="runtime-ide-edge-layer" viewBox="0 0 ${bounds.width} ${bounds.height}" aria-hidden="true">
        <defs>
          <marker id="ide-arrow" markerWidth="14" markerHeight="12" refX="9.8" refY="5" orient="auto" markerUnits="userSpaceOnUse" overflow="visible">
            <path d="M0,0 L10,5 L0,10 L2.4,5 z" fill="context-stroke" stroke="none"></path>
          </marker>
          <marker id="ide-arrow-module" markerWidth="18" markerHeight="14" refX="13.4" refY="6" orient="auto" markerUnits="userSpaceOnUse" overflow="visible">
            <path d="M0,1 L13.6,6 L0,11 L3.2,6 z" fill="context-stroke" stroke="none"></path>
          </marker>
        </defs>
        ${edgeMarkup}
      </svg>
      ${nodeMarkup}
    </div>
  `;
  graphCanvas.style.minHeight = `${Math.max(460, Math.min(680, bounds.height * graphZoom + 96))}px`;
  updateCanvasViewHint(bounds);
  graphCanvas.querySelectorAll("[data-node-id]").forEach((el) => {
    const nodeId = el.getAttribute("data-node-id") || "";
    el.addEventListener("pointerdown", (event) => beginNodeDrag(event, nodeId));
    el.addEventListener("click", (event) => {
      if (suppressNextNodeClick) {
        suppressNextNodeClick = false;
        return;
      }
      if (event.detail > 1) return;
      clearTimeout(nodeClickTimer);
      nodeClickTimer = setTimeout(() => handleGraphNodeClick(nodeId), 190);
    });
    el.addEventListener("dblclick", (event) => {
      event.preventDefault();
      clearTimeout(nodeClickTimer);
      focusModuleForNode(nodeId);
    });
  });
  graphCanvas.querySelectorAll("[data-port-node]").forEach((el) => {
    el.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      event.stopPropagation();
      beginPortConnect(el.getAttribute("data-port-node") || "", el.getAttribute("data-port-side") || "right", event);
    });
  });
  graphCanvas.querySelectorAll("[data-edge-source]").forEach((el) => {
    el.addEventListener("click", () => {
      const source = el.getAttribute("data-edge-source") || "";
      const target = el.getAttribute("data-edge-target") || "";
      transitionSource.value = source;
      transitionTarget.value = target;
      const condition = el.getAttribute("data-edge-condition") || "";
      activeRuntimeEdge = { source, target, condition };
      updateEdgeEditStatus();
      renderGraph(parseGraphEditor());
      log(`Selected edge ${source} -> ${target}${condition ? ` (${condition})` : ""}`);
    });
  });
  populateTransitionEditor(activeGraph);
  renderNodeInspector();
  renderMiniMap(activeGraph, bounds);
  renderGraphExplorer(activeGraph);
  renderRuntimeHeader();
  renderActivationChecklist();
  renderRuntimeReadinessPanel();
  syncRuntimeIdeState();
}

function clientToWorldPoint(event) {
  const world = graphCanvas.querySelector(".runtime-ide-canvas-world");
  const canvasRect = graphCanvas.getBoundingClientRect();
  const worldRect = world?.getBoundingClientRect() || canvasRect;
  return {
    x: Math.max(0, (event.clientX - worldRect.left) / graphZoom),
    y: Math.max(0, (event.clientY - worldRect.top) / graphZoom),
    canvasX: event.clientX - canvasRect.left + graphCanvas.scrollLeft,
    canvasY: event.clientY - canvasRect.top + graphCanvas.scrollTop,
  };
}

function elementContainsPoint(element, event) {
  if (!element || !event) return false;
  const rect = element.getBoundingClientRect();
  return event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
}

function canvasNodeElementFromPoint(event) {
  const elements = typeof document.elementsFromPoint === "function"
    ? document.elementsFromPoint(event.clientX, event.clientY)
    : [document.elementFromPoint(event.clientX, event.clientY)].filter(Boolean);
  for (const element of elements) {
    const node = element?.closest?.("[data-node-id]");
    if (node && graphCanvas.contains(node)) return node;
  }
  const candidates = Array.from(graphCanvas.querySelectorAll("[data-node-id]"));
  return candidates.find((node) => elementContainsPoint(node, event)) || null;
}

function expandedNodeElementFromPoint(event, margin = 34) {
  const exact = canvasNodeElementFromPoint(event);
  if (exact) return exact;
  const candidates = Array.from(graphCanvas.querySelectorAll("[data-node-id]"));
  return candidates.find((node) => {
    const rect = node.getBoundingClientRect();
    return event.clientX >= rect.left - margin
      && event.clientX <= rect.right + margin
      && event.clientY >= rect.top - margin
      && event.clientY <= rect.bottom + margin;
  }) || null;
}

function canvasPortElementFromPoint(event) {
  const elements = typeof document.elementsFromPoint === "function"
    ? document.elementsFromPoint(event.clientX, event.clientY)
    : [document.elementFromPoint(event.clientX, event.clientY)].filter(Boolean);
  for (const element of elements) {
    const port = element?.closest?.("[data-port-node]");
    if (port && graphCanvas.contains(port)) return port;
  }
  const candidates = Array.from(graphCanvas.querySelectorAll("[data-port-node]"));
  return candidates.find((port) => elementContainsPoint(port, event)) || null;
}

function setTrashZoneVisible(visible, active = false) {
  if (!trashZone) return;
  trashZone.classList.toggle("visible", Boolean(visible));
  trashZone.classList.toggle("active", Boolean(active));
  trashZoneHover = Boolean(active);
}

function updateTrashZoneHover(event) {
  if (!trashZone?.classList.contains("visible")) return false;
  const active = elementContainsPoint(trashZone, event);
  setTrashZoneVisible(true, active);
  return active;
}

function ensureConnectionPreview() {
  let preview = graphCanvas.querySelector(".runtime-ide-connection-preview");
  if (preview) return preview;
  const edgeLayer = graphCanvas.querySelector(".runtime-ide-edge-layer");
  if (!edgeLayer) return null;
  preview = document.createElementNS("http://www.w3.org/2000/svg", "path");
  preview.setAttribute("class", "runtime-ide-connection-preview");
  edgeLayer.appendChild(preview);
  return preview;
}

function connectionDragPlan(target = null) {
  if (!edgeDrag) return { valid: false, label: "No active connection", detail: "Drag from a node port to begin.", sourceStage: "", targetStage: "", condition: "" };
  const graph = parseGraphEditor();
  const sourceNode = graph.nodes?.find((node) => node.id === edgeDrag.sourceNodeId);
  const sourceStage = sourceNode ? nodeStage(sourceNode) : edgeDrag.sourceStage || edgeConnectSource || edgeDrag.sourceNodeId;
  if (!target?.nodeId) {
    return { valid: false, label: "Choose target node", detail: `${sourceStage} ready; drop on another node or its port.`, sourceStage, targetStage: "", condition: "" };
  }
  const targetNode = graph.nodes?.find((node) => node.id === target.nodeId);
  const targetStage = targetNode ? nodeStage(targetNode) : target.nodeId;
  if (!targetNode || target.nodeId === edgeDrag.sourceNodeId || targetStage === sourceStage) {
    return { valid: false, label: "Invalid target", detail: "Self connections are ignored; choose a different stage.", sourceStage, targetStage, condition: "" };
  }
  const defaultTarget = graph.transitions?.[sourceStage] || "";
  const makeDefault = !defaultTarget || defaultTarget === targetStage;
  const condition = makeDefault ? "default" : `next_stage:${targetStage}`;
  const label = makeDefault ? "Create default route" : "Add candidate route";
  const detail = makeDefault
    ? `graph.transitions[${sourceStage}] -> ${targetStage}`
    : `default stays ${defaultTarget}; condition ${condition}`;
  return { valid: true, makeDefault, label, detail, sourceStage, targetStage, condition, defaultTarget };
}

function ensureConnectionTooltip() {
  let tooltip = graphCanvas.querySelector(".runtime-ide-connection-tooltip");
  if (tooltip) return tooltip;
  tooltip = document.createElement("div");
  tooltip.className = "runtime-ide-connection-tooltip";
  graphCanvas.appendChild(tooltip);
  return tooltip;
}

function updateConnectionTooltip(event, target = null) {
  if (!edgeDrag) return;
  const tooltip = ensureConnectionTooltip();
  const plan = connectionDragPlan(target);
  const point = clientToWorldPoint(event);
  tooltip.className = `runtime-ide-connection-tooltip ${plan.valid ? "valid" : "invalid"} ${plan.makeDefault ? "default" : "candidate"}`;
  tooltip.style.left = `${Math.max(10, point.canvasX + 16)}px`;
  tooltip.style.top = `${Math.max(10, point.canvasY + 16)}px`;
  tooltip.innerHTML = `
    <strong>${escapeHtml(plan.label)}</strong>
    <span>${escapeHtml(plan.targetStage ? `${plan.sourceStage} -> ${plan.targetStage}` : plan.sourceStage || "source")}</span>
    <small>${escapeHtml(plan.detail)}</small>
  `;
}

function updateConnectionPreview(event, target = null) {
  if (!edgeDrag) return;
  const preview = ensureConnectionPreview();
  if (!preview) return;
  const point = clientToWorldPoint(event);
  const sourceNode = findNodeById(edgeDrag.sourceNodeId);
  const sourcePoint = sourceNode ? portPoint(sourceNode, edgeDrag.sourceSide) : edgeDrag.startPoint;
  const bend = Math.max(44, Math.min(180, Math.abs(point.x - sourcePoint.x) / 2));
  preview.setAttribute("d", `M ${sourcePoint.x} ${sourcePoint.y} C ${sourcePoint.x + bend} ${sourcePoint.y}, ${point.x - bend} ${point.y}, ${point.x} ${point.y}`);
  updateConnectionTooltip(event, target);
}

function clearEdgeDragTarget() {
  graphCanvas.querySelectorAll(".runtime-ide-node.connect-target").forEach((node) => node.classList.remove("connect-target"));
  edgeDragHoverNodeId = "";
}

function highlightEdgeDragTarget(nodeId = "") {
  const cleanNodeId = String(nodeId || "");
  if (cleanNodeId === edgeDragHoverNodeId) return;
  clearEdgeDragTarget();
  if (!cleanNodeId || cleanNodeId === edgeDrag?.sourceNodeId) return;
  graphCanvas.querySelector(`[data-node-id="${CSS.escape(cleanNodeId)}"]`)?.classList.add("connect-target");
  edgeDragHoverNodeId = cleanNodeId;
}

function clearConnectionPreview() {
  graphCanvas.querySelector(".runtime-ide-connection-preview")?.remove();
  graphCanvas.querySelector(".runtime-ide-connection-tooltip")?.remove();
  clearEdgeDragTarget();
}

function cancelPortConnection(message = "Connection cancelled. Drag from a port and drop on a target node.") {
  edgeDrag = null;
  edgeConnectDraft = null;
  edgeConnectSource = "";
  edgeConnectMode = false;
  edgeConnectBtn?.classList.remove("active");
  clearConnectionPreview();
  updateEdgeEditStatus(message);
  renderGraph(parseGraphEditor());
}

function beginPortConnect(nodeId, side = "right", event = null) {
  const graph = parseGraphEditor();
  normalizeNodePositions(graph);
  const node = graph.nodes.find((item) => item.id === nodeId);
  if (!node) return;
  const cleanSide = PORT_SIDES.includes(side) ? side : "right";
  const stage = nodeStage(node);
  edgeConnectMode = true;
  edgeConnectSource = stage;
  edgeConnectDraft = { sourceNodeId: node.id, sourceStage: stage, sourceSide: cleanSide };
  selectedNodeId = node.id;
  edgeConnectBtn?.classList.add("active");
  updateEdgeEditStatus(`Drag from ${stage}:${cleanSide} and drop on another node.`);
  if (!event) {
    renderGraph(graph);
    return;
  }
  edgeDrag = { ...edgeConnectDraft, startPoint: portPoint(node, cleanSide), moved: false };
  graphCanvas.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`)?.classList.add("connect-source");
  updateConnectionPreview(event, null);
  window.addEventListener("pointermove", dragPortConnection);
  window.addEventListener("pointerup", endPortConnection, { once: true });
}

function dragPortConnection(event) {
  if (!edgeDrag) return;
  edgeDrag.moved = true;
  const target = dropTargetFromEvent(event);
  const plan = connectionDragPlan(target);
  updateConnectionPreview(event, target);
  highlightEdgeDragTarget(plan.valid ? target.nodeId : "");
  if (edgeEditStatus) {
    edgeEditStatus.textContent = plan.valid
      ? `${plan.label}: ${plan.sourceStage} -> ${plan.targetStage} · ${plan.condition}`
      : plan.detail;
  }
}

function dropTargetFromEvent(event) {
  const port = canvasPortElementFromPoint(event);
  if (port) {
    return {
      nodeId: port.getAttribute("data-port-node") || "",
      side: port.getAttribute("data-port-side") || "left",
    };
  }
  const node = expandedNodeElementFromPoint(event);
  if (node) {
    const targetNodeId = node.getAttribute("data-node-id") || "";
    const graph = parseGraphEditor();
    const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    const sourceNode = nodes.find((item) => item.id === edgeDrag?.sourceNodeId);
    const targetNode = nodes.find((item) => item.id === targetNodeId);
    const inferred = sourceNode && targetNode ? inferPortPair(sourceNode, targetNode) : { targetSide: "left" };
    return { nodeId: targetNodeId, side: inferred.targetSide || "left" };
  }
  return null;
}

function endPortConnection(event) {
  window.removeEventListener("pointermove", dragPortConnection);
  const target = dropTargetFromEvent(event);
  const sourceSide = edgeDrag?.sourceSide || "right";
  if (!edgeDrag || !target?.nodeId) {
    cancelPortConnection("Connection cancelled. Drag from a port and drop on a target node.");
    return;
  }
  clearConnectionPreview();
  edgeDrag = null;
  finishPortConnect(target.nodeId, target.side, { keepChaining: false, sourceSide });
}

function finishPortConnect(nodeId, side = "left", options = {}) {
  if (!edgeConnectDraft) {
    beginPortConnect(nodeId, side);
    return;
  }
  const graph = parseGraphEditor();
  normalizeNodePositions(graph);
  const targetNode = graph.nodes.find((item) => item.id === nodeId);
  const sourceNode = graph.nodes.find((item) => item.id === edgeConnectDraft.sourceNodeId);
  if (!sourceNode || !targetNode) return;
  if (sourceNode.id === targetNode.id) {
    cancelPortConnection("Self connection ignored. Drag to a different target node.");
    return;
  }
  const sourceStage = nodeStage(sourceNode);
  const targetStage = nodeStage(targetNode);
  graph.transitions = graph.transitions || {};
  const hadDefault = Boolean(graph.transitions[sourceStage]);
  const makeDefault = !hadDefault || graph.transitions[sourceStage] === targetStage;
  const condition = makeDefault ? "default" : `next_stage:${targetStage}`;
  const edge = syncLogicalTransitionEdge(graph, sourceStage, targetStage, {
    makeDefault,
    condition,
    sourcePort: options.sourceSide || edgeConnectDraft.sourceSide,
    targetPort: PORT_SIDES.includes(side) ? side : "left",
    autoPorts: true,
  });
  activeRuntimeEdge = edge || { source: sourceStage, target: targetStage, condition };
  selectedNodeId = targetNode.id;
  edgeConnectSource = options.keepChaining ? targetStage : "";
  edgeConnectDraft = options.keepChaining ? { sourceNodeId: targetNode.id, sourceStage: targetStage, sourceSide: "right" } : null;
  edgeConnectMode = Boolean(options.keepChaining);
  edgeConnectBtn?.classList.toggle("active", edgeConnectMode);
  setGraphJson(graph);
  if (graph.metadata?.ide_tab_kind === "module") {
    applyModuleGraphDraftToEditor(graph);
  }
  markActiveTabDirty(graph);
  const detail = makeDefault
    ? `Connected default ${sourceStage} -> ${targetStage}.`
    : `Added candidate ${sourceStage} -> ${targetStage}; default remains ${graph.transitions[sourceStage]}.`;
  updateEdgeEditStatus(detail);
  renderGraph(graph);
  log(`${detail} Validate before saving.`, "ok");
}

function beginNodeDrag(event, nodeId) {
  if (event.button !== 0 || event.target.closest("[data-port-node]")) return;
  const graph = parseGraphEditor();
  normalizeNodePositions(graph);
  const node = graph.nodes.find((item) => item.id === nodeId);
  if (!node) return;
  nodeDrag = {
    nodeId,
    startX: event.clientX,
    startY: event.clientY,
    originX: Number(node.position?.x || 0),
    originY: Number(node.position?.y || 0),
    moved: false,
  };
  setTrashZoneVisible(true, false);
  window.addEventListener("pointermove", dragNode);
  window.addEventListener("pointerup", endNodeDrag, { once: true });
}

function dragNode(event) {
  if (!nodeDrag) return;
  const graph = parseGraphEditor();
  normalizeNodePositions(graph);
  const node = graph.nodes.find((item) => item.id === nodeDrag.nodeId);
  if (!node) return;
  const dx = (event.clientX - nodeDrag.startX) / graphZoom;
  const dy = (event.clientY - nodeDrag.startY) / graphZoom;
  node.position = { x: snapToGrid(nodeDrag.originX + dx), y: snapToGrid(nodeDrag.originY + dy) };
  setGraphJson(graph);
  const el = graphCanvas.querySelector(`[data-node-id="${CSS.escape(nodeDrag.nodeId)}"]`);
  if (el) {
    el.style.left = `${node.position.x}px`;
    el.style.top = `${node.position.y}px`;
  }
  updateTrashZoneHover(event);
  nodeDrag.moved = true;
}

function endNodeDrag(event) {
  if (!nodeDrag) return;
  window.removeEventListener("pointermove", dragNode);
  const moved = nodeDrag.moved;
  const nodeId = nodeDrag.nodeId;
  const droppedOnTrash = moved && updateTrashZoneHover(event);
  nodeDrag = null;
  setTrashZoneVisible(false, false);
  if (droppedOnTrash) {
    suppressNextNodeClick = true;
    removeNodeById(nodeId);
    return;
  }
  if (moved) {
    suppressNextNodeClick = true;
    const graph = parseGraphEditor();
    if (graph.metadata?.ide_tab_kind === "module") {
      applyModuleGraphDraftToEditor(graph);
    }
    markActiveTabDirty(graph);
    renderGraph(graph);
    log(`Moved node ${nodeId} on ${GRAPH_GRID}px grid. Validate before saving.`, "ok");
  }
}

function canvasVisibleWorldRect() {
  if (!graphCanvas) return { x: 0, y: 0, width: 0, height: 0 };
  return {
    x: Number(graphCanvas.scrollLeft || 0),
    y: Number(graphCanvas.scrollTop || 0),
    width: Math.max(1, Number(graphCanvas.clientWidth || 1) / Math.max(0.1, graphZoom)),
    height: Math.max(1, Number(graphCanvas.clientHeight || 1) / Math.max(0.1, graphZoom)),
  };
}

function updateMiniMapViewport() {
  const world = minimapOutput?.querySelector?.(".runtime-ide-minimap-world");
  const viewport = minimapOutput?.querySelector?.(".runtime-ide-minimap-viewport");
  if (!world || !viewport) return;
  const scale = Number(world.dataset.scale || 1);
  const boundsWidth = Number(world.dataset.boundsWidth || 1);
  const boundsHeight = Number(world.dataset.boundsHeight || 1);
  const rect = canvasVisibleWorldRect();
  const left = Math.max(0, Math.min(boundsWidth, rect.x)) * scale;
  const top = Math.max(0, Math.min(boundsHeight, rect.y)) * scale;
  const width = Math.max(16, Math.min(boundsWidth, rect.width) * scale);
  const height = Math.max(16, Math.min(boundsHeight, rect.height) * scale);
  viewport.style.left = `${left}px`;
  viewport.style.top = `${top}px`;
  viewport.style.width = `${Math.min(width, Math.max(16, boundsWidth * scale - left))}px`;
  viewport.style.height = `${Math.min(height, Math.max(16, boundsHeight * scale - top))}px`;
}

function centerCanvasOnWorldPoint(worldX, worldY) {
  if (!graphCanvas) return;
  const targetLeft = Number(worldX || 0) - (Number(graphCanvas.clientWidth || 0) / Math.max(0.1, graphZoom)) / 2;
  const targetTop = Number(worldY || 0) - (Number(graphCanvas.clientHeight || 0) / Math.max(0.1, graphZoom)) / 2;
  graphCanvas.scrollLeft = Math.max(0, targetLeft);
  graphCanvas.scrollTop = Math.max(0, targetTop);
  updateMiniMapViewport();
}

function minimapWorldPointFromEvent(event) {
  const world = minimapOutput?.querySelector?.(".runtime-ide-minimap-world");
  if (!world) return null;
  const rect = world.getBoundingClientRect();
  const scale = Number(world.dataset.scale || 1);
  return {
    x: Math.max(0, Math.min(rect.width, event.clientX - rect.left)) / Math.max(0.001, scale),
    y: Math.max(0, Math.min(rect.height, event.clientY - rect.top)) / Math.max(0.001, scale),
  };
}

function panCanvasFromMiniMapEvent(event) {
  const point = minimapWorldPointFromEvent(event);
  if (!point) return;
  centerCanvasOnWorldPoint(point.x, point.y);
}

function beginMiniMapPan(event) {
  if (event.button !== 0 || event.target.closest("[data-minimap-node]")) return;
  event.preventDefault();
  panCanvasFromMiniMapEvent(event);
  const move = (moveEvent) => panCanvasFromMiniMapEvent(moveEvent);
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", () => window.removeEventListener("pointermove", move), { once: true });
}

function ensureMiniMapScrollBinding() {
  if (!graphCanvas || graphCanvas.dataset.minimapScrollBound === "1") return;
  graphCanvas.dataset.minimapScrollBound = "1";
  graphCanvas.addEventListener("scroll", updateMiniMapViewport, { passive: true });
}

function renderMiniMap(graph, bounds) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const viewportWidth = Math.max(240, (minimapOutput?.clientWidth || 300) - 18);
  const viewportHeight = Math.max(140, (minimapOutput?.clientHeight || 160) - 18);
  const scale = Math.min(1, viewportWidth / Math.max(bounds.width, 1), viewportHeight / Math.max(bounds.height, 1));
  minimapOutput.innerHTML = `
    <div class="runtime-ide-minimap-world" data-scale="${scale}" data-bounds-width="${escapeHtml(bounds.width)}" data-bounds-height="${escapeHtml(bounds.height)}" style="width:${Math.ceil(bounds.width * scale)}px;height:${Math.ceil(bounds.height * scale)}px;">
      <div class="runtime-ide-minimap-viewport" aria-hidden="true"></div>
      ${nodes
        .map((node) => {
          const x = Number(node.position?.x || 0) * scale;
          const y = Number(node.position?.y || 0) * scale;
          const activeClass = nodeStage(node) === activeRuntimeStage ? " active" : "";
          return `<button class="runtime-ide-minimap-node${activeClass}" data-minimap-node="${escapeHtml(node.id)}" style="left:${x}px;top:${y}px;width:${GRAPH_NODE_WIDTH * scale}px;height:${GRAPH_NODE_HEIGHT * scale}px" title="${escapeHtml(node.label || node.id)}"></button>`;
        })
        .join("")}
    </div>
  `;
  minimapOutput.querySelectorAll("[data-minimap-node]").forEach((el) => {
    el.addEventListener("click", () => selectNode(el.getAttribute("data-minimap-node") || ""));
  });
  minimapOutput.querySelector(".runtime-ide-minimap-world")?.addEventListener("pointerdown", beginMiniMapPan);
  ensureMiniMapScrollBinding();
  updateMiniMapViewport();
}

function handleGraphNodeClick(nodeId) {
  const graph = parseGraphEditor();
  normalizeNodePositions(graph);
  const node = graph.nodes.find((item) => item.id === nodeId);
  if (!node) return;
  const stage = node.stage || node.id;
  if (!edgeConnectMode) {
    selectNode(nodeId);
    return;
  }
  selectedNodeId = nodeId;
  if (!edgeConnectSource) {
    edgeConnectSource = stage;
    updateEdgeEditStatus();
    renderGraph(graph);
    log(`Edge source selected: ${stage}. Click target node.`, "ok");
    return;
  }
  if (edgeConnectSource === stage) {
    edgeConnectSource = "";
    updateEdgeEditStatus("Connect source cleared. Click source node.");
    renderGraph(graph);
    return;
  }
  graph.transitions = graph.transitions || {};
  const hadDefault = Boolean(graph.transitions[edgeConnectSource]);
  const makeDefault = !hadDefault || graph.transitions[edgeConnectSource] === stage;
  const condition = makeDefault ? "default" : `next_stage:${stage}`;
  activeRuntimeEdge = syncLogicalTransitionEdge(graph, edgeConnectSource, stage, { makeDefault, condition }) || { source: edgeConnectSource, target: stage, condition };
  edgeConnectMode = false;
  edgeConnectSource = "";
  setGraphJson(graph);
  if (graph.metadata?.ide_tab_kind === "module") {
    applyModuleGraphDraftToEditor(graph);
  }
  markActiveTabDirty(graph);
  updateEdgeEditStatus();
  renderGraph(graph);
  log(`Connected ${makeDefault ? "default" : "candidate"} edge ${activeRuntimeEdge.source} -> ${activeRuntimeEdge.target}. Validate before saving.`, "ok");
}

function toggleEdgeConnectMode() {
  edgeConnectMode = !edgeConnectMode;
  edgeConnectSource = "";
  edgeConnectDraft = null;
  edgeConnectBtn.classList.toggle("active", edgeConnectMode);
  updateEdgeEditStatus();
  renderGraph(parseGraphEditor());
}

function deleteSelectedEdge() {
  const graph = parseGraphEditor();
  const source = activeRuntimeEdge?.source || transitionSource.value;
  const target = activeRuntimeEdge?.target || transitionTarget.value || graph.transitions?.[source];
  const condition = activeRuntimeEdge?.condition || "default";
  if (!source || !target) {
    log("No transition edge selected for deletion.", "error");
    return;
  }
  graph.edges = Array.isArray(graph.edges) ? graph.edges : [];
  const wasDefault = graph.transitions?.[source] === target && ["", "default", "continue", "always"].includes(condition || "default");
  const before = graph.edges.length;
  graph.edges = graph.edges.filter((edge) => {
    if (edge.metadata?.runtime_edge !== "logical_transition") return true;
    const from = edge.metadata?.from_stage || edge.source;
    const to = edge.metadata?.to_stage || edge.target;
    const edgeCondition = logicalEdgeCondition(edge) || (edge.metadata?.default_transition ? "default" : "candidate");
    return !(from === source && to === target && edgeCondition === condition);
  });
  if (graph.transitions && wasDefault) {
    delete graph.transitions[source];
    const replacement = graph.edges.find((edge) => edge.metadata?.runtime_edge === "logical_transition" && (edge.metadata?.from_stage || edge.source) === source);
    if (replacement) {
      const replacementTarget = replacement.metadata?.to_stage || replacement.target;
      graph.transitions[source] = replacementTarget;
      replacement.condition = null;
      replacement.metadata.condition = "default";
      replacement.metadata.transition_condition = "default";
      replacement.metadata.default_transition = true;
    }
  }
  normalizeDefaultLogicalEdges(graph, source);
  activeRuntimeEdge = null;
  edgeConnectMode = false;
  edgeConnectSource = "";
  edgeConnectDraft = null;
  edgeConnectBtn.classList.remove("active");
  setGraphJson(graph);
  if (graph.metadata?.ide_tab_kind === "module") {
    applyModuleGraphDraftToEditor(graph);
  }
  markActiveTabDirty(graph);
  updateEdgeEditStatus();
  renderGraph(graph);
  const deleted = before !== graph.edges.length || wasDefault;
  log(`${deleted ? "Deleted" : "Cleared"} edge ${source} -> ${target}${condition ? ` (${condition})` : ""}. Validate before saving.`, "ok");
}

function nodeInspectorJson(value, fallback = "n/a", limit = 1800) {
  if (value === undefined || value === null || value === "") return fallback;
  try {
    const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    return text.length > limit ? `${text.slice(0, limit)}\n... truncated` : text;
  } catch (err) {
    return String(value).slice(0, limit);
  }
}

function runtimeEventMatchesNode(event, node) {
  const stage = nodeStage(node);
  const eventNode = String(event?.node_id || event?.payload?.node_id || event?.payload?.node || "");
  const eventStageValue = String(event?.state?.stage || event?.payload?.stage || event?.timestamp_stage || "");
  return eventNode === node.id || eventNode === stage || eventStageValue === node.id || eventStageValue === stage;
}

function nodeRuntimeEvents(node) {
  return recentRuntimeEvents.filter((event) => runtimeEventMatchesNode(event, node)).slice(0, 6);
}

function runtimeStatusForNode(node, lastEvent = null) {
  const stage = nodeStage(node);
  const eventType = String(lastEvent?.type || lastEvent?.event_type || "").toLowerCase();
  const eventStatus = String(lastEvent?.status || lastEvent?.payload?.status || "").toLowerCase();
  if (activeRuntimeStage && activeRuntimeStage === stage) return "running";
  if (eventType.includes("fail") || eventStatus.includes("fail") || eventStatus.includes("error")) return "failed";
  if (visitedRuntimeStages.has(stage)) return "done";
  if (stage && activeGraph?.transitions?.[stage]) return "idle";
  return "pending";
}

function nodeConfigValue(node, key, fallback = "inherit") {
  if (node?.[key] !== undefined && node?.[key] !== null && node?.[key] !== "") return node[key];
  if (node?.metadata?.[key] !== undefined && node?.metadata?.[key] !== null && node?.metadata?.[key] !== "") return node.metadata[key];
  return fallback;
}

function nodeModuleId(node) {
  const raw = String(node?.module_id || node?.module || "").trim();
  if (!raw) return "";
  return raw.split("/").filter(Boolean).pop() || raw;
}

function modulePayloadForNode(node) {
  const moduleId = nodeModuleId(node);
  if (!moduleId) return null;
  return modulePayloadCache.get(moduleId) || null;
}

function ensureModulePayloadForInspector(moduleId = "", nodeId = selectedNodeId) {
  const clean = String(moduleId || "").trim();
  if (!clean || modulePayloadCache.has(clean) || modulePayloadFetches.has(clean)) return;
  modulePayloadFetches.add(clean);
  requestJson(`/api/modules/${encodeURIComponent(clean)}`)
    .then((result) => {
      if (result?.module) modulePayloadCache.set(clean, result.module);
      const selected = findNodeById(selectedNodeId);
      if (selectedNodeId === nodeId || nodeModuleId(selected) === clean) renderNodeInspector();
    })
    .catch((err) => log(`Module payload load failed for ${clean}: ${err}`, "warn"))
    .finally(() => modulePayloadFetches.delete(clean));
}

function moduleConfigForNode(node) {
  const payload = modulePayloadForNode(node);
  if (payload?.module && typeof payload.module === "object") return payload.module;
  if (payload && typeof payload === "object") return payload;
  const moduleId = nodeModuleId(node);
  return availableModules.find((item) => item.id === moduleId) || null;
}

function moduleCatalogItem(moduleId) {
  return availableModules.find((item) => item.id === moduleId) || {};
}

function moduleConfigPath(node, module, catalog) {
  return catalog.path || module?.metadata?.module_config_path || (nodeModuleId(node) ? `graphs/modules/${nodeModuleId(node)}/module.yaml` : "n/a");
}

function firstPresentValue(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "";
}

function schemaIssueValues(event) {
  const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
  const candidates = [
    event?.schema_mismatch,
    event?.schema_errors,
    event?.validation_errors,
    event?.contract_violation,
    payload.schema_mismatch,
    payload.schema_errors,
    payload.validation_errors,
    payload.contract_violation,
    payload.schema_warning,
    payload.schema_warnings,
  ];
  return candidates.filter((item) => item !== undefined && item !== null && item !== false && item !== "");
}

function hasPayloadValue(value) {
  if (value === undefined || value === null || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

function nodeSchemaStatus(node, module, lastEvent, inputPayload, outputPayload) {
  const io = module?.io_contract && typeof module.io_contract === "object" ? module.io_contract : {};
  const issues = schemaIssueValues(lastEvent);
  const status = { kind: "ok", label: "contract declared", messages: [] };
  if (!module) {
    return { kind: "warn", label: "module not loaded", messages: ["Module config is not loaded yet; select/load the module to inspect its I/O contract."] };
  }
  if (!io.input && !io.output) {
    status.kind = "warn";
    status.label = "contract missing";
    status.messages.push("module.yaml does not declare io_contract.input/output.");
  }
  if (issues.length) {
    status.kind = "error";
    status.label = "schema mismatch";
    status.messages.push(...issues.map((item) => compactJson(item)));
  }
  const type = String(lastEvent?.type || lastEvent?.event_type || "").toLowerCase();
  if (lastEvent && io.output && (type.includes("completed") || type.includes("result")) && !hasPayloadValue(outputPayload)) {
    status.kind = status.kind === "error" ? "error" : "warn";
    status.label = status.kind === "error" ? status.label : "output missing";
    status.messages.push("A completion event exists but no output/result payload was captured.");
  }
  if (!lastEvent) {
    status.kind = status.kind === "error" ? "error" : "idle";
    status.label = status.kind === "error" ? status.label : "no runtime sample";
    status.messages.push("No node-scoped runtime event has been captured for schema comparison yet.");
  }
  if (!status.messages.length) {
    status.messages.push("No schema mismatch indicator was found in the latest node event.");
  }
  return status;
}

function nodeCodeMapping(node, module, lastEvent) {
  const moduleId = nodeModuleId(node);
  const catalog = moduleCatalogItem(moduleId);
  const metadata = module?.metadata && typeof module.metadata === "object" ? module.metadata : {};
  const prompt = module ? modulePrompt(module) : {};
  const moduleRuntime = lastEvent?.payload?.module_runtime || lastEvent?.state?.run_metadata?.module_runtime?.[nodeStage(node)] || {};
  const moduleHandler = module?.handler || catalog.handler || "";
  const graphHandler = node.handler || "";
  const effectiveHandler = moduleRuntime.effective_handler || moduleRuntime.handler || moduleHandler || graphHandler || "";
  return {
    moduleId,
    graphHandler: graphHandler || "n/a",
    graphHandlerSignature: handlerSignatureText(graphHandler),
    graphHandlerOrigin: handlerOriginText(graphHandler),
    graphHandlerStatus: handlerMetadataStatus(graphHandler),
    moduleHandler: moduleHandler || "n/a",
    moduleHandlerSignature: handlerSignatureText(moduleHandler),
    moduleHandlerOrigin: handlerOriginText(moduleHandler),
    moduleHandlerStatus: handlerMetadataStatus(moduleHandler),
    effectiveHandler: effectiveHandler || "n/a",
    effectiveHandlerSignature: handlerSignatureText(effectiveHandler),
    effectiveHandlerOrigin: handlerOriginText(effectiveHandler),
    effectiveHandlerStatus: handlerMetadataStatus(effectiveHandler),
    modulePath: moduleConfigPath(node, module, catalog),
    promptPath: prompt.path || metadata.prompt_path || "not configured",
    sourcePath: firstPresentValue(metadata.python_source_path, metadata.source_path, catalog.source_path, "not configured"),
    adapterPath: firstPresentValue(metadata.transformed_python_source_path, metadata.transformed_source_path, "not configured"),
    protocolContract: metadata.protocol_contract || module?.io_contract?.protocol || "AgentResult / OrchestratorState / AgentContext",
    pendingRegistration: Boolean(metadata.pending_handler_registration || catalog.pending_handler_registration),
  };
}

function nodeInspectorStatusMarkup(status) {
  return `
    <div class="runtime-schema-status ${escapeHtml(status.kind)}">
      <strong>${escapeHtml(status.label)}</strong>
      <ul>${status.messages.map((message) => `<li>${escapeHtml(message)}</li>`).join("")}</ul>
    </div>
  `;
}

function nodeRouteAudit(node, graph = activeGraph) {
  const stage = nodeStage(node);
  let routes = [];
  try {
    routes = logicalGraphEdges(graph || {});
  } catch (_err) {
    routes = [];
  }
  const outgoing = routes.filter((edge) => edge.sourceStage === stage);
  const incoming = routes.filter((edge) => edge.targetStage === stage);
  const defaultTarget = graph?.transitions?.[stage] || "";
  const candidateCount = outgoing.filter((edge) => !edge.isDefault).length;
  return { stage, outgoing, incoming, defaultTarget, candidateCount };
}

function nodeRouteAuditRowMarkup(edge, direction = "outgoing") {
  const isOutgoing = direction === "outgoing";
  const peer = isOutgoing ? edge.targetStage : edge.sourceStage;
  const condition = edge.condition || (edge.isDefault ? "default" : "candidate");
  const role = edge.isDefault ? "default" : "candidate";
  const caption = isOutgoing ? routeConditionExplanation(condition, edge.targetStage) : `Incoming route from ${edge.sourceStage}. Inspect the source stage before changing live routing.`;
  return `
    <div class="runtime-node-route-row ${escapeHtml(role)}">
      <div>
        <strong>${escapeHtml(isOutgoing ? `to ${peer}` : `from ${peer}`)}</strong>
        <small>${escapeHtml(edgeTitle(edge))}</small>
        <p>${escapeHtml(caption)}</p>
      </div>
      <div class="runtime-node-route-actions">
        <em>${escapeHtml(edge.isDefault ? "default" : edgeDisplayLabel(edge))}</em>
        <button type="button" class="btn tiny" data-inspector-route-edit="1" data-route-source="${escapeHtml(edge.sourceStage)}" data-route-target="${escapeHtml(edge.targetStage)}" data-route-condition="${escapeHtml(condition)}">Edit</button>
        <button type="button" class="btn tiny" data-inspector-route-dry-run="${escapeHtml(edge.sourceStage)}">Dry-run</button>
      </div>
    </div>
  `;
}

function nodeRouteAuditMarkup(node, graph = activeGraph) {
  const audit = nodeRouteAudit(node, graph);
  const outgoing = audit.outgoing.slice().sort((a, b) => Number(b.isDefault) - Number(a.isDefault) || String(a.targetStage).localeCompare(String(b.targetStage)));
  const incoming = audit.incoming.slice().sort((a, b) => Number(b.isDefault) - Number(a.isDefault) || String(a.sourceStage).localeCompare(String(b.sourceStage)));
  const dispatch = graph?.stage_dispatch?.[audit.stage] || node.id || "n/a";
  const routeState = outgoing.length ? "configured" : "missing outgoing";
  return `
    <section class="runtime-node-inspector-card wide runtime-node-route-audit">
      <h3>Runtime Routes</h3>
      <div class="runtime-node-route-summary">
        <span><strong>${escapeHtml(audit.stage || "n/a")}</strong><small>stage</small></span>
        <span><strong>${escapeHtml(dispatch)}</strong><small>dispatch node</small></span>
        <span><strong>${escapeHtml(audit.defaultTarget || "none")}</strong><small>default out</small></span>
        <span><strong>${escapeHtml(audit.candidateCount)}</strong><small>candidate out</small></span>
        <span><strong>${escapeHtml(incoming.length)}</strong><small>incoming</small></span>
        <span><strong>${escapeHtml(routeState)}</strong><small>route state</small></span>
      </div>
      <div class="runtime-node-route-columns">
        <div>
          <div class="runtime-node-route-column-head"><strong>Outgoing</strong><small>${escapeHtml(outgoing.length)} route(s)</small></div>
          ${outgoing.length ? outgoing.map((edge) => nodeRouteAuditRowMarkup(edge, "outgoing")).join("") : `<div class="runtime-node-route-empty">No outgoing route is configured. Add a default route before live execution.</div>`}
        </div>
        <div>
          <div class="runtime-node-route-column-head"><strong>Incoming</strong><small>${escapeHtml(incoming.length)} route(s)</small></div>
          ${incoming.length ? incoming.map((edge) => nodeRouteAuditRowMarkup(edge, "incoming")).join("") : `<div class="runtime-node-route-empty">No incoming route in the current graph draft.</div>`}
        </div>
      </div>
    </section>
  `;
}

function nodeLatestProblemEvent(events = []) {
  return events.find((event) => ["error", "warn"].includes(eventSeverity(event))) || null;
}

function nodeRecoveryStatus(node, events = [], runtimeStatus = "idle", schemaStatus = {}, codeMapping = {}) {
  const stage = nodeStage(node);
  const moduleId = nodeModuleId(node);
  const audit = nodeRouteAudit(node, activeGraph);
  const finishNodes = new Set([...(activeGraph?.finish_nodes || []), ...(activeGraph?.terminal_stages || [])]);
  const dispatchable = Boolean(stage && activeGraph?.stage_dispatch?.[stage]);
  const controlNode = node?.kind === "runtime" && !node?.stage;
  const terminal = finishNodes.has(stage) || ["complete", "error"].includes(stage) || controlNode;
  const traceSummary = moduleTraceSummary(moduleTraceEventsForStage(stage, moduleId, 80));
  const problemEvent = nodeLatestProblemEvent(events);
  const readinessIssues = runtimeReadinessNodeIssueMap(runtimeReadinessStatus(activeGraph)).get(node?.id || "")?.items || [];
  const issues = [];
  readinessIssues.forEach((item) => {
    issues.push({ severity: item.level || "warn", text: `Readiness ${item.title}: ${item.detail || "check graph/module config"}` });
  });
  if (runtimeStatus === "failed") issues.push({ severity: "error", text: `Latest runtime status is failed${problemEvent ? ` (${eventTypeName(problemEvent)})` : ""}.` });
  if (!controlNode && schemaStatus.kind === "error") issues.push({ severity: "error", text: `I/O contract mismatch: ${schemaStatus.messages?.[0] || schemaStatus.label || "schema mismatch"}` });
  if (!controlNode && schemaStatus.kind === "warn") issues.push({ severity: "warn", text: `I/O contract warning: ${schemaStatus.messages?.[0] || schemaStatus.label || "contract warning"}` });
  if (codeMapping.pendingRegistration) issues.push({ severity: "warn", text: "Module adapter is pending handler registration; live execution will not use arbitrary Python." });
  if (moduleId && !moduleConfigForNode(node)) issues.push({ severity: "warn", text: `Module config for ${moduleId} is not loaded in the inspector cache yet.` });
  if (dispatchable && !terminal && !audit.outgoing.length) issues.push({ severity: "error", text: "No outgoing runtime route is configured for this non-terminal stage." });
  if (traceSummary.failed) issues.push({ severity: "error", text: `${traceSummary.failed} module internal step event(s) failed.` });
  if (!events.length && dispatchable) issues.push({ severity: "idle", text: "No node-scoped runtime event has been captured yet; dry-run from this node to create evidence." });
  const severity = issues.some((item) => item.severity === "error")
    ? "error"
    : issues.some((item) => item.severity === "warn")
      ? "warn"
      : runtimeStatus === "done"
        ? "ok"
        : "idle";
  const recommendations = problemEvent
    ? eventRemediationActions(problemEvent, node, stage)
    : [
        readinessIssues.length ? "Fix the readiness issue shown on the graph node before live execution." : "Dry-run from this node to confirm the saved/draft route and effective handler.",
        "Validate Draft if graph/module config changed since the last evidence.",
        moduleId ? "Open Module Management Tool if handler, prompt, tools, retry, or safety settings need edits." : "Inspect graph config before adding module-specific recovery actions.",
      ];
  return { stage, moduleId, audit, traceSummary, problemEvent, issues, severity, recommendations: Array.from(new Set(recommendations)).slice(0, 5) };
}

function nodeRuntimeRecoveryMarkup(node, events = [], runtimeStatus = "idle", schemaStatus = {}, codeMapping = {}) {
  const status = nodeRecoveryStatus(node, events, runtimeStatus, schemaStatus, codeMapping);
  const problemEventId = status.problemEvent?.event_id || "";
  const dryRunDisabled = status.stage && activeGraph?.stage_dispatch?.[status.stage] ? "" : "disabled";
  const moduleDisabled = status.moduleId ? "" : "disabled";
  const eventDisabled = problemEventId ? "" : "disabled";
  const primary = status.severity === "error" ? "Inspect latest event and replay this stage before editing config." : status.severity === "warn" ? "Review warnings, then dry-run from this node." : "No blocking node issue detected from current runtime evidence.";
  return `
    <section class="runtime-node-inspector-card wide runtime-node-recovery ${escapeHtml(status.severity)}">
      <div class="runtime-node-recovery-head">
        <span>
          <h3>Runtime Recovery</h3>
          <small>${escapeHtml(primary)}</small>
        </span>
        <em>${escapeHtml(status.severity.toUpperCase())}</em>
      </div>
      <div class="runtime-node-recovery-grid">
        <span><small>Stage</small><strong>${escapeHtml(status.stage || "n/a")}</strong></span>
        <span><small>Problem Event</small><strong>${escapeHtml(status.problemEvent ? eventTypeName(status.problemEvent) : "none")}</strong></span>
        <span><small>Routes</small><strong>${escapeHtml(`${status.audit.outgoing.length} out / ${status.audit.incoming.length} in`)}</strong></span>
        <span><small>Module Trace</small><strong>${escapeHtml(`${status.traceSummary.failed} failed / ${status.traceSummary.total} events`)}</strong></span>
      </div>
      <div class="runtime-node-recovery-issues">
        ${(status.issues.length ? status.issues : [{ severity: "ok", text: "Current node evidence has no explicit failure, schema mismatch, or missing route." }]).map((issue) => `<p class="${escapeHtml(issue.severity)}">${escapeHtml(issue.text)}</p>`).join("")}
      </div>
      <div class="runtime-node-recovery-actions">
        <button type="button" class="btn tiny" data-node-recovery-action="inspect-event" data-node-recovery-event-id="${escapeHtml(problemEventId)}" ${eventDisabled}>Inspect latest issue</button>
        <button type="button" class="btn tiny primary" data-node-recovery-action="dry-run" data-node-recovery-stage="${escapeHtml(status.stage || "idle")}" ${dryRunDisabled}>Dry-run from node</button>
        <button type="button" class="btn tiny" data-node-recovery-action="validate">Validate Draft</button>
        <button type="button" class="btn tiny" data-node-recovery-action="module-management" ${moduleDisabled}>Open Module Management</button>
      </div>
      <div class="runtime-node-recovery-next">
        <small>Recommended next actions</small>
        ${status.recommendations.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
      </div>
    </section>
  `;
}

function bindNodeRecoveryActions() {
  nodeInspector.querySelectorAll("[data-node-recovery-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.getAttribute("data-node-recovery-action") || "";
      if (action === "dry-run") {
        const startStage = button.getAttribute("data-node-recovery-stage") || "idle";
        dryRunGraph(startStage, dryRunOutput).catch((err) => log(String(err), "error"));
      } else if (action === "validate") {
        validateGraph().catch((err) => log(String(err), "error"));
      } else if (action === "module-management") {
        openModuleManagementTool();
      } else if (action === "inspect-event") {
        const eventId = button.getAttribute("data-node-recovery-event-id") || "";
        const index = timelineIndexForEventId(eventId);
        if (index >= 0) inspectTimelineEvent(index).catch((err) => log(String(err), "error"));
        else log(`Runtime recovery event not found: ${eventId || "none"}`, "warn");
      }
    });
  });
}

function bindNodeRouteAuditActions() {
  nodeInspector.querySelectorAll("[data-inspector-route-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      const source = button.getAttribute("data-route-source") || "";
      const target = button.getAttribute("data-route-target") || "";
      const condition = button.getAttribute("data-route-condition") || "default";
      if (transitionSource) transitionSource.value = source;
      if (transitionTarget) transitionTarget.value = target;
      setTransitionConditionControls(condition || "default", target);
      activeRuntimeEdge = { source, target, condition: condition || "default" };
      updateEdgeEditStatus(`inspecting route ${source} -> ${target}`);
      renderGraph(parseGraphEditor());
      edgeRoutePreview?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    });
  });
  nodeInspector.querySelectorAll("[data-inspector-route-dry-run]").forEach((button) => {
    button.addEventListener("click", () => {
      const startStage = button.getAttribute("data-inspector-route-dry-run") || "idle";
      dryRunGraph(startStage, dryRunOutput).catch((err) => log(String(err), "error"));
    });
  });
}

function renderNodeInspector() {
  const node = findNodeById(selectedNodeId);
  selectedNodeBadge.textContent = node?.id || "none";
  if (!node) {
    nodeInspector.innerHTML = "<div>No node selected.</div>";
    return;
  }
  const stage = nodeStage(node);
  const next = node.stage ? activeGraph?.transitions?.[node.stage] : "";
  const events = nodeRuntimeEvents(node);
  const lastEvent = events[0] || null;
  const agentName = node.handler?.startsWith("agent.") ? node.handler.replace("agent.", "") : "";
  const snapshotAgentStatus = agentName ? latestStateSnapshot?.state?.agent_status?.[agentName] || {} : {};
  const eventAgentStatus = agentName ? lastEvent?.state?.agent_status?.[agentName] || {} : {};
  const agentStatus = { ...snapshotAgentStatus, ...eventAgentStatus };
  const runtimeStatus = runtimeStatusForNode(node, lastEvent);
  const moduleId = nodeModuleId(node);
  if (moduleId && !modulePayloadCache.has(moduleId)) ensureModulePayloadForInspector(moduleId, node.id);
  const module = moduleConfigForNode(node);
  const inputPayload = lastEvent?.input || lastEvent?.payload?.input || lastEvent?.payload?.request || lastEvent?.payload?.arguments || null;
  const outputPayload = lastEvent?.output || lastEvent?.payload?.output || lastEvent?.payload?.result || lastEvent?.payload?.data || lastEvent?.payload || null;
  const schemaStatus = nodeSchemaStatus(node, module, lastEvent, inputPayload, outputPayload);
  const codeMapping = nodeCodeMapping(node, module, lastEvent);
  const eventRows = events.length
    ? events
        .map((event) => {
          const type = event.type || event.event_type || "event";
          const ts = event.ts || event.timestamp || "";
          const status = event.status || event.payload?.status || "n/a";
          return `<div class="runtime-node-event-row"><strong>${escapeHtml(type)}</strong><span>${escapeHtml(status)}</span><small>${escapeHtml(ts)}</small></div>`;
        })
        .join("")
    : `<div class="runtime-node-event-row empty">No node-scoped runtime event yet.</div>`;
  const problemEventId = nodeLatestProblemEvent(events)?.event_id || "";
  const nodeDryRunDisabled = stage && activeGraph?.stage_dispatch?.[stage] ? "" : "disabled";
  const nodeModuleDisabled = moduleId ? "" : "disabled";
  const nodeEventDisabled = problemEventId ? "" : "disabled";
  nodeInspector.innerHTML = `
    <div class="runtime-node-inspector-grid">
      <section class="runtime-node-inspector-card wide runtime-node-quick-actions">
        <span>
          <h3>Node Quick Actions</h3>
          <small>common recovery and verification actions for the selected runtime node</small>
        </span>
        <div class="runtime-node-quick-action-row">
          <button type="button" class="btn tiny primary" data-node-recovery-action="dry-run" data-node-recovery-stage="${escapeHtml(stage || "idle")}" ${nodeDryRunDisabled}>Dry-run from node</button>
          <button type="button" class="btn tiny" data-node-recovery-action="validate">Validate Draft</button>
          <button type="button" class="btn tiny" data-node-recovery-action="module-management" ${nodeModuleDisabled}>Open Module Management</button>
          <button type="button" class="btn tiny" data-node-recovery-action="inspect-event" data-node-recovery-event-id="${escapeHtml(problemEventId)}" ${nodeEventDisabled}>Inspect latest issue</button>
        </div>
      </section>
      <section class="runtime-node-inspector-card">
        <h3>Info</h3>
        <dl>
          <dt>Label</dt><dd>${escapeHtml(node.label || node.id)}</dd>
          <dt>ID</dt><dd>${escapeHtml(node.id)}</dd>
          <dt>Stage</dt><dd>${escapeHtml(node.stage || "n/a")}</dd>
          <dt>Kind</dt><dd>${escapeHtml(node.kind || "runtime")}</dd>
          <dt>Description</dt><dd>${escapeHtml(node.description || "No description in graph config.")}</dd>
        </dl>
      </section>
      <section class="runtime-node-inspector-card">
        <h3>Runtime</h3>
        <dl>
          <dt>Status</dt><dd><span class="runtime-node-status-pill ${escapeHtml(runtimeStatus)}">${escapeHtml(runtimeStatus)}</span></dd>
          <dt>Next</dt><dd>${escapeHtml(next || "n/a")}</dd>
          <dt>Agent state</dt><dd>${escapeHtml(agentStatus.state || lastEvent?.status || "n/a")}</dd>
          <dt>Success</dt><dd>${escapeHtml(agentStatus.success ?? "n/a")}</dd>
          <dt>Last run</dt><dd>${escapeHtml(agentStatus.last_run_time || "n/a")}</dd>
          <dt>Events</dt><dd>${escapeHtml(events.length)}</dd>
        </dl>
        <div class="runtime-node-event-list">${eventRows}</div>
      </section>
      ${nodeRuntimeRecoveryMarkup(node, events, runtimeStatus, schemaStatus, codeMapping)}
      <section class="runtime-node-inspector-card wide">
        <h3>Module Step Trace</h3>
        ${renderModuleTraceMarkup(stage, moduleId)}
        ${moduleTraceEventsForStage(stage, moduleId).length ? "" : `<div class="runtime-event-detail-empty">No module step events captured for this node yet.</div>`}
      </section>
      ${nodeRouteAuditMarkup(node, activeGraph)}
      <section class="runtime-node-inspector-card">
        <h3>Config</h3>
        <dl>
          <dt>Graph handler</dt><dd>${escapeHtml(node.handler || "n/a")}</dd>
          <dt>Module</dt><dd>${escapeHtml(moduleId || node.module_id || "n/a")}</dd>
          <dt>Effective handler</dt><dd>${escapeHtml(codeMapping.effectiveHandler)}</dd>
          <dt>Model</dt><dd>${escapeHtml(nodeConfigValue(node, "model"))}</dd>
          <dt>Timeout</dt><dd>${escapeHtml(nodeConfigValue(node, "timeout_s", "inherit"))}</dd>
          <dt>Retry</dt><dd>${escapeHtml(nodeConfigValue(node, "retry", "inherit"))}</dd>
          <dt>Safety</dt><dd>${escapeHtml(nodeConfigValue(node, "safety_class", "standard"))}</dd>
        </dl>
      </section>
      <section class="runtime-node-inspector-card wide">
        <h3>I/O Contract</h3>
        <dl>
          <dt>Expected input</dt><dd>${escapeHtml(module?.io_contract?.input || "not declared")}</dd>
          <dt>Expected output</dt><dd>${escapeHtml(module?.io_contract?.output || "not declared")}</dd>
        </dl>
        ${nodeInspectorStatusMarkup(schemaStatus)}
        <details open>
          <summary>Last input</summary>
          <pre>${escapeHtml(nodeInspectorJson(inputPayload, "No captured input payload yet."))}</pre>
        </details>
        <details open>
          <summary>Last output / event payload</summary>
          <pre>${escapeHtml(nodeInspectorJson(outputPayload, "No captured output payload yet."))}</pre>
        </details>
      </section>
      <section class="runtime-node-inspector-card wide">
        <h3>Code Mapping</h3>
        <dl>
          <dt>Graph handler</dt><dd>${escapeHtml(codeMapping.graphHandler)} ${handlerStatusPillMarkup(codeMapping.graphHandler)}</dd>
          <dt>Graph signature</dt><dd><code class="runtime-handler-signature">${escapeHtml(codeMapping.graphHandlerSignature)}</code></dd>
          <dt>Module handler</dt><dd>${escapeHtml(codeMapping.moduleHandler)} ${handlerStatusPillMarkup(codeMapping.moduleHandler)}</dd>
          <dt>Module signature</dt><dd><code class="runtime-handler-signature">${escapeHtml(codeMapping.moduleHandlerSignature)}</code></dd>
          <dt>Effective handler</dt><dd>${escapeHtml(codeMapping.effectiveHandler)} ${handlerStatusPillMarkup(codeMapping.effectiveHandler)}</dd>
          <dt>Effective origin</dt><dd>${escapeHtml(codeMapping.effectiveHandlerOrigin)}</dd>
          <dt>Effective signature</dt><dd><code class="runtime-handler-signature">${escapeHtml(codeMapping.effectiveHandlerSignature)}</code>${handlerErrorListMarkup(codeMapping.effectiveHandler)}</dd>
          <dt>Module config</dt><dd>${escapeHtml(codeMapping.modulePath)}</dd>
          <dt>Prompt path</dt><dd>${escapeHtml(codeMapping.promptPath)}</dd>
          <dt>Source file</dt><dd>${escapeHtml(codeMapping.sourcePath)}</dd>
          <dt>ATR adapter</dt><dd>${escapeHtml(codeMapping.adapterPath)}</dd>
          <dt>Protocol</dt><dd>${escapeHtml(codeMapping.protocolContract)}</dd>
          <dt>Registry state</dt><dd><span class="runtime-node-status-pill ${escapeHtml(codeMapping.pendingRegistration ? "warn" : "ok")}">${escapeHtml(codeMapping.pendingRegistration ? "pending registration" : "allowlisted/configured")}</span></dd>
        </dl>
        <button type="button" class="btn tiny" data-node-dry-run-stage="${escapeHtml(stage || "idle")}">Dry-run from this node</button>
      </section>
    </div>
  `;
  if (node.stage && !activeRuntimeEdge) {
    transitionSource.value = node.stage;
    transitionTarget.value = next || transitionTarget.value;
    setTransitionConditionControls("default", transitionTarget.value);
    updateTransitionConditionPlaceholder();
  }
  if (node.module_id) {
    const moduleId = String(node.module_id).split("/").pop();
    const hasModuleOption = Array.from(moduleSelect.options).some((option) => option.value === moduleId);
    if (moduleId && moduleId !== activeModuleId && hasModuleOption) {
      moduleSelect.value = moduleId;
      loadModule()
        .then(() => {
          if (selectedNodeId === node.id) renderNodeInspector();
        })
        .catch((err) => log(String(err), "error"));
    }
  }
  nodeInspector.querySelectorAll("[data-node-dry-run-stage]").forEach((button) => {
    button.addEventListener("click", () => {
      const startStage = button.getAttribute("data-node-dry-run-stage") || stage || "idle";
      dryRunGraph(startStage, dryRunOutput).catch((err) => log(String(err), "error"));
    });
  });
  bindNodeRecoveryActions();
  bindNodeRouteAuditActions();
}

function resolveGraphNodeRef(graph, ref = "") {
  const clean = String(ref || "").trim();
  if (!clean) return "";
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const matched = nodes.find((node) => node.id === clean || node.stage === clean || node.label === clean);
  return matched?.id || "";
}

function focusGraphNodeInCanvas(nodeId) {
  if (!nodeId) return;
  const el = graphCanvas?.querySelector?.(`[data-node-id="${CSS.escape(nodeId)}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
  el.classList.add("deep-link-focus");
  window.setTimeout(() => el.classList.remove("deep-link-focus"), 1800);
}

function selectNode(nodeId, options = {}) {
  selectedNodeId = nodeId;
  renderGraph(parseGraphEditor());
  if (options.focus !== false) requestAnimationFrame(() => focusGraphNodeInCanvas(nodeId));
}

function flashRuntimeElement(element, className = "runtime-readiness-focus") {
  if (!element) return;
  element.classList.remove(className);
  void element.offsetWidth;
  element.classList.add(className);
  window.setTimeout(() => element.classList.remove(className), 1800);
}

function focusNodeInspectorSurface() {
  nodeInspector?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  flashRuntimeElement(nodeInspector);
}

function transitionTargetOptionExists(target = "") {
  if (!transitionTarget || !target) return false;
  return Array.from(transitionTarget.options || []).some((option) => option.value === target);
}

function routeRepairTargetForStage(graph = activeGraph, stage = "") {
  const cleanStage = String(stage || "");
  if (!cleanStage) return "";
  const currentDefault = graph?.transitions?.[cleanStage] || "";
  if (currentDefault && transitionTargetOptionExists(currentDefault)) return currentDefault;
  const tab = activeGraphTab();
  const baseline = tab?.baselineGraph || tab?.activeGraph || null;
  const baselineDefault = baseline?.transitions?.[cleanStage] || "";
  if (baselineDefault && transitionTargetOptionExists(baselineDefault)) return baselineDefault;
  try {
    const defaultEdge = logicalGraphEdges(baseline || {}).find((edge) => edge.sourceStage === cleanStage && edge.isDefault);
    if (defaultEdge?.targetStage && transitionTargetOptionExists(defaultEdge.targetStage)) return defaultEdge.targetStage;
  } catch (_err) {
    // Baseline may be unavailable while graph data is loading; fall through to draft candidates.
  }
  try {
    const candidate = logicalGraphEdges(graph || {}).find((edge) => edge.sourceStage === cleanStage)?.targetStage || "";
    if (candidate && transitionTargetOptionExists(candidate)) return candidate;
  } catch (_err) {
    return "";
  }
  return "";
}

function focusTransitionEditorForNode(nodeId = "") {
  const graph = (() => { try { return parseGraphEditor(); } catch { return activeGraph || {}; } })();
  const node = resolveGraphNodeRef(graph, nodeId) ? (graph.nodes || []).find((item) => item.id === resolveGraphNodeRef(graph, nodeId)) : findNodeById(nodeId);
  const stage = nodeStage(node);
  const suggestedTarget = routeRepairTargetForStage(graph, stage);
  if (stage && transitionSource) transitionSource.value = stage;
  if (stage && transitionTarget && suggestedTarget) transitionTarget.value = suggestedTarget;
  setTransitionConditionControls("default", suggestedTarget || transitionTarget?.value || "");
  activeRuntimeEdge = stage ? { source: stage, target: suggestedTarget || transitionTarget?.value || "", condition: "default" } : activeRuntimeEdge;
  updateEdgeEditStatus(stage ? `fix route coverage for ${stage}${suggestedTarget ? ` -> ${suggestedTarget}` : ""}` : "fix route coverage");
  renderEdgeRoutePreview(graph);
  document.querySelector(".runtime-ide-transition-editor")?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  flashRuntimeElement(document.querySelector(".runtime-ide-transition-editor"));
}

function focusModuleManagementEntryForNode(nodeId = "") {
  const node = findNodeById(nodeId);
  const moduleId = normalizeModuleIdRef(node?.module_id || "");
  if (moduleId) {
    if (moduleSelect && Array.from(moduleSelect.options).some((option) => option.value === moduleId)) moduleSelect.value = moduleId;
    openModuleGraphTab(moduleId).catch((err) => log(String(err), "error"));
  }
  const target = moduleManagementOpenBtn || moduleManagementInlineBtn;
  target?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  flashRuntimeElement(target);
}

function focusRuntimeReadinessIssue(nodeId = "", kind = "") {
  if (!nodeId) return;
  selectNode(nodeId);
  window.setTimeout(() => {
    const normalizedKind = String(kind || "");
    if (normalizedKind === "route") {
      focusTransitionEditorForNode(nodeId);
      return;
    }
    if (["module", "module_handler", "pending_registration"].includes(normalizedKind)) {
      focusModuleManagementEntryForNode(nodeId);
      return;
    }
    focusNodeInspectorSurface();
  }, 120);
}

function parseGraphEditor() {
  return JSON.parse(graphJson.value || "{}");
}

function parseModuleEditor() {
  return JSON.parse(moduleJson.value || "{}");
}

function populateGraphSelector(graphs, selectedId) {
  if (!graphSelect) return;
  graphSelect.innerHTML = graphs
    .map((item) => {
      const label = `${item.name || item.id}${item.primary ? " · primary" : item.workspace ? ` · ${item.workspace}` : ""}`;
      return `<option value="${escapeHtml(item.id)}"${item.id === selectedId ? " selected" : ""}>${escapeHtml(label)}</option>`;
    })
    .join("");
  graphSelect.value = selectedId;
}

async function loadGraph(graphId = "") {
  setStatus("busy", "Loading", "Reading graph config.");
  const list = await requestJson("/api/graphs");
  availableGraphs = Array.isArray(list.graphs) ? list.graphs : [];
  const urlGraphId = deepLinkGraphId();
  const requested = graphId || urlGraphId || graphSelect?.value || list.active_graph_id || availableGraphs[0]?.id || "atr_closed_loop";
  const selected = availableGraphs.some((item) => item.id === requested) ? requested : availableGraphs[0]?.id;
  if (!selected) throw new Error("No Runtime graph config found.");
  populateGraphSelector(availableGraphs, selected);
  const graph = await requestJson(`/api/graphs/${selected}`);
  const useUrlFocus = !graphId || graphId === urlGraphId;
  const deepLinkedNodeId = useUrlFocus ? resolveGraphNodeRef(graph.graph, deepLinkNodeRef()) : "";
  selectedNodeId = deepLinkedNodeId || "";
  activeRuntimeEdge = null;
  edgeConnectMode = false;
  edgeConnectSource = "";
  edgeConnectDraft = null;
  upsertGraphTab({
    id: MAIN_GRAPH_TAB_ID,
    kind: "main",
    title: "Main System",
    subtitle: graph.graph.name || graph.graph.id || selected,
    graphId: selected,
    graph: graph.graph,
    baselineGraph: cloneConfig(graph.graph),
    fixed: true,
    dirty: false,
  });
  activeGraphTabId = MAIN_GRAPH_TAB_ID;
  activationEvidence = { validation: null, compile: null, dry_run: null, save: null, dirty: false, reason: "graph loaded" };
  liveGateSnapshot = { graph_id: selected, gate_ok: false, has_record: false, dry_run_record: {}, checking: true };
  renderGraph(graph.graph);
  if (deepLinkedNodeId) {
    requestAnimationFrame(() => focusGraphNodeInCanvas(deepLinkedNodeId));
    log(`Deep-linked to ${selected}:${deepLinkedNodeId}`, "ok");
  } else {
    requestAnimationFrame(() => fitGraphToCanvas({ silent: true }));
  }
  loadGraphDryRunGate(selected).catch((err) => log(String(err), "error"));
  setStatus("busy", "Graph Loaded", `${graph.graph.name} ${graph.graph.version}`);
  log(`Loaded graph ${graph.graph.id}`);
}

async function validateGraph() {
  const graph = parseGraphEditor();
  if (graph.metadata?.ide_tab_kind === "module") {
    applyModuleGraphDraftToEditor(graph);
    await validateModule(dryRunOutput);
    return;
  }
  const result = await requestJson(`/api/graphs/${graph.id}/validate-draft`, {
    method: "POST",
    body: JSON.stringify({ graph, reason: "runtime_ide_validate", author: "runtime_ide", activate: false }),
  });
  setStatus(result.ok ? "busy" : "warn", result.ok ? "Valid" : "Invalid", result.errors.join("; ") || "Draft graph validated and compiled.");
  if (result.compiled_graph) {
    dryRunOutput.innerHTML = compiledGraphSummaryMarkup(result.compiled_graph);
  }
  setActivationEvidence("validation", { ok: result.ok, errors: result.errors || [], detail: result.ok ? "draft validated + compiled" : "validation failed", compiled_graph: result.compiled_graph || null });
  if (result.compiled_graph) setActivationEvidence("compile", { ok: true, detail: compiledGraphEvidenceText(result.compiled_graph), compiled_graph: result.compiled_graph });
  log(`Validate draft ${result.ok ? "ok" : "failed"}: ${result.errors.join("; ") || "compiled"}`, result.ok ? "ok" : "error");
}

async function compileGraph() {
  const graph = parseGraphEditor();
  if (graph.metadata?.ide_tab_kind === "module") {
    applyModuleGraphDraftToEditor(graph);
    await validateModule(dryRunOutput);
    setStatus("busy", "Module Validated", `${graph.metadata?.module_id || "module"} internal graph draft validated.`);
    return;
  }
  const result = await requestJson(`/api/graphs/${graph.id}/validate-draft`, {
    method: "POST",
    body: JSON.stringify({ graph, reason: "runtime_ide_compile_draft", author: "runtime_ide", activate: false }),
  });
  setStatus(result.ok ? "busy" : "warn", result.compiled ? "Compiled" : "Compile Failed", result.errors.join("; ") || "Draft graph compiled.");
  dryRunOutput.innerHTML = compiledGraphSummaryMarkup(result.compiled_graph) || `<pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
  setActivationEvidence("compile", { ok: result.compiled, errors: result.errors || [], detail: result.compiled_graph ? compiledGraphEvidenceText(result.compiled_graph) : "compile failed", compiled_graph: result.compiled_graph || null });
  log(`Compile draft ${result.compiled ? "ok" : "failed"}`, result.compiled ? "ok" : "error");
}

function normalizedHandlerName(value = "") {
  return String(value || "").toLowerCase().replace(/^agent\./, "").replace(/agent$/g, "").replace(/[^a-z0-9]+/g, "");
}

function replayCompareStatus(expected = "", actual = "", options = {}) {
  const cleanExpected = String(expected || "").trim();
  const cleanActual = String(actual || "").trim();
  if (!cleanExpected || !cleanActual) return { status: "warn", label: "not enough data" };
  const normalize = options.handler ? normalizedHandlerName : (value) => String(value || "").toLowerCase().trim();
  return normalize(cleanExpected) === normalize(cleanActual)
    ? { status: "ok", label: "match" }
    : { status: "warn", label: `${cleanExpected} vs ${cleanActual}` };
}

function replayValidationMarkup(event = null, startStage = "", result = {}) {
  if (!event) return "";
  const sequence = Array.isArray(result.sequence) ? result.sequence : [];
  const first = sequence[0] || {};
  const eventStageValue = eventStage(event);
  const route = selectedTransitionSummary(event);
  const expectedNext = route.target || event?.payload?.next_stage || event?.state?.next_stage || "";
  const actualNext = first.next_stage || "";
  const node = eventNode(event);
  const expectedHandler = node?.handler || event?.payload?.handler || event?.payload?.agent || event?.agent || "";
  const actualHandler = first.effective_handler || first.graph_handler || first.module_handler || "";
  const stageStatus = replayCompareStatus(eventStageValue || startStage, first.stage || startStage);
  const routeStatus = expectedNext ? replayCompareStatus(expectedNext, actualNext) : { status: "warn", label: actualNext ? `actual ${actualNext}` : "no selected route" };
  const handlerStatus = replayCompareStatus(expectedHandler, actualHandler, { handler: true });
  const overallOk = Boolean(result.ok) && stageStatus.status === "ok" && (!expectedNext || routeStatus.status === "ok") && handlerStatus.status !== "warn";
  const overallClass = overallOk ? "ok" : "warn";
  return `
    <div class="runtime-replay-validation ${overallClass}">
      <div class="runtime-replay-validation-head">
        <strong>${escapeHtml(overallOk ? "Replay matches selected event" : "Replay check needs review")}</strong>
        <span>${escapeHtml(sequence.length)} dry-run step(s) · ${escapeHtml(result.draft ? "draft payload" : "active config")}</span>
      </div>
      <div class="runtime-replay-validation-grid">
        <span class="${escapeHtml(stageStatus.status)}">
          <small>Stage</small>
          <strong>${escapeHtml(stageStatus.label)}</strong>
          <em>${escapeHtml(eventStageValue || startStage || "n/a")} -> ${escapeHtml(first.stage || "n/a")}</em>
        </span>
        <span class="${escapeHtml(routeStatus.status)}">
          <small>Route</small>
          <strong>${escapeHtml(routeStatus.label)}</strong>
          <em>${escapeHtml(expectedNext || "event route unknown")} -> ${escapeHtml(actualNext || "dry-run target unknown")}</em>
        </span>
        <span class="${escapeHtml(handlerStatus.status)}">
          <small>Handler</small>
          <strong>${escapeHtml(handlerStatus.label)}</strong>
          <em>${escapeHtml(expectedHandler || "event handler unknown")} -> ${escapeHtml(actualHandler || "dry-run handler unknown")}</em>
        </span>
        <span class="${result.ok ? "ok" : "error"}">
          <small>Dry-run</small>
          <strong>${escapeHtml(result.ok ? "compiled" : "failed")}</strong>
          <em>${escapeHtml(result.graph_id || activeGraph?.id || "graph")}</em>
        </span>
      </div>
    </div>
  `;
}

async function dryRunGraph(startStage = "idle", targetOutput = dryRunOutput) {
  const graph = parseGraphEditor();
  if (graph.metadata?.ide_tab_kind === "module") {
    applyModuleGraphDraftToEditor(graph);
    await dryRunModule(targetOutput);
    return;
  }
  const result = await requestJson(`/api/graphs/${graph.id}/dry-run`, {
    method: "POST",
    body: JSON.stringify({ graph, start_stage: startStage, max_steps: 24 }),
  });
  const sequenceMarkup = result.sequence
    .map((item) => {
      const moduleRuntime = item.module_runtime || {};
      const moduleText = item.module_id
        ? ` · module ${escapeHtml(item.module_id)} · pre ${escapeHtml(moduleRuntime.pre_execution_count || 0)} · internal ${escapeHtml(moduleRuntime.internal_graph_count || 0)}`
        : "";
      const handlerText = item.effective_handler || item.graph_handler
        ? `<small>node ${escapeHtml(item.node_id || "-")} · handler ${escapeHtml(item.effective_handler || item.graph_handler || "-")}${moduleText}</small>`
        : "";
      return `<div><strong>${escapeHtml(item.step)}. ${escapeHtml(item.stage)}</strong> -> ${escapeHtml(item.next_stage)} ${handlerText}</div>`;
    })
    .join("");
  const replayPreamble = targetOutput === replayOutput ? targetOutput.innerHTML : "";
  const replayValidation = targetOutput === replayOutput ? replayValidationMarkup(selectedTimelineEvent(), startStage, result) : "";
  targetOutput.innerHTML = `${replayPreamble}${replayValidation}${compiledGraphSummaryMarkup(result.compiled_graph)}${sequenceMarkup}`;
  if (targetOutput === dryRunOutput) {
    setActivationEvidence("dry_run", { ok: result.ok, errors: result.errors || [], detail: `${(result.sequence || []).length} steps · ${result.draft ? "draft payload" : "active config"}`, sequence: result.sequence || [], dry_run_record: result.dry_run_record || {}, compiled_graph: result.compiled_graph || null });
  }
  log(`Dry-run ${result.ok ? "ok" : "failed"} from ${startStage}`, result.ok ? "ok" : "error");
}

async function loadGraphVersions() {
  if (!graphVersionOutput) return;
  const graph = activeGraph || parseGraphEditor();
  const graphId = graph.id || graphSelect?.value || "atr_closed_loop";
  if (graphVersionPanel) graphVersionPanel.open = true;
  graphVersionOutput.innerHTML = "<div>Loading graph versions...</div>";
  const result = await requestJson(`/api/graphs/${graphId}/versions`);
  const versions = Array.isArray(result.versions) ? result.versions : [];
  if (!versions.length) {
    graphVersionOutput.innerHTML = `<div>No saved graph versions for ${escapeHtml(graphId)} yet.</div>`;
    return;
  }
  graphVersionOutput.innerHTML = versions
    .map((version) => `
      <div class="runtime-version-item">
        <div>
          <strong>${escapeHtml(versionLabel(version))}</strong>
          <small>${escapeHtml(formatVersionTimestamp(version.created_at))}</small>
          <span>${escapeHtml(version.reason || "no reason")}</span>
        </div>
        <button type="button" class="btn tiny" data-graph-version-load="${escapeHtml(version.version_id)}">Load Draft</button>
      </div>
    `)
    .join("");
  graphVersionOutput.querySelectorAll("[data-graph-version-load]").forEach((el) => {
    el.addEventListener("click", () => loadGraphVersionDraft(el.getAttribute("data-graph-version-load") || "").catch((err) => log(String(err), "error")));
  });
}

async function loadGraphVersionDraft(versionId) {
  if (!versionId) return;
  const graph = activeGraph || parseGraphEditor();
  const graphId = graph.id || graphSelect?.value || "atr_closed_loop";
  const result = await requestJson(`/api/graphs/${graphId}/versions/${encodeURIComponent(versionId)}`);
  const draft = result.version?.graph;
  if (!draft || typeof draft !== "object") throw new Error(`Graph version payload is missing: ${versionId}`);
  selectedNodeId = "";
  activeRuntimeEdge = null;
  setGraphJson(draft);
  const tab = activeGraphTab();
  if (tab) {
    tab.graph = draft;
    tab.dirty = true;
  }
  markActivationDirty(`version draft ${versionId}`);
  renderGraph(draft);
  setStatus("busy", "Version Draft Loaded", `${graphId} ${versionId}`);
  dryRunOutput.innerHTML = `<div class="runtime-version-draft-note"><strong>Loaded graph version into draft.</strong> Validate, dry-run, then Save Version to activate.</div>`;
  log(`Loaded graph version draft ${versionId}`, "ok");
}

async function saveGraph() {
  const graph = parseGraphEditor();
  if (graph.metadata?.ide_tab_kind === "module") {
    applyModuleGraphDraftToEditor(graph);
    const modulePayload = modulePayloadForGraphDraft(graph);
    const moduleId = modulePayload.module?.id || graph.metadata?.module_id || activeModuleId;
    const preflight = moduleSavePreflightStatus(moduleId, modulePayload);
    if (!preflight.ok) {
      setStatus("warn", "Module Save Blocked", `${moduleId}: validate and dry-run this exact draft before saving.`);
      dryRunOutput.innerHTML = moduleSavePreflightBlockedMarkup(moduleId, preflight);
      log(`Module save blocked for ${moduleId}: validation=${preflight.validationOk} dry_run=${preflight.dryRunOk}`, "warn");
      return;
    }
    await saveModule({ enforcePreflight: false });
    const tab = activeGraphTab();
    if (tab) tab.dirty = false;
    setModulePreflightEvidence(moduleId, "save", { ok: true, fingerprint: preflight.fingerprint, detail: "module version saved" });
    renderGraphTabs();
    return;
  }
  const result = await requestJson(`/api/graphs/${graph.id}`, {
    method: "PUT",
    body: JSON.stringify({ graph, reason: "runtime_ide_save", author: "runtime_ide", activate: true }),
  });
  if (!result.ok) {
    const errors = result.errors || ["graph save failed"];
    setStatus("error", "Graph Save Failed", errors.join("; "));
    dryRunOutput.innerHTML = `<div class="runtime-version-draft-note danger"><strong>Graph save failed.</strong><p>${escapeHtml(errors.join("; "))}</p></div>`;
    setActivationEvidence("save", { ok: false, errors, detail: errors.join("; ") });
    log(`Graph save failed for ${graph.id}: ${errors.join("; ")}`, "error");
    return result;
  }
  const tab = activeGraphTab();
  if (tab) {
    tab.graph = graph;
    tab.baselineGraph = cloneConfig(graph);
    tab.dirty = false;
  }
  const dryRun = result.dry_run || {};
  const dryRunRecord = result.dry_run_record || dryRun.dry_run_record || {};
  if (dryRun.ok) {
    setActivationEvidence("dry_run", {
      ok: true,
      errors: [],
      detail: `${(dryRun.sequence || []).length} steps · server save preflight`,
      sequence: dryRun.sequence || [],
      dry_run_record: dryRunRecord,
      compiled_graph: dryRun.compiled_graph || result.compiled_graph || null,
    });
  }
  liveGateSnapshot = {
    graph_id: graph.id,
    gate_ok: Boolean(dryRunRecord.live_gate_recorded),
    has_record: Boolean(dryRunRecord.digest),
    dry_run_record: dryRunRecord,
    checking: false,
  };
  renderGraph(graph);
  if (!dryRunRecord.live_gate_recorded) loadGraphDryRunGate(graph.id).catch((err) => log(String(err), "error"));
  setStatus("busy", "Saved", `Version ${result.version?.version_id || "versioned"}`);
  if (result.compiled_graph || dryRun.sequence) {
    const sequenceMarkup = (dryRun.sequence || [])
      .map((item) => `<div><strong>${escapeHtml(item.step)}. ${escapeHtml(item.stage)}</strong> -> ${escapeHtml(item.next_stage)}</div>`)
      .join("");
    dryRunOutput.innerHTML = `${compiledGraphSummaryMarkup(result.compiled_graph || dryRun.compiled_graph)}${sequenceMarkup}`;
  }
  setActivationEvidence("save", { ok: result.ok, errors: result.errors || [], detail: result.version?.version_id || "versioned", version_id: result.version?.version_id || "", activated: result.activated, compiled_graph: result.compiled_graph || null });
  log(`Saved active graph ${result.version?.version_id || "version recorded"}; dry-run gate ${dryRunRecord.live_gate_recorded ? "recorded" : "not recorded"}.`, "ok");
  if (graphVersionPanel?.open) loadGraphVersions().catch((err) => log(String(err), "error"));
}

async function exportGraphYaml() {
  const graph = parseGraphEditor();
  const res = await fetch(`/api/graphs/${graph.id}/export-yaml`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ graph, reason: "runtime_ide_export", author: "runtime_ide", activate: false }),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  const blob = new Blob([text], { type: "application/x-yaml" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${graph.id || "runtime_graph"}.yaml`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  log(`Exported graph YAML for ${graph.id}`, "ok");
}

async function importGraphYamlText(yamlText) {
  const current = parseGraphEditor();
  const graphId = current.id || activeGraph?.id || "atr_closed_loop";
  const result = await requestJson(`/api/graphs/${graphId}/import-yaml`, {
    method: "POST",
    body: JSON.stringify({ yaml_text: yamlText }),
  });
  if (!result.ok) {
    log(`Import YAML failed: ${result.errors.join("; ")}`, "error");
    return;
  }
  selectedNodeId = "";
  activeRuntimeEdge = null;
  const tab = activeGraphTab();
  if (tab) {
    tab.graph = result.graph;
    tab.dirty = true;
  }
  markActivationDirty("yaml import draft");
  renderGraph(result.graph);
  setStatus("busy", "YAML Imported", result.compiled ? "Imported draft compiled." : "Imported draft loaded.");
  if (result.compiled_graph) {
    dryRunOutput.innerHTML = compiledGraphSummaryMarkup(result.compiled_graph);
  }
  log(`Imported graph YAML ${result.graph.id}. Validate before saving.`, "ok");
}

async function importGraphYamlFile(file) {
  if (!file) return;
  await importGraphYamlText(await file.text());
  yamlImportFile.value = "";
}

function logicalEdgeCondition(edge) {
  return String(edge?.condition || edge?.metadata?.condition || edge?.metadata?.transition_condition || "").trim();
}

function normalizeDefaultLogicalEdges(graph, sourceStage = "") {
  graph.transitions = graph.transitions || {};
  graph.edges = Array.isArray(graph.edges) ? graph.edges : [];
  const stages = sourceStage
    ? [sourceStage]
    : Array.from(new Set(graph.edges
      .filter((edge) => edge.metadata?.runtime_edge === "logical_transition")
      .map((edge) => edge.metadata?.from_stage || edge.source)
      .filter(Boolean)));
  for (const stage of stages) {
    const defaultTarget = graph.transitions?.[stage] || "";
    for (const edge of graph.edges) {
      if (edge.metadata?.runtime_edge !== "logical_transition") continue;
      const from = edge.metadata?.from_stage || edge.source;
      if (from !== stage) continue;
      edge.metadata = edge.metadata || {};
      const to = edge.metadata?.to_stage || edge.target;
      const condition = logicalEdgeCondition(edge);
      const isDefault = Boolean(defaultTarget) && to === defaultTarget && ["", "default", "continue", "always"].includes(condition || "default");
      edge.metadata.default_transition = isDefault;
      if (isDefault) {
        edge.condition = null;
        edge.metadata.condition = "default";
        edge.metadata.transition_condition = "default";
        edge.label = `default transition: ${stage} -> ${to}`;
      }
    }
  }
}

function syncLogicalTransitionEdge(graph, source, target, ports = {}) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const sourceNode = nodes.find((node) => node.stage === source || node.id === source);
  const targetNode = nodes.find((node) => node.stage === target || node.id === target);
  if (!sourceNode || !targetNode) return null;
  graph.transitions = graph.transitions || {};
  graph.edges = Array.isArray(graph.edges) ? graph.edges : [];
  const hadDefault = Boolean(graph.transitions[source]);
  const sameAsDefault = graph.transitions[source] === target;
  const makeDefault = ports.makeDefault === true || !hadDefault || sameAsDefault;
  if (makeDefault) graph.transitions[source] = target;
  const inferred = inferPortPair(sourceNode, targetNode);
  const condition = String(ports.condition || (makeDefault ? "default" : `next_stage:${target}`)).trim() || "next_stage";
  graph.edges = graph.edges.filter((edge) => {
    if (edge.metadata?.runtime_edge !== "logical_transition") return true;
    const from = edge.metadata?.from_stage || edge.source;
    const to = edge.metadata?.to_stage || edge.target;
    const edgeCondition = logicalEdgeCondition(edge) || (edge.metadata?.default_transition ? "default" : "candidate");
    return !(from === source && to === target && edgeCondition === condition);
  });
  if (makeDefault) {
    graph.edges = graph.edges.filter((edge) => {
      if (edge.metadata?.runtime_edge !== "logical_transition") return true;
      const from = edge.metadata?.from_stage || edge.source;
      if (from !== source) return true;
      const to = edge.metadata?.to_stage || edge.target;
      const edgeCondition = logicalEdgeCondition(edge) || (edge.metadata?.default_transition ? "default" : "candidate");
      const defaultLike = ["", "default", "continue", "always"].includes(edgeCondition || "default");
      return !(to !== target && defaultLike);
    });
    for (const edge of graph.edges) {
      if (edge.metadata?.runtime_edge === "logical_transition" && (edge.metadata?.from_stage || edge.source) === source) {
        edge.metadata.default_transition = false;
      }
    }
  }
  graph.edges.push({
    source: sourceNode.id,
    target: targetNode.id,
    condition: condition === "default" ? null : condition,
    label: `${makeDefault ? "default" : "candidate"} transition: ${source} -> ${target}`,
    metadata: {
      runtime_edge: "logical_transition",
      from_stage: source,
      to_stage: target,
      condition,
      transition_condition: condition,
      default_transition: makeDefault,
      auto_ports: ports.autoPorts !== false,
      source_port: ports.sourcePort || inferred.sourceSide,
      target_port: ports.targetPort || inferred.targetSide,
    },
  });
  normalizeDefaultLogicalEdges(graph, source);
  return { source, target, condition, default: makeDefault };
}


function applyTransitionEdit() {
  const graph = parseGraphEditor();
  const { source, target, condition, makeDefault } = transitionConditionSpec();
  if (!source || !target) {
    log("Transition source/target is empty.", "error");
    return;
  }
  const previousCondition = String(activeRuntimeEdge?.condition || "").trim();
  const editingSameEdge = activeRuntimeEdge?.source === source && activeRuntimeEdge?.target === target && previousCondition && previousCondition !== condition;
  if (editingSameEdge) {
    graph.edges = Array.isArray(graph.edges) ? graph.edges.filter((edgeItem) => {
      if (edgeItem.metadata?.runtime_edge !== "logical_transition") return true;
      const from = edgeItem.metadata?.from_stage || edgeItem.source;
      const to = edgeItem.metadata?.to_stage || edgeItem.target;
      const edgeCondition = logicalEdgeCondition(edgeItem) || (edgeItem.metadata?.default_transition ? "default" : "candidate");
      return !(from === source && to === target && edgeCondition === previousCondition);
    }) : [];
  }
  const edge = syncLogicalTransitionEdge(graph, source, target, { makeDefault, condition });
  selectedNodeId = findNodeByStage(source)?.id || selectedNodeId;
  activeRuntimeEdge = edge || { source, target, condition };
  updateEdgeEditStatus();
  if (graph.metadata?.ide_tab_kind === "module") {
    applyModuleGraphDraftToEditor(graph);
  }
  markActiveTabDirty(graph);
  renderGraph(graph);
  const routeKind = edge?.default ? "default transition" : "candidate edge";
  renderEdgeRoutePreview(graph);
  log(`Set ${routeKind} ${source} -> ${target} (${condition}). Validate before saving.`, "ok");
}

function setDesignerStatus(message, kind = "info") {
  if (!designerStatus) return;
  designerStatus.textContent = message;
  designerStatus.className = `hint runtime-module-designer-status ${kind}`;
}

function designerModuleIdFromFile(file) {
  const name = String(file?.name || "custom_module.py").replace(/\.py$/i, "");
  return slugify(name, "custom_module");
}

function fillDesignerFromFile(file) {
  if (!file) return;
  const moduleId = designerModuleIdFromFile(file);
  if (designerModuleIdInput && !designerModuleIdInput.value.trim()) designerModuleIdInput.value = moduleId;
  if (designerLabelInput && !designerLabelInput.value.trim()) designerLabelInput.value = titleFromSlug(moduleId);
}

async function createModuleFromDesigner() {
  const file = designerPythonFileInput?.files?.[0];
  if (!file) {
    setDesignerStatus("Select a Python source file first.", "error");
    return;
  }
  fillDesignerFromFile(file);
  const moduleId = slugify(designerModuleIdInput?.value || designerModuleIdFromFile(file), "custom_module");
  const label = designerLabelInput?.value?.trim() || titleFromSlug(moduleId);
  const category = designerCategoryInput?.value?.trim() || "";
  const handler = designerHandlerSelect?.value || "runtime.step_complete";
  const llmRole = designerLlmRoleInput?.value?.trim() || "";
  const notes = designerNotesInput?.value?.trim() || "";
  const sourceText = await file.text();
  designerCreateBtn.disabled = true;
  setDesignerStatus("Gemma 31B is transforming the Python file into an ATR protocol adapter...", "busy");
  try {
    const result = await requestJson("/api/modules", {
      method: "POST",
      body: JSON.stringify({
        module_id: moduleId,
        label,
        category,
        handler,
        llm_role: llmRole,
        source_filename: file.name,
        source_text: sourceText,
        notes,
        transform_with_llm: true,
        transform_model: "gemma4:31b",
      }),
    });
    if (!result.ok) {
      setDesignerStatus(`Module transform failed: ${(result.errors || []).join("; ") || "unknown error"}`, "error");
      log(`Module Designer failed for ${moduleId}: ${(result.errors || []).join("; ")}`, "error");
      return;
    }
    modulePayloadCache.set(result.module_id, result.module);
    await loadModules({ preferredModuleId: result.module_id, skipLoad: true });
    moduleSelect.value = result.module_id;
    activeModuleId = result.module_id;
    setModuleJson(result.module);
    updateModuleSummary(result.module.module || {});
    renderModuleGraph(result.module);
    await openModuleGraphTab(result.module_id);
    const warningText = Array.isArray(result.warnings) && result.warnings.length ? ` · warnings: ${result.warnings.join("; ")}` : "";
    setDesignerStatus(`Added ${result.module_id} (${result.transform?.category || "custom"}) using Gemma 31B.${warningText}`, result.warnings?.length ? "warn" : "ok");
    log(`Module Designer added ${result.module_id}; transformed source: ${result.transform?.transformed_source_path || "handler.py"}`, "ok");
  } catch (err) {
    setDesignerStatus(String(err), "error");
    log(`Module Designer error: ${err}`, "error");
  } finally {
    designerCreateBtn.disabled = false;
  }
}

async function loadHandlers() {
  const result = await requestJson("/api/handlers");
  availableHandlers = Array.isArray(result.handlers) ? result.handlers.slice().sort() : [];
  const metadata = Array.isArray(result.handler_metadata) ? result.handler_metadata : [];
  availableHandlerMetadata = new Map(metadata.map((item) => [String(item.handler_id || ""), item]).filter(([handlerId]) => Boolean(handlerId)));
  handlersOutput.innerHTML = availableHandlers.map((handler) => {
    const status = handlerMetadataStatus(handler);
    const meta = handlerMetadata(handler);
    return `
      <div class="runtime-handler-row ${escapeHtml(status.kind)}">
        <strong>${escapeHtml(handler)}</strong>
        <span>${escapeHtml(status.label)}</span>
        <small>${escapeHtml(meta?.signature || status.detail)}</small>
      </div>
    `;
  }).join("");
  renderDesignerHandlerOptions();
  refreshRuntimeReadinessViews();
}

function renderDesignerHandlerOptions() {
  if (!designerHandlerSelect) return;
  const current = designerHandlerSelect.value || "runtime.step_complete";
  designerHandlerSelect.innerHTML = handlerOptions(current || "runtime.step_complete");
  if (Array.from(designerHandlerSelect.options).some((option) => option.value === current)) designerHandlerSelect.value = current;
  else if (Array.from(designerHandlerSelect.options).some((option) => option.value === "runtime.step_complete")) designerHandlerSelect.value = "runtime.step_complete";
}

async function loadTools() {
  try {
    const result = await requestJson("/api/tools");
    availableTools = Array.isArray(result.tools) ? result.tools : [];
  } catch (err) {
    availableTools = [];
    log(`Tool list unavailable: ${err}`, "warn");
  }
}

async function loadModules(options = {}) {
  const result = await requestJson("/api/modules");
  availableModules = Array.isArray(result.modules) ? result.modules : [];
  const activeTab = activeGraphTab();
  const tabModuleId = activeTab?.kind === "module" ? activeTab.moduleId : "";
  const previous = options.preferredModuleId || tabModuleId || activeModuleId || moduleSelect.value;
  moduleSelect.innerHTML = availableModules
    .map((module) => `<option value="${escapeHtml(module.id)}">${escapeHtml(module.label)} · ${escapeHtml(module.category || "runtime")}</option>`)
    .join("");
  if (previous && Array.from(moduleSelect.options).some((option) => option.value === previous)) moduleSelect.value = previous;
  activeModuleId = moduleSelect.value;
  renderModuleCatalog();
  renderModuleTabs();
  if (activeModuleId && options.skipLoad !== true) {
    const stillActiveTab = activeGraphTab();
    if (stillActiveTab?.kind === "module" && stillActiveTab.moduleId === activeModuleId && stillActiveTab.modulePayload) {
      persistModuleTabPayload(activeModuleId, stillActiveTab.modulePayload, stillActiveTab.graph);
    } else {
      await loadModule(activeModuleId);
    }
  }
  refreshRuntimeReadinessViews();
}

async function loadModule(moduleId = "", options = {}) {
  const requested = moduleId || moduleSelect.value || activeModuleId;
  if (!requested) return;
  const activeTab = activeGraphTab();
  if (activeTab?.kind === "module" && activeTab.moduleId && requested !== activeTab.moduleId && options.force !== true) {
    const payload = activeTab.modulePayload || modulePayloadCache.get(activeTab.moduleId);
    if (payload) persistModuleTabPayload(activeTab.moduleId, payload, activeTab.graph);
    if (moduleSelect && Array.from(moduleSelect.options).some((option) => option.value === activeTab.moduleId)) moduleSelect.value = activeTab.moduleId;
    activeModuleId = activeTab.moduleId;
    log(`Skipped loading ${requested}; ${activeTab.moduleId} module tab is active.`, "warn");
    return;
  }
  activeModuleId = requested;
  if (moduleSelect && Array.from(moduleSelect.options).some((option) => option.value === requested)) moduleSelect.value = requested;
  const result = await requestJson(`/api/modules/${activeModuleId}`);
  modulePayloadCache.set(activeModuleId, result.module);
  setModuleJson(result.module);
  const module = result.module.module || {};
  renderModuleTabs();
  updateModuleSummary(module);
  renderModuleGraph(result.module);
  const tab = graphTabs.find((item) => item.id === `${MODULE_TAB_PREFIX}${activeModuleId}`);
  if (tab && activeGraphTabId === tab.id) {
    tab.modulePayload = cloneConfig(result.module);
    tab.graph = modulePayloadToGraph(result.module);
    tab.baselineGraph = tab.dirty ? tab.baselineGraph : cloneConfig(tab.graph);
    renderGraph(tab.graph);
  } else {
    refreshOpenModuleGraphTab(activeModuleId, { dirty: false, renderIfActive: true });
  }
  log(`Loaded module ${activeModuleId}`);
}

function renderModuleGraph(modulePayload = parseModuleEditor()) {
  const payload = modulePayload.module ? modulePayload : { module: modulePayload };
  const module = payload.module || {};
  const preSteps = Array.isArray(module.pre_execution) ? module.pre_execution : [];
  const internalSteps = Array.isArray(module.internal_graph) ? module.internal_graph : [];

  const renderSection = (title, hint, phase, steps, defaultKind) => `
    <div class="runtime-module-step-section" data-module-step-section="${escapeHtml(phase)}">
      <div class="panel-title-row runtime-ide-subtitle">
        <h3>${escapeHtml(title)}</h3>
        <span class="hint">${escapeHtml(hint)} · ${steps.length} step(s)</span>
      </div>
      ${steps.length ? steps.map((step, index) => `
        <div class="runtime-module-step" draggable="true" data-module-step-index="${index}" data-module-step-phase="${escapeHtml(phase)}">
          <strong>${escapeHtml(step.label || step.id || `${title} ${index + 1}`)}</strong>
          <span>${escapeHtml(step.id || "no-id")} · ${escapeHtml(step.kind || defaultKind)}${step.enabled === false ? " · disabled" : ""}</span>
          <div class="runtime-module-step-fields">
            <label class="runtime-handler-select-label">id
              <input class="text-input runtime-module-step-field" data-module-step-field="id" data-module-step-index="${index}" data-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.id || "")}" />
            </label>
            <label class="runtime-handler-select-label">label
              <input class="text-input runtime-module-step-field" data-module-step-field="label" data-module-step-index="${index}" data-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.label || "")}" />
            </label>
            <label class="runtime-handler-select-label">kind
              <input class="text-input runtime-module-step-field" data-module-step-field="kind" data-module-step-index="${index}" data-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.kind || defaultKind)}" />
            </label>
            <label class="runtime-handler-select-label">step handler
              <select class="text-input runtime-module-step-handler" data-module-step-handler="${index}" data-module-step-phase="${escapeHtml(phase)}">${handlerOptions(step.handler || module.handler || "")}</select>
            </label>
            ${phase === "pre_execution" ? `
              <label class="runtime-handler-select-label">output key
                <input class="text-input runtime-module-step-field" data-module-step-field="output_key" data-module-step-index="${index}" data-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.output_key || "")}" />
              </label>
              <label class="runtime-handler-select-label">event type
                <input class="text-input runtime-module-step-field" data-module-step-field="event_type" data-module-step-index="${index}" data-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.event_type || "")}" />
              </label>
              <label class="runtime-module-step-enabled">
                <input type="checkbox" data-module-step-field="enabled" data-module-step-index="${index}" data-module-step-phase="${escapeHtml(phase)}" ${step.enabled === false ? "" : "checked"} /> enabled
              </label>
            ` : ""}
          </div>
          <div class="runtime-module-step-actions">
            <button class="btn tiny" type="button" data-module-step-up="${index}" data-module-step-phase="${escapeHtml(phase)}">Up</button>
            <button class="btn tiny" type="button" data-module-step-down="${index}" data-module-step-phase="${escapeHtml(phase)}">Down</button>
            <button class="btn tiny danger" type="button" data-module-step-delete="${index}" data-module-step-phase="${escapeHtml(phase)}">Delete</button>
          </div>
        </div>
      `).join("") : `<div class="runtime-module-empty">No ${escapeHtml(title.toLowerCase())} steps.</div>`}
      <button class="btn tiny" type="button" data-module-step-add="${escapeHtml(phase)}">Add ${escapeHtml(title)} Step</button>
    </div>
  `;

  moduleGraphOutput.innerHTML = `
    ${renderSection("Pre-Execution", "runs before stage handler", "pre_execution", preSteps, "pre_stage")}
    ${renderSection("Internal Graph", "emitted as module trace", "internal_graph", internalSteps, "internal_step")}
  `;
  moduleGraphOutput.querySelectorAll("[data-module-step-up]").forEach((el) => {
    el.addEventListener("click", () => moveModuleStep(Number(el.getAttribute("data-module-step-up")), -1, el.getAttribute("data-module-step-phase") || "internal_graph"));
  });
  moduleGraphOutput.querySelectorAll("[data-module-step-down]").forEach((el) => {
    el.addEventListener("click", () => moveModuleStep(Number(el.getAttribute("data-module-step-down")), 1, el.getAttribute("data-module-step-phase") || "internal_graph"));
  });
  moduleGraphOutput.querySelectorAll("[data-module-step-delete]").forEach((el) => {
    el.addEventListener("click", () => deleteModuleStep(Number(el.getAttribute("data-module-step-delete")), el.getAttribute("data-module-step-phase") || "internal_graph"));
  });
  moduleGraphOutput.querySelectorAll("[data-module-step-handler]").forEach((el) => {
    el.addEventListener("change", () => updateModuleStepHandler(Number(el.getAttribute("data-module-step-handler")), el.value, el.getAttribute("data-module-step-phase") || "internal_graph"));
  });
  moduleGraphOutput.querySelectorAll("[data-module-step-field]").forEach((el) => {
    const eventName = el.getAttribute("type") === "checkbox" ? "change" : "input";
    el.addEventListener(eventName, () => updateModuleStepField(
      Number(el.getAttribute("data-module-step-index")),
      el.getAttribute("data-module-step-field") || "",
      el.getAttribute("type") === "checkbox" ? Boolean(el.checked) : el.value,
      el.getAttribute("data-module-step-phase") || "internal_graph",
    ));
  });
  moduleGraphOutput.querySelectorAll("[data-module-step-add]").forEach((el) => {
    el.addEventListener("click", () => addModuleStep(el.getAttribute("data-module-step-add") || "internal_graph"));
  });
  moduleGraphOutput.querySelectorAll("[data-module-step-index]").forEach((el) => {
    el.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", JSON.stringify({
        index: Number(el.getAttribute("data-module-step-index") || "0"),
        phase: el.getAttribute("data-module-step-phase") || "internal_graph",
      }));
    });
    el.addEventListener("dragover", (event) => event.preventDefault());
    el.addEventListener("drop", (event) => {
      event.preventDefault();
      let source = { index: Number(event.dataTransfer.getData("text/plain")), phase: el.getAttribute("data-module-step-phase") || "internal_graph" };
      try {
        source = JSON.parse(event.dataTransfer.getData("text/plain"));
      } catch (_error) {
        source = { index: Number(event.dataTransfer.getData("text/plain")), phase: el.getAttribute("data-module-step-phase") || "internal_graph" };
      }
      const targetPhase = el.getAttribute("data-module-step-phase") || "internal_graph";
      if ((source.phase || "internal_graph") !== targetPhase) {
        log("Cross-phase drag is disabled; use add/delete to move between pre_execution and internal_graph.", "warn");
        return;
      }
      reorderModuleStep(Number(source.index), Number(el.getAttribute("data-module-step-index")), targetPhase);
    });
  });
}

function modulePayloadWithSteps() {
  const payload = parseModuleEditor();
  const wrapped = payload.module ? payload : { module: payload };
  wrapped.module.pre_execution = Array.isArray(wrapped.module.pre_execution) ? wrapped.module.pre_execution : [];
  wrapped.module.internal_graph = Array.isArray(wrapped.module.internal_graph) ? wrapped.module.internal_graph : [];
  return wrapped;
}

function moduleStepsForPhase(module, phase = "internal_graph") {
  module.pre_execution = Array.isArray(module.pre_execution) ? module.pre_execution : [];
  module.internal_graph = Array.isArray(module.internal_graph) ? module.internal_graph : [];
  return phase === "pre_execution" ? module.pre_execution : module.internal_graph;
}

function readInputValue(id) {
  return document.getElementById(id)?.value?.trim() || "";
}

function readNumberInput(id) {
  const raw = readInputValue(id);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function readCheckbox(id) {
  return Boolean(document.getElementById(id)?.checked);
}

function parseLineList(value) {
  return String(value || "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function updateModuleConfigFromForm() {
  const payload = modulePayloadWithSteps();
  const module = payload.module;
  module.handler = document.getElementById("ide-module-handler-select")?.value || module.handler || "";
  module.llm_role = readInputValue("ide-module-llm-role");
  const backend = readInputValue("ide-module-llm-backend");
  const model = readInputValue("ide-module-llm-model");
  module.llm = {};
  if (backend) module.llm.backend = backend;
  if (model) module.llm.model = model;
  if (!Object.keys(module.llm).length) delete module.llm;
  const timeout = readNumberInput("ide-module-timeout");
  if (timeout === null) delete module.timeout_s;
  else module.timeout_s = timeout;
  const maxAttempts = readNumberInput("ide-module-retry");
  if (maxAttempts === null) delete module.retry;
  else module.retry = { ...(module.retry || {}), max_attempts: Math.trunc(maxAttempts) };
  const checkedTools = Array.from(document.querySelectorAll("[data-module-tool-checkbox]:checked"))
    .map((input) => input.value)
    .filter(Boolean);
  const manualTools = parseLineList(document.getElementById("ide-module-tools")?.value || "");
  module.tools = Array.from(new Set([...checkedTools, ...manualTools]));
  const promptPath = readInputValue("ide-module-prompt-path");
  const systemPrompt = document.getElementById("ide-module-prompt-system")?.value || "";
  const developerPrompt = document.getElementById("ide-module-prompt-developer")?.value || "";
  module.prompt = {};
  if (promptPath) module.prompt.path = promptPath;
  if (systemPrompt.trim()) module.prompt.system = systemPrompt.trim();
  if (developerPrompt.trim()) module.prompt.developer = developerPrompt.trim();
  if (!Object.keys(module.prompt).length) delete module.prompt;
  module.safety = {
    ...(module.safety || {}),
    live_requires_validation: readCheckbox("ide-module-live-validation"),
    dry_run_supported: readCheckbox("ide-module-dry-run-supported"),
    requires_human_approval: readCheckbox("ide-module-human-approval"),
  };
  markModulePreflightDirty(module.id || activeModuleId, "module config changed");
  setModuleJson(payload);
  updateModuleSummary(module);
  renderModuleGraph(payload);
  refreshOpenModuleGraphTab(module.id || activeModuleId);
  log(`Updated module config draft for ${module.id || activeModuleId}. Validate before saving.`, "ok");
}

function updateModuleHandler(handler) {
  const payload = modulePayloadWithSteps();
  payload.module.handler = handler;
  for (const step of [...payload.module.pre_execution, ...payload.module.internal_graph]) {
    if (!step.handler) step.handler = handler;
  }
  markModulePreflightDirty(payload.module?.id || activeModuleId, "module handler changed");
  setModuleJson(payload);
  updateModuleSummary(payload.module);
  renderModuleGraph(payload);
  refreshOpenModuleGraphTab(payload.module?.id || activeModuleId);
  log(`Updated module handler to ${handler}. Validate before saving.`, "ok");
}

function updateModuleStepHandler(index, handler, phase = "internal_graph") {
  updateModuleStepField(index, "handler", handler, phase, { rerender: true });
}

function updateModuleStepField(index, field, value, phase = "internal_graph", options = {}) {
  const payload = modulePayloadWithSteps();
  const steps = moduleStepsForPhase(payload.module, phase);
  if (!field || index < 0 || index >= steps.length) return;
  if (field === "enabled") {
    steps[index][field] = Boolean(value);
  } else if (field === "id") {
    steps[index][field] = String(value || "").trim();
  } else if (String(value || "").trim()) {
    steps[index][field] = String(value).trim();
  } else {
    delete steps[index][field];
  }
  markModulePreflightDirty(payload.module?.id || activeModuleId, `module ${phase} step changed`);
  setModuleJson(payload);
  if (options.rerender) renderModuleGraph(payload);
  log(`Updated ${phase} step ${index + 1} ${field}. Validate before saving.`, "ok");
}

function moveModuleStep(index, delta, phase = "internal_graph") {
  reorderModuleStep(index, index + delta, phase);
}

function reorderModuleStep(fromIndex, toIndex, phase = "internal_graph") {
  const payload = modulePayloadWithSteps();
  const steps = moduleStepsForPhase(payload.module, phase);
  if (fromIndex < 0 || fromIndex >= steps.length || toIndex < 0 || toIndex >= steps.length || fromIndex === toIndex) return;
  const [item] = steps.splice(fromIndex, 1);
  steps.splice(toIndex, 0, item);
  markModulePreflightDirty(payload.module?.id || activeModuleId, `module ${phase} step reordered`);
  setModuleJson(payload);
  renderModuleGraph(payload);
  refreshOpenModuleGraphTab(payload.module?.id || activeModuleId);
  log(`Reordered ${phase} step ${fromIndex + 1} -> ${toIndex + 1}. Validate before saving.`, "ok");
}

function deleteModuleStep(index, phase = "internal_graph") {
  const payload = modulePayloadWithSteps();
  const steps = moduleStepsForPhase(payload.module, phase);
  if (index < 0 || index >= steps.length) return;
  const [removed] = steps.splice(index, 1);
  markModulePreflightDirty(payload.module?.id || activeModuleId, `module ${phase} step deleted`);
  setModuleJson(payload);
  renderModuleGraph(payload);
  refreshOpenModuleGraphTab(payload.module?.id || activeModuleId);
  log(`Deleted ${phase} step ${removed?.id || index + 1}. Validate before saving.`, "ok");
}

function addModuleStep(phase = "internal_graph") {
  const payload = modulePayloadWithSteps();
  const steps = moduleStepsForPhase(payload.module, phase);
  const nextIndex = steps.length + 1;
  const defaultHandler = payload.module.handler || availableHandlers[0] || "";
  const isPre = phase === "pre_execution";
  steps.push({
    id: `${isPre ? "pre_step" : "step"}_${String(nextIndex).padStart(2, "0")}`,
    label: `${isPre ? "Pre Step" : "Step"} ${nextIndex}`,
    kind: isPre ? "pre_stage" : "internal_step",
    handler: defaultHandler,
    ...(isPre ? { output_key: `pre_step_${String(nextIndex).padStart(2, "0")}`, event_type: "module_pre_step_completed", enabled: true } : {}),
  });
  markModulePreflightDirty(payload.module?.id || activeModuleId, `module ${phase} step added`);
  setModuleJson(payload);
  renderModuleGraph(payload);
  refreshOpenModuleGraphTab(payload.module?.id || activeModuleId);
  log(`Added ${phase} step ${nextIndex}. Validate before saving.`, "ok");
}

async function saveModule(options = {}) {
  const modulePayload = parseModuleEditor();
  const module = modulePayload.module || modulePayload;
  const moduleId = module.id || activeModuleId;
  let saveFingerprint = modulePayloadFingerprint(modulePayload);
  if (options.enforcePreflight) {
    const preflight = moduleSavePreflightStatus(moduleId, modulePayload);
    if (!preflight.ok) {
      setStatus("warn", "Module Save Blocked", `${moduleId}: validate and dry-run this exact draft before saving.`);
      dryRunOutput.innerHTML = moduleSavePreflightBlockedMarkup(moduleId, preflight);
      log(`Module save blocked for ${moduleId}: validation=${preflight.validationOk} dry_run=${preflight.dryRunOk}`, "warn");
      return null;
    }
    saveFingerprint = preflight.fingerprint;
  }
  const result = await requestJson(`/api/modules/${moduleId}`, {
    method: "PUT",
    body: JSON.stringify({ module: modulePayload, reason: "runtime_ide_module_save", author: "runtime_ide", activate: true }),
  });
  if (!result.ok) {
    const errors = result.errors || ["module save failed"];
    setStatus("error", "Module Save Failed", errors.join("; "));
    dryRunOutput.innerHTML = moduleValidationResultMarkup({ ok: false, errors }, moduleId);
    setModulePreflightEvidence(moduleId, "save", { ok: false, fingerprint: saveFingerprint, detail: errors.join("; ") });
    log(`Module save failed for ${moduleId}: ${errors.join("; ")}`, "error");
    return result;
  }
  if (result.dry_run?.ok) {
    setModulePreflightEvidence(moduleId, "dry_run", {
      ok: true,
      sequence: result.dry_run.sequence || [],
      summary: result.dry_run.summary || {},
      fingerprint: saveFingerprint,
      detail: `${(result.dry_run.sequence || []).length} step(s), server verified`,
    });
  }
  setModulePreflightEvidence(moduleId, "save", { ok: true, fingerprint: saveFingerprint, detail: result.version?.version_id || "module version saved", version_id: result.version?.version_id || "" });
  log(`Saved module ${moduleId} ${result.version?.version_id || "version recorded"}`, "ok");
  await loadModule();
  const tab = graphTabs.find((item) => item.id === `${MODULE_TAB_PREFIX}${moduleId}`);
  if (tab) {
    tab.modulePayload = normalizedModulePayload(parseModuleEditor());
    tab.baselineModulePayload = cloneConfig(tab.modulePayload);
    tab.graph = modulePayloadToGraph(tab.modulePayload);
    tab.baselineGraph = cloneConfig(tab.graph);
    tab.dirty = false;
    if (activeGraphTabId === tab.id) renderGraph(tab.graph);
    else renderGraphTabs();
  }
}

async function validateModule(targetOutput = null) {
  const modulePayload = parseModuleEditor();
  const module = modulePayload.module || modulePayload;
  const moduleId = module.id || activeModuleId;
  const result = await requestJson(`/api/modules/${moduleId}/validate`, {
    method: "POST",
    body: JSON.stringify({ module: modulePayload, reason: "runtime_ide_module_validate", author: "runtime_ide", activate: false }),
  });
  const errors = Array.isArray(result.errors) ? result.errors : [];
  const fingerprint = modulePayloadFingerprint(modulePayload);
  setModulePreflightEvidence(moduleId, "validation", { ok: result.ok, errors, fingerprint, detail: errors.join("; ") || "module validated" });
  setStatus(result.ok ? "busy" : "warn", result.ok ? "Module Valid" : "Module Invalid", errors.join("; ") || `${moduleId} internal graph validated.`);
  if (targetOutput) {
    targetOutput.innerHTML = moduleValidationResultMarkup(result, moduleId);
  } else if (currentGraphTabKind() === "module") {
    dryRunOutput.innerHTML = moduleValidationResultMarkup(result, moduleId);
  }
  log(`Module validate ${result.ok ? "ok" : "failed"}: ${errors.join("; ") || "valid"}`, result.ok ? "ok" : "error");
}

async function dryRunModule(targetOutput = null) {
  const modulePayload = parseModuleEditor();
  const module = modulePayload.module || modulePayload;
  const moduleId = module.id || activeModuleId;
  const result = await requestJson(`/api/modules/${moduleId}/dry-run`, {
    method: "POST",
    body: JSON.stringify({ module: modulePayload, reason: "runtime_ide_module_dry_run", author: "runtime_ide", activate: false }),
  });
  const sequence = Array.isArray(result.sequence) ? result.sequence : [];
  updateModuleSummary(module);
  const status = document.getElementById("ide-module-config-status");
  if (status) {
    status.innerHTML = `module dry-run: ${escapeHtml(result.ok ? "ok" : "failed")} · ${escapeHtml(sequence.length)} step(s)`;
  }
  const fingerprint = modulePayloadFingerprint(modulePayload);
  setModulePreflightEvidence(moduleId, "dry_run", { ok: result.ok, sequence, summary: result.summary || {}, fingerprint, detail: `${sequence.length} step(s), no hardware calls` });
  const evidenceMarkup = moduleDryRunResultMarkup(result, moduleId);
  if (targetOutput) {
    targetOutput.innerHTML = evidenceMarkup;
  } else if (currentGraphTabKind() === "module") {
    dryRunOutput.innerHTML = evidenceMarkup;
  }
  moduleGraphOutput.insertAdjacentHTML(
    "afterbegin",
    `<div class="runtime-module-dry-run-result">${sequence.map((item) => `<div>${escapeHtml(item.step)}. [${escapeHtml(item.phase || "internal_graph")}] ${escapeHtml(item.label)} <small>${escapeHtml(item.handler || item.kind)}${item.executable ? " · executable" : " · checkpoint"}</small></div>`).join("")}</div>`,
  );
  setStatus(result.ok ? "busy" : "warn", result.ok ? "Module Dry-run Complete" : "Module Dry-run Failed", `${moduleId}: ${sequence.length} step(s), no hardware calls.`);
  log(`Module dry-run ${result.ok ? "ok" : "failed"}`, result.ok ? "ok" : "error");
}

function eventStage(event) {
  return String(
    event?.node_id ||
      event?.payload?.node_id ||
      event?.payload?.stage ||
      event?.timestamp_stage ||
      event?.state?.stage ||
      "",
  );
}

function eventTypeName(event) {
  return String(event?.type || event?.event_type || "event");
}

function eventSeverity(event) {
  const explicit = String(event?.severity || event?.level || event?.status || event?.payload?.status || "").toLowerCase();
  const type = eventTypeName(event).toLowerCase();
  if (explicit.includes("error") || explicit.includes("fail") || type.includes("error") || type.includes("fail")) return "error";
  if (explicit.includes("warn") || explicit.includes("blocked") || explicit.includes("pending") || type.includes("approval")) return "warn";
  if (explicit === "info" || explicit.includes("done") || explicit.includes("ok") || explicit.includes("success") || type.includes("complete") || type.includes("compiled") || type.includes("created")) return "ok";
  return "idle";
}

function eventTimestamp(event) {
  return String(event?.ts || event?.timestamp || event?.created_at || "");
}

function eventNode(event) {
  const nodeId = String(event?.node_id || event?.payload?.node_id || event?.payload?.node || eventStage(event) || "");
  return findNodeById(nodeId) || findNodeByStage(nodeId) || null;
}

function eventPayloadSummary(event) {
  const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
  const keys = Object.keys(payload).slice(0, 4);
  if (event?.message) return event.message;
  if (keys.length) return keys.map((key) => `${key}=${compactJson(payload[key])}`).join(" · ");
  return "no payload summary";
}

function isModuleTraceEvent(event) {
  const type = eventTypeName(event);
  return type.startsWith("module.step.") || type.startsWith("module.graph.") || type.startsWith("module.pre_step.");
}

function moduleIdFromEvent(event) {
  const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
  const moduleRuntime = payload.module_runtime && typeof payload.module_runtime === "object" ? payload.module_runtime : {};
  return String(payload.module_id || moduleRuntime.module_id || event?.module_id || "");
}

function moduleStepFromEvent(event) {
  const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
  return payload.module_step && typeof payload.module_step === "object" ? payload.module_step : {};
}

function moduleTraceEventsForStage(stage = "", moduleId = "", limit = 80, runId = "") {
  const cleanStage = String(stage || "");
  const cleanModule = String(moduleId || "").split("/").filter(Boolean).pop() || String(moduleId || "");
  const selectedRun = runId || currentRunId || latestStateSnapshot?.state?.run_id || "";
  const matchesTrace = (event, enforceRun = true) => {
    if (!isModuleTraceEvent(event)) return false;
    if (enforceRun && selectedRun && event.run_id && event.run_id !== selectedRun) return false;
    const rawEventModule = moduleIdFromEvent(event);
    const eventModule = rawEventModule.split("/").filter(Boolean).pop() || rawEventModule;
    const eventStageValue = eventStage(event) || event?.payload?.node_id || event?.node_id || "";
    const stageMatch = !cleanStage || eventStageValue === cleanStage || event?.payload?.node_id === cleanStage;
    const moduleMatch = !cleanModule || eventModule === cleanModule;
    return stageMatch && moduleMatch;
  };
  const scoped = recentRuntimeEvents.filter((event) => matchesTrace(event, true));
  const source = scoped.length ? scoped : recentRuntimeEvents.filter((event) => matchesTrace(event, false));
  return source.slice(0, limit).reverse();
}

function moduleTraceSummary(traceEvents = []) {
  return traceEvents.reduce(
    (acc, event) => {
      const type = eventTypeName(event);
      acc.total += 1;
      if (type.startsWith("module.graph.")) acc.graph += 1;
      if (type.startsWith("module.step.")) acc.step += 1;
      if (type.startsWith("module.pre_step.")) acc.pre += 1;
      if (type.endsWith("failed")) acc.failed += 1;
      if (event?.payload?.executable) acc.executable += 1;
      return acc;
    },
    { total: 0, graph: 0, step: 0, pre: 0, executable: 0, failed: 0 },
  );
}

function renderModuleTraceMarkup(stage = "", moduleId = "", selectedEvent = null) {
  const traceEvents = moduleTraceEventsForStage(stage, moduleId, 80, selectedEvent?.run_id || "");
  if (!traceEvents.length) return "";
  const summary = moduleTraceSummary(traceEvents);
  const selectedId = selectedEvent?.event_id || "";
  return `
    <section class="runtime-module-trace-panel">
      <div class="runtime-module-trace-head">
        <span><strong>${escapeHtml(summary.total)}</strong><small>module events</small></span>
        <span><strong>${escapeHtml(summary.step)}</strong><small>internal steps</small></span>
        <span><strong>${escapeHtml(summary.pre)}</strong><small>pre steps</small></span>
        <span><strong>${escapeHtml(summary.executable)}</strong><small>executable</small></span>
        <span class="${summary.failed ? "error" : "ok"}"><strong>${escapeHtml(summary.failed)}</strong><small>failed</small></span>
      </div>
      <div class="runtime-module-trace-list">
        ${traceEvents.map((event) => {
          const type = eventTypeName(event);
          const step = moduleStepFromEvent(event);
          const severity = eventSeverity(event);
          const selected = selectedId && event.event_id === selectedId ? " selected" : "";
          const executable = Boolean(event?.payload?.executable || step.executable);
          const handlerConfigured = Boolean(event?.payload?.handler_configured || step.handler);
          const label = step.label || step.id || type;
          const handler = step.handler || event?.payload?.module_runtime?.handler || event?.payload?.agent || event.agent || "checkpoint";
          return `
            <div class="runtime-module-trace-row ${escapeHtml(severity)}${selected}">
              <span class="runtime-timeline-severity-dot ${escapeHtml(severity)}"></span>
              <div>
                <strong>${escapeHtml(type)} · ${escapeHtml(label)}</strong>
                <small>${escapeHtml(step.id || "module")} · ${escapeHtml(handler)} · ${escapeHtml(eventTimestamp(event) || "no timestamp")}</small>
                <em>${escapeHtml(executable ? "handler-backed step" : handlerConfigured ? "configured checkpoint" : "checkpoint event")}</em>
              </div>
            </div>
          `;
        }).join("")}
      </div>
    </section>
  `;
}

function eventJsonPreview(value, limit = 2600) {
  try {
    const text = JSON.stringify(value ?? {}, null, 2);
    return text.length > limit ? `${text.slice(0, limit)}\n... truncated` : text;
  } catch (err) {
    return String(value || "").slice(0, limit);
  }
}

function timelineStats(events) {
  const counts = events.reduce(
    (acc, event) => {
      const severity = eventSeverity(event);
      acc.total += 1;
      acc[severity] = (acc[severity] || 0) + 1;
      return acc;
    },
    { total: 0, ok: 0, warn: 0, error: 0, idle: 0 },
  );
  const stages = Array.from(new Set(events.map((event) => eventStage(event)).filter(Boolean)));
  return { ...counts, stages };
}

function renderRunTimeline() {
  const events = recentRuntimeEvents.slice(0, 40);
  if (!events.length) {
    selectedTimelineEventIndex = -1;
    runTimelineOutput.innerHTML = "<div>No runtime events yet.</div>";
    renderSelectedEventDetail();
    if (replayOutput) replayOutput.innerHTML = "<div>Select a runtime event to preview replay from that stage.</div>";
    return;
  }
  if (selectedTimelineEventIndex >= events.length) selectedTimelineEventIndex = -1;
  const stats = timelineStats(events);
  runTimelineOutput.innerHTML = `
    <div class="runtime-timeline-summary">
      <span><strong>${escapeHtml(stats.total)}</strong><small>events</small></span>
      <span class="ok"><strong>${escapeHtml(stats.ok)}</strong><small>ok</small></span>
      <span class="warn"><strong>${escapeHtml(stats.warn)}</strong><small>warn</small></span>
      <span class="error"><strong>${escapeHtml(stats.error)}</strong><small>error</small></span>
      <span><strong>${escapeHtml(stats.stages.length)}</strong><small>stages</small></span>
    </div>
    <div class="runtime-timeline-list">
      ${events
        .map((event, index) => {
          const selected = index === selectedTimelineEventIndex ? " selected" : "";
          const type = eventTypeName(event);
          const stage = eventStage(event) || "n/a";
          const ts = eventTimestamp(event);
          const severity = eventSeverity(event);
          const node = eventNode(event);
          const handler = node?.handler || event.agent || event.payload?.agent || "runtime";
          return `
            <button class="runtime-timeline-item ${escapeHtml(severity)}${selected}" data-event-index="${index}" type="button">
              <span class="runtime-timeline-severity-dot ${escapeHtml(severity)}"></span>
              <strong>${escapeHtml(type)}</strong>
              <span>${escapeHtml(stage)}</span>
              <small>${escapeHtml(handler)} · ${escapeHtml(ts || "no timestamp")}</small>
            </button>
          `;
        })
        .join("")}
    </div>
  `;
  runTimelineOutput.querySelectorAll("[data-event-index]").forEach((el) => {
    el.addEventListener("click", () => inspectTimelineEvent(Number(el.getAttribute("data-event-index"))));
  });
  renderSelectedEventDetail();
}

function selectedTimelineEvent() {
  return selectedTimelineEventIndex >= 0 ? recentRuntimeEvents[selectedTimelineEventIndex] : null;
}

function timelineIndexForEventId(eventId = "") {
  const clean = String(eventId || "");
  if (!clean) return -1;
  return recentRuntimeEvents.findIndex((event) => String(event.event_id || "") === clean);
}

function artifactRelatedEventId(artifact = {}) {
  const related = artifactRelatedEvent(artifact);
  return String(related?.event_id || "");
}

function relatedArtifactsForEvent(event = null) {
  if (!event) return [];
  const eventId = String(event.event_id || "");
  const payloadText = JSON.stringify(event.payload || {});
  return currentArtifacts
    .map((artifact, index) => ({ artifact, index, relatedId: artifactRelatedEventId(artifact) }))
    .filter(({ artifact, relatedId }) => {
      const path = String(artifact?.path || "");
      const name = String(artifact?.name || "");
      return (eventId && relatedId === eventId) || (path && payloadText.includes(path)) || (name && payloadText.includes(name));
    });
}

function selectedTransitionSummary(event = null) {
  if (!event) return { label: "n/a", target: "", candidateCount: 0 };
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  const selected = payload.selected_transition || payload.transition || event.selected_transition || {};
  const candidates = payload.transition_candidates || event.transition_candidates || [];
  const candidateCount = Array.isArray(candidates)
    ? candidates.length
    : candidates && typeof candidates === "object"
      ? Object.values(candidates).reduce((acc, items) => acc + (Array.isArray(items) ? items.length : 0), 0)
      : 0;
  if (selected && typeof selected === "object" && Object.keys(selected).length) {
    const condition = selected.condition || selected.route || selected.label || "selected";
    const target = selected.next_stage || selected.target || selected.to_stage || selected.node_id || "";
    return {
      label: target ? `${condition} -> ${target}` : String(condition),
      target: String(target || ""),
      candidateCount,
    };
  }
  const nextStage = payload.next_stage || payload.target_stage || payload.to_stage || event.next_stage || "";
  if (nextStage) {
    return { label: `next -> ${nextStage}`, target: String(nextStage), candidateCount };
  }
  return { label: candidateCount ? `${candidateCount} candidate(s)` : "no route change", target: "", candidateCount };
}

function selectedEventDecisionStripMarkup(event = null, node = null, stage = "") {
  if (!event) return "";
  const severity = eventSeverity(event);
  const relatedArtifacts = relatedArtifactsForEvent(event);
  const route = selectedTransitionSummary(event);
  const canReplay = Boolean(stage && activeGraph?.stage_dispatch?.[stage]);
  const moduleId = node?.module_id || event.module_id || event.payload?.module_id || moduleIdFromEvent(event) || "n/a";
  const runId = event.run_id || currentRunId || "n/a";
  return `
    <div class="runtime-event-decision-strip ${escapeHtml(severity)}">
      <span>
        <small>Event Status</small>
        <strong>${escapeHtml(severity.toUpperCase())}</strong>
        <em>${escapeHtml(eventTypeName(event))}</em>
      </span>
      <span>
        <small>Runtime Target</small>
        <strong>${escapeHtml(stage || "n/a")}</strong>
        <em>${escapeHtml(moduleId)}</em>
      </span>
      <span>
        <small>Route Decision</small>
        <strong>${escapeHtml(route.label)}</strong>
        <em>${escapeHtml(route.candidateCount ? `${route.candidateCount} candidate(s) checked` : "default/effective route")}</em>
      </span>
      <span>
        <small>Replay Basis</small>
        <strong>${escapeHtml(canReplay ? "available" : "snapshot only")}</strong>
        <em>${escapeHtml(canReplay ? `dry-run from ${stage}` : "no stage dispatch")}</em>
      </span>
      <span>
        <small>Artifacts</small>
        <strong>${escapeHtml(relatedArtifacts.length)}</strong>
        <em>${escapeHtml(runId)}</em>
      </span>
    </div>
  `;
}

function selectedEventActionMarkup(event = null, node = null, stage = "") {
  if (!event) return "";
  const relatedArtifacts = relatedArtifactsForEvent(event);
  const canReplay = Boolean(stage && activeGraph?.stage_dispatch?.[stage]);
  return `
    <div class="runtime-event-action-row">
      <button class="btn tiny" type="button" data-event-detail-action="focus-node" ${node ? "" : "disabled"}>Focus Node</button>
      <button class="btn tiny" type="button" data-event-detail-action="replay-stage" ${canReplay ? "" : "disabled"}>Replay From Stage</button>
      <button class="btn tiny" type="button" data-event-detail-action="show-artifacts" ${relatedArtifacts.length ? "" : "disabled"}>Related Artifacts (${escapeHtml(relatedArtifacts.length)})</button>
    </div>
  `;
}

function renderRelatedArtifactsForSelectedEvent(event = null) {
  const related = relatedArtifactsForEvent(event);
  if (!artifactPreviewOutput) return;
  if (!related.length) {
    artifactPreviewOutput.innerHTML = `<div>No artifacts are linked to the selected event.</div>`;
    return;
  }
  artifactPreviewOutput.innerHTML = `
    <div class="runtime-artifact-related-head">
      <strong>Artifacts linked to ${escapeHtml(eventTypeName(event))}</strong>
      <small>${escapeHtml(related.length)} file(s)</small>
    </div>
    <div class="runtime-artifact-related-list">
      ${related.map(({ artifact, index }) => `
        <button type="button" class="runtime-artifact-related-item" data-artifact-preview-index="${index}">
          <strong>${escapeHtml(artifact.name || artifact.path)}</strong>
          <span>${escapeHtml(artifact.path || "artifact")}</span>
        </button>
      `).join("")}
    </div>
  `;
  artifactPreviewOutput.querySelectorAll("[data-artifact-preview-index]").forEach((el) => {
    el.addEventListener("click", () => previewArtifact(Number(el.getAttribute("data-artifact-preview-index"))));
  });
}

async function replaySelectedTimelineEvent() {
  const event = selectedTimelineEvent();
  if (!event) return;
  const stage = eventStage(event);
  if (stage && activeGraph?.stage_dispatch?.[stage]) {
    replayOutput.innerHTML = `<div class="runtime-replay-preamble"><strong>Replay basis:</strong> ${escapeHtml(eventTypeName(event))} at stage ${escapeHtml(stage)}</div>`;
    await dryRunGraph(stage, replayOutput);
    return;
  }
  replayOutput.innerHTML = `
    <div class="runtime-replay-preamble"><strong>Replay basis:</strong> ${escapeHtml(eventTypeName(event))}</div>
    <pre>${escapeHtml(eventJsonPreview(event.state || event.payload || event, 2200))}</pre>
  `;
}

function firstIssueValue(...values) {
  for (const value of values) {
    if (Array.isArray(value) && value.length) return value.map((item) => String(item)).join("; ");
    if (value && typeof value === "object" && Object.keys(value).length) return compactJson(value);
    if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
  }
  return "";
}

function approvalIdFromEvent(event = null) {
  const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
  return String(payload.approval_id || payload.id || event?.approval_id || "");
}

function focusApprovalQueueItem(approvalId = "") {
  const clean = String(approvalId || "");
  if (!clean || !approvalQueueOutput) return false;
  renderApprovalQueue(latestStateSnapshot);
  const item = approvalQueueOutput.querySelector(`[data-approval-item-id="${CSS.escape(clean)}"]`);
  if (!item) {
    log(`Approval item not found in queue: ${clean}`, "warn");
    return false;
  }
  approvalQueueOutput.querySelectorAll(".runtime-approval-item.focused").forEach((el) => el.classList.remove("focused"));
  item.classList.add("focused");
  item.scrollIntoView({ block: "center", behavior: "smooth" });
  setTimeout(() => item.classList.remove("focused"), 4200);
  log(`Focused approval queue item: ${clean}`, "ok");
  return true;
}

function approvalResolutionForEvent(event = null) {
  const approvalId = approvalIdFromEvent(event);
  if (!approvalId) return { approvalId: "", status: "n/a", decision: "", operator: "", resolved_at: "", resolved_event_id: "" };
  const fromQueue = [...(currentApprovals.approvals || []), ...(currentApprovals.resolved || []), ...(currentApprovals.pending || [])]
    .find((item) => String(item?.approval_id || "") === approvalId);
  const resolvedEvent = recentRuntimeEvents.find((item) => {
    const type = eventTypeName(item);
    const payload = item?.payload && typeof item.payload === "object" ? item.payload : {};
    return type === "approval.resolved" && String(payload.approval_id || payload.id || "") === approvalId;
  });
  const resolvedPayload = resolvedEvent?.payload && typeof resolvedEvent.payload === "object" ? resolvedEvent.payload : {};
  const status = fromQueue?.status || (resolvedEvent ? "resolved" : "pending");
  return {
    approvalId,
    status,
    decision: fromQueue?.decision || resolvedPayload.decision || "",
    operator: fromQueue?.operator || resolvedPayload.operator || "",
    resolved_at: fromQueue?.resolved_at || resolvedPayload.resolved_at || eventTimestamp(resolvedEvent) || "",
    resolved_event_id: fromQueue?.resolved_event_id || resolvedEvent?.event_id || "",
  };
}

function eventRemediationActions(event = null, node = null, stage = "") {
  const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
  const type = eventTypeName(event).toLowerCase();
  const actions = [];
  if (node) actions.push("Focus Node로 graph와 inspector를 해당 node에 맞춘다.");
  if (stage && activeGraph?.stage_dispatch?.[stage]) actions.push("Replay From Stage로 saved/draft graph 기준 재현 경로를 확인한다.");
  if (relatedArtifactsForEvent(event).length) actions.push("Related Artifacts에서 원본 파일과 생성 event를 추적한다.");
  if (type.includes("approval") || payload.requires_human_approval || payload.status === "waiting_approval") actions.push("Human Approval Queue에서 approve/reject 상태를 처리한다.");
  if (type.includes("validation") || type.includes("compiled") || payload.errors || payload.validation_errors) actions.push("Validate/Compile evidence에서 schema, handler, module, route 오류를 먼저 수정한다.");
  if (payload.device || payload.printer || payload.robot || payload.bridge || payload.failure_code) actions.push("Device Status와 관련 workspace bridge health를 확인한다.");
  if (!actions.length) actions.push("Payload JSON과 State JSON을 확인한 뒤 같은 stage replay 결과와 비교한다.");
  return Array.from(new Set(actions)).slice(0, 5);
}

function eventRemediationMarkup(event = null, node = null, stage = "") {
  const severity = eventSeverity(event);
  if (!event || !["warn", "error"].includes(severity)) return "";
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  const cause = firstIssueValue(
    payload.failure_code,
    payload.error,
    payload.error_message,
    payload.reason,
    payload.errors,
    payload.validation_errors,
    event.error,
    event.message,
    payload.status,
  ) || "No explicit failure code; inspect payload/state JSON.";
  const impact = firstIssueValue(payload.blocked_stage, payload.stage, stage, event.node_id, payload.node_id) || "runtime";
  const evidence = firstIssueValue(payload.artifact, payload.log_path, payload.report_url, payload.preview_url, payload.connection_memory_path, payload.command_preview) || "No direct artifact/log reference.";
  const actions = eventRemediationActions(event, node, stage);
  const approvalState = approvalResolutionForEvent(event);
  const approvalId = approvalState.approvalId;
  const approvalResolved = approvalState.status === "resolved";
  const approvalAction = approvalId && !approvalResolved ? `<button type="button" class="btn tiny runtime-remediation-focus-approval" data-remediation-approval-id="${escapeHtml(approvalId)}">Focus Approval Queue</button>` : "";
  const approvalStatusMarkup = approvalId ? `
        <span class="runtime-event-approval-status ${escapeHtml(approvalResolved ? "ok" : "warn")}">
          <small>Approval Status</small>
          <strong>${escapeHtml(approvalResolved ? `resolved ${approvalState.decision || ""}`.trim() : "pending")}</strong>
          <em>${escapeHtml(approvalResolved ? `${approvalState.operator || "operator"} · ${approvalState.resolved_at || "resolved"}` : approvalId)}</em>
        </span>` : "";
  return `
    <section class="runtime-event-remediation ${escapeHtml(severity)}">
      <div class="runtime-event-remediation-head">
        <strong>${escapeHtml(severity === "error" ? "Error remediation" : "Warning remediation")}</strong>
        <span>${escapeHtml(eventTypeName(event))}</span>
        ${approvalAction}
      </div>
      <div class="runtime-event-remediation-grid">
        <span>
          <small>Likely Cause</small>
          <strong>${escapeHtml(cause)}</strong>
        </span>
        <span>
          <small>Impacted Target</small>
          <strong>${escapeHtml(impact)}</strong>
        </span>
        <span>
          <small>Evidence</small>
          <strong>${escapeHtml(evidence)}</strong>
        </span>
        ${approvalStatusMarkup}
      </div>
      <div class="runtime-event-remediation-actions">
        <small>Recommended next actions</small>
        ${actions.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
      </div>
    </section>
  `;
}

function bindSelectedEventDetailActions() {
  eventDetailOutput?.querySelectorAll?.("[data-event-detail-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const event = selectedTimelineEvent();
      if (!event) return;
      const action = button.getAttribute("data-event-detail-action") || "";
      if (action === "focus-node") {
        const node = eventNode(event);
        if (node) selectNode(node.id, { focus: true });
      } else if (action === "replay-stage") {
        replaySelectedTimelineEvent().catch((err) => log(String(err), "error"));
      } else if (action === "show-artifacts") {
        renderRelatedArtifactsForSelectedEvent(event);
      }
    });
  });
  eventDetailOutput?.querySelectorAll?.("[data-remediation-approval-id]").forEach((button) => {
    button.addEventListener("click", () => focusApprovalQueueItem(button.getAttribute("data-remediation-approval-id") || ""));
  });
}

function renderSelectedEventDetail() {
  if (!eventDetailOutput) return;
  const event = selectedTimelineEvent();
  if (!event) {
    eventDetailOutput.innerHTML = `
      <div class="runtime-event-detail-empty">Select a Run Timeline event to inspect raw state, payload, and replay path.</div>
    `;
    return;
  }
  const node = eventNode(event);
  const stage = eventStage(event) || "n/a";
  const severity = eventSeverity(event);
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  const state = event.state && typeof event.state === "object" ? event.state : {};
  eventDetailOutput.innerHTML = `
    <div class="runtime-event-detail-head ${escapeHtml(severity)}">
      <div>
        <span class="runtime-node-status-pill ${escapeHtml(statusBadgeClass(severity))}">${escapeHtml(severity)}</span>
        <strong>${escapeHtml(eventTypeName(event))}</strong>
        <small>${escapeHtml(event.event_id || event.run_id || "event")}</small>
      </div>
      <div>
        <span>${escapeHtml(stage)}</span>
        <small>${escapeHtml(eventTimestamp(event) || "no timestamp")}</small>
      </div>
    </div>
    ${selectedEventActionMarkup(event, node, stage)}
    ${selectedEventDecisionStripMarkup(event, node, stage)}
    ${eventRemediationMarkup(event, node, stage)}
    <div class="runtime-event-detail-grid">
      <span><strong>Node</strong><small>${escapeHtml(node?.label || event.node_id || stage)}</small></span>
      <span><strong>Handler</strong><small>${escapeHtml(node?.handler || payload.agent || event.agent || "runtime")}</small></span>
      <span><strong>Module</strong><small>${escapeHtml(node?.module_id || event.module_id || payload.module_id || "n/a")}</small></span>
      <span><strong>Run</strong><small>${escapeHtml(event.run_id || currentRunId || "n/a")}</small></span>
    </div>
    <p class="runtime-event-summary">${escapeHtml(eventPayloadSummary(event))}</p>
    ${renderModuleTraceMarkup(stage, payload.module_id || node?.module_id || moduleIdFromEvent(event), event)}
    <details open class="runtime-event-json-block">
      <summary>Payload JSON</summary>
      <pre>${escapeHtml(eventJsonPreview(payload))}</pre>
    </details>
    <details class="runtime-event-json-block">
      <summary>State JSON at event</summary>
      <pre>${escapeHtml(eventJsonPreview(state))}</pre>
    </details>
  `;
  bindSelectedEventDetailActions();
}

async function inspectTimelineEvent(index) {
  const event = recentRuntimeEvents[index];
  if (!event) return;
  selectedTimelineEventIndex = index;
  const stage = eventStage(event);
  if (stage) {
    activeRuntimeStage = stage;
    const node = findNodeByStage(stage);
    if (node) selectedNodeId = node.id;
  }
  renderRunTimeline();
  renderSelectedEventDetail();
  if (activeGraph) renderGraph(parseGraphEditor());
  if (stage && activeGraph?.stage_dispatch?.[stage]) {
    replayOutput.innerHTML = `<div class="runtime-replay-preamble"><strong>Replay basis:</strong> ${escapeHtml(eventTypeName(event))} at stage ${escapeHtml(stage)}</div>`;
    await dryRunGraph(stage, replayOutput);
  } else {
    replayOutput.innerHTML = `
      <div class="runtime-replay-preamble"><strong>Replay basis:</strong> ${escapeHtml(eventTypeName(event))}</div>
      <pre>${escapeHtml(eventJsonPreview(event.state || event.payload || event, 2200))}</pre>
    `;
  }
}

function artifactStageFromPath(path = "") {
  const parts = String(path || "").split("/").filter(Boolean);
  if (!parts.length) return "artifact";
  if (parts[0] === "workspace") {
    const workspace = parts[1] || "workspace";
    const workspaceStages = {
      bo: "bo",
      cae: "analysis",
      printer: "specimen",
      lerobot: "manipulation",
      equipment: "equipment",
      windows: "equipment",
    };
    return workspaceStages[workspace] || workspace;
  }
  if (parts[0] === "runtime") {
    const runtimeStage = parts[1] || "runtime";
    const runtimeStages = {
      bo: "bo",
      analysis: "analysis",
      cae: "analysis",
      printer: "specimen",
      specimen: "specimen",
      lerobot: "manipulation",
      manipulation: "manipulation",
      equipment: "equipment",
    };
    return runtimeStages[runtimeStage] || runtimeStage;
  }
  if (parts[0] === "planning" && parts.length > 1) return "planning";
  if (parts[0] === "cae" || parts[0] === "fem") return "analysis";
  if (parts[0] === "printer" || parts[0] === "gcode") return "specimen";
  return parts[0];
}

function artifactRelatedEvent(artifact) {
  const path = String(artifact?.path || "");
  const name = String(artifact?.name || "");
  return recentRuntimeEvents.find((event) => {
    const payloadText = JSON.stringify(event.payload || {});
    return (path && payloadText.includes(path)) || (name && payloadText.includes(name));
  }) || null;
}

function artifactProvenanceMarkup(artifact = {}, related = null, kind = "download", url = "") {
  const stage = related ? eventStage(related) : artifactStageFromPath(artifact.path);
  const node = related ? eventNode(related) : null;
  const payload = related?.payload && typeof related.payload === "object" ? related.payload : {};
  const handler = node?.handler || payload.agent || related?.agent || "n/a";
  const previewable = kind === "image" || kind === "text";
  const sizeKb = Number(artifact.size_bytes || 0) / 1024;
  const canReplay = Boolean(stage && activeGraph?.stage_dispatch?.[stage]);
  return `
    <div class="runtime-artifact-provenance-strip ${related ? "linked" : "unlinked"}">
      <span>
        <small>Producer Stage</small>
        <strong>${escapeHtml(stage || "artifact")}</strong>
        <em>${escapeHtml(related ? eventTypeName(related) : "path-inferred")}</em>
      </span>
      <span>
        <small>Producer Handler</small>
        <strong>${escapeHtml(handler)}</strong>
        <em>${escapeHtml(related?.event_id || "no event link")}</em>
      </span>
      <span>
        <small>Artifact Type</small>
        <strong>${escapeHtml(kind || "file")}</strong>
        <em>${escapeHtml(`${sizeKb.toFixed(1)} KB`)}</em>
      </span>
      <span>
        <small>Preview</small>
        <strong>${escapeHtml(previewable ? "inline" : "download")}</strong>
        <em>${escapeHtml(url ? "url ready" : "missing url")}</em>
      </span>
      <span>
        <small>Replay</small>
        <strong>${escapeHtml(canReplay ? "available" : "blocked")}</strong>
        <em>${escapeHtml(canReplay ? `dry-run from ${stage}` : "no dispatch stage")}</em>
      </span>
    </div>
  `;
}

function renderArtifactLineage() {
  if (!currentArtifacts.length) {
    artifactLineageOutput.innerHTML = currentRunId ? "<div>No artifacts found for current run.</div>" : "<div>No active run loaded.</div>";
    artifactPreviewOutput.innerHTML = "<div>No artifact selected.</div>";
    return;
  }
  const artifacts = currentArtifacts.slice(0, 80).map((artifact, index) => {
    const related = artifactRelatedEvent(artifact);
    const stage = related ? eventStage(related) : artifactStageFromPath(artifact.path);
    return { artifact, index, related, stage };
  });
  const groups = artifacts.reduce((acc, item) => {
    const stage = item.stage || "artifact";
    if (!acc.has(stage)) acc.set(stage, []);
    acc.get(stage).push(item);
    return acc;
  }, new Map());
  artifactLineageOutput.innerHTML = `
    <div class="runtime-artifact-summary">
      <span><strong>${escapeHtml(currentArtifacts.length)}</strong><small>files</small></span>
      <span><strong>${escapeHtml(groups.size)}</strong><small>groups</small></span>
      <span><strong>${escapeHtml(currentRunId || "n/a")}</strong><small>run</small></span>
    </div>
    <div class="runtime-artifact-lineage-groups">
      ${Array.from(groups.entries())
        .map(([stage, items]) => `
          <section class="runtime-artifact-group">
            <div class="runtime-artifact-group-title"><strong>${escapeHtml(stage)}</strong><small>${escapeHtml(items.length)} artifact(s)</small></div>
            ${items
              .map(({ artifact, index, related }) => {
                const sizeKb = Number(artifact.size_bytes || 0) / 1024;
                const kind = artifact.preview_kind || artifact.suffix || "file";
                return `
                  <div class="runtime-artifact-item">
                    <strong>${escapeHtml(artifact.name || artifact.path)}</strong>
                    <span>${escapeHtml(artifact.path)}</span>
                    <small>${escapeHtml(kind)} · ${sizeKb.toFixed(1)} KB${related ? ` · ${escapeHtml(eventTypeName(related))}` : ""}</small>
                    <div class="runtime-artifact-actions">
                      <button type="button" class="btn tiny" data-artifact-preview-index="${index}">Preview</button>
                      ${related?.event_id ? `<button type="button" class="btn tiny" data-artifact-trace-event="${escapeHtml(related.event_id)}">Trace Event</button>` : ""}
                      <a class="btn tiny" href="${escapeHtml(artifact.download_url || artifact.url || "#")}">Download</a>
                    </div>
                  </div>
                `;
              })
              .join("")}
          </section>
        `)
        .join("")}
    </div>
  `;
  artifactLineageOutput.querySelectorAll("[data-artifact-preview-index]").forEach((el) => {
    el.addEventListener("click", () => previewArtifact(Number(el.getAttribute("data-artifact-preview-index"))));
  });
  artifactLineageOutput.querySelectorAll("[data-artifact-trace-event]").forEach((el) => {
    el.addEventListener("click", () => {
      const index = timelineIndexForEventId(el.getAttribute("data-artifact-trace-event") || "");
      if (index >= 0) inspectTimelineEvent(index).catch((err) => log(String(err), "error"));
    });
  });
}

async function previewArtifact(index) {
  const artifact = currentArtifacts[index];
  if (!artifact) return;
  const url = artifact.url || artifact.download_url || "";
  const kind = artifact.preview_kind || "download";
  const related = artifactRelatedEvent(artifact);
  const relatedId = String(related?.event_id || "");
  const relatedStage = related ? eventStage(related) : artifactStageFromPath(artifact.path);
  const canReplayProducer = Boolean(relatedStage && activeGraph?.stage_dispatch?.[relatedStage]);
  const traceButton = relatedId ? `<button type="button" class="btn tiny" data-preview-trace-event="${escapeHtml(relatedId)}">Trace Event</button>` : "";
  const replayButton = canReplayProducer ? `<button type="button" class="btn tiny" data-preview-replay-producer="${escapeHtml(relatedId)}" data-preview-replay-stage="${escapeHtml(relatedStage)}">Replay Producer Stage</button>` : "";
  const headerMarkup = `
    <div class="runtime-artifact-preview-head">
      <strong>${escapeHtml(artifact.name || artifact.path)}</strong>
      <div class="runtime-artifact-preview-actions">
        ${traceButton}
        ${replayButton}
        <a class="btn tiny" href="${escapeHtml(artifact.download_url || url || "#")}">Download</a>
      </div>
    </div>
    ${artifactProvenanceMarkup(artifact, related, kind, url)}
  `;
  const bindPreviewActions = () => {
    artifactPreviewOutput.querySelector("[data-preview-trace-event]")?.addEventListener("click", () => {
      const eventIndex = timelineIndexForEventId(relatedId);
      if (eventIndex >= 0) inspectTimelineEvent(eventIndex).catch((err) => log(String(err), "error"));
    });
    artifactPreviewOutput.querySelector("[data-preview-replay-producer]")?.addEventListener("click", () => {
      const eventIndex = timelineIndexForEventId(relatedId);
      if (eventIndex >= 0) {
        inspectTimelineEvent(eventIndex).catch((err) => log(String(err), "error"));
        return;
      }
      if (relatedStage && activeGraph?.stage_dispatch?.[relatedStage]) {
        replayOutput.innerHTML = `<div class="runtime-replay-preamble"><strong>Replay basis:</strong> artifact ${escapeHtml(artifact.name || artifact.path)} at stage ${escapeHtml(relatedStage)}</div>`;
        dryRunGraph(relatedStage, replayOutput).catch((err) => log(String(err), "error"));
      }
    });
  };
  if (!url) {
    artifactPreviewOutput.innerHTML = `${headerMarkup}<div>Artifact URL is unavailable.</div>`;
    bindPreviewActions();
    return;
  }
  if (kind === "image") {
    artifactPreviewOutput.innerHTML = `
      ${headerMarkup}
      <img class="runtime-artifact-preview-image" src="${escapeHtml(url)}" alt="${escapeHtml(artifact.name || artifact.path)}" />
    `;
    bindPreviewActions();
    return;
  }
  if (kind === "text") {
    const res = await fetch(url);
    const text = await res.text();
    artifactPreviewOutput.innerHTML = `
      ${headerMarkup}
      <pre>${escapeHtml(text.slice(0, 6000))}</pre>
    `;
    bindPreviewActions();
    return;
  }
  artifactPreviewOutput.innerHTML = `
    ${headerMarkup}
    <div>Inline preview is not available for ${escapeHtml(kind)} artifacts.</div>
  `;
  bindPreviewActions();
}

async function loadRunContext(options = {}) {
  const preservedEventId = options.preserveSelectedEventId || selectedTimelineEvent()?.event_id || "";
  const state = await requestJson("/api/state");
  latestStateSnapshot = state;
  currentRunId = state?.state?.run_id || "";
  renderRuntimeHeader(state);
  renderInfraList(state);
  renderGraphExplorer(activeGraph);
  renderDashboardPanels(state);
  if (!currentRunId) {
    renderArtifactLineage();
    renderRunTimeline();
    renderEventLog();
    return;
  }
  const events = await requestJson(`/api/runs/${currentRunId}/events`);
  if (Array.isArray(events.events) && events.events.length) {
    recentRuntimeEvents = events.events.slice(-40).reverse();
    if (preservedEventId) {
      const restoredIndex = timelineIndexForEventId(preservedEventId);
      if (restoredIndex >= 0) selectedTimelineEventIndex = restoredIndex;
    }
    for (const event of recentRuntimeEvents) {
      const stage = eventStage(event);
      if (stage) visitedRuntimeStages.add(stage);
    }
    const activeEvent = recentRuntimeEvents.find((event) => eventUpdatesActiveStage(event));
    if (activeEvent) {
      activeRuntimeStage = activeEvent?.state?.stage || activeEvent?.timestamp_stage || activeEvent?.node_id || activeRuntimeStage;
      if (activeEvent?.payload?.from_stage && activeEvent?.payload?.to_stage) {
        activeRuntimeEdge = { source: String(activeEvent.payload.from_stage), target: String(activeEvent.payload.to_stage) };
      }
    }
  }
  const approvals = await requestJson(`/api/runs/${currentRunId}/approvals`);
  currentApprovals = {
    approvals: Array.isArray(approvals.approvals) ? approvals.approvals : [],
    pending: Array.isArray(approvals.pending) ? approvals.pending : [],
    resolved: Array.isArray(approvals.resolved) ? approvals.resolved : [],
  };
  const artifacts = await requestJson(`/api/runs/${currentRunId}/artifacts`);
  currentArtifacts = Array.isArray(artifacts.artifacts) ? artifacts.artifacts : [];
  renderRuntimeHeader();
  try {
    if (activeGraph) renderGraph(parseGraphEditor());
  } catch (_err) {
    if (activeGraph) renderGraph(activeGraph);
  }
  renderGraphExplorer(activeGraph);
  renderDashboardPanels();
  renderLiveStatus();
  renderRunTimeline();
  renderEventLog();
  renderArtifactLineage();
}

function renderAgentStatusPanel(snapshot = latestStateSnapshot) {
  if (!agentStatusOutput) return;
  const agentStatus = snapshot?.state?.agent_status || {};
  const agents = Array.isArray(snapshot?.agents) ? snapshot.agents : Object.keys(agentStatus);
  if (!agents.length) {
    agentStatusOutput.innerHTML = "<div>No registered agent snapshot.</div>";
    return;
  }
  agentStatusOutput.innerHTML = agents
    .map((agent) => {
      const status = agentStatus[agent] || {};
      const state = status.state || status.status || "idle";
      const summary = status.summary || status.message || status.last_error || "no recent output";
      return `
        <div class="runtime-status-row ${statusBadgeClass(state)}">
          <span>${escapeHtml(agent)}</span>
          <strong>${escapeHtml(state)}</strong>
          <small>${escapeHtml(summary)}</small>
        </div>
      `;
    })
    .join("");
}

function renderDeviceStatusPanel(snapshot = latestStateSnapshot) {
  if (!deviceStatusOutput) return;
  const state = snapshot?.state || {};
  const runtime = snapshot?.runtime || state.run_metadata || {};
  const backend = runtime.backend || state.run_metadata?.backend || {};
  const health = state.device_health || {};
  const resources = systemResources(snapshot);
  const ram = resources.ram || {};
  const gpu = resources.gpu || {};
  const baseRows = Object.entries(health).map(([name, status]) => ({ name, status, detail: "device bridge" }));
  const backendRows = [
    { name: "vLLM / backend", status: backend.active ? "ready" : "idle", detail: backend.label || backend.name || "not selected" },
    { name: "Ollama / NemoClaw", status: backend.name === "ollama" || backend.name === "nemoclaw" ? "ready" : "idle", detail: backend.name || "inactive" },
    { name: "Host RAM", status: ram.status || "unknown", detail: formatRamDetail(ram) },
    { name: "GPU / VRAM", status: gpu.status || "unknown", detail: formatGpuDetail(gpu) },
  ];
  const gpuRows = Array.isArray(gpu.gpus) && gpu.gpus.length > 1
    ? gpu.gpus.slice(0, 4).map((item) => ({
        name: `GPU ${item.index}`,
        status: item.status || gpu.status || "unknown",
        detail: `${item.name || "NVIDIA"} · ${formatGb(item.memory_used_gb)} / ${formatGb(item.memory_total_gb)} · util ${formatResourcePercent(item.utilization_percent)}`,
      }))
    : [];
  const rows = [...baseRows, ...backendRows, ...gpuRows];
  deviceStatusOutput.innerHTML = rows.length
    ? rows.map((row) => `
        <div class="runtime-status-row ${statusBadgeClass(row.status)}">
          <span>${escapeHtml(row.name)}</span>
          <strong>${escapeHtml(row.status || "unknown")}</strong>
          <small>${escapeHtml(row.detail || "")}</small>
        </div>
      `).join("")
    : "<div>No device status snapshot.</div>";
}

function renderMetricsPanel(snapshot = latestStateSnapshot) {
  if (!metricsPanelOutput) return;
  const state = snapshot?.state || {};
  const analysis = latestAnalysisPayload();
  const utm = analysis.utm_metrics || analysis.metrics || {};
  const cae = analysis.cae_metrics || {};
  const evaluation = latestEvaluation();
  const spec = state.current_experiment_spec || {};
  const geometry = spec.geometry || spec.design || {};
  const bo = state.run_metadata?.bo_agent || state.run_metadata?.bo || {};
  const metricEvent = lastEventOfType("metric.updated");
  const tokenEvent = recentRuntimeEvents.find((event) => event.payload?.token_usage || event.payload?.usage) || null;
  const resources = systemResources(snapshot);
  const ram = resources.ram || {};
  const gpu = resources.gpu || {};
  const gpuAgg = gpuAggregate(resources);
  const objective = analysis.objective_score ?? evaluation.objective_score ?? evaluation.score ?? bo.best_score;
  const strength = utm.compressive_strength_MPa ?? utm.strength_MPa ?? cae.equivalent_strength_MPa;
  const density = geometry.relative_density ?? spec.relative_density ?? utm.relative_density;
  const boScore = bo.best_score ?? bo.objective_score ?? bo.last_score ?? objective;
  const latency = recentRuntimeEvents.length ? `${recentRuntimeEvents.length} events` : "n/a";
  const tokens = tokenEvent?.payload?.token_usage?.total_tokens ?? tokenEvent?.payload?.usage?.total_tokens ?? "n/a";
  metricsPanelOutput.innerHTML = `
    <div class="runtime-metric-grid">
      ${metricCard("Objective", formatMetricValue(objective), "latest analysis/evaluation", objective === undefined ? "idle" : "ok")}
      ${metricCard("Strength", formatMetricValue(strength, "MPa"), "UTM/CAE", strength === undefined ? "idle" : "ok")}
      ${metricCard("Density", formatMetricValue(density), "specimen relative density", density === undefined ? "idle" : "ok")}
      ${metricCard("BO Score", formatMetricValue(boScore), "knowledge -> BO", boScore === undefined ? "idle" : "ok")}
      ${metricCard("Latency", latency, "recent runtime buffer", "info")}
      ${metricCard("Tokens", compactJson(tokens), "last token usage event", tokens === "n/a" ? "idle" : "ok")}
      ${metricCard("RAM", formatResourcePercent(ram.used_percent), formatRamDetail(ram), resourceMetricLevel(ram.status))}
      ${metricCard("VRAM", formatResourcePercent(gpuAgg.memory_used_percent), formatGpuDetail(gpu), resourceMetricLevel(gpu.status))}
    </div>
    ${metricEvent ? `<pre>${escapeHtml(JSON.stringify(metricEvent.payload || metricEvent, null, 2).slice(0, 1200))}</pre>` : ""}
  `;
}

function derivedPendingApprovalItems() {
  if (Array.isArray(currentApprovals.pending) && currentApprovals.pending.length) {
    return currentApprovals.pending.map((item) => ({
      approval_id: item.approval_id,
      title: item.title,
      stage: item.stage,
      reason: item.reason,
      status: item.status || "pending",
    }));
  }
  const requested = recentRuntimeEvents.filter((event) => {
    const type = event.type || event.event_type || "";
    const payload = event.payload || {};
    return type === "approval.requested" || payload.requires_human_approval || payload.requires_approval || payload.status === "waiting_approval";
  });
  const resolvedIds = new Set(
    recentRuntimeEvents
      .filter((event) => (event.type || event.event_type) === "approval.resolved")
      .map((event) => event.payload?.approval_id || event.payload?.id || event.event_id)
      .filter(Boolean),
  );
  return requested
    .filter((event) => {
      const id = event.payload?.approval_id || event.payload?.id || event.event_id;
      return !id || !resolvedIds.has(id);
    })
    .map((event) => {
      const payload = event.payload || {};
      return {
        approval_id: payload.approval_id || payload.id || event.event_id,
        title: payload.title || event.message || "Approval required",
        stage: payload.stage || event.state?.stage || event.node_id || "runtime",
        reason: payload.reason || payload.failure_code || payload.status || "pending",
        status: "pending",
      };
    });
}

function normalizeModuleIdRef(value = "") {
  return String(value || "").replace(/^modules\//, "").trim();
}

function moduleCatalogById() {
  return new Map(availableModules.map((module) => [String(module.id || ""), module]));
}

function runtimeReadinessStatus(graph = activeGraph, snapshot = latestStateSnapshot) {
  const draft = graph || activeGraph || {};
  const nodes = Array.isArray(draft.nodes) ? draft.nodes : [];
  const edges = Array.isArray(draft.edges) ? draft.edges : [];
  const handlerSet = new Set(availableHandlers);
  const moduleMap = moduleCatalogById();
  const handlerCatalogReady = availableHandlers.length > 0;
  const moduleCatalogReady = availableModules.length > 0;
  let routes = [];
  try {
    routes = logicalGraphEdges(draft);
  } catch (_err) {
    routes = [];
  }
  const nodeByIdOrStage = nodeMapByStageOrId(nodes);
  const entryNode = nodeByIdOrStage.get(draft.entry_node || "");
  const entryStages = new Set([draft.entry_node, entryNode?.id, entryNode ? nodeStage(entryNode) : ""].filter(Boolean));
  const finishRefs = Array.isArray(draft.finish_nodes) ? draft.finish_nodes : [];
  const terminalRefs = Array.isArray(draft.terminal_stages) ? draft.terminal_stages : [];
  const terminalStages = new Set(["complete", "error", "step_complete"]);
  [...finishRefs, ...terminalRefs].forEach((ref) => {
    if (!ref) return;
    terminalStages.add(ref);
    const node = nodeByIdOrStage.get(ref);
    if (node) {
      terminalStages.add(node.id);
      terminalStages.add(nodeStage(node));
    }
  });
  const agentLikeNodes = nodes.filter((node) => ["agent", "module"].includes(String(node.kind || "")) || node.module_id);
  const missingHandlers = handlerCatalogReady ? nodes.filter((node) => node.handler && !handlerSet.has(node.handler)) : [];
  const invalidHandlers = handlerCatalogReady ? nodes.filter((node) => node.handler && handlerSet.has(node.handler) && handlerMetadataStatus(node.handler).kind === "error") : [];
  const missingModules = moduleCatalogReady ? agentLikeNodes.filter((node) => node.module_id && !moduleMap.has(normalizeModuleIdRef(node.module_id))) : [];
  const pendingModules = moduleCatalogReady
    ? agentLikeNodes
      .map((node) => ({ node, module: moduleMap.get(normalizeModuleIdRef(node.module_id)) }))
      .filter(({ module }) => Boolean(module?.pending_handler_registration))
    : [];
  const moduleHandlerIssues = handlerCatalogReady && moduleCatalogReady
    ? agentLikeNodes
      .map((node) => ({ node, module: moduleMap.get(normalizeModuleIdRef(node.module_id)) }))
      .filter(({ module }) => module?.handler && !handlerSet.has(module.handler))
    : [];
  const moduleSignatureIssues = handlerCatalogReady && moduleCatalogReady
    ? agentLikeNodes
      .map((node) => ({ node, module: moduleMap.get(normalizeModuleIdRef(node.module_id)) }))
      .filter(({ module }) => module?.handler && handlerSet.has(module.handler) && handlerMetadataStatus(module.handler).kind === "error")
    : [];
  const catalogWarnings = [];
  if (!handlerCatalogReady) catalogWarnings.push(["handlers", "handler catalog pending"]);
  if (!moduleCatalogReady) catalogWarnings.push(["modules", "module catalog pending"]);
  const routeIssues = agentLikeNodes.filter((node) => {
    const stage = nodeStage(node);
    if (!stage || terminalStages.has(stage) || terminalStages.has(node.id)) return false;
    const outgoing = routes.some((edge) => edge.sourceStage === stage);
    const incoming = routes.some((edge) => edge.targetStage === stage);
    const needsIncoming = !entryStages.has(stage) && !entryStages.has(node.id);
    const needsOutgoing = !terminalStages.has(stage) && !terminalStages.has(node.id);
    return needsOutgoing && !outgoing || needsIncoming && !incoming;
  });
  const state = snapshot?.state || {};
  const deviceHealth = state.device_health || {};
  const deviceWarnings = Object.entries(deviceHealth).filter(([, status]) => String(status) !== "ready");
  const preflight = livePreflightStatus(draft, runModeSelect?.value || "test");
  const moduleTab = draft?.metadata?.ide_tab_kind === "module" || Boolean(preflight.moduleTab);
  let validationOk = Boolean(activationEvidence.validation?.ok && !activationEvidence.dirty);
  let dryRunOk = Boolean(activationEvidence.dry_run?.ok && !activationEvidence.dirty);
  let compileOk = Boolean(activationEvidence.compile?.ok && !activationEvidence.dirty);
  let modulePreflight = null;
  if (moduleTab) {
    const moduleId = draft?.metadata?.module_id || activeModuleId || "module";
    try {
      modulePreflight = moduleSavePreflightStatus(moduleId, modulePayloadForGraphDraft(draft));
      validationOk = Boolean(modulePreflight.validationOk);
      dryRunOk = Boolean(modulePreflight.dryRunOk);
      compileOk = validationOk;
    } catch (err) {
      modulePreflight = { ok: false, validationOk: false, dryRunOk: false, reason: String(err?.message || err || "module preflight unavailable") };
      validationOk = false;
      dryRunOk = false;
      compileOk = false;
    }
  }
  const hardIssues = [...missingHandlers, ...invalidHandlers, ...missingModules, ...moduleHandlerIssues, ...moduleSignatureIssues, ...routeIssues];
  const warnings = [...pendingModules, ...deviceWarnings, ...catalogWarnings];
  const catalogsReady = handlerCatalogReady && moduleCatalogReady;
  const readyForTest = catalogsReady && hardIssues.length === 0 && validationOk && dryRunOk && preflight.draftClean && !moduleTab;
  const moduleDraftReady = moduleTab && hardIssues.length === 0 && validationOk && dryRunOk;
  const readyForLive = readyForTest && preflight.gateOk && (!preflight.liveMode || preflight.confirmed);
  const status = moduleTab
    ? hardIssues.length ? "error" : warnings.length || !moduleDraftReady ? "warn" : "ok"
    : hardIssues.length ? "error" : warnings.length || !readyForTest ? "warn" : "ok";
  return {
    status,
    moduleTab,
    moduleDraftReady,
    modulePreflight,
    handlerCatalogReady,
    moduleCatalogReady,
    catalogWarnings,
    nodes,
    edges,
    routes,
    agentLikeNodes,
    missingHandlers,
    invalidHandlers,
    missingModules,
    pendingModules,
    moduleHandlerIssues,
    moduleSignatureIssues,
    routeIssues,
    deviceWarnings,
    validationOk,
    compileOk,
    dryRunOk,
    readyForTest,
    readyForLive,
    preflight,
  };
}

function runtimeReadinessNodeIssueMap(status = runtimeReadinessStatus()) {
  const map = new Map();
  const add = (node, level, title, detail = "") => {
    if (!node?.id) return;
    const current = map.get(node.id) || { node, level: "ok", items: [] };
    if (level === "error" || current.level !== "error" && level === "warn") current.level = level;
    current.items.push({ level, title, detail });
    map.set(node.id, current);
  };
  status.missingHandlers.forEach((node) => add(node, "error", "handler", node.handler || "missing handler"));
  status.invalidHandlers.forEach((node) => add(node, "error", "handler signature", handlerMetadataStatus(node.handler).detail));
  status.missingModules.forEach((node) => add(node, "error", "module", node.module_id || "missing module"));
  status.moduleHandlerIssues.forEach(({ node, module }) => add(node, "error", "module handler", module?.handler || "unregistered"));
  status.moduleSignatureIssues.forEach(({ node, module }) => add(node, "error", "module signature", handlerMetadataStatus(module?.handler).detail));
  status.routeIssues.forEach((node) => add(node, "error", "route", "incoming/outgoing route coverage"));
  status.pendingModules.forEach(({ node, module }) => add(node, "warn", "registration", module?.id || node.module_id || "pending"));
  return map;
}

function runtimeReadinessIssueLabel(issue) {
  if (!issue || !issue.items?.length) return "ready";
  const first = issue.items[0];
  const extra = Math.max(0, issue.items.length - 1);
  return `${first.title}${extra ? ` +${extra}` : ""}`;
}

function runtimeReadinessIssueTitle(issue) {
  if (!issue || !issue.items?.length) return "No readiness issue detected.";
  return issue.items.map((item) => `${item.level.toUpperCase()}: ${item.title}${item.detail ? ` - ${item.detail}` : ""}`).join("\n");
}

function runtimeReadinessIssueRows(status) {
  const rows = [];
  status.missingHandlers.slice(0, 4).forEach((node) => rows.push({ level: "error", kind: "handler", node, title: "Unregistered graph handler", detail: `${node.id}: ${node.handler}` }));
  status.invalidHandlers.slice(0, 4).forEach((node) => rows.push({ level: "error", kind: "handler", node, title: "Invalid graph handler signature", detail: `${node.id}: ${handlerMetadataStatus(node.handler).detail}` }));
  status.missingModules.slice(0, 4).forEach((node) => rows.push({ level: "error", kind: "module", node, title: "Missing module config", detail: `${node.id}: ${node.module_id}` }));
  status.moduleHandlerIssues.slice(0, 4).forEach(({ node, module }) => rows.push({ level: "error", kind: "module_handler", node, title: "Unregistered module handler", detail: `${module?.id || node.id}: ${module?.handler || "handler"}` }));
  status.moduleSignatureIssues.slice(0, 4).forEach(({ node, module }) => rows.push({ level: "error", kind: "module_handler", node, title: "Invalid module handler signature", detail: `${module?.id || node.id}: ${handlerMetadataStatus(module?.handler).detail}` }));
  status.routeIssues.slice(0, 4).forEach((node) => rows.push({ level: "error", kind: "route", node, title: "Route coverage gap", detail: `${nodeStage(node)} requires incoming and outgoing logical transition routes` }));
  status.pendingModules.slice(0, 4).forEach(({ node, module }) => rows.push({ level: "warn", kind: "pending_registration", node, title: "Pending handler registration", detail: `${module?.id || node.id} needs code integration before live execution` }));
  status.deviceWarnings.slice(0, 4).forEach(([name, value]) => rows.push({ level: "warn", title: "Device/backend warning", detail: `${name}: ${value}` }));
  if (!status.handlerCatalogReady) rows.push({ level: "warn", title: "Handler catalog loading", detail: "Waiting for /api/handlers before declaring handler coverage." });
  if (!status.moduleCatalogReady) rows.push({ level: "warn", title: "Module catalog loading", detail: "Waiting for /api/modules before declaring module linkage." });
  if (!status.validationOk) rows.push({ level: "warn", action: "validate", title: "Validation evidence missing", detail: "Validate the exact current draft before save/run." });
  if (!status.dryRunOk) rows.push({ level: "warn", action: "dry-run", title: "Dry-run evidence missing", detail: "Run a no-hardware dry-run for the exact current draft." });
  if (!status.moduleTab && !status.preflight.draftClean) rows.push({ level: "warn", action: "open-run-launcher", title: "Unsaved editor draft present", detail: "Save Version or discard draft changes before saved test/live execution." });
  if (!status.moduleTab && !status.preflight.gateOk) rows.push({ level: "idle", action: "record-gate", title: "Live gate not recorded", detail: "Required only before live execution." });
  return rows;
}

function runtimeReadinessCard(label, value, detail, level = "info") {
  return `
    <span class="runtime-readiness-kpi ${escapeHtml(level)}">
      <small>${escapeHtml(label)}</small>
      <strong>${escapeHtml(value)}</strong>
      <em>${escapeHtml(detail)}</em>
    </span>
  `;
}

function refreshRuntimeReadinessViews() {
  let graph = activeGraph;
  try {
    graph = parseGraphEditor();
  } catch (_err) {
    graph = activeGraph;
  }
  if (graph) renderGraph(graph);
  else renderRuntimeReadinessPanel();
}

function runtimeReadinessHandlerCard(status) {
  if (!status.handlerCatalogReady) {
    return runtimeReadinessCard("Handlers", "loading", "handler catalog pending", "warn");
  }
  return runtimeReadinessCard(
    "Handlers",
    status.missingHandlers.length ? `${status.missingHandlers.length} missing` : status.invalidHandlers.length ? `${status.invalidHandlers.length} invalid` : "registered",
    `${availableHandlers.length} allowlisted`,
    status.missingHandlers.length || status.invalidHandlers.length ? "error" : "ok",
  );
}

function runtimeReadinessModuleCard(status) {
  if (!status.moduleCatalogReady) {
    return runtimeReadinessCard("Modules", "loading", "module catalog pending", "warn");
  }
  return runtimeReadinessCard(
    "Modules",
    `${status.agentLikeNodes.length - status.missingModules.length}/${status.agentLikeNodes.length}`,
    status.pendingModules.length ? `${status.pendingModules.length} pending registration` : "linked",
    status.missingModules.length ? "error" : status.pendingModules.length ? "warn" : "ok",
  );
}

function renderRuntimeReadinessPanel(snapshot = latestStateSnapshot) {
  if (!runtimeReadinessOutput) return;
  const status = runtimeReadinessStatus(activeGraph, snapshot);
  const issues = runtimeReadinessIssueRows(status);
  const headline = status.moduleTab
    ? status.moduleDraftReady
      ? "Module draft is ready to save after validation and dry-run."
      : status.status === "error"
        ? "Fix module blocking issues before saving this module."
        : "Validate and dry-run this module draft before saving."
    : !status.preflight.draftClean
      ? "Save or discard the editor draft before running the saved active graph."
      : status.status === "ok"
        ? "Executable graph is ready for saved test execution."
        : status.status === "error"
          ? "Fix graph/module blocking issues before execution."
          : "Complete validation/dry-run evidence before relying on this graph.";
  const liveGateCard = status.moduleTab
    ? runtimeReadinessCard("Live Gate", "n/a", "module draft only", "idle")
    : runtimeReadinessCard("Live Gate", status.preflight.gateOk ? "recorded" : "needed", status.preflight.liveMode ? "required now" : "required for live", status.preflight.gateOk ? "ok" : "idle");
  const actionButtons = status.moduleTab
    ? `
        <button class="btn tiny" type="button" data-readiness-action="validate">Validate Module</button>
        <button class="btn tiny" type="button" data-readiness-action="dry-run">Dry Run Module</button>
        <button class="btn tiny" type="button" data-readiness-action="save-module">Save Module</button>
      `
    : `
        <button class="btn tiny" type="button" data-readiness-action="validate">Validate</button>
        <button class="btn tiny" type="button" data-readiness-action="dry-run">Dry Run</button>
        <button class="btn tiny" type="button" data-readiness-action="open-run-launcher">Run Launcher</button>
      `;
  runtimeReadinessOutput.innerHTML = `
    <section class="runtime-readiness-card ${escapeHtml(status.status)}">
      <div class="runtime-readiness-head">
        <span>
          <strong>${escapeHtml(headline)}</strong>
          <small>${escapeHtml(status.preflight.graphId || activeGraph?.id || "graph")} · ${escapeHtml(status.preflight.mode || "test")}</small>
        </span>
        <em>${escapeHtml(status.readyForLive ? "live-ready" : status.readyForTest ? "test-ready" : status.status)}</em>
      </div>
      <div class="runtime-readiness-kpis">
        ${runtimeReadinessCard("Graph", `${status.nodes.length} nodes / ${status.edges.length} edges`, `${status.routes.length} logical route(s)`, status.routeIssues.length ? "error" : "ok")}
        ${runtimeReadinessHandlerCard(status)}
        ${runtimeReadinessModuleCard(status)}
        ${runtimeReadinessCard("Evidence", `${status.validationOk ? "V" : "-"}${status.compileOk ? "C" : "-"}${status.dryRunOk ? "D" : "-"}`, status.moduleTab ? status.modulePreflight?.reason || "module evidence" : status.preflight.draftClean ? "draft clean" : "draft changed", status.validationOk && status.dryRunOk ? "ok" : "warn")}
        ${liveGateCard}
      </div>
      <div class="runtime-readiness-actions">
        ${actionButtons}
      </div>
      <div class="runtime-readiness-issues">
        ${issues.length ? issues.slice(0, 8).map((issue) => `
          <button type="button" class="runtime-readiness-issue ${escapeHtml(issue.level)}" ${issue.node ? `data-readiness-node="${escapeHtml(issue.node.id)}" data-readiness-kind="${escapeHtml(issue.kind || "node")}"` : issue.action ? `data-readiness-action="${escapeHtml(issue.action)}"` : ""}>
            <span class="runtime-timeline-severity-dot ${escapeHtml(issue.level)}"></span>
            <strong>${escapeHtml(issue.title)}</strong>
            <small>${escapeHtml(issue.detail)}</small>
            ${issue.node ? `<em>${escapeHtml(issue.kind === "route" ? "focus route editor" : ["module", "module_handler", "pending_registration"].includes(issue.kind || "") ? "focus module tools" : "focus node inspector")}</em>` : ""}
          </button>
        `).join("") : `<div class="runtime-readiness-empty">No blocking readiness issue detected.</div>`}
      </div>
    </section>
  `;
  runtimeReadinessOutput.querySelectorAll("[data-readiness-node]").forEach((el) => {
    el.addEventListener("click", () => focusRuntimeReadinessIssue(el.getAttribute("data-readiness-node") || "", el.getAttribute("data-readiness-kind") || ""));
  });
  runtimeReadinessOutput.querySelectorAll("[data-readiness-action]").forEach((el) => {
    el.addEventListener("click", () => executeRuntimeReadinessAction(el.getAttribute("data-readiness-action") || ""));
  });
}

function executeRuntimeReadinessAction(action = "") {
  if (action === "validate") return validateGraph().catch((err) => log(String(err), "error"));
  if (action === "dry-run") return dryRunGraph("idle", dryRunOutput).catch((err) => log(String(err), "error"));
  if (action === "save-module") return saveModule({ enforcePreflight: true }).catch((err) => log(String(err), "error"));
  if (action === "record-gate") return recordActiveDryRunGate().catch((err) => log(String(err), "error"));
  if (action === "open-run-launcher" && runLauncherDrawer) {
    runLauncherDrawer.open = true;
    runLauncherDrawer.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  return undefined;
}

function renderApprovalQueue(snapshot = latestStateSnapshot) {
  if (!approvalQueueOutput) return;
  const openItems = derivedPendingApprovalItems();
  const state = snapshot?.state || {};
  const liveUnsafe = state.mode === "live" && state.stage && state.stage !== "idle" && !state.is_paused;
  if (!openItems.length) {
    approvalQueueOutput.innerHTML = `
      <div class="runtime-approval-empty">No pending human approval request.</div>
      <div class="runtime-status-row ${liveUnsafe ? "warn" : "ok"}">
        <span>Live safety gate</span>
        <strong>${escapeHtml(liveUnsafe ? "monitor" : "clear")}</strong>
        <small>${escapeHtml(liveUnsafe ? "live run is active; watch device gates" : "no unresolved approval event")}</small>
      </div>
    `;
    return;
  }
  approvalQueueOutput.innerHTML = openItems
    .map((item) => `
      <div class="runtime-approval-item" data-approval-item-id="${escapeHtml(item.approval_id)}">
        <strong>${escapeHtml(item.title || "Approval required")}</strong>
        <span>${escapeHtml(item.stage || "runtime")}</span>
        <small>${escapeHtml(item.reason || item.status || "pending")}</small>
        <div class="runtime-approval-actions">
          <button type="button" class="btn tiny" data-approval-decision="approved" data-approval-id="${escapeHtml(item.approval_id)}">Approve</button>
          <button type="button" class="btn tiny danger" data-approval-decision="rejected" data-approval-id="${escapeHtml(item.approval_id)}">Reject</button>
        </div>
      </div>
    `)
    .join("");
  approvalQueueOutput.querySelectorAll("[data-approval-id]").forEach((el) => {
    el.addEventListener("click", () => resolveApproval(el.getAttribute("data-approval-id") || "", el.getAttribute("data-approval-decision") || "approved"));
  });
}

function renderDashboardPanels(snapshot = latestStateSnapshot) {
  renderRuntimeReadinessPanel(snapshot);
  renderAgentStatusPanel(snapshot);
  renderDeviceStatusPanel(snapshot);
  renderMetricsPanel(snapshot);
  renderApprovalQueue(snapshot);
}

function renderLiveStatus() {
  const events = recentRuntimeEvents.slice(0, 8);
  const current = activeRuntimeStage || latestStateSnapshot?.state?.stage || "idle";
  const activeModuleStep = latestStateSnapshot?.state?.run_metadata?.active_module_step || {};
  liveStatusOutput.innerHTML = `
    <div><strong>active stage:</strong> ${escapeHtml(current)}</div>
    <div><strong>active edge:</strong> ${escapeHtml(activeRuntimeEdge ? `${activeRuntimeEdge.source} -> ${activeRuntimeEdge.target}` : "none")}</div>
    <div><strong>active module step:</strong> ${escapeHtml(activeModuleStep.step?.id || activeModuleStep.step_id || "none")}</div>
    <div><strong>visited:</strong> ${escapeHtml(Array.from(visitedRuntimeStages).join(" -> ") || "none")}</div>
    <hr />
    ${events
      .map((event) => `<div><strong>${escapeHtml(event.event_type || event.type || "event")}</strong> ${escapeHtml(event.message || "")}</div>`)
      .join("")}
  `;
}

function mergeRuntimeEventState(event) {
  const eventState = event?.state && typeof event.state === "object" ? event.state : null;
  if (!eventState) return;
  const previousState = latestStateSnapshot?.state && typeof latestStateSnapshot.state === "object" ? latestStateSnapshot.state : {};
  const previousMetadata = previousState.run_metadata && typeof previousState.run_metadata === "object" ? previousState.run_metadata : {};
  const eventMetadata = eventState.run_metadata && typeof eventState.run_metadata === "object" ? eventState.run_metadata : {};
  latestStateSnapshot = {
    ...(latestStateSnapshot || {}),
    state: {
      ...previousState,
      ...eventState,
      run_metadata: {
        ...previousMetadata,
        ...eventMetadata,
      },
    },
  };
}

function eventUpdatesRuntimeState(event) {
  const type = eventTypeName(event);
  if (type.startsWith("graph.") || type.startsWith("ide.")) return false;
  return Boolean(event?.state && typeof event.state === "object");
}

function eventUpdatesActiveStage(event) {
  const type = eventTypeName(event);
  if (type.startsWith("graph.") || type.startsWith("ide.") || type.startsWith("artifact.")) return false;
  return true;
}

function consumeRuntimeEvent(event) {
  const eventType = event.event_type || event.type || "event";
  if (eventUpdatesRuntimeState(event)) mergeRuntimeEventState(event);
  recentRuntimeEvents.unshift(event);
  if (selectedTimelineEventIndex >= 0) selectedTimelineEventIndex = Math.min(selectedTimelineEventIndex + 1, 39);
  recentRuntimeEvents = recentRuntimeEvents.slice(0, 40);
  const stateStage = event?.state?.stage || event?.timestamp_stage || event?.node_id || "";
  if (stateStage) {
    visitedRuntimeStages.add(String(stateStage));
    if (eventUpdatesActiveStage(event)) activeRuntimeStage = String(stateStage);
  }
  if (event?.payload?.from_stage && event?.payload?.to_stage) {
    activeRuntimeEdge = { source: String(event.payload.from_stage), target: String(event.payload.to_stage) };
  }
  if (["run_complete", "run_error", "run_stop"].includes(eventType)) {
    activeRuntimeStage = event?.state?.stage || activeRuntimeStage;
  }
  renderRuntimeHeader();
  renderGraphExplorer(activeGraph);
  renderDashboardPanels();
  renderLiveStatus();
  renderRunTimeline();
  renderEventLog();
  if (["artifact.created", "approval.requested", "approval.resolved"].includes(event.type || event.event_type) && currentRunId) {
    loadRunContext().catch((err) => log(String(err), "error"));
  }
  if (activeGraph) renderGraph(parseGraphEditor());
}

async function loadRecentEvents() {
  const data = await requestJson("/api/events/recent");
  const incoming = Array.isArray(data.events) ? data.events : [];
  for (const event of incoming.slice(-40)) {
    const stage = event?.state?.stage || event?.timestamp_stage || event?.node_id;
    if (stage) visitedRuntimeStages.add(String(stage));
  }
  if (incoming.length) {
    const latest = incoming[incoming.length - 1];
    activeRuntimeStage = latest?.state?.stage || latest?.timestamp_stage || latest?.node_id || activeRuntimeStage;
    recentRuntimeEvents = incoming.slice(-40).reverse();
  }
  renderRuntimeHeader();
  renderGraphExplorer(activeGraph);
  renderDashboardPanels();
  renderLiveStatus();
  renderRunTimeline();
  renderEventLog();
}

async function resolveApproval(approvalId, decision) {
  if (!currentRunId || !approvalId) {
    log("Approval resolve failed: missing run or approval id.", "error");
    return;
  }
  const result = await requestJson(`/api/runs/${currentRunId}/approvals/${encodeURIComponent(approvalId)}/resolve`, {
    method: "POST",
    body: JSON.stringify({ decision, operator: "runtime_ide", note: "Resolved from Runtime IDE" }),
  });
  currentApprovals = {
    approvals: Array.isArray(result.approvals) ? result.approvals : [],
    pending: Array.isArray(result.pending) ? result.pending : [],
    resolved: Array.isArray(result.resolved) ? result.resolved : [],
  };
  log(`Approval ${decision}: ${approvalId}`, result.ok ? "ok" : "error");
  const selectedEventId = selectedTimelineEvent()?.event_id || result.approval_id || "";
  await loadRunContext({ preserveSelectedEventId: selectedEventId });
  renderSelectedEventDetail();
}

async function controlRuntimeRun(action) {
  if (!currentRunId) {
    log("No active run id is available.", "error");
    return;
  }
  const result = await requestJson(`/api/runs/${currentRunId}/${action}`, { method: "POST" });
  log(`Runtime ${action}: ${result.ok === false ? "failed" : "ok"}`, result.ok === false ? "error" : "ok");
  await loadRunContext();
}

function handleRuntimeIdeKeydown(event) {
  if (event.key === "Escape" && (edgeDrag || edgeConnectDraft || edgeConnectMode)) {
    event.preventDefault();
    cancelPortConnection("Connection cancelled with Escape.");
  }
}


function openModuleManagementTool(event) {
  event?.preventDefault?.();
  const opened = window.open("/module-management", "_blank");
  if (opened) {
    opened.opener = null;
    opened.focus?.();
  } else {
    window.location.assign("/module-management");
  }
  return false;
}

document.addEventListener("click", (event) => {
  const trigger = event.target?.closest?.("[data-open-module-management]");
  if (trigger) {
    openModuleManagementTool(event);
  }
});
document.addEventListener("keydown", handleRuntimeIdeKeydown);

function openSettingsFocus() {
  graphJson.scrollIntoView({ behavior: "smooth", block: "center" });
  graphJson.focus();
  log("Settings focus moved to graph/module config editors.", "ok");
}

function connectEventStream() {
  if (!window.EventSource) return;
  const source = new EventSource("/api/events/stream");
  source.addEventListener("update", (msg) => {
    try {
      consumeRuntimeEvent(JSON.parse(msg.data));
    } catch (err) {
      log(`SSE parse failed: ${err}`, "error");
    }
  });
  source.onerror = () => {
    source.close();
    setTimeout(connectEventStream, 1400);
  };
}

async function boot() {
  try {
    await loadGraph();
    await loadHandlers();
    await loadTools();
    await loadModules();
    await loadRecentEvents();
    await loadRunContext();
    connectEventStream();
  } catch (err) {
    setStatus("warn", "IDE Error", String(err));
    log(String(err), "error");
  }
}

document.getElementById("ide-load-btn").addEventListener("click", () => loadGraph(graphSelect?.value || "").catch((err) => log(String(err), "error")));
graphSelect?.addEventListener("change", () => loadGraph(graphSelect.value).catch((err) => log(String(err), "error")));
document.getElementById("ide-validate-btn").addEventListener("click", () => validateGraph().catch((err) => log(String(err), "error")));
document.getElementById("ide-compile-btn").addEventListener("click", () => compileGraph().catch((err) => log(String(err), "error")));
document.getElementById("ide-dry-run-btn").addEventListener("click", () => dryRunGraph("idle", dryRunOutput).catch((err) => log(String(err), "error")));
exportYamlBtn.addEventListener("click", () => exportGraphYaml().catch((err) => log(String(err), "error")));
importYamlBtn.addEventListener("click", () => yamlImportFile.click());
yamlImportFile.addEventListener("change", () => importGraphYamlFile(yamlImportFile.files?.[0]).catch((err) => log(String(err), "error")));
document.getElementById("ide-save-btn").addEventListener("click", () => saveGraph().catch((err) => log(String(err), "error")));
graphVersionsBtn?.addEventListener("click", () => loadGraphVersions().catch((err) => log(String(err), "error")));
document.getElementById("ide-module-load-btn").addEventListener("click", () => openModuleGraphTab(moduleSelect.value || activeModuleId).catch((err) => log(String(err), "error")));
document.getElementById("ide-module-validate-btn").addEventListener("click", () => validateModule(dryRunOutput).catch((err) => log(String(err), "error")));
document.getElementById("ide-module-dry-run-btn").addEventListener("click", () => dryRunModule(dryRunOutput).catch((err) => log(String(err), "error")));
document.getElementById("ide-module-save-btn").addEventListener("click", () => saveModule({ enforcePreflight: true }).catch((err) => log(String(err), "error")));
transitionApplyBtn.addEventListener("click", applyTransitionEdit);
transitionConditionPreset?.addEventListener("change", updateTransitionConditionPlaceholder);
transitionSource?.addEventListener("change", handleTransitionSourceChange);
transitionTarget?.addEventListener("change", updateTransitionConditionPlaceholder);
edgeConnectBtn.addEventListener("click", toggleEdgeConnectMode);
edgeDeleteBtn.addEventListener("click", deleteSelectedEdge);
zoomOutBtn.addEventListener("click", () => { graphZoom = Math.max(0.36, graphZoom - 0.1); renderGraph(parseGraphEditor()); });
fitGraphBtn?.addEventListener("click", fitGraphToCanvas);
zoomResetBtn.addEventListener("click", () => { graphZoom = 1; renderGraph(parseGraphEditor()); });
zoomInBtn.addEventListener("click", () => { graphZoom = Math.min(1.8, graphZoom + 0.1); renderGraph(parseGraphEditor()); });
recordLiveGateBtn?.addEventListener("click", () => recordActiveDryRunGate().catch((err) => { setRunLauncherStatus("warn", "gate failed", `<pre>${escapeHtml(String(err))}</pre>`); log(String(err), "error"); }));
runTestBtn?.addEventListener("click", () => startRuntimeGraphFromIde("test").catch((err) => log(String(err), "error")));
runLiveBtn?.addEventListener("click", () => startRuntimeGraphFromIde("live").catch((err) => log(String(err), "error")));
runLiveConfirmInput?.addEventListener("change", () => renderLivePreflight(runModeSelect?.value || "test"));
runModeSelect?.addEventListener("change", () => {
  const mode = runModeSelect.value || "test";
  renderLivePreflight(mode);
  setRunLauncherStatus("idle", mode, `<div class="runtime-run-message idle">Selected run mode: ${escapeHtml(mode)}. Preflight status remains authoritative.</div>`);
});
pauseRunBtn?.addEventListener("click", () => controlRuntimeRun("pause").catch((err) => log(String(err), "error")));
resumeRunBtn?.addEventListener("click", () => controlRuntimeRun("resume").catch((err) => log(String(err), "error")));
stopRunBtn?.addEventListener("click", () => controlRuntimeRun("stop").catch((err) => log(String(err), "error")));
settingsBtn?.addEventListener("click", openSettingsFocus);
nodeSearchInput?.addEventListener("input", () => { nodeSearchQuery = nodeSearchInput.value || ""; renderGraphExplorer(activeGraph); });
moduleSelect.addEventListener("change", () => openModuleGraphTab(moduleSelect.value || activeModuleId).catch((err) => log(String(err), "error")));
graphCanvas?.addEventListener("dragover", (event) => {
  if (event.dataTransfer?.types?.includes("application/x-atr-module")) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }
});
graphCanvas?.addEventListener("drop", handleCanvasCatalogDrop);
designerPythonFileInput?.addEventListener("change", () => fillDesignerFromFile(designerPythonFileInput.files?.[0]));
designerCreateBtn?.addEventListener("click", () => createModuleFromDesigner().catch((err) => {
  setDesignerStatus(String(err), "error");
  log(String(err), "error");
}));
graphJson.addEventListener("change", () => {
  try {
    const graph = parseGraphEditor();
    if (graph.metadata?.ide_tab_kind === "module") applyModuleGraphDraftToEditor(graph);
    markActiveTabDirty(graph);
    renderGraph(graph);
  } catch (err) {
    log(`Graph JSON parse failed: ${err}`, "error");
  }
});
moduleJson.addEventListener("change", () => {
  try {
    const payload = parseModuleEditor();
    setModuleJson(payload);
    renderModuleGraph(payload);
    const moduleId = (payload.module || payload || {}).id || activeModuleId;
    markModulePreflightDirty(moduleId, "raw module JSON changed");
    refreshOpenModuleGraphTab(moduleId);
  } catch (err) {
    log(`Module JSON parse failed: ${err}`, "error");
  }
});

eventFilterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    eventLogFilter = button.getAttribute("data-event-filter") || "all";
    renderEventLog();
  });
});

setInterval(() => renderRuntimeHeader(), 1000);

renderEventLog();
boot();
