from __future__ import annotations

from pathlib import Path

import yaml

from graphs import load_graph_config


def _yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_vision_module_declares_specimen_pose_tool_and_steps() -> None:
    payload = _yaml("graphs/modules/vision/module.yaml")
    module = payload["module"]
    step_ids = {item["id"] for item in module["internal_graph"]}

    assert "vision.specimen_pose_snapshot" in module["tools"]
    assert "03a_acquire_d455f_lease" in step_ids
    assert "03b_one_shot_specimen_pose" in step_ids
    assert "03c_release_d455f_to_vla" in step_ids
    assert "specimen_pose.v1" in module["io_contract"]["produces"]


def test_manipulation_module_consumes_camera_return_gate() -> None:
    payload = _yaml("graphs/modules/manipulation/module.yaml")
    module = payload["module"]
    contract = module["runtime_contract"]

    assert contract["requires_camera_return_to_vla"] is True
    assert "specimen_pose.v1" in module["io_contract"]["input"]


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
