"""
File purpose:
- Decide whether recovery should be triggered based on SARM risk estimate.

Key classes/functions:
- should_trigger_recovery

Inputs/outputs:
- Input: precursor probability
- Output: bool trigger decision

Dependencies:
- none

Modification guide:
- Safe places to edit: threshold value
- Risky places to edit: coupling with guardian stop policy
- Related files: agents/manipulation_agent.py, policies/recovery_policy.py
"""

from __future__ import annotations


def should_trigger_recovery(precursor_probability: float, threshold: float = 0.62) -> bool:
    """Return True when recovery should be suggested."""
    return precursor_probability >= threshold
