---
doc_type: design
subtype: architecture
status: active
authority: proposal
decision_status: approved
audience: [developer, researcher, maintainer]
scope: [knowledge, source_ingestion, curation, scoped_rag]
summary: Folder-driven source ingestion, bounded LLM curation, Markdown organization, and source-backed agent retrieval.
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/superpowers/plans/2026-09-11-source-curation.md
supersedes: []
---

# Source Ingestion and Knowledge Curation

## Approved Contract

The existing source folder becomes a general Knowledge inbox. Detect additions
and changes, extract source-preserving Markdown, let the registered model inspect
and organize evidence through tools, then publish searchable curated Markdown.
Keep original inputs unchanged. Preserve existing loop memory, ontology, numerical
contracts, execution routes, and device bridges. Published documentation describes
generic source material without enumerating input subject categories or devices.

## Ownership and Flow

The [Wiki and Memory integration](../../knowledge/wiki_memory.md) adds a public
platform corpus and separately scoped private memory. It preserves this source
worker and its existing retrieval contract. Source Library remains its own
Workspace tab and store; its publications are not automatically copied into
public Wiki or private memory. Opening the Workspace does not start ingestion.

`Folder change → stable source snapshot → page files → page-level LLM reading → bounded consolidation → one Markdown publication → scoped retrieval`

- Code detects files and owns extraction, hashing, locks, path containment,
  atomic persistence, and validation. It never invents missing content.
- The Knowledge LLM inspects source blocks, compares existing knowledge, selects
  classification and applicability, and writes organized Markdown with citations.
- Converted source text and derived curation are separate artifacts. Their source
  hashes and block references remain inspectable. Extraction is not a summary.
- The worker runs outside the experiment stage. It uses ATR's existing model
  routing/lease and gives active workflow requests priority. No model startup or
  equipment command is part of ingestion.
- Other agents retrieve relevant published knowledge through a shared read-only
  API/tool contract; source content cannot alter tool/approval authority.

## Persistence and Identity

Default inbox: `docs/knowledge/manuals/sources/`, owned by the local service;
HTTP requests cannot override its root. Generated data: `memory/knowledge/source_library/`. Source identities
derive from content hashes, not fabricated experiment runs or cycles. Equal
content has one extraction/curation record with path aliases. Modified content
creates a new source version while earlier artifacts remain available for audit.
Only current, successfully published material is eligible for default retrieval.
Deleting an inbox file does not delete preserved artifacts, but stale path
versions must not silently remain current.

For each source, retain a manifest, complete extracted `source.md`, page files,
source blocks, and model/tool trace. Process page files individually, preserving
page numbers and table/section provenance. Consolidate the page-level findings
into **one curated Markdown output per original source**, under a validated
classification. Intermediate page findings are not published as separate RAG
documents. Long pages may use smaller blocks without losing their page identity.
Record state as discovered/extracted/processing/ready/needs_review/failed/missing.
Unsupported, unreadable, incomplete, or changed-during-processing inputs must not
publish partial output as success. Failed revisions must not overwrite a previous
complete artifact. Retry only failed/pending work; unchanged successful work is
not repeated. Do not ingest generated output recursively.

## Decision Tools and Retrieval

The bounded curation tools inspect source pages, stage grounded page findings,
compare existing knowledge, and publish the consolidated document. Inspection
exposes indexed source blocks with stable IDs. A complete long input is never
sent in one inference request; bounded consolidation combines intermediate
findings hierarchically when necessary. Per-call inference timeouts do not impose
the same total processing deadline on short and long sources. Publication requires every source block to have been
inspected, cited block IDs to exist, valid ontology labels, bounded Markdown and
metadata, and an unchanged source identity. Ambiguous/conflicting content retains
qualifications rather than being promoted to a fact.

Page revisions are cumulative, retaining prior quantitative evidence and its
conditions while adding newly inspected content. Consolidation covers substantive
findings from every current input; reference lists and quoted/appendix content
must not be confused with primary findings or implemented dependencies. Prompts
expose only the tools and evidence needed for the current phase.

Audit persistence retains every event with stable source/block/stage references
and content hashes. Its event-count, per-event and total-byte budgets are aligned
with the admitted extraction and bounded traversal limits; full extracted text
and validated drafts remain in their own artifacts.

The published document exposes source IDs, source version/hash, title, category,
ontology_type, tags, applicability, body, and citations. Retrieval filters before
ranking, supports exact source/category/tag/applicability restrictions, and rejects
unknown filters. Empty or absent evidence is explicit. Scoped detail uses the same
filters as search. Original source blocks can be inspected alongside derived notes.

Existing Knowledge decisions gain a source corpus and preserve citations into BO.
Equipment's normal workflow decision may request relevant source context without
changing its immutable proposals or execution. Retire its unconditional legacy
manual-context attachment; do not substitute current sources into an equipment-
specific legacy schema. Existing loop and typed memory contracts remain unchanged.

## Operations and Verification

The existing workspace tab becomes Source Library: inbox/status, scan/retry,
background progress, scoped search, and full note/source detail. Keep other tabs.
The worker detects stable files while ATR is running, records progress, and waits
when a model is unavailable/busy. Startup does not launch inference services or
immediately process previously present material without a saved enablement choice.
Provide explicit activation in the workspace; preserve the enabled setting.

Verify real file conversion, revisions, duplicate avoidance, provenance, scoped
retrieval, failure isolation, cancellation, model unavailability, and consumer
handoffs. Test registered API and local model paths with varied temporary evidence,
including a public-source fixture and independently specified answer checks.
Keep test labels and generated data separate from experimental observations.
After verification, remove temporary working roots and keep operational stores
untouched. The user's subsequent retention instruction requires a separate
external validation archive: preserve inputs, generated Markdown, page results,
indices, model responses and consumer traces there, never in the ATR repository
or production knowledge corpus. Keep executable verification and measured
summaries in Git; the probe accepts an explicit external archive destination.

No physical actuation, native solver, production restart, model-server startup,
or historical-data deletion is part of this implementation. After verification
and temporary-data cleanup, update the existing documentation and publish the
scoped changes as a commit with a new tag, as subsequently requested by the user.
