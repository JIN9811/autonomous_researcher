---
{"topic_id":"manipulation-role","owner":"manipulation_agent","source_refs":["docs/agents/manipulation_agent.md"],"source_revision":{"docs/agents/manipulation_agent.md":"72a2cb3d4f4516270492379839ea1478e46e9c09d8a427258b7e72ff2fb46e8c"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: manipulation-role","status":"reviewed"}
---

# Manipulation Agent — Robot Tasks and Result Review

Manipulation (MAN) supervises configured policies, Skills and replay tasks within delegated scope. The LLM does not generate arbitrary joint commands or new robot policies.

## Execution sequence

1. Check specimen/run scope, configured Skills and valid Vision evidence.
2. Use bounded model review to assess task/executor suitability.
3. Pass bridge preflight, approval and safety gates.
4. Collect logs, measured joints, target telemetry and terminal state.
5. Review the result after Vision confirmation, then hand off or hold.

Use the latest execution evidence from the same session. An initial action count of zero does not invalidate later motion; a missing terminal counter does not prove that no motion occurred.

## Before and after testing

Initial tasks transfer and place the specimen. Post-test work runs the configured removal replay, checks home return against the final recorded observation state, and obtains a separate Vision clearance check.

Command completion, measured home return and an observed empty platen are distinct evidence requirements.

## Reading the report

Live Robot Pose distinguishes measured posture from the policy-target ghost. Policy Tracking shows measured and target values for selected joints. Visual alignment in the 3D environment does not prove collision safety or successful placement.

Failure, stop or uncertain external effects must not trigger automatic replay. Revalidating preserved completion evidence is different from initiating new physical work.

[Manipulation reference](../../agents/manipulation_agent.md), [Vision role](vision-role.md), [recovery boundaries](recovery.md).
