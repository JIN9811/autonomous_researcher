"""Canonical Linux-owned lifecycle and evidence store for Lab Equipment runs."""

from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any
from uuid import uuid4


EXECUTION_SCHEMA = "atr.equipment_execution.v1"
PROJECTION_SCHEMA = "atr.equipment_execution_projection.v1"
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+\-]{0,191}$")
_EXECUTION_ID = re.compile(r"^equipment-[0-9a-f]{32}$")
_LIFECYCLE_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_DEFAULT_TRANSITIONS = {
    "RESOLVING": frozenset({"RESOLVING", "PREFLIGHT", "BLOCKED", "ABORTED", "ESCALATED"}),
    "PREFLIGHT": frozenset({"PREFLIGHT", "EXECUTING", "BLOCKED", "ABORTED", "ESCALATED"}),
    "EXECUTING": frozenset({"EXECUTING", "VERIFYING", "RECOVERING", "EFFECT_UNKNOWN", "BLOCKED", "ABORTED", "ESCALATED"}),
    "VERIFYING": frozenset({"VERIFYING", "EXECUTING", "RECOVERING", "COMPLETED", "EFFECT_UNKNOWN", "BLOCKED", "ABORTED", "ESCALATED"}),
    "RECOVERING": frozenset({"RECOVERING", "EXECUTING", "VERIFYING", "EFFECT_UNKNOWN", "BLOCKED", "ABORTED", "ESCALATED"}),
    "COMPLETED": frozenset({"COMPLETED"}),
    "BLOCKED": frozenset({"BLOCKED", "PREFLIGHT", "RECOVERING", "ABORTED", "ESCALATED"}),
    "ABORTED": frozenset({"ABORTED"}),
    "ESCALATED": frozenset({"ESCALATED", "RECOVERING", "ABORTED"}),
    "EFFECT_UNKNOWN": frozenset({"EFFECT_UNKNOWN"}),
}
_ROOT_LOCKS_GUARD = RLock()
_ROOT_LOCKS: dict[str, RLock] = {}


def _shared_root_lock(root: Path) -> RLock:
    key = str(root)
    with _ROOT_LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(key, RLock())


class EquipmentRuntimeContractError(ValueError):
    """Raised when an Equipment execution identity or lifecycle is invalid."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_identity(value: Any, field: str) -> str:
    clean = str(value or "").strip()
    if not _IDENTITY.fullmatch(clean):
        raise EquipmentRuntimeContractError(f"invalid {field}: {clean!r}")
    return clean


def _safe_execution_id(value: Any) -> str:
    clean = str(value or "").strip()
    if not _EXECUTION_ID.fullmatch(clean):
        raise EquipmentRuntimeContractError(f"invalid execution_id: {clean!r}")
    return clean


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_lifecycle_contract(value: dict[str, Any] | None) -> dict[str, list[str]]:
    source = value if isinstance(value, dict) and value else _DEFAULT_TRANSITIONS
    contract: dict[str, list[str]] = {}
    for raw_source, raw_targets in source.items():
        state = str(raw_source or "").strip().upper()
        if not _LIFECYCLE_NAME.fullmatch(state):
            raise EquipmentRuntimeContractError(f"invalid lifecycle state: {raw_source!r}")
        if not isinstance(raw_targets, (list, tuple, set, frozenset)):
            raise EquipmentRuntimeContractError(f"lifecycle targets must be a list: {state}")
        targets = sorted({str(item or "").strip().upper() for item in raw_targets})
        if not targets or any(not _LIFECYCLE_NAME.fullmatch(item) for item in targets):
            raise EquipmentRuntimeContractError(f"invalid lifecycle targets: {state}")
        contract[state] = targets
    if "RESOLVING" not in contract:
        raise EquipmentRuntimeContractError("lifecycle contract must define RESOLVING")
    referenced = {target for targets in contract.values() for target in targets}
    missing = sorted(referenced.difference(contract))
    if missing:
        raise EquipmentRuntimeContractError(f"lifecycle contract has undefined states: {', '.join(missing)}")
    return contract


def _json_safe(value: Any, seen: set[int] | None = None) -> Any:
    """Detach runtime artifacts from response object graphs before persistence."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    active = seen if seen is not None else set()
    marker = id(value)
    if marker in active:
        return "<circular-reference-omitted>"
    if isinstance(value, dict):
        active.add(marker)
        result = {str(key): _json_safe(item, active) for key, item in value.items()}
        active.remove(marker)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        active.add(marker)
        result = [_json_safe(item, active) for item in value]
        active.remove(marker)
        return result
    return str(value)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EquipmentRuntimeContractError(f"invalid Equipment runtime artifact: {path}") from exc
    if not isinstance(value, dict):
        raise EquipmentRuntimeContractError(f"Equipment runtime artifact must be an object: {path}")
    return value


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class EquipmentRuntimeService:
    """Own the single authoritative execution record for every Equipment run."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.execution_root = self.root / "executions"
        self.index_path = self.root / "sequence_index.json"
        self.process_lock_path = self.root / ".runtime.lock"
        self._lock = _shared_root_lock(self.root)

    @contextmanager
    def _process_lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.process_lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def begin(
        self,
        *,
        sequence_id: str,
        run_id: str,
        experiment_id: str,
        specimen_id: str,
        profile_id: str,
        mode: str,
        worker: dict[str, Any],
        execution_ref: dict[str, Any],
        model_snapshot: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        lifecycle_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        identity = {
            "run_id": _safe_identity(run_id, "run_id"),
            "experiment_id": _safe_identity(experiment_id, "experiment_id"),
            "specimen_id": _safe_identity(specimen_id, "specimen_id"),
            "sequence_id": _safe_identity(sequence_id, "sequence_id"),
        }
        safe_profile = _safe_identity(profile_id, "profile_id")
        clean_mode = str(mode or "").strip().lower()
        if clean_mode not in {"test", "live", "virtual"}:
            raise EquipmentRuntimeContractError(f"invalid mode: {mode!r}")
        clean_worker = deepcopy(worker) if isinstance(worker, dict) else {}
        clean_ref = deepcopy(execution_ref) if isinstance(execution_ref, dict) else {}
        if not str(clean_worker.get("worker_id") or "").strip():
            raise EquipmentRuntimeContractError("worker.worker_id is required")
        if str(clean_ref.get("type") or "") not in {"program", "skill"}:
            raise EquipmentRuntimeContractError("execution_ref.type must be program or skill")
        clean_lifecycle_contract = _normalize_lifecycle_contract(lifecycle_contract)
        sequence_hash = _canonical_hash(
            {
                "identity": identity,
                "profile_id": safe_profile,
                "mode": clean_mode,
                "worker": clean_worker,
                "execution_ref": clean_ref,
                "lifecycle_contract": clean_lifecycle_contract,
            }
        )
        with self._lock, self._process_lock():
            index = _read_object(self.index_path) if self.index_path.exists() else {}
            existing_id = str(index.get(sequence_hash) or "")
            if existing_id:
                existing = self.get(existing_id)
                if str(existing.get("lifecycle") or "").upper() != "BLOCKED":
                    existing["idempotent"] = True
                    return existing
            execution_id = f"equipment-{uuid4().hex}"
            now = _now_iso()
            state = {
                "schema": EXECUTION_SCHEMA,
                "execution_id": execution_id,
                "identity": identity,
                "profile_id": safe_profile,
                "mode": clean_mode,
                "worker": clean_worker,
                "execution_ref": clean_ref,
                "lifecycle_contract": clean_lifecycle_contract,
                "lifecycle": "RESOLVING",
                "status": "resolving",
                "detail": "execution contract accepted",
                "evidence": [],
                "completion": {},
                "recovery": {},
                "handoff": {},
                "failure": {},
                "raw_result": {},
                "model_snapshot": deepcopy(model_snapshot or {}),
                "metadata": deepcopy(metadata or {}),
                "events": [
                    {
                        "lifecycle": "RESOLVING",
                        "status": "resolving",
                        "detail": "execution contract accepted",
                        "at": now,
                    }
                ],
                "idempotent": False,
                "created_at": now,
                "updated_at": now,
            }
            state = _json_safe(state)
            _atomic_write(self._state_path(execution_id), state)
            index[sequence_hash] = execution_id
            _atomic_write(self.index_path, index)
            return deepcopy(state)

    def transition(self, execution_id: str, lifecycle: str, **updates: Any) -> dict[str, Any]:
        safe_id = _safe_execution_id(execution_id)
        target = str(lifecycle or "").strip().upper()
        with self._lock, self._process_lock():
            current = self.get(safe_id)
            contract = _normalize_lifecycle_contract(current.get("lifecycle_contract"))
            if target not in contract:
                raise EquipmentRuntimeContractError(f"invalid lifecycle: {lifecycle!r}")
            source = str(current.get("lifecycle") or "").upper()
            if target not in contract.get(source, []):
                raise EquipmentRuntimeContractError(f"invalid lifecycle transition: {source} -> {target}")
            now = _now_iso()
            incoming_evidence = updates.pop("evidence", None)
            if isinstance(incoming_evidence, list):
                known = {
                    _canonical_hash(item)
                    for item in current.get("evidence", [])
                    if isinstance(item, dict)
                }
                for item in incoming_evidence:
                    if isinstance(item, dict) and _canonical_hash(item) not in known:
                        current.setdefault("evidence", []).append(deepcopy(item))
                        known.add(_canonical_hash(item))
            for key, value in updates.items():
                current[key] = deepcopy(value)
            current["lifecycle"] = target
            current["status"] = str(updates.get("status") or target.lower())
            current["updated_at"] = now
            current["idempotent"] = False
            event = {
                "lifecycle": target,
                "status": current["status"],
                "detail": str(current.get("detail") or ""),
                "at": now,
            }
            if isinstance(current.get("failure"), dict) and current["failure"].get("failure_code"):
                event["failure_code"] = str(current["failure"]["failure_code"])
            current.setdefault("events", []).append(event)
            current = _json_safe(current)
            _atomic_write(self._state_path(safe_id), current)
            return deepcopy(current)

    def get(self, execution_id: str) -> dict[str, Any]:
        safe_id = _safe_execution_id(execution_id)
        path = self._state_path(safe_id)
        if not path.exists():
            raise EquipmentRuntimeContractError(f"Equipment execution not found: {safe_id}")
        return _read_object(path)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1000))
        if not self.execution_root.exists():
            return []
        executions = [
            _read_object(path)
            for path in self.execution_root.glob("*/state.json")
            if path.is_file()
        ]
        executions.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return executions[:bounded]

    def latest(
        self,
        *,
        run_id: str = "",
        profile_id: str = "",
        execution_id: str = "",
    ) -> dict[str, Any] | None:
        """Return the latest execution matching the requested runtime identity."""
        requested_run = str(run_id or "").strip()
        requested_profile = str(profile_id or "").strip()
        requested_execution = str(execution_id or "").strip()
        executions = self.list(limit=1000)
        if requested_run:
            executions = [
                item
                for item in executions
                if str((item.get("identity") or {}).get("run_id") or "") == requested_run
            ]
        if requested_profile:
            executions = [item for item in executions if str(item.get("profile_id") or "") == requested_profile]
        if requested_execution:
            executions = [item for item in executions if str(item.get("execution_id") or "") == requested_execution]
        return executions[0] if executions else None

    @staticmethod
    def project(execution: dict[str, Any]) -> dict[str, Any]:
        completion = execution.get("completion") if isinstance(execution.get("completion"), dict) else {}
        handoff = execution.get("handoff") if isinstance(execution.get("handoff"), dict) else {}
        failure = execution.get("failure") if isinstance(execution.get("failure"), dict) else {}
        status = str(completion.get("status") or execution.get("status") or "unknown")
        return {
            "schema": PROJECTION_SCHEMA,
            "execution_id": str(execution.get("execution_id") or ""),
            "lifecycle": str(execution.get("lifecycle") or ""),
            "status": status,
            "profile_id": str(execution.get("profile_id") or ""),
            "mode": str(execution.get("mode") or ""),
            "worker": deepcopy(execution.get("worker") or {}),
            "execution_ref": deepcopy(execution.get("execution_ref") or {}),
            "evidence_count": len(execution.get("evidence") or []),
            "ready_for_analysis": str(handoff.get("status") or "") == "ready_for_analysis",
            "failure_code": str(failure.get("failure_code") or ""),
            "updated_at": str(execution.get("updated_at") or ""),
        }

    def _state_path(self, execution_id: str) -> Path:
        return self.execution_root / _safe_execution_id(execution_id) / "state.json"


__all__ = [
    "EXECUTION_SCHEMA",
    "PROJECTION_SCHEMA",
    "EquipmentRuntimeContractError",
    "EquipmentRuntimeService",
]
