"""
File purpose:
- Deterministic test-mode printer simulator matching printer.prepare schema.

Key classes/functions:
- PrinterSimulator

Inputs/outputs:
- Input: printer.prepare command payload
- Output: structured simulated printer workflow response

Dependencies:
- device_bridges.base_bridge.BaseBridge
- device_bridges.prusa_bridge.PrusaBridgeConfig, PrinterAgenticWorkflow

Modification guide:
- Safe places to edit: simulated status values and artifact naming
- Risky places to edit: response keys consumed by SpecimenMakingAgent
- Related files: mcp_tools/printer_tools.py, agents/specimen_agent.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_bridges.base_bridge import BaseBridge
from device_bridges.prusa_bridge import PrinterAgenticWorkflow, PrusaBridgeConfig


class PrinterSimulator(BaseBridge):
    """Deterministic simulator for specimen preparation commands."""

    def __init__(self, config: PrusaBridgeConfig | None = None, *, repo_root: Path | None = None) -> None:
        cfg = config or PrusaBridgeConfig(mode="test", virtual_prusalink_dry_run=True)
        self.workflow = PrinterAgenticWorkflow(cfg, repo_root=repo_root)

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "prepare":
            prepared = dict(payload)
            prepared["runtime_mode"] = "test"
            return self.workflow.prepare(prepared)
        if command == "health":
            return self.workflow.health({"runtime_mode": "test"})
        return {"ok": False, "bridge": "printer_sim", "command": command, "failure_code": "UNKNOWN_PRINTER_COMMAND"}
