"""Physical wall/cell design inputs and derived Gyroid density metadata."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_only_wall_and_cell_control_gyroid_level_not_legacy_overrides():
    from mcp_tools.tpms_geometry import tpms_thickness_level
    levels = []
    for wall in [0.8, 1.2, 1.6]:
        level = tpms_thickness_level(wall_thickness_mm=wall, cell_size_mm=5)
        for density, explicit in [(0.15, 0.1), (0.4, 0.317), (0.8, 0.8)]:
            assert tpms_thickness_level(wall_thickness_mm=wall, tpms_thickness=explicit,
                                       cell_size_mm=5, relative_density=density) == level
        levels.append(level)
    assert levels[0] < levels[1] < levels[2]

from mcp_tools.tpms_geometry import write_smooth_gyroid_stl


def test_decimal_cell_pitch_is_preserved_and_center_cropped(tmp_path):
    import trimesh
    from mcp_tools.tpms_geometry import _cell_counts, _gyroid_value

    cell = 7.13789
    counts = _cell_counts([30, 30, 30], cell, 1)
    assert counts == (5, 5, 5)
    kwargs = dict(size=[30, 30, 30], cell_counts_xyz=counts,
                  orientation_rad=0, cell_size_mm=cell)
    assert _gyroid_value(12, 13, 14, **kwargs) == pytest.approx(_gyroid_value(12 + cell, 13, 14, **kwargs))
    path = tmp_path / "crop.stl"
    report = write_smooth_gyroid_stl(stl_path=path, name="crop", specimen_size_mm=[30]*3,
        wall_thickness_mm=1.2, cell_size_mm=cell, relative_density=.3, resolution=48)
    assert report["generation_envelope_mm"] == pytest.approx([5 * cell]*3)
    assert report["cell_size_requested_mm"] == cell
    mesh = trimesh.load_mesh(path)
    assert mesh.extents == pytest.approx([30]*3, abs=1e-5)
    assert mesh.bounds.mean(axis=0) == pytest.approx([0]*3, abs=1e-5)
    assert mesh.is_watertight


def test_small_cell_wall_target_returns_whole_specimen(tmp_path):
    import trimesh
    path = tmp_path / "thin.stl"
    report = write_smooth_gyroid_stl(stl_path=path, name="thin", specimen_size_mm=[30]*3,
        wall_thickness_mm=1.2, cell_size_mm=5, relative_density=.15, resolution=72)
    assert report["target_wall_thickness_mm"] == 1.2
    mesh = trimesh.load_mesh(path)
    assert mesh.extents == pytest.approx([30]*3, abs=1e-5)
    assert mesh.is_watertight


@pytest.mark.parametrize("target_wall", [0.8, 1.2, 1.6])
def test_smooth_gyroid_reports_target_wall_and_derived_density(
    tmp_path: Path,
    target_wall: float,
) -> None:
    metadata = write_smooth_gyroid_stl(
        stl_path=tmp_path / f"gyroid-{target_wall:.2f}.stl",
        name="density-contract",
        specimen_size_mm=[30.0, 30.0, 30.0],
        wall_thickness_mm=target_wall,
        cell_size_mm=6.0,
        relative_density=0.15,  # Obsolete independent input must not control geometry.
        anisotropy_ratio=1.0,
        orientation_deg=0.0,
        defect_seed=1,
        defect_ratio=0.0,
        skin_thickness_mm=0.8,
        top_cap_enabled=False,
        bottom_cap_enabled=True,
        resolution=48,
    )

    assert metadata is not None
    from mcp_tools.tpms_geometry import relative_density_for_wall
    estimated = relative_density_for_wall(target_wall, 6.0)
    assert metadata["target_wall_thickness_mm"] == target_wall
    assert metadata["gyroid_parameterization"] == "wall_cell_v1"
    assert metadata["tpms_thickness_source"] == "wall_thickness_mm_normal_calibration"
    assert metadata["realized_relative_density_without_caps"] == pytest.approx(estimated, abs=0.02)
    assert metadata["relative_density_absolute_error"] <= 0.02
    assert metadata["solid_fraction"] >= metadata["realized_relative_density_without_caps"]
