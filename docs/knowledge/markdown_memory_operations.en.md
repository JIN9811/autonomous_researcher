<!-- atr-doc
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience: [operator, developer, maintainer]
scope: [knowledge, markdown_memory, scoped_rag, ontology]
summary: Find execution knowledge, check its provenance, manage record status and explicitly process historical archives.
source_of_truth:
  - knowledge/markdown_memory.py
  - knowledge/markdown_runtime.py
  - knowledge/http_api.py
  - agents/core/knowledge/decision.py
last_verified: 2026-09-29
verified_against: dd0d772
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/knowledge/manual_rag_knowledge.en.md
supersedes: []
-->

# Find and manage execution Markdown knowledge

[한국어](markdown_memory_operations.ko.md)

Use Knowledge's Markdown search to find observations and reusable knowledge
retained from experiments. An interpretation is not a new measurement: check
numerical evidence in the original Analysis record. External manuals and papers
belong in [Source Library](manual_rag_knowledge.en.md); confirmed personal
preferences and context belong in [private memory](wiki_memory.md#private-memory-lifecycle).

First identify the run, cycle, agent and applicability conditions you need.
Search scope determines which evidence is eligible, not which answer you hope
to receive.

## Find an observation and follow its provenance

1. Open **Memory** at `/knowledge#memory`, then expand **Execution knowledge ·
   source-backed Markdown**. This preserved execution search is separate from
   the private-memory browser above it and from Ontology.
2. Fill in **Run**, **Cycle**, **Agent**, **Validity** and the needed
   **Applicability (exact JSON object)** conditions. Enter a query and choose
   **Search Knowledge**. For an export-validation issue in a particular
   protocol, combine that protocol condition with the Equipment/Knowledge
   agent scope.
3. Read a candidate excerpt, then open its full record using the same scope.
   Match the record identity, provenance, run, cycle and attempt to the original.
4. Request review-held or superseded states explicitly if needed. If no record
   matches, check scope and originals; do not substitute a differently applicable
   record as equivalent evidence.

The task is complete when the detail record is linked to its original and the
conditions match. Plausible Markdown alone does not establish measurement
quality or successful device execution.

## Search scope

Example POST `/api/knowledge/markdown/query`:

```json
{
  "query": "export validation",
  "scope": {
    "agent_id": ["equipment_agent", "knowledge_agent"],
    "status": "valid",
    "applicability": {"protocol_version": "example-v2"}
  },
  "top_k": 6
}
```

These are example conditions. Records must actually carry that metadata; the
system neither invents missing values nor changes bridge settings to match it.

- Default retrieval selects `valid`; request `needs_review` and `superseded` explicitly.
- Lists for run/cycle/agent/ontology/fidelity/status are OR within a field and AND across fields.
- All specified tags and applicability conditions must match.
- An empty list matches nothing; unknown fields return errors.
- Candidates contain short excerpts. Send the same scope and record_id to `/markdown/read` for the full body.
- The LLM can narrow caller scope, never replace conditions because categories look similar.

## Change a record's status

After checking provenance and applicability, POST `status` and `reason` to
`/api/knowledge/markdown/<record_id>/status`. For replacement, also supply
`superseded_by`: it must identify an existing valid record with the same
ontology type and applicability. Read the detail again to confirm status and
reason. Earlier revisions are retained.

Producer retries do not clear operator review holds or supersession. If the
latest file is corrupt, the record is isolated from retrieval rather than
falling back to an older valid status. Use the API instead of editing files so
that original revisions remain intact.

## Loop records and historical intake

After existing manifest/result persistence on completion, failure or
cancellation, one observation Markdown is written. Operator/runtime cancellation
remains distinct from equipment failure. Reprocessing the same execution is
idempotent; different loops and attempts remain separate observations.

Historical archive intake is explicit:

1. POST optional `run_id`, `limit` (1–500) and `cursor` from a previous
   response's `next_cursor` to `/api/knowledge/markdown/intake`.
2. Read the returned `job_id` with GET `/api/knowledge/markdown/intake/<job_id>`.
3. Inspect per-file failures and originals. If `has_more` is true, request a new
   job with the next cursor. Correct failed inputs before retrying the needed scope.

Intake does not rerun devices or invoke an LLM. Job state is file-backed, but a
job interrupted by the web process stopping does not restart automatically;
request the same scope again. The Markdown index can be rebuilt from files.
Opening the GUI does not scan every historical log or start a model.

## Storage and provenance

| Location | Content |
|---|---|
| `memory/knowledge/markdown/<run>/<cycle>/<agent>/<record>/revision-*.md` | Immutable Markdown revisions with original provenance and classification |
| `memory/knowledge/*.jsonl` | Experiment memories, patterns, performance and retained historical Evolution records |
| `runs/<run>/knowledge/` | Current Knowledge reports, LLM decisions/tool responses and prior-input snapshots |
| `runs/<run>/runtime/loops/` | Original loop/agent/attempt archives |
| `memory/knowledge/markdown_jobs/` | Explicit historical-intake job state |

## Compatibility with older Knowledge workflows

Knowledge graph and Neo4j operational dependencies are retired. Ontology
definitions, original artifacts and existing JSONL memories, patterns and
performance records remain. Evolution no longer generates records; historical
records are retained. Source Library replaces manual-specific retrieval, and
`/api/knowledge/manuals/*` returns HTTP 410. The closed-loop execution graph is
not a knowledge graph and is unchanged by this migration.

Knowledge's LLM reads evidence, judges reuse/classification and invokes scoped
search, detail and writing tools. Code owns persistence and condition checks.
Simple observation logging does not invoke an LLM after every agent completion.

## Verification boundary

Recorded API/local-model checks used synthetic evidence. The historical
two-cycle integration replaced equipment and the then-existing FEM execution
boundary with fixtures. Current Analysis owns measured-data postprocessing
only, not FEM execution. Results and reproduction details are in the
[Knowledge Agent verification record](../agents/knowledge_agent.md#artifacts-and-verification).
They are neither a new physical demonstration nor a comparative retrieval study.

The original full-document/source inspection was at `dd0d772` on 2026-09-29.
This editorial revision does not call models, change Knowledge stores or
operate equipment.
