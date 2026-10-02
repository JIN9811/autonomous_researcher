"""HDF5 contract helpers for the Isaac Lab Mimic sidecar."""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any


DEFAULT_ISAAC_RGBD_HDF5_EMBED_FRAME_LIMIT = 1000


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_env_args(attrs: Any) -> dict[str, Any]:
    raw = attrs.get("env_args")
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def validate_isaac_lab_hdf5_contract(path: Path, *, expected_env_name: str) -> dict[str, Any]:
    """Validate the minimum HDF5 fields required by Isaac Lab Mimic."""
    import h5py

    blockers: list[str] = []
    demos: list[str] = []
    path = Path(path).expanduser()
    if not path.is_file():
        return {"ok": False, "path": str(path), "blockers": ["HDF5_FILE_MISSING"], "demo_count": 0}

    with h5py.File(path, "r") as handle:
        data = handle.get("data")
        data_env_args = _load_env_args(data.attrs) if data is not None else {}
        env_args = data_env_args or _load_env_args(handle.attrs)
        env_name = str(env_args.get("env_name") or "")
        if not env_args:
            blockers.append("ENV_ARGS_MISSING")
        elif env_name != expected_env_name:
            blockers.append("ENV_NAME_MISMATCH")

        if data is None:
            blockers.append("DATA_GROUP_MISSING")
        else:
            demos = sorted(str(name) for name in data.keys() if str(name).startswith("demo_"))
            if not demos:
                blockers.append("DEMO_GROUPS_MISSING")
            for demo_name in demos:
                demo = data[demo_name]
                if "actions" not in demo:
                    blockers.append(f"{demo_name}:ACTIONS_MISSING")
                if "initial_state" not in demo:
                    blockers.append(f"{demo_name}:INITIAL_STATE_MISSING")
                else:
                    blockers.extend(_initial_state_blockers(demo["initial_state"], prefix=demo_name))
                blockers.extend(_non_tensor_dataset_blockers(demo, prefix=demo_name))
                if "obs" not in demo:
                    blockers.append(f"{demo_name}:OBS_MISSING")
                    blockers.append("DATAGEN_INFO_MISSING")
                    continue
                if "datagen_info" not in demo["obs"]:
                    blockers.append("DATAGEN_INFO_MISSING")
                else:
                    datagen = demo["obs"]["datagen_info"]
                    for key in ("object_pose", "eef_pose", "target_eef_pose", "subtask_term_signals"):
                        if key not in datagen:
                            blockers.append(f"DATAGEN_{key.upper()}_MISSING")

    return {
        "ok": not blockers,
        "path": str(path),
        "expected_env_name": expected_env_name,
        "blockers": sorted(set(blockers)),
        "demo_count": len(demos),
        "demos": demos,
    }


def validate_isaac_lab_datagen_pool_contract(
    path: Path,
    *,
    expected_env_name: str,
    subtask_term_signals: list[str | None] | None = None,
    required_object_refs: list[str] | None = None,
    eef_name: str = "omx",
    select_demo_keys: str | None = None,
) -> dict[str, Any]:
    """Validate that official Isaac Lab Mimic can parse the HDF5 datagen_info pool."""

    path = Path(path).expanduser()
    hdf5_report = validate_isaac_lab_hdf5_contract(path, expected_env_name=expected_env_name)
    if not hdf5_report.get("ok"):
        return {
            "ok": False,
            "path": str(path),
            "blockers": ["HDF5_CONTRACT_FAILED", *list(hdf5_report.get("blockers") or [])],
            "hdf5_contract": hdf5_report,
            "num_datagen_infos": 0,
            "subtask_boundaries": {},
        }

    try:
        import torch
        from isaaclab_mimic.datagen.datagen_info_pool import DataGenInfoPool
    except Exception as exc:  # noqa: BLE001 - Isaac Lab import errors vary by environment.
        return {
            "ok": False,
            "path": str(path),
            "blockers": ["DATAGEN_POOL_IMPORT_FAILED"],
            "detail": f"{exc.__class__.__name__}: {exc}",
            "hdf5_contract": hdf5_report,
            "num_datagen_infos": 0,
            "subtask_boundaries": {},
        }

    signals = subtask_term_signals or ["cube_lifted", "released_at_target", None]
    subtask_configs = [
        SimpleNamespace(
            subtask_term_signal=signal,
            subtask_start_offset_range=(0, 0),
            subtask_term_offset_range=(0, 0),
        )
        for signal in signals
    ]
    env_cfg = SimpleNamespace(
        subtask_configs={eef_name: subtask_configs},
        datagen_config=SimpleNamespace(use_skillgen=False),
    )

    class _PoolValidationEnv:
        def actions_to_gripper_actions(self, actions: Any) -> dict[str, Any]:
            return {eef_name: actions}

    try:
        pool = DataGenInfoPool(_PoolValidationEnv(), env_cfg, torch.device("cpu"))
        pool.load_from_dataset_file(str(path), select_demo_keys=select_demo_keys)
    except Exception as exc:  # noqa: BLE001 - official loader raises ValueError/KeyError/AssertionError.
        return {
            "ok": False,
            "path": str(path),
            "blockers": ["DATAGEN_POOL_LOAD_FAILED"],
            "detail": f"{exc.__class__.__name__}: {exc}",
            "hdf5_contract": hdf5_report,
            "num_datagen_infos": 0,
            "subtask_boundaries": {},
            "subtask_term_signals": signals,
        }

    object_refs = required_object_refs or ["red_cube", "place_target"]
    missing_object_refs: list[dict[str, Any]] = []
    for index, datagen_info in enumerate(pool.datagen_infos):
        available = set((datagen_info.object_poses or {}).keys())
        for object_ref in object_refs:
            if object_ref not in available:
                missing_object_refs.append(
                    {"datagen_info_index": index, "object_ref": object_ref, "available_object_refs": sorted(available)}
                )
    if missing_object_refs:
        return {
            "ok": False,
            "path": str(path),
            "blockers": ["DATAGEN_OBJECT_REF_MISSING"],
            "hdf5_contract": hdf5_report,
            "num_datagen_infos": int(pool.num_datagen_infos),
            "subtask_boundaries": pool.subtask_boundaries,
            "subtask_term_signals": signals,
            "required_object_refs": object_refs,
            "missing_object_refs": missing_object_refs,
        }

    return {
        "ok": True,
        "path": str(path),
        "blockers": [],
        "hdf5_contract": hdf5_report,
        "num_datagen_infos": int(pool.num_datagen_infos),
        "subtask_boundaries": pool.subtask_boundaries,
        "subtask_term_signals": signals,
        "required_object_refs": object_refs,
    }


def ensure_isaac_lab_mimic_signal_aliases(path: Path) -> dict[str, Any]:
    """Add official Mimic signal aliases to an annotated HDF5 copy when legacy signals exist."""
    import h5py

    path = Path(path).expanduser()
    if not path.is_file():
        return {"ok": False, "path": str(path), "blockers": ["HDF5_FILE_MISSING"], "added": [], "missing": []}

    alias_sources = {
        "cube_lifted": ("lift",),
        "released_at_target": ("release", "place"),
    }
    added: list[dict[str, str]] = []
    missing: list[dict[str, Any]] = []
    checked_demos: list[str] = []

    with h5py.File(path, "r+") as handle:
        data = handle.get("data")
        if data is None:
            return {"ok": False, "path": str(path), "blockers": ["DATA_GROUP_MISSING"], "added": [], "missing": []}
        for demo_name in sorted(str(name) for name in data.keys() if str(name).startswith("demo_")):
            checked_demos.append(demo_name)
            signals = data[demo_name].get("obs/datagen_info/subtask_term_signals")
            if signals is None:
                missing.append({"demo": demo_name, "alias": "*", "available_sources": []})
                continue
            for alias_name, source_names in alias_sources.items():
                if alias_name in signals:
                    continue
                source_name = next((candidate for candidate in source_names if candidate in signals), None)
                if source_name is None:
                    missing.append(
                        {
                            "demo": demo_name,
                            "alias": alias_name,
                            "available_sources": sorted(str(name) for name in signals.keys()),
                        }
                    )
                    continue
                source = signals[source_name]
                created = signals.create_dataset(alias_name, data=source[()], dtype=source.dtype)
                for key, value in source.attrs.items():
                    created.attrs[key] = value
                added.append({"demo": demo_name, "alias": alias_name, "source": source_name})

    return {
        "ok": not missing,
        "path": str(path),
        "blockers": [] if not missing else ["MIMIC_SIGNAL_ALIAS_SOURCE_MISSING"],
        "checked_demos": checked_demos,
        "added": added,
        "missing": missing,
    }


def ensure_isaac_lab_mimic_object_pose_refs(path: Path) -> dict[str, Any]:
    """Add static official Mimic object refs that are required by the task config."""
    import h5py

    path = Path(path).expanduser()
    if not path.is_file():
        return {"ok": False, "path": str(path), "blockers": ["HDF5_FILE_MISSING"], "added": [], "missing": []}

    added: list[dict[str, str]] = []
    missing: list[dict[str, Any]] = []
    checked_demos: list[str] = []
    with h5py.File(path, "r+") as handle:
        data = handle.get("data")
        if data is None:
            return {"ok": False, "path": str(path), "blockers": ["DATA_GROUP_MISSING"], "added": [], "missing": []}
        for demo_name in sorted(str(name) for name in data.keys() if str(name).startswith("demo_")):
            checked_demos.append(demo_name)
            demo = data[demo_name]
            object_pose_group = demo.get("obs/datagen_info/object_pose")
            if object_pose_group is None:
                missing.append({"demo": demo_name, "object_ref": "*", "reason": "OBJECT_POSE_GROUP_MISSING"})
                continue
            if "place_target" not in object_pose_group:
                frame_count = _demo_frame_count(demo)
                object_pose_group.create_dataset("place_target", data=_place_target_pose_matrices(frame_count))
                added.append({"demo": demo_name, "object_ref": "place_target", "source": "physical_place_target_constant"})

    return {
        "ok": not missing,
        "path": str(path),
        "blockers": [] if not missing else ["MIMIC_OBJECT_POSE_GROUP_MISSING"],
        "checked_demos": checked_demos,
        "added": added,
        "missing": missing,
    }


def _demo_frame_count(demo: Any) -> int:
    actions = demo.get("actions")
    if actions is not None and len(getattr(actions, "shape", ())) >= 1:
        return max(1, int(actions.shape[0]))
    try:
        return max(1, int(demo.attrs.get("num_samples", 1)))
    except Exception:  # noqa: BLE001
        return 1


def _place_target_pose_matrices(frame_count: int) -> Any:
    import numpy as np

    try:
        from integrations.isaac_lab_robotis_omx.mdp import physical_observations

        x_m, y_m = physical_observations.PLACE_TARGET_XY_M
        z_m = physical_observations.PLACE_TARGET_CUBE_CENTER_Z_M
    except Exception:  # noqa: BLE001
        x_m, y_m, z_m = 0.590, 0.078, 0.119
    pose = np.eye(4, dtype=np.float32).reshape(1, 4, 4).repeat(max(1, int(frame_count)), axis=0)
    pose[:, 0, 3] = float(x_m)
    pose[:, 1, 3] = float(y_m)
    pose[:, 2, 3] = float(z_m)
    return pose


def _non_tensor_dataset_blockers(group: Any, *, prefix: str) -> list[str]:
    """Return datasets under an episode that Isaac Lab cannot convert to torch tensors."""
    import h5py

    blockers: list[str] = []

    def visit(name: str, obj: Any) -> None:
        if not isinstance(obj, h5py.Dataset):
            return
        kind = getattr(obj.dtype, "kind", "")
        if kind not in {"b", "i", "u", "f", "c"}:
            blockers.append(f"{prefix}:NON_TENSOR_DATASET:{name}:{obj.dtype}")

    group.visititems(visit)
    return blockers


def _initial_state_blockers(group: Any, *, prefix: str) -> list[str]:
    blockers: list[str] = []
    required = {
        "articulation/robot/root_pose": (1, 7),
        "articulation/robot/root_velocity": (1, 6),
        "articulation/robot/joint_position": (1, 7),
        "articulation/robot/joint_velocity": (1, 7),
        "rigid_object/red_cube/root_pose": (1, 7),
        "rigid_object/red_cube/root_velocity": (1, 6),
    }
    for path, shape in required.items():
        node: Any = group
        missing = False
        for part in path.split("/"):
            if part not in node:
                missing = True
                break
            node = node[part]
        if missing:
            blockers.append(f"{prefix}:INITIAL_STATE_{path.upper().replace('/', '_')}_MISSING")
            continue
        if tuple(getattr(node, "shape", ())) != shape:
            blockers.append(f"{prefix}:INITIAL_STATE_{path.upper().replace('/', '_')}_SHAPE")
    return blockers


def export_lerobot_success_episodes_to_isaac_lab_hdf5(
    *,
    request: Any,
    dataset_path: Path,
    canonical_manifest_path: Path,
    canonical_rows: list[dict[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    """Export successful LeRobot episodes to the Isaac Lab Mimic HDF5 shape."""
    import h5py
    import numpy as np
    import pyarrow.parquet as pq

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in canonical_rows:
        grouped[_safe_int(row.get("episode_index"), 0, minimum=0)].append(row)

    exported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    parsed_episodes: dict[int, dict[str, Any]] = {}
    mirror_targets_by_frame = _mirror_targets_by_frame(dataset_path)
    specimen_pose_by_episode = _rgbd_render_attempt_specimen_pose_by_episode(dataset_path)
    embed_isaac_rgbd, isaac_rgbd_embed_reason, isaac_rgbd_embed_limit = _isaac_rgbd_embedding_policy(
        request,
        canonical_frame_count=len(canonical_rows),
    )
    for episode_index, episode_rows in sorted(grouped.items()):
        if any(row.get("episode_success") is False for row in episode_rows):
            skipped.append({"episode_index": episode_index, "reason": "EPISODE_MARKED_FAILED"})
            continue
        episode_path = _episode_data_file_path(dataset_path, episode_index)
        if not episode_path.is_file():
            skipped.append({"episode_index": episode_index, "reason": "PARQUET_MISSING", "path": str(episode_path)})
            continue
        try:
            table = pq.read_table(episode_path)
        except Exception as exc:  # noqa: BLE001 - pyarrow raises several concrete exception types.
            skipped.append(
                {
                    "episode_index": episode_index,
                    "reason": "PARQUET_READ_FAILED",
                    "path": str(episode_path),
                    "detail": f"{exc.__class__.__name__}: {exc}",
                }
            )
            continue
        data = table.to_pydict()
        missing_columns = [column for column in ("observation.state", "action") if column not in data]
        if missing_columns:
            skipped.append(
                {
                    "episode_index": episode_index,
                    "reason": "REQUIRED_COLUMNS_MISSING",
                    "path": str(episode_path),
                    "missing_columns": missing_columns,
                }
            )
            continue
        try:
            parsed = _parse_episode_for_hdf5(
                request=request,
                data=data,
                canonical_rows=episode_rows,
                episode_index=episode_index,
                mirror_targets_by_frame=mirror_targets_by_frame,
                specimen_pose_by_episode=specimen_pose_by_episode,
                embed_isaac_rgbd=embed_isaac_rgbd,
                isaac_rgbd_embed_reason=isaac_rgbd_embed_reason,
                isaac_rgbd_embed_limit=isaac_rgbd_embed_limit,
            )
        except ValueError as exc:
            skipped.append(
                {
                    "episode_index": episode_index,
                    "reason": "EPISODE_PARSE_FAILED",
                    "path": str(episode_path),
                    "detail": str(exc),
                }
            )
            continue
        parsed_episodes[episode_index] = parsed
        exported.append(
            {
                "episode_index": episode_index,
                "frame_count": int(parsed["actions"].shape[0]),
                "parquet_path": str(episode_path),
            }
        )

    canonical_frame_count = len(canonical_rows)
    if not exported:
        blocker_by_reason = {
            "PARQUET_READ_FAILED": "HDF5_EXPORT_PARQUET_READ_FAILED",
            "PARQUET_MISSING": "HDF5_EXPORT_PARQUET_MISSING",
            "REQUIRED_COLUMNS_MISSING": "HDF5_EXPORT_REQUIRED_COLUMNS_MISSING",
        }
        first_reason = str(skipped[0].get("reason") if skipped else "")
        return blocked_hdf5_summary(
            blocker=blocker_by_reason.get(first_reason, "HDF5_EXPORT_NO_TRAIN_READY_EPISODES"),
            message="No canonical real episodes could be exported to HDF5.",
            canonical_manifest_path=canonical_manifest_path,
            canonical_frame_count=canonical_frame_count,
            output_path=output_path,
            skipped_episodes=skipped,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.name}.tmp.{os.getpid()}")
    if tmp_path.exists():
        tmp_path.unlink()
    with h5py.File(tmp_path, "w") as handle:
        handle.attrs["schema"] = "atr.lerobot.isaac_lab_hdf5_export.v1"
        handle.attrs["format_version"] = 1
        handle.attrs["dataset_path"] = str(dataset_path)
        handle.attrs["canonical_manifest_path"] = str(canonical_manifest_path)
        handle.attrs["total"] = sum(int(item["frame_count"]) for item in exported)
        env_args_json = json.dumps(
            {"env_name": request.isaac_lab_task_name, "type": 2, "env_kwargs": {}}
        )
        handle.attrs["env_args"] = env_args_json
        data_group = handle.create_group("data")
        data_group.attrs["total"] = sum(int(item["frame_count"]) for item in exported)
        data_group.attrs["env_args"] = env_args_json
        canonical_sidecar = handle.create_group("canonical_sidecar")
        canonical_sidecar.attrs["schema"] = "atr.lerobot.canonical_episode_hdf5_sidecar.v1"
        for episode_index, parsed in sorted(parsed_episodes.items()):
            demo = data_group.create_group(f"demo_{episode_index:06d}")
            demo.attrs["episode_index"] = episode_index
            demo.attrs["num_samples"] = int(parsed["actions"].shape[0])
            initial_state = demo.create_group("initial_state")
            articulation_state = initial_state.create_group("articulation")
            robot_state = articulation_state.create_group("robot")
            robot_state.create_dataset("root_pose", data=_robot_initial_root_pose())
            robot_state.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
            robot_state.create_dataset("joint_position", data=_robot_initial_joint_position(parsed["joint_pos"]))
            robot_state.create_dataset("joint_velocity", data=np.zeros((1, 7), dtype=np.float32))
            rigid_state = initial_state.create_group("rigid_object")
            red_cube_state = rigid_state.create_group("red_cube")
            red_cube_state.create_dataset("root_pose", data=parsed["initial_red_cube_root_pose"])
            red_cube_state.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
            demo.create_dataset("actions", data=parsed["actions"])
            demo.create_dataset("states", data=parsed["states"])
            demo.create_dataset("timestamps", data=parsed["timestamps"])
            demo.create_dataset("frame_indices", data=parsed["frame_indices"])
            obs = demo.create_group("obs")
            obs.create_dataset("robot_state", data=parsed["states"])
            obs.create_dataset("joint_pos", data=parsed["joint_pos"])
            obs.create_dataset("gripper_state", data=parsed["gripper_state"])
            obs.create_dataset("object_pose", data=parsed["object_pose"])
            obs.create_dataset("eef_pose", data=parsed["eef_pose"])
            for name, values in parsed.get("isaac_rgbd_observations", {}).items():
                dataset = obs.create_dataset(name, data=values)
                if name.endswith("_depth"):
                    metadata = parsed.get("isaac_rgbd_depth_metadata", {}).get(name, {})
                    dataset.attrs["encoding"] = str(metadata.get("encoding") or "png16")
                    dataset.attrs["depth_scale_m_per_unit"] = float(metadata.get("depth_scale_m_per_unit") or 0.001)
            for name, values in parsed.get("isaac_rgbd_valid_masks", {}).items():
                obs.create_dataset(f"{name}_valid", data=values)
            datagen = obs.create_group("datagen_info")
            object_pose_group = datagen.create_group("object_pose")
            object_pose_group.create_dataset("red_cube", data=parsed["object_pose"])
            object_pose_group.create_dataset("place_target", data=parsed["place_target_pose"])
            eef_pose_group = datagen.create_group("eef_pose")
            eef_pose_group.create_dataset("omx", data=parsed["eef_pose"])
            target_eef_pose_group = datagen.create_group("target_eef_pose")
            target_eef_pose_group.create_dataset("omx", data=parsed["target_eef_pose"])
            subtask_term_signals = datagen.create_group("subtask_term_signals")
            for signal_name, values in parsed["subtask_term_signals"].items():
                subtask_term_signals.create_dataset(signal_name, data=values)
            canonical = canonical_sidecar.create_group(f"demo_{episode_index:06d}")
            canonical.attrs["episode_index"] = episode_index
            isaac_rgbd_embedding = parsed.get("isaac_rgbd_embedding") if isinstance(parsed.get("isaac_rgbd_embedding"), dict) else {}
            canonical.attrs["isaac_rgbd_embedded"] = 1 if bool(isaac_rgbd_embedding.get("embedded")) else 0
            canonical.attrs["isaac_rgbd_embedding_reason"] = str(isaac_rgbd_embedding.get("reason") or "")
            canonical.attrs["isaac_rgbd_embedding_frame_limit"] = int(isaac_rgbd_embedding.get("frame_limit") or 0)
            red_cube_source = parsed.get("initial_red_cube_root_pose_source")
            if isinstance(red_cube_source, dict):
                canonical.attrs["specimen_pose_source"] = str(red_cube_source.get("source") or "lab_scene_default")
                canonical.attrs["specimen_pose_attempt_id"] = str(red_cube_source.get("attempt_id") or "")
                canonical.attrs["specimen_pose_source_path"] = str(red_cube_source.get("source_path") or "")
            string_dtype = h5py.string_dtype(encoding="utf-8")
            canonical.create_dataset("grasp_event_labels", data=parsed["grasp_event_labels"], dtype=string_dtype)
            canonical.create_dataset("missing_sources", data=parsed["missing_sources"], dtype=string_dtype)
            canonical.create_dataset("raw_depth_paths", data=parsed["raw_depth_paths"], dtype=string_dtype)
            canonical.create_dataset("action_source_labels", data=parsed["action_source_labels"], dtype=string_dtype)
            canonical.create_dataset(
                "mirror_action_source_paths",
                data=parsed["mirror_action_source_paths"],
                dtype=string_dtype,
            )
            isaac_rgbd_paths = parsed.get("isaac_rgbd_paths", {})
            if isaac_rgbd_paths:
                isaac_rgbd_group = canonical.create_group("isaac_rgbd_paths")
                for name, values in isaac_rgbd_paths.items():
                    isaac_rgbd_group.create_dataset(name, data=values, dtype=string_dtype)
            availability = canonical.create_group("source_availability")
            for source, values in parsed["source_availability"].items():
                availability.create_dataset(source, data=np.asarray(values, dtype=np.bool_))
    tmp_path.replace(output_path)

    exported_frame_count = sum(int(item["frame_count"]) for item in exported)
    contract_report = validate_isaac_lab_hdf5_contract(
        output_path,
        expected_env_name=request.isaac_lab_task_name,
    )
    _atomic_write_json(output_path.with_name("hdf5_contract_report.json"), contract_report)
    return {
        "schema": "atr.lerobot.isaac_lab_hdf5_export.summary.v1",
        "ok": True,
        "status": "passed",
        "blocker": "",
        "hdf5_available": True,
        "message": "Exported canonical successful real episodes to Isaac Lab/robomimic HDF5.",
        "canonical_manifest_path": str(canonical_manifest_path),
        "canonical_frame_count": canonical_frame_count,
        "output_path": str(output_path),
        "exported_episode_count": len(exported),
        "exported_frame_count": exported_frame_count,
        "isaac_rgbd_embedded": bool(embed_isaac_rgbd),
        "isaac_rgbd_embedding_reason": isaac_rgbd_embed_reason,
        "isaac_rgbd_embedding_frame_limit": isaac_rgbd_embed_limit,
        "exported_episodes": exported,
        "skipped_episodes": skipped,
        "contract_report_path": str(output_path.with_name("hdf5_contract_report.json")),
        "contract_ok": bool(contract_report.get("ok")),
        "contract_blockers": list(contract_report.get("blockers") or []),
        "required_next_parser_fields": [],
    }


def import_mimic_successes_from_hdf5(
    *,
    generated_hdf5_path: Path,
    success_manifest_path: Path,
) -> dict[str, Any]:
    """Inspect a generated Mimic HDF5 and write a success manifest skeleton."""
    import h5py

    generated_hdf5_path = Path(generated_hdf5_path).expanduser()
    success_manifest_path = Path(success_manifest_path).expanduser()
    if not generated_hdf5_path.is_file():
        return {
            "ok": False,
            "status": "blocked",
            "blocker": "MIMIC_GENERATED_HDF5_MISSING",
            "generated_hdf5_path": str(generated_hdf5_path),
            "success_manifest_path": str(success_manifest_path),
            "success_count": 0,
        }

    rows: list[dict[str, Any]] = []
    with h5py.File(generated_hdf5_path, "r") as handle:
        data = handle.get("data")
        demo_names = sorted(str(name) for name in data.keys() if str(name).startswith("demo_")) if data else []
        for index, demo_name in enumerate(demo_names):
            demo = data[demo_name]
            success = bool(demo.attrs.get("success", True))
            if not success:
                continue
            rows.append(
                {
                    "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                    "source_type": "isaac_lab_mimic",
                    "generated_demo": demo_name,
                    "episode_index": index,
                    "frame_count": int(demo.attrs.get("num_samples", 0)),
                    "hdf5_path": str(generated_hdf5_path),
                }
            )

    success_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with success_manifest_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return {
        "ok": True,
        "status": "passed",
        "generated_hdf5_path": str(generated_hdf5_path),
        "success_manifest_path": str(success_manifest_path),
        "success_count": len(rows),
    }


def blocked_hdf5_summary(
    *,
    blocker: str,
    message: str,
    canonical_manifest_path: Path,
    canonical_frame_count: int,
    output_path: Path,
    skipped_episodes: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "atr.lerobot.isaac_lab_hdf5_export.summary.v1",
        "ok": False,
        "status": "blocked",
        "blocker": blocker,
        "hdf5_available": False,
        "message": message,
        "canonical_manifest_path": str(canonical_manifest_path),
        "canonical_frame_count": max(0, int(canonical_frame_count)),
        "output_path": str(output_path),
        "exported_episode_count": 0,
        "exported_frame_count": 0,
        "skipped_episodes": skipped_episodes,
        "required_next_parser_fields": [
            "observation.state",
            "action",
            "episode_index",
            "frame_index",
            "timestamp",
            "success",
        ],
        **dict(extra or {}),
    }


def _isaac_rgbd_embedding_policy(request: Any, *, canonical_frame_count: int) -> tuple[bool, str, int]:
    limit = _safe_int(
        os.environ.get("ATR_ISAAC_LAB_HDF5_RGBD_EMBED_FRAME_LIMIT"),
        DEFAULT_ISAAC_RGBD_HDF5_EMBED_FRAME_LIMIT,
        minimum=0,
    )
    explicit = getattr(request, "isaac_lab_hdf5_embed_rgbd", None)
    if explicit is not None:
        return bool(explicit), "request_override" if bool(explicit) else "request_disabled", limit
    if limit <= 0:
        return False, "frame_embedding_disabled", limit
    if canonical_frame_count > limit:
        return False, "frame_count_exceeds_limit", limit
    return True, "frame_count_within_limit", limit


def _parse_episode_for_hdf5(
    *,
    request: Any,
    data: dict[str, list[Any]],
    canonical_rows: list[dict[str, Any]],
    episode_index: int,
    mirror_targets_by_frame: dict[tuple[int, int], dict[str, Any]] | None = None,
    specimen_pose_by_episode: dict[int, dict[str, Any]] | None = None,
    embed_isaac_rgbd: bool = True,
    isaac_rgbd_embed_reason: str = "frame_count_within_limit",
    isaac_rgbd_embed_limit: int = DEFAULT_ISAAC_RGBD_HDF5_EMBED_FRAME_LIMIT,
) -> dict[str, Any]:
    import numpy as np

    data = _episode_filtered_table_data(data, episode_index)
    mirror_targets_by_frame = dict(mirror_targets_by_frame or {})
    frame_values = data.get("frame_index") or list(range(len(data["action"])))
    row_by_frame = {_safe_int(frame, index, minimum=0): index for index, frame in enumerate(frame_values)}
    ordered_rows = sorted(canonical_rows, key=lambda item: _safe_int(item.get("frame_index"), 0, minimum=0))
    actions: list[list[float]] = []
    states: list[list[float]] = []
    joint_positions: list[list[float]] = []
    timestamps: list[float] = []
    frame_indices: list[int] = []
    source_availability: dict[str, list[bool]] = defaultdict(list)
    grasp_event_labels: list[str] = []
    missing_sources: list[str] = []
    raw_depth_paths: list[str] = []
    action_source_labels: list[str] = []
    mirror_action_source_paths: list[str] = []
    isaac_rgbd_paths: dict[str, list[str]] = defaultdict(list)
    isaac_rgbd_arrays: dict[str, list[Any]] = defaultdict(list)
    isaac_rgbd_depth_metadata: dict[str, dict[str, Any]] = {}
    isaac_rgbd_camera_names = _isaac_rgbd_camera_names(ordered_rows)
    isaac_rgbd_target_size = _isaac_rgbd_target_size(request)
    for row in ordered_rows:
        frame_index = _safe_int(row.get("frame_index"), 0, minimum=0)
        if frame_index not in row_by_frame:
            raise ValueError(f"episode {episode_index} missing frame_index {frame_index} in parquet")
        table_index = row_by_frame[frame_index]
        source_action = _numeric_vector(data["action"][table_index], field="action", frame_index=frame_index)
        mirror_target = mirror_targets_by_frame.get((episode_index, frame_index))
        mirror_action = (
            mirror_target.get("action") if isinstance(mirror_target, dict) else None
        )
        if isinstance(mirror_action, list) and mirror_action:
            action = [float(item) for item in mirror_action]
            action_source_labels.append("isaac_mirror_target")
            mirror_action_source_paths.append(str(mirror_target.get("source_manifest") or ""))
        else:
            action = _lab_action_vector(source_action)
            action_source_labels.append("lerobot_action")
            mirror_action_source_paths.append("")
        state = _numeric_vector(
            data["observation.state"][table_index],
            field="observation.state",
            frame_index=frame_index,
        )
        actions.append(action)
        states.append(state)
        joint_positions.append(action if action_source_labels[-1] == "isaac_mirror_target" else state)
        timestamp_values = data.get("timestamp")
        timestamp = float(timestamp_values[table_index]) if timestamp_values is not None else round(frame_index / 15.0, 6)
        timestamps.append(timestamp)
        frame_indices.append(frame_index)
        availability = row.get("source_availability") if isinstance(row.get("source_availability"), dict) else {}
        for source in (
            "real_rgb",
            "raw_depth",
            "isaac_rgbd",
            "active_robot_cam",
            "grasp_diagnostics",
            "lerobot_action",
        ):
            source_availability[source].append(bool(availability.get(source)))
        grasp = row.get("grasp_diagnostics") if isinstance(row.get("grasp_diagnostics"), dict) else {}
        grasp_event_labels.append(str(row.get("grasp_event_label") or grasp.get("event_label") or grasp.get("state") or ""))
        missing = row.get("missing_sources") if isinstance(row.get("missing_sources"), list) else []
        missing_sources.append(",".join(str(item) for item in missing))
        raw_depth = row.get("raw_depth") if isinstance(row.get("raw_depth"), dict) else {}
        raw_depth_paths.append(str(raw_depth.get("path") or ""))
        _collect_isaac_rgbd_frame(
            row,
            camera_names=isaac_rgbd_camera_names,
            target_size=isaac_rgbd_target_size,
            isaac_rgbd_paths=isaac_rgbd_paths,
            isaac_rgbd_arrays=isaac_rgbd_arrays,
            isaac_rgbd_depth_metadata=isaac_rgbd_depth_metadata,
            load_arrays=embed_isaac_rgbd,
        )
    states_array = np.asarray(states, dtype=np.float32)
    actions_array = np.asarray(actions, dtype=np.float32)
    if "isaac_mirror_target" in action_source_labels:
        joint_pos_array = actions_array.astype(np.float32)
        pose_source_array = joint_pos_array
    else:
        joint_pos_array = np.asarray(joint_positions, dtype=np.float32)
        pose_source_array = states_array
    specimen_pose = dict((specimen_pose_by_episode or {}).get(episode_index) or {})
    initial_red_cube_root_pose = _red_cube_initial_root_pose(specimen_pose)
    object_pose = _pose_matrices_from_root_pose(initial_red_cube_root_pose, len(actions))
    place_target_pose = _place_target_pose_matrices(len(actions))
    eef_pose = _eef_pose_matrices_from_states(pose_source_array)
    return {
        "actions": actions_array,
        "states": states_array,
        "timestamps": np.asarray(timestamps, dtype=np.float32),
        "frame_indices": np.asarray(frame_indices, dtype=np.int64),
        "joint_pos": joint_pos_array,
        "gripper_state": _gripper_state_from_actions(actions_array),
        "object_pose": object_pose,
        "place_target_pose": place_target_pose,
        "eef_pose": eef_pose,
        "initial_red_cube_root_pose": initial_red_cube_root_pose,
        "initial_red_cube_root_pose_source": specimen_pose,
        "target_eef_pose": eef_pose.copy(),
        "subtask_term_signals": _subtask_term_signals(len(actions)),
        "source_availability": dict(source_availability),
        "grasp_event_labels": grasp_event_labels,
        "missing_sources": missing_sources,
        "raw_depth_paths": raw_depth_paths,
        "action_source_labels": action_source_labels,
        "mirror_action_source_paths": mirror_action_source_paths,
        "isaac_rgbd_paths": dict(isaac_rgbd_paths),
        "isaac_rgbd_observations": _isaac_rgbd_observation_arrays(
            isaac_rgbd_arrays,
            expected_count=len(actions),
        ) if embed_isaac_rgbd else {},
        "isaac_rgbd_valid_masks": _isaac_rgbd_valid_masks(
            isaac_rgbd_arrays,
            expected_count=len(actions),
        ) if embed_isaac_rgbd else {},
        "isaac_rgbd_depth_metadata": isaac_rgbd_depth_metadata,
        "isaac_rgbd_embedding": {
            "embedded": bool(embed_isaac_rgbd),
            "reason": str(isaac_rgbd_embed_reason or ""),
            "frame_limit": int(isaac_rgbd_embed_limit),
            "frame_count": len(actions),
        },
    }


def _episode_filtered_table_data(data: dict[str, list[Any]], episode_index: int) -> dict[str, list[Any]]:
    episode_values = data.get("episode_index")
    if not isinstance(episode_values, list):
        return data
    selected = [
        index
        for index, value in enumerate(episode_values)
        if _safe_int(value, -1, minimum=-1) == int(episode_index)
    ]
    if not selected:
        return data
    row_count = len(episode_values)
    filtered: dict[str, list[Any]] = {}
    for key, values in data.items():
        if isinstance(values, list) and len(values) == row_count:
            filtered[key] = [values[index] for index in selected]
        else:
            filtered[key] = values
    return filtered


def _episode_data_file_path(dataset_path: Path, episode_index: int) -> Path:
    info = _read_json(dataset_path / "meta" / "info.json")
    chunks_size = _safe_int(info.get("chunks_size"), 1000, minimum=1)
    episode_chunk = int(episode_index) // chunks_size
    template = str(info.get("data_path") or "").strip()
    format_values = {
        "episode_index": int(episode_index),
        "episode_chunk": episode_chunk,
        "chunk_index": episode_chunk,
        "file_index": episode_chunk,
    }
    candidates: list[Path] = []
    if template:
        try:
            candidates.append(dataset_path / template.format(**format_values))
        except (KeyError, ValueError):
            pass
    candidates.extend(
        [
            dataset_path / "data" / f"chunk-{episode_chunk:03d}" / f"episode_{episode_index:06d}.parquet",
            dataset_path / "data" / "chunk-000" / f"episode_{episode_index:06d}.parquet",
            dataset_path / "data" / f"chunk-{episode_chunk:03d}" / f"file-{episode_chunk:03d}.parquet",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _mirror_targets_by_frame(dataset_path: Path) -> dict[tuple[int, int], dict[str, Any]]:
    indexed: dict[tuple[int, int], dict[str, Any]] = {}
    mirror_root = Path(dataset_path).expanduser() / "sidecar" / "isaac_mirror"
    if not mirror_root.is_dir():
        return indexed
    for manifest_path in sorted(mirror_root.glob("*.jsonl")):
        try:
            rows = manifest_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in rows:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            joint_state = row.get("joint_state") if isinstance(row.get("joint_state"), list) else []
            action = _mirror_action_vector(joint_state)
            if not action:
                continue
            episode_index = _mirror_episode_index(row)
            frame_index = _mirror_frame_index(row)
            if frame_index is None:
                continue
            indexed[(episode_index, frame_index)] = {
                "action": action,
                "source_manifest": str(manifest_path),
                "sample_index": row.get("sample_index"),
            }
    return indexed


def _rgbd_render_attempt_specimen_pose_by_episode(dataset_path: Path) -> dict[int, dict[str, Any]]:
    """Return the specimen pose selected by the same render-queue grouping used for Isaac RGB-D."""
    dataset_path = Path(dataset_path).expanduser()
    mirror_root = dataset_path / "sidecar" / "isaac_mirror"
    if not mirror_root.is_dir():
        return {}
    selected: dict[int, dict[str, Any]] = {}
    sequence = 0
    for manifest_path in sorted(mirror_root.glob("*.jsonl")):
        for row in _read_jsonl_rows(manifest_path):
            render_queue = row.get("render_queue") if isinstance(row.get("render_queue"), dict) else {}
            if not isinstance(render_queue, dict) or not render_queue:
                continue
            request = render_queue.get("render_request") if isinstance(render_queue.get("render_request"), dict) else {}
            if request and not bool(request.get("enabled", True)):
                continue
            attempt_id = str(
                (request.get("attempt_id") if isinstance(request, dict) else "")
                or render_queue.get("attempt_id")
                or ""
            ).strip()
            if not attempt_id:
                continue
            episode_index = _safe_int(
                request.get("episode_index") if isinstance(request, dict) else None,
                _safe_int(render_queue.get("episode_index"), _mirror_episode_index(row), minimum=0),
                minimum=0,
            )
            frame_index = _safe_int(
                request.get("frame_index") if isinstance(request, dict) else None,
                _safe_int(render_queue.get("frame_index"), _mirror_frame_index(row) or 0, minimum=0),
                minimum=0,
            )
            pose = _rgbd_render_attempt_specimen_pose(
                dataset_path,
                episode_index=episode_index,
                attempt_id=attempt_id,
            )
            if not pose:
                continue
            pose["frame_index"] = frame_index
            pose["source_manifest"] = str(manifest_path)
            pose["render_queue_status"] = str(render_queue.get("status") or "")
            sequence += 1
            pose["_selection_sequence"] = sequence
            previous = selected.get(episode_index)
            if previous is None:
                selected[episode_index] = pose
                continue
            previous_frame = _safe_int(previous.get("frame_index"), 0, minimum=0)
            previous_sequence = _safe_int(previous.get("_selection_sequence"), 0, minimum=0)
            if frame_index < previous_frame or (frame_index == previous_frame and sequence >= previous_sequence):
                selected[episode_index] = pose
    for pose in selected.values():
        pose.pop("_selection_sequence", None)
    return selected


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
    except OSError:
        return []
    return rows


def _rgbd_render_attempt_specimen_pose(
    dataset_path: Path,
    *,
    episode_index: int,
    attempt_id: str,
) -> dict[str, Any]:
    pose_path = (
        Path(dataset_path).expanduser()
        / "sidecar"
        / "attempts"
        / f"episode_{int(episode_index):03d}"
        / str(attempt_id)
        / "specimen_pose.json"
    )
    try:
        raw = json.loads(pose_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(raw, dict) and raw.get("ok") is False:
        return {}
    pose = raw.get("pose") if isinstance(raw, dict) and isinstance(raw.get("pose"), dict) else raw
    if not isinstance(pose, dict):
        return {}
    position = pose.get("position_isaac_world_mm") if isinstance(pose.get("position_isaac_world_mm"), dict) else {}
    try:
        position_m = [
            float(position["x"]) * 0.001,
            float(position["y"]) * 0.001,
            float(position["z"]) * 0.001,
        ]
    except (KeyError, TypeError, ValueError):
        return {}
    yaw_deg = _specimen_yaw_deg_from_pose(pose)
    root_pose = _red_cube_root_pose_values(position_m, yaw_deg)
    return {
        "source": "isaac_rgbd_render_attempt_specimen_pose",
        "attempt_id": str(attempt_id),
        "episode_index": int(episode_index),
        "source_path": str(pose_path),
        "position_m": position_m,
        "yaw_deg": yaw_deg,
        "root_pose": root_pose,
    }


def _specimen_yaw_deg_from_pose(pose: dict[str, Any]) -> float | None:
    orientation = pose.get("orientation_deg") if isinstance(pose.get("orientation_deg"), dict) else {}
    for value in (orientation.get("yaw"), orientation.get("yaw_deg"), pose.get("yaw_deg")):
        if value is None:
            continue
        try:
            yaw = float(value)
        except (TypeError, ValueError):
            continue
        return ((yaw + 180.0) % 360.0) - 180.0
    return None


def _red_cube_root_pose_values(position_m: list[float], yaw_deg: float | None) -> list[float]:
    yaw = math.radians(float(yaw_deg or 0.0))
    half = yaw * 0.5
    return [
        float(position_m[0]),
        float(position_m[1]),
        float(position_m[2]),
        0.0,
        0.0,
        float(math.sin(half)),
        float(math.cos(half)),
    ]


def _mirror_episode_index(row: dict[str, Any]) -> int:
    render_queue = row.get("render_queue") if isinstance(row.get("render_queue"), dict) else {}
    render_request = row.get("render_request") if isinstance(row.get("render_request"), dict) else {}
    nested_render_request = render_queue.get("render_request") if isinstance(render_queue.get("render_request"), dict) else {}
    for value in (
        row.get("episode_index"),
        row.get("record_episode_index"),
        render_queue.get("episode_index"),
        render_request.get("episode_index"),
        nested_render_request.get("episode_index"),
    ):
        if value is not None:
            return _safe_int(value, 0, minimum=0)
    return 0


def _mirror_frame_index(row: dict[str, Any]) -> int | None:
    render_queue = row.get("render_queue") if isinstance(row.get("render_queue"), dict) else {}
    render_request = row.get("render_request") if isinstance(row.get("render_request"), dict) else {}
    nested_render_request = render_queue.get("render_request") if isinstance(render_queue.get("render_request"), dict) else {}
    for value in (
        row.get("frame_index"),
        row.get("canonical_frame_index"),
        row.get("source_frame_index"),
        render_queue.get("frame_index"),
        render_request.get("frame_index"),
        nested_render_request.get("frame_index"),
    ):
        if value is not None:
            return _safe_int(value, 0, minimum=0)
    if row.get("sample_index") is not None:
        return _safe_int(row.get("sample_index"), 1, minimum=1) - 1
    return None


def _mirror_action_vector(joint_state: list[Any], width: int = 7) -> list[float] | None:
    import numpy as np

    targets: dict[int, float] = {}
    gripper_mimic_multiplier = -1.0
    for item in joint_state:
        if not isinstance(item, dict):
            continue
        index = _mirror_joint_index(item)
        if index is None:
            continue
        raw_value = item.get("target_value")
        if raw_value is None:
            raw_value = item.get("position_deg")
        if raw_value is None:
            raw_value = item.get("source_value")
        try:
            target = float(raw_value)
        except (TypeError, ValueError):
            continue
        unit = str(item.get("unit") or "").strip().lower()
        if unit not in {"rad", "radian", "radians"}:
            target = float(np.deg2rad(target))
        targets[index] = target
        if index == 5:
            gripper_mimic_multiplier = _safe_float(item.get("mimic_multiplier"), -1.0)
    if any(index not in targets for index in range(6)):
        return None
    action = np.zeros((width,), dtype=np.float32)
    for index in range(min(5, width)):
        action[index] = targets[index]
    if width >= 7:
        action[5] = targets[5]
        action[6] = targets.get(6, targets[5] * gripper_mimic_multiplier)
    elif width > 5:
        action[5] = targets[5]
    return [float(item) for item in action.tolist()]


def _mirror_joint_index(item: dict[str, Any]) -> int | None:
    name = str(item.get("isaac_joint_name") or "").strip()
    by_name = {
        "Joint1": 0,
        "Joint2": 1,
        "Joint3": 2,
        "Joint4": 3,
        "Joint5": 4,
        "Gripper": 5,
        "Gripper_mimic": 6,
    }
    if name in by_name:
        return by_name[name]
    motor_name = str(item.get("motor_name") or "").strip().lower()
    by_motor_name = {
        "shoulder_pan": 0,
        "shoulder_lift": 1,
        "elbow_flex": 2,
        "wrist_flex": 3,
        "wrist_roll": 4,
        "gripper": 5,
    }
    if motor_name in by_motor_name:
        return by_motor_name[motor_name]
    motor_id = _safe_int(item.get("motor_id"), -1)
    if 11 <= motor_id <= 16:
        return motor_id - 11
    return None


def _collect_isaac_rgbd_frame(
    row: dict[str, Any],
    *,
    camera_names: list[str],
    target_size: tuple[int, int] | None,
    isaac_rgbd_paths: dict[str, list[str]],
    isaac_rgbd_arrays: dict[str, list[Any]],
    isaac_rgbd_depth_metadata: dict[str, dict[str, Any]],
    load_arrays: bool = True,
) -> None:
    isaac_rgbd = row.get("isaac_rgbd") if isinstance(row.get("isaac_rgbd"), dict) else {}
    frames = isaac_rgbd.get("frames") if isinstance(isaac_rgbd.get("frames"), dict) else {}
    for camera in camera_names:
        entry = frames.get(camera)
        if not isinstance(entry, dict):
            entry = {}
        camera_key = str(camera)
        rgb_path = str(entry.get("rgb_path") or "")
        depth_path = str(entry.get("depth_path") or "")
        rgb_obs_name = f"{camera_key}_rgb"
        depth_obs_name = f"{camera_key}_depth"
        isaac_rgbd_paths[rgb_obs_name].append(rgb_path)
        if rgb_path and load_arrays:
            rgb = _load_rgb_array(rgb_path, target_size=target_size)
            isaac_rgbd_arrays[rgb_obs_name].append(rgb)
        elif load_arrays:
            isaac_rgbd_arrays[rgb_obs_name].append(None)
        isaac_rgbd_paths[depth_obs_name].append(depth_path)
        if depth_path:
            isaac_rgbd_depth_metadata[depth_obs_name] = _depth_metadata_for_entry(entry, depth_path)
        if depth_path and load_arrays:
            depth = _load_depth_array(depth_path, target_size=target_size)
            isaac_rgbd_arrays[depth_obs_name].append(depth)
        elif load_arrays:
            isaac_rgbd_arrays[depth_obs_name].append(None)


def _isaac_rgbd_camera_names(rows: list[dict[str, Any]]) -> list[str]:
    preferred = ["top", "front", "right", "wrist"]
    seen: set[str] = set()
    names: list[str] = []
    for row in rows:
        isaac_rgbd = row.get("isaac_rgbd") if isinstance(row.get("isaac_rgbd"), dict) else {}
        for camera in isaac_rgbd.get("camera_names") or []:
            value = str(camera).strip()
            if value and value not in seen:
                seen.add(value)
                names.append(value)
        frames = isaac_rgbd.get("frames") if isinstance(isaac_rgbd.get("frames"), dict) else {}
        for camera in frames:
            value = str(camera).strip()
            if value and value not in seen:
                seen.add(value)
                names.append(value)
    return [name for name in preferred if name in seen] + sorted(name for name in names if name not in preferred)


def _isaac_rgbd_target_size(request: Any) -> tuple[int, int] | None:
    width = _safe_int(getattr(request, "mimic_camera_width", 0), 0, minimum=0)
    height = _safe_int(getattr(request, "mimic_camera_height", 0), 0, minimum=0)
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def _load_rgb_array(path: str, *, target_size: tuple[int, int] | None = None) -> Any | None:
    try:
        import numpy as np
        from PIL import Image

        image = Image.open(path).convert("RGB")
        image = _resize_image_if_larger(image, target_size, resample=Image.Resampling.BILINEAR)
        return np.asarray(image, dtype=np.uint8)
    except Exception:  # noqa: BLE001 - optional rendered sidecar frames should not block state export.
        return None


def _load_depth_array(path: str, *, target_size: tuple[int, int] | None = None) -> Any | None:
    try:
        import numpy as np
        from PIL import Image

        if Path(path).suffix.lower() == ".npy":
            depth = np.asarray(np.load(path), dtype=np.float32)
            finite = np.isfinite(depth)
            if finite.any():
                max_finite = float(np.max(depth[finite]))
                depth = np.where(finite, depth, max_finite).astype(np.float32)
            else:
                depth = np.zeros(depth.shape, dtype=np.float32)
            depth = _resize_float_depth_if_larger(depth, target_size)
        else:
            image = Image.open(path)
            image = _resize_image_if_larger(image, target_size, resample=Image.Resampling.NEAREST)
            depth = np.asarray(image, dtype=np.uint16)
        if depth.ndim == 3:
            depth = depth[..., 0]
        return depth[..., None]
    except Exception:  # noqa: BLE001
        return None


def _resize_image_if_larger(image: Any, target_size: tuple[int, int] | None, *, resample: Any) -> Any:
    if target_size is None:
        return image
    target_width, target_height = target_size
    source_width, source_height = image.size
    if source_width <= target_width and source_height <= target_height:
        return image
    return image.resize((target_width, target_height), resample=resample)


def _resize_float_depth_if_larger(depth: Any, target_size: tuple[int, int] | None) -> Any:
    if target_size is None or depth.ndim < 2:
        return depth
    height, width = depth.shape[:2]
    target_width, target_height = target_size
    if width <= target_width and height <= target_height:
        return depth
    import numpy as np
    from PIL import Image

    image = Image.fromarray(np.asarray(depth, dtype=np.float32), mode="F")
    resized = image.resize((target_width, target_height), resample=Image.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.float32)


def _depth_metadata_for_entry(entry: dict[str, Any], depth_path: str) -> dict[str, Any]:
    encoding = str(entry.get("depth_encoding") or "png16")
    if Path(depth_path).suffix.lower() == ".npy" or encoding == "npy":
        return {"encoding": "npy_meters", "depth_scale_m_per_unit": 1.0}
    return {
        "encoding": encoding,
        "depth_scale_m_per_unit": _safe_float(entry.get("depth_scale_m_per_unit"), 0.001),
    }


def _isaac_rgbd_observation_arrays(values_by_name: dict[str, list[Any]], *, expected_count: int) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for name, values in values_by_name.items():
        if any(value is not None for value in values):
            observations[name] = _stack_isaac_rgbd_arrays(values, expected_count=expected_count, name=name)
    return observations


def _isaac_rgbd_valid_masks(values_by_name: dict[str, list[Any]], *, expected_count: int) -> dict[str, Any]:
    import numpy as np

    masks: dict[str, Any] = {}
    for name, values in values_by_name.items():
        if any(value is not None for value in values):
            padded = _padded_isaac_rgbd_values(values, expected_count=expected_count)
            masks[name] = np.asarray([[value is not None] for value in padded], dtype=np.bool_)
    return masks


def _stack_isaac_rgbd_arrays(values: list[Any], *, expected_count: int, name: str) -> Any:
    import numpy as np

    padded = _padded_isaac_rgbd_values(values, expected_count=expected_count)
    first_valid = next((value for value in padded if value is not None), None)
    if first_valid is None:
        raise ValueError(f"{name} has no readable RGB-D frames")
    fallback = np.zeros_like(first_valid)
    previous = first_valid
    filled = []
    for value in padded:
        if value is not None:
            previous = value
            filled.append(value)
        elif previous is not None:
            filled.append(previous)
        else:
            filled.append(fallback)
    return np.stack(filled, axis=0)


def _padded_isaac_rgbd_values(values: list[Any], *, expected_count: int) -> list[Any]:
    if len(values) >= expected_count:
        return list(values[:expected_count])
    return [*values, *([None] * (expected_count - len(values)))]


def _red_cube_initial_root_pose(specimen_pose: dict[str, Any] | None = None) -> Any:
    import numpy as np

    # Isaac Lab root pose uses position plus quaternion in (x, y, z, w).
    if isinstance(specimen_pose, dict):
        root_pose = specimen_pose.get("root_pose")
        if isinstance(root_pose, (list, tuple)) and len(root_pose) == 7:
            return np.asarray([root_pose], dtype=np.float32)
    # Physical Robotis OMX scene default, matching RobotisOMXPhysicalSceneCfg.red_cube.
    return np.asarray([[0.4, 0.3, 0.0152, 0.0, 0.0, 0.0, 1.0]], dtype=np.float32)


def _robot_initial_root_pose() -> Any:
    import numpy as np

    # Physical Robotis OMX scene root pose, matching RobotisOMXPhysicalSceneCfg.
    return np.asarray([[0.315, 0.06, -0.02, 0.0, 0.0, 0.7071068, 0.7071068]], dtype=np.float32)


def _robot_initial_joint_position(states: Any) -> Any:
    import numpy as np

    state_array = np.asarray(states, dtype=np.float32)
    first = state_array[0] if state_array.ndim == 2 and state_array.shape[0] else np.asarray([], dtype=np.float32)
    first = np.asarray(first, dtype=np.float32).reshape(-1)
    if first.size and float(np.nanmax(np.abs(first))) > (2.0 * np.pi):
        first = np.deg2rad(first).astype(np.float32)
    joint_position = np.zeros((7,), dtype=np.float32)
    arm_width = min(5, first.size)
    if arm_width:
        joint_position[:arm_width] = first[:arm_width]
    if first.size >= 7:
        joint_position[5:7] = first[5:7]
    elif first.size >= 6:
        gripper = float(first[5])
        joint_position[5] = gripper
        joint_position[6] = -gripper
    return joint_position.reshape(1, 7)


def _pose_matrices_from_xyz(xyz: Any) -> Any:
    import numpy as np

    positions = np.asarray(xyz, dtype=np.float32)
    if positions.ndim != 2 or positions.shape[1] != 3:
        positions = np.zeros((max(1, positions.shape[0] if positions.ndim else 1), 3), dtype=np.float32)
    poses = np.repeat(np.eye(4, dtype=np.float32)[None, :, :], positions.shape[0], axis=0)
    poses[:, :3, 3] = positions
    return poses


def _pose_matrices_from_root_pose(root_pose: Any, frame_count: int) -> Any:
    import numpy as np

    root = np.asarray(root_pose, dtype=np.float32).reshape(-1)
    count = max(1, int(frame_count))
    poses = np.repeat(np.eye(4, dtype=np.float32)[None, :, :], count, axis=0)
    if root.size < 7:
        return poses
    x, y, z, qx, qy, qz, qw = [float(item) for item in root[:7]]
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm <= 0.0:
        qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0
    else:
        qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    poses[:, :3, :3] = np.asarray(
        [
            [1.0 - 2.0 * (qy * qy + qz * qz), 2.0 * (qx * qy - qz * qw), 2.0 * (qx * qz + qy * qw)],
            [2.0 * (qx * qy + qz * qw), 1.0 - 2.0 * (qx * qx + qz * qz), 2.0 * (qy * qz - qx * qw)],
            [2.0 * (qx * qz - qy * qw), 2.0 * (qy * qz + qx * qw), 1.0 - 2.0 * (qx * qx + qy * qy)],
        ],
        dtype=np.float32,
    )
    poses[:, :3, 3] = [x, y, z]
    return poses


def _eef_pose_matrices_from_states(states: Any) -> Any:
    import numpy as np

    state_array = np.asarray(states, dtype=np.float32)
    positions = np.zeros((state_array.shape[0], 3), dtype=np.float32)
    if state_array.ndim == 2 and state_array.shape[1] > 0:
        dims = min(3, state_array.shape[1])
        positions[:, :dims] = state_array[:, :dims]
    return _pose_matrices_from_xyz(positions)


def _gripper_state_from_actions(actions: Any) -> Any:
    import numpy as np

    action_array = np.asarray(actions, dtype=np.float32)
    if action_array.ndim != 2 or action_array.shape[1] == 0:
        return np.zeros((max(1, action_array.shape[0] if action_array.ndim else 1), 1), dtype=np.float32)
    return action_array[:, -1:].astype(np.float32)


def _subtask_term_signals(frame_count: int) -> dict[str, Any]:
    import numpy as np

    count = max(1, int(frame_count))
    fractions = {
        "approach": 0.25,
        "grasp": 0.45,
        "lift": 0.65,
        "cube_lifted": 0.65,
        "place": 0.85,
        "released_at_target": 0.85,
    }
    signals: dict[str, Any] = {}
    for name, fraction in fractions.items():
        index = min(count - 1, max(1, int(round(count * fraction)))) if count > 1 else 0
        values = np.zeros((count, 1), dtype=np.bool_)
        values[index:] = True
        signals[name] = values
    return signals


def _numeric_vector(value: Any, *, field: str, frame_index: int) -> list[float]:
    if value is None:
        raise ValueError(f"{field} is missing at frame {frame_index}")
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        value = [value]
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not numeric at frame {frame_index}") from exc
    if not vector:
        raise ValueError(f"{field} is empty at frame {frame_index}")
    return vector


def _lab_action_vector(source_action: list[float], width: int = 7) -> list[float]:
    """Normalize source LeRobot joint actions to Robotis OMX joint targets."""
    import numpy as np

    values = np.asarray([float(item) for item in source_action], dtype=np.float32)
    if values.size and float(np.nanmax(np.abs(values))) > (2.0 * np.pi):
        values = np.deg2rad(values).astype(np.float32)
    action = np.zeros((width,), dtype=np.float32)
    arm_width = min(5, values.size, width)
    if arm_width:
        action[:arm_width] = values[:arm_width]
    if width >= 7 and values.size >= 7:
        action[5:7] = values[5:7]
    elif width >= 7 and values.size >= 6:
        gripper = float(values[5])
        action[5] = gripper
        action[6] = -gripper
    elif values.size:
        action[-1] = float(values[-1])
    return [float(item) for item in action.tolist()]


def _safe_int(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _safe_float(value: Any, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    if minimum is not None:
        result = max(float(minimum), result)
    if maximum is not None:
        result = min(float(maximum), result)
    return result
