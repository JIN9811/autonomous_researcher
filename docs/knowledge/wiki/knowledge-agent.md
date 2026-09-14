---
{"topic_id":"knowledge-agent","owner":"knowledge","source_refs":["docs/agents/knowledge_agent.md"],"source_revision":{"docs/agents/knowledge_agent.md":"bb87bd7a08bf38bf15050163a6fdb50ec71377e0126d7e496d9b3da7bd1f6598"},"verified_at":"2026-09-14T00:00:00+00:00","applicability":"Knowledge evidence and memory orientation","status":"reviewed"}
---

# Knowledge Agent role

The Knowledge Agent manages evidence-oriented knowledge outputs and provides
reference context to consumers. It does not own experiment setup approval,
runtime execution, or physical devices. Private user memory is separately
scoped and is unavailable without a trusted server-provided principal.

References returned by the Wiki are evidence pointers, not commands or a
substitute for the responsible agent's current-state readback.
An optional applied owner declaration may narrow supported Knowledge inputs for
a future pinned run; it does not grant private-memory access or execution authority.
