"""Tests for the Improvement 05 UTM completion audit CLI."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
from pathlib import Path
from types import ModuleType


def _load_audit_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "audit_lab_equipment_utm_completion.py"
    spec = importlib.util.spec_from_file_location("audit_lab_equipment_utm_completion", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_completion_audit_fails_closed_without_proof_package() -> None:
    module = _load_audit_module()

    result = module.audit("", latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "PROOF_PACKAGE_PATH_REQUIRED" in result["blockers"]
    assert "PROOF_PACKAGE_NOT_AVAILABLE" in result["blockers"]


def test_latest_proof_package_picks_newest_artifact(tmp_path: Path) -> None:
    module = _load_audit_module()
    old_path = tmp_path / "artifacts" / "equipment" / "run-old" / "utm" / "windows_utm_proof_package_20260101T000000Z.json"
    new_path = tmp_path / "artifacts" / "equipment" / "run-new" / "utm" / "windows_utm_proof_package_20260102T000000Z.json"
    old_path.parent.mkdir(parents=True)
    new_path.parent.mkdir(parents=True)
    old_path.write_text("{}", encoding="utf-8")
    new_path.write_text("{}", encoding="utf-8")
    os.utime(old_path, (1_700_000_000, 1_700_000_000))
    os.utime(new_path, (1_700_000_100, 1_700_000_100))

    assert module._latest_proof_package(tmp_path) == new_path


TINY_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"atr-cli-proof-screen"


def _write_valid_cli_proof_package(module: ModuleType, run_name: str) -> tuple[Path, dict[str, object]]:
    root = Path(module.REPO_ROOT) / "artifacts" / "equipment" / run_name / "utm"
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / "utm_result.csv"
    csv_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n1,0.2,250\n", encoding="utf-8")
    screen_paths = []
    for name in ("before", "running", "complete"):
        screen_path = root / f"screen_{name}.png"
        screen_path.write_bytes(TINY_PNG_BYTES)
        screen_paths.append(screen_path)
    proof_path = root / "windows_utm_proof_package_20260530T000000Z.json"
    physical = {
        "ok": True,
        "source": "last_windows_utm_physical_validation",
        "requested_physical_execute": True,
        "execute_sent": True,
        "non_actuating": False,
        "status": "verified_complete",
        "run_id": run_name,
        "sequence_id": "seq-cli-proof",
        "specimen_id": "specimen-cli-proof",
        "program_id": "utm_compression_start_v1",
    }
    package: dict[str, object] = {
        "ok": True,
        "tool": "equipment.pyautogui.live_proof_package",
        "status": "ready_for_analysis",
        "ready_for_analysis": True,
        "proof_ready": True,
        "run_id": run_name,
        "package_artifact": {"kind": "windows_utm_proof_package", "path": str(proof_path), "local_path": str(proof_path)},
        "evidence_audit": {"status": "ready_for_analysis", "program_id": "utm_compression_start_v1"},
        "proof_checklist": [
            {"id": "physical_motion", "ok": True},
            {"id": "screen_evidence", "ok": True},
            {"id": "linux_artifact_pull", "ok": True},
            {"id": "save_export_responsibility", "ok": True},
        ],
        "manifest": {
            "proof_package_path": str(proof_path),
            "physical_execution": dict(physical),
            "request_log": {"execute_event_seen": True, "execute_event_count": 1, "execute_identity_match": True},
            "save_export": {
                "ok": True,
                "save_method": "windows_export_watch",
                "save_attempted_by_agent": True,
                "save_confirmation_screen_ok": True,
                "windows_path": "C:/ATR/utm_exports/specimen-cli-proof.csv",
                "linux_path": str(csv_path),
                "recognized_save_method": True,
            },
            "screen_evidence_refs": [str(item) for item in screen_paths],
            "screen_evidence_count": 3,
            "data_evidence_refs": [str(csv_path)],
            "data_evidence_count": 1,
            "linux_data_path": str(csv_path),
            "vision_frame_count": 3,
        },
        "source_packets": {
            "last_windows_utm_physical_validation": dict(physical),
            "last_windows_utm_result": {
                "artifact_records": [
                    {"kind": "screen_png", "artifact_id": f"screen-{idx}", "local_path": str(screen_path)}
                    for idx, screen_path in enumerate(screen_paths)
                ]
                + [{"kind": "utm_csv", "artifact_id": "utm-csv", "local_path": str(csv_path)}]
            },
        },
    }
    proof_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    return proof_path, package


def test_completion_audit_verifies_realistic_file_backed_proof_package() -> None:
    module = _load_audit_module()
    run_name = f"unit-cli-audit-{os.getpid()}"
    run_root = Path(module.REPO_ROOT) / "artifacts" / "equipment" / run_name
    try:
        proof_path, _package = _write_valid_cli_proof_package(module, run_name)
        result = module.audit(str(proof_path), latest=False)

        assert result["ok"] is True
        assert result["status"] == "complete_evidence_verified"
        assert result["verification"]["status"] == "verified"
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


def test_completion_audit_rejects_invalid_screen_image_and_physical_identity_mismatch() -> None:
    module = _load_audit_module()
    run_name = f"unit-cli-audit-negative-{os.getpid()}"
    run_root = Path(module.REPO_ROOT) / "artifacts" / "equipment" / run_name
    try:
        proof_path, package = _write_valid_cli_proof_package(module, run_name)
        first_screen = Path(package["manifest"]["screen_evidence_refs"][0])  # type: ignore[index]
        first_screen.write_text("not an image", encoding="utf-8")
        invalid_image = module.audit(str(proof_path), latest=False)
        assert invalid_image["ok"] is False
        assert "UTM_SCREEN_EVIDENCE_FILES_REQUIRED" in invalid_image["blockers"]

        first_screen.write_bytes(TINY_PNG_BYTES)
        mismatched = copy.deepcopy(package)
        mismatched["source_packets"]["last_windows_utm_physical_validation"]["program_id"] = "wrong_program"  # type: ignore[index]
        proof_path.write_text(json.dumps(mismatched, ensure_ascii=False, indent=2), encoding="utf-8")
        mismatch = module.audit(str(proof_path), latest=False)
        assert mismatch["ok"] is False
        assert "UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED" in mismatch["blockers"]
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
