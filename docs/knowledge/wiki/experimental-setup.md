---
{"topic_id":"experimental-setup","owner":"documentation","source_refs":["docs/agents/orchestrator_agent.md","docs/modularity.md"],"source_revision":{"docs/agents/orchestrator_agent.md":"760edc6b269c1c35dacfece350d325186db98a55c47224bfcef102ee5a5f7d0c","docs/modularity.md":"542adcea353a0f49ea4d9777927dc0f161ed2642144b54e804ec79ee39b57826"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: experimental-setup","status":"reviewed"}
---

# Experimental Setup — Agreeing on a Run Contract

An experimental package describes a reusable configuration. The run contract specifies the researcher's agreed objective, conditions and scope. Experimental Setup shows those values and their proposed/applied state.

## A conversation

Researcher: What experiments are currently available?

Orchestrator: Explains the active configuration and any readiness checks still needed.

Researcher: Let's plan that experiment.

Orchestrator: Asks for the required objective, material, specimen conditions and parameter space.

Researcher: Supplies conditions or revises earlier values.

Orchestrator: Summarizes the agreement and requests execution review.

This illustrates interaction, not a fixed script. The LLM generates responses from current information. The initial greeting is bilingual; subsequent conversation follows the researcher's language.

## Updating values

Agreed inputs are saved to the same canonical Setup fields. Revised answers update their revisions and the display. Edit opens a conversation about the selected item.

Click a one-line item to open its card; click again to close it. Up to three cards can be open. Raw values and revisions belong in Technical details.

## Saving is not execution

Saving conversational inputs does not start equipment. Owner-setting proposals require separate validation and Confirm/Discard, with next-run application boundaries. Active snapshots remain unchanged; new runs read validated settings.

System questions do not reset the existing plan. Ambiguous agreement, questions, quoted examples and instructions not to execute must not become start approval. Execution requires explicit approval and existing admission checks.

[Orchestrator reference](../../agents/orchestrator_agent.md), [packages and plans](packages-and-plans.md), [test conversations](test-modes.md).
