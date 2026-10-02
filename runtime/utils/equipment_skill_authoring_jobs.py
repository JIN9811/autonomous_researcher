"""Persistent progress records for asynchronous Lab Equipment Skill authoring."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


JOB_SCHEMA = "atr.equipment_skill_authoring_job.v1"
TERMINAL_STATUSES = frozenset({"COMPLETED", "STOPPED", "FAILED"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class EquipmentSkillAuthoringJobManager:
    """Own persisted authoring progress so browser refreshes do not lose state."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self._lock = RLock()

    def create(
        self,
        *,
        recording_id: str,
        skill_id: str,
        version: str,
        target_profile: str,
        bridge_id: str,
    ) -> dict[str, Any]:
        job_id = f"equipment-skill-job-{uuid4().hex}"
        now = _now_iso()
        job = {
            "schema": JOB_SCHEMA,
            "job_id": job_id,
            "operation": "authoring",
            "recording_id": str(recording_id),
            "skill_id": str(skill_id),
            "version": str(version),
            "target_profile": str(target_profile),
            "bridge_id": str(bridge_id),
            "status": "QUEUED",
            "stage": "PREPARING",
            "progress": 5,
            "status_text": "Preparing recording import",
            "stop_requested": False,
            "result": {},
            "error": {},
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            _atomic_write(self._path(job_id), job)
        return deepcopy(job)

    def create_deployment(
        self,
        *,
        skill_id: str,
        version: str,
        bridge_id: str,
    ) -> dict[str, Any]:
        job_id = f"equipment-skill-job-{uuid4().hex}"
        now = _now_iso()
        job = {
            "schema": JOB_SCHEMA,
            "job_id": job_id,
            "operation": "deployment",
            "recording_id": "",
            "skill_id": str(skill_id),
            "version": str(version),
            "target_profile": "",
            "bridge_id": str(bridge_id),
            "status": "QUEUED",
            "stage": "PREFLIGHT",
            "progress": 5,
            "status_text": "Preparing validated Skill deployment",
            "stop_requested": False,
            "result": {},
            "error": {},
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            _atomic_write(self._path(job_id), job)
        return deepcopy(job)

    def get(self, job_id: str) -> dict[str, Any]:
        path = self._path(job_id)
        with self._lock:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise KeyError(job_id) from exc
        if not isinstance(value, dict):
            raise KeyError(job_id)
        return value

    def update(
        self,
        job_id: str,
        *,
        stage: str,
        progress: int,
        status_text: str,
        status: str = "RUNNING",
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            if str(job.get("status") or "").upper() in TERMINAL_STATUSES:
                return job
            job.update(
                {
                    "stage": str(stage).upper(),
                    "progress": max(0, min(100, int(progress))),
                    "status_text": str(status_text),
                    "status": str(status).upper(),
                    "updated_at": _now_iso(),
                }
            )
            if result is not None:
                job["result"] = deepcopy(result)
            if error is not None:
                job["error"] = deepcopy(error)
            _atomic_write(self._path(job_id), job)
            return deepcopy(job)

    def request_stop(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            if str(job.get("status") or "").upper() in TERMINAL_STATUSES:
                return job
            job.update(
                {
                    "status": "STOPPING",
                    "status_text": "Stop requested; waiting for a safe stage boundary",
                    "stop_requested": True,
                    "updated_at": _now_iso(),
                }
            )
            _atomic_write(self._path(job_id), job)
            return deepcopy(job)

    def mark_stopped(self, job_id: str, status_text: str) -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            job.update(
                {
                    "stage": "STOPPED",
                    "status": "STOPPED",
                    "status_text": str(status_text),
                    "stop_requested": True,
                    "updated_at": _now_iso(),
                }
            )
            _atomic_write(self._path(job_id), job)
            return deepcopy(job)

    def _path(self, job_id: str) -> Path:
        clean = str(job_id or "").strip()
        if not clean.startswith("equipment-skill-job-") or not clean.removeprefix("equipment-skill-job-").isalnum():
            raise KeyError(clean)
        return self.root / f"{clean}.json"
