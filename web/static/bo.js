/*
File purpose:
- Frontend runtime for BO Workspace controls.

Key classes/functions:
- loadConfig
- runBenchmark
- runBOAgent

Inputs/outputs:
- Input: operator BO settings
- Output: benchmark/recommendation panels

Dependencies:
- /api/bo/config
- /api/bo/benchmark
- /api/bo/run
*/

const boStatusDot = document.getElementById("bo-status-dot");
const boStatusLabel = document.getElementById("bo-status-label");
const boStatusDetail = document.getElementById("bo-status-detail");
const strategyInput = document.getElementById("bo-strategy-input");
const backendInput = document.getElementById("bo-backend-input");
const acquisitionInput = document.getElementById("bo-acquisition-input");
const budgetInput = document.getElementById("bo-budget-input");
const seedInput = document.getElementById("bo-seed-input");
const kappaInput = document.getElementById("bo-kappa-input");
const xiInput = document.getElementById("bo-xi-input");
const explorationInput = document.getElementById("bo-exploration-input");
const exploitationInput = document.getElementById("bo-exploitation-input");
const llmPreferenceInput = document.getElementById("bo-llm-preference-input");
const llmWeightInput = document.getElementById("bo-llm-weight-input");
const topKInput = document.getElementById("bo-top-k-input");
const objectiveInput = document.getElementById("bo-objective-input");
const parameterSpaceInput = document.getElementById("bo-parameter-space-input");
const btnBenchmark = document.getElementById("btn-bo-benchmark");
const btnRun = document.getElementById("btn-bo-run");
const btnSave = document.getElementById("btn-bo-save");
const btnReset = document.getElementById("btn-bo-reset");
const recommendationLabel = document.getElementById("bo-recommendation-label");
const bestScoreLabel = document.getElementById("bo-best-score-label");
const curveTable = document.getElementById("bo-curve-table");
const surrogatePlot = document.getElementById("bo-surrogate-plot");
const selectedPoints = document.getElementById("bo-selected-points");
const priorSummaryPanel = document.getElementById("bo-prior-summary");
const reasoningPanel = document.getElementById("bo-reasoning-panel");
const candidateRankingPanel = document.getElementById("bo-candidate-ranking");
const recommendationPanel = document.getElementById("bo-recommendation-panel");
const resultJson = document.getElementById("bo-result-json");
const objectiveIntentInput = document.getElementById("objective-intent-input");
const objectiveOperatorInput = document.getElementById("objective-operator-input");
const objectiveRunIdInput = document.getElementById("objective-run-id-input");
const objectiveVersionSelect = document.getElementById("objective-version-select");
const objectiveMetricBrowser = document.getElementById("objective-metric-browser");
const objectiveEquationTree = document.getElementById("objective-equation-tree");
const objectiveValidationPanel = document.getElementById("objective-validation-panel");
const objectivePreviewPanel = document.getElementById("objective-preview-summary");
const objectivePreviewObservationsInput = document.getElementById("objective-preview-observations-input");
const objectiveScoreChart = document.getElementById("objective-preview-score-chart");
const objectiveContributionChart = document.getElementById("objective-preview-contribution-chart");
const objectiveSensitivityChart = document.getElementById("objective-preview-sensitivity-chart");
const objectiveVersionDiff = document.getElementById("objective-version-diff");
const objectiveLifecycleChip = document.getElementById("objective-lifecycle-chip");
const objectiveActiveIdentity = document.getElementById("objective-active-identity");
const objectiveActiveHash = document.getElementById("objective-active-hash");
const objectiveActionStatus = document.getElementById("objective-action-status");
const btnObjectiveCompose = document.getElementById("btn-objective-compose");
const btnObjectiveRevise = document.getElementById("btn-objective-revise");
const btnObjectiveRefresh = document.getElementById("btn-objective-refresh");
const btnObjectiveValidate = document.getElementById("btn-objective-validate");
const btnObjectivePreview = document.getElementById("btn-objective-preview");
const btnObjectiveApprove = document.getElementById("btn-objective-approve");
const btnObjectiveActivate = document.getElementById("btn-objective-activate");

let defaults = {};
let objectiveMetrics = [];
let objectiveRuntimeStatus = {};
let selectedObjectiveState = null;
let objectiveActionBusy = false;

function setDot(el, state) {
  if (!el) return;
  el.className = `status-dot ${state}`;
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await res.json();
  if (!res.ok) {
    const detail = payload && payload.detail !== undefined ? payload.detail : payload;
    throw new Error(typeof detail === "string" ? detail : pretty(detail));
  }
  return payload;
}

async function getJson(url) {
  const res = await fetch(url);
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`);
  return payload;
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function numberText(value, digits = 4) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "n/a";
  return String(Number(num.toFixed(digits)));
}

function boolValue(el, fallback = true) {
  if (!el) return fallback;
  const value = String(el.value ?? fallback).trim().toLowerCase();
  if (["true", "1", "yes", "on", "enabled"].includes(value)) return true;
  if (["false", "0", "no", "off", "disabled"].includes(value)) return false;
  return fallback;
}

function parseJsonField(el, fallback) {
  try {
    const text = (el && el.value ? el.value : "").trim();
    return text ? JSON.parse(text) : fallback;
  } catch (err) {
    throw new Error(`Invalid JSON: ${err.message || err}`);
  }
}

function settingsPayload() {
  return {
    strategy: strategyInput.value,
    bo_backend: backendInput ? backendInput.value : "lightweight_pool",
    acquisition: acquisitionInput.value,
    budget: Number(budgetInput.value || 1),
    random_seed: Number(seedInput.value || 7),
    kappa: Number(kappaInput.value || 2.0),
    xi: Number(xiInput.value || 0.01),
    exploration_weight: Number(explorationInput.value || 0.35),
    exploitation_weight: Number(exploitationInput.value || 0.65),
    llm_preference_enabled: boolValue(llmPreferenceInput, true),
    llm_candidate_weight: (llmWeightInput.value || "auto").trim() || "auto",
    top_k: Number(topKInput.value || 5),
    objective: parseJsonField(objectiveInput, {}),
    parameter_space: parseJsonField(parameterSpaceInput, defaults.parameter_space || {}),
    mode: "test",
  };
}

function applyDefaults(data) {
  defaults = data.defaults || {};
  strategyInput.value = defaults.strategy || "bo";
  if (backendInput) backendInput.value = defaults.bo_backend || "lightweight_pool";
  acquisitionInput.value = defaults.acquisition || "expected_improvement";
  budgetInput.value = defaults.budget || 8;
  seedInput.value = defaults.random_seed || 7;
  kappaInput.value = defaults.kappa || 2.0;
  xiInput.value = defaults.xi || 0.01;
  explorationInput.value = defaults.exploration_weight || 0.35;
  exploitationInput.value = defaults.exploitation_weight || 0.65;
  if (llmPreferenceInput) llmPreferenceInput.value = String(defaults.llm_preference_enabled ?? true);
  if (llmWeightInput) llmWeightInput.value = defaults.llm_candidate_weight ?? "auto";
  if (topKInput) topKInput.value = defaults.top_k || 5;
  parameterSpaceInput.value = pretty(defaults.parameter_space || {});
  objectiveInput.value = "{}";
}

function applySettings(settings) {
  if (!settings || typeof settings !== "object") return;
  if (settings.strategy) strategyInput.value = settings.strategy;
  if (settings.bo_backend && backendInput) backendInput.value = settings.bo_backend;
  if (settings.acquisition) acquisitionInput.value = settings.acquisition;
  if (settings.budget !== undefined) budgetInput.value = settings.budget;
  if (settings.random_seed !== undefined) seedInput.value = settings.random_seed;
  if (settings.kappa !== undefined) kappaInput.value = settings.kappa;
  if (settings.xi !== undefined) xiInput.value = settings.xi;
  if (settings.exploration_weight !== undefined) explorationInput.value = settings.exploration_weight;
  if (settings.exploitation_weight !== undefined) exploitationInput.value = settings.exploitation_weight;
  if (settings.llm_preference_enabled !== undefined && llmPreferenceInput) llmPreferenceInput.value = String(settings.llm_preference_enabled);
  if (settings.llm_candidate_weight !== undefined && llmWeightInput) llmWeightInput.value = settings.llm_candidate_weight;
  if (settings.top_k !== undefined && topKInput) topKInput.value = settings.top_k;
  if (settings.parameter_space && typeof settings.parameter_space === "object") {
    parameterSpaceInput.value = pretty(settings.parameter_space);
  }
  if (settings.objective && typeof settings.objective === "object") {
    objectiveInput.value = pretty(settings.objective);
  }
}

function renderCurve(curve) {
  const items = Array.isArray(curve) ? curve : [];
  if (!items.length) {
    curveTable.textContent = "No best-so-far data yet.";
    return;
  }
  curveTable.innerHTML = items
    .map((item) => {
      const step = item.step ?? "";
      const score = item.score ?? "n/a";
      const best = item.best_score ?? "n/a";
      const candidate = item.candidate_id || "";
      return `<div class="log-line"><strong>#${step}</strong> score=${score} best=${best} candidate=${candidate}</div>`;
    })
    .join("");
}

function firstCurveFromBenchmark(benchmark) {
  const strategies = benchmark && benchmark.strategies ? benchmark.strategies : {};
  const firstKey = Object.keys(strategies)[0];
  return firstKey && strategies[firstKey] ? strategies[firstKey].curve || [] : [];
}

function boStrategyFromBenchmark(benchmark) {
  const strategies = benchmark && benchmark.strategies ? benchmark.strategies : {};
  if (strategies.bo) return strategies.bo;
  const firstKey = Object.keys(strategies)[0];
  return firstKey ? strategies[firstKey] : null;
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

function compactParams(params) {
  const p = params || {};
  const keys = ["relative_density", "wall_thickness_mm", "cell_size_mm", "tpms_thickness", "orientation_deg", "anisotropy_ratio"];
  return keys
    .filter((key) => p[key] !== undefined && p[key] !== null)
    .map((key) => `${key}=${numberText(p[key], 4)}`)
    .join(", ");
}

function traceSvg(trace) {
  const candidates = Array.isArray(trace.candidates) ? trace.candidates : [];
  if (!candidates.length) {
    return `<div class="bo-plot-empty">No candidate landscape for step ${escapeHtml(trace.step || "")}.</div>`;
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
  const band = [...upper, ...lower];
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
      <polygon points="${polyline(band)}" class="bo-uncertainty-band"></polygon>
      <polyline points="${polyline(meanLine)}" class="bo-mean-line"></polyline>
      <polyline points="${polyline(acqLine)}" class="bo-acq-line"></polyline>
      ${observed.map((point) => `
        <circle cx="${xScale(point.x)}" cy="${yScore(point.score)}" r="5.8" class="bo-observed-point">
          <title>${escapeHtml(point.candidate_id || point.source || "observed")} score=${escapeHtml(numberText(point.score, 5))} ${escapeHtml(compactParams(point.parameters))}</title>
        </circle>
      `).join("")}
      ${Number.isFinite(selectedX) ? `
        <line x1="${xScale(selectedX)}" y1="${pad.top}" x2="${xScale(selectedX)}" y2="${pad.top + plotH}" class="bo-selected-line"></line>
        <circle cx="${xScale(selectedX)}" cy="${selectedY}" r="8" class="bo-selected-point">
          <title>${escapeHtml(selected.candidate_id || "selected")} acquisition=${escapeHtml(numberText(selected.acquisition_value, 5))} ${escapeHtml(compactParams(selected.parameters))}</title>
        </circle>
      ` : ""}
      <text x="${pad.left}" y="20" class="bo-svg-title">step ${escapeHtml(trace.step)} · ${escapeHtml(trace.acquisition || "acquisition")} · x: candidate pool index</text>
      <g class="bo-legend">
        <line x1="${width - 330}" y1="20" x2="${width - 300}" y2="20" class="bo-mean-line"></line>
        <text x="${width - 294}" y="24">surrogate mean</text>
        <line x1="${width - 190}" y1="20" x2="${width - 160}" y2="20" class="bo-acq-line"></line>
        <text x="${width - 154}" y="24">acquisition</text>
      </g>
    </svg>
  `;
}

function renderSurrogateTrace(benchmark) {
  const strategyPayload = boStrategyFromBenchmark(benchmark);
  const trace = strategyPayload && Array.isArray(strategyPayload.surrogate_trace) ? strategyPayload.surrogate_trace : [];
  if (!surrogatePlot || !selectedPoints) return;
  if (!trace.length) {
    surrogatePlot.innerHTML = `<div class="bo-plot-empty">BO strategy trace가 아직 없습니다. strategy=bo 또는 mbo로 실행하세요.</div>`;
    selectedPoints.innerHTML = "";
    return;
  }
  const visibleTrace = trace.length > 20 ? trace.slice(-20) : trace;
  const hiddenNote = trace.length > visibleTrace.length ? `<p class="hint">최근 ${visibleTrace.length}/${trace.length} step만 표시합니다.</p>` : "";
  surrogatePlot.innerHTML = `${hiddenNote}${visibleTrace.map((item) => `
    <article class="bo-trace-card">
      ${traceSvg(item)}
    </article>
  `).join("")}`;
  selectedPoints.innerHTML = trace
    .map((item) => {
      const selected = item.selected || {};
      return `
        <div class="bo-selected-row">
          <strong>#${escapeHtml(item.step || "")}</strong>
          <span>${escapeHtml(selected.candidate_id || "candidate")}</span>
          <code>${escapeHtml(compactParams(selected.parameters))}</code>
          <em>score=${escapeHtml(numberText(selected.score, 5))} · acq=${escapeHtml(numberText(selected.acquisition_value, 5))}</em>
        </div>
      `;
    })
    .join("");
}

function paramsHtml(params) {
  const entries = Object.entries(params || {}).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (!entries.length) return `<span class="hint">No parameters.</span>`;
  return `<div class="bo-param-grid">${entries
    .map(([key, value]) => `<div><span>${escapeHtml(key)}</span><strong>${escapeHtml(typeof value === "number" ? numberText(value, 5) : value)}</strong></div>`)
    .join("")}</div>`;
}

function renderPriorSummary(summary) {
  if (!priorSummaryPanel) return;
  if (!summary || typeof summary !== "object") {
    priorSummaryPanel.innerHTML = "No prior evidence loaded.";
    return;
  }
  priorSummaryPanel.innerHTML = `
    <div class="bo-kpi-grid">
      <div><span>prior</span><strong>${escapeHtml(summary.prior_count ?? 0)}</strong></div>
      <div><span>measured</span><strong>${escapeHtml(summary.measured_count ?? 0)}</strong></div>
      <div><span>failed</span><strong>${escapeHtml(summary.failed_count ?? 0)}</strong></div>
      <div><span>best score</span><strong>${escapeHtml(numberText(summary.best_score, 5))}</strong></div>
      <div><span>best candidate</span><strong>${escapeHtml(summary.best_candidate_id || "n/a")}</strong></div>
    </div>
  `;
}

function renderReasoning(reasoning, failureModel) {
  if (!reasoningPanel) return;
  if (!reasoning || typeof reasoning !== "object") {
    reasoningPanel.innerHTML = "No reasoning artifact yet.";
    return;
  }
  const strategy = reasoning.strategy_recommendation || {};
  const hypotheses = Array.isArray(reasoning.hypotheses) ? reasoning.hypotheses : [];
  const regions = Array.isArray(reasoning.preference_regions) ? reasoning.preference_regions : [];
  const risks = Array.isArray(failureModel?.risk_patterns) ? failureModel.risk_patterns : [];
  reasoningPanel.innerHTML = `
    <div class="bo-reasoning-head">
      <span>source: <strong>${escapeHtml(reasoning.source || "unknown")}</strong></span>
      <span>strategy: <strong>${escapeHtml(strategy.strategy || "n/a")}</strong></span>
      <span>acquisition: <strong>${escapeHtml(strategy.acquisition || "n/a")}</strong></span>
    </div>
    <p class="bo-reasoning-summary">${escapeHtml(reasoning.operator_summary || strategy.reason || "No operator summary.")}</p>
    <div class="bo-two-column">
      <div>
        <h4>Hypotheses</h4>
        ${hypotheses.length ? `<ol class="bo-compact-list">${hypotheses.map((item) => `
          <li><strong>${escapeHtml(item.id || "h")}</strong> ${escapeHtml(item.claim || "")}
            <em>confidence=${escapeHtml(numberText(item.confidence, 2))}</em>
          </li>`).join("")}</ol>` : `<p class="hint">No hypothesis entries.</p>`}
      </div>
      <div>
        <h4>Preference / Failure Regions</h4>
        ${regions.length ? `<ol class="bo-compact-list">${regions.slice(0, 6).map((item) => `
          <li><strong>${escapeHtml(numberText(item.preference_score, 2))}</strong> ${escapeHtml(item.condition || "")}</li>`).join("")}</ol>` : `<p class="hint">No preference regions.</p>`}
        ${risks.length ? `<p class="hint">Failure risk patterns: ${escapeHtml(risks.length)}</p>` : ""}
      </div>
    </div>
  `;
}

function renderCandidateRanking(ranking) {
  if (!candidateRankingPanel) return;
  const rows = Array.isArray(ranking) ? ranking.slice(0, 8) : [];
  if (!rows.length) {
    candidateRankingPanel.innerHTML = "No ranked candidates yet.";
    return;
  }
  candidateRankingPanel.innerHTML = rows
    .map((item, idx) => {
      const numeric = item.numeric || {};
      const llm = item.llm || {};
      const constraints = item.constraints || {};
      const warnings = Array.isArray(constraints.warnings) ? constraints.warnings : [];
      return `
        <article class="bo-candidate-card ${constraints.valid === false ? "warn" : ""}">
          <div class="bo-candidate-head">
            <strong>#${idx + 1} ${escapeHtml(item.candidate_id || "candidate")}</strong>
            <span>combined=${escapeHtml(numberText(item.combined_score, 5))}</span>
          </div>
          <div class="bo-candidate-metrics">
            <span>acq ${escapeHtml(numberText(numeric.acquisition_value, 5))}</span>
            <span>mean ${escapeHtml(numberText(numeric.surrogate_mean, 5))}</span>
            <span>unc ${escapeHtml(numberText(numeric.uncertainty, 5))}</span>
            <span>llm ${escapeHtml(numberText(llm.preference_score, 3))}</span>
            <span>risk ${escapeHtml(numberText(constraints.risk_score, 3))}</span>
          </div>
          ${paramsHtml(item.parameters || {})}
          ${warnings.length ? `<p class="bo-warning">${escapeHtml(warnings.join("; "))}</p>` : ""}
        </article>
      `;
    })
    .join("");
}

function renderRecommendationPanel(recommendation, nextDesignRequest) {
  if (!recommendationPanel) return;
  if (!recommendation || typeof recommendation !== "object" || !recommendation.candidate_id) {
    recommendationPanel.innerHTML = "Run BO Agent to generate a next-design handoff.";
    return;
  }
  recommendationPanel.innerHTML = `
    <div class="bo-recommendation-title">
      <strong>${escapeHtml(recommendation.candidate_id)}</strong>
      <span>${escapeHtml(recommendation.source_strategy || "bo")}</span>
    </div>
    <p>${escapeHtml(recommendation.why_this_candidate || recommendation.reason || "Recommended by candidate ranking.")}</p>
    ${paramsHtml(recommendation.parameters || {})}
    <div class="bo-handoff-note">
      <span>handoff: ${escapeHtml(nextDesignRequest?.schema || "next_design_request.v1")}</span>
      <span>status: ${escapeHtml(nextDesignRequest?.status || "ready")}</span>
    </div>
  `;
}

function renderResult(data) {
  const boResult = data?.data?.bo_result || data?.bo_result || null;
  const benchmark = boResult ? boResult.benchmark : data.benchmark;
  const recommendation = boResult ? boResult.recommendation || {} : {};
  const strategyPayload = benchmark?.strategies ? Object.values(benchmark.strategies)[0] || {} : {};
  const backendNote = boResult ? ` · backend=${boResult.bo_backend || "lightweight_pool"}/${strategyPayload.backend_active || "lightweight_pool"}` : "";
  const score = recommendation.objective_score ?? (benchmark?.strategies ? strategyPayload.best_score : "n/a");
  recommendationLabel.textContent = recommendation.candidate_id || "benchmark only";
  bestScoreLabel.textContent = `${score ?? "n/a"}${backendNote}`;
  renderRecommendationPanel(recommendation, boResult ? boResult.next_design_request : null);
  renderPriorSummary(boResult ? boResult.prior_summary : null);
  renderReasoning(boResult ? boResult.reasoning : null, boResult ? boResult.failure_model : null);
  renderCandidateRanking(boResult ? boResult.candidate_ranking || boResult.candidate_pool : []);
  renderCurve(boResult ? boResult.best_so_far || [] : firstCurveFromBenchmark(benchmark));
  renderSurrogateTrace(benchmark);
  resultJson.textContent = pretty(data);
}

function objectiveStateKey(state) {
  return state ? `${state.objective_id}::${state.version}` : "";
}

function objectiveLifecycle(state) {
  if (!state) return "No objective";
  if (state.active) return "Active";
  if (state.approved) return "Approved";
  if (state.preview && Number(state.preview.usable_rows || 0) > 0) return "Previewed";
  if (state.validation && state.validation.valid) return "Validated";
  return "Draft";
}

function expressionSummary(node) {
  if (!node || typeof node !== "object") return String(node ?? "-");
  if (node.op === "metric") return node.metric_id || "metric";
  if (node.op === "literal") return numberText(node.value, 5);
  const children = Array.isArray(node.args)
    ? node.args
    : node.arg !== undefined
      ? [node.arg]
      : node.left !== undefined || node.right !== undefined
        ? [node.left, node.right]
        : [];
  const rendered = children.filter((item) => item !== undefined).map(expressionSummary);
  if (!rendered.length) return node.op || "expression";
  return `${node.op}(${rendered.join(", ")})`;
}

function expressionTreeHtml(node, label = "objective") {
  if (!node || typeof node !== "object") return `<li><span>${escapeHtml(label)}</span><strong>${escapeHtml(node)}</strong></li>`;
  const operator = node.op || "node";
  const details = Object.entries(node)
    .filter(([key, value]) => !["op", "args", "arg", "left", "right"].includes(key) && (typeof value !== "object" || value === null))
    .map(([key, value]) => `<code>${escapeHtml(key)}=${escapeHtml(value)}</code>`)
    .join("");
  const children = Array.isArray(node.args)
    ? node.args.map((value, index) => [`arg ${index + 1}`, value])
    : node.arg !== undefined
      ? [["arg", node.arg]]
      : [["left", node.left], ["right", node.right]].filter(([, value]) => value !== undefined);
  return `<li><div class="bo-equation-node"><span>${escapeHtml(label)}</span><strong>${escapeHtml(operator)}</strong>${details}</div>${children.length ? `<ul>${children.map(([childLabel, value]) => expressionTreeHtml(value, childLabel)).join("")}</ul>` : ""}</li>`;
}

function renderMetricRegistry() {
  if (!objectiveMetricBrowser) return;
  if (!objectiveMetrics.length) {
    objectiveMetricBrowser.textContent = "No registered metrics.";
    return;
  }
  objectiveMetricBrowser.innerHTML = objectiveMetrics.map((metric) => `
    <article class="bo-metric-entry" title="${escapeHtml(metric.description || metric.metric_id)}">
      <strong>${escapeHtml(metric.label || metric.metric_id)}</strong>
      <code>${escapeHtml(metric.metric_id)}</code>
      <span>${escapeHtml(metric.unit || "dimensionless")} · ${escapeHtml((metric.fidelity || []).join(" / "))}</span>
    </article>
  `).join("");
}

function objectiveBarChart(values, options = {}) {
  const entries = Object.entries(values || {}).filter(([, value]) => Number.isFinite(Number(value)));
  if (!entries.length) return `<p class="bo-objective-empty">No preview data.</p>`;
  const maxAbs = Math.max(1e-9, ...entries.map(([, value]) => Math.abs(Number(value))));
  return `<div class="bo-objective-bars">${entries.map(([key, value]) => {
    const numeric = Number(value);
    const width = Math.max(2, Math.abs(numeric) / maxAbs * 100);
    return `<div class="bo-objective-bar-row"><span>${escapeHtml(key)}</span><div><i style="width:${width}%" class="${numeric < 0 ? "negative" : ""}"></i></div><strong>${escapeHtml(numberText(numeric, options.digits ?? 4))}</strong></div>`;
  }).join("")}</div>`;
}

function renderObjectiveDiff(state) {
  if (!objectiveVersionDiff) return;
  if (!state) {
    objectiveVersionDiff.textContent = "No prior version.";
    return;
  }
  const previous = (objectiveRuntimeStatus.objective_states || []).find((item) => item.objective_id === state.objective_id && Number(item.version) === Number(state.version) - 1);
  if (!previous) {
    objectiveVersionDiff.innerHTML = `<span class="hint">Version ${escapeHtml(state.version)} is the first stored version.</span>`;
    return;
  }
  const currentSpec = state.spec || {};
  const previousSpec = previous.spec || {};
  const changes = [
    ["Intent", previousSpec.intent, currentSpec.intent],
    ["Direction", previousSpec.direction, currentSpec.direction],
    ["Equation", expressionSummary(previousSpec.expression), expressionSummary(currentSpec.expression)],
    ["Constraints", (previousSpec.constraints || []).length, (currentSpec.constraints || []).length],
  ].filter(([, before, after]) => String(before ?? "") !== String(after ?? ""));
  objectiveVersionDiff.innerHTML = changes.length
    ? `<div class="bo-objective-diff-list">${changes.map(([label, before, after]) => `<div><strong>${escapeHtml(label)}</strong><del>${escapeHtml(before ?? "-")}</del><ins>${escapeHtml(after ?? "-")}</ins></div>`).join("")}</div>`
    : `<span class="hint">No semantic changes detected from version ${escapeHtml(previous.version)}.</span>`;
}

function renderObjectivePreview(preview) {
  if (objectivePreviewPanel) {
    objectivePreviewPanel.innerHTML = preview
      ? `<div class="bo-objective-kpis"><div><span>usable</span><strong>${escapeHtml(preview.usable_rows)}</strong></div><div><span>feasible</span><strong>${escapeHtml(preview.feasible_ratio === null ? "n/a" : `${numberText(Number(preview.feasible_ratio) * 100, 1)}%`)}</strong></div><div><span>rejected</span><strong>${escapeHtml(preview.rejected_rows)}</strong></div><div><span>fidelity</span><strong>${escapeHtml(Object.keys(preview.fidelity_groups || {}).join(" / ") || "n/a")}</strong></div></div>`
      : "No preview.";
  }
  if (objectiveScoreChart) objectiveScoreChart.innerHTML = objectiveBarChart(preview?.score_distribution);
  if (objectiveContributionChart) objectiveContributionChart.innerHTML = objectiveBarChart(preview?.contribution_summary);
  if (objectiveSensitivityChart) objectiveSensitivityChart.innerHTML = objectiveBarChart(preview?.sensitivity);
}

function updateObjectiveButtons() {
  const state = selectedObjectiveState;
  const valid = Boolean(state?.validation?.valid);
  const previewed = Boolean(state?.preview && Number(state.preview.usable_rows || 0) > 0);
  const approved = Boolean(state?.approved);
  [btnObjectiveCompose, btnObjectiveRefresh].forEach((button) => { if (button) button.disabled = objectiveActionBusy; });
  if (btnObjectiveRevise) btnObjectiveRevise.disabled = objectiveActionBusy || !state;
  if (btnObjectiveValidate) btnObjectiveValidate.disabled = objectiveActionBusy || !state;
  if (btnObjectivePreview) btnObjectivePreview.disabled = objectiveActionBusy || !state || !valid;
  if (btnObjectiveApprove) btnObjectiveApprove.disabled = objectiveActionBusy || !valid || !previewed || approved;
  if (btnObjectiveActivate) btnObjectiveActivate.disabled = objectiveActionBusy || !approved || !String(objectiveRunIdInput?.value || "").trim();
}

function renderSelectedObjective(state) {
  selectedObjectiveState = state || null;
  const lifecycle = objectiveLifecycle(state);
  if (objectiveLifecycleChip) {
    objectiveLifecycleChip.textContent = lifecycle;
    objectiveLifecycleChip.className = `runtime-chip ${state?.active || state?.approved ? "ok" : state?.validation?.valid ? "running" : state ? "warning" : "idle"}`;
  }
  if (objectiveActiveIdentity) objectiveActiveIdentity.textContent = state ? `${state.objective_id} · v${state.version}` : "Unbound";
  if (objectiveActiveHash) objectiveActiveHash.textContent = state?.objective_hash ? `hash ${state.objective_hash.slice(0, 12)}` : "hash -";
  if (objectiveIntentInput && state?.spec?.intent) objectiveIntentInput.value = state.spec.intent;
  if (objectiveEquationTree) {
    const expression = state?.spec?.expression;
    const constraints = state?.spec?.constraints || [];
    objectiveEquationTree.innerHTML = expression
      ? `<p class="bo-equation-summary">${escapeHtml(state.spec.direction || "maximize")} · ${escapeHtml(expressionSummary(expression))}</p><ul class="bo-equation-root">${expressionTreeHtml(expression)}${constraints.map((constraint, index) => expressionTreeHtml(constraint, `constraint ${index + 1}`)).join("")}</ul>`
      : "Compose or select an objective.";
  }
  if (objectiveValidationPanel) {
    const validation = state?.validation;
    objectiveValidationPanel.innerHTML = validation
      ? `<div class="bo-objective-validation ${validation.valid ? "valid" : "invalid"}"><strong>${validation.valid ? "VALID" : "INVALID"}</strong><span>${escapeHtml(validation.node_count)} nodes · depth ${escapeHtml(validation.max_depth)} · ${escapeHtml(validation.result_dimension || "dimensionless")}</span>${validation.warnings?.length ? `<p>${escapeHtml(validation.warnings.join("; "))}</p>` : ""}${validation.errors?.length ? `<p>${escapeHtml(validation.errors.join("; "))}</p>` : ""}</div>`
      : "Not validated.";
  }
  renderObjectivePreview(state?.preview || null);
  renderObjectiveDiff(state);
  objectiveInput.value = state ? pretty({
    objective_id: state.objective_id,
    objective_version: state.version,
    objective_hash: state.objective_hash || "",
    name: state.spec?.name || "",
    direction: state.spec?.direction || "maximize",
  }) : "{}";
  updateObjectiveButtons();
}

function populateObjectiveVersions(preferredKey = "") {
  if (!objectiveVersionSelect) return;
  const states = [...(objectiveRuntimeStatus.objective_states || [])].sort((left, right) => {
    if (left.objective_id !== right.objective_id) return left.objective_id.localeCompare(right.objective_id);
    return Number(right.version) - Number(left.version);
  });
  const currentKey = preferredKey || objectiveVersionSelect.value || objectiveStateKey(states.find((item) => item.active)) || objectiveStateKey(states[0]);
  objectiveVersionSelect.innerHTML = states.length
    ? states.map((state) => `<option value="${escapeHtml(objectiveStateKey(state))}">${escapeHtml(state.objective_id)} · v${escapeHtml(state.version)} · ${escapeHtml(objectiveLifecycle(state))}</option>`).join("")
    : `<option value="">No saved objective</option>`;
  const selected = states.find((state) => objectiveStateKey(state) === currentKey) || states[0] || null;
  if (selected) objectiveVersionSelect.value = objectiveStateKey(selected);
  renderSelectedObjective(selected);
}

async function refreshObjectiveCompiler(preferredKey = "") {
  const runId = String(objectiveRunIdInput?.value || "").trim();
  const [metrics, status] = await Promise.all([
    getJson("/api/objectives/metrics"),
    getJson(`/api/objectives/status${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`),
  ]);
  objectiveMetrics = Array.isArray(metrics.metrics) ? metrics.metrics : [];
  objectiveRuntimeStatus = status || {};
  renderMetricRegistry();
  populateObjectiveVersions(preferredKey);
}

async function runObjectiveAction(label, action) {
  if (objectiveActionBusy) return;
  objectiveActionBusy = true;
  if (objectiveActionStatus) objectiveActionStatus.textContent = label;
  updateObjectiveButtons();
  try {
    const preferredKey = await action();
    await refreshObjectiveCompiler(preferredKey || objectiveStateKey(selectedObjectiveState));
    if (objectiveActionStatus) objectiveActionStatus.textContent = `${label} complete.`;
  } catch (err) {
    if (objectiveActionStatus) objectiveActionStatus.textContent = `Error: ${err.message || err}`;
    try {
      await refreshObjectiveCompiler(objectiveStateKey(selectedObjectiveState));
    } catch (_refreshErr) {
      // Preserve the original action error when state refresh is also unavailable.
    }
  } finally {
    objectiveActionBusy = false;
    updateObjectiveButtons();
  }
}

function selectedObjectiveReference() {
  if (!selectedObjectiveState) throw new Error("Select or compose an objective first.");
  return { objective_id: selectedObjectiveState.objective_id, version: Number(selectedObjectiveState.version) };
}

async function composeObjective() {
  const intent = String(objectiveIntentInput?.value || "").trim();
  if (!intent) throw new Error("Research intent is required.");
  const result = await postJson("/api/objectives/compose", { intent });
  return `${result.draft.objective_id}::${result.draft.version}`;
}

async function reviseObjective() {
  const intent = String(objectiveIntentInput?.value || "").trim();
  if (!intent) throw new Error("Revision instruction is required.");
  const reference = selectedObjectiveReference();
  const result = await postJson("/api/objectives/revise", { objective_id: reference.objective_id, instruction: intent });
  return `${result.draft.objective_id}::${result.draft.version}`;
}

async function validateObjective() {
  await postJson("/api/objectives/validate", selectedObjectiveReference());
  return objectiveStateKey(selectedObjectiveState);
}

async function previewObjective() {
  const observations = parseJsonField(objectivePreviewObservationsInput, []);
  if (!Array.isArray(observations) || !observations.length) throw new Error("Preview requires at least one observation row.");
  await postJson("/api/objectives/preview", { ...selectedObjectiveReference(), observations });
  return objectiveStateKey(selectedObjectiveState);
}

async function approveObjective() {
  const operator = String(objectiveOperatorInput?.value || "").trim();
  if (!operator) throw new Error("Operator is required.");
  await postJson("/api/objectives/approve", { ...selectedObjectiveReference(), operator });
  return objectiveStateKey(selectedObjectiveState);
}

async function activateObjective() {
  const operator = String(objectiveOperatorInput?.value || "").trim();
  const runId = String(objectiveRunIdInput?.value || "").trim();
  if (!operator || !runId) throw new Error("Operator and Run ID are required.");
  await postJson("/api/objectives/activate", { ...selectedObjectiveReference(), operator, run_id: runId });
  return objectiveStateKey(selectedObjectiveState);
}

async function loadConfig() {
  setDot(boStatusDot, "idle");
  boStatusLabel.textContent = "Loading";
  boStatusDetail.textContent = "Reading BO defaults.";
  const res = await fetch("/api/bo/config");
  const data = await res.json();
  applyDefaults(data);
  applySettings(data.saved || {});
  setDot(boStatusDot, data.ok ? "busy" : "warn");
  boStatusLabel.textContent = data.ok ? "Ready" : "Unavailable";
  const savedNote = data.saved && Object.keys(data.saved).length ? ` · saved=${data.settings_path || "memory"}` : "";
  boStatusDetail.textContent = data.recent && data.recent.recommendation ? `Latest: ${data.recent.recommendation.candidate_id}${savedNote}` : `No recent BO Agent run.${savedNote}`;
  if (data.recent && data.recent.recommendation) {
    renderResult({ data: { bo_result: data.recent } });
  }
  const recentRunId = data.state && data.state.run_id ? String(data.state.run_id) : "";
  if (objectiveRunIdInput && !objectiveRunIdInput.value && recentRunId) objectiveRunIdInput.value = recentRunId;
  try {
    await refreshObjectiveCompiler();
  } catch (err) {
    if (objectiveActionStatus) objectiveActionStatus.textContent = `Objective state unavailable: ${err.message || err}`;
  }
}

async function saveSettings() {
  try {
    setDot(boStatusDot, "busy");
    boStatusLabel.textContent = "Saving";
    const data = await postJson("/api/bo/config", settingsPayload());
    boStatusLabel.textContent = data.ok ? "Settings saved" : "Save failed";
    boStatusDetail.textContent = data.ok ? `Saved to ${data.settings_path || "memory/bo_workspace_settings.json"}` : pretty(data);
    setDot(boStatusDot, data.ok ? "busy" : "warn");
  } catch (err) {
    boStatusLabel.textContent = "Save error";
    boStatusDetail.textContent = String(err);
    setDot(boStatusDot, "warn");
  }
}

async function runBenchmark() {
  try {
    setDot(boStatusDot, "busy");
    boStatusLabel.textContent = "Benchmarking";
    const data = await postJson("/api/bo/benchmark", settingsPayload());
    renderResult(data);
    boStatusLabel.textContent = data.ok ? "Benchmark complete" : "Benchmark failed";
    boStatusDetail.textContent = data.warnings && data.warnings.length ? data.warnings.join("; ") : "Virtual benchmark completed.";
    setDot(boStatusDot, data.ok ? "busy" : "warn");
  } catch (err) {
    boStatusLabel.textContent = "Error";
    boStatusDetail.textContent = String(err);
    setDot(boStatusDot, "warn");
  }
}

async function runBOAgent() {
  try {
    setDot(boStatusDot, "busy");
    boStatusLabel.textContent = "Running BO Agent";
    const data = await postJson("/api/bo/run", settingsPayload());
    renderResult(data);
    boStatusLabel.textContent = data.ok ? "BO Agent complete" : "BO Agent failed";
    boStatusDetail.textContent = data.summary || "BO Agent returned.";
    setDot(boStatusDot, data.ok ? "busy" : "warn");
  } catch (err) {
    boStatusLabel.textContent = "Error";
    boStatusDetail.textContent = String(err);
    setDot(boStatusDot, "warn");
  }
}

btnBenchmark.addEventListener("click", runBenchmark);
btnRun.addEventListener("click", runBOAgent);
btnSave.addEventListener("click", saveSettings);
btnReset.addEventListener("click", () => applyDefaults({ defaults }));
if (objectiveVersionSelect) objectiveVersionSelect.addEventListener("change", () => {
  const state = (objectiveRuntimeStatus.objective_states || []).find((item) => objectiveStateKey(item) === objectiveVersionSelect.value);
  renderSelectedObjective(state || null);
});
if (objectiveRunIdInput) objectiveRunIdInput.addEventListener("input", updateObjectiveButtons);
if (btnObjectiveCompose) btnObjectiveCompose.addEventListener("click", () => runObjectiveAction("Composing bounded objective", composeObjective));
if (btnObjectiveRevise) btnObjectiveRevise.addEventListener("click", () => runObjectiveAction("Revising objective version", reviseObjective));
if (btnObjectiveRefresh) btnObjectiveRefresh.addEventListener("click", () => runObjectiveAction("Refreshing objective state", async () => objectiveStateKey(selectedObjectiveState)));
if (btnObjectiveValidate) btnObjectiveValidate.addEventListener("click", () => runObjectiveAction("Validating objective contract", validateObjective));
if (btnObjectivePreview) btnObjectivePreview.addEventListener("click", () => runObjectiveAction("Evaluating preview observations", previewObjective));
if (btnObjectiveApprove) btnObjectiveApprove.addEventListener("click", () => runObjectiveAction("Recording operator approval", approveObjective));
if (btnObjectiveActivate) btnObjectiveActivate.addEventListener("click", () => runObjectiveAction("Binding objective to run", activateObjective));

loadConfig();
