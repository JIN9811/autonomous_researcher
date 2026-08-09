---
doc_type: plan
subtype: implementation
status: review
authority: execution
audience:
  - developer
  - maintainer
  - researcher
scope:
  - agent_documentation
  - figures
  - repository_navigation
summary: Implementation plan for 26 agent figures, deeper agent References, root README navigation, and figure validation.
execution_status: planned
governing_design: docs/superpowers/specs/2026-08-09-agent-reference-figures-and-navigation-design.md
related_docs:
  - docs/agents/README.md
  - docs/standards/documentation_standard.md
  - scripts/validate_documentation.py
supersedes: []
---

# Agent Reference Figures and Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 26 code-backed Graphviz figures and deeper runtime explanations to all ten canonical agent References, expose them through a ten-row root README table, and enforce the visual contract in documentation validation.

**Architecture:** Every agent owns two stable figure pairs for closed-loop handoffs and internal execution/effect boundaries. Specimen, Vision, Manipulation, Equipment, Analysis, and Knowledge own a third API/connection pair. The general Documentation Standard defines the rule, `validate_documentation.py` verifies inventory, embeddings, captions, and root navigation, and the existing References retain their common 17-section structure.

**Tech Stack:** Markdown, Graphviz DOT/SVG, Python documentation validator, pytest, Git.

## Global Constraints

- Runtime facts remain pinned to implementation baseline `0b7627b`; documentation commits after that baseline do not change agent behavior.
- Create exactly 26 `.dot` sources and 26 matching `.svg` renderings under `docs/agents/assets/figures/`.
- Every canonical agent embeds Figures 1 and 2; only Specimen, Vision, Manipulation, Equipment, Analysis, and Knowledge require Figure 3.
- Use repository-relative image and document links.
- Use `DejaVu Sans`, transparent backgrounds, text labels, shapes, border styles, and edge styles so meaning does not depend on color.
- Solid arrows mean current required flow; dashed arrows name optional, compatibility, or fallback conditions; green labeled arrows mean evidence rather than control flow.
- Rounded boxes are agent/internal work, diamonds are gates, notes are evidence/state, components are services/bridges/models, octagons are physical or desktop effects, and bold red boxes are error/review/terminal outcomes.
- Every caption states message, scope, and `inspection` evidence state and avoids runtime, safety-effectiveness, or scientific claims.
- Manifest internal steps may be grouped only when every ID or contiguous range is visible.
- Preserve the exact 17-H2 order in all ten agent References.
- Add detail inside existing sections rather than creating divergent agent outlines.
- Do not modify runtime, route, graph, bridge, tool, or agent implementation files.
- Do not alter or stage the existing `.env.example` modification.
- Keep root English README prose canonical; the new table is navigation and does not change thesis or claim semantics, so no Korean thesis rewrite is required.

---

### Task 1: Enforce the Agent Figure Contract

**Files:**
- Modify: `tests/unit/test_documentation_validation.py`
- Modify: `scripts/validate_documentation.py`
- Modify: `docs/standards/documentation_standard.md`

**Interfaces:**
- Consumes: canonical paths in `docs/document_manifest.yaml` and Markdown bodies passed to `validate_document()`.
- Produces: `AGENT_REFERENCE_FIGURES`, `_validate_agent_reference_figures(path, body, root, label)`, and `_validate_root_agent_navigation(root, documents, manifest_label)`.
- Produces error messages used by focused tests: `missing agent figure source`, `missing agent figure rendering`, `missing agent figure link`, `missing agent figure caption`, and `missing root README agent link`.

- [ ] **Step 1: Add failing agent-figure validation tests**

Add a fixture helper that creates a valid active Reference at
`docs/agents/<agent>_agent.md`, writes the required `.dot`/`.svg` pairs, embeds
each SVG, and adds caption markers such as `**Figure Orchestrator-1.**`.

Add focused tests with these assertions:

```python
def test_agent_reference_requires_matching_figure_source_rendering_link_and_caption(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write_agent_reference(tmp_path, "orchestrator", figure_count=2)
    assert module.validate_document(document, tmp_path) == []

    (tmp_path / "docs/agents/assets/figures/orchestrator_01_closed_loop_handoffs.dot").unlink()
    errors = module.validate_document(document, tmp_path)
    assert any("missing agent figure source" in error for error in errors)


def test_complex_agent_requires_third_figure(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write_agent_reference(tmp_path, "specimen", figure_count=2)
    errors = module.validate_document(document, tmp_path)
    assert any("specimen_03_api_connection_architecture" in error for error in errors)


def test_root_readme_requires_all_canonical_agent_links(tmp_path: Path) -> None:
    module = _load_validator()
    documents = ["README.md", *module.AGENT_REFERENCE_PATHS.values()]
    _write(tmp_path, "README.md", "# ATR\n")
    errors = module._validate_root_agent_navigation(tmp_path, documents, "manifest")
    assert len([error for error in errors if "missing root README agent link" in error]) == 10
```

Also test missing SVG, missing Markdown image, missing caption, a valid
three-figure complex agent, and a root README containing all ten links.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_documentation_validation.py
```

Expected: new tests fail because the inventory and validation helpers do not
exist.

- [ ] **Step 3: Implement the validator inventory and checks**

Define stable mappings:

```python
AGENT_REFERENCE_PATHS = {
    "orchestrator": "docs/agents/orchestrator_agent.md",
    "design": "docs/agents/design_agent.md",
    "specimen": "docs/agents/specimen_agent.md",
    "vision": "docs/agents/vision_agent.md",
    "manipulation": "docs/agents/manipulation_agent.md",
    "equipment": "docs/agents/equipment_agent.md",
    "analysis": "docs/agents/analysis_agent.md",
    "knowledge": "docs/agents/knowledge_agent.md",
    "bo": "docs/agents/bo_agent.md",
    "guardian": "docs/agents/guardian_agent.md",
}

AGENT_REFERENCE_FIGURES = {
    "orchestrator": ("orchestrator_01_closed_loop_handoffs", "orchestrator_02_execution_effect_boundary"),
    "design": ("design_01_closed_loop_handoffs", "design_02_execution_effect_boundary"),
    "specimen": ("specimen_01_closed_loop_handoffs", "specimen_02_execution_effect_boundary", "specimen_03_api_connection_architecture"),
    "vision": ("vision_01_closed_loop_handoffs", "vision_02_execution_effect_boundary", "vision_03_api_connection_architecture"),
    "manipulation": ("manipulation_01_closed_loop_handoffs", "manipulation_02_execution_effect_boundary", "manipulation_03_api_connection_architecture"),
    "equipment": ("equipment_01_closed_loop_handoffs", "equipment_02_execution_effect_boundary", "equipment_03_api_connection_architecture"),
    "analysis": ("analysis_01_closed_loop_handoffs", "analysis_02_execution_effect_boundary", "analysis_03_api_connection_architecture"),
    "knowledge": ("knowledge_01_closed_loop_handoffs", "knowledge_02_execution_effect_boundary", "knowledge_03_api_connection_architecture"),
    "bo": ("bo_01_closed_loop_handoffs", "bo_02_execution_effect_boundary"),
    "guardian": ("guardian_01_closed_loop_handoffs", "guardian_02_execution_effect_boundary"),
}
```

For the owning agent path, require
`assets/figures/<stem>.svg` in a Markdown image target, both repository files,
and a caption marker `**Figure <Title>-<index>.**`. Use a title mapping so BO
uses `BO`, Lab Equipment uses `Equipment`, and other caption names remain
stable. Invoke the check from `validate_document()` after local-link
validation. Invoke root navigation validation from `validate_manifest()` only
when the canonical agent paths are present in `documents`.

- [ ] **Step 4: Add the normative rule to the Documentation Standard**

Add `## Agent Reference Figures` before `Required Checks`. Include the exact
two-plus-one inventory, source/render/caption rules, visual grammar, current
versus optional distinction, root README navigation requirement, Graphviz
render command, and legacy-guideline exception.

- [ ] **Step 5: Run validator tests and syntax checks**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_documentation_validation.py
.venv/bin/python -m py_compile scripts/validate_documentation.py
```

Expected: all documentation-validator tests pass. The repository-level
validator is expected to fail until Tasks 2–6 create all required assets and
embeddings.

- [ ] **Step 6: Commit the enforceable figure contract**

```bash
git add tests/unit/test_documentation_validation.py scripts/validate_documentation.py docs/standards/documentation_standard.md
git commit -m "docs: enforce agent reference figures"
```

### Task 2: Add Control-Plane Figures and Detail

**Files:**
- Create: `docs/agents/assets/figures/orchestrator_01_closed_loop_handoffs.dot`
- Create: `docs/agents/assets/figures/orchestrator_01_closed_loop_handoffs.svg`
- Create: `docs/agents/assets/figures/orchestrator_02_execution_effect_boundary.dot`
- Create: `docs/agents/assets/figures/orchestrator_02_execution_effect_boundary.svg`
- Create: `docs/agents/assets/figures/guardian_01_closed_loop_handoffs.dot`
- Create: `docs/agents/assets/figures/guardian_01_closed_loop_handoffs.svg`
- Create: `docs/agents/assets/figures/guardian_02_execution_effect_boundary.dot`
- Create: `docs/agents/assets/figures/guardian_02_execution_effect_boundary.svg`
- Modify: `docs/agents/orchestrator_agent.md`
- Modify: `docs/agents/guardian_agent.md`

**Interfaces:**
- Consumes: Orchestrator/Guardian manifests, primary graph, controller/run lifecycle, approval/event services, and current Reference prose.
- Produces: four figure pairs and step-to-state-to-evidence explanations that define coordination versus safety authority.

- [ ] **Step 1: Create Orchestrator Figure 1 and embed it**

Show `Operator intent -> Orchestrator -> active domain agent`, prior accepted
Knowledge/BO/failure context into Orchestrator, domain result back to
Orchestrator, Guardian decision back to route translation, and next
Design/review/complete/error alternatives. Send transcript, decision,
checkpoint, and handoff evidence to an evidence note with green labeled edges.

Embed after the opening `Closed-Loop Position and Handoffs` paragraph and add:

```markdown
**Figure Orchestrator-1.** The Orchestrator converts accepted intent and prior
state into bounded handoffs, then translates agent and Guardian results into
the next route. This is an inspection-backed projection of baseline `0b7627b`;
the executable graph remains authoritative and runtime effectiveness is not
evaluated here.
```

- [ ] **Step 2: Create Orchestrator Figure 2 and add execution detail**

Show pre-execution IDs `01`–`03`, internal IDs `01`–`09`, grouped only as:
intent/mission, plan/read-only checks, context/handoff, follow-up/decision,
reflection/Guardian translation. Show the model backend as a component whose
advice cannot bypass required-input or Guardian diamonds. Show no direct
device edge. Show transcript/checkpoint/event evidence.

Add an `Execution trace details` table covering phase, state read, decision,
state written, evidence, and stop/recovery rule. Explain session transcript
versus checkpointed run state versus external device state.

- [ ] **Step 3: Create Guardian Figure 1 and embed it**

Show current run state, agent failures, device health, queue state, approval
state, and safety budget entering Guardian; show continue/review/stop/error
leaving Guardian for Orchestrator route translation; show incidents,
corrective actions, and approval records as evidence.

- [ ] **Step 4: Create Guardian Figure 2 and add execution detail**

Show internal IDs `01_collect_graphwide_safety_state`,
`02_evaluate_recent_failures`, and `03_decide_continue_stop_or_error`, the
`device.health` and `experiment.queue.status` tools, model review as bounded
advice, deterministic risk/budget/approval gates, and the absence of a direct
device-action edge.

Add detailed rows for known safe continuation, missing approval, uncertain
effect, exhausted budget, corrective review, and terminal stop. State the
evidence required before Orchestrator may resume routing.

- [ ] **Step 5: Render and validate the four control-plane pairs**

Run `dot -Tsvg` for each source, direct `validate_document()` for both
References, and `git diff --check`.

- [ ] **Step 6: Commit control-plane figures**

```bash
git add docs/agents/assets/figures/orchestrator_* docs/agents/assets/figures/guardian_* docs/agents/orchestrator_agent.md docs/agents/guardian_agent.md
git commit -m "docs: illustrate orchestrator and guardian agents"
```

### Task 3: Add Design and BO Figures and Detail

**Files:**
- Create: `docs/agents/assets/figures/design_01_closed_loop_handoffs.{dot,svg}`
- Create: `docs/agents/assets/figures/design_02_execution_effect_boundary.{dot,svg}`
- Create: `docs/agents/assets/figures/bo_01_closed_loop_handoffs.{dot,svg}`
- Create: `docs/agents/assets/figures/bo_02_execution_effect_boundary.{dot,svg}`
- Modify: `docs/agents/design_agent.md`
- Modify: `docs/agents/bo_agent.md`

**Interfaces:**
- Consumes: Design/BO manifests, deterministic selection/acquisition behavior, Knowledge/Analysis handoffs, and graph execution boundary.
- Produces: four figure pairs explaining the governed proposal feedback loop without implying device authority.

- [ ] **Step 1: Add Design handoff and execution figures**

Figure 1 shows Orchestrator objective plus Knowledge/BO/failure context entering
Design and `experiment_spec`, candidate ledger, design report, decisions,
metrics, and handoff packet leaving for Specimen and evidence storage.

Figure 2 names `orchestrator_plan` and internal IDs `01`–`12`; visualize
normalization, prior context, hypothesis/design space, deterministic pool,
constraint/repair gate, scoring, authoritative selection, report, and handoff.
Place LLM rationale review beside—not after—the authoritative selection path,
with no edge granting it constraint bypass.

- [ ] **Step 2: Expand Design execution and handoff detail**

Add a trace table separating required objective/constraints, optional prior
context, candidate repair versus rejection, authoritative deterministic score,
LLM rationale metadata, accepted state merge, and no-valid-candidate recovery.
Explain why planning and graph-authoring APIs are connected/operator surfaces,
not a dedicated Design execution API.

- [ ] **Step 3: Add BO handoff and execution figures**

Figure 1 shows Analysis evidence and Knowledge priors/constraints entering BO,
ranked candidates/recommendation returning through Guardian and Orchestrator to
Design, and rejected/empty candidate alternatives.

Figure 2 names all internal IDs `01`–`15`, grouped as evidence/prior intake,
bounded reasoning patch, search space/pool, numeric acquisition, bounded LLM
preference, constraints/failure penalties, top-k critique, recommendation,
artifacts, and Design handoff. Numeric acquisition and validators must be on
the authoritative solid path; LLM preference is a bounded dashed input.

- [ ] **Step 4: Expand BO evidence and proposal-boundary detail**

Add trace rows for analysis handoff validity, prior-trial deduplication,
constraint rejection, acquisition score, failure penalty, critique, final
proposal, and downstream governance. Distinguish config save, benchmark,
direct workspace run, and closed-loop execution evidence.

- [ ] **Step 5: Render, validate, and commit**

Render all four sources, validate both documents directly, audit all 12 Design
and 15 BO internal IDs, then commit:

```bash
git add docs/agents/assets/figures/design_* docs/agents/assets/figures/bo_* docs/agents/design_agent.md docs/agents/bo_agent.md
git commit -m "docs: illustrate design and bo agents"
```

### Task 4: Add Specimen and Vision Figures and Detail

**Files:**
- Create: `docs/agents/assets/figures/specimen_01_closed_loop_handoffs.{dot,svg}`
- Create: `docs/agents/assets/figures/specimen_02_execution_effect_boundary.{dot,svg}`
- Create: `docs/agents/assets/figures/specimen_03_api_connection_architecture.{dot,svg}`
- Create: `docs/agents/assets/figures/vision_01_closed_loop_handoffs.{dot,svg}`
- Create: `docs/agents/assets/figures/vision_02_execution_effect_boundary.{dot,svg}`
- Create: `docs/agents/assets/figures/vision_03_api_connection_architecture.{dot,svg}`
- Modify: `docs/agents/specimen_agent.md`
- Modify: `docs/agents/vision_agent.md`

**Interfaces:**
- Consumes: Specimen/Vision manifests, printer manager/providers, camera/pose/UTM services, and manipulation verification contracts.
- Produces: six figure pairs showing the manufacturing-observation boundary, freshness, proof, and physical-effect gates.

- [ ] **Step 1: Add three Specimen figures**

Figure 1 shows Design specification to Specimen, manufacturing artifacts and
readiness to Vision/Manipulation, equipment-ready handoff, Guardian/operator
redirection, and digital-thread evidence.

Figure 2 names all 11 internal IDs and six tools. Show required-field,
mesh/manufacturability, slice/prestart, start, bed-clear, and proof gates;
separate artifact preparation from publish/physical effect; route ambiguous
publish/start state to stop/status/proof review rather than automatic replay.

Figure 3 shows printer APIs -> printer manager -> selected Bambu or Prusa
provider; Bambu slicer/G-code patch -> artifact route/MQTT -> printer; status,
camera, bed-clear, hash, and completion proof returning to ATR. Bambu active
selection and Prusa operator selection are labeled configurations, not
equivalent validation.

- [ ] **Step 2: Expand Specimen digital-thread and recovery detail**

Add trace/lifecycle rows for specification validation, geometry, mesh QA,
manufacturability, slicing, source/patched hash, start draft/gate/publish,
post-publish observation, autoejection/bed-clear, completion audit, and
Vision/Manipulation handoff. State exactly which evidence is inspected before
republish or next-job release.

- [ ] **Step 3: Add three Vision figures**

Figure 1 shows Specimen/Manipulation/Equipment context plus cameras entering
Vision, then `vision_report.v1`, `vision_signal.v1`, pose/evidence, placement
verification, and verified rollout stop flowing to consumers and Guardian.

Figure 2 names all 11 internal IDs—including both `03_*` IDs—and seven tools.
Show task/zone resolution, capture, degrade, scene/events, arbitration,
freshness gate, evidence packaging, ejection/placement verification, and the
verified stop branch. No edge may start robot, printer, UTM, or PyAutoGUI.

Figure 3 shows specimen-pose APIs, pose tracker, LeRobot active camera/camera
test, UTM runtime and camera APIs, camera/ROS sources, signal arbitration,
evidence, and rollout-stop service. Mark observation paths read-only and the
verified stop path physical-process-affecting.

- [ ] **Step 4: Expand Vision freshness and connection detail**

Add trace rows for capture source, timestamp/expiry, confidence/quality,
degraded result, arbitration, downstream rejection, evidence reference, and
verified stop. Add connection lifecycle rows for pose tracker, LeRobot camera,
UTM runtime/camera, and rollout stop.

- [ ] **Step 5: Render, validate, and commit**

Render all six sources; audit 11/6 Specimen and 11/7 Vision step/tool coverage;
validate both documents; commit:

```bash
git add docs/agents/assets/figures/specimen_* docs/agents/assets/figures/vision_* docs/agents/specimen_agent.md docs/agents/vision_agent.md
git commit -m "docs: illustrate specimen and vision agents"
```

### Task 5: Add Manipulation and Equipment Figures and Detail

**Files:**
- Create: `docs/agents/assets/figures/manipulation_01_closed_loop_handoffs.{dot,svg}`
- Create: `docs/agents/assets/figures/manipulation_02_execution_effect_boundary.{dot,svg}`
- Create: `docs/agents/assets/figures/manipulation_03_api_connection_architecture.{dot,svg}`
- Create: `docs/agents/assets/figures/equipment_01_closed_loop_handoffs.{dot,svg}`
- Create: `docs/agents/assets/figures/equipment_02_execution_effect_boundary.{dot,svg}`
- Create: `docs/agents/assets/figures/equipment_03_api_connection_architecture.{dot,svg}`
- Modify: `docs/agents/manipulation_agent.md`
- Modify: `docs/agents/equipment_agent.md`

**Interfaces:**
- Consumes: Manipulation/Equipment manifests, LeRobot and equipment bridge APIs, Vision freshness and placement verification, and physical safety boundaries.
- Produces: six figure pairs that expose robot and instrument execution, stop/status ownership, and unknown-effect recovery.

- [ ] **Step 1: Add three Manipulation figures**

Figure 1 shows Specimen plus fresh Vision signal entering the two supported
tasks, post-place Vision verification, verified handoff to Equipment or
Knowledge, and Guardian/operator stop/review alternatives.

Figure 2 names both supported task IDs, all 11 internal IDs, and four tools.
Show profile/policy/freshness/live gates, backend selection, bounded rollout,
monitoring/SARM, post-place verification, decision, report, result, and stored
evidence. The robot is an octagon reached only after all gates.

Figure 3 groups configuration/session, camera/port/profile, policy/file/dataset,
teleoperation, record/train, rollout, manipulation-agent, Isaac/synthetic,
mirror, and visualization APIs around LeRobot services. Show policy process,
serial/camera, optional Isaac services, robot, stop/status, visual proof, and
dataset/checkpoint evidence.

- [ ] **Step 2: Expand Manipulation lifecycle and uncertain-effect detail**

Add trace/lifecycle rows for task resolution, camera return, profile/policy
preflight, rollout session identity, bounded motion, event monitoring, SARM
progress, stop/status, visual verification, post-place signal, and downstream
handoff. Explicitly prohibit replay until status and visual proof resolve an
unknown rollout effect.

- [ ] **Step 3: Add three Equipment figures**

Figure 1 shows verified specimen placement plus profile/skill/protocol and
approval entering Equipment, raw measurement and proof leaving for Analysis,
and stop/review/error paths returning through Guardian/Orchestrator.

Figure 2 names five internal IDs and four tools. Show exact profile/skill
resolution, bridge validation, deterministic segment execution, bounded
recovery, evidence packaging, and handoff. Put operator approval, live
preflight, Guardian, and effect-uncertainty gates before desktop/instrument
effects.

Figure 3 shows bridge registry/actions, skill/profile lifecycle, Windows
worker/local bridge, locators/screenshots/run-program/proof audit, UTM ROS
runtime/camera, PyAutoGUI/desktop application, UTM instrument, and evidence
return. UI and module descriptors must have no bypass edge.

- [ ] **Step 4: Expand Equipment protocol and proof detail**

Add connection lifecycle rows for registered skill, profile, worker/bridge,
desktop application, UTM runtime, physical instrument, and proof audit. Add
trace rows for segment identity, pre/post screenshot, command evidence,
measurement artifact, completion audit, and unknown-effect inspection before
segment retry.

- [ ] **Step 5: Render, validate, and commit**

Render all six sources; audit both supported tasks, 11/4 Manipulation and 5/4
Equipment step/tool coverage; validate both documents; commit:

```bash
git add docs/agents/assets/figures/manipulation_* docs/agents/assets/figures/equipment_* docs/agents/manipulation_agent.md docs/agents/equipment_agent.md
git commit -m "docs: illustrate manipulation and equipment agents"
```

### Task 6: Add Analysis and Knowledge Figures and Detail

**Files:**
- Create: `docs/agents/assets/figures/analysis_01_closed_loop_handoffs.{dot,svg}`
- Create: `docs/agents/assets/figures/analysis_02_execution_effect_boundary.{dot,svg}`
- Create: `docs/agents/assets/figures/analysis_03_api_connection_architecture.{dot,svg}`
- Create: `docs/agents/assets/figures/knowledge_01_closed_loop_handoffs.{dot,svg}`
- Create: `docs/agents/assets/figures/knowledge_02_execution_effect_boundary.{dot,svg}`
- Create: `docs/agents/assets/figures/knowledge_03_api_connection_architecture.{dot,svg}`
- Modify: `docs/agents/analysis_agent.md`
- Modify: `docs/agents/knowledge_agent.md`

**Interfaces:**
- Consumes: Analysis/Knowledge manifests, CAE bridge, run artifacts, Knowledge repositories/services, graph sync, relation review, and BO context contracts.
- Produces: six figure pairs distinguishing raw/derived evidence and durable local/graph state.

- [ ] **Step 1: Add three Analysis figures**

Figure 1 shows Equipment artifact and metadata entering Analysis; canonical
curve, UTM metrics, optional FEM comparison, objective/uncertainty, evaluation,
and BO/Knowledge handoffs leaving; invalid input and unresolved units route to
error rather than fabricated measurement.

Figure 2 names all 22 internal IDs and `cae.run_static_analysis`. Show input
fingerprint, format/parser, raw table, columns/units, canonical curve,
preprocess/quality, metrics, optional CAE prepare/probe/run/compare/refine,
objective/prior comparison, artifacts/evaluation, and BO handoff. Dashed CAE
paths remain optional.

Figure 3 shows run artifacts -> parser/metric logic -> derived artifacts and
`/api/cae/config`/`run` -> CAE bridge -> optional CalculiX process ->
FEM/result evidence. No physical-device edge exists.

- [ ] **Step 2: Expand Analysis lineage and optional-process detail**

Add trace rows with input hash, parser, unit resolution, raw/derived identity,
quality gate, metric formula category, solver config/probe, comparison,
objective uncertainty, and BO handoff. Add connection lifecycle rows for the
optional CAE process including known-no-effect cancellation versus ambiguous
external failure.

- [ ] **Step 3: Add three Knowledge figures**

Figure 1 shows accepted stage artifacts/reports/decisions/provenance entering
Knowledge and BO/Design/Guardian/Evolution contexts leaving, with durable
records and graph-sync degradation separated from control flow.

Figure 2 names all 12 internal IDs, eight output contracts, and five transition
conditions. Show provenance/ontology gates, experiment record, patterns,
performance ledger, BO context, evolution ranking/packs/report/prefill,
outbox/receipt, and explicit absence reasons.

Figure 3 shows Knowledge APIs, service, ontology, ledger, JSONL repositories,
outbox, optional graph/Neo4j/Graphify, relation scan/reconcile/operator review,
existing-node edit validation, bounded query, already-loaded model with
priority lease, and graph receipts. No raw-Cypher or auto-activation edge exists.

- [ ] **Step 4: Expand Knowledge durability and degraded-sync detail**

Add trace/lifecycle rows for provenance normalization, ontology validation,
ledger append, local record, outbox enqueue, graph write, receipt, context
read, relation proposal/review, and evolution recommendation. Explain which
state remains authoritative when optional graph sync is degraded.

- [ ] **Step 5: Render, validate, and commit**

Render all six sources; audit 22/1 Analysis and 12/8/5 Knowledge
step/tool/output/transition coverage; validate both documents; commit:

```bash
git add docs/agents/assets/figures/analysis_* docs/agents/assets/figures/knowledge_* docs/agents/analysis_agent.md docs/agents/knowledge_agent.md
git commit -m "docs: illustrate analysis and knowledge agents"
```

### Task 7: Add Root and Documentation Navigation

**Files:**
- Modify: `README.md`
- Modify: `docs/agents/README.md`
- Modify: `docs/agents/agent_api_connection_matrix.md`
- Modify: `docs/README.md`
- Modify: `docs/paper/appendix_a_interfaces.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all 26 rendered figures and ten canonical References.
- Produces: a ten-row public entry table and consistent index/matrix/paper navigation.

- [ ] **Step 1: Add the root README Agent References table**

Insert a top-level `## Agent References` section after the closed-loop system
explanation. Link the Agent Index and API/Connection Matrix above the table.
Use exactly these rows and bounded role/effect messages:

| Agent | Actual role | Primary input → output | Highest effect |
|---|---|---|---|
| Orchestrator | compiles mission, context, handoffs, and routes | intent/state → mission, handoff, decision, route | model/local state; no direct device |
| Design | selects a constrained experiment candidate | objective/priors → experiment specification | model/local state; no physical action |
| Specimen Making | creates the manufacturing digital thread | experiment specification → fabricated-specimen evidence/handoff | physical possible after printer gates |
| Vision | emits freshness-bounded observation and verification | camera/context → vision report/signal/evidence | read-only observation; verified stop possible |
| Manipulation | supervises bounded robot transfer | specimen/fresh vision → verified transfer result | physical possible after robot gates |
| Lab Equipment | executes registered instrument protocols | verified placement/protocol → measurement/proof | desktop and physical possible after live gates |
| Analysis | derives curves, metrics, objectives, and optional CAE comparison | raw measurement → evaluation/BO handoff | optional external analysis; no direct device |
| Knowledge | persists provenance, patterns, performance, and context | accepted artifacts/reports → durable records/contexts | local/external persistence; no physical action |
| BO | proposes the next constrained candidate | analysis/priors → ranked recommendation | model/local state; proposal only |
| Guardian | decides continue, review, stop, or error | risk/health/failures/approvals → route decision | blocks/stops downstream; no direct action |

Add `Details` links to every agent document and `Figures` links to every SVG
owned by that row.

- [ ] **Step 2: Add figure navigation to the agent index**

Add a concise `Visual Contract` section and a `Figures` column to the canonical
inventory. Each row links `Flow`, `Execution`, and `Connections` where present.
State that figures are inspection-backed projections and the executable graph,
manifest, routes, and bridges remain authoritative.

- [ ] **Step 3: Update matrix, documentation index, paper appendix, and changelog**

- Matrix: link to the visual inventory after Summary and explain that the
  matrix compares cross-agent facts while figures explain one agent.
- Documentation index: state that canonical References include paired
  editable/rendered architecture figures.
- Paper appendix: link to the Agent Index visual inventory without duplicating
  it.
- Changelog: add 26 paired figures, deeper execution/connection/recovery
  detail, root navigation table, and automated figure checks under Unreleased.

- [ ] **Step 4: Run navigation and document validation**

Run the general validator, paper validator, focused tests, and direct link scan.
Expected: all ten root links, 26 image links, sources, renderings, and captions
are accepted.

- [ ] **Step 5: Commit navigation integration**

```bash
git add README.md docs/agents/README.md docs/agents/agent_api_connection_matrix.md docs/README.md docs/paper/appendix_a_interfaces.md CHANGELOG.md
git commit -m "docs: expose illustrated agent references"
```

### Task 8: Render, Audit, and Verify the Complete Set

**Files:**
- Modify only if audit finds a defect: `docs/agents/assets/figures/*`, canonical agent References, navigation files, validator/tests, or this Plan.

**Interfaces:**
- Consumes: completed figure/document/navigation set.
- Produces: fresh render equivalence, manifest coverage, route consistency, public-content safety, and a documentation-only final diff.

- [ ] **Step 1: Verify exact asset and embedding inventory**

Assert 26 `.dot` and 26 `.svg` files, two figures in every agent document,
three only in the six complex documents, and matching stable caption markers.
Assert the root README contains exactly ten canonical agent rows.

- [ ] **Step 2: Compare fresh Graphviz output**

Create a temporary directory with `mktemp -d`, render every `.dot` source using
Graphviz 2.43.0-compatible `dot -Tsvg`, and compare each byte-for-byte with its
checked-in SVG. Remove only the explicit temporary directory after comparison.

- [ ] **Step 3: Re-audit manifest and API coverage**

For all ten manifests, confirm every tool, pre-execution ID, internal-step ID,
output contract, supported task, and transition condition still appears in the
owning Reference. Import `app.main.app` and recheck every literal or grouped API
path in the modified References against `APIRoute` objects.

- [ ] **Step 4: Run public-content scans**

Run unresolved-marker, personal-path, secret, malformed-table-pipe, and broken
local-link scans over the ten References, index, matrix, root README, and SVG
labels. Expected: no matches or validation defects.

- [ ] **Step 5: Run final required checks**

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py
.venv/bin/python -m py_compile scripts/validate_documentation.py
git diff --check
git status --short
```

Expected: both validators pass; all focused tests pass; Python compilation
passes; no whitespace errors; `.env.example` is the only unrelated
modification.

- [ ] **Step 6: Mark this Plan completed and commit audit corrections**

Set all Plan checkboxes to complete and `execution_status: completed`. Stage
only files in this Plan and commit:

```bash
git add docs/agents docs/standards/documentation_standard.md scripts/validate_documentation.py tests/unit/test_documentation_validation.py README.md docs/README.md docs/paper/appendix_a_interfaces.md CHANGELOG.md docs/superpowers/plans/2026-08-09-agent-reference-figures-and-navigation.md
git commit -m "docs: verify illustrated agent references"
```

## Completion Report

Report:

- the 26 editable/rendered figure pairs;
- the ten enriched References and six third-figure connection maps;
- root README and index navigation;
- validator and test coverage;
- fresh Graphviz comparison result;
- focused test result and the known boundary of any unrelated full-suite
  failures;
- preserved `.env.example` change;
- final commit and push status only if publishing is explicitly authorized.
