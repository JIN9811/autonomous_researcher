"""
File purpose:
- Persist editable Runtime IDE module configs without touching Python source.

Key classes/functions:
- ModuleConfigStore

Inputs/outputs:
- Input: module YAML payloads edited by the GUI/IDE
- Output: versioned module snapshots and atomic active module.yaml updates

Dependencies:
- pathlib
- pyyaml

Modification guide:
- Safe places to edit: metadata fields and module validation helpers
- Risky places to edit: allowing module ids to escape graphs/modules
- Related files: app/main.py, graphs/modules/*/module.yaml
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class ModuleConfigStore:
    """File-backed store for Runtime IDE module configs."""

    module_root: Path
    version_root: Path

    @staticmethod
    def safe_module_id(module_id: str) -> str:
        """Normalize module ids to a single safe path segment."""
        clean = module_id.strip()
        if not clean:
            raise ValueError("module_id cannot be empty")
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in clean)
        if safe != clean:
            raise ValueError(f"Unsafe module_id={module_id}")
        return safe

    @staticmethod
    def version_id() -> str:
        """Return a monotonically sortable UTC version id."""
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    def module_path(self, module_id: str) -> Path:
        """Return active module.yaml path."""
        safe = self.safe_module_id(module_id)
        return self.module_root / safe / "module.yaml"

    def version_dir(self, module_id: str) -> Path:
        """Return version directory for a module."""
        safe = self.safe_module_id(module_id)
        return self.version_root / safe

    def list_versions(self, module_id: str) -> list[dict[str, Any]]:
        """List module versions newest first."""
        path = self.version_dir(module_id)
        if not path.exists():
            return []
        versions: list[dict[str, Any]] = []
        for item in sorted(path.glob("*.yaml"), reverse=True):
            try:
                raw = yaml.safe_load(item.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                raw = {}
            meta = raw.get("metadata", {}) if isinstance(raw, dict) else {}
            versions.append(
                {
                    "version_id": item.stem,
                    "path": str(item),
                    "reason": meta.get("reason", ""),
                    "author": meta.get("author", ""),
                    "created_at": meta.get("created_at", ""),
                }
            )
        return versions

    def read_version(self, module_id: str, version_id: str) -> dict[str, Any]:
        """Read one immutable module version payload."""
        safe = self.safe_module_id(module_id)
        version_dir = self.version_dir(safe).resolve()
        path = (version_dir / f"{version_id}.yaml").resolve()
        try:
            path.relative_to(version_dir)
        except ValueError as exc:
            raise ValueError(f"Unsafe module version_id={version_id}") from exc
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Unknown module version_id={version_id}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid module version payload: {version_id}")
        meta = raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {}
        payload = self.normalize_payload(raw)
        return {
            "version_id": path.stem,
            "path": str(path),
            "metadata": meta,
            "module": payload,
        }

    @staticmethod
    def normalize_payload(module_payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize module payload to the canonical {'module': ...} wrapper."""
        if "module" in module_payload and isinstance(module_payload["module"], dict):
            return module_payload
        return {"module": module_payload}

    def save_version(
        self,
        module_id: str,
        module_payload: dict[str, Any],
        *,
        reason: str = "module_save",
        author: str = "runtime_api",
    ) -> dict[str, Any]:
        """Save an immutable module config version."""
        safe = self.safe_module_id(module_id)
        version_dir = self.version_dir(safe)
        version_dir.mkdir(parents=True, exist_ok=True)
        version_id = self.version_id()
        created_at = datetime.now(timezone.utc).isoformat()
        path = version_dir / f"{version_id}.yaml"
        payload = {
            "metadata": {
                "version_id": version_id,
                "module_id": safe,
                "reason": reason,
                "author": author,
                "created_at": created_at,
                "active_module_path": str(self.module_path(safe)),
            },
            **self.normalize_payload(module_payload),
        }
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return {
            "version_id": version_id,
            "path": str(path),
            "reason": reason,
            "author": author,
            "created_at": created_at,
        }

    def write_active(self, module_id: str, module_payload: dict[str, Any]) -> None:
        """Atomically replace active module.yaml."""
        safe = self.safe_module_id(module_id)
        active = self.module_path(safe)
        active.parent.mkdir(parents=True, exist_ok=True)
        payload = self.normalize_payload(module_payload)
        tmp = active.with_suffix(active.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        tmp.replace(active)
