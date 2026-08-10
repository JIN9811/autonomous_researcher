"""
File purpose:
- Bayesian Optimization advisory agent for Autonomous Experiment Runtime candidates.

Key classes/functions:
- BOAgent

Inputs/outputs:
- Input: OrchestratorState, optional BO settings from GUI/API
- Output: AgentResult.data["bo_result"] with benchmark curves, reasoning, candidate ranking, and recommendation

Dependencies:
- experiments.benchmark
- agents.base_agent

Modification guide:
- Safe places to edit: supported acquisition settings and default parameter space
- Risky places to edit: bo_result schema consumed by GUI/API/tests
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState


class BOAgent(BaseAgent):
    """Advisory BO/MBO agent that proposes next design constraints without touching hardware."""

    name = "bo_agent"

    SUPPORTED_STRATEGIES = (
        "random",
        "grid",
        "bo",
        "mbo",
        "llm_warmstart",
        "llm_preference_bo",
        "safe_constrained_bo",
        "multi_objective_pareto",
        "multi_fidelity_bo",
    )
    BENCHMARK_STRATEGY_MAP = {
        "llm_warmstart": "bo",
        "llm_preference_bo": "bo",
        "safe_constrained_bo": "bo",
        "multi_objective_pareto": "bo",
        "multi_fidelity_bo": "bo",
    }
    SUPPORTED_ACQUISITIONS = (
        "expected_improvement",
        "upper_confidence_bound",
        "probability_of_improvement",
        "uncertainty_sampling",
        "exploitation",
        "exploration",
    )
    DEFAULT_PARAMETER_SPACE: dict[str, Any] = {
        "geometry_type": ["gyroid"],
        "relative_density": [0.20, 0.48],
        "wall_thickness_mm": [1.2, 2.0],
        "cell_size_mm": [5.0, 10.0],
        "tpms_thickness": [0.28, 0.52],
        "orientation_deg": [0, 15, 30, 45, 60, 90],
        "anisotropy_ratio": [0.85, 1.0, 1.25],
        "skin_thickness_mm": [0.0, 0.8],
        "bottom_cap_enabled": [True],
        "top_cap_enabled": [False],
        "skirt_enabled": [False],
    }
    SHAPE_PARAMETER_KEYS = (
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

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        """Return GUI/API defaults."""
        return {
            "strategy": "bo",
            "acquisition": "expected_improvement",
            "budget": 8,
            "random_seed": 7,
            "kappa": 2.0,
            "xi": 0.01,
            "exploration_weight": 0.35,
            "exploitation_weight": 0.65,
            "llm_preference_enabled": True,
            "llm_candidate_weight": "auto",
            "top_k": 5,
            "bo_backend": "lightweight_pool",
            "supported_bo_backends": ["lightweight_pool", "botorch_optional"],
            "parameter_space": dict(cls.DEFAULT_PARAMETER_SPACE),
            "supported_strategies": list(cls.SUPPORTED_STRATEGIES),
            "supported_acquisitions": list(cls.SUPPORTED_ACQUISITIONS),
        }

    @classmethod
    def normalize_settings(cls, raw: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
        """Normalize operator-supplied BO settings with safe fallbacks."""
        raw = raw if isinstance(raw, dict) else {}
        warnings: list[str] = []
        defaults = cls.defaults()
        strategy = str(raw.get("strategy") or defaults["strategy"]).strip().lower()
        if strategy not in cls.SUPPORTED_STRATEGIES:
            warnings.append(f"unknown strategy '{strategy}' fell back to bo")
            strategy = "bo"
        acquisition = str(raw.get("acquisition") or defaults["acquisition"]).strip().lower()
        if acquisition not in cls.SUPPORTED_ACQUISITIONS:
            warnings.append(f"unknown acquisition '{acquisition}' fell back to expected_improvement")
            acquisition = "expected_improvement"
        try:
            budget = max(1, int(raw.get("budget", defaults["budget"])))
        except (TypeError, ValueError):
            warnings.append("invalid budget fell back to 8")
            budget = int(defaults["budget"])
        try:
            random_seed = int(raw.get("random_seed", raw.get("seed", defaults["random_seed"])))
        except (TypeError, ValueError):
            warnings.append("invalid random_seed fell back to 7")
            random_seed = int(defaults["random_seed"])
        parameter_space = raw.get("parameter_space") if isinstance(raw.get("parameter_space"), dict) else {}
        if not parameter_space:
            parameter_space = dict(defaults["parameter_space"])
        top_k = int(max(1, min(cls._float_setting(raw, "top_k", defaults["top_k"], warnings), 12)))
        bo_backend = str(raw.get("bo_backend") or raw.get("backend") or defaults["bo_backend"]).strip().lower()
        if bo_backend not in set(defaults["supported_bo_backends"]):
            warnings.append(f"unknown bo_backend '{bo_backend}' fell back to lightweight_pool")
            bo_backend = "lightweight_pool"
        return (
            {
                "strategy": strategy,
                "benchmark_strategy": cls.BENCHMARK_STRATEGY_MAP.get(strategy, strategy),
                "acquisition": acquisition,
                "budget": budget,
                "random_seed": random_seed,
                "kappa": cls._float_setting(raw, "kappa", defaults["kappa"], warnings),
                "xi": cls._float_setting(raw, "xi", defaults["xi"], warnings),
                "exploration_weight": cls._float_setting(
                    raw,
                    "exploration_weight",
                    defaults["exploration_weight"],
                    warnings,
                ),
                "exploitation_weight": cls._float_setting(
                    raw,
                    "exploitation_weight",
                    defaults["exploitation_weight"],
                    warnings,
                ),
                "llm_preference_enabled": cls._bool_setting(raw, "llm_preference_enabled", bool(defaults["llm_preference_enabled"])),
                "llm_candidate_weight": raw.get("llm_candidate_weight", defaults["llm_candidate_weight"]),
                "top_k": top_k,
                "bo_backend": bo_backend,
                "parameter_space": parameter_space,
            },
            warnings,
        )

    @staticmethod
    def _float_setting(raw: dict[str, Any], key: str, default: float, warnings: list[str]) -> float:
        try:
            return float(raw.get(key, default))
        except (TypeError, ValueError):
            warnings.append(f"invalid {key} fell back to {default}")
            return float(default)

    @staticmethod
    def _bool_setting(raw: dict[str, Any], key: str, default: bool) -> bool:
        value = raw.get(key, default)
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "off", "disabled"}:
            return False
        return default

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if math.isfinite(parsed) else default

    @staticmethod
    def _locked_cell_size_from_state(state: OrchestratorState) -> float | None:
        """Return the current design cell size that BO must not mutate between cycles."""
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        constraints = spec.get("constraints") if isinstance(spec.get("constraints"), dict) else {}
        for source in (spec, constraints):
            if not isinstance(source, dict) or source.get("cell_size_mm") in (None, "", []):
                continue
            try:
                value = float(source["cell_size_mm"])
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return None

    @staticmethod
    def _lock_parameter_space(parameter_space: dict[str, Any], *, cell_size_mm: float | None) -> dict[str, Any]:
        """Keep operator-defined non-BO dimensions fixed while preserving GUI schema."""
        locked = dict(parameter_space)
        density_space = locked.get("relative_density")
        if isinstance(density_space, list) and len(density_space) == 2 and all(isinstance(item, (int, float)) for item in density_space):
            locked["relative_density"] = [max(0.20, float(density_space[0])), max(0.20, float(density_space[1]))]
        elif isinstance(density_space, list):
            filtered = [item for item in density_space if isinstance(item, (int, float)) and float(item) >= 0.20]
            locked["relative_density"] = filtered or [0.20]
        elif density_space is not None:
            try:
                locked["relative_density"] = max(0.20, float(density_space))
            except (TypeError, ValueError):
                locked["relative_density"] = [0.20, 0.48]
        if cell_size_mm is not None:
            locked["cell_size_mm"] = [float(cell_size_mm)]
        return locked

    @staticmethod
    def _apply_locked_parameters(parameters: dict[str, Any], *, cell_size_mm: float | None) -> dict[str, Any]:
        """Sanitize BO recommendations before they become next-cycle constraints."""
        sanitized = dict(parameters)
        geometry = str(sanitized.get("geometry_type") or sanitized.get("preferred_geometry_type") or "gyroid").strip().lower()
        if geometry == "gyroid":
            try:
                density = float(sanitized.get("relative_density", 0.32))
            except (TypeError, ValueError):
                density = 0.32
            sanitized["relative_density"] = max(0.20, density)
        if cell_size_mm is not None:
            sanitized["cell_size_mm"] = float(cell_size_mm)
        return sanitized

    @staticmethod
    def _objective_from_state(state: OrchestratorState, payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("objective") if isinstance(payload.get("objective"), dict) else {}
        current = state.current_experiment_objective if isinstance(state.current_experiment_objective, dict) else {}
        constraints = state.current_experiment_spec.get("constraints") if isinstance(state.current_experiment_spec, dict) else {}
        if not isinstance(constraints, dict):
            constraints = {}
        objective = {
            "objective_id": raw.get("objective_id") or current.get("objective_id") or "bo-specimen-objective",
            "objective_version": raw.get("objective_version") or raw.get("version") or current.get("objective_version") or current.get("version"),
            "objective_hash": raw.get("objective_hash") or current.get("objective_hash") or "",
            "name": raw.get("name") or current.get("name") or "Specimen printability and performance proxy",
            "description": raw.get("description") or current.get("description") or state.active_goal,
            "metric_name": raw.get("metric_name") or current.get("metric_name") or "objective_score",
            "direction": raw.get("direction") or current.get("direction") or "maximize",
            "constraints": {**constraints, **(raw.get("constraints") if isinstance(raw.get("constraints"), dict) else {})},
            "tags": raw.get("tags") if isinstance(raw.get("tags"), list) else ["bo", "specimen", "tpms"],
        }
        return objective

    @staticmethod
    def _active_binding_from_context(state: OrchestratorState, ctx: AgentContext) -> dict[str, Any]:
        tools = getattr(ctx, "tools", None)
        resource = getattr(tools, "resource", None)
        service = resource("objective.service") if callable(resource) else None
        if service is None:
            return {}
        status = service.status(run_id=state.run_id)
        binding = status.get("active_binding") if isinstance(status, dict) else None
        return dict(binding) if isinstance(binding, dict) else {}

    @staticmethod
    def objective_observations(
        records: list[dict[str, Any]],
        *,
        objective_hash: str,
        mode: Mode,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Select only finite, traceable observations for one immutable objective."""
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for index, record in enumerate(records):
            observation_id = str(record.get("observation_id") or record.get("candidate_id") or f"observation-{index + 1}")

            def reject(reason: str) -> None:
                rejected.append({"observation_id": observation_id, "reason": reason})

            if str(record.get("objective_hash") or "") != objective_hash:
                reject("objective_hash_mismatch")
                continue
            score = record.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                reject("finite_score_required")
                continue
            if record.get("feasible") is not True:
                reject("infeasible")
                continue
            fidelity = str(record.get("fidelity") or "").strip().lower()
            if not fidelity:
                reject("fidelity_required")
                continue
            if mode == Mode.LIVE and fidelity != "measured":
                reject("synthetic_live_proxy")
                continue
            if fidelity not in {"measured", "synthetic", "simulation"}:
                reject("unsupported_fidelity")
                continue
            if not isinstance(record.get("parameters"), dict) or not record["parameters"]:
                reject("parameters_required")
                continue
            provenance = record.get("provenance_refs")
            if not isinstance(provenance, list) or not any(str(item).strip() for item in provenance):
                reject("provenance_required")
                continue
            if record.get("ok_for_bo") is not True:
                reject("quality_gate_blocked")
                continue
            accepted.append(dict(record))
        return accepted, rejected

    @staticmethod
    def _best_strategy(benchmark: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        strategies = benchmark.get("strategies") if isinstance(benchmark.get("strategies"), dict) else {}
        best_name = ""
        best_payload: dict[str, Any] = {}
        best_score = float("-inf")
        for name, payload in strategies.items():
            if not isinstance(payload, dict):
                continue
            score = payload.get("best_score")
            value = float(score) if isinstance(score, (int, float)) else float("-inf")
            if value > best_score:
                best_name = str(name)
                best_payload = payload
                best_score = value
        return best_name, best_payload

    @staticmethod
    def _parameters_from_result(result: dict[str, Any]) -> dict[str, Any]:
        bridge_result = result.get("bridge_result") if isinstance(result.get("bridge_result"), dict) else {}
        candidate = bridge_result.get("candidate") if isinstance(bridge_result.get("candidate"), dict) else {}
        params = result.get("parameters") if isinstance(result.get("parameters"), dict) else {}
        if params:
            return params
        if isinstance(candidate.get("parameters"), dict):
            return dict(candidate["parameters"])
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        out: dict[str, Any] = {}
        for key in ("geometry_type", "relative_density", "wall_thickness_mm", "cell_size_mm"):
            if key in metrics:
                out[key] = metrics[key]
        return out

    @staticmethod
    def _knowledge_context_from_state(state: OrchestratorState) -> dict[str, Any]:
        """Return compact KnowledgeAgent context for BO/MBO proposal metadata."""
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        knowledge = metadata.get("knowledge") if isinstance(metadata.get("knowledge"), dict) else {}
        if not knowledge:
            return {}
        return {
            "retrieval_coverage": knowledge.get("retrieval_coverage", 0.0),
            "local_chunks": knowledge.get("local_chunks", 0),
            "web_results": knowledge.get("web_results", 0),
            "memory_summary": str(knowledge.get("memory_summary", ""))[:500],
        }

    @classmethod
    def _analysis_handoff_records(cls, state: OrchestratorState) -> list[dict[str, Any]]:
        """Collect Analysis-generated BO handoff records before generic priors."""
        records: list[dict[str, Any]] = []
        candidates: list[Any] = []
        latest_analysis = state.latest_analysis if isinstance(state.latest_analysis, dict) else {}
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        for source in (latest_analysis, metadata.get("analysis") if isinstance(metadata.get("analysis"), dict) else {}, metadata):
            if not isinstance(source, dict):
                continue
            for key in ("bo_handoff", "bo_observation", "experiment_evaluation"):
                if isinstance(source.get(key), dict):
                    candidates.append(source[key])
        for item in candidates:
            if not isinstance(item, dict):
                continue
            params = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
            if not params and isinstance(item.get("metrics"), dict):
                params = {key: item["metrics"].get(key) for key in cls.SHAPE_PARAMETER_KEYS if key in item["metrics"]}
            if not params:
                continue
            objective = item.get("objective") if isinstance(item.get("objective"), dict) else {}
            evaluation = item.get("objective_evaluation") if isinstance(item.get("objective_evaluation"), dict) else {}
            score = evaluation.get("score", item.get("objective_score", objective.get("score")))
            ok_for_bo = item.get("ok_for_bo")
            if ok_for_bo is None:
                ok_for_bo = item.get("ok", True) and str(item.get("status") or "ready") not in {"blocked", "failed"}
            trust_score = item.get("trust_score") if isinstance(item.get("trust_score"), dict) else {}
            trust_gate = str(trust_score.get("gate") or item.get("trust_gate") or "").strip()
            if trust_gate in {"block", "calibrate_only"}:
                ok_for_bo = False
            quality_score_source = trust_score.get("score") if trust_score else (
                (item.get("quality") or {}).get("score") if isinstance(item.get("quality"), dict) else item.get("quality_score")
            )
            record = {
                "source": str(item.get("schema") or item.get("schema_version") or "analysis_handoff"),
                "candidate_id": str(item.get("candidate_id") or item.get("specimen_id") or state.experiment_id),
                "observation_id": str(evaluation.get("observation_id") or item.get("observation_id") or item.get("evaluation_id") or ""),
                "parameters": dict(params),
                "objective_id": str(evaluation.get("objective_id") or objective.get("objective_id") or ""),
                "objective_version": evaluation.get("objective_version") or objective.get("objective_version") or objective.get("version"),
                "objective_hash": str(evaluation.get("objective_hash") or item.get("objective_hash") or objective.get("objective_hash") or ""),
                "feasible": evaluation.get("feasible") if "feasible" in evaluation else item.get("feasible"),
                "fidelity": str(evaluation.get("fidelity") or item.get("fidelity") or ""),
                "provenance_refs": evaluation.get("provenance_refs") if isinstance(evaluation.get("provenance_refs"), list) else item.get("provenance_refs", []),
                "uncertainty": cls._safe_float(item.get("uncertainty", objective.get("uncertainty")), 0.5),
                "quality_score": cls._safe_float(quality_score_source, 0.7),
                "ok_for_bo": bool(ok_for_bo),
                "trust_score": dict(trust_score),
                "trust_gate": trust_gate,
                "multifidelity_comparison": item.get("multifidelity_comparison") if isinstance(item.get("multifidelity_comparison"), dict) else {},
                "fidelity_records": item.get("fidelity_records") if isinstance(item.get("fidelity_records"), dict) else {},
                "failure_tags": item.get("failure_tags") if isinstance(item.get("failure_tags"), list) else [],
                "artifact_refs": item.get("artifact_refs") or item.get("artifacts") or {},
            }
            if not isinstance(score, bool) and isinstance(score, (int, float)) and math.isfinite(float(score)):
                record["score"] = float(score)
            records.append(record)
        return records

    @classmethod
    def _prior_evaluations_from_state(cls, state: OrchestratorState) -> list[dict[str, Any]]:
        """Return compact prior points so BO does not keep recommending the same specimen."""
        priors: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for record in cls._analysis_handoff_records(state):
            observation_id = str(record.get("observation_id") or "").strip()
            key = (
                ("observation", observation_id)
                if observation_id
                else (
                    str(record.get("candidate_id") or ""),
                    json.dumps(record.get("parameters", {}), sort_keys=True, ensure_ascii=True),
                )
            )
            if key in seen:
                continue
            seen.add(key)
            if record.get("ok_for_bo"):
                priors.append(record)
            else:
                priors.append({**record, "source": f"failed:{record.get('source', 'analysis_handoff')}"})

        current = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        if current:
            params = {key: current.get(key) for key in cls.SHAPE_PARAMETER_KEYS if key in current}
            if params:
                priors.append({"source": "current_specimen", "parameters": params, "ok_for_bo": True})
        for item in state.experiment_evaluations:
            if not isinstance(item, dict):
                continue
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            params = {key: metrics.get(key) for key in cls.SHAPE_PARAMETER_KEYS if key in metrics}
            if not params and isinstance(item.get("parameters"), dict):
                params = {key: item["parameters"].get(key) for key in cls.SHAPE_PARAMETER_KEYS if key in item["parameters"]}
            if not params:
                continue
            prior: dict[str, Any] = {
                "source": "analysis_experiment_evaluation" if item.get("source") == "analysis_agent" else "experiment_evaluation",
                "candidate_id": str(item.get("candidate_id") or item.get("evaluation_id") or f"prior-{len(priors) + 1}"),
                "parameters": params,
                "ok_for_bo": bool(item.get("ok", True)) and str(item.get("status") or "") != "analysis_blocked",
                "failure_tags": item.get("failure_tags") if isinstance(item.get("failure_tags"), list) else [],
                "quality_score": cls._safe_float(metrics.get("quality_score"), 0.7),
                "uncertainty": cls._safe_float(item.get("uncertainty"), 0.5),
            }
            evaluation = item.get("objective_evaluation") if isinstance(item.get("objective_evaluation"), dict) else {}
            prior.update(
                {
                    "observation_id": str(evaluation.get("observation_id") or item.get("evaluation_id") or ""),
                    "objective_id": str(evaluation.get("objective_id") or ""),
                    "objective_version": evaluation.get("objective_version"),
                    "objective_hash": str(evaluation.get("objective_hash") or item.get("objective_hash") or ""),
                    "feasible": evaluation.get("feasible") if "feasible" in evaluation else item.get("feasible"),
                    "fidelity": str(evaluation.get("fidelity") or item.get("fidelity") or ""),
                    "provenance_refs": evaluation.get("provenance_refs") if isinstance(evaluation.get("provenance_refs"), list) else item.get("provenance_refs", []),
                }
            )
            score = evaluation.get("score", item.get("objective_score"))
            if not isinstance(score, bool) and isinstance(score, (int, float)) and math.isfinite(float(score)):
                prior["score"] = float(score)
            priors.append(prior)
        return priors

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def _failure_model(cls, priors: list[dict[str, Any]]) -> dict[str, Any]:
        risk_patterns: dict[str, dict[str, Any]] = {}
        forbidden: list[dict[str, str]] = []
        for prior in priors:
            failed = not bool(prior.get("ok_for_bo", True)) or bool(prior.get("failure_tags"))
            if not failed:
                continue
            params = prior.get("parameters") if isinstance(prior.get("parameters"), dict) else {}
            tags = [str(item) for item in prior.get("failure_tags", []) if str(item or "").strip()]
            if not tags:
                tags = ["failed_prior"]
            density = cls._safe_float(params.get("relative_density"), 0.0)
            wall = cls._safe_float(params.get("wall_thickness_mm"), 0.0)
            condition = ""
            if density > 0:
                condition = f"relative_density >= {max(0.20, density - 0.02):.3f}"
            if wall > 0:
                condition = f"{condition} and wall_thickness_mm <= {wall + 0.05:.3f}" if condition else f"wall_thickness_mm <= {wall + 0.05:.3f}"
            key = condition or "failed_prior_region"
            entry = risk_patterns.setdefault(key, {"condition": key, "failure": tags[0], "count": 0, "tags": []})
            entry["count"] += 1
            entry["tags"] = sorted(set(entry.get("tags", []) + tags))
        if risk_patterns:
            forbidden.append({"condition": "relative_density < 0.20", "reason": "FDM continuous-shell lower bound"})
        return {"forbidden_regions": forbidden, "risk_patterns": list(risk_patterns.values())}

    @classmethod
    def _default_reasoning(
        cls,
        *,
        objective: dict[str, Any],
        normalized: dict[str, Any],
        priors: list[dict[str, Any]],
        knowledge_context: dict[str, Any],
        failure_model: dict[str, Any],
    ) -> dict[str, Any]:
        measured = [item for item in priors if item.get("ok_for_bo", True) and isinstance(item.get("score"), (int, float))]
        failed = [item for item in priors if not item.get("ok_for_bo", True) or item.get("failure_tags")]
        best = max(measured, key=lambda item: float(item.get("score", float("-inf"))), default={})
        strategy = normalized.get("strategy", "bo")
        if not measured:
            strategy = "llm_warmstart" if strategy in {"bo", "mbo"} else strategy
        elif failed:
            strategy = "safe_constrained_bo" if strategy in {"bo", "mbo", "llm_preference_bo"} else strategy
        return {
            "schema_version": "bo_reasoning_v1",
            "source": "deterministic_fallback",
            "hypotheses": [
                {
                    "id": "h1",
                    "claim": "Increase relative density and wall thickness cautiously to improve compression response while preserving FDM printability.",
                    "evidence": [
                        f"measured_prior_count={len(measured)}",
                        f"best_candidate={best.get('candidate_id', 'none')}",
                    ],
                    "confidence": 0.58 if measured else 0.42,
                    "testable_by_next_candidate": True,
                }
            ],
            "strategy_recommendation": {
                "strategy": strategy,
                "acquisition": normalized.get("acquisition", "expected_improvement"),
                "exploration_weight": normalized.get("exploration_weight", 0.35),
                "exploitation_weight": normalized.get("exploitation_weight", 0.65),
                "reason": "Use measured evidence first; use LLM as a soft prior and keep numeric acquisition as the decision gate.",
            },
            "search_space_patch": {
                "narrow": {},
                "expand": {},
                "lock": {},
                "forbid": [{"condition": "relative_density < 0.20", "reason": "FDM continuous-shell lower bound"}],
            },
            "preference_regions": [
                {
                    "condition": "relative_density between 0.30 and 0.42 and wall_thickness_mm >= 1.2",
                    "preference_score": 0.65,
                    "reason": "Balanced region for early TPMS compression experiments.",
                }
            ],
            "risk_flags": failed[:5],
            "operator_summary": (
                "BO will rank candidates by numeric acquisition, lightweight LLM preference, and failure-risk penalty. "
                f"Knowledge context available={bool(knowledge_context)}; objective={objective.get('metric_name', 'objective_score')}."
            ),
            "failure_model": failure_model,
        }

    @classmethod
    def _sanitize_reasoning(cls, raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return fallback
        out = dict(fallback)
        out["source"] = "llm" if raw else fallback.get("source", "deterministic_fallback")
        out["schema_version"] = "bo_reasoning_v1"
        if isinstance(raw.get("hypotheses"), list):
            hypotheses = []
            for idx, item in enumerate(raw["hypotheses"][:8], start=1):
                if not isinstance(item, dict):
                    continue
                hypotheses.append(
                    {
                        "id": str(item.get("id") or f"h{idx}"),
                        "claim": str(item.get("claim") or "").strip()[:500],
                        "evidence": [str(v)[:240] for v in item.get("evidence", []) if str(v).strip()][:8] if isinstance(item.get("evidence"), list) else [],
                        "confidence": max(0.0, min(cls._safe_float(item.get("confidence"), 0.5), 1.0)),
                        "testable_by_next_candidate": bool(item.get("testable_by_next_candidate", True)),
                    }
                )
            if hypotheses:
                out["hypotheses"] = hypotheses
        rec = raw.get("strategy_recommendation") if isinstance(raw.get("strategy_recommendation"), dict) else {}
        if rec:
            strategy = str(rec.get("strategy") or fallback.get("strategy_recommendation", {}).get("strategy") or "bo").strip().lower()
            acquisition = str(rec.get("acquisition") or fallback.get("strategy_recommendation", {}).get("acquisition") or "expected_improvement").strip().lower()
            if strategy not in cls.SUPPORTED_STRATEGIES:
                strategy = fallback.get("strategy_recommendation", {}).get("strategy", "bo")
            if acquisition not in cls.SUPPORTED_ACQUISITIONS:
                acquisition = fallback.get("strategy_recommendation", {}).get("acquisition", "expected_improvement")
            out["strategy_recommendation"] = {
                "strategy": strategy,
                "acquisition": acquisition,
                "exploration_weight": max(0.0, min(cls._safe_float(rec.get("exploration_weight"), fallback.get("strategy_recommendation", {}).get("exploration_weight", 0.35)), 1.0)),
                "exploitation_weight": max(0.0, min(cls._safe_float(rec.get("exploitation_weight"), fallback.get("strategy_recommendation", {}).get("exploitation_weight", 0.65)), 1.0)),
                "reason": str(rec.get("reason") or fallback.get("strategy_recommendation", {}).get("reason") or "")[:700],
            }
        patch = raw.get("search_space_patch") if isinstance(raw.get("search_space_patch"), dict) else {}
        if patch:
            out["search_space_patch"] = {
                "narrow": patch.get("narrow") if isinstance(patch.get("narrow"), dict) else {},
                "expand": patch.get("expand") if isinstance(patch.get("expand"), dict) else {},
                "lock": patch.get("lock") if isinstance(patch.get("lock"), dict) else {},
                "forbid": [item for item in patch.get("forbid", []) if isinstance(item, dict)][:12] if isinstance(patch.get("forbid"), list) else fallback.get("search_space_patch", {}).get("forbid", []),
            }
        if isinstance(raw.get("preference_regions"), list):
            regions = []
            for item in raw["preference_regions"][:12]:
                if not isinstance(item, dict):
                    continue
                regions.append(
                    {
                        "condition": str(item.get("condition") or "")[:300],
                        "preference_score": max(0.0, min(cls._safe_float(item.get("preference_score"), 0.0), 1.0)),
                        "reason": str(item.get("reason") or "")[:400],
                    }
                )
            if regions:
                out["preference_regions"] = regions
        if isinstance(raw.get("risk_flags"), list):
            out["risk_flags"] = raw["risk_flags"][:12]
        if raw.get("operator_summary"):
            out["operator_summary"] = str(raw.get("operator_summary"))[:900]
        return out

    async def _llm_reasoning(
        self,
        state: OrchestratorState,
        ctx: AgentContext,
        *,
        objective: dict[str, Any],
        normalized: dict[str, Any],
        priors: list[dict[str, Any]],
        knowledge_context: dict[str, Any],
        failure_model: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        fallback = self._default_reasoning(
            objective=objective,
            normalized=normalized,
            priors=priors,
            knowledge_context=knowledge_context,
            failure_model=failure_model,
        )
        if not normalized.get("llm_preference_enabled", True) or not hasattr(ctx, "complete"):
            return fallback
        prompt_context = {
            "active_goal": state.active_goal,
            "objective": objective,
            "parameter_space": normalized.get("parameter_space", {}),
            "locked_parameters": {"cell_size_mm": self._locked_cell_size_from_state(state)},
            "prior_evaluations": priors[-12:],
            "knowledge_context": knowledge_context,
            "failure_model": failure_model,
            "current_strategy_settings": {
                key: normalized.get(key)
                for key in ("strategy", "benchmark_strategy", "bo_backend", "acquisition", "budget", "kappa", "xi", "exploration_weight", "exploitation_weight")
            },
        }
        prompt = (
            "You are BO Agent, an optimization scientist for TPMS/FDM autonomous experiments. "
            "Return strict JSON only. Do not choose hardware actions. Do not invent parameter keys. "
            "Use LLM reasoning only as soft preference; numeric acquisition and validators decide the final candidate.\n\n"
            "Required JSON keys: schema_version, hypotheses, strategy_recommendation, search_space_patch, "
            "preference_regions, risk_flags, operator_summary.\n\n"
            f"Context:\n{json.dumps(prompt_context, ensure_ascii=False, indent=2)}"
        )
        try:
            response = await ctx.complete("bo_policy", prompt, timeout_s=45.0 if state.mode == Mode.TEST else None)
            parsed = self._extract_json_object(response.text)
            if not parsed:
                warnings.append("bo_policy returned non-json reasoning; deterministic reasoning used")
                return fallback
            return self._sanitize_reasoning(parsed, fallback)
        except Exception as exc:
            warnings.append(f"bo_policy reasoning unavailable: {exc.__class__.__name__}")
            return fallback

    @staticmethod
    def _condition_matches(condition: str, parameters: dict[str, Any]) -> bool:
        text = str(condition or "").strip()
        if not text:
            return False
        between_pattern = r"([a-zA-Z_][\w]*)\s+between\s+([-+]?\d*\.?\d+)\s+and\s+([-+]?\d*\.?\d+)"
        protected = re.sub(
            between_pattern,
            lambda match: f"{match.group(1)} between {match.group(2)} __BO_BETWEEN_AND__ {match.group(3)}",
            text,
            flags=re.IGNORECASE,
        )
        clauses = [
            part.strip().replace("__BO_BETWEEN_AND__", "and")
            for part in re.split(r"\band\b|&&", protected, flags=re.IGNORECASE)
            if part.strip()
        ]
        if not clauses:
            return False
        for clause in clauses:
            between = re.search(between_pattern, clause, flags=re.IGNORECASE)
            if between:
                key, low, high = between.group(1), float(between.group(2)), float(between.group(3))
                value = BOAgent._safe_float(parameters.get(key), float("nan"))
                if not math.isfinite(value) or not (low <= value <= high):
                    return False
                continue
            comp = re.search(r"([a-zA-Z_][\w]*)\s*(>=|<=|>|<|==|=)\s*([-+]?\d*\.?\d+|true|false|gyroid|bcc|tpms)", clause, flags=re.IGNORECASE)
            if not comp:
                return False
            key, op, rhs_raw = comp.group(1), comp.group(2), comp.group(3)
            lhs = parameters.get(key)
            if rhs_raw.lower() in {"true", "false"}:
                rhs = rhs_raw.lower() == "true"
                lhs_value = bool(lhs)
                ok = lhs_value == rhs if op in {"=", "=="} else False
            else:
                try:
                    rhs_num = float(rhs_raw)
                    lhs_num = BOAgent._safe_float(lhs, float("nan"))
                    ok = {
                        ">=": lhs_num >= rhs_num,
                        "<=": lhs_num <= rhs_num,
                        ">": lhs_num > rhs_num,
                        "<": lhs_num < rhs_num,
                        "=": lhs_num == rhs_num,
                        "==": lhs_num == rhs_num,
                    }[op]
                except ValueError:
                    ok = str(lhs).strip().lower() == rhs_raw.strip().lower() if op in {"=", "=="} else False
            if not ok:
                return False
        return True

    @classmethod
    def _preference_score(cls, parameters: dict[str, Any], reasoning: dict[str, Any]) -> tuple[float, list[str]]:
        matched: list[str] = []
        scores: list[float] = []
        for region in reasoning.get("preference_regions", []) if isinstance(reasoning.get("preference_regions"), list) else []:
            if not isinstance(region, dict):
                continue
            condition = str(region.get("condition") or "")
            if condition and cls._condition_matches(condition, parameters):
                scores.append(max(0.0, min(cls._safe_float(region.get("preference_score"), 0.0), 1.0)))
                matched.append(condition)
        if not scores:
            return 0.0, []
        return round(sum(scores) / len(scores), 6), matched[:5]

    @classmethod
    def _constraint_penalty(cls, parameters: dict[str, Any], reasoning: dict[str, Any], failure_model: dict[str, Any]) -> tuple[float, list[str], bool]:
        reasons: list[str] = []
        penalty = 0.0
        valid = True
        if str(parameters.get("geometry_type", "gyroid")).lower() == "gyroid" and cls._safe_float(parameters.get("relative_density"), 0.32) < 0.20:
            reasons.append("relative_density below FDM continuous-shell lower bound")
            penalty += 1.0
            valid = False
        if bool(parameters.get("top_cap_enabled", False)):
            reasons.append("top cap may collapse under FDM overhang/gravity unless explicitly approved")
            penalty += 0.08
        forbid = []
        patch = reasoning.get("search_space_patch") if isinstance(reasoning.get("search_space_patch"), dict) else {}
        if isinstance(patch.get("forbid"), list):
            forbid.extend(item for item in patch["forbid"] if isinstance(item, dict))
        if isinstance(failure_model.get("forbidden_regions"), list):
            forbid.extend(item for item in failure_model["forbidden_regions"] if isinstance(item, dict))
        for item in forbid:
            condition = str(item.get("condition") or "")
            if condition and cls._condition_matches(condition, parameters):
                reasons.append(str(item.get("reason") or condition)[:240])
                penalty += 0.35
                if "relative_density < 0.20" in condition:
                    valid = False
        for item in failure_model.get("risk_patterns", []) if isinstance(failure_model.get("risk_patterns"), list) else []:
            if not isinstance(item, dict):
                continue
            condition = str(item.get("condition") or "")
            if condition and cls._condition_matches(condition, parameters):
                reasons.append(f"matches failure pattern: {item.get('failure', condition)}")
                penalty += min(0.45, 0.12 * max(1, int(item.get("count", 1))))
        return round(min(penalty, 1.5), 6), reasons[:8], valid

    @staticmethod
    def _strategy_payload(benchmark: dict[str, Any], preferred: str) -> tuple[str, dict[str, Any]]:
        strategies = benchmark.get("strategies") if isinstance(benchmark.get("strategies"), dict) else {}
        if isinstance(strategies.get(preferred), dict):
            return preferred, strategies[preferred]
        if isinstance(strategies.get("bo"), dict):
            return "bo", strategies["bo"]
        return BOAgent._best_strategy(benchmark)

    @classmethod
    def _candidate_pool_from_benchmark(cls, benchmark: dict[str, Any], preferred_strategy: str) -> list[dict[str, Any]]:
        strategy_name, payload = cls._strategy_payload(benchmark, preferred_strategy)
        trace = payload.get("surrogate_trace") if isinstance(payload.get("surrogate_trace"), list) else []
        if trace:
            latest = trace[-1] if isinstance(trace[-1], dict) else {}
            candidates = latest.get("candidates") if isinstance(latest.get("candidates"), list) else []
            pool = []
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                pool.append(
                    {
                        "candidate_id": str(item.get("candidate_id") or f"candidate-{len(pool) + 1:03d}"),
                        "parameters": item.get("parameters") if isinstance(item.get("parameters"), dict) else {},
                        "numeric": {
                            "surrogate_mean": cls._safe_float(item.get("surrogate_mean"), 0.0),
                            "uncertainty": cls._safe_float(item.get("uncertainty"), 0.0),
                            "acquisition_value": cls._safe_float(item.get("acquisition_value"), 0.0),
                        },
                        "already_evaluated": bool(item.get("already_evaluated")),
                        "source_strategy": strategy_name,
                    }
                )
            return pool
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        pool = []
        for item in results:
            if not isinstance(item, dict):
                continue
            params = cls._parameters_from_result(item)
            score = item.get("objective_score")
            pool.append(
                {
                    "candidate_id": str(item.get("candidate_id") or f"candidate-{len(pool) + 1:03d}"),
                    "parameters": params,
                    "numeric": {
                        "surrogate_mean": cls._safe_float(score, 0.0),
                        "uncertainty": cls._safe_float(item.get("uncertainty"), 0.2),
                        "acquisition_value": cls._safe_float(score, 0.0),
                    },
                    "already_evaluated": False,
                    "source_strategy": strategy_name,
                }
            )
        return pool

    @classmethod
    def _llm_weight(cls, normalized: dict[str, Any], prior_count: int, loop_count: int) -> float:
        raw = normalized.get("llm_candidate_weight", "auto")
        if raw != "auto":
            return max(0.0, min(cls._safe_float(raw, 0.15), 0.45))
        count = max(prior_count, loop_count)
        if count <= 3:
            return 0.25
        if count <= 10:
            return 0.15
        return 0.08

    @classmethod
    def _rank_candidates(
        cls,
        *,
        benchmark: dict[str, Any],
        normalized: dict[str, Any],
        reasoning: dict[str, Any],
        failure_model: dict[str, Any],
        locked_cell_size: float | None,
        prior_count: int,
        loop_count: int,
    ) -> list[dict[str, Any]]:
        pool = cls._candidate_pool_from_benchmark(benchmark, normalized.get("benchmark_strategy", normalized.get("strategy", "bo")))
        if not pool:
            return []
        max_acq = max(abs(cls._safe_float(item.get("numeric", {}).get("acquisition_value"), 0.0)) for item in pool) or 1.0
        llm_weight = cls._llm_weight(normalized, prior_count=prior_count, loop_count=loop_count)
        ranked: list[dict[str, Any]] = []
        for item in pool:
            params = cls._apply_locked_parameters(item.get("parameters", {}), cell_size_mm=locked_cell_size)
            pref_score, matched = cls._preference_score(params, reasoning)
            penalty, warnings, valid = cls._constraint_penalty(params, reasoning, failure_model)
            already = bool(item.get("already_evaluated"))
            duplicate_penalty = 0.18 if already else 0.0
            numeric = item.get("numeric") if isinstance(item.get("numeric"), dict) else {}
            acq = cls._safe_float(numeric.get("acquisition_value"), 0.0)
            numeric_score = acq / max_acq
            combined = numeric_score + llm_weight * pref_score - penalty - duplicate_penalty
            ranked.append(
                {
                    "candidate_id": item.get("candidate_id"),
                    "parameters": params,
                    "numeric": numeric,
                    "llm": {
                        "preference_score": pref_score,
                        "matched_regions": matched,
                        "weight": llm_weight,
                    },
                    "constraints": {
                        "valid": valid,
                        "risk_score": round(min(1.0, penalty), 6),
                        "warnings": warnings,
                        "already_evaluated": already,
                    },
                    "combined_score": round(combined, 6),
                    "source_strategy": item.get("source_strategy") or normalized.get("benchmark_strategy"),
                }
            )
        ranked.sort(key=lambda item: (bool(item["constraints"].get("valid")), item["combined_score"]), reverse=True)
        return ranked

    def _recommendation(self, benchmark: dict[str, Any], strategy: str) -> dict[str, Any]:
        best_name, best_payload = self._best_strategy(benchmark)
        best_result = best_payload.get("best_result") if isinstance(best_payload.get("best_result"), dict) else {}
        return {
            "candidate_id": str(best_result.get("candidate_id") or best_payload.get("best_candidate_id") or "candidate-default"),
            "parameters": self._parameters_from_result(best_result),
            "objective_score": best_payload.get("best_score"),
            "source_strategy": best_name or strategy,
            "reason": f"Selected best candidate from {best_name or strategy} best-so-far comparison.",
        }

    @classmethod
    def _recommendation_from_ranking(cls, ranking: list[dict[str, Any]], fallback: dict[str, Any], reasoning: dict[str, Any]) -> dict[str, Any]:
        if not ranking:
            return fallback
        selected = next((item for item in ranking if item.get("constraints", {}).get("valid", False)), ranking[0])
        hypotheses = [item.get("id") for item in reasoning.get("hypotheses", []) if isinstance(item, dict) and item.get("id")]
        rejected = [
            {
                "candidate_id": item.get("candidate_id"),
                "combined_score": item.get("combined_score"),
                "reason": item.get("constraints", {}).get("warnings", [])[:2] or ["lower combined score"],
            }
            for item in ranking[1:5]
        ]
        numeric = selected.get("numeric") if isinstance(selected.get("numeric"), dict) else {}
        return {
            "candidate_id": str(selected.get("candidate_id") or fallback.get("candidate_id") or "candidate-default"),
            "parameters": dict(selected.get("parameters") or fallback.get("parameters") or {}),
            "objective_score": numeric.get("surrogate_mean", fallback.get("objective_score")),
            "source_strategy": str(selected.get("source_strategy") or fallback.get("source_strategy") or "bo"),
            "reason": str(reasoning.get("operator_summary") or fallback.get("reason") or "Ranked by combined numeric acquisition and validated LLM preference."),
            "why_this_candidate": (
                f"combined_score={selected.get('combined_score')}, acquisition={numeric.get('acquisition_value')}, "
                f"llm_preference={selected.get('llm', {}).get('preference_score')}, risk={selected.get('constraints', {}).get('risk_score')}"
            ),
            "why_not_best_exploitation_only": "Duplicate, failed, or lower-information candidates are penalized before handoff.",
            "expected_information_gain": numeric.get("uncertainty", 0.0),
            "risk_assessment": selected.get("constraints", {}),
            "bo_hypothesis_ids": hypotheses[:5],
            "why_not_chosen": rejected,
            "combined_score": selected.get("combined_score"),
        }

    @staticmethod
    def _best_so_far(benchmark: dict[str, Any], strategy: str) -> list[dict[str, Any]]:
        strategies = benchmark.get("strategies") if isinstance(benchmark.get("strategies"), dict) else {}
        selected = strategies.get(strategy) if isinstance(strategies.get(strategy), dict) else {}
        if not selected:
            _, selected = BOAgent._best_strategy(benchmark)
        curve = selected.get("curve") if isinstance(selected.get("curve"), list) else []
        return [dict(item) for item in curve if isinstance(item, dict)]

    @staticmethod
    def _artifact_dir(state: OrchestratorState) -> Path:
        path = Path(__file__).resolve().parents[1] / "runs" / str(state.run_id or "run") / "bo"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return str(path)

    def _write_artifacts(self, state: OrchestratorState, *, reasoning: dict[str, Any], candidate_ranking: list[dict[str, Any]], next_candidate: dict[str, Any]) -> dict[str, str]:
        base = self._artifact_dir(state)
        return {
            "bo_reasoning_report": self._write_json(base / "bo_reasoning_report.json", reasoning),
            "candidate_pool": self._write_json(base / "candidate_pool.json", {"schema": "bo_candidate_pool.v1", "candidates": candidate_ranking}),
            "bo_next_candidate": self._write_json(base / "bo_next_candidate.json", next_candidate),
        }

    async def run_with_settings(
        self,
        state: OrchestratorState,
        ctx: AgentContext,
        settings: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Run BO Agent with GUI/API-supplied settings."""
        normalized, warnings = self.normalize_settings(settings)
        locked_cell_size = self._locked_cell_size_from_state(state)
        if locked_cell_size is not None:
            normalized["parameter_space"] = self._lock_parameter_space(
                normalized["parameter_space"],
                cell_size_mm=locked_cell_size,
            )
        strategy = normalized["strategy"]
        benchmark_strategy = normalized["benchmark_strategy"]
        benchmark_strategies = ["random", "grid", "bo"] if strategy == "mbo" else [benchmark_strategy]
        if strategy == "mbo" and not state.experiment_evaluations:
            warnings.append("mbo requested without prior evaluations; degraded to bo benchmark")
            benchmark_strategies = ["bo"]
        objective = self._objective_from_state(state, settings or {})
        active_binding = self._active_binding_from_context(state, ctx)
        if active_binding:
            objective.update(
                {
                    "objective_id": active_binding.get("objective_id"),
                    "objective_version": active_binding.get("version"),
                    "objective_hash": active_binding.get("objective_hash"),
                }
            )
        execution_mode = "virtual" if state.mode in {Mode.TEST, Mode.LIVE} else state.mode.value
        knowledge_context = self._knowledge_context_from_state(state)
        raw_priors = self._prior_evaluations_from_state(state)
        objective_hash = str(objective.get("objective_hash") or "")
        if objective_hash:
            priors, rejected_observations = self.objective_observations(
                raw_priors,
                objective_hash=objective_hash,
                mode=state.mode,
            )
        else:
            priors = raw_priors
            rejected_observations = []
        observation_integrity = {
            "objective_hash": objective_hash,
            "accepted_count": len(priors),
            "rejected_count": len(rejected_observations),
            "accepted_observation_ids": [str(item.get("observation_id") or item.get("candidate_id") or "") for item in priors],
            "rejected": rejected_observations,
        }
        if state.mode == Mode.LIVE and objective_hash and not priors:
            blocked_result = {
                "ok": False,
                "tool": "bo.agent",
                "run_id": state.run_id,
                "experiment_id": state.experiment_id,
                "status": "blocked",
                "failure_code": "BO_VALID_OBSERVATION_REQUIRED",
                "objective": objective,
                "observation_integrity": observation_integrity,
                "warnings": ["Live BO requires at least one hash-matched measured observation."],
            }
            return AgentResult(
                success=False,
                summary="BO blocked: no valid measured observation for the active objective",
                data={"bo_result": blocked_result, "experiment_objective": objective},
            )
        failure_model = self._failure_model(priors)
        reasoning = await self._llm_reasoning(
            state,
            ctx,
            objective=objective,
            normalized=normalized,
            priors=priors,
            knowledge_context=knowledge_context,
            failure_model=failure_model,
            warnings=warnings,
        )
        benchmark_payload = {
            "budget": normalized["budget"],
            "strategies": benchmark_strategies,
            "seed": normalized["random_seed"],
            "parameter_space": normalized["parameter_space"],
            "objective": objective,
            "acquisition": normalized["acquisition"],
            "kappa": normalized["kappa"],
            "xi": normalized["xi"],
            "exploration_weight": normalized["exploration_weight"],
            "exploitation_weight": normalized["exploitation_weight"],
            "bo_backend": normalized["bo_backend"],
            "request": {
                "run_id": state.run_id,
                "experiment_id": state.experiment_id,
                "session_id": state.active_session_id or state.run_id,
                "objective": objective,
                "execution": {"mode": execution_mode, "bridge": "virtual", "dry_run": True},
                "metadata": {
                    "agent": self.name,
                    "strategy": strategy,
                    "benchmark_strategy": benchmark_strategy,
                    "acquisition": normalized["acquisition"],
                    "kappa": normalized["kappa"],
                    "xi": normalized["xi"],
                    "exploration_weight": normalized["exploration_weight"],
                    "exploitation_weight": normalized["exploitation_weight"],
                    "bo_backend": normalized["bo_backend"],
                    "knowledge_context": knowledge_context,
                    "reasoning_source": reasoning.get("source"),
                },
            },
            "prior_evaluations": priors,
        }
        benchmark = ctx.tools.call("experiment.benchmark", benchmark_payload)
        fallback_strategy = "bo" if strategy == "mbo" and warnings else benchmark_strategy
        fallback_recommendation = self._recommendation(benchmark, fallback_strategy)
        candidate_ranking = self._rank_candidates(
            benchmark=benchmark,
            normalized=normalized,
            reasoning=reasoning,
            failure_model=failure_model,
            locked_cell_size=locked_cell_size,
            prior_count=len(priors),
            loop_count=int(state.loop_count or 0),
        )
        recommendation = self._recommendation_from_ranking(candidate_ranking, fallback_recommendation, reasoning)
        recommendation["parameters"] = self._apply_locked_parameters(
            recommendation.get("parameters", {}),
            cell_size_mm=locked_cell_size,
        )
        if knowledge_context.get("memory_summary"):
            recommendation["reason"] = (
                f"{recommendation['reason']} KnowledgeAgent context was attached for next-cycle DesignAgent constraints."
            )
        top_k = candidate_ranking[: normalized["top_k"]]
        measured_priors = [item for item in priors if item.get("ok_for_bo", True) and isinstance(item.get("score"), (int, float))]
        failed_priors = [item for item in priors if not item.get("ok_for_bo", True) or item.get("failure_tags")]
        best_prior = max(measured_priors, key=lambda item: float(item.get("score", float("-inf"))), default={})
        prior_summary = {
            "prior_count": len(priors),
            "measured_count": len(measured_priors),
            "failed_count": len(failed_priors),
            "best_score": float(best_prior["score"]) if isinstance(best_prior.get("score"), (int, float)) else None,
            "best_candidate_id": best_prior.get("candidate_id"),
        }
        next_design_request = {
            "schema": "next_design_request.v1",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "producer_agent": self.name,
            "consumer_agent": "design_agent",
            "objective_id": objective.get("objective_id"),
            "objective_version": objective.get("objective_version"),
            "objective_hash": objective_hash,
            "status": "ready" if recommendation.get("parameters") else "blocked",
            "candidate_id": recommendation.get("candidate_id"),
            "constraints": dict(recommendation.get("parameters") or {}),
            "rationale": recommendation.get("why_this_candidate") or recommendation.get("reason"),
            "reasoning_ref": "bo_reasoning_report",
            "guardian_status": "not_checked",
            "decisions": [
                {
                    "decision": "recommend_candidate",
                    "candidate_id": recommendation.get("candidate_id"),
                    "source_strategy": recommendation.get("source_strategy"),
                    "combined_score": recommendation.get("combined_score"),
                }
            ],
            "warnings": recommendation.get("risk_assessment", {}).get("warnings", []),
            "next_action": "Design Agent should validate manufacturability before specimen generation.",
            "created_at": self.now_iso(),
        }
        artifacts = self._write_artifacts(
            state,
            reasoning=reasoning,
            candidate_ranking=candidate_ranking,
            next_candidate=next_design_request,
        )
        strategy_payload = (
            benchmark.get("strategies", {}).get(recommendation.get("source_strategy"), {})
            if isinstance(benchmark.get("strategies"), dict)
            else {}
        )
        visualization_trace = (
            strategy_payload.get("surrogate_trace", [])
            if isinstance(strategy_payload, dict) and isinstance(strategy_payload.get("surrogate_trace"), list)
            else []
        )
        visualizations = [
            item.get("visualization")
            for item in visualization_trace
            if isinstance(item, dict) and isinstance(item.get("visualization"), dict)
        ]
        latest_visualization = visualizations[-1] if visualizations else {}
        bo_result = {
            "ok": bool(benchmark.get("ok", False)) and bool(recommendation.get("parameters")),
            "tool": "bo.agent",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "strategy": strategy,
            "benchmark_strategy": benchmark_strategy,
            "acquisition": normalized["acquisition"],
            "budget": normalized["budget"],
            "bo_backend": normalized["bo_backend"],
            "parameter_space": normalized["parameter_space"],
            "objective": objective,
            "benchmark": benchmark,
            "prior_summary": prior_summary,
            "failure_model": failure_model,
            "reasoning": reasoning,
            "candidate_pool": candidate_ranking,
            "candidate_ranking": top_k,
            "recommendation": recommendation,
            "next_design_request": next_design_request,
            "observation_integrity": observation_integrity,
            "best_so_far": self._best_so_far(benchmark, recommendation["source_strategy"]),
            "visualization": latest_visualization,
            "visualization_steps": [
                {
                    "step": int(item.get("step") or 0),
                    "selected_parameter": str((item.get("view") or {}).get("selected_parameter") or ""),
                }
                for item in visualizations
            ],
            "knowledge_context": knowledge_context,
            "warnings": warnings,
            "artifacts": artifacts,
            "metadata": {
                "mode": state.mode.value,
                "random_seed": normalized["random_seed"],
                "kappa": normalized["kappa"],
                "xi": normalized["xi"],
                "exploration_weight": normalized["exploration_weight"],
                "exploitation_weight": normalized["exploitation_weight"],
                "llm_preference_enabled": normalized["llm_preference_enabled"],
                "llm_candidate_weight": self._llm_weight(normalized, prior_count=len(priors), loop_count=int(state.loop_count or 0)),
                "bo_backend": normalized["bo_backend"],
                "benchmark_backend_active": (benchmark.get("strategies", {}).get(recommendation.get("source_strategy"), {}) if isinstance(benchmark.get("strategies"), dict) else {}).get("backend_active"),
                "prior_evaluation_count": len(state.experiment_evaluations),
                "analysis_prior_count": len(priors),
                "locked_parameters": {
                    "cell_size_mm": locked_cell_size,
                }
                if locked_cell_size is not None
                else {},
            },
        }
        state.run_metadata["bo_agent"] = bo_result
        state.run_metadata["bo_recommended_constraints"] = dict(recommendation.get("parameters") or {})
        state.run_metadata["next_design_request"] = next_design_request
        return AgentResult(
            success=bool(bo_result["ok"]),
            summary=f"BO Agent selected {recommendation['candidate_id']} via {recommendation['source_strategy']}",
            data={
                "bo_result": bo_result,
                "experiment_objective": objective,
                "experiment_spec_update": recommendation.get("parameters", {}),
                "next_design_request": next_design_request,
            },
        )

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        """Run with defaults when invoked directly by registry/future orchestrator paths."""
        return await self.run_with_settings(state, ctx, {})
