"""Specimen-owned projection preserving the existing live report precedence."""

REPORT_PROFILE = {
    "title": "Manufacturing Digital Thread / Printer Runtime",
    "summary": "Transforms the selected STL into a fabrication digital thread with slicer settings, quality gates, printer runtime evidence, monitoring handoff, and feedback to the next loop.",
    "focus_rows": [
        {"label": "Digital thread", "value": "design candidate -> STL -> G-code -> printer job -> Vision/Manipulation handoff"},
        {"label": "Process plan", "value": "material, profile, layer/nozzle/temp, adhesion, cap skin, and ejection policy"},
        {"label": "Quality gates", "value": "required fields, mesh, manufacturability, slicer, G-code, storage, live execution, and ejection"},
        {"label": "Runtime evidence", "value": "PrusaLink upload/start/transfer trace, operator messages, outcome, and feedback to Design/Knowledge/BO"},
    ],
    "checklist": ["Confirm fabrication intent", "Inspect digital thread", "Review quality gates", "Log printer runtime", "Prepare Vision handoff"],
}


def project_specimen_report(metadata: dict, agent_payload: dict) -> dict:
    role_specific = {}
    report_decisions = []
    report_metrics = {}
    specimen_fabrication_report = None
    specimen_agent_report = None
    specimen_result = metadata.get("specimen_result") if isinstance(metadata.get("specimen_result"), dict) else {}
    if not specimen_result and isinstance(agent_payload.get("specimen_result"), dict):
        specimen_result = agent_payload["specimen_result"]
    if isinstance(metadata.get("latest_specimen_agent_report"), dict):
        specimen_agent_report = metadata["latest_specimen_agent_report"]
    elif isinstance(agent_payload.get("specimen_agent_report"), dict):
        specimen_agent_report = agent_payload["specimen_agent_report"]
    elif isinstance(specimen_result.get("specimen_agent_report"), dict):
        specimen_agent_report = specimen_result["specimen_agent_report"]
    if isinstance(metadata.get("fabrication_report"), dict):
        specimen_fabrication_report = metadata["fabrication_report"]
    elif isinstance(specimen_result.get("fabrication_report"), dict):
        specimen_fabrication_report = specimen_result["fabrication_report"]
    elif isinstance(agent_payload.get("fabrication_report"), dict):
        specimen_fabrication_report = agent_payload["fabrication_report"]
    specimen_packet = metadata.get("specimen_fabricated") if isinstance(metadata.get("specimen_fabricated"), dict) else {}
    if not specimen_packet and isinstance(agent_payload.get("specimen_fabricated"), dict):
        specimen_packet = agent_payload["specimen_fabricated"]
    if isinstance(specimen_fabrication_report, dict):
        role_specific["summary"] = "Manufacturing digital thread, process plan, quality gates, printer runtime evidence, monitoring handoff, and feedback to Design/Knowledge/BO."
        role_specific["fabrication_intent"] = specimen_fabrication_report.get("fabrication_intent", {})
        role_specific["digital_thread"] = specimen_fabrication_report.get("digital_thread", {})
        role_specific["process_plan"] = specimen_fabrication_report.get("process_plan", {})
        role_specific["quality_gates"] = specimen_fabrication_report.get("quality_gates", [])
        role_specific["monitoring_plan"] = specimen_fabrication_report.get("monitoring_plan", {})
        role_specific["printer_runtime"] = specimen_fabrication_report.get("printer_runtime", {})
        role_specific["fabrication_outcome"] = specimen_fabrication_report.get("fabrication_outcome", {})
        role_specific["feedback_to_design"] = specimen_fabrication_report.get("feedback_to_design", {})
        role_specific["handoff_packet"] = specimen_packet
        if isinstance(specimen_agent_report, dict):
            role_specific["specimen_agent_report"] = specimen_agent_report
        report_decisions = specimen_packet.get("decisions", []) if isinstance(specimen_packet.get("decisions"), list) else agent_payload.get("decisions", []) if isinstance(agent_payload.get("decisions"), list) else []
        report_metrics = metadata.get("specimen_metrics") if isinstance(metadata.get("specimen_metrics"), dict) else agent_payload.get("metrics", {}) if isinstance(agent_payload.get("metrics"), dict) else {}

    return {"role_specific": role_specific, "decisions": report_decisions, "metrics": report_metrics,
            "fabrication_report": specimen_fabrication_report, "specimen_agent_report": specimen_agent_report}
