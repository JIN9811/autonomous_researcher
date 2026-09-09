"""Oversized FRD history retains one explicitly selected complete field frame."""
import hashlib
import json
from pathlib import Path

from device_bridges.calculix_bridge import CalculiXBridge, CalculiXBridgeConfig
import device_bridges.calculix_bridge as native
from test_calculix_fields import TETRA_INP, TETRA_FRD


def field_history(tmp_path, *, truncated=False):
    prefix, first = TETRA_FRD.split('    1PSTEP', 1)
    blocks = '    1PSTEP' + first
    # Fixture's first DISP-only .2 frame is deliberately incomplete.
    complete = blocks[blocks.index('    1PSTEP', 1):].replace(' 9999\n', '')
    second = complete.replace('5.00000E-01', '8.00000E-01')
    third = complete.replace('5.00000E-01', '9.00000E-01')
    if truncated:
        third = third.rsplit(' -3', 1)[0]
    source = tmp_path / 'history.frd'
    source.write_text(prefix + complete + second + third + ('' if truncated else ' 9999\n'))
    inp = tmp_path / 'history.inp'
    inp.write_text(TETRA_INP)
    return inp, source


def test_oversized_history_yields_bounded_last_complete_frame_and_source_identity(tmp_path, monkeypatch):
    inp, source = field_history(tmp_path)
    monkeypatch.setattr(native, 'MAX_FIELD_FILE_BYTES', 2500, raising=False)
    bridge = CalculiXBridge(CalculiXBridgeConfig(artifact_dir=tmp_path))
    result = bridge.postprocess({'inp_path': str(inp), 'frd_path': str(source)})
    assert result['field_status'] == 'complete'
    frames = result['field_manifest']['frames']
    assert len(frames) == 1
    assert frames[0]['value'] == 0.9
    selection = result['field_selection']
    assert selection['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert selection['source'] == str(source)
    assert selection['complete_frame_count'] == 3
    assert selection['full_history'] is False
    assert Path(selection['selected_frd_path']).stat().st_size <= 2500
    manifest = json.loads(Path(result['field_asset_path']).read_text())
    assert manifest['field_selection'] == selection
    assert manifest['frames'][0]['fields']['S']['values'][0] == [100, 0, 0, 0, 0, 0]


def test_incomplete_final_stress_block_falls_back_to_last_closed_pair(tmp_path, monkeypatch):
    inp, source = field_history(tmp_path, truncated=True)
    monkeypatch.setattr(native, 'MAX_FIELD_FILE_BYTES', 2500, raising=False)
    result = CalculiXBridge(CalculiXBridgeConfig(artifact_dir=tmp_path)).postprocess(
        {'inp_path': str(inp), 'frd_path': str(source)})
    assert result['field_status'] == 'complete'
    assert result['field_manifest']['frames'][0]['value'] == 0.8
    assert result['field_selection']['complete_frame_count'] == 2


def test_single_frame_over_budget_is_explicit_failure_not_unbounded_read(tmp_path, monkeypatch):
    inp, source = field_history(tmp_path)
    monkeypatch.setattr(native, 'MAX_FIELD_FILE_BYTES', 128, raising=False)
    result = CalculiXBridge(CalculiXBridgeConfig(artifact_dir=tmp_path)).postprocess(
        {'inp_path': str(inp), 'frd_path': str(source)})
    assert result['field_status'] == 'failed'
    assert result['field_failure_code'] == 'CALCULIX_FIELD_BUDGET_EXCEEDED'
    assert result['frd_path'] == str(source)
    assert result['field_asset_path'] == ''
