"""
Unit tests for local and hybrid RAG behavior.
"""

from pathlib import Path

import pytest

from knowledge.rag import HybridRAG, LocalRAGIndex, WebRetriever


@pytest.mark.asyncio
async def test_local_rag_returns_chunks(tmp_path: Path) -> None:
    path = tmp_path / "guide.txt"
    path.write_text(
        "LangGraph orchestrator controls stage transitions.\n"
        "Ollama is the local-first backend.\n"
        "Test mode supports dry-run and fault injection.",
        encoding="utf-8",
    )
    index = LocalRAGIndex.from_file(path)
    rag = HybridRAG(local_index=index, web_retriever=WebRetriever(None, None))
    result = await rag.retrieve("What backend is used for local inference?")
    assert result["local_chunks"]
    assert "coverage" in result
