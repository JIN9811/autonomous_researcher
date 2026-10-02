#!/usr/bin/env python3
"""Audit whether Bambu autoejection has real physical completion evidence.

This script is intentionally non-actuating. It does not connect to the printer,
publish MQTT commands, move axes, or infer completion from a successful upload.
Exit code 0 is reserved for a persisted, file-backed proof package that shows
supervised physical ejection, bed-clear evidence, and a clear next-job gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
if (
    __name__ == "__main__"
    and
    LOCAL_VENV_PYTHON.exists()
    and Path(sys.executable) != LOCAL_VENV_PYTHON
    and os.environ.get("VIRTUAL_ENV") != str(REPO_ROOT / ".venv")
    and os.environ.get("ATR_NO_VENV_REEXEC") != "1"
):
    os.environ["ATR_NO_VENV_REEXEC"] = "1"
    os.execv(str(LOCAL_VENV_PYTHON), [str(LOCAL_VENV_PYTHON), *sys.argv])
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


BASE_REQUIRED_BLOCKERS = [
    "BAMBU_PHYSICAL_CENTER_EJECTION_REQUIRED",
    "BAMBU_PHYSICAL_LIVE_EJECTION_REQUIRED",
    "BAMBU_BED_CLEAR_EVIDENCE_REQUIRED",
    "BAMBU_NEXT_JOB_GATE_REQUIRED",
]

NOT_STARTED_POST_PUBLISH_STATUSES = {
    "idle",
    "ready",
    "not_started",
    "not started",
    "standby",
    "unknown",
    "none",
}


def _json_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _latest_proof_package(root: Path) -> Path | None:
    patterns = [
        "artifacts/printer/*/bambu/bambu_autoejection_physical_validation_*.json",
        "runs/*/workspace/printer/bambu_autoejection_physical_validation_*.json",
        "memory/bambu_autoejection_physical_validation_*.json",
    ]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(root.glob(pattern))
    candidates = [item for item in candidates if item.is_file()]
    candidates.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0.0, reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return None, {"ok": False, "failure_code": "PROOF_PACKAGE_NOT_AVAILABLE", "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, {"ok": False, "failure_code": "PROOF_PACKAGE_JSON_INVALID", "path": str(path), "error": str(exc)}
    if not isinstance(payload, dict):
        return None, {"ok": False, "failure_code": "PROOF_PACKAGE_JSON_OBJECT_REQUIRED", "path": str(path)}
    return payload, {"ok": True, "path": str(path)}


def _resolve_evidence_path(value: Any, *, base_dir: Path) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _is_image_file(path: Path | None) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False
    return head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff")


def _same_existing_path(left: Path | None, right: Path | None) -> bool:
    if left is None or right is None:
        return False
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _valid_sha256(value: Any) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in text)


def _file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _artifact_file_matches_hash(path: Path | None, expected_sha256: Any) -> bool:
    expected = str(expected_sha256 or "").strip()
    if path is None or not _valid_sha256(expected):
        return False
    actual = _file_sha256(path)
    return bool(actual and actual.lower() == expected.lower())


def _valid_patch_manifest(path: Path | None, *, live: dict[str, Any]) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    payload, load_info = _load_json(path)
    if payload is None or not load_info.get("ok"):
        return False
    validation = _as_dict(payload.get("validation"))
    blockers = validation.get("blockers")
    blockers = blockers if isinstance(blockers, list) else []
    source_sha = str(payload.get("source_sha256") or "").strip()
    patched_sha = str(payload.get("patched_sha256") or "").strip()
    return bool(
        payload.get("schema") == "bambu_autoejection_artifact_manifest.v1"
        and _valid_sha256(source_sha)
        and _valid_sha256(patched_sha)
        and source_sha == str(live.get("source_artifact_sha256") or "").strip()
        and patched_sha == str(live.get("patched_artifact_sha256") or "").strip()
        and validation.get("ok") is True
        and not blockers
    )


def _artifact_hashes_match_live(evidence: dict[str, Any], *, live: dict[str, Any]) -> bool:
    source_sha = str(evidence.get("source_artifact_sha256") or "").strip()
    patched_sha = str(evidence.get("patched_artifact_sha256") or "").strip()
    return bool(
        _valid_sha256(source_sha)
        and _valid_sha256(patched_sha)
        and source_sha == str(live.get("source_artifact_sha256") or "").strip()
        and patched_sha == str(live.get("patched_artifact_sha256") or "").strip()
    )


def _valid_lane_artifact(path: Path | None, *, position: str) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool("atr.bambu.autoejection.v1" in text and f"atr_position={position}" in text)


def _valid_lane_validation_snapshot(path: Path | None, *, position: str) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    payload, load_info = _load_json(path)
    if payload is None or not load_info.get("ok"):
        return False
    validation = _as_dict(payload.get("validation"))
    top_blockers = payload.get("blockers")
    top_blockers = top_blockers if isinstance(top_blockers, list) else []
    validation_blockers = validation.get("blockers")
    validation_blockers = validation_blockers if isinstance(validation_blockers, list) else []
    observed_position = str(payload.get("position") or payload.get("requested_position") or "").strip().lower()
    return bool(
        payload.get("ok") is True
        and validation.get("ok") is True
        and observed_position == position
        and not top_blockers
        and not validation_blockers
    )


def _contains_text(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_text(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_contains_text(item, needle) for item in value)
    return str(value or "").strip() == needle


def _valid_next_job_gate_snapshot(path: Path | None) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    payload, load_info = _load_json(path)
    if payload is None or not load_info.get("ok"):
        return False
    blockers = payload.get("blockers")
    if not isinstance(blockers, list):
        return False
    bed_clear = _as_dict(payload.get("bed_clear"))
    return bool(
        payload.get("ok") is True
        and payload.get("ready_to_publish") is True
        and payload.get("start_enabled") is True
        and not blockers
        and not str(bed_clear.get("blocking_code") or "").strip()
        and not _contains_text(payload, "BAMBU_POST_EJECT_BED_NOT_CLEAR")
    )


def _valid_prestart_snapshot(path: Path | None) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    payload, load_info = _load_json(path)
    if payload is None or not load_info.get("ok"):
        return False
    return bool(
        payload.get("tool") == "printer.bambu.prestart_check"
        and payload.get("ok") is True
        and str(payload.get("provider") or "").strip().lower() in {"bambulab", "bambulab_x2d", "bambu"}
        and payload.get("status") == "ready_to_publish_not_started"
        and payload.get("ready_to_publish") is True
        and payload.get("published") is False
        and payload.get("will_publish") is False
        and payload.get("start_enabled") is True
    )


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _path_matches_observed_remote(expected: Any, observed: Any) -> bool:
    expected_text = str(expected or "").strip()
    observed_text = str(observed or "").strip()
    if not expected_text or not observed_text:
        return False
    return bool(expected_text == observed_text or observed_text.endswith(expected_text) or expected_text.endswith(observed_text))


def _valid_publish_snapshot(path: Path | None, *, evidence: dict[str, Any]) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    payload, load_info = _load_json(path)
    if payload is None or not load_info.get("ok"):
        return False
    publish_result = _as_dict(payload.get("publish_result"))
    post_publish_state = _as_dict(payload.get("post_publish_state"))
    draft = _as_dict(payload.get("draft"))
    draft_payload = _as_dict(draft.get("payload"))
    draft_print = _as_dict(draft_payload.get("print"))
    observed_remote = _first_text(payload.get("remote_path"), payload.get("bambu_artifact_url"), draft_print.get("url"))
    observed_sequence = _first_text(payload.get("publish_sequence_id"), publish_result.get("sequence_id"))
    observed_topic = _first_text(payload.get("publish_topic"), publish_result.get("topic"), draft.get("topic"))
    observed_status = _first_text(payload.get("post_publish_status"), post_publish_state.get("status"))
    expected_topic = str(evidence.get("publish_topic") or "").strip()
    blockers = payload.get("blockers")
    blockers = blockers if isinstance(blockers, list) else []
    return bool(
        payload.get("tool") == "printer.bambu.start_publish"
        and payload.get("ok") is True
        and payload.get("published") is True
        and payload.get("ready_to_publish") is True
        and payload.get("start_enabled") is True
        and not blockers
        and _path_matches_observed_remote(evidence.get("remote_path"), observed_remote)
        and observed_sequence == str(evidence.get("publish_sequence_id") or "").strip()
        and (not expected_topic or observed_topic == expected_topic)
        and observed_topic
        and _observed_post_publish_start(observed_status)
        and observed_status == str(evidence.get("post_publish_status") or "").strip()
    )


def _lane_publish_evidence(lanes: dict[str, Any], *, position: str) -> dict[str, Any]:
    return {
        "remote_path": lanes.get(f"{position}_remote_path"),
        "publish_sequence_id": lanes.get(f"{position}_publish_sequence_id"),
        "publish_topic": lanes.get(f"{position}_publish_topic"),
        "post_publish_status": lanes.get(f"{position}_post_publish_status"),
    }


def _add_once(blockers: list[str], code: str) -> None:
    if code not in blockers:
        blockers.append(code)


def _observed_post_publish_start(value: Any) -> bool:
    status = str(value or "").strip().lower()
    return bool(status and status not in NOT_STARTED_POST_PUBLISH_STATUSES)


def _verify_bambu_physical_proof(package: dict[str, Any], *, proof_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    base_dir = proof_path.parent

    if package.get("schema") != "bambu_autoejection_physical_validation.v1":
        _add_once(blockers, "BAMBU_PHYSICAL_PROOF_SCHEMA_INVALID")

    printer = _as_dict(package.get("printer"))
    if str(printer.get("provider") or "").strip().lower() not in {"bambulab", "bambulab_x2d", "bambu"}:
        _add_once(blockers, "BAMBU_ACTIVE_PROVIDER_PROOF_REQUIRED")

    precheck = _as_dict(package.get("physical_start_precheck"))
    precheck_snapshot_path = _resolve_evidence_path(precheck.get("prestart_snapshot_path"), base_dir=base_dir)
    if not (
        precheck.get("ok") is True
        and precheck.get("published") is False
        and precheck.get("will_publish") is False
        and precheck.get("ready_to_publish_not_started") is True
        and _valid_prestart_snapshot(precheck_snapshot_path)
    ):
        _add_once(blockers, "BAMBU_PRESTART_VALIDATION_REQUIRED")

    center = _as_dict(package.get("center_standalone_ejection"))
    center_started_observed = _observed_post_publish_start(center.get("post_publish_status"))
    center_artifact_path = _resolve_evidence_path(center.get("artifact_path"), base_dir=base_dir)
    center_publish_snapshot_path = _resolve_evidence_path(center.get("publish_snapshot_path"), base_dir=base_dir)
    if not (
        center.get("ok") is True
        and center.get("published") is True
        and center.get("object_cleared") is True
        and center.get("collision_observed") is False
        and center.get("toolhead_cover_shifted") is False
        and center.get("build_plate_shifted") is False
        and str(center.get("remote_path") or "").strip()
        and str(center.get("publish_sequence_id") or "").strip()
        and str(center.get("post_publish_status") or "").strip()
        and center_started_observed
        and _valid_lane_artifact(center_artifact_path, position="center")
        and _valid_publish_snapshot(center_publish_snapshot_path, evidence=center)
    ):
        _add_once(blockers, "BAMBU_PHYSICAL_CENTER_EJECTION_REQUIRED")
    if str(center.get("post_publish_status") or "").strip() and not center_started_observed:
        _add_once(blockers, "BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED")

    live = _as_dict(package.get("disposable_live_ejection"))
    live_started_observed = _observed_post_publish_start(live.get("post_publish_status"))
    live_source_artifact_path = _resolve_evidence_path(live.get("source_artifact_path"), base_dir=base_dir)
    live_patched_artifact_path = _resolve_evidence_path(live.get("patched_artifact_path"), base_dir=base_dir)
    live_publish_snapshot_path = _resolve_evidence_path(live.get("publish_snapshot_path"), base_dir=base_dir)
    if not (
        live.get("ok") is True
        and live.get("tail_observed") is True
        and live.get("object_cleared") is True
        and live.get("bed_clear_locked") is True
        and str(live.get("remote_path") or "").strip()
        and str(live.get("publish_sequence_id") or "").strip()
        and str(live.get("post_publish_status") or "").strip()
        and _valid_sha256(live.get("source_artifact_sha256"))
        and _valid_sha256(live.get("patched_artifact_sha256"))
        and _artifact_file_matches_hash(live_source_artifact_path, live.get("source_artifact_sha256"))
        and _artifact_file_matches_hash(live_patched_artifact_path, live.get("patched_artifact_sha256"))
        and live_started_observed
        and _valid_publish_snapshot(live_publish_snapshot_path, evidence=live)
    ):
        _add_once(blockers, "BAMBU_PHYSICAL_LIVE_EJECTION_REQUIRED")
    if str(live.get("post_publish_status") or "").strip() and not live_started_observed:
        _add_once(blockers, "BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED")

    manifest_path = _resolve_evidence_path(live.get("manifest_path"), base_dir=base_dir)
    if not _valid_patch_manifest(manifest_path, live=live):
        _add_once(blockers, "BAMBU_PATCH_MANIFEST_EVIDENCE_REQUIRED")

    lanes = _as_dict(package.get("left_right_lane"))
    lane_blockers = lanes.get("validator_blockers")
    lane_blockers = lane_blockers if isinstance(lane_blockers, list) else []
    left_lane_path = _resolve_evidence_path(lanes.get("left_artifact_path"), base_dir=base_dir)
    right_lane_path = _resolve_evidence_path(lanes.get("right_artifact_path"), base_dir=base_dir)
    left_validation_path = _resolve_evidence_path(lanes.get("left_validation_snapshot_path"), base_dir=base_dir)
    right_validation_path = _resolve_evidence_path(lanes.get("right_validation_snapshot_path"), base_dir=base_dir)
    left_publish_snapshot_path = _resolve_evidence_path(lanes.get("left_publish_snapshot_path"), base_dir=base_dir)
    right_publish_snapshot_path = _resolve_evidence_path(lanes.get("right_publish_snapshot_path"), base_dir=base_dir)
    left_publish_evidence = _lane_publish_evidence(lanes, position="left")
    right_publish_evidence = _lane_publish_evidence(lanes, position="right")
    if not (
        lanes.get("ok") is True
        and lanes.get("left_ok") is True
        and lanes.get("right_ok") is True
        and len(lane_blockers) == 0
        and _valid_lane_artifact(left_lane_path, position="left")
        and _valid_lane_artifact(right_lane_path, position="right")
        and _valid_lane_validation_snapshot(left_validation_path, position="left")
        and _valid_lane_validation_snapshot(right_validation_path, position="right")
        and _valid_publish_snapshot(left_publish_snapshot_path, evidence=left_publish_evidence)
        and _valid_publish_snapshot(right_publish_snapshot_path, evidence=right_publish_evidence)
    ):
        _add_once(blockers, "BAMBU_PHYSICAL_LEFT_RIGHT_EJECTION_REQUIRED")

    bed_clear = _as_dict(package.get("post_ejection_bed_clear"))
    bed_clear_method = str(bed_clear.get("verification_method") or "").strip().lower()
    if not (
        bed_clear.get("ok") is True
        and bed_clear.get("bed_clear_verified") is True
        and not str(bed_clear.get("blocking_code") or "").strip()
        and bed_clear_method in {"operator", "camera", "vision"}
        and _artifact_hashes_match_live(bed_clear, live=live)
    ):
        _add_once(blockers, "BAMBU_BED_CLEAR_EVIDENCE_REQUIRED")

    next_job = _as_dict(package.get("next_job_gate"))
    next_job_snapshot_path = _resolve_evidence_path(next_job.get("start_gate_snapshot_path"), base_dir=base_dir)
    if not (
        next_job.get("ok") is True
        and next_job.get("no_bambu_post_eject_bed_not_clear") is True
        and next_job.get("printer_state_matches_idle_ready") is True
        and _valid_next_job_gate_snapshot(next_job_snapshot_path)
    ):
        _add_once(blockers, "BAMBU_NEXT_JOB_GATE_REQUIRED")

    image_fields = [
        precheck.get("camera_snapshot_path"),
        center.get("camera_before_path"),
        center.get("camera_after_path"),
        live.get("camera_snapshot_path"),
        bed_clear.get("camera_snapshot_path"),
    ]
    image_paths = [_resolve_evidence_path(item, base_dir=base_dir) for item in image_fields]
    if not all(_is_image_file(path) for path in image_paths):
        _add_once(blockers, "BAMBU_CAMERA_EVIDENCE_FILES_REQUIRED")
    if _same_existing_path(image_paths[1], image_paths[2]):
        _add_once(blockers, "BAMBU_CAMERA_BEFORE_AFTER_DISTINCT_REQUIRED")

    if str(center.get("post_publish_status") or "").strip().lower() in {"idle", "finish", "finished"}:
        warnings.append("center_standalone_ejection.post_publish_status does not prove motion by itself; camera evidence remains authoritative")

    status = "verified" if not blockers else "blocked"
    return {
        "ok": not blockers,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "proof_path": str(proof_path),
        "checked_evidence": {
            "camera_paths": [str(path) if path else "" for path in image_paths],
            "prestart_snapshot_path": str(precheck_snapshot_path) if precheck_snapshot_path else "",
            "center_artifact_path": str(center_artifact_path) if center_artifact_path else "",
            "center_publish_snapshot_path": str(center_publish_snapshot_path) if center_publish_snapshot_path else "",
            "live_source_artifact_path": str(live_source_artifact_path) if live_source_artifact_path else "",
            "live_patched_artifact_path": str(live_patched_artifact_path) if live_patched_artifact_path else "",
            "live_publish_snapshot_path": str(live_publish_snapshot_path) if live_publish_snapshot_path else "",
            "manifest_path": str(manifest_path) if manifest_path else "",
            "left_lane_validation_snapshot_path": str(left_validation_path) if left_validation_path else "",
            "right_lane_validation_snapshot_path": str(right_validation_path) if right_validation_path else "",
            "left_lane_publish_snapshot_path": str(left_publish_snapshot_path) if left_publish_snapshot_path else "",
            "right_lane_publish_snapshot_path": str(right_publish_snapshot_path) if right_publish_snapshot_path else "",
            "next_job_start_gate_snapshot_path": str(next_job_snapshot_path) if next_job_snapshot_path else "",
            "remote_path": str(live.get("remote_path") or ""),
            "publish_sequence_id": str(live.get("publish_sequence_id") or ""),
            "publish_topic": str(live.get("publish_topic") or ""),
            "bed_clear_verification_method": bed_clear_method,
        },
    }


def audit(path_value: str = "", *, latest: bool = False) -> dict[str, Any]:
    """Return a strict completion audit for a persisted Bambu proof package."""
    selected_path = str(path_value or "").strip()
    latest_path: Path | None = None
    if not selected_path and latest:
        latest_path = _latest_proof_package(REPO_ROOT)
        selected_path = str(latest_path or "")

    if not selected_path:
        blockers = ["PROOF_PACKAGE_PATH_REQUIRED", "PROOF_PACKAGE_NOT_AVAILABLE", *BASE_REQUIRED_BLOCKERS]
        return {
            "ok": False,
            "tool": "printer.bambu.improvement14_completion_audit",
            "status": "incomplete",
            "objective": "14_bambulab_gcode_autoejection_runtime",
            "proof_package_path": "",
            "latest_search_used": bool(latest),
            "completion_rule": "Bambu autoejection is incomplete until physical ejection, bed-clear, and next-job gate evidence are verified from a proof package.",
            "blockers": blockers,
            "verification": {"ok": False, "status": "blocked", "blockers": blockers},
            "next_actions": [
                "Run a supervised center standalone ejection test on the real Bambu printer.",
                "Run a disposable live autoeject print and capture camera evidence.",
                "Verify bed-clear and next-job gate before marking Improvement 14 complete.",
            ],
        }

    proof_path = Path(selected_path).expanduser()
    if not proof_path.is_absolute():
        proof_path = REPO_ROOT / proof_path
    package, load_info = _load_json(proof_path)
    if package is None:
        blockers = [str(load_info.get("failure_code") or "PROOF_PACKAGE_NOT_AVAILABLE"), *BASE_REQUIRED_BLOCKERS]
        return {
            "ok": False,
            "tool": "printer.bambu.improvement14_completion_audit",
            "status": "incomplete",
            "objective": "14_bambulab_gcode_autoejection_runtime",
            "proof_package_path": str(proof_path),
            "latest_search_used": bool(latest and latest_path is not None),
            "completion_rule": "Bambu autoejection is incomplete until physical ejection, bed-clear, and next-job gate evidence are verified from a proof package.",
            "blockers": blockers,
            "load_info": load_info,
            "verification": {"ok": False, "status": "blocked", "blockers": blockers},
            "next_actions": ["Create or select a valid Bambu physical validation proof package."],
        }

    verification = _verify_bambu_physical_proof(package, proof_path=proof_path)
    blockers = [str(item) for item in verification.get("blockers", []) if str(item or "").strip()]
    ok = bool(verification.get("ok") and verification.get("status") == "verified")
    result = {
        "ok": ok,
        "tool": "printer.bambu.improvement14_completion_audit",
        "status": "complete_evidence_verified" if ok else "incomplete",
        "objective": "14_bambulab_gcode_autoejection_runtime",
        "proof_package_path": str(proof_path),
        "latest_search_used": bool(latest and latest_path is not None),
        "completion_rule": "Only file-backed physical proof with center/live ejection, bed-clear, and next-job gate evidence can satisfy Improvement 14.",
        "blockers": blockers,
        "verification": verification,
    }
    if ok:
        result["next_actions"] = ["Bambu autoejection physical evidence is verified for this proof package."]
    else:
        result["next_actions"] = [
            "Resolve verification.blockers.",
            "Re-run supervised Bambu physical validation if evidence is missing.",
            "Do not mark Improvement 14 complete until this audit exits 0.",
        ]
    return result


def write_proof_template(
    path_value: str = "",
    *,
    printer_profile_id: str = "bambulab_x2d",
    provider: str = "bambulab",
) -> dict[str, Any]:
    """Write a fail-closed proof package scaffold for supervised validation."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path_text = str(path_value or "").strip()
    if path_text:
        proof_path = Path(path_text).expanduser()
    else:
        proof_path = REPO_ROOT / "artifacts" / "printer" / "manual" / "bambu" / f"bambu_autoejection_physical_validation_{stamp}.json"
    if not proof_path.is_absolute():
        proof_path = REPO_ROOT / proof_path
    payload: dict[str, Any] = {
        "schema": "bambu_autoejection_physical_validation.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completion_ready": False,
        "instructions": [
            "Fill this package only after supervised physical Bambu validation.",
            "Do not set booleans true from intent, upload success, MQTT ack, or GUI status alone.",
            "Camera paths must point to real PNG/JPEG files captured before/after ejection.",
            "Center before/after camera paths must be distinct files, not one reused snapshot.",
            "Center ejection must point to a local center standalone artifact with ATR marker comments and a saved printer.bambu.start_publish response snapshot.",
            "Live ejection must reference a saved printer.bambu.start_publish response snapshot with matching remote path, topic, sequence id, and running post-publish status.",
            "Bed-clear evidence must name operator/camera/vision verification and match the live source/patched artifact sha256 values.",
            "Run scripts/audit_bambu_autoejection_completion.py against this file before declaring completion.",
        ],
        "printer": {"provider": str(provider or "bambulab"), "profile_id": str(printer_profile_id or "bambulab_x2d")},
        "physical_start_precheck": {
            "ok": False,
            "published": False,
            "will_publish": False,
            "ready_to_publish_not_started": False,
            "prestart_snapshot_path": "",
            "camera_snapshot_path": "",
        },
        "center_standalone_ejection": {
            "ok": False,
            "published": False,
            "post_publish_status": "",
            "remote_path": "",
            "publish_sequence_id": "",
            "publish_topic": "",
            "publish_snapshot_path": "",
            "artifact_path": "",
            "camera_before_path": "",
            "camera_after_path": "",
            "object_cleared": False,
            "collision_observed": True,
            "toolhead_cover_shifted": True,
            "build_plate_shifted": True,
        },
        "disposable_live_ejection": {
            "ok": False,
            "tail_observed": False,
            "object_cleared": False,
            "bed_clear_locked": False,
            "remote_path": "",
            "source_artifact_path": "",
            "patched_artifact_path": "",
            "source_artifact_sha256": "",
            "patched_artifact_sha256": "",
            "manifest_path": "",
            "publish_sequence_id": "",
            "publish_topic": "",
            "publish_snapshot_path": "",
            "post_publish_status": "",
            "camera_snapshot_path": "",
        },
        "left_right_lane": {
            "ok": False,
            "left_ok": False,
            "right_ok": False,
            "left_artifact_path": "",
            "right_artifact_path": "",
            "left_validation_snapshot_path": "",
            "right_validation_snapshot_path": "",
            "left_remote_path": "",
            "right_remote_path": "",
            "left_publish_sequence_id": "",
            "right_publish_sequence_id": "",
            "left_publish_topic": "",
            "right_publish_topic": "",
            "left_post_publish_status": "",
            "right_post_publish_status": "",
            "left_publish_snapshot_path": "",
            "right_publish_snapshot_path": "",
            "validator_blockers": ["NOT_VALIDATED"],
        },
        "post_ejection_bed_clear": {
            "ok": False,
            "bed_clear_verified": False,
            "blocking_code": "BAMBU_POST_EJECT_BED_NOT_CLEAR",
            "verification_method": "",
            "source_artifact_sha256": "",
            "patched_artifact_sha256": "",
            "camera_snapshot_path": "",
        },
        "next_job_gate": {
            "ok": False,
            "no_bambu_post_eject_bed_not_clear": False,
            "printer_state_matches_idle_ready": False,
            "start_gate_snapshot_path": "",
        },
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(_json_dump(payload) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "tool": "printer.bambu.improvement14_proof_template",
        "status": "template_written_fail_closed",
        "completion_ready": False,
        "proof_package_path": str(proof_path),
        "message": "Template written. It is intentionally incomplete until supervised physical evidence is filled and the completion audit exits 0.",
        "next_actions": [
            "Capture supervised center/live/left/right ejection evidence.",
            "Fill camera paths, manifest paths, hashes, and gate fields from real evidence.",
            "Run scripts/audit_bambu_autoejection_completion.py --proof-package <this file>.",
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-package", default="", help="Path to bambu_autoejection_physical_validation_*.json")
    parser.add_argument("--latest", action="store_true", help="Use the newest Bambu proof package under artifacts/, runs/, or memory/")
    parser.add_argument("--write-template", default="", help="Write a fail-closed physical validation proof package scaffold to this path")
    parser.add_argument("--printer-profile-id", default="bambulab_x2d", help="Printer profile id to place in a generated template")
    parser.add_argument("--provider", default="bambulab", help="Provider id to place in a generated template")
    parser.add_argument("--out", default="", help="Optional JSON output path for the audit result")
    parser.add_argument("--quiet", action="store_true", help="Print only PASS/FAIL summary instead of JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write_template:
        result = write_proof_template(args.write_template, printer_profile_id=args.printer_profile_id, provider=args.provider)
    else:
        result = audit(args.proof_package, latest=bool(args.latest))
    if args.out:
        out_path = Path(args.out).expanduser()
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_json_dump(result) + "\n", encoding="utf-8")
        result["audit_artifact"] = str(out_path)
    if args.quiet:
        blockers = result.get("blockers") if isinstance(result.get("blockers"), list) else []
        print("PASS" if result.get("ok") else "FAIL", result.get("status"), ",".join(str(item) for item in blockers[:5]))
    else:
        print(_json_dump(result))
    if args.write_template:
        return 0 if result.get("ok") else 2
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
