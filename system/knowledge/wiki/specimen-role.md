---
{"topic_id":"specimen-role","owner":"specimen_agent","source_refs":["system/agents/specimen_agent.md","system/runtime/test_mode.md"],"source_revision":{"system/agents/specimen_agent.md":"fe47900b6cd81e0a23364e8767893d2cee08a77b0d4161b90b64f4d9fd04103d","system/runtime/test_mode.md":"4a525fdc1da418bb7ed17c8e2a0d0659ee8a7e976a71a5595348e00d297b4270"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: specimen-role","status":"reviewed"}
---

# Specimen Making Agent — Fabrication

## Runtime decision reference

Specimen Making owns the configured fabrication task. Its current run-bound execution profile and registered workflow determine physical effects and required evidence. Descriptions of other printer modes are not instructions to skip, repeat or add work. Telemetry alone is not proof of this task's completion.

## Overview

Specimen Making (SPC) connects accepted Design specifications to fabrication. It owns geometry/manufacturing checks, bounded LLM decisions, registered printer-tool calls and result review—not merely printer status display.

## Fabrication sequence

1. Receive the accepted specification and manufacturing conditions.
2. Check geometry, manufacturing constraints and path prerequisites.
3. After a permitted model decision, use the existing slicing/printer workflow.
4. Execute printing or ejection according to the selected mode.
5. Collect evidence for Vision and Manipulation handoff.

Printer Fleet owns connections, provider selection, telemetry and commands. Bambu and Prusa are providers within the same printer boundary. The agent package itself does not execute printer commands.

## Interpreting status

Printer running/done is device telemetry. SPC completion depends on the current run's intent, progress and required evidence. Another print's state or a polling result is not current-agent success.

Physical printing executes the full project with cooling and autoejection conditions. Installed-printer testing slices normally, then uses an ejection-only project without the print body or cooling wait. No printing does not mean no physical actuation.

## Where to look

The Report shows fabrication conditions, readiness, Agentic Progress and handoff results. The 3D Printer Workspace exposes connection, camera, print defaults and G-code/autoejection settings. Previewing or saving settings does not authorize printing.

[Specimen reference](../../agents/specimen_agent.md), [test modes](test-modes.md), [packages and bridges](packages-and-plans.md).
