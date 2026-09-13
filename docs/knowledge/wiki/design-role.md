---
{"topic_id":"design-role","owner":"design_agent","source_refs":["docs/agents/design_agent.md"],"source_revision":{"docs/agents/design_agent.md":"cdf8b41d5553b34c2247ceb6e731454091a2c801dfdd01eed12c8cb4fc091709"},"verified_at":"2026-09-13T00:00:00+00:00","applicability":"Public Design Agent responsibilities and handoff","status":"reviewed"}
---

# Design Agent

Design evaluates candidate suitability within the delegated design task. The LLM selects an accepted specification or requests owner review; deterministic checks and preview generation remain code-owned. The primary handoff is design_candidate.v1 to Specimen. Global mission and routing belong to Orchestrator. Design has no physical device command. Candidate suitability is not candidate-matched performance prediction.

The internal Runtime IDE graph and backend share a validated execution definition. The LLM/tool loop is a composite operation; editing a valid route changes execution after activation, while layout changes do not. Existing downstream handoffs remain authoritative.

The Middle decision also exposes code-owned internal tools, validation and evidence relationships. Low includes software functions, not only equipment. CODE boxes inspect implementation references and are not extra executable steps. Documentation figures use a light theme independently of the IDE.

Source: [Design Agent reference](../../agents/design_agent.md).
