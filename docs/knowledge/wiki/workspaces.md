---
{"topic_id":"workspaces","owner":"documentation","source_refs":["docs/runtime/runtime_ide.md","docs/device_bridges/README.md","docs/knowledge/wiki_memory.md","docs/agents/orchestrator_agent.md"],"source_revision":{"docs/runtime/runtime_ide.md":"7fedbe753f0f34415b3bfdaf429a2c9a3814d9258a0d1936184f89c8d89faf1c","docs/device_bridges/README.md":"bc735fe1a6f3bd024989e2743077e9eb42819fe94b1eb04be60298fd69763c7b","docs/knowledge/wiki_memory.md":"6f25c22ca5f150dce959a4cd39bb90997c0bac9736baa0e45cc9d8f4ba5954d4","docs/agents/orchestrator_agent.md":"760edc6b269c1c35dacfece350d325186db98a55c47224bfcef102ee5a5f7d0c"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: workspaces","status":"reviewed"}
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
