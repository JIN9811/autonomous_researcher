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
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

  const numberText = (value, digits = 4) => {
    const number = finite(value);
    return number === null ? "-" : String(Number(number.toFixed(digits)));
  };

  const axisNumberText = (value, digits = 4) => {
    const number = finite(value);
    if (number === null) return "-";
    if (number !== 0 && Math.abs(number) < 1e-3) return number.toExponential(1);
    return numberText(number, digits);
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
    const designSpace = payload.design_space || {};
    const backend = payload.backend || {};
    const variables = Array.isArray(designSpace.variables) ? designSpace.variables.map(titleText).join(" × ") : "-";
    const cells = Array.isArray(designSpace.feasible_cell_sizes_mm) ? designSpace.feasible_cell_sizes_mm.join(", ") : "-";
    const density = Array.isArray(designSpace.relative_density_bounds) ? designSpace.relative_density_bounds.join("–") : "-";
    return `
      <div class="bo-viz-equation-head">
        <div>
          <span class="bo-viz-kicker">ACTIVE OBJECTIVE</span>
          <h4>${escapeHtml(objective.name || "Objective not bound")}</h4>
        </div>
        <span class="bo-viz-direction">${escapeHtml(String(objective.direction || "-").toUpperCase())}</span>
      </div>
      <div class="bo-viz-equation"><span>f(x) =</span><strong>${escapeHtml(objective.equation || "-")}</strong><em>${escapeHtml(objective.unit || "")}</em></div>
      <div class="bo-viz-contract" aria-label="BO design and model contract">
        <span><b>${escapeHtml(designSpace.dimension || 0)}D</b> ${escapeHtml(variables)}</span>
        <span><b>${escapeHtml(designSpace.cell_size_rule || "a=L/N")}</b> · a=[${escapeHtml(cells)}] mm</span>
        <span><b>Relative density</b> ${escapeHtml(density)}</span>
        <span><b>GP</b> ARD Matérn 5/2 + noise</span>
        <span><b>Acquisition</b> EI · ${escapeHtml(backend.input_normalization || "unit_hypercube")}</span>
      </div>
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

  function tickDigits(domain, tickCount) {
    const step = Math.abs(Number(domain[1]) - Number(domain[0])) / Math.max(1, Number(tickCount) - 1);
    if (!Number.isFinite(step) || step <= 0) return 3;
    return Math.max(3, Math.min(8, Math.ceil(-Math.log10(step)) + 1));
  }

  function points(rows) {
    return rows.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  }

  function plotData(payload, mode, parameter) {
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
    const selectedSlice = parameter && payload.parameter_slices && payload.parameter_slices[parameter]
      ? payload.parameter_slices[parameter]
      : null;
    const posterior = selectedSlice ? selectedSlice.posterior : payload.posterior;
    const acquisition = selectedSlice ? selectedSlice.acquisition : payload.acquisition;
    return {
      x: posterior.x,
      mean: posterior.mean,
      lower: posterior.lower_95,
      upper: posterior.upper_95,
      acquisition: acquisition.value,
      observations: Array.isArray(selectedSlice?.observations) ? selectedSlice.observations : (Array.isArray(payload.observations) ? payload.observations : []),
      currentBest: selectedSlice?.current_best || payload.current_best || {},
      nextPoint: selectedSlice?.next_point || payload.next_point || {},
      candidateIds: [],
      xLabel: selectedSlice?.x_label || payload.view.x_label || payload.view.selected_parameter || "Design parameter",
      xUnit: (selectedSlice?.x_unit || payload.view.x_unit) !== "1" ? (selectedSlice?.x_unit || payload.view.x_unit || "") : "",
      mode: "parameter_slice",
    };
  }

  function groupedSeries(payload) {
    const supplied = Array.isArray(payload.gp_series) ? payload.gp_series.filter((item) => (
      item && validArrays(item, ["x", "mean", "std", "lower_95", "upper_95", "acquisition"])
    )) : [];
    if (supplied.length) return supplied;
    const surface = payload.gp_surface || {};
    if (surface.mode !== "mixed_2d_gp_surface") return [];
    const fixedValues = Array.isArray(surface.x_values) ? surface.x_values : [];
    const varyingValues = Array.isArray(surface.y_values) ? surface.y_values : [];
    const matrixKeys = ["mean", "std", "lower_95", "upper_95", "acquisition"];
    if (!fixedValues.length || !varyingValues.length || !matrixKeys.every((key) => Array.isArray(surface[key]))) return [];
    const training = Array.isArray(payload.training_observations) ? payload.training_observations : [];
    const selectedParameters = payload.next_point?.parameters || {};
    const fixedLabel = String(surface.x_parameter || "parameter")
      .replace(/_mm$/, "")
      .replaceAll("_", " ")
      .replace(/^./, (char) => char.toUpperCase());
    return fixedValues.map((fixedValue, index) => {
      const rows = Object.fromEntries(matrixKeys.map((key) => [key, Array.isArray(surface[key][index]) ? surface[key][index] : []]));
      if (!matrixKeys.every((key) => rows[key].length === varyingValues.length)) return null;
      const observations = training.filter((item) => {
        const observed = finite(item?.parameters?.[surface.x_parameter]);
        return observed !== null && Math.abs(observed - Number(fixedValue)) <= 1e-8 && finite(item.score) !== null;
      }).map((item) => ({
        candidate_id: String(item.candidate_id || ""),
        x: finite(item.parameters?.[surface.y_parameter]),
        score: finite(item.score),
      })).filter((item) => item.x !== null);
      const selectedFixed = finite(selectedParameters[surface.x_parameter]);
      return {
        series_id: `${surface.x_parameter}=${numberText(fixedValue, 8)}`,
        label: `${fixedLabel} ${numberText(fixedValue, 8)}${String(surface.x_parameter).endsWith("_mm") ? " mm" : ""}`,
        fixed_parameters: { [surface.x_parameter]: fixedValue },
        x_parameter: surface.y_parameter,
        x_unit: String(surface.y_parameter).endsWith("_mm") ? "mm" : "1",
        x: varyingValues,
        ...rows,
        observations,
        selected_for_next_point: selectedFixed !== null && Math.abs(selectedFixed - Number(fixedValue)) <= 1e-8,
      };
    }).filter(Boolean);
  }

  function renderPlot(payload, options = {}) {
    if (!isValid(payload)) return '<div class="bo-viz-empty bo-viz-stale">BO visualization unavailable</div>';
    const backend = payload.backend || {};
    if (String(backend.active || "").toLowerCase() === "lhs" || String(backend.phase || "").toLowerCase() === "initial_design") {
      return '<div class="bo-viz-empty">BO posterior unavailable during initial design</div>';
    }
    if (payload.objective_trace?.mode === "normalized_search_path" || payload.gp_surface?.mode === "mixed_2d_gp_surface") {
      return renderObjectiveTrace(payload);
    }
    const mode = options.mode === "candidate_index" ? "candidate_index" : "parameter_slice";
    const data = plotData(payload, mode, options.parameter);
    if (!data.x.length) return '<div class="bo-viz-empty">Waiting for first BO observation</div>';

    const width = 960;
    const height = 500;
    const left = 82;
    const right = 34;
    const top = 110;
    const mainHeight = 280;
    const plotWidth = width - left - right;
    const xDomain = range(data.x);
    const yDomain = range([
      ...data.lower,
      ...data.upper,
      ...data.observations.map((item) => item.score),
    ]);
    const xScale = (value) => scale(value, xDomain, [left, left + plotWidth]);
    const yScale = (value) => scale(value, yDomain, [top + mainHeight, top]);
    const meanLine = data.x.map((x, index) => [xScale(x), yScale(data.mean[index])]);
    const band = [
      ...data.x.map((x, index) => [xScale(x), yScale(data.upper[index])]),
      ...data.x.slice().reverse().map((x, reverseIndex) => {
        const index = data.x.length - reverseIndex - 1;
        return [xScale(x), yScale(data.lower[index])];
      }),
    ];
    const xTicks = Array.from({ length: 5 }, (_, index) => xDomain[0] + ((xDomain[1] - xDomain[0]) * index) / 4);
    const yTicks = Array.from({ length: 5 }, (_, index) => yDomain[0] + ((yDomain[1] - yDomain[0]) * index) / 4);
    const yTickDigits = tickDigits(yDomain, yTicks.length);
    const nextX = finite(data.nextPoint.x);
    const nextY = finite(data.nextPoint.mean);
    const bestX = finite(data.currentBest.x);
    const bestY = finite(data.currentBest.score);
    const anchorCount = Number(payload.view?.anchor_count || 0);
    const projectionContext = payload.view?.mode === "marginal_projection" && anchorCount > 0
      ? ` · marginal over ${anchorCount} measured designs`
      : "";
    const warning = Array.isArray(payload.warnings) && payload.warnings.length ? payload.warnings[0] : "";

    return `
      <svg class="bo-viz-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Bayesian optimization posterior step ${escapeHtml(payload.step)}">
        <rect class="bo-viz-paper" x="0" y="0" width="${width}" height="${height}"></rect>
        <text class="bo-viz-title" x="${left}" y="31">Bayesian optimization posterior · step ${escapeHtml(payload.step)}</text>
        <text class="bo-viz-subtitle" x="${left}" y="52">${escapeHtml(data.xLabel)}${data.xUnit ? ` (${escapeHtml(data.xUnit)})` : ""} · ${escapeHtml(payload.backend.active || "backend")} / ${escapeHtml(payload.backend.model || "model")}${escapeHtml(projectionContext)}</text>
        ${xTicks.map((tick) => `<line class="bo-viz-grid" x1="${xScale(tick)}" y1="${top}" x2="${xScale(tick)}" y2="${top + mainHeight}"></line>`).join("")}
        ${yTicks.map((tick) => `<g><line class="bo-viz-grid" x1="${left}" y1="${yScale(tick)}" x2="${left + plotWidth}" y2="${yScale(tick)}"></line><text class="bo-viz-tick" x="${left - 12}" y="${yScale(tick) + 4}" text-anchor="end">${numberText(tick, yTickDigits)}</text></g>`).join("")}
        <line class="bo-viz-axis" x1="${left}" y1="${top}" x2="${left}" y2="${top + mainHeight}"></line>
        <line class="bo-viz-axis" x1="${left}" y1="${top + mainHeight}" x2="${left + plotWidth}" y2="${top + mainHeight}"></line>
        <polygon class="bo-viz-confidence-band" points="${points(band)}"><title>95% confidence interval</title></polygon>
        <polyline class="bo-viz-mean-line" points="${points(meanLine)}"></polyline>
        ${data.observations.map((item) => `<circle class="bo-viz-observation" cx="${xScale(item.x)}" cy="${yScale(item.score)}" r="6"><title>Measured observations · ${escapeHtml(item.candidate_id || "observation")} · ${numberText(item.score)}</title></circle>`).join("")}
        ${bestX !== null && bestY !== null ? `<circle class="bo-viz-best" cx="${xScale(bestX)}" cy="${yScale(bestY)}" r="8"><title>Current best · ${escapeHtml(data.currentBest.candidate_id || "best")}</title></circle>` : ""}
        ${nextX !== null ? `<line class="bo-viz-next-guide" x1="${xScale(nextX)}" y1="${top}" x2="${xScale(nextX)}" y2="${top + mainHeight}"></line>${nextY !== null ? `<g class="bo-viz-next-cross" transform="translate(${xScale(nextX)} ${yScale(nextY)})"><line x1="-7" y1="-7" x2="7" y2="7"></line><line x1="-7" y1="7" x2="7" y2="-7"></line><title>EI-selected next point · ${escapeHtml(data.nextPoint.candidate_id || "selected")}</title></g>` : ""}` : ""}
        ${xTicks.map((tick) => `<text class="bo-viz-tick" x="${xScale(tick)}" y="${top + mainHeight + 22}" text-anchor="middle">${numberText(tick, mode === "candidate_index" ? 0 : 3)}</text>`).join("")}
        <text class="bo-viz-axis-label" x="18" y="${top + mainHeight / 2}" text-anchor="middle" transform="rotate(-90 18 ${top + mainHeight / 2})">Objective</text>
        <text class="bo-viz-axis-label" x="${left + plotWidth / 2}" y="${height - 24}" text-anchor="middle">${escapeHtml(data.xLabel)}${data.xUnit ? ` (${escapeHtml(data.xUnit)})` : ""}</text>
        <g class="bo-viz-legend" transform="translate(${left}, 78)">
          <line class="bo-viz-mean-line" x1="0" y1="0" x2="28" y2="0"></line><text x="35" y="4">Posterior mean</text>
          <rect class="bo-viz-confidence-band" x="150" y="-8" width="28" height="12"></rect><text x="185" y="4">95% CI</text>
          <circle class="bo-viz-observation" cx="275" cy="0" r="5"></circle><text x="287" y="4">Measured observations</text>
          <g class="bo-viz-next-cross" transform="translate(447 0)"><line x1="-5" y1="-5" x2="5" y2="5"></line><line x1="-5" y1="5" x2="5" y2="-5"></line></g><text x="459" y="4">EI-selected Next point</text>
        </g>
        ${data.candidateIds.map((id, index) => `<title>${escapeHtml(id)} · x=${escapeHtml(data.x[index])}</title>`).join("")}
        ${warning ? `<text class="bo-viz-warning" x="${left + plotWidth}" y="${height - 5}" text-anchor="end">${escapeHtml(warning)}</text>` : ""}
      </svg>
    `;
  }

  function renderObjectiveTrace(payload) {
    const trace = payload.objective_trace?.mode === "normalized_search_path"
      && payload.objective_trace?.path_mode === "continuous_2d_gp_path"
      ? payload.objective_trace
      : objectiveTraceFromSurface(payload);
    const rows = (Array.isArray(trace.rows) ? trace.rows : [])
      .filter((row) => finite(row?.search_x) !== null && finite(row?.mean) !== null && finite(row?.std) !== null);
    if (rows.length < 2) return '<div class="bo-viz-empty">Waiting for BO objective observations</div>';
    const width = 960, height = 620, left = 86, right = 34, top = 102;
    const posteriorHeight = 291, gap = 62, acquisitionHeight = 112;
    const acquisitionTop = top + posteriorHeight + gap;
    const plotWidth = width - left - right;
    const xDomain = [0, 1];
    const evaluated = (Array.isArray(trace.observations) ? trace.observations : [])
      .filter((row) => finite(row?.search_x) !== null && finite(row?.observed) !== null);
    const threshold = finite(trace.improvement_threshold);
    const yDomain = range(rows.flatMap((row) => [
      Number(row.mean) - 3 * Number(row.std),
      Number(row.mean) + 3 * Number(row.std),
    ]).concat(evaluated.map((row) => Number(row.observed)), threshold === null ? [] : [threshold]));
    const next = trace.next_point && finite(trace.next_point.search_x) !== null ? trace.next_point : rows[rows.length - 1];
    const acquisitionDomain = range([
      0,
      ...rows.map((row) => Math.max(0, Number(row.acquisition || 0))),
      Math.max(0, Number(next.acquisition || 0)),
    ], [0, 1]);
    acquisitionDomain[0] = 0;
    const xScale = (value) => scale(value, xDomain, [left, left + plotWidth]);
    const yScale = (value) => scale(value, yDomain, [top + posteriorHeight, top]);
    const acquisitionScale = (value) => scale(value, acquisitionDomain, [acquisitionTop + acquisitionHeight, acquisitionTop]);
    const orderedRows = rows.slice().sort((a, b) => Number(a.search_x) - Number(b.search_x));
    const band = (segment, sigma) => points([
      ...segment.map((row) => [xScale(row.search_x), yScale(Number(row.mean) + sigma * Number(row.std))]),
      ...segment.slice().reverse().map((row) => [xScale(row.search_x), yScale(Number(row.mean) - sigma * Number(row.std))]),
    ]);
    const posteriorBand = (sigma, fill, opacity) => (
      `<polygon points="${band(orderedRows, sigma)}" fill="${fill}" fill-opacity="${opacity}"><title>BoTorch posterior mean ± ${sigma}σ</title></polygon>`
    );
    const posteriorLine = `<polyline class="bo-viz-gp-mean-grid" points="${points(orderedRows.map((row) => [xScale(row.search_x), yScale(row.mean)]))}" fill="none" stroke="#111827" stroke-width="2.7"><title>BoTorch GP posterior grid</title></polyline>`;
    const acquisitionLine = `<polyline class="bo-viz-ei-grid" points="${points(orderedRows.map((row) => [xScale(row.search_x), acquisitionScale(Math.max(0, Number(row.acquisition || 0)))]))}" fill="none" stroke="#15803d" stroke-width="2.7"><title>BoTorch Expected Improvement grid</title></polyline>`;
    const xTicks = Array.from({ length: 6 }, (_, index) => index / 5);
    const yTicks = Array.from({ length: 5 }, (_, index) => yDomain[0] + (yDomain[1] - yDomain[0]) * index / 4);
    const acquisitionTicks = Array.from({ length: 3 }, (_, index) => acquisitionDomain[0] + (acquisitionDomain[1] - acquisitionDomain[0]) * index / 2);
    return `<svg class="bo-viz-svg bo-viz-objective-trace" viewBox="0 0 ${width} ${height}" role="img" aria-label="BO objective posterior and expected improvement step ${escapeHtml(payload.step)}">
      <rect class="bo-viz-paper" width="${width}" height="${height}"></rect>
      <text class="bo-viz-title" x="${left}" y="29">BO objective posterior and expected improvement · step ${escapeHtml(payload.step)}</text>
      <text class="bo-viz-subtitle" x="${left}" y="50">Score posterior, predictive uncertainty, measured scores, and Expected Improvement</text>
      ${yTicks.map((tick) => `<g><line class="bo-viz-grid" x1="${left}" y1="${yScale(tick)}" x2="${left + plotWidth}" y2="${yScale(tick)}"></line><text class="bo-viz-tick" x="${left - 10}" y="${yScale(tick) + 4}" text-anchor="end">${numberText(tick, 6)}</text></g>`).join("")}
      ${posteriorBand(3, "#dbeafe", 0.55)}
      ${posteriorBand(2, "#93c5fd", 0.50)}
      ${posteriorBand(1, "#3b82f6", 0.42)}
      ${posteriorLine}
      ${threshold !== null ? `<g class="bo-viz-improvement-threshold"><line x1="${left}" y1="${yScale(threshold)}" x2="${left + plotWidth}" y2="${yScale(threshold)}" stroke="#f59e0b" stroke-width="1.7" stroke-dasharray="8 5"><title>Improvement threshold (best + ξ) · ${numberText(threshold, 7)}</title></line><text x="${left + plotWidth - 4}" y="${Math.max(top + 12, yScale(threshold) - 7)}" text-anchor="end" fill="#b45309" font-size="11" font-weight="600">Improvement threshold (best + ξ)</text></g>` : ""}
      ${evaluated.map((row) => `<circle cx="${xScale(row.search_x)}" cy="${yScale(row.observed)}" r="5.2" fill="#dc2626" stroke="#fff" stroke-width="1.3"><title>Measured score=${numberText(row.observed, 7)}</title></circle>`).join("")}
      <line class="bo-viz-axis" x1="${left}" y1="${top}" x2="${left}" y2="${top + posteriorHeight}"></line>
      <line class="bo-viz-axis" x1="${left}" y1="${top + posteriorHeight}" x2="${left + plotWidth}" y2="${top + posteriorHeight}"></line>
      <text class="bo-viz-axis-label" x="22" y="${top + posteriorHeight / 2}" text-anchor="middle" transform="rotate(-90 22 ${top + posteriorHeight / 2})">Score</text>
      ${acquisitionTicks.map((tick) => `<g><line class="bo-viz-grid" x1="${left}" y1="${acquisitionScale(tick)}" x2="${left + plotWidth}" y2="${acquisitionScale(tick)}"></line><text class="bo-viz-tick" x="${left - 10}" y="${acquisitionScale(tick) + 4}" text-anchor="end">${axisNumberText(tick, 5)}</text></g>`).join("")}
      ${acquisitionLine}
      <line class="bo-viz-axis" x1="${left}" y1="${acquisitionTop}" x2="${left}" y2="${acquisitionTop + acquisitionHeight}"></line>
      <line class="bo-viz-axis" x1="${left}" y1="${acquisitionTop + acquisitionHeight}" x2="${left + plotWidth}" y2="${acquisitionTop + acquisitionHeight}"></line>
      <text class="bo-viz-axis-label" x="28" y="${acquisitionTop + acquisitionHeight / 2}" text-anchor="middle" transform="rotate(-90 28 ${acquisitionTop + acquisitionHeight / 2})">Expected Improvement</text>
      <line x1="${xScale(next.search_x)}" y1="${top}" x2="${xScale(next.search_x)}" y2="${acquisitionTop + acquisitionHeight}" stroke="#2563eb" stroke-width="1.8" stroke-dasharray="9 5"><title>Next score query</title></line>
      <g class="bo-viz-next-star" transform="translate(${xScale(next.search_x)} ${acquisitionScale(Math.max(0, Number(next.acquisition || 0)))})"><path d="M0,-8 L2.4,-2.7 L8,-2.5 L3.7,1.2 L5.1,7 L0,4 L-5.1,7 L-3.7,1.2 L-8,-2.5 L-2.4,-2.7 Z" fill="#1d4ed8"><title>Maximum EI / next query</title></path></g>
      ${xTicks.map((tick) => `<text class="bo-viz-tick" x="${xScale(tick)}" y="${acquisitionTop + acquisitionHeight + 23}" text-anchor="middle">${numberText(tick, 1)}</text>`).join("")}
      <text class="bo-viz-axis-label" x="${left + plotWidth / 2}" y="${height - 17}" text-anchor="middle">Normalized BO search coordinate</text>
      <g class="bo-viz-legend" transform="translate(${left + 8} 76)"><line x1="0" y1="0" x2="26" y2="0" stroke="#111827" stroke-width="2.5"></line><text x="33" y="4">GP mean</text><circle cx="116" cy="0" r="4.5" fill="#dc2626"></circle><text x="126" y="4">Measured</text><rect x="204" y="-7" width="22" height="11" fill="#3b82f6" fill-opacity="0.42"></rect><text x="232" y="4">±1σ</text><rect x="278" y="-7" width="22" height="11" fill="#93c5fd" fill-opacity="0.5"></rect><text x="306" y="4">±2σ</text><rect x="352" y="-7" width="22" height="11" fill="#dbeafe" fill-opacity="0.7"></rect><text x="380" y="4">±3σ</text><line x1="426" y1="0" x2="452" y2="0" stroke="#f59e0b" stroke-width="1.7" stroke-dasharray="8 5"></line><text x="460" y="4">Improvement threshold (best + ξ)</text></g>
    </svg>`;
  }

  function objectiveTraceFromSurface(payload) {
    const surface = payload.gp_surface || {};
    const xValues = Array.isArray(surface.x_values) ? surface.x_values.map(Number) : [];
    const yValues = Array.isArray(surface.y_values) ? surface.y_values.map(Number) : [];
    if (!xValues.length || !yValues.length || !Array.isArray(surface.mean) || !Array.isArray(surface.std)) return [];
    const nearest = (values, target) => values.reduce((best, value, index) => (
      Math.abs(value - Number(target)) < Math.abs(values[best] - Number(target)) ? index : best
    ), 0);
    const xMin = Math.min(...xValues), xMax = Math.max(...xValues), xSpan = Math.max(1e-12, xMax - xMin);
    const yMin = Math.min(...yValues), yMax = Math.max(...yValues), ySpan = Math.max(1e-12, yMax - yMin);
    const normalizedVector = (parameters) => [
      Math.max(0, Math.min(1, (Number(parameters?.[surface.x_parameter]) - xMin) / xSpan)),
      Math.max(0, Math.min(1, (Number(parameters?.[surface.y_parameter]) - yMin) / ySpan)),
    ];
    const observationsInput = (payload.training_observations || []).filter((item) => (
      finite(item?.parameters?.[surface.x_parameter]) !== null
      && finite(item?.parameters?.[surface.y_parameter]) !== null
    ));
    const anchors = observationsInput.map((item, index) => ({ vector: normalizedVector(item.parameters), observationIndex: index }));
    const selectedParameters = payload.next_point?.parameters || {};
    const hasSelected = finite(selectedParameters[surface.x_parameter]) !== null
      && finite(selectedParameters[surface.y_parameter]) !== null;
    if (hasSelected) {
      const selectedVector = normalizedVector(selectedParameters);
      if (!anchors.some((item) => item.vector.every((value, index) => Math.abs(value - selectedVector[index]) < 1e-10))) {
        anchors.push({ vector: selectedVector, selected: true });
      } else {
        anchors.find((item) => item.vector.every((value, index) => Math.abs(value - selectedVector[index]) < 1e-10)).selected = true;
      }
    }
    if (anchors.length === 1) {
      const selectedVector = anchors[0].vector;
      anchors.unshift({ vector: selectedVector.map((value) => (value >= 0.5 ? 0 : 1)) });
    }
    if (anchors.length < 2) return [];

    const remaining = anchors.map((_, index) => index);
    remaining.sort((left, right) => anchors[left].vector[0] - anchors[right].vector[0] || anchors[left].vector[1] - anchors[right].vector[1]);
    const ordered = [remaining.shift()];
    while (remaining.length) {
      const previous = anchors[ordered[ordered.length - 1]].vector;
      remaining.sort((left, right) => {
        const leftDistance = anchors[left].vector.reduce((sum, value, index) => sum + (value - previous[index]) ** 2, 0);
        const rightDistance = anchors[right].vector.reduce((sum, value, index) => sum + (value - previous[index]) ** 2, 0);
        return leftDistance - rightDistance || anchors[left].vector[0] - anchors[right].vector[0] || anchors[left].vector[1] - anchors[right].vector[1];
      });
      ordered.push(remaining.shift());
    }
    const knots = ordered.map((index) => anchors[index].vector);
    const lengths = knots.slice(1).map((vector, index) => Math.max(1e-12, Math.hypot(vector[0] - knots[index][0], vector[1] - knots[index][1])));
    const coordinates = [0];
    lengths.forEach((length) => coordinates.push(coordinates[coordinates.length - 1] + length));
    const total = coordinates[coordinates.length - 1] || 1;
    coordinates.forEach((_, index) => { coordinates[index] /= total; });
    const slopes = knots.map(() => [0, 0]);
    const deltas = lengths.map((_, index) => [
      (knots[index + 1][0] - knots[index][0]) / Math.max(1e-12, coordinates[index + 1] - coordinates[index]),
      (knots[index + 1][1] - knots[index][1]) / Math.max(1e-12, coordinates[index + 1] - coordinates[index]),
    ]);
    slopes[0] = deltas[0].slice();
    slopes[slopes.length - 1] = deltas[deltas.length - 1].slice();
    for (let index = 1; index < slopes.length - 1; index += 1) {
      for (let dimension = 0; dimension < 2; dimension += 1) {
        const left = deltas[index - 1][dimension], right = deltas[index][dimension];
        slopes[index][dimension] = left * right > 0 ? (2 * left * right) / (left + right) : 0;
      }
    }
    const pathVector = (searchX) => {
      let segment = coordinates.length - 2;
      for (let index = 0; index < coordinates.length - 1; index += 1) {
        if (searchX <= coordinates[index + 1]) { segment = index; break; }
      }
      const span = Math.max(1e-12, coordinates[segment + 1] - coordinates[segment]);
      const u = Math.max(0, Math.min(1, (searchX - coordinates[segment]) / span));
      const u2 = u * u, u3 = u2 * u;
      return [0, 1].map((dimension) => Math.max(0, Math.min(1,
        (2 * u3 - 3 * u2 + 1) * knots[segment][dimension]
        + (u3 - 2 * u2 + u) * span * slopes[segment][dimension]
        + (-2 * u3 + 3 * u2) * knots[segment + 1][dimension]
        + (u3 - u2) * span * slopes[segment + 1][dimension]
      )));
    };
    const bracket = (values, target) => {
      if (target <= values[0]) return [0, 0, 0];
      if (target >= values[values.length - 1]) return [values.length - 1, values.length - 1, 0];
      let upper = 1;
      while (upper < values.length && values[upper] < target) upper += 1;
      const lower = upper - 1;
      return [lower, upper, (target - values[lower]) / Math.max(1e-12, values[upper] - values[lower])];
    };
    const interpolate = (matrix, vector) => {
      if (!Array.isArray(matrix)) return 0;
      const xValue = xMin + vector[0] * xSpan, yValue = yMin + vector[1] * ySpan;
      const [x0, x1, tx] = bracket(xValues, xValue), [y0, y1, ty] = bracket(yValues, yValue);
      const q00 = finite(matrix?.[x0]?.[y0]) ?? 0, q10 = finite(matrix?.[x1]?.[y0]) ?? q00;
      const q01 = finite(matrix?.[x0]?.[y1]) ?? q00, q11 = finite(matrix?.[x1]?.[y1]) ?? q10;
      return (1 - tx) * ((1 - ty) * q00 + ty * q01) + tx * ((1 - ty) * q10 + ty * q11);
    };
    const rows = Array.from({ length: 384 }, (_, index) => {
      const searchX = index / 383, vector = pathVector(searchX);
      return {
        search_x: searchX,
        normalized_vector: vector,
        mean: interpolate(surface.mean, vector),
        std: Math.max(0, interpolate(surface.std, vector)),
        acquisition: Math.max(0, interpolate(surface.acquisition, vector)),
      };
    });
    const coordinateByAnchor = new Map(ordered.map((anchorIndex, position) => [anchorIndex, coordinates[position]]));
    const observations = observationsInput.map((item, index) => ({
      search_x: coordinateByAnchor.get(anchors.findIndex((anchor) => anchor.observationIndex === index)),
      candidate_id: String(item.candidate_id || "evaluated"),
      parameters: item.parameters || {},
      observed: finite(item.score),
    }));
    const selectedAnchor = anchors.findIndex((anchor) => anchor.selected);
    const nextCoordinate = selectedAnchor >= 0 ? coordinateByAnchor.get(selectedAnchor) : 1;
    const nextVector = pathVector(nextCoordinate);
    const nextPoint = hasSelected ? {
      ...payload.next_point,
      search_x: nextCoordinate,
      mean: finite(payload.next_point.mean) ?? interpolate(surface.mean, nextVector),
      std: Math.max(0, finite(payload.next_point.std) ?? interpolate(surface.std, nextVector)),
      acquisition: Math.max(0, finite(payload.next_point.acquisition) ?? interpolate(surface.acquisition, nextVector)),
    } : {};
    const scores = observations.map((item) => finite(item.observed)).filter((value) => value !== null);
    const currentBest = scores.length
      ? (String(payload.objective?.direction || "maximize") === "minimize" ? Math.min(...scores) : Math.max(...scores))
      : null;
    const margin = 0.01;
    return {
      mode: "normalized_search_path",
      path_mode: "continuous_2d_gp_path",
      rows,
      observations,
      next_point: nextPoint,
      current_best: currentBest,
      exploration_margin: margin,
      improvement_threshold: currentBest === null ? null : currentBest + (String(payload.objective?.direction || "maximize") === "minimize" ? -margin : margin),
    };
  }

  function renderResponseSurface(payload) {
    const surface = payload.gp_surface || {};
    const x1 = Array.isArray(surface.x_values) ? surface.x_values.map(Number) : [];
    const x2 = Array.isArray(surface.y_values) ? surface.y_values.map(Number) : [];
    const mean = Array.isArray(surface.mean) ? surface.mean : [];
    const observations = Array.isArray(payload.training_observations) ? payload.training_observations : [];
    if (!x1.length || !x2.length || mean.length !== x1.length) return '<div class="bo-viz-empty">GP response surface unavailable</div>';
    const values = mean.flat().map(Number).filter(Number.isFinite);
    const zDomain = range(values, [0, 1]);
    const width = 960, height = 590, left = 96, right = 132, top = 88, bottom = 74;
    const plotWidth = width - left - right, plotHeight = height - top - bottom;
    const xDomain = range(x2);
    const cellW = plotWidth / Math.max(1, x2.length);
    const cellH = plotHeight / Math.max(1, x1.length);
    const xScale = (v) => scale(v, xDomain, [left + cellW / 2, left + plotWidth - cellW / 2]);
    const yScale = (v) => {
      let nearest = 0;
      for (let index = 1; index < x1.length; index += 1) {
        if (Math.abs(x1[index] - v) < Math.abs(x1[nearest] - v)) nearest = index;
      }
      return top + plotHeight - (nearest + 0.5) * cellH;
    };
    const color = (value) => {
      const t = Math.max(0, Math.min(1, (Number(value) - zDomain[0]) / Math.max(1e-12, zDomain[1] - zDomain[0])));
      const stops = [[35,55,130],[31,126,180],[45,174,146],[253,196,70],[215,48,39]];
      const p = t * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(p)), q = p - i;
      return `rgb(${stops[i].map((v, k) => Math.round(v + (stops[i + 1][k] - v) * q)).join(',')})`;
    };
    const cells = mean.map((row, i) => row.map((z, j) => {
      const x = left + j * cellW;
      const y = top + plotHeight - (i + 1) * cellH;
      return `<rect x="${x}" y="${y}" width="${cellW + 0.8}" height="${cellH + 0.8}" fill="${color(z)}"><title>f(x1=${numberText(x1[i])}, x2=${numberText(x2[j])}) = ${numberText(z, 6)}</title></rect>`;
    }).join('')).join('');
    const measured = observations.map((item) => {
      const p = item.parameters || {}, a = finite(p[surface.x_parameter]), b = finite(p[surface.y_parameter]), z = finite(item.score);
      if (a === null || b === null || z === null) return '';
      return `<g transform="translate(${xScale(b)} ${yScale(a)})"><circle r="6" fill="#fff" stroke="#111827" stroke-width="2"></circle><title>${escapeHtml(item.candidate_id || 'measured')} · measured f=${numberText(z, 6)}</title></g>`;
    }).join('');
    const next = payload.next_point?.parameters || {}, nx = finite(next[surface.y_parameter]), ny = finite(next[surface.x_parameter]);
    const nextMarker = nx === null || ny === null ? '' : `<g class="bo-viz-next-cross" transform="translate(${xScale(nx)} ${yScale(ny)})"><line x1="-9" y1="-9" x2="9" y2="9"></line><line x1="-9" y1="9" x2="9" y2="-9"></line><title>EI-selected next input</title></g>`;
    const xTicks = Array.from({length:5}, (_,i)=>xDomain[0]+(xDomain[1]-xDomain[0])*i/4);
    const bar = Array.from({length:80}, (_,i)=>`<rect x="${width-right+34}" y="${top+i*plotHeight/80}" width="22" height="${plotHeight/80+0.5}" fill="${color(zDomain[1]-(zDomain[1]-zDomain[0])*i/79)}"></rect>`).join('');
    return `<svg class="bo-viz-svg bo-viz-response-surface" viewBox="0 0 ${width} ${height}" role="img" aria-label="GP objective response surface step ${escapeHtml(payload.step)}">
      <rect class="bo-viz-paper" width="${width}" height="${height}"></rect>
      <text class="bo-viz-title" x="${left}" y="30">Surrogate objective function · step ${escapeHtml(payload.step)}</text>
      <text class="bo-viz-subtitle" x="${left}" y="52">Inputs (x1, x2) → predicted objective f(x1, x2) = ${escapeHtml(payload.objective?.equation || 'objective_score')}</text>
      ${cells}${measured}${nextMarker}
      <rect x="${left}" y="${top}" width="${plotWidth}" height="${plotHeight}" fill="none" stroke="#111827" stroke-width="1.2"></rect>
      ${xTicks.map(t=>`<text class="bo-viz-tick" x="${xScale(t)}" y="${top+plotHeight+24}" text-anchor="middle">${numberText(t,3)}</text>`).join('')}
      ${x1.map(v=>`<text class="bo-viz-tick" x="${left-12}" y="${yScale(v)+4}" text-anchor="end">${numberText(v,4)}</text>`).join('')}
      <text class="bo-viz-axis-label" x="${left+plotWidth/2}" y="${height-22}" text-anchor="middle">x2 · ${escapeHtml(titleText(surface.y_parameter || 'input 2'))}</text>
      <text class="bo-viz-axis-label" x="24" y="${top+plotHeight/2}" text-anchor="middle" transform="rotate(-90 24 ${top+plotHeight/2})">x1 · ${escapeHtml(titleText(surface.x_parameter || 'input 1'))}</text>
      ${bar}<text class="bo-viz-axis-label" x="${width-right+45}" y="${top-14}" text-anchor="middle">f(x1,x2)</text>
      <text class="bo-viz-tick" x="${width-right+64}" y="${top+5}">${numberText(zDomain[1],6)}</text><text class="bo-viz-tick" x="${width-right+64}" y="${top+plotHeight}">${numberText(zDomain[0],6)}</text>
      <g transform="translate(${left} 72)"><circle r="5" fill="#fff" stroke="#111827" stroke-width="2"></circle><text x="12" y="4">Measured f</text><g class="bo-viz-next-cross" transform="translate(116 0)"><line x1="-6" y1="-6" x2="6" y2="6"></line><line x1="-6" y1="6" x2="6" y2="-6"></line></g><text x="130" y="4">EI-selected next input</text></g>
    </svg>`;
  }

  function renderGroupedGpPlot(payload, seriesRows) {
    const colors = ["#2563eb", "#0891b2", "#16a34a", "#7c3aed", "#dc2626", "#ca8a04"];
    const width = 960;
    const height = 620;
    const left = 82;
    const right = 34;
    const top = 116;
    const posteriorHeight = 270;
    const gap = 64;
    const acqTop = top + posteriorHeight + gap;
    const acqHeight = 105;
    const plotWidth = width - left - right;
    const allX = seriesRows.flatMap((item) => item.x);
    const observations = seriesRows.flatMap((item) => Array.isArray(item.observations) ? item.observations : []);
    const xDomain = range(allX);
    const yDomain = range([
      ...seriesRows.flatMap((item) => item.lower_95),
      ...seriesRows.flatMap((item) => item.upper_95),
      ...observations.map((item) => item.score),
    ]);
    const acqDomain = range([0, ...seriesRows.flatMap((item) => item.acquisition)], [0, 1]);
    if (acqDomain[0] < 0) acqDomain[0] = 0;
    const xScale = (value) => scale(value, xDomain, [left, left + plotWidth]);
    const yScale = (value) => scale(value, yDomain, [top + posteriorHeight, top]);
    const acqScale = (value) => scale(value, acqDomain, [acqTop + acqHeight, acqTop]);
    const xTicks = Array.from({ length: 5 }, (_, index) => xDomain[0] + ((xDomain[1] - xDomain[0]) * index) / 4);
    const yTicks = Array.from({ length: 5 }, (_, index) => yDomain[0] + ((yDomain[1] - yDomain[0]) * index) / 4);
    const acqTicks = Array.from({ length: 3 }, (_, index) => acqDomain[0] + ((acqDomain[1] - acqDomain[0]) * index) / 2);
    const xLabel = titleText(seriesRows[0].x_parameter || payload.view?.selected_parameter || "Design parameter");
    const xUnit = seriesRows[0].x_unit && seriesRows[0].x_unit !== "1" ? ` (${seriesRows[0].x_unit})` : "";
    const selected = payload.next_point || {};
    const selectedParameters = selected.parameters || {};
    const selectedX = finite(selectedParameters[seriesRows[0].x_parameter] ?? selected.x);
    const selectedMean = finite(selected.mean);
    const selectedSeries = seriesRows.find((item) => item.selected_for_next_point) || null;

    const plots = seriesRows.map((item, index) => {
      const color = colors[index % colors.length];
      const meanLine = item.x.map((x, pointIndex) => [xScale(x), yScale(item.mean[pointIndex])]);
      const acquisitionLine = item.x.map((x, pointIndex) => [xScale(x), acqScale(item.acquisition[pointIndex])]);
      const band = [
        ...item.x.map((x, pointIndex) => [xScale(x), yScale(item.upper_95[pointIndex])]),
        ...item.x.slice().reverse().map((x, reverseIndex) => {
          const pointIndex = item.x.length - reverseIndex - 1;
          return [xScale(x), yScale(item.lower_95[pointIndex])];
        }),
      ];
      const measured = (item.observations || []).map((observation) => `
        <circle class="bo-viz-observation bo-viz-series-observation" style="fill:${color}" cx="${xScale(observation.x)}" cy="${yScale(observation.score)}" r="5">
          <title>${escapeHtml(item.label)} · ${escapeHtml(observation.candidate_id || "observation")} · ${numberText(observation.score)}</title>
        </circle>`).join("");
      return `
        <polygon class="bo-viz-confidence-band" style="fill:${color};fill-opacity:0.11" points="${points(band)}"><title>${escapeHtml(item.label)} · 95% CI</title></polygon>
        <polyline class="bo-viz-mean-line" style="stroke:${color}" points="${points(meanLine)}"><title>${escapeHtml(item.label)} · posterior mean</title></polyline>
        <polyline class="bo-viz-acquisition-line" style="stroke:${color}" points="${points(acquisitionLine)}"><title>${escapeHtml(item.label)} · Expected Improvement</title></polyline>
        ${measured}`;
    }).join("");
    const legend = seriesRows.map((item, index) => {
      const column = index % 4;
      const row = Math.floor(index / 4);
      const color = colors[index % colors.length];
      return `<g transform="translate(${column * 200} ${row * 19})"><line x1="0" y1="0" x2="25" y2="0" style="stroke:${color};stroke-width:3"></line><text x="32" y="4">${escapeHtml(item.label)}</text></g>`;
    }).join("");
    const selectedMarker = selectedSeries && selectedX !== null && selectedMean !== null
      ? `<line class="bo-viz-next-guide" x1="${xScale(selectedX)}" y1="${top}" x2="${xScale(selectedX)}" y2="${acqTop + acqHeight}"></line><g class="bo-viz-next-cross" transform="translate(${xScale(selectedX)} ${yScale(selectedMean)})"><line x1="-7" y1="-7" x2="7" y2="7"></line><line x1="-7" y1="7" x2="7" y2="-7"></line><title>EI-selected next point · ${escapeHtml(selected.candidate_id || "selected")}</title></g>`
      : "";
    return `
      <svg class="bo-viz-svg bo-viz-grouped-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Grouped Bayesian optimization posterior step ${escapeHtml(payload.step)}">
        <rect class="bo-viz-paper" x="0" y="0" width="${width}" height="${height}"></rect>
        <text class="bo-viz-title" x="${left}" y="30">Bayesian optimization posterior · step ${escapeHtml(payload.step)}</text>
        <text class="bo-viz-subtitle" x="${left}" y="51">LHS-seeded 2D GP · grouped GP from ${seriesRows.length} measured-design strata · ${escapeHtml(payload.backend?.model || "SingleTaskGP")}</text>
        <g class="bo-viz-legend" transform="translate(${left} 78)">${legend}</g>
        <g class="bo-viz-legend" transform="translate(${left + plotWidth - 405} 31)"><text x="0" y="0">Posterior mean · 95% CI · Measured observations · EI-selected Next point</text></g>
        ${xTicks.map((tick) => `<line class="bo-viz-grid" x1="${xScale(tick)}" y1="${top}" x2="${xScale(tick)}" y2="${acqTop + acqHeight}"></line>`).join("")}
        ${yTicks.map((tick) => `<g><line class="bo-viz-grid" x1="${left}" y1="${yScale(tick)}" x2="${left + plotWidth}" y2="${yScale(tick)}"></line><text class="bo-viz-tick" x="${left - 12}" y="${yScale(tick) + 4}" text-anchor="end">${numberText(tick, tickDigits(yDomain, yTicks.length))}</text></g>`).join("")}
        ${acqTicks.map((tick) => `<g><line class="bo-viz-grid" x1="${left}" y1="${acqScale(tick)}" x2="${left + plotWidth}" y2="${acqScale(tick)}"></line><text class="bo-viz-tick" x="${left - 12}" y="${acqScale(tick) + 4}" text-anchor="end">${numberText(tick, tickDigits(acqDomain, acqTicks.length))}</text></g>`).join("")}
        <line class="bo-viz-axis" x1="${left}" y1="${top}" x2="${left}" y2="${top + posteriorHeight}"></line>
        <line class="bo-viz-axis" x1="${left}" y1="${top + posteriorHeight}" x2="${left + plotWidth}" y2="${top + posteriorHeight}"></line>
        <line class="bo-viz-axis" x1="${left}" y1="${acqTop}" x2="${left}" y2="${acqTop + acqHeight}"></line>
        <line class="bo-viz-axis" x1="${left}" y1="${acqTop + acqHeight}" x2="${left + plotWidth}" y2="${acqTop + acqHeight}"></line>
        ${plots}${selectedMarker}
        ${xTicks.map((tick) => `<text class="bo-viz-tick" x="${xScale(tick)}" y="${acqTop + acqHeight + 22}" text-anchor="middle">${numberText(tick, 3)}</text>`).join("")}
        <text class="bo-viz-axis-label" x="18" y="${top + posteriorHeight / 2}" text-anchor="middle" transform="rotate(-90 18 ${top + posteriorHeight / 2})">Objective</text>
        <text class="bo-viz-axis-label" x="28" y="${acqTop + acqHeight / 2}" text-anchor="middle" transform="rotate(-90 28 ${acqTop + acqHeight / 2})">Expected Improvement</text>
        <text class="bo-viz-axis-label" x="${left + plotWidth / 2}" y="${height - 22}" text-anchor="middle">${escapeHtml(xLabel)}${escapeHtml(xUnit)}</text>
      </svg>`;
  }

  function artifactLinks(payload) {
    const artifacts = payload && payload.artifacts && typeof payload.artifacts === "object" ? payload.artifacts : {};
    return ["png", "svg", "csv"].map((kind) => ({ kind, url: String(artifacts[`${kind}_url`] || "") })).filter((item) => item.url);
  }

  return {
    isValid,
    availableParameters,
    renderEquationCard,
    renderPlot,
    artifactLinks,
  };
});
