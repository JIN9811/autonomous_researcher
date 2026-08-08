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
  - api_connections
  - runtime_contracts
summary: Approved design for ten uniform, code-backed agent References and a cross-agent API and connection matrix.
decision_status: approved
related_docs:
  - docs/README.md
  - docs/standards/documentation_standard.md
  - docs/standards/paper_documentation_standard.md
  - docs/paper/appendix_a_interfaces.md
  - docs/runtime/current_code_snapshot.md
supersedes: []
---

# Agent Reference Documentation Design

## Summary

This Design defines a canonical documentation set for all ten executable ATR
agents: Orchestrator, Design, Specimen Making, Vision, Manipulation, Lab
Equipment, Analysis, Knowledge, Bayesian Optimization (BO), and Guardian.

Each agent receives an independent, code-backed Reference using the same
structure. A shared index and API/connection matrix explain the closed-loop
order, ownership boundaries, cross-agent handoffs, services, devices, operator
surfaces, evidence, and safety gates. Existing agent guideline files remain as
legacy domain detail and are linked rather than deleted or silently treated as
canonical.

## Problem

The repository already contains substantial agent information, but it is
distributed across:

- `agents/*.py` implementations;
- `graphs/modules/*/module.yaml` execution manifests;
- the primary graph configuration;
- route handlers in `app/main.py`;
- tool registration and bridge implementations;
- runtime, GUI, hardware, and agent guideline documents;
- paper architecture and interface chapters.

The current `docs/agents/` files are inconsistent in naming, format, age, and
scope. Several are `.txt` guidelines written for one subsystem. They do not
provide one stable place to answer all of these questions for every agent:

- What does the agent actually own?
- What does it explicitly not do?
- What state and schemas does it consume and emit?
- Which API endpoints expose its behavior, configuration, or operator review?
- Which tools, services, devices, and model routes does it connect to?
- Which preceding and following agents exchange handoffs with it?
- What evidence is stored, where, and under which environment?
- Which safety, approval, freshness, validation, and recovery gates apply?
- Which statements are implemented, tested, historical, optional, or not
  evaluated?

Without a uniform contract, readers can confuse an operator workspace with an
agent-owned API, a tool registration with direct device authority, or a module
manifest with behavioral validation.

## Goals

1. Create one canonical active Reference per executable agent.
2. Make the real closed-loop role and non-role explicit.
3. Document input, output, event, artifact, state, and handoff contracts.
4. Distinguish owned, connected, and operator APIs.
5. Map tools to their implementation, service/device boundary, and effect.
6. Document Test, Replay, Simulation, Browser, and Live differences where the
   implementation exposes them.
7. Make Guardian, approval, dry-run, freshness, validation, and physical-effect
   boundaries visible.
8. Preserve exact source paths and code baseline for every current fact.
9. Give researchers a cross-agent matrix suitable for the paper appendix while
   giving operators and developers enough detail to find implementation and
   failure paths.
10. Keep legacy detailed guidelines discoverable without assigning them higher
    authority than the new References.

## Non-goals

- Rewriting agent implementation code, schemas, tools, routes, or runtime
  behavior.
- Generating a complete OpenAPI reference inside Markdown.
- Claiming that every exposed route is owned by one agent.
- Treating route count, internal-step count, or tool count as a performance
  metric.
- Replacing hardware-specific operating procedures.
- Promoting historical test notes into current evidence.
- Deleting or mass-renaming existing `docs/agents/*.txt` guidelines.
- Adding scientific, comparative, browser, or live-hardware results that were
  not executed for this documentation change.

## Current Baseline

The implementation baseline for agent facts is `0b7627b`. Later commits through
`6fa0982` changed documentation and documentation validators, not the agent,
graph, route, tool, bridge, or runtime implementation used by this Design.

The primary executable inventory is:

| Order or plane | Agent ID | Class | Module manifest | Primary graph role |
|---|---|---|---|---|
| Control plane | `orchestrator` | `OrchestratorAgent` | `graphs/modules/orchestrator/module.yaml` | Plans, prepares context, emits handoffs, records decisions, translates Guardian results |
| 1 | `design` | `DesignAgent` | `graphs/modules/design/module.yaml` | Converts objective and prior context into a constrained experiment specification |
| 2 | `specimen` | `SpecimenMakingAgent` | `graphs/modules/specimen/module.yaml` | Builds and validates the specimen/manufacturing digital thread |
| 3 and verification sidecars | `vision` | `VisionAgent` | `graphs/modules/vision/module.yaml` | Produces freshness-bounded observations and verification signals |
| Physical transfer branch | `manipulation` | `ManipulationAgent` | `graphs/modules/manipulation/module.yaml` | Supervises bounded robot policy execution behind LeRobot bridges |
| 4 | `equipment` | `LabEquipmentAgent` | `graphs/modules/equipment/module.yaml` | Resolves and executes registered instrument protocols behind bridges |
| 5 | `analysis` | `AnalysisAgent` | `graphs/modules/analysis/module.yaml` | Parses observations, computes metrics, and optionally invokes bounded CAE tools |
| 6 | `knowledge` | `KnowledgeAgent` | `graphs/modules/knowledge/module.yaml` | Persists provenance, knowledge, patterns, performance, and evolution evidence |
| 7 | `bo` | `BOAgent` | `graphs/modules/bo/module.yaml` | Ranks constrained next candidates using numeric acquisition plus bounded LLM advice |
| Safety/control plane | `guardian` | `GuardianAgent` | `graphs/modules/guardian/module.yaml` | Evaluates safety and continuation state and routes continue, stop, review, or error |

The primary graph remains the source of truth for actual order and branching.
This table is an explanatory projection and MUST NOT erase sidecars, conditional
edges, supervisor overlays, or terminal states.

## Options Considered

### Option A: Independent References plus shared matrix

Create a shared index, one independent Reference per agent, and one cross-agent
API/connection matrix.

Advantages:

- one agent can be reviewed or updated without rewriting all others;
- a reader can compare common fields across agents;
- large domains such as LeRobot and equipment remain focused;
- the matrix exposes boundaries and cross-agent flow without duplicating full
  prose;
- current References can link to legacy detailed guidelines.

Costs:

- repeated section structure;
- eleven or twelve maintained files instead of one;
- shared facts require careful linking to prevent duplication.

### Option B: One monolithic agent handbook

Put all ten agents and the connection matrix in one large file.

Advantages:

- one entry point;
- global search and printing are straightforward.

Costs:

- high merge conflict and review cost;
- difficult to keep API tables and hardware detail readable;
- one agent change invalidates the verification status of a large file;
- encourages duplicated cross-agent explanations.

### Option C: Distribute agent detail across paper chapters and domain guides

Expand the paper and current hardware/runtime guides without a new canonical
agent set.

Advantages:

- fewer new files;
- readers already in one domain see local context.

Costs:

- no single agent contract;
- paper narrative becomes operationally overloaded;
- API ownership and connection boundaries remain inconsistent;
- difficult to compare all ten agents.

## Decision

Use Option A. Create:

```text
docs/agents/
├── README.md
├── agent_api_connection_matrix.md
├── orchestrator_agent.md
├── design_agent.md
├── specimen_agent.md
├── vision_agent.md
├── manipulation_agent.md
├── equipment_agent.md
├── analysis_agent.md
├── knowledge_agent.md
├── bo_agent.md
└── guardian_agent.md
```

The new files are canonical current References. Existing files under
`docs/agents/` remain available as legacy domain guidelines and are linked from
the applicable Reference.

## Authority and Lifecycle

- `docs/agents/README.md` is an active `index/index` with navigation authority.
- `agent_api_connection_matrix.md` is an active `reference/system`.
- Each agent file is an active `reference/system`.
- Every active Reference declares implementation `source_of_truth`,
  `last_verified: 2026-08-09`, and `verified_against: 0b7627b`.
- Current facts use descriptive authority and present tense.
- Optional, historical, planned, and unevaluated behavior is labeled explicitly.
- Existing `.txt` and older `.md` guidelines are not added to the governed
  manifest merely because a new Reference links to them.

## Canonical Agent Reference Structure

Every agent Reference MUST use these H2 sections in this order.

### 1. Summary

One paragraph stating the agent's actual responsibility and control plane or
closed-loop position.

### 2. Scope

Included implementation boundary, excluded adjacent concerns, and evidence
environment. The section MUST say what the agent does not own.

### 3. Source of Truth

Exact implementation, manifest, graph, bridge/service, schema, and route source
paths. A generic folder path is allowed only when the document names the
specific responsibility represented by that folder.

### 4. Actual Role

The decision or transformation performed, why it exists in the loop, and the
authoritative mechanism when LLM reasoning and deterministic logic coexist.

Each file MUST include a `Does` / `Does not` table. Examples:

- BO proposes a candidate; it does not issue a physical command.
- Vision may stop a verified rollout; it does not start robot motion.
- Orchestrator coordinates workflow; Guardian retains safety authority.
- Knowledge proposes evolution targets; it does not activate variants.

### 5. Closed-Loop Position and Handoffs

Preceding and following stage, sidecars, conditional routes, inputs received,
outputs handed off, and terminal/error alternatives. A handoff table uses:

| Direction | Component | Contract or state | Purpose | Gate |
|---|---|---|---|---|

### 6. Inputs and Outputs

Document:

- relevant `OrchestratorState` fields;
- named schema/contract versions;
- required versus optional values;
- merge target in runtime state;
- artifact and evidence references;
- freshness or provenance requirements;
- explicit absence/reason contracts where applicable.

Fields are described at the stable contract level. Full data-model definitions
remain linked to implementation schemas rather than copied without bounds.

### 7. Internal Execution

Translate `module.yaml` pre-execution and internal graph entries into a table:

| Step | Kind | Consumes | Produces or decides | Failure boundary |
|---|---|---|---|---|

The document MAY group adjacent mechanical steps when all manifest step IDs are
still named. It MUST NOT imply that a listed manifest step has independent
runtime scheduling unless the implementation does so.

### 8. API Surface

API classification is mandatory:

- `owned`: directly exposes this agent's execution, configuration, status, or
  result contract;
- `connected`: a service API or tool surface used by the agent or its bridge;
- `operator`: supports configuration, review, evidence inspection, or manual
  invocation without being the agent's internal call contract;
- `shared`: run, event, approval, graph, module, or runtime API serving several
  agents.

Every endpoint row uses:

| Class | Method | Path or family | Runtime handler/service | Effect | Notes |
|---|---|---|---|---|---|

`Effect` is one of `read_only`, `local_state`, `model`, `external_service`, or
`physical_possible`. The exact effect can be conditional on mode and gate; the
notes state that condition.

Large route families are summarized by complete functional categories and the
endpoints that initiate, stop, inspect, validate, and retrieve evidence. For
example, the Manipulation Reference groups the 87 `/api/lerobot/*` routes by
configuration, ports/camera, teleoperation, recording, training, rollout,
policy/dataset, Isaac, mirror, and agent-control categories. It does not print
87 undifferentiated rows. The current OpenAPI endpoint remains the exhaustive
route source.

An endpoint MUST NOT be labeled `owned` solely because its URL resembles the
agent name. Ownership follows the service and handler boundary.

### 9. Tools and Connections

Each tool or connection row uses:

| Tool or service | Registry/implementation | Protocol or boundary | Mode | Effect | Evidence |
|---|---|---|---|---|---|

This section distinguishes:

- LLM route and role;
- Python/deterministic logic;
- internal service;
- local process;
- remote HTTP/WebSocket/MQTT/ROS/desktop bridge where implemented;
- simulator or compatibility fallback;
- physical equipment.

No document prints credentials or private endpoints. It names configuration
fields or public profile identifiers only.

### 10. State, Events, Artifacts, and Storage

Name run/cycle state fields, event families, report/artifact types, storage
roots, durable records, and API retrieval paths. The section distinguishes
ephemeral UI state, checkpointed runtime state, append-only evidence, and
external system state.

### 11. Modes and Fallbacks

State behavior in relevant Test, Replay, Simulation, Browser, and Live modes.
Unsupported modes are explicit. A fallback is described as a different
configuration/evidence environment, not equivalent validation.

### 12. Safety, Approval, and Effect Boundary

Document:

- Guardian role;
- operator approval requirements;
- dry-run/preflight/capability gates;
- freshness, ontology, schema, or validation gates;
- direct device or shell authority;
- stop and emergency behavior;
- ambiguous external-effect handling.

The section MUST distinguish control presence from validated effectiveness.

### 13. Errors and Recovery

Map failure codes or classes to effect uncertainty, persisted evidence,
operator-visible state, retry/resume condition, and prohibited retry behavior.
Physical or external actions with unknown effect do not receive a generic
automatic retry recommendation.

### 14. Operator and GUI Surfaces

Name page routes, workspaces, status cards, review flows, and read/mutation
boundaries. The document states whether the GUI invokes an agent, a service, a
bridge, or a compatibility API.

### 15. Current Verification

Record inspected baseline, manifest/route collection method, applicable focused
tests or existing Evidence, and observed API-family counts where useful. Counts
are drift indicators only.

### 16. Limitations and Known Gaps

State optional dependency, incomplete mode coverage, historical guideline
status, unexecuted behavior, and scientific/live evidence gaps.

### 17. Related Documents

Link the matrix, adjacent agent References, paper chapters, runtime References,
hardware/GUI guides, and applicable legacy guidelines.

## Per-Agent Content Requirements

### Orchestrator

MUST document:

- operator intent and mission-contract compilation;
- pre-execution role for Design;
- context packing, handoff, follow-up, decision register, loop reflection, and
  Guardian route translation;
- direct-device-execution prohibition;
- shared planning, run lifecycle, runtime state, events, artifacts, and approval
  API families;
- pause/resume, safe stop, emergency stop/resume/reset, and run-scoped routes;
- session transcript and checkpoint distinctions.

### Design

MUST document:

- objective/constraint normalization;
- prior BO, Knowledge, and failure context;
- deterministic candidate generation, hard constraints, repair/rejection,
  scoring, and authoritative selection;
- LLM rationale-review boundary;
- `experiment_spec`, reports, ledgers, decisions, metrics, and Specimen handoff;
- the distinction between planning APIs, graph-authoring APIs, and agent
  execution through the graph.

### Specimen Making

MUST document:

- specification intake and required-field gate;
- geometry/STL generation, mesh/manufacturability checks, slicing/G-code,
  manufacturing digital thread, execution gate, monitoring, repair/stop, and
  handoff;
- registered geometry, artifact, evaluation, and `printer.prepare` tools;
- printer fleet, connection, slicing, prestart, publish, autoejection,
  bed-clear, proof, and completion-audit API categories;
- Bambu/Prusa provider distinction and physical-effect boundary;
- Vision/Manipulation handoff and evidence.

### Vision

MUST document:

- task and zone resolution, capture, perception/degrade, scene state, temporal
  events, arbitration, visual evidence, and `vision_signal.v1`;
- signal freshness and downstream rejection of stale signals;
- active robot-camera ejection confirmation and UTM placement verification;
- authority to stop a verified rollout but not start robot motion;
- camera, LeRobot camera, UTM runtime, specimen-pose, and evidence surfaces;
- observation versus physical action boundary.

### Manipulation

MUST document:

- bounded `transfer_to_utm` and `clear_utm_to_disposal` tasks;
- LeRobot/Pi0.5 policy selection and direct-shell prohibition;
- Vision/specimen context, camera-return requirement, preflight, rollout,
  SARM-lite progress, post-place verification, recovery/stop/handoff;
- rollout, teleoperation, recording, training, policy/dataset, port/camera,
  Isaac, mirror, and manipulation-agent API categories;
- physical effect, session identity, proof, and uncertain-timeout handling.

### Lab Equipment

MUST document:

- profile/skill resolution, bridge validation, registered protocol execution,
  bounded recovery, and evidence handoff;
- `equipment.pyautogui.*` and `utm.run_protocol` tools;
- bridge registry, skill lifecycle, profiles, Windows discovery/connect/test,
  local bridge, locator/screenshot, run-program, proof/completion audit, and UTM
  ROS/camera API categories;
- Windows/PyAutoGUI, recorded skills, UTM runtime, and physical instrument
  boundaries;
- operator management and live preflight requirements.

### Analysis

MUST document:

- equipment artifact fingerprinting, parser/column/unit resolution, canonical
  curve construction, preprocessing, validation, UTM metrics, objective and
  uncertainty;
- optional CAE/CalculiX problem, probe, run, compare, accept/refine path;
- `cae.run_static_analysis` and `/api/cae/*` boundaries;
- evidence distinction among raw measurement, derived curve, UTM metric, FEM
  result, and BO handoff;
- no silent fabrication of missing physical measurements.

### Knowledge

MUST document:

- artifact collection, provenance normalization, report ingestion, experiment
  knowledge, failure/success patterns, performance records, BO context,
  evolution evidence, and reports;
- Knowledge service ingestion, ontology, ledger, durable outbox, graph receipt,
  bounded query, run/BO/safety context, activity, sync, and Graphify categories;
- relation scan/reconcile/review and existing-node-only graph edit flows;
- already-loaded LLM and priority-lease boundary for background reconciliation;
- recommendation versus activation boundary for self-evolution.

### BO

MUST document:

- analysis handoff, valid priors, evidence table, reasoning patch, search space,
  candidate pool, numeric acquisition, LLM preference, penalties, top-k
  critique, recommendation, artifacts, and Design handoff;
- numeric acquisition and validator authority over LLM advice;
- `/api/bo/config`, `/api/bo/benchmark`, and `/api/bo/run` distinctions;
- proposal-only boundary before Design, Specimen, Equipment, and Guardian;
- benchmark versus live-loop evidence.

### Guardian

MUST document:

- graph-wide safety checks, recent failure review, continue/stop/error/review
  decision;
- risk vectors, incidents, hardware alerts, tool-call records, corrective
  actions, approval queue, safety budget, and run-scoped status;
- `device.health` and `experiment.queue.status` tool connections;
- status, incident note, and approval resolution API categories;
- priority over background LLM work and separation from Orchestrator authority;
- control presence versus safety-effectiveness evidence.

## Cross-Agent Matrix Design

`agent_api_connection_matrix.md` provides five coordinated views.

### Closed-loop responsibility matrix

| Agent | Plane/stage | Preceding inputs | Authoritative work | Following handoff | Physical effect |
|---|---|---|---|---|---|

### Contract matrix

| Agent | Required state | Primary output contracts | Checkpoint/evidence | Blocking condition |
|---|---|---|---|---|

### API matrix

| Agent | Owned API | Connected API | Operator/shared API | Exhaustive source |
|---|---|---|---|---|

### Connection matrix

| Agent | LLM route | Internal services | External software | Device/physical boundary | Protocol |
|---|---|---|---|---|---|

### Safety and recovery matrix

| Agent | Main gate | Approval | Dry run/preflight | Stop owner | Unknown-effect rule |
|---|---|---|---|---|---|

Cells use `none`, `not_applicable`, `optional`, or an explicit boundary; blank
cells are prohibited.

## API Collection and Verification Method

API tables are built from imported FastAPI `APIRoute` objects rather than
decorator grep. The documentation records:

- HTTP methods;
- normalized path;
- route handler name;
- functional family;
- documentation classification;
- effect classification.

The exhaustive source remains `GET /openapi.json` or `/docs` from the selected
server commit. The new References do not freeze every Pydantic field or copy
the entire OpenAPI document.

Route families overlap by design. For example, approval routes are shared by
Orchestrator and Guardian, LeRobot camera routes connect Vision and
Manipulation, and module/graph routes configure execution surfaces rather than
belonging to one domain agent. The matrix MUST state overlaps instead of forcing
exclusive ownership.

## Connection Classification

Every connection is classified along two axes.

### Location and protocol

- in-process Python/service call;
- local process or file store;
- local/remote HTTP API;
- SSE or stream;
- desktop/PyAutoGUI bridge;
- printer provider/MQTT or HTTP artifact path;
- robotics process/serial/camera/Isaac boundary;
- ROS runtime;
- graph database/service;
- model provider/runtime.

Only protocols demonstrated by current code or active References are named.

### Effect

- `read_only`: observation or status only;
- `local_state`: repository-local state, configuration, artifact, or process;
- `model`: inference or model lifecycle;
- `external_service`: remote software state without a direct physical claim;
- `physical_possible`: a route/tool may produce a physical or desktop effect
  after mode, policy, approval, and bridge gates.

The most consequential possible effect is documented, even when Test mode is
the default example.

## Language and Duplication Policy

Canonical agent References are written in English to align with the paper
package. `docs/agents/README.md` includes a concise Korean navigation and
terminology note so Korean operators can locate the correct document.

Implementation contracts are stated once per owning agent. Adjacent agent
documents summarize the handoff and link to the owner. Shared run lifecycle,
approval, event, graph, module, and runtime APIs are fully explained in the
matrix and Orchestrator/Guardian References; other agents link rather than
copying the complete route table.

## Legacy Documentation Policy

The following existing files remain in place and are labeled as legacy or
domain-specific detail from the new References:

- `docs/agents/analysis_utm_runtime_guideline.txt`
- `docs/agents/bo_agent_runtime_guideline.txt`
- `docs/agents/cae_analysis_runtime_guideline.txt`
- `docs/agents/knowledge_agent_self_evolution_runtime_guideline.md`
- `docs/agents/manipulation_pi05_transfer_runtime_guideline.txt`
- `docs/agents/specimen_design_existing_runtime_guideline.txt`
- `docs/agents/vision_pickup_observation_runtime_guideline.txt`

Their existence does not make their metadata, counts, or current-behavior
claims authoritative. Where a legacy document conflicts with executable code,
the new Reference states the current behavior and identifies the legacy file as
historical detail.

## Documentation Integration

The implementation updates:

- `docs/document_manifest.yaml` to govern the index, matrix, and ten References;
- `docs/README.md` to add a paper/developer/operator agent path;
- `docs/paper/appendix_a_interfaces.md` to link the canonical matrix and agent
  index;
- root README paper-documentation navigation with one concise agent-reference
  entry;
- `CHANGELOG.md` with the new documentation surface.

The paper chapters do not duplicate the per-agent detail. They retain the
argument and link to the canonical References for implementation depth.

## Validation

The implementation MUST pass:

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py
git diff --check
```

Manual review MUST also confirm:

1. all ten modules and agent classes have exactly one canonical Reference;
2. every manifest tool and internal step appears in its Reference;
3. every API row exists in imported `APIRoute` output at baseline `0b7627b`;
4. ownership classification follows the handler/service boundary;
5. every physical-capable connection states its gate and unknown-effect rule;
6. every current fact names a source path;
7. no personal path, secret, private endpoint, or invented evidence appears;
8. no blank table cell conceals an unsupported or inapplicable capability;
9. local links resolve;
10. existing `.env.example` user changes remain untouched.

## Failure and Drift Handling

- A missing API path blocks activation of the affected Reference.
- A new manifest tool or internal step requires updating the relevant Reference
  in the same change when the behavioral contract changes.
- Route-family growth updates category descriptions and key endpoints; it does
  not require duplicating the complete OpenAPI output.
- A connection whose effect cannot be determined is classified conservatively
  and flagged for maintainer review.
- Optional service unavailability is documented as `optional` or
  `not_evaluated`, never silently described as active.
- A stale legacy guideline is not edited merely to match the new structure;
  the canonical Reference records the conflict and current source.

## Acceptance Criteria

1. `docs/agents/README.md` provides stage order, reading paths, terminology,
   and links to all ten References and the matrix.
2. All ten canonical files exist, share the required section order, and pass
   governed-document validation.
3. Every Reference includes actual role/non-role, handoffs, inputs/outputs,
   internal steps, APIs, connections, state/evidence, modes, safety, errors,
   GUI, verification, limitations, sources, and related documents.
4. The matrix exposes responsibility, contracts, APIs, connections, and safety
   across all agents with no ambiguous blank cells.
5. All module-declared tools and internal steps are represented.
6. API ownership versus connection versus operator/shared use is explicit.
7. Physical, desktop, model, and external-service effects are classified.
8. Orchestrator and Guardian authority remain separate and explicit.
9. The root/docs/paper navigation points to the new canonical agent set.
10. Existing legacy guideline files and `.env.example` remain untouched.
11. All required validators and focused tests pass.
12. The changes are committed in reviewable documentation units; pushing is
    performed only when explicitly requested.

## Limitations and Known Gaps

This documentation set will describe implementation contracts, not validate
agent intelligence, scientific quality, live safety effectiveness, usability,
or cross-device compatibility. API tables remain curated views over the
current OpenAPI surface rather than a replacement for it.

Some agent behavior is concentrated in large controller, route, or bridge
files. The References will point to precise responsibility areas but will not
refactor those files. Optional providers and historical guideline content may
remain uneven in detail because no new environment or live evidence is created
for this documentation task.

## Verification

The Design was checked on 2026-08-09 against:

- ten `agents/*_agent.py` implementations;
- ten `graphs/modules/*/module.yaml` manifests;
- `graphs/configs/atr_closed_loop.yaml`;
- imported FastAPI route groups from `app.main.app`;
- existing `docs/agents/` guidelines;
- the active Documentation and Paper Documentation Standards;
- the paper system, platform, evaluation, and interface documents.

## Related Documents

- `docs/standards/documentation_standard.md`
- `docs/standards/paper_documentation_standard.md`
- `docs/paper/02_system_architecture.md`
- `docs/paper/04_platform_architecture.md`
- `docs/paper/appendix_a_interfaces.md`
- `docs/runtime/current_code_snapshot.md`
