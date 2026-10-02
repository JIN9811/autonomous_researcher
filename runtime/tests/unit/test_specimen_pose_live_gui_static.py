from __future__ import annotations

from pathlib import Path


def test_planning_js_mentions_specimen_pose_and_d455f_return() -> None:
    source = Path("web/static/planning.js").read_text(encoding="utf-8")

    assert "specimen_pose" in source
    assert "camera_returned_to_vla" in source
    assert "VLA camera" in source
    assert "D455F" in source
