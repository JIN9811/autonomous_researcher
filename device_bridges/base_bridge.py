"""
File purpose:
- Abstract base contract for swappable hardware bridges.

Key classes/functions:
- BaseBridge

Inputs/outputs:
- Input: structured command payload
- Output: structured response dictionary

Dependencies:
- abc.ABC

Modification guide:
- Safe places to edit: optional metadata fields
- Risky places to edit: abstract method signatures
- Related files: device_bridges/*.py, mcp_tools/*.py
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseBridge(ABC):
    """Base class for live and simulated device bridges."""

    @abstractmethod
    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute one bridge command."""
        raise NotImplementedError
