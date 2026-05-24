"""
File purpose:
- Lightweight local embedding utility for simple lexical+vector-style ranking fallback.

Key classes/functions:
- simple_embed
- cosine_similarity

Inputs/outputs:
- Input: text
- Output: fixed-length float vector

Dependencies:
- math

Modification guide:
- Safe places to edit: hashing dimensions
- Risky places to edit: similarity assumptions used by RAG ranking
- Related files: knowledge/rag.py
"""

from __future__ import annotations

import math

EMBED_DIM = 64


def simple_embed(text: str) -> list[float]:
    """Create a deterministic lightweight embedding from token hashes."""
    vec = [0.0] * EMBED_DIM
    for token in text.lower().split():
        bucket = hash(token) % EMBED_DIM
        vec[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity for equal-length vectors."""
    return sum(x * y for x, y in zip(a, b))
