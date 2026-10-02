"""Target filesystem and positive distribution contracts; no app import."""
from pathlib import Path
import json
import os
import hashlib
import shutil
import subprocess
import sys
import stat
import tarfile
import zipfile

import pytest

RUNTIME = Path(__file__).resolve().parents[2]


def test_distribution_uses_positive_per_file_selection():
    selection = RUNTIME / 'distribution-files.json'
    assert selection.is_file(), 'positive code/resource selection is missing'
    contract = json.loads(selection.read_text())
    assert len(contract['packages']) == 43
    assert {'objectives', 'integrations.isaac_lab_robotis_omx',
            'integrations.isaac_lab_robotis_omx.mdp',
            'integrations.isaac_lab_robotis_omx.robomimic'} <= set(contract['packages'])
    assert {p for p in contract['wheel'] if p.startswith('memory/')} == {
        'memory/__init__.py', 'memory/experiment_db.py', 'memory/failure_memory.py',
        'memory/retrieval.py', 'memory/schemas.py'}
    assert not any(p.startswith('models/') for p in contract['bound_resources'])
    for role in ('wheel', 'bound_resources', 'sdist'):
        assert len(contract[role]) == len(set(contract[role]))
        assert all(not any(c in p for c in ('*', '\\', ':')) and '..' not in Path(p).parts
                   and not p.startswith('/') for p in contract[role])
        assert not any(p.split('/')[0] in {'runs', 'artifacts', 'outputs', 'output', 'user_files',
                                          'workspace', 'logs', 'test-results'} for p in contract[role])


def test_runtime_move_targets_match_exact_phase_identities():
    outer = RUNTIME.parent
    manifest = json.loads((outer / 'system/maintenance/repository_layout_manifest.json').read_text())
    phase = manifest['runtime_phase']
    assert 'files' in phase, 'runtime final identity accounting is missing'
    assert set(phase['files']) == set(phase['moves'])
    # Later phases are explicit overlays, never refreshed earlier proof hashes.
    subsequent = {**manifest.get('task10_phase', {}).get('files', {}),
                  **manifest.get('task11_phase', {}).get('files', {})}
    for source, record in phase['files'].items():
        record = subsequent.get(phase['moves'][source], record)
        path = outer / phase['moves'][source]
        assert path.is_file() and not path.is_symlink(), source
        data = path.read_bytes()
        assert len(data) == record['size'], source
        assert hashlib.sha256(data).hexdigest() == record['sha256'], source
        assert ('100755' if path.stat().st_mode & 0o111 else '100644') == record['mode'], source
    for source, record in phase['post_move_additions'].items():
        record = subsequent.get(source, record)
        assert hashlib.sha256((outer / source).read_bytes()).hexdigest() == record['sha256'], source
    for source, record in manifest.get('task10_phase', {}).get('additions', {}).items():
        record = subsequent.get(source, record)
        assert hashlib.sha256((outer / source).read_bytes()).hexdigest() == record['sha256'], source
    for source, record in manifest.get('task11_phase', {}).get('files', {}).items():
        path = outer / source
        assert path.is_file() and not path.is_symlink(), source
        data = path.read_bytes()
        assert len(data) == record['size'], source
        assert hashlib.sha256(data).hexdigest() == record['sha256'], source
        assert ('100755' if path.stat().st_mode & 0o111 else '100644') == record['mode'], source
    assert len(phase['generated_deferrals']) == 39
    for source, record in phase['generated_deferrals'].items():
        assert record['current_location'] == source and record['handoff'] == 'Task 10'
        path = outer / source
        original = manifest['entries'][source]
        retirement = manifest.get('generated_output_rebuilds', {}).get(source, {}).get('source_retirement')
        if retirement is not None:
            assert retirement['status'] == 'removed_from_source'
            assert retirement['baseline_identity'] == {key: original[key] for key in ('mode', 'git_blob', 'sha256', 'size')}
            assert len(retirement['rebuild_receipt_sha256']) == 64
            assert not os.path.lexists(path), source
            assert not os.path.lexists(outer / original['destination']), source
            continue
        # Generated links may deliberately be dangling; certify link bytes,
        # never follow them into old build/install or external locations.
        if original['mode'] == '120000':
            assert path.is_symlink(), source
            data = os.readlink(path).encode()
        else:
            assert path.is_file() and not path.is_symlink(), source
            data = path.read_bytes()
            assert ('100755' if path.stat().st_mode & 0o111 else '100644') == original['mode'], source
        assert hashlib.sha256(data).hexdigest() == original['sha256'], source


@pytest.mark.skipif(os.environ.get('ATR_DISTRIBUTION_BUILD') != '1',
                    reason='explicit bounded archive build gate')
def test_built_archives_match_positive_manifest_and_reject_injected_files(tmp_path):
    contract = json.loads((RUNTIME / 'distribution-files.json').read_text())
    project = tmp_path / 'project'
    project.mkdir()
    for name in contract['sdist']:
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RUNTIME / name, target)
    for name in ('memory/private_payload.py', 'memory/nested/__init__.py',
                 'configs/local-secret.yaml', 'web/static/operator-token.json',
                 'runs-public-looking/secret.txt', 'app/novel_payload.py'):
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('PRIVATE_SENTINEL_NOT_FOR_DISTRIBUTION')
    result = subprocess.run([sys.executable, '-m', 'build', '--no-isolation'],
                            cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    wheel = next((project / 'dist').glob('*.whl'))
    sdist = next((project / 'dist').glob('*.tar.gz'))
    expected = {name: name for name in contract['wheel']}
    expected.update({'_autonomous_researcher_resources/' + name: name for name in contract['bound_resources']})
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(stat.S_IFMT(info.external_attr >> 16) in {0, stat.S_IFREG}
                   for info in archive.infolist())
        metadata = {'autonomous_researcher-0.1.0.dist-info/' + name for name in
                    ('METADATA', 'WHEEL', 'top_level.txt', 'RECORD', 'licenses/LICENSE')}
        assert set(names) == set(expected) | metadata
        for name, source in expected.items():
            assert archive.read(name) == (RUNTIME / source).read_bytes(), name
            mode = archive.getinfo(name).external_attr >> 16
            assert mode & 0o777 == (RUNTIME / source).stat().st_mode & 0o777, name
            assert not mode & 0o170000 == 0o120000
    with tarfile.open(sdist) as archive:
        members = [m for m in archive.getmembers() if not m.isdir()]
        names = [m.name.split('/', 1)[1] for m in members]
        assert len(names) == len(set(names))
        assert all(m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts
                   and '\\' not in m.name and ':' not in m.name for m in members)
        metadata = {'PKG-INFO', 'setup.cfg'} | {'autonomous_researcher.egg-info/' + name for name in
                    ('PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'requires.txt', 'top_level.txt')}
        assert set(names) == set(contract['sdist']) | metadata
        for member, name in zip(members, names):
            if name in contract['sdist']:
                assert archive.extractfile(member).read() == (RUNTIME / name).read_bytes(), name
                assert member.mode == (RUNTIME / name).stat().st_mode & 0o777, name


def test_executable_project_is_contained_under_runtime():
    # This test is intentionally RED in the pre-move disposable checkout.
    here = Path(__file__).resolve()
    root = here.parents[3] if here.parents[2].name == 'runtime' else here.parents[2]
    assert sorted(p.name for p in root.iterdir() if p.is_file() and not p.name.startswith('.')) == ['README.md']
    assert (root / 'runtime/pyproject.toml').is_file()
    assert (root / 'runtime/LICENSE').is_file()
    assert (root / 'runtime/README.md').is_file()
    assert not (root / 'runtime/__init__.py').exists()
