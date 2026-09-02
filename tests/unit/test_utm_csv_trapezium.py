"""Regression tests for native TRAPEZIUM raw CSV exports."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from device_bridges.windows_pyautogui_bridge import WindowsPyAutoGUIBridge
from mcp_tools.utm_tools import _probe_csv
from utils.utm_csv import parse_utm_csv_bytes, probe_utm_csv_bytes


def _trapezium_csv_bytes() -> bytes:
    text = (
        '"1 _ 1",,,,,,,,\r\n'
        '"Time","Force","스트로크","Height","Stress","스트로크 (신율)","변위","변위 (신율)","Height (Strain)"\r\n'
        '"sec","N","mm","mm","N/mm2","%","mm","%","%"\r\n'
        '"0","-0.199","0","30.49998","-0.0002211111","0","0","0","101.6666"\r\n'
        '"0.01","-0.201","0.001191667","30.49879","-0.0002233333","0.003972222","0.001191667","0.003972222","101.6626"\r\n'
        '"0.02","-0.25","0.005841667","30.49413","-0.0002777778","0.01947222","0.005841667","0.01947222","101.6471"\r\n'
    )
    return text.encode("cp949")


def _assert_trapezium_probe(probe: dict[str, object]) -> None:
    assert probe["ok"] is True
    assert probe["source_format"] == "trapeziumx_raw"
    assert probe["encoding"] == "cp949"
    assert probe["columns_probe"] == ["time_s", "force_N", "displacement_mm", "height_mm"]
    assert probe["source_columns"][:4] == ["Time", "Force", "스트로크", "Height"]
    assert probe["units"][:4] == ["sec", "N", "mm", "mm"]
    assert probe["row_count_probe"] == 3
    quality = probe["data_quality"]
    assert isinstance(quality, dict)
    assert quality["numeric_row_count"] == 3
    assert quality["time_monotonic_non_decreasing"] is True
    assert quality["displacement_changes"] is True
    assert quality["force_changes"] is True
    assert quality["raw_csv_preserved"] is True


def test_linux_probes_parse_cp949_trapezium_three_row_header(tmp_path: Path) -> None:
    data = _trapezium_csv_bytes()
    path = tmp_path / "trapezium.csv"
    path.write_bytes(data)

    _assert_trapezium_probe(WindowsPyAutoGUIBridge._probe_utm_csv_bytes(data))
    _assert_trapezium_probe(_probe_csv(path))
    assert path.read_bytes() == data


def test_shared_parser_returns_canonical_rows_without_bloating_probe_payload() -> None:
    data = _trapezium_csv_bytes()

    rows, probe = parse_utm_csv_bytes(data)

    assert probe["source_format"] == "trapeziumx_raw"
    assert rows[1] == {
        "time_s": 0.01,
        "force_N": -0.201,
        "displacement_mm": 0.001191667,
        "height_mm": 30.49879,
    }
    assert "canonical_rows" not in probe_utm_csv_bytes(data)


def test_standalone_worker_matches_trapezium_probe_contract(tmp_path: Path) -> None:
    helper_path = Path(__file__).resolve().parents[2] / "install" / "windows_pyautogui_bridge_server.py"
    spec = importlib.util.spec_from_file_location("trapezium_worker_probe_test", helper_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    path = tmp_path / "trapezium.csv"
    path.write_bytes(_trapezium_csv_bytes())

    _assert_trapezium_probe(module._probe_utm_csv(path))
