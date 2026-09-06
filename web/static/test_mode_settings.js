const profileLabels = {
  virtual_bridge: "Virtual Bridge",
  installed_printer: "Installed Printer",
  physical_print: "Physical Print",
};

const state = { revision: 0, profiles: {}, drafts: {}, active: "virtual_bridge" };
const tabs = [...document.querySelectorAll("[data-profile-id]")];
const agentCards = [...document.querySelectorAll("[data-agent-id]")];
const printBody = document.getElementById("test-mode-print-body");
const coolingWait = document.getElementById("test-mode-cooling-wait");
const autoEjection = document.getElementById("test-mode-auto-ejection");
const revision = document.getElementById("test-mode-profile-revision");
const updated = document.getElementById("test-mode-profile-updated");
const activeLabel = document.getElementById("test-mode-active-profile");
const derived = document.getElementById("test-mode-derived-flow");
const validation = document.getElementById("test-mode-validation");

function clone(value) { return JSON.parse(JSON.stringify(value)); }

function collectDraft() {
  const profile = clone(state.drafts[state.active]);
  agentCards.forEach((card) => {
    profile.agents[card.dataset.agentId].device_mode = card.querySelector("select").value;
  });
  profile.printer_flow = {
    print_body: printBody.value,
    cooling_wait: coolingWait.value,
    auto_ejection: autoEjection.checked,
  };
  state.drafts[state.active] = profile;
  return profile;
}

function validate(profile) {
  const blockers = [];
  const warnings = [];
  if (profile.printer_flow.print_body === "execute" && profile.printer_flow.cooling_wait === "skip") {
    blockers.push("Cooling can be skipped only with a skipped print body.");
  }
  if (profile.agents.specimen.device_mode === "real" && profile.printer_flow.print_body === "skip" && !profile.printer_flow.auto_ejection) {
    blockers.push("A real printer with no print body requires auto-ejection.");
  }
  if (profile.agents.vision.device_mode === "virtual" && profile.agents.manipulation.device_mode === "real") {
    blockers.push("Real robot actuation requires real Vision pose evidence.");
  }
  if (profile.agents.manipulation.device_mode === "virtual" && profile.agents.lab_equipment.device_mode === "real") {
    warnings.push("Operator LeRobot teleop confirmation and fresh UTM Vision are required.");
  }
  if ((profile.agents.specimen.device_mode === "virtual" || profile.printer_flow.print_body === "skip") && profile.agents.lab_equipment.device_mode === "real") {
    warnings.push("External specimen materialization and pickup Vision evidence are required.");
  }
  return { blockers, warnings };
}

function renderDerived(profile) {
  const report = validate(profile);
  const real = Object.entries(profile.agents).filter(([, value]) => value.device_mode === "real").map(([key]) => key);
  const virtual = Object.entries(profile.agents).filter(([, value]) => value.device_mode === "virtual").map(([key]) => key);
  derived.innerHTML = `<strong>Real:</strong> ${real.join(", ") || "none"}<br><strong>Preflight:</strong> ${virtual.join(", ") || "none"}`;
  validation.className = `test-mode-validation ${report.blockers.length ? "error" : report.warnings.length ? "warning" : "ok"}`;
  validation.textContent = [...report.blockers, ...report.warnings].join(" ") || "Profile is valid.";
  document.getElementById("btn-test-mode-save").disabled = report.blockers.length > 0;
}

function render() {
  const profile = state.drafts[state.active];
  if (!profile) return;
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.profileId === state.active));
  activeLabel.textContent = profileLabels[state.active];
  agentCards.forEach((card) => { card.querySelector("select").value = profile.agents[card.dataset.agentId].device_mode; });
  printBody.value = profile.printer_flow.print_body;
  coolingWait.value = profile.printer_flow.cooling_wait;
  autoEjection.checked = profile.printer_flow.auto_ejection;
  const printEnabled = printBody.value === "execute";
  coolingWait.disabled = printEnabled;
  if (printEnabled) coolingWait.value = "execute";
  collectDraft();
  renderDerived(state.drafts[state.active]);
}

async function readJson(response) {
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function acceptDocument(document) {
  state.revision = document.revision;
  state.profiles = clone(document.profiles);
  state.drafts = clone(document.profiles);
  revision.textContent = `Revision ${document.revision} · ${String(document.sha256 || "").slice(0, 12)}`;
  updated.textContent = document.updated_at ? `Updated ${document.updated_at}` : "Using built-in defaults; no file written yet.";
  render();
}

async function loadProfiles() {
  validation.textContent = "Loading profiles.";
  try { acceptDocument(await readJson(await fetch("/api/test-mode-execution-profiles"))); }
  catch (error) { validation.className = "test-mode-validation error"; validation.textContent = error.message; }
}

async function saveProfile() {
  const profile = collectDraft();
  try {
    const document = await readJson(await fetch(`/api/test-mode-execution-profiles/${state.active}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: state.revision, profile }),
    }));
    acceptDocument(document);
    validation.textContent = "Saved. This revision applies to the next run.";
  } catch (error) { validation.className = "test-mode-validation error"; validation.textContent = error.message; }
}

async function resetProfiles(profileId) {
  try {
    acceptDocument(await readJson(await fetch("/api/test-mode-execution-profiles/reset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: state.revision, profile_id: profileId }),
    })));
  } catch (error) { validation.className = "test-mode-validation error"; validation.textContent = error.message; }
}

tabs.forEach((tab) => tab.addEventListener("click", () => { collectDraft(); state.active = tab.dataset.profileId; render(); }));
agentCards.forEach((card) => card.querySelector("select").addEventListener("change", () => renderDerived(collectDraft())));
[printBody, coolingWait, autoEjection].forEach((control) => control.addEventListener("change", render));
document.getElementById("btn-test-mode-save").addEventListener("click", saveProfile);
document.getElementById("btn-test-mode-reload").addEventListener("click", loadProfiles);
document.getElementById("btn-test-mode-restore").addEventListener("click", () => resetProfiles(state.active));
document.getElementById("btn-test-mode-restore-all").addEventListener("click", () => resetProfiles(null));
loadProfiles();
