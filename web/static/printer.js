/*
File purpose:
- Frontend behavior for the dedicated multi-printer / Bambu Lab 3DP workspace.

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
const bambuSourcePathInput = document.getElementById("printer-bambu-source-path-input");
const bambuArtifactPathInput = document.getElementById("printer-bambu-artifact-path-input");
const bambuPublicBaseUrlInput = document.getElementById("printer-bambu-public-base-url-input");
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
const connectionSerialInput = document.getElementById("printer-connection-serial-input");
const connectionPrinterNameInput = document.getElementById("printer-connection-printer-name-input");
const connectionModelInput = document.getElementById("printer-connection-model-input");
const connectionAccessCodeInput = document.getElementById("printer-connection-access-code-input");
const connectionLanModeInput = document.getElementById("printer-connection-lan-mode-input");
const connectionDeveloperModeInput = document.getElementById("printer-connection-developer-mode-input");
const fleetProfileInput = document.getElementById("printer-fleet-profile-input");
const autoejectionEnabledInput = document.getElementById("printer-autoejection-enabled-input");
const autoejectionProviderInput = document.getElementById("printer-autoejection-provider-input");
const autoejectionRoutineInput = document.getElementById("printer-autoejection-routine-input");
const autoejectionPreVisionInput = document.getElementById("printer-autoejection-pre-vision-input");
const autoejectionPostVisionInput = document.getElementById("printer-autoejection-post-vision-input");
const autoejectionPushDirectionInput = document.getElementById("printer-autoejection-push-direction-input");
const autoejectionZPushOffsetInput = document.getElementById("printer-autoejection-z-push-offset-input");
const autoejectionPushLaneOffsetInput = document.getElementById("printer-autoejection-push-lane-offset-input");
const autoejectionPushSpeedInput = document.getElementById("printer-autoejection-push-speed-input");
const autoejectionFullBedSweepInput = document.getElementById("printer-autoejection-full-bed-sweep-input");
const autoejectionSweepZInput = document.getElementById("printer-autoejection-sweep-z-input");
const autoejectionSweepSpeedInput = document.getElementById("printer-autoejection-sweep-speed-input");
const autoejectionFrontPathClearInput = document.getElementById("printer-autoejection-front-path-clear-input");
const autoejectionRampReadyInput = document.getElementById("printer-autoejection-ramp-ready-input");
const autoejectionToolheadCoverSecuredInput = document.getElementById("printer-autoejection-toolhead-cover-secured-input");
const autoejectionReleaseSurfaceConfirmedInput = document.getElementById("printer-autoejection-release-surface-confirmed-input");
const autoejectionReleaseSurfaceProfileInput = document.getElementById("printer-autoejection-release-surface-profile-input");
const autoejectionSupervisedInput = document.getElementById("printer-autoejection-supervised-input");
const startOperatorConfirmedInput = document.getElementById("printer-start-operator-confirmed-input");
const startGuardianApprovedInput = document.getElementById("printer-start-guardian-approved-input");
const startDryRunInput = document.getElementById("printer-start-dry-run-input");
const startGateModeDetail = document.getElementById("printer-start-gate-mode-detail");

const connectionSummary = document.getElementById("printer-connection-summary");
const connectionDetail = document.getElementById("printer-connection-detail");
const connectionActionSummary = document.getElementById("printer-connection-action-summary");
const connectionActionDetail = document.getElementById("printer-connection-action-detail");
const connectionActionList = document.getElementById("printer-connection-action-list");
const gateSummary = document.getElementById("printer-gate-summary");
const gateDetail = document.getElementById("printer-gate-detail");
const slicerSummary = document.getElementById("printer-slicer-summary");
const slicerDetail = document.getElementById("printer-slicer-detail");
const deviceTitle = document.getElementById("printer-device-title");
const cameraSummary = document.getElementById("printer-camera-summary");
const cameraDetail = document.getElementById("printer-camera-detail");
const cameraPlaceholder = document.getElementById("printer-camera-placeholder");
const cameraLiveState = document.getElementById("printer-camera-live-state");
const cameraStreamKind = document.getElementById("printer-camera-stream-kind");
const cameraProxyState = document.getElementById("printer-camera-proxy-state");
const jobSummary = document.getElementById("printer-job-summary");
const progressSummary = document.getElementById("printer-progress-summary");
const speedSummary = document.getElementById("printer-speed-summary");
const layerSummary = document.getElementById("printer-layer-summary");
const tempSummary = document.getElementById("printer-temp-summary");
const materialsSummary = document.getElementById("printer-materials-summary");
const storageSummary = document.getElementById("printer-storage-summary");
const toolSummary = document.getElementById("printer-tool-summary");
const safetySummary = document.getElementById("printer-safety-summary");
const controlState = document.getElementById("printer-control-state");
const controlQueue = document.getElementById("printer-control-queue");
const controlUpload = document.getElementById("printer-control-upload");
const controlStart = document.getElementById("printer-control-start");
const materialSlotSummary = document.getElementById("printer-material-slot-summary");
const materialSlotList = document.getElementById("printer-material-slot-list");
const evidenceSummary = document.getElementById("printer-evidence-summary");
const evidenceCards = document.getElementById("printer-evidence-cards");
const mqttPill = document.getElementById("printer-mqtt-pill");
const ftpsPill = document.getElementById("printer-ftps-pill");
const uploadPill = document.getElementById("printer-upload-pill");
const fleetSummary = document.getElementById("printer-fleet-summary");
const fleetDetail = document.getElementById("printer-fleet-detail");
const autoejectionStatusSummary = document.getElementById("printer-autoejection-status-summary");
const autoejectionStatusDetail = document.getElementById("printer-autoejection-status-detail");
const autoejectionValidationBody = document.getElementById("printer-autoejection-validation-body");
const autoejectionProofPathInput = document.getElementById("printer-autoejection-proof-path-input");
const autoejectionProofSummary = document.getElementById("printer-autoejection-proof-summary");
const autoejectionProofDetail = document.getElementById("printer-autoejection-proof-detail");
const bedClearSummary = document.getElementById("printer-bed-clear-summary");
const bedClearDetail = document.getElementById("printer-bed-clear-detail");
const spcReadinessSummary = document.getElementById("printer-spc-readiness-summary");
const spcReadinessDetail = document.getElementById("printer-spc-readiness-detail");
const spcReadinessLevels = document.getElementById("printer-spc-readiness-levels");
const spcReadinessSections = document.getElementById("printer-spc-readiness-sections");
const spcNextActions = document.getElementById("printer-spc-next-actions");
const prestartCheckSummary = document.getElementById("printer-prestart-check-summary");
const prestartCheckDetail = document.getElementById("printer-prestart-check-detail");
const prestartCheckSteps = document.getElementById("printer-prestart-check-steps");

const btnSave = document.getElementById("btn-printer-save");
const btnReset = document.getElementById("btn-printer-reset");
const btnStatusTest = document.getElementById("btn-printer-status-test");
const btnStatusLive = document.getElementById("btn-printer-status-live");
const btnVideoStatus = document.getElementById("btn-printer-video-status");
const btnUploadPathProbe = document.getElementById("btn-printer-upload-path-probe");
const btnBambuSliceArtifact = document.getElementById("btn-printer-bambu-slice-artifact");
const btnHttpArtifactRoute = document.getElementById("btn-printer-http-artifact-route");
const btnBambuPrestartCheck = document.getElementById("btn-printer-bambu-prestart-check");
const btnStartCommandDraft = document.getElementById("btn-printer-start-command-draft");
const btnStartGate = document.getElementById("btn-printer-start-gate");
const btnStartPublish = document.getElementById("btn-printer-start-publish");
const btnSpcReadiness = document.getElementById("btn-printer-spc-readiness");
const btnOpenLive = document.getElementById("btn-printer-open-live");
const btnConnectionSave = document.getElementById("btn-printer-connection-save");
const btnConnectionReload = document.getElementById("btn-printer-connection-reload");
const btnFleetSave = document.getElementById("btn-printer-fleet-save");
const btnAutoejectionFillNative = document.getElementById("btn-printer-autoejection-fill-native");
const btnAutoejectionConfigSave = document.getElementById("btn-printer-autoejection-config-save");
const btnAutoejectionValidatePreview = document.getElementById("btn-printer-autoejection-validate-preview");
const btnAutoejectionValidateLeft = document.getElementById("btn-printer-autoejection-validate-left");
const btnAutoejectionValidateCenter = document.getElementById("btn-printer-autoejection-validate-center");
const btnAutoejectionValidateRight = document.getElementById("btn-printer-autoejection-validate-right");
const btnAutoejectionTestArtifact = document.getElementById("btn-printer-autoejection-test-artifact");
const btnAutoejectionSweepTestArtifact = document.getElementById("btn-printer-autoejection-sweep-test-artifact");
const btnAutoejectionPatchArtifact = document.getElementById("btn-printer-autoejection-patch-artifact");
const btnAutoejectionProofTemplate = document.getElementById("btn-printer-autoejection-proof-template");
const btnAutoejectionCompletionAudit = document.getElementById("btn-printer-autoejection-completion-audit");
const btnBedClearMark = document.getElementById("btn-printer-bed-clear-mark");
const btnBedClearNotClear = document.getElementById("btn-printer-bed-clear-not-clear");
const btnEjectLeft = document.getElementById("btn-printer-eject-left");
const btnEjectCenter = document.getElementById("btn-printer-eject-center");
const btnEjectRight = document.getElementById("btn-printer-eject-right");
const btnEjectionApplyTestSize = document.getElementById("btn-printer-ejection-apply-test-size");

let lastProfile = null;
let ejectionObjectSizeManuallyEdited = false;
let lastWritableRemoteDir = "";
let lastHttpArtifactUrl = "";
let printerStatusManualOverride = false;
let lastPrinterProvider = "";
let lastFleetPayload = {};
let lastCameraSnapshotPath = "";
let printerOperationLockDepth = 0;
const printerOperationDisabledSnapshot = new Map();

function printerOperationButtons() {
  return [
    btnSave,
    btnReset,
    btnStatusTest,
    btnStatusLive,
    btnVideoStatus,
    btnUploadPathProbe,
    btnBambuSliceArtifact,
    btnHttpArtifactRoute,
    btnBambuPrestartCheck,
    btnStartCommandDraft,
    btnStartGate,
    btnStartPublish,
    btnSpcReadiness,
    btnConnectionSave,
    btnConnectionReload,
    btnFleetSave,
    btnAutoejectionFillNative,
    btnAutoejectionConfigSave,
    btnAutoejectionValidatePreview,
    btnAutoejectionValidateLeft,
    btnAutoejectionValidateCenter,
    btnAutoejectionValidateRight,
    btnAutoejectionTestArtifact,
    btnAutoejectionSweepTestArtifact,
    btnAutoejectionPatchArtifact,
    btnAutoejectionProofTemplate,
    btnAutoejectionCompletionAudit,
    btnBedClearMark,
    btnBedClearNotClear,
    btnEjectLeft,
    btnEjectCenter,
    btnEjectRight,
  ].filter(Boolean);
}

function setOperationButtonsLocked(locked) {
  const buttons = printerOperationButtons();
  if (locked) {
    if (printerOperationLockDepth === 0) {
      printerOperationDisabledSnapshot.clear();
      buttons.forEach((button) => printerOperationDisabledSnapshot.set(button, button.disabled));
    }
    printerOperationLockDepth += 1;
    buttons.forEach((button) => {
      button.disabled = true;
      button.classList.add("busy-locked");
    });
    return;
  }

  printerOperationLockDepth = Math.max(0, printerOperationLockDepth - 1);
  if (printerOperationLockDepth > 0) return;
  buttons.forEach((button) => {
    button.disabled = Boolean(printerOperationDisabledSnapshot.get(button));
    button.classList.remove("busy-locked");
  });
  printerOperationDisabledSnapshot.clear();
  applyStartPublishBedClearGate(btnStartPublish && btnStartPublish.dataset.bedClearBlocked === "true");
}

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
  setOperationButtonsLocked(busy);
  if (busy) button.disabled = true;
  button.textContent = busy ? "Working..." : button.dataset.originalText;
}

function applyStartPublishBedClearGate(blocked) {
  if (!btnStartPublish) return;
  btnStartPublish.dataset.bedClearBlocked = blocked ? "true" : "false";
  if (printerOperationLockDepth > 0) return;
  btnStartPublish.disabled = Boolean(blocked);
  if (blocked) {
    btnStartPublish.title = "Bambu bed-clear evidence is required before Start Publish.";
  } else {
    btnStartPublish.removeAttribute("title");
  }
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

function readStartGateOptions() {
  const options = {
    operator_confirmed: true,
    guardian_approved: true,
    dry_run: false,
    door_or_front_path_clear: true,
    ejection_ramp_or_bin_ready: true,
    toolhead_cover_secured: true,
    release_surface_confirmed: true,
    release_surface_profile: "operator-admin-managed",
    first_ejection_supervised: true,
  };
  if (startGateModeDetail) {
    startGateModeDetail.textContent = "operator-admin-managed · publish enabled";
  }
  return options;
}

function fillProfile(profile) {
  const data = profile || {};
  lastProfile = { ...data };
  if (materialInput) materialInput.value = data.material || "PLA";
  if (modelInput) modelInput.value = data.printer_model || "Bambu Lab X2D";
  if (profileInput) profileInput.value = data.printer_profile || "bambulab_x2d_pla_0p4_nozzle";
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
  if (bambuArtifactPathInput && data.bambu_artifact_path) bambuArtifactPathInput.value = data.bambu_artifact_path;
  if (bambuPublicBaseUrlInput && data.bambu_public_base_url) bambuPublicBaseUrlInput.value = data.bambu_public_base_url;
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
  if (connectionSerialInput) connectionSerialInput.value = data.serial || "";
  if (connectionPrinterNameInput) connectionPrinterNameInput.value = data.printer_name || "";
  if (connectionModelInput) connectionModelInput.value = data.model || "Bambu Lab X2D";
  if (connectionAccessCodeInput) connectionAccessCodeInput.value = "";
  if (connectionLanModeInput) connectionLanModeInput.checked = Boolean(data.lan_mode_confirmed);
  if (connectionDeveloperModeInput) connectionDeveloperModeInput.checked = Boolean(data.developer_mode_confirmed);
}

function renderFleet(data) {
  const incoming = data && typeof data === "object" ? data : {};
  const merged = {
    ...lastFleetPayload,
    ...incoming,
    selected_printer: incoming.selected_printer || lastFleetPayload.selected_printer || {},
    available_printers: Array.isArray(incoming.available_printers)
      ? incoming.available_printers
      : (Array.isArray(lastFleetPayload.available_printers) ? lastFleetPayload.available_printers : []),
  };
  if (Array.isArray(incoming.available_printers) && incoming.available_printers.length) {
    lastFleetPayload = merged;
  }
  const selected = merged.selected_printer || {};
  const activeProfileId = merged.active_profile_id || selected.profile_id || "";
  const printers = Array.isArray(merged.available_printers) ? merged.available_printers : [];
  if (fleetProfileInput && printers.length) {
    const current = fleetProfileInput.value || activeProfileId;
    fleetProfileInput.innerHTML = printers
      .map((item) => {
        const id = escapeHtml(item.profile_id || "");
        const label = escapeHtml(`${item.label || item.profile_id || "Printer"} (${item.provider || "unknown"})`);
        return `<option value="${id}">${label}</option>`;
      })
      .join("");
    fleetProfileInput.value = printers.some((item) => item.profile_id === current) ? current : activeProfileId;
  }
  if (fleetSummary) {
    const provider = selected.provider || merged.provider || "unknown";
    fleetSummary.textContent = `${activeProfileId || "not selected"} · ${provider} · auto-switch=${merged.automatic_fallback ? "on" : "off"}`;
  }
  if (fleetDetail) {
    const names = printers.map((item) => `${item.label || item.profile_id}${item.profile_id === activeProfileId ? " [active]" : ""}`).join(" / ");
    fleetDetail.textContent = names || "No selectable printer profiles reported.";
  }
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
    serial: connectionSerialInput ? connectionSerialInput.value.trim() : "",
    printer_name: connectionPrinterNameInput ? connectionPrinterNameInput.value.trim() : "",
    model: connectionModelInput ? connectionModelInput.value.trim() || "Bambu Lab X2D" : "Bambu Lab X2D",
    access_code: connectionAccessCodeInput ? connectionAccessCodeInput.value : "",
    lan_mode_confirmed: connectionLanModeInput ? connectionLanModeInput.checked : false,
    developer_mode_confirmed: connectionDeveloperModeInput ? connectionDeveloperModeInput.checked : false,
  };
}

function readProfile() {
  const topCapEnabled = topCapInput ? topCapInput.checked : false;
  const bottomCapEnabled = bottomCapInput ? bottomCapInput.checked : false;
  const capEnabled = topCapEnabled || bottomCapEnabled;
  const skinValue = Math.max(0.2, Number(skinInput ? skinInput.value : 0.8) || 0.8);
  return {
    material: materialInput ? materialInput.value.trim() : "PLA",
    printer_model: modelInput ? modelInput.value.trim() : "Bambu Lab X2D",
    printer_profile: profileInput ? profileInput.value.trim() : "bambulab_x2d_pla_0p4_nozzle",
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

function readAutoejectionConfig() {
  const provider = autoejectionProviderInput ? autoejectionProviderInput.value.trim() || "none" : "none";
  const nativePatch = provider === "bambu_gcode_patch";
  return {
    enabled: autoejectionEnabledInput ? autoejectionEnabledInput.checked : false,
    provider,
    verified_routine_id: autoejectionRoutineInput ? autoejectionRoutineInput.value.trim() : "",
    pre_eject_vision_profile: autoejectionPreVisionInput ? autoejectionPreVisionInput.value.trim() : "",
    post_eject_vision_profile: autoejectionPostVisionInput ? autoejectionPostVisionInput.value.trim() : "",
    push_direction: autoejectionPushDirectionInput ? autoejectionPushDirectionInput.value : "center",
    z_push_offset_mm: Number(autoejectionZPushOffsetInput ? autoejectionZPushOffsetInput.value : 15) || 15,
    push_lane_offset_mm: Number(autoejectionPushLaneOffsetInput ? autoejectionPushLaneOffsetInput.value : 30) || 30,
    push_speed_mm_min: Number(autoejectionPushSpeedInput ? autoejectionPushSpeedInput.value : 6000) || 6000,
    enable_full_bed_sweep: autoejectionFullBedSweepInput ? autoejectionFullBedSweepInput.checked : false,
    sweep_z_mm: Number(autoejectionSweepZInput ? autoejectionSweepZInput.value : 1) || 1,
    sweep_speed_mm_min: Number(autoejectionSweepSpeedInput ? autoejectionSweepSpeedInput.value : 6000) || 6000,
    require_verified_routine: !nativePatch,
    require_pre_eject_vision: !nativePatch,
    require_post_eject_vision: !nativePatch,
    recovery_to_robot_pickoff: !nativePatch,
  };
}

function fillAutoejectionConfig(status) {
  const data = status || {};
  const native = data.native_gcode_parameters || {};
  if (autoejectionEnabledInput) autoejectionEnabledInput.checked = Boolean(data.requested || data.enabled);
  if (autoejectionProviderInput) autoejectionProviderInput.value = data.provider || data.method || "none";
  if (autoejectionRoutineInput) autoejectionRoutineInput.value = data.verified_routine_id || "";
  if (autoejectionPreVisionInput) autoejectionPreVisionInput.value = data.pre_eject_vision_profile || "";
  if (autoejectionPostVisionInput) autoejectionPostVisionInput.value = data.post_eject_vision_profile || "";
  if (autoejectionPushDirectionInput) autoejectionPushDirectionInput.value = native.push_direction || data.push_direction || "center";
  if (autoejectionZPushOffsetInput) autoejectionZPushOffsetInput.value = Number(native.z_push_offset_mm ?? data.z_push_offset_mm ?? 15);
  if (autoejectionPushLaneOffsetInput) autoejectionPushLaneOffsetInput.value = Number(native.push_lane_offset_mm ?? data.push_lane_offset_mm ?? 30);
  if (autoejectionPushSpeedInput) autoejectionPushSpeedInput.value = Number(native.push_speed_mm_min ?? data.push_speed_mm_min ?? 6000);
  if (autoejectionFullBedSweepInput) autoejectionFullBedSweepInput.checked = Boolean(native.enable_full_bed_sweep ?? data.enable_full_bed_sweep ?? false);
  if (autoejectionSweepZInput) autoejectionSweepZInput.value = Number(native.sweep_z_mm ?? data.sweep_z_mm ?? 1);
  if (autoejectionSweepSpeedInput) autoejectionSweepSpeedInput.value = Number(native.sweep_speed_mm_min ?? data.sweep_speed_mm_min ?? 6000);
  if (autoejectionReleaseSurfaceProfileInput) {
    autoejectionReleaseSurfaceProfileInput.value = data.release_surface_profile || "cool-plate-pla";
  }
}

function fillNativeGcodeAutoejectionDefaults() {
  if (autoejectionEnabledInput) autoejectionEnabledInput.checked = true;
  if (autoejectionProviderInput) autoejectionProviderInput.value = "bambu_gcode_patch";
  if (autoejectionRoutineInput) autoejectionRoutineInput.value = "";
  if (autoejectionPreVisionInput) autoejectionPreVisionInput.value = "";
  if (autoejectionPostVisionInput) autoejectionPostVisionInput.value = "";
  if (autoejectionPushDirectionInput) autoejectionPushDirectionInput.value = "center";
  if (autoejectionZPushOffsetInput) autoejectionZPushOffsetInput.value = 15;
  if (autoejectionPushLaneOffsetInput) autoejectionPushLaneOffsetInput.value = 30;
  if (autoejectionPushSpeedInput) autoejectionPushSpeedInput.value = 6000;
  if (autoejectionFullBedSweepInput) autoejectionFullBedSweepInput.checked = false;
  if (autoejectionSweepZInput) autoejectionSweepZInput.value = 1;
  if (autoejectionSweepSpeedInput) autoejectionSweepSpeedInput.value = 6000;
  if (autoejectionReleaseSurfaceProfileInput) autoejectionReleaseSurfaceProfileInput.value = "cool-plate-pla";
  if (autoejectionStatusDetail) {
    autoejectionStatusDetail.textContent = "Native G-code patch preset filled locally. Press Save Autoejection Config, then Generate Patched Artifact before routing or publishing.";
  }
}

function renderConfig(data) {
  const profile = data.profile || {};
  const gates = data.live_gates || {};
  const autoEjection = data.auto_ejection || {};
  const slicer = data.slicer || {};
  updateAutoejectionButtonLabels(data.provider || lastPrinterProvider);
  if (statusDetail) {
    const layer = `${profile.layer_height_mm || 0.2} mm layer`;
    const testSize = Array.isArray(profile.test_specimen_size_mm) ? `${profile.test_specimen_size_mm.join("x")} mm test` : "30x30x30 mm test";
    const printerModel = profile.printer_model || "selected printer";
    const printerProfile = profile.printer_profile || "active print profile";
    const storage = String(profile.storage || "storage").toUpperCase();
    if (statusLabel && (!statusLabel.textContent || statusLabel.textContent === "Loading")) {
      statusLabel.textContent = `${printerModel} print defaults ready`;
    }
    statusDetail.textContent = `${printerModel} · ${profile.material || "PLA"} · ${layer} · ${testSize} · ${storage} · ${printerProfile}`;
  }
  if (gateSummary) {
    gateSummary.textContent = `policy upload=${Boolean(gates.allow_upload)} start=${Boolean(gates.allow_start_print)} auto-eject=${Boolean(autoEjection.enabled)}`;
  }
  if (gateDetail) {
    gateDetail.textContent = `Auto-eject mode=${autoEjection.mode || "not_configured"} · method=${autoEjection.method || "none"} · routine must be bridge-verified before physical motion.`;
  }
  renderAutoejectionStatus({ autoejection: autoEjection, blockers: autoEjection.blockers || [] });
  if (slicerSummary) {
    slicerSummary.textContent = slicer.resolved_executable_path || slicer.executable_path || "not configured";
  }
  if (slicerDetail) {
    const availability = slicer.available === undefined ? "unknown" : (slicer.available ? "available" : "missing");
    const source = slicer.source || "configured";
    slicerDetail.textContent = `enabled=${Boolean(slicer.enabled)} · ${availability} via ${source} · output=${slicer.output_dir || "artifacts/gcode"}`;
  }
}

function setAutoejectionButtonsEnabled(enabled) {
  [btnEjectLeft, btnEjectCenter, btnEjectRight].forEach((button) => {
    if (button) button.disabled = !enabled;
  });
}

function updateAutoejectionButtonLabels(provider) {
  lastPrinterProvider = provider || lastPrinterProvider || "";
  const isPrusa = String(lastPrinterProvider).toLowerCase().includes("prusa");
  const labels = isPrusa
    ? ["Autoeject Left", "Autoeject Center", "Autoeject Right"]
    : ["Run Standalone Eject: Left", "Run Standalone Eject: Center", "Run Standalone Eject: Right"];
  [
    [btnEjectLeft, labels[0]],
    [btnEjectCenter, labels[1]],
    [btnEjectRight, labels[2]],
  ].forEach(([button, label]) => {
    if (!button) return;
    button.textContent = label;
    button.dataset.originalText = label;
  });
}

function autoejectionCanRun(data, status) {
  if (Object.prototype.hasOwnProperty.call(data || {}, "can_run_test")) {
    return Boolean(data.can_run_test);
  }
  return Boolean(status.can_run_test || status.enabled);
}

function renderManipulationConsumerReadiness(data, handoff = {}) {
  const consumer = data.consumer_readiness || handoff.consumer_readiness || {};
  if (!consumer || !Object.keys(consumer).length) return "";
  if (consumer.mode === "native_gcode_patch" || consumer.profile_id === "bambu_gcode_patch") {
    return "Native G-code patcher ready · no robot consumer required";
  }
  const state = consumer.ready ? "ready" : "blocked";
  const blockers = Array.isArray(consumer.blockers) && consumer.blockers.length
    ? ` · blockers=${consumer.blockers.join(", ")}`
    : "";
  const profile = consumer.profile_id ? ` · profile=${consumer.profile_id}` : "";
  const policy = consumer.policy_ref ? ` · policy=${consumer.policy_ref}` : "";
  return `Manipulation consumer ${state}${profile}${policy}${blockers}`;
}

function formatBoundsSummary(bounds) {
  const data = bounds && typeof bounds === "object" ? bounds : {};
  const minX = data.min_x ?? "-";
  const maxX = data.max_x ?? "-";
  const minY = data.min_y ?? "-";
  const maxY = data.max_y ?? "-";
  const maxZ = data.max_z ?? "-";
  return `x=${minX}..${maxX}, y=${minY}..${maxY}, z<=${maxZ}`;
}

function formatBambuAutoejectionArtifactSummary(artifact) {
  const data = artifact && typeof artifact === "object" ? artifact : {};
  const validation = data.validation && typeof data.validation === "object" ? data.validation : {};
  const blockers = Array.isArray(data.blockers) && data.blockers.length
    ? data.blockers
    : (Array.isArray(validation.blockers) ? validation.blockers : []);
  const blockersText = blockers.length ? blockers.join(", ") : "none";
  const sourcePlate = data.source_plate_path || validation.source_plate_path || "n/a";
  const objectBounds = data.object_bounds_mm || validation.object_bounds_mm || {};
  const artifactPath = data.patched_artifact_path || data.source_path || "n/a";
  return [
    `artifact=${artifactPath}`,
    `plate=${sourcePlate}`,
    `validation=${Boolean(validation.ok)}`,
    `blockers=${blockersText}`,
    `object_bounds_mm=${formatBoundsSummary(objectBounds)}`,
  ].join(" · ");
}

function renderBambuAutoejectionValidationEvidence(data) {
  if (!autoejectionValidationBody) return;
  const payload = data && typeof data === "object" ? data : {};
  const artifact = payload.standalone_artifact && typeof payload.standalone_artifact === "object"
    ? payload.standalone_artifact
    : payload;
  const validation = artifact.validation && typeof artifact.validation === "object" ? artifact.validation : {};
  const status = payload.autoejection && typeof payload.autoejection === "object" ? payload.autoejection : {};
  const nativeParams = artifact.native_gcode_parameters && typeof artifact.native_gcode_parameters === "object"
    ? artifact.native_gcode_parameters
    : (status.native_gcode_parameters && typeof status.native_gcode_parameters === "object" ? status.native_gcode_parameters : {});
  const runtimePaths = status.runtime_paths && typeof status.runtime_paths === "object" ? status.runtime_paths : {};
  const blockers = Array.isArray(artifact.blockers) && artifact.blockers.length
    ? artifact.blockers
    : (Array.isArray(validation.blockers) ? validation.blockers : []);
  const objectBounds = artifact.object_bounds_mm || validation.object_bounds_mm || {};
  const sweepPath = [
    `position=${artifact.position || payload.position || nativeParams.push_direction || "n/a"}`,
    `push_direction=${nativeParams.push_direction || "n/a"}`,
    `z_push_offset_mm=${nativeParams.z_push_offset_mm ?? "n/a"}`,
    `push_lane_offset_mm=${nativeParams.push_lane_offset_mm ?? "n/a"}`,
    `push_speed_mm_min=${nativeParams.push_speed_mm_min ?? "n/a"}`,
    `full_bed_sweep=${Boolean(nativeParams.enable_full_bed_sweep)}`,
    `sweep_z_mm=${nativeParams.sweep_z_mm ?? "n/a"}`,
    `sweep_speed_mm_min=${nativeParams.sweep_speed_mm_min ?? "n/a"}`,
  ].join(" · ");
  autoejectionValidationBody.textContent = [
    "schema_marker=atr.bambu.autoejection.v1",
    `source_plate_path=${artifact.source_plate_path || validation.source_plate_path || "n/a"}`,
    `plate_id=${artifact.plate_id ?? "n/a"}`,
    `loop_index=${artifact.loop_index ?? "n/a"}`,
    `validation_ok=${Boolean(validation.ok)}`,
    `blockers=${blockers.length ? blockers.join(", ") : "none"}`,
    `object_bounds_mm=${formatBoundsSummary(objectBounds)}`,
    `sweep_path=${sweepPath}`,
    `standalone_path=${runtimePaths.standalone_endpoint || "/api/printer/autoejection-test"} -> ${runtimePaths.standalone_transport || "project_file"}`,
    `virtual_bridge_path=${runtimePaths.virtual_bridge_transport || "virtual"}`,
    `actual_print_path=${runtimePaths.actual_print_transport || "project_file"}${runtimePaths.home_after_standalone === false ? " · no_home_after_standalone" : ""}`,
    `patched_artifact_path=${artifact.patched_artifact_path || "n/a"}`,
    `manifest_path=${artifact.manifest_path || "n/a"}`,
  ].join("\n");
}

function renderAutoejectionStatus(data) {
  const status = data.autoejection || data.auto_ejection || {};
  const handoff = data.handoff || status.handoff || {};
  const consumerText = renderManipulationConsumerReadiness(data, handoff);
  if (data.provider) updateAutoejectionButtonLabels(data.provider);
  const blockers = Array.isArray(data.blockers) && data.blockers.length ? data.blockers : status.blockers || [];
  const canRun = autoejectionCanRun(data, status);
  const mode = status.status || status.mode || "not_configured";
  const provider = status.provider || status.method || "none";
  const validationResult = Boolean(data.validation && typeof data.validation === "object");
  const artifactResult = data.standalone_artifact || ((data.patched_artifact_path || validationResult) ? data : null);
  if (autoejectionStatusSummary) {
    const handoffReady = data.status === "provider_handoff_ready" || handoff.schema;
    const standaloneReady = data.status === "standalone_artifact_ready" || data.status === "sweep_test_artifact_ready" || (data.standalone_artifact && data.standalone_artifact.ok);
    const patchReady = Boolean(data.patched_artifact_path && data.validation);
    const validateReady = Boolean(!data.patched_artifact_path && validationResult);
    const validationPassed = Boolean(data.validation && data.validation.ok);
    autoejectionStatusSummary.textContent = standaloneReady
      ? `Native G-code artifact ready · ${provider}`
      : patchReady
        ? `Native G-code patch validated · ${provider}`
      : validateReady
        ? `Native G-code validation ${validationPassed ? "passed" : "blocked"} · ${provider}`
      : handoffReady
        ? `provider handoff ready · ${provider}`
        : `${mode} · provider=${provider}`;
  }
 if (autoejectionStatusDetail) {
    const runtimePaths = status.runtime_paths && typeof status.runtime_paths === "object" ? status.runtime_paths : {};
    if (artifactResult && (artifactResult.patched_artifact_path || validationResult)) {
      autoejectionStatusDetail.textContent = [
        formatBambuAutoejectionArtifactSummary(artifactResult),
        consumerText,
      ].filter(Boolean).join(" · ");
    } else if (handoff.schema) {
      const consumer = handoff.recommended_consumer_agent || handoff.next_owner || "provider executor";
      const motion = handoff.motion_started ? "motion started" : "no motion started";
      autoejectionStatusDetail.textContent = [
        `${consumer} · ${handoff.next_tool || "handoff only"} · ${motion}`,
        `guardian=${Boolean(handoff.requires_guardian_approval)} · operator=${Boolean(handoff.requires_operator_confirmation)}`,
        consumerText,
      ].filter(Boolean).join(" · ");
    } else {
      autoejectionStatusDetail.textContent = canRun
        ? [
            status.native_gcode_patch ? "Native G-code patch provider configured" : `routine=${status.verified_routine_id || "configured"}`,
            runtimePaths.standalone_transport ? `standalone=${runtimePaths.standalone_transport}` : "",
            `pre=${status.pre_eject_vision_profile || "n/a"}`,
            `post=${status.post_eject_vision_profile || "n/a"}`,
            consumerText,
          ].filter(Boolean).join(" · ")
        : [
            `blocked=${blockers.length ? blockers.join(", ") : "not configured"}`,
            consumerText,
          ].filter(Boolean).join(" · ");
    }
  }
  if (!document.activeElement?.id?.startsWith("printer-autoejection-")) {
    fillAutoejectionConfig(status);
  }
  renderBambuAutoejectionValidationEvidence(data);
  setAutoejectionButtonsEnabled(canRun);
}

function renderBedClearStatus(data) {
  const payload = data || {};
  const bedClear = payload.bed_clear || payload.bed_clear_evidence || {};
  const required = Boolean(bedClear.bed_clear_required);
  const verified = Boolean(bedClear.bed_clear_verified);
  const blockingCode = bedClear.blocking_code || (required && !verified ? "BAMBU_POST_EJECT_BED_NOT_CLEAR" : "");
  if (bedClearSummary) {
    bedClearSummary.textContent = blockingCode
      ? "blocked · bed not verified clear"
      : required
        ? "verified clear"
        : "not required";
  }
  if (bedClearDetail) {
    const method = bedClear.verification_method || "not recorded";
    const snapshot = bedClear.camera_snapshot_path ? ` · snapshot=${bedClear.camera_snapshot_path}` : "";
    const updated = bedClear.updated_at ? ` · updated=${bedClear.updated_at}` : "";
    bedClearDetail.textContent = blockingCode
      ? `${blockingCode} · method=${method}${snapshot}${updated}`
      : `required=${required} · verified=${verified} · method=${method}${snapshot}${updated}`;
  }
  applyStartPublishBedClearGate(Boolean(blockingCode));
}

function renderBambuProofStatus(data) {
  const payload = data || {};
  const blockers = Array.isArray(payload.blockers) ? payload.blockers : [];
  const path = payload.proof_package_path || "";
  if (autoejectionProofPathInput && path) {
    autoejectionProofPathInput.value = path;
  }
  if (autoejectionProofSummary) {
    const status = payload.status || (payload.ok ? "ok" : "incomplete");
    const verified = status === "complete_evidence_verified";
    autoejectionProofSummary.textContent = payload.ok
      ? `${status} · ${verified ? "evidence verified" : "fail-closed"}`
      : `${status} · blockers=${blockers.length}`;
  }
  if (autoejectionProofDetail) {
    const blockerText = blockers.length ? ` · ${blockers.slice(0, 4).join(", ")}` : "";
    autoejectionProofDetail.textContent = [
      path ? `path=${path}` : "path not selected",
      payload.message || payload.completion_rule || "",
      blockerText,
    ].filter(Boolean).join(" · ");
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderSpcReadiness(data) {
  const status = data.status || "not_checked";
  const ready = Boolean(data.ready_for_live_print);
  const autonomous = Boolean(data.autonomous_cycle_ready);
  const blockers = Array.isArray(data.blockers) ? data.blockers : [];
  const summary = data.operator_summary || {};
  if (spcReadinessSummary) {
    spcReadinessSummary.textContent = summary.title || `${status} · print=${ready ? "ready" : "blocked"} · loop=${autonomous ? "ready" : "attention"}`;
  }
  if (spcReadinessDetail) {
    const primary = summary.primary_blocker ? `Primary blocker: ${summary.primary_blocker}` : "";
    const policy = summary.publish_policy || "";
    const consumerText = renderManipulationConsumerReadiness(data, data.autoejection_handoff || {});
    spcReadinessDetail.textContent = [primary, policy, consumerText, data.message].filter(Boolean).join(" · ") ||
      "Specimen Making Agent printer handoff is ready for operator review.";
  }
  renderReadinessLevels(data.readiness_levels);
  renderBedClearStatus(data);
  renderConnectionActionGuidance(data.connection || {}, data.next_actions || data.operator_actions || [], data.preprint_gate || data.start_gate || {});
  if (spcReadinessSections) {
    const sections = Array.isArray(data.sections) ? data.sections : [];
    spcReadinessSections.innerHTML = sections
      .map((section) => {
        const sectionBlockers = Array.isArray(section.blockers) && section.blockers.length ? section.blockers.join(", ") : "clear";
        return `<div class="printer-readiness-section ${escapeHtml(section.status || "unknown")}">
          <strong>${escapeHtml(section.label || section.id || "Gate")}</strong>
          <span>${escapeHtml(section.status || "unknown")}</span>
          <small>${escapeHtml(section.detail || sectionBlockers)}</small>
        </div>`;
      })
      .join("");
  }
  if (spcNextActions) {
    const actions = Array.isArray(data.next_actions) ? data.next_actions : [];
    const handoff = data.autoejection_handoff || {};
    const consumerText = renderManipulationConsumerReadiness(data, handoff);
    const handoffCard = handoff.schema
      ? `<div class="printer-spc-action ready">
          <strong>Manipulation Agent handoff</strong>
          <span>${escapeHtml(handoff.status || handoff.schema || "ready")}</span>
          <small>${escapeHtml(`${handoff.recommended_consumer_agent || handoff.next_owner || "ManipulationAgent"} · ${handoff.next_tool || "lerobot.manipulation-agent.run"} · motion_started=${Boolean(handoff.motion_started)}`)}</small>
        </div>`
      : consumerText
      ? `<div class="printer-spc-action warning">
          <strong>Manipulation consumer</strong>
          <span>BLOCKED</span>
          <small>${escapeHtml(consumerText)}</small>
        </div>`
      : "";
    spcNextActions.innerHTML = actions.length
      ? actions
          .map((action) => `<div class="printer-spc-action ${escapeHtml(action.severity || "warning")}">
            <strong>${escapeHtml(action.label || action.code || "Action")}</strong>
            <span>${escapeHtml(action.code || "")}</span>
            <small>${escapeHtml(action.detail || "")}</small>
          </div>`)
          .join("") + handoffCard
      : `${handoffCard}<div class="printer-spc-action ready"><strong>No immediate operator action</strong><span>READY</span><small>${escapeHtml(data.message || "All reported gates are clear.")}</small></div>`;
  }
}

function renderPrestartCheck(data) {
  const steps = Array.isArray(data.steps) ? data.steps : [];
  const ready = Boolean(data.ready_to_publish || (data.start_gate && data.start_gate.ready_to_publish));
  if (prestartCheckSummary) {
    prestartCheckSummary.textContent = data.ok
      ? "Ready to publish, not started"
      : data.failure_code || data.status || "Blocked";
  }
  if (prestartCheckDetail) {
    const artifact = data.artifact_url || "";
    const publish = `will_publish=${Boolean(data.will_publish)} · published=${Boolean(data.published)}`;
    prestartCheckDetail.textContent = [
      ready ? "All technical pre-start gates passed." : data.message || "Review blocked pre-start gates.",
      artifact ? `artifact=${artifact}` : "",
      publish,
    ].filter(Boolean).join(" · ");
  }
  if (prestartCheckSteps) {
    prestartCheckSteps.innerHTML = steps.length
      ? steps.map((step) => `<div class="printer-readiness-level ${escapeHtml(step.status || "unknown")}">
          <span>${escapeHtml(step.label || step.id || "Step")}</span>
          <strong>${escapeHtml(step.status || "unknown")}</strong>
          <small>${escapeHtml(step.detail || "")}</small>
        </div>`).join("")
      : `<div class="printer-readiness-level unknown"><span>Pre-start checklist</span><strong>not checked</strong><small>Run Pre-start Check.</small></div>`;
  }
}

function normalizeActionList(actions) {
  const list = Array.isArray(actions) ? actions : [];
  return list
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      code: String(item.code || "").trim(),
      label: String(item.label || item.code || "Action").trim(),
      detail: String(item.detail || item.message || "").trim(),
      severity: String(item.severity || "warning").trim(),
    }))
    .filter((item) => item.code);
}

function actionByCode(actions) {
  return normalizeActionList(actions).reduce((acc, item) => {
    if (!acc[item.code]) acc[item.code] = item;
    return acc;
  }, {});
}

function renderConnectionActionGuidance(connection, actions = [], gate = {}) {
  if (!connectionActionSummary && !connectionActionList && !connectionActionDetail) return;
  const data = connection || {};
  const mappedActions = actionByCode(actions);
  const gateBlockers = Array.isArray(gate.blockers) ? gate.blockers.map((item) => String(item)) : [];
  const hasGateBlocker = (code) => gateBlockers.includes(code) || Boolean(mappedActions[code]);
  const cards = [
    {
      code: "BAMBU_LAN_MODE_NOT_CONFIRMED",
      label: "LAN-only mode",
      ok: Boolean(data.lan_mode_confirmed),
      status: data.lan_mode_confirmed ? "ready" : hasGateBlocker("BAMBU_LAN_MODE_NOT_CONFIRMED") ? "warning" : "waiting",
      detail: data.lan_mode_confirmed
        ? "Saved connection memory confirms local LAN control."
        : mappedActions.BAMBU_LAN_MODE_NOT_CONFIRMED?.detail || "Confirm LAN-only mode on the printer, then save Bridge Connection.",
    },
    {
      code: "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED",
      label: "Developer Mode",
      ok: Boolean(data.developer_mode_confirmed),
      status: data.developer_mode_confirmed ? "ready" : hasGateBlocker("BAMBU_DEVELOPER_MODE_NOT_CONFIRMED") ? "blocking" : "waiting",
      detail: data.developer_mode_confirmed
        ? "Saved connection memory confirms local write/control permission."
        : mappedActions.BAMBU_DEVELOPER_MODE_NOT_CONFIRMED?.detail || "Confirm Developer Mode before upload/start validation.",
    },
    {
      code: "BAMBU_FTPS_WRITE_FAILED",
      label: "Sliced artifact transfer",
      ok: !hasGateBlocker("BAMBU_FTPS_WRITE_FAILED") && !hasGateBlocker("BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED"),
      status: hasGateBlocker("BAMBU_FTPS_WRITE_FAILED")
        ? "blocking"
        : hasGateBlocker("BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED")
          ? "warning"
          : "ready",
      detail: mappedActions.BAMBU_FTPS_WRITE_FAILED?.detail ||
        mappedActions.BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED?.detail ||
        "Upload path has no reported blocker in the latest bridge evidence.",
    },
    {
      code: "BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE",
      label: "HTTP artifact route",
      ok: Boolean(mappedActions.BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE),
      status: mappedActions.BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE ? "warning" : "waiting",
      detail: mappedActions.BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE?.detail ||
        "Use Prepare HTTP Artifact only when FTPS write remains blocked and the printer can fetch the server URL.",
    },
  ];
  const blockingCount = cards.filter((item) => item.status === "blocking").length;
  const warningCount = cards.filter((item) => item.status === "warning" || item.status === "waiting").length;
  if (connectionActionSummary) {
    connectionActionSummary.textContent = blockingCount
      ? `${blockingCount} blocking confirmation${blockingCount === 1 ? "" : "s"}`
      : warningCount
        ? `${warningCount} confirmations to review`
        : "Connection confirmations clear";
  }
  if (connectionActionDetail) {
    const host = data.host || "host missing";
    const serial = data.serial || "SN missing";
    connectionActionDetail.textContent = `${host} · ${serial} · based on latest Live Status / SPC Readiness evidence`;
  }
  if (!connectionActionList) return;
  connectionActionList.innerHTML = cards
    .map((card) => `<div class="connection-action-card ${escapeHtml(card.status)}">
      <strong>${escapeHtml(card.label)}</strong>
      <span>${escapeHtml(card.ok ? "confirmed" : card.status)}</span>
      <small>${escapeHtml(card.detail)}</small>
    </div>`)
    .join("");
}

function renderReadinessLevels(levels) {
  if (!spcReadinessLevels) return;
  const items = Array.isArray(levels) ? levels : [];
  spcReadinessLevels.innerHTML = items.length
    ? items
        .map((level) => {
          const codes = Array.isArray(level.blocking_codes) && level.blocking_codes.length
            ? level.blocking_codes.join(", ")
            : "clear";
          return `<div class="printer-readiness-level ${escapeHtml(level.status || "unknown")}">
            <span>${escapeHtml(level.label || level.id || "Readiness")}</span>
            <strong>${escapeHtml(level.status || "unknown")}</strong>
            <small>${escapeHtml(level.detail || codes)}</small>
          </div>`;
        })
        .join("")
    : `<div class="printer-readiness-level unknown"><span>Readiness levels</span><strong>not checked</strong><small>Run SPC Readiness.</small></div>`;
}

function renderConnection(connection) {
  const data = connection || {};
  if (connectionSummary) {
    const host = data.host || "not configured";
    const serial = data.serial || "SN missing";
    connectionSummary.textContent = `${host} · ${serial}`;
  }
  if (connectionDetail) {
    const accessCode = data.access_code_set ? "access code saved" : "access code missing";
    const auth = data.auth_mode || "digest";
    const lan = data.lan_mode_confirmed ? "LAN confirmed" : "LAN not confirmed";
    const dev = data.developer_mode_confirmed ? "Developer confirmed" : "Developer not confirmed";
    connectionDetail.textContent = `${data.model || "Bambu Lab X2D"} · auth=${auth} · ${data.username || "bblp"} · ${accessCode} · ${lan} · ${dev}`;
  }
  renderConnectionActionGuidance(data);
}

function setBridgePill(element, label, state) {
  if (!element) return;
  const normalized = state || "unknown";
  element.textContent = `${label}: ${normalized}`;
  element.classList.toggle("ok", ["connected", "virtual", "ready"].includes(normalized));
  element.classList.toggle("warn", ["read_only", "degraded"].includes(normalized));
  element.classList.toggle("bad", ["disconnected", "blocked", "unknown"].includes(normalized));
}

function formatMaybe(value, suffix = "") {
  return value === null || value === undefined || value === "" ? "--" : `${value}${suffix}`;
}

function statusTone(value) {
  const state = String(value || "unknown").toLowerCase();
  if (["connected", "ready", "virtual", "preview_available", "streaming", "proxy_ready", "snapshot"].includes(state)) return "ok";
  if (["read_only", "attention", "degraded", "warning", "streaming_candidate"].includes(state)) return "warn";
  if (["blocked", "disconnected", "unavailable", "failed", "error"].includes(state)) return "bad";
  return "neutral";
}

function renderMaterialSlots(panel) {
  const slots = Array.isArray(panel.slots) ? panel.slots : [];
  if (materialSlotSummary) {
    materialSlotSummary.textContent = slots.length
      ? `${slots.length} slot${slots.length === 1 ? "" : "s"} · AMS ${formatMaybe(panel.ams_unit_count)}`
      : "No material report";
  }
  if (!materialSlotList) return;
  materialSlotList.innerHTML = slots.length
    ? slots
        .map((slot) => {
          const color = String(slot.tray_color || "").replace(/[^0-9a-fA-F]/g, "").slice(0, 6);
          const swatch = color ? `#${color}` : "#94a3b8";
          return `<div class="bambu-material-slot">
            <i style="background:${escapeHtml(swatch)}"></i>
            <strong>${escapeHtml(slot.tray_type || "Unknown")}</strong>
            <span>${escapeHtml(slot.tray_sub_brands || slot.label || "AMS slot")}</span>
            <small>${escapeHtml(formatMaybe(slot.remain_percent, "%"))}</small>
          </div>`;
        })
        .join("")
    : `<div class="bambu-empty-panel">No AMS/material payload reported by MQTT.</div>`;
}

function renderEvidenceCards(cards) {
  const list = Array.isArray(cards) ? cards : [];
  if (evidenceSummary) {
    const blocked = list.filter((card) => ["bad", "warn"].includes(statusTone(card.status))).length;
    evidenceSummary.textContent = list.length ? `${list.length} checks · ${blocked} attention` : "No evidence yet";
  }
  if (!evidenceCards) return;
  evidenceCards.innerHTML = list.length
    ? list
        .map((card) => `<div class="bambu-evidence-card ${statusTone(card.status)}">
          <strong>${escapeHtml(card.label || card.id || "Evidence")}</strong>
          <span>${escapeHtml(card.status || "unknown")}</span>
          <small>${escapeHtml(card.detail || "")}</small>
        </div>`)
        .join("")
    : `<div class="bambu-empty-panel">Run Live Status or SPC Readiness to collect bridge evidence.</div>`;
}

function streamUrlWithCacheBuster(url) {
  const value = String(url || "").trim();
  if (!value) return "";
  const joiner = value.includes("?") ? "&" : "?";
  return `${value}${joiner}t=${Date.now()}`;
}

function waitForCameraFrameLoaded(timeoutMs = 8000) {
  const img = cameraPlaceholder ? cameraPlaceholder.querySelector(".printer-video-stream") : null;
  if (!img) return Promise.resolve(false);
  if (img.complete && img.naturalWidth > 0) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      img.removeEventListener("load", onLoad);
      img.removeEventListener("error", onError);
      clearTimeout(timer);
      resolve(Boolean(ok));
    };
    const onLoad = () => finish(img.naturalWidth > 0);
    const onError = () => finish(false);
    const timer = setTimeout(() => finish(false), Number(timeoutMs) || 8000);
    img.addEventListener("load", onLoad, { once: true });
    img.addEventListener("error", onError, { once: true });
  });
}

function renderCameraPanel(data, options = {}) {
  const screen = data.device_screen || {};
  const connection = screen.connection || {};
  const camera = screen.camera || {};
  const cameraPanel = screen.camera_panel || {};
  const hasCameraPayload = Boolean(screen.camera || screen.camera_panel || data.video_status);
  if (!hasCameraPayload && options.preserveExistingStream) return;
  if (cameraSummary) {
    cameraSummary.textContent = cameraPanel.summary || (camera.liveview_preview ? `${camera.resolution || "live"} preview available` : camera.mode || "unavailable");
  }
  if (cameraLiveState) cameraLiveState.textContent = `video: ${cameraPanel.status || camera.mode || connection.video || "unknown"}`;
  if (cameraStreamKind) cameraStreamKind.textContent = `stream: ${cameraPanel.stream_kind || "unknown"}`;
  if (cameraProxyState) cameraProxyState.textContent = `proxy: ${cameraPanel.proxy_ready ? "ready" : "not ready"}`;
  if (cameraPlaceholder) {
    const proxyUrl = cameraPanel.proxy_ready && cameraPanel.proxy_url ? cameraPanel.proxy_url : "";
    const snapshotUrl = cameraPanel.snapshot_url || camera.snapshot_url || "";
    const imageUrl = snapshotUrl || proxyUrl;
    lastCameraSnapshotPath = snapshotUrl || proxyUrl || lastCameraSnapshotPath;
    const existingStream = cameraPlaceholder.querySelector(".printer-video-stream");
    if (imageUrl) {
      cameraPlaceholder.innerHTML = `<img class="printer-video-stream" src="${escapeHtml(streamUrlWithCacheBuster(imageUrl))}" alt="Bambu live video stream" />`;
    } else if (!options.preserveExistingStream || !existingStream) {
      cameraPlaceholder.innerHTML = `<span>Live video proxy is not connected yet.</span>`;
    }
  }
  if (cameraDetail) {
    const stream = cameraPanel.proxy_url || camera.rtsp_url || camera.proxy_url || "";
    const blockers = Array.isArray(cameraPanel.blockers) && cameraPanel.blockers.length ? ` · ${cameraPanel.blockers.join(", ")}` : "";
    cameraDetail.textContent = stream ? `Video endpoint detected · ${stream}${blockers}` : camera.error || `recording=${camera.recording || "unknown"} · mode=${camera.mode || "unknown"}${blockers}`;
  }
}

function renderDeviceScreen(data) {
  const screen = data.device_screen || {};
  const selected = data.selected_printer || {};
  const connection = screen.connection || {};
  const job = screen.job || {};
  const progressPanel = screen.progress_panel || {};
  const controlPanel = screen.control_panel || {};
  const materialPanel = screen.material_panel || {};
  const thermal = screen.thermal || {};
  const materials = screen.materials || {};
  const storage = screen.storage || {};
  const actions = screen.actions || {};
  const device = screen.device || {};
  const motion = screen.motion || {};
  const monitoring = screen.monitoring || {};
  const diagnostics = screen.diagnostics || {};
  const health = screen.health || {};
  if (deviceTitle) deviceTitle.textContent = selected.label || selected.profile_id || "Selected Printer";
  renderCameraPanel(data);
  if (jobSummary) jobSummary.textContent = `${progressPanel.state || job.state || "unknown"}${progressPanel.job_name || job.name ? ` · ${progressPanel.job_name || job.name}` : ""}`;
  if (progressSummary) {
    const progress = progressPanel.progress_percent ?? job.progress_percent;
    const prepareValue = progressPanel.prepare_percent ?? job.prepare_percent;
    const prepare = prepareValue === null || prepareValue === undefined || prepareValue === "" ? "" : ` · prep ${prepareValue}%`;
    progressSummary.textContent = `${formatMaybe(progress, "%")}${prepare}`;
  }
  if (speedSummary) {
    const speed = motion.speed || {};
    const queue = motion.queue || {};
    const speedValue = controlPanel.speed_percent ?? speed.magnitude_percent;
    const speedText = speedValue === null || speedValue === undefined ? "--" : `${speedValue}%`;
    const queueText = controlPanel.queue_label && controlPanel.queue_label !== "--" ? `Q ${controlPanel.queue_label}` : queue.total ? `Q ${queue.number || 0}/${queue.total}` : "Q --";
    speedSummary.textContent = `${speedText} · ${queueText}`;
  }
  if (layerSummary) {
    const currentLayer = progressPanel.current_layer ?? job.layer ?? job.current_layer;
    const totalLayers = progressPanel.total_layers ?? job.total_layers;
    layerSummary.textContent = currentLayer ? `${currentLayer}/${totalLayers || "?"}` : "--";
  }
  if (tempSummary) tempSummary.textContent = `N ${formatMaybe(thermal.main_nozzle_current_c, "C")} / B ${formatMaybe(thermal.bed_current_c, "C")}`;
  if (materialsSummary) {
    const slots = Array.isArray(materials.slots) ? materials.slots.length : 0;
    const amsStatus = materials.ams_status === null || materials.ams_status === undefined ? "" : ` · AMS ${materials.ams_status}`;
    materialsSummary.textContent = slots ? `${slots} AMS slots${amsStatus}` : `--${amsStatus}`;
  }
  if (storageSummary) {
    const internalFree = storage.internal_free_kb ? `${Math.round(Number(storage.internal_free_kb) / 1024)} MB free` : "internal unknown";
    const sdcard = storage.sdcard_available === false ? "sdcard=false" : storage.sdcard_available === true ? "sdcard=true" : "sdcard=?";
    storageSummary.textContent = `${sdcard} · ${internalFree}`;
  }
  if (toolSummary) {
    const nozzles = Array.isArray(device.nozzles) ? device.nozzles : [];
    const activeNozzle = device.active_nozzle_id === null || device.active_nozzle_id === undefined ? "?" : device.active_nozzle_id;
    const plate = device.plate && device.plate.cur_id ? device.plate.cur_id : "plate?";
    toolSummary.textContent = nozzles.length ? `${nozzles.length} nozzles · active ${activeNozzle} · ${plate}` : plate;
  }
  if (safetySummary) {
    const xcam = monitoring.xcam || {};
    const activeChecks = ["spaghetti_detector", "first_layer_inspector", "printing_monitor", "print_halt"].filter((key) => Boolean(xcam[key])).length;
    const hms = Number(health.hms_count || 0);
    const wifi = diagnostics.wifi_signal || "";
    safetySummary.textContent = `HMS ${hms} · AI ${activeChecks}/4${wifi ? ` · ${wifi}` : ""}`;
  }
  if (controlState) controlState.textContent = `state: ${controlPanel.state || job.state || "unknown"}`;
  if (controlQueue) controlQueue.textContent = `queue: ${controlPanel.queue_label || "--"}`;
  if (controlUpload) controlUpload.textContent = `upload: ${controlPanel.can_upload ? "ready" : "blocked"}`;
  if (controlStart) controlStart.textContent = `start: ${controlPanel.can_start_print ? "enabled" : "guarded"}`;
  if (gateSummary) {
    const autoEjection = data.auto_ejection || data.autoejection || {};
    gateSummary.textContent = `actual upload=${Boolean(actions.can_upload)} start=${Boolean(actions.can_start_print)} auto-eject=${Boolean(autoEjection.enabled)}`;
  }
  renderMaterialSlots(materialPanel);
  renderEvidenceCards(screen.evidence_cards);
  setBridgePill(mqttPill, "MQTT", connection.mqtt);
  setBridgePill(ftpsPill, "FTPS", connection.transfer);
  setBridgePill(uploadPill, "UPLOAD", actions.can_upload ? "ready" : "blocked");
  renderFleet(data);
}

function renderStatus(data) {
  const connection = data.connection || {};
  const health = data.health || {};
  const mode = data.mode || "test";
  const ok = Boolean(data.ok || health.ok || mode === "test");
  lastPrinterProvider = data.provider || lastPrinterProvider;
  setDotState(statusDot, ok ? (mode === "live" ? "busy" : "idle") : "warn");
  renderConnection(connection);
  if (data.connection && !document.activeElement?.id?.startsWith("printer-connection-")) {
    fillConnection(data.connection);
  }
  renderConnectionActionGuidance(data.connection || {}, data.operator_actions || [], data.preprint_gate || {});
  if (statusLabel) {
    const selected = data.selected_printer || {};
    const label = selected.label || data.provider || "printer";
    const bridgeState = ok ? "ready" : mode === "live" ? "attention" : "unavailable";
    statusLabel.textContent = `${label} ${mode} bridge ${bridgeState}`;
  }
  if (statusDetail) {
    statusDetail.textContent = health.state || health.failure_code || "virtual-ready";
  }
  renderConfig(data);
  renderDeviceScreen(data);
  if (statusLabel) {
    const selected = data.selected_printer || {};
    const label = selected.label || data.provider || "printer";
    const bridgeState = ok ? "ready" : mode === "live" ? "attention" : "unavailable";
    statusLabel.textContent = `${label} ${mode} bridge ${bridgeState}`;
  }
  if (statusDetail) {
    statusDetail.textContent = health.state || health.failure_code || data.failure_code || "virtual-ready";
  }
  const actions = Array.isArray(data.operator_actions) ? data.operator_actions : [];
  if (gateDetail && actions.length) {
    const blockers = data.preprint_gate?.blockers?.length ? `Blockers: ${data.preprint_gate.blockers.join(", ")}` : "";
    const actionText = actions.slice(0, 3).map((action) => `${action.code}: ${action.message}`).join(" · ");
    gateDetail.textContent = [blockers, actionText].filter(Boolean).join(" · ");
  }
}

async function refreshConnection() {
  const data = await apiJson("/api/printer/connection");
  fillConnection(data.connection || {});
  renderConnection(data.connection || {});
  writeLog(data);
  return data;
}

async function refreshFleet() {
  const data = await apiJson("/api/printer/fleet");
  renderFleet(data);
  writeLog(data);
  return data;
}

async function refreshProfile() {
  const data = await apiJson("/api/printer/profile");
  fillProfile(data.profile || {});
  renderConfig(data);
  writeLog(data);
}

async function refreshStatus(mode, options = {}) {
  if (options.manual) {
    printerStatusManualOverride = true;
  }
  const params = new URLSearchParams({ mode });
  if (options.emit) params.set("emit", "1");
  const data = await apiJson(`/api/printer/status?${params.toString()}`);
  if (options.initial && printerStatusManualOverride) {
    return data;
  }
  renderStatus(data);
  if (!options.silentLog) writeLog(data);
  return data;
}

async function refreshVideoStatusCamera(options = {}) {
  const data = await apiJson("/api/printer/video-status");
  renderCameraPanel(data, { preserveExistingStream: true });
  await waitForCameraFrameLoaded();
  if (!options.silentLog) writeLog(data);
  return data;
}

async function runVideoStatus() {
  setBusy(btnVideoStatus, true);
  setDotState(statusDot, "busy");
  try {
    const data = await apiJson("/api/printer/video-status");
    setDotState(statusDot, data.ok ? "idle" : "warn");
    renderCameraPanel(data);
    await waitForCameraFrameLoaded();
    const cameraPanel = data.device_screen && data.device_screen.camera_panel ? data.device_screen.camera_panel : {};
    if (cameraDetail) {
      const blockers = Array.isArray(cameraPanel.blockers) && cameraPanel.blockers.length ? ` · ${cameraPanel.blockers.join(", ")}` : "";
      cameraDetail.textContent = `${cameraPanel.status || data.status || "unknown"} · ${cameraPanel.stream_kind || "unavailable"} · proxy=${cameraPanel.proxy_ready ? "ready" : "not ready"}${blockers}`;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.video_status" });
  } finally {
    setBusy(btnVideoStatus, false);
  }
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
    await refreshStatus("live");
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
    await refreshStatus("live");
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, connection: "redacted" });
  } finally {
    setBusy(btnConnectionSave, false);
  }
}

async function saveFleetSelection() {
  setBusy(btnFleetSave, true);
  setDotState(statusDot, "busy");
  try {
    const profileId = fleetProfileInput ? fleetProfileInput.value : "";
    const data = await apiJson("/api/printer/fleet", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId }),
    });
    renderFleet(data);
    await refreshConnection();
    await refreshProfile();
    await refreshStatus("live");
    setDotState(statusDot, "idle");
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.fleet" });
  } finally {
    setBusy(btnFleetSave, false);
  }
}

async function saveAutoejectionConfig() {
  setBusy(btnAutoejectionConfigSave, true);
  setDotState(statusDot, "busy");
  try {
    const data = await apiJson("/api/printer/autoejection-config", {
      method: "POST",
      body: JSON.stringify(readAutoejectionConfig()),
    });
    setDotState(statusDot, data.autoejection && data.autoejection.can_run_test ? "idle" : "warn");
    renderAutoejectionStatus(data);
    await refreshStatus("live");
    await refreshAutoejectionStatus();
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.autoejection_config" });
  } finally {
    setBusy(btnAutoejectionConfigSave, false);
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

async function runAutoejectionTest(position, button, options = {}) {
  setBusy(button, true);
  setDotState(statusDot, "busy");
  const mode = options.mode || "live";
  const startImmediately = options.startImmediately !== false;
  try {
    const data = await apiJson("/api/printer/autoejection-test", {
      method: "POST",
      body: JSON.stringify({
        position,
        mode,
        object_size_mm: parseVector3(ejectionObjectSizeInput ? ejectionObjectSizeInput.value : "", currentTestSpecimenSize()),
        start_immediately: startImmediately,
        public_base_url: bambuPublicBaseUrlInput ? bambuPublicBaseUrlInput.value.trim() : "",
        verify_fetch: true,
        ...(startImmediately ? readStartGateOptions() : {}),
      }),
    });
    setDotState(statusDot, data.ok ? "idle" : "warn");
    await refreshStatus("live");
    renderAutoejectionStatus(data);
    if (gateDetail && data.message) {
      gateDetail.textContent = data.message;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, position });
  } finally {
    setBusy(button, false);
  }
}

async function runBambuSweepTestArtifact() {
  setBusy(btnAutoejectionSweepTestArtifact, true);
  setDotState(statusDot, "busy");
  try {
    const data = await apiJson("/api/printer/bambu-autoejection-sweep-test", {
      method: "POST",
      body: JSON.stringify({
        position: "center",
        mode: "test",
        object_size_mm: parseVector3(ejectionObjectSizeInput ? ejectionObjectSizeInput.value : "", currentTestSpecimenSize()),
        start_immediately: false,
      }),
    });
    setDotState(statusDot, data.ok ? "idle" : "warn");
    await refreshStatus("live");
    renderAutoejectionStatus(data);
    if (gateDetail) {
      const artifact = data.standalone_artifact && data.standalone_artifact.patched_artifact_path
        ? data.standalone_artifact.patched_artifact_path
        : "";
      gateDetail.textContent = data.ok
        ? `Generate Sweep Test Artifact complete: ${artifact} · no upload or MQTT publish`
        : `Generate Sweep Test Artifact blocked: ${data.failure_code || "unknown"}`;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.autoejection_sweep_test" });
  } finally {
    setBusy(btnAutoejectionSweepTestArtifact, false);
  }
}

async function refreshAutoejectionStatus() {
  try {
    const data = await apiJson("/api/printer/autoejection-status");
    renderAutoejectionStatus(data);
    return data;
  } catch (err) {
    renderAutoejectionStatus({ autoejection: { status: "unknown", provider: "none" }, blockers: [err.message] });
    return null;
  }
}

async function refreshBedClearStatus() {
  try {
    const data = await apiJson("/api/printer/bed-clear");
    renderBedClearStatus(data);
    return data;
  } catch (err) {
    renderBedClearStatus({
      bed_clear: {
        bed_clear_required: true,
        bed_clear_verified: false,
        blocking_code: err.message || "BAMBU_BED_CLEAR_STATUS_UNAVAILABLE",
      },
    });
    return null;
  }
}

async function markBedClear(verified, button) {
  setBusy(button, true);
  setDotState(statusDot, "busy");
  try {
    const data = await apiJson("/api/printer/bed-clear", {
      method: "POST",
      body: JSON.stringify({
        bed_clear_required: true,
        bed_clear_verified: Boolean(verified),
        verification_method: "operator",
        camera_snapshot_path: lastCameraSnapshotPath,
      }),
    });
    renderBedClearStatus(data);
    setDotState(statusDot, data.blockers && data.blockers.length ? "warn" : "idle");
    if (gateDetail) {
      gateDetail.textContent = verified
        ? "Bed-clear evidence marked verified by operator. Next Bambu job may proceed if other gates pass."
        : "Bed-clear evidence marked not clear. Next Bambu job remains blocked.";
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bed_clear" });
  } finally {
    setBusy(button, false);
  }
}

async function runBambuProofTemplate() {
  setBusy(btnAutoejectionProofTemplate, true);
  setDotState(statusDot, "busy");
  try {
    const proofPath = autoejectionProofPathInput ? autoejectionProofPathInput.value.trim() : "";
    const data = await apiJson("/api/printer/bambu-autoejection-proof-template", {
      method: "POST",
      body: JSON.stringify({ proof_package_path: proofPath }),
    });
    renderBambuProofStatus(data);
    setDotState(statusDot, data.ok ? "idle" : "warn");
    if (gateDetail) {
      gateDetail.textContent = data.ok
        ? `Bambu proof template created fail-closed: ${data.proof_package_path || ""}`
        : `Bambu proof template blocked: ${data.failure_code || data.message || "unknown"}`;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    renderBambuProofStatus({ ok: false, status: "error", blockers: [err.message], message: err.message });
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.improvement14_proof_template" });
  } finally {
    setBusy(btnAutoejectionProofTemplate, false);
  }
}

async function runBambuCompletionAudit() {
  setBusy(btnAutoejectionCompletionAudit, true);
  setDotState(statusDot, "busy");
  try {
    const proofPath = autoejectionProofPathInput ? autoejectionProofPathInput.value.trim() : "";
    const data = await apiJson("/api/printer/bambu-autoejection-completion-audit", {
      method: "POST",
      body: JSON.stringify({ proof_package_path: proofPath, latest: !proofPath }),
    });
    renderBambuProofStatus(data);
    setDotState(statusDot, data.ok ? "idle" : "warn");
    if (gateDetail) {
      gateDetail.textContent = data.ok
        ? "Bambu physical autoejection proof verified by completion audit."
        : `Bambu completion audit incomplete: ${(data.blockers || []).join(", ") || data.failure_code || "missing proof evidence"}`;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    renderBambuProofStatus({ ok: false, status: "error", blockers: [err.message], message: err.message });
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.improvement14_completion_audit" });
  } finally {
    setBusy(btnAutoejectionCompletionAudit, false);
  }
}

async function runUploadPathProbe() {
  setBusy(btnUploadPathProbe, true);
  setDotState(statusDot, "busy");
  try {
    const data = await apiJson("/api/printer/upload-path-probe", {
      method: "POST",
      body: JSON.stringify({ candidate_dirs: ["", "cache", "sdcard", "Metadata", "data/Metadata"] }),
    });
    setDotState(statusDot, data.ok ? "idle" : "warn");
    if (gateDetail) {
      const selected = data.selected_remote_dir ? `selected=${data.selected_remote_dir}` : "no writable path";
      const candidates = Array.isArray(data.candidates)
        ? data.candidates.map((item) => `${item.remote_dir || "root"}:${item.ok ? "ok" : item.failure_code || "failed"}`).join(" · ")
        : "";
      gateDetail.textContent = `Upload path probe: ${selected}${candidates ? ` · ${candidates}` : ""}`;
    }
    lastWritableRemoteDir = data.selected_remote_dir || "";
    setBridgePill(ftpsPill, "FTPS", data.ok ? "connected" : "read_only");
    setBridgePill(uploadPill, "UPLOAD", data.ok ? "ready" : "blocked");
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.upload_path_probe" });
  } finally {
    setBusy(btnUploadPathProbe, false);
  }
}

async function runBambuSliceArtifact() {
  setBusy(btnBambuSliceArtifact, true);
  setDotState(statusDot, "busy");
  try {
    const sourcePath = bambuSourcePathInput ? bambuSourcePathInput.value.trim() : "";
    if (!sourcePath) {
      throw new Error("Bambu source STL / 3MF path is required.");
    }
    const specimenId = sourcePath.split(/[\\/]/).pop()?.replace(/\.(stl|3mf)$/i, "") || "bambu-specimen";
    const data = await apiJson("/api/printer/bambu-slice-artifact", {
      method: "POST",
      body: JSON.stringify({
        source_path: sourcePath,
        specimen_id: specimenId,
      }),
    });
    const slicedPath = data.sliced_artifact_path || (data.artifact && data.artifact.sliced_artifact_path) || "";
    if (data.ok && slicedPath && bambuArtifactPathInput) {
      bambuArtifactPathInput.value = slicedPath;
    }
    setDotState(statusDot, data.ok ? "idle" : "warn");
    if (gateDetail) {
      const digest = data.sha256 ? String(data.sha256).slice(0, 12) : "";
      gateDetail.textContent = data.ok
        ? `Bambu sliced artifact ready: ${slicedPath}${digest ? ` · sha256=${digest}` : ""} · no upload or MQTT publish`
        : `Bambu slicing blocked: ${data.failure_code || data.message || "unknown"}`;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.slice_artifact" });
  } finally {
    setBusy(btnBambuSliceArtifact, false);
  }
}

async function runBambuAutoejectionPatchArtifact(options = {}) {
  const updateArtifactInput = options.updateArtifactInput !== false;
  const actionLabel = options.actionLabel || "Generate Patched Artifact";
  const button = options.button || btnAutoejectionPatchArtifact;
  const position = options.positionOverride || (autoejectionPushDirectionInput ? autoejectionPushDirectionInput.value : "center");
  const validateOnly = Boolean(options.validateOnly);
  setBusy(button, true);
  setDotState(statusDot, "busy");
  try {
    const artifactPath = bambuArtifactPathInput ? bambuArtifactPathInput.value.trim() : "";
    if (!artifactPath) {
      throw new Error("Bambu sliced artifact path is required before G-code autoejection patching.");
    }
    const specimenId = artifactPath.split(/[\\/]/).pop()?.replace(/\.(gcode\.3mf|gcode|3mf)$/i, "") || "bambu-specimen";
    const data = await apiJson("/api/printer/bambu-autoejection-patch", {
      method: "POST",
      body: JSON.stringify({
        artifact_path: artifactPath,
        specimen_id: specimenId,
        position,
        plate_id: 1,
        validate_only: Boolean(options.validateOnly),
      }),
    });
    const patchedPath = data.patched_artifact_path || "";
    if (!validateOnly && updateArtifactInput && data.ok && patchedPath && bambuArtifactPathInput) {
      bambuArtifactPathInput.value = patchedPath;
    }
    setDotState(statusDot, data.ok ? "idle" : "warn");
    renderAutoejectionStatus(data);
    if (gateDetail) {
      const digest = (data.patched_sha256 || data.candidate_patched_sha256) ? String(data.patched_sha256 || data.candidate_patched_sha256).slice(0, 12) : "";
      gateDetail.textContent = data.ok
        ? `${actionLabel} complete: ${validateOnly ? "validation only, no artifact written" : patchedPath}${digest ? ` · sha256=${digest}` : ""} · no upload or MQTT publish${updateArtifactInput && !validateOnly ? "" : " · source input unchanged"}`
        : `${actionLabel} blocked: ${data.failure_code || (data.blockers || []).join(", ") || "unknown"}`;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.autoejection_patch" });
  } finally {
    setBusy(button, false);
  }
}

async function runHttpArtifactRoute() {
  setBusy(btnHttpArtifactRoute, true);
  setDotState(statusDot, "busy");
  try {
    const artifactPath = bambuArtifactPathInput ? bambuArtifactPathInput.value.trim() : "";
    if (!artifactPath) {
      throw new Error("Bambu sliced artifact path is required.");
    }
    const data = await apiJson("/api/printer/http-artifact-route", {
      method: "POST",
      body: JSON.stringify({
        artifact_path: artifactPath,
        public_base_url: bambuPublicBaseUrlInput ? bambuPublicBaseUrlInput.value.trim() : "",
        subtask_name: "atr-specimen-http-artifact",
        plate_id: 1,
        use_ams: false,
        verify_fetch: true,
      }),
    });
    const fetchReady = Boolean(data.printer_fetch_ready);
    lastHttpArtifactUrl = fetchReady ? data.artifact_url || "" : "";
    setDotState(statusDot, fetchReady ? "idle" : "warn");
    if (gateDetail) {
      const url = data.artifact_url || "";
      const digest = data.artifact && data.artifact.sha256 ? String(data.artifact.sha256).slice(0, 12) : "";
      const probe = data.server_fetch_probe || {};
      const probeText = fetchReady ? "fetch verified" : `fetch blocked=${probe.failure_code || "unknown"}`;
      gateDetail.textContent = `HTTP artifact ${probeText}: ${url || data.failure_code || "unavailable"}${digest ? ` · sha256=${digest}` : ""} · no MQTT publish`;
    }
    setBridgePill(uploadPill, "UPLOAD", fetchReady ? "ready" : "blocked");
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.http_artifact_route" });
  } finally {
    setBusy(btnHttpArtifactRoute, false);
  }
}

async function runBambuPrestartCheck() {
  setBusy(btnBambuPrestartCheck, true);
  setDotState(statusDot, "busy");
  try {
    const sourcePath = bambuSourcePathInput ? bambuSourcePathInput.value.trim() : "";
    const artifactPath = bambuArtifactPathInput ? bambuArtifactPathInput.value.trim() : "";
    try {
      await refreshVideoStatusCamera({ silentLog: true });
    } catch (cameraErr) {
      if (cameraDetail) {
        cameraDetail.textContent = `Video status refresh failed · ${cameraErr.message}`;
      }
    }
    if (!sourcePath && !artifactPath) {
      throw new Error("Bambu source STL / 3MF path or sliced artifact path is required.");
    }
    const sourceName = sourcePath.split(/[\\/]/).pop()?.replace(/\.(stl|3mf)$/i, "") || "";
    const artifactName = artifactPath.split(/[\\/]/).pop()?.replace(/\.(gcode\.3mf|gcode|3mf)$/i, "") || "";
    const data = await apiJson("/api/printer/bambu-prestart-check", {
      method: "POST",
      body: JSON.stringify({
        source_path: sourcePath,
        artifact_path: artifactPath,
        specimen_id: sourceName || artifactName || "bambu-specimen",
        public_base_url: bambuPublicBaseUrlInput ? bambuPublicBaseUrlInput.value.trim() : "",
        subtask_name: "atr-bambu-prestart",
        plate_id: 1,
        use_ams: false,
        verify_fetch: true,
        ...readStartGateOptions(),
      }),
    });
    if (data.sliced_artifact_path && bambuArtifactPathInput) {
      bambuArtifactPathInput.value = data.sliced_artifact_path;
    }
    if (data.artifact_url) {
      lastHttpArtifactUrl = data.artifact_url;
    }
    setDotState(statusDot, data.ready_to_publish ? "idle" : "warn");
    renderPrestartCheck(data);
    if (data.device_screen || (data.spc_readiness && data.spc_readiness.device_screen)) {
      renderDeviceScreen(data.spc_readiness || data);
    }
    if (data.spc_readiness) {
      renderSpcReadiness(data.spc_readiness);
    }
    try {
      await refreshVideoStatusCamera({ silentLog: true });
    } catch (cameraErr) {
      if (cameraDetail) {
        cameraDetail.textContent = `Video status refresh failed · ${cameraErr.message}`;
      }
    }
    if (gateDetail) {
      const blockers = data.start_gate && Array.isArray(data.start_gate.blockers) && data.start_gate.blockers.length
        ? data.start_gate.blockers.join(", ")
        : "none";
      gateDetail.textContent = `Pre-start: ready=${Boolean(data.ready_to_publish)} · blockers=${blockers} · no MQTT publish`;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    renderPrestartCheck({ ok: false, status: "error", failure_code: err.message, steps: [] });
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.prestart_check" });
  } finally {
    setBusy(btnBambuPrestartCheck, false);
  }
}

async function runStartCommandDraft() {
  setBusy(btnStartCommandDraft, true);
  setDotState(statusDot, "busy");
  try {
    const baseDir = lastWritableRemoteDir || "cache";
    const defaultRemote = lastHttpArtifactUrl || `${baseDir}/specimen.gcode.3mf`.replace(/^\/+/, "");
    const data = await apiJson("/api/printer/start-command-draft", {
      method: "POST",
      body: JSON.stringify({
        remote_path: defaultRemote,
        subtask_name: "atr-specimen-draft",
        plate_id: 1,
        use_ams: false,
      }),
    });
    setDotState(statusDot, data.ok ? "idle" : "warn");
    if (gateDetail) {
      const command = data.payload && data.payload.print ? data.payload.print.command : "unavailable";
      const url = data.payload && data.payload.print ? data.payload.print.url : "";
      gateDetail.textContent = `Print command draft: ${command} · ${url || data.failure_code || "no artifact"} · draft only, no publish`;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.start_command_draft" });
  } finally {
    setBusy(btnStartCommandDraft, false);
  }
}

async function runStartGateCheck() {
  setBusy(btnStartGate, true);
  setDotState(statusDot, "busy");
  try {
    const baseDir = lastWritableRemoteDir || "cache";
    const defaultRemote = lastHttpArtifactUrl || `${baseDir}/specimen.gcode.3mf`.replace(/^\/+/, "");
    const data = await apiJson("/api/printer/start-gate", {
      method: "POST",
      body: JSON.stringify({
        remote_path: defaultRemote,
        subtask_name: "atr-specimen-start-gate",
        plate_id: 1,
        use_ams: false,
        ...readStartGateOptions(),
      }),
    });
    setDotState(statusDot, data.ready_to_publish ? "idle" : "warn");
    if (gateDetail) {
      const blockers = Array.isArray(data.blockers) && data.blockers.length ? data.blockers.join(", ") : "none";
      gateDetail.textContent = `Start gate: ready=${Boolean(data.ready_to_publish)} · blockers=${blockers} · will_publish=${Boolean(data.will_publish)}`;
    }
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.start_gate" });
  } finally {
    setBusy(btnStartGate, false);
  }
}

async function runStartPublish() {
  if (!window.confirm("This can send the Bambu project_file start command if every gate is ready. Continue?")) {
    return;
  }
  setBusy(btnStartPublish, true);
  setDotState(statusDot, "busy");
  try {
    const baseDir = lastWritableRemoteDir || "cache";
    const defaultRemote = lastHttpArtifactUrl || `${baseDir}/specimen.gcode.3mf`.replace(/^\/+/, "");
    const data = await apiJson("/api/printer/start-publish", {
      method: "POST",
      body: JSON.stringify({
        remote_path: defaultRemote,
        subtask_name: "atr-specimen-start",
        plate_id: 1,
        use_ams: false,
        ...readStartGateOptions(),
      }),
    });
    setDotState(statusDot, data.published ? "idle" : "warn");
    if (gateDetail) {
      const blockers = Array.isArray(data.blockers) && data.blockers.length ? data.blockers.join(", ") : "none";
      gateDetail.textContent = `Start publish: published=${Boolean(data.published)} · blockers=${blockers} · ${data.message || ""}`;
    }
    writeLog(data);
    await refreshStatus("live");
  } catch (err) {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message, tool: "printer.bambu.start_publish" });
  } finally {
    setBusy(btnStartPublish, false);
  }
}

async function runSpcReadiness() {
  setBusy(btnSpcReadiness, true);
  setDotState(statusDot, "busy");
  try {
    const baseDir = lastWritableRemoteDir || "cache";
    const defaultRemote = lastHttpArtifactUrl || `${baseDir}/specimen.gcode.3mf`.replace(/^\/+/, "");
    const data = await apiJson("/api/printer/spc-readiness", {
      method: "POST",
      body: JSON.stringify({
        mode: "live",
        remote_path: defaultRemote,
        subtask_name: "atr-spc-readiness",
        plate_id: 1,
        use_ams: false,
        ...readStartGateOptions(),
      }),
    });
    setDotState(statusDot, data.ready_for_live_print ? "idle" : "warn");
    renderDeviceScreen(data);
    renderSpcReadiness(data);
    writeLog(data);
  } catch (err) {
    setDotState(statusDot, "warn");
    renderSpcReadiness({ status: "error", ready_for_live_print: false, blockers: [err.message], sections: [] });
    writeLog({ ok: false, error: err.message, tool: "printer.spc_readiness" });
  } finally {
    setBusy(btnSpcReadiness, false);
  }
}

if (btnSave) btnSave.addEventListener("click", saveProfile);
if (btnReset) btnReset.addEventListener("click", resetFields);
if (btnConnectionSave) btnConnectionSave.addEventListener("click", saveConnection);
if (btnConnectionReload) btnConnectionReload.addEventListener("click", () => refreshConnection().catch((err) => writeLog({ ok: false, error: err.message })));
if (btnFleetSave) btnFleetSave.addEventListener("click", () => saveFleetSelection());
if (btnAutoejectionFillNative) btnAutoejectionFillNative.addEventListener("click", fillNativeGcodeAutoejectionDefaults);
if (btnAutoejectionConfigSave) btnAutoejectionConfigSave.addEventListener("click", () => saveAutoejectionConfig());
if (btnAutoejectionValidatePreview) {
  btnAutoejectionValidatePreview.addEventListener("click", () => runBambuAutoejectionPatchArtifact({
    actionLabel: "Validate G-code Preview",
    button: btnAutoejectionValidatePreview,
    updateArtifactInput: false,
    validateOnly: true,
  }));
}
if (btnAutoejectionValidateLeft) {
  btnAutoejectionValidateLeft.addEventListener("click", () => runBambuAutoejectionPatchArtifact({
    actionLabel: "Validate Left",
    button: btnAutoejectionValidateLeft,
    updateArtifactInput: false,
    positionOverride: "left",
    validateOnly: true,
  }));
}
if (btnAutoejectionValidateCenter) {
  btnAutoejectionValidateCenter.addEventListener("click", () => runBambuAutoejectionPatchArtifact({
    actionLabel: "Validate Center",
    button: btnAutoejectionValidateCenter,
    updateArtifactInput: false,
    positionOverride: "center",
    validateOnly: true,
  }));
}
if (btnAutoejectionValidateRight) {
  btnAutoejectionValidateRight.addEventListener("click", () => runBambuAutoejectionPatchArtifact({
    actionLabel: "Validate Right",
    button: btnAutoejectionValidateRight,
    updateArtifactInput: false,
    positionOverride: "right",
    validateOnly: true,
  }));
}
if (btnBedClearMark) btnBedClearMark.addEventListener("click", () => markBedClear(true, btnBedClearMark));
if (btnBedClearNotClear) btnBedClearNotClear.addEventListener("click", () => markBedClear(false, btnBedClearNotClear));
if (btnStatusTest) btnStatusTest.addEventListener("click", () => refreshStatus("test", { manual: true, emit: true }).catch((err) => writeLog({ ok: false, error: err.message })));
if (btnStatusLive) btnStatusLive.addEventListener("click", () => refreshStatus("live", { manual: true, emit: true }).catch((err) => writeLog({ ok: false, error: err.message })));
if (btnVideoStatus) btnVideoStatus.addEventListener("click", () => runVideoStatus());
if (btnUploadPathProbe) btnUploadPathProbe.addEventListener("click", () => runUploadPathProbe());
if (btnBambuSliceArtifact) btnBambuSliceArtifact.addEventListener("click", () => runBambuSliceArtifact());
if (btnAutoejectionPatchArtifact) btnAutoejectionPatchArtifact.addEventListener("click", () => runBambuAutoejectionPatchArtifact());
if (btnAutoejectionTestArtifact) {
  btnAutoejectionTestArtifact.addEventListener("click", () => {
    const position = autoejectionPushDirectionInput ? autoejectionPushDirectionInput.value : "center";
    runAutoejectionTest(position, btnAutoejectionTestArtifact, { mode: "test", startImmediately: false });
  });
}
if (btnAutoejectionSweepTestArtifact) btnAutoejectionSweepTestArtifact.addEventListener("click", () => runBambuSweepTestArtifact());
if (btnAutoejectionProofTemplate) btnAutoejectionProofTemplate.addEventListener("click", () => runBambuProofTemplate());
if (btnAutoejectionCompletionAudit) btnAutoejectionCompletionAudit.addEventListener("click", () => runBambuCompletionAudit());
if (btnHttpArtifactRoute) btnHttpArtifactRoute.addEventListener("click", () => runHttpArtifactRoute());
if (btnBambuPrestartCheck) btnBambuPrestartCheck.addEventListener("click", () => runBambuPrestartCheck());
if (btnStartCommandDraft) btnStartCommandDraft.addEventListener("click", () => runStartCommandDraft());
if (btnStartGate) btnStartGate.addEventListener("click", () => runStartGateCheck());
if (btnStartPublish) btnStartPublish.addEventListener("click", () => runStartPublish());
if (btnSpcReadiness) btnSpcReadiness.addEventListener("click", () => runSpcReadiness());
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
[
  startOperatorConfirmedInput,
  startGuardianApprovedInput,
  startDryRunInput,
  autoejectionFrontPathClearInput,
  autoejectionRampReadyInput,
  autoejectionToolheadCoverSecuredInput,
  autoejectionReleaseSurfaceConfirmedInput,
  autoejectionReleaseSurfaceProfileInput,
  autoejectionSupervisedInput,
].forEach((input) => {
  if (input) input.addEventListener("change", readStartGateOptions);
});

refreshFleet()
  .then(() => refreshConnection())
  .then(() => refreshProfile())
  .then(() => refreshStatus("live", { initial: true }))
  .then(() => refreshAutoejectionStatus())
  .then(() => refreshBedClearStatus())
  .then(() => readStartGateOptions())
  .catch((err) => {
    setDotState(statusDot, "warn");
    writeLog({ ok: false, error: err.message });
  });
