"""Durable storage for objective definitions, decisions, and run bindings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from objectives.schemas import (
    ObjectiveBinding,
    ObjectiveDecision,
    ObjectiveEvaluation,
    ObjectivePreview,
    ObjectiveSpec,
    ObjectiveValidation,
)


class ObjectiveConflict(RuntimeError):
    """Raised when an immutable objective or run binding would be changed."""


class ObjectiveNotFound(KeyError):
    """Raised when an objective artifact cannot be found."""


class ObjectiveStore:
    """Inspectible JSON/JSONL persistence with atomic mutable indexes."""

    def __init__(self, root: Path, *, run_root: Path | None = None) -> None:
        self.root = root.resolve()
        self.run_root = (run_root or self.root.parent.parent / "runs").resolve()
        self.spec_root = self.root / "specs"
        self.spec_root.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.decisions_path = self.root / "decisions.jsonl"
        self.evaluations_path = self.root / "evaluations.jsonl"
        self.bindings_path = self.root / "active_bindings.json"

    @classmethod
    def default(cls, project_root: Path | None = None) -> "ObjectiveStore":
        project = (project_root or Path(__file__).resolve().parent.parent).resolve()
        return cls(project / "memory" / "objectives", run_root=project / "runs")

    @staticmethod
    def _safe_id(value: str, label: str = "id") -> str:
        clean = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in str(value).strip())
        if not clean or clean in {".", ".."}:
            raise ValueError(f"invalid {label}")
        return clean

    def _version_dir(self, objective_id: str) -> Path:
        path = (self.spec_root / self._safe_id(objective_id, "objective_id")).resolve()
        path.relative_to(self.spec_root.resolve())
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _artifact_path(self, objective_id: str, version: int, suffix: str) -> Path:
        if version < 1:
            raise ValueError("version must be positive")
        return self._version_dir(objective_id) / f"v{version:06d}.{suffix}.json"

    @staticmethod
    def _atomic_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _read_json(path: Path, default: Any = None) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def save_spec(self, spec: ObjectiveSpec) -> Path:
        path = self._artifact_path(spec.objective_id, spec.version, "spec")
        if path.exists():
            current = ObjectiveSpec.model_validate(self._read_json(path))
            if current != spec:
                raise ObjectiveConflict(f"objective {spec.objective_id} v{spec.version} is immutable")
            return path
        self._atomic_json(path, spec.model_dump(mode="json"))
        return path

    def load_spec(self, objective_id: str, version: int | None = None) -> ObjectiveSpec:
        resolved_version = version or self.latest_version(objective_id)
        path = self._artifact_path(objective_id, resolved_version, "spec")
        if not path.exists():
            raise ObjectiveNotFound(f"objective {objective_id} v{resolved_version} not found")
        return ObjectiveSpec.model_validate(self._read_json(path))

    def latest_version(self, objective_id: str) -> int:
        versions = []
        for path in self._version_dir(objective_id).glob("v*.spec.json"):
            try:
                versions.append(int(path.name.split(".", 1)[0][1:]))
            except ValueError:
                continue
        if not versions:
            raise ObjectiveNotFound(f"objective {objective_id} not found")
        return max(versions)

    def list_specs(self) -> list[ObjectiveSpec]:
        records: list[ObjectiveSpec] = []
        for path in sorted(self.spec_root.glob("*/v*.spec.json")):
            try:
                records.append(ObjectiveSpec.model_validate(self._read_json(path)))
            except Exception:
                continue
        return records

    def save_validation(self, validation: ObjectiveValidation) -> Path:
        path = self._artifact_path(validation.objective_id, validation.version, "validation")
        self._atomic_json(path, validation.model_dump(mode="json"))
        return path

    def load_validation(self, objective_id: str, version: int) -> ObjectiveValidation | None:
        path = self._artifact_path(objective_id, version, "validation")
        payload = self._read_json(path)
        return ObjectiveValidation.model_validate(payload) if isinstance(payload, dict) else None

    def save_preview(self, preview: ObjectivePreview) -> Path:
        path = self._artifact_path(preview.objective_id, preview.version, "preview")
        self._atomic_json(path, preview.model_dump(mode="json"))
        return path

    def load_preview(self, objective_id: str, version: int) -> ObjectivePreview | None:
        path = self._artifact_path(objective_id, version, "preview")
        payload = self._read_json(path)
        return ObjectivePreview.model_validate(payload) if isinstance(payload, dict) else None

    def append_decision(self, decision: ObjectiveDecision) -> None:
        self._append_jsonl(self.decisions_path, decision.model_dump(mode="json"))

    def list_decisions(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.decisions_path)

    def append_evaluation(self, evaluation: ObjectiveEvaluation, *, run_id: str = "") -> None:
        payload = evaluation.model_dump(mode="json")
        if run_id:
            payload["run_id"] = run_id
        self._append_jsonl(self.evaluations_path, payload)
        if run_id:
            run_path = self.run_objective_dir(run_id) / "evaluations.jsonl"
            self._append_jsonl(run_path, payload)

    def list_evaluations(self, *, objective_hash: str = "", run_id: str = "") -> list[dict[str, Any]]:
        records = self._read_jsonl(self.evaluations_path)
        if objective_hash:
            records = [item for item in records if item.get("objective_hash") == objective_hash]
        if run_id:
            records = [item for item in records if item.get("run_id") == run_id]
        return records

    def run_objective_dir(self, run_id: str) -> Path:
        path = (self.run_root / self._safe_id(run_id, "run_id") / "objective").resolve()
        path.relative_to(self.run_root)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def bind_run(self, binding: ObjectiveBinding) -> None:
        bindings = self._read_json(self.bindings_path, {})
        if not isinstance(bindings, dict):
            bindings = {}
        existing = bindings.get(binding.run_id)
        payload = binding.model_dump(mode="json")
        if existing:
            if existing != payload:
                raise ObjectiveConflict(f"run {binding.run_id} is already bound to an immutable objective")
            return
        bindings[binding.run_id] = payload
        self._atomic_json(self.bindings_path, bindings)
        self._atomic_json(self.run_objective_dir(binding.run_id) / "binding.json", payload)

    def load_binding(self, run_id: str) -> ObjectiveBinding | None:
        bindings = self._read_json(self.bindings_path, {})
        payload = bindings.get(run_id) if isinstance(bindings, dict) else None
        return ObjectiveBinding.model_validate(payload) if isinstance(payload, dict) else None
