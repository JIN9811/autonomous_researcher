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
let selectedGraphNode = null;
let resizeTimer = null;

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

function graphOption(payload = {}, title = "Knowledge Graph") {
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
      draggable: false,
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
}

function bindGraphEvents(chart) {
  chart.off("click");
  chart.off("dblclick");
  chart.on("click", (params) => {
    if (params.dataType === "node") inspectNode(params.data);
  });
  chart.on("dblclick", (params) => {
    if (params.dataType === "node" && params.data?.id) {
      inspectNode(params.data);
      expandSelectedNode();
    }
  });
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
    runtimeChart = ensureChart(mount, runtimeChart);
    runtimeChart.setOption(graphOption(payload, "Runtime Graph"), true);
    bindGraphEvents(runtimeChart);
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

function activateTab(name) {
  document.querySelectorAll("[data-knowledge-tab]").forEach((button) => button.classList.toggle("active", button.dataset.knowledgeTab === name));
  document.querySelectorAll("[data-knowledge-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.knowledgePanel === name));
  window.requestAnimationFrame(() => {
    runtimeChart?.resize();
    projectChart?.resize();
    activityChart?.resize();
  });
}

async function refreshWorkspace() {
  const button = document.getElementById("knowledge-refresh");
  button.disabled = true;
  setRuntimeMessage("Refreshing Knowledge Workspace…", "busy");
  const results = await Promise.allSettled([refreshStatus(), refreshOntology(), refreshMemory(), refreshActivity()]);
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

window.addEventListener("resize", () => {
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    runtimeChart?.resize();
    projectChart?.resize();
    activityChart?.resize();
  }, 100);
});

renderLegend();
refreshWorkspace().then(() => runGraphQuery({ kind: "run_context", limit: 60 })).catch((error) => setRuntimeMessage(`Workspace initialization failed: ${error}`, "error"));
