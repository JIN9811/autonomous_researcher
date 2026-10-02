#!/usr/bin/env python3
"""Run one LeRobot training command and persist its detached lifecycle state."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("training command is required after --")

    state_path = Path(args.state_path).expanduser().resolve()
    state: dict[str, Any] = {
        "schema": "atr.lerobot.background_train_state.v1",
        "status": "STARTING",
        "runner_pid": os.getpid(),
        "child_pid": None,
        "returncode": None,
        "started_at": _now(),
        "finished_at": "",
    }
    _write_state(state_path, state)
    stopping = False
    child: subprocess.Popen[bytes] | None = None

    def stop_child(signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGTERM, stop_child)
    signal.signal(signal.SIGINT, stop_child)

    try:
        child = subprocess.Popen(command, cwd=args.cwd)
        state.update({"status": "TRAINING", "child_pid": child.pid})
        _write_state(state_path, state)
        returncode = child.wait()
    except BaseException as exc:
        state.update(
            {
                "status": "CANCELLED" if stopping else "FAILED",
                "returncode": -int(signal.SIGTERM) if stopping else 1,
                "finished_at": _now(),
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        )
        _write_state(state_path, state)
        if isinstance(exc, KeyboardInterrupt):
            return 130
        return int(state["returncode"])

    state.update(
        {
            "status": "CANCELLED" if stopping else ("COMPLETED" if returncode == 0 else "FAILED"),
            "returncode": returncode,
            "finished_at": _now(),
        }
    )
    _write_state(state_path, state)
    return int(returncode)


if __name__ == "__main__":
    sys.exit(main())
