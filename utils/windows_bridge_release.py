"""Build the bounded update package sent to a paired Windows worker."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "Pyautogui_server_for_window"
DEFAULT_MANIFEST_PATH = DEFAULT_PACKAGE_ROOT / "release_manifest.json"
MAX_UPDATE_FILE_BYTES = 12 * 1024 * 1024
MAX_UPDATE_PACKAGE_BYTES = 24 * 1024 * 1024


def _safe_relative_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"invalid relative update path: {raw!r}")
    return path.as_posix()


def load_release_manifest(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    package_root: Path = DEFAULT_PACKAGE_ROOT,
) -> dict[str, Any]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "atr.windows_bridge_release.v1":
        raise ValueError("invalid Windows bridge release manifest schema")
    version = str(payload.get("version") or "").strip()
    files = payload.get("files")
    if not version or not isinstance(files, list) or not files:
        raise ValueError("Windows bridge release manifest requires version and files")
    normalized = [_safe_relative_path(value) for value in files]
    if len(set(normalized)) != len(normalized):
        raise ValueError("Windows bridge release manifest contains duplicate paths")
    root = Path(package_root).resolve()
    for relative in normalized:
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ValueError(f"release file is missing or outside package root: {relative}")
    return {"schema": payload["schema"], "version": version, "files": normalized}


def build_release_package(
    manifest: dict[str, Any] | None = None,
    *,
    package_root: Path = DEFAULT_PACKAGE_ROOT,
    max_file_bytes: int = MAX_UPDATE_FILE_BYTES,
    max_package_bytes: int = MAX_UPDATE_PACKAGE_BYTES,
) -> dict[str, Any]:
    release = manifest or load_release_manifest(package_root=package_root)
    root = Path(package_root).resolve()
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for raw_path in release.get("files", []):
        relative = _safe_relative_path(raw_path)
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"release file is missing or outside package root: {relative}")
        raw = path.read_bytes()
        if len(raw) > int(max_file_bytes):
            raise ValueError(f"release file exceeds size limit: {relative}")
        total_bytes += len(raw)
        if total_bytes > int(max_package_bytes):
            raise ValueError("Windows bridge release package exceeds size limit")
        files.append(
            {
                "path": relative,
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "data_base64": base64.b64encode(raw).decode("ascii"),
            }
        )
    digest_payload = {
        "schema": "atr.windows_bridge_update_package.v1",
        "version": str(release.get("version") or ""),
        "files": [
            {key: item[key] for key in ("path", "size_bytes", "sha256")}
            for item in files
        ],
    }
    canonical = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {
        **digest_payload,
        "files": files,
        "package_sha256": hashlib.sha256(canonical).hexdigest(),
        "total_bytes": total_bytes,
    }
