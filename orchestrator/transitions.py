"""
File purpose:
- Define explicit stage transitions for the orchestration graph.

Key classes/functions:
- default_next_stage
- ordered_stages

Inputs/outputs:
- Input: current stage and guardian decision
- Output: next stage enum

Dependencies:
- orchestrator.state.Stage

Modification guide:
- Safe places to edit: stage ordering and completion conditions
- Risky places to edit: assumptions in run loop and GUI timeline
- Related files: orchestrator/graph.py, orchestrator/run_loop.py
"""

from __future__ import annotations

from orchestrator.state import Stage

ordered_stages: list[Stage] = [
    Stage.DESIGN,
    Stage.SPECIMEN,
    Stage.VISION,
    Stage.MANIPULATION,
    Stage.EQUIPMENT,
    Stage.ANALYSIS,
    Stage.KNOWLEDGE,
    Stage.GUARDIAN,
]


def default_next_stage(current: Stage, guardian_decision: str = "continue") -> Stage:
    """Return next stage based on current stage and optional guardian decision."""
    if current == Stage.IDLE:
        return Stage.DESIGN
    if current == Stage.GUARDIAN:
        if guardian_decision == "stop":
            return Stage.COMPLETE
        if guardian_decision == "error":
            return Stage.ERROR
        return Stage.DESIGN
    if current in ordered_stages:
        idx = ordered_stages.index(current)
        if idx == len(ordered_stages) - 1:
            return Stage.GUARDIAN
        return ordered_stages[idx + 1]
    return Stage.COMPLETE
