---
{"topic_id":"guardian-role","owner":"guardian_agent","source_refs":["docs/agents/guardian_agent.md"],"source_revision":{"docs/agents/guardian_agent.md":"7c303b0a2ee01ecd41581fb84309543d7aafc7eab23f5765ca1077763baa70bf"},"verified_at":"2026-09-14T00:00:00+00:00","applicability":"Public Guardian Agent responsibilities and handoff","status":"reviewed"}
---

# Guardian Agent

Guardian provides supervisory policy assessment and an advisory LLM note. Deterministic policy, consistency and freshness gates retain authority over continuation, review, stop and error outcomes. Unknown evidence must not become permission through fallback. Orchestrator translates the resulting route decision; device-specific interlocks, emergency behavior and physical command acknowledgement remain hardware and bridge responsibilities. Knowledge retrieval never replaces these deterministic gates.

Source: [Guardian Agent reference](../../agents/guardian_agent.md).

Guardian may receive configured reference-only advisory context from a pinned
module declaration. Deterministic gates, operator stops and device authority remain mandatory.
