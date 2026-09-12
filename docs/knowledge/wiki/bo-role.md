---
{"topic_id":"bo-role","owner":"bo_agent","source_refs":["docs/agents/bo_agent.md"],"source_revision":{"docs/agents/bo_agent.md":"474aaf6cb038d21dae6bd2026b3a13146bff0cf95b89827ac787d8fbb5bb7a49"},"verified_at":"2026-09-13T00:00:00+00:00","applicability":"Public BO Agent responsibilities and handoff","status":"reviewed"}
---

# BO Agent

BO's LLM interprets optimization evidence, selects a permitted strategy or retrieval tool, and reviews the result. LHS, Gaussian-process fitting and acquisition optimization are numerical code responsibilities. The optimizer, not the language model, produces the next coordinates. One optimizer invocation is allowed per decision; successful computation is not repeated. next_design_request.v1 is handed through Orchestrator to Design. Global mission and routing remain with Orchestrator.

Source: [BO Agent reference](../../agents/bo_agent.md).
