---
{"topic_id":"platform-overview","owner":"documentation","source_refs":["docs/README.md","docs/modularity.md","docs/runtime/three_level_control_model.md"],"source_revision":{"docs/README.md":"7350abfcdd4cc391eb39e7c840a01f2b0d84043ca39bf1544561742c2e2bd5f1","docs/modularity.md":"dbb5f75b8abe1a1b9f9a5e1b64fe7853d7da60d77ec29dd0103e9f2c2a24cfd3","docs/runtime/three_level_control_model.md":"85195ea1600067c61996f1201b29d3221cd2c91a05a038067d494b1de52d661b"},"verified_at":"2026-09-18T00:00:00+09:00","applicability":"Public AX4LAB reference: platform-overview","status":"reviewed"}
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
