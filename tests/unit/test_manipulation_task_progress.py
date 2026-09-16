from utils.manipulation_execution import task_progress_counts


def test_verified_execution_counts_exclude_joint_cycles_and_pending_from_rate():
    state = {"run_id":"r", "run_metadata":{"manipulation_execution":{
        "run_id":"r", "loop_id":0, "session_id":"s", "state":"done", "success":True},
        "utm_clear_execution":{"run_id":"r","loop_id":0,"session_id":"c","state":"waiting","success":None}}}
    counts = task_progress_counts(state)
    assert counts["attempt_count"] == 2
    assert counts["success_count"] == 1
    assert counts["pending_count"] == 1
    assert counts["success_rate"] == 1
    state["run_metadata"]["utm_clear_execution"].update(state="error",success=False)
    assert task_progress_counts(state)["success_rate"] == .5
    state["run_id"] = "different"
    assert task_progress_counts(state)["success_rate"] is None
