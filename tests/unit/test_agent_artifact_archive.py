"""Loop/retry evidence survives mutable producers and application restarts."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.base_agent import AgentResult
from orchestrator.state import OrchestratorState
from utils.agent_artifact_archive import archive_agent_run, list_executions, current_execution


def state(loop=0):
    return OrchestratorState(run_id="run-archive", experiment_id="exp-1", loop_count=loop,
                             current_experiment_spec={"specimen_id": "same-specimen"})


class Producer:
    name = "analysis_agent"

    @archive_agent_run
    async def run(self, state, ctx):
        ctx.source.write_text(str(state.loop_count))
        return AgentResult(True, "done", {"metrics_path": str(ctx.source), "score": state.loop_count})


@pytest.mark.asyncio
async def test_two_loops_and_retry_preserve_bytes_and_reload(tmp_path):
    source = tmp_path / "artifacts" / "metrics.json"
    source.parent.mkdir()
    ctx = SimpleNamespace(artifact_run_root=tmp_path / "runs", source=source)
    agent = Producer()
    first = await agent.run(state(), ctx)
    second = await agent.run(state(1), ctx)
    retry = await agent.run(state(1), ctx)
    executions = list_executions(ctx.artifact_run_root / "run-archive")
    assert [(e["loop_index"], e["attempt_index"]) for e in executions] == [(0, 1), (1, 1), (1, 2)]
    assert len({e["execution_id"] for e in executions}) == 3
    for entry, value in zip(executions, ["0", "1", "1"]):
        assert entry["status"] == "completed"
        assert entry["specimen_id"] == "same-specimen"
        saved = next(a for a in entry["artifacts"] if a.get("source_path") == str(source))
        assert (ctx.artifact_run_root / "run-archive" / saved["path"]).read_text() == value
        assert saved["sha256"]
    assert first.data["score"] == 0 and second.data["score"] == retry.data["score"] == 1
    assert first.data["artifact_execution"]["loop_index"] == 0
    source.unlink()
    assert len(list_executions(ctx.artifact_run_root / "run-archive")) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_and_cancel_keep_partial_tool_result(tmp_path, cancel):
    from mcp_tools.tool_registry import ToolRegistry

    tools = ToolRegistry()
    source = tmp_path / "artifacts" / "partial.csv"
    source.parent.mkdir()
    source.write_text("displacement,load\n0,0\n")
    tools.register("fixture.export", lambda payload: {"csv_path": str(source)})

    class Failing:
        name = "equipment_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            tools.call("fixture.export", {"token": "do-not-save"})
            raise asyncio.CancelledError() if cancel else ValueError("fixture failure")

    ctx = SimpleNamespace(artifact_run_root=tmp_path / "runs")
    with pytest.raises(asyncio.CancelledError if cancel else ValueError):
        await Failing().run(state(), ctx)
    entry, = list_executions(ctx.artifact_run_root / "run-archive")
    assert entry["status"] == ("cancelled" if cancel else "failed")
    copied = next(a for a in entry["artifacts"] if a.get("source_path") == str(source))
    assert (ctx.artifact_run_root / "run-archive" / copied["path"]).read_text().startswith("displacement")
    events = (ctx.artifact_run_root / "run-archive" / entry["events_path"]).read_text()
    assert "fixture.export" in events and "do-not-save" not in events
    assert current_execution() is None


@pytest.mark.asyncio
async def test_nested_entry_does_not_double_archive_and_never_copies_external_secret(tmp_path):
    class Nested:
        name = "bo_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            return await self.run_with_settings(state, ctx, {})

        @archive_agent_run
        async def run_with_settings(self, state, ctx, settings):
            return AgentResult(False, "rejected", {"result_path": "/etc/passwd", "api_key": "secret"})

    await Nested().run(state(), SimpleNamespace(artifact_run_root=tmp_path / "runs"))
    entry, = list_executions(tmp_path / "runs" / "run-archive")
    assert entry["status"] == "failed"
    assert any(a.get("status") == "external" for a in entry["artifacts"])
    result = (tmp_path / "runs" / "run-archive" / entry["result_path"]).read_text()
    assert '"api_key": "[REDACTED]"' in result


@pytest.mark.asyncio
async def test_archive_io_failure_does_not_retry_or_change_agent_result(tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied")
    source = tmp_path / "metrics.json"
    current = state()
    result = await Producer().run(current, SimpleNamespace(artifact_run_root=blocked, source=source))
    assert result.success is True and result.data["score"] == 0
    assert current.run_metadata["artifact_archive_errors"]


@pytest.mark.asyncio
async def test_path_traversal_is_not_used_as_archive_target(tmp_path):
    current = state()
    current.run_id = "../escape"
    source = tmp_path / "metrics.json"
    await Producer().run(current, SimpleNamespace(artifact_run_root=tmp_path / "runs", source=source))
    assert not (tmp_path / "escape").exists()
    assert current.run_metadata["artifact_archive_errors"]


@pytest.mark.asyncio
async def test_real_orchestrator_entrypoint_preserves_each_loop(tmp_path):
    from agents.orchestrator_agent import OrchestratorAgent

    async def offline(*args, **kwargs):
        raise RuntimeError("No model service in this non-actuating test")

    ctx = SimpleNamespace(artifact_run_root=tmp_path / "runs", complete=offline)
    for loop in (0, 1):
        result = await OrchestratorAgent().run(state(loop), ctx)
        assert result.success
    entries = list_executions(tmp_path / "runs" / "run-archive")
    assert [e["agent"] for e in entries] == ["orchestrator_agent", "orchestrator_agent"]
    assert [e["loop_index"] for e in entries] == [0, 1]


@pytest.mark.asyncio
async def test_rollout_payload_uses_invocation_identity_not_only_run(tmp_path):
    from agents.manipulation_agent import ManipulationAgent

    class PayloadProducer:
        name = "manipulation_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            payload = ManipulationAgent()._lerobot_payload(state, "test", "lerobot_policy")
            return AgentResult(True, "payload only", payload)

    ctx = SimpleNamespace(artifact_run_root=tmp_path / "runs")
    outputs = [await PayloadProducer().run(state(loop), ctx) for loop in (0, 1, 1)]
    assert len({item.data["session_id"] for item in outputs}) == 3
    assert all(item.data["session_id"].startswith("rollout-run-archive-") for item in outputs)


@pytest.mark.asyncio
async def test_rollout_stream_stays_owned_after_agent_returns(tmp_path):
    from utils.rollout_artifact_stream import bind_rollout_log, resolve_rollout_log, update_rollout_artifact
    from tests.unit.test_lerobot_joint_telemetry import _action_event

    legacy = tmp_path / "runs" / "lerobot_action_logs" / "rollout-unique"

    class Start:
        name = "manipulation_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            path = bind_rollout_log(legacy)
            (path / "motor_events.jsonl").write_text(json.dumps(_action_event(1, 100)) + "\n")
            return AgentResult(True, "started", {"session_id": "rollout-unique"})

    await Start().run(state(), SimpleNamespace(artifact_run_root=tmp_path / "runs"))
    path = resolve_rollout_log(legacy)
    assert "loop-000001/manipulation_agent/attempt-000001/streams/rollout-unique" in str(path)
    with (path / "motor_events.jsonl").open("a") as handle:
        handle.write(json.dumps(_action_event(2, 100.1)) + "\n")
    update_rollout_artifact(path, {"session_id": "rollout-unique", "status": "STOPPED", "workflow": "rollout"})
    assert (path / "grasp_outcomes.json").is_file()
    assert json.loads((path / "session.json").read_text())["status"] == "STOPPED"
    entry, = list_executions(tmp_path / "runs" / "run-archive")
    assert entry["streams"][0]["session_id"] == "rollout-unique"
    assert len((path / "motor_events.jsonl").read_text().splitlines()) == 2


def test_rollout_location_marker_cannot_escape_run_root(tmp_path):
    from utils.rollout_artifact_stream import resolve_rollout_log
    legacy = tmp_path / "runs" / "lerobot_action_logs" / "session"
    legacy.mkdir(parents=True)
    (legacy / "artifact_location.json").write_text(json.dumps({"path": "../../private"}))
    assert resolve_rollout_log(legacy) == legacy


@pytest.mark.asyncio
async def test_runtime_postprocessing_and_events_remain_in_originating_loop(tmp_path):
    from agents.registry import AgentRegistry
    from logging_system.structured_logger import StructuredLogger
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Stage

    root = tmp_path / "runs"
    current = state()
    current.stage = Stage.ANALYSIS
    source = tmp_path / "artifacts" / "metrics.json"
    source.parent.mkdir()
    ctx = SimpleNamespace(artifact_run_root=root, source=source)
    result = await Producer().run(current, ctx)
    run_dir = root / current.run_id
    runtime = LangGraphRunLoop(state=current, agent_registry=AgentRegistry(),
        orchestrator_agent_name="orchestrator_agent", ctx=ctx,
        logger=StructuredLogger(run_dir / "structured.jsonl", run_dir / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml")
    artifacts = runtime._register_runtime_artifacts(Stage.ANALYSIS, "analysis_agent", result.data)
    assert artifacts and all("loop-000001/analysis_agent/attempt-000001/derived/" in a["path"] for a in artifacts)
    await runtime._emit(event_type="stage_transition", message="fixture", payload={"from_stage": "analysis", "to_stage": "bo"})
    event_file = run_dir / "runtime" / "loops" / "loop-000001" / "events.jsonl"
    assert '"event_type": "stage_transition"' in event_file.read_text()


@pytest.mark.asyncio
async def test_archive_target_symlink_cannot_write_outside_run_root(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "run-archive").symlink_to(outside, target_is_directory=True)
    current = state()
    await Producer().run(current, SimpleNamespace(artifact_run_root=root, source=tmp_path / "metrics.json"))
    assert list(outside.iterdir()) == []
    assert current.run_metadata["artifact_archive_errors"]


@pytest.mark.asyncio
async def test_large_evidence_is_copied_not_replaced_by_a_source_pointer(tmp_path):
    source = tmp_path / "artifacts" / "recording.rrd"
    source.parent.mkdir()
    with source.open("wb") as handle:
        handle.truncate(51 * 1024 * 1024)

    class Large:
        name = "vision_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            return AgentResult(True, "recorded", {"recording_path": str(source)})

    await Large().run(state(), SimpleNamespace(artifact_run_root=tmp_path / "runs"))
    entry, = list_executions(tmp_path / "runs" / "run-archive")
    artifact, = entry["artifacts"]
    assert artifact["status"] == "copied" and artifact["size_bytes"] == 51 * 1024 * 1024
    assert (tmp_path / "runs" / "run-archive" / artifact["path"]).stat().st_size == 51 * 1024 * 1024


@pytest.mark.asyncio
async def test_child_task_for_same_agent_is_a_distinct_invocation(tmp_path):
    class Concurrent:
        name = "bo_agent"

        @archive_agent_run
        async def run(self, state, ctx, child=False):
            if not child:
                await asyncio.create_task(self.run(state, ctx, child=True))
            return AgentResult(True, "done", {})

    await Concurrent().run(state(), SimpleNamespace(artifact_run_root=tmp_path / "runs"))
    assert len(list_executions(tmp_path / "runs" / "run-archive")) == 2


@pytest.mark.asyncio
async def test_failed_input_snapshot_is_not_reported_as_complete(tmp_path, monkeypatch):
    import utils.agent_artifact_archive as archive
    original = archive._json

    def fail_input(path, value):
        if path.name == "input.json":
            raise OSError("fixture disk failure")
        return original(path, value)

    monkeypatch.setattr(archive, "_json", fail_input)
    source = tmp_path / "artifacts" / "metrics.json"
    source.parent.mkdir()
    result = await Producer().run(state(), SimpleNamespace(artifact_run_root=tmp_path / "runs", source=source))
    assert result.success
    entry, = list_executions(tmp_path / "runs" / "run-archive")
    assert entry["archive_status"] == "incomplete"


@pytest.mark.asyncio
async def test_invalid_old_archive_error_metadata_never_blocks_agent(tmp_path):
    current = state()
    current.run_metadata["artifact_archive_errors"] = "old-format"
    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    result = await Producer().run(current, SimpleNamespace(artifact_run_root=blocked, source=tmp_path / "metrics.json"))
    assert result.success and result.data["score"] == 0
    assert isinstance(current.run_metadata["artifact_archive_errors"], list)


@pytest.mark.asyncio
async def test_guardian_tail_event_uses_loop_before_counter_increment(tmp_path):
    from utils.agent_artifact_archive import archive_runtime_stage, append_loop_event

    class Runtime:
        def __init__(self):
            self._state = state()

        @archive_runtime_stage
        async def step(self):
            self._state.loop_count += 1
            append_loop_event(tmp_path, self._state, {"event_type": "loop_reflection", "payload": {}})

    await Runtime().step()
    assert (tmp_path / "runtime/loops/loop-000001/events.jsonl").is_file()
    assert not (tmp_path / "runtime/loops/loop-000002/events.jsonl").exists()


@pytest.mark.asyncio
async def test_independent_bridge_root_uses_configured_archive_root(tmp_path):
    from utils.rollout_artifact_stream import bind_rollout_log, resolve_rollout_log
    legacy = tmp_path / "bridge-root" / "lerobot_action_logs" / "rollout-1"

    class Start:
        name = "manipulation_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            bound = bind_rollout_log(legacy)
            assert bound != legacy
            assert bound.is_relative_to(Path(ctx.artifact_run_root))
            assert resolve_rollout_log(legacy, run_root=ctx.artifact_run_root) == bound
            assert resolve_rollout_log(legacy, run_root=tmp_path / "untrusted") == legacy
            return AgentResult(True, "existing bridge path retained", {})

    await Start().run(state(), SimpleNamespace(artifact_run_root=tmp_path / "runs"))
    entry, = list_executions(tmp_path / "runs" / "run-archive")
    assert entry["archive_status"] == "recording"
    assert len(entry["streams"]) == 1


@pytest.mark.asyncio
async def test_cancelled_agent_keeps_late_worker_result(tmp_path):
    import threading
    from mcp_tools.tool_registry import ToolRegistry
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    source = tmp_path / "artifacts" / "late.csv"
    source.parent.mkdir()
    tools = ToolRegistry()

    def handler(payload):
        entered.set()
        assert release.wait(5)
        source.write_text("late device result")
        return {"csv_path": str(source)}

    tools.register("fixture.late", handler)

    def worker():
        try:
            return tools.call("fixture.late", {})
        finally:
            done.set()

    class Waiting:
        name = "equipment_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            await asyncio.to_thread(worker)
            return AgentResult(True, "done", {})

    root = tmp_path / "runs" / "run-archive"
    task = asyncio.create_task(Waiting().run(state(), SimpleNamespace(artifact_run_root=tmp_path / "runs")))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        before, = list_executions(root)
        assert before["status"] == "cancelled"
        assert before["archive_status"] == "recording"
    finally:
        release.set()
        assert await asyncio.to_thread(done.wait, 5)
    after, = list_executions(root)
    assert after["status"] == "cancelled"
    assert after["archive_status"] == "complete"
    copied = next(a for a in after["artifacts"] if a.get("source_path") == str(source))
    assert (root / copied["path"]).read_text() == "late device result"
    events = (root / after["events_path"]).read_text()
    assert events.index("agent_finished") < events.index("tool_result")


@pytest.mark.asyncio
async def test_failed_stream_locator_does_not_leave_recording_orphan(tmp_path, monkeypatch):
    import utils.rollout_artifact_stream as streams
    original = streams._json

    def fail_marker(path, value):
        if path.name == "artifact_location.json":
            raise OSError("fixture locator failure")
        return original(path, value)

    monkeypatch.setattr(streams, "_json", fail_marker)
    legacy = tmp_path / "runs" / "lerobot_action_logs" / "rollout-failed-marker"

    class Start:
        name = "manipulation_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            assert streams.bind_rollout_log(legacy) == legacy
            return AgentResult(True, "bridge can continue logging", {})

    result = await Start().run(state(), SimpleNamespace(artifact_run_root=tmp_path / "runs"))
    entry, = list_executions(tmp_path / "runs" / "run-archive")
    assert result.success
    assert entry["archive_status"] == "incomplete"
    assert entry["streams"][0]["status"] == "FAILED"
