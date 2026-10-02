#!/usr/bin/env python3
"""Monitor long LeRobot training runs for post-crash diagnosis.

This script is intentionally passive. It does not start/stop training, models,
printers, cameras, or robot processes. It samples host state into JSONL so a
hard reset, power loss, GPU hang, or service restart storm can be diagnosed
from the last flushed records.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "runs" / "training_watch"
_STOP = False


def _handle_stop(signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], *, timeout: float = 8.0) -> dict[str, Any]:
    exe = cmd[0]
    if shutil.which(exe) is None and not Path(exe).exists():
        return {"ok": False, "error": f"not_found:{exe}", "cmd": cmd}
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "cmd": cmd}
    except Exception as exc:  # pragma: no cover - diagnostic fallback.
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "cmd": cmd}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "cmd": cmd,
    }


def _tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    try:
        return subprocess.run(
            ["tail", "-n", str(lines), str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except Exception as exc:  # pragma: no cover - diagnostic fallback.
        return f"tail_failed:{type(exc).__name__}: {exc}"


def _read_training_step(checkpoint_dir: Path | None) -> dict[str, Any]:
    if checkpoint_dir is None:
        return {}
    path = checkpoint_dir / "training_state" / "training_step.json"
    if not path.exists():
        return {"checkpoint_dir": str(checkpoint_dir), "step_file": "missing"}
    try:
        return {"checkpoint_dir": str(checkpoint_dir), "training_step": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"checkpoint_dir": str(checkpoint_dir), "step_file_error": f"{type(exc).__name__}: {exc}"}


def sample(args: argparse.Namespace) -> dict[str, Any]:
    since = f"{max(args.interval_seconds * 2, 10)} seconds ago"
    checkpoint_dir = Path(args.checkpoint_dir).expanduser() if args.checkpoint_dir else None
    train_log = Path(args.train_log).expanduser() if args.train_log else None
    return {
        "ts": _now(),
        "hostname": os.uname().nodename,
        "uptime": _run(["uptime"], timeout=3),
        "memory": _run(["free", "-h"], timeout=3),
        "disk": _run(["df", "-h", "/", str(ROOT)], timeout=3),
        "gpu": _run([
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,temperature.gpu,power.draw,utilization.gpu",
            "--format=csv,noheader,nounits",
        ], timeout=5),
        "top_processes": _run([
            "bash",
            "-lc",
            "ps -eo pid,ppid,stat,%cpu,%mem,rss,comm,args --sort=-rss | head -20",
        ], timeout=5),
        "kernel_recent_warnings": _run([
            "journalctl",
            "-k",
            "--since",
            since,
            "-p",
            "warning..alert",
            "--no-pager",
        ], timeout=5),
        "system_recent_errors": _run([
            "journalctl",
            "--since",
            since,
            "-p",
            "err..alert",
            "--no-pager",
        ], timeout=5),
        "ollama_service": _run(["systemctl", "is-active", "ollama.service"], timeout=3),
        "ollama_recent": _run([
            "journalctl",
            "-u",
            "ollama.service",
            "--since",
            since,
            "--no-pager",
        ], timeout=5),
        "checkpoint": _read_training_step(checkpoint_dir),
        "train_log_tail": _tail_file(train_log, args.log_tail_lines) if train_log else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Passive host monitor for long LeRobot/Pi0.5 training runs.")
    parser.add_argument("--interval-seconds", type=float, default=30.0, help="Sampling interval. Default: 30 seconds.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT), help="Directory for monitor JSONL and summary files.")
    parser.add_argument("--train-log", default="", help="Optional LeRobot training log to tail in each sample.")
    parser.add_argument("--checkpoint-dir", default="", help="Optional checkpoint dir, e.g. outputs/train/run/checkpoints/000500.")
    parser.add_argument("--log-tail-lines", type=int, default=30, help="Training log lines to include per sample.")
    parser.add_argument("--once", action="store_true", help="Write one sample and exit.")
    args = parser.parse_args()

    out_dir = Path(args.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("training-watch-%Y%m%dT%H%M%S")
    jsonl_path = out_dir / f"{run_id}.jsonl"
    summary_path = out_dir / f"{run_id}.summary.txt"

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    header = {
        "run_id": run_id,
        "started_at": _now(),
        "output_jsonl": str(jsonl_path),
        "train_log": args.train_log,
        "checkpoint_dir": args.checkpoint_dir,
        "interval_seconds": args.interval_seconds,
    }
    summary_path.write_text(json.dumps(header, indent=2) + "\n", encoding="utf-8")
    print(f"writing {jsonl_path}", flush=True)

    with jsonl_path.open("a", encoding="utf-8") as handle:
        while True:
            record = sample(args)
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            if args.once or _STOP:
                break
            time.sleep(max(args.interval_seconds, 1.0))

    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ended_at": _now(), "stopped": _STOP or args.once}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
