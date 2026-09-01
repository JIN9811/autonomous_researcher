from __future__ import annotations

import pytest

from utils.equipment_vision_tasks import (
    EQUIPMENT_VISION_TASK_IDS,
    build_equipment_vision_check,
    get_equipment_vision_task,
    list_equipment_vision_tasks,
)


def test_catalog_exposes_existing_utm_tasks_once() -> None:
    tasks = list_equipment_vision_tasks()

    assert [item["task_id"] for item in tasks] == [
        "utm_pre_start",
        "utm_motion_confirm",
        "utm_test_complete",
    ]
    assert EQUIPMENT_VISION_TASK_IDS == frozenset(item["task_id"] for item in tasks)
    assert get_equipment_vision_task("utm_motion_confirm")["timeout_s"] == 10


def test_catalog_returns_defensive_copies() -> None:
    tasks = list_equipment_vision_tasks()
    tasks[0]["expected"]["specimen_on_utm_fixture"] = False

    assert get_equipment_vision_task("utm_pre_start")["expected"]["specimen_on_utm_fixture"] is True


def test_unknown_task_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown Equipment Vision task"):
        get_equipment_vision_task("missing")


def test_build_check_preserves_runtime_identity_and_selected_task_only() -> None:
    check = build_equipment_vision_check(
        "utm_pre_start",
        run_id="run-7",
        loop_id=3,
        specimen_id="specimen-4",
    )

    assert check["task_id"] == "utm_pre_start"
    assert check["check_id"] == "utm_pre_start"
    assert check["run_id"] == "run-7"
    assert check["loop_id"] == 3
    assert check["specimen_id"] == "specimen-4"
    assert check["producer_agent"] == "equipment_agent"
    assert check["consumer_agent"] == "vision_agent"
    assert check["expected"]["specimen_on_utm_fixture"] is True
