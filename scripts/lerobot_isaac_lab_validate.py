#!/usr/bin/env python3
"""CLI wrapper for LeRobot Isaac Lab synthetic validation.

The CLI intentionally calls the same bridge methods as the GUI/API path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from utils.config_loader import load_all_configs


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bridge() -> LeRobotBridge:
    repo = _repo_root()
    cfg = load_all_configs(repo / "configs")
    return LeRobotBridge(LeRobotBridgeConfig.from_config(cfg.get("lerobot", {}), repo_root=repo))


def _payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "mode": args.mode,
        "dataset_path": args.dataset,
        "validation_checks": _checks(args.checks),
        "pipeline_mode": args.pipeline_mode,
        "fallback_policy": args.fallback_policy,
        "source_intent": args.source_intent,
        "output_root": args.output_root,
        "isaac_lab_path": args.isaac_lab_path,
        "isaac_sim_python": args.isaac_sim_python,
        "isaac_sim_version": args.isaac_sim_version,
        "isaac_sim_docs_version": args.isaac_sim_docs_version,
        "stage_path": args.stage,
        "cameras": [item.strip() for item in args.cameras.split(",") if item.strip()],
        "max_source_frames": args.max_source_frames,
        "attempts_per_source_frame": args.attempts_per_source_frame,
        "seed": args.seed,
        "enable_replicator": args.enable_replicator,
        "enable_hdf5_export": args.enable_hdf5_export,
        "enable_mimic": args.enable_mimic,
        "enable_rl_teacher": args.enable_rl_teacher,
        "real_weight": args.real_weight,
        "isaac_rgbd_weight": args.isaac_rgbd_weight,
        "replicator_render_weight": args.replicator_render_weight,
        "isaac_lab_synthetic_weight": args.isaac_lab_synthetic_weight,
        "legacy_sidecar_weight": args.legacy_sidecar_weight,
        "require_digital_twin_pass": args.require_digital_twin_pass,
        "require_physics_pass": args.require_physics_pass,
        "require_depth_pass": args.require_depth_pass,
        "require_articulation_pass": args.require_articulation_pass,
        "dry_run": args.dry_run,
    }


def _checks(raw: str) -> list[str]:
    items = [item.strip().lower() for item in str(raw or "all").split(",") if item.strip()]
    return items or ["all"]


def _write_output(path: str, result: dict[str, Any]) -> None:
    if not str(path or "").strip():
        return
    output_path = Path(path).expanduser()
    payload = result.get("validation_report") if isinstance(result.get("validation_report"), dict) else result
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate or prepare LeRobot Isaac Lab synthetic pipeline artifacts.",
        allow_abbrev=False,
    )
    parser.add_argument("--dataset", required=True, help="LeRobot dataset path.")
    parser.add_argument("--stage", default="", help="Isaac Sim USD/USDA stage path.")
    parser.add_argument("--output", default="", help="Write the validation report JSON to this path.")
    parser.add_argument("--output-root", default="", help="Synthetic output root. Defaults under dataset sidecar.")
    parser.add_argument("--checks", default="all", help="Comma-separated validation groups, or all.")
    parser.add_argument("--fail-on", default="blocker", choices=["never", "blocker"])
    parser.add_argument("--action", default="validate", choices=["validate", "prepare", "build-synthetic", "preview", "export-hdf5", "status"])
    parser.add_argument("--mode", default="test", choices=["live", "test", "replay", "fault-injection"])
    parser.add_argument("--pipeline-mode", default="isaac_lab_replicator")
    parser.add_argument("--fallback-policy", default="block_on_primary_failure")
    parser.add_argument("--source-intent", default="train_ready_success_only")
    parser.add_argument("--isaac-lab-path", default="")
    parser.add_argument("--isaac-sim-python", default="")
    parser.add_argument("--isaac-sim-version", default="")
    parser.add_argument("--isaac-sim-docs-version", default="")
    parser.add_argument("--cameras", default="top,front,right")
    parser.add_argument("--max-source-frames", type=int, default=150)
    parser.add_argument("--attempts-per-source-frame", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--enable-replicator", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-hdf5-export", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-mimic", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--enable-rl-teacher", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--real-weight", type=float, default=1.0)
    parser.add_argument("--isaac-rgbd-weight", type=float, default=0.6)
    parser.add_argument("--replicator-render-weight", type=float, default=0.25)
    parser.add_argument("--isaac-lab-synthetic-weight", type=float, default=0.25)
    parser.add_argument("--legacy-sidecar-weight", type=float, default=0.0)
    parser.add_argument("--require-digital-twin-pass", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-physics-pass", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-depth-pass", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-articulation-pass", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    bridge = _bridge()
    payload = _payload(args)
    if args.action == "prepare":
        result = bridge.isaac_lab_prepare(payload)
    elif args.action == "build-synthetic":
        result = bridge.isaac_lab_build_synthetic(payload)
    elif args.action == "preview":
        result = bridge.isaac_lab_preview(payload)
    elif args.action == "export-hdf5":
        result = bridge.isaac_lab_export_hdf5(payload)
    elif args.action == "status":
        result = bridge.isaac_lab_status(payload)
    else:
        result = bridge.isaac_lab_validate(payload)
    _write_output(args.output, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.fail_on == "blocker" and result.get("status") == "BLOCKED":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
