---
doc_type: design
subtype: architecture
status: review
authority: proposal
audience:
  - researcher
  - operator
  - maintainer
scope:
  - knowledge_agent
  - knowledge_graph
  - relation_reconciliation
  - operator_approval
summary: Continuous LLM-assisted reconciliation of disconnected Knowledge Graph nodes with ontology validation, evidence scoring, and operator revision approval.
decision_status: approved
related_docs:
  - docs/superpowers/specs/2026-08-08-knowledge-agent-neo4j-graphify-ontology-design.md
  - docs/knowledge/knowledge_graph_operations.ko.md
  - docs/agents/knowledge_agent_self_evolution_runtime_guideline.md
supersedes: []
---

# Knowledge Relation Reconciliation Design

## 1. Purpose

This design adds a continuous, LLM-assisted relation reconciliation loop to
the ATR Knowledge Agent. The loop identifies isolated or weakly connected
Knowledge Graph nodes, proposes evidence-backed typed relationships, validates
them against the active ontology, and either promotes them automatically or
places them in a dedicated operator review queue.

The LLM is a proposal engine. It never writes directly to Neo4j and never
changes the core ontology. Every accepted relationship follows the existing
append-only audit ledger, durable outbox, and graph synchronization path.

## 2. Confirmed Decisions

1. Relation reconciliation runs continuously as bounded incremental work.
2. The worker processes new or unresolved nodes instead of repeatedly scanning
   the entire graph.
3. The currently selected Live GUI LLM route is used; no reconciliation model
   is hard-coded.
4. The LLM may propose relationships but may not execute arbitrary Cypher or
   write directly to the graph backend.
5. Candidate relationships must reference existing source and target nodes.
6. Candidate relationship types must exist in the active ontology and pass its
   domain/range rules.
7. Automatic promotion requires all of the following:
   - LLM confidence greater than or equal to `0.90`;
   - deterministic evidence score greater than or equal to `0.80`;
   - successful ontology validation;
   - at least one valid provenance reference;
   - no self-reference or duplicate relationship.
8. Every candidate that does not meet all automatic-promotion requirements is
   placed in the Knowledge Workspace review queue.
9. Operators may approve, revise and approve, reject, defer, or request LLM
   re-evaluation.
10. The source node of a proposal is fixed. An operator may revise its target,
    relationship type, and review rationale.
11. Original proposals are immutable. Revisions create versioned decisions and
    preserve a complete before/after audit trail.
12. Relation reconciliation failure does not block the experiment loop.
13. Knowledge Workspace reports detected graph gaps and recommends a manual
    reconciliation run; opening the workspace does not automatically occupy an
    LLM.
14. During an active closed loop, reconciliation may run automatically only
    while the selected LLM route is already loaded and its central lease is
    idle.
15. Background reconciliation has lower priority than Guardian, active
    experiment-stage calls, and operator chat, and never loads a model solely
    for graph maintenance.
16. Graph Explorer has explicit `View Mode` and `Edit Mode`; View Mode remains
    the default.
17. Edit Mode is limited to existing nodes, existing relationships, and
    operator-editable metadata. It cannot create new graph nodes.
18. Edit Mode changes remain in a draft layer until the operator validates and
    applies the complete change set.

## 3. Current Baseline

The repository already provides the required persistence and validation
boundaries:

- `agents/knowledge_agent.py` creates experiment memory and graph events.
- `knowledge/service.py` normalizes, validates, records, queues, and synchronizes
  Knowledge events.
- `knowledge/ontology/validator.py` enforces typed relationship domain/range
  rules.
- `knowledge/audit_ledger.py` is the append-only source of mutation evidence.
- `knowledge/durable_outbox.py` preserves graph writes across backend outages.
- `knowledge/neo4j_repository.py` converts accepted events into graph entities.
- `knowledge/graph_backend.py` exposes bounded, allowlisted graph operations.
- `/knowledge` provides Graph Explorer, Memory, Ontology, Sync, and Project
  Graph tabs.

The missing capability is active graph completion: existing nodes are not
continuously examined for missing or plausible typed relationships.

## 4. Reconciliation Architecture

```text
Knowledge event accepted
        |
        v
Incremental node/change queue
        |
        v
Orphan and weak-link detector
        |
        v
Deterministic candidate generator
        |
        v
Bounded LLM relation proposal
        |
        v
Ontology + evidence + duplicate validation
        |
        +-- high confidence ----------> automatic decision event
        |
        +-- all other valid proposals -> Relation Review queue
                                           |
                                           v
                                  operator decision/revision
                                           |
                                           v
JSONL ledger -> durable outbox -> Neo4j synchronization
```

### 4.1 Component Boundaries

The feature is divided into isolated components:

- **Reconciliation Scheduler**: consumes bounded work without blocking the
  active experiment loop.
- **Graph Gap Detector**: identifies nodes requiring examination.
- **Candidate Generator**: produces a small deterministic target set.
- **Relation Proposer**: asks the selected LLM to rank and explain only those
  candidates.
- **Proposal Validator**: applies ontology, existence, provenance, duplicate,
  and score checks.
- **Proposal Store**: preserves immutable proposals and versioned decisions.
- **Promotion Service**: emits accepted relations through `KnowledgeService`.
- **Relation Review Workspace**: lets an operator inspect and resolve queued
  proposals.

No component is permitted to bypass `KnowledgeService.ingest()` when a graph
mutation is promoted.

## 5. Graph Gap Detection

The detector recognizes three classes of graph gap.

### 5.1 Isolated Node

A node has no accepted incoming or outgoing relationship.

### 5.2 Disconnected Component

A node has relationships but cannot reach a runtime root such as `Run`,
`Experiment`, or a registered project module within a bounded traversal depth.

### 5.3 Missing Expected Relationship

A node is connected but lacks a relationship expected from its class and the
available evidence. Examples include a `Specimen` with a manufacturing session
but no observation, or an `AgentExecution` with an artifact but no `PRODUCES`
edge.

Detection is deterministic. The LLM does not decide whether a node is isolated
and does not receive arbitrary access to the complete graph.

## 6. Incremental Scheduling

Reconciliation is event-driven and persistent.

1. A successful Knowledge ingest records changed entity IDs in a reconciliation
   queue.
2. One worker instance claims a bounded batch.
3. A node is skipped when the same graph revision and evidence hash were
   already evaluated.
4. Unresolved candidates remain durable across server restarts.
5. Failed model calls use bounded retry with backoff and return the item to the
   queue.
6. Reconciliation never starts a second in-flight job for the same source node.

Recommended initial limits:

- 10 source nodes per batch;
- 8 deterministic target candidates per source;
- at most 3 LLM relationship proposals per source;
- one reconciliation LLM call at a time;
- 30-second idle cooldown when no unresolved work exists;
- no full-graph scan during an active physical-device stage.

A manual `Scan gaps` action may enqueue a bounded audit scan, but it uses the
same worker and cannot create a parallel full-graph job.

### 6.1 LLM Lease and Priority

All reconciliation model calls acquire a shared LLM lease instead of inferring
availability from UI state. The priority order is:

1. E-STOP and Guardian safety reasoning;
2. active closed-loop stage reasoning and tool planning;
3. operator chat;
4. Knowledge relation reconciliation.

The background worker starts one bounded proposal call only when no higher
priority request is queued or active. A higher-priority request prevents the
next reconciliation item from starting; the worker does not corrupt or discard
the current proposal. Reconciliation does not load an unloaded model and does
not switch the selected backend or model.

### 6.2 Workspace and Closed-loop Triggers

Knowledge Workspace performs deterministic gap detection and displays a
recommendation with the unresolved count and estimated bounded work. The
operator starts reconciliation with `Run Reconciliation`.

During a closed loop, successful Knowledge ingest enqueues changed nodes. The
background worker processes them opportunistically while the selected LLM
lease is idle. Workspace and closed-loop triggers feed one durable queue and
cannot produce duplicate jobs.

## 7. Candidate Generation

The deterministic candidate generator ranks existing nodes by:

1. same run, experiment, or cycle;
2. shared artifact or provenance references;
3. compatible source and target classes under the active ontology;
4. shared agent, tool, device, policy, specimen, or module identifiers;
5. bounded semantic retrieval similarity;
6. temporal proximity;
7. existing neighboring-node overlap.

The LLM receives only the highest-ranked bounded candidate set. It may select a
candidate, reject all candidates, or propose no relation. It may not invent a
new target ID.

## 8. Proposal Contract

Each immutable proposal uses `knowledge_relation_proposal.v1`.

Required fields:

- stable proposal ID and source graph revision;
- source node ID and class;
- proposed target node ID and class;
- proposed ontology relationship type;
- LLM confidence;
- deterministic evidence score;
- concise rationale;
- provenance and artifact references;
- selected model/backend snapshot;
- ontology version;
- graph-context hash;
- creation time and lifecycle status.

Proposal statuses are:

```text
pending -> approved | revised_approved | rejected | deferred | superseded
```

Re-evaluation never overwrites a proposal. It creates a new proposal version
and marks the older unresolved version as `superseded`.

## 9. Validation and Promotion

Before a proposal can be promoted, the validator checks:

- source and target nodes still exist;
- graph revision changes have not invalidated the proposal context;
- relationship type exists in the active ontology;
- source and target classes satisfy domain/range rules;
- source and target are different;
- the accepted relationship does not already exist;
- provenance references are valid and accessible;
- payload and relationship counts remain inside ontology maxima;
- the decision is attributable to either the automatic policy or an operator.

High-confidence automatic decisions use
`decision_source=automatic_policy`. Operator decisions use
`decision_source=operator` and include the original proposal plus any revision.

An accepted decision is converted to a normal `knowledge_event.v1` containing
the approved `relationship_intents`. It then follows:

```text
normalize -> ontology validate -> audit ledger -> outbox -> Neo4j
```

## 10. Relation Review Workspace

Add `Relation Review` as a dedicated `/knowledge` tab. ATT displays only the
pending count, severity, and a link to this tab; it does not perform graph
approval itself.

### 10.1 Summary Strip

Show:

- orphan and weak-link node count;
- pending proposal count;
- approved count;
- revised-and-approved count;
- rejected count;
- deferred count;
- reconciliation worker state.

### 10.2 Queue Pane

The left pane lists proposals with filters for:

- confidence band;
- source and target class;
- relationship type;
- run/experiment;
- pending/deferred state;
- creation time;
- evidence availability.

Repeated proposals for the same source, target, relation, and graph revision are
deduplicated. Repeated supporting evidence increases an occurrence counter
instead of creating duplicate rows.

### 10.3 Context Pane

The center pane shows:

- source and proposed target nodes;
- accepted one-hop neighborhood for both nodes;
- the proposed relationship as an amber dashed edge;
- ontology-compatible alternative targets;
- provenance and artifact evidence;
- LLM rationale and model snapshot;
- deterministic score factors;
- ontology validation result.

Pending edges must never be rendered as accepted graph relationships.

### 10.4 Decision Pane

The right pane provides:

- `Approve`;
- `Edit & Approve`;
- `Reject`;
- `Defer`;
- `Re-evaluate`.

`Edit & Approve` permits:

- target selection from existing graph nodes;
- relationship selection from ontology-compatible types;
- an operator rationale.

The source node remains fixed. The interface validates revisions before
enabling approval and shows a before/after diff.

### 10.5 Decision History

The lower section presents immutable proposal and decision versions, including:

- who or what made the decision;
- timestamps;
- original and revised relationship values;
- rejection/defer rationale;
- promotion event ID;
- ledger receipt and Neo4j sync status.

### 10.6 Graph Explorer Edit Mode

Graph Explorer provides a deliberate `View Mode / Edit Mode` switch. Switching
to Edit Mode creates a local draft change set and changes the canvas and toolbar
appearance so an operator cannot confuse pending edits with accepted graph
state.

Allowed operations are limited to:

- move existing nodes for layout purposes;
- connect two existing nodes with an ontology-compatible relationship;
- revise the target or relationship type of an existing edge;
- mark an existing edge `deprecated` or `revoked`;
- edit allowlisted metadata such as label, alias, note, and tags.

Edit Mode does not create nodes and cannot modify node IDs, entity classes,
original provenance, ontology versions, or audit receipts. Physical deletion
is prohibited.

The toolbar provides `Undo`, `Redo`, `Validate`, `Apply Changes`, and `Discard`.
Draft relationships render as cyan dashed edges, revisions as amber edges,
deprecations as red struck edges, and invalid changes with a red boundary.

`Apply Changes` is the operator approval action for that draft. It creates an
immutable `knowledge_graph_edit_decision.v1` record and emits validated
`knowledge_event.v1` relationship intents through the normal ledger, outbox,
and synchronization path. These operator-authored changes do not require a
second Relation Review approval. Validation failures leave the draft intact
and produce no graph mutation.

## 11. Operator Processing Rules

- Approval requires a currently valid proposal and successful validation.
- Revised approval requires a visible diff and a new validation pass.
- Rejection requires a bounded reason code; an optional note may be added.
- Deferral records a review-after time and note without changing the graph.
- Re-evaluation uses the currently selected LLM route and preserves the prior
  proposal.
- Batch approval is allowed only when every selected proposal is unchanged,
  currently valid, and requires no revision.
- Batch rejection may use one common reason while preserving individual
  decision records.
- Low-confidence proposals remain reviewable but sort below medium-confidence
  proposals by default.

## 12. Failure and Recovery Behavior

### LLM unavailable

- Mark reconciliation as degraded.
- Preserve queued nodes and retry later.
- Do not fabricate relationships or block the experiment loop.

### Neo4j unavailable

- Preserve accepted decision events in the ledger and outbox.
- Show synchronization pending state in Relation Review and Sync.
- Do not represent the edge as synchronized until a receipt exists.

### Stale proposal

- Disable approval when source, target, ontology version, or graph context has
  changed materially.
- Allow re-evaluation against the current graph.

### Invalid operator revision

- Show the ontology or existence failure inline.
- Do not create a decision event or graph mutation.

### Queue growth

- Deduplicate equivalent proposals.
- Prioritize by graph impact, evidence score, and age.
- Keep resolved proposals in append-only history rather than the active queue.

## 13. API Boundary

The workspace requires bounded APIs for:

- reconciliation status and metrics;
- paginated proposal listing;
- one proposal with bounded graph context;
- approve, revise-and-approve, reject, defer, and re-evaluate actions;
- bounded manual gap scan;
- decision history;
- accepted-event and synchronization receipts.

Graph Edit Mode additionally requires bounded APIs for draft validation and
atomic application of an optimistic-concurrency-protected change set. Layout
coordinates may be saved as UI preferences without producing semantic graph
events; semantic and metadata changes always produce decision and ledger
records.

All mutation endpoints require optimistic concurrency using proposal version or
graph-context hash. Arbitrary Cypher, arbitrary node creation, and unvalidated
relationship types remain prohibited.

## 14. Live GUI and ATT Integration

The Knowledge Agent report adds compact reconciliation metrics:

- examined nodes;
- proposals generated;
- automatically accepted;
- waiting for review;
- rejected or deferred;
- worker health.

The existing Knowledge activity visualization remains intact. A separate
relation-reconciliation card displays these metrics so collection/retrieval
activity is not conflated with graph mutation decisions.

ATT creates one aggregated notification when pending proposals exist. It links
to the Relation Review tab and must not emit one attention item per proposal.
Relation review does not block the physical experiment loop.

## 15. Security and Governance

- Core ontology changes remain outside this feature.
- LLM output is treated as untrusted structured input.
- Prompt context is bounded and excludes secrets or raw high-volume artifacts.
- Operator identity defaults to the authenticated/local runtime identity and is
  recorded on every manual decision.
- Accepted relationships retain model, prompt-contract version, ontology
  version, evidence, and decision provenance.
- Rejected proposals remain audit evidence but are not graph edges.

## 16. Verification Strategy

### Unit tests

- isolated, disconnected-component, and missing-expected-link detection;
- candidate ranking and deterministic bounds;
- proposal parsing and rejection of invented targets;
- score threshold behavior;
- ontology, duplicate, self-reference, and stale-context validation;
- immutable proposal versioning and decision diff generation;
- automatic, manual, revised, rejected, deferred, and superseded transitions.

### Integration tests

- accepted relation traverses ledger, outbox, and Neo4j once;
- Neo4j outage leaves a replayable pending event;
- LLM outage preserves reconciliation work without blocking Knowledge Agent;
- concurrent decisions cannot approve the same proposal twice;
- operator revision is visible in the ledger and synchronized edge properties;
- ATT receives one aggregated pending-review notification.

### GUI tests

- queue filters and pagination;
- source/target context and dashed pending-edge rendering;
- ontology-filtered relation and target editors;
- approval controls remain disabled until revision validation succeeds;
- decisions update counts and remove resolved items from the active queue;
- refresh and server restart preserve pending and resolved state;
- 1920 x 1080 browser audit without clipped controls or overlapping text.
- View Mode is the default and cannot mutate graph state;
- Edit Mode supports only existing-node relation and allowlisted metadata
  drafts;
- Undo, redo, validation, apply, and discard preserve the accepted graph until
  apply succeeds;
- stale graph revisions prevent draft application without losing the draft.

### End-to-end acceptance

1. Ingest a Knowledge event containing an intentionally isolated node.
2. Confirm incremental detection without a full-graph scan.
3. Generate a bounded LLM relationship proposal.
4. Confirm a medium-confidence proposal appears in Relation Review only.
5. Revise its target or relationship type and approve it.
6. Confirm immutable original and revised decision records.
7. Confirm ontology validation, ledger receipt, outbox receipt, and Neo4j edge.
8. Restart the server and confirm queue and decision history persist.
9. Disconnect Neo4j, approve another proposal, reconnect, and confirm replay.
10. Confirm the experiment workflow was never blocked by reconciliation.
11. Enter Edit Mode, revise an existing relation, validate, and apply it.
12. Confirm the original edge remains in history as deprecated and the revised
    edge is synchronized once.
13. Confirm Edit Mode cannot create a new node or alter identity/provenance.

## 17. Non-goals

- Autonomous modification of the core ontology.
- Arbitrary Cypher generation or execution by an LLM.
- Creation of new graph entities solely from an LLM suggestion.
- Replacement of Graphify deterministic project scanning.
- Blocking device operation while a semantic relationship awaits review.
- Replacing Guardian physical-safety authority with Knowledge confidence.

## 18. Completion Criteria

The feature is complete when:

- new and unresolved graph nodes are reconciled incrementally;
- high-confidence proposals follow the confirmed automatic policy;
- every other valid proposal is durable and reviewable;
- operators can revise and approve ontology-compatible relationships;
- every graph mutation is traceable through proposal, decision, ledger, outbox,
  and synchronization receipts;
- failure and restart behavior preserve work without blocking experiments;
- Knowledge Workspace, Live GUI, and ATT expose consistent reconciliation state.
