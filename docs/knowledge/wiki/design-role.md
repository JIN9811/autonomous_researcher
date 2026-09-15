---
{"topic_id":"design-role","owner":"design_agent","source_refs":["docs/agents/design_agent.md","docs/runtime/three_level_control_model.md"],"source_revision":{"docs/agents/design_agent.md":"16daa0bdf27936a9945da327a53e382c47b1d52500010c4eb687aaf316eeb600","docs/runtime/three_level_control_model.md":"85195ea1600067c61996f1201b29d3221cd2c91a05a038067d494b1de52d661b"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: design-role","status":"reviewed"}
---

# Design Agent — Specifications and Candidate Review

Design (DSN) turns experiment requests and BO coordinates into a checked specimen specification. Code prepares candidates, checks and geometry; the LLM chooses further checks, acceptance or owner review from supplied evidence. Acceptance is neither fabrication success nor validated performance prediction.

## Inputs and outputs

Inputs are objectives, constraints, fixed material/geometry settings, and BO's requested parameters and parameter space. Outputs are the experiment specification, design candidate and handoff packet consumed by Specimen Making.

Coordinates retain their precision: a requested cell size of 7.13789 mm must not become 7 mm for display convenience. Out-of-range values and manufacturing violations are rejected with reasons, not silently adjusted.

## Reading the report

| Section | Meaning |
|---|---|
| Design Space | Requested variables, ranges and fixed conditions |
| Candidate Comparison | Available evidence for comparing candidates |
| Constraint Checks | Compliance and missing evidence |
| Handoff | Exact specification for fabrication |

Historical scores remain historical evidence, not measured performance or physical validation of the current candidate. Suitability checks and measured objective evaluation are separate stages.

## Internal structure

High covers LLM decisions. Middle covers candidate generation, checks, previews and handoffs. There is no direct-device Low task. Runtime IDE explains the same execution definition; CODE boxes are not additional execution stages.

![Design inputs and Specimen Making handoff](../../agents/assets/figures/design_01_closed_loop_handoffs.svg)

[Design reference](../../agents/design_agent.md), [BO role](bo-role.md), [Specimen Making role](specimen-role.md).
