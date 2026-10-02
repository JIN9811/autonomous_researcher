"""Persistence tests for objective definitions and immutable run bindings."""

from __future__ import annotations

import pytest

from objectives.schemas import ObjectiveBinding, ObjectiveDecision, ObjectiveSpec
from objectives.store import ObjectiveConflict, ObjectiveStore


def sample_spec(version: int = 1) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="durable-objective",
        version=version,
        name="Durable objective",
        expression={"op": "metric", "metric_id": "compressive_strength_mpa"},
    )


def test_store_round_trips_specs_and_append_only_decisions(tmp_path) -> None:
    store = ObjectiveStore(tmp_path / "memory" / "objectives", run_root=tmp_path / "runs")
    spec = sample_spec()
    decision = ObjectiveDecision(
        decision_id="decision-1",
        action="approve",
        objective_id=spec.objective_id,
        version=spec.version,
        objective_hash="hash-a",
        operator="operator",
    )

    store.save_spec(spec)
    store.append_decision(decision)

    assert store.load_spec(spec.objective_id, 1) == spec
    assert store.latest_version(spec.objective_id) == 1
    assert store.list_decisions() == [decision.model_dump(mode="json")]


def test_store_rejects_mutating_existing_spec(tmp_path) -> None:
    store = ObjectiveStore(tmp_path / "memory" / "objectives", run_root=tmp_path / "runs")
    store.save_spec(sample_spec())

    with pytest.raises(ObjectiveConflict, match="immutable"):
        store.save_spec(sample_spec().model_copy(update={"name": "changed"}))


def test_run_binding_is_immutable_and_written_to_run_artifacts(tmp_path) -> None:
    store = ObjectiveStore(tmp_path / "memory" / "objectives", run_root=tmp_path / "runs")
    binding = ObjectiveBinding(
        run_id="run-2",
        objective_id="durable-objective",
        version=1,
        objective_hash="hash-a",
        activated_by="operator",
    )

    store.bind_run(binding)

    assert store.load_binding("run-2") == binding
    assert (tmp_path / "runs" / "run-2" / "objective" / "binding.json").exists()
    with pytest.raises(ObjectiveConflict, match="already bound"):
        store.bind_run(binding.model_copy(update={"objective_hash": "hash-b"}))
