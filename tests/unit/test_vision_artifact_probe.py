from __future__ import annotations

import json

import pytest

from scripts import verify_vision_multimodal as probe


def _fixture(tmp_path, *, nested=False, perturbation=None):
    raw = tmp_path / "raw.png"
    annotated = tmp_path / "annotated.png"
    raw.write_bytes(b"original raw bytes")
    annotated.write_bytes(b"original annotation bytes")
    capture = {
        "run_id": "archived-run", "loop_id": 7, "specimen_id": "original-specimen",
        "timestamp": "2026-09-01T00:00:00+00:00", "frame_id": "original-frame",
        "detected": True, "bbox_xyxy": [1, 2, 3, 4],
        "raw_frame_path": str(raw), "annotated_frame_path": str(annotated),
    }
    document = {"data": {"observation": {"raw_capture": capture}}} if nested else capture
    metadata = tmp_path / "result.json"
    metadata.write_text(json.dumps(document))
    case = {"case": "historical", "metadata_path": "result.json", "contract_id": "active_cam",
            "description": "Archived camera evidence", "expected_tool": "accept_visual_evidence"}
    if perturbation is not None:
        case["perturbation"] = perturbation
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([case]))
    return manifest, metadata, raw, annotated


def test_artifact_loader_preserves_capture_identity_and_original_timestamp(tmp_path):
    manifest, metadata, raw, annotated = _fixture(tmp_path)
    before = metadata.read_bytes()

    case = probe.load_artifact_cases(manifest)[0]

    assert case["capture"]["timestamp"] == "2026-09-01T00:00:00+00:00"
    assert case["capture"]["specimen_id"] == "original-specimen"
    assert case["capture"]["raw_frame_path"] == str(raw)
    assert set(case["source_image_sha256"]) == {str(raw), str(annotated)}
    assert metadata.read_bytes() == before


def test_archived_runtime_capture_restores_matching_state_and_session(tmp_path):
    manifest, _, _, _ = _fixture(tmp_path, nested=True)
    (tmp_path / "input.json").write_text(json.dumps({"state": {
        "run_id": "archived-run", "loop_count": 7, "experiment_id": "original-experiment",
        "current_experiment_spec": {"specimen_id": "original-specimen", "material": "PLA"},
        "run_metadata": {"manipulation_result": {"session_id": "original-session"}},
    }}))

    case = probe.load_artifact_cases(manifest)[0]
    state = probe.state_for_case(case, backend="vllm", timeout_s=45)

    assert state.run_id == "archived-run"
    assert state.loop_count == 7
    assert state.experiment_id == "original-experiment"
    assert state.current_experiment_spec["specimen_id"] == "original-specimen"
    assert state.run_metadata["manipulation_result"]["session_id"] == "original-session"
    assert case["capture"]["timestamp"] == "2026-09-01T00:00:00+00:00"


def test_artifact_perturbation_only_changes_in_memory_detector_and_annotation(tmp_path):
    alternate = tmp_path / "alternate.png"
    alternate.write_bytes(b"existing alternate annotation")
    manifest, metadata, raw, _ = _fixture(tmp_path, perturbation={
        "detector_facts": {"detected": False, "bbox_xyxy": []},
        "annotated_frame_path": "alternate.png",
    })
    before = metadata.read_bytes()

    case = probe.load_artifact_cases(manifest)[0]

    assert case["capture"]["detected"] is False
    assert case["capture"]["bbox_xyxy"] == []
    assert case["capture"]["annotated_frame_path"] == str(alternate)
    assert case["capture"]["raw_frame_path"] == str(raw)
    assert case["synthetic_perturbation"] is True
    assert metadata.read_bytes() == before
    assert raw.read_bytes() == b"original raw bytes"
    assert str(alternate) in case["source_image_sha256"]


def test_flat_detector_perturbation_updates_activecam_nested_evidence_only(tmp_path):
    manifest, metadata, _, _ = _fixture(tmp_path, perturbation={"detected": False})
    capture = json.loads(metadata.read_text())
    original_timestamp = capture.pop("timestamp")
    metadata.write_text(json.dumps({"timestamp": original_timestamp, "active_cam_ejection_check": capture}))

    case = probe.load_artifact_cases(manifest)[0]

    assert case["capture"]["timestamp"] == original_timestamp
    assert case["capture"]["active_cam_ejection_check"]["detected"] is False
    assert "detected" not in case["capture"]


@pytest.mark.parametrize("perturbation", [
    {"timestamp": "2099-01-01T00:00:00Z"},
    {"raw_frame_path": "replacement.png"},
    {"detector_facts": {"specimen_id": "changed"}},
])
def test_artifact_loader_rejects_identity_and_raw_image_perturbations(tmp_path, perturbation):
    manifest, _, _, _ = _fixture(tmp_path, perturbation=perturbation)

    with pytest.raises(ValueError, match="perturbation"):
        probe.load_artifact_cases(manifest)


def test_semantic_tool_expectation_does_not_turn_stale_gate_into_success():
    outcome = probe.decision_outcome({
        "status": "review_required", "failure_code": "VISION_EVIDENCE_EXPIRED",
        "request": {"tool": "accept_visual_evidence"},
    }, expected_tool="accept_visual_evidence")

    assert outcome == {"model_tool": "accept_visual_evidence", "model_accepted": True,
                       "final_status": "review_required", "semantic_expectation_met": True}


def test_absent_semantic_expectation_is_not_reported_as_pass():
    assert probe.decision_outcome({"status": "review_required"})["semantic_expectation_met"] is None


def test_probe_does_not_invent_material_when_archive_has_no_experiment_spec(tmp_path):
    manifest, _, _, _ = _fixture(tmp_path)
    state = probe.state_for_case(probe.load_artifact_cases(manifest)[0], backend="vllm", timeout_s=45)
    assert state.current_experiment_spec == {"specimen_id": "original-specimen"}
