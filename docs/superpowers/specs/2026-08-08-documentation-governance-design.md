# ATR Documentation Governance Design

## 1. Purpose

ATR documentation must make three boundaries explicit:

1. what the current code actually does;
2. what operators should do;
3. what is only research, proposed design, or future work.

The documentation system uses a small role-based taxonomy, machine-readable
metadata, and type-specific body templates. Existing domain folders may remain
in place during the first migration so links do not break solely for taxonomy
cleanup.

## 2. Goals

- Give every maintained document exactly one primary document type.
- Make authority, lifecycle state, audience, and verification age visible.
- Prevent Research, Design, and Plan documents from being mistaken for current
  runtime behavior.
- Make Reference and Guide documents traceable to code, configuration, API, or
  generated evidence.
- Support automated indexes and stale-document checks without generating the
  prose itself.
- Refresh the current public entry points and runtime references against the
  latest working tree, including approved uncommitted work when explicitly in
  scope.

## 3. Non-goals

- This work does not refactor runtime code.
- It does not bulk-move all existing documents in the first pass.
- It does not make generated API documentation replace operator explanations.
- It does not treat every historical design package as active documentation.
- It does not require identical Korean and English documents for every internal
  engineering note.

## 4. Canonical Document Types

Every maintained document has one `doc_type` from this list.

| Type | Purpose | Authority |
|---|---|---|
| `index` | Navigation and discovery | Navigation only |
| `standard` | Normative project rules and contracts | Normative for its declared scope |
| `reference` | Current implemented behavior, interfaces, and schemas | Descriptive; code/config remains source of truth |
| `guide` | Procedures for users, operators, and maintainers | Procedural; depends on active Reference/Standard documents |
| `design` | Approved or proposed target architecture and decisions | Proposal until approved; never current-state authority |
| `plan` | Ordered work required to realize an approved Design | Execution coordination only |
| `evidence` | Time-bounded research, audits, benchmarks, and test reports | Evidence for its stated date and method |

Allowed subtypes are intentionally bounded:

```text
index

standard
  documentation
  repository
  safety
  contract

reference
  system
  runtime
  api
  schema
  current_snapshot

guide
  tutorial
  how_to
  operations_runbook
  troubleshooting

design
  feature
  architecture
  adr

plan
  implementation
  migration

evidence
  research
  audit
  test_report
  benchmark
```

Adding a new top-level type requires updating the Documentation Standard and
the document index validation rules. New one-off top-level types are not
allowed.

## 5. Document Lifecycle

The shared `status` field uses only:

```text
draft -> review -> active -> superseded -> archived
```

- `draft`: incomplete and not authoritative.
- `review`: complete enough to review but not yet accepted.
- `active`: maintained and valid for its declared scope.
- `superseded`: replaced by another named document.
- `archived`: preserved for history and excluded from normal navigation.

Plans may additionally carry `execution_status` with `planned`, `in_progress`,
`blocked`, `completed`, or `cancelled`. Designs may carry `decision_status`
with `proposed`, `approved`, `rejected`, or `superseded`. These type-specific
fields do not replace the shared lifecycle status.

## 6. Required Metadata

Maintained Markdown documents use YAML front matter.

```yaml
---
doc_type: reference
subtype: runtime
status: active
authority: descriptive
audience:
  - developer
  - operator
scope:
  - runtime
  - langgraph
summary: Current executable ATR graph and runtime contracts.
source_of_truth:
  - graphs/configs/atr_closed_loop.yaml
  - orchestrator/langgraph_runtime.py
last_verified: 2026-08-08
verified_against: working-tree
related_docs:
  - docs/runtime/current_code_snapshot.md
supersedes: []
---
```

Required fields for all maintained documents:

- `doc_type`
- `subtype`
- `status`
- `authority`
- `audience`
- `scope`
- `summary`
- `related_docs`
- `supersedes`

Additional requirements:

- Active `reference` and `guide` documents require non-empty
  `source_of_truth`, `last_verified`, and `verified_against`.
- Active `standard` documents require a clearly declared normative scope.
- `design` documents require `decision_status`.
- `plan` documents require `execution_status` and a link to the governing
  Design unless explicitly marked as a maintenance plan.
- `evidence` documents require `evidence_date` and `method`.
- `superseded` documents require a replacement in `supersedes` or in a
  dedicated `superseded_by` field.

`verified_against` uses a Git commit when documenting a committed baseline. It
uses `working-tree` only when the document intentionally describes local
uncommitted code, and the document must say so in its verification section.

## 7. Authority Rules

When documents conflict, use this order:

```text
executable code and checked-in configuration
-> active Standard
-> active Reference
-> active Guide
-> approved Design
-> active Plan
-> Evidence
-> archived or superseded documents
```

This order does not make code automatically correct; it identifies the current
implemented behavior. A discovered defect is recorded as a defect or known gap,
not silently rewritten as intended behavior.

Research, Design, and Plan documents must not use phrases such as "the system
does" for unimplemented behavior. They use "proposed", "target", or "planned".

## 8. Shared Body Structure

All maintained documents start with:

1. `Summary`
2. `Scope`
3. `Source of Truth` or `Evidence Basis`

They end with:

1. `Limitations and Known Gaps`
2. `Verification`
3. `Related Documents`

Type-specific middle sections are defined below.

### 8.1 Index

```text
Summary
Audience Paths
Documents by Type
Documents by Domain
Archived/Superseded Entry Point
Index Verification
```

### 8.2 Standard

```text
Summary
Normative Scope
Rules
Required Checks
Exceptions
Compliance Examples
Change Process
```

Normative statements use `MUST`, `MUST NOT`, `SHOULD`, and `MAY` consistently.

### 8.3 Reference

```text
Summary
Scope
Source of Truth
Current Contracts
Current Data Flow
Interfaces and Schemas
Compatibility Boundaries
Limitations and Known Gaps
Verification
Related Documents
```

Current snapshots additionally include measured counts, collection time, and
commands that reproduce every reported count.

### 8.4 Guide

```text
Summary
Audience and Outcome
Prerequisites
Safety Boundary
Procedure
Success Criteria
Failure Recovery
Rollback or Stop Procedure
Verification
Related Reference
```

### 8.5 Design

```text
Summary
Problem
Goals and Non-goals
Current Context
Options Considered
Decision
Architecture and Contracts
Failure and Safety Design
Acceptance Criteria
Open Questions
Related Evidence and Plan
```

Approved Designs contain no unresolved placeholders. Open questions must be
resolved before `decision_status: approved`.

### 8.6 Plan

```text
Goal
Governing Design
Global Constraints
File and Interface Map
Ordered Tasks
Verification per Task
Documentation Updates
Completion Criteria
```

Plans do not redefine architecture already decided by the governing Design.

### 8.7 Evidence

```text
Summary
Question or Audit Objective
Method
Inputs and Environment
Findings
Uncertainty and Limitations
Recommendations
Reproduction or Evidence Links
Related Design/Reference
```

## 9. Organization Strategy

The first migration keeps existing domain-oriented paths such as
`docs/runtime/`, `docs/hardware/`, and `docs/agents/`. Document type is carried
in metadata and indexes. This avoids a large link-breaking move while the
documentation is stale.

New governance assets use:

```text
docs/standards/documentation_standard.md
docs/templates/document_types.md
docs/README.md
```

Design and plan documents continue under:

```text
docs/superpowers/specs/
docs/superpowers/plans/
```

Historical package instructions and external reference bundles remain in their
current directories but are classified as Evidence or archived material unless
they are explicitly maintained as active Standards.

## 10. Migration Mapping for the Current Repository

| Current material | Target classification |
|---|---|
| `README*.md`, `docs/README.md` | Index |
| `docs/runtime/current_code_snapshot.md` | Reference / Current Snapshot |
| `docs/runtime/langgraph_runtime.md` | Reference / Runtime |
| `docs/runtime/closed_loop_and_pages_reference.md` | Reference / System |
| `docs/tutorials/*` | Guide / Tutorial or How-to |
| `docs/hardware/*guideline*` | Guide / Operations Runbook or Reference, based on content |
| `docs/repository/*` | Standard / Repository or Guide |
| `docs/superpowers/specs/*` | Design |
| `docs/superpowers/plans/*` | Plan |
| `개선안/01` through `개선안/17` | Evidence / Research unless separately approved as Design |
| browser, completion, and safety audits | Evidence / Audit or Test Report |

Mixed documents are split by authority, not merely relabeled. For example, a
file containing current behavior plus future recommendations becomes an active
Reference plus a linked Design or Evidence document.

## 11. Verification and Automation Design

Automation checks metadata and reproducible facts; it does not rewrite prose.

Required checks:

- every active maintained document has valid front matter;
- `doc_type`, subtype, lifecycle, and authority values are allowlisted;
- local links and `source_of_truth` paths exist;
- active Reference/Guide verification metadata is present;
- `superseded` documents name their replacement;
- measured runtime snapshot counts are regenerated from current code;
- README and `docs/README.md` do not point to missing files;
- plans link to Designs and Guides link to References where applicable.

The first pass may validate only documents migrated to the new standard. A
manifest records that set so legacy documents do not block adoption while still
remaining visible as migration debt.

## 12. Initial Rollout

1. Add the Documentation Standard and type templates.
2. Refresh the current code snapshot from the latest working tree.
3. Update root README and `docs/README.md` so authority and document types are
   visible at the entry points.
4. Migrate the primary runtime Reference and Knowledge operations Guide.
5. Add a documentation manifest and validation command.
6. Classify remaining documents in batches without bulk-moving paths.
7. Only after link-safe classification, decide whether type-based directories
   provide enough value to justify relocation.

## 13. Acceptance Criteria

- The seven canonical document types and their subtypes are documented.
- Maintained documents expose lifecycle, authority, scope, and verification
  metadata.
- A reader can distinguish current implementation from research and future
  plans without reading the whole document.
- The current code snapshot reports values reproduced from the latest working
  tree.
- Primary entry points explain where current facts, procedures, designs, plans,
  and evidence live.
- No runtime code or physical-device behavior changes as part of the
  documentation rollout.
