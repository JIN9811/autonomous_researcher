"""
File purpose:
- Score manipulation progress for SARM submodule integration.

Key classes/functions:
- score_progress

Inputs/outputs:
- Input: grasp score and anomaly flag
- Output: normalized progress score [0, 1]

Dependencies:
- none

Modification guide:
- Safe places to edit: weighting constants
- Risky places to edit: output range assumptions in recovery logic
- Related files: submodules/sarm/failure_predictor.py, agents/manipulation_agent.py
"""

from __future__ import annotations


def score_progress(grasp_score: float, anomaly: bool) -> float:
    """Compute progress score from manipulation signal quality."""
    penalty = 0.25 if anomaly else 0.0
    return max(0.0, min(1.0, grasp_score - penalty))
