"""Existing ORC run-bound functions, decision tools, checks and evidence.

Core Chat/Setup semantic intake remains outside the run() graph. Handler effects
are supplied by the existing caller; this declaration grants no device access.
"""
from agents.control_structure import implementation_detail as detail

S = "orchestrator/supervisor.py"
D = "agents/orchestrator_decision.py"
K = "agents/knowledge_context.py"


def orchestrator_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "orchestrator.mission": detail([
            ("contract", "Accepted intent and experiment contract", "low", S, "build_mission_contract"),
        ], [("$operation", "contract", "call", "build")]),
        "orchestrator.plan": detail([
            ("route", "Graph route and parallel-check plan", "low", S, "build_orchestration_plan"),
        ], [("$operation", "route", "call", "compile plan")]),
        "orchestrator.decide": detail([
            ("reference", "Scoped Wiki / reference context", "knowledge", K, "build_reference_context"),
            ("schema", "Tool schema and cited evidence", "guardian", D, "validate_choice"),
            ("target", "Admitted owner and setup revision", "guardian", D, "_validate_target"),
            ("inspect", "inspect_context / inspect_availability", "low", D, "decide_orchestration"),
            ("dispatch", "Bound terminal handler dispatch", "low", D, "decide_orchestration"),
            ("effect", "Returned effect and scope checks", "guardian", D, "decide_orchestration"),
        ], [
            ("reference", "$operation", "evidence", "reference only"),
            ("$operation", "schema", "validation", "LLM choice"),
            ("schema", "target", "validation", "authorize request"),
            ("target", "inspect", "call", "inspect"),
            ("inspect", "$operation", "evidence", "new evidence / next decision"),
            ("target", "dispatch", "call", "handoff / proposal / review / defer"),
            ("dispatch", "effect", "validation", "returned effect"),
        ]),
        "orchestrator.report": detail([
            ("control", "Control-plane snapshot", "middle", S, "build_orchestrator_control_plane_snapshot"),
            ("followup", "Follow-up and owner concerns", "middle", S, "build_orchestrator_followup"),
            ("record", "Decision register and evidence IDs", "knowledge", S, "build_decision_record"),
        ], [
            ("$operation", "control", "call", "snapshot"),
            ("$operation", "followup", "call", "follow-up"),
            ("$operation", "record", "evidence", "record decision"),
        ]),
    }}
