"""Code-owned exact Skill catalog for the recorded TRAPEZIUM-X UTM flow."""

from __future__ import annotations

import base64
from collections import OrderedDict
from io import BytesIO
import hashlib
from pathlib import Path
from typing import Any

from PIL import Image

from utils.equipment_agentic_task import (
    UTM_COMPRESSION_BLOCKS,
    build_utm_compression_flow_template,
)
from utils.equipment_skill_flow import EquipmentSkillFlowStore
from utils.equipment_skill_runtime import EquipmentSkillRegistry, SkillContractError


UTM_PROFILE_ID = "utm_windows_v1"
UTM_SKILL_VERSION = "1.0.8"
UTM_SKILL_BINDINGS: "OrderedDict[str, tuple[str, str]]" = OrderedDict(
    (
        ("prepare_next_specimen", ("utm_prepare_next_specimen", "1.0.6")),
        ("start_test", ("utm_start_test", UTM_SKILL_VERSION)),
        ("monitor_contact_and_run", ("utm_monitor_contact_and_run", "1.0.6")),
        ("await_auto_return", ("utm_await_auto_return", "1.0.7")),
        ("save_raw_data", ("utm_save_raw_data", "1.0.8")),
        ("validate_raw_data", ("utm_validate_raw_data", "1.0.6")),
        ("advance_without_save", ("utm_advance_without_save", "1.0.6")),
        ("restore_robot_clearance", ("utm_restore_robot_clearance", "1.0.6")),
    )
)

_MODEL_SNAPSHOT = {
    "provider": "code_owned",
    "model": "trapeziumx-recorded-flow-2026-09-01",
    "endpoint_profile": "recorded_reference",
    "fallback_allowed": False,
}
_EXPORT_GLOB = "C:/ATR/utm_exports/{run_id}/{specimen_id}*.csv"
_START_HEIGHT_30_5_PNG_BASE64 = (
    "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"
)
_START_TEST_CONFIRM_BUTTON_PNG_BASE64 = (
    "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"
)


def _locator_candidate(path: Path, crop: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise SkillContractError(f"UTM reference locator is missing: {path}")
    with Image.open(path) as source:
        image = source.convert("RGB")
        if crop is not None:
            image = image.crop(crop)
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
    raw = output.getvalue()
    width, height = image.size
    if not 1 <= width <= 512 or not 1 <= height <= 512:
        raise SkillContractError(f"UTM locator dimensions are invalid: {path.name} ({width}x{height})")
    return {
        "kind": "recorded_reference",
        "png_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": width,
        "height": height,
        "confidence": 0.9,
        "source": path.name,
    }


def _embedded_locator_candidate(*, png_base64: str, source: str) -> dict[str, Any]:
    raw = base64.b64decode(png_base64, validate=True)
    with Image.open(BytesIO(raw)) as image:
        image.verify()
        width, height = image.size
    if not 1 <= width <= 512 or not 1 <= height <= 512:
        raise SkillContractError(f"UTM locator dimensions are invalid: {source} ({width}x{height})")
    return {
        "kind": "recorded_reference",
        "png_base64": png_base64,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": width,
        "height": height,
        "confidence": 0.9,
        "source": source,
    }


def _visual_action(
    action: str,
    *,
    target: str,
    candidate: dict[str, Any] | list[dict[str, Any]],
    timeout_s: float | None = None,
) -> dict[str, Any]:
    candidates = candidate if isinstance(candidate, list) else [candidate]
    value: dict[str, Any] = {
        "action": action,
        "target": target,
        "required": True,
        "image_candidates": candidates,
    }
    if timeout_s is not None:
        value.update({"timeout_s": timeout_s, "poll_interval_s": 0.25})
    return value


def _step(index: int, label: str, action: dict[str, Any], *, checkpoint: bool = False) -> dict[str, Any]:
    return {
        "step_id": f"step-{index:03d}",
        "label": label,
        "action": action,
        "checkpoint_after": checkpoint,
    }


def _skill_workflows(reference_root: Path) -> dict[str, list[dict[str, Any]]]:
    locators = Path(reference_root) / "images" / "locators"
    jig_controls = locators / "jig_motion_controls.png"
    result_controls = locators / "export_and_next_test_controls.png"

    entry_height_150 = _locator_candidate(locators / "entry_height_150mm.png")
    confirm_crosshead_dialog = _locator_candidate(locators / "confirm_crosshead_movement_dialog.png")
    confirm_crosshead_ok = [
        _locator_candidate(locators / "confirm_crosshead_movement_ok.png"),
        _locator_candidate(locators / "confirm_crosshead_movement_ok_focused.png"),
    ]
    position_zero_reset_dialog = _locator_candidate(locators / "position_zero_reset_dialog.png")
    position_zero_reset_yes = _locator_candidate(locators / "position_zero_reset_yes.png")
    move_next = _locator_candidate(jig_controls, (4, 4, 278, 46))
    move_any_distance = _locator_candidate(jig_controls, (278, 4, 516, 46))
    save_raw = _locator_candidate(result_controls, (8, 8, 170, 43))
    next_without_save = _locator_candidate(result_controls, (8, 101, 170, 136))
    start_ready = _locator_candidate(locators / "start_test_ready.png")
    start_height_30_5 = _embedded_locator_candidate(
        png_base64=_START_HEIGHT_30_5_PNG_BASE64,
        source="start_height_30_5mm.png",
    )
    start_confirm = _embedded_locator_candidate(
        png_base64=_START_TEST_CONFIRM_BUTTON_PNG_BASE64,
        source="start_test_confirm_button.png",
    )
    testing = _locator_candidate(locators / "testing_state.png")
    completed = _locator_candidate(locators / "tests_completed_state.png")
    jig_moving = _locator_candidate(locators / "jig_distance_moving_state.png")
    loading = _locator_candidate(locators / "loading_main_screen_state.png")

    return {
        "prepare_next_specimen": [
            _step(1, "Capture full screen before preparation", {"action": "screenshot", "checkpoint": "prepare_next_specimen_initial_full_screen"}, checkpoint=True),
            _step(2, "Require robot-entry Height 150 mm", _visual_action("wait_until_image", target="entry_height_150_mm", candidate=entry_height_150, timeout_s=5)),
            _step(3, "Move Jigs for Next Specimen", _visual_action("click", target="move_jigs_next_specimen", candidate=move_next)),
            _step(4, "Confirm crosshead movement dialog", _visual_action("wait_until_image", target="confirm_crosshead_movement_dialog", candidate=confirm_crosshead_dialog, timeout_s=10)),
            _step(5, "Accept crosshead movement", _visual_action("click", target="confirm_crosshead_movement_ok", candidate=confirm_crosshead_ok)),
            _step(6, "Observe jig motion", _visual_action("wait_until_image", target="jig_distance_moving", candidate=jig_moving, timeout_s=15)),
            _step(7, "Wait for Position Zero-Reset dialog", _visual_action("wait_until_image", target="position_zero_reset_dialog", candidate=position_zero_reset_dialog, timeout_s=180)),
            _step(8, "Accept Position Zero-Reset", _visual_action("click", target="position_zero_reset_yes", candidate=position_zero_reset_yes)),
            _step(9, "Wait for test-ready screen", _visual_action("wait_until_image", target="start_test_ready", candidate=start_ready, timeout_s=60)),
            _step(10, "Capture prepared state", {"action": "screenshot", "checkpoint": "prepare_next_specimen_complete"}, checkpoint=True),
        ],
        "start_test": [
            _step(1, "Capture full screen before Start Test", {"action": "screenshot", "checkpoint": "start_test_initial_full_screen"}, checkpoint=True),
            _step(2, "Require Start Height 30.5 mm", _visual_action("wait_until_image", target="start_height_30_5_mm", candidate=start_height_30_5, timeout_s=5)),
            _step(3, "Start Test", _visual_action("click", target="start_test", candidate=start_ready)),
            _step(4, "Wait for Start Test confirmation", _visual_action("wait_until_image", target="start_test_confirm_button", candidate=start_confirm, timeout_s=10)),
            _step(5, "Confirm Start Test", _visual_action("click", target="start_test_confirm_button", candidate=start_confirm)),
            _step(6, "Confirm Testing state", _visual_action("wait_until_image", target="testing_state", candidate=testing, timeout_s=15)),
            _step(7, "Capture test start", {"action": "screenshot", "checkpoint": "start_test_complete"}, checkpoint=True),
        ],
        "monitor_contact_and_run": [
            _step(1, "Wait for method-controlled completion", _visual_action("wait_until_image", target="tests_completed", candidate=completed, timeout_s=3600)),
            _step(2, "Capture completed test", {"action": "screenshot", "checkpoint": "method_run_complete"}, checkpoint=True),
        ],
        "await_auto_return": [
            _step(1, "Keep completed state visible", _visual_action("wait_until_image", target="tests_completed", candidate=completed, timeout_s=30)),
            _step(2, "Wait for automatic Height return to 30.5 mm", _visual_action("wait_until_image", target="auto_return_height_30_5_mm", candidate=start_height_30_5, timeout_s=3600)),
            _step(3, "Capture automatic return state", {"action": "screenshot", "checkpoint": "auto_return_observed"}, checkpoint=True),
        ],
        "save_raw_data": [
            _step(1, "Save Raw Data to CSV File", _visual_action("click", target="save_raw_data_csv", candidate=save_raw)),
            _step(2, "Keep Save dialog visible", {"action": "wait", "seconds": 2.0}),
            _step(3, "Select file name field", {"action": "hotkey", "keys": ["ctrl", "a"]}),
            _step(4, "Paste worker-owned Raw CSV path", {"action": "paste_runtime_value", "key": "raw_csv_path"}),
            _step(5, "Keep pasted path visible", {"action": "wait", "seconds": 1.5}),
            _step(6, "Confirm CSV save", {"action": "press", "key": "enter"}),
            _step(7, "Wait for stable CSV", {"action": "wait_for_file", "pattern": "{raw_csv_path}", "timeout_s": 30, "poll_interval_s": 0.25, "stable_for_sec": 2.0, "required": True}),
            _step(8, "Keep saved result visible", {"action": "wait", "seconds": 1.0}),
            _step(9, "Capture CSV save result", {"action": "screenshot", "checkpoint": "raw_csv_saved"}, checkpoint=True),
        ],
        "validate_raw_data": [
            _step(1, "Require the run-scoped CSV", {"action": "wait_for_file", "pattern": _EXPORT_GLOB, "timeout_s": 10, "poll_interval_s": 0.25, "stable_for_sec": 2.0, "required": True}),
            _step(2, "Capture CSV validation boundary", {"action": "screenshot", "checkpoint": "raw_csv_validation_boundary"}, checkpoint=True),
        ],
        "advance_without_save": [
            _step(1, "Next Test without saving current test", _visual_action("click", target="next_test_without_save", candidate=next_without_save)),
            _step(2, "Observe Loading Main screen", _visual_action("wait_until_image", target="loading_main_screen", candidate=loading, timeout_s=15)),
            _step(3, "Wait for the new Ready screen", _visual_action("wait_until_image", target="start_test_ready", candidate=start_ready, timeout_s=60)),
            _step(4, "Capture next-test Ready state", {"action": "screenshot", "checkpoint": "next_test_ready"}, checkpoint=True),
        ],
        "restore_robot_clearance": [
            _step(1, "Move to configured inter-jig distance", _visual_action("click", target="move_to_configured_inter_jig_distance", candidate=move_any_distance)),
            _step(2, "Observe clearance motion", _visual_action("wait_until_image", target="jig_distance_moving", candidate=jig_moving, timeout_s=15)),
            _step(3, "Wait for Ready state after configured clearance", _visual_action("wait_until_image", target="start_test_ready", candidate=start_ready, timeout_s=180)),
            _step(4, "Capture robot-entry clearance", {"action": "screenshot", "checkpoint": "robot_clearance_restored"}, checkpoint=True),
        ],
    }


def _recording(skill_id: str, name: str, version: str) -> dict[str, Any]:
    return {
        "schema": "atr.equipment_recording.v1",
        "recording_id": f"recorded-reference-{skill_id}-{version}",
        "name": name,
        "target_app": "TRAPEZIUM-X",
        "target_window": "TRAPEZIUM-X-V",
        "status": "saved",
        "events": [{"kind": "key_press", "at_ms": 0, "key": "esc"}],
        "checkpoints": [],
        "source_reference": "TRAPEZIUMX-V 2026-09-01 recorded workflow",
    }


def _desired_workflow(
    *, skill_id: str, version: str, steps: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema": "atr.equipment_skill.v1",
        "skill_id": skill_id,
        "version": version,
        "steps": steps,
        "program_ids": [],
        "capability_coverage": {
            "source": "recorded_reference",
            "pointer_policy": "image_first_no_coordinate_fallback",
        },
    }


def stage_utm_skill_packages(
    *,
    registry_root: str | Path,
    reference_root: str | Path,
    target_profile: str = UTM_PROFILE_ID,
) -> list[dict[str, Any]]:
    """Create, compile, and validate all exact UTM Skills without executing them."""
    registry = EquipmentSkillRegistry(registry_root)
    workflows = _skill_workflows(Path(reference_root))
    task_names = dict(UTM_COMPRESSION_BLOCKS)
    packages: list[dict[str, Any]] = []
    for block_id, (skill_id, version) in UTM_SKILL_BINDINGS.items():
        desired = _desired_workflow(skill_id=skill_id, version=version, steps=workflows[block_id])
        try:
            package = registry.get(skill_id, version)
        except SkillContractError:
            package = registry.create_draft(
                recording=_recording(skill_id, task_names[block_id], version),
                skill_id=skill_id,
                version=version,
                target_profile=target_profile,
                model_snapshot=_MODEL_SNAPSHOT,
            )
        if package["manifest"].get("target_profile") != target_profile:
            raise SkillContractError(f"target profile mismatch for {skill_id}@{version}")
        current_steps = package["workflow"].get("steps", [])
        if package["manifest"].get("lifecycle") in {"deployed", "disabled"}:
            if current_steps != desired["steps"]:
                raise SkillContractError(f"immutable deployed UTM Skill differs from catalog: {skill_id}@{version}")
            packages.append(package)
            continue
        if current_steps != desired["steps"]:
            package = registry.update_workflow(
                skill_id,
                version,
                desired,
                expected_workflow_sha256=package["manifest"]["workflow_sha256"],
            )
        package = registry.annotate(
            skill_id,
            version,
            {
                "steps": [
                    {
                        "step_id": step["step_id"],
                        "label": step["label"],
                        "confidence": 1.0,
                        "review_required": False,
                        "checkpoint_after": step.get("checkpoint_after", False),
                    }
                    for step in desired["steps"]
                ],
                "workflow_summary": {
                    "intent": task_names[block_id],
                    "initial_state": "Previous canonical UTM block verified",
                    "completion_state": "Recorded GUI/file checkpoint verified",
                    "failure_state": "Expected state or artifact not verified before timeout",
                },
            },
            model_snapshot=_MODEL_SNAPSHOT,
        )
        package = registry.compile(skill_id, version)
        package = registry.validate(skill_id, version)["package"]
        packages.append(package)
    return packages


def bind_deployed_utm_skills(
    *,
    registry_root: str | Path,
    flow_path: str | Path,
    profile_id: str = UTM_PROFILE_ID,
) -> dict[str, Any]:
    """Bind all exact deployed/enabled UTM versions as one atomic canonical flow."""
    registry = EquipmentSkillRegistry(registry_root)
    flow = build_utm_compression_flow_template(profile_id)
    for block in flow["blocks"]:
        skill_id, version = UTM_SKILL_BINDINGS[block["id"]]
        package = registry.get(skill_id, version)
        manifest = package["manifest"]
        if manifest.get("lifecycle") != "deployed" or manifest.get("enabled") is False:
            raise SkillContractError(f"exact UTM Skill is not deployed and enabled: {skill_id}@{version}")
        if manifest.get("target_profile") != profile_id:
            raise SkillContractError(f"UTM Skill Profile mismatch: {skill_id}@{version}")
        block["skill"] = {"skill_id": skill_id, "skill_version": version}
    return EquipmentSkillFlowStore(Path(flow_path)).save(profile_id, flow)["flow"]
