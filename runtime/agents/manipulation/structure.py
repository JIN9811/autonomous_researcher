"""Source-bound CODE relationships; these are not additional execution stages."""
from agents.control_structure import implementation_detail as detail

A = "agents/manipulation/agent.py"
D = "agents/manipulation/decision.py"
C = "utils/utm_clear_cycle.py"


def manipulation_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "manipulation.task": detail([
            ("task", "Existing task admission and dispatch", "middle", A, "ManipulationAgent._run_task"),
            ("preflight", "Preflight and post-decision freshness recheck", "guardian", A, "ManipulationAgent._preflight"),
            ("choice", "LLM bounded skill selection", "high", D, "select_manipulation_tool"),
            ("once", "Persistent task start claim", "guardian", D, "claim_skill_execution"),
            ("rollout", "Rollout status recovery", "middle", A, "ManipulationAgent._refresh_existing_rollout_status"),
            ("stop", "Stop rollout for verified completion", "middle", A, "ManipulationAgent._stop_rollout_for_completion"),
            ("robot", "LeRobot rollout, replay and stop boundary", "low", "device_bridges/lerobot/bridge.py", "LeRobotBridge"),
            ("clear", "Existing UTM clear-cycle dispatch", "middle", C, "run_clear_manipulation"),
            ("clear_scope", "Same-cycle Equipment handoff admission", "guardian", C, "current_clear"),
            ("verification", "Deterministic Vision verification gate", "guardian", A, "ManipulationAgent._verification_status"),
            ("review", "LLM post-Vision result review", "high", D, "review_manipulation_result"),
            ("evidence", "Rollout evidence references", "knowledge", A, "ManipulationAgent._evidence_refs"),
        ], [("$operation", "task", "call", "unchanged composite task"),
            ("task", "clear_scope", "validation", "clear dispatch comes first"),
            ("clear_scope", "clear", "call", "same-cycle clear branch"),
            ("clear", "robot", "call", "existing replay path"),
            ("clear", "choice", "call", "clear skill selection"),
            ("task", "preflight", "validation", "initial and post-model recheck"),
            ("task", "choice", "call", "configured skill only"),
            ("choice", "once", "validation", "claim before uncertain start"),
            ("task", "robot", "call", "selected rollout execution"),
            ("task", "rollout", "call", "existing completion recovery"),
            ("rollout", "robot", "call", "refresh status"),
            ("task", "stop", "call", "verified completion stop"),
            ("stop", "robot", "call", "stop boundary"),
            ("task", "verification", "validation", "Vision completion evidence"),
            ("verification", "review", "evidence", "execution ended and Vision accepted"),
            ("task", "evidence", "evidence", "execution artifacts")]),
        "manipulation.deliver": detail([
            ("report", "Manipulation task report", "knowledge", A, "ManipulationAgent._manipulation_report"),
            ("screen", "Runtime report snapshot", "knowledge", A, "ManipulationAgent._manipulation_agent_report_snapshot"),
            ("packet", "Robot task handoff result", "knowledge", A, "ManipulationAgent._robot_task_result"),
            ("projection", "Owner report projection", "knowledge", "agents/manipulation/presentation.py", "project_manipulation_report"),
            ("archive", "Public run archive wrapper", "knowledge", "utils/agent_artifact_archive.py", "archive_agent_run"),
        ], [("report", "$operation", "evidence", "original owner AgentResult"),
            ("screen", "projection", "evidence", "runtime report fields"),
            ("packet", "projection", "evidence", "handoff and decisions"),
            ("report", "projection", "evidence", "metadata and payload precedence"),
            ("$operation", "archive", "evidence", "public run archives once")]),
    }}
