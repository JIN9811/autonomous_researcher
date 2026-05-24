"""
File purpose:
- Compatibility wrapper exposing experiment DB from knowledge package.

Key classes/functions:
- ExperimentDB

Inputs/outputs:
- Input: memory records
- Output: in-memory record storage and lookup

Dependencies:
- knowledge.experiment_db.ExperimentDB

Modification guide:
- Safe places to edit: extension methods
- Risky places to edit: breaking compatibility import path
- Related files: knowledge/experiment_db.py, agents/knowledge_agent.py
"""

from knowledge.experiment_db import ExperimentDB

__all__ = ["ExperimentDB"]
