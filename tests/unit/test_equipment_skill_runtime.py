from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from utils.equipment_skill_runtime import (
    EquipmentSkillRegistry,
    SkillContractError,
    build_exception_packet,
    canonical_sha256,
    compile_recording_actions,
    recording_capability_coverage,
    split_program_segments,
    validate_recovery_decision,
    validate_skill_package,
)


def _recording(*, event_count: int = 2) -> dict:
    events = [
        {"kind": "mouse_click", "at_ms": 100, "x": 320, "y": 240, "button": "left"},
        {"kind": "key_press", "at_ms": 180, "key": "enter"},
    ]
    if event_count > len(events):
        events.extend(
            {"kind": "key_press", "at_ms": 200 + index, "key": "tab"}
            for index in range(event_count - len(events))
        )
    return {
        "schema": "atr.equipment_recording.v1",
        "recording_id": "rec-program1",
        "name": "Program 1 demonstration",
        "target_app": "Program 1",
        "target_window": "Program 1",
        "status": "saved",
        "events": events,
        "checkpoints": [{"checkpoint_id": "cp-1", "at_ms": 190, "label": "completed"}],
    }


def _model_snapshot() -> dict:
    return {
        "provider": "vllm",
        "model": "gemma4:e4b-it-nvfp4",
        "endpoint_profile": "nemoclaw-vllm",
        "capabilities": {"text": True, "vision": False},
    }


def test_canonical_hash_is_order_independent() -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})


def test_recording_actions_compile_to_existing_program_actions() -> None:
    actions = compile_recording_actions(_recording()["events"])

    assert actions == [
        {"action": "click", "x": 320, "y": 240, "button": "left"},
        {"action": "press", "key": "enter"},
    ]


def test_recording_language_change_compiles_to_replayable_skill_action() -> None:
    actions = compile_recording_actions(
        [
            {"kind": "key_press", "at_ms": 100, "key": "a"},
            {
                "kind": "input_language_changed",
                "at_ms": 120,
                "input_language": {
                    "status": "available",
                    "layout_id": "00000412",
                    "locale": "ko_KR",
                    "language": "ko",
                    "ime_mode": "alphanumeric",
                    "typing_mode": "latin",
                },
            },
            {"kind": "key_press", "at_ms": 140, "key": "b"},
        ]
    )

    assert actions == [
        {"action": "write", "text": "a", "interval_sec": 0.02},
        {
            "action": "set_input_language",
            "layout_id": "00000412",
            "locale": "ko_KR",
            "language": "ko",
            "ime_mode": "alphanumeric",
            "typing_mode": "latin",
        },
        {"action": "write", "text": "b", "interval_sec": 0.02},
    ]

    coverage = recording_capability_coverage(
        [{"kind": "input_language_changed", "input_language": actions[1]}]
    )
    assert coverage["actions"] == ["set_input_language"]
    assert coverage["families"] == ["keyboard"]
    assert coverage["unsupported_event_kinds"] == []


def test_recording_control_click_is_not_compiled_as_equipment_action() -> None:
    events = [
        {"kind": "mouse_click", "at_ms": 100, "x": 320, "y": 240, "button": "left"},
        {
            "kind": "mouse_click",
            "at_ms": 200,
            "x": 984,
            "y": 46,
            "button": "left",
            "recording_control": "overlay_stop",
        },
    ]

    actions = compile_recording_actions(events)
    coverage = recording_capability_coverage(events)

    assert actions == [{"action": "click", "x": 320, "y": 240, "button": "left"}]
    assert coverage["actions"] == ["click"]
    assert coverage["recording_control_event_count"] == 1


def _inline_locator(locator_id: str, coordinate: tuple[int, int]) -> dict:
    raw = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    import base64
    import hashlib

    encoded = base64.b64encode(raw).decode("ascii")
    return {
        "locator_id": locator_id,
        "status": "ready",
        "recorded_coordinate": list(coordinate),
        "candidates": [
            {
                "kind": "tight",
                "png_base64": encoded,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "width": 64,
                "height": 64,
                "confidence": 0.88,
            }
        ],
    }


def test_image_first_click_compiles_without_executable_coordinates() -> None:
    locator = _inline_locator("evt-001-target", (320, 240))

    actions = compile_recording_actions(
        [{"kind": "mouse_click", "x": 320, "y": 240, "button": "left", "visual_locator": locator}],
        visual_locator_policy={
            "mode": "image_first",
            "required_for_pointer_actions": True,
            "coordinate_fallback": False,
        },
    )

    assert actions == [
        {
            "action": "click",
            "button": "left",
            "required": True,
            "target": "evt-001-target",
            "image_candidates": locator["candidates"],
            "recorded_coordinate": [320, 240],
        }
    ]
    assert "x" not in actions[0]
    assert "y" not in actions[0]


def test_image_first_compiler_omits_ambient_coordinate_mouse_moves() -> None:
    locator = _inline_locator("evt-004-target", (320, 240))

    actions = compile_recording_actions(
        [
            {"kind": "mouse_move", "at_ms": 50, "x": 100, "y": 110},
            {"kind": "mouse_move", "at_ms": 90, "x": 260, "y": 220},
            {
                "kind": "mouse_click",
                "at_ms": 120,
                "x": 320,
                "y": 240,
                "button": "left",
                "visual_locator": locator,
            },
        ],
        visual_locator_policy={
            "mode": "image_first",
            "required_for_pointer_actions": True,
            "coordinate_fallback": False,
        },
    )

    assert [item["action"] for item in actions] == ["click"]
    assert "x" not in actions[0]
    assert "y" not in actions[0]


def test_image_first_compiler_preserves_bounded_interaction_pauses() -> None:
    first = _inline_locator("evt-005-target", (100, 100))
    second = _inline_locator("evt-006-target", (200, 200))

    actions = compile_recording_actions(
        [
            {"kind": "mouse_click", "at_ms": 100, "x": 100, "y": 100, "visual_locator": first},
            {"kind": "mouse_move", "at_ms": 600, "x": 160, "y": 160},
            {"kind": "mouse_click", "at_ms": 1400, "x": 200, "y": 200, "visual_locator": second},
        ],
        visual_locator_policy={
            "mode": "image_first",
            "required_for_pointer_actions": True,
            "coordinate_fallback": False,
        },
    )

    assert [item["action"] for item in actions] == ["click", "wait", "click"]
    assert actions[1] == {"action": "wait", "seconds": 1.3}


def test_image_first_drag_compiles_source_and_target_image_locators() -> None:
    source = _inline_locator("evt-002-source", (100, 120))
    target = _inline_locator("evt-002-target", (420, 360))

    actions = compile_recording_actions(
        [
            {
                "kind": "mouse_drag",
                "start_x": 100,
                "start_y": 120,
                "x": 420,
                "y": 360,
                "button": "left",
                "duration_sec": 0.5,
                "source_visual_locator": source,
                "target_visual_locator": target,
            }
        ],
        visual_locator_policy={"mode": "image_first", "required_for_pointer_actions": True},
    )

    assert actions[0]["action"] == "move_to"
    assert actions[0]["target"] == "evt-002-source"
    assert actions[0]["image_candidates"] == source["candidates"]
    assert "x" not in actions[0]
    assert actions[1]["action"] == "drag_to"
    assert actions[1]["target"] == "evt-002-target"
    assert actions[1]["image_candidates"] == target["candidates"]
    assert "x" not in actions[1]


def test_image_first_compiler_rejects_missing_required_pointer_locator() -> None:
    with pytest.raises(SkillContractError, match="visual locator"):
        compile_recording_actions(
            [{"kind": "mouse_click", "x": 320, "y": 240, "button": "left"}],
            visual_locator_policy={
                "mode": "image_first",
                "required_for_pointer_actions": True,
                "coordinate_fallback": False,
            },
        )


def test_image_first_compiler_rejects_tampered_inline_png() -> None:
    locator = _inline_locator("evt-003-target", (10, 20))
    locator["candidates"][0]["sha256"] = "0" * 64

    with pytest.raises(SkillContractError, match="sha256"):
        compile_recording_actions(
            [{"kind": "mouse_click", "x": 10, "y": 20, "visual_locator": locator}],
            visual_locator_policy={"mode": "image_first", "required_for_pointer_actions": True},
        )


def test_registry_creates_v2_image_first_draft(tmp_path: Path) -> None:
    recording = _recording()
    recording["schema"] = "atr.equipment_recording.v2"
    recording["visual_locator_policy"] = {
        "mode": "image_first",
        "required_for_pointer_actions": True,
        "coordinate_fallback": False,
    }
    recording["events"][0]["visual_locator"] = _inline_locator("evt-001-target", (320, 240))

    created = EquipmentSkillRegistry(tmp_path).create_draft(
        recording=recording,
        skill_id="visual_program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )

    action = created["workflow"]["steps"][0]["action"]
    assert action["target"] == "evt-001-target"
    assert action["required"] is True
    assert "x" not in action


def test_compiler_emits_windows_worker_compatible_program_identity(tmp_path: Path) -> None:
    recording = _recording()
    recording["name"] = "N" * 240
    skill_id = "s" * 96
    version = "1.0.0-" + ("a" * 58)
    registry = EquipmentSkillRegistry(tmp_path)
    registry.create_draft(
        recording=recording,
        skill_id=skill_id,
        version=version,
        target_profile="windows_desktop_v1",
        model_snapshot=_model_snapshot(),
    )

    compiled = registry.compile(skill_id, version)

    assert compiled["programs"]
    for program in compiled["programs"]:
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", program["program_id"])
        assert len(program["name"]) <= 160


def test_registry_accepts_v3_time_series_recording_and_preserves_evidence_refs(tmp_path: Path) -> None:
    recording = _recording()
    recording["schema"] = "atr.equipment_recording.v3"
    recording["timeline_id"] = "timeline-buffered-program1"
    recording["exceptions"] = [
        {
            "exception_id": "exception-001",
            "timeline_id": "timeline-buffered-program1",
            "at_ms": 700,
            "failure_code": "LOCATOR_NOT_FOUND",
            "detail": "completion locator was not found",
        }
    ]
    recording["time_series_evidence"] = {
        "schema": "atr.equipment_recording_frames.v1",
        "timeline_id": "timeline-buffered-program1",
        "sampled_frame_count": 40,
        "persisted_frame_count": 2,
        "capture_errors": 0,
        "frames": [
            {"frame_id": "frame-0001", "at_ms": 0, "artifact_path": "timeline/frame-0001.jpg"},
            {"frame_id": "frame-0002", "at_ms": 1000, "artifact_path": "timeline/frame-0002.jpg"},
        ],
        "exception_window_count": 1,
        "exception_windows": [
            {
                "exception_id": "exception-001",
                "failure_code": "LOCATOR_NOT_FOUND",
                "at_ms": 700,
                "pre_window_ms": 5000,
                "post_window_ms": 5000,
                "frame_ids": ["frame-0001", "frame-0002"],
            }
        ],
    }

    created = EquipmentSkillRegistry(tmp_path).create_draft(
        recording=recording,
        skill_id="buffered_program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )

    assert created["manifest"]["recording_evidence"] == recording["time_series_evidence"]
    assert created["manifest"]["timeline_id"] == recording["timeline_id"]
    assert created["manifest"]["recording_exceptions"] == recording["exceptions"]


def test_mouse_move_recording_compiles_to_timed_move_to_actions() -> None:
    actions = compile_recording_actions(
        [
            {"kind": "mouse_move", "at_ms": 100, "x": 780, "y": 440},
            {"kind": "mouse_move", "at_ms": 350, "x": 900, "y": 440},
            {"kind": "mouse_move", "at_ms": 600, "x": 900, "y": 520},
        ]
    )

    assert actions == [
        {"action": "move_to", "x": 780, "y": 440, "duration_sec": 0.1},
        {"action": "move_to", "x": 900, "y": 440, "duration_sec": 0.25},
        {"action": "move_to", "x": 900, "y": 520, "duration_sec": 0.25},
    ]


def test_recording_compiler_compacts_text_and_preserves_non_printable_keys() -> None:
    actions = compile_recording_actions(
        [
            {"kind": "key_press", "at_ms": 10, "key": "a"},
            {"kind": "key_press", "at_ms": 20, "key": "t"},
            {"kind": "key_press", "at_ms": 30, "key": "r"},
            {"kind": "key_press", "at_ms": 40, "key": "space"},
            {"kind": "key_press", "at_ms": 50, "key": "1"},
            {"kind": "key_press", "at_ms": 60, "key": "2"},
            {"kind": "key_press", "at_ms": 70, "key": "enter"},
        ]
    )

    assert actions == [
        {"action": "write", "text": "atr 12"},
        {"action": "press", "key": "enter"},
    ]


def test_recording_compiler_translates_drag_and_two_axis_scroll() -> None:
    actions = compile_recording_actions(
        [
            {
                "kind": "mouse_drag",
                "at_ms": 500,
                "start_x": 100,
                "start_y": 120,
                "x": 420,
                "y": 360,
                "button": "left",
                "duration_sec": 0.5,
            },
            {"kind": "mouse_scroll", "at_ms": 700, "dx": -2, "dy": 4},
        ]
    )

    assert actions == [
        {"action": "move_to", "x": 100, "y": 120, "duration_sec": 0.05},
        {"action": "drag_to", "x": 420, "y": 360, "button": "left", "duration_sec": 0.5},
        {"action": "hscroll", "clicks": -2},
        {"action": "scroll", "clicks": 4},
    ]


def test_recording_capability_coverage_reports_recorded_families() -> None:
    coverage = recording_capability_coverage(
        [
            {"kind": "mouse_click", "x": 1, "y": 2},
            {"kind": "mouse_drag", "start_x": 1, "start_y": 2, "x": 3, "y": 4},
            {"kind": "mouse_scroll", "dx": 0, "dy": 1},
            {"kind": "hotkey", "keys": ["ctrl", "s"]},
        ]
    )

    assert coverage == {
        "actions": ["click", "drag_to", "hotkey", "scroll"],
        "families": ["keyboard", "mouse"],
        "event_count": 4,
        "hotkey_count": 1,
        "drag_count": 1,
        "scroll_count": 1,
        "unsupported_event_kinds": [],
    }


def test_segments_never_exceed_existing_program_limit() -> None:
    actions = compile_recording_actions(_recording(event_count=205)["events"])
    segments = split_program_segments(actions)

    assert [len(segment) for segment in segments] == [100, 100, 5]


def test_registry_creates_reloadable_draft_and_exact_hashes(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    created = registry.create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )

    assert created["manifest"]["schema"] == "atr.equipment_skill.v1"
    assert created["manifest"]["lifecycle"] == "draft"
    assert created["manifest"]["recording_sha256"] == canonical_sha256(_recording())
    assert created["manifest"]["capability_coverage"]["families"] == ["keyboard", "mouse"]
    assert created["workflow"]["capability_coverage"]["actions"] == ["click", "press"]
    assert EquipmentSkillRegistry(tmp_path).get("program1_skill", "1.0.0") == created


def test_registry_reuses_empty_version_directory_left_by_interrupted_authoring(tmp_path: Path) -> None:
    stale = tmp_path / "program1_skill" / "1.0.0"
    stale.mkdir(parents=True)

    created = EquipmentSkillRegistry(tmp_path).create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )

    assert created["manifest"]["skill_id"] == "program1_skill"
    assert (stale / "manifest.json").is_file()


def test_registry_rejects_unsafe_identity(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)

    with pytest.raises(SkillContractError, match="skill_id"):
        registry.create_draft(
            recording=_recording(),
            skill_id="../escape",
            version="1.0.0",
            target_profile="local_program1",
            model_snapshot=_model_snapshot(),
        )


def test_compile_emits_existing_schema_segments_and_validates(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    registry.create_draft(
        recording=_recording(event_count=101),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )

    compiled = registry.compile("program1_skill", "1.0.0")
    validated = registry.validate("program1_skill", "1.0.0")

    assert [len(item["sequence"]) for item in compiled["programs"]] == [100, 1]
    assert all(item["schema"] == "atr.pyautogui_program.v1" for item in compiled["programs"])
    assert all(item["requires_pyautogui"] is True for item in compiled["programs"])
    assert validated["ok"] is True
    assert validated["package"]["manifest"]["lifecycle"] == "validated"


def test_annotation_review_blocks_validation_until_resolved(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    registry.create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )
    annotated = registry.annotate(
        "program1_skill",
        "1.0.0",
        {
            "steps": [
                {"step_id": "step-001", "label": "Select target", "confidence": 0.4, "review_required": True},
                {"step_id": "step-002", "label": "Confirm", "confidence": 0.9, "review_required": False},
            ]
        },
    )
    registry.compile("program1_skill", "1.0.0")

    assert annotated["manifest"]["lifecycle"] == "review_required"
    with pytest.raises(SkillContractError, match="review"):
        registry.validate("program1_skill", "1.0.0")

    registry.annotate(
        "program1_skill",
        "1.0.0",
        {
            "steps": [
                {"step_id": "step-001", "label": "Select target", "confidence": 0.95, "review_required": False},
                {"step_id": "step-002", "label": "Confirm", "confidence": 0.95, "review_required": False},
            ]
        },
    )
    assert registry.validate("program1_skill", "1.0.0")["ok"] is True


def test_annotation_locator_is_persisted_into_executable_workflow(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    registry.create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )

    package = registry.annotate(
        "program1_skill",
        "1.0.0",
        {
            "steps": [
                {
                    "step_id": "step-001",
                    "label": "Select target",
                    "confidence": 0.95,
                    "review_required": False,
                    "locator": {
                        "region_normalized": [0.1, 0.2, 0.3, 0.4],
                        "locator_backend": "multimodal_roi_image",
                    },
                }
            ]
        },
    )

    assert package["workflow"]["steps"][0]["action"]["region_normalized"] == [0.1, 0.2, 0.3, 0.4]
    assert package["workflow"]["steps"][0]["action"]["locator_backend"] == "multimodal_roi_image"


def test_annotation_persists_bounded_workflow_semantics(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    registry.create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )

    package = registry.annotate(
        "program1_skill",
        "1.0.0",
        {
            "workflow_summary": {
                "intent": "Open the test program and start one bounded run.",
                "initial_state": "Program is idle.",
                "completion_state": "Run result is visible.",
            },
            "step_transitions": [
                {
                    "step_id": "step-001",
                    "before_state": "Program is idle.",
                    "action_effect": "The start control is activated.",
                    "after_state": "The run begins.",
                    "success_evidence": "Running indicator appears.",
                }
            ],
            "steps": [],
        },
    )

    assert package["annotations"]["workflow_summary"]["intent"] == (
        "Open the test program and start one bounded run."
    )
    assert package["annotations"]["step_transitions"][0]["step_id"] == "step-001"
    assert package["annotations"]["step_transitions"][0]["success_evidence"] == (
        "Running indicator appears."
    )

def test_deploy_lifecycle_requires_validation_and_exact_hash(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    registry.create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )

    with pytest.raises(SkillContractError, match="validated"):
        registry.mark_deployed("program1_skill", "1.0.0", bridge_id="local", deployment_sha256="a" * 64)

    registry.compile("program1_skill", "1.0.0")
    registry.validate("program1_skill", "1.0.0")
    deployed = registry.mark_deployed(
        "program1_skill",
        "1.0.0",
        bridge_id="local",
        deployment_sha256="a" * 64,
    )

    assert deployed["manifest"]["lifecycle"] == "deployed"
    assert deployed["manifest"]["deployment"]["sha256"] == "a" * 64


def test_update_workflow_reorders_steps_and_invalidates_compiled_artifacts(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    registry.create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )
    before = registry.compile("program1_skill", "1.0.0")
    edited = deepcopy(before["workflow"])
    edited["steps"] = list(reversed(edited["steps"]))

    updated = registry.update_workflow(
        "program1_skill",
        "1.0.0",
        edited,
        expected_workflow_sha256=before["manifest"]["workflow_sha256"],
    )

    assert [item["step_id"] for item in updated["workflow"]["steps"]] == ["step-002", "step-001"]
    assert updated["workflow"]["program_ids"] == []
    assert updated["programs"] == []
    assert updated["manifest"]["program_sha256"] == {}
    assert updated["manifest"]["lifecycle"] == "annotated"
    assert "compiled_at" not in updated["workflow"]
    audit = (tmp_path / "program1_skill" / "1.0.0" / "audit.jsonl").read_text(encoding="utf-8")
    assert '"event":"workflow_edited"' in audit


def test_update_workflow_rejects_stale_hash(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    package = registry.create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )

    with pytest.raises(SkillContractError, match="revision conflict"):
        registry.update_workflow(
            "program1_skill",
            "1.0.0",
            package["workflow"],
            expected_workflow_sha256="0" * 64,
        )


def test_update_workflow_rejects_deployed_exact_version(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    registry.create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )
    registry.compile("program1_skill", "1.0.0")
    registry.validate("program1_skill", "1.0.0")
    deployed = registry.mark_deployed(
        "program1_skill",
        "1.0.0",
        bridge_id="local",
        deployment_sha256="a" * 64,
    )

    with pytest.raises(SkillContractError, match="immutable"):
        registry.update_workflow(
            "program1_skill",
            "1.0.0",
            deployed["workflow"],
            expected_workflow_sha256=deployed["manifest"]["workflow_sha256"],
        )


def test_validate_skill_package_rejects_tampered_workflow(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    registry.create_draft(
        recording=_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
    )
    registry.compile("program1_skill", "1.0.0")
    package_dir = tmp_path / "program1_skill" / "1.0.0"
    workflow_path = package_dir / "workflow.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    workflow["steps"][0]["label"] = "tampered"
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

    with pytest.raises(SkillContractError, match="hash"):
        validate_skill_package(package_dir)


def test_exception_packet_is_bounded_and_recovery_allowlisted() -> None:
    packet = build_exception_packet(
        skill_id="program1_skill",
        version="1.0.0",
        execution_id="exec-1",
        segment_id="program1_skill_1_0_0_segment_001",
        checkpoint_id="cp-1",
        failure_code="PYAUTOGUI_WINDOW_NOT_FOUND",
        message="window focus was lost",
        evidence=[{"artifact_id": "screen-1", "sha256": "a" * 64}],
        allowed_recovery_operations=["focus_window", "press"],
    )

    assert packet["schema"] == "atr.equipment_skill_exception.v1"
    assert packet["allowed_recovery_operations"] == ["focus_window", "press"]
    assert "click" not in packet["allowed_recovery_operations"]


def test_recovery_decision_must_match_exception_allowlist() -> None:
    packet = build_exception_packet(
        skill_id="program1_skill",
        version="1.0.0",
        execution_id="exec-1",
        segment_id="program1_skill_1_0_0_segment_001",
        checkpoint_id="cp-1",
        failure_code="PYAUTOGUI_WINDOW_NOT_FOUND",
        message="window focus was lost",
        evidence=[{"artifact_id": "screen-1", "sha256": "a" * 64}],
        allowed_recovery_operations=["focus_window", "screenshot"],
    )

    valid = validate_recovery_decision(
        {
            "schema": "atr.equipment_skill_recovery.v1",
            "operation": "focus_window",
            "payload": {"target_window": "Program 1"},
            "expected_verification": {"window_focused": True},
            "confidence": 0.91,
            "attempt": 1,
        },
        exception=packet,
        max_attempts=1,
    )
    assert valid["operation"] == "focus_window"

    with pytest.raises(SkillContractError, match="not allowed"):
        validate_recovery_decision(
            {
                "schema": "atr.equipment_skill_recovery.v1",
                "operation": "click",
                "payload": {"x": 10, "y": 10},
                "expected_verification": {"clicked": True},
                "confidence": 0.99,
                "attempt": 1,
            },
            exception=packet,
            max_attempts=1,
        )


def test_execution_state_is_idempotent_for_same_sequence(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    first = registry.begin_execution(
        skill_id="program1_skill",
        version="1.0.0",
        sequence_id="sequence-1",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
        allow_unvalidated=True,
    )
    second = registry.begin_execution(
        skill_id="program1_skill",
        version="1.0.0",
        sequence_id="sequence-1",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
        allow_unvalidated=True,
    )

    assert second["execution_id"] == first["execution_id"]
    assert second["idempotent"] is True


def test_execution_preserves_agentic_task_and_existing_skill_annotation(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)

    execution = registry.begin_execution(
        skill_id="program1_skill",
        version="1.0.0",
        sequence_id="sequence-agentic-task",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
        allow_unvalidated=True,
        agentic_task="Run bounded compression test",
        annotation_context={
            "workflow_summary": {
                "intent": "Run the recorded compression workflow.",
                "completion_state": "The result view is visible.",
            }
        },
    )

    assert execution["agentic_task"] == "Run bounded compression test"
    assert execution["annotation_context"]["workflow_summary"]["intent"] == (
        "Run the recorded compression workflow."
    )
    assert execution["runtime_execution"]["metadata"]["agentic_task"] == (
        "Run bounded compression test"
    )


def test_skill_completion_does_not_claim_analysis_readiness_without_profile_verification(tmp_path: Path) -> None:
    registry = EquipmentSkillRegistry(tmp_path)
    execution = registry.begin_execution(
        skill_id="program1_skill",
        version="1.0.0",
        sequence_id="sequence-complete",
        target_profile="local_program1",
        model_snapshot=_model_snapshot(),
        allow_unvalidated=True,
    )

    completed = registry.transition_execution(execution["execution_id"], "COMPLETED")

    assert completed["state"] == "COMPLETED"
    assert completed["runtime_execution"]["lifecycle"] == "VERIFYING"
    assert completed["handoff"]["status"] == "execution_complete"
    assert completed["handoff"]["ready_for_analysis"] is False

    verified = registry.finalize_execution_verification(
        execution["execution_id"],
        verified=True,
        completion={"ok": True, "status": "verified_complete"},
        handoff={"status": "ready_for_analysis", "ready_for_analysis": True},
        evidence=[{"kind": "request_log", "artifact_id": "request-log-1"}],
        raw_result={"ok": True, "status": "completed"},
    )

    assert verified["runtime_execution"]["lifecycle"] == "COMPLETED"
    assert verified["handoff"]["status"] == "ready_for_analysis"
