"""Tests for one-frame UTM specimen-presence evidence."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from utils.utm_specimen_presence import inspect_specimen_presence


def _data_url(image: np.ndarray) -> str:
    buffer = BytesIO()
    Image.fromarray(image.astype(np.uint8), mode="RGB").save(buffer, format="JPEG", quality=95)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def test_red_specimen_is_detected_and_evidence_is_persisted(tmp_path: Path) -> None:
    image = np.full((120, 180, 3), 220, dtype=np.uint8)
    image[35:95, 70:125] = [225, 25, 30]

    result = inspect_specimen_presence(
        _data_url(image),
        output_dir=tmp_path,
        specimen_id="specimen-1",
        frame_id="utm-frame-1",
        min_area_px=400,
    )

    assert result["ok"] is True
    assert result["detected"] is True
    assert result["status"] == "confirmed"
    assert result["bbox_xyxy"][0] < result["bbox_xyxy"][2]
    assert result["contour_area_px"] >= 2500
    assert Path(result["raw_frame_path"]).is_file()
    assert Path(result["annotated_frame_path"]).is_file()
    assert Path(result["evidence_path"]).is_file()


def test_frame_without_red_specimen_is_recorded_but_not_confirmed(tmp_path: Path) -> None:
    image = np.full((100, 160, 3), 185, dtype=np.uint8)

    result = inspect_specimen_presence(
        _data_url(image),
        output_dir=tmp_path,
        specimen_id="specimen-2",
        frame_id="utm-frame-2",
        min_area_px=200,
    )

    assert result["ok"] is True
    assert result["detected"] is False
    assert result["status"] == "not_detected"
    assert result["failure_code"] == "SPECIMEN_NOT_DETECTED"
    assert Path(result["raw_frame_path"]).is_file()
    assert Path(result["annotated_frame_path"]).is_file()
    assert Path(result["evidence_path"]).is_file()
