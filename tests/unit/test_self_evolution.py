"""Tests for ATR self-evolution service gates and versioned activation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from graphs import HandlerRegistry, load_graph_config
from self_evolution import EvolutionTaskCreate, SelfEvolutionService
from self_evolution.registry import EvolutionRegistry
from self_evolution.trace_collector import TraceCollector


async def _noop_handler(runtime_state: dict[str, object]) -> dict[str, object]:
    return runtime_state


def _write_run_trace(run_root: Path, run_id: str = "run-self-evolution-smoke") -> str:
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True)
    events = [
        {
            "type": "run_started",
            "stage": "idle",
            "payload": {"graph_id": "atr_closed_loop", "graph_version": "0.2.0"},
        },
        {
            "type": "agent_started",
            "stage": "design",
            "payload": {"node_id": "design"},
        },
        {
            "type": "tool_call_failed",
            "level": "ERROR",
            "stage": "specimen",
            "payload": {"node_id": "specimen", "failure_code": "MISSING_FIELD"},
        },
        {
            "event_type": "approval_requested",
            "level": "WARNING",
            "payload": {"stage": "guardian"},
        },
    ]
    (run_dir / "structured.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    (run_dir / "artifact.stl").write_text("solid smoke\nendsolid smoke\n", encoding="utf-8")
    return run_id


def _copy_design_module(module_root: Path) -> None:
    dst = module_root / "design"
    dst.mkdir(parents=True)
    shutil.copy2(Path("graphs/modules/design/module.yaml"), dst / "module.yaml")


def _copy_closed_loop_graph(graph_root: Path) -> Path:
    graph_root.mkdir(parents=True)
    dst = graph_root / "atr_closed_loop.yaml"
    shutil.copy2(Path("graphs/configs/atr_closed_loop.yaml"), dst)
    return dst


def _registry_for_handlers(handler_ids: set[str]) -> HandlerRegistry:
    registry = HandlerRegistry()
    for handler_id in handler_ids:
        registry.register(handler_id, _noop_handler)
    return registry


def _service(tmp_path: Path) -> SelfEvolutionService:
    run_root = tmp_path / "runs"
    module_root = tmp_path / "modules"
    graph_root = tmp_path / "graphs"
    _write_run_trace(run_root)
    _copy_design_module(module_root)
    _copy_closed_loop_graph(graph_root)
    return SelfEvolutionService(
        root=tmp_path / "memory" / "evolution",
        run_root=run_root,
        graph_config_root=graph_root,
        graph_version_root=tmp_path / "memory" / "graph_versions",
        module_root=module_root,
        module_version_root=tmp_path / "memory" / "module_versions",
    )


def test_trace_collector_extracts_metrics_and_blocks_unsafe_ids(tmp_path: Path) -> None:
    run_id = _write_run_trace(tmp_path / "runs")
    collector = TraceCollector(tmp_path / "runs")

    trace = collector.collect_one(run_id)

    assert trace.run_id == run_id
    assert trace.graph_id == "atr_closed_loop"
    assert trace.metrics["event_count"] == 4
    assert trace.metrics["artifact_count"] == 1
    assert trace.metrics["error_count"] == 1
    assert trace.metrics["warning_count"] == 1
    assert trace.metrics["approval_count"] == 1
    assert trace.metrics["stage_counts"]["specimen"] == 1
    with pytest.raises(ValueError):
        collector.collect_one("../run-self-evolution-smoke")


def test_prompt_evolution_generates_gate_passed_variant_and_activates_next_run(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    registry = _registry_for_handlers({"agent.design_agent"})
    task = svc.create_task(
        EvolutionTaskCreate(
            target_type="prompt",
            target_id="design",
            source_run_ids=["run-self-evolution-smoke"],
            objective="Reduce missing specimen handoff fields before hardware execution.",
        )
    )

    result = svc.run_task(task.task_id, handler_registry=registry)

    assert result["ok"] is True
    variant = svc.read_variant(result["variant"]["variant_id"])
    assert variant.status == "gate_passed"
    assert all(gate.passed for gate in variant.gate_results)
    assert "Self-evolution guidance" in variant.body["module"]["prompt"]["developer"]
    assert "errors: 1" in variant.body["module"]["prompt"]["developer"]

    svc.approve_variant(variant.variant_id, operator="pytest")
    activated = svc.activate_variant(variant.variant_id, operator="pytest")

    assert activated.status == "active_next_run"
    active_yaml = yaml.safe_load((tmp_path / "modules" / "design" / "module.yaml").read_text(encoding="utf-8"))
    assert "Self-evolution guidance" in active_yaml["module"]["prompt"]["developer"]
    assert list((tmp_path / "memory" / "module_versions" / "design").glob("*.yaml"))
    assert svc.lineage("design")["active"]["prompt:design"]["variant_id"] == variant.variant_id


def test_graph_evolution_validates_existing_closed_loop_config_without_route_mutation(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    graph_config = load_graph_config(tmp_path / "graphs" / "atr_closed_loop.yaml")
    registry = _registry_for_handlers(graph_config.handler_ids)
    task = svc.create_task(
        EvolutionTaskCreate(
            target_type="graph",
            target_id="atr_closed_loop",
            source_run_ids=["run-self-evolution-smoke"],
            objective="Add self-evolution metadata while preserving the active closed-loop route.",
        )
    )

    result = svc.run_task(task.task_id, handler_registry=registry)

    assert result["ok"] is True
    variant = svc.read_variant(result["variant"]["variant_id"])
    assert variant.status == "gate_passed"
    assert all(gate.passed for gate in variant.gate_results)
    graph_body = variant.body["graph"]
    assert graph_body["transitions"] == graph_config.model_dump(mode="json")["transitions"]
    assert graph_body["metadata"]["self_evolution_candidate"]["objective"].startswith("Add self-evolution")


def test_registry_rejects_unsafe_task_and_variant_ids(tmp_path: Path) -> None:
    registry = EvolutionRegistry(tmp_path / "evolution")

    with pytest.raises(ValueError):
        registry.read_task("../bad")
    with pytest.raises(ValueError):
        registry.read_variant("bad/id")

def test_prompt_evolution_uses_knowledge_evidence_pack_guidance(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    registry = _registry_for_handlers({"agent.design_agent"})
    run_dir = tmp_path / "runs" / "run-self-evolution-smoke" / "knowledge"
    run_dir.mkdir(parents=True, exist_ok=True)
    pack = {
        "schema_version": "evolution_evidence_pack_v1",
        "pack_id": "evo-pack-test-design",
        "created_by": "knowledge_agent",
        "target_type": "prompt",
        "target_id": "design",
        "priority": 0.92,
        "objective": "Reduce missing design-to-specimen handoff fields.",
        "why_this_target": ["design handoff omitted required manufacturing fields"],
        "supporting_records": {"failure_patterns": ["design-missing-required-fields"]},
        "recommended_changes": ["Emit required fields before handoff: design_candidate, handoff_to_specimen."],
        "constraints": {"require_human_approval": True, "no_live_hardware_execution": True},
        "eval_metrics": {"primary": "contract_validity_delta"},
        "blocked": False,
        "provenance": {"was_generated_by": "knowledge_agent", "used": ["knowledge_report.json"], "was_associated_with": ["design", "knowledge_agent"], "was_derived_from": ["run-self-evolution-smoke"], "artifact_fingerprints": {}},
        "created_at": "2026-05-30T00:00:00+00:00",
    }
    (run_dir / "evolution_evidence_packs.json").write_text(json.dumps([pack]), encoding="utf-8")
    task = svc.create_task(
        EvolutionTaskCreate(
            target_type="prompt",
            target_id="design",
            source_run_ids=["run-self-evolution-smoke"],
            objective="Improve design handoff contract reliability.",
            constraints={"knowledge_evidence_pack_id": "evo-pack-test-design"},
        )
    )

    result = svc.run_task(task.task_id, handler_registry=registry)

    assert result["ok"] is True
    variant = svc.read_variant(result["variant"]["variant_id"])
    guidance = variant.body["module"]["prompt"]["developer"]
    assert "Knowledge evidence packs: 1" in guidance
    assert "Evidence objective: Reduce missing design-to-specimen handoff fields" in guidance
    assert "Recommended change: Emit required fields before handoff" in guidance
    assert variant.metrics["trace_metrics"]["knowledge_evidence_pack_count"] == 1
    assert variant.metrics["replay_eval"]["gate_passed"] == variant.metrics["replay_eval"]["gate_total"]


def test_prompt_evolution_replay_eval_uses_heldout_trace_gate(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    _write_run_trace(svc.run_root, "run-self-evolution-heldout")
    registry = _registry_for_handlers({"agent.design_agent"})
    task = svc.create_task(
        EvolutionTaskCreate(
            target_type="prompt",
            target_id="design",
            source_run_ids=["run-self-evolution-smoke"],
            objective="Improve design handoff robustness against held-out trace failures.",
        )
    )

    result = svc.run_task(task.task_id, handler_registry=registry)

    assert result["ok"] is True
    variant = svc.read_variant(result["variant"]["variant_id"])
    gate_ids = {gate.gate_id for gate in variant.gate_results}
    assert "replay_cases_present" in gate_ids
    assert "replay_contract_completeness" in gate_ids
    assert "replay_groundedness_to_trace" in gate_ids
    assert "replay_safety_preservation" in gate_ids
    assert "replay_no_forbidden_behavior" in gate_ids
    replay = variant.metrics["replay_eval"]
    assert replay["source_trace_count"] == 1
    assert replay["heldout_trace_count"] >= 1
    assert replay["replay_trace_count"] >= 1
    assert replay["gate_passed"] == replay["gate_total"]
    assert variant.status == "gate_passed"
