#!/usr/bin/env python3
"""Generate Robotis OMX Mimic HDF5 data by replaying joint-position source segments."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Robotis OMX joint-position replay Mimic backend.")
    parser.add_argument("--backend", choices=("joint_replay",), default="joint_replay")
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--success-manifest", required=True)
    parser.add_argument("--failure-manifest", required=True)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--domain-variants", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--env-name", default="")
    parser.add_argument("--robotis-domain-randomization-profile", default="conservative")
    parser.add_argument("--summary-file", default="")
    parser.add_argument("--sim-step-generation", action="store_true")
    parser.add_argument("--visualize-generation", action="store_true")
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument("--rgbd-render-only", action="store_true")
    parser.add_argument("--rgbd-render-backend", choices=("mirror_http", "lab_camera"), default="mirror_http")
    parser.add_argument("--mirror-endpoint", default="http://127.0.0.1:8766/render")
    parser.add_argument("--mirror-timeout-s", type=float, default=0.5)
    parser.add_argument("--mirror-settle-timeout-s", type=float, default=4.0)
    parser.add_argument("--mirror-settle-tolerance-deg", type=float, default=5.0)
    parser.add_argument("--mirror-settle-velocity-tolerance-deg-s", type=float, default=10.0)
    parser.add_argument("--rgbd-output-dir", default="")
    parser.add_argument("--rgbd-manifest", default="")
    parser.add_argument("--rgbd-cameras", default="top,front,right")
    parser.add_argument("--visual-task", default="")
    parser.add_argument("--visual-num-envs", type=int, default=1)
    parser.add_argument("--external-callback", default="")
    parser.add_argument("--robotis-camera-mode", default="off")
    parser.add_argument("--robotis-camera-width", type=int, default=640)
    parser.add_argument("--robotis-camera-height", type=int, default=480)
    parser.add_argument("--enable-cameras", action="store_true")
    parser.add_argument("--rendering-mode", default="balanced")
    parser.add_argument("--viz", default="kit")
    parser.add_argument("--kit-args", default="")
    parser.add_argument("--visual-fps", type=float, default=15.0)
    parser.add_argument("--visual-max-demos", type=int, default=3)
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    output_path = Path(args.output_file).expanduser()
    success_manifest_path = Path(args.success_manifest).expanduser()
    failure_manifest_path = Path(args.failure_manifest).expanduser()
    if args.rgbd_render_only:
        render_kwargs = {
            "dataset_path": Path(args.input_file).expanduser(),
            "output_path": output_path,
            "success_manifest_path": success_manifest_path,
            "failure_manifest_path": failure_manifest_path,
            "render_output_dir": Path(args.rgbd_output_dir).expanduser()
            if args.rgbd_output_dir
            else output_path.parent / "renders",
            "render_manifest_path": Path(args.rgbd_manifest).expanduser()
            if args.rgbd_manifest
            else output_path.parent / "manifest.jsonl",
            "cameras": _camera_list(args.rgbd_cameras),
            "camera_width": int(args.robotis_camera_width),
            "camera_height": int(args.robotis_camera_height),
            "fps": float(args.visual_fps),
            "max_demos": int(args.visual_max_demos or 0),
        }
        if str(args.rgbd_render_backend or "mirror_http") == "mirror_http":
            rgbd_summary = _render_generated_dataset_rgbd_via_mirror(
                **render_kwargs,
                mirror_endpoint=str(args.mirror_endpoint or ""),
                mirror_timeout_s=float(args.mirror_timeout_s),
                mirror_settle_timeout_s=float(args.mirror_settle_timeout_s),
                mirror_settle_tolerance_deg=float(args.mirror_settle_tolerance_deg),
                mirror_settle_velocity_tolerance_deg_s=float(args.mirror_settle_velocity_tolerance_deg_s),
            )
        else:
            rgbd_summary = _render_generated_dataset_rgbd(
                **render_kwargs,
                task_name=str(args.visual_task or args.env_name or ""),
                num_envs=int(args.visual_num_envs),
                external_callback=str(args.external_callback or ""),
                domain_randomization_profile=str(args.robotis_domain_randomization_profile),
                camera_mode=str(args.robotis_camera_mode or "off"),
                enable_cameras=bool(args.enable_cameras),
                rendering_mode=str(args.rendering_mode or "balanced"),
                visualizer=str(args.viz or "none"),
                kit_args=str(args.kit_args or ""),
            )
        summary_path = (
            Path(args.summary_file).expanduser()
            if args.summary_file
            else output_path.parent / "summary.json"
        )
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(rgbd_summary, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(rgbd_summary, indent=2, sort_keys=True))
        return 0 if rgbd_summary.get("ok") else 1
    if args.preview_only:
        visual_summary = _visualize_generated_dataset(
            dataset_path=Path(args.input_file).expanduser(),
            task_name=str(args.visual_task or args.env_name or ""),
            num_envs=int(args.visual_num_envs),
            external_callback=str(args.external_callback or ""),
            domain_randomization_profile=str(args.robotis_domain_randomization_profile),
            camera_mode=str(args.robotis_camera_mode or "off"),
            camera_width=int(args.robotis_camera_width),
            camera_height=int(args.robotis_camera_height),
            enable_cameras=bool(args.enable_cameras),
            rendering_mode=str(args.rendering_mode or "balanced"),
            visualizer=str(args.viz or "kit"),
            kit_args=str(args.kit_args or ""),
            fps=float(args.visual_fps),
            max_demos=int(args.visual_max_demos or 0),
        )
        summary = {
            "schema": "atr.lerobot.isaac_lab_mimic.joint_replay.preview.summary.v1",
            "ok": bool(visual_summary.get("ok")),
            "status": str(visual_summary.get("status") or ("completed" if visual_summary.get("ok") else "blocked")),
            "mode": "preview_only",
            "input_path": str(Path(args.input_file).expanduser()),
            "output_path": str(output_path),
            "visualization": visual_summary,
        }
        if not visual_summary.get("ok"):
            summary["blocker"] = str(visual_summary.get("blocker") or "JOINT_REPLAY_PREVIEW_FAILED")
        summary_path = (
            Path(args.summary_file).expanduser()
            if args.summary_file
            else output_path.with_name("joint_replay_preview_summary.json")
        )
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary.get("ok") else 1

    from device_bridges.isaac_lab_joint_replay_mimic import generate_joint_replay_mimic_dataset

    generation_output_path = output_path
    generation_success_manifest_path = success_manifest_path
    generation_failure_manifest_path = failure_manifest_path
    if args.sim_step_generation:
        generation_output_path = output_path.with_name(f"{output_path.stem}_joint_plan{output_path.suffix}")
        generation_success_manifest_path = success_manifest_path.with_name(
            f"{success_manifest_path.stem}_joint_plan{success_manifest_path.suffix}"
        )
        generation_failure_manifest_path = failure_manifest_path.with_name(
            f"{failure_manifest_path.stem}_joint_plan{failure_manifest_path.suffix}"
        )
    summary = generate_joint_replay_mimic_dataset(
        input_path=Path(args.input_file).expanduser(),
        output_path=generation_output_path,
        success_manifest_path=generation_success_manifest_path,
        failure_manifest_path=generation_failure_manifest_path,
        trials=int(args.trials),
        domain_variants=int(args.domain_variants),
        seed=int(args.seed),
        env_name=str(args.env_name or ""),
        domain_randomization_profile=str(args.robotis_domain_randomization_profile),
    )
    summary["domain_randomization_profile"] = str(args.robotis_domain_randomization_profile)
    if args.sim_step_generation and summary.get("ok"):
        lab_step_summary = _generate_lab_step_replay_dataset(
            dataset_path=generation_output_path,
            output_path=output_path,
            success_manifest_path=success_manifest_path,
            failure_manifest_path=failure_manifest_path,
            task_name=str(args.visual_task or args.env_name or ""),
            num_envs=int(args.visual_num_envs),
            external_callback=str(args.external_callback or ""),
            domain_randomization_profile=str(args.robotis_domain_randomization_profile),
            camera_mode=str(args.robotis_camera_mode or "off"),
            camera_width=int(args.robotis_camera_width),
            camera_height=int(args.robotis_camera_height),
            enable_cameras=bool(args.enable_cameras),
            rendering_mode=str(args.rendering_mode or "balanced"),
            visualizer=str(args.viz or "kit"),
            kit_args=str(args.kit_args or ""),
            fps=float(args.visual_fps),
            max_demos=int(args.visual_max_demos or 0),
        )
        summary["lab_step_generation"] = lab_step_summary
        summary["visualization"] = lab_step_summary
        summary["output_path"] = str(output_path)
        summary["success_manifest_path"] = str(success_manifest_path)
        summary["failure_manifest_path"] = str(failure_manifest_path)
        summary["success_count"] = int(lab_step_summary.get("success_count") or 0)
        summary["failure_count"] = int(lab_step_summary.get("failure_count") or 0)
        summary["trial_count"] = int(lab_step_summary.get("visual_demo_count") or summary.get("trial_count") or 0)
        if not lab_step_summary.get("ok"):
            summary["ok"] = False
            summary["status"] = "blocked"
            summary["blocker"] = str(lab_step_summary.get("blocker") or "JOINT_REPLAY_LAB_STEP_GENERATION_FAILED")
    elif args.visualize_generation and summary.get("ok"):
        visual_summary = _visualize_generated_dataset(
            dataset_path=output_path,
            task_name=str(args.visual_task or args.env_name or ""),
            num_envs=int(args.visual_num_envs),
            external_callback=str(args.external_callback or ""),
            domain_randomization_profile=str(args.robotis_domain_randomization_profile),
            camera_mode=str(args.robotis_camera_mode or "off"),
            camera_width=int(args.robotis_camera_width),
            camera_height=int(args.robotis_camera_height),
            enable_cameras=bool(args.enable_cameras),
            rendering_mode=str(args.rendering_mode or "balanced"),
            visualizer=str(args.viz or "kit"),
            kit_args=str(args.kit_args or ""),
            fps=float(args.visual_fps),
            max_demos=int(args.visual_max_demos or 0),
        )
        summary["visualization"] = visual_summary
        if not visual_summary.get("ok"):
            summary["ok"] = False
            summary["status"] = "blocked"
            summary["blocker"] = str(visual_summary.get("blocker") or "JOINT_REPLAY_VISUALIZATION_FAILED")
    summary_path = Path(args.summary_file).expanduser() if args.summary_file else output_path.with_name("joint_replay_summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("ok") else 1


def _call_external_callback(callback_path: str) -> None:
    if not callback_path:
        return
    module_name, _, attr = callback_path.rpartition(".")
    if not module_name or not attr:
        return
    callback = getattr(importlib.import_module(module_name), attr)
    callback()


def _generate_lab_step_replay_dataset(
    *,
    dataset_path: Path,
    output_path: Path,
    success_manifest_path: Path,
    failure_manifest_path: Path,
    task_name: str,
    num_envs: int,
    external_callback: str,
    domain_randomization_profile: str,
    camera_mode: str,
    camera_width: int,
    camera_height: int,
    enable_cameras: bool,
    rendering_mode: str,
    visualizer: str,
    kit_args: str,
    fps: float,
    max_demos: int,
) -> dict[str, object]:
    if not task_name:
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_LAB_STEP_TASK_MISSING",
            "message": "Lab step generation requires a Mimic task name.",
        }
    os.environ["ROBOTIS_OMX_DOMAIN_RANDOMIZATION_PROFILE"] = domain_randomization_profile
    os.environ["ROBOTIS_OMX_CAMERA_MODE"] = camera_mode
    os.environ["ROBOTIS_OMX_CAMERA_WIDTH"] = str(camera_width)
    os.environ["ROBOTIS_OMX_CAMERA_HEIGHT"] = str(camera_height)
    os.environ.setdefault("ROBOTIS_OMX_USE_FABRIC", "0")
    if output_path.exists():
        output_path.unlink()
    _write_jsonl_rows(success_manifest_path, [])
    _write_jsonl_rows(failure_manifest_path, [])
    simulation_app = None
    env = None
    try:
        from isaaclab.app import AppLauncher

        app_launcher = AppLauncher(
            {
                "visualizer": [visualizer],
                "visualizer_explicit": True,
                "headless": False,
                "enable_cameras": bool(enable_cameras),
                "rendering_mode": rendering_mode,
                "kit_args": kit_args,
            }
        )
        simulation_app = app_launcher.app
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_LAB_STEP_APP_LAUNCH_FAILED",
            "message": f"Could not launch Isaac Lab app for sim-step generation: {exc}",
            "dataset_path": str(dataset_path),
            "output_path": str(output_path),
        }
    try:
        _call_external_callback(external_callback)
        import gymnasium as gym
        import h5py
        import torch
        from isaaclab.envs.mdp.recorders.recorders_cfg import ActionStateRecorderManagerCfg
        from isaaclab.managers import DatasetExportMode
        from isaaclab_tasks.utils import parse_env_cfg

        output_path.parent.mkdir(parents=True, exist_ok=True)
        env_cfg = parse_env_cfg(task_name, num_envs=max(1, int(num_envs)), use_fabric=False)
        env_cfg.recorders = ActionStateRecorderManagerCfg()
        env_cfg.recorders.dataset_export_dir_path = str(output_path.parent)
        env_cfg.recorders.dataset_filename = output_path.stem
        env_cfg.recorders.dataset_export_mode = DatasetExportMode.EXPORT_ALL
        env_cfg.recorders.export_in_record_pre_reset = False
        env_cfg.recorders.export_in_close = False
        env_cfg.recorders.dataset_compression = True
        env = gym.make(task_name, cfg=env_cfg)
        env_num_envs = int(getattr(env.unwrapped, "num_envs", getattr(env, "num_envs", 1)))
        visual_camera_view = _apply_visual_camera_view(env)
        visual_camera_view_apply_count = 1 if bool(visual_camera_view.get("applied")) else 0
        replayed_frames = 0
        viewport_update_count = 0
        visual_render_method_last = ""
        exported_count = 0
        success_rows: list[dict[str, object]] = []
        readback_samples: list[dict[str, object]] = []
        initial_state_last: dict[str, bool] = {}
        initial_state_refresh_last: dict[str, bool] = {}
        visual_joint_frame_last: dict[str, bool] = {}
        visual_frame_state_last: dict[str, bool] = {}
        visual_frame_state_applied = 0
        domain_randomization_attr_copy: dict[str, object] = {}
        with h5py.File(dataset_path, "r") as handle:
            demos = handle.get("data")
            names = sorted(str(name) for name in demos.keys()) if demos is not None else []
            total_demo_count = len(names)
            if int(max_demos) > 0:
                names = names[: int(max_demos)]
            for source_index, name in enumerate(names):
                if not simulation_app.is_running():
                    break
                env.reset()
                recorder = getattr(env.unwrapped, "recorder_manager", None)
                initial_state_last = _apply_hdf5_demo_initial_state(env, demos[name], apply_rigid_objects=True)
                if any(initial_state_last.values()):
                    initial_state_refresh_last = _refresh_env_after_hdf5_initial_state(env)
                if recorder is not None:
                    recorder.reset([0])
                    recorder.record_post_reset([0])
                camera_after_reset = _apply_visual_camera_view(env)
                if bool(camera_after_reset.get("applied")):
                    visual_camera_view = camera_after_reset
                    visual_camera_view_apply_count += 1
                actions = demos[name]["actions"][:]
                readback_frame_indices = _visual_readback_frame_indices(len(actions))
                for frame_index, row in enumerate(actions):
                    if not simulation_app.is_running():
                        break
                    started = time.monotonic()
                    action = _visual_action_tensor(torch, row, env, env_num_envs)
                    visual_joint_frame_last = _apply_visual_joint_frame(env, action)
                    env.step(action)
                    visual_frame_state_last = _apply_hdf5_demo_frame_state(
                        env,
                        demos[name],
                        frame_index=frame_index,
                        apply_rigid_objects=True,
                    )
                    if any(visual_frame_state_last.values()):
                        visual_frame_state_applied += 1
                        _refresh_env_after_hdf5_initial_state(env)
                    if frame_index in readback_frame_indices:
                        sample = _visual_joint_readback_sample(
                            env,
                            action,
                            demo_name=name,
                            frame_index=frame_index,
                            phase="lab_step_generation",
                        )
                        if sample:
                            readback_samples.append(sample)
                    render_method = _pump_visual_viewport(env, simulation_app)
                    if render_method:
                        visual_render_method_last = render_method
                        viewport_update_count += 1
                    replayed_frames += 1
                    if fps > 0:
                        delay = max(0.0, (1.0 / fps) - (time.monotonic() - started))
                        if delay:
                            time.sleep(delay)
                if recorder is not None:
                    success = torch.ones((1,), dtype=torch.bool, device=getattr(env.unwrapped, "device", None))
                    recorder.set_success_to_episodes([0], success)
                    recorder.export_episodes([0], demo_ids=[exported_count])
                domain_randomization = _hdf5_json_attr(demos[name], "domain_randomization")
                success_rows.append(
                    {
                        "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                        "source_type": "isaac_lab_mimic",
                        "generator": "isaac_lab_mimic_lab_step_joint_replay",
                        "generated_demo": f"demo_{exported_count}",
                        "trajectory_id": f"lab_step_joint_replay_{exported_count:06d}",
                        "generated_index": int(exported_count),
                        "source_demo": str(name),
                        "source_demo_index": int(source_index),
                        "frame_count": int(len(actions)),
                        "hdf5_path": str(output_path),
                        "artifacts": {"hdf5_path": "mimic/generated_dataset.hdf5"},
                        "training": {"eligible": True, "fidelity_weight": 1.0},
                        "metrics": {"success": True, "lab_step_replay": True},
                        "domain_randomization": domain_randomization,
                    }
                )
                exported_count += 1
        domain_randomization_attr_copy = _copy_domain_randomization_attrs_to_lab_output(
            dataset_path,
            output_path,
            success_rows,
        )
        _write_jsonl_rows(success_manifest_path, success_rows)
        _write_jsonl_rows(failure_manifest_path, [])
        return {
            "ok": True,
            "status": "completed",
            "mode": "lab_step_generation",
            "task_name": task_name,
            "num_envs": int(num_envs),
            "dataset_path": str(dataset_path),
            "output_path": str(output_path),
            "success_manifest_path": str(success_manifest_path),
            "failure_manifest_path": str(failure_manifest_path),
            "visual_demo_count": int(exported_count),
            "visual_total_demo_count": int(total_demo_count),
            "visual_max_demos": int(max_demos),
            "success_count": int(exported_count),
            "failure_count": 0,
            "replayed_frames": int(replayed_frames),
            "viewport_update_count": int(viewport_update_count),
            "visual_render_method_last": visual_render_method_last,
            "visual_camera_view_applied": bool(visual_camera_view.get("applied")),
            "visual_camera_view_apply_count": int(visual_camera_view_apply_count),
            "visual_camera_view": {
                "eye": list(visual_camera_view.get("eye") or []),
                "target": list(visual_camera_view.get("target") or []),
                "method": str(visual_camera_view.get("method") or ""),
            },
            "initial_state_last": initial_state_last,
            "initial_state_refresh_last": initial_state_refresh_last,
            "domain_randomization_attr_copy": domain_randomization_attr_copy,
            "visual_joint_frame_last": visual_joint_frame_last,
            "visual_frame_state_applied_count": int(visual_frame_state_applied),
            "visual_frame_state_last": visual_frame_state_last,
            "visual_readback_sample_count": int(len(readback_samples)),
            "visual_readback_samples": readback_samples,
            "visual_readback_target_error_max": _visual_readback_error_max(readback_samples),
            "camera_mode": camera_mode,
            "enable_cameras": bool(enable_cameras),
            "visualizer": visualizer,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_LAB_STEP_REPLAY_FAILED",
            "message": f"Could not generate Mimic data through Isaac Lab sim-step replay: {exc}",
            "dataset_path": str(dataset_path),
            "output_path": str(output_path),
            "task_name": task_name,
        }
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass


def _write_jsonl_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _rgbd_render_staging_paths(
    *,
    output_path: Path,
    success_manifest_path: Path,
    failure_manifest_path: Path,
    render_output_dir: Path,
    render_manifest_path: Path,
) -> dict[str, Path]:
    stamp = f"{int(time.time() * 1000)}_{os.getpid()}"
    staging_root = output_path.parent / ".render_staging" / f"rgbd_{stamp}"
    return {
        "root": staging_root,
        "output_path": staging_root / output_path.name,
        "success_manifest_path": staging_root / success_manifest_path.name,
        "failure_manifest_path": staging_root / failure_manifest_path.name,
        "render_output_dir": staging_root / "renders",
        "render_manifest_path": staging_root / render_manifest_path.name,
    }


def _rewrite_rgbd_render_paths(value: Any, *, staging_render_output_dir: Path, render_output_dir: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _rewrite_rgbd_render_paths(
                item,
                staging_render_output_dir=staging_render_output_dir,
                render_output_dir=render_output_dir,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_rgbd_render_paths(
                item,
                staging_render_output_dir=staging_render_output_dir,
                render_output_dir=render_output_dir,
            )
            for item in value
        ]
    if not isinstance(value, str) or not value:
        return value
    try:
        path = Path(value)
        relative = path.relative_to(staging_render_output_dir)
    except ValueError:
        return value
    return str(render_output_dir / relative)


def _rewrite_rgbd_render_manifest_file(
    path: Path,
    *,
    staging_render_output_dir: Path,
    render_output_dir: Path,
) -> None:
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return
    rewritten = _rewrite_rgbd_render_paths(
        rows,
        staging_render_output_dir=staging_render_output_dir,
        render_output_dir=render_output_dir,
    )
    _write_jsonl_rows(path, rewritten)


def _commit_rgbd_render_outputs(
    *,
    input_path: Path,
    output_path: Path,
    success_manifest_path: Path,
    failure_manifest_path: Path,
    render_output_dir: Path,
    render_manifest_path: Path,
    staging: dict[str, Path],
    render_rows: list[dict[str, object]],
    success_rows: list[dict[str, object]],
    failure_rows: list[dict[str, object]],
    hdf5_path_rows: dict[str, dict[str, list[str]]],
) -> None:
    staging_render_output_dir = staging["render_output_dir"]
    final_render_rows = _rewrite_rgbd_render_paths(
        render_rows,
        staging_render_output_dir=staging_render_output_dir,
        render_output_dir=render_output_dir,
    )
    final_hdf5_path_rows = _rewrite_rgbd_render_paths(
        hdf5_path_rows,
        staging_render_output_dir=staging_render_output_dir,
        render_output_dir=render_output_dir,
    )
    _write_jsonl_rows(staging["render_manifest_path"], final_render_rows)
    _write_jsonl_rows(staging["success_manifest_path"], success_rows)
    _write_jsonl_rows(staging["failure_manifest_path"], failure_rows)
    if success_rows:
        for demo_manifest_path in staging_render_output_dir.rglob("manifest.jsonl"):
            _rewrite_rgbd_render_manifest_file(
                demo_manifest_path,
                staging_render_output_dir=staging_render_output_dir,
                render_output_dir=render_output_dir,
            )
        _copy_hdf5_with_rgbd_paths(
            input_path=input_path,
            output_path=staging["output_path"],
            path_rows_by_demo=final_hdf5_path_rows,
            render_manifest_path=render_manifest_path,
        )
        if render_output_dir.exists():
            shutil.rmtree(render_output_dir, ignore_errors=True)
        render_output_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_render_output_dir.replace(render_output_dir)
        staging["render_manifest_path"].replace(render_manifest_path)
        staging["success_manifest_path"].replace(success_manifest_path)
        staging["failure_manifest_path"].replace(failure_manifest_path)
        staging["output_path"].replace(output_path)
    shutil.rmtree(staging["root"], ignore_errors=True)
    try:
        staging["root"].parent.rmdir()
    except OSError:
        pass


def _camera_list(raw: str) -> list[str]:
    values = [part.strip() for part in str(raw or "").replace(";", ",").split(",") if part.strip()]
    return values or ["top", "front", "right"]


def _mirror_render_endpoint(endpoint: str) -> str:
    trimmed = str(endpoint or "http://127.0.0.1:8766/render").strip().rstrip("/")
    if not trimmed:
        return "http://127.0.0.1:8766/render"
    if trimmed.endswith("/render"):
        return trimmed
    if trimmed.endswith("/joints"):
        return trimmed[: -len("/joints")] + "/render"
    return trimmed + "/render"


def _mirror_joint_state_from_lab_action(row: Any, *, calibration: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    import numpy as np

    from utils.isaac_omx_mirror_mapping import ISAAC_OMX_JOINT_MAP, positions_to_joint_state

    action = np.asarray(row, dtype=np.float64).reshape(-1)
    joint_count = min(len(action), len(ISAAC_OMX_JOINT_MAP))
    positions = {
        int(ISAAC_OMX_JOINT_MAP[index]["motor_id"]): math.degrees(float(action[index]))
        for index in range(joint_count)
    }
    joint_state = positions_to_joint_state(positions, calibration=calibration, values_are_isaac_targets=True)
    index_by_motor_id = {
        int(ISAAC_OMX_JOINT_MAP[index]["motor_id"]): index
        for index in range(joint_count)
    }
    for item in joint_state:
        motor_id = int(item.get("motor_id", -1))
        action_index = index_by_motor_id.get(motor_id)
        item.pop("source_value", None)
        item.pop("base_target_value", None)
        item["source_unit"] = "lab_action_rad"
        item["target_contract"] = "precomputed_isaac_joint_target_deg"
        if action_index is not None:
            item["source_value_rad"] = float(action[action_index])
    return joint_state


def _mirror_specimen_pose_from_hdf5_demo(demo: Any) -> dict[str, Any]:
    import numpy as np

    try:
        root_pose = demo["initial_state"]["rigid_object"]["red_cube"]["root_pose"][:]
    except Exception:  # noqa: BLE001
        return {}
    values = np.asarray(root_pose, dtype=np.float64).reshape(-1)
    if values.size < 3:
        return {}
    pose: dict[str, Any] = {
        "schema": "specimen_pose.v1",
        "source": "isaac_lab_mimic_hdf5_initial_state",
        "position_isaac_world_mm": {
            "x": float(values[0]) * 1000.0,
            "y": float(values[1]) * 1000.0,
            "z": float(values[2]) * 1000.0,
        },
    }
    yaw_deg = _yaw_deg_from_lab_root_pose(values)
    if yaw_deg is not None:
        pose["orientation_deg"] = {"yaw": float(yaw_deg)}
    return {
        "ok": True,
        "source": "isaac_lab_mimic_hdf5_initial_state",
        "pose": pose,
    }


def _yaw_deg_from_lab_root_pose(values: Any) -> float | None:
    try:
        if len(values) < 7:
            return None
        qx, qy, qz, qw = (float(values[3]), float(values[4]), float(values[5]), float(values[6]))
        norm = math.sqrt((qx * qx) + (qy * qy) + (qz * qz) + (qw * qw))
        if norm <= 1e-9:
            return None
        qx /= norm
        qy /= norm
        qz /= norm
        qw /= norm
        siny_cosp = 2.0 * ((qw * qz) + (qx * qy))
        cosy_cosp = 1.0 - (2.0 * ((qy * qy) + (qz * qz)))
        return math.degrees(math.atan2(siny_cosp, cosy_cosp))
    except Exception:  # noqa: BLE001
        return None


def _render_generated_dataset_rgbd_via_mirror(
    *,
    dataset_path: Path,
    output_path: Path,
    success_manifest_path: Path,
    failure_manifest_path: Path,
    render_output_dir: Path,
    render_manifest_path: Path,
    cameras: list[str],
    camera_width: int,
    camera_height: int,
    fps: float,
    max_demos: int,
    mirror_endpoint: str,
    mirror_timeout_s: float,
    mirror_settle_timeout_s: float = 4.0,
    mirror_settle_tolerance_deg: float = 5.0,
    mirror_settle_velocity_tolerance_deg_s: float = 10.0,
) -> dict[str, object]:
    if not dataset_path.is_file():
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_RGBD_INPUT_MISSING",
            "message": f"Generated Mimic HDF5 does not exist: {dataset_path}",
        }
    endpoint = _mirror_render_endpoint(mirror_endpoint)
    final_output_path = output_path
    final_success_manifest_path = success_manifest_path
    final_failure_manifest_path = failure_manifest_path
    final_render_output_dir = render_output_dir
    final_render_manifest_path = render_manifest_path
    staging = _rgbd_render_staging_paths(
        output_path=output_path,
        success_manifest_path=success_manifest_path,
        failure_manifest_path=failure_manifest_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
    )
    render_output_dir = staging["render_output_dir"]
    render_output_dir.mkdir(parents=True, exist_ok=True)

    import h5py

    render_rows: list[dict[str, object]] = []
    success_rows: list[dict[str, object]] = []
    failure_rows: list[dict[str, object]] = []
    hdf5_path_rows: dict[str, dict[str, list[str]]] = {}
    replayed_frames = 0
    rendered_frames = 0
    camera_frame_count: dict[str, int] = {camera: 0 for camera in cameras}
    frame_source_count: dict[str, int] = {}
    source_episode_by_demo = _mimic_source_episode_index_by_demo(dataset_path)
    motion_audits: list[dict[str, object]] = []
    post_failures: list[dict[str, object]] = []
    preplay_rows: list[dict[str, object]] = []
    preplay_warnings: list[dict[str, object]] = []

    with h5py.File(dataset_path, "r") as handle:
        demos = handle.get("data")
        names = sorted(str(name) for name in demos.keys()) if demos is not None else []
        total_demo_count = len(names)
        if int(max_demos) > 0:
            names = names[: int(max_demos)]
        for demo_index, name in enumerate(names):
            demo = demos[name]
            actions = demo["actions"][:]
            safe_demo = str(name).replace("/", "_")
            demo_output_dir = render_output_dir / safe_demo
            demo_manifest_path = demo_output_dir / "manifest.jsonl"
            demo_paths: dict[str, list[str]] = {f"{camera}_rgb_path": [] for camera in cameras}
            demo_paths.update({f"{camera}_depth_path": [] for camera in cameras})
            rgb_motion_samples: dict[str, list[dict[str, object]]] = {camera: [] for camera in cameras}
            readback_frame_indices = _visual_readback_frame_indices(len(actions))
            specimen_pose = _mirror_specimen_pose_from_hdf5_demo(demo)
            preplay = _preplay_mirror_first_frame_before_rgbd_render(
                endpoint=endpoint,
                joint_state=_mirror_joint_state_from_lab_action(actions[0]) if len(actions) else [],
                specimen_pose=specimen_pose,
                demo_index=demo_index,
                demo_name=name,
                post_timeout_s=mirror_timeout_s,
                settle_timeout_s=mirror_settle_timeout_s,
                tolerance_deg=mirror_settle_tolerance_deg,
                velocity_tolerance_deg_s=mirror_settle_velocity_tolerance_deg_s,
            )
            preplay_rows.append(preplay)
            if not preplay.get("ok"):
                preplay_warnings.append(preplay)
            demo_rendered_frames = 0
            demo_complete_frames = 0
            demo_failures: list[dict[str, object]] = []
            for frame_index, row in enumerate(actions):
                started = time.monotonic()
                joint_state = _mirror_joint_state_from_lab_action(row)
                render_request = {
                    "schema": "atr.isaac_rgbd.render_request.v1",
                    "enabled": True,
                    "attempt_id": f"mimic_rgbd_{demo_index:06d}",
                    "episode_index": int(demo_index),
                    "frame_index": int(frame_index),
                    "sample_index": int(frame_index) + 1,
                    "target_fps": float(fps or 15.0),
                    "cameras": list(cameras),
                    "output_dir": str(demo_output_dir),
                    "resolution": [int(camera_width), int(camera_height)],
                    "source_dataset_path": str(dataset_path),
                    "source_demo": name,
                    "render_source": "isaac_sim_mirror_http",
                }
                payload: dict[str, Any] = {
                    "schema": "atr.lerobot.isaac_lab_mimic_rgbd.mirror_frame.v1",
                    "sample_index": int(frame_index) + 1,
                    "joint_state": joint_state,
                    "render_request": render_request,
                }
                if frame_index == 0 and specimen_pose:
                    payload["specimen_pose"] = specimen_pose
                response = _post_json(endpoint, payload, timeout_s=mirror_timeout_s)
                replayed_frames += 1
                if response.get("ok") is False and str(response.get("status") or "").startswith("post_"):
                    frame_paths = {}
                else:
                    frame_paths = _mirror_frame_paths_from_response_or_manifest(
                        response=response,
                        manifest_path=demo_manifest_path,
                        cameras=cameras,
                        frame_index=frame_index,
                        timeout_s=max(float(mirror_timeout_s), 10.0),
                    )
                    if not frame_paths:
                        retry_payload = {**payload, "render_request": {**render_request, "retry_index": 1}}
                        retry_payload.pop("specimen_pose", None)
                        time.sleep(0.1)
                        retry_response = _post_json(endpoint, retry_payload, timeout_s=mirror_timeout_s)
                        if retry_response.get("ok") is not False:
                            response = retry_response
                            frame_paths = _mirror_frame_paths_from_response_or_manifest(
                                response=retry_response,
                                manifest_path=demo_manifest_path,
                                cameras=cameras,
                                frame_index=frame_index,
                                timeout_s=max(float(mirror_timeout_s), 10.0),
                            )
                frame_source = "isaac_sim_mirror_http" if frame_paths else "missing"
                frame_source_count[frame_source] = int(frame_source_count.get(frame_source, 0)) + 1
                if frame_paths:
                    for camera in cameras:
                        paths = frame_paths.get(camera) or {}
                        if paths:
                            camera_frame_count[camera] = camera_frame_count.get(camera, 0) + 1
                        demo_paths.setdefault(f"{camera}_rgb_path", []).append(str(paths.get("rgb_path") or ""))
                        demo_paths.setdefault(f"{camera}_depth_path", []).append(str(paths.get("depth_path") or ""))
                    render_rows.append(
                        {
                            "schema": "atr.lerobot.isaac_lab_mimic_rgbd.frame.v1",
                            "generated_demo": name,
                            "demo_index": int(demo_index),
                            "frame_index": int(frame_index),
                            "render_method": "isaac_sim_mirror_http",
                            "endpoint": endpoint,
                            "cameras": frame_paths,
                        }
                    )
                    demo_rendered_frames += 1
                    rendered_frames += 1
                    if all(str(camera) in frame_paths for camera in cameras):
                        demo_complete_frames += 1
                    if frame_index in readback_frame_indices:
                        _record_rgb_motion_samples_from_paths(
                            rgb_motion_samples,
                            frame_paths,
                            frame_index=frame_index,
                            cameras=cameras,
                        )
                else:
                    failure = {
                        "frame_index": int(frame_index),
                        "response_status": str(response.get("status") or ""),
                        "failure_code": str(response.get("failure_code") or ""),
                        "message": str(response.get("message") or "mirror render did not produce all requested camera files"),
                    }
                    demo_failures.append(failure)
                    post_failures.append({"demo": name, **failure})
                    for camera in cameras:
                        demo_paths.setdefault(f"{camera}_rgb_path", []).append("")
                        demo_paths.setdefault(f"{camera}_depth_path", []).append("")
                if fps > 0:
                    delay = max(0.0, (1.0 / fps) - (time.monotonic() - started))
                    if delay:
                        time.sleep(delay)
            motion_audit = _rgb_motion_audit(
                demo_name=name,
                actions=actions,
                samples_by_camera=rgb_motion_samples,
            )
            motion_audits.append(motion_audit)
            if (
                demo_complete_frames == int(len(actions))
                and demo_rendered_frames > 0
                and motion_audit.get("status") != "blocked"
            ):
                hdf5_path_rows[name] = demo_paths
                success_rows.append(
                    {
                        "schema": "atr.lerobot.isaac_lab_mimic_rgbd.success.v1",
                        "source_type": "isaac_lab_mimic_rgbd",
                        "generator": "isaac_sim_mirror_rgbd_post_render",
                        "generated_demo": name,
                        "trajectory_id": f"mimic_rgbd_{demo_index:06d}",
                        "generated_index": int(demo_index),
                        "episode_index": int(demo_index),
                        "source_episode_index": _source_episode_index_for_generated_demo(
                            demo,
                            demo_name=name,
                            source_episode_by_demo=source_episode_by_demo,
                        ),
                        "frame_count": int(len(actions)),
                        "rendered_frame_count": int(demo_rendered_frames),
                        "complete_frame_count": int(demo_complete_frames),
                        "camera_names": list(cameras),
                        "artifacts": {
                            "hdf5_path": "mimic_rgbd/generated_dataset_rgbd.hdf5",
                            "render_manifest_path": "mimic_rgbd/manifest.jsonl",
                            "render_root": "mimic_rgbd/renders",
                        },
                        "training": {"eligible": True, "fidelity_weight": 0.25},
                        "metrics": {
                            "success": True,
                            "rgbd_render": True,
                            "mirror_http_render": True,
                            "motion_audit": motion_audit,
                            "camera_count": int(len(cameras)),
                            "rendered_frame_count": int(demo_rendered_frames),
                            "complete_frame_count": int(demo_complete_frames),
                        },
                    }
                )
            else:
                failure_label = "camera_frames_static" if motion_audit.get("status") == "blocked" else "mirror_camera_frames_incomplete"
                failure_rows.append(
                    {
                        "schema": "atr.lerobot.isaac_lab_mimic_rgbd.failure.v1",
                        "source_type": "isaac_lab_mimic_rgbd",
                        "generator": "isaac_sim_mirror_rgbd_post_render",
                        "generated_demo": name,
                        "trajectory_id": f"mimic_rgbd_{demo_index:06d}",
                        "frame_count": int(len(actions)),
                        "rendered_frame_count": int(demo_rendered_frames),
                        "complete_frame_count": int(demo_complete_frames),
                        "metrics": {"success": False, "rgbd_render": False, "mirror_http_render": True},
                        "failure_label": failure_label,
                        "message": str(
                            motion_audit.get("message")
                            if motion_audit.get("status") == "blocked"
                            else "One or more requested RGB-D files were missing from the Isaac Sim mirror render."
                        ),
                        "motion_audit": motion_audit,
                        "frame_failures": demo_failures[:20],
                    }
                )

    _commit_rgbd_render_outputs(
        input_path=dataset_path,
        output_path=final_output_path,
        success_manifest_path=final_success_manifest_path,
        failure_manifest_path=final_failure_manifest_path,
        render_output_dir=final_render_output_dir,
        render_manifest_path=final_render_manifest_path,
        staging=staging,
        render_rows=render_rows,
        success_rows=success_rows,
        failure_rows=failure_rows,
        hdf5_path_rows=hdf5_path_rows,
    )
    return {
        "schema": "atr.lerobot.isaac_lab_mimic_rgbd.render.summary.v1",
        "ok": bool(success_rows),
        "status": "completed" if success_rows else "blocked",
        "blocker": "" if success_rows else "JOINT_REPLAY_RGBD_MIRROR_RENDER_FAILED",
        "mode": "rgbd_render_after_generation",
        "backend": "isaac_sim_mirror_http",
        "mirror_endpoint": endpoint,
        "dataset_path": str(dataset_path),
        "output_path": str(final_output_path),
        "render_output_dir": str(final_render_output_dir),
        "render_manifest_path": str(final_render_manifest_path),
        "success_manifest_path": str(final_success_manifest_path),
        "failure_manifest_path": str(final_failure_manifest_path),
        "visual_demo_count": int(len(success_rows) + len(failure_rows)),
        "visual_total_demo_count": int(total_demo_count),
        "visual_max_demos": int(max_demos),
        "success_count": int(len(success_rows)),
        "failure_count": int(len(failure_rows)),
        "replayed_frames": int(replayed_frames),
        "rendered_frames": int(rendered_frames),
        "camera_frame_count": camera_frame_count,
        "frame_source_count": frame_source_count,
        "motion_audits": motion_audits,
        "preplay_policy": "stop_specimen_play_settle_per_episode",
        "preplay_count": int(len(preplay_rows)),
        "preplay_warning_count": int(len(preplay_warnings)),
        "last_preplay": preplay_rows[-1] if preplay_rows else {},
        "last_preplay_warning": preplay_warnings[-1] if preplay_warnings else {},
        "post_failure_count": int(len(post_failures)),
        "post_failures": post_failures[:20],
        "rgbd_hdf5_available": bool(output_path.is_file()),
    }


def _post_json(endpoint: str, payload: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(float(timeout_s), 0.1)) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return {"ok": False, "status": "post_failed", "failure_code": "MIRROR_HTTP_POST_FAILED", "message": str(exc)}
    except TimeoutError as exc:
        return {"ok": False, "status": "post_timeout", "failure_code": "MIRROR_HTTP_POST_TIMEOUT", "message": str(exc)}
    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {"ok": False, "status": "invalid_response", "failure_code": "MIRROR_HTTP_INVALID_JSON", "message": body[:200]}
    return parsed if isinstance(parsed, dict) else {"ok": False, "status": "invalid_response", "message": str(parsed)}


def _get_json(endpoint: str, *, timeout_s: float) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(endpoint, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=max(float(timeout_s), 0.1)) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return {"ok": False, "status": "get_failed", "failure_code": "MIRROR_HTTP_GET_FAILED", "message": str(exc)}
    except TimeoutError as exc:
        return {"ok": False, "status": "get_timeout", "failure_code": "MIRROR_HTTP_GET_TIMEOUT", "message": str(exc)}
    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {"ok": False, "status": "invalid_response", "failure_code": "MIRROR_HTTP_INVALID_JSON", "message": body[:200]}
    return parsed if isinstance(parsed, dict) else {"ok": False, "status": "invalid_response", "message": str(parsed)}


def _mirror_endpoint_path(endpoint: str, path: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/render").strip())
    normalized_path = "/" + str(path or "").strip().lstrip("/")
    if not parsed.scheme or not parsed.netloc:
        return f"http://127.0.0.1:8766{normalized_path}"
    return parsed._replace(path=normalized_path, params="", query="", fragment="").geturl()


def _preplay_mirror_first_frame_before_rgbd_render(
    *,
    endpoint: str,
    joint_state: list[dict[str, Any]],
    specimen_pose: dict[str, Any],
    demo_index: int,
    demo_name: str,
    post_timeout_s: float,
    settle_timeout_s: float,
    tolerance_deg: float,
    velocity_tolerance_deg_s: float,
) -> dict[str, object]:
    if not joint_state:
        return {
            "ok": False,
            "status": "empty_preplay_joint_state",
            "demo_index": int(demo_index),
            "demo_name": str(demo_name),
            "message": "Cannot preplay RGB-D render because the source demo has no joint action row.",
        }
    stop = _post_json(
        _mirror_endpoint_path(endpoint, "/timeline/stop"),
        {"reason": "isaac_lab_mimic_rgbd_preplay_stop"},
        timeout_s=post_timeout_s,
    )
    if not bool(stop.get("ok", True)):
        return {
            "ok": False,
            "status": "timeline_stop_failed",
            "demo_index": int(demo_index),
            "demo_name": str(demo_name),
            "timeline_stop": stop,
            "message": str(stop.get("message") or stop.get("status") or "Isaac timeline stop failed."),
        }
    specimen_result: dict[str, Any] = {}
    if specimen_pose:
        specimen_result = _post_json(
            _mirror_endpoint_path(endpoint, "/specimen_pose"),
            dict(specimen_pose),
            timeout_s=post_timeout_s,
        )
        if not bool(specimen_result.get("ok", True)):
            return {
                "ok": False,
                "status": "specimen_pose_failed",
                "demo_index": int(demo_index),
                "demo_name": str(demo_name),
                "timeline_stop": stop,
                "specimen_pose": specimen_result,
                "message": str(
                    specimen_result.get("message")
                    or specimen_result.get("status")
                    or "Recorded specimen pose was not accepted by Isaac."
                ),
            }
    play = _post_json(
        _mirror_endpoint_path(endpoint, "/timeline/play"),
        {"reason": "isaac_lab_mimic_rgbd_preplay", "skip_specimen_pose_on_play": True},
        timeout_s=post_timeout_s,
    )
    if not bool(play.get("ok", True)):
        return {
            "ok": False,
            "status": "timeline_play_failed",
            "demo_index": int(demo_index),
            "demo_name": str(demo_name),
            "timeline_stop": stop,
            "specimen_pose": specimen_result,
            "timeline": play,
            "message": str(play.get("message") or play.get("status") or "Isaac timeline play failed."),
        }
    joint_endpoint = _mirror_endpoint_path(endpoint, "/joints")
    settle = _wait_for_mirror_joint_settle(
        joint_endpoint=joint_endpoint,
        state_endpoint=_mirror_endpoint_path(endpoint, "/state"),
        payload={
            "schema": "atr.lerobot.isaac_lab_mimic_rgbd.preplay.v1",
            "mode": "preplay",
            "sample_index": 1,
            "joint_state": [dict(item) for item in joint_state],
            "isaac_rgbd_preplay": {
                "reason": "first_frame_settle_before_render",
                "demo_index": int(demo_index),
                "demo_name": str(demo_name),
                "frame_index": 0,
            },
        },
        post_timeout_s=post_timeout_s,
        settle_timeout_s=settle_timeout_s,
        tolerance_deg=tolerance_deg,
        velocity_tolerance_deg_s=velocity_tolerance_deg_s,
    )
    return {
        "ok": bool(settle.get("ok")),
        "status": "preplay_stable" if settle.get("ok") else "preplay_unstable",
        "demo_index": int(demo_index),
        "demo_name": str(demo_name),
        "timeline_stop": stop,
        "specimen_pose": specimen_result,
        "timeline": play,
        "joint_endpoint": joint_endpoint,
        "settle": settle,
        "message": "" if settle.get("ok") else str(settle.get("message") or settle.get("status") or "Isaac preplay did not stabilize."),
    }


def _wait_for_mirror_joint_settle(
    *,
    joint_endpoint: str,
    state_endpoint: str,
    payload: dict[str, Any],
    post_timeout_s: float,
    settle_timeout_s: float,
    tolerance_deg: float,
    velocity_tolerance_deg_s: float,
) -> dict[str, object]:
    deadline = time.monotonic() + max(0.1, float(settle_timeout_s))
    attempts = 0
    last_summary: dict[str, object] = {"ok": False, "status": "not_checked"}
    while time.monotonic() <= deadline:
        attempts += 1
        post = _post_json(joint_endpoint, dict(payload), timeout_s=post_timeout_s)
        if not bool(post.get("ok", True)):
            return {
                "ok": False,
                "status": "joint_post_failed",
                "attempts": attempts,
                "post": post,
                "message": str(post.get("message") or post.get("failure_code") or post.get("status") or "failed to post joint preplay payload"),
            }
        time.sleep(0.2)
        state = _get_json(state_endpoint, timeout_s=post_timeout_s)
        last_summary = _mirror_joint_settle_summary(
            state,
            tolerance_deg=tolerance_deg,
            velocity_tolerance_deg_s=velocity_tolerance_deg_s,
        )
        last_summary["attempts"] = attempts
        if last_summary.get("ok"):
            return last_summary
        time.sleep(0.3)
    return {
        **last_summary,
        "ok": False,
        "status": "settle_timeout",
        "attempts": attempts,
        "message": (
            f"Timed out waiting for Isaac joint readback to settle within {tolerance_deg:g} deg "
            f"and {velocity_tolerance_deg_s:g} deg/s."
        ),
    }


def _mirror_joint_settle_summary(
    state: dict[str, Any],
    *,
    tolerance_deg: float,
    velocity_tolerance_deg_s: float,
) -> dict[str, object]:
    last_apply = state.get("last_apply_result") if isinstance(state.get("last_apply_result"), dict) else {}
    rows = last_apply.get("joint_readback") if isinstance(last_apply, dict) else []
    comparable: list[dict[str, object]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if row.get("state_position") is None or row.get("target_value") is None:
            continue
        error = row.get("target_minus_state")
        if error is None:
            error = _safe_float(row.get("target_value"), 0.0) - _safe_float(row.get("state_position"), 0.0)
        velocity = _safe_float(row.get("state_velocity"), 0.0)
        comparable.append(
            {
                "motor_id": row.get("motor_id"),
                "name": str(row.get("name") or ""),
                "target_value": _safe_float(row.get("target_value"), 0.0),
                "state_position": _safe_float(row.get("state_position"), 0.0),
                "target_minus_state": _safe_float(error, 0.0),
                "state_velocity": velocity,
                "abs_error_deg": abs(_safe_float(error, 0.0)),
                "abs_velocity_deg_s": abs(velocity),
            }
        )
    if not comparable:
        return {
            "ok": False,
            "status": "joint_readback_unavailable",
            "sample_count": state.get("sample_count"),
            "comparable_count": 0,
            "message": "Isaac receiver state did not include comparable joint_readback rows.",
        }
    max_error = max(_safe_float(row.get("abs_error_deg"), 0.0) for row in comparable)
    max_velocity = max(_safe_float(row.get("abs_velocity_deg_s"), 0.0) for row in comparable)
    stable = max_error <= tolerance_deg and max_velocity <= velocity_tolerance_deg_s
    return {
        "ok": stable,
        "status": "stable" if stable else "settling",
        "sample_count": state.get("sample_count"),
        "comparable_count": len(comparable),
        "max_abs_error_deg": max_error,
        "max_abs_velocity_deg_s": max_velocity,
        "tolerance_deg": tolerance_deg,
        "velocity_tolerance_deg_s": velocity_tolerance_deg_s,
        "joints": comparable[:12],
    }


def _mirror_frame_paths_from_response_or_manifest(
    *,
    response: dict[str, Any],
    manifest_path: Path,
    cameras: list[str],
    frame_index: int,
    timeout_s: float,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + max(float(timeout_s), 0.1)
    while True:
        for row in _candidate_mirror_render_rows(response=response, manifest_path=manifest_path):
            if int(_safe_int(row.get("frame_index"), -1)) != int(frame_index):
                continue
            frame_paths = _mirror_files_to_frame_paths(row.get("files"), cameras)
            if all(camera in frame_paths for camera in cameras):
                return frame_paths
        if time.monotonic() >= deadline:
            return {}
        time.sleep(0.02)


def _candidate_mirror_render_rows(*, response: dict[str, Any], manifest_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(response, dict) and response.get("files"):
        rows.append(response)
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in reversed(lines[-20:]):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _mirror_files_to_frame_paths(files: Any, cameras: list[str]) -> dict[str, dict[str, str]]:
    if not isinstance(files, list):
        return {}
    result: dict[str, dict[str, str]] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        camera = str(item.get("camera") or "")
        if camera not in cameras:
            continue
        kind = str(item.get("kind") or "").lower()
        path = str(item.get("path") or "").strip()
        if not kind or not path or not Path(path).is_file():
            continue
        row = result.setdefault(camera, {})
        if kind == "rgb":
            row["rgb_path"] = path
            row["rgb_encoding"] = str(item.get("encoding") or "png")
        elif kind == "depth":
            row["depth_path"] = path
            row["depth_encoding"] = str(item.get("encoding") or "png16")
            row["depth_scale_m_per_unit"] = 0.001
    return {
        camera: paths
        for camera, paths in result.items()
        if paths.get("rgb_path") and paths.get("depth_path")
    }


def _record_rgb_motion_samples_from_paths(
    samples_by_camera: dict[str, list[dict[str, object]]],
    frame_paths: dict[str, dict[str, str]],
    *,
    frame_index: int,
    cameras: list[str],
) -> None:
    from PIL import Image
    import numpy as np

    frames: dict[str, dict[str, Any]] = {}
    for camera in cameras:
        rgb_path = str((frame_paths.get(camera) or {}).get("rgb_path") or "")
        if not rgb_path:
            continue
        try:
            rgb = np.asarray(Image.open(rgb_path).convert("RGB"))
        except Exception:  # noqa: BLE001
            continue
        frames[camera] = {"rgb": rgb}
    _record_rgb_motion_samples(samples_by_camera, frames, frame_index=frame_index, cameras=cameras)


def _safe_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None and result < minimum:
        return int(minimum)
    return result


def _safe_float(value: Any, default: float, *, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    if minimum is not None and result < minimum:
        return float(minimum)
    return result


def _render_generated_dataset_rgbd(
    *,
    dataset_path: Path,
    output_path: Path,
    success_manifest_path: Path,
    failure_manifest_path: Path,
    render_output_dir: Path,
    render_manifest_path: Path,
    cameras: list[str],
    task_name: str,
    num_envs: int,
    external_callback: str,
    domain_randomization_profile: str,
    camera_mode: str,
    camera_width: int,
    camera_height: int,
    enable_cameras: bool,
    rendering_mode: str,
    visualizer: str,
    kit_args: str,
    fps: float,
    max_demos: int,
) -> dict[str, object]:
    if not task_name:
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_RGBD_TASK_MISSING",
            "message": "RGB-D render requires an Isaac Lab task name.",
        }
    if not dataset_path.is_file():
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_RGBD_INPUT_MISSING",
            "message": f"Generated Mimic HDF5 does not exist: {dataset_path}",
        }
    os.environ["ROBOTIS_OMX_DOMAIN_RANDOMIZATION_PROFILE"] = domain_randomization_profile
    os.environ["ROBOTIS_OMX_CAMERA_MODE"] = camera_mode
    os.environ["ROBOTIS_OMX_CAMERA_WIDTH"] = str(camera_width)
    os.environ["ROBOTIS_OMX_CAMERA_HEIGHT"] = str(camera_height)
    os.environ.setdefault("ROBOTIS_OMX_USE_FABRIC", "0")
    final_output_path = output_path
    final_success_manifest_path = success_manifest_path
    final_failure_manifest_path = failure_manifest_path
    final_render_output_dir = render_output_dir
    final_render_manifest_path = render_manifest_path
    staging = _rgbd_render_staging_paths(
        output_path=output_path,
        success_manifest_path=success_manifest_path,
        failure_manifest_path=failure_manifest_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
    )
    render_output_dir = staging["render_output_dir"]
    render_output_dir.mkdir(parents=True, exist_ok=True)
    simulation_app = None
    env = None
    try:
        from isaaclab.app import AppLauncher

        headless = str(visualizer or "").lower() in {"", "none", "off", "headless"}
        app_launcher = AppLauncher(
            {
                "visualizer": [] if headless else [visualizer],
                "visualizer_explicit": not headless,
                "headless": headless,
                "enable_cameras": bool(enable_cameras),
                "rendering_mode": rendering_mode,
                "kit_args": kit_args,
            }
        )
        simulation_app = app_launcher.app
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_RGBD_APP_LAUNCH_FAILED",
            "message": f"Could not launch Isaac Lab app for RGB-D render: {exc}",
            "dataset_path": str(dataset_path),
            "output_path": str(output_path),
        }
    try:
        _call_external_callback(external_callback)
        import gymnasium as gym
        import h5py
        import torch
        from isaaclab_tasks.utils import parse_env_cfg

        env_cfg = parse_env_cfg(task_name, num_envs=max(1, int(num_envs)), use_fabric=False)
        env = gym.make(task_name, cfg=env_cfg)
        env_num_envs = int(getattr(env.unwrapped, "num_envs", getattr(env, "num_envs", 1)))
        render_rows: list[dict[str, object]] = []
        success_rows: list[dict[str, object]] = []
        failure_rows: list[dict[str, object]] = []
        hdf5_path_rows: dict[str, dict[str, list[str]]] = {}
        replayed_frames = 0
        rendered_frames = 0
        camera_frame_count: dict[str, int] = {camera: 0 for camera in cameras}
        frame_source_count: dict[str, int] = {}
        source_episode_by_demo = _mimic_source_episode_index_by_demo(dataset_path)
        readback_samples: list[dict[str, object]] = []
        motion_audits: list[dict[str, object]] = []
        visual_frame_state_last: dict[str, bool] = {}
        visual_frame_state_applied = 0
        with h5py.File(dataset_path, "r") as handle:
            demos = handle.get("data")
            names = sorted(str(name) for name in demos.keys()) if demos is not None else []
            total_demo_count = len(names)
            if int(max_demos) > 0:
                names = names[: int(max_demos)]
            for demo_index, name in enumerate(names):
                if not simulation_app.is_running():
                    break
                env.reset()
                initial_state_last = _apply_hdf5_demo_initial_state(env, demos[name], apply_rigid_objects=True)
                if any(initial_state_last.values()):
                    _refresh_env_after_hdf5_initial_state(env)
                actions = demos[name]["actions"][:]
                readback_frame_indices = _visual_readback_frame_indices(len(actions))
                rgb_motion_samples: dict[str, list[dict[str, object]]] = {camera: [] for camera in cameras}
                demo_paths: dict[str, list[str]] = {
                    f"{camera}_rgb_path": [] for camera in cameras
                }
                demo_paths.update({f"{camera}_depth_path": [] for camera in cameras})
                demo_rendered_frames = 0
                demo_complete_frames = 0
                for frame_index, row in enumerate(actions):
                    if not simulation_app.is_running():
                        break
                    started = time.monotonic()
                    action = _visual_action_tensor(torch, row, env, env_num_envs)
                    _apply_visual_joint_frame(env, action)
                    step_result = env.step(action)
                    visual_frame_state_last = _apply_hdf5_demo_frame_state(
                        env,
                        demos[name],
                        frame_index=frame_index,
                        apply_rigid_objects=True,
                    )
                    if any(visual_frame_state_last.values()):
                        visual_frame_state_applied += 1
                        _refresh_env_after_hdf5_initial_state(env)
                    else:
                        _apply_visual_joint_frame(env, action)
                    render_method = _pump_visual_viewport(env, simulation_app)
                    obs_payload = _step_observation_payload(step_result, env)
                    scene_frames = _extract_rgbd_camera_frames_from_scene(env, cameras)
                    obs_frames = _extract_rgbd_camera_frames(obs_payload, cameras)
                    frames = _merge_rgbd_camera_frames(scene_frames, obs_frames)
                    frame_source = "scene_camera_data_output" if scene_frames else "observation_payload"
                    if scene_frames and obs_frames and set(scene_frames) != set(frames):
                        frame_source = "scene_camera_data_output_with_observation_fallback"
                    frame_source_count[frame_source] = int(frame_source_count.get(frame_source, 0)) + 1
                    replayed_frames += 1
                    if frame_index in readback_frame_indices:
                        sample = _visual_joint_readback_sample(
                            env,
                            action,
                            demo_name=name,
                            frame_index=frame_index,
                            phase="rgbd_render_after_env_step",
                        )
                        if sample:
                            readback_samples.append(sample)
                        _record_rgb_motion_samples(
                            rgb_motion_samples,
                            frames,
                            frame_index=frame_index,
                            cameras=cameras,
                        )
                    if frames:
                        frame_paths = _write_rgbd_frame_files(
                            render_output_dir,
                            demo_name=name,
                            frame_index=frame_index,
                            frames=frames,
                        )
                        for camera in cameras:
                            paths = frame_paths.get(camera) or {}
                            if paths:
                                camera_frame_count[camera] = camera_frame_count.get(camera, 0) + 1
                            demo_paths.setdefault(f"{camera}_rgb_path", []).append(str(paths.get("rgb_path") or ""))
                            demo_paths.setdefault(f"{camera}_depth_path", []).append(str(paths.get("depth_path") or ""))
                        render_rows.append(
                            {
                                "schema": "atr.lerobot.isaac_lab_mimic_rgbd.frame.v1",
                                "generated_demo": name,
                                "demo_index": int(demo_index),
                                "frame_index": int(frame_index),
                                "render_method": render_method,
                                "cameras": frame_paths,
                            }
                        )
                        demo_rendered_frames += 1
                        rendered_frames += 1
                        if all(str(camera) in frame_paths for camera in cameras):
                            demo_complete_frames += 1
                    else:
                        for camera in cameras:
                            demo_paths.setdefault(f"{camera}_rgb_path", []).append("")
                            demo_paths.setdefault(f"{camera}_depth_path", []).append("")
                    if fps > 0:
                        delay = max(0.0, (1.0 / fps) - (time.monotonic() - started))
                        if delay:
                            time.sleep(delay)
                motion_audit = _rgb_motion_audit(
                    demo_name=name,
                    actions=actions,
                    samples_by_camera=rgb_motion_samples,
                )
                motion_audits.append(motion_audit)
                if (
                    demo_complete_frames == int(len(actions))
                    and demo_rendered_frames > 0
                    and motion_audit.get("status") != "blocked"
                ):
                    hdf5_path_rows[name] = demo_paths
                    success_rows.append(
                        {
                            "schema": "atr.lerobot.isaac_lab_mimic_rgbd.success.v1",
                            "source_type": "isaac_lab_mimic_rgbd",
                            "generator": "isaac_lab_mimic_rgbd_post_render",
                            "generated_demo": name,
                            "trajectory_id": f"mimic_rgbd_{demo_index:06d}",
                            "generated_index": int(demo_index),
                            "episode_index": int(demo_index),
                            "source_episode_index": _source_episode_index_for_generated_demo(
                                demos[name],
                                demo_name=name,
                                source_episode_by_demo=source_episode_by_demo,
                            ),
                            "frame_count": int(len(actions)),
                            "rendered_frame_count": int(demo_rendered_frames),
                            "complete_frame_count": int(demo_complete_frames),
                            "camera_names": list(cameras),
                            "artifacts": {
                                "hdf5_path": "mimic_rgbd/generated_dataset_rgbd.hdf5",
                                "render_manifest_path": "mimic_rgbd/manifest.jsonl",
                                "render_root": "mimic_rgbd/renders",
                            },
                            "training": {"eligible": True, "fidelity_weight": 0.25},
                            "metrics": {
                                "success": True,
                                "rgbd_render": True,
                                "motion_audit": motion_audit,
                                "camera_count": int(len(cameras)),
                                "rendered_frame_count": int(demo_rendered_frames),
                                "complete_frame_count": int(demo_complete_frames),
                            },
                        }
                    )
                else:
                    failure_rows.append(
                        {
                            "schema": "atr.lerobot.isaac_lab_mimic_rgbd.failure.v1",
                            "source_type": "isaac_lab_mimic_rgbd",
                            "generated_demo": name,
                            "trajectory_id": f"mimic_rgbd_{demo_index:06d}",
                            "frame_count": int(len(actions)),
                            "rendered_frame_count": int(demo_rendered_frames),
                            "complete_frame_count": int(demo_complete_frames),
                            "metrics": {"success": False, "rgbd_render": False},
                            "failure_label": "camera_frames_static"
                            if motion_audit.get("status") == "blocked"
                            else "camera_observation_incomplete",
                            "message": str(
                                motion_audit.get("message")
                                if motion_audit.get("status") == "blocked"
                                else "One or more requested RGB-D camera observations were missing while replaying this generated demo."
                            ),
                            "motion_audit": motion_audit,
                        }
                    )
        _commit_rgbd_render_outputs(
            input_path=dataset_path,
            output_path=final_output_path,
            success_manifest_path=final_success_manifest_path,
            failure_manifest_path=final_failure_manifest_path,
            render_output_dir=final_render_output_dir,
            render_manifest_path=final_render_manifest_path,
            staging=staging,
            render_rows=render_rows,
            success_rows=success_rows,
            failure_rows=failure_rows,
            hdf5_path_rows=hdf5_path_rows,
        )
        return {
            "schema": "atr.lerobot.isaac_lab_mimic_rgbd.render.summary.v1",
            "ok": bool(success_rows),
            "status": "completed" if success_rows else "blocked",
            "blocker": "" if success_rows else "JOINT_REPLAY_RGBD_NO_CAMERA_FRAMES",
            "mode": "rgbd_render_after_generation",
            "task_name": task_name,
            "num_envs": int(num_envs),
            "dataset_path": str(dataset_path),
            "output_path": str(final_output_path),
            "render_output_dir": str(final_render_output_dir),
            "render_manifest_path": str(final_render_manifest_path),
            "success_manifest_path": str(final_success_manifest_path),
            "failure_manifest_path": str(final_failure_manifest_path),
            "visual_demo_count": int(len(success_rows) + len(failure_rows)),
            "visual_total_demo_count": int(total_demo_count),
            "visual_max_demos": int(max_demos),
            "success_count": int(len(success_rows)),
            "failure_count": int(len(failure_rows)),
            "replayed_frames": int(replayed_frames),
            "rendered_frames": int(rendered_frames),
            "camera_frame_count": camera_frame_count,
            "frame_source_count": frame_source_count,
            "motion_audits": motion_audits,
            "visual_frame_state_applied_count": int(visual_frame_state_applied),
            "visual_frame_state_last": visual_frame_state_last,
            "visual_readback_sample_count": int(len(readback_samples)),
            "visual_readback_samples": readback_samples,
            "visual_readback_target_error_max": _visual_readback_error_max(readback_samples),
            "camera_mode": camera_mode,
            "enable_cameras": bool(enable_cameras),
            "visualizer": visualizer,
            "rgbd_hdf5_available": bool(output_path.is_file()),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_RGBD_RENDER_FAILED",
            "message": f"Could not render Mimic RGB-D data through Isaac Lab replay: {exc}",
            "dataset_path": str(dataset_path),
            "output_path": str(output_path),
            "task_name": task_name,
        }
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass


def _step_observation_payload(step_result: Any, env: Any) -> dict[str, Any]:
    payloads: list[Any] = []
    if isinstance(step_result, tuple) and step_result:
        payloads.append(step_result[0])
    elif step_result is not None:
        payloads.append(step_result)
    unwrapped = getattr(env, "unwrapped", env)
    for source in (getattr(unwrapped, "obs_buf", None), getattr(env, "obs_buf", None)):
        if source is not None:
            payloads.append(source)
    merged: dict[str, Any] = {}
    for payload in payloads:
        flattened = _flatten_observation_tensors(payload)
        merged.update(flattened)
    return merged


def _flatten_observation_tensors(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        rows: dict[str, Any] = {}
        for key, item in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.update(_flatten_observation_tensors(item, child_prefix))
        return rows
    if isinstance(value, (list, tuple)) and not hasattr(value, "shape"):
        rows: dict[str, Any] = {}
        for index, item in enumerate(value):
            child_prefix = f"{prefix}.{index}" if prefix else str(index)
            rows.update(_flatten_observation_tensors(item, child_prefix))
        return rows
    array = _to_numpy(value)
    if array is None or not prefix:
        return {}
    return {prefix: array}


def _extract_rgbd_camera_frames(observation: dict[str, Any], cameras: list[str]) -> dict[str, dict[str, Any]]:
    flattened = observation if all(not isinstance(value, dict) for value in observation.values()) else _flatten_observation_tensors(observation)
    frames: dict[str, dict[str, Any]] = {}
    for camera in cameras:
        rgb = None
        depth = None
        for key, value in flattened.items():
            normalized = _normalized_obs_key(key)
            if _obs_key_matches_camera(normalized, camera) and _obs_key_is_rgb(normalized):
                rgb = _rgb_image_array(value)
                if rgb is not None:
                    break
        for key, value in flattened.items():
            normalized = _normalized_obs_key(key)
            if _obs_key_matches_camera(normalized, camera) and _obs_key_is_depth(normalized):
                depth = _depth_png16_array(value)
                if depth is not None:
                    break
        if rgb is not None and depth is not None:
            frames[str(camera)] = {"rgb": rgb, "depth": depth}
    return frames


def _extract_rgbd_camera_frames_from_scene(env: Any, cameras: list[str]) -> dict[str, dict[str, Any]]:
    """Read the latest Isaac Lab camera sensor outputs directly from the scene."""
    unwrapped = getattr(env, "unwrapped", env)
    scene = getattr(unwrapped, "scene", {})
    frames: dict[str, dict[str, Any]] = {}
    for camera in cameras:
        sensor = _scene_camera_sensor(scene, camera)
        if sensor is None:
            continue
        _refresh_scene_camera_sensor(sensor)
        data = getattr(sensor, "data", None)
        output = getattr(data, "output", None)
        if not isinstance(output, dict):
            continue
        rgb = None
        depth = None
        for key, value in output.items():
            normalized = _normalized_obs_key(key)
            if rgb is None and _obs_key_is_rgb(normalized):
                rgb = _rgb_image_array(value)
            if depth is None and _obs_key_is_depth(normalized):
                depth = _depth_png16_array(value)
        if rgb is not None and depth is not None:
            frames[str(camera)] = {"rgb": rgb, "depth": depth}
    return frames


def _scene_camera_sensor(scene: Any, camera: str) -> Any:
    normalized = _normalized_obs_key(camera)
    candidates = (
        f"{normalized}_cam",
        f"{normalized}_camera",
        normalized,
        f"Camera{str(camera).strip().capitalize()}",
    )
    for name in candidates:
        sensor = _scene_asset(scene, name)
        if sensor is not None:
            return sensor
    return None


def _refresh_scene_camera_sensor(sensor: Any) -> None:
    update = getattr(sensor, "update", None)
    if not callable(update):
        return
    for args, kwargs in (
        ((1.0 / 15.0,), {"force_recompute": True}),
        ((1.0 / 15.0,), {}),
        ((0.0,), {}),
        ((), {}),
    ):
        try:
            update(*args, **kwargs)
            return
        except TypeError:
            continue
        except Exception:  # noqa: BLE001 - camera extraction can fall back to existing output.
            return


def _merge_rgbd_camera_frames(
    preferred: dict[str, dict[str, Any]],
    fallback: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    frames = dict(fallback)
    frames.update(preferred)
    return frames


def _record_rgb_motion_samples(
    samples_by_camera: dict[str, list[dict[str, object]]],
    frames: dict[str, dict[str, Any]],
    *,
    frame_index: int,
    cameras: list[str],
) -> None:
    for camera in cameras:
        payload = frames.get(camera) or {}
        rgb = payload.get("rgb")
        sample = _rgb_motion_sample(rgb, frame_index=frame_index)
        if sample:
            samples_by_camera.setdefault(camera, []).append(sample)


def _rgb_motion_sample(rgb: Any, *, frame_index: int) -> dict[str, object] | None:
    array = _to_numpy(rgb)
    if array is None:
        return None
    import numpy as np

    arr = np.asarray(array)
    if arr.size == 0:
        return None
    rgb_arr = arr
    if rgb_arr.ndim == 4:
        rgb_arr = rgb_arr[0]
    if rgb_arr.ndim == 2:
        rgb_arr = np.repeat(rgb_arr[..., None], 3, axis=-1)
    if rgb_arr.ndim == 3 and rgb_arr.shape[-1] >= 3:
        gray = np.mean(rgb_arr[..., :3].astype(np.float32), axis=-1)
    else:
        gray = np.asarray(rgb_arr, dtype=np.float32).reshape(-1, 1)
    if gray.ndim == 2 and gray.size:
        y_indices = np.linspace(0, gray.shape[0] - 1, min(48, gray.shape[0])).astype(np.int64)
        x_indices = np.linspace(0, gray.shape[1] - 1, min(64, gray.shape[1])).astype(np.int64)
        thumb = gray[np.ix_(y_indices, x_indices)].astype(np.float32)
    else:
        thumb = gray.astype(np.float32)
    return {
        "frame_index": int(frame_index),
        "sha1": hashlib.sha1(arr.tobytes()).hexdigest(),
        "mean": float(np.mean(arr.astype(np.float32))),
        "motion_thumb": thumb,
    }


def _rgb_motion_audit(
    *,
    demo_name: str,
    actions: Any,
    samples_by_camera: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    import numpy as np

    action_array = np.asarray(actions, dtype=np.float32)
    action_delta = 0.0
    if action_array.size and action_array.ndim >= 2:
        action_delta = float(np.max(np.abs(action_array - action_array[0:1])))
    cameras: dict[str, dict[str, object]] = {}
    changed_camera_count = 0
    sampled_camera_count = 0
    for camera, samples in sorted(samples_by_camera.items()):
        hashes = [str(sample.get("sha1") or "") for sample in samples if sample.get("sha1")]
        unique_hashes = sorted(set(hashes))
        thumbs = [sample.get("motion_thumb") for sample in samples if sample.get("motion_thumb") is not None]
        motion_delta_mean_max = 0.0
        if len(thumbs) >= 2:
            try:
                first = np.asarray(thumbs[0], dtype=np.float32)
                deltas = []
                for thumb in thumbs[1:]:
                    current = np.asarray(thumb, dtype=np.float32)
                    if current.shape != first.shape:
                        continue
                    deltas.append(float(np.mean(np.abs(current - first))))
                motion_delta_mean_max = max(deltas) if deltas else 0.0
            except Exception:  # noqa: BLE001 - diagnostics should not abort the render path.
                motion_delta_mean_max = 0.0
        changed = len(unique_hashes) > 1 and motion_delta_mean_max >= 2.0
        if hashes:
            sampled_camera_count += 1
        if changed:
            changed_camera_count += 1
        cameras[str(camera)] = {
            "sample_count": len(samples),
            "unique_frame_hash_count": len(unique_hashes),
            "motion_delta_mean_max": float(motion_delta_mean_max),
            "changed": changed,
            "frame_indices": [int(sample.get("frame_index", 0)) for sample in samples],
            "means": [float(sample.get("mean", 0.0)) for sample in samples],
        }
    blocked = action_delta > 1e-4 and sampled_camera_count > 0 and changed_camera_count == 0
    return {
        "schema": "atr.lerobot.isaac_lab_mimic_rgbd.motion_audit.v1",
        "demo_name": str(demo_name),
        "status": "blocked" if blocked else "passed",
        "action_delta_max": action_delta,
        "sampled_camera_count": sampled_camera_count,
        "changed_camera_count": changed_camera_count,
        "cameras": cameras,
        "message": "RGB-D render produced identical sampled RGB frames while joint actions changed."
        if blocked
        else "RGB-D sampled motion check passed.",
    }


def _normalized_obs_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")


def _obs_key_matches_camera(normalized_key: str, camera: str) -> bool:
    normalized_camera = _normalized_obs_key(camera)
    return bool(normalized_camera and normalized_camera in normalized_key)


def _obs_key_is_rgb(normalized_key: str) -> bool:
    return any(token in normalized_key for token in ("rgb", "color", "colour")) and "depth" not in normalized_key


def _obs_key_is_depth(normalized_key: str) -> bool:
    return any(token in normalized_key for token in ("depth", "distance", "range"))


def _rgb_image_array(value: Any) -> Any | None:
    array = _to_numpy(value)
    if array is None:
        return None
    import numpy as np

    arr = np.asarray(array)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim == 3 and arr.shape[0] in {3, 4} and arr.shape[-1] not in {3, 4}:
        arr = np.moveaxis(arr, 0, -1)
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=-1)
    if arr.ndim != 3 or arr.shape[-1] < 3:
        return None
    arr = arr[..., :3]
    if np.issubdtype(arr.dtype, np.floating):
        finite = np.isfinite(arr)
        arr = np.where(finite, arr, 0.0)
        if float(np.nanmax(arr)) <= 1.0:
            arr = arr * 255.0
    return np.clip(np.rint(arr), 0, 255).astype(np.uint8)


def _depth_png16_array(value: Any) -> Any | None:
    array = _to_numpy(value)
    if array is None:
        return None
    import numpy as np

    arr = np.asarray(array)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim == 3 and arr.shape[-1] == 1:
        arr = arr[..., 0]
    elif arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim != 2:
        return None
    if np.issubdtype(arr.dtype, np.floating):
        finite = np.isfinite(arr)
        arr = np.where(finite, arr, 0.0)
        arr = arr * 1000.0
    return np.clip(np.rint(arr), 0, 65535).astype(np.uint16)


def _write_rgbd_frame_files(
    render_output_dir: Path,
    *,
    demo_name: str,
    frame_index: int,
    frames: dict[str, dict[str, Any]],
) -> dict[str, dict[str, str]]:
    from PIL import Image

    result: dict[str, dict[str, str]] = {}
    safe_demo = str(demo_name).replace("/", "_")
    for camera, payload in frames.items():
        camera_dir = render_output_dir / safe_demo / str(camera)
        camera_dir.mkdir(parents=True, exist_ok=True)
        rgb_path = camera_dir / f"frame_{int(frame_index):06d}_rgb.png"
        depth_path = camera_dir / f"frame_{int(frame_index):06d}_depth.png"
        Image.fromarray(payload["rgb"]).save(rgb_path)
        Image.fromarray(payload["depth"]).save(depth_path)
        result[str(camera)] = {
            "rgb_path": str(rgb_path),
            "depth_path": str(depth_path),
            "rgb_encoding": "png",
            "depth_encoding": "png16",
            "depth_scale_m_per_unit": 0.001,
        }
    return result


def _copy_hdf5_with_rgbd_paths(
    *,
    input_path: Path,
    output_path: Path,
    path_rows_by_demo: dict[str, dict[str, list[str]]],
    render_manifest_path: Path,
) -> None:
    import shutil

    import h5py
    import numpy as np

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.name}.tmp.{os.getpid()}")
    if tmp_path.exists():
        tmp_path.unlink()
    shutil.copy2(input_path, tmp_path)
    string_dtype = h5py.string_dtype(encoding="utf-8")
    with h5py.File(tmp_path, "a") as handle:
        handle.attrs["mimic_rgbd_rendered"] = 1
        handle.attrs["mimic_rgbd_render_manifest_path"] = str(render_manifest_path)
        data = handle.get("data")
        if data is not None:
            for demo_name, path_rows in path_rows_by_demo.items():
                if demo_name not in data:
                    continue
                demo = data[demo_name]
                obs = demo.require_group("obs")
                demo.attrs["mimic_rgbd_rendered"] = 1
                for dataset_name, values in path_rows.items():
                    if dataset_name in obs:
                        del obs[dataset_name]
                    obs.create_dataset(dataset_name, data=np.asarray(values, dtype=object), dtype=string_dtype)
    tmp_path.replace(output_path)


def _hdf5_int_attr(group: Any, key: str, fallback: int) -> int:
    try:
        value = group.attrs.get(key, fallback)
    except Exception:  # noqa: BLE001
        return int(fallback)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def _mimic_source_episode_index_by_demo(dataset_path: Path) -> dict[str, int]:
    manifest_path = Path(dataset_path).expanduser().parent / "successes.jsonl"
    mapping: dict[str, int] = {}
    try:
        lines = manifest_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return mapping
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        demo_name = str(row.get("generated_demo") or "").strip()
        if not demo_name:
            continue
        source_episode_index = row.get("source_episode_index")
        if source_episode_index is None:
            source_episode_index = row.get("episode_index")
        if source_episode_index is None:
            continue
        try:
            mapping[demo_name] = int(source_episode_index)
        except (TypeError, ValueError):
            continue
    return mapping


def _source_episode_index_for_generated_demo(
    group: Any,
    *,
    demo_name: str,
    source_episode_by_demo: dict[str, int],
) -> int:
    if demo_name in source_episode_by_demo:
        return int(source_episode_by_demo[demo_name])
    # Generated demo index is not a real LeRobot episode index. If the official
    # HDF5 lacks provenance, keep the safest single-source fallback instead of
    # letting contact-audit exclusions treat demo_4 as real episode 4.
    return _hdf5_int_attr(group, "source_episode_index", 0)


def _visualize_generated_dataset(
    *,
    dataset_path: Path,
    task_name: str,
    num_envs: int,
    external_callback: str,
    domain_randomization_profile: str,
    camera_mode: str,
    camera_width: int,
    camera_height: int,
    enable_cameras: bool,
    rendering_mode: str,
    visualizer: str,
    kit_args: str,
    fps: float,
    max_demos: int,
) -> dict[str, object]:
    if not task_name:
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_VISUAL_TASK_MISSING",
            "message": "Visual joint replay requires a visual task name.",
        }
    os.environ["ROBOTIS_OMX_DOMAIN_RANDOMIZATION_PROFILE"] = domain_randomization_profile
    os.environ["ROBOTIS_OMX_CAMERA_MODE"] = camera_mode
    os.environ["ROBOTIS_OMX_CAMERA_WIDTH"] = str(camera_width)
    os.environ["ROBOTIS_OMX_CAMERA_HEIGHT"] = str(camera_height)
    os.environ.setdefault("ROBOTIS_OMX_USE_FABRIC", "0")
    try:
        from isaaclab.app import AppLauncher

        app_launcher = AppLauncher(
            {
                "visualizer": [visualizer],
                "visualizer_explicit": True,
                "headless": False,
                "enable_cameras": bool(enable_cameras),
                "rendering_mode": rendering_mode,
                "kit_args": kit_args,
            }
        )
        simulation_app = app_launcher.app
    except Exception as exc:  # noqa: BLE001 - caller needs a user-visible blocker.
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_VISUAL_APP_LAUNCH_FAILED",
            "message": f"Could not launch Isaac Lab visualizer: {exc}",
        }
    try:
        _call_external_callback(external_callback)
        import gymnasium as gym
        import h5py
        import torch
        from isaaclab_tasks.utils import parse_env_cfg

        env_cfg = parse_env_cfg(task_name, num_envs=max(1, int(num_envs)), use_fabric=False)
        env = gym.make(task_name, cfg=env_cfg)
        env_num_envs = int(getattr(env.unwrapped, "num_envs", getattr(env, "num_envs", 1)))
        visual_camera_view = _apply_visual_camera_view(env)
        visual_camera_view_apply_count = 1 if bool(visual_camera_view.get("applied")) else 0
        replayed_frames = 0
        viewport_update_count = 0
        visual_render_method_last = ""
        initial_state_applied = 0
        initial_state_last: dict[str, bool] = {}
        initial_state_refresh_last: dict[str, bool] = {}
        visual_joint_frame_applied = 0
        visual_joint_frame_last: dict[str, bool] = {}
        visual_preplay_frame_applied = 0
        visual_preplay_last: dict[str, bool] = {}
        visual_frame_state_last: dict[str, bool] = {}
        visual_frame_state_applied = 0
        visual_readback_samples: list[dict[str, object]] = []
        guided_grasp_enabled = _env_flag("ROBOTIS_OMX_MIMIC_GUIDED_GRASP", default=True)
        guided_grasp_frames = 0
        guided_grasp_last: dict[str, object] = {}
        with h5py.File(dataset_path, "r") as handle:
            demos = handle.get("data")
            names = sorted(str(name) for name in demos.keys()) if demos is not None else []
            total_demo_count = len(names)
            if int(max_demos) > 0:
                names = names[: int(max_demos)]
            for name in names:
                env.reset()
                camera_after_reset = _apply_visual_camera_view(env)
                if bool(camera_after_reset.get("applied")):
                    visual_camera_view = camera_after_reset
                    visual_camera_view_apply_count += 1
                initial_state_last = _apply_hdf5_demo_initial_state(env, demos[name], apply_rigid_objects=True)
                if any(initial_state_last.values()):
                    initial_state_applied += 1
                    initial_state_refresh_last = _refresh_env_after_hdf5_initial_state(env)
                guided_grasp_state: dict[str, object] = {}
                actions = demos[name]["actions"][:]
                if len(actions) > 0:
                    first_action = _visual_action_tensor(torch, actions[0], env, env_num_envs)
                    visual_preplay_last = _apply_visual_joint_frame(env, first_action)
                    if any(visual_preplay_last.values()):
                        visual_preplay_frame_applied += 1
                readback_frame_indices = _visual_readback_frame_indices(len(actions))
                for frame_index, row in enumerate(actions):
                    if not simulation_app.is_running():
                        break
                    started = time.monotonic()
                    action = _visual_action_tensor(torch, row, env, env_num_envs)
                    visual_joint_frame_last = _apply_visual_joint_frame(env, action)
                    if any(visual_joint_frame_last.values()):
                        visual_joint_frame_applied += 1
                    env.step(action)
                    visual_frame_state_last = _apply_hdf5_demo_frame_state(
                        env,
                        demos[name],
                        frame_index=frame_index,
                        apply_rigid_objects=True,
                    )
                    if any(visual_frame_state_last.values()):
                        visual_frame_state_applied += 1
                        _refresh_env_after_hdf5_initial_state(env)
                    else:
                        visual_joint_frame_last = _apply_visual_joint_frame(env, action)
                    if frame_index in readback_frame_indices:
                        sample = _visual_joint_readback_sample(
                            env,
                            action,
                            demo_name=name,
                            frame_index=frame_index,
                            phase="after_env_step",
                        )
                        if sample:
                            visual_readback_samples.append(sample)
                    if guided_grasp_enabled and not any(visual_frame_state_last.values()):
                        guided_grasp_last = _apply_guided_grasp_follow(
                            env,
                            demos[name],
                            frame_index=frame_index,
                            state=guided_grasp_state,
                        )
                        if bool(guided_grasp_last.get("wrote_pose")):
                            guided_grasp_frames += 1
                    render_method = _pump_visual_viewport(env, simulation_app)
                    if render_method:
                        visual_render_method_last = render_method
                        viewport_update_count += 1
                    replayed_frames += 1
                    if fps > 0:
                        delay = max(0.0, (1.0 / fps) - (time.monotonic() - started))
                        if delay:
                            time.sleep(delay)
                if not simulation_app.is_running():
                    break
        env.close()
        return {
            "ok": True,
            "status": "completed",
            "task_name": task_name,
            "num_envs": int(num_envs),
            "dataset_path": str(dataset_path),
            "visual_demo_count": int(len(names)),
            "visual_total_demo_count": int(total_demo_count),
            "visual_max_demos": int(max_demos),
            "replayed_frames": int(replayed_frames),
            "viewport_update_count": int(viewport_update_count),
            "visual_render_method_last": visual_render_method_last,
            "visual_camera_view_applied": bool(visual_camera_view.get("applied")),
            "visual_camera_view_apply_count": int(visual_camera_view_apply_count),
            "visual_camera_view": {
                "eye": list(visual_camera_view.get("eye") or []),
                "target": list(visual_camera_view.get("target") or []),
                "method": str(visual_camera_view.get("method") or ""),
            },
            "initial_state_applied_count": int(initial_state_applied),
            "initial_state_last": initial_state_last,
            "initial_state_refresh_last": initial_state_refresh_last,
            "visual_preplay_frame_applied_count": int(visual_preplay_frame_applied),
            "visual_preplay_last": visual_preplay_last,
            "visual_joint_frame_applied_count": int(visual_joint_frame_applied),
            "visual_joint_frame_last": visual_joint_frame_last,
            "visual_frame_state_applied_count": int(visual_frame_state_applied),
            "visual_frame_state_last": visual_frame_state_last,
            "visual_readback_sample_count": int(len(visual_readback_samples)),
            "visual_readback_samples": visual_readback_samples,
            "visual_readback_target_error_max": _visual_readback_error_max(visual_readback_samples),
            "guided_grasp_enabled": bool(guided_grasp_enabled),
            "guided_grasp_frames": int(guided_grasp_frames),
            "guided_grasp_last": guided_grasp_last,
            "camera_mode": camera_mode,
            "enable_cameras": bool(enable_cameras),
            "visualizer": visualizer,
        }
    except Exception as exc:  # noqa: BLE001 - preserve the failed visual reason in the runner summary.
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "JOINT_REPLAY_VISUAL_REPLAY_FAILED",
            "message": f"Could not replay generated joint trajectory in Isaac Lab: {exc}",
            "dataset_path": str(dataset_path),
            "task_name": task_name,
        }


def _visual_action_tensor(torch_module: Any, row: Any, env: Any, env_num_envs: int) -> Any:
    action = torch_module.as_tensor(row, dtype=torch_module.float32, device=env.unwrapped.device).reshape(1, -1)
    if action.shape[0] != env_num_envs:
        action = action.repeat(env_num_envs, 1)
    return action


def _apply_visual_joint_frame(env: Any, action: Any) -> dict[str, bool]:
    """Write the replay action row directly to the visual robot joint pose."""
    applied = {
        "robot_joint_state": False,
        "robot_joint_target": False,
        "robot_write_data": False,
    }
    unwrapped = getattr(env, "unwrapped", env)
    scene = getattr(unwrapped, "scene", {})
    robot = _scene_asset(scene, "robot")
    if robot is None or action is None:
        return applied

    joint_pos = action
    if len(getattr(joint_pos, "shape", ())) == 1:
        joint_pos = joint_pos.reshape(1, -1)
    joint_pos = _repeat_for_envs(joint_pos, _env_num_envs(env))
    try:
        import torch

        joint_vel = torch.zeros_like(joint_pos)
    except Exception:  # noqa: BLE001 - visual replay should keep running without torch helpers in tests.
        joint_vel = None

    if joint_vel is not None:
        try:
            robot.write_joint_state_to_sim(joint_pos, joint_vel)
            applied["robot_joint_state"] = True
        except Exception:  # noqa: BLE001 - not every Lab asset wrapper exposes this writer.
            applied["robot_joint_state"] = False
    if _call_asset_writer(robot, "set_joint_position_target", joint_pos):
        applied["robot_joint_target"] = True
    flush = getattr(robot, "write_data_to_sim", None)
    if callable(flush):
        try:
            flush()
            applied["robot_write_data"] = True
        except Exception:  # noqa: BLE001 - flushing is best-effort for visual replay.
            applied["robot_write_data"] = False
    return applied


def _apply_visual_camera_view(env: Any) -> dict[str, object]:
    """Apply the task viewer camera to the Kit viewport and record what happened."""
    eye, target = _visual_camera_eye_target(env)
    result: dict[str, object] = {
        "applied": False,
        "method": "",
        "eye": [float(value) for value in eye],
        "target": [float(value) for value in target],
    }
    unwrapped = getattr(env, "unwrapped", env)
    controller = getattr(unwrapped, "viewport_camera_controller", None)
    update_view_location = getattr(controller, "update_view_location", None)
    if callable(update_view_location):
        try:
            update_view_location()
            result["applied"] = True
            result["method"] = "viewport_camera_controller.update_view_location"
            return result
        except Exception as exc:  # noqa: BLE001 - fallback to direct sim camera view.
            result["error"] = f"{exc.__class__.__name__}: {exc}"
    sim = getattr(unwrapped, "sim", None)
    set_camera_view = getattr(sim, "set_camera_view", None)
    if callable(set_camera_view):
        try:
            set_camera_view(eye=tuple(eye), target=tuple(target))
            result["applied"] = True
            result["method"] = "sim.set_camera_view"
        except Exception as exc:  # noqa: BLE001 - diagnostics only; visual replay can continue.
            result["error"] = f"{exc.__class__.__name__}: {exc}"
    return result


def _visual_camera_eye_target(env: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    unwrapped = getattr(env, "unwrapped", env)
    cfg = getattr(unwrapped, "cfg", None)
    viewer = getattr(cfg, "viewer", None)
    eye = getattr(viewer, "eye", (0.9, -1.2, 0.8))
    target = getattr(viewer, "lookat", getattr(viewer, "target", (0.315, 0.22, 0.02)))
    return _triple_float_tuple(eye, (0.9, -1.2, 0.8)), _triple_float_tuple(target, (0.315, 0.22, 0.02))


def _triple_float_tuple(value: Any, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    try:
        parts = list(value)
    except TypeError:
        return fallback
    if len(parts) != 3:
        return fallback
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except (TypeError, ValueError):
        return fallback


def _pump_visual_viewport(env: Any, simulation_app: Any) -> str:
    """Render through Isaac Lab's SimulationContext when available, else pump Kit."""
    unwrapped = getattr(env, "unwrapped", env)
    sim = getattr(unwrapped, "sim", None)
    render = getattr(sim, "render", None)
    if callable(render):
        try:
            render()
            return "sim.render"
        except Exception:  # noqa: BLE001 - fallback keeps the visual runner alive.
            pass
    update_viewport = getattr(simulation_app, "update", None)
    if callable(update_viewport):
        try:
            update_viewport()
            return "simulation_app.update"
        except Exception:  # noqa: BLE001 - diagnostics only.
            return ""
    return ""


def _visual_readback_frame_indices(frame_count: int) -> set[int]:
    if int(frame_count) <= 0:
        return set()
    last = int(frame_count) - 1
    return {0, max(0, int(frame_count) // 2), last}


def _visual_joint_readback_sample(
    env: Any,
    action: Any,
    *,
    demo_name: str,
    frame_index: int,
    phase: str,
) -> dict[str, object] | None:
    unwrapped = getattr(env, "unwrapped", env)
    scene = getattr(unwrapped, "scene", {})
    robot = _scene_asset(scene, "robot")
    if robot is None:
        return None
    data = getattr(robot, "data", None)
    joint_pos = _first_env_vector(getattr(data, "joint_pos", None))
    target = _first_env_vector(action)
    if not joint_pos and not target:
        return None
    sample: dict[str, object] = {
        "demo_name": str(demo_name),
        "frame_index": int(frame_index),
        "phase": str(phase),
        "target": target,
        "joint_pos": joint_pos,
        "target_error_max": _vector_error_max(joint_pos, target),
    }
    action_manager = getattr(unwrapped, "action_manager", None)
    raw_actions = _first_env_vector(getattr(action_manager, "raw_actions", None))
    processed_actions = _first_env_vector(getattr(action_manager, "processed_actions", None))
    if raw_actions:
        sample["action_manager_raw"] = raw_actions
    if processed_actions:
        sample["action_manager_processed"] = processed_actions
    return sample


def _visual_readback_error_max(samples: list[dict[str, object]]) -> float | None:
    errors = [sample.get("target_error_max") for sample in samples]
    numeric = [float(value) for value in errors if isinstance(value, (int, float))]
    return max(numeric) if numeric else None


def _first_env_vector(value: Any) -> list[float]:
    array = _to_numpy(value)
    if array is None:
        return []
    try:
        import numpy as np

        numeric = np.asarray(array, dtype=np.float64)
        if numeric.ndim == 0:
            return [float(numeric)]
        if numeric.ndim >= 2:
            numeric = numeric[0]
        return [float(item) for item in numeric.reshape(-1)]
    except Exception:  # noqa: BLE001 - diagnostics must not interrupt visual replay.
        return []


def _vector_error_max(left: list[float], right: list[float]) -> float | None:
    if not left or not right:
        return None
    count = min(len(left), len(right))
    if count <= 0:
        return None
    try:
        import numpy as np

        return float(np.max(np.abs(np.asarray(left[:count], dtype=np.float64) - np.asarray(right[:count], dtype=np.float64))))
    except Exception:  # noqa: BLE001 - diagnostics must not interrupt visual replay.
        return None


def _apply_hdf5_demo_initial_state(env: Any, demo: Any, *, apply_rigid_objects: bool = False) -> dict[str, bool]:
    """Apply robomimic-style HDF5 initial_state to the live Isaac Lab env."""
    applied = {
        "robot_root_pose": False,
        "robot_root_velocity": False,
        "robot_joint_state": False,
        "robot_joint_target": False,
        "red_cube_root_pose": False,
        "red_cube_root_velocity": False,
    }
    initial_state = demo.get("initial_state") if hasattr(demo, "get") else None
    if initial_state is None:
        return applied

    unwrapped = getattr(env, "unwrapped", env)
    scene = getattr(unwrapped, "scene", {})
    robot = _scene_asset(scene, "robot")
    cube = _scene_asset(scene, "red_cube") if apply_rigid_objects else None

    robot_state = _nested_group(initial_state, "articulation", "robot")
    cube_state = _nested_group(initial_state, "rigid_object", "red_cube")
    joint_pos = _initial_state_tensor(env, robot_state, "joint_position")
    joint_vel = _initial_state_tensor(env, robot_state, "joint_velocity")
    if robot is not None:
        if _call_asset_writer(robot, "write_root_pose_to_sim", _initial_state_tensor(env, robot_state, "root_pose")):
            applied["robot_root_pose"] = True
        if _call_asset_writer(robot, "write_root_velocity_to_sim", _initial_state_tensor(env, robot_state, "root_velocity")):
            applied["robot_root_velocity"] = True
        if joint_pos is not None:
            if joint_vel is None:
                import torch

                joint_vel = torch.as_tensor([[0.0] * int(joint_pos.shape[1])], dtype=torch.float32, device=getattr(unwrapped, "device", None))
                joint_vel = _repeat_for_envs(joint_vel, _env_num_envs(env))
            try:
                robot.write_joint_state_to_sim(joint_pos, joint_vel)
                applied["robot_joint_state"] = True
            except Exception:  # noqa: BLE001 - not all test/runtime articulation wrappers expose this exact writer.
                applied["robot_joint_state"] = False
            if _call_asset_writer(robot, "set_joint_position_target", joint_pos):
                applied["robot_joint_target"] = True
    if cube is not None:
        should_flush_cube = False
        if _call_asset_writer(cube, "write_root_pose_to_sim", _initial_state_tensor(env, cube_state, "root_pose")):
            applied["red_cube_root_pose"] = True
            should_flush_cube = True
        if _call_asset_writer(cube, "write_root_velocity_to_sim", _initial_state_tensor(env, cube_state, "root_velocity")):
            applied["red_cube_root_velocity"] = True
            should_flush_cube = True
        flush = getattr(cube, "write_data_to_sim", None)
        if should_flush_cube and callable(flush):
            try:
                flush()
            except Exception:  # noqa: BLE001 - initial-state replay should keep running on wrapper differences.
                pass
    return applied


def _apply_hdf5_demo_frame_state(
    env: Any,
    demo: Any,
    *,
    frame_index: int,
    apply_rigid_objects: bool = False,
) -> dict[str, bool]:
    """Apply one recorded HDF5 state frame to the live Isaac Lab env."""
    applied = {
        "robot_root_pose": False,
        "robot_root_velocity": False,
        "robot_joint_state": False,
        "robot_joint_target": False,
        "red_cube_root_pose": False,
        "red_cube_root_velocity": False,
    }
    states = demo.get("states") if hasattr(demo, "get") else None
    if states is None or not hasattr(states, "get"):
        return applied

    unwrapped = getattr(env, "unwrapped", env)
    scene = getattr(unwrapped, "scene", {})
    robot = _scene_asset(scene, "robot")
    cube = _scene_asset(scene, "red_cube") if apply_rigid_objects else None

    robot_state = _nested_group(states, "articulation", "robot")
    cube_state = _nested_group(states, "rigid_object", "red_cube")
    joint_pos = _frame_state_tensor(env, robot_state, "joint_position", frame_index=frame_index)
    joint_vel = _frame_state_tensor(env, robot_state, "joint_velocity", frame_index=frame_index)
    if robot is not None:
        if _call_asset_writer(robot, "write_root_pose_to_sim", _frame_state_tensor(env, robot_state, "root_pose", frame_index=frame_index)):
            applied["robot_root_pose"] = True
        if _call_asset_writer(
            robot,
            "write_root_velocity_to_sim",
            _frame_state_tensor(env, robot_state, "root_velocity", frame_index=frame_index),
        ):
            applied["robot_root_velocity"] = True
        if joint_pos is not None:
            if joint_vel is None:
                import torch

                joint_vel = torch.as_tensor([[0.0] * int(joint_pos.shape[1])], dtype=torch.float32, device=getattr(unwrapped, "device", None))
                joint_vel = _repeat_for_envs(joint_vel, _env_num_envs(env))
            try:
                robot.write_joint_state_to_sim(joint_pos, joint_vel)
                applied["robot_joint_state"] = True
            except Exception:  # noqa: BLE001 - not all Lab wrappers expose this writer.
                applied["robot_joint_state"] = False
            if _call_asset_writer(robot, "set_joint_position_target", joint_pos):
                applied["robot_joint_target"] = True
            flush = getattr(robot, "write_data_to_sim", None)
            if callable(flush):
                try:
                    flush()
                except Exception:  # noqa: BLE001 - frame replay should continue across wrapper differences.
                    pass
    if cube is not None:
        should_flush_cube = False
        if _call_asset_writer(cube, "write_root_pose_to_sim", _frame_state_tensor(env, cube_state, "root_pose", frame_index=frame_index)):
            applied["red_cube_root_pose"] = True
            should_flush_cube = True
        if _call_asset_writer(
            cube,
            "write_root_velocity_to_sim",
            _frame_state_tensor(env, cube_state, "root_velocity", frame_index=frame_index),
        ):
            applied["red_cube_root_velocity"] = True
            should_flush_cube = True
        flush = getattr(cube, "write_data_to_sim", None)
        if should_flush_cube and callable(flush):
            try:
                flush()
            except Exception:  # noqa: BLE001 - frame replay should keep running on wrapper differences.
                pass
    return applied


def _refresh_env_after_hdf5_initial_state(env: Any) -> dict[str, bool]:
    """Synchronize Isaac Lab buffers after manually replaying a demo initial_state."""
    refreshed = {
        "scene_write_data_to_sim": False,
        "sim_forward": False,
        "render_context_reset_transform_cadence": False,
        "scene_update": False,
        "observation_compute": False,
    }
    unwrapped = getattr(env, "unwrapped", env)
    scene = getattr(unwrapped, "scene", None)
    write_scene = getattr(scene, "write_data_to_sim", None)
    if callable(write_scene):
        try:
            write_scene()
            refreshed["scene_write_data_to_sim"] = True
        except Exception:  # noqa: BLE001 - replay should continue across Lab wrapper differences.
            refreshed["scene_write_data_to_sim"] = False

    sim = getattr(unwrapped, "sim", None)
    forward = getattr(sim, "forward", None)
    if callable(forward):
        try:
            forward()
            refreshed["sim_forward"] = True
        except Exception:  # noqa: BLE001
            refreshed["sim_forward"] = False

    render_context = getattr(sim, "render_context", None)
    reset_transform_cadence = getattr(render_context, "reset_transform_cadence", None)
    if callable(reset_transform_cadence):
        try:
            reset_transform_cadence()
            refreshed["render_context_reset_transform_cadence"] = True
        except Exception:  # noqa: BLE001 - a stale transform cadence should not abort replay.
            refreshed["render_context_reset_transform_cadence"] = False

    update_scene = getattr(scene, "update", None)
    if callable(update_scene):
        try:
            update_scene(0.0)
            refreshed["scene_update"] = True
        except Exception:  # noqa: BLE001
            refreshed["scene_update"] = False

    observation_manager = getattr(unwrapped, "observation_manager", None)
    compute = getattr(observation_manager, "compute", None)
    if callable(compute):
        try:
            obs_buf = compute(update_history=True)
            setattr(unwrapped, "obs_buf", obs_buf)
            try:
                setattr(env, "obs_buf", obs_buf)
            except Exception:  # noqa: BLE001 - gym wrappers may disallow direct assignment.
                pass
            refreshed["observation_compute"] = True
        except Exception:  # noqa: BLE001
            refreshed["observation_compute"] = False
    return refreshed


def _hdf5_json_attr(group: Any, key: str) -> dict[str, object]:
    try:
        raw = group.attrs.get(key)
    except Exception:  # noqa: BLE001 - HDF5 attrs are optional diagnostics.
        return {}
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        value = json.loads(str(raw))
    except Exception:  # noqa: BLE001
        return {}
    return value if isinstance(value, dict) else {}


def _copy_domain_randomization_attrs_to_lab_output(
    source_path: Path,
    output_path: Path,
    success_rows: list[dict[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {"copied": 0, "missing": 0}
    if not success_rows:
        return result
    try:
        import h5py

        with h5py.File(source_path, "r") as source_handle, h5py.File(output_path, "a") as output_handle:
            source_data = source_handle.get("data")
            output_data = output_handle.get("data")
            for row in success_rows:
                source_demo = str(row.get("source_demo") or "")
                generated_demo = str(row.get("generated_demo") or "")
                if source_data is None or output_data is None or source_demo not in source_data or generated_demo not in output_data:
                    result["missing"] = int(result["missing"]) + 1
                    continue
                domain_randomization = row.get("domain_randomization")
                if not isinstance(domain_randomization, dict) or not domain_randomization:
                    domain_randomization = _hdf5_json_attr(source_data[source_demo], "domain_randomization")
                if not isinstance(domain_randomization, dict) or not domain_randomization:
                    result["missing"] = int(result["missing"]) + 1
                    continue
                output_data[generated_demo].attrs["domain_randomization"] = json.dumps(
                    domain_randomization,
                    sort_keys=True,
                )
                result["copied"] = int(result["copied"]) + 1
    except Exception as exc:  # noqa: BLE001 - metadata copy should not invalidate generated trajectories.
        result["error"] = str(exc)
    return result


def _apply_guided_grasp_follow(env: Any, demo: Any, *, frame_index: int, state: dict[str, object]) -> dict[str, object]:
    """Attach the cube to the finger center while Mimic grasp is active."""
    result: dict[str, object] = {"held": False, "wrote_pose": False, "frame_index": int(frame_index)}
    if _hdf5_signal_at(demo, "place", frame_index):
        state["held"] = False
        return result
    if not (_hdf5_signal_at(demo, "grasp", frame_index) or bool(state.get("held"))):
        return result

    unwrapped = getattr(env, "unwrapped", env)
    scene = getattr(unwrapped, "scene", {})
    cube = _scene_asset(scene, "red_cube")
    center = _finger_center_w(scene)
    if cube is None or center is None:
        state["held"] = bool(state.get("held"))
        result["held"] = bool(state.get("held"))
        return result

    import numpy as np
    import torch

    offset = np.asarray(_guided_grasp_offset(), dtype=np.float32)
    pos = np.asarray(center, dtype=np.float32).reshape(3) + offset
    pose = np.asarray([[pos[0], pos[1], pos[2], 0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
    tensor = torch.as_tensor(pose, dtype=torch.float32, device=getattr(unwrapped, "device", None))
    try:
        cube.write_root_pose_to_sim(tensor)
        _sync_guided_cube_usd_prim(cube, pos)
        flush = getattr(cube, "write_data_to_sim", None)
        if callable(flush):
            flush()
    except Exception:  # noqa: BLE001 - report failure but keep replay running.
        result["held"] = bool(state.get("held"))
        return result
    state["held"] = True
    result.update({"held": True, "wrote_pose": True, "cube_pos": [float(v) for v in pos]})
    return result


def _sync_guided_cube_usd_prim(cube: Any, pos: Any) -> bool:
    try:
        from pxr import Gf, UsdGeom
    except Exception:  # noqa: BLE001 - unit tests and headless minimal installs may not have pxr loaded.
        return False
    prims = getattr(cube, "_prims", None)
    if prims is None:
        cfg = getattr(cube, "cfg", None)
        prim_path = str(getattr(cfg, "prim_path", "") or "")
        if not prim_path:
            return False
        try:
            import isaaclab.sim as sim_utils

            prims = sim_utils.find_matching_prims(prim_path)
        except Exception:  # noqa: BLE001
            prims = None
        if not prims:
            prims = _find_usd_prims_by_regex(prim_path)
    wrote = False
    xyz = [float(pos[0]), float(pos[1]), float(pos[2])]
    for prim in list(prims or []):
        try:
            xform = UsdGeom.Xformable(prim)
            translate_op = next((op for op in xform.GetOrderedXformOps() if "translate" in op.GetOpName()), None)
            if translate_op is None:
                translate_op = xform.AddTranslateOp()
            translate_op.Set(Gf.Vec3d(*xyz))
            wrote = True
        except Exception:  # noqa: BLE001
            continue
    return wrote


def _find_usd_prims_by_regex(prim_path_pattern: str) -> list[Any]:
    import re

    try:
        import omni.usd
    except Exception:  # noqa: BLE001
        return []
    try:
        stage = omni.usd.get_context().get_stage()
        pattern = re.compile(str(prim_path_pattern))
        return [prim for prim in stage.Traverse() if pattern.fullmatch(str(prim.GetPath()))]
    except Exception:  # noqa: BLE001
        return []


def _hdf5_signal_at(demo: Any, name: str, frame_index: int) -> bool:
    signals = _nested_group(demo, "obs", "datagen_info", "subtask_term_signals")
    if signals is None or not hasattr(signals, "get"):
        return False
    dataset = signals.get(name)
    if dataset is None:
        return False
    try:
        index = max(0, min(int(frame_index), int(dataset.shape[0]) - 1))
        return bool(dataset[index].reshape(-1)[0])
    except Exception:  # noqa: BLE001
        return False


def _finger_center_w(scene: Any) -> Any:
    import numpy as np

    robot = _scene_asset(scene, "robot")
    if robot is None:
        return None
    names = list(getattr(robot, "body_names", []) or [])
    data = getattr(robot, "data", None)
    positions = None
    for attr in ("body_pos_w", "body_link_pos_w", "body_com_pos_w"):
        positions = _to_numpy(getattr(data, attr, None))
        if positions is not None and positions.ndim >= 3 and positions.shape[1] >= 2:
            break
    if positions is None or positions.ndim < 3:
        return None
    indices = []
    for name in ("link6", "link7"):
        try:
            indices.append(names.index(name))
        except ValueError:
            pass
    if len(indices) < 2:
        indices = [positions.shape[1] - 2, positions.shape[1] - 1]
    return np.mean(positions[0, indices, :3], axis=0)


def _to_numpy(value: Any) -> Any:
    if value is None:
        return None
    payload = getattr(value, "array", None)
    if payload is not None:
        value = payload
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    try:
        import numpy as np

        return np.asarray(value)
    except Exception:  # noqa: BLE001
        return None


def _guided_grasp_offset() -> tuple[float, float, float]:
    raw = os.environ.get("ROBOTIS_OMX_MIMIC_GUIDED_GRASP_OFFSET", "").strip()
    if not raw:
        return (0.0, 0.0, 0.0)
    parts = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    if len(parts) != 3:
        return (0.0, 0.0, 0.0)
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return (0.0, 0.0, 0.0)


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return bool(default)
    return value not in {"0", "false", "off", "disabled", "no"}


def _nested_group(group: Any, *names: str) -> Any:
    current = group
    for name in names:
        if current is None or not hasattr(current, "get"):
            return None
        current = current.get(name)
    return current


def _scene_asset(scene: Any, name: str) -> Any:
    try:
        return scene[name]
    except Exception:  # noqa: BLE001 - scene can be a dict-like Isaac Lab object.
        return None


def _env_num_envs(env: Any) -> int:
    unwrapped = getattr(env, "unwrapped", env)
    return max(1, int(getattr(unwrapped, "num_envs", getattr(env, "num_envs", 1)) or 1))


def _initial_state_tensor(env: Any, group: Any, dataset_name: str) -> Any:
    if group is None or not hasattr(group, "get"):
        return None
    dataset = group.get(dataset_name)
    if dataset is None:
        return None
    import torch

    value = dataset[:]
    tensor = torch.as_tensor(value[:1], dtype=torch.float32, device=getattr(getattr(env, "unwrapped", env), "device", None))
    return _repeat_for_envs(tensor, _env_num_envs(env))


def _frame_state_tensor(env: Any, group: Any, dataset_name: str, *, frame_index: int) -> Any:
    if group is None or not hasattr(group, "get"):
        return None
    dataset = group.get(dataset_name)
    if dataset is None:
        return None
    import numpy as np
    import torch

    value = np.asarray(dataset[:])
    if value.size == 0:
        return None
    if value.ndim == 0:
        value = value.reshape(1, 1)
    elif value.ndim == 1:
        value = value.reshape(1, -1)
    index = max(0, min(int(frame_index), int(value.shape[0]) - 1))
    tensor = torch.as_tensor(value[index : index + 1], dtype=torch.float32, device=getattr(getattr(env, "unwrapped", env), "device", None))
    return _repeat_for_envs(tensor, _env_num_envs(env))


def _repeat_for_envs(tensor: Any, num_envs: int) -> Any:
    if int(num_envs) <= 1 or len(getattr(tensor, "shape", ())) == 0 or int(tensor.shape[0]) == int(num_envs):
        return tensor
    if int(tensor.shape[0]) == 1:
        return tensor.repeat(int(num_envs), 1)
    return tensor


def _call_asset_writer(asset: Any, method_name: str, value: Any) -> bool:
    if value is None or asset is None:
        return False
    method = getattr(asset, method_name, None)
    if not callable(method):
        return False
    try:
        method(value)
    except Exception:  # noqa: BLE001 - initial-state application should be reported but not crash visual replay.
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
