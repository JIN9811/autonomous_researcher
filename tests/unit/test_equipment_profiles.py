from __future__ import annotations

from utils.equipment_profiles import EquipmentProfile, EquipmentProfileRegistry, build_execution_contract


def test_profile_contract_owns_bridge_payload_vision_and_completion_policy() -> None:
    profile = EquipmentProfile(
        profile_id="generic_desktop_v1",
        label="Generic desktop equipment",
        bridge_provider="windows_pyautogui",
        default_program_id="program1",
        allowed_program_ids=("program1",),
        required_locators=(),
        required_evidence=("request_log",),
        mode_payloads={
            "test": {"simulate_equipment": True},
            "live": {"simulate_equipment": False},
        },
        vision_link={"enabled": False, "required_modes": []},
        completion_policy={"interpreter": "program_result_v1"},
    )

    contract = build_execution_contract(profile, runtime_mode="test")

    assert contract.provider == "windows_pyautogui"
    assert contract.bridge_payload == {"simulate_equipment": True}
    assert contract.vision_link == {"enabled": False, "required_modes": []}
    assert contract.completion_policy == {"interpreter": "program_result_v1"}
    assert "simulate_utm_protocol" not in contract.to_safe_dict()["bridge_payload"]


def test_default_registry_resolves_program_without_agent_prefix_logic() -> None:
    registry = EquipmentProfileRegistry.default()

    assert registry.resolve(program_id="program1").profile_id == "windows_desktop_v1"
    assert registry.resolve(program_id="utm_compression_start_v1").profile_id == "utm_windows_v1"
    assert registry.resolve(profile_id="utm_windows_v1", program_id="program1").profile_id == "utm_windows_v1"


def test_utm_compatibility_flag_is_declared_only_by_profile_payload() -> None:
    profile = EquipmentProfileRegistry.default().get("utm_windows_v1")

    test_contract = build_execution_contract(profile, runtime_mode="test")
    live_contract = build_execution_contract(profile, runtime_mode="live")

    assert test_contract.bridge_payload["simulate_utm_protocol"] is True
    assert live_contract.bridge_payload["simulate_utm_protocol"] is False
    assert test_contract.simulate_utm_protocol is True
    assert live_contract.simulate_utm_protocol is False
