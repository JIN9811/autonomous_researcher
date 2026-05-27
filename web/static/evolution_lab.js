/* Self-Evolution Lab GUI. */
const $ = (id) => document.getElementById(id);
const statusDot = $("evolution-status-dot");
const statusLabel = $("evolution-status-label");
const statusDetail = $("evolution-status-detail");
const targetInput = $("evolution-target-input");
const runInput = $("evolution-run-input");
const objectiveInput = $("evolution-objective-input");
const summaryOutput = $("evolution-candidate-summary");
const pipelineOutput = $("evolution-pipeline-output");
const leaderboardOutput = $("evolution-leaderboard-output");
const historyOutput = $("evolution-history-output");
const lineageOutput = $("evolution-lineage-output");
const output = $("evolution-output");
const activeBadge = $("evolution-active-variant");
let currentTaskId = "";
let currentVariantId = "";
let currentVariant = null;
let latestTasks = [];
let latestTargets = [];
let latestTraces = [];
let latestVariants = [];
const queryParams = new URLSearchParams(window.location.search);
let queryPrefillApplied = false;

const PIPELINE_STEPS = [
  { id: "trace", label: "Trace Intake", detail: "Source run traces loaded" },
  { id: "mine", label: "Trace Mining", detail: "Failures, missing fields, and bottlenecks summarized" },
  { id: "candidate", label: "Candidate", detail: "Prompt/graph/report/policy variant generated" },
  { id: "gate", label: "Gate Check", detail: "Schema, compiler, dry-run, and safety gates" },
  { id: "approval", label: "Human Approval", detail: "Operator review before activation" },
  { id: "activation", label: "Next-Run Activation", detail: "Versioned activation or rollback marker" },
];

function setStatus(kind, label, detail = "") {
  if (statusDot) statusDot.className = `status-dot ${kind === "error" ? "warn" : kind === "busy" ? "busy" : "idle"}`;
  if (statusLabel) statusLabel.textContent = label;
  if (statusDetail) statusDetail.textContent = detail;
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`);
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function compact(value, limit = 96) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function write(data) {
  if (output) output.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

function selectedTargetParts() {
  const raw = String(targetInput?.value || "prompt:design");
  const [targetType, ...rest] = raw.split(":");
  return { targetType: targetType || "prompt", targetId: rest.join(":") || "design", value: raw };
}

function ensureSelectOption(selectEl, value, label) {
  if (!selectEl || !value) return;
  const exists = Array.from(selectEl.options).some((option) => option.value === value);
  if (exists) return;
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label || value;
  selectEl.prepend(option);
}

function gateSummary(variant) {
  const gates = Array.isArray(variant?.gate_results) ? variant.gate_results : [];
  const passed = gates.filter((gate) => Boolean(gate.passed)).length;
  return { total: gates.length, passed, failed: gates.length - passed };
}

function gateChecklistMarkup(variant) {
  const gates = Array.isArray(variant?.gate_results) ? variant.gate_results : [];
  if (!gates.length) return `<p class="hint">No gate results.</p>`;
  return `<div class="evolution-gate-list">${gates.map((gate) => `
    <article class="evolution-gate-item ${gate.passed ? "passed" : "failed"}">
      <span class="evolution-gate-badge">${gate.passed ? "PASS" : "FAIL"}</span>
      <div>
        <strong>${escapeHtml(gate.gate_id || "gate")}</strong>
        <small>${escapeHtml(gate.message || "No message")}</small>
      </div>
    </article>
  `).join("")}</div>`;
}

function pipelineState(variant) {
  const status = variant?.status || "";
  const gates = gateSummary(variant);
  const hasVariant = Boolean(variant?.variant_id);
  return {
    trace: latestTraces.length || currentTaskId ? "done" : "pending",
    mine: currentTaskId || hasVariant ? "done" : "pending",
    candidate: hasVariant ? "done" : currentTaskId ? "active" : "pending",
    gate: hasVariant ? (gates.failed ? "error" : gates.total ? "done" : "active") : "pending",
    approval: ["approved", "active_next_run"].includes(status) ? "done" : status === "gate_passed" ? "active" : status === "rolled_back" ? "warning" : "pending",
    activation: status === "active_next_run" ? "done" : status === "rolled_back" ? "warning" : status === "approved" ? "active" : "pending",
  };
}

function renderPipeline(variant = currentVariant) {
  if (!pipelineOutput) return;
  const states = pipelineState(variant);
  pipelineOutput.innerHTML = PIPELINE_STEPS.map((step, index) => `
    <article class="evolution-pipeline-step ${states[step.id] || "pending"}">
      <div class="evolution-pipeline-node">${index + 1}</div>
      <div>
        <strong>${escapeHtml(step.label)}</strong>
        <small>${escapeHtml(step.detail)}</small>
      </div>
    </article>
  `).join("");
}

function variantStatusRank(status) {
  return {
    active_next_run: 6,
    approved: 5,
    gate_passed: 4,
    generated: 3,
    failed_gate: 2,
    rolled_back: 1,
  }[status] || 0;
}

function sortedVariants(variants) {
  return [...(variants || [])].sort((a, b) => {
    const scoreA = Number(a.score);
    const scoreB = Number(b.score);
    const normalizedA = Number.isFinite(scoreA) ? scoreA : -1000000000;
    const normalizedB = Number.isFinite(scoreB) ? scoreB : -1000000000;
    const scoreDelta = normalizedB - normalizedA;
    if (scoreDelta !== 0) return scoreDelta;
    const statusDelta = variantStatusRank(b.status) - variantStatusRank(a.status);
    if (statusDelta !== 0) return statusDelta;
    return String(b.created_at || "").localeCompare(String(a.created_at || ""));
  });
}

function renderLeaderboard(variants = latestVariants) {
  if (!leaderboardOutput) return;
  const rows = sortedVariants(variants).slice(0, 10);
  if (!rows.length) {
    const { targetType, targetId } = selectedTargetParts();
    leaderboardOutput.innerHTML = `<p class="hint">No candidates for ${escapeHtml(targetType)}:${escapeHtml(targetId)} yet.</p>`;
    return;
  }
  leaderboardOutput.innerHTML = rows.map((variant, index) => {
    const gates = gateSummary(variant);
    const selected = variant.variant_id === currentVariantId;
    const active = variant.status === "active_next_run";
    const unreviewed = variant.status === "gate_passed";
    return `
      <article class="evolution-leaderboard-row ${selected ? "selected" : ""} ${active ? "active" : ""} ${unreviewed ? "unreviewed" : ""}">
        <div class="evolution-rank">#${index + 1}</div>
        <div class="evolution-leaderboard-copy">
          <strong>${escapeHtml(variant.variant_id || "variant")}</strong>
          <small>${escapeHtml(variant.status || "unknown")} · score=${escapeHtml(variant.score ?? "-")} · gates=${gates.passed}/${gates.total}</small>
          <p>${escapeHtml(compact(variant.diff || "No diff summary", 110))}</p>
        </div>
        <button class="btn tiny evolution-variant-action" data-variant-id="${escapeHtml(variant.variant_id)}">Open</button>
      </article>
    `;
  }).join("");
}

function applyQueryPrefill() {
  if (queryPrefillApplied) return;
  const targetType = queryParams.get("target_type") || "";
  const targetId = queryParams.get("target_id") || "";
  const targetValue = targetType && targetId ? `${targetType}:${targetId}` : queryParams.get("target") || "";
  const runId = queryParams.get("run_id") || "";
  const objective = queryParams.get("objective") || "";
  if (targetValue) {
    ensureSelectOption(targetInput, targetValue, `${targetType || "target"} · ${targetId || targetValue} · from Live GUI`);
    targetInput.value = targetValue;
  }
  if (runId) {
    ensureSelectOption(runInput, runId, `${runId} · from Live GUI`);
    runInput.value = runId;
  }
  if (objective && objectiveInput) objectiveInput.value = objective;
  if (targetValue || runId || objective) {
    setStatus("idle", "Ready", `Prefilled from ${queryParams.get("source") || "query"}: ${targetValue || "target"} ${runId || "latest traces"}`);
    write({
      ok: true,
      source: queryParams.get("source") || "query",
      agent_id: queryParams.get("agent_id") || "",
      target: targetValue,
      run_id: runId,
      event_key: queryParams.get("event_key") || "",
      note: "Review the prefilled task, then click Create + Run Task. No hardware is executed by self-evolution evaluation.",
    });
  }
  queryPrefillApplied = true;
}

function setVariant(variant) {
  if (!variant) return;
  currentVariant = variant;
  currentVariantId = variant.variant_id || "";
  if (activeBadge) {
    activeBadge.textContent = currentVariantId || "none";
    activeBadge.className = `badge ${variant.status === "active_next_run" ? "busy" : variant.status === "gate_passed" || variant.status === "approved" ? "ok" : variant.status === "rolled_back" ? "warning" : "idle"}`;
  }
  if (summaryOutput) {
    const gates = gateSummary(variant);
    summaryOutput.innerHTML = `
      <div class="evolution-candidate-head">
        <div>
          <strong>${escapeHtml(variant.status || "unknown")}</strong>
          <small>${escapeHtml(currentVariantId || "no variant id")}</small>
        </div>
        <span class="state-pill">score=${escapeHtml(variant.score ?? "-")}</span>
        <span class="state-pill ${gates.failed ? "warning" : "ok"}">gates=${gates.passed}/${gates.total}</span>
      </div>
      ${gateChecklistMarkup(variant)}
    `;
  }
  renderPipeline(variant);
  renderLeaderboard(latestVariants);
  write({ variant_id: variant.variant_id, status: variant.status, score: variant.score, diff: variant.diff, body: variant.body, gates: variant.gate_results, activation: variant.activation });
}

function renderTaskHistory(tasks) {
  if (!historyOutput) return;
  const { targetType, targetId } = selectedTargetParts();
  const filtered = (tasks || []).filter((task) => task.target_type === targetType && task.target_id === targetId).slice(0, 8);
  if (!filtered.length) {
    historyOutput.innerHTML = `<p class="hint">No tasks for ${escapeHtml(targetType)}:${escapeHtml(targetId)} yet.</p>`;
    return;
  }
  historyOutput.innerHTML = filtered.map((task) => `
    <article class="evolution-history-card ${task.task_id === currentTaskId ? "selected" : ""}">
      <small>${escapeHtml(task.status || "draft")} · ${escapeHtml(task.created_at || "")}</small>
      <strong>${escapeHtml(task.task_id || "task")}</strong>
      <p>${escapeHtml(compact(task.objective || "No objective", 120))}</p>
      <small>runs=${escapeHtml((task.source_run_ids || []).join(", ") || "latest")} · variants=${escapeHtml((task.variant_ids || []).length)}</small>
      <div class="button-row">
        <button class="btn tiny evolution-task-action" data-task-id="${escapeHtml(task.task_id)}" data-task-action="variants">Load Variants</button>
      </div>
    </article>
  `).join("");
}

function renderLineage(lineage) {
  if (!lineageOutput) return;
  const active = lineage?.active || {};
  const variants = Array.isArray(lineage?.variants) ? lineage.variants : [];
  const activeRows = Object.entries(active).map(([key, value]) => `<p><strong>${escapeHtml(key)}</strong><br /><small>${escapeHtml(value?.variant_id || "")}</small></p>`).join("");
  const variantRows = variants.slice(0, 8).map((variant) => `
    <article class="evolution-history-card ${variant.variant_id === currentVariantId ? "selected" : ""} ${variant.status === "active_next_run" ? "active" : ""}">
      <small>${escapeHtml(variant.status || "unknown")} · score=${escapeHtml(variant.score ?? "-")}</small>
      <strong>${escapeHtml(variant.variant_id || "variant")}</strong>
      <p>${escapeHtml(compact(variant.diff || "No diff summary", 120))}</p>
      <div class="button-row">
        <button class="btn tiny evolution-variant-action" data-variant-id="${escapeHtml(variant.variant_id)}">Open Variant</button>
      </div>
    </article>
  `).join("");
  lineageOutput.innerHTML = `
    <div class="evolution-lineage-active"><h4>Active</h4>${activeRows || "<p class='hint'>No active variant for this target.</p>"}</div>
    <div class="evolution-lineage-variants"><h4>Recent Variants</h4>${variantRows || "<p class='hint'>No variants for this target yet.</p>"}</div>
  `;
}

async function refreshVariantsForTarget() {
  const { targetType, targetId } = selectedTargetParts();
  const result = await requestJson(`/api/evolution/variants?target_type=${encodeURIComponent(targetType)}&target_id=${encodeURIComponent(targetId)}`);
  latestVariants = result.variants || [];
  renderLeaderboard(latestVariants);
  return latestVariants;
}

async function refreshLineage() {
  const { targetId } = selectedTargetParts();
  const lineage = await requestJson(`/api/evolution/lineage/${encodeURIComponent(targetId)}`);
  renderLineage(lineage);
  return lineage;
}

async function refreshHistoryAndLineage() {
  renderTaskHistory(latestTasks);
  await refreshVariantsForTarget();
  await refreshLineage();
  renderPipeline(currentVariant);
}

async function refresh() {
  setStatus("busy", "Loading", "Reading evolution targets, traces, and history.");
  const [targets, traces, tasks] = await Promise.all([
    requestJson("/api/evolution/targets"),
    requestJson("/api/evolution/traces?limit=20"),
    requestJson("/api/evolution/tasks"),
  ]);
  latestTargets = targets.targets || [];
  latestTraces = traces.traces || [];
  latestTasks = tasks.tasks || [];
  if (targetInput) {
    targetInput.innerHTML = latestTargets.map((target) => {
      const value = `${target.target_type}:${target.target_id}`;
      return `<option value="${escapeHtml(value)}">${escapeHtml(target.target_type)} · ${escapeHtml(target.target_id)}</option>`;
    }).join("");
  }
  if (runInput) {
    runInput.innerHTML = `<option value="">latest traces</option>` + latestTraces.map((trace) => {
      const metric = trace.metrics || {};
      return `<option value="${escapeHtml(trace.run_id)}">${escapeHtml(trace.run_id)} · events=${escapeHtml(metric.event_count || 0)} errors=${escapeHtml(metric.error_count || 0)}</option>`;
    }).join("");
  }
  applyQueryPrefill();
  await refreshHistoryAndLineage();
  setStatus("idle", "Ready", `${latestTargets.length} targets · ${latestTraces.length} traces · ${latestTasks.length} tasks · ${latestVariants.length} variants`);
}

async function createAndRunTask() {
  const { targetType, targetId } = selectedTargetParts();
  const runId = String(runInput?.value || "").trim();
  setStatus("busy", "Running", `Generating candidate for ${targetType}:${targetId}.`);
  const created = await requestJson("/api/evolution/tasks", {
    method: "POST",
    body: JSON.stringify({
      target_type: targetType,
      target_id: targetId,
      source_run_ids: runId ? [runId] : [],
      objective: objectiveInput?.value || "Improve next closed-loop run reliability.",
      constraints: { require_human_approval: true, no_live_hardware_execution: true },
    }),
  });
  currentTaskId = created.task.task_id;
  renderPipeline(currentVariant);
  const result = await requestJson(`/api/evolution/tasks/${encodeURIComponent(currentTaskId)}/run`, { method: "POST", body: "{}" });
  if (result.variant) setVariant(result.variant);
  else write(result);
  await refresh();
}

async function loadVariant(variantId) {
  if (!variantId) return;
  const result = await requestJson(`/api/evolution/variants/${encodeURIComponent(variantId)}`);
  setVariant(result.variant);
  await refreshLineage();
  setStatus("idle", "Variant Loaded", variantId);
}

async function loadTaskVariants(taskId) {
  if (!taskId) return;
  currentTaskId = taskId;
  const result = await requestJson(`/api/evolution/tasks/${encodeURIComponent(taskId)}/variants`);
  const variants = sortedVariants(result.variants || []);
  latestVariants = variants;
  renderLeaderboard(variants);
  if (variants.length) {
    setVariant(variants[0]);
  } else {
    renderPipeline(currentVariant);
  }
  write({ task_id: taskId, variants });
  setStatus("idle", "Task Variants", `${variants.length} variants loaded for ${taskId}`);
}

async function validateCurrent() {
  if (!currentVariantId) throw new Error("No active variant.");
  const result = await requestJson(`/api/evolution/variants/${encodeURIComponent(currentVariantId)}/validate`, { method: "POST", body: "{}" });
  setVariant(result.variant);
  await refreshHistoryAndLineage();
}

async function approveCurrent() {
  if (!currentVariantId) throw new Error("No active variant.");
  const result = await requestJson(`/api/evolution/variants/${encodeURIComponent(currentVariantId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ operator: "runtime_gui", note: "Approved from Evolution Lab", activate_runtime: true }),
  });
  setVariant(result.variant);
  await refreshHistoryAndLineage();
}

async function activateCurrent() {
  if (!currentVariantId) throw new Error("No active variant.");
  const result = await requestJson(`/api/evolution/variants/${encodeURIComponent(currentVariantId)}/activate`, {
    method: "POST",
    body: JSON.stringify({ operator: "runtime_gui", note: "Activate for next run", activate_runtime: true }),
  });
  setVariant(result.variant);
  await refreshHistoryAndLineage();
}

async function rollbackCurrent() {
  if (!currentVariantId) throw new Error("No active variant.");
  const result = await requestJson(`/api/evolution/variants/${encodeURIComponent(currentVariantId)}/rollback`, {
    method: "POST",
    body: JSON.stringify({ operator: "runtime_gui", note: "Operator rollback mark" }),
  });
  setVariant(result.variant);
  await refreshHistoryAndLineage();
}

function bind(id, fn) {
  const el = $(id);
  if (!el) return;
  el.addEventListener("click", () => fn().catch((err) => { setStatus("error", "Error", err.message); write({ ok: false, error: err.message }); }));
}

bind("btn-evolution-refresh", refresh);
bind("btn-evolution-create-run", createAndRunTask);
bind("btn-evolution-validate", validateCurrent);
bind("btn-evolution-approve", approveCurrent);
bind("btn-evolution-activate", activateCurrent);
bind("btn-evolution-rollback", rollbackCurrent);

if (targetInput) {
  targetInput.addEventListener("change", () => {
    currentVariant = null;
    currentVariantId = "";
    refreshHistoryAndLineage().catch((err) => { setStatus("error", "Error", err.message); write({ ok: false, error: err.message }); });
  });
}

document.addEventListener("click", (event) => {
  const taskButton = event.target.closest(".evolution-task-action[data-task-id]");
  if (taskButton) {
    loadTaskVariants(taskButton.dataset.taskId || "").catch((err) => { setStatus("error", "Error", err.message); write({ ok: false, error: err.message }); });
    return;
  }
  const variantButton = event.target.closest(".evolution-variant-action[data-variant-id]");
  if (variantButton) {
    loadVariant(variantButton.dataset.variantId || "").catch((err) => { setStatus("error", "Error", err.message); write({ ok: false, error: err.message }); });
  }
});

renderPipeline(null);
refresh().catch((err) => { setStatus("error", "Error", err.message); write({ ok: false, error: err.message }); });
