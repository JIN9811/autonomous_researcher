/*
File purpose:
- Frontend behavior for the dedicated Prusa MK4S / 3DP printer workspace.

Key classes/functions:
- refreshProfile
- saveProfile
- refreshStatus

Inputs/outputs:
- Input: /api/printer/profile and /api/printer/status
- Output: saved print defaults and read-only bridge status display

Dependencies:
- Fetch API

Modification guide:
- Safe places to edit: display formatting and field labels.
- Risky places to edit: API paths and element IDs consumed by printer.html.
*/

const statusDot = document.getElementById("printer-status-dot");
const statusLabel = document.getElementById("printer-status-label");
const statusDetail = document.getElementById("printer-status-detail");
const resultLog = document.getElementById("printer-result-log");

const materialInput = document.getElementById("printer-material-input");
const modelInput = document.getElementById("printer-model-input");
const profileInput = document.getElementById("printer-profile-input");
const slicerProfileInput = document.getElementById("printer-slicer-profile-input");
const nozzleInput = document.getElementById("printer-nozzle-input");
const layerInput = document.getElementById("printer-layer-input");
const firstLayerHeightInput = document.getElementById("printer-first-layer-height-input");
const firstLayerSpeedInput = document.getElementById("printer-first-layer-speed-input");
const bedTempInput = document.getElementById("printer-bed-temp-input");
const firstLayerBedTempInput = document.getElementById("printer-first-layer-bed-temp-input");
const storageInput = document.getElementById("printer-storage-input");
const maxTimeInput = document.getElementById("printer-max-time-input");
const overwriteInput = document.getElementById("printer-overwrite-input");
const startInput = document.getElementById("printer-start-input");
const ejectionInput = document.getElementById("printer-ejection-input");
const slowFirstLayerInput = document.getElementById("printer-slow-first-layer-input");
const skirtInput = document.getElementById("printer-skirt-input");
const topCapInput = document.getElementById("printer-top-cap-input");
const bottomCapInput = document.getElementById("printer-bottom-cap-input");
const skinInput = document.getElementById("printer-skin-input");
const testSizeInput = document.getElementById("printer-test-size-input");
const testCellInput = document.getElementById("printer-test-cell-input");
const ejectionObjectSizeInput = document.getElementById("printer-ejection-object-size-input");
const notesInput = document.getElementById("printer-notes-input");
const connectionHostInput = document.getElementById("printer-connection-host-input");
const connectionSchemeInput = document.getElementById("printer-connection-scheme-input");
const connectionPortInput = document.getElementById("printer-connection-port-input");
const connectionStorageInput = document.getElementById("printer-connection-storage-input");
const connectionAuthModeInput = document.getElementById("printer-connection-auth-mode-input");
const connectionUsernameInput = document.getElementById("printer-connection-username-input");
const connectionPasswordInput = document.getElementById("printer-connection-password-input");
const connectionApiKeyHeaderInput = document.getElementById("printer-connection-api-key-header-input");
const connectionApiKeyInput = document.getElementById("printer-connection-api-key-input");

const connectionSummary = document.getElementById("printer-connection-summary");
const connectionDetail = document.getElementById("printer-connection-detail");
const gateSummary = document.getElementById("printer-gate-summary");
const gateDetail = document.getElementById("printer-gate-detail");
const slicerSummary = document.getElementById("printer-slicer-summary");
const slicerDetail = document.getElementById("printer-slicer-detail");

const btnSave = document.getElementById("btn-printer-save");
const btnReset = document.getElementById("btn-printer-reset");
const btnStatusTest = document.getElementById("btn-printer-status-test");
const btnStatusLive = document.getElementById("btn-printer-status-live");
const btnOpenLive = document.getElementById("btn-printer-open-live");
const btnConnectionSave = document.getElementById("btn-printer-connection-save");
const btnConnectionReload = document.getElementById("btn-printer-connection-reload");
const btnEjectLeft = document.getElementById("btn-printer-eject-left");
const btnEjectCenter = document.getElementById("btn-printer-eject-center");
const btnEjectRight = document.getElementById("btn-printer-eject-right");
const btnEjectionApplyTestSize = document.getElementById("btn-printer-ejection-apply-test-size");

let lastProfile = null;
let ejectionObjectSizeManuallyEdited = false;

function setDotState(dot, state) {
  if (!dot) return;
  dot.className = "status-dot";
  dot.classList.add(state || "idle");
}

function writeLog(data) {
  if (resultLog) {
    resultLog.textContent = JSON.stringify(data, null, 2);
  }
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || data.message || `HTTP ${response.status}`);
  }
  return data;
}

function setBusy(button, busy) {
  if (!button) return;
  if (!button.dataset.originalText) {
    button.dataset.originalText = button.textContent;
  }
  button.disabled = busy;
  button.textContent = busy ? "Working..." : button.dataset.originalText;
}

function parseVector3(value, fallback = [30, 30, 30]) {
  const parts = String(value || "")
    .split(/[,xX×\s]+/)
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
  return parts.length === 3 ? parts : fallback;
}

function formatVector3(value, fallback = [30, 30, 30]) {
  const vector = Array.isArray(value) && value.length === 3 ? value : fallback;
  return vector.map((item) => Number(item || 0)).join(",");
}

function currentTestSpecimenSize(fallback = [30, 30, 30]) {
  return parseVector3(testSizeInput ? testSizeInput.value : "", fallback);
}

function syncEjectionObjectSizeFromTestOptions(force = false) {
  if (!ejectionObjectSizeInput) return;
  if (!force && ejectionObjectSizeManuallyEdited) return;
  ejectionObjectSizeInput.value = formatVector3(currentTestSpecimenSize());
}

function fillProfile(profile) {
  const data = profile || {};
  lastProfile = { ...data };
  if (materialInput) materialInput.value = data.material || "PLA";
  if (modelInput) modelInput.value = data.printer_model || "Prusa MK4S";
  if (profileInput) profileInput.value = data.printer_profile || "prusa_mk4s_pla_0p4_nozzle";
  if (slicerProfileInput) slicerProfileInput.value = data.slicer_profile_hint || "0.2mm_quality";
  if (nozzleInput) nozzleInput.value = Number(data.nozzle_diameter_mm || 0.4);
  if (layerInput) layerInput.value = Number(data.layer_height_mm || 0.2);
  if (firstLayerHeightInput) firstLayerHeightInput.value = Number(data.first_layer_height_mm || data.layer_height_mm || 0.2);
  if (slowFirstLayerInput) slowFirstLayerInput.checked = data.slow_first_layer_enabled !== false;
  if (firstLayerSpeedInput) {
    firstLayerSpeedInput.value = Number(data.first_layer_speed_mm_s || 10);
    firstLayerSpeedInput.disabled = data.slow_first_layer_enabled === false;
  }
  if (bedTempInput) bedTempInput.value = Number(data.bed_temperature_c ?? 60);
  if (firstLayerBedTempInput) firstLayerBedTempInput.value = Number(data.first_layer_bed_temperature_c ?? data.bed_temperature_c ?? 60);
  if (storageInput) storageInput.value = data.storage || "usb";
  if (maxTimeInput) maxTimeInput.value = Number(data.max_print_time_min || 120);
  if (overwriteInput) overwriteInput.checked = data.overwrite !== false;
  if (startInput) startInput.checked = data.start_immediately_live !== false;
  if (ejectionInput) ejectionInput.checked = Boolean(data.allow_ejection);
  if (skirtInput) skirtInput.checked = Boolean(data.skirt_enabled);
  const legacyCap = data.top_bottom_cap !== false;
  const topCap = data.top_cap_enabled === undefined ? false : Boolean(data.top_cap_enabled);
  const bottomCap = data.bottom_cap_enabled === undefined ? legacyCap : Boolean(data.bottom_cap_enabled);
  if (topCapInput) topCapInput.checked = topCap;
  if (bottomCapInput) bottomCapInput.checked = bottomCap;
  if (skinInput) {
    const skin = Number(data.skin_thickness_mm);
    skinInput.value = Number.isFinite(skin) && skin > 0 ? skin : 0.8;
    skinInput.disabled = !(topCap || bottomCap);
  }
  if (testSizeInput) testSizeInput.value = formatVector3(data.test_specimen_size_mm);
  ejectionObjectSizeManuallyEdited = false;
  syncEjectionObjectSizeFromTestOptions(true);
  if (testCellInput) testCellInput.value = Number(data.test_unit_cell_size_mm || 10);
  if (notesInput) notesInput.value = data.notes || "";
}

function fillConnection(connection) {
  const data = connection || {};
  if (connectionHostInput) connectionHostInput.value = data.host || "";
  if (connectionSchemeInput) connectionSchemeInput.value = data.scheme || "http";
  if (connectionPortInput) connectionPortInput.value = Number(data.port || 80);
  if (connectionStorageInput) connectionStorageInput.value = data.storage || "usb";
  if (connectionAuthModeInput) connectionAuthModeInput.value = data.auth_mode || "digest";
  if (connectionUsernameInput) connectionUsernameInput.value = data.username || "";
  if (connectionPasswordInput) connectionPasswordInput.value = "";
  if (connectionApiKeyHeaderInput) connectionApiKeyHeaderInput.value = data.api_key_header || "X-Api-Key";
  if (connectionApiKeyInput) connectionApiKeyInput.value = "";
}

function readConnection() {
  return {
    host: connectionHostInput ? connectionHostInput.value.trim() : "",
    scheme: connectionSchemeInput ? connectionSchemeInput.value : "http",
    port: Number(connectionPortInput ? connectionPortInput.value : 80) || 80,
    storage: connectionStorageInput ? connectionStorageInput.value.trim() || "usb" : "usb",
    auth_mode: connectionAuthModeInput ? connectionAuthModeInput.value : "digest",
    username: connectionUsernameInput ? connectionUsernameInput.value.trim() : "",
    password: connectionPasswordInput ? connectionPasswordInput.value : "",
    api_key_header: connectionApiKeyHeaderInput ? connectionApiKeyHeaderInput.value.trim() || "X-Api-Key" : "X-Api-Key",
    api_key: connectionApiKeyInput ? connectionApiKeyInput.value : "",
  };
}

function readProfile() {
  const topCapEnabled = topCapInput ? topCapInput.checked : false;
  const bottomCapEnabled = bottomCapInput ? bottomCapInput.checked : false;
  const capEnabled = topCapEnabled || bottomCapEnabled;
  const skinValue = Math.max(0.2, Number(skinInput ? skinInput.value : 0.8) || 0.8);
  return {
    material: materialInput ? materialInput.value.trim() : "PLA",
    printer_model: modelInput ? modelInput.value.trim() : "Prusa MK4S",
    printer_profile: profileInput ? profileInput.value.trim() : "prusa_mk4s_pla_0p4_nozzle",
    slicer_profile_hint: slicerProfileInput ? slicerProfileInput.value.trim() : "0.2mm_quality",
    nozzle_diameter_mm: Number(nozzleInput ? nozzleInput.value : 0.4) || 0.4,
    layer_height_mm: Number(layerInput ? layerInput.value : 0.2) || 0.2,
    first_layer_height_mm: Number(firstLayerHeightInput ? firstLayerHeightInput.value : 0.2) || 0.2,
    first_layer_speed_mm_s: Number(firstLayerSpeedInput ? firstLayerSpeedInput.value : 10) || 10,
    bed_temperature_c: Number(bedTempInput ? bedTempInput.value : 60),
    first_layer_bed_temperature_c: Number(firstLayerBedTempInput ? firstLayerBedTempInput.value : 60),
    storage: storageInput ? storageInput.value.trim() : "usb",
    max_print_time_min: Number(maxTimeInput ? maxTimeInput.value : 120) || 120,
    overwrite: overwriteInput ? overwriteInput.checked : true,
    start_immediately_live: startInput ? startInput.checked : true,
    allow_ejection: ejectionInput ? ejectionInput.checked : false,
    slow_first_layer_enabled: slowFirstLayerInput ? slowFirstLayerInput.checked : true,
    skirt_enabled: skirtInput ? skirtInput.checked : false,
    top_cap_enabled: topCapEnabled,
    bottom_cap_enabled: bottomCapEnabled,
    top_bottom_cap: capEnabled,
    skin_thickness_mm: capEnabled ? skinValue : 0.0,
    require_flat_compression_faces: topCapEnabled && bottomCapEnabled,
    test_specimen_size_mm: parseVector3(testSizeInput ? testSizeInput.value : ""),
    test_unit_cell_size_mm: Number(testCellInput ? testCellInput.value : 10) || 10,
    notes: notesInput ? notesInput.value.trim() : "",
  };
}

function renderConfig(data) {
  const profile = data.profile || {};
  const gates = data.live_gates || {};
  const autoEjection = data.auto_ejection || {};
  const slicer = data.slicer || {};
  const start = profile.start_immediately_live !== false ? "start enabled" : "upload only";
  const eject = autoEjection.enabled || profile.allow_ejection ? "auto-eject on" : "auto-eject off";
  const skirt = profile.skirt_enabled ? "skirt on" : "skirt off";
  const topCap = Boolean(profile.top_cap_enabled);
  const bottomCap = Boolean(profile.bottom_cap_enabled);
  const capSides = topCap && bottomCap ? "top+bottom" : bottomCap ? "bottom" : topCap ? "top" : "";
  const cap = profile.top_bottom_cap ? `${capSides} cap ${profile.skin_thickness_mm || 0.8} mm` : "flat cap off";
  const firstLayerHeight = `${profile.first_layer_height_mm || profile.layer_height_mm || 0.2} mm first layer`;
  const firstLayerSpeed = profile.slow_first_layer_enabled === false ? "first layer default speed" : `${profile.first_layer_speed_mm_s || 10} mm/s first layer`;
  const bedTemp = `${profile.bed_temperature_c ?? 60}/${profile.first_layer_bed_temperature_c ?? 60} C bed`;
  const testSize = Array.isArray(profile.test_specimen_size_mm) ? `test ${profile.test_specimen_size_mm.join("x")} mm` : "test 30x30x30 mm";
  const testCell = `test cell ${profile.test_unit_cell_size_mm || 10} mm`;
  if (statusLabel) {
    statusLabel.textContent = `${profile.material || "PLA"} · ${profile.layer_height_mm || 0.2} mm layer · ${firstLayerHeight} · ${firstLayerSpeed} · ${bedTemp} · ${testSize} · ${testCell} · ${start} · ${eject} · ${skirt} · ${cap}`;
  }
  if (statusDetail) {
    statusDetail.textContent = `Profile: ${data.profile_path || "memory/prusa_print_profile.json"}`;
  }
  if (gateSummary) {
    gateSummary.textContent = `upload=${Boolean(gates.allow_upload)} start=${Boolean(gates.allow_start_print)} auto-eject=${Boolean(autoEjection.enabled || profile.allow_ejection)}`;
  }
  if (gateDetail) {
    gateDetail.textContent = `Auto-eject mode=${autoEjection.mode || "append_end_gcode"} · method=${autoEjection.method || "bed_sweep"} · applies to test/live/live-test when checked.`;
  }
  if (slicerSummary) {
    slicerSummary.textContent = slicer.executable_path || "not configured";
  }
  if (slicerDetail) {
    slicerDetail.textContent = `enabled=${Boolean(slicer.enabled)} · output=${slicer.output_dir || "artifacts/gcode"}`;
  }
}

function renderConnection(connection) {
  const data = connection || {};
  if (connectionSummary) {
    const host = data.host || "not configured";
    const user = data.username || "no user";
    connectionSummary.textContent = `${host} · ${user}`;
  }
  if (connectionDetail) {
    const password = data.password_set ? "password saved" : "password missing";
    const apiKey = data.api_key_set ? "api key saved" : "api key missing";
    const auth = data.auth_mode || "digest";
    connectionDetail.textContent = `${data.scheme || "http"}:${data.port || 80} · storage=${data.storage || "usb"} · auth=${auth} · ${password} · ${apiKey}`;
  }
}

function renderStatus(data) {
  const connection = data.connection || {};
  const health = data.health || {};
  const mode = data.mode || "test";
  const ok = Boolean(data.ok || health.ok || mode === "test");
  setDotState(statusDot, ok ? (mode === "live" ? "busy" : "idle") : "warn");
  renderConnection(connection);
  if (data.connection && !document.activeElement?.id?.startsWith("printer-connection-")) {
    fillConnection(data.connection);
  }
  if (statusLabel) {
    statusLabel.textContent = ok ? `PrusaLink ${mode} status ready` : "PrusaLink status unavailable";
  }
  if (statusDetail) {
    statusDetail.textContent = health.state || health.failure_code || "virtual-ready";
  }
  renderConfig(data);
}

async function refreshConnection() {
  const data = await apiJson("/api/printer/connection");
  fillConnection(data.connection || {});
  renderConnection(data.connection || {});
  writeLog(data);
  return data;
}

async function refreshProfile() {
  const data = await apiJson("/api/printer/profile");
  fillProfile(data.profile || {});
  renderConfig(data);
  writeLog(data);
}

async function refreshStatus(mode) {
  const data = await apiJson(`/api/printer/status?mode=${encodeURIComponent(mode)}`);
  renderStatus(data);
  writeLog(data);
}

async function saveProfile() {
  setBusy(btnSave, true);
  try {
    const data = await apiJson("/api/printer/profile", {
      method: "POST",
      body: JSON.stringify(readProfile()),
    });
    fillProfile(data.profile || {});
    renderConfig(data);
    await refreshStatus("test");
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnSave, false);
  }
}

async function saveConnection() {
  setBusy(btnConnectionSave, true);
  setDotState(statusDot, "busy");
  try {
    const data = await apiJson("/api/printer/connection", {
      method: "POST",
      body: JSON.stringify(readConnection()),
    });
    fillConnection(data.connection || {});
    renderConnection(data.connection || {});
    await refreshStatus("test");
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, connection: readConnection() });
  } finally {
    setBusy(btnConnectionSave, false);
  }
}

function resetFields() {
  fillProfile(lastProfile || {});
  writeLog({ ok: true, message: "Fields reset to last loaded printer profile.", profile: lastProfile || {} });
}

function openLiveGui() {
  const url = new URL("/live", window.location.origin);
  url.searchParams.set("backend", "vllm");
  const opened = window.open(url.toString(), "_blank", "width=1440,height=960,popup=yes");
  if (!opened) {
    window.location.href = url.toString();
  }
}

async function runAutoejectionTest(position, button) {
  setBusy(button, true);
  setDotState(statusDot, "busy");
  try {
    const data = await apiJson("/api/printer/autoejection-test", {
      method: "POST",
      body: JSON.stringify({
        position,
        mode: "live",
        object_size_mm: parseVector3(ejectionObjectSizeInput ? ejectionObjectSizeInput.value : "", currentTestSpecimenSize()),
        start_immediately: true,
      }),
    });
    setDotState(statusDot, data.ok ? "idle" : "warn");
    writeLog(data);
    await refreshStatus("live");
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, position });
  } finally {
    setBusy(button, false);
  }
}

if (btnSave) btnSave.addEventListener("click", saveProfile);
if (btnReset) btnReset.addEventListener("click", resetFields);
if (btnConnectionSave) btnConnectionSave.addEventListener("click", saveConnection);
if (btnConnectionReload) btnConnectionReload.addEventListener("click", () => refreshConnection().catch((err) => writeLog({ ok: false, error: err.message })));
if (btnStatusTest) btnStatusTest.addEventListener("click", () => refreshStatus("test").catch((err) => writeLog({ ok: false, error: err.message })));
if (btnStatusLive) btnStatusLive.addEventListener("click", () => refreshStatus("live").catch((err) => writeLog({ ok: false, error: err.message })));
if (btnOpenLive) btnOpenLive.addEventListener("click", openLiveGui);
if (btnEjectLeft) btnEjectLeft.addEventListener("click", () => runAutoejectionTest("left", btnEjectLeft));
if (btnEjectCenter) btnEjectCenter.addEventListener("click", () => runAutoejectionTest("center", btnEjectCenter));
if (btnEjectRight) btnEjectRight.addEventListener("click", () => runAutoejectionTest("right", btnEjectRight));
if (testSizeInput) {
  testSizeInput.addEventListener("input", () => syncEjectionObjectSizeFromTestOptions(false));
}
if (ejectionObjectSizeInput) {
  ejectionObjectSizeInput.addEventListener("input", () => {
    ejectionObjectSizeManuallyEdited = true;
  });
}
if (btnEjectionApplyTestSize) {
  btnEjectionApplyTestSize.addEventListener("click", () => {
    ejectionObjectSizeManuallyEdited = false;
    syncEjectionObjectSizeFromTestOptions(true);
  });
}
function refreshSkinInputState() {
  if (skinInput) {
    skinInput.disabled = !Boolean((topCapInput && topCapInput.checked) || (bottomCapInput && bottomCapInput.checked));
  }
}
if (topCapInput) topCapInput.addEventListener("change", refreshSkinInputState);
if (bottomCapInput) bottomCapInput.addEventListener("change", refreshSkinInputState);
if (slowFirstLayerInput) {
  slowFirstLayerInput.addEventListener("change", () => {
    if (firstLayerSpeedInput) firstLayerSpeedInput.disabled = !slowFirstLayerInput.checked;
  });
}

refreshConnection()
  .then(() => refreshProfile())
  .then(() => refreshStatus("test"))
  .catch((err) => {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message });
  });
