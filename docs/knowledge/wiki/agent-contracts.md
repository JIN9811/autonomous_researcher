---
{"topic_id":"agent-contracts","owner":"agent-architecture","source_refs":["docs/agents/agent_api_connection_matrix.md"],"source_revision":{"docs/agents/agent_api_connection_matrix.md":"18c2cc8fbbc26f6c5ff3ef5272f78c9e6ec7a1aee70d11c6e0524250c4926ac5"},"verified_at":"2026-09-13T00:00:00+00:00","applicability":"Public agent role and handoff orientation","status":"reviewed"}
---

# Agent roles and handoffs

This compact guide is a reference to the current agent API matrix. It does not
claim that every role has consumed this Wiki in a model request; that requires
separate delivery and use evidence.

- **ORC / Orchestrator** classifies intent, compiles bounded plans and sends
  work to the responsible agent; it does not directly actuate devices.
- **Design** evaluates candidates and hands an accepted experiment
  specification to **Specimen Making**, which owns fabrication intent and its
  existing printer handoff.
- **Vision** produces freshness-bounded observation evidence; **Manipulation**
  owns bounded transfer/task decisions after that evidence.
- **Lab Equipment** owns approved equipment flows and terminal review;
  **Analysis** owns interpretation and objective evidence rather than physical
  actuation.
- **Knowledge** curates evidence and scoped context; **BO** proposes numerical
  candidates; **Guardian** applies deterministic safety and approval policy.

Every handoff remains subject to the owner’s validation, current state, and
existing approval gates. A Wiki citation never authorizes a setup change, run,
model call, or device operation.
