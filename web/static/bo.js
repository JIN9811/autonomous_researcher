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
const acquisitionInput = document.getElementById("bo-acquisition-input");
const budgetInput = document.getElementById("bo-budget-input");
const seedInput = document.getElementById("bo-seed-input");
const kappaInput = document.getElementById("bo-kappa-input");
const xiInput = document.getElementById("bo-xi-input");
const explorationInput = document.getElementById("bo-exploration-input");
const exploitationInput = document.getElementById("bo-exploitation-input");
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
const resultJson = document.getElementById("bo-result-json");

let defaults = {};

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
  return await res.json();
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
    acquisition: acquisitionInput.value,
    budget: Number(budgetInput.value || 1),
    random_seed: Number(seedInput.value || 7),
    kappa: Number(kappaInput.value || 2.0),
    xi: Number(xiInput.value || 0.01),
    exploration_weight: Number(explorationInput.value || 0.35),
    exploitation_weight: Number(exploitationInput.value || 0.65),
    objective: parseJsonField(objectiveInput, {}),
    parameter_space: parseJsonField(parameterSpaceInput, defaults.parameter_space || {}),
    mode: "test",
  };
}

function applyDefaults(data) {
  defaults = data.defaults || {};
  strategyInput.value = defaults.strategy || "bo";
  acquisitionInput.value = defaults.acquisition || "expected_improvement";
  budgetInput.value = defaults.budget || 8;
  seedInput.value = defaults.random_seed || 7;
  kappaInput.value = defaults.kappa || 2.0;
  xiInput.value = defaults.xi || 0.01;
  explorationInput.value = defaults.exploration_weight || 0.35;
  exploitationInput.value = defaults.exploitation_weight || 0.65;
  parameterSpaceInput.value = pretty(defaults.parameter_space || {});
  objectiveInput.value = pretty({
    objective_id: "bo-workspace-objective",
    name: "Specimen printability and performance proxy",
    metric_name: "objective_score",
    direction: "maximize",
    tags: ["bo", "workspace", "tpms"],
  });
}

function applySettings(settings) {
  if (!settings || typeof settings !== "object") return;
  if (settings.strategy) strategyInput.value = settings.strategy;
  if (settings.acquisition) acquisitionInput.value = settings.acquisition;
  if (settings.budget !== undefined) budgetInput.value = settings.budget;
  if (settings.random_seed !== undefined) seedInput.value = settings.random_seed;
  if (settings.kappa !== undefined) kappaInput.value = settings.kappa;
  if (settings.xi !== undefined) xiInput.value = settings.xi;
  if (settings.exploration_weight !== undefined) explorationInput.value = settings.exploration_weight;
  if (settings.exploitation_weight !== undefined) exploitationInput.value = settings.exploitation_weight;
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

function renderResult(data) {
  const boResult = data?.data?.bo_result || data?.bo_result || null;
  const benchmark = boResult ? boResult.benchmark : data.benchmark;
  const recommendation = boResult ? boResult.recommendation || {} : {};
  const score = recommendation.objective_score ?? (benchmark?.strategies ? Object.values(benchmark.strategies)[0]?.best_score : "n/a");
  recommendationLabel.textContent = recommendation.candidate_id || "benchmark only";
  bestScoreLabel.textContent = score ?? "n/a";
  renderCurve(boResult ? boResult.best_so_far || [] : firstCurveFromBenchmark(benchmark));
  renderSurrogateTrace(benchmark);
  resultJson.textContent = pretty(data);
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

loadConfig();
