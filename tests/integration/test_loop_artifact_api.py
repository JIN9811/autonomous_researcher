"""Historical artifact queries use disk identity, never the current live loop."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from tests.unit.test_agent_artifact_archive import Producer, state


@pytest.mark.asyncio
async def test_existing_artifact_api_filters_loops_and_serves_frozen_files(tmp_path, monkeypatch):
    import app.main as main

    root = tmp_path / "runs"
    source = tmp_path / "artifacts" / "metrics.json"
    source.parent.mkdir()
    ctx = SimpleNamespace(artifact_run_root=root, source=source)
    for loop in (0, 1, 1):
        await Producer().run(state(loop), ctx)
    (root / "run-archive" / "legacy.json").write_text("legacy")
    (root / "run-archive" / "external.txt").symlink_to("/etc/passwd")
    monkeypatch.setattr(main, "controller", SimpleNamespace(_deps=SimpleNamespace(run_root=root)))
    client = TestClient(main.app)
    all_items = client.get("/api/runs/run-archive/artifacts").json()
    assert len(all_items["executions"]) == 3
    assert any(item["name"] == "legacy.json" for item in all_items["artifacts"])
    assert not any(item["name"] == "external.txt" for item in all_items["artifacts"])
    selected = client.get("/api/runs/run-archive/artifacts", params={"loop_index": 0}).json()
    assert len(selected["executions"]) == 1
    assert all(item["loop_index"] == 0 for item in selected["artifacts"])
    metrics = next(item for item in selected["artifacts"] if item["name"].endswith("_metrics.json"))
    assert client.get(metrics["url"]).text == "0"
    retry = client.get("/api/runs/run-archive/artifacts", params={"loop_index": 1, "attempt_index": 2}).json()
    assert len(retry["executions"]) == 1
    assert retry["executions"][0]["attempt_index"] == 2
    assert client.get("/api/runs/run-archive/artifacts", params={"loop_index": -1}).status_code == 400
    empty = client.get("/api/runs/run-archive/artifacts", params={"loop_index": 100}).json()
    assert empty["artifacts"] == [] and empty["executions"] == []
@pytest.mark.asyncio
async def test_telemetry_resolves_the_selected_bridges_custom_archive_root(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import app.main as main
    from agents.base_agent import AgentResult
    from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
    from orchestrator.state import OrchestratorState
    from utils.agent_artifact_archive import archive_agent_run

    config = LeRobotBridgeConfig.from_config({"lerobot": {
        "session_log_root": str(tmp_path / "bridge-logs" / "sessions"),
        "artifact_run_root": str(tmp_path / "archive-root"),
    }}, repo_root=tmp_path)
    # Only path methods are used: no bridge initialization, ports, or processes.
    bridge = object.__new__(LeRobotBridge)
    bridge.config = config
    bridge.sessions_recent = lambda: [{"session_id": "custom-root", "workflow": "rollout", "status": "STOPPED"}]

    class Start:
        name = "manipulation_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            return AgentResult(True, "path binding only", bridge._omx_action_log_env_overrides("custom-root"))

    await Start().run(OrchestratorState(run_id="custom-run", experiment_id="fixture"),
                      SimpleNamespace(artifact_run_root=config.artifact_run_root))
    monkeypatch.setattr(main, "_lerobot_bridge", lambda: bridge)
    monkeypatch.setattr(main, "_registered_lerobot_bridge", lambda: bridge)
    selected = main._joint_telemetry_session_context()
    assert selected["log_path"].is_relative_to(config.artifact_run_root)
    assert selected["log_path"].parent.name == "custom-root"
    assert (selected["log_path"].parent / "session.json").is_file()
