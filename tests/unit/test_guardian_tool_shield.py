"""
Unit tests for Guardian runtime action shield around module tool calls.
"""

from __future__ import annotations

from typing import Any

from orchestrator.langgraph_runtime import ModuleToolRegistryProxy
from orchestrator.state import Mode, OrchestratorState, Stage
from policies.guardian_gate import guardian_gate


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


def test_guardian_allows_vision_handoff_when_active_cam_confirms_spc_despite_pose_snapshot_failure() -> None:
    state = OrchestratorState(run_id="run-activecam-spc", experiment_id="exp-activecam-spc", mode=Mode.TEST, stage=Stage.VISION)

    gate = guardian_gate(
        state=state,
        stage="vision",
        phase="post",
        agent="vision_agent",
        payload={
            "observation": {
                "transfer_readiness": {
                    "ready": True,
                    "camera_ok": True,
                    "camera_returned_to_vla": True,
                    "vla_camera_precheck_ok": True,
                    "spc_autoejection_confirmed": True,
                    "blocking_reason": None,
                },
                "raw_capture": {
                    "active_cam_ejection_check": {
                        "status": "confirmed",
                        "specimen_detected": True,
                        "spc_autoejection_confirmed": True,
                        "camera_returned_to_vla": True,
                        "camera_owner_after": "vla_runtime",
                        "capture_path": "/tmp/active-cam.jpg",
                    },
                    "specimen_pose_result": {
                        "ok": False,
                        "status": "error",
                        "failure_code": "MISSING_REQUIRED_INPUT",
                        "message": "ROS2 camera topics are missing; D455F is not publishing RGB-D frames for specimen pose tracking.",
                    },
                },
            },
            "vision_signal": {"status": "ready", "confidence": 0.86, "warnings": []},
            "evidence_refs": ["/tmp/active-cam.jpg"],
        },
    )

    assert gate["decision"] in {"allow", "allow_with_warning"}
    assert gate["ok_for_next_stage"] is True
    assert all(
        not (
            alarm["reason_code"] == "MISSING_REQUIRED_INPUT"
            and "specimen_pose_result" in str(alarm.get("source_path") or "")
        )
        for alarm in gate["alarms"]
    )


def test_guardian_tool_shield_preserves_disabled_rollout_clamp_from_gui() -> None:
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
    assert recorded[0]["decision"] == "allow"
    assert recorded[0]["modified_payload_patch"] == {}
    assert events == []
    assert tools.calls[0][1]["rollout_action_clamp"] is False
    assert "guardian_modified_payload" not in tools.calls[0][1]
    records = state.run_metadata["tool_call_records"]
    assert [record["status"] for record in records] == ["requested", "completed"]


def test_guardian_tool_shield_preserves_enabled_rollout_clamp_from_gui() -> None:
    state = _state(Stage.MANIPULATION)
    tools = FakeTools()
    proxy = ModuleToolRegistryProxy(
        tools,
        ["lerobot.rollout.start"],
        Stage.MANIPULATION,
        state=state,
    )

    result = proxy.call(
        "lerobot.rollout.start",
        {
            "mode": "test",
            "dry_run": False,
            "policy_path": "/tmp/policy.ckpt",
            "rollout_action_clamp": True,
        },
    )

    assert result["ok"] is True
    assert tools.calls[0][1]["rollout_action_clamp"] is True
    assert "guardian_modified_payload" not in tools.calls[0][1]


def test_guardian_tool_shield_allows_rollout_after_bambu_http_artifact_handoff() -> None:
    state = _state(Stage.MANIPULATION)
    tools = FakeTools()
    recorded: list[dict[str, Any]] = []
    proxy = ModuleToolRegistryProxy(
        tools,
        ["lerobot.rollout.start"],
        Stage.MANIPULATION,
        state=state,
        gate_recorder=recorded.append,
    )

    result = proxy.call(
        "lerobot.rollout.start",
        {
            "mode": "test",
            "runtime_mode": "test",
            "dry_run": True,
            "profile_id": "robotis_omx_ai",
            "policy_path": "fake://policy",
            "rollout_action_clamp": True,
            "specimen": {
                "status": "ready",
                "spc_readiness": {
                    "preprint_gate_state": "test_printer_started_then_stopped",
                    "blockers": [],
                    "operator_actions": [
                        {
                            "code": "BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE",
                            "severity": "warning",
                            "message": "HTTP artifact routing is active.",
                        },
                        {
                            "code": "BAMBU_FTPS_TOO_MANY_CONNECTIONS",
                            "severity": "warning",
                            "message": "FTPS still reports too many active sessions; HTTP artifact routing is active.",
                        },
                    ],
                },
                "build_timeline": {
                    "timeline": [
                        {"step": "BAMBU_FTPS_STORAGE", "status": "blocked", "failure_code": "BAMBU_FTPS_TOO_MANY_CONNECTIONS"},
                        {"step": "BAMBU_ARTIFACT_ROUTE", "status": "ok", "detail": "http://printer-artifact/job.gcode.3mf"},
                        {"step": "BAMBU_START_PUBLISH", "status": "published"},
                        {"step": "BAMBU_STOP_AFTER_START", "status": "published"},
                    ]
                },
                "print_result": {
                    "status": "TEST_PRINTER_STARTED_THEN_STOPPED",
                    "upload": {"ok": True, "route": "http_artifact", "url": "http://printer-artifact/job.gcode.3mf"},
                    "start": {"ok": True, "status": "published", "published": True, "command": "project_file"},
                    "stop": {"ok": True, "status": "published", "published": True},
                },
            },
        },
    )

    assert result["ok"] is True
    assert tools.calls[0][0] == "lerobot.rollout.start"
    assert all(gate["reason_code"] != "BAMBU_FTPS_TOO_MANY_CONNECTIONS" for gate in recorded)


def test_guardian_tool_shield_allows_rollout_after_completed_printer_wait_handoff() -> None:
    state = _state(Stage.MANIPULATION)
    tools = FakeTools()
    recorded: list[dict[str, Any]] = []
    proxy = ModuleToolRegistryProxy(
        tools,
        ["lerobot.rollout.start"],
        Stage.MANIPULATION,
        state=state,
        gate_recorder=recorded.append,
    )

    result = proxy.call(
        "lerobot.rollout.start",
        {
            "mode": "test",
            "runtime_mode": "live",
            "dry_run": False,
            "confirm_live_execute": True,
            "profile_id": "robotis_omx_ai",
            "policy_path": "/tmp/policy.ckpt",
            "rollout_action_clamp": True,
            "physical_printer_tail": True,
            "specimen": {
                "status": "ready",
                "handoff_status": "ready",
                "printer_completion_wait": {
                    "schema": "specimen_printer_completion_wait.v1",
                    "status": "complete",
                    "last_status": {
                        "status": "complete",
                        "failure_code": "131184",
                        "message": "Printer job completed before Vision handoff.",
                    },
                    "samples": [
                        {
                            "status": "transient",
                            "failure_code": "BAMBU_PORT_UNREACHABLE",
                            "message": "Bambu printer port was temporarily unreachable.",
                        },
                        {
                            "status": "transient",
                            "failure_code": "BAMBU_MQTT_REPORT_TIMEOUT",
                            "message": "Timed out waiting for Bambu MQTT report.",
                        },
                        {
                            "status": "printing",
                            "failure_code": "131184",
                            "message": "Printer job is still active.",
                        }
                    ],
                },
                "active_cam_ejection_check": {
                    "status": "confirmed",
                    "specimen_detected": True,
                    "spc_autoejection_confirmed": True,
                    "camera_returned_to_vla": True,
                    "camera_owner_after": "vla_runtime",
                    "capture_path": "/tmp/active-cam.jpg",
                },
            },
        },
    )

    assert result["ok"] is True
    assert tools.calls[0][0] == "lerobot.rollout.start"
    assert all(
        not (
            "printer_completion_wait" in str(alarm.get("source_path") or "")
            and alarm.get("reason_code") in {"131184", "BAMBU_MQTT_REPORT_TIMEOUT", "HEARTBEAT_LOST"}
        )
        for gate in recorded
        for alarm in gate.get("alarms", [])
    )
