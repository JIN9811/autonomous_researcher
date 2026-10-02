from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DEMO_PATH = ROOT / "Pyautogui_server_for_window" / "demo" / "advanced_visual_work_queue.py"


def _load_demo_module():
    spec = importlib.util.spec_from_file_location("advanced_visual_work_queue_under_test", DEMO_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_mode_accepts_supported_modes_and_reset_suffixes() -> None:
    module = _load_demo_module()

    assert module.normalize_mode("shifted_reordered_reset") == "shifted_reordered"
    assert module.normalize_mode("missing_target") == "missing_target"
    assert module.normalize_mode("unknown") == "initial"


def test_reordered_mode_moves_specimen_beta_to_a_different_row() -> None:
    module = _load_demo_module()

    initial = [row[0] for row in module.specimens_for_mode("initial")]
    reordered = [row[0] for row in module.specimens_for_mode("reordered")]

    assert reordered == list(reversed(initial))
    assert initial.index("specimen-beta") != reordered.index("specimen-beta")


def test_validated_batch_summary_uses_actual_specimen_count() -> None:
    module = _load_demo_module()

    assert module.validated_batch_summary() == "validated-batch-2026-08 · 4 records · schema valid"


def test_analysis_result_normalizes_exact_business_values() -> None:
    module = _load_demo_module()

    result = module.analysis_result(" specimen-beta ", " Compression ", True, "12.5")

    assert result == {
        "specimen_id": "specimen-beta",
        "method": "Compression",
        "evidence_enabled": True,
        "load_limit": 12.5,
    }


def test_stable_button_style_keeps_recorded_target_colors_constant() -> None:
    module = _load_demo_module()

    assert module.stable_button_style("#123456", "#fefefe") == {
        "bg": "#123456",
        "fg": "#fefefe",
        "activebackground": "#123456",
        "activeforeground": "#fefefe",
    }


@pytest.mark.parametrize("load_limit", ["", "not-a-number", "-1", "0"])
def test_analysis_result_rejects_invalid_load_limit(load_limit: str) -> None:
    module = _load_demo_module()

    with pytest.raises(ValueError, match="load limit"):
        module.analysis_result("specimen-beta", "Compression", True, load_limit)


def test_write_exports_emits_matching_json_and_csv(tmp_path: Path) -> None:
    module = _load_demo_module()
    result = module.analysis_result("specimen-beta", "Compression", True, "12.5")

    paths = module.write_exports(tmp_path, "advanced_queue_result", result)

    assert json.loads(Path(paths["json"]).read_text(encoding="utf-8")) == result
    with Path(paths["csv"]).open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle)) == [
            {
                "specimen_id": "specimen-beta",
                "method": "Compression",
                "evidence_enabled": "true",
                "load_limit": "12.5",
            }
        ]


def test_write_exports_rejects_empty_output_name(tmp_path: Path) -> None:
    module = _load_demo_module()
    result = module.analysis_result("specimen-beta", "Compression", True, "12.5")

    with pytest.raises(ValueError, match="output name"):
        module.write_exports(tmp_path, "***", result)


def test_demo_source_exposes_required_surfaces() -> None:
    source = DEMO_PATH.read_text(encoding="utf-8")

    for label in (
        "INPUT BROWSER",
        "specimen-beta",
        "ANALYSIS QUEUE",
        "Compression",
        "EVIDENCE REQUIRED",
        "advanced_queue_result",
        "JSON",
        "CSV",
    ):
        assert label in source
