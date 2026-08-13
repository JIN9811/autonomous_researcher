"""Tests for direct BoTorch GP fitting and acquisition optimization."""

from __future__ import annotations

import math

import pytest
import torch

from learning.bo_parameter_space import BOParameterSpace
from learning.botorch_backend import BoTorchBackendError, propose_next


def _space() -> BOParameterSpace:
    return BOParameterSpace.from_mapping(
        {
            "geometry_type": ["gyroid"],
            "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
            "relative_density": [0.20, 0.48],
            "orientation_deg": [0.0],
            "anisotropy_ratio": [1.0],
        }
    )


def _observations() -> list[dict[str, object]]:
    return [
        {
            "candidate_id": "obs-1",
            "parameters": {"geometry_type": "gyroid", "cell_size_mm": 5.0, "relative_density": 0.22, "orientation_deg": 0.0, "anisotropy_ratio": 1.0},
            "score": 0.38,
            "uncertainty": 0.04,
        },
        {
            "candidate_id": "obs-2",
            "parameters": {"geometry_type": "gyroid", "cell_size_mm": 6.0, "relative_density": 0.31, "orientation_deg": 0.0, "anisotropy_ratio": 1.0},
            "score": 0.76,
            "uncertainty": 0.03,
        },
        {
            "candidate_id": "obs-3",
            "parameters": {"geometry_type": "gyroid", "cell_size_mm": 10.0, "relative_density": 0.44, "orientation_deg": 0.0, "anisotropy_ratio": 1.0},
            "score": 0.51,
            "uncertainty": 0.05,
        },
    ]


@pytest.mark.parametrize(
    "acquisition",
    ["expected_improvement", "upper_confidence_bound", "probability_of_improvement", "uncertainty_sampling", "exploitation", "exploration"],
)
def test_propose_next_uses_real_botorch_optimizer(acquisition: str) -> None:
    result = propose_next(
        parameter_space=_space(),
        observations=_observations(),
        acquisition=acquisition,
        random_seed=13,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=15,
    ).to_dict()

    assert result["backend_active"] == "botorch"
    assert result["model"]["class"] == "SingleTaskGP"
    assert result["optimizer"]["function"] == "optimize_acqf_mixed"
    assert result["acquisition"]["requested"] == acquisition
    assert result["candidate"]["cell_size_mm"] in {5.0, 6.0, 7.5, 10.0}
    assert 0.20 <= result["candidate"]["relative_density"] <= 0.48
    assert result["candidate"]["orientation_deg"] == 0.0
    assert result["candidate"]["anisotropy_ratio"] == 1.0
    assert math.isfinite(result["posterior"]["mean"])
    assert result["posterior"]["std"] >= 0
    assert len(result["projection"]["x"]) == 96
    assert len(result["projection"]["mean"]) == 96
    assert result["projection"]["mode"] == "candidate_conditioned_slice"
    assert result["projection"]["fixed_parameters"]["cell_size_mm"] == result["candidate"]["cell_size_mm"]
    assert 0 <= result["projection"]["anchor_count"] <= len(_observations())


def test_expected_improvement_reports_logei_class_for_plotting() -> None:
    result = propose_next(
        parameter_space=_space(),
        observations=_observations(),
        acquisition="expected_improvement",
        random_seed=13,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=15,
    ).to_dict()

    assert result["acquisition"]["class"] == "LogExpectedImprovement"
    assert result["model"]["kernel"] == "ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=2))"
    assert result["model"]["ard_num_dims"] == 2
    assert result["model"]["input_normalization"] == "unit_hypercube"


def test_repeated_design_coordinates_are_aggregated_before_gp_fit() -> None:
    observations = _observations()
    observations.extend(
        [
            {
                **dict(observations[0]),
                "candidate_id": f"repeat-{index}",
                "score": 0.38,
            }
            for index in range(5)
        ]
    )

    result = propose_next(
        parameter_space=_space(),
        observations=observations,
        acquisition="expected_improvement",
        random_seed=13,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=15,
    ).to_dict()

    assert result["model"]["observation_count"] == 8
    assert result["model"]["training_count"] == 3
    assert result["model"]["duplicate_observation_count"] == 5


def test_projection_conditions_on_selected_discrete_design_instead_of_averaging_all_cells() -> None:
    observations = []
    for cell_size, offset in ((5.0, 0.0), (10.0, 0.3)):
        for density in (0.20, 0.30, 0.40, 0.48):
            observations.append(
                {
                    "candidate_id": f"obs-{cell_size}-{density}",
                    "parameters": {
                        "geometry_type": "gyroid",
                        "cell_size_mm": cell_size,
                        "relative_density": density,
                        "orientation_deg": 0.0,
                        "anisotropy_ratio": 1.0,
                    },
                    "score": offset + density,
                }
            )

    result = propose_next(
        parameter_space=_space(),
        observations=observations,
        acquisition="expected_improvement",
        random_seed=17,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=25,
    ).to_dict()

    projection = result["projection"]
    assert projection["mode"] == "candidate_conditioned_slice"
    assert projection["fixed_parameters"] == {"cell_size_mm": result["candidate"]["cell_size_mm"]}
    assert projection["anchor_count"] == 4
    assert max(projection["mean"]) - min(projection["mean"]) > 0.1


def test_projection_exposes_two_dimensional_gp_surface_from_all_lhs_observations() -> None:
    observations = []
    for index, (cell_size, density, score) in enumerate(
        (
            (5.0, 0.22, 0.38),
            (6.0, 0.31, 0.76),
            (7.5, 0.44, 0.51),
            (10.0, 0.27, 0.64),
            (5.0, 0.39, 0.83),
            (6.0, 0.46, 0.56),
            (7.5, 0.25, 0.69),
            (10.0, 0.35, 0.72),
        ),
        start=1,
    ):
        observations.append(
            {
                "candidate_id": f"lhs-{index:03d}",
                "parameters": {
                    "geometry_type": "gyroid",
                    "cell_size_mm": cell_size,
                    "relative_density": density,
                    "orientation_deg": 0.0,
                    "anisotropy_ratio": 1.0,
                },
                "score": score,
                "uncertainty": 0.03,
            }
        )

    result = propose_next(
        parameter_space=_space(),
        observations=observations,
        acquisition="expected_improvement",
        random_seed=19,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=15,
    ).to_dict()

    surface = result["projection"]["surface"]
    assert result["model"]["training_count"] == 8
    assert surface["mode"] == "mixed_2d_gp_surface"
    assert surface["x_parameter"] == "cell_size_mm"
    assert surface["x_values"] == [5.0, 6.0, 7.5, 10.0]
    assert surface["y_parameter"] == "relative_density"
    assert surface["y_values"][0] == pytest.approx(0.20)
    assert surface["y_values"][-1] == pytest.approx(0.48)
    assert surface["shape"] == [4, len(surface["y_values"])]
    for key in ("mean", "std", "lower_95", "upper_95", "acquisition"):
        assert len(surface[key]) == 4
        assert all(len(row) == len(surface["y_values"]) for row in surface[key])
        assert all(math.isfinite(value) for row in surface[key] for value in row)


def test_projection_evaluates_one_continuous_path_through_two_dimensional_gp() -> None:
    observations = []
    for index, (cell_size, density, score) in enumerate(
        (
            (5.0, 0.22, 0.38),
            (6.0, 0.31, 0.76),
            (7.5, 0.44, 0.51),
            (10.0, 0.27, 0.64),
            (5.0, 0.39, 0.83),
            (6.0, 0.46, 0.56),
            (7.5, 0.25, 0.69),
            (10.0, 0.35, 0.72),
        ),
        start=1,
    ):
        observations.append(
            {
                "candidate_id": f"lhs-{index:03d}",
                "parameters": {
                    "geometry_type": "gyroid",
                    "cell_size_mm": cell_size,
                    "relative_density": density,
                    "orientation_deg": 0.0,
                    "anisotropy_ratio": 1.0,
                },
                "score": score,
                "uncertainty": 0.03,
            }
        )

    result = propose_next(
        parameter_space=_space(),
        observations=observations,
        acquisition="expected_improvement",
        random_seed=19,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=15,
    ).to_dict()

    path = result["projection"]["objective_path"]
    assert path["mode"] == "continuous_2d_gp_path"
    assert path["parameter_names"] == ["cell_size_mm", "relative_density"]
    assert len(path["search_x"]) == 384
    assert path["search_x"][0] == pytest.approx(0.0)
    assert path["search_x"][-1] == pytest.approx(1.0)
    assert path["search_x"] == sorted(path["search_x"])
    assert len(path["normalized_vectors"]) == len(path["search_x"])
    assert all(len(vector) == 2 for vector in path["normalized_vectors"])
    assert all(0.0 <= value <= 1.0 for vector in path["normalized_vectors"] for value in vector)
    assert max(
        math.dist(left, right)
        for left, right in zip(path["normalized_vectors"], path["normalized_vectors"][1:])
    ) < 0.05
    for key in ("mean", "std", "lower_95", "upper_95", "acquisition"):
        assert len(path[key]) == len(path["search_x"])
        assert all(math.isfinite(value) for value in path[key])
    assert len(path["observation_coordinates"]) == 8
    assert 0.0 <= path["next_point_coordinate"] <= 1.0
    assert "segment_index" not in path


def test_propose_next_supports_minimize_and_known_noise() -> None:
    result = propose_next(
        parameter_space=_space(),
        observations=_observations(),
        acquisition="expected_improvement",
        objective_direction="minimize",
        random_seed=5,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=15,
    ).to_dict()

    assert result["objective_direction"] == "minimize"
    assert result["model"]["noise_mode"] == "known_observation_variance"
    assert result["posterior"]["confidence_95"][0] <= result["posterior"]["mean"]
    assert result["posterior"]["confidence_95"][1] >= result["posterior"]["mean"]


def test_inferred_noise_posterior_tracks_sea_observations_instead_of_flat_prior() -> None:
    observations = [
        {
            "parameters": {
                "geometry_type": "gyroid",
                "cell_size_mm": cell_size,
                "relative_density": density,
                "orientation_deg": 0.0,
                "anisotropy_ratio": 1.0,
            },
            "score": score,
        }
        for cell_size, density, score in (
            (5.0, 0.20, 0.01813),
            (5.0, 0.34, 0.01055),
            (5.0, 0.45, 0.00807),
            (6.0, 0.27, 0.01344),
            (6.0, 0.38, 0.00947),
            (7.5, 0.30, 0.01220),
            (7.5, 0.42, 0.00871),
            (10.0, 0.22, 0.01615),
            (10.0, 0.32, 0.00674),
        )
    ]

    result = propose_next(
        parameter_space=_space(),
        observations=observations,
        acquisition="expected_improvement",
        random_seed=23,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=50,
    ).to_dict()

    surface = result["projection"]["surface"]
    posterior_values = [value for row in surface["mean"] for value in row]
    assert result["model"]["noise_mode"] == "inferred_homoskedastic"
    assert max(posterior_values) - min(posterior_values) > 0.008

    for observation in observations:
        cell_index = surface["x_values"].index(observation["parameters"]["cell_size_mm"])
        density_index = min(
            range(len(surface["y_values"])),
            key=lambda index: abs(surface["y_values"][index] - observation["parameters"]["relative_density"]),
        )
        predicted = surface["mean"][cell_index][density_index]
        assert predicted == pytest.approx(observation["score"], abs=8e-4)


def test_propose_next_rejects_insufficient_observations_without_fallback() -> None:
    with pytest.raises(BoTorchBackendError, match="at least two") as exc_info:
        propose_next(parameter_space=_space(), observations=_observations()[:1])

    assert exc_info.value.failure_code == "BOTORCH_INSUFFICIENT_OBSERVATIONS"
    assert exc_info.value.to_dict()["backend_active"] == "none"


def test_propose_next_replaces_optimizer_duplicate_with_unobserved_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    import botorch.optim

    space = _space()
    observations = _observations()
    duplicate_vector = torch.tensor([[space.encode(observations[0]["parameters"])]], dtype=torch.double)

    def _duplicate_optimizer(**_kwargs):
        return duplicate_vector, torch.tensor([1.0], dtype=torch.double)

    monkeypatch.setattr(botorch.optim, "optimize_acqf_mixed", _duplicate_optimizer)

    result = propose_next(
        parameter_space=space,
        observations=observations,
        acquisition="expected_improvement",
        random_seed=13,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=15,
    ).to_dict()

    observed_signatures = {space.signature(item["parameters"]) for item in observations}
    assert space.signature(result["candidate"]) not in observed_signatures
    assert result["optimizer"]["duplicate_replaced"] is True
    assert result["optimizer"]["duplicate_avoidance"] == "sobol_acquisition_rescore"
