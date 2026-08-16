# Manual RAG Knowledge Design

## Goal

Add a dedicated `Manual RAG Knowledge` module inside the Knowledge Agent and
make its evidence available to the Lab Equipment Agent's UTM-profile LLM for
PyAutoGUI Skill authoring, procedural guidance, runtime decisions, and bounded
exception recovery.

## Boundaries

- The equipment hierarchy is selected by `equipment_type=utm`.
- Product and software names or versions are provenance and ranking metadata;
  they are never mandatory query filters or hard-coded runtime selectors.
- Manual retrieval never dispatches a device command.
- Generated Skill content still passes the existing Skill schema, deployment,
  bridge preflight, Guardian, and operator gates.
- Manual evidence is source-separated from experiment memory, project-graph
  context, web retrieval, and model reasoning.

## Architecture

`Manual RAG Knowledge` owns source registration, PDF extraction, hierarchical
chunking, ontology projection, graph persistence, bounded retrieval, citations,
and ingestion receipts. The existing Knowledge graph backend stores manual graph
nodes and edges in JSON or Neo4j. A manual query combines ranked text chunks
with a bounded graph neighborhood into `manual_context.v1`.

The Lab Equipment Agent requests this context with `equipment_type=utm` and a
purpose chosen from `skill_authoring`, `procedure`, `decision`, `safety`, and
`recovery`. The UTM-profile LLM receives only bounded evidence with page-level
citations. Product/version metadata may improve ranking but may not exclude an
otherwise relevant UTM source.

## Storage

- Sources: `docs/knowledge/manuals/sources/*.pdf`
- Source registry: `docs/knowledge/manuals/registry.yaml`
- Runtime corpus: `memory/knowledge/manual_rag/corpus.json`
- Runtime graph export: `memory/knowledge/manual_rag/manual_graph.json`
- Ingestion receipts: `memory/knowledge/manual_rag/receipts/*.json`
- Optional Neo4j projection: existing Knowledge graph backend

Generated runtime files remain outside Git. Source PDFs and the declarative
registry are versioned documentation inputs.

## Manual Ontology Extension

Node classes: `ManualDocument`, `ManualVersion`, `ManualSection`, `ManualChunk`,
`EquipmentType`, `EquipmentModel`, `SoftwareProduct`, `SoftwareVersion`,
`Screen`, `Menu`, `Control`, `Procedure`, `ProcedureStep`, `Parameter`, `Unit`,
`CommunicationInterface`, `Warning`, `Interlock`, `Fault`, `Cause`, `Remedy`,
`MaintenanceTask`, and `ConsumablePart`.

Relations: `APPLIES_TO`, `HAS_VERSION`, `HAS_SECTION`, `HAS_CHUNK`, `HAS_STEP`,
`PRECEDES`, `DISPLAYED_ON`, `OPERATES_CONTROL`, `SETS_PARAMETER`, `REQUIRES`,
`PROHIBITS`, `HAS_WARNING`, `HAS_CAUSE`, `RESOLVED_BY`, `CONNECTS_TO`,
`PRODUCES_RESULT`, and `SOURCED_FROM`.

All manual nodes carry source ID, page, section path, source hash, and extraction
timestamp. Relationships derived from heuristics carry confidence and provenance.

## Retrieval Contract

`ManualKnowledgeService.query(payload) -> dict` accepts:

- `equipment_type`: required and currently `utm`
- `query`: required natural-language request
- `purpose`: one of the allowlisted purposes
- `top_k`: bounded to 1..12
- optional non-binding `product_hint` and `version_hint`

It returns `manual_context.v1` with ranked chunks, graph nodes/edges, citations,
coverage, source hashes, and an explicit `insufficient_evidence` flag.

## Equipment Integration

Manual context is injected into:

1. selected-model Skill annotation and authoring prompts;
2. UTM protocol-formatting guidance;
3. bounded recovery decisions.

Model output must cite chunk IDs for manual-derived claims. Unsupported steps are
marked for operator review rather than invented. Existing command allowlists and
physical-effect gates remain authoritative.

## Operator Surface

The Knowledge workspace gains a `Manual RAG Knowledge` section showing source
status, ingestion receipts, ontology/graph counts, bounded query results, and
citations. The Lab Equipment workspace reports which manual context package was
used without duplicating the Knowledge management interface.

## Failure Handling

- Missing or unreadable source: ingestion receipt is failed; existing corpus is
  not overwritten.
- Weak retrieval: return `insufficient_evidence=true`; do not use web fallback.
- Graph backend unavailable: the explicit JSON graph backend remains queryable
  when selected; no silent backend switch occurs.
- Conflicting manuals: preserve both sources and expose the conflict to the LLM
  and operator; never silently choose by product/version.

## Verification

- Parser tests preserve page and section provenance.
- Ontology tests reject invalid node/edge types.
- Retrieval tests prove UTM filtering without product/version hard filtering.
- Equipment integration tests prove context injection and unchanged command
  validation boundaries.
- API and browser tests cover ingestion status and manual query presentation.

