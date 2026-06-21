"""
File purpose:
- Central runtime controller connecting API controls, run loop, logs, and event streams.

Key classes/functions:
- MainController

Inputs/outputs:
- Input: control commands (start/pause/stop), mode toggles, run goal updates
- Output: live state snapshots and streamed events for web GUI

Dependencies:
- asyncio
- orchestrator.run_loop.RunLoop
- logging_system.run_trace.RunTrace

Modification guide:
- Safe places to edit: control command behavior and event payload shape
- Risky places to edit: run lifecycle and concurrent task handling
- Related files: app/main.py, app/bootstrap.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from agents.base_agent import AgentContext
from agents.registry import AgentRegistry
from logging_system.event_logger import log_system_event
from logging_system.logger_factory import LoggerBundle, build_logger_bundle
from logging_system.run_trace import RunTrace
from mcp_tools.tpms_geometry import (
    generate_gyroid_stl_text,
    normalize_geometry_type as normalize_tpms_geometry_type,
    write_smooth_gyroid_stl,
)
from graphs import load_graph_config, load_module_config
from orchestrator.run_loop import RunLoop
from orchestrator.langgraph_runtime import compact_runtime_payload, trim_runtime_memory
from orchestrator.state import Mode, OrchestratorState, Stage
from orchestrator.supervisor import (
    build_decision_record,
    build_mission_contract,
    build_orchestration_plan,
    build_orchestrator_control_plane_snapshot,
    build_orchestrator_followup,
    build_orchestrator_handoff_packet,
    normalize_operator_intent,
)
from policies.validation_policy import validate_agent_output
from utils.ids import make_event_id, make_experiment_id, make_run_id
from device_bridges.bambu_bridge import PrinterDeviceBridgeManager
from utils.config_loader import load_all_configs
from utils.paths import resolve_path
from utils.printer_profile import adapt_print_profile_for_provider, load_prusa_print_profile


WORKSPACE_ARTIFACT_COPY_LIMIT_BYTES = 50 * 1024 * 1024
PLANNING_TRANSCRIPT_MEMORY_LIMIT = 50
PLANNING_TRANSCRIPT_PAGE_LIMIT = 160
PLANNING_TRANSCRIPT_MAX_PAGE_LIMIT = 240


@dataclass(slots=True)
class ControllerDeps:
    """Dependency bundle injected from bootstrap."""

    agent_registry: AgentRegistry
    orchestrator_agent_name: str
    agent_context: AgentContext
    run_root: Path
    logging_config: dict[str, Any]
    system_config: dict[str, Any]
    runtime_profile: dict[str, Any]


class MainController:
    """Stateful controller for orchestrator execution and event fanout."""

    TEST_MODE_FIXED_GEOMETRY = "gyroid"
    TEST_MODE_LOOP_CYCLES = 5
    CLOSED_LOOP_FREE_SHAPE_KEYS = {
        "candidate_id",
        "specimen_id",
        "wall_thickness_mm",
        "relative_density",
        "porosity",
        "anisotropy_ratio",
        "orientation_deg",
        "defect_seed",
        "defect_ratio",
        "tpms_thickness",
        "expected_mass_g",
        "expected_volume_mm3",
        "expected_print_time_min",
        "expected_manufacturability_score",
        "expected_objective_proxy_score",
        "generation_strategy",
        "generation_reason",
        "validation_warnings",
        "candidate_pool_summary",
        "prior_results_summary",
        "failure_memory_summary",
        "model_note",
    }

    def __init__(self, deps: ControllerDeps) -> None:
        self._deps = deps
        self._trace = RunTrace(max_events=int(deps.system_config.get("event_buffer_size", 300)))
        self._event_queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._run_task: asyncio.Task[None] | None = None
        self._active_graph_id = "atr_closed_loop"
        self._active_graph_config_path: Path | None = None

        self._logger_bundle = self._new_logger_bundle()
        self._state = self._new_state(mode=Mode(deps.system_config.get("default_mode", "test")))
        self._last_completed_trace: list[dict[str, Any]] = []
        self._planning_messages: list[dict[str, Any]] = []
        self._planning_message_total = 0
        self._planning_session_id: str | None = None
        self._planning_bootstrapped = False
        self._planning_request_lock = asyncio.Lock()
        self._planning_handoff_task: asyncio.Task[dict[str, Any]] | None = None
        self._vllm_transition_task: asyncio.Task[dict[str, Any]] | None = None
        self._deps.agent_context.on_model_call = self._on_model_call
        self._deps.agent_context.on_tool_event = self._on_tool_event

    def _new_logger_bundle(self) -> LoggerBundle:
        run_id = make_run_id()
        return build_logger_bundle(
            run_id=run_id,
            run_root=self._deps.run_root,
            logging_config=self._deps.logging_config,
        )

    def _new_state(self, mode: Mode) -> OrchestratorState:
        return OrchestratorState(
            run_id=self._logger_bundle.run_dir.name,
            experiment_id=make_experiment_id(),
            active_session_id=self._logger_bundle.run_dir.name,
            mode=mode,
            stage=Stage.IDLE,
            active_goal="Build and run autonomous AI researcher loop",
            device_health={"printer": "ready", "camera": "ready", "robot": "ready", "utm": "ready"},
            run_metadata=self._runtime_profile(),
            retry_counters={},
            fault_injection={"fault": "none", "stage": ""},
        )

    def _runtime_profile(self) -> dict[str, Any]:
        """Return active backend/model metadata from the shared AgentContext."""
        if hasattr(self._deps.agent_context, "runtime_profile"):
            profile = self._deps.agent_context.runtime_profile()
            self._deps.runtime_profile.clear()
            self._deps.runtime_profile.update(profile)
            return dict(profile)
        return dict(self._deps.runtime_profile)

    @staticmethod
    def _first_failure_code(payload: Any) -> str:
        if isinstance(payload, dict):
            value = payload.get("failure_code") or payload.get("error_code") or payload.get("code")
            if value:
                return str(value)
            for item in payload.values():
                found = MainController._first_failure_code(item)
                if found:
                    return found
        if isinstance(payload, list):
            for item in payload:
                found = MainController._first_failure_code(item)
                if found:
                    return found
        return ""

    @staticmethod
    def _hardware_alert_component(workspace: str, tool: str, failure_code: str, message: str) -> tuple[str, str, str]:
        code = failure_code.upper()
        text = f"{tool} {message}".lower()
        if workspace == "lerobot" or code.startswith("LEROBOT"):
            if "CAMERA" in code or "camera" in text:
                return "robot", "camera", "Robot camera stream/capture path"
            if "POLICY" in code:
                return "robot", "policy_runtime", "Pi0.5/LeRobot policy checkpoint/runtime"
            if "CALIBRATION" in code:
                return "robot", "calibration", "ROBOTIS leader/follower calibration"
            if "ROLLOUT_ALREADY_ACTIVE" in code:
                return "robot", "rollout_scheduler", "LeRobot rollout concurrency guard"
            if "PORT" in code:
                return "robot", "robot_io_port", "ROBOTIS follower/leader serial port"
            if "PROCESS" in code or "RUNTIME" in code:
                return "robot", "pi05_runtime", "Pi0.5 conda/runtime process"
            return "robot", "lerobot_bridge", "LeRobot bridge"
        if workspace == "printer" or code.startswith("PRINTER") or code.startswith("SLICER") or code.startswith("GCODE") or code.startswith("BAMBU"):
            if code.startswith("BAMBU"):
                if "FTPS" in code or "UPLOAD" in code or "STORAGE" in code:
                    return "printer", "bambu_ftps_storage", "Bambu Lab FTPS storage/upload path"
                if "MQTT" in code:
                    return "printer", "bambu_mqtt", "Bambu Lab MQTT telemetry/control bridge"
                if "AUTOEJECTION" in code:
                    return "printer", "bambu_autoejection", "Bambu Lab autoejection routine gate"
                return "printer", "bambu_bridge", "Bambu Lab device bridge"
            if code.startswith("SLICER"):
                return "printer", "slicer", "PrusaSlicer pipeline"
            if code.startswith("GCODE"):
                return "printer", "gcode_safety", "Prusa MK4S G-code safety gate"
            if "STORAGE" in code or "UPLOAD" in code:
                return "printer", "prusabridge_storage", "PrusaLink storage/upload path"
            if "START" in code or "READY" in code or "JOB" in code:
                return "printer", "prusabridge_job", "PrusaLink print job state"
            return "printer", "prusalink", "Prusa MK4S bridge"
        if workspace == "equipment" or code.startswith("PYAUTOGUI"):
            if "TOKEN" in code or "URL" in code or "UNREACHABLE" in code:
                return "equipment", "windows_pyautogui_bridge", "Windows PyAutoGUI bridge connection"
            return "equipment", "lab_equipment_program", "Lab equipment macro/program bridge"
        if workspace == "cae" or code.startswith("CAE"):
            return "analysis", "cae_solver", "CAE/FEM solver bridge"
        if code.startswith("UTM"):
            return "equipment", "utm_bridge", "UTM data/acquisition bridge"
        return workspace or "hardware", "device_bridge", "Hardware bridge"

    @staticmethod
    def _hardware_alert_severity(failure_code: str, status: str) -> str:
        code = failure_code.upper()
        clean_status = status.lower()
        if any(token in code for token in ("UNSAFE", "EMERGENCY", "STOP_FAILED", "COLLISION")):
            return "critical"
        if "ALREADY_ACTIVE" in code or clean_status in {"busy", "retryable", "waiting"}:
            return "warning"
        if failure_code or clean_status in {"blocked", "failed", "error", "not_enabled"}:
            return "blocking"
        return "warning"

    @staticmethod
    def _hardware_alert_recovery_hint(device_class: str, component: str, failure_code: str) -> str:
        code = failure_code.upper()
        if component == "robot_io_port":
            return "Reconnect/check ROBOTIS follower/leader USB, rerun port detection, then retry the same stage."
        if component == "camera":
            return "Check camera cable/index/by-id mapping, run camera test, then refresh Vision/Manipulation readiness."
        if component == "policy_runtime":
            return "Select a valid local policy checkpoint or policy repo, then rerun rollout preflight."
        if component == "calibration":
            return "Run LeRobot calibration interactively in terminal, then retry GUI rollout/teleoperation."
        if component == "rollout_scheduler":
            return "Stop the active rollout session before starting another inference request."
        if component == "pi05_runtime":
            return "Inspect the Pi0.5 session log, conda env, CUDA availability, and policy compatibility."
        if device_class == "printer":
            return "Check PrusaLink status, connection memory, storage, slicer/G-code gate, then rerun printer preflight."
        if device_class == "equipment":
            return "Check the selected equipment bridge host/token/program list, then rerun the bridge test."
        if device_class == "analysis":
            return "Check solver installation/input mesh/BC settings, then rerun CAE analysis."
        if "REQUIRED" in code:
            return "Fill the required configuration field and rerun preflight."
        return "Inspect the hardware workspace status and rerun the affected device preflight."

    @staticmethod
    def _guardian_reason_code(device_class: str, component: str, failure_code: str, status: str) -> str:
        code = failure_code.upper()
        clean_status = status.lower()
        if "REQUIRED" in code:
            return "MISSING_REQUIRED_INPUT"
        if component == "policy_runtime":
            return "ROBOT_POLICY_UNAPPROVED"
        if component in {"robot_io_port", "camera", "windows_pyautogui_bridge", "prusalink", "prusabridge_storage"}:
            return "HEARTBEAT_LOST" if "UNREACHABLE" in code or "LOST" in code else "DEVICE_UNHEALTHY"
        if component == "rollout_scheduler":
            return "HUMAN_APPROVAL_REQUIRED" if "ALREADY_ACTIVE" in code else "ROBOT_ACTION_OUT_OF_BOUNDS"
        if component == "lab_equipment_program":
            return "UTM_MACRO_MISMATCH"
        if device_class == "printer":
            return "DEVICE_UNHEALTHY"
        if device_class == "analysis":
            return "DATA_QUALITY_LOW"
        if clean_status in {"blocked", "failed", "error", "not_enabled"}:
            return "DEVICE_UNHEALTHY"
        return "CONTRACT_SCHEMA_INVALID"

    @staticmethod
    def _guardian_risk_score(severity: str) -> float:
        if severity == "critical":
            return 0.93
        if severity == "blocking":
            return 0.78
        if severity == "warning":
            return 0.45
        return 0.25

    @staticmethod
    def _guardian_action_for_severity(severity: str) -> str:
        if severity == "critical":
            return "safe_stop"
        if severity == "blocking":
            return "block"
        if severity == "warning":
            return "allow_with_warning"
        return "allow"

    @staticmethod
    def _guardian_risk_vector(device_class: str, severity: str) -> dict[str, float]:
        base = MainController._guardian_risk_score(severity)
        vector = {
            "hardware": min(base, 1.0),
            "vision": 0.0,
            "robot": 0.0,
            "equipment": 0.0,
            "data": 0.0,
            "optimization": 0.0,
            "self_evolution": 0.0,
            "operator": 0.0,
        }
        if device_class == "robot":
            vector["robot"] = min(base, 1.0)
        elif device_class == "equipment":
            vector["equipment"] = min(base, 1.0)
        elif device_class == "printer":
            vector["hardware"] = min(max(base, 0.55), 1.0)
            vector["equipment"] = max(vector["equipment"], min(base * 0.6, 1.0))
        elif device_class == "analysis":
            vector["data"] = min(base, 1.0)
        else:
            vector["hardware"] = min(base, 1.0)
        return vector

    def _hardware_alert_for_result(
        self,
        *,
        workspace: str,
        tool: str,
        result: dict[str, Any],
        stage: Stage | None,
        agent: str,
        workflow: str,
        status: str,
    ) -> dict[str, Any] | None:
        failure_code = self._first_failure_code(result)
        if bool(result.get("ok", False)) and not failure_code:
            return None
        if not failure_code and status.lower() not in {"blocked", "failed", "error", "not_enabled"}:
            return None
        message = str(result.get("message") or result.get("error") or result.get("status") or failure_code or "hardware alert")
        device_class, component, hardware = self._hardware_alert_component(workspace, tool, failure_code, message)
        severity = self._hardware_alert_severity(failure_code, status)
        blocks_workflow = severity in {"blocking", "critical"}
        reason_code = self._guardian_reason_code(device_class, component, failure_code, status)
        guardian_decision = self._guardian_action_for_severity(severity)
        risk_score = self._guardian_risk_score(severity)
        risk_vector = self._guardian_risk_vector(device_class, severity)
        alert_id = make_event_id()
        stage_value = stage.value if isinstance(stage, Stage) else workspace
        created_at = datetime.now(timezone.utc).isoformat()
        contract = {
            "schema_version": "guardian_contract.v1",
            "run_id": self._state.run_id,
            "loop_id": int(self._state.loop_count),
            "stage": stage_value,
            "status": "blocked" if blocks_workflow else "warning",
            "confidence": 1.0,
            "artifact_refs": [],
            "provenance_refs": [alert_id],
            "requires_human_approval": blocks_workflow,
            "ok_for_next_stage": not blocks_workflow,
            "ok_for_bo": False,
            "failure_code": failure_code or status,
            "risk_flags": [reason_code, device_class, component],
        }
        decision_record = {
            "schema": "guardian_decision.v1",
            "decision_id": alert_id,
            "decision": guardian_decision,
            "reason_code": reason_code,
            "risk_score": risk_score,
            "risk_vector": risk_vector,
            "dominant_risks": [key for key, value in risk_vector.items() if value >= 0.5],
            "requires_human_approval": blocks_workflow,
            "recommended_action": guardian_decision,
        }
        recovery_hint = self._hardware_alert_recovery_hint(device_class, component, failure_code)
        incident_record = {
            "schema": "incident_record.v1",
            "incident_id": alert_id,
            "run_id": self._state.run_id,
            "experiment_id": self._state.experiment_id,
            "stage": stage_value,
            "source": "hardware_alert",
            "risk_class": device_class,
            "component": component,
            "severity": severity,
            "reason_code": reason_code,
            "failure_code": failure_code or status,
            "message": message,
            "detected_by": ["controller", "guardian_sidecar"],
            "guardian_decision": guardian_decision,
            "corrective_action": recovery_hint,
            "created_at": created_at,
        }
        return {
            "schema": "hardware_alert.v1",
            "alert_id": alert_id,
            "device_class": device_class,
            "device": hardware,
            "component": component,
            "workspace": workspace,
            "tool": tool,
            "agent": agent,
            "stage": stage_value,
            "workflow": workflow or str(result.get("workflow") or tool),
            "severity": severity,
            "failure_code": failure_code or status,
            "status": status,
            "message": message,
            "blocks_workflow": blocks_workflow,
            "requires_ack": blocks_workflow,
            "guardian_route_hint": "stop" if severity == "critical" else "recover" if blocks_workflow else "continue_with_warning",
            "reason_code": reason_code,
            "risk_score": risk_score,
            "risk_vector": risk_vector,
            "guardian_contract": contract,
            "guardian_decision": decision_record,
            "incident_record": incident_record,
            "recovery_hint": recovery_hint,
            "created_at": created_at,
        }

    def _append_guardian_event(self, event: dict[str, Any]) -> None:
        """Append Guardian-readable incidents without relying only on in-memory state."""
        try:
            path = self._logger_bundle.run_dir / "guardian_events.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True, default=str) + "\n")
        except Exception:
            return

    def _record_incident_records(self, records: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
        stored = self._state.run_metadata.setdefault("incident_records", [])
        if not isinstance(stored, list):
            stored = []
            self._state.run_metadata["incident_records"] = stored
        seen = {str(item.get("incident_id") or item.get("id") or "") for item in stored if isinstance(item, dict)}
        for record in records:
            if not isinstance(record, dict):
                continue
            copied = dict(record)
            incident_id = str(copied.get("incident_id") or copied.get("id") or "")
            if incident_id and incident_id in seen:
                continue
            stored.append(copied)
            if incident_id:
                seen.add(incident_id)
            self._append_guardian_event(copied)
        del stored[:-100]

    def _record_hardware_alert(self, alert: dict[str, Any]) -> None:
        alerts = self._state.run_metadata.setdefault("hardware_alerts", [])
        if not isinstance(alerts, list):
            alerts = []
            self._state.run_metadata["hardware_alerts"] = alerts
        alerts.append(alert)
        del alerts[:-50]
        guardian_decision = alert.get("guardian_decision")
        if isinstance(guardian_decision, dict):
            self._state.run_metadata["latest_guardian_decision"] = guardian_decision
        incident_record = alert.get("incident_record")
        if isinstance(incident_record, dict):
            self._record_incident_records([incident_record])
        device_class = str(alert.get("device_class") or "hardware")
        failure_code = str(alert.get("failure_code") or alert.get("status") or "alert")
        severity = str(alert.get("severity") or "warning")
        if device_class:
            self._state.device_health[device_class] = f"{severity}:{failure_code}"

    async def _on_model_call(self, *, task_type: str, model: str, role: str, backend: str) -> None:
        """Keep active vLLM deployments warm while a Live GUI/run workflow is progressing."""
        if backend != "vllm" or self._deps.agent_context.active_backend != "vllm":
            return
        self._cancel_pending_vllm_transition()

    @staticmethod
    def _equipment_step_message_type(step: str, status: str) -> str:
        step_upper = str(step or "").upper()
        status_lower = str(status or "").lower()
        if status_lower in {"blocked", "failed", "error"}:
            return "warning"
        if any(token in step_upper for token in ("PULL_ARTIFACT", "PARSE_PROBE", "SAVE_EXPORT", "WAIT_FOR_EXPORT")):
            return "artifact"
        if "SCREEN" in step_upper or "ASSERT" in step_upper:
            return "signal"
        if "DONE" in step_upper:
            return "handoff"
        return "tool_call"

    @staticmethod
    def _equipment_step_label(step: str) -> str:
        step_upper = str(step or "").upper()
        if "SCREEN" in step_upper or "ASSERT" in step_upper:
            return "화면 상태 검증"
        if "PHYSICAL" in step_upper or "MOTION" in step_upper:
            return "물리 동작 검증"
        if "SAVE" in step_upper or "EXPORT" in step_upper:
            return "저장/내보내기"
        if "PULL_ARTIFACT" in step_upper:
            return "Linux 데이터 회수"
        if "PARSE" in step_upper:
            return "데이터 파싱 검증"
        if "FOCUS" in step_upper:
            return "UTM 창 포커스"
        if "START" in step_upper or "EXECUTE" in step_upper:
            return "등록 프로토콜 실행"
        if "DONE" in step_upper:
            return "장비 단계 완료"
        return "장비 제어"

    @staticmethod
    def _equipment_event_metadata(event: dict[str, Any]) -> dict[str, Any]:
        step = str(event.get("step") or "")
        step_upper = step.upper()
        status = str(event.get("status") or "unknown")
        detail = str(event.get("detail") or "")
        command_id = str(event.get("command_id") or event.get("sequence_id") or "")
        program_id = str(event.get("program_id") or "")
        target_ui = str(
            event.get("target_ui")
            or event.get("target_window")
            or event.get("window_title")
            or event.get("target_app")
            or ("UTM software" if program_id.startswith("utm_") else "")
        )
        data_file_ref = str(event.get("data_file_ref") or event.get("linux_path") or event.get("local_path") or event.get("windows_path") or detail or "")
        failure_code = str(event.get("failure_code") or event.get("code") or "")
        metadata: dict[str, Any] = {
            "command_id": command_id,
            "program_id": program_id,
            "windows_host": str(event.get("windows_host") or event.get("bridge_host") or event.get("host") or ""),
            "macro_command": {
                "command_id": command_id,
                "program_id": program_id,
                "step": step,
                "status": status,
                "target_ui": target_ui,
                "detail": detail,
            },
        }
        if "SCREEN" in step_upper or "ASSERT" in step_upper:
            metadata["visual_assertion"] = {
                "step": step,
                "status": status,
                "detail": detail,
                "checkpoint": str(event.get("checkpoint") or detail or step),
                "confidence": event.get("confidence"),
                "screenshot_artifact": event.get("screenshot_artifact") or event.get("artifact_id"),
                "target_ui": target_ui,
                "ok": status not in {"blocked", "failed", "error"},
            }
        if "PHYSICAL" in step_upper or "MOTION" in step_upper:
            metadata["physical_cross_check"] = {
                "step": step,
                "status": status,
                "detail": detail,
                "check_id": event.get("check_id"),
                "target_ui": target_ui,
                "ok": status not in {"blocked", "failed", "error"},
            }
        if any(token in step_upper for token in ("SAVE", "EXPORT", "PULL_ARTIFACT", "PARSE", "WAIT_FOR_FILE")):
            metadata["data_file_ref"] = data_file_ref
            metadata["data_acquisition"] = {
                "step": step,
                "status": status,
                "detail": detail,
                "artifact_or_path": data_file_ref,
                "windows_path": event.get("windows_path"),
                "linux_path": event.get("linux_path") or event.get("local_path"),
                "sha256": event.get("sha256"),
                "size_bytes": event.get("size_bytes"),
                "row_count_probe": event.get("row_count_probe"),
                "columns_probe": event.get("columns_probe"),
                "save_method": event.get("save_method"),
                "artifact_pull_status": event.get("artifact_pull_status"),
                "parse_probe": "PARSE" in step_upper,
            }
        if status in {"blocked", "failed", "error"}:
            metadata["recovery"] = {
                "status": "operator_review_required",
                "failure_step": step,
                "failure_code": failure_code,
                "failure_detail": detail,
                "recommended_action": "장비 화면, Windows bridge log, Vision cross-check, UTM export artifact를 확인한 뒤 재시도하세요.",
            }
        return {key: value for key, value in metadata.items() if value not in (None, "", {}, [])}

    async def _on_tool_event(self, event: dict[str, Any]) -> None:
        """Stream hardware tool step progress into the Live GUI conversation."""
        if not self._planning_bootstrapped or not isinstance(event, dict):
            return
        tool = str(event.get("tool", ""))
        if tool not in {"printer.prepare", "equipment.pyautogui.run", "vision.equipment_cross_check", "guardian.tool_shield"} and not tool.startswith("lerobot."):
            return
        step = str(event.get("step", "STEP"))
        status = str(event.get("status", "unknown"))
        status_key = status.strip().lower()
        detail = event.get("detail")
        suffix = f" ({detail})" if detail not in (None, "") else ""
        attention_statuses = {"blocked", "failed", "error", "warning", "approval_required"}
        needs_operator_attention = status_key in attention_statuses or any(
            bool(event.get(key))
            for key in (
                "requires_human_approval",
                "requires_approval",
                "requires_response",
                "pending_operator_input",
                "blocks_workflow",
            )
        )
        tool_event_role = str(event.get("role") or "").strip()
        if not tool_event_role:
            if tool == "guardian.tool_shield":
                tool_event_role = "guardian_ai"
            elif tool.startswith("lerobot."):
                tool_event_role = "manipulation_ai"
            elif tool in {"equipment.pyautogui.run", "vision.equipment_cross_check"}:
                tool_event_role = "equipment_ai"
            else:
                tool_event_role = "printer_ai"
        if not needs_operator_attention:
            await self._broadcast_controller_event(
                {
                    "event_id": make_event_id(),
                    "run_id": self._state.run_id,
                    "experiment_id": self._state.experiment_id,
                    "timestamp_stage": self._state.stage.value,
                    "event_type": "planning_tool_step",
                    "type": "tool.step",
                    "level": "INFO",
                    "severity": "info",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "graph_id": "atr_closed_loop",
                    "node_id": self._state.stage.value,
                    "module_id": self._state.stage.value,
                    "agent": self._planning_agent_id_for_role(tool_event_role),
                    "status": status,
                    "message": f"{tool} step {step} {status}{suffix}",
                    "payload": {
                        "surface": ["backend", "io"],
                        "visibility": "internal",
                        "tool": tool,
                        "step": step,
                        "status": status,
                        "detail": detail,
                        "check_id": event.get("check_id", ""),
                        "program_id": event.get("program_id", ""),
                        "sequence_id": event.get("sequence_id", ""),
                        "source": "live_gui_tool_event",
                    },
                    "state": self._state.model_dump(mode="json"),
                }
            )
            return
        if tool == "guardian.tool_shield":
            shielded_tool = str(event.get("shielded_tool") or "runtime tool")
            decision = str(event.get("decision") or status)
            reason_code = str(event.get("reason_code") or detail or "")
            gate = event.get("guardian_gate") if isinstance(event.get("guardian_gate"), dict) else {}
            message_type = "approval" if event.get("requires_human_approval") else "warning" if status in {"warning", "approval_required"} else "incident" if status in {"blocked", "failed", "error"} else "status"
            await self._append_planning_message(
                {
                    "schema": "live_chat_message.v1",
                    "role": "guardian_ai",
                    "message_type": message_type,
                    "content": f"Guardian action shield: {shielded_tool} -> {decision}{suffix}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "guardian_agent",
                    "ok": status_key not in attention_statuses,
                    "tool": tool,
                    "shielded_tool": shielded_tool,
                    "decision": decision,
                    "reason_code": reason_code,
                    "risk_score": event.get("risk_score", gate.get("risk_score", 0.0)),
                    "guardian_gate": gate,
                    "guardian_decision": event.get("guardian_decision", gate.get("guardian_decision", {})),
                    "guardian_contract": event.get("guardian_contract", gate.get("guardian_contract", {})),
                    "requires_human_approval": bool(event.get("requires_human_approval")),
                    "blocks_workflow": bool(event.get("blocks_workflow")),
                    "guardian_runtime_event": event,
                },
                event_type="planning_guardian_tool_shield",
                message=f"guardian.tool_shield {shielded_tool} {decision}",
                level="ERROR" if status_key in {"blocked", "failed", "error"} else "WARNING" if status_key in {"warning", "approval_required"} else "INFO",
            )
            return
        if tool.startswith("lerobot."):
            await self._append_planning_message(
                {
                    "role": "manipulation_ai",
                    "content": f"Manipulation Agent / LeRobot 단계 진행: {step} -> {status}{suffix}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "manipulation_agent",
                    "ok": status_key not in attention_statuses,
                    "lerobot_runtime_event": event,
                },
                event_type="planning_lerobot_step",
                message=f"{tool} step {step} {status}",
                level="ERROR" if status_key in {"blocked", "failed", "error"} else "WARNING" if status_key in {"warning", "approval_required"} else "INFO",
            )
            return
        if tool == "vision.equipment_cross_check":
            check_id = str(event.get("check_id") or "")
            check_suffix = f" · check={check_id}" if check_id else ""
            await self._append_planning_message(
                {
                    "schema": "live_chat_message.v1",
                    "role": "equipment_ai",
                    "message_type": "signal" if step.startswith("VISION_CHECK:") else "status",
                    "content": f"Equipment Agent Vision 물리검증: {step} -> {status}{check_suffix}{suffix}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "equipment_agent",
                    "ok": status_key not in attention_statuses,
                    "tool": tool,
                    "check_id": check_id,
                    "equipment_runtime_event": event,
                    "vision_cross_check_event": event,
                },
                event_type="planning_equipment_vision_check",
                message=f"vision.equipment_cross_check step {step} {status}",
                level="ERROR" if status_key in {"blocked", "failed", "error"} else "WARNING" if status_key in {"warning", "approval_required"} else "INFO",
            )
            return
        if tool == "equipment.pyautogui.run":
            semantic_label = self._equipment_step_label(step)
            metadata = self._equipment_event_metadata(event)
            message_type = self._equipment_step_message_type(step, status)
            await self._append_planning_message(
                {
                    "schema": "live_chat_message.v1",
                    "role": "equipment_ai",
                    "message_type": message_type,
                    "content": f"Equipment Agent {semantic_label}: {step} -> {status}{suffix}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "equipment_agent",
                    "ok": status_key not in attention_statuses,
                    "tool": tool,
                    "equipment_runtime_event": event,
                    **metadata,
                },
                event_type="planning_equipment_step",
                message=f"equipment.pyautogui.run step {step} {status}",
                level="ERROR" if status_key in {"blocked", "failed", "error"} else "WARNING" if status_key in {"warning", "approval_required"} else "INFO",
            )
            return
        await self._append_planning_message(
            {
                "role": "printer_ai",
                "content": f"Specimen Making Agent 단계 진행: {step} -> {status}{suffix}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "specimen_agent",
                "ok": status_key not in attention_statuses,
                "printer_runtime_event": event,
            },
            event_type="planning_printer_step",
            message=f"printer.prepare step {step} {status}",
            level="ERROR" if status_key in {"blocked", "failed", "error"} else "WARNING" if status_key in {"warning", "approval_required"} else "INFO",
        )

    def _apply_inference_backend(self, backend: str | None) -> None:
        """Switch the central inference backend without touching individual agents."""
        clean_backend = str(backend or "").strip().lower()
        if not clean_backend:
            self._merge_runtime_profile_metadata()
            return
        if self._run_task and not self._run_task.done():
            raise RuntimeError("Cannot switch inference backend while a run is active.")
        self._deps.agent_context.set_active_backend(clean_backend)
        self._merge_runtime_profile_metadata()

    def _merge_runtime_profile_metadata(self) -> None:
        """Refresh backend/model metadata without discarding run evidence."""
        runtime_profile = self._runtime_profile()
        existing = self._state.run_metadata if isinstance(self._state.run_metadata, dict) else {}
        self._state.run_metadata = {**existing, **runtime_profile}

    def _log_controller_event(self, event: dict[str, Any]) -> None:
        """Persist controller-origin Runtime IDE events to the structured run log."""
        try:
            payload = dict(event.get("payload", {})) if isinstance(event.get("payload"), dict) else {}
            payload.setdefault("runtime_event_type", event.get("type", event.get("event_type", "")))
            payload.setdefault("graph_id", event.get("graph_id", ""))
            payload.setdefault("node_id", event.get("node_id", ""))
            payload.setdefault("module_id", event.get("module_id", ""))
            payload.setdefault("status", event.get("status", ""))
            log_system_event(
                self._logger_bundle.logger,
                run_id=str(event.get("run_id") or self._state.run_id),
                level=str(event.get("level") or event.get("severity") or "INFO"),
                event_type=str(event.get("type") or event.get("event_type") or "runtime.event"),
                message=str(event.get("message") or "Runtime event"),
                payload=payload,
            )
        except Exception:
            return

    async def _broadcast_controller_event(self, event: dict[str, Any]) -> None:
        """Persist and broadcast a controller-origin Runtime IDE event."""
        self._log_controller_event(event)
        await self._broadcast_event(event)

    @staticmethod
    def _compact_event_payload_for_display(payload: Any) -> dict[str, Any]:
        """Return a tiny event payload for high-frequency Live GUI polling."""
        if not isinstance(payload, dict):
            return {}
        keep = {
            "agent", "agent_id", "node_id", "module_id", "stage", "status", "mode", "ok",
            "workspace", "workflow", "step", "detail", "surface", "visibility",
            "tool", "tool_name", "requested_tool", "program_id", "check_id",
            "sequence_id",
            "failure_code", "reason_code", "decision", "risk_score", "title", "reason",
            "requires_human_approval", "requires_approval", "safety_class", "approval_id",
            "artifact_id", "artifact_path", "report_url", "preview_url", "stl_url",
            "graph_id", "run_id", "experiment_id", "summary", "message", "action",
            "compiled_graph", "errors", "graph_hash", "graph_version", "graph_version_id",
            "graph_version_path", "source", "source_action", "latest", "target_agent_id", "selected_agent_id",
            "target_agent", "target_node_id", "target_event_key",
            "selected_agent", "selected_agent_label", "selected_view", "ask_scope",
            "selected_node_id", "selected_graph_node_id", "trace_id", "selected_trace_id",
            "event_key", "selected_event_key", "selected_event_id", "selected_event_type",
            "selected_report_section", "selected_report_section_text",
            "selected_report_section_text_excerpt", "run_context", "live_run_id",
            "live_mode", "live_stage", "live_is_running", "live_active_goal",
            "chat_mode", "chat_target_mode", "pinned_finding", "pinned_at", "reviewed_at",
            "attention_kind", "attention_action", "attention_event_key", "attention_event_type",
            "attention_agent_id", "attention_node_id", "attention_trace_id", "attention_message",
            "operator_source",
        }
        out: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            if key_text in keep:
                if isinstance(value, (str, int, float, bool)) or value is None:
                    text = str(value) if isinstance(value, str) else value
                    out[key_text] = text[:500] if isinstance(text, str) else text
                elif isinstance(value, list):
                    out[key_text] = value[:8]
                elif isinstance(value, dict):
                    out[key_text] = {str(k): v for k, v in list(value.items())[:12] if isinstance(v, (str, int, float, bool)) or v is None}
            elif key_text in {"guardian_gate", "guardian_decision", "guardian_contract"} and isinstance(value, dict):
                out[key_text] = {
                    str(k): value.get(k)
                    for k in ("gate_id", "stage", "phase", "decision", "reason_code", "risk_score", "ok_for_next_stage", "ok_for_bo")
                    if k in value
                }
            elif key_text == "artifact" and isinstance(value, dict):
                out[key_text] = {
                    str(k): value.get(k)
                    for k in ("path", "key", "type", "label", "kind", "mime_type")
                    if k in value and (isinstance(value.get(k), (str, int, float, bool)) or value.get(k) is None)
                }
        return out

    def _compact_event_for_buffer(self, event: dict[str, Any]) -> dict[str, Any]:
        """Store display-sized events in RAM; durable evidence remains in logs/artifacts."""
        compact = {
            "event_id": event.get("event_id", ""),
            "run_id": event.get("run_id", ""),
            "experiment_id": event.get("experiment_id", ""),
            "timestamp_stage": event.get("timestamp_stage", ""),
            "event_type": event.get("event_type", event.get("type", "")),
            "type": event.get("type", event.get("event_type", "")),
            "level": event.get("level", event.get("severity", "INFO")),
            "severity": event.get("severity", str(event.get("level", "INFO")).lower()),
            "message": str(event.get("message", ""))[:600],
            "ts": event.get("ts", event.get("timestamp", "")),
            "timestamp": event.get("timestamp", event.get("ts", "")),
            "graph_id": event.get("graph_id", "atr_closed_loop"),
            "node_id": event.get("node_id", ""),
            "module_id": event.get("module_id", ""),
            "agent": event.get("agent", ""),
            "status": event.get("status", ""),
            "payload": self._compact_event_payload_for_display(event.get("payload", {})),
        }
        return {key: value for key, value in compact.items() if value not in (None, "")}

    async def _broadcast_event(self, event: dict[str, Any]) -> None:
        compact_event = self._compact_event_for_buffer(event)
        self._trace.add(compact_event)
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._event_queues:
            try:
                queue.put_nowait(compact_event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self._event_queues.discard(queue)

    def _workspace_artifact_payloads(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract artifact-like workspace outputs for Runtime IDE lineage."""
        artifacts: list[dict[str, Any]] = []

        def walk(value: Any, path: str) -> None:
            if isinstance(value, dict):
                key = path.split(".")[-1]
                has_artifact_fields = any(
                    field in value
                    for field in {
                        "path",
                        "url",
                        "preview_url",
                        "download_url",
                        "stl_path",
                        "sliced_path",
                        "gcode_path",
                        "log_path",
                        "dataset_path",
                        "checkpoint_path",
                        "output_dir",
                        "report_url",
                        "contour_url",
                    }
                )
                if key in {"artifact", "artifacts", "specimen_artifacts", "fem_artifacts"} or has_artifact_fields:
                    artifacts.append({"key": path or "result", "value": value})
                for child_key, child in value.items():
                    walk(child, f"{path}.{child_key}" if path else str(child_key))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}[{index}]")

        walk(result, "result")
        return artifacts


    @staticmethod
    def _safe_workspace_artifact_segment(value: str, fallback: str = "artifact") -> str:
        """Return a filesystem-safe path segment for workspace artifacts."""
        clean = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
        return clean[:120] or fallback

    def _workspace_artifact_dir(self, workspace: str) -> Path:
        """Return the run-local directory used for dedicated workspace artifacts."""
        safe_workspace = self._safe_workspace_artifact_segment(workspace, "workspace")
        output_dir = self._logger_bundle.run_dir / "workspace" / safe_workspace
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _workspace_artifact_relpath(self, path: Path) -> str:
        """Return a run-relative artifact path for Runtime IDE file APIs."""
        try:
            return path.resolve().relative_to(self._logger_bundle.run_dir.resolve()).as_posix()
        except ValueError:
            return path.name

    def _write_workspace_result_artifact(self, *, workspace: str, tool: str, result: dict[str, Any]) -> dict[str, Any] | None:
        """Persist the raw workspace result as a run artifact for replay/debug evidence."""
        try:
            output_dir = self._workspace_artifact_dir(workspace)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            safe_tool = self._safe_workspace_artifact_segment(tool.replace(".", "_"), "tool")
            path = output_dir / f"{stamp}_{safe_tool}_result.json"
            path.write_text(json.dumps(result, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
            return {
                "key": "workspace.result",
                "path": self._workspace_artifact_relpath(path),
                "name": path.name,
                "source": "workspace_result",
                "workspace": workspace,
                "tool": tool,
            }
        except Exception as exc:
            return {
                "key": "workspace.result",
                "path": "",
                "name": "",
                "source": "workspace_result",
                "workspace": workspace,
                "tool": tool,
                "error": f"{exc.__class__.__name__}: {exc}",
            }

    @staticmethod
    def _iter_workspace_file_candidates(value: Any, path: str = "result") -> list[tuple[str, str]]:
        """Return likely local file paths embedded in a workspace result."""
        path_keys = {
            "path",
            "stl_path",
            "sliced_path",
            "gcode_path",
            "log_path",
            "dataset_path",
            "checkpoint_path",
            "input_path",
            "report_path",
            "contour_svg_path",
            "artifact_path",
            "result_file",
        }
        candidates: list[tuple[str, str]] = []
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if key in path_keys and isinstance(child, str) and child.strip():
                    candidates.append((child_path, child.strip()))
                candidates.extend(MainController._iter_workspace_file_candidates(child, child_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                candidates.extend(MainController._iter_workspace_file_candidates(child, f"{path}[{index}]"))
        return candidates

    def _resolve_workspace_source_path(self, value: str) -> Path:
        """Resolve an artifact source path relative to the project root when needed."""
        source = Path(value).expanduser()
        if source.is_absolute():
            return source.resolve()
        return (self._deps.run_root.parent / source).resolve()

    def _copy_workspace_file_artifact(self, *, workspace: str, key: str, source_value: str) -> dict[str, Any] | None:
        """Copy a workspace-produced file into the current run directory, or store a pointer for large files."""
        try:
            source = self._resolve_workspace_source_path(source_value)
            if not source.exists() or not source.is_file():
                return None
            output_dir = self._workspace_artifact_dir(workspace)
            digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:10]
            safe_key = self._safe_workspace_artifact_segment(key.replace(".", "_").replace("[", "_").replace("]", ""), "file")
            target_name = f"{safe_key}_{digest}_{source.name}"
            target = output_dir / target_name
            size = source.stat().st_size
            if size <= WORKSPACE_ARTIFACT_COPY_LIMIT_BYTES:
                if source.resolve() != target.resolve():
                    shutil.copy2(source, target)
                copied = True
            else:
                target = output_dir / f"{target_name}.pointer.json"
                target.write_text(
                    json.dumps(
                        {
                            "source_path": str(source),
                            "source_size_bytes": size,
                            "reason": "source file exceeded workspace artifact copy limit",
                            "copy_limit_bytes": WORKSPACE_ARTIFACT_COPY_LIMIT_BYTES,
                        },
                        indent=2,
                        ensure_ascii=True,
                    ),
                    encoding="utf-8",
                )
                copied = False
            return {
                "key": key,
                "path": self._workspace_artifact_relpath(target),
                "name": target.name,
                "source_path": str(source),
                "source_size_bytes": size,
                "copied": copied,
                "workspace": workspace,
            }
        except Exception as exc:
            return {
                "key": key,
                "path": "",
                "name": "",
                "source_path": source_value,
                "workspace": workspace,
                "error": f"{exc.__class__.__name__}: {exc}",
            }

    @staticmethod
    def _bo_strategies_from_result(result: dict[str, Any]) -> dict[str, Any]:
        """Extract benchmark strategy payloads from BO workspace result shapes."""
        if isinstance(result.get("strategies"), dict):
            return result["strategies"]
        benchmark = result.get("benchmark") if isinstance(result.get("benchmark"), dict) else {}
        if isinstance(benchmark.get("strategies"), dict):
            return benchmark["strategies"]
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        bo_result = data.get("bo_result") if isinstance(data.get("bo_result"), dict) else {}
        benchmark = bo_result.get("benchmark") if isinstance(bo_result.get("benchmark"), dict) else {}
        if isinstance(benchmark.get("strategies"), dict):
            return benchmark["strategies"]
        return {}

    def _write_bo_plot_artifact(self, *, workspace: str, result: dict[str, Any]) -> dict[str, Any] | None:
        """Write a compact BO progress/acquisition SVG for Runtime IDE artifact lineage."""
        strategies = self._bo_strategies_from_result(result)
        if not strategies:
            return None
        colors = ["#1d4ed8", "#047857", "#b45309", "#be123c"]
        width, height = 760, 360
        margin_left, margin_right, margin_top, margin_bottom = 70, 30, 48, 64
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom
        series: list[tuple[str, list[tuple[float, float]]]] = []
        values: list[float] = []
        max_step = 1.0
        for name, payload in strategies.items():
            if not isinstance(payload, dict):
                continue
            points: list[tuple[float, float]] = []
            for item in payload.get("curve", []):
                if not isinstance(item, dict) or item.get("best_score") is None:
                    continue
                try:
                    step = float(item.get("step", len(points) + 1))
                    score = float(item["best_score"])
                except (TypeError, ValueError):
                    continue
                points.append((step, score))
                values.append(score)
                max_step = max(max_step, step)
            if points:
                series.append((str(name), points))
        if not series or not values:
            return None
        min_value = min(values)
        max_value = max(values)
        span = max(max_value - min_value, 1e-9)

        def sx(step: float) -> float:
            return margin_left + ((step - 1.0) / max(max_step - 1.0, 1.0)) * plot_w

        def sy(score: float) -> float:
            return margin_top + (1.0 - ((score - min_value) / span)) * plot_h

        paths: list[str] = []
        legends: list[str] = []
        for idx, (name, points) in enumerate(series):
            color = colors[idx % len(colors)]
            commands = " ".join(f"{'M' if point_idx == 0 else 'L'} {sx(step):.2f} {sy(score):.2f}" for point_idx, (step, score) in enumerate(points))
            circles = "\n".join(
                f'<circle cx="{sx(step):.2f}" cy="{sy(score):.2f}" r="4.2" fill="{color}" stroke="#ffffff" stroke-width="1.5"/>'
                for step, score in points
            )
            paths.append(f'<path d="{commands}" fill="none" stroke="{color}" stroke-width="2.8"/>\n{circles}')
            legends.append(
                f'<g transform="translate({margin_left + idx * 150}, 326)"><rect width="14" height="14" rx="3" fill="{color}"/>'
                f'<text x="22" y="12" font-family="Arial, sans-serif" font-size="13" fill="#334155">{name}</text></g>'
            )
        latest_trace = ""
        bo_payload = strategies.get("bo") if isinstance(strategies.get("bo"), dict) else {}
        surrogate = bo_payload.get("surrogate_trace") if isinstance(bo_payload.get("surrogate_trace"), list) else []
        if surrogate:
            last = surrogate[-1] if isinstance(surrogate[-1], dict) else {}
            selected = last.get("selected") if isinstance(last.get("selected"), dict) else {}
            latest_trace = (
                f"latest acquisition={last.get('acquisition', '')}, "
                f"selected={selected.get('candidate_id', '')}, "
                f"value={selected.get('acquisition_value', '')}"
            )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
            '<rect width="100%" height="100%" fill="#ffffff"/>\n'
            '<text x="28" y="30" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#0f172a">BO progress and acquisition trace</text>\n'
            f'<text x="28" y="52" font-family="Arial, sans-serif" font-size="13" fill="#475569">{latest_trace}</text>\n'
            f'<rect x="{margin_left}" y="{margin_top}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#cbd5e1"/>\n'
            f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="#334155"/>\n'
            f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="#334155"/>\n'
            f'<text x="{margin_left}" y="{height - 22}" font-family="Arial, sans-serif" font-size="12" fill="#475569">iteration</text>\n'
            f'<text x="18" y="{margin_top + 12}" font-family="Arial, sans-serif" font-size="12" fill="#475569">best score</text>\n'
            f'<text x="{margin_left - 54}" y="{margin_top + 8}" font-family="Arial, sans-serif" font-size="11" fill="#64748b">{max_value:.3f}</text>\n'
            f'<text x="{margin_left - 54}" y="{margin_top + plot_h}" font-family="Arial, sans-serif" font-size="11" fill="#64748b">{min_value:.3f}</text>\n'
            f"{''.join(paths)}\n{''.join(legends)}\n"
            "</svg>\n"
        )
        try:
            output_dir = self._workspace_artifact_dir(workspace)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            path = output_dir / f"{stamp}_bo_progress.svg"
            path.write_text(svg, encoding="utf-8")
            return {
                "key": "workspace.bo_plot",
                "path": self._workspace_artifact_relpath(path),
                "name": path.name,
                "source": "bo_workspace_plot",
                "workspace": workspace,
            }
        except Exception as exc:
            return {
                "key": "workspace.bo_plot",
                "path": "",
                "name": "",
                "source": "bo_workspace_plot",
                "workspace": workspace,
                "error": f"{exc.__class__.__name__}: {exc}",
            }

    def _register_workspace_artifacts(self, *, workspace: str, tool: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Materialize workspace evidence under the active run directory."""
        records: list[dict[str, Any]] = []
        result_record = self._write_workspace_result_artifact(workspace=workspace, tool=tool, result=result)
        if result_record:
            records.append(result_record)
        if workspace == "bo":
            bo_plot = self._write_bo_plot_artifact(workspace=workspace, result=result)
            if bo_plot:
                records.append(bo_plot)
        seen_sources: set[str] = set()
        for key, value in self._iter_workspace_file_candidates(result):
            source_path = str(value)
            if source_path in seen_sources:
                continue
            seen_sources.add(source_path)
            record = self._copy_workspace_file_artifact(workspace=workspace, key=key, source_value=source_path)
            if record:
                records.append(record)
        return records

    async def emit_workspace_result(
        self,
        *,
        workspace: str,
        tool: str,
        result: dict[str, Any],
        stage: Stage | None = None,
        module_id: str = "",
        agent: str = "",
        workflow: str = "",
        node_event: bool = False,
        event_type: str = "workspace_tool_result",
    ) -> None:
        """Broadcast dedicated workspace actions using the Runtime IDE event schema."""
        if not isinstance(result, dict):
            return
        ok = bool(result.get("ok", False))
        status = str(result.get("status") or ("done" if ok else "error"))
        node_id = stage.value if isinstance(stage, Stage) else workspace
        resolved_module = module_id or node_id
        module_runtime = {
            "module_id": resolved_module,
            "handler": f"agent.{agent}" if agent else "",
            "workspace": workspace,
            "workflow": workflow or str(result.get("workflow") or result.get("tool") or tool),
            "tool": tool,
            "direct_workspace_api": True,
        }
        base_payload = {
            "workspace": workspace,
            "tool": tool,
            "workflow": workflow or result.get("workflow", ""),
            "result": result,
            "node_id": node_id,
            "module_id": resolved_module,
            "agent": agent,
            "status": status,
            "module_runtime": module_runtime,
        }
        hardware_alert = self._hardware_alert_for_result(
            workspace=workspace,
            tool=tool,
            result=result,
            stage=stage,
            agent=agent,
            workflow=workflow,
            status=status,
        )
        if hardware_alert:
            result["hardware_alert"] = hardware_alert
            base_payload["hardware_alert"] = hardware_alert
            self._record_hardware_alert(hardware_alert)
        registered_artifacts = self._register_workspace_artifacts(workspace=workspace, tool=tool, result=result)
        if registered_artifacts:
            base_payload["runtime_artifacts"] = registered_artifacts
        level = "INFO" if ok else "ERROR"
        severity = level.lower()
        runtime_type = "tool.completed" if ok else "tool.failed"
        await self._broadcast_controller_event(
            {
                "event_id": make_event_id(),
                "run_id": self._state.run_id,
                "experiment_id": self._state.experiment_id,
                "event_type": event_type,
                "type": runtime_type,
                "severity": severity,
                "level": level,
                "ts": datetime.now(timezone.utc).isoformat(),
                "graph_id": "atr_closed_loop",
                "node_id": node_id,
                "module_id": resolved_module,
                "agent": agent,
                "status": status,
                "message": f"{workspace} workspace {tool} {status}",
                "payload": base_payload,
                "state": self._state.model_dump(mode="json"),
            }
        )
        if hardware_alert:
            alert_level = "ERROR" if hardware_alert.get("severity") in {"blocking", "critical"} else "WARNING"
            await self._broadcast_controller_event(
                {
                    "event_id": make_event_id(),
                    "run_id": self._state.run_id,
                    "experiment_id": self._state.experiment_id,
                    "event_type": "hardware.alert",
                    "type": "hardware.alert",
                    "severity": str(hardware_alert.get("severity") or "warning"),
                    "level": alert_level,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "graph_id": "atr_closed_loop",
                    "node_id": node_id,
                    "module_id": resolved_module,
                    "agent": agent,
                    "status": status,
                    "message": str(hardware_alert.get("message") or hardware_alert.get("failure_code") or "hardware alert"),
                    "payload": {**base_payload, "hardware_alert": hardware_alert},
                    "state": self._state.model_dump(mode="json"),
                }
            )
        if node_event:
            await self._broadcast_controller_event(
                {
                    "event_id": make_event_id(),
                    "run_id": self._state.run_id,
                    "experiment_id": self._state.experiment_id,
                    "event_type": "workspace_node_result",
                    "type": "node.completed" if ok else "node.failed",
                    "severity": severity,
                    "level": level,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "graph_id": "atr_closed_loop",
                    "node_id": node_id,
                    "module_id": resolved_module,
                    "agent": agent,
                    "status": status,
                    "message": f"{agent or workspace} workspace node {status}",
                    "payload": base_payload,
                    "state": self._state.model_dump(mode="json"),
                }
            )
        for artifact in registered_artifacts:
            if not artifact.get("path"):
                continue
            await self._broadcast_controller_event(
                {
                    "event_id": make_event_id(),
                    "run_id": self._state.run_id,
                    "experiment_id": self._state.experiment_id,
                    "event_type": "workspace_artifact_file_created",
                    "type": "artifact.created",
                    "severity": "info",
                    "level": "INFO",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "graph_id": "atr_closed_loop",
                    "node_id": node_id,
                    "module_id": resolved_module,
                    "agent": agent,
                    "status": "done",
                    "message": f"{workspace} workspace artifact file: {artifact['path']}",
                    "payload": {**base_payload, "artifact": artifact},
                    "state": self._state.model_dump(mode="json"),
                }
            )
        for artifact in self._workspace_artifact_payloads(result):
            await self._broadcast_controller_event(
                {
                    "event_id": make_event_id(),
                    "run_id": self._state.run_id,
                    "experiment_id": self._state.experiment_id,
                    "event_type": "workspace_artifact_created",
                    "type": "artifact.created",
                    "severity": "info",
                    "level": "INFO",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "graph_id": "atr_closed_loop",
                    "node_id": node_id,
                    "module_id": resolved_module,
                    "agent": agent,
                    "status": "done",
                    "message": f"{workspace} workspace artifact: {artifact['key']}",
                    "payload": {**base_payload, "artifact": artifact},
                    "state": self._state.model_dump(mode="json"),
                }
            )
        events = self._state.run_metadata.setdefault("workspace_runtime_events", [])
        if isinstance(events, list):
            events.append(
                {
                    "workspace": workspace,
                    "tool": tool,
                    "node_id": node_id,
                    "module_id": resolved_module,
                    "agent": agent,
                    "status": status,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
            del events[:-50]

    async def emit_lerobot_result(self, result: dict[str, Any]) -> None:
        """Broadcast a LeRobot GUI/tool result and stream its steps into Live GUI when active."""
        if not isinstance(result, dict):
            return
        tool = str(result.get("tool") or "lerobot")
        status = str(result.get("status") or ("ok" if result.get("ok") else "failed"))
        await self.emit_workspace_result(
            workspace="lerobot",
            tool=tool,
            result=result,
            stage=Stage.MANIPULATION,
            module_id="manipulation",
            agent="manipulation_agent",
            workflow=str(result.get("workflow") or tool),
            node_event=tool.startswith("manipulation_agent."),
            event_type="lerobot_step",
        )
        for item in result.get("step_trace", []):
            if not isinstance(item, dict):
                continue
            await self._on_tool_event(
                {
                    "tool": tool,
                    "profile_id": result.get("profile_id", ""),
                    "session_id": result.get("session_id", ""),
                    "mode": result.get("mode", ""),
                    "step": item.get("step", "STEP"),
                    "status": item.get("status", status),
                    "detail": item.get("detail", ""),
                }
            )

    def _ensure_orchestrator_supervisor_baseline(self) -> None:
        """Keep Live GUI snapshots populated with the current supervisor contract and plan."""
        metadata = self._state.run_metadata if isinstance(self._state.run_metadata, dict) else {}
        mission = metadata.get("latest_mission_contract") if isinstance(metadata.get("latest_mission_contract"), dict) else {}
        plan = metadata.get("latest_orchestration_plan") if isinstance(metadata.get("latest_orchestration_plan"), dict) else {}
        stale_mission = mission.get("run_id") != self._state.run_id or mission.get("stage") != self._state.stage.value
        stale_plan = plan.get("run_id") != self._state.run_id or plan.get("current_stage") != self._state.stage.value
        if stale_mission:
            mission = build_mission_contract(state=self._state)
            self._state.run_metadata["mission_contract"] = mission
            self._state.run_metadata["latest_mission_contract"] = mission
        if stale_plan:
            plan = self._build_orchestration_plan()
            plans = self._state.run_metadata.get("orchestration_plans")
            if not isinstance(plans, list):
                plans = []
            if not plans or plans[-1].get("plan_id") != plan.get("plan_id"):
                plans.append(plan)
            self._state.run_metadata["orchestration_plans"] = plans[-20:]
            self._state.run_metadata["latest_orchestration_plan"] = plan
        control_plane = metadata.get("latest_orchestrator_control_plane") if isinstance(metadata.get("latest_orchestrator_control_plane"), dict) else {}
        stale_control_plane = (
            control_plane.get("run_id") != self._state.run_id
            or control_plane.get("stage") != self._state.stage.value
            or control_plane.get("route_state", {}).get("next_recommended_stage") != plan.get("next_recommended_stage")
        )
        if stale_control_plane:
            self._state.run_metadata["latest_orchestrator_control_plane"] = build_orchestrator_control_plane_snapshot(
                state=self._state,
                mission_contract=mission,
                orchestration_plan=plan,
            )

    def _active_graph_plan_route_override(self, start: Stage | None = None) -> list[dict[str, Any]] | None:
        """Return active graph stage metadata for supervisor plans, if graph-backed."""
        config = self._active_graph_config()
        if config is None:
            return None
        current = start or self._state.stage
        if current in {Stage.COMPLETE, Stage.ERROR}:
            return None
        if current == Stage.IDLE:
            try:
                current = Stage(config.next_stage(Stage.IDLE.value, state_metadata=self._state.run_metadata))
            except Exception:
                current = Stage.DESIGN
        stages = self._active_graph_stage_sequence(current, stop_at=Stage.GUARDIAN, include_start=True)
        if not stages:
            return None
        route: list[dict[str, Any]] = []
        for stage in stages:
            node = self._graph_node_for_stage(stage)
            module_runtime = self._module_runtime_for_stage(stage)
            step = {
                "stage": stage.value,
                "agent": self._planning_stage_role(stage, module_runtime),
                "label": self._planning_stage_label(stage, module_runtime),
                "handler": str(module_runtime.get("handler") or getattr(node, "handler", "") or ""),
                "module_id": str(module_runtime.get("graph_module_id") or getattr(node, "module_id", "") or ""),
            }
            required_outputs = self._module_required_outputs_for_graph_node(node)
            if required_outputs:
                step["required_outputs"] = required_outputs
            route.append(step)
        return route

    def _active_graph_module_root(self) -> Path:
        """Resolve module root for the active graph config path."""
        if self._active_graph_config_path is None:
            return Path(__file__).resolve().parent.parent / "graphs"
        graph_dir = Path(self._active_graph_config_path).resolve().parent
        return graph_dir.parent if graph_dir.name == "configs" else graph_dir

    def _module_required_outputs_for_graph_node(self, node: Any) -> list[str]:
        """Read module-declared output contracts for supervisor task queues."""
        module_id = str(getattr(node, "module_id", "") or "").strip()
        if not module_id:
            return []
        module_path = self._active_graph_module_root() / module_id / "module.yaml"
        if not module_path.exists():
            return []
        try:
            module = load_module_config(module_path).model_dump(mode="json", exclude_none=True)
        except Exception:
            return []
        outputs: list[str] = []
        output_contracts = module.get("output_contracts")
        if isinstance(output_contracts, list):
            outputs.extend(str(item).strip() for item in output_contracts if str(item).strip())
        io_contract = module.get("io_contract") if isinstance(module.get("io_contract"), dict) else {}
        io_output = io_contract.get("output")
        if isinstance(io_output, list):
            outputs.extend(str(item).strip() for item in io_output if str(item).strip())
        return list(dict.fromkeys(outputs))

    def _build_orchestration_plan(self) -> dict[str, Any]:
        """Build supervisor plan with the active graph as the source of truth."""
        return build_orchestration_plan(
            state=self._state,
            route_override=self._active_graph_plan_route_override(),
        )

    def snapshot(self) -> dict[str, Any]:
        """Return current state plus logging metadata."""
        self._ensure_orchestrator_supervisor_baseline()
        return {
            "state": self._state.model_dump(mode="json"),
            "runtime": self._runtime_profile(),
            "logs": {
                "run_dir": str(self._logger_bundle.run_dir),
                "json": str(self._logger_bundle.json_log_path),
                "summary": str(self._logger_bundle.summary_log_path),
            },
            "is_running": bool(self._run_task and not self._run_task.done()) or self._planning_handoff_active(),
            "agents": self._deps.agent_registry.names(),
        }

    def recent_events(self) -> list[dict[str, Any]]:
        """Return buffered recent events in display-sized form."""
        return [self._compact_event_for_buffer(event) for event in self._trace.snapshot()]

    async def emit_runtime_event(
        self,
        *,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
        level: str = "INFO",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Emit a standard Runtime IDE event through the shared event bus."""
        payload = dict(payload or {})
        ts = datetime.now(timezone.utc).isoformat()
        state_json = self._state.model_dump(mode="json")
        event = {
            "event_id": make_event_id(),
            "run_id": run_id or self._state.run_id,
            "experiment_id": self._state.experiment_id,
            "timestamp_stage": state_json.get("stage", ""),
            "event_type": event_type,
            "level": level,
            "message": message,
            "payload": payload,
            "state": state_json,
            "ts": ts,
            "type": event_type,
            "severity": level.lower(),
            "graph_id": payload.get("graph_id", "atr_closed_loop"),
            "node_id": payload.get("node_id", payload.get("stage", state_json.get("stage", ""))),
            "module_id": payload.get("module_id", ""),
            "agent": payload.get("agent", ""),
            "status": payload.get("status", "ok" if level != "ERROR" else "failed"),
        }
        await self._broadcast_controller_event(event)
        return event

    def apply_runtime_approval_resolution(
        self,
        *,
        approval_id: str,
        decision: str,
        operator: str = "operator",
        note: str = "",
    ) -> dict[str, Any]:
        """Apply a Runtime IDE approval decision to the active OrchestratorState."""
        approvals = self._state.run_metadata.setdefault("runtime_approvals", {})
        if not isinstance(approvals, dict):
            approvals = {}
            self._state.run_metadata["runtime_approvals"] = approvals
        matched: dict[str, Any] | None = None
        matched_key = ""
        for key, item in approvals.items():
            if isinstance(item, dict) and str(item.get("approval_id") or "") == approval_id:
                matched = item
                matched_key = str(key)
                break
        if matched is None:
            return {"matched": False, "approval_id": approval_id, "decision": decision}

        normalized_decision = decision if decision in {"approved", "rejected", "cancelled"} else "cancelled"
        matched.update(
            {
                "status": normalized_decision,
                "decision": normalized_decision,
                "operator": operator,
                "note": note,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._state.run_metadata["runtime_approvals"][matched_key] = matched
        if normalized_decision == "approved":
            self._state.is_paused = False
            if self._state.run_metadata.get("approval_blocked_stage", {}).get("approval_id") == approval_id:
                self._state.run_metadata.pop("approval_blocked_stage", None)
        else:
            self._state.is_paused = False
            self._state.stage = Stage.ERROR
            self._state.run_metadata["approval_rejection"] = {
                "approval_id": approval_id,
                "decision": normalized_decision,
                "operator": operator,
                "note": note,
                "gate_key": matched_key,
            }
        return {"matched": True, "approval_id": approval_id, "decision": normalized_decision, "gate_key": matched_key}


    async def switch_inference_backend(self, backend: str) -> dict[str, Any]:
        """Switch active inference backend for future agent/model calls."""
        try:
            self._apply_inference_backend(backend)
        except Exception as exc:
            return {"ok": False, "message": str(exc), "snapshot": self.snapshot()}
        profile = self._runtime_profile()
        await self._broadcast_event(
            {
                "event_id": f"evt-backend-{profile.get('backend', {}).get('name', 'unknown')}",
                "run_id": self._state.run_id,
                "experiment_id": self._state.experiment_id,
                "event_type": "backend_switch",
                "level": "INFO",
                "message": f"Inference backend switched to {profile.get('backend', {}).get('label', backend)}",
                "payload": {"runtime": profile},
                "state": self._state.model_dump(mode="json"),
            }
        )
        return {"ok": True, "message": "Inference backend switched.", "snapshot": self.snapshot()}

    def _planning_transcript_path(self) -> Path:
        """Return the append-only Live GUI transcript file for this run."""
        return self._logger_bundle.run_dir / "live_planning_transcript.jsonl"

    @staticmethod
    def _select_runtime_fields(source: Any, keys: tuple[str, ...] | list[str]) -> dict[str, Any]:
        """Select only operator-facing fields from a bulky runtime object."""
        if not isinstance(source, dict):
            return {}
        return {key: compact_runtime_payload(source.get(key)) for key in keys if key in source and source.get(key) is not None}

    @classmethod
    def _planning_display_slicer_settings(cls, settings: Any) -> dict[str, Any]:
        return cls._select_runtime_fields(
            settings,
            (
                "printer_profile",
                "material",
                "slicer_profile_hint",
                "layer_height_mm",
                "first_layer_height_mm",
                "nozzle_diameter_mm",
                "bed_temperature_c",
                "first_layer_bed_temperature_c",
                "slow_first_layer_enabled",
                "first_layer_speed_mm_s",
                "wall_thickness_mm",
                "cell_size_mm",
                "relative_density",
                "skirt_enabled",
                "bottom_cap_enabled",
                "top_cap_enabled",
                "top_bottom_cap",
                "skin_thickness_mm",
                "expected_mass_g",
                "input_model_path",
                "output_gcode_path",
                "simulated",
                "resolved_command",
            ),
        )

    @classmethod
    def _planning_display_fabrication_report(cls, report: Any) -> dict[str, Any]:
        if not isinstance(report, dict):
            return {}
        compact = cls._select_runtime_fields(
            report,
            (
                "schema",
                "fabrication_intent",
                "digital_thread",
                "fabrication_outcome",
                "quality_gates",
                "experiment_evaluation_ref",
            ),
        )
        if isinstance(compact.get("quality_gates"), list):
            compact["quality_gates"] = compact["quality_gates"][:12]
        process_plan = cls._select_runtime_fields(
            report.get("process_plan"),
            (
                "layer_height_mm",
                "first_layer_height_mm",
                "nozzle_diameter_mm",
                "bed_temperature_c",
                "first_layer_bed_temperature_c",
                "adhesion_policy",
                "cap_skin_policy",
                "ejection_policy",
                "estimated_mass_g",
                "estimated_print_time_min",
            ),
        )
        printer_runtime = cls._select_runtime_fields(
            report.get("printer_runtime"),
            (
                "provider",
                "selected_printer",
                "device_screen",
                "preprint_gate",
                "readiness_levels",
                "operator_actions",
                "autoejection",
                "autoejection_handoff",
                "prepare_status",
                "mode",
                "path",
                "upload",
                "transfer_wait",
                "start",
                "ejection",
                "step_trace",
            ),
        )
        monitoring_plan = cls._select_runtime_fields(
            report.get("monitoring_plan"),
            (
                "observe_printer_bridge_status",
                "observe_prusalink_status",
                "observe_transfer_idle",
                "observe_camera_after_print",
                "layerwise_monitoring_available",
                "defect_classes",
            ),
        )
        if process_plan:
            compact["process_plan"] = process_plan
        if printer_runtime:
            if isinstance(printer_runtime.get("step_trace"), list):
                printer_runtime["step_trace"] = printer_runtime["step_trace"][-16:]
            compact["printer_runtime"] = printer_runtime
        if monitoring_plan:
            compact["monitoring_plan"] = monitoring_plan
        return compact

    @classmethod
    def _planning_display_specimen_result(cls, specimen: Any) -> dict[str, Any]:
        """Keep Specimen Making details shown in Live GUI without raw geometry/report payloads."""
        if not isinstance(specimen, dict):
            return {}
        tool_result = specimen.get("tool_result") if isinstance(specimen.get("tool_result"), dict) else {}
        printer = specimen.get("printer") if isinstance(specimen.get("printer"), dict) else tool_result.get("printer", {})
        prusalink = specimen.get("prusalink") if isinstance(specimen.get("prusalink"), dict) else tool_result.get("prusalink", {})
        print_result = specimen.get("print_result") if isinstance(specimen.get("print_result"), dict) else tool_result.get("print_result", {})
        compact = cls._select_runtime_fields(
            specimen,
            (
                "specimen_id",
                "candidate_id",
                "geometry_hash",
                "stl_path",
                "sliced_path",
                "handoff_package_path",
                "printer_prepare_status",
                "printer_mode",
                "printer_path",
                "expected_mass_g",
                "expected_print_time_min",
            ),
        )
        compact.update(
            {
                "fabrication_report": cls._planning_display_fabrication_report(specimen.get("fabrication_report")),
                "slicer_settings": cls._planning_display_slicer_settings(specimen.get("slicer_settings") or tool_result.get("slicer_settings")),
                "selected_printer": cls._select_runtime_fields(
                    specimen.get("selected_printer") or tool_result.get("selected_printer"),
                    ("profile_id", "label", "provider", "model", "host", "serial_number"),
                ),
                "device_screen": cls._select_runtime_fields(
                    specimen.get("device_screen") or tool_result.get("device_screen"),
                    ("connection", "actions", "status", "camera", "temperatures", "job"),
                ),
                "preprint_gate": cls._select_runtime_fields(
                    specimen.get("preprint_gate") or tool_result.get("preprint_gate") or tool_result.get("start_gate"),
                    ("state", "technical_ready_for_start", "approval_ready_for_start", "ready_for_live_print", "blockers", "checks"),
                ),
                "operator_actions": compact_runtime_payload(
                    specimen.get("operator_actions") or tool_result.get("operator_actions") or []
                ),
                "readiness_levels": compact_runtime_payload(
                    specimen.get("readiness_levels") or tool_result.get("readiness_levels") or []
                ),
                "autoejection": cls._select_runtime_fields(
                    specimen.get("autoejection") or tool_result.get("autoejection") or tool_result.get("autoejection_gate"),
                    ("status", "blockers", "provider", "requested", "method", "handoff", "checks"),
                ),
                "autoejection_handoff": cls._select_runtime_fields(
                    specimen.get("autoejection_handoff") or tool_result.get("autoejection_handoff") or tool_result.get("handoff"),
                    (
                        "schema",
                        "status",
                        "provider",
                        "routine_id",
                        "recommended_consumer_agent",
                        "next_owner",
                        "next_tool",
                        "requires_guardian_approval",
                        "requires_operator_confirmation",
                        "requires_provider_executor",
                        "motion_started",
                        "dry_run_only",
                    ),
                ),
                "prusalink": cls._select_runtime_fields(prusalink, ("transport", "storage", "upload_endpoint", "start_endpoint", "remote_path")),
                "printer": cls._select_runtime_fields(printer, ("state", "status", "provider", "storage", "transfer", "job", "host_configured")),
                "slicer_result": cls._select_runtime_fields(specimen.get("slicer_result") or tool_result.get("slicer_result"), ("ok", "failure_code", "elapsed_sec", "simulated", "sliced_path")),
                "gcode_validation": cls._select_runtime_fields(specimen.get("gcode_validation") or tool_result.get("gcode_validation"), ("ok", "failure_code", "violations")),
                "print_result": cls._select_runtime_fields(print_result, ("status", "failure_code", "set_ready", "upload", "transfer_wait", "start")),
                "ejection_result": cls._select_runtime_fields(specimen.get("ejection_result") or tool_result.get("ejection_result"), ("status", "failure_code", "method", "resolved", "object_bounds", "attempts")),
                "step_trace": compact_runtime_payload((specimen.get("step_trace") or tool_result.get("step_trace") or [])[-16:]),
            }
        )
        return {key: value for key, value in compact.items() if value not in ({}, [], None)}

    @classmethod
    def _planning_display_equipment_fields(cls, entry: dict[str, Any]) -> dict[str, Any]:
        """Flatten Lab Equipment runtime evidence into the fields consumed by the chat card."""
        equipment = entry.get("equipment") if isinstance(entry.get("equipment"), dict) else {}
        report = entry.get("equipment_report") if isinstance(entry.get("equipment_report"), dict) else equipment.get("equipment_report", {})
        result = entry.get("equipment_result") if isinstance(entry.get("equipment_result"), dict) else equipment.get("equipment_result", {})
        data_ledger = entry.get("data_ledger") if isinstance(entry.get("data_ledger"), dict) else report.get("data_ledger", {})
        data_acquisition = entry.get("data_acquisition") if isinstance(entry.get("data_acquisition"), dict) else report.get("data_acquisition", {})
        if not data_acquisition and isinstance(data_ledger, dict):
            data_acquisition = data_ledger
        compact: dict[str, Any] = {
            "equipment_runtime_event": cls._select_runtime_fields(
                entry.get("equipment_runtime_event") or result,
                ("tool", "sequence_id", "program_id", "bridge", "mode", "status", "step", "host", "bridge_host"),
            ),
            "macro_command": cls._select_runtime_fields(entry.get("macro_command") or report.get("control_trace"), ("command_id", "program_id", "target_ui", "step", "status", "detail")),
            "visual_assertion": cls._select_runtime_fields(entry.get("visual_assertion") or report.get("visual_verification"), ("checkpoint", "status", "ok", "target_ui", "confidence", "screenshot_artifact", "detail", "screen_checks_passed", "screen_checks_total")),
            "physical_cross_check": cls._select_runtime_fields(entry.get("physical_cross_check") or report.get("physical_verification"), ("status", "ok", "check_id", "target_ui", "detail", "all_required_ok", "vision_motion_confirmed", "specimen_alignment_ok", "fixture_safe_to_access")),
            "data_acquisition": cls._select_runtime_fields(data_acquisition, ("status", "artifact_or_path", "windows_path", "linux_path", "sha256", "row_count_probe", "save_method", "artifact_pull_status", "parse_probe", "detail")),
            "recovery": cls._select_runtime_fields(entry.get("recovery") or report.get("recovery"), ("status", "failure_step", "failure_code", "failure_detail", "recommended_action")),
            "command_id": entry.get("command_id") or result.get("sequence_id"),
            "data_file_ref": entry.get("data_file_ref") or result.get("result_file") or (data_ledger.get("linux_path") if isinstance(data_ledger, dict) else None),
            "windows_host": entry.get("windows_host"),
        }
        return {key: value for key, value in compact.items() if value not in ({}, [], None, "")}

    @staticmethod
    def _planning_agent_id_for_role(role: str) -> str:
        mapping = {
            "operator": "Operator",
            "orchestrator": "OrchestratorAgent",
            "design_ai": "DesignAgent",
            "printer_ai": "SpecimenMakingAgent",
            "specimen_ai": "SpecimenMakingAgent",
            "vision_ai": "VisionAgent",
            "manipulation_ai": "ManipulationAgent",
            "equipment_ai": "LabEquipmentAgent",
            "analysis_ai": "AnalysisAgent",
            "knowledge_ai": "KnowledgeAgent",
            "bo_ai": "BOAgent",
            "guardian": "GuardianAgent",
            "guardian_ai": "GuardianAgent",
            "system": "System",
        }
        clean_role = str(role or "").strip().lower()
        return mapping.get(clean_role, clean_role or "System")

    @staticmethod
    def _planning_parse_system_event(content: str) -> tuple[str, dict[str, str]]:
        """Parse legacy SYSTEM_EVENT blocks without changing the stored content."""
        text = str(content or "").strip()
        if not text.startswith("SYSTEM_EVENT:"):
            return "", {}
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        event_name = lines[0].split(":", 1)[1].strip() if lines else ""
        fields: dict[str, str] = {}
        for line in lines[1:]:
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            clean_key = re.sub(r"[^a-zA-Z0-9_]+", "_", key.strip()).strip("_").lower()
            if clean_key:
                fields[clean_key] = value.strip()
        return event_name, fields

    @classmethod
    def _classify_planning_message(cls, entry: dict[str, Any]) -> dict[str, Any]:
        """Assign display routing metadata for Live GUI chat/report/backend surfaces."""
        if not isinstance(entry, dict):
            return {
                "message_class": "system_event",
                "surface": ["backend"],
                "visibility": "internal",
                "agent_id": "System",
            }
        role = str(entry.get("role") or "system").strip().lower()
        content = str(entry.get("content") or "")
        message_type = str(entry.get("message_type") or "").strip().lower()
        agent_id = str(entry.get("agent_id") or cls._planning_agent_id_for_role(role))
        severity = str(entry.get("severity") or entry.get("level") or "").strip().lower()
        system_event_name, system_event_fields = cls._planning_parse_system_event(content)
        has_artifacts = any(
            key in entry
            for key in (
                "artifacts",
                "specimen_artifacts",
                "fem_artifacts",
                "artifact_pair",
                "bo_result",
            )
        )
        has_report_payload = has_artifacts or any(
            key in entry
            for key in (
                "experiment_spec",
                "specimen",
                "analysis",
                "knowledge",
                "equipment_runtime_event",
                "equipment_result",
                "vision_signal",
            )
        )
        requires_user_action = bool(
            entry.get("requires_response")
            or entry.get("pending_operator_input")
            or entry.get("requires_design_inputs")
            or entry.get("requires_connection_info")
            or entry.get("requires_human_approval")
        )
        classification: dict[str, Any] = {
            "agent_id": agent_id,
            "severity": severity or ("warning" if message_type in {"warning", "approval", "incident"} else "info"),
        }
        if system_event_name:
            event_key = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", system_event_name.strip().lower()).strip("_") or "system"
            is_handoff = "handoff" in event_key
            is_timeline = is_handoff or any(token in event_key for token in ("cycle", "workflow", "trigger", "node_failed", "halted", "complete"))
            classification.update(
                {
                    "message_class": "handoff_event" if is_handoff else "system_event",
                    "surface": ["timeline", "backend"] if is_timeline else ["backend"],
                    "visibility": "internal",
                    "event_type": f"planning.{event_key}",
                    "event_fields": system_event_fields,
                }
            )
            return classification
        if role == "operator":
            classification.update({"message_class": "operator_input", "surface": ["chat"], "visibility": "user"})
            return classification
        if role == "system":
            classification.update({"message_class": "system_event", "surface": ["backend"], "visibility": "internal"})
            return classification
        if message_type in {"approval", "warning", "incident"} or severity in {"warning", "error", "failed"}:
            surfaces = ["chat", "backend"]
            if role in {"printer_ai", "specimen_ai", "equipment_ai", "manipulation_ai", "vision_ai"}:
                surfaces.append("io")
            if has_report_payload:
                surfaces.append("report")
            classification.update(
                {
                    "message_class": "guardian_event" if role == "guardian" else "error_event" if severity in {"error", "failed"} else "agent_chat",
                    "surface": list(dict.fromkeys(surfaces)),
                    "visibility": "user" if requires_user_action or role == "guardian" else "mixed",
                }
            )
            return classification
        if entry.get("pendingReasoning"):
            classification.update({"message_class": "agent_chat", "surface": ["chat"], "visibility": "user"})
            return classification
        surfaces = ["chat"] if content.strip() else []
        if has_report_payload:
            surfaces.append("report")
        if has_artifacts:
            surfaces.append("artifacts")
        if role in {"printer_ai", "specimen_ai", "equipment_ai", "manipulation_ai", "vision_ai"} and has_report_payload:
            surfaces.append("io")
        if not surfaces:
            surfaces = ["backend"]
        classification.update(
            {
                "message_class": "agent_chat" if "chat" in surfaces else "agent_report",
                "surface": list(dict.fromkeys(surfaces)),
                "visibility": "user" if "chat" in surfaces else "internal",
            }
        )
        return classification

    def _compact_planning_message_for_storage(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Keep transcript messages useful while dropping bulky runtime internals."""
        if not isinstance(entry, dict):
            return {}
        entry = {**entry, **self._classify_planning_message(entry)}
        scalar_keys = (
            "role",
            "content",
            "timestamp",
            "model",
            "ok",
            "schema",
            "message_type",
            "message_class",
            "surface",
            "visibility",
            "event_type",
            "event_fields",
            "agent_id",
            "severity",
            "cycle_index",
            "total_cycles",
            "requires_response",
            "requires_design_inputs",
            "missing_design_inputs",
            "requires_connection_info",
            "blocks_workflow",
            "pendingReasoning",
            "pending_operator_input",
            "reasoning",
            "goal",
            "constraints",
            "operator_intent",
            "command_id",
            "program_id",
            "check_id",
            "shielded_tool",
            "decision",
            "reason_code",
            "risk_score",
            "requires_human_approval",
            "signal_id",
            "zone_id",
            "confidence",
            "stability_ms",
            "windows_host",
            "data_file_ref",
            "failure_code",
        )
        compact = {key: compact_runtime_payload(entry.get(key)) for key in scalar_keys if key in entry}
        if "content" in entry:
            compact["content"] = str(entry.get("content") or "")
        if "experiment_spec" in entry:
            compact["experiment_spec"] = self._planning_display_spec(entry.get("experiment_spec"))
        if "artifacts" in entry:
            compact["artifacts"] = self._planning_display_artifacts(entry.get("artifacts"))
        if "specimen_artifacts" in entry:
            compact["specimen_artifacts"] = self._planning_display_artifacts(entry.get("specimen_artifacts"))
        if "fem_artifacts" in entry:
            compact["fem_artifacts"] = self._planning_display_artifacts(entry.get("fem_artifacts"))
        if "artifact_pair" in entry:
            compact["artifact_pair"] = self._planning_display_artifact_pair(entry.get("artifact_pair"))
        if "design_candidate" in entry and "experiment_spec" not in compact:
            compact["experiment_spec"] = self._planning_display_spec(entry.get("design_candidate"))
        if "specimen" in entry:
            compact["specimen"] = self._planning_display_specimen_result(entry.get("specimen"))
        if entry.get("role") == "equipment_ai" or "equipment" in entry or "equipment_result" in entry:
            compact.update(self._planning_display_equipment_fields(entry))
        if "analysis" in entry:
            analysis = entry.get("analysis") if isinstance(entry.get("analysis"), dict) else {}
            compact["analysis"] = self._select_runtime_fields(
                analysis,
                (
                    "ok",
                    "objective_score",
                    "uncertainty",
                    "recommendation",
                    "summary",
                    "utm_metrics",
                    "utm_curve",
                    "data_quality_gate",
                    "fem_metrics",
                    "cae_metrics",
                    "quality_gate",
                    "fem_utm_comparison",
                    "multifidelity_comparison",
                    "trust_score",
                    "fidelity_records",
                    "analysis_artifacts",
                    "bo_handoff",
                ),
            )
        if "vision_signal" in entry:
            compact["vision_signal"] = compact_runtime_payload(entry.get("vision_signal"))
        if "knowledge" in entry:
            knowledge = entry.get("knowledge") if isinstance(entry.get("knowledge"), dict) else {}
            compact["knowledge"] = self._select_runtime_fields(
                knowledge,
                (
                    "retrieval_coverage",
                    "local_chunks",
                    "web_results",
                    "failure_pattern_count",
                    "success_pattern_count",
                    "agent_performance_count",
                    "evolution_pack_count",
                    "graph_backend_status",
                    "artifact_paths",
                ),
            )
        if "bo_result" in entry:
            compact["bo_result"] = self._planning_display_bo_result(entry.get("bo_result"))
        for key in ("module_runtime", "module_step_trace", "vision_cross_check_event", "guardian_gate"):
            value = entry.get(key)
            if isinstance(value, dict):
                compact[key] = compact_runtime_payload(value)
            elif isinstance(value, list):
                compact[key] = compact_runtime_payload(value[:12])
        return {key: value for key, value in compact.items() if value not in ({}, [], None)}

    def _json_safe_planning_message(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Detach planning messages from large live objects and make them JSONL-safe."""
        compact_entry = self._compact_planning_message_for_storage(entry)
        try:
            return json.loads(json.dumps(compact_entry, ensure_ascii=False, default=str))
        except Exception:
            return {
                "role": str(entry.get("role") or "system"),
                "content": str(entry.get("content") or ""),
                "timestamp": str(entry.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                "serialization_error": True,
            }

    def _seed_planning_transcript_count(self) -> None:
        """Initialize transcript count from disk when a running server reuses a file."""
        if self._planning_message_total:
            return
        path = self._planning_transcript_path()
        if not path.exists():
            return
        try:
            with path.open("r", encoding="utf-8") as handle:
                self._planning_message_total = sum(1 for line in handle if line.strip())
        except OSError:
            self._planning_message_total = max(self._planning_message_total, len(self._planning_messages))

    def _reset_planning_transcript(self) -> None:
        """Clear the active Live GUI transcript for an explicit fresh session."""
        self._planning_messages = []
        self._planning_message_total = 0
        try:
            self._planning_transcript_path().unlink(missing_ok=True)
        except OSError:
            return

    def _record_planning_message(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Persist the full chat message to disk and keep only a recent memory window."""
        self._seed_planning_transcript_count()
        stored = self._json_safe_planning_message(entry)
        index = self._planning_message_total
        stored.setdefault("message_id", f"planning-msg-{index + 1:06d}")
        stored["transcript_index"] = index
        path = self._planning_transcript_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(stored, ensure_ascii=False, default=str) + "\n")
            self._planning_message_total = index + 1
        except OSError:
            # Keep the GUI usable even if disk persistence is temporarily unavailable.
            self._planning_message_total = max(self._planning_message_total, index + 1)
        self._planning_messages.append(stored)
        if len(self._planning_messages) > PLANNING_TRANSCRIPT_MEMORY_LIMIT:
            del self._planning_messages[: len(self._planning_messages) - PLANNING_TRANSCRIPT_MEMORY_LIMIT]
        return stored

    def _compact_planning_message_for_event(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Keep SSE/recent-event payloads small; full messages are in the transcript file."""
        entry = {**entry, **self._classify_planning_message(entry)}
        compact_keys = {
            "role",
            "content",
            "timestamp",
            "model",
            "ok",
            "schema",
            "message_type",
            "message_class",
            "surface",
            "visibility",
            "event_type",
            "event_fields",
            "agent_id",
            "severity",
            "message_id",
            "transcript_index",
            "pendingReasoning",
            "pending_operator_input",
            "requires_response",
        }
        compact = {key: entry.get(key) for key in compact_keys if key in entry}
        compact["has_full_transcript_record"] = True
        compact["has_artifacts"] = any(
            key in entry
            for key in (
                "artifacts",
                "specimen_artifacts",
                "fem_artifacts",
                "bo_result",
                "equipment",
                "vision",
                "analysis",
                "knowledge",
            )
        )
        return compact

    @staticmethod
    def _planning_display_spec(spec: Any) -> dict[str, Any]:
        """Return only specimen/design fields needed for Live GUI cards."""
        if not isinstance(spec, dict):
            return {}
        keys = (
            "candidate_id",
            "specimen_id",
            "geometry_type",
            "structure_type",
            "specimen_size_mm",
            "cell_size_mm",
            "wall_thickness_mm",
            "relative_density",
            "porosity",
            "expected_mass_g",
            "expected_print_time_min",
            "expected_objective_proxy_score",
            "predicted_objective",
            "uncertainty",
            "risk_score",
            "tpms_surface",
            "tpms_thickness",
            "orientation_deg",
            "top_cap_enabled",
            "bottom_cap_enabled",
            "skirt_enabled",
        )
        return {key: spec.get(key) for key in keys if key in spec}

    @classmethod
    def _planning_display_artifacts(cls, artifacts: Any) -> dict[str, Any]:
        """Keep artifact links but drop filesystem/debug payloads from chat snapshots."""
        if not isinstance(artifacts, dict):
            return {}
        keys = (
            "preview_url",
            "stl_url",
            "experiment_spec_url",
            "contour_url",
            "report_url",
            "gcode_url",
            "download_url",
            "preview_path",
            "stl_path",
            "experiment_spec_path",
        )
        compact = {key: artifacts.get(key) for key in keys if artifacts.get(key)}
        return compact

    @classmethod
    def _planning_display_artifact_pair(cls, pair: Any) -> dict[str, Any]:
        if not isinstance(pair, dict):
            return {}
        compact: dict[str, Any] = {}
        for key in ("previous", "next"):
            item = pair.get(key) if isinstance(pair.get(key), dict) else {}
            if not item:
                continue
            compact[key] = {
                "label": item.get("label") or ("Previous shape" if key == "previous" else "Next shape"),
                "artifacts": cls._planning_display_artifacts(item.get("artifacts")),
                "experiment_spec": cls._planning_display_spec(item.get("experiment_spec")),
            }
        return compact

    @classmethod
    def _planning_display_bo_result(cls, bo_result: Any) -> dict[str, Any]:
        """Keep only BO fields needed for operator-facing Live GUI summaries."""
        if not isinstance(bo_result, dict):
            return {}
        compact: dict[str, Any] = {}
        for key in ("strategy", "benchmark_strategy", "acquisition", "status", "summary", "budget", "bo_backend"):
            if key in bo_result:
                value = bo_result.get(key)
                compact[key] = value[:500] if isinstance(value, str) else value
        for key in ("recommendation", "next_design_request", "prior_summary"):
            if isinstance(bo_result.get(key), dict):
                compact[key] = cls._planning_scalar_summary(bo_result.get(key))
        reasoning = bo_result.get("reasoning") if isinstance(bo_result.get("reasoning"), dict) else {}
        if reasoning:
            compact["reasoning"] = cls._planning_scalar_summary(reasoning, keys=("source", "preference", "rationale", "recommendation"))
        artifacts = bo_result.get("artifacts") if isinstance(bo_result.get("artifacts"), dict) else {}
        if artifacts:
            compact["artifacts"] = cls._planning_scalar_summary(artifacts)
        benchmark = bo_result.get("benchmark") if isinstance(bo_result.get("benchmark"), dict) else {}
        if benchmark:
            compact["benchmark"] = cls._planning_scalar_summary(benchmark, keys=("strategy", "acquisition", "best_score", "iteration_count", "budget", "ok"))
            strategies = cls._bo_strategies_from_result(bo_result)
            if strategies:
                compact["benchmark"]["strategies"] = {
                    str(name): cls._planning_display_bo_strategy(payload)
                    for name, payload in strategies.items()
                    if isinstance(payload, dict)
                }
        ranking = bo_result.get("candidate_ranking")
        if isinstance(ranking, list):
            compact["candidate_ranking"] = [cls._planning_scalar_summary(item) for item in ranking[:3] if isinstance(item, dict)]
        return compact

    @classmethod
    def _planning_display_bo_strategy(cls, payload: dict[str, Any]) -> dict[str, Any]:
        """Preserve the compact BO curve and acquisition trace needed by Live GUI plots."""
        compact = cls._planning_scalar_summary(
            payload,
            keys=("strategy", "acquisition", "best_score", "iteration_count", "budget", "backend_active"),
        )
        curve = payload.get("curve")
        if isinstance(curve, list):
            compact["curve"] = [
                cls._planning_scalar_summary(item, keys=("step", "best_score", "score", "candidate_id"))
                for item in curve[-24:]
                if isinstance(item, dict)
            ]
        surrogate_trace = payload.get("surrogate_trace")
        if isinstance(surrogate_trace, list):
            trace: list[dict[str, Any]] = []
            for item in surrogate_trace[-24:]:
                if not isinstance(item, dict):
                    continue
                entry = cls._planning_scalar_summary(
                    item,
                    keys=("iteration", "acquisition", "acquisition_value", "score", "candidate_id"),
                )
                selected = item.get("selected") if isinstance(item.get("selected"), dict) else {}
                if selected:
                    entry["selected"] = cls._planning_scalar_summary(
                        selected,
                        keys=("acquisition_value", "source_strategy", "parameters"),
                    )
                trace.append(entry)
            compact["surrogate_trace"] = trace
        return compact

    @classmethod
    def _compact_planning_message_for_display(cls, entry: dict[str, Any]) -> dict[str, Any]:
        """Build the small message object returned to the browser on every refresh."""
        if not isinstance(entry, dict):
            return {}
        entry = {**entry, **cls._classify_planning_message(entry)}
        scalar_keys = (
            "role",
            "content",
            "timestamp",
            "ok",
            "schema",
            "message_type",
            "message_class",
            "surface",
            "visibility",
            "event_type",
            "event_fields",
            "agent_id",
            "severity",
            "message_id",
            "transcript_index",
            "cycle_index",
            "total_cycles",
            "requires_response",
            "requires_design_inputs",
            "missing_design_inputs",
            "requires_connection_info",
            "blocks_workflow",
            "pendingReasoning",
            "pending_operator_input",
            "reasoning",
            "command_id",
            "program_id",
            "check_id",
            "shielded_tool",
            "decision",
            "reason_code",
            "risk_score",
            "requires_human_approval",
            "signal_id",
            "zone_id",
            "confidence",
            "stability_ms",
            "windows_host",
            "data_file_ref",
            "failure_code",
        )
        compact = {key: entry.get(key) for key in scalar_keys if key in entry}
        if isinstance(compact.get("content"), str) and len(compact["content"]) > 1800:
            compact["content"] = compact["content"][:1800] + "..."
        if isinstance(compact.get("reasoning"), str) and len(compact["reasoning"]) > 1200:
            compact["reasoning"] = compact["reasoning"][:1200] + "..."
        model = str(entry.get("model") or "")
        if model:
            compact["model"] = model.splitlines()[0][:140]
        if "experiment_spec" in entry:
            compact["experiment_spec"] = cls._planning_display_spec(entry.get("experiment_spec"))
        if "artifacts" in entry:
            compact["artifacts"] = cls._planning_display_artifacts(entry.get("artifacts"))
        if "specimen_artifacts" in entry:
            compact["specimen_artifacts"] = cls._planning_display_artifacts(entry.get("specimen_artifacts"))
        if "fem_artifacts" in entry:
            compact["fem_artifacts"] = cls._planning_display_artifacts(entry.get("fem_artifacts"))
        if "artifact_pair" in entry:
            compact["artifact_pair"] = cls._planning_display_artifact_pair(entry.get("artifact_pair"))
        if "specimen" in entry:
            compact["specimen"] = cls._planning_display_specimen_result(entry.get("specimen"))
        if "bo_result" in entry:
            compact["bo_result"] = cls._planning_display_bo_result(entry.get("bo_result"))
        if "analysis" in entry:
            analysis = entry.get("analysis") if isinstance(entry.get("analysis"), dict) else {}
            compact["analysis"] = cls._select_runtime_fields(
                analysis,
                (
                    "ok",
                    "objective_score",
                    "uncertainty",
                    "recommendation",
                    "summary",
                    "utm_metrics",
                    "utm_curve",
                    "data_quality_gate",
                    "fem_metrics",
                    "cae_metrics",
                    "quality_gate",
                    "fem_utm_comparison",
                    "multifidelity_comparison",
                    "trust_score",
                    "fidelity_records",
                    "analysis_artifacts",
                    "bo_handoff",
                ),
            )
        # Agent reports can use state.run_metadata; avoid shipping bulky per-message internals every poll.
        for key in (
            "module_runtime",
            "equipment_runtime_event",
            "macro_command",
            "equipment_result",
            "data_ledger",
            "data_acquisition",
            "visual_assertion",
            "physical_cross_check",
            "recovery",
            "handoff_packet",
            "vision_signal",
            "vision_cross_check_event",
            "guardian_gate",
        ):
            value = entry.get(key)
            if isinstance(value, dict):
                compact[key] = compact_runtime_payload(value)
            elif isinstance(value, list):
                compact[key] = compact_runtime_payload(value[:12])
        return compact

    def planning_messages_page(
        self,
        *,
        session_id: str | None = None,
        before: int | None = None,
        limit: int = PLANNING_TRANSCRIPT_PAGE_LIMIT,
    ) -> dict[str, Any]:
        """Return a page of transcript messages without loading the full chat history."""
        self._bind_planning_session(session_id)
        self._ensure_planning_intro()
        self._ensure_orchestrator_supervisor_baseline()
        try:
            clean_limit = max(1, min(int(limit), PLANNING_TRANSCRIPT_MAX_PAGE_LIMIT))
        except (TypeError, ValueError):
            clean_limit = PLANNING_TRANSCRIPT_PAGE_LIMIT
        clean_before: int | None
        try:
            clean_before = int(before) if before is not None else None
        except (TypeError, ValueError):
            clean_before = None

        path = self._planning_transcript_path()
        records: list[dict[str, Any]] = []
        total = 0
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle):
                        raw = line.strip()
                        if not raw:
                            continue
                        try:
                            message = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(message, dict):
                            continue
                        index = int(message.get("transcript_index", line_number))
                        message["transcript_index"] = index
                        total = max(total, index + 1)
                        if clean_before is not None and index >= clean_before:
                            continue
                        records.append(message)
                        if len(records) > clean_limit:
                            del records[0]
            except OSError:
                records = list(self._planning_messages[-clean_limit:])
                total = max(self._planning_message_total, len(records))
        else:
            records = list(self._planning_messages[-clean_limit:])
            total = max(self._planning_message_total, len(records))
        self._planning_message_total = max(self._planning_message_total, total)
        first_index = int(records[0].get("transcript_index", 0)) if records else 0
        display_records = [self._compact_planning_message_for_display(record) for record in records]
        return {
            "messages": display_records,
            "message_total": total,
            "messages_loaded": len(records),
            "message_limit": clean_limit,
            "message_before": clean_before,
            "has_more_messages": bool(records and first_index > 0),
            "next_before": first_index if records and first_index > 0 else None,
            "transcript_path": str(path),
        }

    @classmethod
    def _compact_planning_payload(cls, value: Any, *, depth: int = 0) -> Any:
        """Trim bulky nested runtime payloads before sending repeated Live GUI snapshots."""
        large_context_keys = {
            "source_stage_context",
            "handoff_packet",
            "utm_data_ready",
            "prior_evaluations",
            "raw_trace",
            "raw_events",
            "full_payload",
            "full_context",
        }
        if depth >= 6:
            if isinstance(value, dict):
                return {"_truncated": "depth_limit", "keys": list(value.keys())[:16]}
            if isinstance(value, list):
                return {"_truncated": "depth_limit", "items": len(value)}
            text = str(value)
            return text[:300] + "..." if len(text) > 300 else value
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            for key, child in value.items():
                key_text = str(key)
                if key_text in large_context_keys:
                    compact[key_text] = {
                        "_omitted": "large_runtime_context",
                        "type": type(child).__name__,
                        "keys": list(child.keys())[:16] if isinstance(child, dict) else None,
                        "items": len(child) if isinstance(child, (dict, list)) else None,
                    }
                    continue
                compact[key_text] = cls._compact_planning_payload(child, depth=depth + 1)
            return compact
        if isinstance(value, list):
            limit = 24
            items = [cls._compact_planning_payload(item, depth=depth + 1) for item in value[:limit]]
            if len(value) > limit:
                items.append({"_truncated_items": len(value) - limit})
            return items
        if isinstance(value, str) and len(value) > 4000:
            return value[:4000] + "..."
        return value

    @classmethod
    def _planning_scalar_summary(cls, value: Any, *, keys: tuple[str, ...] = ()) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        default_keys = (
            "schema", "status", "ok", "summary", "decision", "reason", "reason_code",
            "failure_code", "candidate_id", "specimen_id", "geometry_type", "objective_score",
            "uncertainty", "score", "risk_score", "created_at", "artifact_path", "report_url",
            "preview_url", "stl_url", "gcode_path", "result_file", "linux_path",
            "incident_id", "alert_id", "device_class", "component", "severity",
            "blocks_workflow", "requires_ack", "corrective_action",
        )
        out: dict[str, Any] = {}
        for key in (*default_keys, *keys):
            if key not in value:
                continue
            item = value.get(key)
            if isinstance(item, str):
                out[key] = item[:500]
            elif isinstance(item, (int, float, bool)) or item is None:
                out[key] = item
            elif isinstance(item, list):
                out[key] = item[:6]
            elif isinstance(item, dict):
                out[key] = {str(k): v for k, v in list(item.items())[:12] if isinstance(v, (str, int, float, bool)) or v is None}
        return out

    @classmethod
    def _planning_list_summary(cls, value: Any, limit: int = 4) -> list[Any]:
        if not isinstance(value, list):
            return []
        return [cls._planning_scalar_summary(item) if isinstance(item, dict) else item for item in value[-limit:]]

    @classmethod
    def _compact_planning_run_metadata(cls, metadata: Any) -> dict[str, Any]:
        """Return a Live-GUI-sized run_metadata allowlist.

        The full runtime metadata can contain repeated STL/FEM/BO/history payloads.
        Live polling must never serialize those raw structures on every refresh.
        """
        if not isinstance(metadata, dict):
            return {}

        skip_keys = {
            "latest_vision_observation",
            "vision_vision_report",
            "manipulation_manipulation_report",
            "specimen_fabrication_report",
            "equipment_handoff_packet",
            "module_runtime",
            "module_step_trace",
            "module_step_results",
            "workspace_runtime_events",
            "runtime_artifacts",
            "raw_trace",
            "raw_events",
            "source_stage_context",
            "full_context",
            "full_payload",
            "raw_input_sidecar",
            "stl_text",
            "stl_bytes",
            "mesh_vertices",
            "mesh_faces",
        }
        allow_keys = {
            "pending_specimen_input",
            "mission_contract",
            "latest_mission_contract",
            "latest_orchestration_plan",
            "latest_orchestrator_followup",
            "latest_orchestrator_decision",
            "latest_orchestrator_handoff",
            "latest_orchestrator_control_plane",
            "latest_orchestrator_parallel_checks",
            "latest_operator_followup",
            "operator_followup_context",
            "latest_loop_reflection",
            "design_report",
            "latest_design_agent_report",
            "design_candidate",
            "fabrication_report",
            "latest_specimen_agent_report",
            "specimen_result",
            "specimen_fabricated",
            "vision_report",
            "latest_vision_agent_report",
            "vision_signal",
            "manipulation_report",
            "latest_manipulation_agent_report",
            "manipulation_result",
            "robot_task_result",
            "equipment_report",
            "equipment_result",
            "equipment_handoff",
            "utm_data_ready",
            "latest_analysis",
            "knowledge",
            "knowledge_report",
            "knowledge_context",
            "bo_agent",
            "bo_recommended_constraints",
            "next_design_request",
            "guardian",
            "latest_guardian_gate",
            "latest_guardian_gate_decision",
            "latest_guardian_decision",
            "safe_stop_verified",
            "safe_stop_confirmed",
            "safety_budget",
            "risk_budget",
            "runtime_approvals",
            "approval_blocked_stage",
            "approval_rejection",
            "active_module_step",
            "runtime_graph",
            "backend",
            "mode",
            "active_models",
            "inference_backend",
        }
        list_limits = {
            "orchestration_plans": 4,
            "handoff_packets": 3,
            "orchestrator_handoff_packets": 3,
            "orchestrator_followups": 4,
            "orchestrator_decision_register": 4,
            "loop_reflections": 6,
            "orchestrator_parallel_checks": 4,
            "operator_followup_queue": 8,
            "operator_followups": 8,
            "tool_call_records": 6,
            "incident_records": 6,
            "hardware_alerts": 6,
            "corrective_actions": 12,
            "guardian_contracts": 4,
            "guardian_gates": 6,
            "guardian_approval_queue": 20,
        }

        compact: dict[str, Any] = {}
        for key, value in metadata.items():
            key_text = str(key)
            if key_text in skip_keys or key_text.endswith("_agent_payload"):
                continue
            include = key_text in allow_keys or key_text in list_limits or key_text.endswith("_handoff_packet") or key_text.endswith("_decision_register") or key_text.endswith("_metrics")
            if not include:
                continue
            if key_text in list_limits and isinstance(value, list):
                compact[key_text] = cls._planning_list_summary(value, limit=list_limits[key_text])
                continue
            if key_text in {
                "design_report", "fabrication_report", "vision_report", "manipulation_report",
                "equipment_report", "equipment_result", "equipment_handoff", "utm_data_ready",
                "latest_analysis", "guardian", "latest_guardian_gate", "latest_guardian_gate_decision",
                "latest_guardian_decision", "runtime_graph", "latest_orchestrator_parallel_checks",
            } and isinstance(value, dict):
                compact[key_text] = cls._planning_scalar_summary(value)
                continue
            compact[key_text] = compact_runtime_payload(value)

        if isinstance(compact.get("last_stage_payload"), dict):
            payload = compact["last_stage_payload"]
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            compact["last_stage_payload"] = {
                "stage": payload.get("stage"),
                "data_keys": sorted(str(key) for key in data.keys())[:40],
            }
        if isinstance(metadata.get("last_stage_payload"), dict) and "last_stage_payload" not in compact:
            payload = metadata.get("last_stage_payload") or {}
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            compact["last_stage_payload"] = {
                "stage": payload.get("stage"),
                "data_keys": sorted(str(key) for key in data.keys())[:40],
            }
        if isinstance(metadata.get("specimen_result"), dict):
            compact["specimen_result"] = cls._planning_display_specimen_result(metadata.get("specimen_result"))
        if isinstance(metadata.get("bo_agent"), dict):
            compact["bo_agent"] = cls._planning_display_bo_result(metadata.get("bo_agent"))
        if isinstance(metadata.get("knowledge"), dict):
            knowledge = metadata.get("knowledge")
            compact["knowledge"] = cls._select_runtime_fields(
                compact_runtime_payload(knowledge),
                (
                    "retrieval_coverage",
                    "local_chunks",
                    "web_results",
                    "failure_pattern_count",
                    "success_pattern_count",
                    "agent_performance_count",
                    "evolution_pack_count",
                    "graph_backend_status",
                    "artifact_paths",
                    "knowledge_report",
                    "evolution_proposal",
                ),
            )
        if isinstance(metadata.get("guardian_gates"), list):
            compact["guardian_gates"] = [
                cls._select_runtime_fields(item, ("stage", "phase", "decision", "reason_code", "risk_score", "ok_for_next_stage", "created_at"))
                for item in metadata["guardian_gates"][-20:]
                if isinstance(item, dict)
            ]
        return compact

    @classmethod
    def _compact_planning_state_for_display(cls, state_json: Any) -> dict[str, Any]:
        """Return only the state fields the Live GUI needs on frequent refreshes."""
        if not isinstance(state_json, dict):
            return {}
        metadata = state_json.get("run_metadata") if isinstance(state_json.get("run_metadata"), dict) else {}
        evaluations = state_json.get("experiment_evaluations") if isinstance(state_json.get("experiment_evaluations"), list) else []
        agent_status = state_json.get("agent_status") if isinstance(state_json.get("agent_status"), dict) else {}
        return {
            "run_id": state_json.get("run_id", ""),
            "experiment_id": state_json.get("experiment_id", ""),
            "mode": state_json.get("mode", ""),
            "stage": state_json.get("stage", ""),
            "active_goal": state_json.get("active_goal", ""),
            "device_health": compact_runtime_payload(state_json.get("device_health", {})),
            "current_experiment_spec": cls._planning_display_spec(state_json.get("current_experiment_spec")),
            "current_experiment_objective": compact_runtime_payload(state_json.get("current_experiment_objective", {})),
            "experiment_evaluations": cls._planning_list_summary(evaluations, limit=3),
            "active_session_id": state_json.get("active_session_id", ""),
            "latest_observations": cls._planning_scalar_summary(state_json.get("latest_observations", {})),
            "latest_analysis": cls._planning_scalar_summary(state_json.get("latest_analysis", {})),
            "retry_counters": compact_runtime_payload(state_json.get("retry_counters", {})),
            "run_metadata": cls._compact_planning_run_metadata(metadata),
            "agent_status": compact_runtime_payload(agent_status),
            "fault_injection": compact_runtime_payload(state_json.get("fault_injection", {})),
            "is_paused": bool(state_json.get("is_paused", False)),
            "stop_requested": bool(state_json.get("stop_requested", False)),
            "safe_stop_requested": bool(state_json.get("safe_stop_requested", False)),
            "loop_count": state_json.get("loop_count", 0),
        }

    def _planning_state_payload(self) -> dict[str, Any]:
        """Return a compact state payload for high-frequency Live GUI refreshes."""
        self._ensure_orchestrator_supervisor_baseline()
        state_json = self._state.model_dump(mode="json")
        return self._compact_planning_state_for_display(state_json)

    def planning_snapshot(self, *, session_id: str | None = None) -> dict[str, Any]:
        """Return current live-planning context with only the latest transcript page."""
        page = self.planning_messages_page(session_id=session_id, limit=PLANNING_TRANSCRIPT_PAGE_LIMIT)
        return {
            "messages": page["messages"],
            "message_total": page["message_total"],
            "messages_loaded": page["messages_loaded"],
            "message_limit": page["message_limit"],
            "has_more_messages": page["has_more_messages"],
            "next_before": page["next_before"],
            "transcript_path": page["transcript_path"],
            "state": self._planning_state_payload(),
            "runtime": self._runtime_profile(),
            "is_running": bool(self._run_task and not self._run_task.done()) or self._planning_handoff_active(),
            "is_planning_busy": self._planning_request_lock.locked() or self._planning_handoff_active(),
            "planning_session_id": self._planning_session_id,
        }

    def prepare_live_gui(
        self,
        *,
        goal: str | None = None,
        backend: str | None = None,
        reset: bool = False,
    ) -> dict[str, Any]:
        """Prepare the shared controller state for the live GUI without starting hardware."""
        if self._run_task and not self._run_task.done():
            return self.planning_snapshot()
        self._apply_inference_backend(backend)
        self._state.mode = Mode.LIVE
        if goal:
            self._state.active_goal = goal
        if reset:
            self._reset_planning_transcript()
            self._planning_session_id = None
            self._planning_bootstrapped = False
        self._ensure_planning_intro()
        return self.planning_snapshot()

    def _bind_planning_session(self, session_id: str | None) -> None:
        """Bind Live GUI to a shared server-side conversation for all open windows."""
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return
        if self._planning_session_id is None:
            self._planning_session_id = clean_session_id
            return
        if clean_session_id == self._planning_session_id:
            return
        # A newly opened browser window may have a different local id. Do not clear
        # the server-side Live GUI transcript; reset is handled explicitly by fresh=1.
        return

    def _ensure_planning_intro(self) -> None:
        """Keep the Live GUI session initialized without injecting static chat copy."""
        return

    async def _append_planning_message(
        self,
        entry: dict[str, Any],
        *,
        event_type: str = "planning_message",
        level: str = "INFO",
        message: str = "Live GUI planning message updated.",
    ) -> None:
        """Append one Live GUI message and broadcast a compact event for incremental display."""
        stored_entry = self._record_planning_message(entry)
        await self._broadcast_event(
            {
                "event_id": f"evt-planning-{stored_entry.get('transcript_index', 0)}",
                "run_id": self._state.run_id,
                "experiment_id": self._state.experiment_id,
                "event_type": event_type,
                "level": level,
                "message": message,
                "payload": {"latest": self._compact_planning_message_for_event(stored_entry)},
                "state": self._planning_state_context(),
            }
        )

    def _append_orchestrator_metadata(self, key: str, record: dict[str, Any], *, limit: int = 200) -> None:
        records = self._state.run_metadata.setdefault(key, [])
        if not isinstance(records, list):
            records = []
            self._state.run_metadata[key] = records
        records.append(record)
        del records[:-limit]

    @staticmethod
    def _format_orchestrator_followup_message(followup: dict[str, Any]) -> str:
        concerns = followup.get("concerns") if isinstance(followup.get("concerns"), list) else []
        concerns_text = ", ".join(str(item) for item in concerns[:4]) if concerns else "none"
        options = followup.get("options") if isinstance(followup.get("options"), list) else []
        options_text = ""
        if options:
            options_text = "\n- options: " + "; ".join(
                str(item.get("label") or item.get("id") or item) for item in options[:3] if isinstance(item, dict)
            )
        return (
            "Orchestrator supervisor follow-up\n"
            f"- stage: {followup.get('stage', '-')} / trigger: {followup.get('trigger', '-')}\n"
            f"- 판단: {followup.get('opinion', '-')}\n"
            f"- 우려: {concerns_text}\n"
            f"- 추천: {followup.get('recommendation', '-')}"
            f"{options_text}"
        )

    async def _record_planning_orchestrator_followup(
        self,
        *,
        stage: Stage,
        trigger: str,
        payload: dict[str, Any] | None = None,
        next_stage: Stage | None = None,
        guardian_context: dict[str, Any] | None = None,
        level: str = "INFO",
    ) -> dict[str, Any]:
        followup = build_orchestrator_followup(
            state=self._state,
            stage=stage,
            trigger=trigger,
            payload=payload or {},
            next_stage=next_stage,
            guardian_context=guardian_context,
        )
        self._append_orchestrator_metadata("orchestrator_followups", followup)
        self._state.run_metadata["latest_orchestrator_followup"] = followup
        await self._append_planning_message(
            {
                "schema": "live_chat_message.v1",
                "role": "orchestrator",
                "message_type": "warning" if followup.get("concerns") else "decision",
                "content": self._format_orchestrator_followup_message(followup),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "orchestrator_supervisor",
                "ok": followup.get("status") != "error",
                "orchestrator_followup": followup,
                "requires_response": bool(followup.get("requires_response")),
                "evidence_refs": followup.get("evidence_refs", []),
            },
            event_type="planning_orchestrator_followup",
            level=level,
            message=f"Orchestrator supervisor follow-up recorded for {stage.value}.",
        )
        return followup

    def _runtime_followup_is_active(self, constraints: dict[str, Any]) -> bool:
        """Return True when a Live GUI chat message should be routed into the active runtime loop."""
        if bool(constraints.get("live_runtime_followup_queue_only")):
            return True
        if bool(constraints.get("live_is_running")):
            return True
        if self._run_task and not self._run_task.done():
            return True
        return self._planning_handoff_active()

    def _operator_followup_record(
        self,
        *,
        message: str,
        goal: str | None,
        constraints: dict[str, Any],
        session_id: str | None,
        user_entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        target_agent = str(
            constraints.get("live_chat_target_resolved")
            or constraints.get("live_chat_target")
            or constraints.get("live_selected_agent")
            or "orchestrator"
        )
        selected_agent = str(constraints.get("live_selected_agent") or "")
        selected_node = str(
            constraints.get("live_selected_node_id")
            or constraints.get("live_selected_graph_node_id")
            or selected_agent
            or target_agent
            or self._state.stage.value
        )
        run_context = {
            "run_id": constraints.get("live_run_id") or self._state.run_id,
            "mode": constraints.get("live_mode") or self._state.mode.value,
            "stage": constraints.get("live_stage") or self._state.stage.value,
            "is_running": bool(constraints.get("live_is_running", bool(self._run_task and not self._run_task.done()))),
            "active_goal": constraints.get("live_active_goal") or self._state.active_goal,
        }
        record = {
            "schema": "operator_runtime_followup.v1",
            "followup_id": make_event_id(),
            "status": "queued",
            "message": message,
            "goal": goal or self._state.active_goal,
            "session_id": session_id or self._planning_session_id or "",
            "run_id": self._state.run_id,
            "experiment_id": self._state.experiment_id,
            "loop_id": self._state.loop_count,
            "stage_at_submit": self._state.stage.value,
            "target_agent": target_agent,
            "target_agent_mode": str(constraints.get("live_chat_target_mode") or ""),
            "selected_agent": selected_agent,
            "selected_node": selected_node,
            "chat_mode": str(constraints.get("live_chat_mode") or "ask"),
            "operator_intent": normalize_operator_intent(message),
            "run_context": run_context,
            "transcript_message_id": user_entry.get("message_id") if isinstance(user_entry, dict) else "",
            "transcript_index": user_entry.get("transcript_index") if isinstance(user_entry, dict) else None,
            "created_at": now,
        }
        queue = self._state.run_metadata.setdefault("operator_followup_queue", [])
        if not isinstance(queue, list):
            queue = []
            self._state.run_metadata["operator_followup_queue"] = queue
        queue.append(record)
        del queue[:-50]
        history = self._state.run_metadata.setdefault("operator_followups", [])
        if not isinstance(history, list):
            history = []
            self._state.run_metadata["operator_followups"] = history
        history.append(record)
        del history[:-200]
        self._state.run_metadata["latest_operator_followup"] = record
        return record

    async def _queue_runtime_operator_followup(
        self,
        *,
        message: str,
        goal: str | None,
        constraints: dict[str, Any],
        session_id: str | None,
        user_entry: dict[str, Any] | None = None,
        append_ack: bool = False,
    ) -> dict[str, Any]:
        record = self._operator_followup_record(
            message=message,
            goal=goal,
            constraints=constraints,
            session_id=session_id,
            user_entry=user_entry,
        )
        await self.emit_runtime_event(
            event_type="operator.followup_queued",
            message="Operator follow-up queued for Orchestrator runtime.",
            payload={
                "agent": "orchestrator",
                "node_id": record.get("stage_at_submit") or self._state.stage.value,
                "module_id": "orchestrator",
                "status": "queued",
                "operator_followup": record,
                "target_agent_id": record.get("target_agent", ""),
                "chat_mode": record.get("chat_mode", "ask"),
                "source": "live_gui_chat",
            },
        )
        if append_ack:
            await self._append_planning_message(
                {
                    "schema": "live_chat_message.v1",
                    "role": "orchestrator",
                    "message_type": "decision",
                    "content": (
                        "실행 중 입력을 받았습니다. 현재 동작을 끊지 않고 다음 안전한 stage boundary에서 "
                        "오케스트레이터가 이 내용을 반영합니다."
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "orchestrator_supervisor",
                    "ok": True,
                    "operator_followup": record,
                    "requires_response": False,
                },
                event_type="planning_operator_followup_queued",
                message="Operator follow-up queued for active runtime.",
            )
        return record

    async def _queue_runtime_operator_followup_message(
        self,
        *,
        message: str,
        goal: str | None,
        constraints: dict[str, Any],
        session_id: str | None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        operator_intent = normalize_operator_intent(message)
        user_entry = self._record_planning_message(
            {
                "role": "operator",
                "content": message,
                "timestamp": now,
                "goal": goal or self._state.active_goal,
                "constraints": constraints,
                "operator_intent": operator_intent,
            }
        )
        await self.emit_runtime_event(
            event_type="user_reply",
            message="Operator follow-up submitted from Live GUI while runtime was busy.",
            payload={
                "latest": user_entry,
                "session_id": session_id or self._planning_session_id or "",
                "agent_id": constraints.get("live_chat_target_resolved") or constraints.get("live_chat_target") or "orchestrator",
                "target_agent_id": constraints.get("live_chat_target_resolved") or constraints.get("live_chat_target") or "orchestrator",
                "stage": constraints.get("live_stage") or self._state.stage.value,
                "node_id": constraints.get("live_stage") or self._state.stage.value,
                "operator_intent": operator_intent,
                "chat_mode": constraints.get("live_chat_mode") or "ask",
                "source": "live_gui",
            },
        )
        await self._queue_runtime_operator_followup(
            message=message,
            goal=goal,
            constraints=constraints,
            session_id=session_id,
            user_entry=user_entry,
            append_ack=True,
        )
        return {"ok": True, "message": "Runtime follow-up queued.", "session": self.planning_snapshot(session_id=session_id)}

    async def _record_planning_orchestrator_transition(
        self,
        *,
        from_stage: Stage,
        to_stage: Stage,
        payload: dict[str, Any] | None = None,
        selected_transition: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        result_payload = payload or {}
        decision = build_decision_record(
            state=self._state,
            stage=from_stage,
            decision="planning_route_next_stage",
            selected=to_stage.value,
            alternatives=[to_stage.value],
            reason="Live GUI planning chain selected the next graph stage.",
            authority="orchestrator",
        )
        handoff = build_orchestrator_handoff_packet(
            state=self._state,
            from_stage=from_stage,
            to_stage=to_stage,
            result_payload=result_payload,
            selected_transition=selected_transition or {"to_stage": to_stage.value, "source": "planning_chain"},
        )
        self._append_orchestrator_metadata("orchestrator_decision_register", decision)
        self._append_orchestrator_metadata("orchestrator_handoff_packets", handoff)
        self._state.run_metadata["latest_orchestrator_decision"] = decision
        self._state.run_metadata["latest_orchestrator_handoff"] = handoff
        mission_contract = build_mission_contract(state=self._state)
        orchestration_plan = self._build_orchestration_plan()
        self._state.run_metadata["mission_contract"] = mission_contract
        self._state.run_metadata["latest_mission_contract"] = mission_contract
        self._append_orchestrator_metadata("orchestration_plans", orchestration_plan, limit=20)
        self._state.run_metadata["latest_orchestration_plan"] = orchestration_plan
        await self.emit_runtime_event(
            event_type="orchestrator.decision",
            message=f"Orchestrator planning route {from_stage.value} -> {to_stage.value}",
            payload={
                "agent": "orchestrator",
                "node_id": from_stage.value,
                "module_id": "orchestrator",
                "decision": decision,
                "handoff_packet": handoff,
                "status": "ok",
            },
        )
        return decision, handoff

    def subscribe(self, queue_size: int = 200) -> asyncio.Queue[dict[str, Any]]:
        """Create a new event subscription queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self._event_queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove event subscription queue."""
        self._event_queues.discard(queue)

    async def _emit_control_event(self, event_type: str, message: str, payload: dict[str, Any] | None = None, level: str = "INFO") -> None:
        """Emit auditable control-plane events for GUI/runtime action tracking."""
        state_json = self._state.model_dump(mode="json")
        event_payload = dict(payload or {})
        event_payload.setdefault("source", "controller")
        event_payload.setdefault("stage", state_json.get("stage", ""))
        await self._broadcast_controller_event(
            {
                "event_id": make_event_id(),
                "run_id": self._state.run_id,
                "experiment_id": self._state.experiment_id,
                "timestamp_stage": state_json.get("stage", ""),
                "event_type": event_type,
                "level": level,
                "message": message,
                "payload": event_payload,
                "state": state_json,
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                "severity": level.lower(),
                "graph_id": event_payload.get("graph_id", "atr_closed_loop"),
                "node_id": event_payload.get("node_id", event_payload.get("stage", state_json.get("stage", ""))),
                "module_id": event_payload.get("module_id", ""),
                "agent": event_payload.get("agent", ""),
                "status": event_payload.get("status", "ok" if level != "ERROR" else "failed"),
            }
        )

    async def _run_live_or_test(self) -> None:
        configured_interval = float(self._deps.system_config.get("loop_interval_seconds", 1.25))
        loop = RunLoop(
            state=self._state,
            agent_registry=self._deps.agent_registry,
            orchestrator_agent_name=self._deps.orchestrator_agent_name,
            ctx=self._deps.agent_context,
            logger=self._logger_bundle.logger,
            max_retry_per_stage=int(self._deps.system_config.get("max_retry_per_stage", 2)),
            interval_seconds=0.0 if self._state.mode == Mode.TEST else configured_interval,
            on_event=self._broadcast_event,
            graph_config_path=self._active_graph_config_path,
        )
        try:
            await loop.run()
            self._last_completed_trace = self._trace.snapshot()
        finally:
            self._schedule_post_run_vllm_transition()

    async def _run_replay(self) -> None:
        if not self._last_completed_trace:
            await self._broadcast_event(
                {
                    "event_id": "evt-replay-empty",
                    "event_type": "replay_empty",
                    "message": "No previous run to replay.",
                    "payload": {},
                    "state": self._state.model_dump(mode="json"),
                }
            )
            self._state.stage = Stage.COMPLETE
            return
        for event in self._last_completed_trace:
            replay_event = dict(event)
            replay_event["event_type"] = "replay_event"
            await self._broadcast_event(replay_event)
            await asyncio.sleep(0.15)
        self._state.stage = Stage.COMPLETE
        await self._broadcast_event(
            {
                "event_id": "evt-replay-done",
                "event_type": "replay_complete",
                "message": "Replay finished.",
                "payload": {},
                "state": self._state.model_dump(mode="json"),
            }
        )

    async def start(
        self,
        *,
        mode: Mode,
        goal: str | None = None,
        backend: str | None = None,
        fault: str = "none",
        fault_stage: str = "",
        graph_id: str = "atr_closed_loop",
        graph_config_path: str | Path | None = None,
        graph_hash: str = "",
        graph_version: str = "",
        graph_version_id: str = "",
        graph_version_path: str = "",
    ) -> dict[str, Any]:
        """Start a new run if idle."""
        if self._run_task and not self._run_task.done():
            return {"ok": False, "message": "Run already active."}

        try:
            self._apply_inference_backend(backend)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        self._cancel_pending_vllm_transition()

        self._active_graph_id = graph_id or "atr_closed_loop"
        self._active_graph_config_path = Path(graph_config_path) if graph_config_path else None
        self._trace = RunTrace(max_events=int(self._deps.system_config.get("event_buffer_size", 300)))
        self._logger_bundle = self._new_logger_bundle()
        self._state = self._new_state(mode=mode)
        self._state.run_metadata["runtime_graph"] = {
            "graph_id": self._active_graph_id,
            "config_path": str(self._active_graph_config_path or ""),
            "primary": self._active_graph_id == "atr_closed_loop",
            "graph_hash": graph_hash,
            "graph_version": graph_version,
            "graph_version_id": graph_version_id,
            "graph_version_path": graph_version_path,
        }
        if goal:
            self._state.active_goal = goal
        self._state.fault_injection = {"fault": fault, "stage": fault_stage}

        await self.emit_runtime_event(
            event_type="run.created",
            message=f"Run created in mode={mode.value}",
            payload={
                "graph_id": self._active_graph_id,
                "node_id": self._state.stage.value,
                "status": "created",
                "mode": mode.value,
                "goal": self._state.active_goal,
                "graph_config_path": str(self._active_graph_config_path or ""),
                "graph_hash": graph_hash,
                "graph_version": graph_version,
                "graph_version_id": graph_version_id,
                "graph_version_path": graph_version_path,
            },
        )

        if mode == Mode.REPLAY:
            self._run_task = asyncio.create_task(self._run_replay())
        else:
            self._run_task = asyncio.create_task(self._run_live_or_test())
        return {
            "ok": True,
            "message": f"Run started in mode={mode.value}",
            "run_id": self._state.run_id,
            "graph_id": self._active_graph_id,
            "graph_config_path": str(self._active_graph_config_path or ""),
            "graph_hash": graph_hash,
            "graph_version": graph_version,
            "graph_version_id": graph_version_id,
            "graph_version_path": graph_version_path,
            "startup_vllm": {"enabled": False, "manual_loading_required": True},
        }

    async def pause(self) -> dict[str, Any]:
        """Pause the active run loop."""
        self._state.is_paused = True
        await self._emit_control_event("run_pause", "Run paused by operator", {"status": "paused", "control": "pause", "operator_action": True})
        return {"ok": True, "message": "Paused", "state": self._state.model_dump(mode="json")}

    async def resume(self) -> dict[str, Any]:
        """Resume paused run loop."""
        self._state.is_paused = False
        await self._emit_control_event("run_resume", "Run resumed by operator", {"status": "resumed", "control": "resume", "operator_action": True})
        return {"ok": True, "message": "Resumed", "state": self._state.model_dump(mode="json")}

    async def stop(self) -> dict[str, Any]:
        """Request stop for active run."""
        self._state.stop_requested = True
        if self._run_task and not self._run_task.done():
            self._state.stage = Stage.COMPLETE
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
            await self._emit_control_event("run_stop", "Stop requested by operator (forced cancel)")
            await self._emit_control_event("run_complete", "Run finished in stage=complete")
            self._last_completed_trace = self._trace.snapshot()
        return {"ok": True, "message": "Stop requested"}

    async def safe_stop(self) -> dict[str, Any]:
        """Request safe stop for active run."""
        self._state.safe_stop_requested = True
        await self._emit_control_event(
            "run_safe_stop",
            "Safe stop requested by operator",
            {"status": "safe_stop_requested", "control": "safe_stop", "operator_action": True},
            level="WARNING",
        )
        return {"ok": True, "message": "Safe stop requested", "state": self._state.model_dump(mode="json")}

    async def planning_message(
        self,
        *,
        message: str,
        goal: str | None = None,
        backend: str | None = None,
        constraints: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the top-level orchestrator model for live-planning discussion only."""
        try:
            self._apply_inference_backend(backend)
        except Exception as exc:
            return {"ok": False, "message": str(exc), "session": self.planning_snapshot(session_id=session_id)}
        self._cancel_pending_vllm_transition()
        self._bind_planning_session(session_id)
        self._ensure_planning_intro()
        constraints = constraints or {}
        clean_message = message.strip()
        if not clean_message:
            return {"ok": False, "message": "Planning message is empty.", "session": self.planning_snapshot(session_id=session_id)}
        if self._planning_request_lock.locked():
            if self._runtime_followup_is_active(constraints):
                return await self._queue_runtime_operator_followup_message(
                    message=clean_message,
                    goal=goal,
                    constraints=constraints,
                    session_id=session_id,
                )
            return {
                "ok": False,
                "message": "Live GUI orchestrator is still reasoning.",
                "session": self.planning_snapshot(session_id=session_id),
            }

        async with self._planning_request_lock:
            return await self._planning_message_locked(
                message=clean_message,
                goal=goal,
                constraints=constraints,
                session_id=session_id,
            )

    async def _planning_message_locked(
        self,
        *,
        message: str,
        goal: str | None,
        constraints: dict[str, Any],
        session_id: str | None,
    ) -> dict[str, Any]:
        """Handle one operator message while the Live GUI planning lock is held."""
        now = datetime.now(timezone.utc).isoformat()
        operator_intent = normalize_operator_intent(message)
        user_entry = {
            "role": "operator",
            "content": message,
            "timestamp": now,
            "goal": goal or self._state.active_goal,
            "constraints": constraints,
            "operator_intent": operator_intent,
        }
        user_entry = self._record_planning_message(user_entry)
        target_agent = str(
            constraints.get("live_chat_target_resolved")
            or constraints.get("live_chat_target")
            or constraints.get("live_selected_agent")
            or "operator"
        )
        selected_agent = str(constraints.get("live_selected_agent") or "")
        selected_node = str(
            constraints.get("live_selected_node_id")
            or constraints.get("live_selected_graph_node_id")
            or selected_agent
            or target_agent
            or self._state.stage.value
        )
        selected_trace_id = str(constraints.get("live_selected_trace_id") or "")
        selected_event_key = str(constraints.get("live_selected_event_key") or "")
        selected_report_section_text = str(constraints.get("live_selected_report_section_text") or "")
        chat_mode = str(constraints.get("live_chat_mode") or "ask")
        run_context = {
            "run_id": constraints.get("live_run_id") or self._state.run_id,
            "mode": constraints.get("live_mode") or self._state.mode.value,
            "stage": constraints.get("live_stage") or self._state.stage.value,
            "is_running": bool(constraints.get("live_is_running", bool(self._run_task and not self._run_task.done()))),
            "active_goal": constraints.get("live_active_goal") or self._state.active_goal,
        }
        await self.emit_runtime_event(
            event_type="user_reply",
            message="Operator reply submitted from Live GUI.",
            payload={
                "latest": user_entry,
                "session_id": session_id or self._planning_session_id or "",
                "agent_id": target_agent,
                "target_agent_id": target_agent,
                "selected_agent_id": selected_agent,
                "stage": selected_node,
                "node_id": selected_node,
                "selected_node_id": selected_node,
                "selected_graph_node_id": constraints.get("live_selected_graph_node_id") or "",
                "trace_id": selected_trace_id,
                "selected_trace_id": selected_trace_id,
                "event_key": selected_event_key,
                "selected_event_key": selected_event_key,
                "selected_event_id": constraints.get("live_selected_event_id") or "",
                "selected_event_type": constraints.get("live_selected_event_type") or "",
                "selected_report_section": constraints.get("live_selected_report_section") or "",
                "selected_report_section_text": selected_report_section_text,
                "selected_report_section_text_excerpt": selected_report_section_text[:600],
                "run_context": run_context,
                "live_run_id": run_context["run_id"],
                "live_mode": run_context["mode"],
                "live_stage": run_context["stage"],
                "live_is_running": run_context["is_running"],
                "live_active_goal": run_context["active_goal"],
                "chat_mode": chat_mode,
                "chat_target_mode": constraints.get("live_chat_target_mode") or "",
                "operator_intent": operator_intent,
                "source": "live_gui",
            },
            level="INFO",
        )

        runtime_followup_active = self._runtime_followup_is_active(constraints)
        if runtime_followup_active:
            await self._queue_runtime_operator_followup(
                message=message,
                goal=goal,
                constraints=constraints,
                session_id=session_id,
                user_entry=user_entry,
                append_ack=bool(constraints.get("live_runtime_followup_queue_only")),
            )
            if bool(constraints.get("live_runtime_followup_queue_only")):
                return {"ok": True, "message": "Runtime follow-up queued.", "session": self.planning_snapshot(session_id=session_id)}

        if not runtime_followup_active and self._should_trigger_test_design(message):
            return await self._run_test_mode_planning(goal=goal, constraints=constraints, operator_message=message)

        if not runtime_followup_active and self._should_route_specimen_printer_choice(message):
            self._ensure_pending_specimen_printer_choice()
            return await self._handle_pending_specimen_operator_input(message=message, session_id=session_id)

        if not runtime_followup_active and self._state.run_metadata.get("pending_specimen_input"):
            return await self._handle_pending_specimen_operator_input(message=message, session_id=session_id)

        if not runtime_followup_active and self._should_trigger_design(message):
            readiness = self._planning_design_handoff_readiness(goal=goal, constraints=constraints)
            if readiness["missing"]:
                return await self._request_missing_design_values(readiness, session_id=session_id)
            return await self._handoff_planning_to_design(
                goal=str(readiness.get("goal") or goal or self._state.active_goal),
                constraints=dict(readiness.get("constraints", constraints)),
            )

        prompt = await self._build_live_orchestrator_prompt(
            operator_message=message,
            goal=goal or self._state.active_goal,
            constraints=constraints,
        )

        try:
            response, response_message = await self._complete_live_planning_prompt(
                prompt=prompt
            )
            assistant_entry = {
                "role": "orchestrator",
                "content": response.text,
                "reasoning": self._extract_reasoning(response.raw),
                "token_usage": self._extract_token_usage(response.raw),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": response.model,
                "ok": True,
            }
            ok = True
        except Exception as exc:
            assistant_entry = {
                "role": "orchestrator",
                "content": (
                    "Live GUI 오케스트레이터 호출에 실패했습니다. "
                    "NemoClaw/Ollama 연결과 모델 상태를 확인하세요.\n"
                    f"error={exc.__class__.__name__}: {exc}"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": None,
                "ok": False,
            }
            ok = False
            response_message = "Live GUI orchestrator_plan call failed."

        await self._append_planning_message(
            assistant_entry,
            level="INFO" if ok else "ERROR",
            message=response_message,
        )
        return {"ok": ok, "message": response_message, "session": self.planning_snapshot(session_id=session_id)}

    async def bootstrap_live_orchestrator(
        self,
        *,
        goal: str | None = None,
        backend: str | None = None,
        constraints: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Warm up and start the Live GUI orchestrator before the operator sends text."""
        try:
            self._apply_inference_backend(backend)
        except Exception as exc:
            return {"ok": False, "message": str(exc), "session": self.planning_snapshot(session_id=session_id)}
        self._cancel_pending_vllm_transition()
        self._bind_planning_session(session_id)
        self.prepare_live_gui(goal=goal, backend=backend, reset=False)
        if self._planning_bootstrapped:
            return {
                "ok": True,
                "message": "Live GUI orchestrator bootstrap already completed.",
                "session": self.planning_snapshot(session_id=session_id),
            }
        if self._planning_request_lock.locked():
            return {
                "ok": False,
                "message": "Live GUI orchestrator is already starting.",
                "session": self.planning_snapshot(session_id=session_id),
            }

        async with self._planning_request_lock:
            if self._planning_bootstrapped:
                return {
                    "ok": True,
                    "message": "Live GUI orchestrator bootstrap already completed.",
                    "session": self.planning_snapshot(session_id=session_id),
                }

            prompt = await self._build_live_orchestrator_prompt(
                operator_message=(
                    "Live GUI was opened from the main Start button. "
                    "No operator message has been sent yet. Start the orchestration discussion by asking for "
                    "the experiment objective, specimen size, material/printer constraints, and the trigger keyword."
                ),
                goal=goal or self._state.active_goal,
                constraints=constraints or {},
            )

            try:
                response, response_message = await self._complete_live_planning_prompt(prompt=prompt)
                assistant_entry = {
                    "role": "orchestrator",
                    "content": response.text,
                    "reasoning": self._extract_reasoning(response.raw),
                    "token_usage": self._extract_token_usage(response.raw),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": response.model,
                    "ok": True,
                    "bootstrap": True,
                }
                self._planning_bootstrapped = True
                ok = True
            except Exception as exc:
                assistant_entry = {
                    "role": "orchestrator",
                    "content": (
                        "Live GUI 오케스트레이터 초기 호출에 실패했습니다. "
                        "send를 누르면 동일한 orchestrator_plan 경로로 다시 호출할 수 있습니다.\n"
                        f"error={exc.__class__.__name__}: {exc}"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": None,
                    "ok": False,
                    "bootstrap": True,
                }
                ok = False
                response_message = "Live GUI orchestrator bootstrap failed."

            await self._append_planning_message(
                assistant_entry,
                event_type="planning_bootstrap",
                level="INFO" if ok else "ERROR",
                message=response_message,
            )
            return {"ok": ok, "message": response_message, "session": self.planning_snapshot(session_id=session_id)}

    async def _run_test_mode_planning(
        self,
        *,
        goal: str | None,
        constraints: dict[str, Any],
        operator_message: str,
    ) -> dict[str, Any]:
        """Let the orchestrator LLM choose concrete test values, then hand off to DesignAgent."""
        base_goal = goal or "테스트 모드 TPMS gyroid(PLA) 압축 시편 설계"
        defaults = self._default_test_constraints(constraints)
        inline_printer_choice = self._parse_inline_test_mode_printer_choice(operator_message)
        if inline_printer_choice:
            defaults = self._apply_specimen_printer_choice_to_spec(defaults, inline_printer_choice)
        prompt = await self._build_test_mode_orchestrator_prompt(
            operator_message=operator_message,
            goal=base_goal,
            constraints=defaults,
        )

        try:
            response, response_message = await self._complete_live_planning_prompt(prompt=prompt)
            llm_payload = self._extract_test_mode_payload(response.text)
            test_goal = str(llm_payload.get("goal") or base_goal)
            llm_constraints = llm_payload.get("constraints") if isinstance(llm_payload.get("constraints"), dict) else {}
            test_constraints = self._normalize_test_mode_constraints(defaults, llm_constraints)
            if inline_printer_choice:
                test_constraints = self._apply_specimen_printer_choice_to_spec(test_constraints, inline_printer_choice)
            assistant_entry = {
                "role": "orchestrator",
                "content": (
                    f"{response.text.strip()}\n\n"
                    "적용할 테스트 실험값:\n"
                    "```json\n"
                    f"{json.dumps(test_constraints, ensure_ascii=False, indent=2)}\n"
                    "```"
                ),
                "reasoning": self._extract_reasoning(response.raw),
                "token_usage": self._extract_token_usage(response.raw),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": response.model,
                "ok": True,
            }
            await self._append_planning_message(
                assistant_entry,
                level="INFO",
                message=response_message,
            )
            if inline_printer_choice:
                return await self._start_planning_handoff_background(goal=test_goal, constraints=test_constraints)
            return await self._handoff_planning_to_design(goal=test_goal, constraints=test_constraints)
        except Exception as exc:
            assistant_entry = {
                "role": "orchestrator",
                "content": (
                    "테스트 모드 실험값 생성에 실패했습니다. NemoClaw/Ollama 연결과 모델 상태를 확인하세요.\n"
                    f"error={exc.__class__.__name__}: {exc}"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": None,
                "ok": False,
            }
            await self._append_planning_message(
                assistant_entry,
                level="ERROR",
                message="Live GUI test-mode orchestration failed.",
            )
            return {"ok": False, "message": "Live GUI test-mode orchestration failed.", "session": self.planning_snapshot()}

    def _planning_handoff_active(self) -> bool:
        task = self._planning_handoff_task
        return bool(task and not task.done())

    async def _start_planning_handoff_background(self, *, goal: str | None, constraints: dict[str, Any]) -> dict[str, Any]:
        """Return the Live GUI request before the full test/live planning loop blocks fetch."""
        if self._planning_handoff_active():
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": "이미 실행 중인 Live GUI workflow가 있습니다. 현재 작업이 끝난 뒤 다음 요청을 보내세요.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": False,
                },
                event_type="planning_handoff",
                level="WARNING",
                message="Planning handoff already active.",
            )
            return {"ok": False, "message": "Planning handoff already active.", "session": self.planning_snapshot()}

        printer_path = str(constraints.get("printer_test_path") or constraints.get("test_printer_path") or "").strip()
        if printer_path == "physical_print":
            background_content = "테스트 모드 실제 출력 workflow를 시작했습니다. 슬라이싱, G-code 업로드, 출력 시작은 시간이 걸릴 수 있어 백그라운드에서 계속 진행하고 이 창에 단계별 결과를 갱신합니다."
            schedule_message = "Physical-print planning handoff scheduled in background."
        elif printer_path == "installed_printer":
            background_content = "테스트 모드 설치 프린터 통신 검증 workflow를 시작했습니다. Specimen Making 이후 Vision, Manipulation, Equipment, Analysis, Knowledge, BO, Guardian까지 백그라운드 closed-loop로 진행하고 단계별 결과를 이 창에 갱신합니다."
            schedule_message = "Installed-printer test planning handoff scheduled in background."
        elif printer_path == "virtual_bridge":
            background_content = "테스트 모드 가상 브릿지 workflow를 시작했습니다. Specimen Making의 virtual 3DP bridge boundary를 통과한 뒤 Vision, Manipulation, Equipment, Analysis, Knowledge, BO, Guardian까지 백그라운드 closed-loop로 진행하고 단계별 결과를 이 창에 갱신합니다."
            schedule_message = "Virtual-bridge test planning handoff scheduled in background."
        else:
            background_content = "Live GUI workflow를 시작했습니다. 전체 agent closed-loop는 백그라운드에서 진행하고 이 창에 단계별 결과를 갱신합니다."
            schedule_message = "Planning handoff scheduled in background."

        await self._append_planning_message(
            {
                "role": "system",
                "content": background_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": True,
            },
            event_type="planning_handoff",
            message=schedule_message,
        )

        async def _runner() -> dict[str, Any]:
            try:
                return await self._handoff_planning_to_design(goal=goal, constraints=constraints)
            except Exception as exc:
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": f"백그라운드 workflow 실행 실패: {exc.__class__.__name__}: {exc}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": False,
                    },
                    event_type="planning_handoff",
                    level="ERROR",
                    message="Background planning handoff failed.",
                )
                return {"ok": False, "message": "Background planning handoff failed.", "session": self.planning_snapshot()}

        task = asyncio.create_task(_runner())
        self._planning_handoff_task = task

        def _clear(done: asyncio.Task[dict[str, Any]]) -> None:
            if self._planning_handoff_task is done:
                self._planning_handoff_task = None
            try:
                done.result()
            except Exception:
                pass

        task.add_done_callback(_clear)
        return {"ok": True, "message": "Planning handoff started in background.", "session": self.planning_snapshot()}

    async def _build_live_orchestrator_prompt(
        self,
        *,
        operator_message: str,
        goal: str,
        constraints: dict[str, Any],
    ) -> str:
        """Build the Live GUI prompt from existing project/runtime guideline context."""
        conversation_memory = self._planning_memory_context(limit=4, max_chars=500)
        state_context = self._planning_state_context()
        return (
            "Live GUI operator conversation for the existing autonomous_researcher runtime.\n"
            "Use this compact project contract as the authoritative instruction basis.\n"
            f"{self._live_runtime_contract_context()}\n"
            "Use the conversation_memory as short-lived session memory; do not assume it persists after this Live GUI session.\n"
            "Do not create new top-level stages. Use the controller intent state machine before keyword fallback.\n"
            "Intent classes are ask_question, revise_goal, set_constraint, approve_plan, start_dry_run, start_live_run, pause, resume, stop, request_status, select_option, operator_note.\n"
            "Treat `실험 수행` as start_live_run only when required design values are complete; otherwise ask for missing values.\n"
            "Do not add runtime-safety disclaimers. Focus on mission contract, missing values, and the next handoff.\n"
            "Do not use LaTeX math notation. Use plain text arrows like '->' for routes.\n"
            "For normal Live GUI execution, `실험 수행` means generate the design and proceed to the selected printer bridge through Specimen Making Agent. The default selected printer bridge is Bambu Lab X2D.\n"
            "For `테스트 모드`, keep printer actions virtual/read-only unless Specimen Making Agent later asks for the printer path and the operator explicitly chooses `실제 출력`.\n"
            "Use validated active-printer defaults unless the operator overrides them. Bambu Lab X2D uses guarded HTTP artifact/SPC Readiness/start gates; Prusa MK4S is explicit profile selection only.\n"
            "Ask for experimental objective, material, specimen size, structure/domain, and any printer/slicer override needed before handoff.\n"
            "If the operator includes `실험 수행` and required design inputs are complete, the controller will hand off to DesignAgent and then continue to the Specimen Making Agent.\n"
            "Respond in concise Korean as the OrchestratorAgent. Use at most 6 short bullets or 140 Korean words.\n\n"
            f"conversation_memory=\n{conversation_memory}\n\n"
            f"state_context={state_context}\n"
            f"goal={goal}\n"
            f"constraints={constraints}\n"
            f"operator_message={operator_message}\n"
            "Required response shape:\n"
            "- Ask for missing experiment-design and live-print inputs.\n"
            "- Summarize the proposed route only once, briefly.\n"
            "- Tell the operator that including `실험 수행` starts DesignAgent -> Specimen Making Agent and, in live mode, the selected printer bridge with SPC Readiness/start gates.\n"
        )

    async def _live_guideline_context(self, *, operator_message: str, goal: str) -> str:
        """Retrieve existing docs context for Live GUI orchestration guidance."""
        query = (
            "orchestrator live gui experiment planning existing runtime stages "
            "DesignAgent printer specimen spec Guardian operator approval "
            f"{goal} {operator_message}"
        )
        retrieved = await self._deps.agent_context.rag.retrieve(query, top_k_local=3)
        chunks = retrieved.get("local_chunks", []) if isinstance(retrieved, dict) else []
        lines = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            source = str(chunk.get("source", "Project_guide"))
            text = str(chunk.get("text", "")).strip()
            if text:
                lines.append(f"[source={source}]\n{text[:1200]}")

        specimen_guideline = self._load_optional_guideline(
            self._deps.run_root.parent / "docs" / "agents" / "specimen_design_existing_runtime_guideline.txt",
            limit=1800,
        )
        if specimen_guideline:
            lines.append(f"[source=docs/agents/specimen_design_existing_runtime_guideline.txt]\n{specimen_guideline}")
        return "\n\n---\n\n".join(lines) if lines else "No guideline context retrieved; follow current runtime state only."

    async def _build_test_mode_orchestrator_prompt(
        self,
        *,
        operator_message: str,
        goal: str,
        constraints: dict[str, Any],
    ) -> str:
        """Build a prompt that asks the orchestrator LLM to choose concrete test-mode values."""
        conversation_memory = self._planning_memory_context(limit=4, max_chars=500)
        state_context = self._planning_state_context()
        return (
            "Live GUI test-mode orchestration request.\n"
            "Use the existing autonomous_researcher runtime contract.\n"
            f"{self._live_runtime_contract_context()}\n"
            "Use conversation_memory as short-lived Live GUI session memory.\n"
            "Choose concrete test experiment values yourself, then prepare the DesignAgent handoff.\n"
            "The default specimen must be an FDM-printable closed-shell gyroid TPMS, not a visual-only thin TPMS surface.\n"
            "Test-mode printer handling first asks Specimen Making Agent for `가상 브릿지`, `설치 프린터`, or `실제 출력`; only `실제 출력` may physically upload/start.\n"
            "If operator_message already contains one of those choices, set constraints.printer_test_path accordingly so Specimen Making Agent can continue without asking again.\n"
            "Do not add runtime-safety disclaimers; focus on generated values and handoff.\n"
            "Do not use LaTeX math notation. Use plain text arrows like '->' for routes.\n"
            f"Runtime pipeline after DesignAgent handoff: {self._active_graph_stage_route_text(Stage.DESIGN, stop_at=Stage.GUARDIAN)}.\n"
            "Respond in concise Korean and include a fenced JSON block at the end with this schema:\n"
            "```json\n"
            "{\n"
            "  \"goal\": \"short concrete test goal\",\n"
            "  \"constraints\": {\n"
            "    \"material\": \"PLA\",\n"
            "    \"geometry_type\": \"gyroid\",\n"
            "    \"preferred_geometry_type\": \"gyroid\",\n"
            "    \"max_specimen_size_mm\": [30, 30, 30],\n"
            "    \"specimen_size_mm\": [30, 30, 30],\n"
            "    \"objective_type\": \"specific_energy_absorption\",\n"
            "    \"objective_direction\": \"maximize\",\n"
            "    \"cell_size_mm\": 10.0,\n"
            "    \"wall_thickness_mm\": 1.2,\n"
            "    \"relative_density\": 0.35,\n"
            "    \"tpms_surface\": \"gyroid\",\n"
            "    \"tpms_thickness\": 0.38,\n"
            "    \"tpms_resolution\": 72,\n"
            "    \"printability_mode\": \"fdm_closed_shell\",\n"
            "    \"fdm_min_wall_thickness_mm\": 1.2,\n"
            "    \"fdm_max_bridge_distance_mm\": 10.0,\n"
            "    \"fdm_max_unsupported_overhang_deg\": 45,\n"
            "    \"fdm_max_gyroid_wall_cell_ratio\": 0.28,\n"
            "    \"expected_mass_g\": 18.0,\n"
            "    \"max_print_time_min\": 120,\n"
            "    \"printer_model\": \"Bambu Lab X2D\",\n"
            "    \"printer_profile\": \"bambulab_x2d_pla_0p4_nozzle\",\n"
            "    \"slicer_profile_hint\": \"0.2mm_quality\",\n"
            "    \"nozzle_diameter_mm\": 0.4,\n"
            "    \"layer_height_mm\": 0.2,\n"
            "    \"first_layer_height_mm\": 0.2,\n"
            "    \"slow_first_layer_enabled\": true,\n"
            "    \"first_layer_speed_mm_s\": 10.0,\n"
            "    \"bed_temperature_c\": 60.0,\n"
            "    \"first_layer_bed_temperature_c\": 60.0,\n"
            "    \"storage\": \"ftps\",\n"
            "    \"print\": {\"storage\": \"ftps\", \"start_immediately\": false, \"overwrite\": true}\n"
            "  }\n"
            "}\n"
            "```\n\n"
            f"conversation_memory=\n{conversation_memory}\n\n"
            f"state_context={state_context}\n"
            f"operator_message={operator_message}\n"
            f"default_constraints={constraints}\n"
        )

    def _live_runtime_contract_context(self) -> str:
        """Compact docs-derived contract for Live GUI prompts."""
        route = self._active_graph_stage_route_text(Stage.DESIGN, stop_at=Stage.GUARDIAN)
        return (
            "Project contract: Orchestrator routes existing graph-configured stages only. "
            f"Active graph stage order is {route}. "
            "Design Agent chooses metamaterial parameters; deterministic geometry tools create STL; "
            "Specimen Making Agent owns printer.prepare and printer/ejection preparation. "
            "Validated live printer path uses the selected printer bridge. Default is Bambu Lab X2D -> Bambu slicer artifact -> Bambu MQTT/FTPS/HTTP artifact readiness -> guarded SPC Readiness/start gates. Prusa MK4S remains explicit profile selection only. "
            "Live mode may physically print after `실험 수행`; test modes stay virtual/read-only unless the operator explicitly selects `실제 출력` at the Specimen Making Agent printer-path prompt or sends `테스트 모드, 실제 출력`. "
            "Bambu actual-print autoejection uses native bambu_gcode_patch artifacts; Bambu standalone ejection tests use direct MQTT gcode_line after live gates. Prusa auto ejection uses a gated bed-sweep append G-code path only when Prusa is explicitly selected. "
            "Do not use LaTeX route notation such as $\\rightarrow$; use '->' only."
        )

    def _planning_state_context(self) -> dict[str, Any]:
        """Return a compact state summary instead of the full controller state JSON."""
        spec = self._state.current_experiment_spec if isinstance(self._state.current_experiment_spec, dict) else {}
        return {
            "run_id": self._state.run_id,
            "mode": self._state.mode.value,
            "stage": self._state.stage.value,
            "loop_count": self._state.loop_count,
            "active_goal": self._state.active_goal,
            "current_specimen_id": spec.get("specimen_id"),
            "current_geometry_type": spec.get("geometry_type"),
        }

    def _planning_memory_context(self, *, limit: int = 10, max_chars: int = 1200) -> str:
        """Build compact, session-scoped conversation memory for Live GUI prompts."""
        if not self._planning_messages:
            return "No prior Live GUI messages in this session."
        lines: list[str] = []
        for msg in self._planning_messages[-limit:]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "unknown")).strip() or "unknown"
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            if len(content) > max_chars:
                content = content[:max_chars] + "..."
            model = str(msg.get("model", "")).strip()
            model_part = f" model={model}" if model else ""
            lines.append(f"{role}{model_part}: {content}")
        return "\n\n".join(lines) if lines else "No prior Live GUI messages in this session."

    async def _complete_live_planning_prompt(
        self,
        *,
        prompt: str,
    ):
        """Call the existing orchestrator_plan route for the Live GUI orchestrator chat."""
        timeout_s = self._live_gui_timeout_s()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = await self._deps.agent_context.complete(
                    "orchestrator_plan",
                    prompt,
                    timeout_s=timeout_s,
                )
                suffix = " after retry" if attempt else ""
                return response, f"Live GUI orchestrator_plan call completed{suffix}. model={response.model}"
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    # MTP/NVFP4 serving can JIT a few kernels on the first real generation
                    # after readiness. Retry internally so transient cold-start failures do
                    # not become a visible chat failure before the next operator action.
                    await asyncio.sleep(2.0)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("Live GUI orchestrator_plan call failed without an exception.")

    @staticmethod
    def _extract_token_usage(raw: dict[str, Any]) -> dict[str, int]:
        """Extract token usage from OpenAI/vLLM or Ollama-style responses."""
        if not isinstance(raw, dict):
            return {}

        def as_int(value: Any) -> int:
            try:
                number = int(float(value))
            except (TypeError, ValueError):
                return 0
            return number if number >= 0 else 0

        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        prompt_tokens = as_int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or raw.get("prompt_eval_count")
            or raw.get("prompt_tokens")
            or raw.get("input_tokens")
        )
        completion_tokens = as_int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or raw.get("eval_count")
            or raw.get("completion_tokens")
            or raw.get("output_tokens")
        )
        total_tokens = as_int(
            usage.get("total_tokens")
            or raw.get("total_tokens")
            or (prompt_tokens + completion_tokens if prompt_tokens or completion_tokens else 0)
        )
        result = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        return {key: value for key, value in result.items() if value}

    @staticmethod
    def _extract_reasoning(raw: dict[str, Any]) -> str:
        """Extract model reasoning text from OpenAI/vLLM or Ollama-style responses."""
        if not isinstance(raw, dict):
            return ""
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    for key in ("reasoning", "reasoning_content", "thinking"):
                        value = str(message.get(key, "")).strip()
                        if value and value.lower() != "none":
                            return value
                    # Fallback for Gemma-style channel output when parser output is absent.
                    content = str(message.get("content", ""))
                    match = re.search(r"<\|channel\>\s*thought\s*(.*?)<channel\|>", content, flags=re.DOTALL)
                    if match:
                        return match.group(1).strip()
        message = raw.get("message")
        if isinstance(message, dict):
            for key in ("thinking", "reasoning", "reasoning_content"):
                value = str(message.get(key, "")).strip()
                if value:
                    return value
        for key in ("thinking", "reasoning", "reasoning_content"):
            value = str(raw.get(key, "")).strip()
            if value:
                return value
        return ""

    def _live_gui_timeout_s(self) -> float:
        """Resolve Live GUI orchestrator route timeout."""
        timeout_s = float(os.getenv(
            "AUTONOMOUS_PLANNING_PRIMARY_TIMEOUT_S",
            str(self._deps.system_config.get("planning_primary_timeout_seconds", 240)),
        ))
        return max(30.0, timeout_s)

    @staticmethod
    def _load_optional_guideline(path: Path, *, limit: int) -> str:
        """Read a local guideline snippet when available."""
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()[:limit]

    def _should_trigger_design(self, message: str) -> bool:
        """Detect operator intent to move from orchestration discussion into design generation."""
        intent = normalize_operator_intent(message)
        return bool(intent.get("requires_design_handoff") and intent.get("intent") == "start_live_run")

    @staticmethod
    def _is_generic_planning_goal(value: Any) -> bool:
        """Return whether a goal is a GUI/bootstrap placeholder rather than operator input."""
        text = str(value or "").strip().lower()
        if not text:
            return True
        generic_fragments = (
            "build autonomous",
            "terminal live gui session",
            "design and validate a live-mode specimen plan",
            "autonomous ai researcher",
        )
        return any(fragment in text for fragment in generic_fragments)

    @staticmethod
    def _clean_design_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
        """Keep only concrete experiment-design values, not GUI transport metadata."""
        ignored = {"runtime_contract", "require_operator_approval"}
        cleaned: dict[str, Any] = {}
        for key, value in (constraints or {}).items():
            if key in ignored or value in (None, "", []):
                continue
            cleaned[key] = value
        return cleaned

    @staticmethod
    def _coerce_size_vector(value: Any) -> list[float] | None:
        """Normalize a 3D size vector when present."""
        if isinstance(value, (list, tuple)) and len(value) == 3:
            try:
                parsed = [float(item) for item in value]
            except (TypeError, ValueError):
                return None
            if all(item > 0 for item in parsed):
                return parsed
        return None

    @staticmethod
    def _extract_size_from_text(text: str) -> list[float] | None:
        """Extract dimensions like 30 x 30 x 30 mm from operator text."""
        pattern = (
            r"(\d+(?:\.\d+)?)\s*(?:mm|밀리|미리)?\s*"
            r"(?:x|×|\*)\s*"
            r"(\d+(?:\.\d+)?)\s*(?:mm|밀리|미리)?\s*"
            r"(?:x|×|\*)\s*"
            r"(\d+(?:\.\d+)?)\s*(?:mm|밀리|미리)?"
        )
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            return None
        return [float(match.group(idx)) for idx in range(1, 4)]

    @staticmethod
    def _extract_material_from_text(text: str) -> str:
        """Extract common 3DP material names from operator text."""
        upper = text.upper()
        for material in ("PLA", "PETG", "TPU", "ABS", "ASA", "PA", "NYLON", "RESIN"):
            if re.search(rf"(?<![A-Z0-9]){re.escape(material)}(?![A-Z0-9])", upper):
                return "Nylon" if material in {"PA", "NYLON"} else material
        if "나일론" in text:
            return "Nylon"
        if "레진" in text:
            return "resin"
        return ""

    @classmethod
    def _extract_geometry_or_domain_from_text(cls, text: str) -> dict[str, str]:
        """Extract supported geometry or broader lattice domain hints."""
        lowered = text.lower()
        normalized = lowered.replace("-", "_").replace(" ", "_")
        result: dict[str, str] = {}
        geometry_keywords = {
            "gyroid": (
                "gyroid",
                "tpms",
                "tpms_gyroid",
                "gyroid_tpms",
                "metamaterial",
                "bending_dominated",
                "bending-dominated",
                "자이로이드",
                "메타물질",
                "굽힘",
                "벤딩",
            ),
            "auxetic_reentrant": ("auxetic", "reentrant", "re_entrant", "re-entrant", "오제틱"),
            "lattice_octet": ("octet", "옥텟"),
            "lattice_bcc": ("bcc", "body_centered", "body-centered"),
            "lattice_fcc": ("fcc",),
            "honeycomb": ("honeycomb", "허니컴"),
            "random_voronoi": ("voronoi", "보로노이"),
        }
        for geometry, keywords in geometry_keywords.items():
            if any(keyword in lowered or keyword in normalized for keyword in keywords):
                result["geometry_type"] = geometry
                result["preferred_geometry_type"] = geometry
                break
        if "bending" in lowered or "굽힘" in text or "벤딩" in text:
            result["experiment_domain"] = "bending_dominated_lattice"
        elif "lattice" in lowered or "격자" in text:
            result["experiment_domain"] = "lattice"
        elif result.get("geometry_type"):
            result["experiment_domain"] = result["geometry_type"]
        return result

    @staticmethod
    def _extract_objective_from_text(text: str) -> tuple[str, str]:
        """Extract objective type/direction from compact operator text."""
        lowered = text.lower()
        objective = ""
        direction = "maximize"
        if any(token in lowered for token in ("energy absorption", "specific energy", "sea", "에너지 흡수", "흡수량")):
            objective = "specific_energy_absorption"
        elif any(token in lowered for token in ("stiffness", "강성")):
            objective = "stiffness"
        elif any(token in lowered for token in ("mass", "질량", "무게")):
            objective = "mass"
        elif any(token in lowered for token in ("strength", "강도")):
            objective = "strength"
        if any(token in lowered for token in ("minimize", "minimum", "최소화", "줄이")):
            direction = "minimize"
        if any(token in lowered for token in ("maximize", "maximum", "최대화", "높이", "늘리")):
            direction = "maximize"
        return objective, direction

    def _extract_design_values_from_text(self, text: str) -> dict[str, Any]:
        """Extract concrete design values from one operator message."""
        values: dict[str, Any] = {}
        size = self._extract_size_from_text(text)
        if size:
            values["specimen_size_mm"] = size
            values["max_specimen_size_mm"] = size
        material = self._extract_material_from_text(text)
        if material:
            values["material"] = material
        values.update(self._extract_geometry_or_domain_from_text(text))
        objective, direction = self._extract_objective_from_text(text)
        if objective:
            values["objective_type"] = objective
            values["objective_direction"] = direction
        if re.search(r"\bprusa\s*mk4s?\b", text, flags=re.IGNORECASE):
            values["printer_model"] = "Prusa MK4S"
            values["printer_profile_id"] = "prusa_mk4s_lab_01"
            values["printer_profile"] = "prusa_mk4s_pla_0p4_nozzle"
            values["storage"] = "usb"
            values.setdefault("print", {"storage": "usb", "start_immediately": False, "overwrite": True})
        elif re.search(r"\bprusa\s*mk3s?\b", text, flags=re.IGNORECASE):
            values["printer_model"] = "Prusa MK3S"
            values["storage"] = "usb"
        elif re.search(r"\bbambu(?:\\s*lab)?\\s*x2d\b|\bx2d\b", text, flags=re.IGNORECASE):
            values["printer_model"] = "Bambu Lab X2D"
            values["printer_profile_id"] = "bambulab_x2d_lab_01"
            values["printer_profile"] = "bambulab_x2d_pla_0p4_nozzle"
            values["storage"] = "ftps"
            values.setdefault("print", {"storage": "ftps", "start_immediately": False, "overwrite": True})
        nozzle = re.search(r"(?:nozzle|노즐)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*mm", text, flags=re.IGNORECASE)
        if nozzle:
            values["nozzle_diameter_mm"] = float(nozzle.group(1))
        layer = re.search(r"(?:layer|레이어)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*mm", text, flags=re.IGNORECASE)
        if layer:
            values["layer_height_mm"] = float(layer.group(1))
        first_layer_height = re.search(
            r"(?:first\s*layer\s*height|첫\s*레이어\s*높이|초층\s*높이)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*mm",
            text,
            flags=re.IGNORECASE,
        )
        if first_layer_height:
            values["first_layer_height_mm"] = float(first_layer_height.group(1))
        first_layer_speed = re.search(
            r"(?:first\s*layer\s*speed|첫\s*레이어\s*속도|초층\s*속도)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:mm/s|mm\/s)?",
            text,
            flags=re.IGNORECASE,
        )
        if first_layer_speed:
            values["first_layer_speed_mm_s"] = float(first_layer_speed.group(1))
        bed_temp = re.search(
            r"(?:bed\s*(?:temperature|temp)|베드\s*온도)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:c|°c|도)?",
            text,
            flags=re.IGNORECASE,
        )
        if bed_temp:
            values["bed_temperature_c"] = float(bed_temp.group(1))
        first_layer_bed_temp = re.search(
            r"(?:first\s*layer\s*bed\s*(?:temperature|temp)|첫\s*레이어\s*베드\s*온도|초층\s*베드\s*온도)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:c|°c|도)?",
            text,
            flags=re.IGNORECASE,
        )
        if first_layer_bed_temp:
            values["first_layer_bed_temperature_c"] = float(first_layer_bed_temp.group(1))
        max_time = re.search(r"(?:max(?:imum)?\s*print\s*time|최대\s*출력\s*시간|출력\s*시간)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:min|분)?", text, flags=re.IGNORECASE)
        if max_time:
            values["max_print_time_min"] = float(max_time.group(1))
        if any(token in text.lower() for token in ("usb", "유에스비")):
            values["storage"] = "usb"
        lowered = text.lower()
        compact = re.sub(r"\s+", "", lowered)
        if any(token in compact for token in ("스커트켜", "skirton", "brimon", "rafton")):
            values["skirt_enabled"] = True
        if any(token in compact for token in ("스커트꺼", "스커트없이", "skirtoff", "brimoff", "raftoff", "noskirt")):
            values["skirt_enabled"] = False
        explicit_top_cap = False
        explicit_bottom_cap = False
        if any(token in compact for token in ("상단캡켜", "상부캡켜", "topcapon", "topcapson")):
            values["top_cap_enabled"] = True
            explicit_top_cap = True
        if any(token in compact for token in ("상단캡꺼", "상단캡없이", "상부캡꺼", "topcapoff", "notopcap")):
            values["top_cap_enabled"] = False
            explicit_top_cap = True
        if any(token in compact for token in ("하단캡켜", "하부캡켜", "bottomcapon", "bottomcapson")):
            values["bottom_cap_enabled"] = True
            explicit_bottom_cap = True
        if any(token in compact for token in ("하단캡꺼", "하단캡없이", "하부캡꺼", "bottomcapoff", "nobottomcap")):
            values["bottom_cap_enabled"] = False
            explicit_bottom_cap = True
        if any(token in compact for token in ("평판켜", "캡켜", "flatcapon", "capson")) and not (explicit_top_cap or explicit_bottom_cap):
            values["top_cap_enabled"] = False
            values["bottom_cap_enabled"] = True
            values["top_bottom_cap"] = True
            values["require_flat_compression_faces"] = False
            if "skin_thickness_mm" not in values:
                values["skin_thickness_mm"] = 0.8
        if explicit_top_cap or explicit_bottom_cap:
            top_cap = bool(values.get("top_cap_enabled", False))
            bottom_cap = bool(values.get("bottom_cap_enabled", True))
            values["top_bottom_cap"] = bool(top_cap or bottom_cap)
            values["require_flat_compression_faces"] = bool(top_cap and bottom_cap)
            if values["top_bottom_cap"] and "skin_thickness_mm" not in values:
                values["skin_thickness_mm"] = 0.8
        if any(token in compact for token in ("평판꺼", "평판없이", "캡꺼", "캡없이", "flatcapoff", "nocap")) and not (
            explicit_top_cap or explicit_bottom_cap
        ):
            values["top_cap_enabled"] = False
            values["bottom_cap_enabled"] = False
            values["top_bottom_cap"] = False
            values["require_flat_compression_faces"] = False
            values["skin_thickness_mm"] = 0.0
        if any(token in text for token in ("실제 출력", "실제 프린트", "출력까지", "프린트까지")):
            values["physical_print_intent"] = True
        return values

    @staticmethod
    def _validated_printer_defaults() -> dict[str, Any]:
        """Return operator-controlled print defaults adapted to the active printer profile."""
        profile = load_prusa_print_profile()
        try:
            manager = PrinterDeviceBridgeManager.from_devices_config(load_all_configs(resolve_path("configs")))
            selected_profile, _reason = manager.fleet_selection()
            profile = adapt_print_profile_for_provider(profile, selected_profile.provider)
        except Exception:
            # Keep Live GUI usable even if the optional fleet config cannot be read.
            pass
        allowed = (
            "material",
            "printer_model",
            "printer_profile",
            "slicer_profile_hint",
            "nozzle_diameter_mm",
            "layer_height_mm",
            "first_layer_height_mm",
            "slow_first_layer_enabled",
            "first_layer_speed_mm_s",
            "bed_temperature_c",
            "first_layer_bed_temperature_c",
            "storage",
            "max_print_time_min",
            "overwrite",
            "start_immediately_live",
            "allow_ejection",
            "skirt_enabled",
            "top_cap_enabled",
            "bottom_cap_enabled",
            "top_bottom_cap",
            "skin_thickness_mm",
            "require_flat_compression_faces",
            "test_specimen_size_mm",
            "test_unit_cell_size_mm",
        )
        return {key: profile[key] for key in allowed if key in profile}

    def _with_validated_printer_defaults(self, constraints: dict[str, Any]) -> dict[str, Any]:
        """Apply validated printer defaults while preserving operator overrides."""
        merged = dict(self._validated_printer_defaults())
        merged.update({key: value for key, value in constraints.items() if value not in (None, "", [])})
        return merged

    def _planning_design_handoff_readiness(self, *, goal: str | None, constraints: dict[str, Any]) -> dict[str, Any]:
        """Collect current Live GUI design inputs and decide whether handoff can proceed."""
        merged_constraints: dict[str, Any] = {}
        detected_goal = "" if self._is_generic_planning_goal(goal) else str(goal or "").strip()

        history_page = self.planning_messages_page(limit=PLANNING_TRANSCRIPT_MAX_PAGE_LIMIT)
        history_entries = list(history_page.get("messages", []))
        seen_history_keys = {
            str(entry.get("message_id") or entry.get("transcript_index") or id(entry))
            for entry in history_entries
            if isinstance(entry, dict)
        }
        for entry in self._planning_messages[-PLANNING_TRANSCRIPT_MAX_PAGE_LIMIT:]:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("message_id") or entry.get("transcript_index") or id(entry))
            if key in seen_history_keys:
                continue
            history_entries.append(entry)
            seen_history_keys.add(key)
        for entry in history_entries:
            if not isinstance(entry, dict) or entry.get("role") != "operator":
                continue
            entry_constraints = entry.get("constraints") if isinstance(entry.get("constraints"), dict) else {}
            merged_constraints.update(self._clean_design_constraints(entry_constraints))
            content = str(entry.get("content", ""))
            extracted = self._extract_design_values_from_text(content)
            merged_constraints.update({key: value for key, value in extracted.items() if value not in (None, "", [])})
            if not detected_goal and not self._should_trigger_design(content):
                maybe_objective, _ = self._extract_objective_from_text(content)
                if maybe_objective or any(token in content for token in ("실험", "시편", "압축", "compression")):
                    detected_goal = content.strip()

        merged_constraints.update(self._clean_design_constraints(constraints))
        merged_constraints = self._with_validated_printer_defaults(merged_constraints)
        if not detected_goal and not self._is_generic_planning_goal(self._state.active_goal):
            detected_goal = self._state.active_goal

        size = self._coerce_size_vector(
            merged_constraints.get("specimen_size_mm") or merged_constraints.get("max_specimen_size_mm")
        )
        if size:
            merged_constraints["specimen_size_mm"] = size
            merged_constraints["max_specimen_size_mm"] = size

        has_goal = bool(detected_goal)
        has_material = bool(str(merged_constraints.get("material", "")).strip())
        has_size = bool(size)
        has_domain = bool(
            str(merged_constraints.get("geometry_type", "")).strip()
            or str(merged_constraints.get("preferred_geometry_type", "")).strip()
            or str(merged_constraints.get("experiment_domain", "")).strip()
        )

        missing: list[dict[str, str]] = []
        if not has_goal:
            missing.append(
                {
                    "field": "실험 목표/평가지표",
                    "key": "objective",
                    "example": "예: 압축 시편의 specific energy absorption을 최대화",
                }
            )
        if not has_material:
            missing.append({"field": "재료", "key": "material", "example": "예: PLA 또는 PETG"})
        if not has_size:
            missing.append({"field": "시편 크기", "key": "specimen_size_mm", "example": "예: 30 x 30 x 30 mm"})
        if not has_domain:
            missing.append(
                {
                    "field": "구조/실험 domain",
                    "key": "geometry_or_domain",
                    "example": "예: TPMS gyroid, gyroid metamaterial, BCC lattice",
                }
            )
        return {"goal": detected_goal, "constraints": merged_constraints, "missing": missing}

    def _format_design_readiness_message(self, readiness: dict[str, Any]) -> str:
        """Describe current and missing values before DesignAgent handoff."""
        constraints = readiness.get("constraints", {}) if isinstance(readiness.get("constraints"), dict) else {}
        goal = str(readiness.get("goal") or "").strip()

        def value_or_missing(value: Any) -> str:
            if value in (None, "", []):
                return "미입력"
            if isinstance(value, list):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        current_rows = [
            ("실험 목표/평가지표", goal),
            ("재료", constraints.get("material")),
            ("시편 크기 mm", constraints.get("specimen_size_mm") or constraints.get("max_specimen_size_mm")),
            (
                "구조/domain",
                constraints.get("geometry_type")
                or constraints.get("preferred_geometry_type")
                or constraints.get("experiment_domain"),
            ),
            ("프린터", constraints.get("printer_model")),
            ("노즐/레이어", self._join_optional_values([constraints.get("nozzle_diameter_mm"), constraints.get("layer_height_mm")], " / ")),
            ("첫 레이어 높이", constraints.get("first_layer_height_mm")),
            (
                "첫 레이어 속도 저하",
                f"{constraints.get('first_layer_speed_mm_s')} mm/s" if constraints.get("slow_first_layer_enabled", True) else "미사용",
            ),
            (
                "베드 온도",
                self._join_optional_values(
                    [constraints.get("bed_temperature_c"), constraints.get("first_layer_bed_temperature_c")],
                    " / ",
                ),
            ),
            ("최대 출력시간", constraints.get("max_print_time_min")),
            ("전송/storage", constraints.get("storage")),
            ("스커트/브림/래프트", "사용" if constraints.get("skirt_enabled") else "미사용"),
            (
                "cap/skin",
                (
                    f"bottom={bool(constraints.get('bottom_cap_enabled'))}, "
                    f"top={bool(constraints.get('top_cap_enabled'))}, "
                    f"skin={constraints.get('skin_thickness_mm', 0.0)} mm"
                )
                if constraints.get("top_bottom_cap")
                else "미사용",
            ),
            ("실제 출력", "live mode에서 실험 수행 시 upload/start"),
        ]
        missing = readiness.get("missing", [])
        missing_lines = [
            f"- {item['field']}: {item['example']}"
            for item in missing
            if isinstance(item, dict) and item.get("field")
        ]
        return (
            "아직 Design Agent로 넘기기엔 필수 실험값이 부족합니다. 임의값으로 진행하지 않고, 아래 값을 먼저 확인하겠습니다.\n\n"
            "현재 확인된 값:\n"
            + "\n".join(f"- {label}: {value_or_missing(value)}" for label, value in current_rows)
            + "\n\n"
            "추가로 필요한 값:\n"
            + "\n".join(missing_lines)
            + "\n\n"
            "한 번에 입력하는 예:\n"
            "\"PLA로 30 x 30 x 30 mm TPMS gyroid 압축 시편을 만들고, "
            "specific energy absorption을 최대화. FDM 출력 가능한 closed-shell 구조로 하고, "
            "프린터는 Bambu Lab X2D, nozzle 0.4 mm, layer 0.2 mm, "
            "최대 출력 시간 120분. 실험 수행\""
        )

    @staticmethod
    def _join_optional_values(values: list[Any], sep: str) -> str:
        """Join non-empty values for compact display."""
        clean = [str(value) for value in values if value not in (None, "", [])]
        return sep.join(clean)

    async def _request_missing_design_values(
        self,
        readiness: dict[str, Any],
        *,
        session_id: str | None,
    ) -> dict[str, Any]:
        """Ask the operator for required values instead of fabricating a design."""
        content = self._format_design_readiness_message(readiness)
        await self._append_planning_message(
            {
                "role": "orchestrator",
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "orchestrator_plan",
                "ok": True,
                "requires_design_inputs": True,
                "current_design_inputs": readiness.get("constraints", {}),
                "missing_design_inputs": readiness.get("missing", []),
            },
            event_type="planning_design_inputs_required",
            message="Design handoff blocked until required operator inputs are provided.",
            level="INFO",
        )
        return {
            "ok": True,
            "message": "Design handoff requires operator inputs.",
            "session": self.planning_snapshot(session_id=session_id),
        }

    @staticmethod
    def _should_trigger_test_design(message: str) -> bool:
        """Detect Live GUI shortcut for creating a default test design handoff."""
        normalized = re.sub(r"\s+", "", message.lower())
        if normalized.startswith("test") and MainController._parse_specimen_printer_choice(message):
            return True
        return normalized in {"테스트모드", "testmode", "test"} or "테스트모드" in normalized

    def _default_test_constraints(self, constraints: dict[str, Any]) -> dict[str, Any]:
        """Fill missing Live GUI constraints with deterministic test-mode defaults."""
        printer_defaults = self._validated_printer_defaults()
        test_unit_cell_size_mm = float(printer_defaults.get("test_unit_cell_size_mm", 10.0))
        defaults: dict[str, Any] = {
            "material": printer_defaults.get("material", "PLA"),
            "max_specimen_size_mm": printer_defaults.get("test_specimen_size_mm", [30, 30, 30]),
            "max_print_time_min": printer_defaults.get("max_print_time_min", 120),
            "geometry_type": MainController.TEST_MODE_FIXED_GEOMETRY,
            "preferred_geometry_type": MainController.TEST_MODE_FIXED_GEOMETRY,
            "specimen_size_mm": printer_defaults.get("test_specimen_size_mm", [30, 30, 30]),
            "objective_type": "specific_energy_absorption",
            "objective_direction": "maximize",
            "infill_pattern": MainController.TEST_MODE_FIXED_GEOMETRY,
            "infill_density_percent": 35,
            "layer_height_mm": printer_defaults.get("layer_height_mm", 0.2),
            "first_layer_height_mm": printer_defaults.get("first_layer_height_mm", printer_defaults.get("layer_height_mm", 0.2)),
            "slow_first_layer_enabled": printer_defaults.get("slow_first_layer_enabled", True),
            "first_layer_speed_mm_s": printer_defaults.get("first_layer_speed_mm_s", 10.0),
            "bed_temperature_c": printer_defaults.get("bed_temperature_c", 60.0),
            "first_layer_bed_temperature_c": printer_defaults.get("first_layer_bed_temperature_c", 60.0),
            "wall_thickness_mm": 1.2,
            "cell_size_mm": test_unit_cell_size_mm,
            "relative_density": 0.32,
            "skin_thickness_mm": printer_defaults.get("skin_thickness_mm", 0.8),
            "top_cap_enabled": printer_defaults.get("top_cap_enabled", False),
            "bottom_cap_enabled": printer_defaults.get("bottom_cap_enabled", True),
            "top_bottom_cap": printer_defaults.get("top_bottom_cap", True),
            "skirt_enabled": printer_defaults.get("skirt_enabled", False),
            "tpms_surface": "gyroid",
            "tpms_thickness": 0.38,
            "tpms_resolution": 72,
            "printability_mode": "fdm_closed_shell",
            "require_flat_compression_faces": printer_defaults.get("require_flat_compression_faces", False),
            "fdm_min_wall_thickness_mm": 1.2,
            "fdm_max_bridge_distance_mm": min(test_unit_cell_size_mm, 10.0),
            "fdm_max_unsupported_overhang_deg": 45.0,
            "fdm_max_gyroid_wall_cell_ratio": 0.28,
            "printer_model": printer_defaults.get("printer_model", "Bambu Lab X2D"),
            "printer_profile": printer_defaults.get("printer_profile", "bambulab_x2d_pla_0p4_nozzle"),
            "slicer_profile_hint": printer_defaults.get("slicer_profile_hint", "0.2mm_quality"),
            "nozzle_diameter_mm": printer_defaults.get("nozzle_diameter_mm", 0.4),
            "storage": printer_defaults.get("storage", "ftps"),
            "print": {
                "storage": printer_defaults.get("storage", "ftps"),
                "start_immediately": False,
                "overwrite": printer_defaults.get("overwrite", True),
                "physical_intent": False,
                "skirt_enabled": printer_defaults.get("skirt_enabled", False),
            },
            "ejection": {"enabled": bool(printer_defaults.get("allow_ejection", False))},
            "test_mode_autofill": True,
        }
        merged = dict(defaults)
        merged.update({key: value for key, value in constraints.items() if value not in (None, "", [])})
        geometry = MainController._normalize_planning_geometry_type(merged.get("geometry_type")) or MainController.TEST_MODE_FIXED_GEOMETRY
        merged["geometry_type"] = geometry
        merged["preferred_geometry_type"] = MainController._normalize_planning_geometry_type(
            merged.get("preferred_geometry_type") or geometry
        ) or geometry
        return merged

    @staticmethod
    def _extract_test_mode_payload(text: str) -> dict[str, Any]:
        """Parse the orchestrator's test-mode JSON block when available."""
        matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        candidates = matches or re.findall(r"(\{.*\})", text, flags=re.DOTALL)
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    @staticmethod
    def _normalize_test_mode_constraints(defaults: dict[str, Any], llm_constraints: dict[str, Any]) -> dict[str, Any]:
        """Merge LLM-selected test values with safe defaults and normalize equivalent size keys."""
        merged = dict(defaults)
        merged.update({key: value for key, value in llm_constraints.items() if value not in (None, "", [])})
        if "specimen_size_mm" in merged and "max_specimen_size_mm" not in llm_constraints:
            merged["max_specimen_size_mm"] = merged["specimen_size_mm"]
        if "max_specimen_size_mm" in merged and "specimen_size_mm" not in llm_constraints:
            merged["specimen_size_mm"] = merged["max_specimen_size_mm"]
        forced_geometry = MainController.TEST_MODE_FIXED_GEOMETRY
        merged["geometry_type"] = forced_geometry
        merged["preferred_geometry_type"] = forced_geometry
        merged["infill_pattern"] = forced_geometry
        merged["tpms_surface"] = "gyroid"
        merged["cell_size_mm"] = float(defaults.get("cell_size_mm", merged.get("cell_size_mm", 10.0)))
        merged["tpms_thickness"] = merged.get("tpms_thickness", 0.38)
        merged["tpms_resolution"] = merged.get("tpms_resolution", 72)
        merged["printability_mode"] = "fdm_closed_shell"
        explicit_top_cap = "top_cap_enabled" in llm_constraints
        explicit_bottom_cap = "bottom_cap_enabled" in llm_constraints
        explicit_legacy_cap = "top_bottom_cap" in llm_constraints
        if explicit_top_cap or explicit_bottom_cap:
            merged["top_cap_enabled"] = bool(merged.get("top_cap_enabled", defaults.get("top_cap_enabled", False)))
            merged["bottom_cap_enabled"] = bool(merged.get("bottom_cap_enabled", defaults.get("bottom_cap_enabled", True)))
        elif explicit_legacy_cap:
            legacy_cap = bool(merged.get("top_bottom_cap", defaults.get("top_bottom_cap", True)))
            merged["top_cap_enabled"] = False
            merged["bottom_cap_enabled"] = legacy_cap
        else:
            merged["top_cap_enabled"] = bool(defaults.get("top_cap_enabled", False))
            merged["bottom_cap_enabled"] = bool(defaults.get("bottom_cap_enabled", True))
        merged["top_bottom_cap"] = bool(merged["top_cap_enabled"] or merged["bottom_cap_enabled"])
        if merged["top_bottom_cap"]:
            merged["skin_thickness_mm"] = max(
                0.2,
                float(merged.get("skin_thickness_mm", defaults.get("skin_thickness_mm", 0.8)) or 0.8),
            )
            merged["require_flat_compression_faces"] = bool(
                merged.get("require_flat_compression_faces", defaults.get("require_flat_compression_faces", False))
                and merged["top_cap_enabled"]
                and merged["bottom_cap_enabled"]
            )
        else:
            merged["skin_thickness_mm"] = 0.0
            merged["require_flat_compression_faces"] = False
        merged["fdm_min_wall_thickness_mm"] = merged.get("fdm_min_wall_thickness_mm", 1.2)
        merged["fdm_max_bridge_distance_mm"] = merged.get("fdm_max_bridge_distance_mm", 10.0)
        merged["fdm_max_unsupported_overhang_deg"] = merged.get("fdm_max_unsupported_overhang_deg", 45.0)
        merged["fdm_max_gyroid_wall_cell_ratio"] = merged.get("fdm_max_gyroid_wall_cell_ratio", 0.28)
        merged["print"] = {
            **{"storage": "usb", "start_immediately": False, "overwrite": True, "physical_intent": False},
            **(merged.get("print") if isinstance(merged.get("print"), dict) else {}),
            "start_immediately": False,
            "physical_intent": False,
            "skirt_enabled": bool(merged.get("skirt_enabled", defaults.get("skirt_enabled", False))),
        }
        default_ejection = defaults.get("ejection") if isinstance(defaults.get("ejection"), dict) else {}
        requested_ejection = merged.get("ejection") if isinstance(merged.get("ejection"), dict) else {}
        merged["ejection"] = {
            **default_ejection,
            **requested_ejection,
            "enabled": bool(requested_ejection.get("enabled", default_ejection.get("enabled", False))),
        }
        merged["test_mode_llm_generated"] = True
        return merged

    @staticmethod
    def _normalize_planning_geometry_type(value: Any) -> str:
        """Normalize legacy Live GUI geometry names into supported specimen-design names."""
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "lattice": "gyroid",
            "tpms": "gyroid",
            "tpms_gyroid": "gyroid",
            "gyroid_tpms": "gyroid",
            "metamaterial": "gyroid",
            "bending_dominated": "gyroid",
            "bending_dominated_lattice": "gyroid",
            "bcc": "lattice_bcc",
            "fcc": "lattice_fcc",
            "octet": "lattice_octet",
            "octet_lattice": "lattice_octet",
            "compression_cube": "gyroid",
            "cube": "gyroid",
        }
        normalized = aliases.get(text, normalize_tpms_geometry_type(text))
        supported = {
            "lattice_bcc",
            "lattice_fcc",
            "lattice_octet",
            "gyroid",
            "honeycomb",
            "auxetic_reentrant",
            "random_voronoi",
        }
        return normalized if normalized in supported else ""

    def _planning_cycle_limit(self, payload: dict[str, Any]) -> int:
        """Return planned Live GUI cycle count for test-mode handoffs."""
        return self.TEST_MODE_LOOP_CYCLES if self._is_planning_test_spec(payload) else 1

    def _reset_planning_workflow_controls(self) -> None:
        """Clear stale operator-control flags before a newly requested Live GUI workflow."""
        self._state.safe_stop_requested = False
        self._state.stop_requested = False
        self._state.is_paused = False
        self._state.run_metadata["_planning_workflow_controls_reset"] = True

    def _design_constraints_for_cycle(self, base_constraints: dict[str, Any]) -> dict[str, Any]:
        """Merge BO recommendation into DesignAgent constraints for the next cycle."""
        constraints = dict(base_constraints)
        bo_update = self._state.run_metadata.get("bo_recommended_constraints")
        if isinstance(bo_update, dict):
            for key, value in bo_update.items():
                if key == "cell_size_mm":
                    continue
                if value not in (None, "", []):
                    constraints[key] = value
            geometry = self._normalize_planning_geometry_type(
                bo_update.get("geometry_type") or bo_update.get("preferred_geometry_type")
            )
            if geometry:
                constraints["geometry_type"] = geometry
                constraints["preferred_geometry_type"] = geometry
        geometry = self._normalize_planning_geometry_type(
            constraints.get("geometry_type") or constraints.get("preferred_geometry_type")
        )
        if geometry == "gyroid":
            try:
                density = float(constraints.get("relative_density", 0.32))
            except (TypeError, ValueError):
                density = 0.32
            constraints["relative_density"] = max(0.20, density)
        return constraints

    @classmethod
    def _closed_loop_static_design_constraints(cls, constraints: dict[str, Any]) -> dict[str, Any]:
        """Keep operator/static settings while freeing shape variables for BO/design updates."""

        def clean_mapping(source: dict[str, Any]) -> dict[str, Any]:
            cleaned: dict[str, Any] = {}
            for key, value in source.items():
                if key in cls.CLOSED_LOOP_FREE_SHAPE_KEYS:
                    continue
                if key == "constraints":
                    continue
                cleaned[key] = value
            nested = source.get("constraints")
            if isinstance(nested, dict):
                nested_clean = {
                    key: value
                    for key, value in nested.items()
                    if key not in cls.CLOSED_LOOP_FREE_SHAPE_KEYS and key != "constraints"
                }
                if nested_clean:
                    cleaned["constraints"] = nested_clean
            return cleaned

        return clean_mapping(constraints if isinstance(constraints, dict) else {})

    @staticmethod
    def _design_reference_spec(previous_spec: dict[str, Any] | None, next_spec: dict[str, Any]) -> dict[str, Any]:
        """Return a previous-shape reference so each test cycle can display two shapes."""
        if isinstance(previous_spec, dict) and previous_spec.get("specimen_id"):
            return dict(previous_spec)
        reference = dict(next_spec)
        candidate_id = str(next_spec.get("candidate_id", "candidate"))
        reference["candidate_id"] = f"baseline-before-{candidate_id}"
        reference["specimen_id"] = f"specimen-baseline-before-{candidate_id}"
        reference["generation_strategy"] = "baseline_reference_before_first_test_cycle"
        return reference

    def _artifact_pair_payload(
        self,
        *,
        previous_spec: dict[str, Any] | None,
        next_spec: dict[str, Any],
        next_artifacts: dict[str, str],
    ) -> dict[str, Any]:
        previous_display = self._design_reference_spec(previous_spec, next_spec)
        previous_artifacts = self._write_planning_artifacts(previous_display)
        return {
            "previous": {
                "label": "Previous shape",
                "experiment_spec": previous_display,
                "artifacts": previous_artifacts,
            },
            "next": {
                "label": "Next shape",
                "experiment_spec": next_spec,
                "artifacts": next_artifacts,
            },
        }

    def _format_design_cycle_message(
        self,
        *,
        experiment_spec: dict[str, Any],
        previous_spec: dict[str, Any] | None,
        cycle_index: int,
        total_cycles: int,
    ) -> str:
        bo_update = self._state.run_metadata.get("bo_recommended_constraints")
        bo_note = json.dumps(bo_update, ensure_ascii=False) if isinstance(bo_update, dict) and bo_update else "n/a"
        if cycle_index <= 1:
            return (
                f"Design Agent가 cycle {cycle_index}/{total_cycles} 첫 후보 시편 설계를 생성했습니다.\n\n"
                "생성된 형상:\n"
                f"- specimen_id: {experiment_spec['specimen_id']}\n"
                f"- geometry_type: {experiment_spec['geometry_type']}\n"
                f"- specimen_size_mm: {experiment_spec['specimen_size_mm']}\n"
                f"- cell_size_mm: {experiment_spec['cell_size_mm']}\n"
                f"- wall_thickness_mm: {experiment_spec['wall_thickness_mm']}\n"
                f"- relative_density: {experiment_spec['relative_density']}\n"
                f"- expected_mass_g: {experiment_spec['expected_mass_g']}\n"
                f"- expected_print_time_min: {experiment_spec['expected_print_time_min']}\n"
                f"- BO recommendation applied: {bo_note}"
            )

        previous_display = self._design_reference_spec(previous_spec, experiment_spec)
        return (
            f"Design Agent가 cycle {cycle_index}/{total_cycles} 후보 시편 설계를 생성했습니다.\n\n"
            "이전 형상:\n"
            f"- specimen_id: {self._runtime_value(previous_display.get('specimen_id'))}\n"
            f"- geometry_type: {self._runtime_value(previous_display.get('geometry_type'))}\n"
            f"- cell_size_mm: {self._runtime_value(previous_display.get('cell_size_mm'))}\n"
            f"- wall_thickness_mm: {self._runtime_value(previous_display.get('wall_thickness_mm'))}\n\n"
            "다음 형상:\n"
            f"- specimen_id: {experiment_spec['specimen_id']}\n"
            f"- geometry_type: {experiment_spec['geometry_type']}\n"
            f"- specimen_size_mm: {experiment_spec['specimen_size_mm']}\n"
            f"- cell_size_mm: {experiment_spec['cell_size_mm']}\n"
            f"- wall_thickness_mm: {experiment_spec['wall_thickness_mm']}\n"
            f"- relative_density: {experiment_spec['relative_density']}\n"
            f"- expected_mass_g: {experiment_spec['expected_mass_g']}\n"
            f"- expected_print_time_min: {experiment_spec['expected_print_time_min']}\n"
            f"- BO recommendation applied: {bo_note}"
        )

    async def _run_planning_langgraph_stage(
        self,
        stage: Stage,
        *,
        emit_runtime_events: bool = True,
        run_orchestrator_before_design: bool = False,
    ) -> None:
        """Execute one Live GUI planning stage through the configured LangGraph runtime."""
        loop = RunLoop(
            state=self._state,
            agent_registry=self._deps.agent_registry,
            orchestrator_agent_name=self._deps.orchestrator_agent_name,
            ctx=self._deps.agent_context,
            logger=self._logger_bundle.logger,
            max_retry_per_stage=int(self._deps.system_config.get("max_retry_per_stage", 2)),
            interval_seconds=0.0,
            on_event=self._broadcast_event if emit_runtime_events else None,
            graph_config_path=self._active_graph_config_path,
            run_orchestrator_before_design=run_orchestrator_before_design,
        )
        self._state.stage = stage
        await loop.step()
        if self._state.is_paused:
            raise RuntimeError(f"Planning LangGraph stage={stage.value} paused for approval.")
        if self._state.stage == Stage.ERROR:
            raise RuntimeError(f"Planning LangGraph stage={stage.value} failed; see runtime events for details.")

    async def _run_planning_design_stage(
        self,
        *,
        previous_spec: dict[str, Any] | None,
        design_constraints: dict[str, Any],
        cycle_index: int,
        total_cycles: int,
        emit_handoff: bool,
    ) -> dict[str, Any]:
        if emit_handoff:
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": f"SYSTEM_EVENT: HANDOFF\nfrom=GuardianAgent\nto=DesignAgent\ncycle={cycle_index}\nstatus=started",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": True,
                },
                event_type="planning_handoff",
                message="Planning handoff to DesignAgent started.",
            )
        effective_constraints = self._design_constraints_for_cycle(design_constraints)
        previous_constraints = previous_spec.get("constraints") if isinstance(previous_spec, dict) and isinstance(previous_spec.get("constraints"), dict) else {}
        self._state.stage = Stage.DESIGN
        self._state.current_experiment_spec = {
            **(previous_spec if isinstance(previous_spec, dict) else {}),
            **{key: value for key, value in effective_constraints.items() if key in {"geometry_type", "specimen_size_mm"}},
            "constraints": {**previous_constraints, **effective_constraints},
        }
        await self._run_planning_langgraph_stage(
            Stage.DESIGN,
            run_orchestrator_before_design=False,
        )
        design_stage_payload = self._state.run_metadata.get("design_agent_payload")
        if not isinstance(design_stage_payload, dict):
            last_stage_payload = self._state.run_metadata.get("last_stage_payload")
            last_stage_data = last_stage_payload.get("data") if isinstance(last_stage_payload, dict) else {}
            design_stage_payload = last_stage_data if isinstance(last_stage_data, dict) else {}
        base_spec = dict(self._state.current_experiment_spec or {})
        if not base_spec:
            raise RuntimeError("DesignAgent did not return experiment_spec.")
        design_model = base_spec.get("model_note", "design_agent")
        experiment_spec = self._build_planning_spec(base_spec=base_spec, constraints=effective_constraints)
        experiment_spec = self._apply_test_cycle_surface_cap_policy(
            experiment_spec,
            cycle_index=cycle_index,
        )
        self._state.current_experiment_spec = experiment_spec
        design_report = dict(design_stage_payload.get("design_report") or {}) if isinstance(design_stage_payload.get("design_report"), dict) else {}
        if design_report:
            handoff_to_specimen = dict(design_report.get("handoff_to_specimen") or {}) if isinstance(design_report.get("handoff_to_specimen"), dict) else {}
            required = [
                "candidate_id",
                "specimen_id",
                "geometry_type",
                "specimen_size_mm",
                "cell_size_mm",
                "wall_thickness_mm",
                "relative_density",
                "material",
                "printer_profile",
                "slicer_profile_hint",
                "layer_height_mm",
                "expected_mass_g",
                "expected_print_time_min",
            ]
            missing = [field for field in required if experiment_spec.get(field) in (None, "", [])]
            handoff_to_specimen.update({
                "required_fields_present": not missing,
                "missing_required_fields": missing,
                "authoritative_specimen_id": experiment_spec.get("specimen_id"),
                "authoritative_candidate_id": experiment_spec.get("candidate_id"),
            })
            design_report["handoff_to_specimen"] = handoff_to_specimen
            design_report["selected_experiment_spec"] = {key: experiment_spec.get(key) for key in required if key in experiment_spec}
        design_candidate = dict(design_stage_payload.get("design_candidate") or design_stage_payload.get("handoff_packet") or {}) if isinstance(design_stage_payload.get("design_candidate") or design_stage_payload.get("handoff_packet"), dict) else {}
        if design_candidate:
            design_candidate.update({
                "experiment_spec": experiment_spec,
                "candidate_id": experiment_spec.get("candidate_id"),
                "specimen_id": experiment_spec.get("specimen_id"),
                "status": "ready" if not (design_report.get("handoff_to_specimen", {}) or {}).get("missing_required_fields") else "blocked",
            })
        merge_payload = {"experiment_spec": experiment_spec}
        if design_report:
            merge_payload["design_report"] = design_report
        if design_candidate:
            merge_payload["design_candidate"] = design_candidate
            merge_payload["handoff_packet"] = design_candidate
        for key in ("candidate_ledger", "decisions", "metrics"):
            if key in design_stage_payload:
                merge_payload[key] = design_stage_payload[key]
        self._merge_planning_agent_data(Stage.DESIGN, merge_payload)
        await self._record_planning_orchestrator_transition(
            from_stage=Stage.DESIGN,
            to_stage=Stage.SPECIMEN,
            payload=merge_payload,
        )
        await self._record_planning_orchestrator_followup(
            stage=Stage.DESIGN,
            trigger="post_stage",
            payload=merge_payload,
            next_stage=Stage.SPECIMEN,
        )
        artifact = self._write_planning_artifacts(experiment_spec)
        message_payload: dict[str, Any] = {
            "role": "design_ai",
            "content": self._format_design_cycle_message(
                experiment_spec=experiment_spec,
                previous_spec=previous_spec,
                cycle_index=cycle_index,
                total_cycles=total_cycles,
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": design_model,
            "ok": True,
            "cycle_index": cycle_index,
            "total_cycles": total_cycles,
            "experiment_spec": experiment_spec,
            "artifacts": artifact,
        }
        if design_report:
            message_payload["design_report"] = design_report
        if design_candidate:
            message_payload["design_candidate"] = design_candidate
        if cycle_index > 1:
            message_payload["artifact_pair"] = self._artifact_pair_payload(
                previous_spec=previous_spec,
                next_spec=experiment_spec,
                next_artifacts=artifact,
            )
        await self._append_planning_message(
            message_payload,
            event_type="planning_design_result",
            message="DesignAgent generated planning artifacts.",
        )
        return experiment_spec

    async def _run_planning_specimen_stage(self, experiment_spec: dict[str, Any], *, emit_handoff: bool = True) -> dict[str, Any]:
        if emit_handoff:
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": "SYSTEM_EVENT: HANDOFF\nfrom=DesignAgent\nto=SpecimenMakingAgent\nstatus=started",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": True,
                },
                event_type="planning_handoff",
                message="Planning handoff to Specimen Making Agent started.",
            )
        remembered_printer_choice = str(self._state.run_metadata.get("last_specimen_printer_choice") or "").strip()
        if remembered_printer_choice and not self._specimen_printer_path(experiment_spec):
            experiment_spec = self._apply_specimen_printer_choice_to_spec(dict(experiment_spec), remembered_printer_choice)
            experiment_spec.setdefault("test_mode_autofill", True)
            experiment_spec.setdefault("test_mode_llm_generated", True)

        self._state.stage = Stage.SPECIMEN
        self._state.current_experiment_spec = experiment_spec
        await self._run_planning_langgraph_stage(Stage.SPECIMEN)
        specimen_payload = self._state.run_metadata.get("specimen_result", {})
        if not isinstance(specimen_payload, dict):
            raise RuntimeError("SpecimenMakingAgent did not return specimen_result.")
        if specimen_payload.get("requires_operator_input"):
            self._state.stage = Stage.SPECIMEN
            await self._record_pending_specimen_input(specimen_payload)
            await self._record_planning_orchestrator_followup(
                stage=Stage.SPECIMEN,
                trigger="missing_input",
                payload=specimen_payload,
                next_stage=Stage.SPECIMEN,
                level="WARNING",
            )
            return {"pending": True, "specimen": specimen_payload}
        next_stage = self._planning_tail_start_stage() or Stage.COMPLETE
        await self._record_planning_orchestrator_transition(
            from_stage=Stage.SPECIMEN,
            to_stage=next_stage,
            payload=specimen_payload,
        )
        await self._record_planning_orchestrator_followup(
            stage=Stage.SPECIMEN,
            trigger="post_stage",
            payload=specimen_payload,
            next_stage=next_stage,
        )
        specimen_artifacts = self._write_planning_artifacts(experiment_spec, specimen_result=specimen_payload)
        await self._append_planning_message(
            {
                "role": "printer_ai",
                "content": self._format_specimen_runtime_message(experiment_spec, specimen_payload),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "specimen_agent",
                "ok": True,
                "specimen": specimen_payload,
                "specimen_artifacts": specimen_artifacts,
                "render_artifacts": False,
            },
            event_type="planning_specimen_result",
            message="SpecimenMakingAgent completed Specimen Making Agent handoff preparation.",
        )
        return {"pending": False, "specimen": specimen_payload}

    async def _run_planning_cycle_series(
        self,
        *,
        first_spec: dict[str, Any],
        design_constraints: dict[str, Any],
        start_cycle: int = 1,
    ) -> dict[str, Any]:
        if start_cycle <= 1:
            already_reset = bool(self._state.run_metadata.pop("_planning_workflow_controls_reset", False))
            if not already_reset:
                self._reset_planning_workflow_controls()
        total_cycles = self._planning_cycle_limit(first_spec)
        static_design_constraints = self._closed_loop_static_design_constraints(design_constraints)
        current_spec = first_spec
        previous_spec: dict[str, Any] | None = None if start_cycle == 1 else dict(first_spec)
        last_tail: dict[str, Any] = {"ok": True, "decision": "continue", "message": "Planning cycle started."}

        for cycle_index in range(start_cycle, total_cycles + 1):
            if cycle_index > start_cycle:
                current_spec = await self._run_planning_design_stage(
                    previous_spec=previous_spec,
                    design_constraints=static_design_constraints,
                    cycle_index=cycle_index,
                    total_cycles=total_cycles,
                    emit_handoff=True,
                )
                specimen = await self._run_planning_specimen_stage(current_spec)
                if specimen.get("pending"):
                    return {
                        "ok": True,
                        "message": "SpecimenMakingAgent waiting for operator input.",
                        "decision": "pending_operator_input",
                    }

            last_tail = await self._run_planning_loop_tail(
                current_spec,
                cycle_index=cycle_index,
                total_cycles=total_cycles,
            )
            if not bool(last_tail.get("ok", False)):
                return last_tail
            decision = str(last_tail.get("decision", "continue"))
            if decision in {"stop", "error"}:
                return last_tail
            previous_spec = dict(current_spec)

        return last_tail

    async def _handoff_planning_to_design(
        self,
        *,
        goal: str | None,
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        """Call DesignAgent for planning-only candidate generation and emit handoff chat messages."""
        self._reset_planning_workflow_controls()
        self._state.active_goal = goal or self._state.active_goal
        await self._append_planning_message(
            {
                "role": "orchestrator",
                "content": "SYSTEM_EVENT: WORKFLOW_TRIGGER_ACCEPTED\nstatus=started",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "orchestrator_plan",
                "ok": True,
            },
            event_type="planning_message",
            message="Orchestrator approved DesignAgent -> Specimen Making Agent handoff.",
        )
        await self._append_planning_message(
            {
                "role": "system",
                "content": "SYSTEM_EVENT: HANDOFF\nfrom=OrchestratorAgent\nto=DesignAgent\nstatus=started",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": True,
            },
            event_type="planning_handoff",
            message="Planning handoff to DesignAgent started.",
        )
        await self._record_planning_orchestrator_transition(
            from_stage=self._state.stage if self._state.stage not in {Stage.COMPLETE, Stage.ERROR} else Stage.IDLE,
            to_stage=Stage.DESIGN,
            payload={"goal": self._state.active_goal, "constraints": constraints},
        )
        await self._record_planning_orchestrator_followup(
            stage=Stage.IDLE,
            trigger="mission_intake_complete",
            payload={"goal": self._state.active_goal, "constraints": constraints},
            next_stage=Stage.DESIGN,
        )

        try:
            design_constraints = dict(constraints)
            geometry_hint = self._normalize_planning_geometry_type(design_constraints.get("geometry_type"))
            if geometry_hint:
                design_constraints["geometry_type"] = geometry_hint
                design_constraints["preferred_geometry_type"] = self._normalize_planning_geometry_type(
                    design_constraints.get("preferred_geometry_type") or geometry_hint
                ) or geometry_hint
            previous_spec = dict(self._state.current_experiment_spec or {})
            total_cycles = self._planning_cycle_limit(design_constraints)
            experiment_spec = await self._run_planning_design_stage(
                previous_spec=previous_spec,
                design_constraints=design_constraints,
                cycle_index=1,
                total_cycles=total_cycles,
                emit_handoff=False,
            )
            specimen = await self._run_planning_specimen_stage(experiment_spec)
            if specimen.get("pending"):
                self._schedule_post_run_vllm_transition()
                return {
                    "ok": True,
                    "message": "SpecimenMakingAgent waiting for operator input.",
                    "session": self.planning_snapshot(),
                }

            tail = await self._run_planning_cycle_series(
                first_spec=experiment_spec,
                design_constraints=design_constraints,
                start_cycle=1,
            )
            ok = bool(tail.get("ok", False))
            message = str(tail.get("message", "Planning handoff chain completed."))
        except Exception as exc:
            await self._append_planning_message(
                {
                    "role": "design_ai",
                    "content": (
                        "Planning handoff 실패했습니다.\n"
                        f"error={exc.__class__.__name__}: {exc}"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": False,
                },
                event_type="planning_design_result",
                level="ERROR",
                message="Planning handoff chain failed.",
            )
            ok = False
            message = "Planning handoff chain failed."

        self._schedule_post_run_vllm_transition()
        return {"ok": ok, "message": message, "session": self.planning_snapshot()}

    @staticmethod
    def _runtime_value(value: Any, default: str = "n/a") -> str:
        if value in (None, "", []):
            return default
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _runtime_command(value: Any) -> str:
        if not isinstance(value, list) or not value:
            return "n/a"
        return " ".join(str(item) for item in value)

    @staticmethod
    def _runtime_step_lines(step_trace: Any) -> list[str]:
        if not isinstance(step_trace, list) or not step_trace:
            return ["- n/a"]
        lines: list[str] = []
        for item in step_trace:
            if not isinstance(item, dict):
                continue
            step = str(item.get("step", "UNKNOWN"))
            status = str(item.get("status", "unknown"))
            detail = item.get("detail")
            suffix = f" ({detail})" if detail not in (None, "") else ""
            lines.append(f"- [{status}] {step}{suffix}")
        return lines or ["- n/a"]

    def _format_specimen_runtime_message(
        self,
        experiment_spec: dict[str, Any],
        specimen_payload: dict[str, Any],
    ) -> str:
        tool_result = specimen_payload.get("tool_result") if isinstance(specimen_payload.get("tool_result"), dict) else {}
        settings = specimen_payload.get("slicer_settings") if isinstance(specimen_payload.get("slicer_settings"), dict) else {}
        if not settings and isinstance(tool_result.get("slicer_settings"), dict):
            settings = tool_result["slicer_settings"]
        slicer_result = specimen_payload.get("slicer_result") if isinstance(specimen_payload.get("slicer_result"), dict) else {}
        if not slicer_result and isinstance(tool_result.get("slicer_result"), dict):
            slicer_result = tool_result["slicer_result"]
        gcode_validation = specimen_payload.get("gcode_validation") if isinstance(specimen_payload.get("gcode_validation"), dict) else {}
        printer = specimen_payload.get("printer") if isinstance(specimen_payload.get("printer"), dict) else {}
        prusalink = specimen_payload.get("prusalink") if isinstance(specimen_payload.get("prusalink"), dict) else {}
        print_result = specimen_payload.get("print_result") if isinstance(specimen_payload.get("print_result"), dict) else {}
        upload_result = print_result.get("upload") if isinstance(print_result.get("upload"), dict) else {}
        start_result = print_result.get("start") if isinstance(print_result.get("start"), dict) else {}
        ejection_result = specimen_payload.get("ejection_result") if isinstance(specimen_payload.get("ejection_result"), dict) else {}
        selected_printer = (
            tool_result.get("selected_printer")
            if isinstance(tool_result.get("selected_printer"), dict)
            else specimen_payload.get("selected_printer")
            if isinstance(specimen_payload.get("selected_printer"), dict)
            else {}
        )
        provider = (
            printer.get("provider")
            or tool_result.get("provider")
            or selected_printer.get("provider")
            or experiment_spec.get("printer_provider")
            or "selected_bridge"
        )
        printer_label = (
            selected_printer.get("label")
            or experiment_spec.get("printer_model")
            or settings.get("printer_model")
            or provider
        )
        storage_status = self._printer_storage_summary(printer.get("storage"), prusalink.get("storage"))

        lines = [
            "Specimen Making Agent가 선택된 3DP bridge 실행 준비를 완료했습니다.",
            "",
            "STL 형상 확인은 Design Agent artifact에서 처리하고, 이 단계는 슬라이싱 설정과 프린터 bridge 진행 상태를 표시합니다.",
            "",
            "Slicer / artifact 적용 설정값:",
            f"- specimen_id: {self._runtime_value(specimen_payload.get('specimen_id', experiment_spec.get('specimen_id')))}",
            f"- selected_printer: {self._runtime_value(printer_label)}",
            f"- provider: {self._runtime_value(provider)}",
            f"- printer_profile: {self._runtime_value(settings.get('printer_profile') or experiment_spec.get('printer_profile'))}",
            f"- material: {self._runtime_value(settings.get('material') or experiment_spec.get('material'))}",
            f"- slicer_profile_hint: {self._runtime_value(settings.get('slicer_profile_hint') or experiment_spec.get('slicer_profile_hint'))}",
            f"- layer_height_mm: {self._runtime_value(settings.get('layer_height_mm') or experiment_spec.get('layer_height_mm'))}",
            f"- nozzle_diameter_mm: {self._runtime_value(settings.get('nozzle_diameter_mm') or experiment_spec.get('nozzle_diameter_mm'))}",
            f"- first_layer_height_mm: {self._runtime_value(settings.get('first_layer_height_mm') or experiment_spec.get('first_layer_height_mm'))}",
            f"- slow_first_layer_enabled: {self._runtime_value(settings.get('slow_first_layer_enabled') if 'slow_first_layer_enabled' in settings else experiment_spec.get('slow_first_layer_enabled'))}",
            f"- first_layer_speed_mm_s: {self._runtime_value(settings.get('first_layer_speed_mm_s') or experiment_spec.get('first_layer_speed_mm_s'))}",
            f"- bed_temperature_c: {self._runtime_value(settings.get('bed_temperature_c') or experiment_spec.get('bed_temperature_c'))}",
            f"- first_layer_bed_temperature_c: {self._runtime_value(settings.get('first_layer_bed_temperature_c') or experiment_spec.get('first_layer_bed_temperature_c'))}",
            f"- wall_thickness_mm: {self._runtime_value(settings.get('wall_thickness_mm') or experiment_spec.get('wall_thickness_mm'))}",
            f"- cell_size_mm: {self._runtime_value(settings.get('cell_size_mm') or experiment_spec.get('cell_size_mm'))}",
            f"- relative_density: {self._runtime_value(settings.get('relative_density') or experiment_spec.get('relative_density'))}",
            f"- skirt_enabled: {self._runtime_value(settings.get('skirt_enabled') if 'skirt_enabled' in settings else experiment_spec.get('skirt_enabled'))}",
            f"- bottom_cap_enabled: {self._runtime_value(settings.get('bottom_cap_enabled') if 'bottom_cap_enabled' in settings else experiment_spec.get('bottom_cap_enabled'))}",
            f"- top_cap_enabled: {self._runtime_value(settings.get('top_cap_enabled') if 'top_cap_enabled' in settings else experiment_spec.get('top_cap_enabled'))}",
            f"- top_bottom_cap: {self._runtime_value(settings.get('top_bottom_cap') if 'top_bottom_cap' in settings else experiment_spec.get('top_bottom_cap'))}",
            f"- skin_thickness_mm: {self._runtime_value(settings.get('skin_thickness_mm') if 'skin_thickness_mm' in settings else experiment_spec.get('skin_thickness_mm'))}",
            f"- expected_mass_g: {self._runtime_value(settings.get('expected_mass_g') or specimen_payload.get('expected_mass_g') or experiment_spec.get('expected_mass_g'))}",
            f"- input_model_path: {self._runtime_value(settings.get('input_model_path') or specimen_payload.get('stl_path'))}",
            f"- output_gcode_path: {self._runtime_value(settings.get('output_gcode_path') or specimen_payload.get('sliced_path'))}",
            f"- slicer_simulated: {self._runtime_value(settings.get('simulated'))}",
            f"- slicer_command: {self._runtime_command(settings.get('resolved_command'))}",
            "",
            "Printer Bridge 결과:",
            f"- printer_prepare_status: {self._runtime_value(specimen_payload.get('printer_prepare_status'))}",
            f"- printer_mode: {self._runtime_value(specimen_payload.get('printer_mode'))}",
            f"- printer_path: {self._runtime_value(specimen_payload.get('printer_path'))}",
            f"- printer_state: {self._runtime_value(printer.get('state'))}",
            f"- bridge_transport: {self._runtime_value(prusalink.get('transport') or printer.get('transfer'))}",
            f"- storage: {storage_status}",
            f"- transfer_endpoint: {self._runtime_value(prusalink.get('upload_endpoint') or printer.get('artifact_url'))}",
            f"- upload_status: {self._runtime_value(upload_result.get('status') or upload_result.get('failure_code'))}",
            f"- upload_http_status: {self._runtime_value(upload_result.get('status_code'))}",
            f"- upload_elapsed_sec: {self._runtime_value(upload_result.get('elapsed_sec'))}",
            f"- upload_timeout_sec: {self._runtime_value(upload_result.get('timeout_sec'))}",
            f"- upload_bytes: {self._runtime_value(upload_result.get('bytes'))}",
            f"- start_status: {self._runtime_value(start_result.get('status') or start_result.get('failure_code'), 'ok' if start_result.get('ok') else 'n/a')}",
            f"- start_http_status: {self._runtime_value(start_result.get('status_code'))}",
            f"- gcode_validation: {self._runtime_value(gcode_validation.get('failure_code'), 'ok' if gcode_validation.get('ok') else 'n/a')}",
            f"- slicer_result: {self._runtime_value(slicer_result.get('failure_code'), 'ok' if slicer_result.get('ok') else 'n/a')}",
            f"- print_result: {self._runtime_value(print_result.get('status'))}",
            f"- ejection_result: {self._runtime_value(ejection_result.get('status'))}",
            "",
            "적용 중인 단계:",
            *self._runtime_step_lines(specimen_payload.get("step_trace")),
            "",
            "다음 단계는 GuardianAgent의 제조성/안전성 검증으로 넘깁니다.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _printer_storage_summary(storage_result: Any, selected_storage: Any) -> str:
        """Summarize selected printer storage readiness for operator-facing runtime text."""
        selected = str(selected_storage or "storage")
        if not isinstance(storage_result, dict):
            return selected
        if not storage_result.get("ok", False):
            return f"{selected} ({storage_result.get('failure_code', 'status_failed')})"
        payload = storage_result.get("payload") if isinstance(storage_result.get("payload"), dict) else storage_result
        entries = payload.get("storage_list") if isinstance(payload.get("storage_list"), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or entry.get("path") or "").strip("/")
            if name == selected:
                available = entry.get("available", "unknown")
                read_only = entry.get("read_only", "unknown")
                return f"{selected} available={available} read_only={read_only}"
        return selected

    async def _record_pending_specimen_input(self, specimen_payload: dict[str, Any]) -> None:
        input_request = specimen_payload.get("input_request") if isinstance(specimen_payload.get("input_request"), dict) else {}
        prompt = str(input_request.get("prompt") or "").strip()
        if not prompt:
            operator_messages = specimen_payload.get("operator_messages") if isinstance(specimen_payload.get("operator_messages"), list) else []
            prompt = "\n".join(str(item) for item in operator_messages if str(item).strip())
        prompt = prompt or "Specimen Making Agent가 작업자 입력을 기다립니다."
        self._state.run_metadata["pending_specimen_input"] = {
            "type": str(input_request.get("type") or "specimen_operator_input"),
            "specimen_id": specimen_payload.get("specimen_id"),
            "input_request": input_request,
        }
        await self._append_planning_message(
            {
                "role": "printer_ai",
                "content": prompt,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "specimen_agent",
                "ok": True,
                "pending_operator_input": True,
                "specimen": specimen_payload,
            },
            event_type="planning_specimen_input_required",
            message="SpecimenMakingAgent waiting for operator input.",
        )

    async def _handle_pending_specimen_operator_input(self, *, message: str, session_id: str | None) -> dict[str, Any]:
        pending = self._state.run_metadata.get("pending_specimen_input")
        pending = pending if isinstance(pending, dict) else {}
        request_type = str(pending.get("type", "")).strip()
        if request_type == "printer_test_path_choice":
            choice = self._parse_specimen_printer_choice(message)
            if not choice:
                await self._append_planning_message(
                    {
                        "role": "printer_ai",
                        "content": "Specimen Making Agent 선택지가 명확하지 않습니다. `가상 브릿지`, `설치 프린터`, `실제 출력` 중 하나로 답해주세요.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "model": "specimen_agent",
                        "ok": True,
                        "pending_operator_input": True,
                    },
                    event_type="planning_specimen_input_required",
                    message="SpecimenMakingAgent printer path choice still pending.",
                )
                return {"ok": True, "message": "SpecimenMakingAgent waiting for valid printer path choice.", "session": self.planning_snapshot(session_id=session_id)}

            experiment_spec = self._apply_specimen_printer_choice_to_spec(dict(self._state.current_experiment_spec or {}), choice)
            experiment_spec.setdefault("test_mode_autofill", True)
            experiment_spec.setdefault("test_mode_llm_generated", True)
            self._state.current_experiment_spec = experiment_spec
            self._state.run_metadata["last_specimen_printer_choice"] = choice
            self._state.run_metadata.pop("pending_specimen_input", None)
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": (
                        "SYSTEM_EVENT: OPERATOR_INPUT_APPLIED\n"
                        "agent=SpecimenMakingAgent\n"
                        f"printer_path={choice}\n"
                        "status=retry"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": True,
                },
                event_type="planning_handoff",
                message="SpecimenMakingAgent operator input received.",
            )
            return await self._resume_specimen_after_operator_input(experiment_spec=experiment_spec, session_id=session_id)

        if request_type == "printer_connection_info":
            if not self._is_connection_retry_message(message):
                connection_path = str(
                    input_request.get("connection_memory_path")
                    or input_request.get("settings_path")
                    or "memory/printer_connection.json"
                )
                provider = str(input_request.get("provider") or "selected printer bridge")
                await self._append_planning_message(
                    {
                        "role": "printer_ai",
                        "content": f"`{connection_path}`에 {provider} 연결 정보를 채운 뒤 `연결정보 입력 완료`라고 보내면 재시도합니다.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "model": "specimen_agent",
                        "ok": True,
                        "pending_operator_input": True,
                    },
                    event_type="planning_specimen_input_required",
                    message="SpecimenMakingAgent connection info still pending.",
                )
                return {"ok": True, "message": "SpecimenMakingAgent waiting for selected printer bridge connection info.", "session": self.planning_snapshot(session_id=session_id)}
            self._state.run_metadata.pop("pending_specimen_input", None)
            return await self._resume_specimen_after_operator_input(
                experiment_spec=dict(self._state.current_experiment_spec or {}),
                session_id=session_id,
            )

        self._state.run_metadata.pop("pending_specimen_input", None)
        return {"ok": False, "message": f"Unknown pending specimen input type: {request_type}", "session": self.planning_snapshot(session_id=session_id)}

    def _should_route_specimen_printer_choice(self, message: str) -> bool:
        """Give explicit printer-path answers priority over the orchestrator chat."""
        if not self._parse_specimen_printer_choice(message):
            return False
        pending = self._state.run_metadata.get("pending_specimen_input")
        if isinstance(pending, dict) and pending:
            return True
        spec = self._state.current_experiment_spec if isinstance(self._state.current_experiment_spec, dict) else {}
        if self._is_live_gui_test_handoff_spec(spec) and not self._specimen_printer_path(spec):
            return True
        for entry in reversed(self._planning_messages[-8:]):
            if not isinstance(entry, dict):
                continue
            if entry.get("pending_operator_input"):
                request = entry.get("input_request")
                if not isinstance(request, dict):
                    specimen = entry.get("specimen") if isinstance(entry.get("specimen"), dict) else {}
                    request = specimen.get("input_request") if isinstance(specimen.get("input_request"), dict) else {}
                if str(request.get("type", "")).strip() == "printer_test_path_choice":
                    return True
            content = str(entry.get("content", ""))
            if "가상 브릿지" in content and "설치 프린터" in content and "실제 출력" in content:
                return True
        return False

    def _ensure_pending_specimen_printer_choice(self) -> None:
        """Recover printer-path pending state if the browser/server session lost it."""
        spec = self._state.current_experiment_spec if isinstance(self._state.current_experiment_spec, dict) else {}
        self._state.run_metadata["pending_specimen_input"] = {
            "type": "printer_test_path_choice",
            "specimen_id": spec.get("specimen_id"),
            "input_request": {
                "type": "printer_test_path_choice",
                "choices": ["virtual_bridge", "installed_printer", "physical_print"],
            },
        }

    @staticmethod
    def _is_live_gui_test_handoff_spec(spec: dict[str, Any]) -> bool:
        return bool(spec.get("test_mode_autofill") or spec.get("test_mode_llm_generated"))

    @staticmethod
    def _specimen_printer_path(spec: dict[str, Any]) -> str:
        for key in ("printer_test_path", "test_printer_path", "printer_bridge_mode", "printer_test_mode"):
            value = str(spec.get(key, "")).strip()
            if value:
                return value
        return ""

    @staticmethod
    def _parse_inline_test_mode_printer_choice(message: str) -> str:
        """Parse one-shot Live GUI test commands like `테스트 모드, 실제 출력`."""
        if not MainController._should_trigger_test_design(message):
            return ""
        return MainController._parse_specimen_printer_choice(message)

    @staticmethod
    def _apply_specimen_printer_choice_to_spec(spec: dict[str, Any], choice: str) -> dict[str, Any]:
        """Apply the SpecimenMakingAgent printer path choice to a spec/constraint payload."""
        normalized = str(choice or "").strip()
        if normalized not in {"virtual_bridge", "installed_printer", "physical_print"}:
            return dict(spec)

        updated = dict(spec)
        updated["printer_test_path"] = normalized
        updated["test_printer_transport"] = "real" if normalized in {"installed_printer", "physical_print"} else "virtual"
        updated["allow_test_printer_live"] = normalized in {"installed_printer", "physical_print"}

        print_request = dict(updated.get("print", {})) if isinstance(updated.get("print"), dict) else {}
        if normalized == "physical_print":
            print_request.update(
                {
                    "start_immediately": True,
                    "physical_intent": True,
                    "confirm_physical_print": True,
                }
            )
        else:
            print_request.update(
                {
                    "start_immediately": False,
                    "physical_intent": False,
                    "confirm_physical_print": False,
                }
            )
        updated["print"] = print_request
        return updated

    @staticmethod
    def _parse_specimen_printer_choice(message: str) -> str:
        normalized = re.sub(r"\s+", "", message.lower())
        if any(token in normalized for token in ("실제출력", "출력", "actualprint", "physicalprint", "startprint")):
            return "physical_print"
        if any(token in normalized for token in ("가상", "virtual", "bridge", "브릿지", "브리지")):
            return "virtual_bridge"
        if any(token in normalized for token in ("설치", "실제", "프린터", "printer", "prusa", "real")):
            return "installed_printer"
        return ""

    @staticmethod
    def _is_connection_retry_message(message: str) -> bool:
        normalized = re.sub(r"\s+", "", message.lower())
        return any(token in normalized for token in ("완료", "입력", "저장", "재시도", "retry", "done"))

    async def _resume_specimen_after_operator_input(self, *, experiment_spec: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        try:
            tail = await self._run_specimen_guardian_tail(experiment_spec)
            ok = bool(tail.get("ok", False))
            message = str(tail.get("message", "SpecimenMakingAgent resumed."))
        except Exception as exc:
            await self._append_planning_message(
                {
                    "role": "printer_ai",
                    "content": (
                        "Specimen Making Agent 재시도에 실패했습니다.\n"
                        f"error={exc.__class__.__name__}: {exc}"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": False,
                },
                event_type="planning_specimen_result",
                level="ERROR",
                message="SpecimenMakingAgent resume failed.",
            )
            ok = False
            message = "SpecimenMakingAgent resume failed."
        self._schedule_post_run_vllm_transition()
        return {"ok": ok, "message": message, "session": self.planning_snapshot(session_id=session_id)}

    @staticmethod
    def _is_planning_test_spec(experiment_spec: dict[str, Any]) -> bool:
        """Return whether Live GUI handoff represents test-mode execution."""
        return bool(
            experiment_spec.get("test_mode_autofill")
            or experiment_spec.get("test_mode_llm_generated")
            or experiment_spec.get("printer_test_path")
            or experiment_spec.get("test_printer_path")
            or experiment_spec.get("printer_bridge_mode")
            or experiment_spec.get("printer_test_mode")
        )

    def _apply_test_cycle_surface_cap_policy(
        self,
        experiment_spec: dict[str, Any],
        *,
        cycle_index: int,
    ) -> dict[str, Any]:
        """Disable generated-model cap skins from cycle 2 onward in test-mode series."""
        if cycle_index < 2 or not self._is_planning_test_spec(experiment_spec):
            return experiment_spec
        updated = dict(experiment_spec)
        updated["top_cap_enabled"] = False
        updated["bottom_cap_enabled"] = False
        updated["top_bottom_cap"] = False
        updated["skin_thickness_mm"] = 0.0
        updated["require_flat_compression_faces"] = False
        updated["test_loop_surface_caps_disabled"] = True
        updated["analysis_platen_policy"] = {
            "top": True,
            "bottom": True,
            "applies_to": "cae_only_not_generated_stl",
        }
        constraints = updated.get("constraints") if isinstance(updated.get("constraints"), dict) else {}
        updated["constraints"] = {
            **constraints,
            "top_cap_enabled": False,
            "bottom_cap_enabled": False,
            "top_bottom_cap": False,
            "skin_thickness_mm": 0.0,
            "require_flat_compression_faces": False,
            "test_loop_surface_caps_disabled": True,
        }
        return updated

    def _merge_planning_agent_data(self, stage: Stage, data: dict[str, Any]) -> None:
        """Mirror RunLoop state merging for Live GUI's manual handoff chain."""
        if isinstance(data, dict):
            self._state.run_metadata[f"{stage.value}_agent_payload"] = data
            if isinstance(data.get("design_report"), dict):
                self._state.run_metadata["design_report"] = data["design_report"]
            if isinstance(data.get("design_agent_report"), dict):
                self._state.run_metadata["latest_design_agent_report"] = data["design_agent_report"]
            if isinstance(data.get("design_candidate"), dict):
                self._state.run_metadata["design_candidate"] = data["design_candidate"]
            if isinstance(data.get("handoff_packet"), dict):
                self._state.run_metadata[f"{stage.value}_handoff_packet"] = data["handoff_packet"]
                packets = self._state.run_metadata.get("handoff_packets")
                if not isinstance(packets, list):
                    packets = []
                packets.append({"stage": stage.value, "packet": data["handoff_packet"]})
                self._state.run_metadata["handoff_packets"] = packets[-20:]
            if isinstance(data.get("decisions"), list):
                self._state.run_metadata[f"{stage.value}_decision_register"] = data["decisions"]
            if isinstance(data.get("metrics"), dict):
                self._state.run_metadata[f"{stage.value}_metrics"] = data["metrics"]
            if isinstance(data.get("mission_contract"), dict):
                self._state.run_metadata["mission_contract"] = data["mission_contract"]
                self._state.run_metadata["latest_mission_contract"] = data["mission_contract"]
            if isinstance(data.get("orchestration_plan"), dict):
                plans = self._state.run_metadata.get("orchestration_plans")
                if not isinstance(plans, list):
                    plans = []
                plans.append(data["orchestration_plan"])
                self._state.run_metadata["orchestration_plans"] = plans[-20:]
                self._state.run_metadata["latest_orchestration_plan"] = data["orchestration_plan"]
            if isinstance(data.get("fabrication_report"), dict):
                self._state.run_metadata["fabrication_report"] = data["fabrication_report"]
                self._state.run_metadata[f"{stage.value}_fabrication_report"] = data["fabrication_report"]
            if isinstance(data.get("specimen_agent_report"), dict):
                self._state.run_metadata["latest_specimen_agent_report"] = data["specimen_agent_report"]
            if isinstance(data.get("specimen_fabricated"), dict):
                self._state.run_metadata["specimen_fabricated"] = data["specimen_fabricated"]
            if isinstance(data.get("vision_report"), dict):
                self._state.run_metadata["vision_report"] = data["vision_report"]
                self._state.run_metadata[f"{stage.value}_vision_report"] = data["vision_report"]
            if isinstance(data.get("vision_agent_report"), dict):
                self._state.run_metadata["latest_vision_agent_report"] = data["vision_agent_report"]
            if isinstance(data.get("vision_signal"), dict):
                self._state.run_metadata["vision_signal"] = data["vision_signal"]
            if isinstance(data.get("manipulation_report"), dict):
                self._state.run_metadata["manipulation_report"] = data["manipulation_report"]
                self._state.run_metadata[f"{stage.value}_manipulation_report"] = data["manipulation_report"]
            if isinstance(data.get("manipulation_agent_report"), dict):
                self._state.run_metadata["latest_manipulation_agent_report"] = data["manipulation_agent_report"]
            if isinstance(data.get("robot_task_result"), dict):
                self._state.run_metadata["robot_task_result"] = data["robot_task_result"]
                self._state.run_metadata[f"{stage.value}_robot_task_result"] = data["robot_task_result"]
        if "experiment_spec" in data:
            self._state.current_experiment_spec = data["experiment_spec"]
        if "experiment_objective" in data:
            self._state.current_experiment_objective = data["experiment_objective"]
        if "experiment_evaluation" in data and isinstance(data["experiment_evaluation"], dict):
            self._state.experiment_evaluations.append(data["experiment_evaluation"])
        specimen_result = data.get("specimen_result") if isinstance(data.get("specimen_result"), dict) else {}
        if specimen_result:
            self._state.run_metadata["specimen_result"] = specimen_result
        if isinstance(specimen_result.get("experiment_evaluation"), dict):
            self._state.experiment_evaluations.append(specimen_result["experiment_evaluation"])
        if "observation" in data:
            self._state.latest_observations = data["observation"]
            if isinstance(data["observation"], dict):
                self._state.run_metadata["latest_vision_observation"] = data["observation"]
        if "analysis" in data:
            self._state.latest_analysis.update(data["analysis"])
        if "sarm" in data:
            self._state.latest_analysis["sarm"] = data["sarm"]
        if "manipulation" in data:
            manipulation = data["manipulation"] if isinstance(data["manipulation"], dict) else {}
            self._state.run_metadata["manipulation_result"] = manipulation
            self._state.latest_analysis["last_grasp_score"] = float(manipulation.get("grasp_score", 0.0))
            if "sarm" in data:
                self._state.latest_analysis["sarm"] = data["sarm"]
        if "equipment_result" in data:
            equipment_result = data["equipment_result"] if isinstance(data["equipment_result"], dict) else {}
            self._state.run_metadata["equipment_result"] = equipment_result
            if isinstance(data.get("equipment_report"), dict):
                self._state.run_metadata["equipment_report"] = data["equipment_report"]
            if isinstance(data.get("utm_data_ready"), dict):
                self._state.run_metadata["utm_data_ready"] = data["utm_data_ready"]
            if "equipment_handoff" in data:
                self._state.run_metadata["equipment_handoff"] = data["equipment_handoff"]
            self._state.latest_analysis["equipment_ok"] = bool(equipment_result.get("ok", False))
            self._state.latest_analysis["equipment_status"] = str(equipment_result.get("status") or "")
            self._state.latest_analysis["equipment_program_id"] = str(equipment_result.get("program_id") or "")
            result_file = equipment_result.get("result_file") or equipment_result.get("utm_csv_path")
            if result_file:
                self._state.latest_analysis["equipment_result_file"] = str(result_file)
            failure_code = equipment_result.get("failure_code")
            if failure_code:
                self._state.latest_analysis["equipment_failure_code"] = str(failure_code)
        hardware_alerts_raw = data.get("hardware_alerts") if isinstance(data.get("hardware_alerts"), list) else []
        hardware_alert_single = data.get("hardware_alert") if isinstance(data.get("hardware_alert"), dict) else None
        hardware_alerts = [dict(item) for item in hardware_alerts_raw if isinstance(item, dict)]
        if hardware_alert_single:
            hardware_alerts.append(dict(hardware_alert_single))
        incident_records_raw = data.get("incident_records") if isinstance(data.get("incident_records"), list) else []
        incident_records = [dict(item) for item in incident_records_raw if isinstance(item, dict)]
        if hardware_alerts:
            stored_alerts = self._state.run_metadata.setdefault("hardware_alerts", [])
            if not isinstance(stored_alerts, list):
                stored_alerts = []
                self._state.run_metadata["hardware_alerts"] = stored_alerts
            seen_alert_ids = {str(item.get("alert_id")) for item in stored_alerts if isinstance(item, dict)}
            for alert in hardware_alerts:
                alert_id = str(alert.get("alert_id") or "")
                if alert_id and alert_id in seen_alert_ids:
                    incident = alert.get("incident_record")
                    if isinstance(incident, dict):
                        incident_records.append(dict(incident))
                    continue
                stored_alerts.append(alert)
                guardian_decision = alert.get("guardian_decision")
                if isinstance(guardian_decision, dict):
                    self._state.run_metadata["latest_guardian_decision"] = guardian_decision
                incident = alert.get("incident_record")
                if isinstance(incident, dict):
                    incident_records.append(dict(incident))
                device_class = str(alert.get("device_class") or "hardware")
                failure = str(alert.get("failure_code") or alert.get("status") or "alert")
                severity = str(alert.get("severity") or "warning")
                self._state.device_health[device_class] = f"{severity}:{failure}"
            del stored_alerts[:-50]
        if incident_records:
            self._record_incident_records(incident_records)
        if "knowledge" in data:
            self._state.run_metadata["knowledge"] = data["knowledge"]
        if "bo_result" in data:
            self._state.run_metadata["bo_agent"] = data["bo_result"]
        if "experiment_spec_update" in data and isinstance(data["experiment_spec_update"], dict):
            update = {
                key: value
                for key, value in data["experiment_spec_update"].items()
                if key != "cell_size_mm"
            }
            self._state.run_metadata["bo_recommended_constraints"] = update
        if "guardian" in data:
            self._state.run_metadata["guardian"] = data["guardian"]
        self._state.run_metadata["last_stage_payload"] = {"stage": stage.value, "data": data}
        self._compact_planning_runtime_state()

    def _compact_planning_runtime_state(self) -> None:
        """Keep Live GUI handoff state bounded after agent payload merges."""
        self._state.run_metadata = self._compact_planning_run_metadata(self._state.run_metadata)
        self._state.current_experiment_spec = compact_runtime_payload(self._state.current_experiment_spec)
        self._state.current_experiment_objective = compact_runtime_payload(self._state.current_experiment_objective)
        self._state.latest_observations = compact_runtime_payload(self._state.latest_observations)
        self._state.latest_analysis = compact_runtime_payload(self._state.latest_analysis)
        self._state.experiment_evaluations = compact_runtime_payload(self._state.experiment_evaluations)
        trim_runtime_memory()

    def _planning_stage_role(self, stage: Stage, module_runtime: dict[str, Any] | None = None) -> str:
        fixed_role = {
            Stage.VISION: "vision_ai",
            Stage.MANIPULATION: "manipulation_ai",
            Stage.EQUIPMENT: "equipment_ai",
            Stage.ANALYSIS: "analysis_ai",
            Stage.KNOWLEDGE: "knowledge_ai",
            Stage.GUARDIAN: "guardian",
        }.get(stage)
        if fixed_role:
            return fixed_role
        runtime = module_runtime if isinstance(module_runtime, dict) else {}
        for key in ("effective_handler", "handler"):
            handler = str(runtime.get(key) or "").strip()
            if handler.startswith("agent."):
                return handler.removeprefix("agent.")
            if handler:
                return handler.replace(".", "_")
        return f"{stage.value}_agent" if stage.value not in {Stage.IDLE.value, Stage.COMPLETE.value, Stage.ERROR.value} else "system"

    def _active_graph_config_for_labels(self):
        """Compatibility wrapper for label lookups."""
        return self._active_graph_config()

    def _active_graph_config(self):
        """Load the active runtime graph config used by Live GUI planning."""
        path = self._active_graph_config_path or (Path(__file__).resolve().parent.parent / "graphs" / "configs" / "atr_closed_loop.yaml")
        try:
            return load_graph_config(path)
        except Exception:
            return None

    def _graph_node_for_stage(self, stage: Stage):
        """Return the graph node bound to a runtime stage, if present."""
        config = self._active_graph_config()
        if config is None:
            return None
        for node in config.nodes:
            if node.stage == stage.value:
                return node
        return None

    def _module_runtime_for_stage(self, stage: Stage, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return compact module runtime metadata for Live GUI messages."""
        payload = payload if isinstance(payload, dict) else {}
        module_runtime = payload.get("module_runtime") if isinstance(payload.get("module_runtime"), dict) else {}
        node = self._graph_node_for_stage(stage)
        if node is None:
            return {
                **module_runtime,
                "module_id": stage.value,
                "graph_module_id": str(module_runtime.get("module_id") or ""),
                "stage": stage.value,
                "handler": "",
                "label": self._planning_stage_role(stage, module_runtime),
            }
        original_module_id = str(module_runtime.get("module_id") or getattr(node, "module_id", "") or "")
        return {
            **module_runtime,
            "module_id": getattr(node, "id", stage.value) or stage.value,
            "graph_module_id": original_module_id,
            "stage": stage.value,
            "handler": getattr(node, "handler", "") or "",
            "label": getattr(node, "label", "") or stage.value,
            "kind": getattr(node, "kind", "") or "",
        }

    def _next_configured_stage_after(self, stage: Stage, *, fallback: Stage | None = None) -> Stage | None:
        """Resolve the next stage from the active graph transitions."""
        config = self._active_graph_config()
        if config is not None:
            try:
                return Stage(config.next_stage(stage.value))
            except ValueError:
                return fallback
        return fallback

    def _active_graph_stage_sequence(
        self,
        start: Stage,
        *,
        stop_at: Stage | None = None,
        include_start: bool = True,
        max_steps: int = 64,
    ) -> list[Stage]:
        """Follow active graph transitions and return a bounded stage sequence."""
        config = self._active_graph_config()
        if config is None:
            fallback = [
                Stage.DESIGN,
                Stage.SPECIMEN,
                Stage.VISION,
                Stage.MANIPULATION,
                Stage.EQUIPMENT,
                Stage.ANALYSIS,
                Stage.KNOWLEDGE,
                Stage.BO,
                Stage.GUARDIAN,
            ]
            if start in fallback:
                fallback = fallback[fallback.index(start):]
            if stop_at in fallback:
                fallback = fallback[: fallback.index(stop_at) + 1]
            return fallback if include_start else fallback[1:]

        sequence: list[Stage] = []
        current = start
        visited_edges: set[tuple[str, str]] = set()
        for index in range(max_steps):
            if include_start or index > 0:
                sequence.append(current)
            if stop_at is not None and current == stop_at:
                break
            if current in {Stage.COMPLETE, Stage.ERROR}:
                break
            try:
                next_stage = Stage(config.next_stage(current.value))
            except ValueError:
                break
            edge = (current.value, next_stage.value)
            if edge in visited_edges:
                break
            visited_edges.add(edge)
            current = next_stage
        return sequence

    def _active_graph_stage_route_text(self, start: Stage, *, stop_at: Stage | None = None) -> str:
        """Return a user-facing route string from the active graph config."""
        stages = self._active_graph_stage_sequence(start, stop_at=stop_at, include_start=True)
        if not stages:
            stages = [start]
        return " -> ".join(self._planning_stage_label(stage) for stage in stages)

    def _planning_tail_start_stage(self) -> Stage | None:
        """Return the configured stage after Specimen for Live GUI planning tail."""
        return self._next_configured_stage_after(Stage.SPECIMEN, fallback=Stage.VISION)

    def _planning_tail_stages(self, start: Stage) -> set[Stage]:
        """Return active graph stages handled by the post-Specimen planning tail."""
        stages = self._active_graph_stage_sequence(start, stop_at=Stage.GUARDIAN, include_start=True)
        return {stage for stage in stages if stage not in {Stage.IDLE, Stage.DESIGN, Stage.SPECIMEN, Stage.COMPLETE, Stage.ERROR}}

    def _planning_stage_label(self, stage: Stage, module_runtime: dict[str, Any] | None = None) -> str:
        """Resolve a user-facing stage label from module/graph config, then fallback to display text."""
        module_runtime = module_runtime if isinstance(module_runtime, dict) else {}
        label = str(module_runtime.get("label") or "").strip()
        if label:
            return label
        config = self._active_graph_config_for_labels()
        if config is not None:
            for node in config.nodes:
                if node.stage == stage.value and node.label:
                    return node.label
        return {
            Stage.VISION: "Vision Agent",
            Stage.MANIPULATION: "Manipulation Agent",
            Stage.EQUIPMENT: "Lab Equipment Agent",
            Stage.ANALYSIS: "Analysis Agent",
            Stage.KNOWLEDGE: "Knowledge Agent",
            Stage.BO: "BO Agent",
            Stage.GUARDIAN: "Guardian Agent",
        }.get(stage, stage.value)

    @staticmethod
    def _planning_agent_from_payload(payload: dict[str, Any]) -> str:
        """Resolve event agent identity from runtime event/module config only."""
        agent = str(payload.get("agent") or "").strip()
        if agent:
            return agent
        module_runtime = payload.get("module_runtime") if isinstance(payload.get("module_runtime"), dict) else {}
        for key in ("effective_handler", "handler"):
            handler = str(module_runtime.get(key) or "").strip()
            if handler.startswith("agent."):
                return handler.removeprefix("agent.")
        return ""

    def _planning_stage_handoff_text(self, previous: str, stage: Stage, module_runtime: dict[str, Any] | None = None) -> str:
        return f"SYSTEM_EVENT: HANDOFF\nfrom={previous}\nto={self._planning_stage_label(stage, module_runtime)}\nstatus=started"

    def _format_planning_stage_message(self, stage: Stage, data: dict[str, Any], summary: str) -> str:
        if stage == Stage.VISION:
            observation = data.get("observation") if isinstance(data.get("observation"), dict) else {}
            report = data.get("vision_report") if isinstance(data.get("vision_report"), dict) else observation.get("vision_report", {}) if isinstance(observation.get("vision_report"), dict) else {}
            packet = data.get("vision_signal") if isinstance(data.get("vision_signal"), dict) else observation.get("vision_signal", {}) if isinstance(observation.get("vision_signal"), dict) else {}
            readiness = observation.get("transfer_readiness") if isinstance(observation.get("transfer_readiness"), dict) else {}
            camera = report.get("camera_source") if isinstance(report.get("camera_source"), dict) else {}
            zones = report.get("scene_map") if isinstance(report.get("scene_map"), dict) else report.get("zones", {}) if isinstance(report.get("zones"), dict) else {}
            signals = report.get("signal_board") if isinstance(report.get("signal_board"), list) else report.get("agent_signals", []) if isinstance(report.get("agent_signals"), list) else []
            pickup = next((signal for signal in signals if isinstance(signal, dict) and signal.get("signal") == "pickup_ready"), {})
            zone_summary = ", ".join(
                f"{zone_id}={zone.get('state') or ('present' if zone.get('specimen_present') else 'unknown')}"
                for zone_id, zone in list(zones.items())[:4]
                if isinstance(zone, dict)
            )
            artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
            return (
                "Vision Agent가 lab perception signal을 발행했습니다.\n\n"
                f"- task: {self._runtime_value(report.get('task') or 'post_ejection_basket_check')}\n"
                f"- camera: {self._runtime_value(camera.get('camera_key') or observation.get('camera_key'))} / {self._runtime_value(camera.get('source') or observation.get('source'))}\n"
                f"- zone_state: {self._runtime_value(zone_summary or 'not recorded')}\n"
                f"- pickup_ready: {self._runtime_value(pickup.get('status') or readiness.get('ready'))}, confidence={self._runtime_value(pickup.get('confidence') or readiness.get('pose_confidence'))}\n"
                f"- expires_at: {self._runtime_value(pickup.get('expires_at') or packet.get('expires_at'))}\n"
                f"- anomaly: {self._runtime_value(observation.get('anomaly'))}\n"
                f"- evidence: {self._runtime_value(artifacts.get('annotated_frame_path') or artifacts.get('detection_json_path'))}"
            )
        if stage == Stage.MANIPULATION:
            manipulation = data.get("manipulation") if isinstance(data.get("manipulation"), dict) else {}
            sarm = data.get("sarm") if isinstance(data.get("sarm"), dict) else {}
            transfer = manipulation.get("transfer_task") if isinstance(manipulation.get("transfer_task"), dict) else {}
            return (
                "Manipulation Agent가 3DP 출력물 이송 단계를 실행했습니다.\n\n"
                f"- strategy: {self._runtime_value(manipulation.get('strategy'))}\n"
                f"- status: {self._runtime_value(manipulation.get('status'))}\n"
                f"- completion_status: {self._runtime_value(manipulation.get('completion_status'))}\n"
                f"- source -> target: {self._runtime_value(transfer.get('source'))} -> {self._runtime_value(transfer.get('target'))}\n"
                f"- grasp_score: {self._runtime_value(manipulation.get('grasp_score'))}\n"
                f"- sarm_progress: {self._runtime_value(sarm.get('progress_score'))}\n"
                f"- recovery_hint: {self._runtime_value(sarm.get('recovery_hint'))}"
            )
        if stage == Stage.EQUIPMENT:
            equipment = data.get("equipment_result") if isinstance(data.get("equipment_result"), dict) else {}
            handoff = data.get("equipment_handoff") if isinstance(data.get("equipment_handoff"), dict) else {}
            report = data.get("equipment_report") if isinstance(data.get("equipment_report"), dict) else {}
            cross = report.get("cross_checks") if isinstance(report.get("cross_checks"), dict) else equipment.get("cross_checks", {}) if isinstance(equipment.get("cross_checks"), dict) else {}
            vision_cross = report.get("vision_cross_checks") if isinstance(report.get("vision_cross_checks"), dict) else equipment.get("vision_cross_checks", {}) if isinstance(equipment.get("vision_cross_checks"), dict) else {}
            vision_blocking = vision_cross.get("blocking_reasons") if isinstance(vision_cross.get("blocking_reasons"), list) else []
            data_acq = report.get("data_acquisition") if isinstance(report.get("data_acquisition"), dict) else equipment.get("data_acquisition", {}) if isinstance(equipment.get("data_acquisition"), dict) else {}
            decision = report.get("decision") if isinstance(report.get("decision"), dict) else {}
            return (
                "Lab Equipment Agent가 UTM 장비 제어/검증 단계를 실행했습니다.\n\n"
                f"- tool: {self._runtime_value(equipment.get('tool'))}\n"
                f"- status: {self._runtime_value(equipment.get('status'))}\n"
                f"- program_id: {self._runtime_value(equipment.get('program_id'))}\n"
                f"- handoff: {self._runtime_value(handoff.get('status'))}\n"
                f"- screen/physical/data: {self._runtime_value(cross.get('screen_started'))} / {self._runtime_value(cross.get('physical_motion_started'))} / {self._runtime_value(cross.get('data_parse_probe_ok'))}\n"
                f"- vision_gate: {self._runtime_value(vision_cross.get('all_required_ok'))}, blocking={self._runtime_value(vision_blocking)}\n"
                f"- result_file: {self._runtime_value(data_acq.get('linux_path') or handoff.get('result_file'))}\n"
                f"- rows: {self._runtime_value(data_acq.get('row_count_probe'))}, columns: {self._runtime_value(data_acq.get('columns_probe'))}\n"
                f"- failure_code: {self._runtime_value(decision.get('failure_code') or equipment.get('failure_code'))}\n"
                "적용 중인 단계:\n"
                + "\n".join(self._runtime_step_lines(equipment.get("step_trace")))
            )
        if stage == Stage.ANALYSIS:
            analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
            utm = analysis.get("utm_metrics") if isinstance(analysis.get("utm_metrics"), dict) else {}
            cae = analysis.get("cae_metrics") if isinstance(analysis.get("cae_metrics"), dict) else {}
            cae_result = analysis.get("cae_result") if isinstance(analysis.get("cae_result"), dict) else {}
            platens = cae_result.get("analysis_platens") if isinstance(cae_result.get("analysis_platens"), dict) else {}
            generated_caps = cae_result.get("generated_model_caps") if isinstance(cae_result.get("generated_model_caps"), dict) else {}
            trust_score = analysis.get("trust_score") if isinstance(analysis.get("trust_score"), dict) else {}
            multifidelity = analysis.get("multifidelity_comparison") if isinstance(analysis.get("multifidelity_comparison"), dict) else {}
            mf_curve = multifidelity.get("curve") if isinstance(multifidelity.get("curve"), dict) else {}
            return (
                "Analysis Agent가 UTM/CAE closed-loop 분석을 완료했습니다.\n\n"
                f"- objective_score: {self._runtime_value(analysis.get('objective_score'))}\n"
                f"- uncertainty: {self._runtime_value(analysis.get('uncertainty'))}\n"
                f"- trust_score/gate: {self._runtime_value(trust_score.get('score'))} / {self._runtime_value(trust_score.get('gate'))}\n"
                f"- UTM-FEA agreement: {self._runtime_value(mf_curve.get('agreement_score'))}, peak_error_pct={self._runtime_value(mf_curve.get('peak_force_error_pct'))}\n"
                f"- peak_force_N: {self._runtime_value(utm.get('peak_force_N'))}\n"
                f"- compressive_strength_MPa: {self._runtime_value(utm.get('compressive_strength_MPa'))}\n"
                f"- CAE max_von_mises_MPa: {self._runtime_value(cae.get('max_von_mises_MPa'))}\n"
                f"- CAE effective_modulus_MPa: {self._runtime_value(cae.get('effective_modulus_MPa'))}\n"
                f"- CAE structural_score: {self._runtime_value(cae.get('structural_score'))}\n"
                f"- CAE platens: top={self._runtime_value(platens.get('top'))}, bottom={self._runtime_value(platens.get('bottom'))}, applies_to={self._runtime_value(platens.get('applies_to'))}\n"
                f"- generated_model_caps: {json.dumps(generated_caps, ensure_ascii=False)}\n"
                f"- closed_loop_sources: {self._runtime_value(analysis.get('closed_loop_sources'))}"
            )
        if stage == Stage.KNOWLEDGE:
            knowledge = data.get("knowledge") if isinstance(data.get("knowledge"), dict) else {}
            context = knowledge.get("knowledge_context") if isinstance(knowledge.get("knowledge_context"), dict) else {}
            evidence_quality = context.get("evidence_quality") if isinstance(context.get("evidence_quality"), dict) else {}
            proposal = knowledge.get("evolution_proposal") if isinstance(knowledge.get("evolution_proposal"), dict) else {}
            packs = proposal.get("evidence_packs") if isinstance(proposal.get("evidence_packs"), list) else []
            top_pack = packs[0] if packs and isinstance(packs[0], dict) else {}
            return (
                "Knowledge Agent가 연구 기억과 self-evolution 증거팩을 갱신했습니다.\n\n"
                f"- retrieval_coverage: {self._runtime_value(knowledge.get('retrieval_coverage'))}\n"
                f"- memory_summary: {self._runtime_value(knowledge.get('memory_summary'))}\n"
                f"- agent_performance_records: {self._runtime_value(knowledge.get('agent_performance_count'))}\n"
                f"- failure/success_patterns: {self._runtime_value(knowledge.get('failure_pattern_count'))} / {self._runtime_value(knowledge.get('success_pattern_count'))}\n"
                f"- evolution_evidence_packs: {self._runtime_value(knowledge.get('evolution_pack_count'))}\n"
                f"- artifact_link_coverage: {self._runtime_value(evidence_quality.get('artifact_link_coverage'))}\n"
                f"- top_evolution_target: {self._runtime_value(top_pack.get('target_id'))} ({self._runtime_value(top_pack.get('target_type'))})"
            )
        if stage == Stage.GUARDIAN:
            guardian = data.get("guardian") if isinstance(data.get("guardian"), dict) else {}
            decision = str(guardian.get("decision", "continue")).strip() or "continue"
            action = str(guardian.get("action", "")).strip()
            reason = str(guardian.get("reason", "")).strip()
            return (
                "Guardian Agent 검증 결과:\n\n"
                f"- decision: {decision}\n"
                f"- action: {action or 'continue'}\n"
                f"- reason: {reason or 'n/a'}\n"
                f"- precursor: {self._runtime_value(guardian.get('precursor'))}\n"
                f"- design_validation: {json.dumps(guardian.get('design_validation', {}), ensure_ascii=False)}\n"
                f"- health_validation: {json.dumps(guardian.get('health_validation', {}), ensure_ascii=False)}\n"
                f"- consistency: {json.dumps(guardian.get('consistency', {}), ensure_ascii=False)}"
            )
        return summary

    def _format_planning_bo_message(self, data: dict[str, Any]) -> str:
        bo_result = data.get("bo_result") if isinstance(data.get("bo_result"), dict) else {}
        recommendation = bo_result.get("recommendation") if isinstance(bo_result.get("recommendation"), dict) else {}
        knowledge = bo_result.get("knowledge_context") if isinstance(bo_result.get("knowledge_context"), dict) else {}
        reasoning = bo_result.get("reasoning") if isinstance(bo_result.get("reasoning"), dict) else {}
        prior_summary = bo_result.get("prior_summary") if isinstance(bo_result.get("prior_summary"), dict) else {}
        return (
            "BO Agent가 측정 evidence, Knowledge memory, acquisition score, reasoning preference를 결합해 다음 설계 후보를 추천했습니다.\n\n"
            f"- strategy: {self._runtime_value(bo_result.get('strategy'))} / benchmark={self._runtime_value(bo_result.get('benchmark_strategy'))}\n"
            f"- acquisition: {self._runtime_value(bo_result.get('acquisition'))}\n"
            f"- priors: measured={self._runtime_value(prior_summary.get('measured_count'))}, failed={self._runtime_value(prior_summary.get('failed_count'))}\n"
            f"- recommended_candidate: {self._runtime_value(recommendation.get('candidate_id'))}\n"
            f"- combined_score: {self._runtime_value(recommendation.get('combined_score'))}\n"
            f"- why: {self._runtime_value(recommendation.get('why_this_candidate') or recommendation.get('reason'))}\n"
            f"- recommended_parameters: {json.dumps(recommendation.get('parameters', {}), ensure_ascii=False)}\n"
            f"- reasoning_summary: {self._runtime_value(reasoning.get('operator_summary'))}\n"
            f"- knowledge_coverage: {self._runtime_value(knowledge.get('retrieval_coverage'))}"
        )

    async def _run_planning_loop_tail(
        self,
        experiment_spec: dict[str, Any],
        *,
        cycle_index: int = 1,
        total_cycles: int = 1,
    ) -> dict[str, Any]:
        """Continue Live GUI handoff through the configured LangGraph runtime after Specimen."""
        original_mode = self._state.mode
        effective_mode = Mode.TEST if self._is_planning_test_spec(experiment_spec) else original_mode
        guardian_payload: dict[str, Any] = {}
        previous_label = self._planning_stage_label(Stage.SPECIMEN)
        tail_start = self._planning_tail_start_stage()
        if tail_start is None or tail_start in {Stage.COMPLETE, Stage.ERROR}:
            self._state.stage = Stage.COMPLETE if tail_start != Stage.ERROR else Stage.ERROR
            return {
                "ok": tail_start != Stage.ERROR,
                "decision": "complete" if tail_start != Stage.ERROR else "error",
                "message": "Planning graph has no post-Specimen tail to execute.",
            }
        planning_stages = self._planning_tail_stages(tail_start)
        if not planning_stages:
            planning_stages = {tail_start}
        cycle_context = {"cycle_index": cycle_index, "total_cycles": total_cycles}

        async def halt_for_control_flag() -> dict[str, Any]:
            reason = "safe_stop_requested" if self._state.safe_stop_requested else "stop_requested"
            self._state.stage = Stage.COMPLETE
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": (
                        "SYSTEM_EVENT: WORKFLOW_HALTED\n"
                        f"reason={reason}\n"
                        f"cycle={cycle_index}\n"
                        f"total_cycles={total_cycles}"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": True,
                    **cycle_context,
                },
                event_type="planning_handoff",
                message=f"Planning LangGraph tail halted by operator control flag: {reason}.",
                level="WARNING",
            )
            return {
                "ok": True,
                "decision": "stop",
                "message": f"Planning LangGraph handoff stopped because {reason} is set.",
            }

        if self._state.safe_stop_requested or self._state.stop_requested:
            return await halt_for_control_flag()

        async def planning_runtime_event(event: dict[str, Any]) -> None:
            nonlocal previous_label, guardian_payload
            await self._broadcast_event(event)
            event_type = str(event.get("type") or event.get("event_type") or "")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event_type == "orchestrator.followup":
                followup = payload.get("orchestrator_followup") if isinstance(payload.get("orchestrator_followup"), dict) else {}
                if followup:
                    await self._append_planning_message(
                        {
                            "schema": "live_chat_message.v1",
                            "role": "orchestrator",
                            "message_type": "warning" if followup.get("concerns") else "decision",
                            "content": self._format_orchestrator_followup_message(followup),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "model": "orchestrator_supervisor",
                            "ok": followup.get("status") != "error",
                            "graph_id": event.get("graph_id", ""),
                            "orchestrator_followup": followup,
                            "requires_response": bool(followup.get("requires_response")),
                            "evidence_refs": followup.get("evidence_refs", []),
                            **cycle_context,
                        },
                        event_type="planning_orchestrator_followup",
                        level=str(event.get("level") or "INFO"),
                        message="Orchestrator supervisor follow-up streamed from LangGraph runtime.",
                    )
                return
            if event_type == "orchestrator.loop_reflection":
                reflection = payload.get("loop_reflection") if isinstance(payload.get("loop_reflection"), dict) else {}
                if reflection:
                    await self._append_planning_message(
                        {
                            "schema": "live_chat_message.v1",
                            "role": "orchestrator",
                            "message_type": "decision",
                            "content": (
                                "Orchestrator loop reflection\n"
                                f"- summary: {reflection.get('operator_visible_summary', '-')}\n"
                                f"- next: {reflection.get('next_loop_recommendation', '-')}\n"
                                f"- near_miss: {self._runtime_value(reflection.get('what_failed_or_nearly_failed'))}"
                            ),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "model": "orchestrator_supervisor",
                            "ok": True,
                            "graph_id": event.get("graph_id", ""),
                            "loop_reflection": reflection,
                            **cycle_context,
                        },
                        event_type="planning_orchestrator_reflection",
                        message="Orchestrator loop reflection streamed from LangGraph runtime.",
                    )
                return
            raw_stage = str(payload.get("node_id") or event.get("node_id") or "")
            try:
                stage = Stage(raw_stage)
            except ValueError:
                return
            if stage not in planning_stages:
                return

            module_runtime = self._module_runtime_for_stage(stage, payload)
            agent_name = self._planning_agent_from_payload(payload)
            if event_type == "node.started":
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": self._planning_stage_handoff_text(previous_label, stage, module_runtime),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": True,
                        "graph_id": event.get("graph_id", ""),
                        "module_runtime": module_runtime,
                        **cycle_context,
                    },
                    event_type="planning_handoff",
                    message=f"Planning LangGraph handoff to {agent_name or stage.value} started.",
                )
                return

            if event_type == "node.failed":
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": (
                            "SYSTEM_EVENT: NODE_FAILED\n"
                            f"stage={stage.value}\n"
                            f"agent={agent_name or 'unknown'}\n"
                            f"error={payload.get('error') or event.get('message') or 'unknown'}"
                        ),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": False,
                        "graph_id": event.get("graph_id", ""),
                        "module_runtime": module_runtime,
                        **cycle_context,
                    },
                    event_type="planning_handoff",
                    level="ERROR",
                    message=f"Planning LangGraph node failed at {stage.value}.",
                )
                return

            if event_type != "node.completed":
                return
            data = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            if not data:
                return

            if stage == Stage.BO:
                await self._append_planning_message(
                    {
                        "role": "bo_ai",
                        "content": self._format_planning_bo_message(data),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "model": agent_name or "bo_agent",
                        "ok": True,
                        "bo_result": data.get("bo_result", {}),
                        "graph_id": event.get("graph_id", ""),
                        "module_runtime": module_runtime,
                        **cycle_context,
                    },
                    event_type="planning_bo_result",
                    message="BOAgent completed next design recommendation through LangGraph runtime.",
                )
                previous_label = self._planning_stage_label(stage, module_runtime)
                return

            content = self._format_planning_stage_message(stage, data, str(event.get("message") or ""))
            message_payload: dict[str, Any] = {
                "role": self._planning_stage_role(stage, module_runtime),
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": agent_name or stage.value,
                "ok": True,
                "graph_id": event.get("graph_id", ""),
                "module_runtime": module_runtime,
                **cycle_context,
                stage.value: data.get(stage.value, data),
            }
            if stage == Stage.VISION:
                observation = data.get("observation") if isinstance(data.get("observation"), dict) else {}
                vision_report = data.get("vision_report") if isinstance(data.get("vision_report"), dict) else observation.get("vision_report", {}) if isinstance(observation.get("vision_report"), dict) else {}
                vision_signal = data.get("vision_signal") if isinstance(data.get("vision_signal"), dict) else observation.get("vision_signal", {}) if isinstance(observation.get("vision_signal"), dict) else {}
                message_payload["schema"] = "live_chat_message.v1"
                message_payload["message_type"] = "signal"
                message_payload["signal_id"] = vision_signal.get("signal_id", "")
                message_payload["zone_id"] = vision_signal.get("zone_id", "")
                message_payload["confidence"] = vision_signal.get("confidence", None)
                message_payload["stability_ms"] = vision_signal.get("stable_for_ms", None)
                message_payload["vision_report"] = vision_report
                message_payload["vision_signal"] = vision_signal
                message_payload["agent_signals"] = vision_report.get("signal_board", []) if isinstance(vision_report.get("signal_board"), list) else []
            if stage == Stage.EQUIPMENT:
                equipment_report = data.get("equipment_report") if isinstance(data.get("equipment_report"), dict) else {}
                equipment_result = data.get("equipment_result") if isinstance(data.get("equipment_result"), dict) else {}
                utm_packet = data.get("utm_data_ready") if isinstance(data.get("utm_data_ready"), dict) else {}
                handoff_packet = data.get("equipment_handoff") if isinstance(data.get("equipment_handoff"), dict) else {}
                decision = equipment_report.get("decision") if isinstance(equipment_report.get("decision"), dict) else {}
                bridge = equipment_report.get("bridge") if isinstance(equipment_report.get("bridge"), dict) else {}
                data_ledger = equipment_report.get("data_ledger") if isinstance(equipment_report.get("data_ledger"), dict) else equipment_report.get("data_acquisition", {}) if isinstance(equipment_report.get("data_acquisition"), dict) else {}
                message_payload.update(
                    {
                        "schema": "live_chat_message.v1",
                        "message_type": "handoff" if decision.get("handoff_status") == "ready_for_analysis" else "warning",
                        "command_id": equipment_result.get("sequence_id") or handoff_packet.get("sequence_id") or "",
                        "windows_host": bridge.get("bridge_url_host") or bridge.get("host") or bridge.get("provider") or "",
                        "visual_assertion": equipment_report.get("visual_verification", {}),
                        "physical_cross_check": equipment_report.get("physical_verification", {}),
                        "data_file_ref": data_ledger.get("linux_path") or handoff_packet.get("result_file") or utm_packet.get("result_file") or "",
                        "data_ledger": data_ledger,
                        "recovery": equipment_report.get("recovery", {}),
                        "handoff_packet": utm_packet or handoff_packet,
                        "equipment_report": equipment_report,
                        "equipment_result": equipment_result,
                        "evidence_refs": utm_packet.get("evidence_refs", []) if isinstance(utm_packet.get("evidence_refs"), list) else [],
                    }
                )
            if stage == Stage.ANALYSIS:
                fem_artifacts = self._write_planning_fem_artifacts(experiment_spec, data)
                if fem_artifacts:
                    message_payload["fem_artifacts"] = fem_artifacts
                    message_payload["artifacts"] = {
                        "preview_url": fem_artifacts.get("contour_url", ""),
                        "experiment_spec_url": fem_artifacts.get("report_url", ""),
                    }
                    message_payload["experiment_spec"] = experiment_spec
            if stage == Stage.GUARDIAN:
                guardian_payload = data.get("guardian", {}) if isinstance(data.get("guardian", {}), dict) else {}
            await self._append_planning_message(
                message_payload,
                event_type=f"planning_{stage.value}_result",
                message=f"{agent_name or stage.value} completed through LangGraph runtime.",
            )
            previous_label = self._planning_stage_label(stage, module_runtime)

        try:
            self._state.mode = effective_mode
            self._state.current_experiment_spec = experiment_spec
            self._state.stage = tail_start
            loop = RunLoop(
                state=self._state,
                agent_registry=self._deps.agent_registry,
                orchestrator_agent_name=self._deps.orchestrator_agent_name,
                ctx=self._deps.agent_context,
                logger=self._logger_bundle.logger,
                max_retry_per_stage=int(self._deps.system_config.get("max_retry_per_stage", 2)),
                interval_seconds=0.0,
                graph_config_path=self._active_graph_config_path,
                on_event=planning_runtime_event,
            )
            max_steps = max(16, len(planning_stages) * 4)
            for _ in range(max_steps):
                before_stage = self._state.stage
                await loop.step()
                if self._state.safe_stop_requested or self._state.stop_requested:
                    return await halt_for_control_flag()
                if self._state.is_paused:
                    return {
                        "ok": True,
                        "decision": "pending_operator_approval",
                        "message": "Planning LangGraph tail is waiting for runtime approval.",
                    }
                if (Stage.GUARDIAN in planning_stages and before_stage == Stage.GUARDIAN) or self._state.stage in {Stage.DESIGN, Stage.COMPLETE, Stage.ERROR}:
                    break
            else:
                raise RuntimeError("Planning LangGraph tail exceeded max_steps without reaching Guardian/terminal stage.")

            decision = str(guardian_payload.get("decision", "continue")).strip() or "continue"
            planned_final_stop = decision == "stop" and effective_mode == Mode.TEST and cycle_index >= total_cycles
            if self._state.stage == Stage.ERROR or decision == "error":
                self._state.stage = Stage.ERROR
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": f"SYSTEM_EVENT: WORKFLOW_HALTED\nagent=GuardianAgent\ndecision={decision}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": False,
                        **cycle_context,
                    },
                    event_type="planning_handoff",
                    message="Planning LangGraph tail halted by Guardian decision.",
                    level="ERROR",
                )
            elif planned_final_stop or cycle_index >= total_cycles:
                self._state.stage = Stage.COMPLETE
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": f"SYSTEM_EVENT: WORKFLOW_COMPLETE\nstatus=passed_guardian\ncycle={cycle_index}\ntotal_cycles={total_cycles}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": True,
                        **cycle_context,
                    },
                    event_type="planning_handoff",
                    message="Planning LangGraph tail completed.",
                )
            elif decision == "stop":
                self._state.stage = Stage.COMPLETE
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": f"SYSTEM_EVENT: WORKFLOW_HALTED\nagent=GuardianAgent\ndecision={decision}\ncycle={cycle_index}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": True,
                        **cycle_context,
                    },
                    event_type="planning_handoff",
                    message="Planning LangGraph tail halted by Guardian decision.",
                    level="WARNING",
                )
            else:
                self._state.stage = Stage.DESIGN
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": f"SYSTEM_EVENT: CYCLE_COMPLETE\ncycle={cycle_index}\ntotal_cycles={total_cycles}\nstatus=next_design",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": True,
                        **cycle_context,
                    },
                    event_type="planning_handoff",
                    message="Planning LangGraph cycle completed; next design cycle queued.",
                )
            return {
                "ok": decision != "error" and self._state.stage != Stage.ERROR,
                "decision": decision,
                "message": f"Planning LangGraph handoff cycle {cycle_index}/{total_cycles} completed.",
            }
        finally:
            self._state.mode = original_mode

    async def _run_specimen_guardian_tail(self, experiment_spec: dict[str, Any]) -> dict[str, Any]:
        await self._append_planning_message(
            {
                "role": "system",
                "content": "SYSTEM_EVENT: HANDOFF\nfrom=OperatorInput\nto=SpecimenMakingAgent\nstatus=retry",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": True,
            },
            event_type="planning_handoff",
            message="Planning handoff back to Specimen Making Agent started.",
        )
        specimen = await self._run_planning_specimen_stage(experiment_spec, emit_handoff=False)
        if specimen.get("pending"):
            return {"ok": True, "message": "SpecimenMakingAgent waiting for operator input."}

        constraints = experiment_spec.get("constraints") if isinstance(experiment_spec.get("constraints"), dict) else {}
        return await self._run_planning_cycle_series(
            first_spec=experiment_spec,
            design_constraints={**constraints, **experiment_spec},
            start_cycle=1,
        )

    def _build_planning_spec(
        self,
        *,
        base_spec: dict[str, Any],
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        """Adapt current DesignAgent output into a specimen-design planning spec."""
        def pick(key: str, default: Any) -> Any:
            return constraints.get(key, base_spec.get(key, default))

        candidate_id = str(base_spec.get("candidate_id", f"cand-{self._state.loop_count + 1}"))
        size = constraints.get("specimen_size_mm", constraints.get("max_specimen_size_mm", base_spec.get("specimen_size_mm", [30.0, 30.0, 30.0])))
        if not isinstance(size, list) or len(size) != 3:
            size = [30.0, 30.0, 30.0]
        specimen_size = [float(item) for item in size]
        validated_defaults = self._validated_printer_defaults()
        test_handoff = bool(constraints.get("test_mode_autofill") or constraints.get("test_mode_llm_generated"))
        print_constraints = constraints.get("print") if isinstance(constraints.get("print"), dict) else {}
        if "start_immediately" in print_constraints:
            requested_live_start = bool(print_constraints.get("start_immediately"))
        else:
            requested_live_start = bool(pick("start_immediately_live", validated_defaults.get("start_immediately_live", True)))
        live_physical_print = self._state.mode == Mode.LIVE and not test_handoff and requested_live_start
        default_cell_size_mm = 10.0 if self._state.mode == Mode.TEST or test_handoff else 5.0
        max_print_time_min = float(pick("max_print_time_min", validated_defaults.get("max_print_time_min", 120.0)))
        geometry_type = (
            self._normalize_planning_geometry_type(pick("geometry_type", ""))
            or self._normalize_planning_geometry_type(base_spec.get("geometry_type"))
            or (self.TEST_MODE_FIXED_GEOMETRY if self._state.mode == Mode.TEST else "gyroid")
        )
        base_geometry_type = self._normalize_planning_geometry_type(base_spec.get("geometry_type"))
        digest = hashlib.sha1(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "geometry_type": geometry_type,
                    "size": specimen_size,
                    "run_id": self._state.run_id,
                    "cell_size_mm": pick("cell_size_mm", default_cell_size_mm),
                    "wall_thickness_mm": pick("wall_thickness_mm", 1.0),
                    "relative_density": pick("relative_density", 0.35),
                    "anisotropy_ratio": pick("anisotropy_ratio", 1.0),
                    "orientation_deg": pick("orientation_deg", 0.0),
                    "tpms_thickness": pick("tpms_thickness", base_spec.get("tpms_thickness")),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:8]
        base_specimen_id = str(base_spec.get("specimen_id") or "")
        if base_specimen_id and (not base_geometry_type or base_geometry_type == geometry_type):
            specimen_id = base_specimen_id
        else:
            specimen_id = f"specimen-{candidate_id}-{geometry_type}-{digest}"
        planning_spec = {
            **base_spec,
            "candidate_id": candidate_id,
            "specimen_id": specimen_id,
            "objective_type": str(pick("objective_type", "maximize_energy_absorption_per_mass")),
            "objective_direction": str(pick("objective_direction", "maximize")),
            "geometry_type": geometry_type,
            "specimen_size_mm": specimen_size,
            "cell_size_mm": float(pick("cell_size_mm", default_cell_size_mm)),
            "wall_thickness_mm": float(pick("wall_thickness_mm", 1.0)),
            "relative_density": float(pick("relative_density", 0.35)),
            "porosity": float(pick("porosity", 0.65)),
            "anisotropy_ratio": float(pick("anisotropy_ratio", 1.0)),
            "orientation_deg": float(pick("orientation_deg", 0.0)),
            "defect_seed": int(pick("defect_seed", self._state.loop_count + 1)),
            "defect_ratio": float(pick("defect_ratio", 0.0)),
            "skin_thickness_mm": float(pick("skin_thickness_mm", validated_defaults.get("skin_thickness_mm", 0.8))),
            "top_cap_enabled": bool(pick("top_cap_enabled", validated_defaults.get("top_cap_enabled", False))),
            "bottom_cap_enabled": bool(pick("bottom_cap_enabled", validated_defaults.get("bottom_cap_enabled", True))),
            "top_bottom_cap": bool(pick("top_bottom_cap", validated_defaults.get("top_bottom_cap", True))),
            "skirt_enabled": bool(pick("skirt_enabled", validated_defaults.get("skirt_enabled", False))),
            "require_flat_compression_faces": bool(
                pick(
                    "require_flat_compression_faces",
                    validated_defaults.get("require_flat_compression_faces", False),
                )
            ),
            "fdm_min_wall_thickness_mm": float(pick("fdm_min_wall_thickness_mm", 1.2)),
            "fdm_max_bridge_distance_mm": float(pick("fdm_max_bridge_distance_mm", 10.0)),
            "fdm_max_unsupported_overhang_deg": float(pick("fdm_max_unsupported_overhang_deg", 45.0)),
            "fdm_max_gyroid_wall_cell_ratio": float(pick("fdm_max_gyroid_wall_cell_ratio", 0.28)),
            "material": str(pick("material", validated_defaults.get("material", "PLA"))),
            "printer_model": str(pick("printer_model", validated_defaults["printer_model"])),
            "printer_profile": str(pick("printer_profile", validated_defaults["printer_profile"])),
            "slicer_profile_hint": str(pick("slicer_profile_hint", validated_defaults["slicer_profile_hint"])),
            "layer_height_mm": float(pick("layer_height_mm", validated_defaults["layer_height_mm"])),
            "first_layer_height_mm": float(pick("first_layer_height_mm", validated_defaults.get("first_layer_height_mm", pick("layer_height_mm", validated_defaults["layer_height_mm"])))),
            "slow_first_layer_enabled": bool(pick("slow_first_layer_enabled", validated_defaults.get("slow_first_layer_enabled", True))),
            "first_layer_speed_mm_s": float(pick("first_layer_speed_mm_s", validated_defaults.get("first_layer_speed_mm_s", 10.0))),
            "bed_temperature_c": float(pick("bed_temperature_c", validated_defaults.get("bed_temperature_c", 60.0))),
            "first_layer_bed_temperature_c": float(
                pick("first_layer_bed_temperature_c", validated_defaults.get("first_layer_bed_temperature_c", validated_defaults.get("bed_temperature_c", 60.0)))
            ),
            "nozzle_diameter_mm": float(pick("nozzle_diameter_mm", validated_defaults["nozzle_diameter_mm"])),
            "storage": str(pick("storage", validated_defaults["storage"])),
            "max_print_time_min": max_print_time_min,
            "expected_mass_g": round(float(pick("expected_mass_g", 18.0)), 3),
            "expected_volume_mm3": round(float(pick("expected_volume_mm3", 14500.0)), 3),
            "expected_print_time_min": round(float(pick("expected_print_time_min", max_print_time_min * 0.62)), 2),
            "expected_manufacturability_score": float(pick("expected_manufacturability_score", 0.82)),
            "expected_objective_proxy_score": float(pick("expected_objective_proxy_score", 0.74)),
            "generation_strategy": str(pick("generation_strategy", "planning_chat_design_agent_with_artifact_adaptation")),
            "generation_reason": str(pick("generation_reason", "Operator requested experiment execution from planning chat.")),
            "print": {
                **(
                    {
                        "storage": validated_defaults["storage"],
                        "overwrite": bool(pick("overwrite", validated_defaults.get("overwrite", True))),
                    }
                    | print_constraints
                ),
                "storage": str(pick("storage", validated_defaults["storage"])),
                "skirt_enabled": bool(pick("skirt_enabled", validated_defaults.get("skirt_enabled", False))),
                "start_immediately": bool(live_physical_print),
                "physical_intent": bool(live_physical_print),
                "confirm_physical_print": bool(live_physical_print),
            },
            "ejection": {
                **(constraints.get("ejection") if isinstance(constraints.get("ejection"), dict) else {}),
                "enabled": bool(validated_defaults.get("allow_ejection", False)),
            },
        }
        explicit_top_cap = "top_cap_enabled" in constraints or "top_cap_enabled" in base_spec
        explicit_bottom_cap = "bottom_cap_enabled" in constraints or "bottom_cap_enabled" in base_spec
        explicit_legacy_cap = "top_bottom_cap" in constraints or "top_bottom_cap" in base_spec
        if explicit_top_cap or explicit_bottom_cap:
            planning_spec["top_cap_enabled"] = bool(planning_spec.get("top_cap_enabled", False))
            planning_spec["bottom_cap_enabled"] = bool(planning_spec.get("bottom_cap_enabled", False))
        elif explicit_legacy_cap:
            legacy_cap = bool(planning_spec.get("top_bottom_cap", validated_defaults.get("top_bottom_cap", True)))
            planning_spec["top_cap_enabled"] = False
            planning_spec["bottom_cap_enabled"] = legacy_cap
        else:
            planning_spec["top_cap_enabled"] = bool(validated_defaults.get("top_cap_enabled", False))
            planning_spec["bottom_cap_enabled"] = bool(validated_defaults.get("bottom_cap_enabled", True))
        planning_spec["top_bottom_cap"] = bool(planning_spec["top_cap_enabled"] or planning_spec["bottom_cap_enabled"])
        if planning_spec["geometry_type"] == "gyroid" and planning_spec["relative_density"] < 0.20:
            planning_spec["relative_density"] = 0.20
            nested_constraints = planning_spec.get("constraints") if isinstance(planning_spec.get("constraints"), dict) else {}
            planning_spec["constraints"] = {**nested_constraints, "relative_density": 0.20}
        if planning_spec["top_bottom_cap"]:
            planning_spec["skin_thickness_mm"] = max(0.2, float(planning_spec.get("skin_thickness_mm") or 0.8))
            planning_spec["require_flat_compression_faces"] = bool(
                planning_spec.get("require_flat_compression_faces", False)
                and planning_spec["top_cap_enabled"]
                and planning_spec["bottom_cap_enabled"]
            )
        else:
            planning_spec["skin_thickness_mm"] = 0.0
            planning_spec["require_flat_compression_faces"] = False
        if geometry_type == "gyroid":
            wall_ratio = planning_spec["wall_thickness_mm"] / max(planning_spec["cell_size_mm"], 1e-6)
            physical_min = max(
                0.18,
                min(0.68, 0.50 * planning_spec["wall_thickness_mm"] * (6.283185307179586 / max(planning_spec["cell_size_mm"], 1e-6))),
            )
            default_tpms_thickness = max(
                physical_min,
                min(0.68, 0.10 + 0.40 * planning_spec["relative_density"] + min(0.06, 0.20 * wall_ratio)),
            )
            planning_spec["tpms_surface"] = str(pick("tpms_surface", planning_spec.get("tpms_surface", "gyroid")))
            planning_spec["tpms_thickness"] = float(pick("tpms_thickness", planning_spec.get("tpms_thickness", default_tpms_thickness)))
            planning_spec["tpms_resolution"] = int(pick("tpms_resolution", planning_spec.get("tpms_resolution", 72)))
            planning_spec["printability_mode"] = str(pick("printability_mode", planning_spec.get("printability_mode", "fdm_closed_shell")))
        # Preserve Live GUI test-mode handoff markers across the DesignAgent
        # adaptation step so SpecimenMakingAgent can request the printer path.
        passthrough_keys = (
            "test_mode_autofill",
            "test_mode_llm_generated",
            "printer_test_path",
            "test_printer_path",
            "printer_bridge_mode",
            "printer_test_mode",
            "test_printer_transport",
            "allow_test_printer_live",
        )
        for key in passthrough_keys:
            if key in constraints:
                planning_spec[key] = constraints[key]
            elif key in base_spec:
                planning_spec[key] = base_spec[key]
        return planning_spec

    def _write_planning_artifacts(
        self,
        experiment_spec: dict[str, Any],
        *,
        specimen_result: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Create planning artifacts and prefer real specimen results when available."""
        specimen_id = self._safe_artifact_segment(str(experiment_spec["specimen_id"]))
        artifact_dir = self._deps.run_root / self._state.run_id / "planning" / specimen_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        stl_path = artifact_dir / "specimen.stl"
        preview_path = artifact_dir / "specimen_preview.svg"
        spec_path = artifact_dir / "experiment_spec.json"
        specimen_paths = specimen_result or {}
        source_stl = None
        source_preview = None
        source_stl_candidate = specimen_paths.get("stl_path")
        source_preview_candidate = specimen_paths.get("preview_image_path")
        if isinstance(source_stl_candidate, str) and source_stl_candidate.strip():
            source_stl = Path(source_stl_candidate).expanduser()
        if isinstance(source_preview_candidate, str) and source_preview_candidate.strip():
            source_preview = Path(source_preview_candidate).expanduser()

        if source_stl is None or not source_stl.exists():
            source_stl = stl_path
            self._write_planning_stl(source_stl, experiment_spec)
        if source_preview is None or not source_preview.exists():
            source_preview = preview_path
            source_preview.write_text(self._preview_svg(experiment_spec), encoding="utf-8")

        if source_stl != stl_path:
            shutil.copy2(source_stl, stl_path)
        if source_preview != preview_path:
            shutil.copy2(source_preview, preview_path)

        spec_path.write_text(json.dumps(experiment_spec, ensure_ascii=True, indent=2), encoding="utf-8")

        base = f"/api/planning/artifacts/{self._state.run_id}/{specimen_id}"
        return {
            "stl_path": str(stl_path),
            "preview_image_path": str(preview_path),
            "experiment_spec_path": str(spec_path),
            "stl_url": f"{base}/specimen.stl",
            "preview_url": f"{base}/specimen_preview.svg",
            "experiment_spec_url": f"{base}/experiment_spec.json",
        }

    def _write_planning_fem_artifacts(
        self,
        experiment_spec: dict[str, Any],
        analysis_data: dict[str, Any],
    ) -> dict[str, str]:
        """Copy CAE/FEM contour artifacts into the planning artifact directory."""
        analysis = analysis_data.get("analysis") if isinstance(analysis_data.get("analysis"), dict) else {}
        cae_result = analysis.get("cae_result") if isinstance(analysis.get("cae_result"), dict) else {}
        artifacts = cae_result.get("artifacts") if isinstance(cae_result.get("artifacts"), dict) else {}
        source_contour = Path(str(artifacts.get("contour_svg_path") or "")).expanduser()
        if not source_contour.exists():
            return {}
        specimen_id = self._safe_artifact_segment(str(experiment_spec["specimen_id"]))
        artifact_dir = self._deps.run_root / self._state.run_id / "planning" / specimen_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        contour_path = artifact_dir / "fem_contour.svg"
        shutil.copy2(source_contour, contour_path)
        source_report = Path(str(artifacts.get("report_path") or "")).expanduser()
        report_path = artifact_dir / "cae_report.json"
        if source_report.exists():
            shutil.copy2(source_report, report_path)
        base = f"/api/planning/artifacts/{self._state.run_id}/{specimen_id}"
        return {
            "contour_svg_path": str(contour_path),
            "contour_url": f"{base}/fem_contour.svg",
            "report_path": str(report_path) if report_path.exists() else "",
            "report_url": f"{base}/cae_report.json" if report_path.exists() else "",
        }

    @staticmethod
    def _write_planning_stl(stl_path: Path, experiment_spec: dict[str, Any]) -> None:
        """Write planning STL with the same smooth/cleanup path as specimen generation."""
        geometry = str(experiment_spec.get("geometry_type", "")).strip()
        name = str(experiment_spec.get("specimen_id", "specimen"))
        size = experiment_spec.get("specimen_size_mm", [30.0, 30.0, 30.0])
        if geometry == "gyroid":
            metadata = write_smooth_gyroid_stl(
                stl_path=stl_path,
                name=name,
                specimen_size_mm=size,
                cell_size_mm=float(experiment_spec.get("cell_size_mm", 5.0)),
                wall_thickness_mm=float(experiment_spec.get("wall_thickness_mm", 1.2)),
                relative_density=float(experiment_spec.get("relative_density", 0.32)),
                anisotropy_ratio=float(experiment_spec.get("anisotropy_ratio", 1.0)),
                orientation_deg=float(experiment_spec.get("orientation_deg", 0.0)),
                defect_seed=int(experiment_spec.get("defect_seed", 1)),
                defect_ratio=float(experiment_spec.get("defect_ratio", 0.0)),
                skin_thickness_mm=float(experiment_spec.get("skin_thickness_mm", 0.0)),
                top_bottom_cap=bool(experiment_spec.get("top_bottom_cap", False)),
                top_cap_enabled=experiment_spec.get("top_cap_enabled"),
                bottom_cap_enabled=experiment_spec.get("bottom_cap_enabled"),
                tpms_thickness=experiment_spec.get("tpms_thickness"),
                resolution=max(72, min(96, int(experiment_spec.get("tpms_resolution", 72) or 72))),
            )
            if metadata is not None:
                return
        stl_path.write_text(MainController._planning_stl(experiment_spec), encoding="utf-8")

    @staticmethod
    def _safe_artifact_segment(value: str) -> str:
        """Return a filesystem and URL-safe artifact path segment."""
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip(".-")
        return safe or "artifact"

    @staticmethod
    def _planning_stl(experiment_spec: dict[str, Any]) -> str:
        """Generate a lightweight ASCII STL that reflects the selected planning geometry."""
        geometry = str(experiment_spec.get("geometry_type", "")).strip()
        name = str(experiment_spec.get("specimen_id", "specimen"))
        size = experiment_spec.get("specimen_size_mm", [30.0, 30.0, 30.0])
        if geometry == "gyroid":
            stl_text, _metadata = generate_gyroid_stl_text(
                name=name,
                specimen_size_mm=size,
                cell_size_mm=float(experiment_spec.get("cell_size_mm", 7.5)),
                wall_thickness_mm=float(experiment_spec.get("wall_thickness_mm", 1.2)),
                relative_density=float(experiment_spec.get("relative_density", 0.32)),
                anisotropy_ratio=float(experiment_spec.get("anisotropy_ratio", 1.0)),
                orientation_deg=float(experiment_spec.get("orientation_deg", 0.0)),
                defect_seed=int(experiment_spec.get("defect_seed", 1)),
                defect_ratio=float(experiment_spec.get("defect_ratio", 0.0)),
                skin_thickness_mm=float(experiment_spec.get("skin_thickness_mm", 0.0)),
                top_bottom_cap=bool(experiment_spec.get("top_bottom_cap", False)),
                top_cap_enabled=experiment_spec.get("top_cap_enabled"),
                bottom_cap_enabled=experiment_spec.get("bottom_cap_enabled"),
                tpms_thickness=experiment_spec.get("tpms_thickness"),
                resolution=max(72, min(96, int(experiment_spec.get("tpms_resolution", 72) or 72))),
            )
            return stl_text
        if geometry == "auxetic_reentrant":
            return MainController._auxetic_reentrant_stl(
                name=name,
                size=size,
                cell_size=float(experiment_spec.get("cell_size_mm", 7.5)),
                wall=float(experiment_spec.get("wall_thickness_mm", 1.2)),
                cap=bool(experiment_spec.get("top_bottom_cap", False)),
            )
        if geometry.startswith("lattice"):
            return MainController._lattice_stl(
                name=name,
                size=size,
                cell_size=float(experiment_spec.get("cell_size_mm", 7.5)),
                wall=float(experiment_spec.get("wall_thickness_mm", 1.2)),
                cap=bool(experiment_spec.get("top_bottom_cap", False)),
            )
        return MainController._box_stl(name, size)

    @staticmethod
    def _box_stl(name: str, size: list[float]) -> str:
        """Generate a simple ASCII STL box placeholder for planning visualization."""
        x, y, z = [max(float(item), 1.0) for item in size]
        return MainController._cuboids_stl(name, [(-x / 2.0, x / 2.0, -y / 2.0, y / 2.0, -z / 2.0, z / 2.0)])

    @staticmethod
    def _lattice_stl(*, name: str, size: Any, cell_size: float, wall: float, cap: bool) -> str:
        """Generate an axis-strut BCC-style lattice STL for immediate planning visualization."""
        x, y, z = [max(float(item), 1.0) for item in MainController._vector3_value(size, [30.0, 30.0, 30.0])]
        hx, hy, hz = x / 2.0, y / 2.0, z / 2.0
        strut = max(0.6, min(float(wall), min(x, y, z) / 8.0))
        cell = max(float(cell_size), strut * 3.0)
        cells = max(2, min(4, round(min(x, y, z) / cell)))

        def positions(length: float) -> list[float]:
            half = length / 2.0
            step = length / cells
            return [round(-half + step * idx, 6) for idx in range(cells + 1)]

        xs = positions(x)
        ys = positions(y)
        zs = positions(z)

        def clipped(center: float, half_width: float, low: float, high: float) -> tuple[float, float]:
            return max(low, center - half_width), min(high, center + half_width)

        cuboids: list[tuple[float, float, float, float, float, float]] = []
        h = strut / 2.0
        for yy in ys:
            y0, y1 = clipped(yy, h, -hy, hy)
            for zz in zs:
                z0, z1 = clipped(zz, h, -hz, hz)
                cuboids.append((-hx, hx, y0, y1, z0, z1))
        for xx in xs:
            x0, x1 = clipped(xx, h, -hx, hx)
            for zz in zs:
                z0, z1 = clipped(zz, h, -hz, hz)
                cuboids.append((x0, x1, -hy, hy, z0, z1))
        for xx in xs:
            x0, x1 = clipped(xx, h, -hx, hx)
            for yy in ys:
                y0, y1 = clipped(yy, h, -hy, hy)
                cuboids.append((x0, x1, y0, y1, -hz, hz))
        if cap:
            cap_thickness = max(0.6, min(strut, z / 12.0))
            cuboids.append((-hx, hx, -hy, hy, -hz, -hz + cap_thickness))
            cuboids.append((-hx, hx, -hy, hy, hz - cap_thickness, hz))
        return MainController._cuboids_stl(name, cuboids)

    @staticmethod
    def _auxetic_reentrant_stl(*, name: str, size: Any, cell_size: float, wall: float, cap: bool) -> str:
        """Generate a lightweight re-entrant auxetic (zigzag ligament) STL."""
        x, y, z = [max(float(item), 1.0) for item in MainController._vector3_value(size, [30.0, 30.0, 30.0])]
        hx, hy, hz = x / 2.0, y / 2.0, z / 2.0
        strut = max(0.6, min(float(wall), min(x, y, z) / 10.0))
        cell = max(float(cell_size), strut * 4.0)
        cols = max(2, min(6, round(x / cell)))
        rows = max(2, min(6, round(y / cell)))
        pitch_x = x / cols
        pitch_y = y / rows
        amp = max(strut * 1.2, min(pitch_x * 0.28, pitch_y * 0.28))
        amp = min(amp, pitch_x * 0.4)

        z0, z1 = -hz, hz
        cuboids: list[tuple[float, float, float, float, float, float]] = []
        bounds = (-hx, hx, -hy, hy)

        def add_segment(x0: float, y0: float, x1: float, y1: float, *, steps: int = 1) -> None:
            MainController._append_xy_segment_cuboids(
                cuboids=cuboids,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                strut=strut,
                z0=z0,
                z1=z1,
                steps=steps,
                bounds=bounds,
            )

        # Perimeter frame.
        add_segment(-hx, -hy, hx, -hy)
        add_segment(-hx, hy, hx, hy)
        add_segment(-hx, -hy, -hx, hy)
        add_segment(hx, -hy, hx, hy)

        base_x = [(-hx + pitch_x * idx) for idx in range(cols + 1)]
        row_nodes: list[tuple[float, list[float]]] = []
        for row in range(rows + 1):
            y_coord = -hy + pitch_y * row
            shift = amp if row % 2 else -amp
            nodes: list[float] = []
            for col, x_coord in enumerate(base_x):
                shifted = x_coord
                if 0 < col < cols:
                    shifted += shift
                shifted = max(-hx + strut * 0.7, min(hx - strut * 0.7, shifted))
                nodes.append(shifted)
            row_nodes.append((y_coord, nodes))

        # Horizontal ligaments in each row.
        for y_coord, nodes in row_nodes:
            for col in range(cols):
                add_segment(nodes[col], y_coord, nodes[col + 1], y_coord)

        # Re-entrant diagonals between alternating rows.
        for row in range(rows):
            y0_row, nodes0 = row_nodes[row]
            y1_row, nodes1 = row_nodes[row + 1]
            for col in range(1, cols):
                add_segment(nodes0[col], y0_row, nodes1[col], y1_row, steps=4)

        if cap:
            cap_thickness = max(0.6, min(strut, z / 14.0))
            cuboids.append((-hx, hx, -hy, hy, -hz, -hz + cap_thickness))
            cuboids.append((-hx, hx, -hy, hy, hz - cap_thickness, hz))

        return MainController._cuboids_stl(name, cuboids)

    @staticmethod
    def _append_xy_segment_cuboids(
        *,
        cuboids: list[tuple[float, float, float, float, float, float]],
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        strut: float,
        z0: float,
        z1: float,
        steps: int,
        bounds: tuple[float, float, float, float],
    ) -> None:
        """Append one XY segment (optionally staircase-subdivided) as cuboids."""
        min_x, max_x, min_y, max_y = bounds
        parts = max(1, int(steps))
        for idx in range(parts):
            t0 = idx / parts
            t1 = (idx + 1) / parts
            xa = x0 + (x1 - x0) * t0
            xb = x0 + (x1 - x0) * t1
            ya = y0 + (y1 - y0) * t0
            yb = y0 + (y1 - y0) * t1
            cx = (xa + xb) / 2.0
            cy = (ya + yb) / 2.0
            lx = abs(xb - xa) + strut
            ly = abs(yb - ya) + strut

            ax0 = max(min_x, cx - lx / 2.0)
            ax1 = min(max_x, cx + lx / 2.0)
            ay0 = max(min_y, cy - ly / 2.0)
            ay1 = min(max_y, cy + ly / 2.0)
            if (ax1 - ax0) < 0.05 or (ay1 - ay0) < 0.05 or (z1 - z0) < 0.05:
                continue
            cuboids.append((ax0, ax1, ay0, ay1, z0, z1))

    @staticmethod
    def _cuboids_stl(name: str, cuboids: list[tuple[float, float, float, float, float, float]]) -> str:
        """Generate one ASCII STL from multiple axis-aligned cuboids."""
        lines = [f"solid {name}"]
        for cuboid in cuboids:
            lines.extend(MainController._cuboid_facets(*cuboid))
        lines.append(f"endsolid {name}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _cuboid_facets(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[str]:
        """Return ASCII STL facets for one axis-aligned cuboid."""
        v = [
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
        ]
        faces = [
            (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
            (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
            (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0),
        ]
        lines: list[str] = []
        for a, b, c in faces:
            lines.extend(
                [
                    "  facet normal 0 0 0",
                    "    outer loop",
                    f"      vertex {v[a][0]:.6f} {v[a][1]:.6f} {v[a][2]:.6f}",
                    f"      vertex {v[b][0]:.6f} {v[b][1]:.6f} {v[b][2]:.6f}",
                    f"      vertex {v[c][0]:.6f} {v[c][1]:.6f} {v[c][2]:.6f}",
                    "    endloop",
                    "  endfacet",
                ]
            )
        return lines

    @staticmethod
    def _vector3_value(value: Any, default: list[float]) -> list[float]:
        """Convert a loose value into a numeric 3-vector."""
        if not isinstance(value, list) or len(value) != 3:
            return list(default)
        out: list[float] = []
        for idx, item in enumerate(value):
            try:
                out.append(float(item))
            except (TypeError, ValueError):
                out.append(float(default[idx]))
        return out

    @staticmethod
    def _preview_svg(experiment_spec: dict[str, Any]) -> str:
        """Create a lightweight SVG preview card for chat display."""
        specimen_id = str(experiment_spec.get("specimen_id", "specimen"))
        geometry = str(experiment_spec.get("geometry_type", "geometry"))
        size = experiment_spec.get("specimen_size_mm", [30, 30, 30])
        density = max(0.05, min(0.85, float(experiment_spec.get("relative_density", 0.32) or 0.32)))
        wall = max(0.05, float(experiment_spec.get("wall_thickness_mm", 1.2) or 1.2))
        orientation = float(experiment_spec.get("orientation_deg", 0.0) or 0.0)
        tpms_t = float(experiment_spec.get("tpms_thickness", 0.0) or 0.0)
        if geometry.startswith("lattice"):
            internal = """
  <g stroke="#1436b3" stroke-width="3" opacity="0.72">
    <path d="M92 108 H310 M92 160 H310 M92 212 H310 M92 264 H310"/>
    <path d="M92 108 V264 M146 108 V264 M200 108 V264 M254 108 V264 M310 108 V264"/>
    <path d="M345 124 L430 170 M345 176 L430 222 M345 228 L430 274"/>
    <path d="M310 108 L395 154 M310 160 L395 206 M310 212 L395 258"/>
    <path d="M92 108 L177 154 M146 108 L231 154 M200 108 L285 154 M254 108 L339 154"/>
  </g>
"""
        elif geometry == "auxetic_reentrant":
            internal = """
  <g stroke="#1436b3" stroke-width="3" opacity="0.78" fill="none">
    <path d="M92 110 L146 146 L200 110 L254 146 L310 110"/>
    <path d="M92 164 L146 200 L200 164 L254 200 L310 164"/>
    <path d="M92 218 L146 254 L200 218 L254 254 L310 218"/>
    <path d="M146 146 L146 200 M200 110 L200 164 M254 146 L254 200"/>
    <path d="M345 126 L396 160 L430 126 M345 182 L396 216 L430 182 M345 238 L396 272 L430 238"/>
  </g>
"""
        elif geometry == "gyroid":
            stroke = round(1.8 + density * 5.0 + min(1.6, wall * 0.25), 2)
            amp = round(34.0 + density * 34.0 + min(12.0, tpms_t * 18.0), 2)
            phase = round((orientation % 90.0) / 90.0 * 42.0, 2)
            internal = f"""
  <g stroke="#1436b3" stroke-width="{stroke}" opacity="0.78" fill="none" stroke-linecap="round">
    <path d="M92 {128 - phase * 0.20:.1f} C138 {128 - amp:.1f} 184 {128 + amp:.1f} 230 {128 - phase * 0.10:.1f} S320 {128 - amp:.1f} 366 {128 + phase * 0.15:.1f}"/>
    <path d="M92 {180 + phase * 0.08:.1f} C138 {180 - amp * 0.82:.1f} 184 {180 + amp * 0.82:.1f} 230 {180 + phase * 0.10:.1f} S320 {180 - amp * 0.82:.1f} 366 {180 - phase * 0.12:.1f}"/>
    <path d="M92 {232 + phase * 0.18:.1f} C138 {232 - amp * 0.72:.1f} 184 {232 + amp * 0.72:.1f} 230 {232 + phase * 0.16:.1f} S320 {232 - amp * 0.72:.1f} 366 {232 - phase * 0.20:.1f}"/>
    <path d="M112 {108 + phase * 0.28:.1f} C168 {164 - amp * 0.22:.1f} 252 {74 + phase * 0.20:.1f} 312 {130 + amp * 0.15:.1f} S388 {230 - phase * 0.18:.1f} 430 {168 + phase * 0.24:.1f}"/>
    <path d="M128 {270 - phase * 0.25:.1f} C186 {214 + amp * 0.12:.1f} 250 {304 - phase * 0.16:.1f} 318 {244 - amp * 0.10:.1f} S392 {144 + phase * 0.18:.1f} 430 {210 - phase * 0.20:.1f}"/>
    <path d="M345 {126 + phase * 0.18:.1f} C384 {96 + amp * 0.08:.1f} 406 {178 - phase * 0.18:.1f} 430 {148 + phase * 0.12:.1f} M345 {190 - phase * 0.14:.1f} C384 {160 + amp * 0.08:.1f} 406 {242 - phase * 0.14:.1f} 430 {212 + phase * 0.10:.1f} M345 {252 + phase * 0.10:.1f} C384 {222 + amp * 0.08:.1f} 406 {304 - phase * 0.10:.1f} 430 {274 - phase * 0.08:.1f}"/>
  </g>
"""
        else:
            internal = ""
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="420" viewBox="0 0 720 420">
  <rect width="720" height="420" rx="28" fill="#f5f8ff"/>
  <rect x="70" y="80" width="260" height="220" rx="18" fill="#dfe9ff" fill-opacity="0.42" stroke="#1436b3" stroke-width="4"/>
  <path d="M330 80 L430 135 L430 350 L330 300 Z" fill="#b9ccff" fill-opacity="0.42" stroke="#1436b3" stroke-width="4"/>
  <path d="M70 80 L170 135 L430 135 L330 80 Z" fill="#edf3ff" fill-opacity="0.7" stroke="#1436b3" stroke-width="4"/>
{internal}
  <text x="470" y="135" font-family="monospace" font-size="22" fill="#1436b3">{geometry}</text>
  <text x="470" y="176" font-family="monospace" font-size="16" fill="#091225">{specimen_id}</text>
  <text x="470" y="215" font-family="monospace" font-size="16" fill="#5a6883">size={size}</text>
  <text x="470" y="252" font-family="monospace" font-size="16" fill="#5a6883">rho={density:.3f} wall={wall:.3f}</text>
  <text x="470" y="289" font-family="monospace" font-size="16" fill="#5a6883">orient={orientation:.1f} tpms={tpms_t:.3f}</text>
</svg>
"""

    def planning_artifact_path(self, run_id: str, specimen_id: str, filename: str) -> Path:
        """Resolve a planning artifact path under run_root."""
        safe_run = self._safe_artifact_segment(run_id)
        safe_specimen = self._safe_artifact_segment(specimen_id)
        safe_filename = self._safe_artifact_segment(filename)
        allowed = {"specimen.stl", "specimen_preview.svg", "experiment_spec.json", "fem_contour.svg", "cae_report.json"}
        if safe_filename not in allowed:
            raise ValueError(f"Unsupported planning artifact: {filename}")
        run_root = self._deps.run_root.resolve()
        planning_path = (self._deps.run_root / safe_run / "planning" / safe_specimen / safe_filename).resolve()
        if planning_path.exists():
            path = planning_path
        else:
            specimens_path = (self._deps.run_root / safe_run / "specimens" / safe_specimen / safe_filename).resolve()
            if specimens_path.exists():
                path = specimens_path
            else:
                # Preserve previous behavior for missing files while returning a deterministic path.
                path = planning_path
        if not str(path).startswith(str(run_root)):
            raise ValueError("Planning artifact path escapes run root.")
        return path

    async def runtime_model_statuses(self) -> dict[str, Any]:
        """Return managed model statuses for the active vLLM backend."""
        backend = self._deps.agent_context.primary_backends.get("vllm")
        status_fn = getattr(backend, "managed_model_statuses", None)
        if self._deps.agent_context.active_backend != "vllm" or status_fn is None:
            return {
                "ok": False,
                "enabled": False,
                "active_backend": self._deps.agent_context.active_backend,
                "models": [],
                "runtime": self._runtime_profile(),
            }
        try:
            result = await status_fn()
        except Exception as exc:
            return {
                "ok": False,
                "enabled": True,
                "active_backend": "vllm",
                "models": [],
                "runtime": self._runtime_profile(),
                "error": str(exc),
            }
        return {
            "ok": True,
            "enabled": bool(result.get("enabled", False)) if isinstance(result, dict) else False,
            "active_backend": "vllm",
            "models": result.get("models", []) if isinstance(result, dict) else [],
            "runtime": self._runtime_profile(),
        }

    async def load_runtime_model(self, model: str) -> dict[str, Any]:
        """Manually load one managed vLLM model from the GUI."""
        backend = self._deps.agent_context.primary_backends.get("vllm")
        load_fn = getattr(backend, "load_model", None)
        if self._deps.agent_context.active_backend != "vllm" or load_fn is None:
            return {"ok": False, "message": "Managed vLLM runtime is not active."}
        clean_model = str(model or "").strip()
        if not clean_model:
            return {"ok": False, "message": "model is required."}
        self._cancel_pending_vllm_transition()
        try:
            result = await load_fn(clean_model)
        except Exception as exc:
            return {
                "ok": False,
                "message": f"Model load failed: {exc}",
                "status": await self.runtime_model_statuses(),
            }
        await self._emit_control_event("runtime_model_load", f"vLLM model loaded: {clean_model}")
        return {
            "ok": True,
            "message": f"Model loaded: {clean_model}",
            "result": result,
            "status": await self.runtime_model_statuses(),
        }

    async def unload_runtime_model(self, model: str) -> dict[str, Any]:
        """Manually unload one managed vLLM model from the GUI."""
        backend = self._deps.agent_context.primary_backends.get("vllm")
        unload_fn = getattr(backend, "unload_model", None)
        if self._deps.agent_context.active_backend != "vllm" or unload_fn is None:
            return {"ok": False, "message": "Managed vLLM runtime is not active."}
        clean_model = str(model or "").strip()
        if not clean_model:
            return {"ok": False, "message": "model is required."}
        try:
            result = await unload_fn(clean_model)
        except Exception as exc:
            return {
                "ok": False,
                "message": f"Model unload failed: {exc}",
                "status": await self.runtime_model_statuses(),
            }
        await self._emit_control_event("runtime_model_unload", f"vLLM model unloaded: {clean_model}")
        return {
            "ok": True,
            "message": f"Model unloaded: {clean_model}",
            "result": result,
            "status": await self.runtime_model_statuses(),
        }

    async def apply_openai_api_key(self, api_key: str, *, enabled: bool, emit_event: bool = True) -> dict[str, Any]:
        """Apply the saved OpenAI API key and update backend fallback priority."""
        clean_key = str(api_key or "").strip()
        use_api_key = bool(enabled and clean_key)
        effective_key = clean_key if use_api_key else ""
        if use_api_key:
            os.environ["OPENAI_API_KEY"] = clean_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)

        touched = 0
        seen: set[int] = set()
        backend_maps = (
            self._deps.agent_context.primary_backends,
            self._deps.agent_context.fallback_backends,
        )
        for registry in backend_maps:
            for backend in registry.values():
                ident = id(backend)
                if ident in seen:
                    continue
                seen.add(ident)
                if hasattr(backend, "_api_key"):
                    setattr(backend, "_api_key", effective_key)
                    touched += 1

        openai_backend = self._deps.agent_context.primary_backends.get("openai")
        for backend_name, primary_backend in self._deps.agent_context.primary_backends.items():
            if use_api_key and openai_backend is not None:
                self._deps.agent_context.backend_fallbacks[backend_name] = "openai"
                self._deps.agent_context.fallback_backends[backend_name] = openai_backend
            else:
                self._deps.agent_context.backend_fallbacks[backend_name] = backend_name
                self._deps.agent_context.fallback_backends[backend_name] = primary_backend

        active_fallback = self._deps.agent_context.backend_fallbacks.get(
            self._deps.agent_context.active_backend,
            self._deps.agent_context.active_backend,
        )
        if emit_event:
            await self._emit_control_event(
                "runtime_api_key_load" if use_api_key else "runtime_api_key_unload",
                (
                    "OpenAI API key enabled as first inference route."
                    if use_api_key
                    else "OpenAI API key disabled and local inference restored as first route."
                ),
            )
        return {
            "ok": True,
            "enabled": use_api_key,
            "updated_backends": touched,
            "primary_backend": "openai" if use_api_key else self._deps.agent_context.active_backend,
            "fallback_backend": active_fallback,
        }

    def _ollama_base_url(self) -> str:
        """Resolve direct Ollama endpoint used for model unload/clear."""
        explicit = os.getenv("OLLAMA_BASE_URL")
        if explicit:
            return explicit.rstrip("/")
        backend_port = os.getenv("NEMOCLAW_BACKEND_PORT", "11434").strip()
        return f"http://127.0.0.1:{backend_port}"

    async def _scale_down_idle_vllm_models(
        self,
        *,
        keep_models: set[str] | None = None,
        include_persistent: bool = False,
    ) -> dict[str, Any]:
        """Scale down NemoClaw-hosted vLLM deployments."""
        backend = self._deps.agent_context.primary_backends.get("vllm")
        scale_down = getattr(backend, "scale_down_idle_models", None)
        if scale_down is None:
            return {"enabled": False, "scaled_down": [], "errors": []}
        if keep_models:
            scale_down_except = getattr(backend, "scale_down_models_except", None)
            if scale_down_except is not None:
                try:
                    result = await scale_down_except(keep_models, include_persistent=include_persistent)
                    return result if isinstance(result, dict) else {"enabled": True, "scaled_down": [], "errors": []}
                except Exception as exc:
                    return {"enabled": True, "scaled_down": [], "errors": [str(exc)]}
        try:
            result = await scale_down(include_persistent=include_persistent)
        except Exception as exc:
            return {"enabled": True, "scaled_down": [], "errors": [str(exc)]}
        return result if isinstance(result, dict) else {"enabled": True, "scaled_down": [], "errors": []}

    def _cancel_pending_vllm_transition(self) -> None:
        """Cancel delayed idle transition when new model work begins."""
        task = self._vllm_transition_task
        if task is not None and not task.done():
            task.cancel()
        self._vllm_transition_task = None

    def _schedule_post_run_vllm_transition(self) -> None:
        """Run vLLM idle transition in the background instead of blocking GUI/API responses."""
        if self._deps.agent_context.active_backend != "vllm":
            return

        self._cancel_pending_vllm_transition()

        async def _runner() -> dict[str, Any]:
            return await self._post_run_vllm_transition()

        task = asyncio.create_task(_runner())
        self._vllm_transition_task = task

        def _clear(done: asyncio.Task[dict[str, Any]]) -> None:
            if self._vllm_transition_task is done:
                self._vllm_transition_task = None
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception:
                return

        task.add_done_callback(_clear)

    async def _post_run_vllm_transition(self) -> dict[str, Any]:
        """After run/planning completion, scale idle vLLM deployments down."""
        if self._deps.agent_context.active_backend != "vllm":
            return {"enabled": False, "action": "none"}

        scale_result = await self._scale_down_idle_vllm_models()
        return {
            "enabled": True,
            "action": "scale_down",
            "scale_down": scale_result,
        }

    async def clear_gpu(self) -> dict[str, Any]:
        """Unload currently resident Ollama models to free GPU memory."""
        if self._run_task and not self._run_task.done():
            await self.stop()

        vllm_clear = await self._scale_down_idle_vllm_models(include_persistent=True)
        base_url = self._ollama_base_url()
        unloaded: list[str] = []
        errors: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                ps_resp = await client.get(f"{base_url}/api/ps")
                ps_resp.raise_for_status()
                payload = ps_resp.json()
                models = payload.get("models", []) if isinstance(payload, dict) else []
                loaded_model_names: list[str] = []
                for item in models:
                    if isinstance(item, dict):
                        name = str(item.get("name") or item.get("model") or "").strip()
                        if name:
                            loaded_model_names.append(name)

                for model_name in loaded_model_names:
                    try:
                        unload_resp = await client.post(
                            f"{base_url}/api/generate",
                            json={"model": model_name, "prompt": "", "stream": False, "keep_alive": 0},
                        )
                        unload_resp.raise_for_status()
                        unloaded.append(model_name)
                    except Exception as exc:
                        errors.append(f"{model_name}: {exc}")
        except Exception as exc:
            if vllm_clear.get("scaled_down"):
                msg = f"GPU clear completed for vLLM; Ollama clear skipped: {exc}"
                await self._emit_control_event("gpu_clear", msg)
                return {
                    "ok": not vllm_clear.get("errors"),
                    "message": msg,
                    "base_url": base_url,
                    "unloaded_models": unloaded,
                    "vllm": vllm_clear,
                    "errors": [str(exc), *vllm_clear.get("errors", [])],
                }
            msg = f"GPU clear failed: {exc}"
            await self._emit_control_event("gpu_clear", msg)
            return {
                "ok": False,
                "message": msg,
                "base_url": base_url,
                "unloaded_models": [],
                "vllm": vllm_clear,
                "errors": [str(exc), *vllm_clear.get("errors", [])],
            }

        msg = f"GPU clear completed. unloaded={len(unloaded)} vllm_scaled_down={len(vllm_clear.get('scaled_down', []))}"
        await self._emit_control_event("gpu_clear", msg)
        return {
            "ok": len(errors) == 0 and not vllm_clear.get("errors"),
            "message": msg if not errors else f"{msg}, errors={len(errors)}",
            "base_url": base_url,
            "unloaded_models": unloaded,
            "vllm": vllm_clear,
            "errors": errors,
        }
