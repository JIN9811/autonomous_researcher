---
{"topic_id":"closed-loop","owner":"documentation","source_refs":["docs/agents/agent_api_connection_matrix.md","docs/agents/equipment_agent.md","docs/agents/bo_agent.md","docs/agents/orchestrator_agent.md"],"source_revision":{"docs/agents/agent_api_connection_matrix.md":"48d567dbec45fe9fa28b00b5c4782f53093123d26d52b6b4d63305916b318496","docs/agents/equipment_agent.md":"833fc4d6c8181a3dc719f33b1c7d948c3f424798c4425f0fb36cd683e3852531","docs/agents/bo_agent.md":"c94fd36eaae85610dc266287337db37f8315640ca1fe4a7a7f26a22bdea47c14","docs/agents/orchestrator_agent.md":"2e68c1fca24538dc108f224f1ec13a171e058cdc23aed816045e28048eb40bff"},"verified_at":"2026-09-28T00:00:00+09:00","applicability":"Public AX4LAB reference: closed-loop","status":"reviewed"}
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
