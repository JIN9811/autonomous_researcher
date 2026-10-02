"""Real USD field classification; never execute a scene or read external assets."""
import ast
import builtins
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tools.repository_layout import manifest as inventory


LAYER = 'runtime/sim/demo/root.usda'
REBUILD = ['colcon', '--log-base', '/tmp/atr-ros-log', 'build', '--base-paths',
           '/tmp/atr-ros-src/atr_specimen_pose_tracker', '--build-base', '/tmp/atr-ros-build',
           '--install-base', '/tmp/atr-ros-install', '--packages-select', 'atr_specimen_pose_tracker']


def fixture(tmp_path, text):
    root = tmp_path / 'repo'
    layer = root / LAYER
    layer.parent.mkdir(parents=True)
    layer.write_text('#usda 1.0\n' + text)
    return root, {'entries': {LAYER: {'destination': LAYER, 'mode': '100644'}}}


def declare(root, manifest, name, data=b'asset'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    manifest['entries'][name] = {'destination': name, 'mode': '100644'}


def audit(root, manifest):
    before = copy.deepcopy(manifest)
    data = (root / LAYER).read_bytes() if (root / LAYER).exists() else None
    result = inventory.audit_asset_references(root, manifest)
    assert manifest == before
    if data is not None:
        assert (root / LAYER).read_bytes() == data
    assert set(result) == {'owned', 'external', 'missing', 'escaping', 'generated_outputs', 'errors'}
    return result


def test_owned_fields_not_provenance_and_real_sublayer(tmp_path):
    root, manifest = fixture(tmp_path, '''(subLayers = [@./child.usda@])
def Shader "Texture" (
    doc = "Historical @/old/source/location.usda@ is not a dependency"
) {
    asset inputs:file = @./Textures/grain.png@
}
''')
    declare(root, manifest, 'runtime/sim/demo/child.usda', b'#usda 1.0\n')
    declare(root, manifest, 'runtime/sim/demo/Textures/grain.png')
    result = audit(root, manifest)
    assert not result['errors'], result['errors']
    assert {(r['reference'], r['target']) for r in result['owned']} == {
        ('./child.usda', 'runtime/sim/demo/child.usda'),
        ('./Textures/grain.png', 'runtime/sim/demo/Textures/grain.png')}
    assert not any(result[k] for k in ('external', 'missing', 'escaping', 'errors'))


@pytest.mark.parametrize('reference', ['/external/assets/grain.png', 'https://example.invalid/grain.png'])
def test_exact_external_configuration_is_preserved(tmp_path, reference):
    root, manifest = fixture(tmp_path, f'def Shader "T" {{\n asset inputs:file = @{reference}@\n}}\n')
    manifest['external_asset_references'] = [dict(layer=LAYER, reference=reference, configuration='ATR_TEST_TEXTURE_PATH')]
    result = audit(root, manifest)
    assert len(result['external']) == 1
    assert result['external'][0]['configuration'] == 'ATR_TEST_TEXTURE_PATH'
    assert result['external'][0]['reference'] == reference
    assert result['external'][0]['target'] is None
    assert not any(result[k] for k in ('owned', 'missing', 'escaping', 'errors'))


@pytest.mark.parametrize('present,declared,reason', [(False, True, 'absent'), (True, False, 'unlisted')])
def test_missing_and_unlisted_are_not_owned(tmp_path, present, declared, reason):
    root, manifest = fixture(tmp_path, 'def Shader "T" {\n asset inputs:file = @./missing.png@\n}\n')
    name = 'runtime/sim/demo/missing.png'
    if present:
        (root / name).write_bytes(b'not declared')
    if declared:
        manifest['entries'][name] = {'destination': name, 'mode': '100644'}
    result = audit(root, manifest)
    assert len(result['missing']) == 1
    assert result['missing'][0]['target'] == name
    assert result['missing'][0]['reason'] == reason
    assert not result['owned'] and not result['external'] and not result['errors']


@pytest.mark.parametrize('reference,link', [('../../../../outside.usda', False), ('./link.png', True),
                                         ('/external/not-approved.png', False), ('https://example.invalid/x', False)])
def test_escape_or_unapproved_external_is_never_read(tmp_path, reference, link):
    root, manifest = fixture(tmp_path, f'def Shader "T" {{\n asset inputs:file = @{reference}@\n}}\n')
    if link:
        name = 'runtime/sim/demo/link.png'
        (root / name).symlink_to('../../../../outside.png')
        manifest['entries'][name] = {'destination': name, 'mode': '120000'}
    result = audit(root, manifest)
    assert len(result['escaping']) == 1
    assert not result['owned'] and not result['external'] and not result['errors']


def test_reference_payload_arrays_timesamples_and_crate(tmp_path):
    from pxr import Sdf
    root, manifest = fixture(tmp_path, '''def Xform "Root" (
 prepend references = @./child.usda@</Child>
 prepend payload = @./child.usda@</Child>
) {
 asset[] files = [@./a.png@, @./b.png@]
 asset frame.timeSamples = { 1: @./a.png@, 2: @./b.png@ }
}
''')
    for name in ('a.png', 'b.png'):
        declare(root, manifest, 'runtime/sim/demo/' + name)
    declare(root, manifest, 'runtime/sim/demo/child.usda', b'#usda 1.0\ndef Xform "Child" {}\n')
    crate = 'runtime/sim/demo/crate.usdc'
    assert Sdf.Layer.FindOrOpen(str(root / LAYER)).Export(str(root / crate))
    manifest['entries'][crate] = {'destination': crate, 'mode': '100644'}
    result = audit(root, manifest)
    assert len(result['owned']) == 12
    assert {r['field'] for r in result['owned']} == {'references', 'payload', 'default', 'timeSamples'}
    assert {r['time'] for r in result['owned'] if r['field'] == 'timeSamples'} == {1.0, 2.0}
    assert not any(result[k] for k in ('external', 'missing', 'escaping', 'errors'))


def test_malformed_layer_is_an_error_not_empty_success(tmp_path):
    root, manifest = fixture(tmp_path, 'def invalid syntax here')
    assert audit(root, manifest)['errors']


@pytest.mark.parametrize('invalid', [None, {'entries': []}, {'entries': {'bad': None}},
                                     {'external_asset_references': None}, {'generated_output_rebuilds': []},
                                     {'external_asset_references': [{'layer': []}]}])
def test_invalid_metadata_reports_error(tmp_path, invalid):
    assert inventory.audit_asset_references(tmp_path, invalid)['errors']


def test_missing_usd_tooling_is_an_explicit_failed_gate(tmp_path, monkeypatch):
    root, manifest = fixture(tmp_path, 'def Xform "Root" {}\n')
    original = builtins.__import__
    def without_usd(name, *args, **kwargs):
        if name == 'pxr':
            raise ImportError('test USD reader unavailable')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_usd)
    result = audit(root, manifest)
    assert result['errors'][0]['reason'] == 'USD inspection unavailable'


def test_external_and_escaped_link_do_not_stat_external_target(tmp_path, monkeypatch):
    root, manifest = fixture(tmp_path, '''def Shader "T" {
 asset external = @/unreadable/external.png@
 asset escaped = @./link.png@
}
''')
    (root / 'runtime/sim/demo/link.png').symlink_to('/unreadable/escaped.png')
    manifest['external_asset_references'] = [dict(layer=LAYER, reference='/unreadable/external.png', configuration='EXTERNAL_TEXTURE')]
    original = Path.lstat
    def guarded(path, *args, **kwargs):
        assert not str(path).startswith('/unreadable'), 'external target was inspected'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', guarded)
    result = audit(root, manifest)
    assert len(result['external']) == len(result['escaping']) == 1
    assert not result['errors']


@pytest.mark.parametrize('missing', [None, 'owning_source', 'rebuild_command', 'rebuild_profile'])
def test_generated_prefix_accounting_never_rewrites_bytes(tmp_path, missing):
    root = tmp_path / 'repo'
    root.mkdir()
    path = root / 'old-setup.sh'
    data = b'prefix=/historical/checkout/ros/install\n'
    path.write_bytes(data)
    row = dict(destination='runtime/ros/install/setup.sh', disposition='regenerated_build_output',
               mode='100644', sha256=hashlib.sha256(data).hexdigest(),
               owning_source='runtime/ros/atr_specimen_pose_tracker', rebuild_command=REBUILD,
               rebuild_profile='staged_ros_jazzy_system_python')
    if missing:
        row.pop(missing)
    result = audit(root, {'entries': {'old-setup.sh': row}})
    assert path.read_bytes() == data
    if missing:
        assert result['errors']
    else:
        assert len(result['generated_outputs']) == 1
        assert result['generated_outputs'][0]['rebuild_command'] == REBUILD
        assert result['generated_outputs'][0]['owning_source'] == 'runtime/ros/atr_specimen_pose_tracker'
        assert not result['errors']


def test_generator_derives_owned_outputs_from_its_relocated_source(tmp_path):
    source = Path(__file__).resolve().parents[2] / 'sim/robotis_omx/tools/build_table_layout_scene.py'
    tree = ast.parse(source.read_text())
    names = {'ROOT', 'OUT', 'ROBOT_USD', 'TEXTURE_DIR', 'REDWOOD_TEXTURE'}
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                   and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id in names]
    relocated = tmp_path / 'arbitrary/runtime/sim/robotis_omx/tools/build_table_layout_scene.py'
    scope = {'Path': Path, '__file__': str(relocated)}
    # Evaluate only the five path expressions, never generator imports or execution.
    exec(compile(ast.Module(body=assignments, type_ignores=[]), '<owned-paths>', 'exec'), scope)
    expected = tmp_path / 'arbitrary/runtime/sim/robotis_omx'
    assert scope['ROOT'] == expected
    assert scope['OUT'] == expected / 'scene/omx_table_layout.usda'
    assert scope['ROBOT_USD'] == expected / 'omx/omx.usda'
    assert scope['TEXTURE_DIR'] == expected / 'scene/Textures'
    assert scope['REDWOOD_TEXTURE'] == expected / 'scene/Textures/redwood_table_grain.png'


def test_actual_generated_retirement_and_asset_manifest_are_complete():
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / 'system/maintenance/repository_layout_manifest.json').read_text())
    generated = {source for source, row in manifest['entries'].items()
                 if row['disposition'] == 'regenerated_build_output'}
    assert len(generated) == 39
    assert set(manifest['generated_output_rebuilds']) == generated
    result = inventory.audit_asset_references(root, manifest)
    assert len(result['generated_outputs']) == 39
    assert len(result['owned']) == 115
    assert not any(result[key] for key in ('external', 'missing', 'escaping', 'errors'))
    for source in generated:
        row = manifest['generated_output_rebuilds'][source]
        assert row['owning_source'] == 'runtime/ros/atr_specimen_pose_tracker'
        assert row['rebuild_command'] == REBUILD
        assert row['source_retirement']['status'] == 'removed_from_source'
        assert len(row['source_retirement']['rebuild_receipt_sha256']) == 64
        for name in (source, manifest['entries'][source]['destination']):
            assert not (root / name).exists() and not (root / name).is_symlink()
