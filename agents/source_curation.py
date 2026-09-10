"""Bounded model tool loop for source-preserving knowledge curation."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
from typing import Any

from backends.llm_lease import RECONCILIATION_PRIORITY
from knowledge.source_library import MAX_AUDIT_EVENT_BYTES, PublicationValidationError


_MAX_INSPECT_BLOCKS = 2
_MAX_MERGE_INPUTS = 3
_MAX_PAGE_BODY_BYTES = 2_000
_MAX_INTERMEDIATE_BODY_BYTES = 2_000
_MAX_FINAL_BODY_BYTES = 6_000
_MAX_PROMPT_BYTES = 12_000
_MAX_VALIDATION_RETRIES = 2
_NOTE_EXAMPLE = {
    "title": "Source-grounded finding",
    "body": "## Finding\n\nSummarize a source statement with its reported units and qualifications.",
    "category": "source-findings",
    "ontology_type": "KnowledgeClaim",
    "tags": ["source-topic"],
    "applicability": {"condition": "source-stated"},
    "source_block_ids": ["block-<inspected-id>"],
}
_TOOLS = {
    "inspect_source": {
        "offset": "non-negative integer",
        "limit": f"integer 1..{_MAX_INSPECT_BLOCKS}",
    },
    "search_existing": {
        "query": "string",
        "scope": "optional source-library scope",
        "top_k": "integer 1..12",
    },
    "stage_notes": {
        "notes": {
            "type": "JSON array with exactly one note_schema object",
            "example": [_NOTE_EXAMPLE],
        }
    },
    "consolidate_notes": {
        "input_stage_ids": "all IDs in consolidation_inputs",
        "notes": {
            "type": "JSON array with exactly one note object, omitting source_block_ids",
            "example": [{key: value for key, value in _NOTE_EXAMPLE.items() if key != "source_block_ids"}],
        },
    },
    "publish_knowledge": {
        "notes": {
            "type": "for sources of at most 2 blocks: JSON array with exactly one note_schema object",
            "example": [_NOTE_EXAMPLE],
        },
        "staged_note_ids": "exactly the one final_stage ID",
    },
}


class _BodySizeValidationError(PublicationValidationError):
    def __init__(self, message: str, *, actual_bytes: int, target_bytes: int):
        super().__init__(message)
        self.actual_bytes = actual_bytes
        self.target_bytes = target_bytes


async def curate_source(
    library: Any,
    source_id: str,
    ctx: Any,
    *,
    timeout_s: float = 300,
) -> dict:
    """Inspect every source block through tools before one atomic publication."""
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        raise ValueError("timeout_s must be positive and finite")
    loaded_check = getattr(ctx, "selected_model_loaded", None)
    if callable(loaded_check):
        loaded = loaded_check("knowledge_query")
        if inspect.isawaitable(loaded):
            loaded = await loaded
        if loaded is not True:
            return {
                "ok": False,
                "status": "deferred",
                "source_id": source_id,
                "error": "model_unavailable",
            }

    trace: list[dict] = []
    recent_event: dict | None = None
    visible_event: dict | None = None
    stageable_ids: set[str] = set()
    page_drafts: dict[int, dict] = {}
    consolidation_queue: list[dict] | None = None
    consolidation_serial = 0
    cursor = 0
    validation_retries = 0
    publication_task: asyncio.Task | None = None
    publication_committed = False
    model = {"provider": "", "model": "", "mock": False, "real": True}
    try:
        await asyncio.to_thread(library.extract, source_id)
        overview = await asyncio.to_thread(library.inspect, source_id, offset=0, limit=1)
        total_blocks = overview["total_blocks"]
        ontology_types = overview["ontology_types"]
        note_schema = {
            **overview["note_schema"],
            "source_block_ids": (
                "currently visible block IDs; prior page provenance is unioned by code"
            ),
        }
        block_plan = await asyncio.to_thread(
            _block_plan,
            library,
            source_id,
            total_blocks,
        )
        all_block_ids = {item["block_id"] for item in block_plan}
        source_pages = sorted({item["page"] for item in block_plan})
        await asyncio.to_thread(library.mark, source_id, "processing")
        max_steps = total_blocks * 3 + len(source_pages) * 3 + 64
        for _ in range(max_steps):
            final_stage = (
                consolidation_queue[0]
                if consolidation_queue is not None and len(consolidation_queue) == 1
                else None
            )
            if cursor == 0 and recent_event is None:
                mode = "inspect"
                tools = {"inspect_source": _TOOLS["inspect_source"]}
                consolidation_inputs: list[dict] = []
            elif (
                total_blocks <= _MAX_INSPECT_BLOCKS
                and cursor == total_blocks
                and not page_drafts
                and stageable_ids == all_block_ids
                and len(source_pages) == 1
            ):
                mode = "review"
                tools = {
                    "search_existing": _TOOLS["search_existing"],
                    "publish_knowledge": {
                        "notes": _TOOLS["publish_knowledge"]["notes"]
                    },
                }
                consolidation_inputs = []
            elif stageable_ids:
                mode = "page_curation"
                tools = {"stage_notes": _TOOLS["stage_notes"]}
                consolidation_inputs = []
            else:
                if consolidation_queue is None:
                    consolidation_queue = [page_drafts[page] for page in source_pages]
                    final_stage = consolidation_queue[0] if len(consolidation_queue) == 1 else None
                if len(consolidation_queue) > 1:
                    mode = "consolidation"
                    consolidation_inputs = consolidation_queue[:_MAX_MERGE_INPUTS]
                    tools = {
                        "consolidate_notes": {
                            **_TOOLS["consolidate_notes"],
                            "input_stage_ids": {
                                "type": "JSON array in the exact supplied order",
                                "exact_value": [
                                    item["stage_id"] for item in consolidation_inputs
                                ],
                            },
                        },
                        "search_existing": _TOOLS["search_existing"],
                    }
                else:
                    mode = "review"
                    consolidation_inputs = []
                    final_stage = consolidation_queue[0]
                    tools = {
                        "search_existing": _TOOLS["search_existing"],
                        "publish_knowledge": {
                            "staged_note_ids": _TOOLS["publish_knowledge"][
                                "staged_note_ids"
                            ]
                        },
                    }
            current_page = block_plan[cursor - 1]["page"] if cursor else source_pages[0]
            observations = _phase_observations(mode, visible_event, recent_event)
            prompt = json.dumps(
                {
                    "task": "Curate reusable knowledge from a preserved local source.",
                    "mode": mode,
                    "source_id": source_id,
                    "total_blocks": total_blocks,
                    "inspection_progress": {
                        "inspected": cursor,
                        "total": total_blocks,
                        "complete": cursor == total_blocks,
                    },
                    "page_progress": {
                        "current": current_page,
                        "total": len(source_pages),
                        "completed": len(page_drafts),
                    },
                    "recent_inspected_block_ids": (
                        sorted(stageable_ids) if mode == "page_curation" else []
                    ),
                    "current_page_draft": (
                        _page_draft_prompt(page_drafts.get(current_page))
                        if mode == "page_curation"
                        else None
                    ),
                    **(
                        {
                            "page_update_contract": {
                                "operation": "cumulative_revision",
                                "retained_evidence": "current_page_draft, when present",
                                "new_evidence": "currently visible inspect_source blocks",
                                "priority": (
                                    "exact measurements, units, comparisons, test conditions, "
                                    "and qualifications before narrative, references, or roadmap"
                                ),
                            }
                        }
                        if mode == "page_curation"
                        else {}
                    ),
                    "staged_note_count": len(page_drafts),
                    "consolidation_inputs": [
                        _consolidation_prompt(item) for item in consolidation_inputs
                    ],
                    "consolidation_input_stage_ids": [
                        item["stage_id"] for item in consolidation_inputs
                    ],
                    "final_stage": (
                        _stage_inventory(final_stage)
                        if mode == "review" and final_stage
                        else None
                    ),
                    "ontology_types": ontology_types,
                    "note_schema": {
                        **note_schema,
                        "body": (
                            _body_contract(
                                _consolidation_body_limit(consolidation_queue),
                                mode=mode,
                            )
                            if mode == "consolidation"
                            else _body_contract(_MAX_PAGE_BODY_BYTES, mode=mode)
                        ),
                    },
                    "tools": tools,
                    "rules": [
                        "Return exactly one JSON object with tool and arguments keys.",
                        "Schema examples show structure only; never copy their factual content.",
                        "Process pages and their subchunks in the supplied order; never skip ahead.",
                        "Update one concise page draft from the prior draft plus the currently visible blocks.",
                        "Consolidate every supplied stage; final publication contains exactly one note.",
                        "Preserve exact quantities, units, qualifications, and conflicting conditions.",
                        "Label source-reported evidence separately from derived interpretation; do not invent verification.",
                        "Cite only source_block_ids actually returned by inspect_source.",
                        "Use actual Markdown newline characters encoded as JSON \\n escapes; never write literal backslash-n text.",
                        "Keep the note concise; complete text remains in source.md and per-page files.",
                        "Do not issue commands, change ontology, escape categories, or claim unavailable evidence.",
                        *_phase_curation_rules(
                            mode,
                            has_prior_page_draft=page_drafts.get(current_page) is not None,
                        ),
                    ],
                    "observations": observations,
                },
                ensure_ascii=False,
            )
            if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
                raise ValueError(
                    f"bounded curation prompt exceeds {_MAX_PROMPT_BYTES} UTF-8 bytes"
                )
            response = await asyncio.wait_for(
                ctx.complete(
                    "knowledge_query",
                    prompt,
                    timeout_s=float(timeout_s),
                    priority=RECONCILIATION_PRIORITY,
                    owner=f"source-curation:{source_id}",
                    lease_wait=True,
                ),
                timeout=float(timeout_s) + 1,
            )
            raw = getattr(response, "raw", {})
            is_mock = bool(isinstance(raw, dict) and raw.get("mock") is True)
            provider = str(getattr(ctx, "active_backend", "") or "unknown")
            model = {
                "provider": provider,
                "model": str(getattr(response, "model", "") or "unknown"),
                "mock": is_mock,
                "real": not is_mock,
            }
            tool, arguments = _request(str(getattr(response, "text", "")))
            if tool not in tools:
                raise ValueError(f"tool {tool} is not available in {mode} mode")
            observation: dict
            if tool == "inspect_source":
                offset = arguments.get("offset", 0)
                limit = arguments.get("limit", 8)
                if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                    raise ValueError("inspect_source offset is invalid")
                if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 16:
                    raise ValueError("inspect_source limit is invalid")
                if offset != cursor:
                    raise ValueError("inspect_source must continue at the next sequential offset")
                observation, cursor = await _inspect_next(
                    library, source_id, block_plan, cursor, requested_limit=limit
                )
                stageable_ids = {item["block_id"] for item in observation["blocks"]}
                visible_event = _prompt_event(tool, observation)
            elif tool == "search_existing":
                if cursor == 0:
                    raise ValueError("inspect source evidence before searching")
                query = _bounded_text(arguments.get("query"), "query", 2_000, empty=True)
                scope = arguments.get("scope", {})
                top_k = arguments.get("top_k", 6)
                if not isinstance(scope, dict):
                    raise ValueError("search scope must be an object")
                if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 12:
                    raise ValueError("search_existing top_k is invalid")
                observation = await asyncio.to_thread(
                    library.search,
                    query,
                    scope=scope,
                    top_k=top_k,
                )
            elif tool == "stage_notes":
                notes = arguments.get("notes")
                try:
                    clean_notes = _curated_notes(notes, exact_count=1)
                    actual_body_bytes = _utf8_size(clean_notes[0]["body"])
                    if actual_body_bytes > _MAX_PAGE_BODY_BYTES:
                        raise _BodySizeValidationError(
                            f"curated body exceeds {_MAX_PAGE_BODY_BYTES} UTF-8 bytes",
                            actual_bytes=actual_body_bytes,
                            target_bytes=_MAX_PAGE_BODY_BYTES,
                        )
                    cited_ids = _cited_block_ids(clean_notes)
                    page = block_plan[cursor - 1]["page"]
                    prior = page_drafts.get(page)
                    prior_ids = prior["note"]["source_block_ids"] if prior else []
                    if not cited_ids.issubset(stageable_ids):
                        raise ValueError("page note cites evidence outside its visible source batch")
                    if not cited_ids:
                        raise ValueError("page note must cite the currently visible source batch")
                    clean_notes[0] = {
                        **clean_notes[0],
                        "source_block_ids": _ordered_union(
                            [prior_ids, clean_notes[0]["source_block_ids"]]
                        ),
                    }
                    staged_result = await asyncio.to_thread(
                        library.stage_notes,
                        source_id,
                        clean_notes,
                        stage_key=f"page-{page:04d}-revision-{cursor:04d}",
                    )
                    entry = _stage_entry(staged_result, pages={page})
                    page_drafts[page] = entry
                    validation_retries = 0
                    observation = {
                        "ok": True,
                        "status": "staged",
                        "stage_id": entry["stage_id"],
                        "page": page,
                    }
                except PublicationValidationError as exc:
                    validation_retries += 1
                    if validation_retries > _MAX_VALIDATION_RETRIES:
                        raise
                    observation = _validation_feedback(exc, validation_retries)
                    trace.append(
                        {"tool": tool, "arguments": arguments, "observation": observation}
                    )
                    recent_event = _prompt_event(tool, observation)
                    continue
                trace.append({"tool": tool, "arguments": arguments, "observation": observation})
                stageable_ids = set()
                visible_event = None
                if cursor < total_blocks:
                    next_observation, cursor = await _inspect_next(
                        library,
                        source_id,
                        block_plan,
                        cursor,
                        requested_limit=_MAX_INSPECT_BLOCKS,
                    )
                    stageable_ids = {
                        item["block_id"] for item in next_observation["blocks"]
                    }
                    automatic = {
                        "tool": "inspect_source",
                        "arguments": {"offset": next_observation["offset"], "automatic": True},
                        "observation": next_observation,
                    }
                    trace.append(automatic)
                    visible_event = _prompt_event("inspect_source", next_observation)
                    recent_event = visible_event
                    continue
                consolidation_queue = None
                recent_event = _prompt_event(tool, observation)
                continue
            elif tool == "consolidate_notes":
                if consolidation_queue is None or len(consolidation_queue) <= 1:
                    raise ValueError("no consolidation batch is available")
                batch = consolidation_queue[:_MAX_MERGE_INPUTS]
                requested_ids = arguments.get("input_stage_ids")
                expected_ids = [item["stage_id"] for item in batch]
                try:
                    if requested_ids != expected_ids:
                        raise PublicationValidationError(
                            "input_stage_ids must exactly equal the supplied ordered array: "
                            + json.dumps(expected_ids)
                        )
                    authored = arguments.get("notes")
                    if not isinstance(authored, list) or len(authored) != 1:
                        raise PublicationValidationError(
                            "consolidation notes must be a JSON array with exactly one object"
                        )
                    note = authored[0]
                    if not isinstance(note, dict) or "source_block_ids" in note:
                        raise PublicationValidationError(
                            "consolidated note must omit source_block_ids; provenance is unioned by code"
                        )
                    citations = _ordered_union(
                        item["note"]["source_block_ids"] for item in batch
                    )
                    clean_notes = _curated_notes(
                        [{**note, "source_block_ids": citations}], exact_count=1
                    )
                    body_limit = _consolidation_body_limit(consolidation_queue)
                    actual_body_bytes = _utf8_size(clean_notes[0]["body"])
                    if actual_body_bytes > body_limit:
                        raise _BodySizeValidationError(
                            f"consolidated body exceeds {body_limit} UTF-8 bytes",
                            actual_bytes=actual_body_bytes,
                            target_bytes=body_limit,
                        )
                    consolidation_serial += 1
                    staged_result = await asyncio.to_thread(
                        library.stage_notes,
                        source_id,
                        clean_notes,
                        stage_key=f"merge-{consolidation_serial:04d}",
                    )
                    merged = _stage_entry(
                        staged_result,
                        pages=set().union(*(item["pages"] for item in batch)),
                    )
                    consolidation_queue = [merged, *consolidation_queue[len(batch) :]]
                    validation_retries = 0
                    observation = {
                        "ok": True,
                        "status": "consolidated",
                        "stage_id": merged["stage_id"],
                        "input_count": len(batch),
                    }
                except PublicationValidationError as exc:
                    validation_retries += 1
                    if validation_retries > _MAX_VALIDATION_RETRIES:
                        raise
                    observation = _validation_feedback(exc, validation_retries)
            elif tool == "publish_knowledge":
                if cursor != total_blocks:
                    raise ValueError("inspect all source blocks before publication")
                try:
                    notes = _publication_notes(arguments, final_stage, total_blocks)
                except PublicationValidationError as exc:
                    validation_retries += 1
                    if validation_retries > _MAX_VALIDATION_RETRIES:
                        raise
                    observation = _validation_feedback(exc, validation_retries)
                    trace.append(
                        {"tool": tool, "arguments": arguments, "observation": observation}
                    )
                    recent_event = _prompt_event(tool, observation)
                    continue
                cited_ids = _cited_block_ids(notes)
                if not cited_ids.issubset(all_block_ids):
                    raise ValueError("publication cites an uninspected source block")
                try:
                    publication_trace = _publication_audit_trace([
                        *trace,
                        {
                            "tool": "publish_knowledge",
                            "arguments": arguments,
                            "observation": {"status": "publication_requested"},
                        },
                    ])
                    publication_task = asyncio.create_task(
                        asyncio.to_thread(
                            library.publish,
                            source_id,
                            notes,
                            model=model,
                            trace=publication_trace,
                        )
                    )
                    publication = await asyncio.shield(publication_task)
                    publication_committed = True
                except PublicationValidationError as exc:
                    publication_task = None
                    validation_retries += 1
                    if validation_retries > _MAX_VALIDATION_RETRIES:
                        raise
                    observation = _validation_feedback(exc, validation_retries)
                    trace.append(
                        {"tool": tool, "arguments": arguments, "observation": observation}
                    )
                    recent_event = _prompt_event(tool, observation)
                    continue
                observation = publication
                trace.append({"tool": tool, "arguments": arguments, "observation": observation})
                return {
                    "ok": True,
                    "status": "ready",
                    "source_id": source_id,
                    "publication": publication,
                    "model": model,
                    "trace": trace,
                }
            else:  # pragma: no cover - guarded by _request
                raise ValueError("unsupported source curation tool")
            trace.append({"tool": tool, "arguments": arguments, "observation": observation})
            recent_event = _prompt_event(tool, observation)
        raise ValueError("source curation step limit reached")
    except asyncio.CancelledError:
        if publication_task is not None:
            try:
                await publication_task
            except Exception:
                publication_committed = False
            else:
                publication_committed = True
        if not publication_committed:
            await asyncio.to_thread(library.mark, source_id, "extracted")
        raise
    except Exception as exc:
        try:
            await asyncio.to_thread(
                library.mark,
                source_id,
                "failed",
                error=f"{type(exc).__name__}: {exc}"[:4_000],
            )
        except Exception:
            pass
        return {
            "ok": False,
            "status": "failed",
            "source_id": source_id,
            "error": type(exc).__name__,
            "message": str(exc)[:1_000],
            "model": model,
            "trace": trace,
        }


def _curated_notes(value: Any, *, exact_count: int = 1) -> list[dict]:
    if not isinstance(value, list) or len(value) != exact_count:
        raise PublicationValidationError(f"notes must contain exactly {exact_count} entry")
    notes: list[dict] = []
    for note in value:
        if not isinstance(note, dict):
            raise PublicationValidationError("notes must be objects")
        body = note.get("body")
        if not isinstance(body, str) or not body.strip():
            raise PublicationValidationError("body must be a non-empty Markdown string")
        block_ids = note.get("source_block_ids")
        if not isinstance(block_ids, list) or not 1 <= len(block_ids) <= 4_096:
            raise PublicationValidationError(
                "source_block_ids must contain 1 to 4096 entries"
            )
        notes.append(note)
    return notes


def _publication_notes(arguments: dict, final_stage: dict | None, total_blocks: int) -> list[dict]:
    has_notes = "notes" in arguments
    has_staged = "staged_note_ids" in arguments
    if has_notes == has_staged:
        raise PublicationValidationError(
            "publish exactly one of notes or staged_note_ids"
        )
    if has_notes:
        if total_blocks > _MAX_INSPECT_BLOCKS:
            raise PublicationValidationError(
                "long sources must publish selected staged_note_ids"
            )
        return _curated_notes(arguments["notes"], exact_count=1)
    stage_ids = arguments["staged_note_ids"]
    if not isinstance(stage_ids, list) or len(stage_ids) != 1:
        raise PublicationValidationError("staged_note_ids must contain exactly one ID")
    if final_stage is None or stage_ids[0] != final_stage["stage_id"]:
        raise ValueError("publication selected an unknown staged note")
    return [final_stage["note"]]


def _stage_inventory(stage: dict) -> dict:
    return {
        "stage_id": stage["stage_id"],
        "title": stage["note"]["title"],
        "category": stage["note"]["category"],
        "ontology_type": stage["note"]["ontology_type"],
        "pages": _page_ranges(stage["pages"]),
        "citation_count": len(stage["note"]["source_block_ids"]),
    }


def _page_draft_prompt(stage: dict | None) -> dict | None:
    if stage is None:
        return None
    return {
        **_stage_inventory(stage),
        **{
            key: value
            for key, value in stage["note"].items()
            if key != "source_block_ids"
        },
    }


def _consolidation_prompt(stage: dict) -> dict:
    return {
        **_stage_inventory(stage),
        "body": stage["note"]["body"],
        "tags": stage["note"]["tags"],
        "applicability": stage["note"]["applicability"],
    }


def _stage_entry(result: dict, *, pages: set[int]) -> dict:
    records = result.get("records")
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError("intermediate stage must contain exactly one validated record")
    record = records[0]
    fields = (
        "title",
        "body",
        "category",
        "ontology_type",
        "tags",
        "applicability",
        "source_block_ids",
    )
    return {
        "stage_id": result["stage_id"],
        "note": {field: record[field] for field in fields},
        "pages": set(pages),
    }


def _page_ranges(pages: set[int]) -> str:
    ordered = sorted(pages)
    ranges: list[str] = []
    start = end = ordered[0]
    for page in ordered[1:]:
        if page == end + 1:
            end = page
            continue
        ranges.append(str(start) if start == end else f"{start}-{end}")
        start = end = page
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return ",".join(ranges)


def _ordered_union(groups: Any) -> list[str]:
    result: list[str] = []
    for group in groups:
        for item in group:
            if item not in result:
                result.append(item)
    return result


def _consolidation_body_limit(queue: list[dict] | None) -> int:
    if queue is not None and len(queue) <= _MAX_MERGE_INPUTS:
        return _MAX_FINAL_BODY_BYTES
    return _MAX_INTERMEDIATE_BODY_BYTES


def _body_contract(hard_limit: int, *, mode: str) -> str:
    soft_target = 4_000 if hard_limit == _MAX_FINAL_BODY_BYTES else 1_200
    word_target = 450 if hard_limit == _MAX_FINAL_BODY_BYTES else 120
    purpose = {
        "page_curation": "CUMULATIVE page draft retaining prior and new evidence",
        "consolidation": "complete synthesis covering every supplied consolidation input",
    }.get(mode, "source-grounded note")
    return (
        f"{purpose}; compact Markdown bullets; about {word_target} words maximum; "
        f"soft target at most {soft_target} UTF-8 bytes; "
        f"hard max at most {hard_limit} UTF-8 bytes; remove repetition and background"
    )


def _phase_curation_rules(mode: str, *, has_prior_page_draft: bool) -> list[str]:
    if mode == "page_curation":
        return [
            "CUMULATIVE PAGE UPDATE: synthesize retained current_page_draft evidence together with the new visible blocks.",
            (
                "The current_page_draft is authoritative retained evidence; never replace it "
                "with a summary of only the newest blocks."
                if has_prior_page_draft
                else "Create the first cumulative page draft from all currently visible evidence."
            ),
            "Carry forward every prior quantitative result, exact value, unit, comparison, test condition, qualification, limitation, and evidence classification.",
            "Add substantive new evidence without erasing retained evidence; use terse bullets or a compact table to stay within the hard byte limit.",
            "If space is tight, remove repetition, narrative background, reference listings, and roadmap detail before any measurement or its conditions.",
            "Roadmap and future-work statements are lower priority than source-reported measurements and cannot erase them.",
        ]
    if mode == "consolidation":
        return [
            "The consolidated body MUST cover the substantive findings from EVERY consolidation input; later inputs cannot erase earlier measurements or conditions.",
            "Prioritize exact quantitative results, units, comparisons, configurations, conditions, and qualifications over narrative or bibliography.",
            "Distinguish the primary source's own results from results merely quoted from cited works and from appendix or example content; preserve attribution.",
            "Reference-list entries are provenance, not software dependencies and not evidence that a cited package was used by the primary source.",
            "Under space pressure, compress or omit bibliographic cataloging before any substantive measurement, condition, conflict, or limitation.",
        ]
    return []


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _prompt_observations(visible: dict | None, recent: dict | None) -> list[dict]:
    if visible is None:
        return [recent] if recent is not None else []
    if recent is None or recent == visible:
        return [visible]
    return [visible, recent]


def _phase_observations(
    mode: str,
    visible: dict | None,
    recent: dict | None,
) -> list[dict]:
    if mode in {"inspect", "page_curation"}:
        return _prompt_observations(visible, recent)
    if mode == "review" and visible is not None and visible.get("tool") == "inspect_source":
        return _prompt_observations(visible, recent)
    candidates = _prompt_observations(None, recent)
    return [
        event
        for event in candidates
        if event.get("tool") == "search_existing"
        or event.get("observation", {}).get("status") == "validation_error"
    ]


def _publication_audit_trace(events: list[dict]) -> list[dict]:
    return [_publication_audit_event(event) for event in events]


def _publication_audit_event(event: dict) -> dict:
    tool = event.get("tool")
    arguments = dict(event.get("arguments", {}))
    observation = dict(event.get("observation", {}))
    if "notes" in arguments:
        notes = arguments["notes"]
        if isinstance(notes, list):
            arguments["notes"] = [_audit_note(note) for note in notes]
        else:
            arguments["notes"] = {
                "invalid_type": type(notes).__name__,
                "value_sha256": _json_digest(notes),
            }
    if tool == "inspect_source":
        source_id = str(observation.get("source_id", ""))
        observation["blocks"] = [
            {
                "block_id": block["block_id"],
                "page": block["page"],
                "text_sha256": hashlib.sha256(block["text"].encode("utf-8")).hexdigest(),
                "source_ref": f"source:{source_id}#{block['block_id']}",
            }
            for block in observation.get("blocks", [])
        ]
        observation.pop("ontology_types", None)
        observation.pop("note_schema", None)
    elif tool == "search_existing":
        observation["hits"] = [
            {
                "record_id": hit.get("record_id"),
                "source_id": hit.get("source_id"),
                "score": hit.get("score"),
            }
            for hit in observation.get("hits", [])
        ]
    projected = {"tool": tool, "arguments": arguments, "observation": observation}
    if _utf8_size(_canonical_json(projected)) <= MAX_AUDIT_EVENT_BYTES:
        return projected
    return {
        "tool": tool,
        "compacted": True,
        "event_sha256": _json_digest(event),
        "arguments_sha256": _json_digest(event.get("arguments")),
        "observation_sha256": _json_digest(event.get("observation")),
        "refs": _audit_refs(event),
    }


def _audit_note(note: Any) -> dict:
    if not isinstance(note, dict):
        return {"invalid_type": type(note).__name__, "value_sha256": _json_digest(note)}
    body = note.get("body")
    block_ids = note.get("source_block_ids")
    return {
        "title": note.get("title"),
        "category": note.get("category"),
        "ontology_type": note.get("ontology_type"),
        "note_sha256": _json_digest(note),
        "body_sha256": (
            hashlib.sha256(body.encode("utf-8")).hexdigest()
            if isinstance(body, str)
            else None
        ),
        "body_bytes": _utf8_size(body) if isinstance(body, str) else None,
        "source_block_ids_sha256": _json_digest(block_ids),
        "source_block_count": len(block_ids) if isinstance(block_ids, list) else None,
    }


def _json_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _audit_refs(value: Any) -> dict:
    aliases = {
        "source_id": "source_ids",
        "source_ids": "source_ids",
        "block_id": "block_ids",
        "source_block_ids": "block_ids",
        "page": "pages",
        "pages": "pages",
        "stage_id": "stage_ids",
        "input_stage_ids": "stage_ids",
        "staged_note_ids": "stage_ids",
    }
    found: dict[str, list[str | int]] = {
        "source_ids": [],
        "block_ids": [],
        "pages": [],
        "stage_ids": [],
    }

    def collect(item: Any, key: str | None = None) -> None:
        target = aliases.get(key or "")
        if target and isinstance(item, (str, int)) and not isinstance(item, bool):
            if item not in found[target]:
                found[target].append(item)
            return
        if isinstance(item, dict):
            for child_key, child in item.items():
                collect(child, child_key)
        elif isinstance(item, list):
            for child in item:
                collect(child, key)

    collect(value)
    return {
        key: _audit_ref_summary(items)
        for key, items in found.items()
        if items
    }


def _audit_ref_summary(items: list[str | int]) -> dict:
    if len(items) <= 4 and all(len(str(item).encode("utf-8")) <= 128 for item in items):
        return {"values": items}
    return {"count": len(items), "sha256": _json_digest(items)}


def _prompt_event(tool: str, observation: dict) -> dict:
    compact = dict(observation)
    if tool == "inspect_source":
        compact = {
            key: observation.get(key)
            for key in ("source_id", "blocks", "total_blocks", "offset", "next_offset")
        }
        compact["blocks"] = [
            {
                **block,
                "text": re.sub(r"[ \t]{2,}", " ", block["text"]),
            }
            for block in observation.get("blocks", [])
        ]
    elif tool == "search_existing":
        compact["hits"] = [
            {
                key: hit.get(key)
                for key in (
                    "record_id",
                    "source_id",
                    "title",
                    "excerpt",
                    "category",
                    "ontology_type",
                    "tags",
                )
            }
            for hit in observation.get("hits", [])[:6]
        ]
    return {"tool": tool, "arguments": {}, "observation": compact}


def _validation_feedback(exc: Exception, attempt: int) -> dict:
    result = {
        "ok": False,
        "status": "validation_error",
        "message": str(exc)[:500],
        "correction_attempt": attempt,
        "remaining_attempts": _MAX_VALIDATION_RETRIES - attempt,
    }
    actual_bytes = getattr(exc, "actual_bytes", None)
    target_bytes = getattr(exc, "target_bytes", None)
    if isinstance(actual_bytes, int) and isinstance(target_bytes, int):
        soft_target = 1_200 if target_bytes == _MAX_PAGE_BODY_BYTES else 4_000
        word_target = 120 if target_bytes == _MAX_PAGE_BODY_BYTES else 450
        result["actual_bytes"] = actual_bytes
        result["target_bytes"] = target_bytes
        result["soft_target_bytes"] = soft_target
        result["correction_instruction"] = (
            f"REWRITE the same grounded evidence as compact Markdown bullets: about "
            f"{word_target} words or fewer and target at most {soft_target} UTF-8 bytes "
            f"(hard maximum {target_bytes}; previous body was {actual_bytes}). Remove "
            "repetition and background, retain key quantities/units/qualifications, and "
            "return one corrected call using the required one-element JSON notes array."
        )
    else:
        result["category_requirement"] = (
            "^[a-z0-9][a-z0-9-]{0,79}$; use hyphens, for example material-properties"
        )
    return result


def _block_plan(library: Any, source_id: str, total: int) -> list[dict]:
    blocks: list[dict] = []
    for offset in range(0, total, 64):
        page = library.inspect(source_id, offset=offset, limit=64)
        blocks.extend(
            {"block_id": item["block_id"], "page": item["page"]}
            for item in page["blocks"]
        )
    if len(blocks) != total:
        raise ValueError("source block index is inconsistent")
    return blocks


async def _inspect_next(
    library: Any,
    source_id: str,
    block_plan: list[dict],
    cursor: int,
    *,
    requested_limit: int,
) -> tuple[dict, int]:
    page = block_plan[cursor]["page"]
    page_remaining = 0
    for item in block_plan[cursor:]:
        if item["page"] != page:
            break
        page_remaining += 1
    limit = min(requested_limit, _MAX_INSPECT_BLOCKS, page_remaining)
    observation = await asyncio.to_thread(
        library.inspect,
        source_id,
        offset=cursor,
        limit=limit,
    )
    if not observation["blocks"] or any(item["page"] != page for item in observation["blocks"]):
        raise ValueError("source page index is inconsistent")
    return observation, cursor + len(observation["blocks"])


def _request(text: str) -> tuple[str, dict]:
    value = text.strip()
    if value.startswith("```json\n") and value.endswith("```"):
        value = value[8:-3].strip()
    payload = json.loads(value)
    if not isinstance(payload, dict) or set(payload) != {"tool", "arguments"}:
        raise ValueError("return exactly one tool/arguments JSON object")
    tool = payload["tool"]
    arguments = payload["arguments"]
    if tool not in _TOOLS or not isinstance(arguments, dict):
        raise ValueError("unknown source curation tool")
    if set(arguments) - set(_TOOLS[tool]):
        raise ValueError("unknown source curation tool argument")
    return tool, arguments


def _cited_block_ids(notes: Any) -> set[str]:
    if not isinstance(notes, list) or not notes:
        raise ValueError("publish_knowledge notes must be non-empty")
    result: set[str] = set()
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError("publish_knowledge notes must be objects")
        block_ids = note.get("source_block_ids")
        if not isinstance(block_ids, list):
            raise ValueError("source_block_ids must be a list")
        for block_id in block_ids:
            if not isinstance(block_id, str):
                raise ValueError("source_block_ids must contain strings")
            result.add(block_id)
    return result


def _bounded_text(value: Any, field: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"invalid {field}")
    return value.strip()
