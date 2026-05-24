/*
File purpose:
- Frontend runtime for CAE Analysis Workspace controls.

Key classes/functions:
- loadConfig
- runCAEAnalysis

Inputs/outputs:
- Input: operator CAE settings
- Output: CAE metrics and raw result panels

Dependencies:
- /api/cae/config
- /api/cae/run
*/

const caeStatusDot = document.getElementById("cae-status-dot");
const caeStatusLabel = document.getElementById("cae-status-label");
const caeStatusDetail = document.getElementById("cae-status-detail");
const modeInput = document.getElementById("cae-mode-input");
const solverInput = document.getElementById("cae-solver-input");
const mesherInput = document.getElementById("cae-mesher-input");
const specimenIdInput = document.getElementById("cae-specimen-id-input");
const stlPathInput = document.getElementById("cae-stl-path-input");
const meshSizeInput = document.getElementById("cae-mesh-size-input");
const sizeXInput = document.getElementById("cae-size-x-input");
const sizeYInput = document.getElementById("cae-size-y-input");
const sizeZInput = document.getElementById("cae-size-z-input");
const elasticInput = document.getElementById("cae-elastic-input");
const poissonInput = document.getElementById("cae-poisson-input");
const yieldInput = document.getElementById("cae-yield-input");
const loadMaxInput = document.getElementById("cae-load-max-input");
const loadRatioInput = document.getElementById("cae-load-ratio-input");
const cyclesInput = document.getElementById("cae-cycles-input");
const frequencyInput = document.getElementById("cae-frequency-input");
const requireSolverInput = document.getElementById("cae-require-solver-input");
const btnHealth = document.getElementById("btn-cae-health");
const btnRun = document.getElementById("btn-cae-run");
const btnSave = document.getElementById("btn-cae-save");
const btnReset = document.getElementById("btn-cae-reset");
const stressLabel = document.getElementById("cae-stress-label");
const displacementLabel = document.getElementById("cae-displacement-label");
const fatigueLabel = document.getElementById("cae-fatigue-label");
const scoreLabel = document.getElementById("cae-score-label");
const stepTraceEl = document.getElementById("cae-step-trace");
const resultJsonEl = document.getElementById("cae-result-json");

let defaults = {};

function setDot(el, state) {
  if (!el) return;
  el.className = `status-dot ${state}`;
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return await res.json();
}

function metricText(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "n/a";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return `${value}${suffix}`;
  return `${parsed.toPrecision(5)}${suffix}`;
}

function payload() {
  return {
    mode: modeInput.value || "test",
    solver: solverInput.value || "calculix",
    mesher: mesherInput.value || "gmsh",
    specimen_id: specimenIdInput.value || "manual-specimen",
    stl_path: stlPathInput.value || "",
    specimen_size_mm: [
      Number(sizeXInput.value || 20),
      Number(sizeYInput.value || 20),
      Number(sizeZInput.value || 20),
    ],
    mesh_size_mm: Number(meshSizeInput.value || 2),
    elastic_modulus_mpa: Number(elasticInput.value || 1800),
    poisson_ratio: Number(poissonInput.value || 0.35),
    yield_strength_mpa: Number(yieldInput.value || 35),
    load_max_n: Number(loadMaxInput.value || 500),
    load_min_ratio: Number(loadRatioInput.value || 0.1),
    cycles: Number(cyclesInput.value || 10),
    frequency_hz: Number(frequencyInput.value || 1),
    require_solver: Boolean(requireSolverInput.checked),
  };
}

function applyDefaults(data) {
  defaults = data.defaults || {};
  const material = defaults.material || {};
  const loading = defaults.loading || {};
  const size = defaults.specimen_size_mm || [20, 20, 20];
  const health = data.health || {};
  solverInput.value = defaults.solver || "calculix";
  mesherInput.value = defaults.mesher || "gmsh";
  sizeXInput.value = size[0] || 20;
  sizeYInput.value = size[1] || 20;
  sizeZInput.value = size[2] || 20;
  meshSizeInput.value = defaults.mesh_size_mm || 2;
  elasticInput.value = material.elastic_modulus_mpa || 1800;
  poissonInput.value = material.poisson_ratio || 0.35;
  yieldInput.value = material.yield_strength_mpa || 35;
  loadMaxInput.value = loading.load_max_n || 500;
  loadRatioInput.value = loading.load_min_ratio || 0.1;
  cyclesInput.value = loading.cycles || 10;
  frequencyInput.value = loading.frequency_hz || 1;
  if (Object.prototype.hasOwnProperty.call(health, "require_solver_in_live")) {
    requireSolverInput.checked = Boolean(health.require_solver_in_live);
  }
}

function applySettings(settings) {
  if (!settings || typeof settings !== "object") return;
  if (settings.mode) modeInput.value = settings.mode;
  if (settings.solver) solverInput.value = settings.solver;
  if (settings.mesher) mesherInput.value = settings.mesher;
  if (settings.specimen_id) specimenIdInput.value = settings.specimen_id;
  if (settings.stl_path !== undefined) stlPathInput.value = settings.stl_path || "";
  if (settings.mesh_size_mm !== undefined) meshSizeInput.value = settings.mesh_size_mm;
  const size = Array.isArray(settings.specimen_size_mm) ? settings.specimen_size_mm : null;
  if (size && size.length >= 3) {
    sizeXInput.value = size[0];
    sizeYInput.value = size[1];
    sizeZInput.value = size[2];
  }
  if (settings.elastic_modulus_mpa !== undefined) elasticInput.value = settings.elastic_modulus_mpa;
  if (settings.poisson_ratio !== undefined) poissonInput.value = settings.poisson_ratio;
  if (settings.yield_strength_mpa !== undefined) yieldInput.value = settings.yield_strength_mpa;
  if (settings.load_max_n !== undefined) loadMaxInput.value = settings.load_max_n;
  if (settings.load_min_ratio !== undefined) loadRatioInput.value = settings.load_min_ratio;
  if (settings.cycles !== undefined) cyclesInput.value = settings.cycles;
  if (settings.frequency_hz !== undefined) frequencyInput.value = settings.frequency_hz;
  if (settings.require_solver !== undefined) requireSolverInput.checked = Boolean(settings.require_solver);
}

function renderTrace(trace) {
  const items = Array.isArray(trace) ? trace : [];
  if (!items.length) {
    stepTraceEl.textContent = "No step trace.";
    return;
  }
  stepTraceEl.innerHTML = items
    .map((item) => {
      const step = item.step || "";
      const status = item.status || "";
      const detail = item.detail || "";
      return `<div class="log-line"><strong>${step}</strong> ${status} · ${detail}</div>`;
    })
    .join("");
}

function renderResult(data) {
  const result = data.result || data.recent || data || {};
  const metrics = result.cae_metrics || result.metrics || {};
  stressLabel.textContent = metricText(metrics.max_von_mises_MPa, " MPa");
  displacementLabel.textContent = metricText(metrics.max_displacement_mm, " mm");
  fatigueLabel.textContent = metricText(metrics.fatigue_damage_proxy);
  scoreLabel.textContent = metricText(metrics.structural_score);
  renderTrace(result.step_trace || []);
  resultJsonEl.textContent = pretty(result);
}

async function loadConfig() {
  setDot(caeStatusDot, "idle");
  caeStatusLabel.textContent = "Loading";
  caeStatusDetail.textContent = "Reading CAE bridge status.";
  const res = await fetch("/api/cae/config");
  const data = await res.json();
  applyDefaults(data);
  applySettings(data.saved || {});
  const health = data.health || {};
  const solver = health.calculix || {};
  const mesher = health.gmsh || {};
  setDot(caeStatusDot, data.ok ? "busy" : "warn");
  caeStatusLabel.textContent = data.ok ? "Ready" : "Unavailable";
  const savedNote = data.saved && Object.keys(data.saved).length ? ` · saved=${data.settings_path || "memory"}` : "";
  caeStatusDetail.textContent = `CalculiX=${Boolean(solver.available)} · Gmsh=${Boolean(mesher.available)} · bottom fixed / top cyclic${savedNote}`;
  if (data.recent && Object.keys(data.recent).length) {
    renderResult({ result: data.recent });
  }
}

async function saveSettings() {
  try {
    setDot(caeStatusDot, "busy");
    caeStatusLabel.textContent = "Saving";
    const data = await postJson("/api/cae/config", payload());
    caeStatusLabel.textContent = data.ok ? "Settings saved" : "Save failed";
    caeStatusDetail.textContent = data.ok ? `Saved to ${data.settings_path || "memory/cae_workspace_settings.json"}` : pretty(data);
    setDot(caeStatusDot, data.ok ? "busy" : "warn");
  } catch (err) {
    caeStatusLabel.textContent = "Save error";
    caeStatusDetail.textContent = String(err);
    setDot(caeStatusDot, "warn");
  }
}

async function runCAEAnalysis() {
  try {
    setDot(caeStatusDot, "busy");
    caeStatusLabel.textContent = "Running CAE";
    const data = await postJson("/api/cae/run", payload());
    renderResult(data);
    caeStatusLabel.textContent = data.ok ? "CAE complete" : "CAE blocked";
    const result = data.result || {};
    caeStatusDetail.textContent = result.message || `${result.solver_mode || "analysis"} · ${result.status || "done"}`;
    setDot(caeStatusDot, data.ok ? "busy" : "warn");
  } catch (err) {
    caeStatusLabel.textContent = "Error";
    caeStatusDetail.textContent = String(err);
    setDot(caeStatusDot, "warn");
  }
}

btnHealth.addEventListener("click", loadConfig);
btnRun.addEventListener("click", runCAEAnalysis);
btnSave.addEventListener("click", saveSettings);
btnReset.addEventListener("click", () => applyDefaults({ defaults }));

loadConfig();
