"""Historical references are lookup metadata, never rewritten evidence."""
import hashlib
import json
from pathlib import Path

import pytest


def mapping(old, new, *, field="csv_path", schema="atr.error_run_checkpoint.v1", run="run", kind="absolute"):
    return {"schema": "atr.persisted_reference_map.v1", "entries": [
        {"schema": schema, "field": field, "run_id": run, "reference_kind": kind,
         "source": str(old), "target": str(new)}]}


def resolve(value, roots, relocation_map, **kwargs):
    from utils.persisted_references import resolve_persisted_reference
    return resolve_persisted_reference(str(value), schema="atr.error_run_checkpoint.v1",
        field=kwargs.pop("field", "csv_path"), run_id=kwargs.pop("run_id", "run"),
        reference_kind=kwargs.pop("reference_kind", "absolute"),
        allowed_roots=roots, relocation_map=relocation_map, **kwargs)


def test_component_mapping_does_not_open_or_require_the_old_source(tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    (new / "compression.csv").write_bytes(b"original")
    old = tmp_path / "old"
    assert resolve(old / "compression.csv", (new,), mapping(old, new)).read_bytes() == b"original"
    assert not old.exists()


@pytest.mark.parametrize("fault", ["traversal", "prefix", "wrong_run", "ambiguous", "escape", "unknown_field", "wrong_kind", "malformed"])
def test_fail_closed_without_path_guessing(tmp_path, fault):
    old, new = tmp_path / "old", tmp_path / "new"
    refs = mapping(old, new)
    value, kwargs = old / "compression.csv", {}
    if fault == "traversal": value = str(old) + "/../old/compression.csv"
    if fault == "prefix": value = tmp_path / "old-neighbor/compression.csv"
    if fault == "wrong_run": kwargs["run_id"] = "other"
    if fault == "ambiguous": refs["entries"].append(dict(refs["entries"][0]))
    if fault == "escape": refs["entries"][0]["target"] = str(tmp_path / "outside")
    if fault == "unknown_field": kwargs["field"] = "model_path"
    if fault == "wrong_kind": kwargs["reference_kind"] = "run-relative"
    if fault == "malformed": refs["entries"][0]["source"] = "relative"
    with pytest.raises(ValueError): resolve(value, (new,), refs, **kwargs)


def test_symlink_target_cannot_escape_allowed_physical_root(tmp_path):
    new, outside = tmp_path / "new", tmp_path / "outside"
    new.mkdir(); outside.mkdir()
    (outside / "compression.csv").write_text("foreign")
    (new / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        resolve("/old/link/compression.csv", (new,), mapping("/old", new))


def test_identity_requires_explicit_root_and_keeps_unknown_fields_closed(tmp_path):
    assert resolve(tmp_path / "a.csv", (tmp_path,), {}) == tmp_path / "a.csv"
    with pytest.raises(ValueError): resolve(tmp_path / "a.csv", (), {})
    with pytest.raises(ValueError): resolve(tmp_path / "a.csv", (tmp_path,), {}, field="device_path")


def checkpoint(tmp_path, planning=None):
    from app.run_recovery import save_checkpoint
    old = tmp_path / "old"
    attempt = old / "run/runtime/loops/loop-000001/equipment_agent/attempt-000001"
    attempt.mkdir(parents=True)
    csv = old / "compression.csv"
    csv.write_bytes(b"time_s,force_N,displacement_mm\n0,0,0\n")
    (attempt / "result.json").write_text(json.dumps({"status": "failed", "data": {
        "equipment_workflow_execution_id": "equipment-" + "a" * 32,
        "equipment_handoff": {"failure_code": "EQUIPMENT_WORKFLOW_REVIEW_REQUIRED"},
        "raw_data_export": {"path": str(csv), "sha256": hashlib.sha256(csv.read_bytes()).hexdigest()}}}))
    saved = save_checkpoint({"is_running": False, "state": {"run_id": "run", "experiment_id": "e", "stage": "error"}},
        planning or {}, old, "run")
    original = (old / "run/recovery/checkpoint.json").read_bytes()
    new = tmp_path / "new"
    old.rename(new)
    refs = mapping(old, new)
    refs["entries"] += mapping(old, new, field="result_path")["entries"]
    return new, saved, original, refs


def test_moved_checkpoint_reads_evidence_without_rewriting_envelope(tmp_path):
    from app.run_recovery import read_checkpoint
    new, saved, original, refs = checkpoint(tmp_path)
    assert read_checkpoint(new, "run", reference_roots=(new,), relocation_map=refs) == saved
    assert (new / "run/recovery/checkpoint.json").read_bytes() == original


@pytest.mark.parametrize("fault", ["payload", "csv", "backup", "result", "run"])
def test_moved_checkpoint_rejects_changed_original_evidence(tmp_path, fault):
    from app.run_recovery import read_checkpoint
    new, saved, original, refs = checkpoint(tmp_path)
    envelope = new / "run/recovery/checkpoint.json"
    if fault in {"payload", "run"}:
        data = json.loads(original)
        if fault == "payload": data["payload_json"] += " "
        else:
            payload = json.loads(data["payload_json"]); payload["run_id"] = "foreign"
            data["payload_json"] = json.dumps(payload)
            data["sha256"] = hashlib.sha256(data["payload_json"].encode()).hexdigest()
        envelope.write_text(json.dumps(data))
    else:
        path = {"csv": new / "compression.csv", "backup": new / "run/recovery/compression.csv",
                "result": new / "run/runtime/loops/loop-000001/equipment_agent/attempt-000001/result.json"}[fault]
        path.write_text("altered")
    with pytest.raises(ValueError): read_checkpoint(new, "run", reference_roots=(new,), relocation_map=refs)


def test_checkpoint_verifies_envelope_before_mapping(tmp_path):
    from app.run_recovery import read_checkpoint
    new, _, original, _ = checkpoint(tmp_path)
    envelope = new / "run/recovery/checkpoint.json"
    data = json.loads(original); data["payload_json"] += "tampered"
    envelope.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="integrity mismatch"):
        read_checkpoint(new, "run", reference_roots=(new,), relocation_map={"schema": "invalid"})


@pytest.mark.parametrize("key", ["schema", "field", "reference_kind", "run_id"])
def test_malformed_mapping_discriminators_are_rejected(tmp_path, key):
    refs = mapping("/old", tmp_path)
    refs["entries"][0][key] = []
    with pytest.raises(ValueError): resolve("/old/a.csv", (tmp_path,), refs)


def test_checkpoint_mapping_cannot_substitute_another_run_result(tmp_path):
    from app.run_recovery import read_checkpoint
    new, _, _, refs = checkpoint(tmp_path)
    result = new / "run/runtime/loops/loop-000001/equipment_agent/attempt-000001/result.json"
    other = new / "other/runtime/loops/loop-000001/equipment_agent/attempt-000001/result.json"
    other.parent.mkdir(parents=True); other.write_bytes(result.read_bytes())
    refs["entries"][1]["source"] += "/run"
    refs["entries"][1]["target"] += "/other"
    with pytest.raises(ValueError): read_checkpoint(new, "run", reference_roots=(new,), relocation_map=refs)


def test_legacy_external_csv_identity_and_explicit_exact_file_authority(tmp_path):
    from app.run_recovery import read_checkpoint
    new, saved, _, _ = checkpoint(tmp_path)
    # Put original paths back: the unconfigured legacy contract is unchanged.
    old = tmp_path / "old"
    new.rename(old)
    assert read_checkpoint(old, "run") == saved
    with pytest.raises(ValueError): read_checkpoint(old, "run", reference_roots=(old / "run",))
    assert read_checkpoint(old, "run", reference_roots=(old / "run", old / "compression.csv")) == saved


def test_moved_equipment_request_keeps_path_keys_and_source_bytes(tmp_path):
    from app.equipment_tail_recovery import read_request, validate
    from tests.unit.test_equipment_tail_recovery import fixture
    from agents.equipment import workflow
    from unittest.mock import patch
    state, record = fixture()
    old = tmp_path / "old"
    directory = old / "run-1/recovery"
    directory.mkdir(parents=True)
    source = directory / "source.json"
    source.write_text(json.dumps(record))
    request = {"schema": "equipment_tail_recovery.v1", "run_id": "run-1", "requested_by": "operator",
        "source_path": str(source), "evidence_hashes": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()},
        "loop_id": 0, "description": {}, "experiment_spec": state.current_experiment_spec}
    raw = json.dumps(request)
    envelope = directory / "equipment_tail_request.json"
    envelope.write_text(json.dumps({"payload_json": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest()}))
    original = envelope.read_bytes()
    new = tmp_path / "new"; old.rename(new)
    refs = mapping(old, new, schema="equipment_tail_recovery.v1", field="evidence_hashes.keys", run="run-1")
    refs["entries"] += mapping(old, new, schema="equipment_tail_recovery.v1", field="source_path", run="run-1")["entries"]
    kwargs = {"reference_roots": (new,), "relocation_map": refs}
    assert read_request(new, "run-1", **kwargs) == request
    with patch.object(workflow, "_describe", return_value={}):
        assert validate(state, request, {}, **kwargs) == record
    assert (new / "run-1/recovery/equipment_tail_request.json").read_bytes() == original
    (new / "run-1/recovery/source.json").write_text("altered")
    with pytest.raises(ValueError, match="evidence changed"): read_request(new, "run-1", **kwargs)


def test_moved_bo_transcript_restores_separate_planning_session(tmp_path):
    from app.bo_budget_recovery import save
    from app.run_recovery import restore_checkpoint
    from tests.unit.test_bo_budget_recovery import state_fixture
    from orchestrator.state import OrchestratorState, Stage
    from types import SimpleNamespace
    old = tmp_path / "old"
    transcript = old / "conversation/live_planning_transcript.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"role":"user","content":"original"}\n')
    path = save({"state": state_fixture().model_dump(mode="json")},
        {"planning_session_id": "conversation", "transcript_path": str(transcript)}, old)
    original = path.read_bytes()
    new = tmp_path / "new"; old.rename(new)
    controller = SimpleNamespace(_state=OrchestratorState(run_id="startup", experiment_id="startup", stage=Stage.IDLE),
        _deps=SimpleNamespace(run_root=new, logging_config={}),
        snapshot=lambda: {"is_running": False}, _active_safety_sources=lambda: [])
    refs = mapping(old, new, schema="atr.bo_budget_checkpoint.v1", field="planning.transcript_path")
    result = restore_checkpoint(controller, "run", reference_roots=(new,), relocation_map=refs)
    assert result["status"] == "bo_resume_ready" and result["actuation_performed"] is False
    assert controller._planning_messages == [{"role": "user", "content": "original"}]
    assert controller._canonical_planning_transcript_path == new / "conversation/live_planning_transcript.jsonl"
    assert (new / "run/recovery/bo_budget_checkpoint.json").read_bytes() == original


def test_moved_error_checkpoint_restores_original_session_without_rewriting(tmp_path, monkeypatch):
    from app import run_recovery
    from orchestrator.state import OrchestratorState, Stage
    from types import SimpleNamespace
    old = tmp_path / "old"
    transcript = old / "original-conversation/live_planning_transcript.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"role":"operator","content":"kept"}\n')
    new, _, original, refs = checkpoint(tmp_path, {"planning_session_id": "original-session", "transcript_path": str(transcript)})
    refs["entries"] += mapping(old, new, field="planning.transcript_path")["entries"]
    controller = SimpleNamespace(_state=OrchestratorState(run_id="startup", experiment_id="startup", stage=Stage.IDLE),
        _deps=SimpleNamespace(run_root=new, logging_config={}),
        snapshot=lambda: {"is_running": False}, _active_safety_sources=lambda: [])
    # This test covers restore I/O, not downstream live Equipment scope checks.
    monkeypatch.setattr(run_recovery, "prepare_error_resume", lambda *args, **kwargs: "existing-execution")
    restored = run_recovery.restore_checkpoint(controller, "run", reference_roots=(new,), relocation_map=refs)
    assert restored["status"] == "restored_awaiting_resume" and not restored["actuation_performed"]
    assert controller._planning_session_id == "original-session"
    assert controller._planning_messages == [{"role": "operator", "content": "kept"}]
    assert (new / "run/recovery/checkpoint.json").read_bytes() == original


def test_bo_envelope_validation_precedes_bad_mapping_and_state_replacement(tmp_path):
    from app.bo_budget_recovery import save, restore
    from tests.unit.test_bo_budget_recovery import state_fixture
    from orchestrator.state import OrchestratorState, Stage
    from types import SimpleNamespace
    path = save({"state": state_fixture().model_dump(mode="json")}, {}, tmp_path)
    data = json.loads(path.read_text()); data["payload"] += "tampered"
    path.write_text(json.dumps(data))
    state = OrchestratorState(run_id="startup", experiment_id="startup", stage=Stage.IDLE)
    controller = SimpleNamespace(_state=state, _deps=SimpleNamespace(run_root=tmp_path),
        snapshot=lambda: {"is_running": False}, _active_safety_sources=lambda: [])
    with pytest.raises(ValueError, match="integrity mismatch"):
        restore(controller, "run", reference_roots=(tmp_path,), relocation_map={"schema": "invalid"})
    assert controller._state is state


def test_moved_clearance_frame_comparison_uses_physical_paths_not_stored_strings(tmp_path):
    from app.run_recovery import archived_clearance_capture
    from tests.unit.test_run_recovery_checkpoint import historical_fixture
    old = tmp_path / "old"; old.mkdir()
    state, source, raw, request = historical_fixture(old)
    original = source.read_bytes()
    new = tmp_path / "new"; old.rename(new)
    refs = {"schema": "atr.persisted_reference_map.v1", "entries": []}
    for field in ("source_result", "record.evidence.raw_frame_path", "record.evidence.vision_decision.images[].path"):
        refs["entries"] += mapping(old, new, schema="atr.clearance_recovery.v1", field=field, run="run-test")["entries"]
    capture = archived_clearance_capture(state, request, new / "review", reference_roots=(new,), relocation_map=refs)
    assert capture["historical_review"] and not capture["current_physical_clearance"]
    assert (new / source.relative_to(old)).read_bytes() == original
    assert state.run_metadata["clearance_review_recovery"]["source_result"] == str(source)


def test_run_relative_reference_has_its_own_base(tmp_path):
    from utils.persisted_references import resolve_persisted_reference
    kwargs = dict(schema="atr.clearance_recovery.v1", field="source_result_relative", run_id="run",
        reference_kind="run-relative", allowed_roots=(tmp_path / "run",), relocation_map={})
    assert resolve_persisted_reference("runtime/result.json", **kwargs) == tmp_path / "run/runtime/result.json"
    for invalid in ("../other/result.json", "/runtime/result.json"):
        with pytest.raises(ValueError): resolve_persisted_reference(invalid, **kwargs)
    kwargs["allowed_roots"] = (tmp_path / "run", tmp_path / "other")
    with pytest.raises(ValueError): resolve_persisted_reference("runtime/result.json", **kwargs)


def test_relative_reader_base_cannot_widen_explicit_authority(tmp_path):
    from utils.persisted_references import historical_reference
    with pytest.raises(ValueError):
        historical_reference("runtime/result.json", schema="atr.clearance_recovery.v1",
            field="source_result_relative", run_id="run", reference_kind="run-relative",
            reference_roots=(tmp_path / "other",), base=tmp_path / "run", relocation_map={})


@pytest.mark.parametrize("malformed", [[], "", False, 0])
def test_reader_does_not_treat_falsey_malformed_maps_as_identity(tmp_path, malformed):
    from app.run_recovery import read_checkpoint
    new, _, _, _ = checkpoint(tmp_path)
    old = tmp_path / "old"; new.rename(old)
    with pytest.raises(ValueError):
        read_checkpoint(old, "run", reference_roots=(old,), relocation_map=malformed)


@pytest.mark.parametrize("kind", ["source-inbox-relative", "extraction-relative"])
def test_source_library_kinds_do_not_become_run_reference_authority(tmp_path, kind):
    with pytest.raises(ValueError): resolve("item.txt", (tmp_path,), {}, reference_kind=kind)


def test_archive_alias_uses_only_existing_copy_and_never_original_source(tmp_path):
    from utils.run_review_artifacts import artifact_alias_path
    run = tmp_path / "run"
    directory = run / "runtime/loops/loop-000001/vision_agent/attempt-000001"
    (directory / "files").mkdir(parents=True)
    (run / "review").mkdir()
    (run / "review/index.json").write_text('{"run_id":"run","points":[]}')
    copy = directory / "files/frame.png"; copy.write_bytes(b"archived")
    original = tmp_path / "source.png"; original.write_bytes(b"current wrong frame")
    manifest = {"schema": "atr.agent_artifact_execution.v1", "run_id": "run", "agent": "vision_agent",
        "manifest_path": str((directory / "manifest.json").relative_to(run)), "loop_index": 0,
        "archive_status": "complete", "artifacts": [{"status": "copied", "source_path": str(original),
        "path": str(copy.relative_to(run)), "sha256": hashlib.sha256(copy.read_bytes()).hexdigest()}]}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert artifact_alias_path(tmp_path, "run", str(original)).read_bytes() == b"archived"
    copy.unlink()
    with pytest.raises(ValueError): artifact_alias_path(tmp_path, "run", str(original))
    assert original.read_bytes() == b"current wrong frame"


@pytest.mark.asyncio
async def test_archive_capture_explicit_roots_do_not_infer_adjacent_stores(tmp_path):
    from utils.agent_artifact_archive import AgentArtifactExecution
    from tests.unit.test_agent_artifact_archive import state
    root = tmp_path / "isolated-runs"
    approved = tmp_path / "approved"; approved.mkdir()
    image = approved / "frame.png"; image.write_bytes(b"image")
    neighbor = tmp_path / "artifacts"; neighbor.mkdir()
    secret = neighbor / "secret.png"; secret.write_bytes(b"secret")
    execution = AgentArtifactExecution(root, state(), "vision_agent", reference_roots=(approved,))
    execution.capture({"frame": str(image), "other": str(secret)})
    copied = [item for item in execution.manifest["artifacts"] if item["status"] == "copied"]
    assert len(copied) == 1 and copied[0]["source_path"] == str(image)
    assert (execution.run_dir / copied[0]["path"]).read_bytes() == b"image"


def test_recorder_uses_explicit_relative_image_base(tmp_path):
    from utils.run_review import RunReviewRecorder
    from tests.unit.test_run_review import event
    root = tmp_path / "private/runs"
    run = root / "new-run"; run.mkdir(parents=True)
    (run / "frame.png").write_bytes(b"correct image")
    recorder = RunReviewRecorder(root, "excluded", image_base=root)
    recorder.record(event(payload={"frame_path": "new-run/frame.png"}))
    point = json.loads((run / "review/000001.json").read_text())
    image = point["cards"]["vision"]["images"][0]
    assert (run / "review/assets" / image["name"]).read_bytes() == b"correct image"


def test_preservation_explicit_project_and_knowledge_roots(tmp_path):
    from tests.unit.test_artifact_preservation import execution
    from utils.artifact_preservation import preserve_execution
    from dataclasses import replace
    from utils.runtime_paths import current_paths
    project = tmp_path / "project"; project.mkdir()
    run, directory, _ = execution(tmp_path, "knowledge", {"note_path": "notes/revision-1.md"})
    notes = project / "notes"; notes.mkdir()
    note = notes / "revision-1.md"; note.write_bytes(b"immutable note")
    # Use the configured memory store; do not infer it from the run root parent.
    memory = tmp_path / "memory-store"
    source = memory / "knowledge/markdown/records/run-evidence/revision-1.md"
    source.parent.mkdir(parents=True); source.write_bytes(b"immutable note")
    (directory / "result.json").write_text(json.dumps({"data": {"note_path": str(source)}}))
    paths = replace(current_paths(), repository_root=project, memory_root=memory)
    receipt = preserve_execution(run, directory / "manifest.json", paths=paths)
    assert len(receipt["generated"]) == 1
    assert (run / receipt["generated"][0]["path"]).read_bytes() == b"immutable note"


@pytest.mark.asyncio
async def test_application_archive_composition_uses_configured_paths(tmp_path):
    """Execute the three production wiring sites without importing app.main.

    The real constructors and router run; unrelated main-module startup and
    device services are not part of this isolated composition test.
    """
    import ast
    from dataclasses import replace
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fastapi.templating import Jinja2Templates
    from app.run_review_routes import review_router
    from utils.run_review import RunReviewRecorder
    from utils import run_review, agent_artifact_archive
    from utils.runtime_paths import current_paths
    paths = replace(current_paths(), repository_root=tmp_path / "project",
        runtime_root=tmp_path / "runtime", memory_root=tmp_path / "memory", run_root=tmp_path / "runs")
    frontend = paths.runtime_root / "agents/vision/frontend/live_report.js"
    frontend.parent.mkdir(parents=True)
    frontend.write_text("global.AX4LABRelocatedVisionUI = {};")
    source = Path(__file__).resolve().parents[2] / "app/main.py"
    selected = []
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name in {"start_artifact_preservation", "start_read_only_run_review"}:
            node.decorator_list = []
            selected.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "review_router"
                   for child in ast.walk(node)):
                selected.append(node)
    app = FastAPI()
    ns = dict(app=app, RUNTIME_PATHS=paths, review_router=review_router, RunReviewRecorder=RunReviewRecorder,
        templates=Jinja2Templates(directory="web/templates"),
        controller=SimpleNamespace(_deps=SimpleNamespace(run_root=paths.run_root), _state=SimpleNamespace(run_id="excluded")))
    prior_capture, prior_preservation = run_review.capture_sink, agent_artifact_archive._PRESERVATION_SINK
    try:
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), ns)
        await ns["start_artifact_preservation"]()
        await ns["start_read_only_run_review"]()
        assert ns["_RUN_REVIEW_RECORDER"].image_base == paths.repository_root
        assert ns["_ARTIFACT_PRESERVATION_SERVICE"].paths == paths
        with TestClient(app) as client:
            vision = next(item for item in client.get("/api/review/layout").json()["agents"] if item["id"] == "vision")
        assert vision["implementation"]["frontend"]["namespace"] == "AX4LABRelocatedVisionUI"
    finally:
        if ns.get("_RUN_REVIEW_RECORDER"):
            ns["_RUN_REVIEW_RECORDER"].stop()
            ns["_RUN_REVIEW_RECORDER"].thread.join(timeout=2)
        if ns.get("_ARTIFACT_PRESERVATION_SERVICE"):
            ns["_ARTIFACT_PRESERVATION_SERVICE"].close()
        run_review.capture_sink = prior_capture
        agent_artifact_archive.set_preservation_sink(prior_preservation)
