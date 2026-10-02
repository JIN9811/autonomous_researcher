"""Byte-preserving, fully preflighted moves from an explicit reviewed Git map.

This does not rewrite references, stage Git changes, delete documents, or select
private state. Baseline identity and reviewed move-time identity are distinct.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import json
import posixpath
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .manifest import _git, disposition, git_entries, validate_manifest

IDENTITY_FIELDS = ('mode', 'git_blob', 'sha256', 'size')
RAW_SOURCE_DEFERRALS = frozenset({
    'docs/knowledge/manuals/sources/Indicator Manual.pdf',
    'docs/knowledge/manuals/sources/Software Manual.pdf',
})


def document_move(source: str, row: dict) -> bool:
    """Classify approved rows; never infer a destination to perform a move."""
    destination = row['destination']
    return row['disposition'] == 'move' and (
        destination.startswith(('system/', 'docs/'))
        or (source, destination) in {('SECURITY.md', '.github/SECURITY.md'),
                                    ('LICENSE', 'runtime/LICENSE')})


def _identity(data: bytes, mode: str) -> dict:
    header = f'blob {len(data)}\0'.encode()
    return {'mode': mode, 'git_blob': hashlib.sha1(header + data).hexdigest(),
            'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def _parents(root: Path, path: Path) -> None:
    for parent in path.parents:
        if parent == root:
            return
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f'Unsafe parent or symlink: {path.relative_to(root)}')
    raise ValueError('Path is not contained in repository')


def _working_identity(root: Path, relative: str) -> dict:
    path = root / relative
    _parents(root, path)
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f'Missing source: {relative}') from exc
    if stat.S_ISLNK(info.st_mode):
        if not path.resolve().is_relative_to(root):
            raise ValueError(f'Escaping source symlink: {relative}')
        return _identity(os.fsencode(os.readlink(path)), '120000')
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Unsupported source type: {relative}')
    return _identity(path.read_bytes(), '100755' if info.st_mode & 0o111 else '100644')


def _records(root: Path, revision: str) -> dict:
    return {path: (mode, kind, blob) for path, mode, kind, blob in git_entries(root, revision)}


def _lfs_object(root: Path, source: str, destination: str, data: bytes, records: dict) -> dict | None:
    match = re.fullmatch(rb'version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize ([1-9][0-9]*)\n', data)
    if not match:
        return None
    attributes = records.get('.gitattributes')
    if not attributes or attributes[:2] != ('100644', 'blob'):
        raise ValueError('LFS pointer lacks pinned attributes')
    contents = _git(root, 'cat-file', 'blob', attributes[2])
    # Deliberately supports only the reviewed repository rule, not arbitrary
    # filter commands/configuration. No Git LFS process or download is run.
    if (contents.strip() != b'*.mp4 filter=lfs diff=lfs merge=lfs -text'
            or not source.endswith('.mp4') or not destination.endswith('.mp4')
            or _working_identity(root, '.gitattributes') != _identity(contents, '100644')):
        raise ValueError('Unverified LFS attributes')
    for name in records:
        if name.endswith('/.gitattributes') and any(
                path.startswith(name.removesuffix('.gitattributes')) for path in (source, destination)):
            raise ValueError('Nested LFS attribute overrides are not approved')
    return {'sha256': match[1].decode(), 'size': int(match[2])}


def apply_moves(repository_root: Path, manifest: dict, *, phase: str,
                dry_run: bool = True) -> dict:
    """Preflight every selected path, then rename without staging or rewriting.

    ``move_revision`` must be the exact reviewed HEAD commit. ``additions`` is
    a separate exact inventory for new selected paths, not a baseline refresh.
    The two raw manual PDFs require explicit ``phase_deferrals`` and remain in
    place for the separately authorized private-state phase.
    """
    if phase != 'documents':
        raise ValueError(f'Unsupported move phase: {phase}')
    root = Path(repository_root).resolve()
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError('; '.join(errors))
    revision = manifest.get('move_revision')
    if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('An exact reviewed move_revision commit is required')
    if _git(root, 'rev-parse', 'HEAD').decode().strip() != revision:
        raise ValueError('HEAD differs from reviewed move_revision')
    current = _records(root, revision)
    baseline_revision = manifest['baseline_commit']
    baseline = _records(root, baseline_revision)
    entries = manifest['entries']
    if set(entries) != set(baseline):
        raise ValueError('Frozen inventory must account for exactly the baseline')
    additions = manifest.get('additions', {})
    if not isinstance(additions, dict) or set(additions) & set(entries):
        raise ValueError('Invalid separate addition inventory')
    combined = {**entries, **additions}
    validation = {**manifest, 'entries': combined, 'tracked_paths': sorted(combined)}
    if validate_manifest(validation):
        raise ValueError('Invalid addition destinations or identities')
    # New paths are only classified to detect omissions; no inferred row moves.
    for source in set(current) - set(entries):
        destination, action, _ = disposition(source)
        if document_move(source, {'destination': destination, 'disposition': action}) and source not in additions:
            raise ValueError(f'Unaccounted document addition: {source}')
    selected = {path: row for path, row in combined.items() if document_move(path, row)}
    deferrals = manifest.get('phase_deferrals', {})
    required_deferrals = set(selected) & RAW_SOURCE_DEFERRALS
    if not isinstance(deferrals, dict) or set(deferrals) != required_deferrals:
        raise ValueError('Exact raw source phase deferral accounting required')
    index = {}
    for record in _git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if record:
            metadata, name = record.split(b'\t', 1)
            mode, blob, stage = metadata.decode().split()
            if stage != '0':
                raise ValueError('Unmerged index entries prohibit moves')
            index[name.decode()] = (mode, blob)
    moves, deferred = [], []
    for source, row in sorted(selected.items()):
        destination = row['destination']
        if source not in current or current[source][1] != 'blob':
            raise ValueError(f'Reviewed source unavailable: {source}')
        mode, _, blob = current[source]
        data = _git(root, 'cat-file', 'blob', blob)
        expected = _identity(data, mode)
        if index.get(source) != (mode, blob):
            raise ValueError(f'Source index differs from reviewed commit: {source}')
        working = _working_identity(root, source)
        lfs = _lfs_object(root, source, destination, data, current)
        smudged = lfs is not None and working['mode'] == mode and all(working[key] == lfs[key] for key in ('sha256', 'size'))
        if working != expected and not smudged:
            raise ValueError(f'Source bytes/mode differ from reviewed commit: {source}')
        original = None
        if source in entries:
            old_mode, old_kind, old_blob = baseline[source]
            if old_kind != 'blob':
                raise ValueError(f'Unsupported baseline type: {source}')
            original = _identity(_git(root, 'cat-file', 'blob', old_blob), old_mode)
            if any(row[key] != original[key] for key in IDENTITY_FIELDS):
                raise ValueError(f'Frozen baseline identity changed: {source}')
            original = {'revision': baseline_revision, **original}
        elif any(row[key] != expected[key] for key in IDENTITY_FIELDS):
            raise ValueError(f'Addition identity differs from reviewed commit: {source}')
        if source in deferrals:
            record = deferrals[source]
            if (not isinstance(record, dict) or record.get('phase') != phase
                    or record.get('current_location') != source
                    or any(record.get(key) != expected[key] for key in ('mode', 'sha256'))
                    or not record.get('reason') or not record.get('handoff')
                    or original is None
                    or any(original[key] != expected[key] for key in IDENTITY_FIELDS)):
                raise ValueError(f'Invalid unchanged raw source deferral: {source}')
            deferred.append({'source': source, 'destination': destination, **record,
                             'baseline': original, 'pre_move': {'revision': revision, **expected}})
            continue
        if source.startswith('docs/knowledge/manuals/sources/'):
            raise ValueError(f'Private raw sources cannot move in document phase: {source}')
        target = root / destination
        _parents(root, target)
        if destination in current or destination in index or os.path.lexists(target):
            raise ValueError(f'Destination collision (including untracked): {destination}')
        if mode == '120000':
            link = os.readlink(root / source)
            if not (target.parent / link).resolve().is_relative_to(root):
                raise ValueError(f'Escaping destination symlink: {destination}')
        record = {'source': source, 'destination': destination, 'baseline': original,
                  'pre_move': {'revision': revision, **expected}, 'post_move': expected.copy()}
        if lfs:
            record.update(lfs_object=lfs, representation='lfs-smudged' if smudged else 'lfs-pointer',
                          working_before=working, working_after=working.copy())
        if source in additions:
            record['addition_reason'] = row['reason']
        moves.append(record)
    changed = []
    if not dry_run:
        for record in moves:
            source, destination = root / record['source'], root / record['destination']
            # Recheck immediately before touching each path. Exclusive writer is
            # still required; the tool does not claim a cross-filesystem transaction.
            _parents(root, destination)
            expected_working = record.get('working_before', record['post_move'])
            if os.path.lexists(destination) or _working_identity(root, record['source']) != expected_working:
                raise ValueError(f'Path changed after preflight: {record["source"]}')
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            actual = _working_identity(root, record['destination'])
            if actual != expected_working:
                raise ValueError(f'Post-move identity differs: {record["destination"]}')
            changed.extend((record['source'], record['destination']))
    return {'phase': phase, 'dry_run': dry_run, 'move_revision': revision,
            'moves': moves, 'deferred': deferred, 'changed_paths': sorted(changed)}


def rewrite_document_references(text: str, old_path: str, new_path: str,
                                mapping: dict[str, str]) -> tuple[str, list[dict]]:
    """Rewrite only parsed link targets and explicitly owned metadata scalars.

    Returns exact before/after/reason accounting. Does not write files, refresh
    evidence hashes, change execution excerpts, or reinterpret runtime paths.
    """
    import yaml
    from .checks import METADATA_PATH_FIELDS, reference_spans
    edits = []

    def mapped(path):
        if path in mapping:
            return mapping[path]
        children = [(old, new) for old, new in mapping.items() if old.startswith(path.rstrip('/') + '/')]
        candidates = {new[:-len(old) + len(path.rstrip('/'))] for old, new in children}
        return next(iter(candidates)) + ('/' if path.endswith('/') else '') if len(candidates) == 1 else path

    def relative(target):
        parts = urlsplit(target)
        if not parts.path or parts.scheme or parts.netloc or target.startswith('/'):
            return target
        old_target = posixpath.normpath(posixpath.join(posixpath.dirname(old_path), unquote(parts.path)))
        target_path = mapped(old_target)
        result = posixpath.relpath(target_path, posixpath.dirname(new_path) or '.')
        # Keep the original spelling where the target does not change.
        if result == unquote(parts.path):
            return target
        result = quote(result, safe='/@:+,~!$&*=;') if '%' in parts.path or ' ' in result else result
        return urlunsplit(('', '', result, parts.query, parts.fragment))

    def replace(start, end, before, after, reason):
        if before != after:
            edits.append({'start': start, 'end': end, 'before': text[start:end],
                          'after': after, 'reason': reason})

    suffix = Path(old_path).suffix.lower()
    front = re.match(r'\A(?:---\r?\n|<!-- atr-doc\r?\n)', text)
    offset, metadata_end = 0, 0
    document = None
    if front:
        close = '-->' if text.startswith('<!--') else '---'
        closing = re.search(r'^' + re.escape(close) + r'\s*$', text[front.end():], re.M)
        if not closing:
            raise ValueError('Unterminated metadata')
        offset = front.end()
        metadata_end = offset + closing.end()
        document = yaml.compose(text[offset:offset + closing.start()])
    elif old_path.endswith(('document_manifest.yaml', 'paper/artifact_manifest.yaml',
                            'knowledge/manuals/registry.yaml', 'knowledge/publication_allowlist.json')):
        document = yaml.compose(text)
        metadata_end = len(text)

    def scalar(node, kind='repository'):
        if not isinstance(node, yaml.ScalarNode):
            return
        old = node.value
        if kind == 'filesystem-relative':
            # Registry consumers use Path(parent / value), not URL decoding.
            if Path(old).is_absolute():
                raise ValueError('Registry source must be a relative filesystem path')
            target = posixpath.normpath(posixpath.join(posixpath.dirname(old_path), old))
            new = posixpath.relpath(mapped(target), posixpath.dirname(new_path) or '.')
        else:
            new = relative(old) if kind == 'relative' else mapped(old)
        if new == old:
            return
        start, end = offset + node.start_mark.index, offset + node.end_mark.index
        raw = text[start:end]
        rendered = json.dumps(new, ensure_ascii=False) if raw.startswith(('"', "'")) else new
        replace(start, end, old, rendered, kind + ' metadata reference')

    def values(node, kind='repository'):
        if isinstance(node, yaml.SequenceNode):
            for value in node.value:
                scalar(value, kind)
        else:
            scalar(node, kind)

    def fields(node):
        return {key.value: value for key, value in node.value} if isinstance(node, yaml.MappingNode) else {}

    data = fields(document)
    if front:
        for field in METADATA_PATH_FIELDS:
            if field in data:
                values(data[field])
        if 'source_revision' in data:
            for key, _ in data['source_revision'].value:
                scalar(key)
    elif old_path.endswith('document_manifest.yaml'):
        values(data['documents'])
        snapshot = fields(data.get('snapshot'))
        if 'document' in snapshot:
            scalar(snapshot['document'])
    elif old_path.endswith('knowledge/manuals/registry.yaml'):
        for source in data['sources'].value:
            scalar(fields(source)['path'], 'filesystem-relative')
    elif old_path.endswith('knowledge/publication_allowlist.json'):
        for key, _ in data['approved_assets'].value:
            scalar(key)
        values(data['approved_corpora'])
    elif old_path.endswith('paper/artifact_manifest.yaml'):
        for record in data['evidence'].value:
            row = fields(record)
            values(row['inputs'])
            for output in row['outputs'].value:
                scalar(fields(output)['path'])
    body = ' ' * metadata_end + text[metadata_end:]
    for start, end, target in reference_spans(body, suffix):
        replace(start, end, target, relative(target), 'document-relative link')
    result = text
    for edit in sorted(edits, key=lambda edit: edit['start'], reverse=True):
        result = result[:edit['start']] + edit['after'] + result[edit['end']:]
    return result, sorted(edits, key=lambda edit: edit['start'])
