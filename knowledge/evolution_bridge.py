"""Bridge typed Knowledge memory into Self-Evolution evidence packs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from knowledge.provenance import build_provenance_ref, stable_id
from knowledge.schemas import AgentPerformanceRecord, EvolutionEvidencePack, EvolutionOutcomeRecord, ExperimentKnowledgeRecord, FailurePatternRecord, ProvenanceRef, SuccessPatternRecord


def build_evidence_packs(
    *,
    run_id: str,
    experiment_record: ExperimentKnowledgeRecord,
    performance_records: list[AgentPerformanceRecord],
    failure_patterns: list[FailurePatternRecord],
    success_patterns: list[SuccessPatternRecord],
    ranked_targets: list[dict[str, Any]],
    evidence_refs: list[dict[str, Any]],
    limit: int = 5,
) -> list[EvolutionEvidencePack]:
    """Create reviewable evidence packs for the top evolution targets."""
    now = datetime.now(timezone.utc).isoformat()
    packs: list[EvolutionEvidencePack] = []
    perf_by_agent = {record.agent_id: record for record in performance_records}
    failures_by_agent: dict[str, list[FailurePatternRecord]] = {}
    for pattern in failure_patterns:
        agents = pattern.affected_agents or [str((pattern.recommended_evolution or {}).get("target_id") or "knowledge")]
        for agent in agents:
            failures_by_agent.setdefault(agent, []).append(pattern)
    success_by_agent: dict[str, list[SuccessPatternRecord]] = {}
    for pattern in success_patterns:
        success_by_agent.setdefault(pattern.agent_id, []).append(pattern)
    for target in ranked_targets[:limit]:
        target_id = str(target.get("target_id") or "knowledge")
        target_type = str(target.get("target_type") or "prompt")
        perf = perf_by_agent.get(target_id)
        failures = failures_by_agent.get(target_id, [])
        successes = success_by_agent.get(target_id, [])
        why = [str(item) for item in target.get("reasons", []) if item]
        why.extend(pattern.root_cause_hypothesis for pattern in failures if pattern.root_cause_hypothesis)
        why = list(dict.fromkeys(why))[:6]
        recommended_changes = _recommended_changes(target_id, failures, perf)
        constraints = {
            "require_human_approval": True,
            "no_live_hardware_execution": True,
            "no_live_synthetic_fallback": True,
            "preserve_raw_artifact": True,
            "must_emit_failure_code": True,
        }
        pack_id = stable_id("evo-pack", run_id, target_type, target_id, why, recommended_changes)
        packs.append(
            EvolutionEvidencePack(
                pack_id=pack_id,
                target_type=target_type,
                target_id=target_id,
                priority=float(target.get("priority") or 0.0),
                objective=_objective_for_target(target_id, failures, perf),
                why_this_target=why or [f"{target_id} has runtime evidence that should be reviewed before the next run."],
                supporting_records={
                    "experiment_records": [experiment_record.record_id],
                    "agent_performance_records": [perf.record_id] if perf else [],
                    "failure_patterns": [pattern.pattern_id for pattern in failures],
                    "success_patterns": [pattern.skill_id for pattern in successes],
                    "artifact_refs": evidence_refs,
                },
                recommended_changes=recommended_changes,
                constraints=constraints,
                eval_metrics={
                    "primary": "contract_validity_delta",
                    "secondary": ["missing_field_rate", "warning_count_delta", "artifact_completeness", "gate_pass_rate"],
                },
                blocked=False,
                provenance=build_provenance_ref(
                    run_id=run_id,
                    used=["experiment_knowledge_record.json", "agent_performance_records.json", "failure_patterns.json"],
                    associated_with=[target_id, "knowledge_agent", "self_evolution_service"],
                    derived_from=[run_id],
                    artifact_refs=evidence_refs,
                ),
                created_at=now,
            )
        )
    return packs



def build_outcomes_for_active_variants(
    *,
    run_id: str,
    performance_records: list[AgentPerformanceRecord],
    evolution_root: Path,
    existing_outcomes: list[EvolutionOutcomeRecord],
    evidence_refs: list[dict[str, Any]],
) -> list[EvolutionOutcomeRecord]:
    """Attribute active self-evolution variants against the current run ledger.

    This is conservative bookkeeping, not automatic promotion or rollback. It records
    an observable after-run snapshot for each active variant so the operator can
    compare trends and decide keep/observe/rollback later.
    """
    active_path = evolution_root / "active_variants.json"
    if not active_path.exists():
        return []
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(active, dict):
        return []
    existing_keys = {(item.variant_id, item.activated_for_run_id, item.target_type, item.target_id) for item in existing_outcomes}
    perf_by_agent = {record.agent_id: record for record in performance_records}
    all_warning_count = sum(_signal_count(record, "warnings") for record in performance_records)
    all_missing_count = sum(_signal_count(record, "missing_required_fields") for record in performance_records)
    all_error_count = sum(1 for record in performance_records if record.status == "failed")
    avg_score = round(sum(record.score for record in performance_records) / max(1, len(performance_records)), 4) if performance_records else 0.0
    now = datetime.now(timezone.utc).isoformat()
    outcomes: list[EvolutionOutcomeRecord] = []
    for key, activation in active.items():
        if not isinstance(activation, dict):
            continue
        try:
            target_type, target_id = str(key).split(":", 1)
        except ValueError:
            target_type = str(activation.get("target_type") or "unknown")
            target_id = str(activation.get("target_id") or key)
        variant_id = str(activation.get("variant_id") or "")
        if not variant_id or (variant_id, run_id, target_type, target_id) in existing_keys:
            continue
        variant_payload = _read_variant_payload(evolution_root, variant_id)
        trace_metrics = ((variant_payload.get("metrics") or {}).get("trace_metrics") or {}) if isinstance(variant_payload, dict) else {}
        perf = perf_by_agent.get(target_id)
        after_warning_count = _signal_count(perf, "warnings") if perf else all_warning_count
        after_missing_count = _signal_count(perf, "missing_required_fields") if perf else all_missing_count
        after_error_count = (1 if perf and perf.status == "failed" else 0) if perf else all_error_count
        after_score = float(perf.score) if perf else avg_score
        before_warning_count = float(trace_metrics.get("warning_count") or 0.0) if isinstance(trace_metrics, dict) else 0.0
        before_error_count = float(trace_metrics.get("error_count") or 0.0) if isinstance(trace_metrics, dict) else 0.0
        metrics_delta = {
            "warning_count_delta": after_warning_count - before_warning_count,
            "error_count_delta": after_error_count - before_error_count,
            "missing_field_count_after": after_missing_count,
            "agent_score_after": after_score,
            "artifact_completeness_after": _signal_float(perf, "artifact_completeness", 0.0) if perf else 0.0,
            "contract_validity_after": _signal_float(perf, "contract_validity", 0.0) if perf else 0.0,
        }
        rollback_recommended = bool(after_error_count > before_error_count and after_score < 0.5)
        verdict = "rollback_review" if rollback_recommended else "promising_keep_observing" if after_score >= 0.8 and after_warning_count <= before_warning_count else "observe"
        parent_version = str(variant_payload.get("parent_version") or activation.get("parent_version") or "") if isinstance(variant_payload, dict) else str(activation.get("parent_version") or "")
        source_runs = []
        if isinstance(variant_payload, dict):
            for trace_id in variant_payload.get("source_trace_ids", []) or []:
                if isinstance(trace_id, str) and trace_id.startswith("trace-"):
                    source_runs.append(trace_id.removeprefix("trace-"))
        outcome_id = stable_id("evolution-outcome", variant_id, run_id, target_type, target_id)
        outcomes.append(
            EvolutionOutcomeRecord(
                outcome_id=outcome_id,
                variant_id=variant_id,
                target_type=target_type,
                target_id=target_id,
                parent_version=parent_version,
                activated_for_run_id=run_id,
                comparison_window={"before_runs": source_runs, "after_runs": [run_id]},
                metrics_delta=metrics_delta,
                verdict=verdict,
                rollback_recommended=rollback_recommended,
                provenance=ProvenanceRef(
                    was_generated_by="knowledge_agent",
                    used=["active_variants.json", f"variants/{variant_id}.json", "agent_performance_records.json"],
                    was_associated_with=[target_id, "knowledge_agent", "self_evolution_service"],
                    was_derived_from=source_runs + [run_id],
                    artifact_fingerprints={str(index): str(ref.get("path") or ref.get("artifact_id") or ref) for index, ref in enumerate(evidence_refs[:8]) if isinstance(ref, dict)},
                ),
                created_at=now,
            )
        )
    return outcomes

def map_pack_to_evolution_task(pack: EvolutionEvidencePack) -> dict[str, Any]:
    """Return an EvolutionTaskCreate-compatible payload without importing service models."""
    source_runs = pack.provenance.was_derived_from or []
    return {
        "target_type": pack.target_type,
        "target_id": pack.target_id,
        "source_run_ids": source_runs,
        "objective": pack.objective,
        "constraints": pack.constraints | {"knowledge_evidence_pack_id": pack.pack_id},
    }


def score_evolution_outcome(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compute a conservative before/after delta for a variant outcome."""
    keys = sorted(set(before) | set(after))
    delta: dict[str, Any] = {}
    for key in keys:
        try:
            delta[key] = float(after.get(key, 0.0)) - float(before.get(key, 0.0))
        except Exception:
            continue
    return delta


def _objective_for_target(target_id: str, failures: list[FailurePatternRecord], perf: AgentPerformanceRecord | None) -> str:
    if failures:
        first = failures[0]
        return str((first.recommended_evolution or {}).get("objective") or f"Reduce recurrence of {first.failure_type} in {target_id}.")
    if perf and perf.evolution_hint.get("reason"):
        return f"Improve {target_id} runtime contract reliability: {perf.evolution_hint['reason']}"
    return f"Improve {target_id} next-run reliability using Knowledge evidence."


def _recommended_changes(target_id: str, failures: list[FailurePatternRecord], perf: AgentPerformanceRecord | None) -> list[str]:
    changes: list[str] = []
    for pattern in failures:
        changes.extend(pattern.do_not_repeat)
        rec = pattern.recommended_evolution or {}
        if rec.get("objective"):
            changes.append(str(rec["objective"]))
    if perf:
        missing = perf.signals.get("missing_required_fields") if isinstance(perf.signals, dict) else []
        if missing:
            changes.append(f"Emit required fields before handoff: {', '.join(str(item) for item in missing[:6])}.")
        warnings = perf.signals.get("warnings") if isinstance(perf.signals, dict) else []
        if warnings:
            changes.append("Explain warning causes, uncertainty, and recovery choice in the agent report.")
    if not changes:
        changes.append(f"Preserve {target_id} contract fields and make uncertainty explicit for Guardian review.")
    return list(dict.fromkeys(changes))[:8]


def _read_variant_payload(evolution_root: Path, variant_id: str) -> dict[str, Any]:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in variant_id)
    if safe != variant_id:
        return {}
    path = evolution_root / "variants" / f"{safe}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _signal_count(record: AgentPerformanceRecord | None, key: str) -> int:
    if record is None or not isinstance(record.signals, dict):
        return 0
    value = record.signals.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return int(bool(value))


def _signal_float(record: AgentPerformanceRecord | None, key: str, default: float = 0.0) -> float:
    if record is None or not isinstance(record.signals, dict):
        return default
    try:
        return float(record.signals.get(key, default))
    except Exception:
        return default
