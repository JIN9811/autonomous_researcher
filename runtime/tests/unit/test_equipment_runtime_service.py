from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context

import pytest

from utils.equipment_runtime_service import EquipmentRuntimeContractError, EquipmentRuntimeService


def _begin(service: EquipmentRuntimeService) -> dict:
    return service.begin(
        sequence_id="run-1-equipment-1",
        run_id="run-1",
        experiment_id="exp-1",
        specimen_id="specimen-1",
        profile_id="utm_windows_v1",
        mode="test",
        worker={"worker_id": "windows-main", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "utm_compression_start_v1"},
    )


def _begin_in_process(root: str) -> str:
    return str(_begin(EquipmentRuntimeService(root))["execution_id"])


def test_equipment_runtime_persists_one_canonical_execution_snapshot(tmp_path: Path) -> None:
    service = EquipmentRuntimeService(tmp_path / "equipment_runtime")

    execution = _begin(service)

    assert execution["schema"] == "atr.equipment_execution.v1"
    assert execution["lifecycle"] == "RESOLVING"
    assert execution["identity"] == {
        "run_id": "run-1",
        "experiment_id": "exp-1",
        "specimen_id": "specimen-1",
        "sequence_id": "run-1-equipment-1",
    }
    assert execution["profile_id"] == "utm_windows_v1"
    assert service.get(execution["execution_id"]) == execution


def test_equipment_runtime_is_idempotent_for_same_sequence(tmp_path: Path) -> None:
    service = EquipmentRuntimeService(tmp_path / "equipment_runtime")

    first = _begin(service)
    second = _begin(service)

    assert second["execution_id"] == first["execution_id"]
    assert second["idempotent"] is True


def test_equipment_runtime_identity_includes_selected_worker(tmp_path: Path) -> None:
    service = EquipmentRuntimeService(tmp_path)
    first = _begin(service)
    second = service.begin(
        sequence_id="run-1-equipment-1",
        run_id="run-1",
        experiment_id="exp-1",
        specimen_id="specimen-1",
        profile_id="utm_windows_v1",
        mode="test",
        worker={"worker_id": "worker-b", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "utm_compression_start_v1"},
    )

    assert second["execution_id"] != first["execution_id"]


def test_equipment_runtime_blocked_attempt_can_start_a_new_retry_execution(tmp_path: Path) -> None:
    service = EquipmentRuntimeService(tmp_path)
    first = _begin(service)
    blocked = service.transition(first["execution_id"], "BLOCKED", status="blocked")

    retried = _begin(service)

    assert blocked["lifecycle"] == "BLOCKED"
    assert retried["execution_id"] != first["execution_id"]
    assert retried["lifecycle"] == "RESOLVING"


def test_equipment_runtime_latest_can_be_scoped_to_active_run(tmp_path: Path) -> None:
    service = EquipmentRuntimeService(tmp_path / "equipment_runtime")
    run_one = _begin(service)
    run_two = service.begin(
        sequence_id="run-2-equipment-1",
        run_id="run-2",
        experiment_id="exp-2",
        specimen_id="specimen-2",
        profile_id="utm_windows_v1",
        mode="test",
        worker={"worker_id": "windows-main", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "utm_compression_start_v1"},
    )

    assert service.latest(run_id="run-1")["execution_id"] == run_one["execution_id"]
    assert service.latest(run_id="run-2")["execution_id"] == run_two["execution_id"]
    assert service.latest(run_id="missing-run") is None


def test_equipment_runtime_enforces_lifecycle_and_projects_shared_status(tmp_path: Path) -> None:
    service = EquipmentRuntimeService(tmp_path / "equipment_runtime")
    execution = _begin(service)

    service.transition(execution["execution_id"], "PREFLIGHT", detail="bridge ready")
    service.transition(execution["execution_id"], "EXECUTING", detail="worker started")
    service.transition(
        execution["execution_id"],
        "VERIFYING",
        evidence=[{"kind": "screen_png", "artifact_id": "screen-complete"}],
    )
    completed = service.transition(
        execution["execution_id"],
        "COMPLETED",
        completion={"ok": True, "status": "verified_complete"},
        handoff={"status": "ready_for_analysis"},
    )
    projection = service.project(completed)

    assert projection == {
        "schema": "atr.equipment_execution_projection.v1",
        "execution_id": execution["execution_id"],
        "lifecycle": "COMPLETED",
        "status": "verified_complete",
        "profile_id": "utm_windows_v1",
        "mode": "test",
        "worker": {"worker_id": "windows-main", "kind": "windows_pyautogui"},
        "execution_ref": {"type": "program", "program_id": "utm_compression_start_v1"},
        "evidence_count": 1,
        "ready_for_analysis": True,
        "failure_code": "",
        "updated_at": completed["updated_at"],
    }


def test_equipment_runtime_rejects_invalid_transition(tmp_path: Path) -> None:
    service = EquipmentRuntimeService(tmp_path / "equipment_runtime")
    execution = _begin(service)

    with pytest.raises(EquipmentRuntimeContractError, match="invalid lifecycle transition"):
        service.transition(execution["execution_id"], "COMPLETED")


def test_equipment_runtime_effect_unknown_is_terminal_after_actuation_timeout(tmp_path: Path) -> None:
    service = EquipmentRuntimeService(tmp_path / "equipment_runtime")
    execution = _begin(service)
    service.transition(execution["execution_id"], "PREFLIGHT")
    service.transition(execution["execution_id"], "EXECUTING")

    uncertain = service.transition(
        execution["execution_id"],
        "EFFECT_UNKNOWN",
        status="effect_unknown",
        failure={"failure_code": "PYAUTOGUI_EFFECT_UNKNOWN"},
    )

    assert uncertain["lifecycle"] == "EFFECT_UNKNOWN"
    assert service.project(uncertain)["failure_code"] == "PYAUTOGUI_EFFECT_UNKNOWN"
    with pytest.raises(EquipmentRuntimeContractError, match="invalid lifecycle transition"):
        service.transition(execution["execution_id"], "EXECUTING")


def test_equipment_runtime_supports_profile_specific_lifecycle_contract(tmp_path: Path) -> None:
    service = EquipmentRuntimeService(tmp_path / "equipment_runtime")
    execution = service.begin(
        sequence_id="run-custom-equipment-1",
        run_id="run-custom",
        experiment_id="exp-custom",
        specimen_id="specimen-custom",
        profile_id="custom_equipment_v1",
        mode="test",
        worker={"worker_id": "custom-main", "kind": "windows_pyautogui"},
        execution_ref={"type": "program", "program_id": "custom_program_v1"},
        lifecycle_contract={
            "RESOLVING": ["CALIBRATING", "BLOCKED"],
            "CALIBRATING": ["RUNNING", "BLOCKED"],
            "RUNNING": ["QUALITY_CHECK", "EFFECT_UNKNOWN", "BLOCKED"],
            "QUALITY_CHECK": ["COMPLETED", "BLOCKED"],
            "COMPLETED": ["COMPLETED"],
            "BLOCKED": ["BLOCKED"],
            "EFFECT_UNKNOWN": ["EFFECT_UNKNOWN"],
        },
    )

    service.transition(execution["execution_id"], "CALIBRATING")
    service.transition(execution["execution_id"], "RUNNING")
    service.transition(execution["execution_id"], "QUALITY_CHECK")
    completed = service.transition(execution["execution_id"], "COMPLETED")

    assert completed["lifecycle"] == "COMPLETED"
    assert "CALIBRATING" in completed["lifecycle_contract"]


def test_equipment_runtime_serializes_multiple_service_instances_for_same_root(tmp_path: Path) -> None:
    root = tmp_path / "equipment_runtime"
    services = [EquipmentRuntimeService(root) for _ in range(8)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        executions = list(pool.map(_begin, services))

    assert len({item["execution_id"] for item in executions}) == 1
    assert len(services[0].list()) == 1


def test_equipment_runtime_serializes_multiple_processes_for_same_root(tmp_path: Path) -> None:
    root = str(tmp_path / "equipment_runtime")
    context = get_context("spawn")

    with context.Pool(processes=4) as pool:
        execution_ids = pool.map(_begin_in_process, [root] * 8)

    service = EquipmentRuntimeService(root)
    assert len(set(execution_ids)) == 1
    assert len(service.list()) == 1


@pytest.mark.parametrize(
    "execution_id",
    ["../escape", "equipment-valid/../../escape", "equipment-valid/state.json"],
)
def test_equipment_runtime_rejects_path_like_execution_ids(tmp_path: Path, execution_id: str) -> None:
    service = EquipmentRuntimeService(tmp_path / "equipment_runtime")

    with pytest.raises(EquipmentRuntimeContractError, match="invalid execution_id"):
        service.get(execution_id)
