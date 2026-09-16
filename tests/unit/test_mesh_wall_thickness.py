import numpy as np
import pytest
import trimesh

from mcp_tools.wall_thickness import inspect_wall_thickness
from mcp_tools.mock_tools import _check_manufacturability


@pytest.mark.parametrize("thickness,expected", [(0.25, "fail"), (0.65, "pass")])
def test_actual_shell_wall_not_nominal_parameter(tmp_path, thickness, expected):
    outer = trimesh.creation.icosphere(subdivisions=2, radius=5)
    inner = trimesh.creation.icosphere(subdivisions=2, radius=5-thickness)
    inner.invert()
    mesh = trimesh.util.concatenate([outer, inner])
    path = tmp_path / "shell.stl"
    mesh.export(path)
    report = inspect_wall_thickness(path)
    assert report["status"] == expected
    assert report["sample_count"] > 0
    result = _check_manufacturability({"stl_path": str(path), "constraints": {
        "geometry_type": "gyroid", "wall_thickness_mm": 1.2,
        "cell_size_mm": 5, "relative_density": 0.3}})
    assert result["ok"] is (expected == "pass")
    assert result["wall_thickness_verification"]["stl_sha256"] == report["stl_sha256"]


def test_missing_mesh_cannot_pass_using_nominal_wall():
    result = _check_manufacturability({"constraints": {
        "geometry_type": "gyroid", "wall_thickness_mm": 10}})
    assert result["ok"] is False
    assert result["wall_thickness_verification"]["status"] == "unverified"
