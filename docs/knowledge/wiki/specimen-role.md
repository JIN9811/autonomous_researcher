---
{"topic_id":"specimen-role","owner":"specimen_agent","source_refs":["docs/agents/specimen_agent.md","docs/runtime/test_mode.md"],"source_revision":{"docs/agents/specimen_agent.md":"d72dc520dcca1475e03b5ff7dcafa477f2935e1461a903b03ab8813db7dda232","docs/runtime/test_mode.md":"1373447525b8865130129acc229c2220c075b00dc6d9fc193807fd43c54793ce"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: specimen-role","status":"reviewed"}
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
