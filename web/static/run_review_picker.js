/* Main GUI replay selector: presentation-only, no run-control requests. */
(() => {
  "use strict";
  const mode = document.getElementById("mode-select");
  const field = document.getElementById("replay-session-field");
  const select = document.getElementById("replay-session-select");
  const status = document.getElementById("replay-session-status");
  if (!mode || !field || !select || !status) return;
  const grid = document.getElementById("main-run-control-grid");
  const experimentFields = ["run-inference-field", "run-fault-field", "run-fault-stage-field"]
    .map(id => document.getElementById(id)).filter(Boolean);
  let generation = 0;
  function option(value, label) {
    const node = document.createElement("option"); node.value = value; node.textContent = label; return node;
  }
  async function update() {
    const current = ++generation;
    const active = mode.value === "replay";
    if (grid) grid.dataset.mode = mode.value;
    for (const item of experimentFields) {
      item.hidden = active;
      item.style.display = active ? "none" : "";
    }
    field.hidden = !active; field.style.display = active ? "" : "none";
    if (!active) return;
    const previous = select.value;
    select.disabled = true; select.replaceChildren(option("", "Loading recorded sessions…")); status.textContent = "";
    try {
      const response = await fetch("/api/review/runs", {method:"GET",cache:"no-store"});
      if (!response.ok) throw new Error("Replay archive unavailable. Enable it at the next server restart.");
      const data = await response.json();
      if (generation !== current) return;
      select.replaceChildren();
      for (const run of data.runs) select.append(option(run.run_id, `${run.run_id} · ${run.points} points`));
      select.disabled = !data.runs.length;
      if (data.runs.some(run => run.run_id === previous)) select.value = previous;
      if (!data.runs.length) select.append(option("", "No recorded sessions"));
      status.textContent = data.runs.length ? "Start opens the selected session in a read-only window." : "New runs will appear here after recording is enabled.";
    } catch (error) {
      if (generation !== current) return;
      select.replaceChildren(option("", "Archive unavailable")); status.textContent = error.message;
    }
  }
  function open() {
    if (mode.value !== "replay") return;
    if (select.disabled || !select.value) {status.textContent = "Select a recorded experiment session first."; return;}
    const display = window.screen || {};
    const width = display.availWidth || window.innerWidth || 1440;
    const height = display.availHeight || window.innerHeight || 960;
    const left = Number.isFinite(display.availLeft) ? display.availLeft : 0;
    const top = Number.isFinite(display.availTop) ? display.availTop : 0;
    window.open(`/replay?run_id=${encodeURIComponent(select.value)}`, "_blank",
      `popup=yes,width=${width},height=${height},left=${left},top=${top},noopener,noreferrer`);
  }
  window.AX4LABRunReviewPicker = Object.freeze({open});
  mode.addEventListener("change", update);
  update();
})();
