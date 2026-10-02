"""Tests for the Lab Equipment live UTM validation runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_runner() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "lab_equipment_live_utm_validation.py"
    spec = importlib.util.spec_from_file_location("lab_equipment_live_utm_validation", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


TINY_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"atr-live-runner-screen"


def _health() -> dict[str, object]:
    return {
        "ok": True,
        "status": "ready",
        "bridge_url": "http://192.168.50.58:8765",
        "bridge_host": "192.168.50.58",
        "pyautogui": {"available": True, "failsafe": True, "pause": 0.1},
    }


def _programs() -> dict[str, object]:
    return {"ok": True, "status": "ready", "programs": [{"program_id": "utm_compression_start_v1"}]}


def _request_log(*, identity: bool = True) -> dict[str, object]:
    if identity:
        return {
            "ok": True,
            "status": "ready",
            "event_count": 2,
            "execute_event_seen": True,
            "execute_event_count": 1,
            "execute_run_ids": ["run-live-001"],
            "execute_sequence_ids": ["run-live-001"],
            "execute_specimen_ids": ["specimen-001"],
            "execute_program_ids": ["utm_compression_start_v1"],
            "events": [
                {
                    "path": "/execute",
                    "audit_kind": "execute_payload",
                    "run_id": "run-live-001",
                    "sequence_id": "run-live-001",
                    "specimen_id": "specimen-001",
                    "program_id": "utm_compression_start_v1",
                }
            ],
        }
    return {
        "ok": True,
        "status": "ready",
        "event_count": 1,
        "execute_event_seen": True,
        "execute_run_ids": ["other-run"],
        "execute_sequence_ids": ["other-seq"],
        "execute_specimen_ids": ["other-specimen"],
        "execute_program_ids": ["utm_compression_start_v1"],
    }


def _artifact_root() -> Path:
    root = Path("/tmp/atr_lab_equipment_live_validation_runner")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _screen_paths() -> list[Path]:
    root = _artifact_root()
    paths = [root / "screen-before.png", root / "screen-running.png", root / "screen-complete.png"]
    for path in paths:
        path.write_bytes(TINY_PNG_BYTES)
    return paths


def _csv_path() -> Path:
    path = _artifact_root() / "specimen.csv"
    path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.2,320\n", encoding="utf-8")
    return path


def _execution() -> dict[str, object]:
    screen_paths = _screen_paths()
    csv_path = _csv_path()
    return {
        "ok": True,
        "status": "verified_complete",
        "run_id": "run-live-001",
        "sequence_id": "run-live-001",
        "specimen_id": "specimen-001",
        "program_id": "utm_compression_start_v1",
        "result_file": str(csv_path),
        "utm_csv_path": str(csv_path),
        "screen_checks": [
            {"checkpoint": "before_start", "ok": True, "screenshot_artifact": "screen-before"},
            {"checkpoint": "after_start", "ok": True, "screenshot_artifact": "screen-running"},
            {"checkpoint": "after_complete", "ok": True, "screenshot_artifact": "screen-complete"},
        ],
        "artifact_records": [
            {"kind": "screen_png", "artifact_id": "screen-before", "local_path": str(screen_paths[0])},
            {"kind": "screen_png", "artifact_id": "screen-running", "local_path": str(screen_paths[1])},
            {"kind": "screen_png", "artifact_id": "screen-complete", "local_path": str(screen_paths[2])},
        ],
        "data_acquisition": {
            "status": "pulled_to_linux",
            "save_method": "manual_save_dialog",
            "save_attempted_by_agent": True,
            "save_confirmation_screen_ok": True,
            "windows_path": "C:/ATR/utm_exports/run-live-001/specimen.csv",
            "linux_path": str(csv_path),
            "row_count_probe": 120,
            "columns_probe": ["time_s", "displacement_mm", "force_N"],
            "local_parse_ok": True,
        },
        "artifact_pull": {
            "status": "complete",
            "data_artifact_pulled": True,
            "data_artifact_parse_ok": True,
        },
        "cross_checks": {
            "save_export_responsibility_ok": True,
            "data_parse_probe_ok": True,
        },
        "step_trace": [{"step": "DONE", "status": "ok"}],
    }


def _vision() -> dict[str, object]:
    return {
        "ok": True,
        "run_id": "run-live-001",
        "specimen_id": "specimen-001",
        "checks": {
            "utm_pre_start": {"ok": True, "evidence": {"frame_ids": ["frame-pre-001"]}},
            "utm_motion_confirm": {"ok": True, "evidence": {"frame_ids": ["frame-motion-001"]}},
            "utm_test_complete": {"ok": True, "evidence": {"frame_ids": ["frame-complete-001"]}},
        },
        "evidence": {"frame_ids": ["frame-pre-001", "frame-motion-001", "frame-complete-001"]},
    }


def test_preflight_only_does_not_require_execute_or_vision() -> None:
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=None,
        request_log_after={"ok": True, "status": "ready", "events": []},
        vision_proof={},
        executed=False,
    )

    assert report["ok"] is True
    assert report["status"] == "preflight_passed"
    assert report["non_actuating"] is True
    assert any(item["name"] == "execution_not_sent" and item["required"] is False for item in report["gates"])


def _readiness_profile(*, locators: dict[str, object], require_screen: bool = True) -> dict[str, object]:
    return {
        "source": "memory",
        "profile": {
            "program_id": "utm_compression_start_v1",
            "export_glob": "*.csv",
            "require_screen_assertions": require_screen,
            "locators": locators,
        },
    }


def test_passive_readiness_blocks_preflight_when_required_locators_missing() -> None:
    readiness = runner.passive_utm_readiness(
        programs=_programs(),
        profile_status=_readiness_profile(locators={"ready_state": {}}),
        runtime_overrides={"program_id": "utm_compression_start_v1"},
    )
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=None,
        request_log_after={"ok": True, "status": "ready", "events": []},
        vision_proof={},
        executed=False,
        passive_readiness=readiness,
    )

    assert readiness["ready_for_autonomous_profile"] is False
    assert "UTM_REQUIRED_LOCATORS_MISSING" in readiness["blockers"]
    assert report["ok"] is False
    assert report["status"] == "blocked"
    passive_gate = next(item for item in report["gates"] if item["name"] == "passive_utm_readiness")
    assert passive_gate["ok"] is False


def test_passive_readiness_accepts_complete_screen_assertion_profile() -> None:
    locators = {name: {"image_path": f"C:/ATR/locators/{name}.png"} for name in ("ready_state", "start_button", "running_state", "complete_state")}
    readiness = runner.passive_utm_readiness(
        programs=_programs(),
        profile_status=_readiness_profile(locators=locators),
        runtime_overrides={"program_id": "utm_compression_start_v1"},
    )

    assert readiness["status"] == "ready"
    assert readiness["ready_for_autonomous_profile"] is True
    assert readiness["gates"]["missing_required_locators"] == []


def test_full_live_success_requires_all_equipment_gates() -> None:
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=_execution(),
        request_log_after=_request_log(identity=True),
        vision_proof=_vision(),
        executed=True,
    )

    assert report["ok"] is True
    assert report["status"] == "verified_complete"
    assert report["summary"]["physical_live_evidence_captured"] is True
    assert {item["name"] for item in report["gates"]} >= {
        "execution_completed",
        "request_log_identity_match",
        "screen_state_evidence",
        "vision_physical_cross_check",
        "save_export_responsibility",
        "linux_data_artifact",
        "utm_csv_parse_probe",
    }


def test_identity_mismatch_blocks_full_live_validation() -> None:
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=_execution(),
        request_log_after=_request_log(identity=False),
        vision_proof=_vision(),
        executed=True,
    )

    assert report["ok"] is False
    blockers = {item["name"] for item in report["blockers"]}
    assert "request_log_identity_match" in blockers


def test_screen_evidence_without_file_backing_blocks_full_live_validation() -> None:
    execution = _execution()
    execution.pop("artifact_records", None)
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=execution,
        request_log_after=_request_log(identity=True),
        vision_proof=_vision(),
        executed=True,
    )

    assert report["ok"] is False
    screen_blockers = [item for item in report["blockers"] if item["name"] == "screen_state_evidence"]
    assert screen_blockers
    assert "unresolved refs" in screen_blockers[0]["detail"]


def test_screen_evidence_with_duplicate_ref_blocks_full_live_validation() -> None:
    execution = _execution()
    execution["screen_checks"] = [
        {"checkpoint": "before_start", "ok": True, "screenshot_artifact": "screen-before"},
        {"checkpoint": "after_start", "ok": True, "screenshot_artifact": "screen-before"},
        {"checkpoint": "after_complete", "ok": True, "screenshot_artifact": "screen-before"},
    ]
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=execution,
        request_log_after=_request_log(identity=True),
        vision_proof=_vision(),
        executed=True,
    )

    assert report["ok"] is False
    screen_blockers = [item for item in report["blockers"] if item["name"] == "screen_state_evidence"]
    assert screen_blockers
    assert "duplicate screen refs" in screen_blockers[0]["detail"]


def test_screen_evidence_with_non_image_file_blocks_full_live_validation() -> None:
    execution = _execution()
    bad_screen = Path(str(execution["artifact_records"][1]["local_path"]))
    bad_screen.write_text("not an image", encoding="utf-8")
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=execution,
        request_log_after=_request_log(identity=True),
        vision_proof=_vision(),
        executed=True,
    )

    assert report["ok"] is False
    screen_blockers = [item for item in report["blockers"] if item["name"] == "screen_state_evidence"]
    assert screen_blockers
    assert "invalid image files" in screen_blockers[0]["detail"]


def test_save_export_boolean_only_blocks_full_live_validation() -> None:
    execution = _execution()
    data = execution["data_acquisition"]
    data["save_method"] = ""
    data["save_attempted_by_agent"] = False
    data["save_confirmation_screen_ok"] = False
    data["windows_path"] = ""
    execution["cross_checks"]["save_export_responsibility_ok"] = True
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=execution,
        request_log_after=_request_log(identity=True),
        vision_proof=_vision(),
        executed=True,
    )

    assert report["ok"] is False
    save_blockers = [item for item in report["blockers"] if item["name"] == "save_export_responsibility"]
    assert save_blockers
    assert "recognized=False" in save_blockers[0]["detail"]


def test_save_export_without_confirmation_blocks_full_live_validation() -> None:
    execution = _execution()
    execution["data_acquisition"]["save_confirmation_screen_ok"] = False
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=execution,
        request_log_after=_request_log(identity=True),
        vision_proof=_vision(),
        executed=True,
    )

    assert report["ok"] is False
    save_blockers = [item for item in report["blockers"] if item["name"] == "save_export_responsibility"]
    assert save_blockers
    assert "confirmation=False" in save_blockers[0]["detail"]


def test_missing_linux_csv_blocks_full_live_validation() -> None:
    execution = _execution()
    csv_path = Path(str(execution["result_file"]))
    csv_path.unlink()
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=execution,
        request_log_after=_request_log(identity=True),
        vision_proof=_vision(),
        executed=True,
    )

    assert report["ok"] is False
    blockers = {item["name"] for item in report["blockers"]}
    assert "linux_data_artifact" in blockers
    assert "utm_csv_parse_probe" in blockers


def test_flat_linux_csv_signal_blocks_full_live_validation() -> None:
    execution = _execution()
    csv_path = Path(str(execution["result_file"]))
    csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0,0\n", encoding="utf-8")
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=execution,
        request_log_after=_request_log(identity=True),
        vision_proof=_vision(),
        executed=True,
    )

    assert report["ok"] is False
    parse_blockers = [item for item in report["blockers"] if item["name"] == "utm_csv_parse_probe"]
    assert parse_blockers
    assert "parse_ok=False" in parse_blockers[0]["detail"]


def test_vision_proof_without_frame_evidence_blocks_full_live_validation() -> None:
    vision = _vision()
    vision["checks"] = {
        "utm_pre_start": {"ok": True},
        "utm_motion_confirm": {"ok": True},
        "utm_test_complete": {"ok": True},
    }
    vision.pop("evidence", None)
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=_execution(),
        request_log_after=_request_log(identity=True),
        vision_proof=vision,
        executed=True,
    )

    assert report["ok"] is False
    vision_blockers = [item for item in report["blockers"] if item["name"] == "vision_physical_cross_check"]
    assert vision_blockers
    assert "missing check frame evidence" in vision_blockers[0]["detail"]


def test_vision_proof_with_duplicate_frame_ids_blocks_full_live_validation() -> None:
    vision = _vision()
    for item in vision["checks"].values():
        item["evidence"] = {"frame_ids": ["same-frame-001"]}
    vision["evidence"] = {"frame_ids": ["same-frame-001"]}
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=_execution(),
        request_log_after=_request_log(identity=True),
        vision_proof=vision,
        executed=True,
    )

    assert report["ok"] is False
    vision_blockers = [item for item in report["blockers"] if item["name"] == "vision_physical_cross_check"]
    assert vision_blockers
    assert "insufficient unique frame evidence: 1/3" in vision_blockers[0]["detail"]


def test_vision_proof_without_identity_blocks_full_live_validation() -> None:
    vision = _vision()
    vision.pop("run_id", None)
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=_execution(),
        request_log_after=_request_log(identity=True),
        vision_proof=vision,
        executed=True,
    )

    assert report["ok"] is False
    vision_blockers = [item for item in report["blockers"] if item["name"] == "vision_physical_cross_check"]
    assert vision_blockers
    assert "identity missing: run_id" in vision_blockers[0]["detail"]


def test_missing_vision_proof_blocks_full_live_validation() -> None:
    report = runner.evaluate_live_validation(
        run_id="run-live-001",
        sequence_id="run-live-001",
        specimen_id="specimen-001",
        program_id="utm_compression_start_v1",
        health=_health(),
        programs=_programs(),
        request_log_before={"ok": True, "status": "ready", "events": []},
        execution=_execution(),
        request_log_after=_request_log(identity=True),
        vision_proof={},
        executed=True,
    )

    assert report["ok"] is False
    vision_blockers = [item for item in report["blockers"] if item["name"] == "vision_physical_cross_check"]
    assert vision_blockers
    assert vision_blockers[0]["failure_code"] == "VISION_PROOF_REQUIRED"
