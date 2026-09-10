from __future__ import annotations

import hashlib
import json
import multiprocessing
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Event

import pytest
import yaml

from knowledge.markdown_memory import MarkdownKnowledgeStore
from knowledge.ontology import OntologyRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _note(**overrides: object) -> dict[str, object]:
    note: dict[str, object] = {
        "run_id": "run-a",
        "cycle_id": "loop-000001",
        "agent_id": "equipment",
        "event_id": "event-a",
        "ontology_type": "Observation",
        "title": "Export completed",
        "body": "CSV export completed.",
        "source_refs": ["runs/run-a/result.json"],
        "evidence_kind": "observed",
        "fidelity": "virtual",
    }
    note.update(overrides)
    return note


@pytest.fixture
def ontology() -> OntologyRegistry:
    return OntologyRegistry.load_default(PROJECT_ROOT)


@pytest.fixture
def store(tmp_path: Path, ontology: OntologyRegistry) -> MarkdownKnowledgeStore:
    return MarkdownKnowledgeStore(tmp_path / "markdown", ontology)


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    _, raw, _ = text.split("---", 2)
    payload = yaml.safe_load(raw)
    assert isinstance(payload, dict)
    return payload


def _rewrite_record(path: Path, **changes: object) -> None:
    """Tamper with a real revision while recomputing the documented content hash."""
    text = path.read_text(encoding="utf-8")
    _, raw_header, raw_body = text.split("---", 2)
    frontmatter = yaml.safe_load(raw_header)
    assert isinstance(frontmatter, dict)
    frontmatter.update(changes)
    body = raw_body.strip("\n")
    content = {
        key: value
        for key, value in {**frontmatter, "body": body}.items()
        if key
        not in {"schema", "record_id", "revision", "content_hash", "ontology_version", "path"}
    }
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    frontmatter["content_hash"] = hashlib.sha256(encoded).hexdigest()
    header = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip()
    path.write_text(f"---\n{header}\n---\n\n{body}\n", encoding="utf-8")


def _write_retry_worker(root: str, note: dict[str, object], queue: object) -> None:
    ontology = OntologyRegistry.load_default(PROJECT_ROOT)
    receipt = MarkdownKnowledgeStore(Path(root), ontology).write_note(note)
    queue.put(receipt)


def test_roundtrip_writes_typed_frontmatter_and_default_metadata(
    store: MarkdownKnowledgeStore,
) -> None:
    receipt = store.write_note(_note(evidence_kind=None, fidelity=None))

    assert receipt == {
        "ok": True,
        "status": "created",
        "record_id": receipt["record_id"],
        "revision": 1,
        "path": receipt["path"],
    }
    path = Path(receipt["path"])
    assert path.is_file()
    assert path.resolve().is_relative_to(store.root)
    assert _frontmatter(path) == {
        "schema": "knowledge_markdown.v1",
        "record_id": receipt["record_id"],
        "revision": 1,
        "run_id": "run-a",
        "cycle_id": "loop-000001",
        "agent_id": "equipment",
        "event_id": "event-a",
        "ontology_type": "Observation",
        "title": "Export completed",
        "tags": [],
        "applicability": {},
        "source_refs": ["runs/run-a/result.json"],
        "evidence_kind": "derived",
        "fidelity": "unknown",
        "status": "valid",
        "content_hash": _frontmatter(path)["content_hash"],
        "ontology_version": "atr-core-1.0.0",
    }

    loaded = store.read_note(receipt["record_id"])
    assert loaded["ok"] is True
    assert loaded["status"] == "found"
    assert loaded["record"]["body"] == "CSV export completed."
    assert loaded["record"]["evidence_kind"] == "derived"
    assert loaded["record"]["fidelity"] == "unknown"


def test_retries_are_unchanged_and_changed_content_appends_revision(
    tmp_path: Path, ontology: OntologyRegistry
) -> None:
    root = tmp_path / "markdown"
    store = MarkdownKnowledgeStore(root, ontology)
    first = store.write_note(_note())
    first_bytes = Path(first["path"]).read_bytes()

    retry = store.write_note(_note())
    changed = store.write_note(_note(body="CSV export completed with a checksum."))

    assert retry == {**first, "status": "unchanged"}
    assert changed["record_id"] == first["record_id"]
    assert changed["revision"] == 2
    assert changed["status"] == "updated"
    assert Path(first["path"]).read_bytes() == first_bytes
    assert Path(changed["path"]).is_file()
    assert Path(changed["path"]) != Path(first["path"])

    rehydrated = MarkdownKnowledgeStore(root, ontology)
    record = rehydrated.read_note(first["record_id"])["record"]
    assert record["revision"] == 2
    assert record["body"] == "CSV export completed with a checksum."


def test_producer_cannot_create_or_rewrite_superseded_records(store):
    with pytest.raises(ValueError):
        store.write_note(_note(status="superseded"))
    original = store.write_note(_note())
    replacement = store.write_note(_note(event_id="replacement"))
    store.set_status(original["record_id"], "superseded", reason="Replacement verified",
                     superseded_by=replacement["record_id"])
    assert store.write_note(_note())["status"] == "unchanged"
    with pytest.raises(ValueError):
        store.write_note(_note(body="Changed source", applicability={"material": "changed"}))


def test_same_failure_in_different_cycles_has_independent_identity(
    store: MarkdownKnowledgeStore,
) -> None:
    first = store.write_note(
        _note(event_id="failed-export", ontology_type="Failure", title="Export failed")
    )
    second = store.write_note(
        _note(
            cycle_id="loop-000002",
            event_id="failed-export",
            ontology_type="Failure",
            title="Export failed",
        )
    )

    assert first["record_id"] != second["record_id"]
    assert store.status()["records"] == 2


def test_rejects_unknown_ontology_and_unbounded_or_unsafe_metadata(
    store: MarkdownKnowledgeStore,
) -> None:
    with pytest.raises(ValueError, match="ontology_type"):
        store.write_note(_note(ontology_type="ImaginaryThing"))
    with pytest.raises(ValueError, match="run_id"):
        store.write_note(_note(run_id="../outside"))
    with pytest.raises(ValueError, match="body"):
        store.write_note(_note(body="x" * 65_537))
    with pytest.raises(ValueError, match="source_refs"):
        store.write_note(_note(source_refs="runs/run-a/result.json"))
    with pytest.raises(ValueError, match="source_refs"):
        store.write_note(_note(source_refs=[]))


def test_lifecycle_status_is_append_only_and_controls_default_visibility(
    store: MarkdownKnowledgeStore,
) -> None:
    receipt = store.write_note(_note())
    replacement = store.write_note(_note(event_id="replacement", body="Reviewed replacement."))
    original_bytes = Path(receipt["path"]).read_bytes()

    update = store.set_status(receipt["record_id"], "needs_review", reason="conflicting run")

    assert update["ok"] is True
    assert update["status"] == "updated"
    assert update["record_status"] == "needs_review"
    assert update["revision"] == 2
    assert Path(receipt["path"]).read_bytes() == original_bytes
    assert all(hit["record_id"] != receipt["record_id"] for hit in store.search("export")["hits"])
    assert store.read_note(receipt["record_id"])["status"] == "not_found"
    visible = store.read_note(receipt["record_id"], scope={"status": "needs_review"})
    assert visible["record"]["lifecycle_reason"] == "conflicting run"

    superseded = store.set_status(
        receipt["record_id"],
        "superseded",
        reason="replacement reviewed",
        superseded_by=replacement["record_id"],
    )
    assert superseded["record_status"] == "superseded"
    assert superseded["revision"] == 3
    assert store.status()["status_counts"] == {"superseded": 1, "valid": 1}


def test_producer_retries_preserve_operator_lifecycle_status(
    store: MarkdownKnowledgeStore,
) -> None:
    receipt = store.write_note(_note())
    reviewed = store.set_status(receipt["record_id"], "needs_review", reason="operator review")

    identical_retry = store.write_note(_note())
    changed_retry = store.write_note(_note(body="CSV export completed with checksum evidence."))

    assert identical_retry["status"] == "unchanged"
    assert identical_retry["revision"] == reviewed["revision"] == 2
    assert changed_retry["status"] == "updated"
    assert changed_retry["revision"] == 3
    assert store.read_note(receipt["record_id"])["status"] == "not_found"
    current = store.read_note(receipt["record_id"], scope={"status": "needs_review"})["record"]
    assert current["body"] == "CSV export completed with checksum evidence."
    assert current["lifecycle_reason"] == "operator review"


def test_supersession_requires_a_current_compatible_target(store: MarkdownKnowledgeStore) -> None:
    source = store.write_note(_note(event_id="source", applicability={"material": "PLA"}))
    compatible = store.write_note(
        _note(event_id="compatible", body="replacement", applicability={"material": "PLA"})
    )
    other_type = store.write_note(
        _note(event_id="other-type", ontology_type="Failure", applicability={"material": "PLA"})
    )
    other_context = store.write_note(
        _note(event_id="other-context", body="PETG only", applicability={"material": "PETG"})
    )

    with pytest.raises(ValueError, match="itself"):
        store.set_status(
            source["record_id"],
            "superseded",
            reason="self target",
            superseded_by=source["record_id"],
        )
    with pytest.raises(ValueError, match="does not exist"):
        store.set_status(
            source["record_id"],
            "superseded",
            reason="missing target",
            superseded_by="km-00000000000000000000000000000000",
        )
    with pytest.raises(ValueError, match="ontology_type"):
        store.set_status(
            source["record_id"],
            "superseded",
            reason="wrong type",
            superseded_by=other_type["record_id"],
        )
    with pytest.raises(ValueError, match="applicability"):
        store.set_status(
            source["record_id"],
            "superseded",
            reason="wrong context",
            superseded_by=other_context["record_id"],
        )
    store.set_status(compatible["record_id"], "needs_review", reason="target disputed")
    with pytest.raises(ValueError, match="currently valid"):
        store.set_status(
            source["record_id"],
            "superseded",
            reason="stale target",
            superseded_by=compatible["record_id"],
        )

    assert store.read_note(source["record_id"])["record"]["status"] == "valid"
    assert store.read_note(other_context["record_id"])["record"]["status"] == "valid"


def test_scope_filters_are_exact_conjunctions_and_fail_closed(
    store: MarkdownKnowledgeStore,
) -> None:
    first = store.write_note(
        _note(tags=["csv", "export"], applicability={"material": "PLA", "device": "utm-1"})
    )
    store.write_note(
        _note(
            event_id="event-b",
            agent_id="analysis",
            title="Export analysis",
            tags=["csv"],
            applicability={"material": "PETG", "device": "utm-1"},
        )
    )

    scoped = store.search(
        "export",
        scope={
            "run_id": ["run-a", "run-b"],
            "agent_id": "equipment",
            "tags": ["csv", "export"],
            "applicability": {"material": "PLA", "device": "utm-1"},
        },
    )
    assert [hit["record_id"] for hit in scoped["hits"]] == [first["record_id"]]
    assert scoped["scope"]["status"] == "valid"
    assert store.search("export", scope={"run_id": []})["hits"] == []
    assert store.search("export", scope={"run_id": "RUN-A"})["hits"] == []
    with pytest.raises(ValueError, match="unknown scope"):
        store.search("export", scope={"project_id": "secret"})


def test_scoped_read_uses_the_same_filtering_rules_as_search(
    store: MarkdownKnowledgeStore,
) -> None:
    receipt = store.write_note(_note(tags=["export"], applicability={"material": "PLA"}))

    hidden = store.read_note(receipt["record_id"], scope={"cycle_id": "loop-999999"})
    visible = store.read_note(
        receipt["record_id"],
        scope={"cycle_id": "loop-000001", "tags": "export", "applicability": {"material": "PLA"}},
    )

    assert hidden == {"ok": False, "status": "not_found", "record_id": receipt["record_id"]}
    assert visible["ok"] is True
    with pytest.raises(ValueError, match="unknown scope"):
        store.read_note(receipt["record_id"], scope={"path": "../outside"})


def test_search_matches_english_and_korean_text(store: MarkdownKnowledgeStore) -> None:
    english = store.write_note(_note(event_id="english", title="CSV export complete"))
    korean = store.write_note(
        _note(event_id="korean", title="내보내기 완료", body="측정 결과를 안전하게 저장했습니다.")
    )

    assert store.search("EXPORT")["hits"][0]["record_id"] == english["record_id"]
    assert store.search("측정 결과")["hits"][0]["record_id"] == korean["record_id"]


def test_search_returns_bounded_excerpt_and_read_returns_full_body(
    store: MarkdownKnowledgeStore,
) -> None:
    body = "distinctive " + " ".join(["measurement"] * 100)
    receipt = store.write_note(_note(event_id="long-note", body=body))

    hit = store.search("distinctive")["hits"][0]

    assert "body" not in hit
    assert hit["excerpt"] == body[:500]
    assert len(hit["excerpt"]) == 500
    assert store.read_note(receipt["record_id"])["record"]["body"] == body


def test_existing_store_incrementally_observes_another_store_write(
    tmp_path: Path, ontology: OntologyRegistry
) -> None:
    root = tmp_path / "markdown"
    first = MarkdownKnowledgeStore(root, ontology)
    assert first.search("late arrival")["hits"] == []

    second = MarkdownKnowledgeStore(root, ontology)
    receipt = second.write_note(_note(event_id="late", title="Late arrival"))

    found = first.search("late arrival")
    assert found["hits"][0]["record_id"] == receipt["record_id"]
    assert found["index"]["parsed_files"] == 1
    assert first.search("late arrival")["index"]["parsed_files"] == 0


def test_shared_store_serializes_search_index_and_writer_cache_mutation(
    store: MarkdownKnowledgeStore,
) -> None:
    store.write_note(_note(event_id="first"))
    store.write_note(_note(event_id="second"))
    scoring_started = Event()
    release_scoring = Event()
    original_score = store._search_score

    def blocking_score(query: str, record: dict[str, object]) -> float:
        if not scoring_started.is_set():
            scoring_started.set()
            assert release_scoring.wait(timeout=2)
        return original_score(query, record)

    store._search_score = blocking_score  # type: ignore[method-assign]
    with ThreadPoolExecutor(max_workers=2) as executor:
        search = executor.submit(store.search, "export")
        assert scoring_started.wait(timeout=2)
        write = executor.submit(store.write_note, _note(event_id="third"))
        try:
            write.result(timeout=0.2)
        except TimeoutError:
            pass
        release_scoring.set()
        assert search.result(timeout=2)["ok"] is True
        assert write.result(timeout=2)["ok"] is True


def test_corrupt_newest_revision_quarantines_record_instead_of_rolling_back(
    store: MarkdownKnowledgeStore,
) -> None:
    receipt = store.write_note(_note())
    reviewed = store.set_status(receipt["record_id"], "needs_review", reason="operator review")
    Path(reviewed["path"]).write_text("---\ninvalid: [\n", encoding="utf-8")

    assert store.search("export")["hits"] == []
    assert store.search("export", scope={"status": "needs_review"})["hits"] == []
    assert store.read_note(receipt["record_id"], scope={"status": "valid"})["status"] == "not_found"
    index = store.status()["index"]
    assert index["quarantined_records"] == 1
    assert index["errors"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"title": "x" * 513}, "title"),
        ({"source_refs": []}, "source_refs"),
        ({"evidence_kind": "fact"}, "evidence_kind"),
        ({"run_id": "other-run"}, "record_id"),
    ],
)
def test_rehydration_revalidates_schema_even_with_recomputed_hash(
    tmp_path: Path,
    ontology: OntologyRegistry,
    changes: dict[str, object],
    message: str,
) -> None:
    root = tmp_path / "markdown"
    receipt = MarkdownKnowledgeStore(root, ontology).write_note(_note())
    _rewrite_record(Path(receipt["path"]), **changes)

    status = MarkdownKnowledgeStore(root, ontology).status()

    assert status["records"] == 0
    assert status["index"]["quarantined_records"] == 1
    assert message in status["index"]["errors"][0]


def test_rehydration_requires_exact_metadata_directory_hierarchy(
    tmp_path: Path, ontology: OntologyRegistry
) -> None:
    root = tmp_path / "markdown"
    receipt = MarkdownKnowledgeStore(root, ontology).write_note(_note())
    original = Path(receipt["path"])
    wrong = root / "records" / "run-b" / "loop-000001" / "equipment" / receipt["record_id"]
    wrong.mkdir(parents=True)
    moved = wrong / original.name
    original.rename(moved)

    status = MarkdownKnowledgeStore(root, ontology).status()

    assert status["records"] == 0
    assert status["index"]["quarantined_records"] == 1
    assert "directory" in status["index"]["errors"][0]


def test_cross_process_retries_create_one_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "markdown"
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    processes = [
        context.Process(target=_write_retry_worker, args=(str(root), _note(), queue))
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    receipts = [queue.get(timeout=2) for _ in processes]
    assert sorted(receipt["status"] for receipt in receipts) == [
        "created",
        "unchanged",
        "unchanged",
        "unchanged",
    ]
    revision_files = list(root.glob("**/revision-*.md"))
    assert len(revision_files) == 1


def test_cross_thread_retries_create_one_revision(
    tmp_path: Path, ontology: OntologyRegistry
) -> None:
    root = tmp_path / "markdown"

    def write() -> dict[str, object]:
        return MarkdownKnowledgeStore(root, ontology).write_note(_note())

    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = list(executor.map(lambda _: write(), range(8)))

    assert Counter(receipt["status"] for receipt in receipts) == {
        "created": 1,
        "unchanged": 7,
    }
    assert len(list(root.glob("**/revision-*.md"))) == 1


def test_record_ids_cannot_be_used_for_path_escape(
    store: MarkdownKnowledgeStore, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.md"

    with pytest.raises(ValueError, match="record_id"):
        store.read_note("../../outside.md", scope={})
    with pytest.raises(ValueError, match="record_id"):
        store.set_status("../../outside.md", "valid", reason="unsafe")

    assert not outside.exists()
