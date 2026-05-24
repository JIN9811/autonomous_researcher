"""
File purpose:
- Provide first-class structured logging across system, agents, tools, and experiments.

Key classes/functions:
- StructuredLogEvent
- StructuredLogger

Inputs/outputs:
- Input: log event metadata and payload dictionaries
- Output: JSONL records + readable summary logs

Dependencies:
- dataclasses
- json
- pathlib.Path
- threading.Lock

Modification guide:
- Safe places to edit: payload fields and readable format text
- Risky places to edit: schema keys used by GUI filters
- Related files: logging_system/logger_factory.py, app/controller.py
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass(slots=True)
class StructuredLogEvent:
    """Normalized log event schema used across all logging layers."""

    timestamp: str
    run_id: str
    experiment_id: str | None
    level: str
    layer: str
    event_type: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


class StructuredLogger:
    """Thread-safe logger that writes both JSONL and human-readable summaries."""

    def __init__(self, jsonl_path: Path, summary_path: Path) -> None:
        self._jsonl_path = jsonl_path
        self._summary_path = summary_path
        self._lock = Lock()
        self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._summary_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        *,
        run_id: str,
        level: str,
        layer: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
        experiment_id: str | None = None,
    ) -> StructuredLogEvent:
        """Emit one structured event to both sinks and return it."""
        event = StructuredLogEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            run_id=run_id,
            experiment_id=experiment_id,
            level=level.upper(),
            layer=layer,
            event_type=event_type,
            message=message,
            payload=payload or {},
        )
        with self._lock:
            with self._jsonl_path.open("a", encoding="utf-8") as jf:
                jf.write(json.dumps(asdict(event), ensure_ascii=True) + "\n")
            with self._summary_path.open("a", encoding="utf-8") as sf:
                sf.write(
                    f"[{event.timestamp}] {event.level} {event.layer}/{event.event_type} "
                    f"run={event.run_id} exp={event.experiment_id or '-'} :: {event.message}\n"
                )
        return event
