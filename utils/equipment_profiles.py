"""Shared equipment profile contracts for Agent, Workspace, and bridges."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
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
    mode_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    vision_link: dict[str, Any] = field(default_factory=lambda: {"enabled": False, "required_modes": []})
    completion_policy: dict[str, Any] = field(default_factory=lambda: {"interpreter": "program_result_v1"})
    manual_knowledge_scope: str = ""

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "bridge_provider": self.bridge_provider,
            "default_program_id": self.default_program_id,
            "allowed_program_ids": list(self.allowed_program_ids),
            "required_locators": list(self.required_locators),
            "required_evidence": list(self.required_evidence),
            "mode_payloads": deepcopy(self.mode_payloads),
            "vision_link": deepcopy(self.vision_link),
            "completion_policy": deepcopy(self.completion_policy),
            "manual_knowledge_scope": self.manual_knowledge_scope,
        }


@dataclass(frozen=True)
class EquipmentExecutionContract:
    """Mode-specific, token-free execution input for a registered profile."""

    profile_id: str
    program_id: str
    provider: str
    runtime_mode: str
    bridge_payload: dict[str, Any]
    required_evidence: tuple[str, ...]
    vision_link: dict[str, Any]
    completion_policy: dict[str, Any]

    @property
    def simulate_utm_protocol(self) -> bool:
        """Compatibility view; the UTM flag is owned by profile data."""
        return bool(self.bridge_payload.get("simulate_utm_protocol"))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "program_id": self.program_id,
            "provider": self.provider,
            "runtime_mode": self.runtime_mode,
            "bridge_payload": deepcopy(self.bridge_payload),
            "simulate_utm_protocol": self.simulate_utm_protocol,
            "required_evidence": list(self.required_evidence),
            "vision_link": deepcopy(self.vision_link),
            "completion_policy": deepcopy(self.completion_policy),
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
                    mode_payloads={
                        "test": {"simulate_utm_protocol": True},
                        "live": {"simulate_utm_protocol": False},
                    },
                    vision_link={
                        "enabled": True,
                        "required_modes": ["live"],
                        "request_schema": "equipment_vision_check_request.v1",
                        "result_schema": "equipment_vision_check_result.v1",
                        "freshness_required": True,
                    },
                    completion_policy={"interpreter": "utm_proof_v1", "requires_analysis_handoff": True},
                    manual_knowledge_scope="utm",
                ),
                EquipmentProfile(
                    profile_id="windows_desktop_v1",
                    label="Windows Desktop Macro",
                    bridge_provider="windows_pyautogui",
                    default_program_id="program1",
                    allowed_program_ids=("program1",),
                    required_locators=(),
                    required_evidence=("request_log",),
                    mode_payloads={"test": {}, "live": {}},
                    vision_link={"enabled": False, "required_modes": []},
                    completion_policy={"interpreter": "program_result_v1", "requires_analysis_handoff": False},
                    manual_knowledge_scope="generic_desktop_equipment",
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

    def resolve(self, *, profile_id: str = "", program_id: str = "") -> EquipmentProfile:
        """Resolve an explicit profile or infer one from registered program ownership."""
        clean_profile = str(profile_id or "").strip()
        if clean_profile:
            return self.get(clean_profile)
        clean_program = str(program_id or "").strip()
        if clean_program:
            matches = [profile for profile in self._profiles if clean_program in profile.allowed_program_ids]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ValueError(f"Program {clean_program} is owned by multiple equipment profiles")
        return self.get(DEFAULT_UTM_PROFILE_ID)


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
        provider=profile.bridge_provider,
        runtime_mode=mode,
        bridge_payload=deepcopy(profile.mode_payloads.get(mode, {})),
        required_evidence=profile.required_evidence,
        vision_link=deepcopy(profile.vision_link),
        completion_policy=deepcopy(profile.completion_policy),
    )
