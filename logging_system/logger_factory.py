"""
File purpose:
- Build configured logger instances from config and run metadata.

Key classes/functions:
- LoggerBundle
- build_logger_bundle

Inputs/outputs:
- Input: system and logging config dictionaries + run root path
- Output: logger bundle containing StructuredLogger and output paths

Dependencies:
- dataclasses
- pathlib.Path
- logging_system.structured_logger.StructuredLogger

Modification guide:
- Safe places to edit: directory layout and naming strategy
- Risky places to edit: path schema consumed by GUI and tests
- Related files: logging_system/structured_logger.py, app/bootstrap.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logging_system.structured_logger import StructuredLogger


@dataclass(slots=True)
class LoggerBundle:
    """Container for logging resources produced at bootstrap time."""

    logger: StructuredLogger
    run_dir: Path
    json_log_path: Path
    summary_log_path: Path


def build_logger_bundle(
    *,
    run_id: str,
    run_root: Path,
    logging_config: dict[str, Any],
) -> LoggerBundle:
    """Build a logger bundle for a single orchestration run."""
    log_cfg = logging_config.get("logging", {})
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    json_log_path = run_dir / log_cfg.get("json_file", "structured.jsonl")
    summary_log_path = run_dir / log_cfg.get("human_file", "summary.log")
    logger = StructuredLogger(jsonl_path=json_log_path, summary_path=summary_log_path)

    return LoggerBundle(
        logger=logger,
        run_dir=run_dir,
        json_log_path=json_log_path,
        summary_log_path=summary_log_path,
    )
