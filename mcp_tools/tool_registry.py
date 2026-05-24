"""
File purpose:
- Dynamic registry for MCP-compatible tools with structured inputs/outputs.

Key classes/functions:
- ToolRegistry

Inputs/outputs:
- Input: tool name and parameter payload
- Output: tool execution dictionary

Dependencies:
- collections.abc.Callable

Modification guide:
- Safe places to edit: registration helpers
- Risky places to edit: execution contract used by agents
- Related files: mcp_tools/mock_tools.py, agents/*.py
"""

from __future__ import annotations

from typing import Any, Callable

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class ToolRegistry:
    """Runtime registry for pluggable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        """Register or replace a tool handler."""
        self._tools[name] = handler

    def call(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a registered tool by name."""
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        return self._tools[name](payload or {})

    def list_tools(self) -> list[str]:
        """Return sorted list of registered tool names."""
        return sorted(self._tools.keys())
