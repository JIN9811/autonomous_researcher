"""Behavior tests for selecting historical UTM evidence for CAE calibration."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _write_curve(path: Path, rows: list[tuple[float, float, float]]) -> None:
    path.write_text(
        "time_s,displacement_mm,force_N\n"
        + "\n".join(f"{time},{displacement},{force}" for time, displacement, force in rows)
        + "\n",
        encoding="utf-8",
    )


def test_reference_calibration_accepts_exact_metric_and_deduplicates_content(tmp_path: Path) -> None:
    module = importlib.import_module("utils.utm_reference_calibration")
    valid = tmp_path / "valid.csv"
    duplicate = tmp_path / "duplicate.csv"
    flat = tmp_path / "flat.csv"
    partial = tmp_path / "partial.csv"
    valid_rows = [
        (0.0, 0.0, 0.0),
        (1.0, 7.5, 900.0),
        (2.0, 15.0, 1800.0),
    ]
    _write_curve(valid, valid_rows)
    duplicate.write_bytes(valid.read_bytes())
    _write_curve(flat, [(0.0, 0.0, 0.0), (1.0, 15.0, 0.0)])
    _write_curve(partial, [(0.0, 0.0, 0.0), (1.0, 10.0, 1200.0)])

    result = module.build_reference_calibration(
        [valid, duplicate, flat, partial],
        target_strain=0.5,
        specimen_size_mm=[30.0, 30.0, 30.0],
    )

    assert result["schema"] == "utm_reference_calibration.v1"
    assert result["status"] == "ready"
    assert result["accepted_count"] == 1
    assert result["metric_name"] == "energy_density_50pct_MJ_per_m3"
    assert result["reference_value"] == pytest.approx(0.5)
    assert len(result["accepted"][0]["sha256"]) == 64
    rejection_codes = {item["reason"] for item in result["rejected"]}
    assert {"duplicate_content", "UTM_DATA_NO_FORCE_SIGNAL", "target_strain_not_reached"} <= rejection_codes


def test_reference_calibration_blocks_without_eligible_force_curve(tmp_path: Path) -> None:
    module = importlib.import_module("utils.utm_reference_calibration")
    flat = tmp_path / "flat.csv"
    _write_curve(flat, [(0.0, 0.0, 0.0), (1.0, 15.0, 0.0)])

    result = module.build_reference_calibration(
        [flat],
        target_strain=0.5,
        specimen_size_mm=[30.0, 30.0, 30.0],
    )

    assert result["status"] == "blocked"
    assert result["accepted_count"] == 0
    assert result["reference_value"] is None
