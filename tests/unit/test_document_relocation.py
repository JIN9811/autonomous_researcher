"""Guarded moves use reviewed Git objects, never a regenerated baseline."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from tools.repository_layout import move_files
from tools.repository_layout import checks
from tools.repository_layout.manifest import build_manifest


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


def put(root, path, content, mode=0o644):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    target.chmod(mode)
    return target


def commit(root, message):
    git(root, 'add', '--all')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-qm', message)
    return git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / 'repository'
    root.mkdir()
    git(root, 'init', '-q')
    put(root, 'README.md', b'# User entry\n')
    put(root, 'docs/tutorials/tutorial.md', b'# Tutorial\n')
    put(root, 'docs/agents/owner.md', b'# Owner\n\nFrozen execution excerpt.\n')
    put(root, 'docs/agents/assets/figure.svg', b'<svg>owner figure</svg>')
    put(root, 'docs/tutorials/assets/figure.svg', b'<svg>tutorial figure</svg>')
    put(root, 'docs/project/Project_guide.txt', b'Exact guide bytes\n')
    put(root, 'docs/knowledge/publication_allowlist.json', b'{"revision": 1}\n')
    put(root, 'references/example/tool.sh', b'#!/bin/sh\nexit 0\n', 0o755)
    put(root, 'scripts/example.py', b'print("runtime source stays")\n')
    put(root, 'LICENSE', b'Unchanged legal bytes\n')
    baseline = commit(root, 'baseline')
    manifest = build_manifest(root, baseline)
    # This approved later change must never be replaced with frozen bytes.
    put(root, 'docs/knowledge/publication_allowlist.json', b'{"revision": 2}\n')
    manifest['move_revision'] = commit(root, 'reviewed metadata change')
    return root, manifest


def apply(root, manifest, **kwargs):
    # Missing production API is an assertion failure in the initial RED suite.
    assert callable(getattr(move_files, 'apply_moves', None)), 'guarded move API is absent'
    return move_files.apply_moves(root, manifest, phase='documents', **kwargs)


def test_dry_run_changes_nothing_and_reports_exact_document_targets(repository):
    root, manifest = repository
    before = git(root, 'status', '--porcelain')
    result = apply(root, manifest)
    assert result['dry_run'] is True
    assert result['changed_paths'] == []
    assert [(x['source'], x['destination']) for x in result['moves']] == [
        ('LICENSE', 'runtime/LICENSE'),
        ('docs/agents/assets/figure.svg', 'system/agents/assets/figure.svg'),
        ('docs/agents/owner.md', 'system/agents/owner.md'),
        ('docs/knowledge/publication_allowlist.json', 'system/knowledge/publication_allowlist.json'),
        ('docs/project/Project_guide.txt', 'system/project/Project_guide.txt'),
        ('references/example/tool.sh', 'system/references/example/tool.sh'),
    ]
    assert not (root / 'system').exists()
    assert git(root, 'status', '--porcelain') == before


def test_moves_preserve_modes_bytes_and_distinct_baseline_reviewed_identities(repository):
    root, manifest = repository
    frozen = deepcopy(manifest)
    index_before = git(root, 'ls-files', '--stage')
    result = apply(root, manifest, dry_run=False)
    assert manifest == frozen
    assert git(root, 'ls-files', '--stage') == index_before  # Caller owns staging.
    assert result['changed_paths'] == sorted([
        path for row in result['moves'] for path in (row['source'], row['destination'])])
    assert len(result['moves']) == 6
    for row in result['moves']:
        assert not os.path.lexists(root / row['source'])
        assert (root / row['destination']).is_file()
        assert row['pre_move']['revision'] == manifest['move_revision']
        assert row['post_move'] == {k: row['pre_move'][k] for k in ('mode', 'git_blob', 'sha256', 'size')}
    assert (root / 'system/project/Project_guide.txt').read_bytes() == b'Exact guide bytes\n'
    assert (root / 'system/agents/owner.md').read_bytes() == b'# Owner\n\nFrozen execution excerpt.\n'
    assert (root / 'system/agents/assets/figure.svg').read_bytes() == b'<svg>owner figure</svg>'
    assert (root / 'docs/tutorials/assets/figure.svg').read_bytes() == b'<svg>tutorial figure</svg>'
    assert (root / 'scripts/example.py').is_file()
    assert (root / 'system/references/example/tool.sh').stat().st_mode & 0o777 == 0o755
    row = next(x for x in result['moves'] if x['source'].endswith('publication_allowlist.json'))
    assert row['baseline']['sha256'] != row['pre_move']['sha256']
    assert (root / row['destination']).read_bytes() == b'{"revision": 2}\n'


@pytest.mark.parametrize('damage', ['bytes', 'mode', 'staged', 'missing', 'untracked-target',
                                   'tracked-target', 'source-parent-link', 'target-parent-link'])
def test_preflight_rejects_damage_before_moving_any_file(repository, tmp_path, damage):
    root, manifest = repository
    source = root / 'docs/agents/owner.md'
    if damage == 'bytes':
        source.write_bytes(b'unreviewed change')
    elif damage == 'mode':
        source.chmod(0o755)
    elif damage == 'staged':
        source.write_bytes(b'staged unreviewed change')
        git(root, 'add', 'docs/agents/owner.md')
        source.write_bytes(b'# Owner\n\nFrozen execution excerpt.\n')
    elif damage == 'missing':
        source.unlink()
    elif damage in {'untracked-target', 'tracked-target'}:
        put(root, 'system/agents/owner.md', b'collision')
        if damage == 'tracked-target':
            manifest['move_revision'] = commit(root, 'target collision')
    elif damage == 'source-parent-link':
        (root / 'docs/agents').rename(root / 'displaced')
        (root / 'docs/agents').symlink_to('../displaced')
    else:
        (root / 'system').symlink_to(tmp_path)
    with pytest.raises(ValueError):
        apply(root, manifest, dry_run=False)
    assert (root / 'LICENSE').read_bytes() == b'Unchanged legal bytes\n'
    assert not (root / 'runtime/LICENSE').exists()


@pytest.mark.parametrize('damage', ['source-traversal', 'destination-traversal', 'collision',
                                   'baseline-hash', 'unreviewed-revision', 'missing-revision'])
def test_invalid_manifest_cannot_authorize_moves(repository, damage):
    root, manifest = repository
    row = manifest['entries']['docs/agents/owner.md']
    if damage == 'source-traversal':
        manifest['entries']['../outside'] = manifest['entries'].pop('docs/agents/owner.md')
        manifest['tracked_paths'] = sorted(manifest['entries'])
    elif damage == 'destination-traversal':
        row['destination'] = 'system/../outside'
    elif damage == 'collision':
        row['destination'] = 'system/project/Project_guide.txt'
    elif damage == 'baseline-hash':
        row['sha256'] = '0' * 64
    elif damage == 'unreviewed-revision':
        manifest['move_revision'] = manifest['baseline_commit']
    else:
        manifest.pop('move_revision')
    with pytest.raises(ValueError):
        apply(root, manifest, dry_run=False)
    assert (root / 'LICENSE').is_file()


def test_added_document_requires_separate_exact_inventory(repository):
    root, manifest = repository
    put(root, 'docs/maintenance/added.md', b'# Reviewed addition\n')
    manifest['move_revision'] = commit(root, 'reviewed added document')
    with pytest.raises(ValueError, match='addition'):
        apply(root, manifest)
    manifest['additions'] = {'docs/maintenance/added.md': {
        'destination': 'system/maintenance/added.md', 'disposition': 'move',
        'reason': 'Exact reviewed post-baseline documentation addition',
        'mode': '100644', 'git_blob': git(root, 'rev-parse', 'HEAD:docs/maintenance/added.md'),
        'sha256': hashlib.sha256(b'# Reviewed addition\n').hexdigest(), 'size': 20,
        'approved_content_changes': [],
    }}
    result = apply(root, manifest, dry_run=False)
    row = next(x for x in result['moves'] if x['source'] == 'docs/maintenance/added.md')
    assert row['baseline'] is None
    assert row['addition_reason'] == 'Exact reviewed post-baseline documentation addition'
    assert (root / row['destination']).read_bytes() == b'# Reviewed addition\n'


def test_escaping_symlink_is_rejected_but_internal_link_bytes_are_preserved(repository):
    root, manifest = repository
    (root / 'docs/agents/guide-link').symlink_to('../../project/Project_guide.txt')
    baseline = commit(root, 'fixture link')
    manifest = build_manifest(root, baseline)
    manifest['move_revision'] = baseline
    # This link stays within the repository both before and after moving.
    result = apply(root, manifest, dry_run=False)
    link = root / 'system/agents/guide-link'
    assert link.is_symlink()
    assert os.readlink(link) == '../../project/Project_guide.txt'
    row = next(x for x in result['moves'] if x['source'].endswith('guide-link'))
    assert row['post_move']['mode'] == '120000'


def test_symlink_destination_escape_is_rejected_before_any_move(repository):
    root, manifest = repository
    (root / 'docs/agents/guide-link').symlink_to('../../../outside')
    baseline = commit(root, 'fixture escaping link')
    manifest = build_manifest(root, baseline)
    manifest['move_revision'] = baseline
    with pytest.raises(ValueError, match='symlink'):
        apply(root, manifest, dry_run=False)
    assert (root / 'LICENSE').is_file()


def test_unknown_phase_never_moves_runtime_source(repository):
    root, manifest = repository
    assert callable(getattr(move_files, 'apply_moves', None)), 'guarded move API is absent'
    with pytest.raises(ValueError, match='phase'):
        move_files.apply_moves(root, manifest, phase='everything', dry_run=False)
    assert (root / 'scripts/example.py').is_file()


def test_registry_pdf_deferrals_are_explicit_verified_and_never_moved(repository):
    root, manifest = repository
    names = ('Indicator Manual.pdf', 'Software Manual.pdf')
    for name in names:
        put(root, 'docs/knowledge/manuals/sources/' + name, b'synthetic PDF bytes')
    put(root, 'docs/knowledge/manuals/registry.yaml', b'schema: manual_source_registry.v1\n')
    baseline = commit(root, 'fixture tracked raw source bundle')
    manifest = build_manifest(root, baseline)
    manifest['move_revision'] = baseline
    with pytest.raises(ValueError, match='deferral'):
        apply(root, manifest)
    manifest['phase_deferrals'] = {}
    for name in names:
        path = 'docs/knowledge/manuals/sources/' + name
        entry = manifest['entries'][path]
        manifest['phase_deferrals'][path] = {
            'phase': 'documents', 'reason': 'Private raw source belongs to the later state phase',
            'current_location': path, 'mode': entry['mode'], 'sha256': entry['sha256'],
            'handoff': 'Separately approved offline copy/untracking decision; no source-phase publication',
        }
    result = apply(root, manifest, dry_run=False)
    assert len(result['deferred']) == 2
    assert (root / 'system/knowledge/manuals/registry.yaml').is_file()
    for name in names:
        path = 'docs/knowledge/manuals/sources/' + name
        assert (root / path).read_bytes() == b'synthetic PDF bytes'
        assert not (root / manifest['entries'][path]['destination']).exists()
        reference = os.path.relpath(root / path, root / 'system/knowledge/manuals')
        assert reference == '../../../docs/knowledge/manuals/sources/' + name
        assert (root / 'system/knowledge/manuals' / reference).resolve() == root / path


def audit(root, manifest):
    assert callable(getattr(checks, 'audit_document_references', None)), 'full reference audit is absent'
    return checks.audit_document_references(root, manifest)


def audit_fixture(root):
    files = {
        'docs/user.md': b'''---
related_docs: [system/owner.md]
---
# User
[owner](../system/owner.md#owner)
![encoded](assets/same%20name.svg)
[reference][owner]
[owner]: ../system/owner.md#duplicate-1
<a href="../system/page.html#explicit">html</a>
[self](#user)
```md
[fake](absent.md)
```
    [indented example](missing.md)
`[inline example](absent.md)`
''',
        'system/owner.md': b'# Owner\n## Duplicate\n## Duplicate\n![figure](assets/same%20name.svg)\n',
        'docs/assets/same name.svg': b'<svg>user image</svg>',
        'system/assets/same name.svg': b'<svg>owner image</svg>',
        'system/page.html': b'<h1 id="explicit">HTML</h1><a href="owner.md#owner">owner</a><img src="assets/same%20name.svg">',
        'system/reference.rst': b'''Reference
=========
`Owner <owner.md#owner>`_
.. image:: assets/same%20name.svg
.. include:: owner.md
.. automodule:: nonexistent.python.name
''',
    }
    for path, content in files.items():
        put(root, path, content)
    return {'entries': {path: {'destination': path, 'disposition': 'keep'} for path in files}}


def test_all_tracked_formats_assets_metadata_and_fragments_audit_cleanly(tmp_path):
    manifest = audit_fixture(tmp_path)
    result = audit(tmp_path, manifest)
    assert result['checked'] == 12
    for key in ('missing_files', 'missing_anchors', 'escaping_references', 'metadata_errors'):
        assert result[key] == []


def test_audit_separates_missing_files_fragments_escapes_and_metadata(tmp_path):
    manifest = audit_fixture(tmp_path)
    with (tmp_path / 'docs/user.md').open('ab') as output:
        output.write(b'\n[missing](absent.md)\n[anchor](../system/owner.md#absent)\n[escape](%2e%2e/%2e%2e/private.md)\n[external](https://example.invalid/page)\n')
    (tmp_path / 'system/owner.md').write_text('---\nsource_of_truth: nonexistent.py\n---\n# Owner\n')
    result = audit(tmp_path, manifest)
    assert any('absent.md' in str(x) for x in result['missing_files'])
    assert any('#absent' in str(x) for x in result['missing_anchors'])
    assert len(result['escaping_references']) == 1
    assert any('nonexistent.py' in str(x) for x in result['metadata_errors'])
    assert result['external_urls'] == 1


def test_audit_uses_exact_phase_destinations_and_declared_registry_base(tmp_path):
    put(tmp_path, 'system/knowledge/manuals/registry.yaml', b'''schema: manual_source_registry.v1
sources:
  - source_id: unchanged
    path: ../../../docs/knowledge/manuals/sources/Indicator Manual.pdf
''')
    put(tmp_path, 'docs/knowledge/manuals/sources/Indicator Manual.pdf', b'fixture PDF')
    manifest = {'entries': {
        'docs/knowledge/manuals/registry.yaml': {'destination': 'system/knowledge/manuals/registry.yaml', 'disposition': 'move'},
        'docs/knowledge/manuals/sources/Indicator Manual.pdf': {'destination': 'system/knowledge/manuals/sources/Indicator Manual.pdf', 'disposition': 'move'},
    }, 'phase_deferrals': {'docs/knowledge/manuals/sources/Indicator Manual.pdf': {
        'current_location': 'docs/knowledge/manuals/sources/Indicator Manual.pdf', 'phase': 'documents'}}}
    result = audit(tmp_path, manifest)
    assert result['checked'] == 1
    assert all(result[key] == [] for key in ('missing_files', 'missing_anchors', 'escaping_references', 'metadata_errors'))


@pytest.mark.parametrize('representation', ['pointer', 'smudged', 'mismatch', 'missing-attribute'])
def test_lfs_preserves_verified_representation_without_running_lfs(repository, representation):
    root, _ = repository
    payload = b'synthetic video bytes, no network or real media process'
    digest = hashlib.sha256(payload).hexdigest()
    pointer = f'version https://git-lfs.github.com/spec/v1\noid sha256:{digest}\nsize {len(payload)}\n'.encode()
    put(root, 'references/movie.mp4', pointer)
    if representation != 'missing-attribute':
        put(root, '.gitattributes', b'*.mp4 filter=lfs diff=lfs merge=lfs -text\n')
    baseline = commit(root, 'fixture pointer')
    manifest = build_manifest(root, baseline)
    manifest['move_revision'] = baseline
    if representation != 'pointer':
        put(root, 'references/movie.mp4', payload if representation != 'mismatch' else b'wrong bytes')
    if representation in {'mismatch', 'missing-attribute'}:
        with pytest.raises(ValueError):
            apply(root, manifest, dry_run=False)
        assert (root / 'LICENSE').is_file()
        return
    result = apply(root, manifest, dry_run=False)
    row = next(item for item in result['moves'] if item['source'] == 'references/movie.mp4')
    assert row['representation'] == 'lfs-' + representation
    assert row['pre_move']['size'] == len(pointer)
    assert row['lfs_object'] == {'sha256': digest, 'size': len(payload)}
    assert row['working_before'] == row['working_after']
    assert (root / 'system/references/movie.mp4').read_bytes() == (pointer if representation == 'pointer' else payload)


def test_reference_rewrite_preserves_guide_excerpt_review_values_and_runtime_paths():
    text = '''---
{"topic_id":"owner", "source_refs":["docs/agents/owner.md"], "source_revision":{"docs/agents/owner.md":"unchanged-digest"}, "verified_at":"2026-01-01"}
---
# Owner
[reference](../../agents/owner.md#owner)
[runtime](../../../scripts/tool.py?mode=reference#entry)
## Runtime decision reference
Frozen decision bytes. No edit.
'''
    mapping = {'docs/knowledge/wiki/owner.md': 'system/knowledge/wiki/owner.md',
               'docs/agents/owner.md': 'system/agents/owner.md', 'scripts/tool.py': 'scripts/tool.py'}
    assert callable(getattr(move_files, 'rewrite_document_references', None)), 'reference rewrite API is absent'
    changed, edits = move_files.rewrite_document_references(text, 'docs/knowledge/wiki/owner.md',
                                                           'system/knowledge/wiki/owner.md', mapping)
    assert '"source_refs":["system/agents/owner.md"]' in changed
    assert '"source_revision":{"system/agents/owner.md":"unchanged-digest"}' in changed
    assert '"verified_at":"2026-01-01"' in changed
    assert changed.split('## Runtime decision reference')[1] == text.split('## Runtime decision reference')[1]
    assert '[runtime](../../../scripts/tool.py?mode=reference#entry)' in changed
    assert len(edits) == 2  # Owner relative navigation remains the same.


def test_allowlist_rewrite_preserves_corpus_slash_and_approval_values():
    text = '{"approved_assets":{"docs/agents/owner.md":{"review":"same","sha256":"same"},"docs/paper/evidence/absent.md":{"review":"historic","sha256":"historic"}},"approved_corpora":["docs/knowledge/wiki/"]}'
    mapping = {'docs/agents/owner.md': 'system/agents/owner.md',
               'docs/knowledge/wiki/one.md': 'system/knowledge/wiki/one.md'}
    result, _ = move_files.rewrite_document_references(text, 'docs/knowledge/publication_allowlist.json',
                                                      'system/knowledge/publication_allowlist.json', mapping)
    assert '"approved_corpora":["system/knowledge/wiki/"]' in result
    assert '"system/agents/owner.md":{"review":"same","sha256":"same"}' in result
    assert '"docs/paper/evidence/absent.md":{"review":"historic","sha256":"historic"}' in result


def test_explicit_historical_document_is_accounted_not_a_current_link_pass(tmp_path):
    content = b'# Evidence\n[old](../agents/owner.md#owner)\n'
    put(tmp_path, 'system/evidence/report.md', content)
    put(tmp_path, 'system/agents/owner.md', b'# Owner\n')
    manifest = {'move_revision': 'a' * 40, 'entries': {
        'docs/evidence/report.md': {'destination': 'system/evidence/report.md', 'disposition': 'move'},
        'docs/agents/owner.md': {'destination': 'system/agents/owner.md', 'disposition': 'move'},
    }, 'historical_documents': {'docs/evidence/report.md': {
        'original_path': 'docs/evidence/report.md', 'revision': 'a' * 40,
        'sha256': hashlib.sha256(content).hexdigest(),
        'reason': 'Approved immutable evidence bytes',
        'references': [{'reference': '../agents/owner.md#owner', 'base': 'document',
                        'original_target': 'docs/agents/owner.md', 'original_resolution': 'file',
                        'current_target': 'system/agents/owner.md', 'fragment_verified': True}],
    }}}
    result = audit(tmp_path, manifest)
    assert result['checked'] == 0
    assert len(result['historical_references']) == 1
    assert result['metadata_errors'] == []
    put(tmp_path, 'system/evidence/report.md', content + b'changed evidence')
    assert audit(tmp_path, manifest)['metadata_errors']


def test_screenshot_references_use_manifest_base_not_repository_base(tmp_path):
    put(tmp_path, 'docs/assets/capture_manifest.json', b'{"images":[{"file":"image.png","sha256":"unchanged"}],"reused_images":"../other/capture_manifest.json"}')
    put(tmp_path, 'docs/assets/image.png', b'fixture image')
    put(tmp_path, 'docs/other/capture_manifest.json', b'{"images":[]}')
    paths = ['docs/assets/capture_manifest.json', 'docs/assets/image.png', 'docs/other/capture_manifest.json']
    manifest = {'entries': {p: {'destination': p, 'disposition': 'keep'} for p in paths}}
    result = audit(tmp_path, manifest)
    assert result['checked'] == 2
    assert result['metadata_errors'] == []
    (tmp_path / 'docs/assets/image.png').unlink()
    assert audit(tmp_path, manifest)['metadata_errors']
