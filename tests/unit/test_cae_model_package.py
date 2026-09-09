"""Portable native model contains the actual deck, not a synthetic surrogate."""
import hashlib
import json
import shutil


def test_model_package_can_move_without_original_paths(tmp_path):
    from utils.cae_model_package import export_model_package
    source = tmp_path/'source'; source.mkdir()
    deck = source/'specimen.inp'; deck.write_text('*NODE\n1,0,0,0\n*END STEP\n')
    mesh = source/'mesh.inp'; mesh.write_text('*NODE\n1,0,0,0\n')
    stl = source/'specimen.stl'; stl.write_text('solid example\nendsolid example\n')
    manifest = source/'preparation.json'; manifest.write_text('{"target_displacement_mm": 12}')
    original_hash = hashlib.sha256(deck.read_bytes()).hexdigest()
    result = export_model_package({'run_id':'r','specimen_id':'s','material':{'elastic_modulus_mpa':1800},
        'stl_path':str(stl), 'computation_limits':{'timeout_s':None}},
        {'inp_path':str(deck),'mesh_inp_path':str(mesh),'manifest_path':str(manifest)})
    relocated = tmp_path/'relocated'
    shutil.copytree(result['model_package_path'], relocated)
    data = json.loads((relocated/'model.json').read_text())
    assert data['validation_status']=='not_promoted'
    assert data['units']['length']=='mm'
    assert data['parameters']['material']['elastic_modulus_mpa']==1800
    assert data['files']['model.inp']['sha256']==original_hash
    for name, entry in data['files'].items():
        assert (relocated/name).is_file()
        assert hashlib.sha256((relocated/name).read_bytes()).hexdigest()==entry['sha256']
    assert str(source) not in (relocated/'model.json').read_text()
    assert 'ccx -i model' in (relocated/'README.md').read_text()


def test_model_package_rejects_nonportable_external_includes(tmp_path):
    import pytest
    from utils.cae_model_package import export_model_package
    deck=tmp_path/'a.inp'; deck.write_text('*INCLUDE, INPUT=/outside/mesh.inp\n')
    with pytest.raises(ValueError, match='INCLUDE'):
        export_model_package({}, {'inp_path':str(deck)})
