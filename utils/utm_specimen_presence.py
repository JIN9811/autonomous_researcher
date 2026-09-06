"""Deterministic one-frame specimen-presence evidence for the UTM workspace."""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from skimage.color import rgb2hsv
from skimage.measure import label, regionprops
from skimage.morphology import closing, disk, opening, remove_small_objects


SPECIMEN_PRESENCE_SCHEMA = "vision_utm_specimen_presence.v1"
# Unannotated sources returned by the shared UTM1/UTM2 raw_frame() path.
# Both must still satisfy the camera profile, geometry and registration checks.
UTM_CLEAR_CAMERA_TOPICS = frozenset({"/camera/image_raw", "/camera/image_rect"})
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_RED_MIN_SATURATION = 0.50
_RED_MIN_VALUE = 0.25


def _safe_name(value: Any, default: str) -> str:
    clean = _SAFE_NAME_RE.sub("-", str(value or "").strip()).strip(".-")
    return clean or default


def _decode_data_url(data_url: str) -> Image.Image:
    if not str(data_url).startswith("data:image/") or "," not in str(data_url):
        raise ValueError("Frame is not an image data URL.")
    encoded = str(data_url).split(",", 1)[1]
    image_bytes = base64.b64decode(encoded, validate=True)
    return Image.open(BytesIO(image_bytes)).convert("RGB")


def virtual_specimen_frame_data_url(*, width: int = 640, height: int = 480) -> str:
    """Create an explicitly virtual red specimen frame for test-bridge verification."""
    image = np.full((height, width, 3), 210, dtype=np.uint8)
    x0, x1 = int(width * 0.42), int(width * 0.58)
    y0, y1 = int(height * 0.38), int(height * 0.68)
    image[y0:y1, x0:x1] = [225, 30, 35]
    buffer = BytesIO()
    Image.fromarray(image).save(buffer, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _red_region(image_rgb: np.ndarray, *, min_area_px: float) -> tuple[Any | None, np.ndarray]:
    hsv = rgb2hsv(image_rgb.astype(np.float32) / 255.0)
    hue = hsv[..., 0]
    saturation = hsv[..., 1]
    value = hsv[..., 2]
    red = ((hue <= (12.0 / 180.0)) | (hue >= (168.0 / 180.0)))
    # The UTM table is red-brown and can occupy more pixels than the specimen.
    # Keep only chromatic red material instead of selecting the largest warm surface.
    mask = red & (saturation >= _RED_MIN_SATURATION) & (value >= _RED_MIN_VALUE)
    footprint = disk(2)
    mask = opening(mask, footprint=footprint)
    mask = closing(mask, footprint=footprint)
    minimum_component_area = max(8, int(min_area_px * 0.25))
    mask = remove_small_objects(mask, max_size=minimum_component_area - 1)
    regions = regionprops(label(mask))
    if not regions:
        return None, mask
    region = max(regions, key=lambda item: float(item.area))
    if float(region.area) < float(min_area_px):
        return None, mask
    return region, mask


def _normalized_roi_box(
    image: Image.Image,
    roi_normalized: tuple[float, float, float, float] | None,
) -> tuple[int, int, int, int]:
    if roi_normalized is None:
        return 0, 0, image.width, image.height
    if len(roi_normalized) != 4:
        raise ValueError("roi_normalized must contain left, top, right, bottom.")
    left, top, right, bottom = [float(value) for value in roi_normalized]
    left_px = max(0, min(image.width - 1, int(round(left * image.width))))
    top_px = max(0, min(image.height - 1, int(round(top * image.height))))
    right_px = max(left_px + 1, min(image.width, int(round(right * image.width))))
    bottom_px = max(top_px + 1, min(image.height, int(round(bottom * image.height))))
    return left_px, top_px, right_px, bottom_px


def _inspect_specimen_presence_image(
    image: Image.Image,
    *,
    output_dir: Path | str,
    specimen_id: str,
    frame_id: str,
    min_area_px: float = 300.0,
    roi_normalized: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Inspect one RGB frame, persist raw/annotated evidence, and return a bounded contract."""
    image = image.convert("RGB")
    roi_xyxy = _normalized_roi_box(image, roi_normalized)
    roi_image = image.crop(roi_xyxy)
    image_rgb = np.asarray(roi_image, dtype=np.uint8)
    region, _mask = _red_region(image_rgb, min_area_px=max(float(min_area_px), 1.0))

    target_dir = Path(output_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_frame_id = _safe_name(frame_id, "utm-frame")
    raw_path = target_dir / f"{safe_frame_id}_raw.png"
    annotated_path = target_dir / f"{safe_frame_id}_annotated.png"
    evidence_path = target_dir / f"{safe_frame_id}_presence.json"
    image.save(raw_path, format="PNG")

    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    detected = region is not None
    bbox_xyxy: list[int] = []
    center_px: list[int] = []
    contour_area_px = 0.0
    confidence = 0.0
    if region is not None:
        min_row, min_col, max_row, max_col = [int(value) for value in region.bbox]
        roi_left, roi_top, _roi_right, _roi_bottom = roi_xyxy
        bbox_xyxy = [min_col + roi_left, min_row + roi_top, max_col + roi_left, max_row + roi_top]
        center_px = [
            int(round(float(region.centroid[1]))) + roi_left,
            int(round(float(region.centroid[0]))) + roi_top,
        ]
        contour_area_px = float(region.area)
        image_area = float(max(1, image.width * image.height))
        confidence = min(0.99, max(0.05, (contour_area_px / image_area) * 6.0))
        draw.rectangle(bbox_xyxy, outline=(20, 220, 130), width=3)
        cx, cy = center_px
        draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=(20, 220, 130))
    annotated.save(annotated_path, format="PNG")

    result = {
        "schema": SPECIMEN_PRESENCE_SCHEMA,
        "ok": True,
        "status": "confirmed" if detected else "not_detected",
        "detected": detected,
        "failure_code": "" if detected else "SPECIMEN_NOT_DETECTED",
        "message": "Specimen detected in the UTM observation frame." if detected else "No specimen was detected in the UTM observation frame.",
        "specimen_id": str(specimen_id or ""),
        "frame_id": str(frame_id or safe_frame_id),
        "width": int(image.width),
        "height": int(image.height),
        "roi_xyxy": list(roi_xyxy),
        "bbox_xyxy": bbox_xyxy,
        "center_px": center_px,
        "contour_area_px": round(contour_area_px, 3),
        "confidence": round(confidence, 4),
        "detector": "high_chroma_red_hsv_largest_component",
        "raw_frame_path": str(raw_path),
        "annotated_frame_path": str(annotated_path),
        "evidence_path": str(evidence_path),
    }
    evidence_path.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    return result


def inspect_specimen_presence(
    data_url: str,
    *,
    output_dir: Path | str,
    specimen_id: str,
    frame_id: str,
    min_area_px: float = 300.0,
    roi_normalized: tuple[float, float, float, float] | None = None,
    purpose: str = "",
    capture_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect an image data URL and persist deterministic specimen evidence."""
    if purpose == "utm_clear_verification":
        return _inspect_clear_presence(_decode_data_url(data_url), output_dir=output_dir,
            specimen_id=specimen_id, frame_id=frame_id, evidence=capture_evidence or {})
    return _inspect_specimen_presence_image(
        _decode_data_url(data_url),
        output_dir=output_dir,
        specimen_id=specimen_id,
        frame_id=frame_id,
        min_area_px=min_area_px,
        roi_normalized=roi_normalized,
    )


def _inspect_clear_presence(image, *, output_dir, specimen_id, frame_id, evidence):
    """Profile-specific red-residual check. Registration is not metric calibration."""
    configured_roi = [210, 270, 390, 363]
    result = {"schema": SPECIMEN_PRESENCE_SCHEMA, "purpose": "utm_clear_verification",
        "ok": True, "status": "unknown", "clear_confirmed": False, "detected": False,
        "failure_code": "", "registered": False, "specimen_id": specimen_id,
        "frame_id": frame_id, "width": image.width, "height": image.height,
        "configured_roi_xyxy": configured_roi, "roi_xyxy": configured_roi,
        "detector": "registered_high_chroma_red_residual_v1", "post_clear_min_red_area_px": 150,
        **evidence}
    try:
        stamp, after = float(evidence.get("frame_timestamp", 0)), float(evidence.get("after_timestamp", 0))
        valid = (0 < after < stamp <= time.time() + 1 and time.time() - stamp <= 3
            and image.size == (640, 480) and evidence.get("topic") in UTM_CLEAR_CAMERA_TOPICS
            and evidence.get("camera_profile_id") == "camera_utm_primary" and evidence.get("material") == "high_chroma_red")
    except (ValueError, TypeError):
        stamp, valid = 0, False
    result["captured_at"] = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if 0 < stamp < 1e11 else ""
    hsv = rgb2hsv(np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0)
    green = (hsv[..., 0] >= 0.20) & (hsv[..., 0] <= 0.48) & (hsv[..., 1] >= 0.4) & (hsv[..., 2] >= 0.15)
    anchors = []
    if image.size == (640, 480):
        for x0, y0, x1, y1 in ([220, 348, 255, 385], [335, 348, 370, 385]):
            components = [r for r in regionprops(label(green[y0:y1, x0:x1])) if 30 <= r.area <= 200]
            if len(components) == 1:
                r = components[0]
                anchors.append({"x": float(r.centroid[1] + x0), "y": float(r.centroid[0] + y0), "area": float(r.area)})
    registered = len(anchors) == 2 and 95 <= anchors[1]["x"] - anchors[0]["x"] <= 130 and abs(anchors[1]["y"] - anchors[0]["y"]) <= 8
    result.update(registered=registered, registration={"anchors": anchors, "valid": registered})
    if valid and registered:
        x0, y0, x1, y1 = configured_roi
        crop = hsv[y0:y1, x0:x1]
        raw = ((crop[..., 0] <= 12 / 180) | (crop[..., 0] >= 168 / 180)) & (crop[..., 1] >= 0.5) & (crop[..., 2] >= 0.25)
        mask = closing(opening(raw, footprint=disk(2)), footprint=disk(2))
        regions = [r for r in regionprops(label(mask)) if r.area >= 8]
        total = float(sum(r.area for r in regions))
        raw_total = int(raw.sum())
        occupied = total >= 150 or raw_total >= 150
        bbox = ([min(r.bbox[1] for r in regions) + x0, min(r.bbox[0] for r in regions) + y0,
                 max(r.bbox[3] for r in regions) + x0, max(r.bbox[2] for r in regions) + y0] if regions else [])
        width, height = (bbox[2] - bbox[0], bbox[3] - bbox[1]) if bbox else (0, 0)
        result.update(status="occupied" if occupied else "clear", detected=occupied, clear_confirmed=not occupied,
            aggregate_red_area_px=total, pre_opening_red_area_px=raw_total,
            largest_component_area_px=float(max((r.area for r in regions), default=0)),
            component_count=len(regions), bbox_xyxy=bbox, residual_width_px=width, residual_height_px=height,
            residual_aspect_ratio=width / height if height else None)
    else:
        result["unknown_reason"] = "capture_profile_material_or_registration_invalid"
    directory = Path(output_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    name = _safe_name(frame_id, "utm-clear")
    raw_path, annotated_path, evidence_path = (directory / f"{name}_{suffix}" for suffix in ("raw.png", "annotated.png", "presence.json"))
    image.save(raw_path, format="PNG")
    annotated = image.copy()
    if result.get("bbox_xyxy"):
        ImageDraw.Draw(annotated).rectangle(result["bbox_xyxy"], outline=(20, 220, 130), width=2)
    annotated.save(annotated_path, format="PNG")
    result.update(raw_frame_path=str(raw_path), annotated_frame_path=str(annotated_path), evidence_path=str(evidence_path))
    evidence_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def inspect_specimen_presence_path(
    image_path: Path | str,
    *,
    output_dir: Path | str,
    specimen_id: str,
    frame_id: str,
    min_area_px: float = 300.0,
    roi_normalized: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Inspect a local RGB frame while keeping detections in full-frame coordinates."""
    with Image.open(Path(image_path).expanduser()) as image:
        return _inspect_specimen_presence_image(
            image,
            output_dir=output_dir,
            specimen_id=specimen_id,
            frame_id=frame_id,
            min_area_px=min_area_px,
            roi_normalized=roi_normalized,
        )
