"""
File purpose:
- Retrieve guide/web knowledge with RAG and maintain experiment memory.

Key classes/functions:
- KnowledgeAgent

Inputs/outputs:
- Input: active goal, analysis result, current experiment metadata
- Output: retrieval summary and memory write confirmation

Dependencies:
- knowledge.rag.HybridRAG
- knowledge.retrieval.format_rag_context
- knowledge.schemas.MemoryRecord

Modification guide:
- Safe places to edit: query shaping and memory summary text
- Risky places to edit: record schema and RAG context formatting
- Related files: knowledge/rag.py, knowledge/experiment_db.py
"""

from __future__ import annotations

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from knowledge.retrieval import format_rag_context
from knowledge.schemas import MemoryRecord
from orchestrator.state import OrchestratorState


class KnowledgeAgent(BaseAgent):
    """Handles retrieval and memory persistence."""

    name = "knowledge_agent"

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        query = (
            f"{state.active_goal}. "
            f"Current stage={state.stage.value}. "
            "What constraints and architecture rules should this loop enforce?"
        )
        retrieval = await ctx.rag.retrieve(query=query, top_k_local=4)
        rag_context = format_rag_context(retrieval)

        timeout_s = 45.0 if state.mode.value == "test" else None
        try:
            response = await ctx.complete(
                "knowledge_query",
                "Use the context to produce concise constraints and next-step reminders.\n" + rag_context,
                timeout_s=timeout_s,
            )
            memory_summary = response.text[:300]
        except Exception as exc:
            if state.mode.value == "test":
                memory_summary = f"Knowledge degraded in test mode: {exc.__class__.__name__}"
            else:
                raise
        objective = float(state.latest_analysis.get("objective_score", 0.0))
        uncertainty = float(state.latest_analysis.get("uncertainty", 1.0))
        record = MemoryRecord(
            run_id=state.run_id,
            experiment_id=state.experiment_id,
            summary=memory_summary,
            score=objective,
            uncertainty=uncertainty,
        )
        ctx.experiment_db.add(record)

        return AgentResult(
            success=True,
            summary="Knowledge retrieval and memory update complete",
            data={
                "knowledge": {
                    "retrieval_coverage": retrieval.get("coverage", 0.0),
                    "local_chunks": len(retrieval.get("local_chunks", [])),
                    "web_results": len(retrieval.get("web_results", [])),
                    "memory_summary": memory_summary,
                }
            },
        )
