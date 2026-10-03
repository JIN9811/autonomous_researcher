---
{"topic_id":"platform-overview","owner":"documentation","source_refs":["docs/README.md","docs/modularity.md","docs/runtime/three_level_control_model.md"],"source_revision":{"docs/README.md":"b8bc4404dcce840e393de444e078c645f529ffdeee04b3b33447bebff7b3a812","docs/modularity.md":"542adcea353a0f49ea4d9777927dc0f161ed2642144b54e804ec79ee39b57826","docs/runtime/three_level_control_model.md":"e825ed068815e8d849568da873b65b10ef9203c9e7b0f576758efb7a6c955ce4"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: platform-overview","status":"reviewed"}
---

# AX4LAB Platform — System Guide

AX4LAB connects experiment planning, design, fabrication, observation, transfer, testing, analysis and the next design. Agents make bounded decisions, code computes and validates, and device bridges perform permitted physical actions.

## Start here

1. [Experiment cycle](closed-loop.md): from one specimen to the next candidate.
2. [Packages and plans](packages-and-plans.md): agents, bridges, reusable experiments and contracts.
3. [Conversation and Setup](experimental-setup.md): agreeing on experiment conditions.
4. [Test modes](test-modes.md): virtual bridges, installed printers and physical printing.
5. [GUIs and workspaces](workspaces.md): where to inspect each part of the system.
6. [Metrics](measurement-metrics.md), [BO plots](bo-visualization.md) and [artifacts](artifacts.md): interpreting results.
7. [Agent roles and handoffs](agent-contracts.md): responsibilities and detailed guides.

## Responsibility boundaries

| Area | Responsibility |
|---|---|
| High | Bounded LLM reasoning and decisions |
| Middle | APIs, internal processes, computation, validation and tool calls |
| Low | Physical execution through bridges and drivers |
| Guardian | Safety, approval and stop conditions across levels |
| Knowledge | Preserving and delivering source-backed information and evidence |

These are responsibility boundaries, not folder locations or file counts. See [control levels](control-levels.md).

## Using this Wiki

Operational LLM decisions receive only a reviewed, owner-specific Runtime decision reference excerpt. Full articles remain available for user-facing explanations and Wiki browsing. Examples, historical recovery paths, UI limits and described defaults are not executable rules, current observations or extra acceptance conditions. Missing Wiki material is not itself missing experimental evidence.

See the [runtime reference safety audit](../runtime_reference_safety.md) for the reviewed boundary and page-by-page disposition.

The Wiki is public reference material for readers and agents. Current device availability, the active graph and the run contract must be checked with runtime owners. A documented capability is not proof of readiness or permission to execute.

Each page records its sources and review date. Changed source documents can make a page stale and require review. Private conversations and past experimental results are not automatically published here.

[Documentation index](../../README.md), [modularity guide](../../modularity.md).
