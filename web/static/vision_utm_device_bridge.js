"use strict";

const el = (id) => document.getElementById(id);
const state = {
  busy: false,
  buttons: [],
  frameStreamActive: false,
  frameStreamFetching: false,
  frameStreamTimer: null,
  frameStreamIntervalMs: 1000,
  frameStreamUrlCache: "",
  frameStreamUrlKey: "",
  activeProfile: {},
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>\"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;",
  }[ch]));
}

async function fetchJson(url, options = {}) {
  const { timeoutMs = 8000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  if (!fetchOptions.signal) fetchOptions.signal = controller.signal;
  let res;
  let text = "";
  try {
    res = await fetch(url, fetchOptions);
    text = await res.text();
  } catch (err) {
    return {
      ok: false,
      failure_code: err?.name === "AbortError" ? "FETCH_TIMEOUT" : "FETCH_FAILED",
      message: `${url}: ${String(err)}`,
    };
  } finally {
    clearTimeout(timer);
  }
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (err) {
    data = { ok: false, failure_code: "JSON_PARSE_FAILED", message: String(err), raw: text };
  }
  if (!res.ok) {
    data.ok = false;
    data.failure_code = data.failure_code || `HTTP_${res.status}`;
  }
  return data;
}

function setBusy(busy, label = "working") {
  state.busy = busy;
  state.buttons.forEach((button) => { button.disabled = busy; });
  updateFrameStreamControls();
  const pill = el("vision-camera-command-pill");
  if (pill) {
    pill.textContent = busy ? label : "idle";
    pill.className = `badge ${busy ? "busy" : "idle"}`;
  }
}

function updateFrameStreamControls() {
  const play = el("btn-vision-camera-frame-play");
  const stop = el("btn-vision-camera-frame-stop");
  if (play) play.disabled = state.busy || state.frameStreamActive || state.frameStreamFetching;
  if (stop) stop.disabled = state.busy || (!state.frameStreamActive && !state.frameStreamTimer);
}

function setFrameStreamStatus(status, detail = "") {
  const node = el("vision-camera-frame-stream-status");
  if (!node) return;
  node.textContent = detail ? `${status} · ${detail}` : status;
  node.className = `badge ${
    status === "live" ? "ready" :
    status === "updating" ? "busy" :
    status === "error" ? "warn" :
    "idle"
  }`;
}

function clearFrameStreamTimer() {
  if (!state.frameStreamTimer) return;
  clearTimeout(state.frameStreamTimer);
  state.frameStreamTimer = null;
}

function frameStreamFps() {
  const value = Number(el("vision-camera-fps")?.value || 15);
  return Number.isFinite(value) && value > 0 ? value : 15;
}

function utmRuntimeFrameStreamUrl() {
  const fps = frameStreamFps();
  const topic = frameStreamTopicLabel();
  const streamKey = `${topic}|${fps}`;
  if (streamKey !== state.frameStreamUrlKey || !state.frameStreamUrlCache) {
    state.frameStreamUrlKey = streamKey;
    state.frameStreamUrlCache = `/api/equipment/utm-runtime/frame-stream.mjpeg?topic=${encodeURIComponent(topic)}&fps=${encodeURIComponent(String(fps))}`;
  }
  return state.frameStreamUrlCache;
}

function frameStreamTopicLabel() {
  const profile = state.activeProfile || {};
  return profile.ros_output_topic || profile.ros_rect_topic || profile.ros_image_topic || "/image_utm";
}

function setDot(node, status) {
  if (!node) return;
  node.className = `status-dot ${status || "idle"}`;
}

function logResult(payload) {
  const log = el("vision-camera-result-log");
  if (log) log.textContent = JSON.stringify(payload || {}, null, 2);
}

function updateBanner(title, detail, status = "idle") {
  const titleEl = el("vision-camera-command-title");
  const detailEl = el("vision-camera-command-detail");
  const pill = el("vision-camera-command-pill");
  if (titleEl) titleEl.textContent = title;
  if (detailEl) detailEl.textContent = detail;
  if (pill && !state.busy) {
    pill.textContent = status;
    pill.className = `badge ${status === "ok" ? "ready" : status === "error" ? "warn" : "idle"}`;
  }
}

function activeProfileFrom(payload) {
  return payload?.active_profile || payload?.config?.active_profile || payload?.config?.active_profile || {};
}

function renderConfig(payload) {
  const profile = activeProfileFrom(payload);
  state.activeProfile = profile || {};
  const configDot = el("vision-camera-config-dot");
  setDot(configDot, payload?.ok === false ? "warn" : "ready");
  const label = el("vision-camera-config-label");
  const detail = el("vision-camera-config-detail");
  if (label) label.textContent = profile.label || "Camera profile loaded";
  if (detail) detail.textContent = `${profile.width || "-"}x${profile.height || "-"} @ ${profile.fps || "-"}fps · ${profile.device_path || "no device"}`;
  const map = {
    "vision-camera-device-path": profile.device_path,
    "vision-camera-width": profile.width,
    "vision-camera-height": profile.height,
    "vision-camera-fps": profile.fps,
    "vision-camera-pixel-format": profile.pixel_format,
    "vision-camera-brightness": profile.brightness,
    "vision-camera-gain": profile.gain,
    "vision-camera-checkerboard-size": profile.checkerboard_size,
    "vision-camera-checkerboard-square": profile.checkerboard_square_m,
    "vision-camera-calibration-file": profile.calibration_file,
  };
  Object.entries(map).forEach(([id, value]) => {
    const input = el(id);
    if (input && value !== undefined && value !== null) input.value = value;
  });
}

function formPayload() {
  const numberValue = (id) => {
    const value = el(id)?.value;
    if (value === "" || value === undefined || value === null) return undefined;
    const num = Number(value);
    return Number.isFinite(num) ? num : undefined;
  };
  return {
    profiles: {
      camera_utm_primary: {
        profile_id: "camera_utm_primary",
        label: "Camera UTM Primary",
        device_path: el("vision-camera-device-path")?.value || undefined,
        width: numberValue("vision-camera-width"),
        height: numberValue("vision-camera-height"),
        fps: numberValue("vision-camera-fps"),
        pixel_format: el("vision-camera-pixel-format")?.value || undefined,
        brightness: numberValue("vision-camera-brightness"),
        gain: numberValue("vision-camera-gain"),
        checkerboard_size: el("vision-camera-checkerboard-size")?.value || undefined,
        checkerboard_square_m: numberValue("vision-camera-checkerboard-square"),
        calibration_file: el("vision-camera-calibration-file")?.value || undefined,
      },
    },
    active_profile_id: "camera_utm_primary",
  };
}

function renderDevices(payload) {
  const container = el("vision-camera-devices");
  if (!container) return;
  const devices = Array.isArray(payload?.devices) ? payload.devices : [];
  if (!payload?.ok) {
    container.innerHTML = `<div class="equipment-candidate-card error">${escapeHtml(payload?.failure_code || "DEVICE_SCAN_FAILED")}</div>`;
    return;
  }
  if (!devices.length) {
    container.innerHTML = `<div class="equipment-candidate-card">No V4L2 by-id Camera candidates found.</div>`;
    return;
  }
  container.innerHTML = devices.map((device) => `
    <button class="equipment-candidate-card vision-camera-device-card" type="button" data-device-path="${escapeHtml(device.by_id_path || device.device_path || "")}">
      <strong>${escapeHtml(device.label || device.id || "Camera")}</strong>
      <span>${escapeHtml(device.by_id_path || device.device_path || "")}</span>
      <small>${device.recommended ? "recommended · " : ""}${device.format_probe_ok ? "formats ok" : "formats unchecked"}</small>
    </button>
  `).join("");
  container.querySelectorAll(".vision-camera-device-card").forEach((card) => {
    card.addEventListener("click", () => {
      const input = el("vision-camera-device-path");
      if (input) input.value = card.dataset.devicePath || "";
      updateBanner("Camera candidate selected", "Apply Camera to persist this candidate before starting the UTM runtime.", "idle");
    });
  });
}

function renderRuntime(payload) {
  const status = payload?.status || payload?.runtime_probe?.status || "unknown";
  const dot = el("vision-camera-runtime-dot");
  setDot(dot, status === "running" ? "busy" : status === "error" ? "warn" : payload?.ok ? "ready" : "idle");
  const label = el("vision-camera-runtime-label");
  const detail = el("vision-camera-runtime-detail");
  if (label) label.textContent = status;
  if (detail) {
    const pid = payload?.pid || payload?.runtime_probe?.pid || "-";
    const code = payload?.failure_code || payload?.runtime_probe?.failure_code || "";
    detail.textContent = `pid=${pid}${code ? ` · ${code}` : ""}`;
  }
}

function renderGraph(payload) {
  const graph = payload?.graph || payload || {};
  const container = el("vision-camera-graph");
  const meta = el("vision-camera-graph-meta");
  if (!container) return;
  const expected = graph.expected_graph || {};
  const actual = graph.actual_graph || {};
  const expectedNodeCount = Array.isArray(expected.nodes) ? expected.nodes.length : 0;
  const actualNodeCount = Array.isArray(actual.nodes) ? actual.nodes.length : 0;
  const flow = ["usb_cam", "rectify_node", "green_dot_monitor", "yolov8"];
  container.innerHTML = flow.map((item, index) => `
    <span class="utm-rqt-node">${escapeHtml(item)}</span>
    ${index < flow.length - 1 ? '<span class="utm-rqt-arrow">→</span>' : ''}
  `).join("");
  const diag = graph.diagnostics || {};
  if (meta) {
    meta.textContent = `expected ${expectedNodeCount} nodes · actual ${actualNodeCount} nodes · ${diag.ros2_available ? "ROS2 ready" : "ROS2 pending"} · ${diag.topic_seen ? "topic ready" : "topic waiting"}`;
  }
}

function renderFrame(payload) {
  const frame = payload?.frame || payload || {};
  const container = el("vision-camera-frame");
  const meta = el("vision-camera-frame-meta");
  if (!container) return;
  const liveImage = container.querySelector('img[src*="/api/equipment/utm-runtime/frame-stream.mjpeg"]');
  if (state.frameStreamActive && liveImage) {
    if (meta) {
      const code = frame?.failure_code || "";
      const topic = frame?.topic || frameStreamTopicLabel();
      const detail = frame?.ok && frame.width && frame.height
        ? `${frame.width}x${frame.height} · ${frame.encoding || "image"}`
        : code || "live MJPEG";
      meta.textContent = `${topic} · ${detail}`;
    }
    return;
  }
  if (frame?.ok && frame.data_url) {
    container.innerHTML = `<img src="${escapeHtml(frame.data_url)}" alt="UTM Camera frame evidence" class="vision-camera-frame-img">`;
    if (meta) meta.textContent = `${frame.topic || "/image_utm"} · ${frame.width || "-"}x${frame.height || "-"} · ${frame.encoding || "image"}`;
    return;
  }
  const code = frame?.failure_code || "FRAME_UNAVAILABLE";
  container.innerHTML = `<div class="vision-camera-frame-placeholder">${escapeHtml(code)}<br><small>${escapeHtml(frame?.message || "No frame evidence returned yet.")}</small></div>`;
  if (meta) meta.textContent = `${frame?.topic || "/image_utm"} · ${code}`;
}

function renderCalibration(payload) {
  const status = payload?.status || "stopped";
  setDot(el("vision-camera-calibration-dot"), status === "running" ? "busy" : status === "error" ? "warn" : "idle");
  const label = el("vision-camera-calibration-label");
  const detail = el("vision-camera-calibration-detail");
  if (label) label.textContent = status;
  if (detail) detail.textContent = `${payload?.calibration_file || "calibration YAML pending"}${payload?.pid ? ` · pid=${payload.pid}` : ""}`;
}

async function withBusy(label, action) {
  if (state.busy) return;
  setBusy(true, label);
  try {
    const payload = await action();
    logResult(payload);
    return payload;
  } catch (err) {
    const payload = { ok: false, failure_code: "UI_ACTION_FAILED", message: String(err) };
    logResult(payload);
    updateBanner("Camera bridge action failed", String(err), "error");
    return payload;
  } finally {
    setBusy(false);
  }
}

async function loadConfig() {
  const payload = await fetchJson("/api/equipment/utm-runtime/camera-config");
  renderConfig(payload);
  updateBanner("Camera config loaded", "Saved Camera profile is reflected in the form.", payload.ok ? "ok" : "error");
  return payload;
}

async function loadDevices() {
  const payload = await fetchJson("/api/equipment/utm-runtime/camera/devices");
  renderDevices(payload);
  updateBanner("Camera device scan complete", `${payload.device_count || 0} candidate(s) found.`, payload.ok ? "ok" : "error");
  return payload;
}

async function applyCamera() {
  const payload = await fetchJson("/api/equipment/utm-runtime/camera/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(formPayload()),
  });
  renderConfig(payload.config || payload);
  updateBanner("Camera profile saved", "The next UTM runtime launch will use this Camera profile.", payload.ok ? "ok" : "error");
  return payload;
}

async function preStartCheck() {
  const payload = await fetchJson("/api/equipment/utm-runtime/camera/probe", { method: "POST", timeoutMs: 20000 });
  renderConfig(payload.config || {});
  renderDevices(payload.devices || {});
  renderRuntime(payload.runtime_probe || {});
  renderGraph(payload.graph || {});
  renderFrame(payload.frame || {});
  updateBanner("Pre Start Check complete", payload.ok ? "Camera, runtime, graph, and frame checks returned." : "One or more Camera/UTM checks need attention.", payload.ok ? "ok" : "error");
  return payload;
}

async function loadRuntimeGraph() {
  const payload = await fetchJson("/api/equipment/utm-runtime/graph");
  renderGraph(payload);
  return payload;
}

async function loadRuntimeFrame(options = {}) {
  const payload = await fetchJson("/api/equipment/utm-runtime/frame", options);
  renderFrame(payload);
  return payload;
}

async function refreshFrameStreamFrame() {
  if (!state.frameStreamActive || state.frameStreamFetching) return null;
  state.frameStreamFetching = true;
  updateFrameStreamControls();
  setFrameStreamStatus("updating", "frame");
  try {
    const payload = await loadRuntimeFrame({ timeoutMs: 6000 });
    logResult(payload);
    if (!state.frameStreamActive) {
      setFrameStreamStatus("stopped");
      return payload;
    }
    if (payload?.ok) {
      const frame = payload.frame || payload;
      const age = Number.isFinite(Number(frame.frame_age_ms)) ? `${Math.round(Number(frame.frame_age_ms))}ms` : "";
      setFrameStreamStatus("live", age || "streaming");
    } else {
      setFrameStreamStatus("error", payload?.failure_code || "frame");
    }
    return payload;
  } catch (err) {
    const payload = { ok: false, failure_code: "FRAME_STREAM_FAILED", message: String(err) };
    logResult(payload);
    setFrameStreamStatus(state.frameStreamActive ? "error" : "stopped", state.frameStreamActive ? "stream" : "");
    return payload;
  } finally {
    state.frameStreamFetching = false;
    updateFrameStreamControls();
  }
}

function scheduleFrameStreamTick() {
  clearFrameStreamTimer();
  if (!state.frameStreamActive) return;
  state.frameStreamTimer = setTimeout(async () => {
    await refreshFrameStreamFrame();
    scheduleFrameStreamTick();
  }, state.frameStreamIntervalMs);
}

async function startFrameStream() {
  if (state.frameStreamActive) return;
  state.frameStreamActive = true;
  clearFrameStreamTimer();
  const fps = frameStreamFps();
  const container = el("vision-camera-frame");
  const meta = el("vision-camera-frame-meta");
  if (container) {
    container.innerHTML = `<img src="${escapeHtml(utmRuntimeFrameStreamUrl())}" alt="UTM Camera live frame stream" class="vision-camera-frame-img">`;
  }
  if (meta) meta.textContent = `${frameStreamTopicLabel()} · live MJPEG · ${fps}fps`;
  setFrameStreamStatus("live", `${fps}fps`);
  updateFrameStreamControls();
  updateBanner("Live frame stream started", `Device Bridge is receiving Camera frame evidence at ${fps}fps.`, "ok");
}

function stopFrameStream(options = {}) {
  state.frameStreamActive = false;
  clearFrameStreamTimer();
  state.frameStreamFetching = false;
  state.frameStreamUrlCache = "";
  state.frameStreamUrlKey = "";
  const image = el("vision-camera-frame")?.querySelector("img");
  if (image) image.removeAttribute("src");
  setFrameStreamStatus("stopped");
  updateFrameStreamControls();
  if (!options.silent) {
    updateBanner("Live frame stream stopped", "Polling is stopped. The last frame remains visible.", "idle");
  }
}

async function runtimeAction(action) {
  if (action === "stop") stopFrameStream({ silent: true });
  const payload = await fetchJson(`/api/equipment/utm-runtime/${action}`, { method: "POST" });
  renderRuntime(payload);
  if (action !== "stop") {
    await Promise.allSettled([loadRuntimeGraph(), loadRuntimeFrame()]);
  }
  updateBanner(`UTM runtime ${action}`, payload.message || payload.status || "Runtime action returned.", payload.ok ? "ok" : "error");
  return payload;
}

async function cleanupCameraPorts() {
  stopFrameStream({ silent: true });
  const payload = await fetchJson("/api/equipment/utm-runtime/camera/cleanup", { method: "POST", timeoutMs: 12000 });
  renderRuntime(payload.runtime || payload);
  updateBanner("Camera ports released", payload.message || "UTM camera runtime and stale stream subscribers were cleaned up.", payload.ok ? "ok" : "error");
  return payload;
}

async function calibrationAction(action) {
  const payload = action === "start"
    ? await fetchJson("/api/equipment/utm-runtime/camera/calibrate/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          checkerboard_size: el("vision-camera-checkerboard-size")?.value || undefined,
          checkerboard_square_m: Number(el("vision-camera-checkerboard-square")?.value || 0) || undefined,
        }),
      })
    : await fetchJson("/api/equipment/utm-runtime/camera/calibrate/stop", { method: "POST" });
  renderCalibration(payload);
  updateBanner(action === "start" ? "Calibration GUI requested" : "Calibration GUI stop requested", payload.message || payload.status || "Calibration action returned.", payload.ok ? "ok" : "error");
  return payload;
}

async function refreshInitial() {
  const [graphResult, configResult, statusResult, calibrationResult] = await Promise.allSettled([
    fetchJson("/api/equipment/utm-runtime/graph", { timeoutMs: 8000 }),
    fetchJson("/api/equipment/utm-runtime/camera-config"),
    fetchJson("/api/equipment/utm-runtime/status"),
    fetchJson("/api/equipment/utm-runtime/camera/calibrate/status"),
  ]);
  const graph = graphResult.status === "fulfilled" ? graphResult.value : { ok: false, failure_code: "GRAPH_FETCH_FAILED", message: String(graphResult.reason) };
  const config = configResult.status === "fulfilled" ? configResult.value : { ok: false, failure_code: "CONFIG_FETCH_FAILED", message: String(configResult.reason) };
  const status = statusResult.status === "fulfilled" ? statusResult.value : { ok: false, status: "error", failure_code: "STATUS_FETCH_FAILED", message: String(statusResult.reason) };
  const calibration = calibrationResult.status === "fulfilled" ? calibrationResult.value : { ok: false, status: "error", failure_code: "CALIBRATION_FETCH_FAILED", message: String(calibrationResult.reason) };
  renderGraph(graph);
  renderConfig(config);
  renderRuntime(status);
  renderCalibration(calibration);
  logResult({ config, status, calibration, graph });
  if (status?.status !== "running") return;
  loadRuntimeFrame({ timeoutMs: 6000 }).then((frame) => {
    logResult({ config, status, calibration, graph, frame });
  });
}

function init() {
  state.buttons = Array.from(document.querySelectorAll("button"));
  el("btn-vision-camera-load")?.addEventListener("click", () => withBusy("load", loadConfig));
  el("btn-vision-camera-devices")?.addEventListener("click", () => withBusy("scan", loadDevices));
  el("btn-vision-camera-apply")?.addEventListener("click", () => withBusy("save", applyCamera));
  el("btn-vision-camera-precheck")?.addEventListener("click", () => withBusy("checking", preStartCheck));
  el("btn-vision-camera-frame-play")?.addEventListener("click", () => startFrameStream());
  el("btn-vision-camera-frame-stop")?.addEventListener("click", () => stopFrameStream());
  el("btn-vision-camera-runtime-start")?.addEventListener("click", () => withBusy("loading", () => runtimeAction("start")));
  el("btn-vision-camera-runtime-stop")?.addEventListener("click", () => withBusy("unloading", () => runtimeAction("stop")));
  el("btn-vision-camera-cleanup")?.addEventListener("click", () => withBusy("cleanup", cleanupCameraPorts));
  el("btn-vision-camera-calibrate")?.addEventListener("click", () => withBusy("calibrating", () => calibrationAction("start")));
  el("btn-vision-camera-calibrate-stop")?.addEventListener("click", () => withBusy("stopping", () => calibrationAction("stop")));
  refreshInitial().catch((err) => logResult({ ok: false, message: String(err) }));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
