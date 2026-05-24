"""
File purpose:
- Centralized structured error logging helpers.

Key classes/functions:
- log_error

Inputs/outputs:
- Input: exception and optional state snapshot
- Output: structured error event with stack context

Dependencies:
- traceback.format_exc
- logging_system.structured_logger.StructuredLogger

Modification guide:
- Safe places to edit: payload fields
- Risky places to edit: error schema consumed by GUI
- Related files: app/controller.py, orchestrator/run_loop.py
"""

from __future__ import annotations

from typing import Any
import traceback

from logging_system.structured_logger import StructuredLogger


def log_error(
    logger: StructuredLogger,
    *,
    run_id: str,
    where: str,
    error: Exception,
    state_snapshot: dict[str, Any] | None = None,
) -> None:
    """Persist rich structured error information."""
    logger.emit(
        run_id=run_id,
        level="ERROR",
        layer="error",
        event_type="exception",
        message=f"{where}: {error}",
        payload={
            "where": where,
            "exception_type": error.__class__.__name__,
            "stack_trace": traceback.format_exc(),
            "state_snapshot": state_snapshot or {},
            "recommended_action": "switch_to_test_mode_and_retry",
        },
    )
