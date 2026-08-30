"""Unit tests for Windows PyAutoGUI equipment bridge."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from device_bridges.windows_pyautogui_bridge import (
    WindowsPyAutoGUIBridge,
    WindowsPyAutoGUIBridgeConfig,
    discover_windows_pyautogui_bridges,
    local_ipv4_scan_targets,
)
from mcp_tools.equipment_tools import register_equipment_tools
from mcp_tools.tool_registry import ToolRegistry
from utils.windows_bridge_release import load_release_manifest


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


def test_live_execute_response_timeout_is_effect_unknown_and_not_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)

    class _Client:
        def __init__(self, timeout: float) -> None:
            assert timeout == bridge.config.request_timeout_sec

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, *args: object, **kwargs: object) -> None:
            raise httpx.ReadTimeout("response timeout after request dispatch")

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)

    result = bridge._live_post("equipment.pyautogui.run", "/execute", {"program_id": "program1"})

    assert result["ok"] is False
    assert result["status"] == "effect_unknown"
    assert result["failure_code"] == "PYAUTOGUI_EFFECT_UNKNOWN"
    assert result["attempted"] is True
    assert result["retryable"] is False


def test_live_bridge_lists_and_fetches_saved_recordings_from_selected_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live")
    calls: list[tuple[str, str]] = []

    def fake_live_get(tool: str, path: str, _connection_payload: dict | None = None) -> dict:
        calls.append((tool, path))
        if path == "/recordings":
            return {"ok": True, "recordings": [{"recording_id": "rec-001", "status": "saved"}]}
        return {
            "ok": True,
            "schema": "atr.equipment_recording_package.v1",
            "recording": {
                "schema": "atr.equipment_recording.v3",
                "recording_id": "rec-001",
                "status": "saved",
                "events": [],
            },
            "artifacts": [],
        }

    monkeypatch.setattr(bridge, "_live_precheck", lambda **_kwargs: None)
    monkeypatch.setattr(bridge, "_live_get", fake_live_get)

    listed = bridge.list_recordings({"force_live_bridge": True})
    fetched = bridge.get_recording({"recording_id": "rec-001", "force_live_bridge": True})

    assert listed["recordings"][0]["recording_id"] == "rec-001"
    assert fetched["recording_id"] == "rec-001"
    assert Path(fetched["import_manifest_path"]).is_file()
    assert calls == [
        ("equipment.pyautogui.list_recordings", "/recordings"),
        ("equipment.pyautogui.get_recording", "/recordings/rec-001/package"),
    ]


def test_live_recording_package_is_imported_and_artifact_paths_are_rewritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live")
    raw = b"event-frame"
    source_path = "C:/ATR/recordings/rec-001/timeline/event_keyframes/event-0001.jpg"
    package = {
        "ok": True,
        "schema": "atr.equipment_recording_package.v1",
        "recording": {
            "schema": "atr.equipment_recording.v3",
            "recording_id": "rec-001",
            "status": "saved",
            "events": [{"frame_evidence": {"artifact_path": source_path, "sha256": hashlib.sha256(raw).hexdigest()}}],
        },
        "artifacts": [
            {
                "relative_path": "timeline/event_keyframes/event-0001.jpg",
                "source_path": source_path,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "media_type": "image/jpeg",
                "data_base64": base64.b64encode(raw).decode("ascii"),
            }
        ],
    }
    monkeypatch.setattr(bridge, "_live_precheck", lambda **_kwargs: None)
    monkeypatch.setattr(bridge, "_live_get", lambda *_args, **_kwargs: package)

    imported = bridge.get_recording({"recording_id": "rec-001", "force_live_bridge": True})
    local_path = Path(imported["events"][0]["frame_evidence"]["artifact_path"])

    assert imported["ok"] is True
    assert local_path.is_file()
    assert local_path.read_bytes() == raw
    assert imported["artifact_import"]["verified_count"] == 1


def test_live_recording_package_rejects_tampered_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live")
    package = {
        "ok": True,
        "schema": "atr.equipment_recording_package.v1",
        "recording": {"recording_id": "rec-001", "events": []},
        "artifacts": [
            {
                "relative_path": "timeline/event.jpg",
                "source_path": "C:/ATR/recordings/rec-001/timeline/event.jpg",
                "sha256": "0" * 64,
                "size_bytes": 8,
                "data_base64": base64.b64encode(b"tampered").decode("ascii"),
            }
        ],
    }
    monkeypatch.setattr(bridge, "_live_precheck", lambda **_kwargs: None)
    monkeypatch.setattr(bridge, "_live_get", lambda *_args, **_kwargs: package)

    result = bridge.get_recording({"recording_id": "rec-001", "force_live_bridge": True})

    assert result["ok"] is False
    assert result["failure_code"] == "PYAUTOGUI_RECORDING_ARTIFACT_INTEGRITY_FAILED"


def test_live_recording_package_rejects_inconsistent_package_totals(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, mode="live")
    raw = b"frame"
    package = {
        "ok": True,
        "schema": "atr.equipment_recording_package.v1",
        "recording": {"recording_id": "rec-001", "events": []},
        "artifact_count": 2,
        "total_bytes": len(raw) + 1,
        "artifacts": [{
            "relative_path": "timeline/frame.jpg",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "data_base64": base64.b64encode(raw).decode("ascii"),
        }],
    }

    result = bridge._import_recording_package(package)

    assert result["ok"] is False
    assert result["failure_code"] == "PYAUTOGUI_RECORDING_PACKAGE_INTEGRITY_FAILED"


def test_live_recording_package_rejects_malformed_declared_size_without_raising(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, mode="live")
    raw = b"frame"
    package = {
        "ok": True,
        "schema": "atr.equipment_recording_package.v1",
        "recording": {"recording_id": "rec-001", "events": []},
        "artifact_count": 1,
        "total_bytes": len(raw),
        "artifacts": [{
            "relative_path": "timeline/frame.jpg",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": "not-an-integer",
            "data_base64": base64.b64encode(raw).decode("ascii"),
        }],
    }

    result = bridge._import_recording_package(package)

    assert result["ok"] is False
    assert result["failure_code"] == "PYAUTOGUI_RECORDING_ARTIFACT_INTEGRITY_FAILED"


def test_live_recording_import_accepts_complete_timeline_beyond_old_artifact_count_cap(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, mode="live")
    raw = b"x"
    digest = hashlib.sha256(raw).hexdigest()
    artifacts = [
        {
            "relative_path": f"frames/periodic/frame-{index:08d}.jpg",
            "source_path": f"C:/ATR/recordings/rec-001/frames/periodic/frame-{index:08d}.jpg",
            "sha256": digest,
            "size_bytes": 1,
            "data_base64": base64.b64encode(raw).decode("ascii"),
        }
        for index in range(4100)
    ]
    package = {
        "ok": True,
        "schema": "atr.equipment_recording_package.v1",
        "recording": {"recording_id": "rec-001", "events": []},
        "artifact_count": len(artifacts),
        "total_bytes": len(artifacts),
        "artifacts": artifacts,
    }

    result = bridge._import_recording_package(package)

    assert result["ok"] is True
    assert result["artifact_import"]["verified_count"] == 4100


def test_live_recording_package_failure_does_not_fallback_to_unverified_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live")
    calls: list[str] = []

    def fake_get(
        _tool: str, path: str, _connection_payload: dict | None = None, **_kwargs: object
    ) -> dict[str, object]:
        calls.append(path)
        return {
            "ok": False,
            "status": "blocked",
            "failure_code": "PYAUTOGUI_RECORDING_PACKAGE_INTEGRITY_FAILED",
        }

    monkeypatch.setattr(bridge, "_live_precheck", lambda **_kwargs: None)
    monkeypatch.setattr(bridge, "_live_get", fake_get)

    result = bridge.get_recording({"recording_id": "rec-001", "force_live_bridge": True})

    assert result["ok"] is False
    assert result["failure_code"] == "PYAUTOGUI_RECORDING_PACKAGE_INTEGRITY_FAILED"
    assert calls == ["/recordings/rec-001/package"]


def test_requested_bridge_id_resolves_exact_candidate_without_changing_selection(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    memory = {
        "selected_candidate": "worker-a",
        "candidates": {
            "worker-a": {
                "bridge_id": "worker-a",
                "bridge_url": "http://192.168.50.10:8765",
                "internal_key": "1111",
                "allow_live_execute": True,
            },
            "worker-b": {
                "bridge_id": "worker-b",
                "bridge_url": "http://192.168.50.11:8765",
                "internal_key": "2222",
                "allow_live_execute": True,
            },
        },
    }
    bridge.config.connection_memory_path.write_text(json.dumps(memory), encoding="utf-8")

    requested = {"bridge_id": "worker-b", "runtime_mode": "live"}
    assert bridge._bridge_url(requested) == "http://192.168.50.11:8765"
    assert bridge._token(requested) == "2222"
    assert bridge._live_precheck(require_execute=True, payload=requested) is None
    assert bridge.load_connection_memory()["selected_candidate"] == "worker-a"


def test_unknown_requested_bridge_id_is_blocked_instead_of_using_selected_candidate(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    bridge.config.connection_memory_path.write_text(
        json.dumps(
            {
                "selected_candidate": "worker-a",
                "candidates": {
                    "worker-a": {
                        "bridge_url": "http://192.168.50.10:8765",
                        "internal_key": "1111",
                        "allow_live_execute": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = bridge._live_precheck(
        require_execute=True,
        payload={"bridge_id": "missing-worker", "runtime_mode": "live"},
    )

    assert result is not None
    assert result["failure_code"] == "PYAUTOGUI_CANDIDATE_NOT_FOUND"


def test_worker_update_status_targets_exact_saved_candidate_and_compares_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    bridge.config.connection_memory_path.write_text(
        json.dumps(
            {
                "selected_candidate": "worker-a",
                "candidates": {
                    "worker-a": {"bridge_url": "http://192.168.50.10:8765", "internal_key": "a"},
                    "worker-b": {"bridge_url": "http://192.168.50.11:8765", "internal_key": "b"},
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []
    monkeypatch.setattr(bridge, "_live_precheck", lambda **_kwargs: None)
    monkeypatch.setattr(
        bridge,
        "_live_get",
        lambda _tool, path, payload: calls.append({"path": path, "payload": dict(payload)})
        or {"ok": True, "current_version": "2026.08.27.1", "status": "ready"},
    )

    result = bridge.worker_update_status({"candidate_alias": "worker-b"})

    assert calls == [{"path": "/update/status", "payload": {"candidate_alias": "worker-b", "bridge_id": "worker-b", "runtime_mode": "live", "force_live_bridge": True}}]
    assert result["latest_version"] == load_release_manifest()["version"]
    assert result["update_available"] is True
    assert bridge.load_connection_memory()["selected_candidate"] == "worker-a"


def test_update_worker_stages_then_applies_same_release_to_exact_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    calls: list[tuple[str, str, dict, dict]] = []
    release = {"schema": "atr.windows_bridge_update_package.v1", "version": "2026.08.28.2", "files": [], "package_sha256": "a" * 64}
    monkeypatch.setattr(bridge, "_live_precheck", lambda **_kwargs: None)
    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.build_release_package", lambda: release)

    def post(tool: str, path: str, payload: dict, connection: dict) -> dict:
        calls.append((tool, path, payload, dict(connection)))
        return {"ok": True, "status": "staged" if path.endswith("stage") else "update_restarting"}

    monkeypatch.setattr(bridge, "_live_post", post)

    result = bridge.update_worker({"candidate_alias": "worker-b"})

    assert result["ok"] is True
    assert [call[1] for call in calls] == ["/update/stage", "/update/apply"]
    assert calls[0][2] is release
    assert all(call[3]["bridge_id"] == "worker-b" for call in calls)


def test_rollback_worker_calls_only_exact_worker_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(bridge, "_live_precheck", lambda **_kwargs: None)
    monkeypatch.setattr(
        bridge,
        "_live_post",
        lambda _tool, path, _payload, connection: calls.append((path, dict(connection)))
        or {"ok": True, "status": "rollback_restarting"},
    )

    result = bridge.rollback_worker({"candidate_alias": "worker-b"})

    assert result["ok"] is True
    assert calls == [("/update/rollback", {"candidate_alias": "worker-b", "bridge_id": "worker-b", "runtime_mode": "live", "force_live_bridge": True})]


def test_simulator_registers_and_executes_compiled_skill_program(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    program = {
        "schema": "atr.pyautogui_program.v1",
        "program_id": "program1_skill_1_0_0_segment_001",
        "name": "Program 1 Skill segment",
        "description": "compiled segment",
        "enabled": True,
        "program_type": "macro",
        "safe_test": True,
        "sequence": [{"action": "press", "key": "enter"}, {"action": "log", "message": "done"}],
    }

    registered = bridge.register_program({"runtime_mode": "test", "program": program})
    result = bridge.run({"runtime_mode": "test", "program_id": program["program_id"], "sequence_id": "skill-seq-1"})

    assert registered["ok"] is True
    assert registered["program_sha256"]
    assert result["ok"] is True
    assert result["program_id"] == program["program_id"]


def test_live_program_registration_preserves_worker_computed_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live")
    program = {
        "schema": "atr.pyautogui_program.v1",
        "program_id": "worker_digest_probe",
        "name": "Worker digest probe",
        "sequence": [{"action": "press", "key": "enter"}],
    }
    monkeypatch.setattr(bridge, "_live_precheck", lambda **kwargs: None)
    sent: list[tuple[object, ...]] = []

    def _live_post(*args, **kwargs):
        sent.append(args)
        return {
            "ok": True,
            "status": "registered",
            "program_id": "worker_digest_probe",
            "program_sha256": "a" * 64,
        }

    monkeypatch.setattr(bridge, "_live_post", _live_post)

    result = bridge.register_program({"program": program, "force_live_bridge": True})

    assert result["program_sha256"] == "a" * 64
    deployment_payload = sent[0][2]
    assert deployment_payload["program"] == program
    assert deployment_payload["_atr_deployment"]["managed_by"] == "atr_equipment_skill"
    assert deployment_payload["_atr_deployment"]["program_sha256"] == hashlib.sha256(
        json.dumps(program, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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


def test_wait_until_image_is_allowed_for_visual_protocol_sequences(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.run(
        {
            "runtime_mode": "test",
            "sequence": [
                {"action": "locate_image", "target": "ready_state"},
                {"action": "wait_until_image", "target": "running_state", "timeout_s": 0.1},
            ],
        }
    )

    assert response["ok"] is True
    assert response["failure_code"] is None
    assert [item["step"] for item in response["step_trace"]][-2:] == ["EXECUTE_STEP", "DONE"]


def test_text_assertion_actions_are_allowed_for_visual_protocol_sequences(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.run(
        {
            "runtime_mode": "test",
            "sequence": [
                {"action": "assert_text", "target": "status_text", "contains": "Ready"},
                {"action": "wait_until_text", "target": "running_text", "contains": "Running", "timeout_s": 0.1},
            ],
        }
    )

    assert response["ok"] is True
    assert response["failure_code"] is None
    assert [item["step"] for item in response["step_trace"]][-2:] == ["EXECUTE_STEP", "DONE"]


def test_unknown_program_rejected_in_simulator(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.run({"runtime_mode": "test", "program_id": "program404"})

    assert response["ok"] is False
    assert response["failure_code"] == "PYAUTOGUI_PROGRAM_NOT_FOUND"


def test_live_delete_program_preserves_remote_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "token")

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def delete(self, url: str, headers: dict[str, str]) -> httpx.Response:
            request = httpx.Request("DELETE", url, headers=headers)
            return httpx.Response(
                404,
                request=request,
                json={
                    "ok": False,
                    "status": "not_found",
                    "failure_code": "PYAUTOGUI_PROGRAM_NOT_FOUND",
                    "program_id": "missing_skill_program",
                },
            )

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)

    response = bridge.delete_program(
        {"program_id": "missing_skill_program", "runtime_mode": "live", "force_live_bridge": True}
    )

    assert response["ok"] is False
    assert response["status"] == "not_found"
    assert response["failure_code"] == "PYAUTOGUI_PROGRAM_NOT_FOUND"
    assert response["program_id"] == "missing_skill_program"


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


def test_pair_connection_exchanges_four_digit_code_and_saves_internal_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live")

    class _Reply:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True, "status": "paired", "internal_key": "worker-internal-key"}

    class _Client:
        def __init__(self, timeout: float) -> None:
            assert timeout == bridge.config.request_timeout_sec

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, json: dict[str, str]) -> _Reply:
            assert url == "http://192.168.50.58:8765/pairing/complete"
            assert json == {"pairing_code": "0427"}
            return _Reply()

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)

    result = bridge.pair_connection(
        {
            "candidate_alias": "utm_worker",
            "host": "192.168.50.58",
            "port": 8765,
            "pairing_code": "0427",
        }
    )

    assert result["ok"] is True
    assert result["selected_candidate"] == "utm_worker"
    memory = json.loads(bridge.config.connection_memory_path.read_text(encoding="utf-8"))
    assert memory["candidates"]["utm_worker"]["internal_key"] == "worker-internal-key"
    assert "token" not in memory["candidates"]["utm_worker"]
    assert "0427" not in bridge.config.connection_memory_path.read_text(encoding="utf-8")
    assert bridge.connection_status()["paired"] is True


def test_paired_internal_key_takes_precedence_over_legacy_environment_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live")
    bridge.save_connection(
        {
            "candidate_alias": "paired_worker",
            "host": "192.168.50.58",
            "port": 8765,
            "internal_key": "paired-key",
        }
    )
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "legacy-env-token")

    assert bridge._token() == "paired-key"


def test_pair_connection_rejects_public_or_credentialed_bridge_urls(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, mode="live")

    public = bridge.pair_connection(
        {
            "candidate_alias": "public",
            "bridge_url": "https://example.com",
            "pairing_code": "0427",
        }
    )
    credentialed = bridge.pair_connection(
        {
            "candidate_alias": "credentialed",
            "bridge_url": "http://user:pass@127.0.0.1:8765",
            "pairing_code": "0427",
        }
    )

    assert public["failure_code"] == "PYAUTOGUI_BRIDGE_URL_NOT_PRIVATE"
    assert credentialed["failure_code"] == "PYAUTOGUI_BRIDGE_URL_INVALID"


def test_save_local_candidate_preserves_platform_metadata_without_selecting(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge.save_connection({"candidate_alias": "win_a", "host": "192.168.0.20", "port": 8765, "token": "secret-a"})

    status = bridge.save_connection(
        {
            "candidate_alias": "local_development",
            "host": "127.0.0.1",
            "port": 8766,
            "token": "local-secret",
            "platform": "linux",
            "scope": "localhost",
            "managed_local": True,
            "select": False,
        }
    )

    assert status["selected_candidate"] == "win_a"
    local = next(item for item in status["candidates"] if item["candidate_alias"] == "local_development")
    assert local["platform"] == "linux"
    assert local["scope"] == "localhost"
    assert local["managed_local"] is True


def test_first_unselected_candidate_remains_standby(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    status = bridge.save_connection(
        {
            "candidate_alias": "local_development",
            "host": "127.0.0.1",
            "port": 8766,
            "token": "local-secret",
            "select": False,
        }
    )

    assert status["selected"] is False
    assert status["selected_candidate"] == ""
    assert status["candidates"][0]["selected"] is False


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


def test_live_health_normalizes_bridge_identity_and_latency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path, mode="live")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://192.168.50.58:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "token")

    class _Reply:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "ok": True,
                "status": "ready",
                "bridge": "windows_pyautogui",
                "pyautogui": {"available": True, "failsafe": True, "pause": 0.1},
                "server_version": "WindowsPyAutoGUIBridge/0.1",
                "script_version": "windows_pyautogui_bridge_server.py:utm_visual_control_v1",
            }

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> _Reply:
            assert url == "http://192.168.50.58:8765/health"
            assert headers["X-Bridge-Token"] == "token"
            return _Reply()

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)

    response = bridge.health({"runtime_mode": "live"})

    assert response["ok"] is True
    assert response["bridge_url"] == "http://192.168.50.58:8765"
    assert response["bridge_host"] == "192.168.50.58"
    assert response["client_latency_ms"] >= 0
    assert response["server_version"] == "WindowsPyAutoGUIBridge/0.1"
    assert response["script_version"] == "windows_pyautogui_bridge_server.py:utm_visual_control_v1"


def test_bridge_ui_proxy_injects_saved_token_without_accepting_browser_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path, mode="live")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://192.168.50.58:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "server-only-token")

    class _Reply:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        content = b"<html>bridge</html>"

    class _Client:
        def __init__(self, timeout: float, follow_redirects: bool) -> None:
            assert timeout == bridge.config.request_timeout_sec
            assert follow_redirects is False

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def request(self, method: str, url: str, headers: dict[str, str], content: bytes) -> _Reply:
            assert method == "GET"
            assert url == "http://192.168.50.58:8765/health"
            assert headers["X-Bridge-Token"] == "server-only-token"
            assert content == b""
            return _Reply()

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)

    response = bridge.proxy_ui_request(method="GET", resource_path="health")

    assert response["ok"] is True
    assert response["status_code"] == 200
    assert response["content"] == b"<html>bridge</html>"


def test_bridge_ui_proxy_forwards_delete_with_saved_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(tmp_path, mode="live")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://192.168.50.58:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "server-only-token")

    class _Reply:
        status_code = 200
        headers = {"content-type": "application/json; charset=utf-8"}
        content = b'{"ok":true,"status":"deleted"}'

    class _Client:
        def __init__(self, timeout: float, follow_redirects: bool) -> None:
            assert timeout == bridge.config.request_timeout_sec
            assert follow_redirects is False

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def request(self, method: str, url: str, headers: dict[str, str], content: bytes) -> _Reply:
            assert method == "DELETE"
            assert url == "http://192.168.50.58:8765/programs/custom-probe?source=atr"
            assert headers["X-Bridge-Token"] == "server-only-token"
            assert content == b""
            return _Reply()

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)

    response = bridge.proxy_ui_request(
        method="DELETE",
        resource_path="programs/custom-probe",
        query_string="source=atr",
    )

    assert response["ok"] is True
    assert response["status_code"] == 200
    assert response["content"] == b'{"ok":true,"status":"deleted"}'


def test_bridge_ui_proxy_still_rejects_methods_outside_allowlist(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, mode="live")

    response = bridge.proxy_ui_request(method="PATCH", resource_path="programs/custom-probe")
    payload = json.loads(response["content"])

    assert response["status_code"] == 405
    assert payload["failure_code"] == "PYAUTOGUI_UI_METHOD_NOT_ALLOWED"
    assert payload["message"] == "Only GET, POST, and DELETE are supported."


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
    assert "equipment.pyautogui.screenshot" in tools.list_tools()
    assert "equipment.pyautogui.list_locators" in tools.list_tools()
    assert "equipment.pyautogui.capture_locator" in tools.list_tools()
    assert "equipment.pyautogui.utm_profile" in tools.list_tools()
    assert "equipment.pyautogui.save_utm_profile" in tools.list_tools()
    assert "equipment.runtime.current" in tools.list_tools()
    assert "equipment.runtime.list" in tools.list_tools()
    assert tools.call("equipment.pyautogui.list_programs", {})["programs"][0]["program_id"] == "program1"
    assert tools.call("equipment.runtime.current", {}) == {
        "ok": True,
        "execution": None,
        "projection": None,
    }


def test_explicit_subnet_scan_targets_are_bounded() -> None:
    targets = local_ipv4_scan_targets(port=8765, subnet="192.0.2.0/30", max_hosts=10)

    assert [item["host"] for item in targets] == ["192.0.2.1", "192.0.2.2"]


@pytest.mark.asyncio
async def test_discovery_uses_public_discovery_endpoint_without_pairing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _bridge(tmp_path)

    class _Reply:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "ok": True,
                "status": "ready",
                "bridge": "windows_pyautogui",
                "server_version": "WindowsPyAutoGUIBridge/2026.08.29.1",
                "pairing": {"paired": False},
            }

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str]) -> _Reply:
            assert url == "http://192.0.2.1:8765/discovery"
            assert "X-Bridge-Token" not in headers
            return _Reply()

    monkeypatch.setattr(
        "device_bridges.windows_pyautogui_bridge.local_ipv4_scan_targets",
        lambda **_kwargs: [{"host": "192.0.2.1", "port": 8765, "bridge_url": "http://192.0.2.1:8765"}],
    )
    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.AsyncClient", _Client)

    response = await discover_windows_pyautogui_bridges(bridge.config, subnet="192.0.2.0/30", token="")

    assert response["ok"] is True
    assert response["candidates"][0]["bridge_url"] == "http://192.0.2.1:8765"
    assert response["candidates"][0]["pairing_required"] is True
    assert response["candidates"][0]["server_version"] == "WindowsPyAutoGUIBridge/2026.08.29.1"


def test_simulator_utm_protocol_returns_csv_artifact(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.run(
        {
            "runtime_mode": "test",
            "program_id": "utm_compression_start_v1",
            "sequence_id": "seq-utm",
            "run_id": "run-utm-test",
            "experiment_spec": {"specimen_id": "specimen-utm-001"},
        }
    )

    assert response["ok"] is True
    assert response["status"] == "verified_complete"
    assert response["program_id"] == "utm_compression_start_v1"
    assert Path(response["result_file"]).exists()
    assert response["data_acquisition"]["row_count_probe"] == 80
    assert response["cross_checks"]["data_parse_probe_ok"] is True
    assert response["output_artifacts"][0]["kind"] == "utm_csv"


def test_configured_programs_are_merged_with_default_utm_protocols(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    programs = bridge.list_programs({"runtime_mode": "test"})["programs"]
    program_by_id = {item["program_id"]: item for item in programs}

    assert "program1" in program_by_id
    expected_protocols = {"utm_compression_start_v1", "utm_export_csv_v1", "utm_manual_save_csv_v1", "utm_stop_or_abort_v1"}
    assert expected_protocols.issubset(program_by_id)

    compression = program_by_id["utm_compression_start_v1"]
    assert compression["program_type"] == "utm_protocol"
    assert compression["target_app"] == "UTM software"
    assert compression["target_window"] == "main_window_title_or_regex"
    assert compression["preconditions"] == ["windows_bridge_ready", "utm_app_visible", "specimen_verified_on_fixture", "robot_clear_of_utm"]
    assert compression["expected_screen_before"][0]["name"] == "ready_state"
    assert {item.get("target") for item in compression["sequence"] if isinstance(item, dict)} >= {"ready_state", "start_button", "running_state", "complete_state"}
    assert compression["save_policy"]["manual_save_required_if_no_artifact"] is True
    assert compression["output_artifacts"][0]["kind"] == "utm_csv"
    assert compression["safe_abort"]["program_id"] == "utm_stop_or_abort_v1"

    export = program_by_id["utm_export_csv_v1"]
    assert export["program_type"] == "utm_export"
    assert export["expected_screen_before"][0]["name"] == "complete_state"
    assert export["save_policy"]["save_method"] == "export_menu"
    assert export["safe_abort"]["program_id"] == "utm_stop_or_abort_v1"

    manual = program_by_id["utm_manual_save_csv_v1"]
    assert manual["program_type"] == "utm_export"
    assert manual["save_policy"]["save_method"] == "manual_save_dialog"
    assert manual["save_policy"]["manual_save_required_if_no_artifact"] is False

    abort = program_by_id["utm_stop_or_abort_v1"]
    assert abort["program_type"] == "utm_abort"
    assert abort["preconditions"] == ["windows_bridge_ready", "utm_app_visible_or_focused"]
    assert abort["expected_screen_before"][0]["name"] == "running_or_unknown_state"
    assert abort["expected_screen_after"][0]["name"] == "stopped_or_idle_state"
    assert abort["save_policy"]["save_method"] == "not_applicable"
    assert abort["output_artifacts"] == []
    assert abort["sequence"][0]["action"] == "press"
    assert abort["safe_abort"]["action"] == "press"


def test_live_verified_complete_response_is_success(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)

    response = bridge._normalize_live_response(
        "equipment.pyautogui.run",
        {"status": "verified_complete", "program_id": "utm_compression_start_v1", "step_trace": []},
    )

    assert response["ok"] is True
    assert response["failure_code"] is None


def test_runtime_program_payload_merges_registered_utm_profile(tmp_path: Path) -> None:
    cfg = WindowsPyAutoGUIBridgeConfig.from_devices_config(
        {
            "devices": {
                "equipment": {
                    "mode": "live",
                    "provider": "windows_pyautogui",
                    "windows_pyautogui": {
                        "connection_memory_path": str(tmp_path / "conn.json"),
                        "registered_programs": {
                            "utm_compression_start_v1": {
                                "program_type": "utm_protocol",
                                "sequence": [{"action": "assert_visible", "target": "ready_state"}],
                                "locators": {"ready_state": {"image_path": "C:/ATR/locators/ready.png", "confidence": 0.83}},
                                "export_glob": "specimen*.csv",
                                "artifact_timeout_s": 90,
                                "stable_for_sec": 3.0,
                                "expected_export_path": "C:/ATR/utm_exports/run-live/specimen.csv",
                                "require_window_focus": True,
                                "manual_save_required_if_no_artifact": False,
                                "target_window_regex": ".*UTM.*",
                                "require_screen_assertions": True,
                            }
                        },
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    bridge = WindowsPyAutoGUIBridge(cfg)

    payload = bridge._runtime_program_payload({"program_id": "utm_compression_start_v1", "runtime_mode": "live"})

    assert payload["sequence"] == [{"action": "assert_visible", "target": "ready_state"}]
    assert payload["locators"]["ready_state"]["image_path"] == "C:/ATR/locators/ready.png"
    assert payload["export_glob"] == "specimen*.csv"
    assert payload["artifact_timeout_s"] == 90
    assert payload["stable_for_sec"] == 3.0
    assert payload["expected_export_path"].endswith("specimen.csv")
    assert payload["require_window_focus"] is True
    assert payload["manual_save_required_if_no_artifact"] is False
    assert payload["target_window_regex"] == ".*UTM.*"
    assert payload["require_screen_assertions"] is True



def test_simulator_screenshot_returns_png_artifact(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.screenshot({"runtime_mode": "test", "checkpoint": "manual"})

    assert response["ok"] is True
    assert response["status"] == "captured"
    artifact = response["output_artifacts"][0]
    assert artifact["kind"] == "screen_png"
    assert Path(artifact["local_path"]).exists()


def test_simulator_capture_locator_returns_locator_override(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.capture_locator(
        {
            "runtime_mode": "test",
            "program_id": "utm_compression_start_v1",
            "name": "start_button",
            "region": [10, 20, 120, 60],
            "confidence": 0.85,
        }
    )

    assert response["ok"] is True
    assert response["locator_name"] == "start_button"
    assert response["locator"]["confidence"] == 0.85
    assert response["locator"]["region"] == [10, 20, 120, 60]
    assert Path(response["locator"]["image_path"]).exists()

def test_utm_profile_memory_merges_into_registered_program(tmp_path: Path) -> None:
    profile_path = tmp_path / "equipment_utm_profile.json"
    profile_path.write_text(
        '{"program_id":"utm_compression_start_v1","export_glob":"run*.csv","artifact_timeout_s":120,'
        '"stable_for_sec":4.0,"expected_export_path":"C:/ATR/utm_exports/run/specimen.csv",'
        '"require_window_focus":true,"manual_save_required_if_no_artifact":false,'
        '"target_window":"UTM Controller","require_screen_assertions":true,'
        '"locators":{"ready_state":{"image_path":"C:/ATR/locators/ready.png","confidence":0.91}}}',
        encoding="utf-8",
    )
    cfg = WindowsPyAutoGUIBridgeConfig.from_devices_config(
        {
            "devices": {
                "equipment": {
                    "mode": "live",
                    "windows_pyautogui": {
                        "connection_memory_path": str(tmp_path / "conn.json"),
                        "utm_profile_memory_path": str(profile_path),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    bridge = WindowsPyAutoGUIBridge(cfg)

    payload = bridge._runtime_program_payload({"program_id": "utm_compression_start_v1", "runtime_mode": "live"})

    assert payload["export_glob"] == "run*.csv"
    assert payload["artifact_timeout_s"] == 120
    assert payload["stable_for_sec"] == 4.0
    assert payload["expected_export_path"].endswith("specimen.csv")
    assert payload["require_window_focus"] is True
    assert payload["manual_save_required_if_no_artifact"] is False
    assert payload["target_window"] == "UTM Controller"
    assert payload["require_screen_assertions"] is True
    assert payload["locators"]["ready_state"]["confidence"] == 0.91
    assert bridge.utm_profile_status()["source"] == "memory"

    response = bridge.run({"runtime_mode": "test", "program_id": "utm_compression_start_v1"})
    assert response["control_profile"]["profile_memory_applied"] is True
    assert response["control_profile"]["export_glob"] == "run*.csv"
    assert response["control_profile"]["locator_names"] == ["ready_state"]


def test_save_utm_profile_persists_and_updates_runtime_payload(tmp_path: Path) -> None:
    cfg = WindowsPyAutoGUIBridgeConfig.from_devices_config(
        {
            "devices": {
                "equipment": {
                    "mode": "simulator",
                    "windows_pyautogui": {
                        "connection_memory_path": str(tmp_path / "conn.json"),
                        "utm_profile_memory_path": str(tmp_path / "equipment_utm_profile.json"),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    bridge = WindowsPyAutoGUIBridge(cfg)

    saved = bridge.save_utm_profile(
        {
            "program_id": "utm_compression_start_v1",
            "export_glob": "specimen-final*.csv",
            "artifact_timeout_s": 75,
            "stable_for_sec": 2.5,
            "expected_export_path": "C:/ATR/utm_exports/final/specimen-final.csv",
            "require_window_focus": True,
            "manual_save_required_if_no_artifact": False,
            "target_window_regex": ".*UTM.*",
            "require_screen_assertions": True,
            "locators": {"start_button": {"image_path": "C:/ATR/locators/start.png", "confidence": 0.87}},
        }
    )
    payload = bridge._runtime_program_payload({"program_id": "utm_compression_start_v1", "runtime_mode": "live"})

    assert saved["ok"] is True
    assert saved["status"] == "saved"
    assert cfg.utm_profile_memory_path.exists()
    assert payload["export_glob"] == "specimen-final*.csv"
    assert payload["expected_export_path"].endswith("specimen-final.csv")
    assert payload["require_window_focus"] is True
    assert payload["manual_save_required_if_no_artifact"] is False
    assert payload["target_window_regex"] == ".*UTM.*"
    assert payload["require_screen_assertions"] is True
    assert payload["locators"]["start_button"]["image_path"] == "C:/ATR/locators/start.png"


def test_live_artifact_pull_updates_data_acquisition_linux_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "token")
    csv_bytes = b"time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.1,2.5\n"
    screen_bytes = b"fake-png"
    digest = hashlib.sha256(csv_bytes).hexdigest()
    screen_digest = hashlib.sha256(screen_bytes).hexdigest()

    class _Reply:
        def __init__(self, artifact_id: str) -> None:
            self.artifact_id = artifact_id

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            if self.artifact_id == "screen_before_live_001":
                return {
                    "ok": True,
                    "artifact_id": "screen_before_live_001",
                    "kind": "screen_png",
                    "filename": "before.png",
                    "windows_path": "C:/ATR/bridge_artifacts/run-live/before.png",
                    "content_base64": base64.b64encode(screen_bytes).decode("ascii"),
                    "content_type": "image/png",
                }
            return {
                "ok": True,
                "artifact_id": "utm_csv_live_001",
                "kind": "utm_csv",
                "filename": "live.csv",
                "windows_path": "C:/ATR/utm_exports/run-live/live.csv",
                "content_base64": base64.b64encode(csv_bytes).decode("ascii"),
                "row_count_probe": 2,
                "columns_probe": ["time_s", "displacement_mm", "force_N"],
            }

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> _Reply:
            assert headers["X-Bridge-Token"] == "token"
            artifact_id = url.rsplit("/", 1)[-1]
            assert artifact_id in {"utm_csv_live_001", "screen_before_live_001"}
            return _Reply(artifact_id)

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)
    response = bridge._pull_live_artifacts(
        {
            "ok": True,
            "status": "verified_complete",
            "sequence_id": "run-live",
            "output_artifacts": [
                {
                    "artifact_id": "screen_before_live_001",
                    "kind": "screen_png",
                    "filename": "before.png",
                    "windows_path": "C:/ATR/bridge_artifacts/run-live/before.png",
                },
                {
                    "artifact_id": "utm_csv_live_001",
                    "kind": "utm_csv",
                    "filename": "live.csv",
                    "windows_path": "C:/ATR/utm_exports/run-live/live.csv",
                },
            ],
            "data_acquisition": {
                "status": "exported_on_windows",
                "save_method": "manual_save_dialog",
                "save_attempted_by_agent": True,
                "save_confirmation_screen_ok": True,
                "windows_path": "C:/ATR/utm_exports/run-live/live.csv",
            },
        }
    )

    local_path = Path(response["result_file"])
    screen_path = Path(response["output_artifacts"][0]["local_path"])
    assert local_path.exists()
    assert screen_path.exists()
    assert local_path.read_bytes() == csv_bytes
    assert screen_path.read_bytes() == screen_bytes
    assert response["utm_csv_path"] == str(local_path)
    assert response["data_integrity"]["sha256"] == digest
    assert response["output_artifacts"][0]["sha256"] == screen_digest
    assert response["data_acquisition"]["status"] == "pulled_to_linux"
    assert response["data_acquisition"]["linux_path"] == str(local_path)
    assert response["data_acquisition"]["local_path"] == str(local_path)
    assert response["data_acquisition"]["save_method"] == "manual_save_dialog"
    assert response["data_acquisition"]["sha256"] == digest
    assert response["data_acquisition"]["row_count_probe"] == 2
    assert response["data_acquisition"]["local_parse_ok"] is True
    assert response["data_acquisition"]["local_parse_probe"]["ok"] is True
    assert response["data_integrity"]["local_parse_ok"] is True
    assert response["artifact_pull"]["status"] == "complete"
    assert response["artifact_pull"]["attempted_count"] == 2
    assert response["artifact_pull"]["pulled_count"] == 2
    assert response["artifact_pull"]["failed_count"] == 0
    assert response["artifact_pull"]["data_artifact_pulled"] is True
    assert response["artifact_pull"]["screen_artifact_count"] == 1
    assert str(screen_path) in response["artifact_pull"]["screen_artifact_paths"]
    artifact_records = {item["artifact_id"]: item for item in response["artifact_records"]}
    assert artifact_records["screen_before_live_001"]["local_path"] == str(screen_path)
    assert artifact_records["utm_csv_live_001"]["local_path"] == str(local_path)


def test_live_artifact_pull_does_not_promote_unparseable_utm_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "token")
    bad_csv = b"time_s,force_N\n0,0.0\n1,2.5\n"

    class _Reply:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "ok": True,
                "artifact_id": "utm_csv_bad_001",
                "kind": "utm_csv",
                "filename": "bad.csv",
                "windows_path": "C:/ATR/utm_exports/run-live/bad.csv",
                "content_base64": base64.b64encode(bad_csv).decode("ascii"),
                "row_count_probe": 999,
                "columns_probe": ["time_s", "displacement_mm", "force_N"],
            }

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> _Reply:
            assert headers["X-Bridge-Token"] == "token"
            assert url.endswith("/artifacts/utm_csv_bad_001")
            return _Reply()

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)
    response = bridge._pull_live_artifacts(
        {
            "ok": True,
            "status": "verified_complete",
            "sequence_id": "run-live",
            "output_artifacts": [{"artifact_id": "utm_csv_bad_001", "kind": "utm_csv", "filename": "bad.csv"}],
            "data_acquisition": {"status": "exported_on_windows"},
        }
    )

    local_path = Path(response["data_acquisition"]["local_path"])
    assert local_path.exists()
    assert "result_file" not in response
    assert "utm_csv_path" not in response
    assert response["data_acquisition"]["status"] == "pulled_to_linux_parse_failed"
    assert response["data_acquisition"]["artifact_pull_status"] == "pulled_parse_failed"
    assert response["data_acquisition"]["row_count_probe"] == 2
    assert response["data_acquisition"]["columns_probe"] == ["time_s", "force_N"]
    assert response["data_acquisition"]["missing_columns"] == ["displacement_mm"]
    assert response["data_acquisition"]["local_parse_ok"] is False
    assert response["artifact_pull"]["data_artifact_pulled"] is True
    assert response["artifact_pull"]["data_artifact_parse_ok"] is False
    assert response["artifact_pull"]["data_artifact_probe"]["failure_code"] == "UTM_DATA_PARSE_FAILED"
    assert response["artifact_pull"]["pulled_artifacts"][0]["parse_ok"] is False


def test_live_artifact_pull_records_failed_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "token")

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> object:
            raise RuntimeError("bridge down")

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)
    response = bridge._pull_live_artifacts(
        {
            "ok": True,
            "status": "verified_complete",
            "sequence_id": "run-live",
            "output_artifacts": [{"artifact_id": "utm_csv_missing", "kind": "utm_csv", "filename": "missing.csv"}],
            "data_acquisition": {"status": "exported_on_windows"},
        }
    )

    assert response["artifact_pull"]["status"] == "failed"
    assert response["artifact_pull"]["attempted_count"] == 1
    assert response["artifact_pull"]["pulled_count"] == 0
    assert response["artifact_pull"]["failed_count"] == 1
    assert response["artifact_pull"]["failed_artifacts"][0]["artifact_id"] == "utm_csv_missing"
    assert response["artifact_pull"]["failed_artifacts"][0]["reason"] == "ARTIFACT_PULL_FAILED"
    assert response["data_acquisition"]["status"] == "exported_on_windows"
    assert "result_file" not in response


def test_simulator_health_exposes_bridge_audit_paths(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    response = bridge.health({"runtime_mode": "test"})

    assert response["ok"] is True
    assert response["artifacts"]["root"] == str(bridge.config.artifact_dir)
    assert response["artifacts"]["request_log"].endswith("bridge_requests.jsonl")
    assert response["locator_root"].endswith("simulated_locators")
    assert response["utm_export_root"].endswith("simulated_utm_exports")


def test_request_log_simulator_returns_recent_events_without_token_requirement(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    log_path = bridge.config.artifact_dir / "bridge_requests.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        '{"path":"/health","auth_ok":true,"token_header_present":true}\n'
        '{"path":"/execute","auth_ok":true,"token_header_present":true}\n',
        encoding="utf-8",
    )

    response = bridge.request_log({"runtime_mode": "test"})

    assert response["ok"] is True
    assert response["request_log"] == str(log_path)
    assert response["event_count"] == 2
    assert response["recent_paths"] == ["/health", "/execute"]
    assert response["execute_event_seen"] is True
    assert response["execute_event_count"] == 1
    assert [event["path"] for event in response["events"]] == ["/health", "/execute"]


def test_equipment_tool_registry_exposes_request_log(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_equipment_tools(
        registry,
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

    assert "equipment.pyautogui.request_log" in registry.list_tools()
    response = registry.call("equipment.pyautogui.request_log", {"runtime_mode": "test"})
    assert response["ok"] is True
    assert response["request_log"].endswith("bridge_requests.jsonl")


def test_live_artifact_pull_does_not_promote_zero_force_utm_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(tmp_path, mode="live", allow_live=True)
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "token")
    bad_csv = b"time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.1,0.0\n2,0.2,0.0\n"

    class _Reply:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "ok": True,
                "artifact_id": "utm_csv_zero_force_001",
                "kind": "utm_csv",
                "filename": "zero_force.csv",
                "windows_path": "C:/ATR/utm_exports/run-live/zero_force.csv",
                "content_base64": base64.b64encode(bad_csv).decode("ascii"),
                "row_count_probe": 3,
                "columns_probe": ["time_s", "displacement_mm", "force_N"],
            }

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> _Reply:
            assert headers["X-Bridge-Token"] == "token"
            assert url.endswith("/artifacts/utm_csv_zero_force_001")
            return _Reply()

    monkeypatch.setattr("device_bridges.windows_pyautogui_bridge.httpx.Client", _Client)
    response = bridge._pull_live_artifacts(
        {
            "ok": True,
            "status": "verified_complete",
            "sequence_id": "run-live",
            "output_artifacts": [{"artifact_id": "utm_csv_zero_force_001", "kind": "utm_csv", "filename": "zero_force.csv"}],
            "data_acquisition": {"status": "exported_on_windows"},
        }
    )

    assert "result_file" not in response
    assert "utm_csv_path" not in response
    assert response["data_acquisition"]["status"] == "pulled_to_linux_parse_failed"
    assert response["data_acquisition"]["parse_failure_code"] == "UTM_DATA_NO_FORCE_SIGNAL"
    assert response["data_acquisition"]["data_quality"]["force_nonzero"] is False
    assert response["artifact_pull"]["data_artifact_parse_ok"] is False
    assert response["artifact_pull"]["data_artifact_probe"]["failure_code"] == "UTM_DATA_NO_FORCE_SIGNAL"
