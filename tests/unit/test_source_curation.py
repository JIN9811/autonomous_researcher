from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.source_curation import _publication_audit_event, curate_source
from backends.llm_lease import RECONCILIATION_PRIORITY
from knowledge.source_library import SourceLibrary
from knowledge import source_library as source_library_module


def _request(tool: str, **arguments: object) -> str:
    return json.dumps({"tool": tool, "arguments": arguments})


def _grounded_note(block_id: str, *, category: str = "qualified-guidance") -> dict:
    return {
        "title": "Qualified final condition",
        "body": (
            "The source reports a conflicting condition; it remains source-reported "
            "rather than independently verified."
        ),
        "category": category,
        "ontology_type": "KnowledgeClaim",
        "tags": ["quantity", "conflict"],
        "applicability": {"qualification": "source-specific"},
        "source_block_ids": [block_id],
    }


def _multipage_text_pdf(texts: list[str]) -> bytes:
    pages = list(range(3, 3 + len(texts)))
    font = 3 + len(texts)
    contents = list(range(font + 1, font + 1 + len(texts)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Kids [{' '.join(f'{page} 0 R' for page in pages)}] "
            f"/Count {len(texts)} >>"
        ).encode("ascii"),
    ]
    for content in contents:
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> "
                f"/Contents {content} 0 R >>"
            ).encode("ascii")
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for value in texts:
        stream = f"BT /F1 12 Tf 72 720 Td ({value}) Tj ET".encode("ascii")
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(data)


def _prepared(tmp_path: Path, *, long: bool = False) -> tuple[SourceLibrary, str, dict]:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    if long:
        paragraphs = [f"Section {index}: quantity {index}.5 mm; valid only under condition {index}." + " x" * 1100 for index in range(12)]
        text = "\n\n".join(paragraphs) + "\n\nFINAL-BLOCK conflicting condition retained"
    else:
        text = "Threshold: 17.5 MPa, but only when dry. A conflicting wet result is 11.0 MPa.\nEND"
    (inbox / "source.md").write_text(text, encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)
    library.scan()
    source_id = library.scan()["pending_ids"][0]
    return library, source_id, library.extract(source_id)


class FakeContext:
    active_backend = "fixture"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []

    async def complete(self, task_type: str, prompt: str, **kwargs: object) -> object:
        self.calls.append((task_type, prompt, dict(kwargs)))
        return SimpleNamespace(
            text=self.responses.pop(0),
            model="fixture-model",
            raw={"mock": True},
        )


@pytest.mark.asyncio
async def test_curation_inspects_every_page_searches_and_publishes_grounded_note(
    tmp_path: Path,
) -> None:
    library, source_id, extracted = _prepared(tmp_path, long=True)
    blocks = extracted["blocks"]

    class StagedContext:
        active_backend = "fixture"

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict]] = []
            self.searched = False
            self.sent_stage_object = False

        async def complete(self, task_type: str, prompt: str, **kwargs: object) -> object:
            self.calls.append((task_type, prompt, dict(kwargs)))
            payload = json.loads(prompt)
            mode = payload["mode"]
            if mode == "inspect":
                text = _request("inspect_source", offset=0, limit=16)
            elif mode == "page_curation":
                visible = next(
                    item["observation"]["blocks"]
                    for item in payload["observations"]
                    if item["tool"] == "inspect_source"
                )
                prior = payload.get("current_page_draft")
                prior_body = prior["body"] + " " if prior else ""
                facts = []
                if any("Section 0" in block["text"] for block in visible):
                    facts.append("Early source fact: Section 0 reports 0.5 mm.")
                if any("FINAL-BLOCK" in block["text"] for block in visible):
                    facts.append("Late source fact: FINAL-BLOCK conflicts with prior conditions.")
                body = (prior_body + " ".join(facts or ["Page evidence inspected."])).strip()
                new_ids = (
                    [block["block_id"] for block in visible]
                    if facts
                    else [visible[-1]["block_id"]]
                )
                note = {
                        **_grounded_note(visible[-1]["block_id"]),
                        "body": body,
                        "source_block_ids": new_ids,
                    }
                notes: object = [note]
                if not self.sent_stage_object:
                    self.sent_stage_object = True
                    notes = note
                text = _request("stage_notes", notes=notes)
            elif mode == "review" and not self.searched:
                self.searched = True
                text = _request(
                    "search_existing",
                    query="quantity conditions",
                    scope={},
                    top_k=3,
                )
            else:
                final_stage = payload["final_stage"]
                assert set(payload["tools"]["publish_knowledge"]) == {
                    "staged_note_ids"
                }
                assert library.search("")["hits"] == []
                assert list(
                    (tmp_path / "library").glob(
                        "sources/*/extractions/*/intermediate/**/*.json"
                    )
                )
                text = _request(
                    "publish_knowledge",
                    staged_note_ids=[final_stage["stage_id"]],
                )
            return SimpleNamespace(text=text, model="fixture-model", raw={"mock": True})

    ctx = StagedContext()

    result = await curate_source(library, source_id, ctx, timeout_s=30)

    assert result["ok"] is True and result["status"] == "ready"
    assert result["model"] == {
        "provider": "fixture",
        "model": "fixture-model",
        "mock": True,
        "real": False,
    }
    assert [item["tool"] for item in result["trace"]][-3:] == [
        "stage_notes",
        "search_existing",
        "publish_knowledge",
    ]
    inspected = [
        block["block_id"]
        for item in result["trace"]
        if item["tool"] == "inspect_source"
        for block in item["observation"]["blocks"]
    ]
    assert inspected == [block["block_id"] for block in blocks]
    assert all(
        len(item["observation"]["blocks"]) <= 2
        for item in result["trace"]
        if item["tool"] == "inspect_source"
    )
    assert max(len(call[1].encode("utf-8")) for call in ctx.calls) <= 12_000
    assert len(json.loads(ctx.calls[1][1])["observations"]) == 1
    hits = library.search("source fact")["hits"]
    assert len(hits) == 1 and hits[0]["source_id"] == source_id
    record = library.read(hits[0]["record_id"])["record"]
    assert "Early source fact" in record["body"]
    assert "Late source fact" in record["body"]
    assert blocks[0]["block_id"] in record["source_block_ids"]
    assert blocks[-1]["block_id"] in record["source_block_ids"]
    publication_dir = Path(result["publication"]["paths"][0]).parents[2]
    stored_trace = json.loads(
        (publication_dir / "trace.json").read_text(encoding="utf-8")
    )
    assert stored_trace[-1]["observation"] == {"status": "publication_requested"}
    stored_blocks = [
        block
        for event in stored_trace
        if event["tool"] == "inspect_source"
        for block in event["observation"]["blocks"]
    ]
    assert stored_blocks
    assert all(
        set(block) == {"block_id", "page", "text_sha256", "source_ref"}
        for block in stored_blocks
    )
    assert all(
        "source_block_ids" not in prompt["current_page_draft"]
        for _, raw, _ in ctx.calls
        if (prompt := json.loads(raw)).get("current_page_draft")
    )
    cumulative_prompts = [
        json.loads(raw)
        for _, raw, _ in ctx.calls
        if json.loads(raw).get("current_page_draft")
    ]
    assert cumulative_prompts
    cumulative_rules = " ".join(cumulative_prompts[0]["rules"])
    assert cumulative_prompts[0]["page_update_contract"]["operation"] == (
        "cumulative_revision"
    )
    assert "CUMULATIVE" in cumulative_rules
    assert "quantitative" in cumulative_rules
    assert "never replace" in cumulative_rules
    assert "roadmap" in cumulative_rules
    assert all(call[0] == "knowledge_query" for call in ctx.calls)
    assert all(call[2]["priority"] == RECONCILIATION_PRIORITY for call in ctx.calls)
    assert all(call[2]["lease_wait"] is True for call in ctx.calls)
    prompt = json.loads(ctx.calls[0][1])
    rules = " ".join(prompt["rules"])
    assert set(prompt["note_schema"]) == {
        "title",
        "body",
        "category",
        "ontology_type",
        "tags",
        "applicability",
        "source_block_ids",
    }
    assert "KnowledgeClaim" in prompt["ontology_types"]
    assert "^[a-z0-9][a-z0-9-]{0,79}$" in prompt["note_schema"]["category"]
    assert "material-properties" in prompt["note_schema"]["category"]
    assert "quantities" in rules
    assert "qualifications" in rules
    assert "conflicting" in rules
    assert "source-reported" in rules and "derived" in rules
    assert "exactly one note" in rules
    assert "literal backslash-n" in rules
    assert "17.5" not in ctx.calls[0][1]
    assert isinstance(
        json.loads(json.dumps(prompt["tools"]))["inspect_source"], dict
    )


@pytest.mark.asyncio
async def test_short_curation_corrects_object_to_one_element_notes_array(
    tmp_path: Path,
) -> None:
    library, source_id, extracted = _prepared(tmp_path)
    note = _grounded_note(extracted["blocks"][0]["block_id"])
    ctx = FakeContext(
        [
            _request("inspect_source", offset=0, limit=8),
            _request("publish_knowledge", notes=note),
            _request("publish_knowledge", notes=[note]),
        ]
    )

    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is True, result
    retry_prompt = json.loads(ctx.calls[2][1])
    assert set(retry_prompt["tools"]["publish_knowledge"]) == {"notes"}
    assert retry_prompt["observations"][-1]["observation"]["status"] == "validation_error"
    assert retry_prompt["observations"][0]["tool"] == "inspect_source"


@pytest.mark.asyncio
async def test_multipage_curation_merges_every_page_into_one_bounded_publication(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "paper.pdf").write_bytes(
        _multipage_text_pdf(
            [
                "PAGE-1 early modulus 17.5 MPa dry only " + "early evidence " * 20,
                *[
                    f"PAGE-{page} intermediate qualified fact " + "page evidence " * 20
                    for page in range(2, 20)
                ],
                "PAGE-20 late strength 21.0 MPa wet only " + "late evidence " * 20,
            ]
        )
    )
    library = SourceLibrary(tmp_path / "library", inbox)
    library.scan()
    source_id = library.scan()["pending_ids"][0]

    class MergeContext:
        active_backend = "fixture"

        def __init__(self) -> None:
            self.prompts: list[dict] = []
            self.page_attempts: dict[int, int] = {}
            self.sent_consolidation_object = False
            self.sent_extra_stage_id = False

        async def complete(self, task_type: str, prompt: str, **kwargs: object) -> object:
            payload = json.loads(prompt)
            self.prompts.append(payload)
            mode = payload["mode"]
            if mode == "inspect":
                request = _request("inspect_source", offset=0, limit=16)
            elif mode == "page_curation":
                block = next(
                    item["observation"]["blocks"][0]
                    for item in payload["observations"]
                    if item["tool"] == "inspect_source"
                )
                note = {
                        **_grounded_note(block["block_id"]),
                        "title": f"Page {payload['page_progress']['current']} finding",
                        "body": block["text"],
                        "source_block_ids": [block["block_id"]],
                    }
                notes: object = [note]
                page = payload["page_progress"]["current"]
                attempt = self.page_attempts.get(page, 0)
                self.page_attempts[page] = attempt + 1
                if attempt == 0:
                    notes = note
                elif attempt == 1:
                    notes = [{**note, "body": "oversized " * 300}]
                request = _request("stage_notes", notes=notes)
            elif mode == "consolidation":
                inputs = payload["consolidation_inputs"]
                expected_ids = [item["stage_id"] for item in inputs]
                assert payload["current_page_draft"] is None
                assert payload["recent_inspected_block_ids"] == []
                assert payload["final_stage"] is None
                assert not any(
                    item["tool"] == "inspect_source"
                    for item in payload["observations"]
                )
                assert payload["consolidation_input_stage_ids"] == expected_ids
                assert payload["tools"]["consolidate_notes"]["input_stage_ids"][
                    "exact_value"
                ] == expected_ids
                body = "\n\n".join(item["body"] for item in inputs)
                body_limit = int(payload["note_schema"]["body"].split("at most ")[1].split()[0])
                if len(body.encode("utf-8")) > body_limit:
                    body = body[:950] + "\n\n[intermediate summary]\n\n" + body[-950:]
                note = {
                    "title": "Consolidated paper findings",
                    "body": body,
                    "category": "paper-findings",
                    "ontology_type": "KnowledgeClaim",
                    "tags": ["paper", "grounded"],
                    "applicability": {"source": "paper"},
                }
                notes = [note]
                requested_ids = expected_ids
                if not self.sent_consolidation_object:
                    self.sent_consolidation_object = True
                    notes = note
                elif not self.sent_extra_stage_id:
                    self.sent_extra_stage_id = True
                    requested_ids = [*expected_ids, "stage-not-supplied"]
                request = _request(
                    "consolidate_notes",
                    input_stage_ids=requested_ids,
                    notes=notes,
                )
            else:
                assert set(payload["tools"]["publish_knowledge"]) == {
                    "staged_note_ids"
                }
                request = _request(
                    "publish_knowledge",
                    staged_note_ids=[payload["final_stage"]["stage_id"]],
                )
            return SimpleNamespace(text=request, model="fixture-model", raw={"mock": True})

    ctx = MergeContext()
    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is True, result
    inspected_pages = [
        block["page"]
        for item in result["trace"]
        if item["tool"] == "inspect_source"
        for block in item["observation"]["blocks"]
    ]
    assert inspected_pages == list(range(1, 21))
    assert all(len(prompt.get("consolidation_inputs", [])) <= 3 for prompt in ctx.prompts)
    consolidation_prompt = next(
        prompt for prompt in ctx.prompts if prompt["mode"] == "consolidation"
    )
    consolidation_rules = " ".join(consolidation_prompt["rules"])
    assert "EVERY consolidation input" in consolidation_rules
    assert "primary source" in consolidation_rules
    assert "quoted" in consolidation_rules
    assert "appendix" in consolidation_rules
    assert "not software dependencies" in consolidation_rules
    assert max(len(json.dumps(prompt).encode("utf-8")) for prompt in ctx.prompts) <= 12_000
    size_feedback = [
        item["observation"]
        for prompt in ctx.prompts
        for item in prompt["observations"]
        if item["observation"].get("actual_bytes")
    ]
    assert size_feedback
    assert all(item["actual_bytes"] > item["target_bytes"] == 2_000 for item in size_feedback)
    hits = library.search("modulus strength")["hits"]
    assert len(hits) == 1
    record = library.read(hits[0]["record_id"])["record"]
    assert 1_600 < len(record["body"]) < 6_000
    assert "17.5 MPa dry only" in record["body"]
    assert "21.0 MPa wet only" in record["body"]
    assert {citation["page"] for citation in record["citations"]} == set(range(1, 21))


@pytest.mark.asyncio
async def test_curation_retries_only_note_schema_error_then_publishes_once(
    tmp_path: Path,
) -> None:
    library, source_id, extracted = _prepared(tmp_path)
    block_id = extracted["blocks"][0]["block_id"]
    ctx = FakeContext(
        [
            _request("inspect_source", offset=0, limit=8),
            _request(
                "publish_knowledge",
                notes=[_grounded_note(block_id, category="material_properties")],
            ),
            _request(
                "publish_knowledge",
                notes=[_grounded_note(block_id, category="material-properties")],
            ),
        ]
    )

    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is True
    assert len(ctx.calls) == 3
    observations = json.loads(ctx.calls[2][1])["observations"]
    assert observations[0]["tool"] == "inspect_source"
    assert observations[0]["observation"]["blocks"][0]["block_id"] == block_id
    feedback = observations[-1]["observation"]
    assert feedback["status"] == "validation_error"
    assert "safe lowercase slug" in feedback["message"]
    assert len(list((tmp_path / "library").glob("sources/*/publications/*"))) == 1


@pytest.mark.asyncio
async def test_curation_does_not_retry_forged_block_id(tmp_path: Path) -> None:
    library, source_id, _ = _prepared(tmp_path)
    ctx = FakeContext(
        [
            _request("inspect_source", offset=0, limit=8),
            _request(
                "publish_knowledge",
                notes=[_grounded_note("block-forged")],
            ),
            _request("inspect_source", offset=0, limit=1),
        ]
    )

    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is False
    assert "uninspected" in result["message"]
    assert len(ctx.calls) == 2


@pytest.mark.asyncio
async def test_curation_does_not_retry_when_source_changes(tmp_path: Path) -> None:
    library, source_id, extracted = _prepared(tmp_path)
    block_id = extracted["blocks"][0]["block_id"]

    class ChangingContext(FakeContext):
        async def complete(self, task_type: str, prompt: str, **kwargs: object) -> object:
            if len(self.calls) == 1:
                (library.inbox / "source.md").write_text("changed", encoding="utf-8")
            return await super().complete(task_type, prompt, **kwargs)

    ctx = ChangingContext(
        [
            _request("inspect_source", offset=0, limit=8),
            _request("publish_knowledge", notes=[_grounded_note(block_id)]),
            _request("inspect_source", offset=0, limit=1),
        ]
    )

    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is False
    assert "changed" in result["message"]
    assert len(ctx.calls) == 2


@pytest.mark.asyncio
async def test_cancellation_waits_for_inflight_publication_and_keeps_ready_state(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "source.md").write_text("Threshold 17.5", encoding="utf-8")

    class BlockingLibrary(SourceLibrary):
        def __init__(self, root: Path, source_inbox: Path) -> None:
            super().__init__(root, source_inbox)
            self.publish_entered = threading.Event()
            self.publish_release = threading.Event()
            self.publish_calls = 0

        def publish(self, *args: object, **kwargs: object) -> dict:
            self.publish_calls += 1
            self.publish_entered.set()
            assert self.publish_release.wait(timeout=5)
            return super().publish(*args, **kwargs)

    library = BlockingLibrary(tmp_path / "library", inbox)
    library.scan()
    source_id = library.scan()["pending_ids"][0]
    extracted = library.extract(source_id)
    block_id = extracted["blocks"][0]["block_id"]
    ctx = FakeContext(
        [
            _request("inspect_source", offset=0, limit=8),
            _request("publish_knowledge", notes=[_grounded_note(block_id)]),
        ]
    )
    task = asyncio.create_task(curate_source(library, source_id, ctx, timeout_s=10))
    assert await asyncio.to_thread(library.publish_entered.wait, 2)

    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()
    library.publish_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert library.publish_calls == 1
    source = {item["source_id"]: item for item in library.status()["sources"]}[source_id]
    assert source["status"] == "ready"
    assert library.search("")["hits"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "publish_request",
    [
        _request("publish_knowledge", notes=[]),
        _request(
            "publish_knowledge",
            notes=[{
                "title": "bad block",
                "body": "unsupported",
                "category": "valid-category",
                "ontology_type": "KnowledgeClaim",
                "tags": [],
                "applicability": {},
                "source_block_ids": ["block-unknown"],
            }],
        ),
        _request(
            "publish_knowledge",
            notes=[{
                "title": "bad ontology",
                "body": "unsupported",
                "category": "valid-category",
                "ontology_type": "FabricatedClass",
                "tags": [],
                "applicability": {},
                "source_block_ids": [],
            }],
        ),
        _request(
            "publish_knowledge",
            notes=[{
                "title": "escape",
                "body": "unsupported",
                "category": "../../outside",
                "ontology_type": "KnowledgeClaim",
                "tags": [],
                "applicability": {},
                "source_block_ids": [],
            }],
        ),
    ],
)
async def test_curation_rejects_invalid_publication_without_partial_notes(
    tmp_path: Path, publish_request: str
) -> None:
    library, source_id, extracted = _prepared(tmp_path)
    ctx = FakeContext(
        [
            _request("inspect_source", offset=0, limit=8),
            publish_request,
        ]
    )

    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is False and result["status"] == "failed"
    assert library.search("")["hits"] == []
    assert list((tmp_path / "library").glob("sources/*/publications/*/notes/**/*.md")) == []
    assert extracted["blocks"]


@pytest.mark.asyncio
async def test_curation_cannot_publish_before_every_block_is_inspected(tmp_path: Path) -> None:
    library, source_id, extracted = _prepared(tmp_path, long=True)
    ctx = FakeContext(
        [
            _request("inspect_source", offset=0, limit=1),
            _request(
                "publish_knowledge",
                notes=[{
                    "title": "premature",
                    "body": "The unseen ending cannot be curated.",
                    "category": "review",
                    "ontology_type": "KnowledgeClaim",
                    "tags": [],
                    "applicability": {},
                    "source_block_ids": [extracted["blocks"][0]["block_id"]],
                }],
            ),
        ]
    )

    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert len(extracted["blocks"]) > 1
    assert result["ok"] is False
    assert "not available in page_curation mode" in result["message"]
    assert library.search("")["hits"] == []


@pytest.mark.asyncio
async def test_curation_readiness_guard_defers_without_calling_or_marking_failed(
    tmp_path: Path,
) -> None:
    library, source_id, _ = _prepared(tmp_path)

    class UnloadedContext:
        async def selected_model_loaded(self, task_type: str) -> bool:
            assert task_type == "knowledge_query"
            return False

        async def complete(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("unloaded model must not be called or started")

    result = await curate_source(library, source_id, UnloadedContext(), timeout_s=10)

    assert result == {
        "ok": False,
        "status": "deferred",
        "source_id": source_id,
        "error": "model_unavailable",
    }
    source = {item["source_id"]: item for item in library.status()["sources"]}[source_id]
    assert source["status"] == "extracted"


@pytest.mark.asyncio
async def test_curation_reports_missing_extraction_as_failed_result(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "bad.txt").write_bytes(b"\xff\xfe")
    library = SourceLibrary(tmp_path / "library", inbox)
    library.scan()
    source_id = library.scan()["pending_ids"][0]
    ctx = FakeContext([])

    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is False and result["status"] == "failed"
    assert result["error"] == "ValueError"
    assert ctx.calls == []


@pytest.mark.asyncio
async def test_curation_runs_extraction_for_newly_discovered_source(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "new.md").write_text("New threshold 17.5\nDISCOVERY-TAIL", encoding="utf-8")
    library = SourceLibrary(tmp_path / "library", inbox)
    library.scan()
    source_id = library.scan()["pending_ids"][0]

    class AdaptiveContext:
        active_backend = "fixture"

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, task_type: str, prompt: str, **kwargs: object) -> object:
            self.calls += 1
            if self.calls == 1:
                text = _request("inspect_source", offset=0, limit=8)
            else:
                seen = json.loads(prompt)["observations"][0]["observation"]["blocks"]
                text = _request(
                    "publish_knowledge",
                    notes=[{
                        "title": "New threshold",
                        "body": "The source reports 17.5 with its original qualification.",
                        "category": "new-evidence",
                        "ontology_type": "KnowledgeClaim",
                        "tags": ["threshold"],
                        "applicability": {},
                        "source_block_ids": [seen[0]["block_id"]],
                    }],
                )
            return SimpleNamespace(text=text, model="fixture-model", raw={"mock": True})

    ctx = AdaptiveContext()
    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is True and result["status"] == "ready"
    assert ctx.calls == 2
    assert library.search("17.5")["hits"]


@pytest.mark.asyncio
async def test_curation_rejects_uninspected_or_unknown_tool_requests(tmp_path: Path) -> None:
    library, source_id, _ = _prepared(tmp_path)
    ctx = FakeContext([_request("search_existing", query="x", scope={}, top_k=1)])

    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is False
    assert library.search("")["hits"] == []


@pytest.mark.asyncio
async def test_page_size_feedback_is_phase_specific_and_removes_nested_schema(
    tmp_path: Path,
) -> None:
    library, source_id, _ = _prepared(tmp_path, long=True)

    class CompactingContext:
        active_backend = "fixture"

        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.sent_oversized = False

        async def complete(self, task_type: str, prompt: str, **kwargs: object) -> object:
            payload = json.loads(prompt)
            self.calls.append(payload)
            if payload["mode"] == "inspect":
                text = _request("inspect_source", offset=0, limit=2)
            elif payload["mode"] == "page_curation":
                inspected = next(
                    item["observation"]["blocks"]
                    for item in payload["observations"]
                    if item["tool"] == "inspect_source"
                )
                inspection = next(
                    item["observation"]
                    for item in payload["observations"]
                    if item["tool"] == "inspect_source"
                )
                assert "note_schema" not in inspection
                assert "ontology_types" not in inspection
                assert "about 120 words maximum" in payload["note_schema"]["body"]
                assert "concise Markdown grounded in cited blocks" not in prompt
                body = "- Compact source-grounded page finding."
                if not self.sent_oversized:
                    self.sent_oversized = True
                    body = "verbose " * 300
                elif any(
                    item["observation"].get("status") == "validation_error"
                    for item in payload["observations"]
                ):
                    feedback = payload["observations"][-1]["observation"]
                    assert "REWRITE" in feedback["correction_instruction"]
                    assert "120 words" in feedback["correction_instruction"]
                    assert "category_requirement" not in feedback
                text = _request(
                    "stage_notes",
                    notes=[{
                        **_grounded_note(inspected[-1]["block_id"]),
                        "body": body,
                        "source_block_ids": [item["block_id"] for item in inspected],
                    }],
                )
            else:
                text = _request(
                    "publish_knowledge",
                    staged_note_ids=[payload["final_stage"]["stage_id"]],
                )
            return SimpleNamespace(text=text, model="fixture-model", raw={"mock": True})

    ctx = CompactingContext()
    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is True, result
    feedback_prompts = [
        payload
        for payload in ctx.calls
        if any(
            item["observation"].get("status") == "validation_error"
            for item in payload["observations"]
        )
    ]
    assert len(feedback_prompts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("separate_pages", [False, True])
async def test_two_block_partial_initial_inspection_stages_every_batch(
    tmp_path: Path,
    separate_pages: bool,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    if separate_pages:
        (inbox / "source.pdf").write_bytes(
            _multipage_text_pdf(["FIRST-PAGE evidence", "SECOND-PAGE evidence"])
        )
    else:
        (inbox / "source.md").write_text(
            "A" * 1_900 + "\n\n" + "B" * 1_900,
            encoding="utf-8",
        )
    library = SourceLibrary(tmp_path / "library", inbox)
    library.scan()
    source_id = library.scan()["pending_ids"][0]
    extracted = library.extract(source_id)
    assert len(extracted["blocks"]) == 2

    class PartialContext:
        active_backend = "fixture"

        def __init__(self) -> None:
            self.stage_calls = 0

        async def complete(self, task_type: str, prompt: str, **kwargs: object) -> object:
            payload = json.loads(prompt)
            if payload["mode"] == "inspect":
                request = _request("inspect_source", offset=0, limit=1)
            elif payload["mode"] == "page_curation":
                blocks = next(
                    item["observation"]["blocks"]
                    for item in payload["observations"]
                    if item["tool"] == "inspect_source"
                )
                self.stage_calls += 1
                request = _request(
                    "stage_notes",
                    notes=[{
                        **_grounded_note(blocks[0]["block_id"]),
                        "body": f"- Batch {self.stage_calls} evidence retained.",
                    }],
                )
            elif payload["mode"] == "consolidation":
                inputs = payload["consolidation_inputs"]
                request = _request(
                    "consolidate_notes",
                    input_stage_ids=[item["stage_id"] for item in inputs],
                    notes=[{
                        key: value
                        for key, value in _grounded_note("unused").items()
                        if key != "source_block_ids"
                    }],
                )
            else:
                assert set(payload["tools"]["publish_knowledge"]) == {
                    "staged_note_ids"
                }
                request = _request(
                    "publish_knowledge",
                    staged_note_ids=[payload["final_stage"]["stage_id"]],
                )
            return SimpleNamespace(text=request, model="fixture-model", raw={"mock": True})

    ctx = PartialContext()
    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is True, result
    assert ctx.stage_calls == 2
    record = library.read(result["publication"]["record_ids"][0])["record"]
    assert record["source_block_ids"] == [
        block["block_id"] for block in extracted["blocks"]
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_body", [None, 17])
async def test_page_note_body_type_error_receives_schema_feedback(
    tmp_path: Path,
    bad_body: object,
) -> None:
    library, source_id, _ = _prepared(tmp_path, long=True)

    class CorrectingContext:
        active_backend = "fixture"

        def __init__(self) -> None:
            self.sent_bad = False
            self.saw_feedback = False

        async def complete(self, task_type: str, prompt: str, **kwargs: object) -> object:
            payload = json.loads(prompt)
            if payload["mode"] == "inspect":
                request = _request("inspect_source", offset=0, limit=2)
            elif payload["mode"] == "page_curation":
                blocks = next(
                    item["observation"]["blocks"]
                    for item in payload["observations"]
                    if item["tool"] == "inspect_source"
                )
                note = _grounded_note(blocks[0]["block_id"])
                if not self.sent_bad:
                    self.sent_bad = True
                    note["body"] = bad_body
                if any(
                    item["observation"].get("status") == "validation_error"
                    for item in payload["observations"]
                ):
                    self.saw_feedback = True
                request = _request("stage_notes", notes=[note])
            else:
                request = _request(
                    "publish_knowledge",
                    staged_note_ids=[payload["final_stage"]["stage_id"]],
                )
            return SimpleNamespace(text=request, model="fixture-model", raw={"mock": True})

    ctx = CorrectingContext()
    result = await curate_source(library, source_id, ctx, timeout_s=10)

    assert result["ok"] is True, result
    assert ctx.saw_feedback is True


def test_audit_projection_has_deterministic_event_and_whole_trace_bounds() -> None:
    block_ids = [f"block-{index:064x}" for index in range(4_096)]
    event = {
        "tool": "stage_notes",
        "arguments": {
            "notes": [{
                "title": "T" * 300,
                "body": "evidence " * 10_000,
                "category": "source-findings",
                "ontology_type": "KnowledgeClaim",
                "tags": ["tag"] * 32,
                "applicability": {"conditions": ["condition " * 2_000]},
                "source_block_ids": block_ids,
            }],
        },
        "observation": {
            "ok": False,
            "status": "validation_error",
            "message": "invalid " * 2_000,
            "stage_id": "stage-" + "a" * 64,
        },
    }

    projected = _publication_audit_event(event)
    projected_bytes = len(
        json.dumps(
            projected,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    assert projected_bytes <= source_library_module.MAX_AUDIT_EVENT_BYTES
    assert projected["event_sha256"]
    assert projected["refs"]["block_ids"]["count"] == 4_096
    assert source_library_module.MAX_AUDIT_TRACE_EVENTS == 7 * 4_096 + 65
    assert source_library_module.MAX_AUDIT_TRACE_BYTES >= (
        source_library_module.MAX_AUDIT_TRACE_EVENTS
        * (source_library_module.MAX_AUDIT_EVENT_BYTES + 1)
        + 2
    )
    assert source_library_module._finite_json(
        [projected],
        "trace",
        source_library_module.MAX_AUDIT_TRACE_BYTES,
        maximum_depth=16,
    ) == [projected]
