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

let queryGoal = "Design and validate a live-mode specimen plan before hardware execution.";
let queryBackend = "vllm";
let planningMessagesCache = [];
let planningSessionId = "";
let planningThinkingCount = 0;
let planningBootstrapStarted = false;
let planningRefreshTimer = null;
let planningFreshSessionInitialized = false;
let planningPendingSpecimenInput = null;

function ensurePlanningSessionId() {
  const key = "autonomousLivePlanningSessionId";
  const params = new URLSearchParams(window.location.search);
  try {
    if (params.get("fresh") === "1" && !planningFreshSessionInitialized) {
      window.sessionStorage.removeItem(key);
      planningFreshSessionInitialized = true;
    }
    let existing = window.sessionStorage.getItem(key);
    if (!existing) {
      existing = `live-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      window.sessionStorage.setItem(key, existing);
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
  const constraints = {
    require_operator_approval: true,
    runtime_contract: "existing_stage_enum_only",
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

function setChatStatus(label, cls = "idle") {
  if (!planningChatStatus) return;
  planningChatStatus.textContent = label;
  planningChatStatus.className = `badge ${cls}`;
}

function updatePlanningControls() {
  const isThinking = planningThinkingCount > 0;
  if (btnPlanningSend) btnPlanningSend.disabled = isThinking;
  if (btnPlanningGenerate) btnPlanningGenerate.disabled = isThinking;
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

function renderSingleArtifactCard(artifacts, spec, label = "") {
  const previewUrl = safeUrl(artifacts.preview_url);
  const stlUrl = safeUrl(artifacts.stl_url);
  const specUrl = safeUrl(artifacts.experiment_spec_url);
  if (!previewUrl && !stlUrl && !specUrl) return "";

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
          ${stlUrl ? `<a href="${escapeHtml(stlUrl)}" target="_blank" rel="noreferrer">Open STL</a>` : ""}
          ${specUrl ? `<a href="${escapeHtml(specUrl)}" target="_blank" rel="noreferrer">experiment_spec.json</a>` : ""}
        </div>
      </div>
      ${stlUrl ? `
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
  const pair = msg.artifact_pair || {};
  if (pair.previous || pair.next) {
    const previous = pair.previous || {};
    const next = pair.next || {};
    const previousCard = renderSingleArtifactCard(
      previous.artifacts || {},
      previous.experiment_spec || {},
      previous.label || "Previous shape"
    );
    const nextCard = renderSingleArtifactCard(
      next.artifacts || {},
      next.experiment_spec || msg.experiment_spec || {},
      next.label || "Next shape"
    );
    return `<div class="artifact-pair">${previousCard}${nextCard}</div>`;
  }
  return renderSingleArtifactCard(msg.artifacts || {}, msg.experiment_spec || {});
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

function compactBoParams(params) {
  const p = params || {};
  const keys = ["geometry_type", "relative_density", "wall_thickness_mm", "cell_size_mm", "tpms_thickness", "orientation_deg", "anisotropy_ratio"];
  return keys
    .filter((key) => p[key] !== undefined && p[key] !== null)
    .map((key) => `${key}=${numberText(p[key], 4)}`)
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

function renderBoResultCard(msg) {
  const boResult = msg.bo_result && typeof msg.bo_result === "object" ? msg.bo_result : {};
  if (msg.role !== "bo_ai" || !Object.keys(boResult).length) return "";
  const benchmark = boResult.benchmark || {};
  const strategyPayload = boStrategyFromBenchmark(benchmark);
  const trace = strategyPayload && Array.isArray(strategyPayload.surrogate_trace) ? strategyPayload.surrogate_trace : [];
  const visibleTrace = trace.length > 12 ? trace.slice(-12) : trace;
  const recommendation = boResult.recommendation && typeof boResult.recommendation === "object" ? boResult.recommendation : {};
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
    <div class="bo-live-card">
      <div class="runtime-card-section">
        <h4>BO Surrogate / Acquisition Trace</h4>
        ${runtimeRows([
          ["strategy", boResult.strategy],
          ["acquisition", boResult.acquisition],
          ["budget", boResult.budget],
          ["recommended_candidate", recommendation.candidate_id],
          ["recommended_score", recommendation.objective_score],
        ])}
      </div>
      <div class="bo-plot-stack">
        ${trace.length > visibleTrace.length ? `<p class="hint">최근 ${visibleTrace.length}/${trace.length} step만 표시합니다.</p>` : ""}
        ${visibleTrace.length
          ? visibleTrace.map((item) => `<article class="bo-trace-card">${renderBoTraceSvg(item)}</article>`).join("")
          : `<div class="bo-plot-empty">BO surrogate/acquisition trace가 없습니다. BO/MBO strategy 결과가 들어오면 여기에 표시됩니다.</div>`}
      </div>
      ${selectedRows ? `<div class="bo-selected-points">${selectedRows}</div>` : ""}
    </div>
  `;
}

function renderRuntimeValue(value, fallback = "n/a") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value) || typeof value === "object") return JSON.stringify(value);
  return String(value);
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
    return;
  }

  planningChatLog.innerHTML = "";
  for (const msg of messages) {
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
      ${renderBoResultCard(msg)}
      ${renderArtifactCard(msg)}
    `;
    planningChatLog.appendChild(item);
  }
  planningChatLog.scrollTop = planningChatLog.scrollHeight;
  initStlViewers();
}

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

function applyPlanningSession(session) {
  const state = session.state || {};
  const metadata = state.run_metadata || {};
  planningPendingSpecimenInput = metadata.pending_specimen_input || null;
  const running = Boolean(session.is_running);
  setPlanningDot(running);
  if (planningStageLabel) {
    planningStageLabel.textContent = `Stage: ${state.stage || "idle"}`;
  }
  if (planningRunDetail) {
    planningRunDetail.textContent = `run=${state.run_id || "-"} mode=${state.mode || "-"} running=${running}`;
  }
  renderSpecSummary(state);
  renderPlanningMessages(session.messages || []);
}

async function refreshPlanningState() {
  const sessionId = encodeURIComponent(ensurePlanningSessionId());
  const res = await fetch(`/api/planning/session?session_id=${sessionId}`);
  const session = await res.json();
  applyPlanningSession(session);
}

function schedulePlanningRefresh() {
  if (planningRefreshTimer) return;
  planningRefreshTimer = window.setTimeout(async () => {
    planningRefreshTimer = null;
    try {
      await refreshPlanningState();
    } catch (err) {
      setChatStatus("ERROR", "warning");
    }
  }, 120);
}

async function sendPlanningMessage(message) {
  const clean = String(message || "").trim();
  if (!clean) return;
  if (planningThinkingCount > 0) return;
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
  if (!window.EventSource) return;
  const source = new EventSource("/api/events/stream");
  source.addEventListener("update", (event) => {
    try {
      const data = JSON.parse(event.data || "{}");
      const eventType = String(data.event_type || "");
      if (eventType.startsWith("planning_") || eventType === "planning_message") {
        schedulePlanningRefresh();
      }
    } catch (err) {
      setChatStatus("ERROR", "warning");
    }
  });
  source.onerror = () => {
    source.close();
  };
}

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
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      sendPlanningMessage(planningMessageInput.value);
    }
  });
}

applyQueryGoal();
ensurePlanningSessionId();
connectPlanningEventStream();
refreshPlanningState()
  .then(bootstrapLiveOrchestrator)
  .catch(() => setChatStatus("ERROR", "warning"));
