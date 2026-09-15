---
{"topic_id":"guardian-role","owner":"guardian_agent","source_refs":["docs/agents/guardian_agent.md","docs/device_bridges/plc_safety_bridge.md"],"source_revision":{"docs/agents/guardian_agent.md":"c3d77ab9777911077cf3503d55372118c3b95e5f78672a079ebe692869ce202c","docs/device_bridges/plc_safety_bridge.md":"7957b423af9436dd18175a91761f3016e0ea6dc6290a02ebf9ef8391415ed6a1"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: guardian-role","status":"reviewed"}
---

# Guardian Agent — Progression and Safety Boundaries

Guardian (GRD) evaluates policy, risk, health, evidence, approval and stop conditions to produce proceed, review, stop or error outcomes. It remains a core platform owner, distinct from ORC planning and bridges that perform physical stops.

## Two decision layers

Deterministic gates evaluate stop requests, valid state, policy, approvals and failures. Bounded LLM review considers policy and failure evidence; prose cannot authorize a state blocked by code. Unknown states do not become fallback success.

| Check | Question |
|---|---|
| Current state and health | Is the information valid for this decision? |
| Failures and uncertain effects | Is there evidence that repeating work is permissible? |
| Approvals and stops | Are owner and operator decisions respected? |
| Handoff evidence | Does it match the current run and support the next step? |

Past incidents are audit history, not necessarily current failures. Past success is not current safety clearance.

## Owner plans and PLC

The Guardian owner plan supplies supported advisory evidence context for future runs. It cannot remove thresholds, deterministic checks, operator stops or equipment interlocks.

The PLC service latch is checked separately during start, recovery and Resume. Restoring a checkpoint does not clear the latch. A software stop request and the resulting physical stop are distinct facts.

Read the decision rationale, current blockers, required approvals, next action and incident history separately. Merely viewing the report does not resolve an approval.

[Guardian reference](../../agents/guardian_agent.md), [PLC bridge](../../device_bridges/plc_safety_bridge.md), [recovery boundaries](recovery.md).
