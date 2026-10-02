---
{"topic_id":"orchestrator-role","owner":"orchestrator_agent","source_refs":["system/agents/orchestrator_agent.md","system/runtime/test_mode.md"],"source_revision":{"system/agents/orchestrator_agent.md":"0081e2e93bb1fd9b9139052e85c80f29c89ff8417359d735f1bf7c49dd5b2a9c","system/runtime/test_mode.md":"4a525fdc1da418bb7ed17c8e2a0d0659ee8a7e976a71a5595348e00d297b4270"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: orchestrator-role","status":"reviewed"}
---

# Orchestrator Agent — Conversation and Coordination

## Runtime decision reference

Orchestrator coordinates the supplied user request, validated run contract, active graph and owner handoffs. Registered candidates and current evidence determine available transitions. Explanatory sequences and example conversations do not define a new plan, approval, goal, device state or missing prerequisite.

## Overview

Orchestrator (ORC) interprets research requests and connects them to work supported by the current graph and owners. It distinguishes system questions, condition changes and experiment starts; it does not directly operate printers, robots or test machines.

## From conversation to execution

1. Greet the researcher in English, followed by Korean, without demanding experiment details.
2. Explain available experiments from the active graph, without claiming unverified device readiness.
3. Once planning is agreed, ask for required conditions and update Experimental Setup.
4. Review conditions, obtain explicit execution approval and pass existing admission gates.
5. Coordinate results, holds and next actions under the current contract.

The LLM conducts this conversation. Agreement to plan is not approval to execute. Intervening system questions do not erase agreed conditions.

## Inputs and outputs

Inputs include user intent, current settings/graph, owner state and prior handoffs. Outputs are validated plans, setting proposals, task handoffs and explanations—not invented equipment-completion evidence.

Conversational Setup updates modify the same block and emit change events. Applying owner settings to the next run requires separate validation and does not retroactively mutate an active snapshot.

## Reading the report

Read the current contract, Orchestration Plan, Handoff and Next Action together. Distinguish saved settings, prepared work and actual execution. Wiki citations and model responses cannot release safety gates.

Test modes use the same conversation and validation path with an automatic scenario participant.

[Conversation and Setup](experimental-setup.md), [test modes](test-modes.md), [Orchestrator reference](../../agents/orchestrator_agent.md).
