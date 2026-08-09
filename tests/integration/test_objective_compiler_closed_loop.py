"""End-to-end regression for the compiled objective closed loop."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agents.analysis_agent import AnalysisAgent
from agents.bo_agent import BOAgent
from agents.knowledge_agent import KnowledgeAgent
from knowledge.experiment_db import ExperimentDB
from knowledge.stores import JsonlKnowledgeStore
from mcp_tools.cae_tools import register_cae_tools
from mcp_tools.experiment_tools import register_experiment_tools
from mcp_tools.tool_registry import ToolRegistry
from objectives.metric_registry import MetricRegistry
from objectives.service import ObjectiveService
from objectives.store import ObjectiveStore
from orchestrator.state import Mode, OrchestratorState, Stage


def _metric(metric_id: str) -> dict[str, Any]:
    return {"op": "metric", "metric_id": metric_id}


def _literal(value: float, unit: str = "1") -> dict[str, Any]:
    return {"op": "literal", "value": value, "unit": unit}


def _invalid_spec() -> dict[str, Any]:
    return {
        "schema_version": "objective_spec.v1",
        "objective_id": "closed-loop-compression",
        "version": 1,
        "name": "Invalid mixed-unit objective",
        "direction": "maximize",
        "expression": {
            "op": "add",
            "args": [_metric("compressive_strength_mpa"), _metric("displacement_at_peak_mm")],
        },
    }


def _corrected_spec() -> dict[str, Any]:
    return {
        "schema_version": "objective_spec.v1",
        "objective_id": "ignored-by-revise",
        "version": 99,
        "name": "Nonlinear compression performance",
        "direction": "maximize",
        "expression": {
            "op": "subtract",
            "args": [
                {
                    "op": "weighted_sum",
                    "terms": [
                        {
                            "name": "strength",
                            "weight": 0.7,
                            "expression": {
                                "op": "normalize",
                                "value": _metric("compressive_strength_mpa"),
                                "min": _literal(0.0, "MPa"),
                                "max": _literal(2.0, "MPa"),
                            },
                        },
                        {
                            "name": "energy",
                            "weight": 0.3,
                            "expression": {
                                "op": "normalize",
                                "value": _metric("specific_energy_absorption_j_per_g"),
                                "min": _literal(0.0, "J/g"),
                                "max": _literal(1.0, "J/g"),
                            },
                        },
                    ],
                },
                {
                    "op": "hinge_penalty",
                    "value": _metric("displacement_at_peak_mm"),
                    "threshold": _literal(4.0, "mm"),
                    "scale": _literal(4.0, "mm"),
                    "side": "above",
                },
            ],
        },
        "constraints": [
            {
                "op": "greater_equal",
                "args": [_metric("specific_energy_absorption_j_per_g"), _literal(0.0, "J/g")],
            }
        ],
    }


class _QueueLLMContext:
    def __init__(self, *payloads: dict[str, Any]) -> None:
        self.payloads = list(payloads)
        self.calls: list[str] = []

    async def complete(self, task_type: str, user_prompt: str, **_: Any) -> Any:
        self.calls.append(task_type)
        return SimpleNamespace(text=json.dumps(self.payloads.pop(0)))


class _RagStub:
    async def retrieve(self, *, query: str, top_k_local: int = 4) -> dict[str, Any]:
        return {"coverage": 1.0, "local_chunks": [], "web_results": []}


class _AgentContext:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools
        self.rag = _RagStub()
        self.experiment_db = ExperimentDB()
        self.force_real_llm_in_test = False

    async def complete(self, task_type: str, user_prompt: str, **_: Any) -> Any:
        return SimpleNamespace(text="deterministic test summary")


class _BOContext:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools


def _curve() -> list[dict[str, float]]:
    return [
        {"time_s": 0.0, "displacement_mm": 0.0, "force_N": 0.0},
        {"time_s": 0.5, "displacement_mm": 0.5, "force_N": 80.0},
        {"time_s": 1.0, "displacement_mm": 1.0, "force_N": 180.0},
        {"time_s": 1.5, "displacement_mm": 1.5, "force_N": 310.0},
        {"time_s": 2.0, "displacement_mm": 2.0, "force_N": 430.0},
        {"time_s": 2.5, "displacement_mm": 2.5, "force_N": 520.0},
        {"time_s": 3.0, "displacement_mm": 3.0, "force_N": 500.0},
        {"time_s": 3.5, "displacement_mm": 3.5, "force_N": 455.0},
        {"time_s": 4.0, "displacement_mm": 4.0, "force_N": 390.0},
        {"time_s": 4.5, "displacement_mm": 4.5, "force_N": 340.0},
        {"time_s": 5.0, "displacement_mm": 5.0, "force_N": 300.0},
    ]


@pytest.mark.asyncio
async def test_objective_compiler_analysis_knowledge_bo_survives_restart(tmp_path, monkeypatch) -> None:
    composer = _QueueLLMContext(_invalid_spec(), _corrected_spec())
    store = ObjectiveStore(tmp_path / "memory" / "objectives", run_root=tmp_path / "runs")
    service = ObjectiveService(store=store, registry=MetricRegistry.default(), context=composer)

    invalid = await service.compose("combine compression strength and displacement")
    invalid_validation = service.validate(invalid.objective_id, invalid.version)
    assert invalid_validation.valid is False
    assert "incompatible units" in invalid_validation.errors[0]

    corrected = await service.revise(invalid.objective_id, "normalize units and add a nonlinear displacement penalty")
    validation = service.validate(corrected.objective_id, corrected.version)
    preview = service.preview(
        corrected.objective_id,
        corrected.version,
        [
            {
                "observation_id": "preview-1",
                "metrics": {
                    "compressive_strength_mpa": 1.2,
                    "specific_energy_absorption_j_per_g": 0.2,
                    "displacement_at_peak_mm": 3.0,
                },
                "quality_ok": True,
                "fidelity": "measured",
                "provenance_refs": ["preview:utm-1"],
            }
        ],
    )
    assert validation.valid is True
    assert preview.usable_rows == 1
    service.approve(corrected.objective_id, corrected.version, operator="test-operator")
    binding = service.activate(
        corrected.objective_id,
        corrected.version,
        run_id="run-objective-e2e",
        operator="test-operator",
    )

    tools = ToolRegistry()
    tools.register_resource("objective.service", service)
    register_cae_tools(
        tools,
        {"devices": {"cae": {"enabled": True, "mode": "test", "artifact_dir": "artifacts/cae"}}},
        repo_root=tmp_path,
    )
    register_experiment_tools(tools)
    state = OrchestratorState(
        run_id="run-objective-e2e",
        experiment_id="experiment-objective-e2e",
        mode=Mode.TEST,
        stage=Stage.ANALYSIS,
        active_goal="optimize nonlinear compression performance",
        current_experiment_spec={
            "specimen_id": "specimen-objective-e2e",
            "specimen_size_mm": [20.0, 20.0, 20.0],
            "expected_mass_g": 6.0,
            "relative_density": 0.32,
            "wall_thickness_mm": 1.2,
            "cell_size_mm": 10.0,
        },
        current_experiment_objective={
            "schema_version": "objective_spec.v1",
            "objective_id": binding.objective_id,
            "version": binding.version,
            "objective_hash": binding.objective_hash,
            "direction": "maximize",
        },
        run_metadata={"equipment_result": {"ok": True, "tool": "equipment.pyautogui.run", "utm_data": _curve()}},
    )
    agent_ctx = _AgentContext(tools)
    analysis_result = await AnalysisAgent().run(state, agent_ctx)
    evaluation = analysis_result.data["analysis"]["objective_evaluation"]

    assert analysis_result.success is True
    assert evaluation["objective_hash"] == binding.objective_hash
    assert analysis_result.data["bo_handoff"]["objective_evaluation"]["objective_hash"] == binding.objective_hash

    state.stage = Stage.KNOWLEDGE
    state.latest_analysis = dict(analysis_result.data["analysis"])
    state.latest_analysis.update(
        bo_handoff=analysis_result.data["bo_handoff"],
        bo_observation=analysis_result.data["bo_observation"],
        experiment_evaluation=analysis_result.data["experiment_evaluation"],
    )
    state.experiment_evaluations.append(analysis_result.data["experiment_evaluation"])
    knowledge_store = JsonlKnowledgeStore(
        memory_root=tmp_path / "memory" / "knowledge",
        run_root=tmp_path / "runs",
    )
    monkeypatch.setattr(
        JsonlKnowledgeStore,
        "default",
        classmethod(lambda cls, project_root=None: knowledge_store),
    )
    knowledge_result = await KnowledgeAgent().run(state, agent_ctx)
    persisted = knowledge_store.list_experiment_records(objective_hash=binding.objective_hash)

    assert knowledge_result.success is True
    assert len(persisted) == 1
    assert persisted[0].objective_evaluation["observation_id"] == evaluation["observation_id"]

    state.stage = Stage.BO
    bo_result = await BOAgent().run_with_settings(state, _BOContext(tools), {"strategy": "bo", "budget": 2})
    request = bo_result.data["next_design_request"]

    assert bo_result.success is True
    integrity = bo_result.data["bo_result"]["observation_integrity"]
    assert integrity["accepted_observation_ids"] == [evaluation["observation_id"]], integrity
    assert request["objective_hash"] == binding.objective_hash
    assert request["objective_id"] == binding.objective_id
    assert request["objective_version"] == binding.version

    restarted = ObjectiveService(
        store=ObjectiveStore(tmp_path / "memory" / "objectives", run_root=tmp_path / "runs"),
        registry=MetricRegistry.default(),
        context=None,
    )
    replay = restarted.evaluate(
        run_id=state.run_id,
        metrics=evaluation["metrics"],
        observation_id="replay-without-llm",
        uncertainty=evaluation["uncertainty"],
        provenance_refs=evaluation["provenance_refs"],
        fidelity=evaluation["fidelity"],
    )

    assert composer.calls == ["objective_composition", "objective_composition"]
    assert restarted.status(run_id=state.run_id)["active_binding"]["objective_hash"] == binding.objective_hash
    assert replay.score == evaluation["score"]
