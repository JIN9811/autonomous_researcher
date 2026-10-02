"""Code-owned reference bases are explicit; metadata is never open authority."""
from dataclasses import replace
from pathlib import Path

import pytest

from utils import runtime_paths as rp


@pytest.fixture
def paths(tmp_path):
    return replace(rp.current_paths(), repository_root=tmp_path / 'repo',
                   runtime_root=tmp_path / 'repo/runtime')


def test_runtime_and_document_references_have_distinct_cwd_independent_bases(paths, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = getattr(rp, 'resolve_runtime_reference', None)
    document = getattr(rp, 'resolve_document_reference', None)
    assert callable(runtime) and callable(document), 'strict reference resolvers are required'
    assert runtime('agents/design/agent.py', paths=paths) == paths.runtime_root / 'agents/design/agent.py'
    assert document('docs/agents/design_agent.md', paths=paths) == paths.repository_root / 'docs/agents/design_agent.md'
    assert not paths.repository_root.exists(), 'reference resolution must not create files'


@pytest.mark.parametrize('resolver', ['resolve_runtime_reference', 'resolve_document_reference'])
@pytest.mark.parametrize('value', ['', '.', '../escape', 'agents/../escape', '/etc/passwd',
                                   'agents//file.py', './agents/file.py', 'agents/file.py/',
                                   r'agents\file.py', 'C:/private/file.py', 'file\x00.py'])
def test_code_reference_rejects_noncanonical_paths(paths, resolver, value):
    resolve = getattr(rp, resolver, None)
    assert callable(resolve), 'strict reference resolver is required'
    with pytest.raises(ValueError):
        resolve(value, paths=paths)


@pytest.mark.parametrize('resolver,base', [('resolve_runtime_reference', 'runtime_root'),
                                          ('resolve_document_reference', 'repository_root')])
def test_code_reference_rejects_symlink_escape(paths, tmp_path, resolver, base):
    root = getattr(paths, base)
    root.mkdir(parents=True)
    (root / 'escape').symlink_to(tmp_path)
    resolve = getattr(rp, resolver, None)
    assert callable(resolve), 'strict reference resolver is required'
    with pytest.raises(ValueError):
        resolve('escape/private.txt', paths=paths)


def test_installed_owner_reference_classification(paths):
    from importlib import import_module
    import shutil
    source = Path(__file__).resolve().parents[2]
    runtime = getattr(rp, 'resolve_runtime_reference', None)
    document = getattr(rp, 'resolve_document_reference', None)
    assert callable(runtime) and callable(document)
    for owner in ('design', 'specimen', 'vision', 'manipulation', 'equipment', 'analysis', 'bo'):
        descriptor = import_module(f'agents.{owner}.module').MODULE.describe()
        doc = document(descriptor['documentation'], paths=paths)
        assert doc.is_relative_to(paths.repository_root / 'system')
        doc.parent.mkdir(parents=True, exist_ok=True)
        document_source = rp.current_paths().repository_root / descriptor['documentation']
        shutil.copyfile(document_source, doc)
        assert doc.read_bytes() == document_source.read_bytes()
        references = [*descriptor['backend'].values(), descriptor['frontend']['descriptor']]
        references.extend(descriptor['configuration'].get(key) for key in ('source', 'plan_contract', 'profile', 'skill_flow'))
        references.extend(descriptor.get('owned_references', {}).values())
        references.extend(descriptor.get('dependencies', {}).get('shared_bridge_sources', []))
        for values in references:
            for value in values if isinstance(values, list) else [values]:
                if not isinstance(value, str) or '/' not in value:
                    continue  # Python symbols are not filesystem references.
                target = runtime(value, paths=paths)
                assert target.is_relative_to(paths.runtime_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / value, target)
                assert target.read_bytes() == (source / value).read_bytes()
        assert runtime(descriptor['configuration']['source'], paths=paths) == paths.runtime_root / f'graphs/modules/{owner}/module.yaml'
        assert descriptor['frontend']['asset_url'] == f'/module-assets/{owner}/live_report.js'


def test_all_ten_control_structures_resolve_only_runtime_relative_sources(paths):
    from importlib import import_module
    source = Path(__file__).resolve().parents[2]
    for owner in ('design', 'orchestrator', 'specimen', 'vision', 'manipulation',
                  'equipment', 'analysis', 'bo', 'knowledge', 'guardian'):
        prefix = 'agents.core' if owner in {'orchestrator', 'knowledge', 'guardian'} else 'agents'
        structure = getattr(import_module(f'{prefix}.{owner}.structure'), f'{owner}_implementation_structure')()
        assert structure['operations']
        for detail in structure['operations'].values():
            assert detail['nodes']
            for node in detail['nodes']:
                value = node['source']['path']
                assert (source / value).is_file()
                assert rp.resolve_runtime_reference(value, paths=paths) == paths.runtime_root / value
