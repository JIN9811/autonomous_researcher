"""Validated persistence and resolution for test-mode execution profiles."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


STORE_SCHEMA = "test_mode_execution_profiles.v1"
RESOLVED_SCHEMA = "resolved_test_mode_execution_profile.v1"
PROFILE_IDS = ("virtual_bridge", "installed_printer", "physical_print")
AGENT_POLICY_KEYS = {
    "specimen": "printer",
    "vision": "vision",
    "manipulation": "manipulation",
    "lab_equipment": "lab_equipment",
}


class TestModeExecutionProfileError(ValueError):
    """Base error for test-mode execution profile operations."""


class TestModeExecutionProfileValidationError(TestModeExecutionProfileError):
    """Raised when profile data violates the strict schema or safety rules."""


class TestModeExecutionProfileConflictError(TestModeExecutionProfileError):
    """Raised when optimistic revision control detects a stale writer."""


def _agent_modes(mode: str) -> dict[str, dict[str, str]]:
    return {key: {"device_mode": mode} for key in AGENT_POLICY_KEYS}


BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "virtual_bridge": {
        "agents": _agent_modes("virtual"),
        "printer_flow": {
            "print_body": "execute",
            "cooling_wait": "execute",
            "auto_ejection": True,
        },
        "handoff": {"strategy": "operator_teleop"},
    },
    "installed_printer": {
        "agents": _agent_modes("real"),
        "printer_flow": {
            "print_body": "skip",
            "cooling_wait": "skip",
            "auto_ejection": True,
        },
        "handoff": {"strategy": "operator_teleop"},
    },
    "physical_print": {
        "agents": _agent_modes("real"),
        "printer_flow": {
            "print_body": "execute",
            "cooling_wait": "execute",
            "auto_ejection": True,
        },
        "handoff": {"strategy": "operator_teleop"},
    },
}


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _document_hash(document: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in document.items() if key not in {"sha256", "warnings"}}
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_exact_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    keys = set(value)
    if keys != allowed:
        missing = sorted(allowed - keys)
        unknown = sorted(keys - allowed)
        raise TestModeExecutionProfileValidationError(
            f"{label} fields mismatch: missing={missing}, unknown={unknown}"
        )


def validate_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, Mapping):
        raise TestModeExecutionProfileValidationError("profile must be an object")
    _validate_exact_keys(profile, {"agents", "printer_flow", "handoff"}, "profile")

    agents = profile.get("agents")
    if not isinstance(agents, Mapping):
        raise TestModeExecutionProfileValidationError("agents must be an object")
    _validate_exact_keys(agents, set(AGENT_POLICY_KEYS), "agents")
    normalized_agents: dict[str, dict[str, str]] = {}
    for agent_id in AGENT_POLICY_KEYS:
        agent = agents.get(agent_id)
        if not isinstance(agent, Mapping):
            raise TestModeExecutionProfileValidationError(f"agents.{agent_id} must be an object")
        _validate_exact_keys(agent, {"device_mode"}, f"agents.{agent_id}")
        mode = agent.get("device_mode")
        if mode not in {"virtual", "real"}:
            raise TestModeExecutionProfileValidationError(
                f"agents.{agent_id}.device_mode must be virtual or real"
            )
        normalized_agents[agent_id] = {"device_mode": str(mode)}

    printer_flow = profile.get("printer_flow")
    if not isinstance(printer_flow, Mapping):
        raise TestModeExecutionProfileValidationError("printer_flow must be an object")
    _validate_exact_keys(
        printer_flow,
        {"print_body", "cooling_wait", "auto_ejection"},
        "printer_flow",
    )
    print_body = printer_flow.get("print_body")
    cooling_wait = printer_flow.get("cooling_wait")
    auto_ejection = printer_flow.get("auto_ejection")
    if print_body not in {"execute", "skip"}:
        raise TestModeExecutionProfileValidationError("printer_flow.print_body must be execute or skip")
    if cooling_wait not in {"execute", "skip"}:
        raise TestModeExecutionProfileValidationError("printer_flow.cooling_wait must be execute or skip")
    if type(auto_ejection) is not bool:
        raise TestModeExecutionProfileValidationError("printer_flow.auto_ejection must be boolean")
    if print_body == "execute" and cooling_wait == "skip":
        raise TestModeExecutionProfileValidationError(
            "cooling_wait may be skipped only when print_body is skipped"
        )
    if (
        normalized_agents["specimen"]["device_mode"] == "real"
        and print_body == "skip"
        and not auto_ejection
    ):
        raise TestModeExecutionProfileValidationError(
            "a real printer with skipped print body requires auto_ejection"
        )
    if (
        normalized_agents["vision"]["device_mode"] == "virtual"
        and normalized_agents["manipulation"]["device_mode"] == "real"
    ):
        raise TestModeExecutionProfileValidationError(
            "real manipulation requires real Vision pose evidence"
        )

    handoff = profile.get("handoff")
    if not isinstance(handoff, Mapping):
        raise TestModeExecutionProfileValidationError("handoff must be an object")
    _validate_exact_keys(handoff, {"strategy"}, "handoff")
    if handoff.get("strategy") != "operator_teleop":
        raise TestModeExecutionProfileValidationError("handoff.strategy must be operator_teleop")

    return {
        "agents": normalized_agents,
        "printer_flow": {
            "print_body": str(print_body),
            "cooling_wait": str(cooling_wait),
            "auto_ejection": auto_ejection,
        },
        "handoff": {"strategy": "operator_teleop"},
    }


def _merge_profile(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(dict(base))
    for key, value in override.items():
        if key not in merged:
            raise TestModeExecutionProfileValidationError(f"unknown profile override field: {key}")
        if isinstance(value, Mapping) and isinstance(merged[key], Mapping):
            for child_key, child_value in value.items():
                if child_key not in merged[key]:
                    raise TestModeExecutionProfileValidationError(
                        f"unknown profile override field: {key}.{child_key}"
                    )
                if isinstance(child_value, Mapping) and isinstance(merged[key][child_key], Mapping):
                    merged[key][child_key].update(copy.deepcopy(dict(child_value)))
                else:
                    merged[key][child_key] = copy.deepcopy(child_value)
        else:
            merged[key] = copy.deepcopy(value)
    return validate_profile(merged)


class TestModeExecutionProfileStore:
    """Thread-safe profile store with strict validation and atomic writes."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()

    @staticmethod
    def _default_document() -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema": STORE_SCHEMA,
            "revision": 0,
            "updated_at": None,
            "profiles": copy.deepcopy(BUILTIN_PROFILES),
        }
        document["sha256"] = _document_hash(document)
        return document

    @staticmethod
    def _validate_document(raw: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise TestModeExecutionProfileValidationError("profile store must be an object")
        allowed = {"schema", "revision", "updated_at", "profiles", "sha256"}
        _validate_exact_keys(raw, allowed, "profile store")
        if raw.get("schema") != STORE_SCHEMA:
            raise TestModeExecutionProfileValidationError("unsupported profile store schema")
        revision = raw.get("revision")
        if type(revision) is not int or revision < 0:
            raise TestModeExecutionProfileValidationError("revision must be a non-negative integer")
        updated_at = raw.get("updated_at")
        if updated_at is not None and not isinstance(updated_at, str):
            raise TestModeExecutionProfileValidationError("updated_at must be a string or null")
        profiles = raw.get("profiles")
        if not isinstance(profiles, Mapping):
            raise TestModeExecutionProfileValidationError("profiles must be an object")
        _validate_exact_keys(profiles, set(PROFILE_IDS), "profiles")
        document: dict[str, Any] = {
            "schema": STORE_SCHEMA,
            "revision": revision,
            "updated_at": updated_at,
            "profiles": {profile_id: validate_profile(profiles[profile_id]) for profile_id in PROFILE_IDS},
        }
        expected_hash = _document_hash(document)
        if raw.get("sha256") != expected_hash:
            raise TestModeExecutionProfileValidationError("profile store hash mismatch")
        document["sha256"] = expected_hash
        return document

    def _read(self) -> dict[str, Any]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return self._default_document()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return self._validate_document(raw)
        except (OSError, json.JSONDecodeError, TestModeExecutionProfileValidationError) as exc:
            fallback = self._default_document()
            fallback["warnings"] = [
                {"code": "PROFILE_STORE_INVALID", "message": str(exc)}
            ]
            return fallback

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._read())

    def _write(self, document: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = copy.deepcopy(document)
        document.pop("warnings", None)
        document["sha256"] = _document_hash(document)
        encoded = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return copy.deepcopy(document)

    def _assert_revision(self, document: Mapping[str, Any], expected_revision: int) -> None:
        if type(expected_revision) is not int or expected_revision < 0:
            raise TestModeExecutionProfileValidationError(
                "expected_revision must be a non-negative integer"
            )
        if document["revision"] != expected_revision:
            raise TestModeExecutionProfileConflictError(
                f"stale profile revision: expected {expected_revision}, current {document['revision']}"
            )

    def save_profile(
        self,
        profile_id: str,
        profile: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        if profile_id not in PROFILE_IDS:
            raise TestModeExecutionProfileValidationError(f"unknown profile_id: {profile_id}")
        normalized = validate_profile(profile)
        with self._lock:
            document = self._read()
            self._assert_revision(document, expected_revision)
            document["profiles"][profile_id] = normalized
            document["revision"] += 1
            document["updated_at"] = _utc_now()
            return self._write(document)

    def reset(self, profile_id: str | None, *, expected_revision: int) -> dict[str, Any]:
        if profile_id is not None and profile_id not in PROFILE_IDS:
            raise TestModeExecutionProfileValidationError(f"unknown profile_id: {profile_id}")
        with self._lock:
            document = self._read()
            self._assert_revision(document, expected_revision)
            if profile_id is None:
                document["profiles"] = copy.deepcopy(BUILTIN_PROFILES)
            else:
                document["profiles"][profile_id] = copy.deepcopy(BUILTIN_PROFILES[profile_id])
            document["revision"] += 1
            document["updated_at"] = _utc_now()
            return self._write(document)

    def resolve(
        self,
        profile_id: str,
        override: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if profile_id not in PROFILE_IDS:
            raise TestModeExecutionProfileValidationError(f"unknown profile_id: {profile_id}")
        snapshot = self.snapshot()
        profile = validate_profile(snapshot["profiles"][profile_id])
        if override:
            profile = _merge_profile(profile, override)
        policy = {
            policy_key: (
                "execute"
                if profile["agents"][agent_id]["device_mode"] == "real"
                else "preflight_only"
            )
            for agent_id, policy_key in AGENT_POLICY_KEYS.items()
        }
        print_body_skipped = profile["printer_flow"]["print_body"] == "skip"
        physical_specimen_created = policy["printer"] == "execute" and not print_body_skipped
        resolved = {
            "schema": RESOLVED_SCHEMA,
            "profile_id": profile_id,
            "source_revision": snapshot["revision"],
            "source_sha256": snapshot["sha256"],
            "resolved_at": _utc_now(),
            **copy.deepcopy(profile),
            "execution_policy": policy,
            "derived": {
                "operator_teleop_required": (
                    policy["manipulation"] == "preflight_only"
                    and policy["lab_equipment"] == "execute"
                ),
                "external_specimen_materialization_required": (
                    not physical_specimen_created and policy["lab_equipment"] == "execute"
                ),
                "physical_specimen_created_by_printer": physical_specimen_created,
            },
        }
        if snapshot.get("warnings"):
            resolved["warnings"] = copy.deepcopy(snapshot["warnings"])
        return resolved


__all__ = [
    "AGENT_POLICY_KEYS",
    "BUILTIN_PROFILES",
    "PROFILE_IDS",
    "RESOLVED_SCHEMA",
    "STORE_SCHEMA",
    "TestModeExecutionProfileConflictError",
    "TestModeExecutionProfileError",
    "TestModeExecutionProfileStore",
    "TestModeExecutionProfileValidationError",
    "validate_profile",
]
