---
doc_type: design
subtype: architecture
status: review
authority: proposal
audience:
  - researcher
  - reviewer
  - operator
  - developer
  - maintainer
scope:
  - runtime_ide_documentation
  - figures
  - repository_navigation
summary: Approved design for a code-backed Runtime IDE Reference, operator workflow, architecture figures, navigation, and drift validation.
decision_status: approved
related_docs:
  - README.md
  - docs/README.md
  - docs/runtime/langgraph_runtime.md
  - docs/runtime/architecture.md
  - docs/gui/gui.md
  - docs/standards/documentation_standard.md
supersedes: []
---

# Runtime IDE Reference Documentation Design

## Summary

This Design adds one canonical Runtime IDE Reference under `docs/runtime/`.
The document explains the implemented operator surface, graph and module draft
editing, validation and compilation, versioning and activation, dry-run gates,
test and live execution, approvals, runtime observation, artifact evidence,
and recovery. Three editable Graphviz figures make the system boundary,
configuration lifecycle, and observability flow directly inspectable.

The existing `docs/runtime/langgraph_runtime.md` remains the authority for the
config-driven executable runtime. The new Reference owns the IDE-facing view of
that runtime and links back to engine details rather than duplicating every
compiler or module-runtime rule.

## Problem

Runtime IDE behavior is currently distributed across:

- the LangGraph Runtime Reference;
- the broad GUI Guide;
- runtime architecture notes;
- the FastAPI route implementation;
- a large HTML/JavaScript/CSS operator surface;
- graph, module, and version stores;
- unit and browser audit suites;
- historical package instructions and GUI implementation plans.

The root README exposes `/ide`, but there is no single current, code-backed
document that tells an operator or reviewer what each surface controls, which
API it calls, what persists, what can affect execution, what evidence is
produced, and how to recover from an invalid or unsafe state. Existing package
instructions describe implementation intent and visual assets; they are not a
current interface Reference.

## Goals

1. Publish one canonical Runtime IDE Reference at
   `docs/runtime/runtime_ide.md`.
2. Explain the actual UI surfaces, controls, API families, persistence owners,
   execution boundaries, and evidence products.
3. Give operators one complete workflow from deep-link entry through editing,
   validation, dry-run, version save, test/live execution, observation, and
   recovery.
4. Distinguish draft editing, compile evidence, active graph state, management
   workspace state, and live physical effects.
5. Explain graph, module, bridge descriptor, approval, timeline, replay, and
   artifact flows without implying unsupported authority.
6. Add three editable/rendered figures and implementation-backed captions.
7. Expose the Reference from the root README, documentation index, and
   LangGraph Runtime Reference.
8. Add automated checks for the document structure, figures, captions, and
   navigation entries.

## Non-goals

- Changing Runtime IDE UI, API, graph, module, bridge, safety, or execution
  behavior.
- Replacing the LangGraph Runtime Reference or the GUI Guide.
- Copying every DOM id, JavaScript helper, response field, or CSS rule into the
  Reference.
- Treating Module Management load/unload as runtime activation.
- Claiming that a saved custom bridge action directly executes hardware.
- Claiming live reliability, safety effectiveness, or scientific validity from
  code inspection or browser layout tests.
- Moving package instruction assets into the active documentation set.
- Modifying or committing the pre-existing `.env.example` working-tree change.

## Options Considered

### Option A: One Dedicated Runtime IDE Reference

Create one detailed Reference with three figures, operator workflow, API and
effect tables, navigation, and validation.

Advantages:

- one stable GitHub entry point;
- keeps UI, API, persistence, effects, evidence, and recovery together;
- links to runtime-engine detail without repeating it;
- matches the existing agent and device-bridge documentation style.

Costs:

- the document is substantial;
- section boundaries and summary tables must prevent it from becoming a dump
  of implementation details.

### Option B: Split Reference and Operator Guide

Create an interface Reference plus a separate click-by-click operator Guide.

Advantages:

- sharper Reference/Guide authority split;
- shorter individual documents.

Costs:

- validation, dry-run, save, run, evidence, and recovery rules would be
  repeated;
- two documents would need coordinated freshness and navigation.

### Option C: Expand the LangGraph Runtime Reference

Add all Runtime IDE content to `docs/runtime/langgraph_runtime.md`.

Advantages:

- no new canonical file;
- direct proximity to compiler and execution contracts.

Costs:

- mixes engine authority with operator-surface guidance;
- makes the existing long Reference harder to navigate;
- leaves no concise `/ide` entry point from the root README.

## Decision

Use Option A. The Runtime IDE is a single operator capability with tightly
coupled edit, gate, execution, and evidence flows. One dedicated Reference is
the smallest structure that explains those flows without splitting repeated
safety and recovery rules across multiple documents.

## Canonical Document

Create `docs/runtime/runtime_ide.md` with the following second-level sections
in order:

1. `Summary`;
2. `Scope`;
3. `Source of Truth`;
4. `System Position and Authority Boundary`;
5. `Operator Surface Map`;
6. `Entry Paths and Context Handoffs`;
7. `Graph Draft Editing`;
8. `Module and Bridge Descriptor Editing`;
9. `Validation, Compilation, and Dry-Run Gates`;
10. `Versioning, Save, and Activation`;
11. `Operator Workflow`;
12. `Run Modes and Execution Effects`;
13. `API and Connection Architecture`;
14. `Runtime Events, Timeline, and Artifact Evidence`;
15. `Approvals, Safety, and Stop Controls`;
16. `Persistence and Configuration Ownership`;
17. `Errors and Recovery`;
18. `Verification`;
19. `Limitations and Known Gaps`;
20. `Related Documents`.

The operator workflow MUST cover:

```text
open or deep-link
-> select/focus active graph context
-> edit draft graph or module configuration
-> validate draft
-> compile and inspect executable summary
-> dry-run and inspect effective handlers/module runtime
-> save version and optionally activate
-> record matching active dry-run gate
-> run saved test or explicitly confirmed live mode
-> inspect approvals, timeline, node state, artifacts, and logs
-> pause/resume/stop or repair draft and repeat gates
```

This is a safe ordered workflow, not a claim that every control is always
available. The Reference must state prerequisites and failure behavior at each
effect boundary.

## Required Tables

The Reference MUST include these implementation-backed tables:

1. operator surface, purpose, primary API, persisted state, and highest effect;
2. graph/module/run/approval/artifact API families and owning component;
3. test, replay, fault-injection, and live mode gates and effect limits;
4. graph YAML, module YAML/UI YAML, version snapshots, dry-run gate, runtime
   events, and artifacts with their persistence owner;
5. validation, stale digest, invalid handler, approval, bridge descriptor,
   artifact path, and run-control failures with recovery actions.

Large route inventories may group endpoints by family. The document must name
high-consequence endpoints individually, including graph save/activation,
dry-run, run, approval resolution, artifact-file access, and runtime stop or
emergency controls.

## Figures

Create three stable DOT/SVG pairs under `docs/runtime/assets/figures/`:

| Stem | Figure message |
|---|---|
| `runtime_ide_01_system_boundaries` | `/ide` projects config, runtime, bridge, approval, and evidence state but does not replace their execution owners |
| `runtime_ide_02_config_activation_flow` | draft edits become execution-affecting only through validation, compile evidence, versioned save/activation, and a matching active dry-run digest |
| `runtime_ide_03_observability_evidence_flow` | run and operator actions produce events, approvals, node state, logs, and artifacts that the IDE reads for observation and recovery |

Every figure MUST have:

- an editable `.dot` source and same-stem checked-in `.svg` rendering;
- a repository-relative embed in `docs/runtime/runtime_ide.md`;
- a stable caption marker `**Figure Runtime IDE-N.**`;
- message, scope, and `inspection` evidence boundary in the caption;
- distinct control, configuration, event, evidence, and physical-effect edge
  styles with a legend;
- text or line style in addition to color;
- solid edges for required current paths and labeled dashed edges for optional,
  descriptor-only, compatibility, or physical-device handoffs.

The figures MUST NOT imply that:

- graph overlay nodes are executable LangGraph stage nodes;
- editing JSON/YAML immediately changes the active graph;
- saving a module in Module Management attaches it to a graph;
- a custom bridge action descriptor invokes the target device endpoint;
- timeline presence proves physical success;
- browser rendering proves safety effectiveness or live reliability.

## Source and Data Boundaries

The Reference is verified against these implementation groups:

- route and controller ownership: `app/main.py`;
- operator DOM: `web/templates/runtime_ide.html`;
- client orchestration: `web/static/runtime_ide.js`;
- layout and state styling: `web/static/runtime_ide.css`;
- graph geometry: `web/static/runtime_graph_geometry.js`;
- graph schemas, validation, compilation, registry, storage, and versions:
  `graphs/schema.py`, `graphs/validator.py`, `graphs/compiler.py`,
  `graphs/registry.py`, `graphs/version_store.py`, and `graphs/module_store.py`;
- executable run loop: `orchestrator/langgraph_runtime.py`;
- primary and workspace graph configs: `graphs/configs/*.yaml`;
- module contracts: `graphs/modules/*/module.yaml` and optional `ui.yaml`;
- tests: `tests/unit/test_langgraph_runtime.py`,
  `tests/ui/runtime_ide_browser_audit.py`, and relevant documentation tests.

The document may use inspected code and configuration as descriptive evidence.
Browser audit scenarios are layout and interaction evidence only. Live device
or scientific outcome claims require separate dated Evidence.

## Navigation

Update these active entry points:

1. root `README.md` Runtime IDE table row links the new Reference;
2. `README.ko.md` and `README.en.md` Runtime IDE rows link the new Reference;
3. `docs/README.md` adds the Reference to audience, type, page, and runtime
   navigation where applicable;
4. `docs/runtime/langgraph_runtime.md` links the Reference as the operator and
   UI companion;
5. `docs/document_manifest.yaml` governs the new Reference.

The root entry should remain concise. Detailed action and API tables live only
in the Runtime IDE Reference.

## Validation Contract

Extend `scripts/validate_documentation.py` and
`tests/unit/test_documentation_validation.py` with a focused Runtime IDE
contract. Validation MUST reject:

- a missing governed Runtime IDE Reference;
- missing required H2 sections or changed order;
- missing DOT/SVG pairs, unexpected declared figure stems, or stale embeds;
- missing stable captions;
- missing root README, language README, documentation-index, or LangGraph
  Runtime links;
- missing high-consequence source paths and endpoint tokens required by the
  Reference contract.

The validator should check stable inventory and safety-critical anchors, not
freeze every sentence, DOM id, or route. Runtime behavior remains covered by
the existing runtime and browser tests.

## Verification Plan

The implementation is complete only when:

1. focused validator tests pass red-to-green;
2. all three DOT sources render successfully;
3. fresh temporary renders match checked-in SVG files byte-for-byte;
4. repository documentation validation passes;
5. all local Markdown links resolve;
6. focused LangGraph Runtime tests covering graph validation, dry-run gating,
   save/activation, approvals, and artifact paths pass;
7. the existing Runtime IDE browser audit script compiles; live browser
   execution is reported separately if the required server/WebDriver
   environment is unavailable;
8. `git diff --check` passes;
9. `.env.example` remains unstaged and unchanged by this work.

The repository's known unrelated full-suite pytest instability is not a
documentation completion gate. Any full-suite attempt and failure must be
reported separately from the focused Runtime IDE and documentation results.

## Limitations and Known Gaps

- The Reference describes the current server-rendered HTML/JavaScript Runtime
  IDE, not the historical React implementation intent in package instructions.
- In-memory runtime buffers and gate records may not have the same persistence
  lifetime as versioned YAML or run artifacts; the persistence table must state
  those differences explicitly.
- Workspace graph live execution depends on graph metadata and device-specific
  gates; the IDE does not make every template live-capable.
- Browser audits cover selected interaction scenarios and reference viewport
  behavior, not every browser, display scale, or assistive-technology path.
- A current UI screenshot is not required because the three checked-in figures
  explain stable system relationships; screenshots from audits remain dated
  test artifacts rather than interface authority.

## Related Documents

- [LangGraph Runtime](../../runtime/langgraph_runtime.md)
- [Runtime Architecture](../../runtime/architecture.md)
- [GUI Guide](../../gui/gui.md)
- [Documentation Standard](../../standards/documentation_standard.md)
- [Documentation Governance Design](2026-08-08-documentation-governance-design.md)
