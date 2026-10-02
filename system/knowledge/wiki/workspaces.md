---
{"topic_id":"workspaces","owner":"documentation","source_refs":["system/runtime/runtime_ide.md","system/device_bridges/README.md","system/knowledge/wiki_memory.md","system/agents/orchestrator_agent.md"],"source_revision":{"system/runtime/runtime_ide.md":"25e739d3647c5a458ce57cc19fd5476d80a481a8993d3b1929ff7907904f4e5c","system/device_bridges/README.md":"4947359cd3bf80e5338e1d8d2a29afea210f3990c2fe1899b7f6f19f602d87b6","system/knowledge/wiki_memory.md":"895db872a7c91ce24f2ec2bcf880ddd0c7f15c3dd55696dccbf1b12b1efb3f42","system/agents/orchestrator_agent.md":"0ead09417efae55effb2c035e52c34390861e6b3946cd70c79a447f8c771e39e"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: workspaces","status":"reviewed"}
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
