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
from agents.orchestrator_decision import decide_orchestration
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
        mission_contract = build_mission_contract(state=state)
        orchestration_plan = build_orchestration_plan(state=state)
        if context is None:
            # Standalone calls have no dispatcher authority. The live boundaries
            # supply invocation-local candidates, scope and handlers explicitly.
            context = {'scope': {'checkpoint': 'standalone'},
                       'evidence': {'context:mission': mission_contract},
                       'handoff_candidates': [],
                       'settings': state.run_metadata.get('orchestrator_decision_settings', {})}
            async def defer(arguments):
                return {'condition': arguments['condition'], 'status': 'deferred'}
            handlers = {'defer': defer}
        decision = await decide_orchestration(state, ctx, context=context, handlers=handlers or {})
        plan_text = decision['reason'][:600]
        model = decision['model']
        control_plane = build_orchestrator_control_plane_snapshot(
            state=state,
            mission_contract=mission_contract,
            orchestration_plan=orchestration_plan,
            next_action=plan_text,
        )
        followup = build_orchestrator_followup(
            state=state,
            stage=state.stage,
            trigger="pre_stage_plan",
            payload={"status": "planning", "mission_contract": mission_contract, "orchestration_plan": orchestration_plan, "plan_text": plan_text},
            next_stage=state.stage,
        )
        record = build_decision_record(
            state=state, stage=state.stage,
            decision=decision['tool'] or decision['status'],
            selected=decision['arguments'].get('candidate') if decision['status'] == 'prepared' else None,
            reason=decision['reason'], evidence_refs=decision['evidence_refs'],
        )
        record['decision_id'] = decision['decision_id']
        record['status'] = decision['status']
        return AgentResult(
            success=decision['status'] == 'prepared',
            summary=f"Orchestration decision: {decision['status']}",
            data={
                "plan_text": plan_text,
                "model": model,
                "mission_contract": mission_contract,
                "orchestration_plan": orchestration_plan,
                "orchestrator_control_plane": control_plane,
                "orchestrator_followup": followup,
                "decisions": [record],
                "orchestration_decision": decision,
                "metrics": {
                    "plan_text_chars": len(plan_text),
                    "followup_confidence": followup.get("confidence", 0.0),
                    "route_stage_count": len(orchestration_plan.get("route", [])),
                    "parallelizable_check_count": len(orchestration_plan.get("parallelizable_checks", [])),
                },
            },
        )
