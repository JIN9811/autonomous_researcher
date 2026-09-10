"""Completed, failed and cancelled archives become evidence without replaying work."""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.base_agent import AgentResult
from orchestrator.state import Mode, OrchestratorState, Stage
from utils.agent_artifact_archive import archive_agent_run


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failed", "cancelled"])
async def test_terminal_agent_archive_creates_one_observed_note(tmp_path, outcome):
    state = OrchestratorState(run_id="intake-run", experiment_id="exp-a", mode=Mode.TEST, stage=Stage.EQUIPMENT)
    state.current_experiment_objective = {"objective_id": "objective-a", "objective_hash": "hash-a"}
    ctx = SimpleNamespace(artifact_run_root=str(tmp_path / "runs"))
    calls = []

    class Agent:
        name = "equipment_agent"

        @archive_agent_run
        async def run(self, state, ctx):
            calls.append(outcome)
            if outcome == "cancelled":
                raise asyncio.CancelledError()
            if outcome == "failed":
                raise RuntimeError("fixture failure")
            return AgentResult(success=True, summary="Export finished", data={"csv_valid": True})

    if outcome == "success":
        assert (await Agent().run(state, ctx)).success
    else:
        with pytest.raises(asyncio.CancelledError if outcome == "cancelled" else RuntimeError):
            await Agent().run(state, ctx)
    assert calls == [outcome]
    notes = list((tmp_path / "memory" / "knowledge" / "markdown").rglob("*.md"))
    assert len(notes) == 1, "Terminal archive did not produce a Markdown observation"
    text = notes[0].read_text()
    assert "evidence_kind: observed" in text
    expected_status = "completed" if outcome == "success" else outcome
    assert expected_status in text
    assert "operator" in text.lower() if outcome == "cancelled" else True
    manifest = next((tmp_path / "runs").rglob("manifest.json"))
    assert json.loads(manifest.read_text())["status"] == expected_status
    from knowledge.markdown_runtime import store_for
    found = store_for(project_root=tmp_path).search("", scope={"applicability": {
        "objective_id": "objective-a", "objective_hash": "hash-a"}})
    assert len(found["hits"]) == 1


def test_background_archive_reprocessing_is_idempotent_and_bounded(tmp_path):
    assert importlib.util.find_spec("knowledge.markdown_runtime") is not None
    from knowledge.markdown_runtime import ingest_archive_manifest, store_for
    manifest = tmp_path / "runs" / "run-a" / "runtime" / "loops" / "loop-000001" / "equipment" / "attempt-000001" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    (manifest.parent / "result.json").write_text(json.dumps({"status": "failed", "summary": "Export failed", "data": {"error_type": "ValueError"}}))
    manifest.write_text(json.dumps({"run_id": "run-a", "execution_id": "exec-1", "loop_number": 1,
        "agent": "equipment", "status": "failed", "result_path": "runtime/loops/loop-000001/equipment/attempt-000001/result.json"}))
    store = store_for(project_root=tmp_path)
    first = ingest_archive_manifest(tmp_path / "runs", manifest, store=store)
    second = ingest_archive_manifest(tmp_path / "runs", manifest, store=store)
    assert first["status"] == "created"
    assert second["status"] == "unchanged"
    with pytest.raises(ValueError):
        ingest_archive_manifest(tmp_path / "runs", tmp_path / "outside.json", store=store)


def test_applicability_merges_matching_objective_fields_and_rejects_conflicts():
    from knowledge.markdown_runtime import applicability_for
    state = OrchestratorState(run_id="run-a", experiment_id="a", mode=Mode.TEST, stage=Stage.KNOWLEDGE,
        current_experiment_objective={"objective_id": "A"},
        latest_analysis={"objective_evaluation": {"objective_id": "A", "objective_hash": "hash-a"}})
    assert applicability_for(state) == {"objective_id": "A", "objective_hash": "hash-a"}
    state.latest_analysis["objective_evaluation"]["objective_id"] = "B"
    with pytest.raises(ValueError, match="objective"):
        applicability_for(state)
