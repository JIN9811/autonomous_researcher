"""
Unit tests for Guardian runtime action shield around module tool calls.
"""

from __future__ import annotations

from typing import Any

from orchestrator.langgraph_runtime import ModuleToolRegistryProxy
from orchestrator.state import Mode, OrchestratorState, Stage


class FakeTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((name, dict(payload or {})))
        return {"ok": True, "tool": name, "status": "executed"}

    def list_tools(self) -> list[str]:
        return ["lerobot.rollout.start", "experiment.evaluate", "geometry.check_mesh_quality"]

    def queue_status(self) -> dict[str, Any]:
        return {"ok": True}


def _state(stage: Stage) -> OrchestratorState:
    return OrchestratorState(run_id="run-tool-shield", experiment_id="exp-tool-shield", mode=Mode.LIVE, stage=stage)


def test_guardian_tool_shield_blocks_live_rollout_without_confirmation() -> None:
    state = _state(Stage.MANIPULATION)
    tools = FakeTools()
    recorded: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    proxy = ModuleToolRegistryProxy(
        tools,
        ["lerobot.rollout.start"],
        Stage.MANIPULATION,
        state=state,
        gate_recorder=recorded.append,
        tool_event_emitter=events.append,
    )

    result = proxy.call(
        "lerobot.rollout.start",
        {
            "mode": "live",
            "dry_run": False,
            "policy_path": "/tmp/policy.ckpt",
            "rollout_action_clamp": True,
        },
    )

    assert result["ok"] is False
    assert result["failure_code"] == "GUARDIAN_TOOL_APPROVAL_REQUIRED"
    assert result["requires_human_approval"] is True
    assert tools.calls == []
    assert recorded[-1]["decision"] == "require_human_approval"
    assert events[-1]["tool"] == "guardian.tool_shield"
    assert events[-1]["shielded_tool"] == "lerobot.rollout.start"
    records = state.run_metadata["tool_call_records"]
    assert [record["status"] for record in records] == ["requested", "approval_required"]
    assert records[-1]["guardian_decision"] == "require_human_approval"
    assert records[-1]["failure_code"] == "GUARDIAN_TOOL_APPROVAL_REQUIRED"


def test_guardian_tool_shield_allows_confirmed_live_rollout_and_records_post_gate() -> None:
    state = _state(Stage.MANIPULATION)
    tools = FakeTools()
    recorded: list[dict[str, Any]] = []
    proxy = ModuleToolRegistryProxy(tools, ["lerobot.rollout.start"], Stage.MANIPULATION, state=state, gate_recorder=recorded.append)

    result = proxy.call(
        "lerobot.rollout.start",
        {
            "mode": "live",
            "dry_run": False,
            "confirm_live_execute": True,
            "policy_path": "/tmp/policy.ckpt",
            "rollout_action_clamp": True,
        },
    )

    assert result["ok"] is True
    assert tools.calls[0][0] == "lerobot.rollout.start"
    assert [gate["action"] for gate in recorded] == ["pre_tool_call", "post_tool_call"]
    assert recorded[0]["decision"] == "allow"
    records = state.run_metadata["tool_call_records"]
    assert [record["status"] for record in records] == ["requested", "completed"]
    assert records[-1]["guardian_gate_id"] == recorded[-1]["gate_id"]


def test_guardian_tool_shield_blocks_live_printer_experiment_without_physical_allow() -> None:
    state = _state(Stage.SPECIMEN)
    tools = FakeTools()
    recorded: list[dict[str, Any]] = []
    proxy = ModuleToolRegistryProxy(tools, ["experiment.evaluate"], Stage.SPECIMEN, state=state, gate_recorder=recorded.append)

    result = proxy.call(
        "experiment.evaluate",
        {
            "execution": {"mode": "live", "bridge": "printer", "requested_tool": "printer.prepare", "dry_run": False},
            "candidate": {"parameters": {"print": {"start_immediately": True}}},
        },
    )

    assert result["ok"] is False
    assert result["failure_code"] == "GUARDIAN_TOOL_SHIELD_BLOCKED"
    assert tools.calls == []
    assert recorded[-1]["decision"] == "block"
    assert any(alarm["reason_code"] == "MISSING_REQUIRED_INPUT" for alarm in recorded[-1]["alarms"])
    records = state.run_metadata["tool_call_records"]
    assert [record["status"] for record in records] == ["requested", "blocked"]
    assert records[-1]["guardian_decision"] == "block"


def test_guardian_tool_shield_passes_non_side_effect_tool_without_gate() -> None:
    state = _state(Stage.SPECIMEN)
    tools = FakeTools()
    recorded: list[dict[str, Any]] = []
    proxy = ModuleToolRegistryProxy(tools, ["geometry.check_mesh_quality"], Stage.SPECIMEN, state=state, gate_recorder=recorded.append)

    result = proxy.call("geometry.check_mesh_quality", {"mode": "live"})

    assert result["ok"] is True
    assert tools.calls[0][0] == "geometry.check_mesh_quality"
    assert recorded == []
    records = state.run_metadata["tool_call_records"]
    assert [record["status"] for record in records] == ["requested", "completed"]
    assert records[-1]["tool"] == "geometry.check_mesh_quality"


def test_guardian_tool_shield_modifies_disabled_rollout_clamp_before_execution() -> None:
    state = _state(Stage.MANIPULATION)
    tools = FakeTools()
    recorded: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    proxy = ModuleToolRegistryProxy(
        tools,
        ["lerobot.rollout.start"],
        Stage.MANIPULATION,
        state=state,
        gate_recorder=recorded.append,
        tool_event_emitter=events.append,
    )

    result = proxy.call(
        "lerobot.rollout.start",
        {
            "mode": "test",
            "dry_run": False,
            "policy_path": "/tmp/policy.ckpt",
            "rollout_action_clamp": False,
        },
    )

    assert result["ok"] is True
    assert recorded[0]["decision"] == "modify"
    assert recorded[0]["modified_payload_patch"]["rollout_action_clamp"] is True
    assert events[-1]["status"] == "modified"
    assert tools.calls[0][1]["rollout_action_clamp"] is True
    assert tools.calls[0][1]["guardian_modified_payload"] is True
    records = state.run_metadata["tool_call_records"]
    assert [record["status"] for record in records] == ["requested", "modified", "completed"]
    assert records[1]["guardian_decision"] == "modify"
