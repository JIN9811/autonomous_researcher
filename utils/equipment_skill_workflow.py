"""Validation helpers for editable sequential Equipment Skill workflows."""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re
from typing import Any


SKILL_SCHEMA = "atr.equipment_skill.v1"
STEP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
EDITABLE_ACTIONS = frozenset(
    {
        "move_to",
        "click",
        "double_click",
        "drag_to",
        "scroll",
        "hscroll",
        "press",
        "hotkey",
        "write",
        "wait",
        "wait_until",
        "wait_until_image",
        "wait_until_text",
        "wait_for_file",
        "screenshot",
        "set_input_language",
    }
)
UNTIL_ACTIONS = frozenset({"wait_until", "wait_until_image", "wait_until_text", "wait_for_file"})


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _issue(step_id: str, field: str, code: str, message: str) -> dict[str, str]:
    return {"step_id": step_id, "field": field, "code": code, "message": message}


def workflow_duration_bounds(workflow: dict[str, Any]) -> dict[str, float]:
    """Return deterministic lower/upper elapsed-time estimates for waits."""
    minimum = 0.0
    maximum = 0.0
    for step in workflow.get("steps", []):
        if not isinstance(step, dict) or not isinstance(step.get("action"), dict):
            continue
        action = step["action"]
        action_name = str(action.get("action") or "")
        if action_name == "wait":
            seconds = _finite_number(action.get("seconds", action.get("duration_sec", 0)))
            if seconds is not None and seconds >= 0:
                minimum += seconds
                maximum += seconds
        elif action_name in UNTIL_ACTIONS:
            timeout = _finite_number(action.get("timeout_s"))
            if timeout is not None and timeout >= 0:
                maximum += timeout
    return {"minimum_s": round(minimum, 3), "maximum_s": round(maximum, 3)}


def _validate_image_candidates(step_id: str, action: dict[str, Any]) -> list[dict[str, str]]:
    candidates = action.get("image_candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 2:
        return [
            _issue(
                step_id,
                "action.image_candidates",
                "IMAGE_CANDIDATES_INVALID",
                "Image wait requires one or two PNG locator candidates.",
            )
        ]
    issues: list[dict[str, str]] = []
    for index, candidate in enumerate(candidates):
        field = f"action.image_candidates.{index}"
        if not isinstance(candidate, dict):
            issues.append(_issue(step_id, field, "IMAGE_CANDIDATE_INVALID", "Locator candidate must be an object."))
            continue
        encoded = str(candidate.get("png_base64") or "")
        expected = str(candidate.get("sha256") or "").lower()
        try:
            content = base64.b64decode(encoded, validate=True)
        except Exception:
            content = b""
        if not content.startswith(b"\x89PNG\r\n\x1a\n") or len(content) > 256 * 1024:
            issues.append(_issue(step_id, field, "IMAGE_PNG_INVALID", "Locator must be a PNG no larger than 256 KiB."))
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or hashlib.sha256(content).hexdigest() != expected:
            issues.append(_issue(step_id, f"{field}.sha256", "IMAGE_HASH_INVALID", "Locator SHA-256 does not match."))
        width = _finite_number(candidate.get("width"))
        height = _finite_number(candidate.get("height"))
        if width is None or height is None or not 1 <= width <= 512 or not 1 <= height <= 512:
            issues.append(_issue(step_id, field, "IMAGE_SIZE_INVALID", "Locator dimensions must be within 1..512."))
    return issues


def _validate_action(step_id: str, action: dict[str, Any]) -> list[dict[str, str]]:
    name = str(action.get("action") or "").strip()
    if name not in EDITABLE_ACTIONS:
        return [_issue(step_id, "action.action", "ACTION_UNSUPPORTED", f"Unsupported action: {name or '(empty)'}")]

    issues: list[dict[str, str]] = []
    if name == "wait":
        seconds = _finite_number(action.get("seconds", action.get("duration_sec")))
        if seconds is None or not 0 <= seconds <= 30:
            issues.append(_issue(step_id, "action.seconds", "WAIT_DURATION_INVALID", "Wait must be within 0..30 seconds."))
    if name in UNTIL_ACTIONS:
        timeout = _finite_number(action.get("timeout_s"))
        if timeout is None or not 0.1 <= timeout <= 3600:
            issues.append(_issue(step_id, "action.timeout_s", "WAIT_TIMEOUT_INVALID", "Timeout must be within 0.1..3600 seconds."))
        poll = _finite_number(action.get("poll_interval_s", 0.25))
        if poll is None or not 0.05 <= poll <= 10 or (
            timeout is not None and 0.1 <= timeout <= 3600 and poll > timeout
        ):
            issues.append(_issue(step_id, "action.poll_interval_s", "WAIT_POLL_INVALID", "Polling must be within 0.05..10 seconds and no greater than timeout."))
    if name in {"wait_until", "wait_until_image", "wait_until_text"} and not str(action.get("target") or "").strip():
        issues.append(_issue(step_id, "action.target", "WAIT_TARGET_REQUIRED", "Wait target is required."))
    if name == "wait_for_file" and not str(action.get("pattern") or "").strip():
        issues.append(_issue(step_id, "action.pattern", "FILE_PATTERN_REQUIRED", "File pattern is required."))
    if name == "wait_until_image" and action.get("image_candidates") is not None:
        issues.extend(_validate_image_candidates(step_id, action))
    if name in {"move_to", "click", "double_click", "drag_to"} and not action.get("image_candidates"):
        for axis in ("x", "y"):
            if _finite_number(action.get(axis)) is None:
                issues.append(_issue(step_id, f"action.{axis}", "POINTER_COORDINATE_REQUIRED", f"Pointer {axis} coordinate is required."))
    if name in {"move_to", "drag_to"}:
        duration = _finite_number(action.get("duration_sec", 0.25))
        if duration is None or not 0.05 <= duration <= 5:
            issues.append(_issue(step_id, "action.duration_sec", "POINTER_DURATION_INVALID", "Pointer duration must be within 0.05..5 seconds."))
    if name == "write" and len(str(action.get("text") or "")) > 512:
        issues.append(_issue(step_id, "action.text", "WRITE_TEXT_TOO_LONG", "Write text must not exceed 512 characters."))
    if name == "press" and not str(action.get("key") or "").strip():
        issues.append(_issue(step_id, "action.key", "KEY_REQUIRED", "Key is required."))
    if name == "hotkey" and not [item for item in action.get("keys", []) if str(item).strip()]:
        issues.append(_issue(step_id, "action.keys", "HOTKEY_REQUIRED", "At least one hotkey key is required."))
    if name == "set_input_language":
        layout_id = str(action.get("layout_id") or "").strip()
        typing_mode = str(action.get("typing_mode") or "").strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{8}", layout_id):
            issues.append(_issue(step_id, "action.layout_id", "INPUT_LAYOUT_INVALID", "Layout ID must contain exactly 8 hexadecimal digits."))
        if not typing_mode or typing_mode == "unknown":
            issues.append(_issue(step_id, "action.typing_mode", "INPUT_TYPING_MODE_REQUIRED", "A known typing mode is required."))
    if name == "screenshot" and not str(action.get("checkpoint") or "").strip():
        issues.append(_issue(step_id, "action.checkpoint", "CHECKPOINT_REQUIRED", "Checkpoint label is required."))
    return issues


def validate_editable_workflow(
    workflow: dict[str, Any], *, locator_root: Path | None = None
) -> dict[str, Any]:
    """Normalize and validate one editable sequential workflow document."""
    del locator_root  # Embedded locator candidates are authoritative in v1.
    normalized = deepcopy(dict(workflow or {}))
    issues: list[dict[str, str]] = []
    if normalized.get("schema") != SKILL_SCHEMA:
        issues.append(_issue("", "schema", "SCHEMA_INVALID", f"Schema must be {SKILL_SCHEMA}."))
    steps = normalized.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 10_000:
        issues.append(_issue("", "steps", "STEP_COUNT_INVALID", "Workflow must contain 1..10000 steps."))
        steps = []
    seen: set[str] = set()
    normalized_steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            issues.append(_issue("", f"steps.{index}", "STEP_INVALID", "Step must be an object."))
            continue
        step = deepcopy(raw_step)
        step_id = str(step.get("step_id") or "").strip()
        if not STEP_ID_PATTERN.fullmatch(step_id):
            issues.append(_issue(step_id, "step_id", "STEP_ID_INVALID", "Step ID is missing or invalid."))
        elif step_id in seen:
            issues.append(_issue(step_id, "step_id", "DUPLICATE_STEP_ID", "Step ID must be unique."))
        seen.add(step_id)
        label = str(step.get("label") or step_id or f"Step {index + 1}").strip()
        if len(label) > 160:
            issues.append(_issue(step_id, "label", "STEP_LABEL_TOO_LONG", "Step label must not exceed 160 characters."))
        step["label"] = label[:160]
        step["checkpoint_after"] = bool(step.get("checkpoint_after", False))
        action = step.get("action")
        if not isinstance(action, dict):
            issues.append(_issue(step_id, "action", "ACTION_INVALID", "Step action must be an object."))
            step["action"] = {}
        else:
            step["action"] = deepcopy(action)
            issues.extend(_validate_action(step_id, step["action"]))
        normalized_steps.append(step)
    normalized["steps"] = normalized_steps
    normalized["program_ids"] = []
    normalized.pop("compiled_at", None)
    return {
        "ok": not issues,
        "workflow": normalized,
        "issues": issues,
        "duration": workflow_duration_bounds(normalized),
    }
