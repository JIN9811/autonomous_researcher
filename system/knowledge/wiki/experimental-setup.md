---
{"topic_id":"experimental-setup","owner":"documentation","source_refs":["system/agents/orchestrator_agent.md","system/modularity.md"],"source_revision":{"system/agents/orchestrator_agent.md":"0081e2e93bb1fd9b9139052e85c80f29c89ff8417359d735f1bf7c49dd5b2a9c","system/modularity.md":"3f337170c201f3ca121b2a0e47fe5e4e90922e0191b3b0275a18d38925367f2e"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: experimental-setup","status":"reviewed"}
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
