"""
File purpose:
- Evaluate candidate objective outcomes.

Key classes/functions:
- score_candidate

Inputs/outputs:
- Input: objective and penalty values
- Output: scalar evaluation score

Dependencies:
- none

Modification guide:
- Safe places to edit: weighting coefficients
- Risky places to edit: score direction assumptions
- Related files: learning/bo_engine.py, agents/analysis_agent.py
"""

from __future__ import annotations


def score_candidate(objective: float, penalty: float = 0.0) -> float:
    """Compute weighted candidate score."""
    return objective - 0.5 * penalty
