"""Unit tests for Windows PyAutoGUI equipment bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from device_bridges.windows_pyautogui_bridge import (
    WindowsPyAutoGUIBridge,
    WindowsPyAutoGUIBridgeConfig,
    discover_windows_pyautogui_bridges,
    local_ipv4_scan_targets,
)
from mcp_tools.equipment_tools import register_equipment_tools
from mcp_tools.tool_registry import ToolRegistry


def _bridge(tmp_path: Path, *, mode: str = "simulator", allow_live: bool = False) -> WindowsPyAutoGUIBridge:
    cfg = WindowsPyAutoGUIBridgeConfig.from_devices_config(
        {
            "devices": {
                "equipment": {
                    "mode": mode,
                    "windows_pyautogui": {
                        "allow_live_execute": allow_live,
                        "connection_memory_path": str(tmp_path / "windows_pyautogui_connection.json"),
                        "simulator": {"pyautogui_available": True},
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    return WindowsPyAutoGUIBridge(cfg)


def test_simulator_program1_returns_completion_log(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.run({"runtime_mode": "test", "program_id": "program1", "sequence_id": "seq-1"})

    assert response["ok"] is True
    assert response["program_id"] == "program1"
    assert response["program_log"] == "program1 completed"
    assert any(step["step"] == "EXECUTE_PROGRAM" for step in response["step_trace"])


def test_simulator_program1_reports_missing_pyautogui(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.run(
        {
            "runtime_mode": "test",
            "program_id": "program1",
            "sequence_id": "seq-1",
            "simulate_pyautogui_available": False,
        }
    )

    assert response["ok"] is False
    assert response["failure_code"] == "PYAUTOGUI_NOT_INSTALLED"
    assert response["requires_install"] is True


def test_unknown_action_rejected_before_execution(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.run({"runtime_mode": "test", "sequence": [{"action": "shell", "cmd": "dir"}]})

    assert response["ok"] is False
    assert response["failure_code"] == "PYAUTOGUI_ACTION_NOT_ALLOWED"


def test_unknown_program_rejected_in_simulator(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.run({"runtime_mode": "test", "program_id": "program404"})

    assert response["ok"] is False
    assert response["failure_code"] == "PYAUTOGUI_PROGRAM_NOT_FOUND"


def test_live_execution_requires_explicit_allow_or_setup_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=False)
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "token")

    response = bridge.run({"runtime_mode": "live", "program_id": "program1"})

    assert response["ok"] is False
    assert response["failure_code"] == "PYAUTOGUI_LIVE_EXECUTION_BLOCKED"


def test_live_missing_url_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    monkeypatch.delenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", raising=False)
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "token")

    response = bridge.run({"runtime_mode": "live", "program_id": "program1"})

    assert response["ok"] is False
    assert response["failure_code"] == "PYAUTOGUI_BRIDGE_URL_REQUIRED"


def test_save_connection_memory_used_by_status(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    status = bridge.save_connection({"candidate_alias": "win_macro_1", "host": "192.168.0.20", "port": 8765, "token": "secret"})

    assert status["selected"] is True
    assert status["selected_candidate"] == "win_macro_1"
    assert status["bridge_url"] == "http://192.168.0.20:8765"
    assert status["token_configured"] is True
    assert status["candidates"][0]["candidate_alias"] == "win_macro_1"


def test_save_connection_requires_name_and_token(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    missing_name = bridge.save_connection({"host": "192.168.0.20", "port": 8765, "token": "secret"})
    missing_token = bridge.save_connection({"candidate_alias": "win_macro_1", "host": "192.168.0.20", "port": 8765})

    assert missing_name["failure_code"] == "PYAUTOGUI_CANDIDATE_ALIAS_REQUIRED"
    assert missing_token["failure_code"] == "PYAUTOGUI_TOKEN_REQUIRED"


def test_select_and_delete_saved_candidate(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    bridge.save_connection({"candidate_alias": "win_a", "host": "192.168.0.20", "port": 8765, "token": "secret-a"})
    bridge.save_connection({"candidate_alias": "win_b", "host": "192.168.0.21", "port": 8765, "token": "secret-b"})

    selected = bridge.select_candidate({"candidate_alias": "win_a"})
    assert selected["selected_candidate"] == "win_a"
    assert selected["bridge_url"] == "http://192.168.0.20:8765"

    deleted = bridge.delete_candidate({"candidate_alias": "win_a"})
    assert deleted["selected_candidate"] == "win_b"
    assert len(deleted["candidates"]) == 1
    assert deleted["candidates"][0]["candidate_alias"] == "win_b"


def test_select_delete_unknown_candidate_reports_clear_error(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    selected = bridge.select_candidate({"candidate_alias": "missing"})
    deleted = bridge.delete_candidate({"candidate_alias": "missing"})

    assert selected["failure_code"] == "PYAUTOGUI_CANDIDATE_NOT_FOUND"
    assert deleted["failure_code"] == "PYAUTOGUI_CANDIDATE_NOT_FOUND"


def test_register_equipment_tools_exposes_pyautogui_tools(tmp_path: Path) -> None:
    tools = ToolRegistry()
    register_equipment_tools(
        tools,
        {
            "devices": {
                "equipment": {
                    "mode": "simulator",
                    "windows_pyautogui": {"connection_memory_path": str(tmp_path / "conn.json")},
                }
            }
        },
        repo_root=tmp_path,
    )

    assert "equipment.pyautogui.health" in tools.list_tools()
    assert "equipment.pyautogui.list_programs" in tools.list_tools()
    assert "equipment.pyautogui.run" in tools.list_tools()
    assert tools.call("equipment.pyautogui.list_programs", {})["programs"][0]["program_id"] == "program1"


def test_explicit_subnet_scan_targets_are_bounded() -> None:
    targets = local_ipv4_scan_targets(port=8765, subnet="192.0.2.0/30", max_hosts=10)

    assert [item["host"] for item in targets] == ["192.0.2.1", "192.0.2.2"]


@pytest.mark.asyncio
async def test_discovery_requires_token(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = await discover_windows_pyautogui_bridges(bridge.config, subnet="192.0.2.0/30", token="")

    assert response["ok"] is False
    assert response["failure_code"] == "PYAUTOGUI_TOKEN_REQUIRED"
    assert response["candidates"] == []
