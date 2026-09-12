---
doc_type: plan
subtype: implementation
status: active
authority: execution
execution_status: in_progress
audience: [developer, maintainer]
scope: [knowledge, ax4lab_wiki, private_memory, orchestrator_chat, workspace]
summary: Implement scoped Wiki and memory delivery on existing agent and GUI paths.
governing_design:
  - docs/superpowers/specs/2026-09-12-ax4lab-wiki-memory-orchestrator-design.md
related_docs:
  - docs/knowledge/wiki_memory.md
  - docs/knowledge/publication.md
supersedes: []
---

# AX4LAB Wiki, Memory and Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Follow TDD and preserve existing runtime paths.

**Goal:** Supply each active agent with scoped AX4LAB knowledge, manage private memory centrally, and expose the same contracts in ORC Chat and Knowledge Workspace.

**Architecture:** Add corpus adapters and scoped services over existing Knowledge stores. Share read-only retrieval at explicit agent decision boundaries; preserve existing graph execution, Setup and equipment ownership. Live GUI and Workspace consume the same server receipts.

**Tech Stack:** Existing Python/FastAPI, Markdown/JSON, registered model backends, static JavaScript/CSS, pytest and Node/browser verification.

**Spec:** `docs/superpowers/specs/2026-09-12-ax4lab-wiki-memory-orchestrator-design.md`

## Execution Checkpoint — 2026-09-13

Core implementation and scoped regressions are verified in the working tree:
162 affected Python tests, 71 original loop/admission tests, 38 DOM-boundary tests, and registered
API/vLLM response checks. Checkboxes below track performed work, not full-design
acceptance. Remaining: unified legacy adapters, the full per-owner semantic-use
and applicability matrix, broader filters/summary details, and rendered browser
verification. Default private access still requires trusted server integration.
No operating service restart, device action, commit, tag or push was performed.
See [current verification and limits](../../knowledge/wiki_memory.md).

## Global Constraints

- Work in the existing checkout as requested by the user; preserve pre-existing chat expansion changes and untracked output/.
- No actual device commands, operational run start, model-server startup, new fallback, commit, tag or push.
- Default corpus is ax4lab_wiki. Private identity comes from trusted server context, not request/model arguments. Unknown identity means Wiki-only.
- Existing Source Library, Markdown v1, ontology, execution memory, Setup and graph contracts remain usable.
- No private data in public Wiki, URL, browser storage, public test artifacts or committed files. Use synthetic test principals/content only.
- API and local validation use already registered backends; never start Ollama or alternate model services.
- Reports distinguish implemented, unit-tested, browser-tested, model-tested, and device-tested; device-tested must remain false.
- Public product docs/Wiki/UI English; design discussion and this spec may be Korean.

## Task 1: Knowledge service, Wiki seed, private memory and Workspace API

**Files:** Create `knowledge/wiki.py`, `knowledge/private_memory.py`, `knowledge/context_service.py`, `knowledge/delivery.py`, `knowledge/workspace_api.py`, `docs/knowledge/wiki/` pages and focused `tests/unit/test_knowledge_workspace_services.py`, `tests/integration/test_knowledge_workspace_v2_api.py`. Modify app registration in `app/main.py` only at the existing Knowledge installation block. No agent/UI edits in this task.

**Interfaces:** Define `KnowledgeContextService(project_root, data_root=None)` as the common facade. It exposes wiki, memory and delivery components. Use explicit immutable `KnowledgePrincipal` (subject_id, allowed project/session/run scopes, local/remote model consent) at service methods; absent principal is public-only. Publish exact callable methods and response envelopes in the task report before consumer tasks. Routes must match spec §14.3. Use installation dependency injection for principal resolution; production default deny-private until a trusted server-configured local profile is present, never a user-selectable HTTP identity. Do not expose private memory through legacy routes.

- [x] Write failing service tests for Wiki cold start/Korean queries; principal A/B isolation; unknown scope rejection; memory candidate/confirm/edit/expire/forget; repeat commands and revision conflicts; deleted-source reingestion protection; delivery distinction. Example behavior:

```python
def test_public_reader_cannot_read_private_memory(service, alice):
    receipt = service.memory.command(alice, action="propose", payload={
        "kind": "preference", "content": "Use concise explanations", "source_refs": ["synthetic:one"],
        "scope": {"kind": "user"}}, idempotency_key="proposal-1")
    assert service.memory.read(None, receipt["record_id"]) is None
```

Adapt exact constructor/method tests to the final single documented interface, without weakening behavior.
- [x] Run `.venv/bin/python -m pytest tests/unit/test_knowledge_workspace_services.py -q --tb=short`; record the expected RED.
- [ ] Implement small corpus adapters, atomic/locked private revisions, content-free receipts and bounded query/read. Wiki source links/hash freshness must be real checked sources, not fabricated verification. Private deletion removes content from all private revisions/command receipts/index projections and suppresses same-source auto reingestion. Avoid secrets in errors. Prevent symlink/path escape and cross-scope cursor/read leaks.
- [x] Write route tests using an injected synthetic principal, temp data roots and `TestClient`; confirm no-store and no model/scan/device effect on reads. API receives only scope narrowing, never subject identity. Explicit administrative endpoints use authorization and origin checks for cookie/local profile based mutations.
- [x] Run new tests plus `tests/integration/test_markdown_knowledge_api.py` and `tests/unit/test_knowledge_source_library.py` if present; report actual commands/results, not guessed files.
- [x] Self-review and write report in this plan's ignored SDD directory; no commit. Record concrete service interfaces for Tasks 2–4.

## Task 2: Agent knowledge delivery and read-only ORC answers

**Files:** `agents/base_agent.py`, existing `agents/*decision*.py`, selected `agents/*_agent.py` decision call sites, `app/bootstrap.py`, `app/controller.py`, existing prompt registry; create a focused agent context adapter if needed and tests `tests/unit/test_agent_knowledge_delivery.py`, `tests/integration/test_orchestrator_knowledge_chat.py`.

**Interfaces:** Consume Task 1 facade and principal. All active main graph agent bindings receive Wiki at meaningful existing LLM decision boundaries. Retrieval is not a new LLM stage and cannot change tool contracts. Preserve original prompts/schema; append a bounded reference-only pack, record actual delivered refs, validate cited refs in returned output before recording used. Old BO source/Design summary fields adapt through one path. No automatic user memory sent to remote model without explicit server consent.

- [x] Write RED tests that invoke actual decision entry points with controlled transport and inspect outgoing prompts/returned receipts, not only registration. At least one public relevant and one no-match case per active consumer; state/mode/tool ownership unchanged.
- [x] Implement explicit injection using shared helper and frozen per-call context. No mutable global agent/principal state, no every-complete blanket injection. Repeated tool turns reuse context; workflow internals and deterministic Guardian checks unchanged.
- [x] Implement ORC persona and grounded question handling in the existing question intake branch. Capture scope/revision before awaits; do not enter Setup/start path for questions. Current-state answers use existing owner readback; unavailable is unknown. Memory commands route to Task 1 service with explicit semantic intent/confirmation; confirmation never authorizes execution.
- [x] Run focused tests and existing setup admission/orchestrator decision tests. Example invariant:

```python
before = controller._planning_intake_scope()
result = await controller.planning_message(message="What does the Design Agent do?", session_id=session_id)
assert result["ok"]
assert controller._planning_intake_scope() == before
```

Check existing method signatures when implementing the real integration fixture; capture no-device counters and exclude transcript append from configuration invariants.
- [x] Write report, exact context envelope and frontend response linkage, then independent scoped review.

## Task 3: Knowledge Workspace and Live cards

**Files:** `web/templates/knowledge.html`, `web/static/knowledge.js`, `web/static/knowledge.css`, existing `planning.html/js`, optional focused `knowledge_workspace.js` / `knowledge_live.js` modules, existing/new UI tests.

**Interfaces:** Consume Task 1 API and Task 2 response/receipt. Five tabs: Wiki, Memory, Source Library, Agent Delivery, Ontology. Preserve existing operational patterns/Evolution and source controls; compatibility-map old tab anchors. Four Live Knowledge cards and one ORC Knowledge & Memory card, Chat source/memory actions per spec §12. Reuse existing event surface with bounded revision resync fallback, not click-only updates.

- [x] Write failing DOM/API boundary tests for tabs, empty/error states, permission denial, candidate confirm/forget, delivery pending vs used, preserved legacy panels. Assert rendered behavior using synthetic responses.
- [x] Implement UI in existing styling and panels. No cache of private text or context HTML; protect against unsafe Markdown and external image fetches. Scope switch clears previous detail; stale responses cannot replace a current selection. Do not activate scans or agents from page load.
- [x] Verify Node syntax and focused tests, then browser if the Browser integration is available. If unavailable, report the limitation; never claim rendered verification from static tests.
- [x] Keep prior three-bubble chat changes intact, update cache versions, report tests and any UI limits.

## Task 4: Publication boundary and documentation

**Files:** `.gitignore`, new `scripts/verify_knowledge_publication.py`, existing CI validation workflow if appropriate, synthetic tests, agent docs/index/matrix, Live GUI and Knowledge docs, spec status.

**Interfaces:** Validator inspects staged paths/content; private roots denied even force-added, public evidence requires explicit allowlist. Checks do not echo sensitive matching content. CI can detect but cannot undo a prior push; docs say so. Existing tracked-file/history audit is report-only, no history rewrite.

- [x] Write RED tests in an isolated temporary Git repository: forced private path blocked, synthetic credential in public MD blocked, safe Wiki accepted.
- [x] Implement validator and ignore missing private roots/inbox originals without deleting tracked artifacts. Document exact pre-commit invocation and CI boundary.
- [x] Update current agent docs only for actually implemented behavior; Wiki roots, context consumption, privacy scope and validation status must match code. Link new docs from existing indexes; no private source examples.
- [x] Run validator tests, doc/link checks and git diff --check. Record pre-existing unrelated failures separately.

## Task 5: Cross-provider and non-actuating integrated verification

**Files:** Create `scripts/verify_knowledge_workspace.py` and synthetic integration fixtures as needed; evidence under ignored `runs/validation-*` only. Public evidence note contains sanitized aggregate, never prompts containing user material.

- [x] Verify current registered backend availability read-only. Do not change active services or trigger real run startup.
- [ ] Run synthetic relevant/irrelevant/unknown/scope-conflict cases via registered API and local model; inspect actual prompt packets and output references for every active agent decision adapter. A missing provider is explicitly incomplete, not silently substituted.
- [x] Exercise question → Wiki answer, memory candidate → confirm → lookup → forget, and Live/Workspace same revision views; assert no Setup changes for questions and no device requests.
- [x] Run existing virtual-route regression and all new scoped tests; retain failed case evidence and classify known baseline failures.
- [ ] Independent whole-change review, fix scoped findings, rerun affected tests. Update spec/plan with exact completion status; no commit/push without user request.
