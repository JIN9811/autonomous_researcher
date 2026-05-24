"""
File purpose:
- CLI entry for launching quick test/live runs without web UI.

Key classes/functions:
- main

Inputs/outputs:
- Input: command-line arguments
- Output: run lifecycle execution and final state summary

Dependencies:
- argparse
- asyncio
- app.bootstrap.load_runtime

Modification guide:
- Safe places to edit: CLI flags and defaults
- Risky places to edit: mode parsing contract with controller
- Related files: app/main.py, orchestrator/state.py
"""

from __future__ import annotations

import argparse
import asyncio

from app.bootstrap import load_runtime
from orchestrator.state import Mode


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Researcher CLI")
    parser.add_argument("--mode", default="test", choices=["live", "test", "replay", "fault-injection"])
    parser.add_argument("--goal", default="Run autonomous researcher loop from CLI")
    parser.add_argument("--fault", default="none")
    parser.add_argument("--fault-stage", default="")
    parser.add_argument("--wait-seconds", type=float, default=8.0)
    args = parser.parse_args()

    controller = load_runtime()
    result = await controller.start(
        mode=Mode(args.mode),
        goal=args.goal,
        fault=args.fault,
        fault_stage=args.fault_stage,
    )
    print(result)
    await asyncio.sleep(args.wait_seconds)
    snapshot = controller.snapshot()
    print(snapshot["state"])


def main() -> None:
    """CLI process entrypoint."""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
