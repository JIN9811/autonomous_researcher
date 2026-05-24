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
        if len(candidates) >= budget:
            break
    return candidates


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


def _numeric_vector(candidate: dict[str, Any]) -> list[float]:
    vector: list[float] = []
    for value in candidate.values():
        if isinstance(value, (int, float)):
            vector.append(float(value))
        else:
            vector.append(float(abs(hash(str(value))) % 1000) / 1000.0)
    return vector


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
        return evaluator(request)
    return evaluate_experiment(request)


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
    base_request = dict(payload.get("request", {})) if isinstance(payload.get("request"), dict) else {}
    base_request.setdefault("objective", payload.get("objective", {}))
    base_request.setdefault("execution", {"mode": "virtual", "bridge": "virtual"})

    grid_pool = _grid_candidates(parameter_space, max(budget * 3, budget))
    output: dict[str, Any] = {
        "ok": True,
        "tool": "experiment.benchmark",
        "budget": budget,
        "strategies": {},
        "parameter_space": parameter_space,
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
            vectors = [_numeric_vector(candidate) for candidate in candidates]
            seen: set[int] = set()
            scores: list[float] = []
            evaluated_vectors: list[list[float]] = []
            for idx in range(min(budget, len(candidates))):
                if not scores:
                    pick = 0
                else:
                    available_indexes = [i for i in range(len(vectors)) if i not in seen]
                    best_seen = propose_next(evaluated_vectors, scores)
                    anchor = evaluated_vectors[min(best_seen, len(evaluated_vectors) - 1)]
                    pick = min(
                        available_indexes,
                        key=lambda item: sum(abs(a - b) for a, b in zip(vectors[item], anchor, strict=False)),
                    )
                seen.add(pick)
                result = _evaluate_candidate(
                    base_request=base_request,
                    candidate_parameters=candidates[pick],
                    index=idx + 1,
                    evaluator=evaluator,
                )
                results.append(result)
                score = result.get("objective_score")
                scores.append(float(score) if isinstance(score, (int, float)) else float("-inf"))
                evaluated_vectors.append(vectors[pick])
        else:
            candidates = _random_candidates(parameter_space, budget, seed=seed)
            for idx, candidate in enumerate(candidates, start=1):
                results.append(_evaluate_candidate(base_request=base_request, candidate_parameters=candidate, index=idx, evaluator=evaluator))
        output["strategies"][name] = {"results": results, **_curve_summary(results)}
    return output
