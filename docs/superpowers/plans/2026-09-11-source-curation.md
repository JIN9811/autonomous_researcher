---
doc_type: plan
subtype: implementation
status: active
authority: execution
execution_status: completed
audience: [developer, researcher, maintainer]
scope: [knowledge, source_ingestion, curation, scoped_rag]
summary: Implement the approved general source-curation replacement and verify both registered model paths without device execution.
governing_design: docs/superpowers/specs/2026-09-11-source-curation-design.md
related_docs:
  - docs/agents/knowledge_agent.md
supersedes: []
---

# Source Curation Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Follow TDD and track task results. No commits or pushes during implementation.

**Goal:** Replace active manual-specific ingestion with source-preserving Markdown conversion, LLM curation, organization, and agent-consumable scoped retrieval.

**Architecture:** Reuse the current source folder and registered Knowledge model route. A small source library owns content-addressed artifacts, a background service runs the bounded curation loop, and existing consumers obtain read-only cited context.

**Tech Stack:** Existing Python/FastAPI, local extraction utilities, JSON/Markdown, existing model backends and lease, plain JavaScript/HTML/CSS, existing Playwright.

**Spec:** `docs/superpowers/specs/2026-09-11-source-curation-design.md`

## Global Constraints

- Work in `/home/jin/autonomous_researcher` on the existing feature branch; do not switch the running checkout or merge unrelated branches.
- No device/solver actions, production-server restart, model-server startup, or original-data deletion. The user's subsequent approval permits a final scoped commit, new tag and push after verification and cleanup.
- Use only ATR's registered API and local vLLM routes. No alternative model server, silent fallback, or synthetic success for model-required paths.
- Preserve numerical values, execution order, bridges, loop Markdown memory, and ontology definitions.
- New UI and published prose are English. Describe generic source material; do not enumerate subject categories or fixed equipment in documentation.
- Verification uses isolated temporary roots; the user's subsequent retention instruction preserves evidence in an external validation-only archive, never in the ATR repository or production knowledge corpus.
- Keep original inputs unchanged, detect partially copied/changed files, deduplicate successful content, preserve prior revisions, and reject out-of-scope paths/filters.

## Verification Receipt

Implementation and review completed on 2026-09-11. Final scoped regression:
278 passed, 12 existing warnings, 29.25 s. Registered GPT API and local vLLM
Gemma each passed eight valid source publications, one expected unreadable-input
rejection and three Knowledge/BO plus Equipment consumer checks. The original
matrix completed in 1301.396 s; its aggregate report is retained externally.
Desktop/mobile workspace checks passed. No hardware, solver, production restart
or model-server startup was used. The final archive-option tests cover success,
failure and rejection of repository-internal destinations. Intermediate outputs
from the earlier matrix were already cleaned; this limitation is recorded in the
external archive and agent reference. Publication is authorized on the existing
feature branch with the new `Knowledge-Agent-Source-Curation` tag.
- Agent tools remain read-only outside the Knowledge source writer; references are evidence, not execution authority.
- Split paginated inputs into page files, process pages individually, then emit one consolidated curated Markdown document per original input. Temporary page findings are not separate published outputs.

### Task 1: Source library, extraction, and bounded model curation

**Files:** Create `knowledge/source_library.py`, `knowledge/source_extraction.py`, `agents/source_curation.py`; tests `tests/unit/test_source_library.py`, `tests/unit/test_source_curation.py`.

**Interfaces:**

```python
class SourceLibrary:
    def __init__(self, root: Path, inbox: Path): ...
    def scan(self) -> dict: ...  # sources plus pending_ids; stable file detection
    def extract(self, source_id: str) -> dict: ...  # complete Markdown and stable blocks
    def inspect(self, source_id: str, *, offset: int = 0, limit: int = 8) -> dict: ...
    def publish(self, source_id: str, notes: list[dict], *, model: dict, trace: list) -> dict: ...
    def mark(self, source_id: str, status: str, *, error: str = '') -> dict: ...
    def status(self) -> dict: ...
    def search(self, query: str, *, scope: dict | None = None, top_k: int = 6) -> dict: ...
    def read(self, record_id: str, *, scope: dict | None = None) -> dict: ...

async def curate_source(library, source_id: str, ctx, *, timeout_s: float = 300) -> dict: ...
```

`scan()` returns `{sources: [...], pending_ids: [...], errors: [...]}`. The same stable
content is discovered once; a second unchanged scan admits it (test via real repeated
scans, no sleeps). IDs are `source-<sha256>`, not run IDs. Source dicts include
source_id, sha256, paths, status, format, and current. `extract` preserves complete
source text as Markdown and yields blocks `{block_id, text, page}`; `inspect`
returns paginated blocks, total_blocks and next_offset. Notes contain title, body,
category (safe slug), ontology_type (existing registry), tags, applicability, and
source_block_ids. `search` returns `{hits, scope}`, hits include record_id,
source_id, title, excerpt, category, source_refs and citations. `read` returns the
full note. Scope permits source_id/category/ontology_type/status/tags/applicability;
unknown keys fail, empty lists match nothing, default status is ready/current.

- [x] RED: test real temporary file discovery, full conversion, table/end-marker retention, duplicate aliases, changed source versions, deleted input eligibility, symlink escape, bad input, scoped reads, and atomic publication. Use literal expected content and actual files, not mocked storage.

```python
def test_published_content_keeps_the_last_section(tmp_path):
    inbox = tmp_path / 'inbox'; inbox.mkdir()
    (inbox / 'sample.md').write_text('# Start\nThreshold: 17.5\n\n# End\nTAIL-EVIDENCE')
    library = SourceLibrary(tmp_path / 'library', inbox)
    library.scan(); discovered = library.scan()
    source_id = discovered['pending_ids'][0]
    extracted = library.extract(source_id)
    assert 'TAIL-EVIDENCE' in extracted['markdown']
    assert 'Threshold: 17.5' in extracted['markdown']
```

- [x] GREEN: reuse existing PDF extraction where appropriate; implement textual/structured extraction using available local libraries/stdlib, preserving table/section text and page provenance. Explicitly fail unreadable inputs; no fabricated OCR. Bound resource use without silently truncating successful output. Use atomic manifests and immutable revisions; publish only after validating notes, source block IDs, and source hash stability.
- [x] RED/GREEN curation: a fake `ctx.complete` exercises actual inspect/search/publish dispatch. Model must inspect every block before publication, cannot cite uninspected/unknown blocks, publish empty notes, fabricate ontology classes, escape output root, or mark mock responses as real. Paginated long input must reach the final block. Prompt preserves quantities, qualifications, conflicting conditions, and source-vs-derived distinction. Curation calls `knowledge_query` with low-priority existing lease; no fake run context.
- [x] Latest approved long-source contract: preserve physical page boundaries/files; read page-by-page (subdivide unusually long pages), stage grounded findings, and consolidate to one final Markdown output. Keep prompt size bounded independently of source length using hierarchical consolidation, preserve late-page facts and page citations, and keep intermediate findings invisible to normal retrieval. Apply timeouts per model call, not one short-source deadline to the entire document. Test cancellation during atomic publication and retain visible evidence during schema correction.
- [x] Verify `.venv/bin/python -m pytest tests/unit/test_source_library.py tests/unit/test_source_curation.py -q`. Self-review and report exact RED/GREEN evidence and interfaces; do not commit.

### Task 2: Background intake, APIs, and actual agent consumers

**Files:** Create `knowledge/source_runtime.py`, `knowledge/source_api.py`, `mcp_tools/source_tools.py`; modify `app/main.py`, `app/bootstrap.py`, `agents/knowledge_decision.py`, `agents/equipment_agent.py`, `agents/equipment_workflow.py`; tests `tests/unit/test_source_runtime.py`, `tests/integration/test_source_library_api.py`, `tests/unit/test_source_consumers.py` and affected old tests only.

**Interfaces:**

```python
class SourceIngestionService:
    def __init__(self, library, context_factory, *, poll_interval_s=5.0): ...
    async def start(self): ...
    async def shutdown(self): ...
    async def tick(self): ...
    def configure(self, *, enabled: bool) -> dict: ...
    def status(self) -> dict: ...
    def retry(self, source_id: str) -> dict: ...

def install_source_routes(app, *, service_factory): ...
def register_source_tools(tools, library_factory): ...
```

GET `/api/knowledge/sources/status`, POST `/settings` `{enabled: bool}`, POST
`/scan`, POST `/retry` `{source_id}`, POST `/query` `{query,scope,top_k}`, POST
`/read` `{record_id,scope}`. Scan/retry schedules work, never awaits model inference
in the HTTP request. Query/detail return only published scoped data. Worker
settings persist; enabling requires operator choice. Startup may restore enabled
watching but never boot a model. Failed/model-unavailable work remains visible and
retryable without a hot loop. Observe file stability before processing. Existing
model lease protects active workflow priority; shutdown/cancellation cannot publish
partial data. Requests cannot supply arbitrary server file paths.

- [x] RED/GREEN: tmp-path worker tests for enablement, discover/process, unavailable model, idempotent tick, shutdown, and scope errors; API tests without production lifespan or equipment registry. Hard tripwires prohibit external execution.

```python
def test_query_scope_rejects_unknown_filter(client):
    response = client.post('/api/knowledge/sources/query', json={
        'query': 'threshold', 'scope': {'unknown_filter': 'x'}})
    assert response.status_code == 422
```

- [x] Register read-only `knowledge.sources.search` and `knowledge.sources.read` tools via existing ToolRegistry and expose the library resource. Add `sources` to Knowledge's existing search/read corpus and propagate full selected knowledge/citations into the unchanged BO context. Do not force source records into run-specific identity/scope filters; source scope is explicit in knowledge settings.
- [x] Equipment workflow's existing bounded model context gains optional relevant source evidence through the same shared read-only retrieval contract; empty library preserves existing choices. Remove unconditional legacy manual evidence attachment from program planning, standalone recovery, and annotation creation; return an explicit retired compatibility context where an old contract must remain. Existing manual-specific active API endpoints retire or explicitly point to replacement; old files remain untouched.
- [x] Verify actual Knowledge/BO source handoff and Equipment decision evidence, not merely API retrieval. Check source citation and wrong-scope exclusion, unchanged numerical/command payloads, and absence of old manual retrieval calls. Preserve old non-actuating closed-loop regression.
- [x] Report targeted tests and independent review scope. No commit.

### Task 3: Source Library workspace

**Files:** Modify `web/templates/knowledge.html`, `web/static/knowledge.js`, minimal `web/static/knowledge.css`; update `tests/ui/knowledge_workspace_browser_audit.py`, `tests/integration/test_knowledge_workspace.py`.

- [x] RED: extend the isolated browser fixture with real SourceLibrary/service routes. Check existing Markdown/Memory/Ontology tabs, new Source Library status, explicit enable toggle, scan/retry, progress, query filters, selected note and original source provenance.
- [x] GREEN: replace the manual-specific tab in place; no new dashboard or navigation redesign. Keep stable route/hash compatibility if cheap. English generic copy only. Show empty, pending, failed, ready, and no-match states. Poll job state independent of selected record; stop unnecessary polls when hidden. No heavy source bodies in list responses.
- [x] Verify desktop/mobile layout, console/network health and meaningful interactions using existing Playwright (Browser tools are unavailable). No production-server startup. Report screenshots outside source tree; remove temporary fixture artifacts after review. No commit.

### Task 4: Registered-provider verification and focused documentation

**Files:** Create `scripts/verify_source_curation.py`, test its cleanup/failure/external-retention behavior in `tests/unit/test_source_verification.py`; update `docs/agents/knowledge_agent.md`, the existing source operations guide at `docs/knowledge/manual_rag_knowledge.ko.md`, the existing 3 DOT/SVG figures only where needed, this plan/spec; add manifest entries as needed. Store validation reports and raw artifacts outside the repository.

**Provider compatibility:** Existing `knowledge_query` output caps in `backends/openai_client.py` and `backends/vllm_client.py` allow structured Markdown publication. Keep registered endpoints, model-server context settings, and model selection unchanged; bound input batches within the existing context budget.

- [x] RED/GREEN: verification driver uses `TemporaryDirectory` and actual registered backend construction from `scripts/verify_knowledge_decisions.py`. No API configuration changes, credentials in logs, alternative server startup, fallback, or copied production memory. CLI requires `--execute`; cleanup executes on success and failure. Sanitize reports outside the temporary input/library root; no raw source text, generated notes, fixture identity names, or private paths in checked-in evidence.
- [x] Test varied structured/unstructured, long, multilingual, duplicate, revised, contradictory, and unreadable inputs. Include a real openly accessible public-source fixture acquired only into the temporary input root. Ground expectations independently in original evidence, including a final-section fact, numerical value/unit, table content, and appropriate uncertainty.
- [x] Run curation and actual source-consuming Knowledge/BO and Equipment decision paths using registered GPT API and local Gemma, not independent chatbot prompts. Check source reading, MD usefulness, scoped citation reuse, insufficient/wrong-scope handling, and preserved execution/numerical contracts. Record per-case backend/model/duration/tools/expectation results and failures honestly; tune generic prompt only if needed and rerun both providers.
- [x] Run combined source + affected Knowledge/Equipment/API/browser + non-actuating loop regression; verify parallel intake does not await curation inside an experiment stage. Review exact diff; run documentation/link checks. Do not claim full repository or physical validation.
- [x] Remove temporary working roots after checks; preserve requested validation evidence separately outside the repository and operational stores. The original full-provider run retained only its aggregate report because its intermediate workspace had already been cleaned before the retention instruction; do not present regenerated fixtures as that run's original outputs. Update focused English agent/operations docs with generic feature/status/tool/storage/verification contracts and measured outcomes. No bulk translation of unrelated docs.
- [x] After final review and verification, commit the scoped implementation/docs, create a new Knowledge Agent source-curation tag and push the existing branch plus that tag. Preserve old tags and do not force-push or merge unrelated work.
