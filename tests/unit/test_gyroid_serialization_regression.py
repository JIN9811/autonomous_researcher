"""Generated gyroid topology must survive crop and binary STL serialization."""
import pytest

from mcp_tools.mesh_quality import inspect_stl
from mcp_tools.tpms_geometry import write_smooth_gyroid_stl
from mcp_tools.wall_thickness import inspect_wall_thickness


def test_six_mm_cell_nine_tenths_wall_survives_high_resolution_export(tmp_path):
    path = tmp_path / 'gyroid.stl'
    result = write_smooth_gyroid_stl(
        stl_path=path, name='crop-serialization-regression', specimen_size_mm=[30]*3,
        cell_size_mm=6.0, wall_thickness_mm=0.9, resolution=160,
    )
    report = inspect_stl(path, [30]*3)
    assert report['ok'], report
    assert report['boundary_edges'] == 0
    assert report['non_manifold_edges'] == 0
    assert report['bbox'] == pytest.approx([30]*3, abs=1e-5)
    assert result['cell_size_requested_mm'] == 6.0
    assert result['target_wall_thickness_mm'] == 0.9
    assert result['tpms_resolution'] == [160]*3
    assert inspect_wall_thickness(path, minimum_mm=0.4, max_samples=4096)['status'] == 'pass'


@pytest.mark.parametrize('cell,wall,resolution', [
    # Exercise both requested resolutions. Adaptive sampling raises a 0.5 mm
    # wall to 181 and a 0.9 mm wall requested at 72 to 101 grid points per axis.
    (6.0, 0.5, 72), (6.0, 0.9, 72), (10.0, 0.5, 72), (10.0, 0.9, 72),
    (6.0, 0.5, 160), (10.0, 0.5, 160), (10.0, 0.9, 160),
])
def test_design_space_corners_keep_closed_geometry_and_minimum_wall(tmp_path, cell, wall, resolution):
    path = tmp_path / 'corner.stl'
    result = write_smooth_gyroid_stl(
        stl_path=path, name='design-space-corner', specimen_size_mm=[30]*3,
        cell_size_mm=cell, wall_thickness_mm=wall, resolution=resolution,
    )
    report = inspect_stl(path, [30]*3)
    assert report['ok'], report
    assert report['bbox'] == pytest.approx([30]*3, abs=1e-5)
    assert result['cell_size_requested_mm'] == cell
    assert result['target_wall_thickness_mm'] == wall
    thickness = inspect_wall_thickness(path, minimum_mm=0.4, max_samples=4096)
    assert thickness['status'] == 'pass', thickness
