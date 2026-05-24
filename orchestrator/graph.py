"""
File purpose:
- LangGraph-style explicit node execution and stage transition wrapper.

Key classes/functions:
- OrchestrationGraph

Inputs/outputs:
- Input: stage and guardian decision
- Output: next stage

Dependencies:
- orchestrator.transitions.default_next_stage

Modification guide:
- Safe places to edit: transition policies and branch logic
- Risky places to edit: terminal stage handling
- Related files: orchestrator/run_loop.py, orchestrator/transitions.py
"""

from __future__ import annotations

from orchestrator.state import Stage
from orchestrator.transitions import default_next_stage


class OrchestrationGraph:
    """Explicit transition graph for the autonomous loop."""

    def next_stage(self, current: Stage, guardian_decision: str = "continue") -> Stage:
        """Compute next stage deterministically from current stage and decisions."""
        return default_next_stage(current=current, guardian_decision=guardian_decision)
