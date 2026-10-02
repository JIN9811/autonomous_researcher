"""Vision-owned report projection with transient observation context."""

# Read-only report input contract; unlisted state is never copied for this view.
REPORT_METADATA_KEYS = ["latest_vision_observation","latest_vision_agent_report","vision_report","vision_signal","vision_metrics"]
REPORT_STATE_FIELDS = ["latest_observations"]

REPORT_PROFILE = {
        "title": "Lab Perception Signal Bus / Visual Evidence",
        "summary": "Converts camera or screenshot evidence into zone states, freshness-bounded agent signals, visual evidence, and downstream handoff gates.",
        "focus_rows": [
            {"label": "Scene task", "value": "post-ejection, pickup, UTM fixture, or reset observation task with current specimen context"},
            {"label": "Signal board", "value": "pickup_ready, visual_evidence_ready, anomaly_detected, and future equipment cross-check signals with confidence/freshness"},
            {"label": "D455F snapshot", "value": "one-shot RGB-D pose after auto-ejection, then camera returned to VLA route"},
            {"label": "VLA gate", "value": "Manipulation starts only when specimen_pose_ready and camera_returned_to_vla are true"},
            {"label": "Evidence", "value": "frame/annotated scene, detection JSON, zone states, and Knowledge memory payload"},
            {"label": "Safety", "value": "Vision observes only; robot/printer/equipment actions remain gated by downstream agents and Guardian"},
        ],
        "checklist": ["Check camera heartbeat", "Review zone state", "Verify signal freshness", "Inspect visual evidence", "Gate manipulation handoff"],
    }


def project_vision_report(metadata: dict, agent_payload: dict) -> dict:
    role_specific = {}
    report_decisions = []
    report_metrics = {}
    vision_report = None
    vision_agent_report = None
    latest_observation = metadata.get("_projection_state", {}).get("latest_observations") if isinstance(metadata.get("_projection_state", {}).get("latest_observations"), dict) else {}
    if not latest_observation and isinstance(metadata.get("latest_vision_observation"), dict):
        latest_observation = metadata["latest_vision_observation"]
    if isinstance(metadata.get("latest_vision_agent_report"), dict):
        vision_agent_report = metadata["latest_vision_agent_report"]
    elif isinstance(latest_observation.get("vision_agent_report"), dict):
        vision_agent_report = latest_observation["vision_agent_report"]
    elif isinstance(agent_payload.get("vision_agent_report"), dict):
        vision_agent_report = agent_payload["vision_agent_report"]
    if isinstance(metadata.get("vision_report"), dict):
        vision_report = metadata["vision_report"]
    elif isinstance(latest_observation.get("vision_report"), dict):
        vision_report = latest_observation["vision_report"]
    elif isinstance(agent_payload.get("vision_report"), dict):
        vision_report = agent_payload["vision_report"]
    vision_packet = metadata.get("vision_signal") if isinstance(metadata.get("vision_signal"), dict) else {}
    if not vision_packet and isinstance(latest_observation.get("vision_signal"), dict):
        vision_packet = latest_observation["vision_signal"]
    if not vision_packet and isinstance(agent_payload.get("vision_signal"), dict):
        vision_packet = agent_payload["vision_signal"]
    if isinstance(vision_report, dict):
        role_specific["summary"] = "Lab perception signal board with zone states, freshness-bounded signals, visual evidence artifacts, and Knowledge/Guardian handoff context."
        role_specific["scene_map"] = vision_report.get("scene_map", vision_report.get("zones", {}))
        role_specific["signal_board"] = vision_report.get("signal_board", vision_report.get("agent_signals", []))
        role_specific["evidence_timeline"] = vision_report.get("events", [])
        role_specific["dataset_ledger"] = vision_report.get("dataset_ledger", {})
        role_specific["model_backend"] = vision_report.get("model_backend", {})
        role_specific["camera_source"] = vision_report.get("camera_source", {})
        role_specific["safety_anomaly"] = vision_report.get("safety_anomaly", {})
        role_specific["knowledge_payload"] = vision_report.get("knowledge_payload", {})
        role_specific["handoff_packet"] = vision_packet
        if isinstance(vision_agent_report, dict):
            role_specific["vision_agent_report"] = vision_agent_report
        report_decisions = vision_packet.get("decisions", []) if isinstance(vision_packet.get("decisions"), list) else agent_payload.get("decisions", []) if isinstance(agent_payload.get("decisions"), list) else []
        report_metrics = metadata.get("vision_metrics") if isinstance(metadata.get("vision_metrics"), dict) else agent_payload.get("metrics", {}) if isinstance(agent_payload.get("metrics"), dict) else {}

    return {"role_specific": role_specific, "decisions": report_decisions, "metrics": report_metrics,
            "vision_report": vision_report, "vision_agent_report": vision_agent_report}
