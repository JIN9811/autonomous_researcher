"""
File purpose:
- Compatibility wrapper exposing memory schemas.

Key classes/functions:
- MemoryRecord

Inputs/outputs:
- Input: schema payloads
- Output: validated model instances

Dependencies:
- knowledge.schemas.MemoryRecord

Modification guide:
- Safe places to edit: new schema aliases
- Risky places to edit: compatibility export path
- Related files: knowledge/schemas.py
"""

from knowledge.schemas import MemoryRecord

__all__ = ["MemoryRecord"]
