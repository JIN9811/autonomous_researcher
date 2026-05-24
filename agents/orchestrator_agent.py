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
from orchestrator.state import Mode, OrchestratorState


class OrchestratorAgent(BaseAgent):
    """Produces top-level reasoning text for current loop cycle."""

    name = "orchestrator_agent"

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        prompt = (
            f"run_id={state.run_id}\n"
            f"mode={state.mode.value}\n"
            f"stage={state.stage.value}\n"
            f"goal={state.active_goal}\n"
            f"loop_count={state.loop_count}\n"
            "Return short plan for the next stage.\n"
            "Topology constraint: orchestrator must support feedback loops "
            "(guardian->design), not linear one-pass pipelines."
        )
        timeout_s = 45.0 if state.mode == Mode.TEST else None
        try:
            response = await ctx.complete("orchestrator_plan", prompt, timeout_s=timeout_s)
            plan_text = response.text[:600]
            model = response.model
        except Exception as exc:
            if state.mode == Mode.TEST:
                plan_text = (
                    "Deterministic test-mode orchestration plan: "
                    f"advance stage from {state.stage.value} using standard topology."
                )
                model = "deterministic:test"
            else:
                raise
        return AgentResult(
            success=True,
            summary="Top-level orchestration plan generated",
            data={"plan_text": plan_text, "model": model},
        )
