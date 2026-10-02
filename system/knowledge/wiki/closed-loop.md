---
{"topic_id":"closed-loop","owner":"documentation","source_refs":["system/agents/agent_api_connection_matrix.md","system/agents/equipment_agent.md","system/agents/bo_agent.md","system/agents/orchestrator_agent.md"],"source_revision":{"system/agents/agent_api_connection_matrix.md":"973e2e0c531d18485b1044e0113fdc06aa4e3b8263862c6740cd1283f70194ef","system/agents/equipment_agent.md":"21de8d0387ce55d54c666d687dcddbc443ced70cfcdaade3f0687f12fc63a396","system/agents/bo_agent.md":"19b5aa92d2356bb70995b60925e727afcc13445e3a87da836a842f4d7c14abf7","system/agents/orchestrator_agent.md":"0081e2e93bb1fd9b9139052e85c80f29c89ff8417359d735f1bf7c49dd5b2a9c"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: closed-loop","status":"reviewed"}
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
