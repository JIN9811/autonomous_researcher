"""Candidate-bound synthetic camera evidence; no model or native camera calls."""
from copy import deepcopy
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image
import pytest


def mesh_request(tmp_path, shape="box"):
    import trimesh
    root = tmp_path / shape
    root.mkdir()
    path = root / "specimen.stl"
    mesh = trimesh.creation.box(extents=(2, 3, 4)) if shape == "box" else trimesh.creation.icosphere(subdivisions=2)
    mesh.export(path)
    identity = {"run_id": "mesh-run", "loop_id": 2, "specimen_id": "current-specimen",
        "session_id": "current-placement", "candidate_id": "current-candidate"}
    return {**identity, "runtime_mode": "test", "allow_virtual_bridge_in_test": True,
        "prefer_virtual_bridge_in_test": True, "virtual_specimen_mesh_required": True,
        "frame_id": shape, "output_dir": str(root / "capture"),
        "virtual_specimen_mesh": {"schema": "virtual_specimen_mesh.v1", **identity,
            "stl_path": str(path), "stl_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "geometry_hash": "parameter-hash-" + shape}}


def camera_tools():
    from mcp_tools.camera_tools import register_camera_tools
    from mcp_tools.tool_registry import ToolRegistry
    class NoNative:
        def __getattr__(self, name):
            def forbidden(*a, **k): pytest.fail("Native camera invoked: " + name)
            return forbidden
    tools = ToolRegistry()
    register_camera_tools(tools, utm_runtime_manager=NoNative())
    return tools


def test_distinct_actual_meshes_produce_distinct_detector_bound_same_capture_pairs(tmp_path):
    tools, raw_frames = camera_tools(), []
    for shape in ("box", "sphere"):
        request = mesh_request(tmp_path, shape)
        result = tools.call("vision.utm_specimen_presence.capture", request)
        assert result["ok"] and result["detected"] and result["virtualized"]
        receipt = result["frame_capture"]["mesh_render"]
        assert receipt["stl_sha256"] == request["virtual_specimen_mesh"]["stl_sha256"]
        assert receipt["geometry_hash"] == request["virtual_specimen_mesh"]["geometry_hash"]
        assert receipt["synthetic"] and receipt["renderer"] == "actual_stl_cpu"
        raw = np.asarray(Image.open(result["raw_frame_path"]))
        annotated = np.asarray(Image.open(result["annotated_frame_path"]))
        assert raw.shape == annotated.shape == (480, 640, 3)
        x0, y0, x1, y1 = result["bbox_xyxy"]
        cx, cy = result["center_px"]
        assert x0 < cx < x1 and y0 < cy < y1
        assert tuple(annotated[y0, x0]) == (20, 220, 130)
        allowed_overlay = np.zeros(raw.shape[:2], dtype=bool)
        allowed_overlay[y0:y1 + 1, x0:x1 + 1] = True
        assert np.array_equal(raw[~allowed_overlay], annotated[~allowed_overlay])
        raw_frames.append(raw)
    assert not np.array_equal(*raw_frames)


@pytest.mark.parametrize("fault", ["missing", "identity", "loop", "candidate", "digest", "not_found", "directory", "invalid", "degenerate"])
def test_requested_candidate_mesh_failure_is_unknown_not_rectangle_success(tmp_path, fault):
    request = mesh_request(tmp_path)
    mesh = request["virtual_specimen_mesh"]
    if fault == "missing": request.pop("virtual_specimen_mesh")
    elif fault == "identity": mesh["specimen_id"] = "old-specimen"
    elif fault == "loop": mesh["loop_id"] = 1
    elif fault == "candidate": mesh["candidate_id"] = "old-candidate"
    elif fault == "digest": mesh["stl_sha256"] = "0" * 64
    elif fault == "not_found": mesh["stl_path"] += ".missing"
    elif fault == "directory": mesh["stl_path"] = str(tmp_path)
    elif fault == "degenerate":
        import trimesh
        trimesh.Trimesh(vertices=[[0, 0, 0], [1, 1, 1], [2, 2, 2]], faces=[[0, 1, 2]], process=False).export(mesh["stl_path"])
        mesh["stl_sha256"] = hashlib.sha256(Path(mesh["stl_path"]).read_bytes()).hexdigest()
    else:
        Path(mesh["stl_path"]).write_bytes(b"not an STL mesh")
        mesh["stl_sha256"] = hashlib.sha256(b"not an STL mesh").hexdigest()
    result = camera_tools().call("vision.utm_specimen_presence.capture", request)
    assert result["ok"] is False and result["status"] == "unknown" and not result["detected"]
    assert result["failure_code"] == "VIRTUAL_SPECIMEN_MESH_INVALID"


def test_render_material_option_does_not_change_default_preview_or_use_schematic_fallback(tmp_path):
    from mcp_tools.mock_tools import _try_write_stl_iso_capture_png
    request = mesh_request(tmp_path)
    mesh = Path(request["virtual_specimen_mesh"]["stl_path"])
    before, material, after = (tmp_path / name for name in ("before.png", "material.png", "after.png"))
    kwargs = {"stl_path": mesh, "specimen_id": "same", "geometry_type": "gyroid"}
    assert _try_write_stl_iso_capture_png(before, **kwargs)
    assert _try_write_stl_iso_capture_png(material, **kwargs, material_color=(225, 30, 35),
        canvas_size=(640, 480), background_color=(210, 210, 210))
    assert _try_write_stl_iso_capture_png(after, **kwargs)
    assert before.read_bytes() == after.read_bytes()
    assert Image.open(before).size == (760, 420) and Image.open(material).size == (640, 480)
    assert before.read_bytes() != material.read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize("virtual", [True, False])
async def test_vision_passes_current_host_mesh_only_on_strict_virtual_placement(tmp_path, monkeypatch, virtual):
    from agents.vision_agent import VisionAgent
    from tests.unit.test_vision_agent import _state, _CtxStub
    from tests.unit.test_virtual_device_llm_execution import virtualize
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.state import Mode
    state = _state()
    if virtual: virtualize(state, tmp_path)
    else: state.mode = Mode.LIVE
    request = mesh_request(tmp_path)
    reference = request["virtual_specimen_mesh"]
    state.current_experiment_spec.update(specimen_id="current-specimen", candidate_id="current-candidate")
    state.run_metadata["specimen_result"].update(specimen_id="current-specimen", candidate_id="current-candidate",
        stl_path=reference["stl_path"], geometry_hash=reference["geometry_hash"])
    interlock = {"schema": "post_place_interlock.v1", "session_id": "current-placement",
        "ungrasping_seen": True, "home_after_ungrasping": True, "ready_for_utm_snapshot": True}
    state.run_metadata["manipulation_result"] = {"ok": True, "session_id": "current-placement", "workflow": "rollout",
        "runtime_phase": "ACTION_ACTIVE", "action_count": 30, "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete", "post_place_interlock": interlock}
    state.run_metadata["robot_task_result"] = {"rollout_session_id": "current-placement",
        "handoff_status": "needs_post_place_vision", "completion_status": "reported_complete", "post_place_interlock": interlock}
    tools, calls = ToolRegistry(), []
    tools.register("vision.utm_specimen_presence.capture", lambda payload: calls.append(deepcopy(payload)) or
        {"ok": False, "status": "unknown", "detected": False, "failure_code": "controlled_capture_hold"})
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    await VisionAgent().run(state, _CtxStub(tools))
    assert len(calls) == 1
    payload = calls[0]
    if virtual:
        assert payload["virtual_specimen_mesh_required"] is True
        mesh = payload["virtual_specimen_mesh"]
        assert mesh["stl_path"] == reference["stl_path"] and mesh["stl_sha256"] == reference["stl_sha256"]
        assert mesh["geometry_hash"] == reference["geometry_hash"]
        for key in ("run_id", "loop_id", "specimen_id", "session_id", "candidate_id"):
            assert mesh[key] == payload[key]
    else:
        assert "virtual_specimen_mesh_required" not in payload and "virtual_specimen_mesh" not in payload
        assert "loop_id" not in payload and "candidate_id" not in payload
