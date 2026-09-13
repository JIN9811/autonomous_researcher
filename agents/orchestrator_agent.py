"""
File purpose:
- Top-level orchestration reasoning agent for route planning and summary control.

Key classes/functions:
- OrchestratorAgent

Inputs/outputs:
- Input: current global state snapshot
- Output: high-level control summary

Dependencies:
- agents.base_agent.BaseAgent

Modification guide:
- Safe places to edit: prompt contents and summary fields
- Risky places to edit: returned keys consumed in run loop
- Related files: orchestrator/run_loop.py, backends/model_router.py
"""

from __future__ import annotations

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from agents.execution_graph import execution_event_emitter, execution_graph_from_context
from agents.orchestrator_execution import default_orchestrator_execution_graph, execute_orchestrator_graph
from utils.agent_artifact_archive import archive_agent_run
from orchestrator.state import OrchestratorState
from orchestrator.supervisor import (
    build_decision_record,
    build_orchestrator_control_plane_snapshot,
    build_mission_contract,
    build_orchestration_plan,
    build_orchestrator_followup,
)


class OrchestratorAgent(BaseAgent):
    """Produces top-level reasoning text for current loop cycle."""

    name = "orchestrator_agent"

    def setup_descriptor(self) -> dict:
        return {"write_enabled": True, "fields": [
            {"id": "research.goal", "field": "active_goal", "type": "string", "required": True}]}

    def read_setup(self, state: OrchestratorState) -> dict:
        return {"active_goal": state.active_goal}

    def validate_setup(self, changes: dict, state: OrchestratorState) -> dict:
        if not isinstance(changes, dict) or set(changes) - {"active_goal"}:
            raise ValueError("Unsupported Orchestrator setup field")
        values = {**self.read_setup(state), **changes}
        goal = values["active_goal"]
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("Research goal must be nonempty text")
        values["active_goal"] = goal.strip()
        return {"values": values, "warnings": [],
                "requires_confirmation": any(values[key] != value for key, value in changes.items())}

    def apply_setup(self, changes: dict, state: OrchestratorState, request_id: str) -> dict:
        if state.stage.value != "idle" or state.loop_count or state.experiment_evaluations:
            raise ValueError("Setup applies only to fresh-run inputs")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id is required")
        validated = self.validate_setup(changes, state)
        state.active_goal = validated["values"]["active_goal"]
        return {"owner": self.name, "request_id": request_id, "values": self.read_setup(state)}

    @archive_agent_run
    async def run(self, state: OrchestratorState, ctx: AgentContext, *,
                  context: dict | None = None, handlers: dict | None = None) -> AgentResult:
        execution = await execute_orchestrator_graph(
            self,
            state,
            ctx,
            context=context,
            handlers=handlers,
            graph=execution_graph_from_context(ctx, "orchestrator", default_orchestrator_execution_graph),
            emit=execution_event_emitter(ctx),
        )
        if not isinstance(execution.result, AgentResult):
            raise RuntimeError("Orchestrator execution graph completed without AgentResult")
        return execution.result
