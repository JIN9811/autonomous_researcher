from __future__ import annotations

import json

import pytest

from utils.test_mode_execution_profiles import (
    TestModeExecutionProfileConflictError as ProfileConflictError,
    TestModeExecutionProfileStore as ProfileStore,
    TestModeExecutionProfileValidationError as ProfileValidationError,
)


def _profile(
    *,
    specimen: str = "virtual",
    vision: str = "virtual",
    manipulation: str = "virtual",
    lab_equipment: str = "virtual",
    print_body: str = "execute",
    cooling_wait: str = "execute",
    auto_ejection: bool = True,
) -> dict:
    return {
        "agents": {
            "specimen": {"device_mode": specimen},
            "vision": {"device_mode": vision},
            "manipulation": {"device_mode": manipulation},
            "lab_equipment": {"device_mode": lab_equipment},
        },
        "printer_flow": {
            "print_body": print_body,
            "cooling_wait": cooling_wait,
            "auto_ejection": auto_ejection,
        },
        "handoff": {"strategy": "operator_teleop"},
    }


def test_missing_store_returns_safe_defaults_without_writing(tmp_path):
    path = tmp_path / "profiles.json"
    snapshot = ProfileStore(path).snapshot()

    assert snapshot["schema"] == "test_mode_execution_profiles.v1"
    assert snapshot["revision"] == 0
    assert snapshot["profiles"]["installed_printer"]["printer_flow"] == {
        "print_body": "skip",
        "cooling_wait": "skip",
        "auto_ejection": True,
    }
    assert snapshot["profiles"]["virtual_bridge"]["agents"]["specimen"] == {
        "device_mode": "virtual"
    }
    assert not path.exists()


def test_save_round_trip_increments_revision_and_uses_deterministic_hash(tmp_path):
    path = tmp_path / "profiles.json"
    store = ProfileStore(path)
    changed = _profile(manipulation="virtual", lab_equipment="real")

    saved = store.save_profile("installed_printer", changed, expected_revision=0)
    loaded = ProfileStore(path).snapshot()

    assert saved["revision"] == 1
    assert len(saved["sha256"]) == 64
    assert loaded == saved
    assert loaded["profiles"]["installed_printer"] == changed
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["sha256"] == saved["sha256"]


def test_save_rejects_stale_revision_without_overwriting(tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    first = store.save_profile("virtual_bridge", _profile(), expected_revision=0)

    with pytest.raises(ProfileConflictError):
        store.save_profile("virtual_bridge", _profile(vision="real"), expected_revision=0)

    assert store.snapshot() == first


@pytest.mark.parametrize(
    "profile",
    [
        _profile(print_body="execute", cooling_wait="skip"),
        _profile(specimen="real", print_body="skip", cooling_wait="skip", auto_ejection=False),
        _profile(vision="virtual", manipulation="real"),
    ],
)
def test_save_rejects_unsafe_printer_combinations(tmp_path, profile):
    store = ProfileStore(tmp_path / "profiles.json")

    with pytest.raises(ProfileValidationError):
        store.save_profile("installed_printer", profile, expected_revision=0)


def test_save_rejects_unknown_fields_and_modes(tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    profile = _profile()
    profile["agents"]["vision"]["device_mode"] = "disabled"
    profile["surprise"] = True

    with pytest.raises(ProfileValidationError):
        store.save_profile("virtual_bridge", profile, expected_revision=0)


def test_resolve_maps_agents_to_execution_policy_and_marks_hybrid_requirements(tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    store.save_profile(
        "installed_printer",
        _profile(specimen="real", vision="real", manipulation="virtual", lab_equipment="real", print_body="skip", cooling_wait="skip"),
        expected_revision=0,
    )

    resolved = store.resolve("installed_printer")

    assert resolved["schema"] == "resolved_test_mode_execution_profile.v1"
    assert resolved["execution_policy"] == {
        "printer": "execute",
        "vision": "execute",
        "manipulation": "preflight_only",
        "lab_equipment": "execute",
    }
    assert resolved["derived"]["operator_teleop_required"] is True
    assert resolved["derived"]["external_specimen_materialization_required"] is True


def test_reset_one_and_reset_all_use_revision_checks(tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    one = store.save_profile("virtual_bridge", _profile(vision="real"), expected_revision=0)
    reset_one = store.reset("virtual_bridge", expected_revision=one["revision"])
    assert reset_one["profiles"]["virtual_bridge"]["agents"]["vision"]["device_mode"] == "virtual"

    changed = store.save_profile(
        "physical_print",
        _profile(specimen="virtual", print_body="execute", cooling_wait="execute"),
        expected_revision=reset_one["revision"],
    )
    reset_all = store.reset(None, expected_revision=changed["revision"])
    assert reset_all["profiles"]["physical_print"]["agents"]["specimen"]["device_mode"] == "real"


def test_malformed_nonempty_file_falls_back_as_a_whole_with_warning(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text('{"schema":"wrong","profiles":{"virtual_bridge":{}}}', encoding="utf-8")

    snapshot = ProfileStore(path).snapshot()

    assert snapshot["revision"] == 0
    assert snapshot["profiles"]["physical_print"]["agents"]["lab_equipment"]["device_mode"] == "real"
    assert snapshot["warnings"][0]["code"] == "PROFILE_STORE_INVALID"
