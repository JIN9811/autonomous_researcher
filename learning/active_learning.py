"""
File purpose:
- Active learning candidate selection placeholder.

Key classes/functions:
- select_uncertain

Inputs/outputs:
- Input: list of uncertainty values
- Output: index of most uncertain sample

Dependencies:
- none

Modification guide:
- Safe places to edit: selection policy
- Risky places to edit: assumptions about uncertainty scale
- Related files: learning/uncertainty.py, agents/design_agent.py
"""

from __future__ import annotations


def select_uncertain(uncertainties: list[float]) -> int:
    """Return index with highest uncertainty."""
    if not uncertainties:
        return 0
    return int(max(range(len(uncertainties)), key=lambda i: uncertainties[i]))
