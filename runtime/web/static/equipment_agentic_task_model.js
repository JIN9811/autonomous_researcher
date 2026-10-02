(function equipmentAgenticTaskModelFactory(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ATREquipmentAgenticTaskModel = api;
})(typeof globalThis !== "undefined" ? globalThis : window, function equipmentAgenticTaskModel() {
  "use strict";

  const BLOCK_LABELS = {
    prepare_next_specimen: "Move Jigs for Next Specimen",
    start_test: "Start Test",
    monitor_contact_and_run: "Monitor contact and compression",
    await_auto_return: "Wait for automatic Height return",
    save_raw_data: "Save Raw Data CSV",
    validate_raw_data: "Validate Raw Data CSV",
    advance_without_save: "Next Test without saving current test",
    restore_robot_clearance: "Restore robot-entry clearance",
  };

  function object(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function cycleContext(payload) {
    const source = object(payload);
    const report = object(source.equipment_report);
    const task = object(source.workflow_agentic_task && source.workflow_agentic_task.task_id
      ? source.workflow_agentic_task
      : report.workflow_agentic_task);
    if (!task.task_id) return { available: false };
    return {
      available: true,
      task,
      blockExecutions: Array.isArray(source.block_executions)
        ? source.block_executions
        : Array.isArray(report.block_executions)
          ? report.block_executions
          : [],
      methodValues: object(source.method_values && Object.keys(source.method_values).length ? source.method_values : report.method_values),
      screenTransitions: Array.isArray(source.screen_transition_evidence)
        ? source.screen_transition_evidence
        : Array.isArray(report.screen_transition_evidence)
          ? report.screen_transition_evidence
          : [],
      rawDataExport: object(source.raw_data_export && Object.keys(source.raw_data_export).length ? source.raw_data_export : report.raw_data_export),
      nextSpecimenReadiness: object(source.next_specimen_readiness && Object.keys(source.next_specimen_readiness).length ? source.next_specimen_readiness : report.next_specimen_readiness),
      handoffEligibility: object(source.handoff_eligibility && Object.keys(source.handoff_eligibility).length ? source.handoff_eligibility : report.handoff_eligibility),
    };
  }

  function progressStatus(skill, activeBlock, blockId) {
    const outcome = String(skill && (skill.status || skill.outcome) || "").toLowerCase();
    if (["completed", "complete", "success", "passed"].includes(outcome)) return "complete";
    if (["failed", "blocked", "error", "timeout"].includes(outcome)) return "blocked";
    if (["active", "running", "executing", "started"].includes(outcome) || activeBlock === blockId) return "active";
    return "waiting";
  }

  function progressSteps(ctx) {
    if (!ctx || !ctx.available) return [];
    const order = Array.isArray(ctx.task.block_order) ? ctx.task.block_order : [];
    return order.map((blockId) => {
      const entries = ctx.blockExecutions.filter((item) => String(item && item.block_id || "") === blockId);
      const grouped = entries.find((item) => item && item.status && !item.phase) || {};
      const skill = entries.find((item) => item && item.phase === "skill") || object(grouped.skill);
      const vision = entries.find((item) => item && item.phase === "vision") || object(grouped.vision);
      const visionEnabled = vision.enabled === true || vision.vision_link_enabled === true;
      const visionOutcome = String(vision.outcome || (visionEnabled ? "waiting" : "bypass"));
      const visionStatus = !visionEnabled || ["bypass", "waiting", "pending"].includes(visionOutcome.toLowerCase())
        ? "waiting"
        : ["detected", "completed", "complete", "success", "passed", "verified"].includes(visionOutcome.toLowerCase())
          ? "success"
          : "failed";
      const skillId = String(skill.skill_id || grouped.skill_id || "");
      const skillVersion = String(skill.skill_version || grouped.skill_version || "");
      return {
        blockId,
        label: String(grouped.task || skill.task || BLOCK_LABELS[blockId] || blockId),
        status: progressStatus(grouped.status ? grouped : skill, String(ctx.task.active_block || ""), blockId),
        skill: skillId ? `${skillId}${skillVersion ? `@${skillVersion}` : ""}` : "unbound",
        vision: {
          optional: true,
          enabled: visionEnabled,
          blocking: vision.blocking !== false,
          outcome: visionOutcome,
          status: visionStatus,
          label: String(vision.verification_label || vision.result_label || ""),
          taskId: String(vision.vision_task_id || vision.task_id || ""),
        },
      };
    });
  }

  function methodRows(ctx) {
    const values = ctx && ctx.available ? object(ctx.methodValues) : {};
    return ["Force", "Stroke", "Height"].map((label) => {
      const item = object(values[label]);
      return {
        label,
        observed: item.observed === undefined ? null : item.observed,
        target: item.target === undefined ? null : item.target,
      };
    });
  }

  function rawData(ctx) {
    return ctx && ctx.available ? { ...object(ctx.rawDataExport) } : {};
  }

  function readiness(ctx) {
    return ctx && ctx.available ? { ...object(ctx.nextSpecimenReadiness) } : {};
  }

  return { cycleContext, progressSteps, methodRows, rawData, readiness };
});
