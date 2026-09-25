"""Read-only final BO assessment; never proposes or schedules another specimen."""
from __future__ import annotations

import asyncio
from copy import deepcopy

from agents.base_agent import AgentResult
from experiments.benchmark import _botorch_observations, _observation_trace
from experiments.bo_visualization import build_bo_visualization
from learning.bo_parameter_space import BOParameterSpace
from learning.botorch_backend import BoTorchBackendError, propose_next


async def finalize_bo(agent, state, settings, objective, priors, integrity, knowledge):
    space = BOParameterSpace.from_mapping(settings["parameter_space"])
    observations = _botorch_observations({"prior_evaluations": priors}, space)
    if not observations:
        report = {"ok": False, "optimization_phase": "final_report",
            "failure_code": "BO_VALID_OBSERVATION_REQUIRED", "objective": objective,
            "observation_integrity": integrity}
        state.run_metadata["bo_agent"] = report
        return AgentResult(success=False, summary="Final BO assessment requires measured evidence",
                           data={"bo_result": report})
    visualization, model, warnings = {}, {}, []
    try:
        proposal = await asyncio.to_thread(propose_next, parameter_space=space,
            observations=observations, acquisition=settings["acquisition"],
            objective_direction=objective.get("direction", "maximize"),
            random_seed=settings["random_seed"], kappa=settings["kappa"], report_only=True)
    except BoTorchBackendError as exc:
        if exc.failure_code not in {"BOTORCH_INSUFFICIENT_OBSERVATIONS", "BOTORCH_PARAMETER_SPACE_FIXED"}:
            report = {**exc.to_dict(), "optimization_phase": "final_report", "objective": objective}
            state.run_metadata["bo_agent"] = report
            return AgentResult(success=False, summary="Final BO model update failed", data={"bo_result": report})
        # A one-experiment/fixed-design run may finish without claiming a GP fit.
        warnings.append(str(exc))
    else:
        model = proposal.model
        trace = {"step": state.loop_count + 1, "phase": "final_report", "selected": {},
            "candidates": [], "evaluated_points": _observation_trace(observations),
            "backend_active": "botorch", "model": model, "optimizer": proposal.optimizer,
            "acquisition_class": proposal.acquisition["class"], "projection": proposal.projection}
        visualization = build_bo_visualization(run_id=state.run_id, objective=objective,
            parameter_space=settings["parameter_space"], trace=trace)
    best = (min if objective.get("direction") == "minimize" else max)(
        observations, key=lambda row: row["score"], default={})
    decision = {"status": "completed", "decision": "final_report",
                "reason": "Approved experiment count reached; no further candidate requested."}
    artifacts = agent._write_artifacts(state, reasoning=decision, decision=decision,
                                      candidate_ranking=[], next_candidate={})
    if visualization:
        from reporting.bo_visualization_artifacts import write_bo_visualization_artifacts
        plots = await asyncio.to_thread(write_bo_visualization_artifacts,
                                       visualization, agent._artifact_dir(state))
        artifacts.update({item["name"]: item["path"] for item in plots})
    report = {"ok": True, "tool": "bo.agent", "status": "completed", "run_id": state.run_id,
        "experiment_id": state.experiment_id, "optimization_phase": "final_report",
        "budget": settings["budget"], "strategy": settings["strategy"],
        "acquisition": settings["acquisition"], "objective": objective,
        "parameter_space": settings["parameter_space"], "backend_active": "botorch" if model else "none",
        "model": model, "recommendation": {}, "next_design_request": {},
        "candidate_pool": [], "candidate_ranking": [], "decision": decision, "reasoning": decision,
        "best_observation": best, "observation_integrity": integrity,
        "knowledge_context": knowledge, "visualization": visualization,
        "visualization_steps": [{"step": state.loop_count + 1}] if visualization else [],
        "artifacts": artifacts, "warnings": warnings}
    state.run_metadata["bo_settings"] = deepcopy(settings)
    state.run_metadata["bo_agent"] = report
    return AgentResult(success=True, summary="Final BO assessment complete; no next experiment",
                       data={"bo_result": report, "experiment_objective": objective})
