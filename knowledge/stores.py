"""File-backed Knowledge Agent memory store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from knowledge.schemas import (
    AgentPerformanceRecord,
    EvolutionEvidencePack,
    EvolutionOutcomeRecord,
    ExperimentKnowledgeRecord,
    FailurePatternRecord,
    SuccessPatternRecord,
)

T = TypeVar("T", bound=BaseModel)


class KnowledgeStore:
    """Interface-like base class for typed knowledge persistence."""

    def write_run_artifacts(self, run_id: str, artifacts: dict[str, Any]) -> dict[str, str]:
        raise NotImplementedError


class JsonlKnowledgeStore(KnowledgeStore):
    """JSON artifact + JSONL long-term memory store.

    Per-run files live under runs/<run_id>/knowledge/*.json. Long-term records are
    appended to memory/knowledge/*.jsonl. This keeps the first implementation
    inspectable and easy to migrate to SQLite/DuckDB later.
    """

    FILE_MAP = {
        "experiment_records": "experiment_knowledge_records.jsonl",
        "agent_performance_records": "agent_performance_records.jsonl",
        "failure_patterns": "failure_patterns.jsonl",
        "success_patterns": "success_patterns.jsonl",
        "evolution_evidence_packs": "evolution_evidence_packs.jsonl",
        "evolution_outcomes": "evolution_outcomes.jsonl",
    }

    def __init__(self, *, memory_root: Path, run_root: Path) -> None:
        self.memory_root = memory_root
        self.run_root = run_root
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def default(cls, project_root: Path | None = None) -> "JsonlKnowledgeStore":
        root = project_root or Path(__file__).resolve().parent.parent
        return cls(memory_root=root / "memory" / "knowledge", run_root=root / "runs")

    def run_knowledge_dir(self, run_id: str) -> Path:
        safe = self._safe_id(run_id)
        path = (self.run_root / safe / "knowledge").resolve()
        root = self.run_root.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Unsafe run_id={run_id}") from exc
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_run_artifacts(self, run_id: str, artifacts: dict[str, Any]) -> dict[str, str]:
        out: dict[str, str] = {}
        run_dir = self.run_knowledge_dir(run_id)
        for name, payload in artifacts.items():
            safe = self._safe_id(name).replace("-json", "")
            path = run_dir / f"{safe}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
            out[name] = path.as_posix()
        return out

    def append_experiment_record(self, record: ExperimentKnowledgeRecord) -> None:
        self._append("experiment_records", record)

    def append_agent_performance_records(self, records: list[AgentPerformanceRecord]) -> None:
        self._append_many("agent_performance_records", records)

    def append_failure_patterns(self, records: list[FailurePatternRecord]) -> None:
        self._append_many("failure_patterns", records)

    def append_success_patterns(self, records: list[SuccessPatternRecord]) -> None:
        self._append_many("success_patterns", records)

    def append_evolution_evidence_packs(self, records: list[EvolutionEvidencePack]) -> None:
        self._append_many("evolution_evidence_packs", records)

    def append_evolution_outcome(self, record: EvolutionOutcomeRecord) -> None:
        self._append("evolution_outcomes", record)

    def list_failure_patterns(self, limit: int = 200) -> list[FailurePatternRecord]:
        return self._read_model_list("failure_patterns", FailurePatternRecord, limit=limit)

    def list_success_patterns(self, limit: int = 200) -> list[SuccessPatternRecord]:
        return self._read_model_list("success_patterns", SuccessPatternRecord, limit=limit)

    def list_agent_performance(self, *, agent_id: str | None = None, limit: int = 200) -> list[AgentPerformanceRecord]:
        records = self._read_model_list("agent_performance_records", AgentPerformanceRecord, limit=limit)
        if agent_id:
            records = [record for record in records if record.agent_id == agent_id]
        return records[-limit:]

    def list_evolution_outcomes(self, *, target_id: str | None = None, limit: int = 100) -> list[EvolutionOutcomeRecord]:
        records = self._read_model_list("evolution_outcomes", EvolutionOutcomeRecord, limit=limit * 4)
        if target_id:
            records = [record for record in records if record.target_id == target_id]
        return records[-limit:]

    def list_evolution_packs(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        limit: int = 100,
    ) -> list[EvolutionEvidencePack]:
        records = self._read_model_list("evolution_evidence_packs", EvolutionEvidencePack, limit=limit * 4)
        if target_type:
            records = [record for record in records if record.target_type == target_type]
        if target_id:
            records = [record for record in records if record.target_id == target_id]
        records.sort(key=lambda item: (item.priority, item.created_at), reverse=True)
        return records[:limit]

    def read_run_artifact(self, run_id: str, name: str) -> Any:
        path = self.run_knowledge_dir(run_id) / f"{self._safe_id(name)}.json"
        if not path.exists() and name.endswith(".json"):
            path = self.run_knowledge_dir(run_id) / self._safe_id(name)
        return json.loads(path.read_text(encoding="utf-8"))

    def _append_many(self, key: str, records: list[BaseModel]) -> None:
        if not records:
            return
        path = self.memory_root / self.FILE_MAP[key]
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, default=str) + "\n")

    def _append(self, key: str, record: BaseModel) -> None:
        self._append_many(key, [record])

    def _read_model_list(self, key: str, model: type[T], *, limit: int) -> list[T]:
        path = self.memory_root / self.FILE_MAP[key]
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        records: list[T] = []
        for line in lines[-max(limit, 1):]:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                records.append(model.model_validate(payload))
            except Exception:
                continue
        return records

    @staticmethod
    def _safe_id(value: str) -> str:
        clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value).strip())
        if not clean:
            raise ValueError("empty id")
        return clean
