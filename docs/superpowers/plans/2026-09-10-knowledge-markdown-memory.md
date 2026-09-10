---
doc_type: plan
subtype: implementation
status: active
authority: execution
execution_status: completed
audience: [developer, researcher, maintainer]
scope: [knowledge, ontology, markdown_memory, scoped_rag]
summary: Knowledge-only restructuring, preserving existing scientific and device paths.
governing_design: docs/superpowers/specs/2026-09-10-knowledge-markdown-memory-design.md
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/knowledge/markdown_memory_operations.ko.md
supersedes: []
---

# Knowledge Markdown Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. No commits or pushes.

**Goal:** Replace active Knowledge graph dependencies with ontology-guided Markdown knowledge and scoped RAG while preserving the existing closed loop.

**Architecture:** Small Markdown records retain typed frontmatter and source references. An agent-local LLM tool loop selects classification/retrieval/context, while deterministic archives and existing scientific contracts remain authoritative. Graph-only runtime/UI paths are retired without deleting historical data.

**Tech Stack:** Existing Python/Pydantic/PyYAML/FastAPI, existing RAG primitives, plain JavaScript/HTML/CSS, Graphviz; no new database.

**Spec:** `docs/superpowers/specs/2026-09-10-knowledge-markdown-memory-design.md`

## Global Constraints

- No physical actuation, solver execution, model-server startup, commit, tag, push, or deletion of historical data.
- Preserve executable graph, bridges, Analysis/BO numerical values and coordinates, raw archives, ontology, manual citations, memory/pattern/Evolution contracts.
- Retire Knowledge graph operational wiring only. Legacy offline graph implementation may remain unused.
- New UI text is English; design/spec narrative is Korean.
- All test writes use temporary roots. Real providers use registered API/vLLM routes with no fallback and synthetic/copied evidence only.
- Work in the existing checkout on `feat/knowledge-markdown-memory`; prior user requests require preserving the current project path.

### Task 1: Markdown store and scoped retrieval

**Files:** Create `knowledge/markdown_memory.py`, optional `knowledge/markdown_schemas.py`, `tests/unit/test_markdown_knowledge.py`.

**Interfaces:** `MarkdownKnowledgeStore(root: Path, ontology: OntologyRegistry)`;
`write_note(note: dict) -> dict` returns ok/status/record_id/revision/path;
`search(query: str, *, scope: dict | None = None, top_k: int = 6) -> dict` returns hits/scope;
`read_note(record_id: str, *, scope: dict | None = None) -> dict`; `status() -> dict`.
Note input requires run_id/cycle_id/agent_id/event_id/ontology_type/title/body/source_refs;
optional tags/applicability/evidence_kind/fidelity/status; defaults derived/unknown/valid.
Scope accepts exact string or list values for run_id/cycle_id/agent_id/ontology_type/fidelity/status,
tags and applicability mapping (exact conjunction). None uses valid records; explicit empty lists match none.
Allow an operator lifecycle update API through `set_status(record_id, status, *, reason, superseded_by='')`.

- [x] RED: write real tmp_path tests for one record roundtrip, unchanged retry, same event changed content revision, same failure different cycle separation, invalid ontology rejection, status visibility, exact scope/no-match/unknown filter, scoped read, Korean/English search, incremental cache refresh, no path escape. Run `.venv/bin/python -m pytest tests/unit/test_markdown_knowledge.py -q`.
- [x] GREEN: implement atomic frontmatter/body files, stable event-derived identity, per-record locking and append-only revisions; latest record projection/index is rebuildable. Validate finite bounded metadata and known ontology. Derive ID/hash from normalized identity/content, not timestamps.
- [x] Verify real files and new store instances rehydrate the same records. Record RED/GREEN commands and output in task report. No commit.

Example acceptance fixture:
```python
note = dict(run_id='run-a', cycle_id='loop-000001', agent_id='equipment', event_id='event-a',
    ontology_type='Observation', title='Export completed', body='CSV export completed.',
    source_refs=['runs/run-a/result.json'], evidence_kind='observed', fidelity='virtual')
first = store.write_note(note)
assert store.write_note(note)['status'] == 'unchanged'
assert store.search('export', scope={'run_id': 'run-b'})['hits'] == []
```

### Task 2: Graph-free operational service and manual preservation

**Files:** Modify `knowledge/manuals/service.py`, `knowledge/service.py`, `knowledge/graph_backend.py` only if required for an explicit retired factory; `app/main.py` Knowledge helpers/startup/routes; add `knowledge/markdown_runtime.py`; tests `tests/unit/test_manual_knowledge_retrieval.py`, new `tests/integration/test_markdown_knowledge_api.py`.

**Interfaces:** runtime `store_for(ctx=None, *, project_root=None)` returns store using temporary artifact root when provided. FastAPI GET `/api/knowledge/status`, POST `/api/knowledge/markdown/query`, GET `/api/knowledge/markdown/{record_id}`, POST `/api/knowledge/markdown/{record_id}/status`. Query body `{query, scope, top_k}`; response retains explicit scope and citations. Graph-only endpoints return 410 with retired status before any graph factory.

- [x] RED: graph backend methods/factories tripwires prove manual query and graph-free API operate without graph access; existing citations match fixtures; preserved memory/ontology/evolution APIs remain successful; query filters and invalid payloads return clear errors.
- [x] GREEN: decouple manual corpus ingest/readiness/query from graph projections, retain manual_context.v1 citation and evidence contract. Remove graph worker startup callbacks. Keep audit records/local JSONL; no Neo4j receipts fabricated.
- [x] Implement bounded explicit archive intake/reindex API as a background task using stored archive JSON; no device replay, full scan at startup, or LLM calls. Return job state and per-file errors. No arbitrary absolute source paths.
- [x] Verify `.venv/bin/python -m pytest tests/unit/test_manual_knowledge_retrieval.py tests/integration/test_markdown_knowledge_api.py tests/integration/test_knowledge_api.py -q`.

### Task 3: Knowledge LLM tool loop and archive intake

**Files:** Create `agents/knowledge_decision.py`; modify `agents/knowledge_agent.py`, `backends/prompt_registry.py`, `graphs/modules/knowledge/module.yaml`, `utils/agent_artifact_archive.py`, `knowledge/markdown_runtime.py`, scoped consumers `agents/bo_agent.py`; new `tests/unit/test_knowledge_decision.py`, archive tests and Knowledge tests.

**Interfaces:** `run_knowledge_decision(state, ctx, *, store, evidence, scope, settings=None) -> dict`; actions inspect_evidence/search_knowledge/read_knowledge/write_knowledge_note/publish_context, one JSON envelope `{tool, arguments}`. Trace includes selected refs and actual observations. Store runtime/archive helpers must never change original AgentResult or propagate archive failures into device outcomes.

- [x] RED: fake model selects inspection, search, detail, note write and publication; test different evidence leads to no-context or qualified context; unknown refs/wrong identity/scope expansion rejected; duplicate writes idempotent; missing model output is not successful LLM decision.
- [x] GREEN: real `ctx.complete('knowledge_query', ...)` follows registered provider; frozen source IDs and default scope from current state; preserve objective/uncertainty/metrics. Per-call timeout configurable with sufficiently long local allowance, no fixed 45s test limit. Normal path model required; explicit offline test dispatcher is labeled.
- [x] Archive terminal success/failure/cancelled records after existing result persistence using immutable execution identity. Failure before Knowledge still yields an observed MD; no model/device call. Keep error classification separate from operator cancellation.
- [x] Extend existing knowledge_context.v1/report with selected knowledge, scope, citations, decision and Markdown receipts; retain existing compact summary and JSONL output keys and BO numerical path.
- [x] Verify Knowledge/archive tests plus existing non-actuating two-cycle integration with busy FEM boundary.

### Task 4: Workspace and documentation

**Files:** `web/templates/knowledge.html`, `web/static/knowledge.js`, `web/static/knowledge.css`, Knowledge status portion only of `web/static/app.js`; update `tests/integration/test_knowledge_workspace.py`, UI fixture; `docs/agents/knowledge_agent.md`, figure DOT/SVGs, knowledge operation/manual guides, agent navigation/matrix where current claims change.

- [x] RED: browser/API fixture checks MD list/detail/scope controls, preserved memory/ontology/manual tabs; no graph fetches or Neo4j status pollution; main dashboard links current Knowledge status.
- [x] GREEN: reuse existing workspace style/components, replace graph tab with Markdown knowledge; retain memory/performance/pattern/evolution/manual evidence display. Minimal CSS; English copy.
- [x] Update Reference Status at a Glance, five-area responsibilities, actual tools/contracts, MD artifact paths, retirement boundary and actual verification; regenerate existing 3 SVGs from DOT. Mark obsolete graph-operation docs retired with links, keep history.
- [x] Verify desktop/mobile fixture, browser console/network behavior, changed-page links/SVGs and focused UI tests.

### Task 5: Provider and closed-loop verification

**Files:** Create `scripts/verify_knowledge_decisions.py`, sanitized `docs/agents/assets/verification/knowledge_decisions_2026-09-10.json`; update plan checkboxes and reference verification.

- [x] Reuse registered backend construction from `scripts/verify_bo_decisions.py`, but use temporary Markdown store with synthetic success/failure/cancelled/conflicting/out-of-scope notes and no device tools.
- [x] Verify API and registered vLLM model each inspect and call meaningful search/write/publish tools. Save durations, selected model/backend, scoped sources, actual outcomes, no startup/actuation flags; do not log secrets.
- [x] Run consolidated targeted Knowledge/manual/API/archive/BO-consumer/closed-loop regression set, review exact diff, then independent task/final review. Preserve uncommitted changes; no commit/push.

## Verified Outcome — 2026-09-10

- Final targeted regression: **210 passed**, 14 existing warnings, 25.79 seconds.
  Includes Markdown/store/decision/archive, manual citations, ontology/typed APIs,
  BO, Evolution, objective compiler, the nonactuating two-cycle busy-FEM boundary,
  and real-browser workspace integration. Full repository tests were not run.
- Registered providers: API `gpt-5.5` and vLLM `gemma4:31b`, each passing
  classified-note, scoped-reuse and insufficient-evidence cases.
  [Sanitized evidence](../../agents/assets/verification/knowledge_decisions_2026-09-10.json).
  Command: `.venv/bin/python scripts/verify_knowledge_decisions.py --execute`.
- Browser: existing Playwright/Chromium, isolated fixture, 1440×1000 and 390×844.
  Scope/detail, stale/no-match/invalid inputs, Memory/Ontology/manual citations,
  explicit intake job and reload passed. No console or retired-graph requests.
  Command: `.venv/bin/python -m pytest tests/integration/test_knowledge_workspace.py -q`.
- Documentation: 10 changed governed documents pass the existing validator;
  three DOT sources regenerate their SVGs. Full manifest retains unrelated,
  pre-existing Windows bridge governance and PLC design-frontmatter errors.
- Independent store, runtime and final UI/API reviews approved after fixes.
- No hardware/solver execution, model-server startup, production-server restart,
  historical-data deletion, commit, tag or push. Existing checkout remains on
  `feat/knowledge-markdown-memory`, HEAD `36fdf1f`. Restart ATR when ready to
  load changed Python routes; no running server was restarted for this work.

### Implementation Decomposition

Routes live in `knowledge/http_api.py` with small wiring in `app/main.py`.
Shared applicability/archive adapters live in `knowledge/markdown_runtime.py`.
Markdown-source metadata is preserved through the existing `knowledge/retrieval.py`
and typed source references. The UI shows lifecycle state and filters; mutation
requires the explicit lifecycle API. History intake reconstructs Markdown and
its incremental index without rerunning any execution. In-progress jobs are not
automatically resumed after a process restart; safe idempotent re-request is
documented in the operations guide.
