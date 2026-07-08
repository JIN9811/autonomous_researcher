#!/usr/bin/env python3
"""Isaac Lab Mimic + IL sidecar smoke runner.

This script is non-actuating unless called with ``--mode live``. In test/dry
mode it verifies the same sidecar contracts used by the GUI without touching
teleoperation, recording, Isaac Sim mirror runtime, or robot hardware.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bridge(repo_root: Path):
    from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
    from utils.config_loader import load_all_configs

    cfg = load_all_configs(repo_root / "configs")
    return LeRobotBridge(LeRobotBridgeConfig.from_config(cfg.get("lerobot", {}), repo_root=repo_root))


def _wait_job(bridge: Any, kind: str, payload: dict[str, Any], result: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    if str(result.get("status") or "").upper() != "RUNNING":
        return result
    job_id = str(result.get("job_id") or "")
    deadline = time.monotonic() + max(1.0, float(timeout_s))
    status_payload = {**payload, "job_id": job_id}
    while time.monotonic() < deadline:
        status = bridge._isaac_lab_job_status(kind, status_payload)
        if str(status.get("status") or "").upper() != "RUNNING":
            return status
        time.sleep(2.0)
    return bridge._isaac_lab_job_stop(kind, status_payload)


def _stage_completed(result: dict[str, Any]) -> bool:
    status = str(result.get("status") or "").upper()
    if status == "COMPLETED":
        return True
    job = result.get("job") if isinstance(result.get("job"), dict) else {}
    if str(job.get("status") or "").upper() == "COMPLETED":
        return True
    annotation = ((result.get("hdf5") or {}).get("annotation") if isinstance(result.get("hdf5"), dict) else {})
    return isinstance(annotation, dict) and str(annotation.get("status") or "").lower() == "completed"


def _run_live_sequence(
    bridge: Any,
    payload: dict[str, Any],
    *,
    timeout_s: float,
    include_il_train: bool = False,
) -> dict[str, Any]:
    build = bridge.isaac_lab_build_synthetic(payload)
    export = bridge.isaac_lab_export_hdf5(payload)
    annotate = _wait_job(bridge, "annotate", payload, bridge.isaac_lab_annotate(payload), timeout_s)
    mimic = {}
    training_import_refresh = {}
    train = {}
    eval_result = {}
    if _stage_completed(annotate):
        mimic = _wait_job(bridge, "mimic", payload, bridge.isaac_lab_run_mimic(payload), timeout_s)
    if _stage_completed(mimic):
        training_import_refresh = bridge.isaac_lab_build_synthetic(payload)
    if include_il_train and bool(training_import_refresh.get("ok")):
        train = _wait_job(bridge, "il_train", payload, bridge.isaac_lab_train_il(payload), timeout_s)
    if include_il_train and _stage_completed(train):
        eval_result = _wait_job(bridge, "il_eval", payload, bridge.isaac_lab_eval_il(payload), timeout_s)
    ok = bool(build.get("ok")) and bool(export.get("ok"))
    ok = ok and _stage_completed(annotate)
    ok = ok and _stage_completed(mimic)
    ok = ok and bool(training_import_refresh.get("ok"))
    if include_il_train:
        ok = ok and _stage_completed(train)
        ok = ok and _stage_completed(eval_result)
    return {
        "ok": ok,
        "tool": "lerobot.isaac_lab.e2e_live_smoke",
        "status": "COMPLETED" if include_il_train and ok else "READY_FOR_VLA_TRAINING_IMPORT" if ok else "BLOCKED",
        "build": build,
        "export": export,
        "annotation": annotate,
        "mimic": mimic,
        "training_import_refresh": training_import_refresh,
        "train": train,
        "eval": eval_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Isaac Lab Mimic + IL E2E sidecar smoke.")
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--isaac-lab-path", default="/home/jin/IsaacLab")
    parser.add_argument("--isaac-sim-python", default="/home/jin/IsaacSim/python.sh")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--num-envs", type=int, default=1)
    parser.add_argument("--domain-randomization-profile", default="conservative")
    parser.add_argument("--repo-root", default=str(_repo_root()))
    parser.add_argument("--create-fixture", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--episodes", type=int, default=5)
    parser.add_argument("--episode-s", type=int, default=10)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--mimic-camera-width", type=int, default=320)
    parser.add_argument("--mimic-camera-height", type=int, default=240)
    parser.add_argument("--mimic-enable-cameras", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--mode", choices=("test", "live"), default="test")
    parser.add_argument("--stage-timeout-s", type=float, default=1800.0)
    parser.add_argument("--visualize-generation", action="store_true", default=False)
    parser.add_argument("--include-il-train", action="store_true", default=False)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).expanduser().resolve()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    dataset_path = Path(args.dataset_path).expanduser().resolve()
    if args.create_fixture:
        from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

        build_fixture_recording_dataset(
            dataset_path,
            episodes=args.episodes,
            episode_s=args.episode_s,
            fps=args.fps,
        )

    bridge = _bridge(repo_root)
    policy_task_name = (
        "ATR-Robotis-OMX-PickPlace-Physical-v0"
        if bool(args.mimic_enable_cameras)
        else "ATR-Robotis-OMX-PickPlace-Physical-State-v0"
    )
    payload = {
        "mode": args.mode,
        "dataset_path": str(dataset_path),
        "isaac_lab_path": str(Path(args.isaac_lab_path).expanduser()),
        "isaac_sim_python": str(Path(args.isaac_sim_python).expanduser()),
        "mimic_trials": args.trials,
        "mimic_num_envs": args.num_envs,
        "domain_randomization_profile": args.domain_randomization_profile,
        "dry_run": bool(args.dry_run or args.mode != "live"),
        "enable_mimic": True,
        "enable_hdf5_export": True,
        "enable_replicator": False,
        "enable_rl_teacher": False,
        "e2e_episodes": args.episodes,
        "e2e_episode_s": args.episode_s,
        "e2e_fps": args.fps,
        "isaac_lab_visualize_generation": bool(args.visualize_generation),
        "mimic_enable_cameras": bool(args.mimic_enable_cameras),
        "mimic_camera_width": int(args.mimic_camera_width),
        "mimic_camera_height": int(args.mimic_camera_height),
        "mimic_annotation_mode": "preannotated_passthrough",
        "isaac_lab_policy_task_name": policy_task_name,
        "require_digital_twin_pass": False,
        "require_physics_pass": False,
        "require_depth_pass": False,
        "require_articulation_pass": False,
        "max_source_frames": int(args.episodes * args.episode_s * args.fps),
        "source_intent": "train_ready_success_only",
    }
    result = (
        _run_live_sequence(
            bridge,
            payload,
            timeout_s=args.stage_timeout_s,
            include_il_train=bool(args.include_il_train),
        )
        if args.mode == "live" and not payload["dry_run"]
        else bridge.isaac_lab_run_e2e(payload)
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
