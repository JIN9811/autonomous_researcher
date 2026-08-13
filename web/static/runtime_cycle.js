/* Shared runtime-cycle formatter. The backend cycle contract is authoritative. */
(function attachRuntimeCycle(global) {
  "use strict";

  function positiveInteger(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric > 0 ? Math.floor(numeric) : 0;
  }

  function total(state = {}) {
    const metadata = state.run_metadata && typeof state.run_metadata === "object" ? state.run_metadata : {};
    const planning = metadata.planning_cycle_contract && typeof metadata.planning_cycle_contract === "object"
      ? metadata.planning_cycle_contract
      : {};
    const resume = metadata.planning_resume_context && typeof metadata.planning_resume_context === "object"
      ? metadata.planning_resume_context
      : {};
    const mission = metadata.latest_mission_contract && typeof metadata.latest_mission_contract === "object"
      ? metadata.latest_mission_contract
      : (metadata.mission_contract && typeof metadata.mission_contract === "object" ? metadata.mission_contract : {});
    const missionBudget = mission.safety_budget && typeof mission.safety_budget === "object" ? mission.safety_budget : {};
    const safetyBudget = metadata.safety_budget && typeof metadata.safety_budget === "object" ? metadata.safety_budget : {};
    const authoritativeCandidates = [
      planning.total_cycles,
      resume.total_cycles,
      safetyBudget.max_loop_count,
    ];
    for (const value of authoritativeCandidates) {
      const resolved = positiveInteger(value);
      if (resolved) return resolved;
    }
    // A baseline mission contract uses one cycle to mean "not yet bounded".
    const legacyMissionTotal = positiveInteger(missionBudget.max_loop_count);
    if (legacyMissionTotal > 1) return legacyMissionTotal;
    return 0;
  }

  function current(state = {}, running = false) {
    const stage = String(state.stage || "idle").toLowerCase();
    const completed = Math.max(0, Number(state.loop_count || 0));
    const active = Boolean(running && !["complete", "error", "idle"].includes(stage));
    return Math.max(active ? completed + 1 : completed, 0);
  }

  function cycleMode(state = {}) {
    const metadata = state.run_metadata && typeof state.run_metadata === "object" ? state.run_metadata : {};
    const planning = metadata.planning_cycle_contract && typeof metadata.planning_cycle_contract === "object"
      ? metadata.planning_cycle_contract
      : {};
    return String(planning.mode || state.mode || "").toLowerCase();
  }

  function format(state = {}, running = false, options = {}) {
    const prefix = String(options.prefix ?? "C:");
    const cycle = current(state, running);
    const cycleTotal = cycleMode(state) === "test" ? total(state) : 0;
    return `${prefix}${cycle}${cycleTotal ? `/${cycleTotal}` : ""}`;
  }

  global.ATRRuntimeCycle = Object.freeze({ current, format, total });
})(window);
