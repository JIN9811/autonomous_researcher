"""
File purpose:
- Provide local-document RAG with optional internet fallback for unknown topics.

Key classes/functions:
- RAGChunk
- LocalRAGIndex
- WebRetriever
- HybridRAG

Inputs/outputs:
- Input: guide text path and query
- Output: ranked context chunks and optional web snippets

Dependencies:
- pathlib.Path
- re
- httpx
- backends.embedding_client

Modification guide:
- Safe places to edit: chunk size and ranking blend
- Risky places to edit: web provider request contract and auth headers
- Related files: agents/knowledge_agent.py, configs/system.yaml
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import httpx

from backends.embedding_client import cosine_similarity, simple_embed


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))


@dataclass(slots=True)
class RAGChunk:
    """Represents one retrievable document chunk."""

    chunk_id: str
    text: str
    source: str
    embedding: list[float]
    keywords: set[str]


class LocalRAGIndex:
    """Simple local document index with lexical and embedding ranking."""

    def __init__(self, chunks: list[RAGChunk]) -> None:
        self._chunks = chunks

    @classmethod
    def from_file(cls, path: Path, chunk_size: int = 900, overlap: int = 120) -> "LocalRAGIndex":
        text = path.read_text(encoding="utf-8")
        chunks: list[RAGChunk] = []
        i = 0
        cursor = 0
        while cursor < len(text):
            end = min(len(text), cursor + chunk_size)
            snippet = text[cursor:end].strip()
            if snippet:
                chunks.append(
                    RAGChunk(
                        chunk_id=f"local-{i}",
                        text=snippet,
                        source=str(path),
                        embedding=simple_embed(snippet),
                        keywords=_tokenize(snippet),
                    )
                )
                i += 1
            if end == len(text):
                break
            cursor = max(end - overlap, cursor + 1)
        return cls(chunks)

    def search(self, query: str, top_k: int = 4) -> list[RAGChunk]:
        """Return top-k chunks by blended lexical and embedding score."""
        q_embed = simple_embed(query)
        q_tokens = _tokenize(query)
        scored: list[tuple[float, RAGChunk]] = []
        for chunk in self._chunks:
            lex = 0.0
            if q_tokens:
                lex = len(q_tokens.intersection(chunk.keywords)) / len(q_tokens)
            sem = cosine_similarity(q_embed, chunk.embedding)
            score = 0.45 * lex + 0.55 * sem
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]


class WebRetriever:
    """Optional web retriever supporting Tavily and Serper APIs."""

    def __init__(self, tavily_api_key: str | None, serper_api_key: str | None) -> None:
        self._tavily_key = tavily_api_key
        self._serper_key = serper_api_key

    async def retrieve(self, query: str, limit: int = 3) -> list[dict[str, str]]:
        """Return web snippets from configured provider, else empty list."""
        if self._tavily_key:
            return await self._retrieve_tavily(query=query, limit=limit)
        if self._serper_key:
            return await self._retrieve_serper(query=query, limit=limit)
        return []

    async def _retrieve_tavily(self, query: str, limit: int) -> list[dict[str, str]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._tavily_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": limit,
                },
            )
            response.raise_for_status()
            data = response.json()
        out: list[dict[str, str]] = []
        for item in data.get("results", [])[:limit]:
            out.append(
                {
                    "title": str(item.get("title", "")),
                    "url": str(item.get("url", "")),
                    "snippet": str(item.get("content", ""))[:420],
                }
            )
        return out

    async def _retrieve_serper(self, query: str, limit: int) -> list[dict[str, str]]:
        headers = {"X-API-KEY": str(self._serper_key), "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": limit},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        out: list[dict[str, str]] = []
        for item in data.get("organic", [])[:limit]:
            out.append(
                {
                    "title": str(item.get("title", "")),
                    "url": str(item.get("link", "")),
                    "snippet": str(item.get("snippet", ""))[:420],
                }
            )
        return out


class HybridRAG:
    """Hybrid retriever combining local guide retrieval and optional web context."""

    def __init__(self, local_index: LocalRAGIndex, web_retriever: WebRetriever) -> None:
        self._local_index = local_index
        self._web_retriever = web_retriever

    async def retrieve(self, query: str, top_k_local: int = 4) -> dict[str, Any]:
        """Retrieve from local index and optionally from web when confidence is low."""
        local = self._local_index.search(query, top_k=top_k_local)
        coverage = 0.0
        q_tokens = _tokenize(query)
        if q_tokens and local:
            union = set().union(*(chunk.keywords for chunk in local))
            coverage = len(q_tokens.intersection(union)) / max(len(q_tokens), 1)

        web: list[dict[str, str]] = []
        # If local coverage looks weak, augment with internet retrieval.
        if coverage < 0.25:
            web = await self._web_retriever.retrieve(query, limit=3)

        return {
            "coverage": coverage,
            "local_chunks": [
                {"chunk_id": chunk.chunk_id, "source": chunk.source, "text": chunk.text}
                for chunk in local
            ],
            "web_results": web,
        }
