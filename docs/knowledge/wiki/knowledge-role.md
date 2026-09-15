---
{"topic_id":"knowledge-role","owner":"knowledge_agent","source_refs":["docs/agents/knowledge_agent.md","docs/knowledge/wiki_memory.md"],"source_revision":{"docs/agents/knowledge_agent.md":"1ec005351ea74e93e614927f673fc4fb506778f0a3c1d88dabe45e36da35a04e","docs/knowledge/wiki_memory.md":"31aac9e4d4fb449190beaa7d7594f325e59ed6fb45c0d98004337659d67c4307"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: knowledge-role","status":"reviewed"}
---

# Knowledge Agent — Source-Backed Context

Knowledge (KNW) inspects, searches, reads and curates experimental evidence, literature and records for other agents. It does not replace Analysis calculations or BO selection, authorize device work or approve settings.

## Work within an experiment

1. Inspect evidence bound to the current run and loop.
2. Search permitted records and read the required sources.
3. Separate observations, interpretations and hypotheses.
4. Save source-linked notes when needed.
5. Deliver grounded context or explain the evidence gap.

Seeing a search-result ID does not mean the source was read. A successful note receipt can support rereading that new record within the same scope; it does not authorize arbitrary IDs.

## Separate stores

Public Wiki describes the platform. Private Memory holds confirmed personal preferences and research context under trusted identity. Source Library preserves literature and provenance. Execution knowledge holds run-specific measurements and decisions. These are not interchangeable memories, and conversations are not automatically published.

## Retrieved, delivered and used

Retrieved means found by search. Delivered means included in a model request. Used requires valid citation evidence referencing supplied records. Missing citations can mean Unknown, not necessarily deliberate exclusion.

Configured owner plans apply supported scopes, sources and budgets to future runs. They do not alter current experiment evidence or broaden private access.

[Knowledge reference](../../agents/knowledge_agent.md), [knowledge stores](knowledge-agent.md), [Wiki and Memory contracts](../wiki_memory.md).
