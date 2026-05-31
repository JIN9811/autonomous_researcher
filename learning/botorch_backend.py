"""
File purpose:
- Optional BoTorch posterior scoring backend for the lightweight BO benchmark.

Key classes/functions:
- is_available
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
from typing import Any


class BoTorchBackendUnavailable(RuntimeError):
    """Raised when optional BoTorch dependencies or data requirements are unavailable."""


def is_available() -> bool:
    """Return True when torch, gpytorch, and botorch can be imported."""
    return all(importlib.util.find_spec(name) is not None for name in ("torch", "gpytorch", "botorch"))


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
