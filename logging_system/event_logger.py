"""
File purpose:
- Convenience wrapper for system and agent event logging.

Key classes/functions:
- log_system_event
- log_agent_event

Inputs/outputs:
- Input: StructuredLogger and event metadata
- Output: persisted structured log events

Dependencies:
- logging_system.structured_logger.StructuredLogger

Modification guide:
- Safe places to edit: helper signatures and payload shape
- Risky places to edit: field names expected by GUI filters
- Related files: app/controller.py, orchestrator/run_loop.py
"""

from __future__ import annotations

from typing import Any

from logging_system.structured_logger import StructuredLogger


def log_system_event(
    logger: StructuredLogger,
    *,
    run_id: str,
    level: str,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Log a framework-level event."""
    logger.emit(
        run_id=run_id,
        level=level,
        layer="system",
        event_type=event_type,
        message=message,
        payload=payload,
    )


def log_agent_event(
    logger: StructuredLogger,
    *,
    run_id: str,
    agent_name: str,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
    experiment_id: str | None = None,
) -> None:
    """Log an agent-level event."""
    logger.emit(
        run_id=run_id,
        level="INFO",
        layer=f"agent:{agent_name}",
        event_type=event_type,
        message=message,
        payload=payload,
        experiment_id=experiment_id,
    )
