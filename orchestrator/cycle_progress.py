"""Count completed experiment cycles, not Guardian review attempts."""


def record_guardian_completion(state):
    context = state.run_metadata.get("_planning_resume_context") or {}
    cycle = context.get("cycle_index")
    current = state.current_experiment_spec or {}
    saved = context.get("current_spec") or {}
    if (context.get("kind") == "planning_cycle_series"
            and context.get("phase") == "tail"
            and isinstance(cycle, int) and not isinstance(cycle, bool) and cycle > 0
            and current.get("specimen_id")
            and saved.get("specimen_id") == current["specimen_id"]):
        # Re-running Guardian for this specimen completes the same cycle again.
        # The series index is authoritative, including after legacy count drift.
        state.loop_count = cycle
    else:
        state.loop_count += 1
