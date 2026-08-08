# Knowledge Agent Neo4j Graphify Ontology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Neo4j the operational Knowledge Graph while preserving append-only JSONL evidence, durable outage recovery, bounded Graph RAG, and existing Knowledge Agent contracts.

**Architecture:** Runtime inputs are normalized into `knowledge_event.v1`, validated against a versioned ATR ontology, durably appended to JSONL, and placed in a file outbox before any Neo4j write. A shared service layer handles synchronization, bounded query plans, reconciliation, API/CLI operations, and additive Knowledge Agent context so GUI, CLI, BO, and Guardian consume the same state.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, Neo4j Python driver, FastAPI, pytest, existing ATR JSONL/Graphify infrastructure.

## Global Constraints

- Existing `knowledge_context.v1`, `knowledge_report.v1`, `evolution_proposal.v1`, and typed JSONL contracts remain backward compatible.
- Every graph mutation uses validate -> JSONL append/fsync -> durable outbox -> bounded Neo4j transaction -> acknowledgement.
- Neo4j outage is degraded operation, not evidence loss; pending items remain replayable and safety-event lag is visible.
- No LLM, browser, or API caller may submit arbitrary Cypher.
- Core ontology definitions are versioned and cannot be autonomously modified.
- Raw telemetry, raw reasoning, credentials, and large artifacts remain outside Neo4j.
- Runtime writes are idempotent by deterministic event, entity, and relation identifiers.
- Existing hardware, orchestrator, MCP, and Agent output contracts are not changed destructively.

---

### Task 1: ATR Core Ontology Registry and Validator

**Files:**
- Create: `knowledge/ontology/__init__.py`
- Create: `knowledge/ontology/atr_core.v1.yaml`
- Create: `knowledge/ontology/relation_rules.v1.yaml`
- Create: `knowledge/ontology/validation_shapes.v1.yaml`
- Create: `knowledge/ontology/registry.py`
- Create: `knowledge/ontology/validator.py`
- Test: `tests/unit/test_knowledge_ontology.py`

**Interfaces:**
- Produces: `OntologyRegistry.load_default(project_root: Path) -> OntologyRegistry`
- Produces: `OntologyRegistry.class_names`, `relation_rules`, `state_transitions`, `version_id`
- Produces: `OntologyValidator.validate_event(event: dict[str, Any]) -> ValidationReport`
- Produces: `OntologyValidator.validate_transition(entity_class: str, old: str, new: str) -> ValidationReport`

- [ ] **Step 1: Write failing ontology tests**

```python
def test_default_registry_exposes_versioned_run_and_specimen_classes(project_root):
    registry = OntologyRegistry.load_default(project_root)
    assert registry.version_id == "atr-core-1.0.0"
    assert {"Run", "Specimen", "GuardianGate"} <= registry.class_names

def test_validator_rejects_relation_outside_declared_domain(project_root):
    report = OntologyValidator(OntologyRegistry.load_default(project_root)).validate_relationship(
        {"relation_type": "CONTAINS", "source_class": "Specimen", "target_class": "Cycle"}
    )
    assert not report.ok
    assert "domain" in report.errors[0]
```

- [ ] **Step 2: Run `pytest -q tests/unit/test_knowledge_ontology.py` and confirm import failure**
- [ ] **Step 3: Add immutable YAML definitions and typed registry/validation result dataclasses**
- [ ] **Step 4: Implement class, relation domain/range, required property, cardinality-intent, and lifecycle validation**
- [ ] **Step 5: Run ontology tests and existing `tests/unit/test_knowledge_graph_backend.py`**

### Task 2: Event Normalizer and Append-Only Audit Ledger

**Files:**
- Create: `knowledge/event_normalizer.py`
- Create: `knowledge/audit_ledger.py`
- Test: `tests/unit/test_knowledge_event_pipeline.py`

**Interfaces:**
- Produces: `normalize_knowledge_event(payload: dict[str, Any], *, ontology_version: str) -> dict[str, Any]`
- Produces: `AuditLedger(root: Path).append(event: dict[str, Any]) -> LedgerReceipt`
- Consumes: ontology validator from Task 1.

- [ ] **Step 1: Write failing deterministic-ID and ledger tests**

```python
def test_normalizer_is_idempotent_for_same_semantic_event():
    one = normalize_knowledge_event(PAYLOAD, ontology_version="atr-core-1.0.0")
    two = normalize_knowledge_event(PAYLOAD, ontology_version="atr-core-1.0.0")
    assert one["event_id"] == two["event_id"]
    assert one["idempotency_key"] == two["idempotency_key"]

def test_ledger_appends_one_json_line_and_returns_hash(tmp_path):
    receipt = AuditLedger(tmp_path).append(EVENT)
    assert receipt.path.exists()
    assert receipt.sha256
    assert receipt.line_number == 1
```

- [ ] **Step 2: Run the focused tests and confirm missing-module failure**
- [ ] **Step 3: Implement canonical JSON hashing, event defaults, stable identifiers, and bounded summaries**
- [ ] **Step 4: Implement date-partitioned append, flush, fsync, and receipt generation**
- [ ] **Step 5: Verify duplicate semantic events preserve IDs but remain auditable ledger entries**

### Task 3: Durable Outbox and Dead-Letter Recovery

**Files:**
- Create: `knowledge/durable_outbox.py`
- Test: `tests/unit/test_knowledge_outbox.py`

**Interfaces:**
- Produces: `DurableOutbox(root: Path, max_attempts: int = 5)`
- Produces: `enqueue(event, ledger_receipt) -> OutboxItem`
- Produces: `pending()`, `acknowledge(item_id, sync_receipt)`, `record_failure(item_id, error)`
- Produces: `stats() -> dict[str, Any]`

- [ ] **Step 1: Write failing tests for atomic enqueue, acknowledgement, retry, and dead-letter state**
- [ ] **Step 2: Confirm tests fail because `DurableOutbox` does not exist**
- [ ] **Step 3: Implement atomic temp-write plus `os.replace`, deterministic filenames, and attempt metadata**
- [ ] **Step 4: Implement pending/acknowledged/dead-letter moves without deleting payload evidence**
- [ ] **Step 5: Run focused tests including process-restart reconstruction from disk**

### Task 4: Neo4j Repository, Schema Migration, and Sync Worker

**Files:**
- Create: `knowledge/migrations/v1_constraints.cypher`
- Create: `knowledge/migrations/v1_indexes.cypher`
- Create: `knowledge/neo4j_repository.py`
- Create: `knowledge/graph_sync_worker.py`
- Modify: `knowledge/graph_backend.py`
- Test: `tests/unit/test_neo4j_repository.py`
- Test: `tests/integration/test_knowledge_graph_sync.py`

**Interfaces:**
- Produces: `Neo4jRepository(driver, database).apply_schema()`
- Produces: `Neo4jRepository.apply_event(event) -> GraphSyncReceipt`
- Produces: `GraphSyncWorker.sync_pending(limit: int = 100) -> SyncReport`
- Consumes: Task 2 ledger receipts and Task 3 outbox items.

- [ ] **Step 1: Write a fake-driver unit test proving stable `MERGE` keys and bounded transaction payloads**
- [ ] **Step 2: Write outage/recovery integration test: enqueue while unavailable, replay once, no duplicate logical event**
- [ ] **Step 3: Confirm both tests fail before production code**
- [ ] **Step 4: Implement constraints/index migration and repository health/stats/entity/event upserts**
- [ ] **Step 5: Implement synchronous bounded worker with retry metadata and safety-lag counts**
- [ ] **Step 6: Keep `JsonGraphBackend` as compatibility/read-only fallback, not operational source of truth**
- [ ] **Step 7: Run unit tests; run Docker Neo4j integration when Docker is available**

### Task 5: Graph Query Plans, Retrieval, and Graph RAG

**Files:**
- Create: `knowledge/graph_query_planner.py`
- Create: `knowledge/graph_retrieval.py`
- Create: `knowledge/graph_rag.py`
- Test: `tests/unit/test_graph_query_planner.py`
- Test: `tests/unit/test_graph_rag.py`

**Interfaces:**
- Produces: `GraphQueryPlan(kind, filters, depth, limit)` with an explicit allowlist.
- Produces: `validate_query_plan(payload) -> GraphQueryPlan`
- Produces: `GraphRetrievalService.query(plan) -> dict[str, Any]`
- Produces: `GraphRAG.build_context(plan, typed_memory, vector_context, orchestrator_state) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests rejecting raw Cypher, unknown query kinds, depth above 4, and limit above 100**
- [ ] **Step 2: Write failing tests for `run_context`, `similar_experiments`, `failure_path`, `bo_context`, and `safety_context` templates**
- [ ] **Step 3: Implement immutable query-kind registry and normalized filters**
- [ ] **Step 4: Implement predefined parameterized Cypher templates and result bounding**
- [ ] **Step 5: Implement context fusion that labels graph, typed-memory, vector, and current-state evidence separately**
- [ ] **Step 6: Run focused security and context tests**

### Task 6: Knowledge Service and Agent Runtime Integration

**Files:**
- Create: `knowledge/service.py`
- Modify: `agents/knowledge_agent.py`
- Modify: `knowledge/graph_importer.py`
- Test: `tests/unit/test_knowledge_service.py`
- Modify: `tests/unit/test_knowledge_agent.py`

**Interfaces:**
- Produces: `KnowledgeService.from_env(project_root: Path) -> KnowledgeService`
- Produces: `ingest(payload) -> IngestReport`, `sync() -> SyncReport`, `query(payload) -> dict`
- Produces: `build_run_context(...)`, `build_bo_context(...)`, `build_safety_context(...)`
- Consumes all Task 1-5 services.

- [ ] **Step 1: Write failing service test proving ledger/outbox survive Neo4j failure and status reports degraded mode**
- [ ] **Step 2: Write failing Knowledge Agent test proving graph context is additive and legacy keys remain unchanged**
- [ ] **Step 3: Implement the service facade and explicit lifecycle management**
- [ ] **Step 4: Replace direct mirror-only Agent use with service ingestion, pre-query, and post-sync receipts**
- [ ] **Step 5: Add BO and Guardian context payloads with confidence, validity, and unsynchronized-safety counts**
- [ ] **Step 6: Run Knowledge Agent and LangGraph runtime regression tests**

### Task 7: Ontology Proposals and Graphify Reconciliation

**Files:**
- Create: `knowledge/ontology_proposals.py`
- Create: `knowledge/graph_reconciliation.py`
- Modify: `knowledge/graphify_bridge.py`
- Test: `tests/unit/test_ontology_proposals.py`
- Modify: `tests/unit/test_graphify_bridge.py`

**Interfaces:**
- Produces: `OntologyProposalStore.create/approve/reject/list`
- Produces: `reconcile_project_graph(previous, current) -> ReconciliationReport`
- Consumes: core ontology registry and existing Graphify project graph.

- [ ] **Step 1: Write failing tests that prevent apply before validation, Guardian review, and operator approval**
- [ ] **Step 2: Write failing Graphify test for content-hash skip and retired-node preservation**
- [ ] **Step 3: Implement append-only proposal transitions and immutable approval evidence**
- [ ] **Step 4: Implement project graph diff/reconciliation with `active=false` and `retired_at`**
- [ ] **Step 5: Run proposal, Graphify, and import regression tests**

### Task 8: Shared API and CLI Surface

**Files:**
- Modify: `app/main.py`
- Modify: `scripts/knowledge_graph_cli.py`
- Modify: `scripts/knowledge_graphify_scan.py`
- Create: `scripts/knowledge_ontology_cli.py`
- Modify: `install/atr`
- Test: `tests/integration/test_knowledge_ontology_api.py`
- Modify: `tests/integration/test_knowledge_api.py`
- Modify: `tests/integration/test_knowledge_graphify_api.py`

**Interfaces:**
- API and CLI both consume `KnowledgeService`; neither constructs raw Cypher.
- Adds ontology, stats, sync, reconcile, entity/run/provenance, Graphify status/diff endpoints from the approved spec.

- [ ] **Step 1: Write failing API tests for ontology metadata, validation, graph stats/sync, bounded POST query, and raw-Cypher rejection**
- [ ] **Step 2: Write CLI parity tests for health/stats/sync/reconcile/query and ontology version/validate/proposals**
- [ ] **Step 3: Implement API dependency helpers returning one request-scoped service**
- [ ] **Step 4: Add routes without removing existing GET graph query compatibility**
- [ ] **Step 5: Implement CLI commands over the same service methods**
- [ ] **Step 6: Run all Knowledge API/CLI tests**

### Task 9: Knowledge Workspace and Live Report Integration

**Files:**
- Modify: `web/static/planning.js`
- Modify: `graphs/modules/knowledge/ui.yaml`
- Modify: `graphs/modules/knowledge/module.yaml`
- Test: `tests/integration/test_live_gui_runtime_layout.py`
- Create: `tests/ui/knowledge_workspace_browser_audit.py`

**Interfaces:**
- Consumes API status, graph query, ontology, proposal, and reconciliation responses.
- Keeps the Live GUI report compact while the workspace exposes administration details.

- [ ] **Step 1: Write failing DOM/layout tests for connection, ontology version, pending/dead-letter, explorer, memory, proposal, and sync sections**
- [ ] **Step 2: Implement compact report cards and bounded graph explorer rendering**
- [ ] **Step 3: Implement proposal controls and sync/reconcile actions with in-flight button locking**
- [ ] **Step 4: Run JS syntax, layout regression, and Selenium browser audit**

### Task 10: Migration, Documentation, and End-to-End Verification

**Files:**
- Create: `knowledge/ontology/migration.py`
- Create: `scripts/migrate_knowledge_graph.py`
- Modify: `REQUIREMENTS.md`
- Modify: `docs/runtime/current_code_snapshot.md`
- Modify: `docs/tutorials/user_manual.ko.md`
- Create: `docs/knowledge/knowledge_graph_operations.ko.md`
- Test: `tests/integration/test_knowledge_migration.py`

**Interfaces:**
- Produces dry-run and apply migration modes with backup manifest, import counts, hash verification, reconciliation, and rollback instructions.

- [ ] **Step 1: Write failing migration test using legacy JSONL and Graphify fixtures**
- [ ] **Step 2: Implement backup manifest, schema apply, ontology load, Graphify import, typed-memory import, and reconciliation**
- [ ] **Step 3: Document installation, credentials, startup, degraded operation, recovery, GUI, CLI, and troubleshooting**
- [ ] **Step 4: Run `python -m py_compile` for changed Python and `node --check web/static/planning.js`**
- [ ] **Step 5: Run all Knowledge unit/integration tests and the existing Knowledge/Graphify suite**
- [ ] **Step 6: With Docker available, start Neo4j, apply schema, migrate fixtures, simulate outage/recovery, query lineage, then stop only the test container**
- [ ] **Step 7: Run `git diff --check` and review the final diff for credentials and destructive contract changes**

## Execution Order and Checkpoints

1. Tasks 1-3 establish the durable, testable evidence foundation without requiring Neo4j.
2. Tasks 4-5 add operational graph storage and safe retrieval.
3. Tasks 6-7 integrate runtime decisions and governed evolution.
4. Tasks 8-9 expose the shared service to operators without duplicating backend logic.
5. Task 10 migrates existing data and validates outage recovery end-to-end.

Each task must finish green before starting the next. No task may mark an outbox item acknowledged unless its Neo4j transaction returns a receipt for the same event ID.
