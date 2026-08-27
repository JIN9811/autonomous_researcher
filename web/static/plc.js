const plcElements = {
  statusDot: document.getElementById("plc-status-dot"),
  statusLabel: document.getElementById("plc-status-label"),
  statusDetail: document.getElementById("plc-status-detail"),
  connectionState: document.getElementById("plc-connection-state"),
  configForm: document.getElementById("plc-config-form"),
  configNote: document.getElementById("plc-config-note"),
  actionStatus: document.getElementById("plc-action-status"),
  saveConfig: document.getElementById("plc-save-config"),
  preflight: document.getElementById("plc-preflight"),
  connect: document.getElementById("plc-connect"),
  disconnect: document.getElementById("plc-disconnect"),
  d100: document.getElementById("plc-d100-raw"),
  d101: document.getElementById("plc-d101-raw"),
  d102: document.getElementById("plc-d102-raw"),
  d100Decoded: document.getElementById("plc-d100-decoded"),
  d101Decoded: document.getElementById("plc-d101-decoded"),
  d102Decoded: document.getElementById("plc-d102-decoded"),
  sequence: document.getElementById("plc-register-sequence"),
  safetyBadge: document.getElementById("plc-safety-badge"),
  sourceSet: document.getElementById("plc-source-set"),
  transactionPhase: document.getElementById("plc-transaction-phase"),
  pendingCommand: document.getElementById("plc-pending-command"),
  failureCode: document.getElementById("plc-failure-code"),
  transportKind: document.getElementById("plc-transport-kind"),
  latency: document.getElementById("plc-latency"),
  freshness: document.getElementById("plc-freshness"),
  reconnectAttempt: document.getElementById("plc-reconnect-attempt"),
  lastError: document.getElementById("plc-last-error"),
  eventCount: document.getElementById("plc-event-count"),
  events: document.getElementById("plc-events"),
  virtualControls: document.getElementById("plc-virtual-controls"),
};

const plcConfigFields = {
  host: document.getElementById("plc-config-host"),
  port: document.getElementById("plc-config-port"),
  poll_interval_s: document.getElementById("plc-config-poll-interval"),
  stale_after_s: document.getElementById("plc-config-stale-after"),
  handshake_timeout_s: document.getElementById("plc-config-handshake-timeout"),
};

let plcLastMaterialSignature = "";
let plcLastEventSignature = "";
let plcRefreshInFlight = false;
let plcEventsLoaded = false;
let plcPollTimer = null;
let plcConfig = {};
let plcConnected = false;

function plcSetDot(state) {
  if (!plcElements.statusDot) return;
  plcElements.statusDot.className = `status-dot ${state}`;
}

function plcStatusKind(status = {}) {
  if (Array.isArray(status.active_estop_sources) && status.active_estop_sources.length) return "E-STOP";
  if (String(status.safety_state || "").includes("estop")) return "E-STOP";
  if (status.connection_state === "stale") return "STALE";
  if (status.failure_code) return "FAULT";
  return status.connection_state === "online" ? "ONLINE" : "OFFLINE";
}

function plcDotKind(kind) {
  if (kind === "ONLINE") return "active";
  if (kind === "STALE") return "warning";
  if (kind === "E-STOP" || kind === "FAULT") return "error";
  return "idle";
}

function plcText(value, fallback = "--") {
  return value === undefined || value === null || value === "" ? fallback : String(value);
}

function plcMillis(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${Math.round(numeric)} ms` : "--";
}

function plcSecondsAsMillis(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${Math.round(numeric * 1000)} ms` : "--";
}

function plcDecodeCommand(value) {
  return ({ 0: "Idle", 1: "Resume request", 2: "Reset request" })[Number(value)] || "Unknown command";
}

function plcDecodeEstop(value) {
  return Number(value) === 1 ? "E-stop latched" : Number(value) === 0 ? "No PLC e-stop request" : "Unknown e-stop state";
}

function plcDecodeAck(value) {
  return Number(value) === 1 ? "Recovery acknowledgment asserted" : Number(value) === 0 ? "Recovery acknowledgment clear" : "Unknown acknowledgment state";
}

function plcIsVirtualTransport(status = {}) {
  return status.transport === "virtual";
}

function plcMaterialStatus(status = {}) {
  const snapshot = status.register_snapshot || null;
  return {
    connection_state: status.connection_state,
    monitor_state: status.monitor_state,
    transport: status.transport,
    safety_state: status.safety_state,
    active_estop_sources: status.active_estop_sources,
    failure_code: status.failure_code,
    last_error: status.last_error,
    register_snapshot: snapshot && { d100: snapshot.d100, d101: snapshot.d101, d102: snapshot.d102 },
    pending_command: status.pending_command,
    transaction_phase: status.transaction?.phase,
    reconnect_attempt: status.reconnect_attempt,
  };
}

function plcEventSignature(status = {}) {
  return String(status.event_revision ?? 0);
}

function plcSetAction(message, isError = false) {
  if (!plcElements.actionStatus) return;
  plcElements.actionStatus.textContent = message;
  plcElements.actionStatus.classList.toggle("is-error", isError);
}

async function plcApi(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.message || data.detail || `Request failed with HTTP ${response.status}`);
  }
  return data;
}

function renderPLCConfig(config, connected = plcConnected) {
  if (config && typeof config === "object") plcConfig = { ...plcConfig, ...config };
  for (const [name, field] of Object.entries(plcConfigFields)) {
    if (!field) continue;
    if (Object.hasOwn(plcConfig, name)) field.value = plcText(plcConfig[name], "");
    field.disabled = connected;
  }
  if (plcElements.saveConfig) plcElements.saveConfig.disabled = connected;
  if (plcElements.configNote) {
    plcElements.configNote.textContent = connected
      ? "Configuration is locked while monitoring is connected. Stop monitoring before editing settings."
      : "Connection settings are saved only while the PLC is disconnected.";
  }
}

function renderPLCStatus(status = {}) {
  const snapshot = status.register_snapshot || {};
  const kind = plcStatusKind(status);
  const monitorRunning = status.monitor_state === "running";
  const transportAvailable = status.connection_state !== "offline";
  const sources = Array.isArray(status.active_estop_sources) ? status.active_estop_sources : [];
  const transaction = status.transaction || {};
  plcConnected = monitorRunning;
  plcSetDot(plcDotKind(kind));
  if (plcElements.statusLabel) plcElements.statusLabel.textContent = kind;
  if (plcElements.statusDetail) {
    plcElements.statusDetail.textContent = kind === "OFFLINE"
      ? "PLC is optional and offline. Manual setup remains available."
      : kind === "STALE"
        ? "PLC monitor is running, but its last sample exceeded the configured freshness window."
        : `${plcText(status.connection_state, "offline").toUpperCase()} monitor · safety=${plcText(status.safety_state, "unknown")}`;
  }
  if (plcElements.connectionState) {
    plcElements.connectionState.textContent = plcText(status.connection_state, "offline").toUpperCase();
    plcElements.connectionState.className = `badge ${status.connection_state === "online" ? "running" : transportAvailable ? "warning" : "idle"}`;
  }
  if (plcElements.connect) plcElements.connect.disabled = monitorRunning;
  if (plcElements.disconnect) plcElements.disconnect.disabled = !monitorRunning && !transportAvailable;
  if (plcElements.d100) plcElements.d100.textContent = plcText(snapshot.d100);
  if (plcElements.d101) plcElements.d101.textContent = plcText(snapshot.d101);
  if (plcElements.d102) plcElements.d102.textContent = plcText(snapshot.d102);
  if (plcElements.d100Decoded) plcElements.d100Decoded.textContent = plcDecodeCommand(snapshot.d100);
  if (plcElements.d101Decoded) plcElements.d101Decoded.textContent = plcDecodeEstop(snapshot.d101);
  if (plcElements.d102Decoded) plcElements.d102Decoded.textContent = plcDecodeAck(snapshot.d102);
  if (plcElements.sequence) plcElements.sequence.textContent = `sequence: ${plcText(snapshot.sequence)}`;
  if (plcElements.safetyBadge) {
    plcElements.safetyBadge.textContent = plcText(status.safety_state, "unknown").toUpperCase();
    plcElements.safetyBadge.className = `badge ${kind === "ONLINE" ? "running" : kind === "OFFLINE" ? "idle" : "warning"}`;
  }
  if (plcElements.sourceSet) plcElements.sourceSet.textContent = sources.length ? sources.join(", ") : "None active";
  if (plcElements.transactionPhase) plcElements.transactionPhase.textContent = plcText(transaction.phase, "No transaction");
  if (plcElements.pendingCommand) plcElements.pendingCommand.textContent = plcText(status.pending_command, "None");
  if (plcElements.failureCode) plcElements.failureCode.textContent = plcText(status.failure_code, "None");
  if (plcElements.transportKind) plcElements.transportKind.textContent = `transport: ${plcText(status.transport, "unknown")}`;
  if (plcElements.reconnectAttempt) plcElements.reconnectAttempt.textContent = plcText(status.reconnect_attempt, "0");
  if (plcElements.lastError) plcElements.lastError.textContent = plcText(status.last_error, "None");
  if (plcElements.virtualControls) plcElements.virtualControls.hidden = !plcIsVirtualTransport(status);
  renderPLCConfig();
}

function renderPLCTiming(status = {}) {
  if (plcElements.latency) plcElements.latency.textContent = plcMillis(status.last_latency_ms);
  if (plcElements.freshness) plcElements.freshness.textContent = plcSecondsAsMillis(status.sample_age_s);
}

function renderPLCEvents(payload = {}) {
  const events = Array.isArray(payload.events) ? payload.events.slice(-20).reverse() : [];
  if (plcElements.eventCount) plcElements.eventCount.textContent = `${events.length} bounded event${events.length === 1 ? "" : "s"}`;
  if (!plcElements.events) return;
  plcElements.events.replaceChildren();
  if (!events.length) {
    const empty = document.createElement("p");
    empty.className = "plc-event-empty";
    empty.textContent = "No PLC events reported.";
    plcElements.events.append(empty);
    return;
  }
  for (const event of events) {
    const row = document.createElement("article");
    row.className = "plc-event";
    const title = document.createElement("strong");
    title.textContent = plcText(event.event, "plc.event");
    const detail = document.createElement("small");
    detail.textContent = `at ${plcText(event.at, "--")} · ${JSON.stringify(event.details || {})}`;
    row.append(title, detail);
    plcElements.events.append(row);
  }
}

async function refreshPLCStatus({ forceEvents = false } = {}) {
  if (plcRefreshInFlight) return;
  plcRefreshInFlight = true;
  try {
    const status = await plcApi("/api/plc/status");
    const materialSignature = JSON.stringify(plcMaterialStatus(status));
    const materialChanged = materialSignature !== plcLastMaterialSignature;
    if (materialChanged) {
      plcLastMaterialSignature = materialSignature;
      renderPLCStatus(status);
    }
    renderPLCTiming(status);
    const eventSignature = plcEventSignature(status);
    const eventsChanged = eventSignature !== plcLastEventSignature;
    if (eventsChanged || forceEvents || !plcEventsLoaded) {
      plcLastEventSignature = eventSignature;
      renderPLCEvents(await plcApi("/api/plc/events"));
      plcEventsLoaded = true;
    }
  } catch (error) {
    plcSetDot("error");
    if (plcElements.statusLabel) plcElements.statusLabel.textContent = "FAULT";
    if (plcElements.statusDetail) plcElements.statusDetail.textContent = `PLC status unavailable: ${error.message || error}`;
    plcSetAction(`Status refresh failed: ${error.message || error}`, true);
  } finally {
    plcRefreshInFlight = false;
  }
}

async function loadPLCConfig() {
  try {
    const config = await plcApi("/api/plc/config");
    renderPLCConfig(config);
  } catch (error) {
    plcSetAction(`Configuration load failed: ${error.message || error}`, true);
  }
}

function plcConfigPayload() {
  return {
    transport: "pymcprotocol_type3e",
    host: plcConfigFields.host?.value.trim() || "",
    port: Number(plcConfigFields.port?.value),
    poll_interval_s: Number(plcConfigFields.poll_interval_s?.value),
    stale_after_s: Number(plcConfigFields.stale_after_s?.value),
    handshake_timeout_s: Number(plcConfigFields.handshake_timeout_s?.value),
  };
}

async function plcRunAction(path, message, body) {
  try {
    const result = await plcApi(path, body ? { method: "POST", body: JSON.stringify(body) } : { method: "POST" });
    plcSetAction(result.message || message);
    await refreshPLCStatus({ forceEvents: true });
  } catch (error) {
    plcSetAction(`${message} failed: ${error.message || error}`, true);
  }
}

function startPLCPolling() {
  if (plcPollTimer) return;
  plcPollTimer = window.setInterval(() => {
    if (!document.hidden) refreshPLCStatus();
  }, 4000);
}

function stopPLCPolling() {
  if (!plcPollTimer) return;
  window.clearInterval(plcPollTimer);
  plcPollTimer = null;
}

plcElements.saveConfig?.addEventListener("click", () => plcRunAction("/api/plc/config", "PLC configuration saved.", plcConfigPayload()));
plcElements.preflight?.addEventListener("click", () => plcRunAction("/api/plc/preflight", "PLC preflight completed."));
plcElements.connect?.addEventListener("click", () => plcRunAction("/api/plc/connect", "PLC monitoring started."));
plcElements.disconnect?.addEventListener("click", () => plcRunAction("/api/plc/disconnect", "PLC monitoring stopped."));
document.getElementById("plc-virtual-estop")?.addEventListener("click", () => plcRunAction("/api/plc/virtual/input", "Virtual E-stop applied.", { action: "estop" }));
document.getElementById("plc-virtual-resume")?.addEventListener("click", () => plcRunAction("/api/plc/virtual/input", "Virtual resume applied.", { action: "resume" }));
document.getElementById("plc-virtual-reset")?.addEventListener("click", () => plcRunAction("/api/plc/virtual/input", "Virtual reset applied.", { action: "reset" }));
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshPLCStatus();
});
window.addEventListener("pagehide", stopPLCPolling, { once: true });

Promise.all([loadPLCConfig(), refreshPLCStatus({ forceEvents: true })]).then(startPLCPolling);
