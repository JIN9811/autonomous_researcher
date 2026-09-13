"""Specimen owner discovery, graph admission and offline execution contracts."""
from pathlib import Path

import pytest

from agents.registry import AgentRegistry
from agents.specimen_agent import SpecimenMakingAgent
from agents.execution_graph import ExecutionGraphError, compile_execution_graph
from orchestrator.state import Mode, OrchestratorState, Stage


def test_discovered_specimen_preserves_compatibility_and_activation():
    from agents.module_discovery import discover_agent_modules
    modules = {module.module_id: module for module in discover_agent_modules()}
    assert "specimen" in modules, "Specimen must be a discovered code owner"
    from agents.specimen.agent import SpecimenMakingAgent as Owner
    from agents.specimen.decision import decide_specimen
    from agents.specimen_decision import decide_specimen as legacy_decide
    assert Owner is SpecimenMakingAgent and legacy_decide is decide_specimen
    registry = AgentRegistry()
    registry.register_module(modules["specimen"])
    agent = registry.get("specimen_agent")
    active = {"specimen_agent"}
    registry.bind_activation(lambda: active)
    active.clear()
    with pytest.raises(KeyError, match="inactive"):
        registry.get("specimen_agent")
    assert registry.get_installed("specimen_agent") is agent
    assert registry.get_module("specimen").describe()["handler"] == "agent.specimen_agent"
    assert agent.execution_catalog().module_id == "specimen"


def catalog_and_graph():
    from agents.specimen.execution import default_specimen_execution_graph, specimen_execution_catalog
    return specimen_execution_catalog(SpecimenMakingAgent()), default_specimen_execution_graph()


@pytest.mark.parametrize("mutation", ["skip_prepare", "swap_outcomes", "stale_terminal"])
def test_graph_rejects_missing_producer_wrong_outcome_and_stale_result(mutation):
    catalog, graph = catalog_and_graph()
    if mutation == "skip_prepare":
        graph = {"schema": graph["schema"], "entry": "finalize",
                 "nodes": [{"id": "finalize", "handler": "specimen.finalize", "area": "middle"}],
                 "edges": [], "terminals": ["finalize"]}
    elif mutation == "swap_outcomes":
        for edge in graph["edges"]:
            if edge["source"] == "decide":
                edge["target"] = "review" if edge["on"] == "executed" else "finalize"
    else:
        graph["terminals"].remove("finalize")
        graph["terminals"].append("late_decision")
        graph["nodes"].append({"id": "late_decision", "handler": "specimen.decide", "area": "middle"})
        graph["edges"].append({"source": "finalize", "target": "late_decision", "on": "next", "kind": "execution"})
    with pytest.raises(ExecutionGraphError, match="required input|terminal.*agent_result"):
        compile_execution_graph(graph, catalog)


def test_projection_preserves_nested_report_precedence_and_metrics():
    from agents.specimen.presentation import project_specimen_report
    report = {"digital_thread": {"specimen_id": "nested-current"}, "quality_gates": [{"status": "blocked"}]}
    result = project_specimen_report(
        {"specimen_result": {"fabrication_report": report}, "specimen_metrics": {"quality": 0}},
        {"fabrication_report": {"digital_thread": {"specimen_id": "stale"}},
         "specimen_agent_report": {"status": "blocked"}, "specimen_fabricated": {"decisions": [{"status": "blocked"}]}})
    assert result["fabrication_report"] == report
    assert result["role_specific"]["digital_thread"] == {"specimen_id": "nested-current"}
    assert result["specimen_agent_report"] == {"status": "blocked"}
    assert result["metrics"] == {"quality": 0}
    assert result["decisions"] == [{"status": "blocked"}]


@pytest.mark.asyncio
async def test_owner_uses_invocation_graph_and_never_replays_successful_fabrication(tmp_path, monkeypatch):
    from tests.unit.test_specimen_agent import _CtxStub, _valid_spec
    catalog, graph = catalog_and_graph()
    ctx = _CtxStub()
    ctx.artifact_run_root = tmp_path / "runs"
    ctx.force_real_llm_in_test = False
    ctx.runtime_module_config = lambda: {"id": "specimen", "execution_graph": graph}
    events = []
    ctx.emit_execution_event = events.append
    calls = []
    original = ctx.tools.call
    def call(name, payload):
        calls.append(name)
        return original(name, payload)
    ctx.tools.call = call
    monkeypatch.setattr(SpecimenMakingAgent, "_artifact_dir", lambda *args: tmp_path / "geometry")
    state = OrchestratorState(run_id="specimen-module", experiment_id="offline", mode=Mode.TEST,
                              stage=Stage.SPECIMEN, current_experiment_spec={**_valid_spec(), "tpms_resolution": 18})
    # A saved graph can route through two result projections, but fabricates only once.
    graph["nodes"].append({"id": "report_again", "handler": "specimen.finalize", "area": "knowledge"})
    graph["edges"].append({"source": "finalize", "target": "report_again", "on": "next", "kind": "evidence"})
    graph["terminals"] = ["report_again" if item == "finalize" else item for item in graph["terminals"]]
    result = await SpecimenMakingAgent().run(state, ctx)
    assert result.success
    assert result.data["specimen_result"]["candidate_id"] == "cand-1-01"
    assert calls == ["geometry.generate_metamaterial_stl", "geometry.check_mesh_quality",
                     "geometry.check_manufacturability", "artifact.create_specimen_handoff", "experiment.evaluate", "printer.prepare"]
    completed = [event["payload"]["node_id"] for event in events if event["type"] == "execution.node.completed"]
    assert completed == ["prepare", "decide", "finalize", "report_again"]
    assert result.data["artifact_execution"]


def test_specimen_code_relationships_resolve_to_real_owner_symbols():
    import ast
    catalog, graph = catalog_and_graph()
    compile_execution_graph(graph, catalog)
    structure = catalog.describe()["implementation_structure"]
    assert structure and structure["operations"]
    root = Path(__file__).resolve().parents[2]
    for handler, detail in structure["operations"].items():
        catalog.operation(handler)
        ids = {"$operation"} | {node["id"] for node in detail["nodes"]}
        for edge in detail["edges"]:
            assert edge["source"] in ids and edge["target"] in ids
        for node in detail["nodes"]:
            ref = node["source"]
            tree = ast.parse((root / ref["path"]).read_text())
            assert any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                       and item.name == ref["symbol"].split(".")[-1] for item in ast.walk(tree))


def test_owner_move_preserves_geometry_artifact_root(tmp_path, monkeypatch):
    from agents.specimen import agent as owner
    monkeypatch.setattr(owner, "__file__", str(tmp_path / "agents/specimen/agent.py"))
    state = OrchestratorState(run_id="root-check", experiment_id="offline", mode=Mode.TEST, stage=Stage.SPECIMEN)
    directory = SpecimenMakingAgent._artifact_dir(state, "specimen-path")
    assert directory.is_relative_to(tmp_path / "runs"), "Owner relocation must not move run artifacts under agents/"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "cancel", "duplicate_decision"])
async def test_uncertain_or_repeated_fabrication_never_replays_and_is_archived(tmp_path, monkeypatch, failure):
    import asyncio
    from tests.unit.test_specimen_agent import _CtxStub, _valid_spec
    from utils.agent_artifact_archive import list_executions

    ctx = _CtxStub()
    ctx.artifact_run_root = tmp_path / "runs"
    ctx.force_real_llm_in_test = False
    _, graph = catalog_and_graph()
    ctx.runtime_module_config = lambda: {"id": "specimen", "execution_graph": graph}
    state = OrchestratorState(run_id="no-replay", experiment_id="offline", mode=Mode.TEST, stage=Stage.SPECIMEN,
                              current_experiment_spec={**_valid_spec(), "tpms_resolution": 18})
    monkeypatch.setattr(SpecimenMakingAgent, "_artifact_dir", lambda *args: tmp_path / "geometry")
    calls = []
    original = ctx.tools.call
    def call(name, payload):
        if name == "experiment.evaluate":
            calls.append(name)
            if failure == "exception":
                raise OSError("uncertain effect")
            if failure == "cancel":
                raise asyncio.CancelledError()
        return original(name, payload)
    ctx.tools.call = call
    if failure == "duplicate_decision":
        graph["nodes"].append({"id": "repeat_decision", "handler": "specimen.decide", "area": "middle"})
        for edge in graph["edges"]:
            if edge["source"] == "decide" and edge["on"] == "executed":
                edge["target"] = "repeat_decision"
        graph["edges"].extend([
            {"source": "repeat_decision", "target": "finalize", "on": "executed", "kind": "execution"},
            {"source": "repeat_decision", "target": "review", "on": "blocked", "kind": "validation"},
        ])
    error = {"exception": OSError, "cancel": asyncio.CancelledError, "duplicate_decision": ExecutionGraphError}[failure]
    with pytest.raises(error):
        await SpecimenMakingAgent().run(state, ctx)
    assert calls == ["experiment.evaluate"]
    entries = list_executions(tmp_path / "runs/no-replay")
    assert len(entries) == 1
    assert entries[0]["status"] == ("cancelled" if failure == "cancel" else "failed")


@pytest.mark.asyncio
async def test_deterministic_specimen_matches_complete_result_state_and_tool_payload_golden(tmp_path, monkeypatch):
    """Catch changed result fields, owner side effects, or any fabrication tool argument.

    The checked-in synthetic baseline is data from the pre-migration owner.
    This test never reads Git history, duplicates an old owner, or rewrites it.
    """
    from copy import deepcopy
    from dataclasses import asdict
    from datetime import datetime, timezone
    import json
    from types import SimpleNamespace
    from agents.specimen import agent as owner

    golden_path = Path(__file__).parents[1] / "fixtures/specimen_module_deterministic_golden.json"
    # Only the explicitly marked artifact root is replaced; no output fields are ignored.
    fixture = json.loads(golden_path.read_text().replace("$ARTIFACT_ROOT", str(tmp_path / "geometry")))
    calls = []

    class SyntheticTools:
        def call(self, name, payload):
            calls.append({"tool": name, "payload": deepcopy(payload)})
            return deepcopy(fixture["tool_responses"][name])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 13, tzinfo=timezone.utc)

    monkeypatch.setattr(owner, "datetime", Clock)
    monkeypatch.setattr("agents.knowledge_context.uuid4", lambda: SimpleNamespace(hex="synthetic-request"))
    monkeypatch.setattr(SpecimenMakingAgent, "_artifact_dir", lambda *args: tmp_path / "geometry")
    state = OrchestratorState(**fixture["state_input"])
    before = state.model_dump(mode="json")
    ctx = SimpleNamespace(tools=SyntheticTools(), force_real_llm_in_test=False)

    result = await SpecimenMakingAgent().run(state, ctx)

    assert calls == fixture["expected_tool_calls"]
    assert asdict(result) == fixture["expected_result"]
    after = state.model_dump(mode="json")
    changed = {key: value for key, value in after.items() if value != before[key]}
    assert changed == fixture["expected_state_changes"]
    assert after.keys() == before.keys()
