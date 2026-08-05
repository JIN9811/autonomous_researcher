"""Unit tests for ManipulationAgent LeRobot policy path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.manipulation_agent import ManipulationAgent
from mcp_tools.lerobot_tools import register_lerobot_tools
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage
from utils.config_loader import load_all_configs
import utils.manipulation_profile as manipulation_profile_module
from utils.manipulation_profile import normalize_manipulation_agent_profile


class _CtxStub:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools
        self.events: list[dict[str, Any]] = []
        self.prompts: list[str] = []

    async def complete(self, task_type: str, prompt: str, timeout_s: float | None = None) -> Any:
        self.prompts.append(prompt)
        return SimpleNamespace(text="policy rollout command ready", raw={}, model="mock-e4b")

    def on_tool_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-lerobot",
        experiment_id="exp-lerobot",
        mode=Mode.TEST,
        stage=Stage.MANIPULATION,
        active_goal="pick and place specimen with LeRobot",
        current_experiment_spec={
            "manipulation_strategy": "lerobot_policy",
            "lerobot_profile_id": "fake_omx_ai",
            "lerobot_policy_path": "fake://policy",
            "rollout_dataset_repo_id": "jin/pick_and_place_cube_rollout",
            "manipulation_task": "pick specimen from fixture",
        },
        latest_observations={"frame_id": "frame-1", "anomaly": False, "status": "clear"},
    )


def _post_specimen_state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-pi05-transfer",
        experiment_id="exp-pi05-transfer",
        mode=Mode.TEST,
        stage=Stage.MANIPULATION,
        active_goal="transfer printed specimen to UTM",
        current_experiment_spec={},
        latest_observations={
            "frame_id": "frame-transfer",
            "anomaly": False,
            "transfer_readiness": {"ready": True, "pose_confidence": 0.82},
            "pose_estimate": {"x_mm": 0.0, "y_mm": 0.0, "z_mm": 5.0, "confidence": 0.82},
        },
        run_metadata={
            "specimen_result": {
                "ok": True,
                "specimen_id": "specimen-transfer-001",
                "candidate_id": "candidate-transfer-001",
                "handoff_status": "ready",
                "stl_path": "runs/specimen-transfer-001.stl",
                "sliced_path": "runs/specimen-transfer-001.gcode",
            }
        },
    )


def _post_specimen_completion_state() -> OrchestratorState:
    state = _post_specimen_state()
    state.latest_observations["vision_manipulation_completion"] = {
        "schema": "vision_manipulation_completion.v1",
        "specimen_id": "specimen-transfer-001",
        "detected": True,
        "confidence": 0.94,
        "camera": "brio_top",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evidence_path": "runs/vision/specimen-transfer-001.png",
        "ready_to_stop_rollout": True,
        "run_id": "run-pi05-transfer",
        "session_id": "lr-rollout-completion-001",
    }
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "tool": "lerobot.rollout.status",
        "status": "POLICY_ACTIVE",
        "session_id": "lr-rollout-completion-001",
        "profile_id": "fake_omx_ai",
        "workflow": "rollout",
        "runtime_phase": "ACTION_ACTIVE",
        "action_count": 30,
        "runtime": {"phase": "ACTION_ACTIVE", "action_count": 30},
    }
    state.run_metadata["robot_task_result"] = {
        "schema": "robot_task_result.v1",
        "rollout_session_id": "lr-rollout-completion-001",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete",
    }
    return state


def _tools(tmp_path: Path) -> ToolRegistry:
    cfg = load_all_configs(Path("configs"))
    tools = ToolRegistry()
    register_mock_tools(tools)
    register_lerobot_tools(tools, cfg.get("lerobot", {}), repo_root=tmp_path)
    return tools


def _register_action_active_rollout_status(tools: ToolRegistry, *, post_place_ready: bool = True) -> None:
    tools.register(
        "lerobot.rollout.status",
        lambda payload: {
            "ok": True,
            "tool": "lerobot.rollout.status",
            "workflow": "rollout",
            "status": "POLICY_ACTIVE",
            "runtime_phase": "ACTION_ACTIVE",
            "action_count": 30,
            "runtime": {"phase": "ACTION_ACTIVE", "action_count": 30},
            "session_id": payload.get("session_id", ""),
            "profile_id": payload.get("profile_id", ""),
            "post_place_interlock": {
                "schema": "post_place_interlock.v1",
                "session_id": payload.get("session_id", ""),
                "ungrasping_seen": post_place_ready,
                "home_after_ungrasping": post_place_ready,
                "ready_for_utm_snapshot": post_place_ready,
            },
        },
    )


def _isolate_manipulation_profile(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        manipulation_profile_module,
        "MANIPULATION_AGENT_PROFILE_PATH",
        tmp_path / "memory" / "manipulation_agent_bridge.json",
    )


def test_manipulation_profile_accepts_xvla_policy_type() -> None:
    profile = normalize_manipulation_agent_profile(
        {
            "manipulation_strategy": "lerobot_policy",
            "policy_type": "xvla",
            "policy_path": "fake://xvla-policy",
            "rollout_inference_type": "sync",
        }
    )

    assert profile["manipulation_strategy"] == "lerobot_policy"
    assert profile["policy_type"] == "xvla"
    assert profile["policy_path"] == "fake://xvla-policy"
    assert profile["rollout_inference_type"] == "sync"


def test_manipulation_profile_accepts_smolvla_policy_type() -> None:
    profile = normalize_manipulation_agent_profile(
        {
            "manipulation_strategy": "lerobot_policy",
            "policy_type": "smolvla",
            "policy_path": "fake://smolvla-policy",
            "rollout_inference_type": "sync",
        }
    )

    assert profile["manipulation_strategy"] == "lerobot_policy"
    assert profile["policy_type"] == "smolvla"
    assert profile["policy_path"] == "fake://smolvla-policy"
    assert profile["rollout_inference_type"] == "sync"


def test_manipulation_profile_defaults_action_clamp_off() -> None:
    profile = normalize_manipulation_agent_profile({})

    assert profile["rollout_action_clamp"] is False


def test_manipulation_profile_defaults_to_smolvla_rollout_options() -> None:
    profile = normalize_manipulation_agent_profile({})

    assert profile["manipulation_strategy"] == "lerobot_policy"
    assert profile["policy_type"] == "smolvla"
    assert profile["rollout_inference_type"] == ""
    assert profile["rollout_action_clamp"] is False
    assert profile["rollout_max_relative_target"] == 5
    assert profile["rollout_shoulder_lift_backstop"] is True
    assert profile["rollout_temporal_ensemble"] is True
    assert profile["rollout_temporal_ensemble_coeff"] == 0.01


def test_existing_rollout_is_not_reused_for_a_different_specimen() -> None:
    """A new specimen must not inherit an active rollout from the prior cycle."""
    state = _post_specimen_state()
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "tool": "lerobot.rollout.start",
        "status": "ACTIVE",
        "session_id": "rollout-cycle-1",
        "workflow": "rollout",
    }
    state.run_metadata["robot_task_result"] = {
        "schema": "robot_task_result.v1",
        "specimen_id": "specimen-cycle-1",
        "rollout_session_id": "rollout-cycle-1",
    }
    agent = ManipulationAgent()
    payload = agent._lerobot_payload(state, protocol_note="test", strategy="lerobot_policy")

    reused = agent._existing_rollout_response_for_completion(
        state=state,
        payload=payload,
        strategy="lerobot_policy",
        task_id="transfer_to_utm",
        vision_context={},
    )

    assert reused is None


def test_manipulation_profile_persists_task_specific_rollout_settings() -> None:
    profile = normalize_manipulation_agent_profile(
        {
            "task_id": "clear_utm_to_disposal",
            "policy_type": "xvla",
            "policy_path": "fake://clear-policy",
            "task_instruction": "Clear tested specimen to disposal.",
            "max_duration_s": 42,
            "rollout_action_clamp": True,
            "task_profiles": {
                "transfer_to_utm": {
                    "policy_type": "smolvla",
                    "policy_path": "fake://transfer-policy",
                    "task_instruction": "Transfer printed specimen to UTM.",
                    "max_duration_s": "",
                    "rollout_action_clamp": False,
                },
                "clear_utm_to_disposal": {
                    "policy_type": "xvla",
                    "policy_path": "fake://clear-policy",
                    "task_instruction": "Clear tested specimen to disposal.",
                    "source_location": "incorrect_source",
                    "target_location": "incorrect_target",
                    "max_duration_s": 42,
                    "rollout_action_clamp": True,
                },
                "unknown": {"policy_type": "act"},
            },
        }
    )

    assert set(profile["task_profiles"]) == {"transfer_to_utm", "clear_utm_to_disposal"}
    assert profile["task_profiles"]["transfer_to_utm"]["policy_type"] == "smolvla"
    assert profile["task_profiles"]["transfer_to_utm"]["policy_path"] == "fake://transfer-policy"
    assert profile["task_profiles"]["transfer_to_utm"]["source_location"] == "3dp_output_area"
    assert profile["task_profiles"]["transfer_to_utm"]["target_location"] == "utm_fixture"
    assert profile["task_profiles"]["transfer_to_utm"]["continuous_rollout"] is True
    assert profile["task_profiles"]["clear_utm_to_disposal"]["policy_type"] == "xvla"
    assert profile["task_profiles"]["clear_utm_to_disposal"]["source_location"] == "utm_fixture"
    assert profile["task_profiles"]["clear_utm_to_disposal"]["target_location"] == "discard_bin"
    assert profile["task_profiles"]["clear_utm_to_disposal"]["rollout_action_clamp"] is True
    assert profile["policy_type"] == "xvla"
    assert profile["policy_path"] == "fake://clear-policy"


def test_manipulation_profile_policy_path_replaces_stale_checkpoint_path() -> None:
    profile = normalize_manipulation_agent_profile(
        {
            "task_id": "transfer_to_utm",
            "policy_path": "/tmp/policies/selected/pretrained_model",
            "policy_checkpoint_path": "/tmp/policies/previous/pretrained_model",
        }
    )

    assert profile["policy_path"] == "/tmp/policies/selected/pretrained_model"
    assert profile["policy_checkpoint_path"] == "/tmp/policies/selected/pretrained_model"
    assert profile["task_profiles"]["transfer_to_utm"]["policy_path"] == "/tmp/policies/selected/pretrained_model"
    assert profile["task_profiles"]["transfer_to_utm"]["policy_checkpoint_path"] == "/tmp/policies/selected/pretrained_model"


def test_manipulation_profile_file_persists_one_policy_path_per_task(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    selected = "/tmp/policies/selected/pretrained_model"

    manipulation_profile_module.save_manipulation_agent_profile(
        {
            "task_id": "transfer_to_utm",
            "policy_type": "smolvla",
            "policy_path": selected,
            "policy_checkpoint_path": "/tmp/policies/stale/pretrained_model",
        }
    )

    stored = json.loads(manipulation_profile_module.MANIPULATION_AGENT_PROFILE_PATH.read_text(encoding="utf-8"))
    assert "policy_path" not in stored
    assert "policy_checkpoint_path" not in stored
    assert stored["task_profiles"]["transfer_to_utm"]["policy_path"] == selected
    assert "policy_checkpoint_path" not in stored["task_profiles"]["transfer_to_utm"]
    assert manipulation_profile_module.MANIPULATION_AGENT_PROFILE_PATH.read_text(encoding="utf-8").count(selected) == 1

    reloaded = manipulation_profile_module.load_manipulation_agent_profile()
    assert reloaded["policy_path"] == selected
    assert reloaded["task_profiles"]["transfer_to_utm"]["policy_path"] == selected


def test_manipulation_agent_reloads_changed_saved_policy_path(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    state = _post_specimen_state()
    state.mode = Mode.LIVE
    agent = ManipulationAgent()

    manipulation_profile_module.save_manipulation_agent_profile(
        {
            "task_id": "transfer_to_utm",
            "policy_type": "smolvla",
            "policy_path": "/tmp/policies/first/pretrained_model",
            "policy_checkpoint_path": "/tmp/policies/first/pretrained_model",
        }
    )
    first = agent._lerobot_payload(state, "saved profile", "lerobot_policy")

    manipulation_profile_module.save_manipulation_agent_profile(
        {
            "task_id": "transfer_to_utm",
            "policy_type": "smolvla",
            "policy_path": "/tmp/policies/second/pretrained_model",
            "policy_checkpoint_path": "/tmp/policies/first/pretrained_model",
        }
    )
    second = agent._lerobot_payload(state, "saved profile", "lerobot_policy")

    assert first["policy_path"] == "/tmp/policies/first/pretrained_model"
    assert second["policy_path"] == "/tmp/policies/second/pretrained_model"
    assert second["policy_checkpoint_path"] == "/tmp/policies/second/pretrained_model"


def test_manipulation_agent_uses_saved_policy_for_requested_task(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "agents.manipulation_agent.load_manipulation_agent_profile",
        lambda: normalize_manipulation_agent_profile(
            {
                "task_id": "clear_utm_to_disposal",
                "policy_path": "/tmp/policies/clear/pretrained_model",
                "task_profiles": {
                    "transfer_to_utm": {
                        "policy_type": "smolvla",
                        "policy_path": "/tmp/policies/transfer/pretrained_model",
                    },
                    "clear_utm_to_disposal": {
                        "policy_type": "smolvla",
                        "policy_path": "/tmp/policies/clear/pretrained_model",
                    },
                },
            }
        ),
    )
    state = _post_specimen_state()
    state.mode = Mode.LIVE
    state.current_experiment_spec = {"task_id": "transfer_to_utm"}

    payload = ManipulationAgent()._lerobot_payload(state, "saved task profile", "lerobot_policy")

    assert payload["task_id"] == "transfer_to_utm"
    assert payload["policy_path"] == "/tmp/policies/transfer/pretrained_model"
    assert payload["policy_checkpoint_path"] == "/tmp/policies/transfer/pretrained_model"


def test_live_workflow_saved_task_profile_overrides_stale_experiment_policy(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "agents.manipulation_agent.load_manipulation_agent_profile",
        lambda: normalize_manipulation_agent_profile(
            {
                "task_id": "transfer_to_utm",
                "profile_id": "robotis_omx_ai",
                "policy_type": "smolvla",
                "policy_path": "/tmp/policies/saved-040000/pretrained_model",
                "dataset_root": "/tmp/datasets",
                "dataset_repo_id": "jin/saved-agent-dataset",
                "device": "cuda",
                "fps": 15,
                "camera_fps": 15,
                "display_data": True,
                "task_profiles": {
                    "transfer_to_utm": {
                        "policy_type": "smolvla",
                        "policy_path": "/tmp/policies/saved-040000/pretrained_model",
                        "dataset_root": "/tmp/datasets",
                        "dataset_repo_id": "jin/saved-agent-dataset",
                        "task_instruction": "Use the saved transfer policy.",
                        "rollout_temporal_ensemble": False,
                    }
                },
            }
        ),
    )
    state = _post_specimen_state()
    state.mode = Mode.LIVE
    state.current_experiment_spec = {
        "manipulation_task_id": "transfer_to_utm",
        "lerobot_profile_id": "stale_profile",
        "lerobot_policy_type": "pi05",
        "policy_type": "pi05",
        "lerobot_policy_path": "/tmp/policies/stale-latest/pretrained_model",
        "policy_path": "/tmp/policies/stale-latest/pretrained_model",
        "lerobot_policy_checkpoint_path": "/tmp/policies/stale-latest/pretrained_model",
        "policy_checkpoint_path": "/tmp/policies/stale-latest/pretrained_model",
        "lerobot_rollout_dataset_repo_id": "jin/stale-dataset",
        "dataset_repo_id": "jin/stale-dataset",
        "fps": 60,
        "camera_fps": 60,
        "display_data": False,
        "rollout_temporal_ensemble": True,
    }

    payload = ManipulationAgent()._lerobot_payload(state, "live workflow", "lerobot_policy")

    assert payload["profile_id"] == "robotis_omx_ai"
    assert payload["policy_type"] == "smolvla"
    assert payload["policy_path"] == "/tmp/policies/saved-040000/pretrained_model"
    assert payload["policy_checkpoint_path"] == "/tmp/policies/saved-040000/pretrained_model"
    assert payload["dataset_repo_id"] == "jin/saved-agent-dataset"
    assert payload["dataset_root"] == "/tmp/datasets"
    assert payload["task_instruction"] == "Use the saved transfer policy."
    assert payload["fps"] == 15
    assert payload["camera_fps"] == 15
    assert payload["display_data"] is True
    assert payload["rollout_temporal_ensemble"] is False


def test_direct_manipulation_bridge_run_uses_saved_task_profile_policy(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "agents.manipulation_agent.load_manipulation_agent_profile",
        lambda: normalize_manipulation_agent_profile(
            {
                "task_id": "transfer_to_utm",
                "policy_type": "smolvla",
                "policy_path": "/tmp/policies/saved/pretrained_model",
            }
        ),
    )
    state = _post_specimen_state()
    state.mode = Mode.LIVE
    state.run_metadata["source"] = "lerobot_gui_manipulation_bridge"
    state.current_experiment_spec = {
        "task_id": "transfer_to_utm",
        "lerobot_policy_type": "xvla",
        "policy_type": "xvla",
        "lerobot_policy_path": "/tmp/policies/direct/pretrained_model",
        "policy_path": "/tmp/policies/direct/pretrained_model",
        "lerobot_policy_checkpoint_path": "/tmp/policies/direct/pretrained_model",
        "policy_checkpoint_path": "/tmp/policies/direct/pretrained_model",
    }

    payload = ManipulationAgent()._lerobot_payload(state, "direct bridge", "lerobot_policy")

    assert payload["policy_type"] == "smolvla"
    assert payload["policy_path"] == "/tmp/policies/saved/pretrained_model"
    assert payload["policy_checkpoint_path"] == "/tmp/policies/saved/pretrained_model"


def test_live_workflow_selects_clear_task_after_equipment_completion(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "agents.manipulation_agent.load_manipulation_agent_profile",
        lambda: normalize_manipulation_agent_profile(
            {
                "task_id": "transfer_to_utm",
                "policy_path": "/tmp/policies/transfer/pretrained_model",
                "task_profiles": {
                    "transfer_to_utm": {"policy_path": "/tmp/policies/transfer/pretrained_model"},
                    "clear_utm_to_disposal": {"policy_path": "/tmp/policies/clear/pretrained_model"},
                },
            }
        ),
    )
    state = _post_specimen_state()
    state.mode = Mode.LIVE
    state.run_metadata["equipment_result"] = {"status": "completed"}

    payload = ManipulationAgent()._lerobot_payload(state, "post equipment", "lerobot_policy")

    assert payload["task_id"] == "clear_utm_to_disposal"
    assert payload["policy_path"] == "/tmp/policies/clear/pretrained_model"


def test_installed_printer_test_tail_uses_saved_policy_with_live_runtime(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "agents.manipulation_agent.load_manipulation_agent_profile",
        lambda: normalize_manipulation_agent_profile(
            {
                "manipulation_strategy": "lerobot_policy",
                "profile_id": "robotis_omx_ai",
                "policy_type": "smolvla",
                "policy_path": "/tmp/atr-policy/pretrained_model",
                "policy_checkpoint_path": "/tmp/atr-policy/pretrained_model",
                "dataset_repo_id": "jin/eval_installed_printer_tail",
                "fps": 15,
                "camera_fps": 15,
                "camera_enabled": True,
            }
        ),
    )
    state = _post_specimen_state()
    state.current_experiment_spec = {}
    state.run_metadata["specimen_fabricated"] = {
        "schema": "specimen_fabricated.v1",
        "status": "ready",
        "fabrication_summary": {
            "physical_intent": True,
            "printer_path": "installed_printer",
            "outcome_status": "ready_for_vision",
        },
    }
    state.run_metadata["fabrication_report"] = {
        "schema": "fabrication_report.v1",
        "fabrication_intent": {"physical_intent": True, "printer_path": "installed_printer"},
        "spc_readiness": {
            "preprint_gate_state": "test_printer_started_then_stopped",
            "blockers": [],
        },
    }

    payload = ManipulationAgent()._lerobot_payload(state, "installed printer tail", "lerobot_policy")

    assert payload["mode"] == "test"
    assert payload["runtime_mode"] == "live"
    assert payload["dry_run"] is False
    assert payload["confirm_live_execute"] is True
    assert payload["policy_path"] == "/tmp/atr-policy/pretrained_model"
    assert payload["policy_checkpoint_path"] == "/tmp/atr-policy/pretrained_model"
    assert payload["profile_id"] == "robotis_omx_ai"


@pytest.mark.asyncio
async def test_manipulation_agent_calls_lerobot_rollout(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(_state(), ctx)

    assert result.success is True
    assert result.data["manipulation"]["tool"] == "lerobot.rollout.start"
    assert result.data["manipulation"]["strategy"] == "lerobot_policy"
    assert result.data["manipulation"]["profile_id"] == "fake_omx_ai"
    assert "--dataset.repo_id=jin/eval_pick_and_place_cube_rollout" in result.data["manipulation"]["command_preview"]
    assert "--dataset.episode_time_s=86400.0" in result.data["manipulation"]["command_preview"]
    assert "--policy.temporal_ensemble_coeff=0.01" in result.data["manipulation"]["command_preview"]
    assert "--policy.n_action_steps=1" in result.data["manipulation"]["command_preview"]
    assert all(not item.startswith("--robot.max_relative_target=") for item in result.data["manipulation"]["command_preview"])
    assert result.data["sarm"]["stage_name"] == "post_place_verify"
    assert result.data["sarm"]["failure_precursor"] >= 0
    assert result.data["manipulation_report"]["schema"] == "manipulation_report.v1"
    assert result.data["manipulation_report"]["execution_safety"] == result.data["manipulation_report"]["sarm"]
    report = result.data["manipulation_report"]
    assert report["port_lease"]["status"] in {"ready", "unknown"}
    assert report["port_lease"]["profile_id"] == "fake_omx_ai"
    assert report["port_lease"]["follower_port"]
    assert report["active_camera_lease"]["status"] in {"ready", "unknown"}
    assert report["active_camera_lease"]["returned_to_vla"] is True
    assert report["policy_runtime"]["policy_type"] == "act"
    assert report["policy_runtime"]["session_id"] == report["session_id"]
    assert report["rollout_runtime"]["policy_runtime"] == report["policy_runtime"]
    assert report["rerun_telemetry"]["status"] in {"waiting", "available", "disabled"}
    assert "home_pose" not in report
    manipulation_response = result.data["manipulation"]
    assert manipulation_response["port_lease"]["profile_id"] == "fake_omx_ai"
    assert manipulation_response["policy_runtime"]["session_id"] == report["session_id"]
    assert result.data["robot_task_result"]["schema"] == "robot_task_result.v1"
    assert result.data["robot_task_result"]["handoff_status"] == "needs_post_place_vision"
    assert result.data["requested_next_stage"] == "vision"
    assert ctx.events
    assert ctx.events[0]["tool"] == "lerobot.rollout.start"


@pytest.mark.asyncio
async def test_manipulation_agent_defaults_to_smolvla_transfer_after_specimen(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(_post_specimen_state(), ctx)

    manipulation = result.data["manipulation"]
    assert result.success is True
    assert manipulation["tool"] == "lerobot.rollout.start"
    assert manipulation["strategy"] == "lerobot_policy"
    assert manipulation["transfer_task"]["policy_type"] == "smolvla"
    assert manipulation["transfer_task"]["source"] == "3dp_output_area"
    assert manipulation["transfer_task"]["target"] == "utm_fixture"
    assert manipulation["transfer_task"]["specimen_id"] == "specimen-transfer-001"
    assert manipulation["completion_status"] == "awaiting_post_place_home"
    assert manipulation["handoff_status"] == "needs_post_place_vision"
    assert result.data["requested_next_stage"] == "vision"
    assert result.data["robot_task_result"]["requested_next_stage"] == "vision"
    assert result.data["manipulation_report"]["task"]["task_id"] == "transfer_to_utm"
    assert result.data["manipulation_report"]["policy_plan"]["policy_type"] == "smolvla"
    assert result.data["robot_task_result"]["terminal_pose"] == "standby_clear_of_utm"
    assert "--policy.path=fake://policy" in manipulation["command_preview"]
    assert "--dataset.repo_id=jin/eval_3dp_to_utm_smolvla_rollout" in manipulation["command_preview"]
    assert "--dataset.single_task=Move specimen-transfer-001" in " ".join(manipulation["command_preview"])
    assert all("--rtc.enabled=true" not in item for item in manipulation["command_preview"])


@pytest.mark.asyncio
async def test_manipulation_does_not_reenter_before_vision_handoff(tmp_path: Path, monkeypatch: Any) -> None:
    """The rollout launch hands the existing session to Vision exactly once."""
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    agent = ManipulationAgent()
    ctx = _CtxStub(_tools(tmp_path))
    calls: list[str] = []

    async def fake_call_tool(_ctx: Any, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(tool)
        if tool == "lerobot.rollout.start":
            return {
                "ok": True,
                "tool": tool,
                "workflow": "rollout",
                "status": "POLICY_ACTIVE",
                "runtime_phase": "PROCESS_STARTED",
                "action_count": 0,
                "runtime": {"phase": "PROCESS_STARTED", "action_count": 0},
                "session_id": payload["session_id"],
                "profile_id": payload["profile_id"],
            }
        if tool == "lerobot.rollout.status":
            return {
                "ok": True,
                "tool": tool,
                "workflow": "rollout",
                "status": "POLICY_ACTIVE",
                "runtime_phase": "ACTION_ACTIVE",
                "action_count": 1,
                "runtime": {"phase": "ACTION_ACTIVE", "action_count": 1},
                "session_id": payload["session_id"],
                "profile_id": payload["profile_id"],
                "post_place_interlock": {
                    "schema": "post_place_interlock.v1",
                    "session_id": payload["session_id"],
                    "ungrasping_seen": False,
                    "home_after_ungrasping": False,
                    "ready_for_utm_snapshot": False,
                },
            }
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(agent, "_call_tool", fake_call_tool)
    state = _post_specimen_state()

    started = await agent.run(state, ctx)

    assert started.success is True
    assert started.data["requested_next_stage"] == "vision"
    assert started.data["manipulation"]["completion_status"] == "awaiting_post_place_home"
    assert calls == ["lerobot.rollout.start"]


def test_manipulation_agent_test_mode_accepts_recently_expired_vision_signal() -> None:
    state = _post_specimen_state()
    expires_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    state.latest_observations["transfer_readiness"]["expires_at"] = expires_at
    state.latest_observations["vision_signal"] = {
        "schema": "vision_signal.v1",
        "signal_id": "sig-recently-expired",
        "expires_at": expires_at,
    }

    freshness = ManipulationAgent._vision_signal_freshness(state)

    assert freshness["fresh"] is True
    assert freshness["reason"] == "fresh_with_test_mode_grace"
    assert freshness["grace_s"] == 120

@pytest.mark.asyncio
async def test_manipulation_agent_blocks_expired_vision_signal(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    state = _post_specimen_state()
    state.latest_observations["transfer_readiness"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    state.latest_observations["vision_signal"] = {
        "schema": "vision_signal.v1",
        "signal_id": "sig-expired",
        "expires_at": "2000-01-01T00:00:00+00:00",
    }
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(state, ctx)

    assert result.success is False
    assert result.data["manipulation"]["failure_code"] == "STALE_VISION_SIGNAL"
    assert result.data["manipulation"]["freshness"]["reason"] == "stale_vision_signal"
    assert result.data["sarm"]["stage_name"] == "vision_signal_gate"
    assert result.data["manipulation_report"]["preflight"]["status"] == "fail"
    assert result.data["robot_task_result"]["handoff_status"] == "blocked"


@pytest.mark.asyncio
async def test_manipulation_agent_blocks_when_active_camera_not_returned(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    state = _post_specimen_state()
    state.latest_observations["transfer_readiness"]["camera_returned_to_vla"] = False
    state.latest_observations["transfer_readiness"]["vla_camera_precheck_ok"] = False
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(state, ctx)

    assert result.success is False
    assert result.data["manipulation"]["failure_code"] == "MANIPULATION_PREFLIGHT_BLOCKED"
    assert "active_camera_not_returned_to_vla" in result.data["manipulation"]["preflight"]["blocking_reasons"]
    assert result.data["robot_task_result"]["handoff_status"] == "blocked"


@pytest.mark.asyncio
async def test_manipulation_agent_passes_pickup_pose_to_rollout(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    state = _post_specimen_state()
    state.latest_observations["transfer_readiness"]["camera_returned_to_vla"] = True
    state.latest_observations["transfer_readiness"]["vla_camera_precheck_ok"] = True
    state.latest_observations["pose_estimate"] = {"x_mm": 11.0, "y_mm": 22.0, "z_mm": 33.0, "yaw_deg": 7.5, "confidence": 0.93}
    state.latest_observations["pickup_target"] = {"source_location": "a4_robot_workspace", "target_location": "utm_fixture"}
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(state, ctx)

    assert result.success is True
    assert result.data["manipulation"]["observation"]["pose_estimate"]["x_mm"] == 11.0
    assert result.data["manipulation"]["pickup_pose"]["yaw_deg"] == 7.5
    assert result.data["manipulation"]["pickup_target"]["source_location"] == "a4_robot_workspace"
    assert result.data["manipulation_report"]["vision_context"]["pose_estimate"]["yaw_deg"] == 7.5
    assert result.data["manipulation_report"]["task"]["source_location"] == "a4_robot_workspace"
    assert result.data["robot_task_result"]["pickup_pose"]["x_mm"] == 11.0


@pytest.mark.asyncio
async def test_manipulation_agent_stops_rollout_when_vision_completion_detected(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    tools = _tools(tmp_path)
    _register_action_active_rollout_status(tools)
    stop_calls: list[dict[str, Any]] = []

    def stop_tool(payload: dict[str, Any]) -> dict[str, Any]:
        stop_calls.append(dict(payload))
        return {
            "ok": True,
            "tool": "lerobot.rollout.stop",
            "status": "STOPPED",
            "session_id": payload.get("session_id", ""),
            "step_trace": [{"step": "STOPPED", "status": "ok", "detail": "vision completion"}],
            "events": [{"step": "STOPPED", "status": "ok", "detail": "vision completion"}],
            "log_tail": "stopped by vision completion",
        }

    tools.register("lerobot.rollout.stop", stop_tool)
    ctx = _CtxStub(tools)

    result = await ManipulationAgent().run(_post_specimen_completion_state(), ctx)

    assert result.success is True
    assert len(stop_calls) == 1
    assert stop_calls[0]["reason"] == "vision_manipulation_completion"
    assert stop_calls[0]["session_id"] == result.data["manipulation"]["session_id"]
    assert result.data["manipulation"]["stop_rollout_on_completion"] is True
    assert result.data["manipulation"]["rollout_stop"]["status"] == "STOPPED"
    assert result.data["manipulation_report"]["vision_context"]["manipulation_completion"]["detected"] is True
    assert result.data["manipulation_report"]["decision"]["completion_status"] == "verified_complete"
    assert result.data["robot_task_result"]["stop_rollout_on_completion"] is True


@pytest.mark.asyncio
async def test_manipulation_agent_keeps_rollout_active_until_post_place_gate_opens(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    tools = _tools(tmp_path)
    _register_action_active_rollout_status(tools, post_place_ready=False)
    stop_calls: list[dict[str, Any]] = []
    tools.register("lerobot.rollout.stop", lambda payload: stop_calls.append(dict(payload)) or {"ok": True, "status": "STOPPED"})

    result = await ManipulationAgent().run(_post_specimen_completion_state(), _CtxStub(tools))

    assert stop_calls == []
    assert result.data["manipulation"]["completion_status"] == "awaiting_post_place_home"
    assert result.data["manipulation"]["post_place_interlock"]["ready_for_utm_snapshot"] is False
    assert result.data["requested_next_stage"] == "vision"


@pytest.mark.asyncio
async def test_manipulation_agent_rejects_completion_from_another_rollout_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    tools = _tools(tmp_path)
    _register_action_active_rollout_status(tools, post_place_ready=True)
    stop_calls: list[dict[str, Any]] = []
    tools.register("lerobot.rollout.stop", lambda payload: stop_calls.append(dict(payload)) or {"ok": True, "status": "STOPPED"})
    state = _post_specimen_completion_state()
    state.latest_observations["vision_manipulation_completion"]["session_id"] = "stale-rollout-session"

    result = await ManipulationAgent().run(state, _CtxStub(tools))

    assert stop_calls == []
    assert result.data["manipulation"]["completion_status"] != "verified_complete"
    assert result.data["manipulation"]["completion_signal_identity"]["valid"] is False
    assert "session_id_mismatch" in result.data["manipulation"]["completion_signal_identity"]["mismatches"]


@pytest.mark.asyncio
async def test_manipulation_agent_completion_pass_does_not_restart_rollout(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    tools = _tools(tmp_path)
    _register_action_active_rollout_status(tools)
    start_calls: list[dict[str, Any]] = []
    stop_calls: list[dict[str, Any]] = []

    def start_tool(payload: dict[str, Any]) -> dict[str, Any]:
        start_calls.append(dict(payload))
        raise AssertionError("completion pass must not start a new rollout")

    def stop_tool(payload: dict[str, Any]) -> dict[str, Any]:
        stop_calls.append(dict(payload))
        return {
            "ok": True,
            "tool": "lerobot.rollout.stop",
            "status": "STOPPED",
            "session_id": payload.get("session_id", ""),
            "step_trace": [{"step": "STOPPED", "status": "ok", "detail": "vision completion"}],
            "events": [{"step": "STOPPED", "status": "ok", "detail": "vision completion"}],
        }

    tools.register("lerobot.rollout.start", start_tool)
    tools.register("lerobot.rollout.stop", stop_tool)
    state = _post_specimen_completion_state()
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "tool": "lerobot.rollout.start",
        "status": "ACTIVE",
        "session_id": "lr-rollout-existing-001",
        "profile_id": "fake_omx_ai",
        "workflow": "rollout",
    }
    state.run_metadata["robot_task_result"] = {
        "schema": "robot_task_result.v1",
        "rollout_session_id": "lr-rollout-existing-001",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete",
    }
    state.latest_observations["vision_manipulation_completion"]["session_id"] = "lr-rollout-existing-001"
    ctx = _CtxStub(tools)

    result = await ManipulationAgent().run(state, ctx)

    assert result.success is True
    assert start_calls == []
    assert len(stop_calls) == 1
    assert stop_calls[0]["session_id"] == "lr-rollout-existing-001"
    assert result.data["manipulation"]["tool"] == "lerobot.rollout.stop"
    assert result.data["manipulation"]["status"] == "STOPPED"
    assert result.data["manipulation"]["completion_status"] == "verified_complete"
    assert result.data["robot_task_result"]["handoff_status"] == "ready_for_equipment"


@pytest.mark.asyncio
async def test_manipulation_agent_marks_stop_failed_when_completion_stop_fails(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    tools = _tools(tmp_path)
    _register_action_active_rollout_status(tools)

    def stop_tool(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": "lerobot.rollout.stop",
            "status": "FAILED",
            "failure_code": "STOP_FAILED",
            "message": "simulated stop failure",
            "log_tail": "stop traceback tail",
            "step_trace": [{"step": "STOP_FAILED", "status": "failed", "detail": "simulated"}],
        }

    tools.register("lerobot.rollout.stop", stop_tool)
    ctx = _CtxStub(tools)

    result = await ManipulationAgent().run(_post_specimen_completion_state(), ctx)

    assert result.success is False
    assert result.data["manipulation"]["failure_code"] == "STOP_FAILED"
    assert result.data["manipulation"]["rollout_stop"]["log_tail"] == "stop traceback tail"
    assert result.data["manipulation_report"]["rollout_stop"]["status"] == "FAILED"
    assert result.data["manipulation_report"]["decision"]["reason"] == "STOP_FAILED"


@pytest.mark.asyncio
async def test_manipulation_agent_does_not_complete_while_rollout_stop_is_still_stopping(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    tools = _tools(tmp_path)
    _register_action_active_rollout_status(tools)

    tools.register(
        "lerobot.rollout.stop",
        lambda payload: {
            "ok": True,
            "tool": "lerobot.rollout.stop",
            "status": "STOPPING",
            "session_id": payload.get("session_id", ""),
            "step_trace": [{"step": "STOPPING", "status": "active", "detail": "process still alive"}],
        },
    )
    state = _post_specimen_completion_state()
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "tool": "lerobot.rollout.start",
        "status": "POLICY_ACTIVE",
        "session_id": "lr-rollout-stopping-001",
        "profile_id": "fake_omx_ai",
        "workflow": "rollout",
    }
    state.run_metadata["robot_task_result"] = {
        "schema": "robot_task_result.v1",
        "rollout_session_id": "lr-rollout-stopping-001",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete",
    }
    state.latest_observations["vision_manipulation_completion"]["session_id"] = "lr-rollout-stopping-001"

    result = await ManipulationAgent().run(state, _CtxStub(tools))

    assert result.success is True
    assert result.data["manipulation"]["stop_status"] == "STOPPING"
    assert result.data["manipulation"]["stop_confirmed"] is False
    assert result.data["manipulation_report"]["decision"]["completion_status"] != "verified_complete"
    assert result.data["robot_task_result"]["handoff_status"] == "needs_post_place_vision"
    assert result.data["requested_next_stage"] == "vision"
