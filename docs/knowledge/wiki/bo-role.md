---
{"topic_id":"bo-role","owner":"bo_agent","source_refs":["docs/agents/bo_agent.md"],"source_revision":{"docs/agents/bo_agent.md":"c5ade5381497b765961d9a8ada9566d80ecdb34bcaec7522a043c1853107b470"},"verified_at":"2026-09-14T00:00:00+00:00","applicability":"Public BO Agent responsibilities and handoff","status":"reviewed"}
---

# BO Agent

BO's LLM interprets optimization evidence, selects a permitted strategy or retrieval tool, and reviews the result. LHS, Gaussian-process fitting and acquisition optimization are numerical code responsibilities. The optimizer, not the language model, produces the next coordinates. One optimizer invocation is allowed per decision; successful computation is not repeated. next_design_request.v1 is handed through Orchestrator to Design. Global mission and routing remain with Orchestrator.

Source: [BO Agent reference](../../agents/bo_agent.md).
