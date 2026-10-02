"""
File purpose:
- Backward-compatible import path for the LangGraph-backed orchestration loop.

Key classes/functions:
- RunLoop
- LangGraphRunLoop

Inputs/outputs:
- Input: same constructor arguments as the previous RunLoop
- Output: compiled LangGraph runtime execution

Dependencies:
- orchestrator.langgraph_runtime

Modification guide:
- Safe places to edit: compatibility aliases
- Risky places to edit: changing public import names used by tests/controllers
- Related files: app/controller.py, orchestrator/langgraph_runtime.py
"""

from __future__ import annotations

from orchestrator.langgraph_runtime import EventCallback, LangGraphRunLoop

RunLoop = LangGraphRunLoop

__all__ = ["EventCallback", "LangGraphRunLoop", "RunLoop"]
