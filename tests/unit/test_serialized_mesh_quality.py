import numpy as np
import pytest
import trimesh

from mcp_tools.mesh_quality import finalize_generated_stl, inspect_stl
from mcp_tools.mock_tools import _check_mesh_quality, _generate_geometry_stl, _check_manufacturability
from utils import compute_pool


def test_remove_only_degenerate_and_duplicate_faces(tmp_path):
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    faces = np.vstack([mesh.faces, mesh.faces[:1], [[0, 0, 1]]])
    path = tmp_path / 'defective.stl'
    trimesh.Trimesh(vertices=mesh.vertices, faces=faces, process=False).export(path)
    assert not _check_mesh_quality({'stl_path': str(path)})['ok']
    result = finalize_generated_stl(path, [10]*3)
    assert result['removed_degenerate_faces'] == 1
    assert result['removed_duplicate_faces'] == 1
    assert result['final_validation']['ok']
    assert result['final_validation']['volume_mm3'] == pytest.approx(1000)
    assert result['final_validation']['self_intersections'] is None
    before = path.read_bytes()
    assert finalize_generated_stl(path, [10]*3)['removed_degenerate_faces'] == 0
    assert path.read_bytes() == before


@pytest.mark.parametrize('defect', ['hole', 'inverted', 'disconnected', 'bounds', 'corrupt'])
def test_real_quality_rejects_unrepaired_defects(tmp_path, defect):
    path = tmp_path / 'invalid.stl'
    mesh = trimesh.creation.box(extents=[10]*3)
    expected = [10]*3
    if defect == 'hole': mesh.update_faces(np.arange(len(mesh.faces)-1))
    if defect == 'inverted': mesh.invert()
    if defect == 'disconnected':
        other = mesh.copy()
        other.apply_translation([20,0,0])
        mesh = trimesh.util.concatenate([mesh,other])
        expected = [30,10,10]
    if defect == 'bounds': expected = [30]*3
    mesh.export(path)
    if defect == 'corrupt': path.write_text('not a mesh')
    assert not _check_mesh_quality({'stl_path':str(path),'expected_bounding_box_mm':expected})['ok']
    if defect != 'corrupt':
        original = path.read_bytes()
        with pytest.raises(ValueError): finalize_generated_stl(path, expected)
        assert path.read_bytes() == original


def test_cycle8_serialized_regression_direct_and_worker(tmp_path):
    payload = {'run_id':'isolated-regression','specimen_id':'cycle8-regression','geometry_type':'gyroid',
        'specimen_size_mm':[30]*3,'wall_thickness_mm':0.858487698594413,
        'cell_size_mm':7.184657338151279,'relative_density':0.404,'defect_seed':50,
        'top_cap_enabled':False,'bottom_cap_enabled':False,'skin_thickness_mm':0,'tpms_resolution':72,
        'output_dir':str(tmp_path/'direct')}
    result = _generate_geometry_stl(payload)
    path = result['stl_path']
    report = result['geometry_report']
    assert report['serialized_mesh_cleanup']['final_validation']['ok']
    assert report['cell_size_requested_mm'] == payload['cell_size_mm']
    assert report['target_wall_thickness_mm'] == payload['wall_thickness_mm']
    assert inspect_stl(path,[30]*3)['degenerate_faces'] == 0
    check = {'stl_path':path,'constraints':{'geometry_type':'gyroid','cell_size_mm':payload['cell_size_mm'],
        'wall_thickness_mm':payload['wall_thickness_mm'],'min_wall_thickness_mm':0.4}}
    direct = _check_manufacturability(check)
    assert direct['ok']
    assert direct['wall_thickness_verification']['minimum_sampled_mm'] >= .4
    digest = report['stl_sha256']
    compute_pool.configure_compute_pool(3)
    try:
        worker = _generate_geometry_stl({**payload,'output_dir':str(tmp_path/'worker')})
        assert worker['geometry_report']['stl_sha256'] == digest
        assert _check_mesh_quality({'stl_path':worker['stl_path'],'expected_bounding_box_mm':[30]*3})['ok']
        check['stl_path'] = worker['stl_path']
        assert _check_manufacturability(check) == direct
    finally:
        compute_pool.close_compute_pool()
