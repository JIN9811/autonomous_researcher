# Knowledge Agent Neo4j·Graphify Ontology Architecture Design

## 1. Document Purpose

This document defines the production architecture for upgrading ATR's Knowledge Agent from file-backed memory plus an optional graph mirror into a Neo4j-centered research knowledge system.

The implementation must preserve the existing autonomous loop, typed Knowledge contracts, Live/Test/Virtual bridge behavior, BO handoff, Guardian authority, and append-only evidence history.

The target runtime role is:

```text
Knowledge Agent
= Ontology Validator
+ Runtime Knowledge Graph Writer
+ Graph RAG Retriever
+ Failure/Success Pattern Miner
+ BO/Guardian Context Provider
+ Graphify Project Knowledge Linker
```

## 2. Confirmed Decisions

The following decisions are fixed for this design.

1. Neo4j is the primary operational Knowledge query store.
2. JSONL remains an append-only audit and disaster-recovery ledger.
3. Every graph mutation is written to JSONL before Neo4j.
4. Neo4j outage must not discard records or stop a safe experiment loop.
5. Failed Neo4j writes remain in a durable outbox and are replayed after recovery.
6. Ontology and Knowledge Graph are separate logical layers in one Neo4j database.
7. The core ontology is versioned and cannot be changed automatically by an LLM or Agent.
8. Ontology extensions require a proposal, validation, Guardian review, and operator approval.
9. Graphify represents project code, documentation, modules, tests, and architecture.
10. Runtime experiment entities are connected to Graphify project entities by stable namespaces and explicit relationships.
11. Raw high-volume data remains in files; Neo4j stores metadata, summaries, hashes, and provenance links.
12. LLMs may request allowlisted graph query modes but may not execute arbitrary Cypher.

## 3. Current Baseline

The repository already contains:

- `agents/knowledge_agent.py`: typed experiment memory, performance records, failure/success patterns, evolution evidence packs, and graph mirroring.
- `knowledge/graph_backend.py`: disabled, JSON, and optional Neo4j backends.
- `knowledge/graphify_bridge.py`: deterministic project scan plus optional external Graphify ingestion.
- `knowledge/graph_importer.py`: project/runtime memory import adapters.
- `memory/knowledge/graphify/`: Graphify-compatible graph artifacts.
- `memory/knowledge/graph_backend/knowledge_graph.json`: local graph backend artifact.
- Graph health/query/scan/import APIs and CLI commands.

The current gap is not basic graph export. The active Knowledge Agent writes typed runtime memory and mirrors it to a selected backend, but does not consistently query Graphify and runtime graph relationships before making Knowledge, BO, Guardian, and orchestration decisions. The graph backend is also disabled by default in the current environment.

## 4. Layered Architecture

```text
Runtime / Agents / Devices
        |
        v
Knowledge Event Normalizer
        |
        +--> JSONL Audit Ledger + Raw Artifacts
        |
        +--> Durable Neo4j Outbox
                    |
                    v
               Neo4j Writer
                    |
         +----------+----------+
         |                     |
  Ontology Layer       Knowledge Graph Layer
  versioned rules      runtime instances
         |                     |
         +---- INSTANCE_OF ----+
                    |
              Graph Query/RAG
                    |
     Knowledge -> BO / Guardian / Orchestrator
```

### 4.1 Ontology Layer

The Ontology Layer defines:

- allowed classes;
- allowed relationships;
- required properties;
- relationship domain and range;
- cardinality;
- lifecycle state transitions;
- evidence and confidence requirements;
- ontology version and migration lineage;
- extension proposal and approval state.

Neo4j labels:

```text
OntologyVersion
OntologyClass
OntologyRelation
OntologyConstraint
OntologyChangeProposal
```

### 4.2 Knowledge Graph Layer

The Knowledge Graph Layer stores actual runtime and research instances:

```text
Run
Cycle
Stage
AgentExecution
Handoff
ResearchObjective
Experiment
Candidate
ParameterSet
Specimen
Device
DeviceSession
Command
DeviceState
Calibration
Observation
Metric
AnalysisResult
Decision
Recommendation
Artifact
Failure
Incident
GuardianGate
Approval
Interlock
OptimizationStudy
BOIteration
Acquisition
SurrogateModel
Policy
Model
Skill
Tool
PromptVersion
KnowledgeClaim
FailurePattern
SuccessPattern
EvidencePack
```

Every runtime instance must connect to an ontology class through `INSTANCE_OF`.

### 4.3 Evidence Layer

The Evidence Layer remains file-backed and immutable where practical. It stores:

- JSONL event records;
- images and videos;
- STL and G-code;
- device logs;
- high-frequency telemetry;
- LLM raw responses or reasoning traces when retention is allowed;
- complete Agent reports;
- model, policy, and training artifacts.

Neo4j stores only bounded metadata and references:

- approved path or artifact identifier;
- SHA-256;
- MIME type;
- byte size;
- schema;
- producer;
- time range;
- summary statistics;
- provenance edges.

### 4.4 Graphify Project Layer

Graphify extracts repository-level structure:

```text
Agent -> Module -> Handler -> Tool -> Config -> Document -> Test
```

The project graph is linked to runtime entities through:

```text
AgentExecution INSTANCE_OF Agent
Agent IMPLEMENTED_BY Module
Module DECLARED_IN File
Module DOCUMENTED_BY Document
Module VERIFIED_BY Test
Failure AFFECTS Module
Decision JUSTIFIED_BY Document
Artifact GENERATED_BY Tool
```

## 5. Repository and Runtime Storage

### 5.1 Versioned Definitions

```text
knowledge/
├── ontology/
│   ├── registry.py
│   ├── validator.py
│   ├── migration.py
│   ├── atr_core.v1.yaml
│   ├── relation_rules.v1.yaml
│   ├── validation_shapes.v1.yaml
│   └── extensions/
│       └── approved/
├── event_normalizer.py
├── audit_ledger.py
├── durable_outbox.py
├── neo4j_repository.py
├── graph_sync_worker.py
├── graph_retrieval.py
├── graph_rag.py
├── graph_query_planner.py
├── graph_reconciliation.py
└── ontology_proposals.py

knowledge/migrations/
├── v1_constraints.cypher
└── v1_indexes.cypher
```

### 5.2 Append-Only Runtime Memory

```text
memory/knowledge/
├── ledger/
│   ├── events/YYYY/MM/DD/*.jsonl
│   ├── entities/YYYY/MM/*.jsonl
│   └── relationships/YYYY/MM/*.jsonl
├── outbox/
│   ├── pending/
│   ├── acknowledged/
│   └── dead_letter/
├── ontology/
│   ├── active_version.json
│   ├── proposals.jsonl
│   └── migration_history.jsonl
├── graphify/
│   ├── project_graph.json
│   ├── project_graph.html
│   └── import_manifest.json
└── graph_backend/
    ├── sync_state.json
    └── reconciliation_report.json
```

### 5.3 Per-Run Evidence

```text
runs/<run_id>/knowledge/
├── knowledge_report.json
├── graph_ingest_manifest.json
├── graph_sync_receipt.json
├── graph_context_snapshot.json
└── ontology_validation_report.json
```

Existing typed JSONL records remain supported and are migrated through adapters instead of being deleted or rewritten in place.

## 6. Identifier and Namespace Rules

Stable identifiers prevent Graphify project entities, ontology definitions, runtime entities, and artifacts from colliding.

```text
ontology:version:atr-core-1.0.0
ontology:class:Specimen
ontology:relation:GENERATED_BY

runtime:run:<run_id>
runtime:cycle:<run_id>:<cycle_number>
runtime:agent_execution:<execution_id>
runtime:specimen:<specimen_id>
runtime:device_session:<session_id>

project:file:agents/analysis_agent.py
project:module:analysis
project:agent:analysis

artifact:sha256:<digest>
event:<event_id>
```

Required common runtime properties:

```text
entity_id
run_id
cycle_id
schema_version
ontology_version
created_at
updated_at
status
```

All event and relationship identifiers must be deterministic or protected by an idempotency key.

## 7. Knowledge Event Contract

All graph-bound records use `knowledge_event.v1`.

```json
{
  "schema": "knowledge_event.v1",
  "event_id": "evt-...",
  "idempotency_key": "sha256:...",
  "run_id": "run-...",
  "cycle_id": "cycle-3",
  "source_agent": "analysis_agent",
  "event_type": "analysis.completed",
  "occurred_at": "2026-08-08T00:00:00Z",
  "entity_refs": [],
  "relationship_intents": [],
  "artifact_refs": [],
  "payload_summary": {},
  "ontology_version": "atr-core-1.0.0",
  "provenance": {}
}
```

### 7.1 Required Event Families

```text
run.created
run.completed
run.failed
cycle.started
cycle.completed

agent.started
agent.completed
agent.failed
agent.handoff

tool.requested
tool.completed
tool.failed

device.connected
device.command_dispatched
device.command_completed
device.faulted

specimen.designed
specimen.validated
specimen.sliced
specimen.printed
specimen.ejected
specimen.transferred
specimen.tested
specimen.analyzed

guardian.approved
guardian.blocked
guardian.incident

bo.candidate_proposed
bo.observation_received
bo.surrogate_updated

ontology.proposal_created
ontology.version_applied
```

## 8. Durable Write Protocol

Every graph mutation follows this order:

1. Normalize the runtime input into `knowledge_event.v1`.
2. Validate schema, ontology class, relation domain/range, cardinality, and state transition.
3. Append the event to JSONL.
4. Flush and `fsync` the audit record.
5. Create a durable outbox entry through atomic file replacement.
6. Execute a bounded Neo4j transaction.
7. Write a sync receipt.
8. Move the outbox entry to `acknowledged`.

### 8.1 Neo4j Failure

If Neo4j is unavailable:

- JSONL remains authoritative evidence;
- pending outbox entries remain durable;
- the safe experiment loop may continue in degraded mode;
- the Knowledge report exposes sync lag and the last successful write;
- a background worker retries after Neo4j recovery;
- Guardian-related unsynchronized records create an Operator Attention warning.

### 8.2 Repeated Failure

After the configured retry limit:

- move the item to `dead_letter`;
- retain payload hash, failure type, attempts, and last error;
- emit a Guardian/Operator Attention event;
- do not silently discard or mark the event synchronized.

### 8.3 Idempotency

- Nodes use `MERGE` on stable `entity_id`.
- Events use a unique `event_id` and `idempotency_key`.
- Relationships use a deterministic `relation_id`.
- Replaying the same outbox entry must not create duplicate logical entities or edges.

## 9. ATR Core Ontology v1

### 9.1 Classes

| Domain | Classes |
|---|---|
| Execution | `Run`, `Cycle`, `Stage`, `AgentExecution`, `Handoff` |
| Research | `ResearchObjective`, `Experiment`, `Candidate`, `Specimen`, `ParameterSet` |
| Results | `Observation`, `Metric`, `AnalysisResult`, `Decision`, `Recommendation` |
| Devices | `Device`, `DeviceSession`, `Command`, `DeviceState`, `Calibration` |
| Software | `Agent`, `Module`, `Tool`, `Model`, `Policy`, `Skill`, `PromptVersion` |
| Evidence | `Artifact`, `Event`, `Provenance`, `EvidencePack` |
| Safety | `GuardianGate`, `Approval`, `Interlock`, `Incident`, `Failure` |
| Optimization | `OptimizationStudy`, `BOIteration`, `Acquisition`, `SurrogateModel` |
| Knowledge | `KnowledgeClaim`, `Constraint`, `FailurePattern`, `SuccessPattern`, `OntologyChangeProposal` |

### 9.2 Relationships

```text
Run CONTAINS Cycle
Cycle EXECUTES AgentExecution
AgentExecution INSTANCE_OF Agent
AgentExecution USES Tool
AgentExecution USES Model
AgentExecution USES Policy
AgentExecution USES Skill
AgentExecution PRODUCES Artifact
AgentExecution PRODUCES Observation
AgentExecution PRODUCES Decision
AgentExecution HANDS_OFF_TO AgentExecution

Experiment REALIZES ResearchObjective
Experiment EVALUATES Candidate
Candidate HAS_PARAMETERS ParameterSet
Candidate GENERATES Specimen
Specimen MANUFACTURED_BY DeviceSession
Specimen OBSERVED_BY Observation
Specimen TESTED_IN DeviceSession
AnalysisResult DERIVED_FROM Observation
AnalysisResult DERIVED_FROM Artifact
Metric DESCRIBES Specimen
Metric DESCRIBES Experiment
Metric DESCRIBES Run

Failure OBSERVED_DURING AgentExecution
Failure OBSERVED_DURING DeviceSession
Failure AFFECTS Agent
Failure AFFECTS Device
Failure AFFECTS Specimen
Failure SUPPORTS FailurePattern
SuccessPattern SUPPORTED_BY Run
SuccessPattern SUPPORTED_BY Artifact
Decision JUSTIFIED_BY EvidencePack
Recommendation CONSTRAINS ParameterSet
Recommendation CONSTRAINS AgentExecution

BOIteration CONSUMES KnowledgeClaim
BOIteration CONSUMES AnalysisResult
BOIteration PROPOSES Candidate
GuardianGate VALIDATES AgentExecution
GuardianGate VALIDATES Command
GuardianGate VALIDATES Decision
Approval AUTHORIZES Command
Approval AUTHORIZES OntologyChangeProposal
```

### 9.3 Cardinality

- A `Run` contains one or more `Cycle` instances.
- A `Cycle` belongs to exactly one `Run`.
- An `AgentExecution` references exactly one `Agent`, `Run`, and `Cycle`.
- An `Artifact` has at least one generating provenance relationship.
- A `Specimen` has exactly one final `ParameterSet` for a given manufactured instance.
- A `Command` belongs to exactly one `DeviceSession` and has one execution principal.
- A `Decision` has at least one `EvidencePack` or an explicit `no_evidence_reason`.
- A `FailurePattern` has at least one observed `Failure` as evidence.
- An `OntologyChangeProposal` cannot become an `OntologyVersion` without approval.

### 9.4 State Transitions

```text
Run:
created -> running -> paused | completed | failed | aborted

AgentExecution:
queued -> preparing -> running -> waiting_operator
       -> completed | blocked | failed | cancelled

DeviceSession:
discovered -> connecting -> ready -> busy
           -> ready | degraded | disconnected | faulted

Specimen:
designed -> validated -> sliced -> queued
         -> printing -> manufactured -> ejected
         -> transferred -> tested -> analyzed -> archived

Command:
proposed -> guardian_checked -> approved
         -> dispatched -> acknowledged -> completed
         -> failed | cancelled

OntologyChangeProposal:
draft -> validated -> guardian_reviewed
      -> operator_approved -> applied | rejected | superseded
```

An invalid transition is not written to the active Knowledge Graph. It is retained in the audit ledger, moved to dead-letter handling, and exposed as a Guardian warning.

## 10. Knowledge Confidence and Claim Lifecycle

Every `KnowledgeClaim`, `FailurePattern`, and `SuccessPattern` requires:

```text
confidence
evidence_count
source_run_ids
artifact_refs
supporting_entity_ids
contradicting_entity_ids
first_observed_at
last_observed_at
ontology_version
validity_status
```

Lifecycle:

```text
provisional -> validated -> contradicted -> retired
```

Rules:

- A result from one run is `provisional` by default.
- Independent repeated evidence or operator approval is required for `validated`.
- Contradictory evidence does not delete the original claim; it creates an explicit contradiction relationship and changes validity state.
- BO, Guardian, and Orchestrator receive confidence and validity state with each claim.

## 11. Neo4j Schema and Indexes

### 11.1 Ontology Nodes

```text
(:OntologyVersion)
(:OntologyClass)
(:OntologyRelation)
(:OntologyConstraint)

(:OntologyVersion)-[:DECLARES]->(:OntologyClass)
(:OntologyVersion)-[:DECLARES]->(:OntologyRelation)
(:OntologyRelation)-[:DOMAIN]->(:OntologyClass)
(:OntologyRelation)-[:RANGE]->(:OntologyClass)
```

### 11.2 Runtime Nodes

Domain nodes carry `KnowledgeEntity` plus a specific label:

```text
(:KnowledgeEntity:Run)
(:KnowledgeEntity:Experiment)
(:KnowledgeEntity:Specimen)
(:KnowledgeEntity:Agent)
(:KnowledgeEntity:Device)
(:KnowledgeEntity:Artifact)
(:KnowledgeEntity:Failure)
```

### 11.3 Constraints and Indexes

Unique:

- `KnowledgeEntity.entity_id`
- `Event.event_id`
- `Artifact.sha256`
- `OntologyVersion.version_id`
- `OntologyClass.class_id`
- `OntologyRelation.relation_type_id`

Indexed:

- `run_id`
- `cycle_id`
- `occurred_at`
- `agent_id`
- `device_id`
- `status`
- `ontology_version`
- `validity_status`

## 12. Graphify Scan and Reconciliation

Graphify does not perform a full repository scan for each experiment cycle.

Scan triggers:

- explicit operator request;
- new Git commit;
- changes under Agent, Module, Tool, graph config, test, or documentation paths;
- ontology version change;
- scheduled maintenance scan.

Flow:

```text
Repository
 -> Graphify extraction
 -> project_graph.json
 -> ATR namespace normalization
 -> Neo4j Project Layer import
 -> previous project graph reconciliation
```

Unchanged files are skipped by content hash. Removed files and modules are retained for provenance with:

```text
active=false
retired_at=<timestamp>
```

Historical runtime nodes must retain links to the project version used during their run.

## 13. Knowledge Agent Runtime Flow

The Knowledge module internal graph becomes:

```text
01 Collect Run Artifacts
02 Normalize Provenance
03 Validate Against Ontology
04 Flush Pending Graph Events
05 Query Similar Experiments
06 Query Failure and Success Paths
07 Query Device and Policy History
08 Build Graph-RAG Context
09 Write Experiment Knowledge
10 Update Failure and Success Patterns
11 Build BO Context
12 Build Guardian Safety Context
13 Build Evolution Evidence Packs
14 Commit Knowledge Claims
15 Emit Knowledge Report
16 Reconcile Neo4j and JSONL
```

The existing output contracts remain compatible:

- `knowledge_context.v1`
- `knowledge_report.v1`
- `evolution_proposal.v1`
- existing typed memory records

New graph fields are additive and schema-versioned.

## 14. Graph RAG

Graph RAG combines:

```text
Graph traversal
+ Typed memory
+ Vector/RAG retrieval
+ Current Orchestrator state
```

Supported query modes:

| Query mode | Purpose |
|---|---|
| `run_context` | Current Run, executions, artifacts, and failures |
| `similar_experiments` | Similar parameters, geometry, devices, and conditions |
| `failure_path` | Failure cause and preceding event paths |
| `success_path` | Repeated successful Agent/Device procedures |
| `specimen_lineage` | Design-to-analysis specimen provenance |
| `device_history` | Device command, fault, state, and calibration history |
| `policy_history` | VLA policy, checkpoint, and result history |
| `bo_context` | Candidate, objective, uncertainty, and observation history |
| `safety_context` | Guardian gates, incidents, approvals, and interlocks |
| `project_context` | Graphify code, docs, module, tool, and test structure |
| `impact_analysis` | Runtime paths affected by a module or ontology change |
| `provenance_trace` | Reverse trace from result to source artifacts |

An LLM emits a bounded `GraphQueryPlan`; the backend validates it and executes predefined Cypher templates. Raw LLM-generated Cypher is forbidden.

## 15. BO Handoff

Knowledge Agent sends BO Agent:

```text
similar_candidates
successful_parameter_regions
failed_parameter_regions
hard_constraints
device_constraints
specimen_constraints
objective_history
uncertainty_history
excluded_regions
evidence_refs
claim_confidence
claim_validity
```

Graph lineage:

```text
BOIteration PROPOSES Candidate
Candidate EVALUATED_BY Experiment
Experiment PRODUCES AnalysisResult
AnalysisResult UPDATES SurrogateModel
```

## 16. Guardian Handoff

Guardian receives:

- similar device incidents;
- repeated failure patterns;
- prior success/failure rate for the proposed command;
- active policy/checkpoint lineage;
- unsynchronized safety events;
- ontology validation failures;
- decisions with insufficient evidence;
- unapproved ontology extensions.

Guardian may approve or block a live command or ontology proposal. It does not delete Knowledge evidence.

## 17. API Contract

### 17.1 Ontology

```text
GET  /api/knowledge/ontology
GET  /api/knowledge/ontology/version
GET  /api/knowledge/ontology/classes
GET  /api/knowledge/ontology/relations
POST /api/knowledge/ontology/validate
GET  /api/knowledge/ontology/proposals
POST /api/knowledge/ontology/proposals
POST /api/knowledge/ontology/proposals/{id}/approve
POST /api/knowledge/ontology/proposals/{id}/reject
```

### 17.2 Graph

```text
GET  /api/knowledge/graph/health
GET  /api/knowledge/graph/stats
GET  /api/knowledge/graph/sync
POST /api/knowledge/graph/reconcile
POST /api/knowledge/graph/query
GET  /api/knowledge/graph/entity/{entity_id}
GET  /api/knowledge/graph/run/{run_id}
GET  /api/knowledge/graph/provenance/{entity_id}
```

### 17.3 Graphify

```text
POST /api/knowledge/graphify/scan
GET  /api/knowledge/graphify/status
POST /api/knowledge/graphify/import
GET  /api/knowledge/graphify/diff
```

No endpoint accepts unrestricted Cypher from the browser or LLM.

## 18. CLI Contract

```bash
atr knowledge graph health
atr knowledge graph stats
atr knowledge graph sync
atr knowledge graph reconcile
atr knowledge graph query --kind similar_experiments

atr knowledge ontology validate
atr knowledge ontology version
atr knowledge ontology proposals
atr knowledge ontology approve <proposal-id>

atr knowledge graphify scan
atr knowledge graphify diff
atr knowledge graphify import
```

GUI and CLI must call the same service layer and return the same state.

## 19. Knowledge Workspace GUI

### 19.1 Runtime Status

- Neo4j connection state;
- active ontology version;
- pending outbox count;
- dead-letter count;
- last successful graph write;
- last Graphify scan;
- graph node and relationship count.

### 19.2 Knowledge Graph Explorer

- Run, Specimen, Agent, Device, Failure, and Artifact-centered subgraphs;
- visual distinction between ontology and instance layers;
- provenance path inspection;
- node detail panel;
- filters for time, Run, Agent, Device, and state.

### 19.3 Memory Board

- recent experiments;
- similar experiments;
- failure patterns;
- success patterns;
- Knowledge Claims;
- contradictory evidence.

### 19.4 Ontology Manager

- active class/relation definitions;
- validation results;
- extension proposals;
- proposal diff;
- Guardian and operator approval state;
- ontology version history.

### 19.5 Sync Operations

- pending outbox;
- retry and reconcile;
- dead-letter inspection;
- JSONL/Neo4j consistency report.

The Live GUI Knowledge report remains a compact run-facing report. It must not duplicate the complete administration workspace.

## 20. Security and Operational Limits

- Exclude `.env`, token, password, connection, credential, and secret files from Graphify.
- Artifact paths must resolve under the project root or explicitly approved data roots.
- Do not store raw high-frequency telemetry in Neo4j.
- Do not store raw reasoning in Neo4j.
- Bound query depth, result count, property size, and execution timeout.
- Reject arbitrary Cypher from LLM or GUI clients.
- Do not auto-apply ontology changes.
- Store Neo4j credentials in a Git-ignored secret file.
- Preserve Guardian/operator authority for live hardware and ontology changes.

## 21. Migration Plan

1. Back up current typed JSONL and graph JSON artifacts.
2. Start and verify the Neo4j service.
3. Apply Neo4j constraints and indexes.
4. Load ATR Core Ontology v1.
5. Import the current Graphify project graph.
6. Import existing typed Knowledge JSONL through schema adapters.
7. Validate artifact hashes and provenance links.
8. Run node/relationship reconciliation.
9. Enable graph retrieval in Knowledge Agent.
10. Change the JSON graph backend to read-only compatibility mode.
11. Enable Neo4j primary mode.
12. Verify rollback by disabling Neo4j writes while retaining JSONL/outbox records.

Migration does not remove existing JSONL files or rewrite historical evidence in place.

## 22. Test Strategy

### 22.1 Unit Tests

- ontology class/relation validation;
- cardinality validation;
- lifecycle state transitions;
- event normalization;
- JSONL atomic append and `fsync` path;
- durable outbox retry and idempotency;
- query-plan allowlist validation;
- artifact path and hash validation;
- claim confidence and validity transitions.

### 22.2 Integration Tests

- Neo4j container health and CRUD;
- ontology import and migration;
- Graphify import and reconciliation;
- JSONL to outbox to Neo4j flow;
- Neo4j outage and recovery;
- duplicate event replay;
- Knowledge Agent Graph RAG;
- BO graph context handoff;
- Guardian graph evidence handoff.

### 22.3 End-to-End Tests

- Live GUI test-mode five-cycle loop;
- uninterrupted loop during Neo4j outage;
- automatic outbox synchronization after recovery;
- Knowledge report live update;
- BO receives graph-grounded context;
- Guardian receives graph-grounded safety evidence;
- GUI refresh and new-window state restoration;
- server restart and pending-outbox recovery;
- CLI/GUI cross-reflection;
- no regression in Live/Test/Virtual bridge behavior.

## 23. Acceptance Criteria

The feature is complete only when:

1. Neo4j operates as the primary Knowledge query store.
2. JSONL is durably written before every Neo4j mutation.
3. Neo4j outage cannot lose an accepted event.
4. Pending events synchronize automatically after recovery.
5. Ontology and Knowledge Graph layers are visibly and logically distinct.
6. Every runtime instance has an ontology reference or an explicit validation failure.
7. Knowledge Agent uses graph query results in actual synthesis and handoff packets.
8. BO receives graph-grounded optimization context.
9. Guardian receives graph-grounded safety context.
10. Graphify project entities connect to runtime Agent, Module, Tool, Failure, and Artifact entities.
11. GUI and CLI show the same graph, ontology, and synchronization status.
12. Five-cycle test mode and outage-recovery tests pass.
13. Existing Knowledge contracts and autonomous loop behavior remain compatible.

## 24. Non-Goals

- Storing raw videos, images, STL, G-code, or complete telemetry streams as Neo4j properties.
- Allowing LLM-generated arbitrary Cypher.
- Automatic ontology mutation or automatic ontology approval.
- Replacing Guardian or operator authority.
- Removing existing JSONL audit records.
- Replacing the vector/RAG layer; Graph RAG augments it.
- Performing a full Graphify repository scan during every experiment cycle.

## 25. Implementation Boundary

This design is one program composed of independently testable increments:

1. ontology registry and validator;
2. append-only ledger and durable outbox;
3. Neo4j repository and sync worker;
4. Graphify reconciliation;
5. graph query planner and Graph RAG;
6. Knowledge Agent integration;
7. BO and Guardian handoffs;
8. API and CLI parity;
9. Knowledge Workspace GUI;
10. migration, outage recovery, and full-path verification.

Each increment must preserve existing runtime contracts and must be independently reversible before Neo4j primary mode is enabled.
