"""
File purpose:
- Persist operator-controlled Prusa MK4S print/profile defaults for GUI and controller use.

Key classes/functions:
- DEFAULT_PRUSA_PRINT_PROFILE
- load_prusa_print_profile
- save_prusa_print_profile

Inputs/outputs:
- Input: JSON-compatible printer profile fields from the 3DP GUI
- Output: normalized profile dictionary stored under memory/prusa_print_profile.json

Dependencies:
- utils.paths.resolve_path

Modification guide:
- Safe places to edit: default profile values and validation ranges.
- Risky places to edit: field names consumed by app.controller and web/static/printer.js.
- Related files: app/main.py, app/controller.py, web/static/printer.js.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.paths import resolve_path


PRUSA_PRINT_PROFILE_PATH = resolve_path("memory/prusa_print_profile.json")

DEFAULT_PRUSA_PRINT_PROFILE: dict[str, Any] = {
    "material": "PLA",
    "printer_model": "Prusa MK4S",
    "printer_profile": "prusa_mk4s_pla_0p4_nozzle",
    "slicer_profile_hint": "0.2mm_quality",
    "nozzle_diameter_mm": 0.4,
    "layer_height_mm": 0.2,
    "first_layer_height_mm": 0.2,
    "slow_first_layer_enabled": True,
    "first_layer_speed_mm_s": 10.0,
    "bed_temperature_c": 60.0,
    "first_layer_bed_temperature_c": 60.0,
    "storage": "usb",
    "max_print_time_min": 120.0,
    "overwrite": True,
    "start_immediately_live": True,
    "allow_ejection": False,
    "skirt_enabled": False,
    "top_cap_enabled": False,
    "bottom_cap_enabled": True,
    "top_bottom_cap": True,
    "skin_thickness_mm": 0.8,
    "require_flat_compression_faces": False,
    "test_specimen_size_mm": [30.0, 30.0, 30.0],
    "test_unit_cell_size_mm": 10.0,
    "notes": "Validated Prusa MK4S PLA profile. Auto ejection uses gated bed-sweep append G-code when enabled.",
}

_STRING_LIMITS = {
    "material": 40,
    "printer_model": 80,
    "printer_profile": 120,
    "slicer_profile_hint": 120,
    "storage": 40,
    "notes": 1000,
}


def _clean_string(value: Any, default: str, *, max_len: int) -> str:
    text = str(value if value is not None else default).strip()
    if not text:
        text = default
    return text[:max_len]


def _clean_float(value: Any, default: float, *, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    if parsed < min_value or parsed > max_value:
        parsed = float(default)
    return parsed


def _clean_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _clean_vector3(value: Any, default: list[float], *, min_value: float, max_value: float) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        return list(default)
    cleaned: list[float] = []
    for idx, item in enumerate(value):
        cleaned.append(_clean_float(item, float(default[idx]), min_value=min_value, max_value=max_value))
    return cleaned


def normalize_prusa_print_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize GUI-supplied profile values and enforce safe field ranges."""
    source = raw if isinstance(raw, dict) else {}
    profile = dict(DEFAULT_PRUSA_PRINT_PROFILE)
    profile.update({key: value for key, value in source.items() if key in DEFAULT_PRUSA_PRINT_PROFILE})

    for key, max_len in _STRING_LIMITS.items():
        profile[key] = _clean_string(
            profile.get(key),
            str(DEFAULT_PRUSA_PRINT_PROFILE[key]),
            max_len=max_len,
        )

    profile["nozzle_diameter_mm"] = _clean_float(
        profile.get("nozzle_diameter_mm"),
        float(DEFAULT_PRUSA_PRINT_PROFILE["nozzle_diameter_mm"]),
        min_value=0.1,
        max_value=2.0,
    )
    profile["layer_height_mm"] = _clean_float(
        profile.get("layer_height_mm"),
        float(DEFAULT_PRUSA_PRINT_PROFILE["layer_height_mm"]),
        min_value=0.02,
        max_value=1.0,
    )
    profile["first_layer_height_mm"] = _clean_float(
        profile.get("first_layer_height_mm"),
        float(profile["layer_height_mm"]),
        min_value=0.02,
        max_value=1.0,
    )
    profile["first_layer_speed_mm_s"] = _clean_float(
        profile.get("first_layer_speed_mm_s"),
        float(DEFAULT_PRUSA_PRINT_PROFILE["first_layer_speed_mm_s"]),
        min_value=3.0,
        max_value=60.0,
    )
    profile["bed_temperature_c"] = _clean_float(
        profile.get("bed_temperature_c"),
        float(DEFAULT_PRUSA_PRINT_PROFILE["bed_temperature_c"]),
        min_value=0.0,
        max_value=120.0,
    )
    profile["first_layer_bed_temperature_c"] = _clean_float(
        profile.get("first_layer_bed_temperature_c"),
        float(profile["bed_temperature_c"]),
        min_value=0.0,
        max_value=120.0,
    )
    profile["max_print_time_min"] = _clean_float(
        profile.get("max_print_time_min"),
        float(DEFAULT_PRUSA_PRINT_PROFILE["max_print_time_min"]),
        min_value=1.0,
        max_value=10080.0,
    )
    profile["overwrite"] = _clean_bool(profile.get("overwrite"), bool(DEFAULT_PRUSA_PRINT_PROFILE["overwrite"]))
    profile["start_immediately_live"] = _clean_bool(
        profile.get("start_immediately_live"),
        bool(DEFAULT_PRUSA_PRINT_PROFILE["start_immediately_live"]),
    )
    profile["allow_ejection"] = _clean_bool(profile.get("allow_ejection"), bool(DEFAULT_PRUSA_PRINT_PROFILE["allow_ejection"]))
    profile["slow_first_layer_enabled"] = _clean_bool(
        profile.get("slow_first_layer_enabled"),
        bool(DEFAULT_PRUSA_PRINT_PROFILE["slow_first_layer_enabled"]),
    )
    profile["skirt_enabled"] = _clean_bool(profile.get("skirt_enabled"), bool(DEFAULT_PRUSA_PRINT_PROFILE["skirt_enabled"]))
    legacy_cap = _clean_bool(profile.get("top_bottom_cap"), bool(DEFAULT_PRUSA_PRINT_PROFILE["top_bottom_cap"]))
    explicit_top_cap = "top_cap_enabled" in source
    explicit_bottom_cap = "bottom_cap_enabled" in source
    explicit_legacy_cap = "top_bottom_cap" in source
    if explicit_top_cap or explicit_bottom_cap:
        profile["top_cap_enabled"] = _clean_bool(
            profile.get("top_cap_enabled"),
            bool(DEFAULT_PRUSA_PRINT_PROFILE["top_cap_enabled"]),
        )
        profile["bottom_cap_enabled"] = _clean_bool(
            profile.get("bottom_cap_enabled"),
            bool(DEFAULT_PRUSA_PRINT_PROFILE["bottom_cap_enabled"]),
        )
    elif explicit_legacy_cap:
        # Migrate old single-checkbox profiles to the new safer default:
        # bottom cap only. A top cap can sag on unsupported TPMS channels.
        profile["top_cap_enabled"] = False
        profile["bottom_cap_enabled"] = bool(legacy_cap)
    else:
        profile["top_cap_enabled"] = bool(DEFAULT_PRUSA_PRINT_PROFILE["top_cap_enabled"])
        profile["bottom_cap_enabled"] = bool(DEFAULT_PRUSA_PRINT_PROFILE["bottom_cap_enabled"])

    profile["top_bottom_cap"] = bool(profile["top_cap_enabled"] or profile["bottom_cap_enabled"])
    if profile["top_bottom_cap"]:
        profile["skin_thickness_mm"] = _clean_float(
            profile.get("skin_thickness_mm"),
            float(DEFAULT_PRUSA_PRINT_PROFILE["skin_thickness_mm"]),
            min_value=0.2,
            max_value=3.0,
        )
    else:
        profile["skin_thickness_mm"] = 0.0
    both_caps_enabled = bool(profile["top_cap_enabled"] and profile["bottom_cap_enabled"])
    profile["require_flat_compression_faces"] = (
        _clean_bool(profile.get("require_flat_compression_faces"), both_caps_enabled) and both_caps_enabled
        if profile["top_bottom_cap"]
        else False
    )
    profile["test_specimen_size_mm"] = _clean_vector3(
        profile.get("test_specimen_size_mm"),
        list(DEFAULT_PRUSA_PRINT_PROFILE["test_specimen_size_mm"]),
        min_value=1.0,
        max_value=250.0,
    )
    profile["test_unit_cell_size_mm"] = _clean_float(
        profile.get("test_unit_cell_size_mm"),
        float(DEFAULT_PRUSA_PRINT_PROFILE["test_unit_cell_size_mm"]),
        min_value=3.0,
        max_value=10.0,
    )
    return profile


def adapt_print_profile_for_provider(profile: dict[str, Any], provider: str) -> dict[str, Any]:
    """Return operator print defaults overlaid for the active printer provider."""
    selected_provider = str(provider or "").strip()
    adapted = dict(profile or {})
    if selected_provider != "bambulab_x2d":
        return adapted
    if str(adapted.get("printer_model", "")).lower().startswith("prusa"):
        adapted.update(
            {
                "printer_model": "Bambu Lab X2D",
                "printer_profile": "bambulab_x2d_pla_0p4_nozzle",
                "storage": "ftps",
                "start_immediately_live": False,
                "allow_ejection": False,
                "skirt_enabled": False,
                "notes": (
                    "Bambu Lab X2D provider overlay. MQTT/FTPS/HTTP artifact gates must pass before transfer; "
                    "print start and autoejection require explicit Guardian-approved enablement."
                ),
            }
        )
    return adapted


def load_prusa_print_profile(path: str | Path | None = None) -> dict[str, Any]:
    """Load the saved print profile or return normalized defaults."""
    profile_path = Path(path) if path is not None else PRUSA_PRINT_PROFILE_PATH
    if not profile_path.exists():
        return normalize_prusa_print_profile({})
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return normalize_prusa_print_profile({})
    return normalize_prusa_print_profile(raw if isinstance(raw, dict) else {})


def save_prusa_print_profile(payload: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    """Persist a normalized profile atomically enough for local GUI use."""
    profile_path = Path(path) if path is not None else PRUSA_PRINT_PROFILE_PATH
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile = normalize_prusa_print_profile(payload)
    tmp_path = profile_path.with_suffix(profile_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(profile_path)
    try:
        profile_path.chmod(0o600)
    except OSError:
        pass
    return profile
