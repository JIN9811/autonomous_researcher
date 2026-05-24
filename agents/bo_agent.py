"""
File purpose:
- Bayesian Optimization advisory agent for Autonomous Experiment Runtime candidates.

Key classes/functions:
- BOAgent

Inputs/outputs:
- Input: OrchestratorState, optional BO settings from GUI/API
- Output: AgentResult.data["bo_result"] with benchmark curves and recommendation

Dependencies:
- experiments.benchmark
- agents.base_agent

Modification guide:
- Safe places to edit: supported acquisition settings and default parameter space
- Risky places to edit: bo_result schema consumed by GUI/API/tests
"""

from __future__ import annotations

from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState


class BOAgent(BaseAgent):
    """Advisory BO/MBO agent that proposes next design constraints without touching hardware."""

    name = "bo_agent"

    SUPPORTED_STRATEGIES = ("random", "grid", "bo", "mbo")
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
        return (
            {
                "strategy": strategy,
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
            "name": raw.get("name") or current.get("name") or "Specimen printability and performance proxy",
            "description": raw.get("description") or current.get("description") or state.active_goal,
            "metric_name": raw.get("metric_name") or current.get("metric_name") or "objective_score",
            "direction": raw.get("direction") or current.get("direction") or "maximize",
            "constraints": {**constraints, **(raw.get("constraints") if isinstance(raw.get("constraints"), dict) else {})},
            "tags": raw.get("tags") if isinstance(raw.get("tags"), list) else ["bo", "specimen", "tpms"],
        }
        return objective

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
    def _prior_evaluations_from_state(cls, state: OrchestratorState) -> list[dict[str, Any]]:
        """Return compact prior points so BO does not keep recommending the same specimen."""
        priors: list[dict[str, Any]] = []
        current = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        if current:
            params = {key: current.get(key) for key in cls.SHAPE_PARAMETER_KEYS if key in current}
            if params:
                priors.append({"source": "current_specimen", "parameters": params})
        for item in state.experiment_evaluations:
            if not isinstance(item, dict):
                continue
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            params = {key: metrics.get(key) for key in cls.SHAPE_PARAMETER_KEYS if key in metrics}
            if not params:
                continue
            prior: dict[str, Any] = {"source": "experiment_evaluation", "parameters": params}
            score = item.get("objective_score")
            if isinstance(score, (int, float)):
                prior["score"] = float(score)
            priors.append(prior)
        return priors

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

    @staticmethod
    def _best_so_far(benchmark: dict[str, Any], strategy: str) -> list[dict[str, Any]]:
        strategies = benchmark.get("strategies") if isinstance(benchmark.get("strategies"), dict) else {}
        selected = strategies.get(strategy) if isinstance(strategies.get(strategy), dict) else {}
        if not selected:
            _, selected = BOAgent._best_strategy(benchmark)
        curve = selected.get("curve") if isinstance(selected.get("curve"), list) else []
        return [dict(item) for item in curve if isinstance(item, dict)]

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
        benchmark_strategies = ["random", "grid", "bo"] if strategy == "mbo" else [strategy]
        if strategy == "mbo" and not state.experiment_evaluations:
            warnings.append("mbo requested without prior evaluations; degraded to bo benchmark")
            benchmark_strategies = ["bo"]
        objective = self._objective_from_state(state, settings or {})
        execution_mode = "virtual" if state.mode in {Mode.TEST, Mode.LIVE} else state.mode.value
        knowledge_context = self._knowledge_context_from_state(state)
        benchmark_payload = {
            "budget": normalized["budget"],
            "strategies": benchmark_strategies,
            "seed": normalized["random_seed"],
            "parameter_space": normalized["parameter_space"],
            "objective": objective,
            "request": {
                "run_id": state.run_id,
                "experiment_id": state.experiment_id,
                "session_id": state.active_session_id or state.run_id,
                "objective": objective,
                "execution": {"mode": execution_mode, "bridge": "virtual", "dry_run": True},
                "metadata": {
                    "agent": self.name,
                    "strategy": strategy,
                    "acquisition": normalized["acquisition"],
                    "kappa": normalized["kappa"],
                    "xi": normalized["xi"],
                    "exploration_weight": normalized["exploration_weight"],
                    "exploitation_weight": normalized["exploitation_weight"],
                    "knowledge_context": knowledge_context,
                },
            },
            "prior_evaluations": self._prior_evaluations_from_state(state),
        }
        benchmark = ctx.tools.call("experiment.benchmark", benchmark_payload)
        recommendation = self._recommendation(benchmark, "bo" if strategy == "mbo" and warnings else strategy)
        recommendation["parameters"] = self._apply_locked_parameters(
            recommendation.get("parameters", {}),
            cell_size_mm=locked_cell_size,
        )
        if knowledge_context.get("memory_summary"):
            recommendation["reason"] = (
                f"{recommendation['reason']} KnowledgeAgent context was attached for next-cycle DesignAgent constraints."
            )
        bo_result = {
            "ok": bool(benchmark.get("ok", False)),
            "tool": "bo.agent",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "strategy": strategy,
            "acquisition": normalized["acquisition"],
            "budget": normalized["budget"],
            "parameter_space": normalized["parameter_space"],
            "objective": objective,
            "benchmark": benchmark,
            "recommendation": recommendation,
            "best_so_far": self._best_so_far(benchmark, recommendation["source_strategy"]),
            "knowledge_context": knowledge_context,
            "warnings": warnings,
            "metadata": {
                "mode": state.mode.value,
                "random_seed": normalized["random_seed"],
                "kappa": normalized["kappa"],
                "xi": normalized["xi"],
                "exploration_weight": normalized["exploration_weight"],
                "exploitation_weight": normalized["exploitation_weight"],
                "prior_evaluation_count": len(state.experiment_evaluations),
                "locked_parameters": {
                    "cell_size_mm": locked_cell_size,
                }
                if locked_cell_size is not None
                else {},
            },
        }
        state.run_metadata["bo_agent"] = bo_result
        return AgentResult(
            success=bool(bo_result["ok"]),
            summary=f"BO Agent selected {recommendation['candidate_id']} via {recommendation['source_strategy']}",
            data={
                "bo_result": bo_result,
                "experiment_objective": objective,
                "experiment_spec_update": recommendation.get("parameters", {}),
            },
        )

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        """Run with defaults when invoked directly by registry/future orchestrator paths."""
        return await self.run_with_settings(state, ctx, {})
