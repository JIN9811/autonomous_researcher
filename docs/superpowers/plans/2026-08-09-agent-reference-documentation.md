# Canonical Agent Reference Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a uniform, code-backed Reference for each of ATR's ten executable agents plus a shared API, connection, contract, and safety matrix.

**Architecture:** `docs/agents/README.md` is the entry point, `agent_api_connection_matrix.md` owns cross-agent facts, and ten focused References own agent-specific behavior. Each Reference follows the same section contract and distinguishes owned, connected, operator, and shared API surfaces. Existing `.txt` and older `.md` guidelines remain linked legacy detail, while the governed document manifest and repository/paper indexes point to the new canonical set.

**Tech Stack:** Markdown with governed YAML front matter, YAML module manifests, Python/FastAPI `APIRoute` inspection, existing documentation validators, Git.

## Global Constraints

- Cover exactly these agents: Orchestrator, Design, Specimen Making, Vision, Manipulation, Lab Equipment, Analysis, Knowledge, BO, and Guardian.
- Use runtime implementation baseline `0b7627b`; later commits through `99f145d` change documentation only.
- Every agent Reference uses the exact H2 order defined in `docs/superpowers/specs/2026-08-09-agent-reference-documentation-design.md`.
- Each Reference includes role and non-role, handoffs, inputs/outputs, internal execution, API surface, tools/connections, state/evidence, modes, safety, errors/recovery, GUI, verification, limitations, and related documents.
- API classifications are `owned`, `connected`, `operator`, and `shared`.
- Effect classifications are `read_only`, `local_state`, `model`, `external_service`, and `physical_possible`.
- API paths come from imported FastAPI `APIRoute` objects, not decorator grep.
- Large route families are grouped by complete functional category and include initiating, stopping, status, validation, and evidence endpoints; they are not copied as undifferentiated lists.
- A module tool, internal step, or output contract must not be omitted from its canonical Reference.
- Physical or desktop-capable actions state their Guardian/operator/dry-run/preflight gates and unknown-effect rule.
- Current implementation facts use present tense; optional, historical, proposed, and unevaluated behavior are labeled.
- Do not invent scientific, browser, simulation, or live-hardware evidence.
- Do not print credentials, private endpoints, personal paths, or unpublished data.
- Existing files under `docs/agents/` remain unchanged and are linked as legacy or domain-specific detail.
- Existing uncommitted `.env.example` changes remain untouched and unstaged.
- This implementation changes documentation only; it does not modify runtime code, routes, manifests, schemas, tools, or tests.

---

### Task 1: Agent Index and Cross-Agent Matrix

**Files:**
- Create: `docs/agents/README.md`
- Create: `docs/agents/agent_api_connection_matrix.md`

**Interfaces:**
- Consumes: `graphs/configs/atr_closed_loop.yaml`, all ten `graphs/modules/*/module.yaml` files, imported FastAPI routes, paper architecture chapters, and current runtime References.
- Produces: canonical navigation, stage/control-plane map, terminology, responsibility matrix, contract matrix, API matrix, connection matrix, and safety/recovery matrix.
- Produces links expected by all ten agent References.

- [ ] **Step 1: Reproduce the ten-agent inventory and route families**

Run:

```bash
.venv/bin/python -c 'from pathlib import Path; import yaml; root=Path("graphs/modules");
for path in sorted(root.glob("*/module.yaml")):
    module=yaml.safe_load(path.read_text())["module"]
    print(module["id"], module["handler"], len(module.get("tools", [])), len(module.get("internal_graph", [])))'
```

Run an imported `APIRoute` scan for these functional prefixes:

```text
Orchestrator: /api/planning, /api/run, /api/runs, /api/events, /api/approvals, /api/runtime
Design: /api/planning, /api/graphs
Specimen: /api/printer
Vision: /api/vision, selected /api/lerobot camera routes, UTM vision routes
Manipulation: /api/lerobot
Equipment: /api/equipment, /api/bridges
Analysis: /api/cae
Knowledge: /api/knowledge
BO: /api/bo
Guardian: /api/guardian, /api/approvals, run-scoped Guardian status
```

Expected inventory: ten module manifests and ten Python agent classes. Route families overlap; the scan is collection evidence, not ownership assignment.

- [ ] **Step 2: Write the canonical agent index**

`docs/agents/README.md` uses active `index/index` metadata and contains:

- English canonical summary plus a concise Korean navigation note;
- the ten-agent inventory with class, manifest, stage/plane, and primary Reference;
- the nominal loop and explicit control-plane placement of Orchestrator and Guardian;
- reader paths for researcher, operator, developer, and maintainer;
- terminology for agent, stage, module, handler, tool, bridge, service, owned/connected/operator/shared API, and evidence environment;
- authority and conflict resolution;
- legacy guideline inventory and its non-canonical status;
- update checklist and verification commands.

- [ ] **Step 3: Write all five matrix views**

`agent_api_connection_matrix.md` uses active `reference/system` metadata with `source_of_truth` covering agents, manifests, graph, routes, bridges, and knowledge services. It contains:

1. closed-loop responsibility matrix;
2. contract matrix;
3. API classification matrix;
4. connection/protocol/effect matrix;
5. safety and recovery matrix.

Every row covers all ten agents. No cell is blank: use `none`, `not_applicable`, `optional`, or a bounded explanation.

- [ ] **Step 4: Validate the two documents directly**

Run:

```bash
.venv/bin/python -c 'from pathlib import Path; from scripts.validate_documentation import validate_document; root=Path.cwd(); paths=[root/"docs/agents/README.md", root/"docs/agents/agent_api_connection_matrix.md"]; errors=[error for path in paths for error in validate_document(path, root)]; print("agent index and matrix validation passed" if not errors else "\n".join(errors)); raise SystemExit(bool(errors))'
```

Expected: `agent index and matrix validation passed`.

- [ ] **Step 5: Commit the shared documentation core**

```bash
git add docs/agents/README.md docs/agents/agent_api_connection_matrix.md
git commit -m "docs: add canonical agent documentation core"
```

### Task 2: Control-Plane Agent References

**Files:**
- Create: `docs/agents/orchestrator_agent.md`
- Create: `docs/agents/guardian_agent.md`

**Interfaces:**
- Consumes: `agents/orchestrator_agent.py`, `agents/guardian_agent.py`, their module manifests, graph overlays and transitions, controller/run lifecycle, approval/event APIs, Guardian status services, and Task 1 matrix.
- Produces: the authoritative coordination-versus-safety boundary used by all domain agent References.

- [ ] **Step 1: Document Orchestrator**

The Reference names all three pre-execution entries and all nine internal graph entries. It documents `operator_intent.v1`, `experiment_contract.v1`, `mission_contract.v1`, `orchestration_plan.v1`, `orchestrator_parallel_checks.v1`, `orchestrator_followup.v1`, `decision_register.v1`, `handoff_packet.v1`, and `loop_reflection.v1`.

The API table groups planning session/message/artifact routes, run start/pause/resume/stop/safe-stop/emergency lifecycle, run-scoped state/events/artifacts, approval routes, runtime state/model/backend routes, and SSE/recent events. It classifies them as shared/operator rather than claiming that every controller route is agent-owned.

The non-role states: no direct device execution, no replacement for Guardian safety authority, and no claim that a chat response is a completed run.

- [ ] **Step 2: Document Guardian**

The Reference names its three internal graph entries, `device.health` and `experiment.queue.status`, risk vectors, incidents, hardware alerts, tool-call records, corrective actions, approval queue, safety budgets, and route decisions.

The API table covers `/api/guardian/status`, incident-note routes, run-scoped Guardian status, run-scoped approvals, and compatibility approve/reject/revise routes. It distinguishes policy decisions from operator approval resolution and from Orchestrator route translation.

The safety section states LLM priority, stop authority, uncertainty handling, and that control presence does not establish live safety effectiveness.

- [ ] **Step 3: Validate control-plane References and cross-links**

Run direct `validate_document()` for both files and manually confirm that each `internal_graph.id` in the two manifests appears in the applicable Reference.

Expected: no metadata, path, or local-link errors; all internal IDs accounted for.

- [ ] **Step 4: Commit control-plane References**

```bash
git add docs/agents/orchestrator_agent.md docs/agents/guardian_agent.md
git commit -m "docs: document orchestrator and guardian agents"
```

### Task 3: Design and Specimen Agent References

**Files:**
- Create: `docs/agents/design_agent.md`
- Create: `docs/agents/specimen_agent.md`

**Interfaces:**
- Consumes: Design/Specimen implementations and manifests, planning/graph APIs, geometry and artifact tools, experiment evaluation, printer services, and Task 2 control boundaries.
- Produces: the authoritative objective-to-design and design-to-manufacturing contract descriptions.

- [ ] **Step 1: Document Design**

Name the Orchestrator pre-stage and all 12 Design internal steps. Explain objective normalization, prior BO/Knowledge/failure context, hypothesis/design space, deterministic candidates, constraints, repair/rejection, scoring, authoritative selection, report, and Specimen handoff.

Document the LLM as rationale review while deterministic constraints and ranking select `experiment_spec`. Describe `experiment_spec`, `design_report`, `design_candidate`, `candidate_ledger`, decisions, metrics, and handoff packet.

Classify planning session/message/artifact routes as connected/shared operator surfaces and graph authoring/validation/dry-run/run routes as operator platform surfaces rather than Design-owned execution APIs.

- [ ] **Step 2: Document Specimen Making**

Name all 11 Specimen internal steps and all six tools: geometry generation, mesh quality, manufacturability, specimen handoff artifact, experiment evaluation, and printer preparation.

Group printer APIs into status/video/fleet, connection/profile, upload/draft/gate/publish, slicing/prestart, autoejection/bed-clear, and proof/completion-audit categories. State which categories are read-only, local-state, external-service, or physical-capable.

Explain Bambu active provider versus operator-selected Prusa, manufacturing digital thread, source/patched hashes, start proof, autoejection evidence, ambiguous publish/start state, and Vision/Manipulation handoff.

- [ ] **Step 3: Validate Design/Specimen References**

Run direct document validation, compare manifest tools and internal IDs to the two References, and verify every named route through imported `APIRoute` output.

- [ ] **Step 4: Commit Design/Specimen References**

```bash
git add docs/agents/design_agent.md docs/agents/specimen_agent.md
git commit -m "docs: document design and specimen agents"
```

### Task 4: Vision and Manipulation Agent References

**Files:**
- Create: `docs/agents/vision_agent.md`
- Create: `docs/agents/manipulation_agent.md`

**Interfaces:**
- Consumes: Vision/Manipulation implementations and manifests, camera/UTM/LeRobot tools, LeRobot APIs, robotics bridges, transfer tasks, and control-plane References.
- Produces: the authoritative observation-versus-motion boundary and post-place verification contract.

- [ ] **Step 1: Document Vision**

Name all Vision internal steps, including both `03_*` entries, and all seven tools. Document observation task/zone resolution, capture, perception degrade, scene estimation, temporal events, signal arbitration, evidence packaging, freshness-bounded `vision_signal.v1`, active-camera autoejection confirmation, UTM placement verification, and verified rollout stop.

The API table covers specimen-pose status/snapshot/release, LeRobot active-camera pose and camera test, and connected UTM runtime/camera surfaces. State that Vision can stop a verified rollout but cannot start robot, printer, UTM, or PyAutoGUI action.

- [ ] **Step 2: Document Manipulation**

Name both supported tasks and all 11 internal steps. Document Pi0.5/LeRobot policy selection, direct-shell prohibition, specimen/Vision context, camera-return gate, profile/policy preflight, rollout session, SARM-lite, post-place Vision verification, decision, report, result, and evidence.

Group all 87 LeRobot routes into configuration/session, files/policies/datasets, ports/camera/profiles, teleoperation, recording, training/W&B, rollout, manipulation-agent, Isaac synthetic/IL/RL/Mimic/RGBD, visualization, and mirror categories. Include start/stop/status/validate/evidence endpoints for each applicable category.

The effect boundary states which routes can cause robot motion and that an unknown rollout effect requires stop/status/visual verification before replay.

- [ ] **Step 3: Validate Vision/Manipulation References**

Run direct document validation, manifest step/tool coverage, and imported route checks. Confirm that the two documents agree on camera freshness, post-place verification, and rollout stop ownership.

- [ ] **Step 4: Commit Vision/Manipulation References**

```bash
git add docs/agents/vision_agent.md docs/agents/manipulation_agent.md
git commit -m "docs: document vision and manipulation agents"
```

### Task 5: Equipment and Analysis Agent References

**Files:**
- Create: `docs/agents/equipment_agent.md`
- Create: `docs/agents/analysis_agent.md`

**Interfaces:**
- Consumes: Equipment/Analysis implementations and manifests, equipment skill runtime, Windows/PyAutoGUI and UTM bridges, CAE bridge, raw measurement/curve contracts, and adjacent agent References.
- Produces: the authoritative physical-instrument execution and measurement-to-analysis boundary.

- [ ] **Step 1: Document Lab Equipment**

Name all five internal steps and all four tools. Group APIs into bridge registry/action descriptors, UTM runtime/graph/frame/camera/calibration, live preflight/validation, skill draft/annotate/compile/validate/deploy/enable/test/delete, equipment profile/state/preflight/test, Windows configuration/readiness/discovery/connect/select/delete/test, local bridge, locator/screenshot, run-program, proof package, and completion audit.

Document exact-profile/skill resolution, deterministic segment execution, bounded recovery through Guardian, evidence handoff, desktop versus physical instrument effects, and live preflight/approval/unknown-effect rules.

- [ ] **Step 2: Document Analysis**

Name all 22 internal steps and `cae.run_static_analysis`. Explain input fingerprint, format/parser detection, raw table, column/unit resolution, canonical curve, preprocessing, quality, UTM metrics, FEM/CAE preparation/probe/run/compare/refine, objective/uncertainty, prior comparison, artifacts, evaluation, and BO handoff.

Document `/api/cae/config` GET/POST and `/api/cae/run`, distinguishing configuration state, external analysis process, raw measurement, derived curve, UTM metrics, FEM result, objective result, and BO evidence. State that missing physical measurements are not silently fabricated.

- [ ] **Step 3: Validate Equipment/Analysis References**

Run direct document validation, manifest coverage, route checks, and a manual cross-check that Equipment output categories align with Analysis input categories.

- [ ] **Step 4: Commit Equipment/Analysis References**

```bash
git add docs/agents/equipment_agent.md docs/agents/analysis_agent.md
git commit -m "docs: document equipment and analysis agents"
```

### Task 6: Knowledge and BO Agent References

**Files:**
- Create: `docs/agents/knowledge_agent.md`
- Create: `docs/agents/bo_agent.md`

**Interfaces:**
- Consumes: Knowledge/BO implementations and manifests, Knowledge service/repositories/reconciliation, graph APIs, analysis handoff, experiment benchmark, and feedback path.
- Produces: the authoritative durable-memory-to-next-candidate feedback contract.

- [ ] **Step 1: Document Knowledge**

Name all 12 internal steps and every declared output contract and transition condition. Explain artifact/provenance collection, reports, experiment knowledge, failure/success patterns, performance ledger, BO context, evolution targets/evidence packs, report, and Evolution Lab prefill.

Group Knowledge APIs into evolution/performance/patterns/outcomes, relation status/scan/reconcile/proposal/review, graph edit validate/apply, health/ontology/stats/activity/sync/query/import, Graphify scan/import, and run/BO/safety context.

Document ontology/ledger/outbox/receipt ordering, bounded query and no raw Cypher, existing-node-only relation edits, operator review, already-loaded LLM and priority lease, degraded graph sync, and recommendation-without-activation boundary.

- [ ] **Step 2: Document BO**

Name all 15 internal steps and `experiment.benchmark`. Explain analysis handoff, priors, evidence table, LLM hypothesis patch, search space, candidate pool, numeric acquisition, LLM preference, constraints/failure penalties, top-k, critique, recommendation, artifacts, and Design handoff.

Document `/api/bo/config` GET/POST, `/api/bo/benchmark`, and `/api/bo/run`. Distinguish configuration, bounded benchmark, direct operator workspace run, and closed-loop graph execution. State numeric acquisition/validators are authoritative and the result is a proposal, not a device action.

- [ ] **Step 3: Validate Knowledge/BO References**

Run direct document validation, manifest coverage, route checks, and a manual cross-check that Knowledge `bo_context` and BO Design handoff form a bounded feedback loop.

- [ ] **Step 4: Commit Knowledge/BO References**

```bash
git add docs/agents/knowledge_agent.md docs/agents/bo_agent.md
git commit -m "docs: document knowledge and bo agents"
```

### Task 7: Governance and Repository Integration

**Files:**
- Modify: `docs/document_manifest.yaml`
- Modify: `docs/README.md`
- Modify: `docs/paper/appendix_a_interfaces.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 1–6 documents.
- Produces: governed active References and discoverable paper/developer/operator navigation.

- [ ] **Step 1: Register the twelve new governed documents**

Add `docs/agents/README.md`, the matrix, and the ten agent References to `docs/document_manifest.yaml` immediately after the paper documents or in a contiguous agent block. Do not add the legacy guideline files.

- [ ] **Step 2: Update repository and paper navigation**

- `docs/README.md`: add the agent index and matrix to audience and type paths; replace the old agent map with canonical Reference links while retaining legacy links as secondary detail.
- `docs/paper/appendix_a_interfaces.md`: add canonical agent index/matrix links and state that the appendix summarizes rather than duplicates them.
- `README.md`: add one concise `Agent References` link under Paper Documentation or System Architecture.
- `CHANGELOG.md`: record the ten canonical References and matrix under Unreleased.

- [ ] **Step 3: Run governed document and publication validation**

Run:

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py
```

Expected: documentation validation passes, paper publication validation passes, and 23 focused tests pass.

- [ ] **Step 4: Commit repository integration**

```bash
git add docs/document_manifest.yaml docs/README.md docs/paper/appendix_a_interfaces.md README.md CHANGELOG.md
git commit -m "docs: integrate canonical agent references"
```

### Task 8: Full Agent Documentation Audit

**Files:**
- Modify only if an audit defect is found: files created or modified in Tasks 1–7.
- Preserve without staging: `.env.example`.

**Interfaces:**
- Consumes: complete canonical agent documentation set.
- Produces: verified coverage, valid links and metadata, consistent cross-agent boundaries, and a clean documentation-only diff.

- [ ] **Step 1: Audit the canonical inventory and section contract**

Confirm exactly ten `*_agent.md` canonical References plus the index and matrix. Confirm each agent Reference contains the 17 required H2 headings in the approved order.

- [ ] **Step 2: Audit manifest tool, step, and output coverage**

For each of the ten module manifests, compare `tools`, `pre_execution`, `internal_graph`, `output_contracts`, `supported_tasks`, and transition conditions against its Reference. Every declared item must be named or explicitly grouped with its IDs visible.

- [ ] **Step 3: Audit API paths and effect classifications**

Import `app.main.app`; verify every literal API path documented exists or is clearly marked as a path family containing parameterized routes. Review every `physical_possible`, `model`, and `external_service` row for its mode and gate.

- [ ] **Step 4: Run public-content and unresolved-marker scans**

Run:

```bash
rg -n 'T[B]D|T[O]DO|implement[[:space:]]+later|fill[[:space:]]+in[[:space:]]+details' docs/agents/README.md docs/agents/agent_api_connection_matrix.md docs/agents/*_agent.md
rg -n '/home/[^/[:space:]]+|C:\\Users\\|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY' docs/agents/README.md docs/agents/agent_api_connection_matrix.md docs/agents/*_agent.md
```

Expected: both scans return no matches.

- [ ] **Step 5: Run final validation and inspect scope**

Run:

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py
git diff --check
git status --short
```

Expected: both validators pass; 23 tests pass; no whitespace errors; `.env.example` is the only unrelated worktree modification.

- [ ] **Step 6: Commit audit corrections if tracked files changed**

```bash
git add docs/agents docs/document_manifest.yaml docs/README.md docs/paper/appendix_a_interfaces.md README.md CHANGELOG.md
git commit -m "docs: verify canonical agent references"
```

Do not create an empty commit when the audit requires no correction. Do not push unless the user explicitly requests it.
