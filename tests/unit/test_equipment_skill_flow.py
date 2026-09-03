"""Tests for the shared Lab Equipment composite Skill Flow contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils.equipment_agentic_task import build_utm_compression_flow_template
from utils.equipment_skill_flow import (
    STORE_SCHEMA,
    EquipmentSkillFlowError,
    EquipmentSkillFlowStore,
    normalize_equipment_skill_flow,
)


def _flow() -> dict:
    return {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": "utm_windows_v1",
        "profile_id": "utm_windows_v1",
        "version": 1,
        "blocks": [
            {
                "id": "prepare",
                "label": "Prepare UTM",
                "skill": {"skill_id": "utm_prepare", "skill_version": "1.0.0"},
                "agentic": {"completed": "next", "failed": "__blocked__"},
                "vision": {
                    "enabled": True,
                    "blocking": False,
                    "task_id": "utm_pre_start",
                    "detected": "next",
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                },
            },
            {
                "id": "test",
                "label": "Run UTM",
                "skill": {"skill_id": "utm_test", "skill_version": "2.0.0"},
                "agentic": {"completed": "__complete__", "failed": "__blocked__"},
                "vision": {
                    "enabled": False,
                    "task_id": "utm_test_complete",
                    "detected": "__complete__",
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                },
            },
        ],
    }


def test_flow_store_round_trips_composite_blocks(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")

    saved = store.save("utm_windows_v1", _flow())
    loaded = store.get("utm_windows_v1")

    assert saved["ok"] is True
    assert [block["id"] for block in loaded["blocks"]] == ["prepare", "test"]
    assert loaded["blocks"][0]["skill"]["skill_id"] == "utm_prepare"
    assert loaded["blocks"][0]["agentic"]["task"] == "Prepare UTM"
    assert loaded["blocks"][0]["vision"]["enabled"] is True
    assert loaded["blocks"][0]["vision"]["blocking"] is False
    assert loaded["blocks"][0]["vision"]["task_id"] == "utm_pre_start"
    assert "condition" not in loaded["blocks"][0]["vision"]
    assert "nodes" not in loaded


def test_explicit_agentic_task_is_canonical_and_updates_legacy_label(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    flow = _flow()
    flow["blocks"][0]["agentic"]["task"] = "Prepare compression specimen"

    loaded = store.save("utm_windows_v1", flow)["flow"]

    assert loaded["blocks"][0]["agentic"]["task"] == "Prepare compression specimen"
    assert loaded["blocks"][0]["label"] == "Prepare compression specimen"


def test_workflow_agentic_task_binding_round_trips_without_affecting_block_vision() -> None:
    """Catch normalization that drops the overlay binding or changes optional Vision."""
    flow = normalize_equipment_skill_flow(
        "utm_windows_v1",
        build_utm_compression_flow_template("utm_windows_v1"),
    )

    assert flow["agentic_task_id"] == "run_utm_compression_cycle"
    assert flow["blocks"][0]["vision"]["enabled"] is True
    assert flow["blocks"][0]["vision"]["blocking"] is False


def test_flow_rejects_unknown_workflow_agentic_task_id() -> None:
    flow = _flow()
    flow["agentic_task_id"] = "unknown_task"

    with pytest.raises(EquipmentSkillFlowError, match="unsupported workflow Agentic Task"):
        normalize_equipment_skill_flow("utm_windows_v1", flow)


def test_flow_rejects_noncanonical_utm_task_revision() -> None:
    flow = build_utm_compression_flow_template("utm_windows_v1")
    flow["blocks"][0], flow["blocks"][1] = flow["blocks"][1], flow["blocks"][0]

    with pytest.raises(EquipmentSkillFlowError, match="canonical block revision"):
        normalize_equipment_skill_flow("utm_windows_v1", flow)


def test_flow_store_round_trips_an_unbound_skill_slot(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    flow = _flow()
    flow["blocks"] = [flow["blocks"][0]]
    flow["blocks"][0]["label"] = "Unbound equipment block"
    flow["blocks"][0]["skill"] = {"skill_id": "", "skill_version": ""}
    flow["blocks"][0]["agentic"]["completed"] = "__complete__"
    flow["blocks"][0]["vision"]["detected"] = "__complete__"

    store.save("utm_windows_v1", flow)
    loaded = store.get("utm_windows_v1")

    assert loaded["blocks"][0]["skill"] == {"skill_id": "", "skill_version": ""}
    assert loaded["blocks"][0]["label"] == "Unbound equipment block"


def test_flow_store_rejects_a_partially_bound_skill_slot(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    flow = _flow()
    flow["blocks"][0]["skill"] = {"skill_id": "utm_prepare", "skill_version": ""}

    with pytest.raises(EquipmentSkillFlowError, match="both be set or both be empty"):
        store.save("utm_windows_v1", flow)


def test_legacy_skill_followed_by_vision_migrates_into_one_block(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    legacy = {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": "utm_windows_v1",
        "profile_id": "utm_windows_v1",
        "entry_node": "prepare",
        "nodes": [
            {
                "id": "prepare",
                "kind": "skill",
                "label": "Prepare UTM",
                "skill_id": "utm_prepare",
                "skill_version": "1.0.0",
                "routes": {"completed": "inspect", "failed": "__blocked__"},
            },
            {
                "id": "inspect",
                "kind": "vision_gate",
                "label": "Verify specimen",
                "condition": "equipment_specimen_detected",
                "routes": {
                    "detected": "__complete__",
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                    "bypass": "__complete__",
                },
            },
        ],
    }

    migrated = store.save("utm_windows_v1", legacy)["flow"]

    assert len(migrated["blocks"]) == 1
    assert migrated["blocks"][0]["id"] == "prepare"
    assert migrated["blocks"][0]["vision"]["enabled"] is True
    assert migrated["blocks"][0]["vision"]["task_id"] == "utm_pre_start"
    assert "condition" not in migrated["blocks"][0]["vision"]


def test_enabled_vision_requires_catalog_task_id(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    flow = _flow()
    flow["blocks"][0]["vision"]["task_id"] = "unknown_task"

    with pytest.raises(EquipmentSkillFlowError, match="unknown Equipment Vision task"):
        store.save("utm_windows_v1", flow)


def test_disabled_vision_may_remain_unbound(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    flow = _flow()
    flow["blocks"][0]["vision"] = {
        "enabled": False,
        "task_id": "",
        "detected": "next",
        "not_detected": "__blocked__",
        "timeout": "__blocked__",
        "error": "__blocked__",
    }

    loaded = store.save("utm_windows_v1", flow)["flow"]

    assert loaded["blocks"][0]["vision"]["task_id"] == ""


def test_legacy_condition_migrates_to_pre_start_with_note(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    legacy = _flow()
    legacy["blocks"][0]["vision"].pop("task_id")
    legacy["blocks"][0]["vision"]["condition"] = "equipment_specimen_detected"
    store.path.write_text(
        json.dumps({"schema": STORE_SCHEMA, "flows": {"utm_windows_v1": legacy}}),
        encoding="utf-8",
    )

    flow, notes = store.get_with_migration("utm_windows_v1")

    assert flow["blocks"][0]["vision"]["task_id"] == "utm_pre_start"
    assert "condition" not in flow["blocks"][0]["vision"]
    assert notes == ["prepare: migrated legacy Vision condition to utm_pre_start"]


def test_legacy_standalone_vision_is_rejected(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    legacy = {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": "utm_windows_v1",
        "profile_id": "utm_windows_v1",
        "entry_node": "inspect",
        "nodes": [
            {
                "id": "inspect",
                "kind": "vision_gate",
                "condition": "equipment_specimen_detected",
                "routes": {
                    "detected": "__complete__",
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                    "bypass": "__complete__",
                },
            }
        ],
    }

    with pytest.raises(EquipmentSkillFlowError, match="standalone Vision"):
        store.save("utm_windows_v1", legacy)


def test_flow_validation_rejects_duplicate_blocks_and_invalid_targets(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    flow = _flow()
    flow["blocks"][1]["id"] = "prepare"
    with pytest.raises(EquipmentSkillFlowError, match="duplicate block id"):
        store.save("utm_windows_v1", flow)

    flow = _flow()
    flow["blocks"][0]["agentic"]["failed"] = "unknown"
    with pytest.raises(EquipmentSkillFlowError, match="unsupported route target"):
        store.save("utm_windows_v1", flow)


def test_runtime_graph_exposes_composite_control_lanes(tmp_path: Path) -> None:
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    store.save("utm_windows_v1", _flow())

    graph = store.as_runtime_graph("utm_windows_v1")
    node_ids = {node["id"] for node in graph["nodes"]}

    assert graph["metadata"]["ide_tab_kind"] == "equipment_skill_flow"
    assert {"prepare.skill", "prepare.vision", "test.skill"}.issubset(node_ids)
    assert "test.vision" not in node_ids
    assert {node["metadata"]["control_level"] for node in graph["nodes"]} == {"high", "middle", "low"}
    prepare_skill = next(node for node in graph["nodes"] if node["id"] == "prepare.skill")
    prepare_vision = next(node for node in graph["nodes"] if node["id"] == "prepare.vision")
    assert prepare_skill["metadata"]["task"] == "Prepare UTM"
    assert prepare_vision["label"] == "Pre-UTM Fixture Check"
    assert prepare_vision["metadata"]["task_id"] == "utm_pre_start"
    assert prepare_vision["metadata"]["check_id"] == "utm_pre_start"
    assert prepare_vision["metadata"]["timeout_s"] == 5
    assert any(edge["source"] == "prepare.skill" and edge["target"] == "prepare.vision" for edge in graph["edges"])
    identities = [(edge["source"], edge["target"], edge["condition"]) for edge in graph["edges"]]
    assert identities.count(("prepare.vision", "test.skill", "observed")) == 1
    assert not any(
        source == "prepare.vision" and target == "__blocked__"
        for source, target, _condition in identities
    )
    assert ("prepare.vision", "test.skill", "next") not in identities
