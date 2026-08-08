---
doc_type: standard
subtype: documentation
status: active
authority: normative
audience:
  - contributor
  - maintainer
scope:
  - repository_documentation
summary: Copy-ready YAML metadata and body structures for all canonical ATR document types.
related_docs:
  - docs/standards/documentation_standard.md
  - docs/standards/paper_documentation_standard.md
  - docs/superpowers/specs/2026-08-08-documentation-governance-design.md
supersedes: []
---

# Document Type Templates

## Summary

Use one template as the starting point for each governed Markdown document.
Angle-bracket values are authoring prompts, not valid final content. They MUST
be replaced before a document becomes `active` or enters
`docs/document_manifest.yaml`.

## Scope

These templates cover the seven document types defined by the Documentation
Standard. They specify primary structure; they do not generate prose or replace
technical review.

## Source of Truth

- `docs/standards/documentation_standard.md`
- `docs/superpowers/specs/2026-08-08-documentation-governance-design.md`
- `scripts/validate_documentation.py`

## Shared Authoring Rules

- Choose one primary type based on what authority the reader should assign.
- Use repository-relative paths in metadata.
- Keep list fields as YAML lists even when empty.
- Use a Git commit in `verified_against` for committed behavior.
- Split mixed current/future documents instead of hiding the difference in one
  label.
- Remove instructional comments and angle-bracket prompts before activation.

Paper-facing chapters MUST also follow
`docs/standards/paper_documentation_standard.md`. Use this copy-ready extension
after the shared front matter fields:

```yaml
paper_section: system_architecture
research_questions:
  - RQ1
claim_ids:
  - C-SYS-ARCH-01
```

For a code-backed paper Reference, use repository-relative `source_of_truth`,
an ISO date in `last_verified`, and the inspected commit in
`verified_against`. Replace the example section and identifiers with values
actually addressed by the chapter.

## Index Template

```markdown
---
doc_type: index
subtype: index
status: draft
authority: navigation
audience:
  - <reader-role>
scope:
  - <navigation-scope>
summary: <one-sentence navigation purpose>
related_docs: []
supersedes: []
---

# <Index Name>

## Summary

<What this index helps readers find.>

## Scope

<What is and is not indexed.>

## Evidence Basis

<Manifest, repository scan, or source used to verify entries.>

## Audience Paths

<Ordered reading paths by audience or outcome.>

## Documents by Type

<Standards, References, Guides, Designs, Plans, and Evidence.>

## Documents by Domain

<Domain-oriented navigation that preserves existing paths.>

## Archived/Superseded Entry Point

<Where historical material is found and how it is labeled.>

## Limitations and Known Gaps

<Unclassified or deliberately omitted areas.>

## Index Verification

<Date, command, and link-check method.>

## Related Documents

<Governance Standard and adjacent indexes.>
```

## Standard Template

```markdown
---
doc_type: standard
subtype: <documentation|repository|safety|contract>
status: draft
authority: normative
audience:
  - <governed-role>
scope:
  - <normative-scope>
summary: <one-sentence rule-set purpose>
related_docs: []
supersedes: []
---

# <Standard Name>

## Summary

<Rule set and why it exists.>

## Normative Scope

<Exact people, files, systems, or workflows governed.>

## Source of Truth

<Approved decision and machine-enforced contracts.>

## Rules

<MUST, MUST NOT, SHOULD, and MAY statements.>

## Required Checks

<Exact commands and expected result.>

## Exceptions

<Bounded exceptions and approval conditions.>

## Compliance Examples

<At least one compliant and one non-compliant example.>

## Change Process

<How to propose, approve, test, and publish changes.>

## Limitations and Known Gaps

<Unenforced or deferred aspects.>

## Verification

<Review date and governing source.>

## Related Documents

<Templates, Designs, and References governed by this Standard.>
```

## Reference Template

```markdown
---
doc_type: reference
subtype: <system|runtime|api|schema|current_snapshot>
status: draft
authority: descriptive
audience:
  - <reader-role>
scope:
  - <implemented-domain>
summary: <one-sentence description of current behavior>
source_of_truth:
  - <existing/code/or/config/path>
last_verified: <YYYY-MM-DD>
verified_against: <git-commit-or-working-tree>
related_docs: []
supersedes: []
---

# <Reference Name>

## Summary

<Current behavior in a few sentences.>

## Scope

<Included and excluded implementation boundaries.>

## Source of Truth

<Exact code, configuration, schema, or generated contract.>

## Current Contracts

<Guaranteed or observed current behavior.>

## Current Data Flow

<Inputs, transitions, outputs, and persisted evidence.>

## Interfaces and Schemas

<Routes, functions, files, payloads, and compatibility shape.>

## Compatibility Boundaries

<Version, provider, fallback, and migration constraints.>

## Limitations and Known Gaps

<Known defects and intentionally unsupported behavior.>

## Verification

<Exact commands, date, commit, and measured values.>

## Related Documents

<Guides, Standards, and Designs.>
```

For `current_snapshot`, Verification MUST also state collection time and
commands that reproduce every measured count.

## Guide Template

```markdown
---
doc_type: guide
subtype: <tutorial|how_to|operations_runbook|troubleshooting>
status: draft
authority: procedural
audience:
  - <operator-or-user-role>
scope:
  - <procedure-domain>
summary: <outcome the reader will achieve>
source_of_truth:
  - <existing/reference/or/runtime/path>
last_verified: <YYYY-MM-DD>
verified_against: <git-commit-or-working-tree>
related_docs:
  - <existing/reference/document.md>
supersedes: []
---

# <Guide Name>

## Summary

<Outcome and safest normal path.>

## Audience and Outcome

<Who should use this and what completion means.>

## Scope

<Included procedure and excluded responsibilities.>

## Source of Truth

<Reference, code, configuration, and runtime evidence.>

## Prerequisites

<Access, configuration, files, and service health.>

## Safety Boundary

<Read-only versus mutating actions, approvals, and stop conditions.>

## Procedure

<Numbered, observable steps.>

## Success Criteria

<Exact state, response, artifact, or measurement proving success.>

## Failure Recovery

<Diagnosis and safe retry paths.>

## Rollback or Stop Procedure

<How to stop effects and return to a known state.>

## Limitations and Known Gaps

<Unsupported cases and operator caveats.>

## Verification

<Date, baseline, commands, and observed outcome.>

## Related Reference

<Current Reference documents governing used interfaces.>
```

## Design Template

```markdown
---
doc_type: design
subtype: <feature|architecture|adr>
status: draft
authority: proposal
audience:
  - <decision-maker-or-implementer>
scope:
  - <target-domain>
summary: <decision or target architecture in one sentence>
decision_status: proposed
related_docs: []
supersedes: []
---

# <Design Name>

## Summary

<Decision and current decision state.>

## Problem

<Observed problem without assuming a solution.>

## Goals and Non-goals

<Success boundaries and explicit exclusions.>

## Current Context

<Current implementation and constraints.>

## Options Considered

<Alternatives, tradeoffs, and rejection reasons.>

## Decision

<Chosen proposal, labeled as target behavior.>

## Architecture and Contracts

<Components, interfaces, data, and ownership.>

## Failure and Safety Design

<Failure modes, gates, recovery, and audit evidence.>

## Acceptance Criteria

<Observable conditions required for approval or completion.>

## Open Questions

<Questions that must be resolved before approval.>

## Related Evidence and Plan

<Evidence supporting the decision and implementation plan.>

## Limitations and Known Gaps

<Deliberate omissions and residual risks.>

## Verification

<Review participants, date, and approval evidence.>

## Related Documents

<Current References and governing Standards.>
```

## Plan Template

The agentic planning workflow requires its own fixed leading header. Use that
workflow for executable plans under `docs/superpowers/plans/`; this template
shows the target governance metadata when a compatible carrier is available.

```markdown
---
doc_type: plan
subtype: <implementation|migration>
status: draft
authority: execution
audience:
  - implementer
scope:
  - <work-scope>
summary: <one-sentence delivery goal>
execution_status: planned
governing_design: <existing/design/document.md>
related_docs:
  - <existing/design/document.md>
supersedes: []
---

# <Plan Name>

## Goal

<Concrete end state.>

## Governing Design

<Approved Design and decisions that MUST NOT be redefined.>

## Global Constraints

<Safety, compatibility, dependency, and scope rules.>

## File and Interface Map

<Exact created/modified files and consumed/produced interfaces.>

## Ordered Tasks

<Test-first, independently verifiable task sequence.>

## Verification per Task

<Exact commands and expected outcomes.>

## Documentation Updates

<References and Guides that change with implementation.>

## Completion Criteria

<Observable definition of done.>

## Limitations and Known Gaps

<Deferred work and known external blockers.>

## Verification

<Execution evidence and final baseline.>

## Related Documents

<Design, Standards, and affected References.>
```

## Evidence Template

```markdown
---
doc_type: evidence
subtype: <research|audit|test_report|benchmark>
status: draft
authority: evidentiary
audience:
  - <evidence-consumer>
scope:
  - <measured-domain>
summary: <question and result in one sentence>
evidence_date: <YYYY-MM-DD>
method: <measurement-or-research-method>
related_docs: []
supersedes: []
---

# <Evidence Name>

## Summary

<Main finding bounded to the recorded evidence.>

## Question or Audit Objective

<Question this evidence can answer.>

## Evidence Basis

<Primary inputs and why they are relevant.>

## Method

<Reproducible collection and analysis procedure.>

## Inputs and Environment

<Versions, hardware, fixtures, data, date, and configuration.>

## Findings

<Observed facts, measurements, and supporting artifacts.>

## Uncertainty and Limitations

<What the evidence cannot establish.>

## Recommendations

<Actions supported by findings, labeled as recommendations.>

## Reproduction or Evidence Links

<Commands, logs, screenshots, datasets, and hashes.>

## Related Design/Reference

<Decisions informed and current behavior compared.>

## Related Documents

<Adjacent Evidence and governing Standards.>
```

## Limitations and Known Gaps

- Templates cannot determine the correct authority from prose.
- The plan template has the first-rollout agent-header exception described in
  the Documentation Standard.
- Legacy `.txt` guidelines require classification before they can use this
  Markdown metadata scheme.

## Verification

All seven templates were compared on 2026-08-08 with the canonical type,
lifecycle, metadata, and body rules in the approved governance Design and the
active Documentation Standard.

## Related Documents

- [Documentation Standard](../standards/documentation_standard.md)
- [Documentation Governance Design](../superpowers/specs/2026-08-08-documentation-governance-design.md)
- [Documentation Index](../README.md)
