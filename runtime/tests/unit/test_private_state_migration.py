"""Synthetic, offline copy rehearsals. Never open selected real stores."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest


STORES = ("run_root", "memory_root", "artifact_root", "output_root",
          "source_inbox_root", "user_file_root", "log_root")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/maintenance/migrate_private_state.py"


@pytest.fixture
def migration():
    # Keep collection/setup runnable before implementation; missing exported
    # functions fail at the actual call site in RED, not in fixture setup.
    if not SCRIPT.is_file():
        return SimpleNamespace()
    spec = importlib.util.spec_from_file_location("private_state_migration", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_copy_interfaces_exist(migration):
    for name in ("plan_copy", "copy_and_verify", "verify", "propose_bindings"):
        assert callable(getattr(migration, name, None)), f"missing migration interface: {name}"


def write(path, data=b"immutable synthetic record", mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return path


def tree(root):
    """Independent byte/mode observation, not the tool's snapshot implementation."""
    if not root.exists():
        return None
    return {p.relative_to(root).as_posix():
            (stat.S_IMODE(p.lstat().st_mode), p.read_bytes() if p.is_file() else None)
            for p in [root, *sorted(root.rglob("*"))]}


@pytest.fixture
def stores(tmp_path):
    source = {"schema": "atr.path_bindings.v1", "stores": {}}
    destination = {"schema": "atr.path_bindings.v1", "stores": {}}
    for name in STORES:
        old = tmp_path / "originals" / name
        old.mkdir(parents=True, mode=0o700)
        source["stores"][name] = str(old)
        destination["stores"][name] = str(tmp_path / "copies" / name)
    (tmp_path / "copies").mkdir(mode=0o700)
    write(Path(source["stores"]["run_root"]) / "run-1/cycle-1/result.json", b'{"cycle":1}')
    write(Path(source["stores"]["run_root"]) / "run-1/cycle-2/result.json", b'{"cycle":2}', 0o640)
    for name in STORES:
        for directory in Path(source["stores"][name]).rglob("*"):
            if directory.is_dir():
                directory.chmod(0o700)
    return source, destination


def test_plan_is_deterministic_read_only_and_retains_empty_stores(migration, stores, tmp_path):
    before = tree(tmp_path)
    plan = migration.plan_copy(*stores)
    assert plan == migration.plan_copy(*stores)
    assert plan["schema"] == "atr.private_state_migration.v1"
    assert plan["status"] == "planned"
    assert plan["activated"] is False
    assert plan["selected_bindings"] is None
    assert plan["compatibility_map"] is None
    assert {e["store"] for e in plan["entries"] if e["relative_path"] == "."} == set(STORES)
    assert tree(tmp_path) == before


@pytest.mark.parametrize("mutation", ["missing", "unknown", "relative", "duplicate", "overlap", "same", "cross"])
def test_rejects_ambiguous_or_incomplete_root_authority(migration, stores, mutation, tmp_path):
    source, destination = copy.deepcopy(stores)
    selected = destination["stores"]
    if mutation == "missing":
        selected.pop("log_root")
    elif mutation == "unknown":
        selected["repository_root"] = str(tmp_path)
    elif mutation == "relative":
        selected["log_root"] = "logs"
    elif mutation == "duplicate":
        selected["log_root"] = selected["memory_root"]
    elif mutation == "overlap":
        selected["log_root"] = selected["memory_root"] + "/nested"
    elif mutation == "same":
        selected["log_root"] = source["stores"]["log_root"]
    else:
        selected["log_root"] = source["stores"]["run_root"] + "/nested"
    before = tree(tmp_path)
    with pytest.raises(ValueError):
        migration.plan_copy(source, destination)
    assert tree(tmp_path) == before


def test_open_writer_rejection_precedes_any_destination_write(migration, stores, tmp_path):
    plan = migration.plan_copy(*stores)
    before = tree(tmp_path)
    with pytest.raises(ValueError, match="quiescent"):
        migration.copy_and_verify(plan, writers_quiescent=False)
    assert tree(tmp_path) == before


def test_copy_preserves_bytes_modes_and_never_activates(migration, stores, tmp_path, monkeypatch):
    monkeypatch.setenv("ATR_PATH_BINDINGS", "operator-existing-binding.json")
    source, destination = stores
    original = tree(tmp_path / "originals")
    result = migration.copy_and_verify(migration.plan_copy(*stores), writers_quiescent=True)
    assert result["status"] == "verified", result["errors"]
    assert result["activated"] is False
    assert result["writers_quiescent"] is True
    assert tree(tmp_path / "originals") == original
    for name in STORES:
        assert tree(Path(source["stores"][name])) == tree(Path(destination["stores"][name]))
    proposal = migration.propose_bindings(result)
    assert proposal["selected_bindings"] == destination
    assert proposal["activated"] is False
    assert proposal["ready_for_activation"] is False
    assert os.environ["ATR_PATH_BINDINGS"] == "operator-existing-binding.json"
    assert not (tmp_path / "operator-existing-binding.json").exists()


@pytest.mark.parametrize("kind", ["file", "populated", "identical"])
def test_populated_destinations_are_collisions_not_merge_authority(migration, stores, tmp_path, kind):
    destination = Path(stores[1]["stores"]["run_root"])
    if kind == "file":
        write(destination)
    else:
        write(destination / "run-1/cycle-1/result.json", b'{"cycle":1}' if kind == "identical" else b"newer")
    before = tree(tmp_path)
    plan = migration.plan_copy(*stores)
    assert plan["collisions"]
    result = migration.copy_and_verify(plan, writers_quiescent=True)
    assert result["status"] == "copy_incomplete"
    assert result["activated"] is False
    assert tree(tmp_path) == before


@pytest.mark.parametrize("kind", ["root", "ancestor", "nested_file", "nested_directory", "destination"])
def test_rejects_symlinks_even_when_the_target_is_inside_the_store(migration, stores, tmp_path, kind):
    source, destination = copy.deepcopy(stores)
    old = Path(source["stores"]["run_root"])
    if kind == "root":
        alias = tmp_path / "alias"
        alias.symlink_to(old, target_is_directory=True)
        source["stores"]["run_root"] = str(alias)
    elif kind == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path / "copies", target_is_directory=True)
        destination["stores"]["run_root"] = str(alias / "run_root")
    elif kind == "nested_file":
        (old / "alias.json").symlink_to(old / "run-1/cycle-1/result.json")
    elif kind == "nested_directory":
        (old / "alias").symlink_to(old / "run-1", target_is_directory=True)
    else:
        Path(destination["stores"]["run_root"]).symlink_to(old, target_is_directory=True)
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        migration.plan_copy(source, destination)


def test_rejects_special_files_without_opening_them(migration, stores):
    os.mkfifo(Path(stores[0]["stores"]["log_root"]) / "pipe")
    with pytest.raises(ValueError, match="[Ss]pecial"):
        migration.plan_copy(*stores)


@pytest.mark.parametrize("change", ["source_bytes", "destination_bytes", "file_mode", "directory_mode", "extra_file"])
def test_verify_rejects_post_copy_drift_without_repairing_records(migration, stores, tmp_path, change):
    result = migration.copy_and_verify(migration.plan_copy(*stores), writers_quiescent=True)
    source, destination = stores
    old = Path(source["stores"]["run_root"]) / "run-1/cycle-1/result.json"
    new = Path(destination["stores"]["run_root"]) / "run-1/cycle-1/result.json"
    if change == "source_bytes":
        old.write_bytes(b"new source record")
    elif change == "destination_bytes":
        new.write_bytes(b"new destination record")
    elif change == "file_mode":
        new.chmod(0o644)
    elif change == "directory_mode":
        new.parent.chmod(0o755)
    else:
        write(new.parent / "unexpected.json")
    before = tree(tmp_path)
    checked = migration.verify(result)
    assert checked["status"] == "copy_incomplete"
    assert checked["errors"]
    assert checked["selected_bindings"] is None
    assert checked["compatibility_map"] is None
    assert checked["activated"] is False
    with pytest.raises(ValueError):
        migration.propose_bindings(checked)
    assert tree(tmp_path) == before


@pytest.mark.parametrize("side", [0, 1])
def test_copy_rechecks_plan_before_creating_anything(migration, stores, tmp_path, side):
    plan = migration.plan_copy(*stores)
    root = Path(stores[side]["stores"]["log_root"])
    write(root / "new-record")
    before = tree(tmp_path)
    result = migration.copy_and_verify(plan, writers_quiescent=True)
    assert result["status"] == "copy_incomplete"
    assert result["errors"]
    assert result["activated"] is False
    assert tree(tmp_path) == before


@pytest.mark.parametrize("operation", ["read", "mkdir", "write", "fsync", "chmod", "publish"])
def test_permission_failures_keep_originals_and_disable_proposals(migration, stores, tmp_path, monkeypatch, operation):
    plan = migration.plan_copy(*stores)
    original = tree(tmp_path / "originals")

    def denied(*args, **kwargs):
        raise PermissionError("synthetic denied operation")

    target, attribute = {
        "read": (migration, "_read_file"),
        "mkdir": (migration.os, "mkdir"),
        "write": (migration.os, "write"),
        "fsync": (migration.os, "fsync"),
        "chmod": (migration.os, "fchmod"),
        "publish": (migration.os, "link"),
    }[operation]
    with monkeypatch.context() as patch:
        patch.setattr(target, attribute, denied)
        result = migration.copy_and_verify(plan, writers_quiescent=True)
    assert result["status"] == "copy_incomplete"
    assert result["errors"]
    assert result["activated"] is False
    assert result["selected_bindings"] is None
    assert tree(tmp_path / "originals") == original


def test_interruption_never_rolls_back_over_a_newer_destination(migration, stores, tmp_path, monkeypatch):
    plan = migration.plan_copy(*stores)
    original = tree(tmp_path / "originals")
    link = migration.os.link
    published = []

    def interrupt(source, destination, **kwargs):
        if published:
            published[0].write_bytes(b"newer writer record")
            raise OSError("synthetic copy interruption")
        link(source, destination, **kwargs)
        published.append(Path(stores[1]["stores"]["run_root"]) / "run-1/cycle-1/result.json")

    monkeypatch.setattr(migration.os, "link", interrupt)
    result = migration.copy_and_verify(plan, writers_quiescent=True)
    assert result["status"] == "copy_incomplete"
    assert result["activated"] is False
    assert result["rollback_conflicts"]
    assert published[0].read_bytes() == b"newer writer record"
    assert tree(tmp_path / "originals") == original


def test_manifest_cannot_redirect_copy_outside_its_explicit_roots(migration, stores, tmp_path):
    plan = migration.plan_copy(*stores)
    file = next(entry for entry in plan["entries"] if entry["kind"] == "file")
    file["destination"] = str(tmp_path / "outside-owned-stores")
    before = tree(tmp_path)
    with pytest.raises(ValueError):
        migration.copy_and_verify(plan, writers_quiescent=True)
    assert tree(tmp_path) == before


def test_all_cli_modes_are_inert_and_output_private_exclusive_manifests(migration, stores, tmp_path):
    source, destination = stores
    source_file = write(tmp_path / "source-bindings.json", json.dumps(source).encode())
    destination_file = write(tmp_path / "destination-bindings.json", json.dumps(destination).encode())
    plan_file = tmp_path / "plan.json"
    copied_file = tmp_path / "copied.json"
    verified_file = tmp_path / "verified.json"
    proposal_file = tmp_path / "proposal.json"
    commands = [
        ["plan", "--source-bindings", str(source_file), "--destination-bindings", str(destination_file), "--output", str(plan_file)],
        ["copy", "--manifest", str(plan_file), "--writers-quiescent", "--output", str(copied_file)],
        ["verify", "--manifest", str(copied_file), "--output", str(verified_file)],
        ["propose-bindings", "--manifest", str(verified_file), "--output", str(proposal_file)],
    ]
    for args, output in zip(commands, [plan_file, copied_file, verified_file, proposal_file]):
        run = subprocess.run([sys.executable, "-S", str(SCRIPT), *args], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        document = json.loads(output.read_text())
        assert document["activated"] is False
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
    before = proposal_file.read_bytes()
    retry = subprocess.run([sys.executable, "-S", str(SCRIPT), *commands[-1]], capture_output=True, text=True)
    assert retry.returncode != 0
    assert proposal_file.read_bytes() == before


REFERENCE_FIELDS = [
    ("atr.error_run_checkpoint.v1", "csv_path", "absolute"),
    ("atr.error_run_checkpoint.v1", "result_path", "absolute"),
    ("atr.error_run_checkpoint.v1", "planning.transcript_path", "absolute"),
    ("equipment_tail_recovery.v1", "source_path", "absolute"),
    ("equipment_tail_recovery.v1", "evidence_hashes.keys", "absolute"),
    ("atr.bo_budget_checkpoint.v1", "planning.transcript_path", "absolute"),
    ("atr.clearance_recovery.v1", "source_result", "absolute"),
    ("atr.clearance_recovery.v1", "record.evidence.raw_frame_path", "absolute"),
    ("atr.clearance_recovery.v1", "record.evidence.vision_decision.images[].path", "absolute"),
    ("atr.clearance_recovery.v1", "source_result_relative", "run-relative"),
    ("atr.clearance_recovery.v1", "bo_result_relative", "run-relative"),
]


def requests(source):
    root = Path(source["stores"]["run_root"])
    rows = []
    for schema, field, kind in REFERENCE_FIELDS:
        relative = "cycle-1/result.json"
        row = dict(schema=schema, field=field, run_id="run-1", reference_kind=kind,
                   source=str(root / "run-1" / relative) if kind == "absolute" else relative)
        if kind == "run-relative":
            row["source_base"] = str(root / "run-1")
        rows.append(row)
    return rows


def test_exact_typed_maps_are_emitted_only_for_verified_copies(migration, stores, tmp_path):
    from utils.persisted_references import resolve_persisted_reference
    plan = migration.plan_copy(*stores)
    plan["reference_requests"] = requests(stores[0])
    assert plan["compatibility_map"] is None
    original = tree(tmp_path / "originals")
    result = migration.copy_and_verify(plan, writers_quiescent=True)
    assert result["status"] == "verified", result["errors"]
    relocation = result["compatibility_map"]
    assert relocation["schema"] == "atr.persisted_reference_map.v1"
    assert len(relocation["entries"]) == 11
    new = Path(stores[1]["stores"]["run_root"])
    before = tree(tmp_path)
    for row in relocation["entries"]:
        assert set(row) == {"schema", "field", "run_id", "reference_kind", "source", "target"}
        assert row["target"] == str(new / "run-1/cycle-1/result.json")
        identity = {key: row[key] for key in ("schema", "field", "run_id", "reference_kind")}
        physical = resolve_persisted_reference(row["source"], **identity,
            allowed_roots=(new / "run-1",) if row["reference_kind"] == "run-relative" else (new,),
            relocation_map=relocation)
        assert physical.read_bytes() == b'{"cycle":1}'
    assert tree(tmp_path) == before
    assert tree(tmp_path / "originals") == original
    assert result["historical_coverage"] == "explicit-requests-only"
    assert result["resume_certified"] is False


@pytest.mark.parametrize("fault", ["unknown_key", "unsupported_field", "wrong_kind", "wrong_run", "outside", "noncanonical", "relative_base", "unverified_target", "duplicate"])
def test_map_requests_cannot_expand_copy_or_run_authority(migration, stores, tmp_path, fault):
    plan = migration.plan_copy(*stores)
    rows = requests(stores[0])
    if fault == "unknown_key":
        rows[0]["extra"] = "no"
    elif fault == "unsupported_field":
        rows[0]["field"] = "connection_memory_path"
    elif fault == "wrong_kind":
        rows[0]["reference_kind"] = "run-relative"
    elif fault == "wrong_run":
        rows[1]["run_id"] = "other-run"
    elif fault == "outside":
        rows[0]["source"] = str(tmp_path / "outside.csv")
    elif fault == "noncanonical":
        rows[0]["source"] += "/../result.json"
    elif fault == "relative_base":
        rows[-1]["source_base"] = stores[0]["stores"]["run_root"]
    elif fault == "unverified_target":
        rows[0]["target"] = str(tmp_path / "uncopied.csv")
    else:
        rows.append(dict(rows[0]))
    plan["reference_requests"] = rows
    before = tree(tmp_path)
    with pytest.raises(ValueError):
        migration.copy_and_verify(plan, writers_quiescent=True)
    assert tree(tmp_path) == before


def test_proposal_revalidates_bytes_and_does_not_trust_a_verified_status_string(migration, stores, tmp_path):
    result = migration.copy_and_verify(migration.plan_copy(*stores), writers_quiescent=True)
    result["compatibility_map"]["entries"].append({"schema": "fake", "target": "/elsewhere"})
    with pytest.raises(ValueError):
        migration.propose_bindings(result)
    forged = migration.plan_copy(*stores)
    forged["status"] = "verified"
    with pytest.raises(ValueError):
        migration.propose_bindings(forged)


def test_empty_requests_do_not_claim_historical_coverage(migration, stores):
    result = migration.copy_and_verify(migration.plan_copy(*stores), writers_quiescent=True)
    assert result["compatibility_map"] == {"schema": "atr.persisted_reference_map.v1", "entries": []}
    assert result["historical_coverage"] == "explicit-requests-only"
    assert result["resume_certified"] is False


def test_explicit_printer_and_registry_authorities_remain_unresolved(migration, stores, tmp_path):
    plan = migration.plan_copy(*stores)
    fields = {row["field"] for row in plan["selected_overrides"]}
    assert fields == {"devices.printer.connection_memory_path",
        "devices.printer.profiles.prusa_mk4s_lab_01.connection_memory_path"}
    for row in plan["selected_overrides"]:
        row["repository_root"] = str(tmp_path / "retained-repository")
    result = migration.copy_and_verify(plan, writers_quiescent=True)
    proposal = migration.propose_bindings(result)
    assert proposal["ready_for_activation"] is False
    assert proposal["activated"] is False
    assert len(proposal["unresolved_authorities"]) == 4
    overrides = proposal["selected_overrides"]
    assert overrides[0]["value"] == "memory/printer_fleet.json"
    assert overrides[1]["value"] == "memory/prusa_connection.json"
    assert all(row["decision"] is None for row in overrides)
    pdfs = proposal["phase_deferrals"]
    assert [(row["source"], row["frozen_destination"], row["size"]) for row in pdfs] == [
        ("docs/knowledge/manuals/sources/Indicator Manual.pdf", "system/knowledge/manuals/sources/Indicator Manual.pdf", 5895087),
        ("docs/knowledge/manuals/sources/Software Manual.pdf", "system/knowledge/manuals/sources/Software Manual.pdf", 4602565)]
    assert pdfs[0]["sha256"] == "2b4553da1de359681117c0a56be74d7f41db8324407f024979867bb38dd2ffaf"
    assert pdfs[1]["sha256"] == "d5389a0df3273d88f8f99b2449119baa93f2d194bc0f8ea8a97197b252390ad4"


def test_representative_multi_cycle_library_and_versions_are_byte_identical(migration, stores, tmp_path):
    source, destination = stores
    for name, relative, data in [
        ("artifact_root", "run-1/cycle-1/raw.bin", b"raw-1"),
        ("artifact_root", "run-1/cycle-2/raw.bin", b"raw-2"),
        ("output_root", "run-1/cycle-2/summary.csv", b"iteration,score\n2,1\n"),
        ("source_inbox_root", "manuals/synthetic.pdf", b"synthetic non-PDF fixture"),
        ("memory_root", "knowledge/source_library/catalog.json", b'{"schema":"source_library_catalog.v1","source_id":"source-kept"}'),
        ("memory_root", "knowledge/source_library/source-kept/manifest.json", b'{"extraction_hash":"kept"}'),
        ("memory_root", "knowledge/source_library/source-kept/pages/1.txt", b"manual page"),
        ("memory_root", "knowledge/manual_rag/index.json", b'{"path_id":"unchanged"}'),
        ("memory_root", "knowledge/graph_backend/knowledge_graph.json", b'{"nodes":[]}'),
        ("memory_root", "graph_versions/graph-1/v1.json", b'{"version":"graph-1-v1"}'),
        ("memory_root", "module_versions/module-1/v2.json", b'{"version":"module-1-v2"}'),
        ("user_file_root", "run-1/input.txt", b"input"),
        ("log_root", "run-1/cycles.jsonl", b'{"cycle":1}\n{"cycle":2}\n'),
    ]:
        write(Path(source["stores"][name]) / relative, data)
    originals = tree(tmp_path / "originals")
    result = migration.copy_and_verify(migration.plan_copy(*stores), writers_quiescent=True)
    assert result["status"] == "verified", result["errors"]
    assert tree(tmp_path / "originals") == originals
    for name in STORES:
        assert tree(Path(source["stores"][name])) == tree(Path(destination["stores"][name]))


def test_actual_error_checkpoint_reader_uses_verified_map_read_only(migration, stores, tmp_path):
    from app.run_recovery import read_checkpoint, save_checkpoint
    source, destination = stores
    old, new = Path(source["stores"]["run_root"]), Path(destination["stores"]["run_root"])
    csv = write(old / "compression.csv", b"time_s,force_N,displacement_mm\n0,0,0\n")
    result_path = old / "run-1/runtime/loops/loop-000001/equipment_agent/attempt-000001/result.json"
    write(result_path, json.dumps({"status": "failed", "data": {
        "equipment_workflow_execution_id": "equipment-" + "a" * 32,
        "equipment_handoff": {"failure_code": "EQUIPMENT_WORKFLOW_REVIEW_REQUIRED"},
        "raw_data_export": {"path": str(csv), "sha256": hashlib.sha256(csv.read_bytes()).hexdigest()}}}).encode())
    saved = save_checkpoint({"is_running": False, "state": {
        "run_id": "run-1", "experiment_id": "e", "stage": "error"}}, {}, old, "run-1")
    plan = migration.plan_copy(*stores)
    plan["reference_requests"] = [dict(schema="atr.error_run_checkpoint.v1", field=field,
        run_id="run-1", reference_kind="absolute", source=str(path))
        for field, path in [("csv_path", csv), ("result_path", result_path)]]
    verified = migration.copy_and_verify(plan, writers_quiescent=True)
    before = tree(tmp_path)
    assert read_checkpoint(new, "run-1", reference_roots=(new,), relocation_map=verified["compatibility_map"]) == saved
    assert tree(tmp_path) == before
    assert verified["resume_certified"] is False


def test_plan_cli_rejects_manifest_output_inside_selected_source(migration, stores, tmp_path, capsys):
    source = write(tmp_path / "source.json", json.dumps(stores[0]).encode())
    destination = write(tmp_path / "destination.json", json.dumps(stores[1]).encode())
    before = tree(tmp_path)
    code = migration.main(["plan", "--source-bindings", str(source), "--destination-bindings", str(destination),
        "--output", str(Path(stores[0]["stores"]["run_root"]) / "private-plan.json")])
    assert code == 1
    assert "outside copied stores" in capsys.readouterr().err
    assert tree(tmp_path) == before


def test_manifest_write_failure_preserves_sources_and_reports_failure(migration, stores, tmp_path, monkeypatch, capsys):
    plan = migration.plan_copy(*stores)
    path = write(tmp_path / "plan.json", json.dumps(plan).encode())
    original = tree(tmp_path / "originals")

    def denied(*args):
        raise PermissionError("synthetic manifest write denied")

    monkeypatch.setattr(migration, "_write_manifest", denied)
    assert migration.main(["copy", "--manifest", str(path), "--writers-quiescent",
                           "--output", str(tmp_path / "result.json")]) == 1
    assert "PermissionError" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()
    assert tree(tmp_path / "originals") == original


def test_interruption_after_mode_application_keeps_originals(migration, stores, tmp_path, monkeypatch):
    plan = migration.plan_copy(*stores)
    original = tree(tmp_path / "originals")
    chmod = migration.os.fchmod

    def interruption(descriptor, mode):
        chmod(descriptor, mode)
        raise OSError("synthetic interruption after mode application")

    monkeypatch.setattr(migration.os, "fchmod", interruption)
    result = migration.copy_and_verify(plan, writers_quiescent=True)
    assert result["status"] == "copy_incomplete"
    assert result["retained_paths"]
    assert result["selected_bindings"] is None
    assert not result["activated"]
    assert tree(tmp_path / "originals") == original


@pytest.mark.parametrize("fault", ["unknown_manifest_key", "omitted_override", "changed_deferral", "unknown_override_key"])
def test_tampered_accounting_fails_before_copy(migration, stores, tmp_path, fault):
    plan = migration.plan_copy(*stores)
    if fault == "unknown_manifest_key":
        plan["activate"] = True
    elif fault == "omitted_override":
        plan["selected_overrides"].pop()
    elif fault == "changed_deferral":
        plan["phase_deferrals"][0]["frozen_destination"] = "workspace/inbox/Indicator Manual.pdf"
    else:
        plan["selected_overrides"][0]["activate"] = True
    before = tree(tmp_path)
    with pytest.raises(ValueError):
        migration.copy_and_verify(plan, writers_quiescent=True)
    assert tree(tmp_path) == before


def test_deferred_pdf_identity_mismatch_is_not_certified(migration, stores, tmp_path):
    write(Path(stores[0]["stores"]["source_inbox_root"]) / "Indicator Manual.pdf", b"synthetic wrong identity")
    plan = migration.plan_copy(*stores)
    before = tree(tmp_path)
    with pytest.raises(ValueError, match="[Dd]eferred"):
        migration.copy_and_verify(plan, writers_quiescent=True)
    assert tree(tmp_path) == before


def test_actual_bound_profile_defaults_and_retained_external_authorities(migration, stores, tmp_path):
    from utils.runtime_paths import RuntimePaths
    from device_bridges.printer_fleet.bridge import PrinterProfile
    plan = migration.plan_copy(*stores)
    plan["selected_overrides"][0].update(repository_root=str(tmp_path / "repository"))
    external = str(tmp_path / "external" / "prusa-connection.json")
    plan["selected_overrides"][1].update(value=external, repository_root=str(tmp_path / "repository"))
    copied = migration.copy_and_verify(plan, writers_quiescent=True)
    proposal = migration.propose_bindings(copied)
    paths = RuntimePaths(repository_root=tmp_path / "repository", runtime_root=SCRIPT.parents[2],
        system_root=tmp_path / "system", workspace_root=tmp_path / "workspace",
        **{key: Path(value) for key, value in proposal["selected_bindings"]["stores"].items()})
    before = tree(tmp_path)
    omitted = PrinterProfile.from_dict("omitted", {}, repo_root=paths.repository_root, paths=paths)
    assert omitted.connection_memory_path == paths.memory_root / "bambu_connection.json"
    relative = PrinterProfile.from_dict("explicit", {"connection_memory_path": "memory/printer_fleet.json"},
        repo_root=paths.repository_root, paths=paths)
    assert relative.connection_memory_path == paths.repository_root / "memory/printer_fleet.json"
    absolute = PrinterProfile.from_dict("external", {"connection_memory_path": external},
        repo_root=paths.repository_root, paths=paths)
    assert absolute.connection_memory_path == Path(external)
    assert proposal["selected_overrides"][1]["value"] == external
    assert not proposal["ready_for_activation"] and not proposal["activated"]
    assert tree(tmp_path) == before


def test_native_source_library_identities_read_unchanged_after_copy(migration, stores, tmp_path):
    from knowledge.source_library import SourceLibrary
    old, new = stores
    runtime = SCRIPT.parents[2]
    inbox = Path(old["stores"]["source_inbox_root"])
    manual = write(inbox / "synthetic.md", b"# Manual\nSynthetic preserved evidence, 42 seconds.\n")
    library = SourceLibrary(Path(old["stores"]["memory_root"]) / "knowledge/source_library", inbox, runtime_root=runtime)
    library.scan()
    admitted = library.scan()
    source_id = "source-" + hashlib.sha256(manual.read_bytes()).hexdigest()
    assert admitted["pending_ids"] == [source_id]
    library.extract(source_id)
    expected = library.inspect(source_id)
    expected_status = library.status()
    verified = migration.copy_and_verify(migration.plan_copy(*stores), writers_quiescent=True)
    assert verified["status"] == "verified", verified["errors"]
    before = tree(tmp_path)
    copied = SourceLibrary(Path(new["stores"]["memory_root"]) / "knowledge/source_library",
        Path(new["stores"]["source_inbox_root"]), runtime_root=runtime)
    assert copied.status() == expected_status
    assert copied.inspect(source_id) == expected
    assert verified["compatibility_map"]["entries"] == []
    assert tree(tmp_path) == before


def test_equipment_bo_and_clearance_rehearsal_never_invokes_restore(migration, stores, tmp_path):
    from app.equipment_tail_recovery import read_request
    from utils.persisted_references import historical_reference
    old = Path(stores[0]["stores"]["run_root"])
    new = Path(stores[1]["stores"]["run_root"])
    transcript = write(old / "separate-session/live_planning_transcript.jsonl", b'{"role":"user","content":"kept"}\n')
    evidence = write(old / "run-1/recovery/equipment-record.json", b'{"run_id":"run-1","loop_id":0}')
    frame = write(old / "run-1/runtime/frame.bin", b"archived synthetic frame")
    other_frame = write(old / "run-1/runtime/frame-2.bin", b"archived second frame")
    evidence_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (evidence, frame)}
    request = dict(schema="equipment_tail_recovery.v1", run_id="run-1", requested_by="operator",
                   source_path=str(evidence), evidence_hashes=evidence_hashes)
    raw = json.dumps(request)
    write(old / "run-1/recovery/equipment_tail_request.json",
        json.dumps({"payload_json": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest()}).encode())
    bo_raw = json.dumps({"state": {"run_id": "run-1", "loop_count": 1},
        "planning": {"planning_session_id": "separate-session", "transcript_path": str(transcript)}})
    write(old / "run-1/recovery/bo_budget_checkpoint.json",
        json.dumps({"payload": bo_raw, "sha256": hashlib.sha256(bo_raw.encode()).hexdigest()}).encode())
    clearance = {"source_result": str(old / "run-1/cycle-1/result.json"),
        "source_result_relative": "cycle-1/result.json", "bo_result_relative": "cycle-2/result.json",
        "record": {"evidence": {"raw_frame_path": str(frame),
            "vision_decision": {"images": [{"path": str(frame)}, {"path": str(other_frame)}]}}}}
    write(old / "run-1/recovery/clearance.json", json.dumps(clearance).encode())
    plan = migration.plan_copy(*stores)
    rows = []

    def request_row(schema, field, value, kind="absolute"):
        row = dict(schema=schema, field=field, run_id="run-1", reference_kind=kind, source=value)
        if kind == "run-relative":
            row["source_base"] = str(old / "run-1")
        rows.append(row)

    request_row("equipment_tail_recovery.v1", "source_path", str(evidence))
    for path in evidence_hashes:
        request_row("equipment_tail_recovery.v1", "evidence_hashes.keys", path)
    request_row("atr.bo_budget_checkpoint.v1", "planning.transcript_path", str(transcript))
    request_row("atr.clearance_recovery.v1", "source_result", clearance["source_result"])
    request_row("atr.clearance_recovery.v1", "record.evidence.raw_frame_path", str(frame))
    for path in (frame, other_frame):
        request_row("atr.clearance_recovery.v1", "record.evidence.vision_decision.images[].path", str(path))
    for field in ("source_result_relative", "bo_result_relative"):
        request_row("atr.clearance_recovery.v1", field, clearance[field], "run-relative")
    plan["reference_requests"] = rows
    verified = migration.copy_and_verify(plan, writers_quiescent=True)
    assert verified["status"] == "verified", verified["errors"]
    before = tree(tmp_path)
    context = dict(reference_roots=(new,), relocation_map=verified["compatibility_map"])
    assert read_request(new, "run-1", **context) == request
    for row in rows:
        identity = {key: row[key] for key in ("schema", "field", "run_id", "reference_kind")}
        physical = historical_reference(row["source"], **identity, **context,
            **({"base": new / "run-1"} if row["reference_kind"] == "run-relative" else {}))
        original = Path(row["source_base"]) / row["source"] if row["reference_kind"] == "run-relative" else Path(row["source"])
        assert physical.read_bytes() == original.read_bytes()
    envelope = json.loads((new / "run-1/recovery/bo_budget_checkpoint.json").read_text())
    assert hashlib.sha256(envelope["payload"].encode()).hexdigest() == envelope["sha256"]
    assert tree(tmp_path) == before
    assert not verified["resume_certified"] and not verified["activated"]


def test_verify_cannot_promote_populated_dual_stores_even_with_identical_bytes(migration, stores, tmp_path):
    first = migration.copy_and_verify(migration.plan_copy(*stores), writers_quiescent=True)
    assert first["status"] == "verified"
    colliding = migration.plan_copy(*stores)
    rejected = migration.copy_and_verify(colliding, writers_quiescent=True)
    assert rejected["status"] == "copy_incomplete" and rejected["collisions"]
    before = tree(tmp_path)
    checked = migration.verify(rejected)
    assert checked["status"] == "copy_incomplete"
    assert checked["compatibility_map"] is None and checked["selected_bindings"] is None
    with pytest.raises(ValueError):
        migration.propose_bindings(checked)
    assert tree(tmp_path) == before


def test_keyboard_interrupt_returns_incomplete_without_source_or_destination_rollback(migration, stores, tmp_path, monkeypatch):
    plan = migration.plan_copy(*stores)
    original = tree(tmp_path / "originals")
    link, published = migration.os.link, []

    def interrupt(source, destination, **kwargs):
        if published:
            raise KeyboardInterrupt()
        link(source, destination, **kwargs)
        published.append(Path(stores[1]["stores"]["run_root"]) / "run-1/cycle-1/result.json")

    monkeypatch.setattr(migration.os, "link", interrupt)
    try:
        result = migration.copy_and_verify(plan, writers_quiescent=True)
    except KeyboardInterrupt:
        pytest.fail("Interrupted copy must return its incomplete non-activating receipt")
    assert result["status"] == "copy_incomplete"
    assert result["errors"] and not result["activated"]
    assert result["selected_bindings"] is None and result["compatibility_map"] is None
    assert published[0].read_bytes() == b'{"cycle":1}'
    assert tree(tmp_path / "originals") == original


def test_created_store_root_parents_are_synced_before_verified_manifest(migration, stores, tmp_path, monkeypatch):
    source, destination = stores
    parent_identities = set()
    for name in STORES:
        parent = tmp_path / ("destination-parent-" + name)
        parent.mkdir(mode=0o700)
        info = parent.stat()
        parent_identities.add((info.st_dev, info.st_ino))
        destination["stores"][name] = str(parent / "copied-store")
    receipts = tmp_path / "separate-private-manifests"
    receipts.mkdir(mode=0o700)
    plan = migration.plan_copy(source, destination)
    plan_file = write(receipts / "plan.json", json.dumps(plan).encode())
    original = tree(tmp_path / "originals")
    synced, fsync = [], migration.os.fsync

    def record_sync(descriptor):
        info = os.fstat(descriptor)
        fsync(descriptor)
        if stat.S_ISDIR(info.st_mode):
            synced.append((info.st_dev, info.st_ino))

    monkeypatch.setattr(migration.os, "fsync", record_sync)
    output = receipts / "copied.json"
    assert migration.main(["copy", "--manifest", str(plan_file), "--writers-quiescent",
                           "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["status"] == "verified" and result["activated"] is False
    assert parent_identities.issubset(set(synced))
    assert tree(tmp_path / "originals") == original


def test_root_parent_sync_failure_retains_created_root_and_blocks_verification(migration, stores, tmp_path, monkeypatch):
    plan = migration.plan_copy(*stores)
    original = tree(tmp_path / "originals")
    first_root = Path(stores[1]["stores"]["artifact_root"])
    info = first_root.parent.stat()
    parent_identity = (info.st_dev, info.st_ino)
    fsync = migration.os.fsync

    def fail_root_parent_sync(descriptor):
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) == parent_identity:
            raise OSError("synthetic root-parent fsync failure")
        fsync(descriptor)

    monkeypatch.setattr(migration.os, "fsync", fail_root_parent_sync)
    result = migration.copy_and_verify(plan, writers_quiescent=True)
    assert result["status"] == "copy_incomplete"
    assert result["activated"] is False
    assert result["compatibility_map"] is None and result["selected_bindings"] is None
    assert "synthetic root-parent fsync failure" in result["errors"]
    assert str(first_root) in result["retained_paths"]
    assert first_root.is_dir() and list(first_root.iterdir()) == []
    assert tree(tmp_path / "originals") == original
