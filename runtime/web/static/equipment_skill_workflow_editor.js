(function initializeEquipmentSkillWorkflowEditor() {
  "use strict";

  const root = document.getElementById("skill-workflow-editor");
  const model = window.EquipmentSkillWorkflowModel;
  if (!root || !model) return;

  const skillId = root.dataset.skillId;
  const version = root.dataset.skillVersion;
  const workerId = new URLSearchParams(window.location.search).get("worker") || "";
  const apiBase = `/api/equipment/skills/${encodeURIComponent(skillId)}/${encodeURIComponent(version)}/workflow`;
  const elements = {
    lifecycle: document.getElementById("workflow-editor-lifecycle"),
    dirty: document.getElementById("workflow-editor-dirty"),
    duration: document.getElementById("workflow-editor-duration"),
    check: document.getElementById("workflow-editor-check"),
    save: document.getElementById("workflow-editor-save"),
    close: document.getElementById("workflow-editor-close"),
    add: document.getElementById("workflow-editor-add-step"),
    addAction: document.getElementById("workflow-editor-add-action"),
    list: document.getElementById("workflow-editor-step-list"),
    count: document.getElementById("workflow-editor-step-count"),
    status: document.getElementById("workflow-editor-status"),
    worker: document.getElementById("workflow-editor-worker"),
    cropDialog: document.getElementById("workflow-crop-dialog"),
    cropStage: document.getElementById("workflow-crop-stage"),
    cropSource: document.getElementById("workflow-crop-source"),
    cropBox: document.getElementById("workflow-crop-box"),
    cropPreview: document.getElementById("workflow-crop-preview"),
    cropCoordinates: document.getElementById("workflow-crop-coordinates"),
    cropReset: document.getElementById("workflow-crop-reset"),
    cropApply: document.getElementById("workflow-crop-apply"),
    cropCancel: document.getElementById("workflow-crop-cancel"),
  };
  const state = {
    workflow: null,
    workflowSha256: "",
    editable: false,
    dirty: false,
    expandedStepId: "",
    selectedStepId: "",
    issues: [],
    busy: false,
    crop: null,
  };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[character]));
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    let payload = {};
    try { payload = await response.json(); } catch (_error) { payload = {}; }
    if (!response.ok) {
      const detail = payload.detail || payload;
      const error = new Error(String(detail.message || detail.failure_code || `HTTP ${response.status}`));
      error.status = response.status;
      error.payload = detail;
      throw error;
    }
    return payload;
  }

  function setStatus(message, tone = "idle") {
    elements.status.textContent = message;
    elements.status.dataset.tone = tone;
  }

  function setBusy(busy) {
    state.busy = busy;
    [elements.check, elements.save, elements.add].forEach((button) => {
      if (button) button.disabled = busy || (!state.editable && button !== elements.check);
    });
  }

  function issuesFor(stepId) {
    return state.issues.filter((issue) => String(issue.step_id || "") === stepId);
  }

  function fieldInput(stepId, label, path, value, type = "text", attrs = "") {
    return `<label>${escapeHtml(label)}<input class="text-input" type="${type}" value="${escapeHtml(value)}" data-step-id="${escapeHtml(stepId)}" data-field-path="${escapeHtml(path)}" ${attrs}></label>`;
  }

  function selectInput(stepId, label, path, value, options) {
    const choices = options.map(([key, text]) => `<option value="${escapeHtml(key)}" ${key === value ? "selected" : ""}>${escapeHtml(text)}</option>`).join("");
    return `<label>${escapeHtml(label)}<select class="text-input" data-step-id="${escapeHtml(stepId)}" data-field-path="${escapeHtml(path)}">${choices}</select></label>`;
  }

  function actionFields(step) {
    const id = step.step_id;
    const action = step.action || {};
    const name = action.action;
    const pointer = ["move_to", "click", "double_click", "drag_to"].includes(name);
    const parts = [];
    if (pointer) {
      parts.push(fieldInput(id, "X", "action.x", action.x ?? "", "number", "step=1"));
      parts.push(fieldInput(id, "Y", "action.y", action.y ?? "", "number", "step=1"));
    }
    if (["move_to", "drag_to"].includes(name)) parts.push(fieldInput(id, "Duration s", "action.duration_sec", action.duration_sec ?? 0.25, "number", 'min="0.05" max="5" step="0.05"'));
    if (["click", "double_click", "drag_to"].includes(name)) parts.push(selectInput(id, "Button", "action.button", action.button || "left", [["left", "Left"], ["middle", "Middle"], ["right", "Right"]]));
    if (["scroll", "hscroll"].includes(name)) parts.push(fieldInput(id, "Clicks", "action.clicks", action.clicks ?? 1, "number", "step=1"));
    if (name === "write") parts.push(fieldInput(id, "Text", "action.text", action.text || "", "text", 'maxlength="512"'));
    if (name === "press") {
      parts.push(fieldInput(id, "Key", "action.key", action.key || "enter"));
      parts.push(fieldInput(id, "Presses", "action.presses", action.presses ?? 1, "number", 'min="1" step="1"'));
      parts.push(fieldInput(id, "Interval s", "action.interval", action.interval ?? 0, "number", 'min="0" step="0.01"'));
    }
    if (name === "hotkey") parts.push(fieldInput(id, "Keys", "action.keys", (action.keys || []).join("+"), "text", 'data-value-kind="keys"'));
    if (name === "set_input_language") {
      parts.push(fieldInput(id, "Layout ID", "action.layout_id", action.layout_id || "00000409", "text", 'maxlength="8" pattern="[0-9A-Fa-f]{8}"'));
      parts.push(fieldInput(id, "Locale", "action.locale", action.locale || "en_US"));
      parts.push(fieldInput(id, "Language", "action.language", action.language || "en"));
      parts.push(selectInput(id, "IME mode", "action.ime_mode", action.ime_mode || "alphanumeric", [["alphanumeric", "Alphanumeric"], ["native", "Native"]]));
      parts.push(fieldInput(id, "Typing mode", "action.typing_mode", action.typing_mode || "latin"));
    }
    if (name === "wait") parts.push(fieldInput(id, "Seconds", "action.seconds", action.seconds ?? 1, "number", 'min="0" max="30" step="0.1"'));
    if (["wait_until", "wait_until_image", "wait_until_text"].includes(name)) parts.push(fieldInput(id, "Target", "action.target", action.target || ""));
    if (name === "wait_until_text") parts.push(fieldInput(id, "Expected text", "action.text", action.text || ""));
    if (name === "wait_for_file") parts.push(fieldInput(id, "File pattern", "action.pattern", action.pattern || ""));
    if (["wait_until", "wait_until_image", "wait_until_text", "wait_for_file"].includes(name)) {
      parts.push(fieldInput(id, "Timeout s", "action.timeout_s", action.timeout_s ?? 30, "number", 'min="0.1" max="3600" step="0.1"'));
      parts.push(fieldInput(id, "Poll interval s", "action.poll_interval_s", action.poll_interval_s ?? 0.5, "number", 'min="0.05" max="10" step="0.05"'));
    }
    if (name === "screenshot") parts.push(fieldInput(id, "Checkpoint", "action.checkpoint", action.checkpoint || "checkpoint"));
    return parts.join("");
  }

  function locatorMarkup(step) {
    const candidates = Array.isArray(step.action?.image_candidates) ? step.action.image_candidates : [];
    const preview = candidates[0]?.png_base64
      ? `<img src="data:image/png;base64,${candidates[0].png_base64}" alt="Locator preview for ${escapeHtml(step.label)}">`
      : `<span>No embedded locator</span>`;
    return `<div class="skill-workflow-locator"><div>${preview}<small>${candidates.length ? `${candidates.length} candidate(s)` : "Coordinate or target lookup"}</small></div><div class="skill-workflow-locator-actions"><button class="btn mini" type="button" data-step-command="crop" data-step-id="${escapeHtml(step.step_id)}" ${state.editable ? "" : "disabled"}>Edit Crop</button><label class="btn mini ${state.editable ? "" : "disabled"}">Replace locator<input type="file" accept="image/png" data-locator-step="${escapeHtml(step.step_id)}" ${state.editable ? "" : "disabled"}></label></div></div>`;
  }

  function renderStep(step, index) {
    const expanded = step.step_id === state.expandedStepId;
    const selected = step.step_id === state.selectedStepId;
    const issues = issuesFor(step.step_id);
    const issueMarkup = issues.length ? `<div class="skill-workflow-step-issues">${issues.map((issue) => `<span>${escapeHtml(issue.message)}</span>`).join("")}</div>` : "";
    const actionOptions = Object.entries(model.ACTION_LABELS).map(([key, label]) => `<option value="${escapeHtml(key)}" ${key === step.action?.action ? "selected" : ""}>${escapeHtml(label)}</option>`).join("");
    return `<article class="skill-workflow-step-card ${expanded ? "expanded" : ""} ${selected ? "selected" : ""} ${issues.length ? "invalid" : ""}" data-step-card="${escapeHtml(step.step_id)}" draggable="${state.editable}">
      <button class="skill-workflow-step-summary" type="button" data-expand-step="${escapeHtml(step.step_id)}">
        <span class="skill-workflow-step-index">${String(index + 1).padStart(2, "0")}</span>
        <span><strong>${escapeHtml(step.label || step.step_id)}</strong><small>${escapeHtml(model.actionSummary(step))}</small></span>
        <span class="skill-workflow-step-state">${issues.length ? `${issues.length} issue(s)` : expanded ? "Expanded" : "Ready"}</span>
      </button>
      <div class="skill-workflow-step-editor" ${expanded ? "" : "hidden"}>
        <div class="skill-workflow-fields">
          ${fieldInput(step.step_id, "Step label", "label", step.label || "", "text", 'maxlength="160"')}
          <label>Action<select class="text-input" data-step-id="${escapeHtml(step.step_id)}" data-action-type>${actionOptions}</select></label>
          ${actionFields(step)}
          <label class="skill-workflow-check"><input type="checkbox" data-step-id="${escapeHtml(step.step_id)}" data-field-path="checkpoint_after" ${step.checkpoint_after ? "checked" : ""}> Capture checkpoint after step</label>
        </div>
        ${locatorMarkup(step)}
        ${issueMarkup}
        <div class="button-row skill-workflow-step-actions">
          <button class="btn mini" type="button" data-step-command="up" data-step-id="${escapeHtml(step.step_id)}" ${index === 0 || !state.editable ? "disabled" : ""}>Move up</button>
          <button class="btn mini" type="button" data-step-command="down" data-step-id="${escapeHtml(step.step_id)}" ${index === state.workflow.steps.length - 1 || !state.editable ? "disabled" : ""}>Move down</button>
          <button class="btn mini" type="button" data-step-command="duplicate" data-step-id="${escapeHtml(step.step_id)}" ${state.editable ? "" : "disabled"}>Duplicate</button>
          <button class="btn mini danger" type="button" data-step-command="delete" data-step-id="${escapeHtml(step.step_id)}" ${state.editable ? "" : "disabled"}>Delete</button>
          <button class="btn mini primary" type="button" data-step-command="test" data-step-id="${escapeHtml(step.step_id)}" ${!workerId || state.dirty || issues.length ? "disabled" : ""}>Test one step</button>
        </div>
      </div>
    </article>`;
  }

  function renderEditor() {
    if (!state.workflow) return;
    const bounds = model.durationBounds(state.workflow);
    elements.lifecycle.textContent = root.dataset.skillLifecycle || "draft";
    elements.lifecycle.className = `badge ${state.editable ? "idle" : "warning"}`;
    elements.dirty.textContent = state.dirty ? "Unsaved" : "Saved";
    elements.dirty.className = `badge ${state.dirty ? "warning" : "ok"}`;
    elements.duration.textContent = `Wait estimate ${bounds.minimum_s.toFixed(1)}-${bounds.maximum_s.toFixed(1)}s`;
    elements.count.textContent = `${state.workflow.steps.length} step${state.workflow.steps.length === 1 ? "" : "s"}`;
    elements.list.innerHTML = state.workflow.steps.map(renderStep).join("");
    elements.worker.textContent = `Worker: ${workerId || "not selected (step test disabled)"}`;
    elements.save.disabled = state.busy || !state.editable || !state.dirty;
    elements.add.disabled = state.busy || !state.editable;
    elements.addAction.disabled = state.busy || !state.editable;
    if (!state.editable) {
      elements.list.querySelectorAll("input, select").forEach((control) => { control.disabled = true; });
    }
  }

  function markDirty(workflow, selectedStepId = state.selectedStepId) {
    state.workflow = workflow;
    state.selectedStepId = selectedStepId;
    state.expandedStepId = selectedStepId || state.expandedStepId;
    state.dirty = true;
    state.issues = [];
    setStatus("Unsaved workflow changes.", "warning");
    renderEditor();
  }

  function typedValue(input) {
    if (input.type === "checkbox") return input.checked;
    if (input.dataset.valueKind === "keys") return input.value.split("+").map((value) => value.trim()).filter(Boolean);
    if (input.type === "number") return input.value === "" ? null : Number(input.value);
    return input.value;
  }

  async function loadWorkflow() {
    setBusy(true);
    try {
      const payload = await apiJson(apiBase);
      state.workflow = model.normalizeWorkflowState(payload.workflow);
      state.workflowSha256 = payload.workflow_sha256;
      state.editable = payload.editable === true;
      state.dirty = false;
      state.issues = [];
      state.selectedStepId = state.workflow.steps[0]?.step_id || "";
      state.expandedStepId = state.selectedStepId;
      root.dataset.skillLifecycle = payload.manifest?.lifecycle || root.dataset.skillLifecycle;
      setStatus(state.editable ? "Exact Skill workflow loaded." : "This deployed Skill version is read-only.", state.editable ? "ok" : "warning");
    } catch (error) {
      setStatus(`Load failed: ${error.message}`, "error");
      throw error;
    } finally {
      setBusy(false);
      renderEditor();
    }
  }

  async function checkWorkflow() {
    setBusy(true);
    try {
      const payload = await apiJson(`${apiBase}/check`, { method: "POST", body: JSON.stringify({ workflow: state.workflow }) });
      state.issues = payload.issues || [];
      setStatus(payload.ok ? "Workflow contract check passed." : `${state.issues.length} workflow issue(s) require correction.`, payload.ok ? "ok" : "error");
      return payload.ok;
    } finally {
      setBusy(false);
      renderEditor();
    }
  }

  async function saveWorkflow() {
    if (!state.editable || !state.dirty) return;
    const valid = await checkWorkflow();
    if (!valid) return;
    setBusy(true);
    try {
      const payload = await apiJson(apiBase, {
        method: "PUT",
        body: JSON.stringify({ expected_workflow_sha256: state.workflowSha256, workflow: state.workflow }),
      });
      state.workflow = model.normalizeWorkflowState(payload.workflow);
      state.workflowSha256 = payload.manifest.workflow_sha256;
      root.dataset.skillLifecycle = payload.manifest.lifecycle;
      state.dirty = false;
      state.issues = [];
      setStatus("Workflow saved. Previous compiled artifacts were invalidated.", "ok");
    } catch (error) {
      if (error.status === 409) setStatus("Save conflict: this Skill changed elsewhere. Local edits were preserved.", "error");
      else setStatus(`Save failed: ${error.message}`, "error");
    } finally {
      setBusy(false);
      renderEditor();
    }
  }

  async function testStep(stepId) {
    if (state.dirty) throw new Error("Save the workflow before testing a step.");
    if (!workerId) throw new Error("Open the editor from a selected Worker to test a step.");
    if (!window.confirm("Run only this saved step on the selected Worker?")) return;
    setBusy(true);
    try {
      const payload = await apiJson(`${apiBase}/steps/${encodeURIComponent(stepId)}/test`, {
        method: "POST",
        body: JSON.stringify({ bridge_id: workerId, confirm_execute: true }),
      });
      setStatus(`Step ${payload.step_id} completed on ${workerId}.`, "ok");
    } finally {
      setBusy(false);
      renderEditor();
    }
  }

  async function imageCandidate(file, kind = "editor") {
    if (!file || file.type !== "image/png") throw new Error("Select a PNG locator image.");
    if (file.size > 256 * 1024) throw new Error("Locator PNG must be 256 KiB or smaller.");
    const bytes = new Uint8Array(await file.arrayBuffer());
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const sha256 = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
    const pngBase64 = btoa(Array.from(bytes, (value) => String.fromCharCode(value)).join(""));
    const dimensions = await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
      image.onerror = () => reject(new Error("Unable to read locator image dimensions."));
      image.src = `data:image/png;base64,${pngBase64}`;
    });
    if (dimensions.width > 512 || dimensions.height > 512) throw new Error("Locator dimensions must be 512x512 or smaller.");
    return { kind, png_base64: pngBase64, sha256, ...dimensions, confidence: 0.9 };
  }

  function renderCrop() {
    if (!state.crop || !elements.cropSource.complete || !elements.cropSource.naturalWidth) return;
    const [x, y, width, height] = state.crop.box;
    Object.assign(elements.cropBox.style, {
      left: `${x * 100}%`,
      top: `${y * 100}%`,
      width: `${width * 100}%`,
      height: `${height * 100}%`,
    });
    const dimensions = model.cropPixelRect(
      state.crop.box,
      elements.cropSource.naturalWidth,
      elements.cropSource.naturalHeight,
    );
    elements.cropPreview.width = dimensions.output_width;
    elements.cropPreview.height = dimensions.output_height;
    const context = elements.cropPreview.getContext("2d");
    context.clearRect(0, 0, dimensions.output_width, dimensions.output_height);
    context.drawImage(
      elements.cropSource,
      dimensions.source_x,
      dimensions.source_y,
      dimensions.source_width,
      dimensions.source_height,
      0,
      0,
      dimensions.output_width,
      dimensions.output_height,
    );
    elements.cropCoordinates.textContent = `x ${x.toFixed(3)} · y ${y.toFixed(3)} · w ${width.toFixed(3)} · h ${height.toFixed(3)} · ${dimensions.output_width}×${dimensions.output_height}`;
  }

  async function openCropEditor(stepId) {
    if (!state.editable) return;
    setStatus("Loading the verified pre-action frame.", "idle");
    try {
      const source = await apiJson(`${apiBase}/steps/${encodeURIComponent(stepId)}/locator-source`);
      const localStep = state.workflow.steps.find((item) => item.step_id === stepId);
      const localBox = localStep?.action?.target_bbox_norm;
      const currentBox = Array.isArray(localBox) && localBox.length === 4
        ? localBox.map(Number)
        : source.target_bbox_norm;
      state.crop = {
        stepId,
        source,
        box: [...currentBox],
        aiBox: [...(source.ai_target_bbox_norm || source.target_bbox_norm)],
        drag: null,
      };
      const loaded = new Promise((resolve, reject) => {
        elements.cropSource.onload = resolve;
        elements.cropSource.onerror = () => reject(new Error("Unable to load the verified pre-action frame."));
      });
      elements.cropSource.src = `${source.image_url}?sha256=${encodeURIComponent(source.source_sha256)}`;
      elements.cropDialog.showModal();
      await loaded;
      renderCrop();
      setStatus("Adjust the Target ROI, then apply and save the workflow.", "ok");
    } catch (error) {
      state.crop = null;
      if (elements.cropDialog.open) elements.cropDialog.close();
      setStatus(`Crop source unavailable: ${error.message}`, "error");
    }
  }

  function closeCropEditor() {
    state.crop = null;
    elements.cropSource.removeAttribute("src");
    if (elements.cropDialog.open) elements.cropDialog.close();
  }

  function canvasBlob(canvas) {
    return new Promise((resolve, reject) => canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("Unable to encode the crop as PNG.")),
      "image/png",
    ));
  }

  async function boundedCropBlob() {
    let source = elements.cropPreview;
    let blob = await canvasBlob(source);
    while (blob.size > 256 * 1024 && Math.max(source.width, source.height) > 64) {
      const scale = Math.max(64 / Math.max(source.width, source.height), 0.82);
      const reduced = document.createElement("canvas");
      reduced.width = Math.max(1, Math.floor(source.width * scale));
      reduced.height = Math.max(1, Math.floor(source.height * scale));
      reduced.getContext("2d").drawImage(source, 0, 0, reduced.width, reduced.height);
      source = reduced;
      blob = await canvasBlob(source);
    }
    if (blob.size > 256 * 1024) throw new Error("The cropped PNG exceeds 256 KiB. Select a smaller Target ROI.");
    return blob;
  }

  async function applyCrop() {
    if (!state.crop) return;
    elements.cropApply.disabled = true;
    try {
      const stepId = state.crop.stepId;
      const step = state.workflow.steps.find((item) => item.step_id === stepId);
      const existing = Array.isArray(step?.action?.image_candidates) ? step.action.image_candidates : [];
      const dimensions = model.cropPixelRect(
        state.crop.box,
        elements.cropSource.naturalWidth,
        elements.cropSource.naturalHeight,
      );
      const candidate = {
        ...await imageCandidate(await boundedCropBlob(), "manual_target"),
        crop_origin: [dimensions.source_x, dimensions.source_y],
      };
      let workflow = model.updateStepField(
        state.workflow,
        stepId,
        ["action", "image_candidates"],
        [candidate, ...existing.slice(1)],
      );
      workflow = model.updateStepField(workflow, stepId, ["action", "target_bbox_norm"], [...state.crop.box]);
      workflow = model.updateStepField(workflow, stepId, ["action", "ai_target_bbox_norm"], [...state.crop.aiBox]);
      workflow = model.updateStepField(workflow, stepId, ["action", "locator_origin"], "manual_crop");
      closeCropEditor();
      markDirty(workflow, stepId);
      setStatus("Target crop applied locally. Save the workflow to persist it.", "warning");
    } catch (error) {
      setStatus(`Crop apply failed: ${error.message}`, "error");
    } finally {
      elements.cropApply.disabled = false;
    }
  }

  elements.list.addEventListener("click", async (event) => {
    const expand = event.target.closest("[data-expand-step]");
    if (expand) {
      const stepId = expand.dataset.expandStep;
      state.selectedStepId = stepId;
      state.expandedStepId = state.expandedStepId === stepId ? "" : stepId;
      renderEditor();
      return;
    }
    const command = event.target.closest("[data-step-command]");
    if (!command) return;
    const stepId = command.dataset.stepId;
    const index = state.workflow.steps.findIndex((step) => step.step_id === stepId);
    try {
      if (command.dataset.stepCommand === "up") markDirty(model.moveStep(state.workflow, stepId, index - 1), stepId);
      if (command.dataset.stepCommand === "down") markDirty(model.moveStep(state.workflow, stepId, index + 1), stepId);
      if (command.dataset.stepCommand === "duplicate") {
        const next = model.duplicateStep(state.workflow, stepId);
        markDirty(next, next.steps[index + 1].step_id);
      }
      if (command.dataset.stepCommand === "delete") markDirty(model.deleteStep(state.workflow, stepId), state.workflow.steps[Math.max(0, index - 1)]?.step_id || "");
      if (command.dataset.stepCommand === "test") await testStep(stepId);
      if (command.dataset.stepCommand === "crop") await openCropEditor(stepId);
    } catch (error) { setStatus(error.message, "error"); }
  });

  elements.list.addEventListener("change", async (event) => {
    const input = event.target;
    const stepId = input.dataset.stepId;
    if (input.dataset.locatorStep) {
      try {
        const candidate = await imageCandidate(input.files[0]);
        markDirty(model.updateStepField(state.workflow, input.dataset.locatorStep, ["action", "image_candidates"], [candidate]), input.dataset.locatorStep);
      } catch (error) { setStatus(error.message, "error"); }
      return;
    }
    if (!stepId || !state.editable) return;
    if (input.hasAttribute("data-action-type")) {
      markDirty(model.updateStepField(state.workflow, stepId, ["action"], model.actionDefaults(input.value)), stepId);
      return;
    }
    const path = String(input.dataset.fieldPath || "").split(".").filter(Boolean);
    if (path.length) markDirty(model.updateStepField(state.workflow, stepId, path, typedValue(input)), stepId);
  });

  elements.list.addEventListener("dragstart", (event) => {
    const card = event.target.closest("[data-step-card]");
    if (card) event.dataTransfer.setData("text/plain", card.dataset.stepCard);
  });
  elements.list.addEventListener("dragover", (event) => event.preventDefault());
  elements.list.addEventListener("drop", (event) => {
    event.preventDefault();
    const target = event.target.closest("[data-step-card]");
    const stepId = event.dataTransfer.getData("text/plain");
    if (!target || !stepId || !state.editable) return;
    const targetIndex = state.workflow.steps.findIndex((step) => step.step_id === target.dataset.stepCard);
    markDirty(model.moveStep(state.workflow, stepId, targetIndex), stepId);
  });

  elements.add.addEventListener("click", () => {
    if (!state.editable) return;
    const reference = state.selectedStepId || state.workflow.steps.at(-1)?.step_id || "";
    const next = model.insertStep(state.workflow, reference, "after", elements.addAction.value);
    const referenceIndex = next.steps.findIndex((step) => step.step_id === reference);
    markDirty(next, next.steps[Math.min(referenceIndex + 1, next.steps.length - 1)].step_id);
  });
  elements.check.addEventListener("click", () => checkWorkflow().catch((error) => setStatus(error.message, "error")));
  elements.save.addEventListener("click", () => saveWorkflow());
  elements.close.addEventListener("click", () => {
    if (!state.dirty || window.confirm("Close and discard unsaved workflow changes?")) window.close();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  elements.cropBox.addEventListener("pointerdown", (event) => {
    if (!state.crop) return;
    event.preventDefault();
    const handle = event.target.closest("[data-crop-handle]")?.dataset.cropHandle || "move";
    const sourceRect = elements.cropSource.getBoundingClientRect();
    state.crop.drag = {
      pointerId: event.pointerId,
      handle,
      startX: event.clientX,
      startY: event.clientY,
      sourceWidth: sourceRect.width,
      sourceHeight: sourceRect.height,
      startBox: [...state.crop.box],
    };
    elements.cropBox.setPointerCapture(event.pointerId);
  });

  elements.cropBox.addEventListener("pointermove", (event) => {
    const drag = state.crop?.drag;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = (event.clientX - drag.startX) / Math.max(1, drag.sourceWidth);
    const deltaY = (event.clientY - drag.startY) / Math.max(1, drag.sourceHeight);
    state.crop.box = model.adjustCropBox(drag.startBox, drag.handle, deltaX, deltaY);
    renderCrop();
  });

  function endCropDrag(event) {
    if (!state.crop?.drag || state.crop.drag.pointerId !== event.pointerId) return;
    state.crop.drag = null;
    if (elements.cropBox.hasPointerCapture(event.pointerId)) elements.cropBox.releasePointerCapture(event.pointerId);
  }

  elements.cropBox.addEventListener("pointerup", endCropDrag);
  elements.cropBox.addEventListener("pointercancel", endCropDrag);
  elements.cropReset.addEventListener("click", () => {
    if (!state.crop) return;
    state.crop.box = [...state.crop.aiBox];
    renderCrop();
  });
  elements.cropApply.addEventListener("click", () => applyCrop());
  elements.cropCancel.addEventListener("click", closeCropEditor);
  elements.cropDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeCropEditor();
  });

  loadWorkflow().catch(() => {});
})();
