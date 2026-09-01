"""Unit tests for local LeRobot v2.1 dataset management utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from utils.lerobot_dataset_manager import (
    delete_episodes,
    list_datasets,
    merge_datasets,
    split_dataset,
    suggest_next_repo_id,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _episode_table(*, episode_index: int, start_index: int, length: int, task_index: int = 0) -> pa.Table:
    return pa.table(
        {
            "episode_index": pa.array([episode_index] * length, type=pa.int64()),
            "frame_index": pa.array(list(range(length)), type=pa.int64()),
            "timestamp": pa.array([float(i) / 15.0 for i in range(length)], type=pa.float64()),
            "index": pa.array(list(range(start_index, start_index + length)), type=pa.int64()),
            "task_index": pa.array([task_index] * length, type=pa.int64()),
            "observation.state": pa.array([[float(episode_index), float(i)] for i in range(length)], type=pa.list_(pa.float32())),
            "action": pa.array([[float(i), float(episode_index)] for i in range(length)], type=pa.list_(pa.float32())),
        }
    )


def _make_lerobot_dataset(dataset_root: Path, repo_id: str, lengths: list[int]) -> Path:
    dataset_path = dataset_root / repo_id
    (dataset_path / "meta").mkdir(parents=True, exist_ok=True)
    (dataset_path / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    video_keys = [
        "observation.images.top",
        "observation.images.top_depth",
        "observation.images.wrist",
        "observation.images.wrist_depth",
    ]
    features = {
        "observation.state": {"dtype": "float32", "shape": [2]},
        "action": {"dtype": "float32", "shape": [2]},
    }
    for key in video_keys:
        features[key] = {
            "dtype": "video",
            "shape": [480, 640, 3],
            "names": ["height", "width", "channels"],
        }
    total_frames = sum(lengths)
    (dataset_path / "meta" / "info.json").write_text(
        json.dumps(
            {
                "codebase_version": "v2.1",
                "robot_type": "omx_follower",
                "fps": 15,
                "total_episodes": len(lengths),
                "total_frames": total_frames,
                "total_videos": len(lengths) * len(video_keys),
                "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
                "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
                "features": features,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _write_jsonl(dataset_path / "meta" / "tasks.jsonl", [{"task_index": 0, "task": "Pick up the cube"}])
    episodes: list[dict] = []
    stats: list[dict] = []
    frame_base = 0
    for episode_index, length in enumerate(lengths):
        pq.write_table(
            _episode_table(episode_index=episode_index, start_index=frame_base, length=length),
            dataset_path / "data" / "chunk-000" / f"episode_{episode_index:06d}.parquet",
        )
        episodes.append({"episode_index": episode_index, "tasks": ["Pick up the cube"], "length": length})
        stats.append({"episode_index": episode_index, "stats": {"length": length}})
        for video_key in video_keys:
            video_path = dataset_path / "videos" / "chunk-000" / video_key / f"episode_{episode_index:06d}.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(f"{repo_id}:{video_key}:{episode_index}".encode("utf-8"))
        for camera in ["top", "wrist"]:
            depth_dir = dataset_path / "sidecar" / "depth_raw" / camera / f"episode_{episode_index:06d}"
            depth_dir.mkdir(parents=True, exist_ok=True)
            for frame_index in range(length):
                (depth_dir / f"frame_{frame_index:06d}.png").write_bytes(b"depth16")
        attempt_dir = dataset_path / "sidecar" / "attempts" / f"episode_{episode_index:03d}" / f"attempt_fixture_ep{episode_index:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / "metadata.json").write_text(
            json.dumps({"episode_index": episode_index, "dataset_path": str(dataset_path), "attempt_dir": str(attempt_dir)}),
            encoding="utf-8",
        )
        isaac_rgbd_dir = dataset_path / "sidecar" / "isaac_rgbd" / f"episode_{episode_index:03d}"
        isaac_rgbd_dir.mkdir(parents=True, exist_ok=True)
        (isaac_rgbd_dir / "manifest.jsonl").write_text(
            json.dumps({"episode_index": episode_index, "dataset_path": str(dataset_path), "frame_count": length}) + "\n",
            encoding="utf-8",
        )
        frame_base += length
    _write_jsonl(dataset_path / "meta" / "episodes.jsonl", episodes)
    _write_jsonl(dataset_path / "meta" / "episodes_stats.jsonl", stats)
    _write_jsonl(
        dataset_path / "sidecar" / "attempts" / "manifest.jsonl",
        [
            {
                "episode_index": episode_index,
                "dataset_path": str(dataset_path),
                "attempt_dir": str(dataset_path / "sidecar" / "attempts" / f"episode_{episode_index:03d}" / f"attempt_fixture_ep{episode_index:03d}"),
                "manifest_path": str(dataset_path / "sidecar" / "attempts" / "manifest.jsonl"),
            }
            for episode_index in range(len(lengths))
        ],
    )
    _write_jsonl(
        dataset_path / "sidecar" / "isaac_mirror" / "lr-record-fixture.jsonl",
        [
            {
                "record_episode_index": episode_index,
                "frame_index": 0,
                "dataset_path": str(dataset_path),
                "record_attempt_id": f"attempt_fixture_ep{episode_index:03d}",
                "joint_positions": [episode_index, length],
            }
            for episode_index, length in enumerate(lengths)
        ],
    )
    (dataset_path / "meta" / "atr_pipeline.json").write_text(
        json.dumps({"dataset_repo_id": repo_id, "dataset_path": str(dataset_path), "observation_pipeline_id": "raw_depth_adapter"}),
        encoding="utf-8",
    )
    return dataset_path


def test_merge_reindexes_lerobot_core_and_atr_sidecars(tmp_path: Path) -> None:
    dataset_root = tmp_path / "lerobot"
    _make_lerobot_dataset(dataset_root, "jin/source_1", [2, 1])
    _make_lerobot_dataset(dataset_root, "jin/source_2", [1, 2, 1])

    result = merge_datasets(
        {
            "dataset_root": str(dataset_root),
            "sources": [
                {"dataset_repo_id": "jin/source_1", "episode_range": "all"},
                {"dataset_repo_id": "jin/source_2", "episode_range": "0-1"},
            ],
            "output_repo_id": "jin/merged",
        }
    )

    assert result["ok"] is True
    assert result["output_repo_id"] == "jin/merged"
    output = dataset_root / "jin" / "merged"
    info = json.loads((output / "meta" / "info.json").read_text(encoding="utf-8"))
    assert info["total_episodes"] == 4
    assert info["total_frames"] == 6
    episodes = _read_jsonl(output / "meta" / "episodes.jsonl")
    assert [row["episode_index"] for row in episodes] == [0, 1, 2, 3]
    assert [row["length"] for row in episodes] == [2, 1, 1, 2]
    assert (output / "videos" / "chunk-000" / "observation.images.wrist_depth" / "episode_000003.mp4").is_file()
    assert not (output / "data" / "chunk-000" / "episode_000004.parquet").exists()

    last = pq.read_table(output / "data" / "chunk-000" / "episode_000003.parquet").to_pydict()
    assert last["episode_index"] == [3, 3]
    assert last["index"] == [4, 5]
    assert last["frame_index"] == [0, 1]
    assert (output / "sidecar" / "depth_raw" / "top" / "episode_000003" / "frame_000001.png").is_file()
    assert (output / "sidecar" / "attempts" / "episode_003" / "attempt_fixture_ep003" / "metadata.json").is_file()
    attempts = _read_jsonl(output / "sidecar" / "attempts" / "manifest.jsonl")
    assert [row["episode_index"] for row in attempts] == [0, 1, 2, 3]
    assert all(str(output) in row["dataset_path"] for row in attempts)
    mirror_rows = _read_jsonl(output / "sidecar" / "isaac_mirror" / "jin_source_2__lr-record-fixture.jsonl")
    assert [row["record_episode_index"] for row in mirror_rows] == [2, 3]
    assert [row["record_attempt_id"] for row in mirror_rows] == ["attempt_fixture_ep002", "attempt_fixture_ep003"]
    assert (output / "sidecar" / "isaac_rgbd" / "episode_003" / "manifest.jsonl").is_file()
    audit = json.loads((output / "sidecar" / "dataset_manage" / "manifest.json").read_text(encoding="utf-8"))
    assert audit["operation"] == "merge"
    assert audit["total_episodes"] == 4


def test_suggest_next_repo_id_lists_datasets_and_skips_existing_names(tmp_path: Path) -> None:
    dataset_root = tmp_path / "lerobot"
    _make_lerobot_dataset(dataset_root, "jin/20260901_2", [1])
    _make_lerobot_dataset(dataset_root, "jin/20260901_8", [1])

    assert suggest_next_repo_id(dataset_root, namespace="jin", date_prefix="20260901") == "jin/20260901_9"
    listing = list_datasets({"dataset_root": str(dataset_root), "namespace": "jin", "date_prefix": "20260901"})
    assert listing["ok"] is True
    assert listing["suggested_repo_id"] == "jin/20260901_9"
    assert [row["repo_id"] for row in listing["datasets"]] == ["jin/20260901_2", "jin/20260901_8"]


def test_merge_20260901_2_and_8_auto_names_9_when_output_is_blank(tmp_path: Path) -> None:
    dataset_root = tmp_path / "lerobot"
    _make_lerobot_dataset(dataset_root, "jin/20260901_2", [2, 3])
    _make_lerobot_dataset(dataset_root, "jin/20260901_8", [4])

    result = merge_datasets(
        {
            "dataset_root": str(dataset_root),
            "namespace": "jin",
            "date_prefix": "20260901",
            "sources": [
                {"dataset_repo_id": "jin/20260901_8", "episode_range": "all"},
                {"dataset_repo_id": "jin/20260901_2", "episode_range": "0-1"},
            ],
        }
    )

    assert result["ok"] is True
    assert result["output_repo_id"] == "jin/20260901_9"
    output = dataset_root / "jin" / "20260901_9"
    info = json.loads((output / "meta" / "info.json").read_text(encoding="utf-8"))
    assert info["total_episodes"] == 3
    assert info["total_frames"] == 9
    assert [row["length"] for row in _read_jsonl(output / "meta" / "episodes.jsonl")] == [4, 2, 3]


def test_split_and_delete_compact_keep_sidecars_in_episode_order(tmp_path: Path) -> None:
    dataset_root = tmp_path / "lerobot"
    _make_lerobot_dataset(dataset_root, "jin/source", [2, 3, 4, 5])

    split = split_dataset(
        {
            "dataset_root": str(dataset_root),
            "source": {"dataset_repo_id": "jin/source"},
            "splits": [{"name": "train", "episode_range": "1-2", "output_repo_id": "jin/source_train"}],
        }
    )
    assert split["ok"] is True
    train = dataset_root / "jin" / "source_train"
    split_info = json.loads((train / "meta" / "info.json").read_text(encoding="utf-8"))
    assert split_info["total_episodes"] == 2
    assert split_info["total_frames"] == 7
    assert (train / "sidecar" / "depth_raw" / "wrist" / "episode_000001" / "frame_000003.png").is_file()

    compact = delete_episodes(
        {
            "dataset_root": str(dataset_root),
            "source": {"dataset_repo_id": "jin/source"},
            "delete_episode_range": "1,3",
            "output_repo_id": "jin/source_without_bad",
        }
    )
    assert compact["ok"] is True
    compact_path = dataset_root / "jin" / "source_without_bad"
    compact_episodes = _read_jsonl(compact_path / "meta" / "episodes.jsonl")
    assert [row["length"] for row in compact_episodes] == [2, 4]
    assert (compact_path / "data" / "chunk-000" / "episode_000001.parquet").is_file()
    assert not (compact_path / "data" / "chunk-000" / "episode_000002.parquet").exists()
    remaining = pq.read_table(compact_path / "data" / "chunk-000" / "episode_000001.parquet").to_pydict()
    assert remaining["episode_index"] == [1, 1, 1, 1]
    assert remaining["index"] == [2, 3, 4, 5]


def test_overwrite_compact_moves_existing_output_to_backup_before_recreate(tmp_path: Path) -> None:
    dataset_root = tmp_path / "lerobot"
    source = _make_lerobot_dataset(dataset_root, "jin/target", [2, 3, 4])
    marker = source / "sidecar" / "original_marker.txt"
    marker.write_text("preserve me", encoding="utf-8")

    result = delete_episodes(
        {
            "dataset_root": str(dataset_root),
            "source": {"dataset_repo_id": "jin/target"},
            "delete_episode_range": "1",
            "output_repo_id": "jin/target",
            "overwrite": True,
        }
    )

    output = dataset_root / "jin" / "target"
    backup = dataset_root / "jin" / "target_backup"
    assert result["ok"] is True
    assert result["backup_path"] == str(backup)
    assert output.is_dir()
    assert backup.is_dir()
    assert (backup / "sidecar" / "original_marker.txt").read_text(encoding="utf-8") == "preserve me"
    assert [row["length"] for row in _read_jsonl(output / "meta" / "episodes.jsonl")] == [2, 4]
    assert [row["length"] for row in _read_jsonl(backup / "meta" / "episodes.jsonl")] == [2, 3, 4]
    compact_ep1 = pq.read_table(output / "data" / "chunk-000" / "episode_000001.parquet").to_pydict()
    assert compact_ep1["episode_index"] == [1, 1, 1, 1]
    assert compact_ep1["index"] == [2, 3, 4, 5]
