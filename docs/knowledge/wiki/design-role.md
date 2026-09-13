---
{"topic_id":"design-role","owner":"design_agent","source_refs":["docs/agents/design_agent.md"],"source_revision":{"docs/agents/design_agent.md":"ae5b8556385e94bad9e2e802aa169d5223f182ac3cd8150bba184b1f027942a8"},"verified_at":"2026-09-13T00:00:00+00:00","applicability":"Public Design Agent responsibilities and handoff","status":"reviewed"}
---

# Design Agent

Design evaluates candidate suitability within the delegated design task. The LLM selects an accepted specification or requests owner review; deterministic checks and preview generation remain code-owned. The primary handoff is design_candidate.v1 to Specimen. Global mission and routing belong to Orchestrator. Design has no physical device command. Candidate suitability is not candidate-matched performance prediction.

The internal Runtime IDE graph and backend share a validated execution definition. The LLM/tool loop is a composite operation; editing a valid route changes execution after activation, while layout changes do not. Existing downstream handoffs remain authoritative.

Source: [Design Agent reference](../../agents/design_agent.md).
