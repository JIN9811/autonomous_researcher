"""
File purpose:
- Helpers for launching dry-run and replay-oriented orchestration sessions.

Key classes/functions:
- run_dry_loop

Inputs/outputs:
- Input: configured RunLoop instance
- Output: terminal orchestration state

Dependencies:
- orchestrator.run_loop.RunLoop

Modification guide:
- Safe places to edit: dry-run defaults
- Risky places to edit: behavior assumptions in CLI/API
- Related files: app/controller.py, app/cli.py
"""

from __future__ import annotations

from orchestrator.run_loop import RunLoop
from orchestrator.state import Mode, OrchestratorState, Stage


async def run_dry_loop(loop: RunLoop, state: OrchestratorState, max_cycles: int = 3) -> OrchestratorState:
    """Run bounded dry loop for quick validation without hardware."""
    state.mode = Mode.TEST
    while state.stage not in {Stage.COMPLETE, Stage.ERROR} and state.loop_count < max_cycles:
        await loop.step()
    if state.stage not in {Stage.COMPLETE, Stage.ERROR}:
        state.stage = Stage.COMPLETE
    return state
