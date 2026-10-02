"""Failure/success pattern mining for Knowledge Agent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from knowledge.provenance import build_provenance_ref, safe_slug, stable_id
from knowledge.schemas import AgentPerformanceRecord, FailurePatternRecord, SuccessPatternRecord

AGENT_STAGES = ["design", "specimen", "vision", "manipulation", "equipment", "analysis", "knowledge", "bo", "guardian"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_agent_performance_records(
    *,
    run_id: str,
    metadata: dict[str, Any],
    retry_counters: dict[str, Any],
    current_stage: str,
    analysis_payload: dict[str, Any],
    knowledge_artifacts: list[dict[str, Any]],
) -> list[AgentPerformanceRecord]:
    """Build one performance ledger entry per observed stage."""
    now = utc_now()
    records: list[AgentPerformanceRecord] = []
    for stage in AGENT_STAGES:
        payload = _stage_payload(stage, metadata, analysis_payload)
        observed = bool(payload) or stage == current_stage
        if not observed:
            continue
        warnings = _collect_warnings(payload)
        failure_code = _find_failure_code(payload)
        missing_fields = _find_missing_fields(stage, payload)
        artifact_count = _artifact_count(payload)
        retry_count = int(retry_counters.get(stage, 0) or 0) if isinstance(retry_counters, dict) else 0
        status = "failed" if failure_code else "warning" if warnings or missing_fields else "success"
        contract_validity = 0.0 if failure_code else max(0.0, 1.0 - 0.15 * len(missing_fields))
        artifact_completeness = min(1.0, artifact_count / 3.0) if artifact_count else (0.5 if stage in {"knowledge", current_stage} else 0.0)
        warning_penalty = min(0.4, 0.08 * len(warnings))
        retry_penalty = min(0.2, 0.05 * retry_count)
        score = max(0.0, round((0.55 * contract_validity) + (0.35 * artifact_completeness) + 0.10 - warning_penalty - retry_penalty, 4))
        needs_evolution = bool(failure_code or missing_fields or len(warnings) >= 2 or retry_count > 0)
        reason_parts = []
        if failure_code:
            reason_parts.append(f"failure_code={failure_code}")
        if missing_fields:
            reason_parts.append(f"missing_fields={','.join(missing_fields[:5])}")
        if warnings:
            reason_parts.append(f"warnings={len(warnings)}")
        if retry_count:
            reason_parts.append(f"retry_count={retry_count}")
        provenance = build_provenance_ref(
            run_id=run_id,
            used=[f"run_metadata.{stage}", "knowledge_report.json"],
            associated_with=[f"{stage}_agent", "knowledge_agent"],
            derived_from=[run_id],
            artifact_refs=knowledge_artifacts,
        )
        records.append(
            AgentPerformanceRecord(
                record_id=stable_id("agent-performance", run_id, stage, status, missing_fields, warnings),
                run_id=run_id,
                agent_id=stage,
                stage=stage,
                status=status,
                score=score,
                signals={
                    "missing_required_fields": missing_fields,
                    "warnings": warnings,
                    "latency_s": _find_latency(payload),
                    "retry_count": retry_count,
                    "artifact_completeness": artifact_completeness,
                    "contract_validity": contract_validity,
                    "failure_code": failure_code,
                    "artifact_count": artifact_count,
                },
                evolution_hint={
                    "needs_evolution": needs_evolution,
                    "target_type": "prompt",
                    "target_id": stage,
                    "reason": "; ".join(reason_parts),
                },
                provenance=provenance,
                created_at=now,
            )
        )
    return records


def update_failure_patterns(
    *,
    run_id: str,
    performance_records: list[AgentPerformanceRecord],
    failure_tags: list[str],
    existing_patterns: list[FailurePatternRecord],
    evidence_refs: list[dict[str, Any]],
) -> list[FailurePatternRecord]:
    """Create current failure pattern records and merge recurrence counts from prior memory."""
    now = utc_now()
    existing = {item.pattern_id: item for item in existing_patterns}
    raw_patterns: list[tuple[str, list[str], str, list[str]]] = []
    for tag in failure_tags:
        raw_patterns.append((str(tag), ["analysis", "knowledge"], f"Analysis quality tag observed: {tag}", [f"Do not pass unresolved {tag} evidence to BO without quality flag."]))
    for record in performance_records:
        signals = record.signals
        failure_code = str(signals.get("failure_code") or "").strip()
        missing = [str(item) for item in signals.get("missing_required_fields", []) if item]
        warnings = [str(item) for item in signals.get("warnings", []) if item]
        if failure_code:
            raw_patterns.append((failure_code, [record.agent_id], f"{record.agent_id} emitted failure code {failure_code}.", [f"Do not mark {record.agent_id} handoff ready while {failure_code} is active."]))
        if missing:
            raw_patterns.append(("missing-required-fields", [record.agent_id], f"{record.agent_id} omitted required fields: {', '.join(missing[:6])}.", [f"{record.agent_id} must emit required contract fields before downstream handoff."]))
        if len(warnings) >= 2:
            raw_patterns.append(("repeated-runtime-warnings", [record.agent_id], f"{record.agent_id} produced {len(warnings)} warnings in one run.", [f"{record.agent_id} must surface warning causes and recovery choices before continuing."]))
    patterns: list[FailurePatternRecord] = []
    for failure_type, agents, hypothesis, do_not_repeat in raw_patterns:
        pattern_id = safe_slug(f"{'-'.join(sorted(set(agents)))}-{failure_type}", fallback="failure-pattern")
        previous = existing.get(pattern_id)
        recurrence = int(previous.recurrence_count) + 1 if previous else 1
        first_seen = previous.first_seen_run_id if previous else run_id
        recommended_target = sorted(set(agents))[0]
        patterns.append(
            FailurePatternRecord(
                pattern_id=pattern_id,
                affected_agents=sorted(set(agents)),
                failure_type=safe_slug(failure_type, fallback="unknown_failure").upper().replace("-", "_"),
                recurrence_count=recurrence,
                first_seen_run_id=first_seen,
                last_seen_run_id=run_id,
                evidence_refs=evidence_refs,
                root_cause_hypothesis=hypothesis,
                do_not_repeat=do_not_repeat,
                recommended_evolution={
                    "target_type": "prompt",
                    "target_id": recommended_target,
                    "objective": f"Reduce recurrence of {failure_type} in {recommended_target} stage.",
                    "constraints": {
                        "preserve_live_blocking": True,
                        "must_emit_failure_code": True,
                        "must_not_generate_synthetic_live_data": True,
                    },
                },
                provenance=build_provenance_ref(
                    run_id=run_id,
                    used=["agent_performance_records.json", "knowledge_report.json"],
                    associated_with=sorted({*agents, "knowledge_agent"}),
                    derived_from=[run_id],
                    artifact_refs=evidence_refs,
                ),
                created_at=previous.created_at if previous else now,
                updated_at=now,
            )
        )
    unique: dict[str, FailurePatternRecord] = {}
    for pattern in patterns:
        if pattern.pattern_id not in unique or pattern.recurrence_count > unique[pattern.pattern_id].recurrence_count:
            unique[pattern.pattern_id] = pattern
    return list(unique.values())


def update_success_patterns(
    *,
    run_id: str,
    performance_records: list[AgentPerformanceRecord],
    existing_patterns: list[SuccessPatternRecord],
    evidence_refs: list[dict[str, Any]],
) -> list[SuccessPatternRecord]:
    """Capture successful agent procedures as reviewable skill cards."""
    now = utc_now()
    existing = {item.skill_id: item for item in existing_patterns}
    results: list[SuccessPatternRecord] = []
    for record in performance_records:
        if record.status != "success" or record.score < 0.65:
            continue
        skill_id = safe_slug(f"{record.agent_id}-successful-handoff-v1", fallback="success-pattern")
        previous = existing.get(skill_id)
        success_runs = int((previous.success_metrics or {}).get("runs_successful", 0)) + 1 if previous else 1
        results.append(
            SuccessPatternRecord(
                skill_id=skill_id,
                agent_id=record.agent_id,
                scope=f"{record.agent_id}_runtime_procedure",
                preconditions=["required input packet available", "Guardian hard block absent"],
                procedure_summary=f"{record.agent_id} completed its observed runtime handoff with score {record.score}.",
                success_metrics={
                    "runs_successful": success_runs,
                    "latest_score": record.score,
                    "failure_rate": 0.0,
                },
                artifact_refs=evidence_refs,
                operator_review_required=True,
                provenance=build_provenance_ref(
                    run_id=run_id,
                    used=["agent_performance_records.json"],
                    associated_with=[record.agent_id, "knowledge_agent"],
                    derived_from=[run_id],
                    artifact_refs=evidence_refs,
                ),
                created_at=previous.created_at if previous else now,
                updated_at=now,
            )
        )
    return results


def rank_evolution_targets(
    performance_records: list[AgentPerformanceRecord],
    failure_patterns: list[FailurePatternRecord],
) -> list[dict[str, Any]]:
    """Rank targets for evidence-pack generation."""
    scores: dict[str, dict[str, Any]] = {}
    for record in performance_records:
        hint = record.evolution_hint or {}
        if not hint.get("needs_evolution"):
            continue
        target = str(hint.get("target_id") or record.agent_id)
        item = scores.setdefault(target, {"target_type": str(hint.get("target_type") or "prompt"), "target_id": target, "priority": 0.0, "reasons": []})
        item["priority"] += max(0.1, 1.0 - record.score)
        if hint.get("reason"):
            item["reasons"].append(str(hint["reason"]))
    for pattern in failure_patterns:
        target = str((pattern.recommended_evolution or {}).get("target_id") or (pattern.affected_agents[0] if pattern.affected_agents else "knowledge"))
        item = scores.setdefault(target, {"target_type": str((pattern.recommended_evolution or {}).get("target_type") or "prompt"), "target_id": target, "priority": 0.0, "reasons": []})
        item["priority"] += min(1.5, 0.35 * max(1, pattern.recurrence_count))
        item["reasons"].append(pattern.root_cause_hypothesis or pattern.failure_type)
    ranked = sorted(scores.values(), key=lambda item: item["priority"], reverse=True)
    for item in ranked:
        item["priority"] = round(min(1.0, float(item["priority"])), 4)
        item["reasons"] = list(dict.fromkeys(item.get("reasons", [])))[:5]
    return ranked


def _stage_payload(stage: str, metadata: dict[str, Any], analysis_payload: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = [metadata.get(f"{stage}_agent_payload"), metadata.get(f"{stage}_report"), metadata.get(f"{stage}_result")]
    if stage == "analysis":
        candidates.extend([metadata.get("analysis_agent_payload"), analysis_payload, metadata.get("analysis_report")])
    if stage == "specimen":
        candidates.extend([metadata.get("specimen_result"), metadata.get("fabrication_report"), metadata.get("specimen_fabricated")])
    if stage == "equipment":
        candidates.extend([metadata.get("equipment_result"), metadata.get("equipment_report"), metadata.get("utm_data_ready")])
    if stage == "manipulation":
        candidates.extend([metadata.get("manipulation_report"), metadata.get("robot_task_result")])
    if stage == "vision":
        candidates.extend([metadata.get("vision_report"), metadata.get("vision_signal"), metadata.get("latest_vision_observation")])
    if stage == "bo":
        candidates.extend([metadata.get("bo_agent"), metadata.get("next_design_request")])
    if stage == "knowledge":
        candidates.append(metadata.get("knowledge"))
    if stage == "guardian":
        candidates.extend([metadata.get("guardian"), metadata.get("latest_guardian_decision")])
    merged: dict[str, Any] = {}
    for candidate in candidates:
        if isinstance(candidate, dict):
            merged.update(candidate)
    return merged


def _collect_warnings(payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for key in ("warnings", "risk_flags", "failure_tags", "blocking_reasons"):
        value = payload.get(key)
        if isinstance(value, list):
            warnings.extend(str(item) for item in value if item)
    status = str(payload.get("status") or payload.get("handoff_status") or "").lower()
    if status in {"warning", "blocked", "failed", "error"}:
        warnings.append(f"status={status}")
    return list(dict.fromkeys(warnings))[:12]


def _find_failure_code(payload: dict[str, Any]) -> str:
    for key in ("failure_code", "error_code", "incident_code"):
        value = payload.get(key)
        if value:
            return str(value)
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    return str(decision.get("failure_code") or "")


def _find_missing_fields(stage: str, payload: dict[str, Any]) -> list[str]:
    required_by_stage = {
        "design": ["design_candidate", "handoff_to_specimen"],
        "specimen": ["specimen_fabricated", "fabrication_report"],
        "vision": ["vision_signal"],
        "manipulation": ["robot_task_result"],
        "equipment": ["utm_data_ready"],
        "analysis": ["bo_observation", "knowledge_payload"],
        "knowledge": ["knowledge_report", "evolution_evidence_packs"],
        "bo": ["next_design_request"],
        "guardian": ["guardian_decision"],
    }
    required = required_by_stage.get(stage, [])
    return [key for key in required if key not in payload]


def _artifact_count(payload: dict[str, Any]) -> int:
    count = 0
    for key in ("artifact_refs", "artifacts", "artifact_records", "evidence_refs", "screen_evidence_refs", "data_evidence_refs"):
        value = payload.get(key)
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += len(value)
    return count


def _find_latency(payload: dict[str, Any]) -> float:
    for key in ("latency_s", "duration_s", "elapsed_s"):
        try:
            value = float(payload.get(key))
            if value >= 0:
                return value
        except Exception:
            continue
    return 0.0
