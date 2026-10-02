"""
File purpose:
- Compatibility wrapper exposing retrieval context formatter.

Key classes/functions:
- format_rag_context

Inputs/outputs:
- Input: retrieval result dictionary
- Output: prompt-ready context string

Dependencies:
- knowledge.retrieval.format_rag_context

Modification guide:
- Safe places to edit: extra helper wrappers
- Risky places to edit: compatibility exports
- Related files: knowledge/retrieval.py
"""

from knowledge.retrieval import format_rag_context

__all__ = ["format_rag_context"]
