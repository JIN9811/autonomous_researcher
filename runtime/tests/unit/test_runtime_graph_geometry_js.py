from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_JS = ROOT / "web" / "static" / "runtime_graph_geometry.js"
GRAPH_CONFIG_DIR = ROOT / "graphs" / "configs"


def _normalize_with_browser_geometry(graph: dict) -> dict:
    script = f"""
const fs = require("fs");
const vm = require("vm");
const context = {{ window: {{}} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(GEOMETRY_JS))}, "utf8"), context);
const graph = {json.dumps(graph)};
const normalized = context.window.ATRRuntimeGraphGeometry.normalizeNodePositions(graph, {{
  grid: 16,
  nodeWidth: 184,
  nodeHeight: 76,
  collisionGapX: 44,
  collisionGapY: 34,
}});
process.stdout.write(JSON.stringify(normalized));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _overlapping_pairs(graph: dict) -> list[tuple[str, str]]:
    width = 184 + 44
    height = 76 + 34
    nodes = graph.get("nodes", [])
    collisions: list[tuple[str, str]] = []
    for index, left in enumerate(nodes):
        lx = float(left["position"]["x"])
        ly = float(left["position"]["y"])
        for right in nodes[index + 1 :]:
            rx = float(right["position"]["x"])
            ry = float(right["position"]["y"])
            if lx < rx + width and lx + width > rx and ly < ry + height and ly + height > ry:
                collisions.append((str(left["id"]), str(right["id"])))
    return collisions


@pytest.mark.parametrize("config_path", sorted(GRAPH_CONFIG_DIR.glob("*.yaml")), ids=lambda path: path.stem)
def test_shared_runtime_geometry_prevents_node_overlap(config_path: Path) -> None:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    graph = payload.get("graph", payload)
    if not isinstance(graph, dict) or not graph.get("nodes"):
        pytest.skip("graph config has no nodes")

    normalized = _normalize_with_browser_geometry(graph)

    assert _overlapping_pairs(normalized) == []


def test_shared_runtime_geometry_keeps_main_route_order() -> None:
    payload = yaml.safe_load((GRAPH_CONFIG_DIR / "atr_closed_loop.yaml").read_text(encoding="utf-8"))
    normalized = _normalize_with_browser_geometry(payload["graph"])
    positions = {node["id"]: node["position"] for node in normalized["nodes"]}

    assert positions["manipulation"]["x"] < positions["vision_verify"]["x"]
    assert positions["vision_verify"]["x"] < positions["equipment"]["x"]
    assert positions["vision_verify"]["y"] <= positions["equipment"]["y"]


def test_shared_runtime_geometry_preserves_authored_route_row_when_horizontal_shift_is_smaller() -> None:
    payload = yaml.safe_load((GRAPH_CONFIG_DIR / "lerobot_pick_place.yaml").read_text(encoding="utf-8"))
    normalized = _normalize_with_browser_geometry(payload["graph"])
    positions = {node["id"]: node["position"] for node in normalized["nodes"]}

    assert positions["dispatch"]["y"] == positions["idle"]["y"]
    assert positions["dispatch"]["x"] < positions["idle"]["x"]


def test_shared_runtime_geometry_spreads_edge_labels_away_from_each_other_and_nodes() -> None:
    script = f"""
const fs = require("fs");
const vm = require("vm");
const context = {{ window: {{}} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(GEOMETRY_JS))}, "utf8"), context);
const labels = [
  {{ key: "a", x: 200, y: 120, width: 120, height: 22 }},
  {{ key: "b", x: 200, y: 120, width: 120, height: 22 }},
  {{ key: "c", x: 202, y: 121, width: 120, height: 22 }},
];
const resolved = context.window.ATRRuntimeGraphGeometry.resolveLabelCollisions(labels, {{
  gap: 8,
  obstacles: [{{ left: 140, top: 105, right: 260, bottom: 135 }}],
}});
process.stdout.write(JSON.stringify(resolved));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    labels = json.loads(completed.stdout)

    def rect(label: dict) -> tuple[float, float, float, float]:
        return (
            label["x"] - label["width"] / 2,
            label["y"] - label["height"] / 2,
            label["x"] + label["width"] / 2,
            label["y"] + label["height"] / 2,
        )

    obstacle = (140, 105, 260, 135)
    rectangles = [rect(label) for label in labels]
    for index, left in enumerate(rectangles):
        assert not (left[0] < obstacle[2] and left[2] > obstacle[0] and left[1] < obstacle[3] and left[3] > obstacle[1])
        for right in rectangles[index + 1 :]:
            assert not (left[0] < right[2] and left[2] > right[0] and left[1] < right[3] and left[3] > right[1])
