"""
File purpose:
- Convert camera/screenshot observations into lab perception signals for the closed loop.

Key classes/functions:
- VisionAgent

Inputs/outputs:
- Input: OrchestratorState plus camera.capture response
- Output: legacy observation fields, vision_report.v1, vision_signal.v1, decisions, metrics, evidence refs

Dependencies:
- agents.base_agent.BaseAgent
- mcp tool: camera.capture

Modification guide:
- Safe places to edit: zone defaults, simulator signal rules, evidence payload shape
- Risky places to edit: legacy observation keys consumed by Manipulation/Guardian
- Related files: mcp_tools/camera_tools.py, device_bridges/realsense_bridge.py, graphs/modules/vision/module.yaml
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any
from urllib.parse import quote

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from utils.agent_artifact_archive import archive_agent_run
from orchestrator.state import Mode, OrchestratorState
from utils.utm_specimen_presence import inspect_specimen_presence_path
from utils.vision_operator_intervention import (
    active_intervention,
    begin_intervention,
    intervention_deadline_expired,
    mark_intervention_waiting,
    resolve_intervention,
)


class VisionAgent(BaseAgent):
    """Build lab scene signals and close a verified manipulation rollout before handoff."""

    name = "vision_agent"
    SIGNAL_TTL_MS = 5000
    ACTIVE_CAM_WORKSPACE_ROI = (0.18, 0.0, 0.84, 0.62)

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[1]

    @classmethod
    def _artifact_dir(cls, state: OrchestratorState, observation_id: str) -> Path:
        path = cls._repo_root() / "runs" / state.run_id / "vision" / observation_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _persist_active_cam_run_artifact(
        cls,
        *,
        state: OrchestratorState,
        observation_id: str,
        active_check: dict[str, Any],
    ) -> dict[str, Any]:
        captured_at_dt = datetime.now(timezone.utc)
        captured_at = captured_at_dt.isoformat()
        raw_source_text = str(active_check.get("raw_capture_path") or active_check.get("capture_path") or "").strip()
        source_text = str(active_check.get("annotated_capture_path") or active_check.get("capture_path") or "").strip()
        base = {
            "schema": "active_cam_run_artifact.v1",
            "path": "",
            "url": "",
            "source_path": raw_source_text,
            "annotated_source_path": source_text,
            "run_id": state.run_id,
            "observation_id": observation_id,
            "loop_index": int(state.loop_count or 0),
            "specimen_id": str(active_check.get("specimen_id") or ""),
            "camera_key": str(active_check.get("camera_key") or ""),
            "camera_port": str(active_check.get("camera_port") or ""),
            "frame_width": active_check.get("frame_width"),
            "frame_height": active_check.get("frame_height"),
            "captured_at": captured_at,
            "decision_status": str(active_check.get("status") or "").strip().lower(),
            "specimen_detected": bool(active_check.get("specimen_detected")),
            "spc_autoejection_confirmed": bool(active_check.get("spc_autoejection_confirmed")),
            "placement_status": str(active_check.get("placement_status") or ""),
            "bbox_xyxy": list(active_check.get("bbox_xyxy") or []),
            "center_px": list(active_check.get("center_px") or []),
            "confidence": active_check.get("confidence"),
            "detector": str(active_check.get("detector") or ""),
            "detection_source": str(active_check.get("detection_source") or ""),
            "roi_xyxy": list(active_check.get("roi_xyxy") or []),
        }
        active_status = str(active_check.get("status") or "").strip().lower()
        if active_status not in {"confirmed", "not_detected"}:
            return {
                **base,
                "status": "failed",
                "failure_code": "ACTIVE_CAM_ATTEMPT_FAILED",
            }

        source = Path(source_text).expanduser() if source_text else None
        if source is None or not source.is_file():
            return {
                **base,
                "status": "failed",
                "failure_code": "ACTIVE_CAM_ARTIFACT_SOURCE_MISSING",
            }
        suffix = source.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg"}:
            return {
                **base,
                "status": "failed",
                "failure_code": "ACTIVE_CAM_ARTIFACT_FORMAT_UNSUPPORTED",
            }

        output_dir = cls._artifact_dir(state, observation_id)
        stamp = captured_at_dt.strftime("%Y%m%dT%H%M%S%fZ")
        target = output_dir / f"active_cam_capture_{stamp}{suffix}"
        try:
            shutil.copy2(source, target)
            run_dir = (cls._repo_root() / "runs" / state.run_id).resolve()
            relative = target.resolve().relative_to(run_dir).as_posix()
        except (OSError, ValueError) as exc:
            target.unlink(missing_ok=True)
            return {
                **base,
                "status": "failed",
                "failure_code": "ACTIVE_CAM_ARTIFACT_COPY_FAILED",
                "message": f"{exc.__class__.__name__}: {exc}",
            }
        return {
            **base,
            "status": "stored",
            "path": str(target.resolve()),
            "url": f"/api/runs/{quote(state.run_id, safe='')}/artifact-file/{quote(relative, safe='/')}",
            "relative_path": relative,
            "source_path": str(Path(raw_source_text).expanduser().resolve()) if raw_source_text else str(source.resolve()),
            "annotated_source_path": str(source.resolve()),
        }

    @classmethod
    def _persist_utm_completion_run_artifact(
        cls,
        *,
        state: OrchestratorState,
        observation_id: str,
        capture: dict[str, Any],
    ) -> dict[str, Any]:
        captured_at_dt = datetime.now(timezone.utc)
        captured_at = captured_at_dt.isoformat()
        raw_source_text = str(capture.get("raw_frame_path") or "").strip()
        source_text = str(
            capture.get("annotated_frame_path")
            or capture.get("frame_path")
            or capture.get("raw_frame_path")
            or ""
        ).strip()
        base = {
            "schema": "utm_completion_run_artifact.v1",
            "path": "",
            "url": "",
            "source_path": source_text,
            "raw_source_path": raw_source_text,
            "run_id": state.run_id,
            "loop_id": int(state.loop_count or 0),
            "observation_id": observation_id,
            "frame_id": str(capture.get("frame_id") or ""),
            "session_id": str(capture.get("session_id") or ""),
            "specimen_id": str(capture.get("specimen_id") or ""),
            "camera_key": str(capture.get("camera_key") or "utm"),
            "frame_width": capture.get("frame_width", capture.get("width")),
            "frame_height": capture.get("frame_height", capture.get("height")),
            "confidence": cls._as_float(capture.get("confidence"), 0.0),
            "detected": capture.get("detected") is True,
            "bbox_xyxy": list(capture.get("bbox_xyxy") or []),
            "center_px": list(capture.get("center_px") or []),
            "roi_xyxy": list(capture.get("roi_xyxy") or []),
            "detector": str(capture.get("detector") or ""),
            "detection_source": str(capture.get("source") or ""),
            "captured_at": captured_at,
        }
        if not bool(capture.get("ok")):
            return {
                **base,
                "status": "failed",
                "failure_code": str(capture.get("failure_code") or "UTM_CAPTURE_FAILED"),
            }
        if capture.get("detected") is not True:
            return {
                **base,
                "status": "not_detected",
                "failure_code": str(capture.get("failure_code") or "UTM_SPECIMEN_NOT_DETECTED"),
            }

        source = Path(source_text).expanduser() if source_text else None
        if source is None or not source.is_file():
            return {
                **base,
                "status": "failed",
                "failure_code": "UTM_COMPLETION_ARTIFACT_SOURCE_MISSING",
            }
        suffix = source.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            return {
                **base,
                "status": "failed",
                "failure_code": "UTM_COMPLETION_ARTIFACT_FORMAT_UNSUPPORTED",
            }

        output_dir = cls._artifact_dir(state, observation_id)
        stamp = captured_at_dt.strftime("%Y%m%dT%H%M%S%fZ")
        target = output_dir / f"utm_completion_{stamp}{suffix}"
        try:
            shutil.copy2(source, target)
            run_dir = (cls._repo_root() / "runs" / state.run_id).resolve()
            relative = target.resolve().relative_to(run_dir).as_posix()
        except (OSError, ValueError) as exc:
            target.unlink(missing_ok=True)
            return {
                **base,
                "status": "failed",
                "failure_code": "UTM_COMPLETION_ARTIFACT_COPY_FAILED",
                "message": f"{exc.__class__.__name__}: {exc}",
            }
        return {
            **base,
            "status": "stored",
            "path": str(target.resolve()),
            "url": f"/api/runs/{quote(state.run_id, safe='')}/artifact-file/{quote(relative, safe='/')}",
            "relative_path": relative,
            "source_path": str(source.resolve()),
        }

    @staticmethod
    def _specimen_result(state: OrchestratorState) -> dict[str, Any]:
        raw = state.run_metadata.get("specimen_result") if isinstance(state.run_metadata, dict) else {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _fabrication_report(state: OrchestratorState, specimen: dict[str, Any]) -> dict[str, Any]:
        if isinstance(state.run_metadata, dict):
            for key in ("fabrication_report", "specimen_fabrication_report"):
                if isinstance(state.run_metadata.get(key), dict):
                    return state.run_metadata[key]
        report = specimen.get("fabrication_report") if isinstance(specimen.get("fabrication_report"), dict) else {}
        return report if isinstance(report, dict) else {}

    @classmethod
    def _physical_printer_tail_requested(cls, state: OrchestratorState) -> bool:
        """Test-mode installed/physical printer paths must use real camera tools."""
        if state.mode != Mode.TEST or not isinstance(state.run_metadata, dict):
            return False
        if cls._virtual_printer_tail_requested(state):
            return False
        specimen = cls._specimen_result(state)
        report = cls._fabrication_report(state, specimen)
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        intent = report.get("fabrication_intent") if isinstance(report.get("fabrication_intent"), dict) else {}
        status = report.get("printer_status") if isinstance(report.get("printer_status"), dict) else {}
        profile = report.get("printer_profile") if isinstance(report.get("printer_profile"), dict) else {}
        fabricated = state.run_metadata.get("specimen_fabricated") if isinstance(state.run_metadata.get("specimen_fabricated"), dict) else {}
        summary = fabricated.get("fabrication_summary") if isinstance(fabricated.get("fabrication_summary"), dict) else {}

        paths = {
            str(value or "").strip().lower()
            for value in (
                spec.get("printer_test_path"),
                spec.get("test_printer_path"),
                specimen.get("printer_path"),
                intent.get("printer_path"),
                status.get("printer_path"),
                status.get("path"),
                profile.get("printer_path"),
                summary.get("printer_path"),
            )
            if str(value or "").strip()
        }
        if not (paths & {"installed_printer", "physical_print", "actual_print", "test_printer_physical_print", "bambulab_x2d"}):
            return False
        return any(
            bool(value)
            for value in (
                spec.get("allow_test_printer_live"),
                specimen.get("physical_intent"),
                intent.get("physical_intent"),
                profile.get("physical_intent"),
                summary.get("physical_intent"),
                paths & {"installed_printer", "physical_print", "actual_print", "test_printer_physical_print", "bambulab_x2d"},
            )
        )

    @staticmethod
    def _virtual_printer_tail_requested(state: OrchestratorState) -> bool:
        """Keep an explicit Live GUI virtual-printer handoff off physical cameras."""
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        virtual_paths = {"virtual", "virtual_bridge", "virtual_printer", "virtual_bambu_bridge"}
        for key in ("printer_test_path", "test_printer_path", "printer_bridge_mode", "printer_test_mode"):
            value = str(spec.get(key) or "").strip().lower().replace("-", "_").replace(" ", "_")
            if value in virtual_paths:
                return True
        return str(spec.get("test_printer_transport") or "").strip().lower() == "virtual"

    @classmethod
    def _camera_runtime_mode(cls, state: OrchestratorState) -> str:
        if cls._virtual_printer_tail_requested(state):
            return "test"
        return "live" if state.mode == Mode.LIVE or cls._physical_printer_tail_requested(state) else state.mode.value

    @staticmethod
    def _rollout_execution_evidence(
        state: OrchestratorState,
        rollout_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        manipulation = metadata.get("manipulation_result") if isinstance(metadata.get("manipulation_result"), dict) else {}
        runtime = manipulation.get("runtime") if isinstance(manipulation.get("runtime"), dict) else {}
        embedded = manipulation.get("execution_evidence") if isinstance(manipulation.get("execution_evidence"), dict) else {}
        status = rollout_status if isinstance(rollout_status, dict) else {}
        status_runtime = status.get("runtime") if isinstance(status.get("runtime"), dict) else {}
        expected_session_id = str(manipulation.get("session_id") or "").strip()
        status_session_id = str(status.get("session_id") or "").strip()
        status_matches_session = bool(
            status
            and expected_session_id
            and status_session_id
            and status_session_id == expected_session_id
        )
        telemetry = status.get("joint_telemetry") if isinstance(status.get("joint_telemetry"), dict) else {}
        packet = telemetry.get("packet") if isinstance(telemetry.get("packet"), dict) else {}
        packet_session_id = str(packet.get("session_id") or "").strip()
        try:
            telemetry_sequence = max(0, int(packet.get("sequence") or 0))
        except (TypeError, ValueError):
            telemetry_sequence = 0
        telemetry_action_observed = bool(
            status_matches_session
            and str(telemetry.get("status") or "").strip().lower() == "available"
            and packet_session_id == expected_session_id
            and str(packet.get("type") or "").strip().lower() == "joint_sample"
            and telemetry_sequence > 0
            and isinstance(packet.get("actual_source"), dict)
            and bool(packet.get("actual_source"))
            and (
                (isinstance(packet.get("target_source"), dict) and bool(packet.get("target_source")))
                or (isinstance(packet.get("applied_target_source"), dict) and bool(packet.get("applied_target_source")))
            )
        )
        tool = str(manipulation.get("tool") or "").strip().lower()
        workflow = str(manipulation.get("workflow") or "").strip().lower()
        required = bool(embedded.get("required", workflow == "rollout" or tool.startswith("lerobot.rollout.")))
        phase = str(
            embedded.get("runtime_phase")
            or manipulation.get("runtime_phase")
            or status_runtime.get("phase")
            or runtime.get("phase")
            or ""
        ).strip().upper()
        raw_count = embedded.get(
            "action_count",
            manipulation.get("action_count", status_runtime.get("action_count", runtime.get("action_count", 0))),
        )
        try:
            action_count = max(0, int(raw_count or 0))
        except (TypeError, ValueError):
            action_count = 0
        action_count = max(action_count, telemetry_sequence if telemetry_action_observed else 0)
        observed = bool(
            not required
            or embedded.get("observed")
            or telemetry_action_observed
            or (phase == "ACTION_ACTIVE" and action_count > 0)
        )
        return {
            "required": required,
            "observed": observed,
            "runtime_phase": phase or "UNKNOWN",
            "action_count": action_count,
            "session_id": expected_session_id,
            "telemetry_sequence": telemetry_sequence if telemetry_action_observed else 0,
            "telemetry_status": str(telemetry.get("status") or "waiting"),
        }

    @staticmethod
    def _refresh_rollout_status_for_utm_completion(
        *,
        state: OrchestratorState,
        ctx: AgentContext,
        post_place_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Read the active rollout session just before UTM completion evaluation."""
        tool_name = "lerobot.rollout.status"
        if tool_name not in set(ctx.tools.list_tools()):
            return {
                "ok": False,
                "tool": tool_name,
                "failure_code": "ROLLOUT_STATUS_TOOL_NOT_REGISTERED",
            }
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        manipulation = metadata.get("manipulation_result") if isinstance(metadata.get("manipulation_result"), dict) else {}
        robot_task = metadata.get("robot_task_result") if isinstance(metadata.get("robot_task_result"), dict) else {}
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        session_id = str(
            post_place_context.get("session_id")
            or robot_task.get("rollout_session_id")
            or manipulation.get("session_id")
            or ""
        ).strip()
        if not session_id:
            return {
                "ok": False,
                "tool": tool_name,
                "failure_code": "ROLLOUT_STATUS_SESSION_MISSING",
            }
        payload = {
            "mode": state.mode.value,
            "runtime_mode": str(manipulation.get("runtime_mode") or manipulation.get("mode") or state.mode.value),
            "profile_id": str(
                manipulation.get("profile_id")
                or robot_task.get("profile_id")
                or spec.get("lerobot_profile_id")
                or spec.get("robot_profile_id")
                or ""
            ),
            "session_id": session_id,
        }
        try:
            response = dict(ctx.tools.call(tool_name, payload))
        except Exception as exc:
            return {
                "ok": False,
                "tool": tool_name,
                "failure_code": "ROLLOUT_STATUS_REFRESH_FAILED",
                "message": f"{exc.__class__.__name__}: {exc}",
                "session_id": session_id,
            }
        response.setdefault("tool", tool_name)
        response.setdefault("session_id", session_id)
        if str(response.get("session_id") or "").strip() != session_id:
            response["ok"] = False
            response["failure_code"] = "ROLLOUT_STATUS_SESSION_MISMATCH"
        return response

    @staticmethod
    def _as_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _stable_digest(value: Any, length: int = 10) -> str:
        payload = json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:length]

    @staticmethod
    def _merge_dict(base: dict[str, Any], override: Any) -> dict[str, Any]:
        if not isinstance(override, dict):
            return dict(base)
        merged = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = VisionAgent._merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _resolve_task(self, state: OrchestratorState, capture: dict[str, Any]) -> str:
        purpose = str(capture.get("purpose") or "").strip()
        if purpose:
            if purpose == "utm_placement_verification":
                return "post_manipulation_utm_verification"
            if purpose == "3dp_output_pickup_check":
                return "post_ejection_basket_check"
            return purpose
        if state.run_metadata.get("equipment_result"):
            return "post_utm_reset_check"
        if state.run_metadata.get("manipulation_result"):
            return "pre_utm_fixture_check"
        return "post_ejection_basket_check"

    def _zone_state(
        self,
        *,
        capture: dict[str, Any],
        specimen_ready: bool,
        capture_ok: bool,
        anomaly: bool,
        confidence: float,
    ) -> dict[str, Any]:
        ready_visible = bool(capture_ok and specimen_ready and not anomaly)
        base = {
            "printer_bed": {
                "specimen_present": False,
                "confidence": round(0.72 if capture_ok else 0.0, 3),
                "ejection_expected": True,
                "state": "clear" if capture_ok else "unknown",
            },
            "ejection_basket": {
                "specimen_present": ready_visible,
                "object_count": 1 if ready_visible else 0,
                "confidence": round(confidence if ready_visible else 0.0, 3),
                "state": "loaded" if ready_visible else "empty_or_unknown",
            },
            "robot_workspace": {
                "clear": bool(capture_ok and not anomaly),
                "confidence": round(0.8 if capture_ok and not anomaly else 0.25 if capture_ok else 0.0, 3),
                "state": "clear" if capture_ok and not anomaly else "review_required",
            },
            "robot_gripper": {
                "holding_specimen": False,
                "confidence": round(0.75 if capture_ok else 0.0, 3),
                "state": "open_or_empty" if capture_ok else "unknown",
            },
            "utm_platen": {
                "specimen_present": False,
                "aligned": False,
                "confidence": 0.0,
                "state": "empty_or_not_checked",
            },
            "utm_screen": {
                "state": "unknown",
                "confidence": 0.0,
            },
        }
        return self._merge_dict(base, capture.get("zones"))

    def _detections(
        self,
        *,
        capture: dict[str, Any],
        specimen: dict[str, Any],
        specimen_ready: bool,
        capture_ok: bool,
        anomaly: bool,
        confidence: float,
    ) -> list[dict[str, Any]]:
        existing = capture.get("detections")
        if isinstance(existing, list):
            return [item for item in existing if isinstance(item, dict)]
        if "detected" in capture and not bool(capture.get("detected")):
            return []
        if not (capture_ok and specimen_ready and not anomaly):
            return []
        return [
            {
                "label": "printed_specimen",
                "zone": "ejection_basket",
                "specimen_id": specimen.get("specimen_id", ""),
                "candidate_id": specimen.get("candidate_id", ""),
                "bbox_xyxy": capture.get("bbox_xyxy") if isinstance(capture.get("bbox_xyxy"), list) else [210, 120, 420, 310],
                "mask_path": str(capture.get("mask_path") or ""),
                "confidence": round(confidence, 3),
                "source": str(capture.get("source") or "simulator"),
            }
        ]

    def _attach_lerobot_camera_evidence(self, state: OrchestratorState, ctx: AgentContext, capture: dict[str, Any]) -> dict[str, Any]:
        if self._post_manipulation_completion_requested(state):
            return capture
        available_tools = set(ctx.tools.list_tools())
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        active_cam_requested = self._should_request_active_cam_ejection_check(state)
        active_cam_tool = "lerobot.active_robot_cam.capture" if "lerobot.active_robot_cam.capture" in available_tools else ""
        camera_test_tool = "lerobot.camera.test" if "lerobot.camera.test" in available_tools else ""
        if active_cam_requested and not active_cam_tool:
            enriched = dict(capture)
            enriched["camera_bridge_warning"] = "lerobot_active_robot_cam_capture_tool_missing"
            enriched["active_cam_ejection_check"] = {
                "schema": "active_cam_ejection_check.v1",
                "status": "blocked",
                "specimen_detected": False,
                "spc_autoejection_confirmed": False,
                "blocking_reason": "lerobot_active_robot_cam_capture_tool_missing",
                "source": "lerobot.active_robot_cam.capture",
            }
            return enriched
        if not active_cam_requested and not camera_test_tool:
            return capture
        live_confirmed = bool(
            spec.get("confirm_live_execute")
            or spec.get("confirm_camera_capture")
            or spec.get("vision_confirm_camera_capture")
            or active_cam_requested
        )
        requested = (
            state.mode == Mode.TEST
            or str(spec.get("vision_camera_backend") or "").strip().lower() == "lerobot"
            or bool(spec.get("camera_enabled") or spec.get("vision_use_lerobot_camera"))
            or active_cam_requested
        )
        if not requested:
            return capture
        if state.mode == Mode.LIVE and not live_confirmed:
            enriched = dict(capture)
            enriched["camera_bridge_warning"] = "lerobot_camera_test_requires_live_confirmation"
            enriched["active_cam_ejection_check"] = {
                "schema": "active_cam_ejection_check.v1",
                "status": "blocked",
                "specimen_detected": False,
                "spc_autoejection_confirmed": False,
                "blocking_reason": "lerobot_camera_test_requires_live_confirmation",
                "source": active_cam_tool or camera_test_tool or "lerobot.camera.test",
            }
            return enriched
        active_camera_key = self._active_cam_camera_key(state, capture)
        runtime_mode = self._camera_runtime_mode(state)
        tool_name = active_cam_tool if active_cam_requested else camera_test_tool
        payload = {
            "mode": runtime_mode,
            "runtime_mode": runtime_mode,
            "camera_key": active_camera_key,
            "profile_id": str(spec.get("lerobot_profile_id") or spec.get("robot_profile_id") or ""),
            "confirm_live_execute": live_confirmed or runtime_mode == "live",
            "reason": "spc_autoejection_verification" if active_cam_requested else "vision_camera_evidence",
        }
        if active_cam_requested:
            payload.update(
                {
                    "active_robot_cam_camera_priority": "d405",
                    "active_robot_cam_d455f_fallback_enabled": False,
                }
            )
        try:
            result = ctx.tools.call(tool_name, payload)
        except Exception as exc:
            enriched = dict(capture)
            result_key = "lerobot_active_robot_cam_capture" if active_cam_requested else "lerobot_camera_test"
            enriched[result_key] = {"ok": False, "tool": tool_name, "failure_code": exc.__class__.__name__, "message": str(exc)}
            enriched["active_cam_ejection_check"] = self._active_cam_ejection_check(
                state=state,
                capture=capture,
                result=enriched[result_key],
                active_camera_key=active_camera_key,
            )
            return enriched
        enriched = dict(capture)
        result_key = "lerobot_active_robot_cam_capture" if active_cam_requested else "lerobot_camera_test"
        enriched[result_key] = result
        capture_result = result.get("capture") if isinstance(result.get("capture"), dict) else {}
        active_check = self._active_cam_ejection_check(
            state=state,
            capture=capture,
            result=result,
            active_camera_key=active_camera_key,
        )
        enriched["active_cam_ejection_check"] = active_check
        enriched["camera_returned_to_vla"] = bool(active_check.get("camera_returned_to_vla", enriched.get("camera_returned_to_vla", True)))
        enriched["vla_camera_precheck_ok"] = bool(active_check.get("port_released", enriched.get("vla_camera_precheck_ok", True)))
        enriched["spc_autoejection_confirmation"] = {
            "schema": "spc_autoejection_confirmation.v1",
            "signal": "SPC_AUTOEJECTION_CONFIRMED_BY_ACTIVE_CAM",
            "status": active_check.get("status"),
            "specimen_detected": bool(active_check.get("specimen_detected")),
            "confirmed": bool(active_check.get("spc_autoejection_confirmed")),
            "source_agent": self.name,
            "consumer_agent": "specimen_agent",
            "camera_key": active_check.get("camera_key"),
            "capture_path": active_check.get("capture_path"),
            "capture_url": active_check.get("capture_url"),
        }
        if active_cam_requested:
            confirmed = bool(active_check.get("status") == "confirmed" and active_check.get("spc_autoejection_confirmed"))
            specimen_not_detected = active_check.get("status") == "not_detected"
            enriched.update(
                {
                    "ok": confirmed or specimen_not_detected,
                    "source": "lerobot_active_robot_cam",
                    "camera_key": active_check.get("camera_key") or active_camera_key,
                    "detected": bool(active_check.get("specimen_detected")),
                    "confidence": 0.86 if confirmed else 0.0,
                    "pose_confidence": 0.86 if confirmed else 0.0,
                    "stable_for_ms": 1200 if confirmed else 0,
                    "failure_code": "" if confirmed or specimen_not_detected else str(active_check.get("blocking_reason") or result.get("failure_code") or "ACTIVE_CAM_CONFIRMATION_REQUIRED"),
                    "backend_mode": "active_cam",
                    "detector": "active_cam_specimen_pose",
                }
            )
        if result.get("ok") and capture_result.get("path"):
            enriched["frame_path"] = str(capture_result.get("path"))
            enriched["frame_url"] = str(capture_result.get("serve_url") or "")
            enriched["source"] = "lerobot_active_robot_cam" if active_cam_requested else "lerobot_camera_test"
            enriched["camera_key"] = result.get("camera_key") or enriched.get("camera_key") or "top"
            enriched["frame_width"] = capture_result.get("width")
            enriched["frame_height"] = capture_result.get("height")
            enriched["synthetic_frame"] = capture_result.get("synthetic")
        return enriched

    def _should_request_active_cam_ejection_check(self, state: OrchestratorState) -> bool:
        specimen = self._specimen_result(state)
        if not specimen or specimen.get("ok") is False:
            return False
        report = self._fabrication_report(state, specimen)
        if not report:
            fabricated = state.run_metadata.get("specimen_fabricated") if isinstance(state.run_metadata, dict) else {}
            return isinstance(fabricated, dict) and fabricated.get("schema") == "specimen_fabricated.v1"
        outcome = report.get("fabrication_outcome") if isinstance(report.get("fabrication_outcome"), dict) else {}
        gate = report.get("autoejection_gate") if isinstance(report.get("autoejection_gate"), dict) else {}
        statuses = {
            str(outcome.get("autoejection_status") or "").strip().lower(),
            str(outcome.get("status") or "").strip().lower(),
            str(gate.get("status") or "").strip().lower(),
        }
        if statuses.intersection({"complete", "completed", "confirmed", "ready", "ok", "success"}):
            return True
        location = str(outcome.get("location") or "").strip().lower()
        return location in {"a4_workspace", "robot_workspace", "ejection_basket", "3dp_output_area"}

    def _active_cam_camera_key(self, state: OrchestratorState, capture: dict[str, Any]) -> str:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        for key in ("active_cam_camera_key", "vision_active_camera_key", "active_robot_cam_primary_camera_key"):
            value = str(spec.get(key) or "").strip()
            if value:
                return value
        value = str(capture.get("active_cam_camera_key") or "").strip()
        return value or "wrist"

    @staticmethod
    def _post_manipulation_context(state: OrchestratorState) -> dict[str, Any]:
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        manipulation = metadata.get("manipulation_result") if isinstance(metadata.get("manipulation_result"), dict) else {}
        robot_task = metadata.get("robot_task_result") if isinstance(metadata.get("robot_task_result"), dict) else {}
        current_specimen_id = str(VisionAgent._specimen_result(state).get("specimen_id") or "").strip()
        transfer_task = manipulation.get("transfer_task") if isinstance(manipulation.get("transfer_task"), dict) else {}
        handoff_specimen_id = str(
            robot_task.get("specimen_id")
            or manipulation.get("specimen_id")
            or transfer_task.get("specimen_id")
            or ""
        ).strip()
        handoff_run_id = str(robot_task.get("run_id") or manipulation.get("run_id") or "").strip()
        stale_specimen = bool(current_specimen_id and handoff_specimen_id and handoff_specimen_id != current_specimen_id)
        stale_run = bool(state.run_id and handoff_run_id and handoff_run_id != state.run_id)
        if stale_specimen or stale_run:
            # Cycle boundaries are strict: prior rollout state must not divert the
            # current specimen away from the post-ejection ActiveCam gate.
            return {
                "handoff_status": "",
                "completion_status": "",
                "post_place_interlock": {},
                "session_id": "",
                "requested": False,
                "stale": True,
                "stale_specimen_id": handoff_specimen_id,
                "stale_run_id": handoff_run_id,
            }
        handoff = str(robot_task.get("handoff_status") or manipulation.get("handoff_status") or "").strip().lower()
        completion = str(robot_task.get("completion_status") or manipulation.get("completion_status") or "").strip().lower()
        interlock = (
            robot_task.get("post_place_interlock")
            if isinstance(robot_task.get("post_place_interlock"), dict)
            else manipulation.get("post_place_interlock")
            if isinstance(manipulation.get("post_place_interlock"), dict)
            else {}
        )
        session_id = str(
            robot_task.get("rollout_session_id")
            or robot_task.get("episode_id")
            or manipulation.get("session_id")
            or interlock.get("session_id")
            or ""
        )
        return {
            "handoff_status": handoff,
            "completion_status": completion,
            "post_place_interlock": dict(interlock),
            "session_id": session_id,
            "requested": handoff == "needs_post_place_vision",
        }

    @classmethod
    def _post_manipulation_handoff_requested(cls, state: OrchestratorState) -> bool:
        return bool(cls._post_manipulation_context(state).get("requested"))

    @classmethod
    def _post_manipulation_completion_requested(cls, state: OrchestratorState) -> bool:
        context = cls._post_manipulation_context(state)
        completion = str(context.get("completion_status") or "")
        interlock = context.get("post_place_interlock") if isinstance(context.get("post_place_interlock"), dict) else {}
        session_id = str(context.get("session_id") or "")
        interlock_session_id = str(interlock.get("session_id") or "")
        session_matches = not (session_id and interlock_session_id and session_id != interlock_session_id)
        return bool(context.get("requested")) and completion in {
            "reported_complete",
            "complete",
            "completed",
        } and bool(interlock.get("ready_for_utm_snapshot")) and session_matches

    @staticmethod
    def _stop_verified_rollout(
        *,
        state: OrchestratorState,
        ctx: AgentContext,
        completion: dict[str, Any],
    ) -> dict[str, Any]:
        """Stop the active rollout after UTM evidence verifies task completion."""
        tool_name = "lerobot.rollout.stop"
        if tool_name not in set(ctx.tools.list_tools()):
            return {
                "ok": False,
                "tool": tool_name,
                "status": "FAILED",
                "failure_code": "UTM_ROLLOUT_STOP_TOOL_NOT_REGISTERED",
                "message": "lerobot.rollout.stop tool is not registered.",
            }
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        manipulation = metadata.get("manipulation_result") if isinstance(metadata.get("manipulation_result"), dict) else {}
        robot_task = metadata.get("robot_task_result") if isinstance(metadata.get("robot_task_result"), dict) else {}
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        session_id = str(
            completion.get("session_id")
            or robot_task.get("rollout_session_id")
            or manipulation.get("session_id")
            or ""
        ).strip()
        if not session_id:
            return {
                "ok": False,
                "tool": tool_name,
                "status": "FAILED",
                "failure_code": "UTM_ROLLOUT_SESSION_MISSING",
                "message": "Verified UTM completion did not include the active rollout session id.",
            }
        if VisionAgent._virtual_printer_tail_requested(state):
            response = {
                "ok": True,
                "tool": tool_name,
                "status": "STOPPED",
                "session_id": session_id,
                "virtual_bridge_simulation": True,
                "message": "Virtual rollout completion acknowledged after UTM evidence verification.",
            }
            for key in ("manipulation_result", "robot_task_result"):
                current = metadata.get(key)
                if not isinstance(current, dict):
                    continue
                updated = dict(current)
                updated["handoff_status"] = "ready_for_equipment"
                updated["completion_status"] = "verified_complete"
                updated["rollout_stop"] = dict(response)
                if key == "manipulation_result":
                    updated["status"] = "STOPPED"
                    updated["stop_confirmed"] = True
                else:
                    updated["status"] = "ready"
                metadata[key] = updated
            return response
        stop_payload = {
            "mode": state.mode.value,
            "runtime_mode": str(manipulation.get("runtime_mode") or manipulation.get("mode") or state.mode.value),
            "profile_id": str(
                manipulation.get("profile_id")
                or robot_task.get("profile_id")
                or spec.get("lerobot_profile_id")
                or spec.get("robot_profile_id")
                or ""
            ),
            "session_id": session_id,
            "reason": "vision_utm_placement_verified",
            "completion_signal": dict(completion),
        }
        try:
            response = dict(ctx.tools.call(tool_name, stop_payload))
        except Exception as exc:
            return {
                "ok": False,
                "tool": tool_name,
                "status": "FAILED",
                "failure_code": "UTM_ROLLOUT_STOP_FAILED",
                "message": f"{exc.__class__.__name__}: {exc}",
                "session_id": session_id,
            }
        response.setdefault("tool", tool_name)
        response.setdefault("session_id", session_id)
        stop_status = str(response.get("status") or "").strip().upper()
        if not response.get("ok") or stop_status != "STOPPED":
            response["ok"] = False
            response.setdefault("failure_code", "UTM_ROLLOUT_STOP_NOT_CONFIRMED")
            response.setdefault("message", "Rollout stop was not confirmed after UTM placement verification.")
            return response

        for key in ("manipulation_result", "robot_task_result"):
            current = metadata.get(key)
            if not isinstance(current, dict):
                continue
            updated = dict(current)
            updated["handoff_status"] = "ready_for_equipment"
            updated["completion_status"] = "verified_complete"
            updated["rollout_stop"] = dict(response)
            if key == "manipulation_result":
                updated["status"] = "STOPPED"
                updated["stop_confirmed"] = True
            else:
                updated["status"] = "ready"
            metadata[key] = updated
        return response

    def _capture_request(self, state: OrchestratorState, *, frame_id: str, specimen: dict[str, Any]) -> dict[str, Any]:
        if self._post_manipulation_completion_requested(state):
            spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
            return {
                "frame_id": frame_id,
                "camera_key": str(spec.get("utm_camera_key") or spec.get("vision_utm_camera_key") or "utm"),
                "purpose": "utm_placement_verification",
                "specimen_id": specimen.get("specimen_id", ""),
                "mode": state.mode.value,
            }
        return {
            "frame_id": frame_id,
            "camera_key": "top",
            "purpose": "3dp_output_pickup_check",
            "specimen_id": specimen.get("specimen_id", ""),
            "mode": state.mode.value,
        }

    def _post_place_interlock_waiting_capture(
        self,
        state: OrchestratorState,
        *,
        frame_id: str,
        specimen: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._post_manipulation_context(state)
        return {
            "ok": True,
            "tool": "vision.post_place_interlock.wait",
            "frame_id": frame_id,
            "observation_id": f"obs-{frame_id}",
            "camera_key": "utm",
            "purpose": "utm_placement_verification",
            "source": "post_place_interlock",
            "specimen_id": specimen.get("specimen_id", ""),
            "session_id": context.get("session_id", ""),
            "detected": False,
            "confidence": 0.0,
            "pose_confidence": 0.0,
            "stable_for_ms": 0,
            "anomaly": False,
            "capture_skipped": True,
            "completion_blocking_reason": "post_place_interlock_waiting",
            "post_place_interlock": context.get("post_place_interlock", {}),
        }

    def _active_cam_ejection_check(
        self,
        *,
        state: OrchestratorState,
        capture: dict[str, Any],
        result: dict[str, Any],
        active_camera_key: str,
    ) -> dict[str, Any]:
        specimen = self._specimen_result(state)
        driver_result = result.get("active_robot_cam_result") if isinstance(result.get("active_robot_cam_result"), dict) else {}
        capture_result = result.get("capture") if isinstance(result.get("capture"), dict) else {}
        if not capture_result and isinstance(driver_result.get("capture"), dict):
            capture_result = driver_result["capture"]
        capture_pose = result.get("capture_pose") if isinstance(result.get("capture_pose"), dict) else {}
        if not capture_pose and isinstance(driver_result.get("capture_pose"), dict):
            capture_pose = driver_result["capture_pose"]
        if not capture_pose and isinstance(driver_result.get("capture_wait"), dict):
            capture_pose = driver_result["capture_wait"]
        resume_pose = result.get("resume_pose") if isinstance(result.get("resume_pose"), dict) else {}
        if not resume_pose and isinstance(driver_result.get("resume_pose"), dict):
            resume_pose = driver_result["resume_pose"]
        tool_ok = bool(result.get("ok"))
        capture_ok = bool(capture_result.get("ok", True) and capture_result.get("path"))
        capture_path = str(capture_result.get("path") or "").strip()
        detection: dict[str, Any] = {}
        detection_error = ""
        if capture_ok and capture_path:
            frame_id = str(capture.get("frame_id") or f"frame-{state.run_id}")
            observation_id = str(capture.get("observation_id") or f"{frame_id}-active-cam")
            try:
                detection = inspect_specimen_presence_path(
                    capture_path,
                    output_dir=self._artifact_dir(state, observation_id) / "active_cam_detection",
                    specimen_id=str(specimen.get("specimen_id") or "specimen"),
                    frame_id=f"active-cam-{state.loop_count}",
                    roi_normalized=self.ACTIVE_CAM_WORKSPACE_ROI,
                )
            except (OSError, ValueError) as exc:
                detection_error = f"{exc.__class__.__name__}: {exc}"
        port_released = bool(result.get("port_released") or capture_result.get("port_released") or driver_result.get("port_released"))
        owner_after = str(capture_result.get("camera_owner_after") or result.get("camera_owner_after") or driver_result.get("camera_owner_after") or "")
        camera_returned_to_vla = bool(
            result.get("camera_returned_to_vla")
            or capture_result.get("camera_returned_to_vla")
            or driver_result.get("camera_returned_to_vla")
            or (port_released and owner_after == "vla_runtime")
        )
        release_ok = bool(port_released and camera_returned_to_vla)
        result_markers = {
            str(result.get("status") or "").strip().lower(),
            str(result.get("message") or "").strip().lower(),
            str(result.get("failure_code") or "").strip().lower(),
            str(driver_result.get("status") or "").strip().lower(),
            str(driver_result.get("message") or "").strip().lower(),
            str(driver_result.get("failure_code") or "").strip().lower(),
        }
        explicit_detection_values = [
            payload.get("specimen_detected")
            for payload in (result, driver_result, capture_result)
            if "specimen_detected" in payload
        ]
        detection_available = bool(detection.get("ok"))
        specimen_detected = bool(detection_available and detection.get("detected") is True)
        specimen_not_detected = bool(capture_ok and detection_available and not specimen_detected)
        detection_only_tool_failure = bool(
            any("specimen_not_detected" in marker for marker in result_markers)
            or any("active_robot_cam_specimen_pose_failed" in marker for marker in result_markers)
            or any(value is False for value in explicit_detection_values)
        )
        tool_result_usable = bool(tool_ok or (capture_ok and detection_only_tool_failure))
        confirmed = bool(tool_result_usable and specimen_detected and release_ok)
        placement_status = "inside" if specimen_detected else "not_detected" if specimen_not_detected else "unknown"
        status = (
            "confirmed"
            if confirmed
            else "not_detected"
            if specimen_not_detected
            else "blocked"
            if not tool_result_usable or not detection_available or (capture_ok and not release_ok)
            else "blocked"
        )
        blocking_reason = str(
            result.get("failure_code")
            or driver_result.get("failure_code")
            or result.get("message")
            or driver_result.get("message")
            or detection_error
            or ("camera_not_returned_to_vla" if specimen_detected and not release_ok else "specimen_not_detected")
        )
        return {
            "schema": "active_cam_ejection_check.v1",
            "status": status,
            "source": str(result.get("tool") or "lerobot.camera.test"),
            "camera_key": result.get("camera_key") or active_camera_key,
            "camera_port": result.get("camera_port") or result.get("camera_identity_port") or "",
            "specimen_id": specimen.get("specimen_id", ""),
            "specimen_detected": specimen_detected,
            "placement_status": placement_status,
            "detection_failure_code": str(
                detection.get("failure_code")
                or result.get("detection_failure_code")
                or ("ACTIVE_CAM_IMAGE_DETECTION_FAILED" if detection_error else "")
            ),
            "spc_autoejection_confirmed": confirmed,
            "capture_path": capture_path,
            "capture_url": str(capture_result.get("serve_url") or ""),
            "raw_capture_path": str(detection.get("raw_frame_path") or capture_path),
            "annotated_capture_path": str(detection.get("annotated_frame_path") or ""),
            "frame_width": capture_result.get("width") or detection.get("width"),
            "frame_height": capture_result.get("height") or detection.get("height"),
            "bbox_xyxy": list(detection.get("bbox_xyxy") or []),
            "center_px": list(detection.get("center_px") or []),
            "roi_xyxy": list(detection.get("roi_xyxy") or []),
            "confidence": detection.get("confidence", 0.0),
            "detector": str(detection.get("detector") or ""),
            "synthetic_frame": capture_result.get("synthetic"),
            "port_released": port_released,
            "camera_returned_to_vla": camera_returned_to_vla,
            "camera_owner_after": owner_after,
            "robot_pose_included": bool(result.get("robot_pose_included") or driver_result.get("robot_pose_included") or capture_pose or resume_pose),
            "capture_pose": capture_pose,
            "resume_pose": resume_pose,
            "detection_source": "active_cam_workspace_image_detector",
            "blocking_reason": "" if confirmed else "specimen_not_detected" if specimen_not_detected else blocking_reason,
        }

    def _events(
        self,
        *,
        capture: dict[str, Any],
        capture_ok: bool,
        specimen_ready: bool,
        anomaly: bool,
        confidence: float,
        frame_id: str,
    ) -> list[dict[str, Any]]:
        existing = capture.get("events")
        if isinstance(existing, list):
            return [item for item in existing if isinstance(item, dict)]
        if not capture_ok:
            return [
                {
                    "event_type": "camera_capture_failed",
                    "status": "blocked",
                    "confidence": 0.0,
                    "evidence_frame_id": frame_id,
                    "blocking": True,
                }
            ]
        if anomaly:
            return [
                {
                    "event_type": "anomaly_detected",
                    "status": "observed",
                    "confidence": round(max(confidence, 0.5), 3),
                    "evidence_frame_id": frame_id,
                    "blocking": True,
                }
            ]
        if specimen_ready:
            return [
                {
                    "event_type": "printer_bed_clear",
                    "status": "observed",
                    "confidence": round(min(0.9, max(confidence, 0.72)), 3),
                    "evidence_frame_id": frame_id,
                    "blocking": False,
                },
                {
                    "event_type": "specimen_ejected_to_basket",
                    "status": "observed",
                    "confidence": round(confidence, 3),
                    "evidence_frame_id": frame_id,
                    "blocking": False,
                },
                {
                    "event_type": "basket_contains_specimen",
                    "status": "observed",
                    "confidence": round(confidence, 3),
                    "evidence_frame_id": frame_id,
                    "blocking": False,
                },
            ]
        return [
            {
                "event_type": "specimen_not_ready",
                "status": "blocked",
                "confidence": round(confidence, 3),
                "evidence_frame_id": frame_id,
                "blocking": True,
            }
        ]

    def _signal(
        self,
        *,
        state: OrchestratorState,
        signal: str,
        zone_id: str,
        value: bool | str,
        confidence: float,
        stable_for_ms: int,
        target_agent: str,
        status: str,
        timestamp: str,
        blocking_reason: str | None = None,
    ) -> dict[str, Any]:
        try:
            timestamp_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            timestamp_dt = self._now()
            timestamp = timestamp_dt.isoformat()
        expires_at = (timestamp_dt + timedelta(milliseconds=self.SIGNAL_TTL_MS)).isoformat()
        signal_id = f"sig-{state.run_id}-{state.loop_count}-{signal}-{self._stable_digest([zone_id, value, confidence], 6)}"
        specimen = self._specimen_result(state)
        return {
            "schema": "vision_signal_item.v1",
            "signal_id": signal_id,
            "run_id": state.run_id,
            "loop_id": state.loop_count,
            "experiment_id": state.experiment_id,
            "specimen_id": specimen.get("specimen_id", ""),
            "signal": signal,
            "zone_id": zone_id,
            "value": value,
            "status": status,
            "confidence": round(confidence, 3),
            "stable_for_ms": stable_for_ms,
            "timestamp": timestamp,
            "expires_at": expires_at,
            "target_agent": target_agent,
            "consumer_agents": [target_agent],
            "requires_ack": target_agent in {"manipulation_agent", "equipment_agent", "guardian_agent"},
            "blocking_reason": blocking_reason,
        }

    def _agent_signals(
        self,
        *,
        state: OrchestratorState,
        ready: bool,
        capture_ok: bool,
        anomaly: bool,
        confidence: float,
        timestamp: str,
        stable_for_ms: int,
        active_cam_confirmed: bool = False,
    ) -> list[dict[str, Any]]:
        blocking_reason = None
        if not capture_ok:
            blocking_reason = "camera_capture_failed"
        elif anomaly:
            blocking_reason = "anomaly_detected"
        elif not ready:
            blocking_reason = "specimen_or_pose_not_ready"

        ready_conf = confidence if ready else min(confidence, 0.55)
        clear_conf = round(0.82 if capture_ok and not anomaly else 0.0, 3)
        not_checked_reason = "not_observed_in_current_stage"
        signals = [
            self._signal(
                state=state,
                signal="printer_output_visible",
                zone_id="printer_bed",
                value=False if capture_ok else "unknown",
                confidence=0.72 if capture_ok else 0.0,
                stable_for_ms=stable_for_ms if capture_ok else 0,
                target_agent="specimen_agent",
                status="clear" if capture_ok else "blocked",
                timestamp=timestamp,
                blocking_reason=None if capture_ok else "camera_capture_failed",
            ),
            self._signal(
                state=state,
                signal="specimen_ejected_to_basket",
                zone_id="ejection_basket",
                value=ready,
                confidence=ready_conf,
                stable_for_ms=stable_for_ms if ready else 0,
                target_agent="specimen_agent",
                status="observed" if ready else "blocked",
                timestamp=timestamp,
                blocking_reason=blocking_reason,
            ),
            self._signal(
                state=state,
                signal="spc_autoejection_confirmed",
                zone_id="active_cam_ejection_area",
                value=active_cam_confirmed,
                confidence=ready_conf if active_cam_confirmed else 0.0,
                stable_for_ms=stable_for_ms if active_cam_confirmed else 0,
                target_agent="specimen_agent",
                status="confirmed" if active_cam_confirmed else "not_checked",
                timestamp=timestamp,
                blocking_reason=None if active_cam_confirmed else "active_cam_confirmation_not_available",
            ),
            self._signal(
                state=state,
                signal="basket_contains_specimen",
                zone_id="ejection_basket",
                value=ready,
                confidence=ready_conf,
                stable_for_ms=stable_for_ms if ready else 0,
                target_agent="manipulation_agent",
                status="observed" if ready else "blocked",
                timestamp=timestamp,
                blocking_reason=blocking_reason,
            ),
            self._signal(
                state=state,
                signal="pickup_ready",
                zone_id="ejection_basket",
                value=ready,
                confidence=ready_conf,
                stable_for_ms=stable_for_ms if ready else 0,
                target_agent="manipulation_agent",
                status="ready" if ready else "blocked",
                timestamp=timestamp,
                blocking_reason=blocking_reason,
            ),
            self._signal(
                state=state,
                signal="basket_empty_after_pick",
                zone_id="ejection_basket",
                value=False,
                confidence=0.0,
                stable_for_ms=0,
                target_agent="manipulation_agent",
                status="not_checked",
                timestamp=timestamp,
                blocking_reason=not_checked_reason,
            ),
            self._signal(
                state=state,
                signal="gripper_holding_specimen",
                zone_id="robot_gripper",
                value=False,
                confidence=0.0,
                stable_for_ms=0,
                target_agent="manipulation_agent",
                status="not_checked",
                timestamp=timestamp,
                blocking_reason=not_checked_reason,
            ),
            self._signal(
                state=state,
                signal="specimen_on_utm_platen",
                zone_id="utm_platen",
                value=False,
                confidence=0.0,
                stable_for_ms=0,
                target_agent="equipment_agent",
                status="not_checked",
                timestamp=timestamp,
                blocking_reason=not_checked_reason,
            ),
            self._signal(
                state=state,
                signal="fixture_alignment_ok",
                zone_id="utm_platen",
                value=False,
                confidence=0.0,
                stable_for_ms=0,
                target_agent="equipment_agent",
                status="not_checked",
                timestamp=timestamp,
                blocking_reason=not_checked_reason,
            ),
            self._signal(
                state=state,
                signal="utm_motion_observed",
                zone_id="utm_screen",
                value=False,
                confidence=0.0,
                stable_for_ms=0,
                target_agent="equipment_agent",
                status="not_checked",
                timestamp=timestamp,
                blocking_reason=not_checked_reason,
            ),
            self._signal(
                state=state,
                signal="utm_home_restored",
                zone_id="utm_screen",
                value=False,
                confidence=0.0,
                stable_for_ms=0,
                target_agent="equipment_agent",
                status="not_checked",
                timestamp=timestamp,
                blocking_reason=not_checked_reason,
            ),
            self._signal(
                state=state,
                signal="equipment_screen_state",
                zone_id="utm_screen",
                value="unknown",
                confidence=0.0,
                stable_for_ms=0,
                target_agent="equipment_agent",
                status="not_checked",
                timestamp=timestamp,
                blocking_reason=not_checked_reason,
            ),
            self._signal(
                state=state,
                signal="robot_workspace_clear",
                zone_id="robot_workspace",
                value=bool(capture_ok and not anomaly),
                confidence=clear_conf,
                stable_for_ms=stable_for_ms if capture_ok and not anomaly else 0,
                target_agent="guardian_agent",
                status="clear" if capture_ok and not anomaly else "warning",
                timestamp=timestamp,
                blocking_reason="workspace_review_required" if anomaly or not capture_ok else None,
            ),
            self._signal(
                state=state,
                signal="visual_test_evidence_ready",
                zone_id="camera_top",
                value=capture_ok,
                confidence=1.0 if capture_ok else 0.0,
                stable_for_ms=stable_for_ms if capture_ok else 0,
                target_agent="knowledge_agent",
                status="record" if capture_ok else "blocked",
                timestamp=timestamp,
                blocking_reason=None if capture_ok else "no_frame_evidence",
            ),
            self._signal(
                state=state,
                signal="data_quality_low",
                zone_id="camera_top",
                value=bool((not capture_ok) or anomaly or confidence < 0.6),
                confidence=round(1.0 - max(0.0, min(1.0, confidence)), 3) if capture_ok else 1.0,
                stable_for_ms=stable_for_ms if capture_ok else 0,
                target_agent="knowledge_agent",
                status="warning" if (not capture_ok) or anomaly or confidence < 0.6 else "clear",
                timestamp=timestamp,
                blocking_reason="low_quality_visual_evidence" if (not capture_ok) or anomaly or confidence < 0.6 else None,
            ),
            self._signal(
                state=state,
                signal="anomaly_detected",
                zone_id="robot_workspace",
                value=anomaly or not capture_ok,
                confidence=0.9 if anomaly or not capture_ok else 0.1,
                stable_for_ms=stable_for_ms if anomaly else 0,
                target_agent="guardian_agent",
                status="warning" if anomaly else "clear" if capture_ok else "blocked",
                timestamp=timestamp,
                blocking_reason="operator_review_required" if anomaly or not capture_ok else None,
            ),
        ]
        return signals

    def _post_manipulation_signals(
        self,
        *,
        state: OrchestratorState,
        ready: bool,
        capture_ok: bool,
        anomaly: bool,
        confidence: float,
        timestamp: str,
        stable_for_ms: int,
    ) -> list[dict[str, Any]]:
        waiting_status = "verified" if ready else "waiting" if capture_ok and not anomaly else "blocked"
        wait_reason = None if capture_ok and not anomaly else "utm_camera_capture_failed"
        return [
            self._signal(
                state=state,
                signal="specimen_on_utm_platen",
                zone_id="utm_platen",
                value=ready,
                confidence=confidence if ready else 0.0,
                stable_for_ms=stable_for_ms if ready else 0,
                target_agent="manipulation_agent",
                status=waiting_status,
                timestamp=timestamp,
                blocking_reason=wait_reason,
            ),
            self._signal(
                state=state,
                signal="fixture_alignment_ok",
                zone_id="utm_platen",
                value=ready,
                confidence=confidence if ready else 0.0,
                stable_for_ms=stable_for_ms if ready else 0,
                target_agent="equipment_agent",
                status=waiting_status,
                timestamp=timestamp,
                blocking_reason=wait_reason,
            ),
            self._signal(
                state=state,
                signal="robot_workspace_clear",
                zone_id="robot_workspace",
                value=bool(capture_ok and not anomaly),
                confidence=0.82 if capture_ok and not anomaly else 0.0,
                stable_for_ms=stable_for_ms if capture_ok and not anomaly else 0,
                target_agent="guardian_agent",
                status="clear" if capture_ok and not anomaly else "blocked",
                timestamp=timestamp,
                blocking_reason=None if capture_ok and not anomaly else "workspace_review_required",
            ),
            self._signal(
                state=state,
                signal="visual_test_evidence_ready",
                zone_id="utm_camera",
                value=capture_ok,
                confidence=1.0 if capture_ok else 0.0,
                stable_for_ms=stable_for_ms if capture_ok else 0,
                target_agent="knowledge_agent",
                status="record" if capture_ok else "blocked",
                timestamp=timestamp,
                blocking_reason=None if capture_ok else "no_frame_evidence",
            ),
            self._signal(
                state=state,
                signal="data_quality_low",
                zone_id="utm_camera",
                value=bool(capture_ok and not anomaly and confidence < 0.6),
                confidence=round(1.0 - max(0.0, min(1.0, confidence)), 3) if capture_ok else 1.0,
                stable_for_ms=stable_for_ms if capture_ok else 0,
                target_agent="knowledge_agent",
                status="warning" if capture_ok and not anomaly and confidence < 0.6 else "clear" if capture_ok and not anomaly else "blocked",
                timestamp=timestamp,
                blocking_reason=None if capture_ok and not anomaly else "low_quality_visual_evidence",
            ),
            self._signal(
                state=state,
                signal="anomaly_detected",
                zone_id="robot_workspace",
                value=anomaly or not capture_ok,
                confidence=0.9 if anomaly or not capture_ok else 0.1,
                stable_for_ms=stable_for_ms if anomaly else 0,
                target_agent="guardian_agent",
                status="warning" if anomaly else "clear" if capture_ok else "blocked",
                timestamp=timestamp,
                blocking_reason="operator_review_required" if anomaly or not capture_ok else None,
            ),
        ]

    def _scene_svg(self, zones: dict[str, Any], signals: list[dict[str, Any]], *, observation_id: str) -> str:
        zone_order = ["printer_bed", "ejection_basket", "robot_workspace", "robot_gripper", "utm_platen", "utm_screen"]
        colors = {"loaded": "#3fbf7f", "clear": "#7aa7ff", "review_required": "#f5b95b", "empty_or_unknown": "#d6dde8", "unknown": "#d6dde8"}
        rects = []
        for idx, zone_id in enumerate(zone_order):
            zone = zones.get(zone_id, {}) if isinstance(zones.get(zone_id), dict) else {}
            x = 30 + (idx % 3) * 240
            y = 70 + (idx // 3) * 120
            state = str(zone.get("state") or ("loaded" if zone.get("specimen_present") else "unknown"))
            color = colors.get(state, "#d6dde8")
            conf = zone.get("confidence", "-")
            rects.append(
                f'<rect x="{x}" y="{y}" width="205" height="82" rx="14" fill="{color}" stroke="#22324a" stroke-width="2"/>'
                f'<text x="{x + 14}" y="{y + 28}" font-size="16" font-family="Arial" fill="#111827">{zone_id}</text>'
                f'<text x="{x + 14}" y="{y + 54}" font-size="13" font-family="Arial" fill="#374151">state={state}</text>'
                f'<text x="{x + 14}" y="{y + 73}" font-size="13" font-family="Arial" fill="#374151">conf={conf}</text>'
            )
        signal_text = ", ".join(f"{s.get('signal')}={s.get('status')}" for s in signals[:4])
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="360" viewBox="0 0 760 360">'
            '<rect width="760" height="360" fill="#ffffff"/>'
            f'<text x="30" y="36" font-size="20" font-family="Arial" font-weight="700" fill="#111827">Vision scene map · {observation_id}</text>'
            + "".join(rects)
            + f'<text x="30" y="330" font-size="14" font-family="Arial" fill="#374151">signals: {signal_text}</text>'
            + '</svg>'
        )

    def _write_evidence_artifacts(
        self,
        *,
        state: OrchestratorState,
        observation_id: str,
        capture: dict[str, Any],
        zones: dict[str, Any],
        detections: list[dict[str, Any]],
        events: list[dict[str, Any]],
        signals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        output_dir = self._artifact_dir(state, observation_id)
        timestamp = self.now_iso()
        active_check = capture.get("active_cam_ejection_check") if isinstance(capture.get("active_cam_ejection_check"), dict) else {}
        active_run_artifact = active_check.get("run_artifact") if isinstance(active_check.get("run_artifact"), dict) else {}
        detection_payload = {
            "schema": "vision_detection_evidence.v1",
            "observation_id": observation_id,
            "created_at": timestamp,
            "zones": zones,
            "detections": detections,
            "events": events,
            "agent_signals": signals,
            "raw_capture_summary": {
                "tool": capture.get("tool"),
                "frame_id": capture.get("frame_id"),
                "camera_key": capture.get("camera_key"),
                "source": capture.get("source"),
                "ok": capture.get("ok"),
                "anomaly": capture.get("anomaly"),
            },
        }
        detection_path = output_dir / "detection.json"
        scene_path = output_dir / "scene_map.svg"
        detection_path.write_text(json.dumps(detection_payload, ensure_ascii=True, indent=2, default=str), encoding="utf-8")
        scene_path.write_text(self._scene_svg(zones, signals, observation_id=observation_id), encoding="utf-8")
        return {
            "frame_path": str(capture.get("frame_path") or capture.get("image_path") or ""),
            "active_cam_capture_path": str(active_check.get("capture_path") or ""),
            "active_cam_capture_url": str(active_check.get("capture_url") or ""),
            "active_cam_run_artifact": dict(active_run_artifact),
            "annotated_frame_path": str(scene_path),
            "before_after_path": str(capture.get("before_after_path") or ""),
            "detection_json_path": str(detection_path),
        }

    @staticmethod
    def _evidence_refs(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for key, label in (
            ("frame_path", "frame"),
            ("active_cam_capture_path", "active_cam_capture"),
            ("annotated_frame_path", "annotated_scene"),
            ("before_after_path", "before_after"),
            ("detection_json_path", "detection_json"),
        ):
            path = artifacts.get(key)
            if path:
                refs.append({"type": label, "path": str(path)})
        active_run_artifact = artifacts.get("active_cam_run_artifact")
        if isinstance(active_run_artifact, dict) and active_run_artifact.get("path"):
            refs.append(
                {
                    "type": "active_cam_run_artifact",
                    "path": str(active_run_artifact["path"]),
                    "url": str(active_run_artifact.get("url") or ""),
                }
            )
        return refs

    def _decisions(self, *, task: str, ready: bool, capture_ok: bool, anomaly: bool, signal_count: int) -> list[dict[str, Any]]:
        return [
            {
                "decision_id": "vision.task.resolved",
                "status": "ok",
                "rationale": f"Observation task resolved as {task}; Vision observes only and does not execute hardware actions.",
            },
            {
                "decision_id": "vision.capture.accepted",
                "status": "ok" if capture_ok else "blocked",
                "rationale": "Camera/simulator frame was accepted for scene-state estimation." if capture_ok else "No valid camera frame was available.",
            },
            {
                "decision_id": "vision.signal.arbitrated",
                "status": "ok" if ready and not anomaly else "blocked" if anomaly or not capture_ok else "warn",
                "rationale": f"{signal_count} agent signals emitted with confidence/stability/freshness metadata.",
            },
            {
                "decision_id": "vision.handoff.prepared",
                "status": "ok" if ready else "blocked",
                "rationale": "Manipulation may consume pickup_ready only before expires_at; stale signals must be ignored.",
            },
        ]

    @staticmethod
    def _metrics(*, zones: dict[str, Any], detections: list[dict[str, Any]], signals: list[dict[str, Any]], ready: bool, anomaly: bool) -> dict[str, Any]:
        confidences = [float(item.get("confidence", 0.0)) for item in signals if isinstance(item.get("confidence"), (int, float))]
        return {
            "zone_count": len(zones),
            "detection_count": len(detections),
            "signal_count": len(signals),
            "ready_signal_count": sum(1 for item in signals if item.get("status") in {"ready", "record", "observed"}),
            "max_signal_confidence": round(max(confidences), 3) if confidences else 0.0,
            "min_signal_confidence": round(min(confidences), 3) if confidences else 0.0,
            "transfer_ready": ready,
            "anomaly": anomaly,
            "freshness_ttl_ms": VisionAgent.SIGNAL_TTL_MS,
        }

    def _vision_packet(
        self,
        *,
        state: OrchestratorState,
        specimen: dict[str, Any],
        signals: list[dict[str, Any]],
        evidence_refs: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        ready: bool,
        anomaly: bool,
    ) -> dict[str, Any]:
        primary = next((item for item in signals if item.get("signal") == "pickup_ready"), signals[0] if signals else {})
        status = "ready" if ready else "warning" if anomaly else "blocked"
        return {
            "schema": "vision_signal.v1",
            "run_id": state.run_id,
            "loop_id": f"loop-{state.loop_count}",
            "specimen_id": specimen.get("specimen_id", ""),
            "producer_agent": self.name,
            "consumer_agent": ["manipulation_agent", "knowledge_agent", "guardian_agent"],
            "created_at": self.now_iso(),
            "status": status,
            "signal_id": primary.get("signal_id", ""),
            "zone_id": primary.get("zone_id", ""),
            "value": primary.get("value"),
            "confidence": primary.get("confidence", 0.0),
            "stable_for_ms": primary.get("stable_for_ms", 0),
            "timestamp": primary.get("timestamp", ""),
            "expires_at": primary.get("expires_at", ""),
            "consumer_agents": sorted({agent for signal in signals for agent in signal.get("consumer_agents", []) if agent}),
            "signals": signals,
            "evidence_refs": evidence_refs,
            "guardian_status": "warn" if anomaly else "not_checked",
            "decisions": decisions,
            "warnings": [signal.get("blocking_reason") for signal in signals if signal.get("blocking_reason")],
            "next_action": "manipulation_pickup_precheck" if ready else "operator_or_guardian_review",
        }

    def _vision_agent_report_snapshot(
        self,
        *,
        state: OrchestratorState,
        observation: dict[str, Any],
        vision_report: dict[str, Any],
        vision_packet: dict[str, Any],
        metrics: dict[str, Any],
        evidence_refs: list[dict[str, Any]],
        capture: dict[str, Any],
        ready: bool,
        anomaly: bool,
    ) -> dict[str, Any]:
        """Build the Live GUI Vision Agent screen contract from observation evidence."""
        camera = vision_report.get("camera_source", {}) if isinstance(vision_report.get("camera_source"), dict) else {}
        model = vision_report.get("model_backend", {}) if isinstance(vision_report.get("model_backend"), dict) else {}
        signals = [item for item in vision_report.get("signal_board", []) if isinstance(item, dict)]
        detections = [item for item in vision_report.get("detections", []) if isinstance(item, dict)]
        events = [item for item in vision_report.get("events", []) if isinstance(item, dict)]
        zones = vision_report.get("scene_map", {}) if isinstance(vision_report.get("scene_map"), dict) else {}
        artifacts = vision_report.get("artifacts", {}) if isinstance(vision_report.get("artifacts"), dict) else {}
        safety = vision_report.get("safety_anomaly", {}) if isinstance(vision_report.get("safety_anomaly"), dict) else {}
        pose = observation.get("pose_estimate", {}) if isinstance(observation.get("pose_estimate"), dict) else {}
        readiness = observation.get("transfer_readiness", {}) if isinstance(observation.get("transfer_readiness"), dict) else {}
        active_cam = capture.get("active_cam_ejection_check") if isinstance(capture.get("active_cam_ejection_check"), dict) else {}
        spc_confirmation = observation.get("spc_autoejection_confirmation") if isinstance(observation.get("spc_autoejection_confirmation"), dict) else {}
        utm_completion = observation.get("vision_manipulation_completion") if isinstance(observation.get("vision_manipulation_completion"), dict) else {}
        utm_run_artifact = capture.get("utm_completion_run_artifact") if isinstance(capture.get("utm_completion_run_artifact"), dict) else {}
        pickup_target = observation.get("pickup_target", {}) if isinstance(observation.get("pickup_target"), dict) else {}
        confidences = [self._as_float(signal.get("confidence"), 0.0) for signal in signals]
        bins = [
            {"bin": "0.00-0.25", "count": sum(1 for value in confidences if 0.0 <= value < 0.25)},
            {"bin": "0.25-0.50", "count": sum(1 for value in confidences if 0.25 <= value < 0.5)},
            {"bin": "0.50-0.75", "count": sum(1 for value in confidences if 0.5 <= value < 0.75)},
            {"bin": "0.75-1.00", "count": sum(1 for value in confidences if 0.75 <= value <= 1.0)},
        ]
        clear_signals = sum(1 for signal in signals if signal.get("status") in {"ready", "record", "observed", "clear"})
        blocked_signals = sum(1 for signal in signals if signal.get("status") in {"blocked", "warning"})
        confusion_matrix = {
            "labels": ["clear", "blocked"],
            "matrix": [
                [clear_signals, 0 if anomaly else max(0, len(detections) - clear_signals)],
                [blocked_signals if anomaly else 0, blocked_signals],
            ],
            "source": "signal_status_proxy",
        }
        segmentation_panels = []
        for index, detection in enumerate(detections[:6], start=1):
            segmentation_panels.append(
                {
                    "panel_id": f"seg-{index}",
                    "label": detection.get("label") or "object",
                    "zone": detection.get("zone") or "",
                    "bbox_xyxy": detection.get("bbox_xyxy", []),
                    "mask_path": detection.get("mask_path", ""),
                    "confidence": detection.get("confidence"),
                }
            )
        if not segmentation_panels:
            for index, (zone_id, zone) in enumerate(list(zones.items())[:6], start=1):
                zone_payload = zone if isinstance(zone, dict) else {}
                segmentation_panels.append(
                    {
                        "panel_id": f"zone-{index}",
                        "label": zone_id,
                        "zone": zone_id,
                        "state": zone_payload.get("state", "unknown"),
                        "confidence": zone_payload.get("confidence", 0.0),
                    }
                )
        failure_labels = vision_report.get("knowledge_payload", {}).get("failure_labels", []) if isinstance(vision_report.get("knowledge_payload"), dict) else []
        success_labels = vision_report.get("knowledge_payload", {}).get("success_labels", []) if isinstance(vision_report.get("knowledge_payload"), dict) else []
        agentic_progress = self._vision_agentic_progress(
            observation=observation,
            vision_packet=vision_packet,
            capture=capture,
            ready=ready,
            anomaly=anomaly,
        )
        return {
            "schema": "vision_agent_report.v1",
            "source_report_schema": vision_report.get("schema"),
            "report_id": f"vision-agent-report-{state.run_id or 'run'}-{state.loop_count + 1}",
            "source_report_id": vision_report.get("report_id"),
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "loop_index": state.loop_count + 1,
            "created_at": self.now_iso(),
            "producer_agent": self.name,
            "specimen_pose": observation.get("specimen_pose", {}),
            "transfer_readiness": observation.get("transfer_readiness", {}),
            "camera_health": {
                "camera_key": camera.get("camera_key"),
                "source": camera.get("source"),
                "frame_id": camera.get("frame_id"),
                "frame_age_ms": camera.get("frame_age_ms"),
                "capture_ok": bool(capture.get("ok")),
                "status": "ready" if capture.get("ok") and not anomaly else "review_required",
                "frame_path": artifacts.get("frame_path") or capture.get("frame_path") or capture.get("image_path") or "",
                "utm_runtime_status": capture.get("utm_runtime_status", {}),
            },
            "calibration_summary": {
                "calibration_id": camera.get("calibration_id"),
                "pose_backend": model.get("pose_backend"),
                "frame_width": capture.get("frame_width"),
                "frame_height": capture.get("frame_height"),
                "line_chart": [
                    {"x": "frame_age_ms", "value": camera.get("frame_age_ms") or 0},
                    {"x": "pose_confidence", "value": pose.get("confidence") or 0},
                    {"x": "stable_for_ms", "value": readiness.get("stable_for_ms") or vision_packet.get("stable_for_ms") or 0},
                ],
            },
            "confidence_distribution": {
                "histogram": bins,
                "max_confidence": metrics.get("max_signal_confidence"),
                "min_confidence": metrics.get("min_signal_confidence"),
                "signal_count": len(signals),
            },
            "inspection_feed": {
                "task": vision_report.get("task"),
                "summary": observation.get("summary"),
                "annotated_frame_path": artifacts.get("annotated_frame_path"),
                "frame_path": artifacts.get("frame_path"),
                "events": events,
                "detections": detections,
            },
            "active_cam_ejection_check": {
                "schema": "active_cam_ejection_check.v1",
                "status": active_cam.get("status") or ("not_configured" if not active_cam else "unknown"),
                "source": active_cam.get("source") or "lerobot.camera.test",
                "camera_key": active_cam.get("camera_key") or "",
                "camera_port": active_cam.get("camera_port") or "",
                "specimen_id": active_cam.get("specimen_id") or pickup_target.get("specimen_id", ""),
                "specimen_detected": bool(active_cam.get("specimen_detected")),
                "spc_autoejection_confirmed": bool(active_cam.get("spc_autoejection_confirmed") or spc_confirmation.get("confirmed")),
                "capture_path": active_cam.get("capture_path") or artifacts.get("active_cam_capture_path") or "",
                "capture_url": active_cam.get("capture_url") or artifacts.get("active_cam_capture_url") or "",
                "raw_capture_path": active_cam.get("raw_capture_path") or "",
                "annotated_capture_path": active_cam.get("annotated_capture_path") or "",
                "frame_width": active_cam.get("frame_width"),
                "frame_height": active_cam.get("frame_height"),
                "bbox_xyxy": list(active_cam.get("bbox_xyxy") or []),
                "center_px": list(active_cam.get("center_px") or []),
                "roi_xyxy": list(active_cam.get("roi_xyxy") or []),
                "confidence": active_cam.get("confidence", 0.0),
                "detector": active_cam.get("detector") or "",
                "placement_status": active_cam.get("placement_status") or "",
                "detection_failure_code": active_cam.get("detection_failure_code") or "",
                "synthetic_frame": active_cam.get("synthetic_frame"),
                "port_released": bool(active_cam.get("port_released")),
                "camera_returned_to_vla": bool(active_cam.get("camera_returned_to_vla")),
                "camera_owner_after": active_cam.get("camera_owner_after") or "",
                "robot_pose_included": bool(active_cam.get("robot_pose_included")),
                "capture_pose": active_cam.get("capture_pose") if isinstance(active_cam.get("capture_pose"), dict) else {},
                "resume_pose": active_cam.get("resume_pose") if isinstance(active_cam.get("resume_pose"), dict) else {},
                "detection_source": active_cam.get("detection_source") or "",
                "spc_signal": spc_confirmation.get("signal") or "",
                "blocking_reason": active_cam.get("blocking_reason") or spc_confirmation.get("blocking_reason") or "",
                "run_artifact": dict(active_cam.get("run_artifact")) if isinstance(active_cam.get("run_artifact"), dict) else {},
            },
            "utm_completion_confirmation": {
                **dict(utm_completion),
                "run_artifact": dict(utm_run_artifact),
            },
            "segmentation": {
                "panels": segmentation_panels,
                "detection_count": len(detections),
                "zone_count": len(zones),
            },
            "defect_summary": {
                "anomaly": anomaly,
                "low_confidence": safety.get("low_confidence"),
                "occlusion": safety.get("occlusion"),
                "human_or_obstacle_detected": safety.get("human_or_obstacle_detected"),
                "blocking_reason": safety.get("blocking_reason"),
                "failure_labels": failure_labels,
                "success_labels": success_labels,
            },
            "pose_estimation": {
                **pose,
                "ready": ready,
                "source_zone": (observation.get("pickup_target", {}) or {}).get("source_zone") if isinstance(observation.get("pickup_target"), dict) else "",
                "target_location": (observation.get("pickup_target", {}) or {}).get("target_location") if isinstance(observation.get("pickup_target"), dict) else "",
            },
            "confusion_matrix": confusion_matrix,
            "quality_metrics": {
                **metrics,
                "transfer_ready": ready,
                "blocking_reason": readiness.get("blocking_reason"),
                "freshness_ttl_ms": vision_report.get("freshness_policy", {}).get("ttl_ms") if isinstance(vision_report.get("freshness_policy"), dict) else self.SIGNAL_TTL_MS,
            },
            "evidence_review": {
                "artifacts": artifacts,
                "evidence_refs": evidence_refs,
                "dataset_ledger": vision_report.get("dataset_ledger", {}),
            },
            "handoff_recommendations": {
                "status": vision_packet.get("status"),
                "signal_id": vision_packet.get("signal_id"),
                "zone_id": vision_packet.get("zone_id"),
                "confidence": vision_packet.get("confidence"),
                "expires_at": vision_packet.get("expires_at"),
                "consumer_agents": vision_packet.get("consumer_agents"),
                "next_action": vision_packet.get("next_action"),
                "warnings": vision_packet.get("warnings", []),
            },
            "agentic_progress": agentic_progress,
            "visualization_manifest": [
                {"id": "inspection_feed", "section": "inspection_feed", "type": "image_overlays"},
                {"id": "active_cam_ejection_check", "section": "active_cam_ejection_check", "type": "image_evidence"},
                {"id": "confidence_distribution", "section": "confidence_distribution", "type": "histogram"},
                {"id": "calibration_summary", "section": "calibration_summary", "type": "calibration_line_chart"},
                {"id": "segmentation", "section": "segmentation", "type": "segmentation_panels"},
                {"id": "confusion_matrix", "section": "confusion_matrix", "type": "confusion_matrix"},
            ],
        }

    def _vision_agentic_progress(
        self,
        *,
        observation: dict[str, Any],
        vision_packet: dict[str, Any],
        capture: dict[str, Any],
        ready: bool,
        anomaly: bool,
    ) -> dict[str, Any]:
        """Compact Vision progress contract for Live GUI cards."""
        pose = observation.get("pose_estimate", {}) if isinstance(observation.get("pose_estimate"), dict) else {}
        specimen_pose = observation.get("specimen_pose", {}) if isinstance(observation.get("specimen_pose"), dict) else {}
        readiness = observation.get("transfer_readiness", {}) if isinstance(observation.get("transfer_readiness"), dict) else {}
        capture_ok = bool(capture.get("ok"))
        pose_confidence = self._as_float(pose.get("confidence") or specimen_pose.get("confidence"), 0.0)
        pose_ready = bool(capture_ok and not anomaly and (ready or pose_confidence >= 0.6 or specimen_pose))
        camera_release_ok = bool(readiness.get("camera_returned_to_vla") is True or specimen_pose.get("port_released") is True)
        handoff_ready = bool(ready and str(vision_packet.get("status", "")).lower() == "ready")
        active_cam = capture.get("active_cam_ejection_check") if isinstance(capture.get("active_cam_ejection_check"), dict) else {}
        if active_cam:
            active_status = "complete" if active_cam.get("spc_autoejection_confirmed") else "blocked" if active_cam.get("status") == "blocked" else "waiting"
            active_detail = str(active_cam.get("status") or "active cam pending")
        else:
            active_status = "complete" if capture_ok else "blocked"
            active_detail = "not required for current route" if capture_ok else "camera capture failed"
        utm_completion = observation.get("vision_manipulation_completion") if isinstance(observation.get("vision_manipulation_completion"), dict) else {}
        utm_requested = str(capture.get("purpose") or "").strip().lower() == "utm_placement_verification"
        utm_status = "complete" if ready and utm_completion.get("detected") is True else "waiting" if capture_ok else "blocked"
        utm_detail = str(
            utm_completion.get("blocking_reason")
            or utm_completion.get("status")
            or "post-place verification pending"
        )
        steps = [
            {
                "id": "capture",
                "label": "Capture",
                "status": "complete" if capture_ok else "blocked",
                "detail": "camera frame acquired" if capture_ok else str(capture.get("failure_code") or "camera capture failed"),
            },
            {
                "id": "specimen_pose",
                "label": "Specimen Pose",
                "status": "complete" if pose_ready else "waiting" if capture_ok else "blocked",
                "detail": f"confidence={pose_confidence:.2f}" if pose_confidence else "pose not available",
            },
            {
                "id": "camera_release",
                "label": "Camera Return",
                "status": "complete" if camera_release_ok else "waiting" if capture_ok else "blocked",
                "detail": "camera route returned to VLA" if camera_release_ok else str(readiness.get("blocking_reason") or "waiting for camera release"),
            },
            {
                "id": "active_cam",
                "label": "Active Cam",
                "status": active_status,
                "detail": active_detail,
            },
        ]
        if utm_requested:
            steps.append(
                {
                    "id": "utm_confirmation",
                    "label": "UTM Confirmation",
                    "status": utm_status,
                    "detail": utm_detail,
                }
            )
        steps.append(
            {
                "id": "handoff",
                "label": "Handoff",
                "status": "complete" if handoff_ready else "waiting" if capture_ok else "blocked",
                "detail": str(vision_packet.get("next_action") or vision_packet.get("status") or "handoff pending"),
            }
        )
        current = next((step["id"] for step in steps if step["status"] != "complete"), steps[-1]["id"])
        return {
            "schema": "vision_agentic_progress.v1",
            "current_step": current,
            "steps": steps,
        }

    def _transfer_observation(
        self,
        state: OrchestratorState,
        capture: dict[str, Any],
        *,
        rollout_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        specimen = self._specimen_result(state)
        fabrication_report = self._fabrication_report(state, specimen)
        geometry = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        size = geometry.get("size_mm") if isinstance(geometry.get("size_mm"), list) else []
        z_height = self._as_float(size[2], 10.0) if len(size) >= 3 else self._as_float(geometry.get("height_mm"), 10.0)
        specimen_ready = bool(specimen) and not bool(specimen.get("requires_operator_input")) and specimen.get("ok") is not False
        capture_ok = bool(capture.get("ok"))
        anomaly = bool(capture.get("anomaly", False)) or not capture_ok
        spc_confirmation = capture.get("spc_autoejection_confirmation") if isinstance(capture.get("spc_autoejection_confirmation"), dict) else {}
        active_cam_confirmed = bool(spc_confirmation.get("confirmed") or spc_confirmation.get("spc_autoejection_confirmed"))
        pose_confidence = self._as_float(capture.get("pose_confidence", capture.get("confidence")), 0.82 if capture_ok and specimen_ready else 0.55 if capture_ok else 0.0)
        pose_confidence = max(0.0, min(1.0, pose_confidence))
        frame_id = str(capture.get("frame_id", f"frame-{state.run_id}"))
        observation_id = str(capture.get("observation_id") or frame_id or f"obs-{state.run_id}")
        active_cam_payload = capture.get("active_cam_ejection_check") if isinstance(capture.get("active_cam_ejection_check"), dict) else {}
        active_cam_artifact_update: dict[str, Any] = {}
        if active_cam_payload:
            active_cam_artifact_update = self._persist_active_cam_run_artifact(
                state=state,
                observation_id=observation_id,
                active_check=active_cam_payload,
            )
            active_cam_payload = dict(active_cam_payload)
            if active_cam_artifact_update.get("status") == "stored":
                artifact_confirms_specimen = bool(
                    active_cam_payload.get("status") == "confirmed"
                    and active_cam_payload.get("spc_autoejection_confirmed") is True
                )
                active_cam_payload["capture_path"] = active_cam_artifact_update["path"]
                active_cam_payload["capture_url"] = active_cam_artifact_update["url"]
                active_cam_payload["run_artifact"] = dict(active_cam_artifact_update)
                spc_confirmation = {
                    **dict(spc_confirmation),
                    "schema": str(spc_confirmation.get("schema") or "spc_autoejection_confirmation.v1"),
                    "signal": str(
                        spc_confirmation.get("signal")
                        or "SPC_AUTOEJECTION_CONFIRMED_BY_ACTIVE_CAM"
                    ),
                    "status": "confirmed" if artifact_confirms_specimen else "not_detected",
                    "confirmed": artifact_confirms_specimen,
                    "capture_path": active_cam_artifact_update["path"],
                    "capture_url": active_cam_artifact_update["url"],
                    "run_artifact": dict(active_cam_artifact_update),
                }
            else:
                active_cam_payload.update(
                    {
                        "status": "blocked",
                        "spc_autoejection_confirmed": False,
                        "capture_path": "",
                        "capture_url": "",
                        "run_artifact": {},
                        "artifact_failure_code": active_cam_artifact_update.get(
                            "failure_code",
                            "ACTIVE_CAM_ARTIFACT_FAILED",
                        ),
                    }
                )
                spc_confirmation = {
                    **dict(spc_confirmation),
                    "schema": str(spc_confirmation.get("schema") or "spc_autoejection_confirmation.v1"),
                    "signal": str(
                        spc_confirmation.get("signal")
                        or "SPC_AUTOEJECTION_CONFIRMED_BY_ACTIVE_CAM"
                    ),
                    "status": "blocked",
                    "confirmed": False,
                    "capture_path": "",
                    "capture_url": "",
                    "run_artifact": {},
                    "artifact_failure_code": active_cam_artifact_update.get(
                        "failure_code",
                        "ACTIVE_CAM_ARTIFACT_FAILED",
                    ),
                }
            capture["active_cam_ejection_check"] = active_cam_payload
            capture["spc_autoejection_confirmation"] = spc_confirmation
        timestamp = str(capture.get("timestamp") or self.now_iso())
        stable_for_ms = self._as_int(capture.get("stable_for_ms"), 1200 if capture_ok and specimen_ready and not anomaly else 0)
        task = self._resolve_task(state, capture)
        placement_verification = task == "post_manipulation_utm_verification"
        utm_completion_artifact_update: dict[str, Any] = {}
        if placement_verification and not bool(capture.get("capture_skipped")):
            utm_completion_artifact_update = self._persist_utm_completion_run_artifact(
                state=state,
                observation_id=observation_id,
                capture=capture,
            )
            capture["utm_completion_run_artifact"] = dict(utm_completion_artifact_update)
            if utm_completion_artifact_update.get("status") == "stored":
                capture["annotated_frame_path"] = utm_completion_artifact_update["path"]
                capture["frame_path"] = utm_completion_artifact_update["path"]
        specimen_detected = capture.get("detected") is True
        ready = bool(capture_ok and specimen_ready and not anomaly)
        if not placement_verification:
            ready = bool(ready and pose_confidence >= 0.6)
        completion_blocking_reason = ""
        if placement_verification and not specimen_detected:
            ready = False
            completion_blocking_reason = str(
                capture.get("completion_blocking_reason")
                or capture.get("failure_code")
                or "specimen_not_detected_on_utm"
            )
        if placement_verification and specimen_detected and utm_completion_artifact_update.get("status") != "stored":
            ready = False
            completion_blocking_reason = str(
                utm_completion_artifact_update.get("failure_code")
                or "utm_completion_artifact_required"
            )
        rollout_execution = self._rollout_execution_evidence(state, rollout_status)
        if placement_verification and rollout_execution.get("required") and not rollout_execution.get("observed"):
            ready = False
            completion_blocking_reason = completion_blocking_reason or "rollout_action_evidence_required"
        if placement_verification and (state.mode == Mode.LIVE or self._physical_printer_tail_requested(state)):
            source = str(capture.get("source") or "").strip().lower()
            if source in {"", "simulator", "simulation", "mock", "virtual", "virtual_utm_bridge"}:
                ready = False
                completion_blocking_reason = "physical_utm_evidence_required"
        pose_payload = capture.get("specimen_pose") if isinstance(capture.get("specimen_pose"), dict) else {}
        camera_returned_to_vla = bool(capture.get("camera_returned_to_vla", True if not pose_payload else False))
        vla_camera_precheck_ok = bool(capture.get("vla_camera_precheck_ok", True if not pose_payload else False))
        if active_cam_payload:
            active_cam_confirmed = bool(
                active_cam_confirmed
                and active_cam_payload.get("spc_autoejection_confirmed")
                and active_cam_payload.get("status") == "confirmed"
            )
            camera_returned_to_vla = bool(camera_returned_to_vla and active_cam_payload.get("camera_returned_to_vla"))
            vla_camera_precheck_ok = bool(vla_camera_precheck_ok and active_cam_payload.get("port_released"))
            if not active_cam_confirmed:
                ready = False
        if (pose_payload or active_cam_payload) and (not camera_returned_to_vla or not vla_camera_precheck_ok):
            ready = False
        zones = self._zone_state(capture=capture, specimen_ready=specimen_ready, capture_ok=capture_ok, anomaly=anomaly, confidence=pose_confidence)
        detections = self._detections(capture=capture, specimen=specimen, specimen_ready=specimen_ready, capture_ok=capture_ok, anomaly=anomaly, confidence=pose_confidence)
        events = self._events(capture=capture, capture_ok=capture_ok, specimen_ready=specimen_ready, anomaly=anomaly, confidence=pose_confidence, frame_id=frame_id)
        signals = (
            self._post_manipulation_signals(
                state=state,
                ready=ready,
                capture_ok=capture_ok,
                anomaly=anomaly,
                confidence=pose_confidence,
                timestamp=timestamp,
                stable_for_ms=stable_for_ms,
            )
            if placement_verification
            else self._agent_signals(
                state=state,
                ready=ready,
                capture_ok=capture_ok,
                anomaly=anomaly,
                confidence=pose_confidence,
                timestamp=timestamp,
                stable_for_ms=stable_for_ms,
                active_cam_confirmed=active_cam_confirmed,
            )
        )
        completion_signal: dict[str, Any] = {}
        if placement_verification:
            utm_status = "verified" if ready else "detected" if specimen_detected else "waiting" if capture_ok and not anomaly else "blocked"
            zones["utm_platen"] = {
                **(zones.get("utm_platen") if isinstance(zones.get("utm_platen"), dict) else {}),
                "specimen_present": specimen_detected,
                "aligned": specimen_detected,
                "confidence": round(pose_confidence if specimen_detected else 0.0, 3),
                "state": "loaded_and_aligned" if specimen_detected else "placement_not_confirmed",
            }
            for signal in signals:
                if signal.get("signal") in {"specimen_on_utm_platen", "fixture_alignment_ok"}:
                    signal["value"] = specimen_detected
                    signal["confidence"] = round(pose_confidence if specimen_detected else 0.0, 3)
                    signal["stable_for_ms"] = stable_for_ms if specimen_detected else 0
                    signal["status"] = utm_status
                    signal["blocking_reason"] = None if specimen_detected else completion_blocking_reason
            metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
            manipulation = metadata.get("manipulation_result") if isinstance(metadata.get("manipulation_result"), dict) else {}
            robot_task = metadata.get("robot_task_result") if isinstance(metadata.get("robot_task_result"), dict) else {}
            session_id = str(
                capture.get("session_id")
                or robot_task.get("rollout_session_id")
                or robot_task.get("episode_id")
                or manipulation.get("session_id")
                or ""
            )
            completion_signal = {
                "schema": "vision_manipulation_completion.v1",
                "signal": "vision_manipulation_completion",
                "run_id": state.run_id,
                "loop_id": int(state.loop_count or 0),
                "specimen_id": specimen.get("specimen_id", ""),
                "detected": specimen_detected,
                "value": specimen_detected,
                "confidence": round(pose_confidence if specimen_detected else 0.0, 3),
                "camera": capture.get("camera_key") or capture.get("camera") or "utm",
                "timestamp": timestamp,
                "evidence_path": str(
                    capture.get("annotated_frame_path")
                    or capture.get("frame_path")
                    or capture.get("path")
                    or ""
                ),
                "ready_to_stop_rollout": ready,
                "session_id": session_id,
                "target_agent": "equipment_agent" if ready else "manipulation_agent",
                "status": "detected" if specimen_detected else "waiting",
                "blocking_reason": completion_blocking_reason,
                "rollout_execution": rollout_execution,
                "post_place_interlock": (
                    dict(capture.get("post_place_interlock"))
                    if isinstance(capture.get("post_place_interlock"), dict)
                    else {}
                ),
            }
            signals.append(completion_signal)
        artifacts = self._write_evidence_artifacts(
            state=state,
            observation_id=observation_id,
            capture=capture,
            zones=zones,
            detections=detections,
            events=events,
            signals=signals,
        )
        evidence_refs = self._evidence_refs(artifacts)
        decisions = self._decisions(task=task, ready=ready, capture_ok=capture_ok, anomaly=anomaly, signal_count=len(signals))
        if placement_verification and capture_ok and not anomaly and not ready:
            for decision in decisions:
                if decision.get("decision_id") in {"vision.signal.arbitrated", "vision.handoff.prepared"}:
                    decision["status"] = "waiting"
                    decision["rationale"] = "UTM placement monitoring is active; the rollout remains in the current session."
        metrics = self._metrics(zones=zones, detections=detections, signals=signals, ready=ready, anomaly=anomaly)
        source_location = "3dp_output_area"
        fabrication_outcome = fabrication_report.get("fabrication_outcome") if isinstance(fabrication_report.get("fabrication_outcome"), dict) else {}
        physical_location = str(fabrication_outcome.get("location") or "ejection_basket")
        if pose_payload:
            source_location = str(pose_payload.get("workspace") or physical_location or "a4_workspace")
            physical_location = source_location
        if placement_verification:
            source_location = "utm_fixture"
            physical_location = "utm_fixture"
        pose = {
            "x_mm": self._as_float(capture.get("x_mm"), 0.0),
            "y_mm": self._as_float(capture.get("y_mm"), 0.0),
            "z_mm": self._as_float(capture.get("z_mm"), max(1.0, z_height / 2.0)),
            "roll_deg": self._as_float(capture.get("roll_deg"), 0.0),
            "pitch_deg": self._as_float(capture.get("pitch_deg"), 0.0),
            "yaw_deg": self._as_float(capture.get("yaw_deg"), 0.0),
            "confidence": round(pose_confidence, 3),
            "source": "specimen_pose.v1" if pose_payload else "capture_fields",
        }
        vision_report = {
            "schema": "vision_report.v1",
            "report_id": f"vision-report-{self._stable_digest([state.run_id, observation_id], 8)}",
            "task": task,
            "stage": state.stage.value,
            "model_backend": {
                "mode": str(capture.get("backend_mode") or "simulator"),
                "dino_model_id": str(capture.get("dino_model_id") or "facebook/dinov3-convnext-tiny-pretrain-lvd1689m"),
                "weights_available": bool(capture.get("weights_available", False)),
                "degraded_to": "simulator" if not capture.get("weights_available") else "none",
                "detector": str(capture.get("detector") or "rule_or_mock"),
                "tracker": str(capture.get("tracker") or "not_enabled"),
                "pose_backend": str(capture.get("pose_backend") or "2d_bbox_plus_height_estimate"),
            },
            "camera_source": {
                "camera_key": capture.get("camera_key") or capture.get("camera") or "top",
                "source": capture.get("source") or ("live_camera" if state.mode == Mode.LIVE else "simulator"),
                "frame_id": frame_id,
                "timestamp": timestamp,
                "calibration_id": str(capture.get("calibration_id") or "default-top-workspace"),
                "frame_age_ms": self._as_int(capture.get("frame_age_ms"), 0),
            },
            "scene_map": zones,
            "zones": zones,
            "detections": detections,
            "events": events,
            "agent_signals": signals,
            "signal_board": signals,
            "artifacts": artifacts,
            "safety_anomaly": {
                "anomaly": anomaly,
                "low_confidence": pose_confidence < 0.6,
                "occlusion": bool(capture.get("occlusion", False)),
                "human_or_obstacle_detected": bool(capture.get("human_or_obstacle_detected", False)),
                "blocking_reason": next((signal.get("blocking_reason") for signal in signals if signal.get("blocking_reason")), None),
            },
            "dataset_ledger": {
                "episode_id": str(capture.get("episode_id") or f"vision-{state.run_id}-{state.loop_count}"),
                "camera_key": capture.get("camera_key") or "top",
                "frame_ts": timestamp,
                "source_stage": state.stage.value,
                "signal_type": "vision_manipulation_completion" if placement_verification else "pickup_ready",
                "candidate_for_lerobot_dataset": bool(capture_ok),
            },
            "knowledge_payload": {
                "specimen_id": specimen.get("specimen_id", ""),
                "candidate_id": specimen.get("candidate_id", ""),
                "success_labels": [event.get("event_type") for event in events if event.get("status") in {"observed", "ready"} and not event.get("blocking")],
                "failure_labels": [event.get("event_type") for event in events if event.get("blocking")],
                "visual_notes": (
                    "UTM placement verified"
                    if placement_verification and ready
                    else "UTM placement monitoring in progress"
                    if placement_verification and capture_ok and not anomaly
                    else "pickup zone ready"
                    if ready
                    else "vision review required before manipulation"
                ),
                "store_in_memory": True,
            },
            "cross_agent_contract": {
                "manipulation_precondition": "pickup_ready must be true and not expired",
                "equipment_cross_check": "future UTM fixture signals must be refreshed before equipment action",
                "knowledge_memory": "visual evidence is stored as success/failure context",
                "guardian_gate": "anomaly_detected or stale signal requires review",
            },
            "freshness_policy": {
                "ttl_ms": self.SIGNAL_TTL_MS,
                "stale_action": "block_downstream_use",
            },
            "specimen_pose": pose_payload,
            "spc_autoejection_confirmation": spc_confirmation,
        }
        vision_packet = self._vision_packet(
            state=state,
            specimen=specimen,
            signals=signals,
            evidence_refs=evidence_refs,
            decisions=decisions,
            ready=ready,
            anomaly=anomaly,
        )
        if placement_verification and capture_ok and not anomaly and not ready:
            vision_packet["status"] = "waiting"
            vision_packet["next_action"] = "continue_utm_monitoring"
            vision_packet["warnings"] = []
        observation = {
            "observation_id": observation_id,
            "frame_id": frame_id,
            "camera_key": capture.get("camera_key") or capture.get("camera") or "top",
            "source": capture.get("source") or ("live_camera" if state.mode == Mode.LIVE else "simulator"),
            "summary": (
                "specimen detected on UTM platen; manipulation completion signal emitted"
                if placement_verification and ready
                else "monitoring UTM placement; rollout remains active"
                if placement_verification and capture_ok and not anomaly
                else "specimen detected in ejection basket; pickup_ready signal emitted"
                if ready
                else "vision review required before robot transfer"
            ),
            "anomaly": anomaly,
            "pose_estimate": pose,
            "pickup_target": {
                "specimen_id": specimen.get("specimen_id", ""),
                "candidate_id": specimen.get("candidate_id", ""),
                "source_location": source_location,
                "source_zone": "utm_platen" if placement_verification else "ejection_basket",
                "physical_location": physical_location,
                "target_location": "utm_fixture",
                "stl_path": specimen.get("stl_path", ""),
                "sliced_path": specimen.get("sliced_path", ""),
            },
            "transfer_readiness": {
                "ready": ready,
                "camera_ok": capture_ok,
                "specimen_ready": specimen_ready,
                "pose_confidence": round(pose_confidence, 3),
                "camera_returned_to_vla": camera_returned_to_vla,
                "vla_camera_precheck_ok": vla_camera_precheck_ok,
                "spc_autoejection_confirmed": active_cam_confirmed,
                "blocking_reason": (
                    None
                    if ready or (placement_verification and capture_ok and not anomaly)
                    else next((signal.get("blocking_reason") for signal in signals if signal.get("signal") == "pickup_ready"), "unknown")
                ),
                "signal_id": vision_packet.get("signal_id"),
                "expires_at": vision_packet.get("expires_at"),
            },
            "vision_report": vision_report,
            "agent_signals": signals,
            "vision_signal": vision_packet,
            "raw_capture": capture,
            "specimen_pose": pose_payload,
            "vision_manipulation_completion": completion_signal,
            "spc_autoejection_confirmation": spc_confirmation,
            "utm_runtime_status": capture.get("utm_runtime_status", {}),
        }
        vision_agent_report = self._vision_agent_report_snapshot(
            state=state,
            observation=observation,
            vision_report=vision_report,
            vision_packet=vision_packet,
            metrics=metrics,
            evidence_refs=evidence_refs,
            capture=capture,
            ready=ready,
            anomaly=anomaly,
        )
        observation["vision_agent_report"] = vision_agent_report
        route_to_completion_monitor = self._post_manipulation_handoff_requested(state)
        payload = {
            "observation": observation,
            "vision_report": vision_report,
            "vision_agent_report": vision_agent_report,
            "vision_signal": vision_packet,
            "decisions": decisions,
            "metrics": metrics,
            "evidence_refs": evidence_refs,
        }
        if active_cam_artifact_update:
            payload["active_cam_artifact_update"] = dict(active_cam_artifact_update)
        if utm_completion_artifact_update:
            payload["utm_completion_artifact_update"] = dict(utm_completion_artifact_update)
        if route_to_completion_monitor:
            completion_ready = bool(
                completion_signal.get("detected") and completion_signal.get("ready_to_stop_rollout")
            )
            payload["requested_next_stage"] = "equipment" if completion_ready else "vision"
            payload["transition_decision"] = (
                "vision_equipment_handoff" if completion_ready else "vision_utm_monitoring"
            )
        else:
            # The first Vision pass confirms ejection from the same active-camera
            # contract used by the LeRobot bridge. Only that confirmation can
            # release Manipulation; otherwise Vision remains responsible for retry.
            active_cam_check = (
                capture.get("active_cam_ejection_check")
                if isinstance(capture.get("active_cam_ejection_check"), dict)
                else {}
            )
            active_cam_confirmed = bool(
                active_cam_check.get("spc_autoejection_confirmed")
                and str(active_cam_check.get("status", "")).lower() == "confirmed"
            )
            payload["requested_next_stage"] = "manipulation" if active_cam_confirmed else "vision"
            payload["transition_decision"] = (
                "vision_manipulation_handoff" if active_cam_confirmed else "vision_active_cam_monitoring"
            )
        return payload

    def _auto_start_utm_runtime(self, state: OrchestratorState, ctx: AgentContext) -> dict[str, Any]:
        """Start the Vision ROS runtime when the shared device bridge tool exists."""
        if state.mode not in {Mode.TEST, Mode.LIVE}:
            return {}
        if "vision.utm_runtime.start" not in ctx.tools.list_tools():
            return {}
        try:
            return ctx.tools.call(
                "vision.utm_runtime.start",
                {"mode": state.mode.value, "source": "vision_agent.preflight", "agent": self.name},
            )
        except Exception as exc:
            return {
                "ok": False,
                "tool": "vision.utm_runtime.start",
                "status": "error",
                "failure_code": "VISION_UTM_RUNTIME_START_FAILED",
                "message": str(exc),
            }

    @staticmethod
    def _no_actuation_transfer_preflight(state: OrchestratorState) -> dict[str, Any]:
        """Resolve a printer-to-VLA plan without pretending a specimen was observed."""
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        policy = spec.get("execution_policy") if isinstance(spec.get("execution_policy"), dict) else {}
        if str(policy.get("printer") or "").strip().lower() != "preflight_only":
            return {}
        if str(policy.get("manipulation") or "").strip().lower() != "preflight_only":
            return {}
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        printer = metadata.get("printer_preflight") if isinstance(metadata.get("printer_preflight"), dict) else {}
        if printer.get("schema") != "printer_preflight.v1":
            return {}
        if printer.get("status") != "execution_ready_pending_approval":
            return {}
        if str(printer.get("run_id") or "").strip() != str(state.run_id or "").strip():
            return {}
        specimen = VisionAgent._specimen_result(state)
        expected_specimen_id = str(specimen.get("specimen_id") or "").strip()
        printer_specimen_id = str(printer.get("specimen_id") or "").strip()
        if not expected_specimen_id or printer_specimen_id != expected_specimen_id:
            return {}
        expected_candidate_id = str(specimen.get("candidate_id") or "").strip()
        printer_candidate_id = str(printer.get("candidate_id") or "").strip()
        if printer_candidate_id and expected_candidate_id and printer_candidate_id != expected_candidate_id:
            return {}
        if any(
            bool(printer.get(key))
            for key in ("actuation_performed", "upload_performed", "start_command_published", "print_started")
        ):
            return {}
        artifact_path = str(
            printer.get("immutable_artifact_path")
            or printer.get("artifact_path")
            or ""
        ).strip()
        artifact_sha256 = str(printer.get("artifact_sha256") or "").strip()
        if not artifact_path or not artifact_sha256:
            return {}
        if "://" not in artifact_path:
            local_artifact = Path(artifact_path).expanduser()
            if not local_artifact.is_file():
                return {}
            if hashlib.sha256(local_artifact.read_bytes()).hexdigest() != artifact_sha256:
                return {}
        return printer

    def _planned_transfer_result(
        self,
        *,
        state: OrchestratorState,
        frame_id: str,
        specimen: dict[str, Any],
        printer_preflight: dict[str, Any],
    ) -> AgentResult:
        specimen_id = str(printer_preflight.get("specimen_id") or specimen.get("specimen_id") or "")
        bounds = (
            printer_preflight.get("source_object_bounds_mm")
            if isinstance(printer_preflight.get("source_object_bounds_mm"), dict)
            else {}
        )
        observation = {
            "schema": "vision_preflight_observation.v1",
            "frame_id": frame_id,
            "observation_id": f"preflight-{frame_id}",
            "source": "printer_artifact_geometry",
            "camera": "not_captured",
            "summary": "Printer artifact transfer geometry validated; physical perception deferred until execution.",
            "anomaly": False,
            "specimen_id": specimen_id,
            "pose_estimate": {},
            "pickup_target": {
                "source_location": "3dp_output_area",
                "target_location": "utm_fixture",
                "object_bounds_mm": bounds,
                "physical_pose_available": False,
            },
            "transfer_readiness": {
                "ready": False,
                "status": "preflight_only",
                "blocking_reason": "physical_specimen_not_created",
                "physical_observation_performed": False,
            },
            "agent_signals": [],
            "vision_signal": {
                "schema": "vision_signal.v1",
                "status": "preflight_only",
                "signals": [],
            },
            "utm_runtime_status": {
                "ok": True,
                "status": "not_started_preflight_only",
                "actuation_performed": False,
            },
        }
        preflight = {
            "schema": "vision_preflight.v1",
            "run_id": state.run_id,
            "status": "execution_ready_pending_approval",
            "capture_performed": False,
            "actuation_performed": False,
            "would_execute_tools": ["lerobot.active_robot_cam.capture", "camera.capture"],
            "planned_task": "post_ejection_basket_check",
            "consumer": "manipulation_agent",
            "specimen_id": specimen_id,
            "printer_artifact_path": str(
                printer_preflight.get("immutable_artifact_path")
                or printer_preflight.get("artifact_path")
                or ""
            ),
            "printer_artifact_sha256": str(printer_preflight.get("artifact_sha256") or ""),
            "source_object_bounds_mm": bounds,
        }
        vision_report = {
            "schema": "vision_report.v1",
            "status": "preflight_complete",
            "observation_id": observation["observation_id"],
            "signal_board": [],
            "transfer_readiness": observation["transfer_readiness"],
            "safety_anomaly": {"anomaly": False},
        }
        agent_report = {
            "schema": "vision_agent_report.v1",
            "status": "preflight_complete",
            "camera_health": {"status": "not_started_preflight_only"},
            "handoff_recommendations": {
                "status": "execution_ready_pending_approval",
                "recommended_next_agent": "manipulation_agent",
            },
        }
        decision = {
            "decision_id": "vision.transfer_preflight",
            "status": "pass",
            "rationale": "Transfer inputs are resolved from the immutable printer artifact; camera capture remains deferred.",
        }
        return AgentResult(
            success=True,
            summary="Vision transfer preflight complete without capture",
            data={
                "observation": observation,
                "vision_preflight": preflight,
                "vision_report": vision_report,
                "vision_agent_report": agent_report,
                "vision_signal": observation["vision_signal"],
                "handoff_packet": preflight,
                "decisions": [decision],
                "metrics": {"capture_performed": 0, "physical_detection_claimed": 0},
                "evidence_refs": [
                    {
                        "type": "printer_artifact",
                        "path": preflight["printer_artifact_path"],
                        "sha256": preflight["printer_artifact_sha256"],
                    }
                ],
                "requested_next_stage": "manipulation",
                "transition_decision": "vision_preflight_complete",
            },
            next_hint="manipulation",
        )

    @archive_agent_run
    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        frame_id = f"frame-{state.loop_count}-{state.stage.value}"
        timeout_s = 30.0 if state.mode == Mode.TEST else None
        specimen = self._specimen_result(state)
        printer_preflight = self._no_actuation_transfer_preflight(state)
        if printer_preflight:
            return self._planned_transfer_result(
                state=state,
                frame_id=frame_id,
                specimen=specimen,
                printer_preflight=printer_preflight,
            )
        utm_runtime_status = self._auto_start_utm_runtime(state, ctx)
        try:
            protocol = await ctx.complete(
                "tool_formatting",
                (
                    "Format a concise lab perception task before robot transfer. "
                    "Preserve Vision as observer/signal bus only; do not command hardware. "
                    f"frame_id={frame_id} specimen_id={specimen.get('specimen_id', '')}"
                ),
                timeout_s=timeout_s,
            )
            protocol_note = protocol.text[:220]
        except Exception as exc:
            if state.mode == Mode.TEST:
                protocol_note = f"Vision LLM degraded in test mode: {exc.__class__.__name__}"
            else:
                raise
        placement_handoff = self._post_manipulation_handoff_requested(state)
        post_place_context = self._post_manipulation_context(state)
        rollout_status = (
            self._refresh_rollout_status_for_utm_completion(
                state=state,
                ctx=ctx,
                post_place_context=post_place_context,
            )
            if placement_handoff
            else {}
        )
        status_interlock = (
            rollout_status.get("post_place_interlock")
            if isinstance(rollout_status.get("post_place_interlock"), dict)
            else {}
        )
        expected_session_id = str(post_place_context.get("session_id") or "")
        observed_session_id = str(
            status_interlock.get("session_id") or rollout_status.get("session_id") or ""
        )
        session_matches = not (
            expected_session_id and observed_session_id and expected_session_id != observed_session_id
        )
        if status_interlock and session_matches:
            post_place_context["post_place_interlock"] = dict(status_interlock)
        placement_verification = self._post_manipulation_completion_requested(state)
        if not placement_verification:
            placement_verification = bool(
                placement_handoff
                and session_matches
                and status_interlock.get("ready_for_utm_snapshot")
            )
        if placement_verification:
            tool_name = "vision.utm_specimen_presence.capture"
            if tool_name not in set(ctx.tools.list_tools()):
                response = {
                    "ok": False,
                    "tool": tool_name,
                    "frame_id": frame_id,
                    "observation_id": f"obs-{frame_id}",
                    "camera_key": "utm",
                    "purpose": "utm_placement_verification",
                    "source": "utm_ros_frame",
                    "detected": False,
                    "failure_code": "UTM_SPECIMEN_PRESENCE_TOOL_NOT_REGISTERED",
                    "message": "UTM specimen-presence capture tool is not registered.",
                }
            else:
                output_dir = self._artifact_dir(state, frame_id) / "utm_completion"
                physical_camera_runtime = self._camera_runtime_mode(state) == "live"
                virtual_test_bridge = bool(
                    self._camera_runtime_mode(state) == "test"
                    and not self._physical_printer_tail_requested(state)
                )
                tool_payload = {
                    "mode": self._camera_runtime_mode(state),
                    "runtime_mode": self._camera_runtime_mode(state),
                    "run_id": state.run_id,
                    "session_id": str(post_place_context.get("session_id") or ""),
                    "specimen_id": str(specimen.get("specimen_id") or ""),
                    "frame_id": frame_id,
                    "output_dir": str(output_dir),
                    "auto_start_runtime": not bool(utm_runtime_status.get("ok")),
                    "frame_attempts": 3 if physical_camera_runtime else 1,
                    "frame_retry_delay_sec": 0.2 if physical_camera_runtime else 0.0,
                    "allow_virtual_bridge_in_test": virtual_test_bridge,
                    "prefer_virtual_bridge_in_test": virtual_test_bridge,
                    "min_area_px": self._as_float(
                        (state.current_experiment_spec or {}).get("utm_specimen_min_area_px")
                        if isinstance(state.current_experiment_spec, dict)
                        else None,
                        300.0,
                    ),
                }
                response = dict(ctx.tools.call(tool_name, tool_payload))
                response.setdefault("frame_id", frame_id)
                response.setdefault("observation_id", f"obs-{response['frame_id']}")
                response["camera_key"] = "utm"
                response["purpose"] = "utm_placement_verification"
                response["session_id"] = str(response.get("session_id") or post_place_context.get("session_id") or "")
                response["pose_confidence"] = self._as_float(response.get("confidence"), 0.0)
                response["frame_path"] = str(
                    response.get("annotated_frame_path") or response.get("raw_frame_path") or ""
                )
                response["frame_width"] = response.get("width")
                response["frame_height"] = response.get("height")
            response["post_place_interlock"] = dict(post_place_context.get("post_place_interlock") or {})
        elif placement_handoff:
            response = self._post_place_interlock_waiting_capture(
                state,
                frame_id=frame_id,
                specimen=specimen,
            )
            response["post_place_interlock"] = dict(post_place_context.get("post_place_interlock") or {})
        elif self._should_request_active_cam_ejection_check(state):
            active_camera_key = self._active_cam_camera_key(state, {})
            response = self._attach_lerobot_camera_evidence(
                state,
                ctx,
                {
                    "ok": True,
                    "tool": "lerobot.active_robot_cam.capture",
                    "frame_id": frame_id,
                    "observation_id": f"obs-{frame_id}",
                    "camera_key": active_camera_key,
                    "purpose": "3dp_output_pickup_check",
                    "specimen_id": specimen.get("specimen_id", ""),
                    "source": "lerobot_active_robot_cam",
                    "timestamp": self.now_iso(),
                    "stable_for_ms": 0,
                    "confidence": 0.0,
                    "pose_confidence": 0.0,
                    "detected": False,
                    "anomaly": False,
                    "backend_mode": "active_cam",
                    "detector": "active_cam_specimen_pose",
                },
            )
        else:
            response = dict(
                ctx.tools.call(
                    "camera.capture",
                    self._capture_request(state, frame_id=frame_id, specimen=specimen),
                )
            )
            response = self._attach_lerobot_camera_evidence(state, ctx, response)
        response = dict(response)
        response["utm_runtime_status"] = utm_runtime_status
        payload = self._transfer_observation(
            state,
            dict(response),
            rollout_status=rollout_status,
        )
        observation = payload["observation"]
        monitoring_ok = bool(response.get("ok")) and not bool(observation.get("anomaly"))
        now = datetime.now(timezone.utc)
        intervention: dict[str, Any] = {}
        utm_rollout_stop_failure: dict[str, Any] = {}
        active_cam_check = (
            payload.get("vision_agent_report", {}).get("active_cam_ejection_check", {})
            if isinstance(payload.get("vision_agent_report"), dict)
            else {}
        )
        if isinstance(active_cam_check, dict) and active_cam_check.get("status") == "not_detected":
            intervention = begin_intervention(
                state.run_metadata,
                run_id=state.run_id,
                checkpoint="active_cam_ejection",
                capture=active_cam_check,
                now=now,
            )
        elif isinstance(active_cam_check, dict) and active_cam_check.get("status") == "confirmed":
            current = active_intervention(state.run_metadata)
            if current.get("checkpoint") == "active_cam_ejection":
                intervention = resolve_intervention(
                    state.run_metadata,
                    checkpoint="active_cam_ejection",
                    now=now,
                    capture=active_cam_check,
                )

        completion = observation.get("vision_manipulation_completion")
        rollout_stop: dict[str, Any] = {}
        if placement_verification and isinstance(completion, dict):
            if bool(response.get("ok")) and not bool(response.get("capture_skipped")) and completion.get("detected") is False:
                artifact = payload.get("utm_completion_artifact_update")
                artifact = artifact if isinstance(artifact, dict) else {}
                intervention = begin_intervention(
                    state.run_metadata,
                    run_id=state.run_id,
                    checkpoint="utm_post_place",
                    capture={
                        "capture_path": artifact.get("path") or response.get("frame_path"),
                        "capture_url": artifact.get("url") or response.get("frame_url"),
                        "camera_key": response.get("camera_key") or "utm",
                    },
                    now=now,
                    automatic_recovery=True,
                    timeout_seconds=300,
                    rollout_session_id=str(completion.get("session_id") or ""),
                )
                if intervention_deadline_expired(intervention, now=now):
                    stop_tool = "lerobot.rollout.stop"
                    if stop_tool not in set(ctx.tools.list_tools()):
                        utm_rollout_stop_failure = {
                            "ok": False,
                            "tool": stop_tool,
                            "status": "FAILED",
                            "failure_code": "UTM_ROLLOUT_STOP_TOOL_NOT_REGISTERED",
                            "message": "lerobot.rollout.stop tool is not registered.",
                        }
                    else:
                        manipulation = (
                            state.run_metadata.get("manipulation_result")
                            if isinstance(state.run_metadata.get("manipulation_result"), dict)
                            else {}
                        )
                        robot_task = (
                            state.run_metadata.get("robot_task_result")
                            if isinstance(state.run_metadata.get("robot_task_result"), dict)
                            else {}
                        )
                        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
                        stop_payload = {
                            "mode": str(manipulation.get("mode") or state.mode.value),
                            "runtime_mode": str(manipulation.get("runtime_mode") or manipulation.get("mode") or state.mode.value),
                            "profile_id": str(
                                manipulation.get("profile_id")
                                or robot_task.get("profile_id")
                                or spec.get("lerobot_profile_id")
                                or spec.get("robot_profile_id")
                                or ""
                            ),
                            "session_id": str(intervention.get("rollout_session_id") or completion.get("session_id") or ""),
                            "reason": "utm_specimen_detection_timeout",
                        }
                        try:
                            stop_result = dict(ctx.tools.call(stop_tool, stop_payload))
                            intervention = mark_intervention_waiting(
                                state.run_metadata,
                                checkpoint="utm_post_place",
                                now=now,
                                rollout_stop=stop_result,
                            )
                        except Exception as exc:
                            utm_rollout_stop_failure = {
                                "ok": False,
                                "tool": stop_tool,
                                "status": "FAILED",
                                "failure_code": "UTM_ROLLOUT_STOP_FAILED",
                                "message": str(exc),
                            }
            elif completion.get("detected") is True and completion.get("ready_to_stop_rollout") is True:
                rollout_stop = self._stop_verified_rollout(
                    state=state,
                    ctx=ctx,
                    completion=completion,
                )
                stop_confirmed = bool(
                    rollout_stop.get("ok")
                    and str(rollout_stop.get("status") or "").strip().upper() == "STOPPED"
                )
                completion["rollout_stopped"] = stop_confirmed
                completion["rollout_stop_status"] = str(rollout_stop.get("status") or "")
                current = active_intervention(state.run_metadata)
                if current.get("checkpoint") == "utm_post_place":
                    intervention = resolve_intervention(
                        state.run_metadata,
                        checkpoint="utm_post_place",
                        now=now,
                    )

        operator_wait = intervention.get("status") == "waiting_for_specimen"
        active_cam_operator_wait = bool(
            intervention.get("checkpoint") == "active_cam_ejection" and operator_wait
        )
        active_cam_physical_failure = bool(
            self._should_request_active_cam_ejection_check(state)
            and (state.mode == Mode.LIVE or self._physical_printer_tail_requested(state))
            and not response.get("ok")
            and not active_cam_operator_wait
        )
        result_data = {
            "observation": observation,
            "vision_report": payload["vision_report"],
            "vision_agent_report": payload["vision_agent_report"],
            "vision_signal": payload["vision_signal"],
            "handoff_packet": payload["vision_signal"],
            "decisions": payload["decisions"],
            "metrics": payload["metrics"],
            "evidence_refs": payload["evidence_refs"],
            "protocol_note": protocol_note,
            **({"rollout_stop": rollout_stop} if rollout_stop else {}),
            **(
                {
                    "vision_operator_intervention": intervention,
                    "operator_intervention_update": intervention,
                    "pending_operator_input": operator_wait,
                    "requires_response": operator_wait,
                }
                if intervention
                else {}
            ),
            **(
                {"active_cam_artifact_update": payload["active_cam_artifact_update"]}
                if payload.get("active_cam_artifact_update")
                else {}
            ),
            **(
                {"utm_completion_artifact_update": payload["utm_completion_artifact_update"]}
                if payload.get("utm_completion_artifact_update")
                else {}
            ),
            **(
                {
                    "requested_next_stage": payload["requested_next_stage"],
                    "transition_decision": payload["transition_decision"],
                }
                if payload.get("requested_next_stage")
                else {}
            ),
        }
        if active_cam_physical_failure:
            result_data.update(
                {
                    "failure_code": str(
                        response.get("failure_code")
                        or response.get("active_cam_ejection_check", {}).get("blocking_reason")
                        or "ACTIVE_CAM_CONFIRMATION_REQUIRED"
                    ),
                    "safe_stop_recommended": True,
                }
            )
        if utm_rollout_stop_failure:
            result_data.update(
                {
                    "utm_rollout_stop": utm_rollout_stop_failure,
                    "failure_code": str(utm_rollout_stop_failure["failure_code"]),
                    "safe_stop_recommended": True,
                }
            )
        completion_stop_failed = bool(
            placement_verification
            and isinstance(completion, dict)
            and completion.get("detected") is True
            and not (
                rollout_stop.get("ok")
                and str(rollout_stop.get("status") or "").strip().upper() == "STOPPED"
            )
        )
        if completion_stop_failed:
            result_data.pop("requested_next_stage", None)
            result_data.pop("transition_decision", None)
            result_data.update(
                {
                    "failure_code": str(
                        rollout_stop.get("failure_code") or "UTM_ROLLOUT_STOP_NOT_CONFIRMED"
                    ),
                    "safe_stop_recommended": True,
                }
            )
        return AgentResult(
            success=(
                True
                if operator_wait
                else False
                if utm_rollout_stop_failure or completion_stop_failed
                else monitoring_ok
                if placement_handoff
                else bool(response.get("ok")) and bool(observation["transfer_readiness"]["ready"])
            ),
            summary="Vision lab perception signal complete",
            data=result_data,
        )
