# Knowledge Relation Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add continuous LLM-assisted Knowledge Graph relation reconciliation, operator revision approval, and an existing-node-only Graph Explorer Edit Mode without bypassing ATR's ontology, ledger, outbox, or Neo4j synchronization contracts.

**Architecture:** A durable relation store records work items, immutable proposals, and versioned decisions. Deterministic graph-gap detection and candidate ranking bound the context before the selected LLM proposes typed edges. A shared priority-aware LLM lease protects Guardian, active workflow, and operator chat from background reconciliation. Approved proposals and graph edits are converted to normal `knowledge_event.v1` payloads and enter the existing Knowledge service pipeline.

**Tech Stack:** Python 3.12, FastAPI, asyncio, Pydantic/dataclasses, JSONL/atomic JSON persistence, Neo4j/JSON graph backends, vanilla JavaScript, ECharts, Selenium, pytest.

## Global Constraints

- LLM confidence for automatic promotion is at least `0.90`.
- Deterministic evidence score for automatic promotion is at least `0.80`.
- An automatically promoted proposal must pass ontology validation, reference existing nodes, contain provenance, and not duplicate or self-reference an accepted edge.
- Every other valid proposal is durable and operator-reviewable.
- The LLM may not create graph nodes, issue arbitrary Cypher, alter the ontology, or write directly to Neo4j.
- Graph Explorer Edit Mode may change only existing-node relationships and allowlisted metadata: `label`, `alias`, `note`, and `tags`.
- Edit Mode may not alter node IDs, entity classes, ontology versions, original provenance, or audit receipts.
- Semantic graph mutations always pass through `KnowledgeService.ingest()`; graph layout coordinates are UI preferences only.
- Background reconciliation never loads an unloaded model and never blocks the experiment loop.
- Existing uncommitted user changes, including `.env.example`, must remain untouched unless directly required by this feature.

---

### Task 1: Durable Relation Contracts and Store

**Files:**
- Create: `knowledge/relation_reconciliation.py`
- Create: `knowledge/relation_store.py`
- Test: `tests/unit/test_knowledge_relation_store.py`

**Interfaces:**
- Produces: `RelationWorkItem`, `RelationProposal`, `RelationDecision`, `GraphEditDraft`, and `RelationStore`.
- Produces: `RelationStore.enqueue_node()`, `claim_pending()`, `append_proposal()`, `append_decision()`, `list_proposals()`, `get_proposal()`, `stats()`, `save_edit_draft()`, and `get_edit_draft()`.
- Persistence root: `memory/knowledge/reconciliation/` with atomic queue state and append-only proposal/decision JSONL files.

- [ ] **Step 1: Write failing store lifecycle tests**

```python
def test_relation_store_deduplicates_work_and_preserves_decisions(tmp_path):
    store = RelationStore(tmp_path)
    first = store.enqueue_node("node:a", graph_revision="rev-1", evidence_hash="ev-1")
    second = store.enqueue_node("node:a", graph_revision="rev-1", evidence_hash="ev-1")
    assert first.work_id == second.work_id
    proposal = store.append_proposal(RelationProposal.fixture("proposal-1"))
    decision = store.append_decision(RelationDecision.approved(proposal, operator="jin"))
    assert store.get_proposal("proposal-1").status == "approved"
    assert decision.proposal_version == 1
```

- [ ] **Step 2: Run the test and confirm missing imports/contracts fail**

Run: `.venv/bin/python -m pytest -q tests/unit/test_knowledge_relation_store.py`

- [ ] **Step 3: Implement immutable contracts and lock-protected atomic persistence**

Use stable SHA-256 IDs, timezone-aware timestamps, bounded string/list fields, `fcntl` file locks, atomic replacement for mutable queue/draft indexes, and append-only JSONL for proposals/decisions.

- [ ] **Step 4: Verify store tests pass**

Run: `.venv/bin/python -m pytest -q tests/unit/test_knowledge_relation_store.py`

- [ ] **Step 5: Commit**

```bash
git add knowledge/relation_reconciliation.py knowledge/relation_store.py tests/unit/test_knowledge_relation_store.py
git commit -m "feat: add durable knowledge relation store"
```

### Task 2: Deterministic Graph Gap Detection and Candidate Ranking

**Files:**
- Modify: `knowledge/graph_backend.py`
- Modify: `knowledge/ontology/registry.py`
- Modify: `knowledge/relation_reconciliation.py`
- Test: `tests/unit/test_knowledge_relation_reconciliation.py`
- Test: `tests/unit/test_knowledge_graph_backend.py`

**Interfaces:**
- Produces: `GraphGapDetector.detect(snapshot, *, limit=10) -> list[GraphGap]`.
- Produces: `RelationCandidateGenerator.rank(source, nodes, edges, registry, *, limit=8) -> list[RelationCandidate]`.
- Adds internal backend query kinds `reconciliation_gaps`, `reconciliation_context`, and `node_lookup`; none accepts Cypher.

- [ ] **Step 1: Write failing isolated, disconnected, missing-link, and ranking tests**

```python
def test_gap_detector_finds_isolated_and_weak_nodes():
    gaps = GraphGapDetector().detect(SNAPSHOT, limit=10)
    assert {(gap.node_id, gap.gap_type) for gap in gaps} == {
        ("specimen:isolated", "isolated"),
        ("artifact:weak", "disconnected_component"),
    }

def test_candidate_ranking_excludes_ontology_incompatible_targets():
    candidates = generator.rank(source, nodes, edges, registry, limit=8)
    assert all(candidate.target_class in candidate.allowed_target_classes for candidate in candidates)
```

- [ ] **Step 2: Run focused tests and verify expected failures**

Run: `.venv/bin/python -m pytest -q tests/unit/test_knowledge_relation_reconciliation.py tests/unit/test_knowledge_graph_backend.py`

- [ ] **Step 3: Implement bounded backend queries and deterministic scoring**

Score same run/cycle, shared provenance/artifact, ontology compatibility, temporal proximity, and neighbor overlap. Return score factors with each candidate; do not use an LLM in this task.

- [ ] **Step 4: Verify focused tests pass**

Run: `.venv/bin/python -m pytest -q tests/unit/test_knowledge_relation_reconciliation.py tests/unit/test_knowledge_graph_backend.py`

- [ ] **Step 5: Commit**

```bash
git add knowledge/graph_backend.py knowledge/ontology/registry.py knowledge/relation_reconciliation.py tests/unit/test_knowledge_relation_reconciliation.py tests/unit/test_knowledge_graph_backend.py
git commit -m "feat: detect knowledge graph relation gaps"
```

### Task 3: Shared Priority-aware LLM Lease

**Files:**
- Create: `backends/llm_lease.py`
- Modify: `agents/base_agent.py`
- Modify: `orchestrator/langgraph_runtime.py`
- Modify: `app/bootstrap.py`
- Test: `tests/unit/test_llm_lease.py`
- Test: `tests/unit/test_model_router.py`
- Test: `tests/unit/test_langgraph_runtime.py`

**Interfaces:**
- Produces: `LLMLeaseCoordinator.acquire(priority: int, owner: str, *, wait: bool = True)` async context manager.
- Priorities: Guardian `0`, active workflow `10`, operator chat `20`, relation reconciliation `30`.
- Adds `AgentContext.llm_lease` and optional `priority`/`owner` parameters to internal completion routing while preserving existing call signatures.
- Produces: `AgentContext.selected_model_loaded(task_type) -> Awaitable[bool]` without calling `prepare_model()`.

- [ ] **Step 1: Write failing scheduling tests**

```python
@pytest.mark.asyncio
async def test_higher_priority_waiter_runs_before_background_waiter():
    lease = LLMLeaseCoordinator()
    order = await exercise_waiters(lease, priorities=[30, 10])
    assert order == [10, 30]

@pytest.mark.asyncio
async def test_background_readiness_does_not_load_model():
    assert await context.selected_model_loaded("knowledge_relation") is False
    assert backend.prepare_calls == []
```

- [ ] **Step 2: Run tests and verify they fail for missing lease behavior**

Run: `.venv/bin/python -m pytest -q tests/unit/test_llm_lease.py tests/unit/test_model_router.py tests/unit/test_langgraph_runtime.py`

- [ ] **Step 3: Implement the coordinator and integrate both AgentContext paths**

Use an `asyncio.Condition`, monotonic sequence numbers, and a priority heap. Existing calls use their current behavior inside the lease. Background readiness inspects `managed_model_statuses()` when available and treats unmanaged remote APIs as available without invoking model loading.

- [ ] **Step 4: Verify routing and runtime tests pass**

Run: `.venv/bin/python -m pytest -q tests/unit/test_llm_lease.py tests/unit/test_model_router.py tests/unit/test_langgraph_runtime.py`

- [ ] **Step 5: Commit**

```bash
git add backends/llm_lease.py agents/base_agent.py orchestrator/langgraph_runtime.py app/bootstrap.py tests/unit/test_llm_lease.py tests/unit/test_model_router.py tests/unit/test_langgraph_runtime.py
git commit -m "feat: coordinate prioritized llm access"
```

### Task 4: LLM Proposal, Validation, Promotion, and Background Worker

**Files:**
- Modify: `backends/prompt_registry.py`
- Modify: `configs/models.yaml`
- Create: `knowledge/reconciliation_service.py`
- Modify: `knowledge/service.py`
- Modify: `agents/knowledge_agent.py`
- Modify: `app/main.py`
- Test: `tests/unit/test_knowledge_reconciliation_service.py`
- Test: `tests/unit/test_knowledge_agent.py`

**Interfaces:**
- Produces: `KnowledgeReconciliationService.scan_gaps()`, `reconcile_batch()`, `re_evaluate()`, `approve()`, `revise_and_approve()`, `reject()`, and `defer()`.
- Uses task route `knowledge_relation` with strict JSON output and one selected target from the supplied candidate IDs.
- Produces automatic promotion only when all confirmed thresholds and validators pass.
- Adds app-owned `KnowledgeReconciliationWorker.start()`, `wake()`, `status()`, and `shutdown()`.

- [ ] **Step 1: Write failing proposal and promotion tests**

```python
@pytest.mark.asyncio
async def test_medium_confidence_proposal_waits_for_operator(service):
    result = await service.reconcile_batch(llm=llm_response(confidence=0.82), limit=1)
    assert result.proposals[0].status == "pending"
    assert service.knowledge_service.ingest_calls == []

@pytest.mark.asyncio
async def test_high_confidence_proposal_uses_knowledge_ingest(service):
    result = await service.reconcile_batch(llm=llm_response(confidence=0.95), limit=1)
    assert result.proposals[0].status == "approved"
    assert service.knowledge_service.ingest_calls[0]["relationship_intents"]
```

- [ ] **Step 2: Run focused tests and verify expected failures**

Run: `.venv/bin/python -m pytest -q tests/unit/test_knowledge_reconciliation_service.py tests/unit/test_knowledge_agent.py`

- [ ] **Step 3: Implement strict parsing, validation, promotion, and worker lifecycle**

The worker is woken after successful Knowledge ingest, processes at most 10 nodes, acquires priority `30`, skips when the selected model is unloaded, and records degraded status without raising into the experiment loop.

- [ ] **Step 4: Verify service and Knowledge Agent tests pass**

Run: `.venv/bin/python -m pytest -q tests/unit/test_knowledge_reconciliation_service.py tests/unit/test_knowledge_agent.py`

- [ ] **Step 5: Commit**

```bash
git add backends/prompt_registry.py configs/models.yaml knowledge/reconciliation_service.py knowledge/service.py agents/knowledge_agent.py app/main.py tests/unit/test_knowledge_reconciliation_service.py tests/unit/test_knowledge_agent.py
git commit -m "feat: reconcile knowledge relations with selected llm"
```

### Task 5: Relation Review and Graph Edit APIs

**Files:**
- Modify: `app/main.py`
- Modify: `knowledge/reconciliation_service.py`
- Test: `tests/integration/test_knowledge_relation_api.py`

**Interfaces:**
- Adds bounded endpoints under `/api/knowledge/relations/` for status, scan, reconcile, proposals, decisions, approval, revised approval, rejection, defer, and re-evaluation.
- Adds `/api/knowledge/graph/edit/validate` and `/api/knowledge/graph/edit/apply` with graph revision optimistic concurrency.
- Manual edits use `knowledge_graph_edit_decision.v1`; accepted semantic changes enter `KnowledgeService.ingest()`.

- [ ] **Step 1: Write failing API contract tests**

```python
def test_revised_approval_rejects_new_target_node(client):
    response = client.post("/api/knowledge/relations/p-1/revise-approve", json={
        "target_id": "invented:node", "relation_type": "OBSERVED_BY", "rationale": "manual correction"
    })
    assert response.status_code == 409

def test_graph_edit_apply_requires_matching_revision(client):
    response = client.post("/api/knowledge/graph/edit/apply", json={"graph_revision": "stale", "changes": []})
    assert response.status_code == 409
```

- [ ] **Step 2: Run API tests and verify missing routes fail**

Run: `.venv/bin/python -m pytest -q tests/integration/test_knowledge_relation_api.py`

- [ ] **Step 3: Implement request models, bounded routes, and conflict responses**

Use existing graph/service factories, no arbitrary query payloads, no direct backend mutation, and explicit operator identity from the local runtime context.

- [ ] **Step 4: Verify API tests pass**

Run: `.venv/bin/python -m pytest -q tests/integration/test_knowledge_relation_api.py`

- [ ] **Step 5: Commit**

```bash
git add app/main.py knowledge/reconciliation_service.py tests/integration/test_knowledge_relation_api.py
git commit -m "feat: expose knowledge relation review api"
```

### Task 6: Knowledge Workspace Relation Review and Edit Mode

**Files:**
- Modify: `web/templates/knowledge.html`
- Modify: `web/static/knowledge.js`
- Modify: `web/static/knowledge.css`
- Modify: `tests/integration/test_knowledge_workspace.py`
- Modify: `tests/ui/knowledge_workspace_browser_audit.py`

**Interfaces:**
- Adds `Relation Review` tab with summary, queue, graph context, decision controls, and history.
- Adds explicit `VIEW / EDIT` mode switch and draft toolbar to Graph Explorer.
- Pending proposals render as amber dashed edges; drafts never alter the accepted graph rendering until apply succeeds.

- [ ] **Step 1: Write failing static and browser contract assertions**

```python
for required in [
    'data-knowledge-tab="relations"',
    'id="knowledge-relation-queue"',
    'id="knowledge-edit-mode"',
    'id="knowledge-edit-validate"',
    'id="knowledge-edit-apply"',
]:
    assert required in html
```

- [ ] **Step 2: Run workspace tests and verify missing controls fail**

Run: `.venv/bin/python -m pytest -q tests/integration/test_knowledge_workspace.py`

- [ ] **Step 3: Implement the responsive workspace UI**

Preserve current visual language, add keyboard-accessible controls, keep View Mode default, persist unsaved drafts in browser session storage, and disable apply until server validation succeeds.

- [ ] **Step 4: Run static tests and 1920 x 1080 Selenium audit**

Run: `.venv/bin/python -m pytest -q tests/integration/test_knowledge_workspace.py`

Run: `.venv/bin/python tests/ui/knowledge_workspace_browser_audit.py --base-url http://127.0.0.1:7860 --screenshot artifacts/ui/knowledge_relation_workspace_1920x1080.png`

- [ ] **Step 5: Commit**

```bash
git add web/templates/knowledge.html web/static/knowledge.js web/static/knowledge.css tests/integration/test_knowledge_workspace.py tests/ui/knowledge_workspace_browser_audit.py
git commit -m "feat: add knowledge relation review workspace"
```

### Task 7: Live GUI and ATT Reconciliation State

**Files:**
- Modify: `app/main.py`
- Modify: `app/controller.py`
- Modify: `web/static/live_runtime.js`
- Test: `tests/integration/test_knowledge_api.py`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Knowledge Agent report exposes examined, proposed, auto-approved, pending, rejected/deferred, and worker status.
- ATT receives one aggregated review item linking to `/knowledge#relations`.
- Relation review state never blocks stage completion or physical-device handoff.

- [ ] **Step 1: Write failing report and ATT aggregation tests**

```python
assert report["role_specific"]["relation_reconciliation"]["pending"] == 3
assert len([item for item in attention if item["source"] == "knowledge_relation_review"]) == 1
```

- [ ] **Step 2: Run focused tests and verify failures**

Run: `.venv/bin/python -m pytest -q tests/integration/test_knowledge_api.py tests/integration/test_live_gui_runtime_layout.py`

- [ ] **Step 3: Implement compact report state and aggregated ATT mapping**

Use persisted reconciliation status as the source of truth. Do not poll or rerender the entire Knowledge report when only counts change.

- [ ] **Step 4: Verify focused tests pass**

Run: `.venv/bin/python -m pytest -q tests/integration/test_knowledge_api.py tests/integration/test_live_gui_runtime_layout.py`

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/controller.py web/static/live_runtime.js tests/integration/test_knowledge_api.py tests/integration/test_live_gui_runtime_layout.py
git commit -m "feat: surface knowledge relation review state"
```

### Task 8: Documentation and Full Verification

**Files:**
- Modify: `docs/knowledge/knowledge_graph_operations.ko.md`
- Modify: `docs/agents/knowledge_agent_self_evolution_runtime_guideline.md`
- Modify: `docs/runtime/current_code_snapshot.md`
- Modify: `README.md`
- Test: `tests/unit/test_documentation_validation.py`

**Interfaces:**
- Documents operator review, edit mode, LLM scheduling, persistence, recovery, and exact API/GUI behavior.

- [ ] **Step 1: Update current-state and operator documentation only after implementation exists**

Document View/Edit Mode, Relation Review actions, automatic thresholds, background lease priority, unloaded-model behavior, Neo4j recovery, and audit locations.

- [ ] **Step 2: Run focused Knowledge test suite**

Run: `.venv/bin/python -m pytest -q tests/unit/test_knowledge_*.py tests/integration/test_knowledge_*.py`

- [ ] **Step 3: Run routing and Live GUI regressions**

Run: `.venv/bin/python -m pytest -q tests/unit/test_model_router.py tests/unit/test_langgraph_runtime.py tests/integration/test_live_gui_runtime_layout.py`

- [ ] **Step 4: Validate documentation and browser evidence**

Run: `.venv/bin/python scripts/validate_documentation.py`

Run: `.venv/bin/python -m pytest -q tests/unit/test_documentation_validation.py`

Run: `.venv/bin/python tests/ui/knowledge_workspace_browser_audit.py --base-url http://127.0.0.1:7860 --screenshot artifacts/ui/knowledge_relation_workspace_1920x1080.png`

- [ ] **Step 5: Verify working-tree scope and commit documentation**

```bash
git diff --check
git status --short
git add README.md docs/knowledge/knowledge_graph_operations.ko.md docs/agents/knowledge_agent_self_evolution_runtime_guideline.md docs/runtime/current_code_snapshot.md
git commit -m "docs: document knowledge relation reconciliation"
```
