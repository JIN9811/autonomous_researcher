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
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState


class VisionAgent(BaseAgent):
    """Builds lab scene state and agent signals without executing hardware actions."""

    name = "vision_agent"
    SIGNAL_TTL_MS = 5000

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[1]

    @classmethod
    def _artifact_dir(cls, state: OrchestratorState, observation_id: str) -> Path:
        path = cls._repo_root() / "runs" / state.run_id / "vision" / observation_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _specimen_result(state: OrchestratorState) -> dict[str, Any]:
        raw = state.run_metadata.get("specimen_result") if isinstance(state.run_metadata, dict) else {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _fabrication_report(state: OrchestratorState, specimen: dict[str, Any]) -> dict[str, Any]:
        if isinstance(state.run_metadata, dict) and isinstance(state.run_metadata.get("fabrication_report"), dict):
            return state.run_metadata["fabrication_report"]
        report = specimen.get("fabrication_report") if isinstance(specimen.get("fabrication_report"), dict) else {}
        return report if isinstance(report, dict) else {}

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
        available_tools = set(ctx.tools.list_tools())
        if "lerobot.camera.test" not in available_tools:
            return capture
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        live_confirmed = bool(
            spec.get("confirm_live_execute")
            or spec.get("confirm_camera_capture")
            or spec.get("vision_confirm_camera_capture")
        )
        requested = (
            state.mode == Mode.TEST
            or str(spec.get("vision_camera_backend") or "").strip().lower() == "lerobot"
            or bool(spec.get("camera_enabled") or spec.get("vision_use_lerobot_camera"))
        )
        if not requested:
            return capture
        if state.mode == Mode.LIVE and not live_confirmed:
            enriched = dict(capture)
            enriched["camera_bridge_warning"] = "lerobot_camera_test_requires_live_confirmation"
            return enriched
        payload = {
            "mode": state.mode.value,
            "runtime_mode": state.mode.value,
            "camera_key": capture.get("camera_key") or "top",
            "profile_id": str(spec.get("lerobot_profile_id") or spec.get("robot_profile_id") or ""),
            "confirm_live_execute": live_confirmed,
        }
        try:
            result = ctx.tools.call("lerobot.camera.test", payload)
        except Exception as exc:
            enriched = dict(capture)
            enriched["lerobot_camera_test"] = {"ok": False, "failure_code": exc.__class__.__name__, "message": str(exc)}
            return enriched
        enriched = dict(capture)
        enriched["lerobot_camera_test"] = result
        capture_result = result.get("capture") if isinstance(result.get("capture"), dict) else {}
        if result.get("ok") and capture_result.get("path"):
            enriched["frame_path"] = str(capture_result.get("path"))
            enriched["frame_url"] = str(capture_result.get("serve_url") or "")
            enriched["source"] = "lerobot_camera_test"
            enriched["camera_key"] = result.get("camera_key") or enriched.get("camera_key") or "top"
            enriched["frame_width"] = capture_result.get("width")
            enriched["frame_height"] = capture_result.get("height")
            enriched["synthetic_frame"] = capture_result.get("synthetic")
        return enriched

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
            "annotated_frame_path": str(scene_path),
            "before_after_path": str(capture.get("before_after_path") or ""),
            "detection_json_path": str(detection_path),
        }

    @staticmethod
    def _evidence_refs(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for key, label in (
            ("frame_path", "frame"),
            ("annotated_frame_path", "annotated_scene"),
            ("before_after_path", "before_after"),
            ("detection_json_path", "detection_json"),
        ):
            path = artifacts.get(key)
            if path:
                refs.append({"type": label, "path": str(path)})
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

    def _transfer_observation(self, state: OrchestratorState, capture: dict[str, Any]) -> dict[str, Any]:
        specimen = self._specimen_result(state)
        fabrication_report = self._fabrication_report(state, specimen)
        geometry = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        size = geometry.get("size_mm") if isinstance(geometry.get("size_mm"), list) else []
        z_height = self._as_float(size[2], 10.0) if len(size) >= 3 else self._as_float(geometry.get("height_mm"), 10.0)
        specimen_ready = bool(specimen) and not bool(specimen.get("requires_operator_input")) and specimen.get("ok") is not False
        capture_ok = bool(capture.get("ok"))
        anomaly = bool(capture.get("anomaly", False)) or not capture_ok
        pose_confidence = self._as_float(capture.get("pose_confidence", capture.get("confidence")), 0.82 if capture_ok and specimen_ready else 0.55 if capture_ok else 0.0)
        pose_confidence = max(0.0, min(1.0, pose_confidence))
        frame_id = str(capture.get("frame_id", f"frame-{state.run_id}"))
        observation_id = str(capture.get("observation_id") or frame_id or f"obs-{state.run_id}")
        timestamp = str(capture.get("timestamp") or self.now_iso())
        stable_for_ms = self._as_int(capture.get("stable_for_ms"), 1200 if capture_ok and specimen_ready and not anomaly else 0)
        task = self._resolve_task(state, capture)
        ready = bool(capture_ok and specimen_ready and not anomaly and pose_confidence >= 0.6)
        zones = self._zone_state(capture=capture, specimen_ready=specimen_ready, capture_ok=capture_ok, anomaly=anomaly, confidence=pose_confidence)
        detections = self._detections(capture=capture, specimen=specimen, specimen_ready=specimen_ready, capture_ok=capture_ok, anomaly=anomaly, confidence=pose_confidence)
        events = self._events(capture=capture, capture_ok=capture_ok, specimen_ready=specimen_ready, anomaly=anomaly, confidence=pose_confidence, frame_id=frame_id)
        signals = self._agent_signals(state=state, ready=ready, capture_ok=capture_ok, anomaly=anomaly, confidence=pose_confidence, timestamp=timestamp, stable_for_ms=stable_for_ms)
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
        metrics = self._metrics(zones=zones, detections=detections, signals=signals, ready=ready, anomaly=anomaly)
        source_location = "3dp_output_area"
        fabrication_outcome = fabrication_report.get("fabrication_outcome") if isinstance(fabrication_report.get("fabrication_outcome"), dict) else {}
        physical_location = str(fabrication_outcome.get("location") or "ejection_basket")
        pose = {
            "x_mm": self._as_float(capture.get("x_mm"), 0.0),
            "y_mm": self._as_float(capture.get("y_mm"), 0.0),
            "z_mm": self._as_float(capture.get("z_mm"), max(1.0, z_height / 2.0)),
            "roll_deg": self._as_float(capture.get("roll_deg"), 0.0),
            "pitch_deg": self._as_float(capture.get("pitch_deg"), 0.0),
            "yaw_deg": self._as_float(capture.get("yaw_deg"), 0.0),
            "confidence": round(pose_confidence, 3),
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
                "signal_type": "pickup_ready",
                "candidate_for_lerobot_dataset": bool(capture_ok),
            },
            "knowledge_payload": {
                "specimen_id": specimen.get("specimen_id", ""),
                "candidate_id": specimen.get("candidate_id", ""),
                "success_labels": [event.get("event_type") for event in events if event.get("status") in {"observed", "ready"} and not event.get("blocking")],
                "failure_labels": [event.get("event_type") for event in events if event.get("blocking")],
                "visual_notes": "pickup zone ready" if ready else "vision review required before manipulation",
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
        observation = {
            "observation_id": observation_id,
            "frame_id": frame_id,
            "camera_key": capture.get("camera_key") or capture.get("camera") or "top",
            "source": capture.get("source") or ("live_camera" if state.mode == Mode.LIVE else "simulator"),
            "summary": "specimen detected in ejection basket; pickup_ready signal emitted" if ready else "vision review required before robot transfer",
            "anomaly": anomaly,
            "pose_estimate": pose,
            "pickup_target": {
                "specimen_id": specimen.get("specimen_id", ""),
                "candidate_id": specimen.get("candidate_id", ""),
                "source_location": source_location,
                "source_zone": "ejection_basket",
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
                "blocking_reason": None if ready else next((signal.get("blocking_reason") for signal in signals if signal.get("signal") == "pickup_ready"), "unknown"),
                "signal_id": vision_packet.get("signal_id"),
                "expires_at": vision_packet.get("expires_at"),
            },
            "vision_report": vision_report,
            "agent_signals": signals,
            "vision_signal": vision_packet,
            "raw_capture": capture,
        }
        return {
            "observation": observation,
            "vision_report": vision_report,
            "vision_signal": vision_packet,
            "decisions": decisions,
            "metrics": metrics,
            "evidence_refs": evidence_refs,
        }

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        frame_id = f"frame-{state.loop_count}-{state.stage.value}"
        timeout_s = 30.0 if state.mode == Mode.TEST else None
        specimen = self._specimen_result(state)
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
        response = ctx.tools.call(
            "camera.capture",
            {
                "frame_id": frame_id,
                "camera_key": "top",
                "purpose": "3dp_output_pickup_check",
                "specimen_id": specimen.get("specimen_id", ""),
                "mode": state.mode.value,
            },
        )
        response = self._attach_lerobot_camera_evidence(state, ctx, dict(response))
        payload = self._transfer_observation(state, dict(response))
        observation = payload["observation"]
        return AgentResult(
            success=bool(response.get("ok")) and bool(observation["transfer_readiness"]["ready"]),
            summary="Vision lab perception signal complete",
            data={
                "observation": observation,
                "vision_report": payload["vision_report"],
                "vision_signal": payload["vision_signal"],
                "handoff_packet": payload["vision_signal"],
                "decisions": payload["decisions"],
                "metrics": payload["metrics"],
                "evidence_refs": payload["evidence_refs"],
                "protocol_note": protocol_note,
            },
        )
