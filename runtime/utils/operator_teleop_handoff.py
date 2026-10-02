"""Server-owned lifecycle for cycle-bound operator teleop handoffs."""

from __future__ import annotations

import asyncio
import copy
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlencode


HANDOFF_SCHEMA = "operator_teleop_handoff.v1"


class OperatorTeleopHandoffError(ValueError):
    """Stable fail-closed error for invalid handoff transitions."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class OperatorTeleopHandoffRegistry:
    """Keep pending teleop handoffs in server memory while the run coroutine waits."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _public(record: Mapping[str, Any]) -> dict[str, Any]:
        return copy.deepcopy({key: value for key, value in record.items() if key != "_event"})

    def create(
        self,
        *,
        run_id: str,
        cycle_index: int,
        specimen_id: str,
        candidate_id: str,
        materialization_evidence: Mapping[str, Any] | None = None,
        require_materialization: bool = False,
    ) -> dict[str, Any]:
        if not run_id or not specimen_id or not candidate_id or cycle_index < 1:
            raise OperatorTeleopHandoffError("TELEOP_HANDOFF_IDENTITY_INVALID")
        evidence = dict(materialization_evidence or {})
        if require_materialization and not (
            evidence.get("status") == "confirmed" and evidence.get("fresh") is True
        ):
            raise OperatorTeleopHandoffError("EXTERNAL_SPECIMEN_MATERIALIZATION_REQUIRED")
        token = secrets.token_urlsafe(32)
        query = urlencode({"handoff_token": token, "run_id": run_id})
        record = {
            "schema": HANDOFF_SCHEMA,
            "status": "pending_operator_teleop_handoff",
            "run_id": run_id,
            "cycle_index": int(cycle_index),
            "specimen_id": specimen_id,
            "candidate_id": candidate_id,
            "source_stage": "manipulation",
            "target_stage": "lab_equipment",
            "source_actuation_performed": False,
            "target_device": "utm",
            "handoff_strategy": "operator_teleop",
            "handoff_token": token,
            "popup_url": f"/lerobot?{query}#teleoperation-card",
            "materialization_evidence": evidence,
            "created_at": _now(),
            "_event": asyncio.Event(),
        }
        with self._lock:
            self._records[(run_id, token)] = record
        return self._public(record)

    def _record(self, run_id: str, handoff_token: str) -> dict[str, Any]:
        record = self._records.get((str(run_id), str(handoff_token)))
        if record is None:
            raise OperatorTeleopHandoffError("TELEOP_HANDOFF_NOT_FOUND")
        return record

    def status(self, run_id: str, handoff_token: str) -> dict[str, Any]:
        with self._lock:
            return self._public(self._record(run_id, handoff_token))

    def event(self, run_id: str, handoff_token: str) -> asyncio.Event:
        with self._lock:
            return self._record(run_id, handoff_token)["_event"]

    def bind_session(
        self,
        *,
        run_id: str,
        handoff_token: str,
        teleop_session_id: str,
    ) -> dict[str, Any]:
        """Bind the one teleop session started from this handoff popup."""
        if not teleop_session_id:
            raise OperatorTeleopHandoffError("TELEOP_SESSION_ID_REQUIRED")
        with self._lock:
            record = self._record(run_id, handoff_token)
            if record["status"] != "pending_operator_teleop_handoff":
                raise OperatorTeleopHandoffError("TELEOP_HANDOFF_ALREADY_CONSUMED")
            existing = str(record.get("teleop_session_id") or "")
            if existing and existing != teleop_session_id:
                raise OperatorTeleopHandoffError("TELEOP_SESSION_MISMATCH")
            record["teleop_session_id"] = teleop_session_id
            record["teleop_started_at"] = record.get("teleop_started_at") or _now()
            return self._public(record)

    def confirm(
        self,
        *,
        run_id: str,
        handoff_token: str,
        teleop_session_id: str,
        teleop_evidence: Mapping[str, Any],
        confirmed_by: str,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._record(run_id, handoff_token)
            if record["status"] != "pending_operator_teleop_handoff":
                raise OperatorTeleopHandoffError("TELEOP_HANDOFF_ALREADY_CONSUMED")
            if not teleop_session_id:
                raise OperatorTeleopHandoffError("TELEOP_SESSION_ID_REQUIRED")
            if str(record.get("teleop_session_id") or "") != teleop_session_id:
                raise OperatorTeleopHandoffError("TELEOP_SESSION_MISMATCH")
            evidence = dict(teleop_evidence or {})
            evidence_session = str(evidence.get("session_id") or teleop_session_id)
            if evidence_session != teleop_session_id:
                raise OperatorTeleopHandoffError("TELEOP_SESSION_MISMATCH")
            status = str(evidence.get("status") or "").upper()
            if status not in {"STOPPED", "TELEOP_STOPPED", "COMPLETED"}:
                raise OperatorTeleopHandoffError("TELEOP_SESSION_ACTIVE")
            port_released = evidence.get("port_released") is True
            camera_returned = (
                evidence.get("camera_returned_to_vision") is True
                or evidence.get("camera_returned_to_vla") is True
            )
            if not port_released or not camera_returned:
                raise OperatorTeleopHandoffError("TELEOP_RESOURCES_NOT_RELEASED")
            record.update(
                {
                    "status": "operator_confirmed",
                    "teleop_session_id": teleop_session_id,
                    "teleop_started_at": evidence.get("teleop_started_at") or evidence.get("started_at"),
                    "teleop_stopped_at": evidence.get("teleop_stopped_at") or evidence.get("stopped_at") or _now(),
                    "teleop_stop_verified": True,
                    "robot_port_released": True,
                    "camera_returned_to_vision": True,
                    "confirmed_by": str(confirmed_by or "local_operator"),
                    "confirmed_at": _now(),
                }
            )
            record["_event"].set()
            return self._public(record)

    def attach_vision_verification(
        self,
        *,
        run_id: str,
        handoff_token: str,
        vision_verification: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            record = self._record(run_id, handoff_token)
            if record["status"] != "operator_confirmed":
                raise OperatorTeleopHandoffError("TELEOP_HANDOFF_NOT_CONFIRMED")
            verification = dict(vision_verification)
            confirmed = bool(
                verification.get("fresh") is True
                and verification.get("evidence_exists") is True
                and verification.get("identity_matches") is True
                and (
                    verification.get("detected") is True
                    or verification.get("status") == "confirmed"
                )
            )
            if not confirmed:
                record["status"] = "blocked"
                record["failure_code"] = "UTM_VISION_VERIFICATION_FAILED"
            else:
                record["status"] = "confirmed"
                record["vision_verification"] = verification
                record["completed_at"] = _now()
            return self._public(record)

    def cancel_run(self, run_id: str, *, reason: str) -> list[dict[str, Any]]:
        cancelled: list[dict[str, Any]] = []
        with self._lock:
            for (record_run_id, _), record in self._records.items():
                if record_run_id != run_id or record["status"] in {"confirmed", "cancelled", "blocked"}:
                    continue
                record.update(
                    {
                        "status": "cancelled",
                        "failure_code": "TELEOP_HANDOFF_CANCELLED",
                        "cancel_reason": reason,
                        "cancelled_at": _now(),
                    }
                )
                record["_event"].set()
                cancelled.append(self._public(record))
        return cancelled


__all__ = ["HANDOFF_SCHEMA", "OperatorTeleopHandoffError", "OperatorTeleopHandoffRegistry"]
