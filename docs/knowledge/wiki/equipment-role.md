---
{"topic_id":"equipment-role","owner":"equipment_agent","source_refs":["docs/agents/equipment_agent.md"],"source_revision":{"docs/agents/equipment_agent.md":"4baaf79dcb3435baceb438fdb20cb4516e33a38e92a2c0d60f94e2e1a8999394"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: equipment-role","status":"reviewed"}
---

# Lab Equipment Agent — Testing and Measurement Handoff

## Runtime decision reference

Equipment reviews the supplied approved Flow, scoped task results and measurement export. Current Flow definitions and code-owned gates determine required steps. Documentation is not an instruction to reorder or repeat Skills. A file or a previous success alone does not prove this execution completed.

## Overview

Lab Equipment (EQP) executes configured Skills and Flows in an approved order, then reviews test completion and measurement export. Arbitrary model text is not executed as an equipment command.

## Profile, Skill and Flow

A Profile defines the equipment and execution environment. A Skill is a configured task; a Flow combines tasks with ordering and conditions. The agent selects and reviews supplied Flow candidates. Existing Windows/Local workers and bridges perform the physical work.

## From input to Analysis

1. Receive specimen identity, test conditions and approved scope.
2. Check readiness and manage configured Skills.
3. Collect test state, screens, observations and exported CSV for terminal review.
4. Follow Manipulation removal and Vision confirmation paths where required.
5. Hand verified measurements and provenance to Analysis.

CSV existence alone does not satisfy completion. Run/specimen identity, integrity and completed task order must also agree.

## Handling errors

If a physical test completed but terminal review failed, recovery can revalidate the same run scope and original CSV hash. It does not repeat Skills or substitute another specimen. Partial execution or uncertain external effects remain blocked.

Read Flow progress, actual block results, terminal review and handoff status together. Previous failures remain in the audit history and are distinct from the current decision.

[Equipment reference](../../agents/equipment_agent.md), [Analysis role](analysis-role.md), [recovery](recovery.md).
