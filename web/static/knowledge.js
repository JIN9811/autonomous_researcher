const runtimeMessageEl = document.getElementById("knowledge-runtime-message");
const updatedAtEl = document.getElementById("knowledge-updated-at");
const ontologyVersionEl = document.getElementById("knowledge-ontology-version");
let activityChart = null;
let activityPayload = null;
let markdownScope = null;
let markdownGeneration = 0;
let detailGeneration = 0;
let intakeTimer = null;
const intakeStorageKey = "knowledgeMarkdownIntakeJob";
const scopedKnowledgeViews = {
  wiki: AX4LABKnowledgeWorkspace.createBrowser(document.getElementById('knowledge-wiki-browser'), {kind:'wiki'}),
  memory: AX4LABKnowledgeWorkspace.createBrowser(document.getElementById('knowledge-private-browser'), {kind:'memory'}),
  delivery: AX4LABKnowledgeWorkspace.createBrowser(document.getElementById('knowledge-delivery-browser'), {kind:'delivery'}),
};
let workspaceScope = null;
let workspaceResyncTimer = null;
let workspaceNavigationGeneration = 0;

async function refreshScopedKnowledge() {
  const summary = await AX4LABKnowledgeWorkspace.request('/api/knowledge/workspace/summary');
  if (workspaceScope !== null && workspaceScope !== summary.scope_ref) Object.values(scopedKnowledgeViews).forEach(view => view.clear());
  workspaceScope = summary.scope_ref;
  document.getElementById('knowledge-workspace-summary').textContent = `${summary.wiki?.count || 0} Wiki pages · ${summary.memory?.status === 'public_only' ? 'Wiki-only access; private identity not configured' : `${summary.memory?.count || 0} scoped memories · ${summary.delivery?.count || 0} delivery records`}`;
  const active = document.querySelector('[data-knowledge-tab].active')?.dataset.knowledgeTab;
  if (scopedKnowledgeViews[active]) await scopedKnowledgeViews[active].refresh();
}

function element(tag, text, className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.error || `${response.status} ${response.statusText}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

function postJson(url, body) {
  return fetchJson(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
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

async function refreshStatus() {
  const payload = await fetchJson("/api/knowledge/status");
  const markdown = payload.markdown || {};
  const counts = markdown.status_counts || {};
  const errors = markdown.index?.errors || [];
  document.getElementById("knowledge-backend-status").textContent = "Markdown";
  document.getElementById("knowledge-backend-detail").textContent = markdown.status || (payload.ok ? "ready" : "unavailable");
  document.getElementById("knowledge-record-count").textContent = String(Number(markdown.records || 0));
  document.getElementById("knowledge-revision-count").textContent = `${Number(markdown.revisions || 0)} preserved revisions`;
  document.getElementById("knowledge-valid-count").textContent = `${Number(counts.valid || 0)} valid`;
  document.getElementById("knowledge-review-count").textContent = `${Number(counts.needs_review || 0)} needs review · ${Number(counts.superseded || 0)} superseded`;
  document.getElementById("knowledge-index-status").textContent = errors.length ? "Needs attention" : "Ready";
  document.getElementById("knowledge-index-detail").textContent = `${Number(markdown.index?.cached_files || 0)} indexed revisions · ${errors.length} errors`;
  return payload;
}

function searchScope() {
  const scope = {};
  for (const [control, field] of [["run", "run_id"], ["cycle", "cycle_id"], ["agent", "agent_id"],
    ["type", "ontology_type"], ["fidelity", "fidelity"]]) {
    const value = document.getElementById(`knowledge-markdown-${control}`).value.trim();
    if (value) scope[field] = value;
  }
  const status = document.getElementById("knowledge-markdown-status").value;
  scope.status = status === "all" ? ["valid", "needs_review", "superseded"] : status;
  const tags = document.getElementById("knowledge-markdown-tags").value.trim();
  if (tags) scope.tags = tags.split(",").map((value) => value.trim()).filter(Boolean);
  const applicability = document.getElementById("knowledge-markdown-applicability").value.trim();
  if (applicability) {
    let parsed;
    try { parsed = JSON.parse(applicability); }
    catch (_error) { throw new Error("Applicability must be an exact JSON object."); }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Applicability must be an exact JSON object.");
    }
    scope.applicability = parsed;
  }
  return scope;
}

function clearMarkdownDetail(message = "Select a record to read its Markdown body and source references.") {
  detailGeneration += 1;
  document.getElementById("knowledge-markdown-detail").replaceChildren(element("p", message));
}

function invalidateMarkdownResults() {
  markdownGeneration += 1;
  markdownScope = null;
  clearMarkdownDetail();
  document.getElementById("knowledge-markdown-results").replaceChildren(element("p", "Run Search Knowledge to apply changed filters."));
  document.getElementById("knowledge-query-summary").textContent = "Filters changed";
  document.getElementById("knowledge-markdown-scope").textContent = "";
}

async function queryMarkdown() {
  const generation = ++markdownGeneration;
  markdownScope = null;
  clearMarkdownDetail();
  const root = document.getElementById("knowledge-markdown-results");
  const button = document.getElementById("knowledge-run-query");
  button.disabled = true;
  try {
    const scope = searchScope();
    root.replaceChildren(element("p", "Searching within the selected scope…"));
    document.getElementById("knowledge-query-summary").textContent = "Searching";
    setRuntimeMessage("Retrieving scoped Markdown knowledge…", "busy");
    const payload = await postJson("/api/knowledge/markdown/query", {
      query: document.getElementById("knowledge-markdown-query").value.trim(),
      scope,
      top_k: boundedInteger(document.getElementById("knowledge-markdown-limit").value, 1, 50, 6),
    });
    if (generation !== markdownGeneration) return;
    // A selection reads with the server-resolved scope, never a broader default.
    markdownScope = structuredClone(payload.scope || scope);
    const hits = Array.isArray(payload.hits) ? payload.hits : [];
    document.getElementById("knowledge-query-summary").textContent = `${hits.length} records · bounded results`;
    document.getElementById("knowledge-markdown-scope").textContent = `Applied scope: ${JSON.stringify(markdownScope)}`;
    root.replaceChildren(...hits.map((hit) => {
      const card = element("button", "", "knowledge-record");
      card.type = "button";
      card.dataset.recordId = hit.record_id;
      card.setAttribute("aria-pressed", "false");
      card.append(element("strong", hit.title || hit.record_id),
        element("span", `${hit.ontology_type} · ${hit.status} · ${hit.evidence_kind} · ${hit.fidelity}`, "knowledge-record-meta"),
        element("span", hit.excerpt || "", "knowledge-record-excerpt"),
        element("small", `${hit.run_id} / ${hit.cycle_id} / ${hit.agent_id} · revision ${hit.revision}`));
      card.addEventListener("click", () => readMarkdown(hit.record_id, card));
      return card;
    }));
    if (!hits.length) root.append(element("p", "No knowledge records match this query and scope."));
    setRuntimeMessage("Scoped knowledge results are current.", "ready");
  } catch (error) {
    if (generation !== markdownGeneration) return;
    root.replaceChildren(element("p", "Knowledge search was not completed. Check the scope and try again."));
    document.getElementById("knowledge-query-summary").textContent = "Search failed";
    setRuntimeMessage(`Knowledge search failed: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
}

function renderMarkdownDetail(record) {
  const root = document.getElementById("knowledge-markdown-detail");
  const details = element("dl", "");
  const fields = [["Record", record.record_id], ["Run / cycle", `${record.run_id} / ${record.cycle_id}`],
    ["Agent / event", `${record.agent_id} / ${record.event_id}`], ["Classification", record.ontology_type],
    ["Evidence / fidelity", `${record.evidence_kind} / ${record.fidelity}`], ["Validity", record.status],
    ["Revision", record.revision], ["Ontology", record.ontology_version],
    ["Tags", (record.tags || []).join(", ") || "None"], ["Applicability", JSON.stringify(record.applicability || {})]];
  if (record.lifecycle_reason) fields.push(["Review reason", record.lifecycle_reason]);
  if (record.superseded_by) fields.push(["Replaced by", record.superseded_by]);
  fields.forEach(([key, value]) => details.append(element("dt", key), element("dd", String(value ?? "-"))));
  const refs = element("ul", "", "knowledge-source-refs");
  (record.source_refs || []).forEach((ref) => refs.append(element("li", typeof ref === "string" ? ref : JSON.stringify(ref))));
  if (!refs.children.length) refs.append(element("li", "No source references attached."));
  // Render Markdown as literal text; stored evidence is never executable markup.
  root.replaceChildren(element("h3", record.title || record.record_id), details,
    element("h3", "Markdown body"), element("pre", record.body || "", "knowledge-markdown-body"),
    element("h3", "Source references"), refs);
}

async function readMarkdown(recordId, selectedButton) {
  if (!markdownScope) return;
  const scope = structuredClone(markdownScope);
  const generation = ++detailGeneration;
  const searchGeneration = markdownGeneration;
  document.getElementById("knowledge-markdown-detail").replaceChildren(element("p", "Reading scoped record…"));
  document.querySelectorAll("#knowledge-markdown-results button").forEach((button) => {
    button.classList.toggle("selected", button === selectedButton);
    button.setAttribute("aria-pressed", String(button === selectedButton));
  });
  try {
    const payload = await postJson("/api/knowledge/markdown/read", {record_id: recordId, scope});
    if (generation !== detailGeneration || searchGeneration !== markdownGeneration) return;
    renderMarkdownDetail(payload.record);
    setRuntimeMessage("Knowledge record loaded within the selected scope.", "ready");
  } catch (error) {
    if (generation !== detailGeneration || searchGeneration !== markdownGeneration) return;
    clearMarkdownDetail("This record could not be read within the selected scope. Refresh the search.");
    setRuntimeMessage(`Knowledge detail failed: ${error.message}`, "error");
  }
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
  const select = document.getElementById("knowledge-markdown-type");
  const selected = select.value;
  select.replaceChildren(new Option("Any type", ""), ...classes.map((name) => new Option(name, name)));
  if (classes.includes(selected)) select.value = selected;
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


function renderActivity() {
  const container = document.getElementById("knowledge-activity-chart");
  // Initialize only once the retained Memory panel is visible.
  if (!activityPayload || !container.clientWidth || !window.echarts) return;
  activityChart = activityChart || window.echarts.init(container, null, {renderer: "canvas"});
  activityChart.setOption(activityOption(activityPayload), true);
  activityChart.resize();
}

async function refreshActivity() {
  activityPayload = await fetchJson("/api/knowledge/activity?limit=20");
  renderActivity();
}

async function refreshManualStatus() {
  const status = await fetchJson("/api/knowledge/sources/status");
  const sources = status.library?.sources || [];
  document.getElementById("knowledge-manual-sources").textContent = String(sources.length);
  document.getElementById("knowledge-manual-chunks").textContent = String(sources.filter(source => source.current && source.status === "ready").length);
  document.getElementById("knowledge-manual-scope").textContent = status.state.replaceAll("_", " ");
  document.getElementById("knowledge-source-enable").checked = Boolean(status.enabled);
  document.getElementById("knowledge-source-inbox").textContent = `Inbox: ${status.inbox}`;
  document.getElementById("knowledge-source-active").textContent = status.active_source_id || status.error || "No active source";
  const progress = document.getElementById("knowledge-source-progress");
  progress.replaceChildren(...sources.map(source => {
    const row = element("div", "", "knowledge-source-progress-row");
    row.append(element("span", `${source.paths?.join(", ") || source.source_id} · ${source.status}${source.error ? ` · ${source.error}` : ""}`));
    if (source.current && ["failed", "needs_review"].includes(source.status)) {
      const retry = element("button", "Retry", "knowledge-button");
      retry.type = "button";
      retry.addEventListener("click", async () => {
        retry.disabled = true;
        try { await postJson("/api/knowledge/sources/retry", {source_id: source.source_id}); await refreshManualStatus(); }
        catch (error) { setRuntimeMessage(error.message, "error"); retry.disabled = false; }
      });
      row.append(retry);
    }
    return row;
  }));
  if (!sources.length) progress.append(element("p", "No sources discovered. Scan the configured inbox to begin."));
  return status;
}

async function ingestManuals() {
  const button = document.getElementById("knowledge-manual-ingest");
  button.disabled = true;
  setRuntimeMessage("Scanning the source inbox…", "busy");
  try {
    await fetchJson("/api/knowledge/sources/scan", {method: "POST"});
    await refreshManualStatus();
    setRuntimeMessage("Source scan complete. Stable changes are curated when automatic intake is enabled.", "ready");
  } catch (error) {
    setRuntimeMessage(`Source scan failed: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
}

let sourceGeneration = 0;
let sourceDetailGeneration = 0;
function renderManualEvidence(payload, generation) {
  const chunks = Array.isArray(payload.hits) ? payload.hits : [];
  const root = document.getElementById("knowledge-manual-results");
  root.replaceChildren(...chunks.map((chunk) => {
    const card = element("article", "", "knowledge-manual-result");
    const header = element("header", "");
    const open = element("button", chunk.title, "knowledge-button");
    open.type = "button";
    open.addEventListener("click", async () => {
      const detailGeneration = ++sourceDetailGeneration;
      const detail = document.getElementById("knowledge-source-detail");
      try {
        const found = await postJson("/api/knowledge/sources/read", {record_id: chunk.record_id, scope: payload.scope});
        if (generation !== sourceGeneration || detailGeneration !== sourceDetailGeneration) return;
        const record = found.record || found;
        detail.replaceChildren(element("h2", record.title), element("pre", record.body, "knowledge-markdown-body"),
          element("h3", "Source provenance"), element("pre", JSON.stringify(record.citations || record.source_refs, null, 2), "knowledge-markdown-body"));
        const original = record.source_markdown || record.source?.markdown;
        if (original) {
          const disclosure = element("details", "");
          disclosure.append(element("summary", "Original extracted Markdown"), element("pre", original, "knowledge-markdown-body"));
          detail.append(disclosure);
        }
      } catch (error) { if (generation === sourceGeneration && detailGeneration === sourceDetailGeneration) detail.replaceChildren(element("p", error.message)); }
    });
    header.append(open, element("span", chunk.category));
    card.append(header, element("p", String(chunk.excerpt || "")), element("footer", chunk.source_id));
    return card;
  }));
  if (!chunks.length) root.append(element("p", "No published source knowledge matches these filters."));
}

async function queryManuals() {
  const query = document.getElementById("knowledge-manual-query").value.trim();
  const generation = ++sourceGeneration;
  const button = document.getElementById("knowledge-manual-run-query");
  button.disabled = true;
  document.getElementById("knowledge-source-detail").replaceChildren(element("p", "Select a source note to inspect its evidence."));
  document.getElementById("knowledge-manual-results").replaceChildren(element("p", "Retrieving source evidence…"));
  try {
    const scope = {};
    const category = document.getElementById("knowledge-source-category").value.trim();
    const tags = document.getElementById("knowledge-source-tags").value.trim();
    const applicability = document.getElementById("knowledge-source-applicability").value.trim();
    if (category) scope.category = category;
    if (tags) scope.tags = tags.split(",").map(tag => tag.trim()).filter(Boolean);
    if (applicability) {
      scope.applicability = JSON.parse(applicability);
      if (!scope.applicability || typeof scope.applicability !== "object" || Array.isArray(scope.applicability)) throw new Error("Applicability must be a JSON object.");
    }
    const payload = await postJson("/api/knowledge/sources/query", {query, scope,
      top_k: boundedInteger(document.getElementById("knowledge-manual-top-k").value, 1, 12, 6),
    });
    if (generation !== sourceGeneration) return;
    renderManualEvidence(payload, generation);
    document.getElementById("knowledge-manual-query-summary").textContent = `${payload.hits?.length || 0} source notes`;
    setRuntimeMessage("Source retrieval complete.", "ready");
  } catch (error) {
    if (generation !== sourceGeneration) return;
    document.getElementById("knowledge-manual-results").replaceChildren(element("p", "Source retrieval failed. Check the filters and try again."));
    document.getElementById("knowledge-manual-query-summary").textContent = "Retrieval failed";
    setRuntimeMessage(`Source retrieval failed: ${error.message}`, "error");
  } finally {
    if (generation === sourceGeneration) button.disabled = false;
  }
}

function rememberIntakeJob(jobId) {
  document.getElementById("knowledge-intake-job").value = jobId;
  try { window.sessionStorage.setItem(intakeStorageKey, jobId); } catch (_error) { /* Optional browser persistence. */ }
}

function showIntakeJob(job) {
  document.getElementById("knowledge-intake-result").textContent = JSON.stringify(job, null, 2);
  const running = ["queued", "running"].includes(job.status);
  document.getElementById("knowledge-intake-start").disabled = running;
  if (job.result?.next_cursor) document.getElementById("knowledge-intake-cursor").value = job.result.next_cursor;
  window.clearTimeout(intakeTimer);
  if (running) intakeTimer = window.setTimeout(() => checkIntakeJob(), 1000);
  return running;
}

async function checkIntakeJob() {
  window.clearTimeout(intakeTimer);
  const jobId = document.getElementById("knowledge-intake-job").value.trim();
  if (!/^[a-f0-9]{32}$/.test(jobId)) {
    setRuntimeMessage("Enter the 32-character job ID returned by archive intake.", "error");
    return;
  }
  try {
    const job = await fetchJson(`/api/knowledge/markdown/intake/${encodeURIComponent(jobId)}`);
    rememberIntakeJob(jobId);
    const running = showIntakeJob(job);
    if (!running) await refreshStatus();
  } catch (error) {
    document.getElementById("knowledge-intake-start").disabled = false;
    document.getElementById("knowledge-intake-result").textContent = `Job check failed: ${error.message}`;
    setRuntimeMessage(`Archive intake job check failed: ${error.message}`, "error");
  }
}

async function startIntake() {
  window.clearTimeout(intakeTimer);
  const button = document.getElementById("knowledge-intake-start");
  button.disabled = true;
  try {
    const job = await postJson("/api/knowledge/markdown/intake", {
      run_id: document.getElementById("knowledge-intake-run").value.trim(),
      limit: boundedInteger(document.getElementById("knowledge-intake-limit").value, 1, 500, 100),
      cursor: document.getElementById("knowledge-intake-cursor").value.trim(),
    });
    rememberIntakeJob(job.job_id);
    showIntakeJob(job);
    setRuntimeMessage("Archive intake queued. The saved job can be checked after a page reload.", "ready");
  } catch (error) {
    button.disabled = false;
    document.getElementById("knowledge-intake-result").textContent = `Archive intake failed: ${error.message}`;
    setRuntimeMessage(`Archive intake failed: ${error.message}`, "error");
  }
}

async function activateTab(name, preserveTarget=false, navigation=++workspaceNavigationGeneration) {
  const hash=window.location.hash;
  Object.values(scopedKnowledgeViews).forEach(view=>view.clear());
  name = AX4LABKnowledgeWorkspace.normalizeTab(name);
  document.querySelectorAll("[data-knowledge-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.knowledgeTab === name);
    button.setAttribute("aria-pressed", String(button.dataset.knowledgeTab === name));
  });
  document.querySelectorAll("[data-knowledge-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.knowledgePanel === name));
  if (name === "memory") window.requestAnimationFrame(renderActivity);
  if (scopedKnowledgeViews[name]) await scopedKnowledgeViews[name].refresh();
  if(navigation!==workspaceNavigationGeneration || hash!==window.location.hash) return;
  if (!preserveTarget && window.location.hash !== `#${name}`) window.history.replaceState(null, "", `#${name}`);
}

async function refreshWorkspace() {
  const button = document.getElementById("knowledge-refresh");
  button.disabled = true;
  setRuntimeMessage("Refreshing Knowledge Workspace…", "busy");
  const results = await Promise.allSettled([refreshStatus(), refreshOntology(), refreshMemory(), refreshActivity(), refreshManualStatus(), refreshScopedKnowledge()]);
  const failed = results.filter((result) => result.status === "rejected");
  await queryMarkdown();
  if (failed.length) setRuntimeMessage(`${failed.length} Knowledge sections could not be refreshed: ${failed.map((item) => item.reason.message).join("; ")}`, "error");
  button.disabled = false;
}

document.querySelectorAll("[data-knowledge-tab]").forEach((button) => button.addEventListener("click", () => activateTab(button.dataset.knowledgeTab)));
document.getElementById("knowledge-refresh").addEventListener("click", refreshWorkspace);
document.getElementById("knowledge-markdown-form").addEventListener("submit", (event) => { event.preventDefault(); queryMarkdown(); });
document.getElementById("knowledge-markdown-form").addEventListener("input", invalidateMarkdownResults);
document.getElementById("knowledge-manual-form").addEventListener("submit", (event) => { event.preventDefault(); queryManuals(); });
document.getElementById("knowledge-manual-ingest").addEventListener("click", ingestManuals);
document.getElementById("knowledge-source-enable").addEventListener("change", async event => {
  const control = event.target;
  control.disabled = true;
  try { await postJson("/api/knowledge/sources/settings", {enabled: control.checked}); await refreshManualStatus(); }
  catch (error) { control.checked = !control.checked; setRuntimeMessage(error.message, "error"); }
  finally { control.disabled = false; }
});
document.getElementById("knowledge-manual-form").addEventListener("input", () => {
  sourceGeneration += 1;
  sourceDetailGeneration += 1;
  document.getElementById("knowledge-manual-run-query").disabled = false;
  document.getElementById("knowledge-source-detail").replaceChildren(element("p", "Apply changed filters to retrieve current evidence."));
  document.getElementById("knowledge-manual-results").replaceChildren(element("p", "Apply changed filters."));
});
let sourceTimer = null;
async function pollSources() {
  try {
    if (!document.hidden && document.querySelector('[data-knowledge-panel="manuals"].active')) await refreshManualStatus();
  } catch (error) { setRuntimeMessage(`Source status unavailable: ${error.message}`, "error"); }
  sourceTimer = window.setTimeout(pollSources, 5000);
}
sourceTimer = window.setTimeout(pollSources, 5000);
window.addEventListener("pagehide", () => window.clearTimeout(sourceTimer));
document.getElementById("knowledge-intake-form").addEventListener("submit", (event) => { event.preventDefault(); startIntake(); });
document.getElementById("knowledge-intake-refresh").addEventListener("click", checkIntakeJob);
window.addEventListener("resize", () => activityChart?.resize());
window.addEventListener("pagehide", () => window.clearTimeout(intakeTimer));
try { document.getElementById("knowledge-intake-job").value = window.sessionStorage.getItem(intakeStorageKey) || ""; } catch (_error) { /* Optional browser persistence. */ }
async function openWorkspaceLocation() {
  const navigation=++workspaceNavigationGeneration;
  const hash=window.location.hash, target=AX4LABKnowledgeWorkspace.parseTarget(hash);
  await activateTab(target.tab,true,navigation);
  if(navigation!==workspaceNavigationGeneration || hash!==window.location.hash) return;
  await AX4LABKnowledgeWorkspace.openTarget(scopedKnowledgeViews,hash);
}
refreshWorkspace().then(openWorkspaceLocation).catch((error) => setRuntimeMessage(`Workspace initialization failed: ${error.message}`, "error"));
window.addEventListener('hashchange',()=>openWorkspaceLocation().catch(()=>setRuntimeMessage('Knowledge target unavailable.','error')));
async function resyncScopedKnowledge() {
  try { if (!document.hidden) await refreshScopedKnowledge(); }
  catch (error) { document.getElementById('knowledge-workspace-summary').textContent = 'Knowledge scope unavailable. Refresh to retry.'; if([401,403].includes(error.status)) Object.values(scopedKnowledgeViews).forEach(view => view.clear()); }
  workspaceResyncTimer = window.setTimeout(resyncScopedKnowledge, 5000);
}
workspaceResyncTimer = window.setTimeout(resyncScopedKnowledge, 5000);
window.addEventListener('ax4lab:knowledge-changed', () => { window.clearTimeout(workspaceResyncTimer); resyncScopedKnowledge(); });
window.addEventListener('pagehide', () => { window.clearTimeout(workspaceResyncTimer); Object.values(scopedKnowledgeViews).forEach(view => view.clear()); });
