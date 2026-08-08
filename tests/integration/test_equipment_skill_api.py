from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module
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


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(main_module, "EQUIPMENT_SKILL_ROOT", tmp_path / "skills")
    return TestClient(main_module.app)


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
    body = response.json()
    assert body["ok"] is True
    assert body["manifest"]["lifecycle"] == "deployed"
    assert body["manifest"]["deployment"]["program_ids"] == [item["program_id"] for item in registered]
    assert body["manifest"]["deployment"]["program_sha256"] == {
        item["program_id"]: canonical_sha256(item) for item in registered
    }


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
