#!/usr/bin/env python3
"""Live UTM validation runner for Lab Equipment Agent improvement 05.

This runner is intentionally stricter than a simple bridge smoke test. It uses
WindowsPyAutoGUIBridge, writes an auditable JSON report, and evaluates whether a
real live UTM run satisfies the four Improvement 05 completion claims:
GUI state, physical/Vision proof, Windows->Linux data return, and explicit
save/export responsibility.

Default mode is non-actuating preflight. Add --confirm-live-execute only when
physical UTM setup is safe and the operator wants to send /execute.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - dependency failure is reported in main
    yaml = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from device_bridges.windows_pyautogui_bridge import (  # noqa: E402
    WindowsPyAutoGUIBridge,
    WindowsPyAutoGUIBridgeConfig,
)


SCHEMA = "lab_equipment_utm_live_validation.v1"
DEFAULT_PROGRAM_ID = "utm_compression_start_v1"
VISION_REQUIRED_CODE = "VISION_PROOF_REQUIRED"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def timestamp_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def read_json_object(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON object required: {path}")
    return data


def load_devices_config(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load configs/devices.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def program_ids(programs_response: dict[str, Any]) -> set[str]:
    programs = as_list(programs_response.get("programs"))
    ids: set[str] = set()
    for program in programs:
        if isinstance(program, dict):
            program_id = str(program.get("program_id") or "").strip()
            if program_id:
                ids.add(program_id)
    return ids


def program_by_id(programs_response: dict[str, Any], program_id: str) -> dict[str, Any]:
    for program in as_list(programs_response.get("programs")):
        if isinstance(program, dict) and str(program.get("program_id") or "") == program_id:
            return dict(program)
    return {}


def required_utm_locator_names(runtime_profile: dict[str, Any], program: dict[str, Any]) -> list[str]:
    names: list[str] = []
    sequence = runtime_profile.get("sequence") if isinstance(runtime_profile.get("sequence"), list) else program.get("sequence")
    for action in as_list(sequence):
        if not isinstance(action, dict):
            continue
        action_name = str(action.get("action") or "").strip().lower()
        if action_name not in {"assert_visible", "click", "wait_until", "locate_image", "wait_until_image", "assert_text", "wait_until_text"}:
            continue
        target = str(action.get("target") or action.get("name") or "").strip()
        if target and target not in names:
            names.append(target)
    return names or ["ready_state", "start_button", "running_state", "complete_state"]


def configured_locator_names(locators: Any) -> list[str]:
    if not isinstance(locators, dict):
        return []
    names: list[str] = []
    for name, locator in locators.items():
        if isinstance(locator, dict) and str(name).strip():
            names.append(str(name))
    return sorted(dict.fromkeys(names))


def passive_utm_readiness(
    *,
    programs: dict[str, Any],
    profile_status: dict[str, Any],
    runtime_overrides: dict[str, Any],
) -> dict[str, Any]:
    profile = as_dict(profile_status.get("profile"))
    program_id = str(runtime_overrides.get("program_id") or profile.get("program_id") or DEFAULT_PROGRAM_ID).strip() or DEFAULT_PROGRAM_ID
    program = program_by_id(programs, program_id) or as_dict(profile_status.get("program"))
    runtime_profile = dict(profile)
    runtime_profile.setdefault("program_id", program_id)
    for key, value in runtime_overrides.items():
        if key in {"sequence", "locators"}:
            if value:
                runtime_profile[key] = value
            continue
        if value not in (None, ""):
            runtime_profile[key] = value

    locators = runtime_profile.get("locators") if isinstance(runtime_profile.get("locators"), dict) else {}
    required = required_utm_locator_names(runtime_profile, program)
    configured = configured_locator_names(locators)
    missing = [name for name in required if name not in set(configured)]
    export_glob = str(runtime_profile.get("export_glob") or "").strip()
    require_screen = bool(runtime_profile.get("require_screen_assertions", False))
    simulate = bool(runtime_profile.get("simulate_utm_protocol", False))

    blockers: list[str] = []
    warnings: list[str] = []
    if program_id not in program_ids(programs):
        blockers.append("UTM_PROGRAM_NOT_REGISTERED")
    if not export_glob:
        blockers.append("UTM_EXPORT_GLOB_MISSING")
    if require_screen and missing:
        blockers.append("UTM_REQUIRED_LOCATORS_MISSING")
    if profile_status.get("source") != "memory":
        warnings.append("UTM_PROFILE_USING_REGISTERED_DEFAULTS")
    if not locators:
        warnings.append("UTM_LOCATORS_NOT_CAPTURED")
    elif missing:
        warnings.append("UTM_LOCATOR_SET_INCOMPLETE")
    if not require_screen:
        warnings.append("UTM_SCREEN_ASSERTIONS_NOT_REQUIRED")
    if simulate:
        warnings.append("UTM_PROFILE_SIMULATION_ENABLED")

    status = "blocked" if blockers else "warning" if warnings else "ready"
    return {
        "ok": not blockers,
        "tool": "equipment.pyautogui.utm_readiness",
        "status": status,
        "bridge": "windows_pyautogui",
        "program_id": program_id,
        "ready_for_setup_test": not blockers,
        "ready_for_autonomous_profile": not blockers and require_screen and bool(locators) and not missing and not simulate,
        "runtime_overrides_applied": bool(runtime_overrides),
        "blockers": blockers,
        "warnings": warnings,
        "gates": {
            "utm_program_registered": program_id in program_ids(programs),
            "export_glob_configured": bool(export_glob),
            "locator_count": len(configured),
            "locator_names": configured,
            "required_locator_names": required,
            "missing_required_locators": missing,
            "required_locators_complete": not missing,
            "require_screen_assertions": require_screen,
            "simulate_utm_protocol": simulate,
            "profile_source": str(profile_status.get("source") or ""),
            "profile_memory_path": str(profile_status.get("profile_memory_path") or ""),
        },
        "next_actions": [
            item
            for item in [
                f"Register program {program_id}." if "UTM_PROGRAM_NOT_REGISTERED" in blockers else "",
                "Set the UTM export glob for the CSV file." if "UTM_EXPORT_GLOB_MISSING" in blockers else "",
                f"Capture required UTM locators: {', '.join(missing)}." if "UTM_REQUIRED_LOCATORS_MISSING" in blockers else "",
                "Capture UTM screen locators and enable screen assertions before live autonomous UTM." if "UTM_LOCATORS_NOT_CAPTURED" in warnings or "UTM_SCREEN_ASSERTIONS_NOT_REQUIRED" in warnings else "",
                "Disable bench simulation before live UTM." if "UTM_PROFILE_SIMULATION_ENABLED" in warnings else "",
            ]
            if item
        ],
    }


def pyautogui_available(health: dict[str, Any]) -> tuple[bool, str]:
    pyautogui = as_dict(health.get("pyautogui"))
    if pyautogui:
        available = pyautogui.get("available") is not False
        detail = "available" if available else str(pyautogui.get("error") or "pyautogui unavailable")
        return available, detail
    nested = as_dict(as_dict(health.get("health")).get("pyautogui"))
    if nested:
        available = nested.get("available") is not False
        detail = "available" if available else str(nested.get("error") or "pyautogui unavailable")
        return available, detail
    return False, "health response does not include pyautogui status"


def request_log_events(log_response: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in as_list(log_response.get("events")):
        if isinstance(item, dict):
            events.append(item)
    return events


def request_log_execute_seen(log_response: dict[str, Any]) -> bool:
    if log_response.get("execute_event_seen") is True:
        return True
    paths = [str(item or "") for item in as_list(log_response.get("recent_paths"))]
    if any(path == "/execute" or path.endswith("/execute") for path in paths):
        return True
    return any(str(event.get("path") or "") == "/execute" for event in request_log_events(log_response))


def request_log_identity_match(
    log_response: dict[str, Any],
    *,
    run_id: str,
    sequence_id: str,
    specimen_id: str,
    program_id: str,
) -> tuple[bool, dict[str, bool], str]:
    def values_for(key: str) -> set[str]:
        direct_key = {
            "run_id": "execute_run_ids",
            "sequence_id": "execute_sequence_ids",
            "specimen_id": "execute_specimen_ids",
            "program_id": "execute_program_ids",
        }.get(key, "")
        values = {str(item) for item in as_list(log_response.get(direct_key)) if str(item).strip()}
        last = as_dict(log_response.get("last_execute_context"))
        if last.get(key):
            values.add(str(last[key]))
        for event in request_log_events(log_response):
            if str(event.get("path") or "") == "/execute" and event.get(key):
                values.add(str(event[key]))
        return values

    checks = {
        "run_id": run_id in values_for("run_id"),
        "sequence_id": sequence_id in values_for("sequence_id"),
        "specimen_id": specimen_id in values_for("specimen_id"),
        "program_id": program_id in values_for("program_id"),
    }
    missing = [key for key, ok in checks.items() if not ok]
    if missing:
        return False, checks, "missing identity fields in request log: " + ", ".join(missing)
    return True, checks, "request log identity matches live validation payload"


def checkable_local_path(value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw or "://" in raw:
        return None
    if len(raw) >= 3 and raw[1] == ":" and raw[2] in {"\\", "/"}:
        return Path(raw).expanduser()
    candidate = Path(raw).expanduser()
    if candidate.is_absolute() or raw.startswith(".") or raw.startswith("~"):
        return candidate
    return candidate if candidate.exists() else None


def artifact_records(execution: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in ("artifact_records", "output_artifacts", "artifacts"):
        values = execution.get(key)
        if isinstance(values, list):
            records.extend([dict(item) for item in values if isinstance(item, dict)])
    return records


def resolved_artifact_path(ref: Any, records: list[dict[str, Any]]) -> tuple[Path | None, str]:
    direct = checkable_local_path(ref)
    if direct is not None:
        return direct, "direct"
    ref_text = str(ref or "").strip()
    if not ref_text:
        return None, "empty"
    for record in records:
        aliases = {
            str(record.get(key) or "")
            for key in ("artifact_id", "filename", "path", "local_path", "linux_path", "screenshot_artifact")
            if str(record.get(key) or "").strip()
        }
        if ref_text not in aliases:
            continue
        for key in ("local_path", "linux_path", "path"):
            candidate = checkable_local_path(record.get(key))
            if candidate is not None:
                return candidate, f"artifact_record.{key}"
    return None, "unresolved"


def image_signature_ok(path: Path) -> tuple[bool, str]:
    try:
        header = path.read_bytes()[:16]
    except OSError as exc:
        return False, str(exc)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True, "png"
    if header.startswith(b"\xff\xd8\xff"):
        return True, "jpeg"
    if header.startswith(b"BM"):
        return True, "bmp"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return True, "gif"
    return False, "unsupported image signature"


def screen_evidence_complete(execution: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    checks = [item for item in as_list(execution.get("screen_checks")) if isinstance(item, dict)]
    by_checkpoint = {str(item.get("checkpoint") or ""): item for item in checks}
    required = ["before_start", "after_start", "after_complete"]
    records = artifact_records(execution)
    missing: list[str] = []
    unresolved: list[str] = []
    missing_files: list[str] = []
    invalid_images: list[str] = []
    verified_files: list[str] = []
    observed_refs: list[str] = []
    for checkpoint in required:
        item = as_dict(by_checkpoint.get(checkpoint))
        ref = str(item.get("screenshot_artifact") or item.get("artifact") or item.get("path") or item.get("local_path") or "").strip()
        if item.get("ok") is not True or not ref:
            missing.append(checkpoint)
            continue
        observed_refs.append(ref)
        resolved, source = resolved_artifact_path(ref, records)
        if resolved is None:
            unresolved.append(f"{checkpoint}:{ref}")
            continue
        if resolved.exists() and resolved.is_file():
            image_ok, image_detail = image_signature_ok(resolved)
            if image_ok:
                verified_files.append(str(resolved))
            else:
                invalid_images.append(f"{checkpoint}:{resolved} ({image_detail}; {source})")
        else:
            missing_files.append(f"{checkpoint}:{resolved} ({source})")
    duplicate_refs = len(set(observed_refs)) < len(required)
    ok = not missing and not unresolved and not missing_files and not invalid_images and not duplicate_refs and len(set(verified_files)) >= len(required)
    if not ok:
        parts = []
        if missing:
            parts.append("missing checkpoints=" + ",".join(missing))
        if unresolved:
            parts.append("unresolved refs=" + ",".join(unresolved[:3]))
        if missing_files:
            parts.append("missing files=" + ",".join(missing_files[:3]))
        if invalid_images:
            parts.append("invalid image files=" + ",".join(invalid_images[:3]))
        if duplicate_refs:
            parts.append("duplicate screen refs")
        if len(set(verified_files)) < len(required):
            parts.append(f"verified_files={len(set(verified_files))}/{len(required)}")
        return False, "; ".join(parts), {"required": required, "observed": checks, "verified_files": verified_files, "unresolved_refs": unresolved, "missing_files": missing_files, "invalid_images": invalid_images}
    return True, f"before/start/complete screen image files verified; files={len(set(verified_files))}", {"required": required, "observed": checks, "verified_files": sorted(set(verified_files))}


def save_export_ok(execution: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    data = as_dict(execution.get("data_acquisition"))
    cross = as_dict(execution.get("cross_checks"))
    save_method = str(data.get("save_method") or "").strip()
    recognized_live_methods = {"windows_export_watch", "manual_save_dialog", "export_menu"}
    auto_methods = {"windows_export_watch"}
    save_attempted = data.get("save_attempted_by_agent") is True or save_method in auto_methods
    save_confirmed = data.get("save_confirmation_screen_ok") is True
    export_path_present = bool(str(data.get("windows_path") or data.get("linux_path") or data.get("local_path") or "").strip())
    bridge_claim = cross.get("save_export_responsibility_ok")
    ok = bool(save_method in recognized_live_methods and save_attempted and save_confirmed and export_path_present and bridge_claim is not False)
    detail = (
        f"method={save_method or '-'}; recognized={save_method in recognized_live_methods}; "
        f"attempted={save_attempted}; confirmation={save_confirmed}; path_present={export_path_present}; bridge_claim={bridge_claim}"
    )
    return ok, detail, {"data_acquisition": data, "cross_checks": cross, "recognized_live_methods": sorted(recognized_live_methods)}


def data_file_path(execution: dict[str, Any]) -> tuple[Path | None, str, str]:
    data = as_dict(execution.get("data_acquisition"))
    records = artifact_records(execution)
    for value in (execution.get("result_file"), execution.get("utm_csv_path"), data.get("linux_path"), data.get("local_path")):
        raw = str(value or "").strip()
        if not raw:
            continue
        path, source = resolved_artifact_path(raw, records)
        return path, raw, source
    return None, "", "missing"


def csv_signal_probe(path: Path) -> dict[str, Any]:
    required = ["time_s", "displacement_mm", "force_N"]
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            missing = [column for column in required if column not in columns]
            rows = list(reader)
    except Exception as exc:
        return {"ok": False, "failure_code": "UTM_DATA_PARSE_FAILED", "message": str(exc), "path": str(path)}
    if missing:
        return {"ok": False, "failure_code": "UTM_DATA_PARSE_FAILED", "message": "Missing UTM columns: " + ", ".join(missing), "columns_probe": columns, "path": str(path)}
    numeric_rows: list[dict[str, float]] = []
    for row in rows:
        try:
            numeric_rows.append({column: float(str(row.get(column, "")).strip()) for column in required})
        except Exception:
            continue
    if len(numeric_rows) < 2:
        return {"ok": False, "failure_code": "UTM_DATA_PARSE_FAILED", "message": "UTM export must contain at least two numeric data rows.", "row_count_probe": len(rows), "columns_probe": columns, "path": str(path)}
    times = [row["time_s"] for row in numeric_rows]
    displacements = [row["displacement_mm"] for row in numeric_rows]
    forces = [row["force_N"] for row in numeric_rows]
    time_monotonic = all(b >= a for a, b in zip(times, times[1:]))
    displacement_changes = max(displacements) != min(displacements)
    force_changes = max(forces) != min(forces)
    force_nonzero = any(abs(value) > 1e-9 for value in forces)
    if not time_monotonic:
        return {"ok": False, "failure_code": "UTM_DATA_NON_MONOTONIC_TIME", "message": "UTM time_s values are not monotonic non-decreasing.", "row_count_probe": len(rows), "columns_probe": columns, "path": str(path)}
    if not displacement_changes:
        return {"ok": False, "failure_code": "UTM_DATA_NO_DISPLACEMENT_SIGNAL", "message": "UTM displacement_mm does not change across samples.", "row_count_probe": len(rows), "columns_probe": columns, "path": str(path)}
    if not force_changes or not force_nonzero:
        return {"ok": False, "failure_code": "UTM_DATA_NO_FORCE_SIGNAL", "message": "UTM force_N has no nonzero changing load signal.", "row_count_probe": len(rows), "columns_probe": columns, "path": str(path)}
    return {
        "ok": True,
        "path": str(path),
        "row_count_probe": len(rows),
        "numeric_row_count": len(numeric_rows),
        "columns_probe": columns,
        "data_quality": {
            "time_monotonic": time_monotonic,
            "displacement_changes": displacement_changes,
            "force_changes": force_changes,
            "force_nonzero": force_nonzero,
        },
    }


def linux_data_ok(execution: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    data = as_dict(execution.get("data_acquisition"))
    artifact_pull = as_dict(execution.get("artifact_pull"))
    local_path, result_file, source = data_file_path(execution)
    pulled = data.get("status") == "pulled_to_linux" or artifact_pull.get("data_artifact_pulled") is True
    exists = bool(local_path and local_path.exists() and local_path.is_file())
    detail = f"pulled={pulled}; result_file={result_file or '-'}; resolved={local_path or '-'}; source={source}; exists={exists}; artifact_pull={artifact_pull.get('status', '-')}"
    return bool(pulled and exists), detail, {"data_acquisition": data, "artifact_pull": artifact_pull, "result_file": result_file, "local_path": str(local_path or ""), "path_source": source}


def parse_probe_ok(execution: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    data = as_dict(execution.get("data_acquisition"))
    cross = as_dict(execution.get("cross_checks"))
    artifact_pull = as_dict(execution.get("artifact_pull"))
    local_path, result_file, source = data_file_path(execution)
    if not local_path:
        return False, f"parse_ok=False; result_file={result_file or '-'}; source={source}", {"data_acquisition": data, "cross_checks": cross, "artifact_pull": artifact_pull, "result_file": result_file, "path_source": source}
    if not local_path.exists() or not local_path.is_file():
        return False, f"parse_ok=False; file missing: {local_path}", {"data_acquisition": data, "cross_checks": cross, "artifact_pull": artifact_pull, "result_file": result_file, "local_path": str(local_path), "path_source": source}
    probe = csv_signal_probe(local_path)
    ok = bool(probe.get("ok")) and cross.get("data_parse_probe_ok") is not False
    detail = f"parse_ok={ok}; rows={probe.get('row_count_probe', 0)}; columns={probe.get('columns_probe', [])}; path={local_path}"
    return ok, detail, {"data_acquisition": data, "cross_checks": cross, "artifact_pull": artifact_pull, "csv_probe": probe, "result_file": result_file, "local_path": str(local_path), "path_source": source}


def vision_frame_ids(value: Any) -> list[str]:
    frames: list[str] = []

    def collect(item: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(item, dict):
            for key in ("frame_ids", "evidence_frame_ids", "frames"):
                values = item.get(key)
                if isinstance(values, list):
                    frames.extend(str(value) for value in values if str(value or "").strip())
                elif isinstance(values, str) and values.strip():
                    frames.append(values.strip())
            for key in ("frame_id", "observation_id", "image_id", "artifact_id"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    frames.append(value.strip())
            for child in item.values():
                collect(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                collect(child, depth + 1)

    collect(value)
    return list(dict.fromkeys(frames))


def vision_proof_ok(vision_proof: dict[str, Any], *, run_id: str, specimen_id: str) -> tuple[bool, str, dict[str, Any]]:
    if not vision_proof:
        return False, "vision proof JSON was not provided", {"failure_code": VISION_REQUIRED_CODE}
    if vision_proof.get("ok") is False:
        return False, str(vision_proof.get("message") or "vision proof reports ok=false"), vision_proof
    checks = vision_proof.get("checks") if isinstance(vision_proof.get("checks"), dict) else vision_proof
    expected_true = ["utm_pre_start", "utm_motion_confirm", "utm_test_complete"]
    missing: list[str] = []
    missing_frames: list[str] = []
    check_identity_issues: list[str] = []
    for key in expected_true:
        value = checks.get(key) if isinstance(checks, dict) else None
        if isinstance(value, dict):
            if value.get("ok") is not True:
                missing.append(key)
            if not vision_frame_ids(value):
                missing_frames.append(key)
            identity = as_dict(value.get("identity"))
            missing_fields = as_list(identity.get("missing_fields"))
            mismatched_fields = as_list(identity.get("mismatched_fields"))
            if missing_fields or mismatched_fields or identity.get("match") is False:
                issue_parts = []
                if missing_fields:
                    issue_parts.append("missing=" + ",".join(str(item) for item in missing_fields))
                if mismatched_fields:
                    issue_parts.append("mismatch=" + ",".join(str(item) for item in mismatched_fields))
                if not issue_parts and identity.get("match") is False:
                    issue_parts.append("match=false")
                check_identity_issues.append(f"{key}({';'.join(issue_parts)})")
        elif value is not True:
            missing.append(key)
        else:
            missing_frames.append(key)
    id_missing: list[str] = []
    id_mismatches: list[str] = []
    for key, expected in {"run_id": run_id, "specimen_id": specimen_id}.items():
        observed = str(vision_proof.get(key) or as_dict(vision_proof.get("identity")).get(key) or "").strip()
        if not observed:
            id_missing.append(key)
        elif observed != expected:
            id_mismatches.append(f"{key}={observed} expected={expected}")
    frame_ids = vision_frame_ids(vision_proof)
    insufficient_unique_frames = len(frame_ids) < len(expected_true)
    if missing or missing_frames or insufficient_unique_frames or id_missing or id_mismatches or check_identity_issues:
        parts = []
        if missing:
            parts.append("missing/failed checks: " + ", ".join(missing))
        if missing_frames:
            parts.append("missing check frame evidence: " + ", ".join(missing_frames))
        if insufficient_unique_frames:
            parts.append(f"insufficient unique frame evidence: {len(frame_ids)}/{len(expected_true)}")
        if id_missing:
            parts.append("identity missing: " + ", ".join(id_missing))
        if id_mismatches:
            parts.append("identity mismatch: " + ", ".join(id_mismatches))
        if check_identity_issues:
            parts.append("check identity invalid: " + ", ".join(check_identity_issues))
        return False, "; ".join(parts), {**vision_proof, "evidence_frame_ids": frame_ids}
    return True, f"vision pre-start, motion, and complete proof present; frame_ids={len(frame_ids)}", {**vision_proof, "evidence_frame_ids": frame_ids}


def gate(name: str, ok: bool, detail: str, *, required: bool = True, evidence: Any = None, failure_code: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": name,
        "ok": bool(ok),
        "required": bool(required),
        "detail": detail,
    }
    if evidence is not None:
        item["evidence"] = evidence
    if failure_code:
        item["failure_code"] = failure_code
    return item


def evaluate_live_validation(
    *,
    run_id: str,
    sequence_id: str,
    specimen_id: str,
    program_id: str,
    health: dict[str, Any],
    programs: dict[str, Any],
    request_log_before: dict[str, Any],
    execution: dict[str, Any] | None,
    request_log_after: dict[str, Any],
    vision_proof: dict[str, Any],
    executed: bool,
    passive_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    execution_data = as_dict(execution)
    gates: list[dict[str, Any]] = []

    py_ok, py_detail = pyautogui_available(health)
    health_ok = health.get("ok") is True and py_ok
    gates.append(gate("bridge_health_pyautogui", health_ok, py_detail, evidence={"health_status": health.get("status"), "bridge_url": health.get("bridge_url"), "bridge_host": health.get("bridge_host")}))

    registered = program_id in program_ids(programs)
    gates.append(gate("program_registered", registered, f"program_id={program_id}", evidence={"program_ids": sorted(program_ids(programs))}))

    before_ok = request_log_before.get("ok") is True
    after_ok = request_log_after.get("ok") is True
    gates.append(gate("request_log_accessible", before_ok and after_ok, f"before={request_log_before.get('status', '-')}; after={request_log_after.get('status', '-')}", evidence={"before_count": request_log_before.get("event_count"), "after_count": request_log_after.get("event_count")}))

    if passive_readiness is not None:
        readiness_ok = bool(passive_readiness.get("ready_for_autonomous_profile"))
        blockers_text = ", ".join(str(item) for item in as_list(passive_readiness.get("blockers")) if str(item or "").strip()) or "-"
        warnings_text = ", ".join(str(item) for item in as_list(passive_readiness.get("warnings")) if str(item or "").strip()) or "-"
        gates.append(
            gate(
                "passive_utm_readiness",
                readiness_ok,
                f"status={passive_readiness.get('status', '-')}; blockers={blockers_text}; warnings={warnings_text}",
                evidence=passive_readiness,
            )
        )

    if not executed:
        gates.append(gate("execution_not_sent", True, "non-actuating preflight only; /execute was intentionally not sent", required=False))
    else:
        execution_ok = execution_data.get("ok") is True and str(execution_data.get("status") or "") in {"completed", "verified_complete", "data_ready", "exported_on_windows"}
        gates.append(gate("execution_completed", execution_ok, f"status={execution_data.get('status', '-')}; failure={execution_data.get('failure_code') or '-'}", evidence={"step_trace_count": len(as_list(execution_data.get("step_trace")))}, failure_code=str(execution_data.get("failure_code") or "") or None))

        execute_seen = request_log_execute_seen(request_log_after)
        gates.append(gate("request_log_execute_seen", execute_seen, "/execute present in bridge request log", evidence={"execute_event_count": request_log_after.get("execute_event_count")}))

        identity_ok, identity_checks, identity_detail = request_log_identity_match(request_log_after, run_id=run_id, sequence_id=sequence_id, specimen_id=specimen_id, program_id=program_id)
        gates.append(gate("request_log_identity_match", identity_ok, identity_detail, evidence=identity_checks))

        screen_ok, screen_detail, screen_evidence = screen_evidence_complete(execution_data)
        gates.append(gate("screen_state_evidence", screen_ok, screen_detail, evidence=screen_evidence))

        vision_ok, vision_detail, vision_evidence = vision_proof_ok(vision_proof, run_id=run_id, specimen_id=specimen_id)
        gates.append(gate("vision_physical_cross_check", vision_ok, vision_detail, evidence=vision_evidence, failure_code=None if vision_ok else VISION_REQUIRED_CODE))

        save_ok, save_detail, save_evidence = save_export_ok(execution_data)
        gates.append(gate("save_export_responsibility", save_ok, save_detail, evidence=save_evidence))

        linux_ok, linux_detail, linux_evidence = linux_data_ok(execution_data)
        gates.append(gate("linux_data_artifact", linux_ok, linux_detail, evidence=linux_evidence))

        parse_ok, parse_detail, parse_evidence = parse_probe_ok(execution_data)
        gates.append(gate("utm_csv_parse_probe", parse_ok, parse_detail, evidence=parse_evidence))

    blockers = [item for item in gates if item["required"] and not item["ok"]]
    status = "verified_complete" if executed and not blockers else "preflight_passed" if not executed and not blockers else "blocked"
    next_actions = []
    for item in blockers:
        next_actions.append({"gate": item["name"], "action": item["detail"], "failure_code": item.get("failure_code")})
    if not executed and not blockers:
        next_actions.append({"gate": "physical_live_run", "action": "Rerun with --confirm-live-execute after UTM fixture, Windows bridge, and Vision are physically ready."})

    return {
        "schema": SCHEMA,
        "ok": not blockers,
        "status": status,
        "created_at": utc_now(),
        "mode": "live",
        "non_actuating": not executed,
        "run_id": run_id,
        "sequence_id": sequence_id,
        "specimen_id": specimen_id,
        "program_id": program_id,
        "bridge": "windows_pyautogui",
        "summary": {
            "required_gate_count": len([item for item in gates if item["required"]]),
            "passed_required_gate_count": len([item for item in gates if item["required"] and item["ok"]]),
            "blocker_count": len(blockers),
            "physical_live_evidence_captured": executed and not blockers,
        },
        "gates": gates,
        "blockers": blockers,
        "next_actions": next_actions,
        "evidence": {
            "health": health,
            "programs": programs,
            "request_log_before": request_log_before,
            "execution": execution_data,
            "request_log_after": request_log_after,
            "vision_proof": vision_proof,
        },
    }


def build_live_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "runtime_mode": "live",
        "force_live_bridge": True,
        "confirm_setup_gui_execute": bool(args.confirm_live_execute),
        "sequence_id": args.sequence_id,
        "run_id": args.run_id,
        "specimen_id": args.specimen_id,
        "program_id": args.program_id,
        "require_screen_assertions": bool(args.require_screen_assertions),
        "require_window_focus": bool(args.require_window_focus),
        "artifact_timeout_s": float(args.artifact_timeout_s),
        "stable_for_sec": float(args.stable_for_sec),
    }
    if args.export_glob:
        payload["export_glob"] = args.export_glob
    if args.expected_export_path:
        payload["expected_export_path"] = args.expected_export_path
    if args.target_window:
        payload["target_window"] = args.target_window
    if args.target_window_regex:
        payload["target_window_regex"] = args.target_window_regex
    return payload


def write_report(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "lab_equipment_utm_live_validation.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--devices-config", default="configs/devices.yaml")
    parser.add_argument("--run-id", default=timestamp_id("utm-live-validation"))
    parser.add_argument("--sequence-id", default="")
    parser.add_argument("--specimen-id", default="specimen-live-validation")
    parser.add_argument("--program-id", default=DEFAULT_PROGRAM_ID)
    parser.add_argument("--confirm-live-execute", action="store_true", help="Actually send live /execute after preflight. Default is non-actuating.")
    parser.add_argument("--require-screen-assertions", action="store_true")
    parser.add_argument("--require-window-focus", action="store_true")
    parser.add_argument("--artifact-timeout-s", type=float, default=60.0)
    parser.add_argument("--stable-for-sec", type=float, default=2.0)
    parser.add_argument("--export-glob", default="*.csv")
    parser.add_argument("--expected-export-path", default="")
    parser.add_argument("--target-window", default="")
    parser.add_argument("--target-window-regex", default="")
    parser.add_argument("--vision-proof-json", default="", help="JSON file containing Vision UTM pre/motion/complete proof.")
    parser.add_argument("--out-dir", default="", help="Default: artifacts/equipment/<run_id>/live_validation")
    args = parser.parse_args(argv)
    if not args.sequence_id:
        args.sequence_id = args.run_id
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    devices_config_path = Path(args.devices_config)
    if not devices_config_path.is_absolute():
        devices_config_path = repo_root / devices_config_path
    out_dir = Path(args.out_dir) if args.out_dir else repo_root / "artifacts" / "equipment" / args.run_id / "live_validation"
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir

    cfg = load_devices_config(devices_config_path)
    bridge_cfg = WindowsPyAutoGUIBridgeConfig.from_devices_config(cfg, repo_root=repo_root)
    bridge = WindowsPyAutoGUIBridge(bridge_cfg)

    common = {"runtime_mode": "live", "force_live_bridge": True}
    health = bridge.health(common)
    programs = bridge.list_programs(common)
    profile_status = bridge.utm_profile_status()
    live_payload = build_live_payload(args)
    passive_readiness = passive_utm_readiness(
        programs=programs,
        profile_status=profile_status,
        runtime_overrides=live_payload,
    )
    request_before = bridge.request_log(common)
    execution: dict[str, Any] | None = None
    execute_sent = False
    if args.confirm_live_execute:
        if bool(passive_readiness.get("ready_for_autonomous_profile")):
            execution = bridge.run(live_payload)
            execute_sent = True
        else:
            execution = {
                "ok": False,
                "tool": "equipment.pyautogui.run",
                "status": "blocked",
                "failure_code": "UTM_PHYSICAL_VALIDATION_READINESS_BLOCKED",
                "message": "Physical UTM validation did not send /execute because passive UTM readiness is incomplete.",
                "bridge_not_called": True,
                "non_actuating": True,
                "run_id": args.run_id,
                "sequence_id": args.sequence_id,
                "specimen_id": args.specimen_id,
                "program_id": args.program_id,
                "readiness": passive_readiness,
                "step_trace": [
                    {"step": "PASSIVE_UTM_READINESS", "status": "blocked", "detail": str(passive_readiness.get("status") or "unknown")},
                ],
            }
    request_after = bridge.request_log(common)
    vision_proof = read_json_object(Path(args.vision_proof_json).resolve()) if args.vision_proof_json else {}

    report = evaluate_live_validation(
        run_id=args.run_id,
        sequence_id=args.sequence_id,
        specimen_id=args.specimen_id,
        program_id=args.program_id,
        health=health,
        programs=programs,
        request_log_before=request_before,
        execution=execution,
        request_log_after=request_after,
        vision_proof=vision_proof,
        executed=execute_sent,
        passive_readiness=passive_readiness,
    )
    report["inputs"] = {
        "repo_root": str(repo_root),
        "devices_config": str(devices_config_path),
        "out_dir": str(out_dir),
        "confirm_live_execute": bool(args.confirm_live_execute),
        "require_screen_assertions": bool(args.require_screen_assertions),
        "require_window_focus": bool(args.require_window_focus),
        "vision_proof_json": args.vision_proof_json,
        "requested_physical_execute": bool(args.confirm_live_execute),
        "execute_sent": execute_sent,
    }
    report["requested_physical_execute"] = bool(args.confirm_live_execute)
    report["execute_sent"] = execute_sent
    report["passive_readiness"] = passive_readiness
    report_path = write_report(report, out_dir)
    print(json.dumps({"ok": report["ok"], "status": report["status"], "report_path": str(report_path), "blocker_count": len(report.get("blockers", []))}, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
