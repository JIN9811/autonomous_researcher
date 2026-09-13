"""Source-bound Vision CODE relationships inside genuine composite operations."""
from agents.control_structure import implementation_detail as detail

A = "agents/vision/agent.py"
D = "agents/vision/decision.py"


def vision_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "vision.prepare": detail([
            ("admission", "Clearance, stop and preflight admission", "guardian", A, "VisionAgent._prepare_observation"),
            ("preflight", "Immutable printer artifact transfer inputs", "middle", A, "VisionAgent._no_actuation_transfer_preflight"),
        ], [("$operation", "admission", "validation", "original admission order"),
            ("admission", "preflight", "call", "preflight route")]),
        "vision.observe": detail([
            ("task", "Resolve observation task", "middle", A, "VisionAgent._resolve_task"),
            ("choice", "LLM observation tool choice", "high", D, "select_vision_tool"),
            ("capture", "Existing capture and placement interlock composite", "middle", A, "VisionAgent._observe_and_review"),
            ("camera", "Camera acquisition / selected provider", "low", "device_bridges/camera_vision/realsense_bridge.py", "RealSenseBridge.capture_one_frame"),
            ("robot", "LeRobot ActiveCam and rollout boundary", "low", "device_bridges/lerobot/bridge.py", "LeRobotBridge"),
            ("interlock", "Refresh rollout evidence and interlock", "guardian", A, "VisionAgent._refresh_rollout_status_for_utm_completion"),
            ("stop", "Stop verified rollout before placement model review", "middle", A, "VisionAgent._stop_verified_rollout"),
            ("review", "LLM same-frame visual review", "high", D, "review_visual_evidence"),
            ("evidence", "Persist observation evidence", "knowledge", A, "VisionAgent._write_evidence_artifacts"),
            ("signals", "Freshness-bounded downstream signals", "guardian", A, "VisionAgent._agent_signals"),
        ], [("$operation", "task", "call", "task contract"),
            ("$operation", "choice", "call", "bounded choice when applicable"),
            ("$operation", "interlock", "validation", "placement admission"),
            ("$operation", "capture", "call", "composite observation"),
            ("capture", "camera", "call", "camera route when selected"),
            ("capture", "robot", "call", "ActiveCam route when selected"),
            ("stop", "robot", "call", "existing stop boundary"),
            ("capture", "stop", "call", "verified placement stop"),
            ("stop", "review", "evidence", "stop precedes placement review"),
            ("capture", "review", "evidence", "same frame"),
            ("capture", "evidence", "call", "persist evidence"),
            ("$operation", "signals", "validation", "downstream readiness")]),
        "vision.clearance": detail([
            ("clear", "Existing UTM clearance owner route", "middle", "utils/utm_clear_cycle.py", "run_clear_vision"),
            ("scope", "Current clearance scope and terminal guards", "guardian", "utils/utm_clear_cycle.py", "current_clear"),
            ("stop", "Stop pending replay on deadline or stop request", "middle", "utils/utm_clear_cycle.py", "stop_pending_clear"),
            ("review", "LLM clearance image review", "high", D, "review_visual_evidence"),
        ], [("$operation", "clear", "call", "composite clearance"),
            ("clear", "scope", "validation", "same invocation scope"),
            ("clear", "stop", "call", "existing early-stop route"),
            ("clear", "review", "evidence", "captured clearance frame")]),
        "vision.deliver": detail([
            ("report", "Observation report and intervention evidence", "knowledge", A, "VisionAgent._vision_agent_report_snapshot"),
        ], [("report", "$operation", "evidence", "completed owner result")]),
        "vision.deliver_prepared": detail([
            ("preflight", "Prepared preflight or stop result", "middle", A, "VisionAgent._prepare_observation"),
        ], [("preflight", "$operation", "evidence", "prepared owner result")]),
        "vision.deliver_clearance": detail([
            ("clearance", "Completed clearance result", "middle", A, "VisionAgent._verify_clearance"),
        ], [("clearance", "$operation", "evidence", "clearance owner result")]),
    }}
