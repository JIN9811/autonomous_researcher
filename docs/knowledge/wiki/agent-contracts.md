---
{"topic_id":"agent-contracts","owner":"agent-architecture","source_refs":["docs/agents/agent_api_connection_matrix.md","docs/runtime/three_level_control_model.md","docs/modularity.md"],"source_revision":{"docs/agents/agent_api_connection_matrix.md":"48d567dbec45fe9fa28b00b5c4782f53093123d26d52b6b4d63305916b318496","docs/runtime/three_level_control_model.md":"85195ea1600067c61996f1201b29d3221cd2c91a05a038067d494b1de52d661b","docs/modularity.md":"dbb5f75b8abe1a1b9f9a5e1b64fe7853d7da60d77ec29dd0103e9f2c2a24cfd3"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: agent-contracts","status":"reviewed"}
---

# Agent Contracts — Roles and Handoffs

A handoff identifies the run, specimen, conditions, outputs and evidence—not just completion. Each downstream owner validates the result against its own contract.

## What each owner provides

| Owner | Responsibility | Handoff |
|---|---|---|
| [Orchestrator](orchestrator-role.md) | Coordinate intent and execution | Scoped task and run contract |
| [Design](design-role.md) | Review candidate suitability | Accepted specification and rationale |
| [Specimen Making](specimen-role.md) | Execute fabrication workflow | Fabrication result and printer evidence |
| [Vision](vision-role.md) | Observe and inspect | Same-capture images and findings |
| [Manipulation](manipulation-role.md) | Supervise configured robot tasks | Execution, observation and return evidence |
| [Lab Equipment](equipment-role.md) | Run an approved test Flow | Measurement CSV and completion evidence |
| [Analysis](analysis-role.md) | Process measurements and objectives | Validated metrics and BO observation |
| [Knowledge](knowledge-role.md) | Curate and supply evidence | Source-backed context |
| [BO](bo-role.md) | Compute initial and subsequent designs | Exact coordinates and parameter space |
| [Guardian](guardian-role.md) | Review policy, safety and approval | Proceed, review or stop decision |

## Success is owner-specific

Design acceptance is not print completion. Printer telemetry reporting done does not establish completion of the current fabrication task. Valid numerical analysis may still lack the objective, coverage or provenance needed for a BO observation. None alone proves research success.

## Modular ownership

Agent packages describe owned modules and bridge dependencies. Experimental packages compose them with graph references. Importing a package does not operate equipment. ORC, KNW and GRD remain core owners.

[System guide](platform-overview.md), [agent documentation](../../agents/README.md), [experiment cycle](closed-loop.md).
