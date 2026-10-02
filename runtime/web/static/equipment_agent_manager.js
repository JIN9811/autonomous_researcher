(() => {
  "use strict";

  const profileSelect = document.getElementById("equipment-manager-profile");
  const blocksHost = document.getElementById("equipment-manager-blocks");
  const addButton = document.getElementById("equipment-manager-add-skill");
  const saveButton = document.getElementById("equipment-manager-save");
  const closeButton = document.getElementById("equipment-manager-close");
  const status = document.getElementById("equipment-manager-status");
  const readiness = document.getElementById("equipment-manager-readiness");
  const version = document.getElementById("equipment-manager-version");
  const taskName = document.getElementById("equipment-manager-agentic-task-name");
  const taskDescription = document.getElementById("equipment-manager-agentic-task-description");
  const loadUtmCycleButton = document.getElementById("equipment-manager-load-utm-cycle");
  const rawCsvPanel = document.getElementById("equipment-raw-csv-panel");
  const rawCsvMode = document.getElementById("equipment-raw-csv-mode");
  const rawCsvSession = document.getElementById("equipment-raw-csv-session");
  const rawCsvSpecimen = document.getElementById("equipment-raw-csv-specimen");
  const rawCsvLoop = document.getElementById("equipment-raw-csv-loop");
  const rawCsvRepeat = document.getElementById("equipment-raw-csv-repeat");
  const rawCsvPreviewButton = document.getElementById("equipment-raw-csv-preview");
  const rawCsvExecuteButton = document.getElementById("equipment-raw-csv-execute");
  const rawCsvStatus = document.getElementById("equipment-raw-csv-status");
  const rawCsvPath = document.getElementById("equipment-raw-csv-path");
  const rawCsvMetadata = document.getElementById("equipment-raw-csv-metadata");
  let flow = null;
  let skills = [];
  let visionTasks = [];
  let agenticTasks = [];
  let flowTemplates = [];
  let flowReadiness = { ready: false, blocks: [] };
  let flowExecution = {};
  let rawCsvPreview = null;
  let dirty = false;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === "string" ? payload.detail : payload.detail?.message || payload.message || `HTTP ${response.status}`;
      const error = new Error(detail);
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  function rawCsvBlock() {
    return (flow?.blocks || []).find((block) => block?.id === "save_raw_data" || block?.skill?.skill_id === "utm_save_raw_data");
  }

  function rawCsvInputContext(mode) {
    return {
      mode,
      session_id: rawCsvSession.value.trim(),
      specimen_id: rawCsvSpecimen.value.trim(),
      loop_index: Number(rawCsvLoop.value),
      repeat_index: Number(rawCsvRepeat.value),
    };
  }

  function rawCsvSignature() {
    return JSON.stringify({ ui_mode: rawCsvMode.value, ...rawCsvInputContext(rawCsvMode.value) });
  }

  function invalidateRawCsvPreview() {
    rawCsvPreview = null;
    rawCsvExecuteButton.disabled = true;
    rawCsvStatus.textContent = "preview required";
    rawCsvPath.textContent = "Not previewed";
    rawCsvMetadata.textContent = "";
  }

  function applyRawCsvMode() {
    const live = rawCsvMode.value === "live";
    if (live) {
      const context = flowExecution?.export_context || flowExecution?.raw_csv_export || flowExecution || {};
      rawCsvSession.value = context.session_id || context.run_id || rawCsvSession.value;
      rawCsvSpecimen.value = context.specimen_id || rawCsvSpecimen.value;
      rawCsvLoop.value = context.loop_index || rawCsvLoop.value;
      rawCsvRepeat.value = context.repeat_index || rawCsvRepeat.value;
    }
    for (const input of [rawCsvSession, rawCsvSpecimen, rawCsvLoop, rawCsvRepeat]) input.readOnly = live;
    rawCsvExecuteButton.hidden = live;
    invalidateRawCsvPreview();
  }

  function renderRawCsvPanel(blocks) {
    const hasRawCsvBlock = blocks.some((block) => block?.id === "save_raw_data" || block?.skill?.skill_id === "utm_save_raw_data");
    rawCsvPanel.hidden = !hasRawCsvBlock;
    if (!hasRawCsvBlock) return;
    const block = rawCsvBlock();
    const bound = block?.skill?.skill_id === "utm_save_raw_data" && Boolean(block?.skill?.skill_version);
    rawCsvPreviewButton.disabled = !bound;
    if (!bound) {
      rawCsvStatus.textContent = "bind skill first";
      rawCsvExecuteButton.disabled = true;
    }
  }

  async function previewRawCsv() {
    const block = rawCsvBlock();
    if (!block?.skill?.skill_id || !block?.skill?.skill_version) return;
    rawCsvPreviewButton.disabled = true;
    rawCsvStatus.textContent = "checking";
    try {
      const payload = await requestJson(`/api/equipment/skills/${encodeURIComponent(block.skill.skill_id)}/${encodeURIComponent(block.skill.skill_version)}/test`, {
        method: "POST",
        body: JSON.stringify({
          runtime_mode: "dry_run",
          confirm_execute: false,
          export_context: rawCsvInputContext("dry_run"),
        }),
      });
      const result = payload.program_results?.[0] || {};
      const plan = result.raw_csv_export || {};
      rawCsvPreview = { signature: rawCsvSignature(), available: plan.available === true };
      rawCsvStatus.textContent = plan.available ? "available" : plan.exists ? "already exists" : plan.reserved ? "reserved" : "blocked";
      rawCsvPath.textContent = plan.windows_path || plan.filename || "Path unavailable";
      rawCsvMetadata.textContent = plan.filename || "";
      rawCsvExecuteButton.disabled = !(rawCsvMode.value === "test" && rawCsvPreview.available);
    } catch (error) {
      rawCsvPreview = null;
      rawCsvStatus.textContent = "blocked";
      rawCsvPath.textContent = error.message;
      rawCsvExecuteButton.disabled = true;
    } finally {
      rawCsvPreviewButton.disabled = false;
    }
  }

  async function executeRawCsvTest() {
    if (rawCsvMode.value !== "test" || !rawCsvPreview?.available || rawCsvPreview.signature !== rawCsvSignature()) return;
    if (!window.confirm("Run the Save Raw Data test against the selected Windows worker?")) return;
    const block = rawCsvBlock();
    rawCsvExecuteButton.disabled = true;
    rawCsvStatus.textContent = "saving";
    try {
      const payload = await requestJson(`/api/equipment/skills/${encodeURIComponent(block.skill.skill_id)}/${encodeURIComponent(block.skill.skill_version)}/test`, {
        method: "POST",
        body: JSON.stringify({
          runtime_mode: "test",
          confirm_execute: true,
          export_context: rawCsvInputContext("test"),
        }),
      });
      const result = payload.program_results?.[0] || {};
      const plan = result.raw_csv_export || {};
      const acquisition = result.data_acquisition || {};
      const csvArtifact = (result.output_artifacts || []).find((item) => item.kind === "utm_csv") || {};
      rawCsvStatus.textContent = "saved";
      rawCsvPath.textContent = plan.windows_path || acquisition.windows_path || "Saved";
      rawCsvMetadata.innerHTML = [
        csvArtifact.local_path ? `Linux · ${escapeHtml(csvArtifact.local_path)}` : "",
        acquisition.sha256 || csvArtifact.sha256 ? `SHA-256 · ${escapeHtml(acquisition.sha256 || csvArtifact.sha256)}` : "",
        Number.isFinite(acquisition.row_count_probe) ? `Rows · ${escapeHtml(acquisition.row_count_probe)}` : "",
        Array.isArray(acquisition.columns_probe) ? `Columns · ${escapeHtml(acquisition.columns_probe.join(", "))}` : "",
      ].filter(Boolean).join("<br>");
      rawCsvPreview = null;
    } catch (error) {
      rawCsvStatus.textContent = "blocked";
      rawCsvPath.textContent = error.message;
    }
  }

  function profileId() {
    return profileSelect.value || new URLSearchParams(location.search).get("profile_id") || "utm_windows_v1";
  }

  function eligibleSkills() {
    return skills.filter((item) => item && item.lifecycle === "deployed" && item.enabled !== false && String(item.target_profile || "") === profileId());
  }

  function skillOptions(selectedId, selectedVersion) {
    const placeholder = `<option value=""${selectedId || selectedVersion ? "" : " selected"}>${eligibleSkills().length ? "Select deployed Skill" : "No deployed Skill available"}</option>`;
    const options = eligibleSkills().map((item) => {
      const value = `${item.skill_id}@@${item.version}`;
      const selected = item.skill_id === selectedId && item.version === selectedVersion ? " selected" : "";
      return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(item.name || item.skill_id)} · ${escapeHtml(item.version)}</option>`;
    });
    return placeholder + options.join("");
  }

  function routeOptions(value, allowNext) {
    const options = [...(allowNext ? ["next"] : []), "__complete__", "__blocked__"];
    return options.map((item) => `<option value="${item}"${item === value ? " selected" : ""}>${item}</option>`).join("");
  }

  function visionTaskOptions(selectedId) {
    const placeholder = `<option value=""${selectedId ? "" : " selected"}>Select Vision Task</option>`;
    return placeholder + visionTasks.map((task) => {
      const selected = task.task_id === selectedId ? " selected" : "";
      return `<option value="${escapeHtml(task.task_id)}"${selected}>${escapeHtml(task.label || task.task_id)}</option>`;
    }).join("");
  }

  function visionTaskDetail(selectedId) {
    const task = visionTasks.find((item) => item.task_id === selectedId);
    if (!task) return '<div class="equipment-manager-task-detail is-empty">Select an existing Vision Agent task for this verification slot.</div>';
    const modes = Array.isArray(task.runtime_modes) ? task.runtime_modes.join(" / ") : "";
    const evidence = Object.keys(task.expected || {}).join(" · ");
    return `<div class="equipment-manager-task-detail">
      <strong>${escapeHtml(task.label || task.task_id)}</strong>
      <span>${escapeHtml(task.description || "")}</span>
      <small>Evidence · ${escapeHtml(evidence || "bounded Vision result")}</small>
      <small>Timeout ${escapeHtml(task.timeout_s)}s · ${escapeHtml(modes)}</small>
    </div>`;
  }

  function render() {
    const blocks = Array.isArray(flow?.blocks) ? flow.blocks : [];
    const selectedTask = agenticTasks.find((item) => item.task_id === flow?.agentic_task_id);
    version.textContent = `v${flow?.version || 1}`;
    taskName.textContent = selectedTask?.label || "No workflow task selected";
    taskDescription.textContent = selectedTask?.description || "Load the recorded UTM cycle as an unsaved draft, then bind exact deployed Skills inside each block.";
    if (!blocks.length) {
      blocksHost.innerHTML = '<div class="equipment-manager-empty">No blocks are configured. Add a block, then bind a deployed Skill in its Skill Slot.</div>';
    } else {
      blocksHost.innerHTML = blocks.map((block, index) => {
        const isLast = index === blocks.length - 1;
        return `<article class="equipment-manager-block" data-block-id="${escapeHtml(block.id)}">
          <header class="equipment-manager-block-head">
            <span class="equipment-manager-block-index">BLOCK ${String(index + 1).padStart(2, "0")}</span>
            <div class="equipment-manager-block-actions">
              <button class="manager-btn" data-move="-1" type="button"${index === 0 ? " disabled" : ""}>Up</button>
              <button class="manager-btn" data-move="1" type="button"${isLast ? " disabled" : ""}>Down</button>
              <button class="manager-btn" data-remove type="button">Delete</button>
            </div>
          </header>
          <div class="equipment-manager-block-main">
            <section class="equipment-manager-skill-slot">
              <div class="equipment-manager-slot-title"><span>Skill Slot</span><small>LOW LEVEL</small></div>
              <div class="equipment-manager-form-grid">
                <label class="span-2">Exact deployed Skill<select class="manager-input" data-field="skill">${skillOptions(block.skill?.skill_id, block.skill?.skill_version)}</select></label>
              </div>
            </section>
            <section class="equipment-manager-agentic-slot">
              <div class="equipment-manager-slot-title"><span>Agentic Task</span><small>MIDDLE LEVEL</small></div>
              <div class="equipment-manager-form-grid">
                <label class="span-2">Task name<input class="manager-input" data-field="agentic.task" value="${escapeHtml(block.agentic?.task || block.label || "Equipment Task")}" /></label>
                <label>On completed<select class="manager-input" data-field="agentic.completed">${routeOptions(block.agentic?.completed, !isLast)}</select></label>
                <label>On failed<select class="manager-input" data-field="agentic.failed">${routeOptions(block.agentic?.failed, false)}</select></label>
              </div>
            </section>
          </div>
          <section class="equipment-manager-vision-slot">
            <div class="equipment-manager-slot-title"><span>Vision Slot</span><small>OPTIONAL VERIFICATION</small></div>
            <div class="equipment-manager-form-grid">
              <label class="manager-toggle"><input type="checkbox" data-field="vision.enabled"${block.vision?.enabled ? " checked" : ""} />Enable Vision verification</label>
              <label class="manager-toggle"><input type="checkbox" data-field="vision.blocking"${block.vision?.blocking !== false ? " checked" : ""} />Block Agentic Progress on failure</label>
              <label>Vision Task<select class="manager-input" data-field="vision.task_id">${visionTaskOptions(block.vision?.task_id || "")}</select></label>
              <div class="span-2">${visionTaskDetail(block.vision?.task_id || "")}</div>
            </div>
          </section>
        </article>`;
      }).join("");
    }
    renderRawCsvPanel(blocks);
    const hasUnboundSlot = (flowReadiness.blocks || []).some((item) => item.reason === "Skill Slot is unbound");
    readiness.textContent = blocks.length ? (dirty ? "draft" : hasUnboundSlot ? "unbound" : "saved") : "empty";
    status.textContent = dirty
      ? "Unsaved Agent Manager changes."
      : blocks.length
        ? hasUnboundSlot ? "Profile flow is saved. Unbound Skill Slots remain non-executable." : "Profile flow is saved and ready for Agent execution."
        : "Add a block, then bind a Skill in its Skill Slot.";
  }

  function mutate(next) {
    flow = next;
    dirty = true;
    render();
  }

  async function loadProfiles() {
    const payload = await requestJson("/api/equipment/profiles");
    const requested = new URLSearchParams(location.search).get("profile_id") || payload.selected_profile_id;
    profileSelect.innerHTML = (payload.profiles || []).map((item) => `<option value="${escapeHtml(item.profile_id)}"${item.profile_id === requested ? " selected" : ""}>${escapeHtml(item.label || item.name || item.profile_id)}</option>`).join("");
  }

  async function loadFlow() {
    const payload = await requestJson(`/api/equipment/profiles/${encodeURIComponent(profileId())}/skill-flow`);
    flow = payload.flow || window.ATREquipmentSkillFlow.empty(profileId());
    skills = Array.isArray(payload.skills) ? payload.skills : [];
    visionTasks = Array.isArray(payload.vision_tasks) ? payload.vision_tasks : [];
    agenticTasks = Array.isArray(payload.agentic_tasks) ? payload.agentic_tasks : [];
    flowTemplates = Array.isArray(payload.flow_templates) ? payload.flow_templates : [];
    flowReadiness = payload.readiness || { ready: false, blocks: [] };
    flowExecution = payload.execution || {};
    rawCsvPreview = null;
    dirty = false;
    render();
  }

  async function saveFlow() {
    saveButton.disabled = true;
    status.textContent = "Validating exact Skill versions and saving the Profile flow.";
    try {
      const payload = await requestJson(`/api/equipment/profiles/${encodeURIComponent(profileId())}/skill-flow`, { method: "PUT", body: JSON.stringify({ flow }) });
      flow = payload.flow;
      skills = payload.skills || skills;
      visionTasks = payload.vision_tasks || visionTasks;
      agenticTasks = payload.agentic_tasks || agenticTasks;
      flowTemplates = payload.flow_templates || flowTemplates;
      flowReadiness = payload.readiness || { ready: false, blocks: [] };
      dirty = false;
      render();
    } catch (error) {
      status.textContent = `Save failed · ${error.message}`;
      readiness.textContent = "blocked";
    } finally {
      saveButton.disabled = false;
    }
  }

  addButton.addEventListener("click", () => {
    mutate(window.ATREquipmentSkillFlow.addBlock(flow));
  });
  loadUtmCycleButton.addEventListener("click", () => {
    const template = flowTemplates.find((item) => item.agentic_task_id === "run_utm_compression_cycle");
    if (!template) {
      status.textContent = "UTM Compression Cycle template is unavailable for this Profile.";
      return;
    }
    if (dirty && !confirm("Replace the current unsaved draft with the UTM Compression Cycle?")) return;
    mutate(window.ATREquipmentSkillFlow.applyTemplate(flow, template));
    status.textContent = "UTM Compression Cycle loaded as an unsaved draft. Bind deployed Skills before saving or executing.";
  });
  saveButton.addEventListener("click", () => saveFlow());
  closeButton.addEventListener("click", () => {
    if (!dirty || confirm("Discard unsaved Agent Manager changes?")) window.close();
  });
  profileSelect.addEventListener("change", async () => {
    if (dirty && !confirm("Discard unsaved changes and switch Profile?")) return render();
    history.replaceState(null, "", `${location.pathname}?profile_id=${encodeURIComponent(profileId())}`);
    await loadFlow();
  });
  blocksHost.addEventListener("click", (event) => {
    const blockElement = event.target.closest("[data-block-id]");
    if (!blockElement) return;
    const blockId = blockElement.dataset.blockId;
    if (event.target.closest("[data-remove]")) mutate(window.ATREquipmentSkillFlow.removeBlock(flow, blockId));
    const move = event.target.closest("[data-move]");
    if (move) mutate(window.ATREquipmentSkillFlow.moveBlock(flow, blockId, Number(move.dataset.move)));
  });
  blocksHost.addEventListener("change", (event) => {
    const blockElement = event.target.closest("[data-block-id]");
    const field = event.target.dataset.field;
    if (!blockElement || !field) return;
    let value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    if (field === "skill") {
      const [skillId = "", skillVersion = ""] = String(value).split("@@");
      let next = window.ATREquipmentSkillFlow.updateBlock(flow, blockElement.dataset.blockId, "skill.skill_id", skillId);
      next = window.ATREquipmentSkillFlow.updateBlock(next, blockElement.dataset.blockId, "skill.skill_version", skillVersion);
      mutate(next);
    } else {
      mutate(window.ATREquipmentSkillFlow.updateBlock(flow, blockElement.dataset.blockId, field, value));
    }
  });
  rawCsvMode.addEventListener("change", applyRawCsvMode);
  for (const input of [rawCsvSession, rawCsvSpecimen, rawCsvLoop, rawCsvRepeat]) {
    input.addEventListener("input", invalidateRawCsvPreview);
  }
  rawCsvPreviewButton.addEventListener("click", previewRawCsv);
  rawCsvExecuteButton.addEventListener("click", executeRawCsvTest);
  window.addEventListener("beforeunload", (event) => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  loadProfiles().then(loadFlow).catch((error) => {
    readiness.textContent = "error";
    status.textContent = error.message;
  });
})();
