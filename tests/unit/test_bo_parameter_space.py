"""Tests for the normalized BO parameter-space contract."""

from __future__ import annotations

import pytest

from learning.bo_parameter_space import BOParameterSpace


@pytest.fixture
def gyroid_two_variable_space() -> BOParameterSpace:
    return BOParameterSpace.from_mapping(
        {
            "geometry_type": ["gyroid"],
            "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
            "relative_density": [0.20, 0.48],
            "orientation_deg": [0.0],
            "anisotropy_ratio": [1.0],
        }
    )


@pytest.fixture
def mixed_space() -> BOParameterSpace:
    return BOParameterSpace.from_mapping(
        {
            "geometry_type": ["gyroid"],
            "relative_density": [0.20, 0.48],
            "wall_thickness_mm": [1.2, 2.0],
            "cell_size_mm": [10.0],
            "orientation_deg": [0, 15, 30, 45, 60, 90],
            "bottom_cap_enabled": [True, False],
        }
    )


def test_parameter_space_classifies_mixed_dimensions(mixed_space: BOParameterSpace) -> None:
    assert mixed_space.continuous_dimension_count == 2
    assert mixed_space.active_dimension_count == 4
    assert mixed_space.fixed_parameters == {"geometry_type": "gyroid", "cell_size_mm": 10.0}
    assert mixed_space.initial_design_size == 8
    assert len(mixed_space.schema_hash) == 64


def test_encode_decode_round_trip_is_stable(mixed_space: BOParameterSpace) -> None:
    parameters = {
        "geometry_type": "gyroid",
        "relative_density": 0.31,
        "wall_thickness_mm": 1.6,
        "cell_size_mm": 10.0,
        "orientation_deg": 45,
        "bottom_cap_enabled": False,
    }

    encoded = mixed_space.encode(parameters)
    decoded = mixed_space.decode(encoded)

    assert decoded["relative_density"] == pytest.approx(0.31)
    assert decoded["wall_thickness_mm"] == pytest.approx(1.6)
    assert decoded["orientation_deg"] == 45
    assert decoded["bottom_cap_enabled"] is False
    assert decoded["cell_size_mm"] == 10.0
    assert decoded["geometry_type"] == "gyroid"
    assert mixed_space.signature(decoded) == mixed_space.signature(parameters)


def test_lhs_is_deterministic_in_bounds_and_balances_discrete_values(mixed_space: BOParameterSpace) -> None:
    first = mixed_space.lhs_points(8, seed=17)
    second = mixed_space.lhs_points(8, seed=17)

    assert first == second
    assert len(first) == 8
    assert all(0.20 <= row["relative_density"] <= 0.48 for row in first)
    assert all(1.2 <= row["wall_thickness_mm"] <= 2.0 for row in first)
    assert {row["bottom_cap_enabled"] for row in first} == {True, False}
    assert len({row["orientation_deg"] for row in first}) >= 5


def test_lhs_excludes_observed_signatures(mixed_space: BOParameterSpace) -> None:
    baseline = mixed_space.lhs_points(8, seed=23)
    excluded = {mixed_space.signature(baseline[0]), mixed_space.signature(baseline[1])}

    remaining = mixed_space.lhs_points(6, seed=23, excluded_signatures=excluded)

    assert len(remaining) == 6
    assert all(mixed_space.signature(row) not in excluded for row in remaining)
    assert remaining[0] == baseline[2]


def test_mixed_fixed_features_enumerate_discrete_combinations(mixed_space: BOParameterSpace) -> None:
    combinations = mixed_space.mixed_fixed_features()

    assert len(combinations) == 12
    assert all(set(item) == {2, 3} for item in combinations)
    assert {item[3] for item in combinations} == {0.0, 1.0}


def test_invalid_space_and_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        BOParameterSpace.from_mapping({})
    with pytest.raises(ValueError, match="continuous bounds"):
        BOParameterSpace.from_mapping({"density": [0.5, 0.2]})

    space = BOParameterSpace.from_mapping({"density": [0.2, 0.4], "kind": ["a", "b"]})
    with pytest.raises(ValueError, match="outside"):
        space.encode({"density": 0.8, "kind": "a"})
    with pytest.raises(ValueError, match="not in choices"):
        space.encode({"density": 0.3, "kind": "c"})


def test_two_variable_gyroid_space_normalizes_only_cell_size_and_density(
    gyroid_two_variable_space: BOParameterSpace,
) -> None:
    encoded = gyroid_two_variable_space.encode(
        {
            "geometry_type": "gyroid",
            "cell_size_mm": 7.5,
            "relative_density": 0.34,
            "orientation_deg": 0.0,
            "anisotropy_ratio": 1.0,
        }
    )

    assert [item.name for item in gyroid_two_variable_space.active_dimensions] == [
        "cell_size_mm",
        "relative_density",
    ]
    assert encoded == pytest.approx([2.0 / 3.0, 0.5])
    assert gyroid_two_variable_space.decode(encoded)["cell_size_mm"] == 7.5

    with pytest.raises(ValueError, match="not in choices"):
        gyroid_two_variable_space.encode(
            {
                "geometry_type": "gyroid",
                "cell_size_mm": 8.0,
                "relative_density": 0.34,
                "orientation_deg": 0.0,
                "anisotropy_ratio": 1.0,
            }
        )


def test_two_variable_lhs_balances_feasible_cell_sizes_and_stratifies_density(
    gyroid_two_variable_space: BOParameterSpace,
) -> None:
    points = gyroid_two_variable_space.lhs_points(8, seed=7)

    assert len(points) == 8
    assert {item["cell_size_mm"] for item in points} == {5.0, 6.0, 7.5, 10.0}
    assert {cell: sum(item["cell_size_mm"] == cell for item in points) for cell in (5.0, 6.0, 7.5, 10.0)} == {
        5.0: 2,
        6.0: 2,
        7.5: 2,
        10.0: 2,
    }
    density_bins = {min(7, int((item["relative_density"] - 0.20) / 0.28 * 8)) for item in points}
    assert density_bins == set(range(8))
