---
{"topic_id":"workspaces","owner":"documentation","source_refs":["docs/runtime/runtime_ide.md","docs/device_bridges/README.md","docs/knowledge/wiki_memory.md","docs/agents/orchestrator_agent.md"],"source_revision":{"docs/runtime/runtime_ide.md":"be6b4b1fe974b657fd372f5d220d15c50857020ed86e9b5ae01c0baf532f7037","docs/device_bridges/README.md":"ac1fb55b57d4c24b7c2031137aabb9c9098ad2136ab397e459fcd3177172b2d7","docs/knowledge/wiki_memory.md":"31aac9e4d4fb449190beaa7d7594f325e59ed6fb45c0d98004337659d67c4307","docs/agents/orchestrator_agent.md":"31147fe1724801e5651b59e083b50e3da41715aa2eedcac54fd993031c3b4f73"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: workspaces","status":"reviewed"}
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
