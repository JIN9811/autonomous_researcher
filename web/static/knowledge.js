const backendStatusEl = document.getElementById("knowledge-backend-status");
const backendDetailEl = document.getElementById("knowledge-backend-detail");
const ontologyVersionEl = document.getElementById("knowledge-ontology-version");
const nodeCountEl = document.getElementById("knowledge-node-count");
const edgeCountEl = document.getElementById("knowledge-edge-count");
const outboxCountEl = document.getElementById("knowledge-outbox-count");
const outboxDetailEl = document.getElementById("knowledge-outbox-detail");
const runtimeMessageEl = document.getElementById("knowledge-runtime-message");
const updatedAtEl = document.getElementById("knowledge-updated-at");
const querySummaryEl = document.getElementById("knowledge-query-summary");
const projectSummaryEl = document.getElementById("knowledge-project-summary");
const nodeInspectorEl = document.getElementById("knowledge-node-inspector");
const expandNodeBtn = document.getElementById("knowledge-expand-node");
const editModeBtn = document.getElementById("knowledge-edit-mode");
const viewModeBtn = document.getElementById("knowledge-view-mode");
const editToolbarEl = document.getElementById("knowledge-edit-toolbar");
const relationQueueEl = document.getElementById("knowledge-relation-queue");
const relationHistoryEl = document.getElementById("knowledge-relation-history");
const graphEditStorageKey = "knowledgeGraphEditDraft";

const graphPalette = {
  Runtime: "#2563eb",
  Evidence: "#d97706",
  Safety: "#dc5a63",
  Project: "#64748b",
  Knowledge: "#0d9488",
};

let runtimeChart = null;
let projectChart = null;
let activityChart = null;
let relationChart = null;
let selectedGraphNode = null;
let selectedRelationProposal = null;
let relationContextPayload = { nodes: [], edges: [] };
let runtimeGraphPayload = { nodes: [], edges: [], graph_revision: "" };
let ontologyPayload = { relations: {} };
let graphEditMode = false;
let relationStatusPayload = null;
let resizeTimer = null;

function emptyGraphEditDraft() {
  return { draft_id: `graph-edit-${Date.now()}`, graph_revision: "", changes: [], undo: [], redo: [], validated: false };
}

function loadGraphEditDraft() {
  try {
    const value = JSON.parse(window.sessionStorage.getItem(graphEditStorageKey) || "null");
    return value && Array.isArray(value.changes) ? { ...emptyGraphEditDraft(), ...value, validated: false } : emptyGraphEditDraft();
  } catch (_error) {
    return emptyGraphEditDraft();
  }
}

let graphEditDraft = loadGraphEditDraft();

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.error || `${response.status} ${response.statusText}`);
  return payload;
}

function setRuntimeMessage(message, tone = "idle") {
  runtimeMessageEl.textContent = message;
  runtimeMessageEl.dataset.tone = tone;
  updatedAtEl.textContent = new Date().toLocaleTimeString();
}

function boundedInteger(value, minimum, maximum, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(minimum, Math.min(maximum, parsed));
}

function graphCategory(node = {}) {
  const text = `${node.kind || ""} ${node.id || ""} ${node.label || ""}`.toLowerCase();
  if (/file:|module:|api:|tool:|concept:|projectgraph|project_graph/.test(text)) return "Project";
  if (/guardian|gate|failure|incident|risk|safety/.test(text)) return "Safety";
  if (/artifact|evidence|measurement|report|snapshot/.test(text)) return "Evidence";
  if (/knowledge|pattern|memory|evolution/.test(text)) return "Knowledge";
  return "Runtime";
}

function graphNodeLabel(node = {}) {
  const label = String(node.label || node.id || node.kind || "node");
  return label.length > 30 ? `${label.slice(0, 28)}…` : label;
}

function graphOption(payload = {}, title = "Knowledge Graph", overlays = {}) {
  const sourceNodes = Array.isArray(payload.nodes) ? payload.nodes : [];
  const sourceEdges = Array.isArray(payload.edges) ? payload.edges : [];
  const categoryNames = Object.keys(graphPalette);
  const nodeIds = new Set(sourceNodes.map((node) => String(node.id || "")).filter(Boolean));
  const nodes = sourceNodes.map((node) => {
    const category = graphCategory(node);
    const degree = sourceEdges.filter((edge) => edge.source === node.id || edge.target === node.id).length;
    return {
      ...node,
      id: String(node.id || ""),
      name: graphNodeLabel(node),
      category: categoryNames.indexOf(category),
      symbolSize: Math.max(14, Math.min(34, 15 + degree * 2)),
      itemStyle: { color: graphPalette[category], borderColor: "#ffffff", borderWidth: 1 },
      label: { show: degree >= 2, color: "#334155", fontSize: 9 },
    };
  });
  const links = sourceEdges
    .filter((edge) => nodeIds.has(String(edge.source || "")) && nodeIds.has(String(edge.target || "")))
    .map((edge) => ({
      ...edge,
      source: String(edge.source),
      target: String(edge.target),
      value: edge.type || edge.label || "related",
      lineStyle: {
        color: /guardian|safety|blocked|failure/i.test(String(edge.type || "")) ? graphPalette.Safety : "#94a3b8",
        width: 1.2,
        opacity: 0.72,
        curveness: 0.08,
      },
    }));
  const draftChanges = Array.isArray(overlays.draftChanges) ? overlays.draftChanges : [];
  draftChanges.filter((change) => change.operation === "add_relation").forEach((change) => {
    if (!nodeIds.has(String(change.source_id || "")) || !nodeIds.has(String(change.target_id || ""))) return;
    links.push({
      id: `draft:${change.source_id}:${change.relation_type}:${change.target_id}`,
      source: String(change.source_id),
      target: String(change.target_id),
      value: change.relation_type || "draft",
      lineStyle: { color: "#22d3ee", width: 2.2, opacity: 0.95, type: "dashed", curveness: 0.14 },
      symbol: ["none", "arrow"],
    });
  });
  const pending = overlays.pendingRelation;
  if (pending && nodeIds.has(String(pending.source_id || "")) && nodeIds.has(String(pending.target_id || ""))) {
    links.push({
      id: `pending:${pending.proposal_id || "relation"}`,
      source: String(pending.source_id),
      target: String(pending.target_id),
      value: pending.relation_type || "pending",
      lineStyle: { color: "#d97706", width: 2.6, opacity: 1, type: "dashed", curveness: 0.16 },
    });
  }
  return {
    animation: false,
    backgroundColor: "#ffffff",
    title: sourceNodes.length ? undefined : {
      text: `No bounded ${title.toLowerCase()} records`,
      left: "center",
      top: "middle",
      textStyle: { color: "#64748b", fontSize: 13, fontWeight: 500 },
    },
    tooltip: {
      trigger: "item",
      confine: true,
      formatter: (params) => {
        if (params.dataType === "edge") return `${params.data.source}<br/>${params.data.value}<br/>${params.data.target}`;
        return `${params.data.name}<br/><span style="color:#64748b">${params.data.kind || graphCategory(params.data)}</span>`;
      },
    },
    series: [{
      type: "graph",
      layout: "force",
      roam: true,
      draggable: Boolean(overlays.editMode),
      data: nodes,
      links,
      categories: categoryNames.map((name) => ({ name, itemStyle: { color: graphPalette[name] } })),
      force: { repulsion: 250, edgeLength: [70, 150], gravity: 0.08, layoutAnimation: sourceNodes.length <= 60 },
      edgeSymbol: ["none", "arrow"],
      edgeSymbolSize: [0, 6],
      emphasis: { focus: "adjacency", lineStyle: { width: 2.4, opacity: 1 } },
    }],
  };
}

function ensureChart(element, existing) {
  if (!element || !window.echarts) return null;
  return existing || window.echarts.init(element, null, { renderer: "canvas" });
}

function renderLegend() {
  const root = document.getElementById("knowledge-graph-legend");
  root.replaceChildren();
  Object.entries(graphPalette).forEach(([label, color]) => {
    const item = document.createElement("span");
    const marker = document.createElement("i");
    marker.style.background = color;
    item.append(marker, document.createTextNode(label));
    root.appendChild(item);
  });
}

function inspectNode(node) {
  selectedGraphNode = node || null;
  nodeInspectorEl.textContent = selectedGraphNode
    ? JSON.stringify(selectedGraphNode, null, 2)
    : "그래프에서 노드를 선택하면 식별자와 저장된 속성을 표시합니다.";
  expandNodeBtn.disabled = !selectedGraphNode?.id;
  populateNodeEditForms();
}

function bindGraphEvents(chart) {
  chart.off("click");
  chart.off("dblclick");
  chart.on("click", (params) => {
    if (params.dataType === "node") inspectNode(params.data);
  });
  chart.on("dblclick", (params) => {
    if (!graphEditMode && params.dataType === "node" && params.data?.id) {
      inspectNode(params.data);
      expandSelectedNode();
    }
  });
  chart.on("mouseup", (params) => {
    if (!graphEditMode || params.dataType !== "node" || !params.data?.id) return;
    const optionNode = chart.getOption()?.series?.[0]?.data?.find((item) => String(item.id) === String(params.data.id));
    if (!optionNode || !Number.isFinite(Number(optionNode.x)) || !Number.isFinite(Number(optionNode.y))) return;
    stageGraphEdit({ operation: "move_node", node_id: String(params.data.id), x: Number(optionNode.x), y: Number(optionNode.y) }, "Node layout staged.");
  });
}

function renderRuntimeGraph() {
  const mount = document.getElementById("knowledge-graph");
  runtimeChart = ensureChart(mount, runtimeChart);
  runtimeChart.setOption(graphOption(runtimeGraphPayload, "Runtime Graph", {
    editMode: graphEditMode,
    draftChanges: graphEditDraft.changes,
  }), true);
  bindGraphEvents(runtimeChart);
}

function queryFilters(kind, value) {
  if (!value) return {};
  const filterByKind = {
    run_context: "run_id",
    similar_experiments: "q",
    failure_path: "entity_id",
    success_path: "agent_id",
    specimen_lineage: "specimen_id",
    device_history: "device_id",
    policy_history: "policy_id",
    bo_context: "objective_id",
    safety_context: "stage",
    project_context: "q",
    provenance_trace: "entity_id",
  };
  return { [filterByKind[kind] || "q"]: value };
}

async function runGraphQuery({ kind, value = "", depth = 2, limit = 60, target = "runtime" }) {
  const queryPlan = {
    kind,
    filters: queryFilters(kind, value.trim()),
    depth: boundedInteger(depth, 1, 4, 2),
    limit: boundedInteger(limit, 1, 100, 60),
  };
  setRuntimeMessage(`Querying ${kind}…`, "busy");
  const payload = await fetchJson("/api/knowledge/graph/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(queryPlan),
  });
  const mount = document.getElementById(target === "project" ? "knowledge-project-graph" : "knowledge-graph");
  if (target === "project") {
    projectChart = ensureChart(mount, projectChart);
    projectChart.setOption(graphOption(payload, "Project Graph"), true);
    bindGraphEvents(projectChart);
    projectSummaryEl.textContent = `${payload.nodes?.length || 0} nodes · ${payload.edges?.length || 0} edges`;
  } else {
    runtimeGraphPayload = { ...payload, nodes: payload.nodes || [], edges: payload.edges || [] };
    if (payload.graph_revision) graphEditDraft.graph_revision = String(payload.graph_revision);
    renderRuntimeGraph();
    querySummaryEl.textContent = `${kind} · ${payload.nodes?.length || 0} nodes · ${payload.edges?.length || 0} edges`;
  }
  setRuntimeMessage(`${kind} query complete.`, "ready");
  return payload;
}

async function expandSelectedNode() {
  if (!selectedGraphNode?.id) return;
  expandNodeBtn.disabled = true;
  try {
    await runGraphQuery({ kind: "provenance_trace", value: selectedGraphNode.id, depth: 2, limit: 80 });
  } catch (error) {
    setRuntimeMessage(`Provenance query failed: ${error}`, "error");
  } finally {
    expandNodeBtn.disabled = false;
  }
}

async function refreshStatus() {
  const payload = await fetchJson("/api/knowledge/graph/stats");
  const graph = payload.graph || {};
  const outbox = payload.outbox || {};
  backendStatusEl.textContent = graph.backend || "disabled";
  backendStatusEl.dataset.state = graph.ok && graph.enabled ? "ready" : "degraded";
  backendDetailEl.textContent = graph.status || payload.status || (graph.enabled ? "connected" : "disabled");
  ontologyVersionEl.textContent = payload.ontology_version || "-";
  nodeCountEl.textContent = String(Number(graph.node_count || 0));
  edgeCountEl.textContent = String(Number(graph.edge_count || 0));
  outboxCountEl.textContent = String(Number(outbox.pending || 0));
  outboxDetailEl.textContent = `${Number(outbox.pending || 0)} pending / ${Number(outbox.dead_letter || 0)} dead`;
  return payload;
}

async function refreshOntology() {
  const payload = await fetchJson("/api/knowledge/ontology");
  ontologyPayload = payload;
  ontologyVersionEl.textContent = payload.version_id || "-";
  const classes = Array.isArray(payload.classes) ? payload.classes : [];
  const relations = payload.relations && typeof payload.relations === "object" ? payload.relations : {};
  document.getElementById("knowledge-ontology-summary").textContent = `${payload.version_id || "-"} · ${classes.length} classes · ${Object.keys(relations).length} relations`;
  const classRoot = document.getElementById("knowledge-ontology-classes");
  classRoot.replaceChildren(...classes.map((name) => {
    const chip = document.createElement("span");
    chip.textContent = name;
    return chip;
  }));
  const relationRoot = document.getElementById("knowledge-ontology-relations");
  relationRoot.replaceChildren(...Object.entries(relations).map(([name, rule]) => {
    const row = document.createElement("article");
    const strong = document.createElement("strong");
    const detail = document.createElement("span");
    strong.textContent = name;
    detail.textContent = `${(rule.domain || []).join(", ") || "*"} → ${(rule.range || []).join(", ") || "*"}`;
    row.append(strong, detail);
    return row;
  }));
  populateNodeEditForms();
  return payload;
}

function memoryCard(title, count, items, emptyText) {
  const card = document.createElement("article");
  card.className = "knowledge-memory-card";
  const label = document.createElement("span");
  const value = document.createElement("strong");
  const list = document.createElement("ul");
  label.textContent = title;
  value.textContent = String(count);
  const rows = items.length ? items.slice(-4) : [emptyText];
  rows.forEach((item) => {
    const row = document.createElement("li");
    row.textContent = typeof item === "string"
      ? item
      : item.summary || item.pattern_id || item.record_id || item.target_id || item.agent_id || "record";
    list.appendChild(row);
  });
  card.append(label, value, list);
  return card;
}

async function refreshMemory() {
  const endpoints = [
    "/api/knowledge/agent-performance?limit=50",
    "/api/knowledge/failure-patterns?limit=50",
    "/api/knowledge/success-patterns?limit=50",
    "/api/knowledge/evolution-packs?limit=50",
  ];
  const [performance, failures, successes, evolution] = await Promise.all(endpoints.map((endpoint) => fetchJson(endpoint)));
  const records = [performance.records || [], failures.records || [], successes.records || [], evolution.packs || []];
  const root = document.getElementById("knowledge-memory-grid");
  root.replaceChildren(
    memoryCard("Agent performance", records[0].length, records[0], "No performance records"),
    memoryCard("Failure patterns", records[1].length, records[1], "No failure patterns"),
    memoryCard("Success patterns", records[2].length, records[2], "No success patterns"),
    memoryCard("Evolution packs", records[3].length, records[3], "No evolution packs"),
  );
  return records;
}

function activityOption(payload = {}) {
  const cycles = Array.isArray(payload.cycles) ? payload.cycles : [];
  const series = [
    ["Collected", "collected", "#2563eb"],
    ["Updated", "updated", "#0d9488"],
    ["Retrieved", "retrieved", "#d97706"],
    ["Used", "used", "#16a34a"],
  ];
  return {
    animation: false,
    backgroundColor: "#ffffff",
    grid: { left: 64, right: 24, top: 46, bottom: 52 },
    legend: { top: 10, textStyle: { color: "#334155", fontSize: 11 } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "category", data: cycles.map((item) => item.cycle_id || "cycle"), name: "Experiment cycle", nameLocation: "middle", nameGap: 32, axisLabel: { color: "#334155" } },
    yAxis: { type: "value", minInterval: 1, name: "Recorded activity count", nameLocation: "middle", nameGap: 44, splitLine: { lineStyle: { color: "#dbe2ea", type: "dashed" } } },
    series: series.map(([name, key, color]) => ({ name, type: "bar", stack: "activity", barMaxWidth: 42, itemStyle: { color }, data: cycles.map((item) => Number(item[key] || 0)) })),
  };
}

async function refreshActivity() {
  const payload = await fetchJson("/api/knowledge/activity?limit=20");
  activityChart = ensureChart(document.getElementById("knowledge-activity-chart"), activityChart);
  activityChart.setOption(activityOption(payload), true);
  return payload;
}

function saveGraphEditDraft() {
  window.sessionStorage.setItem(graphEditStorageKey, JSON.stringify(graphEditDraft));
  updateGraphEditControls();
}

function updateGraphEditControls(message = "") {
  const count = graphEditDraft.changes.length;
  document.getElementById("knowledge-edit-count").textContent = String(count);
  document.getElementById("knowledge-edit-undo").disabled = graphEditDraft.undo.length === 0;
  document.getElementById("knowledge-edit-redo").disabled = graphEditDraft.redo.length === 0;
  document.getElementById("knowledge-edit-validate").disabled = count === 0 || !graphEditDraft.graph_revision;
  document.getElementById("knowledge-edit-apply").disabled = count === 0 || !graphEditDraft.validated;
  document.getElementById("knowledge-edit-discard").disabled = count === 0;
  document.getElementById("knowledge-edit-status").textContent = message || (
    graphEditDraft.validated ? "Server validation passed. Ready to apply." : count ? "Unsaved draft; validate before apply." : "No unsaved graph edits."
  );
}

function setGraphEditMode(enabled) {
  graphEditMode = Boolean(enabled);
  editModeBtn.classList.toggle("active", graphEditMode);
  viewModeBtn.classList.toggle("active", !graphEditMode);
  editModeBtn.setAttribute("aria-pressed", String(graphEditMode));
  viewModeBtn.setAttribute("aria-pressed", String(!graphEditMode));
  editToolbarEl.hidden = !graphEditMode;
  expandNodeBtn.hidden = graphEditMode;
  populateNodeEditForms();
  renderRuntimeGraph();
  updateGraphEditControls();
}

function validRelationOptions(source, target) {
  const sourceClass = String(source?.kind || "");
  const targetClass = String(target?.kind || "");
  return Object.entries(ontologyPayload.relations || {})
    .filter(([, rule]) => (rule.domain || []).includes(sourceClass) && (rule.range || []).includes(targetClass))
    .map(([name]) => name);
}

function populateNodeEditForms() {
  const metadataForm = document.getElementById("knowledge-node-edit-form");
  const relationForm = document.getElementById("knowledge-relation-edit-form");
  const enabled = graphEditMode && Boolean(selectedGraphNode?.id);
  metadataForm.hidden = !enabled;
  relationForm.hidden = !enabled;
  if (!enabled) return;
  const properties = selectedGraphNode.properties && typeof selectedGraphNode.properties === "object" ? selectedGraphNode.properties : selectedGraphNode;
  document.getElementById("knowledge-edit-label").value = String(selectedGraphNode.label || properties.label || "");
  document.getElementById("knowledge-edit-alias").value = String(properties.alias || "");
  document.getElementById("knowledge-edit-note").value = String(properties.note || "");
  document.getElementById("knowledge-edit-tags").value = Array.isArray(properties.tags) ? properties.tags.join(", ") : "";
  const targetSelect = document.getElementById("knowledge-edit-target");
  const previous = targetSelect.value;
  targetSelect.replaceChildren(...(runtimeGraphPayload.nodes || [])
    .filter((node) => String(node.id) !== String(selectedGraphNode.id))
    .map((node) => {
      const option = document.createElement("option");
      option.value = String(node.id);
      option.textContent = `${graphNodeLabel(node)} · ${node.kind || "KnowledgeNode"}`;
      return option;
    }));
  if ([...targetSelect.options].some((option) => option.value === previous)) targetSelect.value = previous;
  populateRelationTypes();
}

function populateRelationTypes() {
  const targetId = document.getElementById("knowledge-edit-target").value;
  const target = (runtimeGraphPayload.nodes || []).find((node) => String(node.id) === targetId);
  const relationSelect = document.getElementById("knowledge-edit-relation");
  relationSelect.replaceChildren(...validRelationOptions(selectedGraphNode, target).map((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    return option;
  }));
  document.getElementById("knowledge-stage-relation").disabled = relationSelect.options.length === 0;
}

function stageGraphEdit(change, message) {
  graphEditDraft.undo.push(JSON.stringify(graphEditDraft.changes));
  graphEditDraft.redo = [];
  const identity = change.operation === "update_node_metadata" || change.operation === "move_node"
    ? `${change.operation}:${change.node_id}`
    : `${change.operation}:${change.source_id || ""}:${change.relation_type || ""}:${change.target_id || ""}`;
  graphEditDraft.changes = graphEditDraft.changes.filter((item) => {
    const itemIdentity = item.operation === "update_node_metadata" || item.operation === "move_node"
      ? `${item.operation}:${item.node_id}`
      : `${item.operation}:${item.source_id || ""}:${item.relation_type || ""}:${item.target_id || ""}`;
    return itemIdentity !== identity;
  });
  graphEditDraft.changes.push(change);
  graphEditDraft.validated = false;
  saveGraphEditDraft();
  renderRuntimeGraph();
  updateGraphEditControls(message);
}

function restoreGraphEditStack(direction) {
  const source = direction === "undo" ? graphEditDraft.undo : graphEditDraft.redo;
  const destination = direction === "undo" ? graphEditDraft.redo : graphEditDraft.undo;
  if (!source.length) return;
  destination.push(JSON.stringify(graphEditDraft.changes));
  graphEditDraft.changes = JSON.parse(source.pop());
  graphEditDraft.validated = false;
  saveGraphEditDraft();
  renderRuntimeGraph();
}

async function validateGraphEdit() {
  const button = document.getElementById("knowledge-edit-validate");
  button.disabled = true;
  try {
    const payload = await fetchJson("/api/knowledge/graph/edit/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        draft_id: graphEditDraft.draft_id,
        graph_revision: graphEditDraft.graph_revision,
        operator: "local-operator",
        changes: graphEditDraft.changes,
      }),
    });
    graphEditDraft.changes = payload.draft?.changes || graphEditDraft.changes;
    graphEditDraft.validated = Boolean(payload.validation?.ok);
    saveGraphEditDraft();
    updateGraphEditControls(graphEditDraft.validated ? "Server validation passed. Ready to apply." : "Validation did not pass.");
  } catch (error) {
    graphEditDraft.validated = false;
    saveGraphEditDraft();
    updateGraphEditControls(`Validation failed: ${error}`);
  }
}

async function applyGraphEdit() {
  if (!graphEditDraft.validated) return;
  const button = document.getElementById("knowledge-edit-apply");
  button.disabled = true;
  try {
    await fetchJson("/api/knowledge/graph/edit/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        draft_id: graphEditDraft.draft_id,
        graph_revision: graphEditDraft.graph_revision,
        operator: "local-operator",
        changes: graphEditDraft.changes,
      }),
    });
    window.sessionStorage.removeItem(graphEditStorageKey);
    graphEditDraft = emptyGraphEditDraft();
    updateGraphEditControls("Graph edit applied through Knowledge ingest.");
    await runGraphQuery({ kind: document.getElementById("knowledge-query-kind").value, value: document.getElementById("knowledge-query-value").value, depth: document.getElementById("knowledge-query-depth").value, limit: document.getElementById("knowledge-query-limit").value });
    await refreshRelationWorkspace();
  } catch (error) {
    graphEditDraft.validated = false;
    saveGraphEditDraft();
    updateGraphEditControls(`Apply failed: ${error}`);
  }
}

function discardGraphEdit() {
  window.sessionStorage.removeItem(graphEditStorageKey);
  graphEditDraft = emptyGraphEditDraft();
  updateGraphEditControls("Draft discarded; accepted graph unchanged.");
  renderRuntimeGraph();
}

async function runSync() {
  const button = document.getElementById("knowledge-run-sync");
  button.disabled = true;
  try {
    const limit = boundedInteger(document.getElementById("knowledge-sync-limit").value, 1, 1000, 100);
    setRuntimeMessage("Synchronizing pending Knowledge events…", "busy");
    const payload = await fetchJson("/api/knowledge/graph/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit }),
    });
    document.getElementById("knowledge-sync-result").textContent = JSON.stringify(payload, null, 2);
    await refreshStatus();
    setRuntimeMessage("Knowledge graph synchronization complete.", "ready");
  } catch (error) {
    document.getElementById("knowledge-sync-result").textContent = String(error);
    setRuntimeMessage(`Knowledge synchronization failed: ${error}`, "error");
  } finally {
    button.disabled = false;
  }
}

function relationDecisionPayload() {
  if (!selectedRelationProposal) return null;
  return {
    proposal_version: selectedRelationProposal.version,
    graph_context_hash: selectedRelationProposal.graph_context_hash,
    operator: "local-operator",
    rationale: document.getElementById("knowledge-relation-rationale").value.trim(),
  };
}

function setRelationDecisionEnabled(enabled) {
  ["knowledge-relation-target", "knowledge-relation-type", "knowledge-relation-rationale", "knowledge-relation-approve", "knowledge-relation-revise", "knowledge-relation-defer", "knowledge-relation-reject", "knowledge-relation-reevaluate"]
    .forEach((id) => { document.getElementById(id).disabled = !enabled; });
}

function relationQueueItem(proposal) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "knowledge-relation-item";
  button.dataset.proposalId = proposal.proposal_id;
  button.setAttribute("role", "listitem");
  const title = document.createElement("strong");
  const route = document.createElement("span");
  const scores = document.createElement("small");
  title.textContent = `${proposal.source_class || "Node"} → ${proposal.target_class || "Node"}`;
  route.textContent = `${proposal.source_id} · ${proposal.relation_type} · ${proposal.target_id}`;
  scores.textContent = `LLM ${(Number(proposal.confidence || 0) * 100).toFixed(0)}% · evidence ${(Number(proposal.evidence_score || 0) * 100).toFixed(0)}% · ${proposal.status}`;
  button.append(title, route, scores);
  button.addEventListener("click", () => selectRelationProposal(proposal.proposal_id));
  return button;
}

function renderRelationHistory(decisions = [], graphEdits = []) {
  const rows = [
    ...decisions.map((item) => ({ ...item, history_type: "relation", timestamp: item.decided_at })),
    ...graphEdits.map((item) => ({ ...item, history_type: "graph edit", timestamp: item.decided_at })),
  ].sort((left, right) => String(right.timestamp || "").localeCompare(String(left.timestamp || "")));
  if (!rows.length) {
    const empty = document.createElement("article");
    empty.textContent = "No operator or automatic decisions recorded.";
    relationHistoryEl.replaceChildren(empty);
    return;
  }
  relationHistoryEl.replaceChildren(...rows.slice(0, 60).map((item) => {
    const row = document.createElement("article");
    const title = document.createElement("strong");
    const detail = document.createElement("span");
    const timestamp = document.createElement("time");
    title.textContent = `${item.history_type} · ${item.decision || item.status || "recorded"}`;
    detail.textContent = item.proposal_id || item.draft_id || item.decision_id || "audit record";
    timestamp.textContent = item.timestamp ? new Date(item.timestamp).toLocaleString() : "-";
    row.append(title, detail, timestamp);
    return row;
  }));
}

async function selectRelationProposal(proposalId) {
  try {
    const payload = await fetchJson(`/api/knowledge/relations/${encodeURIComponent(proposalId)}`);
    selectedRelationProposal = payload.proposal;
    document.querySelectorAll(".knowledge-relation-item").forEach((item) => item.classList.toggle("selected", item.dataset.proposalId === proposalId));
    document.getElementById("knowledge-relation-version").textContent = `v${selectedRelationProposal.version} · ${selectedRelationProposal.status}`;
    document.getElementById("knowledge-relation-selected").textContent = `${selectedRelationProposal.source_id}\n${selectedRelationProposal.relation_type}\n${selectedRelationProposal.target_id}\n\n${selectedRelationProposal.rationale || "No rationale recorded."}`;
    document.getElementById("knowledge-relation-rationale").value = selectedRelationProposal.rationale || "";
    setRelationDecisionEnabled(["pending", "deferred"].includes(selectedRelationProposal.status));
    const context = payload.context || { nodes: [], edges: [] };
    const known = new Set((context.nodes || []).map((node) => String(node.id)));
    if (!known.has(String(selectedRelationProposal.target_id))) {
      context.nodes = [...(context.nodes || []), { id: selectedRelationProposal.target_id, kind: selectedRelationProposal.target_class, label: selectedRelationProposal.target_id }];
    }
    relationContextPayload = context;
    const targetSelect = document.getElementById("knowledge-relation-target");
    targetSelect.replaceChildren(...(context.nodes || []).filter((node) => String(node.id) !== String(selectedRelationProposal.source_id)).map((node) => {
      const option = document.createElement("option");
      option.value = String(node.id);
      option.textContent = `${graphNodeLabel(node)} · ${node.kind || "KnowledgeNode"}`;
      return option;
    }));
    targetSelect.value = selectedRelationProposal.target_id;
    populateRelationDecisionTypes(selectedRelationProposal.relation_type);
    relationChart = ensureChart(document.getElementById("knowledge-relation-context"), relationChart);
    relationChart.setOption(graphOption(context, "Relation Context", { pendingRelation: selectedRelationProposal }), true);
    bindGraphEvents(relationChart);
    document.getElementById("knowledge-relation-evidence").textContent = JSON.stringify({
      provenance_refs: selectedRelationProposal.provenance_refs || [],
      confidence: selectedRelationProposal.confidence,
      evidence_score: selectedRelationProposal.evidence_score,
      ontology_version: selectedRelationProposal.ontology_version,
      graph_revision: selectedRelationProposal.graph_revision,
      model_snapshot: selectedRelationProposal.model_snapshot || {},
    }, null, 2);
  } catch (error) {
    setRuntimeMessage(`Relation proposal load failed: ${error}`, "error");
  }
}

function populateRelationDecisionTypes(preferred = "") {
  if (!selectedRelationProposal) return;
  const targetId = document.getElementById("knowledge-relation-target").value;
  const target = (relationContextPayload.nodes || []).find((node) => String(node.id) === targetId) || { kind: selectedRelationProposal.target_class };
  const source = { kind: selectedRelationProposal.source_class };
  const relationSelect = document.getElementById("knowledge-relation-type");
  const names = validRelationOptions(source, target);
  if (preferred && !names.includes(preferred)) names.unshift(preferred);
  relationSelect.replaceChildren(...names.map((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    return option;
  }));
  relationSelect.value = preferred && names.includes(preferred) ? preferred : names[0] || "";
}

async function submitRelationDecision(action) {
  if (!selectedRelationProposal) return;
  const base = relationDecisionPayload();
  const payload = action === "revise-approve" ? {
    ...base,
    target_id: document.getElementById("knowledge-relation-target").value.trim(),
    relation_type: document.getElementById("knowledge-relation-type").value.trim(),
  } : base;
  setRelationDecisionEnabled(false);
  try {
    await fetchJson(`/api/knowledge/relations/${encodeURIComponent(selectedRelationProposal.proposal_id)}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    selectedRelationProposal = null;
    await refreshRelationWorkspace();
    setRuntimeMessage(`Relation ${action} recorded.`, "ready");
  } catch (error) {
    setRelationDecisionEnabled(true);
    setRuntimeMessage(`Relation decision failed: ${error}`, "error");
  }
}

async function refreshRelationWorkspace() {
  const [status, proposals, history] = await Promise.all([
    fetchJson("/api/knowledge/relations/status"),
    fetchJson("/api/knowledge/relations/proposals?limit=500"),
    fetchJson("/api/knowledge/relations/decisions?limit=500"),
  ]);
  relationStatusPayload = status;
  if (status.graph_revision && (!graphEditDraft.graph_revision || graphEditDraft.changes.length === 0)) {
    graphEditDraft.graph_revision = String(status.graph_revision);
    saveGraphEditDraft();
  }
  const stats = status.relations || {};
  document.getElementById("knowledge-relation-gaps").textContent = String(Number(status.gap_count || 0));
  document.getElementById("knowledge-relation-pending").textContent = String(Number(stats.pending || 0));
  document.getElementById("knowledge-relation-approved").textContent = String(Number(stats.approved || 0));
  document.getElementById("knowledge-relation-held").textContent = String(Number(stats.deferred || 0) + Number(stats.rejected || 0));
  document.getElementById("knowledge-relation-worker").textContent = String(status.worker?.status || "idle");
  document.getElementById("knowledge-relation-model").textContent = status.worker?.last_error || "loaded model only";
  const queue = (proposals.proposals || []).filter((proposal) => ["pending", "deferred"].includes(proposal.status));
  document.getElementById("knowledge-relation-queue-count").textContent = `${queue.length} reviewable`;
  if (queue.length) relationQueueEl.replaceChildren(...queue.map(relationQueueItem));
  else {
    const empty = document.createElement("div");
    empty.className = "knowledge-relation-item";
    empty.textContent = "No relation proposals require operator review.";
    relationQueueEl.replaceChildren(empty);
  }
  renderRelationHistory(history.decisions || [], history.graph_edit_decisions || []);
  if (selectedRelationProposal && queue.some((item) => item.proposal_id === selectedRelationProposal.proposal_id)) {
    await selectRelationProposal(selectedRelationProposal.proposal_id);
  } else if (queue.length) {
    await selectRelationProposal(queue[0].proposal_id);
  } else {
    selectedRelationProposal = null;
    relationContextPayload = { nodes: [], edges: [] };
    setRelationDecisionEnabled(false);
    document.getElementById("knowledge-relation-version").textContent = "no selection";
    document.getElementById("knowledge-relation-selected").textContent = "Select a pending proposal.";
    document.getElementById("knowledge-relation-evidence").textContent = "Select a proposal to inspect its bounded evidence.";
    relationChart = ensureChart(document.getElementById("knowledge-relation-context"), relationChart);
    relationChart.setOption(graphOption({}, "Relation Context"), true);
  }
  return { status, proposals, history };
}

async function scanRelations() {
  const button = document.getElementById("knowledge-relation-scan");
  button.disabled = true;
  try {
    await fetchJson("/api/knowledge/relations/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ limit: 100 }) });
    await refreshRelationWorkspace();
    setRuntimeMessage("Knowledge graph relation scan complete.", "ready");
  } catch (error) {
    setRuntimeMessage(`Relation scan failed: ${error}`, "error");
  } finally {
    button.disabled = false;
  }
}

async function runReconciliation() {
  const button = document.getElementById("knowledge-relation-run");
  button.disabled = true;
  try {
    const payload = await fetchJson("/api/knowledge/relations/reconcile", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ limit: 10 }) });
    await refreshRelationWorkspace();
    setRuntimeMessage(payload.status === "model_unloaded" ? "Selected relation model is unloaded; no model was started." : "Relation reconciliation batch complete.", payload.status === "degraded" ? "error" : "ready");
  } catch (error) {
    setRuntimeMessage(`Relation reconciliation failed: ${error}`, "error");
  } finally {
    button.disabled = false;
  }
}

function activateTab(name) {
  document.querySelectorAll("[data-knowledge-tab]").forEach((button) => button.classList.toggle("active", button.dataset.knowledgeTab === name));
  document.querySelectorAll("[data-knowledge-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.knowledgePanel === name));
  window.requestAnimationFrame(() => {
    runtimeChart?.resize();
    projectChart?.resize();
    activityChart?.resize();
    relationChart?.resize();
  });
  if (name === "relations") refreshRelationWorkspace().catch((error) => setRuntimeMessage(`Relation workspace refresh failed: ${error}`, "error"));
  if (window.location.hash !== `#${name}`) window.history.replaceState(null, "", `#${name}`);
}

async function refreshWorkspace() {
  const button = document.getElementById("knowledge-refresh");
  button.disabled = true;
  setRuntimeMessage("Refreshing Knowledge Workspace…", "busy");
  const results = await Promise.allSettled([refreshStatus(), refreshOntology(), refreshMemory(), refreshActivity(), refreshRelationWorkspace()]);
  const failed = results.filter((result) => result.status === "rejected");
  setRuntimeMessage(failed.length ? `${failed.length} Knowledge sections could not be refreshed.` : "Knowledge Workspace is current.", failed.length ? "error" : "ready");
  button.disabled = false;
}

document.querySelectorAll("[data-knowledge-tab]").forEach((button) => button.addEventListener("click", () => activateTab(button.dataset.knowledgeTab)));
document.getElementById("knowledge-refresh").addEventListener("click", refreshWorkspace);
document.getElementById("knowledge-run-query").addEventListener("click", async () => {
  try {
    await runGraphQuery({
      kind: document.getElementById("knowledge-query-kind").value,
      value: document.getElementById("knowledge-query-value").value,
      depth: document.getElementById("knowledge-query-depth").value,
      limit: document.getElementById("knowledge-query-limit").value,
    });
  } catch (error) {
    setRuntimeMessage(`Graph query failed: ${error}`, "error");
  }
});
document.getElementById("knowledge-run-project-query").addEventListener("click", async () => {
  try {
    await runGraphQuery({ kind: "project_context", value: document.getElementById("knowledge-project-query").value, depth: 2, limit: 100, target: "project" });
  } catch (error) {
    setRuntimeMessage(`Project graph query failed: ${error}`, "error");
  }
});
document.getElementById("knowledge-run-sync").addEventListener("click", runSync);
expandNodeBtn.addEventListener("click", expandSelectedNode);
viewModeBtn.addEventListener("click", () => setGraphEditMode(false));
editModeBtn.addEventListener("click", () => setGraphEditMode(true));
document.getElementById("knowledge-edit-target").addEventListener("change", populateRelationTypes);
document.getElementById("knowledge-node-edit-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!selectedGraphNode?.id) return;
  stageGraphEdit({
    operation: "update_node_metadata",
    node_id: String(selectedGraphNode.id),
    metadata: {
      label: document.getElementById("knowledge-edit-label").value.trim(),
      alias: document.getElementById("knowledge-edit-alias").value.trim(),
      note: document.getElementById("knowledge-edit-note").value.trim(),
      tags: document.getElementById("knowledge-edit-tags").value.split(",").map((item) => item.trim()).filter(Boolean),
    },
  }, "Node metadata staged.");
});
document.getElementById("knowledge-relation-edit-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!selectedGraphNode?.id) return;
  stageGraphEdit({
    operation: "add_relation",
    source_id: String(selectedGraphNode.id),
    target_id: document.getElementById("knowledge-edit-target").value,
    relation_type: document.getElementById("knowledge-edit-relation").value,
  }, "Existing-node relation staged.");
});
document.getElementById("knowledge-edit-undo").addEventListener("click", () => restoreGraphEditStack("undo"));
document.getElementById("knowledge-edit-redo").addEventListener("click", () => restoreGraphEditStack("redo"));
document.getElementById("knowledge-edit-validate").addEventListener("click", validateGraphEdit);
document.getElementById("knowledge-edit-apply").addEventListener("click", applyGraphEdit);
document.getElementById("knowledge-edit-discard").addEventListener("click", discardGraphEdit);
document.getElementById("knowledge-relation-scan").addEventListener("click", scanRelations);
document.getElementById("knowledge-relation-run").addEventListener("click", runReconciliation);
document.getElementById("knowledge-relation-target").addEventListener("change", () => populateRelationDecisionTypes());
document.getElementById("knowledge-relation-approve").addEventListener("click", () => submitRelationDecision("approve"));
document.getElementById("knowledge-relation-revise").addEventListener("click", () => submitRelationDecision("revise-approve"));
document.getElementById("knowledge-relation-defer").addEventListener("click", () => submitRelationDecision("defer"));
document.getElementById("knowledge-relation-reject").addEventListener("click", () => submitRelationDecision("reject"));
document.getElementById("knowledge-relation-reevaluate").addEventListener("click", () => submitRelationDecision("re-evaluate"));

window.addEventListener("resize", () => {
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    runtimeChart?.resize();
    projectChart?.resize();
    activityChart?.resize();
    relationChart?.resize();
  }, 100);
});

renderLegend();
updateGraphEditControls();
const initialTab = ["graph", "memory", "ontology", "sync", "project", "relations"].includes(window.location.hash.slice(1)) ? window.location.hash.slice(1) : "graph";
activateTab(initialTab);
refreshWorkspace().then(() => runGraphQuery({ kind: "run_context", limit: 60 })).catch((error) => setRuntimeMessage(`Workspace initialization failed: ${error}`, "error"));
