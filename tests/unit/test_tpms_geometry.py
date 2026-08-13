"""Focused tests for Gyroid density realization metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_tools.tpms_geometry import write_smooth_gyroid_stl


@pytest.mark.parametrize("target_density", [0.20, 0.34, 0.48])
def test_smooth_gyroid_reports_requested_and_realized_base_density(
    tmp_path: Path,
    target_density: float,
) -> None:
    metadata = write_smooth_gyroid_stl(
        stl_path=tmp_path / f"gyroid-{target_density:.2f}.stl",
        name="density-contract",
        specimen_size_mm=[30.0, 30.0, 30.0],
        wall_thickness_mm=1.2,
        cell_size_mm=6.0,
        relative_density=target_density,
        anisotropy_ratio=1.0,
        orientation_deg=0.0,
        defect_seed=1,
        defect_ratio=0.0,
        skin_thickness_mm=0.8,
        top_cap_enabled=False,
        bottom_cap_enabled=True,
        resolution=48,
    )

    assert metadata is not None
    assert metadata["target_relative_density"] == pytest.approx(target_density)
    assert metadata["tpms_thickness_source"] == "relative_density_inverse"
    assert metadata["realized_relative_density_without_caps"] == pytest.approx(target_density, abs=0.02)
    assert metadata["relative_density_absolute_error"] <= 0.02
    assert metadata["solid_fraction"] >= metadata["realized_relative_density_without_caps"]
