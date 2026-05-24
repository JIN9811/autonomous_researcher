"""
File purpose:
- Resolve stage to agent routing with explicit, inspectable mapping.

Key classes/functions:
- stage_to_agent

Inputs/outputs:
- Input: current stage
- Output: target agent name or None

Dependencies:
- orchestrator.state.Stage

Modification guide:
- Safe places to edit: stage-agent map
- Risky places to edit: unknown stage behavior in run loop
- Related files: orchestrator/run_loop.py, agents/registry.py
"""

from __future__ import annotations

from orchestrator.state import Stage

_MAP: dict[Stage, str] = {
    Stage.DESIGN: "design_agent",
    Stage.SPECIMEN: "specimen_agent",
    Stage.VISION: "vision_agent",
    Stage.MANIPULATION: "manipulation_agent",
    Stage.EQUIPMENT: "equipment_agent",
    Stage.ANALYSIS: "analysis_agent",
    Stage.KNOWLEDGE: "knowledge_agent",
    Stage.GUARDIAN: "guardian_agent",
}


def stage_to_agent(stage: Stage) -> str | None:
    """Return the agent name for a stage or None when no agent is bound."""
    return _MAP.get(stage)
