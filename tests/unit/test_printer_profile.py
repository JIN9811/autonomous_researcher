"""
Unit tests for operator-controlled Prusa MK4S print profile persistence.
"""

from utils.printer_profile import load_prusa_print_profile, save_prusa_print_profile


def test_printer_profile_normalizes_and_persists(tmp_path) -> None:
    path = tmp_path / "prusa_print_profile.json"

    profile = save_prusa_print_profile(
        {
            "material": "PETG",
            "printer_profile": "petg_quality_0p4",
            "slicer_profile_hint": "0.15mm_quality",
            "nozzle_diameter_mm": 0.6,
            "layer_height_mm": 0.15,
            "first_layer_height_mm": 0.15,
            "first_layer_speed_mm_s": 8,
            "bed_temperature_c": 65,
            "first_layer_bed_temperature_c": 70,
            "storage": "usb",
            "max_print_time_min": 180,
            "overwrite": False,
            "start_immediately_live": False,
            "allow_ejection": True,
            "slow_first_layer_enabled": True,
            "skirt_enabled": False,
            "top_cap_enabled": True,
            "bottom_cap_enabled": True,
            "top_bottom_cap": True,
            "skin_thickness_mm": 0.9,
            "require_flat_compression_faces": True,
            "test_specimen_size_mm": [24, 25, 26],
            "test_unit_cell_size_mm": 6.5,
        },
        path=path,
    )

    assert profile["material"] == "PETG"
    assert profile["printer_model"] == "Prusa MK4S"
    assert profile["nozzle_diameter_mm"] == 0.6
    assert profile["layer_height_mm"] == 0.15
    assert profile["first_layer_height_mm"] == 0.15
    assert profile["first_layer_speed_mm_s"] == 8.0
    assert profile["bed_temperature_c"] == 65.0
    assert profile["first_layer_bed_temperature_c"] == 70.0
    assert profile["overwrite"] is False
    assert profile["start_immediately_live"] is False
    assert profile["allow_ejection"] is True
    assert profile["slow_first_layer_enabled"] is True
    assert profile["skirt_enabled"] is False
    assert profile["top_cap_enabled"] is True
    assert profile["bottom_cap_enabled"] is True
    assert profile["top_bottom_cap"] is True
    assert profile["skin_thickness_mm"] == 0.9
    assert profile["require_flat_compression_faces"] is True
    assert profile["test_specimen_size_mm"] == [24.0, 25.0, 26.0]
    assert profile["test_unit_cell_size_mm"] == 6.5
    assert load_prusa_print_profile(path)["printer_profile"] == "petg_quality_0p4"


def test_printer_profile_rejects_out_of_range_values(tmp_path) -> None:
    path = tmp_path / "prusa_print_profile.json"

    profile = save_prusa_print_profile(
        {
            "nozzle_diameter_mm": 99,
            "layer_height_mm": 99,
            "first_layer_height_mm": 99,
            "first_layer_speed_mm_s": 999,
            "bed_temperature_c": 999,
            "first_layer_bed_temperature_c": 999,
            "max_print_time_min": -1,
            "test_specimen_size_mm": [0, 999, "bad"],
            "test_unit_cell_size_mm": 99,
        },
        path=path,
    )

    assert profile["nozzle_diameter_mm"] == 0.4
    assert profile["layer_height_mm"] == 0.2
    assert profile["first_layer_height_mm"] == 0.2
    assert profile["first_layer_speed_mm_s"] == 10.0
    assert profile["bed_temperature_c"] == 60.0
    assert profile["first_layer_bed_temperature_c"] == 60.0
    assert profile["max_print_time_min"] == 120.0
    assert profile["test_specimen_size_mm"] == [30.0, 30.0, 30.0]
    assert profile["test_unit_cell_size_mm"] == 10.0
    assert profile["top_cap_enabled"] is False
    assert profile["bottom_cap_enabled"] is True
    assert profile["top_bottom_cap"] is True
    assert profile["skin_thickness_mm"] == 0.8
    assert profile["require_flat_compression_faces"] is False
    assert profile["bed_temperature_c"] == 60.0
    assert profile["first_layer_bed_temperature_c"] == 60.0


def test_printer_profile_defaults_bottom_cap_on(tmp_path) -> None:
    path = tmp_path / "missing_profile.json"

    profile = load_prusa_print_profile(path)

    assert profile["top_cap_enabled"] is False
    assert profile["bottom_cap_enabled"] is True
    assert profile["top_bottom_cap"] is True
    assert profile["skin_thickness_mm"] == 0.8
    assert profile["require_flat_compression_faces"] is False


def test_printer_profile_disables_flat_skin_when_cap_is_off(tmp_path) -> None:
    path = tmp_path / "prusa_print_profile.json"

    profile = save_prusa_print_profile(
        {
            "top_bottom_cap": False,
            "skin_thickness_mm": 1.2,
            "require_flat_compression_faces": False,
        },
        path=path,
    )

    assert profile["top_cap_enabled"] is False
    assert profile["bottom_cap_enabled"] is False
    assert profile["top_bottom_cap"] is False
    assert profile["skin_thickness_mm"] == 0.0
    assert profile["require_flat_compression_faces"] is False
