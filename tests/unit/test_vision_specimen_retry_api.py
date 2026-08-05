from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agents.base_agent import AgentResult
from app import main as app_main
from app.controller import MainController
from orchestrator.state import Mode, OrchestratorState, Stage


class _VisionAgentStub:
    name = "vision_agent"

    def __init__(self, result: AgentResult) -> None:
        self.result = result
        self.calls = 0

    async def run(self, state: OrchestratorState, ctx: object) -> AgentResult:
        self.calls += 1
        return self.result


class _RegistryStub:
    def __init__(self, vision: _VisionAgentStub) -> None:
        self.vision = vision
        self.requested: list[str] = []

    def get(self, name: str) -> _VisionAgentStub:
        self.requested.append(name)
        if name != "vision_agent":
            raise AssertionError(f"unexpected agent request: {name}")
        return self.vision


def _intervention(*, checkpoint: str, status: str = "waiting_for_specimen") -> dict[str, object]:
    return {
        "schema": "vision_operator_intervention.v1",
        "run_id": "run-vision-retry",
        "checkpoint": checkpoint,
        "status": status,
        "reason": "specimen_not_detected",
        "capture_path": "/tmp/previous.png",
        "capture_url": "/artifacts/previous.png",
        "camera_key": "wrist" if checkpoint == "active_cam_ejection" else "utm",
        "requested_at": "2026-07-20T00:00:00+00:00",
        "retry_started_at": "",
        "retry_deadline_at": "",
        "retry_count": 0,
        "rollout_session_id": "rollout-1" if checkpoint == "utm_post_place" else "",
        "rollout_stopped": checkpoint == "utm_post_place",
    }


def _controller(result: AgentResult, *, checkpoint: str = "active_cam_ejection") -> tuple[MainController, _VisionAgentStub, _RegistryStub]:
    vision = _VisionAgentStub(result)
    registry = _RegistryStub(vision)
    controller = MainController.__new__(MainController)
    controller._state = OrchestratorState(
        run_id="run-vision-retry",
        experiment_id="exp-vision-retry",
        mode=Mode.TEST,
        stage=Stage.VISION,
        is_paused=True,
        run_metadata={"vision_operator_intervention": _intervention(checkpoint=checkpoint)},
    )
    controller._deps = SimpleNamespace(agent_registry=registry, agent_context=object())
    controller._vision_specimen_retry_locks = {}
    controller._vision_intervention_resume_event = asyncio.Event()
    controller._append_planning_message = AsyncMock()
    controller.emit_runtime_event = AsyncMock()

    def merge(stage: Stage, data: dict[str, object]) -> None:
        assert stage == Stage.VISION
        intervention = data.get("vision_operator_intervention")
        if isinstance(intervention, dict):
            controller._state.run_metadata["vision_operator_intervention"] = dict(intervention)
        observation = data.get("observation")
        if isinstance(observation, dict):
            controller._state.latest_observations = dict(observation)

    controller._merge_planning_agent_data = merge
    return controller, vision, registry


@pytest.mark.asyncio
async def test_live_tail_waits_for_active_cam_operator_retry_and_resumes_same_task() -> None:
    controller, _, _ = _controller(AgentResult(success=True, summary="unused"))

    wait_task = asyncio.create_task(controller._wait_for_vision_intervention_resume())
    await asyncio.sleep(0)

    assert wait_task.done() is False
    controller._state.is_paused = False
    controller._state.stage = Stage.MANIPULATION
    controller._vision_intervention_resume_event.set()

    assert await asyncio.wait_for(wait_task, timeout=0.2) is True
    assert controller._state.stage == Stage.MANIPULATION


@pytest.mark.asyncio
async def test_live_tail_waits_for_utm_operator_retry_and_resumes_same_task() -> None:
    controller, _, _ = _controller(
        AgentResult(success=True, summary="unused"),
        checkpoint="utm_post_place",
    )

    wait_task = asyncio.create_task(controller._wait_for_vision_intervention_resume())
    await asyncio.sleep(0)

    assert wait_task.done() is False
    controller._state.is_paused = False
    controller._state.stage = Stage.MANIPULATION
    controller._vision_intervention_resume_event.set()

    assert await asyncio.wait_for(wait_task, timeout=0.2) is True
    assert controller._state.stage == Stage.MANIPULATION


@pytest.mark.asyncio
async def test_controller_active_cam_retry_invokes_only_vision_and_wakes_existing_tail() -> None:
    resolved = _intervention(checkpoint="active_cam_ejection", status="resolved")
    resolved["capture_path"] = "/tmp/retry.png"
    controller, vision, registry = _controller(
        AgentResult(
            success=True,
            summary="specimen detected",
            data={
                "vision_operator_intervention": resolved,
                "observation": {"frame_path": "/tmp/retry.png"},
                "requested_next_stage": "manipulation",
            },
        )
    )

    response = await controller.retry_vision_specimen_placement(
        run_id="run-vision-retry",
        checkpoint="active_cam_ejection",
    )

    assert response["ok"] is True
    assert response["status"] == "resolved"
    assert response["checkpoint"] == "active_cam_ejection"
    assert response["capture_path"] == "/tmp/retry.png"
    assert vision.calls == 1
    assert registry.requested == ["vision_agent"]
    assert controller._state.stage == Stage.MANIPULATION
    assert controller._state.is_paused is False
    assert controller._vision_intervention_resume_event.is_set()


@pytest.mark.asyncio
async def test_controller_active_cam_retry_keeps_latest_frame_and_waits_again() -> None:
    waiting = _intervention(checkpoint="active_cam_ejection")
    waiting["capture_path"] = "/tmp/latest-empty.png"
    controller, vision, _ = _controller(
        AgentResult(
            success=True,
            summary="specimen not detected",
            data={"vision_operator_intervention": waiting},
        )
    )

    response = await controller.retry_vision_specimen_placement(
        run_id="run-vision-retry",
        checkpoint="active_cam_ejection",
    )

    assert response["ok"] is True
    assert response["status"] == "waiting_for_specimen"
    assert response["capture_path"] == "/tmp/latest-empty.png"
    assert vision.calls == 1
    assert controller._state.stage == Stage.VISION
    assert controller._state.is_paused is True
    assert controller._vision_intervention_resume_event.is_set() is False


@pytest.mark.asyncio
async def test_controller_rejects_checkpoint_mismatch_without_agent_call() -> None:
    controller, vision, _ = _controller(
        AgentResult(success=True, summary="unused"),
        checkpoint="active_cam_ejection",
    )

    with pytest.raises(ValueError, match="checkpoint mismatch"):
        await controller.retry_vision_specimen_placement(
            run_id="run-vision-retry",
            checkpoint="utm_post_place",
        )

    assert vision.calls == 0


@pytest.mark.asyncio
async def test_controller_duplicate_retry_is_idempotent_while_lock_is_held() -> None:
    controller, vision, _ = _controller(AgentResult(success=True, summary="unused"))
    lock = asyncio.Lock()
    await lock.acquire()
    controller._vision_specimen_retry_locks["run-vision-retry"] = lock
    try:
        response = await controller.retry_vision_specimen_placement(
            run_id="run-vision-retry",
            checkpoint="active_cam_ejection",
        )
    finally:
        lock.release()

    assert response["ok"] is True
    assert response["idempotent"] is True
    assert response["status"] == "retrying"
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_controller_utm_operator_retry_calls_vision_only_and_never_restarts_rollout() -> None:
    resolved = _intervention(checkpoint="utm_post_place", status="resolved")
    controller, vision, registry = _controller(
        AgentResult(
            success=True,
            summary="UTM placement detected",
            data={
                "vision_operator_intervention": resolved,
                "requested_next_stage": "manipulation",
            },
        ),
        checkpoint="utm_post_place",
    )

    response = await controller.retry_vision_specimen_placement(
        run_id="run-vision-retry",
        checkpoint="utm_post_place",
    )

    assert response["ok"] is True
    assert response["status"] == "resolved"
    assert response["rollout_restarted"] is False
    assert vision.calls == 1
    assert registry.requested == ["vision_agent"]


def test_run_scoped_retry_endpoint_validates_run_and_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(
        snapshot=lambda: {"state": {"run_id": "run-api"}},
        retry_vision_specimen_placement=AsyncMock(
            return_value={
                "ok": True,
                "run_id": "run-api",
                "checkpoint": "active_cam_ejection",
                "status": "resolved",
            }
        ),
    )
    monkeypatch.setattr(app_main, "controller", fake)
    client = TestClient(app_main.app)

    unknown = client.post(
        "/api/runs/other/vision/specimen-placement-retry",
        json={"checkpoint": "active_cam_ejection"},
    )
    invalid = client.post(
        "/api/runs/run-api/vision/specimen-placement-retry",
        json={"checkpoint": "other"},
    )
    accepted = client.post(
        "/api/runs/run-api/vision/specimen-placement-retry",
        json={"checkpoint": "active_cam_ejection"},
    )

    assert unknown.status_code == 404
    assert invalid.status_code == 422
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "resolved"
    fake.retry_vision_specimen_placement.assert_awaited_once_with(
        run_id="run-api",
        checkpoint="active_cam_ejection",
    )
