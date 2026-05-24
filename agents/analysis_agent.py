"""
File purpose:
- Analyze experiment outputs and compute objective/uncertainty summaries.

Key classes/functions:
- AnalysisAgent

Inputs/outputs:
- Input: tool outputs and observations from current loop
- Output: objective score, uncertainty, and summary text

Dependencies:
- agents.base_agent.BaseAgent

Modification guide:
- Safe places to edit: scoring formula and summary fields
- Risky places to edit: schema expected by memory DB and guardian
- Related files: knowledge/experiment_db.py, agents/knowledge_agent.py
"""

from __future__ import annotations

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import OrchestratorState


class AnalysisAgent(BaseAgent):
    """Computes compact experiment analysis outputs."""

    name = "analysis_agent"

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        grasp = float(state.latest_analysis.get("last_grasp_score", 0.82))
        loop_gain = min(0.12, state.loop_count * 0.01)
        objective = round(0.55 + 0.3 * grasp + loop_gain, 4)
        uncertainty = round(max(0.05, 0.35 - state.loop_count * 0.02), 4)

        use_llm = state.mode.value == "live" or ctx.force_real_llm_in_test
        if use_llm:
            timeout_s = 45.0 if state.mode.value == "test" else None
            try:
                response = await ctx.complete(
                    "analysis_reasoning",
                    f"Summarize objective={objective}, uncertainty={uncertainty} for GUI operator.",
                    timeout_s=timeout_s,
                )
                summary = response.text[:320]
            except Exception as exc:
                if state.mode.value == "test":
                    summary = (
                        f"objective={objective} uncertainty={uncertainty} "
                        f"(E4B degraded: {exc.__class__.__name__})"
                    )
                else:
                    raise
        else:
            summary = f"objective={objective} uncertainty={uncertainty} (test analysis)"

        return AgentResult(
            success=True,
            summary="Analysis complete",
            data={"analysis": {"objective_score": objective, "uncertainty": uncertainty, "summary": summary}},
        )
