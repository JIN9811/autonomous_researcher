#!/usr/bin/env python3
"""Replay one Isaac Lab HDF5 demo and print physical task signals."""

from __future__ import annotations

import argparse
import json
from typing import Any

from isaaclab.app import AppLauncher
from isaaclab.utils.string import list_intersection, string_to_callable


parser = argparse.ArgumentParser(description="Debug Robotis OMX Isaac Lab replay signals.")
parser.add_argument("--task", required=True)
parser.add_argument("--input_file", required=True)
parser.add_argument("--episode", default="demo_000000")
parser.add_argument("--external_callback", default=None)
AppLauncher.add_app_launcher_args(parser)
args_cli, remaining_args = parser.parse_known_args()

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

remaining_args_env_registration = None
if args_cli.external_callback:
    callback = string_to_callable(args_cli.external_callback, separator=".")
    remaining_args_env_registration = callback()

unrecognized_args = list_intersection(remaining_args, remaining_args_env_registration)
if unrecognized_args:
    parser.error(f"unrecognized arguments: {' '.join(unrecognized_args)}")


import gymnasium as gym
import torch

import isaaclab_mimic.envs  # noqa: F401
import isaaclab_tasks  # noqa: F401
from isaaclab.envs import ManagerBasedRLMimicEnv
from isaaclab.utils.datasets import HDF5DatasetFileHandler
from isaaclab_tasks.utils.parse_cfg import parse_env_cfg


def _to_list(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    return value


def main() -> int:
    handler = HDF5DatasetFileHandler()
    handler.open(args_cli.input_file)
    env_name = args_cli.task.split(":")[-1]
    env_cfg = parse_env_cfg(env_name, device=args_cli.device, num_envs=1)
    env_cfg.env_name = env_name
    success_term = env_cfg.terminations.success
    env_cfg.terminations = None
    env_cfg.recorders = None

    env: ManagerBasedRLMimicEnv = gym.make(args_cli.task, cfg=env_cfg).unwrapped
    episode = handler.load_episode(args_cli.episode, env.device)
    env.reset()
    env.sim.reset()
    env.reset_to(episode.data["initial_state"], None, is_relative=True)

    signal_max: dict[str, float] = {}
    signal_last: dict[str, float] = {}
    actions = episode.data["actions"]
    with torch.inference_mode():
        for action_index, action in enumerate(actions):
            action_tensor = torch.Tensor(action).reshape([1, action.shape[0]])
            env.step(action_tensor)
            terms = env.get_subtask_term_signals()
            for name, tensor in terms.items():
                value = float(torch.as_tensor(tensor).reshape(-1)[0])
                signal_last[name] = value
                signal_max[name] = max(signal_max.get(name, 0.0), value)

    success = bool(success_term.func(env, **success_term.params)[0])
    cube_pos = env.scene["red_cube"].data.root_pos_w[:, :3][0]
    joint_pos = env.scene["robot"].data.joint_pos[0]
    payload = {
        "episode": args_cli.episode,
        "success": success,
        "cube_pos_w": _to_list(cube_pos),
        "joint_pos": _to_list(joint_pos),
        "signal_max": signal_max,
        "signal_last": signal_last,
        "frame_count": int(len(actions)),
    }
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    env.close()
    return 0 if success else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        simulation_app.close()
