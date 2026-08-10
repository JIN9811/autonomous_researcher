/* Shared BO objective and posterior renderer for /bo and Live GUI. */
(function attachBOVisualization(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.BOVisualization = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildBOVisualizationApi() {
  "use strict";

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);

  const finite = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  };

  const titleText = (value) => String(value || "")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

  const numberText = (value, digits = 4) => {
    const number = finite(value);
    return number === null ? "-" : String(Number(number.toFixed(digits)));
  };

  function validArrays(container, keys) {
    if (!container || typeof container !== "object") return false;
    const arrays = keys.map((key) => container[key]);
    if (!arrays.every(Array.isArray)) return false;
    const length = arrays[0].length;
    return arrays.every((items) => items.length === length && items.every((item) => finite(item) !== null));
  }

  function isValid(payload) {
    if (!payload || payload.schema !== "bo_visualization.v1") return false;
    return validArrays(payload.posterior, ["x", "mean", "std", "lower_95", "upper_95"])
      && validArrays(payload.acquisition, ["x", "value"])
      && payload.posterior.x.length === payload.acquisition.x.length
      && validArrays(payload.candidate_index_view, ["x", "mean", "std", "lower_95", "upper_95", "acquisition"]);
  }

  function availableParameters(payload) {
    const values = payload && payload.view && Array.isArray(payload.view.available_parameters)
      ? payload.view.available_parameters
      : [];
    return values.map(String).filter(Boolean);
  }

  function renderEquationCard(payload) {
    if (!payload || payload.schema !== "bo_visualization.v1") {
      return '<div class="bo-viz-empty">Objective not bound</div>';
    }
    const objective = payload.objective || {};
    const constraints = Array.isArray(objective.constraints) ? objective.constraints : [];
    const identity = objective.objective_id
      ? `${objective.objective_id}${Number(objective.version) ? ` · v${objective.version}` : ""}`
      : "Objective not bound";
    return `
      <div class="bo-viz-equation-head">
        <div>
          <span class="bo-viz-kicker">ACTIVE OBJECTIVE</span>
          <h4>${escapeHtml(objective.name || "Objective not bound")}</h4>
        </div>
        <span class="bo-viz-direction">${escapeHtml(String(objective.direction || "-").toUpperCase())}</span>
      </div>
      <div class="bo-viz-equation"><span>f(x) =</span><strong>${escapeHtml(objective.equation || "-")}</strong><em>${escapeHtml(objective.unit || "")}</em></div>
      ${constraints.length ? `<div class="bo-viz-constraints">${constraints.map((item) => `<code>${escapeHtml(item)}</code>`).join("")}</div>` : ""}
      <div class="bo-viz-equation-meta">
        <span>${escapeHtml(identity)}</span>
        <span>${objective.hash ? `hash ${escapeHtml(String(objective.hash).slice(0, 12))}` : "hash -"}</span>
        <span>${escapeHtml(objective.lifecycle || (objective.run_bound ? "run bound" : "read only"))}</span>
      </div>
    `;
  }

  function range(values, fallback = [0, 1]) {
    const numbers = values.map(finite).filter((value) => value !== null);
    if (!numbers.length) return fallback;
    let low = Math.min(...numbers);
    let high = Math.max(...numbers);
    if (low === high) {
      const pad = Math.max(Math.abs(low) * 0.08, 0.1);
      low -= pad;
      high += pad;
    }
    const pad = (high - low) * 0.08;
    return [low - pad, high + pad];
  }

  function scale(value, domain, output) {
    const span = domain[1] - domain[0] || 1;
    return output[0] + ((Number(value) - domain[0]) / span) * (output[1] - output[0]);
  }

  function points(rows) {
    return rows.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  }

  function plotData(payload, mode) {
    if (mode === "candidate_index") {
      const audit = payload.candidate_index_view;
      const ids = Array.isArray(audit.candidate_ids) ? audit.candidate_ids.map(String) : [];
      const idIndex = new Map(ids.map((id, index) => [id, Number(audit.x[index])]));
      const observations = (payload.observations || []).map((item) => ({
        ...item,
        x: idIndex.get(String(item.candidate_id || "")),
      })).filter((item) => finite(item.x) !== null && finite(item.score) !== null);
      const currentBest = payload.current_best && idIndex.has(String(payload.current_best.candidate_id || ""))
        ? { ...payload.current_best, x: idIndex.get(String(payload.current_best.candidate_id || "")) }
        : {};
      const nextPoint = payload.next_point && idIndex.has(String(payload.next_point.candidate_id || ""))
        ? { ...payload.next_point, x: idIndex.get(String(payload.next_point.candidate_id || "")) }
        : {};
      return {
        x: audit.x, mean: audit.mean, lower: audit.lower_95, upper: audit.upper_95,
        acquisition: audit.acquisition, observations, currentBest, nextPoint,
        candidateIds: ids, xLabel: "Candidate pool index", xUnit: "", mode,
      };
    }
    return {
      x: payload.posterior.x,
      mean: payload.posterior.mean,
      lower: payload.posterior.lower_95,
      upper: payload.posterior.upper_95,
      acquisition: payload.acquisition.value,
      observations: Array.isArray(payload.observations) ? payload.observations : [],
      currentBest: payload.current_best || {},
      nextPoint: payload.next_point || {},
      candidateIds: [],
      xLabel: payload.view.x_label || payload.view.selected_parameter || "Design parameter",
      xUnit: payload.view.x_unit && payload.view.x_unit !== "1" ? payload.view.x_unit : "",
      mode: "parameter_slice",
    };
  }

  function renderPlot(payload, options = {}) {
    if (!isValid(payload)) return '<div class="bo-viz-empty bo-viz-stale">BO visualization unavailable</div>';
    const mode = options.mode === "candidate_index" ? "candidate_index" : "parameter_slice";
    const data = plotData(payload, mode);
    if (!data.x.length) return '<div class="bo-viz-empty">Waiting for first BO observation</div>';

    const width = 960;
    const height = 610;
    const left = 82;
    const right = 34;
    const top = 72;
    const mainHeight = 300;
    const gap = 58;
    const acqTop = top + mainHeight + gap;
    const acqHeight = 110;
    const plotWidth = width - left - right;
    const xDomain = range(data.x);
    const yDomain = range([
      ...data.lower,
      ...data.upper,
      ...data.observations.map((item) => item.score),
    ]);
    const acqDomain = range([0, ...data.acquisition]);
    const xScale = (value) => scale(value, xDomain, [left, left + plotWidth]);
    const yScale = (value) => scale(value, yDomain, [top + mainHeight, top]);
    const acqScale = (value) => scale(value, acqDomain, [acqTop + acqHeight, acqTop]);
    const meanLine = data.x.map((x, index) => [xScale(x), yScale(data.mean[index])]);
    const acquisitionLine = data.x.map((x, index) => [xScale(x), acqScale(data.acquisition[index])]);
    const band = [
      ...data.x.map((x, index) => [xScale(x), yScale(data.upper[index])]),
      ...data.x.slice().reverse().map((x, reverseIndex) => {
        const index = data.x.length - reverseIndex - 1;
        return [xScale(x), yScale(data.lower[index])];
      }),
    ];
    const xTicks = Array.from({ length: 5 }, (_, index) => xDomain[0] + ((xDomain[1] - xDomain[0]) * index) / 4);
    const yTicks = Array.from({ length: 5 }, (_, index) => yDomain[0] + ((yDomain[1] - yDomain[0]) * index) / 4);
    const acqTicks = Array.from({ length: 3 }, (_, index) => acqDomain[0] + ((acqDomain[1] - acqDomain[0]) * index) / 2);
    const nextX = finite(data.nextPoint.x);
    const nextY = finite(data.nextPoint.mean);
    const bestX = finite(data.currentBest.x);
    const bestY = finite(data.currentBest.score);
    const acquisitionName = titleText(payload.acquisition.name || "acquisition");
    const warning = Array.isArray(payload.warnings) && payload.warnings.length ? payload.warnings[0] : "";

    return `
      <svg class="bo-viz-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Bayesian optimization posterior step ${escapeHtml(payload.step)}">
        <rect class="bo-viz-paper" x="0" y="0" width="${width}" height="${height}"></rect>
        <text class="bo-viz-title" x="${left}" y="31">Bayesian optimization posterior · step ${escapeHtml(payload.step)}</text>
        <text class="bo-viz-subtitle" x="${left}" y="52">${escapeHtml(data.xLabel)}${data.xUnit ? ` (${escapeHtml(data.xUnit)})` : ""} · ${escapeHtml(payload.backend.active || "backend")} / ${escapeHtml(payload.backend.model || "model")}</text>
        ${xTicks.map((tick) => `<line class="bo-viz-grid" x1="${xScale(tick)}" y1="${top}" x2="${xScale(tick)}" y2="${acqTop + acqHeight}"></line>`).join("")}
        ${yTicks.map((tick) => `<g><line class="bo-viz-grid" x1="${left}" y1="${yScale(tick)}" x2="${left + plotWidth}" y2="${yScale(tick)}"></line><text class="bo-viz-tick" x="${left - 12}" y="${yScale(tick) + 4}" text-anchor="end">${numberText(tick, 3)}</text></g>`).join("")}
        ${acqTicks.map((tick) => `<g><line class="bo-viz-grid" x1="${left}" y1="${acqScale(tick)}" x2="${left + plotWidth}" y2="${acqScale(tick)}"></line><text class="bo-viz-tick" x="${left - 12}" y="${acqScale(tick) + 4}" text-anchor="end">${numberText(tick, 3)}</text></g>`).join("")}
        <line class="bo-viz-axis" x1="${left}" y1="${top}" x2="${left}" y2="${top + mainHeight}"></line>
        <line class="bo-viz-axis" x1="${left}" y1="${top + mainHeight}" x2="${left + plotWidth}" y2="${top + mainHeight}"></line>
        <line class="bo-viz-axis" x1="${left}" y1="${acqTop}" x2="${left}" y2="${acqTop + acqHeight}"></line>
        <line class="bo-viz-axis" x1="${left}" y1="${acqTop + acqHeight}" x2="${left + plotWidth}" y2="${acqTop + acqHeight}"></line>
        <polygon class="bo-viz-confidence-band" points="${points(band)}"><title>95% confidence interval</title></polygon>
        <polyline class="bo-viz-mean-line" points="${points(meanLine)}"></polyline>
        <polyline class="bo-viz-acquisition-line" points="${points(acquisitionLine)}"></polyline>
        ${data.observations.map((item) => `<circle class="bo-viz-observation" cx="${xScale(item.x)}" cy="${yScale(item.score)}" r="6"><title>Measured observations · ${escapeHtml(item.candidate_id || "observation")} · ${numberText(item.score)}</title></circle>`).join("")}
        ${bestX !== null && bestY !== null ? `<circle class="bo-viz-best" cx="${xScale(bestX)}" cy="${yScale(bestY)}" r="8"><title>Current best · ${escapeHtml(data.currentBest.candidate_id || "best")}</title></circle>` : ""}
        ${nextX !== null ? `<line class="bo-viz-next-guide" x1="${xScale(nextX)}" y1="${top}" x2="${xScale(nextX)}" y2="${acqTop + acqHeight}"></line>${nextY !== null ? `<circle class="bo-viz-next" cx="${xScale(nextX)}" cy="${yScale(nextY)}" r="8"><title>Next point · ${escapeHtml(data.nextPoint.candidate_id || "selected")}</title></circle>` : ""}` : ""}
        ${xTicks.map((tick) => `<text class="bo-viz-tick" x="${xScale(tick)}" y="${acqTop + acqHeight + 22}" text-anchor="middle">${numberText(tick, mode === "candidate_index" ? 0 : 3)}</text>`).join("")}
        <text class="bo-viz-axis-label" x="18" y="${top + mainHeight / 2}" text-anchor="middle" transform="rotate(-90 18 ${top + mainHeight / 2})">Objective</text>
        <text class="bo-viz-axis-label" x="28" y="${acqTop + acqHeight / 2}" text-anchor="middle" transform="rotate(-90 28 ${acqTop + acqHeight / 2})">Acq.</text>
        <text class="bo-viz-axis-label" x="${left + plotWidth / 2}" y="${height - 24}" text-anchor="middle">${escapeHtml(data.xLabel)}${data.xUnit ? ` (${escapeHtml(data.xUnit)})` : ""}</text>
        <g class="bo-viz-legend" transform="translate(${left + plotWidth - 530}, 26)">
          <line class="bo-viz-mean-line" x1="0" y1="0" x2="28" y2="0"></line><text x="35" y="4">Posterior mean</text>
          <rect class="bo-viz-confidence-band" x="150" y="-8" width="28" height="12"></rect><text x="185" y="4">95% CI</text>
          <circle class="bo-viz-observation" cx="275" cy="0" r="5"></circle><text x="287" y="4">Measured observations</text>
          <circle class="bo-viz-next" cx="447" cy="0" r="5"></circle><text x="459" y="4">Next point</text>
        </g>
        <text class="bo-viz-acquisition-label" x="${left + 8}" y="${acqTop + 18}">${escapeHtml(acquisitionName)}</text>
        ${data.candidateIds.map((id, index) => `<title>${escapeHtml(id)} · x=${escapeHtml(data.x[index])}</title>`).join("")}
        ${warning ? `<text class="bo-viz-warning" x="${left + plotWidth}" y="${height - 5}" text-anchor="end">${escapeHtml(warning)}</text>` : ""}
      </svg>
    `;
  }

  function artifactLinks(payload) {
    const artifacts = payload && payload.artifacts && typeof payload.artifacts === "object" ? payload.artifacts : {};
    return ["png", "svg", "csv"].map((kind) => ({ kind, url: String(artifacts[`${kind}_url`] || "") })).filter((item) => item.url);
  }

  return { isValid, availableParameters, renderEquationCard, renderPlot, artifactLinks };
});
