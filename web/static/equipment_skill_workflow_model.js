(function equipmentSkillWorkflowModelFactory(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.EquipmentSkillWorkflowModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildWorkflowModel() {
  "use strict";

  const ACTION_LABELS = Object.freeze({
    click: "Click",
    double_click: "Double click",
    drag_to: "Drag",
    hotkey: "Hotkey",
    hscroll: "Horizontal scroll",
    move_to: "Move pointer",
    press: "Press key",
    screenshot: "Screenshot",
    scroll: "Scroll",
    wait: "Wait",
    wait_for_file: "Wait for file",
    wait_until: "Wait until",
    wait_until_image: "Wait for image",
    wait_until_text: "Wait for text",
    write: "Write text",
  });

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function normalizeWorkflowState(workflow) {
    const normalized = clone(workflow || {});
    normalized.steps = Array.isArray(normalized.steps) ? normalized.steps : [];
    normalized.program_ids = [];
    return normalized;
  }

  function findStepIndex(workflow, stepId) {
    return (workflow.steps || []).findIndex((step) => step.step_id === stepId);
  }

  function nextStepId(steps) {
    const used = new Set((steps || []).map((step) => String(step.step_id || "")));
    let ordinal = 1;
    while (used.has(`step-${String(ordinal).padStart(3, "0")}`)) {
      ordinal += 1;
    }
    return `step-${String(ordinal).padStart(3, "0")}`;
  }

  function actionDefaults(actionName) {
    const defaults = {
      click: { action: "click", x: 0, y: 0, button: "left" },
      double_click: { action: "double_click", x: 0, y: 0, button: "left" },
      drag_to: { action: "drag_to", x: 0, y: 0, duration_sec: 0.5, button: "left" },
      hotkey: { action: "hotkey", keys: ["ctrl", "s"] },
      hscroll: { action: "hscroll", clicks: 1 },
      move_to: { action: "move_to", x: 0, y: 0, duration_sec: 0.2 },
      press: { action: "press", key: "enter", presses: 1, interval: 0 },
      screenshot: { action: "screenshot", checkpoint: "checkpoint" },
      scroll: { action: "scroll", clicks: 1 },
      wait: { action: "wait", seconds: 1 },
      wait_for_file: { action: "wait_for_file", pattern: "", timeout_s: 30, poll_interval_s: 0.5 },
      wait_until: { action: "wait_until", target: "", timeout_s: 30, poll_interval_s: 0.5 },
      wait_until_image: { action: "wait_until_image", target: "", timeout_s: 30, poll_interval_s: 0.5, required: true },
      wait_until_text: { action: "wait_until_text", target: "", text: "", timeout_s: 30, poll_interval_s: 0.5, required: true },
      write: { action: "write", text: "", interval: 0.02 },
    };
    return clone(defaults[actionName] || defaults.wait);
  }

  function moveStep(workflow, stepId, targetIndex) {
    const next = normalizeWorkflowState(workflow);
    const sourceIndex = findStepIndex(next, stepId);
    if (sourceIndex < 0) return next;
    const [step] = next.steps.splice(sourceIndex, 1);
    const boundedIndex = Math.max(0, Math.min(Number(targetIndex) || 0, next.steps.length));
    next.steps.splice(boundedIndex, 0, step);
    return next;
  }

  function duplicateStep(workflow, stepId) {
    const next = normalizeWorkflowState(workflow);
    const sourceIndex = findStepIndex(next, stepId);
    if (sourceIndex < 0) return next;
    const duplicate = clone(next.steps[sourceIndex]);
    duplicate.step_id = nextStepId(next.steps);
    duplicate.label = `${duplicate.label || ACTION_LABELS[duplicate.action?.action] || "Step"} copy`;
    next.steps.splice(sourceIndex + 1, 0, duplicate);
    return next;
  }

  function insertStep(workflow, referenceStepId, position, actionName) {
    const next = normalizeWorkflowState(workflow);
    const referenceIndex = findStepIndex(next, referenceStepId);
    const insertionIndex = referenceIndex < 0
      ? next.steps.length
      : referenceIndex + (position === "before" ? 0 : 1);
    const action = actionDefaults(actionName);
    next.steps.splice(insertionIndex, 0, {
      step_id: nextStepId(next.steps),
      label: ACTION_LABELS[action.action] || "Step",
      action,
      checkpoint_after: false,
    });
    return next;
  }

  function deleteStep(workflow, stepId) {
    const next = normalizeWorkflowState(workflow);
    if (next.steps.length <= 1) {
      throw new Error("Workflow must retain at least one step.");
    }
    const index = findStepIndex(next, stepId);
    if (index >= 0) next.steps.splice(index, 1);
    return next;
  }

  function updateStepField(workflow, stepId, path, value) {
    const next = normalizeWorkflowState(workflow);
    const index = findStepIndex(next, stepId);
    if (index < 0) return next;
    let cursor = next.steps[index];
    path.slice(0, -1).forEach((part) => {
      if (!cursor[part] || typeof cursor[part] !== "object") cursor[part] = {};
      cursor = cursor[part];
    });
    cursor[path[path.length - 1]] = value;
    return next;
  }

  function durationBounds(workflow) {
    return (workflow.steps || []).reduce((bounds, step) => {
      const action = step.action || {};
      if (action.action === "wait") {
        const seconds = Number(action.seconds) || 0;
        bounds.minimum_s += seconds;
        bounds.maximum_s += seconds;
      } else if (["wait_until", "wait_until_image", "wait_until_text", "wait_for_file"].includes(action.action)) {
        bounds.maximum_s += Number(action.timeout_s) || 0;
      }
      return bounds;
    }, { minimum_s: 0, maximum_s: 0 });
  }

  function roundCropValue(value) {
    return Math.round(value * 1000000) / 1000000;
  }

  function adjustCropBox(box, handle, deltaX, deltaY, minSize = 0.01) {
    let [x, y, width, height] = (Array.isArray(box) ? box : [0, 0, 1, 1]).map(Number);
    const dx = Number(deltaX) || 0;
    const dy = Number(deltaY) || 0;
    const minimum = Math.max(0.001, Math.min(1, Number(minSize) || 0.01));
    const right = x + width;
    const bottom = y + height;

    if (handle === "move") {
      x = Math.max(0, Math.min(1 - width, x + dx));
      y = Math.max(0, Math.min(1 - height, y + dy));
    } else {
      if (handle.includes("w")) x = Math.max(0, Math.min(right - minimum, x + dx));
      if (handle.includes("e")) width = Math.max(minimum, Math.min(1 - x, width + dx));
      if (handle.includes("n")) y = Math.max(0, Math.min(bottom - minimum, y + dy));
      if (handle.includes("s")) height = Math.max(minimum, Math.min(1 - y, height + dy));
      if (handle.includes("w")) width = right - x;
      if (handle.includes("n")) height = bottom - y;
    }
    return [x, y, width, height].map(roundCropValue);
  }

  function cropOutputSize(box, sourceWidth, sourceHeight, maxSide = 512) {
    const rect = cropPixelRect(box, sourceWidth, sourceHeight, maxSide);
    return {
      source_width: rect.source_width,
      source_height: rect.source_height,
      output_width: rect.output_width,
      output_height: rect.output_height,
    };
  }

  function cropPixelRect(box, sourceWidth, sourceHeight, maxSide = 512) {
    const normalized = Array.isArray(box) ? box.map(Number) : [0, 0, 1, 1];
    const fullWidth = Math.max(1, Math.round(Number(sourceWidth) || 1));
    const fullHeight = Math.max(1, Math.round(Number(sourceHeight) || 1));
    const source_x = Math.max(0, Math.min(fullWidth - 1, Math.round(fullWidth * normalized[0])));
    const source_y = Math.max(0, Math.min(fullHeight - 1, Math.round(fullHeight * normalized[1])));
    const right = Math.max(source_x + 1, Math.min(fullWidth, Math.round(fullWidth * (normalized[0] + normalized[2]))));
    const bottom = Math.max(source_y + 1, Math.min(fullHeight, Math.round(fullHeight * (normalized[1] + normalized[3]))));
    const source_width = right - source_x;
    const source_height = bottom - source_y;
    const limit = Math.max(1, Number(maxSide) || 512);
    const scale = Math.min(1, limit / Math.max(source_width, source_height));
    return {
      source_x,
      source_y,
      source_width,
      source_height,
      output_width: Math.max(1, Math.round(source_width * scale)),
      output_height: Math.max(1, Math.round(source_height * scale)),
    };
  }

  function actionSummary(step) {
    const action = step.action || {};
    const label = ACTION_LABELS[action.action] || action.action || "Unknown action";
    if (action.action === "wait") return `${label} · ${Number(action.seconds) || 0}s`;
    if (["wait_until", "wait_until_image", "wait_until_text"].includes(action.action)) {
      return `${label} · ${action.target || action.text || "target"} · ${Number(action.timeout_s) || 0}s`;
    }
    if (action.action === "wait_for_file") return `${label} · ${action.pattern || "pattern"} · ${Number(action.timeout_s) || 0}s`;
    if (["move_to", "click", "double_click", "drag_to"].includes(action.action)) return `${label} · (${action.x}, ${action.y})`;
    if (action.action === "write") return `${label} · ${String(action.text || "").slice(0, 40)}`;
    if (action.action === "press") return `${label} · ${action.key || "key"}`;
    if (action.action === "hotkey") return `${label} · ${(action.keys || []).join("+")}`;
    return label;
  }

  return Object.freeze({
    ACTION_LABELS,
    actionDefaults,
    actionSummary,
    adjustCropBox,
    cropOutputSize,
    cropPixelRect,
    deleteStep,
    duplicateStep,
    durationBounds,
    insertStep,
    moveStep,
    normalizeWorkflowState,
    updateStepField,
  });
});
