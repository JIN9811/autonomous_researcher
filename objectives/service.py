"""Objective composition, preview, approval, activation, and evaluation lifecycle."""

from __future__ import annotations

import json
import math
import statistics
import uuid
from typing import Any

from objectives.compiler import compile_objective, validate_objective
from objectives.evaluator import evaluate_objective
from objectives.metric_registry import MetricRegistry
from objectives.schemas import (
    ALLOWED_OPERATORS,
    ObjectiveBinding,
    ObjectiveDecision,
    ObjectiveEvaluation,
    ObjectivePreview,
    ObjectiveSpec,
    ObjectiveValidation,
)
from objectives.store import ObjectiveConflict, ObjectiveNotFound, ObjectiveStore

__all__ = ["ObjectiveConflict", "ObjectiveNotFound", "ObjectiveService"]


class ObjectiveService:
    """Coordinates untrusted LLM composition with deterministic lifecycle gates."""

    def __init__(self, *, store: ObjectiveStore, registry: MetricRegistry, context: Any = None) -> None:
        self.store = store
        self.registry = registry
        self.context = context

    @classmethod
    def default(cls, *, project_root=None, context: Any = None) -> "ObjectiveService":
        return cls(store=ObjectiveStore.default(project_root), registry=MetricRegistry.default(), context=context)

    def create_draft(self, spec: ObjectiveSpec | dict[str, Any]) -> ObjectiveSpec:
        parsed = spec if isinstance(spec, ObjectiveSpec) else ObjectiveSpec.model_validate(spec)
        if parsed.lifecycle != "draft":
            parsed = parsed.model_copy(update={"lifecycle": "draft"})
        self.store.save_spec(parsed)
        self.store.append_decision(
            ObjectiveDecision(
                decision_id=f"objective-decision-{uuid.uuid4().hex}",
                action="compose",
                objective_id=parsed.objective_id,
                version=parsed.version,
                objective_hash=validate_objective(parsed, self.registry).objective_hash,
                reason=parsed.intent,
            )
        )
        return parsed

    def _composition_prompt(self, intent: str, *, current: ObjectiveSpec | None = None) -> str:
        metrics = [item.model_dump(mode="json") for item in self.registry.list()]
        contract = {
            "schema_version": "objective_spec.v1",
            "required": ["objective_id", "version", "direction", "expression"],
            "allowed_operators": sorted(ALLOWED_OPERATORS - {"reference"}),
            "constraints": "list of boolean expression nodes",
            "prohibited": ["python", "shell", "cypher", "filesystem paths", "unregistered metrics"],
        }
        revision = current.model_dump(mode="json") if current else None
        return (
            "Return exactly one JSON object and no Markdown. Compose a bounded objective_spec.v1 from the operator intent. "
            "Use only the supplied metric ids and operators. Every division requires positive epsilon. "
            f"intent={json.dumps(intent, ensure_ascii=True)}\n"
            f"metric_registry={json.dumps(metrics, ensure_ascii=True)}\n"
            f"contract={json.dumps(contract, ensure_ascii=True)}\n"
            f"current_spec={json.dumps(revision, ensure_ascii=True)}"
        )

    async def compose(self, intent: str) -> ObjectiveSpec:
        if self.context is None:
            raise RuntimeError("objective composition requires AgentContext")
        response = await self.context.complete(
            "objective_composition",
            self._composition_prompt(intent),
            timeout_s=90.0,
            owner="objective-compiler",
        )
        try:
            payload = json.loads(response.text.strip())
        except json.JSONDecodeError as exc:
            raise ValueError("objective composer must return one strict JSON object") from exc
        if not isinstance(payload, dict):
            raise ValueError("objective composer must return one JSON object")
        payload["intent"] = str(payload.get("intent") or intent)
        return self.create_draft(payload)

    async def revise(self, objective_id: str, instruction: str) -> ObjectiveSpec:
        if self.context is None:
            raise RuntimeError("objective revision requires AgentContext")
        current = self.store.load_spec(objective_id)
        response = await self.context.complete(
            "objective_composition",
            self._composition_prompt(instruction, current=current),
            timeout_s=90.0,
            owner="objective-compiler",
        )
        try:
            payload = json.loads(response.text.strip())
        except json.JSONDecodeError as exc:
            raise ValueError("objective composer must return one strict JSON object") from exc
        if not isinstance(payload, dict):
            raise ValueError("objective composer must return one JSON object")
        payload["objective_id"] = current.objective_id
        payload["version"] = current.version + 1
        payload["intent"] = str(payload.get("intent") or instruction)
        draft = self.create_draft(payload)
        self.store.append_decision(
            ObjectiveDecision(
                decision_id=f"objective-decision-{uuid.uuid4().hex}",
                action="revise",
                objective_id=draft.objective_id,
                version=draft.version,
                objective_hash=validate_objective(draft, self.registry).objective_hash,
                reason=instruction,
            )
        )
        return draft

    def validate(self, objective_id: str, version: int | None = None) -> ObjectiveValidation:
        spec = self.store.load_spec(objective_id, version)
        validation = validate_objective(spec, self.registry)
        self.store.save_validation(validation)
        self.store.append_decision(
            ObjectiveDecision(
                decision_id=f"objective-decision-{uuid.uuid4().hex}",
                action="validate",
                objective_id=spec.objective_id,
                version=spec.version,
                objective_hash=validation.objective_hash,
                reason="valid" if validation.valid else "; ".join(validation.errors[:3]),
            )
        )
        return validation

    @staticmethod
    def _pearson(xs: list[float], ys: list[float]) -> float:
        if len(xs) < 2 or len(xs) != len(ys):
            return 0.0
        mean_x = statistics.fmean(xs)
        mean_y = statistics.fmean(ys)
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
        denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
        return numerator / denominator if denominator else 0.0

    def preview(
        self,
        objective_id: str,
        version: int | None,
        observations: list[dict[str, Any]],
    ) -> ObjectivePreview:
        spec = self.store.load_spec(objective_id, version)
        compiled = compile_objective(spec, self.registry)
        evaluations: list[ObjectiveEvaluation] = []
        rejected: list[dict[str, str]] = []
        missing_rows = 0
        fidelity_groups: dict[str, int] = {}
        metric_series: dict[str, list[float]] = {metric_id: [] for metric_id in compiled.validation.metric_ids}
        uncertainty_values: list[float] = []
        for index, observation in enumerate(observations):
            observation_id = str(observation.get("observation_id") or f"preview-{index}")
            metrics = observation.get("metrics") if isinstance(observation.get("metrics"), dict) else {}
            missing = [metric_id for metric_id in compiled.validation.metric_ids if metric_id not in metrics or metrics.get(metric_id) is None]
            if missing:
                missing_rows += 1
                rejected.append({"observation_id": observation_id, "reason": "missing_metrics:" + ",".join(missing)})
                continue
            if observation.get("quality_ok") is False:
                rejected.append({"observation_id": observation_id, "reason": "quality_rejected"})
                continue
            try:
                evaluation = evaluate_objective(
                    compiled,
                    metrics,
                    observation_id,
                    observation.get("uncertainty"),
                    provenance_refs=[str(item) for item in observation.get("provenance_refs", [])],
                    fidelity=str(observation.get("fidelity") or "measured"),
                )
            except (ValueError, TypeError) as exc:
                rejected.append({"observation_id": observation_id, "reason": str(exc)[:240]})
                continue
            evaluations.append(evaluation)
            fidelity_groups[evaluation.fidelity] = fidelity_groups.get(evaluation.fidelity, 0) + 1
            for metric_id in metric_series:
                metric_series[metric_id].append(evaluation.metrics[metric_id])
            if evaluation.uncertainty is not None:
                uncertainty_values.append(evaluation.uncertainty)

        scores = [item.score for item in evaluations]
        contribution_keys = sorted({key for item in evaluations for key in item.term_contributions})
        contribution_summary = {
            key: statistics.fmean(item.term_contributions.get(key, 0.0) for item in evaluations)
            for key in contribution_keys
        }
        preview = ObjectivePreview(
            objective_id=spec.objective_id,
            version=spec.version,
            objective_hash=compiled.objective_hash,
            usable_rows=len(evaluations),
            missing_rows=missing_rows,
            rejected_rows=len(rejected) - missing_rows,
            total_rows=len(observations),
            feasible_ratio=(sum(item.feasible for item in evaluations) / len(evaluations)) if evaluations else None,
            score_distribution={
                "min": min(scores) if scores else None,
                "max": max(scores) if scores else None,
                "mean": statistics.fmean(scores) if scores else None,
                "median": statistics.median(scores) if scores else None,
                "stdev": statistics.pstdev(scores) if len(scores) > 1 else 0.0 if scores else None,
            },
            contribution_summary=contribution_summary,
            sensitivity={metric_id: self._pearson(values, scores) for metric_id, values in metric_series.items()},
            uncertainty_stability={
                "mean": statistics.fmean(uncertainty_values) if uncertainty_values else None,
                "max": max(uncertainty_values) if uncertainty_values else None,
            },
            fidelity_groups=fidelity_groups,
            observation_refs=[item.observation_id for item in evaluations],
            rejected=rejected,
        )
        self.store.save_preview(preview)
        self.store.append_decision(
            ObjectiveDecision(
                decision_id=f"objective-decision-{uuid.uuid4().hex}",
                action="preview",
                objective_id=spec.objective_id,
                version=spec.version,
                objective_hash=compiled.objective_hash,
                reason=f"usable={preview.usable_rows};missing={preview.missing_rows};rejected={preview.rejected_rows}",
            )
        )
        return preview

    def _approved_hash(self, objective_id: str, version: int) -> str | None:
        for decision in reversed(self.store.list_decisions()):
            if (
                decision.get("action") == "approve"
                and decision.get("objective_id") == objective_id
                and int(decision.get("version") or 0) == version
            ):
                return str(decision.get("objective_hash") or "")
        return None

    def approve(self, objective_id: str, version: int | None = None, *, operator: str) -> ObjectiveDecision:
        spec = self.store.load_spec(objective_id, version)
        validation = self.store.load_validation(spec.objective_id, spec.version)
        if validation is None or not validation.valid:
            raise ObjectiveConflict("successful validation is required before approval")
        preview = self.store.load_preview(spec.objective_id, spec.version)
        if preview is None or preview.usable_rows < 1:
            raise ObjectiveConflict("successful preview with usable observations is required before approval")
        if preview.objective_hash != validation.objective_hash:
            raise ObjectiveConflict("validation and preview objective hashes do not match")
        decision = ObjectiveDecision(
            decision_id=f"objective-decision-{uuid.uuid4().hex}",
            action="approve",
            objective_id=spec.objective_id,
            version=spec.version,
            objective_hash=validation.objective_hash,
            operator=operator.strip(),
            reason="operator approved validated preview",
        )
        if not decision.operator:
            raise ValueError("operator is required")
        self.store.append_decision(decision)
        return decision

    def activate(self, objective_id: str, version: int, *, run_id: str, operator: str) -> ObjectiveBinding:
        approved_hash = self._approved_hash(objective_id, version)
        if not approved_hash:
            raise ObjectiveConflict("recorded approval is required before activation")
        compiled = compile_objective(self.store.load_spec(objective_id, version), self.registry)
        if compiled.objective_hash != approved_hash:
            raise ObjectiveConflict("approved objective hash does not match compiled objective")
        binding = ObjectiveBinding(
            run_id=run_id,
            objective_id=objective_id,
            version=version,
            objective_hash=approved_hash,
            activated_by=operator,
        )
        self.store.bind_run(binding)
        self.store.append_decision(
            ObjectiveDecision(
                decision_id=f"objective-decision-{uuid.uuid4().hex}",
                action="activate",
                objective_id=objective_id,
                version=version,
                objective_hash=approved_hash,
                operator=operator,
                run_id=run_id,
            )
        )
        return binding

    def evaluate(
        self,
        *,
        run_id: str,
        metrics: dict[str, Any],
        observation_id: str,
        uncertainty: float | dict[str, float] | None = None,
        provenance_refs: list[str] | None = None,
        fidelity: str = "measured",
    ) -> ObjectiveEvaluation:
        binding = self.store.load_binding(run_id)
        if binding is None:
            raise ObjectiveNotFound(f"run {run_id} has no active objective binding")
        compiled = compile_objective(self.store.load_spec(binding.objective_id, binding.version), self.registry)
        if compiled.objective_hash != binding.objective_hash:
            raise ObjectiveConflict("active binding hash does not match stored objective")
        evaluation = evaluate_objective(
            compiled,
            metrics,
            observation_id,
            uncertainty,
            provenance_refs=provenance_refs,
            fidelity=fidelity,
        )
        self.store.append_evaluation(evaluation, run_id=run_id)
        return evaluation

    def compare(
        self,
        candidates: list[dict[str, Any]],
        observations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results = []
        for candidate in candidates:
            preview = self.preview(str(candidate["objective_id"]), int(candidate["version"]), observations)
            results.append(
                {
                    "objective_id": preview.objective_id,
                    "version": preview.version,
                    "objective_hash": preview.objective_hash,
                    "usable_rows": preview.usable_rows,
                    "score_distribution": preview.score_distribution,
                    "feasible_ratio": preview.feasible_ratio,
                }
            )
        return results

    def status(self, *, run_id: str = "") -> dict[str, Any]:
        specs = self.store.list_specs()
        binding = self.store.load_binding(run_id) if run_id else None
        return {
            "ok": True,
            "registry_version": self.registry.version_id,
            "metric_count": len(self.registry.list()),
            "objective_count": len(specs),
            "objectives": [item.model_dump(mode="json") for item in specs],
            "active_binding": binding.model_dump(mode="json") if binding else None,
            "evaluations": self.store.list_evaluations(run_id=run_id) if run_id else [],
        }
