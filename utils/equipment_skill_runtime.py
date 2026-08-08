"""Versioned Equipment Skill contracts, storage, compilation, and runtime state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Iterable
from uuid import uuid4


SKILL_SCHEMA = "atr.equipment_skill.v1"
RECORDING_SCHEMA = "atr.equipment_recording.v1"
RECORDING_SCHEMAS = frozenset({RECORDING_SCHEMA, "atr.equipment_recording.v2"})
EXCEPTION_SCHEMA = "atr.equipment_skill_exception.v1"
RECOVERY_SCHEMA = "atr.equipment_skill_recovery.v1"
PROGRAM_SCHEMA = "atr.pyautogui_program.v1"
PROGRAM_ACTION_LIMIT = 100
IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
ALLOWED_RECOVERY_OPERATIONS = frozenset(
    {
        "focus_window",
        "screenshot",
        "assert_visible",
        "wait_until",
        "locate_image",
        "wait_until_image",
        "assert_text",
        "wait_until_text",
        "press",
        "hotkey",
        "wait",
        "log",
    }
)
EXECUTION_STATES = frozenset(
    {
        "RUNNING",
        "CHECKPOINT_VERIFY",
        "EXCEPTION",
        "RECOVERING",
        "RECOVERY_VERIFY",
        "RESUMED",
        "COMPLETED",
        "ESCALATED",
        "ABORTED",
    }
)


class SkillContractError(ValueError):
    """Raised when a Skill payload, identity, hash, or transition is invalid."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used by all Skill hashes."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _safe_identity(value: str, field: str) -> str:
    clean = str(value or "").strip()
    if not IDENTITY_PATTERN.fullmatch(clean):
        raise SkillContractError(f"invalid {field}: {clean!r}")
    return clean


def _safe_version(value: str) -> str:
    clean = str(value or "").strip()
    if not VERSION_PATTERN.fullmatch(clean):
        raise SkillContractError(f"invalid version: {clean!r}")
    return clean


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillContractError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise SkillContractError(f"JSON artifact must be an object: {path}")
    return value


def _printable_recorded_key(key: str) -> str | None:
    if key == "space":
        return " "
    if len(key) == 1 and key.isprintable():
        return key
    return None


def recording_capability_coverage(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize which replayable capability families a recording exercises."""
    action_by_kind = {
        "mouse_move": "move_to",
        "mouse_click": "click",
        "click": "click",
        "mouse_drag": "drag_to",
        "mouse_scroll": "scroll",
        "key_press": "press",
        "press": "press",
        "hotkey": "hotkey",
        "wait": "wait",
        "sleep": "wait",
        "checkpoint": "screenshot",
        "screenshot": "screenshot",
    }
    family_by_action = {
        "move_to": "mouse",
        "click": "mouse",
        "drag_to": "mouse",
        "scroll": "mouse",
        "press": "keyboard",
        "hotkey": "keyboard",
        "wait": "timing",
        "screenshot": "screen",
    }
    ignored = {"key_release", "recording_started", "recording_stopped", ""}
    actions: set[str] = set()
    families: set[str] = set()
    unsupported: set[str] = set()
    event_count = hotkey_count = drag_count = scroll_count = 0
    for raw_event in events:
        event_count += 1
        kind = str(dict(raw_event or {}).get("kind") or dict(raw_event or {}).get("type") or "").strip().lower()
        action = action_by_kind.get(kind)
        if action:
            actions.add(action)
            families.add(family_by_action[action])
            hotkey_count += int(kind == "hotkey")
            drag_count += int(kind == "mouse_drag")
            scroll_count += int(kind == "mouse_scroll")
        elif kind not in ignored:
            unsupported.add(kind)
    return {
        "actions": sorted(actions),
        "families": sorted(families),
        "event_count": event_count,
        "hotkey_count": hotkey_count,
        "drag_count": drag_count,
        "scroll_count": scroll_count,
        "unsupported_event_kinds": sorted(unsupported),
    }


def compile_recording_actions(
    events: Iterable[dict[str, Any]],
    *,
    visual_locator_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Translate redacted recording events into bounded bridge actions."""
    actions: list[dict[str, Any]] = []
    text_buffer: list[str] = []
    previous_mouse_at_ms = 0
    previous_executable_at_ms: int | None = None
    policy = dict(visual_locator_policy or {})
    image_first = str(policy.get("mode") or "").strip().lower() == "image_first"
    locator_required = image_first and policy.get("required_for_pointer_actions") is not False
    coordinate_fallback = bool(policy.get("coordinate_fallback", False))
    normalized_events = [dict(item or {}) for item in events]
    if image_first and sum(item.get("kind") in {"mouse_click", "click", "mouse_drag"} for item in normalized_events) > 200:
        raise SkillContractError("image-first recordings support at most 200 pointer events")
    locator_payload_bytes = 0

    def validated_candidates(raw_candidates: Any) -> list[dict[str, Any]]:
        nonlocal locator_payload_bytes
        if not isinstance(raw_candidates, list) or not 1 <= len(raw_candidates) <= 2:
            raise SkillContractError("visual locator candidates must contain one or two PNG crops")
        valid: list[dict[str, Any]] = []
        for raw_candidate in raw_candidates:
            if not isinstance(raw_candidate, dict):
                raise SkillContractError("visual locator candidate must be an object")
            candidate = deepcopy(raw_candidate)
            encoded = str(candidate.get("png_base64") or "")
            expected_sha = str(candidate.get("sha256") or "").lower()
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except Exception as exc:
                raise SkillContractError("visual locator png_base64 is invalid") from exc
            if not decoded.startswith(b"\x89PNG\r\n\x1a\n") or len(decoded) > 256 * 1024:
                raise SkillContractError("visual locator must be a PNG no larger than 256 KiB")
            if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or hashlib.sha256(decoded).hexdigest() != expected_sha:
                raise SkillContractError("visual locator sha256 does not match PNG data")
            width, height = int(candidate.get("width", 0)), int(candidate.get("height", 0))
            if not 1 <= width <= 512 or not 1 <= height <= 512:
                raise SkillContractError("visual locator dimensions must be within 1..512")
            locator_payload_bytes += len(decoded)
            if locator_payload_bytes > 32 * 1024 * 1024:
                raise SkillContractError("visual locator payload exceeds 32 MiB")
            valid.append(candidate)
        return valid

    def visual_action(locator: Any, *, action: str, coordinate: tuple[int, int], **extra: Any) -> dict[str, Any]:
        value = dict(locator) if isinstance(locator, dict) else {}
        raw_candidates = value.get("candidates") if isinstance(value.get("candidates"), list) else []
        if value.get("status") != "ready" or not raw_candidates:
            if locator_required and not coordinate_fallback:
                raise SkillContractError(f"{action} visual locator is required but unavailable")
            return {"action": action, "x": coordinate[0], "y": coordinate[1], **extra}
        candidates = validated_candidates(raw_candidates)
        compiled = {
            "action": action,
            "required": bool(locator_required),
            "target": str(value.get("locator_id") or f"recorded_{action}")[:96],
            "image_candidates": candidates,
            "recorded_coordinate": list(value.get("recorded_coordinate") or coordinate),
            **extra,
        }
        if coordinate_fallback:
            compiled.update({"x": coordinate[0], "y": coordinate[1], "coordinate_fallback": True})
        return compiled

    def flush_text() -> None:
        if text_buffer:
            actions.append({"action": "write", "text": "".join(text_buffer)})
            text_buffer.clear()

    for event in normalized_events:
        kind = str(event.get("kind") or event.get("type") or "").strip().lower()
        if image_first and kind not in {"", "mouse_move", "key_release", "recording_started", "recording_stopped", "wait", "sleep"}:
            at_ms = int(event.get("at_ms", previous_executable_at_ms or 0))
            if previous_executable_at_ms is not None:
                gap_ms = max(0, at_ms - previous_executable_at_ms)
                if gap_ms >= 500:
                    flush_text()
                    actions.append({"action": "wait", "seconds": round(min(gap_ms / 1000.0, 5.0), 3)})
            previous_executable_at_ms = at_ms
        if kind == "mouse_move" and image_first:
            previous_mouse_at_ms = max(previous_mouse_at_ms, int(event.get("at_ms", previous_mouse_at_ms)))
            continue
        if kind == "mouse_move":
            flush_text()
            if event.get("x") is None or event.get("y") is None:
                raise SkillContractError("mouse_move requires x and y")
            at_ms = max(previous_mouse_at_ms, int(event.get("at_ms", previous_mouse_at_ms + 100)))
            duration_sec = round(max(0.05, min((at_ms - previous_mouse_at_ms) / 1000.0, 1.0)), 3)
            actions.append(
                {
                    "action": "move_to",
                    "x": int(event["x"]),
                    "y": int(event["y"]),
                    "duration_sec": duration_sec,
                }
            )
            previous_mouse_at_ms = at_ms
        elif kind in {"mouse_click", "click"}:
            flush_text()
            if event.get("x") is None or event.get("y") is None:
                raise SkillContractError("mouse_click requires x and y")
            if image_first:
                actions.append(
                    visual_action(
                        event.get("visual_locator"),
                        action="click",
                        coordinate=(int(event["x"]), int(event["y"])),
                        button=str(event.get("button") or "left"),
                    )
                )
            else:
                actions.append(
                    {
                        "action": "click",
                        "x": int(event["x"]),
                        "y": int(event["y"]),
                        "button": str(event.get("button") or "left"),
                    }
                )
        elif kind == "mouse_drag":
            flush_text()
            required = ("start_x", "start_y", "x", "y")
            if any(event.get(field) is None for field in required):
                raise SkillContractError("mouse_drag requires start_x, start_y, x, and y")
            duration = round(max(0.05, min(float(event.get("duration_sec", 0.25)), 5.0)), 3)
            if image_first:
                actions.append(
                    visual_action(
                        event.get("source_visual_locator"),
                        action="move_to",
                        coordinate=(int(event["start_x"]), int(event["start_y"])),
                        duration_sec=0.05,
                    )
                )
                actions.append(
                    visual_action(
                        event.get("target_visual_locator"),
                        action="drag_to",
                        coordinate=(int(event["x"]), int(event["y"])),
                        button=str(event.get("button") or "left"),
                        duration_sec=duration,
                    )
                )
            else:
                actions.append(
                    {
                        "action": "move_to",
                        "x": int(event["start_x"]),
                        "y": int(event["start_y"]),
                        "duration_sec": 0.05,
                    }
                )
                actions.append(
                    {
                        "action": "drag_to",
                        "x": int(event["x"]),
                        "y": int(event["y"]),
                        "button": str(event.get("button") or "left"),
                        "duration_sec": duration,
                    }
                )
        elif kind == "mouse_scroll":
            flush_text()
            dx = max(-100, min(100, int(event.get("dx", 0))))
            dy = max(-100, min(100, int(event.get("dy", 0))))
            if dx:
                actions.append({"action": "hscroll", "clicks": dx})
            if dy:
                actions.append({"action": "scroll", "clicks": dy})
        elif kind in {"key_press", "press"}:
            key = str(event.get("key") or "").strip().lower()
            if not key:
                raise SkillContractError("key_press requires a key")
            printable = _printable_recorded_key(key)
            if printable is not None:
                text_buffer.append(printable)
            else:
                flush_text()
                actions.append({"action": "press", "key": key})
        elif kind == "hotkey":
            flush_text()
            keys = [str(key).strip().lower() for key in event.get("keys", []) if str(key).strip()]
            if not keys:
                raise SkillContractError("hotkey requires keys")
            actions.append({"action": "hotkey", "keys": keys})
        elif kind in {"wait", "sleep"}:
            flush_text()
            seconds = max(0.0, min(float(event.get("seconds", 0.0)), 30.0))
            actions.append({"action": "wait", "seconds": seconds})
        elif kind in {"checkpoint", "screenshot"}:
            flush_text()
            actions.append(
                {
                    "action": "screenshot",
                    "checkpoint": str(event.get("checkpoint_id") or event.get("label") or "checkpoint")[:96],
                }
            )
        elif kind in {"key_release", "recording_started", "recording_stopped", ""}:
            continue
        else:
            raise SkillContractError(f"unsupported recording event kind: {kind}")
    flush_text()
    if not actions:
        raise SkillContractError("recording contains no executable actions")
    return actions


def split_program_segments(
    actions: Iterable[dict[str, Any]], *, limit: int = PROGRAM_ACTION_LIMIT
) -> list[list[dict[str, Any]]]:
    if not 1 <= int(limit) <= PROGRAM_ACTION_LIMIT:
        raise SkillContractError(f"segment limit must be between 1 and {PROGRAM_ACTION_LIMIT}")
    normalized = [deepcopy(dict(action)) for action in actions]
    if not normalized:
        raise SkillContractError("cannot segment an empty action list")
    return [normalized[index : index + limit] for index in range(0, len(normalized), limit)]


def build_exception_packet(
    *,
    skill_id: str,
    version: str,
    execution_id: str,
    segment_id: str,
    checkpoint_id: str,
    failure_code: str,
    message: str,
    evidence: Iterable[dict[str, Any]],
    allowed_recovery_operations: Iterable[str],
) -> dict[str, Any]:
    allowed = []
    for operation in allowed_recovery_operations:
        clean = str(operation or "").strip()
        if clean not in ALLOWED_RECOVERY_OPERATIONS:
            raise SkillContractError(f"recovery operation is not allowed: {clean}")
        if clean not in allowed:
            allowed.append(clean)
    bounded_evidence = [deepcopy(dict(item)) for item in evidence][:8]
    if not bounded_evidence:
        raise SkillContractError("exception evidence is required")
    return {
        "schema": EXCEPTION_SCHEMA,
        "skill_id": _safe_identity(skill_id, "skill_id"),
        "version": _safe_version(version),
        "execution_id": _safe_identity(execution_id, "execution_id"),
        "segment_id": _safe_identity(segment_id, "segment_id"),
        "checkpoint_id": str(checkpoint_id or "")[:96],
        "failure_code": str(failure_code or "SKILL_CHECKPOINT_FAILED")[:96],
        "message": str(message or "")[:1000],
        "evidence": bounded_evidence,
        "allowed_recovery_operations": allowed,
        "created_at": _now_iso(),
    }


def validate_recovery_decision(
    decision: dict[str, Any],
    *,
    exception: dict[str, Any],
    max_attempts: int = 1,
) -> dict[str, Any]:
    """Validate one bounded, non-physical recovery proposal against its exception packet."""
    payload = deepcopy(dict(decision or {}))
    if payload.get("schema") != RECOVERY_SCHEMA:
        raise SkillContractError(f"recovery schema must be {RECOVERY_SCHEMA}")
    operation = str(payload.get("operation") or "").strip()
    allowed = {str(item) for item in exception.get("allowed_recovery_operations", [])}
    if operation not in ALLOWED_RECOVERY_OPERATIONS or operation not in allowed:
        raise SkillContractError(f"recovery operation is not allowed: {operation}")
    action_payload = payload.get("payload")
    if not isinstance(action_payload, dict):
        raise SkillContractError("recovery payload must be an object")
    expected = payload.get("expected_verification")
    if not isinstance(expected, dict) or not expected:
        raise SkillContractError("recovery expected_verification is required")
    try:
        confidence = float(payload.get("confidence"))
        attempt = int(payload.get("attempt"))
    except (TypeError, ValueError) as exc:
        raise SkillContractError("recovery confidence and attempt must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise SkillContractError("recovery confidence must be between 0 and 1")
    if confidence < 0.6:
        raise SkillContractError("recovery confidence is below the execution threshold")
    if not 1 <= attempt <= max(1, int(max_attempts)):
        raise SkillContractError("recovery attempt exceeds the bounded limit")
    payload["operation"] = operation
    payload["payload"] = deepcopy(action_payload)
    payload["expected_verification"] = deepcopy(expected)
    payload["confidence"] = confidence
    payload["attempt"] = attempt
    return payload


def validate_skill_package(package_dir: str | Path) -> dict[str, Any]:
    """Load and hash-validate one exact Skill package directory."""
    root = Path(package_dir)
    manifest = _read_json(root / "manifest.json")
    workflow = _read_json(root / "workflow.json")
    annotations = _read_json(root / "annotations.json")
    if manifest.get("schema") != SKILL_SCHEMA:
        raise SkillContractError(f"schema must be {SKILL_SCHEMA}")
    _safe_identity(str(manifest.get("skill_id") or ""), "skill_id")
    _safe_version(str(manifest.get("version") or ""))
    if manifest.get("workflow_sha256") != canonical_sha256(workflow):
        raise SkillContractError("workflow hash mismatch")
    if manifest.get("annotations_sha256") != canonical_sha256(annotations):
        raise SkillContractError("annotations hash mismatch")
    program_hashes = manifest.get("program_sha256") if isinstance(manifest.get("program_sha256"), dict) else {}
    programs: list[dict[str, Any]] = []
    for program_id in workflow.get("program_ids", []):
        safe_program_id = _safe_identity(str(program_id), "program_id")
        program = _read_json(root / "programs" / f"{safe_program_id}.json")
        if program.get("schema") != PROGRAM_SCHEMA:
            raise SkillContractError(f"program schema mismatch: {safe_program_id}")
        if not 1 <= len(program.get("sequence", [])) <= PROGRAM_ACTION_LIMIT:
            raise SkillContractError(f"program action limit exceeded: {safe_program_id}")
        if program_hashes.get(safe_program_id) != canonical_sha256(program):
            raise SkillContractError(f"program hash mismatch: {safe_program_id}")
        programs.append(program)
    return {
        "manifest": manifest,
        "workflow": workflow,
        "annotations": annotations,
        "programs": programs,
    }


class EquipmentSkillRegistry:
    """Authoritative filesystem registry for exact Equipment Skill versions."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.execution_root = self.root.parent / "equipment_skill_executions"

    def _package_dir(self, skill_id: str, version: str) -> Path:
        return self.root / _safe_identity(skill_id, "skill_id") / _safe_version(version)

    def create_draft(
        self,
        *,
        recording: dict[str, Any],
        skill_id: str,
        version: str,
        target_profile: str,
        model_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        if str(recording.get("schema") or "") not in RECORDING_SCHEMAS:
            raise SkillContractError(f"recording schema must be one of {sorted(RECORDING_SCHEMAS)}")
        if str(recording.get("status") or "") not in {"saved", "completed"}:
            raise SkillContractError("recording must be saved before Skill creation")
        package_dir = self._package_dir(skill_id, version)
        if package_dir.exists():
            raise SkillContractError("exact Skill version already exists")
        profile = _safe_identity(target_profile, "target_profile")
        actions = compile_recording_actions(
            recording.get("events", []),
            visual_locator_policy=recording.get("visual_locator_policy"),
        )
        capability_coverage = recording_capability_coverage(recording.get("events", []))
        created_at = _now_iso()
        workflow = {
            "schema": SKILL_SCHEMA,
            "skill_id": skill_id,
            "version": version,
            "steps": [
                {
                    "step_id": f"step-{index + 1:03d}",
                    "label": action.get("action", "action"),
                    "action": action,
                    "checkpoint_after": False,
                }
                for index, action in enumerate(actions)
            ],
            "program_ids": [],
            "capability_coverage": deepcopy(capability_coverage),
        }
        checkpoints = list(recording.get("checkpoints", []))
        annotations = {
            "schema": SKILL_SCHEMA,
            "skill_id": skill_id,
            "version": version,
            "status": "draft",
            "steps": [
                {
                    "step_id": item["step_id"],
                    "label": item["label"],
                    "confidence": 0.75,
                    "review_required": False,
                }
                for item in workflow["steps"]
            ],
            "checkpoints": checkpoints,
            "model_snapshot": deepcopy(model_snapshot),
        }
        manifest = {
            "schema": SKILL_SCHEMA,
            "skill_id": skill_id,
            "version": version,
            "name": str(recording.get("name") or skill_id)[:160],
            "target_profile": profile,
            "platform": "windows",
            "lifecycle": "draft",
            "enabled": True,
            "recording_id": str(recording.get("recording_id") or ""),
            "recording_sha256": canonical_sha256(recording),
            "workflow_sha256": canonical_sha256(workflow),
            "annotations_sha256": canonical_sha256(annotations),
            "program_sha256": {},
            "model_snapshot": deepcopy(model_snapshot),
            "capability_coverage": deepcopy(capability_coverage),
            "created_at": created_at,
            "updated_at": created_at,
        }
        _atomic_write_json(package_dir / "recording.json", recording)
        _atomic_write_json(package_dir / "workflow.json", workflow)
        _atomic_write_json(package_dir / "annotations.json", annotations)
        _atomic_write_json(package_dir / "manifest.json", manifest)
        self._append_audit(package_dir, "draft_created", {"recording_id": manifest["recording_id"]})
        return self.get(skill_id, version)

    def _append_audit(self, package_dir: Path, event: str, detail: dict[str, Any]) -> None:
        path = package_dir / "audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json({"at": _now_iso(), "event": event, **deepcopy(detail)}) + "\n")

    def get(self, skill_id: str, version: str) -> dict[str, Any]:
        package_dir = self._package_dir(skill_id, version)
        if not package_dir.is_dir():
            raise SkillContractError("Skill version not found")
        manifest = _read_json(package_dir / "manifest.json")
        workflow = _read_json(package_dir / "workflow.json")
        annotations = _read_json(package_dir / "annotations.json")
        programs = []
        for program_id in workflow.get("program_ids", []):
            programs.append(_read_json(package_dir / "programs" / f"{program_id}.json"))
        return {"manifest": manifest, "workflow": workflow, "annotations": annotations, "programs": programs}

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not self.root.exists():
            return items
        for manifest_path in sorted(self.root.glob("*/*/manifest.json")):
            try:
                items.append(_read_json(manifest_path))
            except SkillContractError:
                continue
        return items

    def compile(self, skill_id: str, version: str) -> dict[str, Any]:
        package_dir = self._package_dir(skill_id, version)
        package = self.get(skill_id, version)
        actions = [dict(step.get("action") or {}) for step in package["workflow"].get("steps", [])]
        segment_actions = split_program_segments(actions)
        version_slug = re.sub(r"[^A-Za-z0-9]+", "_", version).strip("_")
        programs = []
        for index, sequence in enumerate(segment_actions, start=1):
            program_id = f"{skill_id}_{version_slug}_segment_{index:03d}"
            program = {
                "schema": PROGRAM_SCHEMA,
                "program_id": program_id,
                "name": f"{package['manifest'].get('name', skill_id)} segment {index}",
                "description": f"Compiled Equipment Skill {skill_id}@{version}, segment {index}",
                "enabled": True,
                "program_type": "macro",
                "safe_test": False,
                "sequence": sequence,
            }
            _atomic_write_json(package_dir / "programs" / f"{program_id}.json", program)
            programs.append(program)
        workflow = package["workflow"]
        workflow["program_ids"] = [program["program_id"] for program in programs]
        workflow["compiled_at"] = _now_iso()
        annotations = package["annotations"]
        annotations["status"] = "compiled"
        manifest = package["manifest"]
        manifest["lifecycle"] = "compiled"
        manifest["workflow_sha256"] = canonical_sha256(workflow)
        manifest["annotations_sha256"] = canonical_sha256(annotations)
        manifest["program_sha256"] = {program["program_id"]: canonical_sha256(program) for program in programs}
        manifest["updated_at"] = _now_iso()
        _atomic_write_json(package_dir / "workflow.json", workflow)
        _atomic_write_json(package_dir / "annotations.json", annotations)
        _atomic_write_json(package_dir / "manifest.json", manifest)
        self._append_audit(package_dir, "compiled", {"program_ids": workflow["program_ids"]})
        return self.get(skill_id, version)

    def annotate(
        self,
        skill_id: str,
        version: str,
        updates: dict[str, Any],
        *,
        model_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        package_dir = self._package_dir(skill_id, version)
        package = self.get(skill_id, version)
        current_by_id = {
            str(item.get("step_id") or ""): dict(item)
            for item in package["annotations"].get("steps", [])
            if isinstance(item, dict)
        }
        update_steps = updates.get("steps") if isinstance(updates.get("steps"), list) else []
        for raw_item in update_steps:
            if not isinstance(raw_item, dict):
                raise SkillContractError("annotation step must be an object")
            step_id = str(raw_item.get("step_id") or "").strip()
            if step_id not in current_by_id:
                raise SkillContractError(f"unknown annotation step: {step_id}")
            confidence = float(raw_item.get("confidence", current_by_id[step_id].get("confidence", 0.0)))
            if not 0.0 <= confidence <= 1.0:
                raise SkillContractError(f"annotation confidence out of range: {step_id}")
            current_by_id[step_id].update(
                {
                    "label": str(raw_item.get("label") or current_by_id[step_id].get("label") or step_id)[:160],
                    "confidence": confidence,
                    "review_required": bool(raw_item.get("review_required", confidence < 0.7)),
                }
            )
            if isinstance(raw_item.get("locator"), dict):
                current_by_id[step_id]["locator"] = deepcopy(raw_item["locator"])
            if raw_item.get("checkpoint_after") is not None:
                current_by_id[step_id]["checkpoint_after"] = bool(raw_item["checkpoint_after"])
        annotations = package["annotations"]
        annotations["steps"] = [current_by_id[str(item.get("step_id"))] for item in annotations.get("steps", [])]
        if model_snapshot is not None:
            annotations["model_snapshot"] = deepcopy(model_snapshot)
        review_required = any(bool(item.get("review_required")) for item in annotations["steps"])
        annotations["status"] = "review_required" if review_required else "reviewed"
        annotations["updated_at"] = _now_iso()
        manifest = package["manifest"]
        manifest["lifecycle"] = (
            "review_required"
            if review_required
            else "compiled"
            if package["workflow"].get("program_ids")
            else "annotated"
        )
        manifest["annotations_sha256"] = canonical_sha256(annotations)
        manifest["updated_at"] = annotations["updated_at"]
        _atomic_write_json(package_dir / "annotations.json", annotations)
        _atomic_write_json(package_dir / "manifest.json", manifest)
        self._append_audit(
            package_dir,
            "annotations_updated",
            {"review_required": review_required, "model": (model_snapshot or {}).get("model", "")},
        )
        return self.get(skill_id, version)

    def validate(self, skill_id: str, version: str) -> dict[str, Any]:
        package_dir = self._package_dir(skill_id, version)
        package = validate_skill_package(package_dir)
        if not package["programs"]:
            raise SkillContractError("Skill must be compiled before validation")
        if any(item.get("review_required") for item in package["annotations"].get("steps", [])):
            raise SkillContractError("Skill annotation review is required")
        manifest = package["manifest"]
        manifest["lifecycle"] = "validated"
        manifest["validated_at"] = _now_iso()
        manifest["updated_at"] = manifest["validated_at"]
        _atomic_write_json(package_dir / "manifest.json", manifest)
        self._append_audit(package_dir, "validated", {"program_count": len(package["programs"])})
        return {"ok": True, "status": "validated", "package": self.get(skill_id, version)}

    def mark_deployed(
        self,
        skill_id: str,
        version: str,
        *,
        bridge_id: str,
        deployment_sha256: str,
        program_sha256: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        package_dir = self._package_dir(skill_id, version)
        package = self.get(skill_id, version)
        if package["manifest"].get("lifecycle") != "validated":
            raise SkillContractError("Skill must be validated before deployment")
        digest = str(deployment_sha256 or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SkillContractError("deployment hash must be SHA-256")
        deployed_at = _now_iso()
        manifest = package["manifest"]
        manifest["lifecycle"] = "deployed"
        manifest["deployment"] = {
            "bridge_id": _safe_identity(bridge_id, "bridge_id"),
            "sha256": digest,
            "program_ids": list((program_sha256 or {}).keys()),
            "program_sha256": dict(program_sha256 or {}),
            "deployed_at": deployed_at,
        }
        manifest["updated_at"] = deployed_at
        _atomic_write_json(package_dir / "manifest.json", manifest)
        self._append_audit(package_dir, "deployed", dict(manifest["deployment"]))
        return self.get(skill_id, version)

    def set_enabled(self, skill_id: str, version: str, enabled: bool) -> dict[str, Any]:
        package_dir = self._package_dir(skill_id, version)
        package = self.get(skill_id, version)
        manifest = package["manifest"]
        manifest["enabled"] = bool(enabled)
        if not enabled:
            manifest["lifecycle"] = "disabled"
        elif manifest.get("deployment"):
            manifest["lifecycle"] = "deployed"
        manifest["updated_at"] = _now_iso()
        _atomic_write_json(package_dir / "manifest.json", manifest)
        self._append_audit(package_dir, "enabled_changed", {"enabled": bool(enabled)})
        return self.get(skill_id, version)

    def record_test(self, skill_id: str, version: str, result: dict[str, Any]) -> dict[str, Any]:
        package_dir = self._package_dir(skill_id, version)
        package = self.get(skill_id, version)
        manifest = package["manifest"]
        manifest["last_test"] = deepcopy(result)
        manifest["updated_at"] = _now_iso()
        _atomic_write_json(package_dir / "manifest.json", manifest)
        self._append_audit(package_dir, "tested", {"status": result.get("status"), "ok": result.get("ok")})
        return self.get(skill_id, version)

    def delete(self, skill_id: str, version: str) -> dict[str, Any]:
        package_dir = self._package_dir(skill_id, version)
        package = self.get(skill_id, version)
        lifecycle = str(package["manifest"].get("lifecycle") or "")
        if lifecycle == "deployed":
            raise SkillContractError("deployed Skill must be disabled before deletion")
        shutil.rmtree(package_dir)
        skill_root = package_dir.parent
        if skill_root.exists() and not any(skill_root.iterdir()):
            skill_root.rmdir()
        return {"ok": True, "status": "deleted", "skill_id": skill_id, "version": version}

    def begin_execution(
        self,
        *,
        skill_id: str,
        version: str,
        sequence_id: str,
        target_profile: str,
        model_snapshot: dict[str, Any],
        allow_unvalidated: bool = False,
    ) -> dict[str, Any]:
        safe_skill_id = _safe_identity(skill_id, "skill_id")
        safe_version = _safe_version(version)
        safe_sequence = _safe_identity(sequence_id, "sequence_id")
        safe_profile = _safe_identity(target_profile, "target_profile")
        self.execution_root.mkdir(parents=True, exist_ok=True)
        sequence_hash = canonical_sha256(
            {"skill_id": safe_skill_id, "version": safe_version, "sequence_id": safe_sequence, "target_profile": safe_profile}
        )
        index_path = self.execution_root / "sequence_index.json"
        index = _read_json(index_path) if index_path.exists() else {}
        if sequence_hash in index:
            state = _read_json(self.execution_root / str(index[sequence_hash]) / "state.json")
            state["idempotent"] = True
            return state
        if not allow_unvalidated:
            package = self.get(safe_skill_id, safe_version)
            if package["manifest"].get("lifecycle") not in {"validated", "deployed"}:
                raise SkillContractError("Skill version is not validated")
            if package["manifest"].get("target_profile") != safe_profile:
                raise SkillContractError("target profile mismatch")
        execution_id = f"skill-{uuid4().hex}"
        state = {
            "schema": "atr.equipment_skill_execution.v1",
            "execution_id": execution_id,
            "skill_id": safe_skill_id,
            "version": safe_version,
            "sequence_id": safe_sequence,
            "target_profile": safe_profile,
            "state": "RUNNING",
            "model_snapshot": deepcopy(model_snapshot),
            "completed_segments": [],
            "attempt": 0,
            "idempotent": False,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        _atomic_write_json(self.execution_root / execution_id / "state.json", state)
        index[sequence_hash] = execution_id
        _atomic_write_json(index_path, index)
        return state

    def transition_execution(self, execution_id: str, state: str, **updates: Any) -> dict[str, Any]:
        safe_execution_id = _safe_identity(execution_id, "execution_id")
        clean_state = str(state or "").strip().upper()
        if clean_state not in EXECUTION_STATES:
            raise SkillContractError(f"invalid execution state: {state}")
        state_path = self.execution_root / safe_execution_id / "state.json"
        payload = _read_json(state_path)
        payload.update(deepcopy(updates))
        payload["state"] = clean_state
        payload["updated_at"] = _now_iso()
        payload["idempotent"] = False
        _atomic_write_json(state_path, payload)
        return payload
