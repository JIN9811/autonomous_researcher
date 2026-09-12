<!-- atr-doc
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience: [operator, developer, maintainer]
scope: [knowledge_agent, source_library, source_curation, scoped_rag]
summary: Operate folder-driven source curation, page-level processing, consolidated Markdown and scoped agent retrieval.
source_of_truth:
  - knowledge/source_library.py
  - knowledge/source_extraction.py
  - knowledge/source_runtime.py
  - knowledge/source_api.py
  - agents/source_curation.py
  - mcp_tools/source_tools.py
last_verified: 2026-09-11
verified_against: working-tree-2026-09-11
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/knowledge/markdown_memory_operations.ko.md
  - docs/superpowers/specs/2026-09-11-source-curation-design.md
supersedes: []
-->

# Source Library Operations

## Status at a Glance

| At a glance | Details |
|---|---|
| Purpose | Curate submitted sources into cited Markdown and retrieve them by scope |
| Workspace | Knowledge → Source Library |
| Preparation | Configured Knowledge model; source inbox; explicit intake enablement |
| Recorded basis | 2026-09-11 · [Troubleshooting and verification](#troubleshooting-and-verification) |

The existing document URL is retained for link compatibility. Source Library
replaces the former manual-specific runtime; the old `/api/knowledge/manuals/*`
endpoints return HTTP 410. Original files, historical artifacts and ontology
definitions are preserved.

## Intake and Publication

1. Open **Knowledge Workspace → Source Library** at `/knowledge#manuals`.
2. Place source material in `docs/knowledge/manuals/sources/`. Keep generated
   output outside this inbox.
3. Enable **Automatically curate stable source changes**. This choice is saved;
   **Scan Sources** performs discovery without waiting for model inference.
4. Inspect source progress. Stable new or changed contents are processed by
   the registered Knowledge model when its existing inference lease is available.
5. Retrieve a ready document, then open its detail and original extracted Markdown.

The worker preserves a content-addressed original and complete extracted text.
Paginated sources are split into page files and read page-by-page. Bounded
consolidation produces **one curated Markdown output per original source**,
retaining quantities, conditions and page/block citations. Intermediate page
findings are not separate search results. Extraction is not an LLM summary.

The worker does not start a model server. Disabling intake prevents new source
jobs; an already active source may finish. Workflow requests take priority at
the next existing inference-lease boundary, not by interrupting an active call.

## Storage and Identity

| Location | Purpose |
|---|---|
| `docs/knowledge/manuals/sources/` | Existing inbox; operator-owned originals |
| `memory/knowledge/source_library/settings.json` | Saved automatic-intake setting |
| `memory/knowledge/source_library/sources/<source-id>/` | Preserved original, extraction, page files and publication history |
| `.../extractions/<extraction-id>/source.md` | Complete extracted source text |
| `.../extractions/<extraction-id>/pages/page-0001.md` | Individual source page; the page manifest maps files to blocks |
| `.../publications/<publication-id>/notes/<category>/<record-id>.md` | The single curated Markdown output |
| `.../publications/<publication-id>/` | Publication metadata, provenance and model/tool trace |

Here `...` denotes the corresponding `sources/<source-id>` directory, not the
operator inbox. Classification changes the derived output location, never the
original source path.

Equal content shares one identity and path aliases. Changed content receives a
new identity; the earlier complete publication remains available for audit.
Default retrieval includes only current, ready sources. Removing an inbox file
makes its old path version ineligible without deleting historical artifacts.
Generated knowledge stays local and is not automatically published to Git.

## Retrieval and Agent Use

| Surface | Request / result |
|---|---|
| GET `/api/knowledge/sources/status` | Worker state, counts and per-source progress |
| POST `/api/knowledge/sources/settings` | `{enabled: true/false}` |
| POST `/api/knowledge/sources/scan` | Discover and schedule stable changes |
| POST `/api/knowledge/sources/retry` | `{source_id}` for current unfinished work |
| POST `/api/knowledge/sources/query` | `{query, scope, top_k}` → metadata and excerpts |
| POST `/api/knowledge/sources/read` | `{record_id, scope}` → full note and source provenance |

Scope can restrict source identity, category, ontology type, tags and exact
applicability. Unknown filters fail; detail uses the same scope as search.
Source scope is independent of run/cycle identity in execution memory.

Agents share read-only `knowledge.sources.search` and `knowledge.sources.read`.
Knowledge passes selected records and citations through its existing BO handoff.
Equipment receives bounded reference excerpts at its existing decision boundary,
with explicit truncation metadata and full-detail availability. Source content
does not change numerical observations, proposals, commands or approval ownership.

## Troubleshooting and Verification

| State | Action |
|---|---|
| Disabled | Enable automatic intake if background processing is wanted |
| Waiting for model/workflow | Check the existing model selection or allow the active workflow to finish |
| Failed / needs review | Inspect the error, correct the input or configuration, then retry |
| No matching knowledge | Check current publication state and exact scope; do not broaden conditions silently |
| Missing source | Restore the intended input if it should remain eligible |

Unreadable or unsupported content is not fabricated. A failed or interrupted
curation cannot expose a partial publication as ready. Retry does not repeat an
unchanged successful publication.

The opt-in [`verify_source_curation.py`](../../scripts/verify_source_curation.py)
probe uses isolated originals, page files, Markdown and indices. By default,
temporary workspaces are removed on success and failure. To preserve validation
evidence separately, supply an external directory:

```sh
.venv/bin/python scripts/verify_source_curation.py --execute \
  --artifacts-dir /absolute/external/validation/source_curation \
  --output /absolute/external/validation/source_curation/report.json
```

Each invocation archives its workspace under a unique run directory before
temporary cleanup: inputs, original snapshots, extracted pages, staged findings,
curated Markdown, indices, model responses and consumer decisions. Successful
completion also writes `verification-report.json` into that archive. On failure,
the partial workspace remains available for inspection. Embedded original paths
refer to the temporary run root; resolve the same relative paths beneath the
archived run directory. Repository-internal archive destinations are rejected.
Archives are validation-only, not production RAG inputs or Git artifacts; publish
only measured summaries in documentation. The 2026-09-11 provider matrix retained
its aggregate report, but its intermediate workspace had already been cleaned
before external retention was requested. See the
[Knowledge Agent verification section](../agents/knowledge_agent.md#artifacts-and-verification)
for measured provider and regression results. These checks do not actuate devices.
