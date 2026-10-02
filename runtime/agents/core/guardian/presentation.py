"""Read-only Guardian report projection for the shared Live host."""

from __future__ import annotations

from copy import deepcopy


# Read-only report input contract; unlisted state is never copied for this view.
REPORT_METADATA_KEYS = ["latest_guardian_decision","latest_guardian_report","guardian_status"]
REPORT_STATE_FIELDS = []

REPORT_PROFILE = {
    "title": "Safety Gate / Continue-Stop Decision",
    "summary": "Checks live/test gate results, hardware risk, and operator approvals before continuation.",
    "focus_rows": [
        {"label": "Gate", "value": "safe/hold/retry/replan/stop decision with reason"},
        {"label": "Risk", "value": "device errors, missing approvals, unsafe bridge state, failed validation"},
        {"label": "Action", "value": "continue workflow, request operator input, or trigger safe stop"},
    ],
    "checklist": ["Require approval when needed", "Surface blocking errors", "Record final decision"],
}


def project_guardian_report(metadata: dict, agent_payload: dict) -> dict:
    """Expose existing Guardian observations; policy decisions remain owner-owned."""
    decision = metadata.get("latest_guardian_decision") if isinstance(metadata.get("latest_guardian_decision"), dict) else {}
    report = metadata.get("latest_guardian_report") if isinstance(metadata.get("latest_guardian_report"), dict) else {}
    status = metadata.get("guardian_status") if isinstance(metadata.get("guardian_status"), dict) else {}
    if not decision and isinstance(agent_payload.get("guardian"), dict):
        decision = agent_payload["guardian"]
    role_specific = deepcopy(REPORT_PROFILE)
    role_specific.update({"latest_decision": deepcopy(decision), "latest_report": deepcopy(report)})
    metrics = {key: deepcopy(report[key]) for key in ("risk_score", "confidence") if key in report}
    return {
        "role_specific": role_specific,
        "decisions": [deepcopy(decision)] if decision else [],
        "metrics": metrics,
        "guardian_decision": deepcopy(decision),
        "guardian_report": deepcopy(report),
        "guardian_status": deepcopy(status),
    }
