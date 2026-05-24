"""
File purpose:
- Execute manipulation tasks and integrate SARM submodule risk signals.

Key classes/functions:
- ManipulationAgent

Inputs/outputs:
- Input: latest observation and experiment spec
- Output: manipulation result plus SARM metrics

Dependencies:
- mcp tool: robot.pick_place
- submodules.sarm.*

Modification guide:
- Safe places to edit: SARM thresholds and command payloads
- Risky places to edit: output keys used by guardian policies
- Related files: agents/guardian_agent.py, submodules/sarm/*.py
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState
from submodules.sarm.failure_predictor import predict_failure_precursor
from submodules.sarm.progress_scorer import score_progress
from submodules.sarm.recovery_trigger import should_trigger_recovery
from utils.manipulation_profile import load_manipulation_agent_profile


class ManipulationAgent(BaseAgent):
    """Runs pick/place behavior and emits SARM support signals."""

    name = "manipulation_agent"

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
            "raw": observation,
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

    def _default_transfer_task(self, state: OrchestratorState) -> str:
        specimen = self._specimen_result(state)
        specimen_label = str(specimen.get("specimen_id") or specimen.get("candidate_id") or "printed specimen")
        return (
            f"Move {specimen_label} from the 3D printer pickup area to the UTM fixture, "
            "place it on the fixture datum, release safely, then report transfer complete."
        )

    def _lerobot_payload(self, state: OrchestratorState, protocol_note: str, strategy: str) -> dict[str, Any]:
        spec = self._spec(state)
        profile_id = str(spec.get("lerobot_profile_id") or spec.get("robot_profile_id") or "").strip()
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
        task_instruction = str(
            spec.get("manipulation_task")
            or spec.get("task_instruction")
            or state.active_goal
            or self._default_transfer_task(state)
        )
        if self._specimen_ready_for_transfer(state) and not any(
            spec.get(key) for key in ("manipulation_task", "task_instruction")
        ):
            task_instruction = self._default_transfer_task(state)
        return {
            "mode": state.mode.value,
            "runtime_mode": state.mode.value,
            "profile_id": profile_id,
            "session_id": str(spec.get("lerobot_session_id") or f"rollout-{state.run_id}"),
            "task_instruction": task_instruction,
            "dataset_repo_id": str(
                spec.get("lerobot_rollout_dataset_repo_id")
                or spec.get("rollout_dataset_repo_id")
                or spec.get("dataset_repo_id")
                or ("jin/3dp_to_utm_pi05_rollout" if is_pi05 else "")
                or ""
            ),
            "dataset_root": str(spec.get("lerobot_dataset_root") or spec.get("dataset_root") or ""),
            "policy_path": policy_path,
            "policy_checkpoint_path": policy_checkpoint_path,
            "policy_repo_id": policy_repo_id,
            "policy_pretrained_path": str(
                spec.get("lerobot_policy_pretrained_path") or spec.get("policy_pretrained_path") or ""
            ),
            "policy_type": policy_type,
            "device": str(spec.get("lerobot_device") or spec.get("device") or ("cuda" if is_pi05 else "cpu")),
            "episode_s": float(spec.get("lerobot_rollout_episode_s") or spec.get("rollout_episode_s") or 5.0),
            "num_episodes": int(spec.get("lerobot_rollout_num_episodes") or spec.get("rollout_num_episodes") or 1),
            "continuous_rollout": self._bool_spec(spec, "lerobot_continuous_rollout", "continuous_rollout", default=True),
            "rollout_action_clamp": self._bool_spec(spec, "lerobot_rollout_action_clamp", "rollout_action_clamp", default=True),
            "rollout_max_relative_target": int(
                spec.get("lerobot_rollout_max_relative_target")
                or spec.get("rollout_max_relative_target")
                or 5
            ),
            "rollout_temporal_ensemble": self._bool_spec(
                spec,
                "lerobot_rollout_temporal_ensemble",
                "rollout_temporal_ensemble",
                default=True,
            ),
            "rollout_temporal_ensemble_coeff": float(
                spec.get("lerobot_rollout_temporal_ensemble_coeff")
                or spec.get("rollout_temporal_ensemble_coeff")
                or 0.01
            ),
            "rollout_inference_type": str(spec.get("lerobot_rollout_inference_type") or spec.get("rollout_inference_type") or ""),
            "rollout_rtc_execution_horizon": spec.get("lerobot_rollout_rtc_execution_horizon")
            or spec.get("rollout_rtc_execution_horizon"),
            "rollout_rtc_max_guidance_weight": spec.get("lerobot_rollout_rtc_max_guidance_weight")
            or spec.get("rollout_rtc_max_guidance_weight"),
            "fps": spec.get("fps") if isinstance(spec.get("fps"), int) else None,
            "camera_enabled": self._bool_spec(spec, "camera_enabled", "lerobot_camera_enabled", default=is_pi05),
            "display_data": self._bool_spec(spec, "display_data", "lerobot_display_data", default=False),
            "confirm_live_execute": self._bool_spec(
                spec,
                "confirm_live_execute",
                "confirm_manipulation_execute",
                default=state.mode == Mode.LIVE,
            ),
            "observation": self._vision_observation(state),
            "specimen": self._specimen_result(state),
            "source_location": str(spec.get("source_location") or "3dp_output_area"),
            "target_location": str(spec.get("target_location") or "utm_fixture"),
            "dry_run": state.mode != Mode.LIVE,
            "protocol_note": protocol_note,
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

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        timeout_s = 30.0 if state.mode == Mode.TEST else None
        strategy = self._strategy(state)
        try:
            protocol = await ctx.complete(
                "tool_formatting",
                (
                    "Format manipulation execution command with minimal collision-risk wording. "
                    f"strategy={strategy} mode={state.mode.value}"
                ),
                timeout_s=timeout_s,
            )
            protocol_note = protocol.text[:220]
        except Exception as exc:
            if state.mode == Mode.TEST:
                protocol_note = f"E2B degraded in test mode: {exc.__class__.__name__}"
            else:
                raise

        available_tools = set(ctx.tools.list_tools())
        if strategy in {"lerobot_policy", "pi05_lerobot_policy"} and "lerobot.rollout.start" in available_tools:
            payload = self._lerobot_payload(state, protocol_note, strategy)
            callback = self._tool_event_callback(state, ctx)
            if callback:
                payload["_event_callback"] = callback
            response = await self._call_tool(ctx, "lerobot.rollout.start", payload)
            if callback:
                await asyncio.sleep(0)
            response = dict(response)
            response["strategy"] = strategy
            response["transfer_task"] = {
                "source": payload["source_location"],
                "target": payload["target_location"],
                "task_instruction": payload["task_instruction"],
                "policy_type": payload["policy_type"],
                "specimen_id": payload.get("specimen", {}).get("specimen_id", ""),
            }
            response["handoff_status"] = "ready_for_equipment_agent" if response.get("ok") else "blocked"
            response["completion_status"] = "reported_complete" if response.get("ok") else "not_complete"
            response["grasp_score"] = 0.86 if response.get("ok") else 0.2
        else:
            response = ctx.tools.call("robot.pick_place", {"task": "pick_place_alignment"})
            response = dict(response)
            response["strategy"] = "fixed_kinematic"

        grasp_score = float(response.get("grasp_score", 0.78))
        anomaly = bool(state.latest_observations.get("anomaly", False))
        progress = score_progress(grasp_score=grasp_score, anomaly=anomaly)
        retry_count = state.retry_counters.get("manipulation", 0)
        precursor = predict_failure_precursor(progress_score=progress, retry_count=retry_count)
        recovery = should_trigger_recovery(precursor_probability=precursor)
        return AgentResult(
            success=bool(response.get("ok")),
            summary="Manipulation action executed",
            data={
                "manipulation": response,
                "sarm": {
                    "progress_score": round(progress, 3),
                    "stage_index": 0,
                    "stage_name": "policy_rollout"
                    if response.get("strategy") in {"lerobot_policy", "pi05_lerobot_policy"}
                    else "pick_place",
                    "stage_confidence": round(grasp_score, 3),
                    "progress_delta": round(progress - 0.5, 3),
                    "failure_precursor_score": round(precursor, 3),
                    "failure_precursor": round(precursor, 3),
                    "recovery_hint": "review_or_safe_stop" if recovery else "none",
                    "recovery_suggested": recovery,
                    "reward_model_path": "",
                    "source": "deterministic_test_scorer",
                },
                "protocol_note": protocol_note,
            },
            next_hint="guardian_review",
        )
