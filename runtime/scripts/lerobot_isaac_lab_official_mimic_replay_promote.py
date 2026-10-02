#!/usr/bin/env python3
"""Replay official Isaac Lab Mimic candidates and promote replay-passed rows."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    tmp.replace(path)


def _isaac_python_command(isaac_python: str, script: Path) -> list[str]:
    executable = Path(isaac_python).expanduser()
    command = [str(executable)]
    if executable.name == "isaaclab.sh":
        command.append("-p")
    command.append(str(script.expanduser()))
    return command


def _demo_index(value: Any, fallback: int) -> int:
    text = str(value or "").strip()
    match = re.fullmatch(r"demo_(\d+)", text)
    if match:
        return int(match.group(1))
    try:
        return int(text)
    except ValueError:
        return int(fallback)


def _replay_passed(log_text: str, returncode: int) -> bool:
    if returncode != 0:
        return False
    if re.search(r"Successfully replayed:\s*1\s*/\s*1", log_text):
        return "Failed demo IDs" not in log_text
    if re.search(r"Successfully replayed\s+1\s+episode\s+out\s+of\s+1\s+demos", log_text):
        return "Failed demo IDs" not in log_text
    return False


def _replay_command(args: argparse.Namespace, demo_index: int) -> list[str]:
    command = [
        *_isaac_python_command(args.isaac_python, Path(args.replay_script)),
        "--task",
        args.task,
        "--dataset_file",
        str(Path(args.dataset_file).expanduser()),
        "--select_episodes",
        str(demo_index),
        "--validate_success_rate",
        "--reset_sim_buffer_each_episode",
        "--external_callback",
        args.external_callback,
    ]
    if args.headless:
        command.append("--headless")
    if args.enable_cameras:
        command.append("--enable_cameras")
        command.extend(["--rendering_mode", args.rendering_mode])
    return command


def _run_replay(command: list[str], log_path: Path) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return int(proc.returncode), text


def _promoted_row(row: dict[str, Any], *, passed: bool, replay: dict[str, Any]) -> dict[str, Any]:
    updated = dict(row)
    metrics = dict(updated.get("metrics") if isinstance(updated.get("metrics"), dict) else {})
    training = dict(updated.get("training") if isinstance(updated.get("training"), dict) else {})
    metrics["replay_validated"] = True
    metrics["replay_required"] = False
    metrics["lab_step_replay"] = bool(passed)
    training["eligible"] = bool(passed)
    training["exclusion_reason"] = "" if passed else "official_replay_validation_failed"
    updated["metrics"] = metrics
    updated["training"] = training
    updated["replay_validation"] = replay
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay-validate and promote official Isaac Lab Mimic successes.")
    parser.add_argument("--isaac-python", required=True)
    parser.add_argument("--replay-script", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--dataset-file", required=True)
    parser.add_argument("--success-manifest", required=True)
    parser.add_argument("--replay-success-manifest", required=True)
    parser.add_argument("--replay-failure-manifest", required=True)
    parser.add_argument("--summary-file", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--external-callback", default="integrations.isaac_lab_robotis_omx.external_callback.register")
    parser.add_argument("--rendering-mode", default="performance")
    parser.add_argument("--enable-cameras", action="store_true")
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args(argv)

    success_manifest = Path(args.success_manifest).expanduser()
    replay_success_manifest = Path(args.replay_success_manifest).expanduser()
    replay_failure_manifest = Path(args.replay_failure_manifest).expanduser()
    summary_file = Path(args.summary_file).expanduser()
    log_dir = Path(args.log_dir).expanduser()

    rows = _read_jsonl(success_manifest)
    updated_rows: list[dict[str, Any]] = []
    replay_successes: list[dict[str, Any]] = []
    replay_failures: list[dict[str, Any]] = []

    for ordinal, row in enumerate(rows):
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        generated_demo = str(row.get("generated_demo") or f"demo_{ordinal}").strip()
        needs_replay = bool(metrics.get("official_mimic")) and bool(metrics.get("replay_required"))
        if not needs_replay:
            updated_rows.append(row)
            continue
        demo_index = _demo_index(generated_demo, ordinal)
        log_path = log_dir / f"{generated_demo or f'demo_{demo_index}'}.log"
        command = _replay_command(args, demo_index)
        returncode, log_text = _run_replay(command, log_path)
        passed = _replay_passed(log_text, returncode)
        replay = {
            "schema": "atr.lerobot.isaac_lab_mimic.replay_validation.v1",
            "status": "passed" if passed else "failed",
            "returncode": returncode,
            "generated_demo": generated_demo,
            "selected_episode": demo_index,
            "command": command,
            "log_path": str(log_path),
        }
        updated = _promoted_row(row, passed=passed, replay=replay)
        updated_rows.append(updated)
        if passed:
            replay_successes.append(updated)
        else:
            replay_failures.append(updated)

    _write_jsonl(success_manifest, updated_rows)
    _write_jsonl(replay_success_manifest, replay_successes)
    _write_jsonl(replay_failure_manifest, replay_failures)
    summary = {
        "schema": "atr.lerobot.isaac_lab_mimic.replay_promotion.summary.v1",
        "ok": True,
        "status": "completed",
        "dataset_file": str(Path(args.dataset_file).expanduser()),
        "success_manifest": str(success_manifest),
        "replay_success_manifest": str(replay_success_manifest),
        "replay_failure_manifest": str(replay_failure_manifest),
        "candidate_count": len(rows),
        "replay_success_count": len(replay_successes),
        "replay_failure_count": len(replay_failures),
        "promoted_count": len(replay_successes),
        "training_eligible_count": sum(
            1
            for row in updated_rows
            if bool((row.get("training") if isinstance(row.get("training"), dict) else {}).get("eligible"))
        ),
    }
    _write_json(summary_file, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
