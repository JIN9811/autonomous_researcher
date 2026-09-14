---
{"topic_id":"analysis-role","owner":"analysis_agent","source_refs":["docs/agents/analysis_agent.md"],"source_revision":{"docs/agents/analysis_agent.md":"819c2f8af6aaa4385f8b41a664b95b89b8f34d0f36c7c334cf0e6ab666827ed8"},"verified_at":"2026-09-14T00:00:00+00:00","applicability":"Public Analysis Agent responsibilities and handoff","status":"reviewed"}
---

# Analysis Agent

Analysis validates and processes measured data and produces objective evidence for Knowledge and BO. Numerical parsing, metrics and objective computation remain code-owned. Bounded LLM roles select processing actions and review measurement admissibility. The package has no device bridge; numerical tools calculate curves, metrics and the experiment-configured objective. A model explanation cannot overwrite a measurement or declare a new physical validation.

Source: [Analysis Agent reference](../../agents/analysis_agent.md).
