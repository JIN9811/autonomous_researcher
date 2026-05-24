"""
File purpose:
- Uncertainty estimation helper placeholder.

Key classes/functions:
- estimate_uncertainty

Inputs/outputs:
- Input: observed values
- Output: scalar uncertainty score

Dependencies:
- statistics

Modification guide:
- Safe places to edit: uncertainty formula
- Risky places to edit: stability when list is empty
- Related files: learning/evaluation.py, agents/analysis_agent.py
"""

from __future__ import annotations

import statistics


def estimate_uncertainty(values: list[float]) -> float:
    """Return simple uncertainty estimate from sample variance."""
    if len(values) < 2:
        return 1.0
    return float(statistics.pstdev(values))
