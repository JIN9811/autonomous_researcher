from __future__ import annotations

from pathlib import Path

from utils.equipment_skill_authoring_jobs import EquipmentSkillAuthoringJobManager


def test_skill_authoring_job_persists_real_stage_progress(tmp_path: Path) -> None:
    manager = EquipmentSkillAuthoringJobManager(tmp_path)
    created = manager.create(
        recording_id="rec-equipment-demo",
        skill_id="equipment_demonstration",
        version="1.0.0",
        target_profile="utm_windows_v1",
        bridge_id="nextpc",
    )

    updated = manager.update(
        created["job_id"],
        stage="BUILDING_SKILL",
        progress=60,
        status_text="Building Linux Skill draft",
    )
    restored = EquipmentSkillAuthoringJobManager(tmp_path).get(created["job_id"])

    assert updated["status"] == "RUNNING"
    assert restored["stage"] == "BUILDING_SKILL"
    assert restored["progress"] == 60
    assert restored["status_text"] == "Building Linux Skill draft"


def test_skill_authoring_stop_request_is_persistent_and_terminal_stop_preserves_progress(tmp_path: Path) -> None:
    manager = EquipmentSkillAuthoringJobManager(tmp_path)
    created = manager.create(
        recording_id="rec-equipment-demo",
        skill_id="equipment_demonstration",
        version="1.0.0",
        target_profile="utm_windows_v1",
        bridge_id="nextpc",
    )
    manager.update(
        created["job_id"],
        stage="TRANSFERRING",
        progress=25,
        status_text="Transferring recording from worker",
    )

    stopping = manager.request_stop(created["job_id"])
    stopped = manager.mark_stopped(created["job_id"], "Stopped at a safe stage boundary")
    restored = EquipmentSkillAuthoringJobManager(tmp_path).get(created["job_id"])

    assert stopping["stop_requested"] is True
    assert stopping["status"] == "STOPPING"
    assert stopped["status"] == "STOPPED"
    assert restored["progress"] == 25
    assert restored["status_text"] == "Stopped at a safe stage boundary"


def test_skill_deployment_job_persists_operation_and_identity(tmp_path: Path) -> None:
    manager = EquipmentSkillAuthoringJobManager(tmp_path)

    created = manager.create_deployment(
        skill_id="equipment_demonstration",
        version="1.0.0",
        bridge_id="nextpc",
    )
    restored = EquipmentSkillAuthoringJobManager(tmp_path).get(created["job_id"])

    assert restored["operation"] == "deployment"
    assert restored["stage"] == "PREFLIGHT"
    assert restored["progress"] == 5
    assert restored["skill_id"] == "equipment_demonstration"
    assert restored["bridge_id"] == "nextpc"
