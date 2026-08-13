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
import math
import random
from collections.abc import Callable
from typing import Any

from experiments.api import evaluate_experiment
from experiments.bo_visualization import build_bo_visualization
from experiments.lhs_design_visualization import build_lhs_design_visualization
from experiments.schemas import ExperimentEvaluationRequest
from learning.bo_engine import propose_next as propose_lightweight_next
from learning.bo_parameter_space import BOParameterSpace
from learning.botorch_backend import (
    BoTorchBackendError,
    propose_next as propose_botorch_next,
)

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
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        score_value = float(score)
        if not math.isfinite(score_value):
            continue
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


def _botorch_observations(payload: dict[str, Any], space: BOParameterSpace) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    raw = payload.get("prior_evaluations") if isinstance(payload.get("prior_evaluations"), list) else []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("parameters"), dict):
            continue
        if item.get("ok_for_bo") is False or str(item.get("source") or "").startswith("failed:"):
            continue
        score = item.get("score", item.get("objective_score"))
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            continue
        try:
            space.encode(item["parameters"])
        except (TypeError, ValueError):
            continue
        observation = {
            "candidate_id": str(item.get("candidate_id") or f"prior-{index + 1}"),
            "source": str(item.get("source") or "prior"),
            "parameters": dict(item["parameters"]),
            "score": float(score),
        }
        uncertainty = item.get("uncertainty")
        if isinstance(uncertainty, (int, float)) and not isinstance(uncertainty, bool) and float(uncertainty) > 0:
            observation["uncertainty"] = float(uncertainty)
        observations.append(observation)
    return observations


def _observation_trace(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": str(item.get("source") or "bo_evaluation"),
            "candidate_id": str(item.get("candidate_id") or ""),
            "score": round(float(item["score"]), 8),
            "parameters": _compact_parameters(item.get("parameters", {})),
        }
        for item in observations
        if isinstance(item.get("score"), (int, float)) and isinstance(item.get("parameters"), dict)
    ]


def _projection_landscape(proposal: dict[str, Any], *, candidate_id: str) -> list[dict[str, Any]]:
    projection = proposal.get("projection") if isinstance(proposal.get("projection"), dict) else {}
    parameter = str(projection.get("parameter") or "")
    xs = projection.get("x") if isinstance(projection.get("x"), list) else []
    means = projection.get("mean") if isinstance(projection.get("mean"), list) else []
    stds = projection.get("std") if isinstance(projection.get("std"), list) else []
    acquisitions = projection.get("acquisition") if isinstance(projection.get("acquisition"), list) else []
    base = proposal.get("candidate") if isinstance(proposal.get("candidate"), dict) else {}
    rows: list[dict[str, Any]] = []
    for index, (x_value, mean, std, acq) in enumerate(zip(xs, means, stds, acquisitions, strict=False), start=1):
        parameters = dict(base)
        if parameter:
            parameters[parameter] = x_value
        rows.append(
            {
                "candidate_id": f"posterior-{index:03d}",
                "x": index,
                "surrogate_mean": float(mean),
                "uncertainty": max(0.0, float(std)),
                "acquisition_value": float(acq),
                "already_evaluated": False,
                "backend": "botorch",
                "parameters": _compact_parameters(parameters),
            }
        )
    if rows:
        nearest = min(
            rows,
            key=lambda item: abs(float(item.get("parameters", {}).get(parameter, 0.0)) - float(base.get(parameter, 0.0))),
        )
        nearest["candidate_id"] = candidate_id
    return rows


def _run_botorch_strategy(
    *,
    payload: dict[str, Any],
    parameter_space: dict[str, Any],
    base_request: dict[str, Any],
    budget: int,
    seed: int,
    acquisition: str,
    kappa: float,
    evaluator: Evaluator | None,
) -> dict[str, Any]:
    """Run a synthetic multi-step benchmark or one closed-loop BO proposal."""
    space = BOParameterSpace.from_mapping(parameter_space)
    observations = _botorch_observations(payload, space)
    raw_initial_size = payload.get("initial_design_size", "auto")
    try:
        initial_target = space.initial_design_size if raw_initial_size in {None, "", "auto"} else max(2, int(raw_initial_size))
    except (TypeError, ValueError):
        initial_target = space.initial_design_size
    iterations = 1 if bool(payload.get("sequential_only")) else budget
    sequential_only = bool(payload.get("sequential_only"))
    objective = payload.get("objective") if isinstance(payload.get("objective"), dict) else {}
    direction = str(objective.get("direction") or "maximize").strip().lower()
    results: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    backend_active = "lhs"
    failure: dict[str, Any] = {}
    planned_lhs = space.lhs_points(initial_target, seed=seed)

    for step in range(iterations):
        observation_count_before = len(observations)
        next_experiment_step = observation_count_before + 1
        candidate_id = f"bo-candidate-{next_experiment_step:03d}"
        if len(observations) < initial_target:
            excluded = {space.signature(item["parameters"]) for item in observations}
            lhs_candidates = [item for item in planned_lhs if space.signature(item) not in excluded]
            if not lhs_candidates:
                raise RuntimeError("canonical LHS plan has no unobserved point before initialization completed")
            candidate = lhs_candidates[0]
            phase = "initial_design"
            backend_active = "lhs"
            candidate_rows = []
            for index, item in enumerate(lhs_candidates, start=1):
                candidate_rows.append(
                    {
                        "candidate_id": candidate_id if index == 1 else f"lhs-candidate-{len(observations) + index:03d}",
                        "x": index,
                        "surrogate_mean": round(_candidate_proxy(item), 8),
                        "uncertainty": 1.0,
                        "acquisition_value": 1.0,
                        "already_evaluated": False,
                        "backend": "lhs",
                        "parameters": _compact_parameters(item),
                    }
                )
            selected = dict(candidate_rows[0])
            model_payload: dict[str, Any] = {}
            optimizer_payload: dict[str, Any] = {"function": "latin_hypercube"}
            acquisition_class = "LatinHypercube"
            projection_payload: dict[str, Any] = {}
        else:
            phase = "acquisition"
            try:
                proposal = propose_botorch_next(
                    parameter_space=space,
                    observations=observations,
                    acquisition=acquisition,
                    objective_direction=direction,
                    random_seed=seed + step,
                    kappa=kappa,
                    num_restarts=int(payload.get("num_restarts", 12) or 12),
                    raw_samples=int(payload.get("raw_samples", 256) or 256),
                    optimizer_timeout_s=float(payload.get("optimizer_timeout_s", 30.0) or 30.0),
                ).to_dict()
            except BoTorchBackendError as exc:
                failure = exc.to_dict()
                break
            candidate = dict(proposal["candidate"])
            backend_active = "botorch"
            posterior = proposal.get("posterior") if isinstance(proposal.get("posterior"), dict) else {}
            selected = {
                "candidate_id": candidate_id,
                "parameters": _compact_parameters(candidate),
                "surrogate_mean": posterior.get("mean"),
                "uncertainty": posterior.get("std"),
                "acquisition_value": (proposal.get("acquisition") or {}).get("value"),
                "backend": "botorch",
                "score": None,
            }
            # Conditional projection grids are visualization-only. The decision
            # path must preserve the exact mixed-space point optimized by BoTorch.
            candidate_rows = [selected]
            model_payload = dict(proposal.get("model") or {})
            optimizer_payload = dict(proposal.get("optimizer") or {})
            acquisition_class = str((proposal.get("acquisition") or {}).get("class") or acquisition)
            projection_payload = dict(proposal.get("projection") or {})

        if sequential_only:
            result = {
                "ok": True,
                "status": "proposed",
                "candidate_id": candidate_id,
                "parameters": dict(candidate),
                "objective_score": None,
                "evaluation_deferred": True,
            }
        else:
            result = _evaluate_candidate(
                base_request=base_request,
                candidate_parameters=candidate,
                index=step + 1,
                evaluator=evaluator,
            )
            result["candidate_id"] = candidate_id
        results.append(result)
        score = result.get("objective_score")
        if not sequential_only and isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(float(score)):
            observation = {
                "candidate_id": candidate_id,
                "source": "bo_evaluation",
                "parameters": dict(candidate),
                "score": float(score),
            }
            uncertainty = result.get("uncertainty")
            if (
                isinstance(uncertainty, (int, float))
                and not isinstance(uncertainty, bool)
                and math.isfinite(float(uncertainty))
                and float(uncertainty) > 0.0
            ):
                observation["uncertainty"] = float(uncertainty)
            observations.append(observation)
        selected["score"] = float(score) if not sequential_only and isinstance(score, (int, float)) else None
        observed_signatures = {space.signature(item["parameters"]) for item in observations}
        selected_signature = space.signature(candidate)
        next_signature = selected_signature if selected_signature not in observed_signatures else next(
            (space.signature(item) for item in planned_lhs if space.signature(item) not in observed_signatures),
            "",
        )
        initial_points = []
        for point_index, point in enumerate(planned_lhs, start=1):
            signature = space.signature(point)
            status = "measured" if signature in observed_signatures else ("next" if signature == next_signature else "planned")
            initial_points.append(
                {
                    "index": point_index,
                    "candidate_id": f"lhs-candidate-{point_index:03d}",
                    "status": status,
                    "parameters": _compact_parameters(point),
                }
            )
        if sequential_only and phase == "acquisition":
            model_step = observation_count_before
        else:
            model_step = next_experiment_step
        trace = {
            "step": model_step,
            "next_experiment_step": next_experiment_step,
            "phase": phase,
            "acquisition": acquisition,
            "acquisition_class": acquisition_class,
            "x_axis": "parameter_slice" if phase == "acquisition" else "lhs_design_index",
            "candidate_count": len(candidate_rows),
            "selected": selected,
            "backend_requested": "botorch",
            "backend_active": backend_active,
            "initial_design": {
                "sampler": "latin_hypercube",
                "target": initial_target,
                "completed": min(len(observations), initial_target),
                "seed": seed,
                "points": initial_points,
            },
            "model": model_payload,
            "optimizer": optimizer_payload,
            "projection": projection_payload,
            "evaluated_points": _observation_trace(observations),
            "candidates": candidate_rows,
        }
        selected_parameter = ""
        if phase == "acquisition" and proposal.get("projection"):
            selected_parameter = str(proposal["projection"].get("parameter") or "")
        if phase == "initial_design" and "cell_size_mm" in parameter_space and "relative_density" in parameter_space:
            trace["lhs_visualization"] = build_lhs_design_visualization(
                run_id=str(base_request.get("run_id") or ""),
                parameter_space=parameter_space,
                trace=trace,
            )
        else:
            trace["visualization"] = build_bo_visualization(
                run_id=str(base_request.get("run_id") or ""),
                objective=objective,
                parameter_space=parameter_space,
                trace=trace,
                selected_parameter=selected_parameter,
            )
        traces.append(trace)

    summary = {"results": results, **_curve_summary(results)}
    summary.update(
        {
            "ok": not bool(failure),
            "surrogate_trace": traces,
            "backend_requested": "botorch",
            "backend_active": backend_active if not failure else "none",
            "backend_warnings": [],
            "failure": failure,
            "initial_design": {
                "sampler": "latin_hypercube",
                "target": initial_target,
                "completed": min(len(observations), initial_target),
            },
        }
    )
    return summary


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
    bo_backend = str(payload.get("bo_backend") or payload.get("backend") or metadata.get("bo_backend") or "botorch").strip().lower()
    backend_warnings: list[str] = []
    if bo_backend == "botorch_optional":
        bo_backend = "botorch"
    if bo_backend not in {"lightweight_pool", "botorch"}:
        return {
            "ok": False,
            "tool": "experiment.benchmark",
            "budget": budget,
            "strategies": {},
            "parameter_space": parameter_space,
            "bo_backend_requested": bo_backend,
            "backend_warnings": [],
            "failure": {
                "failure_code": "BO_BACKEND_UNSUPPORTED",
                "message": f"unsupported BO backend: {bo_backend}",
            },
        }
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
            if bo_backend == "botorch":
                botorch_payload = _run_botorch_strategy(
                    payload=payload,
                    parameter_space=parameter_space,
                    base_request=base_request,
                    budget=budget,
                    seed=seed,
                    acquisition=acquisition,
                    kappa=kappa,
                    evaluator=evaluator,
                )
                output["strategies"][name] = botorch_payload
                if not botorch_payload.get("ok", False):
                    output["ok"] = False
                    output["failure"] = botorch_payload.get("failure", {})
                continue
            candidates = list(grid_pool)
            vectors = [_numeric_vector(candidate, parameter_keys) for candidate in candidates]
            seen: set[int] = set()
            scores: list[float] = list(prior_scores)
            evaluated_vectors: list[list[float]] = list(prior_vectors)
            evaluated_records: list[dict[str, Any]] = [dict(item) for item in prior_records]
            surrogate_trace: list[dict[str, Any]] = []
            backend_used = "lightweight_pool"
            for idx in range(min(budget, len(candidates))):
                available_indexes = [i for i in range(len(vectors)) if i not in seen]
                if not available_indexes:
                    break
                posterior_scores = None
                active_backend = "lightweight_pool"
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
                    _ = propose_lightweight_next(evaluated_vectors, scores)
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
                trace_item = {
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
                trace_item["visualization"] = build_bo_visualization(
                    run_id=str(base_request.get("run_id") or ""),
                    objective=payload.get("objective") if isinstance(payload.get("objective"), dict) else {},
                    parameter_space=parameter_space,
                    trace=trace_item,
                    selected_parameter=str(payload.get("visualization_parameter") or ""),
                )
                surrogate_trace.append(trace_item)
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
