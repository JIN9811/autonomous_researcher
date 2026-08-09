---
doc_type: design
subtype: repository
status: review
authority: proposal
audience:
  - researcher
  - reviewer
  - developer
  - maintainer
scope:
  - documentation_governance
  - repository_navigation
  - archival
summary: Approved design for minimal domain-local document relocation and strict archival of unused, replaced material.
decision_status: approved
related_docs:
  - docs/README.md
  - docs/document_manifest.yaml
  - docs/standards/documentation_standard.md
  - docs/superpowers/specs/2026-08-08-documentation-governance-design.md
supersedes: []
---

# Document Location Cleanup Design

## Summary

This Design performs a minimal location cleanup without treating age, a legacy
format, or a missing inbound link as proof that a document is unused. Active
research notes, implementation history, and evidence stay available under
domain-local subdirectories. Only one self-contained image package is archived:
the unreferenced GPT-generated PNG schematic bundle that has been replaced by
the editable, implementation-backed agent figures.

## Goals

1. Put clearly misplaced research, historical plan, and evidence documents in
   predictable domain-local directories.
2. Preserve implementation plans and evidence even when normal reading paths
   do not link them.
3. Archive only material with no active consumer and a named replacement.
4. Update every repository reference affected by a move.
5. Define archive admission, indexing, and restoration rules for future work.

## Non-goals

- Reorganizing every legacy document by document type.
- Moving package payloads or canonical instruction copies.
- Treating ungoverned documents as unused.
- Changing application, agent, bridge, API, graph, or test behavior.
- Modifying or committing the pre-existing `.env.example` working-tree change.

## Decision

Use a strict, reviewable relocation batch. Keep active material near its domain
and add one level only when the subtype is unambiguous: `research`, `history`,
or `evidence`. Archive replaced material under
`docs/oldversion/<original-relative-path>` so its former context remains clear.

## Relocation Map

| Current path | New path | Classification | Reason |
|---|---|---|---|
| `docs/lerobot_robotis_pre_research.md` | `docs/hardware/research/lerobot_robotis_pre_research.md` | active research | hardware integration research belongs with the LeRobot/ROBOTIS domain |
| `docs/hardware/isaac_pick_place_leisaac_alignment.md` | `docs/hardware/research/isaac_pick_place_leisaac_alignment.md` | active research | implementation-backed alignment notes are research context, not an operator Guide |
| `docs/gui/live_gui_chat_message_separation_plan.md` | `docs/gui/history/live_gui_chat_message_separation_plan.md` | implementation history | completed GUI planning record remains available but outside the active GUI entry path |
| `docs/gui/live_gui_evolution_plan.md` | `docs/gui/history/live_gui_evolution_plan.md` | implementation history | completed GUI planning record remains available but outside the active GUI entry path |
| `docs/runtime/guardian_improvement_09_audit.md` | `docs/runtime/evidence/guardian_improvement_09_audit.md` | evidence | dated implementation audit belongs under runtime evidence |
| `docs/hardware/lab_equipment_utm_visual_control_completion_audit.md` | `docs/hardware/evidence/lab_equipment_utm_visual_control_completion_audit.md` | evidence | completion audit remains linked from active equipment documentation |
| `docs/hardware/prusa_mk4s_live_validation_20260506.md` | `docs/hardware/evidence/prusa_mk4s_live_validation_20260506.md` | evidence | dated live-validation record belongs under hardware evidence |
| `docs/github_docs_image/autonomous_researcher_gpt_image_schematics/` | `docs/oldversion/github_docs_image/autonomous_researcher_gpt_image_schematics/` | archived | no active inbound reference; replaced by editable DOT/SVG agent figures |

## Archive Admission Rule

A file or self-contained directory may enter `docs/oldversion/` only when all
of the following are demonstrated in the same change:

1. no active README, document, code, configuration, validator, or package
   manifest consumes it;
2. a current replacement is named;
3. it is not required implementation history, evidence, or a reproducibility
   artifact;
4. affected local links and raw repository paths are updated or shown absent;
5. `docs/oldversion/README.md` records the original path, archived path,
   reason, replacement, and archive date.

The archive is excluded from normal reading paths. Archive documents remain
readable historical material and MUST NOT be presented as current interface or
runtime authority.

## Reference Update Contract

Repository-root literal paths and relative Markdown links must both be checked.
The UTM completion audit move updates the hardware Guide, equipment Reference,
and documentation index. The Prusa validation move updates the Prusa bridge
Reference and two research records. Other moves currently have no inbound
repository references, but the old paths must still be absent after relocation
except in the archive index, this Design, and its implementation Plan.

## Verification

The batch is complete only when:

- `git diff --check` passes;
- the documentation validator passes;
- focused documentation validation tests pass;
- all tracked Markdown local links resolve;
- moved active files have no stale old-path references outside the approved
  design, plan, and archive record;
- the image archive manifest still resolves every bundled PNG relative to its
  new directory;
- `.env.example` remains unstaged and unchanged by this work.

## Related Documents

- [Documentation Standard](../../standards/documentation_standard.md)
- [Documentation Governance Design](2026-08-08-documentation-governance-design.md)
- [Agent Figure Design](2026-08-09-agent-reference-figures-and-navigation-design.md)
