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
  - agents/core/knowledge/source_curation.py
  - mcp_tools/source_tools.py
last_verified: 2026-09-29
verified_against: dd0d772
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/knowledge/markdown_memory_operations.en.md
  - docs/oldversion/superpowers/specs/2026-09-11-source-curation-design.md
supersedes: []
-->

# Curate and retrieve reference sources

[한국어](manual_rag_knowledge.ko.md)

Use Source Library when you want an agent to consult a manual, paper or other
submitted reference with traceable citations. Use
[execution Markdown](markdown_memory_operations.en.md) for observations from
runs, and [Wiki and private memory](wiki_memory.md) for platform explanations
or confirmed personal context. These stores have different scopes; adding a
source does not add an experimental observation or approve an action.

This guide follows one source from the inbox to a ready, cited note. You need a
configured Knowledge model and permission to submit the original. Generated
knowledge stays local; public release requires the
[publication review](publication.md). Source Library does not start a model server.

<a id="intake-and-publication"></a>
## Add a source and check its publication

1. Open **Knowledge Workspace → Source Library** at `/knowledge#manuals`.
2. Place source material in `docs/knowledge/manuals/sources/`. Keep generated
   output outside this inbox.
3. Enable **Automatically curate stable source changes**. This choice is saved;
   **Scan Sources** performs discovery without waiting for model inference.
4. Inspect source progress. Stable new or changed contents are processed by
   the registered Knowledge model when its existing inference lease is available.
5. Enter a phrase such as `export validation` in **Reference query**, set the
   needed **Category**, **Tags** and exact **Applicability**, then choose
   **Retrieve Evidence**. Check that the result belongs to the intended manual;
   the API below also supports explicit source-identity scope.
6. Open the ready note's detail. Check its source identity, page/block citations
   and original extracted Markdown before using the advice. A ready publication
   is the completion state of curation, not proof that every scientific statement
   is correct or applicable to the current equipment.

The worker preserves a content-addressed original and complete extracted text.
Paginated sources are split into page files and read page-by-page. Bounded
consolidation produces **one curated Markdown output per original source**,
retaining quantities, conditions and page/block citations. Intermediate page
findings are not separate search results. Extraction is not an LLM summary.

The worker does not start a model server. Disabling intake prevents new source
jobs; an already active source may finish. Workflow requests take priority at
the next existing inference-lease boundary, not by interrupting an active call.

## Keep the right version eligible

Equal content shares one identity and path aliases. Changed content receives a
new identity; the earlier complete publication remains available for audit.
Default retrieval includes only current, ready sources. Removing an inbox file
makes its old path version ineligible without deleting historical artifacts.
Classification changes the derived output location, never the original path.

If a search is empty, first check source readiness and scope. Do not remove
applicability conditions merely to obtain an answer: a plausible note for a
different instrument or protocol is not a substitute.

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

## Compatibility and recorded verification

Source Library replaces the former manual-specific runtime. The retained
`manual_rag_knowledge` document URLs are compatibility entry points; the old
`/api/knowledge/manuals/*` endpoints return HTTP 410. Originals, historical
artifacts and ontology definitions are preserved.

The original full-document/source inspection was at `dd0d772` on 2026-09-29.
The editorial reorganization and language pairing do not rerun its provider
checks, mutate Knowledge stores or operate devices.
