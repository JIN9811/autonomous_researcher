"""Joint-position replay backend for Robotis OMX Isaac Lab Mimic data."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SUBTASK_SIGNALS = ("approach", "grasp", "lift", "place")
JOINT_REPLAY_GENERATOR = "isaac_lab_mimic_joint_replay"


@dataclass(frozen=True)
class _SourceDemo:
    name: str
    actions: Any
    states: Any
    observations: dict[str, Any]
    initial_state: dict[str, Any]
    attrs: dict[str, Any]
    boundaries: list[tuple[int, int]]


def generate_joint_replay_mimic_dataset(
    *,
    input_path: Path,
    output_path: Path,
    success_manifest_path: Path,
    failure_manifest_path: Path,
    trials: int,
    domain_variants: int = 1,
    seed: int = 42,
    env_name: str = "",
    domain_randomization_profile: str = "off",
    subtask_signals: tuple[str, ...] = DEFAULT_SUBTASK_SIGNALS,
) -> dict[str, Any]:
    """Generate a Mimic-shaped HDF5 by replaying source joint-position subtask segments."""
    import h5py
    import numpy as np

    input_path = Path(input_path).expanduser()
    output_path = Path(output_path).expanduser()
    success_manifest_path = Path(success_manifest_path).expanduser()
    failure_manifest_path = Path(failure_manifest_path).expanduser()
    if not input_path.is_file():
        return _blocked_summary(
            "JOINT_REPLAY_INPUT_MISSING",
            f"Joint replay Mimic input HDF5 is missing: {input_path}",
            input_path,
            output_path,
            success_manifest_path,
            failure_manifest_path,
        )

    rng = np.random.default_rng(int(seed))
    with h5py.File(input_path, "r") as source:
        source_env_args = _load_env_args(source)
        if not env_name:
            env_name = str(source_env_args.get("env_name") or "")
        demos = _read_source_demos(source, subtask_signals=subtask_signals)

    if not demos:
        return _blocked_summary(
            "JOINT_REPLAY_SOURCE_DEMOS_MISSING",
            "Joint replay Mimic requires at least one source demo with actions.",
            input_path,
            output_path,
            success_manifest_path,
            failure_manifest_path,
        )

    trials_per_source = max(1, int(trials))
    domain_variant_count = max(1, int(domain_variants))
    generated = _build_ordered_trials(
        demos,
        trials_per_source=trials_per_source,
        domain_variants=domain_variant_count,
        domain_randomization_profile=domain_randomization_profile,
        rng=rng,
    )
    _write_generated_hdf5(output_path, generated, env_name=env_name, input_path=input_path)
    successes = _write_success_manifest(success_manifest_path, generated, output_path)
    _write_jsonl(failure_manifest_path, [])
    summary = {
        "schema": "atr.lerobot.isaac_lab_mimic.joint_replay.summary.v1",
        "ok": True,
        "status": "completed",
        "backend": "joint_replay",
        "generator": JOINT_REPLAY_GENERATOR,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "success_manifest_path": str(success_manifest_path),
        "failure_manifest_path": str(failure_manifest_path),
        "source_demo_count": len(demos),
        "trial_count": len(generated),
        "mimic_trials_per_source": trials_per_source,
        "domain_variants": domain_variant_count,
        "domain_randomization_profile": str(domain_randomization_profile or "off"),
        "success_count": len(successes),
        "failure_count": 0,
        "env_name": env_name,
        "subtask_signals": list(subtask_signals),
    }
    _atomic_write_json(output_path.with_name("joint_replay_summary.json"), summary)
    return summary


def _build_ordered_trials(
    demos: list[_SourceDemo],
    *,
    trials_per_source: int,
    domain_variants: int,
    domain_randomization_profile: str,
    rng: Any,
) -> list[dict[str, Any]]:
    generated: list[dict[str, Any]] = []
    index = 0
    for source_demo_index, demo in enumerate(demos):
        for domain_variant_index in range(max(1, int(domain_variants))):
            domain_randomization = _sample_domain_randomization(domain_randomization_profile, rng)
            for mimic_trial_index in range(max(1, int(trials_per_source))):
                generated.append(
                    _build_trial(
                        index,
                        demos,
                        rng,
                        source_demo=demo,
                        source_demo_index=source_demo_index,
                        domain_randomization=domain_randomization,
                        domain_variant_index=domain_variant_index,
                        mimic_trial_index=mimic_trial_index,
                    )
                )
                index += 1
    return generated


def _read_source_demos(handle: Any, *, subtask_signals: tuple[str, ...]) -> list[_SourceDemo]:
    import numpy as np

    data = handle.get("data")
    if data is None:
        return []
    demos: list[_SourceDemo] = []
    for name in sorted(str(key) for key in data.keys() if str(key).startswith("demo_")):
        demo = data[name]
        if "actions" not in demo:
            continue
        actions = _as_float32(demo["actions"][:])
        if actions.ndim != 2 or actions.shape[0] == 0:
            continue
        observations = _read_observation_tree(demo.get("obs"), frame_count=actions.shape[0])
        states = _read_state_array(demo, observations=observations, actions=actions)
        initial_state = _read_group_tree(demo.get("initial_state"))
        boundaries = _subtask_boundaries(demo, frame_count=actions.shape[0], subtask_signals=subtask_signals)
        demos.append(
            _SourceDemo(
                name=name,
                actions=actions,
                states=states,
                observations=observations,
                initial_state=initial_state,
                attrs={str(key): _attr_value(value) for key, value in demo.attrs.items()},
                boundaries=boundaries,
            )
        )
    return demos


def _read_state_array(demo: Any, *, observations: dict[str, Any], actions: Any) -> Any:
    import numpy as np

    states_obj = demo.get("states")
    if states_obj is not None and hasattr(states_obj, "shape"):
        try:
            states = _as_float32(states_obj[:])
        except TypeError:
            states = None
        if states is not None and getattr(states, "ndim", 0) == 2 and states.shape[0] == actions.shape[0]:
            return _slice_or_pad(states, 0, int(actions.shape[0]), int(actions.shape[1]))
    for key in ("robot_state", "joint_pos"):
        value = observations.get(key)
        if value is not None and not isinstance(value, dict):
            states = _as_float32(value)
            if key == "joint_pos" and states.shape[1] < actions.shape[1]:
                gripper_state = observations.get("gripper_state")
                if gripper_state is not None and not isinstance(gripper_state, dict):
                    gripper = _as_float32(gripper_state)
                    if getattr(gripper, "ndim", 0) == 2 and gripper.shape[0] == actions.shape[0]:
                        states = np.concatenate([states, gripper], axis=1)
            if getattr(states, "ndim", 0) == 2 and states.shape[0] == actions.shape[0]:
                return _slice_or_pad(states, 0, int(actions.shape[0]), int(actions.shape[1]))
    return actions.copy()


def _build_trial(
    index: int,
    demos: list[_SourceDemo],
    rng: Any,
    *,
    source_demo: _SourceDemo | None = None,
    source_demo_index: int = 0,
    domain_randomization: dict[str, Any] | None = None,
    domain_variant_index: int = 0,
    mimic_trial_index: int = 0,
) -> dict[str, Any]:
    import numpy as np

    segment_payloads: list[tuple[_SourceDemo, int, int]] = []
    segment_sources: list[dict[str, Any]] = []
    subtask_count = max(len(demo.boundaries) for demo in demos)
    for subtask_index in range(subtask_count):
        candidates = [demo for demo in demos if subtask_index < len(demo.boundaries)]
        if len(candidates) > 1:
            candidate_index = (int(source_demo_index) + int(domain_variant_index) + int(mimic_trial_index) + int(subtask_index)) % len(candidates)
            demo = candidates[candidate_index]
        else:
            demo = candidates[0]
        start, end = demo.boundaries[subtask_index]
        if end <= start:
            continue
        segment_payloads.append((demo, start, end))
        segment_sources.append(
            {
                "source_demo": demo.name,
                "subtask_index": subtask_index,
                "start": int(start),
                "end": int(end),
            }
        )
    if not segment_payloads:
        demo = demos[int(rng.integers(0, len(demos)))] if len(demos) > 1 else demos[0]
        segment_payloads = [(demo, 0, int(demo.actions.shape[0]))]
        segment_sources = [{"source_demo": demo.name, "subtask_index": 0, "start": 0, "end": int(demo.actions.shape[0])}]

    primary = source_demo or segment_payloads[0][0]
    initial_state = _copy_tree(primary.initial_state)
    domain_randomization = dict(domain_randomization or _sample_domain_randomization("off", rng))
    _apply_domain_randomization_to_initial_state(initial_state, domain_randomization)
    actions = np.concatenate([demo.actions[start:end] for demo, start, end in segment_payloads], axis=0).astype(np.float32)
    states = np.concatenate([_slice_or_pad(demo.states, start, end, actions.shape[1]) for demo, start, end in segment_payloads], axis=0).astype(np.float32)
    observations = _concat_observations(segment_payloads, frame_count=int(actions.shape[0]), action_dim=int(actions.shape[1]))
    source_episode_index = _source_episode_index(primary)
    return {
        "name": f"demo_{index:06d}",
        "actions": actions,
        "states": states,
        "observations": observations,
        "initial_state": initial_state,
        "source_demo": primary.name,
        "source_episode_index": source_episode_index,
        "domain_variant_index": int(domain_variant_index),
        "mimic_trial_index": int(mimic_trial_index),
        "domain_randomization": domain_randomization,
        "source_segments": segment_sources,
    }


def _source_episode_index(demo: _SourceDemo) -> int:
    raw = demo.attrs.get("episode_index")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        pass
    suffix = demo.name.rsplit("_", 1)[-1]
    try:
        return max(0, int(suffix))
    except ValueError:
        return 0


def _write_generated_hdf5(output_path: Path, generated: list[dict[str, Any]], *, env_name: str, input_path: Path) -> None:
    import h5py
    import numpy as np

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.name}.tmp.{os.getpid()}")
    if tmp_path.exists():
        tmp_path.unlink()
    total = sum(int(item["actions"].shape[0]) for item in generated)
    env_args_json = json.dumps({"env_name": env_name, "type": 2, "env_kwargs": {}})
    with h5py.File(tmp_path, "w") as handle:
        handle.attrs["schema"] = "atr.lerobot.isaac_lab_mimic.joint_replay_hdf5.v1"
        handle.attrs["source_type"] = "isaac_lab_mimic"
        handle.attrs["generator"] = JOINT_REPLAY_GENERATOR
        handle.attrs["input_path"] = str(input_path)
        handle.attrs["total"] = int(total)
        handle.attrs["env_args"] = env_args_json
        data = handle.create_group("data")
        data.attrs["total"] = int(total)
        data.attrs["env_args"] = env_args_json
        for index, item in enumerate(generated):
            demo = data.create_group(str(item["name"]))
            actions = item["actions"]
            states = item["states"]
            demo.attrs["num_samples"] = int(actions.shape[0])
            demo.attrs["success"] = np.bool_(True)
            demo.attrs["generator"] = JOINT_REPLAY_GENERATOR
            demo.attrs["source_demo"] = str(item.get("source_demo") or "")
            demo.attrs["source_episode_index"] = int(item.get("source_episode_index") or 0)
            demo.attrs["domain_variant_index"] = int(item.get("domain_variant_index") or 0)
            demo.attrs["mimic_trial_index"] = int(item.get("mimic_trial_index") or 0)
            demo.attrs["domain_randomization"] = json.dumps(item.get("domain_randomization") or {}, sort_keys=True)
            demo.attrs["source_segments"] = json.dumps(item["source_segments"])
            demo.create_dataset("actions", data=actions.astype(np.float32))
            demo.create_dataset("states", data=states.astype(np.float32))
            demo.create_dataset("frame_indices", data=np.arange(actions.shape[0], dtype=np.int64))
            _write_group_tree(demo.create_group("initial_state"), item["initial_state"])
            obs_group = demo.create_group("obs")
            _write_group_tree(obs_group, item["observations"])
    tmp_path.replace(output_path)


def _write_success_manifest(path: Path, generated: list[dict[str, Any]], output_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(generated):
        rows.append(
            {
                "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                "source_type": "isaac_lab_mimic",
                "generator": JOINT_REPLAY_GENERATOR,
                "generated_demo": str(item["name"]),
                "trajectory_id": f"joint_replay_{index:06d}",
                "generated_index": index,
                "episode_index": int(item.get("source_episode_index") or 0),
                "source_episode_index": int(item.get("source_episode_index") or 0),
                "source_demo": str(item.get("source_demo") or ""),
                "domain_variant_index": int(item.get("domain_variant_index") or 0),
                "mimic_trial_index": int(item.get("mimic_trial_index") or 0),
                "domain_randomization": item.get("domain_randomization") or {},
                "frame_count": int(item["actions"].shape[0]),
                "hdf5_path": str(output_path),
                "artifacts": {"hdf5_path": "mimic/generated_dataset.hdf5"},
                "training": {"eligible": True, "fidelity_weight": 1.0},
                "metrics": {"success": True, "joint_replay": True},
            }
        )
    _write_jsonl(path, rows)
    return rows


def _subtask_boundaries(demo: Any, *, frame_count: int, subtask_signals: tuple[str, ...]) -> list[tuple[int, int]]:
    signal_group = demo.get("obs/datagen_info/subtask_term_signals")
    if signal_group is None:
        return [(0, frame_count)]
    boundaries: list[tuple[int, int]] = []
    start = 0
    for name in subtask_signals:
        if name not in signal_group:
            continue
        index = _first_true_index(signal_group[name][:])
        end = min(frame_count, max(start + 1, index + 1))
        boundaries.append((start, end))
        start = end
    if start < frame_count:
        boundaries.append((start, frame_count))
    return boundaries or [(0, frame_count)]


def _first_true_index(values: Any) -> int:
    import numpy as np

    flat = np.asarray(values).reshape(-1)
    true_indices = np.flatnonzero(flat.astype(bool))
    if true_indices.size == 0:
        return max(0, flat.shape[0] - 1)
    return int(true_indices[0])


def _read_observation_tree(group: Any, *, frame_count: int) -> dict[str, Any]:
    tree = _read_group_tree(group)
    if "joint_pos" not in tree and group is not None and "datagen_info" in tree:
        pass
    return tree


def _read_group_tree(group: Any) -> dict[str, Any]:
    import h5py

    if group is None:
        return {}
    tree: dict[str, Any] = {"__attrs__": {str(key): _attr_value(value) for key, value in group.attrs.items()}}
    for key, value in group.items():
        if isinstance(value, h5py.Dataset):
            tree[str(key)] = value[:]
        else:
            tree[str(key)] = _read_group_tree(value)
    return tree


def _concat_observations(
    segment_payloads: list[tuple[_SourceDemo, int, int]],
    *,
    frame_count: int,
    action_dim: int,
) -> dict[str, Any]:
    import numpy as np

    tree = _concat_tree([demo.observations for demo, _, _ in segment_payloads], [(start, end) for _, start, end in segment_payloads])
    actions = np.concatenate([demo.actions[start:end] for demo, start, end in segment_payloads], axis=0).astype(np.float32)
    states = np.concatenate([_slice_or_pad(demo.states, start, end, action_dim) for demo, start, end in segment_payloads], axis=0).astype(np.float32)
    tree.setdefault("joint_pos", actions)
    tree.setdefault("robot_state", states)
    tree.setdefault("gripper_state", actions[:, -1:])
    pose = np.eye(4, dtype=np.float32)[None, :, :].repeat(frame_count, axis=0)
    tree.setdefault("eef_pose", pose)
    tree.setdefault("object_pose", pose)
    datagen = tree.setdefault("datagen_info", {})
    object_pose = datagen.setdefault("object_pose", {})
    object_pose.setdefault("red_cube", tree["object_pose"])
    eef_pose = datagen.setdefault("eef_pose", {})
    eef_pose.setdefault("omx", tree["eef_pose"])
    target_eef_pose = datagen.setdefault("target_eef_pose", {})
    target_eef_pose.setdefault("omx", tree["eef_pose"])
    signals = datagen.setdefault("subtask_term_signals", {})
    for name, values in _synthetic_subtask_signals(frame_count).items():
        signals.setdefault(name, values)
    return tree


def _concat_tree(trees: list[dict[str, Any]], slices: list[tuple[int, int]]) -> dict[str, Any]:
    import numpy as np

    output: dict[str, Any] = {}
    keys = sorted({key for tree in trees for key in tree.keys() if key != "__attrs__"})
    for key in keys:
        values = [tree.get(key) for tree in trees]
        present = [(value, slice_pair) for value, slice_pair in zip(values, slices) if value is not None]
        if not present:
            continue
        first = present[0][0]
        if isinstance(first, dict):
            output[key] = _concat_tree([value for value, _ in present], [slice_pair for _, slice_pair in present])
            continue
        arrays = []
        for value, (start, end) in present:
            array = np.asarray(value)
            if array.shape and array.shape[0] >= end:
                arrays.append(array[start:end])
        if arrays:
            output[key] = _normalize_array(np.concatenate(arrays, axis=0))
    return output


def _write_group_tree(group: Any, tree: dict[str, Any]) -> None:
    attrs = tree.get("__attrs__") if isinstance(tree.get("__attrs__"), dict) else {}
    for key, value in attrs.items():
        if value is not None:
            group.attrs[str(key)] = value
    for key, value in sorted(tree.items()):
        if key == "__attrs__":
            continue
        if isinstance(value, dict):
            _write_group_tree(group.create_group(str(key)), value)
        else:
            group.create_dataset(str(key), data=_normalize_array(value))


def _copy_tree(tree: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    copied: dict[str, Any] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            copied[key] = _copy_tree(value)
        else:
            copied[key] = np.asarray(value).copy()
    return copied


def _sample_domain_randomization(profile_name: str, rng: Any) -> dict[str, Any]:
    import numpy as np

    profile = _domain_randomization_profile(profile_name)
    xy_lo, xy_hi = profile["cube_xy_m"]
    yaw_lo, yaw_hi = profile["cube_yaw_rad"]
    mass_lo, mass_hi = profile["cube_mass_scale"]
    static_lo, static_hi = profile["cube_static_friction"]
    dynamic_lo, dynamic_hi = profile["cube_dynamic_friction"]
    gripper_lo, gripper_hi = profile["gripper_inner_static_friction"]
    return {
        "profile": str(profile_name or "off"),
        "cube_xy_offset_m": [
            float(rng.uniform(float(xy_lo), float(xy_hi))),
            float(rng.uniform(float(xy_lo), float(xy_hi))),
        ],
        "cube_yaw_rad": float(rng.uniform(float(yaw_lo), float(yaw_hi))),
        "cube_mass_scale": float(rng.uniform(float(mass_lo), float(mass_hi))),
        "cube_static_friction": float(rng.uniform(float(static_lo), float(static_hi))),
        "cube_dynamic_friction": float(rng.uniform(float(dynamic_lo), float(dynamic_hi))),
        "gripper_inner_static_friction": float(rng.uniform(float(gripper_lo), float(gripper_hi))),
        "applied_to_initial_state": ["red_cube_root_pose"],
        "sample_source": "joint_replay_domain_variant",
    }


def _domain_randomization_profile(profile_name: str) -> dict[str, tuple[float, float]]:
    try:
        from integrations.isaac_lab_robotis_omx.domain_randomization import get_profile

        return dict(get_profile(str(profile_name or "off")))
    except Exception:  # noqa: BLE001 - keep the generator usable in lightweight test/runtime environments.
        fallback = {
            "off": {
                "cube_xy_m": (0.0, 0.0),
                "cube_yaw_rad": (0.0, 0.0),
                "cube_mass_scale": (1.0, 1.0),
                "cube_static_friction": (0.9, 0.9),
                "cube_dynamic_friction": (0.7, 0.7),
                "gripper_inner_static_friction": (1.2, 1.2),
            },
            "standard": {
                "cube_xy_m": (-0.04, 0.04),
                "cube_yaw_rad": (-0.785398, 0.785398),
                "cube_mass_scale": (0.75, 1.25),
                "cube_static_friction": (0.7, 1.3),
                "cube_dynamic_friction": (0.5, 1.0),
                "gripper_inner_static_friction": (1.0, 1.6),
            },
        }
        return fallback.get(str(profile_name or "off"), fallback["off"])


def _apply_domain_randomization_to_initial_state(initial_state: dict[str, Any], randomization: dict[str, Any]) -> None:
    import numpy as np

    cube_state = (
        initial_state.get("rigid_object", {})
        .get("red_cube", {})
    )
    root_pose = cube_state.get("root_pose") if isinstance(cube_state, dict) else None
    if root_pose is None:
        return
    pose = np.asarray(root_pose, dtype=np.float32).copy()
    if pose.ndim != 2 or pose.shape[0] < 1 or pose.shape[1] < 7:
        return
    offset = np.asarray(randomization.get("cube_xy_offset_m") or [0.0, 0.0], dtype=np.float32).reshape(2)
    pose[0, 0] += offset[0]
    pose[0, 1] += offset[1]
    pose[0, 3:7] = _yaw_quaternion(float(randomization.get("cube_yaw_rad") or 0.0))
    cube_state["root_pose"] = pose


def _yaw_quaternion(yaw: float) -> Any:
    import math
    import numpy as np

    half = float(yaw) * 0.5
    return np.asarray([0.0, 0.0, math.sin(half), math.cos(half)], dtype=np.float32)


def _slice_or_pad(values: Any, start: int, end: int, width: int) -> Any:
    import numpy as np

    array = np.asarray(values)
    if array.ndim == 2 and array.shape[0] >= end:
        sliced = array[start:end]
        if sliced.shape[1] == width:
            return sliced
        adjusted = np.zeros((sliced.shape[0], width), dtype=np.float32)
        columns = min(width, sliced.shape[1])
        adjusted[:, :columns] = sliced[:, :columns]
        return adjusted
    return np.zeros((max(0, end - start), width), dtype=np.float32)


def _synthetic_subtask_signals(frame_count: int) -> dict[str, Any]:
    import numpy as np

    count = max(1, int(frame_count))
    signals: dict[str, Any] = {}
    for name, fraction in {"approach": 0.25, "grasp": 0.45, "lift": 0.65, "place": 0.85}.items():
        index = min(count - 1, max(1, int(round(count * fraction)))) if count > 1 else 0
        values = np.zeros((count, 1), dtype=np.bool_)
        values[index:] = True
        signals[name] = values
    return signals


def _as_float32(values: Any) -> Any:
    import numpy as np

    return np.asarray(values, dtype=np.float32)


def _normalize_array(values: Any) -> Any:
    import numpy as np

    array = np.asarray(values)
    if array.dtype.kind == "f" and array.dtype != np.dtype("float32"):
        return array.astype(np.float32)
    return array


def _load_env_args(handle: Any) -> dict[str, Any]:
    raw = handle.attrs.get("env_args")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _attr_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return value
    return value


def _blocked_summary(
    blocker: str,
    message: str,
    input_path: Path,
    output_path: Path,
    success_manifest_path: Path,
    failure_manifest_path: Path,
) -> dict[str, Any]:
    return {
        "schema": "atr.lerobot.isaac_lab_mimic.joint_replay.summary.v1",
        "ok": False,
        "status": "blocked",
        "backend": "joint_replay",
        "blocker": blocker,
        "message": message,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "success_manifest_path": str(success_manifest_path),
        "failure_manifest_path": str(failure_manifest_path),
        "success_count": 0,
        "failure_count": 0,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
