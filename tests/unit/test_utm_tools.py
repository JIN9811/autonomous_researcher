"""Tests for the direct/legacy UTM tool contract."""

from __future__ import annotations

from pathlib import Path

from mcp_tools.tool_registry import ToolRegistry
from mcp_tools.utm_tools import register_utm_tools, run_utm_protocol


def test_utm_run_protocol_test_mode_creates_parseable_csv(tmp_path: Path) -> None:
    result = run_utm_protocol(
        {
            "runtime_mode": "test",
            "run_id": "run-ut-001",
            "specimen_id": "specimen-ut-001",
            "profile": "test_profile",
        },
        repo_root=tmp_path,
    )

    assert result["ok"] is True
    assert result["tool"] == "utm.run_protocol"
    assert result["bridge"] == "utm_direct"
    assert result["status"] == "verified_complete"
    assert result["cross_checks"]["data_parse_probe_ok"] is True
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert result["data_acquisition"]["row_count_probe"] > 0
    assert Path(result["result_file"]).exists()


def test_utm_run_protocol_live_fails_closed_without_backend(tmp_path: Path) -> None:
    result = run_utm_protocol({"runtime_mode": "live", "profile": "live_profile"}, repo_root=tmp_path)

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["failure_code"] == "UTM_DIRECT_BACKEND_NOT_CONFIGURED"
    assert result["requires_direct_backend_config"] is True
    assert result["cross_checks"]["data_file_created"] is False
    assert result["cross_checks"]["save_export_responsibility_ok"] is False



def test_utm_run_protocol_live_direct_backend_rejects_zero_force_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "zero_force.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0.0,0.00,0.0\n"
        "0.1,0.05,0.0\n"
        "0.2,0.10,0.0\n",
        encoding="utf-8",
    )

    result = run_utm_protocol(
        {
            "runtime_mode": "live",
            "direct_backend_configured": True,
            "result_file": str(csv_path),
        },
        repo_root=tmp_path,
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["failure_code"] == "UTM_DATA_NO_FORCE_SIGNAL"
    assert result["data_acquisition"]["status"] == "pulled_to_linux_parse_failed"
    assert result["data_acquisition"]["data_quality"]["force_signal_present"] is False
    assert result["cross_checks"]["data_parse_probe_ok"] is False


def test_utm_run_protocol_live_direct_backend_rejects_flat_displacement_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "flat_displacement.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0.0,0.00,1.0\n"
        "0.1,0.00,2.0\n"
        "0.2,0.00,3.0\n",
        encoding="utf-8",
    )

    result = run_utm_protocol(
        {
            "runtime_mode": "live",
            "direct_backend_configured": True,
            "result_file": str(csv_path),
        },
        repo_root=tmp_path,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UTM_DATA_NO_DISPLACEMENT_SIGNAL"
    assert result["data_acquisition"]["data_quality"]["displacement_signal_present"] is False
    assert result["cross_checks"]["save_export_responsibility_ok"] is False


def test_utm_run_protocol_live_direct_backend_accepts_negative_compression_sign(tmp_path: Path) -> None:
    csv_path = tmp_path / "negative_compression.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0.0,0.00,0.0\n"
        "0.1,-0.05,-1.5\n"
        "0.2,-0.10,-3.1\n",
        encoding="utf-8",
    )

    result = run_utm_protocol(
        {
            "runtime_mode": "live",
            "direct_backend_configured": True,
            "result_file": str(csv_path),
        },
        repo_root=tmp_path,
    )

    assert result["ok"] is True
    assert result["status"] == "verified_complete"
    assert result["data_acquisition"]["data_quality"]["displacement_monotonic"] is True
    assert result["data_acquisition"]["data_quality"]["force_signal_present"] is True
    assert result["cross_checks"]["data_parse_probe_ok"] is True

def test_register_utm_tools_uses_repo_root_for_artifacts(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_utm_tools(registry, repo_root=tmp_path)

    result = registry.call("utm.run_protocol", {"runtime_mode": "test", "run_id": "run-registry"})

    assert Path(result["result_file"]).is_file()
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert str(tmp_path) in result["result_file"]
