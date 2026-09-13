"""Installed Equipment consumers exercise the owner with controlled I/O only."""
from __future__ import annotations

import ast
from copy import deepcopy
import importlib
from pathlib import Path
from uuid import UUID

import pytest


@pytest.fixture(autouse=True)
def no_external_effects():
    from scripts.orchestrator_verification_guard import VerificationGuard

    with VerificationGuard() as guard:
        yield guard
        assert guard.physical_call_count == 0
        assert guard.denied == []


def test_equipment_identity_and_discovery(monkeypatch):
    from agents.module_discovery import discover_agent_modules
    from agents.registry import AgentRegistry

    owners = {module.module_id: module for module in discover_agent_modules()}
    assert "equipment" in owners
    owner = importlib.import_module("agents.equipment.agent")
    decision = importlib.import_module("agents.equipment.decision")
    workflow = importlib.import_module("agents.equipment.workflow")
    assert importlib.import_module("agents.equipment_agent") is owner
    assert importlib.import_module("agents.equipment_decision") is decision
    assert importlib.import_module("agents.equipment_workflow") is workflow
    monkeypatch.setattr(owner, "_identity_probe", "shared-owner", raising=False)
    assert importlib.import_module("agents.equipment_agent")._identity_probe == "shared-owner"

    module = owners["equipment"]
    assert (module.agent_name, module.version) == ("equipment_agent", "1.0.0")
    registry = AgentRegistry()
    registry.register_module(module)
    assert registry.get("equipment_agent").execution_catalog().module_id == "equipment"


def test_equipment_repository_paths_and_module_ownership_stay_local():
    from agents.equipment.agent import LabEquipmentAgent
    from agents.equipment.module import MODULE

    root = Path(__file__).resolve().parents[2]
    assert LabEquipmentAgent._RUNTIME_ROOT == root / "memory" / "equipment_runtime"
    assert LabEquipmentAgent._SKILL_FLOW_PATH == root / "graphs" / "modules" / "equipment" / "equipment_skill_flows.json"
    assert LabEquipmentAgent._WORKSPACE_SETTINGS_PATH == root / "memory" / "equipment_workspace_settings.json"
    descriptor = MODULE.describe()
    assert descriptor["backend"] == {
        "entrypoint": "agents/equipment/agent.py",
        "decision": "agents/equipment/decision.py",
        "workflow": "agents/equipment/workflow.py",
        "execution": "agents/equipment/execution.py",
        "presentation": "agents/equipment/presentation.py",
        "compatibility_imports": [
            "agents.equipment_agent",
            "agents.equipment_decision",
            "agents.equipment_workflow",
        ],
    }
    assert descriptor["configuration"]["source"] == "graphs/modules/equipment/module.yaml"
    assert descriptor["storage"]["new_settings_store"] is False
    for key in ("documentation",):
        assert (root / descriptor[key]).is_file()


def test_equipment_report_metadata_precedence_keys_and_isolation():
    from agents.equipment.presentation import project_equipment_report

    report = {
        "bridge": {"provider": "windows_pyautogui", "connection_status": "ready"},
        "control_plan": {"program_id": "utm_cycle", "macro_version": "1.0.7", "locator_backend": "image"},
        "screen_checks": [{"checkpoint": "complete", "ok": True}],
        "vision_cross_checks": {"all_required_ok": True},
        "physical_checks": {"vision_motion_confirmed": True, "specimen_alignment_ok": True,
                            "fixture_safe_to_access": True, "evidence_frame_ids": ["frame-1"]},
        "data_acquisition": {"status": "pulled_to_linux", "linux_path": "runs/result.csv",
                             "sha256": "abc", "row_count_probe": 2, "columns_probe": ["force_N"]},
        "cross_checks": {"screen_started": True, "data_parse_probe_ok": True,
                         "save_export_responsibility_ok": True},
        "decision": {"handoff_status": "ready_for_analysis", "equipment_status": "completed"},
        "artifact_records": [{"artifact_id": "csv-1"}],
        "artifact_refs": ["runs/result.csv"],
        "screen_evidence_refs": ["screen.png"],
        "data_evidence_refs": ["result.csv"],
        "failure_retry_table": [],
        "recovery": {},
        "live_evidence_audit": {"save_export": {"ok": True}},
    }
    metadata = {
        "equipment_report": report,
        "equipment_result": {"status": "completed", "program_id": "utm_cycle", "result_file": "runs/result.csv"},
        "utm_data_ready": {"status": "ready", "guardian_status": "allow"},
        "equipment_handoff": {"status": "ready_for_analysis"},
        "equipment_metrics": {"row_count": 2},
    }
    payload = {
        "equipment_report": {"decision": {"handoff_status": "old"}},
        "equipment_result": {"status": "old"},
        "utm_data_ready": {"status": "old"},
        "equipment_handoff": {"status": "old"},
        "metrics": {"row_count": 99},
        "decisions": [{"old": True}],
        "tool_results": [{"tool": "equipment.pyautogui.run"}],
    }
    before = deepcopy((metadata, payload))
    projected = project_equipment_report(metadata, payload)
    assert projected["equipment_report"] is report
    assert projected["equipment_result"]["status"] == "completed"
    assert projected["utm_data_ready"]["status"] == "ready"
    assert projected["equipment_handoff"]["status"] == "ready_for_analysis"
    assert projected["role_specific"]["control_trace"] == {
        "bridge_provider": "windows_pyautogui",
        "connection_status": "ready",
        "program_id": "utm_cycle",
        "macro_version": "1.0.7",
        "locator_backend": "image",
        "tool_result_count": 1,
    }
    assert projected["metrics"] == {"row_count": 2}
    assert projected["decisions"] == [{"handoff_status": "ready_for_analysis", "equipment_status": "completed"}]
    assert (metadata, payload) == before

    fallback = project_equipment_report({}, payload)
    assert fallback["equipment_report"] == payload["equipment_report"]
    assert fallback["equipment_result"] == payload["equipment_result"]
    assert fallback["metrics"] == payload["metrics"]


def test_equipment_executable_contract_and_source_symbols():
    from agents.equipment.agent import LabEquipmentAgent
    from agents.equipment.execution import default_equipment_execution_graph
    from agents.execution_graph import compile_execution_graph

    catalog = LabEquipmentAgent().execution_catalog()
    compile_execution_graph(default_equipment_execution_graph(), catalog)
    assert {operation.handler for operation in catalog.operations} == {"equipment.task", "equipment.deliver"}
    assert catalog.operation("equipment.task").llm is True
    assert catalog.required_outputs == ("agent_result",)
    areas = set()
    root = Path(__file__).resolve().parents[2]
    for detail in catalog.describe()["implementation_structure"]["operations"].values():
        ids = {"$operation"} | {node["id"] for node in detail["nodes"]}
        for edge in detail["edges"]:
            assert edge["source"] in ids and edge["target"] in ids
        for node in detail["nodes"]:
            areas.add(node["area"])
            source = node["source"]
            tree = ast.parse((root / source["path"]).read_text())
            assert any(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and item.name == source["symbol"].split(".")[-1]
                for item in ast.walk(tree)
            ), source
    assert areas == {"high", "middle", "low", "guardian", "knowledge"}


class _Owner:
    def __init__(self, result=None, hook=None):
        from agents.base_agent import AgentResult

        self.result = result or AgentResult(success=True, summary="owner completed", data={"marker": "real"})
        self.effects = 0
        self.hook = hook

    async def _run_task(self, state, ctx):
        self.effects += 1
        if self.hook:
            self.hook()
        return self.result


@pytest.mark.asyncio
async def test_equipment_graph_delivers_the_same_real_result_for_success_block_and_failure():
    from agents.base_agent import AgentResult
    from agents.equipment.execution import execute_equipment_graph

    for expected in (
        AgentResult(success=True, summary="completed", data={"status": "completed"}),
        AgentResult(success=False, summary="blocked", data={"status": "blocked"}),
        AgentResult(success=False, summary="worker failure", data={"failure_code": "WORKER_FAILED"}),
    ):
        owner = _Owner(expected)
        execution = await execute_equipment_graph(owner, object(), object())
        assert execution.result is expected
        assert execution.outputs["agent_result"] is expected
        assert owner.effects == 1
        assert [item["node_id"] for item in execution.trace if item["status"] == "completed"] == ["task", "deliver"]


@pytest.mark.asyncio
async def test_equipment_duplicate_task_is_rejected_before_a_second_owner_effect():
    from agents.equipment.execution import default_equipment_execution_graph, execute_equipment_graph
    from agents.execution_graph import ExecutionGraphError

    graph = default_equipment_execution_graph()
    graph["nodes"].append({"id": "repeat", "handler": "equipment.task", "area": "middle", "llm": True})
    graph["edges"] = [
        {"source": "task", "target": "repeat", "on": "next", "kind": "execution"},
        {"source": "repeat", "target": "deliver", "on": "next", "kind": "evidence"},
    ]
    owner = _Owner()
    with pytest.raises(ExecutionGraphError, match="cannot repeat"):
        await execute_equipment_graph(owner, object(), object(), graph=graph)
    assert owner.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["unknown", "no_task", "no_delivery"])
async def test_invalid_equipment_graph_fails_before_owner_effect(mutation):
    from agents.equipment.execution import default_equipment_execution_graph, execute_equipment_graph
    from agents.execution_graph import ExecutionGraphError

    graph = default_equipment_execution_graph()
    if mutation == "unknown":
        graph["nodes"][0]["handler"] = "python.arbitrary"
    else:
        remaining = "deliver" if mutation == "no_task" else "task"
        graph.update(
            entry=remaining,
            nodes=[node for node in graph["nodes"] if node["id"] == remaining],
            edges=[],
            terminals=[remaining],
        )
    owner = _Owner()
    with pytest.raises(ExecutionGraphError):
        await execute_equipment_graph(owner, object(), object(), graph=graph)
    assert owner.effects == 0


@pytest.mark.asyncio
async def test_equipment_execution_pins_definition_and_trace_invocation():
    from agents.equipment.execution import default_equipment_execution_graph, execute_equipment_graph

    graph = default_equipment_execution_graph()
    invocation = {"run_id": "pinned-run", "loop_index": 4, "invocation_id": "equipment-attempt"}
    owner = _Owner(hook=lambda: (
        graph["nodes"][1].update(handler="python.arbitrary"),
        invocation.update(invocation_id="changed-after-start"),
    ))
    events = []
    execution = await execute_equipment_graph(
        owner, object(), object(), graph=graph, invocation=invocation, emit=events.append
    )
    assert execution.result is owner.result
    assert all(event["payload"]["invocation_id"] == "equipment-attempt" for event in events)
    assert all(event["payload"]["loop_index"] == 4 for event in events)
    assert all(event["payload"]["graph_revision"] == execution.graph_revision for event in events)


@pytest.mark.asyncio
async def test_equipment_delivery_requires_an_owner_agent_result():
    from agents.base_agent import AgentResult
    from agents.equipment.agent import LabEquipmentAgent
    from agents.execution_graph import ExecutionGraphError

    delivery = LabEquipmentAgent().execution_catalog().operation("equipment.deliver")
    with pytest.raises(ExecutionGraphError, match="owner AgentResult"):
        await delivery.operation(None, None, {"task_result": {"success": False}}, {})
    blocked = AgentResult(success=False, summary="blocked")
    delivered = await delivery.operation(None, None, {"task_result": blocked}, {})
    assert delivered.outputs["agent_result"] is blocked


def _without_runtime_identity(value):
    """Remove only generated lifecycle identity fields from independent calls."""
    generated = {
        "execution_id", "created_at", "updated_at", "timestamp", "at",
        "flow_execution_id", "sequence_id", "snapshotted_at", "queued_at",
        "started_at", "finished_at",
    }
    if isinstance(value, dict):
        return {
            key: _without_runtime_identity(item)
            for key, item in value.items()
            if key not in generated
        }
    if isinstance(value, list):
        return [_without_runtime_identity(item) for item in value]
    return value


def _first_differences(left, right, path="result", limit=20):
    """Return compact leaf paths so equivalence failures stay actionable."""
    differences = []

    def visit(left_value, right_value, current_path):
        if len(differences) >= limit or left_value == right_value:
            return
        if isinstance(left_value, dict) and isinstance(right_value, dict):
            for key in sorted(left_value.keys() | right_value.keys()):
                if key not in left_value or key not in right_value:
                    differences.append(f"{current_path}.{key}: missing")
                else:
                    visit(left_value[key], right_value[key], f"{current_path}.{key}")
            return
        if isinstance(left_value, list) and isinstance(right_value, list):
            if len(left_value) != len(right_value):
                differences.append(f"{current_path}: length {len(left_value)} != {len(right_value)}")
            for index, (left_item, right_item) in enumerate(zip(left_value, right_value)):
                visit(left_item, right_item, f"{current_path}[{index}]")
            return
        differences.append(f"{current_path}: {left_value!r} != {right_value!r}")

    visit(left, right, path)
    return differences


class _RecordingTools:
    def __init__(self, registry):
        self.registry = registry
        self.calls = []

    def list_tools(self):
        return self.registry.list_tools()

    def call(self, name, payload):
        self.calls.append(name)
        return self.registry.call(name, payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["virtual_completed", "worker_blocked", "preflight", "worker_failure"])
async def test_equipment_graph_preserves_original_body_modes(
    branch, tmp_path, monkeypatch, no_external_effects
):
    from agents.equipment.agent import LabEquipmentAgent
    import agents.equipment.agent as owner_module
    import agents.knowledge_context as knowledge_context
    import device_bridges.windows_pyautogui.bridge as bridge_module
    import experiments.job_queue as job_queue
    from agents.equipment.execution import execute_equipment_graph
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.state import Mode
    from tests.unit.test_equipment_agent import _CtxStub, _state, _tools
    import utils.equipment_runtime_service as equipment_runtime_service
    import utils.equipment_skill_runtime as equipment_skill_runtime
    import uuid as uuid_module

    real_datetime = owner_module.datetime
    real_time = bridge_module.time

    class FixedDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 2, 3, 4, 5, tzinfo=tz)

    left_state = _state(
        experiment_spec={
            "specimen_id": "specimen-test",
            "equipment_profile_id": "utm_windows_v1",
            "equipment_program_id": "utm_compression_start_v1",
        }
    )
    if branch == "preflight":
        left_state = _state(
            mode=Mode.LIVE,
            experiment_spec={
                "equipment_skill": {"skill_id": "utm_start", "version": "1.0.0"},
                "execution_policy": {"lab_equipment": "preflight_only"},
            },
        )
    right_state = deepcopy(left_state)

    def tools_for(side):
        registry = ToolRegistry() if branch in {"worker_blocked", "preflight"} else _tools(tmp_path)
        if branch == "worker_failure":
            registry.register(
                "equipment.pyautogui.run",
                lambda payload: {
                    "ok": False,
                    "tool": "equipment.pyautogui.run",
                    "status": "failed",
                    "failure_code": "CONTROLLED_WORKER_FAILURE",
                    "program_id": payload.get("program_id", ""),
                    "executed_action_count": 0,
                    "actuation_performed": False,
                    "effects_known": True,
                },
                device="equipment:windows_pyautogui",
            )
        return _RecordingTools(registry)

    left_tools, right_tools = tools_for("left"), tools_for("right")
    no_external_effects.allowed_tools.update(left_tools.list_tools())
    no_external_effects.allowed_tools.update(right_tools.list_tools())
    left_ctx, right_ctx = _CtxStub(left_tools, "{}"), _CtxStub(right_tools, "{}")

    def seed_generated_ids():
        values = iter(UUID(int=index) for index in range(1, 10_000))
        perf_values = iter(index / 1_000 for index in range(1, 10_000))
        monotonic_values = iter(index / 1_000 for index in range(1, 10_000))

        def next_uuid():
            return next(values)

        monkeypatch.setattr(owner_module, "uuid4", next_uuid)
        monkeypatch.setattr(knowledge_context, "uuid4", next_uuid)
        monkeypatch.setattr(equipment_runtime_service, "uuid4", next_uuid)
        monkeypatch.setattr(equipment_skill_runtime, "uuid4", next_uuid)
        monkeypatch.setattr(uuid_module, "uuid4", next_uuid)
        monkeypatch.setattr(owner_module, "datetime", FixedDateTime)
        monkeypatch.setattr(equipment_runtime_service, "_now_iso", lambda: "2026-01-02T03:04:05+00:00")
        monkeypatch.setattr(equipment_skill_runtime, "_now_iso", lambda: "2026-01-02T03:04:05+00:00")
        monkeypatch.setattr(job_queue, "_now_iso", lambda: "2026-01-02T03:04:05+00:00")

        class FixedBridgeTime:
            def __getattr__(self, name):
                return getattr(real_time, name)

            @staticmethod
            def time():
                return 1_767_326_645.0

            @staticmethod
            def gmtime(*_args):
                return real_time.gmtime(1_767_326_645.0)

            @staticmethod
            def perf_counter():
                return next(perf_values)

        class FixedQueueTime:
            @staticmethod
            def monotonic():
                return next(monotonic_values)

        monkeypatch.setattr(bridge_module, "time", FixedBridgeTime())
        monkeypatch.setattr(job_queue, "time", FixedQueueTime())

    seed_generated_ids()
    monkeypatch.setattr(LabEquipmentAgent, "_RUNTIME_ROOT", tmp_path / "left-runtime")
    original = await LabEquipmentAgent()._run_task(left_state, left_ctx)
    seed_generated_ids()
    monkeypatch.setattr(LabEquipmentAgent, "_RUNTIME_ROOT", tmp_path / "right-runtime")
    execution = await execute_equipment_graph(LabEquipmentAgent(), right_state, right_ctx)

    assert (execution.result.success, execution.result.summary, execution.result.next_hint) == (
        original.success, original.summary, original.next_hint
    )
    execution_data = _without_runtime_identity(execution.result.data)
    original_data = _without_runtime_identity(original.data)
    assert execution_data == original_data, "\n".join(
        _first_differences(execution_data, original_data)
    )
    assert right_tools.calls == left_tools.calls
    assert right_ctx.prompts == left_ctx.prompts
    assert [item["node_id"] for item in execution.trace if item["status"] == "completed"] == [
        "task", "deliver"
    ]
