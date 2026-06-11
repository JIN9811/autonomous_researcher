/*
File purpose:
- Runtime for the separate LeLab-inspired ROBOTIS Guided Device Bridge page.

Key functions:
- refreshGuidedBridge
- renderReadiness
- runGuidedCommand

Inputs/outputs:
- Input: /api/device-bridge/lerobot/summary and existing /api/lerobot/* APIs
- Output: readiness board, workflow cards, command output

Modification guide:
- This file must not mutate the legacy /lerobot page DOM.
- Keep all selectors prefixed with guided-*.
*/

const guided = (id) => document.getElementById(id);
const guidedState = {
  summary: null,
  ownerId: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
  owner: false,
  lastRecordSessionId: "",
};

const ownerKey = "atr_guided_lerobot_bridge_owner";
const ownerTtlMs = 10_000;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function setOutput(payload, state = "idle") {
  const output = guided("guided-output");
  const status = guided("guided-output-status");
  if (output) output.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  if (status) {
    status.textContent = state.toUpperCase();
    status.className = `badge ${state}`;
  }
}

function tabOwnershipHeartbeat() {
  const now = Date.now();
  try {
    const raw = window.localStorage.getItem(ownerKey);
    const current = raw ? JSON.parse(raw) : null;
    if (!current || current.ownerId === guidedState.ownerId || now - Number(current.updatedAt || 0) > ownerTtlMs) {
      window.localStorage.setItem(ownerKey, JSON.stringify({ ownerId: guidedState.ownerId, updatedAt: now }));
      guidedState.owner = true;
    } else {
      guidedState.owner = false;
    }
  } catch (_err) {
    guidedState.owner = true;
  }
  const pill = guided("guided-owner-state");
  if (pill) {
    pill.textContent = guidedState.owner ? "OWNER TAB" : "READ ONLY TAB";
    pill.className = `badge ${guidedState.owner ? "ok" : "warning"}`;
  }
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_err) {
    data = { ok: false, raw: text };
  }
  if (!res.ok) {
    const message = data.detail || data.message || `HTTP ${res.status}`;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

function selectedPayload() {
  return {
    mode: guided("guided-mode-select") ? guided("guided-mode-select").value : "test",
    profile_id: guided("guided-profile-select") ? guided("guided-profile-select").value : "",
    confirm_live_execute: Boolean(guided("guided-confirm-live") && guided("guided-confirm-live").checked),
  };
}

function inputValue(id, fallback = "") {
  const el = guided(id);
  return el && typeof el.value === "string" && el.value.trim() ? el.value.trim() : fallback;
}

function numberInputValue(id, fallback = null) {
  const raw = inputValue(id, "");
  if (!raw) return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

function setBadge(id, text, tone = "idle") {
  const el = guided(id);
  if (!el) return;
  el.textContent = text || "IDLE";
  el.className = `badge ${tone}`;
}

function diagnosticTone(item) {
  if (!item) return "idle";
  if (item.active) return "busy";
  const status = String(item.latest_status || "").toUpperCase();
  if (status === "COMPLETED" || status === "DATASET_COMPLETE") return "ok";
  if (status === "FAILED" || status === "ERROR") return "warning";
  return status && status !== "IDLE" ? "ok" : "idle";
}

function renderWorkflowDiagnostics(summary) {
  const diagnostics = summary.workflow_diagnostics || {};
  const record = diagnostics.record || {};
  const train = diagnostics.train || {};
  const rollout = diagnostics.rollout || {};
  setBadge("guided-record-status", record.latest_status || "IDLE", diagnosticTone(record));
  setBadge("guided-train-status", train.latest_status || "IDLE", diagnosticTone(train));
  setBadge("guided-rollout-status", rollout.latest_status || "IDLE", diagnosticTone(rollout));
}


function renderProfileOptions(summary) {
  const select = guided("guided-profile-select");
  if (!select) return;
  const previous = select.value || summary.selected_profile_id || summary.default_profile_id || "";
  select.innerHTML = (summary.profiles || [])
    .map((profile) => {
      const id = profile.profile_id || "";
      return `<option value="${escapeHtml(id)}">${escapeHtml(profile.display_name || id)}</option>`;
    })
    .join("");
  select.value = previous && Array.from(select.options).some((option) => option.value === previous)
    ? previous
    : (summary.selected_profile_id || summary.default_profile_id || "");
}

function renderReadiness(summary) {
  const grid = guided("guided-readiness-grid");
  if (!grid) return;
  grid.innerHTML = (summary.readiness || [])
    .map((item) => `
      <article class="guided-readiness-card tone-${escapeHtml(item.tone || "idle")}">
        <div><span>${escapeHtml(item.label)}</span><b>${escapeHtml(item.status)}</b></div>
        <p>${escapeHtml(item.detail)}</p>
      </article>
    `)
    .join("");
  const selected = guided("guided-selected-profile");
  if (selected) {
    selected.textContent = summary.selected_profile_id || "NO PROFILE";
    selected.className = "badge ok";
  }
}

function sessionTitle(session) {
  const workflow = session.workflow || "session";
  const status = session.status || "UNKNOWN";
  return `${workflow} · ${status}`;
}

function renderActiveMonitor(summary) {
  const active = guided("guided-active-monitor");
  const count = guided("guided-active-count");
  const cards = summary.job_cards && summary.job_cards.length ? summary.job_cards : [];
  if (count) {
    count.textContent = `${(summary.active_sessions || []).length} ACTIVE`;
    count.className = `badge ${(summary.active_sessions || []).length ? "busy" : "idle"}`;
  }
  if (!active) return;
  if (!cards.length) {
    active.innerHTML = `<div class="guided-empty-card">No active LeRobot workflow. Start from the launcher or open the classic bridge for full forms.</div>`;
    return;
  }
  active.innerHTML = cards.map((card) => `
    <article class="guided-session-card tone-${escapeHtml(card.tone || "idle")}">
      <div><strong>${escapeHtml(card.title || sessionTitle(card))}</strong><span>${escapeHtml(card.session_id || "")}</span></div>
      <p>${escapeHtml(card.detail || card.runtime_phase || card.created_at || "no runtime message")}</p>
      ${typeof card.progress_percent === "number" ? `<div class="guided-progress"><span style="width:${Math.max(0, Math.min(100, card.progress_percent))}%"></span></div>` : ""}
      <small>${escapeHtml(card.log_path || card.checkpoint_path || card.dataset_path || "no artifact path")}</small>
    </article>
  `).join("");
}

function renderActions(summary) {
  const actions = guided("guided-workflow-actions");
  if (!actions) return;
  actions.innerHTML = (summary.workflow_actions || []).map((action) => `
    <button class="guided-workflow-card" data-scroll-target="${escapeHtml(action.target)}" type="button">
      <span>${escapeHtml(action.label)}</span>
      <small>${escapeHtml(action.enabled ? "available" : "blocked")}</small>
    </button>
  `).join("");
}

function renderPolicies(summary) {
  const board = guided("guided-policy-board");
  if (!board) return;
  const policies = (summary.policies || []).slice(0, 8);
  const paths = summary.paths || {};
  const env = summary.environment || {};
  board.innerHTML = `
    <div class="guided-policy-summary">
      <article><span>Dataset Root</span><strong>${escapeHtml(paths.dataset_root || "not configured")}</strong></article>
      <article><span>Output Root</span><strong>${escapeHtml(paths.output_root || "not configured")}</strong></article>
      <article><span>Pi0.5 Env</span><strong>${escapeHtml((env.pi05 && env.pi05.conda_env_name) || "lerobot-pi05")}</strong></article>
    </div>
    <div class="guided-policy-list">
      ${policies.length ? policies.map((policy) => `
        <div class="guided-policy-row">
          <strong>${escapeHtml(policy.label || policy.value || policy.path || "policy")}</strong>
          <span>${escapeHtml(policy.policy_type || policy.source || "manual")}</span>
        </div>
      `).join("") : `<div class="guided-empty-card">No policy entries discovered.</div>`}
    </div>
  `;
}

function rememberRecordSession(summary) {
  const record = (summary.sessions || []).slice().reverse().find((session) => session.workflow === "record");
  if (record && record.session_id) guidedState.lastRecordSessionId = record.session_id;
}

async function refreshGuidedBridge() {
  tabOwnershipHeartbeat();
  const summary = await fetchJson("/api/device-bridge/lerobot/summary");
  guidedState.summary = summary;
  rememberRecordSession(summary);
  renderProfileOptions(summary);
  renderReadiness(summary);
  renderActiveMonitor(summary);
  renderActions(summary);
  renderPolicies(summary);
  renderWorkflowDiagnostics(summary);
  setOutput(summary, "ok");
  return summary;
}

async function postLerobot(path, payload = {}) {
  const body = { ...selectedPayload(), ...payload };
  return await fetchJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function runGuidedCommand(command) {
  if (!guidedState.owner && !["validate_profile", "scan_ports", "record_status", "train_status", "rollout_status", "manipulation_config"].includes(command)) {
    setOutput("This tab is read-only. Use the OWNER TAB for hardware-affecting commands.", "warning");
    return;
  }
  setOutput(`Running ${command}...`, "busy");
  let result;
  if (command === "validate_profile") result = await postLerobot("/api/lerobot/profiles/validate");
  else if (command === "record_start") {
    result = await postLerobot("/api/lerobot/record/start", {
      dataset_repo_id: inputValue("guided-record-dataset-input", "jin/record-test"),
      task_instruction: inputValue("guided-record-task-input", "Pick up the cylinder"),
      num_episodes: numberInputValue("guided-record-episodes-input", 5),
    });
    if (result && result.session_id) guidedState.lastRecordSessionId = result.session_id;
  } else if (command === "train_start") {
    const policyType = inputValue("guided-train-policy-type-input", "pi05");
    const pi05 = policyType === "pi05";
    result = await postLerobot("/api/lerobot/train/start", {
      dataset_repo_id: inputValue("guided-train-dataset-input", "jin/record-test"),
      policy_type: policyType,
      steps: numberInputValue("guided-train-steps-input", pi05 ? 3000 : 100000),
      batch_size: pi05 ? 32 : 8,
      num_workers: pi05 ? 12 : 4,
      eval_freq: pi05 ? 500 : 20000,
      log_freq: pi05 ? 5 : 200,
      save_freq: pi05 ? 500 : 20000,
      policy_pretrained_path: pi05 ? "lerobot/pi05_base" : "",
      wandb_enable: false,
      wandb_mode: "disabled",
    });
  } else if (command === "rollout_start") {
    const duration = numberInputValue("guided-rollout-duration-input", null);
    result = await postLerobot("/api/lerobot/rollout/start", {
      policy_path: inputValue("guided-rollout-policy-input", "fake://policy"),
      task_instruction: inputValue("guided-rollout-task-input", "Pick up the cube and put on the metal plate"),
      continuous_rollout: duration === null,
      episode_s: duration === null ? 86400 : duration,
      num_episodes: 1,
    });
  } else if (command === "scan_ports") {
    const payload = selectedPayload();
    const params = new URLSearchParams({ profile_id: payload.profile_id, mode: payload.mode });
    result = await fetchJson(`/api/lerobot/ports?${params.toString()}`);
  } else if (command === "teleop_start") result = await postLerobot("/api/lerobot/teleoperate/start", { display_data: false });
  else if (command === "teleop_stop") result = await postLerobot("/api/lerobot/teleoperate/stop");
  else if (command === "record_status") result = await postLerobot("/api/lerobot/record/status", { session_id: guidedState.lastRecordSessionId });
  else if (command === "record_next") result = await postLerobot("/api/lerobot/record/control", { session_id: guidedState.lastRecordSessionId, action: "next" });
  else if (command === "record_retry") result = await postLerobot("/api/lerobot/record/control", { session_id: guidedState.lastRecordSessionId, action: "retry" });
  else if (command === "record_finish") result = await postLerobot("/api/lerobot/record/control", { session_id: guidedState.lastRecordSessionId, action: "finish" });
  else if (command === "train_status") result = await postLerobot("/api/lerobot/train/status");
  else if (command === "train_cancel") result = await postLerobot("/api/lerobot/train/cancel");
  else if (command === "rollout_status") result = await postLerobot("/api/lerobot/rollout/status");
  else if (command === "rollout_stop") result = await postLerobot("/api/lerobot/rollout/stop");
  else if (command === "manipulation_config") result = await fetchJson("/api/lerobot/manipulation-agent/config");
  else result = { ok: false, message: `Unknown guided command: ${command}` };
  setOutput(result, result.ok === false ? "warning" : "ok");
  await refreshGuidedBridge();
}

function bindGuidedBridge() {
  guided("guided-refresh")?.addEventListener("click", () => refreshGuidedBridge().catch((err) => setOutput(String(err), "warning")));
  guided("guided-profile-select")?.addEventListener("change", async () => {
    try {
      await postLerobot("/api/lerobot/config", { profile_id: guided("guided-profile-select").value });
      await refreshGuidedBridge();
    } catch (err) {
      setOutput(String(err), "warning");
    }
  });
  document.addEventListener("click", (event) => {
    const commandButton = event.target.closest("[data-guided-command]");
    if (commandButton) {
      runGuidedCommand(commandButton.dataset.guidedCommand).catch((err) => setOutput(String(err), "warning"));
      return;
    }
    const scrollButton = event.target.closest("[data-scroll-target]");
    if (scrollButton) {
      const target = guided(scrollButton.dataset.scrollTarget);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  window.setInterval(tabOwnershipHeartbeat, 3000);
  window.addEventListener("beforeunload", () => {
    try {
      const raw = window.localStorage.getItem(ownerKey);
      const current = raw ? JSON.parse(raw) : null;
      if (current && current.ownerId === guidedState.ownerId) window.localStorage.removeItem(ownerKey);
    } catch (_err) {}
  });
}

bindGuidedBridge();
refreshGuidedBridge().catch((err) => setOutput(String(err), "warning"));
