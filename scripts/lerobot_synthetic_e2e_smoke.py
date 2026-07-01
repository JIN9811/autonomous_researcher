#!/usr/bin/env python3
"""End-to-end LeRobot synthetic intelligence smoke runner.

This script is non-actuating. It can create a deterministic LeRobot-shaped
fixture dataset and then runs the same bridge methods used by the GUI backend:
Isaac Lab synthetic build, HDF5 export, and LeRobot train smoke.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from utils.config_loader import load_all_configs


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bridge(repo_root: Path) -> LeRobotBridge:
    cfg = load_all_configs(repo_root / "configs")
    return LeRobotBridge(LeRobotBridgeConfig.from_config(cfg.get("lerobot", {}), repo_root=repo_root))


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _jsonl_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _write_raw_depth_fixture_frames(
    dataset_path: Path,
    *,
    episodes: int,
    frames_per_episode: int,
) -> dict[str, Any]:
    height = 48
    width = 64
    x_gradient = np.arange(width, dtype=np.uint16).reshape(1, width)
    y_gradient = np.arange(height, dtype=np.uint16).reshape(height, 1)
    camera_bases = {"top": 620, "wrist": 780}
    frame_count = int(episodes) * int(frames_per_episode)
    camera_counts: dict[str, int] = {}
    for camera, base_depth_mm in camera_bases.items():
        camera_dir = dataset_path / "sidecar" / "depth_raw" / camera
        camera_dir.mkdir(parents=True, exist_ok=True)
        camera_counts[camera] = 0
        for global_index in range(frame_count):
            depth = base_depth_mm + (global_index % 37) + x_gradient + (y_gradient * 2)
            Image.fromarray(depth.astype(np.uint16)).save(camera_dir / f"frame_{global_index:06d}.png")
            camera_counts[camera] += 1
    return {
        "camera_counts": camera_counts,
        "frame_count_per_camera": frame_count,
        "height": height,
        "width": width,
        "dtype": "uint16",
    }


def build_fixture_recording_dataset(
    dataset_path: Path,
    *,
    episodes: int = 5,
    episode_s: int = 10,
    fps: int = 15,
) -> dict[str, Any]:
    """Create a deterministic 5x10s LeRobot-style recording fixture."""
    dataset_path = dataset_path.expanduser().resolve()
    frames_per_episode = int(episode_s) * int(fps)
    frame_count = int(episodes) * frames_per_episode
    (dataset_path / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    _json_write(
        dataset_path / "meta" / "info.json",
        {
            "codebase_version": "v2.1",
            "total_episodes": int(episodes),
            "total_frames": frame_count,
            "fps": int(fps),
            "features": {
                "observation.state": {"dtype": "float64", "shape": [2]},
                "action": {"dtype": "float64", "shape": [3]},
            },
        },
    )
    _jsonl_write(dataset_path / "meta" / "tasks.jsonl", [{"task_index": 0, "task": "Pick up the cube"}])
    _jsonl_write(
        dataset_path / "meta" / "episodes.jsonl",
        [
            {
                "episode_index": episode_index,
                "tasks": ["Pick up the cube"],
                "length": frames_per_episode,
            }
            for episode_index in range(int(episodes))
        ],
    )
    _jsonl_write(
        dataset_path / "meta" / "episodes_stats.jsonl",
        [{"episode_index": episode_index, "stats": {}} for episode_index in range(int(episodes))],
    )
    for episode_index in range(int(episodes)):
        frame_indices = list(range(frames_per_episode))
        timestamps = [round(frame / float(fps), 6) for frame in frame_indices]
        states = [[episode_index + frame * 0.001, frame * 0.002] for frame in frame_indices]
        actions = [[episode_index * 0.1 + frame * 0.01, frame * 0.02, 0.5] for frame in frame_indices]
        table = pa.table(
            {
                "episode_index": pa.array([episode_index] * frames_per_episode, type=pa.int64()),
                "frame_index": pa.array(frame_indices, type=pa.int64()),
                "timestamp": pa.array(timestamps, type=pa.float64()),
                "observation.state": pa.array(states, type=pa.list_(pa.float64())),
                "action": pa.array(actions, type=pa.list_(pa.float64())),
            }
        )
        pq.write_table(table, dataset_path / "data" / "chunk-000" / f"episode_{episode_index:06d}.parquet")
    _json_write(
        dataset_path / "sidecar" / "depth_raw" / "transform_manifest.json",
        {
            "camera_keys": ["top", "wrist"],
            "aligned_to": "color",
            "depth_encoding": "png16",
            "depth_scale_m_per_unit": 0.001,
            "depth_clip_min_mm": 0.0,
            "depth_clip_max_mm": 2000.0,
        },
    )
    raw_depth = _write_raw_depth_fixture_frames(
        dataset_path,
        episodes=int(episodes),
        frames_per_episode=frames_per_episode,
    )
    return {
        "schema": "atr.lerobot.synthetic_e2e.fixture.v1",
        "dataset_path": str(dataset_path),
        "episode_count": int(episodes),
        "episode_s": int(episode_s),
        "fps": int(fps),
        "frames_per_episode": frames_per_episode,
        "frame_count": frame_count,
        "raw_depth": raw_depth,
    }


def run_e2e_smoke(
    *,
    bridge: LeRobotBridge,
    dataset_path: Path,
    isaac_lab_path: Path,
    stage_path: Path,
    train_steps: int = 2,
    enable_replicator: bool = False,
) -> dict[str, Any]:
    dataset_path = dataset_path.expanduser().resolve()
    synthetic_payload = {
        "mode": "test",
        "dataset_path": str(dataset_path),
        "isaac_lab_path": str(isaac_lab_path.expanduser().resolve()),
        "stage_path": str(stage_path.expanduser().resolve()),
        "enable_replicator": bool(enable_replicator),
        "enable_hdf5_export": True,
        "enable_mimic": False,
        "enable_rl_teacher": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
        "max_source_frames": 5000,
        "source_intent": "train_ready_success_only",
    }
    synthetic = bridge.isaac_lab_build_synthetic(synthetic_payload)
    hdf5 = bridge.isaac_lab_export_hdf5(synthetic_payload)
    train = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset_path),
            "dataset_root": str(dataset_path),
            "dataset_repo_id": "local/synthetic-e2e-fixture",
            "observation_pipeline_id": "raw_depth_adapter",
            "policy_type": "act",
            "steps": int(train_steps),
            "batch_size": 2,
            "num_workers": 0,
            "device": "cpu",
            "dataset_mix_isaac_lab_synthetic_weight": 0.5,
            "fidelity_isaac_lab_synthetic_weight": 0.2,
        }
    )
    fixture = _read_fixture_summary(dataset_path)
    ok = bool(synthetic.get("ok")) and bool(hdf5.get("ok")) and bool(train.get("ok"))
    return {
        "schema": "atr.lerobot.synthetic_e2e.smoke_report.v1",
        "ok": ok,
        "recording_fixture": fixture,
        "synthetic": synthetic,
        "hdf5": hdf5,
        "train": train,
        "summary": {
            "dataset_path": str(dataset_path),
            "canonical_frames": int((synthetic.get("canonical_episode_index") or {}).get("frame_count") or 0),
            "hdf5_frames": int((hdf5.get("hdf5") or {}).get("exported_frame_count") or 0),
            "train_steps": int((train.get("training") or {}).get("total_steps") or 0),
        },
    }


def _read_fixture_summary(dataset_path: Path) -> dict[str, Any]:
    try:
        info = json.loads((dataset_path / "meta" / "info.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        info = {}
    return {
        "dataset_path": str(dataset_path),
        "episode_count": int(info.get("total_episodes") or 0),
        "frame_count": int(info.get("total_frames") or 0),
        "fps": int(info.get("fps") or 0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a non-actuating 5x10s LeRobot synthetic intelligence smoke test.")
    parser.add_argument("--dataset", required=True, help="Fixture or recorded LeRobot dataset path.")
    parser.add_argument("--isaac-lab-path", required=True, help="Isaac Lab checkout path used for compatibility preflight.")
    parser.add_argument("--stage", required=True, help="Isaac Sim USD/USDA stage path.")
    parser.add_argument("--repo-root", default=str(_repo_root()))
    parser.add_argument("--create-fixture", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--episodes", type=int, default=5)
    parser.add_argument("--episode-s", type=int, default=10)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--train-steps", type=int, default=2)
    parser.add_argument("--enable-replicator", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    if args.create_fixture:
        build_fixture_recording_dataset(dataset_path, episodes=args.episodes, episode_s=args.episode_s, fps=args.fps)
    bridge = _bridge(Path(args.repo_root).expanduser().resolve())
    report = run_e2e_smoke(
        bridge=bridge,
        dataset_path=dataset_path,
        isaac_lab_path=Path(args.isaac_lab_path),
        stage_path=Path(args.stage),
        train_steps=args.train_steps,
        enable_replicator=args.enable_replicator,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
