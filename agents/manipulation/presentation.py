"""Owner report projection preserving metadata and payload precedence."""

# Read-only report input contract; unlisted state is never copied for this view.
REPORT_METADATA_KEYS = ["latest_manipulation_agent_report","manipulation_report","robot_task_result","manipulation_metrics"]
REPORT_STATE_FIELDS = []

REPORT_PROFILE = {
        "title": "Manipulation Agent / Runtime Supervision",
        "summary": "Supervises bounded LeRobot policy skills, preflight readiness, task stages, Vision verification dependency, and robot_task_result handoff.",
        "focus_rows": [
            {"label": "Task", "value": "transfer_to_utm or clear_utm_to_disposal with source/target/terminal pose"},
            {"label": "Policy boundary", "value": "LeRobot bridge executes; Manipulation Agent supervises stage, safety, and handoff"},
            {"label": "Task stages", "value": "current stage, completed stages, and post-place verification"},
        ],
        "checklist": ["Confirm Vision freshness", "Validate robot/profile/policy preflight", "Run bounded rollout", "Check task stages", "Require post-place Vision verification"],
    }


def project_manipulation_report(metadata: dict, agent_payload: dict) -> dict:
    role_specific = {}
    report_decisions = []
    report_metrics = {}
    manipulation_report = None
    manipulation_agent_report = None
    robot_task_result = None
    if isinstance(metadata.get("latest_manipulation_agent_report"), dict):
        manipulation_agent_report = metadata["latest_manipulation_agent_report"]
    elif isinstance(agent_payload.get("manipulation_agent_report"), dict):
        manipulation_agent_report = agent_payload["manipulation_agent_report"]
    if isinstance(metadata.get("manipulation_report"), dict):
        manipulation_report = metadata["manipulation_report"]
    elif isinstance(agent_payload.get("manipulation_report"), dict):
        manipulation_report = agent_payload["manipulation_report"]
    if isinstance(metadata.get("robot_task_result"), dict):
        robot_task_result = metadata["robot_task_result"]
    elif isinstance(agent_payload.get("robot_task_result"), dict):
        robot_task_result = agent_payload["robot_task_result"]
    if isinstance(manipulation_report, dict):
        task = manipulation_report.get("task") if isinstance(manipulation_report.get("task"), dict) else {}
        role_specific["summary"] = "Bounded policy execution, preflight readiness, execution supervision, Vision dependency, and robot_task_result handoff evidence."
        role_specific["task"] = task
        role_specific["skill_episode_board"] = {
            "task_id": task.get("task_id", ""),
            "skill_id": robot_task_result.get("skill_id", "") if isinstance(robot_task_result, dict) else "",
            "episode_id": robot_task_result.get("episode_id", "") if isinstance(robot_task_result, dict) else manipulation_report.get("session_id", ""),
            "terminal_pose": robot_task_result.get("terminal_pose", "") if isinstance(robot_task_result, dict) else "",
            "handoff_status": robot_task_result.get("handoff_status", "") if isinstance(robot_task_result, dict) else "",
            "completion_status": robot_task_result.get("completion_status", "") if isinstance(robot_task_result, dict) else "",
        }
        role_specific["policy_plan"] = manipulation_report.get("policy_plan", {})
        role_specific["preflight"] = manipulation_report.get("preflight", {})
        role_specific["vision_context"] = manipulation_report.get("vision_context", {})
        role_specific["rollout_runtime"] = manipulation_report.get("rollout_runtime", {})
        role_specific["stage_machine"] = manipulation_report.get("stage_machine", {})
        role_specific["decision"] = manipulation_report.get("decision", {})
        role_specific["knowledge_payload"] = manipulation_report.get("knowledge_payload", {})
        role_specific["handoff_packet"] = robot_task_result if isinstance(robot_task_result, dict) else manipulation_report.get("handoff_packet", {})
        if isinstance(manipulation_agent_report, dict):
            role_specific["manipulation_agent_report"] = manipulation_agent_report
        report_decisions = robot_task_result.get("decisions", []) if isinstance(robot_task_result, dict) and isinstance(robot_task_result.get("decisions"), list) else agent_payload.get("decisions", []) if isinstance(agent_payload.get("decisions"), list) else []
        report_metrics = metadata.get("manipulation_metrics") if isinstance(metadata.get("manipulation_metrics"), dict) else agent_payload.get("metrics", {}) if isinstance(agent_payload.get("metrics"), dict) else {}
    return {"role_specific": role_specific, "decisions": report_decisions, "metrics": report_metrics,
        "manipulation_report": manipulation_report, "manipulation_agent_report": manipulation_agent_report,
        "robot_task_result": robot_task_result}
