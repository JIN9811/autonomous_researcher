---
{"topic_id":"agent-contracts","owner":"agent-architecture","source_refs":["system/agents/agent_api_connection_matrix.md","system/runtime/three_level_control_model.md","system/modularity.md"],"source_revision":{"system/agents/agent_api_connection_matrix.md":"973e2e0c531d18485b1044e0113fdc06aa4e3b8263862c6740cd1283f70194ef","system/runtime/three_level_control_model.md":"15330a201059320411303aab741381c81835651b897c9d7161e3d507578da9e6","system/modularity.md":"3f337170c201f3ca121b2a0e47fe5e4e90922e0191b3b0275a18d38925367f2e"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: agent-contracts","status":"reviewed"}
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
