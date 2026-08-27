# Manual Knowledge Semantic Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provenance-backed semantic projection and query-focused graph view that makes UTM manual procedures and recovery chains readable without exposing PDF chunk topology by default.

**Architecture:** Keep `manual_graph.json` as the evidence graph and generate a versioned `manual_semantic_graph.json` beside it. Retrieval continues ranking page-aware chunks, then maps those chunks to semantic seed nodes and expands a deterministic two-hop semantic subgraph. The Knowledge workspace renders this query projection with a coordinated evidence list and inspector; Lab Equipment prompt construction continues consuming backward-compatible `manual_context.v1` chunks.

**Tech Stack:** Python 3.12, FastAPI, YAML ontology, JSON atomic persistence, pytest, vanilla JavaScript, ECharts, Selenium/Firefox.

## Global Constraints

- Preserve `equipment_type=utm` as the only hard equipment scope.
- Product and software version values remain non-binding ranking metadata.
- Every displayed semantic assertion requires page-level `SUPPORTED_BY` provenance.
- Manual knowledge cannot create or modify device commands, coordinates, program IDs, credentials, safety gates, or tool payloads.
- `manual_context.v1` ranked chunks and existing Lab Equipment consumers remain backward compatible.
- Default query projection limits are 40 nodes, 60 edges, and two semantic hops.
- `ManualChunk` nodes remain stored but hidden from the default semantic graph.
- Failed semantic rebuilds leave the prior active semantic projection untouched.
- Do not add web retrieval or an implicit graph-backend fallback.

---

## File Structure

- Create `knowledge/manuals/semantic_projection.py`: semantic extraction, normalization, entity resolution, provenance validation, and deterministic query projection.
- Modify `knowledge/manuals/models.py`: typed semantic node and semantic edge records.
- Modify `knowledge/manuals/graph_projection.py`: retain evidence projection and remove duplicated semantic extraction.
- Modify `knowledge/ontology/manual_equipment.v1.yaml`: add `SUPPORTED_BY` and valid semantic-to-evidence domains/ranges.
- Modify `knowledge/manuals/service.py`: atomic semantic index build, metrics, compatible query response, and semantic graph API data.
- Modify `app/main.py`: expose semantic/evidence views without changing equipment execution routes.
- Modify `web/templates/knowledge.html`, `web/static/knowledge.js`, and `web/static/knowledge.css`: evidence, semantic graph, and inspector workspace.
- Add or modify manual graph, retrieval, API, workspace, and Selenium tests.
- Update Knowledge Agent, Equipment Agent, Manual RAG, and document-manifest documentation.

---

### Task 1: Semantic Graph Contracts and Ontology Rules

**Files:**
- Modify: `knowledge/manuals/models.py`
- Modify: `knowledge/ontology/manual_equipment.v1.yaml`
- Create: `tests/unit/test_manual_semantic_projection.py`
- Modify: `tests/unit/test_manual_knowledge_graph.py`

**Interfaces:**
- Consumes: existing manual graph dictionaries.
- Produces: `SemanticNode.as_dict()`, `SemanticEdge.as_dict()`, and ontology relation `SUPPORTED_BY`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_semantic_records_require_page_level_support() -> None:
    node = SemanticNode(
        node_id="manual-semantic:fault:comm-failure",
        kind="Fault",
        label="통신 연결 실패",
        equipment_type="utm",
        confidence=0.92,
        supporting_chunk_ids=("manual-chunk:software:66:1",),
        citations=({"source_id": "software", "page": 66},),
        extraction_method="deterministic",
    )
    assert node.as_dict()["properties"]["citations"][0]["page"] == 66


def test_supported_by_accepts_semantic_to_evidence_edges() -> None:
    report = validate_manual_graph(
        nodes=[
            {"id": "fault:1", "kind": "Fault"},
            {"id": "chunk:1", "kind": "ManualChunk"},
        ],
        edges=[{"id": "edge:1", "source": "fault:1", "target": "chunk:1", "type": "SUPPORTED_BY"}],
    )
    assert report["ok"] is True
```

- [ ] **Step 2: Run tests and confirm missing contracts fail**

Run: `.venv/bin/python -m pytest -q tests/unit/test_manual_semantic_projection.py tests/unit/test_manual_knowledge_graph.py`

Expected: FAIL because semantic records and `SUPPORTED_BY` are undefined.

- [ ] **Step 3: Add frozen semantic records**

```python
@dataclass(frozen=True, slots=True)
class SemanticNode:
    node_id: str
    kind: str
    label: str
    equipment_type: str
    confidence: float
    supporting_chunk_ids: tuple[str, ...]
    citations: tuple[dict[str, Any], ...]
    extraction_method: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "properties": {
                "equipment_type": self.equipment_type,
                "confidence": self.confidence,
                "supporting_chunk_ids": list(self.supporting_chunk_ids),
                "citations": [dict(item) for item in self.citations],
                "extraction_method": self.extraction_method,
                "aliases": list(self.aliases),
                "graph_source": "manual_semantic",
            },
        }
```

Add the corresponding `SemanticEdge` with stable ID, source, target, relation, confidence, supporting chunks, citations, review state, and extraction method. Extend ontology validation so semantic kinds can point to `ManualSection` or `ManualChunk` using `SUPPORTED_BY`.

- [ ] **Step 4: Run contract tests**

Run: `.venv/bin/python -m pytest -q tests/unit/test_manual_semantic_projection.py tests/unit/test_manual_knowledge_graph.py`

Expected: PASS.

- [ ] **Step 5: Commit the contract slice**

```bash
git add knowledge/manuals/models.py knowledge/ontology/manual_equipment.v1.yaml tests/unit/test_manual_semantic_projection.py tests/unit/test_manual_knowledge_graph.py
git commit -m "feat: define manual semantic graph contracts"
```

### Task 2: Provenance-Backed Semantic Extraction and Entity Resolution

**Files:**
- Create: `knowledge/manuals/semantic_projection.py`
- Modify: `knowledge/manuals/graph_projection.py`
- Test: `tests/unit/test_manual_semantic_projection.py`

**Interfaces:**
- Consumes: `build_semantic_graph(corpus: dict[str, Any], evidence_graph: dict[str, Any])`.
- Produces: schema `manual_semantic_graph.v1` with deterministic nodes, edges, and provenance metrics.

- [ ] **Step 1: Add failing extraction and deduplication tests**

```python
def test_build_semantic_graph_creates_cited_fault_chain() -> None:
    graph = build_semantic_graph(_corpus_with_fault_page_66(), _evidence_graph())
    kinds = {node["kind"] for node in graph["nodes"]}
    assert {"Fault", "Cause", "Remedy"} <= kinds
    assert all(node["properties"]["citations"] for node in graph["nodes"])
    assert all(edge["properties"]["supporting_chunk_ids"] for edge in graph["edges"])


def test_alias_normalization_merges_type_compatible_entities_only() -> None:
    graph = build_semantic_graph(_corpus_with_duplicate_com_faults(), _evidence_graph())
    faults = [node for node in graph["nodes"] if node["kind"] == "Fault"]
    remedies = [node for node in graph["nodes"] if node["kind"] == "Remedy"]
    assert len(faults) == 1
    assert len(remedies) == 2
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/unit/test_manual_semantic_projection.py -k "fault_chain or alias_normalization"`

Expected: FAIL because `build_semantic_graph` does not exist.

- [ ] **Step 3: Implement deterministic extraction and normalization**

The module must expose the exact public signatures
`extract_semantic_candidates(chunk: dict[str, Any]) -> list[dict[str, Any]]`,
`resolve_semantic_entities(candidates: list[dict[str, Any]]) -> list[SemanticNode]`,
`build_semantic_graph(corpus: dict[str, Any], evidence_graph: dict[str, Any]) -> dict[str, Any]`,
and `validate_semantic_provenance(payload: dict[str, Any]) -> dict[str, Any]`.
Normalize labels with this implementation:

```python
def normalize_semantic_label(value: str) -> str:
    compact = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().lower()
    return re.sub(r"[^0-9a-z가-힣 ]+", "", compact)
```

Move existing heading, numbered-step, fault, cause, remedy, and warning extraction
from the evidence projector into this module. Each extracted candidate contains
`kind`, `label`, `source_chunk_id`, `citation`, `confidence`, and
`extraction_method`. Entity resolution groups by `(equipment_type, kind,
normalize_semantic_label(label))`; it unions aliases, chunk IDs, and citations
but never merges across kinds. Stable IDs hash semantic type, normalized label,
equipment type, and sorted source IDs. `build_semantic_graph` emits semantic
nodes, semantic relations, and external `SUPPORTED_BY` links. Validation rejects
any semantic node or edge without a supporting chunk and positive page citation.

- [ ] **Step 4: Add procedure ordering and false-positive regression tests**

```python
def test_procedure_steps_preserve_source_order() -> None:
    graph = build_semantic_graph(_numbered_procedure_corpus(), _evidence_graph())
    precedes = [edge for edge in graph["edges"] if edge["type"] == "PRECEDES"]
    assert [(edge["source"], edge["target"]) for edge in precedes] == _expected_step_pairs()


def test_plain_sentence_containing_cause_word_does_not_create_fault() -> None:
    graph = build_semantic_graph(_corpus("원인이 발생하지 않도록 확인합니다."), _evidence_graph())
    assert not any(node["kind"] == "Fault" for node in graph["nodes"])
```

- [ ] **Step 5: Run extraction tests**

Run: `.venv/bin/python -m pytest -q tests/unit/test_manual_semantic_projection.py tests/unit/test_manual_knowledge_graph.py`

Expected: PASS.

- [ ] **Step 6: Commit semantic extraction**

```bash
git add knowledge/manuals/semantic_projection.py knowledge/manuals/graph_projection.py tests/unit/test_manual_semantic_projection.py tests/unit/test_manual_knowledge_graph.py
git commit -m "feat: project cited manual semantics"
```

### Task 3: Deterministic Query-Centered Semantic Projection

**Files:**
- Modify: `knowledge/manuals/semantic_projection.py`
- Modify: `knowledge/manuals/service.py`
- Test: `tests/unit/test_manual_semantic_projection.py`
- Test: `tests/unit/test_manual_knowledge_retrieval.py`

**Interfaces:**
- Consumes: ranked chunk IDs and `manual_semantic_graph.v1`.
- Produces: `project_semantic_subgraph(graph, seed_chunk_ids, purpose, node_limit=40, edge_limit=60, depth=2)` and `manual_context.v1.semantic_projection`.

- [ ] **Step 1: Add failing bounded-projection tests**

```python
def test_query_projection_hides_chunks_and_keeps_connected_recovery_path() -> None:
    projection = project_semantic_subgraph(
        _semantic_graph(),
        seed_chunk_ids={"manual-chunk:software:66:1"},
        purpose="recovery",
        node_limit=40,
        edge_limit=60,
        depth=2,
    )
    assert all(node["kind"] != "ManualChunk" for node in projection["nodes"])
    assert {edge["type"] for edge in projection["edges"]} >= {"HAS_CAUSE", "RESOLVED_BY"}
    assert projection["depth"] == 2


def test_query_projection_is_deterministic_and_bounded() -> None:
    first = project_semantic_subgraph(_large_graph(), {"chunk:1"}, "procedure")
    second = project_semantic_subgraph(_large_graph(), {"chunk:1"}, "procedure")
    assert first == second
    assert len(first["nodes"]) <= 40
    assert len(first["edges"]) <= 60
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/unit/test_manual_semantic_projection.py -k projection`

Expected: FAIL because `project_semantic_subgraph` is undefined.

- [ ] **Step 3: Implement semantic seed resolution and two-hop expansion**

Build reverse support indexes from chunk ID to semantic node IDs. Rank seeds by evidence score, semantic confidence, purpose-specific kind priority, canonical label, and stable ID. Expand only semantic relations; carry citations in node properties rather than inserting evidence nodes. Set `truncated=true` when either limit excludes a candidate.

- [ ] **Step 4: Extend retrieval without breaking existing consumers**

```python
context = {
    "schema": "manual_context.v1",
    "equipment_type": equipment_type,
    "purpose": purpose,
    "query": query,
    "chunks": chunks,
    "graph": legacy_bounded_graph,
    "semantic_projection": project_semantic_subgraph(
        semantic_graph,
        {str(item["chunk_id"]) for item in chunks},
        purpose=purpose,
        node_limit=40,
        edge_limit=60,
        depth=2,
    ),
    "coverage": round(coverage, 6),
    "insufficient_evidence": not chunks or coverage < 0.08,
    "insufficient_semantic_evidence": not semantic_projection["nodes"],
}
```

Keep `graph` during this compatibility release. Prompting and Lab Equipment continue reading `chunks`, not visualization nodes.

- [ ] **Step 5: Add compatibility tests**

```python
def test_query_returns_chunks_and_semantic_projection() -> None:
    result = _service().query(_procedure_request())
    assert result["schema"] == "manual_context.v1"
    assert result["chunks"][0]["citation"]["page"] == 6
    assert result["semantic_projection"]["nodes"]
    assert all(node["kind"] != "ManualChunk" for node in result["semantic_projection"]["nodes"])


def test_product_and_version_hints_do_not_exclude_other_utm_manuals() -> None:
    result = _service().query({**_recovery_request(), "product_hint": "unknown", "version_hint": "0"})
    assert result["chunks"]
```

- [ ] **Step 6: Run service and equipment tests**

Run: `.venv/bin/python -m pytest -q tests/unit/test_manual_semantic_projection.py tests/unit/test_manual_knowledge_retrieval.py tests/unit/test_manual_knowledge_prompting.py tests/unit/test_equipment_agent.py`

Expected: PASS and existing equipment payload assertions remain unchanged.

- [ ] **Step 7: Commit query projection**

```bash
git add knowledge/manuals/semantic_projection.py knowledge/manuals/service.py tests/unit/test_manual_semantic_projection.py tests/unit/test_manual_knowledge_retrieval.py
git commit -m "feat: return bounded manual semantic projections"
```

### Task 4: Atomic Semantic Index Build and Status Metrics

**Files:**
- Modify: `knowledge/manuals/service.py`
- Test: `tests/unit/test_manual_knowledge_ingest.py`
- Test: `tests/unit/test_manual_semantic_projection.py`

**Interfaces:**
- Consumes: `build_semantic_graph(corpus, evidence_graph)`.
- Produces: `memory/knowledge/manual_rag/manual_semantic_graph.json`, semantic receipts, and quality metrics.

- [ ] **Step 1: Add failing atomicity test**

```python
def test_failed_semantic_rebuild_preserves_active_projection(monkeypatch, tmp_path) -> None:
    service = _service(tmp_path)
    active = tmp_path / "manual_semantic_graph.json"
    active.write_text('{"schema":"manual_semantic_graph.v1","version":"old"}', encoding="utf-8")
    monkeypatch.setattr("knowledge.manuals.service.build_semantic_graph", lambda *_args: (_ for _ in ()).throw(ValueError("invalid support")))
    result = service.ingest()
    assert result["ok"] is False
    assert '"version":"old"' in active.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the atomicity test and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/unit/test_manual_knowledge_ingest.py -k semantic_rebuild`

Expected: FAIL because ingestion does not preserve a semantic index.

- [ ] **Step 3: Implement validate-then-replace persistence**

Write the candidate to `manual_semantic_graph.json.tmp`, validate schema, provenance, and ontology, write a semantic rebuild receipt, then use `os.replace`. Never overwrite the active file when extraction or validation fails. Require corpus, evidence graph, and semantic graph in `ensure_ingested`.

- [ ] **Step 4: Add quality metrics to status**

Return `semantic_node_count`, `semantic_edge_count`, `semantic_provenance_coverage`, `isolated_semantic_node_rate`, `fault_chain_completion_rate`, and `procedure_chain_completion_rate`. Preserve existing evidence counts.

- [ ] **Step 5: Run ingestion and status tests**

Run: `.venv/bin/python -m pytest -q tests/unit/test_manual_knowledge_ingest.py tests/unit/test_manual_semantic_projection.py`

Expected: PASS.

- [ ] **Step 6: Rebuild the real local index**

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from knowledge.manuals.service import ManualKnowledgeService
service = ManualKnowledgeService(project_root=Path('.'))
try:
    print(service.ingest())
    print(service.status())
finally:
    service.close()
PY
```

Expected: two sources, nonzero semantic nodes and edges, and provenance coverage `1.0` for accepted semantic assertions.

- [ ] **Step 7: Commit atomic index support**

```bash
git add knowledge/manuals/service.py tests/unit/test_manual_knowledge_ingest.py tests/unit/test_manual_semantic_projection.py
git commit -m "feat: persist versioned manual semantic index"
```

### Task 5: Semantic Graph API Compatibility

**Files:**
- Modify: `knowledge/manuals/service.py`
- Modify: `app/main.py`
- Test: `tests/integration/test_manual_knowledge_api.py`

**Interfaces:**
- Consumes: `ManualKnowledgeService.graph(limit=120, view="semantic")`.
- Produces: `GET /api/knowledge/manuals/graph?view=semantic&limit=120` and compatible query responses.

- [ ] **Step 1: Add failing API tests**

```python
def test_manual_graph_api_defaults_to_semantic_view(monkeypatch) -> None:
    _install_manual_service(monkeypatch)
    payload = TestClient(app).get("/api/knowledge/manuals/graph?limit=120").json()
    assert payload["view"] == "semantic"
    assert all(node["kind"] != "ManualChunk" for node in payload["nodes"])


def test_manual_query_api_keeps_v1_chunks_and_adds_projection(monkeypatch) -> None:
    payload = TestClient(app).post("/api/knowledge/manuals/query", json=_request()).json()
    assert payload["schema"] == "manual_context.v1"
    assert payload["chunks"]
    assert payload["semantic_projection"]["nodes"]
```

- [ ] **Step 2: Run API tests and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/integration/test_manual_knowledge_api.py`

Expected: FAIL because graph view selection is missing.

- [ ] **Step 3: Implement graph view selection**

Accept only `semantic` and `evidence`; default to `semantic`. Evidence view is an explicit diagnostic path bounded to 300 nodes. Return HTTP 422 for another value. Retrieval failures continue degrading to insufficient evidence in equipment prompt paths.

- [ ] **Step 4: Run API and equipment integration tests**

Run: `.venv/bin/python -m pytest -q tests/integration/test_manual_knowledge_api.py tests/integration/test_equipment_skill_api.py tests/unit/test_equipment_agent.py`

Expected: PASS.

- [ ] **Step 5: Commit API support**

```bash
git add knowledge/manuals/service.py app/main.py tests/integration/test_manual_knowledge_api.py
git commit -m "feat: expose manual semantic graph API"
```

### Task 6: Query-Focused Knowledge Workspace

**Files:**
- Modify: `web/templates/knowledge.html`
- Modify: `web/static/knowledge.js`
- Modify: `web/static/knowledge.css`
- Modify: `tests/integration/test_knowledge_workspace.py`
- Modify: `tests/ui/knowledge_workspace_browser_audit.py`

**Interfaces:**
- Consumes: semantic graph API and `manual_context.v1.semantic_projection`.
- Produces: coordinated evidence, semantic graph, and inspector regions.

- [ ] **Step 1: Add failing DOM contract test**

```python
def test_manual_workspace_exposes_semantic_graph_and_inspector(client) -> None:
    html = client.get("/knowledge#manuals").text
    assert 'id="knowledge-manual-graph"' in html
    assert 'id="knowledge-manual-results"' in html
    assert 'id="knowledge-manual-inspector"' in html
    assert 'id="knowledge-manual-show-evidence"' in html
```

- [ ] **Step 2: Run test and confirm failure**

Run: `.venv/bin/python -m pytest -q tests/integration/test_knowledge_workspace.py`

Expected: FAIL because the semantic inspector and evidence expansion control are absent.

- [ ] **Step 3: Build the three-region markup**

Use one query/status row, then a 34/46/20 percent desktop grid for evidence, semantic graph, and inspector. Do not add another page or duplicate Knowledge controls. Evidence expansion is selected-node scoped and hidden by default.

- [ ] **Step 4: Implement semantic rendering**

```javascript
function manualSemanticGraphOption(payload = {}, purpose = "procedure") {}
function manualSemanticSymbol(kind = "ManualSection") {}
function renderManualInspector(nodeOrEdge = null) {}
function renderManualEvidence(payload = {}) {}
function applyManualProjection(payload = {}) {}
```

Use left-to-right hierarchy for procedures, fixed `Fault -> Cause -> Remedy` lanes for recovery, and force layout only for mixed decision queries. Use distinct shapes as well as colors. Never render `ManualChunk` in the default series. Show complete labels, confidence, relation type, and citations in the inspector.

- [ ] **Step 5: Preserve interaction state**

Maintain `manualWorkspaceState = {query, purpose, selectedId, zoom, showEvidence}`. Status refresh must not replace an active query graph. Replace it only after ingestion, a new query, or explicit refresh. Restore selection when the selected ID remains present.

- [ ] **Step 6: Extend browser assertions**

Verify no default chunk nodes, graph width at least 700, inspector width at least 280, evidence width at least 360, no horizontal overflow, and selected-node inspector content containing confidence and a page citation.

- [ ] **Step 7: Run UI tests and visual audit**

```bash
.venv/bin/python -m pytest -q tests/integration/test_knowledge_workspace.py
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 7861
.venv/bin/python tests/ui/knowledge_workspace_browser_audit.py \
  --base-url http://127.0.0.1:7861 \
  --screenshot artifacts/ui/manual_semantic_graph_1920x1080.png
```

Expected: seven tabs, no overflow, no default chunk nodes, readable semantic paths, and a populated inspector. Stop only the temporary port-7861 process.

- [ ] **Step 8: Commit the workspace slice**

```bash
git add web/templates/knowledge.html web/static/knowledge.js web/static/knowledge.css tests/integration/test_knowledge_workspace.py tests/ui/knowledge_workspace_browser_audit.py
git commit -m "feat: visualize query-focused manual semantics"
```

### Task 7: Documentation and Full Acceptance Audit

**Files:**
- Modify: `docs/knowledge/manual_rag_knowledge.ko.md`
- Modify: `docs/agents/knowledge_agent.md`
- Modify: `docs/agents/equipment_agent.md`
- Modify: `docs/document_manifest.yaml`

**Interfaces:**
- Consumes: completed semantic behavior.
- Produces: operator architecture, rebuild procedure, metrics, and acceptance evidence.

- [ ] **Step 1: Update documentation**

Document evidence, semantic, and query layers; atomic rebuild; default chunk hiding; relation review; metrics; and failure handling. State explicitly that Lab Equipment execution and Guardian gates are unchanged.

- [ ] **Step 2: Run complete relevant tests**

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_manual_knowledge_ingest.py \
  tests/unit/test_manual_knowledge_graph.py \
  tests/unit/test_manual_knowledge_retrieval.py \
  tests/unit/test_manual_knowledge_prompting.py \
  tests/unit/test_manual_semantic_projection.py \
  tests/unit/test_equipment_agent.py \
  tests/integration/test_manual_knowledge_api.py \
  tests/integration/test_knowledge_ontology_api.py \
  tests/integration/test_knowledge_workspace.py \
  tests/integration/test_equipment_skill_api.py
```

Expected: all pass with no newly introduced warnings.

- [ ] **Step 3: Validate documents and static code**

```bash
.venv/bin/python scripts/validate_documentation.py --manifest docs/document_manifest.yaml
node --check web/static/knowledge.js
.venv/bin/python -m py_compile app/main.py agents/equipment_agent.py knowledge/manuals/*.py
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 4: Run actual-corpus acceptance queries**

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from knowledge.manuals.service import ManualKnowledgeService
service = ManualKnowledgeService(project_root=Path('.'))
try:
    for purpose, query in [
        ("procedure", "UTM 시험 시작 순서"),
        ("recovery", "통신 연결 실패 원인과 복구 조치"),
    ]:
        result = service.query({"equipment_type": "utm", "purpose": purpose, "query": query, "top_k": 6})
        projection = result["semantic_projection"]
        assert result["chunks"]
        assert projection["nodes"]
        assert all(node["kind"] != "ManualChunk" for node in projection["nodes"])
        assert all(node["properties"]["citations"] for node in projection["nodes"])
        print(purpose, result["chunks"][0]["citation"], len(projection["nodes"]), len(projection["edges"]))
finally:
    service.close()
PY
```

Expected: procedure and recovery questions return their expected pages and connected, fully cited semantic projections.

- [ ] **Step 5: Review execution boundaries**

Confirm no changes to tool payload construction, device bridge dispatch, PyAutoGUI program IDs, Guardian policies, credentials, or safety gates. Confirm generated semantic indexes remain ignored by Git.

- [ ] **Step 6: Commit documentation**

```bash
git add docs/knowledge/manual_rag_knowledge.ko.md docs/agents/knowledge_agent.md docs/agents/equipment_agent.md docs/document_manifest.yaml
git commit -m "docs: explain manual semantic graph operations"
```
