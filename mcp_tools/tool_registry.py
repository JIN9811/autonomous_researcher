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
from utils.agent_artifact_archive import record_tool_artifact

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class ToolRegistry:
    """Runtime registry for pluggable tools."""

    def __init__(self, job_queue: DeviceJobQueue | None = None) -> None:
        self._tools: dict[str, ToolHandler] = {}
        self._tool_devices: dict[str, str] = {}
        self._resources: dict[str, Any] = {}
        self._job_queue = job_queue or DeviceJobQueue()

    def register(self, name: str, handler: ToolHandler, *, device: str | None = None) -> None:
        """Register or replace a tool handler."""
        self._tools[name] = handler
        if device:
            self._tool_devices[name] = device
        else:
            self._tool_devices.pop(name, None)

    def register_resource(self, name: str, resource: Any) -> None:
        """Expose a shared runtime resource without making it an executable tool."""
        self._resources[name] = resource

    def resource(self, name: str) -> Any | None:
        """Return a shared runtime resource registered by a tool package."""
        return self._resources.get(name)

    def call(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a registered tool by name."""
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        normalized = payload or {}
        record_tool_artifact("tool_started", name, normalized)
        try:
            if name in self._tool_devices:
                result = self._job_queue.submit_sync(
                    device=self._tool_devices[name],
                    tool_name=name,
                    handler=self._tools[name],
                    payload=normalized,
                )
            else:
                result = self._tools[name](normalized)
        except Exception as exc:
            record_tool_artifact("tool_failed", name, {"error_type": type(exc).__name__})
            raise
        record_tool_artifact("tool_result", name, result)
        return result

    def list_tools(self) -> list[str]:
        """Return sorted list of registered tool names."""
        return sorted(self._tools.keys())

    def queue_status(self) -> dict[str, Any]:
        """Return current device queue/session history."""
        return self._job_queue.status()
