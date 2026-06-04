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
from datetime import datetime, timezone
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
        return {
            "fresh": expiry > now,
            "reason": "fresh" if expiry > now else "stale_vision_signal",
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
        if state.mode == Mode.TEST and not policy_path and not policy_checkpoint_path and not policy_repo_id:
            policy_path = "fake://pi05_policy" if is_pi05 else "fake://policy"
        source = str(spec.get("source_location") or task_def.get("source_location") or "3dp_output_area")
        target = str(spec.get("target_location") or task_def.get("target_location") or "utm_fixture")
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
            "rollout_action_clamp": self._bool_spec(spec, "lerobot_rollout_action_clamp", "rollout_action_clamp", default=True),
            "rollout_max_relative_target": self._safe_int(
                spec.get("lerobot_rollout_max_relative_target") or spec.get("rollout_max_relative_target"),
                5,
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
            "observation": self._vision_observation(state),
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
        }

    def _preflight(self, *, state: OrchestratorState, strategy: str, payload: dict[str, Any], freshness: dict[str, Any], vision_context: dict[str, Any]) -> dict[str, Any]:
        blocking: list[str] = []
        warnings: list[str] = []
        policy_ref = payload.get("policy_path") or payload.get("policy_checkpoint_path") or payload.get("policy_repo_id")
        policy_type = self._canonical_policy_type(payload.get("policy_type"))
        if not freshness.get("fresh", False):
            blocking.append(str(freshness.get("reason") or "stale_vision_signal"))
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
        return AgentResult(
            success=False,
            summary="Manipulation blocked by preflight gate",
            data={
                "manipulation": response,
                "sarm": sarm,
                "manipulation_report": report,
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
        return AgentResult(
            success=bool(response.get("ok")),
            summary="Manipulation bounded skill executed",
            data={
                "manipulation": response,
                "sarm": sarm,
                "manipulation_report": report,
                "robot_task_result": packet,
                "handoff_packet": packet,
                "decisions": decisions,
                "metrics": self._metrics(report),
                "evidence_refs": evidence_refs,
                "protocol_note": protocol_note,
            },
            next_hint=decision.get("recommended_next_agent", "guardian_review"),
        )
