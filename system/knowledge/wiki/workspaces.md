---
{"topic_id":"workspaces","owner":"documentation","source_refs":["system/runtime/runtime_ide.md","system/device_bridges/README.md","system/knowledge/wiki_memory.md","system/agents/orchestrator_agent.md"],"source_revision":{"system/runtime/runtime_ide.md":"db356c87f7118bdde62e5f67fa65c26d46e671032a9d5f26295822be11acaa04","system/device_bridges/README.md":"2354ef0475e1e54389d8876200f5b2f1204c17fa5e40be17ecc2f798f1879d53","system/knowledge/wiki_memory.md":"fc555dfc74bd8a383c2b86cfdd60d31f84ee2f53ef02b7aa4ac852cc12f81fdf","system/agents/orchestrator_agent.md":"760edc6b269c1c35dacfece350d325186db98a55c47224bfcef102ee5a5f7d0c"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: workspaces","status":"reviewed"}
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
