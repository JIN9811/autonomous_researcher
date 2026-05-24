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

from experiments.job_queue import DeviceJobQueue

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class ToolRegistry:
    """Runtime registry for pluggable tools."""

    def __init__(self, job_queue: DeviceJobQueue | None = None) -> None:
        self._tools: dict[str, ToolHandler] = {}
        self._tool_devices: dict[str, str] = {}
        self._job_queue = job_queue or DeviceJobQueue()

    def register(self, name: str, handler: ToolHandler, *, device: str | None = None) -> None:
        """Register or replace a tool handler."""
        self._tools[name] = handler
        if device:
            self._tool_devices[name] = device
        else:
            self._tool_devices.pop(name, None)

    def call(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a registered tool by name."""
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        normalized = payload or {}
        if name in self._tool_devices:
            return self._job_queue.submit_sync(
                device=self._tool_devices[name],
                tool_name=name,
                handler=self._tools[name],
                payload=normalized,
            )
        return self._tools[name](normalized)

    def list_tools(self) -> list[str]:
        """Return sorted list of registered tool names."""
        return sorted(self._tools.keys())

    def queue_status(self) -> dict[str, Any]:
        """Return current device queue/session history."""
        return self._job_queue.status()
