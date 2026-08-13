/* Dedicated mixed-space LHS renderer for Design Agent and BO Workspace. */
(function attachLHSDesignVisualization(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.LHSDesignVisualization = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildLHSDesignVisualizationApi() {
  "use strict";

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const finite = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
  const numberText = (value, digits = 4) => finite(value) === null ? "-" : String(Number(Number(value).toFixed(digits)));

  function isValid(payload) {
    if (!payload || payload.schema !== "lhs_design_visualization.v1") return false;
    const x = payload.design_space?.x || {};
    const y = payload.design_space?.y || {};
    const initial = payload.initial_design || {};
    const xDomain = Array.isArray(x.values) ? x.values : x.bounds;
    return Array.isArray(xDomain) && xDomain.length > 0
      && xDomain.every((item) => finite(item) !== null)
      && Array.isArray(y.bounds) && y.bounds.length === 2 && y.bounds.every((item) => finite(item) !== null)
      && Array.isArray(initial.points);
  }

  function scale(value, domain, output) {
    const span = domain[1] - domain[0] || 1;
    return output[0] + ((Number(value) - domain[0]) / span) * (output[1] - output[0]);
  }

  function renderPlot(payload) {
    if (!isValid(payload)) return '<div class="lhs-viz-empty">LHS design visualization unavailable</div>';
    const pngUrl = String(payload.artifacts?.png_url || "").trim();
    if (pngUrl) {
      return `<figure class="lhs-viz-matplotlib-figure"><img class="lhs-viz-matplotlib-image" src="${escapeHtml(pngUrl)}" alt="Mixed-space Latin hypercube initial design step ${escapeHtml(payload.step)}"></figure>`;
    }

    const initial = payload.initial_design;
    const xAxis = payload.design_space.x;
    const yAxis = payload.design_space.y;
    const cells = (Array.isArray(xAxis.values) ? xAxis.values : xAxis.bounds).map(Number);
    const bounds = yAxis.bounds.map(Number);
    const target = Math.max(1, Number(initial.target || 1));
    const width = 920;
    const height = 520;
    const pad = { left: 88, right: 38, top: 106, bottom: 70 };
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const xMargin = Math.max((Math.max(...cells) - Math.min(...cells)) * 0.06, 0.2);
    const xDomain = [Math.min(...cells) - xMargin, Math.max(...cells) + xMargin];
    const xScale = (value) => scale(value, xDomain, [pad.left, pad.left + plotWidth]);
    const yScale = (value) => scale(value, bounds, [pad.top + plotHeight, pad.top]);
    const strata = Array.from({ length: target + 1 }, (_, index) => bounds[0] + ((bounds[1] - bounds[0]) * index) / target);
    const yTicks = Array.from({ length: 5 }, (_, index) => bounds[0] + ((bounds[1] - bounds[0]) * index) / 4);
    const pointMarkup = initial.points.map((item, fallbackIndex) => {
      const cell = finite(item.parameters?.cell_size_mm);
      const density = finite(item.parameters?.relative_density);
      if (cell === null || density === null) return "";
      const status = String(item.status || "planned").toLowerCase();
      const index = Number(item.index || fallbackIndex + 1);
      const label = status === "measured" ? "Measured design" : status === "next" ? "Next design" : "Planned design";
      const title = `${label} ${index} · cell=${numberText(cell, 3)} mm · density=${numberText(density, 4)}`;
      if (status === "next") {
        return `<g class="lhs-viz-next" transform="translate(${xScale(cell)} ${yScale(density)})"><line x1="-8" y1="-8" x2="8" y2="8"></line><line x1="-8" y1="8" x2="8" y2="-8"></line><title>${escapeHtml(title)}</title></g>`;
      }
      return `<circle class="lhs-viz-point lhs-viz-${escapeHtml(status)}" cx="${xScale(cell)}" cy="${yScale(density)}" r="${status === "measured" ? 6.5 : 5.5}"><title>${escapeHtml(title)}</title></circle>`;
    }).join("");

    return `
      <svg class="lhs-viz-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Mixed-space Latin hypercube initial design step ${escapeHtml(payload.step)}">
        <rect class="lhs-viz-paper" width="${width}" height="${height}"></rect>
        <text class="lhs-viz-title" x="${pad.left}" y="32">Mixed-space Latin hypercube initial design</text>
        <text class="lhs-viz-subtitle" x="${pad.left}" y="54">${escapeHtml(`${initial.completed} / ${target} measured`)} · discrete cell size × stratified relative density</text>
        ${strata.map((tick) => `<line class="lhs-viz-stratum" x1="${pad.left}" y1="${yScale(tick)}" x2="${pad.left + plotWidth}" y2="${yScale(tick)}"></line>`).join("")}
        ${cells.map((tick) => `<g><line class="lhs-viz-grid" x1="${xScale(tick)}" y1="${pad.top}" x2="${xScale(tick)}" y2="${pad.top + plotHeight}"></line><text class="lhs-viz-tick" x="${xScale(tick)}" y="${pad.top + plotHeight + 24}" text-anchor="middle">${numberText(tick, 2)}</text></g>`).join("")}
        ${yTicks.map((tick) => `<text class="lhs-viz-tick" x="${pad.left - 12}" y="${yScale(tick) + 4}" text-anchor="end">${numberText(tick, 3)}</text>`).join("")}
        <line class="lhs-viz-axis" x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${pad.top + plotHeight}"></line>
        <line class="lhs-viz-axis" x1="${pad.left}" y1="${pad.top + plotHeight}" x2="${pad.left + plotWidth}" y2="${pad.top + plotHeight}"></line>
        ${pointMarkup}
        <text class="lhs-viz-axis-label" x="24" y="${pad.top + plotHeight / 2}" text-anchor="middle" transform="rotate(-90 24 ${pad.top + plotHeight / 2})">Relative density</text>
        <text class="lhs-viz-axis-label" x="${pad.left + plotWidth / 2}" y="${height - 20}" text-anchor="middle">Cell size (mm)</text>
        <g class="lhs-viz-legend" transform="translate(${pad.left} 82)">
          <circle class="lhs-viz-point lhs-viz-measured" cx="5" cy="0" r="5"></circle><text x="16" y="4">Measured design</text>
          <g class="lhs-viz-next" transform="translate(154 0)"><line x1="-5" y1="-5" x2="5" y2="5"></line><line x1="-5" y1="5" x2="5" y2="-5"></line></g><text x="166" y="4">Next design</text>
          <circle class="lhs-viz-point lhs-viz-planned" cx="270" cy="0" r="5"></circle><text x="281" y="4">Planned design</text>
        </g>
        <text class="lhs-viz-strata-label" x="${pad.left + plotWidth}" y="${pad.top + plotHeight - 8}" text-anchor="end">Density strata</text>
      </svg>`;
  }

  function artifactLinks(payload) {
    return ["png", "svg", "csv", "json"].map((kind) => ({ kind, url: String(payload?.artifacts?.[`${kind}_url`] || "") })).filter((item) => item.url);
  }

  return { isValid, renderPlot, artifactLinks };
});
