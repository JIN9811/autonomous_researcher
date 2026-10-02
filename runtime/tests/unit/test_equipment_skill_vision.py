from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from utils.equipment_skill_vision import (
    apply_visual_locator_annotations,
    build_temporal_storyboards,
    collect_visual_annotation_evidence,
    resolve_visual_locator_source,
    strip_inline_image_payloads,
)


def _package(frame_path: Path) -> dict:
    digest = hashlib.sha256(frame_path.read_bytes()).hexdigest()
    return {
        "workflow": {
            "steps": [
                {
                    "step_id": "step-001",
                    "action": {
                        "action": "click",
                        "target": "evt-0001-target",
                        "recorded_coordinate": [100, 50],
                        "image_candidates": [],
                    },
                }
            ]
        },
        "recording": {
            "events": [
                {
                    "kind": "mouse_click",
                    "visual_locator": {
                        "locator_id": "evt-0001-target",
                        "full_frame_artifact_path": str(frame_path),
                        "full_frame_sha256": digest,
                    },
                }
            ]
        },
    }


def test_collect_visual_evidence_uses_verified_pre_action_frame(tmp_path: Path) -> None:
    frame = tmp_path / "evt-0001-source-frame.png"
    Image.new("RGB", (200, 100), "white").save(frame)

    evidence = collect_visual_annotation_evidence(_package(frame), allowed_roots=[tmp_path])

    assert len(evidence.images) == 1
    assert evidence.images[0].data == frame.read_bytes()
    assert evidence.steps == [
        {
            "image_index": 1,
            "step_id": "step-001",
            "locator_id": "evt-0001-target",
            "image_size": [200, 100],
            "recorded_coordinate_norm": [0.5, 0.5],
        }
    ]


def test_collect_visual_evidence_builds_chronological_action_state_flow(tmp_path: Path) -> None:
    initial = tmp_path / "initial.jpg"
    pre_click = tmp_path / "evt-0001-source-frame.png"
    after_click = tmp_path / "after-click.jpg"
    Image.new("RGB", (200, 100), "gray").save(initial)
    Image.new("RGB", (200, 100), "white").save(pre_click)
    Image.new("RGB", (200, 100), "green").save(after_click)
    package = _package(pre_click)
    package["recording"]["events"][0]["at_ms"] = 1000
    package["manifest"] = {
        "recording_evidence": {
            "frames": [
                {
                    "frame_id": "frame-initial",
                    "at_ms": 0,
                    "artifact_path": str(initial),
                    "sha256": hashlib.sha256(initial.read_bytes()).hexdigest(),
                    "media_type": "image/jpeg",
                    "width": 200,
                    "height": 100,
                    "reason": "boundary",
                },
                {
                    "frame_id": "frame-after-click",
                    "at_ms": 1300,
                    "artifact_path": str(after_click),
                    "sha256": hashlib.sha256(after_click.read_bytes()).hexdigest(),
                    "media_type": "image/jpeg",
                    "width": 200,
                    "height": 100,
                    "reason": "state_change",
                },
            ]
        }
    }

    evidence = collect_visual_annotation_evidence(package, allowed_roots=[tmp_path], max_images=8)

    assert [item["role"] for item in evidence.timeline] == [
        "initial_state",
        "pre_action",
        "post_action_state",
    ]
    assert [item["at_ms"] for item in evidence.timeline] == [0, 1000, 1300]
    assert evidence.timeline[1]["step_id"] == "step-001"
    assert evidence.timeline[1]["action"] == "click"
    assert evidence.timeline[2]["after_step_id"] == "step-001"
    assert [item["image_index"] for item in evidence.timeline] == [1, 2, 3]
    assert evidence.steps[0]["image_index"] == 2


def test_collect_visual_evidence_deduplicates_identical_timeline_frames(tmp_path: Path) -> None:
    frame = tmp_path / "same.png"
    Image.new("RGB", (200, 100), "white").save(frame)
    package = _package(frame)
    digest = hashlib.sha256(frame.read_bytes()).hexdigest()
    package["manifest"] = {
        "recording_evidence": {
            "frames": [
                {
                    "frame_id": "duplicate",
                    "at_ms": 1200,
                    "artifact_path": str(frame),
                    "sha256": digest,
                    "media_type": "image/png",
                    "width": 200,
                    "height": 100,
                }
            ]
        }
    }

    evidence = collect_visual_annotation_evidence(package, allowed_roots=[tmp_path])

    assert len(evidence.images) == 1
    assert len(evidence.timeline) == 1


def test_apply_visual_annotation_builds_bounded_runtime_locator(tmp_path: Path) -> None:
    frame = tmp_path / "evt-0001-source-frame.png"
    Image.new("RGB", (200, 100), "white").save(frame)
    package = _package(frame)
    updates = {
        "steps": [
            {
                "step_id": "step-001",
                "locator": {
                    "search_roi_norm": [0.1, 0.1, 0.6, 0.7],
                    "target_bbox_norm": [0.4, 0.4, 0.2, 0.2],
                    "context_bbox_norm": [0.25, 0.2, 0.5, 0.5],
                },
            }
        ]
    }

    enriched = apply_visual_locator_annotations(package, updates, allowed_roots=[tmp_path])
    action = enriched["workflow"]["steps"][0]["action"]

    assert action["region_normalized"] == [0.1, 0.1, 0.6, 0.7]
    assert [(item["kind"], item["width"], item["height"]) for item in action["image_candidates"]] == [
        ("tight", 40, 20),
        ("context", 100, 50),
    ]
    assert action["image_candidates"][0]["crop_origin"] == [80, 40]
    assert action["image_candidates"][0]["png_base64"]


def test_locator_source_recovers_ai_bbox_from_recorded_candidate(tmp_path: Path) -> None:
    frame = tmp_path / "evt-0001-source-frame.png"
    Image.new("RGB", (200, 100), "white").save(frame)
    package = _package(frame)
    package["recording"]["events"][0]["visual_locator"]["candidates"] = [
        {
            "kind": "tight",
            "width": 40,
            "height": 20,
            "crop_origin": [80, 40],
        }
    ]
    package["workflow"]["steps"][0]["action"].update(
        {
            "target_bbox_norm": [0.2, 0.1, 0.3, 0.4],
            "locator_origin": "manual_crop",
        }
    )
    package["annotations"] = {
        "steps": [
            {
                "step_id": "step-001",
                "locator": {
                    "target_bbox_norm": [0.2, 0.1, 0.3, 0.4],
                    "locator_origin": "manual_crop",
                },
            }
        ]
    }

    source = resolve_visual_locator_source(package, "step-001", allowed_roots=[tmp_path])

    assert source is not None
    assert source["target_bbox_norm"] == [0.2, 0.1, 0.3, 0.4]
    assert source["ai_target_bbox_norm"] == [0.4, 0.4, 0.2, 0.2]


def test_collect_visual_evidence_rejects_path_outside_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    frame = tmp_path / "outside.png"
    Image.new("RGB", (20, 20), "white").save(frame)

    evidence = collect_visual_annotation_evidence(_package(frame), allowed_roots=[allowed])

    assert evidence.images == []
    assert evidence.steps == []


def test_prompt_payload_strips_duplicate_inline_base64() -> None:
    payload = {"image_candidates": [{"png_base64": "very-large", "sha256": "abc"}]}

    assert strip_inline_image_payloads(payload) == {
        "image_candidates": [{"png_base64": "<omitted:abc>", "sha256": "abc"}]
    }


def test_build_temporal_storyboards_covers_complete_two_fps_timeline(tmp_path: Path) -> None:
    frames = []
    for index in range(34):
        path = tmp_path / f"frame-{index + 1:08d}.jpg"
        Image.new("RGB", (320, 180), (index * 7 % 255, 80, 120)).save(path, quality=90)
        frames.append(
            {
                "frame_id": f"frame-{index + 1:08d}",
                "at_ms": index * 500,
                "artifact_path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "media_type": "image/jpeg",
                "width": 320,
                "height": 180,
                "reason": "periodic",
            }
        )
    package = {
        "recording": {
            "events": [
                {"kind": "mouse_click", "at_ms": 1000, "x": 120, "y": 80},
                {"kind": "key_press", "at_ms": 8500, "key": "enter"},
            ]
        },
        "manifest": {"recording_evidence": {"fps": 2.0, "frames": frames}},
    }

    bundle = build_temporal_storyboards(
        package,
        allowed_roots=[tmp_path],
        output_dir=tmp_path / "storyboards",
    )

    assert [len(chunk.tiles) for chunk in bundle.chunks] == [16, 16, 2]
    assert bundle.source_frame_count == 34
    assert bundle.covered_frame_ids == [item["frame_id"] for item in frames]
    assert all(chunk.image.data.startswith(b"\xff\xd8") for chunk in bundle.chunks)
    assert all(Path(chunk.path).is_file() for chunk in bundle.chunks)
    assert bundle.chunks[0].start_ms == 0
    assert bundle.chunks[0].end_ms == 7500
    assert bundle.chunks[1].tiles[1]["event"]["kind"] == "key_press"
    assert bundle.overview_images
    assert all(item["source_sha256"] == frames[index]["sha256"] for index, item in enumerate(bundle.chunks[0].tiles))
