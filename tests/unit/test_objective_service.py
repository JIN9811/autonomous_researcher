"""Lifecycle and preview tests for ObjectiveService."""

from __future__ import annotations

import json

import pytest

from backends.llm_backend import LLMResponse
from objectives.metric_registry import MetricRegistry
from objectives.schemas import ObjectiveSpec
from objectives.service import ObjectiveConflict, ObjectiveService
from objectives.store import ObjectiveStore


def make_service(tmp_path, context=None) -> ObjectiveService:
    return ObjectiveService(
        store=ObjectiveStore(tmp_path / "memory" / "objectives", run_root=tmp_path / "runs"),
        registry=MetricRegistry.default(),
        context=context,
    )


def sample_spec() -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="service-objective",
        version=1,
        name="Strength and energy",
        intent="Prefer strong, energy-absorbing specimens",
        expression={
            "op": "weighted_sum",
            "terms": [
                {
                    "name": "strength",
                    "weight": 0.6,
                    "expression": {
                        "op": "normalize",
                        "value": {"op": "metric", "metric_id": "compressive_strength_mpa"},
                        "min": {"op": "literal", "value": 0.0, "unit": "MPa"},
                        "max": {"op": "literal", "value": 10.0, "unit": "MPa"},
                    },
                },
                {
                    "name": "energy",
                    "weight": 0.4,
                    "expression": {
                        "op": "normalize",
                        "value": {"op": "metric", "metric_id": "specific_energy_absorption_j_per_g"},
                        "min": {"op": "literal", "value": 0.0, "unit": "J/g"},
                        "max": {"op": "literal", "value": 0.4, "unit": "J/g"},
                    },
                },
            ],
        },
    )


def observations() -> list[dict]:
    return [
        {
            "observation_id": "obs-1",
            "metrics": {"compressive_strength_mpa": 5.0, "specific_energy_absorption_j_per_g": 0.2},
            "uncertainty": 0.1,
            "fidelity": "measured",
            "quality_ok": True,
            "provenance_refs": ["analysis-1"],
        },
        {
            "observation_id": "obs-2",
            "metrics": {"compressive_strength_mpa": 7.0, "specific_energy_absorption_j_per_g": 0.3},
            "uncertainty": 0.08,
            "fidelity": "synthetic",
            "quality_ok": True,
            "provenance_refs": ["analysis-2"],
        },
        {
            "observation_id": "obs-missing",
            "metrics": {"compressive_strength_mpa": 2.0},
            "fidelity": "measured",
            "quality_ok": True,
        },
        {
            "observation_id": "obs-rejected",
            "metrics": {"compressive_strength_mpa": 4.0, "specific_energy_absorption_j_per_g": 0.1},
            "fidelity": "measured",
            "quality_ok": False,
        },
    ]


def prepare(service: ObjectiveService):
    service.create_draft(sample_spec())
    validation = service.validate("service-objective", 1)
    preview = service.preview("service-objective", 1, observations())
    return validation, preview


def test_preview_separates_usable_missing_and_rejected_rows(tmp_path) -> None:
    service = make_service(tmp_path)

    validation, preview = prepare(service)

    assert validation.valid is True
    assert preview.usable_rows == 2
    assert preview.missing_rows == 1
    assert preview.rejected_rows == 1
    assert preview.observation_refs == ["obs-1", "obs-2"]
    assert preview.fidelity_groups == {"measured": 1, "synthetic": 1}
    assert preview.score_distribution["max"] > preview.score_distribution["min"]
    assert set(preview.contribution_summary) == {"energy", "strength"}
    assert set(preview.sensitivity) == {"compressive_strength_mpa", "specific_energy_absorption_j_per_g"}
    assert preview.uncertainty_stability["mean"] == pytest.approx(0.09)


def test_active_version_is_immutable_and_run_bound(tmp_path) -> None:
    service = make_service(tmp_path)
    prepare(service)
    approved = service.approve("service-objective", 1, operator="operator")

    active = service.activate(approved.objective_id, approved.version, run_id="run-2", operator="operator")

    assert active.objective_hash == approved.objective_hash
    service.create_draft(sample_spec().model_copy(update={"version": 2}))
    service.validate("service-objective", 2)
    service.preview("service-objective", 2, observations())
    service.approve("service-objective", 2, operator="operator")
    with pytest.raises(ObjectiveConflict, match="already bound"):
        service.activate("service-objective", 2, run_id="run-2", operator="operator")


def test_restart_preserves_binding_and_evaluation(tmp_path) -> None:
    service = make_service(tmp_path)
    prepare(service)
    service.approve("service-objective", 1, operator="operator")
    service.activate("service-objective", 1, run_id="run-2", operator="operator")
    evaluation = service.evaluate(
        run_id="run-2",
        metrics={"compressive_strength_mpa": 5.0, "specific_energy_absorption_j_per_g": 0.2},
        observation_id="obs-restart",
    )

    restarted = make_service(tmp_path)

    assert restarted.status(run_id="run-2")["active_binding"]["objective_hash"] == evaluation.objective_hash
    assert restarted.evaluate(
        run_id="run-2",
        metrics={"compressive_strength_mpa": 5.0, "specific_energy_absorption_j_per_g": 0.2},
        observation_id="obs-restart",
    ).score == evaluation.score


def test_approval_requires_successful_validation_and_preview(tmp_path) -> None:
    service = make_service(tmp_path)
    service.create_draft(sample_spec())

    with pytest.raises(ObjectiveConflict, match="validation"):
        service.approve("service-objective", 1, operator="operator")


class _Context:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def complete(self, task_type: str, prompt: str, **kwargs) -> LLMResponse:
        self.calls.append((task_type, prompt))
        return LLMResponse(text=json.dumps(self.payload), model="fake")


@pytest.mark.asyncio
async def test_compose_uses_llm_once_and_persists_valid_json_draft(tmp_path) -> None:
    payload = sample_spec().model_dump(mode="json")
    context = _Context(payload)
    service = make_service(tmp_path, context=context)

    draft = await service.compose("maximize useful compression performance")

    assert draft.objective_id == "service-objective"
    assert context.calls[0][0] == "objective_composition"
    assert "compressive_strength_mpa" in context.calls[0][1]
    assert service.store.load_spec("service-objective", 1) == draft
