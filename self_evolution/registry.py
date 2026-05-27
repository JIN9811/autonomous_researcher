"""File-backed registry for self-evolution tasks and variants."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import EvolutionTask, EvolutionTrace, EvolutionVariant


@dataclass(slots=True)
class EvolutionRegistry:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.variants_dir.mkdir(parents=True, exist_ok=True)
        self.traces_dir.mkdir(parents=True, exist_ok=True)

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def variants_dir(self) -> Path:
        return self.root / "variants"

    @property
    def traces_dir(self) -> Path:
        return self.root / "traces"

    @property
    def active_path(self) -> Path:
        return self.root / "active_variants.json"

    def list_tasks(self) -> list[EvolutionTask]:
        return [EvolutionTask.model_validate(self._read_json(path)) for path in sorted(self.tasks_dir.glob("*.json"), reverse=True)]

    def save_task(self, task: EvolutionTask) -> EvolutionTask:
        self._write_json(self.tasks_dir / f"{task.task_id}.json", task.model_dump(mode="json"))
        return task

    def read_task(self, task_id: str) -> EvolutionTask:
        path = self.tasks_dir / f"{self._safe_id(task_id)}.json"
        if not path.exists():
            raise FileNotFoundError(f"Unknown evolution task_id={task_id}")
        return EvolutionTask.model_validate(self._read_json(path))

    def list_variants(self, task_id: str | None = None) -> list[EvolutionVariant]:
        variants = [EvolutionVariant.model_validate(self._read_json(path)) for path in sorted(self.variants_dir.glob("*.json"), reverse=True)]
        if task_id:
            variants = [variant for variant in variants if variant.task_id == task_id]
        return variants

    def save_variant(self, variant: EvolutionVariant) -> EvolutionVariant:
        self._write_json(self.variants_dir / f"{variant.variant_id}.json", variant.model_dump(mode="json"))
        return variant

    def read_variant(self, variant_id: str) -> EvolutionVariant:
        path = self.variants_dir / f"{self._safe_id(variant_id)}.json"
        if not path.exists():
            raise FileNotFoundError(f"Unknown evolution variant_id={variant_id}")
        return EvolutionVariant.model_validate(self._read_json(path))

    def save_trace(self, trace: EvolutionTrace) -> EvolutionTrace:
        self._write_json(self.traces_dir / f"{trace.trace_id}.json", trace.model_dump(mode="json"))
        return trace

    def read_trace(self, trace_id: str) -> EvolutionTrace:
        path = self.traces_dir / f"{self._safe_id(trace_id)}.json"
        if not path.exists():
            raise FileNotFoundError(f"Unknown evolution trace_id={trace_id}")
        return EvolutionTrace.model_validate(self._read_json(path))

    def active_variants(self) -> dict[str, Any]:
        if not self.active_path.exists():
            return {}
        raw = self._read_json(self.active_path)
        return raw if isinstance(raw, dict) else {}

    def set_active(self, target_type: str, target_id: str, variant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        active = self.active_variants()
        key = f"{target_type}:{target_id}"
        active[key] = {"variant_id": variant_id, **payload}
        self._write_json(self.active_path, active)
        return active[key]

    @staticmethod
    def _safe_id(value: str) -> str:
        clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value).strip())
        if not clean or clean != value:
            raise ValueError(f"Unsafe id={value}")
        return clean

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
