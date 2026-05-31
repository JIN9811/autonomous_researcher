"""
File purpose:
- Shared retrieval utilities for formatting RAG context into prompts.

Key classes/functions:
- format_rag_context

Inputs/outputs:
- Input: hybrid RAG retrieval dictionary
- Output: compact plain-text context block

Dependencies:
- none

Modification guide:
- Safe places to edit: formatting style
- Risky places to edit: downstream parsing assumptions
- Related files: agents/knowledge_agent.py, backends/prompt_registry.py
"""

from __future__ import annotations

from typing import Any


def format_rag_context(result: dict[str, Any]) -> str:
    """Format local + web retrieval results for LLM prompting."""
    lines: list[str] = []
    lines.append(f"LOCAL_COVERAGE={result.get('coverage', 0.0):.2f}")
    lines.append("LOCAL_CONTEXT:")
    for i, chunk in enumerate(result.get("local_chunks", []), start=1):
        lines.append(f"[{i}] source={chunk.get('source')} id={chunk.get('chunk_id')}")
        lines.append(str(chunk.get("text", "")).strip().replace("\n", " ")[:500])

    web_results = result.get("web_results", [])
    if web_results:
        lines.append("WEB_CONTEXT:")
        for i, item in enumerate(web_results, start=1):
            lines.append(f"[W{i}] {item.get('title')} ({item.get('url')})")
            lines.append(str(item.get("snippet", "")).strip())
    return "\n".join(lines)


def retrieve_run_context(*, agent_id: str, run_id: str, knowledge_payload: dict[str, Any]) -> dict[str, Any]:
    """Return hot run context from the latest Knowledge Agent payload."""
    report = knowledge_payload.get("knowledge_report") if isinstance(knowledge_payload.get("knowledge_report"), dict) else {}
    return {
        "agent_id": agent_id,
        "run_id": run_id,
        "source_type": "run_context",
        "memory_summary": knowledge_payload.get("memory_summary", ""),
        "retrieval_coverage": knowledge_payload.get("retrieval_coverage", 0.0),
        "evidence_quality": report.get("evidence_quality", {}),
        "warnings": report.get("warnings", []),
    }


def retrieve_research_context(*, query: str, retrieval_result: dict[str, Any]) -> dict[str, Any]:
    """Normalize project/doc/scientific retrieval evidence for reports."""
    sources: list[dict[str, Any]] = []
    for chunk in retrieval_result.get("local_chunks", []) or []:
        if isinstance(chunk, dict):
            sources.append({
                "source_type": "project_guideline",
                "source_ref": str(chunk.get("source") or chunk.get("chunk_id") or "local_chunk"),
                "trust_level": "project_local_index",
                "recency": "indexed",
                "retrieval_score": float(chunk.get("score") or retrieval_result.get("coverage") or 0.0),
                "used_for": ["knowledge_context"],
            })
    for item in retrieval_result.get("web_results", []) or []:
        if isinstance(item, dict):
            sources.append({
                "source_type": "official_doc" if item.get("url") else "scientific_paper",
                "source_ref": str(item.get("url") or item.get("title") or "web_result"),
                "trust_level": "external_retrieval",
                "recency": "retrieved",
                "retrieval_score": float(item.get("score") or 0.0),
                "used_for": ["research_context"],
            })
    return {"query": query, "source_count": len(sources), "sources": sources}


def retrieve_evolution_context(*, target_id: str, evidence_packs: list[dict[str, Any]]) -> dict[str, Any]:
    """Return ranked self-evolution context for one target."""
    packs = [pack for pack in evidence_packs if isinstance(pack, dict) and (not target_id or pack.get("target_id") == target_id)]
    packs.sort(key=lambda item: float(item.get("priority") or 0.0), reverse=True)
    return {
        "target_id": target_id,
        "pack_count": len(packs),
        "top_pack_ids": [str(item.get("pack_id") or "") for item in packs[:5]],
        "top_objectives": [str(item.get("objective") or "") for item in packs[:3]],
    }
