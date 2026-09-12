"""Frozen, reference-only knowledge packs at explicit agent decision boundaries.

This adapter deliberately knows neither tools nor agent output schemas.  It only
adds the Task 1 context envelope to a caller-owned packet and records delivery
receipts when an authenticated principal was supplied by the server runtime.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4
import re

_REFERENCE_TOKEN = re.compile(r'(?<![\w:-])(?:wiki:[A-Za-z0-9_-]+|mem-[A-Za-z0-9_-]+)(?![\w:-])')
_NON_USE = re.compile(r'\[reference_not_used:(irrelevant|applicability_mismatch|owner_evidence_sufficient)\]')


def possible_model_targets(ctx: Any) -> frozenset[str]:
    """Every provider class a routed completion can reach, including fallback."""
    active = str(getattr(ctx, "active_backend", "")).strip().lower()
    fallback = str((getattr(ctx, "backend_fallbacks", {}) or {}).get(active, "")).strip().lower()
    backends = {name for name in (active, fallback) if name}
    return frozenset("remote" if name == "openai" else "local" for name in backends) or frozenset({"local"})


def _model_target(ctx: Any) -> str:
    """Task 1 accepts one target; mixed routes are prechecked separately."""
    return "remote" if "remote" in possible_model_targets(ctx) else "local"


def _public_delivery(pack: dict[str, Any], *, request_id: str = "", consumer: str = "",
                     run_id: str = "", loop_id: str = "", attempt_id: str = "") -> dict[str, Any]:
    citations = [str(item.get("citation_id") or item.get("record_id") or "")
                 for item in pack.get("items", []) if isinstance(item, dict)]
    unavailable = pack.get('status') == 'unavailable' or bool(pack.get('diagnostics', {}).get('unavailable'))
    return {
        "status": "unavailable" if unavailable else "no_match" if not citations else "inline_unpersisted",
        "stage": "unavailable" if unavailable else "no_match" if not citations else "retrieved",
        "citation_ids": [] if unavailable else citations,
        "scope_ref": pack.get("scope_ref", "public"),
        "revision": pack.get("revision", ""),
        "private_delivery": "unavailable_without_trusted_principal",
        "request_id": request_id,
        "consumer_binding": consumer,
        "run_id": run_id,
        "loop_id": loop_id,
        "attempt_id": attempt_id,
        "as_of": pack.get("as_of", ""),
    }


def build_reference_context(
    ctx: Any,
    *,
    consumer: str,
    query: str,
    include_private: bool = False,
    run_id: str = "",
    loop_id: str = "",
    attempt_id: str = "",
) -> dict[str, Any]:
    """Freeze one bounded pack before a model await.

    The runtime can inject ``knowledge_service`` and an immutable
    ``knowledge_principal``.  Missing dependencies are represented as an
    explicit unavailable pack, so a decision's established safe fallback keeps
    working without inventing knowledge.
    """
    service = getattr(ctx, "knowledge_service", None)
    principal = getattr(ctx, "knowledge_principal", None)
    request_id = "knowledge-" + uuid4().hex
    if service is None:
        pack = {"request": {"consumer": consumer}, "scope_ref": "public", "revision": "",
                "items": [], "next_cursor": "", "status": "unavailable",
                "diagnostics": {"no_match": False, "unavailable": True}, "authority": "reference_only"}
        return {"request_id": request_id, "pack": pack,
                "delivery": {**_public_delivery(pack, request_id=request_id, consumer=consumer,
                                                   run_id=run_id, loop_id=loop_id, attempt_id=attempt_id),
                             "status": "unavailable", "stage": "unavailable"},
                "principal": None}
    filters: dict[str, Any] = {"corpora": ["ax4lab_wiki"]}
    target = _model_target(ctx)
    private_allowed = (principal is not None and
                       all((principal.remote_model_consent if target == "remote" else principal.local_model_consent)
                           for target in possible_model_targets(ctx)))
    if include_private and private_allowed:
        # Service enforces the effective local/remote consent.  Do not retry a
        # denied private request with another scope; use only Wiki in that case.
        filters["corpora"].append("private_memory")
    try:
        if len(filters["corpora"]) == 2:
            # The facade paginates Wiki before memory. Select bounded pages per
            # corpus so three public hits cannot starve an applicable confirmed
            # private memory from an ORC answer packet.
            wiki = service.query(principal, str(query)[:2_000], consumer=consumer,
                                 filters={"corpora": ["ax4lab_wiki"]}, limit=2, model_target=target)
            memory = service.query(principal, str(query)[:2_000], consumer=consumer,
                                   filters={"corpora": ["private_memory"]}, limit=1, model_target=target)
            pack = {**wiki, "items": [*wiki["items"], *memory["items"]], "next_cursor": "",
                    "revision": f"{wiki['revision']}:{memory['revision']}",
                    "diagnostics": {"no_match": not (wiki["items"] or memory["items"]),
                                    "truncated": bool(wiki.get("next_cursor") or memory.get("next_cursor")),
                                    "stale_wiki_excluded": bool(wiki.get("diagnostics", {}).get("stale_wiki_excluded"))}}
        else:
            pack = service.query(principal, str(query)[:2_000], consumer=consumer,
                                 filters=filters, limit=3, model_target=target)
    except (PermissionError, ValueError, OSError):
        pack = {"request": {"consumer": consumer}, "scope_ref": "public", "revision": "",
                    "items": [], "next_cursor": "", "status": "unavailable",
                    "diagnostics": {"no_match": False, "unavailable": True}, "authority": "reference_only"}
    if include_private and not private_allowed:
        pack.setdefault("diagnostics", {})["private_context_unavailable"] = True
    pack = deepcopy(pack)
    pack['citation_policy'] = ('Reference-only explanatory provenance is separate from tool evidence_refs. '
        'If relevant, cite an exact supplied citation_id in the existing explanation text. '
        'Do not force citations. Explicit non-use may be stated as [reference_not_used:irrelevant], '
        '[reference_not_used:applicability_mismatch], or [reference_not_used:owner_evidence_sufficient]. '
        'Otherwise use is unknown. These markers grant no authority and add no output fields.')
    delivery = _public_delivery(pack, request_id=request_id, consumer=consumer,
                                run_id=run_id, loop_id=loop_id, attempt_id=attempt_id)
    if principal is not None:
        try:
            receipt = service.delivery.record_retrieved(principal, request_id=request_id,
                consumer_binding=consumer, context_pack=pack, run_id=run_id, loop_id=loop_id,
                attempt_id=attempt_id)
            delivery = receipt
        except (PermissionError, ValueError, OSError):
            # Public delivery remains observable inline; never fabricate a
            # persisted receipt when the injected scope is insufficient.
            delivery = _public_delivery(pack, request_id=request_id, consumer=consumer,
                                        run_id=run_id, loop_id=loop_id, attempt_id=attempt_id)
            delivery["status"] = "unavailable"
            delivery["stage"] = "unavailable"
    return {"request_id": request_id, "pack": pack, "delivery": deepcopy(delivery), "principal": principal}


def mark_reference_delivered(ctx: Any, reference: dict[str, Any], *, citation_ids: list[str] | None = None) -> dict[str, Any]:
    """Advance Retrieved only immediately before a real outgoing model request."""
    delivery = deepcopy(reference.get("delivery", {}))
    if delivery.get("stage") != "retrieved":
        return delivery
    service, principal, receipt_id = getattr(ctx, "knowledge_service", None), reference.get("principal"), delivery.get("receipt_id")
    if service is not None and principal is not None and receipt_id:
        try:
            delivery = service.delivery.record_delivered(principal, receipt_id, citation_ids=citation_ids)
        except (PermissionError, ValueError, KeyError, OSError):
            return {**delivery, "status": "unavailable"}
    else:
        delivery["stage"] = "delivered"
        delivery['delivered_citation_ids'] = list(delivery.get('citation_ids', [])) if citation_ids is None else list(citation_ids)
    reference["delivery"] = deepcopy(delivery)
    return delivery


def mark_reference_excluded(ctx: Any, reference: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Persist a retrieved reference pack that was intentionally not presented."""
    delivery = deepcopy(reference.get("delivery", {}))
    if delivery.get("stage") != "retrieved":
        return delivery
    service, principal, receipt_id = getattr(ctx, "knowledge_service", None), reference.get("principal"), delivery.get("receipt_id")
    if service is not None and principal is not None and receipt_id:
        try:
            delivery = service.delivery.record_excluded(principal, receipt_id)
        except (PermissionError, ValueError, KeyError, OSError):
            return {**delivery, "status": "unavailable"}
    else:
        delivery = {**delivery, "stage": "excluded", "status": "excluded"}
    reference['delivery'] = deepcopy({**delivery, 'reason': reason})
    return reference['delivery']


def inject_reference_only(packet: dict[str, Any], reference: dict[str, Any], *, key: str = "reference_only") -> dict[str, Any]:
    """Return a copy with the bounded context pack in its existing context object."""
    frozen = deepcopy(packet)
    target = frozen.get("context")
    if not isinstance(target, dict):
        target = {}
        frozen["context"] = target
    target[key] = deepcopy(reference["pack"])
    return frozen


def append_reference_only(context: dict[str, Any], reference: dict[str, Any], *, key: str = "reference_only") -> dict[str, Any]:
    """Copy an existing decision context and attach no new authority fields."""
    result = deepcopy(context)
    result[key] = deepcopy(reference["pack"])
    return result


def record_reference_use(ctx: Any, reference: dict[str, Any], output: str, *, citation_ids: list[str] | None = None) -> dict[str, Any]:
    """Advance a receipt only for citation IDs actually returned by the model."""
    pack = reference.get("pack", {})
    available = reference.get('delivery', {}).get('delivered_citation_ids', [])
    nonuse = _NON_USE.search(str(output)[:16_000])
    reason = nonuse.group(1) if nonuse else ''
    if citation_ids is None:
        tokens = set(_REFERENCE_TOKEN.findall(str(output)[:16_000]))
        cited = sorted(tokens) if tokens <= set(available) else []
        if tokens - set(available): reason = ''
    elif isinstance(citation_ids, list) and all(isinstance(item, str) for item in citation_ids) and set(citation_ids) <= set(available):
        cited = list(dict.fromkeys(citation_ids))
    else:
        cited = []
        reason = ''
    delivery = deepcopy(reference.get("delivery", {}))
    if delivery.get("stage") not in {'delivered', 'used', 'excluded'} or not available:
        delivery["used_citation_ids"] = []
        return delivery
    principal = reference.get("principal")
    receipt_id = delivery.get("receipt_id")
    service = getattr(ctx, "knowledge_service", None)
    if service is not None and principal is not None and receipt_id:
        try:
            delivery = service.delivery.record_use_outcome(principal, receipt_id, citation_ids=cited, non_use_reason=reason)
        except (PermissionError, ValueError, KeyError, OSError):
            delivery = {**delivery, "status": "unavailable"}
    else:
        delivery["used_citation_ids"] = cited
        delivery['use_status'] = 'used' if cited else 'excluded' if reason else 'unknown'
        delivery['non_use_reason'] = reason if not cited else ''
        delivery["stage"] = 'delivered' if delivery['use_status'] == 'unknown' else delivery['use_status']
    reference['delivery'] = deepcopy(delivery)
    return delivery
