"""
File purpose:
- Persist versioned graph config snapshots for Runtime IDE edits.

Key classes/functions:
- GraphVersionStore

Inputs/outputs:
- Input: active graph YAML and validated graph payloads
- Output: immutable version files plus atomic active graph updates

Dependencies:
- pathlib
- pyyaml

Modification guide:
- Safe places to edit: version metadata fields and listing format
- Risky places to edit: active config writes without prior validation/compile
- Related files: app/main.py, graphs/schema.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class GraphVersionStore:
    """Small file-backed store for graph config versions."""

    active_config_path: Path
    version_root: Path

    def _graph_dir(self, graph_id: str) -> Path:
        clean = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in graph_id)
        return self.version_root / clean

    @staticmethod
    def _version_id() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    @staticmethod
    def _yaml_payload(graph_payload: dict[str, Any]) -> str:
        return yaml.safe_dump({"graph": graph_payload}, sort_keys=False, allow_unicode=True)

    def list_versions(self, graph_id: str) -> list[dict[str, Any]]:
        """List available graph versions newest first."""
        graph_dir = self._graph_dir(graph_id)
        if not graph_dir.exists():
            return []
        versions: list[dict[str, Any]] = []
        for path in sorted(graph_dir.glob("*.yaml"), reverse=True):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                raw = {}
            meta = raw.get("metadata", {}) if isinstance(raw, dict) else {}
            versions.append(
                {
                    "version_id": path.stem,
                    "path": str(path),
                    "reason": meta.get("reason", ""),
                    "author": meta.get("author", ""),
                    "created_at": meta.get("created_at", ""),
                }
            )
        return versions

    def read_version(self, graph_id: str, version_id: str) -> dict[str, Any]:
        """Read one immutable graph version payload."""
        graph_dir = self._graph_dir(graph_id).resolve()
        path = (graph_dir / f"{version_id}.yaml").resolve()
        try:
            path.relative_to(graph_dir)
        except ValueError as exc:
            raise ValueError(f"Unsafe graph version_id={version_id}") from exc
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Unknown graph version_id={version_id}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict) or not isinstance(raw.get("graph"), dict):
            raise ValueError(f"Invalid graph version payload: {version_id}")
        meta = raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {}
        return {
            "version_id": path.stem,
            "path": str(path),
            "metadata": meta,
            "graph": raw["graph"],
        }

    def save_version(
        self,
        graph_id: str,
        graph_payload: dict[str, Any],
        *,
        reason: str = "manual_save",
        author: str = "runtime_api",
    ) -> dict[str, Any]:
        """Save one immutable graph config version."""
        graph_dir = self._graph_dir(graph_id)
        graph_dir.mkdir(parents=True, exist_ok=True)
        version_id = self._version_id()
        path = graph_dir / f"{version_id}.yaml"
        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "metadata": {
                "version_id": version_id,
                "graph_id": graph_id,
                "reason": reason,
                "author": author,
                "created_at": created_at,
                "active_config_path": str(self.active_config_path),
            },
            "graph": graph_payload,
        }
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return {
            "version_id": version_id,
            "path": str(path),
            "reason": reason,
            "author": author,
            "created_at": created_at,
        }

    def write_active(self, graph_payload: dict[str, Any]) -> None:
        """Atomically replace the active graph config YAML."""
        self.active_config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.active_config_path.with_suffix(self.active_config_path.suffix + ".tmp")
        tmp.write_text(self._yaml_payload(graph_payload), encoding="utf-8")
        tmp.replace(self.active_config_path)
