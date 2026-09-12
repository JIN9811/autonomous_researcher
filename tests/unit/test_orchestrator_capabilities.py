"""Owner discovery never promotes overlays or executes an owner to inspect it."""
from copy import deepcopy
from types import SimpleNamespace
import time
import socket
import subprocess

import pytest
import yaml

from agents import orchestrator_capabilities as capabilities
from agents.bo_agent import BOAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.registry import AgentRegistry
from graphs.schema import GraphConfig, GraphNode, load_graph_config
from orchestrator.state import OrchestratorState, Stage


@pytest.fixture(autouse=True)
def block_external_effects(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("External network/process execution is forbidden in owner setup tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)


def state():
    return OrchestratorState(run_id="setup", experiment_id="exp")


def test_expired_and_missing_evidence_are_unknown():
    report = {"status": "ready", "observed_at": 10., "expires_at": 11.,
              "owner": "vision_agent", "capability": "inspect", "evidence_refs": ["frame-a"]}
    assert capabilities.availability_view(report, 12)["status"] == "unknown"
    assert report["status"] == "ready"
    assert capabilities.availability_view(report, 10.5)["status"] == "ready"
    for field in ("observed_at", "expires_at", "evidence_refs"):
        missing = deepcopy(report)
        missing.pop(field)
        assert capabilities.availability_view(missing, 10.5)["status"] == "unknown"


@pytest.mark.parametrize("padding", ["", "  "])
def test_discovery_tracks_graph_module_handler_and_pins_snapshot(tmp_path, padding):
    module = tmp_path / "modules" / "example"
    module.mkdir(parents=True)
    path = module / "module.yaml"
    path.write_text(yaml.safe_dump({"module": {"id": "example", "handler": f"{padding}agent.bo_agent{padding}",
        "orchestration_contract": {"version": "1", "admission": {}, "result": {}, "acceptance": {}},
        "pre_execution": [{"id": "plan", "handler": f"{padding}agent.orchestrator_agent{padding}"}]}}))
    graph = GraphConfig(id="x", name="x", entry_node="first", stage_dispatch={"bo": "first"}, nodes=[
        GraphNode(id="first", label="First", handler="agent.wrong", stage="bo", module_id="modules/example"),
        GraphNode(id="overlay", label="Overlay", handler="agent.bo_agent", module_id="modules/example", kind="sidecar")])
    registry = AgentRegistry()
    registry.register(BOAgent())
    registry.register(OrchestratorAgent())
    registry.register(SimpleNamespace(name="unused"))
    catalog = capabilities.OwnerCatalog(registry, graph, graph_root=tmp_path)
    rows = catalog.describe(state(), None)
    assert [(r["owner"], r["role"]) for r in rows] == [
        ("bo_agent", "stage_dispatch"), ("orchestrator_agent", "pre_execution"), ("bo_agent", "overlay")]
    assert rows[-1]["executable"] is False
    pinned = catalog.snapshot()
    graph.nodes.pop()
    payload = yaml.safe_load(path.read_text())
    payload["module"]["orchestration_contract"]["version"] = "2"
    path.write_text(yaml.safe_dump(payload))
    assert len(catalog.describe(state(), None)) == 2
    assert catalog.describe(state(), None)[0]["contract_version"] == "2"
    assert len(pinned.describe(state(), None)) == 3
    assert pinned.describe(state(), None)[0]["contract_version"] == "1"
    graph.nodes.append(GraphNode(id="new", label="New", handler="agent.new_owner"))
    assert catalog.describe(state(), None)[-1]["owner"] == "new_owner"
    with pytest.raises(ValueError):
        catalog.validate("unused", {}, state())


@pytest.mark.asyncio
async def test_missing_owner_and_cached_old_success_do_not_imply_ready():
    graph = GraphConfig(id="x", name="x", entry_node="v", nodes=[GraphNode(id="v", label="v", handler="agent.missing")])
    catalog = capabilities.OwnerCatalog(AgentRegistry(), graph)
    assert catalog.describe(state(), None)[0]["availability"]["status"] == "unknown"
    assert (await catalog.inspect("missing", "inspect", state(), None))["status"] == "unknown"
    with pytest.raises(ValueError):
        await catalog.apply("missing", {}, state(), "r")


def test_main_graph_contracts_keep_optional_results_optional():
    catalog = capabilities.OwnerCatalog(AgentRegistry(), load_graph_config("graphs/configs/atr_closed_loop.yaml"))
    rows = catalog.describe(state(), None)
    by_node = {row["node_id"]: row for row in rows}
    assert by_node["vision"]["contract"]["result"]["required"] == ["observation"]
    assert by_node["specimen"]["contract"]["result"]["required"] == []
    assert by_node["orchestrator_supervisor"]["role"] == "overlay"
    assert any(row["owner"] == "orchestrator_agent" and row["role"] == "pre_execution" for row in rows)


@pytest.mark.parametrize("changes", [
    {"acquisition": "invalid"}, {"parameter_space": {"cell_size_mm": [-1, 8]}},
    {"parameter_space": {"cell_size_mm": [8, 5]}}, {"parameter_space": {"cell_size_mm": [float("nan")]}},
    {"parameter_space": {"cell_size_mm": ["5 cm", 8]}}, {"parameter_space": {"cell_size_cm": [1, 2]}},
    {"parameter_space": {"relative_density": [.8]}}, {"budget": 9},
])
def test_bo_setup_rejects_invalid_inputs(changes):
    with pytest.raises(ValueError):
        BOAgent().validate_setup(changes, state())


@pytest.mark.asyncio
async def test_setup_is_consumed_by_real_initial_design_and_run(monkeypatch):
    owner = BOAgent()
    fresh = state()
    prior = {"constraints": {"cell_size_mm": 99}}
    fresh.run_metadata["next_design_request"] = deepcopy(prior)
    changes = {"parameter_space": {"cell_size_mm": [6, 7], "relative_density": [.25, .30]},
               "acquisition": "upper_confidence_bound"}
    owner.apply_setup(changes, fresh, "request")
    assert owner.read_setup(fresh)["acquisition"] == "upper_confidence_bound"
    initial = owner.initial_design_request(fresh)
    assert initial["parameter_space"]["cell_size_mm"] == [6, 7]
    assert all(6 <= point["parameters"]["cell_size_mm"] <= 7 for point in initial["points"])
    assert fresh.run_metadata["next_design_request"] == prior
    async def consume(state, ctx, settings):
        return settings
    monkeypatch.setattr(owner, "run_with_settings", consume)
    consumed = await owner.run(fresh, SimpleNamespace())
    assert consumed["acquisition"] == "upper_confidence_bound"
    assert consumed["parameter_space"]["cell_size_mm"] == [6, 7]
    fresh.stage = Stage.BO
    with pytest.raises(ValueError):
        owner.apply_setup(changes, fresh, "later")


def test_orchestrator_setup_updates_actual_goal_without_other_writes():
    owner = OrchestratorAgent()
    fresh = state()
    owner.apply_setup({"active_goal": "  Optimize gyroid  "}, fresh, "request")
    assert fresh.active_goal == "Optimize gyroid"
    assert owner.read_setup(fresh) == {"active_goal": "Optimize gyroid"}
    with pytest.raises(ValueError):
        owner.validate_setup({"device": "printer"}, fresh)


@pytest.mark.asyncio
async def test_inspect_requires_fresh_same_run_evidence_and_never_runs_owner():
    class PassiveOwner:
        name = "vision_agent"

        async def run(self, *args):
            pytest.fail("Availability must never run the owner")

    registry = AgentRegistry()
    registry.register(PassiveOwner())
    catalog = capabilities.OwnerCatalog(registry, load_graph_config("graphs/configs/atr_closed_loop.yaml"))
    fresh = state()
    now = time.time()
    report = {"owner": "vision_agent", "capability": "inspect", "status": "ready",
              "run_id": fresh.run_id, "observed_at": now - 1, "expires_at": now + 60, "evidence_refs": ["frame"]}
    fresh.run_metadata["availability_reports"] = {"vision_agent": {"inspect": report}}
    assert (await catalog.inspect("vision_agent", "inspect", fresh, None))["status"] == "ready"
    for key, value in (("run_id", "another-run"), ("observed_at", None), ("observed_at", float("nan")), ("owner", "wrong")):
        fresh.run_metadata["availability_reports"]["vision_agent"]["inspect"] = {**report, key: value}
        assert (await catalog.inspect("vision_agent", "inspect", fresh, None))["status"] == "unknown"
    with pytest.raises(ValueError):
        catalog.readback("vision_agent", fresh)


@pytest.mark.asyncio
async def test_catalog_delegates_setup_and_reports_normalization():
    registry = AgentRegistry()
    registry.register(BOAgent())
    registry.register(OrchestratorAgent())
    catalog = capabilities.OwnerCatalog(registry, load_graph_config("graphs/configs/atr_closed_loop.yaml"))
    fresh = state()
    validation = catalog.validate("bo_agent", {"parameter_space": {"relative_density": [.1, .4]}}, fresh)
    assert validation["requires_confirmation"] is True
    assert validation["values"]["parameter_space"]["relative_density"] == [.2, .4]
    await catalog.apply("bo_agent", {"acquisition": "exploration"}, fresh, "request")
    assert catalog.readback("bo_agent", fresh)["acquisition"] == "exploration"
    row = next(row for row in catalog.describe(fresh, None) if row["owner"] == "orchestrator_agent")
    assert row["setup"]["fields"][0]["id"] == "research.goal"
    assert row["setup"]["fields"][0]["field"] == "active_goal"


@pytest.mark.parametrize("report", [
    {"status": []}, {"status": {"ready": True}},
])
def test_malformed_availability_status_is_unknown(report):
    report.update(owner="owner", capability="inspect", observed_at=1, expires_at=3, evidence_refs=["e"])
    assert capabilities.availability_view(report, 2)["status"] == "unknown"
