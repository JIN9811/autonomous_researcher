"""
File purpose:
- Direct BoTorch GP fitting and acquisition optimization for sequential BO.
- Compatibility posterior scoring for the explicit lightweight benchmark.

Key classes/functions:
- is_available
- propose_next
- score_candidate_pool

Inputs/outputs:
- Input: candidate vectors, prior/evaluated vectors, scores, acquisition settings
- Output: posterior mean/uncertainty/acquisition values for each candidate-pool item

Dependencies:
- Optional: torch, botorch, gpytorch

Modification guide:
- Safe places to edit: acquisition formulas and fit limits.
- Risky places to edit: output keys consumed by experiments.benchmark and BO GUI.
"""

from __future__ import annotations

import importlib.util
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from learning.bo_parameter_space import BOParameterSpace


class BoTorchBackendUnavailable(RuntimeError):
    """Raised when optional BoTorch dependencies or data requirements are unavailable."""


class BoTorchBackendError(RuntimeError):
    """Typed production-backend failure that must not trigger a silent fallback."""

    def __init__(self, message: str, *, failure_code: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.failure_code = failure_code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "backend_requested": "botorch",
            "backend_active": "none",
            "failure_code": self.failure_code,
            "message": str(self),
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class BoTorchProposal:
    """Serializable result from one acquisition-optimized BO proposal."""

    backend_requested: str
    backend_active: str
    objective_direction: str
    schema_hash: str
    candidate: dict[str, Any]
    normalized_vector: list[float]
    posterior: dict[str, Any]
    acquisition: dict[str, Any]
    optimizer: dict[str, Any]
    model: dict[str, Any]
    projection: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_available() -> bool:
    """Return True when torch, gpytorch, and botorch can be imported."""
    return all(importlib.util.find_spec(name) is not None for name in ("torch", "gpytorch", "botorch"))


def _validated_observations(
    parameter_space: BOParameterSpace,
    observations: Sequence[Mapping[str, Any]],
) -> tuple[list[list[float]], list[float], list[float] | None, int]:
    grouped: dict[tuple[float, ...], dict[str, Any]] = {}
    valid_observation_count = 0
    for observation in observations:
        parameters = observation.get("parameters")
        score = observation.get("score", observation.get("objective_score"))
        if not isinstance(parameters, Mapping) or not isinstance(score, RealNumber):
            continue
        score_value = float(score)
        if not math.isfinite(score_value):
            continue
        vector = parameter_space.encode(parameters)
        signature = tuple(round(float(value), 12) for value in vector)
        bucket = grouped.setdefault(signature, {"vector": vector, "scores": [], "uncertainties": []})
        bucket["scores"].append(score_value)
        valid_observation_count += 1
        uncertainty = observation.get("uncertainty")
        if isinstance(uncertainty, RealNumber) and math.isfinite(float(uncertainty)) and float(uncertainty) > 0:
            bucket["uncertainties"].append(float(uncertainty))

    vectors: list[list[float]] = []
    scores: list[float] = []
    uncertainties: list[float] = []
    all_known_noise = True
    for bucket in grouped.values():
        bucket_scores = bucket["scores"]
        bucket_uncertainties = bucket["uncertainties"]
        vectors.append(list(bucket["vector"]))
        scores.append(sum(bucket_scores) / len(bucket_scores))
        if len(bucket_uncertainties) == len(bucket_scores):
            # Standard error of the replicate mean, preserving known-noise semantics.
            uncertainties.append(math.sqrt(sum(value * value for value in bucket_uncertainties)) / len(bucket_uncertainties))
        else:
            all_known_noise = False
    known_noise = uncertainties if all_known_noise and len(uncertainties) == len(scores) else None
    return vectors, scores, known_noise, valid_observation_count


RealNumber = (int, float)


def _build_acquisition(
    *,
    model: Any,
    acquisition: str,
    train_y: Any,
    kappa: float,
) -> tuple[Any, str]:
    from botorch.acquisition.analytic import (
        LogExpectedImprovement,
        PosteriorMean,
        PosteriorStandardDeviation,
        ProbabilityOfImprovement,
        UpperConfidenceBound,
    )

    name = str(acquisition or "expected_improvement").strip().lower()
    best_f = train_y.max()
    if name == "upper_confidence_bound":
        return UpperConfidenceBound(model=model, beta=max(1e-9, float(kappa) ** 2)), "UpperConfidenceBound"
    if name == "probability_of_improvement":
        return ProbabilityOfImprovement(model=model, best_f=best_f), "ProbabilityOfImprovement"
    if name == "uncertainty_sampling":
        return PosteriorStandardDeviation(model=model), "PosteriorStandardDeviation"
    if name == "exploitation":
        return PosteriorMean(model=model), "PosteriorMean"
    if name == "exploration":
        return UpperConfidenceBound(model=model, beta=max(4.0, float(kappa) ** 2)), "UpperConfidenceBound"
    if name != "expected_improvement":
        raise BoTorchBackendError(
            f"unsupported acquisition function: {name}",
            failure_code="BOTORCH_ACQUISITION_UNSUPPORTED",
            details={"acquisition": name},
        )
    return LogExpectedImprovement(model=model, best_f=best_f), "LogExpectedImprovement"


def _matches_observed_vector(candidate: Any, observed: Any, *, tolerance: float = 1e-7) -> bool:
    """Return whether one normalized candidate repeats an observed design."""
    import torch

    row = candidate.reshape(1, -1).to(dtype=torch.double)
    if observed.numel() == 0:
        return False
    distances = torch.linalg.vector_norm(observed.to(dtype=torch.double) - row, dim=1)
    return bool(torch.any(distances <= float(tolerance)).item())


def _best_nonduplicate_candidate(
    *,
    acquisition_function: Any,
    observed: Any,
    dimension_count: int,
    fixed_features: Sequence[Mapping[int, float]],
    random_seed: int,
    raw_samples: int,
) -> tuple[Any, Any]:
    """Rescore a deterministic mixed-space pool after an optimizer duplicate.

    Analytic acquisition optimization does not guarantee that its optimum is a
    new experiment. This pool preserves each discrete combination and only
    replaces a proposal when it exactly repeats prior normalized coordinates.
    """
    import torch

    sample_count = max(256, int(raw_samples) * 4)
    combinations = list(fixed_features) or [{}]
    rows: list[Any] = []
    for combination_index, combination in enumerate(combinations):
        engine = torch.quasirandom.SobolEngine(
            dimension=int(dimension_count),
            scramble=True,
            seed=int(random_seed) + combination_index,
        )
        candidates = engine.draw(sample_count).to(dtype=torch.double)
        for index, value in combination.items():
            candidates[:, int(index)] = float(value)
        rows.append(candidates)
    pool = torch.cat(rows, dim=0)
    distances = torch.cdist(pool, observed.to(dtype=torch.double))
    available = pool[torch.all(distances > 1e-7, dim=1)]
    if available.numel() == 0:
        raise BoTorchBackendError(
            "botorch could not find an unobserved mixed-space candidate",
            failure_code="BOTORCH_NO_UNOBSERVED_CANDIDATE",
            details={"pool_size": int(pool.shape[0]), "observation_count": int(observed.shape[0])},
        )
    with torch.no_grad():
        acquisition_values = acquisition_function(available.unsqueeze(-2)).reshape(-1)
    finite = torch.isfinite(acquisition_values)
    if not bool(torch.any(finite).item()):
        raise BoTorchBackendError(
            "botorch acquisition values are not finite for unobserved candidates",
            failure_code="BOTORCH_ACQUISITION_NONFINITE",
        )
    finite_indexes = torch.nonzero(finite, as_tuple=False).reshape(-1)
    best_index = finite_indexes[torch.argmax(acquisition_values[finite])]
    return available[best_index].reshape(1, -1), acquisition_values[best_index].reshape(1)


def _projection(
    *,
    model: Any,
    acquisition_function: Any,
    parameter_space: BOParameterSpace,
    candidate_vector: list[float],
    anchor_vectors: Sequence[Sequence[float]],
    objective_sign: float,
    points: int = 96,
) -> dict[str, Any]:
    import torch

    continuous = [
        (index, item)
        for index, item in enumerate(parameter_space.active_dimensions)
        if item.kind == "continuous"
    ]
    if not continuous:
        return {
            "mode": "observed_design_marginal",
            "anchor_count": 0,
            "parameter": "",
            "x": [],
            "mean": [],
            "std": [],
            "lower_95": [],
            "upper_95": [],
            "acquisition": [],
        }
    selected_index, selected_dimension = continuous[0]
    unit_values = torch.linspace(0.0, 1.0, points, dtype=torch.double)
    anchors = [list(vector) for vector in anchor_vectors if len(vector) == len(candidate_vector)]
    conditioned_anchors = [
        vector
        for vector in anchors
        if all(
            index == selected_index or math.isclose(float(value), float(candidate_vector[index]), abs_tol=1e-8)
            for index, value in enumerate(vector)
        )
    ]
    rows = torch.tensor([candidate_vector] * points, dtype=torch.double)
    rows[:, selected_index] = unit_values
    with torch.no_grad():
        posterior = model.posterior(rows)
        transformed_mean = posterior.mean.reshape(points)
        std = posterior.variance.clamp_min(1e-12).sqrt().reshape(points)
        mean = transformed_mean * objective_sign
        acquisition_values = acquisition_function(rows.unsqueeze(-2)).reshape(points)
    low, high = (float(item) for item in selected_dimension.values)
    x_values = low + unit_values * (high - low)
    lower = mean - 1.96 * std
    upper = mean + 1.96 * std
    decoded_candidate = parameter_space.decode(candidate_vector)
    fixed_parameters = {
        dimension.name: decoded_candidate[dimension.name]
        for dimension in parameter_space.active_dimensions
        if dimension.name != selected_dimension.name
    }
    result = {
        "mode": "candidate_conditioned_slice",
        "anchor_count": len(conditioned_anchors),
        "parameter": selected_dimension.name,
        "fixed_parameters": fixed_parameters,
        "x": [round(float(item), 8) for item in x_values.tolist()],
        "mean": [round(float(item), 8) for item in mean.tolist()],
        "std": [round(float(item), 8) for item in std.tolist()],
        "lower_95": [round(float(item), 8) for item in lower.tolist()],
        "upper_95": [round(float(item), 8) for item in upper.tolist()],
        "acquisition": [round(float(item), 8) for item in acquisition_values.tolist()],
    }
    active_dimensions = parameter_space.active_dimensions
    if len(active_dimensions) == 2:
        path_anchors = [list(vector) for vector in anchors]
        if not any(
            all(math.isclose(float(left), float(right), abs_tol=1e-10) for left, right in zip(anchor, candidate_vector, strict=True))
            for anchor in path_anchors
        ):
            path_anchors.append(list(candidate_vector))

        if len(path_anchors) >= 2:
            remaining = list(range(len(path_anchors)))
            start_index = min(remaining, key=lambda index: tuple(float(value) for value in path_anchors[index]))
            ordered_indexes = [start_index]
            remaining.remove(start_index)
            while remaining:
                previous = path_anchors[ordered_indexes[-1]]
                next_index = min(
                    remaining,
                    key=lambda index: (
                        sum((float(left) - float(right)) ** 2 for left, right in zip(previous, path_anchors[index], strict=True)),
                        tuple(float(value) for value in path_anchors[index]),
                    ),
                )
                ordered_indexes.append(next_index)
                remaining.remove(next_index)

            knot_tensor = torch.tensor([path_anchors[index] for index in ordered_indexes], dtype=torch.double)
            segment_lengths = torch.linalg.vector_norm(knot_tensor[1:] - knot_tensor[:-1], dim=1).clamp_min(1e-12)
            cumulative = torch.cat((torch.zeros(1, dtype=torch.double), torch.cumsum(segment_lengths, dim=0)))
            total_length = cumulative[-1].clamp_min(1e-12)
            path_coordinates = cumulative / total_length
            search_x = torch.linspace(0.0, 1.0, 384, dtype=torch.double)
            segment_indexes = torch.searchsorted(path_coordinates[1:], search_x, right=False).clamp_max(len(ordered_indexes) - 2)
            starts = path_coordinates[segment_indexes]
            ends = path_coordinates[segment_indexes + 1]
            fractions = (search_x - starts) / (ends - starts).clamp_min(1e-12)

            # Shape-preserving cubic Hermite interpolation keeps one C1 path
            # through every BO observation without the slice-boundary corners
            # produced by concatenating independent conditional projections.
            normalized_spans = (path_coordinates[1:] - path_coordinates[:-1]).unsqueeze(1)
            deltas = (knot_tensor[1:] - knot_tensor[:-1]) / normalized_spans
            tangents = torch.zeros_like(knot_tensor)
            tangents[0] = deltas[0]
            tangents[-1] = deltas[-1]
            if len(ordered_indexes) > 2:
                left_delta = deltas[:-1]
                right_delta = deltas[1:]
                same_direction = left_delta * right_delta > 0
                left_weight = 2.0 * segment_lengths[1:] + segment_lengths[:-1]
                right_weight = segment_lengths[1:] + 2.0 * segment_lengths[:-1]
                harmonic = (left_weight + right_weight).unsqueeze(1) / (
                    left_weight.unsqueeze(1) / left_delta.clamp(min=-1e12, max=1e12)
                    + right_weight.unsqueeze(1) / right_delta.clamp(min=-1e12, max=1e12)
                ).clamp(min=-1e12, max=1e12)
                tangents[1:-1] = torch.where(same_direction, harmonic, torch.zeros_like(harmonic))

            u = fractions.unsqueeze(1)
            u2 = u * u
            u3 = u2 * u
            segment_span = (ends - starts).unsqueeze(1)
            path_tensor = (
                (2.0 * u3 - 3.0 * u2 + 1.0) * knot_tensor[segment_indexes]
                + (u3 - 2.0 * u2 + u) * segment_span * tangents[segment_indexes]
                + (-2.0 * u3 + 3.0 * u2) * knot_tensor[segment_indexes + 1]
                + (u3 - u2) * segment_span * tangents[segment_indexes + 1]
            ).clamp(0.0, 1.0)
            with torch.no_grad():
                path_posterior = model.posterior(path_tensor)
                path_mean = path_posterior.mean.reshape(-1) * objective_sign
                path_std = path_posterior.variance.clamp_min(1e-12).sqrt().reshape(-1)
                path_acquisition = acquisition_function(path_tensor.unsqueeze(-2)).reshape(-1)

            coordinate_by_anchor = {
                original_index: float(path_coordinates[position].item())
                for position, original_index in enumerate(ordered_indexes)
            }
            observation_coordinates = [coordinate_by_anchor[index] for index in range(len(anchors))]
            candidate_anchor_index = next(
                (
                    index
                    for index, anchor in enumerate(path_anchors)
                    if all(
                        math.isclose(float(left), float(right), abs_tol=1e-10)
                        for left, right in zip(anchor, candidate_vector, strict=True)
                    )
                ),
                len(path_anchors) - 1,
            )
            result["objective_path"] = {
                "mode": "continuous_2d_gp_path",
                "parameter_names": [dimension.name for dimension in active_dimensions],
                "search_x": [round(float(value), 10) for value in search_x.tolist()],
                "normalized_vectors": [
                    [round(float(value), 10) for value in row]
                    for row in path_tensor.tolist()
                ],
                "mean": [round(float(value), 8) for value in path_mean.tolist()],
                "std": [round(float(value), 8) for value in path_std.tolist()],
                "lower_95": [round(float(value), 8) for value in (path_mean - 1.96 * path_std).tolist()],
                "upper_95": [round(float(value), 8) for value in (path_mean + 1.96 * path_std).tolist()],
                "acquisition": [round(float(value), 8) for value in path_acquisition.tolist()],
                "observation_coordinates": [round(value, 10) for value in observation_coordinates],
                "next_point_coordinate": round(coordinate_by_anchor[candidate_anchor_index], 10),
            }

        discrete = next(
            ((index, dimension) for index, dimension in enumerate(active_dimensions) if dimension.kind == "discrete"),
            None,
        )
        continuous_dimension = next(
            ((index, dimension) for index, dimension in enumerate(active_dimensions) if dimension.kind == "continuous"),
            None,
        )
        if discrete is not None and continuous_dimension is not None:
            discrete_index, discrete_dimension = discrete
            continuous_index, continuous_item = continuous_dimension
            continuous_units = torch.linspace(0.0, 1.0, points, dtype=torch.double)
            surface_rows: list[Any] = []
            for discrete_value in discrete_dimension.values:
                row = torch.zeros((points, 2), dtype=torch.double)
                row[:, discrete_index] = discrete_dimension.encode(discrete_value)
                row[:, continuous_index] = continuous_units
                surface_rows.append(row)
            surface_tensor = torch.cat(surface_rows, dim=0)
            with torch.no_grad():
                surface_posterior = model.posterior(surface_tensor)
                surface_mean = surface_posterior.mean.reshape(len(discrete_dimension.values), points) * objective_sign
                surface_std = surface_posterior.variance.clamp_min(1e-12).sqrt().reshape(len(discrete_dimension.values), points)
                surface_acquisition = acquisition_function(surface_tensor.unsqueeze(-2)).reshape(
                    len(discrete_dimension.values), points
                )
            continuous_low, continuous_high = (float(item) for item in continuous_item.values)
            continuous_values = continuous_low + continuous_units * (continuous_high - continuous_low)

            def _matrix(values: Any) -> list[list[float]]:
                return [
                    [round(float(value), 8) for value in row]
                    for row in values.tolist()
                ]

            result["surface"] = {
                "mode": "mixed_2d_gp_surface",
                "x_parameter": discrete_dimension.name,
                "x_values": [float(value) for value in discrete_dimension.values],
                "y_parameter": continuous_item.name,
                "y_values": [round(float(value), 8) for value in continuous_values.tolist()],
                "shape": [len(discrete_dimension.values), points],
                "mean": _matrix(surface_mean),
                "std": _matrix(surface_std),
                "lower_95": _matrix(surface_mean - 1.96 * surface_std),
                "upper_95": _matrix(surface_mean + 1.96 * surface_std),
                "acquisition": _matrix(surface_acquisition),
            }
    return result


def propose_next(
    *,
    parameter_space: BOParameterSpace,
    observations: Sequence[Mapping[str, Any]],
    acquisition: str = "expected_improvement",
    objective_direction: str = "maximize",
    random_seed: int = 7,
    kappa: float = 2.0,
    num_restarts: int = 12,
    raw_samples: int = 256,
    optimizer_timeout_s: float | None = None,
    fit_max_iter: int = 50,
    projection_candidate: Mapping[str, Any] | None = None,
) -> BoTorchProposal:
    """Fit a SingleTaskGP and directly optimize one next mixed-space candidate."""
    if not is_available():
        raise BoTorchBackendError(
            "torch/botorch/gpytorch are not installed",
            failure_code="BOTORCH_DEPENDENCY_UNAVAILABLE",
        )
    vectors, scores, uncertainties, observation_count = _validated_observations(parameter_space, observations)
    if len(vectors) < 2:
        raise BoTorchBackendError(
            "botorch backend requires at least two valid observations",
            failure_code="BOTORCH_INSUFFICIENT_OBSERVATIONS",
            details={"valid_observation_count": len(vectors)},
        )
    direction = str(objective_direction or "maximize").strip().lower()
    if direction not in {"maximize", "minimize"}:
        raise BoTorchBackendError(
            f"invalid objective direction: {direction}",
            failure_code="BOTORCH_OBJECTIVE_DIRECTION_INVALID",
        )
    if parameter_space.active_dimension_count == 0:
        raise BoTorchBackendError(
            "parameter space has no active dimensions",
            failure_code="BOTORCH_PARAMETER_SPACE_FIXED",
        )

    try:
        import torch
        from botorch.fit import fit_gpytorch_mll
        from botorch.models import SingleTaskGP
        from botorch.models.transforms.outcome import Standardize
        from botorch.optim import optimize_acqf, optimize_acqf_mixed
        from gpytorch.kernels import MaternKernel, ScaleKernel
        from gpytorch.mlls import ExactMarginalLogLikelihood

        torch.manual_seed(int(random_seed))
        train_x = torch.tensor(vectors, dtype=torch.double)
        objective_sign = 1.0 if direction == "maximize" else -1.0
        train_y = torch.tensor([objective_sign * value for value in scores], dtype=torch.double).view(-1, 1)
        model_kwargs: dict[str, Any] = {
            "train_X": train_x,
            "train_Y": train_y,
            "outcome_transform": Standardize(m=1),
            "covar_module": ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=parameter_space.active_dimension_count)),
        }
        noise_mode = "inferred_homoskedastic"
        if uncertainties is not None:
            variances = [max(1e-10, value * value) for value in uncertainties]
            model_kwargs["train_Yvar"] = torch.tensor(variances, dtype=torch.double).view(-1, 1)
            noise_mode = "known_observation_variance"
        model = SingleTaskGP(**model_kwargs)
        mll = ExactMarginalLogLikelihood(model.likelihood, model)
        fit_gpytorch_mll(mll, optimizer_kwargs={"options": {"maxiter": int(max(5, fit_max_iter))}})
        model.eval()

        acq_function, acq_class = _build_acquisition(
            model=model,
            acquisition=acquisition,
            train_y=train_y,
            kappa=kappa,
        )
        bounds = torch.stack(
            [
                torch.zeros(parameter_space.active_dimension_count, dtype=torch.double),
                torch.ones(parameter_space.active_dimension_count, dtype=torch.double),
            ]
        )
        fixed_features = parameter_space.mixed_fixed_features()
        optimizer_name = "optimize_acqf_mixed" if fixed_features else "optimize_acqf"
        optimizer_kwargs = {
            "acq_function": acq_function,
            "bounds": bounds,
            "q": 1,
            "num_restarts": max(1, int(num_restarts)),
            "raw_samples": max(8, int(raw_samples)),
            "timeout_sec": optimizer_timeout_s,
        }
        if fixed_features:
            candidate_tensor, acquisition_value = optimize_acqf_mixed(
                **optimizer_kwargs,
                fixed_features_list=fixed_features,
            )
        else:
            candidate_tensor, acquisition_value = optimize_acqf(**optimizer_kwargs)
        duplicate_replaced = _matches_observed_vector(candidate_tensor, train_x)
        if duplicate_replaced:
            candidate_tensor, acquisition_value = _best_nonduplicate_candidate(
                acquisition_function=acq_function,
                observed=train_x,
                dimension_count=parameter_space.active_dimension_count,
                fixed_features=fixed_features,
                random_seed=random_seed,
                raw_samples=raw_samples,
            )
        vector = [min(1.0, max(0.0, float(item))) for item in candidate_tensor.reshape(-1).tolist()]
        candidate = parameter_space.decode(vector)
        with torch.no_grad():
            posterior = model.posterior(torch.tensor([vector], dtype=torch.double))
            transformed_mean = float(posterior.mean.reshape(-1)[0].item())
            posterior_std = float(posterior.variance.clamp_min(1e-12).sqrt().reshape(-1)[0].item())
        posterior_mean = transformed_mean * objective_sign
        confidence = [posterior_mean - 1.96 * posterior_std, posterior_mean + 1.96 * posterior_std]
        acq_scalar = float(acquisition_value.reshape(-1)[0].item()) if acquisition_value is not None else float("nan")
        return BoTorchProposal(
            backend_requested="botorch",
            backend_active="botorch",
            objective_direction=direction,
            schema_hash=parameter_space.schema_hash,
            candidate=candidate,
            normalized_vector=[round(value, 10) for value in vector],
            posterior={
                "mean": round(posterior_mean, 8),
                "std": round(posterior_std, 8),
                "confidence_95": [round(value, 8) for value in confidence],
            },
            acquisition={
                "requested": str(acquisition or "expected_improvement").strip().lower(),
                "class": acq_class,
                "value": round(acq_scalar, 8),
                "kappa": float(kappa),
            },
            optimizer={
                "function": optimizer_name,
                "q": 1,
                "num_restarts": max(1, int(num_restarts)),
                "raw_samples": max(8, int(raw_samples)),
                "timeout_s": optimizer_timeout_s,
                "mixed_combination_count": len(fixed_features),
                "duplicate_replaced": duplicate_replaced,
                "duplicate_avoidance": "sobol_acquisition_rescore",
            },
            model={
                "class": "SingleTaskGP",
                "observation_count": observation_count,
                "training_count": len(vectors),
                "duplicate_observation_count": observation_count - len(vectors),
                "noise_mode": noise_mode,
                "fit_max_iter": int(max(5, fit_max_iter)),
                "kernel": f"ScaleKernel(MaternKernel(nu=2.5, ard_num_dims={parameter_space.active_dimension_count}))",
                "ard_num_dims": parameter_space.active_dimension_count,
                "input_normalization": "unit_hypercube",
            },
            projection=_projection(
                model=model,
                acquisition_function=acq_function,
                parameter_space=parameter_space,
                candidate_vector=(
                    parameter_space.encode(projection_candidate)
                    if isinstance(projection_candidate, Mapping)
                    else vector
                ),
                anchor_vectors=vectors,
                objective_sign=objective_sign,
            ),
        )
    except BoTorchBackendError:
        raise
    except Exception as exc:
        raise BoTorchBackendError(
            f"botorch proposal failed: {exc.__class__.__name__}: {exc}",
            failure_code="BOTORCH_PROPOSAL_FAILED",
            details={"exception_type": exc.__class__.__name__},
        ) from exc


def _normalize_vectors(vectors: list[list[float]], lows: list[float], highs: list[float]) -> list[list[float]]:
    out: list[list[float]] = []
    for vector in vectors:
        row: list[float] = []
        for idx, value in enumerate(vector):
            width = max(1e-12, highs[idx] - lows[idx])
            row.append(max(0.0, min(1.0, (float(value) - lows[idx]) / width)))
        out.append(row)
    return out


def _normal_pdf(value: Any) -> Any:
    return 0.3989422804014327 * value.neg().pow(2).mul(0.5).neg().exp()


def _expected_improvement(mean: Any, std: Any, best: float, xi: float) -> Any:
    improvement = mean - float(best) - float(xi)
    safe_std = std.clamp_min(1e-9)
    z = improvement / safe_std
    normal = 0.5 * (1.0 + torch_erf(z / math.sqrt(2.0)))
    return improvement * normal + safe_std * _normal_pdf(z)


def torch_erf(value: Any) -> Any:
    # Kept separate so mypy/static inspection does not require torch at import time.
    import torch

    return torch.erf(value)


def score_candidate_pool(
    *,
    candidates: list[dict[str, Any]],
    vectors: list[list[float]],
    evaluated_vectors: list[list[float]],
    scores: list[float],
    acquisition: str,
    kappa: float,
    xi: float,
    exploration_weight: float,
    exploitation_weight: float,
    fit_max_iter: int = 50,
) -> list[dict[str, float]]:
    """Score an existing candidate pool with a BoTorch SingleTaskGP posterior.

    The optimizer still uses the repository's candidate-pool contract instead of
    unconstrained continuous optimization. This keeps categorical/boolean FDM
    parameters, locked dimensions, and downstream validators authoritative.
    """
    if len(evaluated_vectors) < 2 or len(scores) < 2:
        raise BoTorchBackendUnavailable("botorch backend requires at least two evaluated points")
    if not candidates or not vectors:
        raise BoTorchBackendUnavailable("empty candidate pool")
    if not is_available():
        raise BoTorchBackendUnavailable("torch/botorch/gpytorch are not installed")

    import torch
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.outcome import Standardize
    from gpytorch.mlls import ExactMarginalLogLikelihood

    dims = len(vectors[0])
    all_vectors = [*vectors, *evaluated_vectors]
    lows = [min(float(row[idx]) for row in all_vectors) for idx in range(dims)]
    highs = [max(float(row[idx]) for row in all_vectors) for idx in range(dims)]
    train_x = torch.tensor(_normalize_vectors(evaluated_vectors, lows, highs), dtype=torch.double)
    cand_x = torch.tensor(_normalize_vectors(vectors, lows, highs), dtype=torch.double)
    train_y = torch.tensor([float(item) for item in scores], dtype=torch.double).view(-1, 1)

    model = SingleTaskGP(train_X=train_x, train_Y=train_y, outcome_transform=Standardize(m=1))
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll, optimizer_kwargs={"options": {"maxiter": int(max(5, fit_max_iter))}})
    model.eval()

    with torch.no_grad():
        posterior = model.posterior(cand_x)
        mean = posterior.mean.squeeze(-1).squeeze(-1)
        std = posterior.variance.clamp_min(1e-12).sqrt().squeeze(-1).squeeze(-1)
        best = max(float(item) for item in scores)
        acq = acquisition.strip().lower()
        if acq == "upper_confidence_bound":
            values = mean + float(kappa) * std
        elif acq == "probability_of_improvement":
            z = (mean - best - float(xi)) / std.clamp_min(1e-9)
            values = 0.5 * (1.0 + torch.erf(z / math.sqrt(2.0)))
        elif acq == "uncertainty_sampling":
            values = std
        elif acq == "exploitation":
            values = mean
        elif acq == "exploration":
            values = std + 0.1 * mean
        else:
            values = _expected_improvement(mean, std, best, float(xi)) * float(exploitation_weight) + std * float(exploration_weight)

    return [
        {
            "surrogate_mean": round(float(mean[idx].item()), 6),
            "uncertainty": round(float(std[idx].item()), 6),
            "acquisition_value": round(float(values[idx].item()), 6),
        }
        for idx in range(len(candidates))
    ]
