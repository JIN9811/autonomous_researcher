import json

import pytest
from utils import cae_field_view as module


def fixture():
    return {'schema': 'cae_fields.v1', 'status': 'complete',
            'geometry': {'node_ids': [10, 20, 30, 40], 'points': [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                         'elements': [{'id': 7, 'type': 'C3D4', 'connectivity': [10, 20, 30, 40]}]},
            'frames': [{'fields': {'U': {'values': [[0, 0, 0]] * 4, 'components': ['x', 'y', 'z'], 'units': 'mm'},
                                    'S_MISES': {'values': [[0], [1], [0], [0]], 'components': ['Mises'], 'units': 'MPa'}}}]}


def test_actual_volume_section_interpolates_linear_field_and_retains_parent_element():
    assert hasattr(module, 'section'), 'volume slicing required'
    result = module.section(fixture(), axis='x', position=0.5, frame=0, field='S_MISES')
    assert result['interpolated'] is True
    assert result['owner_element_ids'] == [7]
    assert all(value == pytest.approx(0.5) for value in result['values'])
    assert all(point[0] == pytest.approx(0.5) for point in result['points'])


def test_missing_field_is_not_rendered_as_zero():
    assert hasattr(module, 'section'), 'volume slicing required'
    with pytest.raises(ValueError):
        module.section(fixture(), axis='z', position=0.5, frame=0, field='PEEQ')


def test_field_file_must_be_inside_allowed_artifact_roots(tmp_path):
    assert hasattr(module, 'load_fields'), 'restricted field loading required'
    root = tmp_path / 'artifacts'
    root.mkdir()
    outside = tmp_path / 'outside.json'
    outside.write_text(json.dumps(fixture()))
    with pytest.raises(ValueError):
        module.load_fields(outside, [root])
    inside = root / 'fixture.fields.json'
    inside.write_text(json.dumps(fixture()))
    assert module.load_fields(inside, [root])['geometry']['node_ids'] == [10, 20, 30, 40]


def test_export_view_preserves_camera_section_and_validates_geometry():
    camera = [[3, -3, 3], [0, 0, 0], [0, 0, 1]]
    grid, checked = module.export_view(fixture(), frame=0, field='S_MISES', axis='x', position=0.5, camera=camera)
    assert checked == camera
    assert grid.n_cells == 1
    assert all(point[0] == pytest.approx(0.5) for point in grid.points)
    with pytest.raises(ValueError, match='camera'):
        module.export_view(fixture(), frame=0, field='S_MISES', camera=[[0, 0, 0]] * 3)
    with pytest.raises(ValueError, match='does not intersect'):
        module.export_view(fixture(), frame=0, field='S_MISES', axis='x', position=99)


def test_packed_tensor_has_no_ambiguous_vector_magnitude():
    data = fixture()
    data['frames'][0]['fields']['S'] = {'values': [[1, 2, 3, 4, 5, 6]] * 4, 'components': ['SXX', 'SYY', 'SZZ', 'SXY', 'SYZ', 'SZX'], 'units':'MPa'}
    with pytest.raises(ValueError, match='Tensor'):
        module.volume(data, 0, 'S', -1)
    assert module.field_label(data['frames'][0]['fields']['S'], 'S', 3) == 'S · SXY [MPa]'


@pytest.mark.parametrize('bad', [[], {'schema':'cae_fields.v1','geometry':[], 'frames':[]}, {'schema':'cae_fields.v1','geometry':{}, 'frames':'bad'}])
def test_malformed_json_is_rejected_before_native_rendering(tmp_path, bad):
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        module.load_fields(path, [tmp_path])
