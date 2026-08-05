"""Tests for common equipment profile contracts."""

from __future__ import annotations

from utils.equipment_profiles import (
    DEFAULT_UTM_PROFILE_ID,
    EquipmentProfileRegistry,
    build_execution_contract,
)


def test_default_registry_exposes_utm_as_first_profile() -> None:
    profile = EquipmentProfileRegistry.default().get(DEFAULT_UTM_PROFILE_ID)

    assert profile.label == "UTM"
    assert profile.bridge_provider == "windows_pyautogui"
    assert profile.allowed_program_ids == (
        "utm_compression_start_v1",
        "utm_export_csv_v1",
        "utm_manual_save_csv_v1",
        "utm_stop_or_abort_v1",
    )


def test_test_contract_uses_same_utm_program_with_simulation_enabled() -> None:
    profile = EquipmentProfileRegistry.default().get(DEFAULT_UTM_PROFILE_ID)

    contract = build_execution_contract(
        profile,
        runtime_mode="test",
        bridge_config={"selected_candidate": "utm-pc", "token": "secret"},
    )

    assert contract.program_id == "utm_compression_start_v1"
    assert contract.simulate_utm_protocol is True
    assert "secret" not in str(contract.to_safe_dict())


def test_live_contract_disables_simulation_for_the_same_profile() -> None:
    profile = EquipmentProfileRegistry.default().get(DEFAULT_UTM_PROFILE_ID)

    contract = build_execution_contract(profile, runtime_mode="live", bridge_config={})

    assert contract.program_id == "utm_compression_start_v1"
    assert contract.simulate_utm_protocol is False
