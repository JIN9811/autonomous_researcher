---
{"topic_id":"closed-loop","owner":"documentation","source_refs":["docs/agents/agent_api_connection_matrix.md","docs/agents/equipment_agent.md","docs/agents/bo_agent.md","docs/agents/orchestrator_agent.md"],"source_revision":{"docs/agents/agent_api_connection_matrix.md":"8dec383e37ad90c80396c81d9686d97dd3391aef55aeec0800bb9d61d88940ef","docs/agents/equipment_agent.md":"86682debedafd4b6511f5a0d96ada348e5c1d4f3b8d53a443107fcfac2c4e671","docs/agents/bo_agent.md":"26e0e33bde308d763ff38fb60e5438658fe3dea6ae26e51f7780d5da4e3a11ce","docs/agents/orchestrator_agent.md":"d247bee907be524007a676b3358cb11ce44182f9fc9f2e62481e5e73e12ea1ef"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: closed-loop","status":"reviewed"}
---

# Closed Loop — From Specimen to Next Design

The experiment cycle turns agreed conditions into a specimen and measurements, then feeds the results into the next design. Actual graph transitions and owner gates govern execution, not a simplified sequence diagram.

## One cycle

1. Orchestrator collects goals and conditions, defining the run contract and task scope.
2. Design preserves requested coordinates while checking candidates and manufacturing constraints.
3. Specimen Making executes fabrication and supplies evidence.
4. Vision and Manipulation perform the required observation, transfer and placement checks.
5. Lab Equipment runs the approved test Flow and exports measurements.
6. Required post-test removal involves Manipulation and a separate Vision check.
7. Analysis processes original data and validates objective metrics.
8. Knowledge curates evidence and BO computes the next coordinates.
9. The plan and existing supervisory/safety conditions lead to the next Design, completion or a hold.

## Beyond the arrows

Even an Equipment-to-Analysis summary may contain removal, home-return and visual-clearance gates. Guardian is not merely a final review step; equipment interlocks and approvals remain active at the relevant boundaries.

The first LHS request can precede measurement. This applies BO initialization policy without fabricating observations. Subsequent points follow initial-design progress or the active optimization policy.

## Completion and repetition

Each success belongs to its owner's task. Design acceptance, print completion, a valid measurement and achievement of the research goal are different states. Passing results to another cycle does not waive fixed conditions or safety checks.

[Handoff contracts](agent-contracts.md), [test modes](test-modes.md), [Equipment reference](../../agents/equipment_agent.md), [BO reference](../../agents/bo_agent.md).
