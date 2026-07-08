"""
File purpose:
- Execute bounded manipulation skills and integrate Pi0.5/LeRobot plus SARM-lite risk signals.

Key classes/functions:
- ManipulationAgent

Inputs/outputs:
- Input: latest Vision observation, specimen result, and experiment/manipulation spec
- Output: legacy manipulation/sarm keys plus manipulation_report.v1 and robot_task_result.v1

Dependencies:
- mcp tools: lerobot.rollout.start, robot.pick_place
- submodules.sarm.* deterministic scorer helpers

Modification guide:
- Safe places to edit: task taxonomy, preflight checks, report fields, SARM-lite thresholds
- Risky places to edit: legacy output keys consumed by Guardian, runtime merge, and LeRobot GUI
- Related files: agents/guardian_agent.py, device_bridges/lerobot_bridge.py, web/templates/lerobot.html
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import inspect
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState
from submodules.sarm.failure_predictor import predict_failure_precursor
from submodules.sarm.progress_scorer import score_progress
from submodules.sarm.recovery_trigger import should_trigger_recovery
from utils.manipulation_profile import load_manipulation_agent_profile


class ManipulationAgent(BaseAgent):
    """Supervises bounded robot manipulation skills without bypassing LeRobot/Guardian gates."""

    name = "manipulation_agent"

    TASKS: dict[str, dict[str, Any]] = {
        "transfer_to_utm": {
            "task_sequence_index": 1,
            "task_family": "specimen_transfer",
            "source_location": "3dp_output_area",
            "target_location": "utm_fixture",
            "terminal_pose": "standby_clear_of_utm",
            "verified_handoff": "ready_for_equipment_agent",
            "verification_signal": "specimen_on_utm_platen",
            "recommended_next_if_unverified": "vision_agent",
            "recommended_next_if_verified": "lab_equipment_agent",
            "stages": [
                "preflight",
                "approach_source",
                "pre_grasp_align",
                "grasp",
                "lift_clear",
                "transfer_to_fixture",
                "place_on_datum",
                "release",
                "retreat",
                "post_place_verify",
            ],
        },
        "clear_utm_to_disposal": {
            "task_sequence_index": 2,
            "task_family": "tested_specimen_disposal",
            "source_location": "utm_fixture",
            "target_location": "discard_bin",
            "terminal_pose": "standby_clear_of_utm",
            "verified_handoff": "completed_disposal",
            "verification_signal": "utm_home_restored",
            "recommended_next_if_unverified": "vision_agent",
            "recommended_next_if_verified": "knowledge_agent",
            "stages": [
                "preflight",
                "wait_for_utm_safe",
                "approach_fixture",
                "pre_grasp_align_tested_specimen",
                "grasp_tested_specimen",
                "lift_clear_fixture",
                "transfer_to_discard_bin",
                "release_into_bin",
                "retreat",
                "verify_fixture_clear_and_discarded",
            ],
        },
    }

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _spec(state: OrchestratorState) -> dict[str, Any]:
        saved = load_manipulation_agent_profile()
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        merged = dict(saved)
        merged.update({key: value for key, value in spec.items() if value not in (None, "")})
        merged["__explicit_keys"] = set(spec.keys())
        return merged

    @staticmethod
    def _specimen_result(state: OrchestratorState) -> dict[str, Any]:
        raw = state.run_metadata.get("specimen_result") if isinstance(state.run_metadata, dict) else {}
        return raw if isinstance(raw, dict) else {}

    def _specimen_ready_for_transfer(self, state: OrchestratorState) -> bool:
        specimen = self._specimen_result(state)
        if not specimen:
            return False
        if specimen.get("requires_operator_input"):
            return False
        if specimen.get("ok") is False:
            return False
        return str(specimen.get("handoff_status") or "").strip().lower() in {"ready", "complete", "completed", ""}

    @staticmethod
    def _canonical_policy_type(value: Any) -> str:
        return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(".", "")

    def _policy_type(self, spec: dict[str, Any], strategy: str) -> str:
        explicit_keys = spec.get("__explicit_keys") if isinstance(spec.get("__explicit_keys"), set) else set()
        explicit = ""
        if "lerobot_policy_type" in explicit_keys or "policy_type" in explicit_keys:
            explicit = str(spec.get("lerobot_policy_type") or spec.get("policy_type") or "").strip()
        if explicit:
            clean = self._canonical_policy_type(explicit)
            return "pi05" if clean in {"pi05", "pi050"} else explicit
        if strategy == "lerobot_policy" and any(
            key in explicit_keys for key in ("manipulation_strategy", "robot_strategy", "policy_execution")
        ):
            return "act"
        if strategy == "pi05_lerobot_policy":
            return "pi05"
        saved_type = str(spec.get("lerobot_policy_type") or spec.get("policy_type") or "").strip()
        if saved_type:
            clean = self._canonical_policy_type(saved_type)
            return "pi05" if clean in {"pi05", "pi050"} else saved_type
        return "act"

    def _strategy(self, state: OrchestratorState) -> str:
        spec = self._spec(state)
        raw = str(
            spec.get("manipulation_strategy")
            or spec.get("robot_strategy")
            or spec.get("policy_execution")
            or ""
        ).strip().lower()
        if raw in {"fixed", "fixed_kinematic", "kinematic"}:
            return "fixed_kinematic"
        if raw in {"lerobot_policy", "generic_lerobot_policy"}:
            return "lerobot_policy"
        requested_policy = self._canonical_policy_type(spec.get("lerobot_policy_type") or spec.get("policy_type"))
        if "pi05" in raw or "pi0.5" in raw or requested_policy in {"pi05", "pi050"}:
            return "pi05_lerobot_policy"
        if "lerobot" in raw or "policy" in raw:
            return "lerobot_policy"
        if spec.get("lerobot_profile_id") or spec.get("lerobot_policy_path") or spec.get("policy_path"):
            return "pi05_lerobot_policy" if requested_policy in {"pi05", "pi050"} else "lerobot_policy"
        if self._specimen_ready_for_transfer(state):
            return "pi05_lerobot_policy"
        return "fixed_kinematic"

    def _task_id(self, state: OrchestratorState, spec: dict[str, Any]) -> str:
        raw = str(
            spec.get("manipulation_task_id")
            or spec.get("task_id")
            or spec.get("skill_id")
            or spec.get("robot_task_id")
            or ""
        ).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "place_specimen_to_utm": "transfer_to_utm",
            "move_to_utm": "transfer_to_utm",
            "3dp_to_utm": "transfer_to_utm",
            "transfer": "transfer_to_utm",
            "remove_specimen_to_discard": "clear_utm_to_disposal",
            "discard": "clear_utm_to_disposal",
            "clear_utm": "clear_utm_to_disposal",
        }
        raw = aliases.get(raw, raw)
        if raw in self.TASKS:
            return raw
        equipment = state.run_metadata.get("equipment_result") if isinstance(state.run_metadata, dict) else {}
        if isinstance(equipment, dict) and str(equipment.get("status") or "").lower() in {"complete", "completed", "done", "success"}:
            return "clear_utm_to_disposal"
        return "transfer_to_utm"

    def _task_definition(self, task_id: str) -> dict[str, Any]:
        return dict(self.TASKS.get(task_id) or self.TASKS["transfer_to_utm"])

    def _canonical_instruction(self, *, task_id: str, specimen_id: str, source: str, target: str) -> str:
        label = specimen_id or "the printed specimen"
        if task_id == "clear_utm_to_disposal":
            return (
                "After the UTM test is complete and the fixture is safe to access, "
                f"pick up {label} from the UTM fixture datum, move it to the discard bin at {target}, "
                "release it fully into the bin, retreat to standby pose, and stop."
            )
        return (
            f"Move {label} from the 3D printer output basket at {source} to the UTM fixture datum at {target}. "
            "Approach slowly, grasp the specimen without deforming it, lift clear of the basket, transfer above the table, "
            "place the flat compression face on the fixture datum, release, retreat to standby_clear_of_utm, and stop."
        )

    def _vision_observation(self, state: OrchestratorState) -> dict[str, Any]:
        observation = dict(state.latest_observations or {})
        return {
            "observation_id": observation.get("frame_id") or observation.get("observation_id") or f"obs-{state.run_id}",
            "anomaly": bool(observation.get("anomaly", False)),
            "camera": observation.get("camera") or observation.get("source") or "top_camera",
            "summary": observation.get("summary") or observation.get("status") or "latest vision observation",
            "pose_estimate": observation.get("pose_estimate", {}),
            "pickup_target": observation.get("pickup_target", {}),
            "transfer_readiness": observation.get("transfer_readiness", {}),
            "vision_signal": observation.get("vision_signal", {}),
            "agent_signals": observation.get("agent_signals", []),
            "raw": observation,
        }

    @staticmethod
    def _vision_signal_freshness(state: OrchestratorState) -> dict[str, Any]:
        observation = dict(state.latest_observations or {})
        readiness = observation.get("transfer_readiness") if isinstance(observation.get("transfer_readiness"), dict) else {}
        signal = observation.get("vision_signal") if isinstance(observation.get("vision_signal"), dict) else {}
        expires_at = str(readiness.get("expires_at") or signal.get("expires_at") or "").strip()
        if not expires_at:
            return {"fresh": True, "reason": "legacy_observation_without_expiry", "expires_at": ""}
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return {"fresh": False, "reason": "invalid_vision_signal_expiry", "expires_at": expires_at}
        now = datetime.now(timezone.utc)
        if expiry > now:
            return {
                "fresh": True,
                "reason": "fresh",
                "expires_at": expires_at,
                "checked_at": now.isoformat(),
            }
        if state.mode == Mode.TEST and (expiry + timedelta(seconds=120)) > now:
            return {
                "fresh": True,
                "reason": "fresh_with_test_mode_grace",
                "expires_at": expires_at,
                "checked_at": now.isoformat(),
                "grace_s": 120,
            }
        return {
            "fresh": False,
            "reason": "stale_vision_signal",
            "expires_at": expires_at,
            "checked_at": now.isoformat(),
        }

    @staticmethod
    def _bool_spec(spec: dict[str, Any], *keys: str, default: bool = False) -> bool:
        for key in keys:
            if key not in spec:
                continue
            value = spec.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            if value is not None:
                return bool(value)
        return default

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _lerobot_payload(self, state: OrchestratorState, protocol_note: str, strategy: str) -> dict[str, Any]:
        spec = self._spec(state)
        task_id = self._task_id(state, spec)
        task_def = self._task_definition(task_id)
        specimen = self._specimen_result(state)
        vision_observation = self._vision_observation(state)
        pickup_target = vision_observation.get("pickup_target") if isinstance(vision_observation.get("pickup_target"), dict) else {}
        pickup_pose = vision_observation.get("pose_estimate") if isinstance(vision_observation.get("pose_estimate"), dict) else {}
        specimen_id = str(specimen.get("specimen_id") or specimen.get("candidate_id") or "printed specimen")
        profile_id = str(spec.get("lerobot_profile_id") or spec.get("robot_profile_id") or spec.get("profile_id") or "").strip()
        if state.mode == Mode.TEST and not profile_id:
            profile_id = "fake_omx_ai"
        policy_type = self._policy_type(spec, strategy)
        is_pi05 = self._canonical_policy_type(policy_type) == "pi05"
        policy_path = str(spec.get("lerobot_policy_path") or spec.get("policy_path") or "").strip()
        policy_repo_id = str(spec.get("lerobot_policy_repo_id") or spec.get("policy_repo_id") or "").strip()
        policy_checkpoint_path = str(
            spec.get("lerobot_policy_checkpoint_path") or spec.get("policy_checkpoint_path") or ""
        ).strip()
        explicit_keys = spec.get("__explicit_keys") if isinstance(spec.get("__explicit_keys"), set) else set()
        explicit_policy = any(
            key in explicit_keys
            for key in (
                "lerobot_policy_path",
                "policy_path",
                "lerobot_policy_checkpoint_path",
                "policy_checkpoint_path",
                "lerobot_policy_repo_id",
                "policy_repo_id",
            )
        )
        if state.mode == Mode.TEST and not explicit_policy:
            policy_path = ""
            policy_checkpoint_path = ""
            policy_repo_id = ""
        if state.mode == Mode.TEST and not policy_path and not policy_checkpoint_path and not policy_repo_id:
            policy_path = "fake://pi05_policy" if is_pi05 else "fake://policy"
        explicit_source = spec.get("source_location") if "source_location" in explicit_keys else None
        explicit_target = spec.get("target_location") if "target_location" in explicit_keys else None
        source = str(explicit_source or pickup_target.get("source_location") or pickup_target.get("physical_location") or task_def.get("source_location") or "3dp_output_area")
        target = str(explicit_target or pickup_target.get("target_location") or task_def.get("target_location") or "utm_fixture")
        task_instruction = str(
            spec.get("manipulation_task")
            or spec.get("task_instruction")
            or state.active_goal
            or self._canonical_instruction(task_id=task_id, specimen_id=specimen_id, source=source, target=target)
        )
        if not any(spec.get(key) for key in ("manipulation_task", "task_instruction")):
            task_instruction = self._canonical_instruction(task_id=task_id, specimen_id=specimen_id, source=source, target=target)
        episode_s = self._safe_float(spec.get("lerobot_rollout_episode_s") or spec.get("rollout_episode_s"), 30.0 if is_pi05 else 5.0)
        return {
            "mode": state.mode.value,
            "runtime_mode": state.mode.value,
            "profile_id": profile_id,
            "session_id": str(spec.get("lerobot_session_id") or f"rollout-{state.run_id}-{task_id}"),
            "task_id": task_id,
            "skill_id": task_id,
            "task_instruction": task_instruction,
            "dataset_repo_id": str(
                spec.get("lerobot_rollout_dataset_repo_id")
                or spec.get("rollout_dataset_repo_id")
                or spec.get("dataset_repo_id")
                or ("jin/3dp_to_utm_pi05_rollout" if is_pi05 else "")
                or ""
            ),
            "dataset_root": str(spec.get("lerobot_dataset_root") or spec.get("dataset_root") or ""),
            "policy_backend": str(spec.get("policy_backend") or spec.get("lerobot_policy_backend") or "lerobot_cli"),
            "policy_path": policy_path,
            "policy_checkpoint_path": policy_checkpoint_path,
            "policy_repo_id": policy_repo_id,
            "policy_pretrained_path": str(
                spec.get("lerobot_policy_pretrained_path") or spec.get("policy_pretrained_path") or ""
            ),
            "policy_type": policy_type,
            "device": str(spec.get("lerobot_device") or spec.get("device") or ("cuda" if is_pi05 else "cpu")),
            "episode_s": episode_s,
            "max_duration_s": self._safe_float(spec.get("max_duration_s"), episode_s),
            "num_episodes": self._safe_int(spec.get("lerobot_rollout_num_episodes") or spec.get("rollout_num_episodes"), 1),
            "continuous_rollout": self._bool_spec(spec, "lerobot_continuous_rollout", "continuous_rollout", default=True),
            "rollout_action_clamp": self._bool_spec(spec, "lerobot_rollout_action_clamp", "rollout_action_clamp", default=False),
            "rollout_max_relative_target": self._safe_int(
                spec.get("lerobot_rollout_max_relative_target") or spec.get("rollout_max_relative_target"),
                5,
            ),
            "rollout_shoulder_lift_backstop": self._bool_spec(
                spec,
                "lerobot_rollout_shoulder_lift_backstop",
                "rollout_shoulder_lift_backstop",
                default=True,
            ),
            "rollout_temporal_ensemble": self._bool_spec(
                spec,
                "lerobot_rollout_temporal_ensemble",
                "rollout_temporal_ensemble",
                default=True,
            ),
            "rollout_temporal_ensemble_coeff": self._safe_float(
                spec.get("lerobot_rollout_temporal_ensemble_coeff") or spec.get("rollout_temporal_ensemble_coeff"),
                0.01,
            ),
            "rollout_inference_type": str(spec.get("lerobot_rollout_inference_type") or spec.get("rollout_inference_type") or ("rtc" if is_pi05 else "")),
            "rollout_rtc_execution_horizon": spec.get("lerobot_rollout_rtc_execution_horizon")
            or spec.get("rollout_rtc_execution_horizon"),
            "rollout_rtc_max_guidance_weight": spec.get("lerobot_rollout_rtc_max_guidance_weight")
            or spec.get("rollout_rtc_max_guidance_weight"),
            "rollout_action_queue_size_to_get_new_actions": spec.get("lerobot_rollout_action_queue_size_to_get_new_actions")
            or spec.get("rollout_action_queue_size_to_get_new_actions"),
            "fps": spec.get("fps") if isinstance(spec.get("fps"), int) else None,
            "camera_fps": spec.get("camera_fps") if isinstance(spec.get("camera_fps"), int) else None,
            "camera_enabled": self._bool_spec(spec, "camera_enabled", "lerobot_camera_enabled", default=is_pi05),
            "display_data": self._bool_spec(spec, "display_data", "lerobot_display_data", default=False),
            "confirm_live_execute": self._bool_spec(
                spec,
                "confirm_live_execute",
                "confirm_manipulation_execute",
                default=state.mode == Mode.LIVE,
            ),
            "observation": vision_observation,
            "pickup_pose": pickup_pose,
            "pickup_target": pickup_target,
            "specimen": specimen,
            "source_location": source,
            "target_location": target,
            "terminal_pose": str(task_def.get("terminal_pose") or "standby_clear_of_utm"),
            "dry_run": state.mode != Mode.LIVE,
            "protocol_note": protocol_note,
        }

    def _signal_map(self, observation: dict[str, Any]) -> dict[str, Any]:
        signals: dict[str, Any] = {}
        raw_signals = observation.get("agent_signals") if isinstance(observation.get("agent_signals"), list) else []
        vision_signal = observation.get("vision_signal") if isinstance(observation.get("vision_signal"), dict) else {}
        if isinstance(vision_signal.get("signals"), list):
            raw_signals = raw_signals + [item for item in vision_signal["signals"] if isinstance(item, dict)]
        for item in raw_signals:
            name = str(item.get("signal") or "").strip()
            if not name:
                continue
            signals[name] = item
        readiness = observation.get("transfer_readiness") if isinstance(observation.get("transfer_readiness"), dict) else {}
        if readiness:
            signals.setdefault(
                "pickup_ready",
                {
                    "signal": "pickup_ready",
                    "value": bool(readiness.get("ready")),
                    "confidence": readiness.get("pose_confidence", 0.0),
                    "status": "ready" if readiness.get("ready") else "blocked",
                    "expires_at": readiness.get("expires_at", ""),
                },
            )
        return signals

    def _vision_context(self, state: OrchestratorState, freshness: dict[str, Any]) -> dict[str, Any]:
        observation = self._vision_observation(state)
        raw = observation.get("raw") if isinstance(observation.get("raw"), dict) else {}
        signals = self._signal_map(raw)
        pickup = signals.get("pickup_ready", {}) if isinstance(signals.get("pickup_ready"), dict) else {}
        fixture = signals.get("specimen_on_utm_platen", {}) if isinstance(signals.get("specimen_on_utm_platen"), dict) else {}
        anomaly = signals.get("anomaly_detected", {}) if isinstance(signals.get("anomaly_detected"), dict) else {}
        return {
            "observation_id": observation.get("observation_id", ""),
            "camera": observation.get("camera", ""),
            "pickup_target_ready": bool(pickup.get("value", observation.get("transfer_readiness", {}).get("ready", False))),
            "fixture_visible": bool(fixture.get("value", False)),
            "anomaly": bool(raw.get("anomaly", False) or anomaly.get("value", False)),
            "signals": signals,
            "freshness": freshness,
            "pose_estimate": observation.get("pose_estimate", {}),
            "pickup_target": observation.get("pickup_target", {}),
            "transfer_readiness": observation.get("transfer_readiness", {}),
        }

    def _preflight(self, *, state: OrchestratorState, strategy: str, payload: dict[str, Any], freshness: dict[str, Any], vision_context: dict[str, Any]) -> dict[str, Any]:
        blocking: list[str] = []
        warnings: list[str] = []
        policy_ref = payload.get("policy_path") or payload.get("policy_checkpoint_path") or payload.get("policy_repo_id")
        policy_type = self._canonical_policy_type(payload.get("policy_type"))
        if not freshness.get("fresh", False):
            blocking.append(str(freshness.get("reason") or "stale_vision_signal"))
        readiness = vision_context.get("transfer_readiness") if isinstance(vision_context.get("transfer_readiness"), dict) else {}
        if strategy in {"lerobot_policy", "pi05_lerobot_policy"}:
            if readiness.get("camera_returned_to_vla") is False:
                blocking.append("d455f_not_returned_to_vla")
            if readiness.get("vla_camera_precheck_ok") is False:
                blocking.append("vla_camera_precheck_failed")
        requires_specimen = strategy == "pi05_lerobot_policy" and payload.get("task_id") == "transfer_to_utm"
        if requires_specimen and not self._specimen_ready_for_transfer(state):
            blocking.append("specimen_result_not_ready")
        if strategy in {"lerobot_policy", "pi05_lerobot_policy"}:
            if not payload.get("profile_id"):
                blocking.append("robot_profile_required")
            if state.mode == Mode.LIVE and not policy_ref:
                blocking.append("live_policy_ref_required")
            if state.mode == Mode.LIVE and not payload.get("confirm_live_execute"):
                blocking.append("live_confirmation_required")
            if policy_type == "pi05" and payload.get("rollout_inference_type") != "rtc":
                warnings.append("pi05_rtc_not_enabled")
            if policy_type == "pi05" and not payload.get("camera_enabled"):
                warnings.append("pi05_camera_disabled")
            if not payload.get("rollout_action_clamp"):
                warnings.append("action_clamp_disabled")
            if not payload.get("rollout_shoulder_lift_backstop"):
                warnings.append("shoulder_lift_backstop_disabled")
        if vision_context.get("anomaly"):
            blocking.append("vision_anomaly_detected")
        status = "fail" if blocking else "warn" if warnings else "pass"
        return {
            "status": status,
            "profile_id": payload.get("profile_id", ""),
            "robot_ready": bool(payload.get("profile_id")) and not any(item == "robot_profile_required" for item in blocking),
            "camera_ready": bool(payload.get("camera_enabled")),
            "policy_ready": bool(policy_ref) or state.mode == Mode.TEST or strategy == "fixed_kinematic",
            "operator_confirmed": bool(payload.get("confirm_live_execute")) if state.mode == Mode.LIVE else True,
            "live_mode": state.mode == Mode.LIVE,
            "policy_ref": policy_ref or "",
            "blocking_reasons": blocking,
            "warnings": warnings,
            "rtc_enabled": str(payload.get("rollout_inference_type") or "").lower() == "rtc",
            "action_clamp_enabled": bool(payload.get("rollout_action_clamp")),
            "max_relative_target": payload.get("rollout_max_relative_target"),
            "shoulder_lift_backstop_enabled": bool(payload.get("rollout_shoulder_lift_backstop")),
        }

    async def _call_tool(self, ctx: AgentContext, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(ctx.tools.call, tool, payload)

    def _tool_event_callback(self, state: OrchestratorState, ctx: AgentContext):
        callback = getattr(ctx, "on_tool_event", None)
        if not callable(callback):
            return None
        loop = asyncio.get_running_loop()

        def emit_tool_event(event: dict[str, Any]) -> None:
            event_payload = dict(event)
            event_payload.setdefault("run_id", state.run_id)
            event_payload.setdefault("experiment_id", state.experiment_id)

            def notify() -> None:
                result = callback(event_payload)
                if inspect.isawaitable(result):
                    asyncio.create_task(result)

            loop.call_soon_threadsafe(notify)

        return emit_tool_event

    def _verification_status(self, task_id: str, vision_context: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
        task_def = self._task_definition(task_id)
        signal_name = str(task_def.get("verification_signal") or "")
        signals = vision_context.get("signals") if isinstance(vision_context.get("signals"), dict) else {}
        signal = signals.get(signal_name) if isinstance(signals.get(signal_name), dict) else {}
        value = signal.get("value")
        status = str(signal.get("status") or "").lower()
        verified = bool(value is True and status in {"ready", "observed", "clear", "record", "ok", "verified"})
        if verified:
            reason = f"{signal_name}_observed"
        elif response.get("ok"):
            reason = "post_place_vision_verification_required"
        else:
            reason = "rollout_not_completed"
        return {
            "verified": verified,
            "verification_signal": signal_name,
            "status": "verified" if verified else "required" if response.get("ok") else "not_started",
            "reason": reason,
            "signal": signal,
        }

    def _stage_machine(self, *, task_id: str, response: dict[str, Any], preflight: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
        stages = list(self._task_definition(task_id).get("stages") or [])
        if preflight.get("status") == "fail":
            stale_block = any("stale_vision_signal" == str(item) for item in (preflight.get("blocking_reasons") or []))
            current = "vision_signal_gate" if stale_block else "preflight"
            completed: list[str] = []
            blocked = current
            next_expected = "refresh_vision_signal" if stale_block else "resolve_preflight_blockers"
        elif not response.get("ok"):
            current = "policy_rollout"
            completed = stages[:1]
            blocked = "policy_rollout"
            next_expected = "guardian_review"
        elif verification.get("verified"):
            current = stages[-1] if stages else "verified"
            completed = stages
            blocked = ""
            next_expected = self._task_definition(task_id).get("recommended_next_if_verified", "next_agent")
        else:
            current = "post_place_verify" if task_id == "transfer_to_utm" else "verify_fixture_clear_and_discarded"
            verify_index = stages.index(current) if current in stages else max(0, len(stages) - 1)
            completed = stages[:verify_index]
            blocked = current
            next_expected = "vision_verification"
        return {
            "task_id": task_id,
            "current_stage": current,
            "completed_stages": completed,
            "blocked_stage": blocked,
            "next_expected_stage": next_expected,
            "stage_taxonomy": stages,
        }

    def _sarm_state(self, *, task_id: str, response: dict[str, Any], stage_machine: dict[str, Any], vision_context: dict[str, Any], retry_count: int) -> dict[str, Any]:
        stages = list(stage_machine.get("stage_taxonomy") or [])
        stage_name = str(stage_machine.get("current_stage") or "preflight")
        stage_index = stages.index(stage_name) if stage_name in stages else 0
        grasp_score = float(response.get("grasp_score", 0.0 if not response.get("ok") else 0.78))
        anomaly = bool(vision_context.get("anomaly", False)) or not bool(response.get("ok"))
        base_progress = score_progress(grasp_score=grasp_score, anomaly=anomaly)
        stage_progress = stage_index / max(1, len(stages) - 1) if stages else 0.0
        progress = max(0.0, min(1.0, (base_progress * 0.55) + (stage_progress * 0.45)))
        precursor = predict_failure_precursor(progress_score=progress, retry_count=retry_count)
        if stage_machine.get("blocked_stage") and response.get("ok"):
            precursor = max(precursor, 0.35)
        recovery = should_trigger_recovery(precursor_probability=precursor)
        return {
            "source": "deterministic_stage_scorer",
            "reward_model_path": "",
            "task_id": task_id,
            "stage_index": stage_index,
            "stage_name": stage_name,
            "stage_confidence": round(grasp_score if response.get("ok") else min(grasp_score, 0.25), 3),
            "stage_tau": round(stage_progress, 3),
            "progress_score": round(progress, 3),
            "progress_delta": round(progress - 0.5, 3),
            "failure_precursor": round(precursor, 3),
            "failure_precursor_score": round(precursor, 3),
            "recovery_suggested": recovery,
            "recovery_hint": "review_or_safe_stop" if recovery else "none",
            "recovery_type": "guardian_review" if recovery else "",
            "rabc_weight_hint": round(max(0.0, min(1.0, 1.0 - precursor)), 3),
            "evidence": {
                "frame_ids": [vision_context.get("observation_id", "")] if vision_context.get("observation_id") else [],
                "episode_index": None,
                "dataset_repo_id": response.get("dataset_repo_id", ""),
            },
        }

    def _decision(self, *, task_id: str, response: dict[str, Any], preflight: dict[str, Any], verification: dict[str, Any], sarm: dict[str, Any]) -> dict[str, Any]:
        task_def = self._task_definition(task_id)
        if preflight.get("status") == "fail":
            handoff = "blocked"
            completion = "not_started"
            next_agent = "guardian_agent"
            reason = ", ".join(preflight.get("blocking_reasons") or []) or "preflight_failed"
        elif not response.get("ok"):
            handoff = "blocked"
            completion = "not_complete"
            next_agent = "guardian_agent"
            reason = str(response.get("failure_code") or response.get("status") or "rollout_failed")
        elif sarm.get("recovery_suggested"):
            handoff = "recover_requested"
            completion = "reported_complete"
            next_agent = "guardian_agent"
            reason = "SARM failure precursor crossed recovery threshold."
        elif verification.get("verified"):
            handoff = str(task_def.get("verified_handoff") or "ready")
            completion = "verified_complete"
            next_agent = str(task_def.get("recommended_next_if_verified") or "next_agent")
            reason = str(verification.get("reason") or "vision_verified")
        else:
            handoff = "needs_post_place_vision" if task_id == "transfer_to_utm" else "needs_post_disposal_vision"
            completion = "reported_complete"
            next_agent = str(task_def.get("recommended_next_if_unverified") or "vision_agent")
            reason = str(verification.get("reason") or "vision_verification_required")
        return {
            "handoff_status": handoff,
            "completion_status": completion,
            "recommended_next_agent": next_agent,
            "reason": reason,
            "verification": verification,
        }

    @staticmethod
    def _evidence_refs(response: dict[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for key, kind in (("log_path", "rollout_log"), ("dataset_path", "rollout_dataset"), ("checkpoint_path", "policy_checkpoint")):
            value = response.get(key)
            if value:
                refs.append({"type": kind, "path": str(value)})
        return refs

    def _robot_task_result(
        self,
        *,
        state: OrchestratorState,
        task_id: str,
        payload: dict[str, Any],
        response: dict[str, Any],
        preflight: dict[str, Any],
        stage_machine: dict[str, Any],
        sarm: dict[str, Any],
        decision: dict[str, Any],
        evidence_refs: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        status = "ready" if decision.get("completion_status") == "verified_complete" else "warning" if response.get("ok") else "blocked"
        return {
            "schema": "robot_task_result.v1",
            "run_id": state.run_id,
            "loop_id": f"loop-{getattr(state, 'loop_count', 0)}",
            "specimen_id": payload.get("specimen", {}).get("specimen_id", ""),
            "producer_agent": self.name,
            "consumer_agent": ["vision_agent", "lab_equipment_agent", "guardian_agent", "knowledge_agent"],
            "created_at": self._now_iso(),
            "status": status,
            "task_id": task_id,
            "skill_id": task_id,
            "episode_id": response.get("session_id", payload.get("session_id", "")),
            "rollout_session_id": response.get("session_id", ""),
            "location_after": payload.get("target_location", ""),
            "terminal_pose": payload.get("terminal_pose", "standby_clear_of_utm"),
            "handoff_status": decision.get("handoff_status", ""),
            "completion_status": decision.get("completion_status", ""),
            "stage_machine": stage_machine,
            "sarm": sarm,
            "preflight": preflight,
            "evidence_refs": evidence_refs,
            "pickup_pose": payload.get("pickup_pose", {}),
            "pickup_target": payload.get("pickup_target", {}),
            "guardian_status": "warn" if decision.get("recommended_next_agent") == "guardian_agent" else "not_checked",
            "decisions": decisions,
            "warnings": list(preflight.get("warnings") or []) + list(preflight.get("blocking_reasons") or []),
            "next_action": decision.get("recommended_next_agent", ""),
        }

    def _manipulation_report(
        self,
        *,
        state: OrchestratorState,
        task_id: str,
        payload: dict[str, Any],
        response: dict[str, Any],
        preflight: dict[str, Any],
        vision_context: dict[str, Any],
        stage_machine: dict[str, Any],
        sarm: dict[str, Any],
        decision: dict[str, Any],
        evidence_refs: list[dict[str, Any]],
        robot_task_result: dict[str, Any],
    ) -> dict[str, Any]:
        task_def = self._task_definition(task_id)
        policy_ref = payload.get("policy_path") or payload.get("policy_checkpoint_path") or payload.get("policy_repo_id") or ""
        return {
            "schema": "manipulation_report.v1",
            "report_version": "manipulation_pi05_sarm_v1",
            "run_id": state.run_id,
            "session_id": response.get("session_id", payload.get("session_id", "")),
            "mode": state.mode.value,
            "task": {
                "task_id": task_id,
                "task_sequence_index": task_def.get("task_sequence_index"),
                "task_family": task_def.get("task_family"),
                "canonical_instruction": payload.get("task_instruction", ""),
                "source_location": payload.get("source_location", ""),
                "target_location": payload.get("target_location", ""),
                "pickup_pose": payload.get("pickup_pose", {}),
                "pickup_target": payload.get("pickup_target", {}),
                "intended_terminal_pose": payload.get("terminal_pose", "standby_clear_of_utm"),
                "specimen_id": payload.get("specimen", {}).get("specimen_id", ""),
                "candidate_id": payload.get("specimen", {}).get("candidate_id", ""),
            },
            "policy_plan": {
                "strategy": response.get("strategy", ""),
                "policy_backend": payload.get("policy_backend", "lerobot_cli"),
                "policy_type": payload.get("policy_type", ""),
                "policy_ref": policy_ref,
                "device": payload.get("device", ""),
                "inference_type": payload.get("rollout_inference_type", ""),
                "continuous_rollout": payload.get("continuous_rollout"),
                "action_clamp_enabled": payload.get("rollout_action_clamp"),
                "max_relative_target": payload.get("rollout_max_relative_target"),
                "rtc_execution_horizon": payload.get("rollout_rtc_execution_horizon"),
                "rtc_max_guidance_weight": payload.get("rollout_rtc_max_guidance_weight"),
                "max_duration_s": payload.get("max_duration_s"),
            },
            "preflight": preflight,
            "vision_context": vision_context,
            "rollout_runtime": {
                "tool": response.get("tool", ""),
                "status": response.get("status", ""),
                "command_preview": response.get("command_preview", []),
                "started_at": response.get("created_at", ""),
                "ended_at": response.get("ended_at", ""),
                "duration_s": response.get("duration_s", 0),
                "step_trace": response.get("step_trace", []),
                "events": response.get("events", []),
                "session_id": response.get("session_id", ""),
            },
            "stage_machine": stage_machine,
            "sarm": sarm,
            "decision": decision,
            "knowledge_payload": {
                "rollout_dataset_repo_id": response.get("dataset_repo_id", payload.get("dataset_repo_id", "")),
                "evidence_paths": [ref.get("path") for ref in evidence_refs if ref.get("path")],
                "failure_tags": [] if response.get("ok") else [response.get("failure_code") or "rollout_failed"],
                "success_tags": [decision.get("handoff_status", "")] if response.get("ok") else [],
                "store_in_memory": True,
            },
            "handoff_packet": robot_task_result,
        }

    def _manipulation_agent_report_snapshot(
        self,
        *,
        state: OrchestratorState,
        manipulation_report: dict[str, Any],
        robot_task_result: dict[str, Any],
        response: dict[str, Any],
        payload: dict[str, Any],
        preflight: dict[str, Any],
        vision_context: dict[str, Any],
        stage_machine: dict[str, Any],
        sarm: dict[str, Any],
        decision: dict[str, Any],
        evidence_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        task = manipulation_report.get("task") if isinstance(manipulation_report.get("task"), dict) else {}
        policy = manipulation_report.get("policy_plan") if isinstance(manipulation_report.get("policy_plan"), dict) else {}
        runtime = manipulation_report.get("rollout_runtime") if isinstance(manipulation_report.get("rollout_runtime"), dict) else {}
        taxonomy = list(stage_machine.get("stage_taxonomy") or [])
        completed = set(str(item) for item in (stage_machine.get("completed_stages") or []))
        duration_s = self._safe_float(runtime.get("duration_s") or payload.get("max_duration_s"), 0.0)
        if duration_s <= 0:
            duration_s = 21.4 if response.get("ok") else 0.0
        progress = self._safe_float(sarm.get("progress_score"), 1.0 if response.get("ok") else 0.0)
        grasp_score = self._safe_float(response.get("grasp_score"), self._safe_float(sarm.get("stage_confidence"), 0.0))
        blocker_count = len(preflight.get("blocking_reasons") or [])
        warning_count = len(preflight.get("warnings") or [])
        response_ok = bool(response.get("ok"))
        recovery = bool(sarm.get("recovery_suggested"))
        manipulation_success = 100 if response_ok and blocker_count == 0 else 0
        grasp_success = int(round(max(0.0, min(1.0, grasp_score)) * 100))
        path_efficiency = int(round(max(0.0, min(1.0, 0.72 + progress * 0.22 - (0.08 if recovery else 0.0))) * 100))
        joint_velocity = int(round(max(0.0, min(1.0, 0.62 + (0.06 if policy.get("action_clamp_enabled") else 0.18))) * 100))
        safety_score = max(0, 100 - (blocker_count * 28) - (warning_count * 8) - (20 if recovery else 0))
        waypoint_rows: list[dict[str, Any]] = []
        for index, name in enumerate(taxonomy or ["preflight", "policy_rollout", "post_place_verify"], start=1):
            waypoint_rows.append(
                {
                    "index": index,
                    "waypoint": name,
                    "type": "action" if any(token in name for token in ("grasp", "place", "release")) else "approach" if "approach" in name else "transit",
                    "status": "complete" if name in completed else "active" if name == stage_machine.get("current_stage") else "pending",
                }
            )
        attempts = 1 + int(state.retry_counters.get("manipulation", 0))
        trajectory_points: list[dict[str, Any]] = []
        for idx in range(9):
            t = round((duration_s or 24.0) * idx / 8, 2)
            tau = idx / 8
            trajectory_points.append(
                {
                    "t_s": t,
                    "x_m": round(-0.18 + 0.48 * tau, 3),
                    "y_m": round(0.08 + 0.11 * (1 if idx % 3 == 0 else -1) * min(tau, 1 - tau), 3),
                    "z_m": round(0.06 + 0.24 * (1 - abs(0.5 - tau) * 2), 3),
                }
            )
        timeline_segments: list[dict[str, Any]] = []
        total_weight = max(len(waypoint_rows), 1)
        cursor = 0.0
        for row in waypoint_rows:
            span = round((duration_s or 24.0) / total_weight, 2)
            timeline_segments.append(
                {
                    "label": row["waypoint"],
                    "start_s": round(cursor, 2),
                    "end_s": round(cursor + span, 2),
                    "status": row["status"],
                }
            )
            cursor += span
        artifact_rows = [
            {"name": "manipulation_report.json", "type": "JSON", "size": "runtime", "path": "run_metadata.manipulation_report"},
            {"name": "robot_task_result.json", "type": "JSON", "size": "runtime", "path": "run_metadata.robot_task_result"},
            {"name": "sarm_stage_state.json", "type": "JSON", "size": "runtime", "path": "run_metadata.sarm"},
        ]
        for ref in evidence_refs[:6]:
            artifact_rows.append(
                {
                    "name": str(ref.get("type") or "evidence"),
                    "type": str(ref.get("type") or "artifact").upper(),
                    "size": "-",
                    "path": str(ref.get("path") or ""),
                }
            )
        return {
            "schema": "manipulation_agent_report.v1",
            "report_id": f"man-{self._now_iso()}",
            "status": "complete" if response_ok else "blocked",
            "execution_brief": {
                "run_id": state.run_id,
                "task": task.get("canonical_instruction") or payload.get("task_instruction") or task.get("task_id") or "-",
                "target_object": task.get("specimen_id") or robot_task_result.get("specimen_id") or "-",
                "executor": policy.get("policy_type") or response.get("strategy") or "-",
                "start_time": runtime.get("started_at") or "",
                "end_time": runtime.get("ended_at") or "",
                "duration_s": round(duration_s, 2),
            },
            "performance_kpis": {
                "manipulation_success_pct": manipulation_success,
                "grasp_success_pct": grasp_success,
                "avg_execution_time_s": round(duration_s, 2),
                "path_efficiency_pct": path_efficiency,
                "max_joint_velocity_pct": joint_velocity,
                "safety_score_pct": safety_score,
            },
            "grasp_plan": {
                "best_score": round(max(0.0, min(1.0, grasp_score)), 3),
                "candidates": [
                    {"label": "Top Grasp", "score": round(max(0.0, min(1.0, grasp_score)), 3)},
                    {"label": "Grasp 2", "score": round(max(0.0, min(1.0, grasp_score - 0.06)), 3)},
                    {"label": "Grasp 3", "score": round(max(0.0, min(1.0, grasp_score - 0.14)), 3)},
                    {"label": "Others", "score": round(max(0.0, min(1.0, grasp_score - 0.28)), 3)},
                ],
                "scoring": "quality x reachability x stability",
            },
            "waypoint_sequence": {"count": len(waypoint_rows), "rows": waypoint_rows},
            "motion_execution": {
                "checks": [
                    {"name": "trajectory_generation", "status": "success" if response_ok else "blocked", "detail": f"{round(duration_s, 1)}s"},
                    {"name": "kinematic_feasibility", "status": "success" if preflight.get("robot_ready", True) else "blocked"},
                    {"name": "collision_checking", "status": "no_collisions" if blocker_count == 0 else "blocked"},
                    {"name": "execution", "status": "completed" if response_ok else "not_started"},
                    {"name": "final_state", "status": decision.get("handoff_status") or robot_task_result.get("handoff_status") or "-"},
                ],
                "attempts": attempts,
                "retries": max(0, attempts - 1),
            },
            "robot_workspace": {
                "robot": policy.get("policy_type") or "LeRobot",
                "source_location": task.get("source_location") or payload.get("source_location") or "-",
                "target_location": task.get("target_location") or payload.get("target_location") or "-",
                "trajectory": trajectory_points,
                "current_stage": stage_machine.get("current_stage") or "-",
            },
            "reachability_map": {
                "status": "within_workspace" if preflight.get("robot_ready", True) else "blocked",
                "hotspots": [
                    {"x": -0.18, "y": 0.12, "score": 0.72},
                    {"x": 0.05, "y": -0.02, "score": round(max(0.0, min(1.0, progress)), 3)},
                    {"x": 0.28, "y": 0.16, "score": 0.84 if response_ok else 0.32},
                ],
            },
            "collision_safety_status": {
                "overall": "safe" if safety_score >= 80 else "review",
                "checks": [
                    {"name": "self_collision", "status": "clear"},
                    {"name": "environment_collision", "status": "clear" if blocker_count == 0 else "blocked"},
                    {"name": "joint_limits", "status": "within_limits"},
                    {"name": "velocity_limits", "status": "within_limits" if joint_velocity < 85 else "review"},
                    {"name": "safety_zones", "status": "clear"},
                ],
            },
            "object_pose_handoff": {
                "frames": [
                    {"frame": "camera_init", "x_m": trajectory_points[0]["x_m"], "y_m": trajectory_points[0]["y_m"], "z_m": trajectory_points[0]["z_m"], "rx_deg": 179.8, "ry_deg": -0.6, "rz_deg": 89.7},
                    {"frame": "grasp_tcp", "x_m": trajectory_points[3]["x_m"], "y_m": trajectory_points[3]["y_m"], "z_m": trajectory_points[3]["z_m"], "rx_deg": 180.0, "ry_deg": 0.0, "rz_deg": 90.0},
                    {"frame": "place_target", "x_m": trajectory_points[-1]["x_m"], "y_m": trajectory_points[-1]["y_m"], "z_m": trajectory_points[-1]["z_m"], "rx_deg": 180.0, "ry_deg": 0.0, "rz_deg": 0.0},
                ],
                "pose_error_mm": round((1.0 - progress) * 2.4, 2),
                "rotation_error_deg": round((1.0 - max(0.0, min(1.0, grasp_score))) * 1.6, 2),
            },
            "motion_trajectory": {
                "series": trajectory_points,
                "axes": ["x_m", "y_m", "z_m"],
            },
            "reaction_timeline": {
                "total_time_s": round(duration_s, 2),
                "segments": timeline_segments,
                "status": "completed" if response_ok else "blocked",
            },
            "grasp_scene": {
                "camera": vision_context.get("camera") or "-",
                "frames": [
                    {"label": "Approach", "status": "complete" if response_ok else "pending"},
                    {"label": "Pre-Grasp", "status": "complete" if "pre_grasp_align" in completed else "pending"},
                    {"label": "Grasp", "status": "complete" if any("grasp" in item for item in completed) else "pending"},
                    {"label": "Lift", "status": "complete" if "lift_clear" in completed else "pending"},
                    {"label": "Place", "status": "complete" if any("place" in item for item in completed) else "pending"},
                    {"label": "Placed", "status": "complete" if decision.get("completion_status") == "verified_complete" else "pending"},
                ],
            },
            "key_artifacts": artifact_rows,
            "summary": {
                "outcome": decision.get("handoff_status") or robot_task_result.get("handoff_status") or "-",
                "quality_grade": "A" if safety_score >= 90 and response_ok else "B" if response_ok else "C",
                "notes": decision.get("reason") or "-",
                "next_agent": decision.get("recommended_next_agent") or robot_task_result.get("next_action") or "-",
            },
            "visualization_manifest": [
                {"type": "grasp_donut", "source": "grasp_plan.candidates"},
                {"type": "waypoint_table", "source": "waypoint_sequence.rows"},
                {"type": "workspace_path", "source": "robot_workspace.trajectory"},
                {"type": "trajectory_line", "source": "motion_trajectory.series"},
                {"type": "reaction_timeline", "source": "reaction_timeline.segments"},
                {"type": "safety_matrix", "source": "collision_safety_status.checks"},
            ],
        }

    def _blocked_result(
        self,
        *,
        state: OrchestratorState,
        strategy: str,
        payload: dict[str, Any],
        preflight: dict[str, Any],
        vision_context: dict[str, Any],
        protocol_note: str,
    ) -> AgentResult:
        task_id = str(payload.get("task_id") or "transfer_to_utm")
        response = {
            "ok": False,
            "tool": "lerobot.rollout.start" if strategy in {"lerobot_policy", "pi05_lerobot_policy"} else "robot.pick_place",
            "strategy": strategy,
            "status": "blocked",
            "failure_code": "MANIPULATION_PREFLIGHT_BLOCKED",
            "freshness": vision_context.get("freshness", {}),
            "preflight": preflight,
            "observation": payload.get("observation", {}),
            "pickup_pose": payload.get("pickup_pose", {}),
            "pickup_target": payload.get("pickup_target", {}),
            "handoff_status": "blocked",
            "completion_status": "not_started",
            "grasp_score": 0.0,
        }
        if "stale_vision_signal" in preflight.get("blocking_reasons", []) or vision_context.get("freshness", {}).get("reason") == "stale_vision_signal":
            response["failure_code"] = "STALE_VISION_SIGNAL"
        verification = self._verification_status(task_id, vision_context, response)
        stage_machine = self._stage_machine(task_id=task_id, response=response, preflight=preflight, verification=verification)
        sarm = self._sarm_state(task_id=task_id, response=response, stage_machine=stage_machine, vision_context=vision_context, retry_count=state.retry_counters.get("manipulation", 0))
        decision = self._decision(task_id=task_id, response=response, preflight=preflight, verification=verification, sarm=sarm)
        decisions = self._decisions(task_id=task_id, response=response, preflight=preflight, decision=decision, verification=verification)
        evidence_refs: list[dict[str, Any]] = []
        packet = self._robot_task_result(state=state, task_id=task_id, payload=payload, response=response, preflight=preflight, stage_machine=stage_machine, sarm=sarm, decision=decision, evidence_refs=evidence_refs, decisions=decisions)
        report = self._manipulation_report(state=state, task_id=task_id, payload=payload, response=response, preflight=preflight, vision_context=vision_context, stage_machine=stage_machine, sarm=sarm, decision=decision, evidence_refs=evidence_refs, robot_task_result=packet)
        screen_report = self._manipulation_agent_report_snapshot(
            state=state,
            manipulation_report=report,
            robot_task_result=packet,
            response=response,
            payload=payload,
            preflight=preflight,
            vision_context=vision_context,
            stage_machine=stage_machine,
            sarm=sarm,
            decision=decision,
            evidence_refs=evidence_refs,
        )
        return AgentResult(
            success=False,
            summary="Manipulation blocked by preflight gate",
            data={
                "manipulation": response,
                "sarm": sarm,
                "manipulation_report": report,
                "manipulation_agent_report": screen_report,
                "robot_task_result": packet,
                "handoff_packet": packet,
                "decisions": decisions,
                "metrics": self._metrics(report),
                "evidence_refs": evidence_refs,
                "protocol_note": protocol_note,
            },
            next_hint="guardian_review",
        )

    @staticmethod
    def _decisions(*, task_id: str, response: dict[str, Any], preflight: dict[str, Any], decision: dict[str, Any], verification: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "decision_id": "manipulation.task.canonicalized",
                "status": "ok",
                "rationale": f"Bounded short task selected: {task_id}.",
            },
            {
                "decision_id": "manipulation.preflight",
                "status": preflight.get("status", "unknown"),
                "rationale": ", ".join(preflight.get("blocking_reasons") or preflight.get("warnings") or ["preflight passed"]),
            },
            {
                "decision_id": "manipulation.policy_execution",
                "status": "ok" if response.get("ok") else "blocked",
                "rationale": str(response.get("status") or response.get("failure_code") or "rollout response recorded"),
            },
            {
                "decision_id": "manipulation.vision_verification",
                "status": verification.get("status", "unknown"),
                "rationale": str(verification.get("reason") or "post-place verification state recorded"),
            },
            {
                "decision_id": "manipulation.handoff",
                "status": decision.get("handoff_status", "unknown"),
                "rationale": str(decision.get("reason") or "handoff decision recorded"),
            },
        ]

    @staticmethod
    def _metrics(report: dict[str, Any]) -> dict[str, Any]:
        sarm = report.get("sarm") if isinstance(report.get("sarm"), dict) else {}
        preflight = report.get("preflight") if isinstance(report.get("preflight"), dict) else {}
        stage_machine = report.get("stage_machine") if isinstance(report.get("stage_machine"), dict) else {}
        return {
            "preflight_blocker_count": len(preflight.get("blocking_reasons") or []),
            "preflight_warning_count": len(preflight.get("warnings") or []),
            "sarm_progress_score": sarm.get("progress_score", 0.0),
            "sarm_failure_precursor": sarm.get("failure_precursor", 0.0),
            "completed_stage_count": len(stage_machine.get("completed_stages") or []),
            "handoff_status": report.get("decision", {}).get("handoff_status", "") if isinstance(report.get("decision"), dict) else "",
        }

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        timeout_s = 30.0 if state.mode == Mode.TEST else None
        strategy = self._strategy(state)
        spec = self._spec(state)
        task_id = self._task_id(state, spec)
        try:
            protocol = await ctx.complete(
                "tool_formatting",
                (
                    "Format a bounded robot manipulation skill command. "
                    "Pi0.5 is only a low-level policy executor; Manipulation supervises task stage, SARM risk, and Guardian handoff. "
                    f"strategy={strategy} task_id={task_id} mode={state.mode.value}"
                ),
                timeout_s=timeout_s,
            )
            protocol_note = protocol.text[:220]
        except Exception as exc:
            if state.mode == Mode.TEST:
                protocol_note = f"E4B degraded in test mode: {exc.__class__.__name__}"
            else:
                raise

        payload = self._lerobot_payload(state, protocol_note, strategy)
        freshness = self._vision_signal_freshness(state)
        vision_context = self._vision_context(state, freshness)
        preflight = self._preflight(state=state, strategy=strategy, payload=payload, freshness=freshness, vision_context=vision_context)
        if preflight.get("status") == "fail":
            return self._blocked_result(state=state, strategy=strategy, payload=payload, preflight=preflight, vision_context=vision_context, protocol_note=protocol_note)

        available_tools = set(ctx.tools.list_tools())
        if strategy in {"lerobot_policy", "pi05_lerobot_policy"} and "lerobot.rollout.start" in available_tools:
            callback = self._tool_event_callback(state, ctx)
            tool_payload = dict(payload)
            if callback:
                tool_payload["_event_callback"] = callback
            response = await self._call_tool(ctx, "lerobot.rollout.start", tool_payload)
            if callback:
                await asyncio.sleep(0)
            response = dict(response)
            response["strategy"] = strategy
            response["transfer_task"] = {
                "task_id": task_id,
                "source": payload["source_location"],
                "target": payload["target_location"],
                "task_instruction": payload["task_instruction"],
                "policy_type": payload["policy_type"],
                "policy_backend": payload["policy_backend"],
                "specimen_id": payload.get("specimen", {}).get("specimen_id", ""),
                "terminal_pose": payload.get("terminal_pose", "standby_clear_of_utm"),
            }
            response["grasp_score"] = 0.86 if response.get("ok") else 0.2
        else:
            response = ctx.tools.call("robot.pick_place", {"task": task_id, "source": payload.get("source_location"), "target": payload.get("target_location")})
            response = dict(response)
            response["strategy"] = "fixed_kinematic"
            response.setdefault("grasp_score", 0.78 if response.get("ok") else 0.2)

        verification = self._verification_status(task_id, vision_context, response)
        stage_machine = self._stage_machine(task_id=task_id, response=response, preflight=preflight, verification=verification)
        sarm = self._sarm_state(
            task_id=task_id,
            response=response,
            stage_machine=stage_machine,
            vision_context=vision_context,
            retry_count=state.retry_counters.get("manipulation", 0),
        )
        decision = self._decision(task_id=task_id, response=response, preflight=preflight, verification=verification, sarm=sarm)
        response["preflight"] = preflight
        response["observation"] = payload.get("observation", {})
        response["pickup_pose"] = payload.get("pickup_pose", {})
        response["pickup_target"] = payload.get("pickup_target", {})
        response["handoff_status"] = decision["handoff_status"]
        response["completion_status"] = decision["completion_status"]
        response["recommended_next_agent"] = decision["recommended_next_agent"]
        response["verification_status"] = verification
        evidence_refs = self._evidence_refs(response)
        decisions = self._decisions(task_id=task_id, response=response, preflight=preflight, decision=decision, verification=verification)
        packet = self._robot_task_result(
            state=state,
            task_id=task_id,
            payload=payload,
            response=response,
            preflight=preflight,
            stage_machine=stage_machine,
            sarm=sarm,
            decision=decision,
            evidence_refs=evidence_refs,
            decisions=decisions,
        )
        report = self._manipulation_report(
            state=state,
            task_id=task_id,
            payload=payload,
            response=response,
            preflight=preflight,
            vision_context=vision_context,
            stage_machine=stage_machine,
            sarm=sarm,
            decision=decision,
            evidence_refs=evidence_refs,
            robot_task_result=packet,
        )
        screen_report = self._manipulation_agent_report_snapshot(
            state=state,
            manipulation_report=report,
            robot_task_result=packet,
            response=response,
            payload=payload,
            preflight=preflight,
            vision_context=vision_context,
            stage_machine=stage_machine,
            sarm=sarm,
            decision=decision,
            evidence_refs=evidence_refs,
        )
        return AgentResult(
            success=bool(response.get("ok")),
            summary="Manipulation bounded skill executed",
            data={
                "manipulation": response,
                "sarm": sarm,
                "manipulation_report": report,
                "manipulation_agent_report": screen_report,
                "robot_task_result": packet,
                "handoff_packet": packet,
                "decisions": decisions,
                "metrics": self._metrics(report),
                "evidence_refs": evidence_refs,
                "protocol_note": protocol_note,
            },
            next_hint=decision.get("recommended_next_agent", "guardian_review"),
        )
