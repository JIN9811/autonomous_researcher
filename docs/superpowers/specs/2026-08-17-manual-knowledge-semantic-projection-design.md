# Manual Knowledge Semantic Projection Design

## Goal

Turn the current document-centered manual graph into an operator-readable and
LLM-usable semantic graph without deleting page-level evidence. The default
view must explain UTM procedures and recovery paths rather than visualize PDF
chunking.

## Scope

- Preserve the existing manual registry, extracted corpus, page citations, and
  immutable source hashes.
- Preserve `equipment_type=utm` as the only hard equipment scope.
- Add a semantic projection over the existing evidence graph.
- Return a bounded, query-centered semantic subgraph for retrieval and UI use.
- Improve the Manual RAG Knowledge workspace without changing Lab Equipment
  command payloads, PyAutoGUI program IDs, Guardian gates, or device bridges.
- Do not add web retrieval or allow an LLM to invent executable instructions.

## Graph Layers

### Evidence Graph

The evidence graph remains the authoritative provenance layer:

```text
ManualDocument -> ManualSection -> ManualChunk -> source page
```

It answers where a statement came from. `ManualChunk` nodes remain stored but
are hidden in the default semantic view. They are exposed only through evidence
expansion or the inspector.

### Semantic Graph

The semantic graph represents concepts an operator or agent needs:

```text
EquipmentType -> Procedure -> ProcedureStep
Fault -> Cause -> Remedy
Warning -> Interlock
Parameter -> Unit
```

Every semantic node and edge must have at least one `SUPPORTED_BY` link to an
evidence node. A semantic assertion without page-level provenance is rejected
or queued for review.

### Query Projection

`ManualKnowledgeService.query` returns a compact semantic projection built from
the highest-ranked evidence:

1. rank evidence chunks;
2. resolve their semantic nodes;
3. retain the best one to three seed concepts;
4. expand semantic relationships to a maximum of two hops;
5. attach only the citations required to support the displayed concepts;
6. enforce configurable node and edge limits, defaulting to 40 nodes and 60
   edges.

The projection must be deterministic for identical corpus and query inputs.

## Semantic Extraction

Extraction uses a bounded two-stage pipeline:

1. deterministic parsing identifies headings, numbered steps, explicit labels,
   tables, parameters, units, warnings, faults, causes, and remedies;
2. an optional selected LLM proposes relationships only among extracted spans.

LLM proposals must include source chunk IDs and quoted span offsets. They may
not create commands, coordinates, credentials, program identifiers, safety
settings, or physical actions that are absent from the source. High-confidence
proposals with complete provenance may be accepted automatically. Medium-
confidence proposals enter Relation Review. Low-confidence or unsupported
proposals are discarded.

## Entity Resolution

Semantic entities are normalized before projection:

- normalize whitespace, punctuation, case, and common Korean/English aliases;
- merge only when type-compatible names and source context agree;
- preserve all source labels as aliases;
- never merge faults, remedies, or procedures solely because their embeddings
  are similar;
- record merge decisions and reversible source memberships.

Product names and software versions remain provenance and ranking hints. They
must not split the UTM hierarchy into mandatory runtime branches.

## Contracts

### Semantic Node

Required fields:

- stable node ID;
- semantic type;
- canonical label;
- aliases;
- equipment type;
- confidence;
- supporting chunk IDs;
- source page citations;
- extraction method and timestamp.

### Semantic Edge

Required fields:

- stable edge ID;
- source and target node IDs;
- allowlisted relation type;
- confidence;
- supporting chunk IDs;
- review state;
- extraction method.

### Query Response

`manual_context.v1` remains backward compatible and gains a
`semantic_projection` object containing seeds, nodes, edges, citations,
projection limits, and truncation state. Existing ranked chunks remain
available to prompt construction and audit code.

## Workspace Design

The Manual RAG Knowledge tab uses three coordinated regions:

1. **Evidence**: ranked excerpts, document title, page, section, and score.
2. **Semantic Graph**: query-centered concepts and relationships.
3. **Inspector**: selected node or edge, confidence, aliases, relation label,
   review state, and supporting citations.

Default graph behavior:

- hide `ManualChunk` nodes;
- use left-to-right hierarchy for procedures;
- use `Fault -> Cause -> Remedy` lanes for recovery queries;
- use compact radial layout only for mixed-purpose queries;
- cluster nodes by semantic family, not by source document;
- show edge direction and relation label on selection;
- expand evidence nodes on demand;
- retain zoom, selection, and query state during refresh.

Semantic node shapes supplement color so the graph remains readable for color-
vision deficiencies. Long labels are shortened on-canvas and shown in full in
the inspector.

## Failure Handling

- No semantic match: return ranked evidence with
  `insufficient_semantic_evidence=true`; do not fabricate graph nodes.
- Evidence graph unavailable: return an empty bounded context and preserve the
  existing Lab Equipment execution path.
- Unsupported relation: reject it during validation and retain the source
  evidence for later review.
- Conflicting manuals: retain both assertions, mark the conflict, and display
  both citations.
- Projection limit reached: set `truncated=true` and prioritize semantic nodes
  over sections and chunks.

## Migration

The existing corpus and graph export are not rewritten in place. A versioned
semantic projection is generated beside them. Rebuilding is atomic: validate
the new projection, write a receipt, then replace the active projection pointer.
Failed rebuilds leave the prior projection active.

## Quality Metrics

Track quality independently from graph size:

- percentage of semantic nodes and edges with page citations;
- duplicate semantic entity rate;
- isolated semantic node rate;
- complete `Fault -> Cause -> Remedy` chain rate;
- complete `Procedure -> Step` chain rate;
- relation acceptance and rejection rates;
- retrieval citation recall on a fixed UTM question set;
- operator corrections from Relation Review;
- query projection node count, truncation rate, and render time.

Initial acceptance thresholds:

- 100% provenance coverage for displayed semantic assertions;
- zero uncited executable instructions;
- no `ManualChunk` nodes in the default graph;
- no horizontal overflow at 1920x1080;
- query projection renders within one second from an existing local index;
- procedure and recovery test questions return the expected source pages and a
  connected semantic path.

## Verification

- Unit tests cover semantic extraction, entity resolution, stable IDs, evidence
  requirements, projection limits, and deterministic results.
- Retrieval tests cover procedure and recovery paths and prove product/version
  hints remain non-binding.
- API tests prove backward compatibility of `manual_context.v1`.
- Browser tests verify chunk hiding, evidence expansion, node selection,
  inspector content, graph dimensions, and no overflow at 1920x1080.
- Regression tests prove manual retrieval failures do not alter or block the
  existing Lab Equipment command path.
