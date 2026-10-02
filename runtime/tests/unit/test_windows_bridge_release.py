from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

from utils.windows_bridge_release import build_release_package, load_release_manifest


def _release_tree(tmp_path: Path) -> tuple[Path, Path]:
    package_root = tmp_path / "windows"
    (package_root / "bridge").mkdir(parents=True)
    (package_root / "scripts").mkdir(parents=True)
    (package_root / "bridge" / "windows_pyautogui_bridge_server.py").write_text("print('bridge')\n", encoding="utf-8")
    (package_root / "scripts" / "bridge_self_updater.py").write_text("print('updater')\n", encoding="utf-8")
    (package_root / "requirements-windows.txt").write_text("pynput>=1.7.7,<2\n", encoding="utf-8")
    manifest_path = package_root / "release_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr.windows_bridge_release.v1",
                "version": "2026.08.28.1",
                "files": [
                    "bridge/windows_pyautogui_bridge_server.py",
                    "scripts/bridge_self_updater.py",
                    "requirements-windows.txt",
                ],
            }
        ),
        encoding="utf-8",
    )
    return package_root, manifest_path


def test_release_package_contains_only_manifest_files_with_reproducible_digests(tmp_path: Path) -> None:
    package_root, manifest_path = _release_tree(tmp_path)

    manifest = load_release_manifest(manifest_path, package_root=package_root)
    first = build_release_package(manifest, package_root=package_root)
    second = build_release_package(manifest, package_root=package_root)

    assert first == second
    assert first["schema"] == "atr.windows_bridge_update_package.v1"
    assert first["version"] == "2026.08.28.1"
    assert [item["path"] for item in first["files"]] == manifest["files"]
    for item in first["files"]:
        raw = (package_root / item["path"]).read_bytes()
        assert item["size_bytes"] == len(raw)
        assert item["sha256"] == hashlib.sha256(raw).hexdigest()
        assert item["data_base64"]
    assert len(first["package_sha256"]) == 64


def test_release_manifest_rejects_parent_traversal(tmp_path: Path) -> None:
    package_root, manifest_path = _release_tree(tmp_path)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr.windows_bridge_release.v1",
                "version": "2026.08.28.1",
                "files": ["../outside.py"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="relative update path"):
        load_release_manifest(manifest_path, package_root=package_root)


def test_release_package_rejects_file_larger_than_limit(tmp_path: Path) -> None:
    package_root, manifest_path = _release_tree(tmp_path)
    manifest = load_release_manifest(manifest_path, package_root=package_root)

    with pytest.raises(ValueError, match="size limit"):
        build_release_package(manifest, package_root=package_root, max_file_bytes=4)


def test_repository_release_updates_canonical_launch_files() -> None:
    package_root = Path(__file__).resolve().parents[2] / "Pyautogui_server_for_window"
    manifest = load_release_manifest(package_root=package_root)

    assert "release_manifest.json" in manifest["files"]
    assert "START_WINDOWS_BRIDGE.cmd" in manifest["files"]
    assert "scripts/install_bridge.ps1" in manifest["files"]
    assert "scripts/bridge_supervisor.py" in manifest["files"]
    assert "scripts/start_supervisor.ps1" in manifest["files"]
    assert "scripts/run_bridge.ps1" in manifest["files"]


def test_worker_release_version_is_loaded_from_manifest_instead_of_source_literal() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "Pyautogui_server_for_window"

    for path in (
        package_root / "bridge" / "windows_pyautogui_bridge_server.py",
        root / "install" / "windows_pyautogui_bridge_server.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert re.search(r'^BRIDGE_RELEASE_VERSION = "[^"]+"$', source, re.MULTILINE) is None
        assert "release_manifest.json" in source
