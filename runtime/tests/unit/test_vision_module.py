"""Vision code ownership and executable routing with synthetic device boundaries."""
import asyncio
from pathlib import Path

import pytest

from agents.execution_graph import ExecutionGraphError, compile_execution_graph
from agents.vision.agent import VisionAgent
from agents.registry import AgentRegistry


def catalog_graph():
    from agents.vision.execution import default_vision_execution_graph
    return VisionAgent().execution_catalog(), default_vision_execution_graph()


def test_discovered_canonical_owner_and_activation(monkeypatch, tmp_path):
    from agents.module_discovery import discover_agent_modules
    modules = {m.module_id: m for m in discover_agent_modules()}
    assert "vision" in modules, "Vision must be a code-discovered owner"
    from agents.vision import agent as owner

    assert owner.VisionAgent is VisionAgent
    monkeypatch.setattr(owner, "__file__", str(tmp_path / "agents/vision/agent.py"))
    assert VisionAgent._repo_root() == tmp_path
    registry = AgentRegistry()
    registry.register_module(modules["vision"])
    assert registry.get_module("vision").factory is VisionAgent
    assert registry.get("vision_agent").__class__ is VisionAgent
    active = {"vision_agent"}
    registry.bind_activation(lambda: active)
    assert registry.get("vision_agent").execution_catalog().module_id == "vision"
    active.clear()
    with pytest.raises(KeyError, match="inactive"):
        registry.get("vision_agent")
    descriptor = modules["vision"].describe()
    assert descriptor["handler"] == "agent.vision_agent"
    assert "camera_vision" in descriptor["dependencies"]["bridge_modules"]


@pytest.mark.parametrize("mutation", ["bypass_prepare", "swap_branch", "stale_terminal"])
def test_invalid_routes_reject_before_tools(mutation):
    catalog, graph = catalog_graph()
    if mutation == "bypass_prepare":
        graph = {"schema": graph["schema"], "entry": "observe", "nodes": [
            {"id": "observe", "handler": "vision.observe", "area": "middle"}],
            "edges": [], "terminals": ["observe"]}
    elif mutation == "swap_branch":
        for edge in graph["edges"]:
            if edge["source"] == "prepare" and edge["on"] == "ready":
                edge["target"] = "clearance"
            elif edge["source"] == "prepare" and edge["on"] == "clearance":
                edge["target"] = "observe"
    else:
        graph["nodes"].append({"id": "stale", "handler": "vision.observe", "area": "middle"})
        graph["edges"].append({"source": "deliver", "target": "stale", "on": "next", "kind": "execution"})
        graph["terminals"] = ["stale" if x == "deliver" else x for x in graph["terminals"]]
    with pytest.raises(ExecutionGraphError):
        compile_execution_graph(graph, catalog)


def context(tmp_path, monkeypatch):
    from tests.unit.test_vision_agent import _CtxStub, _state
    from mcp_tools.mock_tools import register_mock_tools
    from mcp_tools.tool_registry import ToolRegistry
    tools = ToolRegistry()
    register_mock_tools(tools)
    ctx = _CtxStub(tools)
    ctx.artifact_run_root = tmp_path / "runs"
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    return ctx, _state()


@pytest.mark.asyncio
async def test_saved_graph_routes_actual_owner_and_retains_invocation(tmp_path, monkeypatch):
    from agents.vision.execution import execute_vision_graph
    ctx, state = context(tmp_path, monkeypatch)
    _, graph = catalog_graph()
    for node in graph["nodes"]:
        if node["id"] == "observe":
            node["id"] = "saved_observation"
    for edge in graph["edges"]:
        for key in ("source", "target"):
            if edge[key] == "observe":
                edge[key] = "saved_observation"
    events = []
    result = await execute_vision_graph(VisionAgent(), state, ctx, graph=graph, emit=events.append,
        invocation={"run_id": "invocation-run", "loop_index": 9, "invocation_id": "attempt-4"})
    assert result.result.success
    assert result.result.data["observation"]["transfer_readiness"]["ready"] is True
    assert [e["node_id"] for e in result.trace if e["status"] == "completed"] == ["prepare", "saved_observation", "deliver"]
    assert all(e["payload"]["invocation_id"] == "attempt-4" and e["payload"]["loop_index"] == 9 for e in events)
    assert any(e["payload"].get("edge", {}).get("target") == "saved_observation" for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "cancel", "repeat"])
async def test_capture_uncertainty_and_duplicate_observation_never_replay(tmp_path, monkeypatch, failure):
    ctx, state = context(tmp_path, monkeypatch)
    _, graph = catalog_graph()
    ctx.runtime_module_config = lambda: {"id": "vision", "execution_graph": graph}
    calls = []
    original = ctx.tools.call
    def call(name, payload):
        if name == "camera.capture":
            calls.append(name)
            if failure == "exception":
                raise OSError("uncertain capture")
            if failure == "cancel":
                raise asyncio.CancelledError()
        return original(name, payload)
    ctx.tools.call = call
    if failure == "repeat":
        graph["nodes"].append({"id": "repeat", "handler": "vision.observe", "area": "middle"})
        for edge in graph["edges"]:
            if edge["source"] == "observe":
                edge["target"] = "repeat"
        graph["edges"].append({"source": "repeat", "target": "deliver", "on": "next", "kind": "execution"})
    error = {"exception": OSError, "cancel": asyncio.CancelledError, "repeat": ExecutionGraphError}[failure]
    with pytest.raises(error):
        await VisionAgent().run(state, ctx)
    assert calls == ["camera.capture"]


def test_code_relationships_resolve_to_real_sources():
    import ast
    catalog, graph = catalog_graph()
    compile_execution_graph(graph, catalog)
    structure = catalog.describe()["implementation_structure"]
    assert catalog.operation("vision.clearance").llm is True, "Clearance includes bounded visual review"
    areas = set()
    root = Path(__file__).resolve().parents[2]
    for handler, detail in structure["operations"].items():
        catalog.operation(handler)
        ids = {"$operation"} | {node["id"] for node in detail["nodes"]}
        for edge in detail["edges"]:
            assert edge["source"] in ids and edge["target"] in ids
        for node in detail["nodes"]:
            areas.add(node["area"])
            ref = node["source"]
            tree = ast.parse((root / ref["path"]).read_text())
            assert any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                       and item.name == ref["symbol"].split(".")[-1] for item in ast.walk(tree))
    assert areas == {"high", "middle", "low", "guardian", "knowledge"}


@pytest.mark.asyncio
async def test_saved_delivery_edge_is_followed_by_archived_owner(tmp_path, monkeypatch):
    ctx, state = context(tmp_path, monkeypatch)
    _, graph = catalog_graph()
    graph["nodes"].append({"id": "saved_delivery", "handler": "vision.deliver", "area": "high"})
    graph["edges"].append({"source": "deliver", "target": "saved_delivery", "on": "next", "kind": "evidence"})
    graph["terminals"] = ["saved_delivery" if x == "deliver" else x for x in graph["terminals"]]
    ctx.runtime_module_config = lambda: {"id": "vision", "execution_graph": graph}
    events, calls = [], []
    ctx.emit_execution_event = events.append
    original = ctx.tools.call
    def call(name, payload):
        calls.append((name, dict(payload)))
        return original(name, payload)
    ctx.tools.call = call
    result = await VisionAgent().run(state, ctx)
    assert result.success
    assert result.data["artifact_execution"]
    assert [e["payload"]["node_id"] for e in events if e["type"] == "execution.node.completed"] == [
        "prepare", "observe", "deliver", "saved_delivery"]
    assert [name for name, _ in calls] == ["camera.capture"]
    assert calls[0][1]["frame_id"] == "frame-0-vision"
    assert calls[0][1]["specimen_id"] == "specimen-001"


@pytest.mark.asyncio
async def test_prepared_stop_result_uses_its_own_terminal_without_tools(tmp_path, monkeypatch):
    ctx, state = context(tmp_path, monkeypatch)
    state.stop_requested = True
    state.current_experiment_spec["execution_policy"] = {"vision": "preflight_only"}
    events = []
    ctx.emit_execution_event = events.append
    result = await VisionAgent().run(state, ctx)
    assert not result.success
    assert result.data["vision_decision"]["failure_code"] == "VISION_STOP_REQUESTED"
    assert [e["payload"]["node_id"] for e in events if e["type"] == "execution.node.completed"] == ["prepare", "deliver_prepared"]


@pytest.mark.asyncio
async def test_current_clear_precedes_generic_stop_and_keeps_replay_cleanup(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tests.unit.test_utm_clear_cycle import state_with_placement, equipment_data, ReplayTools
    from utils import utm_clear_cycle as cycle
    from orchestrator.state import Stage
    state = state_with_placement()
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    state.run_metadata["utm_clear_execution"].update(state="running")
    state.stop_requested = True
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    events, tools = [], ReplayTools(state)
    result = await VisionAgent().run(state, SimpleNamespace(tools=tools, emit_execution_event=events.append))
    assert not result.success
    assert state.run_metadata["utm_clear_execution"]["failure_code"] == "UTM_CLEAR_OPERATOR_STOPPED"
    assert [name for name, _ in tools.calls] == ["lerobot.replay.stop"]
    assert [e["payload"]["node_id"] for e in events if e["type"] == "execution.node.completed"] == [
        "prepare", "clearance", "deliver_clearance"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "cancel", "repeat"])
async def test_placement_stop_is_not_replayed_after_review_failure(tmp_path, monkeypatch, failure):
    from datetime import datetime, timezone
    from PIL import Image
    from tests.unit.test_vision_decision import Model
    from mcp_tools.tool_registry import ToolRegistry
    ctx, state = context(tmp_path, monkeypatch)
    _, graph = catalog_graph()
    raw, annotated = tmp_path / "raw.png", tmp_path / "annotated.png"
    Image.new("RGB", (32, 24), "red").save(raw)
    Image.new("RGB", (32, 24), "green").save(annotated)
    interlock = {"session_id": "rollout", "ungrasping_seen": True,
                 "home_after_ungrasping": True, "ready_for_utm_snapshot": True}
    state.run_metadata["manipulation_result"] = {"ok": True, "session_id": "rollout", "workflow": "rollout",
        "action_count": 30, "runtime_phase": "ACTION_ACTIVE", "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete", "post_place_interlock": interlock}
    state.run_metadata["robot_task_result"] = {"rollout_session_id": "rollout", "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete", "post_place_interlock": interlock}
    order, tools = [], ToolRegistry()
    tools.register("vision.utm_specimen_presence.capture", lambda payload: order.append("capture") or {
        "ok": True, "detected": True, "frame_id": "f1", "specimen_id": "specimen-001",
        "timestamp": datetime.now(timezone.utc).isoformat(), "bbox_xyxy": [1, 2, 20, 21],
        "raw_frame_path": str(raw), "annotated_frame_path": str(annotated),
        "session_id": "rollout", "source": "utm_ros_frame", "confidence": .8, "width": 32, "height": 24})
    tools.register("lerobot.rollout.stop", lambda payload: order.append("stop") or
        {"ok": True, "status": "STOPPED", "session_id": "rollout"})
    def review():
        order.append("review")
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "exception":
            raise RuntimeError("provider failed after stop")
    model = Model("return_to_owner", change=review)
    model.tools = tools
    model.runtime_module_config = lambda: {"id": "vision", "execution_graph": graph}
    if failure == "repeat":
        graph["nodes"].append({"id": "repeat", "handler": "vision.observe", "area": "middle"})
        for edge in graph["edges"]:
            if edge["source"] == "observe":
                edge["target"] = "repeat"
        graph["edges"].append({"source": "repeat", "target": "deliver", "on": "next", "kind": "execution"})
    if failure == "exception":
        result = await VisionAgent().run(state, model)
        assert not result.success
    else:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else ExecutionGraphError):
            await VisionAgent().run(state, model)
    assert order == ["capture", "stop", "review"]
