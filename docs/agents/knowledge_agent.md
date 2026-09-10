---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, reviewer, developer, operator, maintainer]
scope: [agents, knowledge, ontology, markdown_memory, scoped_rag, self_evolution, manual_rag]
summary: Ontology-guided Markdown knowledge, source-backed LLM curation, scoped retrieval and preserved research-memory contracts.
source_of_truth:
  - agents/knowledge_agent.py
  - agents/knowledge_decision.py
  - knowledge/markdown_memory.py
  - knowledge/markdown_runtime.py
  - knowledge/http_api.py
  - knowledge/manuals/service.py
  - knowledge/ontology
  - utils/agent_artifact_archive.py
  - graphs/modules/knowledge/module.yaml
last_verified: 2026-09-10
verified_against: working-tree-2026-09-10
related_docs:
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/knowledge/markdown_memory_operations.ko.md
  - docs/knowledge/manual_rag_knowledge.ko.md
  - docs/agents/knowledge_agent_self_evolution_runtime_guideline.md
  - docs/superpowers/specs/2026-09-10-knowledge-markdown-memory-design.md
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
supersedes: []
---

# Knowledge Agent Reference

## Status at a Glance

- Runtime status: Implemented — ontology-guided Markdown memory and existing typed records
- LLM decision layer: Implemented / API and local vLLM verified
- Physical effect: None
- Primary handoff: `knowledge_context.v1` → BO and downstream context consumers
- Live hardware validation: Not applicable to Knowledge; no new physical validation claimed
- Known gap: Retrieval quality and scientific benefit have no held-out comparative benchmark

## Overview and Responsibilities

Knowledge turns execution evidence into reusable, source-backed context. Its
LLM decides what is worth retaining, how to classify it, which scoped records
to read, and whether evidence supports a useful handoff. Numerical observations
remain Analysis-owned; Knowledge does not reconstruct or optimize their values.

| Owned by Knowledge | Preserved outside its authority |
|---|---|
| Markdown knowledge, ontology-guided classification and scoped retrieval | Core ontology definitions and experimental settings |
| Source citations, evidence status and append-only note revisions | Original logs, artifacts, metrics and objective evaluations |
| Typed memory, patterns, performance and Evolution evidence packs | BO candidate generation and device execution |
| Local decision/tool trace and explicit evidence gaps | Orchestrator stage transitions and Evolution activation |

The active Knowledge Graph, Neo4j synchronization, Graphify import and relation
reconciliation paths are retired. Ontology classes and relation definitions are
still present: a vocabulary is not an instantiated knowledge graph. Existing
historical graph files and offline utilities are left untouched.

### Five-Area Responsibility Map

These are responsibility areas, not five new runtime stages.

| Area | Responsibility | Authority boundary |
|---|---|---|
| High-Level Control | LLM judges reusable knowledge, relevant scope-bound evidence and qualified publication | Does not alter measurements, objectives or global routing |
| Middle-Level Control | Collect evidence; run the bounded tool loop; assemble existing records and context | Tool validation and output assembly remain code-owned |
| Low-Level Control | Atomic Markdown revisions, search/detail reads, JSONL and local audit append | No device tool, graph backend or model-server startup |
| Guardian / Safety | Validate identity, ontology, sources, scope, lifecycle and tool arguments | Reject unsupported writes or scope expansion; preserve raw evidence |
| Knowledge / Evidence | Keep sources, applicability, observation/interpretation distinction and tool trace | Derived notes are not new measurements or causal proof |

## Closed-Loop Position and Handoffs

![Knowledge: terminal archives feed observations; Analysis feeds LLM curation; context goes to BO](assets/figures/knowledge_01_closed_loop_handoffs.svg)

**Figure Knowledge-1.** Code-inspection architecture view, 2026-09-10. The normal
stage remains Analysis → Knowledge → BO. Terminal archive intake is a separate,
deterministic preservation hook and cannot replay an agent.

| Direction | Input/output | Existing owner or consumer |
|---|---|---|
| In | Analysis objective, uncertainty, metrics, evaluation and artifact references | Analysis |
| In | Terminal completed/failed/cancelled execution manifest and result | Existing agent archive wrapper |
| In | Markdown candidates and selected project-document chunks | Scoped retrieval |
| Out | `knowledge_context.v1`: summary, scope, selected records, citations, decision | BO and context consumers |
| Out | `knowledge_report.v1`, typed memory/pattern/performance records | Reports, workspace and local memory |
| Out | `evolution_proposal.v1` and evidence packs | Existing operator-reviewed Evolution path |

## Internal Workflow

1. Persist a copy of current Analysis intake before any LLM call.
2. Freeze source identities and caller scope; expose only evidence inspection initially.
3. Let the LLM inspect, search, read, classify/write, and publish using agent-local tools.
4. Preserve existing numerical memory, provenance, patterns and performance records.
5. Build existing BO/Evolution context and append a local ontology-validated audit event.
6. Save the decision/report; the original archive wrapper preserves the terminal result.

![Knowledge: LLM tools operate behind scope and provenance validation with append-only storage](assets/figures/knowledge_02_execution_effect_boundary.svg)

**Figure Knowledge-2.** The LLM selects semantic actions; deterministic code owns
their validation and storage effects. The separate archive hook records observed
execution outcomes even if a run never reaches the Knowledge stage.

### Decision and Prompt Contract

The normal path calls `ctx.complete("knowledge_query", ...)` through ATR's
registered API or local vLLM routing. Every response is one JSON object:

```json
{"tool": "search_knowledge", "arguments": {"query": "export validation", "scope": {"agent_id": "equipment_agent"}, "top_k": 6}}
```

The prompt supplies the goal, run/cycle identity, allowed ontology classes,
allowed corpus/scope, phase-specific tool schemas and actual previous tool
observations. It asks for reusable evidence rather than general commentary:

| Prompt requirement | Enforced effect |
|---|---|
| Inspect before deciding | Only inspection is offered in the initial phase |
| Search excerpts, then read selected records | Unread search IDs cannot be cited |
| Narrow scope without replacing conditions | The same validated filters govern search and detail |
| Distinguish observation, derived interpretation and hypothesis | LLM writes cannot claim `evidence_kind=observed` |
| Reuse existing evidence instead of repeated writes | At most one curated note per decision |
| State insufficient or conflicting evidence explicitly | Publication without a note requires a reason |
| Keep scientific data and command ownership unchanged | No numeric-edit, ontology-edit or device tool exists |

This is a bounded decision layer, not an LLM implementation of file I/O or a
replacement for Analysis/BO. It can withhold new knowledge when evidence is
insufficient. A failed decision is reported as unsuccessful rather than
presented as successful model reasoning.

### Agent-Local Tools

| Tool | Input | Effect and receipt |
|---|---|---|
| `inspect_evidence` | Empty arguments | Read frozen current source identities and content |
| `search_knowledge` | Query, optional narrower scope, top_k, corpus | Ranked metadata/excerpts; no full bodies |
| `read_knowledge` | ID previously returned by search | Read full selected record within the same scope |
| `write_knowledge_note` | Title/body, ontology class, source IDs, kind, tags | Validated atomic Markdown revision receipt |
| `publish_context` | Summary, source IDs, explicit no-note reason when applicable | Accepted cited context or evidence-gap report |

These tools are dispatched inside Knowledge; the module does not register new
bridge commands. Existing project-document retrieval remains a separate corpus.
Manual RAG retains its own registry, query and citation contract.

## Storage, Scope and Lifecycle

```text
memory/knowledge/markdown/
  <run_id>/<cycle_id>/<agent_id>/<record_id>/revision-000001.md
memory/knowledge/markdown_jobs/<job_id>.json
memory/knowledge/*.jsonl                         existing typed memory
runs/<run_id>/knowledge/intake_<loop>_<hash>.json pre-LLM immutable source snapshot
runs/<run_id>/knowledge/knowledge_decision.json   current full tool trace
runs/<run_id>/knowledge/knowledge_report.json     current report
runs/<run_id>/runtime/loops/<loop>/<agent>/<attempt>/
  manifest.json, result.json, files/...          existing per-attempt archive
```

Current per-run report aliases remain compatible. The archive wrapper snapshots
each execution separately; Markdown identity also includes run, cycle, agent and
event, so a similar failure in a later cycle is retained independently.

| Field | Meaning |
|---|---|
| run_id / cycle_id / agent_id / event_id | Stable event identity; retries deduplicate |
| ontology_type / ontology_version | Existing ontology vocabulary and version |
| source_refs | Traceable original evidence locations |
| evidence_kind | `observed`, `derived`, or `hypothesis` |
| fidelity | `measured`, `simulated`, `virtual`, or `unknown`; not inferred from test mode |
| tags / applicability | Search classification and exact experimental conditions |
| status / revision / content_hash | Lifecycle and immutable content lineage |

Search filters are conjunctive. Scalar/list fields allow exact run, cycle,
agent, ontology type, fidelity and status selection; tags require every listed
tag and applicability requires every specified key/value. Explicit empty lists
match nothing. Unknown filters are rejected. Default status is `valid`.

Lifecycle supports `valid`, `needs_review`, and `superseded`. Status changes
require a reason and create a new revision. Supersession requires a distinct
valid replacement with matching ontology class and applicability. Producer
retries do not reactivate reviewed/superseded records. Invalid newest revisions
quarantine the record instead of exposing an older valid version.

The in-memory index is rebuildable from Markdown and refreshes changed files
incrementally. It is not an external vector database. Historical archive intake
is an explicit, bounded background job, not a startup scan or a new agent run.

## Tools, APIs and Connections

![Knowledge API connections: workspace to local Markdown, ontology and preserved manual/typed stores](assets/figures/knowledge_03_api_connection_architecture.svg)

**Figure Knowledge-3.** Existing FastAPI/workspace entry points reach local
Knowledge stores. The registered model route is used only by the agent decision
layer; history intake does not invoke it.

| Surface | Method / path | Contract |
|---|---|---|
| Status | GET `/api/knowledge/status` | Markdown count/index state; graph explicitly retired |
| Query | POST `/api/knowledge/markdown/query` | `{query, scope, top_k}` → candidate excerpts |
| Detail | POST `/api/knowledge/markdown/read` | `{record_id, scope}` → scoped record, or 404 |
| Default detail | GET `/api/knowledge/markdown/{record_id}` | Valid record only |
| Lifecycle | POST `/api/knowledge/markdown/{record_id}/status` | Status/reason/replacement → immutable receipt |
| History intake | POST `/api/knowledge/markdown/intake` | Run, limit, cursor → queued job |
| Intake progress | GET `/api/knowledge/markdown/intake/{job_id}` | Persisted state and per-file results |
| Preserved | `/api/knowledge/ontology*`, `/activity`, typed memory/context/Evolution APIs | Existing vocabulary and evidence contracts |
| Manual RAG | `/api/knowledge/manuals/status`, `/ingest`, `/query` | Corpus, source hashes and page citations |
| Retired | `/graph*`, `/graphify*`, `/relations*`, `/manuals/graph` | HTTP 410; no graph factory or worker |

The Knowledge workspace replaces graph-specific tabs with Markdown search and
detail. Memory, Ontology and Manual RAG remain. The main dashboard links the same
`/knowledge` route and reads Markdown status.

## Safety, Modes and Recovery

- Original Analysis numbers and objective lineage are copied, not LLM-generated.
- Terminal archive intake is idempotent, has no device/model tool, and records
  cancellation separately from evidence of equipment failure.
- Markdown persistence is local and append-only; an intake error does not replace
  the original agent outcome.
- Normal operation requires a valid model decision. Explicit offline verification
  uses the same tool dispatcher but is labeled `llm_used=false`.
- `knowledge_settings` in run metadata accepts scope, corpora,
  `decision_call_timeout_s` (default 300) and `decision_max_steps` (default 8).
  Core experimental settings and bridges are unchanged.
- Evolution proposals remain recommendations; approval and activation retain
  their existing owners.

## Artifacts and Verification

The 2026-09-10 focused regression run passed **210 tests** (14 existing warnings),
including Knowledge storage/decisions/archives, manual citations, preserved
ontology and typed APIs, BO, Evolution, objective lineage and the nonactuating
two-cycle busy-FEM-boundary integration. This is a targeted set, not the entire
repository test suite.

Workspace QA used an isolated FastAPI fixture and existing Playwright Chromium
at 1440×1000 and 390×844. Page identity, meaningful content, filter → excerpt →
same-scope detail, invalid/no-match states, preserved tabs/manual citations and
intake job reload passed; console warnings/errors and retired graph requests
were empty. The fixture was stopped after verification. Lifecycle mutation
remains API-only; the workspace displays and filters lifecycle status.

Ten changed governed documents passed their focused validation. The full
documentation manifest still reports pre-existing Windows bridge/PLC document
governance errors in files outside this change.

| Actual provider | Classified note | Scoped reuse | Insufficient evidence |
|---|---|---|---|
| API `gpt-5.5` | Pass · 16.876 s | Pass · 11.549 s | Pass · 5.295 s |
| Registered vLLM `gemma4:31b` | Pass · 27.746 s | Pass · 26.820 s | Pass · 11.214 s |

Times cover each complete multi-call decision. All six cases used real model
responses and actual temporary Markdown operations; original synthetic values
were unchanged. [Sanitized verification artifact](assets/verification/knowledge_decisions_2026-09-10.json)
records models, action sequences, note/citation counts and limits.
The executable provider probe is
[`verify_knowledge_decisions.py`](../../scripts/verify_knowledge_decisions.py).

Tests exercise real temporary Markdown files, scoped reads, lifecycle/retries,
archive preservation, graph retirement, manual citations, Knowledge/BO handoff,
and the existing nonactuating two-cycle integration. Provider probes use
synthetic evidence with empty device-tool registries and no model-server startup.
They do not establish retrieval quality, causal scientific benefit, or a new
physical closed-loop result.

## Related Documents

- [Markdown Knowledge Operations](../knowledge/markdown_memory_operations.ko.md)
- [Manual RAG Operations](../knowledge/manual_rag_knowledge.ko.md)
- [Knowledge/Self-Evolution Guideline](knowledge_agent_self_evolution_runtime_guideline.md)
- [Agent Matrix](agent_api_connection_matrix.md)
- [Analysis](analysis_agent.md) · [BO](bo_agent.md)
