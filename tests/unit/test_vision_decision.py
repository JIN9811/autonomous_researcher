"""Non-actuating tests for image-bound Vision decisions."""
import json
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
from PIL import Image

from orchestrator.state import OrchestratorState, Mode, Stage


@pytest.fixture
def state():
    return OrchestratorState(run_id="vision-decision", experiment_id="exp", mode=Mode.TEST,
        stage=Stage.VISION, current_experiment_spec={"specimen_id": "s1"})


@pytest.fixture
def capture(tmp_path):
    raw, annotated = tmp_path / "raw.png", tmp_path / "annotated.png"
    Image.new("RGB", (32, 24), "red").save(raw)
    Image.new("RGB", (32, 24), "green").save(annotated)
    return {"ok": True, "detected": True, "frame_id": "f1", "specimen_id": "s1",
        "timestamp": datetime.now(timezone.utc).isoformat(), "bbox_xyxy": [1, 2, 20, 21],
        "raw_frame_path": str(raw), "annotated_frame_path": str(annotated)}


class Model:
    force_real_llm_in_test = True

    def __init__(self, tool="accept_visual_evidence", change=None):
        self.tool, self.change, self.inputs = tool, change, []

    async def complete(self, task, prompt, *, images=None, **kwargs):
        self.inputs.append((task, prompt, images))
        context = json.loads(prompt.split("\nCONTEXT:\n")[1])
        if self.change:
            self.change()
        return SimpleNamespace(model="fixture-vision", raw={}, text=json.dumps({
            "tool": self.tool, "arguments": {"contract_id": context["contract_id"]},
            "reason": "The marked region agrees with the raw specimen.",
            "evidence_refs": ["frame:current"] if images else ["context:task"]}))


@pytest.mark.asyncio
async def test_review_transmits_ordered_images_and_preserves_detector_facts(state, capture):
    from agents.vision_decision import review_visual_evidence
    before, model = deepcopy(capture), Model()
    result = await review_visual_evidence(state, model, capture, "pickup")
    assert result["status"] == "accepted"
    assert result["llm_used"] is True
    images = model.inputs[0][2]
    assert len(images) == 2
    assert "raw" in images[0].label and "annotated" in images[1].label
    assert result["images"][0]["sha256"] != result["images"][1]["sha256"]
    assert capture == before


@pytest.mark.asyncio
async def test_review_supplies_actual_pixel_frame_and_original_validity_reason(state, capture):
    from agents.vision_decision import review_visual_evidence
    capture.update(status="unknown", unknown_reason="registration_unavailable", registered=False,
                   width=999, height=999)
    before, model = deepcopy(capture), Model()
    await review_visual_evidence(state, model, capture, "clearance")
    context = json.loads(model.inputs[0][1].split("\nCONTEXT:\n")[1])
    assert context["image_geometry"] == {"width_px": 32, "height_px": 24,
        "coordinate_system": "pixel_xy_top_left", "bbox_format": "xyxy"}
    assert context["detector"]["unknown_reason"] == "registration_unavailable"
    assert context["detector"]["registered"] is False
    assert context["target"] == {"specimen_id": "s1"}
    assert capture == before


@pytest.mark.asyncio
@pytest.mark.parametrize("contract", ["active_cam", "placement", "clearance"])
async def test_prompt_response_examples_are_dispatchable_for_both_choices(state, capture, contract):
    from agents.vision_decision import review_visual_evidence
    model = Model()
    await review_visual_evidence(state, model, capture, contract)
    context = json.loads(model.inputs[0][1].split("\nCONTEXT:\n")[1])
    examples = context["response_examples"]
    assert {example["tool"] for example in examples} == {"accept_visual_evidence", "return_to_owner"}
    for example in examples:
        assert example["arguments"] == {"contract_id": contract}
        assert example["evidence_refs"] == ["frame:current"]
        class ExampleModel:
            force_real_llm_in_test = True
            async def complete(self, *args, **kwargs):
                return SimpleNamespace(model="fixture", raw={}, text=json.dumps(example))
        result = await review_visual_evidence(state, ExampleModel(), capture, contract)
        assert "error" not in result
        assert result["status"] == ("accepted" if example["tool"] == "accept_visual_evidence" else "review_required")


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["missing", "invalid", "dimensions", "identity"])
async def test_invalid_pair_or_scope_never_reaches_model(state, capture, tmp_path, broken):
    from agents.vision_decision import review_visual_evidence
    if broken == "missing": capture.pop("raw_frame_path")
    if broken == "invalid": (tmp_path / "raw.png").write_bytes(b"not an image")
    if broken == "dimensions": Image.new("RGB", (20, 20)).save(tmp_path / "raw.png")
    if broken == "identity": capture["specimen_id"] = "previous"
    model = Model()
    result = await review_visual_evidence(state, model, capture, "pickup")
    assert result["status"] == "review_required"
    assert model.inputs == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stop", "loop", "spec", "session"])
async def test_review_cannot_authorize_changed_state(state, capture, change):
    from agents.vision_decision import review_visual_evidence
    def mutate():
        if change == "stop": state.stop_requested = True
        if change == "loop": state.loop_count += 1
        if change == "spec": state.current_experiment_spec["specimen_id"] = "next"
        if change == "session": state.run_metadata["manipulation_result"] = {"session_id": "new"}
    result = await review_visual_evidence(state, Model(change=mutate), capture, "placement")
    assert result["status"] == "review_required"


@pytest.mark.asyncio
async def test_rollout_session_alias_change_during_review_is_rejected(state, capture):
    from agents.vision_decision import review_visual_evidence
    state.run_metadata["robot_task_result"] = {"rollout_session_id": "one"}
    model = Model(change=lambda: state.run_metadata["robot_task_result"].update(rollout_session_id="two"))
    result = await review_visual_evidence(state, model, capture, "placement")
    assert result["status"] == "review_required"


@pytest.mark.asyncio
async def test_evidence_changed_on_disk_during_review_is_rejected(state, capture):
    from agents.vision_decision import review_visual_evidence
    model = Model(change=lambda: Image.new("RGB", (32, 24), "blue").save(capture["raw_frame_path"]))
    result = await review_visual_evidence(state, model, capture, "placement")
    assert result["status"] == "review_required"


@pytest.mark.asyncio
async def test_mismatched_capture_session_never_reaches_model(state, capture):
    from agents.vision_decision import review_visual_evidence
    state.run_metadata["manipulation_result"] = {"session_id": "one"}
    capture["session_id"] = "old"
    model = Model()
    result = await review_visual_evidence(state, model, capture, "placement")
    assert result["status"] == "review_required"
    assert not model.inputs


@pytest.mark.asyncio
async def test_specimen_metadata_change_cannot_relabel_capture(state, capture):
    from agents.vision_decision import review_visual_evidence
    state.current_experiment_spec = {}
    state.run_metadata["specimen_result"] = {"specimen_id": "s1"}
    model = Model(change=lambda: state.run_metadata["specimen_result"].update(specimen_id="s2"))
    result = await review_visual_evidence(state, model, capture, "placement")
    assert result["scope_valid"] is False
    assert result["status"] == "review_required"


@pytest.mark.asyncio
async def test_stale_pickup_never_becomes_fresh_after_model_acceptance(state, capture):
    from agents.vision_decision import review_visual_evidence
    capture["timestamp"] = "2000-01-01T00:00:00+00:00"
    result = await review_visual_evidence(state, Model(), capture, "pickup")
    assert result["status"] == "review_required"
    assert result["failure_code"] == "VISION_EVIDENCE_EXPIRED"
    assert capture["timestamp"] == "2000-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_pickup_uses_original_capture_alias_not_current_time(state, capture):
    from agents.vision_decision import review_visual_evidence
    capture.pop("timestamp")
    capture["captured_at"] = "2000-01-01T00:00:00+00:00"
    result = await review_visual_evidence(state, Model(), capture, "pickup")
    assert result["status"] == "review_required"
    assert result["failure_code"] == "VISION_EVIDENCE_EXPIRED"


@pytest.mark.asyncio
async def test_test_mode_retains_existing_consumer_grace_without_renewing_timestamp(state, capture):
    from agents.vision_decision import review_visual_evidence
    original = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    capture["timestamp"] = original
    result = await review_visual_evidence(state, Model(), capture, "pickup")
    assert result["status"] == "accepted"
    assert result["freshness"]["reason"] == "fresh_with_test_mode_grace"
    assert capture["timestamp"] == original


@pytest.mark.asyncio
async def test_live_mode_never_uses_test_grace(state, capture):
    from agents.vision_decision import review_visual_evidence
    state.mode = Mode.LIVE
    capture["timestamp"] = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    result = await review_visual_evidence(state, Model(), capture, "pickup")
    assert result["failure_code"] == "VISION_EVIDENCE_EXPIRED"


@pytest.mark.asyncio
async def test_selects_existing_contract_not_raw_hardware_arguments(state):
    from agents.vision_decision import select_vision_tool
    result = await select_vision_tool(state, Model("execute_verification"), "active_cam")
    assert result["status"] == "accepted"
    assert result["request"]["arguments"] == {"contract_id": "active_cam"}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["lerobot.replay.start", "execute_verification", "return_to_owner"])
async def test_review_only_accepts_bounded_review_tools(state, capture, tool):
    from agents.vision_decision import review_visual_evidence
    result = await review_visual_evidence(state, Model(tool), capture, "placement")
    assert result["status"] == "review_required"


@pytest.mark.asyncio
async def test_explicit_non_llm_test_is_not_visual_validation(state):
    from agents.vision_decision import review_visual_evidence
    result = await review_visual_evidence(state, SimpleNamespace(), {}, "pickup")
    assert result["status"] == "deterministic_test"
    assert result["llm_used"] is False


@pytest.mark.asyncio
async def test_vision_run_selects_capture_then_reviews_and_blocks_conflicting_frame(state, capture, tmp_path, monkeypatch):
    from agents.vision_agent import VisionAgent
    from mcp_tools.tool_registry import ToolRegistry
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    state.run_metadata["specimen_result"] = {"ok": True, "specimen_id": "s1", "handoff_status": "ready"}
    tools = ToolRegistry()
    tools.register("camera.capture", lambda payload: {**capture, "confidence": .9, "pose_confidence": .9})
    model = Model()
    model.tools = tools
    complete = model.complete
    async def choose(task, prompt, **kwargs):
        model.tool = "return_to_owner" if kwargs.get("images") else "execute_verification"
        return await complete(task, prompt, **kwargs)
    model.complete = choose
    result = await VisionAgent().run(state, model)
    assert not result.success
    assert result.data["vision_decision"]["status"] == "review_required"
    assert result.data["observation"]["raw_capture"]["detected"] is True
    assert result.data["observation"]["transfer_readiness"]["ready"] is False
    assert result.data.get("requested_next_stage") not in {"manipulation", "equipment"}
    assert len(model.inputs) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["reject", "cancel", "scope", "lowercase_stop", "accept_lowercase", "task_reject"])
async def test_placement_stop_precedes_multimodal_review_and_rejection_blocks_handoff(state, capture, tmp_path, monkeypatch, outcome):
    import asyncio
    from agents.vision_agent import VisionAgent
    from mcp_tools.tool_registry import ToolRegistry
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    state.run_metadata["specimen_result"] = {"ok": True, "specimen_id": "s1", "handoff_status": "ready"}
    interlock = {"session_id": "rollout", "ungrasping_seen": True,
                 "home_after_ungrasping": True, "ready_for_utm_snapshot": True}
    state.run_metadata["manipulation_result"] = {"ok": True, "session_id": "rollout", "workflow": "rollout",
        "action_count": 30, "runtime_phase": "ACTION_ACTIVE", "handoff_status": "needs_post_place_vision", "completion_status": "reported_complete",
        "post_place_interlock": interlock}
    state.run_metadata["robot_task_result"] = {"rollout_session_id": "rollout", "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete", "post_place_interlock": interlock}
    order, tools = [], ToolRegistry()
    tools.register("vision.utm_specimen_presence.capture", lambda payload: {**capture, "session_id": "rollout",
        "source": "utm_ros_frame", "confidence": .8, "width": 32, "height": 24})
    tools.register("lerobot.rollout.stop", lambda payload: order.append("stop") or
        {"ok": True, "status": " stopped " if "lowercase" in outcome else "STOPPED", "session_id": "rollout"})
    def during_review():
        order.append("review")
        assert state.run_metadata["manipulation_result"]["completion_status"] != "verified_complete"
        if outcome == "cancel":
            raise asyncio.CancelledError()
        if outcome == "scope":
            state.run_metadata["manipulation_result"] = {"session_id": "replacement", "status": "RUNNING"}
    model = Model("accept_visual_evidence" if outcome in {"accept_lowercase", "task_reject"} else "return_to_owner", change=during_review)
    # Manipulation has its own response schema and model role after Vision accepts.
    from tests.unit.test_manipulation_decision import Model as ManipulationModel
    model.for_agent_decision = lambda owner: ManipulationModel("return_to_owner" if outcome == "task_reject" else None)
    model.tools = tools
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await VisionAgent().run(state, model)
        assert state.run_metadata["manipulation_result"]["handoff_status"] == "needs_post_place_vision"
        assert VisionAgent._post_manipulation_completion_requested(state)
        return
    result = await VisionAgent().run(state, model)
    assert order == ["stop", "review"]
    if outcome == "task_reject":
        assert not result.success
        assert result.data["vision_decision"]["status"] == "accepted"
        assert result.data["observation"]["vision_manipulation_completion"]["detected"] is True
        assert result.data.get("requested_next_stage") != "equipment"
        assert state.run_metadata["manipulation_result"]["completion_status"] == "stopped_pending_task_review"
        return
    if outcome == "accept_lowercase":
        from utils.utm_clear_cycle import merge_utm_clear_cycle
        assert result.success
        merge_utm_clear_cycle(state, Stage.VISION, result.data)
        assert state.run_metadata["utm_verifications"]["verification_1"]["confirmed"] is True
        return
    assert not result.success
    if outcome == "scope":
        assert state.run_metadata["manipulation_result"] == {"session_id": "replacement", "status": "RUNNING"}
        assert not result.data.get("observation", {}).get("raw_capture")
        return
    completion = result.data["observation"]["vision_manipulation_completion"]
    assert completion["rollout_stopped"] is True
    assert completion["detected"] is True
    assert completion["blocking_reason"]
    assert result.data.get("requested_next_stage") != "equipment"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["reject", "deadline", "terminal", "scope"])
async def test_clearance_model_disagreement_prevents_analysis_after_completed_replay(capture, tmp_path, outcome):
    import time
    from agents.vision_agent import VisionAgent
    from tests.unit.test_utm_clear_cycle import state_with_placement, equipment_data, ReplayTools
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {"vision": "execute", "manipulation": "execute"}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    state.run_metadata["utm_clear_execution"]["state"] = "running"
    tools = ReplayTools(state)
    tools.status, tools.home = "COMPLETED", True
    original_call = tools.call
    def call(name, payload):
        result = original_call(name, payload)
        if name == "vision.utm_specimen_presence.capture":
            result.update(raw_frame_path=capture["raw_frame_path"], annotated_frame_path=capture["annotated_frame_path"])
        return result
    tools.call = call
    def during_review():
        execution = state.run_metadata["utm_clear_execution"]
        if outcome == "deadline": execution["pending_deadline_at"] = time.time() - 1
        if outcome == "terminal": execution.update(state="error", success=False, failure_code="UTM_CLEAR_PENDING_TIMEOUT")
        if outcome == "scope": execution["session_id"] = "replacement"
    model = Model("return_to_owner" if outcome == "reject" else "accept_visual_evidence", change=during_review)
    model.tools = tools
    result = await VisionAgent().run(state, model)
    assert not result.success
    assert result.data.get("requested_next_stage") != "analysis"
    assert not result.data.get("utm_verification_2", {}).get("record", {}).get("confirmed")
    assert result.data["vision_decision"]["status"] == "review_required"
    if outcome == "terminal":
        assert state.run_metadata["utm_clear_execution"]["state"] == "error"
    if outcome == "scope":
        assert state.run_metadata["utm_clear_execution"]["session_id"] == "replacement"
    assert [name for name, _ in tools.calls] == ["lerobot.replay.status", "vision.utm_specimen_presence.capture"]


@pytest.mark.asyncio
@pytest.mark.parametrize("detector_status", ["unknown", "occupied"])
async def test_model_acceptance_does_not_override_clearance_detector_gate(capture, detector_status):
    """Archived unknown images may look empty to a model; only code owns clearance."""
    from agents.vision_agent import VisionAgent
    from tests.unit.test_utm_clear_cycle import state_with_placement, equipment_data, ReplayTools
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {"vision": "execute", "manipulation": "execute"}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    state.run_metadata["utm_clear_execution"]["state"] = "running"
    tools = ReplayTools(state)
    tools.status, tools.home = "COMPLETED", True
    original_call = tools.call
    def call(name, payload):
        result = original_call(name, payload)
        if name == "vision.utm_specimen_presence.capture":
            result.update(raw_frame_path=capture["raw_frame_path"],
                          annotated_frame_path=capture["annotated_frame_path"],
                          status=detector_status, clear_confirmed=False,
                          detected=detector_status == "occupied")
        return result
    tools.call = call
    model = Model("accept_visual_evidence")
    model.tools = tools
    result = await VisionAgent().run(state, model)
    assert result.data["vision_decision"]["status"] == "accepted"
    assert result.data["requested_next_stage"] == "vision"
    assert state.run_metadata["utm_clear_execution"]["state"] == "waiting"
    assert result.data["utm_verification_2"]["record"]["confirmed"] is False
    assert len(model.inputs) == 1


@pytest.mark.asyncio
async def test_selection_refusal_is_valid_observation_contract_without_capture(state):
    from agents.vision_agent import VisionAgent
    from mcp_tools.tool_registry import ToolRegistry
    from policies.validation_policy import validate_agent_output
    model = Model("return_to_owner")
    model.tools = ToolRegistry()
    result = await VisionAgent().run(state, model)
    assert not result.success
    assert validate_agent_output("vision", result.data) == (True, "ok")
    assert result.data["observation"]["transfer_readiness"]["ready"] is False
    assert len(model.inputs) == 1


@pytest.mark.asyncio
async def test_stop_requested_before_vision_never_starts_camera_runtime(state):
    from agents.vision_agent import VisionAgent
    from mcp_tools.tool_registry import ToolRegistry
    called = []
    model = Model()
    model.tools = ToolRegistry()
    model.tools.register("vision.utm_runtime.start", lambda payload: called.append(payload) or {"ok": True})
    state.stop_requested = True
    result = await VisionAgent().run(state, model)
    assert not result.success
    assert not called and not model.inputs
