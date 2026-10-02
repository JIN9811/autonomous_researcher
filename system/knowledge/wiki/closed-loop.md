---
{"topic_id":"closed-loop","owner":"documentation","source_refs":["system/agents/agent_api_connection_matrix.md","system/agents/equipment_agent.md","system/agents/bo_agent.md","system/agents/orchestrator_agent.md"],"source_revision":{"system/agents/agent_api_connection_matrix.md":"0f2f026a8e854f93de40c3408949ea34569f4fbdf95fc4293d1b3df225a5706e","system/agents/equipment_agent.md":"ef49a454b482be24ec5fd6ae347e287cca26383f285165b9ec8de2ef3f7f9a8e","system/agents/bo_agent.md":"0aa6e34c8c4bacc0b172b5d9a1d51d94a831cbf1ebcb526185716501e645aff9","system/agents/orchestrator_agent.md":"0ead09417efae55effb2c035e52c34390861e6b3946cd70c79a447f8c771e39e"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: closed-loop","status":"reviewed"}
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
