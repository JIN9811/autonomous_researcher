"""Installed Manipulation consumers exercise the owner with controlled I/O only."""
import ast
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_external_effects():
    from scripts.orchestrator_verification_guard import VerificationGuard
    with VerificationGuard() as guard:
        yield guard
        assert guard.physical_call_count == 0
        assert guard.denied == []


def test_discovery_registers_canonical_active_owner():
    from agents.manipulation.agent import ManipulationAgent
    from agents.module_discovery import discover_agent_modules
    from agents.registry import AgentRegistry
    owners = {m.module_id: m for m in discover_agent_modules()}
    assert "manipulation" in owners
    module = owners["manipulation"]
    registry = AgentRegistry()
    registry.register_module(module)
    assert registry.get_module("manipulation").factory is ManipulationAgent
    assert registry.get("manipulation_agent").__class__ is ManipulationAgent
    active = {"manipulation_agent"}
    registry.bind_activation(lambda: active)
    assert registry.get("manipulation_agent").execution_catalog().module_id == "manipulation"
    active.clear()
    with pytest.raises(KeyError, match="inactive"):
        registry.get("manipulation_agent")


def test_report_metadata_precedence_and_isolation():
    from agents.manipulation.presentation import project_manipulation_report
    metadata = {"manipulation_report": {"task": {"task_id": "transfer_to_utm"}},
        "latest_manipulation_agent_report": {"status": "running"},
        "robot_task_result": {"handoff_status": "needs_post_place_vision", "decisions": []},
        "manipulation_metrics": {"actions": 0}}
    payload = {"manipulation_report": {"task": {"task_id": "old"}}, "decisions": [{"old": True}],
        "metrics": {"actions": 9}, "manipulation_agent_report": {"status": "old"}}
    before = deepcopy((metadata, payload))
    result = project_manipulation_report(metadata, payload)
    assert result["role_specific"]["task"] == {"task_id": "transfer_to_utm"}
    assert result["manipulation_agent_report"] == {"status": "running"}
    assert result["metrics"] == {"actions": 0}
    assert result["decisions"] == []
    assert (metadata, payload) == before
    fallback = project_manipulation_report({}, payload)
    assert fallback["role_specific"]["task"] == {"task_id": "old"}
    assert fallback["decisions"] == [{"old": True}]


def test_executable_contract_and_source_symbols():
    from agents.manipulation.agent import ManipulationAgent
    from agents.manipulation.execution import default_manipulation_execution_graph
    from agents.execution_graph import compile_execution_graph
    catalog = ManipulationAgent().execution_catalog()
    compile_execution_graph(default_manipulation_execution_graph(), catalog)
    assert {op.handler for op in catalog.operations} == {"manipulation.task", "manipulation.deliver"}
    assert catalog.operation("manipulation.task").llm is True
    areas = set()
    for detail in catalog.describe()["implementation_structure"]["operations"].values():
        ids = {"$operation"} | {node["id"] for node in detail["nodes"]}
        for edge in detail["edges"]:
            assert edge["source"] in ids and edge["target"] in ids
        for node in detail["nodes"]:
            areas.add(node["area"])
            source = node["source"]
            tree = ast.parse(Path(source["path"]).read_text())
            assert any(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and x.name == source["symbol"].split(".")[-1] for x in ast.walk(tree))
    assert areas == {"high", "middle", "low", "guardian", "knowledge"}


class BoundaryTools:
    def __init__(self):
        self.calls = []

    def list_tools(self):
        return ["lerobot.rollout.start", "lerobot.rollout.status", "lerobot.rollout.stop"]

    def call(self, name, payload):
        assert name in self.list_tools()
        recorded = deepcopy(payload)
        callback = recorded.pop("_event_callback", None)
        if callback is not None:
            callback({"type": "fixture", "session_id": payload["session_id"]})
        self.calls.append((name, recorded))
        return {"ok": True, "tool": name, "workflow": "rollout",
            "status": "STOPPED" if name == "lerobot.rollout.stop" else "POLICY_ACTIVE",
            "session_id": payload["session_id"], "runtime_phase": "ACTION_ACTIVE", "action_count": 30,
            "stop_confirmed": name == "lerobot.rollout.stop",
            "post_place_interlock": {"session_id": payload["session_id"], "ungrasping_seen": True,
                "home_after_ungrasping": True, "ready_for_utm_snapshot": True}}


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["running", "preflight", "blocked", "clear_without_handoff", "duplicate_start", "completed_recovery"])
async def test_graph_preserves_original_body(branch, tmp_path, monkeypatch):
    from agents.manipulation.agent import ManipulationAgent
    from agents.manipulation.execution import execute_manipulation_graph
    from tests.unit.test_manipulation_lerobot_agent import _state, _CtxStub, _isolate_manipulation_profile
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    state = _state()
    if branch == "completed_recovery":
        from tests.unit.test_manipulation_lerobot_agent import _post_specimen_completion_state
        state = _post_specimen_completion_state()
    if branch == "preflight":
        state.current_experiment_spec["execution_policy"] = {"manipulation": "preflight_only"}
    elif branch == "blocked":
        state.latest_observations["anomaly"] = True
    elif branch == "clear_without_handoff":
        state.current_experiment_spec["task_id"] = "clear_utm_to_disposal"
    elif branch == "duplicate_start":
        first = await ManipulationAgent()._run_task(state, _CtxStub(BoundaryTools()))
        assert first.success
    other = deepcopy(state)
    left, right = _CtxStub(BoundaryTools()), _CtxStub(BoundaryTools())
    monkeypatch.setattr(ManipulationAgent, "_now_iso", staticmethod(lambda: "2026-09-13T00:00:00+00:00"))
    original = await ManipulationAgent()._run_task(state, left)
    executed = await execute_manipulation_graph(ManipulationAgent(), other, right)
    # Independent calls mint Knowledge request IDs; compare the full result except that UUID.
    for result in (original, executed.result):
        for key in ("manipulation_decision", "manipulation_result_decision"):
            result.data.get(key, {}).get("knowledge_delivery", {}).pop("request_id", None)
    assert executed.result == original
    assert right.tools.calls == left.tools.calls
    assert right.events == left.events
    assert [x["node_id"] for x in executed.trace if x["status"] == "completed"] == ["task", "deliver"]
    if branch == "completed_recovery":
        assert [name for name, _ in right.tools.calls] == ["lerobot.rollout.status", "lerobot.rollout.stop"]
        assert executed.result.data["robot_task_result"]["handoff_status"] == "ready_for_equipment"
    elif branch != "running":
        assert right.tools.calls == []


@pytest.mark.asyncio
async def test_duplicate_graph_task_rejects_before_second_device_start(tmp_path, monkeypatch):
    from agents.manipulation.agent import ManipulationAgent
    from agents.manipulation.execution import default_manipulation_execution_graph, execute_manipulation_graph
    from agents.execution_graph import ExecutionGraphError
    from tests.unit.test_manipulation_lerobot_agent import _state, _CtxStub, _isolate_manipulation_profile
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    graph = default_manipulation_execution_graph()
    graph["nodes"].append({"id": "repeat", "handler": "manipulation.task", "area": "middle"})
    graph["edges"] = [{"source": "task", "target": "repeat", "on": "next", "kind": "execution"},
        {"source": "repeat", "target": "deliver", "on": "next", "kind": "evidence"}]
    ctx = _CtxStub(BoundaryTools())
    with pytest.raises(ExecutionGraphError, match="cannot repeat"):
        await execute_manipulation_graph(ManipulationAgent(), _state(), ctx, graph=graph)
    assert [name for name, _ in ctx.tools.calls] == ["lerobot.rollout.start"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["unknown", "no_task", "no_delivery"])
async def test_invalid_graph_fails_before_effects(mutation):
    from agents.manipulation.agent import ManipulationAgent
    from agents.manipulation.execution import default_manipulation_execution_graph, execute_manipulation_graph
    from agents.execution_graph import ExecutionGraphError
    from tests.unit.test_manipulation_lerobot_agent import _state, _CtxStub
    graph = default_manipulation_execution_graph()
    if mutation == "unknown":
        graph["nodes"][0]["handler"] = "python.arbitrary"
    else:
        remaining = "deliver" if mutation == "no_task" else "task"
        graph.update(entry=remaining, nodes=[node for node in graph["nodes"] if node["id"] == remaining],
            edges=[], terminals=[remaining])
    ctx = _CtxStub(BoundaryTools())
    with pytest.raises(ExecutionGraphError):
        await execute_manipulation_graph(ManipulationAgent(), _state(), ctx, graph=graph)
    assert ctx.tools.calls == []


@pytest.mark.asyncio
async def test_clear_dispatch_keeps_first_branch_and_operator_stop_result(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agents.manipulation.agent import ManipulationAgent
    from agents.manipulation.execution import execute_manipulation_graph
    from tests.unit.test_utm_clear_cycle import state_with_placement, equipment_data, ReplayTools
    from tests.unit.test_manipulation_lerobot_agent import _isolate_manipulation_profile
    from utils import utm_clear_cycle as cycle
    from orchestrator.state import Stage
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    state = state_with_placement()
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    state.run_metadata["utm_clear_execution"].update(state="running")
    state.stop_requested = True
    other = deepcopy(state)
    left, right = ReplayTools(state), ReplayTools(other)
    original = await ManipulationAgent()._run_task(state, SimpleNamespace(tools=left))
    executed = await execute_manipulation_graph(ManipulationAgent(), other, SimpleNamespace(tools=right))
    assert executed.result == original
    assert not executed.result.success
    assert other.run_metadata["utm_clear_execution"]["failure_code"] == "UTM_CLEAR_OPERATOR_STOPPED"
    assert right.calls == left.calls
    assert right.calls == []


@pytest.mark.asyncio
async def test_delivery_rejects_non_owner_result():
    from agents.base_agent import AgentResult
    from agents.manipulation.agent import ManipulationAgent
    from agents.execution_graph import ExecutionGraphError
    delivery = ManipulationAgent().execution_catalog().operation("manipulation.deliver")
    with pytest.raises(ExecutionGraphError, match="owner AgentResult"):
        await delivery.operation(None, None, {"task_result": {"success": True}}, {})
    result = AgentResult(success=False, summary="Original blocked result")
    delivered = await delivery.operation(None, None, {"task_result": result}, {})
    assert delivered.outputs["agent_result"] is result


@pytest.mark.asyncio
async def test_execution_pins_definition_and_invocation_during_device_await(tmp_path, monkeypatch):
    from agents.manipulation.agent import ManipulationAgent
    from agents.manipulation.execution import default_manipulation_execution_graph, execute_manipulation_graph
    from tests.unit.test_manipulation_lerobot_agent import _state, _CtxStub, _isolate_manipulation_profile
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    graph = default_manipulation_execution_graph()
    invocation = {"run_id": "pinned-run", "loop_index": 7, "invocation_id": "pinned-attempt"}
    class MutatingBoundary(BoundaryTools):
        def call(self, name, payload):
            graph["nodes"][1]["handler"] = "python.arbitrary"
            invocation["invocation_id"] = "changed-after-start"
            return super().call(name, payload)
    events = []
    result = await execute_manipulation_graph(ManipulationAgent(), _state(), _CtxStub(MutatingBoundary()),
        graph=graph, invocation=invocation, emit=events.append)
    assert result.result.success
    assert [event["node_id"] for event in result.trace if event["status"] == "completed"] == ["task", "deliver"]
    assert all(event["payload"]["invocation_id"] == "pinned-attempt" for event in events)
    assert all(event["payload"]["loop_index"] == 7 for event in events)
    assert all(event["payload"]["graph_revision"] == result.graph_revision for event in events)
