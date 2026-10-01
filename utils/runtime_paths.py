"""Immutable source and private-store bindings; resolution never creates state.

Layout source roots and explicit selections are layout-file-relative. Named
defaults are repository-relative; private selections are bindings-file-relative.
Candidates detect ambiguous populated stores, never select them. An explicit
selection acknowledges competing stores without modifying either one.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import json
import os
from pathlib import Path


_SOURCE_ROOTS = ("repository_root", "runtime_root", "system_root", "workspace_root")
_STORES = ("run_root", "memory_root", "artifact_root", "output_root",
           "source_inbox_root", "user_file_root", "log_root")
_CANONICAL_LAYOUT = Path(__file__).resolve().parents[1] / "configs/repository_layout.json"


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    repository_root: Path
    runtime_root: Path
    system_root: Path
    workspace_root: Path
    run_root: Path
    memory_root: Path
    artifact_root: Path
    output_root: Path
    source_inbox_root: Path
    user_file_root: Path
    log_root: Path

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError(f"{field.name} must be an absolute Path")
            object.__setattr__(self, field.name, value.resolve())


def _path(value: object, base: Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("Path must be non-empty text")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _document(file: Path, schema: str, allowed: set[str]) -> dict:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate/conflicting binding key: {key}")
            result[key] = value
        return result
    value = json.loads(file.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    if not isinstance(value, dict) or value.get("schema") != schema:
        raise ValueError(f"Expected {schema}: {file}")
    if set(value) - allowed:
        raise ValueError(f"Unknown layout fields: {sorted(set(value) - allowed)}")
    return value


def _stores(value: object) -> dict:
    if not isinstance(value, dict) or set(value) - set(_STORES):
        raise ValueError("Stores must be a mapping of named *_root fields")
    return value


def load_paths(layout_file: Path, *, bindings_file: Path | None = None) -> RuntimePaths:
    """Load and validate explicit roots, without mkdir, migration or search."""
    layout_file = Path(layout_file).expanduser().resolve()
    layout = _document(layout_file, "atr.path_layout.v1",
                       {"schema", *_SOURCE_ROOTS, "defaults", "stores", "candidates"})
    if any(name not in layout for name in _SOURCE_ROOTS):
        raise ValueError("Layout must specify every source root")
    roots = {name: _path(layout[name], layout_file.parent) for name in _SOURCE_ROOTS}
    defaults = _stores(layout.get("defaults", {}))
    if set(defaults) != set(_STORES):
        raise ValueError("Layout must specify every named store default")
    selected = {name: _path(value, layout_file.parent)
                for name, value in _stores(layout.get("stores", {})).items()}
    if bindings_file is not None:
        bindings_file = Path(bindings_file).expanduser().resolve()
        bindings = _document(bindings_file, "atr.path_bindings.v1", {"schema", "stores"})
        for name, value in _stores(bindings.get("stores", {})).items():
            path = _path(value, bindings_file.parent)
            if name in selected and selected[name] != path:
                raise ValueError(f"conflicting explicit binding: {name}")
            selected[name] = path
    roots.update({name: _path(value, roots["repository_root"]) for name, value in defaults.items()})
    roots.update(selected)
    for name, candidates in _stores(layout.get("candidates", {})).items():
        if not isinstance(candidates, list):
            raise ValueError(f"Candidates must be a list: {name}")
        for candidate in candidates:
            path = _path(candidate, layout_file.parent)
            if name not in selected and path != roots[name] and path.exists():
                if not path.is_dir() or any(path.iterdir()):
                    raise ValueError(f"populated unselected store: {name}: {path}; select a binding explicitly")
    return RuntimePaths(**roots)


_current: RuntimePaths | None = None


def current_paths() -> RuntimePaths:
    """Read the process binding, or explicit configuration before finalization."""
    if _current is not None:
        return _current
    layout = Path(os.environ.get("ATR_LAYOUT_CONFIG") or _CANONICAL_LAYOUT)
    binding = os.environ.get("ATR_PATH_BINDINGS")
    return load_paths(layout, bindings_file=Path(binding) if binding else None)


def finalize_paths(paths: RuntimePaths) -> RuntimePaths:
    """Install the production binding once; injected runtimes need not install it."""
    global _current
    if _current is not None and _current != paths:
        raise ValueError("conflicting finalized runtime paths")
    if _current is None:
        _current = paths
    return _current


def _resolve(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def resolve_repository_path(value: str | Path, *, paths: RuntimePaths | None = None) -> Path:
    return _resolve(value, (paths or current_paths()).repository_root)


def resolve_runtime_path(value: str | Path, *, paths: RuntimePaths | None = None) -> Path:
    return _resolve(value, (paths or current_paths()).runtime_root)


def resolve_system_path(value: str | Path, *, paths: RuntimePaths | None = None) -> Path:
    return _resolve(value, (paths or current_paths()).system_root)


def resolve_data_path(store: str, value: str | Path = ".", *, paths: RuntimePaths | None = None) -> Path:
    name = store if store.endswith("_root") else f"{store}_root"
    if name not in _STORES:
        raise ValueError(f"Unknown data store: {store}")
    return _resolve(value, getattr(paths or current_paths(), name))
