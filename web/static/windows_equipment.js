/*
File purpose:
- Frontend behavior for Windows PyAutoGUI bridge discovery/setup GUI.

Key classes/functions:
- refreshConfig
- scanNetwork
- connectCandidate
- testSelected
- runProgram1

Inputs/outputs:
- Input: /api/equipment/windows/* endpoints
- Output: saved candidate status, discovered candidates, setup test logs

Dependencies:
- Fetch API

Modification guide:
- Safe places to edit: rendering and labels.
- Risky places to edit: API paths and element IDs consumed by windows_equipment.html.
*/

const connectionDot = document.getElementById("equipment-connection-dot");
const connectionLabel = document.getElementById("equipment-connection-label");
const connectionDetail = document.getElementById("equipment-connection-detail");
const actionDot = document.getElementById("equipment-action-dot");
const actionLabel = document.getElementById("equipment-action-label");
const actionDetail = document.getElementById("equipment-action-detail");
const commandBanner = document.getElementById("equipment-command-banner");
const commandTitle = document.getElementById("equipment-command-title");
const commandDetail = document.getElementById("equipment-command-detail");
const commandPill = document.getElementById("equipment-command-pill");
const subnetInput = document.getElementById("equipment-subnet-input");
const portInput = document.getElementById("equipment-port-input");
const tokenInput = document.getElementById("equipment-token-input");
const candidatesEl = document.getElementById("equipment-candidates");
const savedCandidatesEl = document.getElementById("equipment-saved-candidates");
const resultLog = document.getElementById("equipment-result-log");
const btnScan = document.getElementById("btn-equipment-scan");
const btnRefresh = document.getElementById("btn-equipment-refresh");
const btnTest = document.getElementById("btn-equipment-test");
const btnProgram1 = document.getElementById("btn-equipment-program1");
const btnUtm = document.getElementById("btn-equipment-utm");
const btnAbort = document.getElementById("btn-equipment-abort");
const btnScreenshot = document.getElementById("btn-equipment-screenshot");
const btnListLocators = document.getElementById("btn-equipment-list-locators");
const btnCaptureLocator = document.getElementById("btn-equipment-capture-locator");
const btnLoadUtmProfile = document.getElementById("btn-equipment-load-utm-profile");
const btnOpenBridgeGui = document.getElementById("btn-equipment-open-bridge-gui");
const localBridgeDot = document.getElementById("equipment-local-bridge-dot");
const localBridgeStatus = document.getElementById("equipment-local-bridge-status");
const localBridgeDetail = document.getElementById("equipment-local-bridge-detail");
const btnLocalStart = document.getElementById("btn-equipment-local-start");
const btnLocalStop = document.getElementById("btn-equipment-local-stop");
const btnLocalHealth = document.getElementById("btn-equipment-local-health");
const btnLocalSelect = document.getElementById("btn-equipment-local-select");
const btnSaveUtmProfile = document.getElementById("btn-equipment-save-utm-profile");
const btnReadiness = document.getElementById("btn-equipment-readiness");
const btnLivePreflight = document.getElementById("btn-equipment-live-preflight");
const btnLiveValidation = document.getElementById("btn-equipment-live-validation");
const btnVisionProofDraft = document.getElementById("btn-equipment-vision-proof-draft");
const btnLivePhysicalValidation = document.getElementById("btn-equipment-live-physical-validation");
const btnEvidenceAudit = document.getElementById("btn-equipment-evidence-audit");
const btnProofPackage = document.getElementById("btn-equipment-proof-package");
const btnVerifyProofPackage = document.getElementById("btn-equipment-verify-proof-package");
const btnCompletionAudit = document.getElementById("btn-equipment-completion-audit");
const btnRequestLog = document.getElementById("btn-equipment-request-log");
const livePreflightScreenshotInput = document.getElementById("equipment-live-preflight-screenshot");
const livePhysicalSafeInput = document.getElementById("equipment-live-physical-safe");
const liveVisionProofInput = document.getElementById("equipment-live-vision-proof");
const utmProfileStatus = document.getElementById("equipment-utm-profile-status");
const utmReadinessCard = document.getElementById("equipment-utm-readiness-card");
const utmReadinessStatus = document.getElementById("equipment-utm-readiness-status");
const utmReadinessDetail = document.getElementById("equipment-utm-readiness-detail");
const utmLiveValidationCard = document.getElementById("equipment-utm-live-validation-card");
const utmLiveValidationStatus = document.getElementById("equipment-utm-live-validation-status");
const utmLiveValidationDetail = document.getElementById("equipment-utm-live-validation-detail");
const utmLiveValidationGates = document.getElementById("equipment-utm-live-validation-gates");
const utmEvidenceCard = document.getElementById("equipment-utm-evidence-card");
const utmEvidenceStatus = document.getElementById("equipment-utm-evidence-status");
const utmEvidenceDetail = document.getElementById("equipment-utm-evidence-detail");
const utmProofChecklist = document.getElementById("equipment-utm-proof-checklist");
const proofVerifyCard = document.getElementById("equipment-proof-verify-card");
const proofVerifyStatus = document.getElementById("equipment-proof-verify-status");
const proofVerifyDetail = document.getElementById("equipment-proof-verify-detail");
const completionAuditCard = document.getElementById("equipment-completion-audit-card");
const completionAuditStatus = document.getElementById("equipment-completion-audit-status");
const completionAuditDetail = document.getElementById("equipment-completion-audit-detail");
const requestAuditCard = document.getElementById("equipment-request-audit-card");
const profileItems = document.getElementById("equipment-profile-items");
const profileConnectionStatus = document.getElementById("equipment-profile-connection-status");
const profileEvidenceStatus = document.getElementById("equipment-profile-evidence-status");
const btnProfilePreflight = document.getElementById("btn-equipment-profile-preflight");
const btnProfileTest = document.getElementById("btn-equipment-profile-test");
const requestAuditStatus = document.getElementById("equipment-request-audit-status");
const requestAuditDetail = document.getElementById("equipment-request-audit-detail");
const utmExportGlobInput = document.getElementById("equipment-utm-export-glob");
const utmTimeoutInput = document.getElementById("equipment-utm-timeout");
const utmStableInput = document.getElementById("equipment-utm-stable-sec");
const utmExpectedExportPathInput = document.getElementById("equipment-utm-expected-export-path");
const utmTargetWindowInput = document.getElementById("equipment-utm-target-window");
const utmRequireFocusInput = document.getElementById("equipment-utm-require-focus");
const utmManualSaveInput = document.getElementById("equipment-utm-manual-save");
const utmRequireScreenInput = document.getElementById("equipment-utm-require-screen");
const utmSimulateInput = document.getElementById("equipment-utm-simulate");
const utmLocatorsInput = document.getElementById("equipment-utm-locators");
const locatorProgramInput = document.getElementById("equipment-locator-program");
const locatorNameInput = document.getElementById("equipment-locator-name");
const locatorConfidenceInput = document.getElementById("equipment-locator-confidence");
const locatorXInput = document.getElementById("equipment-locator-x");
const locatorYInput = document.getElementById("equipment-locator-y");
const locatorWidthInput = document.getElementById("equipment-locator-width");
const locatorHeightInput = document.getElementById("equipment-locator-height");
const {
  candidateSelectionView,
  confirmCandidateSelection,
  profileConnectionStatus: profileConnectionStatusValue,
} = window.atrWindowsEquipmentSelection;
let latestProofPackagePath = "";
let selectedBridgeUrl = "";
let latestUtmReadiness = {};
let latestUtmEvidenceAudit = {};
let latestUtmLiveValidation = {};
let latestRequestAudit = {};
let latestProofVerification = {};
let latestCompletionAudit = {};
let latestVisionProofDraft = {};
let selectedEquipmentProfileId = "utm_windows_v1";

function renderEquipmentProfiles(payload) {
  const profiles = Array.isArray(payload && payload.profiles) ? payload.profiles : [];
  selectedEquipmentProfileId = String((payload && payload.selected_profile_id) || selectedEquipmentProfileId || "utm_windows_v1");
  if (!profileItems) return;
  profileItems.innerHTML = profiles.map((profile) => {
    const selected = profile.profile_id === selectedEquipmentProfileId;
    return `<button class="btn ${selected ? "primary" : ""}" data-equipment-profile="${profile.profile_id}">${profile.label} · ${profile.bridge_provider}</button>`;
  }).join("") || "No registered equipment profile.";
  profileItems.querySelectorAll("[data-equipment-profile]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedEquipmentProfileId = button.getAttribute("data-equipment-profile") || "utm_windows_v1";
      loadEquipmentProfileState().catch((err) => writeLog({ ok: false, error: err.message }));
    });
  });
}

async function loadEquipmentProfileState() {
  const [profiles, state] = await Promise.all([
    apiJson("/api/equipment/profiles"),
    apiJson(`/api/equipment/profiles/${encodeURIComponent(selectedEquipmentProfileId)}/state`),
  ]);
  renderEquipmentProfiles(profiles);
  const connection = state.connection || {};
  const readiness = state.readiness || {};
  if (profileConnectionStatus) {
    profileConnectionStatus.textContent = `profile=${state.profile?.label || "UTM"} · bridge=${profileConnectionStatusValue(connection)} · readiness=${readiness.status || "unknown"}`;
  }
  const evidence = state.evidence && typeof state.evidence === "object" ? state.evidence : {};
  if (profileEvidenceStatus) {
    profileEvidenceStatus.textContent = evidence.analysis_handoff?.status || evidence.status || "No profile test result yet.";
  }
  return state;
}

async function runEquipmentProfileAction(action, button) {
  setBusy(button, true);
  try {
    const data = await apiJson(`/api/equipment/profiles/${encodeURIComponent(selectedEquipmentProfileId)}/${action}`, {
      method: "POST",
      body: JSON.stringify(action === "test" ? { confirm_execute: true } : {}),
    });
    if (profileEvidenceStatus && action === "test") {
      profileEvidenceStatus.textContent = data.analysis_handoff?.status || data.status || "test completed";
    }
    writeLog(data);
    await loadEquipmentProfileState();
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(button, false);
  }
}

function proofGateRef(baseId) {
  return {
    card: document.getElementById(baseId),
    status: document.getElementById(`${baseId}-status`),
    detail: document.getElementById(`${baseId}-detail`),
  };
}

const proofGates = {
  windowsBridge: proofGateRef("equipment-gate-windows-bridge"),
  utmProgram: proofGateRef("equipment-gate-utm-program"),
  visionPreconditions: proofGateRef("equipment-gate-vision-preconditions"),
  screenState: proofGateRef("equipment-gate-screen-state"),
  physicalCrosscheck: proofGateRef("equipment-gate-physical-crosscheck"),
  dataArtifact: proofGateRef("equipment-gate-data-artifact"),
  analysisHandoff: proofGateRef("equipment-gate-analysis-handoff"),
};

function setProofGate(key, status, detail, kind = "idle") {
  const gate = proofGates[key];
  if (!gate || !gate.card) return;
  const normalized = ["ready", "warning", "blocked", "idle"].includes(kind) ? kind : "idle";
  gate.card.classList.remove("ready", "warning", "blocked", "idle");
  gate.card.classList.add(normalized);
  if (gate.status) gate.status.textContent = status || "not checked";
  if (gate.detail) gate.detail.textContent = detail || "No evidence loaded yet.";
}

function checklistOk(audit, id) {
  const checklist = audit && Array.isArray(audit.proof_checklist) ? audit.proof_checklist : [];
  return checklist.some((item) => item && item.id === id && item.ok === true);
}

function hasAnyGateValues(gates) {
  return gates && typeof gates === "object" && Object.keys(gates).length > 0;
}

function updateProofDashboard() {
  const readiness = latestUtmReadiness && typeof latestUtmReadiness === "object" ? latestUtmReadiness : {};
  const readinessGates = readiness.gates && typeof readiness.gates === "object" ? readiness.gates : {};
  const evidence = latestUtmEvidenceAudit && typeof latestUtmEvidenceAudit === "object" ? latestUtmEvidenceAudit : {};
  const evidenceGates = evidence.gates && typeof evidence.gates === "object" ? evidence.gates : {};
  const requestAudit = Object.keys(latestRequestAudit || {}).length
    ? latestRequestAudit
    : evidence.request_audit_log && typeof evidence.request_audit_log === "object"
      ? evidence.request_audit_log
      : {};
  const blockers = Array.isArray(evidence.blockers) ? evidence.blockers.filter(Boolean) : [];
  const warnings = Array.isArray(evidence.warnings) ? evidence.warnings.filter(Boolean) : [];
  const readinessKnown = hasAnyGateValues(readinessGates);
  const evidenceKnown = hasAnyGateValues(evidenceGates);

  const bridgeOk = Boolean(readinessGates.connection_saved && readinessGates.token_configured);
  const requestSeen = Boolean(requestAudit.execute_event_seen);
  const requestIdentity = requestAudit.execute_identity_match === false ? "identity mismatch" : requestSeen ? "execute logged" : "execute not seen";
  setProofGate(
    "windowsBridge",
    bridgeOk ? "ready" : readinessKnown || selectedBridgeUrl ? "blocked" : "not checked",
    `candidate=${readinessGates.connection_saved ? "saved" : selectedBridgeUrl ? "selected" : "missing"} · token=${readinessGates.token_configured ? "set" : "missing"} · request=${requestIdentity}`,
    bridgeOk ? "ready" : readinessKnown || selectedBridgeUrl ? "blocked" : "idle"
  );

  const programOk = Boolean(readinessGates.utm_program_registered && readinessGates.export_glob_configured);
  const locatorOk = readinessGates.require_screen_assertions ? Boolean(readinessGates.required_locators_complete) : Boolean(readinessGates.locator_count || !readinessGates.require_screen_assertions);
  const setupOk = Boolean(programOk && locatorOk);
  const missingLocators = Array.isArray(readinessGates.missing_required_locators) ? readinessGates.missing_required_locators.filter(Boolean) : [];
  setProofGate(
    "utmProgram",
    setupOk ? "ready" : readinessKnown ? "blocked" : "not checked",
    `program=${readinessGates.utm_program_registered ? "registered" : "missing"} · export_glob=${readinessGates.export_glob_configured ? "set" : "missing"} · locators=${missingLocators.length ? missingLocators.join(", ") : "ready/optional"}`,
    setupOk ? "ready" : readinessKnown ? "blocked" : "idle"
  );

  const visionOk = Boolean(evidenceGates.vision_evidence_complete || checklistOk(evidence, "vision_evidence_frames"));
  setProofGate(
    "visionPreconditions",
    visionOk ? "ready" : evidenceKnown ? "blocked" : "waiting",
    visionOk ? "Fixture, robot-clear, and frame evidence are attached." : "Need Vision frame evidence for fixture, motion, and completion states.",
    visionOk ? "ready" : evidenceKnown ? "blocked" : "idle"
  );

  const screenOk = Boolean(evidenceGates.screen_evidence_complete || checklistOk(evidence, "screen_evidence"));
  const screenRefs = Array.isArray(evidence.screen_evidence_refs) ? evidence.screen_evidence_refs.length : 0;
  setProofGate(
    "screenState",
    screenOk ? "ready" : evidenceKnown ? "blocked" : "waiting",
    `screen_refs=${screenRefs} · required=before_start/after_start/after_complete`,
    screenOk ? "ready" : evidenceKnown ? "blocked" : "idle"
  );

  const physicalOk = Boolean(evidenceGates.physical_motion_started || checklistOk(evidence, "physical_motion"));
  setProofGate(
    "physicalCrosscheck",
    physicalOk ? "ready" : evidenceKnown ? "blocked" : "waiting",
    physicalOk ? "UTM motion is confirmed beyond the click event." : "Start-click success is insufficient; motion or force/displacement change must be confirmed.",
    physicalOk ? "ready" : evidenceKnown ? "blocked" : "idle"
  );

  const linuxPulled = Boolean(evidenceGates.linux_artifact_pulled || checklistOk(evidence, "linux_artifact_pull"));
  const saveOk = Boolean(evidenceGates.save_export_responsibility_ok || checklistOk(evidence, "save_export_responsibility"));
  const parseOk = Boolean(evidenceGates.data_parse_probe_ok || checklistOk(evidence, "data_parse_probe"));
  const dataOk = Boolean(linuxPulled && saveOk && parseOk);
  const dataRefs = Array.isArray(evidence.data_evidence_refs) ? evidence.data_evidence_refs.length : 0;
  setProofGate(
    "dataArtifact",
    dataOk ? "ready" : evidenceKnown ? "blocked" : "waiting",
    `linux_pull=${linuxPulled ? "ok" : "missing"} · save_export=${saveOk ? "ok" : "missing"} · parse=${parseOk ? "ok" : "missing"} · data_refs=${dataRefs}`,
    dataOk ? "ready" : evidenceKnown ? "blocked" : "idle"
  );

  const proofReady = Boolean(evidence.proof_ready);
  const readyForAnalysis = proofReady && String(evidence.status || "") === "ready_for_analysis";
  const verifyStatus = String(latestProofVerification.status || "");
  const completionStatus = String(latestCompletionAudit.status || "");
  const detail = completionStatus === "complete_evidence_verified"
    ? "Completion audit verified the real UTM proof package."
    : completionStatus === "incomplete"
      ? `completion_audit=incomplete: ${(Array.isArray(latestCompletionAudit.blockers) ? latestCompletionAudit.blockers : []).slice(0, 3).join(", ") || "proof missing"}`
      : readyForAnalysis
    ? "All required proof gates are closed. Analysis handoff can proceed."
    : blockers.length
      ? `blocked=${blockers.slice(0, 3).join(", ")}`
      : warnings.length
        ? `warnings=${warnings.slice(0, 3).join(", ")}`
        : verifyStatus
          ? `proof_verification=${verifyStatus}`
          : "Proof package is not ready for Analysis.";
  setProofGate(
    "analysisHandoff",
    readyForAnalysis ? "ready_for_analysis" : evidenceKnown ? "blocked" : "waiting",
    detail,
    readyForAnalysis ? "ready" : evidenceKnown ? "blocked" : "idle"
  );
}

function setActionStatus(label, detail = "", kind = "idle") {
  const normalizedKind = kind === "ok" ? "ok" : kind === "blocked" || kind === "error" ? "blocked" : kind === "working" ? "working" : "idle";
  if (actionDot) {
    actionDot.className = `status-dot ${normalizedKind === "ok" ? "running" : normalizedKind === "blocked" ? "error" : normalizedKind === "working" ? "running" : "idle"}`;
  }
  if (actionLabel) actionLabel.textContent = label || "Idle";
  if (actionDetail) actionDetail.textContent = detail || "Ready for Windows bridge operation.";
  if (commandBanner) {
    commandBanner.className = `equipment-command-banner ${normalizedKind === "ok" ? "ok" : normalizedKind === "blocked" ? "blocked" : normalizedKind === "working" ? "working" : ""}`.trim();
  }
  if (commandTitle) commandTitle.textContent = label || "Ready for Windows bridge setup";
  if (commandDetail) commandDetail.textContent = detail || "Scan and save a token-verified Windows PC, then run readiness, preflight, simulation, and evidence checks.";
  if (commandPill) {
    commandPill.className = `badge ${normalizedKind === "ok" ? "running" : normalizedKind === "blocked" ? "warning" : "idle"}`;
    commandPill.textContent = normalizedKind;
  }
}

function setBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
  button.textContent = busy ? "Working..." : button.dataset.originalText || button.textContent;
  document.querySelectorAll(`[data-equipment-proxy="${button.id}"]`).forEach((proxy) => {
    proxy.disabled = busy;
    proxy.classList.toggle("is-working", busy);
  });
}

function rememberButtonLabels() {
  [btnScan, btnRefresh, btnTest, btnProgram1, btnUtm, btnAbort, btnScreenshot, btnListLocators, btnCaptureLocator, btnLoadUtmProfile, btnSaveUtmProfile, btnOpenBridgeGui, btnLocalStart, btnLocalStop, btnLocalHealth, btnLocalSelect, btnReadiness, btnLivePreflight, btnLiveValidation, btnVisionProofDraft, btnLivePhysicalValidation, btnEvidenceAudit, btnProofPackage, btnVerifyProofPackage, btnCompletionAudit, btnRequestLog].forEach((button) => {
    if (button && !button.dataset.originalText) {
      button.dataset.originalText = button.textContent;
    }
  });
}

function writeLog(data) {
  if (resultLog) {
    resultLog.textContent = JSON.stringify(data, null, 2);
  }
  const payload = data && typeof data === "object" ? data : {};
  const ok = payload.ok === true;
  const status = String(payload.status || (ok ? "ok" : payload.error ? "failed" : "updated"));
  const tool = String(payload.tool || payload.failure_code || payload.error || "Windows bridge action");
  setActionStatus(status, tool, ok ? "ok" : status === "blocked" || status === "failed" ? "blocked" : "idle");
}

function renderRequestAudit(audit) {
  if (!requestAuditStatus || !requestAuditDetail) return;
  const data = audit && typeof audit === "object" ? audit : {};
  latestRequestAudit = data;
  const ok = data.ok === true;
  const status = String(data.status || (ok ? "ready" : "missing"));
  const path = String(data.request_log || data.path || "");
  const events = Array.isArray(data.events) ? data.events : [];
  const explicitRecentPaths = Array.isArray(data.recent_paths) ? data.recent_paths.map((item) => String(item || "")).filter(Boolean) : [];
  const recentPaths = (explicitRecentPaths.length ? explicitRecentPaths : events
    .map((event) => event && typeof event === "object" ? String(event.path || "") : "")
    .filter(Boolean))
    .slice(-5);
  const executeEventSeen = data.execute_event_seen === true || recentPaths.some((path) => path === "/execute" || path.endsWith("/execute"));
  if (requestAuditCard) {
    requestAuditCard.classList.remove("ready", "warning", "blocked");
    requestAuditCard.classList.add(ok ? "ready" : status === "blocked" || data.failure_code ? "blocked" : "warning");
  }
  requestAuditStatus.textContent = `Bridge request audit: ${status} · events=${data.event_count || events.length || 0} · execute=${executeEventSeen ? "seen" : "missing"}`;
  const pathText = path ? `log=${path}` : "log path unavailable";
  const recentText = recentPaths.length ? `recent=${recentPaths.join(" -> ")}` : "recent requests not loaded";
  requestAuditDetail.textContent = `${pathText} · ${recentText}`;
  updateProofDashboard();
}

function renderUtmEvidenceAudit(audit) {
  if (!utmEvidenceStatus || !utmEvidenceDetail) return;
  const data = audit && typeof audit === "object" ? audit : {};
  latestUtmEvidenceAudit = data;
  const status = String(data.status || "missing");
  const blockers = Array.isArray(data.blockers) ? data.blockers.filter(Boolean) : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
  const gates = data.gates && typeof data.gates === "object" ? data.gates : {};
  if (utmEvidenceCard) {
    utmEvidenceCard.classList.remove("ready", "warning", "blocked");
    utmEvidenceCard.classList.add(status === "ready_for_analysis" ? "ready" : warnings.length && !blockers.length ? "warning" : "blocked");
  }
  utmEvidenceStatus.textContent = `UTM evidence audit: ${status}`;
  const requestLog = data.request_audit_log && typeof data.request_audit_log === "object" ? data.request_audit_log : {};
  const requestLogLabel = gates.request_audit_log_available
    ? requestLog.execute_event_seen === true ? "execute-ok" : "attached"
    : "missing";
  const gateText = [
    `screen=${gates.screen_evidence_complete ? "complete" : "missing"}`,
    `linux_pull=${gates.linux_artifact_pulled ? "ok" : "missing"}`,
    `save_export=${gates.save_export_responsibility_ok ? "ok" : "missing"}`,
    `vision_frames=${gates.vision_evidence_complete ? "ok" : "missing"}`,
    `request_log=${requestLogLabel}`,
    `parse=${gates.data_parse_probe_ok ? "ok" : "missing"}`,
  ].join(" · ");
  const issueText = blockers.length ? `Blockers: ${blockers.join(", ")}` : warnings.length ? `Warnings: ${warnings.join(", ")}` : "Ready for Analysis handoff.";
  const checklist = Array.isArray(data.proof_checklist) ? data.proof_checklist : [];
  const requiredOpen = checklist.filter((item) => item && item.required !== false && item.ok !== true);
  const proofText = checklist.length
    ? `proof=${data.proof_ready === true ? "ready" : `open:${requiredOpen.map((item) => item.id || item.label || "proof").join("|") || "unknown"}`}`
    : "proof=not-loaded";
  utmEvidenceDetail.textContent = `${gateText} · ${proofText} · ${issueText}`;
  if (utmProofChecklist) {
    if (!checklist.length) {
      utmProofChecklist.textContent = "Proof checklist not loaded.";
    } else {
      utmProofChecklist.textContent = checklist
        .map((item) => `${item.ok === true ? "OK" : item.required === false ? "WARN" : "OPEN"} ${item.label || item.id}: ${item.detail || ""}`)
        .join(" · ");
    }
  }
  if (data.request_audit_log && typeof data.request_audit_log === "object") {
    latestRequestAudit = data.request_audit_log;
  }
  updateProofDashboard();
}


function renderUtmLiveValidation(report) {
  if (!utmLiveValidationStatus || !utmLiveValidationDetail) return;
  const data = report && typeof report === "object" ? report : {};
  latestUtmLiveValidation = data;
  const status = String(data.status || "not_built");
  const blockers = Array.isArray(data.blockers) ? data.blockers.filter(Boolean) : [];
  const gates = Array.isArray(data.gates) ? data.gates : [];
  const summary = data.summary && typeof data.summary === "object" ? data.summary : {};
  const artifact = data.report_artifact && typeof data.report_artifact === "object" ? data.report_artifact : data.artifact && typeof data.artifact === "object" ? data.artifact : {};
  if (utmLiveValidationCard) {
    utmLiveValidationCard.classList.remove("ready", "warning", "blocked");
    utmLiveValidationCard.classList.add(data.ok === true ? "ready" : blockers.length ? "blocked" : "warning");
  }
  const passed = Number(summary.passed_required_gate_count || gates.filter((item) => item && item.required !== false && item.ok === true).length || 0);
  const required = Number(summary.required_gate_count || gates.filter((item) => item && item.required !== false).length || 0);
  utmLiveValidationStatus.textContent = `UTM live validation: ${status} · gates=${passed}/${required}`;
  const blockerText = blockers.length
    ? `Blockers: ${blockers.map((item) => item.name || item.failure_code || item.detail || "gate").join(", ")}`
    : data.ok === true
      ? "Live bridge is ready for a physical run decision. /execute was not sent."
      : "Build the non-actuating report before physical UTM execution.";
  const artifactText = artifact.path ? `report=${artifact.path}` : "report artifact not saved yet";
  utmLiveValidationDetail.textContent = `${blockerText} · ${artifactText}`;
  if (utmLiveValidationGates) {
    utmLiveValidationGates.textContent = gates.length
      ? gates.map((item) => `${item.ok === true ? "OK" : item.required === false ? "INFO" : "OPEN"} ${item.name || "gate"}: ${item.detail || ""}`).join(" · ")
      : "Validation gates not loaded.";
  }
  if (data.request_audit_log && typeof data.request_audit_log === "object") {
    renderRequestAudit(data.request_audit_log);
  }
}


function renderProofPackageVerification(verification) {
  if (!proofVerifyStatus || !proofVerifyDetail) return;
  const data = verification && typeof verification === "object" ? verification : {};
  latestProofVerification = data;
  const status = String(data.status || "not_run");
  const blockers = Array.isArray(data.blockers) ? data.blockers.filter(Boolean) : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
  const checks = Array.isArray(data.checks) ? data.checks : [];
  if (proofVerifyCard) {
    proofVerifyCard.classList.remove("ready", "warning", "blocked");
    proofVerifyCard.classList.add(status === "verified" ? "ready" : blockers.length ? "blocked" : warnings.length ? "warning" : "warning");
  }
  proofVerifyStatus.textContent = `Proof package verification: ${status}`;
  const checkText = checks.length ? `checks=${checks.filter((item) => item && item.status === "ok").length}/${checks.length}` : "checks=not-run";
  const issueText = blockers.length ? `Blockers: ${blockers.join(", ")}` : warnings.length ? `Warnings: ${warnings.join(", ")}` : "Persisted proof package is file-checkable.";
  const csvProbe = data.csv_probe && typeof data.csv_probe === "object" ? data.csv_probe : {};
  const csvText = csvProbe.path ? `csv=${csvProbe.path} rows=${csvProbe.row_count || 0}` : "csv=not-probed";
  proofVerifyDetail.textContent = `${checkText} · ${csvText} · ${issueText}`;
  updateProofDashboard();
}

function renderCompletionAudit(audit) {
  if (!completionAuditStatus || !completionAuditDetail) return;
  const data = audit && typeof audit === "object" ? audit : {};
  latestCompletionAudit = data;
  const status = String(data.status || "not_run");
  const blockers = Array.isArray(data.blockers) ? data.blockers.filter(Boolean) : [];
  const verification = data.verification && typeof data.verification === "object" ? data.verification : {};
  const artifact = data.audit_artifact && typeof data.audit_artifact === "object" ? data.audit_artifact : {};
  const proofPath = String(data.proof_package_path || (verification.load_info && verification.load_info.path) || "");
  if (completionAuditCard) {
    completionAuditCard.classList.remove("ready", "warning", "blocked");
    completionAuditCard.classList.add(status === "complete_evidence_verified" ? "ready" : blockers.length ? "blocked" : "warning");
  }
  completionAuditStatus.textContent = `Improvement 05 completion audit: ${status}`;
  const verificationText = verification.status ? `proof_verify=${verification.status}` : "proof_verify=not-run";
  const blockerText = blockers.length ? `Blockers: ${blockers.join(", ")}` : status === "complete_evidence_verified" ? "Real UTM proof package satisfies every required gate." : "Run after a real physical UTM proof package is built.";
  const artifactText = artifact.path ? `audit=${artifact.path}` : "audit=not-saved";
  completionAuditDetail.textContent = `${verificationText} · ${proofPath ? `proof_package=${proofPath}` : "proof_package=runtime/latest"} · ${artifactText} · ${blockerText}`;
  if (verification && Object.keys(verification).length) {
    latestProofVerification = verification;
  }
  updateProofDashboard();
}

function renderUtmReadiness(readiness) {
  if (!utmReadinessStatus || !utmReadinessDetail) return;
  const data = readiness && typeof readiness === "object" ? readiness : {};
  latestUtmReadiness = data;
  const status = String(data.status || "unknown");
  const blockers = Array.isArray(data.blockers) ? data.blockers.filter(Boolean) : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
  const gates = data.gates && typeof data.gates === "object" ? data.gates : {};
  if (utmReadinessCard) {
    utmReadinessCard.classList.remove("ready", "warning", "blocked");
    utmReadinessCard.classList.add(status === "ready" ? "ready" : status === "warning" ? "warning" : "blocked");
  }
  utmReadinessStatus.textContent = `UTM readiness: ${status}`;
  const missingLocators = Array.isArray(gates.missing_required_locators) ? gates.missing_required_locators.filter(Boolean) : [];
  const requiredLocators = Array.isArray(gates.required_locator_names) ? gates.required_locator_names.filter(Boolean) : [];
  const gateText = [
    `bridge=${gates.connection_saved ? "saved" : "missing"}`,
    `token=${gates.token_configured ? "set" : "missing"}`,
    `program=${gates.utm_program_registered ? "registered" : "missing"}`,
    `locators=${Number(gates.locator_count || 0)}/${requiredLocators.length || "?"}`,
    `required=${gates.required_locators_complete ? "complete" : missingLocators.length ? missingLocators.join("|") : "unknown"}`,
    `screen=${gates.require_screen_assertions ? "required" : "not-required"}`,
    `simulate=${gates.simulate_utm_protocol ? "on" : "off"}`,
  ].join(" · ");
  const locatorText = missingLocators.length ? `Missing locators: ${missingLocators.join(", ")}` : "Required locators complete.";
  const issueText = blockers.length ? `Blockers: ${blockers.join(", ")}` : warnings.length ? `Warnings: ${warnings.join(", ")}` : "Ready for screen-asserted autonomous UTM profile.";
  utmReadinessDetail.textContent = `${gateText} · ${locatorText} · ${issueText}`;
  updateProofDashboard();
}

function setConnectionStatus(connection) {
  const selected = Boolean(connection && connection.selected);
  selectedBridgeUrl = selected && connection && connection.bridge_url ? String(connection.bridge_url) : "";
  if (connectionDot) {
    connectionDot.className = `status-dot ${selected ? "running" : "idle"}`;
  }
  if (connectionLabel) {
    const alias = connection && connection.selected_candidate ? `${connection.selected_candidate} · ` : "";
    connectionLabel.textContent = selected ? `${alias}${connection.bridge_url}` : "No PyAutoGUI bridge candidate selected";
  }
  if (connectionDetail) {
    const tokenText = connection && connection.token_configured ? "token configured" : "token missing";
    const memoryPath = connection && connection.connection_memory_path ? connection.connection_memory_path : "memory/windows_pyautogui_connection.json";
    const candidateCount = connection && Array.isArray(connection.candidates) ? `${connection.candidates.length} candidate(s)` : "0 candidates";
    connectionDetail.textContent = `${tokenText} · ${candidateCount} · ${memoryPath}`;
  }
  renderSavedCandidates(connection && Array.isArray(connection.candidates) ? connection.candidates : []);
  updateProofDashboard();
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = data && data.detail;
    throw new Error((detail && typeof detail === "object" ? detail.message || detail.failure_code : detail) || data.message || `HTTP ${response.status}`);
  }
  return data;
}

function renderLocalBridgeStatus(payload) {
  const data = payload && typeof payload === "object" ? payload : {};
  const running = data.running === true;
  const healthy = data.healthy === true;
  const connection = data.connection && typeof data.connection === "object" ? data.connection : {};
  const selected = connection.selected_candidate === "local_development";
  const pyautogui = data.health && data.health.pyautogui && data.health.pyautogui.available === true;
  if (localBridgeDot) localBridgeDot.className = `status-dot ${healthy ? "running" : running ? "warning" : "idle"}`;
  if (localBridgeStatus) localBridgeStatus.textContent = healthy ? "Ready" : running ? "Running · desktop control unavailable" : "Stopped";
  if (localBridgeDetail) {
    localBridgeDetail.textContent = `localhost:8767 · ${pyautogui ? "PyAutoGUI ready" : "PyAutoGUI not ready"} · ${selected ? "selected" : "standby"}`;
  }
  if (btnLocalStart) btnLocalStart.disabled = running;
  if (btnLocalStop) btnLocalStop.disabled = !running;
  if (btnLocalSelect) btnLocalSelect.disabled = !healthy || selected;
}

function setLocalBridgeBusy(busy) {
  [btnLocalStart, btnLocalStop, btnLocalHealth, btnLocalSelect].forEach((button) => setBusy(button, busy));
}

async function refreshLocalBridgeStatus() {
  const data = await apiJson("/api/equipment/windows/local-bridge/status");
  renderLocalBridgeStatus(data);
  return data;
}

async function runLocalBridgeAction(action) {
  setLocalBridgeBusy(true);
  try {
    const data = action === "health"
      ? await apiJson("/api/equipment/windows/local-bridge/status")
      : await apiJson(`/api/equipment/windows/local-bridge/${action}`, { method: "POST", body: "{}" });
    writeLog(data);
    await refreshConfig();
    await refreshLocalBridgeStatus();
  } catch (err) {
    writeLog({ ok: false, status: "blocked", error: err.message });
    await refreshLocalBridgeStatus().catch(() => {});
  } finally {
    setLocalBridgeBusy(false);
    await refreshLocalBridgeStatus().catch(() => {});
  }
}

async function refreshConfig(options = {}) {
  const logResult = !(options && options.logResult === false);
  const data = await apiJson("/api/equipment/windows/config");
  setConnectionStatus(data.connection || {});
  hydrateUtmProfile(data.utm_profile || {});
  renderUtmReadiness(data.utm_readiness || {});
  renderUtmEvidenceAudit(data.utm_evidence_audit || {});
  renderUtmLiveValidation(data.utm_live_validation || {});
  renderCompletionAudit(data.utm_completion_audit || {});
  latestVisionProofDraft = data.utm_vision_proof_draft && typeof data.utm_vision_proof_draft === "object" ? data.utm_vision_proof_draft : {};
  renderRequestAudit(data.request_audit || {});
  if (logResult) writeLog(data);
  return data;
}

function renderCandidates(candidates) {
  if (!candidatesEl) return;
  if (!Array.isArray(candidates) || candidates.length === 0) {
    candidatesEl.textContent = "No token-verified Windows bridge candidates found.";
    return;
  }
  candidatesEl.innerHTML = "";
  candidates.forEach((candidate) => {
    const card = document.createElement("div");
    card.className = "equipment-candidate-card";
    const status = candidate.token_verified ? "token verified" : candidate.status || "ready";
    const pyautogui = candidate.pyautogui && candidate.pyautogui.available === false ? "PyAutoGUI missing" : "PyAutoGUI ready/unknown";
    card.innerHTML = `
      <div>
        <strong>${candidate.bridge_url}</strong>
        <p class="hint">${status} · ${pyautogui}</p>
      </div>
      <div class="equipment-candidate-save">
        <input class="text-input equipment-alias-input" placeholder="candidate alias" />
        <button class="btn mini">Save</button>
      </div>
    `;
    const button = card.querySelector("button");
    const input = card.querySelector("input");
    if (input && candidate.host) {
      input.value = `windows_${String(candidate.host).replace(/[^a-zA-Z0-9_.-]/g, "_")}`;
    }
    button.addEventListener("click", () => saveCandidate(candidate, input ? input.value : ""));
    candidatesEl.appendChild(card);
  });
}

function renderSavedCandidates(candidates) {
  if (!savedCandidatesEl) return;
  if (!Array.isArray(candidates) || candidates.length === 0) {
    savedCandidatesEl.textContent = "No saved PyAutoGUI bridge candidate.";
    return;
  }
  savedCandidatesEl.innerHTML = "";
  candidates.forEach((candidate) => {
    const card = document.createElement("div");
    const view = candidateSelectionView(candidate);
    card.className = view.cardClass;
    if (view.ariaCurrent) card.setAttribute("aria-current", view.ariaCurrent);
    const selected = view.selected ? "selected" : "standby";
    const target = candidate.managed_local ? "local managed" : `${candidate.platform || "windows"} · ${candidate.scope || "network"}`;
    card.innerHTML = `
      <div>
        <strong>${candidate.candidate_alias}</strong>
        <p class="hint">${candidate.bridge_url} · ${target} · ${selected} · ${candidate.allow_live_execute ? "live enabled" : "live blocked"}</p>
      </div>
      <div class="button-row">
        <button class="${view.buttonClass}" data-action="select" aria-pressed="${view.ariaPressed}">${view.buttonText}</button>
        <button class="btn mini danger" data-action="delete">Delete</button>
      </div>
    `;
    const selectButton = card.querySelector('[data-action="select"]');
    const deleteButton = card.querySelector('[data-action="delete"]');
    selectButton.disabled = view.buttonDisabled;
    selectButton.addEventListener("click", () => selectSavedCandidate(candidate.candidate_alias, selectButton));
    deleteButton.addEventListener("click", () => deleteSavedCandidate(candidate.candidate_alias));
    savedCandidatesEl.appendChild(card);
  });
}

async function scanNetwork() {
  const token = tokenInput ? tokenInput.value.trim() : "";
  if (!token) {
    writeLog({ ok: false, failure_code: "PYAUTOGUI_TOKEN_REQUIRED", message: "Enter token before scanning." });
    return;
  }
  setBusy(btnScan, true);
  try {
    const data = await apiJson("/api/equipment/windows/discover", {
      method: "POST",
      body: JSON.stringify({
        subnet: subnetInput ? subnetInput.value.trim() : "",
        port: Number(portInput ? portInput.value : 8765) || 8765,
        token,
      }),
    });
    renderCandidates(data.candidates || []);
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnScan, false);
  }
}

async function saveCandidate(candidate, aliasValue) {
  const token = tokenInput ? tokenInput.value.trim() : "";
  if (!token) {
    writeLog({ ok: false, failure_code: "PYAUTOGUI_TOKEN_REQUIRED", message: "Enter token before saving a candidate." });
    return;
  }
  let candidateAlias = String(aliasValue || "").trim();
  if (!candidateAlias) {
    const host = String(candidate.host || "windows").replace(/[^a-zA-Z0-9_.-]/g, "_");
    candidateAlias = window.prompt("Save this bridge candidate as:", `windows_${host}`) || "";
  }
  candidateAlias = candidateAlias.trim();
  if (!candidateAlias) {
    writeLog({ ok: false, failure_code: "PYAUTOGUI_CANDIDATE_ALIAS_REQUIRED", message: "Candidate alias is required." });
    return;
  }
  const data = await apiJson("/api/equipment/windows/connect", {
    method: "POST",
    body: JSON.stringify({
      candidate_alias: candidateAlias,
      host: candidate.host || "",
      bridge_url: candidate.bridge_url,
      port: candidate.port || Number(portInput ? portInput.value : 8765) || 8765,
      token,
      allow_live_execute: true,
    }),
  });
  setConnectionStatus(data);
  writeLog(data);
}

async function selectSavedCandidate(candidateAlias, button = null) {
  if (button) {
    button.disabled = true;
    button.textContent = "Selecting...";
  }
  try {
    const data = await apiJson("/api/equipment/windows/select", {
      method: "POST",
      body: JSON.stringify({ candidate_alias: candidateAlias }),
    });
    confirmCandidateSelection(data, candidateAlias);
    setConnectionStatus(data);
    writeLog(data);
    setActionStatus("Bridge selected", `${candidateAlias} · ${data.bridge_url || "saved candidate"}`, "ok");
    await Promise.all([
      refreshConfig({ logResult: false }),
      loadEquipmentProfileState(),
    ]);
  } catch (err) {
    writeLog({
      ok: false,
      status: "failed",
      failure_code: "PYAUTOGUI_CANDIDATE_SELECTION_FAILED",
      message: err.message,
    });
  } finally {
    if (button && button.isConnected && !button.closest(".equipment-candidate-card.selected")) {
      button.disabled = false;
      button.textContent = "Select";
    }
  }
}

async function deleteSavedCandidate(candidateAlias) {
  const confirmed = window.confirm(`Delete saved PyAutoGUI bridge candidate "${candidateAlias}"?`);
  if (!confirmed) return;
  const data = await apiJson("/api/equipment/windows/delete", {
    method: "POST",
    body: JSON.stringify({ candidate_alias: candidateAlias }),
  });
  setConnectionStatus(data);
  writeLog(data);
}

async function testSelected() {
  setBusy(btnTest, true);
  try {
    const data = await apiJson("/api/equipment/windows/test", { method: "POST", body: "{}" });
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnTest, false);
  }
}

async function runProgram1() {
  const confirmed = window.confirm("program1 demo will briefly move the mouse on the selected Windows PC. Continue?");
  if (!confirmed) return;
  setBusy(btnProgram1, true);
  try {
    const data = await apiJson("/api/equipment/windows/run-program", {
      method: "POST",
      body: JSON.stringify({ program_id: "program1", command: "program1 실행", confirm_execute: true }),
    });
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnProgram1, false);
  }
}

function parseOptionalJson(text, label) {
  const raw = String(text || "").trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`${label} must be a JSON object.`);
    }
    return parsed;
  } catch (err) {
    throw new Error(`${label} JSON parse failed: ${err.message}`);
  }
}

function mergeLocatorOverride(locatorName, locator) {
  if (!utmLocatorsInput || !locatorName || !locator || typeof locator !== "object") return;
  const current = parseOptionalJson(utmLocatorsInput.value, "Locator override");
  current[locatorName] = locator;
  utmLocatorsInput.value = JSON.stringify(current, null, 2);
}

function collectUtmProfilePayload() {
  const locators = parseOptionalJson(utmLocatorsInput ? utmLocatorsInput.value : "", "Locator override");
  const targetWindow = utmTargetWindowInput ? utmTargetWindowInput.value.trim() : "";
  const payload = {
    program_id: locatorProgramInput ? locatorProgramInput.value.trim() || "utm_compression_start_v1" : "utm_compression_start_v1",
    require_window_focus: Boolean(utmRequireFocusInput && utmRequireFocusInput.checked),
    manual_save_required_if_no_artifact: !utmManualSaveInput || utmManualSaveInput.checked,
    require_screen_assertions: Boolean(utmRequireScreenInput && utmRequireScreenInput.checked),
    simulate_utm_protocol: Boolean(utmSimulateInput && utmSimulateInput.checked),
    export_glob: utmExportGlobInput ? utmExportGlobInput.value.trim() || "*.csv" : "*.csv",
    artifact_timeout_s: Number(utmTimeoutInput ? utmTimeoutInput.value : 60) || 60,
    stable_for_sec: Number(utmStableInput ? utmStableInput.value : 2.0) || 2.0,
    expected_export_path: utmExpectedExportPathInput ? utmExpectedExportPathInput.value.trim() : "",
    locators,
  };
  if (targetWindow) {
    if (targetWindow.startsWith("regex:")) payload.target_window_regex = targetWindow.slice(6).trim();
    else payload.target_window = targetWindow;
  }
  return payload;
}

function hydrateUtmProfile(data) {
  const profile = data && data.profile && typeof data.profile === "object" ? data.profile : data;
  if (!profile || typeof profile !== "object") return;
  if (locatorProgramInput && profile.program_id) locatorProgramInput.value = profile.program_id;
  if (utmExportGlobInput && profile.export_glob) utmExportGlobInput.value = profile.export_glob;
  if (utmTimeoutInput && profile.artifact_timeout_s) utmTimeoutInput.value = profile.artifact_timeout_s;
  if (utmStableInput && profile.stable_for_sec) utmStableInput.value = profile.stable_for_sec;
  if (utmExpectedExportPathInput && profile.expected_export_path) utmExpectedExportPathInput.value = profile.expected_export_path;
  if (utmTargetWindowInput) {
    if (profile.target_window_regex) utmTargetWindowInput.value = `regex:${profile.target_window_regex}`;
    else if (profile.target_window) utmTargetWindowInput.value = profile.target_window;
  }
  if (utmRequireFocusInput && Object.prototype.hasOwnProperty.call(profile, "require_window_focus")) {
    utmRequireFocusInput.checked = Boolean(profile.require_window_focus);
  }
  if (utmManualSaveInput && Object.prototype.hasOwnProperty.call(profile, "manual_save_required_if_no_artifact")) {
    utmManualSaveInput.checked = Boolean(profile.manual_save_required_if_no_artifact);
  }
  if (utmRequireScreenInput && Object.prototype.hasOwnProperty.call(profile, "require_screen_assertions")) {
    utmRequireScreenInput.checked = Boolean(profile.require_screen_assertions);
  }
  if (utmSimulateInput && Object.prototype.hasOwnProperty.call(profile, "simulate_utm_protocol")) {
    utmSimulateInput.checked = Boolean(profile.simulate_utm_protocol);
  }
  if (utmLocatorsInput && profile.locators && typeof profile.locators === "object") {
    utmLocatorsInput.value = JSON.stringify(profile.locators, null, 2);
  }
  if (utmProfileStatus) {
    const source = data && data.source ? data.source : "active";
    const path = data && data.profile_memory_path ? data.profile_memory_path : "memory/equipment_utm_profile.json";
    utmProfileStatus.textContent = `UTM profile ${source} · ${path}`;
  }
}

function openSelectedBridgeGui() {
  window.open("/equipment/windows/console", "_blank", "noopener,noreferrer");
  setActionStatus("Windows GUI opened", "Opened locally; bridge connectivity is checked only when a console action is requested.", "ok");
}

async function checkReadiness() {
  setBusy(btnReadiness, true);
  try {
    const data = await apiJson("/api/equipment/windows/readiness");
    renderUtmReadiness(data);
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnReadiness, false);
  }
}

async function checkEvidenceAudit() {
  setBusy(btnEvidenceAudit, true);
  try {
    const data = await apiJson("/api/equipment/windows/evidence-audit");
    renderUtmEvidenceAudit(data);
    if (data.request_audit_log) renderRequestAudit(data.request_audit_log);
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnEvidenceAudit, false);
  }
}

async function buildProofPackage() {
  setBusy(btnProofPackage, true);
  try {
    const data = await apiJson("/api/equipment/windows/proof-package");
    if (data.evidence_audit) renderUtmEvidenceAudit(data.evidence_audit);
    if (data.evidence_audit && data.evidence_audit.request_audit_log) renderRequestAudit(data.evidence_audit.request_audit_log);
    const artifact = data.package_artifact && typeof data.package_artifact === "object" ? data.package_artifact : {};
    if (artifact.path) {
      latestProofPackagePath = String(artifact.path);
      if (utmEvidenceDetail) utmEvidenceDetail.textContent = `${utmEvidenceDetail.textContent} · proof_package=${artifact.path}`;
      renderProofPackageVerification({ status: "ready_to_verify", warnings: ["PROOF_PACKAGE_VERIFY_NOT_RUN"], package_artifact: artifact });
    }
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnProofPackage, false);
  }
}

async function verifyProofPackage() {
  setBusy(btnVerifyProofPackage, true);
  try {
    const data = await apiJson("/api/equipment/windows/proof-package/verify", {
      method: "POST",
      body: JSON.stringify({ path: latestProofPackagePath, use_current: !latestProofPackagePath }),
    });
    renderProofPackageVerification(data);
    writeLog(data);
  } catch (err) {
    const data = { ok: false, status: "failed", failure_code: "PROOF_PACKAGE_VERIFY_REQUEST_FAILED", error: err.message };
    renderProofPackageVerification(data);
    writeLog(data);
  } finally {
    setBusy(btnVerifyProofPackage, false);
  }
}

async function runCompletionAudit() {
  setBusy(btnCompletionAudit, true);
  try {
    const data = await apiJson("/api/equipment/windows/completion-audit", {
      method: "POST",
      body: JSON.stringify({ path: latestProofPackagePath, use_current: !latestProofPackagePath, latest: !latestProofPackagePath }),
    });
    renderCompletionAudit(data);
    writeLog(data);
  } catch (err) {
    const data = { ok: false, status: "failed", failure_code: "COMPLETION_AUDIT_REQUEST_FAILED", error: err.message };
    renderCompletionAudit(data);
    writeLog(data);
  } finally {
    setBusy(btnCompletionAudit, false);
  }
}

async function checkRequestLog() {
  const confirmed = window.confirm("Load the live Windows bridge request log? This is non-actuating and does not start UTM motion.");
  if (!confirmed) return;
  setBusy(btnRequestLog, true);
  try {
    const data = await apiJson("/api/equipment/windows/request-log", {
      method: "POST",
      body: JSON.stringify({ runtime_mode: "live", confirm_live: true }),
    });
    renderRequestAudit(data);
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnRequestLog, false);
  }
}


async function runLivePreflight() {
  const includeScreenshot = Boolean(livePreflightScreenshotInput && livePreflightScreenshotInput.checked);
  const confirmed = window.confirm(
    includeScreenshot
      ? "Run live preflight without equipment motion and capture one Windows screenshot?"
      : "Run live preflight without equipment motion? This calls health, programs, and locator listing only."
  );
  if (!confirmed) return;
  setBusy(btnLivePreflight, true);
  try {
    const data = await apiJson("/api/equipment/windows/live-preflight", {
      method: "POST",
      body: JSON.stringify({ confirm_preflight: true, include_locators: true, include_screenshot: includeScreenshot, include_request_log: true }),
    });
    renderUtmReadiness({ ...(data.passive_readiness || {}), status: data.status, blockers: data.blockers || [], warnings: data.warnings || [] });
    renderRequestAudit(data.request_log || data.request_audit_log || {});
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnLivePreflight, false);
  }
}

function renderVisionProofDraft(data, { fillInput = false } = {}) {
  const draft = data && typeof data === "object" ? data : {};
  latestVisionProofDraft = draft;
  const proof = draft.vision_proof && typeof draft.vision_proof === "object" ? draft.vision_proof : {};
  if (fillInput && liveVisionProofInput && Object.keys(proof).length) {
    liveVisionProofInput.value = JSON.stringify(proof, null, 2);
  }
  if (utmLiveValidationGates && draft.status) {
    const blockers = Array.isArray(draft.blockers) ? draft.blockers.filter(Boolean) : [];
    const frames = proof.evidence && Array.isArray(proof.evidence.frame_ids) ? proof.evidence.frame_ids.length : 0;
    utmLiveValidationGates.textContent = `Vision proof draft: ${draft.status} · frames=${frames} · ${blockers.length ? `blockers=${blockers.join(", ")}` : "ready for operator review"}`;
  }
}

async function loadVisionProofDraft() {
  setBusy(btnVisionProofDraft, true);
  try {
    const data = await apiJson("/api/equipment/windows/vision-proof-draft", {
      method: "POST",
      body: "{}",
    });
    renderVisionProofDraft(data, { fillInput: true });
    writeLog(data);
  } catch (err) {
    const data = { ok: false, status: "failed", failure_code: "VISION_PROOF_DRAFT_REQUEST_FAILED", error: err.message };
    renderVisionProofDraft(data);
    writeLog(data);
  } finally {
    setBusy(btnVisionProofDraft, false);
  }
}

async function buildLiveValidationReport() {
  const includeScreenshot = Boolean(livePreflightScreenshotInput && livePreflightScreenshotInput.checked);
  const confirmed = window.confirm(
    includeScreenshot
      ? "Build a non-actuating live validation report and capture one Windows screenshot? /execute will not be sent."
      : "Build a non-actuating live validation report? This checks live health, programs, and request audit only."
  );
  if (!confirmed) return;
  setBusy(btnLiveValidation, true);
  try {
    const data = await apiJson("/api/equipment/windows/live-validation", {
      method: "POST",
      body: JSON.stringify(collectLiveValidationPayload({ physical: false })),
    });
    renderUtmLiveValidation(data);
    writeLog(data);
  } catch (err) {
    const data = { ok: false, status: "failed", failure_code: "LIVE_VALIDATION_REQUEST_FAILED", error: err.message };
    renderUtmLiveValidation(data);
    writeLog(data);
  } finally {
    setBusy(btnLiveValidation, false);
  }
}

function collectLiveValidationPayload({ physical = false } = {}) {
  const profile = collectUtmProfilePayload();
  const payload = {
    ...profile,
    program_id: profile.program_id || (locatorProgramInput ? locatorProgramInput.value.trim() || "utm_compression_start_v1" : "utm_compression_start_v1"),
    include_screenshot: Boolean(livePreflightScreenshotInput && livePreflightScreenshotInput.checked),
  };
  if (physical) {
    payload.confirm_live_execute = true;
    payload.confirm_physical_setup_safe = Boolean(livePhysicalSafeInput && livePhysicalSafeInput.checked);
    payload.command = "Run physical UTM validation protocol and export CSV";
    payload.vision_proof = parseOptionalJson(liveVisionProofInput ? liveVisionProofInput.value : "", "Vision proof");
  } else {
    payload.confirm_non_actuating = true;
  }
  return payload;
}

async function runPhysicalLiveValidation() {
  if (!livePhysicalSafeInput || !livePhysicalSafeInput.checked) {
    writeLog({ ok: false, status: "blocked", failure_code: "PHYSICAL_UTM_SETUP_CONFIRMATION_REQUIRED", message: "Check Physical UTM setup safe before running physical validation." });
    return;
  }
  const confirmed = window.confirm("This will send /execute to the selected Windows UTM bridge. Continue only if the real UTM fixture, specimen, Vision path, and operator safety state are ready.");
  if (!confirmed) return;
  setBusy(btnLivePhysicalValidation, true);
  try {
    const data = await apiJson("/api/equipment/windows/live-validation", {
      method: "POST",
      body: JSON.stringify(collectLiveValidationPayload({ physical: true })),
    });
    renderUtmLiveValidation(data);
    if (data.request_audit_log) renderRequestAudit(data.request_audit_log);
    writeLog(data);
  } catch (err) {
    const data = { ok: false, status: "failed", failure_code: "PHYSICAL_LIVE_VALIDATION_REQUEST_FAILED", error: err.message };
    renderUtmLiveValidation(data);
    writeLog(data);
  } finally {
    setBusy(btnLivePhysicalValidation, false);
  }
}

async function loadUtmProfile() {
  setBusy(btnLoadUtmProfile, true);
  try {
    const data = await apiJson("/api/equipment/windows/utm-profile");
    hydrateUtmProfile(data);
    await checkReadiness();
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnLoadUtmProfile, false);
  }
}

async function saveUtmProfile() {
  setBusy(btnSaveUtmProfile, true);
  try {
    const payload = collectUtmProfilePayload();
    const data = await apiJson("/api/equipment/windows/utm-profile", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    hydrateUtmProfile(data);
    await checkReadiness();
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnSaveUtmProfile, false);
  }
}

function locatorRegion() {
  return [
    Number(locatorXInput ? locatorXInput.value : 0),
    Number(locatorYInput ? locatorYInput.value : 0),
    Number(locatorWidthInput ? locatorWidthInput.value : 0),
    Number(locatorHeightInput ? locatorHeightInput.value : 0),
  ];
}

async function captureScreenshot() {
  const confirmed = window.confirm("Capture the current Windows bridge screen for UTM locator calibration?");
  if (!confirmed) return;
  setBusy(btnScreenshot, true);
  try {
    const data = await apiJson("/api/equipment/windows/screenshot", {
      method: "POST",
      body: JSON.stringify({ checkpoint: "manual_locator_calibration", run_id: "locator-calibration", confirm_capture: true }),
    });
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnScreenshot, false);
  }
}

async function listLocators() {
  setBusy(btnListLocators, true);
  try {
    const data = await apiJson("/api/equipment/windows/locators");
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnListLocators, false);
  }
}

async function captureLocator() {
  const name = locatorNameInput ? locatorNameInput.value.trim() : "";
  const programId = locatorProgramInput ? locatorProgramInput.value.trim() : "utm_compression_start_v1";
  const region = locatorRegion();
  if (!name) {
    writeLog({ ok: false, failure_code: "PYAUTOGUI_LOCATOR_NAME_REQUIRED", message: "Enter locator name." });
    return;
  }
  if (region.some((value) => !Number.isFinite(value)) || region[2] <= 0 || region[3] <= 0) {
    writeLog({ ok: false, failure_code: "PYAUTOGUI_LOCATOR_REGION_INVALID", message: "Enter numeric x/y/width/height values. Width and height must be positive." });
    return;
  }
  const confirmed = window.confirm(`Capture ${name} locator from region [${region.join(", ")}] on the selected Windows PC?`);
  if (!confirmed) return;
  setBusy(btnCaptureLocator, true);
  try {
    const data = await apiJson("/api/equipment/windows/capture-locator", {
      method: "POST",
      body: JSON.stringify({
        program_id: programId || "utm_compression_start_v1",
        name,
        region,
        confidence: Number(locatorConfidenceInput ? locatorConfidenceInput.value : 0.8) || 0.8,
        confirm_capture: true,
      }),
    });
    if (data && data.ok && data.locator_name && data.locator) {
      mergeLocatorOverride(data.locator_name, data.locator);
    }
    writeLog(data);
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnCaptureLocator, false);
  }
}

async function runUtmProtocol() {
  const confirmed = window.confirm("Run the registered UTM protocol on the selected Windows PC. Continue only when the UTM software is ready.");
  if (!confirmed) return;
  setBusy(btnUtm, true);
  try {
    const payload = {
      ...collectUtmProfilePayload(),
      command: "Run UTM compression protocol and export CSV",
      confirm_execute: true,
    };
    if (!Object.keys(payload.locators || {}).length) delete payload.locators;
    const data = await apiJson("/api/equipment/windows/run-program", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const evidenceAudit = await apiJson("/api/equipment/windows/evidence-audit");
    renderUtmEvidenceAudit(evidenceAudit);
    writeLog({ run_result: data, evidence_audit: evidenceAudit });
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnUtm, false);
  }
}

async function runUtmAbort() {
  const confirmed = window.confirm("Dispatch the registered UTM stop/abort recovery macro on the selected Windows PC? Use this only when the UTM setup must be stopped or reset safely.");
  if (!confirmed) return;
  setBusy(btnAbort, true);
  try {
    const targetWindow = utmTargetWindowInput ? utmTargetWindowInput.value.trim() : "";
    const payload = {
      program_id: "utm_stop_or_abort_v1",
      command: "Dispatch UTM stop/abort recovery macro",
      confirm_execute: true,
      require_screen_assertions: false,
      simulate_utm_protocol: false,
    };
    if (targetWindow) {
      if (targetWindow.startsWith("regex:")) payload.target_window_regex = targetWindow.slice(6).trim();
      else payload.target_window = targetWindow;
    }
    const data = await apiJson("/api/equipment/windows/run-program", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const requestAudit = await apiJson("/api/equipment/windows/request-log", {
      method: "POST",
      body: JSON.stringify({ runtime_mode: "live", confirm_live: true }),
    });
    renderRequestAudit(requestAudit);
    writeLog({ abort_result: data, request_audit: requestAudit });
  } catch (err) {
    writeLog({ ok: false, error: err.message });
  } finally {
    setBusy(btnAbort, false);
  }
}

rememberButtonLabels();
document.querySelectorAll("[data-equipment-proxy]").forEach((proxy) => {
  proxy.addEventListener("click", () => {
    const targetId = proxy.getAttribute("data-equipment-proxy");
    const target = targetId ? document.getElementById(targetId) : null;
    if (!target || target.disabled) return;
    target.click();
  });
});
if (btnScan) btnScan.addEventListener("click", scanNetwork);
if (btnRefresh) btnRefresh.addEventListener("click", refreshConfig);
if (btnTest) btnTest.addEventListener("click", testSelected);
if (btnProgram1) btnProgram1.addEventListener("click", runProgram1);
if (btnScreenshot) btnScreenshot.addEventListener("click", captureScreenshot);
if (btnListLocators) btnListLocators.addEventListener("click", listLocators);
if (btnCaptureLocator) btnCaptureLocator.addEventListener("click", captureLocator);
if (btnLoadUtmProfile) btnLoadUtmProfile.addEventListener("click", loadUtmProfile);
if (btnSaveUtmProfile) btnSaveUtmProfile.addEventListener("click", saveUtmProfile);
if (btnOpenBridgeGui) btnOpenBridgeGui.addEventListener("click", openSelectedBridgeGui);
if (btnLocalStart) btnLocalStart.addEventListener("click", () => runLocalBridgeAction("start"));
if (btnLocalStop) btnLocalStop.addEventListener("click", () => runLocalBridgeAction("stop"));
if (btnLocalHealth) btnLocalHealth.addEventListener("click", () => runLocalBridgeAction("health"));
if (btnLocalSelect) btnLocalSelect.addEventListener("click", () => runLocalBridgeAction("select"));
if (btnReadiness) btnReadiness.addEventListener("click", checkReadiness);
if (btnLivePreflight) btnLivePreflight.addEventListener("click", runLivePreflight);
if (btnLiveValidation) btnLiveValidation.addEventListener("click", buildLiveValidationReport);
if (btnVisionProofDraft) btnVisionProofDraft.addEventListener("click", loadVisionProofDraft);
if (btnLivePhysicalValidation) btnLivePhysicalValidation.addEventListener("click", runPhysicalLiveValidation);
if (btnEvidenceAudit) btnEvidenceAudit.addEventListener("click", checkEvidenceAudit);
if (btnProofPackage) btnProofPackage.addEventListener("click", buildProofPackage);
if (btnVerifyProofPackage) btnVerifyProofPackage.addEventListener("click", verifyProofPackage);
if (btnCompletionAudit) btnCompletionAudit.addEventListener("click", runCompletionAudit);
if (btnRequestLog) btnRequestLog.addEventListener("click", checkRequestLog);
if (btnUtm) btnUtm.addEventListener("click", runUtmProtocol);
if (btnAbort) btnAbort.addEventListener("click", runUtmAbort);
if (btnProfilePreflight) btnProfilePreflight.addEventListener("click", () => runEquipmentProfileAction("preflight", btnProfilePreflight));
if (btnProfileTest) btnProfileTest.addEventListener("click", () => runEquipmentProfileAction("test", btnProfileTest));
Promise.all([refreshConfig(), refreshLocalBridgeStatus(), loadEquipmentProfileState()]).catch((err) => writeLog({ ok: false, error: err.message }));
