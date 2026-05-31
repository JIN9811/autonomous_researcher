"""Trace collection for ATR self-evolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import EvolutionTrace


@dataclass(slots=True)
class TraceCollector:
    run_root: Path

    def latest_run_ids(self, limit: int = 12) -> list[str]:
        if not self.run_root.exists():
            return []
        run_dirs = [path for path in self.run_root.iterdir() if path.is_dir() and path.name.startswith("run-")]
        run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return [path.name for path in run_dirs[: max(0, limit)]]

    def run_dir(self, run_id: str) -> Path:
        safe = self._safe_run_id(run_id)
        path = (self.run_root / safe).resolve()
        root = self.run_root.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Unsafe run_id={run_id}") from exc
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Unknown run_id={run_id}")
        return path

    def collect(self, run_ids: list[str]) -> list[EvolutionTrace]:
        ids = run_ids or self.latest_run_ids(limit=3)
        traces: list[EvolutionTrace] = []
        for run_id in ids:
            traces.append(self.collect_one(run_id))
        return traces

    def collect_one(self, run_id: str) -> EvolutionTrace:
        run_dir = self.run_dir(run_id)
        events = self._read_events(run_dir / "structured.jsonl")
        artifacts = self._artifact_paths(run_dir)
        human_feedback = [event for event in events if "approval" in str(event.get("event_type") or event.get("type") or "")]
        graph_id = self._first_string(events, "graph_id") or self._first_payload_string(events, "graph_id")
        graph_version = self._first_string(events, "graph_version") or self._first_payload_string(events, "graph_version")
        metrics = self._metrics(events, artifacts)
        knowledge_packs = self._knowledge_evidence_packs(run_dir)
        metrics["knowledge_evidence_pack_count"] = len(knowledge_packs)
        metrics["knowledge_evidence_pack_ids"] = [str(item.get("pack_id") or "") for item in knowledge_packs if isinstance(item, dict)]
        return EvolutionTrace(
            trace_id=f"trace-{run_id}",
            run_id=run_id,
            graph_id=graph_id,
            graph_version=graph_version,
            events=events,
            metrics=metrics,
            artifacts=artifacts,
            human_feedback=human_feedback,
        )


    @staticmethod
    def _knowledge_evidence_packs(run_dir: Path) -> list[dict[str, Any]]:
        path = run_dir / "knowledge" / "evolution_evidence_packs.json"
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, dict) and isinstance(raw.get("evidence_packs"), list):
            return [item for item in raw["evidence_packs"] if isinstance(item, dict)]
        return []

    @staticmethod
    def _safe_run_id(run_id: str) -> str:
        clean = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(run_id).strip())
        if not clean or clean != run_id:
            raise ValueError(f"Unsafe run_id={run_id}")
        return clean

    @staticmethod
    def _read_events(path: Path) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if not path.exists():
            return events
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                events.append(raw)
        return events

    @staticmethod
    def _artifact_paths(run_dir: Path) -> list[str]:
        artifacts: list[str] = []
        for path in sorted(run_dir.rglob("*")):
            if path.is_file() and path.name not in {"structured.jsonl", "summary.log"}:
                artifacts.append(path.relative_to(run_dir).as_posix())
        return artifacts

    @staticmethod
    def _first_string(events: list[dict[str, Any]], key: str) -> str | None:
        for event in events:
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _first_payload_string(events: list[dict[str, Any]], key: str) -> str | None:
        for event in events:
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            value = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _metrics(events: list[dict[str, Any]], artifacts: list[str]) -> dict[str, Any]:
        event_types: dict[str, int] = {}
        stages: dict[str, int] = {}
        errors = 0
        warnings = 0
        approvals = 0
        for event in events:
            event_type = str(event.get("type") or event.get("event_type") or "unknown")
            level = str(event.get("level") or event.get("severity") or "").lower()
            event_types[event_type] = event_types.get(event_type, 0) + 1
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            stage = str(event.get("stage") or payload.get("node_id") or payload.get("stage") or "") if isinstance(payload, dict) else ""
            if stage:
                stages[stage] = stages.get(stage, 0) + 1
            if "error" in level or "failed" in event_type or "error" in event_type:
                errors += 1
            if "warn" in level or "warning" in event_type:
                warnings += 1
            if "approval" in event_type:
                approvals += 1
        return {
            "event_count": len(events),
            "artifact_count": len(artifacts),
            "error_count": errors,
            "warning_count": warnings,
            "approval_count": approvals,
            "event_types": event_types,
            "stage_counts": stages,
        }
