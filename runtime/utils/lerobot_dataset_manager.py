"""Local LeRobot v2.1 dataset merge/split/delete helpers for ATR sidecars."""

from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import pyarrow as pa
import pyarrow.parquet as pq


DEFAULT_DATASET_ROOT = Path("~/.cache/huggingface/lerobot").expanduser()
EPISODE_TOKEN_RE = re.compile(r"episode_(\d{3}|\d{6})")
EP_SUFFIX_RE = re.compile(r"_ep(\d{3}|\d{6})(?=\D|$)")
HANDLED_SIDECARS = {"attempts", "dataset_manage", "depth_raw", "isaac_mirror"}
TEXT_REWRITE_SUFFIXES = {".json", ".jsonl", ".txt", ".csv", ".yaml", ".yml", ".md"}


@dataclass(slots=True)
class SourceDataset:
    repo_id: str
    path: Path
    info: dict[str, Any]
    episodes: dict[int, dict[str, Any]]
    stats: dict[int, dict[str, Any]]
    tasks_by_index: dict[int, str]
    video_keys: list[str]
    chunks_size: int


@dataclass(slots=True)
class EpisodeMapping:
    source: SourceDataset
    old_episode_index: int
    new_episode_index: int
    frame_count: int


def parse_episode_range(value: Any, total_episodes: int) -> list[int]:
    """Parse GUI-friendly episode ranges. Ranges with '-' are inclusive; ':' is stop-exclusive."""
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"all", "*"}:
        return list(range(total_episodes))
    selected: list[int] = []
    seen: set[int] = set()
    for token in re.split(r"[\s,]+", raw):
        token = token.strip()
        if not token:
            continue
        if token.lower() in {"all", "*"}:
            candidates = range(total_episodes)
        elif ":" in token:
            start_raw, stop_raw = token.split(":", 1)
            start = int(start_raw) if start_raw else 0
            stop = int(stop_raw) if stop_raw else total_episodes
            candidates = range(start, stop)
        elif "-" in token:
            start_raw, stop_raw = token.split("-", 1)
            start = int(start_raw)
            stop = int(stop_raw)
            if stop < start:
                raise ValueError(f"Invalid episode range: {token}")
            candidates = range(start, stop + 1)
        else:
            candidates = [int(token)]
        for episode_index in candidates:
            if episode_index < 0 or episode_index >= total_episodes:
                raise ValueError(f"Episode index out of range: {episode_index} (total={total_episodes})")
            if episode_index not in seen:
                selected.append(episode_index)
                seen.add(episode_index)
    if not selected:
        raise ValueError("No episodes selected.")
    return selected


def suggest_next_repo_id(
    dataset_root: str | Path | Mapping[str, Any] | None = None,
    *,
    namespace: str = "jin",
    date_prefix: str | None = None,
) -> str:
    """Return the next date-sequenced repo id, e.g. jin/20260901_9."""
    if isinstance(dataset_root, Mapping):
        namespace = str(dataset_root.get("namespace") or namespace)
        date_prefix = str(dataset_root.get("date_prefix") or date_prefix or "")
        root = _dataset_root_from_payload(dataset_root)
    else:
        root = Path(dataset_root or DEFAULT_DATASET_ROOT).expanduser()
    prefix = str(date_prefix or datetime.now().strftime("%Y%m%d"))
    ns_dir = root / namespace
    max_suffix = 0
    if ns_dir.is_dir():
        for child in ns_dir.iterdir():
            if not child.is_dir():
                continue
            match = re.fullmatch(rf"{re.escape(prefix)}_(\d+)", child.name)
            if match:
                max_suffix = max(max_suffix, int(match.group(1)))
    return f"{namespace}/{prefix}_{max_suffix + 1}"


def list_datasets(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """List local LeRobot datasets under a Hugging Face-style dataset root."""
    data = dict(payload or {})
    root = _dataset_root_from_payload(data)
    namespace = str(data.get("namespace") or "").strip()
    date_prefix = str(data.get("date_prefix") or "").strip() or None
    datasets: list[dict[str, Any]] = []
    if root.is_dir():
        for info_path in root.glob("*/*/meta/info.json"):
            dataset_path = info_path.parents[1]
            repo_id = dataset_path.relative_to(root).as_posix()
            if namespace and not repo_id.startswith(f"{namespace}/"):
                continue
            if date_prefix and not dataset_path.name.startswith(f"{date_prefix}_"):
                continue
            info = _read_json(info_path, default={})
            sidecar_root = dataset_path / "sidecar"
            sidecars = sorted(child.name for child in sidecar_root.iterdir() if child.is_dir()) if sidecar_root.is_dir() else []
            datasets.append(
                {
                    "repo_id": repo_id,
                    "path": str(dataset_path),
                    "name": dataset_path.name,
                    "namespace": dataset_path.parent.name,
                    "total_episodes": _safe_int(info.get("total_episodes"), 0),
                    "total_frames": _safe_int(info.get("total_frames"), 0),
                    "fps": _safe_int(info.get("fps"), 0),
                    "codebase_version": str(info.get("codebase_version") or ""),
                    "sidecars": sidecars,
                }
            )
    datasets.sort(key=lambda row: _natural_key(str(row["repo_id"])))
    ns_for_suggestion = namespace or "jin"
    return {
        "ok": True,
        "tool": "lerobot.dataset_manage.list",
        "dataset_root": str(root),
        "datasets": datasets,
        "suggested_repo_id": suggest_next_repo_id(root, namespace=ns_for_suggestion, date_prefix=date_prefix),
    }


def merge_datasets(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Merge selected episodes from multiple v2.1 datasets into a new dataset."""
    data = dict(payload or {})
    root = _dataset_root_from_payload(data)
    source_specs = list(data.get("sources") or [])
    if len(source_specs) < 2:
        raise ValueError("merge requires at least two sources.")
    sources_and_episodes = _resolve_sources(root, source_specs)
    output_repo_id, output_path = _resolve_output(data, root)
    result = _materialize_dataset(
        operation="merge",
        dataset_root=root,
        output_repo_id=output_repo_id,
        output_path=output_path,
        sources_and_episodes=sources_and_episodes,
        overwrite=bool(data.get("overwrite", False)),
        request_payload=data,
    )
    result["tool"] = "lerobot.dataset_manage.merge"
    return result


def split_dataset(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Split one dataset into one or more newly materialized datasets."""
    data = dict(payload or {})
    root = _dataset_root_from_payload(data)
    source_data = data.get("source") if isinstance(data.get("source"), Mapping) else data
    source = _load_source_dataset(root, source_data)
    splits = list(data.get("splits") or [])
    if not splits:
        raise ValueError("split requires at least one split spec.")
    outputs: list[dict[str, Any]] = []
    for index, split in enumerate(splits):
        if not isinstance(split, Mapping):
            raise ValueError("split entries must be objects.")
        name = str(split.get("name") or f"split_{index}").strip()
        episodes = parse_episode_range(split.get("episode_range") or split.get("episodes") or "all", _source_episode_total(source))
        split_payload = dict(data)
        split_payload.update(split)
        split_payload.setdefault("output_repo_id", _default_split_repo_id(source.repo_id, name))
        output_repo_id, output_path = _resolve_output(split_payload, root)
        outputs.append(
            _materialize_dataset(
                operation="split",
                dataset_root=root,
                output_repo_id=output_repo_id,
                output_path=output_path,
                sources_and_episodes=[(source, episodes)],
                overwrite=bool(data.get("overwrite", False) or split.get("overwrite", False)),
                request_payload={**data, "split": dict(split)},
            )
        )
    return {
        "ok": all(item.get("ok") for item in outputs),
        "tool": "lerobot.dataset_manage.split",
        "status": "completed",
        "outputs": outputs,
    }


def delete_episodes(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create a compacted copy after deleting selected source episodes."""
    data = dict(payload or {})
    root = _dataset_root_from_payload(data)
    source_data = data.get("source") if isinstance(data.get("source"), Mapping) else data
    source = _load_source_dataset(root, source_data)
    total = _source_episode_total(source)
    delete_selection = parse_episode_range(data.get("delete_episode_range") or data.get("episode_range") or data.get("episodes"), total)
    delete_set = set(delete_selection)
    keep_episodes = [episode_index for episode_index in range(total) if episode_index not in delete_set]
    if not keep_episodes:
        raise ValueError("delete would remove every episode.")
    output_repo_id, output_path = _resolve_output(data, root, default_repo_id=_default_delete_repo_id(source.repo_id))
    result = _materialize_dataset(
        operation="delete_compact",
        dataset_root=root,
        output_repo_id=output_repo_id,
        output_path=output_path,
        sources_and_episodes=[(source, keep_episodes)],
        overwrite=bool(data.get("overwrite", False)),
        request_payload={**data, "deleted_episodes": delete_selection},
    )
    result["tool"] = "lerobot.dataset_manage.delete"
    result["deleted_episodes"] = delete_selection
    return result


def verify_dataset_integrity(path: str | Path) -> dict[str, Any]:
    """Perform local structural checks for a materialized LeRobot v2.1 dataset."""
    dataset_path = Path(path).expanduser()
    errors: list[str] = []
    warnings: list[str] = []
    info = _read_json(dataset_path / "meta" / "info.json", default={})
    episodes = _read_jsonl(dataset_path / "meta" / "episodes.jsonl")
    stats = _read_jsonl(dataset_path / "meta" / "episodes_stats.jsonl")
    features = info.get("features") if isinstance(info.get("features"), dict) else {}
    video_keys = _video_keys(features)
    expected_episodes = _safe_int(info.get("total_episodes"), len(episodes))
    expected_frames = _safe_int(info.get("total_frames"), 0)
    if len(episodes) != expected_episodes:
        errors.append(f"episodes.jsonl count {len(episodes)} != total_episodes {expected_episodes}")
    if len(stats) and len(stats) != expected_episodes:
        warnings.append(f"episodes_stats.jsonl count {len(stats)} != total_episodes {expected_episodes}")
    total_frames = 0
    for expected_ep, episode in enumerate(episodes):
        episode_index = _safe_int(episode.get("episode_index"), -1)
        if episode_index != expected_ep:
            errors.append(f"episode row order mismatch: row {expected_ep} has episode_index {episode_index}")
        parquet_path = _episode_data_path(dataset_path, expected_ep, _safe_int(info.get("chunks_size"), 1000, minimum=1))
        if not parquet_path.is_file():
            errors.append(f"missing parquet: {parquet_path}")
            continue
        table = pq.read_table(parquet_path)
        length = table.num_rows
        total_frames += length
        declared_length = _safe_int(episode.get("length"), length)
        if length != declared_length:
            errors.append(f"episode {expected_ep} parquet rows {length} != metadata length {declared_length}")
        _check_reindexed_column(table, "episode_index", [expected_ep] * length, errors, expected_ep)
        _check_reindexed_column(table, "frame_index", list(range(length)), errors, expected_ep)
        for video_key in video_keys:
            video_path = _episode_video_path(dataset_path, expected_ep, video_key, _safe_int(info.get("chunks_size"), 1000, minimum=1))
            if not video_path.is_file():
                errors.append(f"missing video: {video_path}")
        depth_root = dataset_path / "sidecar" / "depth_raw"
        if depth_root.is_dir():
            for camera_dir in [child for child in depth_root.iterdir() if child.is_dir()]:
                raw_dir = camera_dir / f"episode_{expected_ep:06d}"
                if raw_dir.is_dir():
                    raw_count = len(list(raw_dir.glob("*.png")))
                    if raw_count != length:
                        warnings.append(f"raw depth {camera_dir.name} episode {expected_ep} frame count {raw_count} != {length}")
    if total_frames != expected_frames:
        errors.append(f"parquet frame total {total_frames} != total_frames {expected_frames}")
    return {
        "ok": not errors,
        "path": str(dataset_path),
        "total_episodes": len(episodes),
        "total_frames": total_frames,
        "video_keys": video_keys,
        "errors": errors,
        "warnings": warnings,
    }


def _materialize_dataset(
    *,
    operation: str,
    dataset_root: Path,
    output_repo_id: str,
    output_path: Path,
    sources_and_episodes: list[tuple[SourceDataset, list[int]]],
    overwrite: bool,
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not sources_and_episodes:
        raise ValueError("No source episodes selected.")
    output_path = output_path.expanduser()
    backup_path: Path | None = None
    if output_path.exists():
        if not overwrite:
            raise FileExistsError(f"Output dataset already exists: {output_path}")
        backup_path = _next_backup_path(output_path)
        output_path.rename(backup_path)
        _redirect_overwritten_sources(sources_and_episodes, output_path, backup_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.parent / f".{output_path.name}.tmp-{uuid.uuid4().hex}"
    if tmp_path.exists():
        shutil.rmtree(tmp_path)

    warnings: list[str] = []
    mappings: list[EpisodeMapping] = []
    frame_cursor = 0
    first_source = sources_and_episodes[0][0]
    source_task_maps = _build_task_maps(sources_and_episodes)
    info = copy.deepcopy(first_source.info)
    chunks_size = _safe_int(info.get("chunks_size"), 1000, minimum=1)
    try:
        (tmp_path / "meta").mkdir(parents=True, exist_ok=True)
        task_rows = _task_rows_from_maps(source_task_maps)
        _write_jsonl(tmp_path / "meta" / "tasks.jsonl", task_rows)
        episode_rows: list[dict[str, Any]] = []
        stats_rows: list[dict[str, Any]] = []
        new_episode_index = 0
        for source, episode_indices in sources_and_episodes:
            for old_episode_index in episode_indices:
                table = pq.read_table(_episode_data_path(source.path, old_episode_index, source.chunks_size))
                frame_count = table.num_rows
                mapping = EpisodeMapping(
                    source=source,
                    old_episode_index=old_episode_index,
                    new_episode_index=new_episode_index,
                    frame_count=frame_count,
                )
                mappings.append(mapping)
                reindexed = _reindex_table(
                    table,
                    source=source,
                    new_episode_index=new_episode_index,
                    frame_start=frame_cursor,
                    task_index_map=source_task_maps[str(source.path)]["old_to_new"],
                )
                dst_parquet = _episode_data_path(tmp_path, new_episode_index, chunks_size)
                dst_parquet.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(reindexed, dst_parquet)
                _copy_videos(source, tmp_path, old_episode_index, new_episode_index, first_source.video_keys, chunks_size, warnings)
                episode_rows.append(_episode_metadata_row(source, old_episode_index, new_episode_index, frame_count, source_task_maps))
                stats_rows.append(_episode_stats_row(source, old_episode_index, new_episode_index))
                frame_cursor += frame_count
                new_episode_index += 1

        info.update(
            {
                "repo_id": output_repo_id,
                "total_episodes": len(mappings),
                "total_frames": frame_cursor,
                "total_videos": len(mappings) * len(first_source.video_keys),
                "total_chunks": max(1, (len(mappings) + chunks_size - 1) // chunks_size),
                "chunks_size": chunks_size,
                "splits": {"train": f"0:{len(mappings)}"},
                "data_path": info.get("data_path") or "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
                "video_path": info.get("video_path") or "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
            }
        )
        _write_json(tmp_path / "meta" / "info.json", info)
        _write_jsonl(tmp_path / "meta" / "episodes.jsonl", episode_rows)
        _write_jsonl(tmp_path / "meta" / "episodes_stats.jsonl", stats_rows)
        _copy_sidecars(mappings, tmp_path, output_path, warnings)
        _write_pipeline_metadata(tmp_path, output_repo_id, output_path, operation, request_payload, mappings)
        integrity = verify_dataset_integrity(tmp_path)
        if not integrity["ok"]:
            raise ValueError("Output dataset integrity check failed: " + "; ".join(integrity["errors"]))
        tmp_path.rename(output_path)
    except Exception:
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        if backup_path is not None and backup_path.exists() and not output_path.exists():
            backup_path.rename(output_path)
        raise

    integrity = verify_dataset_integrity(output_path)
    return {
        "ok": integrity["ok"],
        "status": "completed" if integrity["ok"] else "failed",
        "operation": operation,
        "dataset_root": str(dataset_root),
        "output_repo_id": output_repo_id,
        "output_path": str(output_path),
        "backup_path": str(backup_path) if backup_path is not None else "",
        "total_episodes": len(mappings),
        "total_frames": frame_cursor,
        "sources": _source_summary(sources_and_episodes),
        "episode_mapping": [
            {
                "source_repo_id": mapping.source.repo_id,
                "source_path": str(mapping.source.path),
                "old_episode_index": mapping.old_episode_index,
                "new_episode_index": mapping.new_episode_index,
                "frame_count": mapping.frame_count,
            }
            for mapping in mappings
        ],
        "integrity": integrity,
        "warnings": warnings + list(integrity.get("warnings") or []),
    }


def _build_task_maps(sources_and_episodes: list[tuple[SourceDataset, list[int]]]) -> dict[str, dict[str, Any]]:
    task_name_to_new: dict[str, int] = {}
    maps: dict[str, dict[str, Any]] = {}
    for source, _episodes in sources_and_episodes:
        old_to_new: dict[int, int] = {}
        for old_index, task_name in sorted(source.tasks_by_index.items()):
            if task_name not in task_name_to_new:
                task_name_to_new[task_name] = len(task_name_to_new)
            old_to_new[old_index] = task_name_to_new[task_name]
        if not old_to_new:
            task_name = "default"
            if task_name not in task_name_to_new:
                task_name_to_new[task_name] = len(task_name_to_new)
            old_to_new[0] = task_name_to_new[task_name]
        maps[str(source.path)] = {
            "source": source,
            "old_to_new": old_to_new,
            "task_name_to_new": task_name_to_new,
        }
    return maps


def _task_rows_from_maps(source_task_maps: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    task_name_to_new: dict[str, int] = {}
    for item in source_task_maps.values():
        task_name_to_new.update(item["task_name_to_new"])
    return [{"task_index": index, "task": task} for task, index in sorted(task_name_to_new.items(), key=lambda pair: pair[1])]


def _episode_metadata_row(
    source: SourceDataset,
    old_episode_index: int,
    new_episode_index: int,
    frame_count: int,
    source_task_maps: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    row = copy.deepcopy(source.episodes.get(old_episode_index) or {})
    row["episode_index"] = new_episode_index
    row["length"] = frame_count
    tasks = row.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        tasks = [source.tasks_by_index.get(0, "default")]
    row["tasks"] = tasks
    task_map = source_task_maps[str(source.path)]["old_to_new"]
    if "task_index" in row:
        row["task_index"] = task_map.get(_safe_int(row["task_index"], 0), 0)
    return row


def _episode_stats_row(source: SourceDataset, old_episode_index: int, new_episode_index: int) -> dict[str, Any]:
    row = copy.deepcopy(source.stats.get(old_episode_index) or {"stats": {}})
    row["episode_index"] = new_episode_index
    return row


def _reindex_table(
    table: pa.Table,
    *,
    source: SourceDataset,
    new_episode_index: int,
    frame_start: int,
    task_index_map: dict[int, int],
) -> pa.Table:
    frame_count = table.num_rows
    table = _replace_or_append_column(table, "episode_index", [new_episode_index] * frame_count, pa.int64())
    table = _replace_or_append_column(table, "frame_index", list(range(frame_count)), pa.int64())
    table = _replace_or_append_column(table, "index", list(range(frame_start, frame_start + frame_count)), pa.int64())
    if "task_index" in table.column_names:
        task_values = [_safe_int(value, 0) for value in table.column("task_index").to_pylist()]
        table = _replace_or_append_column(table, "task_index", [task_index_map.get(value, 0) for value in task_values], pa.int64())
    elif source.tasks_by_index:
        table = _replace_or_append_column(table, "task_index", [0] * frame_count, pa.int64())
    return table


def _replace_or_append_column(table: pa.Table, name: str, values: Iterable[Any], fallback_type: pa.DataType) -> pa.Table:
    if name in table.column_names:
        index = table.column_names.index(name)
        field = table.schema.field(name)
        return table.set_column(index, field, pa.array(list(values), type=field.type))
    return table.append_column(name, pa.array(list(values), type=fallback_type))


def _copy_videos(
    source: SourceDataset,
    output_path: Path,
    old_episode_index: int,
    new_episode_index: int,
    video_keys: list[str],
    chunks_size: int,
    warnings: list[str],
) -> None:
    for video_key in video_keys:
        src = _episode_video_path(source.path, old_episode_index, video_key, source.chunks_size)
        dst = _episode_video_path(output_path, new_episode_index, video_key, chunks_size)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            shutil.copy2(src, dst)
        else:
            warnings.append(f"missing video for {source.repo_id} episode {old_episode_index}: {video_key}")


def _copy_sidecars(mappings: list[EpisodeMapping], tmp_path: Path, final_output_path: Path, warnings: list[str]) -> None:
    by_source: dict[str, list[EpisodeMapping]] = {}
    source_by_path: dict[str, SourceDataset] = {}
    for mapping in mappings:
        key = str(mapping.source.path)
        by_source.setdefault(key, []).append(mapping)
        source_by_path[key] = mapping.source
    for source_key, source_mappings in by_source.items():
        source = source_by_path[source_key]
        sidecar_root = source.path / "sidecar"
        if not sidecar_root.is_dir():
            continue
        episode_map = {mapping.old_episode_index: mapping.new_episode_index for mapping in source_mappings}
        _copy_depth_raw_sidecar(source, episode_map, tmp_path, final_output_path, warnings)
        _copy_attempts_sidecar(source, episode_map, tmp_path, final_output_path, warnings)
        _copy_isaac_mirror_sidecar(source, episode_map, tmp_path, final_output_path)
        for sidecar in sorted(child for child in sidecar_root.iterdir() if child.is_dir() and child.name not in HANDLED_SIDECARS):
            _copy_generic_sidecar(source, sidecar, episode_map, tmp_path / "sidecar" / sidecar.name, final_output_path, warnings)


def _copy_depth_raw_sidecar(
    source: SourceDataset,
    episode_map: dict[int, int],
    output_path: Path,
    final_output_path: Path,
    warnings: list[str],
) -> None:
    src_root = source.path / "sidecar" / "depth_raw"
    if not src_root.is_dir():
        return
    dst_root = output_path / "sidecar" / "depth_raw"
    dst_root.mkdir(parents=True, exist_ok=True)
    for child in src_root.iterdir():
        if child.is_file():
            _copy_rewritten_file(child, dst_root / child.name, source.path, final_output_path, None, None)
            continue
        if not child.is_dir():
            continue
        for old_episode_index, new_episode_index in episode_map.items():
            src_episode = child / f"episode_{old_episode_index:06d}"
            dst_episode = dst_root / child.name / f"episode_{new_episode_index:06d}"
            if src_episode.is_dir():
                _copy_episode_tree(src_episode, dst_episode, source.path, final_output_path, old_episode_index, new_episode_index)
            else:
                warnings.append(f"missing raw depth sidecar for {source.repo_id} {child.name} episode {old_episode_index}")


def _copy_attempts_sidecar(
    source: SourceDataset,
    episode_map: dict[int, int],
    output_path: Path,
    final_output_path: Path,
    warnings: list[str],
) -> None:
    src_root = source.path / "sidecar" / "attempts"
    if not src_root.is_dir():
        return
    dst_root = output_path / "sidecar" / "attempts"
    dst_root.mkdir(parents=True, exist_ok=True)
    for old_episode_index, new_episode_index in episode_map.items():
        src_episode = src_root / f"episode_{old_episode_index:03d}"
        dst_episode = dst_root / f"episode_{new_episode_index:03d}"
        if src_episode.is_dir():
            _copy_episode_tree(src_episode, dst_episode, source.path, final_output_path, old_episode_index, new_episode_index)
        else:
            warnings.append(f"missing attempts sidecar for {source.repo_id} episode {old_episode_index}")
    manifest_rows = _filtered_reindexed_jsonl(src_root / "manifest.jsonl", episode_map, source.path, final_output_path)
    if manifest_rows:
        _append_jsonl(dst_root / "manifest.jsonl", manifest_rows)


def _copy_isaac_mirror_sidecar(
    source: SourceDataset,
    episode_map: dict[int, int],
    output_path: Path,
    final_output_path: Path,
) -> None:
    src_root = source.path / "sidecar" / "isaac_mirror"
    if not src_root.is_dir():
        return
    dst_root = output_path / "sidecar" / "isaac_mirror"
    dst_root.mkdir(parents=True, exist_ok=True)
    prefix = _safe_source_label(source.repo_id)
    for src_file in sorted(src_root.glob("*.jsonl")):
        rows = _filtered_reindexed_jsonl(src_file, episode_map, source.path, final_output_path)
        if rows:
            _write_jsonl(dst_root / f"{prefix}__{src_file.name}", rows)


def _copy_generic_sidecar(
    source: SourceDataset,
    sidecar_root: Path,
    episode_map: dict[int, int],
    output_root: Path,
    final_output_path: Path,
    warnings: list[str],
) -> None:
    copied_episode_dirs: set[Path] = set()
    for directory in sorted((path for path in sidecar_root.rglob("*") if path.is_dir()), key=lambda path: len(path.parts)):
        match = EPISODE_TOKEN_RE.fullmatch(directory.name)
        if not match:
            continue
        old_episode_index = int(match.group(1))
        if old_episode_index not in episode_map:
            continue
        width = len(match.group(1))
        new_episode_index = episode_map[old_episode_index]
        rel_parent = directory.parent.relative_to(sidecar_root)
        dst = output_root / rel_parent / f"episode_{new_episode_index:0{width}d}"
        _copy_episode_tree(directory, dst, source.path, final_output_path, old_episode_index, new_episode_index)
        copied_episode_dirs.add(directory)

    for src_file in sorted(path for path in sidecar_root.rglob("*") if path.is_file()):
        if any(parent in copied_episode_dirs for parent in src_file.parents):
            continue
        rel = src_file.relative_to(sidecar_root)
        dst = output_root / rel
        if src_file.suffix == ".jsonl":
            rows = _filtered_reindexed_jsonl(src_file, episode_map, source.path, final_output_path)
            if rows:
                _append_jsonl(dst, rows)
        elif src_file.suffix == ".json":
            filtered = _filtered_reindexed_json(src_file, episode_map, source.path, final_output_path)
            if filtered is not None:
                _write_json(dst, filtered)
            elif not dst.exists():
                _copy_rewritten_file(src_file, dst, source.path, final_output_path, None, None)
        elif not dst.exists():
            _copy_rewritten_file(src_file, dst, source.path, final_output_path, None, None)
        else:
            warnings.append(f"skipped duplicate generic sidecar file: {dst}")


def _copy_episode_tree(
    src: Path,
    dst: Path,
    source_path: Path,
    output_path: Path,
    old_episode_index: int,
    new_episode_index: int,
) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    _rename_rewritten_paths(dst, old_episode_index, new_episode_index)
    _rewrite_text_tree(dst, source_path, output_path, old_episode_index, new_episode_index)


def _rename_rewritten_paths(root: Path, old_episode_index: int, new_episode_index: int) -> None:
    paths = sorted([path for path in root.rglob("*")], key=lambda item: len(item.parts), reverse=True)
    for path in paths:
        new_name = _rewrite_episode_string(path.name, old_episode_index, new_episode_index)
        if new_name == path.name:
            continue
        target = path.with_name(new_name)
        if not target.exists():
            path.rename(target)


def _rewrite_text_tree(root: Path, source_path: Path, output_path: Path, old_episode_index: int, new_episode_index: int) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_REWRITE_SUFFIXES:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rewritten = _rewrite_episode_string(raw.replace(str(source_path), str(output_path)), old_episode_index, new_episode_index)
        if rewritten != raw:
            path.write_text(rewritten, encoding="utf-8")


def _copy_rewritten_file(
    src: Path,
    dst: Path,
    source_path: Path,
    output_path: Path,
    old_episode_index: int | None,
    new_episode_index: int | None,
) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() not in TEXT_REWRITE_SUFFIXES:
        shutil.copy2(src, dst)
        return
    try:
        raw = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        shutil.copy2(src, dst)
        return
    rewritten = raw.replace(str(source_path), str(output_path))
    if old_episode_index is not None and new_episode_index is not None:
        rewritten = _rewrite_episode_string(rewritten, old_episode_index, new_episode_index)
    dst.write_text(rewritten, encoding="utf-8")


def _filtered_reindexed_jsonl(
    path: Path,
    episode_map: dict[int, int],
    source_path: Path,
    output_path: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        old_episode_index = _episode_index_from_obj(obj)
        if old_episode_index is None or old_episode_index not in episode_map:
            continue
        rows.append(_rewrite_json_obj(obj, source_path, output_path, old_episode_index, episode_map[old_episode_index]))
    return rows


def _filtered_reindexed_json(
    path: Path,
    episode_map: dict[int, int],
    source_path: Path,
    output_path: Path,
) -> Any | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    old_episode_index = _episode_index_from_obj(obj)
    if old_episode_index is not None:
        if old_episode_index not in episode_map:
            return None
        return _rewrite_json_obj(obj, source_path, output_path, old_episode_index, episode_map[old_episode_index])
    if isinstance(obj, list):
        rows = []
        for item in obj:
            item_ep = _episode_index_from_obj(item)
            if item_ep is not None and item_ep in episode_map:
                rows.append(_rewrite_json_obj(item, source_path, output_path, item_ep, episode_map[item_ep]))
        return rows if rows else None
    return None


def _rewrite_json_obj(obj: Any, source_path: Path, output_path: Path, old_episode_index: int, new_episode_index: int) -> Any:
    if isinstance(obj, dict):
        rewritten = {key: _rewrite_json_obj(value, source_path, output_path, old_episode_index, new_episode_index) for key, value in obj.items()}
        for key in ["episode_index", "record_episode_index", "episode"]:
            if key in rewritten and _safe_int(rewritten[key], -1) == old_episode_index:
                rewritten[key] = new_episode_index
        return rewritten
    if isinstance(obj, list):
        return [_rewrite_json_obj(item, source_path, output_path, old_episode_index, new_episode_index) for item in obj]
    if isinstance(obj, str):
        return _rewrite_episode_string(obj.replace(str(source_path), str(output_path)), old_episode_index, new_episode_index)
    return obj


def _rewrite_episode_string(value: str, old_episode_index: int, new_episode_index: int) -> str:
    rewritten = value
    for width in (3, 6):
        rewritten = rewritten.replace(f"episode_{old_episode_index:0{width}d}", f"episode_{new_episode_index:0{width}d}")
        rewritten = rewritten.replace(f"_ep{old_episode_index:0{width}d}", f"_ep{new_episode_index:0{width}d}")
    return rewritten


def _episode_index_from_obj(obj: Any) -> int | None:
    if not isinstance(obj, Mapping):
        return None
    for key in ("episode_index", "record_episode_index", "episode"):
        if key in obj:
            try:
                return int(obj[key])
            except (TypeError, ValueError):
                return None
    return None


def _write_pipeline_metadata(
    output_path: Path,
    output_repo_id: str,
    final_output_path: Path,
    operation: str,
    request_payload: Mapping[str, Any],
    mappings: list[EpisodeMapping],
) -> None:
    first_pipeline = mappings[0].source.path / "meta" / "atr_pipeline.json" if mappings else None
    pipeline = _read_json(first_pipeline, default={}) if first_pipeline else {}
    pipeline.update(
        {
            "dataset_repo_id": output_repo_id,
            "dataset_path": str(final_output_path),
            "dataset_manage_operation": operation,
        }
    )
    _write_json(output_path / "meta" / "atr_pipeline.json", pipeline)
    audit = {
        "schema": "atr.lerobot.dataset_manage.v1",
        "operation": operation,
        "output_repo_id": output_repo_id,
        "output_path": str(final_output_path),
        "total_episodes": len(mappings),
        "total_frames": sum(mapping.frame_count for mapping in mappings),
        "request": _jsonable(request_payload),
        "episode_mapping": [
            {
                "source_repo_id": mapping.source.repo_id,
                "source_path": str(mapping.source.path),
                "old_episode_index": mapping.old_episode_index,
                "new_episode_index": mapping.new_episode_index,
                "frame_count": mapping.frame_count,
            }
            for mapping in mappings
        ],
    }
    _write_json(output_path / "sidecar" / "dataset_manage" / "manifest.json", audit)


def _resolve_sources(root: Path, source_specs: list[Any]) -> list[tuple[SourceDataset, list[int]]]:
    resolved: list[tuple[SourceDataset, list[int]]] = []
    for raw_spec in source_specs:
        if not isinstance(raw_spec, Mapping):
            raise ValueError("source entries must be objects.")
        source = _load_source_dataset(root, raw_spec)
        episodes = parse_episode_range(raw_spec.get("episode_range") or raw_spec.get("episodes") or "all", _source_episode_total(source))
        _validate_selected_episodes(source, episodes)
        resolved.append((source, episodes))
    return resolved


def _load_source_dataset(root: Path, spec: Mapping[str, Any]) -> SourceDataset:
    path = _resolve_dataset_path(root, spec)
    info_path = path / "meta" / "info.json"
    if not info_path.is_file():
        raise FileNotFoundError(f"Missing LeRobot dataset metadata: {info_path}")
    info = _read_json(info_path, default={})
    episodes = {
        _safe_int(row.get("episode_index"), index): row
        for index, row in enumerate(_read_jsonl(path / "meta" / "episodes.jsonl"))
        if isinstance(row, dict)
    }
    stats = {
        _safe_int(row.get("episode_index"), index): row
        for index, row in enumerate(_read_jsonl(path / "meta" / "episodes_stats.jsonl"))
        if isinstance(row, dict)
    }
    tasks_by_index = {
        _safe_int(row.get("task_index"), index): str(row.get("task") or f"task_{index}")
        for index, row in enumerate(_read_jsonl(path / "meta" / "tasks.jsonl"))
        if isinstance(row, dict)
    }
    repo_id = str(spec.get("dataset_repo_id") or spec.get("repo_id") or _repo_id_from_path(root, path))
    features = info.get("features") if isinstance(info.get("features"), dict) else {}
    return SourceDataset(
        repo_id=repo_id,
        path=path,
        info=info,
        episodes=episodes,
        stats=stats,
        tasks_by_index=tasks_by_index,
        video_keys=_video_keys(features),
        chunks_size=_safe_int(info.get("chunks_size"), 1000, minimum=1),
    )


def _validate_selected_episodes(source: SourceDataset, episodes: list[int]) -> None:
    for episode_index in episodes:
        parquet_path = _episode_data_path(source.path, episode_index, source.chunks_size)
        if episode_index not in source.episodes:
            raise ValueError(f"{source.repo_id} has no metadata for episode {episode_index}")
        if not parquet_path.is_file():
            raise FileNotFoundError(f"Missing parquet for {source.repo_id} episode {episode_index}: {parquet_path}")


def _resolve_dataset_path(root: Path, spec: Mapping[str, Any]) -> Path:
    raw_path = str(spec.get("dataset_path") or "").strip()
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    repo_id = str(spec.get("dataset_repo_id") or spec.get("repo_id") or "").strip()
    if not repo_id:
        raise ValueError("dataset_repo_id or dataset_path is required.")
    repo_as_path = Path(repo_id).expanduser()
    if repo_as_path.is_absolute():
        return repo_as_path.resolve()
    return (root / repo_id).resolve()


def _resolve_output(
    payload: Mapping[str, Any],
    root: Path,
    *,
    default_repo_id: str | None = None,
) -> tuple[str, Path]:
    raw_path = str(payload.get("output_path") or "").strip()
    output_repo_id = str(payload.get("output_repo_id") or payload.get("repo_id") or default_repo_id or "").strip()
    if not output_repo_id:
        output_repo_id = suggest_next_repo_id(
            root,
            namespace=str(payload.get("namespace") or "jin"),
            date_prefix=str(payload.get("date_prefix") or "").strip() or None,
        )
    if raw_path:
        output_path = Path(raw_path).expanduser().resolve()
        if not output_repo_id:
            output_repo_id = _repo_id_from_path(root, output_path)
    else:
        output_path = (root / output_repo_id).resolve()
    return output_repo_id, output_path


def _next_backup_path(path: Path) -> Path:
    first = path.with_name(f"{path.name}_backup")
    if not first.exists():
        return first
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}_backup_{index:03d}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"No available backup path for {path}")


def _redirect_overwritten_sources(
    sources_and_episodes: list[tuple[SourceDataset, list[int]]],
    output_path: Path,
    backup_path: Path,
) -> None:
    output_resolved = output_path.resolve()
    for source, _episodes in sources_and_episodes:
        if source.path.resolve() == output_resolved:
            source.path = backup_path.resolve()


def _dataset_root_from_payload(payload: Mapping[str, Any]) -> Path:
    return Path(str(payload.get("dataset_root") or DEFAULT_DATASET_ROOT)).expanduser().resolve()


def _repo_id_from_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _source_episode_total(source: SourceDataset) -> int:
    declared = _safe_int(source.info.get("total_episodes"), 0, minimum=0)
    if declared:
        return declared
    return max(source.episodes.keys(), default=-1) + 1


def _default_split_repo_id(source_repo_id: str, name: str) -> str:
    namespace, _, dataset_name = source_repo_id.partition("/")
    if not dataset_name:
        namespace, dataset_name = "jin", namespace
    return f"{namespace}/{dataset_name}_{name}"


def _default_delete_repo_id(source_repo_id: str) -> str:
    namespace, _, dataset_name = source_repo_id.partition("/")
    if not dataset_name:
        namespace, dataset_name = "jin", namespace
    return f"{namespace}/{dataset_name}_compact"


def _video_keys(features: Mapping[str, Any]) -> list[str]:
    keys = []
    for key, value in features.items():
        if isinstance(value, Mapping) and str(value.get("dtype") or "").lower() == "video":
            keys.append(str(key))
    return sorted(keys)


def _episode_data_path(dataset_path: Path, episode_index: int, chunks_size: int) -> Path:
    chunk = episode_index // max(1, chunks_size)
    return dataset_path / "data" / f"chunk-{chunk:03d}" / f"episode_{episode_index:06d}.parquet"


def _episode_video_path(dataset_path: Path, episode_index: int, video_key: str, chunks_size: int) -> Path:
    chunk = episode_index // max(1, chunks_size)
    return dataset_path / "videos" / f"chunk-{chunk:03d}" / video_key / f"episode_{episode_index:06d}.mp4"


def _check_reindexed_column(table: pa.Table, name: str, expected: list[int], errors: list[str], episode_index: int) -> None:
    if name not in table.column_names:
        errors.append(f"episode {episode_index} missing column {name}")
        return
    actual = table.column(name).to_pylist()
    if actual != expected:
        errors.append(f"episode {episode_index} {name} mismatch")


def _source_summary(sources_and_episodes: list[tuple[SourceDataset, list[int]]]) -> list[dict[str, Any]]:
    return [
        {
            "repo_id": source.repo_id,
            "path": str(source.path),
            "episode_count": len(episodes),
            "episodes": episodes,
        }
        for source, episodes in sources_and_episodes
    ]


def _read_json(path: Path | None, *, default: Any) -> Any:
    if path is None or not path.is_file():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _safe_int(value: Any, fallback: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _safe_source_label(repo_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", repo_id).strip("_") or "source"


def _natural_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value
