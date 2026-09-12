"""Model-only handoff summaries; full authority and evidence stay with the caller."""
from copy import deepcopy
import hashlib
import json
import math


MAX_PROMPT_BYTES = 16000
CURRENT_FIELDS = {
    "schema", "status", "success", "ok", "ready", "completed", "admitted", "mandatory",
    "owner", "agent", "source", "phase", "stage", "next_stage", "target", "candidate", "capability",
    "decision", "action", "reason", "reason_code", "condition", "conditions", "failure_code",
    "blocking_reason", "blocking_reasons", "warnings", "errors", "issues", "risk_score", "risk_vector",
    "required", "locked", "enabled", "fresh", "detected", "actuation_performed", "simulated", "virtualized",
    "observed_at", "expires_at", "timestamp", "evidence_refs", "provenance", "fidelity", "observation_kind",
    "handoff_status", "completion_status", "ready_for_analysis", "ok_for_bo", "ok_for_next_stage",
    "scope_valid", "owner_admits_now", "review_received", "instruction", "required_admission",
    "admission", "validation", "safety_gate", "handoff_gate", "preflight", "readiness",
    "guardian_decision", "hardware_alerts", "alarms", "corrective_actions", "severity", "message",
    "source_path", "recommended_action", "modified_payload_patch",
}
CURRENT_RESULTS = {
    "guardian", "guardian_gate", "guardian_contract", "hardware_alerts", "corrective_actions",
    "equipment_result", "equipment_handoff", "equipment_preflight", "equipment_report", "workflow_agentic_task",
    "printer_preflight", "specimen_result", "specimen_fabricated", "fabrication_report",
    "design_candidate", "design_decision", "design_report", "handoff_packet",
    "analysis", "bo_handoff", "bo_observation", "experiment_evaluation", "knowledge", "evolution_proposal",
}
# Exact current objects emitted by policies.guardian_gate. Audit containers are
# handled separately, never recursively promoted into current conditions.
GUARDIAN_FIELDS = {
    "guardian_gate_result.v1": set("schema gate_id run_id experiment_id loop_id stage phase agent tool action status decision reason_code risk_score risk_vector guardian_contract guardian_decision modified_payload_patch alarms corrective_actions ok_for_next_stage ok_for_bo created_at".split()),
    "guardian_decision.v1": set("schema decision_id decision reason_code stage phase agent tool action risk_score risk_vector dominant_risks requires_human_approval recommended_action required_evidence missing_evidence fallback_action taxonomy_action modified_payload_patch".split()),
    "guardian_contract.v1": set("schema_version run_id loop_id stage phase agent tool action status confidence artifact_refs provenance_refs requires_human_approval ok_for_next_stage ok_for_bo failure_code risk_flags".split()),
}
GUARDIAN_AUDIT_FIELDS = {"incident_records", "history", "historical_logs", "audit_log"}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def reference(value):
    raw = encoded(value)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "utf8_bytes": len(raw), "retained_server_side": True}


def guardian_contract(value, *, expected_schema=None):
    """Keep a current Guardian contract intact, not a recursive field summary.

    The v1 gate's incident records are audit duplicates; current alarms, action
    receipts, decisions and nested contract mappings remain exact. Unknown
    schemas or malformed conditions cannot be described as complete.
    """
    error = "Unsupported current Guardian contract"
    if not isinstance(value, dict):
        raise ValueError(error)
    schema = value.get("schema", value.get("schema_version"))
    if not isinstance(schema, str) or schema not in GUARDIAN_FIELDS or (expected_schema and schema != expected_schema):
        raise ValueError(error + " schema")
    fields = GUARDIAN_FIELDS[schema]
    if fields - value.keys() or value.keys() - fields - GUARDIAN_AUDIT_FIELDS:
        raise ValueError(error + " fields")
    for key in fields & set("schema schema_version gate_id decision_id run_id experiment_id stage phase agent tool action status decision reason_code recommended_action fallback_action taxonomy_action failure_code created_at".split()):
        if not isinstance(value[key], str):
            raise ValueError(error + ": " + key)
    for key in fields & {"risk_score", "confidence"}:
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]):
            raise ValueError(error + ": " + key)
    if "loop_id" in value and type(value["loop_id"]) is not int:
        raise ValueError(error + ": loop_id")
    for key in ("required_evidence", "missing_evidence", "dominant_risks", "risk_flags"):
        if key in value and (not isinstance(value[key], list) or not all(isinstance(item, str) for item in value[key])):
            raise ValueError(error + ": " + key)
    # Original _extract_refs returns list[Any], including typed artifact maps.
    for key in ("artifact_refs", "provenance_refs"):
        if key in value and not isinstance(value[key], list):
            raise ValueError(error + ": " + key)
    for key in ("fallback_action", "taxonomy_action", "recommended_action"):
        if key in value and not isinstance(value[key], str):
            raise ValueError(error + ": " + key)
    if "risk_vector" in value and (not isinstance(value["risk_vector"], dict) or not all(
            isinstance(key, str) and type(item) in (int, float) and math.isfinite(item)
            for key, item in value["risk_vector"].items())):
        raise ValueError(error + ": risk_vector")
    for key in ("ok_for_bo", "ok_for_next_stage", "requires_human_approval"):
        if key in value and type(value[key]) is not bool:
            raise ValueError(error + ": " + key)
    if "modified_payload_patch" in value and not isinstance(value["modified_payload_patch"], dict):
        raise ValueError(error + ": modified_payload_patch")
    for key in ("alarms", "corrective_actions"):
        if key in value and (not isinstance(value[key], list) or not all(isinstance(item, dict) for item in value[key])):
            raise ValueError(error + ": " + key)
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(error + ": non-JSON condition") from exc
    result = {key: deepcopy(value[key]) for key in fields}
    for key in ("guardian_contract", "guardian_decision"):
        if key in value:
            result[key] = guardian_contract(value[key], expected_schema=key + ".v1")
    audits = {key: reference(value[key]) for key in GUARDIAN_AUDIT_FIELDS if key in value}
    if audits:
        result["audit_refs"] = audits
    return result


def admission_contract(value):
    if not isinstance(value, dict):
        raise ValueError("Unsupported current admission contract shape")
    if "owner_admits_now" in value and type(value["owner_admits_now"]) is not bool:
        raise ValueError("Unsupported current admission contract status")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Unsupported current admission contract condition") from exc
    return deepcopy(value)


def current_summary(value):
    """Select current contract facts, not historical logs, model traces or mesh data.

    No selected value is clipped. If current conditions are too large, the
    complete prompt is rejected below and no model/handler can grant admission.
    """
    if isinstance(value, dict):
        if str(value.get("schema", value.get("schema_version", ""))).startswith("guardian_"):
            return guardian_contract(value)
        return {key: admission_contract(item) if key == "required_admission" else deepcopy(item) if key in {"condition", "conditions"} else current_summary(item)
            for key, item in value.items()
            if key in CURRENT_FIELDS or isinstance(item, bool) or key.endswith(("_id", "_required", "_ready", "_verified", "_released"))
            or key.startswith("requires_")}
    if isinstance(value, list):
        return [current_summary(item) for item in value]
    return deepcopy(value)


def evidence_summary(value):
    if not isinstance(value, dict):
        return {"full_evidence": reference(value), "current": current_summary(value)}
    result = current_summary(value)
    if "result_data" not in value:
        for key in ("goal", "constraints"):
            if key in value:
                result[key] = deepcopy(value[key])
    for key in ("guardian_context", "selected_transition", "transition_candidates", "required_admission"):
        if key in value:
            if key == "guardian_context" and value[key] is not None:
                result[key] = guardian_contract(value[key])
            elif key == "required_admission":
                result[key] = admission_contract(value[key])
            else:
                result[key] = current_summary(value[key])
    if isinstance(value.get("result_data"), dict):
        raw = value["result_data"]
        result["result_data"] = {**current_summary(raw), **{
            key: guardian_contract(raw[key]) if key in {"guardian_gate", "guardian_contract"} and raw[key] is not None
            else current_summary(raw[key]) for key in CURRENT_RESULTS if key in raw}}
        gate = value.get("guardian_context")
        if isinstance(gate, dict):
            if raw.get("guardian_gate") == gate:
                result["result_data"]["guardian_gate"] = {"same_contract_ref": "guardian_context"}
            if "corrective_actions" in raw and raw["corrective_actions"] == gate.get("corrective_actions"):
                result["result_data"]["corrective_actions"] = {"same_contract_ref": "guardian_context.corrective_actions"}
    result["full_evidence"] = reference(value)
    return result


def project_handoff_prompt(packet):
    """Project presentation only; hashes never replace server equality checks."""
    public = deepcopy({key: value for key, value in packet.items() if key not in {"scope", "evidence", "trace"}})
    scope = packet["scope"]
    context = scope.get("context", {})
    authorization = context.get("authorization", {})
    specimen = authorization.get("specimen", {})
    setup = authorization.get("setup") or {}
    public["scope"] = {"run_id": scope.get("run_id"), "loop": scope.get("loop"), "stage": scope.get("stage"),
        "full_scope": reference(scope), "context": {key: deepcopy(context[key]) for key in (
            "checkpoint", "revision", "setup_revision", "stop") if key in context},
        "authorization": {key: deepcopy(authorization[key]) for key in ("run_id", "loop", "mode", "goal", "policy", "stop")
            if key in authorization}, "specimen": {key: deepcopy(specimen[key]) for key in (
                "specimen_id", "candidate_id", "execution_policy") if key in specimen},
        "setup": {"revision": setup.get("revision"), "snapshot": reference(setup)}}
    # Availability is evidence, never inferred from registration or idle state.
    public["scope"]["owner_reports"] = {owner: {capability: current_summary(report)
        for capability, report in reports.items()} if isinstance(reports, dict) else {
            "status": "unknown", "malformed_report": reference(reports)}
        for owner, reports in (authorization.get("owners") or {}).items()}
    public["evidence"] = {key: evidence_summary(value) for key, value in packet.get("evidence", {}).items()}
    public["trace"] = []
    for row in packet.get("trace", []):
        item = {key: deepcopy(row[key]) for key in ("choice", "error") if key in row}
        result = row.get("result", {})
        item["result"] = current_summary(result)
        if "report" in result:
            item["result"]["report"] = current_summary(result["report"])
        if "evidence" in result:
            item["result"]["evidence"] = {key: {"same_evidence_ref": key, "full_evidence": reference(value)}
                for key, value in result["evidence"].items()}
        public["trace"].append(item)
    public["presentation"] = {"schema": "handoff_prompt_projection.v1", "complete_current_contract_summary": True,
        "raw_records": "Retained server-side; hashes are references, not approvals. Owner admission remains authoritative."}
    _fit_optional_reference_only(public)
    if len(json.dumps(public, ensure_ascii=False).encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError("Handoff current-contract prompt exceeds presentation budget; owner review required")
    return public


def _fit_optional_reference_only(public):
    """Use only spare handoff-prompt capacity for non-authoritative Wiki text.

    The model's owner contract is assembled before this runs and remains the
    hard presentation boundary.  A reference pack that cannot fit is made
    explicit rather than silently omitted; callers use that marker to avoid a
    false delivery receipt.
    """
    context = public.get("context")
    if not isinstance(context, dict):
        return
    reference_only = context.pop("reference_only", None)
    if not isinstance(reference_only, dict):
        return
    items = reference_only.get("items")
    if not isinstance(items, list):
        items = []

    def fits(candidate):
        context["reference_only"] = candidate
        within_budget = len(json.dumps(public, ensure_ascii=False).encode("utf-8")) <= MAX_PROMPT_BYTES
        context.pop("reference_only", None)
        return within_budget

    # Preserve ordinary no-match/unavailable envelopes when they fit: they do
    # not contain optional source text and have no delivery to suppress.
    if not items and fits(reference_only):
        context["reference_only"] = reference_only
        return

    excluded = {key: deepcopy(value) for key, value in reference_only.items()
                if key not in {"items", "next_cursor"}}
    excluded["items"] = []
    excluded["next_cursor"] = ""
    excluded["presentation"] = {"status": "excluded", "reason": "presentation_budget_exhausted"}
    if not fits(excluded):
        # The current owner contract itself is too large.  Leave no optional
        # context so the unchanged hard gate below can fail closed.
        return

    included = {key: deepcopy(value) for key, value in reference_only.items() if key != "items"}
    selected = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate = {**included, "items": [*selected, deepcopy(item)],
                     "presentation": {"status": "included"}}
        if fits(candidate):
            selected.append(deepcopy(item))
    if selected:
        context["reference_only"] = {**included, "items": selected,
                                      "presentation": {"status": "included"}}
    else:
        context["reference_only"] = excluded
