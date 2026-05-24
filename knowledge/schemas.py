"""
File purpose:
- Typed schema definitions for knowledge retrieval records.

Key classes/functions:
- MemoryRecord

Inputs/outputs:
- Input: retrieval metadata
- Output: validated Pydantic models

Dependencies:
- pydantic.BaseModel

Modification guide:
- Safe places to edit: additive fields
- Risky places to edit: required fields used in DB serialization
- Related files: knowledge/experiment_db.py, agents/knowledge_agent.py
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """Represents one stored experiment memory snapshot."""

    run_id: str = Field(..., description="Run identifier")
    experiment_id: str = Field(..., description="Experiment identifier")
    summary: str = Field(..., description="Compact memory summary")
    score: float = Field(..., description="Objective score")
    uncertainty: float = Field(..., description="Uncertainty estimate")
