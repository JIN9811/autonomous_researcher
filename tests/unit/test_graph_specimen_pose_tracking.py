from __future__ import annotations

from pathlib import Path

import yaml

from graphs import load_graph_config


def _yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_vision_module_uses_active_cam_without_d455_snapshot_steps() -> None:
    payload = _yaml("graphs/modules/vision/module.yaml")
    module = payload["module"]
    step_ids = {item["id"] for item in module["internal_graph"]}

    assert "lerobot.active_robot_cam.capture" in module["tools"]
    assert "lerobot.rollout.stop" in module["tools"]
    assert "vision.utm_specimen_presence.capture" in module["tools"]
    assert "vision.specimen_pose_snapshot" not in module["tools"]
    assert not any("d455" in step_id.lower() for step_id in step_ids)
    assert "specimen_pose.v1" not in module["io_contract"]["produces"]


def test_manipulation_module_consumes_active_camera_return_gate() -> None:
    payload = _yaml("graphs/modules/manipulation/module.yaml")
    module = payload["module"]
    contract = module["runtime_contract"]

    assert contract["requires_camera_return_to_vla"] is True
    assert "specimen_pose.v1" not in module["io_contract"]["input"]


def test_closed_loop_graph_has_post_place_vision_verification() -> None:
    config = load_graph_config(Path("graphs/configs/atr_closed_loop.yaml"))
    nodes = {node.id: node for node in config.nodes}
    edge_pairs = {(edge.source, edge.target) for edge in config.edges}
    sidecar_edges = {
        (edge.source, edge.target)
        for edge in config.edges
        if edge.metadata.get("runtime_edge") == "runtime_sidecar"
    }

    assert "vision" in nodes
    assert "manipulation" in nodes
    assert "vision_verify" in nodes
    assert nodes["vision_verify"].kind == "sidecar"
    assert nodes["vision_verify"].stage is None
    assert ("vision", "manipulation") in edge_pairs
    assert ("manipulation", "vision_verify") in sidecar_edges
    assert ("vision_verify", "equipment") in sidecar_edges
    assert config.transitions["manipulation"] == "equipment"
    assert config.next_stage("manipulation", state_metadata={"agent_result": {"requested_next_stage": "vision"}}) == "vision"
    assert config.next_stage("vision", state_metadata={"agent_result": {"requested_next_stage": "equipment"}}) == "equipment"
    assert [
        config.transitions[stage]
        for stage in ("equipment", "analysis", "knowledge", "bo")
    ] == ["analysis", "knowledge", "bo", "guardian"]
