"""Explicit path authority must not depend on CWD or populated replacements."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from utils import runtime_paths as rp


STORES = {
    "run_root": "runs", "memory_root": "memory", "artifact_root": "artifacts",
    "output_root": "outputs", "source_inbox_root": "docs/knowledge/manuals/sources",
    "user_file_root": "user_files", "log_root": "logs",
}


def layout(tmp_path, **changes):
    config = tmp_path / "configuration" / "layout.json"
    config.parent.mkdir(exist_ok=True)
    payload = {"schema": "atr.path_layout.v1", "repository_root": "../repository",
               "runtime_root": "../code/installed", "system_root": "../reference/guides",
               "workspace_root": "../private/workspace", "defaults": STORES}
    payload.update(changes)
    config.write_text(json.dumps(payload))
    return config


def inventory(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


def test_resolution_is_pure_and_cwd_independent(tmp_path, monkeypatch):
    config = layout(tmp_path)
    runtime = tmp_path / "code/installed"
    runtime.mkdir(parents=True)
    before = inventory(tmp_path)
    monkeypatch.chdir(tmp_path)
    outer = rp.load_paths(config)
    monkeypatch.chdir(runtime)
    inner = rp.load_paths(config)
    assert inner == outer
    assert inner.repository_root == tmp_path / "repository"
    assert inner.runtime_root == runtime
    assert inner.memory_root == tmp_path / "repository/memory"
    assert rp.resolve_runtime_path("configs/system.yaml", paths=inner) == runtime / "configs/system.yaml"
    assert rp.resolve_repository_path(".env", paths=inner) == tmp_path / "repository/.env"
    assert rp.resolve_system_path("project/guide.txt", paths=inner) == tmp_path / "reference/guides/project/guide.txt"
    assert rp.resolve_data_path("memory", "settings.json", paths=inner) == tmp_path / "repository/memory/settings.json"
    absolute = Path("/external/models/../cache")
    assert rp.resolve_runtime_path(absolute, paths=inner) == absolute
    assert inventory(tmp_path) == before
    assert not inner.workspace_root.exists()
    with pytest.raises(FrozenInstanceError):
        inner.run_root = tmp_path


def test_explicit_legacy_binding_wins_without_copy(tmp_path):
    config = layout(tmp_path, candidates={"memory_root": ["../replacement/memory"]})
    replacement = tmp_path / "replacement/memory"
    replacement.mkdir(parents=True)
    (replacement / "stale.json").write_text("replacement")
    legacy = tmp_path / "legacy/memory"
    legacy.mkdir(parents=True)
    (legacy / "evidence.bin").write_bytes(b"immutable evidence")
    bindings = tmp_path / "bindings.json"
    bindings.write_text(json.dumps({"schema": "atr.path_bindings.v1", "stores": {"memory_root": "legacy/memory"}}))
    before = inventory(tmp_path)
    assert rp.load_paths(config, bindings_file=bindings).memory_root == legacy
    assert inventory(tmp_path) == before


def test_conflicting_bindings_fail(tmp_path):
    config = layout(tmp_path, stores={"run_root": "../selected/runs"})
    bindings = tmp_path / "bindings.json"
    bindings.write_text(json.dumps({"schema": "atr.path_bindings.v1", "stores": {"run_root": "other/runs"}}))
    with pytest.raises(ValueError, match="conflict"):
        rp.load_paths(config, bindings_file=bindings)


def test_unselected_populated_stores_fail(tmp_path):
    config = layout(tmp_path, candidates={"memory_root": ["../replacement/memory"]})
    replacement = tmp_path / "replacement/memory"
    replacement.mkdir(parents=True)
    # Even an empty replacement never selects authority.
    assert rp.load_paths(config).memory_root == tmp_path / "repository/memory"
    (replacement / "state.json").write_text("{}")
    with pytest.raises(ValueError, match="unselected"):
        rp.load_paths(config)


def test_finalization_rejects_rebinding_and_compatibility_is_repository_relative(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "_current", None)
    paths = rp.load_paths(layout(tmp_path))
    assert rp.finalize_paths(paths) is paths
    assert rp.current_paths() is paths
    assert rp.finalize_paths(paths) is paths
    with pytest.raises(ValueError, match="conflict"):
        rp.finalize_paths(replace(paths, memory_root=tmp_path / "another"))
    from utils.paths import project_root, resolve_path
    assert project_root() == tmp_path / "repository"
    assert resolve_path("configs") == tmp_path / "repository/configs"


def test_environment_selection_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "_current", None)
    config = layout(tmp_path)
    bindings = tmp_path / "private.json"
    bindings.write_text(json.dumps({"schema": "atr.path_bindings.v1", "stores": {"run_root": "separate/runs"}}))
    monkeypatch.setenv("ATR_LAYOUT_CONFIG", str(config))
    monkeypatch.setenv("ATR_PATH_BINDINGS", str(bindings))
    monkeypatch.chdir(tmp_path / "configuration")
    assert rp.current_paths().run_root == tmp_path / "separate/runs"
    monkeypatch.setenv("ATR_LAYOUT_CONFIG", str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        rp.current_paths()


@pytest.mark.parametrize("changes", [{"schema": "unknown"}, {"defaults": {"typo_root": "x"}}, {"stores": {"memory_root": ""}}])
def test_invalid_configuration_fails(tmp_path, changes):
    with pytest.raises(ValueError):
        rp.load_paths(layout(tmp_path, **changes))


def test_flat_defaults_remain_legacy(tmp_path):
    root = Path(__file__).resolve().parents[2]
    paths = rp.load_paths(root / "configs/repository_layout.json")
    assert paths.repository_root == paths.runtime_root == root
    assert paths.system_root == root / "docs"
    for field, suffix in STORES.items():
        assert getattr(paths, field) == root / suffix
