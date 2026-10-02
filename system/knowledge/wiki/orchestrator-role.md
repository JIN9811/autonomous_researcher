---
{"topic_id":"orchestrator-role","owner":"orchestrator_agent","source_refs":["system/agents/orchestrator_agent.md","system/runtime/test_mode.md"],"source_revision":{"system/agents/orchestrator_agent.md":"760edc6b269c1c35dacfece350d325186db98a55c47224bfcef102ee5a5f7d0c","system/runtime/test_mode.md":"f6e5109e07172362432ee823adf82a580dfdf51186b9e4590ca7a12ca281dbd6"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: orchestrator-role","status":"reviewed"}
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
