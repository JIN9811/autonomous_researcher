"""Resolve Bambu preset inheritance before passing standalone JSON to the CLI."""
from __future__ import annotations

import json
from pathlib import Path


def resolve_profile(path: Path, stack: tuple[Path, ...] = ()) -> dict:
    path = path.resolve()
    if path in stack or len(stack) >= 32:
        raise ValueError(f'Cyclic or excessive preset inheritance: {path.name}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'Invalid preset: {path.name}')
    parent = data.get('inherits', '')
    merged = {}
    if parent:
        if not isinstance(parent, str) or Path(parent).name != parent:
            raise ValueError(f'Invalid parent in {path.name}')
        merged = resolve_profile(path.parent / f'{parent}.json', (*stack, path))
    includes = data.get('include', [])
    if not isinstance(includes, list):
        raise ValueError(f'Invalid includes in {path.name}')
    for name in includes:
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError(f'Invalid include in {path.name}')
        merged.update(resolve_profile(path.parent / f'{name}.json', (*stack, path)))
    merged.update(data)
    merged.pop('inherits', None)
    merged.pop('include', None)
    return merged
