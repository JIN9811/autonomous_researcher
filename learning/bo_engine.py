"""
File purpose:
- Bayesian optimization engine placeholder.

Key classes/functions:
- propose_next

Inputs/outputs:
- Input: candidate vectors and scores
- Output: selected next candidate index

Dependencies:
- none

Modification guide:
- Safe places to edit: acquisition logic
- Risky places to edit: objective direction assumptions
- Related files: learning/surrogate_model.py, agents/design_agent.py
"""

from __future__ import annotations


def propose_next(candidates: list[list[float]], scores: list[float]) -> int:
    """Select next candidate index with simple best-improvement heuristic."""
    if not candidates:
        return 0
    if not scores:
        return 0
    return int(max(range(len(scores)), key=lambda i: scores[i]))
