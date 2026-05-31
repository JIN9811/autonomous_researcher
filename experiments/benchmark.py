"""
File purpose:
- Compare random, grid, and BO-style experiment proposal strategies.

Key classes/functions:
- run_benchmark

Inputs/outputs:
- Input: objective, parameter space, strategy list, budget, evaluator
- Output: per-strategy curves and best candidate summaries

Dependencies:
- experiments.api.evaluate_experiment
- learning.bo_engine.propose_next

Modification guide:
- Safe places to edit: candidate generation heuristics and default budgets
- Risky places to edit: output keys used by GUI/reporting
"""

from __future__ import annotations

import itertools
import random
from collections.abc import Callable
from typing import Any

from experiments.api import evaluate_experiment
from experiments.schemas import ExperimentEvaluationRequest
from learning.bo_engine import propose_next
from learning.botorch_backend import BoTorchBackendUnavailable, score_candidate_pool as score_botorch_candidate_pool

Evaluator = Callable[[dict[str, Any]], dict[str, Any]]


def _space_values(parameter_space: dict[str, Any]) -> dict[str, list[Any]]:
    values: dict[str, list[Any]] = {}
    for key, raw in parameter_space.items():
        if isinstance(raw, list):
            if len(raw) == 2 and all(isinstance(item, (int, float)) for item in raw):
                low, high = float(raw[0]), float(raw[1])
                values[key] = [low, round((low + high) / 2.0, 6), high]
            else:
                values[key] = list(raw)
        else:
            values[key] = [raw]
    return values


def _grid_candidates(parameter_space: dict[str, Any], budget: int) -> list[dict[str, Any]]:
    values = _space_values(parameter_space)
    keys = list(values)
    candidates: list[dict[str, Any]] = []
    for combo in itertools.product(*(values[key] for key in keys)):
        candidates.append(dict(zip(keys, combo, strict=True)))
    if len(candidates) <= budget:
        return candidates
    if budget <= 1:
        return candidates[:1]
    indexes = [round(i * (len(candidates) - 1) / (budget - 1)) for i in range(budget)]
    return [candidates[idx] for idx in indexes]


def _random_candidates(parameter_space: dict[str, Any], budget: int, *, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    candidates: list[dict[str, Any]] = []
    for _ in range(budget):
        candidate: dict[str, Any] = {}
        for key, raw in parameter_space.items():
            if isinstance(raw, list) and len(raw) == 2 and all(isinstance(item, (int, float)) for item in raw):
                candidate[key] = round(rng.uniform(float(raw[0]), float(raw[1])), 6)
            elif isinstance(raw, list) and raw:
                candidate[key] = rng.choice(raw)
            else:
                candidate[key] = raw
        candidates.append(candidate)
    return candidates


def _numeric_vector(candidate: dict[str, Any], keys: list[str] | None = None) -> list[float]:
    vector: list[float] = []
    values = (candidate.get(key) for key in keys) if keys is not None else candidate.values()
    for value in values:
        if isinstance(value, (int, float)):
            vector.append(float(value))
        else:
            vector.append(float(abs(hash(str(value))) % 1000) / 1000.0)
    return vector


def _vector_signature(vector: list[float]) -> tuple[float, ...]:
    """Return a rounded signature stable enough for duplicate-point detection."""
    return tuple(round(float(item), 9) for item in vector)


def _candidate_proxy(candidate: dict[str, Any]) -> float:
    density = float(candidate.get("relative_density", 0.32) or 0.32)
    wall = float(candidate.get("wall_thickness_mm", 1.2) or 1.2)
    cell = max(0.1, float(candidate.get("cell_size_mm", 5.0) or 5.0))
    geometry_bonus = 0.08 if str(candidate.get("geometry_type", "")).lower() == "gyroid" else 0.0
    density_term = 1.0 - abs(density - 0.32)
    manufacturability = min(1.0, wall / max(1.2, 0.24 * cell))
    return max(0.0, density_term * 0.55 + manufacturability * 0.35 + geometry_bonus)


def _distance(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b, strict=False))


def _uncertainty(vector: list[float], seen_vectors: list[list[float]]) -> float:
    if not seen_vectors:
        return 1.0
    return min(1.0, min(_distance(vector, item) for item in seen_vectors))


def _compact_parameters(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return BO-relevant parameters for trace display without large nested payloads."""
    preferred = (
        "geometry_type",
        "relative_density",
        "wall_thickness_mm",
        "cell_size_mm",
        "tpms_thickness",
        "orientation_deg",
        "anisotropy_ratio",
        "skin_thickness_mm",
        "bottom_cap_enabled",
        "top_cap_enabled",
        "skirt_enabled",
    )
    compact = {key: candidate.get(key) for key in preferred if key in candidate}
    if compact:
        return compact
    return {
        key: value
        for key, value in candidate.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }


def _prior_points(payload: dict[str, Any], keys: list[str]) -> tuple[list[list[float]], list[float], list[dict[str, Any]]]:
    raw = payload.get("prior_evaluations")
    if not isinstance(raw, list):
        return [], [], []
    vectors: list[list[float]] = []
    scores: list[float] = []
    records: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        params = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        if not any(key in params for key in keys):
            continue
        vector = _numeric_vector(params, keys)
        score = item.get("score")
        if isinstance(score, (int, float)):
            score_value = float(score)
        else:
            score_value = _candidate_proxy(params)
        vectors.append(vector)
        scores.append(score_value)
        records.append(
            {
                "source": str(item.get("source") or "prior"),
                "candidate_id": str(item.get("candidate_id") or params.get("candidate_id") or f"prior-{len(records) + 1}"),
                "score": round(score_value, 6),
                "parameters": _compact_parameters(params),
                "vector_signature": list(_vector_signature(vector)),
            }
        )
    return vectors, scores, records


def _acquisition_value(
    *,
    candidate: dict[str, Any],
    vector: list[float],
    seen_vectors: list[list[float]],
    scores: list[float],
    acquisition: str,
    kappa: float,
    xi: float,
    exploration_weight: float,
    exploitation_weight: float,
) -> float:
    mean = _candidate_proxy(candidate)
    uncertainty = _uncertainty(vector, seen_vectors)
    best = max(scores) if scores else mean
    improvement = mean - best - xi
    if acquisition == "upper_confidence_bound":
        return mean + kappa * uncertainty
    if acquisition == "probability_of_improvement":
        return 1.0 if improvement > 0 else max(0.0, mean - best + xi)
    if acquisition == "uncertainty_sampling":
        return uncertainty
    if acquisition == "exploitation":
        return mean
    if acquisition == "exploration":
        return uncertainty + 0.1 * mean
    # expected_improvement fallback
    return max(0.0, improvement) * exploitation_weight + uncertainty * exploration_weight


def _evaluate_candidate(
    *,
    base_request: dict[str, Any],
    candidate_parameters: dict[str, Any],
    index: int,
    evaluator: Evaluator | None,
) -> dict[str, Any]:
    request = dict(base_request)
    candidate = dict(request.get("candidate", {})) if isinstance(request.get("candidate"), dict) else {}
    existing_parameters = dict(candidate.get("parameters", {})) if isinstance(candidate.get("parameters"), dict) else {}
    candidate["parameters"] = {**existing_parameters, **candidate_parameters}
    candidate["candidate_id"] = candidate.get("candidate_id") or f"bench-candidate-{index:03d}"
    request["candidate"] = candidate
    if evaluator:
        result = evaluator(request)
    else:
        result = evaluate_experiment(request)
    if isinstance(result, dict):
        result.setdefault("parameters", dict(candidate_parameters))
    return result


def _bo_landscape(
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
    posterior_scores: list[dict[str, float]] | None = None,
    backend_active: str = "lightweight_pool",
) -> list[dict[str, Any]]:
    """Return per-candidate surrogate/acquisition values for plotting."""
    seen_signatures = {_vector_signature(vector) for vector in evaluated_vectors}
    landscape: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        vector = vectors[index - 1]
        signature = _vector_signature(vector)
        posterior = posterior_scores[index - 1] if posterior_scores and index - 1 < len(posterior_scores) else {}
        if posterior:
            uncertainty = float(posterior.get("uncertainty", 0.0))
            mean = float(posterior.get("surrogate_mean", _candidate_proxy(candidate)))
            acquisition_value = float(posterior.get("acquisition_value", mean))
        else:
            uncertainty = _uncertainty(vector, evaluated_vectors)
            mean = _candidate_proxy(candidate)
            acquisition_value = _acquisition_value(
                candidate=candidate,
                vector=vector,
                seen_vectors=evaluated_vectors,
                scores=scores,
                acquisition=acquisition,
                kappa=kappa,
                xi=xi,
                exploration_weight=exploration_weight,
                exploitation_weight=exploitation_weight,
            )
        landscape.append(
            {
                "candidate_id": str(candidate.get("candidate_id") or f"candidate-{index:03d}"),
                "x": index,
                "surrogate_mean": round(mean, 6),
                "uncertainty": round(uncertainty, 6),
                "acquisition_value": round(acquisition_value, 6),
                "already_evaluated": signature in seen_signatures,
                "backend": backend_active,
                "parameters": _compact_parameters(candidate),
                "vector_signature": list(signature),
            }
        )
    return landscape


def _trace_records_with_x(records: list[dict[str, Any]], landscape: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach candidate-pool x positions to prior/evaluated trace records when possible."""
    by_signature = {
        tuple(item.get("vector_signature", [])): item
        for item in landscape
        if isinstance(item.get("vector_signature"), list)
    }
    out: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        match = by_signature.get(tuple(item.get("vector_signature", [])))
        if match:
            item["x"] = match.get("x")
            item["candidate_id"] = item.get("candidate_id") or match.get("candidate_id")
        else:
            item.setdefault("x", None)
        out.append(item)
    return out


def _curve_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    curve: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    for idx, result in enumerate(results, start=1):
        score = result.get("objective_score")
        score_value = float(score) if isinstance(score, (int, float)) else float("-inf")
        if score_value > best_score:
            best_score = score_value
            best = result
        curve.append(
            {
                "step": idx,
                "score": None if score_value == float("-inf") else round(score_value, 6),
                "best_score": None if best_score == float("-inf") else round(best_score, 6),
                "candidate_id": result.get("candidate_id"),
            }
        )
    return {
        "best_score": None if best_score == float("-inf") else round(best_score, 6),
        "best_candidate_id": best.get("candidate_id") if best else None,
        "best_result": best or {},
        "curve": curve,
    }


def run_benchmark(
    payload: dict[str, Any],
    *,
    evaluator: Evaluator | None = None,
) -> dict[str, Any]:
    """Run deterministic random/grid/bo comparison over a virtual or supplied evaluator."""
    parameter_space = payload.get("parameter_space") if isinstance(payload.get("parameter_space"), dict) else {}
    if not parameter_space:
        parameter_space = {
            "relative_density": [0.18, 0.48],
            "wall_thickness_mm": [1.2, 2.4],
            "cell_size_mm": [5.0, 10.0],
            "geometry_type": ["gyroid"],
        }
    budget = max(1, int(payload.get("budget", 6)))
    strategies = payload.get("strategies") if isinstance(payload.get("strategies"), list) else ["random", "grid", "bo"]
    seed = int(payload.get("seed", 7))
    metadata = (
        payload.get("request", {}).get("metadata", {})
        if isinstance(payload.get("request"), dict) and isinstance(payload.get("request", {}).get("metadata"), dict)
        else {}
    )
    acquisition = str(payload.get("acquisition") or metadata.get("acquisition") or "expected_improvement").strip().lower()
    bo_backend = str(payload.get("bo_backend") or payload.get("backend") or metadata.get("bo_backend") or "lightweight_pool").strip().lower()
    backend_warnings: list[str] = []
    if bo_backend not in {"lightweight_pool", "botorch_optional"}:
        backend_warnings.append(f"unknown bo_backend '{bo_backend}' fell back to lightweight_pool")
        bo_backend = "lightweight_pool"
    kappa = float(payload.get("kappa", metadata.get("kappa", 2.0)) or 2.0)
    xi = float(payload.get("xi", metadata.get("xi", 0.01)) or 0.01)
    exploration_weight = float(payload.get("exploration_weight", metadata.get("exploration_weight", 0.35)) or 0.35)
    exploitation_weight = float(payload.get("exploitation_weight", metadata.get("exploitation_weight", 0.65)) or 0.65)
    base_request = dict(payload.get("request", {})) if isinstance(payload.get("request"), dict) else {}
    base_request.setdefault("objective", payload.get("objective", {}))
    base_request.setdefault("execution", {"mode": "virtual", "bridge": "virtual"})

    grid_pool = _grid_candidates(parameter_space, max(budget * 6, budget))
    parameter_keys = list(parameter_space)
    prior_vectors, prior_scores, prior_records = _prior_points(payload, parameter_keys)
    output: dict[str, Any] = {
        "ok": True,
        "tool": "experiment.benchmark",
        "budget": budget,
        "strategies": {},
        "parameter_space": parameter_space,
        "bo_backend_requested": bo_backend,
        "backend_warnings": backend_warnings,
    }
    for strategy in strategies:
        name = str(strategy).strip().lower()
        results: list[dict[str, Any]] = []
        if name == "grid":
            candidates = grid_pool[:budget]
            for idx, candidate in enumerate(candidates, start=1):
                results.append(_evaluate_candidate(base_request=base_request, candidate_parameters=candidate, index=idx, evaluator=evaluator))
        elif name == "bo":
            candidates = list(grid_pool)
            vectors = [_numeric_vector(candidate, parameter_keys) for candidate in candidates]
            seen: set[int] = set()
            scores: list[float] = list(prior_scores)
            evaluated_vectors: list[list[float]] = list(prior_vectors)
            evaluated_records: list[dict[str, Any]] = [dict(item) for item in prior_records]
            surrogate_trace: list[dict[str, Any]] = []
            backend_warning_reported = False
            backend_used = "lightweight_pool"
            for idx in range(min(budget, len(candidates))):
                available_indexes = [i for i in range(len(vectors)) if i not in seen]
                if not available_indexes:
                    break
                posterior_scores = None
                active_backend = "lightweight_pool"
                if bo_backend == "botorch_optional" and len(evaluated_vectors) >= 2 and len(scores) >= 2:
                    try:
                        posterior_scores = score_botorch_candidate_pool(
                            candidates=candidates,
                            vectors=vectors,
                            evaluated_vectors=evaluated_vectors,
                            scores=scores,
                            acquisition=acquisition,
                            kappa=kappa,
                            xi=xi,
                            exploration_weight=exploration_weight,
                            exploitation_weight=exploitation_weight,
                        )
                        active_backend = "botorch_optional"
                        backend_used = "botorch_optional"
                    except (BoTorchBackendUnavailable, Exception) as exc:
                        if not backend_warning_reported:
                            backend_warnings.append(f"botorch_optional unavailable; lightweight_pool used: {exc.__class__.__name__}: {exc}")
                            backend_warning_reported = True
                landscape = _bo_landscape(
                    candidates=candidates,
                    vectors=vectors,
                    evaluated_vectors=evaluated_vectors,
                    scores=scores,
                    acquisition=acquisition,
                    kappa=kappa,
                    xi=xi,
                    exploration_weight=exploration_weight,
                    exploitation_weight=exploitation_weight,
                    posterior_scores=posterior_scores,
                    backend_active=active_backend,
                )
                if not scores:
                    pick = 0
                else:
                    _ = propose_next(evaluated_vectors, scores)
                    pick = max(
                        available_indexes,
                        key=lambda item: _acquisition_value(
                            candidate=candidates[item],
                            vector=vectors[item],
                            seen_vectors=evaluated_vectors,
                            scores=scores,
                            acquisition=acquisition,
                            kappa=kappa,
                            xi=xi,
                            exploration_weight=exploration_weight,
                            exploitation_weight=exploitation_weight,
                        ),
                    )
                    if posterior_scores:
                        pick = max(available_indexes, key=lambda item: landscape[item].get("acquisition_value", float("-inf")))
                seen.add(pick)
                result = _evaluate_candidate(
                    base_request=base_request,
                    candidate_parameters=candidates[pick],
                    index=idx + 1,
                    evaluator=evaluator,
                )
                results.append(result)
                score = result.get("objective_score")
                score_value = float(score) if isinstance(score, (int, float)) else float("-inf")
                selected_trace = dict(landscape[pick])
                selected_trace["score"] = None if score_value == float("-inf") else round(score_value, 6)
                selected_trace["candidate_id"] = str(result.get("candidate_id") or selected_trace.get("candidate_id"))
                observed_records = _trace_records_with_x(
                    [
                        *evaluated_records,
                        {
                            "source": "bo_evaluation",
                            "candidate_id": selected_trace["candidate_id"],
                            "score": selected_trace["score"],
                            "parameters": _compact_parameters(candidates[pick]),
                            "vector_signature": list(_vector_signature(vectors[pick])),
                        },
                    ],
                    landscape,
                )
                surrogate_trace.append(
                    {
                        "step": idx + 1,
                        "acquisition": acquisition,
                        "x_axis": "candidate_pool_index",
                        "candidate_count": len(candidates),
                        "selected": selected_trace,
                        "backend_requested": bo_backend,
                        "backend_active": active_backend,
                        "evaluated_points": observed_records,
                        "candidates": landscape,
                    }
                )
                scores.append(score_value)
                evaluated_vectors.append(vectors[pick])
                evaluated_records.append(
                    {
                        "source": "bo_evaluation",
                        "candidate_id": selected_trace["candidate_id"],
                        "score": selected_trace["score"],
                        "parameters": _compact_parameters(candidates[pick]),
                        "vector_signature": list(_vector_signature(vectors[pick])),
                    }
                )
        else:
            candidates = _random_candidates(parameter_space, budget, seed=seed)
            for idx, candidate in enumerate(candidates, start=1):
                results.append(_evaluate_candidate(base_request=base_request, candidate_parameters=candidate, index=idx, evaluator=evaluator))
        payload = {"results": results, **_curve_summary(results)}
        if name == "bo":
            payload["surrogate_trace"] = surrogate_trace
            payload["backend_requested"] = bo_backend
            payload["backend_active"] = backend_used
            payload["backend_warnings"] = list(backend_warnings)
        output["strategies"][name] = payload
    return output
