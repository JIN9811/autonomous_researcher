"""
File purpose:
- GUI abstraction entrypoint for compatibility with non-web frontends.

Key classes/functions:
- MainWindowSpec

Inputs/outputs:
- Input: panel metadata list
- Output: serializable window specification

Dependencies:
- dataclasses

Modification guide:
- Safe places to edit: panel list schema
- Risky places to edit: compatibility key names used by external adapters
- Related files: gui/panels/*.py, web/templates/index.html
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MainWindowSpec:
    """Serializable GUI layout metadata."""

    title: str = "Autonomous AI Researcher"
    panels: list[str] = field(
        default_factory=lambda: [
            "global_overview",
            "agent_status",
            "device_status",
            "run_control",
            "log_viewer",
            "experiment_memory",
            "config",
        ]
    )
