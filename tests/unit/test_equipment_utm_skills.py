from __future__ import annotations

from pathlib import Path

from utils.equipment_skill_runtime import EquipmentSkillRegistry, canonical_sha256
from utils.equipment_utm_skills import (
    UTM_SKILL_BINDINGS,
    bind_deployed_utm_skills,
    stage_utm_skill_packages,
)


REFERENCE_ROOT = Path(__file__).resolve().parents[2] / "references" / "trapeziumx_v_equipment_agent"


def test_stages_eight_bounded_utm_skills_and_binds_exact_deployed_versions(tmp_path: Path) -> None:
    registry_root = tmp_path / "equipment_skills"
    flow_path = tmp_path / "equipment_skill_flows.json"

    packages = stage_utm_skill_packages(
        registry_root=registry_root,
        reference_root=REFERENCE_ROOT,
    )

    assert [package["manifest"]["skill_id"] for package in packages] == [
        UTM_SKILL_BINDINGS[block_id][0] for block_id in UTM_SKILL_BINDINGS
    ]
    assert len(packages) == 8
    assert all(package["manifest"]["lifecycle"] == "validated" for package in packages)
    assert all(package["manifest"]["target_profile"] == "utm_windows_v1" for package in packages)

    actions_by_block = {
        block_id: [
            action
            for program in package["programs"]
            for action in program["sequence"]
        ]
        for block_id, package in zip(UTM_SKILL_BINDINGS, packages, strict=True)
    }
    assert [item["action"] for item in actions_by_block["prepare_next_specimen"]] == [
        "screenshot",
        "wait_until_image",
        "click",
        "wait_until_image",
        "click",
        "wait_until_image",
        "wait_until_image",
        "click",
        "wait_until_image",
        "screenshot",
    ]
    assert [
        item.get("target")
        for item in actions_by_block["prepare_next_specimen"]
        if item["action"] in {"wait_until_image", "click"}
    ] == [
        "entry_height_150_mm",
        "move_jigs_next_specimen",
        "confirm_crosshead_movement_dialog",
        "confirm_crosshead_movement_ok",
        "jig_distance_moving",
        "position_zero_reset_dialog",
        "position_zero_reset_yes",
        "start_test_ready",
    ]
    assert all(
        item["action"] not in {"assert_text", "wait_until_text", "wait_until"}
        for item in actions_by_block["prepare_next_specimen"]
    )
    prepare_locators = [
        candidate
        for item in actions_by_block["prepare_next_specimen"]
        for candidate in item.get("image_candidates", [])
    ]
    assert {candidate["source"] for candidate in prepare_locators} >= {
        "entry_height_150mm.png",
        "confirm_crosshead_movement_dialog.png",
        "confirm_crosshead_movement_ok.png",
        "confirm_crosshead_movement_ok_focused.png",
        "position_zero_reset_dialog.png",
        "position_zero_reset_yes.png",
        "jig_distance_moving_state.png",
        "start_test_ready.png",
    }
    confirm_ok_action = next(
        item
        for item in actions_by_block["prepare_next_specimen"]
        if item.get("target") == "confirm_crosshead_movement_ok"
    )
    assert [candidate["source"] for candidate in confirm_ok_action["image_candidates"]] == [
        "confirm_crosshead_movement_ok.png",
        "confirm_crosshead_movement_ok_focused.png",
    ]
    assert [item["action"] for item in actions_by_block["start_test"]] == [
        "screenshot",
        "wait_until_image",
        "click",
        "wait_until_image",
        "click",
        "wait_until_image",
        "screenshot",
    ]
    assert [
        item.get("target")
        for item in actions_by_block["start_test"]
        if item["action"] in {"wait_until_image", "click"}
    ] == [
        "start_height_30_5_mm",
        "start_test",
        "start_test_confirm_button",
        "start_test_confirm_button",
        "testing_state",
    ]
    height_interlock = next(
        item
        for item in actions_by_block["start_test"]
        if item.get("target") == "start_height_30_5_mm"
    )
    assert height_interlock["required"] is True
    assert height_interlock["timeout_s"] == 5
    assert [candidate["source"] for candidate in height_interlock["image_candidates"]] == [
        "start_height_30_5mm.png"
    ]
    assert all(candidate["confidence"] == 0.9 for candidate in height_interlock["image_candidates"])
    confirm_actions = [
        item
        for item in actions_by_block["start_test"]
        if item.get("target") == "start_test_confirm_button"
    ]
    assert [item["action"] for item in confirm_actions] == ["wait_until_image", "click"]
    assert all(item["required"] is True for item in confirm_actions)
    assert all(
        [candidate["source"] for candidate in item["image_candidates"]]
        == ["start_test_confirm_button.png"]
        for item in confirm_actions
    )
    assert all(
        candidate["confidence"] == 0.9
        for item in confirm_actions
        for candidate in item["image_candidates"]
    )
    assert all(
        item["action"] in {"wait_until_image", "screenshot"}
        for item in actions_by_block["monitor_contact_and_run"]
    )
    assert [item["action"] for item in actions_by_block["await_auto_return"]] == [
        "wait_until_image",
        "wait_until_image",
        "screenshot",
    ]
    assert [
        item.get("target")
        for item in actions_by_block["await_auto_return"]
        if item["action"] == "wait_until_image"
    ] == ["tests_completed", "auto_return_height_30_5_mm"]
    auto_return_height = next(
        item
        for item in actions_by_block["await_auto_return"]
        if item.get("target") == "auto_return_height_30_5_mm"
    )
    assert auto_return_height["required"] is True
    assert auto_return_height["timeout_s"] == 3600
    assert [candidate["source"] for candidate in auto_return_height["image_candidates"]] == [
        "start_height_30_5mm.png"
    ]
    assert all(candidate["confidence"] == 0.9 for candidate in auto_return_height["image_candidates"])
    assert [item["action"] for item in actions_by_block["restore_robot_clearance"]] == [
        "click",
        "wait_until_image",
        "wait_until_image",
        "screenshot",
    ]
    assert all(
        key not in action
        for actions in actions_by_block.values()
        for action in actions
        for key in ("force_threshold", "stroke_target", "height_target")
    )
    locator_candidates = [
        candidate
        for actions in actions_by_block.values()
        for action in actions
        for candidate in action.get("image_candidates", [])
    ]
    assert locator_candidates
    assert all(candidate["confidence"] == 0.9 for candidate in locator_candidates)
    assert all(
        action["action"] not in {"write", "type_path"}
        for block_id, actions in actions_by_block.items()
        if block_id != "save_raw_data"
        for action in actions
    )
    save_text = [
        action.get("text", "")
        for action in actions_by_block["save_raw_data"]
        if action["action"] == "write"
    ]
    assert save_text == ["C:/ATR/utm_exports/{run_id}/{specimen_id}.csv"]

    # Deployment is simulated by exact program hashes only; no Worker execution is invoked.
    registry = EquipmentSkillRegistry(registry_root)
    for skill_id, version in UTM_SKILL_BINDINGS.values():
        package = registry.get(skill_id, version)
        hashes = {
            program["program_id"]: canonical_sha256(program)
            for program in package["programs"]
        }
        registry.mark_deployed(
            skill_id,
            version,
            bridge_id="windows-lab-1",
            deployment_sha256=canonical_sha256(hashes),
            program_sha256=hashes,
        )

    flow = bind_deployed_utm_skills(
        registry_root=registry_root,
        flow_path=flow_path,
    )

    assert flow["agentic_task_id"] == "run_utm_compression_cycle"
    assert [block["id"] for block in flow["blocks"]] == list(UTM_SKILL_BINDINGS)
    assert [
        (block["skill"]["skill_id"], block["skill"]["skill_version"])
        for block in flow["blocks"]
    ] == list(UTM_SKILL_BINDINGS.values())
    assert all(block["vision"]["enabled"] is False for block in flow["blocks"])
    assert all(block["skill"]["skill_id"] != "equipment_demonstration" for block in flow["blocks"])


def test_visual_completion_upgrades_replace_only_changed_skill_versions() -> None:
    assert UTM_SKILL_BINDINGS["start_test"] == ("utm_start_test", "1.0.8")
    assert UTM_SKILL_BINDINGS["await_auto_return"] == ("utm_await_auto_return", "1.0.7")
    assert {
        version
        for block_id, (_skill_id, version) in UTM_SKILL_BINDINGS.items()
        if block_id not in {"start_test", "await_auto_return"}
    } == {"1.0.6"}
