"""Shared multimodal evidence and locator compilation for Equipment Skills."""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont

from backends.llm_backend import LLMImageInput


@dataclass(slots=True)
class SkillVisionEvidence:
    images: list[LLMImageInput]
    steps: list[dict[str, Any]]
    timeline: list[dict[str, Any]]


@dataclass(slots=True)
class TemporalStoryboardChunk:
    chunk_id: str
    path: str
    image: LLMImageInput
    tiles: list[dict[str, Any]]
    start_ms: int
    end_ms: int


@dataclass(slots=True)
class TemporalStoryboardBundle:
    chunks: list[TemporalStoryboardChunk]
    overview_images: list[LLMImageInput]
    overview_paths: list[str]
    source_frame_count: int
    covered_frame_ids: list[str]


def _storyboard_event(events: list[dict[str, Any]], at_ms: int, tolerance_ms: int = 250) -> dict[str, Any]:
    nearby = [item for item in events if abs(int(item.get("at_ms", 0)) - at_ms) <= tolerance_ms]
    if not nearby:
        return {}
    event = min(nearby, key=lambda item: abs(int(item.get("at_ms", 0)) - at_ms))
    return _event_action_summary(event) | {"at_ms": max(0, int(event.get("at_ms", 0)))}


def _storyboard_image(
    tiles: list[tuple[Image.Image, dict[str, Any]]],
    *,
    columns: int,
    tile_width: int = 320,
    tile_height: int = 180,
) -> Image.Image:
    rows = max(1, (len(tiles) + columns - 1) // columns)
    label_height = 28
    gap = 8
    canvas = Image.new(
        "RGB",
        (columns * tile_width + (columns + 1) * gap, rows * (tile_height + label_height) + (rows + 1) * gap),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    role_colors = {
        "periodic": "#1d4ed8",
        "pre_action": "#f59e0b",
        "event": "#dc2626",
        "post_action": "#16a34a",
        "boundary": "#7c3aed",
        "exception": "#be123c",
    }
    for index, (source, metadata) in enumerate(tiles):
        row, column = divmod(index, columns)
        left = gap + column * tile_width
        top = gap + row * (tile_height + label_height)
        frame = source.convert("RGB").copy()
        frame.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
        frame_left = left + (tile_width - frame.width) // 2
        frame_top = top + (tile_height - frame.height) // 2
        canvas.paste(frame, (frame_left, frame_top))
        role = str(metadata.get("role") or "periodic")
        color = role_colors.get(role, role_colors["periodic"])
        draw.rectangle((left, top, left + tile_width - 1, top + tile_height - 1), outline=color, width=3)
        event = metadata.get("event") if isinstance(metadata.get("event"), dict) else {}
        event_label = str(event.get("kind") or "")
        label = f"{metadata['frame_id']}  {int(metadata['at_ms']) / 1000:.1f}s"
        if event_label:
            label += f"  {event_label}"
        draw.text((left + 4, top + tile_height + 7), label[:52], fill="#111827", font=font)
        if index < len(tiles) - 1:
            draw.text((left + tile_width - 12, top + tile_height + 7), ">", fill="#475569", font=font)
    return canvas


def build_temporal_storyboards(
    package: dict[str, Any],
    *,
    allowed_roots: Iterable[str | Path],
    output_dir: str | Path,
    frames_per_chunk: int = 16,
    columns: int = 4,
) -> TemporalStoryboardBundle:
    """Build ordered storyboard derivatives while retaining exact source-frame mappings."""
    if frames_per_chunk < 1 or columns < 1:
        raise ValueError("storyboard dimensions must be positive")
    manifest = package.get("manifest") if isinstance(package.get("manifest"), dict) else {}
    evidence = manifest.get("recording_evidence") if isinstance(manifest.get("recording_evidence"), dict) else {}
    frames = sorted(
        [item for item in evidence.get("frames", []) if isinstance(item, dict)],
        key=lambda item: (int(item.get("at_ms", 0)), str(item.get("frame_id") or "")),
    )
    recording = package.get("recording") if isinstance(package.get("recording"), dict) else {}
    events = [item for item in recording.get("events", []) if isinstance(item, dict)]
    verified: list[tuple[Image.Image, dict[str, Any]]] = []
    for frame in frames:
        checked = _verified_image(frame.get("artifact_path"), frame.get("sha256"), allowed_roots)
        if checked is None:
            raise ValueError(f"unverified timeline frame: {frame.get('frame_id') or '<missing>'}")
        _path, raw, _size = checked
        with Image.open(BytesIO(raw)) as image:
            source = image.convert("RGB").copy()
        role = str(frame.get("reason") or "periodic")
        if role not in {"pre_action", "event", "post_action", "boundary", "exception"}:
            role = "periodic"
        metadata = {
            "frame_id": str(frame.get("frame_id") or f"frame-{len(verified) + 1:08d}"),
            "at_ms": max(0, int(frame.get("at_ms", 0))),
            "role": role,
            "source_sha256": str(frame.get("sha256") or ""),
            "source_path": str(frame.get("artifact_path") or ""),
            "event": _storyboard_event(events, max(0, int(frame.get("at_ms", 0)))),
        }
        verified.append((source, metadata))

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    chunks: list[TemporalStoryboardChunk] = []
    for offset in range(0, len(verified), frames_per_chunk):
        group = verified[offset : offset + frames_per_chunk]
        chunk_number = len(chunks) + 1
        chunk_id = f"chunk-{chunk_number:04d}"
        image = _storyboard_image(group, columns=columns)
        output = BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        raw = output.getvalue()
        path = destination / f"{chunk_id}.jpg"
        path.write_bytes(raw)
        tiles = []
        for tile_index, (_source, metadata) in enumerate(group):
            tiles.append(dict(metadata) | {"tile_index": tile_index})
        chunks.append(
            TemporalStoryboardChunk(
                chunk_id=chunk_id,
                path=str(path),
                image=LLMImageInput(
                    data=raw,
                    mime_type="image/jpeg",
                    label=f"Temporal storyboard {chunk_id}",
                    detail="high",
                ),
                tiles=tiles,
                start_ms=int(tiles[0]["at_ms"]),
                end_ms=int(tiles[-1]["at_ms"]),
            )
        )

    overview_images: list[LLMImageInput] = []
    overview_paths: list[str] = []
    representatives: list[tuple[Image.Image, dict[str, Any]]] = []
    for chunk_index, chunk in enumerate(chunks):
        source, metadata = verified[chunk_index * frames_per_chunk]
        representatives.append((source, dict(metadata) | {"frame_id": chunk.chunk_id}))
    for offset in range(0, len(representatives), frames_per_chunk):
        page = representatives[offset : offset + frames_per_chunk]
        image = _storyboard_image(page, columns=columns)
        output = BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        raw = output.getvalue()
        path = destination / f"session-overview-{len(overview_paths) + 1:04d}.jpg"
        path.write_bytes(raw)
        overview_paths.append(str(path))
        overview_images.append(
            LLMImageInput(data=raw, mime_type="image/jpeg", label="Session overview", detail="high")
        )
    return TemporalStoryboardBundle(
        chunks=chunks,
        overview_images=overview_images,
        overview_paths=overview_paths,
        source_frame_count=len(verified),
        covered_frame_ids=[str(metadata["frame_id"]) for _source, metadata in verified],
    )


def strip_inline_image_payloads(value: Any) -> Any:
    """Remove duplicate base64 blobs while preserving evidence identity."""
    if isinstance(value, list):
        return [strip_inline_image_payloads(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key == "png_base64":
            cleaned[key] = f"<omitted:{str(value.get('sha256') or '')[:16]}>"
        else:
            cleaned[key] = strip_inline_image_payloads(item)
    return cleaned


def _safe_path(value: Any, allowed_roots: Iterable[str | Path]) -> Path | None:
    try:
        path = Path(str(value or "")).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    roots = []
    for root in allowed_roots:
        try:
            roots.append(Path(root).expanduser().resolve(strict=True))
        except (OSError, RuntimeError):
            continue
    if not any(path == root or root in path.parents for root in roots):
        return None
    return path


def _event_locator_map(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    recording = package.get("recording") if isinstance(package.get("recording"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for event in recording.get("events", []):
        if not isinstance(event, dict):
            continue
        for key in ("visual_locator", "source_visual_locator", "target_visual_locator"):
            locator = event.get(key)
            if isinstance(locator, dict) and str(locator.get("locator_id") or "").strip():
                result[str(locator["locator_id"])] = locator
    return result


def _verified_frame(locator: dict[str, Any], allowed_roots: Iterable[str | Path]) -> tuple[Path, bytes, tuple[int, int]] | None:
    return _verified_image(
        locator.get("full_frame_artifact_path"),
        locator.get("full_frame_sha256"),
        allowed_roots,
    )


def _verified_image(
    path_value: Any,
    sha256_value: Any,
    allowed_roots: Iterable[str | Path],
) -> tuple[Path, bytes, tuple[int, int]] | None:
    path = _safe_path(path_value, allowed_roots)
    if path is None or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return None
    raw = path.read_bytes()
    expected = str(sha256_value or "").lower()
    if len(expected) != 64 or hashlib.sha256(raw).hexdigest() != expected:
        return None
    try:
        with Image.open(BytesIO(raw)) as image:
            size = (int(image.width), int(image.height))
            image.verify()
    except Exception:
        return None
    return path, raw, size


def _mime_type(path: Path) -> str:
    return "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else f"image/{path.suffix.lower().lstrip('.')}"


def _event_context(package: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    recording = package.get("recording") if isinstance(package.get("recording"), dict) else {}
    events = [item for item in recording.get("events", []) if isinstance(item, dict)]
    by_locator: dict[str, dict[str, Any]] = {}
    for event_number, event in enumerate(events, start=1):
        for key in ("visual_locator", "source_visual_locator", "target_visual_locator"):
            locator = event.get(key)
            locator_id = str(locator.get("locator_id") or "") if isinstance(locator, dict) else ""
            if locator_id:
                by_locator[locator_id] = {
                    "event_number": event_number,
                    "at_ms": max(0, int(event.get("at_ms", 0))),
                    "action": str(event.get("kind") or "event"),
                }
    return by_locator, events


def _bounded_text(value: Any, limit: int = 96) -> str:
    return str(value or "").strip()[:limit]


def _event_action_summary(event: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"kind": _bounded_text(event.get("kind") or "event")}
    for key in ("key", "button", "clicks", "language"):
        if key in event and event[key] not in (None, ""):
            summary[key] = _bounded_text(event[key]) if isinstance(event[key], str) else event[key]
    return summary


def _select_candidates(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Preserve locator and boundary evidence, then fill the remaining temporal span."""
    ordered = sorted(candidates, key=lambda item: (int(item["at_ms"]), int(item["phase_order"])))
    if len(ordered) <= limit:
        return ordered
    selected_indexes = {
        index
        for index, item in enumerate(ordered)
        if item["role"] == "pre_action"
    }
    selected_indexes.update({0, len(ordered) - 1})
    if len(selected_indexes) > limit:
        priority = sorted(selected_indexes)
        if limit == 1:
            selected_indexes = {priority[0]}
        else:
            selected_indexes = {
                priority[round(position * (len(priority) - 1) / (limit - 1))]
                for position in range(limit)
            }
    remaining = limit - len(selected_indexes)
    available = [index for index in range(len(ordered)) if index not in selected_indexes]
    if remaining > 0 and available:
        if remaining >= len(available):
            selected_indexes.update(available)
        elif remaining == 1:
            selected_indexes.add(available[len(available) // 2])
        else:
            selected_indexes.update(
                available[round(position * (len(available) - 1) / (remaining - 1))]
                for position in range(remaining)
            )
    return [ordered[index] for index in sorted(selected_indexes)]


def collect_visual_annotation_evidence(
    package: dict[str, Any],
    *,
    allowed_roots: Iterable[str | Path],
    max_images: int = 16,
    max_total_bytes: int = 32 * 1024 * 1024,
) -> SkillVisionEvidence:
    """Collect one bounded chronological visual flow for one model call."""
    locators = _event_locator_map(package)
    locator_events, recording_events = _event_context(package)
    workflow = package.get("workflow") if isinstance(package.get("workflow"), dict) else {}
    candidates: list[dict[str, Any]] = []
    visual_steps: list[dict[str, Any]] = []
    visual_action_times: list[tuple[int, str]] = []
    for step in workflow.get("steps", []):
        if not isinstance(step, dict):
            continue
        action = step.get("action") if isinstance(step.get("action"), dict) else {}
        locator_id = str(action.get("target") or "").strip()
        locator = locators.get(locator_id)
        if not locator:
            continue
        verified = _verified_frame(locator, allowed_roots)
        if verified is None:
            continue
        path, raw, (width, height) = verified
        coordinate = action.get("recorded_coordinate")
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
            continue
        context = locator_events.get(locator_id, {})
        at_ms = max(0, int(context.get("at_ms", 0)))
        step_id = str(step.get("step_id") or "")
        candidate = {
            "role": "pre_action",
            "phase_order": 1,
            "at_ms": at_ms,
            "path": path,
            "raw": raw,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "width": width,
            "height": height,
            "step_id": step_id,
            "locator_id": locator_id,
            "event_number": int(context.get("event_number", 0)),
            "action": str(action.get("action") or context.get("action") or "action"),
            "recorded_coordinate_norm": [
                round(float(coordinate[0]) / width, 6),
                round(float(coordinate[1]) / height, 6),
            ],
        }
        candidates.append(candidate)
        visual_steps.append(candidate)
        visual_action_times.append((at_ms, step_id))

    manifest = package.get("manifest") if isinstance(package.get("manifest"), dict) else {}
    recording_evidence = (
        manifest.get("recording_evidence") if isinstance(manifest.get("recording_evidence"), dict) else {}
    )
    state_frames = [item for item in recording_evidence.get("frames", []) if isinstance(item, dict)]
    for frame_index, frame in enumerate(sorted(state_frames, key=lambda item: int(item.get("at_ms", 0)))):
        verified = _verified_image(frame.get("artifact_path"), frame.get("sha256"), allowed_roots)
        if verified is None:
            continue
        path, raw, (width, height) = verified
        at_ms = max(0, int(frame.get("at_ms", 0)))
        prior = [item for item in visual_action_times if item[0] <= at_ms]
        after_step_id = prior[-1][1] if prior else ""
        role = "initial_state" if frame_index == 0 and not prior else "post_action_state" if prior else "state_observation"
        candidates.append(
            {
                "role": role,
                "phase_order": 2,
                "at_ms": at_ms,
                "path": path,
                "raw": raw,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "width": width,
                "height": height,
                "frame_id": _bounded_text(frame.get("frame_id")),
                "reason": _bounded_text(frame.get("reason") or "state_observation"),
                "after_step_id": after_step_id,
            }
        )

    for frame in recording_evidence.get("event_frames", []):
        if not isinstance(frame, dict):
            continue
        verified = _verified_image(frame.get("artifact_path"), frame.get("sha256"), allowed_roots)
        if verified is None:
            continue
        path, raw, (width, height) = verified
        event_number = max(0, int(frame.get("event_number", 0)))
        source_event = recording_events[event_number - 1] if 0 < event_number <= len(recording_events) else {}
        candidates.append(
            {
                "role": "action_context",
                "phase_order": 0,
                "at_ms": max(0, int(frame.get("event_at_ms", frame.get("at_ms", 0)))),
                "observed_at_ms": max(0, int(frame.get("at_ms", 0))),
                "path": path,
                "raw": raw,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "width": width,
                "height": height,
                "event_number": event_number,
                "source_event": _event_action_summary(source_event),
            }
        )

    deduplicated: list[dict[str, Any]] = []
    seen_sha: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: (int(item["at_ms"]), int(item["phase_order"]))):
        digest = str(candidate["sha256"])
        if digest in seen_sha:
            continue
        seen_sha.add(digest)
        deduplicated.append(candidate)
    selected = _select_candidates(deduplicated, max(1, min(int(max_images), 16)))

    images: list[LLMImageInput] = []
    timeline: list[dict[str, Any]] = []
    total_bytes = 0
    image_index_by_sha: dict[str, int] = {}
    for candidate in selected:
        raw = candidate["raw"]
        if total_bytes + len(raw) > max(1, int(max_total_bytes)):
            continue
        total_bytes += len(raw)
        image_index = len(images) + 1
        image_index_by_sha[str(candidate["sha256"])] = image_index
        images.append(
            LLMImageInput(
                data=raw,
                mime_type=_mime_type(candidate["path"]),
                label=f"{candidate['role']} at {candidate['at_ms']}ms",
                detail="high" if candidate["role"] == "pre_action" else "auto",
            )
        )
        timeline.append(
            {
                key: deepcopy(value)
                for key, value in candidate.items()
                if key not in {"path", "raw", "sha256", "phase_order"} and value not in ("", 0, None, {})
            }
            | {"image_index": image_index, "at_ms": int(candidate["at_ms"]), "role": candidate["role"]}
        )

    steps = []
    for candidate in visual_steps:
        image_index = image_index_by_sha.get(str(candidate["sha256"]))
        if image_index is None:
            continue
        steps.append(
            {
                "image_index": image_index,
                "step_id": candidate["step_id"],
                "locator_id": candidate["locator_id"],
                "image_size": [candidate["width"], candidate["height"]],
                "recorded_coordinate_norm": candidate["recorded_coordinate_norm"],
            }
        )
    return SkillVisionEvidence(images=images, steps=steps, timeline=timeline)


def _bbox(value: Any, *, width: int, height: int, name: str) -> tuple[list[float], tuple[int, int, int, int]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{name} must contain normalized x, y, width, height")
    normalized = [float(item) for item in value]
    x, y, w, h = normalized
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
        raise ValueError(f"{name} must stay within normalized image bounds")
    left = round(x * width)
    top = round(y * height)
    right = round((x + w) * width)
    bottom = round((y + h) * height)
    if not 1 <= right - left <= 512 or not 1 <= bottom - top <= 512:
        raise ValueError(f"{name} pixel dimensions must be within 1..512")
    return normalized, (left, top, right, bottom)


def _candidate(image: Image.Image, box: tuple[int, int, int, int], kind: str, confidence: float) -> dict[str, Any]:
    output = BytesIO()
    image.crop(box).save(output, format="PNG", optimize=True)
    raw = output.getvalue()
    if len(raw) > 256 * 1024:
        raise ValueError(f"{kind} locator crop exceeds 256 KiB")
    return {
        "kind": kind,
        "png_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": box[2] - box[0],
        "height": box[3] - box[1],
        "crop_origin": [box[0], box[1]],
        "confidence": confidence,
    }


def _normalized_bbox(value: Any, *, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{name} must contain normalized x, y, width, height")
    normalized = [float(item) for item in value]
    x, y, width, height = normalized
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise ValueError(f"{name} must stay within normalized image bounds")
    return normalized


def _recorded_candidate_bbox(
    locator: dict[str, Any], *, width: int, height: int
) -> list[float] | None:
    """Recover the original generated ROI from immutable recording evidence."""
    candidates = locator.get("candidates") if isinstance(locator.get("candidates"), list) else []
    ordered = sorted(
        (item for item in candidates if isinstance(item, dict)),
        key=lambda item: str(item.get("kind") or "") != "tight",
    )
    for candidate in ordered:
        origin = candidate.get("crop_origin")
        try:
            crop_width = int(candidate.get("width"))
            crop_height = int(candidate.get("height"))
            origin_x, origin_y = (int(value) for value in origin)
        except (TypeError, ValueError):
            continue
        if (
            crop_width <= 0
            or crop_height <= 0
            or origin_x < 0
            or origin_y < 0
            or origin_x + crop_width > width
            or origin_y + crop_height > height
        ):
            continue
        return [
            origin_x / width,
            origin_y / height,
            crop_width / width,
            crop_height / height,
        ]
    return None


def resolve_visual_locator_source(
    package: dict[str, Any],
    step_id: str,
    *,
    allowed_roots: Iterable[str | Path],
) -> dict[str, Any] | None:
    """Resolve one step's hash-verified pre-action frame for manual ROI editing."""
    workflow = package.get("workflow") if isinstance(package.get("workflow"), dict) else {}
    step = next(
        (
            item
            for item in workflow.get("steps", [])
            if isinstance(item, dict) and str(item.get("step_id") or "") == step_id
        ),
        None,
    )
    action = step.get("action") if isinstance(step, dict) and isinstance(step.get("action"), dict) else None
    if action is None:
        return None
    locator_id = str(action.get("target") or "").strip()
    recorded_locator = _event_locator_map(package).get(locator_id, {})
    verified = _verified_frame(recorded_locator, allowed_roots)
    if verified is None:
        return None
    path, raw, (width, height) = verified
    annotations = package.get("annotations") if isinstance(package.get("annotations"), dict) else {}
    annotation = next(
        (
            item
            for item in annotations.get("steps", [])
            if isinstance(item, dict) and str(item.get("step_id") or "") == step_id
        ),
        {},
    )
    locator = annotation.get("locator") if isinstance(annotation.get("locator"), dict) else {}
    target_bbox = locator.get("target_bbox_norm", action.get("target_bbox_norm"))
    try:
        target_bbox_norm = _normalized_bbox(target_bbox, name="target_bbox_norm")
    except (TypeError, ValueError):
        target_bbox_norm = [0.25, 0.25, 0.5, 0.5]
    recorded_bbox = _recorded_candidate_bbox(recorded_locator, width=width, height=height)
    ai_target_bbox = locator.get("ai_target_bbox_norm", action.get("ai_target_bbox_norm"))
    if ai_target_bbox is None:
        ai_target_bbox = recorded_bbox or target_bbox_norm
    try:
        ai_target_bbox_norm = _normalized_bbox(ai_target_bbox, name="ai_target_bbox_norm")
    except (TypeError, ValueError):
        ai_target_bbox_norm = list(recorded_bbox or target_bbox_norm)
    return {
        "path": path,
        "raw": raw,
        "media_type": _mime_type(path),
        "source_size": [width, height],
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "target_bbox_norm": target_bbox_norm,
        "ai_target_bbox_norm": ai_target_bbox_norm,
        "locator_id": locator_id,
    }


def apply_visual_locator_annotations(
    package: dict[str, Any],
    updates: dict[str, Any],
    *,
    allowed_roots: Iterable[str | Path],
) -> dict[str, Any]:
    """Compile reviewed normalized model boxes into bounded executable locators."""
    enriched = deepcopy(package)
    locators = _event_locator_map(enriched)
    update_by_step = {
        str(item.get("step_id") or ""): item
        for item in updates.get("steps", [])
        if isinstance(item, dict) and isinstance(item.get("locator"), dict)
    }
    workflow = enriched.get("workflow") if isinstance(enriched.get("workflow"), dict) else {}
    for step in workflow.get("steps", []):
        if not isinstance(step, dict) or str(step.get("step_id") or "") not in update_by_step:
            continue
        action = step.get("action") if isinstance(step.get("action"), dict) else {}
        locator_id = str(action.get("target") or "")
        verified = _verified_frame(locators.get(locator_id, {}), allowed_roots)
        if verified is None:
            continue
        _path, raw, (width, height) = verified
        model_locator = update_by_step[str(step["step_id"])]["locator"]
        roi_norm, _roi_box = _bbox(model_locator.get("search_roi_norm"), width=width, height=height, name="search_roi_norm")
        _target_norm, target_box = _bbox(model_locator.get("target_bbox_norm"), width=width, height=height, name="target_bbox_norm")
        _context_norm, context_box = _bbox(model_locator.get("context_bbox_norm"), width=width, height=height, name="context_bbox_norm")
        with Image.open(BytesIO(raw)) as image:
            action["image_candidates"] = [
                _candidate(image, target_box, "tight", 0.9),
                _candidate(image, context_box, "context", 0.84),
            ]
        action["region_normalized"] = roi_norm
        action["locator_backend"] = "multimodal_roi_image"
        step["action"] = action
    return enriched
