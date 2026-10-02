"""Source-bound Equipment CODE relationships; these are not execution stages."""
from agents.control_structure import implementation_detail as detail


A = "agents/equipment/agent.py"
D = "agents/equipment/decision.py"
W = "agents/equipment/workflow.py"
B = "device_bridges/windows_pyautogui/bridge.py"
T = "device_bridges/windows_pyautogui/tools.py"
R = "utils/equipment_runtime_service.py"
G = "policies/guardian_gate.py"
E = "utils/equipment_agentic_task.py"
C = "utils/utm_csv.py"


def equipment_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "equipment.task": detail([
            ("task", "Existing Equipment task admission and dispatch", "middle", A, "LabEquipmentAgent._run_task"),
            ("entry", "Mandatory specimen and UTM handoff admission", "guardian", E, "evaluate_equipment_entry_gate"),
            ("suitability", "LLM stacked-workflow suitability decision", "high", D, "decide_equipment"),
            ("flow", "Existing stacked Equipment Skill Flow supervisor", "middle", W, "run_decided_workflow"),
            ("runtime", "Canonical equipment execution lifecycle service", "middle", R, "EquipmentRuntimeService"),
            ("dispatch", "Selected registered worker tool call", "middle", A, "LabEquipmentAgent._call_tool"),
            ("registration", "Existing tool and queue registration", "middle", T, "register_equipment_tools"),
            ("worker", "Windows or local PyAutoGUI execution boundary", "low", B, "WindowsPyAutoGUIBridge"),
            ("recovery", "No-action bounded recovery eligibility", "guardian", W, "_safe_resume"),
            ("guardian", "Existing recovery safety gate", "guardian", G, "equipment_skill_recovery_gate"),
            ("terminal", "LLM terminal evidence and recovery review", "high", D, "decide_equipment"),
            ("csv", "UTM CSV integrity evidence", "knowledge", C, "probe_utm_csv"),
            ("handoff", "Cycle CSV and Analysis handoff evidence", "knowledge", E, "bind_cycle_csv_artifact"),
        ], [
            ("$operation", "task", "call", "unchanged composite owner task"),
            ("task", "entry", "validation", "mandatory existing handoff gate"),
            ("task", "suitability", "call", "configured flow proposal only"),
            ("suitability", "flow", "validation", "owner accepts the configured flow"),
            ("flow", "runtime", "call", "existing lifecycle record"),
            ("flow", "dispatch", "call", "selected registered worker"),
            ("dispatch", "registration", "call", "existing tool ID and queue"),
            ("registration", "worker", "call", "current bridge execution boundary"),
            ("flow", "recovery", "validation", "failed block remains proven unexecuted"),
            ("recovery", "guardian", "validation", "existing bounded recovery gate"),
            ("flow", "terminal", "evidence", "terminal or failure evidence review"),
            ("flow", "csv", "evidence", "raw CSV parse and identity evidence"),
            ("csv", "handoff", "evidence", "existing Analysis handoff gate"),
        ]),
        "equipment.deliver": detail([
            ("report", "Equipment report and result payload", "knowledge", A, "LabEquipmentAgent._build_equipment_package"),
            ("projection", "Owner report projection", "knowledge", "agents/equipment/presentation.py", "project_equipment_report"),
            ("archive", "Public run archive wrapper", "knowledge", "utils/agent_artifact_archive.py", "archive_agent_run"),
        ], [
            ("report", "$operation", "evidence", "original owner AgentResult"),
            ("report", "projection", "evidence", "metadata and payload precedence"),
            ("$operation", "archive", "evidence", "public run archives once"),
        ]),
    }}
