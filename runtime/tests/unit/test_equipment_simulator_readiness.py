"""Non-actuating contracts for completed simulated UTM cycles."""

import csv
from pathlib import Path

import pytest

from device_bridges.windows_pyautogui_bridge import (
    WindowsPyAutoGUIBridge,
    WindowsPyAutoGUIBridgeConfig,
)


def _bridge(tmp_path: Path) -> WindowsPyAutoGUIBridge:
    return WindowsPyAutoGUIBridge(
        WindowsPyAutoGUIBridgeConfig.from_devices_config(
            {"devices": {"equipment": {"mode": "simulator"}}}, repo_root=tmp_path
        )
    )


def test_completed_simulated_utm_exposes_scoped_nonphysical_reset_and_clearance(tmp_path: Path) -> None:
    result = _bridge(tmp_path).run({
        "runtime_mode": "test", "program_id": "utm_compression_start_v1",
        "run_id": "run-sim", "loop_id": 0, "specimen_id": "specimen-sim",
    })

    readiness = result["next_specimen_readiness"]
    assert result["ok"] is True
    assert result["status"] == "verified_complete"
    assert result["simulated"] is True
    assert result["actuation_performed"] is False
    assert readiness["ready"] is True
    assert readiness["next_test_completed"] is True
    assert readiness["clearance_restored"] is True
    assert readiness["save_current_test"] is False
    assert readiness["simulated"] is True
    assert readiness["actuation_performed"] is False
    assert {key: readiness[key] for key in ("run_id", "loop_id", "specimen_id")} == {
        "run_id": "run-sim", "loop_id": 0, "specimen_id": "specimen-sim",
    }
    steps = {entry["step"]: entry for entry in result["step_trace"]}
    for name in ("SIMULATED_NEXT_TEST_RESET", "SIMULATED_RESTORE_CLEARANCE"):
        assert steps[name]["status"] == "ok"
        assert "simulated" in steps[name]["detail"].lower()
    assert Path(result["result_file"]).is_file()


def test_invalid_simulated_csv_cannot_claim_completed_reset_or_clearance(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    # Inject corruption at the disk-read boundary, keeping the actual CSV probe.
    original_read = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path.suffix == ".csv" and path.is_relative_to(tmp_path):
            return b"invalid,export\nnot,utm\n"
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    result = bridge.run({"runtime_mode": "test", "program_id": "utm_compression_start_v1"})

    assert result["ok"] is False
    assert result["status"] != "verified_complete"
    assert result["cross_checks"]["data_parse_probe_ok"] is False
    readiness = result["next_specimen_readiness"]
    assert readiness["ready"] is False
    assert readiness["next_test_completed"] is False
    assert readiness["clearance_restored"] is False
    assert readiness["failure_code"] == "UTM_DATA_PARSE_FAILED"
    assert not any(entry["step"] in {"SIMULATED_NEXT_TEST_RESET", "SIMULATED_RESTORE_CLEARANCE"}
                   and entry["status"] == "ok" for entry in result["step_trace"])


@pytest.mark.parametrize("program_id", ["program1", "utm_export_csv_v1", "utm_stop_or_abort_v1"])
def test_other_simulated_programs_do_not_claim_next_specimen_readiness(tmp_path: Path, program_id: str) -> None:
    result = _bridge(tmp_path).run({"runtime_mode": "test", "program_id": program_id})

    assert result["ok"] is True
    assert "next_specimen_readiness" not in result


def test_simulated_readiness_preserves_specimen_from_experiment_without_inventing_loop(tmp_path: Path) -> None:
    result = _bridge(tmp_path).run({
        "runtime_mode": "test", "program_id": "utm_compression_start_v1",
        "run_id": "run-scoped", "experiment_spec": {"specimen_id": "specimen-scoped"},
    })

    assert result["next_specimen_readiness"]["run_id"] == "run-scoped"
    assert result["next_specimen_readiness"]["specimen_id"] == "specimen-scoped"
    assert "loop_id" not in result["next_specimen_readiness"]


@pytest.mark.parametrize(("experiment", "expected_extent"), [
    ({}, 10.0),
    ({"specimen_size_mm": [20, 20, 20]}, 10.0),
    ({"specimen_size_mm": [30, 30, 30], "target_strain": 0.5}, 15.0),
    ({"specimen_size_mm": [30, 30, 30], "target_strain": 0.4}, 12.0),
    ({"size_mm": [10, 12, 24]}, 12.0),
    ({"specimen_size_mm": [30, 30, 30], "height_mm": 16}, 8.0),
    ({"specimen_size_mm": [30, 30, 30], "height_mm": 16, "gauge_length_mm": 12}, 6.0),
    ({"gauge_length_mm": 30.123456789012345, "target_strain": 0.5}, round(30.123456789012345, 6) * 0.5),
    ({"gauge_length_mm": 12.1234567, "target_strain": 0.5}, round(12.1234567, 6) * 0.5),
    ({"gauge_length_mm": 12.12345}, 6.061725),
])
def test_simulated_curve_extent_follows_configured_geometry_and_strain(tmp_path: Path, experiment: dict, expected_extent: float) -> None:
    result = _bridge(tmp_path).run({
        "runtime_mode": "test", "program_id": "utm_compression_start_v1",
        "experiment_spec": experiment,
    })

    assert result["ok"] is True
    with Path(result["result_file"]).open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 80
    assert float(rows[0]["displacement_mm"]) == 0
    assert float(rows[-1]["displacement_mm"]) == expected_extent
    assert float(rows[-1]["force_N"]) == 55.7373
    assert result["synthetic"] is True
    assert result["actuation_performed"] is False


@pytest.mark.parametrize(("experiment", "extent"), [({}, 16.0), ({"gauge_length_mm": 18}, 9.0)])
def test_simulated_curve_geometry_uses_candidate_parameters_beneath_experiment(tmp_path: Path, experiment: dict, extent: float) -> None:
    result = _bridge(tmp_path).run({
        "runtime_mode": "test", "program_id": "utm_compression_start_v1",
        "source_stage_context": {"specimen": {"candidate": {"parameters": {"gauge_length_mm": 32}}}},
        "experiment_spec": experiment,
    })
    with Path(result["result_file"]).open() as stream:
        rows = list(csv.DictReader(stream))
    assert float(rows[-1]["displacement_mm"]) == extent


@pytest.mark.parametrize("experiment", [
    {"gauge_length_mm": 0}, {"height_mm": -1}, {"height_mm": None},
    {"height_mm": float("nan")}, {"height_mm": float("inf")},
    {"height_mm": True}, {"specimen_size_mm": [20, 20]},
    {"specimen_size_mm": [20, 20, 0]}, {"specimen_size_mm": None},
    {"target_strain": 0}, {"target_strain": -0.1}, {"target_strain": 1.2},
    {"target_strain": None}, {"target_strain": float("nan")},
    {"target_strain": float("inf")}, {"target_strain": False},
])
def test_invalid_simulated_curve_configuration_fails_without_readiness(tmp_path: Path, experiment: dict) -> None:
    result = _bridge(tmp_path).run({
        "runtime_mode": "test", "program_id": "utm_compression_start_v1",
        "experiment_spec": experiment,
    })

    assert result["ok"] is False
    assert result["failure_code"] == "SIMULATED_UTM_CURVE_CONFIG_INVALID"
    assert "next_specimen_readiness" not in result
    assert "result_file" not in result
    assert result["simulated"] is True
    assert result["actuation_performed"] is False
