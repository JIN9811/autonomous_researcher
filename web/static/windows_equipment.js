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

function setBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
  button.textContent = busy ? "Working..." : button.dataset.originalText || button.textContent;
}

function rememberButtonLabels() {
  [btnScan, btnRefresh, btnTest, btnProgram1].forEach((button) => {
    if (button && !button.dataset.originalText) {
      button.dataset.originalText = button.textContent;
    }
  });
}

function writeLog(data) {
  if (resultLog) {
    resultLog.textContent = JSON.stringify(data, null, 2);
  }
}

function setConnectionStatus(connection) {
  const selected = Boolean(connection && connection.selected);
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

async function refreshConfig() {
  const data = await apiJson("/api/equipment/windows/config");
  setConnectionStatus(data.connection || {});
  writeLog(data);
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
    card.className = "equipment-candidate-card";
    const selected = candidate.selected ? "selected" : "standby";
    card.innerHTML = `
      <div>
        <strong>${candidate.candidate_alias}</strong>
        <p class="hint">${candidate.bridge_url} · ${selected} · ${candidate.allow_live_execute ? "live enabled" : "live blocked"}</p>
      </div>
      <div class="button-row">
        <button class="btn mini" data-action="select">Select</button>
        <button class="btn mini danger" data-action="delete">Delete</button>
      </div>
    `;
    const selectButton = card.querySelector('[data-action="select"]');
    const deleteButton = card.querySelector('[data-action="delete"]');
    selectButton.addEventListener("click", () => selectSavedCandidate(candidate.candidate_alias));
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

async function selectSavedCandidate(candidateAlias) {
  const data = await apiJson("/api/equipment/windows/select", {
    method: "POST",
    body: JSON.stringify({ candidate_alias: candidateAlias }),
  });
  setConnectionStatus(data);
  writeLog(data);
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

rememberButtonLabels();
if (btnScan) btnScan.addEventListener("click", scanNetwork);
if (btnRefresh) btnRefresh.addEventListener("click", refreshConfig);
if (btnTest) btnTest.addEventListener("click", testSelected);
if (btnProgram1) btnProgram1.addEventListener("click", runProgram1);
refreshConfig().catch((err) => writeLog({ ok: false, error: err.message }));
