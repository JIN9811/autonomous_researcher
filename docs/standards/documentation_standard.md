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
  - docs/superpowers/specs/2026-08-09-device-bridge-reference-documentation-design.md
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

## Document Relocation and Archive

Active material SHOULD stay near its owning domain. A reviewable migration MAY
introduce a domain-local `research/`, `history/`, or `evidence/` directory when
the existing location obscures the document's purpose. Such a move MUST keep
the document body and authority stable, update all inbound relative links and
repository-root literal paths in the same change, and pass link validation.

`docs/oldversion/` is reserved for material excluded from normal reading paths.
Age, file format, missing front matter, exclusion from
`docs/document_manifest.yaml`, or a zero inbound-link count is insufficient on
its own. An item MAY be archived only when the same change demonstrates all of
the following:

1. no active README, document, executable code, configuration, validator, or
   package manifest consumes it;
2. a current replacement is named;
3. the item is not required implementation history, Evidence, or a
   reproducibility artifact;
4. all affected Markdown links and repository-root literal paths are updated
   or shown absent;
5. `docs/oldversion/README.md` records the archive date, original path,
   archived path, reason, and replacement.

An archived tree SHOULD retain its former repository-relative context beneath
`docs/oldversion/`. Active References and Guides MUST NOT cite archived
material as current implementation authority. Internal manifests and relative
assets in an archived package MUST continue to resolve from the new location.

Restoration requires a named active consumer, an owning domain, and current
verification. Restore with a path-preserving move into the active domain,
update inbound references and the archive index in the same change, and add the
document to `docs/document_manifest.yaml` only after its metadata and type
contract pass validation.

## Manifest and Migration Debt

`docs/document_manifest.yaml` is the canonical governed set. A document MUST be
added only when its metadata and type-specific requirements pass validation.

Legacy documents remain available in existing domain folders. Indexes MUST
label them as legacy or unclassified when their authority could be ambiguous.
Migration SHOULD happen in reviewable domain batches and MUST split mixed
current/future content by authority rather than merely relabel it.

## Agent Reference Figures

The ten canonical `docs/agents/*_agent.md` References MUST include paired,
implementation-backed architecture figures. This requirement does not apply
retroactively to legacy agent guidelines.

Every canonical agent Reference MUST include:

1. a closed-loop position and handoff figure;
2. an internal execution and effect-boundary figure.

Specimen, Vision, Manipulation, Equipment, Analysis, and Knowledge MUST also
include an API and connection architecture figure. These six agents have
bridge, external-service, device, or persistence boundaries that would be
ambiguous if compressed into the execution figure.

All agent figure assets MUST:

- live under `docs/agents/assets/figures/`;
- use the stable stems defined by the approved
  [Agent Reference Figures and Navigation Design](../superpowers/specs/2026-08-09-agent-reference-figures-and-navigation-design.md);
- include an editable `.dot` source and same-stem checked-in `.svg` rendering;
- be embedded through a repository-relative Markdown image link in the owning
  Reference;
- use a stable caption marker such as `**Figure Vision-2.**`;
- state the figure's message, scope, and `inspection` evidence boundary in the
  caption;
- use text, shape, border, and edge style so meaning does not rely on color;
- show current required paths with solid edges and label dashed optional,
  compatibility, or fallback paths;
- distinguish control flow, evidence flow, model advice, external service, and
  physical or desktop effect;
- avoid implying that manifest internal steps are separately scheduled
  top-level graph nodes unless the executable graph establishes that fact.

An agent figure is an explanatory projection. Executable code, the primary
graph, module manifest, imported FastAPI routes, bridge implementations, and
declared evidence remain authoritative. A figure MUST NOT promote inspection
into runtime, browser, simulation, live, safety-effectiveness, or scientific
evidence.

The root `README.md` MUST link all ten canonical agent References whenever the
complete set is governed by `docs/document_manifest.yaml`. The agent index MUST
also expose direct figure navigation. Moving or renaming a figure therefore
requires updating the owning Reference, root README, agent index, inbound
links, validator inventory, and this Standard's governing Design when the
semantic contract changes.

Render changed sources from repository root:

```bash
find docs/agents/assets/figures -name '*.dot' -print0 \
  | while IFS= read -r -d '' source; do
      dot -Tsvg "$source" -o "${source%.dot}.svg"
    done
```

Before completion, render every source into an explicit temporary directory
and compare it byte-for-byte with the checked-in SVG. A missing pair, missing
embedding, missing caption, or stale rendering is a documentation defect.

## Device Bridge Reference Figures

The eight canonical capability-oriented References under
`docs/device_bridges/` MUST follow one common content and figure contract. The
canonical set is:

- `printer_fleet_bridge.md`;
- `bambu_x2d_bridge.md`;
- `prusa_mk4s_bridge.md`;
- `lerobot_bridge.md`;
- `windows_pyautogui_bridge.md`;
- `utm_vision_bridge.md`;
- `cae_computation_bridges.md`;
- `base_simulator_bridges.md`.

The boundary is operator-visible capability rather than one Python class. The
index MUST distinguish `graph_projected`, `tool_registered`, `api_exposed`,
`provider`, `runtime_sidecar`, `artifact_transformer`, and `test_only` so a
reader does not mistake the graph projection for the complete executable
inventory.

Each Reference MUST contain these H2 sections in order:

1. `Summary`;
2. `Scope`;
3. `Source of Truth`;
4. `Actual Role`;
5. `System Position and Agent Handoffs`;
6. `Inputs, Commands, and Outputs`;
7. `Internal Execution`;
8. `API Surface`;
9. `Tools and Registry Integration`;
10. `Connections and Protocols`;
11. `Configuration and Secrets`;
12. `State, Events, Artifacts, and Evidence`;
13. `Runtime Modes and Fallbacks`;
14. `Safety, Approval, and Effect Boundary`;
15. `Errors, Timeouts, and Recovery`;
16. `Operator and GUI Surfaces`;
17. `Current Verification`;
18. `Limitations and Known Gaps`;
19. `Related Documents`.

A section with no owned API, live protocol, secret, or physical effect MUST
state `none` and explain the actual access/effect boundary rather than being
omitted.

Every bridge Reference MUST contain three figures:

1. system position and agent handoffs;
2. internal execution and effect boundary;
3. API and connection architecture.

The stable figure stems are defined by the approved
[Device Bridge Reference Documentation Design](../superpowers/specs/2026-08-09-device-bridge-reference-documentation-design.md)
and enforced by `scripts/validate_documentation.py`. This produces exactly 24
`.dot` sources and 24 same-stem `.svg` renderings under
`docs/device_bridges/assets/figures/`; undeclared figure assets are defects.

All bridge figures MUST:

- use a stable caption marker such as `**Figure LeRobot-2.**`;
- state the figure message, scope, and `inspection` evidence boundary;
- distinguish agent/API/tool, manager/provider, protocol/process, external
  target, artifact/evidence, gate, and physical/desktop effect;
- show required paths as solid and condition-label optional, compatibility,
  provider-choice, virtual, or fallback paths as dashed;
- distinguish command/control flow from status and evidence return;
- show validation, capability, allowlist, authentication, approval, preflight,
  freshness, proof, or runtime gates that actually exist;
- identify the first possible network, subprocess, desktop, serial, camera, or
  physical effect;
- show `known_no_effect` versus `effect_unknown` recovery where invocation can
  time out after an external effect;
- remain understandable without color and include textual node/edge labels;
- avoid implying that a UI, model, graph descriptor, or bridge registry entry
  grants authority outside registered runtime and policy gates.

`docs/device_bridges/README.md` MUST link all eight References and all 24
renderings. The root `README.md` MUST contain exactly eight canonical rows and
direct links to each Reference and its three figures whenever all References
are governed. `bridge_api_connection_matrix.md` owns cross-boundary comparison;
individual References own lifecycle and recovery detail.

Executable code, checked-in configuration, Tool Registry wiring, imported API
routes, and declared evidence remain authoritative. A bridge figure is an
explanatory projection and MUST NOT promote inspection or test behavior into
live reliability, hardware compatibility, safety effectiveness, or scientific
evidence. A missing graph entry, code-only provider, compatibility stub, or
test-only simulator MUST be labeled as such rather than normalized away.

Render changed bridge sources from repository root:

```bash
find docs/device_bridges/assets/figures -name '*.dot' -print0 \
  | while IFS= read -r -d '' source; do
      dot -Tsvg "$source" -o "${source%.dot}.svg"
    done
```

Before completion, render all 24 sources into a temporary directory and compare
them byte-for-byte with the checked-in SVGs. Changes to a bridge contract MUST
update its Reference and figures, the matrix when a shared boundary changes,
root/index navigation when inventory changes, and validator/tests when the
normative contract changes.

## Runtime IDE Reference Figures

`docs/runtime/runtime_ide.md` is the canonical operator-facing Reference for
the Runtime IDE. It MUST describe the current UI and backend contract without
replacing the lower-level execution detail in `langgraph_runtime.md`. Its
ordered section inventory, source tokens, navigation, and figure inventory are
enforced by `scripts/validate_documentation.py`.

The Reference MUST contain exactly these three editable/rendered figure pairs
under `docs/runtime/assets/figures/`:

1. `runtime_ide_01_system_boundaries.dot` and `.svg` — system position,
   ownership, and authority boundaries;
2. `runtime_ide_02_config_activation_flow.dot` and `.svg` — draft validation,
   compile evidence, dry-run, version save, and activation;
3. `runtime_ide_03_observability_evidence_flow.dot` and `.svg` — runtime
   events, timeline, approvals, artifacts, and operator inspection.

The owning Reference MUST embed every SVG and use the stable caption markers
`**Figure Runtime IDE-1.**`, `**Figure Runtime IDE-2.**`, and
`**Figure Runtime IDE-3.**`. Each caption MUST state the message, scope, and
`inspection` evidence boundary. Figures MUST use solid edges for current
required paths, dashed edges only for labeled optional, contextual, or
inspection paths, and text/shape/edge-style semantics that remain legible
without color. A legend or directly readable edge labels MUST explain those
semantics.

Runtime IDE figures are implementation-inspection projections. They MUST NOT:

- portray non-executable overlay edges as compiled execution order;
- imply that an edited or validated draft is active before version save and
  activation complete;
- portray Module Management `Load` state as graph attachment or runtime
  activation;
- imply that saving a bridge action descriptor invokes an endpoint or
  hardware;
- treat a timeline event, UI badge, or artifact link as proof that a physical
  action succeeded safely.

Executable code, checked-in graph/module configuration, imported API routes,
registered handlers, bridge implementations, device gates, and persisted run
evidence remain authoritative. The root README, both language READMEs, the
documentation index, and `langgraph_runtime.md` MUST provide direct navigation
to the Runtime IDE Reference.

Render changed Runtime IDE sources from repository root:

```bash
for source in docs/runtime/assets/figures/runtime_ide_*.dot; do
  dot -Tsvg "$source" -o "${source%.dot}.svg"
done
```

Before completion, render all three sources into an explicit temporary
directory and compare them byte-for-byte with the checked-in SVG files. A
missing pair, undeclared `runtime_ide_*.dot`/`.svg` asset, missing embedding,
missing caption, stale rendering, or broken required navigation link is a
documentation defect.

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

This Standard was checked on 2026-08-09 against the approved governance and
device-bridge documentation Designs, manifest schema, validator implementation,
and validator unit tests. Runtime behavior described by the bridge References
uses implementation baseline `188a1d6`.

## Related Documents

- [Document Type Templates](../templates/document_types.md)
- [Documentation Governance Design](../superpowers/specs/2026-08-08-documentation-governance-design.md)
- [Device Bridge Reference Documentation Design](../superpowers/specs/2026-08-09-device-bridge-reference-documentation-design.md)
- [Documentation Index](../README.md)
