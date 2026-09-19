/* Approved Matplotlib figures; local view switching never fits or requests a GP. */
(function (root) {
  "use strict";
  const modes = new Map();
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const safeUrl = value => typeof value === "string" && /^\/(?!\/)/.test(value) && !/[\x00-\x20\\]/.test(value);
  function valid(payload) {
    const a = payload?.artifacts;
    return !!a && safeUrl(a.surface_2d_url) && safeUrl(a.surface_3d_url);
  }
  function render(payload) {
    if (!valid(payload)) return "";
    const run = String(payload.run_id || ""), mode = modes.get(run) || "2d";
    return `<section class="bo-surface-card" data-bo-surface-run="${esc(run)}" data-bo-surface-step="${esc(payload.step)}">
      <div class="bo-surface-toolbar"><div role="group" aria-label="Posterior view">${["2d","3d"].map(m => `<button type="button" data-bo-surface-mode="${m}" aria-pressed="${m === mode}">${m.toUpperCase()}</button>`).join("")}</div></div>
      ${["2d","3d"].map(m => `<div class="bo-surface-plots" data-bo-surface-view="${m}" ${m !== mode ? "hidden" : ""}><a href="${esc(payload.artifacts[`surface_${m}_url`])}" target="_blank" rel="noopener"><img src="${esc(payload.artifacts[`surface_${m}_url`])}" alt="Live Posterior ${m.toUpperCase()}: posterior mean, uncertainty and acquisition; step ${esc(payload.step)}${payload.synthetic_only ? '; synthetic data only' : ''}" /></a></div>`).join("")}
    </section>`;
  }
  function select(section, mode) {
    if (!section || !["2d","3d"].includes(mode)) return;
    modes.set(section.dataset.boSurfaceRun, mode);
    if (modes.size > 16) modes.delete(modes.keys().next().value);
    section.querySelectorAll("[data-bo-surface-view]").forEach(p => {p.hidden = p.dataset.boSurfaceView !== mode;});
    section.querySelectorAll("[data-bo-surface-mode]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.boSurfaceMode === mode)));
  }
  root.document?.addEventListener("click", event => {
    const button = event.target.closest?.("[data-bo-surface-mode]");
    if (button) select(button.closest("[data-bo-surface-run]"), button.dataset.boSurfaceMode);
  });
  const api = Object.freeze({valid, render, select});
  root.BOPosteriorSurface = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
