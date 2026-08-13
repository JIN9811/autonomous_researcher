"""Contract tests for the dedicated mixed-space LHS visualization."""

from __future__ import annotations

import pytest

from experiments.lhs_design_visualization import (
    build_lhs_design_visualization,
    validate_lhs_design_visualization,
)


def _payload() -> dict[str, object]:
    return build_lhs_design_visualization(
        run_id="run-lhs-contract",
        parameter_space={
            "geometry_type": ["gyroid"],
            "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
            "relative_density": [0.20, 0.48],
        },
        trace={
            "step": 3,
            "phase": "initial_design",
            "initial_design": {
                "sampler": "latin_hypercube",
                "target": 8,
                "completed": 2,
                "seed": 7,
                "points": [
                    {"index": 1, "status": "measured", "parameters": {"cell_size_mm": 10.0, "relative_density": 0.31}},
                    {"index": 2, "status": "measured", "parameters": {"cell_size_mm": 5.0, "relative_density": 0.35}},
                    {"index": 3, "status": "next", "parameters": {"cell_size_mm": 6.0, "relative_density": 0.39}},
                    {"index": 4, "status": "planned", "parameters": {"cell_size_mm": 7.5, "relative_density": 0.29}},
                ],
            },
        },
    )


def test_build_lhs_design_visualization_exposes_mixed_space_contract() -> None:
    payload = _payload()

    assert payload["schema"] == "lhs_design_visualization.v1"
    assert payload["step"] == 3
    assert payload["design_space"]["x"] == {
        "name": "cell_size_mm",
        "label": "Cell size",
        "unit": "mm",
        "kind": "discrete",
        "values": [5.0, 6.0, 7.5, 10.0],
    }
    assert payload["design_space"]["y"] == {
        "name": "relative_density",
        "label": "Relative density",
        "unit": "1",
        "kind": "continuous",
        "bounds": [0.2, 0.48],
    }
    assert payload["initial_design"]["completed"] == 2
    assert payload["initial_design"]["target"] == 8
    assert payload["initial_design"]["points"][2]["density_stratum"] in range(1, 9)
    assert payload["diagnostics"]["duplicate_count"] == 0
    assert payload["diagnostics"]["coverage_fraction"] == pytest.approx(0.25)
    assert payload["diagnostics"]["centered_discrepancy"] >= 0.0


def test_validate_lhs_design_visualization_rejects_invalid_points() -> None:
    payload = _payload()
    payload["initial_design"]["points"][0]["parameters"]["relative_density"] = 0.8

    with pytest.raises(ValueError, match="relative_density"):
        validate_lhs_design_visualization(payload)

