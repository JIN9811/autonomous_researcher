(function equipmentSkillFlowModelFactory(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ATREquipmentSkillFlow = api;
})(typeof globalThis !== "undefined" ? globalThis : window, function equipmentSkillFlowModel() {
  "use strict";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function empty(profileId) {
    return {
      schema: "atr.equipment_skill_flow.v1",
      flow_id: profileId,
      profile_id: profileId,
      version: 1,
      enabled: true,
      agentic_task_id: "",
      blocks: [],
    };
  }

  function uniqueId(flow) {
    const ids = new Set((flow.blocks || []).map((block) => block.id));
    let index = 1;
    while (ids.has(`block_${String(index).padStart(2, "0")}`)) index += 1;
    return `block_${String(index).padStart(2, "0")}`;
  }

  function rebuildSequence(flow) {
    flow.blocks.forEach((block, index) => {
      const success = index === flow.blocks.length - 1 ? "__complete__" : "next";
      block.agentic = { ...(block.agentic || {}), completed: success, failed: "__blocked__" };
      block.vision = {
        ...(block.vision || {}),
        detected: success,
        not_detected: "__blocked__",
        timeout: "__blocked__",
        error: "__blocked__",
      };
    });
    return flow;
  }

  function addBlock(input, skill = {}) {
    const flow = clone(input);
    flow.blocks = Array.isArray(flow.blocks) ? flow.blocks : [];
    flow.blocks.push({
      id: uniqueId(flow),
      label: "Equipment Task",
      skill: {
        skill_id: skill.skill_id || "",
        skill_version: skill.version || skill.skill_version || "",
      },
      agentic: { task: "Equipment Task", completed: "__complete__", failed: "__blocked__" },
      vision: {
        enabled: false,
        task_id: "",
        detected: "__complete__",
        not_detected: "__blocked__",
        timeout: "__blocked__",
        error: "__blocked__",
      },
    });
    flow.version = Number(flow.version || 0) + 1;
    return rebuildSequence(flow);
  }

  function removeBlock(input, blockId) {
    const flow = clone(input);
    flow.blocks = (flow.blocks || []).filter((block) => block.id !== blockId);
    flow.version = Number(flow.version || 0) + 1;
    return rebuildSequence(flow);
  }

  function moveBlock(input, blockId, delta) {
    const flow = clone(input);
    const index = (flow.blocks || []).findIndex((block) => block.id === blockId);
    const target = index + Number(delta || 0);
    if (index < 0 || target < 0 || target >= flow.blocks.length) return flow;
    const [block] = flow.blocks.splice(index, 1);
    flow.blocks.splice(target, 0, block);
    flow.version = Number(flow.version || 0) + 1;
    return rebuildSequence(flow);
  }

  function setPath(object, path, value) {
    const parts = path.split(".");
    let target = object;
    while (parts.length > 1) {
      const key = parts.shift();
      target[key] = target[key] && typeof target[key] === "object" ? target[key] : {};
      target = target[key];
    }
    target[parts[0]] = value;
  }

  function updateBlock(input, blockId, field, value) {
    const flow = clone(input);
    const block = (flow.blocks || []).find((item) => item.id === blockId);
    if (!block) return flow;
    setPath(block, field, value);
    if (field === "agentic.task") block.label = value;
    flow.version = Number(flow.version || 0) + 1;
    return rebuildSequence(flow);
  }

  function applyTemplate(input, template) {
    const current = clone(input || {});
    const draft = clone(template || {});
    return rebuildSequence({
      ...draft,
      schema: current.schema || draft.schema || "atr.equipment_skill_flow.v1",
      flow_id: current.flow_id || current.profile_id || draft.flow_id,
      profile_id: current.profile_id || draft.profile_id,
      version: Number(current.version || 1),
      enabled: current.enabled !== false,
      agentic_task_id: String(draft.agentic_task_id || ""),
      blocks: Array.isArray(draft.blocks) ? draft.blocks : [],
    });
  }

  return { empty, addBlock, removeBlock, moveBlock, updateBlock, applyTemplate };
});
