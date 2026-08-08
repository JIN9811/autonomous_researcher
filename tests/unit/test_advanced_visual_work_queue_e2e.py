from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "advanced_visual_work_queue_e2e.py"
EXPECTED = {
    "specimen_id": "specimen-beta",
    "method": "Compression",
    "evidence_enabled": True,
    "load_limit": 12.5,
}


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("advanced_visual_work_queue_e2e_under_test", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_outputs(root: Path, *, csv_specimen: str = "specimen-beta") -> tuple[Path, Path]:
    json_path = root / "advanced_queue_result.json"
    csv_path = root / "advanced_queue_result.csv"
    json_path.write_text(json.dumps(EXPECTED), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EXPECTED))
        writer.writeheader()
        writer.writerow({**EXPECTED, "specimen_id": csv_specimen, "evidence_enabled": "true"})
    return json_path, csv_path


def test_assert_image_only_programs_accepts_visual_click_and_drag() -> None:
    module = _load_runner_module()
    candidate = {"kind": "context", "png_base64": "png", "sha256": "a" * 64, "width": 10, "height": 10}
    programs = [
        {
            "sequence": [
                {"action": "click", "target": "row", "image_candidates": [candidate]},
                {"action": "move_to", "target": "drag-source", "image_candidates": [candidate]},
                {"action": "drag_to", "target": "queue", "image_candidates": [candidate]},
                {"action": "write", "text": "12.5"},
            ]
        }
    ]

    module.assert_image_only_programs(programs)


def test_assert_image_only_programs_rejects_executable_coordinates() -> None:
    module = _load_runner_module()

    with pytest.raises(AssertionError, match="executable coordinate"):
        module.assert_image_only_programs([{"sequence": [{"action": "click", "x": 10, "y": 20}]}])


def test_assert_image_only_programs_requires_exactly_one_drag() -> None:
    module = _load_runner_module()

    with pytest.raises(AssertionError, match="exactly one visual drag"):
        module.assert_image_only_programs([{"sequence": [{"action": "write", "text": "none"}]}])


def test_validate_exported_artifacts_requires_json_csv_identity(tmp_path: Path) -> None:
    module = _load_runner_module()
    json_path, csv_path = _write_outputs(tmp_path)

    summary = module.validate_exported_artifacts(json_path, csv_path, EXPECTED)

    assert summary == {"ok": True, "csv_rows": 1, "result": EXPECTED}


def test_validate_exported_artifacts_rejects_csv_mismatch(tmp_path: Path) -> None:
    module = _load_runner_module()
    json_path, csv_path = _write_outputs(tmp_path, csv_specimen="specimen-gamma")

    with pytest.raises(AssertionError, match="CSV output"):
        module.validate_exported_artifacts(json_path, csv_path, EXPECTED)


def test_validate_png_requires_decodable_nonempty_image(tmp_path: Path) -> None:
    module = _load_runner_module()
    valid = tmp_path / "valid.png"
    invalid = tmp_path / "invalid.png"
    Image.new("RGB", (32, 24), "#123456").save(valid)
    invalid.write_bytes(b"not-png")

    assert module.validate_png(valid) == {"path": str(valid), "width": 32, "height": 24}
    with pytest.raises(AssertionError, match="PNG"):
        module.validate_png(invalid)


def test_validate_missing_target_result_requires_safe_block_and_evidence(tmp_path: Path) -> None:
    module = _load_runner_module()
    evidence = tmp_path / "failure.png"
    Image.new("RGB", (20, 20), "#991122").save(evidence)

    summary = module.validate_missing_target_result(
        {
            "ok": False,
            "failure_code": "UI_LOCATOR_NOT_FOUND",
            "trace": [{"step": "SEQ_4_CLICK", "status": "blocked"}],
            "failure_artifacts": [str(evidence)],
        },
        export_paths=[],
    )

    assert summary["blocked_as_expected"] is True
    assert summary["blocked_step"] == "SEQ_4_CLICK"


def test_validate_missing_target_result_rejects_unexpected_export(tmp_path: Path) -> None:
    module = _load_runner_module()
    evidence = tmp_path / "failure.png"
    output = tmp_path / "unexpected.json"
    Image.new("RGB", (20, 20), "#991122").save(evidence)
    output.write_text("{}", encoding="utf-8")

    with pytest.raises(AssertionError, match="export"):
        module.validate_missing_target_result(
            {
                "ok": False,
                "failure_code": "UI_LOCATOR_NOT_FOUND",
                "trace": [{"step": "SEQ_1_CLICK", "status": "blocked"}],
                "failure_artifacts": [str(evidence)],
            },
            export_paths=[output],
        )


def test_build_bridge_command_uses_packaged_source_and_isolated_roots(tmp_path: Path) -> None:
    module = _load_runner_module()

    command = module.build_bridge_command(
        run_root=tmp_path,
        bridge_port=8878,
        token="isolated-token",
        python_executable=sys.executable,
    )

    assert command[0] == sys.executable
    assert command[1] == str(ROOT / "Pyautogui_server_for_window" / "bridge" / "windows_pyautogui_bridge_server.py")
    assert command[command.index("--port") + 1] == "8878"
    assert command[command.index("--platform") + 1] == "linux"
    assert command[command.index("--program-dir") + 1] == str(tmp_path / "bridge" / "programs")
    assert command[command.index("--recording-dir") + 1] == str(tmp_path / "recordings")


def test_build_bridge_command_refuses_main_atr_port(tmp_path: Path) -> None:
    module = _load_runner_module()

    with pytest.raises(ValueError, match="7860"):
        module.build_bridge_command(run_root=tmp_path, bridge_port=7860, token="token")


def test_normalize_execute_failure_extracts_bridge_png_paths(tmp_path: Path) -> None:
    module = _load_runner_module()
    screenshot = tmp_path / "locator_failure.png"
    Image.new("RGB", (20, 20), "#991122").save(screenshot)

    normalized = module.normalize_execute_failure(
        {
            "ok": False,
            "failure_code": "UI_LOCATOR_NOT_FOUND",
            "step_trace": [{"step": "SEQ_4_CLICK", "status": "blocked"}],
            "output_artifacts": [{"kind": "screen_png", "windows_path": str(screenshot)}],
        }
    )

    assert normalized["trace"] == [{"step": "SEQ_4_CLICK", "status": "blocked"}]
    assert normalized["failure_artifacts"] == [str(screenshot)]


def test_recording_click_moves_pointer_before_press() -> None:
    module = _load_runner_module()

    class FakePyAutoGUI:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def moveTo(self, x: int, y: int, *, duration: float) -> None:  # noqa: N802
            self.calls.append(("moveTo", x, y, duration))

        def click(self) -> None:
            self.calls.append(("click",))

    fake = FakePyAutoGUI()
    module._recording_click(fake, 240, 360)

    assert fake.calls == [("moveTo", 240, 360, 0.12), ("click",)]
