---
{"topic_id":"workspaces","owner":"documentation","source_refs":["system/runtime/runtime_ide.md","system/device_bridges/README.md","system/knowledge/wiki_memory.md","system/agents/orchestrator_agent.md"],"source_revision":{"system/runtime/runtime_ide.md":"a891a20f0e99a15633ee75837bfa35a4c80755677fb7fbe52132392250186a24","system/device_bridges/README.md":"726e0ab41a968da898d8549f26bf618dc29568423d6241b1195d8861437e7c49","system/knowledge/wiki_memory.md":"278893b65e6ab9bebde9438a5c59d87f6462b5b1c509230f1f0fb17f320eda88","system/agents/orchestrator_agent.md":"0081e2e93bb1fd9b9139052e85c80f29c89ff8417359d735f1bf7c49dd5b2a9c"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: workspaces","status":"reviewed"}
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
