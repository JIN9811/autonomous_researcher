from __future__ import annotations

import base64
import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main_module
from backends.llm_backend import LLMResponse
from utils.equipment_skill_runtime import canonical_sha256


def _recording() -> dict:
    return {
        "schema": "atr.equipment_recording.v1",
        "recording_id": "rec-program1-api",
        "name": "Program 1 demonstration",
        "target_app": "Program 1",
        "target_window": "Program 1",
        "status": "saved",
        "events": [
            {"kind": "mouse_click", "at_ms": 100, "x": 100, "y": 120, "button": "left"},
            {"kind": "key_press", "at_ms": 200, "key": "enter"},
        ],
        "checkpoints": [],
    }


def _complex_recording() -> dict:
    return {
        "schema": "atr.equipment_recording.v1",
        "recording_id": "rec-complex-api",
        "name": "Complex desktop operation",
        "target_app": "Capability Lab",
        "target_window": "ATR PyAutoGUI Capability Lab",
        "status": "saved",
        "events": [
            {
                "kind": "mouse_drag",
                "at_ms": 100,
                "start_x": 120,
                "start_y": 160,
                "x": 360,
                "y": 240,
                "button": "left",
                "duration_sec": 0.4,
            },
            {"kind": "mouse_scroll", "at_ms": 600, "dx": 2, "dy": -4},
            {"kind": "key_press", "at_ms": 700, "key": "a"},
            {"kind": "key_press", "at_ms": 710, "key": "space"},
            {"kind": "key_press", "at_ms": 720, "key": "b"},
            {"kind": "hotkey", "at_ms": 800, "keys": ["ctrl", "a"]},
        ],
        "checkpoints": [],
    }


def _image_first_recording() -> dict:
    raw = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    candidate = {
        "kind": "tight",
        "png_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": 64,
        "height": 64,
        "confidence": 0.88,
    }
    return {
        "schema": "atr.equipment_recording.v2",
        "recording_id": "rec-image-first-api",
        "name": "Image tracked demonstration",
        "target_app": "Program 1",
        "target_window": "Program 1",
        "status": "saved",
        "visual_locator_policy": {
            "mode": "image_first",
            "required_for_pointer_actions": True,
            "coordinate_fallback": False,
        },
        "events": [
            {
                "kind": "mouse_click",
                "at_ms": 100,
                "x": 100,
                "y": 120,
                "button": "left",
                "visual_locator": {
                    "locator_id": "evt-0001-target",
                    "status": "ready",
                    "recorded_coordinate": [100, 120],
                    "candidates": [candidate],
                },
            }
        ],
        "checkpoints": [],
    }


def _png_candidate(width: int, height: int, color: str = "#2563eb") -> dict:
    from io import BytesIO

    output = BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="PNG")
    raw = output.getvalue()
    return {
        "kind": "manual_target",
        "png_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": width,
        "height": height,
        "confidence": 1.0,
    }


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(main_module, "EQUIPMENT_SKILL_ROOT", tmp_path / "skills")
    monkeypatch.setattr(main_module, "EQUIPMENT_RUNTIME_ROOT", tmp_path / "equipment_runtime")
    monkeypatch.setattr(main_module, "EQUIPMENT_SKILL_AUTHORING_JOB_ROOT", tmp_path / "skill_authoring_jobs")
    return TestClient(main_module.app)


def test_raw_csv_skill_modes_require_context_and_confirmation(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class Registry:
        def get(self, skill_id: str, version: str) -> dict:
            assert (skill_id, version) == ("utm_save_raw_data", "1.0.7")
            return {
                "manifest": {
                    "lifecycle": "deployed",
                    "enabled": True,
                    "deployment": {"bridge_id": "windows-lab-1"},
                },
                "workflow": {"program_ids": ["utm_save_raw_data_1_0_7_segment_001"]},
            }

        def record_test(self, skill_id: str, version: str, summary: dict) -> None:
            return None

    class Bridge:
        def run(self, payload: dict) -> dict:
            calls.append(dict(payload))
            return {
                "ok": True,
                "status": "dry_run_ready" if payload["runtime_mode"] == "dry_run" else "completed",
                "raw_csv_export": {"available": True},
            }

    monkeypatch.setattr(main_module, "_equipment_skill_registry", lambda: Registry())
    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())
    client = _client(monkeypatch, tmp_path)
    base_context = {
        "session_id": "session-20260902-A",
        "specimen_id": "cube-03",
        "loop_index": 2,
        "repeat_index": 4,
    }

    dry = client.post(
        "/api/equipment/skills/utm_save_raw_data/1.0.7/test",
        json={
            "runtime_mode": "dry_run",
            "confirm_execute": False,
            "export_context": {"mode": "dry_run", **base_context},
        },
    )
    blocked = client.post(
        "/api/equipment/skills/utm_save_raw_data/1.0.7/test",
        json={
            "runtime_mode": "test",
            "confirm_execute": False,
            "export_context": {"mode": "test", **base_context},
        },
    )
    live_defaults = client.post(
        "/api/equipment/skills/utm_save_raw_data/1.0.7/test",
        json={"runtime_mode": "live", "confirm_execute": True, "export_context": {"mode": "live"}},
    )

    assert dry.status_code == 200
    assert dry.json()["program_results"][0]["status"] == "dry_run_ready"
    assert blocked.status_code == 422
    assert live_defaults.status_code == 422
    assert calls == [
        {
            "program_id": "utm_save_raw_data_1_0_7_segment_001",
            "runtime_mode": "dry_run",
            "confirm_execute": False,
            "bridge_id": "windows-lab-1",
            "force_live_bridge": True,
            "sequence_id": "skill-test-utm_save_raw_data-1.0.7-001",
            "export_context": {"mode": "dry_run", **base_context},
        }
    ]


def test_skill_test_passes_declared_runtime_context(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class Registry:
        def get(self, skill_id: str, version: str) -> dict:
            assert (skill_id, version) == ("utm_validate_raw_data", "1.0.7")
            return {
                "manifest": {
                    "lifecycle": "deployed",
                    "enabled": True,
                    "deployment": {"bridge_id": "windows-lab-1"},
                },
                "workflow": {
                    "program_ids": ["utm_validate_raw_data_1_0_7_segment_001"],
                    "steps": [{"action": "wait_for_file", "pattern": "{raw_csv_path}"}],
                },
            }

        def record_test(self, skill_id: str, version: str, summary: dict) -> None:
            return None

    class Bridge:
        def run(self, payload: dict) -> dict:
            calls.append(dict(payload))
            return {"ok": True, "status": "completed"}

    monkeypatch.setattr(main_module, "_equipment_skill_registry", lambda: Registry())
    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/equipment/skills/utm_validate_raw_data/1.0.7/test",
        json={
            "runtime_mode": "dry_run",
            "runtime_context": {
                "raw_csv_path": r"C:\ATR\raw.csv",
                "ignored": "not-declared",
            },
        },
    )

    assert response.status_code == 200
    assert calls[0]["runtime_values"] == {"raw_csv_path": r"C:\ATR\raw.csv"}


def test_saved_worker_update_routes_address_path_candidate_without_changing_selection(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict]] = []

    class Bridge:
        def worker_update_status(self, payload: dict) -> dict:
            calls.append(("status", dict(payload)))
            return {"ok": True, "current_version": "1", "latest_version": "2", "update_available": True}

        def update_worker(self, payload: dict) -> dict:
            calls.append(("update", dict(payload)))
            return {"ok": True, "status": "update_restarting"}

        def rollback_worker(self, payload: dict) -> dict:
            calls.append(("rollback", dict(payload)))
            return {"ok": True, "status": "rollback_restarting"}

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())
    client = _client(monkeypatch, tmp_path)

    status = client.get("/api/equipment/windows/workers/nextpc/update")
    update = client.post("/api/equipment/windows/workers/nextpc/update")
    rollback = client.post("/api/equipment/windows/workers/nextpc/rollback")

    assert status.status_code == 200
    assert update.status_code == 200
    assert rollback.status_code == 200
    assert calls == [
        ("status", {"candidate_alias": "nextpc"}),
        ("update", {"candidate_alias": "nextpc"}),
        ("rollback", {"candidate_alias": "nextpc"}),
    ]


def test_equipment_runtime_api_projects_one_authoritative_execution(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    service = main_module._equipment_runtime_service()
    execution = service.begin(
        sequence_id="run-api-equipment-1",
        run_id="run-api",
        experiment_id="exp-api",
        specimen_id="specimen-api",
        profile_id="utm_windows_v1",
        mode="test",
        worker={"worker_id": "simulator", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "utm_compression_start_v1"},
    )

    listed = client.get("/api/equipment/runtime/executions")
    detail = client.get(f"/api/equipment/runtime/executions/{execution['execution_id']}")

    assert listed.status_code == 200
    assert listed.json()["executions"][0]["execution_id"] == execution["execution_id"]
    assert listed.json()["projections"][0]["schema"] == "atr.equipment_execution_projection.v1"
    assert detail.status_code == 200
    assert detail.json()["execution"]["schema"] == "atr.equipment_execution.v1"
    assert detail.json()["projection"]["execution_id"] == execution["execution_id"]


def test_equipment_runtime_current_api_returns_latest_projection(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    service = main_module._equipment_runtime_service()
    first = service.begin(
        sequence_id="run-current-equipment-1",
        run_id="run-current",
        experiment_id="exp-current",
        specimen_id="specimen-current-1",
        profile_id="utm_windows_v1",
        mode="test",
        worker={"worker_id": "simulator", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "utm_compression_start_v1"},
    )
    second = service.begin(
        sequence_id="run-current-equipment-2",
        run_id="run-current",
        experiment_id="exp-current",
        specimen_id="specimen-current-2",
        profile_id="utm_windows_v1",
        mode="test",
        worker={"worker_id": "simulator", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "utm_compression_start_v1"},
    )
    service.transition(
        second["execution_id"],
        "PREFLIGHT",
        status="preflight",
        detail="latest execution",
    )

    response = client.get("/api/equipment/runtime/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["execution"]["execution_id"] == second["execution_id"]
    assert payload["projection"]["execution_id"] == second["execution_id"]
    assert payload["projection"]["lifecycle"] == "PREFLIGHT"
    assert payload["execution"]["execution_id"] != first["execution_id"]


def test_equipment_runtime_current_api_filters_by_run_id(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    service = main_module._equipment_runtime_service()
    expected = service.begin(
        sequence_id="run-filter-a-equipment-1",
        run_id="run-filter-a",
        experiment_id="exp-filter-a",
        specimen_id="specimen-filter-a",
        profile_id="utm_windows_v1",
        mode="test",
        worker={"worker_id": "simulator", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "utm_compression_start_v1"},
    )
    service.begin(
        sequence_id="run-filter-b-equipment-1",
        run_id="run-filter-b",
        experiment_id="exp-filter-b",
        specimen_id="specimen-filter-b",
        profile_id="utm_windows_v1",
        mode="test",
        worker={"worker_id": "simulator", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "utm_compression_start_v1"},
    )

    response = client.get("/api/equipment/runtime/current?run_id=run-filter-a")

    assert response.status_code == 200
    assert response.json()["execution"]["execution_id"] == expected["execution_id"]


def _validated_skill(client: TestClient) -> dict:
    client.post(
        "/api/equipment/skills/drafts",
        json={
            "recording": _recording(),
            "skill_id": "program1_skill",
            "version": "1.0.0",
            "target_profile": "local_program1",
        },
    ).raise_for_status()
    client.post(
        "/api/equipment/skills/program1_skill/1.0.0/annotate",
        json={
            "use_model": False,
            "annotations": {
                "steps": [
                    {"step_id": "step-001", "label": "Click demo", "confidence": 0.95, "review_required": False},
                    {"step_id": "step-002", "label": "Confirm demo", "confidence": 0.95, "review_required": False},
                ]
            },
        },
    ).raise_for_status()
    client.post("/api/equipment/skills/program1_skill/1.0.0/compile").raise_for_status()
    client.post("/api/equipment/skills/program1_skill/1.0.0/validate").raise_for_status()
    return client.get("/api/equipment/skills/program1_skill/1.0.0").json()


def _annotated_skill(client: TestClient) -> dict:
    client.post(
        "/api/equipment/skills/drafts",
        json={
            "recording": _recording(),
            "skill_id": "program1_skill",
            "version": "1.0.0",
            "target_profile": "local_program1",
        },
    ).raise_for_status()
    client.post(
        "/api/equipment/skills/program1_skill/1.0.0/annotate",
        json={
            "use_model": False,
            "annotations": {
                "steps": [
                    {"step_id": "step-001", "label": "Click demo", "confidence": 0.95, "review_required": False},
                    {"step_id": "step-002", "label": "Confirm demo", "confidence": 0.95, "review_required": False},
                ]
            },
        },
    ).raise_for_status()
    return client.get("/api/equipment/skills/program1_skill/1.0.0").json()


def test_workflow_api_load_save_check_and_hash_conflict(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    _annotated_skill(client)

    loaded = client.get("/api/equipment/skills/program1_skill/1.0.0/workflow")
    assert loaded.status_code == 200
    body = loaded.json()
    assert body["editable"] is True
    assert body["workflow_sha256"] == body["manifest"]["workflow_sha256"]

    checked = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/workflow/check",
        json={"workflow": body["workflow"]},
    )
    assert checked.status_code == 200
    assert checked.json()["ok"] is True

    edited = dict(body["workflow"])
    edited["steps"] = list(reversed(edited["steps"]))
    saved = client.put(
        "/api/equipment/skills/program1_skill/1.0.0/workflow",
        json={"expected_workflow_sha256": body["workflow_sha256"], "workflow": edited},
    )
    assert saved.status_code == 200
    assert saved.json()["manifest"]["lifecycle"] == "annotated"

    conflict = client.put(
        "/api/equipment/skills/program1_skill/1.0.0/workflow",
        json={"expected_workflow_sha256": body["workflow_sha256"], "workflow": edited},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["failure_code"] == "SKILL_WORKFLOW_REVISION_CONFLICT"


def test_skill_deploy_auto_compiles_and_validates_annotated_workflow(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    _annotated_skill(client)
    stages: list[str] = []

    class Bridge:
        def register_program(self, payload):
            program = dict(payload["program"])
            return {"ok": True, "program_id": program["program_id"], "program_sha256": canonical_sha256(program)}

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())
    result = main_module._execute_equipment_skill_deployment(
        "program1_skill",
        "1.0.0",
        main_module.EquipmentSkillDeploymentRequest(bridge_id="windows-lab-1"),
        progress_callback=lambda stage, _progress, _text: stages.append(stage),
    )

    assert stages[:2] == ["COMPILING", "VALIDATING"]
    assert result["manifest"]["lifecycle"] == "deployed"


def test_workflow_single_step_test_sends_only_selected_action(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    _annotated_skill(client)
    observed: dict = {}

    class Bridge:
        def run(self, payload):
            observed.update(payload)
            return {"ok": True, "status": "completed", "step_trace": []}

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())
    response = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/workflow/steps/step-002/test",
        json={"bridge_id": "windows-lab-1", "confirm_execute": True},
    )

    assert response.status_code == 200
    assert len(observed["sequence"]) == 1
    assert observed["sequence"][0]["action"] == "press"
    assert observed["force_live_bridge"] is True


def test_workflow_editor_page_binds_exact_skill_and_assets(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    _annotated_skill(client)

    response = client.get("/equipment/skills/program1_skill/1.0.0/workflow-editor")

    assert response.status_code == 200
    assert 'id="skill-workflow-editor"' in response.text
    assert 'data-skill-id="program1_skill"' in response.text
    assert 'data-skill-version="1.0.0"' in response.text
    assert "/static/equipment_skill_workflow_model.js" in response.text
    assert "/static/equipment_skill_workflow_editor.js" in response.text


def test_workflow_locator_source_and_manual_target_crop_are_saved_atomically(monkeypatch, tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts" / "equipment"
    artifact_root.mkdir(parents=True)
    frame_path = artifact_root / "pre-action.png"
    Image.new("RGB", (200, 100), "white").save(frame_path)
    frame_raw = frame_path.read_bytes()
    recording = _image_first_recording()
    recording["events"][0]["visual_locator"].update(
        {
            "full_frame_artifact_path": str(frame_path),
            "full_frame_sha256": hashlib.sha256(frame_raw).hexdigest(),
        }
    )
    original_resolve = main_module.resolve_path
    monkeypatch.setattr(
        main_module,
        "resolve_path",
        lambda value: artifact_root if str(value) == "artifacts/equipment" else original_resolve(value),
    )
    client = _client(monkeypatch, tmp_path)
    client.post(
        "/api/equipment/skills/drafts",
        json={
            "recording": recording,
            "skill_id": "crop_skill",
            "version": "1.0.0",
            "target_profile": "local_program1",
        },
    ).raise_for_status()
    client.post(
        "/api/equipment/skills/crop_skill/1.0.0/annotate",
        json={
            "use_model": False,
            "annotations": {
                "steps": [
                    {
                        "step_id": "step-001",
                        "label": "Click target",
                        "confidence": 0.95,
                        "review_required": False,
                        "locator": {
                            "target_bbox_norm": [0.4, 0.4, 0.2, 0.2],
                            "context_bbox_norm": [0.2, 0.2, 0.6, 0.6],
                        },
                    }
                ]
            },
        },
    ).raise_for_status()

    source = client.get(
        "/api/equipment/skills/crop_skill/1.0.0/workflow/steps/step-001/locator-source"
    )
    image = client.get(
        "/api/equipment/skills/crop_skill/1.0.0/workflow/steps/step-001/locator-source/image"
    )

    assert source.status_code == 200
    assert source.json()["source_size"] == [200, 100]
    assert source.json()["target_bbox_norm"] == [0.4, 0.4, 0.2, 0.2]
    assert source.json()["ai_target_bbox_norm"] == [0.4, 0.4, 0.2, 0.2]
    assert source.json()["image_url"].endswith("/locator-source/image")
    assert image.status_code == 200
    assert image.content == frame_raw

    loaded = client.get("/api/equipment/skills/crop_skill/1.0.0/workflow").json()
    workflow = loaded["workflow"]
    action = workflow["steps"][0]["action"]
    context_candidate = dict(action["image_candidates"][0])
    manual_candidate = _png_candidate(60, 40)
    action["image_candidates"] = [manual_candidate, context_candidate]
    action["target_bbox_norm"] = [0.2, 0.1, 0.3, 0.4]
    action["locator_origin"] = "manual_crop"
    saved = client.put(
        "/api/equipment/skills/crop_skill/1.0.0/workflow",
        json={"expected_workflow_sha256": loaded["workflow_sha256"], "workflow": workflow},
    )

    assert saved.status_code == 200
    saved_locator = saved.json()["annotations"]["steps"][0]["locator"]
    assert saved_locator["target_bbox_norm"] == [0.2, 0.1, 0.3, 0.4]
    assert saved_locator["locator_origin"] == "manual_crop"
    assert saved_locator["image_candidates"][0]["sha256"] == manual_candidate["sha256"]
    assert saved_locator["context_bbox_norm"] == [0.2, 0.2, 0.6, 0.6]
    refreshed_source = client.get(
        "/api/equipment/skills/crop_skill/1.0.0/workflow/steps/step-001/locator-source"
    ).json()
    assert refreshed_source["target_bbox_norm"] == [0.2, 0.1, 0.3, 0.4]
    assert refreshed_source["ai_target_bbox_norm"] == [0.4, 0.4, 0.2, 0.2]


def test_skill_api_persists_complete_draft_compile_validate_lifecycle(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    draft = client.post(
        "/api/equipment/skills/drafts",
        json={
            "recording": _recording(),
            "skill_id": "program1_skill",
            "version": "1.0.0",
            "target_profile": "local_program1",
        },
    )

    assert draft.status_code == 200
    assert draft.json()["ok"] is True
    assert draft.json()["manifest"]["lifecycle"] == "draft"
    assert "api_key" not in str(draft.json()).lower()

    annotated = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/annotate",
        json={
            "use_model": False,
            "annotations": {
                "steps": [
                    {"step_id": "step-001", "label": "Click demo", "confidence": 0.95, "review_required": False},
                    {"step_id": "step-002", "label": "Confirm demo", "confidence": 0.95, "review_required": False},
                ]
            },
        },
    )
    assert annotated.status_code == 200
    assert annotated.json()["ok"] is True
    assert annotated.json()["manifest"]["lifecycle"] == "annotated"

    compiled = client.post("/api/equipment/skills/program1_skill/1.0.0/compile").json()
    assert compiled["ok"] is True
    assert compiled["manifest"]["lifecycle"] == "compiled"
    validated = client.post("/api/equipment/skills/program1_skill/1.0.0/validate")
    assert validated.status_code == 200
    assert validated.json()["package"]["manifest"]["lifecycle"] == "validated"

    listed = client.get("/api/equipment/skills").json()
    assert listed["skills"][0]["skill_id"] == "program1_skill"
    assert listed["skills"][0]["version"] == "1.0.0"


def test_recording_import_pulls_selected_worker_recording_into_linux_skill_registry(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    recording = _recording()
    recording["schema"] = "atr.equipment_recording.v3"
    recording["timeline_id"] = "timeline-api-import"
    recording["time_series_evidence"] = {
        "schema": "atr.equipment_recording_frames.v1",
        "timeline_id": "timeline-api-import",
        "frames": [],
        "exception_windows": [],
    }
    calls: list[dict] = []

    class Bridge:
        def get_recording(self, payload):
            calls.append(dict(payload))
            return {"ok": True, **recording}

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())

    response = client.post(
        "/api/equipment/recordings/rec-program1-api/import-skill",
        json={
            "skill_id": "imported_program1_skill",
            "version": "1.0.0",
            "target_profile": "local_program1",
            "bridge_id": "windows-lab-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == [
        {
            "recording_id": "rec-program1-api",
            "bridge_id": "windows-lab-1",
            "force_live_bridge": True,
        }
    ]
    assert body["ok"] is True
    assert body["manifest"]["recording_id"] == "rec-program1-api"
    assert body["manifest"]["timeline_id"] == "timeline-api-import"
    assert body["transfer"]["source_worker"] == "windows-lab-1"
    assert body["transfer"]["fallback_used"] is False
    assert body["equipment_runtime_projection"]["status"] == "verified_complete"


def test_recording_list_pulls_recordings_from_selected_worker_without_fallback(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    calls: list[dict] = []

    class FakeBridge:
        def list_recordings(self, payload):
            calls.append(dict(payload))
            return {
                "ok": True,
                "status": "ready",
                "recordings": [
                    {
                        "recording_id": "rec-worker-list-001",
                        "name": "UTM compression demo",
                        "status": "completed",
                        "duration_ms": 4200,
                        "events": [{"kind": "mouse_click"}],
                        "time_series_evidence": {"frames": [{"png_base64": "large-payload"}]},
                    }
                ],
            }

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: FakeBridge())

    response = client.get("/api/equipment/workers/nextpc/recordings")

    assert response.status_code == 200
    recording = response.json()["recordings"][0]
    assert recording == {
        "recording_id": "rec-worker-list-001",
        "name": "UTM compression demo",
        "status": "completed",
        "duration_ms": 4200,
        "event_count": 1,
        "created_at": "",
        "updated_at": "",
    }
    assert calls == [{"bridge_id": "nextpc", "force_live_bridge": True}]


def test_recording_import_blocks_without_falling_back_when_selected_worker_is_unreachable(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    class Bridge:
        def get_recording(self, payload):
            return {
                "ok": False,
                "status": "unreachable",
                "failure_code": "PYAUTOGUI_BRIDGE_UNREACHABLE",
                "message": "selected Windows worker is unreachable",
            }

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())

    response = client.post(
        "/api/equipment/recordings/rec-missing/import-skill",
        json={
            "skill_id": "missing_recording_skill",
            "version": "1.0.0",
            "target_profile": "local_program1",
            "bridge_id": "windows-lab-1",
        },
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["failure_code"] == "PYAUTOGUI_BRIDGE_UNREACHABLE"
    assert detail["fallback_used"] is False


def test_recording_import_start_returns_persistent_background_job(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    launched: list[str] = []
    monkeypatch.setattr(main_module, "_launch_equipment_skill_authoring_job", launched.append)

    response = client.post(
        "/api/equipment/recordings/rec-program1-api/import-skill/start",
        json={
            "skill_id": "equipment_demonstration",
            "version": "1.0.0",
            "target_profile": "local_program1",
            "bridge_id": "windows-lab-1",
        },
    )

    assert response.status_code == 202
    job = response.json()["job"]
    assert job["status"] == "QUEUED"
    assert job["stage"] == "PREPARING"
    assert job["progress"] == 5
    assert launched == [job["job_id"]]
    restored = client.get(f"/api/equipment/skill-authoring/jobs/{job['job_id']}")
    assert restored.status_code == 200
    assert restored.json()["job"]["skill_id"] == "equipment_demonstration"


def test_recording_import_background_job_completes_real_transfer_build_and_validation(monkeypatch, tmp_path: Path) -> None:
    _client(monkeypatch, tmp_path)
    recording = _recording()
    calls: list[dict] = []
    annotation_calls: list[dict] = []

    class Bridge:
        def get_recording(self, payload):
            calls.append(dict(payload))
            return {"ok": True, **recording}

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())

    async def annotate(package, **_kwargs):
        annotation_calls.append(package)
        return (
            {
                "steps": [
                    {
                        "step_id": step["step_id"],
                        "label": f"Reviewed {step['label']}",
                        "confidence": 0.97,
                        "review_required": False,
                    }
                    for step in package["workflow"]["steps"]
                ]
            },
            {"provider": "test", "model": "annotation-model", "fallback_allowed": False},
        )

    monkeypatch.setattr(main_module, "_annotate_equipment_skill_with_selected_model", annotate)
    manager = main_module._equipment_skill_authoring_job_manager()
    job = manager.create(
        recording_id="rec-program1-api",
        skill_id="equipment_demonstration",
        version="1.0.0",
        target_profile="local_program1",
        bridge_id="windows-lab-1",
    )

    main_module._run_equipment_skill_authoring_job(job["job_id"])
    completed = manager.get(job["job_id"])

    assert calls == [{"recording_id": "rec-program1-api", "bridge_id": "windows-lab-1", "force_live_bridge": True}]
    assert completed["status"] == "COMPLETED"
    assert completed["stage"] == "COMPLETED"
    assert completed["progress"] == 100
    assert completed["result"]["manifest"]["skill_id"] == "equipment_demonstration"
    assert completed["result"]["manifest"]["lifecycle"] == "annotated"
    assert completed["result"]["annotations"]["status"] == "reviewed"
    assert completed["result"]["annotations"]["model_snapshot"]["model"] == "annotation-model"
    assert completed["result"]["equipment_runtime_projection"]["status"] == "verified_complete"
    assert len(annotation_calls) == 1
    assert len(annotation_calls[0]["workflow"]["steps"]) == 2


def test_recording_import_background_job_does_not_leave_skill_when_annotation_fails(monkeypatch, tmp_path: Path) -> None:
    _client(monkeypatch, tmp_path)

    class Bridge:
        def get_recording(self, _payload):
            return {"ok": True, **_recording()}

    async def fail_annotation(_package):
        raise RuntimeError("selected annotation model unavailable")

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())
    monkeypatch.setattr(main_module, "_annotate_equipment_skill_with_selected_model", fail_annotation)
    manager = main_module._equipment_skill_authoring_job_manager()
    job = manager.create(
        recording_id="rec-program1-api",
        skill_id="failed_annotation_skill",
        version="1.0.0",
        target_profile="local_program1",
        bridge_id="windows-lab-1",
    )

    main_module._run_equipment_skill_authoring_job(job["job_id"])

    failed = manager.get(job["job_id"])
    assert failed["status"] == "FAILED"
    assert failed["stage"] == "FAILED"
    assert failed["error"]["failure_code"] == "SKILL_AUTHORING_FAILED"
    assert main_module._equipment_skill_registry().list() == []


def test_skill_authoring_stop_endpoint_requests_cooperative_stop(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    manager = main_module._equipment_skill_authoring_job_manager()
    job = manager.create(
        recording_id="rec-program1-api",
        skill_id="equipment_demonstration",
        version="1.0.0",
        target_profile="local_program1",
        bridge_id="windows-lab-1",
    )

    response = client.post(f"/api/equipment/skill-authoring/jobs/{job['job_id']}/stop")

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "STOPPING"
    assert manager.get(job["job_id"])["stop_requested"] is True


def test_skill_authoring_storyboard_preview_is_paginated_and_hides_server_paths(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    artifact_root = tmp_path / "artifacts" / "equipment"
    storyboard_root = artifact_root / "skill_storyboards" / "rec-preview"
    storyboard_root.mkdir(parents=True)
    for index in range(3):
        Image.new("RGB", (640, 360), (30 + index * 40, 80, 120)).save(
            storyboard_root / f"chunk-{index + 1:04d}.jpg",
            quality=90,
        )
    manager = main_module._equipment_skill_authoring_job_manager()
    job = manager.create(
        recording_id="rec-preview",
        skill_id="preview_skill",
        version="1.0.0",
        target_profile="local_program1",
        bridge_id="windows-lab-1",
    )
    original_resolve = main_module.resolve_path
    monkeypatch.setattr(
        main_module,
        "resolve_path",
        lambda value: artifact_root if str(value) == "artifacts/equipment" else original_resolve(value),
    )

    response = client.get(
        f"/api/equipment/skill-authoring/jobs/{job['job_id']}/storyboards",
        params={"cursor": 1, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cursor"] == 1
    assert payload["limit"] == 1
    assert payload["next_cursor"] == 2
    assert payload["total_count"] == 3
    assert len(payload["items"]) == 1
    assert payload["items"][0]["name"] == "chunk-0002.jpg"
    assert base64.b64decode(payload["items"][0]["data_base64"])
    assert "path" not in payload["items"][0]


def test_skill_api_compiles_complex_recording_and_reports_capability_coverage(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    draft = client.post(
        "/api/equipment/skills/drafts",
        json={
            "recording": _complex_recording(),
            "skill_id": "complex_desktop_skill",
            "version": "1.0.0",
            "target_profile": "capability_lab",
        },
    )

    assert draft.status_code == 200
    package = draft.json()
    assert package["manifest"]["capability_coverage"] == {
        "actions": ["drag_to", "hotkey", "press", "scroll"],
        "families": ["keyboard", "mouse"],
        "event_count": 6,
        "hotkey_count": 1,
        "drag_count": 1,
        "scroll_count": 1,
        "unsupported_event_kinds": [],
    }
    assert [step["action"] for step in package["workflow"]["steps"]] == [
        {"action": "move_to", "x": 120, "y": 160, "duration_sec": 0.05},
        {"action": "drag_to", "x": 360, "y": 240, "button": "left", "duration_sec": 0.4},
        {"action": "hscroll", "clicks": 2},
        {"action": "scroll", "clicks": -4},
        {"action": "write", "text": "a b"},
        {"action": "hotkey", "keys": ["ctrl", "a"]},
    ]

    compiled = client.post("/api/equipment/skills/complex_desktop_skill/1.0.0/compile")
    assert compiled.status_code == 200
    sequences = [
        action
        for program in compiled.json()["programs"]
        for action in program["sequence"]
    ]
    assert sequences == [step["action"] for step in package["workflow"]["steps"]]


def test_skill_api_preserves_image_first_locator_through_compile(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    draft = client.post(
        "/api/equipment/skills/drafts",
        json={
            "recording": _image_first_recording(),
            "skill_id": "image_first_skill",
            "version": "1.0.0",
            "target_profile": "local_program1",
        },
    )

    assert draft.status_code == 200
    action = draft.json()["workflow"]["steps"][0]["action"]
    assert action["target"] == "evt-0001-target"
    assert "x" not in action
    assert action["image_candidates"][0]["kind"] == "tight"

    compiled = client.post("/api/equipment/skills/image_first_skill/1.0.0/compile")
    assert compiled.status_code == 200
    compiled_action = compiled.json()["programs"][0]["sequence"][0]
    assert compiled_action["target"] == "evt-0001-target"
    assert compiled_action["image_candidates"] == action["image_candidates"]


def test_skill_api_reports_selected_model_unavailable_without_fallback(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    client.post(
        "/api/equipment/skills/drafts",
        json={
            "recording": _recording(),
            "skill_id": "program1_skill",
            "version": "1.0.0",
            "target_profile": "local_program1",
        },
    )

    async def fail_annotation(*_args, **_kwargs):
        raise RuntimeError("selected model unavailable")

    monkeypatch.setattr(main_module, "_annotate_equipment_skill_with_selected_model", fail_annotation)
    response = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/annotate",
        json={"use_model": True, "annotations": {}},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["failure_code"] == "SKILL_SELECTED_MODEL_UNAVAILABLE"
    assert detail["fallback_used"] is False


def test_skill_deploy_registers_exact_programs_before_marking_deployed(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    package = _validated_skill(client)
    registered: list[dict] = []
    registration_payloads: list[dict] = []

    class Bridge:
        def register_program(self, payload):
            registration_payloads.append(dict(payload))
            program = dict(payload["program"])
            registered.append(program)
            return {
                "ok": True,
                "status": "registered",
                "program_id": program["program_id"],
                "program_sha256": canonical_sha256(program),
            }

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())
    response = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/deploy",
        json={"bridge_id": "windows-lab-1"},
    )

    assert response.status_code == 200
    assert registered == package["programs"]
    assert all(item["force_live_bridge"] is True for item in registration_payloads)
    assert all(item["bridge_id"] == "windows-lab-1" for item in registration_payloads)
    body = response.json()
    assert body["ok"] is True
    assert body["manifest"]["lifecycle"] == "deployed"
    assert body["manifest"]["deployment"]["program_ids"] == [item["program_id"] for item in registered]
    assert body["manifest"]["deployment"]["program_sha256"] == {
        item["program_id"]: canonical_sha256(item) for item in registered
    }
    runtime = body["equipment_runtime_execution"]
    assert runtime["lifecycle"] == "COMPLETED"
    assert runtime["execution_ref"] == {
        "type": "skill",
        "skill_id": "program1_skill",
        "version": "1.0.0",
        "operation": "deploy",
    }
    assert runtime["metadata"]["deployment"]["bridge_id"] == "windows-lab-1"
    assert runtime["metadata"]["deployment"]["sha256"] == body["manifest"]["deployment"]["sha256"]
    assert body["equipment_runtime_projection"]["execution_id"] == runtime["execution_id"]


def test_skill_deployment_background_job_registers_exact_programs_and_completes(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    package = _validated_skill(client)
    registered: list[dict] = []

    class Bridge:
        def register_program(self, payload):
            program = dict(payload["program"])
            registered.append(program)
            return {
                "ok": True,
                "status": "registered",
                "program_id": program["program_id"],
                "program_sha256": canonical_sha256(program),
            }

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())
    manager = main_module._equipment_skill_authoring_job_manager()
    job = manager.create_deployment(
        skill_id="program1_skill",
        version="1.0.0",
        bridge_id="windows-lab-1",
    )

    main_module._run_equipment_skill_deployment_job(job["job_id"])

    completed = manager.get(job["job_id"])
    assert completed["operation"] == "deployment"
    assert completed["status"] == "COMPLETED"
    assert completed["stage"] == "DEPLOYED"
    assert completed["progress"] == 100
    assert registered == package["programs"]
    assert completed["result"]["manifest"]["lifecycle"] == "deployed"


def test_skill_deployment_start_returns_persistent_job(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    _validated_skill(client)
    launched: list[str] = []
    monkeypatch.setattr(main_module, "_launch_equipment_skill_deployment_job", launched.append)

    response = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/deploy/start",
        json={"bridge_id": "windows-lab-1"},
    )

    assert response.status_code == 202
    job = response.json()["job"]
    assert job["operation"] == "deployment"
    assert job["stage"] == "PREFLIGHT"
    assert job["progress"] == 5
    assert launched == [job["job_id"]]
    restored = client.get(f"/api/equipment/skill-deployment/jobs/{job['job_id']}")
    assert restored.status_code == 200
    assert restored.json()["job"]["bridge_id"] == "windows-lab-1"


def test_skill_deploy_rejects_hash_mismatch_without_changing_lifecycle(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    _validated_skill(client)

    class Bridge:
        def register_program(self, payload):
            program = dict(payload["program"])
            return {
                "ok": True,
                "status": "registered",
                "program_id": program["program_id"],
                "program_sha256": "0" * 64,
            }

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())
    response = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/deploy",
        json={"bridge_id": "windows-lab-1"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["failure_code"] == "SKILL_DEPLOYMENT_HASH_MISMATCH"
    package = client.get("/api/equipment/skills/program1_skill/1.0.0").json()
    assert package["manifest"]["lifecycle"] == "validated"


def test_skill_deploy_can_retry_after_bridge_registration_failure(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    _validated_skill(client)
    fail_first = {"value": True}

    class Bridge:
        def register_program(self, payload):
            program = dict(payload["program"])
            if fail_first["value"]:
                fail_first["value"] = False
                return {
                    "ok": False,
                    "status": "blocked",
                    "failure_code": "PYAUTOGUI_BRIDGE_UNREACHABLE",
                }
            return {
                "ok": True,
                "status": "registered",
                "program_id": program["program_id"],
                "program_sha256": canonical_sha256(program),
            }

        def delete_program(self, _payload):
            return {"ok": True, "status": "deleted"}

    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: Bridge())

    first = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/deploy",
        json={"bridge_id": "windows-lab-1"},
    )
    second = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/deploy",
        json={"bridge_id": "windows-lab-1"},
    )

    assert first.status_code == 409
    assert second.status_code == 200
    assert second.json()["equipment_runtime_execution"]["lifecycle"] == "COMPLETED"


def test_skill_api_test_then_disable_and_delete_exact_version(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    _validated_skill(client)
    registered: dict[str, dict] = {}
    executions: list[dict] = []
    deletions: list[dict] = []

    class Bridge:
        def register_program(self, payload):
            program = dict(payload["program"])
            registered[program["program_id"]] = program
            return {"ok": True, "program_id": program["program_id"], "program_sha256": canonical_sha256(program)}

        def delete_program(self, payload):
            deletions.append(dict(payload))
            registered.pop(payload["program_id"], None)
            return {"ok": True, "status": "deleted"}

        def run(self, payload):
            executions.append(dict(payload))
            return {"ok": True, "status": "completed", "program_id": payload["program_id"]}

    bridge = Bridge()
    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: bridge)
    client.post(
        "/api/equipment/skills/program1_skill/1.0.0/deploy",
        json={"bridge_id": "windows-lab-1"},
    ).raise_for_status()
    deployed_program_count = len(registered)

    tested = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/test",
        json={"runtime_mode": "test", "confirm_execute": False},
    )
    blocked_delete = client.delete("/api/equipment/skills/program1_skill/1.0.0")
    disabled = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/enabled",
        json={"enabled": False},
    )
    deleted = client.delete("/api/equipment/skills/program1_skill/1.0.0")

    assert tested.status_code == 200
    assert tested.json()["status"] == "passed"
    assert len(executions) == deployed_program_count
    assert all(item["force_live_bridge"] is True for item in executions)
    assert blocked_delete.status_code == 409
    assert disabled.json()["manifest"]["lifecycle"] == "disabled"
    assert deleted.status_code == 200
    assert all(item["force_live_bridge"] is True for item in deletions)
    assert client.get("/api/equipment/skills/program1_skill/1.0.0").status_code == 404


def test_full_timeline_skill_path_imports_annotates_deploys_and_executes(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    artifact_root = tmp_path / "artifacts" / "equipment"
    frame_root = artifact_root / "recordings" / "rec-full-path" / "frames" / "periodic"
    frame_root.mkdir(parents=True)
    frames = []
    for index in range(17):
        frame = frame_root / f"frame-{index + 1:08d}.jpg"
        Image.new("RGB", (320, 180), (30, index * 11 % 255, 160)).save(frame, quality=90)
        frames.append(
            {
                "frame_id": f"frame-{index + 1:08d}",
                "at_ms": index * 500,
                "artifact_path": str(frame),
                "sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
                "media_type": "image/jpeg",
                "width": 320,
                "height": 180,
                "reason": "periodic",
            }
        )
    recording = {
        **_recording(),
        "recording_id": "rec-full-path",
        "timeline_id": "timeline-rec-full-path",
        "time_series_evidence": {
            "schema": "atr.equipment_recording_timeline.v1",
            "timeline_id": "timeline-rec-full-path",
            "fps": 2.0,
            "frames": frames,
            "evidence_complete": True,
        },
    }
    backend_calls: list[dict] = []
    registered: dict[str, dict] = {}
    executions: list[dict] = []

    class Backend:
        async def complete(self, **kwargs):
            backend_calls.append(kwargs)
            if kwargs["metadata"]["task_type"] == "equipment_skill_timeline_chunk":
                chunk = json.loads(kwargs["user_prompt"])["chunk"]
                return LLMResponse(
                    text=json.dumps(
                        {
                            "chunk_id": chunk["chunk_id"],
                            "summary": f"Chronological analysis for {chunk['chunk_id']}",
                            "state_transitions": [],
                            "source_frame_ids": [tile["frame_id"] for tile in chunk["tiles"]],
                        }
                    ),
                    model="vision-model",
                )
            request = json.loads(kwargs["user_prompt"])
            steps = request["workflow"]["steps"]
            return LLMResponse(
                text=json.dumps(
                    {
                        "workflow_summary": {"intent": "Replay the recorded desktop workflow."},
                        "step_transitions": [],
                        "steps": [
                            {
                                "step_id": step["step_id"],
                                "label": step["label"],
                                "confidence": 0.98,
                                "review_required": False,
                            }
                            for step in steps
                        ],
                    }
                ),
                model="vision-model",
            )

    class Bridge:
        def get_recording(self, payload):
            assert payload == {
                "recording_id": "rec-full-path",
                "bridge_id": "windows-lab-1",
                "force_live_bridge": True,
            }
            return {"ok": True, **recording}

        def register_program(self, payload):
            program = dict(payload["program"])
            registered[program["program_id"]] = program
            return {
                "ok": True,
                "program_id": program["program_id"],
                "program_sha256": canonical_sha256(program),
            }

        def run(self, payload):
            executions.append(dict(payload))
            return {"ok": True, "status": "completed", "program_id": payload["program_id"]}

    bridge = Bridge()
    context = main_module.controller._deps.agent_context
    monkeypatch.setitem(context.primary_backends, "vllm", Backend())
    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: bridge)
    monkeypatch.setattr(
        main_module,
        "_equipment_skill_model_snapshot",
        lambda: {
            "provider": "vllm",
            "model": "vision-model",
            "role": "e4b",
            "endpoint_profile": "test",
            "capabilities": {"text": True, "vision": True},
            "fallback_allowed": False,
        },
    )
    original_resolve = main_module.resolve_path
    monkeypatch.setattr(
        main_module,
        "resolve_path",
        lambda value: artifact_root if str(value) == "artifacts/equipment" else original_resolve(value),
    )
    monkeypatch.setattr(
        main_module,
        "_manual_knowledge_context",
        lambda *_args, **_kwargs: {
            "schema": "manual_prompt_context.v1",
            "equipment_type": "",
            "purpose": "skill_authoring",
            "context_hash": "test",
            "insufficient_evidence": True,
            "chunks": [],
        },
    )
    manager = main_module._equipment_skill_authoring_job_manager()
    job = manager.create(
        recording_id="rec-full-path",
        skill_id="full_timeline_skill",
        version="1.0.0",
        target_profile="local_program1",
        bridge_id="windows-lab-1",
    )

    main_module._run_equipment_skill_authoring_job(job["job_id"])
    assert manager.get(job["job_id"])["status"] == "COMPLETED"
    assert [call["metadata"]["task_type"] for call in backend_calls] == [
        "equipment_skill_timeline_chunk",
        "equipment_skill_timeline_chunk",
        "equipment_skill_annotation",
    ]
    client.post("/api/equipment/skills/full_timeline_skill/1.0.0/compile").raise_for_status()
    client.post("/api/equipment/skills/full_timeline_skill/1.0.0/validate").raise_for_status()
    deployed = client.post(
        "/api/equipment/skills/full_timeline_skill/1.0.0/deploy",
        json={"bridge_id": "windows-lab-1"},
    )
    deployed.raise_for_status()
    tested = client.post(
        "/api/equipment/skills/full_timeline_skill/1.0.0/test",
        json={"runtime_mode": "test", "confirm_execute": False},
    )

    assert deployed.json()["manifest"]["lifecycle"] == "deployed"
    assert registered
    assert tested.status_code == 200
    assert tested.json()["status"] == "passed"
    assert len(executions) == len(registered)
    assert all(payload["bridge_id"] == "windows-lab-1" for payload in executions)


def test_selected_skill_annotation_backend_receives_pre_click_frame_and_returns_runtime_locator(
    monkeypatch,
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts" / "equipment"
    artifact_root.mkdir(parents=True)
    frame = artifact_root / "evt-0001-source-frame.png"
    Image.new("RGB", (200, 100), "white").save(frame)
    frame_sha = hashlib.sha256(frame.read_bytes()).hexdigest()
    calls: list[dict] = []

    class Backend:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            return LLMResponse(
                text=json.dumps(
                    {
                        "workflow_summary": {
                            "intent": "Start the recorded equipment workflow.",
                            "initial_state": "The application is ready.",
                            "completion_state": "The requested run has started.",
                        },
                        "step_transitions": [
                            {
                                "step_id": "step-001",
                                "before_state": "The application is ready.",
                                "action_effect": "The run control is activated.",
                                "after_state": "The requested run has started.",
                                "success_evidence": "The running state is visible.",
                            }
                        ],
                        "steps": [
                            {
                                "step_id": "step-001",
                                "label": "Open run",
                                "confidence": 0.98,
                                "review_required": False,
                                "checkpoint_after": False,
                                "locator": {
                                    "search_roi_norm": [0.1, 0.1, 0.6, 0.7],
                                    "target_bbox_norm": [0.4, 0.4, 0.2, 0.2],
                                    "context_bbox_norm": [0.25, 0.2, 0.5, 0.5],
                                },
                            }
                        ]
                    }
                ),
                model="vision-model",
            )

    context = main_module.controller._deps.agent_context
    monkeypatch.setitem(context.primary_backends, "vllm", Backend())
    monkeypatch.setattr(
        main_module,
        "_equipment_skill_model_snapshot",
        lambda: {
            "provider": "vllm",
            "model": "vision-model",
            "role": "e4b",
            "endpoint_profile": "test",
            "capabilities": {"text": True, "vision": True},
            "fallback_allowed": False,
        },
    )
    original_resolve = main_module.resolve_path
    monkeypatch.setattr(
        main_module,
        "resolve_path",
        lambda value: artifact_root if str(value) == "artifacts/equipment" else original_resolve(value),
    )
    monkeypatch.setattr(
        main_module,
        "_manual_knowledge_context",
        lambda *_args, **_kwargs: {
            "schema": "manual_prompt_context.v1",
            "equipment_type": "",
            "purpose": "skill_authoring",
            "context_hash": "test",
            "insufficient_evidence": True,
            "chunks": [],
        },
    )
    package = {
        "workflow": {
            "name": "Visual skill",
            "steps": [
                {
                    "step_id": "step-001",
                    "action": {
                        "action": "click",
                        "target": "evt-0001-target",
                        "recorded_coordinate": [100, 50],
                        "image_candidates": [{"png_base64": "duplicate", "sha256": "old"}],
                    },
                }
            ],
        },
        "annotations": {"steps": [{"step_id": "step-001"}]},
        "manifest": {"recording_evidence": {}},
        "recording": {
            "events": [
                {
                    "kind": "mouse_click",
                    "visual_locator": {
                        "locator_id": "evt-0001-target",
                        "full_frame_artifact_path": str(frame),
                        "full_frame_sha256": frame_sha,
                    },
                }
            ]
        },
    }

    annotations, snapshot = asyncio.run(main_module._annotate_equipment_skill_with_selected_model(package))

    assert len(calls) == 1
    assert len(calls[0]["images"]) == 1
    assert "duplicate" not in calls[0]["user_prompt"]
    request_payload = json.loads(calls[0]["user_prompt"])
    assert request_payload["visual_timeline"][0]["role"] == "pre_action"
    assert request_payload["visual_timeline"][0]["step_id"] == "step-001"
    assert annotations["workflow_summary"]["intent"] == "Start the recorded equipment workflow."
    assert annotations["step_transitions"][0]["after_state"] == "The requested run has started."
    locator = annotations["steps"][0]["locator"]
    assert locator["region_normalized"] == [0.1, 0.1, 0.6, 0.7]
    assert len(locator["image_candidates"]) == 2
    assert snapshot["visual_evidence_count"] == 1


def test_selected_skill_annotation_backend_reads_every_temporal_storyboard_before_synthesis(
    monkeypatch,
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts" / "equipment"
    frame_root = artifact_root / "recordings" / "rec-timeline" / "frames" / "periodic"
    frame_root.mkdir(parents=True)
    frames = []
    for index in range(34):
        frame = frame_root / f"frame-{index + 1:08d}.jpg"
        Image.new("RGB", (320, 180), (index * 7 % 255, 80, 120)).save(frame, quality=90)
        frames.append(
            {
                "frame_id": f"frame-{index + 1:08d}",
                "at_ms": index * 500,
                "artifact_path": str(frame),
                "sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
                "media_type": "image/jpeg",
                "width": 320,
                "height": 180,
                "reason": "periodic",
            }
        )
    calls: list[dict] = []

    class Backend:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            if kwargs["metadata"]["task_type"] == "equipment_skill_timeline_chunk":
                chunk = json.loads(kwargs["user_prompt"])["chunk"]
                return LLMResponse(
                    text=json.dumps(
                        {
                            "chunk_id": chunk["chunk_id"],
                            "summary": f"Observed {chunk['chunk_id']}",
                            "state_transitions": [],
                            "source_frame_ids": [item["frame_id"] for item in chunk["tiles"]],
                        }
                    ),
                    model="vision-model",
                )
            return LLMResponse(
                text=json.dumps(
                    {
                        "workflow_summary": {
                            "intent": "Reconstruct the complete recording.",
                            "initial_state": "Initial desktop state.",
                            "completion_state": "Final desktop state.",
                        },
                        "step_transitions": [],
                        "steps": [],
                    }
                ),
                model="vision-model",
            )

    context = main_module.controller._deps.agent_context
    monkeypatch.setitem(context.primary_backends, "vllm", Backend())
    monkeypatch.setattr(
        main_module,
        "_equipment_skill_model_snapshot",
        lambda: {
            "provider": "vllm",
            "model": "vision-model",
            "role": "e4b",
            "endpoint_profile": "test",
            "capabilities": {"text": True, "vision": True},
            "fallback_allowed": False,
        },
    )
    original_resolve = main_module.resolve_path
    monkeypatch.setattr(
        main_module,
        "resolve_path",
        lambda value: artifact_root if str(value) == "artifacts/equipment" else original_resolve(value),
    )
    monkeypatch.setattr(
        main_module,
        "_manual_knowledge_context",
        lambda *_args, **_kwargs: {
            "schema": "manual_prompt_context.v1",
            "equipment_type": "",
            "purpose": "skill_authoring",
            "context_hash": "test",
            "insufficient_evidence": True,
            "chunks": [],
        },
    )
    package = {
        "workflow": {"name": "Timeline skill", "steps": []},
        "annotations": {"steps": []},
        "recording": {"recording_id": "rec-timeline", "events": []},
        "manifest": {
            "timeline_id": "timeline-rec-timeline",
            "recording_evidence": {"fps": 2.0, "frames": frames},
        },
    }

    progress: list[tuple[str, int, int]] = []
    annotations, snapshot = asyncio.run(
        main_module._annotate_equipment_skill_with_selected_model(
            package,
            progress_callback=lambda stage, completed, total: progress.append((stage, completed, total)),
        )
    )

    assert [call["metadata"]["task_type"] for call in calls] == [
        "equipment_skill_timeline_chunk",
        "equipment_skill_timeline_chunk",
        "equipment_skill_timeline_chunk",
        "equipment_skill_annotation",
    ]
    assert [json.loads(call["user_prompt"])["chunk"]["chunk_id"] for call in calls[:3]] == [
        "chunk-0001",
        "chunk-0002",
        "chunk-0003",
    ]
    assert calls[-1]["images"] == []
    synthesis = json.loads(calls[-1]["user_prompt"])
    assert len(synthesis["timeline_chunk_analyses"]) == 3
    assert sum(len(item["source_frame_ids"]) for item in synthesis["timeline_chunk_analyses"]) == 34
    assert annotations["workflow_summary"]["completion_state"] == "Final desktop state."
    assert snapshot["timeline_chunk_count"] == 3
    assert snapshot["timeline_source_frame_count"] == 34
    assert progress == [
        ("ANALYZING_TIMELINE", 0, 3),
        ("ANALYZING_TIMELINE", 1, 3),
        ("ANALYZING_TIMELINE", 2, 3),
        ("ANALYZING_TIMELINE", 3, 3),
        ("SYNTHESIZING", 3, 3),
    ]


def test_equipment_json_completion_retries_malformed_selected_model_response() -> None:
    calls: list[dict] = []

    class Backend:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return LLMResponse(text='{"chunk_id":"chunk-0001" "summary":"broken"}', model="vision-model")
            return LLMResponse(
                text=json.dumps({"chunk_id": "chunk-0001", "summary": "repaired"}),
                model="vision-model",
            )

    payload, response = asyncio.run(
        main_module._complete_equipment_json_with_retry(
            Backend(),
            model="vision-model",
            system_prompt="Return one JSON object.",
            user_prompt='{"chunk":1}',
            metadata={"task_type": "equipment_skill_timeline_chunk", "no_fallback": True},
            images=[],
        )
    )

    assert payload == {"chunk_id": "chunk-0001", "summary": "repaired"}
    assert response.model == "vision-model"
    assert len(calls) == 2
    assert calls[1]["metadata"]["task_type"] == "equipment_skill_timeline_chunk"
    assert calls[1]["metadata"]["json_retry_attempt"] == 1
    assert calls[1]["metadata"]["no_fallback"] is True
    assert calls[0]["metadata"]["response_format"] == "json_object"
    assert calls[1]["metadata"]["response_format"] == "json_object"
    assert "strict RFC 8259 JSON" in calls[1]["system_prompt"]


def test_equipment_json_completion_repairs_retry_syntax_without_model_fallback() -> None:
    calls: list[dict] = []

    class Backend:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            return LLMResponse(
                text='{"chunk_id":"chunk-0001" "summary":"complete analysis", "source_frame_ids":[]}',
                model="vision-model",
            )

    payload, response = asyncio.run(
        main_module._complete_equipment_json_with_retry(
            Backend(),
            model="vision-model",
            system_prompt="Return one JSON object.",
            user_prompt='{"chunk":1}',
            metadata={"task_type": "equipment_skill_timeline_chunk", "no_fallback": True},
            images=[],
        )
    )

    assert payload == {
        "chunk_id": "chunk-0001",
        "summary": "complete analysis",
        "source_frame_ids": [],
    }
    assert response.model == "vision-model"
    assert len(calls) == 2


def test_equipment_skill_synthesis_workflow_omits_duplicate_image_candidates() -> None:
    workflow = {
        "schema": "equipment.skill.workflow.v1",
        "name": "Recorded workflow",
        "steps": [
            {
                "step_id": "step-001",
                "action": {
                    "action": "click",
                    "target": "evt-0013-target",
                    "image_candidates": [{"png_base64": "large-inline-image", "sha256": "abc"}],
                },
            },
            {
                "step_id": "step-002",
                "action": {
                    "action": "set_input_language",
                    "layout_id": "00000412",
                    "language": "ko",
                },
            },
        ],
    }

    compact = main_module._equipment_skill_synthesis_workflow(workflow)

    assert compact["steps"][0]["action"] == {"action": "click", "target": "evt-0013-target"}
    assert compact["steps"][1]["action"]["action"] == "set_input_language"


def test_equipment_skill_annotation_payload_backfills_missing_steps_without_changing_actions() -> None:
    workflow = {
        "steps": [
            {
                "step_id": "step-001",
                "label": "set_input_language",
                "action": {
                    "action": "set_input_language",
                    "layout_id": "00000412",
                    "language": "ko",
                },
            },
            {
                "step_id": "step-002",
                "label": "write",
                "action": {"action": "write", "text": "test"},
            },
        ]
    }
    annotations = {
        "steps": [
            {"step_id": "step-001", "label": "set_input_language", "confidence": 0.75, "review_required": False},
            {"step_id": "step-002", "label": "write", "confidence": 0.75, "review_required": False},
        ]
    }

    completed, fallback_count = main_module._complete_equipment_annotation_payload(
        {"workflow_summary": {"intent": "Replay the recording."}},
        workflow=workflow,
        current_annotations=annotations,
    )

    assert [item["step_id"] for item in completed["steps"]] == ["step-001", "step-002"]
    assert completed["steps"][0]["label"] == "set_input_language"
    assert completed["workflow_summary"]["intent"] == "Replay the recording."
    assert fallback_count == 2
    assert workflow["steps"][0]["action"]["layout_id"] == "00000412"


def test_selected_skill_annotation_stops_after_persisting_the_current_timeline_chunk(
    monkeypatch,
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts" / "equipment"
    frame_root = artifact_root / "recordings" / "rec-stop" / "frames" / "periodic"
    frame_root.mkdir(parents=True)
    frames = []
    for index in range(17):
        frame = frame_root / f"frame-{index + 1:08d}.jpg"
        Image.new("RGB", (320, 180), (40, index * 9 % 255, 120)).save(frame, quality=90)
        frames.append(
            {
                "frame_id": f"frame-{index + 1:08d}",
                "at_ms": index * 500,
                "artifact_path": str(frame),
                "sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
                "media_type": "image/jpeg",
                "width": 320,
                "height": 180,
                "reason": "periodic",
            }
        )
    calls: list[dict] = []

    class Backend:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            chunk = json.loads(kwargs["user_prompt"])["chunk"]
            return LLMResponse(
                text=json.dumps(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "summary": "Persist this completed chunk before stopping.",
                        "state_transitions": [],
                        "source_frame_ids": [item["frame_id"] for item in chunk["tiles"]],
                    }
                ),
                model="vision-model",
            )

    context = main_module.controller._deps.agent_context
    monkeypatch.setitem(context.primary_backends, "vllm", Backend())
    monkeypatch.setattr(
        main_module,
        "_equipment_skill_model_snapshot",
        lambda: {
            "provider": "vllm",
            "model": "vision-model",
            "role": "e4b",
            "endpoint_profile": "test",
            "capabilities": {"text": True, "vision": True},
            "fallback_allowed": False,
        },
    )
    original_resolve = main_module.resolve_path
    monkeypatch.setattr(
        main_module,
        "resolve_path",
        lambda value: artifact_root if str(value) == "artifacts/equipment" else original_resolve(value),
    )
    monkeypatch.setattr(
        main_module,
        "_manual_knowledge_context",
        lambda *_args, **_kwargs: {
            "schema": "manual_prompt_context.v1",
            "equipment_type": "",
            "purpose": "skill_authoring",
            "context_hash": "test",
            "insufficient_evidence": True,
            "chunks": [],
        },
    )
    package = {
        "workflow": {"name": "Stop-safe timeline skill", "steps": []},
        "annotations": {"steps": []},
        "recording": {"recording_id": "rec-stop", "events": []},
        "manifest": {
            "timeline_id": "timeline-rec-stop",
            "recording_evidence": {"fps": 2.0, "frames": frames},
        },
    }

    with pytest.raises(main_module._EquipmentSkillAuthoringStopped):
        asyncio.run(
            main_module._annotate_equipment_skill_with_selected_model(
                package,
                stop_requested=lambda: len(calls) >= 1,
            )
        )

    assert len(calls) == 1
    analysis_path = artifact_root / "skill_storyboards" / "rec-stop" / "analyses" / "chunk-0001.json"
    assert analysis_path.is_file()
    assert json.loads(analysis_path.read_text(encoding="utf-8"))["chunk_id"] == "chunk-0001"
