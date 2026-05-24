"""
File purpose:
- Estimate failure precursor probability for manipulation actions.

Key classes/functions:
- predict_failure_precursor

Inputs/outputs:
- Input: progress score and retry count
- Output: precursor probability [0, 1]

Dependencies:
- none

Modification guide:
- Safe places to edit: threshold calibration
- Risky places to edit: safety policy assumptions in guardian logic
- Related files: submodules/sarm/recovery_trigger.py, agents/manipulation_agent.py
"""

from __future__ import annotations


def predict_failure_precursor(progress_score: float, retry_count: int) -> float:
    """Estimate precursor risk from progress and retries."""
    base = 1.0 - progress_score
    retry_penalty = min(0.35, retry_count * 0.1)
    return max(0.0, min(1.0, base + retry_penalty))
