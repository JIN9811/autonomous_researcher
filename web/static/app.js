/*
File purpose:
- Frontend runtime for controlling runs and visualizing live loop events.

Key classes/functions:
- refreshState
- connectEventStream
- renderTimeline

Inputs/outputs:
- Input: API responses and SSE events
- Output: updated dashboard DOM state

Dependencies:
- Fetch API
- EventSource

Modification guide:
- Safe places to edit: panel rendering and filter behavior
- Risky places to edit: endpoint URLs and payload schema assumptions
- Related files: app/main.py, web/templates/index.html
*/

const timelineEl = document.getElementById("timeline");
const logViewerEl = document.getElementById("log-viewer");
const agentStatusEl = document.getElementById("agent-status");
const deviceStatusEl = document.getElementById("device-status");
const runIndicatorEl = document.getElementById("run-indicator");
const metricStageEl = document.getElementById("metric-stage");
const metricModeEl = document.getElementById("metric-mode");
const metricLoopEl = document.getElementById("metric-loop");
const levelFilterEl = document.getElementById("log-level-filter");
const graphStageIndicatorEl = document.getElementById("graph-stage-indicator");
const langGraphNodesEl = document.getElementById("langgraph-nodes");
const langGraphCellsEl = document.getElementById("langgraph-cells");
const langGraphShellEl = document.querySelector(".langgraph-shell");
const runtimeMapLegendEl = document.getElementById("runtime-map-legend");
const backendStatusDotEl = document.getElementById("backend-status-dot");
const backendStatusLabelEl = document.getElementById("backend-status-label");
const backendStatusDetailEl = document.getElementById("backend-status-detail");
const nemoclawStatusDotEl = document.getElementById("nemoclaw-status-dot");
const nemoclawStatusLabelEl = document.getElementById("nemoclaw-status-label");
const nemoclawStatusDetailEl = document.getElementById("nemoclaw-status-detail");
const modelOrchestratorChipEl = document.getElementById("model-orchestrator-chip");
const modelE4BChipEl = document.getElementById("model-e4b-chip");
const modelLoadButtons = Array.from(document.querySelectorAll(".model-load-btn"));
const modelUnloadButtons = Array.from(document.querySelectorAll(".model-unload-btn"));
const modelLoadDots = Array.from(document.querySelectorAll("[data-model-dot]"));

const modeSelect = document.getElementById("mode-select");
const backendSelect = document.getElementById("backend-select");
const goalInput = document.getElementById("goal-input");
const faultInput = document.getElementById("fault-input");
const faultStageInput = document.getElementById("fault-stage-input");

const btnStart = document.getElementById("btn-start");
const btnPause = document.getElementById("btn-pause");
const btnResume = document.getElementById("btn-resume");
const btnStop = document.getElementById("btn-stop");
const btnSafeStop = document.getElementById("btn-safe-stop");
const btnGpuClear = document.getElementById("btn-gpu-clear");
const btnOpenPrinter = document.getElementById("btn-open-printer");
const btnOpenWindowsBridge = document.getElementById("btn-open-windows-bridge");
const btnOpenLerobot = document.getElementById("btn-open-lerobot");
const btnOpenBo = document.getElementById("btn-open-bo");
const btnOpenCae = document.getElementById("btn-open-cae");
const printerWorkspaceDotEl = document.getElementById("printer-workspace-dot");
const printerWorkspaceDetailEl = document.getElementById("printer-workspace-detail");
const windowsWorkspaceDotEl = document.getElementById("windows-workspace-dot");
const windowsWorkspaceDetailEl = document.getElementById("windows-workspace-detail");
const lerobotWorkspaceDotEl = document.getElementById("lerobot-workspace-dot");
const lerobotWorkspaceDetailEl = document.getElementById("lerobot-workspace-detail");
const boWorkspaceDotEl = document.getElementById("bo-workspace-dot");
const boWorkspaceDetailEl = document.getElementById("bo-workspace-detail");
const caeWorkspaceDotEl = document.getElementById("cae-workspace-dot");
const caeWorkspaceDetailEl = document.getElementById("cae-workspace-detail");

let events = [];
let currentRunId = null;
let visitedStages = new Set(["controller", "orchestrator", "idle"]);
let visitedEdges = new Set(["controller->orchestrator"]);
let modelStatusTimer = null;

const TERMINAL_EVENTS = new Set(["run_complete", "run_error", "run_stop", "replay_complete"]);
const GRAPH_COLS = 12;
const GRAPH_ROWS = 9;

const GRAPH_NODES = [
  { id: "controller", label: "Controller", col: 2, row: 1, terminal: false, accent: "primary" },
  { id: "orchestrator", label: "Orchestrator", col: 5, row: 1, terminal: false, accent: "primary" },
  { id: "guardian", label: "Guardian Agent", col: 9, row: 1, terminal: false, accent: "secondary" },
  { id: "idle", label: "Idle", col: 1, row: 1, terminal: false, accent: "idle" },
  { id: "design", label: "Design Agent", col: 2, row: 3, terminal: false, accent: "planning" },
  { id: "analysis", label: "Analysis Agent", col: 4, row: 3, terminal: false, accent: "planning" },
  { id: "knowledge", label: "Knowledge Agent", col: 6, row: 3, terminal: false, accent: "planning" },
  { id: "bo", label: "BO Agent", col: 8, row: 3, terminal: false, accent: "planning" },
  { id: "specimen", label: "Specimen Making Agent", col: 2, row: 5, terminal: false, accent: "execution" },
  { id: "vision", label: "Vision", col: 4, row: 5, terminal: false, accent: "execution" },
  { id: "manipulation", label: "Manipulation", col: 6, row: 5, terminal: false, accent: "execution" },
  { id: "equipment", label: "Equipment", col: 8, row: 5, terminal: false, accent: "execution" },
  { id: "mcp", label: "MCP Tools", col: 3, row: 7, terminal: false, accent: "tools" },
  { id: "ollama", label: "NemoClaw / Ollama", col: 6, row: 7, terminal: false, accent: "tools" },
  { id: "memory", label: "Memory / Logs", col: 9, row: 7, terminal: false, accent: "memory" },
  { id: "bridges", label: "Device Bridges", col: 11, row: 7, terminal: false, accent: "tools" },
  { id: "complete", label: "Complete", col: 9, row: 9, terminal: true, accent: "terminal" },
  { id: "error", label: "Error", col: 11, row: 9, terminal: true, accent: "error" },
];

const GRAPH_EDGES = [
  ["controller", "orchestrator"],
  ["orchestrator", "design"],
  ["orchestrator", "knowledge"],
  ["orchestrator", "bo"],
  ["orchestrator", "analysis"],
  ["orchestrator", "guardian"],
  ["orchestrator", "specimen"],
  ["orchestrator", "vision"],
  ["orchestrator", "manipulation"],
  ["orchestrator", "equipment"],
  ["orchestrator", "ollama"],
  ["design", "orchestrator"],
  ["knowledge", "orchestrator"],
  ["knowledge", "bo"],
  ["bo", "orchestrator"],
  ["analysis", "orchestrator"],
  ["guardian", "orchestrator"],
  ["specimen", "mcp"],
  ["vision", "mcp"],
  ["manipulation", "mcp"],
  ["equipment", "mcp"],
  ["mcp", "bridges"],
  ["mcp", "memory"],
  ["ollama", "memory"],
  ["memory", "orchestrator"],
  ["design", "memory"],
  ["knowledge", "memory"],
  ["bo", "memory"],
  ["analysis", "memory"],
  ["guardian", "memory"],
  ["guardian", "complete"],
  ["guardian", "error"],
];

const STAGE_ACTIVE_PATHS = {
  idle: ["controller->orchestrator"],
  design: [
    "controller->orchestrator",
    "orchestrator->design",
    "design->orchestrator",
    "design->memory",
    "orchestrator->ollama",
    "ollama->memory",
  ],
  specimen: [
    "controller->orchestrator",
    "orchestrator->specimen",
    "specimen->mcp",
    "mcp->bridges",
    "mcp->memory",
  ],
  vision: [
    "controller->orchestrator",
    "orchestrator->vision",
    "vision->mcp",
    "mcp->bridges",
    "mcp->memory",
  ],
  manipulation: [
    "controller->orchestrator",
    "orchestrator->manipulation",
    "manipulation->mcp",
    "mcp->bridges",
    "mcp->memory",
  ],
  equipment: [
    "controller->orchestrator",
    "orchestrator->equipment",
    "equipment->mcp",
    "mcp->bridges",
    "mcp->memory",
  ],
  analysis: [
    "controller->orchestrator",
    "orchestrator->analysis",
    "analysis->orchestrator",
    "analysis->memory",
    "orchestrator->ollama",
    "ollama->memory",
  ],
  knowledge: [
    "controller->orchestrator",
    "orchestrator->knowledge",
    "knowledge->orchestrator",
    "knowledge->bo",
    "knowledge->memory",
    "orchestrator->ollama",
    "ollama->memory",
  ],
  bo: [
    "controller->orchestrator",
    "orchestrator->bo",
    "knowledge->bo",
    "bo->orchestrator",
    "bo->memory",
    "orchestrator->ollama",
    "ollama->memory",
  ],
  guardian: [
    "controller->orchestrator",
    "orchestrator->guardian",
    "guardian->orchestrator",
    "guardian->memory",
    "orchestrator->ollama",
    "ollama->memory",
  ],
  complete: ["controller->orchestrator", "guardian->complete"],
  error: ["controller->orchestrator", "guardian->error"],
};

const graphNodeMap = new Map(GRAPH_NODES.map((node) => [node.id, node]));
const RUNTIME_MAP_EDGE_TYPES = new Set(["logical_transition", "control_overlay", "device_bridge", "evidence_flow", "runtime_sidecar"]);
const RUNTIME_MAP_NODE_WIDTH = 184;
const RUNTIME_MAP_NODE_HEIGHT = 76;
const RUNTIME_MAP_EDGE_SPACING = 14;
const RUNTIME_MAP_PARALLEL_SPACING = 26;
const RUNTIME_MAP_GEOMETRY = window.ATRRuntimeGraphGeometry;
let runtimeGraphConfig = null;
let runtimeGraphNodeMap = new Map();
let runtimeGraphEdges = [];
let runtimeGraphBounds = { width: 0, height: 0 };
let runtimeMapResizeObserver = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function runtimeMapClassToken(value, fallback = "item") {
  return String(value || fallback).trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "") || fallback;
}

function runtimeMapNodeStage(node = {}) {
  if (node.id === "orchestrator_supervisor" || node.metadata?.plane === "orchestration_supervisor") {
    return "orchestrator";
  }
  return String(node.stage || node.id || "").trim();
}

function runtimeMapEdgeType(edge = {}) {
  return String(edge.runtimeEdgeType || edge.metadata?.runtime_edge || "logical_transition").trim() || "logical_transition";
}

function runtimeMapNodeLookup(nodes = []) {
  const map = new Map();
  for (const node of nodes) {
    map.set(node.id, node);
    const stage = runtimeMapNodeStage(node);
    if (stage) map.set(stage, node);
  }
  return map;
}

function runtimeMapGeometryOptions() {
  return {
    nodeWidth: RUNTIME_MAP_NODE_WIDTH,
    nodeHeight: RUNTIME_MAP_NODE_HEIGHT,
    edgeSpacing: RUNTIME_MAP_EDGE_SPACING,
    parallelSpacing: RUNTIME_MAP_PARALLEL_SPACING,
    handlePercent: 0.28,
    outwardOffset: 8,
  };
}

function runtimeMapPortPoint(node, side = "right", alongOffset = 0, outwardOffset = 0) {
  return RUNTIME_MAP_GEOMETRY.portPoint(node, side, alongOffset, outwardOffset, runtimeMapGeometryOptions());
}

function runtimeMapInferPorts(source, target) {
  return RUNTIME_MAP_GEOMETRY.inferPorts(source, target, runtimeMapGeometryOptions());
}

function runtimeMapAssignEdgeOffsets(edges) {
  return RUNTIME_MAP_GEOMETRY.assignOffsets(edges, runtimeMapGeometryOptions());
}

function runtimeMapEdgePath(edge) {
  return RUNTIME_MAP_GEOMETRY.path(edge, runtimeMapGeometryOptions());
}

function runtimeMapEdges(graph = {}) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const lookup = runtimeMapNodeLookup(nodes);
  const edges = [];
  const seen = new Set();
  for (const item of Array.isArray(graph.edges) ? graph.edges : []) {
    const type = String(item?.metadata?.runtime_edge || "").trim();
    if (!RUNTIME_MAP_EDGE_TYPES.has(type)) continue;
    const source = lookup.get(item.source);
    const target = lookup.get(item.target);
    if (!source || !target) continue;
    const sourceStage = item.metadata?.from_stage || runtimeMapNodeStage(source) || item.source;
    const targetStage = item.metadata?.to_stage || runtimeMapNodeStage(target) || item.target;
    const condition = String(item.condition || item.metadata?.condition || item.metadata?.transition_condition || item.metadata?.overlay_relation || item.metadata?.bridge || type).trim();
    const key = `${item.source}->${item.target}:${type}:${condition}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const ports = runtimeMapInferPorts(source, target);
    edges.push({
      key,
      source,
      target,
      sourceStage,
      targetStage,
      condition,
      label: item.label || condition,
      runtimeEdgeType: type,
      sourceSide: ports.sourceSide,
      targetSide: ports.targetSide,
      metadata: item.metadata || {},
    });
  }
  return runtimeMapAssignEdgeOffsets(edges);
}

function runtimeMapBounds(nodes = []) {
  const maxX = Math.max(...nodes.map((node) => Number(node.position?.x || 0) + RUNTIME_MAP_NODE_WIDTH), RUNTIME_MAP_NODE_WIDTH);
  const maxY = Math.max(...nodes.map((node) => Number(node.position?.y || 0) + RUNTIME_MAP_NODE_HEIGHT), RUNTIME_MAP_NODE_HEIGHT);
  return { width: maxX + 96, height: maxY + 96 };
}

function runtimeMapEdgeLabel(edge = {}) {
  const type = runtimeMapEdgeType(edge);
  if (type === "logical_transition") return "route";
  if (type === "control_overlay") return "guardian/control";
  if (type === "device_bridge") return edge.metadata?.bridge || "bridge";
  if (type === "evidence_flow") return "evidence";
  if (type === "runtime_sidecar") return "sidecar";
  return type;
}

const RUNTIME_MAP_LEGEND_LABELS = {
  logical_transition: { title: "Route", detail: "main graph transition" },
  control_overlay: { title: "Guardian", detail: "control / approval gate" },
  device_bridge: { title: "Device", detail: "hardware bridge" },
  evidence_flow: { title: "Evidence", detail: "log / memory flow" },
  runtime_sidecar: { title: "Sidecar", detail: "runtime support plane" },
};

function renderRuntimeMapLegend(edges = runtimeGraphEdges) {
  if (!runtimeMapLegendEl) return;
  const types = Array.from(new Set((edges || []).map((edge) => runtimeMapEdgeType(edge)).filter(Boolean)));
  const orderedTypes = ["logical_transition", "control_overlay", "device_bridge", "evidence_flow", "runtime_sidecar"].filter((type) => types.includes(type));
  const fallbackTypes = orderedTypes.length ? orderedTypes : ["logical_transition", "control_overlay", "device_bridge", "evidence_flow"];
  runtimeMapLegendEl.innerHTML = `
    <div class="runtime-map-legend-head">
      <strong>Legend</strong>
      <span>${escapeHtml(String((edges || []).length))} edge(s)</span>
    </div>
    <div class="runtime-map-legend-list">
      ${fallbackTypes.map((type) => {
        const meta = RUNTIME_MAP_LEGEND_LABELS[type] || { title: type, detail: "runtime edge" };
        return `
          <div class="runtime-map-legend-row" title="${escapeHtml(meta.detail)}">
            <span class="runtime-map-legend-line edge-type-${runtimeMapClassToken(type)}" aria-hidden="true"></span>
            <span><strong>${escapeHtml(meta.title)}</strong><small>${escapeHtml(meta.detail)}</small></span>
          </div>`;
      }).join("")}
    </div>
  `;
}

function fitRuntimeGraphCanvas() {
  if (!langGraphShellEl || !langGraphCellsEl || !langGraphNodesEl || !runtimeGraphBounds.width) return;
  const availableWidth = Math.max(320, langGraphShellEl.clientWidth - 24);
  const scale = Math.min(1, availableWidth / runtimeGraphBounds.width);
  const fittedHeight = Math.ceil(runtimeGraphBounds.height * scale + 20);
  for (const layer of [langGraphCellsEl, langGraphNodesEl]) {
    layer.style.transformOrigin = "0 0";
    layer.style.transform = `scale(${scale})`;
  }
  langGraphShellEl.style.height = `${Math.max(430, fittedHeight)}px`;
  langGraphShellEl.style.minHeight = `${Math.max(430, fittedHeight)}px`;
  langGraphShellEl.dataset.fitScale = String(scale.toFixed(3));
}

function renderRuntimeGraphCanvas(graph = runtimeGraphConfig) {
  if (!langGraphShellEl || !langGraphNodesEl || !langGraphCellsEl || !graph) return false;
  const normalizedGraph = RUNTIME_MAP_GEOMETRY.normalizeNodePositions(graph, { grid: 16 });
  runtimeGraphConfig = normalizedGraph;
  const nodes = Array.isArray(normalizedGraph.nodes) ? normalizedGraph.nodes : [];
  runtimeGraphNodeMap = runtimeMapNodeLookup(nodes);
  runtimeGraphEdges = runtimeMapEdges(normalizedGraph);
  runtimeGraphBounds = runtimeMapBounds(nodes);
  langGraphShellEl.classList.add("runtime-readonly-map");
  langGraphCellsEl.style.width = `${runtimeGraphBounds.width}px`;
  langGraphCellsEl.style.height = `${runtimeGraphBounds.height}px`;
  langGraphNodesEl.style.width = `${runtimeGraphBounds.width}px`;
  langGraphNodesEl.style.height = `${runtimeGraphBounds.height}px`;
  const edgeMarkup = runtimeGraphEdges.map((edge) => {
    const type = runtimeMapEdgeType(edge);
    return `<path class="runtime-map-edge edge-type-${runtimeMapClassToken(type)}" data-edge="${escapeHtml(edge.key)}" d="${runtimeMapEdgePath(edge)}"><title>${escapeHtml(edge.sourceStage)} -&gt; ${escapeHtml(edge.targetStage)} · ${escapeHtml(runtimeMapEdgeLabel(edge))}</title></path>`;
  }).join("");
  langGraphCellsEl.innerHTML = `
    <svg class="runtime-map-edge-svg" viewBox="0 0 ${runtimeGraphBounds.width} ${runtimeGraphBounds.height}" aria-hidden="true">
      <defs>
        <marker id="main-runtime-arrow" markerWidth="12" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse" overflow="visible">
          <path d="M0,0 L10,5 L0,10 L2.6,5 z" fill="context-stroke" stroke="none"></path>
        </marker>
      </defs>
      ${edgeMarkup}
    </svg>`;
  renderRuntimeMapLegend(runtimeGraphEdges);
  langGraphNodesEl.innerHTML = nodes.map((node) => {
    const stage = runtimeMapNodeStage(node);
    const kind = runtimeMapClassToken(node.kind || "runtime");
    const runtimeNode = runtimeMapClassToken(node.metadata?.runtime_node || "executable");
    const label = node.label || node.id;
    const sub = node.metadata?.plane || node.handler || stage;
    return `
      <div class="graph-node runtime-map-node kind-${kind} runtime-${runtimeNode}" data-stage="${escapeHtml(stage)}" data-node-id="${escapeHtml(node.id)}" style="left:${Number(node.position?.x || 0)}px;top:${Number(node.position?.y || 0)}px;">
        <span class="node-light"></span>
        <span class="node-copy"><strong>${escapeHtml(label)}</strong><small>${escapeHtml(sub)}</small></span>
      </div>`;
  }).join("");
  fitRuntimeGraphCanvas();
  if (window.ResizeObserver && !runtimeMapResizeObserver) {
    runtimeMapResizeObserver = new ResizeObserver(fitRuntimeGraphCanvas);
    runtimeMapResizeObserver.observe(langGraphShellEl);
  }
  return true;
}

function runtimeMapConnectedEdgeKeys(stage) {
  const clean = String(stage || "");
  if (!runtimeGraphEdges.length) return new Set(STAGE_ACTIVE_PATHS[clean] || []);
  return new Set(runtimeGraphEdges.filter((edge) => edge.sourceStage === clean || edge.targetStage === clean).map((edge) => edge.key));
}

async function postJson(url, body = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return await res.json();
}

function openLiveGuiWindow() {
  const planningUrl = new URL("/live", window.location.origin);
  planningUrl.searchParams.set("auto", "1");
  if (backendSelect && backendSelect.value) {
    planningUrl.searchParams.set("backend", backendSelect.value);
  }
  if (goalInput && goalInput.value) {
    planningUrl.searchParams.set("goal", goalInput.value);
  }
  window.open(planningUrl.toString(), "_blank", "width=1440,height=960,popup=yes");
}

function openLerobotWindow() {
  window.open(new URL("/lerobot", window.location.origin).toString(), "_blank", "width=1440,height=960,popup=yes");
}

function openPrinterWindow() {
  const url = new URL("/printer", window.location.origin).toString();
  const opened = window.open(url, "_blank", "width=1320,height=920,popup=yes");
  if (!opened) {
    window.location.href = url;
  }
}

function openWindowsBridgeWindow() {
  const url = new URL("/equipment/windows", window.location.origin).toString();
  const opened = window.open(url, "_blank", "width=1180,height=880,popup=yes");
  if (!opened) {
    window.location.href = url;
  }
}

function openBoWindow() {
  const url = new URL("/bo", window.location.origin).toString();
  const opened = window.open(url, "_blank", "width=1320,height=920,popup=yes");
  if (!opened) {
    window.location.href = url;
  }
}

function openCaeWindow() {
  const url = new URL("/cae", window.location.origin).toString();
  const opened = window.open(url, "_blank", "width=1320,height=920,popup=yes");
  if (!opened) {
    window.location.href = url;
  }
}

function pushEvent(event) {
  events.unshift(event);
  if (events.length > 250) {
    events = events.slice(0, 250);
  }
  const isRunning = !TERMINAL_EVENTS.has(event.event_type);
  captureVisitedStage(event.state, isRunning);
  renderTimeline();
  renderLogs();
  const fallbackStage = metricStageEl ? metricStageEl.textContent : "idle";
  renderLangGraph(event.state?.stage || fallbackStage || "idle", isRunning);
}

function timelineClass(level) {
  if (level === "ERROR") return "timeline-item error";
  if (level === "WARNING") return "timeline-item warning";
  return "timeline-item";
}

function renderTimeline() {
  timelineEl.innerHTML = "";
  for (const event of events.slice(0, 40)) {
    const item = document.createElement("article");
    item.className = timelineClass(event.level);
    item.innerHTML = `
      <small>${event.level || "INFO"} • ${event.event_type || "event"}</small>
      <div>${event.message || ""}</div>
    `;
    timelineEl.appendChild(item);
  }
}

function renderLogs() {
  const selected = levelFilterEl ? levelFilterEl.value : "all";
  logViewerEl.innerHTML = "";
  for (const event of events) {
    const level = event.level || "INFO";
    if (selected !== "all" && level !== selected) continue;
    const entry = document.createElement("div");
    entry.className = "log-entry";
    entry.innerHTML = `
      <small>${level} • ${event.event_type || "event"}</small>
      <div>${event.message || ""}</div>
    `;
    logViewerEl.appendChild(entry);
  }
}

function captureVisitedStage(state, isRunning = false) {
  if (!state || !state.run_id) return;
  if (currentRunId !== state.run_id) {
    currentRunId = state.run_id;
    visitedStages = new Set(["controller", "orchestrator", "idle"]);
    visitedEdges = new Set(["controller->orchestrator"]);
  }
  const stage = String(state.stage || "idle");
  if (runtimeGraphNodeMap.has(stage) || graphNodeMap.has(stage)) {
    visitedStages.add(stage);
  }
  for (const edge of runtimeMapConnectedEdgeKeys(stage)) {
    visitedEdges.add(edge);
  }
  if (isRunning) {
    visitedStages.add("controller");
    visitedStages.add("orchestrator");
  }
  if (state.run_metadata && state.run_metadata.bo_agent) {
    visitedStages.add("bo");
    visitedEdges.add("knowledge->bo");
    visitedEdges.add("bo->orchestrator");
    visitedEdges.add("bo->memory");
  }
}

async function initLangGraph() {
  if (!langGraphNodesEl || !langGraphCellsEl) return;
  langGraphNodesEl.innerHTML = "";
  langGraphCellsEl.innerHTML = "";
  try {
    const response = await fetch("/api/graphs/atr_closed_loop");
    const payload = await response.json();
    runtimeGraphConfig = payload.graph || null;
    if (!runtimeGraphConfig || !renderRuntimeGraphCanvas(runtimeGraphConfig)) {
      throw new Error("Runtime graph payload is empty");
    }
    renderLangGraph("idle", false);
  } catch (err) {
    langGraphShellEl?.classList.add("runtime-readonly-map", "runtime-map-error");
    langGraphCellsEl.innerHTML = `<div class="runtime-map-load-error">Runtime graph load failed: ${escapeHtml(err.message || String(err))}</div>`;
  }
}

function cellCenter(point) {
  const x = ((point.col - 0.5) / GRAPH_COLS) * 100;
  const y = ((point.row - 0.5) / GRAPH_ROWS) * 100;
  return { x, y };
}

function orthogonalPoints(src, dst) {
  if (src.col === dst.col || src.row === dst.row) {
    return [src, dst];
  }
  const midRow = src.row + Math.round((dst.row - src.row) / 2);
  return [
    src,
    { col: src.col, row: midRow },
    { col: dst.col, row: midRow },
    dst,
  ];
}

function edgeSegments(src, dst) {
  const points = orthogonalPoints(src, dst).map(cellCenter);
  const segments = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i];
    const b = points[i + 1];
    if (Math.abs(a.y - b.y) < 0.0001) {
      segments.push({
        axis: "horizontal",
        x1: Math.min(a.x, b.x),
        x2: Math.max(a.x, b.x),
        y1: a.y,
        y2: a.y,
      });
    } else {
      segments.push({
        axis: "vertical",
        x1: a.x,
        x2: a.x,
        y1: Math.min(a.y, b.y),
        y2: Math.max(a.y, b.y),
      });
    }
  }
  return segments;
}

function renderLangGraph(activeStage, isRunning = false) {
  if (!langGraphNodesEl || !langGraphCellsEl) return;
  const stage = String(activeStage || "idle");
  const activeEdges = runtimeMapConnectedEdgeKeys(stage);

  const nodeElements = langGraphNodesEl.querySelectorAll(".graph-node");
  nodeElements.forEach((el) => {
    const nodeStage = el.dataset.stage;
    el.classList.remove("node-active", "node-visited", "node-error");
    if (visitedStages.has(nodeStage)) {
      el.classList.add("node-visited");
    }
    if (nodeStage === stage) {
      el.classList.add("node-active");
      if (nodeStage === "error") {
        el.classList.add("node-error");
      }
    }
  });

  const segments = langGraphCellsEl.querySelectorAll(".edge-segment, .runtime-map-edge");
  segments.forEach((seg) => {
    const edge = seg.getAttribute("data-edge") || "";
    seg.classList.remove("edge-active", "edge-visited");
    if (visitedEdges.has(edge)) {
      seg.classList.add("edge-visited");
    }
    if (isRunning && activeEdges.has(edge)) {
      seg.classList.add("edge-active");
    }
  });

  if (graphStageIndicatorEl) {
    graphStageIndicatorEl.textContent = `STAGE: ${stage.toUpperCase()}`;
    if (stage === "error") {
      graphStageIndicatorEl.className = "badge warning";
    } else if (stage === "complete" || stage === "idle") {
      graphStageIndicatorEl.className = "badge idle";
    } else {
      graphStageIndicatorEl.className = "badge running";
    }
  }
}

function setDotState(el, state) {
  if (!el) return;
  el.className = "status-dot";
  if (state) {
    el.classList.add(state);
  }
}

function renderRuntimeStatus(snapshot, state, isRunning) {
  const runtime = snapshot.runtime || state.run_metadata || {};
  const backend = runtime.backend || {};
  const models = runtime.models || {};
  const backendActive = Boolean(backend.active) && isRunning;
  if (backendSelect && backend.name && backendSelect.value !== backend.name) {
    backendSelect.value = backend.name;
  }

  setDotState(backendStatusDotEl, backendActive ? "active" : backend.active ? "busy" : "idle");
  if (backendStatusLabelEl) {
    backendStatusLabelEl.textContent = backendActive ? `${backend.label || "Backend"} active` : `${backend.label || "Backend"} standby`;
  }
  if (backendStatusDetailEl) {
    backendStatusDetailEl.textContent = backend.proxy_url
      ? `Endpoint ${backend.proxy_url} routing ${backendActive ? "live" : "ready"} traffic.`
      : "Backend metadata unavailable.";
  }

  const stage = String(state.stage || "idle");
  const e4bStages = new Set(["design", "analysis", "knowledge", "guardian", "specimen", "vision", "manipulation", "equipment"]);
  const e4bActive = isRunning && e4bStages.has(stage);

  setDotState(nemoclawStatusDotEl, backendActive ? "active" : "idle");
  if (nemoclawStatusLabelEl) {
    if (backendActive) {
      nemoclawStatusLabelEl.textContent = `${backend.label || "Backend"} agents working`;
    } else if (backend.active) {
      nemoclawStatusLabelEl.textContent = `${backend.label || "Backend"} ready`;
    } else {
      nemoclawStatusLabelEl.textContent = "Backend idle";
    }
  }
  if (nemoclawStatusDetailEl) {
    nemoclawStatusDetailEl.textContent = isRunning
      ? `Stage ${stage} is currently routed through ${backend.label || "the selected backend"}.`
      : "Waiting for the next run to light up the stack.";
  }

  const chipBindings = [
    [modelOrchestratorChipEl, models.orchestrator?.primary, isRunning],
    [modelE4BChipEl, models.e4b?.primary, e4bActive],
  ];
  for (const [chip, model, active] of chipBindings) {
    if (!chip || !model) continue;
    const body = chip.querySelector("strong");
    if (body) body.textContent = model || body.textContent;
    chip.dataset.model = model;
    chip.classList.toggle("is-primary", Boolean(active));
    chip.classList.toggle("is-idle", !active);
    const dot = chip.querySelector(".chip-dot");
    if (dot) {
      dot.style.background = active ? "var(--primary)" : "var(--secondary)";
      dot.style.boxShadow = active
        ? "0 0 0 4px rgba(20, 54, 179, 0.12), 0 0 18px rgba(20, 54, 179, 0.42)"
        : "0 0 0 4px rgba(47, 114, 255, 0.12), 0 0 16px rgba(47, 114, 255, 0.34)";
    }
  }
}

function setModelActionDot(dot, state) {
  if (!dot) return;
  dot.className = "model-load-dot";
  dot.classList.add(state || "unknown");
}

function renderModelStatuses(payload) {
  const enabled = Boolean(payload && payload.ok && payload.enabled);
  const byModel = new Map();
  for (const item of payload?.models || []) {
    if (item && item.model) byModel.set(String(item.model), item);
  }

  const chips = [modelOrchestratorChipEl, modelE4BChipEl].filter(Boolean);
  for (const chip of chips) {
    const model = chip.dataset.model || chip.querySelector("strong")?.textContent || "";
    const status = byModel.get(model);
    const state = status?.state || (enabled ? "unknown" : "disabled");
    const loaded = Boolean(status?.loaded);
    chip.classList.toggle("is-loaded", loaded);
    chip.classList.toggle("is-loading", state === "loading");
    chip.classList.toggle("is-unloaded", state === "unloaded" || state === "disabled");
    chip.title = status
      ? `${model}: ${state} desired=${status.desired_replicas} available=${status.available_replicas}`
      : `${model}: status unavailable`;
  }

  for (const dot of modelLoadDots) {
    const model = dot.dataset.modelDot || "";
    const status = byModel.get(model);
    setModelActionDot(dot, status?.state || (enabled ? "unknown" : "disabled"));
  }

  for (const button of modelLoadButtons) {
    const status = byModel.get(button.dataset.model || "");
    const state = status?.state || "";
    button.disabled = !enabled || state === "loaded" || state === "loading";
  }
  for (const button of modelUnloadButtons) {
    const status = byModel.get(button.dataset.model || "");
    const state = status?.state || "";
    button.disabled = !enabled || (state !== "loaded" && state !== "loading");
  }
}

async function refreshModelStatuses() {
  try {
    const res = await fetch("/api/runtime/models");
    const data = await res.json();
    renderModelStatuses(data);
  } catch (err) {
    renderModelStatuses({ ok: false, enabled: false, models: [] });
  }
}

async function setModelServingState(model, action, button) {
  if (!model || !["load", "unload"].includes(action)) return;
  const originalText = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = action === "load" ? "Loading..." : "Unloading...";
  }
  try {
    const data = await postJson(`/api/runtime/models/${action}`, { model });
    if (data.status) {
      renderModelStatuses(data.status);
    } else {
      await refreshModelStatuses();
    }
    await refreshState();
  } finally {
    if (button) button.textContent = originalText;
  }
}

function renderAgentStatus(agentStatus) {
  agentStatusEl.innerHTML = "";
  const names = Object.keys(agentStatus || {});
  if (!names.length) {
    agentStatusEl.innerHTML = `<div class="list-item"><span>No agent activity yet</span></div>`;
    return;
  }
  for (const name of names) {
    const item = agentStatus[name];
    const row = document.createElement("div");
    row.className = "list-item";
    row.innerHTML = `
      <span>${name}</span>
      <span class="state-pill">${item.state || "idle"}</span>
    `;
    agentStatusEl.appendChild(row);
  }
}

function renderDeviceStatus(deviceHealth) {
  deviceStatusEl.innerHTML = "";
  const names = Object.keys(deviceHealth || {});
  if (!names.length) {
    deviceStatusEl.innerHTML = `<div class="list-item"><span>No devices</span></div>`;
    return;
  }
  for (const name of names) {
    const row = document.createElement("div");
    row.className = "list-item";
    row.innerHTML = `
      <span>${name}</span>
      <span class="state-pill">${deviceHealth[name]}</span>
    `;
    deviceStatusEl.appendChild(row);
  }
}

function updateIndicators(snapshot) {
  const state = snapshot.state || {};
  captureVisitedStage(state, Boolean(snapshot.is_running));
  if (metricStageEl) metricStageEl.textContent = state.stage || "idle";
  if (metricModeEl) metricModeEl.textContent = state.mode || "test";
  if (metricLoopEl) metricLoopEl.textContent = String(state.loop_count || 0);
  if (snapshot.is_running) {
    runIndicatorEl.textContent = "RUNNING";
    runIndicatorEl.className = "badge running";
  } else {
    runIndicatorEl.textContent = "IDLE";
    runIndicatorEl.className = "badge idle";
  }
  renderAgentStatus(state.agent_status || {});
  renderDeviceStatus(state.device_health || {});
  renderLangGraph(state.stage || "idle", Boolean(snapshot.is_running));
  renderRuntimeStatus(snapshot, state, Boolean(snapshot.is_running));
}

async function refreshState() {
  const res = await fetch("/api/state");
  const data = await res.json();
  updateIndicators(data);
  await refreshPrinterWorkspaceStatus();
  await refreshWindowsWorkspaceStatus();
  await refreshLerobotWorkspaceStatus();
  await refreshCaeWorkspaceStatus();
}

async function refreshPrinterWorkspaceStatus() {
  if (!printerWorkspaceDetailEl && !printerWorkspaceDotEl) return;
  const selectedMode = modeSelect ? modeSelect.value : "test";
  const mode = selectedMode === "live" ? "live" : "test";
  try {
    const res = await fetch(`/api/printer/status?mode=${encodeURIComponent(mode)}`);
    const data = await res.json();
    const gates = data.live_gates || {};
    const connection = data.connection || {};
    const health = data.health || {};
    const ready = Boolean(data.ok || health.reachable || mode === "test");
    setDotState(printerWorkspaceDotEl, ready ? (mode === "live" ? "busy" : "idle") : "warn");
    if (printerWorkspaceDetailEl) {
      const host = connection.host || "not configured";
      const storage = connection.storage || "usb";
      const gateText = `upload=${Boolean(gates.allow_upload)} start=${Boolean(gates.allow_start_print)} eject=${Boolean(gates.allow_ejection)}`;
      const state = health.state || health.failure_code || "virtual-ready";
      printerWorkspaceDetailEl.textContent = `${mode} · ${host} · storage=${storage} · ${gateText} · state=${state}`;
    }
  } catch (err) {
    setDotState(printerWorkspaceDotEl, "warn");
    if (printerWorkspaceDetailEl) {
      printerWorkspaceDetailEl.textContent = `Prusa bridge status unavailable: ${err}`;
    }
  }
}

async function refreshWindowsWorkspaceStatus() {
  if (!windowsWorkspaceDetailEl && !windowsWorkspaceDotEl) return;
  try {
    const res = await fetch("/api/equipment/windows/config");
    const data = await res.json();
    const connection = data.connection || {};
    const candidates = Array.isArray(connection.candidates) ? connection.candidates : [];
    const selected = Boolean(connection.selected);
    setDotState(windowsWorkspaceDotEl, selected ? "busy" : "idle");
    if (windowsWorkspaceDetailEl) {
      const alias = connection.selected_candidate || "none selected";
      const token = connection.token_configured ? "token configured" : "token missing";
      const url = connection.bridge_url || "not configured";
      windowsWorkspaceDetailEl.textContent = `${alias} · ${url} · ${token} · saved=${candidates.length}`;
    }
  } catch (err) {
    setDotState(windowsWorkspaceDotEl, "warn");
    if (windowsWorkspaceDetailEl) {
      windowsWorkspaceDetailEl.textContent = `Windows bridge status unavailable: ${err}`;
    }
  }
}

async function refreshLerobotWorkspaceStatus() {
  if (!lerobotWorkspaceDetailEl && !lerobotWorkspaceDotEl) return;
  try {
    const res = await fetch("/api/lerobot/config");
    const data = await res.json();
    const profileId = data.selected_profile_id || data.default_profile_id || "unknown";
    const profile = (data.profiles || []).find((item) => item.profile_id === profileId) || {};
    const gates = profile.live_gate_summary || data.live_gate_summary || {};
    const sessionCount = Array.isArray(data.sessions) ? data.sessions.length : 0;
    setDotState(lerobotWorkspaceDotEl, data.ok ? "busy" : "warn");
    if (lerobotWorkspaceDetailEl) {
      lerobotWorkspaceDetailEl.textContent = `${profile.display_name || profileId} · live=${Boolean(gates.live_enabled)} · sessions=${sessionCount}`;
    }
  } catch (err) {
    setDotState(lerobotWorkspaceDotEl, "warn");
    if (lerobotWorkspaceDetailEl) {
      lerobotWorkspaceDetailEl.textContent = `LeRobot bridge status unavailable: ${err}`;
    }
  }
}

async function refreshBoWorkspaceStatus() {
  if (!boWorkspaceDetailEl && !boWorkspaceDotEl) return;
  try {
    const res = await fetch("/api/bo/config");
    const data = await res.json();
    const defaults = data.defaults || {};
    const recent = data.recent || {};
    setDotState(boWorkspaceDotEl, data.ok ? "busy" : "warn");
    if (boWorkspaceDetailEl) {
      const strategy = recent.strategy || defaults.strategy || "bo";
      const acquisition = recent.acquisition || defaults.acquisition || "expected_improvement";
      const budget = recent.budget || defaults.budget || 8;
      boWorkspaceDetailEl.textContent = `${strategy} · ${acquisition} · budget=${budget}`;
    }
  } catch (err) {
    setDotState(boWorkspaceDotEl, "warn");
    if (boWorkspaceDetailEl) {
      boWorkspaceDetailEl.textContent = `BO status unavailable: ${err}`;
    }
  }
}

async function refreshCaeWorkspaceStatus() {
  if (!caeWorkspaceDetailEl && !caeWorkspaceDotEl) return;
  try {
    const res = await fetch("/api/cae/config");
    const data = await res.json();
    const health = data.health || {};
    const solver = health.calculix || {};
    const mesher = health.gmsh || {};
    const recent = data.recent || {};
    setDotState(caeWorkspaceDotEl, data.ok ? "busy" : "warn");
    if (caeWorkspaceDetailEl) {
      const recentStatus = recent.status ? ` · latest=${recent.status}` : "";
      caeWorkspaceDetailEl.textContent = `ccx=${Boolean(solver.available)} · gmsh=${Boolean(mesher.available)} · bottom fixed/top cyclic${recentStatus}`;
    }
  } catch (err) {
    setDotState(caeWorkspaceDotEl, "warn");
    if (caeWorkspaceDetailEl) {
      caeWorkspaceDetailEl.textContent = `CAE status unavailable: ${err}`;
    }
  }
}

async function loadRecentEvents() {
  const res = await fetch("/api/events/recent");
  const data = await res.json();
  const incoming = data.events || [];
  events = incoming.slice().reverse();
  if (events.length && events[events.length - 1]?.state?.run_id) {
    currentRunId = events[events.length - 1].state.run_id;
  }
  visitedStages = new Set(["controller", "orchestrator", "idle"]);
  visitedEdges = new Set(["controller->orchestrator"]);
  for (const event of events) {
    captureVisitedStage(event.state, !TERMINAL_EVENTS.has(event.event_type));
  }
  renderTimeline();
  renderLogs();
}

function connectEventStream() {
  const source = new EventSource("/api/events/stream");
  source.addEventListener("update", (msg) => {
    const event = JSON.parse(msg.data);
    pushEvent(event);
    if (event.state) {
      updateIndicators({ state: event.state, is_running: !TERMINAL_EVENTS.has(event.event_type) });
    }
  });
  source.onerror = () => {
    setTimeout(connectEventStream, 1200);
    source.close();
  };
}

btnStart.addEventListener("click", async () => {
  const selectedMode = modeSelect ? modeSelect.value : "test";
  if (selectedMode === "live") {
    openLiveGuiWindow();
    await refreshState();
    return;
  }

  await postJson("/api/run/start", {
    mode: selectedMode,
    goal: goalInput ? goalInput.value : "",
    backend: backendSelect ? backendSelect.value : "vllm",
    fault: faultInput && faultInput.value ? faultInput.value : "none",
    fault_stage: faultStageInput && faultStageInput.value ? faultStageInput.value : "",
  });
  await refreshState();
});

btnPause.addEventListener("click", async () => {
  runIndicatorEl.textContent = "PAUSING";
  runIndicatorEl.className = "badge warning";
  await postJson("/api/run/pause");
  await refreshState();
});

btnResume.addEventListener("click", async () => {
  await postJson("/api/run/resume");
  await refreshState();
});

btnStop.addEventListener("click", async () => {
  runIndicatorEl.textContent = "STOPPING";
  runIndicatorEl.className = "badge warning";
  await postJson("/api/run/stop");
  await refreshState();
});

btnSafeStop.addEventListener("click", async () => {
  await postJson("/api/run/safe-stop");
  await refreshState();
});

btnGpuClear.addEventListener("click", async () => {
  runIndicatorEl.textContent = "GPU CLEAR";
  runIndicatorEl.className = "badge warning";
  await postJson("/api/runtime/gpu-clear");
  await refreshState();
  await refreshModelStatuses();
});

if (btnOpenLerobot) {
  btnOpenLerobot.addEventListener("click", openLerobotWindow);
}

if (btnOpenPrinter) {
  btnOpenPrinter.addEventListener("click", (event) => {
    event.preventDefault();
    openPrinterWindow();
  });
}

if (btnOpenWindowsBridge) {
  btnOpenWindowsBridge.addEventListener("click", (event) => {
    event.preventDefault();
    openWindowsBridgeWindow();
  });
}

if (btnOpenBo) {
  btnOpenBo.addEventListener("click", (event) => {
    event.preventDefault();
    openBoWindow();
  });
}

if (btnOpenCae) {
  btnOpenCae.addEventListener("click", (event) => {
    event.preventDefault();
    openCaeWindow();
  });
}

if (levelFilterEl) {
  levelFilterEl.addEventListener("change", renderLogs);
}

if (backendSelect) {
  backendSelect.addEventListener("change", async () => {
    runIndicatorEl.textContent = "SWITCHING";
    runIndicatorEl.className = "badge warning";
    const data = await postJson("/api/runtime/backend", { backend: backendSelect.value });
    if (data.snapshot) {
      updateIndicators(data.snapshot);
    } else {
      await refreshState();
    }
    await refreshModelStatuses();
  });
}

for (const button of modelLoadButtons) {
  button.addEventListener("click", () => {
    setModelServingState(button.dataset.model || "", "load", button);
  });
}

for (const button of modelUnloadButtons) {
  button.addEventListener("click", () => {
    setModelServingState(button.dataset.model || "", "unload", button);
  });
}

async function bootstrap() {
  await initLangGraph();
  await refreshState();
  await refreshModelStatuses();
  await refreshPrinterWorkspaceStatus();
  await refreshWindowsWorkspaceStatus();
  await refreshLerobotWorkspaceStatus();
  await refreshBoWorkspaceStatus();
  await refreshCaeWorkspaceStatus();
  await loadRecentEvents();
  connectEventStream();
  if (!modelStatusTimer) {
    modelStatusTimer = window.setInterval(refreshModelStatuses, 8000);
  }
}

bootstrap();
