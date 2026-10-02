"""Tests for the Isaac Lab validation CLI wrapper."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import lerobot_isaac_lab_validate


def test_isaac_lab_validate_cli_writes_validation_report_and_passes_check_groups(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []
    output = tmp_path / "validation_report.json"

    class FakeBridge:
        def isaac_lab_validate(self, payload: dict) -> dict:
            calls.append(payload)
            return {
                "ok": True,
                "tool": "lerobot.isaac_lab.validate",
                "status": "READY_TO_BUILD",
                "dataset_path": payload["dataset_path"],
                "validation_report": {
                    "schema": "atr.lerobot.isaac_lab.validation.v1",
                    "ok": True,
                    "status": "passed",
                    "stage": "validation",
                    "checks": [{"id": "validate_isaac_lab_import", "group": "runtime", "status": "passed"}],
                    "blockers": [],
                    "warnings": [],
                },
            }

    monkeypatch.setattr(lerobot_isaac_lab_validate, "_bridge", lambda: FakeBridge())

    exit_code = lerobot_isaac_lab_validate.main(
        [
            "--dataset",
            str(tmp_path / "dataset"),
            "--checks",
            "runtime,digital_twin",
            "--output",
            str(output),
            "--fail-on",
            "blocker",
        ]
    )

    assert exit_code == 0
    assert calls[0]["validation_checks"] == ["runtime", "digital_twin"]
    assert output.is_file()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["schema"] == "atr.lerobot.isaac_lab.validation.v1"
    assert written["checks"][0]["group"] == "runtime"

