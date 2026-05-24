"""
File purpose:
- Compatibility wrapper exposing failure memory store.

Key classes/functions:
- FailureMemory
- FailureRecord

Inputs/outputs:
- Input: failure records
- Output: recent failure retrieval

Dependencies:
- knowledge.failure_memory

Modification guide:
- Safe places to edit: additive helper methods
- Risky places to edit: import compatibility
- Related files: knowledge/failure_memory.py, agents/guardian_agent.py
"""

from knowledge.failure_memory import FailureMemory, FailureRecord

__all__ = ["FailureMemory", "FailureRecord"]
