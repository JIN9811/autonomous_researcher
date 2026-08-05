"""Shared equipment profile contracts for Agent, Workspace, and bridges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_UTM_PROFILE_ID = "utm_windows_v1"


@dataclass(frozen=True)
class EquipmentProfile:
    """A registered equipment type with bounded bridge behavior."""

    profile_id: str
    label: str
    bridge_provider: str
    default_program_id: str
    allowed_program_ids: tuple[str, ...]
    required_locators: tuple[str, ...]
    required_evidence: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "bridge_provider": self.bridge_provider,
            "default_program_id": self.default_program_id,
            "allowed_program_ids": list(self.allowed_program_ids),
            "required_locators": list(self.required_locators),
            "required_evidence": list(self.required_evidence),
        }


@dataclass(frozen=True)
class EquipmentExecutionContract:
    """Mode-specific, token-free execution input for a registered profile."""

    profile_id: str
    program_id: str
    simulate_utm_protocol: bool
    required_evidence: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "program_id": self.program_id,
            "simulate_utm_protocol": self.simulate_utm_protocol,
            "required_evidence": list(self.required_evidence),
        }


class EquipmentProfileRegistry:
    """Immutable registry with an explicit extension boundary for equipment types."""

    def __init__(self, profiles: tuple[EquipmentProfile, ...]) -> None:
        self._profiles = profiles
        self._by_id = {profile.profile_id: profile for profile in profiles}

    @classmethod
    def default(cls) -> "EquipmentProfileRegistry":
        return cls(
            (
                EquipmentProfile(
                    profile_id=DEFAULT_UTM_PROFILE_ID,
                    label="UTM",
                    bridge_provider="windows_pyautogui",
                    default_program_id="utm_compression_start_v1",
                    allowed_program_ids=(
                        "utm_compression_start_v1",
                        "utm_export_csv_v1",
                        "utm_manual_save_csv_v1",
                        "utm_stop_or_abort_v1",
                    ),
                    required_locators=("ready_state", "start_button", "running_state", "complete_state"),
                    required_evidence=("screenshot", "request_log", "csv"),
                ),
            )
        )

    def list(self) -> tuple[EquipmentProfile, ...]:
        return self._profiles

    def get(self, profile_id: str) -> EquipmentProfile:
        try:
            return self._by_id[profile_id]
        except KeyError as exc:
            raise ValueError(f"Unknown equipment profile: {profile_id}") from exc


def build_execution_contract(
    profile: EquipmentProfile,
    *,
    runtime_mode: str,
    bridge_config: dict[str, Any] | None = None,
    program_id: str = "",
) -> EquipmentExecutionContract:
    """Return a bounded execution contract without leaking bridge configuration."""

    del bridge_config  # Bridge credentials remain owned by the bridge implementation.
    mode = str(runtime_mode or "").strip().lower()
    if mode not in {"test", "live"}:
        raise ValueError(f"Unsupported equipment runtime mode: {runtime_mode}")
    selected_program = str(program_id or profile.default_program_id).strip()
    if selected_program not in profile.allowed_program_ids:
        raise ValueError(f"Program {selected_program} is not registered for profile {profile.profile_id}")
    return EquipmentExecutionContract(
        profile_id=profile.profile_id,
        program_id=selected_program,
        simulate_utm_protocol=(mode == "test"),
        required_evidence=profile.required_evidence,
    )
