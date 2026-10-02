"""Read-only source knowledge tools shared by existing agents."""
import json

_CONTEXT_BYTES = 12000


def _size(value):
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def _bounded_context(value):
    if _size(value) <= _CONTEXT_BYTES:
        return value
    return {"status": "unavailable", "notes": [], "citations": [], "authority": "reference_only",
            "error": "source_context_exceeds_budget", "scope_omitted": True, "truncated": True}


def retired_manual_context(query, *, purpose):
    """Keep old audit consumers explicit without reading any historic corpus."""
    return {"schema": "manual_context.v1", "status": "retired", "query": query,
            "purpose": purpose, "chunks": [], "insufficient_evidence": True,
            "replacement": "knowledge.sources", "source_separation": {
                "manual_only": False, "web_used": False, "runtime_memory_used": False}}


def register_source_tools(tools, library_factory):
    tools.register_resource("knowledge.sources", library_factory)

    def search(payload):
        if set(payload) - {"query", "scope", "top_k"}:
            raise ValueError("Unknown source search argument")
        return library_factory().search(payload.get("query", ""), scope=payload.get("scope"),
                                        top_k=payload.get("top_k", 6))

    def read(payload):
        if set(payload) - {"record_id", "scope"}:
            raise ValueError("Unknown source read argument")
        return library_factory().read(payload.get("record_id", ""), scope=payload.get("scope"))

    tools.register("knowledge.sources.search", search)
    tools.register("knowledge.sources.read", read)


def source_library_for_context(ctx):
    getter = getattr(getattr(ctx, "tools", None), "resource", None)
    factory = getter("knowledge.sources") if getter else None
    return factory() if callable(factory) else factory


def source_context(ctx, query, *, scope=None, top_k=3):
    """Build cited reference evidence, never executable proposals or parameters."""
    unavailable = {"status": "unavailable", "notes": [], "citations": [], "scope": scope or {},
                   "authority": "reference_only"}
    if _size(unavailable) > _CONTEXT_BYTES:
        return _bounded_context(unavailable)
    try:
        library = source_library_for_context(ctx)
        if library is None:
            return unavailable
        found = library.search(query, scope=scope, top_k=top_k)
        notes, citations, truncated = [], [], False
        for hit in found["hits"]:
            detail = library.read(hit["record_id"], scope=found["scope"])
            if not detail.get("ok") or not detail.get("record"):
                continue
            record = detail["record"]
            body = record.get("body", "")
            refs = record.get("source_refs", [])
            cited = record.get("citations", hit.get("citations", []))
            note = {"record_id": record["record_id"], "title": record.get("title", "")[:200],
                    "body": body[:1200], "body_truncated": len(body) > 1200,
                    "applicability": record.get("applicability", {}), "source_refs": refs[:3],
                    "citations_truncated": len(cited) > 3 or len(refs) > 3,
                    "detail_tool": "knowledge.sources.read"}
            candidate = {**unavailable, "notes": notes + [note], "citations": citations + cited[:3],
                         "scope": found["scope"], "truncated": True}
            if _size(candidate) > _CONTEXT_BYTES:
                truncated = True
                continue  # Do not strip applicability to make an unsafe partial condition fit.
            notes.append(note)
            citations.extend(cited[:3])
            truncated = truncated or note["body_truncated"] or note["citations_truncated"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _bounded_context({**unavailable, "error": type(exc).__name__})
    return _bounded_context({"status": "ready" if notes else "unavailable" if truncated else "no_match", "notes": notes,
            "citations": citations, "scope": found["scope"], "authority": "reference_only", "truncated": truncated})
