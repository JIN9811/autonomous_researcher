# Manual RAG Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a source-separated UTM manual GraphRAG module and connect it to the Lab Equipment UTM-profile LLM without bypassing existing execution gates.

**Architecture:** Parse registered PDF manuals into page-aware hierarchical chunks, project typed manual entities into the existing Knowledge graph backend, and assemble bounded `manual_context.v1` packages. Inject those packages into UTM Skill annotation, protocol guidance, and recovery prompts while keeping Skill/bridge/Guardian validation authoritative.

**Tech Stack:** Python 3.12, PyMuPDF or `pdftotext`, PyYAML, existing Knowledge JSON/Neo4j backends, FastAPI, vanilla JavaScript, pytest.

## Global Constraints

- `equipment_type=utm` is the only mandatory equipment retrieval boundary.
- Product and version metadata must not become hard query filters.
- Manual retrieval is read-only and cannot dispatch commands.
- No web fallback is allowed for manual evidence.
- Every result retains source hash, page, section, and chunk citation.
- Existing Skill, bridge, Guardian, and operator gates remain unchanged.

---

### Task 1: Source Registry, Extraction, and Hierarchical Chunks

**Files:**
- Create: `knowledge/manuals/__init__.py`
- Create: `knowledge/manuals/models.py`
- Create: `knowledge/manuals/ingest.py`
- Create: `docs/knowledge/manuals/registry.yaml`
- Move: `docs/knowledge/Indicator Manual.pdf` to `docs/knowledge/manuals/sources/Indicator Manual.pdf`
- Move: `docs/knowledge/Software Manual.pdf` to `docs/knowledge/manuals/sources/Software Manual.pdf`
- Test: `tests/unit/test_manual_knowledge_ingest.py`

**Interfaces:**
- Produces: `ManualIngestor.ingest_registry(registry_path: Path, output_root: Path) -> dict[str, Any]`
- Produces: `ManualChunk.as_dict() -> dict[str, Any]`

- [ ] Write tests for page provenance, stable IDs, source hashes, section paths, and atomic corpus replacement.
- [ ] Run the tests and confirm failure because `knowledge.manuals` does not exist.
- [ ] Implement registry loading and page-aware extraction without image copying.
- [ ] Run ingestion tests and confirm pass.

### Task 2: Manual Ontology and Graph Projection

**Files:**
- Create: `knowledge/ontology/manual_equipment.v1.yaml`
- Create: `knowledge/manuals/graph_projection.py`
- Modify: `knowledge/ontology/registry.py`
- Test: `tests/unit/test_manual_knowledge_graph.py`

**Interfaces:**
- Consumes: corpus from Task 1.
- Produces: `project_manual_graph(corpus: dict[str, Any]) -> tuple[list[dict], list[dict]]`

- [ ] Write tests for typed nodes, allowed relations, UTM hierarchy, provenance, and invalid relation rejection.
- [ ] Run tests and confirm missing projection failure.
- [ ] Implement ontology extension loading and deterministic graph projection.
- [ ] Run ontology and graph backend tests.

### Task 3: Bounded Manual GraphRAG Retrieval

**Files:**
- Create: `knowledge/manuals/retrieval.py`
- Create: `knowledge/manuals/service.py`
- Modify: `knowledge/graph_query_planner.py`
- Modify: `knowledge/graph_retrieval.py`
- Test: `tests/unit/test_manual_knowledge_retrieval.py`

**Interfaces:**
- Produces: `ManualKnowledgeService.query(payload: dict[str, Any]) -> dict[str, Any]`
- Produces schema: `manual_context.v1`

- [ ] Write tests proving UTM filtering, product/version soft ranking, bounded top-k, citations, and no web fallback.
- [ ] Run tests and confirm missing service failure.
- [ ] Implement lexical/embedding ranking plus bounded graph expansion using existing backends.
- [ ] Run retrieval, planner, and backend tests.

### Task 4: Ingestion and Query API

**Files:**
- Modify: `app/main.py`
- Test: `tests/integration/test_manual_knowledge_api.py`

**Interfaces:**
- Produces: `GET /api/knowledge/manuals/status`
- Produces: `POST /api/knowledge/manuals/ingest`
- Produces: `POST /api/knowledge/manuals/query`
- Produces: `GET /api/knowledge/manuals/graph`

- [ ] Write API tests for status, ingestion, query validation, and bounded graph responses.
- [ ] Run tests and confirm 404 failures.
- [ ] Add API models and handlers backed by one cached service instance.
- [ ] Run API tests.

### Task 5: UTM Profile LLM Context Injection

**Files:**
- Modify: `app/main.py`
- Modify: `agents/equipment_agent.py`
- Test: `tests/unit/test_equipment_agent.py`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: `ManualKnowledgeService.query(...)`.
- Adds: `manual_context`, `manual_citations`, and `manual_context_hash` to model metadata and audit artifacts.

- [ ] Write tests proving Skill annotation, protocol guidance, and recovery receive UTM manual context.
- [ ] Write tests proving command payloads and gates are unchanged.
- [ ] Run tests and confirm missing context failures.
- [ ] Inject bounded context into prompts and persist citation metadata.
- [ ] Run Equipment and integration tests.

### Task 6: Manual RAG Knowledge Workspace Section

**Files:**
- Modify: `web/templates/knowledge.html`
- Modify: `web/static/knowledge.js`
- Modify: `web/static/knowledge.css`
- Test: `tests/integration/test_knowledge_ontology_api.py`
- Test: `tests/ui/knowledge_workspace_browser_audit.py`

**Interfaces:**
- Consumes: Task 4 APIs.
- Produces: source status, ingestion receipt, graph summary, query result, and citation views.

- [ ] Write markup/API contract tests for the dedicated section.
- [ ] Run tests and confirm missing controls.
- [ ] Implement compact Manual RAG cards and citation rendering without rebuilding existing graph canvases.
- [ ] Run integration and browser audit tests.

### Task 7: Documentation and End-to-End Verification

**Files:**
- Modify: `docs/knowledge/knowledge_graph_operations.ko.md`
- Modify: `docs/agents/knowledge_agent.md`
- Modify: `docs/agents/equipment_agent.md`
- Modify: `docs/document_manifest.yaml`
- Test: `tests/unit/test_documentation_validation.py`

**Interfaces:**
- Documents the source registry, ingestion/query operations, UTM LLM use, provenance, and safety boundaries.

- [ ] Update operational documentation and manifest.
- [ ] Run manual ingestion against both supplied PDFs.
- [ ] Query Skill authoring, procedure, warning, and recovery examples and verify page citations.
- [ ] Run focused Knowledge/Equipment/API/UI tests and documentation validation.
- [ ] Run `git diff --check` and inspect generated artifacts for secrets or copied manual images.

