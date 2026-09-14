---
{"topic_id":"knowledge-role","owner":"knowledge_agent","source_refs":["docs/agents/knowledge_agent.md"],"source_revision":{"docs/agents/knowledge_agent.md":"7bf052d608dc335f4e91bf8a4d5e22a0ad9a26bdd7468c03aef78ea43ca37733"},"verified_at":"2026-09-14T00:00:00+00:00","applicability":"Public Knowledge Agent responsibilities and handoff","status":"reviewed"}
---

# Knowledge Agent

Knowledge's LLM curates source-backed reusable evidence, classifies it using the ontology and chooses scoped records to read or publish. Markdown storage, provenance validation and lifecycle checks remain code-owned. Existing execution memory, patterns and Evolution evidence are preserved. Ontology definitions remain, but the active knowledge graph, Neo4j synchronization and Graphify reconciliation are retired. Numerical observations remain Analysis-owned; Knowledge does not optimize their values or operate devices.

Source: [Knowledge Agent reference](../../agents/knowledge_agent.md).

Configured owner declarations travel as module configuration and affect only
supported Knowledge settings in a later pinned run; no separate plan store exists.
