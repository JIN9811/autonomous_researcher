"""Deterministic one-frame specimen-presence evidence for the UTM workspace."""

from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from skimage.color import rgb2hsv
from skimage.measure import label, regionprops
from skimage.morphology import closing, disk, opening, remove_small_objects


SPECIMEN_PRESENCE_SCHEMA = "vision_utm_specimen_presence.v1"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


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
    mask = red & (saturation >= (70.0 / 255.0)) & (value >= (35.0 / 255.0))
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


def inspect_specimen_presence(
    data_url: str,
    *,
    output_dir: Path | str,
    specimen_id: str,
    frame_id: str,
    min_area_px: float = 300.0,
) -> dict[str, Any]:
    """Inspect one RGB frame, persist raw/annotated evidence, and return a bounded contract."""
    image = _decode_data_url(data_url)
    image_rgb = np.asarray(image, dtype=np.uint8)
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
        bbox_xyxy = [min_col, min_row, max_col, max_row]
        center_px = [int(round(float(region.centroid[1]))), int(round(float(region.centroid[0])))]
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
        "bbox_xyxy": bbox_xyxy,
        "center_px": center_px,
        "contour_area_px": round(contour_area_px, 3),
        "confidence": round(confidence, 4),
        "detector": "dual_red_hsv_largest_component",
        "raw_frame_path": str(raw_path),
        "annotated_frame_path": str(annotated_path),
        "evidence_path": str(evidence_path),
    }
    evidence_path.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    return result
