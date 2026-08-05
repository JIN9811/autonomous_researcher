"""Tests for one-frame UTM specimen-presence evidence."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from utils.utm_specimen_presence import inspect_specimen_presence, inspect_specimen_presence_path


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


def test_vivid_red_specimen_is_selected_over_larger_red_brown_table(tmp_path: Path) -> None:
    image = np.full((120, 180, 3), 190, dtype=np.uint8)
    image[75:120, :] = [58, 39, 30]
    image[30:70, 78:108] = [120, 25, 20]

    result = inspect_specimen_presence(
        _data_url(image),
        output_dir=tmp_path,
        specimen_id="specimen-on-red-brown-table",
        frame_id="utm-table-frame",
        min_area_px=200,
    )

    assert result["detected"] is True
    assert 75 <= result["center_px"][0] <= 110
    assert 30 <= result["center_px"][1] <= 70
    assert result["bbox_xyxy"][3] < 75


def test_path_detector_limits_active_cam_detection_to_workspace_roi(tmp_path: Path) -> None:
    image = np.full((480, 640, 3), 205, dtype=np.uint8)
    image[90:170, 360:430] = [210, 25, 30]
    image[350:470, 60:240] = [225, 20, 25]
    frame_path = tmp_path / "active-cam-positive.png"
    Image.fromarray(image, mode="RGB").save(frame_path)

    result = inspect_specimen_presence_path(
        frame_path,
        output_dir=tmp_path / "evidence",
        specimen_id="specimen-1",
        frame_id="active-cam-positive",
        roi_normalized=(0.18, 0.0, 0.84, 0.62),
    )

    assert result["detected"] is True
    assert result["bbox_xyxy"] == [360, 90, 430, 170]
    assert 394 <= result["center_px"][0] <= 395
    assert result["center_px"][1] == 130
    assert Path(result["annotated_frame_path"]).is_file()


def test_path_detector_ignores_red_robot_parts_outside_workspace_roi(tmp_path: Path) -> None:
    image = np.full((480, 640, 3), 205, dtype=np.uint8)
    image[350:470, 60:240] = [225, 20, 25]
    image[340:475, 440:610] = [225, 20, 25]
    frame_path = tmp_path / "active-cam-empty.png"
    Image.fromarray(image, mode="RGB").save(frame_path)

    result = inspect_specimen_presence_path(
        frame_path,
        output_dir=tmp_path / "evidence",
        specimen_id="specimen-2",
        frame_id="active-cam-empty",
        roi_normalized=(0.18, 0.0, 0.84, 0.62),
    )

    assert result["detected"] is False
    assert result["bbox_xyxy"] == []
