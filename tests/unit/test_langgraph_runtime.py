"""Tests for config-driven LangGraph runtime wiring."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import app.main as app_main
from agents.registry import AgentRegistry
from agents.base_agent import AgentResult
from experiments.bo_visualization import build_bo_visualization
from graphs import ATRLangGraphCompiler, GraphConfig, HandlerRegistry, ModuleConfig, load_graph_config, load_module_config
from logging_system.structured_logger import StructuredLogger
from orchestrator.langgraph_runtime import LangGraphRunLoop, compact_runtime_payload
from orchestrator.graph import OrchestrationGraph
from orchestrator.router import stage_to_agent
from orchestrator.state import Mode, OrchestratorState, Stage
from orchestrator.supervisor import build_orchestrator_followup
from orchestrator.transitions import default_next_stage, ordered_stages
from policies.guardian_gate import gate_blocks_execution, guardian_gate


def _runtime_bo_visualization() -> dict[str, object]:
    return build_bo_visualization(
        run_id="run-runtime-bo-artifacts",
        objective={
            "objective_id": "sea",
            "name": "Specific energy absorption",
            "direction": "maximize",
            "unit": "J/g",
            "expression": {"op": "metric", "metric_id": "specific_energy_absorption"},
        },
        parameter_space={"relative_density": [0.2, 0.3, 0.4]},
        trace={
            "step": 2,
            "acquisition": "expected_improvement",
            "backend_requested": "botorch_optional",
            "backend_active": "botorch_optional",
            "candidates": [
                {
                    "candidate_id": f"candidate-{index}",
                    "x": index,
                    "surrogate_mean": mean,
                    "uncertainty": std,
                    "acquisition_value": acquisition,
                    "parameters": {"relative_density": density},
                }
                for index, (density, mean, std, acquisition) in enumerate(
                    [(0.2, 0.62, 0.08, 0.02), (0.3, 0.78, 0.05, 0.09), (0.4, 0.71, 0.06, 0.04)],
                    start=1,
                )
            ],
            "evaluated_points": [
                {
                    "candidate_id": "candidate-1",
                    "score": 0.60,
                    "parameters": {"relative_density": 0.2},
                }
            ],
            "selected": {
                "candidate_id": "candidate-2",
                "surrogate_mean": 0.78,
                "uncertainty": 0.05,
                "acquisition_value": 0.09,
                "parameters": {"relative_density": 0.3},
            },
        },
        selected_parameter="relative_density",
    )


def test_langgraph_runtime_publishes_bo_posterior_artifacts_under_run_directory(tmp_path: Path) -> None:
    state = OrchestratorState(
        run_id="run-runtime-bo-artifacts",
        experiment_id="exp-runtime-bo-artifacts",
        mode=Mode.TEST,
        stage=Stage.BO,
    )
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=StructuredLogger(tmp_path / "structured.jsonl", tmp_path / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
    )

    data = {"bo_result": {"visualization": _runtime_bo_visualization()}}
    records = runtime._register_runtime_artifacts(
        Stage.BO,
        "bo_agent",
        data,
    )

    posterior_records = [record for record in records if str(record.get("key", "")).startswith("runtime.bo_posterior.")]
    posterior_paths = {tmp_path / str(record["path"]) for record in posterior_records}
    assert {path.suffix for path in posterior_paths} == {".png", ".svg", ".csv"}
    assert all(path.is_file() and path.stat().st_size > 0 for path in posterior_paths)
    assert posterior_records == state.run_metadata["runtime_artifacts"][1:4]
    artifacts = data["bo_result"]["visualization"]["artifacts"]
    assert artifacts["png_url"].startswith(
        "/api/runs/run-runtime-bo-artifacts/artifact-file/runtime/bo/"
    )
    assert artifacts["png_url"].endswith("_posterior.png")


def test_langgraph_runtime_preserves_latest_bo_visualization_for_live_gui(tmp_path: Path) -> None:
    state = OrchestratorState(
        run_id="run-runtime-bo-live-gui",
        experiment_id="exp-runtime-bo-live-gui",
        mode=Mode.TEST,
        stage=Stage.BO,
    )
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=StructuredLogger(tmp_path / "structured.jsonl", tmp_path / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
    )
    visualization = _runtime_bo_visualization()

    runtime._merge_agent_data(
        Stage.BO,
        {
            "bo_result": {
                "benchmark": {
                    "strategies": {
                        "bo": {"surrogate_trace": [{"visualization": visualization}]},
                    }
                }
            }
        },
    )

    assert state.run_metadata["bo_visualization"] == visualization


def test_langgraph_runtime_preserves_both_active_bo_design_variables(tmp_path: Path) -> None:
    state = OrchestratorState(
        run_id="run-runtime-bo-two-variable",
        experiment_id="exp-runtime-bo-two-variable",
        mode=Mode.TEST,
        stage=Stage.BO,
    )
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=StructuredLogger(tmp_path / "structured.jsonl", tmp_path / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
    )

    runtime._merge_agent_data(
        Stage.BO,
        {"experiment_spec_update": {"cell_size_mm": 7.5, "relative_density": 0.41}},
    )

    assert state.run_metadata["bo_recommended_constraints"] == {
        "cell_size_mm": 7.5,
        "relative_density": 0.41,
    }


class _CustomQualityAgent:
    name = "custom_quality_agent"

    async def run(self, state: OrchestratorState, ctx: object) -> AgentResult:
        return AgentResult(
            success=True,
            summary="custom quality gate complete",
            data={
                "metrics": {"quality_score": 0.97},
                "handoff_packet": {"status": "ready", "from_stage": "custom_quality_gate"},
            },
        )


def test_supervisor_followup_uses_custom_stage_supervisor_policy() -> None:
    state = OrchestratorState(
        run_id="run-custom-supervisor-policy",
        experiment_id="exp-custom-supervisor-policy",
        mode=Mode.TEST,
        stage=Stage("custom_quality_gate"),
    )

    followup = build_orchestrator_followup(
        state=state,
        stage="custom_quality_gate",
        trigger="agent_result",
        next_stage=Stage.GUARDIAN,
        payload={
            "status": "ready",
            "quality_metrics": {"quality_score": 0.91},
            "handoff_packet": {"status": "ready"},
            "module_runtime": {
                "module_id": "custom_quality",
                "label": "Custom Quality Gate",
                "handler": "agent.custom_quality_agent",
                "supervisor_policy": {
                    "required_outputs": ["quality_metrics", "handoff_packet"],
                    "opinion_template": "Custom Quality Gate checked status={status} quality_score={quality_metrics.quality_score}.",
                    "recommendation_template": "Handoff to {next_stage} after verifying {required_outputs}.",
                    "concern_rules": [
                        {
                            "id": "quality_score_low",
                            "selector": "quality_metrics.quality_score",
                            "lt": 0.95,
                            "message": "quality score is below target",
                        }
                    ],
                    "options": [{"id": "rerun_quality", "label": "Rerun quality check", "risk": "low"}],
                },
            },
        },
    )

    assert followup["opinion"] == "Custom Quality Gate checked status=ready quality_score=0.91."
    assert followup["recommendation"] == "Handoff to guardian after verifying quality_metrics, handoff_packet."
    assert followup["concerns"] == ["quality_score_low: quality score is below target"]
    assert followup["options"] == [{"id": "rerun_quality", "label": "Rerun quality check", "risk": "low"}]
    assert followup["next_agent"] == "guardian_agent"


def test_module_lifecycle_checks_supervisor_policy_required_outputs() -> None:
    payload = {
        "module": {
            "id": "custom_quality",
            "label": "Custom Quality",
            "status": "active",
            "enabled": True,
            "handler": "agent.custom_quality_agent",
            "execution": {"capability": "agent"},
            "output_contracts": ["quality_metrics"],
            "supervisor_policy": {
                "required_outputs": ["quality_metrics", "handoff_packet"],
            },
            "internal_graph": [
                {
                    "id": "run_quality",
                    "label": "Run quality",
                    "handler": "agent.custom_quality_agent",
                }
            ],
        }
    }

    lifecycle = app_main._module_management_lifecycle("custom_quality", payload)
    requirement_by_id = {item["id"]: item for item in lifecycle["activation_requirements"]}

    assert "supervisor_policy_outputs" in requirement_by_id
    assert requirement_by_id["supervisor_policy_outputs"]["ok"] is False
    assert "handoff_packet" in requirement_by_id["supervisor_policy_outputs"]["detail"]
    assert lifecycle["supervisor_policy_gate"]["required_outputs"] == ["quality_metrics", "handoff_packet"]
    assert lifecycle["supervisor_policy_gate"]["missing_outputs"] == ["handoff_packet"]

    payload["module"]["output_contracts"].append("handoff_packet")
    lifecycle_ready = app_main._module_management_lifecycle("custom_quality", payload)
    ready_requirement_by_id = {item["id"]: item for item in lifecycle_ready["activation_requirements"]}

    assert ready_requirement_by_id["supervisor_policy_outputs"]["ok"] is True
    assert lifecycle_ready["supervisor_policy_gate"]["missing_outputs"] == []


def _noop_registry() -> HandlerRegistry:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    registry = HandlerRegistry()

    async def _noop(runtime_state: dict[str, object]) -> dict[str, object]:
        return runtime_state

    for handler_id in config.handler_ids:
        registry.register(handler_id, _noop)
    return registry


def _event_cursor() -> int:
    return len(app_main.controller.recent_events())


def test_bridge_custom_non_readonly_action_is_workspace_handoff_only() -> None:
    payload = app_main._normalized_bridge_manifests(
        {
            "device_bridges": [
                {
                    "id": "custom_robot_bridge",
                    "label": "Custom Robot Bridge",
                    "workspace": "/lerobot",
                    "tools": ["lerobot.rollout.start"],
                    "actions": [
                        {
                            "id": "run_policy",
                            "label": "Run Policy",
                            "kind": "api",
                            "method": "POST",
                            "endpoint": "/api/lerobot/rollout/start",
                            "requires_confirmation": True,
                            "read_only": False,
                            "tool": "lerobot.rollout.start",
                            "mode_support": ["test", "live"],
                        }
                    ],
                }
            ]
        },
        health={},
    )

    bridge = payload[0]
    action = bridge["actions"][0]

    assert action["id"] == "run_policy"
    assert action["source"] == "graph.metadata.device_bridges.actions"
    assert action["live_card_runnable"] is False
    assert action["handoff_required"] is True
    assert action["handoff_workspace"] == "/lerobot"
    assert action["blocked_reason"] == "workspace_handoff_required"
    assert bridge["custom_action_count"] == 1
    assert bridge["live_card_runnable_action_count"] == 0


def test_bridge_custom_action_descriptor_can_be_saved_to_graph_metadata(tmp_path, monkeypatch) -> None:
    config_root = tmp_path / "graph_configs"
    config_root.mkdir()
    active_graph_path = config_root / "atr_closed_loop.yaml"
    active_graph_path.write_text(Path("graphs/configs/atr_closed_loop.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_CONFIG_ROOT", config_root)
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_VERSION_ROOT", tmp_path / "graph_versions")

    client = TestClient(app_main.app)
    response = client.post(
        "/api/bridges/windows_pyautogui_bridge/actions",
        json={
            "action": {
                "id": "run_utm_macro",
                "label": "Run UTM Macro",
                "kind": "api",
                "method": "POST",
                "endpoint": "/api/equipment/windows/run-program",
                "read_only": False,
                "requires_confirmation": True,
                "tool": "equipment.pyautogui.run",
                "mode_support": ["live"],
            },
            "reason": "unit bridge action descriptor",
            "author": "pytest",
        },
    )

    assert response.status_code == 200
    saved = response.json()
    assert saved["ok"] is True
    assert saved["graph_id"] == "atr_closed_loop"
    assert saved["bridge_id"] == "windows_pyautogui_bridge"
    assert saved["execution_scope"] == "descriptor_only"
    action = saved["action"]
    assert action["id"] == "run_utm_macro"
    assert action["live_card_runnable"] is False
    assert action["handoff_required"] is True
    assert action["handoff_workspace"] == "/equipment/windows"

    bridges = client.get("/api/bridges").json()
    bridge_by_id = {item["id"]: item for item in bridges["bridges"]}
    saved_action_by_id = {
        item["id"]: item
        for item in bridge_by_id["windows_pyautogui_bridge"]["actions"]
    }
    assert saved_action_by_id["run_utm_macro"]["endpoint"] == "/api/equipment/windows/run-program"
    assert saved_action_by_id["run_utm_macro"]["read_only"] is False
    assert saved_action_by_id["run_utm_macro"]["handoff_required"] is True
    assert bridge_by_id["windows_pyautogui_bridge"]["custom_action_count"] == 1
    assert bridge_by_id["windows_pyautogui_bridge"]["live_card_runnable_action_count"] == 0

    runtime_state = client.get("/api/runtime/state").json()
    contract_bridge_by_id = {
        item["id"]: item
        for item in runtime_state["runtime_ide_contract"]["device_bridges"]
    }
    contract_action_by_id = {
        item["id"]: item
        for item in contract_bridge_by_id["windows_pyautogui_bridge"]["actions"]
    }
    assert contract_action_by_id["run_utm_macro"] == saved_action_by_id["run_utm_macro"]
    assert contract_action_by_id["run_utm_macro"]["live_card_runnable"] is False
    assert contract_action_by_id["run_utm_macro"]["handoff_workspace"] == "/equipment/windows"

    active_yaml = active_graph_path.read_text(encoding="utf-8")
    assert "run_utm_macro" in active_yaml
    assert "equipment.pyautogui.run" in active_yaml
    assert (tmp_path / "graph_versions" / "atr_closed_loop" / f"{saved['version']['version_id']}.yaml").exists()


def test_new_bridge_manifest_entry_is_shared_by_bridge_api_and_runtime_contract(tmp_path, monkeypatch) -> None:
    config_root = tmp_path / "graph_configs"
    config_root.mkdir()
    active_graph_path = config_root / "atr_closed_loop.yaml"
    payload = yaml.safe_load(Path("graphs/configs/atr_closed_loop.yaml").read_text(encoding="utf-8"))
    graph_payload = payload.setdefault("graph", {})
    metadata = graph_payload.setdefault("metadata", {})
    bridges = metadata.setdefault("device_bridges", [])
    bridges.append(
        {
            "id": "unit_custom_bridge",
            "label": "Unit Custom Bridge",
            "workspace": "/ide",
            "tools": ["unit.bridge.probe"],
            "health_endpoint": "/api/runtime/state",
            "preflight_endpoint": "/api/runtime/state",
            "actions": [
                {
                    "id": "status_probe",
                    "label": "Status Probe",
                    "kind": "api",
                    "method": "GET",
                    "endpoint": "/api/runtime/state",
                    "read_only": True,
                    "requires_confirmation": False,
                    "tool": "unit.bridge.probe",
                    "mode_support": ["test"],
                }
            ],
        }
    )
    active_graph_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_CONFIG_ROOT", config_root)
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_VERSION_ROOT", tmp_path / "graph_versions")

    client = TestClient(app_main.app)
    bridges_payload = client.get("/api/bridges").json()
    assert bridges_payload["ok"] is True
    bridge_by_id = {item["id"]: item for item in bridges_payload["bridges"]}
    bridge = bridge_by_id["unit_custom_bridge"]
    assert bridge["workspace"] == "/ide"
    assert "tool:unit.bridge.probe" in bridge["evidence_contracts"]
    action_by_id = {item["id"]: item for item in bridge["actions"]}
    assert action_by_id["status_probe"]["live_card_runnable"] is True
    assert action_by_id["status_probe"]["handoff_required"] is False
    assert action_by_id["status_probe"]["endpoint"] == "/api/runtime/state"

    runtime_state = client.get("/api/runtime/state").json()
    contract_bridge_by_id = {
        item["id"]: item
        for item in runtime_state["runtime_ide_contract"]["device_bridges"]
    }
    assert contract_bridge_by_id["unit_custom_bridge"]["actions"] == bridge["actions"]
    assert contract_bridge_by_id["unit_custom_bridge"]["evidence_contracts"] == bridge["evidence_contracts"]
    assert contract_bridge_by_id["unit_custom_bridge"]["source"] == "graph.metadata.device_bridges"


def _assert_runtime_event_since(cursor: int, event_type: str, action: str) -> dict[str, object]:
    events = app_main.controller.recent_events()[cursor:]
    matched = [
        event
        for event in events
        if event.get("type") == event_type and isinstance(event.get("payload"), dict) and event["payload"].get("action") == action
    ]
    assert matched, f"missing {event_type} action={action}; saw={[event.get('type') for event in events]}"
    return matched[-1]


def _set_graph_default_transition(payload: dict[str, object], source: str, target: str) -> None:
    """Update transitions plus the matching logical edge in a graph JSON payload."""
    transitions = payload.setdefault("transitions", {})
    assert isinstance(transitions, dict)
    transitions[source] = target
    edges = payload.get("edges")
    assert isinstance(edges, list)
    default_edge = next(
        edge
        for edge in edges
        if isinstance(edge, dict)
        and isinstance(edge.get("metadata"), dict)
        and edge["metadata"].get("runtime_edge") == "logical_transition"
        and edge["metadata"].get("from_stage") == source
        and edge["metadata"].get("default_transition") is True
    )
    default_edge["target"] = target
    default_edge["label"] = f"default transition: {source} -> {target}"
    default_edge["metadata"]["to_stage"] = target




def _add_graph_transition_candidate(
    payload: dict[str, object],
    source: str,
    target: str,
    condition: str,
) -> None:
    """Append a Runtime IDE-style logical transition candidate without changing the default route."""
    edges = payload.setdefault("edges", [])
    assert isinstance(edges, list)
    edges.append(
        {
            "source": source,
            "target": target,
            "condition": condition,
            "label": f"candidate transition: {source} -> {target}",
            "metadata": {
                "runtime_edge": "logical_transition",
                "from_stage": source,
                "to_stage": target,
                "condition": condition,
                "transition_condition": condition,
                "default_transition": False,
                "auto_ports": True,
            },
        }
    )


def test_compact_runtime_payload_preserves_shared_empty_handoff_lists_for_guardian() -> None:
    missing_required_fields: list[str] = []
    payload = {
        "experiment_spec": {"validation_warnings": ["cand-1-06: cell_size_mm below 3x wall thickness rule"]},
        "design_report": {
            "decision_register": [{"evidence": {"missing_required_fields": missing_required_fields}}],
            "handoff_to_specimen": {
                "required_fields_present": True,
                "missing_required_fields": missing_required_fields,
            },
        },
    }

    compact = compact_runtime_payload(payload)
    gate = guardian_gate(
        state=OrchestratorState(run_id="run-compact", experiment_id="exp-compact", mode=Mode.TEST, stage=Stage.DESIGN),
        stage="design",
        phase="post",
        agent="design_agent",
        payload=compact,
    )

    assert compact["design_report"]["handoff_to_specimen"]["missing_required_fields"] == []
    assert gate["decision"] == "allow_with_warning"
    assert gate_blocks_execution(gate) is False
    assert not any(alarm["reason_code"] == "MISSING_REQUIRED_INPUT" for alarm in gate["alarms"])


def test_langgraph_runtime_tool_call_snapshot_persists_blackbox_record(tmp_path: Path) -> None:
    state = OrchestratorState(run_id="run-runtime-tool", experiment_id="exp-runtime-tool", mode=Mode.TEST)
    logger = StructuredLogger(tmp_path / "runtime.jsonl", tmp_path / "summary.log")
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator",
        ctx=object(),
        logger=logger,
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
    )
    record = {
        "schema": "tool_call_record.v1",
        "record_id": "tool-record-001",
        "call_id": "tool-call-001",
        "run_id": state.run_id,
        "stage": "specimen",
        "tool": "printer.prepare",
        "status": "completed",
    }

    runtime._record_tool_call_snapshot(record)

    assert state.run_metadata["tool_call_records"] == [record]
    guardian_events = tmp_path / "guardian_events.jsonl"
    assert guardian_events.exists()
    lines = [json.loads(line) for line in guardian_events.read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["schema"] == "tool_call_record.v1"
    assert lines[-1]["call_id"] == "tool-call-001"


def test_langgraph_runtime_equipment_alert_merge_persists_incident_records(tmp_path: Path) -> None:
    state = OrchestratorState(run_id="run-runtime-incident", experiment_id="exp-runtime-incident", mode=Mode.TEST)
    logger = StructuredLogger(tmp_path / "runtime.jsonl", tmp_path / "summary.log")
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator",
        ctx=object(),
        logger=logger,
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
    )
    incident = {
        "schema": "incident_record.v1",
        "incident_id": "incident-runtime-001",
        "device_class": "utm",
        "component": "utm_data_export",
        "failure_code": "UTM_DATA_TIMEOUT",
    }
    alert = {
        "schema": "hardware_alert.v1",
        "alert_id": "alert-runtime-001",
        "device_class": "utm",
        "component": "utm_data_export",
        "severity": "blocking",
        "failure_code": "UTM_DATA_TIMEOUT",
        "status": "blocked",
        "guardian_decision": {"schema": "guardian_decision.v1", "decision": "safe_stop"},
        "incident_record": incident,
    }

    runtime._merge_agent_data(
        Stage.EQUIPMENT,
        {
            "equipment_result": {"ok": False, "status": "blocked", "failure_code": "UTM_DATA_TIMEOUT"},
            "hardware_alert": alert,
            "incident_records": [incident],
        },
    )

    assert state.run_metadata["hardware_alerts"][0]["alert_id"] == "alert-runtime-001"
    assert state.run_metadata["incident_records"][0]["incident_id"] == "incident-runtime-001"
    assert state.run_metadata["latest_guardian_decision"]["schema"] == "guardian_decision.v1"
    assert state.device_health["utm"] == "blocking:UTM_DATA_TIMEOUT"
    guardian_log = tmp_path / "guardian_events.jsonl"
    assert guardian_log.exists()
    assert "incident-runtime-001" in guardian_log.read_text(encoding="utf-8")


def test_langgraph_runtime_vision_confirmation_updates_specimen_result(tmp_path: Path) -> None:
    state = OrchestratorState(run_id="run-vision-confirm", experiment_id="exp-vision-confirm", mode=Mode.TEST)
    state.run_metadata["specimen_result"] = {
        "ok": True,
        "specimen_id": "specimen-vision-001",
        "handoff_status": "ready",
        "fabrication_report": {
            "fabrication_outcome": {
                "print_completion_status": "complete",
                "autoejection_status": "awaiting_vision_confirmation",
            }
        },
        "specimen_agent_report": {"autoejection_gate": {"status": "waiting"}},
    }
    logger = StructuredLogger(tmp_path / "runtime.jsonl", tmp_path / "summary.log")
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator",
        ctx=object(),
        logger=logger,
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
    )

    runtime._merge_agent_data(
        Stage.VISION,
        {
            "observation": {
                "active_cam_ejection_check": {
                    "schema": "active_cam_ejection_check.v1",
                    "status": "confirmed",
                    "specimen_detected": True,
                    "spc_autoejection_confirmed": True,
                    "image_path": "/tmp/active-cam.png",
                },
                "spc_autoejection_confirmation": {
                    "schema": "spc_autoejection_confirmation.v1",
                    "signal": "SPC_AUTOEJECTION_CONFIRMED_BY_ACTIVE_CAM",
                    "status": "confirmed",
                    "confirmed": True,
                    "specimen_detected": True,
                    "consumer_agent": "specimen_agent",
                },
            },
            "vision_signal": {
                "schema": "vision_signal.v1",
                "signal": "pickup_ready",
                "value": True,
            },
        },
    )

    specimen = state.run_metadata["specimen_result"]
    assert specimen["vision_completion_signal"]["confirmed"] is True
    assert specimen["vision_verification"]["status"] == "confirmed"
    assert specimen["active_cam_ejection_check"]["image_path"] == "/tmp/active-cam.png"
    assert specimen["autoejection_completion_verified"] is True
    assert specimen["fabrication_report"]["fabrication_outcome"]["autoejection_status"] == "complete"
    assert specimen["specimen_agent_report"]["autoejection_gate"]["status"] == "complete"

    runtime._merge_agent_data(
        Stage.VISION,
        {
            "transition_decision": "vision_utm_monitoring",
            "observation": {
                "active_cam_ejection_check": {
                    "status": "not_checked",
                    "spc_autoejection_confirmed": False,
                },
                "spc_autoejection_confirmation": {
                    "status": "not_checked",
                    "confirmed": False,
                },
            }
        },
    )

    specimen = state.run_metadata["specimen_result"]
    # A post-manipulation UTM retry must not overwrite the completed SPC gate.
    assert specimen["vision_verification"]["status"] == "confirmed"
    assert specimen["autoejection_completion_verified"] is True
    assert specimen["active_cam_ejection_check"]["spc_autoejection_confirmed"] is True


def test_langgraph_runtime_retains_active_cam_artifact_until_explicit_failure(tmp_path: Path) -> None:
    state = OrchestratorState(run_id="run-active-cam", experiment_id="exp-active-cam", mode=Mode.TEST)
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator",
        ctx=object(),
        logger=StructuredLogger(tmp_path / "runtime.jsonl", tmp_path / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
    )
    stored = {
        "schema": "active_cam_run_artifact.v1",
        "status": "stored",
        "path": "/runs/new.jpg",
        "url": "/api/runs/run-active-cam/artifact-file/vision/frame/new.jpg",
    }

    runtime._merge_agent_data(Stage.VISION, {"active_cam_artifact_update": stored})
    runtime._merge_agent_data(Stage.MANIPULATION, {"manipulation_report": {"status": "running"}})

    assert state.run_metadata["latest_active_cam_artifact"] == stored

    runtime._merge_agent_data(
        Stage.VISION,
        {"active_cam_artifact_update": {"schema": "active_cam_run_artifact.v1", "status": "failed"}},
    )

    assert "latest_active_cam_artifact" not in state.run_metadata


def test_langgraph_runtime_retains_utm_completion_artifact_until_next_attempt_fails(tmp_path: Path) -> None:
    state = OrchestratorState(run_id="run-utm", experiment_id="exp-utm", mode=Mode.TEST)
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator",
        ctx=object(),
        logger=StructuredLogger(tmp_path / "runtime.jsonl", tmp_path / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
    )
    stored = {
        "schema": "utm_completion_run_artifact.v1",
        "status": "stored",
        "path": "/runs/utm-confirmed.png",
        "url": "/api/runs/run-utm/artifact-file/vision/frame/utm-confirmed.png",
        "session_id": "rollout-utm-001",
        "specimen_id": "specimen-utm-001",
    }

    runtime._merge_agent_data(Stage.VISION, {"utm_completion_artifact_update": stored})
    runtime._merge_agent_data(Stage.MANIPULATION, {"manipulation_report": {"status": "running"}})

    assert state.run_metadata["latest_utm_completion_artifact"] == stored

    runtime._merge_agent_data(
        Stage.VISION,
        {
            "utm_completion_artifact_update": {
                "schema": "utm_completion_run_artifact.v1",
                "status": "not_detected",
                "session_id": "rollout-utm-002",
            }
        },
    )

    assert "latest_utm_completion_artifact" not in state.run_metadata


def test_atr_graph_config_validates_and_compiles() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    compiler = ATRLangGraphCompiler(config, _noop_registry())

    assert compiler.validate() == []
    assert config.stage_dispatch["bo"] == "bo"
    assert config.transitions["knowledge"] == "bo"
    assert config.transitions["bo"] == "guardian"
    assert config.nodes[0].position["x"] >= 0
    assert config.nodes[0].metadata["icon"]
    transition_edges = [edge for edge in config.edges if edge.metadata.get("runtime_edge") == "logical_transition"]
    assert any(edge.metadata.get("from_stage") == "knowledge" and edge.metadata.get("to_stage") == "bo" for edge in transition_edges)
    assert compiler.compile() is not None


@pytest.mark.asyncio
async def test_langgraph_runtime_accepts_graph_validated_custom_stage(tmp_path: Path) -> None:
    """Graph-configured extension stages must not fail only because they are absent from Stage enum."""
    graph_path = tmp_path / "custom_stage_graph.yaml"
    graph_path.write_text(
        yaml.safe_dump(
            {
                "graph": {
                    "id": "custom_stage_graph",
                    "name": "Custom Stage Graph",
                    "version": "0.1.0",
                    "entry_node": "dispatch",
                    "finish_nodes": ["step_complete"],
                    "terminal_stages": ["complete", "error"],
                    "stage_dispatch": {
                        "idle": "idle_node",
                        "custom_quality_gate": "custom_quality_gate_node",
                        "complete": "complete_node",
                        "error": "error_node",
                    },
                    "transitions": {
                        "idle": "custom_quality_gate",
                        "custom_quality_gate": "complete",
                    },
                    "nodes": [
                        {"id": "dispatch", "label": "Dispatch", "handler": "runtime.dispatch", "kind": "runtime"},
                        {"id": "idle_node", "label": "Idle", "handler": "runtime.idle", "stage": "idle", "kind": "runtime"},
                        {
                            "id": "custom_quality_gate_node",
                            "label": "Custom Quality Gate",
                            "handler": "runtime.step_complete",
                            "stage": "custom_quality_gate",
                            "kind": "runtime",
                        },
                        {"id": "complete_node", "label": "Complete", "handler": "runtime.terminal", "stage": "complete", "kind": "terminal"},
                        {"id": "error_node", "label": "Error", "handler": "runtime.terminal", "stage": "error", "kind": "terminal"},
                        {"id": "step_complete", "label": "Step Complete", "handler": "runtime.step_complete", "kind": "terminal"},
                    ],
                    "edges": [
                        {"source": "dispatch", "target": "idle_node", "condition": "idle"},
                        {"source": "dispatch", "target": "custom_quality_gate_node", "condition": "custom_quality_gate"},
                        {"source": "dispatch", "target": "complete_node", "condition": "complete"},
                        {"source": "dispatch", "target": "error_node", "condition": "error"},
                        {"source": "idle_node", "target": "step_complete"},
                        {"source": "custom_quality_gate_node", "target": "step_complete"},
                        {"source": "complete_node", "target": "step_complete"},
                        {"source": "error_node", "target": "step_complete"},
                        {
                            "source": "idle_node",
                            "target": "custom_quality_gate_node",
                            "condition": "default",
                            "metadata": {
                                "runtime_edge": "logical_transition",
                                "from_stage": "idle",
                                "to_stage": "custom_quality_gate",
                                "condition": "default",
                                "default_transition": True,
                            },
                        },
                        {
                            "source": "custom_quality_gate_node",
                            "target": "complete_node",
                            "condition": "default",
                            "metadata": {
                                "runtime_edge": "logical_transition",
                                "from_stage": "custom_quality_gate",
                                "to_stage": "complete",
                                "condition": "default",
                                "default_transition": True,
                            },
                        },
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    runtime = LangGraphRunLoop(
        state=OrchestratorState(run_id="run-custom-stage", experiment_id="exp-custom-stage", mode=Mode.TEST),
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator",
        ctx=object(),
        logger=StructuredLogger(tmp_path / "custom_runtime.jsonl", tmp_path / "custom_summary.log"),
        graph_config_path=graph_path,
        module_root=tmp_path / "modules",
    )

    await runtime._idle_node({"state": runtime._state})

    assert runtime._state.stage.value == "custom_quality_gate"
    assert runtime._state.model_dump(mode="json")["stage"] == "custom_quality_gate"


@pytest.mark.asyncio
async def test_langgraph_runtime_executes_custom_agent_stage_from_graph_config(tmp_path: Path) -> None:
    module_dir = tmp_path / "modules" / "custom_quality"
    module_dir.mkdir(parents=True)
    (module_dir / "module.yaml").write_text(
        yaml.safe_dump(
            {
                "module": {
                    "id": "custom_quality",
                    "label": "Custom Quality Gate",
                    "handler": "agent.custom_quality_agent",
                    "editable": True,
                    "safety": {"dry_run_supported": True, "live_requires_validation": True},
                    "tools": [],
                    "io_contract": {"input": "custom test state", "output": "custom quality metrics"},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    graph_path = tmp_path / "custom_agent_stage_graph.yaml"
    graph_path.write_text(
        yaml.safe_dump(
            {
                "graph": {
                    "id": "custom_agent_stage_graph",
                    "name": "Custom Agent Stage Graph",
                    "version": "0.1.0",
                    "entry_node": "dispatch",
                    "finish_nodes": ["step_complete"],
                    "terminal_stages": ["complete", "error"],
                    "stage_dispatch": {
                        "idle": "idle_node",
                        "custom_quality_gate": "custom_quality_gate_node",
                        "complete": "complete_node",
                        "error": "error_node",
                    },
                    "transitions": {
                        "idle": "custom_quality_gate",
                        "custom_quality_gate": "complete",
                    },
                    "nodes": [
                        {"id": "dispatch", "label": "Dispatch", "handler": "runtime.dispatch", "kind": "runtime"},
                        {"id": "idle_node", "label": "Idle", "handler": "runtime.idle", "stage": "idle", "kind": "runtime"},
                        {
                            "id": "custom_quality_gate_node",
                            "label": "Custom Quality Gate",
                            "handler": "agent.custom_quality_agent",
                            "stage": "custom_quality_gate",
                            "kind": "agent",
                            "module_id": "modules/custom_quality",
                        },
                        {"id": "complete_node", "label": "Complete", "handler": "runtime.terminal", "stage": "complete", "kind": "terminal"},
                        {"id": "error_node", "label": "Error", "handler": "runtime.terminal", "stage": "error", "kind": "terminal"},
                        {"id": "step_complete", "label": "Step Complete", "handler": "runtime.step_complete", "kind": "terminal"},
                    ],
                    "edges": [
                        {"source": "dispatch", "target": "idle_node", "condition": "idle"},
                        {"source": "dispatch", "target": "custom_quality_gate_node", "condition": "custom_quality_gate"},
                        {"source": "dispatch", "target": "complete_node", "condition": "complete"},
                        {"source": "dispatch", "target": "error_node", "condition": "error"},
                        {"source": "idle_node", "target": "step_complete"},
                        {"source": "custom_quality_gate_node", "target": "step_complete"},
                        {"source": "complete_node", "target": "step_complete"},
                        {"source": "error_node", "target": "step_complete"},
                        {
                            "source": "idle_node",
                            "target": "custom_quality_gate_node",
                            "condition": "default",
                            "metadata": {
                                "runtime_edge": "logical_transition",
                                "from_stage": "idle",
                                "to_stage": "custom_quality_gate",
                                "condition": "default",
                                "default_transition": True,
                            },
                        },
                        {
                            "source": "custom_quality_gate_node",
                            "target": "complete_node",
                            "condition": "default",
                            "metadata": {
                                "runtime_edge": "logical_transition",
                                "from_stage": "custom_quality_gate",
                                "to_stage": "complete",
                                "condition": "default",
                                "default_transition": True,
                            },
                        },
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    registry = AgentRegistry()
    registry.register(_CustomQualityAgent())  # type: ignore[arg-type]
    runtime = LangGraphRunLoop(
        state=OrchestratorState(
            run_id="run-custom-agent-stage",
            experiment_id="exp-custom-agent-stage",
            mode=Mode.TEST,
            stage=Stage("custom_quality_gate"),
        ),
        agent_registry=registry,
        orchestrator_agent_name="orchestrator",
        ctx=object(),
        logger=StructuredLogger(tmp_path / "custom_agent_runtime.jsonl", tmp_path / "custom_agent_summary.log"),
        graph_config_path=graph_path,
        module_root=tmp_path,
    )

    await runtime.step()

    assert runtime._state.stage == Stage.COMPLETE
    assert runtime._state.run_metadata["custom_quality_gate_agent_payload"]["metrics"]["quality_score"] == 0.97
    assert runtime._state.run_metadata["custom_quality_gate_handoff_packet"]["status"] == "ready"


def test_logical_transition_candidates_drive_runtime_next_stage() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")

    guardian_candidates = config.transition_candidates("guardian")
    assert {candidate["to_stage"] for candidate in guardian_candidates} >= {"design", "complete", "error"}
    assert config.next_stage("guardian", guardian_decision="continue") == "design"
    assert config.next_stage("guardian", guardian_decision="stop") == "complete"
    assert config.next_stage("guardian", guardian_decision="error") == "error"

    payload = config.model_dump(mode="json")
    _add_graph_transition_candidate(payload, "design", "guardian", "next_stage:guardian")
    candidate_config = GraphConfig.model_validate(payload)
    assert candidate_config.next_stage("design") == "specimen"
    assert candidate_config.next_stage("design", state_metadata={"agent_result": {"next_stage": "guardian"}}) == "guardian"


def test_manipulation_has_no_self_retry_transition() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")

    assert all(
        not (
            candidate["to_stage"] == "manipulation"
            and candidate["condition"] == "next_stage:manipulation"
        )
        for candidate in config.transition_candidates("manipulation")
    )


def test_vision_monitoring_reenters_vision_without_restarting_manipulation() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")

    assert config.next_stage(
        "vision",
        state_metadata={"agent_result": {"requested_next_stage": "vision"}},
    ) == "vision"


def test_manipulation_routes_to_vision_before_equipment() -> None:
    """Manipulation always enters Vision; only Vision may release Equipment."""
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")

    assert config.next_stage("manipulation") == "vision"
    assert config.next_stage(
        "vision",
        state_metadata={"agent_result": {"requested_next_stage": "manipulation"}},
    ) == "manipulation"
    assert config.next_stage(
        "vision",
        state_metadata={"agent_result": {"requested_next_stage": "equipment"}},
    ) == "equipment"


def test_module_config_schema_validates_active_modules() -> None:
    module_paths = sorted(Path("graphs/modules").glob("*/module.yaml"))
    assert module_paths
    module_ids = set()
    for module_path in module_paths:
        config = load_module_config(module_path)
        module_ids.add(config.id)
        assert config.handler.startswith("agent.")
        assert config.safety.dry_run_supported is True
        assert config.internal_graph
        assert all(step.id for step in config.internal_graph)

    assert {"design", "specimen", "vision", "manipulation", "equipment", "analysis", "knowledge", "bo", "guardian"}.issubset(module_ids)
    design = load_module_config("graphs/modules/design/module.yaml")
    assert design.pre_execution[0].id == "orchestrator_plan"
    assert design.pre_execution[0].handler == "agent.orchestrator_agent"

    with pytest.raises(Exception):
        ModuleConfig.model_validate({"id": "", "handler": "agent.design_agent"})
    with pytest.raises(Exception):
        ModuleConfig.model_validate({"id": "bad", "handler": ""})
    with pytest.raises(Exception):
        ModuleConfig.model_validate({"id": "bad", "handler": "agent.design_agent", "tools": [""]})


def test_legacy_compatibility_helpers_derive_from_graph_and_module_config(tmp_path: Path) -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")

    assert ordered_stages[:3] == [Stage.DESIGN, Stage.SPECIMEN, Stage.VISION]
    assert Stage.BO in ordered_stages
    assert default_next_stage(Stage.KNOWLEDGE) == Stage.BO
    assert default_next_stage(Stage.BO) == Stage.GUARDIAN
    assert default_next_stage(Stage.GUARDIAN, guardian_decision="stop") == Stage.COMPLETE
    assert stage_to_agent(Stage.DESIGN) == "design_agent"

    payload = config.model_dump(mode="json")
    payload["transitions"]["design"] = "guardian"
    for node in payload["nodes"]:
        if node.get("stage") == "design":
            node["handler"] = "agent.guardian_agent"
            node["module_id"] = None
            break
    graph_path = tmp_path / "compat_graph.yaml"
    graph_path.write_text(yaml.safe_dump({"graph": payload}, sort_keys=False), encoding="utf-8")

    assert default_next_stage(Stage.DESIGN, graph_config_path=graph_path) == Stage.GUARDIAN
    assert OrchestrationGraph(graph_path).next_stage(Stage.DESIGN) == Stage.GUARDIAN
    assert stage_to_agent(Stage.DESIGN, graph_config_path=graph_path) == "guardian_agent"


def test_graph_validator_rejects_missing_handler_missing_edge_node_duplicate_and_unguarded_cycle() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    registry = _noop_registry()

    bad_handler_payload = config.model_dump(mode="json")
    bad_handler_payload["nodes"][0]["handler"] = "runtime.not_registered"
    bad_handler = ATRLangGraphCompiler(GraphConfig.model_validate(bad_handler_payload), registry).validate()
    assert any("unregistered handler" in error for error in bad_handler)

    bad_edge_payload = config.model_dump(mode="json")
    bad_edge_payload["edges"].append({"source": "design", "target": "missing_node", "condition": None})
    bad_edge = ATRLangGraphCompiler(GraphConfig.model_validate(bad_edge_payload), registry).validate()
    assert "edge target is unknown: missing_node" in bad_edge

    duplicate_payload = config.model_dump(mode="json")
    duplicate_payload["nodes"].append(dict(duplicate_payload["nodes"][2]))
    duplicate = ATRLangGraphCompiler(GraphConfig.model_validate(duplicate_payload), registry).validate()
    assert "duplicate node id: design" in duplicate

    cycle_payload = config.model_dump(mode="json")
    cycle_payload["transitions"] = {"design": "specimen", "specimen": "design"}
    cycle = ATRLangGraphCompiler(GraphConfig.model_validate(cycle_payload), registry).validate()
    assert any("transition cycle without guardian/terminal" in error for error in cycle)

    orphan_payload = config.model_dump(mode="json")
    orphan_payload["nodes"].append(
        {
            "id": "orphan",
            "label": "Orphan",
            "handler": "runtime.terminal",
            "stage": None,
            "kind": "runtime",
            "position": {"x": 0, "y": 0},
            "metadata": {},
        }
    )
    orphan_errors = ATRLangGraphCompiler(GraphConfig.model_validate(orphan_payload), registry).validate()
    assert "node is disconnected from entry_node: orphan" in orphan_errors

    module_ids = {str(node.module_id).split("/")[-1] for node in config.nodes if node.module_id}
    bad_module_payload = config.model_dump(mode="json")
    bad_module_payload["nodes"][2]["module_id"] = "modules/missing_module"
    bad_module = ATRLangGraphCompiler(
        GraphConfig.model_validate(bad_module_payload),
        registry,
        module_ids=module_ids,
    ).validate()
    assert "node=design references unknown module=modules/missing_module" in bad_module

    unsafe_payload = config.model_dump(mode="json")
    unsafe_payload["stage_dispatch"].pop("guardian", None)
    unsafe = ATRLangGraphCompiler(GraphConfig.model_validate(unsafe_payload), registry).validate()
    assert "safety.guardian_required is true but guardian stage is not dispatchable" in unsafe

    stage_mismatch_payload = config.model_dump(mode="json")
    stage_mismatch_payload["stage_dispatch"]["design"] = "specimen"
    stage_mismatch = ATRLangGraphCompiler(GraphConfig.model_validate(stage_mismatch_payload), registry).validate()
    assert "stage_dispatch[design] points to node=specimen with stage=specimen" in stage_mismatch

    missing_dispatch_payload = config.model_dump(mode="json")
    missing_dispatch_payload["edges"] = [
        edge
        for edge in missing_dispatch_payload["edges"]
        if not (edge.get("source") == "dispatch" and edge.get("condition") == "design")
    ]
    missing_dispatch = ATRLangGraphCompiler(GraphConfig.model_validate(missing_dispatch_payload), registry).validate()
    assert "runtime.dispatch edge for stage=design must target node=design" in missing_dispatch

    missing_module_ref_payload = config.model_dump(mode="json")
    missing_module_ref_payload["nodes"][2]["module_id"] = None
    missing_module_ref = ATRLangGraphCompiler(GraphConfig.model_validate(missing_module_ref_payload), registry).validate()
    assert "agent node=design must reference module_id" in missing_module_ref

    bad_logical_payload = config.model_dump(mode="json")
    first_logical = next(edge for edge in bad_logical_payload["edges"] if edge.get("metadata", {}).get("runtime_edge") == "logical_transition")
    first_logical["metadata"]["from_stage"] = "missing_stage"
    bad_logical = ATRLangGraphCompiler(GraphConfig.model_validate(bad_logical_payload), registry).validate()
    assert "logical_transition[1] from_stage is not dispatchable or terminal: missing_stage" in bad_logical

    missing_stop_payload = config.model_dump(mode="json")
    missing_stop_payload["edges"] = [
        edge
        for edge in missing_stop_payload["edges"]
        if edge.get("metadata", {}).get("transition_condition") != "guardian_decision:stop"
    ]
    missing_stop = ATRLangGraphCompiler(GraphConfig.model_validate(missing_stop_payload), registry).validate()
    assert "safety.guardian_required is true but guardian stop route to terminal stage is missing" in missing_stop


def test_handler_registry_metadata_and_signature_validation() -> None:
    registry = HandlerRegistry()

    async def good_handler(runtime_state: dict[str, object]) -> dict[str, object]:
        return runtime_state

    def no_args_handler() -> dict[str, object]:
        return {}

    def too_many_required(first: dict[str, object], second: object) -> dict[str, object]:
        return first

    registry.register("runtime.good", good_handler)
    registry.register("runtime.bad_no_args", no_args_handler)
    registry.register("runtime.bad_too_many", too_many_required)

    good = registry.metadata("runtime.good")
    assert good["handler_id"] == "runtime.good"
    assert good["is_async"] is True
    assert good["accepts_runtime_state"] is True
    assert "runtime_state" in good["signature"]
    assert good["errors"] == []

    errors = registry.validation_errors({"runtime.good", "runtime.bad_no_args", "runtime.bad_too_many"})
    assert "handler must accept one runtime_state positional argument" in errors["runtime.bad_no_args"]
    assert any("too many required positional" in error for error in errors["runtime.bad_too_many"])
    assert "runtime.good" not in errors

    with pytest.raises(ValueError):
        registry.register("runtime.not_callable", object())  # type: ignore[arg-type]


def test_graph_validator_rejects_registered_handler_with_invalid_signature() -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    registry = _noop_registry()

    def invalid_handler() -> dict[str, object]:
        return {}

    registry.register("runtime.invalid_signature", invalid_handler)
    payload = config.model_dump(mode="json")
    payload["nodes"][0]["handler"] = "runtime.invalid_signature"
    errors = ATRLangGraphCompiler(GraphConfig.model_validate(payload), registry).validate()

    assert "handler=runtime.invalid_signature invalid runtime signature: handler must accept one runtime_state positional argument" in errors


def test_graph_runtime_api_exposes_validate_and_dry_run() -> None:
    client = TestClient(app_main.app)

    graphs = client.get("/api/graphs").json()
    assert graphs["ok"] is True
    assert graphs["active_graph_id"] == "atr_closed_loop"
    graph_ids = [item["id"] for item in graphs["graphs"]]
    assert graph_ids[0] == "atr_closed_loop"
    assert {"printer_pipeline", "lerobot_pick_place", "utm_test_flow"}.issubset(graph_ids)
    assert all("path" in item and "executable_from_runtime_ide" in item for item in graphs["graphs"])

    validation = client.post("/api/graphs/atr_closed_loop/validate").json()
    assert validation == {"ok": True, "graph_id": "atr_closed_loop", "errors": []}

    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    cursor = _event_cursor()
    draft_validation = client.post(
        "/api/graphs/atr_closed_loop/validate-draft",
        json={"graph": graph, "reason": "unit-draft", "author": "pytest", "activate": False},
    ).json()
    assert draft_validation["ok"] is True
    assert draft_validation["compiled"] is True
    assert draft_validation["errors"] == []
    assert draft_validation["compiled_graph"]["entry_node"] == "dispatch"
    compiled_event = _assert_runtime_event_since(cursor, "graph.compiled", "validate-draft")
    assert compiled_event["payload"]["compiled_graph"]["entry_node"] == "dispatch"

    bad_graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    bad_graph["nodes"][0]["handler"] = "runtime.not_registered"
    cursor = _event_cursor()
    bad_draft = client.post(
        "/api/graphs/atr_closed_loop/validate-draft",
        json={"graph": bad_graph, "reason": "bad-draft", "author": "pytest", "activate": False},
    ).json()
    assert bad_draft["ok"] is False
    failed_event = _assert_runtime_event_since(cursor, "graph.validation_failed", "validate-draft")
    assert any("unregistered handler" in error for error in failed_event["payload"]["errors"])

    cursor = _event_cursor()
    dry_run = client.post("/api/graphs/atr_closed_loop/dry-run").json()
    assert dry_run["ok"] is True
    _assert_runtime_event_since(cursor, "graph.compiled", "dry-run")
    sequence = dry_run["sequence"]
    stages = [item["stage"] for item in sequence]
    assert stages[-3:] == ["knowledge", "bo", "guardian"]
    design_step = next(item for item in sequence if item["stage"] == "design")
    assert design_step["graph_handler"] == "agent.design_agent"
    assert design_step["module_id"] == "design"
    assert design_step["module_handler"] == "agent.design_agent"
    assert design_step["effective_handler"] == "agent.design_agent"
    assert design_step["module_runtime"]["pre_execution_count"] == 1
    assert design_step["module_runtime"]["internal_graph_count"] >= 1
    specimen_step = next(item for item in sequence if item["stage"] == "specimen")
    assert specimen_step["module_runtime"]["tool_count"] >= 1

    replay_dry_run = client.post("/api/graphs/atr_closed_loop/dry-run", json={"start_stage": "analysis", "max_steps": 4}).json()
    assert replay_dry_run["ok"] is True
    assert replay_dry_run["start_stage"] == "analysis"
    assert [item["stage"] for item in replay_dry_run["sequence"]] == ["analysis", "knowledge", "bo", "guardian"]
    draft_dry_run = client.post(
        "/api/graphs/atr_closed_loop/dry-run",
        json={"graph": graph, "start_stage": "design", "max_steps": 3},
    ).json()
    assert draft_dry_run["ok"] is True
    assert draft_dry_run["draft"] is True
    assert draft_dry_run["dry_run_record"]["live_gate_recorded"] is False
    assert [item["stage"] for item in draft_dry_run["sequence"]] == ["design", "specimen", "vision"]

    cursor = _event_cursor()
    printer_compile = client.post("/api/graphs/printer_pipeline/compile").json()
    assert printer_compile["ok"] is True
    assert printer_compile["compiled_graph"]["transitions"]["idle"] == "specimen"
    _assert_runtime_event_since(cursor, "graph.compiled", "compile")

    printer_dry_run = client.post("/api/graphs/printer_pipeline/dry-run").json()
    assert printer_dry_run["ok"] is True
    assert [item["stage"] for item in printer_dry_run["sequence"]] == ["idle", "specimen"]

    lerobot_dry_run = client.post("/api/graphs/lerobot_pick_place/dry-run").json()
    assert lerobot_dry_run["ok"] is True
    assert [item["stage"] for item in lerobot_dry_run["sequence"]] == ["idle", "vision", "manipulation"]

    utm_dry_run = client.post("/api/graphs/utm_test_flow/dry-run").json()
    assert utm_dry_run["ok"] is True
    assert [item["stage"] for item in utm_dry_run["sequence"]] == ["idle", "equipment", "analysis", "knowledge"]


def test_graph_runtime_api_exposes_handlers_modules_and_compile() -> None:
    client = TestClient(app_main.app)

    handlers = client.get("/api/handlers").json()
    assert handlers["ok"] is True
    assert "agent.design_agent" in handlers["handlers"]
    assert "runtime.dispatch" in handlers["handlers"]
    handler_metadata = {item["handler_id"]: item for item in handlers["handler_metadata"]}
    assert set(handlers["handlers"]).issubset(handler_metadata)
    assert handler_metadata["runtime.dispatch"]["accepts_runtime_state"] is True
    assert handler_metadata["runtime.dispatch"]["errors"] == []
    assert "runtime_state" in handler_metadata["runtime.dispatch"]["signature"]

    tools = client.get("/api/tools").json()
    assert tools["ok"] is True
    assert tools["count"] == len(tools["tools"])
    assert "geometry.generate_metamaterial_stl" in tools["tools"]

    modules = client.get("/api/modules").json()
    assert modules["ok"] is True
    module_ids = {item["id"] for item in modules["modules"]}
    assert {"design", "specimen", "bo", "guardian"}.issubset(module_ids)

    manifests = client.get("/api/runtime/agent-manifests").json()
    assert manifests["ok"] is True
    assert manifests["graph_id"] == "atr_closed_loop"
    manifest_by_id = {item["id"]: item for item in manifests["agents"]}
    assert {"orchestrator", "design", "specimen", "guardian"}.issubset(manifest_by_id)
    assert manifest_by_id["objective"]["kind"] == "ui_only"
    assert manifest_by_id["orchestrator"]["module_id"] == "orchestrator"
    assert manifest_by_id["orchestrator"]["graph_node_id"] == "orchestrator_supervisor"
    assert manifest_by_id["design"]["module_id"] == "design"
    assert manifest_by_id["design"]["handler"] == "agent.design_agent"
    assert manifest_by_id["design"]["graph_node_id"] == "design"
    assert manifest_by_id["design"]["io_contract"]
    assert manifest_by_id["design"]["cards"]
    assert manifest_by_id["equipment"]["cards"]
    assert manifest_by_id["guardian"]["cards"]
    assert manifest_by_id["design"]["cards"][0]["id"] == "design_decision_descriptor"
    assert manifest_by_id["design"]["report_sections"][0]["id"] == "design_overview"
    assert manifest_by_id["equipment"]["report_sections"][0]["id"] == "equipment_overview"
    assert manifest_by_id["guardian"]["report_sections"][0]["id"] == "guardian_overview"
    assert manifest_by_id["design"]["chat"]["mode"] == "open_on_demand"
    assert manifest_by_id["equipment"]["chat"]["mode"] == "open_on_demand"
    assert manifest_by_id["guardian"]["chat"]["mode"] == "open_on_demand"
    assert manifest_by_id["design"]["safety"]["live_requires_validation"] is True
    assert manifests["source_endpoints"] == [
        "/api/graphs/atr_closed_loop",
        "/api/modules",
        "/api/runtime/agent-manifests",
    ]

    bridges = client.get("/api/bridges").json()
    assert bridges["ok"] is True
    bridge_by_id = {item["id"]: item for item in bridges["bridges"]}
    assert {"prusa_bridge", "lerobot_bridge", "windows_pyautogui_bridge", "cae_bridge", "camera_utm_bridge"}.issubset(bridge_by_id)
    removed_bridge_id = "fe" + "nicsx_cae_bridge"
    removed_solver_token = "fe" + "nics"
    assert removed_bridge_id not in bridge_by_id
    assert not any(removed_solver_token in str(tool).lower() for bridge in bridge_by_id.values() for tool in bridge.get("tools", []))
    assert bridge_by_id["lerobot_bridge"]["workspace"] == "/lerobot"
    assert "lerobot.rollout.start" in bridge_by_id["lerobot_bridge"]["tools"]
    assert bridge_by_id["windows_pyautogui_bridge"]["health_endpoint"] == "/api/equipment/windows/readiness"
    assert bridge_by_id["windows_pyautogui_bridge"]["workspace"] == "/equipment/windows"
    for bridge_id, bridge in bridge_by_id.items():
        assert bridge["actions"], f"{bridge_id} must expose normalized bridge actions"
        assert bridge["evidence_contracts"], f"{bridge_id} must expose evidence contracts"
        for action in bridge["actions"]:
            assert {"id", "label", "kind", "method", "endpoint", "requires_confirmation", "read_only"}.issubset(action)
    windows_actions = {action["id"]: action for action in bridge_by_id["windows_pyautogui_bridge"]["actions"]}
    assert windows_actions["open_workspace"]["endpoint"] == "/equipment/windows"
    assert windows_actions["open_workspace"]["kind"] == "navigation"
    assert windows_actions["health_check"]["endpoint"] == "/api/equipment/windows/readiness"
    assert windows_actions["preflight"]["endpoint"] == "/api/equipment/windows/live-preflight"

    runtime_state = client.get("/api/runtime/state").json()
    contract_bridges = {
        item["id"]: item
        for item in runtime_state["runtime_ide_contract"]["device_bridges"]
    }
    assert contract_bridges["windows_pyautogui_bridge"]["workspace"] == "/equipment/windows"
    assert contract_bridges["windows_pyautogui_bridge"]["actions"] == bridge_by_id["windows_pyautogui_bridge"]["actions"]

    design = client.get("/api/modules/design").json()
    assert design["ok"] is True
    assert design["module"]["module"]["handler"] == "agent.design_agent"
    assert design["module"]["module"]["internal_graph"]
    assert design["runtime_effect"]["scope"] == "management_workspace"
    assert design["lifecycle"]["graph_attached"] is True
    assert design["lifecycle"]["activation_status"] == "active_graph_attached"
    assert design["lifecycle"]["ready_for_live_activation"] is True
    assert design["lifecycle"]["next_required_action"] == "none"
    assert all(item["ok"] is True for item in design["lifecycle"]["activation_requirements"])

    load_result = client.post("/api/modules/design/load").json()
    assert load_result["ok"] is True
    assert load_result["loaded"] is True
    assert "design" in load_result["loaded_module_ids"]
    assert load_result["runtime_effect"] == {
        "scope": "management_workspace",
        "changes_graph_config": False,
        "changes_runtime_execution": False,
        "requires_validate_dry_run_save_for_activation": True,
    }
    assert load_result["lifecycle"]["module_status"] == "active"
    assert load_result["lifecycle"]["graph_attached"] is True
    assert load_result["lifecycle"]["executable_count"] >= 1
    state_result = client.get("/api/modules/management-state").json()
    assert "design" in state_result["loaded_module_ids"]
    unload_result = client.post("/api/modules/design/unload").json()
    assert unload_result["ok"] is True
    assert unload_result["loaded"] is False
    assert "design" not in unload_result["loaded_module_ids"]
    assert unload_result["runtime_effect"]["changes_runtime_execution"] is False
    assert unload_result["lifecycle"]["graph_attached"] is True

    compiled = client.post("/api/graphs/atr_closed_loop/compile").json()
    assert compiled["ok"] is True
    assert compiled["compiled"] is True
    assert compiled["errors"] == []
    assert compiled["compiled_graph"]["transitions"]["knowledge"] == "bo"
    assert compiled["compiled_graph"]["logical_edge_count"] >= 1
    dispatch_node = next(node for node in compiled["compiled_graph"]["nodes"] if node["id"] == "dispatch")
    assert dispatch_node["handler_signature"]
    assert dispatch_node["handler_accepts_runtime_state"] is True

    module_validation = client.post("/api/modules/design/validate").json()
    assert module_validation == {"ok": True, "module_id": "design", "errors": []}

    module_dry_run = client.post("/api/modules/design/dry-run").json()
    assert module_dry_run["ok"] is True
    assert module_dry_run["sequence"][0]["id"] == "orchestrator_plan"
    assert module_dry_run["sequence"][0]["phase"] == "pre_execution"
    assert module_dry_run["sequence"][0]["executable"] is True
    assert [item["id"] for item in module_dry_run["sequence"][1:3]] == [
        "01_receive_objective_context",
        "02_normalize_objective_contract",
    ]
    assert module_dry_run["sequence"][1]["handler_configured"] is False
    assert module_dry_run["sequence"][1]["executable"] is False
    assert module_dry_run["summary"]["step_count"] == len(module_dry_run["sequence"])
    assert module_dry_run["summary"]["pre_execution_count"] == 1
    assert module_dry_run["summary"]["internal_graph_count"] >= 1
    assert module_dry_run["summary"]["executable_count"] >= 1
    assert module_dry_run["summary"]["ordered_step_ids"][0] == "orchestrator_plan"

    saved_module = client.put(
        "/api/modules/design",
        json={"module": design["module"], "reason": "unit-version-detail", "author": "pytest", "activate": False},
    ).json()
    assert saved_module["ok"] is True
    assert saved_module["dry_run"]["ok"] is True
    assert saved_module["dry_run"]["summary"]["pre_execution_count"] == 1
    assert saved_module["dry_run"]["summary"]["internal_graph_count"] >= 1
    assert saved_module["dry_run"]["summary"]["ordered_step_ids"][0] == "orchestrator_plan"
    module_versions = client.get("/api/modules/design/versions").json()
    assert module_versions["ok"] is True
    assert any(item["version_id"] == saved_module["version"]["version_id"] for item in module_versions["versions"])
    module_version = client.get(f"/api/modules/design/versions/{saved_module['version']['version_id']}").json()
    assert module_version["ok"] is True
    assert module_version["version"]["module"]["module"]["id"] == "design"
    missing_graph_version = client.get("/api/graphs/atr_closed_loop/versions/not-a-real-version")
    assert missing_graph_version.status_code == 404


def test_runtime_module_template_creates_non_executable_draft_manifest() -> None:
    client = TestClient(app_main.app)
    module_id = "unit_draft_template"
    module_dir = app_main.RUNTIME_MODULE_ROOT / module_id
    version_dir = app_main.RUNTIME_MODULE_VERSION_ROOT / module_id
    shutil.rmtree(module_dir, ignore_errors=True)
    shutil.rmtree(version_dir, ignore_errors=True)
    try:
        created = client.post(
            "/api/modules/templates/agent",
            json={"module_id": module_id, "label": "Unit Draft Template", "category": "custom"},
        ).json()
        assert created["ok"] is True
        assert created["module_id"] == module_id
        module = created["module"]["module"]
        assert module["status"] == "draft"
        assert module["enabled"] is False
        assert module["handler"] == "runtime.step_complete"
        assert module["execution"]["capability"] == "ui_only"
        assert module["graph"]["attached"] is False

        draft_detail = client.get(f"/api/modules/{module_id}").json()
        lifecycle = draft_detail["lifecycle"]
        assert lifecycle["activation_status"] == "draft_unattached"
        assert lifecycle["ready_for_live_activation"] is False
        assert lifecycle["management_loaded"] is False
        assert lifecycle["next_required_action"] == "edit_module_contract"
        requirement_by_id = {item["id"]: item for item in lifecycle["activation_requirements"]}
        assert requirement_by_id["edit_module_contract"]["ok"] is False
        assert requirement_by_id["attach_graph_node"]["ok"] is False
        assert requirement_by_id["module_dry_run_executable"]["ok"] is False

        listed = client.get("/api/runtime/agent-manifests").json()
        draft_manifest = next(item for item in listed["agents"] if item["id"] == module_id)
        assert draft_manifest["status"] == "draft"
        assert draft_manifest["enabled"] is False
        assert draft_manifest["execution_capability"] == "ui_only"
        assert draft_manifest["graph_node_id"] == ""

        dry_run = client.post(f"/api/modules/{module_id}/dry-run").json()
        assert dry_run["ok"] is True
        assert dry_run["summary"]["executable_count"] == 0
        assert dry_run["summary"]["draft"] is True
        assert all(item["executable"] is False for item in dry_run["sequence"])

        loaded = client.post(f"/api/modules/{module_id}/load").json()
        assert loaded["ok"] is True
        assert loaded["runtime_effect"]["changes_runtime_execution"] is False
        assert loaded["lifecycle"]["management_loaded"] is True
        assert loaded["lifecycle"]["ready_for_live_activation"] is False
        assert loaded["lifecycle"]["activation_status"] == "draft_unattached"

        ui_before = client.get(f"/api/modules/{module_id}/ui").json()
        assert ui_before["ok"] is True
        assert ui_before["exists"] is True
        updated_ui = {
            "short": "UDT",
            "renderer": {
                "dashboard": "design_reference",
                "report": "design_reference",
                "fallback": "descriptor",
            },
            "chat": {"mode": "open_on_demand"},
            "cards": [
                {
                    "id": "unit_descriptor",
                    "title": "Unit Descriptor",
                    "span": "9",
                    "density": "compact",
                    "priority": "high",
                    "mobile_behavior": "stack",
                    "selectors": {"status": "metadata.status"},
                }
            ],
            "report_sections": [
                {
                    "id": "unit_report_section",
                    "title": "Unit Report Section",
                    "span": "12",
                    "density": "dense",
                    "priority": "critical",
                    "mobile_behavior": "compact",
                    "selectors": {"runtime": "metadata.status"},
                    "chart": {
                        "type": "mini_bar_chart",
                        "items": [
                            {"label": "ready", "value": "metadata.ready_count", "max": 5}
                        ],
                    },
                    "actions": [
                        {"label": "Open Module", "kind": "link", "url": "/module-management"},
                        {
                            "id": "runtime_state_probe",
                            "label": "Runtime State",
                            "kind": "api",
                            "method": "GET",
                            "url": "/api/runtime/state",
                            "read_only": True,
                        },
                        {
                            "id": "string_false_api",
                            "label": "String False API",
                            "kind": "api",
                            "method": "GET",
                            "url": "/api/runtime/state",
                            "read_only": "false",
                        },
                        {
                            "id": "run_windows_program",
                            "label": "Run Windows Program",
                            "kind": "api",
                            "method": "POST",
                            "url": "/api/equipment/windows/run-program",
                            "workspace": "/equipment/windows",
                            "read_only": False,
                            "requires_confirmation": True,
                        },
                        {
                            "id": "start_physical_device",
                            "label": "Start Physical Device",
                            "kind": "device",
                            "method": "POST",
                            "url": "/api/printer/start",
                            "workspace": "/printer",
                            "read_only": False,
                            "requires_confirmation": True,
                        },
                        {"label": "Unsafe API", "kind": "link", "url": "/api/runtime/gpu-clear"},
                    ],
                },
                {
                    "id": "unit_scatter_section",
                    "title": "Unit Scatter Section",
                    "chart": {
                        "type": "scatter_plot",
                        "x_label": "cell size",
                        "y_label": "objective",
                        "points": [
                            {
                                "label": "candidate-a",
                                "x": "metadata.candidate_a.cell_size_mm",
                                "y": "metadata.candidate_a.objective_score",
                                "value": "metadata.candidate_a.objective_score",
                                "tone": "success",
                            }
                        ],
                    },
                },
                {
                    "id": "unit_line_section",
                    "title": "Unit Line Section",
                    "chart": {
                        "type": "line_chart",
                        "y_label": "objective",
                        "points": [
                            {"label": "loop 1", "value": "metadata.loop_1.objective_score", "tone": "info"},
                            {"label": "loop 2", "value": "metadata.loop_2.objective_score", "tone": "success"},
                        ],
                    },
                },
                {
                    "id": "unit_table_section",
                    "title": "Unit Table Section",
                    "chart": {
                        "type": "table",
                        "columns": [
                            {"id": "metric", "label": "Metric", "selector": "metadata.table_row.metric"},
                            {"id": "value", "label": "Value", "selector": "metadata.table_row.value"},
                        ],
                        "rows": [
                            {"id": "selected", "label": "Selected"},
                            {"id": "candidate", "metric": "metadata.candidate_a.cell_size_mm", "value": "metadata.candidate_a.objective_score"},
                        ],
                    },
                },
                {
                    "id": "unit_heatmap_section",
                    "title": "Unit Heatmap Section",
                    "chart": {
                        "type": "heatmap",
                        "x_label": "metric",
                        "y_label": "candidate",
                        "cells": [
                            {"row": "candidate-a", "column": "score", "value": "metadata.candidate_a.objective_score"},
                            {"row": "candidate-a", "column": "risk", "value": "metadata.candidate_a.risk_score", "tone": "warning"},
                        ],
                    },
                },
                {
                    "id": "unit_compound_section",
                    "title": "Unit Compound Section",
                    "chart": {
                        "type": "compound_chart",
                        "layout": "two_column",
                        "panels": [
                            {
                                "id": "trend_panel",
                                "title": "Trend",
                                "chart": {
                                    "type": "line_chart",
                                    "points": [
                                        {"label": "loop 1", "value": "metadata.loop_1.objective_score"},
                                        {"label": "loop 2", "value": "metadata.loop_2.objective_score"},
                                    ],
                                },
                            },
                            {
                                "id": "summary_panel",
                                "title": "Summary",
                                "chart": {
                                    "type": "table",
                                    "columns": [
                                        {"id": "metric", "label": "Metric", "selector": "metadata.table_row.metric"},
                                        {"id": "value", "label": "Value", "selector": "metadata.table_row.value"},
                                    ],
                                    "rows": [
                                        {"id": "selected", "label": "Selected"},
                                    ],
                                },
                            },
                        ],
                    },
                }
            ],
        }
        ui_saved = client.put(
            f"/api/modules/{module_id}/ui",
            json={"ui": updated_ui, "reason": "unit-ui-save", "author": "pytest"},
        ).json()
        assert ui_saved["ok"] is True
        assert ui_saved["manifest"]["renderer"] == {
            "dashboard": "design_reference",
            "report": "design_reference",
            "fallback": "descriptor",
            "supported": True,
            "execution_scope": "presentation_only",
            "blocked_reason": "",
        }
        assert ui_saved["manifest"]["cards"][0]["id"] == "unit_descriptor"
        assert ui_saved["manifest"]["cards"][0]["span"] == 9
        assert ui_saved["manifest"]["cards"][0]["density"] == "compact"
        assert ui_saved["manifest"]["cards"][0]["priority"] == "high"
        assert ui_saved["manifest"]["cards"][0]["mobile_behavior"] == "stack"
        assert ui_saved["manifest"]["cards"][0]["layout_intent"] == {
            "span": 9,
            "density": "compact",
            "priority": "high",
            "mobile_behavior": "stack",
        }
        assert ui_saved["manifest"]["report_sections"][0]["id"] == "unit_report_section"
        saved_section = ui_saved["manifest"]["report_sections"][0]
        assert saved_section["span"] == 12
        assert saved_section["density"] == "dense"
        assert saved_section["priority"] == "critical"
        assert saved_section["mobile_behavior"] == "compact"
        assert saved_section["layout_intent"] == {
            "span": 12,
            "density": "dense",
            "priority": "critical",
            "mobile_behavior": "compact",
        }
        assert saved_section["chart"]["type"] == "mini_bar_chart"
        assert saved_section["chart"]["supported"] is True
        assert saved_section["chart"]["render_mode"] == "mini_bar_chart"
        assert saved_section["chart"]["items"][0]["value"] == "metadata.ready_count"
        assert saved_section["actions"][0]["url"] == "/module-management"
        assert saved_section["actions"][0]["safe_navigation"] is True
        assert saved_section["actions"][0]["execution_scope"] == "navigation_only"
        assert saved_section["actions"][1]["url"] == "/api/runtime/state"
        assert saved_section["actions"][1]["safe_navigation"] is False
        assert saved_section["actions"][1]["execution_scope"] == "read_only_api"
        assert saved_section["actions"][1]["method"] == "GET"
        assert saved_section["actions"][1]["read_only"] is True
        assert saved_section["actions"][1]["live_card_runnable"] is True
        assert saved_section["actions"][1]["blocked_reason"] == ""
        assert saved_section["actions"][2]["url"] == "/api/runtime/state"
        assert saved_section["actions"][2]["safe_navigation"] is False
        assert saved_section["actions"][2]["execution_scope"] == "blocked"
        assert saved_section["actions"][2]["blocked_reason"] == "api_action_must_be_read_only"
        assert saved_section["actions"][3]["url"] == "/api/equipment/windows/run-program"
        assert saved_section["actions"][3]["safe_navigation"] is False
        assert saved_section["actions"][3]["execution_scope"] == "workspace_handoff"
        assert saved_section["actions"][3]["live_card_runnable"] is False
        assert saved_section["actions"][3]["handoff_required"] is True
        assert saved_section["actions"][3]["handoff_workspace"] == "/equipment/windows"
        assert saved_section["actions"][3]["blocked_reason"] == "workspace_handoff_required"
        assert saved_section["actions"][4]["url"] == "/api/printer/start"
        assert saved_section["actions"][4]["safe_navigation"] is False
        assert saved_section["actions"][4]["execution_scope"] == "blocked"
        assert saved_section["actions"][4]["handoff_required"] is False
        assert saved_section["actions"][4]["blocked_reason"] == "physical_device_action_requires_bridge_workspace"
        assert saved_section["actions"][5]["url"] == "/api/runtime/gpu-clear"
        assert saved_section["actions"][5]["safe_navigation"] is False
        assert saved_section["actions"][5]["execution_scope"] == "blocked"
        assert saved_section["actions"][5]["blocked_reason"] == "api_endpoint_not_allowed_in_ui_descriptor"
        scatter_section = ui_saved["manifest"]["report_sections"][1]
        assert scatter_section["chart"]["type"] == "scatter_plot"
        assert scatter_section["chart"]["supported"] is True
        assert scatter_section["chart"]["render_mode"] == "scatter_plot"
        assert scatter_section["chart"]["points"][0]["x"] == "metadata.candidate_a.cell_size_mm"
        assert scatter_section["chart"]["points"][0]["y"] == "metadata.candidate_a.objective_score"
        assert scatter_section["chart"]["points"][0]["label"] == "candidate-a"
        line_section = ui_saved["manifest"]["report_sections"][2]
        assert line_section["chart"]["type"] == "line_chart"
        assert line_section["chart"]["supported"] is True
        assert line_section["chart"]["render_mode"] == "line_chart"
        assert line_section["chart"]["points"][0]["value"] == "metadata.loop_1.objective_score"
        assert line_section["chart"]["points"][1]["label"] == "loop 2"
        table_section = ui_saved["manifest"]["report_sections"][3]
        assert table_section["chart"]["type"] == "table"
        assert table_section["chart"]["supported"] is True
        assert table_section["chart"]["render_mode"] == "table"
        assert table_section["chart"]["columns"][0]["id"] == "metric"
        assert table_section["chart"]["columns"][0]["label"] == "Metric"
        assert table_section["chart"]["columns"][0]["selector"] == "metadata.table_row.metric"
        assert table_section["chart"]["rows"][0]["id"] == "selected"
        assert table_section["chart"]["rows"][1]["metric"] == "metadata.candidate_a.cell_size_mm"
        heatmap_section = ui_saved["manifest"]["report_sections"][4]
        assert heatmap_section["chart"]["type"] == "heatmap"
        assert heatmap_section["chart"]["supported"] is True
        assert heatmap_section["chart"]["render_mode"] == "heatmap"
        assert heatmap_section["chart"]["cells"][0]["row"] == "candidate-a"
        assert heatmap_section["chart"]["cells"][0]["column"] == "score"
        assert heatmap_section["chart"]["cells"][0]["value"] == "metadata.candidate_a.objective_score"
        assert heatmap_section["chart"]["cells"][1]["tone"] == "warning"
        compound_section = ui_saved["manifest"]["report_sections"][5]
        assert compound_section["chart"]["type"] == "compound_chart"
        assert compound_section["chart"]["supported"] is True
        assert compound_section["chart"]["render_mode"] == "compound_chart"
        assert compound_section["chart"]["layout"] == "two_column"
        assert compound_section["chart"]["panels"][0]["id"] == "trend_panel"
        assert compound_section["chart"]["panels"][0]["chart"]["render_mode"] == "line_chart"
        assert compound_section["chart"]["panels"][1]["id"] == "summary_panel"
        assert compound_section["chart"]["panels"][1]["chart"]["render_mode"] == "table"

        ui_after = client.get(f"/api/modules/{module_id}/ui").json()
        assert ui_after["ui"]["renderer"]["dashboard"] == "design_reference"
        assert ui_after["ui"]["renderer"]["execution_scope"] == "presentation_only"
        assert ui_after["ui"]["cards"][0]["layout_intent"]["span"] == 9
        assert ui_after["ui"]["report_sections"][0]["layout_intent"]["span"] == 12
        assert ui_after["ui"]["report_sections"][0]["actions"][1]["execution_scope"] == "read_only_api"
        assert ui_after["ui"]["report_sections"][0]["actions"][2]["execution_scope"] == "blocked"
        assert ui_after["ui"]["report_sections"][0]["actions"][3]["execution_scope"] == "workspace_handoff"
        assert ui_after["ui"]["report_sections"][0]["actions"][4]["blocked_reason"] == "physical_device_action_requires_bridge_workspace"
        assert ui_after["ui"]["report_sections"][0]["actions"][5]["execution_scope"] == "blocked"
        assert ui_after["ui"]["report_sections"][1]["chart"]["render_mode"] == "scatter_plot"
        assert ui_after["ui"]["report_sections"][2]["chart"]["render_mode"] == "line_chart"
        assert ui_after["ui"]["report_sections"][3]["chart"]["render_mode"] == "table"
        assert ui_after["ui"]["report_sections"][4]["chart"]["render_mode"] == "heatmap"
        assert ui_after["ui"]["report_sections"][5]["chart"]["render_mode"] == "compound_chart"
        assert ui_after["ui"]["report_sections"][5]["chart"]["panels"][0]["chart"]["render_mode"] == "line_chart"

        listed_after = client.get("/api/runtime/agent-manifests").json()
        listed_manifest = next(item for item in listed_after["agents"] if item["id"] == module_id)
        assert listed_manifest["renderer"]["dashboard"] == "design_reference"
        assert listed_manifest["renderer"]["execution_scope"] == "presentation_only"
        assert listed_manifest["status"] == "draft"
        assert listed_manifest["enabled"] is False
        assert listed_manifest["chat"]["mode"] == "open_on_demand"
        assert listed_manifest["cards"][0]["id"] == "unit_descriptor"
        assert listed_manifest["cards"][0]["layout_intent"]["density"] == "compact"
        assert listed_manifest["report_sections"][0]["id"] == "unit_report_section"
        assert listed_manifest["report_sections"][0]["chart"]["render_mode"] == "mini_bar_chart"
        assert listed_manifest["report_sections"][0]["actions"][1]["execution_scope"] == "read_only_api"
        assert listed_manifest["report_sections"][0]["actions"][3]["execution_scope"] == "workspace_handoff"
        assert listed_manifest["report_sections"][0]["actions"][4]["blocked_reason"] == "physical_device_action_requires_bridge_workspace"
        assert listed_manifest["report_sections"][5]["chart"]["render_mode"] == "compound_chart"
    finally:
        shutil.rmtree(module_dir, ignore_errors=True)
        shutil.rmtree(version_dir, ignore_errors=True)


def test_module_management_ui_exposes_draft_template_creation() -> None:
    client = TestClient(app_main.app)
    page = client.get("/module-management")
    assert page.status_code == 200
    assert 'id="mm-create-draft-btn"' in page.text
    script = client.get("/static/module_management.js").text
    assert "/api/modules/templates/agent" in script
    assert "createDraftModuleTemplate" in script
    assert "graph unattached" in script
    assert "renderModuleLifecycle" in script
    assert "changes_runtime_execution" in script
    assert "Management-only load" in script
    assert "activation_status" in script
    assert "ready_for_live_activation" in script
    assert "next_required_action" in script
    assert "activation_requirements" in script


def test_graph_runtime_api_exports_and_imports_yaml_drafts() -> None:
    client = TestClient(app_main.app)
    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]

    exported = client.post(
        "/api/graphs/atr_closed_loop/export-yaml",
        json={"graph": graph, "reason": "unit-export", "author": "pytest", "activate": False},
    )

    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/x-yaml")
    assert "graph:" in exported.text
    assert "atr_closed_loop" in exported.text

    cursor = _event_cursor()
    imported = client.post("/api/graphs/atr_closed_loop/import-yaml", json={"yaml_text": exported.text}).json()
    assert imported["ok"] is True
    assert imported["compiled"] is True
    assert imported["graph"]["id"] == "atr_closed_loop"
    assert imported["graph"]["nodes"][0]["position"]
    _assert_runtime_event_since(cursor, "graph.compiled", "import-yaml")

    cursor = _event_cursor()
    invalid = client.post("/api/graphs/atr_closed_loop/import-yaml", json={"yaml_text": "- not-an-object"}).json()
    assert invalid["ok"] is False
    assert invalid["errors"] == ["YAML root must be an object"]
    _assert_runtime_event_since(cursor, "graph.validation_failed", "import-yaml")


def test_runtime_run_artifact_event_compatibility_api_exposes_current_run() -> None:
    client = TestClient(app_main.app)
    snapshot = client.get("/api/state").json()
    resources = snapshot["system_resources"]
    assert "ram" in resources
    assert "gpu" in resources
    assert "status" in resources["ram"]
    assert "status" in resources["gpu"]
    run_id = snapshot["state"]["run_id"]

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["ok"] is True
    assert run["run_id"] == run_id
    assert run["active"] is True

    events = client.get(f"/api/runs/{run_id}/events").json()
    assert events["ok"] is True
    assert events["run_id"] == run_id
    assert isinstance(events["events"], list)

    approval = client.post(
        f"/api/runs/{run_id}/approvals",
        json={"title": "Unit approval", "reason": "test gate", "stage": "guardian", "safety_class": "unit"},
    ).json()
    assert approval["ok"] is True
    approval_id = approval["approval_id"]
    assert approval["pending"][0]["approval_id"] == approval_id

    listed = client.get(f"/api/runs/{run_id}/approvals").json()
    assert listed["ok"] is True
    assert any(item["approval_id"] == approval_id for item in listed["pending"])

    app_main.controller._state.run_metadata["runtime_approvals"] = {
        "unit-gate": {"approval_id": approval_id, "status": "pending", "stage": "guardian"}
    }
    app_main.controller._state.run_metadata["approval_blocked_stage"] = {"approval_id": approval_id}
    app_main.controller._state.is_paused = True
    resolved = client.post(
        f"/api/runs/{run_id}/approvals/{approval_id}/resolve",
        json={"decision": "approved", "operator": "pytest", "note": "unit pass"},
    ).json()
    assert resolved["ok"] is True
    assert not any(item["approval_id"] == approval_id for item in resolved["pending"])
    assert any(item["approval_id"] == approval_id and item["decision"] == "approved" for item in resolved["resolved"])
    assert app_main.controller._state.run_metadata["runtime_approvals"]["unit-gate"]["status"] == "approved"
    assert app_main.controller._state.is_paused is False
    app_main.controller._state.run_metadata.pop("runtime_approvals", None)

    run_dir = Path(str(run["run_dir"]))
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_file = run_dir / "runtime_ide_preview_test.txt"
    artifact_file.write_text("artifact preview body", encoding="utf-8")
    try:
        artifacts = client.get(f"/api/runs/{run_id}/artifacts").json()
        assert artifacts["ok"] is True
        assert artifacts["run_id"] == run_id
        assert isinstance(artifacts["artifacts"], list)
        artifact = next(item for item in artifacts["artifacts"] if item["path"] == "runtime_ide_preview_test.txt")
        assert artifact["preview_kind"] == "text"
        assert artifact["previewable"] is True
        assert artifact["url"].endswith("/runtime_ide_preview_test.txt")
        assert artifact["download_url"].endswith("/runtime_ide_preview_test.txt?download=1")

        preview = client.get(str(artifact["url"]))
        assert preview.status_code == 200
        assert preview.text == "artifact preview body"

        download = client.get(str(artifact["download_url"]))
        assert download.status_code == 200
        assert "attachment" in download.headers.get("content-disposition", "")
    finally:
        artifact_file.unlink(missing_ok=True)


def test_graph_run_endpoint_compile_checks_then_delegates_controller_start(monkeypatch) -> None:
    async def _fake_start(**kwargs: object) -> dict[str, object]:
        return {"ok": True, "message": "fake started", "run_id": "run-fake", "received": kwargs}

    monkeypatch.setattr(app_main.controller, "start", _fake_start)
    app_main._RUNTIME_GRAPH_DRY_RUN_RECORDS.clear()
    client = TestClient(app_main.app)

    cursor = _event_cursor()
    result = client.post("/api/graphs/atr_closed_loop/run", json={"mode": "test", "goal": "unit graph run"}).json()

    assert result["ok"] is True
    _assert_runtime_event_since(cursor, "graph.compiled", "run")
    assert result["graph_id"] == "atr_closed_loop"
    assert result["errors"] == []
    assert result["run"]["run_id"] == "run-fake"
    assert result["run"]["received"]["mode"] == "test"
    assert result["run"]["received"]["graph_id"] == "atr_closed_loop"
    assert str(result["run"]["received"]["graph_config_path"]).endswith("graphs/configs/atr_closed_loop.yaml")

    live_without_dry_run = client.post("/api/graphs/atr_closed_loop/run", json={"mode": "live", "goal": "unit live gate"})
    assert live_without_dry_run.status_code == 409
    assert live_without_dry_run.json()["detail"]["code"] == "GRAPH_DRY_RUN_REQUIRED"
    gate_before = client.get("/api/graphs/atr_closed_loop/dry-run-gate").json()
    assert gate_before["ok"] is True
    assert gate_before["gate_ok"] is False
    assert gate_before["has_record"] is False

    dry_run = client.post("/api/graphs/atr_closed_loop/dry-run").json()
    assert dry_run["ok"] is True
    assert dry_run["dry_run_record"]["graph_id"] == "atr_closed_loop"
    assert dry_run["dry_run_record"]["digest"]
    assert dry_run["dry_run_record"]["live_gate_recorded"] is True

    gate_after = client.get("/api/graphs/atr_closed_loop/dry-run-gate").json()
    assert gate_after["gate_ok"] is True
    assert gate_after["dry_run_record"]["digest"] == dry_run["dry_run_record"]["digest"]

    live_result = client.post("/api/graphs/atr_closed_loop/run", json={"mode": "live", "goal": "unit live after dry run"}).json()
    assert live_result["ok"] is True
    assert live_result["run"]["received"]["mode"] == "live"
    assert live_result["dry_run_record"]["digest"] == dry_run["dry_run_record"]["digest"]

    app_main._RUNTIME_GRAPH_DRY_RUN_RECORDS.clear()
    legacy_live_without_dry_run = client.post("/api/run/start", json={"mode": "live", "goal": "legacy live gate"})
    assert legacy_live_without_dry_run.status_code == 409
    client.post("/api/graphs/atr_closed_loop/dry-run")
    legacy_live_result = client.post("/api/run/start", json={"mode": "live", "goal": "legacy live after dry run"}).json()
    assert legacy_live_result["ok"] is True
    assert legacy_live_result["received"]["mode"] == "live"

    template_result = client.post("/api/graphs/printer_pipeline/run", json={"mode": "test", "goal": "unit template run"}).json()
    assert template_result["ok"] is True
    assert template_result["graph_id"] == "printer_pipeline"
    assert template_result["run"]["received"]["graph_id"] == "printer_pipeline"
    assert str(template_result["run"]["received"]["graph_config_path"]).endswith("graphs/configs/printer_pipeline.yaml")

    template_live = client.post("/api/graphs/printer_pipeline/run", json={"mode": "live", "goal": "unit template live"})
    assert template_live.status_code == 400
    assert "live run is disabled" in template_live.json()["detail"]


def test_graph_runtime_api_saves_version_without_activating(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_VERSION_ROOT", tmp_path / "graph_versions")
    client = TestClient(app_main.app)
    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]

    cursor = _event_cursor()
    saved = client.put(
        "/api/graphs/atr_closed_loop",
        json={"graph": graph, "reason": "unit-test", "author": "pytest", "activate": False},
    ).json()

    assert saved["ok"] is True
    _assert_runtime_event_since(cursor, "graph.compiled", "save")
    assert saved["activated"] is False
    assert saved["dry_run"]["ok"] is True
    assert saved["dry_run"]["dry_run_record"]["live_gate_recorded"] is False
    assert saved["dry_run"]["dry_run_record"]["digest"]
    assert saved["dry_run"]["dry_run_record"] == saved["dry_run_record"]
    assert [item["stage"] for item in saved["dry_run"]["sequence"][:3]] == ["idle", "design", "specimen"]
    version = saved["version"]
    assert version["reason"] == "unit-test"
    assert (tmp_path / "graph_versions" / "atr_closed_loop" / f"{version['version_id']}.yaml").exists()

    versions = client.get("/api/graphs/atr_closed_loop/versions").json()
    assert versions["ok"] is True
    assert versions["versions"][0]["version_id"] == version["version_id"]

    printer_graph = client.get("/api/graphs/printer_pipeline").json()["graph"]
    printer_saved = client.put(
        "/api/graphs/printer_pipeline",
        json={"graph": printer_graph, "reason": "unit-template-test", "author": "pytest", "activate": False},
    ).json()
    assert printer_saved["ok"] is True
    assert (tmp_path / "graph_versions" / "printer_pipeline" / f"{printer_saved['version']['version_id']}.yaml").exists()


def test_activated_graph_version_becomes_saved_run_target(tmp_path, monkeypatch) -> None:
    config_root = tmp_path / "graph_configs"
    config_root.mkdir()
    active_graph_path = config_root / "atr_closed_loop.yaml"
    active_graph_path.write_text(Path("graphs/configs/atr_closed_loop.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_CONFIG_ROOT", config_root)
    monkeypatch.setattr(app_main, "RUNTIME_GRAPH_VERSION_ROOT", tmp_path / "graph_versions")
    app_main._RUNTIME_GRAPH_DRY_RUN_RECORDS.clear()

    async def _fake_start(**kwargs: object) -> dict[str, object]:
        return {"ok": True, "message": "fake active graph started", "run_id": "run-active-graph", "received": kwargs}

    monkeypatch.setattr(app_main.controller, "start", _fake_start)
    client = TestClient(app_main.app)
    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    _set_graph_default_transition(graph, "design", "guardian")

    cursor = _event_cursor()
    saved = client.put(
        "/api/graphs/atr_closed_loop",
        json={"graph": graph, "reason": "activate-design-to-guardian", "author": "pytest", "activate": True},
    ).json()

    assert saved["ok"] is True
    assert saved["activated"] is True
    assert saved["compiled_graph"]["transitions"]["design"] == "guardian"
    assert saved["dry_run"]["dry_run_record"]["live_gate_recorded"] is True
    assert [item["stage"] for item in saved["dry_run"]["sequence"][:3]] == ["idle", "design", "guardian"]
    _assert_runtime_event_since(cursor, "graph.compiled", "save")

    active = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    assert active["transitions"]["design"] == "guardian"
    assert "design: guardian" in active_graph_path.read_text(encoding="utf-8")

    gate = client.get("/api/graphs/atr_closed_loop/dry-run-gate").json()
    assert gate["gate_ok"] is True
    assert gate["dry_run_record"]["digest"] == saved["dry_run_record"]["digest"]

    dry_run = client.post("/api/graphs/atr_closed_loop/dry-run", json={"max_steps": 5}).json()
    assert dry_run["ok"] is True
    assert dry_run["compiled_graph"]["transitions"]["design"] == "guardian"
    assert [item["stage"] for item in dry_run["sequence"][:3]] == ["idle", "design", "guardian"]

    run = client.post("/api/graphs/atr_closed_loop/run", json={"mode": "live", "goal": "active config route"}).json()
    assert run["ok"] is True
    assert run["compiled_graph"]["transitions"]["design"] == "guardian"
    assert run["dry_run_record"]["digest"] == dry_run["dry_run_record"]["digest"]
    assert run["run"]["received"]["graph_config_path"] == str(active_graph_path)
    assert run["run"]["received"]["mode"] == "live"


def test_module_runtime_api_saves_version_without_activating(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_VERSION_ROOT", tmp_path / "module_versions")
    client = TestClient(app_main.app)
    module = client.get("/api/modules/design").json()["module"]

    saved = client.put(
        "/api/modules/design",
        json={"module": module, "reason": "unit-module-test", "author": "pytest", "activate": False},
    ).json()

    assert saved["ok"] is True
    assert saved["activated"] is False
    assert saved["dry_run"]["ok"] is True
    assert saved["dry_run"]["summary"]["step_count"] == len(saved["dry_run"]["sequence"])
    assert saved["dry_run"]["summary"]["first_step_id"] == "orchestrator_plan"
    version = saved["version"]
    assert version["reason"] == "unit-module-test"
    assert (tmp_path / "module_versions" / "design" / f"{version['version_id']}.yaml").exists()

    versions = client.get("/api/modules/design/versions").json()
    assert versions["ok"] is True
    assert versions["versions"][0]["version_id"] == version["version_id"]


def test_activated_module_version_changes_runtime_handler(tmp_path, monkeypatch) -> None:
    graph_root = tmp_path / "graphs"
    config_root = graph_root / "configs"
    module_root = graph_root / "modules"
    config_root.mkdir(parents=True)
    (config_root / "atr_closed_loop.yaml").write_text(Path("graphs/configs/atr_closed_loop.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(Path("graphs/modules"), module_root)
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_ROOT", module_root)
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_VERSION_ROOT", tmp_path / "module_versions")

    client = TestClient(app_main.app)
    module = client.get("/api/modules/design").json()["module"]
    module["module"]["handler"] = "agent.guardian_agent"

    saved = client.put(
        "/api/modules/design",
        json={"module": module, "reason": "activate-handler-override", "author": "pytest", "activate": True},
    ).json()

    assert saved["ok"] is True
    assert saved["activated"] is True
    assert saved["dry_run"]["summary"]["internal_graph_count"] == 12
    active = client.get("/api/modules/design").json()["module"]
    assert active["module"]["handler"] == "agent.guardian_agent"
    assert "agent.guardian_agent" in (module_root / "design" / "module.yaml").read_text(encoding="utf-8")

    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {"plan_text": "module api plan"})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "wrong-module"}})
    guardian = _StaticAgent("guardian_agent", {"experiment_spec": {"specimen_id": "active-module-handler"}})
    registry.register(orchestrator)
    registry.register(design)
    registry.register(guardian)
    bundle = build_logger_bundle(run_id="run-module-api-active", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-module-api-active",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path=config_root / "atr_closed_loop.yaml",
        module_root=graph_root,
        on_event=events.append,
    )

    asyncio.run(loop.step())

    assert orchestrator.run_count == 1
    assert design.run_count == 0
    assert guardian.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "active-module-handler"}
    started = [event for event in events if event["type"] == "node.started" and event["node_id"] == "design"]
    assert started[-1]["agent"] == "guardian_agent"
    assert started[-1]["payload"]["module_runtime"]["effective_handler"] == "agent.guardian_agent"


def test_module_runtime_api_rejects_unregistered_handler(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_VERSION_ROOT", tmp_path / "module_versions")
    client = TestClient(app_main.app)
    module = client.get("/api/modules/design").json()["module"]
    module["module"]["handler"] = "agent.not_registered"

    saved = client.put(
        "/api/modules/design",
        json={"module": module, "reason": "bad-handler", "author": "pytest", "activate": False},
    ).json()

    assert saved["ok"] is False
    assert saved["errors"] == ["unregistered handler: agent.not_registered"]
    assert saved["dry_run"]["ok"] is False
    assert saved["dry_run"]["summary"]["step_count"] == 0


def test_module_runtime_api_validates_llm_prompt_tool_safety_config() -> None:
    client = TestClient(app_main.app)
    module = client.get("/api/modules/design").json()["module"]
    module["module"].update(
        {
            "llm_role": "design_reasoning",
            "llm": {"backend": "vllm", "model": "gemma4:e4b-it-nvfp4", "temperature": 0.2, "max_tokens": 1024},
            "prompt": {"path": "docs/runtime/design_prompt.md", "system": "Generate printable TPMS specimens."},
            "tools": ["experiment.evaluate", "geometry.generate_metamaterial_stl"],
            "timeout_s": 120,
            "retry": {"max_attempts": 2, "backoff_s": 1.5},
            "safety": {"live_requires_validation": True, "dry_run_supported": True, "requires_human_approval": False},
        }
    )
    module["module"]["internal_graph"][0]["handler"] = "agent.design_agent"

    valid = client.post(
        "/api/modules/design/validate",
        json={"module": module, "reason": "valid-config", "author": "pytest", "activate": False},
    ).json()
    assert valid == {"ok": True, "module_id": "design", "errors": []}

    bad = client.get("/api/modules/design").json()["module"]
    bad["module"].update(
        {
            "llm": {"backend": 7, "max_tokens": 0},
            "prompt": {"path": 12},
            "tools": ["experiment.evaluate", "", "missing.tool"],
            "timeout_s": -1,
            "retry": {"max_attempts": 99},
            "safety": {"live_requires_validation": "yes"},
        }
    )
    bad["module"]["internal_graph"][0]["handler"] = "agent.not_registered"

    invalid = client.post(
        "/api/modules/design/validate",
        json={"module": bad, "reason": "invalid-config", "author": "pytest", "activate": False},
    ).json()
    assert invalid["ok"] is False
    assert "llm.backend must be a string" in invalid["errors"]
    assert "llm.max_tokens must be a positive integer" in invalid["errors"]
    assert "prompt.path must be a string" in invalid["errors"]
    assert "tools[2] must be a non-empty string" in invalid["errors"]
    assert "unregistered tool: missing.tool" in invalid["errors"]
    assert "timeout_s must be a non-negative number" in invalid["errors"]
    assert "retry.max_attempts must be an integer between 0 and 10" in invalid["errors"]
    assert "safety.live_requires_validation must be boolean" in invalid["errors"]
    assert "unregistered internal_graph step handler at 1: agent.not_registered" in invalid["errors"]


def test_runtime_ide_page_and_main_entry_render() -> None:
    client = TestClient(app_main.app)

    home = client.get("/")
    assert home.status_code == 200
    assert "Open Runtime IDE" in home.text

    ide = client.get("/ide")
    assert ide.status_code == 200
    assert "ATR Runtime IDE" in ide.text
    assert "/static/runtime_ide.js" in ide.text
    assert "runtime_ide.js?v=" in ide.text
    assert "ide-run-status" in ide.text
    assert "ide-run-id" in ide.text
    assert "ide-active-agent" in ide.text
    assert "ide-current-stage" in ide.text
    assert "ide-node-search" in ide.text
    assert "ide-node-list" in ide.text
    assert "ide-infra-list" in ide.text
    assert "ide-template-list" in ide.text
    assert "Module Library" in ide.text
    assert "runtime_ide.css?v=" in ide.text
    assert "ide-module-management-open-btn" in ide.text
    assert "data-open-module-management" in ide.text
    assert "Open Module Management Tool" in ide.text
    assert "ide-agent-status" in ide.text
    assert "ide-device-status" in ide.text
    assert "ide-metrics-panel" in ide.text
    assert "ide-approval-queue" in ide.text
    assert "Human Approval Queue" in ide.text
    assert "ide-pause-run-btn" in ide.text
    assert "ide-resume-run-btn" in ide.text
    assert "ide-stop-run-btn" in ide.text
    assert "ide-node-inspector" in ide.text
    assert "ide-transition-source" in ide.text
    assert "ide-transition-target" in ide.text
    assert "ide-transition-condition-preset" in ide.text
    assert "ide-transition-condition" in ide.text
    assert "ide-edge-route-preview" in ide.text
    assert "Request next stage" in ide.text
    assert "ide-edge-connect-btn" in ide.text
    assert "ide-edge-delete-btn" in ide.text
    assert "ide-live-status" in ide.text
    assert "ide-runtime-readiness" in ide.text
    assert "Readiness" in ide.text
    assert "ide-minimap" in ide.text
    assert "ide-zoom-in-btn" in ide.text
    assert "ide-fit-graph-btn" in ide.text
    assert "ide-draft-safety-strip" in ide.text
    assert "ide-run-launcher-drawer" in ide.text
    assert "ide-run-target-summary" in ide.text
    assert "Run Saved Test" in ide.text
    assert "Run Saved Live" in ide.text
    assert "runtime-draft-safety-strip" in ide.text
    assert "ide-canvas-view-hint" in ide.text
    assert "ide-export-yaml-btn" in ide.text
    assert "ide-import-yaml-btn" in ide.text
    assert "ide-yaml-import-file" in ide.text
    assert "ide-live-preflight" in ide.text
    assert "ide-run-timeline" in ide.text
    assert "ide-event-detail" in ide.text
    assert "Event Detail" in ide.text
    assert "runtime-ide-runtime-detail-grid" in ide.text
    assert "ide-artifact-lineage" in ide.text
    assert "ide-artifact-preview" in ide.text
    assert "ide-replay-output" in ide.text
    assert "Event Log" in ide.text
    assert "data-event-filter=\"all\"" in ide.text
    assert "data-event-filter=\"warn\"" in ide.text
    assert "ide-module-graph" in ide.text
    assert "Module Runtime Steps" in ide.text

    management = client.get("/module-management")
    assert management.status_code == 200
    assert "Module Management Tool" in management.text
    assert "mm-load-btn" in management.text
    assert "mm-unload-btn" in management.text
    assert "mm-config-summary" in management.text
    assert "mm-config-steps" in management.text
    assert "mm-config-json" in management.text
    assert "mm-versions-btn" in management.text
    assert "mm-version-output" in management.text
    assert "mm-dry-run-evidence" in management.text
    assert "Dry-run Evidence" in management.text
    assert "Module Version History" in management.text
    assert "mm-register-generated-btn" in management.text
    assert "Register Generated" in management.text
    assert "Module Configuration Workspace" in management.text
    assert "module-management-config-nav" in management.text
    assert "data-mm-config-jump" in management.text
    assert "edit config below, then validate/dry-run before Save Version" in management.text
    assert "/static/module_management.js" in management.text
    assert "module_management.js?v=atr-ui-20260526-82" in management.text

    js = Path("web/static/runtime_ide.js").read_text(encoding="utf-8")
    module_js = Path("web/static/module_management.js").read_text(encoding="utf-8")
    css = Path("web/static/runtime_ide.css").read_text(encoding="utf-8")
    planning_js = Path("web/static/planning.js").read_text(encoding="utf-8")
    browser_audit = Path("tests/ui/runtime_ide_browser_audit.py").read_text(encoding="utf-8")
    planning_browser_audit = Path("tests/ui/planning_browser_audit.py").read_text(encoding="utf-8")
    module_management_browser_audit = Path("tests/ui/module_management_browser_audit.py").read_text(encoding="utf-8")
    assert "GRAPH_GRID = 16" in js
    assert "beginNodeDrag" in js
    assert "handleGraphNodeClick" in js
    assert "toggleEdgeConnectMode" in js
    assert "deleteSelectedEdge" in js
    assert "expandedNodeElementFromPoint" in js
    assert "highlightEdgeDragTarget" in js
    assert "connect-target" in js
    assert "handleRuntimeIdeKeydown" in js
    assert "transitionConditionSpec" in js
    assert "conditionPresetFromCondition" in js
    assert "setTransitionConditionControls" in js
    assert "renderEdgeRoutePreview" in js
    assert "routeConditionExplanation" in js
    assert "defaultTargetAlreadyRepresented" in js
    assert "simpleDefaultLabel" in js
    assert "runtime-ide-node-route-count" in js
    assert "next_stage:${targetStage}" in js
    assert "next_stage:${stage}" in js
    assert "renderMiniMap" in js
    assert "fitGraphToCanvas" in js
    assert "graphViewportCoverage" in js
    assert "graphRouteDiff" in js
    assert "routeDiffMarkup" in js
    assert "baselineGraph" in js
    assert "Draft route changes" in js
    assert "renderModuleGraph" in js
    assert "normalizeGraphTabId" in js
    assert "runtimeIdeStateSnapshot" in js
    assert "selectedNodeExists" in js
    assert "nodes.some((node) => node.id === selectedNodeId)" in js
    assert "syncRuntimeIdeState" in js
    assert "window.atrRuntimeIdeState" in js
    assert "graphTabsOutput.dataset.activeGraphTab" in js
    assert "data-tab-active" in js
    assert "aria-selected" in js
    assert 'role="tab"' in js
    assert 'clean === "main"' in js
    assert "`${MODULE_TAB_PREFIX}${clean}`" in js
    assert "runtime-module-tab-copy" in js
    assert "runtime-module-agent-title" in js
    assert "compactBoParamValue" in planning_js
    assert "renderBoTraceSvg" in planning_js
    assert "renderBoCollapsedBody" in planning_js
    assert "bo-graph-toggle" in planning_js
    assert "renderBoResultCard(msg, `chat-${messageIndex}`)" in planning_js
    assert "renderFemContourCard(msg)" in planning_js
    assert "BO Surrogate / Acquisition Trace" in planning_js
    assert "FEM / CAE Contour" in planning_js
    assert "planning_browser_audit_live_artifacts.png" in planning_browser_audit
    assert "boSvgCount" in planning_browser_audit
    assert "fem-contour-preview" in planning_browser_audit
    assert "module_management_browser_audit.png" in module_management_browser_audit
    assert "registerGeneratedSelected" in module_js
    assert "/register-generated" in module_js
    assert "generated_adapter_approved" in module_js
    assert "Module Designer controls missing" in module_management_browser_audit
    assert "runtime.step_complete missing from designer handler options" in module_management_browser_audit
    assert "dry-run action did not report OK" in module_management_browser_audit
    assert "openModuleManagementTool" in js
    assert "window.open(\"/module-management\", \"_blank\")" in js
    assert "[data-open-module-management]" in js
    assert "Pre-Execution" in js
    assert "moduleStepsForPhase" in js
    assert "updateModuleStepField" in js
    assert "Cross-phase drag is disabled" in js
    assert "data-module-step-field" in js
    assert "pre_execution" in js
    assert "reorderModuleStep" in js
    assert "exportGraphYaml" in js
    assert "importGraphYamlFile" in js
    assert "updateModuleHandler" in js
    assert "updateModuleStepHandler" in js
    assert "updateModuleConfigFromForm" in js
    assert "ide-module-tools" in js
    assert "ide-module-llm-backend" in js
    assert "ide-module-prompt-system" in js
    assert "renderRuntimeHeader" in js
    assert "systemResources" in js
    assert "resourceMetricLevel" in js
    assert "Host RAM" in js
    assert "GPU / VRAM" in js
    assert 'metricCard("VRAM"' in js
    assert "renderGraphExplorer" in js
    assert "renderInfraList" in js
    assert "renderAgentStatusPanel" in js
    assert "renderDeviceStatusPanel" in js
    assert "renderMetricsPanel" in js
    assert "renderApprovalQueue" in js
    assert "renderDashboardPanels" in js
    assert "renderRuntimeReadinessPanel" in js
    assert "refreshRuntimeReadinessViews" in js
    assert "runtimeReadinessHandlerCard" in js
    assert "runtimeReadinessModuleCard" in js
    assert "runtimeReadinessStatus" in js
    assert "moduleDraftReady" in js
    assert "modulePreflight" in js
    assert "modulePayloadForGraphDraft(draft)" in js
    assert "setModulePreflightEvidence" in js
    assert "markModulePreflightDirty" in js
    assert "renderRuntimeReadinessPanel();" in js
    assert "!status.moduleTab && !status.preflight.gateOk" in js
    assert "module draft only" in js
    assert "save-module" in js
    assert "Validate Module" in js
    assert "Dry Run Module" in js
    assert "entryStages" in js
    assert "needsIncoming" in js
    assert "needsOutgoing" in js
    assert "finishNode ? [finishNode.id] : []" in js
    assert "terminal_stages: finishNode ? [finishNode.stage] : []" in js
    assert "runtimeReadinessNodeIssueMap" in js
    assert "runtimeReadinessIssueLabel" in js
    assert "executeRuntimeReadinessAction" in js
    assert "focusRuntimeReadinessIssue" in js
    assert "focusTransitionEditorForNode" in js
    assert "routeRepairTargetForStage" in js
    assert "transitionTargetOptionExists" in js
    assert "focusModuleManagementEntryForNode" in js
    assert "data-readiness-kind" in js
    assert "data-readiness-node" in js
    assert "renderSelectedEventDetail" in js
    assert "nodeRouteAuditMarkup" in js
    assert "nodeRuntimeRecoveryMarkup" in js
    assert "nodeRecoveryStatus" in js
    assert "bindNodeRecoveryActions" in js
    assert "Runtime Recovery" in js
    assert "data-node-recovery-action" in js
    assert "bindNodeRouteAuditActions" in js
    assert "Runtime Routes" in js
    assert "effectiveMakeDefault" in js
    assert "already targets" in js
    assert "runtime-ide-tab-state" in css
    assert "grid-template-columns: minmax(0, 1fr) auto auto" in css
    assert "runtime-node-route-audit" in css
    assert "runtime-node-recovery" in css
    assert "runtime-node-recovery-actions" in css
    assert "runtime-readiness-panel" in css
    assert "runtime-readiness-kpis" in css
    assert "runtime-node-readiness-badge" in css
    assert "readiness-error" in css
    assert "runtime-readiness-focus" in css
    assert "eventRemediationMarkup" in js
    assert "focusApprovalQueueItem" in js
    assert "approvalResolutionForEvent" in js
    assert "preserveSelectedEventId" in js
    assert "Approval Status" in js
    assert "Focus Approval Queue" in js
    assert "data-approval-item-id" in js
    assert "runtime-remediation-focus-approval" in css
    assert "runtime-event-approval-status" in css
    assert "module-management-list-state" in css
    assert "Select only" in module_js
    assert "chips refocus a loaded module" in module_js
    assert "jumpToConfigSection" in module_js
    assert "module-management-jump-focus" in css
    assert "module-management-config-nav" in css
    assert "Recommended next actions" in js
    assert "runtime-event-remediation" in css
    assert "runtime-event-console-inspect" in css
    assert "selectedEventDecisionStripMarkup" in js
    assert "selectedTransitionSummary" in js
    assert "Route Decision" in js
    assert "Replay Basis" in js
    assert "replayValidationMarkup" in js
    assert "Replay matches selected event" in js
    assert "runtime-replay-validation" in css
    assert "renderModuleTraceMarkup" in js
    assert "moduleTraceEventsForStage" in js
    assert "mergeRuntimeEventState" in js
    assert "activeEvent = recentRuntimeEvents.find((event) => eventUpdatesActiveStage(event))" in js
    assert "if (activeGraph) renderGraph(parseGraphEditor())" in js
    assert "eventUpdatesActiveStage" in js
    assert "type.startsWith(\"graph.\")" in js
    assert "Module Step Trace" in js
    assert "active module step" in js
    assert "nodeSchemaStatus" in js
    assert "nodeCodeMapping" in js
    assert "I/O Contract" in js
    assert "Code Mapping" in js
    assert "handlerMetadataStatus" in js
    assert "handlerSignatureText" in js
    assert "availableHandlerMetadata" in js
    assert "handler_metadata" in js
    assert "Graph signature" in js
    assert "Effective signature" in js
    assert "Invalid graph handler signature" in js
    assert "runtime-handler-signature" in css
    assert "runtime-handler-row" in css
    assert "data-node-dry-run-stage" in js
    assert "timelineStats" in js
    assert "renderEventLog" in js
    assert "eventConsoleSeverity" in js
    assert "runtimeEventConsoleRows" in js
    assert "data-event-log-event-id" in js
    assert "artifactStageFromPath" in js
    assert "workspaceStages" in js
    assert 'bo: "bo"' in js
    assert 'cae: "analysis"' in js
    assert "artifactRelatedEvent" in js
    assert "artifactProvenanceMarkup" in js
    assert "Replay Producer Stage" in js
    assert "runtime-artifact-provenance-strip" in css
    assert "loadGraphVersions" in js
    assert "loadGraphVersionDraft" in js
    assert "renderActivationChecklist" in js
    assert "activationCompiledGraphDetailMarkup" in js
    assert "activationDryRunDetailMarkup" in js
    assert "runtime-activation-table" in js
    assert "Default Runtime Routes" in js
    assert "markActivationDirty" in js
    assert "runtime_ide_compile_draft" in js
    assert "recordActiveDryRunGate" in js
    assert "server save preflight" in js
    assert "dry-run gate" in js
    assert "loadGraphDryRunGate" in js
    assert "livePreflightStatus" in js
    assert "runPreflightTargetStripMarkup" in js
    assert "syncRunLauncherControls" in js
    assert "Preflight status remains authoritative" in js
    assert "Execution Target" in js
    assert "runTestBtn.disabled" in js
    assert "runLiveBtn.disabled" in js
    assert "recordLiveGateBtn.disabled = !canRecordGate" in js
    assert "Run is only available from the Main System graph tab." in js
    assert "Unsaved draft route/config changes are present. Validate and Save Version first." in js
    assert "Run will execute the saved active graph config, not unsaved editor drafts." in js
    assert "Run buttons never execute unsaved editor JSON. Save Version first when the draft changes." in js
    assert "deepLinkGraphId" in js
    assert "deepLinkNodeRef" in js
    assert "focusGraphNodeInCanvas" in js
    assert "modulePayloadFetches" in js
    assert "ensureModulePayloadForInspector" in js
    assert "/api/modules/${encodeURIComponent(clean)}" in js
    assert "Node Quick Actions" in js
    assert "runtime-node-quick-actions" in css
    assert "Skipped loading ${requested}; ${activeTab.moduleId} module tab is active." in js
    assert 'activeTab?.kind === "module"' in js
    assert "openModuleGraphTab(moduleSelect.value || activeModuleId)" in js
    assert 'moduleSelect.addEventListener("change", () => openModuleGraphTab(moduleSelect.value || activeModuleId)' in js
    assert "graphConfigFingerprint" in js
    assert "activeDraftConfigDiff" in js
    assert "readableFitMinZoom" in js
    assert 'view: ${percent}%' in js
    assert "Fit graph viewport to readable" in js
    assert "runtime-ide-minimap-viewport" in js
    assert "centerCanvasOnWorldPoint" in js
    assert "beginMiniMapPan" in js
    assert "updateMiniMapViewport" in js
    assert "dropTargetFromEvent" in js
    assert "canvasPortElementFromPoint" in js
    assert "expandedNodeElementFromPoint" in js
    assert "next_stage:${targetStage}" in js
    assert "Added candidate ${sourceStage} -> ${targetStage}; default remains" in js
    assert "Draft config changes" in js
    assert "renderDraftSafetyStrip" in js
    assert "executeDraftSafetyAction" in js
    assert "data-draft-safety-action" in js
    assert "Open Run Launcher" in js
    assert "Record Gate" in js
    assert "draftSafetyStripStatus" in js
    assert "Validate + Dry Run, then Save Version" in js
    assert "Record Active Dry-run Gate before live" in js
    assert "runtime-draft-safety-strip" in css
    assert "keep the graph canvas above the fold" in css
    assert "repeat(6, minmax(0, 1fr))" in css
    assert "prevent the canvas toolbar and draft gate from turning into tall form rows" in css
    assert "runtime-canvas-view-hint" in css
    assert "closed operator drawers are launch controls" in css
    assert "runtime-version-history-panel summary small" in css
    assert "scenario_evidence" in browser_audit
    assert "scenario_graph_switch" in browser_audit
    assert "scenario_canvas_interactions" in browser_audit
    assert "scenario_workspace_artifacts" in browser_audit
    assert "workspace-artifacts" in browser_audit
    assert "runtime_ide_browser_audit_workspace_artifacts.png" in browser_audit
    assert "BO posterior artifact.created event missing" in browser_audit
    assert "CAE contour artifact.created event missing" in browser_audit
    assert "scenario_saved_test_run" in browser_audit
    assert "runtime_ide_browser_audit_saved_test_run.png" in browser_audit
    assert "Run Saved Test did not create a new run id" in browser_audit
    assert "saved test run missing node.started event" in browser_audit
    assert "pre-existing active run is present" in browser_audit
    assert "scenario_invalid_handler" in browser_audit
    assert "scenario_invalid_module" in browser_audit
    assert "scenario_invalid_route" in browser_audit
    assert "runtime_ide_browser_audit_evidence_vcd.png" in browser_audit
    assert "runtime_ide_browser_audit_graph_switch.png" in browser_audit
    assert "runtime_ide_browser_audit_canvas_interactions.png" in browser_audit
    assert "runtime_ide_browser_audit_invalid_handler.png" in browser_audit
    assert "runtime_ide_browser_audit_invalid_module.png" in browser_audit
    assert "runtime_ide_browser_audit_invalid_route.png" in browser_audit
    assert "graph canvas starts too low" in browser_audit
    assert "graph JSON did not switch" in browser_audit
    assert "minimap node count does not match JSON" in browser_audit
    assert "double-click did not open design module tab" in browser_audit
    assert "module internal graph edges missing module-flow styling" in browser_audit
    assert "module internal graph edges are not visibly styled" in browser_audit
    assert "module internal graph edge label text is empty" in browser_audit
    assert "module internal graph arrows are not using the module-flow marker" in browser_audit
    assert "moduleFlowLabelMinWidth" in browser_audit
    assert "edge-module-flow" in js
    assert "MODULE_GRAPH_COLUMN_GAP" in js
    assert "const MODULE_GRAPH_COLUMN_GAP = 560" in js
    assert "defaultModuleNodePosition" in js
    assert "module internal graph node spacing is too tight for edge labels" in browser_audit
    assert "ide-arrow-module" in js
    assert "fill=\"context-stroke\"" in js
    assert "v120: make agent internal module graph connections explicit" in css
    assert "v121: tighten module-flow arrow alignment" in css
    assert "marker-end: url(#ide-arrow-module)" in css
    assert "minimap pan did not change canvas scroll" in browser_audit
    assert "edge drag did not add design -> vision candidate" in browser_audit
    assert "node drag did not update graph JSON position" in browser_audit
    assert "dry-run did not produce VCD evidence" in browser_audit
    assert "runtime-readiness-panel .runtime-readiness-output" in css
    assert "Runtime Readiness is an operational gate" in css
    assert "runtime-draft-safety-action" in css
    assert "runtime-run-target-summary-card" in css
    assert "Full graph config differs from active baseline" in js
    assert "yaml import draft" in js
    assert "activeTabDirty" in js
    assert "tabDirtyState" in js
    assert "graphConfigDiff(item?.baselineGraph || null, item?.graph || {})" in js
    assert "Run preflight blocked" in js
    assert "Active dry-run gate is missing or stale" in js
    assert "startRuntimeGraphFromIde" in js
    assert "runLauncherPayload" in js
    assert "runTargetSummaryMarkup" in js
    assert "Saved active graph execution" in js
    assert "Run buttons never execute unsaved editor JSON" in js
    assert "runTargetSummaryOutput" in js
    assert "run blocked" in js
    assert "data-graph-version-load" in js
    assert "resolveApproval" in js
    assert "/approvals/" in js
    module_management_js = Path("web/static/module_management.js").read_text(encoding="utf-8")
    assert "module-management-item-copy" in module_management_js
    assert "module-management-title-wrap" in module_management_js
    assert "runtimeNodeIconMarkup(moduleIconName(module))" in module_management_js
    assert "applyConfigFormToPayload" in module_management_js
    assert "saveConfigSelected" in module_management_js
    assert "loadModuleVersions" in module_management_js
    assert "loadModuleVersionDraft" in module_management_js
    assert "renderDryRunEvidence" in module_management_js
    assert "module-management-evidence-step" in module_management_js
    assert "modulePreflightStatus" in module_management_js
    assert "Module save preflight blocked" in module_management_js
    assert "requireAppliedModuleDraft" in module_management_js
    assert "runtimeIdeUsageLink" in module_management_js
    assert "Open Node" in module_management_js
    assert "runtimeIdeModuleAttachLink" in module_management_js
    assert 'params.set("action", "attach")' in module_management_js
    assert "data-mm-version-load" in module_management_js
    assert "mm-config-handler-select" in module_management_js
    assert "mm-config-supervisor-required-outputs" in module_management_js
    assert "mm-config-supervisor-opinion-template" in module_management_js
    assert "mm-config-supervisor-recommendation-template" in module_management_js
    assert "mm-config-supervisor-response-statuses" in module_management_js
    assert "mm-config-supervisor-concern-rules" in module_management_js
    assert "mm-config-supervisor-options" in module_management_js
    assert "moduleSupervisorPolicy" in module_management_js
    assert "supervisor_policy_gate" in module_management_js
    assert "Supervisor required outputs" in module_management_js
    assert "missing_outputs" in module_management_js
    assert "data-mm-module-step-field" in module_management_js
    assert "liveAgentChatMode" in planning_js
    assert "liveAgentAllowsOnDemandChat" in planning_js
    assert "agent.chat" in planning_js
    assert "open_on_demand" in planning_js
    assert "persistent" in planning_js

    assert "stageDisplayLabel" in js
    assert "displayCondition" in js
    assert "Module Draft Changed" in js
    assert "validate and dry-run before saving" in js
    assert "moduleValidationResultMarkup" in js
    assert "moduleDryRunResultMarkup" in js
    assert "modulePayloadForGraphDraft" in js
    assert "persistModuleTabPayload" in js
    assert "deepLinkModuleId" in js
    assert "deepLinkAction" in js
    assert "focusDeepLinkedModule" in js
    assert "data-module-deep-link" in js
    assert "Drag the highlighted module onto the main graph canvas" in js
    assert "bridgeActionDescriptorEditor" in js
    assert "saveBridgeCustomActionDescriptor" in js
    assert "/api/bridges/${bridgeId}/actions" in js
    assert "Custom Bridge Action" in js
    assert "data-bridge-action-save" in js
    assert "descriptor_only" in js
    assert "moduleSavePreflightStatus" in js
    assert "moduleSavePreflightBlockedMarkup" in js
    assert "markModulePreflightDirty" in js
    assert 'dirty: false, reason: "not checked"' in js
    assert "Module save blocked" in js
    assert "Module validation ${ok ?" in js
    assert "handler/tool/safety schema check" in js
    assert "Module dry-run ${ok ?" in js
    assert "no hardware calls" in js
    assert "steps[index].metadata = { ...(steps[index].metadata || {}), position:" in js
    assert "renderModuleActivationChecklist" in js
    assert "moduleActivationEvidenceDetailsMarkup" in js
    assert "Validate Module Draft" in js
    assert "Save Module Version" in js
    assert "saveModule({ enforcePreflight: true })" in js
    assert "validateModule(dryRunOutput)" in js
    assert "dryRunModule(dryRunOutput)" in js
    assert "Module dry-run" in js
    css = Path("web/static/runtime_ide.css").read_text(encoding="utf-8")
    assert "runtime-run-target-strip" in css
    assert "runtime-run-message" in css
    assert "runtime-module-evidence-card" in css
    assert "runtime-module-save-gate-list" in css
    assert "pre_execution" in js and "internal_graph" in js
    assert "controlRuntimeRun" in js

from agents.base_agent import AgentResult, BaseAgent
from agents.registry import AgentRegistry
from logging_system.logger_factory import build_logger_bundle
from orchestrator.run_loop import RunLoop
from orchestrator.state import Mode, OrchestratorState, Stage


class _StaticAgent(BaseAgent):
    """Tiny agent used to prove graph-config transitions affect runtime execution."""

    def __init__(self, name: str, data: dict[str, object]) -> None:
        self.name = name
        self._data = data
        self.run_count = 0

    async def run(self, state: OrchestratorState, ctx: object) -> AgentResult:
        self.run_count += 1
        return AgentResult(success=True, summary=f"{self.name} done", data=dict(self._data))


class _FailingAgent(BaseAgent):
    """Agent that always fails so retry policy can be tested."""

    def __init__(self, name: str, message: str = "planned failure") -> None:
        self.name = name
        self.message = message
        self.run_count = 0

    async def run(self, state: OrchestratorState, ctx: object) -> AgentResult:
        self.run_count += 1
        raise RuntimeError(self.message)


class _ContextProbeAgent(BaseAgent):
    """Agent that records module runtime context visible during internal-step execution."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.run_count = 0
        self.seen_module_config: dict[str, object] = {}

    async def run(self, state: OrchestratorState, ctx: object) -> AgentResult:
        self.run_count += 1
        if hasattr(ctx, "runtime_module_config"):
            self.seen_module_config = ctx.runtime_module_config()  # type: ignore[assignment,attr-defined]
        else:
            self.seen_module_config = {"active_internal_step": state.run_metadata.get("active_module_step", {}).get("step", {})}
        return AgentResult(success=True, summary=f"{self.name} probe", data={"step_output": {"agent": self.name}})


@pytest.mark.asyncio
async def test_langgraph_runtime_pauses_active_cam_operator_wait_at_vision(tmp_path: Path) -> None:
    state = OrchestratorState(
        run_id="run-vision-operator-wait",
        experiment_id="exp-vision-operator-wait",
        mode=Mode.TEST,
        stage=Stage.VISION,
    )
    events: list[dict[str, object]] = []
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=StructuredLogger(tmp_path / "runtime.jsonl", tmp_path / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
        on_event=events.append,
    )
    intervention = {
        "schema": "vision_operator_intervention.v1",
        "run_id": state.run_id,
        "checkpoint": "active_cam_ejection",
        "status": "waiting_for_specimen",
        "reason": "specimen_not_detected",
        "capture_path": "/tmp/fresh-empty-workspace.png",
    }

    paused = await runtime._pause_for_vision_intervention(  # type: ignore[attr-defined]
        stage=Stage.VISION,
        agent_name="vision_agent",
        status=runtime._ensure_agent_status("vision_agent"),
        result_data={"vision_operator_intervention": intervention},
    )

    assert paused is True
    assert state.stage == Stage.VISION
    assert state.is_paused is True
    assert state.agent_status["vision_agent"].state == "waiting"
    assert state.run_metadata["vision_operator_intervention"] == intervention
    assert any(event["event_type"] == "operator_input_required" for event in events)


@pytest.mark.asyncio
async def test_langgraph_runtime_does_not_pause_utm_automatic_recovery(tmp_path: Path) -> None:
    state = OrchestratorState(
        run_id="run-utm-automatic-recovery",
        experiment_id="exp-utm-automatic-recovery",
        mode=Mode.TEST,
        stage=Stage.VISION,
    )
    runtime = LangGraphRunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=StructuredLogger(tmp_path / "runtime.jsonl", tmp_path / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
    )

    paused = await runtime._pause_for_vision_intervention(  # type: ignore[attr-defined]
        stage=Stage.VISION,
        agent_name="vision_agent",
        status=runtime._ensure_agent_status("vision_agent"),
        result_data={
            "vision_operator_intervention": {
                "schema": "vision_operator_intervention.v1",
                "run_id": state.run_id,
                "checkpoint": "utm_post_place",
                "status": "retrying",
                "reason": "specimen_not_detected",
            }
        },
    )

    assert paused is False
    assert state.is_paused is False


def test_runtime_handler_registry_exposes_new_registered_agents_to_graph_and_module_validation() -> None:
    app_main.controller._deps.agent_registry.register(_StaticAgent("experimental_agent", {}))
    client = TestClient(app_main.app)

    handlers = client.get("/api/handlers").json()["handlers"]
    assert "agent.experimental_agent" in handlers

    graph = client.get("/api/graphs/atr_closed_loop").json()["graph"]
    graph["nodes"][2]["handler"] = "agent.experimental_agent"
    graph_validation = client.post(
        "/api/graphs/atr_closed_loop/validate-draft",
        json={"graph": graph, "reason": "experimental-handler", "author": "pytest", "activate": False},
    ).json()
    assert graph_validation["ok"] is True
    assert graph_validation["compiled"] is True
    assert graph_validation["errors"] == []
    assert graph_validation["compiled_graph"]["nodes"][2]["handler"] == "agent.experimental_agent"

    module = client.get("/api/modules/design").json()["module"]
    module["module"]["handler"] = "agent.experimental_agent"
    module["module"]["internal_graph"][0]["handler"] = "agent.experimental_agent"
    module_validation = client.post(
        "/api/modules/design/validate",
        json={"module": module, "reason": "experimental-handler", "author": "pytest", "activate": False},
    ).json()
    assert module_validation == {"ok": True, "module_id": "design", "errors": []}


def _retry_test_loop(
    tmp_path: Path,
    *,
    module_retry: dict[str, object],
    global_max_retry: int,
) -> tuple[RunLoop, OrchestratorState, _FailingAgent, list[dict[str, object]]]:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {})
    design = _FailingAgent("design_agent")
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-retry", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-retry",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        max_retry_per_stage=global_max_retry,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.design_agent",
        "retry": dict(module_retry),
        "tools": [],
    }
    return loop, state, design, events


@pytest.mark.asyncio
async def test_saved_transition_candidate_routes_actual_langgraph_run_loop(tmp_path) -> None:
    """A Runtime IDE candidate edge must survive save/compile and drive actual runtime routing."""
    payload = load_graph_config("graphs/configs/atr_closed_loop.yaml").model_dump(mode="json")
    _add_graph_transition_candidate(payload, "design", "guardian", "next_stage:guardian")
    config = GraphConfig.model_validate(payload)

    assert config.transitions["design"] == "specimen"
    assert config.next_stage("design") == "specimen"
    assert config.next_stage("design", state_metadata={"agent_result": {"next_stage": "guardian"}}) == "guardian"

    graph_path = tmp_path / "atr_closed_loop_candidate.yaml"
    graph_path.write_text(yaml.safe_dump({"graph": config.model_dump(mode="json")}, sort_keys=False), encoding="utf-8")

    registry_for_compile = _noop_registry()
    compiler = ATRLangGraphCompiler(config, registry_for_compile)
    assert compiler.validate() == []
    summary = compiler.summary()
    design_candidates = summary["transition_candidates"]["design"]
    assert any(
        item["to_stage"] == "guardian" and item["condition"] == "next_stage:guardian" and item["default"] is False
        for item in design_candidates
    )

    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {"plan_text": "candidate route preflight"})
    design = _StaticAgent(
        "design_agent",
        {
            "experiment_spec": {"specimen_id": "candidate-route"},
            "next_stage": "guardian",
        },
    )
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-candidate-route", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-candidate-route",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path=graph_path,
        on_event=events.append,
    )

    await loop.step()

    assert orchestrator.run_count == 1
    assert design.run_count == 1
    assert state.stage == Stage.GUARDIAN
    transition_events = [event for event in events if event["type"] == "edge.traversed" and event["node_id"] == "design"]
    assert transition_events
    payload = transition_events[-1]["payload"]
    assert payload["from_stage"] == "design"
    assert payload["to_stage"] == "guardian"
    assert payload["selected_transition"]["to_stage"] == "guardian"
    assert payload["selected_transition"]["condition"] == "next_stage:guardian"
    assert payload["selected_transition"]["default"] is False
    assert any(
        item["to_stage"] == "specimen" and item["default"] is True
        for item in payload["transition_candidates"]
    )


@pytest.mark.asyncio
async def test_workspace_template_graph_executes_through_langgraph_run_loop(tmp_path) -> None:
    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    fabrication_report = {
        "schema": "fabrication_report.v1",
        "digital_thread": {"specimen_id": "sp-1", "stl_path": "sp-1.stl", "gcode_path": "sp-1.gcode"},
        "quality_gates": [{"gate": "slicer", "status": "pass", "evidence": {}, "repair": None}],
        "fabrication_outcome": {"status": "virtual_finished", "location": "virtual_bridge", "warnings": [], "failure_code": None},
    }
    specimen_packet = {
        "schema": "specimen_fabricated.v1",
        "specimen_id": "sp-1",
        "status": "ready",
        "fabrication_report": fabrication_report,
    }
    specimen = _StaticAgent(
        "specimen_agent",
        {
            "specimen_result": {"ok": True, "status": "prepared", "fabrication_report": fabrication_report},
            "fabrication_report": fabrication_report,
            "specimen_fabricated": specimen_packet,
            "handoff_packet": specimen_packet,
            "decisions": [{"decision_id": "specimen.handoff.prepared", "status": "ok"}],
            "metrics": {"quality_gate_count": 1},
        },
    )
    registry.register(specimen)
    bundle = build_logger_bundle(run_id="run-langgraph-printer-template", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-printer-template",
        mode=Mode.TEST,
        stage=Stage.IDLE,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path="graphs/configs/printer_pipeline.yaml",
        on_event=events.append,
    )

    await loop.step()
    assert state.stage == Stage.SPECIMEN
    await loop.step()

    assert specimen.run_count == 1
    assert state.stage == Stage.COMPLETE
    assert state.run_metadata["fabrication_report"]["schema"] == "fabrication_report.v1"
    assert state.run_metadata["specimen_fabricated"]["schema"] == "specimen_fabricated.v1"
    assert state.run_metadata["specimen_handoff_packet"]["schema"] == "specimen_fabricated.v1"
    assert state.run_metadata["specimen_decision_register"][0]["decision_id"] == "specimen.handoff.prepared"
    assert state.run_metadata["specimen_metrics"]["quality_gate_count"] == 1
    assert any(packet["packet"]["schema"] == "specimen_fabricated.v1" for packet in state.run_metadata["handoff_packets"])
    assert any(event["graph_id"] == "printer_pipeline" for event in events)
    assert any(event["type"] == "node.completed" and event["node_id"] == "specimen" for event in events)


@pytest.mark.asyncio
async def test_module_retry_policy_overrides_global_retry_budget(tmp_path) -> None:
    loop, state, design, events = _retry_test_loop(
        tmp_path,
        module_retry={"max_attempts": 1, "backoff_s": 0},
        global_max_retry=0,
    )

    await loop.step()

    assert design.run_count == 1
    assert state.stage == Stage.DESIGN
    assert state.retry_counters["design"] == 1
    retry_events = [event for event in events if event["type"] == "node.retrying"]
    assert retry_events
    assert retry_events[-1]["payload"]["retry_policy"] == {"max_attempts": 1, "backoff_s": 0.0}

    await loop.step()

    assert design.run_count == 2
    assert state.stage == Stage.ERROR
    failed_events = [event for event in events if event["type"] == "node.failed"]
    assert failed_events[-1]["payload"]["retry_policy"] == {"max_attempts": 1, "backoff_s": 0.0}


@pytest.mark.asyncio
async def test_module_retry_policy_zero_attempts_fails_without_retry(tmp_path) -> None:
    loop, state, design, events = _retry_test_loop(
        tmp_path,
        module_retry={"max_attempts": 0, "backoff_s": 0},
        global_max_retry=3,
    )

    await loop.step()

    assert design.run_count == 1
    assert state.stage == Stage.ERROR
    assert state.retry_counters.get("design", 0) == 0
    assert not [event for event in events if event["type"] == "node.retrying"]
    exception_gates = [
        gate
        for gate in state.run_metadata.get("guardian_gates", [])
        if gate.get("phase") == "exception" and gate.get("agent") == "design_agent"
    ]
    assert exception_gates
    assert exception_gates[-1]["schema"] == "guardian_gate_result.v1"
    assert exception_gates[-1]["reason_code"] == "RUNTIMEERROR"


def _approval_test_loop(tmp_path: Path) -> tuple[RunLoop, OrchestratorState, _StaticAgent, list[dict[str, object]]]:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "approval-gated"}})
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-approval", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-approval",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.design_agent",
        "safety": {"requires_human_approval": True},
        "tools": [],
    }
    return loop, state, design, events


@pytest.mark.asyncio
async def test_module_human_approval_gate_blocks_stage_until_approved(tmp_path) -> None:
    loop, state, design, events = _approval_test_loop(tmp_path)

    await loop.step()

    assert state.stage == Stage.DESIGN
    assert state.is_paused is True
    assert design.run_count == 0
    approvals = state.run_metadata["runtime_approvals"]
    gate_key, gate = next(iter(approvals.items()))
    assert gate["status"] == "pending"
    assert gate["stage"] == "design"
    assert any(event["type"] == "approval.requested" for event in events)

    approvals[gate_key]["status"] = "approved"
    state.is_paused = False
    await loop.step()

    assert design.run_count == 1
    assert state.stage == Stage.SPECIMEN
    assert any(event["type"] == "node.completed" and event["node_id"] == "design" for event in events)


@pytest.mark.asyncio
async def test_module_human_approval_rejection_stops_stage(tmp_path) -> None:
    loop, state, design, events = _approval_test_loop(tmp_path)

    await loop.step()
    approvals = state.run_metadata["runtime_approvals"]
    gate_key, _gate = next(iter(approvals.items()))
    approvals[gate_key]["status"] = "rejected"
    state.is_paused = False

    await loop.step()

    assert design.run_count == 0
    assert state.stage == Stage.ERROR
    assert any(event["type"] == "node.failed" and event["payload"].get("decision") == "rejected" for event in events)


@pytest.mark.asyncio
async def test_missing_module_handler_fails_as_routing_error(tmp_path) -> None:
    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    bundle = build_logger_bundle(run_id="run-langgraph-missing-handler", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-missing-handler",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.missing_agent",
        "tools": [],
    }

    await loop.step()

    assert state.stage == Stage.ERROR
    failed = [event for event in events if event["type"] == "node.failed"]
    assert failed[-1]["payload"]["handler"] == "agent.missing_agent"
    assert failed[-1]["payload"]["agent"] == "missing_agent"


@pytest.mark.asyncio
async def test_module_handler_override_changes_actual_agent_execution(tmp_path) -> None:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "wrong-agent"}})
    guardian = _StaticAgent("guardian_agent", {"experiment_spec": {"specimen_id": "handler-override"}})
    registry.register(orchestrator)
    registry.register(design)
    registry.register(guardian)
    bundle = build_logger_bundle(run_id="run-langgraph-handler", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-handler",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "label": "Design Override Module",
        "handler": "agent.guardian_agent",
        "tools": [],
    }

    await loop.step()

    assert design.run_count == 0
    assert guardian.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "handler-override"}
    assert state.stage == Stage.SPECIMEN
    started = [event for event in events if event["type"] == "node.started" and event["node_id"] == "design"]
    assert started[-1]["agent"] == "guardian_agent"
    assert started[-1]["payload"]["module_runtime"]["label"] == "Design Override Module"
    assert started[-1]["payload"]["module_runtime"]["effective_handler"] == "agent.guardian_agent"


@pytest.mark.asyncio
async def test_module_pre_execution_runs_orchestrator_before_design_from_config(tmp_path) -> None:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {"plan_text": "pre plan", "model": "unit"})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "pre-exec"}})
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-pre-exec", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-pre-exec",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )

    await loop.step()

    assert orchestrator.run_count == 1
    assert design.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "pre-exec"}
    assert state.run_metadata["orchestrator_plan"] == {"plan_text": "pre plan", "model": "unit"}
    assert any(event["type"] == "module.pre_step.started" for event in events)
    assert any(event["type"] == "module.pre_step.completed" for event in events)
    legacy = [event for event in events if event["event_type"] == "orchestrator_plan"]
    assert legacy
    assert legacy[-1]["type"] == "node.completed"
    assert legacy[-1]["node_id"] == "orchestrator_plan"


@pytest.mark.asyncio
async def test_module_pre_execution_can_be_skipped_for_live_planning_handoff(tmp_path) -> None:
    registry = AgentRegistry()
    orchestrator = _StaticAgent("orchestrator_agent", {"plan_text": "duplicate"})
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "handoff-design"}})
    registry.register(orchestrator)
    registry.register(design)
    bundle = build_logger_bundle(run_id="run-langgraph-pre-exec-skip", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-pre-exec-skip",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        run_orchestrator_before_design=False,
        on_event=events.append,
    )

    await loop.step()

    assert orchestrator.run_count == 0
    assert design.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "handoff-design"}
    assert "orchestrator_plan" not in state.run_metadata
    assert not [event for event in events if event["type"].startswith("module.pre_step")]


@pytest.mark.asyncio
async def test_module_internal_graph_emits_runtime_trace_events(tmp_path) -> None:
    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    registry.register(_StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "internal-graph"}}))
    bundle = build_logger_bundle(run_id="run-langgraph-internal", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-internal",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.design_agent",
        "internal_graph": [
            {"id": "01_intake", "label": "Intake", "kind": "internal_step"},
            {"id": "02_generate", "label": "Generate", "kind": "internal_step", "handler": "agent.design_agent"},
        ],
        "tools": [],
    }

    await loop.step()

    event_types = [event["type"] for event in events]
    assert "module.graph.started" in event_types
    assert event_types.count("module.step.planned") == 2
    assert "module.graph.completed" in event_types
    planned = [event for event in events if event["type"] == "module.step.planned"]
    assert [event["payload"]["module_step"]["id"] for event in planned] == ["01_intake", "02_generate"]
    completed = [event for event in events if event["type"] == "module.graph.completed"][-1]
    assert completed["payload"]["result_keys"] == ["experiment_spec"]
    assert completed["payload"]["step_count"] == 2


@pytest.mark.asyncio
async def test_module_internal_graph_executes_configured_step_handlers(tmp_path) -> None:
    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    design = _StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "internal-handler"}})
    probe = _ContextProbeAgent("step_agent")
    registry.register(design)
    registry.register(probe)
    bundle = build_logger_bundle(run_id="run-langgraph-internal-handler", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-internal-handler",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        on_event=events.append,
    )
    loop._module_configs["design"] = {  # type: ignore[attr-defined]
        "id": "design",
        "handler": "agent.design_agent",
        "internal_graph": [
            {"id": "01_checkpoint", "label": "Checkpoint", "kind": "internal_step"},
            {"id": "02_probe", "label": "Probe", "kind": "internal_step", "handler": "agent.step_agent"},
        ],
        "tools": [],
    }

    await loop.step()

    assert probe.run_count == 1
    assert design.run_count == 1
    assert state.current_experiment_spec == {"specimen_id": "internal-handler"}
    assert probe.seen_module_config["active_internal_step"]["id"] == "02_probe"
    assert state.run_metadata["module_step_results"]["design"]["02_probe"] == {"step_output": {"agent": "step_agent"}}
    assert "active_module_step" not in state.run_metadata
    started = [event for event in events if event["type"] == "module.step.started"]
    completed = [event for event in events if event["type"] == "module.step.completed"]
    assert [event["payload"]["module_step"]["id"] for event in started] == ["01_checkpoint", "02_probe"]
    assert [event["payload"]["executable"] for event in completed] == [False, True]


@pytest.mark.asyncio
async def test_module_internal_graph_emits_failure_event(tmp_path) -> None:
    loop, state, design, events = _retry_test_loop(
        tmp_path,
        module_retry={"max_attempts": 0, "backoff_s": 0},
        global_max_retry=0,
    )
    loop._module_configs["design"]["internal_graph"] = [  # type: ignore[index]
        {"id": "01_fail", "label": "Fail", "kind": "internal_step"}
    ]

    await loop.step()

    assert design.run_count == 1
    assert state.stage == Stage.ERROR
    failed = [event for event in events if event["type"] == "module.graph.failed"]
    assert failed
    assert failed[-1]["payload"]["step_count"] == 1
    assert "planned failure" in failed[-1]["payload"]["error"]


@pytest.mark.asyncio
async def test_langgraph_runtime_consumes_operator_followup_at_stage_boundary(tmp_path: Path) -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    payload = config.model_dump(mode="json")
    payload["transitions"]["design"] = "guardian"
    for edge in payload["edges"]:
        if (
            edge.get("metadata", {}).get("runtime_edge") == "logical_transition"
            and edge.get("metadata", {}).get("from_stage") == "design"
            and edge.get("metadata", {}).get("default_transition") is True
        ):
            edge["target"] = "guardian"
            edge["label"] = "default transition: design -> guardian"
            edge["metadata"]["to_stage"] = "guardian"
            break
    graph_path = tmp_path / "followup_graph.yaml"
    graph_path.write_text(yaml.safe_dump({"graph": payload}, sort_keys=False), encoding="utf-8")

    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    registry.register(_StaticAgent("design_agent", {"experiment_spec": {"specimen_id": "followup-spec"}}))
    registry.register(_StaticAgent("guardian_agent", {"guardian": {"decision": "stop"}}))

    bundle = build_logger_bundle(run_id="run-langgraph-followup", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-followup",
        mode=Mode.TEST,
        stage=Stage.IDLE,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path=graph_path,
        on_event=events.append,
    )

    await loop.step()
    assert state.stage == Stage.DESIGN
    state.run_metadata["operator_followup_queue"] = [
        {
            "schema": "operator_runtime_followup.v1",
            "followup_id": "operator-followup-001",
            "status": "queued",
            "message": "다음 후보에서는 wall thickness를 낮춰줘",
            "target_agent": "orchestrator",
            "chat_mode": "ask",
            "stage_at_submit": "design",
        }
    ]

    await loop.step()

    assert state.run_metadata["operator_followup_queue"] == []
    consumed = state.run_metadata["operator_followup_context"][-1]
    assert consumed["status"] == "consumed"
    assert consumed["consumed_stage"] == "design"
    assert consumed["message"].startswith("다음 후보")
    assert any(event.get("event_type") == "operator.followup_consumed" for event in events)
    assert any(item.get("trigger") == "operator_followup" for item in state.run_metadata["orchestrator_followups"])
    assert any(
        event.get("event_type") == "orchestrator.followup"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("orchestrator_followup", {}).get("trigger") == "operator_followup"
        for event in events
    )

@pytest.mark.asyncio
async def test_configured_transition_changes_actual_langgraph_runtime(tmp_path) -> None:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    payload = config.model_dump(mode="json")
    payload["transitions"]["design"] = "guardian"
    design_default_edge = next(
        edge
        for edge in payload["edges"]
        if edge.get("metadata", {}).get("runtime_edge") == "logical_transition"
        and edge.get("metadata", {}).get("from_stage") == "design"
        and edge.get("metadata", {}).get("default_transition") is True
    )
    design_default_edge["target"] = "guardian"
    design_default_edge["label"] = "default transition: design -> guardian"
    design_default_edge["metadata"]["to_stage"] = "guardian"
    graph_path = tmp_path / "graph.yaml"
    graph_path.write_text(yaml.safe_dump({"graph": payload}, sort_keys=False), encoding="utf-8")

    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    registry.register(
        _StaticAgent(
            "design_agent",
            {
                "experiment_spec": {"specimen_id": "cfg-transition-test"},
                "artifacts": {"preview_url": "/api/planning/artifacts/run/specimen/specimen_preview.svg"},
            },
        )
    )
    registry.register(_StaticAgent("guardian_agent", {"guardian": {"decision": "stop"}}))

    bundle = build_logger_bundle(run_id="run-langgraph-transition", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-langgraph-transition",
        mode=Mode.TEST,
        stage=Stage.IDLE,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path=graph_path,
        on_event=events.append,
    )

    await loop.step()
    assert state.stage == Stage.DESIGN
    await loop.step()
    assert state.stage == Stage.GUARDIAN
    await loop.step()
    assert state.stage == Stage.COMPLETE
    assert state.loop_count == 1
    assert "specimen_agent" not in state.agent_status
    assert state.run_metadata["orchestrator_decision_register"]
    assert state.run_metadata["orchestrator_handoff_packets"]
    assert state.run_metadata["orchestrator_followups"]
    assert state.run_metadata["loop_reflections"][-1]["schema"] == "loop_reflection.v1"
    assert state.run_metadata["latest_orchestrator_handoff"]["schema"] == "handoff_packet.v1"
    assert state.run_metadata["latest_orchestrator_followup"]["schema"] == "orchestrator_followup.v1"
    assert state.run_metadata["latest_orchestration_plan"]["schema"] == "orchestration_plan.v1"
    assert state.run_metadata["latest_orchestration_plan"]["parallelizable_checks"]
    assert state.run_metadata["latest_orchestrator_parallel_checks"]["schema"] == "orchestrator_parallel_checks.v1"
    assert state.run_metadata["latest_orchestrator_parallel_checks"]["execution_mode"] == "asyncio.gather/read_only"
    assert any(event["event_type"] == "orchestrator.followup" for event in events)
    assert any(event["event_type"] == "orchestrator.decision" for event in events)
    assert any(event["event_type"] == "orchestrator.parallel_checks" for event in events)
    assert any(event["event_type"] == "orchestrator.loop_reflection" for event in events)
    event_types = [event["type"] for event in events]
    assert "node.started" in event_types
    assert "edge.traversed" in event_types

from backends.llm_backend import BaseLLMBackend, LLMResponse
from backends.model_router import ModelRouter
from orchestrator.langgraph_runtime import ModuleRuntimeContext


class _CaptureBackend(BaseLLMBackend):
    """LLM backend that records the exact request received from ModuleRuntimeContext."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, object] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "metadata": metadata or {},
            }
        )
        return LLMResponse(text="module-routed", model=model, raw={"metadata": metadata or {}})


class _FailingBackend(BaseLLMBackend):
    """LLM backend that records calls and then fails."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, object] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "metadata": metadata or {},
            }
        )
        raise RuntimeError(f"{model} unavailable")


class _FakeToolRegistry:
    """Small ToolRegistry-compatible object for module allowlist tests."""

    def __init__(self, tools: list[str] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._tools = tools or ["blocked.tool", "experiment.evaluate", "geometry.generate_metamaterial_stl"]

    def call(self, name: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append({"name": name, "payload": payload or {}})
        return {"ok": True, "tool": name, "payload": payload or {}}

    def list_tools(self) -> list[str]:
        return list(self._tools)

    def queue_status(self) -> dict[str, object]:
        return {"ok": True, "queues": []}


class _FakeAgentContext:
    """Minimal AgentContext-compatible object for module routing tests."""

    def __init__(self, backend: BaseLLMBackend, fallback_backend: BaseLLMBackend | None = None) -> None:
        router = ModelRouter(
            {
                "models": {"e4b": {"primary": "router-primary", "fallback": "router-fallback"}},
                "task_routes": {"module_reasoning": "e4b", "design_reasoning": "e4b"},
            }
        )
        openai_router = ModelRouter(
            {
                "models": {"e4b": {"primary": "gpt-5.5"}},
                "task_routes": {"module_reasoning": "e4b", "design_reasoning": "e4b"},
            }
        )
        effective_fallback = fallback_backend or backend
        self.active_backend = "ollama"
        self.model_router = router
        self.model_routers = {"ollama": router, "vllm": router, "openai": openai_router}
        self.primary_backend = backend
        self.primary_backends = {"ollama": backend, "vllm": backend, "openai": effective_fallback}
        self.fallback_backend = effective_fallback
        self.fallback_backends = {"ollama": effective_fallback, "vllm": effective_fallback, "openai": effective_fallback}
        self.backend_fallbacks = {"ollama": "openai", "vllm": "openai", "openai": "openai"}
        self.tools = _FakeToolRegistry()
        self.notifications: list[dict[str, str]] = []
        self.model_call_events: list[dict[str, str]] = []

    async def _notify_model_call(self, task_type: str, model: str, role: str) -> None:
        self.notifications.append({"task_type": task_type, "model": model, "role": role})

    async def on_model_call(self, *, task_type: str, model: str, role: str, backend: str) -> None:
        self.model_call_events.append({"task_type": task_type, "model": model, "role": role, "backend": backend})


@pytest.mark.asyncio
async def test_module_runtime_context_applies_llm_model_prompt_and_metadata() -> None:
    backend = _CaptureBackend()
    base_ctx = _FakeAgentContext(backend)
    module_ctx = ModuleRuntimeContext(
        base_ctx,  # type: ignore[arg-type]
        {
            "id": "design",
            "llm_role": "module_reasoning",
            "llm": {"backend": "vllm", "model": "module-model", "fallback": "module-fallback"},
            "prompt": {"system": "module system prompt", "developer": "module developer prompt"},
            "timeout_s": 10,
        },
        Stage.DESIGN,
    )

    response = await module_ctx.complete("design_reasoning", "original user prompt")

    assert response.model == "module-model"
    assert backend.calls == [
        {
            "model": "module-model",
            "system_prompt": "module system prompt",
            "user_prompt": "[Module developer guidance: module developer prompt]\n\noriginal user prompt",
            "metadata": {
                "task_type": "module_reasoning",
                "requested_task_type": "design_reasoning",
                "role": "e4b",
                "stage": "design",
                "module_id": "design",
                "module_config_applied": True,
            },
        }
    ]
    assert base_ctx.model_call_events == [
        {"task_type": "module_reasoning", "model": "module-model", "role": "e4b", "backend": "vllm"}
    ]
    assert base_ctx.notifications == []


@pytest.mark.asyncio
async def test_module_runtime_context_uses_shared_llm_lease() -> None:
    from backends.llm_lease import LLMLeaseCoordinator

    backend = _CaptureBackend()
    base_ctx = _FakeAgentContext(backend)
    base_ctx.llm_lease = LLMLeaseCoordinator()
    module_ctx = ModuleRuntimeContext(
        base_ctx,  # type: ignore[arg-type]
        {"id": "design", "llm_role": "design_reasoning", "llm": {"backend": "vllm", "model": "module-model"}},
        Stage.DESIGN,
    )

    await module_ctx.complete("design_reasoning", "prompt")

    assert base_ctx.llm_lease.status()["last_owner"] == "module:design:design_reasoning"
    assert base_ctx.llm_lease.status()["last_priority"] == 10


@pytest.mark.asyncio
async def test_module_runtime_context_uses_backend_fallback_after_active_models_fail() -> None:
    local_backend = _FailingBackend()
    openai_backend = _CaptureBackend()
    base_ctx = _FakeAgentContext(local_backend, fallback_backend=openai_backend)
    module_ctx = ModuleRuntimeContext(
        base_ctx,  # type: ignore[arg-type]
        {
            "id": "design",
            "llm_role": "design_reasoning",
            "llm": {"backend": "vllm", "model": "local-primary", "fallback": "local-fallback"},
        },
        Stage.DESIGN,
    )

    response = await module_ctx.complete("design_reasoning", "design prompt")

    assert response.model == "gpt-5.5"
    assert [call["model"] for call in local_backend.calls] == ["local-primary", "local-fallback"]
    assert openai_backend.calls[-1]["model"] == "gpt-5.5"
    assert openai_backend.calls[-1]["metadata"]["role"] == "e4b:backend_fallback"
    assert base_ctx.model_call_events[-1] == {
        "task_type": "design_reasoning",
        "model": "gpt-5.5",
        "role": "e4b:backend_fallback",
        "backend": "openai",
    }


def test_module_runtime_context_filters_tools_by_module_allowlist() -> None:
    backend = _CaptureBackend()
    base_ctx = _FakeAgentContext(backend)
    module_ctx = ModuleRuntimeContext(
        base_ctx,  # type: ignore[arg-type]
        {
            "id": "specimen",
            "tools": ["geometry.generate_metamaterial_stl", "experiment.evaluate"],
        },
        Stage.SPECIMEN,
    )

    assert module_ctx.tools.list_tools() == ["experiment.evaluate", "geometry.generate_metamaterial_stl"]
    assert module_ctx.tools.call("geometry.generate_metamaterial_stl", {"size": 30}) == {
        "ok": True,
        "tool": "geometry.generate_metamaterial_stl",
        "payload": {"size": 30},
    }
    with pytest.raises(PermissionError) as exc_info:
        module_ctx.tools.call("blocked.tool", {})
    assert "Tool not allowed for stage=specimen: blocked.tool" in str(exc_info.value)
    assert module_ctx.tools.queue_status() == {"ok": True, "queues": []}


def test_vision_module_runtime_exposes_active_cam_and_utm_tools() -> None:
    backend = _CaptureBackend()
    base_ctx = _FakeAgentContext(backend)
    base_ctx.tools = _FakeToolRegistry(
        [
            "camera.capture",
            "lerobot.camera.test",
            "lerobot.active_robot_cam.capture",
            "lerobot.rollout.status",
            "vision.specimen_pose_snapshot",
            "vision.specimen_pose.release",
            "vision.utm_runtime.start",
        ]
    )
    raw = yaml.safe_load(Path("graphs/modules/vision/module.yaml").read_text(encoding="utf-8")) or {}
    module = raw.get("module", raw)

    module_ctx = ModuleRuntimeContext(base_ctx, module, Stage.VISION)  # type: ignore[arg-type]

    assert "lerobot.camera.test" in module_ctx.tools.list_tools()
    assert "lerobot.active_robot_cam.capture" in module_ctx.tools.list_tools()
    assert "lerobot.rollout.status" in module_ctx.tools.list_tools()
    assert "vision.utm_runtime.start" in module_ctx.tools.list_tools()


def test_generated_module_adapter_executes_as_stage_handler(tmp_path) -> None:
    graph_root = tmp_path / "graphs"
    config_root = graph_root / "configs"
    modules_root = graph_root / "modules"
    module_dir = modules_root / "design"
    config_root.mkdir(parents=True)
    shutil.copytree(Path("graphs/modules"), modules_root)
    (config_root / "atr_closed_loop.yaml").write_text(
        Path("graphs/configs/atr_closed_loop.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (module_dir / "handler.py").write_text(
        "from agents.base_agent import AgentResult\n\n"
        "async def run(state, ctx):\n"
        "    return AgentResult(success=True, summary='generated design ok', data={'experiment_spec': {'specimen_id': 'generated-module'}})\n",
        encoding="utf-8",
    )
    (module_dir / "module.yaml").write_text(
        """
module:
  id: design
  label: Generated Design Module
  handler: module.generated_adapter
  metadata:
    pending_handler_registration: false
    generated_adapter_approved: true
    generated_adapter_handler_id: module.generated_adapter
    generated_adapter_path: handler.py
  safety:
    live_requires_validation: true
    dry_run_supported: true
    requires_human_approval: false
  internal_graph:
    - id: 01_generated_checkpoint
      label: Generated adapter checkpoint
      kind: internal_step
""".strip()
        + "\n",
        encoding="utf-8",
    )

    registry = AgentRegistry()
    registry.register(_StaticAgent("orchestrator_agent", {}))
    bundle = build_logger_bundle(run_id="run-generated-module", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-generated-module",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path=config_root / "atr_closed_loop.yaml",
        module_root=graph_root,
        on_event=events.append,
    )

    asyncio.run(loop.step())

    assert state.current_experiment_spec == {"specimen_id": "generated-module"}
    started = [event for event in events if event["type"] == "node.started" and event["node_id"] == "design"]
    assert started[-1]["agent"] == "generated:design"
    assert started[-1]["payload"]["module_runtime"]["effective_handler"] == "module.generated_adapter"
    completed = [event for event in events if event["type"] == "node.completed" and event["node_id"] == "design"]
    assert completed[-1]["agent"] == "generated:design"

@pytest.mark.asyncio
async def test_module_runtime_context_preserves_python_task_when_llm_role_empty() -> None:
    backend = _CaptureBackend()
    base_ctx = _FakeAgentContext(backend)
    module_ctx = ModuleRuntimeContext(
        base_ctx,  # type: ignore[arg-type]
        {
            "id": "analysis",
            "llm_role": "",
            "llm": {"backend": "vllm", "model": "analysis-model"},
            "prompt": {},
        },
        Stage.ANALYSIS,
    )

    response = await module_ctx.complete("analysis_fem_planning", "plan FEM loop")

    assert response.model == "analysis-model"
    assert backend.calls[-1]["metadata"]["task_type"] == "analysis_fem_planning"
    assert backend.calls[-1]["metadata"]["requested_task_type"] == "analysis_fem_planning"
    assert base_ctx.model_call_events[-1] == {
        "task_type": "analysis_fem_planning",
        "model": "analysis-model",
        "role": "e4b",
        "backend": "vllm",
    }


def test_langgraph_run_records_pre_run_guardian_gate(tmp_path: Path) -> None:
    bundle = build_logger_bundle(run_id="run-pre-run-gate", run_root=tmp_path / "runs", logging_config={})
    state = OrchestratorState(
        run_id=bundle.run_dir.name,
        experiment_id="exp-pre-run-gate",
        mode=Mode.TEST,
        stage=Stage.COMPLETE,
    )
    events: list[dict[str, object]] = []
    loop = RunLoop(
        state=state,
        agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator_agent",
        ctx=object(),
        logger=bundle.logger,
        interval_seconds=0,
        graph_config_path="graphs/configs/atr_closed_loop.yaml",
        on_event=events.append,
    )

    asyncio.run(loop.run())

    gates = state.run_metadata.get("guardian_gates", [])
    assert gates
    assert gates[0]["schema"] == "guardian_gate_result.v1"
    assert gates[0]["phase"] == "pre_run"
    assert gates[0]["guardian_contract"]["schema_version"] == "guardian_contract.v1"
    guardian_events = [event for event in events if event.get("type") == "guardian.gate"]
    assert guardian_events
    assert guardian_events[0]["payload"]["guardian_gate"]["phase"] == "pre_run"
    run_start = [event for event in events if event.get("type") == "run.started"]
    assert run_start
    assert run_start[0]["payload"]["guardian_gate"]["phase"] == "pre_run"
