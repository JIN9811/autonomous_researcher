"""Design-owned projection consumed by the existing live report API."""
from __future__ import annotations

# Read-only report input contract; unlisted state is never copied for this view.
REPORT_METADATA_KEYS = ["latest_design_agent_report","design_report"]
REPORT_STATE_FIELDS = []

REPORT_PROFILE = {
    "title": "Design Geometry / Manufacturability",
    "summary": "Converts approved requirements into printable TPMS/FDM specimen geometry with traceable parameters.",
    "focus_rows": [
        {"label": "Geometry", "value": "gyroid TPMS with cell size, unit-cell count, shell thickness, and cap settings"},
        {"label": "Manufacturability", "value": "single connected body, FDM constraints, slicer-safe dimensions"},
        {"label": "Artifacts", "value": "STL preview, parameter JSON, and design candidate metadata"},
    ],
    "checklist": ["Check connected components", "Record final parameters", "Expose STL artifact"],
}


def project_design_report(metadata: dict, agent_payload: dict) -> dict:
    """Preserve the established metadata/payload precedence and report shape."""
    result = {"role_specific": {}, "decisions": [], "metrics": {},
              "design_report": None, "design_agent_report": None}
    if isinstance(metadata.get("latest_design_agent_report"), dict):
        result["design_agent_report"] = metadata["latest_design_agent_report"]
    elif isinstance(agent_payload.get("design_agent_report"), dict):
        result["design_agent_report"] = agent_payload["design_agent_report"]
    if isinstance(metadata.get("design_report"), dict):
        result["design_report"] = metadata["design_report"]
    elif isinstance(agent_payload.get("design_report"), dict):
        result["design_report"] = agent_payload["design_report"]
    report = result["design_report"]
    if isinstance(report, dict):
        generation = report.get("candidate_generation") if isinstance(report.get("candidate_generation"), dict) else {}
        evaluation = report.get("candidate_evaluation") if isinstance(report.get("candidate_evaluation"), dict) else {}
        manufacturability = report.get("manufacturability") if isinstance(report.get("manufacturability"), dict) else {}
        handoff = report.get("handoff_to_specimen") if isinstance(report.get("handoff_to_specimen"), dict) else {}
        result["role_specific"] = {
            "summary": "Traceable objective, hypothesis, candidate pool, selection rationale, rejected/repair log, and Specimen Agent handoff evidence.",
            "candidate_board": {
                "candidate_count": generation.get("candidate_count"),
                "valid_count": generation.get("valid_count"),
                "rejected_count": generation.get("rejected_count"),
                "top_candidates": generation.get("top_candidates", []),
                "candidate_ledger": generation.get("candidate_ledger", []),
            },
            "manufacturability": manufacturability,
            "decision_register": report.get("decision_register", []),
            "handoff_packet": handoff,
            "objective": report.get("objective", {}),
            "hypothesis": report.get("hypothesis", {}),
            "prior_context": report.get("prior_context", {}),
        }
        if isinstance(result["design_agent_report"], dict):
            result["role_specific"]["design_agent_report"] = result["design_agent_report"]
        result["decisions"] = report.get("decision_register", []) if isinstance(report.get("decision_register"), list) else []
        result["metrics"] = evaluation
    return result
