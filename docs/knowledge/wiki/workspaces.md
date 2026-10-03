---
{"topic_id":"workspaces","owner":"documentation","source_refs":["docs/runtime/runtime_ide.md","docs/device_bridges/README.md","docs/knowledge/wiki_memory.md","docs/agents/orchestrator_agent.md"],"source_revision":{"docs/runtime/runtime_ide.md":"0d96e7d9a4ae6ff0cac03e0a60b4c4721249e38386fb4edaacb9f46db39496e5","docs/device_bridges/README.md":"e14b22991dfcbd128e12762628873fa930fb8f4b76fb7bf25928b16c9d0ac531","docs/knowledge/wiki_memory.md":"0950b2b866f89c3f89d51f7b925b2e68bc04b5a50091212de8eb970b0fd9a5ce","docs/agents/orchestrator_agent.md":"38d1189736e3afb895174e4072b8a4e5820cd29c0324f3c352cc48d66bcb3a5a"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: workspaces","status":"reviewed"}
---

# Workspaces — Where to Inspect the System

AX4LAB separates model/run control, experiment monitoring, configuration and device diagnostics. Opening a screen or selecting an item does not itself approve or execute an experiment.

| Screen | Primary purpose |
|---|---|
| Main GUI | Model/run controls and workspace entry points |
| Live GUI | Research conversation, Setup, agent Reports and evidence |
| Runtime IDE | Graph/module structure, connections, validation and versions |
| Device Workspace | Bridge connections, settings, state and manual diagnostics |
| Knowledge Workspace | Wiki, Memory, Source Library, Delivery and Ontology |

## Reading Live GUI

First check the run and selected agent. Report presents owner progress/results, Artifacts exposes related files, and Timeline shows event order. Conversation text and device telemetry are not themselves agent-completion decisions.

Experimental Setup shows conditions and setting state. Message expansion and Chat pin affect presentation, not the backend contract.

## Runtime IDE

Package configuration, graph attachment, module application and execution are different states. Structural edits pass existing validation, save and activation boundaries. Deleting a node does not automatically create an alternative path.

Read LLM, LLM call and CODE relationships using the [control-level guide](control-levels.md).

## Device workspaces

Inspect printer providers, robot environments, camera observations and test-machine task connections in their owning bridge workspace. Manual controls may have real physical effects. Work performed outside the automatic experiment is not automatic handoff-success evidence.

[Runtime IDE reference](../../runtime/runtime_ide.md), [bridge index](../../device_bridges/README.md), [artifact explorer](artifacts.md).
