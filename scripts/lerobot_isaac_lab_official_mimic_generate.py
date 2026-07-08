#!/usr/bin/env python3
"""Run official Isaac Lab Mimic generation one source episode at a time.

The Robotis OMX physical scene needs each generated rollout to reset the red
cube to the source episode's recorded initial pose. Isaac Lab's stock
generate_dataset.py accepts only one reset override per process, so this wrapper
creates one-demo HDF5 shards and launches the official generator per shard.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def _format_float(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _format_csv(values: list[float]) -> str:
    return ",".join(_format_float(value) for value in values)


def _finite(values: list[float]) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def _yaw_from_quat_xyzw(values: Any) -> float:
    x, y, z, w = [float(value) for value in values]
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return float(math.atan2(siny_cosp, cosy_cosp))


def _parse_episode_indices(raw: str, available: list[str]) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return available
    selected: list[str] = []
    available_set = set(available)
    for part in text.replace(",", " ").split():
        if not part:
            continue
        if part.startswith("demo_"):
            name = part
        else:
            try:
                name = f"demo_{int(part):06d}"
            except ValueError:
                continue
        if name in available_set and name not in selected:
            selected.append(name)
    return selected


def _hdf5_demo_names(path: Path) -> list[str]:
    import h5py

    with h5py.File(path, "r") as handle:
        data = handle.get("data")
        if data is None:
            return []
        return sorted(str(name) for name in data.keys() if str(name).startswith("demo_"))


def _copy_one_demo_hdf5(source: Path, destination: Path, demo_name: str) -> None:
    import h5py

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + f".tmp.{os.getpid()}")
    if tmp.exists():
        tmp.unlink()
    with h5py.File(source, "r") as src, h5py.File(tmp, "w") as dst:
        for key, value in src.attrs.items():
            dst.attrs[key] = value
        src_data = src.get("data")
        if src_data is None or demo_name not in src_data:
            raise KeyError(f"demo not found: {demo_name}")
        dst_data = dst.create_group("data")
        for key, value in src_data.attrs.items():
            dst_data.attrs[key] = value
        src.copy(src_data[demo_name], dst_data, name=demo_name)
    tmp.replace(destination)


def _red_cube_reset_pose(path: Path, demo_name: str) -> dict[str, Any]:
    import h5py
    import numpy as np

    with h5py.File(path, "r") as handle:
        demo = handle["data"][demo_name]
        root_pose = demo.get("initial_state/rigid_object/red_cube/root_pose")
        if root_pose is not None and root_pose.shape[0] >= 1 and root_pose.shape[-1] >= 7:
            pose = np.asarray(root_pose[0], dtype=float)
            xyz = [float(value) for value in pose[:3]]
            yaw = _yaw_from_quat_xyzw(pose[3:7])
            if _finite([*xyz, yaw]):
                return {
                    "ok": True,
                    "demo": demo_name,
                    "source": "initial_state/rigid_object/red_cube/root_pose",
                    "xyz_m": xyz,
                    "yaw_rad": float(yaw),
                }
        matrix = demo.get("obs/datagen_info/object_pose/red_cube")
        if matrix is None:
            matrix = demo.get("obs/object_pose")
        if matrix is not None and matrix.shape[0] >= 1 and matrix.shape[-2:] == (4, 4):
            pose = np.asarray(matrix[0], dtype=float)
            xyz = [float(value) for value in pose[:3, 3]]
            yaw = float(math.atan2(float(pose[1, 0]), float(pose[0, 0])))
            if _finite([*xyz, yaw]):
                return {
                    "ok": True,
                    "demo": demo_name,
                    "source": "obs/datagen_info/object_pose/red_cube",
                    "xyz_m": xyz,
                    "yaw_rad": yaw,
                }
    return {"ok": False, "demo": demo_name, "blocker": "RED_CUBE_POSE_MISSING"}


def _demo_count(path: Path) -> int:
    import h5py

    if not path.is_file() or path.stat().st_size <= 100:
        return 0
    with h5py.File(path, "r") as handle:
        data = handle.get("data")
        return len(data.keys()) if data is not None else 0


def _demo_records(path: Path) -> list[dict[str, Any]]:
    import h5py

    if not path.is_file() or path.stat().st_size <= 100:
        return []
    records: list[dict[str, Any]] = []
    with h5py.File(path, "r") as handle:
        data = handle.get("data")
        if data is None:
            return []
        for demo_name in sorted(str(name) for name in data.keys() if str(name).startswith("demo_")):
            demo = data[demo_name]
            num_samples = int(demo.attrs.get("num_samples", 0) or 0)
            if num_samples <= 0 and "actions" in demo:
                num_samples = int(demo["actions"].shape[0])
            records.append(
                {
                    "demo": demo_name,
                    "frame_count": max(0, num_samples),
                    "success": bool(demo.attrs.get("success", True)),
                }
            )
    return records


def _episode_index_from_demo_name(demo_name: str, fallback: int) -> int:
    if demo_name.startswith("demo_"):
        try:
            return int(demo_name.removeprefix("demo_"))
        except ValueError:
            pass
    return int(fallback)


def _merge_success_hdf5s(sources: list[Path], output: Path) -> int:
    import h5py

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + f".tmp.{os.getpid()}")
    if tmp.exists():
        tmp.unlink()
    count = 0
    with h5py.File(tmp, "w") as dst:
        dst_data = dst.create_group("data")
        copied_attrs = False
        for source in sources:
            if not source.is_file() or source.stat().st_size <= 100:
                continue
            with h5py.File(source, "r") as src:
                if not copied_attrs:
                    for key, value in src.attrs.items():
                        dst.attrs[key] = value
                    src_data = src.get("data")
                    if src_data is not None:
                        for key, value in src_data.attrs.items():
                            dst_data.attrs[key] = value
                    copied_attrs = True
                src_data = src.get("data")
                if src_data is None:
                    continue
                for demo_name in sorted(src_data.keys()):
                    dst_name = f"demo_{count}"
                    src.copy(src_data[demo_name], dst_data, name=dst_name)
                    count += 1
        dst.attrs["merged_success_count"] = count
    tmp.replace(output)
    return count


def _isaac_python_command(isaac_python: str, script: Path) -> list[str]:
    executable = Path(isaac_python).expanduser()
    command = [str(executable)]
    if executable.name == "isaaclab.sh":
        command.append("-p")
    command.append(str(script.expanduser()))
    return command


def _attempt_path(path: Path, attempt: int) -> Path:
    if attempt <= 1:
        return path
    return path.with_name(f"{path.stem}_attempt_{attempt}{path.suffix}")


def _official_command(args: argparse.Namespace, shard: Path, output: Path, reset: dict[str, Any], log_path: Path) -> list[str]:
    command = [
        *_isaac_python_command(args.isaac_python, Path(args.generate_script)),
        "--task",
        args.task,
        "--input_file",
        str(shard),
        "--output_file",
        str(output),
        "--generation_num_trials",
        str(args.trials_per_episode),
        "--num_envs",
        str(args.num_envs),
        "--external_callback",
        args.external_callback,
        "--robotis-domain-randomization-profile",
        args.robotis_domain_randomization_profile,
        "--robotis-camera-mode",
        args.robotis_camera_mode,
        "--robotis-camera-width",
        str(args.robotis_camera_width),
        "--robotis-camera-height",
        str(args.robotis_camera_height),
        "--robotis-mimic-generation-guarantee",
        "false",
        "--robotis-mimic-keep-failed",
        "true",
        "--robotis-cube-reset-xyz",
        _format_csv(reset["xyz_m"]),
        "--robotis-cube-reset-yaw",
        _format_float(reset["yaw_rad"]),
    ]
    if args.headless:
        command.append("--headless")
    if args.enable_cameras:
        command.append("--enable_cameras")
        command.extend(["--rendering_mode", args.rendering_mode])
    if args.use_skillgen:
        command.append("--use_skillgen")
    return command


def _annotation_command(args: argparse.Namespace, shard: Path, output: Path, reset: dict[str, Any]) -> list[str]:
    command = [
        *_isaac_python_command(args.isaac_python, Path(args.annotate_script)),
        "--task",
        args.task,
        "--input_file",
        str(shard),
        "--output_file",
        str(output),
        "--external_callback",
        args.external_callback,
        "--robotis-domain-randomization-profile",
        args.robotis_domain_randomization_profile,
        "--robotis-camera-mode",
        args.robotis_camera_mode,
        "--robotis-camera-width",
        str(args.robotis_camera_width),
        "--robotis-camera-height",
        str(args.robotis_camera_height),
        "--robotis-cube-reset-xyz",
        _format_csv(reset["xyz_m"]),
        "--robotis-cube-reset-yaw",
        _format_float(reset["yaw_rad"]),
        "--headless",
        "--auto",
    ]
    if args.enable_cameras:
        command.append("--enable_cameras")
        command.extend(["--rendering_mode", args.rendering_mode])
    return command


def _run_command(command: list[str], log_path: Path, *, cooldown_sec: float = 0.0) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
    if cooldown_sec > 0:
        time.sleep(float(cooldown_sec))
    return int(proc.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-episode official Isaac Lab Mimic generation wrapper.")
    parser.add_argument("--isaac-python", required=True)
    parser.add_argument("--annotate-script", default="")
    parser.add_argument("--generate-script", required=True)
    parser.add_argument("--annotation-mode", choices=["passthrough", "auto"], default="passthrough")
    parser.add_argument("--task", required=True)
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--shard-dir", required=True)
    parser.add_argument("--success-manifest", required=True)
    parser.add_argument("--failure-manifest", required=True)
    parser.add_argument("--summary-file", default="")
    parser.add_argument("--episode-indices", default="")
    parser.add_argument("--trials-per-episode", type=int, default=1)
    parser.add_argument("--num-envs", type=int, default=1)
    parser.add_argument("--annotation-retries", type=int, default=2)
    parser.add_argument("--generation-retries", type=int, default=1)
    parser.add_argument("--process-cooldown-sec", type=float, default=3.0)
    parser.add_argument("--external-callback", default="integrations.isaac_lab_robotis_omx.external_callback.register")
    parser.add_argument("--robotis-domain-randomization-profile", default="off")
    parser.add_argument("--robotis-camera-mode", default="off")
    parser.add_argument("--robotis-camera-width", type=int, default=640)
    parser.add_argument("--robotis-camera-height", type=int, default=480)
    parser.add_argument("--rendering-mode", default="performance")
    parser.add_argument("--enable-cameras", action="store_true")
    parser.add_argument("--use-skillgen", action="store_true")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    source = Path(args.input_file).expanduser()
    output = Path(args.output_file).expanduser()
    shard_dir = Path(args.shard_dir).expanduser()
    success_manifest = Path(args.success_manifest).expanduser()
    failure_manifest = Path(args.failure_manifest).expanduser()
    summary_file = Path(args.summary_file).expanduser() if args.summary_file else output.with_name("official_mimic_summary.json")
    success_manifest.parent.mkdir(parents=True, exist_ok=True)
    failure_manifest.parent.mkdir(parents=True, exist_ok=True)
    success_manifest.write_text("", encoding="utf-8")
    failure_manifest.write_text("", encoding="utf-8")

    demos = _parse_episode_indices(args.episode_indices, _hdf5_demo_names(source))
    rows: list[dict[str, Any]] = []
    success_outputs: list[Path] = []
    next_merged_demo_index = 0
    for ordinal, demo_name in enumerate(demos):
        episode_dir = shard_dir / demo_name
        shard = episode_dir / "source.hdf5"
        annotated = episode_dir / "annotated.hdf5"
        generated = episode_dir / "generated_dataset.hdf5"
        failed = episode_dir / "generated_dataset_failed.hdf5"
        annotation_log_path = episode_dir / "annotate.log"
        log_path = episode_dir / "generate.log"
        for cleanup in episode_dir.glob("annotated*.hdf5"):
            cleanup.unlink()
        for cleanup in episode_dir.glob("generated_dataset*.hdf5"):
            cleanup.unlink()
        for cleanup in episode_dir.glob("generate*.log"):
            cleanup.unlink()
        for cleanup in episode_dir.glob("annotate*.log"):
            cleanup.unlink()
        _copy_one_demo_hdf5(source, shard, demo_name)
        reset = _red_cube_reset_pose(shard, demo_name)
        if not reset.get("ok"):
            row = {
                "source_demo": demo_name,
                "status": "blocked",
                "blocker": reset.get("blocker", "RED_CUBE_POSE_MISSING"),
                "shard_path": str(shard),
            }
            _append_jsonl(failure_manifest, row)
            rows.append(row)
            continue

        generation_input = shard
        annotation_command: list[str] = []
        annotation_returncode: int | None = None
        annotation_count = 0
        annotation_attempts: list[dict[str, Any]] = []
        if args.annotation_mode == "auto":
            if not str(args.annotate_script or "").strip():
                row = {
                    "source_demo": demo_name,
                    "source_demo_ordinal": ordinal,
                    "status": "blocked",
                    "blocker": "ANNOTATE_SCRIPT_MISSING",
                    "shard_path": str(shard),
                    "annotation_mode": args.annotation_mode,
                }
                _append_jsonl(failure_manifest, row)
                rows.append(row)
                continue
            annotation_command = _annotation_command(args, shard, annotated, reset)
            annotation_attempt_limit = max(1, 1 + int(args.annotation_retries))
            if not args.dry_run:
                for attempt in range(1, annotation_attempt_limit + 1):
                    attempt_annotated = _attempt_path(annotated, attempt)
                    attempt_log = _attempt_path(annotation_log_path, attempt)
                    if attempt_annotated.exists():
                        attempt_annotated.unlink()
                    annotation_command = _annotation_command(args, shard, attempt_annotated, reset)
                    annotation_returncode = _run_command(
                        annotation_command,
                        attempt_log,
                        cooldown_sec=max(0.0, float(args.process_cooldown_sec)),
                    )
                    annotation_count = _demo_count(attempt_annotated)
                    annotation_attempts.append(
                        {
                            "attempt": attempt,
                            "returncode": annotation_returncode,
                            "annotation_count": annotation_count,
                            "annotation_path": str(attempt_annotated),
                            "annotation_log_path": str(attempt_log),
                        }
                    )
                    if annotation_returncode == 0 and annotation_count > 0:
                        if attempt_annotated != annotated:
                            shutil.copy2(attempt_annotated, annotated)
                        annotation_log_path = attempt_log
                        annotation_command = _annotation_command(args, shard, annotated, reset)
                        break
                if annotation_returncode != 0 or annotation_count <= 0:
                    row = {
                        "source_demo": demo_name,
                        "source_demo_ordinal": ordinal,
                        "status": "annotation_failed",
                        "returncode": annotation_returncode,
                        "annotation_count": annotation_count,
                        "annotation_attempt_count": len(annotation_attempts),
                        "annotation_attempts": annotation_attempts,
                        "shard_path": str(shard),
                        "annotation_path": str(annotated),
                        "annotation_log_path": str(annotation_log_path),
                        "annotation_command": annotation_command,
                        "annotation_mode": args.annotation_mode,
                        "reset": {
                            "xyz_m": [float(_format_float(value)) for value in reset["xyz_m"]],
                            "yaw_rad": float(_format_float(reset["yaw_rad"])),
                            "source": reset["source"],
                        },
                    }
                    _append_jsonl(failure_manifest, row)
                    rows.append(row)
                    continue
            generation_input = annotated

        command = _official_command(args, generation_input, generated, reset, log_path)
        generation_attempts: list[dict[str, Any]] = []
        returncode = 0
        success_count = 0
        failure_count = 0
        if not args.dry_run:
            generation_attempt_limit = max(1, 1 + int(args.generation_retries))
            for attempt in range(1, generation_attempt_limit + 1):
                attempt_generated = _attempt_path(generated, attempt)
                attempt_failed = _attempt_path(failed, attempt)
                attempt_log = _attempt_path(log_path, attempt)
                if attempt_generated.exists():
                    attempt_generated.unlink()
                if attempt_failed.exists():
                    attempt_failed.unlink()
                command = _official_command(args, generation_input, attempt_generated, reset, attempt_log)
                returncode = _run_command(
                    command,
                    attempt_log,
                    cooldown_sec=max(0.0, float(args.process_cooldown_sec)),
                )
                success_count = _demo_count(attempt_generated)
                failure_count = _demo_count(attempt_failed)
                generation_attempts.append(
                    {
                        "attempt": attempt,
                        "returncode": returncode,
                        "success_count": success_count,
                        "failure_count": failure_count,
                        "generated_path": str(attempt_generated),
                        "failed_path": str(attempt_failed),
                        "log_path": str(attempt_log),
                    }
                )
                if success_count > 0:
                    if attempt_generated != generated:
                        shutil.copy2(attempt_generated, generated)
                    log_path = attempt_log
                    failed = attempt_failed
                    command = _official_command(args, generation_input, generated, reset, log_path)
                    break
            if success_count <= 0 and generation_attempts:
                last_attempt = generation_attempts[-1]
                failed = Path(str(last_attempt["failed_path"]))
                log_path = Path(str(last_attempt["log_path"]))
                command = _official_command(args, generation_input, generated, reset, log_path)
        row = {
            "source_demo": demo_name,
            "source_demo_ordinal": ordinal,
            "status": "dry_run_ready" if args.dry_run else ("success" if success_count > 0 else "failed"),
            "returncode": returncode,
            "success_count": success_count,
            "failure_count": failure_count,
            "shard_path": str(shard),
            "annotation_mode": args.annotation_mode,
            "annotation_path": str(annotated) if args.annotation_mode == "auto" else "",
            "annotation_log_path": str(annotation_log_path) if args.annotation_mode == "auto" else "",
            "annotation_command": annotation_command,
            "annotation_returncode": annotation_returncode,
            "annotation_count": annotation_count,
            "annotation_attempt_count": len(annotation_attempts),
            "annotation_attempts": annotation_attempts,
            "generation_attempt_count": len(generation_attempts),
            "generation_attempts": generation_attempts,
            "generated_path": str(generated),
            "failed_path": str(failed),
            "log_path": str(log_path),
            "reset": {
                "xyz_m": [float(_format_float(value)) for value in reset["xyz_m"]],
                "yaw_rad": float(_format_float(reset["yaw_rad"])),
                "source": reset["source"],
            },
            "command": command,
            "dry_run": bool(args.dry_run),
        }
        if args.dry_run:
            _append_jsonl(success_manifest, row)
        elif success_count > 0:
            success_outputs.append(generated)
            generated_records = _demo_records(generated)
            if not generated_records:
                generated_records = [
                    {"demo": f"demo_{index}", "frame_count": 0, "success": True}
                    for index in range(success_count)
                ]
            for record in generated_records:
                frame_count = int(record.get("frame_count") or 0)
                merged_demo = f"demo_{next_merged_demo_index}"
                next_merged_demo_index += 1
                trajectory_id = f"official_mimic_{demo_name}_{record['demo']}"
                _append_jsonl(
                    success_manifest,
                    {
                        **row,
                        "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                        "source_type": "isaac_lab_mimic",
                        "source_id": trajectory_id,
                        "trajectory_id": trajectory_id,
                        "source_episode_index": _episode_index_from_demo_name(demo_name, ordinal),
                        "episode_index": _episode_index_from_demo_name(demo_name, ordinal),
                        "local_generated_demo": record["demo"],
                        "generated_demo": merged_demo,
                        "frame_count": frame_count,
                        "num_frames": frame_count,
                        "frame_start": 0,
                        "frame_end": max(0, frame_count - 1),
                        "metrics": {
                            "success": bool(record.get("success", True)),
                            "official_mimic": True,
                            "lab_step_replay": False,
                            "replay_required": True,
                        },
                        "artifacts": {
                            "hdf5_path": str(output),
                            "per_episode_hdf5_path": str(generated),
                            "source_hdf5_path": str(shard),
                            "annotated_hdf5_path": str(annotated) if args.annotation_mode == "auto" else "",
                        },
                        "training": {
                            "eligible": False,
                            "fidelity_weight": 0.25,
                            "exclusion_reason": "official_replay_validation_required",
                        },
                    },
                )
        else:
            _append_jsonl(failure_manifest, row)
        rows.append(row)

    merged_count = 0 if args.dry_run else _merge_success_hdf5s(success_outputs, output)
    summary = {
        "schema": "atr.lerobot.isaac_lab_official_mimic_per_episode.summary.v1",
        "ok": bool(args.dry_run or merged_count > 0),
        "status": "dry_run_ready"
        if args.dry_run
        else (
            "success"
            if merged_count > 0 and all(row.get("status") == "success" for row in rows)
            else ("partial_success" if merged_count > 0 else "failed")
        ),
        "dry_run": bool(args.dry_run),
        "input_file": str(source),
        "output_file": str(output),
        "shard_dir": str(shard_dir),
        "selected_demo_count": len(demos),
        "success_demo_count": sum(int(row.get("success_count", 0)) for row in rows),
        "failure_demo_count": sum(int(row.get("failure_count", 0)) for row in rows),
        "success_source_episode_count": sum(1 for row in rows if row.get("status") == "success"),
        "failed_source_episode_count": sum(1 for row in rows if row.get("status") not in {"success", "dry_run_ready"}),
        "annotation_failure_count": sum(1 for row in rows if row.get("status") == "annotation_failed"),
        "generation_failure_count": sum(1 for row in rows if row.get("status") == "failed"),
        "merged_success_count": merged_count,
        "success_manifest": str(success_manifest),
        "failure_manifest": str(failure_manifest),
        "rows": rows,
    }
    _write_json(summary_file, summary)
    if not args.dry_run and merged_count <= 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
