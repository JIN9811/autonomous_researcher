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
