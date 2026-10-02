from __future__ import annotations

import pytest

from app.bootstrap import load_runtime
from utils.test_mode_execution_profiles import TestModeExecutionProfileStore as ProfileStore


def _profile(*, specimen: str, vision: str, manipulation: str, lab_equipment: str) -> dict:
    return {
        "agents": {
            "specimen": {"device_mode": specimen},
            "vision": {"device_mode": vision},
            "manipulation": {"device_mode": manipulation},
            "lab_equipment": {"device_mode": lab_equipment},
        },
        "printer_flow": {
            "print_body": "execute",
            "cooling_wait": "execute",
            "auto_ejection": True,
        },
        "handoff": {"strategy": "operator_teleop"},
    }


@pytest.mark.parametrize(
    ("profile_id", "expected_policy", "operator_teleop", "external_materialization"),
    [
        (
            "virtual_bridge",
            {"printer": "preflight_only", "vision": "preflight_only", "manipulation": "preflight_only", "lab_equipment": "preflight_only"},
            False,
            False,
        ),
        (
            "installed_printer",
            {"printer": "execute", "vision": "execute", "manipulation": "execute", "lab_equipment": "execute"},
            False,
            True,
        ),
        (
            "physical_print",
            {"printer": "execute", "vision": "execute", "manipulation": "execute", "lab_equipment": "execute"},
            False,
            False,
        ),
    ],
)
def test_builtin_profile_matrix_resolves_each_physical_boundary_without_hardware(
    tmp_path, profile_id, expected_policy, operator_teleop, external_materialization
):
    resolved = ProfileStore(tmp_path / "profiles.json").resolve(profile_id)

    assert resolved["execution_policy"] == expected_policy
    assert resolved["derived"]["operator_teleop_required"] is operator_teleop
    assert resolved["derived"]["external_specimen_materialization_required"] is external_materialization


@pytest.mark.parametrize(
    ("manipulation", "lab_equipment", "teleop_required"),
    [("virtual", "real", True), ("real", "virtual", False)],
)
def test_hybrid_matrix_is_snapshotted_by_controller_without_contacting_devices(
    tmp_path, manipulation, lab_equipment, teleop_required
):
    path = tmp_path / "profiles.json"
    store = ProfileStore(path)
    store.save_profile(
        "physical_print",
        _profile(
            specimen="real",
            vision="real",
            manipulation=manipulation,
            lab_equipment=lab_equipment,
        ),
        expected_revision=0,
    )
    controller = load_runtime()
    controller._test_mode_execution_profiles_path = path

    resolved = controller._apply_specimen_printer_choice_to_spec(
        {"candidate_id": "matrix-candidate", "specimen_id": "matrix-specimen"},
        "physical_print",
    )

    assert resolved["execution_policy"]["manipulation"] == (
        "execute" if manipulation == "real" else "preflight_only"
    )
    assert resolved["execution_policy"]["lab_equipment"] == (
        "execute" if lab_equipment == "real" else "preflight_only"
    )
    assert resolved["test_mode_profile"]["derived"]["operator_teleop_required"] is teleop_required
    assert resolved["test_mode_profile"]["source_revision"] == 1
    assert len(resolved["test_mode_profile"]["source_sha256"]) == 64
