/*
File purpose:
- Standalone Module Management Tool frontend logic.
*/

const statusDot = document.getElementById("mm-status-dot");
const statusLabel = document.getElementById("mm-status-label");
const statusDetail = document.getElementById("mm-status-detail");
const moduleListOutput = document.getElementById("mm-module-list");
const loadedStrip = document.getElementById("mm-loaded-strip");
const moduleCount = document.getElementById("mm-module-count");
const searchInput = document.getElementById("mm-search");
const activeModuleBadge = document.getElementById("mm-active-module");
const workbench = document.getElementById("mm-workbench");
const actionOutput = document.getElementById("mm-action-output");
const refreshBtn = document.getElementById("mm-refresh-btn");
const openIdeBtn = document.getElementById("mm-open-ide-btn");
const saveConfigQuickBtn = document.getElementById("mm-save-config-quick-btn");
const saveConfigBtn = document.getElementById("mm-save-config-btn");
const registerGeneratedBtn = document.getElementById("mm-register-generated-btn");
const loadBtn = document.getElementById("mm-load-btn");
const unloadBtn = document.getElementById("mm-unload-btn");
const validateBtn = document.getElementById("mm-validate-btn");
const dryRunBtn = document.getElementById("mm-dry-run-btn");
const versionsBtn = document.getElementById("mm-versions-btn");
const versionOutput = document.getElementById("mm-version-output");
const createBtn = document.getElementById("mm-create-btn");
const createDraftBtn = document.getElementById("mm-create-draft-btn");
const designerModuleIdInput = document.getElementById("mm-designer-module-id");
const designerLabelInput = document.getElementById("mm-designer-label");
const designerCategoryInput = document.getElementById("mm-designer-category");
const designerHandlerSelect = document.getElementById("mm-designer-handler");
const designerLlmRoleInput = document.getElementById("mm-designer-llm-role");
const designerPythonFileInput = document.getElementById("mm-designer-python-file");
const designerNotesInput = document.getElementById("mm-designer-notes");
const designerStatus = document.getElementById("mm-designer-status");
const configModuleSelect = document.getElementById("mm-config-module-select");
const configTabsOutput = document.getElementById("mm-config-tabs");
const configSummaryOutput = document.getElementById("mm-config-summary");
const configStepsOutput = document.getElementById("mm-config-steps");
const dryRunEvidenceOutput = document.getElementById("mm-dry-run-evidence");
const configJsonInput = document.getElementById("mm-config-json");
const configStatus = document.getElementById("mm-config-status");
const applyConfigBtn = document.getElementById("mm-config-apply-btn");
const validateConfigBtn = document.getElementById("mm-config-validate-btn");
const dryRunConfigBtn = document.getElementById("mm-config-dry-run-btn");

let modules = [];
let handlers = [];
let availableTools = [];
let loadedIds = new Set();
let selectedModuleId = "";
let activeModulePayload = null;
let activeModuleBaseline = null;
let activeModuleLifecycle = null;
let activeModuleRuntimeEffect = null;
let searchQuery = "";
let moduleGraphUsage = new Map();
let lastDryRunResult = null;
let hasUnappliedFormEdits = false;
let moduleEvidence = { validation: null, dry_run: null, dirty: false, reason: "initial" };
let moduleStepDragState = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

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
  artifact: "/static/runtime_icons/artifact.svg",
};

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
  return `<span class="runtime-ide-node-icon">${escapeHtml(String(key || "mod").slice(0, 2).toUpperCase())}</span>`;
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(data.detail || data.message || `${response.status} ${response.statusText}`);
  return data;
}

function setStatus(kind, label, detail = "") {
  statusDot.className = `status-dot ${kind}`;
  statusLabel.textContent = label;
  statusDetail.textContent = detail;
}

function setConfigStatus(message, kind = "idle") {
  if (!configStatus) return;
  configStatus.className = `hint module-management-config-status ${kind}`;
  configStatus.textContent = message;
}

function handlerOptions(selected = "", options = {}) {
  const values = Array.from(new Set([...handlers, selected].filter(Boolean))).sort();
  const blank = options.allowBlank ? `<option value=""${selected ? "" : " selected"}>${escapeHtml(options.blankLabel || "checkpoint / no step handler")}</option>` : "";
  return `${blank}${values.map((handler) => `<option value="${escapeHtml(handler)}"${handler === selected ? " selected" : ""}>${escapeHtml(handler)}</option>`).join("")}`;
}

function selectedModule() {
  return modules.find((module) => module.id === selectedModuleId) || null;
}

function normalizedModulePayload(payload) {
  return payload?.module ? payload : { module: payload || {} };
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

function moduleConfigFingerprint(payload) {
  return JSON.stringify(stableConfigValue(normalizedModulePayload(payload)));
}

function activeModuleConfigDiff(payload = activeModulePayload) {
  const baseline = activeModuleBaseline ? moduleConfigFingerprint(activeModuleBaseline) : "";
  const draft = payload ? moduleConfigFingerprint(payload) : "";
  return { changed: Boolean(baseline && draft && baseline !== draft), baseline, draft };
}

function markModuleDraftDirty(reason = "draft changed") {
  moduleEvidence = { validation: null, dry_run: null, dirty: true, reason };
  lastDryRunResult = lastDryRunResult ? { ...lastDryRunResult, stale: true, stale_reason: reason } : null;
}

function resetModuleEvidence(reason = "active config loaded") {
  moduleEvidence = { validation: null, dry_run: null, dirty: false, reason };
  hasUnappliedFormEdits = false;
  lastDryRunResult = null;
}

function evidenceMatchesCurrentDraft(kind, payload = activeModulePayload) {
  const evidence = moduleEvidence[kind];
  if (!evidence?.ok || !payload) return false;
  return evidence.fingerprint === moduleConfigFingerprint(payload);
}

function canonicalModuleId(value) {
  const raw = String(value || "").trim().replaceAll("\\", "/");
  if (!raw) return "";
  const parts = raw.split("/").filter(Boolean);
  const moduleIndex = parts.lastIndexOf("modules");
  if (moduleIndex >= 0 && parts[moduleIndex + 1]) return parts[moduleIndex + 1];
  if (parts.at(-1) === "module.yaml" && parts.length > 1) return parts.at(-2);
  return parts.at(-1) || raw;
}

function moduleRefFromNode(node = {}) {
  return canonicalModuleId(node.module_id || node.module || node.metadata?.module_id || node.metadata?.module || "");
}

function usageForModule(moduleId) {
  return moduleGraphUsage.get(canonicalModuleId(moduleId)) || [];
}

function runtimeIdeUsageLink(item = {}) {
  const params = new URLSearchParams();
  if (item.graph_id) params.set("graph", item.graph_id);
  if (item.node_id) params.set("node", item.node_id);
  else if (item.stage) params.set("stage", item.stage);
  return `/ide${params.toString() ? `?${params.toString()}` : ""}`;
}

function runtimeIdeModuleAttachLink(moduleId = "") {
  const params = new URLSearchParams();
  const clean = String(moduleId || "").trim();
  if (clean) params.set("module", clean);
  params.set("action", "attach");
  return `/ide?${params.toString()}`;
}

function openRuntimeIdeForSelectedModule() {
  const usage = usageForModule(selectedModuleId)[0];
  window.open(usage ? runtimeIdeUsageLink(usage) : runtimeIdeModuleAttachLink(selectedModuleId), "_blank", "noopener");
}

function jumpToConfigSection(selector = "") {
  const target = selector ? document.querySelector(selector) : null;
  if (!target) {
    setConfigStatus(`section not found: ${selector || "unknown"}`, "warn");
    return;
  }
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  target.classList.remove("module-management-jump-focus");
  void target.offsetWidth;
  target.classList.add("module-management-jump-focus");
  window.setTimeout(() => target.classList.remove("module-management-jump-focus"), 1500);
  setConfigStatus(`focused ${selector}`, "ok");
}

function moduleUsageImpactMarkup(usage = [], options = {}) {
  if (!usage.length) return `<small>No active graph node references this module yet.</small>`;
  const compact = Boolean(options.compact);
  return usage.map((item) => `
    <div class="module-management-impact-row${compact ? " compact" : ""}">
      <span>${escapeHtml(item.graph_name)} / ${escapeHtml(item.node_label)} · graph=${escapeHtml(item.graph_id)} · stage=${escapeHtml(item.stage || "n/a")} · node_handler=${escapeHtml(item.handler || "n/a")}</span>
      <a class="btn tiny module-management-usage-open" href="${escapeHtml(runtimeIdeUsageLink(item))}" target="_blank" rel="noopener">Open Node</a>
    </div>
  `).join("");
}

async function refreshGraphUsageIndex() {
  const list = await requestJson("/api/graphs").catch(() => ({ graphs: [] }));
  const graphItems = Array.isArray(list.graphs) ? list.graphs : [];
  const usageMap = new Map();
  const graphDetails = await Promise.all(
    graphItems.map((item) =>
      requestJson(`/api/graphs/${item.id}`)
        .then((detail) => ({ item, detail }))
        .catch(() => null),
    ),
  );
  for (const entry of graphDetails.filter(Boolean)) {
    const graph = entry.detail?.graph?.graph || entry.detail?.graph || {};
    const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    for (const node of nodes) {
      const moduleId = moduleRefFromNode(node);
      if (!moduleId) continue;
      if (!usageMap.has(moduleId)) usageMap.set(moduleId, []);
      usageMap.get(moduleId).push({
        graph_id: graph.id || entry.item.id,
        graph_name: graph.name || entry.item.name || entry.item.id,
        node_id: node.id || "",
        node_label: node.label || node.id || "",
        stage: node.stage || "",
        handler: node.handler || "",
        kind: node.kind || "agent",
      });
    }
  }
  moduleGraphUsage = usageMap;
}

function moduleLlm(module) {
  return module.llm && typeof module.llm === "object" && !Array.isArray(module.llm) ? module.llm : {};
}

function modulePrompt(module) {
  if (typeof module.prompt === "string") return { system: module.prompt };
  return module.prompt && typeof module.prompt === "object" && !Array.isArray(module.prompt) ? module.prompt : {};
}

function moduleSupervisorPolicy(module) {
  return module.supervisor_policy && typeof module.supervisor_policy === "object" && !Array.isArray(module.supervisor_policy)
    ? module.supervisor_policy
    : {};
}

function moduleStepsForPhase(module, phase = "internal_graph") {
  module.pre_execution = Array.isArray(module.pre_execution) ? module.pre_execution : [];
  module.internal_graph = Array.isArray(module.internal_graph) ? module.internal_graph : [];
  return phase === "pre_execution" ? module.pre_execution : module.internal_graph;
}

function stepExecutionState(step = {}, phase = "internal_graph") {
  if (step.enabled === false) return "disabled";
  if (phase === "pre_execution") return step.handler ? "executable" : "missing-handler";
  return step.handler ? "executable" : "checkpoint";
}

function stepStatusLabel(state = "") {
  if (state === "executable") return "exec";
  if (state === "checkpoint") return "checkpoint";
  if (state === "disabled") return "disabled";
  if (state === "missing-handler") return "handler required";
  return "step";
}

function duplicateStepIdSet(steps = []) {
  const counts = new Map();
  for (const step of steps) {
    const id = String(step?.id || "").trim();
    if (!id) continue;
    counts.set(id, (counts.get(id) || 0) + 1);
  }
  return new Set(Array.from(counts.entries()).filter(([, count]) => count > 1).map(([id]) => id));
}

function moduleTextLines(value) {
  if (Array.isArray(value)) return value.join("\n");
  if (value === undefined || value === null) return "";
  return String(value);
}

function parseLineList(value) {
  return String(value || "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
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

function jsonTextareaValue(value, fallback = []) {
  try {
    return JSON.stringify(value === undefined || value === null ? fallback : value, null, 2);
  } catch (err) {
    return JSON.stringify(fallback, null, 2);
  }
}

function readJsonArrayInput(id, label) {
  const raw = document.getElementById(id)?.value?.trim() || "";
  if (!raw) return [];
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new Error(`${label} must be valid JSON array: ${err.message || err}`);
  }
  if (!Array.isArray(parsed)) throw new Error(`${label} must be a JSON array`);
  return parsed;
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

function compactJson(value, limit = 900) {
  try {
    const text = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
    return text.length > limit ? `${text.slice(0, limit)}
... truncated` : text;
  } catch (err) {
    return String(value || "").slice(0, limit);
  }
}

function invalidateDryRunEvidence(reason = "draft changed") {
  markModuleDraftDirty(reason);
  renderDryRunEvidence();
}

function setConfigPayload(payload, options = {}) {
  const normalized = normalizedModulePayload(payload);
  activeModulePayload = normalized;
  if (options.baseline) {
    activeModuleBaseline = cloneConfig(normalized);
    resetModuleEvidence(options.reason || "active config loaded");
  } else if (options.markDirty !== false && activeModuleBaseline && activeModuleConfigDiff(normalized).changed) {
    markModuleDraftDirty(options.reason || "draft changed");
  }
  if (configJsonInput) configJsonInput.value = JSON.stringify(normalized, null, 2);
  if (options.render !== false) renderConfigWorkspace(normalized);
}

function parseConfigEditor() {
  try {
    return normalizedModulePayload(JSON.parse(configJsonInput?.value || "{}"));
  } catch (err) {
    throw new Error(`Module JSON parse failed: ${err.message || err}`);
  }
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
      <p class="hint">ToolRegistry list is unavailable. Manual allowlist is preserved.</p>
      <textarea id="mm-config-tools" class="runtime-module-small-textarea" spellcheck="false">${escapeHtml(manualValue)}</textarea>
    `;
  }
  return `
    <div class="runtime-module-tool-groups module-management-tool-groups">
      ${Array.from(groups.entries()).map(([group, tools]) => `
        <div class="runtime-module-tool-group">
          <strong>${escapeHtml(group)}</strong>
          <div class="runtime-module-tool-list">
            ${tools.map((tool) => `
              <label class="runtime-module-tool-chip">
                <input type="checkbox" data-mm-config-tool-checkbox value="${escapeHtml(tool)}" ${selected.has(tool) ? "checked" : ""} />
                <span>${escapeHtml(tool)}</span>
              </label>
            `).join("")}
          </div>
        </div>
      `).join("")}
    </div>
    <details class="runtime-module-custom-tools">
      <summary><span>Custom / unregistered tools</span><small>one per line</small></summary>
      <textarea id="mm-config-tools" class="runtime-module-small-textarea" spellcheck="false">${escapeHtml(manualValue)}</textarea>
    </details>
  `;
}

function renderLoadedStrip() {
  const loaded = modules.filter((module) => loadedIds.has(module.id));
  loadedStrip.innerHTML = loaded.length
    ? `
      <div class="module-management-loaded-title">
        <strong>Loaded in management workspace</strong>
        <small>chips refocus a loaded module; unload is only in Workbench actions</small>
      </div>
      <div class="module-management-loaded-chip-row">
        ${loaded.map((module) => `<button type="button" class="module-management-loaded-chip" data-load-chip="${escapeHtml(module.id)}">${runtimeNodeIconMarkup(moduleIconName(module))}<span>${escapeHtml(module.label || module.id)}</span></button>`).join("")}
      </div>
    `
    : `<div class="module-management-empty">No loaded modules in management workspace.</div>`;
  loadedStrip.querySelectorAll("[data-load-chip]").forEach((button) => {
    button.addEventListener("click", () => selectModule(button.getAttribute("data-load-chip") || ""));
  });
}

function renderModuleList() {
  const q = searchQuery.trim().toLowerCase();
  const filtered = modules.filter((module) => {
    const haystack = `${module.id} ${module.label || ""} ${module.category || ""} ${module.handler || ""}`.toLowerCase();
    return !q || haystack.includes(q);
  });
  moduleCount.textContent = `${modules.length} modules`;
  moduleListOutput.innerHTML = filtered.length
    ? filtered.map((module) => {
        const active = module.id === selectedModuleId ? " active" : "";
        const loaded = loadedIds.has(module.id);
        return `
          <button type="button" class="module-management-item${active}" data-module-id="${escapeHtml(module.id)}">
            ${runtimeNodeIconMarkup(moduleIconName(module))}
            <span class="module-management-item-copy">
              <strong>${escapeHtml(module.label || module.id)}</strong>
              <small>${escapeHtml(module.category || "runtime")} · ${escapeHtml(module.handler || "runtime.step_complete")}${module.pending_handler_registration ? " · generated pending" : module.generated_adapter_approved ? " · generated approved" : ""}</small>
            </span>
            <em class="module-management-list-state ${loaded ? "loaded" : "select-only"}">${loaded ? "Loaded" : "Select only"}</em>
          </button>
        `;
      }).join("")
    : `<div class="module-management-empty">No module matches the filter.</div>`;
  moduleListOutput.querySelectorAll("[data-module-id]").forEach((button) => {
    button.addEventListener("click", () => selectModule(button.getAttribute("data-module-id") || ""));
  });
  renderLoadedStrip();
}

function renderConfigTabs() {
  if (!configTabsOutput) return;
  if (!modules.length) {
    configTabsOutput.innerHTML = `<div class="runtime-module-tab-empty">No modules loaded.</div>`;
    return;
  }
  configTabsOutput.innerHTML = modules.map((module) => {
    const active = module.id === selectedModuleId ? " active" : "";
    return `<button class="runtime-module-tab${active}" type="button" data-mm-config-tab="${escapeHtml(module.id)}">
      ${runtimeNodeIconMarkup(moduleIconName(module))}
      <span class="runtime-module-tab-copy">
        <strong>${escapeHtml(module.label || module.id)}</strong>
        <small>${escapeHtml(module.category || "runtime")} · ${escapeHtml(module.handler || "handler")}</small>
      </span>
    </button>`;
  }).join("");
  configTabsOutput.querySelectorAll("[data-mm-config-tab]").forEach((button) => {
    button.addEventListener("click", () => selectModule(button.getAttribute("data-mm-config-tab") || ""));
  });
}

function modulePreflightStatus(payload = activeModulePayload) {
  const diff = activeModuleConfigDiff(payload);
  const validationOk = evidenceMatchesCurrentDraft("validation", payload);
  const dryRunOk = evidenceMatchesCurrentDraft("dry_run", payload);
  const issues = [];
  if (!payload?.module?.id && !selectedModuleId) issues.push("No module draft is selected.");
  if (hasUnappliedFormEdits) issues.push("Apply Draft is required because form edits are not reflected in raw module JSON yet.");
  if (diff.changed && !validationOk) issues.push("Validate the current module draft before saving.");
  if (diff.changed && !dryRunOk) issues.push("Dry-run the current module draft before saving.");
  return {
    ready: issues.length === 0,
    diff,
    validationOk,
    dryRunOk,
    issues,
    dirty: moduleEvidence.dirty || diff.changed,
    reason: moduleEvidence.reason || "pending",
  };
}

function modulePreflightMarkup(payload = activeModulePayload) {
  const status = modulePreflightStatus(payload);
  const items = [
    { label: "Draft", ok: !hasUnappliedFormEdits, detail: hasUnappliedFormEdits ? "apply draft first" : status.diff.changed ? "changed draft applied" : "active config clean" },
    { label: "Validate", ok: status.validationOk || !status.diff.changed, detail: status.validationOk ? "current draft validated" : status.diff.changed ? "required" : "not needed" },
    { label: "Dry-run", ok: status.dryRunOk || !status.diff.changed, detail: status.dryRunOk ? "current draft simulated" : status.diff.changed ? "required" : "not needed" },
    { label: "Save", ok: status.ready, detail: status.ready ? "allowed" : "blocked" },
  ];
  return `
    <div class="module-management-preflight ${status.ready ? "ok" : "warn"}">
      <div class="module-management-preflight-head">
        <strong>${escapeHtml(status.ready ? "Module save preflight ready" : "Module save preflight blocked")}</strong>
        <span>${escapeHtml(status.reason)}</span>
      </div>
      <div class="module-management-preflight-items">
        ${items.map((item) => `
          <span class="${item.ok ? "ok" : "warn"}">
            <strong>${escapeHtml(item.ok ? "OK" : "BLOCK")}</strong>
            <small>${escapeHtml(item.label)}</small>
            <em>${escapeHtml(item.detail)}</em>
          </span>
        `).join("")}
      </div>
      ${status.issues.length ? `<ul>${status.issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>` : `<p>Saving will version and activate the selected module config.</p>`}
    </div>
  `;
}

function refreshModulePreflightCard(payload = activeModulePayload) {
  const card = configSummaryOutput?.querySelector?.(".module-management-preflight");
  if (card) card.outerHTML = modulePreflightMarkup(payload);
}

function supervisorPolicyGateMarkup(gate = {}) {
  if (!gate || typeof gate !== "object" || Array.isArray(gate) || !gate.present) return "";
  const required = Array.isArray(gate.required_outputs) ? gate.required_outputs : [];
  const declared = Array.isArray(gate.declared_outputs) ? gate.declared_outputs : [];
  const missingOutputs = Array.isArray(gate.missing_outputs) ? gate.missing_outputs : [];
  const row = (label, values, fallback = "none") => `
    <span>
      <strong>${escapeHtml(label)}</strong>
      <small>${escapeHtml(values.length ? values.join(", ") : fallback)}</small>
    </span>
  `;
  return `
    <div class="module-management-lifecycle-gate ${gate.ok ? "ok" : "warn"}">
      <span class="${gate.ok ? "ok" : "warn"}">${escapeHtml(gate.ok ? "OK" : "BLOCK")}</span>
      <small>Supervisor required outputs</small>
    </div>
    <div class="module-management-requirements">
      ${row("required_outputs", required)}
      ${row("declared_outputs", declared)}
      ${row("missing_outputs", missingOutputs)}
    </div>
  `;
}

function renderModuleLifecycle(lifecycle = activeModuleLifecycle, runtimeEffect = activeModuleRuntimeEffect) {
  if (!lifecycle && !runtimeEffect) return "";
  const state = lifecycle && typeof lifecycle === "object" && !Array.isArray(lifecycle) ? lifecycle : {};
  const effect = runtimeEffect && typeof runtimeEffect === "object" && !Array.isArray(runtimeEffect) ? runtimeEffect : {};
  const runtimeChange = effect.changes_runtime_execution ? "runtime execution changes" : "no runtime execution change";
  const graphChange = effect.changes_graph_config ? "graph config changes" : "no graph config change";
  const requirements = Array.isArray(state.activation_requirements) ? state.activation_requirements : [];
  const supervisor_policy_gate = state.supervisor_policy_gate && typeof state.supervisor_policy_gate === "object" && !Array.isArray(state.supervisor_policy_gate)
    ? state.supervisor_policy_gate
    : {};
  return `
    <div class="module-management-section module-management-lifecycle-section">
      <strong>Management-only load lifecycle</strong>
      <p>${escapeHtml(effect.scope || "management_workspace")} · ${escapeHtml(runtimeChange)} · ${escapeHtml(graphChange)}</p>
      <small>changes_runtime_execution=${escapeHtml(String(Boolean(effect.changes_runtime_execution)))}</small>
      <div class="module-management-kpis compact">
        <span><strong>${escapeHtml(state.module_status || "unknown")}</strong><small>status</small></span>
        <span><strong>${escapeHtml(state.activation_status || "unknown")}</strong><small>activation_status</small></span>
        <span><strong>${escapeHtml(state.graph_attached ? "yes" : "no")}</strong><small>graph</small></span>
        <span><strong>${escapeHtml(state.executable_count ?? 0)}</strong><small>exec</small></span>
      </div>
      <div class="module-management-lifecycle-gate">
        <span class="${state.ready_for_live_activation ? "ok" : "warn"}">${escapeHtml(state.ready_for_live_activation ? "READY" : "NOT READY")}</span>
        <small>next_required_action=${escapeHtml(state.next_required_action || "none")}</small>
      </div>
      ${requirements.length ? `
        <div class="module-management-requirements">
          ${requirements.map((item) => `
            <span class="${item.ok ? "ok" : "warn"}">
              <strong>${escapeHtml(item.ok ? "OK" : "BLOCK")}</strong>
              <small>${escapeHtml(item.id || item.label || "activation_requirement")}</small>
            </span>
          `).join("")}
        </div>
      ` : ""}
      ${supervisorPolicyGateMarkup(supervisor_policy_gate)}
    </div>
  `;
}

function renderModulePayload(modulePayload, loaded = loadedIds.has(selectedModuleId)) {
  const module = modulePayload?.module || {};
  const tools = Array.isArray(module.tools) ? module.tools : [];
  const metadata = module.metadata && typeof module.metadata === "object" && !Array.isArray(module.metadata) ? module.metadata : {};
  const generatedState = metadata.generated_adapter_approved ? "approved" : metadata.pending_handler_registration ? "pending registration" : "not generated";
  const pre = Array.isArray(module.pre_execution) ? module.pre_execution : [];
  const internal = Array.isArray(module.internal_graph) ? module.internal_graph : [];
  const usage = usageForModule(module.id || selectedModuleId);
  workbench.innerHTML = `
    <div class="module-management-detail-head">
      <div class="module-management-title-wrap">
        ${runtimeNodeIconMarkup(moduleIconName(module))}
        <div>
          <span class="runtime-module-id-pill">${escapeHtml(module.id || selectedModuleId)}</span>
          <h3>${escapeHtml(module.label || module.id || selectedModuleId)}</h3>
          <p>${escapeHtml(module.handler || "runtime.step_complete")} · ${escapeHtml(module.llm_role || "inherit")}</p>
        </div>
      </div>
      <div class="module-management-state-badge ${loaded ? "loaded" : "unloaded"}">${loaded ? "Loaded" : "Not loaded"}</div>
    </div>
    <div class="module-management-kpis">
      <span><strong>${escapeHtml(tools.length)}</strong><small>tools</small></span>
      <span><strong>${escapeHtml(pre.length)}</strong><small>pre</small></span>
      <span><strong>${escapeHtml(internal.length)}</strong><small>internal</small></span>
      <span><strong>${escapeHtml(usage.length)}</strong><small>graph refs</small></span>
    </div>
    ${renderModuleLifecycle()}
    <div class="module-management-section module-management-impact-section">
      <strong>Graph Usage / Runtime Impact</strong>
      ${
        usage.length
          ? `<div class="module-management-usage-list">
              ${usage
                .map(
                  (item) => `
                    <div class="module-management-usage-item">
                      <span><strong>${escapeHtml(item.graph_name)}</strong><small>${escapeHtml(item.graph_id)}</small></span>
                      <span><strong>${escapeHtml(item.node_label)}</strong><small>${escapeHtml(item.node_id)} · stage=${escapeHtml(item.stage || "n/a")}</small></span>
                      <span><strong>${escapeHtml(item.handler || "handler")}</strong><small>${escapeHtml(item.kind || "agent")}</small></span>
                      <span class="module-management-usage-actions"><a class="btn tiny module-management-usage-open" href="${escapeHtml(runtimeIdeUsageLink(item))}" target="_blank" rel="noopener">Open Node</a></span>
                    </div>
                  `,
                )
                .join("")}
            </div>`
          : `<p>No active graph node currently references this module. Saving the module only updates its module.yaml until a graph node points to it.</p>`
      }
    </div>
    <div class="module-management-section">
      <strong>Generated adapter registration</strong>
      <p>${escapeHtml(generatedState)} · ${escapeHtml(metadata.generated_adapter_handler_id || "module.generated_adapter")}</p>
      <small>${escapeHtml(metadata.generated_adapter_path || metadata.transformed_python_source_path || metadata.transformed_source_path || "handler.py")}</small>
    </div>
    <div class="module-management-section">
      <strong>Tool allowlist</strong>
      <p>${escapeHtml(tools.join(" · ") || "none")}</p>
    </div>
    <div class="module-management-section">
      <strong>Runtime steps</strong>
      ${[...pre.map((step) => ({ ...step, phase: "pre" })), ...internal.map((step) => ({ ...step, phase: "internal" }))]
        .map((step, index) => `<div>${escapeHtml(index + 1)}. [${escapeHtml(step.phase)}] ${escapeHtml(step.label || step.id)} <small>${escapeHtml(step.handler || module.handler || "checkpoint")}</small></div>`)
        .join("") || "<p>no steps</p>"}
    </div>
  `;
}

function renderConfigSummary(modulePayload = activeModulePayload) {
  const module = normalizedModulePayload(modulePayload).module || {};
  const llm = moduleLlm(module);
  const prompt = modulePrompt(module);
  const supervisorPolicy = moduleSupervisorPolicy(module);
  const retry = module.retry && typeof module.retry === "object" && !Array.isArray(module.retry) ? module.retry : {};
  const safety = module.safety && typeof module.safety === "object" && !Array.isArray(module.safety) ? module.safety : {};
  const preCount = Array.isArray(module.pre_execution) ? module.pre_execution.length : 0;
  const internalCount = Array.isArray(module.internal_graph) ? module.internal_graph.length : 0;
  const toolCount = Array.isArray(module.tools) ? module.tools.length : 0;
  configSummaryOutput.innerHTML = `
    ${modulePreflightMarkup(modulePayload)}
    <div class="runtime-module-agent-head">
      <div class="runtime-module-agent-title">
        ${runtimeNodeIconMarkup(moduleIconName(module))}
        <div>
          <span class="runtime-module-id-pill">${escapeHtml(module.id || selectedModuleId || "module")}</span>
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
          <select id="mm-config-handler-select" class="text-input">${handlerOptions(module.handler || "")}</select>
        </label>
        <label class="runtime-handler-select-label">LLM Role
          <input id="mm-config-llm-role" class="text-input" value="${escapeHtml(module.llm_role || "")}" placeholder="inherit route" />
        </label>
      </section>
      <section class="runtime-module-config-card">
        <div class="runtime-module-card-title"><strong>LLM Runtime</strong><small>backend/model override</small></div>
        <label class="runtime-handler-select-label">Backend
          <select id="mm-config-llm-backend" class="text-input">
            ${["", "vllm", "ollama", "nemoclaw", "mock"].map((item) => `<option value="${item}"${item === (llm.backend || "") ? " selected" : ""}>${item || "inherit"}</option>`).join("")}
          </select>
        </label>
        <label class="runtime-handler-select-label">Model
          <input id="mm-config-llm-model" class="text-input" value="${escapeHtml(llm.model || llm.primary || "")}" placeholder="inherit router default" />
        </label>
      </section>
      <section class="runtime-module-config-card">
        <div class="runtime-module-card-title"><strong>Execution Policy</strong><small>retry, timeout, approval</small></div>
        <div class="runtime-module-two-col">
          <label class="runtime-handler-select-label">Timeout seconds
            <input id="mm-config-timeout" class="text-input" type="number" min="0" step="1" value="${escapeHtml(module.timeout_s ?? "")}" />
          </label>
          <label class="runtime-handler-select-label">Retry max attempts
            <input id="mm-config-retry" class="text-input" type="number" min="0" max="10" step="1" value="${escapeHtml(retry.max_attempts ?? "")}" />
          </label>
        </div>
        <div class="runtime-module-checkboxes">
          <label><input id="mm-config-live-validation" type="checkbox" ${safety.live_requires_validation ? "checked" : ""} /> live validation</label>
          <label><input id="mm-config-dry-run-supported" type="checkbox" ${safety.dry_run_supported !== false ? "checked" : ""} /> dry-run</label>
          <label><input id="mm-config-human-approval" type="checkbox" ${safety.requires_human_approval ? "checked" : ""} /> human approval</label>
        </div>
      </section>
      <section class="runtime-module-config-card wide">
        <div class="runtime-module-card-title"><strong>Tool Allowlist</strong><small>checked tools are callable by this module</small></div>
        ${renderModuleToolPicker(module.tools || [])}
      </section>
      <section class="runtime-module-config-card wide prompt-card">
        <div class="runtime-module-card-title"><strong>Prompt Overrides</strong><small>leave empty to inherit defaults</small></div>
        <label class="runtime-handler-select-label">Prompt path
          <input id="mm-config-prompt-path" class="text-input" value="${escapeHtml(prompt.path || "")}" placeholder="docs/... or prompts/..." />
        </label>
        <div class="runtime-module-two-col prompt-columns">
          <label class="runtime-handler-select-label">System prompt override
            <textarea id="mm-config-prompt-system" class="runtime-module-small-textarea" spellcheck="false">${escapeHtml(prompt.system || "")}</textarea>
          </label>
          <label class="runtime-handler-select-label">Developer prompt override
            <textarea id="mm-config-prompt-developer" class="runtime-module-small-textarea" spellcheck="false">${escapeHtml(prompt.developer || "")}</textarea>
          </label>
        </div>
      </section>
      <section class="runtime-module-config-card wide">
        <div class="runtime-module-card-title"><strong>Supervisor Policy</strong><small>custom Orchestrator follow-up language</small></div>
        <div class="runtime-module-two-col prompt-columns">
          <label class="runtime-handler-select-label">Required outputs
            <textarea id="mm-config-supervisor-required-outputs" class="runtime-module-small-textarea" spellcheck="false" placeholder="one output contract per line">${escapeHtml(moduleTextLines(supervisorPolicy.required_outputs || []))}</textarea>
          </label>
          <label class="runtime-handler-select-label">Response-required statuses
            <textarea id="mm-config-supervisor-response-statuses" class="runtime-module-small-textarea" spellcheck="false" placeholder="blocked&#10;requires_operator_input">${escapeHtml(moduleTextLines(supervisorPolicy.requires_response_on_status || []))}</textarea>
          </label>
        </div>
        <label class="runtime-handler-select-label">Opinion template
          <textarea id="mm-config-supervisor-opinion-template" class="runtime-module-small-textarea" spellcheck="false" placeholder="Custom stage checked status={status} score={metrics.score}.">${escapeHtml(supervisorPolicy.opinion_template || "")}</textarea>
        </label>
        <label class="runtime-handler-select-label">Recommendation template
          <textarea id="mm-config-supervisor-recommendation-template" class="runtime-module-small-textarea" spellcheck="false" placeholder="Continue to {next_stage} after verifying {required_outputs}.">${escapeHtml(supervisorPolicy.recommendation_template || "")}</textarea>
        </label>
        <div class="runtime-module-two-col prompt-columns">
          <label class="runtime-handler-select-label">Concern rules JSON
            <textarea id="mm-config-supervisor-concern-rules" class="runtime-module-small-textarea" spellcheck="false" placeholder='[{"selector":"metrics.score","lt":0.95,"message":"score below target"}]'>${escapeHtml(jsonTextareaValue(supervisorPolicy.concern_rules || []))}</textarea>
          </label>
          <label class="runtime-handler-select-label">Options JSON
            <textarea id="mm-config-supervisor-options" class="runtime-module-small-textarea" spellcheck="false" placeholder='[{"id":"rerun","label":"Rerun check","risk":"low"}]'>${escapeHtml(jsonTextareaValue(supervisorPolicy.options || []))}</textarea>
          </label>
        </div>
      </section>
    </div>
  `;
  document.getElementById("mm-config-handler-select")?.addEventListener("change", (event) => updateModuleHandler(event.target.value));
  configSummaryOutput.querySelectorAll("input, textarea, select").forEach((el) => {
    if (el.id === "mm-config-handler-select") return;
    const eventName = el.getAttribute("type") === "checkbox" ? "change" : "input";
    el.addEventListener(eventName, () => {
      hasUnappliedFormEdits = true;
      markModuleDraftDirty("form edits pending apply");
      setConfigStatus("draft has unapplied form edits", "warn");
      renderDryRunEvidence();
      refreshModulePreflightCard(activeModulePayload);
    });
  });
}

function dryRunPhaseLabel(phase = "internal_graph") {
  return phase === "pre_execution" ? "pre" : "internal";
}

function renderDryRunEvidence(result = lastDryRunResult) {
  if (!dryRunEvidenceOutput) return;
  const module = normalizedModulePayload(activeModulePayload || {}).module || {};
  const usage = usageForModule(module.id || selectedModuleId);
  if (!result) {
    dryRunEvidenceOutput.innerHTML = `
      <div class="module-management-evidence-empty">
        Run module dry-run after editing. The evidence panel will show exact step order, executable handlers, checkpoints, and graph impact.
      </div>
      ${usage.length ? `<div class="module-management-evidence-impact"><strong>Referenced by ${escapeHtml(usage.length)} graph node(s)</strong>${moduleUsageImpactMarkup(usage, { compact: true })}</div>` : ""}
    `;
    return;
  }
  const sequence = Array.isArray(result.sequence) ? result.sequence : [];
  const summary = result.summary && typeof result.summary === "object" ? result.summary : {};
  const status = result.ok ? (result.stale ? "warn" : "ok") : "error";
  dryRunEvidenceOutput.innerHTML = `
    <div class="module-management-evidence-head ${escapeHtml(status)}">
      <span><strong>${escapeHtml(result.ok ? (result.stale ? "STALE" : "DRY-RUN OK") : "DRY-RUN FAILED")}</strong><small>${escapeHtml(result.module_id || selectedModuleId || "module")}</small></span>
      <span><strong>${escapeHtml(summary.step_count ?? sequence.length)}</strong><small>steps</small></span>
      <span><strong>${escapeHtml(summary.executable_count ?? sequence.filter((item) => item.executable).length)}</strong><small>executable</small></span>
      <span><strong>${escapeHtml(summary.checkpoint_count ?? sequence.filter((item) => !item.executable).length)}</strong><small>checkpoints</small></span>
    </div>
    ${result.stale ? `<div class="module-management-evidence-stale">Draft changed after dry-run: ${escapeHtml(result.stale_reason || "run dry-run again")}</div>` : ""}
    ${result.errors?.length ? `<pre>${escapeHtml(compactJson(result.errors))}</pre>` : ""}
    <div class="module-management-evidence-sequence">
      ${sequence.length ? sequence.map((item) => `
        <div class="module-management-evidence-step ${escapeHtml(item.executable ? "executable" : "checkpoint")}">
          <strong>${escapeHtml(item.step)}. [${escapeHtml(dryRunPhaseLabel(item.phase))}] ${escapeHtml(item.label || item.id)}</strong>
          <span>${escapeHtml(item.id || "step")} · ${escapeHtml(item.handler_configured ? (item.handler || item.kind || "handler") : `checkpoint · module handler after graph: ${module.handler || "n/a"}`)}</span>
          <small>${escapeHtml(item.executable ? "handler will execute during real module run" : item.handler_configured ? "handler configured but not executable" : "checkpoint event only; module handler runs once after internal graph")}</small>
        </div>
      `).join("") : `<div class="module-management-evidence-empty">No sequence returned.</div>`}
    </div>
    <div class="module-management-evidence-impact">
      <strong>Graph impact</strong>
      ${moduleUsageImpactMarkup(usage, { compact: true })}
    </div>
  `;
}

function renderConfigSteps(modulePayload = activeModulePayload) {
  const payload = normalizedModulePayload(modulePayload);
  const module = payload.module || {};
  const preSteps = Array.isArray(module.pre_execution) ? module.pre_execution : [];
  const internalSteps = Array.isArray(module.internal_graph) ? module.internal_graph : [];
  const renderSection = (title, hint, phase, steps, defaultKind) => {
    const duplicateIds = duplicateStepIdSet(steps);
    const phaseActions = phase === "internal_graph"
      ? `<button class="btn tiny" type="button" data-mm-module-step-add="${escapeHtml(phase)}" data-mm-module-step-add-mode="checkpoint">Add Checkpoint</button>
         <button class="btn tiny primary" type="button" data-mm-module-step-add="${escapeHtml(phase)}" data-mm-module-step-add-mode="executable">Add Agent Step</button>`
      : `<button class="btn tiny primary" type="button" data-mm-module-step-add="${escapeHtml(phase)}" data-mm-module-step-add-mode="executable">Add Pre Step</button>`;
    const stepCards = steps.length ? steps.map((step, index) => {
      const state = stepExecutionState(step, phase);
      const id = String(step.id || "").trim();
      const hasIssue = !id || duplicateIds.has(id) || state === "missing-handler";
      const issueText = !id ? "missing id" : duplicateIds.has(id) ? "duplicate id" : state === "missing-handler" ? "handler required" : "";
      return `
        <article class="runtime-module-step ${escapeHtml(state)}${hasIssue ? " invalid" : ""}" data-mm-module-step-index="${index}" data-mm-module-step-phase="${escapeHtml(phase)}" data-mm-module-step-drop-index="${index}">
          <div class="runtime-module-step-shell">
            <button class="runtime-module-step-drag-handle" type="button" draggable="true" data-mm-module-step-drag="${index}" data-mm-module-step-phase="${escapeHtml(phase)}" title="Drag to reorder">${escapeHtml(index + 1)}</button>
            <div class="runtime-module-step-main">
              <div class="runtime-module-step-topline">
                <strong>${escapeHtml(step.label || step.id || `${title} ${index + 1}`)}</strong>
                <span class="runtime-module-step-status ${escapeHtml(state)}">${escapeHtml(stepStatusLabel(state))}</span>
              </div>
              <span>${escapeHtml(id || "no-id")} · ${escapeHtml(step.kind || defaultKind)}${step.enabled === false ? " · disabled" : ""}</span>
              ${issueText ? `<em class="runtime-module-step-issue">${escapeHtml(issueText)}</em>` : ""}
            </div>
            <div class="runtime-module-step-actions">
              <button class="btn tiny" type="button" data-mm-module-step-up="${index}" data-mm-module-step-phase="${escapeHtml(phase)}">Up</button>
              <button class="btn tiny" type="button" data-mm-module-step-down="${index}" data-mm-module-step-phase="${escapeHtml(phase)}">Down</button>
              <button class="btn tiny" type="button" data-mm-module-step-duplicate="${index}" data-mm-module-step-phase="${escapeHtml(phase)}">Duplicate</button>
              <button class="btn tiny danger" type="button" data-mm-module-step-delete="${index}" data-mm-module-step-phase="${escapeHtml(phase)}">Delete</button>
            </div>
          </div>
          <details class="runtime-module-step-details" ${hasIssue || index === 0 ? "open" : ""}>
            <summary><span>Edit step config</span><small>${escapeHtml(step.handler || (phase === "internal_graph" ? "checkpoint" : "no handler"))}</small></summary>
            <div class="runtime-module-step-fields">
              <label class="runtime-handler-select-label">id
                <input class="text-input runtime-module-step-field" data-mm-module-step-field="id" data-mm-module-step-index="${index}" data-mm-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.id || "")}" />
              </label>
              <label class="runtime-handler-select-label">label
                <input class="text-input runtime-module-step-field" data-mm-module-step-field="label" data-mm-module-step-index="${index}" data-mm-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.label || "")}" />
              </label>
              <label class="runtime-handler-select-label">kind
                <input class="text-input runtime-module-step-field" data-mm-module-step-field="kind" data-mm-module-step-index="${index}" data-mm-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.kind || defaultKind)}" />
              </label>
              <label class="runtime-handler-select-label">${phase === "internal_graph" ? "step handler (blank = checkpoint)" : "step handler"}
                <select class="text-input runtime-module-step-handler" data-mm-module-step-handler="${index}" data-mm-module-step-phase="${escapeHtml(phase)}">${handlerOptions(step.handler || "", { allowBlank: phase === "internal_graph" })}</select>
              </label>
              ${phase === "pre_execution" ? `
                <label class="runtime-handler-select-label">output key
                  <input class="text-input runtime-module-step-field" data-mm-module-step-field="output_key" data-mm-module-step-index="${index}" data-mm-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.output_key || "")}" />
                </label>
                <label class="runtime-handler-select-label">event type
                  <input class="text-input runtime-module-step-field" data-mm-module-step-field="event_type" data-mm-module-step-index="${index}" data-mm-module-step-phase="${escapeHtml(phase)}" value="${escapeHtml(step.event_type || "")}" />
                </label>
                <label class="runtime-module-step-enabled">
                  <input type="checkbox" data-mm-module-step-field="enabled" data-mm-module-step-index="${index}" data-mm-module-step-phase="${escapeHtml(phase)}" ${step.enabled === false ? "" : "checked"} /> enabled
                </label>
              ` : `
                <label class="runtime-module-step-enabled">
                  <input type="checkbox" data-mm-module-step-field="enabled" data-mm-module-step-index="${index}" data-mm-module-step-phase="${escapeHtml(phase)}" ${step.enabled === false ? "" : "checked"} /> enabled
                </label>
              `}
            </div>
          </details>
        </article>
      `;
    }).join("") : `<div class="runtime-module-empty">No ${escapeHtml(title.toLowerCase())} steps.</div>`;
    return `
      <div class="runtime-module-step-section" data-module-step-section="${escapeHtml(phase)}" data-mm-module-step-section-drop="${escapeHtml(phase)}">
        <div class="panel-title-row runtime-ide-subtitle runtime-module-step-section-head">
          <div>
            <h3>${escapeHtml(title)}</h3>
            <span class="hint">${escapeHtml(hint)} · ${steps.length} step(s)</span>
          </div>
          <div class="button-row compact-row runtime-module-step-section-actions">${phaseActions}</div>
        </div>
        <div class="runtime-module-step-lane" data-mm-module-step-lane="${escapeHtml(phase)}">
          ${stepCards}
        </div>
      </div>
    `;
  };
  configStepsOutput.innerHTML = `
    ${renderSection("Pre-Execution", "runs before stage handler", "pre_execution", preSteps, "pre_stage")}
    ${renderSection("Internal Graph", "emitted as module trace", "internal_graph", internalSteps, "internal_step")}
  `;
  configStepsOutput.querySelectorAll("[data-mm-module-step-up]").forEach((el) => {
    el.addEventListener("click", () => moveModuleStep(Number(el.getAttribute("data-mm-module-step-up")), -1, el.getAttribute("data-mm-module-step-phase") || "internal_graph"));
  });
  configStepsOutput.querySelectorAll("[data-mm-module-step-down]").forEach((el) => {
    el.addEventListener("click", () => moveModuleStep(Number(el.getAttribute("data-mm-module-step-down")), 1, el.getAttribute("data-mm-module-step-phase") || "internal_graph"));
  });
  configStepsOutput.querySelectorAll("[data-mm-module-step-duplicate]").forEach((el) => {
    el.addEventListener("click", () => duplicateModuleStep(Number(el.getAttribute("data-mm-module-step-duplicate")), el.getAttribute("data-mm-module-step-phase") || "internal_graph"));
  });
  configStepsOutput.querySelectorAll("[data-mm-module-step-delete]").forEach((el) => {
    el.addEventListener("click", () => deleteModuleStep(Number(el.getAttribute("data-mm-module-step-delete")), el.getAttribute("data-mm-module-step-phase") || "internal_graph"));
  });
  configStepsOutput.querySelectorAll("[data-mm-module-step-handler]").forEach((el) => {
    el.addEventListener("change", () => updateModuleStepField(Number(el.getAttribute("data-mm-module-step-handler")), "handler", el.value, el.getAttribute("data-mm-module-step-phase") || "internal_graph", { rerender: true }));
  });
  configStepsOutput.querySelectorAll("[data-mm-module-step-field]").forEach((el) => {
    const eventName = el.getAttribute("type") === "checkbox" ? "change" : "input";
    el.addEventListener(eventName, () => updateModuleStepField(
      Number(el.getAttribute("data-mm-module-step-index")),
      el.getAttribute("data-mm-module-step-field") || "",
      el.getAttribute("type") === "checkbox" ? Boolean(el.checked) : el.value,
      el.getAttribute("data-mm-module-step-phase") || "internal_graph",
    ));
  });
  configStepsOutput.querySelectorAll("[data-mm-module-step-add]").forEach((el) => {
    el.addEventListener("click", () => addModuleStep(el.getAttribute("data-mm-module-step-add") || "internal_graph", { mode: el.getAttribute("data-mm-module-step-add-mode") || "executable" }));
  });
  configStepsOutput.querySelectorAll("[data-mm-module-step-drag]").forEach((el) => {
    el.addEventListener("dragstart", (event) => beginModuleStepDrag(event, Number(el.getAttribute("data-mm-module-step-drag")), el.getAttribute("data-mm-module-step-phase") || "internal_graph"));
    el.addEventListener("dragend", endModuleStepDrag);
  });
  configStepsOutput.querySelectorAll("[data-mm-module-step-drop-index], [data-mm-module-step-section-drop]").forEach((el) => {
    el.addEventListener("dragover", handleModuleStepDragOver);
    el.addEventListener("dragleave", handleModuleStepDragLeave);
    el.addEventListener("drop", handleModuleStepDrop);
  });
}

function clearModuleStepDropHints() {
  configStepsOutput?.querySelectorAll?.(".drag-over, .dragging")?.forEach((el) => el.classList.remove("drag-over", "dragging"));
}

function beginModuleStepDrag(event, index, phase = "internal_graph") {
  moduleStepDragState = { index, phase };
  const card = event.target?.closest?.("[data-mm-module-step-index]");
  card?.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", `${phase}:${index}`);
  setConfigStatus(`dragging ${phase} step ${index + 1}`, "ok");
}

function endModuleStepDrag() {
  moduleStepDragState = null;
  clearModuleStepDropHints();
}

function handleModuleStepDragOver(event) {
  if (!moduleStepDragState) return;
  const phase = event.currentTarget.getAttribute("data-mm-module-step-phase") || event.currentTarget.getAttribute("data-mm-module-step-section-drop") || "internal_graph";
  if (phase !== moduleStepDragState.phase) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
  clearModuleStepDropHints();
  event.currentTarget.classList.add("drag-over");
}

function handleModuleStepDragLeave(event) {
  event.currentTarget.classList.remove("drag-over");
}

function handleModuleStepDrop(event) {
  if (!moduleStepDragState) return;
  const phase = event.currentTarget.getAttribute("data-mm-module-step-phase") || event.currentTarget.getAttribute("data-mm-module-step-section-drop") || "internal_graph";
  if (phase !== moduleStepDragState.phase) return;
  event.preventDefault();
  const payload = normalizedModulePayload(parseConfigEditor());
  const steps = moduleStepsForPhase(payload.module, phase);
  const fromIndex = moduleStepDragState.index;
  const rawDropIndex = event.currentTarget.getAttribute("data-mm-module-step-drop-index");
  let toIndex = rawDropIndex === null ? steps.length - 1 : Number(rawDropIndex);
  if (!Number.isFinite(toIndex)) toIndex = steps.length - 1;
  if (fromIndex < 0 || fromIndex >= steps.length || toIndex < 0 || toIndex >= steps.length) {
    endModuleStepDrag();
    return;
  }
  if (fromIndex !== toIndex) {
    const [item] = steps.splice(fromIndex, 1);
    steps.splice(toIndex, 0, item);
    setConfigPayload(payload);
    invalidateDryRunEvidence(`drag reordered ${phase} step ${fromIndex + 1} -> ${toIndex + 1}`);
    setConfigStatus(`reordered ${phase} step ${fromIndex + 1} -> ${toIndex + 1}`, "ok");
  }
  endModuleStepDrag();
}


function renderConfigWorkspace(modulePayload = activeModulePayload) {
  if (!modulePayload || !configSummaryOutput) return;
  const payload = normalizedModulePayload(modulePayload);
  const module = payload.module || {};
  if (configModuleSelect && configModuleSelect.value !== selectedModuleId) configModuleSelect.value = selectedModuleId;
  renderConfigTabs();
  renderConfigSummary(payload);
  renderConfigSteps(payload);
  renderDryRunEvidence();
  setConfigStatus(`draft ready · pre ${(module.pre_execution || []).length} · internal ${(module.internal_graph || []).length}`, "ok");
}

function applyConfigFormToPayload() {
  const payload = normalizedModulePayload(parseConfigEditor());
  const module = payload.module;
  module.handler = document.getElementById("mm-config-handler-select")?.value || module.handler || "";
  module.llm_role = readInputValue("mm-config-llm-role");
  const backend = readInputValue("mm-config-llm-backend");
  const model = readInputValue("mm-config-llm-model");
  module.llm = {};
  if (backend) module.llm.backend = backend;
  if (model) module.llm.model = model;
  if (!Object.keys(module.llm).length) delete module.llm;
  const timeout = readNumberInput("mm-config-timeout");
  if (timeout === null) delete module.timeout_s;
  else module.timeout_s = timeout;
  const maxAttempts = readNumberInput("mm-config-retry");
  if (maxAttempts === null) delete module.retry;
  else module.retry = { ...(module.retry || {}), max_attempts: Math.trunc(maxAttempts) };
  const checkedTools = Array.from(document.querySelectorAll("[data-mm-config-tool-checkbox]:checked")).map((input) => input.value).filter(Boolean);
  const manualTools = parseLineList(document.getElementById("mm-config-tools")?.value || "");
  module.tools = Array.from(new Set([...checkedTools, ...manualTools]));
  const promptPath = readInputValue("mm-config-prompt-path");
  const systemPrompt = document.getElementById("mm-config-prompt-system")?.value || "";
  const developerPrompt = document.getElementById("mm-config-prompt-developer")?.value || "";
  module.prompt = {};
  if (promptPath) module.prompt.path = promptPath;
  if (systemPrompt.trim()) module.prompt.system = systemPrompt.trim();
  if (developerPrompt.trim()) module.prompt.developer = developerPrompt.trim();
  if (!Object.keys(module.prompt).length) delete module.prompt;
  const supervisorPolicy = {};
  const requiredOutputs = parseLineList(document.getElementById("mm-config-supervisor-required-outputs")?.value || "");
  const responseStatuses = parseLineList(document.getElementById("mm-config-supervisor-response-statuses")?.value || "");
  const opinionTemplate = readInputValue("mm-config-supervisor-opinion-template");
  const recommendationTemplate = readInputValue("mm-config-supervisor-recommendation-template");
  const concernRules = readJsonArrayInput("mm-config-supervisor-concern-rules", "Supervisor concern rules");
  const options = readJsonArrayInput("mm-config-supervisor-options", "Supervisor options");
  if (requiredOutputs.length) supervisorPolicy.required_outputs = requiredOutputs;
  if (opinionTemplate) supervisorPolicy.opinion_template = opinionTemplate;
  if (recommendationTemplate) supervisorPolicy.recommendation_template = recommendationTemplate;
  if (concernRules.length) supervisorPolicy.concern_rules = concernRules;
  if (options.length) supervisorPolicy.options = options;
  if (responseStatuses.length) supervisorPolicy.requires_response_on_status = responseStatuses;
  if (Object.keys(supervisorPolicy).length) module.supervisor_policy = supervisorPolicy;
  else delete module.supervisor_policy;
  module.safety = {
    ...(module.safety || {}),
    live_requires_validation: readCheckbox("mm-config-live-validation"),
    dry_run_supported: readCheckbox("mm-config-dry-run-supported"),
    requires_human_approval: readCheckbox("mm-config-human-approval"),
  };
  hasUnappliedFormEdits = false;
  setConfigPayload(payload, { reason: "form draft applied" });
  setConfigStatus(`draft updated · validate before saving`, "ok");
  return payload;
}

function updateModuleHandler(handler) {
  const payload = normalizedModulePayload(parseConfigEditor());
  payload.module.handler = handler;
  for (const step of moduleStepsForPhase(payload.module, "pre_execution")) {
    if (!step.handler) step.handler = handler;
  }
  for (const step of moduleStepsForPhase(payload.module, "internal_graph")) {
    const kind = String(step.kind || "").toLowerCase();
    if (!step.handler && kind && kind !== "checkpoint") step.handler = handler;
  }
  setConfigPayload(payload);
  invalidateDryRunEvidence("handler changed");
  setConfigStatus(`handler updated to ${handler}; checkpoint steps preserved`, "ok");
}

function updateModuleStepField(index, field, value, phase = "internal_graph", options = {}) {
  const payload = normalizedModulePayload(parseConfigEditor());
  const steps = moduleStepsForPhase(payload.module, phase);
  if (!field || index < 0 || index >= steps.length) return;
  if (field === "enabled") steps[index][field] = Boolean(value);
  else if (field === "id") steps[index][field] = String(value || "").trim();
  else if (String(value || "").trim()) steps[index][field] = String(value).trim();
  else delete steps[index][field];
  setConfigPayload(payload, { render: options.rerender !== false });
  invalidateDryRunEvidence(`${phase} step ${index + 1} ${field} updated`);
  setConfigStatus(`${phase} step ${index + 1} ${field} updated`, "ok");
}

function moveModuleStep(index, delta, phase = "internal_graph") {
  reorderModuleStep(index, index + delta, phase);
}

function reorderModuleStep(fromIndex, toIndex, phase = "internal_graph") {
  const payload = normalizedModulePayload(parseConfigEditor());
  const steps = moduleStepsForPhase(payload.module, phase);
  if (fromIndex < 0 || fromIndex >= steps.length || toIndex < 0 || toIndex >= steps.length || fromIndex === toIndex) return;
  const [item] = steps.splice(fromIndex, 1);
  steps.splice(toIndex, 0, item);
  setConfigPayload(payload);
  invalidateDryRunEvidence(`reordered ${phase} step ${fromIndex + 1} -> ${toIndex + 1}`);
  setConfigStatus(`reordered ${phase} step ${fromIndex + 1} -> ${toIndex + 1}`, "ok");
}

function deleteModuleStep(index, phase = "internal_graph") {
  const payload = normalizedModulePayload(parseConfigEditor());
  const steps = moduleStepsForPhase(payload.module, phase);
  if (index < 0 || index >= steps.length) return;
  const [removed] = steps.splice(index, 1);
  setConfigPayload(payload);
  invalidateDryRunEvidence(`deleted ${phase} step ${removed?.id || index + 1}`);
  setConfigStatus(`deleted ${phase} step ${removed?.id || index + 1}`, "warn");
}

function uniqueStepId(baseId, steps = []) {
  const clean = String(baseId || "step").trim().replace(/[^a-zA-Z0-9_\-]+/g, "_") || "step";
  const existing = new Set(steps.map((step) => String(step?.id || "").trim()).filter(Boolean));
  if (!existing.has(clean)) return clean;
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${clean}_${index}`;
    if (!existing.has(candidate)) return candidate;
  }
  return `${clean}_${Date.now()}`;
}

function duplicateModuleStep(index, phase = "internal_graph") {
  const payload = normalizedModulePayload(parseConfigEditor());
  const steps = moduleStepsForPhase(payload.module, phase);
  if (index < 0 || index >= steps.length) return;
  const original = cloneConfig(steps[index]) || {};
  const cloned = {
    ...original,
    id: uniqueStepId(`${original.id || phase}_copy`, steps),
    label: `${original.label || original.id || "Step"} Copy`,
  };
  steps.splice(index + 1, 0, cloned);
  setConfigPayload(payload);
  invalidateDryRunEvidence(`duplicated ${phase} step ${original.id || index + 1}`);
  setConfigStatus(`duplicated ${phase} step ${original.id || index + 1}`, "ok");
}

function addModuleStep(phase = "internal_graph", options = {}) {
  const payload = normalizedModulePayload(parseConfigEditor());
  const steps = moduleStepsForPhase(payload.module, phase);
  const nextIndex = steps.length + 1;
  const mode = options.mode || "executable";
  const defaultHandler = mode === "checkpoint" && phase === "internal_graph" ? "" : (payload.module.handler || handlers[0] || "");
  const isPre = phase === "pre_execution";
  const baseId = `${isPre ? "pre_step" : mode === "checkpoint" ? "checkpoint" : "step"}_${String(nextIndex).padStart(2, "0")}`;
  steps.push({
    id: uniqueStepId(baseId, steps),
    label: `${isPre ? "Pre Step" : mode === "checkpoint" ? "Checkpoint" : "Agent Step"} ${nextIndex}`,
    kind: isPre ? "pre_stage" : mode === "checkpoint" ? "checkpoint" : "internal_step",
    ...(defaultHandler ? { handler: defaultHandler } : {}),
    ...(isPre ? { output_key: `pre_step_${String(nextIndex).padStart(2, "0")}`, event_type: "module_pre_step_completed", enabled: true } : { enabled: true }),
  });
  setConfigPayload(payload);
  invalidateDryRunEvidence(`added ${phase} ${mode} step ${nextIndex}`);
  setConfigStatus(`added ${phase} ${mode} step ${nextIndex}`, "ok");
}

async function selectModule(moduleId) {
  selectedModuleId = moduleId;
  resetModuleEvidence("module selected");
  activeModuleBadge.textContent = moduleId || "none";
  const module = selectedModule();
  if (!module) {
    workbench.innerHTML = `<div>Select or load a module.</div>`;
    renderModuleList();
    renderConfigTabs();
    return;
  }
  renderModuleList();
  await inspectModule(moduleId);
}

async function inspectModule(moduleId) {
  const result = await requestJson(`/api/modules/${moduleId}`);
  activeModuleBadge.textContent = moduleId || "none";
  activeModulePayload = normalizedModulePayload(result.module);
  activeModuleLifecycle = result.lifecycle || null;
  activeModuleRuntimeEffect = result.runtime_effect || null;
  renderModulePayload(activeModulePayload, Boolean(result.loaded));
  setConfigPayload(activeModulePayload, { baseline: true, reason: "active module loaded" });
}

function populateConfigModuleSelect() {
  if (!configModuleSelect) return;
  configModuleSelect.innerHTML = modules
    .map((module) => `<option value="${escapeHtml(module.id)}">${escapeHtml(module.label || module.id)} · ${escapeHtml(module.category || "runtime")}</option>`)
    .join("");
  if (selectedModuleId && Array.from(configModuleSelect.options).some((option) => option.value === selectedModuleId)) {
    configModuleSelect.value = selectedModuleId;
  }
}

async function refreshAll() {
  setStatus("idle", "Refreshing", "Reading module registry.");
  const [handlerResult, stateResult, toolResult] = await Promise.all([
    requestJson("/api/handlers"),
    requestJson("/api/modules/management-state"),
    requestJson("/api/tools").catch(() => ({ tools: [] })),
    refreshGraphUsageIndex(),
  ]);
  handlers = Array.isArray(handlerResult.handlers) ? handlerResult.handlers : [];
  modules = Array.isArray(stateResult.modules) ? stateResult.modules : [];
  availableTools = Array.isArray(toolResult.tools) ? toolResult.tools : [];
  loadedIds = new Set(Array.isArray(stateResult.loaded_module_ids) ? stateResult.loaded_module_ids : []);
  designerHandlerSelect.innerHTML = handlerOptions("runtime.step_complete");
  populateConfigModuleSelect();
  if (!selectedModuleId && modules.length) selectedModuleId = modules[0].id;
  renderModuleList();
  renderConfigTabs();
  if (selectedModuleId) await inspectModule(selectedModuleId);
  setStatus("ok", "Ready", `${modules.length} modules · ${loadedIds.size} loaded`);
}

async function loadSelected() {
  if (!selectedModuleId) return;
  const result = await requestJson(`/api/modules/${selectedModuleId}/load`, { method: "POST", body: "{}" });
  loadedIds = new Set(result.loaded_module_ids || []);
  activeModulePayload = normalizedModulePayload(result.module);
  activeModuleLifecycle = result.lifecycle || null;
  activeModuleRuntimeEffect = result.runtime_effect || null;
  renderModuleList();
  renderModulePayload(activeModulePayload, true);
  setConfigPayload(activeModulePayload, { baseline: true, reason: "module loaded" });
  actionOutput.innerHTML = `<div><strong>Loaded</strong> ${escapeHtml(selectedModuleId)} into management workspace.</div>`;
  setStatus("ok", "Module Loaded", selectedModuleId);
}

async function unloadSelected() {
  if (!selectedModuleId) return;
  const result = await requestJson(`/api/modules/${selectedModuleId}/unload`, { method: "POST", body: "{}" });
  loadedIds = new Set(result.loaded_module_ids || []);
  activeModuleLifecycle = result.lifecycle || null;
  activeModuleRuntimeEffect = result.runtime_effect || null;
  renderModuleList();
  if (activeModulePayload) renderModulePayload(activeModulePayload, false);
  actionOutput.innerHTML = `<div><strong>Unloaded</strong> ${escapeHtml(selectedModuleId)} from management workspace.</div>`;
  setStatus("idle", "Module Unloaded", selectedModuleId);
}

function requireAppliedModuleDraft() {
  if (hasUnappliedFormEdits) {
    throw new Error("Apply Draft before validate, dry-run, or save. Form edits are not reflected in raw module JSON yet.");
  }
  return normalizedModulePayload(parseConfigEditor());
}

function renderModulePreflightBlocked(status) {
  return `
    <div><strong>Save blocked</strong></div>
    <ul>${status.issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>
    ${modulePreflightMarkup(activeModulePayload)}
  `;
}

function showModuleActionError(label, err) {
  const message = String(err?.message || err);
  if (actionOutput) actionOutput.innerHTML = `<div><strong>${escapeHtml(label)}</strong></div><pre>${escapeHtml(message)}</pre>`;
  setConfigStatus(message, "warn");
  setStatus("warn", label, message);
  refreshModulePreflightCard(activeModulePayload);
}

async function validateSelected() {
  if (!selectedModuleId) return;
  const modulePayload = requireAppliedModuleDraft();
  const result = await requestJson(`/api/modules/${selectedModuleId}/validate`, { method: "POST", body: JSON.stringify({ module: modulePayload }) });
  moduleEvidence.validation = { ok: Boolean(result.ok), fingerprint: moduleConfigFingerprint(modulePayload), errors: result.errors || [] };
  actionOutput.innerHTML = `<div><strong>Validate ${escapeHtml(result.ok ? "OK" : "Failed")}</strong></div><pre>${escapeHtml(JSON.stringify(result.errors || [], null, 2))}</pre>`;
  refreshModulePreflightCard(modulePayload);
  setConfigStatus(`validate ${result.ok ? "OK" : "failed"}`, result.ok ? "ok" : "warn");
  setStatus(result.ok ? "ok" : "warn", result.ok ? "Valid" : "Invalid", selectedModuleId);
}

async function dryRunSelected() {
  if (!selectedModuleId) return;
  const modulePayload = requireAppliedModuleDraft();
  const result = await requestJson(`/api/modules/${selectedModuleId}/dry-run`, { method: "POST", body: JSON.stringify({ module: modulePayload }) });
  lastDryRunResult = result;
  moduleEvidence.dry_run = { ok: Boolean(result.ok), fingerprint: moduleConfigFingerprint(modulePayload), errors: result.errors || [], summary: result.summary || {} };
  renderDryRunEvidence(result);
  refreshModulePreflightCard(modulePayload);
  const summary = result.summary || {};
  actionOutput.innerHTML = `
    <div><strong>Dry Run ${escapeHtml(result.ok ? "OK" : "Failed")}</strong></div>
    <div class="module-management-action-summary">
      <span>steps=${escapeHtml(summary.step_count ?? (result.sequence || []).length)}</span>
      <span>pre=${escapeHtml(summary.pre_execution_count ?? 0)}</span>
      <span>internal=${escapeHtml(summary.internal_graph_count ?? 0)}</span>
      <span>executable=${escapeHtml(summary.executable_count ?? 0)}</span>
    </div>
  `;
  setConfigStatus(`dry-run ${result.ok ? "OK" : "failed"} · ${(result.sequence || []).length} step(s)`, result.ok ? "ok" : "warn");
  setStatus(result.ok ? "ok" : "warn", result.ok ? "Dry Run OK" : "Dry Run Failed", `${(result.sequence || []).length} steps`);
}

async function loadModuleVersions() {
  if (!selectedModuleId || !versionOutput) return;
  versionOutput.innerHTML = "<div>Loading module versions...</div>";
  const result = await requestJson(`/api/modules/${selectedModuleId}/versions`);
  const versions = Array.isArray(result.versions) ? result.versions : [];
  if (!versions.length) {
    versionOutput.innerHTML = `<div>No saved module versions for ${escapeHtml(selectedModuleId)} yet.</div>`;
    return;
  }
  versionOutput.innerHTML = versions
    .map((version) => `
      <div class="runtime-version-item">
        <div>
          <strong>${escapeHtml(versionLabel(version))}</strong>
          <small>${escapeHtml(formatVersionTimestamp(version.created_at))}</small>
          <span>${escapeHtml(version.reason || "no reason")}</span>
        </div>
        <button type="button" class="btn tiny" data-mm-version-load="${escapeHtml(version.version_id)}">Load Draft</button>
      </div>
    `)
    .join("");
  versionOutput.querySelectorAll("[data-mm-version-load]").forEach((el) => {
    el.addEventListener("click", () => loadModuleVersionDraft(el.getAttribute("data-mm-version-load") || "").catch((err) => setStatus("warn", "Version Load Failed", String(err))));
  });
}

async function loadModuleVersionDraft(versionId) {
  if (!selectedModuleId || !versionId) return;
  const result = await requestJson(`/api/modules/${selectedModuleId}/versions/${encodeURIComponent(versionId)}`);
  const draft = result.version?.module;
  if (!draft || typeof draft !== "object") throw new Error(`Module version payload is missing: ${versionId}`);
  activeModulePayload = normalizedModulePayload(draft);
  setConfigPayload(activeModulePayload, { reason: `version draft ${versionId}` });
  renderModulePayload(activeModulePayload, loadedIds.has(selectedModuleId));
  actionOutput.innerHTML = `<div><strong>Loaded draft</strong> ${escapeHtml(selectedModuleId)} · ${escapeHtml(versionId)}. Validate, dry-run, then Save Config to activate.</div>`;
  setConfigStatus(`version draft loaded ${versionId}`, "warn");
  setStatus("ok", "Version Draft Loaded", selectedModuleId);
}

async function registerGeneratedSelected() {
  if (!selectedModuleId) return;
  const result = await requestJson(`/api/modules/${selectedModuleId}/register-generated`, { method: "POST", body: "{}" });
  if (!result.ok) {
    actionOutput.innerHTML = `<div><strong>Generated adapter registration failed</strong></div><pre>${escapeHtml(JSON.stringify(result.errors || [], null, 2))}</pre>`;
    setConfigStatus("generated adapter registration failed", "warn");
    setStatus("warn", "Registration Failed", selectedModuleId);
    return;
  }
  actionOutput.innerHTML = `
    <div><strong>Generated adapter registered</strong> ${escapeHtml(selectedModuleId)}</div>
    <div class="module-management-action-summary">
      <span>handler=${escapeHtml(result.handler || "module.generated_adapter")}</span>
      <span>version=${escapeHtml(result.version?.version_id || "versioned")}</span>
    </div>
  `;
  setConfigStatus("generated adapter registered · validate/dry-run before graph live run", "ok");
  setStatus("ok", "Generated Adapter Registered", selectedModuleId);
  await refreshAll();
  await inspectModule(selectedModuleId);
}

async function saveConfigSelected() {
  if (!selectedModuleId) return;
  const modulePayload = requireAppliedModuleDraft();
  const preflight = modulePreflightStatus(modulePayload);
  if (!preflight.ready) {
    actionOutput.innerHTML = renderModulePreflightBlocked(preflight);
    setConfigStatus("save blocked · validate and dry-run current draft first", "warn");
    setStatus("warn", "Save Blocked", selectedModuleId);
    refreshModulePreflightCard(modulePayload);
    return;
  }
  const module = modulePayload.module || {};
  const moduleId = module.id || selectedModuleId;
  const result = await requestJson(`/api/modules/${moduleId}`, {
    method: "PUT",
    body: JSON.stringify({ module: modulePayload, reason: "module_management_tool_save", author: "module_management_tool", activate: true }),
  });
  if (!result.ok) {
    actionOutput.innerHTML = `<div><strong>Save failed</strong></div><pre>${escapeHtml(JSON.stringify(result.errors || [], null, 2))}</pre>`;
    setConfigStatus("save failed", "warn");
    setStatus("warn", "Save Failed", moduleId);
    return;
  }
  actionOutput.innerHTML = `<div><strong>Saved</strong> ${escapeHtml(moduleId)} · ${escapeHtml(result.version?.version_id || "versioned")}</div>`;
  setConfigStatus(`saved ${result.version?.version_id || "active version"}`, "ok");
  await refreshAll();
  selectedModuleId = moduleId;
  await inspectModule(moduleId);
  if (versionOutput?.innerHTML) loadModuleVersions().catch(() => undefined);
}

function fillDesignerFromFile(file) {
  if (!file) return;
  const base = file.name.replace(/\.py$/i, "").replace(/[^A-Za-z0-9_\-]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
  if (!designerModuleIdInput.value) designerModuleIdInput.value = base || "custom_module";
  if (!designerLabelInput.value) designerLabelInput.value = file.name.replace(/\.py$/i, "").replace(/[_\-]+/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

async function createModule() {
  const file = designerPythonFileInput.files?.[0];
  if (!file) throw new Error("Select a Python source file first.");
  const moduleId = designerModuleIdInput.value.trim();
  const label = designerLabelInput.value.trim();
  if (!moduleId || !label) throw new Error("Module ID and Label are required.");
  designerStatus.textContent = "Creating module with Gemma 31B transform...";
  const sourceText = await file.text();
  const result = await requestJson("/api/modules", {
    method: "POST",
    body: JSON.stringify({
      module_id: moduleId,
      label,
      category: designerCategoryInput.value.trim(),
      handler: designerHandlerSelect.value || "runtime.step_complete",
      llm_role: designerLlmRoleInput.value.trim(),
      source_filename: file.name,
      source_text: sourceText,
      notes: designerNotesInput.value.trim(),
      transform_with_llm: true,
      transform_model: "gemma4:31b",
    }),
  });
  if (!result.ok) {
    designerStatus.innerHTML = `<strong>Create failed</strong><pre>${escapeHtml(JSON.stringify(result.errors || result, null, 2))}</pre>`;
    setStatus("warn", "Create Failed", moduleId);
    return;
  }
  designerStatus.innerHTML = `<strong>Created</strong> ${escapeHtml(result.module_id)}<br /><small>${escapeHtml(result.transform?.transformed_source_path || "handler.py")}</small>`;
  selectedModuleId = result.module_id;
  await refreshAll();
  await loadSelected();
}

async function createDraftModuleTemplate() {
  const moduleId = designerModuleIdInput.value.trim();
  const label = designerLabelInput.value.trim();
  if (!moduleId || !label) throw new Error("Module ID and Label are required for a draft agent.");
  createDraftBtn.disabled = true;
  designerStatus.textContent = "Creating inactive draft agent template...";
  try {
    const result = await requestJson("/api/modules/templates/agent", {
      method: "POST",
      body: JSON.stringify({
        module_id: moduleId,
        label,
        category: designerCategoryInput.value.trim() || "custom",
        notes: designerNotesInput.value.trim(),
        author: "module_management_gui",
      }),
    });
    if (!result.ok) {
      designerStatus.innerHTML = `<strong>Draft create failed</strong><pre>${escapeHtml(JSON.stringify(result.errors || result, null, 2))}</pre>`;
      setStatus("warn", "Draft Create Failed", moduleId);
      return;
    }
    designerStatus.innerHTML = `<strong>Draft Created</strong> ${escapeHtml(result.module_id)}<br /><small>inactive preview · graph unattached · ${escapeHtml(result.ui_path || "ui.yaml")}</small>`;
    selectedModuleId = result.module_id;
    await refreshAll();
    await loadSelected();
  } finally {
    createDraftBtn.disabled = false;
  }
}

refreshBtn.addEventListener("click", () => refreshAll().catch((err) => setStatus("warn", "Refresh Failed", String(err))));
openIdeBtn.addEventListener("click", openRuntimeIdeForSelectedModule);
saveConfigQuickBtn.addEventListener("click", () => saveConfigSelected().catch((err) => showModuleActionError("Save Failed", err)));
saveConfigBtn.addEventListener("click", () => saveConfigSelected().catch((err) => showModuleActionError("Save Failed", err)));
loadBtn.addEventListener("click", () => loadSelected().catch((err) => setStatus("warn", "Load Failed", String(err))));
unloadBtn.addEventListener("click", () => unloadSelected().catch((err) => setStatus("warn", "Unload Failed", String(err))));
validateBtn.addEventListener("click", () => validateSelected().catch((err) => showModuleActionError("Validate Failed", err)));
registerGeneratedBtn?.addEventListener("click", () => registerGeneratedSelected().catch((err) => showModuleActionError("Register Generated Failed", err)));
dryRunBtn.addEventListener("click", () => dryRunSelected().catch((err) => showModuleActionError("Dry Run Failed", err)));
versionsBtn?.addEventListener("click", () => loadModuleVersions().catch((err) => setStatus("warn", "Versions Failed", String(err))));
applyConfigBtn.addEventListener("click", () => {
  try {
    applyConfigFormToPayload();
  } catch (err) {
    setConfigStatus(String(err), "warn");
  }
});
validateConfigBtn.addEventListener("click", () => validateSelected().catch((err) => showModuleActionError("Validate Failed", err)));
dryRunConfigBtn.addEventListener("click", () => dryRunSelected().catch((err) => showModuleActionError("Dry Run Failed", err)));
configModuleSelect.addEventListener("change", () => selectModule(configModuleSelect.value).catch((err) => setStatus("warn", "Module Load Failed", String(err))));
configJsonInput.addEventListener("change", () => {
  try {
    setConfigPayload(parseConfigEditor());
    setConfigStatus("raw JSON applied to config workspace", "ok");
  } catch (err) {
    setConfigStatus(String(err), "warn");
  }
});
createBtn.addEventListener("click", () => createModule().catch((err) => {
  designerStatus.textContent = String(err);
  setStatus("warn", "Create Failed", String(err));
}));
createDraftBtn.addEventListener("click", () => createDraftModuleTemplate().catch((err) => {
  designerStatus.textContent = String(err);
  setStatus("warn", "Draft Create Failed", String(err));
}));
designerPythonFileInput.addEventListener("change", () => fillDesignerFromFile(designerPythonFileInput.files?.[0]));
searchInput.addEventListener("input", () => { searchQuery = searchInput.value || ""; renderModuleList(); });
document.querySelectorAll("[data-mm-config-jump]").forEach((button) => {
  button.addEventListener("click", () => jumpToConfigSection(button.getAttribute("data-mm-config-jump") || ""));
});

refreshAll().catch((err) => setStatus("warn", "Tool Error", String(err)));
