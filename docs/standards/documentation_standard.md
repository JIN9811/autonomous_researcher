---
doc_type: standard
subtype: documentation
status: active
authority: normative
audience:
  - contributor
  - maintainer
  - reviewer
scope:
  - repository_documentation
summary: Normative rules for classifying, authoring, verifying, and retiring ATR documentation.
related_docs:
  - docs/templates/document_types.md
  - docs/standards/paper_documentation_standard.md
  - docs/superpowers/specs/2026-08-08-documentation-governance-design.md
supersedes: []
---

# Documentation Standard

## Summary

This Standard defines how maintained ATR documents declare their purpose,
authority, lifecycle, source basis, and verification status. It separates
current implementation facts from operating procedures, proposed designs,
execution plans, and time-bounded evidence.

The uppercase terms `MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative.

## Normative Scope

This Standard applies to Markdown documents listed in
`docs/document_manifest.yaml`. Markdown outside the manifest is migration debt:
it remains readable, but MUST NOT be represented as compliant until it is
classified and added to the manifest.

This Standard governs documentation only. Executable code and checked-in
configuration remain the source of truth for current implemented behavior.

## Source of Truth

- Documentation governance decision:
  `docs/superpowers/specs/2026-08-08-documentation-governance-design.md`
- Governed document set and snapshot expectations:
  `docs/document_manifest.yaml`
- Copy-ready structures: `docs/templates/document_types.md`
- Paper-facing claim and release rules:
  `docs/standards/paper_documentation_standard.md`
- Automated checks: `scripts/validate_documentation.py`
- Validator tests: `tests/unit/test_documentation_validation.py`

## Canonical Types and Subtypes

Every governed document MUST declare exactly one primary `doc_type` and one
allowed `subtype`.

| Type | Allowed subtypes | Purpose |
|---|---|---|
| `index` | `index` | Navigation and discovery |
| `standard` | `documentation`, `repository`, `safety`, `contract` | Normative project rules |
| `reference` | `system`, `runtime`, `api`, `schema`, `current_snapshot` | Current implemented behavior and interfaces |
| `guide` | `tutorial`, `how_to`, `operations_runbook`, `troubleshooting` | Procedures and outcomes |
| `design` | `feature`, `architecture`, `adr` | Proposed or approved target decisions |
| `plan` | `implementation`, `migration` | Ordered work that realizes a Design |
| `evidence` | `research`, `audit`, `test_report`, `benchmark` | Time-bounded observations and results |

A new top-level type MUST NOT be introduced without changing this Standard,
the templates, validator allowlists, tests, and document index in the same
reviewed change.

## Lifecycle

The shared `status` MUST be one of:

```text
draft -> review -> active -> superseded -> archived
```

- `draft` is incomplete and non-authoritative.
- `review` is complete enough to evaluate but is not accepted.
- `active` is maintained and valid for its declared scope.
- `superseded` has a named replacement.
- `archived` is retained for history and excluded from normal reading paths.

Designs MUST additionally declare `decision_status` as `proposed`, `approved`,
`rejected`, or `superseded`. Plans MUST additionally declare
`execution_status` as `planned`, `in_progress`, `blocked`, `completed`, or
`cancelled`.

## Authority Order

When two sources conflict, readers and maintainers MUST use this order to
identify current implemented behavior:

```text
executable code and checked-in configuration
-> active Standard
-> active Reference
-> active Guide
-> approved Design
-> active Plan
-> Evidence
-> archived or superseded material
```

This order identifies implementation state; it does not prove the
implementation is correct. A mismatch discovered in code MUST be recorded as a
defect or known gap rather than silently described as intended behavior.

Design, Plan, and Evidence documents MUST qualify unimplemented statements with
`proposed`, `target`, `planned`, or an equivalent explicit marker.

## Required Metadata

Governed Markdown MUST begin with YAML front matter containing:

```yaml
doc_type: reference
subtype: runtime
status: active
authority: descriptive
audience:
  - developer
scope:
  - runtime
summary: Current runtime contracts.
related_docs: []
supersedes: []
```

The following fields are required for every governed document:

- `doc_type`
- `subtype`
- `status`
- `authority`
- non-empty `audience`
- non-empty `scope`
- non-empty `summary`
- list-valued `related_docs`
- list-valued `supersedes`

Paths in `source_of_truth`, `related_docs`, `supersedes`, `superseded_by`, and
`governing_design` MUST be repository-relative, MUST stay within the repository,
and MUST exist.

## Type-specific Rules

### Index

An Index has `authority: navigation`. It MUST expose intended reader paths and
MUST distinguish governed documents from migration debt.

### Standard

A Standard has `authority: normative`. Its `scope` MUST identify the exact
contract or repository area governed. Normative statements SHOULD use the
uppercase terms defined in this Standard.

### Reference

An active Reference has `authority: descriptive` and MUST provide non-empty
`source_of_truth`, `last_verified`, and `verified_against`. It MUST describe
observed current behavior, not desired behavior.

### Guide

An active Guide has `authority: procedural` and MUST provide non-empty
`source_of_truth`, `last_verified`, and `verified_against`. It SHOULD link the
Reference that defines the interfaces used by its procedure.

### Design

A Design has `authority: proposal` and MUST declare `decision_status`. An
approved Design MUST NOT contain unresolved placeholders. Approval does not
make a Design a statement of current runtime behavior.

### Plan

A Plan has `authority: execution` and MUST declare `execution_status`. It MUST
set `governing_design` to an existing Design unless `maintenance_plan: true`
explains that no architecture decision is involved.

Agent-generated files under `docs/superpowers/plans/` MUST retain the heading
required by the planning workflow as their first line. Because that workflow
and leading YAML front matter currently conflict, those files MAY remain
outside the first manifest. The linked Design and plan heading provide interim
identity; this exception MUST be removed only with a validator-compatible
metadata carrier.

### Evidence

Evidence has `authority: evidentiary` and MUST declare `evidence_date` and
`method`. Findings MUST remain bounded to the recorded inputs, environment, and
date.

### Superseded documents

A document with `status: superseded` MUST name a valid replacement through
`superseded_by` or a replacement path in `supersedes`.

## Body Structure

Every governed document SHOULD begin its body with `Summary`, `Scope`, and
`Source of Truth` or `Evidence Basis`. It SHOULD end with `Limitations and Known
Gaps`, `Verification`, and `Related Documents`. Type-specific middle sections
MUST follow `docs/templates/document_types.md` unless a concise document does
not need a section; omitted sections MUST NOT hide safety, compatibility, or
verification information.

## Verification and Freshness

`last_verified` MUST be an ISO date. `verified_against` MUST be a Git commit for
a committed baseline. It MAY be `working-tree` only when local uncommitted code
is intentionally in scope and the Verification section says so explicitly.

A current snapshot MUST include collection time, reproduction commands, and
labeled measured values. Route counts MUST come from imported FastAPI
`APIRoute` objects rather than decorator grep. Graph counts MUST come from the
checked-in graph configuration or the normalized graph API.

A document SHOULD be reverified whenever any listed `source_of_truth` file
changes. A stale date alone is a review signal; a contradicted fact is a defect.

## Link and Path Rules

- Local Markdown links SHOULD be relative to the containing document.
- Metadata paths MUST be relative to repository root.
- Governed documents MUST NOT link to missing local paths.
- Renames SHOULD update inbound links in the same change.
- This rollout MUST NOT move files solely to group them by document type.

## Manifest and Migration Debt

`docs/document_manifest.yaml` is the canonical governed set. A document MUST be
added only when its metadata and type-specific requirements pass validation.

Legacy documents remain available in existing domain folders. Indexes MUST
label them as legacy or unclassified when their authority could be ambiguous.
Migration SHOULD happen in reviewable domain batches and MUST split mixed
current/future content by authority rather than merely relabel it.

## Required Checks

Every change to a governed document MUST run:

```bash
.venv/bin/python scripts/validate_documentation.py
git diff --check
```

Changes to the validator MUST also run:

```bash
.venv/bin/pytest tests/unit/test_documentation_validation.py -q
.venv/bin/python -m py_compile scripts/validate_documentation.py
```

Current snapshot changes MUST reproduce the recorded route and graph counts
from code before updating expected values in the manifest.

## Exceptions

- Generated API schemas MAY use their generator's metadata format and SHOULD be
  linked from an active Reference.
- External source bundles and historical package instructions MAY remain
  outside the manifest until classified.
- The agent-plan heading exception is defined under the Plan rules above.
- An exception MUST NOT be used to label proposed behavior as current behavior
  or to omit safety and recovery information from an operations Guide.

Paper-facing documents have additional narrative, evidence, figure, language,
privacy, and release constraints in
`docs/standards/paper_documentation_standard.md`. Those constraints are not an
exception to this Standard; both Standards apply.

## Compliance Examples

Compliant current fact:

> `GET /api/knowledge/graph/stats` returned the documented contract when
> verified against commit `09bbe32`; reproduction steps are listed below.

Non-compliant future claim in a Reference:

> The runtime automatically repairs every dead-letter event.

Compliant proposed claim in a Design:

> The target runtime would add an operator-approved dead-letter repair action.

Compliant migration behavior:

> The existing file remains under `docs/runtime/`, gains `reference/runtime`
> metadata, passes validation, and is then added to the manifest.

## Change Process

1. Propose governance changes in a Design or ADR when authority, lifecycle, or
   schema semantics change.
2. Update this Standard, templates, validator allowlists, validator tests, and
   `docs/README.md` together.
3. Run all Required Checks.
4. Review changes for both machine validity and human clarity.
5. Increment the manifest `version` only when its schema changes incompatibly.

## Limitations and Known Gaps

- The first manifest intentionally covers only the initial migration set.
- The validator confirms local paths and metadata but cannot prove prose is
  semantically correct.
- Freshness is event-driven by source changes and review, not yet enforced by a
  maximum age.
- Agentic plan metadata remains an explicit first-rollout exception.

## Verification

This Standard was checked on 2026-08-08 against the approved governance Design,
manifest schema, validator implementation, and validator unit tests in the
working tree after commit `09bbe32`.

## Related Documents

- [Document Type Templates](../templates/document_types.md)
- [Documentation Governance Design](../superpowers/specs/2026-08-08-documentation-governance-design.md)
- [Documentation Index](../README.md)
