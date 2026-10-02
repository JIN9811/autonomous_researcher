"""Tests for the Bambu autoejection physical completion audit CLI."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType


def _load_audit_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "audit_bambu_autoejection_completion.py"
    spec = importlib.util.spec_from_file_location("audit_bambu_autoejection_completion", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TINY_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"atr-bambu-ejection-proof"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_completion_audit_fails_closed_without_physical_proof_package() -> None:
    module = _load_audit_module()

    result = module.audit("", latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "PROOF_PACKAGE_PATH_REQUIRED" in result["blockers"]
    assert "BAMBU_PHYSICAL_CENTER_EJECTION_REQUIRED" in result["blockers"]
    assert "BAMBU_PHYSICAL_LIVE_EJECTION_REQUIRED" in result["blockers"]
    assert "BAMBU_BED_CLEAR_EVIDENCE_REQUIRED" in result["blockers"]
    assert "BAMBU_NEXT_JOB_GATE_REQUIRED" in result["blockers"]


def _write_complete_bambu_proof(tmp_path: Path) -> Path:
    evidence_dir = tmp_path / "bambu-proof"
    evidence_dir.mkdir()
    before = evidence_dir / "camera_before.png"
    after = evidence_dir / "camera_after.png"
    status = evidence_dir / "camera_status.png"
    for path in (before, after, status):
        path.write_bytes(TINY_PNG_BYTES)
    left_artifact = evidence_dir / "standalone.left.autoeject.gcode"
    center_artifact = evidence_dir / "standalone.center.autoeject.gcode"
    right_artifact = evidence_dir / "standalone.right.autoeject.gcode"
    left_artifact.write_text("; atr.bambu.autoejection.v1\n; atr_position=left\n", encoding="utf-8")
    center_artifact.write_text("; atr.bambu.autoejection.v1\n; atr_position=center\n", encoding="utf-8")
    right_artifact.write_text("; atr.bambu.autoejection.v1\n; atr_position=right\n", encoding="utf-8")
    left_validation = evidence_dir / "standalone.left.validation.json"
    right_validation = evidence_dir / "standalone.right.validation.json"
    for position, artifact, validation_path in (
        ("left", left_artifact, left_validation),
        ("right", right_artifact, right_validation),
    ):
        validation_path.write_text(
            json.dumps(
                {
                    "tool": "printer.bambu.autoejection.validate",
                    "ok": True,
                    "position": position,
                    "artifact_path": str(artifact),
                    "blockers": [],
                    "validation": {"ok": True, "blockers": []},
                }
            ),
            encoding="utf-8",
        )
    source_live_artifact = evidence_dir / "specimen.source.gcode.3mf"
    patched_live_artifact = evidence_dir / "specimen.autoeject.gcode.3mf"
    source_live_artifact.write_bytes(b"atr-source-bambu-gcode-3mf")
    patched_live_artifact.write_bytes(b"atr-patched-bambu-gcode-3mf\n; atr.bambu.autoejection.v1\n")
    source_sha = _sha256_file(source_live_artifact)
    patched_sha = _sha256_file(patched_live_artifact)
    manifest = evidence_dir / "bambu_autoejection_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "bambu_autoejection_artifact_manifest.v1",
                "source_sha256": source_sha,
                "patched_sha256": patched_sha,
                "validation": {"ok": True, "blockers": []},
            }
        ),
        encoding="utf-8",
    )
    prestart_snapshot = evidence_dir / "physical_start_precheck.json"
    prestart_snapshot.write_text(
        json.dumps(
            {
                "tool": "printer.bambu.prestart_check",
                "ok": True,
                "provider": "bambulab_x2d",
                "status": "ready_to_publish_not_started",
                "ready_to_publish": True,
                "published": False,
                "will_publish": False,
                "start_enabled": True,
                "steps": [
                    {"id": "camera_status", "ok": True, "status": "ok"},
                    {"id": "start_gate", "ok": True, "status": "ok"},
                ],
            }
        ),
        encoding="utf-8",
    )
    next_gate_snapshot = evidence_dir / "next_job_start_gate.json"
    next_gate_snapshot.write_text(
        json.dumps(
            {
                "tool": "printer.bambu.start_gate",
                "ok": True,
                "ready_to_publish": True,
                "start_enabled": True,
                "blockers": [],
                "gate_checks": {
                    "bed_clear": {
                        "ok": True,
                        "bed_clear_required": False,
                        "bed_clear_verified": True,
                        "blocking_code": "",
                    },
                    "printer_state": {"ok": True, "state": "idle"},
                },
            }
        ),
        encoding="utf-8",
    )
    live_publish_snapshot = evidence_dir / "live_start_publish.json"
    live_publish_snapshot.write_text(
        json.dumps(
            {
                "tool": "printer.bambu.start_publish",
                "ok": True,
                "provider": "bambulab_x2d",
                "published": True,
                "will_publish": True,
                "start_enabled": True,
                "ready_to_publish": True,
                "remote_path": "/cache/specimen.autoeject.gcode.3mf",
                "subtask_name": "specimen-live-proof",
                "publish_sequence_id": "seq-bambu-proof",
                "publish_topic": "device/20P6BJ642001425/request",
                "post_publish_status": "running",
                "publish_result": {
                    "ok": True,
                    "sequence_id": "seq-bambu-proof",
                    "topic": "device/20P6BJ642001425/request",
                },
                "post_publish_state": {"status": "running", "failure_code": ""},
            }
        ),
        encoding="utf-8",
    )
    center_publish_snapshot = evidence_dir / "center_start_publish.json"
    center_publish_snapshot.write_text(
        json.dumps(
            {
                "tool": "printer.bambu.start_publish",
                "ok": True,
                "provider": "bambulab_x2d",
                "published": True,
                "will_publish": True,
                "start_enabled": True,
                "ready_to_publish": True,
                "remote_path": "/cache/standalone.center.autoeject.gcode.3mf",
                "subtask_name": "center-ejection-proof",
                "publish_sequence_id": "seq-bambu-center-proof",
                "publish_topic": "device/20P6BJ642001425/request",
                "post_publish_status": "running",
                "publish_result": {
                    "ok": True,
                    "sequence_id": "seq-bambu-center-proof",
                    "topic": "device/20P6BJ642001425/request",
                },
                "post_publish_state": {"status": "running", "failure_code": ""},
            }
        ),
        encoding="utf-8",
    )
    left_publish_snapshot = evidence_dir / "left_start_publish.json"
    right_publish_snapshot = evidence_dir / "right_start_publish.json"
    for position, snapshot_path, sequence_id in (
        ("left", left_publish_snapshot, "seq-bambu-left-proof"),
        ("right", right_publish_snapshot, "seq-bambu-right-proof"),
    ):
        snapshot_path.write_text(
            json.dumps(
                {
                    "tool": "printer.bambu.start_publish",
                    "ok": True,
                    "provider": "bambulab_x2d",
                    "published": True,
                    "will_publish": True,
                    "start_enabled": True,
                    "ready_to_publish": True,
                    "remote_path": f"/cache/standalone.{position}.autoeject.gcode.3mf",
                    "subtask_name": f"{position}-ejection-proof",
                    "publish_sequence_id": sequence_id,
                    "publish_topic": "device/20P6BJ642001425/request",
                    "post_publish_status": "running",
                    "publish_result": {
                        "ok": True,
                        "sequence_id": sequence_id,
                        "topic": "device/20P6BJ642001425/request",
                    },
                    "post_publish_state": {"status": "running", "failure_code": ""},
                }
            ),
            encoding="utf-8",
        )
    proof_path = evidence_dir / "bambu_autoejection_physical_validation_20260616T000000Z.json"
    proof = {
        "schema": "bambu_autoejection_physical_validation.v1",
        "printer": {"provider": "bambulab", "profile_id": "bambulab_x2d"},
        "physical_start_precheck": {
            "ok": True,
            "published": False,
            "will_publish": False,
            "ready_to_publish_not_started": True,
            "prestart_snapshot_path": str(prestart_snapshot),
            "camera_snapshot_path": str(before),
        },
        "center_standalone_ejection": {
            "ok": True,
            "published": True,
            "post_publish_status": "running",
            "remote_path": "/cache/standalone.center.autoeject.gcode.3mf",
            "publish_sequence_id": "seq-bambu-center-proof",
            "publish_topic": "device/20P6BJ642001425/request",
            "publish_snapshot_path": str(center_publish_snapshot),
            "camera_before_path": str(before),
            "camera_after_path": str(after),
            "artifact_path": str(center_artifact),
            "object_cleared": True,
            "collision_observed": False,
            "toolhead_cover_shifted": False,
            "build_plate_shifted": False,
        },
        "disposable_live_ejection": {
            "ok": True,
            "tail_observed": True,
            "object_cleared": True,
            "bed_clear_locked": True,
            "remote_path": "/cache/specimen.autoeject.gcode.3mf",
            "source_artifact_path": str(source_live_artifact),
            "patched_artifact_path": str(patched_live_artifact),
            "source_artifact_sha256": source_sha,
            "patched_artifact_sha256": patched_sha,
            "manifest_path": str(manifest),
            "publish_sequence_id": "seq-bambu-proof",
            "publish_topic": "device/20P6BJ642001425/request",
            "publish_snapshot_path": str(live_publish_snapshot),
            "post_publish_status": "running",
            "camera_snapshot_path": str(status),
        },
        "left_right_lane": {
            "ok": True,
            "left_ok": True,
            "right_ok": True,
            "left_artifact_path": str(left_artifact),
            "right_artifact_path": str(right_artifact),
            "left_validation_snapshot_path": str(left_validation),
            "right_validation_snapshot_path": str(right_validation),
            "left_remote_path": "/cache/standalone.left.autoeject.gcode.3mf",
            "right_remote_path": "/cache/standalone.right.autoeject.gcode.3mf",
            "left_publish_sequence_id": "seq-bambu-left-proof",
            "right_publish_sequence_id": "seq-bambu-right-proof",
            "left_publish_topic": "device/20P6BJ642001425/request",
            "right_publish_topic": "device/20P6BJ642001425/request",
            "left_post_publish_status": "running",
            "right_post_publish_status": "running",
            "left_publish_snapshot_path": str(left_publish_snapshot),
            "right_publish_snapshot_path": str(right_publish_snapshot),
            "validator_blockers": [],
        },
        "post_ejection_bed_clear": {
            "ok": True,
            "bed_clear_verified": True,
            "blocking_code": "",
            "verification_method": "camera",
            "source_artifact_sha256": source_sha,
            "patched_artifact_sha256": patched_sha,
            "camera_snapshot_path": str(after),
        },
        "next_job_gate": {
            "ok": True,
            "no_bambu_post_eject_bed_not_clear": True,
            "printer_state_matches_idle_ready": True,
            "start_gate_snapshot_path": str(next_gate_snapshot),
        },
    }
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    return proof_path


def test_completion_audit_verifies_file_backed_bambu_physical_proof(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is True
    assert result["status"] == "complete_evidence_verified"
    assert result["verification"]["status"] == "verified"
    assert result["proof_package_path"] == str(proof_path)


def test_completion_audit_rejects_invalid_camera_and_missing_next_job_gate(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    invalid_camera = Path(proof["center_standalone_ejection"]["camera_after_path"])
    invalid_camera.write_text("not an image", encoding="utf-8")

    invalid_image = module.audit(str(proof_path), latest=False)

    assert invalid_image["ok"] is False
    assert "BAMBU_CAMERA_EVIDENCE_FILES_REQUIRED" in invalid_image["blockers"]

    invalid_camera.write_bytes(TINY_PNG_BYTES)
    missing_gate = copy.deepcopy(proof)
    missing_gate["next_job_gate"]["no_bambu_post_eject_bed_not_clear"] = False
    proof_path.write_text(json.dumps(missing_gate, ensure_ascii=False, indent=2), encoding="utf-8")

    gate_result = module.audit(str(proof_path), latest=False)

    assert gate_result["ok"] is False
    assert "BAMBU_NEXT_JOB_GATE_REQUIRED" in gate_result["blockers"]


def test_completion_audit_rejects_prestart_without_snapshot_evidence(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["physical_start_precheck"].pop("prestart_snapshot_path", None)
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PRESTART_VALIDATION_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_next_job_gate_without_snapshot_evidence(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["next_job_gate"].pop("start_gate_snapshot_path", None)
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_NEXT_JOB_GATE_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_reused_center_before_after_camera_file(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["center_standalone_ejection"]["camera_after_path"] = proof["center_standalone_ejection"]["camera_before_path"]
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_CAMERA_BEFORE_AFTER_DISTINCT_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_live_ejection_that_never_observed_printer_start(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["disposable_live_ejection"]["post_publish_status"] = "idle"
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED" in result["blockers"]


def test_completion_audit_rejects_center_ejection_that_never_observed_printer_start(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["center_standalone_ejection"]["post_publish_status"] = "idle"
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_CENTER_EJECTION_REQUIRED" in result["blockers"]
    assert "BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED" in result["blockers"]


def test_completion_audit_rejects_center_ejection_without_center_artifact(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["center_standalone_ejection"].pop("artifact_path", None)
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_CENTER_EJECTION_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_center_ejection_without_publish_snapshot(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["center_standalone_ejection"].pop("publish_snapshot_path", None)
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_CENTER_EJECTION_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_manifest_without_hashes_or_validation(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    manifest_path = Path(proof["disposable_live_ejection"]["manifest_path"])
    manifest_path.write_text('{"schema":"bambu_autoejection_artifact_manifest.v1"}\n', encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PATCH_MANIFEST_EVIDENCE_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_live_ejection_without_file_backed_artifacts(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["disposable_live_ejection"].pop("source_artifact_path", None)
    Path(proof["disposable_live_ejection"]["patched_artifact_path"]).write_bytes(b"tampered-patched-artifact")
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_LIVE_EJECTION_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_live_ejection_without_publish_snapshot(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["disposable_live_ejection"].pop("publish_snapshot_path", None)
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_LIVE_EJECTION_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_live_publish_snapshot_with_blocked_start_gate(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    snapshot_path = Path(proof["disposable_live_ejection"]["publish_snapshot_path"])
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["ready_to_publish"] = False
    snapshot["start_enabled"] = False
    snapshot["blockers"] = ["BAMBU_AUTOEJECTION_FRONT_PATH_NOT_CONFIRMED"]
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_LIVE_EJECTION_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_bed_clear_without_matching_artifact_hashes(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["post_ejection_bed_clear"].pop("source_artifact_sha256", None)
    proof["post_ejection_bed_clear"]["patched_artifact_sha256"] = "c" * 64
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_BED_CLEAR_EVIDENCE_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_boolean_only_left_right_lane_evidence(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["left_right_lane"].pop("left_artifact_path", None)
    proof["left_right_lane"].pop("right_artifact_path", None)
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_LEFT_RIGHT_EJECTION_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_left_right_lane_without_validation_snapshots(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["left_right_lane"].pop("left_validation_snapshot_path", None)
    right_validation = Path(proof["left_right_lane"]["right_validation_snapshot_path"])
    right_payload = json.loads(right_validation.read_text(encoding="utf-8"))
    right_payload["validation"]["blockers"] = ["BAMBU_SWEEP_OUTSIDE_ENVELOPE"]
    right_validation.write_text(json.dumps(right_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_LEFT_RIGHT_EJECTION_REQUIRED" in result["blockers"]


def test_completion_audit_rejects_left_right_lane_without_publish_snapshots(tmp_path: Path) -> None:
    module = _load_audit_module()
    proof_path = _write_complete_bambu_proof(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["left_right_lane"].pop("left_publish_snapshot_path", None)
    right_snapshot = Path(proof["left_right_lane"]["right_publish_snapshot_path"])
    right_payload = json.loads(right_snapshot.read_text(encoding="utf-8"))
    right_payload["start_enabled"] = False
    right_payload["blockers"] = ["BAMBU_AUTOEJECTION_RAMP_OR_BIN_NOT_CONFIRMED"]
    right_snapshot.write_text(json.dumps(right_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

    result = module.audit(str(proof_path), latest=False)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_LEFT_RIGHT_EJECTION_REQUIRED" in result["blockers"]


def test_completion_audit_template_scaffold_is_fail_closed(tmp_path: Path) -> None:
    module = _load_audit_module()
    template_path = tmp_path / "bambu_autoejection_physical_validation_template.json"

    template_result = module.write_proof_template(
        str(template_path),
        printer_profile_id="bambulab_x2d_lab_01",
        provider="bambulab",
    )

    assert template_result["ok"] is True
    assert template_result["status"] == "template_written_fail_closed"
    assert template_result["completion_ready"] is False
    assert template_path.exists()
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "bambu_autoejection_physical_validation.v1"
    assert payload["printer"]["provider"] == "bambulab"
    assert payload["printer"]["profile_id"] == "bambulab_x2d_lab_01"
    assert payload["physical_start_precheck"]["prestart_snapshot_path"] == ""
    assert payload["center_standalone_ejection"]["object_cleared"] is False
    assert payload["center_standalone_ejection"]["artifact_path"] == ""
    assert payload["center_standalone_ejection"]["publish_snapshot_path"] == ""
    assert payload["disposable_live_ejection"]["bed_clear_locked"] is False
    assert payload["disposable_live_ejection"]["source_artifact_path"] == ""
    assert payload["disposable_live_ejection"]["patched_artifact_path"] == ""
    assert payload["left_right_lane"]["left_validation_snapshot_path"] == ""
    assert payload["left_right_lane"]["right_validation_snapshot_path"] == ""
    assert payload["left_right_lane"]["left_publish_snapshot_path"] == ""
    assert payload["left_right_lane"]["right_publish_snapshot_path"] == ""
    assert payload["post_ejection_bed_clear"]["verification_method"] == ""
    assert payload["post_ejection_bed_clear"]["source_artifact_sha256"] == ""
    assert payload["post_ejection_bed_clear"]["patched_artifact_sha256"] == ""
    assert payload["next_job_gate"]["no_bambu_post_eject_bed_not_clear"] is False
    assert payload["next_job_gate"]["start_gate_snapshot_path"] == ""

    audit_result = module.audit(str(template_path), latest=False)

    assert audit_result["ok"] is False
    assert audit_result["status"] == "incomplete"
    assert "BAMBU_PHYSICAL_CENTER_EJECTION_REQUIRED" in audit_result["blockers"]
    assert "BAMBU_PHYSICAL_LIVE_EJECTION_REQUIRED" in audit_result["blockers"]
    assert "BAMBU_NEXT_JOB_GATE_REQUIRED" in audit_result["blockers"]
