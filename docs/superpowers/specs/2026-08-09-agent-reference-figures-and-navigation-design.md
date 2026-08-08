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
  - agent_documentation
  - figures
  - repository_navigation
summary: Approved design for per-agent architecture figures, deeper runtime explanations, and a root README agent entry table.
decision_status: approved
related_docs:
  - README.md
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/standards/documentation_standard.md
  - docs/standards/paper_documentation_standard.md
  - docs/superpowers/specs/2026-08-09-agent-reference-documentation-design.md
supersedes: []
---

# Agent Reference Figures and Navigation Design

## Summary

This Design extends the ten canonical Autonomous Researcher Framework (ATR)
agent References with code-backed architecture figures, deeper execution and
connection explanations, and a root README table that reaches every agent
Reference and its figures directly.

Every agent receives two required figures: its closed-loop position and
handoffs, and its internal execution and effect boundary. Six agents with
substantial bridge, external-service, or durable-storage surfaces receive a
third API and connection architecture figure. All figures use editable
Graphviz sources and checked-in SVG renderings.

## Problem

The canonical agent References document roles, contracts, APIs, tools, state,
safety, and recovery in prose and tables, but they do not contain formal
figures. This creates three gaps:

- a reader cannot locate an agent in the complete loop without reconstructing
  the handoff table;
- internal stages, deterministic gates, external effects, and evidence paths
  are not visually separated;
- the root README links to the shared agent index but does not expose all ten
  agents as first-class entry points.

The paper package already requires editable `.dot` sources, matching `.svg`
renderings, complete captions, and visual distinction among gates, evidence,
and optional paths. Agent References need a compatible rule without turning
them into duplicate paper chapters.

## Goals

1. Put at least two implementation-backed figures in every canonical agent
   Reference.
2. Show the agent's exact closed-loop inputs, outputs, control-plane
   relationships, error alternatives, and evidence flow.
3. Show internal manifest stages without implying that each stage is a
   separately scheduled top-level graph node.
4. Separate deterministic logic, model advice, local services, external
   services, operator gates, and physical effects.
5. Add connection architecture figures where one combined execution figure
   would become unreadable.
6. Add detailed step-to-state-to-evidence and connection-lifecycle explanations
   to the prose surrounding each figure.
7. Make all ten agent References and their figures reachable from a single
   table in the root README.
8. Add normative and automated checks that prevent missing sources,
   renderings, links, or captions.

## Non-goals

- Changing agent, graph, route, bridge, tool, safety, or runtime behavior.
- Claiming simulation, browser, live-hardware, safety-effectiveness, or
  scientific evidence from documentation inspection.
- Replacing OpenAPI, runtime schemas, or hardware operating Guides.
- Copying every API endpoint or implementation branch into a diagram.
- Using decorative generated imagery as evidence.
- Renumbering the six existing paper figures.

## Options Considered

### Option A: Two figures for every agent plus a third for complex boundaries

Create twenty required figures and six additional connection figures.

Advantages:

- every Reference has the same minimum visual contract;
- simple agents avoid a redundant third diagram;
- complex external and persistence boundaries remain readable;
- the result stays maintainable at 26 figures rather than 30.

Costs:

- the visual inventory is not numerically identical for all agents;
- the validator needs an explicit six-agent extension set.

### Option B: Three figures for every agent

Create thirty figures with identical placement.

Advantages:

- perfect numerical symmetry;
- simple validation rules.

Costs:

- Orchestrator, Design, BO, and Guardian would repeat connections already
  visible in their execution/effect figure;
- additional maintenance would not add equivalent explanatory value.

### Option C: One shared loop figure and one unique figure per agent

Create one shared system figure and ten unique execution figures.

Advantages:

- smallest asset set;
- easy global comparison.

Costs:

- individual References would not be self-contained;
- a shared figure cannot expose agent-specific sidecars, failure paths, and
  handoff fields at readable scale.

## Decision

Use Option A. Each agent gets Figures 1 and 2. Specimen, Vision, Manipulation,
Equipment, Analysis, and Knowledge also get Figure 3 because their bridge,
external-service, device, or persistence boundaries need an independent view.

## Asset Inventory and Naming

All assets live in `docs/agents/assets/figures/`. Each editable source has a
matching SVG with the same stem.

| Agent ID | Required figure stems |
|---|---|
| `orchestrator` | `orchestrator_01_closed_loop_handoffs`, `orchestrator_02_execution_effect_boundary` |
| `design` | `design_01_closed_loop_handoffs`, `design_02_execution_effect_boundary` |
| `specimen` | `specimen_01_closed_loop_handoffs`, `specimen_02_execution_effect_boundary`, `specimen_03_api_connection_architecture` |
| `vision` | `vision_01_closed_loop_handoffs`, `vision_02_execution_effect_boundary`, `vision_03_api_connection_architecture` |
| `manipulation` | `manipulation_01_closed_loop_handoffs`, `manipulation_02_execution_effect_boundary`, `manipulation_03_api_connection_architecture` |
| `equipment` | `equipment_01_closed_loop_handoffs`, `equipment_02_execution_effect_boundary`, `equipment_03_api_connection_architecture` |
| `analysis` | `analysis_01_closed_loop_handoffs`, `analysis_02_execution_effect_boundary`, `analysis_03_api_connection_architecture` |
| `knowledge` | `knowledge_01_closed_loop_handoffs`, `knowledge_02_execution_effect_boundary`, `knowledge_03_api_connection_architecture` |
| `bo` | `bo_01_closed_loop_handoffs`, `bo_02_execution_effect_boundary` |
| `guardian` | `guardian_01_closed_loop_handoffs`, `guardian_02_execution_effect_boundary` |

This produces 26 `.dot` files and 26 `.svg` files. File names are stable
public identifiers; a semantic change updates the existing pair instead of
creating an untracked suffix such as `final2`.

## Common Visual Grammar

Figures use the existing paper palette and remain understandable without
color:

| Meaning | Shape/style | Color role |
|---|---|---|
| Agent or internal processing step | rounded box | blue |
| Validation, Guardian, or operator gate | diamond | amber |
| Artifact, event, checkpoint, or durable record | note | green |
| External service, model backend, or bridge | component | purple |
| Physical or desktop effect | octagon with bold border | red |
| Error, review, stop, or terminal alternative | box with bold border | red |
| Current required path | solid arrow | neutral/blue |
| Optional, compatibility, or fallback path | dashed arrow labeled with condition | gray |
| Evidence flow that is not control flow | green arrow labeled `evidence` | green |

Every node has a textual label. Color alone never carries meaning. A dashed
edge always names why the path is optional. Figures distinguish implemented
structure from optional or unevaluated configurations in both line style and
caption text.

Graphviz defaults are consistent across all sources:

```dot
graph [bgcolor="transparent", fontname="DejaVu Sans", pad="0.25"];
node [fontname="DejaVu Sans", fontsize=9, margin="0.10,0.07"];
edge [fontname="DejaVu Sans", fontsize=8, arrowsize=0.7];
```

## Required Figure Contracts

### Figure 1: Closed-Loop Position and Handoffs

Each agent-specific Figure 1 MUST show:

- immediate upstream producers and named input contracts;
- the documented agent highlighted as the focus;
- immediate downstream consumers and named output contracts;
- Orchestrator coordination where it affects the handoff;
- Guardian or operator gates where they can redirect the path;
- error, review, retry, or terminal alternatives;
- evidence or checkpoint output as a path distinct from control flow.

The figure is an explanatory projection. Its caption states that the complete
executable graph remains authoritative for sidecars and conditional edges.

### Figure 2: Internal Execution and Effect Boundary

Each agent-specific Figure 2 MUST show:

- all manifest internal-step IDs, either individually or in labeled contiguous
  groups whose ranges are visible;
- pre-execution entries where declared;
- deterministic validation or policy gates;
- model advice as non-authoritative where deterministic logic is authoritative;
- the primary report, decision, artifact, or handoff outputs;
- the highest possible effect boundary;
- evidence persisted before or after the effect;
- failure and unknown-effect behavior.

The caption states that manifest internal steps are an internal explanatory
graph and are not necessarily separately scheduled runtime nodes.

### Figure 3: API and Connection Architecture

Specimen, Vision, Manipulation, Equipment, Analysis, and Knowledge MUST show:

- agent handler and registered tools;
- owned, connected, operator, and shared API families as applicable;
- internal service or repository boundary;
- local or remote bridge/protocol boundary;
- external software, model, durable store, or physical device;
- preflight, approval, freshness, ontology, schema, or proof gates;
- status/evidence return path;
- the prohibited bypass path in adjacent caption text.

The figure groups API families by function. OpenAPI remains the exhaustive
route source.

## Per-Agent Figure Messages

| Agent | Figure 1 message | Figure 2 message | Figure 3 message where required |
|---|---|---|---|
| Orchestrator | operator intent and accepted prior state become bounded handoffs; Guardian results return as routes | intent, mission, plan, checks, context, handoff, follow-up, decision, reflection, and route translation remain distinct outputs | not_applicable; shared controller/model boundaries fit Figure 2 |
| Design | objective plus BO/Knowledge context becomes a constrained Specimen handoff | deterministic candidate generation, repair, constraint, scoring, and selection remain authoritative over rationale review | not_applicable; no dedicated execution API or external device boundary |
| Specimen | design specification becomes a verified manufacturing handoff to Vision/Manipulation | digital thread, QA, slicing, start gate, monitoring, repair/stop, and evidence precede completion | printer manager, provider, slicer, MQTT/artifact route, printer, bed-clear, and proof paths |
| Vision | camera observations produce freshness-bounded signals for transfer, equipment, and verification | capture, degrade, scene/event estimation, arbitration, freshness, evidence, and verified stop remain distinct | specimen-pose, LeRobot camera, UTM runtime/camera, pose tracker, and rollout-stop connections |
| Manipulation | verified specimen and Vision context become a bounded transfer and post-place handoff | task/profile/policy gates, rollout, SARM progress, Vision verification, decision, result, and evidence | LeRobot APIs, policy/session services, serial/camera/Isaac processes, robot, and stop/status proof |
| Equipment | verified placement plus a registered protocol becomes a measurement artifact for Analysis | profile/skill resolution, bridge validation, deterministic segments, bounded recovery, and proof | bridge registry, skill/profile services, Windows worker, PyAutoGUI/ROS runtime, UTM, and completion audit |
| Analysis | equipment artifact becomes validated metrics, objective, uncertainty, Knowledge, and BO context | input identity, parsing, units, canonical curve, metrics, optional CAE compare/refine, and handoff | run artifacts, parser/metrics, CAE bridge, optional CalculiX process, derived artifacts, and retrieval |
| Knowledge | accepted artifacts and reports become durable context for BO, Design, Guardian, and Evolution review | provenance, ontology, ledger, patterns, performance, outbox, graph receipt, context, and proposals | Knowledge APIs, repositories, relation review, optional graph/Graphify, model lease, and durable receipts |
| BO | Analysis plus Knowledge priors become a governed next-design proposal | evidence table, bounded reasoning patch, numeric acquisition, constraints, penalties, critique, and recommendation | not_applicable; config/benchmark/run and model boundaries fit Figure 2 |
| Guardian | run state, risk, failures, health, and approvals become continue/review/stop/error routing | health and queue reads, risk/budget review, decision, incidents, approvals, and evidence block uncertain continuation | not_applicable; no direct device connection or action authority |

## Detailed Content Additions

The existing 17-H2 Reference structure remains stable. New detail is added
inside the owning sections instead of creating ten divergent outlines.

### Closed-Loop Position and Handoffs

- Embed Figure 1 after the opening position paragraph.
- Add a figure caption with message, scope, and inspection evidence state.
- Expand the handoff table to identify required validation, accepted absence
  reason, downstream consumer, and failure route where those facts are not
  already visible.
- Add a short `Trace interpretation` paragraph explaining what changes in
  runtime state at the agent boundary.

### Internal Execution

- Embed Figure 2 after the manifest-step table.
- Add `Execution trace details`, using a compact table with phase, state read,
  decision or transformation, state written, evidence, and stop/recovery rule.
- Name every manifest ID and every declared pre-execution entry.
- Explain which logic is deterministic, model-assisted, bridge-mediated, or
  operator-resolved.

### API Surface and Tools and Connections

- Embed Figure 3 in `Tools and Connections` for the six complex agents.
- Add a `Connection lifecycle` table with resolve/configure, preflight,
  invoke, observe, persist, and recover rows where applicable.
- State the initiating, stop/status, validation, and evidence categories for
  each consequential API family.
- State the prohibited bypass: no UI, model, or module descriptor grants
  device authority outside the registered service/bridge and policy path.

### State, Evidence, and Recovery

- Distinguish transient in-process state, checkpointed run state, append-only
  events, stored artifacts, durable knowledge, and external state.
- Add an `Effect uncertainty` explanation for every external or physical
  boundary.
- State what evidence must be inspected before replay, resume, republish, or
  retry.

## Root README Entry Table

Add a top-level `Agent References` section after the closed-loop system
explanation and before lower-priority operational/reproduction material. The
table uses these columns:

| Column | Required content |
|---|---|
| `Agent` | canonical English label linked to the agent Reference |
| `Actual role` | one bounded sentence fragment |
| `Primary input → output` | named stable contract or artifact categories |
| `Highest effect` | `none`, `local/model`, `external service`, or `physical possible` with gate qualifier |
| `Details` | Reference link |
| `Figures` | direct links to Figure 1/2 and Figure 3 where present |

The table contains exactly ten rows in closed-loop/control-plane order. It does
not duplicate full API lists. The shared Agent Index and API/Connection Matrix
remain linked immediately above the table.

## Index and Matrix Integration

- `docs/agents/README.md` gains a `Figures` column in the canonical inventory
  and explains the two-plus-one figure rule.
- `agent_api_connection_matrix.md` links to the figure inventory but remains
  the cross-agent comparison source.
- `docs/README.md` keeps the canonical agent map and adds the figure rule to
  the Reference description.
- `docs/paper/appendix_a_interfaces.md` may link to the figure inventory but
  does not duplicate the diagrams.

## Documentation Rule Changes

`docs/standards/documentation_standard.md` gains a normative `Agent Reference
Figures` subsection. It requires:

- the exact two-plus-one inventory defined here;
- repository-relative Markdown image links;
- matching `.dot` and `.svg` assets;
- complete captions stating message, scope, and evidence state;
- readable shape and edge semantics without color dependence;
- current/optional/proposed distinction;
- fresh Graphviz rendering and comparison when a source changes;
- root README and agent index navigation updates when figures move.

The rule applies only to the ten canonical `docs/agents/*_agent.md` files.
Legacy agent guidelines are not retroactively required to carry figures.

## Automated Validation

Extend `scripts/validate_documentation.py` with an explicit figure inventory
for the ten canonical agent References. Validation reports:

- missing required `.dot` source;
- missing matching `.svg` rendering;
- missing Markdown image reference in the owning agent document;
- missing stable caption marker such as `**Figure Vision-2.**`;
- an unexpected third-figure requirement mismatch;
- missing root README link to any canonical agent Reference.

Focused tests in `tests/unit/test_documentation_validation.py` cover a valid
two-figure agent, a valid three-figure agent, missing source/rendering/link,
missing caption, and missing README agent entry.

Fresh rendering is checked from repository root with Graphviz:

```bash
find docs/agents/assets/figures -name '*.dot' -print0 \
  | while IFS= read -r -d '' source; do
      dot -Tsvg "$source" -o "${source%.dot}.svg"
    done
```

Before completion, render into a temporary directory and compare each output
with the checked-in SVG. A byte difference is a stale-rendering defect.

## Verification and Evidence Boundary

The figures are architecture documentation derived from code, manifests,
routes, and checked-in configuration at implementation baseline `0b7627b`.
They are inspection evidence only. They do not establish runtime correctness,
model quality, usability, safety effectiveness, device reliability, or
scientific performance.

Required checks are:

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py
git diff --check
```

The implementation also audits all 26 `.dot`/`.svg` pairs, all ten Reference
links in the root README, all required captions, and public-content safety.

## Rollout Sequence

1. add failing validator tests and the normative figure rule;
2. create the shared asset directory and common visual grammar;
3. implement control-plane and simple-agent figure pairs;
4. implement the six complex-agent third figures;
5. embed figures and add execution/connection/recovery detail;
6. add root README and index navigation tables;
7. render all sources, validate links/captions, compare fresh SVG output, and
   run focused documentation tests.

## Risks and Controls

| Risk | Control |
|---|---|
| Diagram contradicts prose or manifest | name manifest IDs and route families from the same baseline and audit them together |
| SVG becomes stale after `.dot` edit | require paired rendering and fresh-output comparison |
| Figure is readable only through color | shape, border, edge style, and text labels carry every semantic distinction |
| Reference becomes visually overloaded | two core figures for all agents; third only for six complex boundaries |
| Root README becomes another full handbook | use bounded table cells and link to the canonical References |
| Optional provider appears mandatory | dashed labeled path plus caption qualification |
| Figure implies successful live execution | caption states inspection evidence and unevaluated live/scientific boundary |

## Acceptance Criteria

- Exactly 26 agent figure stems exist as `.dot`/`.svg` pairs.
- Every canonical agent Reference embeds Figures 1 and 2 with complete
  captions.
- The six declared complex References embed Figure 3.
- Every manifest step remains named in prose or a labeled figure group.
- Each Reference adds step-to-state-to-evidence or connection-lifecycle detail
  appropriate to its role.
- The root README contains exactly ten agent rows and direct figure links.
- The agent index exposes figure navigation.
- The Documentation Standard and validator enforce the figure contract.
- Fresh Graphviz rendering matches the checked-in SVGs.
- Documentation and paper publication validators pass.
- Focused documentation tests pass.
- No runtime implementation file changes.
- The unrelated `.env.example` modification remains unstaged and unchanged.

## Limitations and Known Gaps

Graphviz figures summarize bounded architecture and cannot show every payload
field, route, conditional graph edge, provider option, or recovery branch.
Direct OpenAPI, manifest, implementation, and domain Guide links remain the
authoritative detailed sources. Future runtime changes require figure review;
the validator can verify inventory and links but cannot prove semantic
agreement with code.

## Related Documents

- [Canonical agent documentation design](2026-08-09-agent-reference-documentation-design.md)
- [Agent Reference Index](../../agents/README.md)
- [Agent API and Connection Matrix](../../agents/agent_api_connection_matrix.md)
- [Documentation Standard](../../standards/documentation_standard.md)
- [Paper Documentation Standard](../../standards/paper_documentation_standard.md)
- [Root README](../../../README.md)
