<!-- atr-doc
doc_type: reference
subtype: system
status: active
authority: descriptive
audience:
  - researcher
  - reviewer
  - operator
  - developer
  - integrator
scope:
  - agents
  - api
  - connections
  - safety
summary: Cross-agent matrix of responsibilities, contracts, APIs, services, external effects, and recovery boundaries.
source_of_truth:
  - agents
  - graphs/modules
  - graphs/configs/atr_closed_loop.yaml
  - app/main.py
  - app/controller.py
  - app/analysis_fem_routes.py
  - app/cae_fields_routes.py
  - backends
  - device_bridges
  - knowledge
  - knowledge/http_api.py
  - knowledge/source_api.py
last_verified: 2026-09-12
verified_against: working-tree
related_docs:
  - docs/agents/README.md
  - docs/runtime/three_level_control_model.md
  - docs/paper/appendix_a_interfaces.md
  - docs/runtime/current_code_snapshot.md
supersedes: []
-->

# Agent API and Connection Matrix

## Summary

This Reference compares all ten ATR Framework agents used by AX4LAB across responsibility, contracts,
API classification, connections, effects, safety, and recovery. It is the
cross-agent source; individual References own detailed behavior.

The [Agent Reference Index](README.md#visual-contract) links the editable
and rendered agent figures. This matrix owns cross-agent comparison; each
figure explains one agent's position, execution, effect, and—where required—
connection boundary without duplicating the tables below.

## Scope

The matrix covers the intentional working-tree scope verified on 2026-09-12. API entries are curated
functional families checked against route declarations and active installers. They do not replace
`/openapi.json` and do not assign exclusive ownership where services overlap.

The refresh includes agent-local decisions, continuous BO inputs, independent
Analysis FEM, Knowledge Source Library, Equipment terminal review/recovery,
and the current Sunburst figure references. It adds no runtime or device path.

## Source of Truth

- `agents/*_agent.py`
- `agents/*_decision*.py`, `agents/analysis_improvement.py`, `agents/source_curation.py`
- `graphs/modules/*/module.yaml`
- `graphs/configs/atr_closed_loop.yaml`
- `app/main.py` and `app/controller.py`
- `app/analysis_fem_routes.py`, `app/cae_fields_routes.py`
- `knowledge/http_api.py`, `knowledge/source_api.py`, `knowledge/source_runtime.py`
- `backends/`, `device_bridges/`, and `knowledge/`

## Closed-Loop Responsibility Matrix

| Agent | Plane/stage | Preceding inputs | Authoritative work | Following handoff | Physical effect |
|---|---|---|---|---|---|
| Orchestrator | Control plane and Design pre-stage | Canonical session, operator intent, Setup block/revision, graph/run state, prior decisions | Bounded decision, mission/plan/context/handoff compilation, owner-validated Setup proposal, and all-confirmed admission | Existing active-agent/Guardian route; confirmed settings at next new run or a deterministic held admission | none; direct device execution prohibited |
| Design | `design` | Objective, constraints, prior BO/Knowledge/failure context | Code-owned checks and bounded LLM suitability decision; accepted experiment specification | Specimen Making | none |
| Specimen Making | `specimen` | Approved experiment specification and fabrication intent | Bounded LLM suitability/tool decision, manufacturing digital thread and print handoff | Vision and Manipulation readiness | `physical_possible` through printer service |
| Vision | `vision` plus verification sidecars | Specimen/manipulation context, camera and scene state | Bounded decision plus ordered raw/annotated review, freshness-bounded observation, and verification signals | Manipulation, Equipment, Specimen completion, Guardian | `physical_possible` through ActiveCam move/capture/return and verified rollout stop |
| Manipulation | physical transfer and post-test clearance | Specimen result, fresh Vision, configured skill and execution evidence | LLM-selected bounded tool call; task-result judgment after Vision and termination | Vision, Equipment, Analysis, Knowledge | `physical_possible` through existing robot executors |
| Lab Equipment | `equipment` | Verified placement/specimen, exact stacked Flow/Skills, approvals | Bounded LLM Flow selection; deterministic execution; terminal screenshot/log review | Manipulation clearance → fresh Vision → Analysis | `physical_possible` through existing gated workers |
| Analysis | `analysis` plus independent background worker | Identified measurement, geometry and bound objective | LLM action/evidence review; tool-computed curves/objective; separately frozen FEM studies | Measured Knowledge/BO handoff without waiting for optional FEM; separate model evidence | none physically; registered computation |
| Knowledge | `knowledge` plus source-intake worker | Analysis, terminal archives and applicable source evidence | Ontology-guided Markdown, page-wise source curation, scoped retrieval and typed memory | Cited BO/agent context; separate Evolution review | none; persistent local Markdown/typed state |
| BO | `bo` | Analysis observations, continuous domain, settings, Knowledge context | Bounded LLM strategy/tool decision and review of the numerical candidate | Guardian and next Design cycle | none; proposal only |
| Guardian | Safety/control plane | State, risk, failures, device health, approvals, tool records | Deterministic policy/approval decision with advisory LLM note | Orchestrator route translation | no direct action; can block/stop downstream action |

## Decision and Tool-Calling Matrix

Local JSON actions are not automatically global tools or HTTP endpoints.
The owning Python dispatcher validates each choice before existing execution.

| Agent | LLM contribution | Action / execution boundary | Output authority |
|---|---|---|---|
| [Orchestrator](orchestrator_agent.md) | Schema-bounded `orchestrator_plan` choice for context, availability, Setup proposal, owner review, handoff, or defer | Code validates allowed tools/scope/evidence and owner adapters validate before draft persistence, then apply/read back only declared settings; no direct device tools | Explicit confirmation schedules a next new run, whose admission validates the captured set and consumes it only after readback |
| [Design](design_agent.md) | Accept, inspect or return candidate suitability | Agent-local evidence queries and candidate acceptance | Prepared candidate, locked inputs and hard checks |
| [Specimen](specimen_agent.md) | Fabrication suitability and tool choice | `inspect_fabrication_evidence`, `execute_fabrication`, `return_to_owner`; execution uses existing evaluation/printer route | Geometry/process checks and actual printer evidence |
| [Vision](vision_agent.md) | Select current observation contract, then review same-capture evidence | `execute_verification`, `accept_visual_evidence`, `return_to_owner`; registered capture/detection callbacks | Detector facts, identity/freshness and existing completion gates |
| [Manipulation](manipulation_agent.md) | Configured-skill suitability and post-Vision task-result review | Existing rollout, fixed skill or replay proposal; result acceptance only after ended execution and accepted Vision | Saved policy/profile, robot executor and observed result |
| [Equipment](equipment_agent.md) | Stacked Flow selection, terminal screenshot/log review, eligible recovery | `execute_stacked_workflow`, `observe_workflow`, `accept_workflow_result`, offered wait/focus/resume or operator return | Exact Flow/Skills, invocation claim, CSV/readiness and no-repeat gates |
| [Analysis](analysis_agent.md) | Measurement admissibility, simulation action, mesh/result and improvement assessment | Phase-specific `option_id` selects offered numeric/CAE actions; background work uses frozen inputs | Numeric tools calculate metrics; FEM evidence does not replace measured objective |
| [Knowledge](knowledge_agent.md) | Inspect, classify, curate and select scope-bound evidence | Inspect/search/read/write/publish local actions; separate page-stage/consolidate/publish source workflow | Source citations, ontology, append-only Markdown/typed records |
| [BO](bo_agent.md) | Strategy/evidence sufficiency and exact numerical-result review | `inspect_diagnostics`, `retrieve_knowledge`, `run_optimizer`, `accept_recommendation`, `return_to_owner` | LHS/BoTorch computes coordinates in the declared continuous domain |
| [Guardian](guardian_agent.md) | Advisory policy note | Existing code evaluates gates; model text does not issue a recovery/device command | Policy, approvals, stop state, evidence and budget |

Explicit deterministic TEST branches are not evidence of an LLM call.
Each Reference records its own API/local verification and remaining gaps.

## Three-Level Control Matrix

The levels describe the runtime path of the automatic experiment loop, not
three separate applications. Guardian safety and Knowledge/evidence cross all
levels. Device Workspace APIs remain manual surfaces outside automatic stage
progression.

| Agent | High-Level Control | Middle-Level Control | Low-Level Control |
|---|---|---|---|
| Orchestrator | primary owner: mission, dispatch, handoff, cycle, route | intent/mission/context/follow-up/decision compilation | prohibited from direct device execution |
| Design | LLM accept / inspect / return decision in the governed Design stage | constrained candidate preparation and checked specification finalization | local evidence/check tools; no device authority |
| Specimen Making | fabrication stage and Vision/Manipulation readiness | geometry-to-fabrication digital thread and completion conditions | geometry tools and selected printer provider bridge |
| Vision | observation stage plus verification sidecars; execute or return the current registered contract | decision/image protocol, same-capture review, and source/freshness/quality arbitration | camera, ROS/UTM, ActiveCam move/capture/return, verified rollout stop; no arbitrary driver or replay-start command |
| Manipulation | configured-skill suitability and evidence-supported task handoff | transfer/clearance tool dispatch, supervision and post-Vision result review | LeRobot rollout/fixed-skill/replay, process/port/camera and optional Isaac boundaries |
| Lab Equipment | measurement stage after verified placement; existing clearance/handoff routing | LLM selects configured Flow and reviews terminal evidence; durable claim and bounded safe recovery | Existing Skill Runtime and Windows/Local PyAutoGUI workers; no intermediate Equipment LLM calls |
| Analysis | measurement admissibility and offered simulation/improvement choices | parse/normalize/derive objective; schedule and review independent frozen FEM | numeric routines, registered prepare/solve and field postprocessing |
| Knowledge | reusable evidence and scoped context before BO/agent consumption | provenance, typed records, page-wise source curation and context publication | audit/ontology/Markdown/JSONL and Source Library adapters; no active graph backend |
| BO | BO-owned strategy and result judgment before Guardian/Design | Validated dispatch, LHS state, candidate integrity and handoff | BoTorch and benchmark computation tools |
| Guardian | cross-level continuation authority | policy/risk/evidence/health/approval evaluation with advisory LLM context | read-only health/queue plus block/stop; hard interlocks remain in bridges |

See [Three-Level Control Model](../runtime/three_level_control_model.md) for
state ownership, failure propagation, and the manual Device Workspace boundary.
The agent-local five-area maps add Guardian/Safety and Knowledge/Evidence as
cross-cutting responsibilities, not additional sequential model calls.

## Contract Matrix

| Agent | Required state | Primary output contracts | Checkpoint/evidence | Blocking condition |
|---|---|---|---|---|
| Orchestrator | Canonical planning session, current scope, accepted values, Setup revision, admitted candidates | mission/handoff/decision contracts plus Setup proposal/readback records | planning transcript, Setup history/receipts, events, checkpoint/run metadata | missing/stale scope, unsupported owner, unknown availability, Guardian route, terminal state |
| Design | objective + constraint context | `experiment_spec`, design report/candidate/ledger, handoff packet | design artifacts, decisions, metrics | hard constraint failure or no valid candidate |
| Specimen Making | complete fabrication specification | STL/mesh/process/slice/fabrication result and specimen handoff | source/patched hashes, printer proof, digital thread | missing fields, QA failure, start gate, bed-clear/proof failure |
| Vision | available capture/zone/task and fresh context | `vision_report.v1`, `vision_signal.v1`, evidence refs | images, pose/event reports, timestamps/expiry | unavailable capture or stale/low-quality signal |
| Manipulation | scoped transfer/clearance task, fresh Vision, configured policy or replay and preflight | `manipulation_report.v1`, `robot_task_result.v1`, decision and handoff evidence | rollout/replay session, confirmed termination, measured return and Vision refs | preflight, stale/conflicting Vision, unconfirmed termination, rejected result review |
| Lab Equipment | exact Profile/Flow/Skills, verified placement, bridge readiness | existing result/report/handoff plus decisions and workflow execution ID | durable invocation, completed-block checkpoint, terminal screenshot/hash, logs, CSV/readiness | existing hard gates, rejected review, changed scope, claimed invocation or unknown effects |
| Analysis | identifiable measurement, initial geometry/dimensions, units and objective domain | canonical curves/metrics, measured BO handoff; separate FEM jobs/fields/model evidence | frozen raw/geometry hashes, parser/coverage record, decision and job receipts | invalid measurement blocks BO; optional FEM failure does not rewrite the measured result |
| Knowledge | source identities, allowed scope and evidence; separate terminal-archive/source intake | `knowledge_context.v1`, `knowledge_report.v1`, `evolution_proposal.v1`, typed records and one curated note per source | Markdown revisions, source/page/block citations, intake receipts and audit | provenance/ontology/scope rejection; failed source stays unavailable to default retrieval |
| BO | valid observations and bounded search space | numerical candidate, decision, artifacts, Design constraints and domain | tool/evidence trace, numerical result, accepted candidate identity | model/optimizer failure, owner return, candidate validation rejection |
| Guardian | current state, risk/device/failure/approval context | gate/decision/contract, incidents, corrective actions | Guardian events, approval and incident records | unsafe, uncertain, exhausted budget, missing approval or evidence |

## API Classification Matrix

| Agent | Owned API | Connected API | Operator/shared API | Route/schema source |
|---|---|---|---|---|
| Orchestrator | planning session/message plus scoped Setup proposal/action contract | owner availability/readback and registered model backend | run lifecycle, run events/artifacts, approvals, SSE/recent events | `/openapi.json`, `/api/planning/*`, `/api/run*`, `/api/runtime/*` |
| Design | no dedicated direct execution endpoint | planning artifact/session context | `/api/graphs/*` authoring/validate/dry-run/run | `/openapi.json`, graph execution handler |
| Specimen Making | no direct agent endpoint | `/api/printer/*`, geometry/artifact tools | printer workspace and selected module management | `/openapi.json`, printer service/bridge implementations |
| Vision | specimen-pose status/snapshot/release | camera, active robot camera, UTM vision/runtime APIs | Vision/UTM workspaces and run retry | `/openapi.json`, Vision tools/bridge handlers |
| Manipulation | manipulation-agent config/test/run | `/api/lerobot/*` robotics services | LeRobot workspace configuration/training/simulation/mirror | `/openapi.json`, LeRobot bridge |
| Lab Equipment | no isolated agent endpoint | `/api/equipment/*`, `/api/bridges*` | equipment skill/profile/worker/UTM workspaces | `/openapi.json`, equipment bridge/tool registry |
| Analysis | `/api/analysis/fem/jobs` and scoped job cancellation; not direct graph-stage execution | `/api/cae/config`, `/api/cae/run`, `/api/cae/fields*` | CAE workspace, field viewer and run artifacts | `/openapi.json`, Analysis FEM and CAE route modules |
| Knowledge | context/report/Markdown via Knowledge service | `/api/knowledge/markdown/*`, `/api/knowledge/sources/*`, ontology and typed-memory surfaces | Source intake settings/scan/retry; archive intake and scoped note lifecycle | `/openapi.json`, active Markdown/source installers; retired graph/manual routes excluded |
| BO | `/api/bo/run` direct bounded workspace execution | `/api/bo/config`, `/api/bo/benchmark` | BO workspace and graph-run context | `/openapi.json`, BO agent/benchmark services |
| Guardian | `/api/guardian/status`, run-scoped status | device health and queue status tools | incidents and approval review/resolve APIs | `/openapi.json`, Guardian status/policy services |

## Connection and Effect Matrix

| Agent | LLM route | Internal services | External software/protocol | Device boundary | Highest possible effect |
|---|---|---|---|---|---|
| Orchestrator | Python: `orchestrator_plan`; manifest: `orchestrator_supervisor` | controller, Setup store/application, owner adapters, run loop, checkpoint/event/planning services | registered API/vLLM model backend for bounded decisions | none | model/local_state |
| Design | `design_reasoning` | candidate checks and validated local decision loop | registered model backend for suitability/tool decisions | none | model/local_state |
| Specimen Making | `specimen_reasoning` | bounded suitability tools, geometry, artifact, evaluation, printer manager | slicer/provider, Bambu MQTT/HTTP artifact path, Prusa bridge where selected | 3D printer | physical_possible through existing gates |
| Vision | `vision_observation` with bounded JSON tools and ordered `LLMImageInput` pairs | decision validation, pose tracker, signal arbitration, evidence packaging | camera, ActiveCam, ROS/UTM runtime, shared API/vLLM multimodal route | cameras; ActiveCam robot motion; rollout stop process | physical_possible through ActiveCam move/capture/return and verified stop |
| Manipulation | `manipulation_plan` | policy/profile/session logic | LeRobot processes, serial/camera, Isaac services | robot/manipulator | physical_possible |
| Lab Equipment | Equipment-owned `equipment_workflow_decision`; bounded proposals and shared `LLMImageInput` | terminal decision boundary, durable Equipment Runtime, exact Flow/Skill registry | registered API/local model; existing PyAutoGUI worker and desktop application | profile-selected laboratory equipment | physical_possible through existing gated execution |
| Analysis | Phase-specific `analysis_reasoning`; manifest role empty | numeric analysis, independent FEM job/model store and field readers | registered API/vLLM decisions; CAE/CalculiX computation bridge | none directly | model/local_state/external computation |
| Knowledge | `knowledge_query` for agent curation and background source curation | ontology, audit, Markdown/typed stores, Source Library and watcher | registered API/vLLM model service; page-wise extraction and consolidation | none | model/local_state |
| BO | `bo_policy` | strict local tool dispatch and numerical candidate validation | selected model backend for strategy/evidence/result decisions | none | model/local_state |
| Guardian | Python: `guardian_reasoning`; manifest: `guardian_review` | policy gate, status aggregation, approval/event services | device/queue status and registered model for advisory note | none directly | model plus downstream stop/block |

The Python call roles above and module `llm_role` declarations are separate
source facts. Orchestrator and Guardian currently use different names at these
two boundaries; this matrix does not silently rename or merge them. Analysis's
empty manifest role does not mean it has no internal LLM calls. Registered
backend routing and shared leases apply; no model service is started here.

### Background and Source Interfaces

All ten current agent owners receive bounded, reference-only Wiki context at
their existing LLM decision entrypoints through `agents/knowledge_context.py`.
This is not a new execution stage or tool permission. Retrieved, delivered and
model-cited states are distinct; structured tool schemas retain their existing
evidence allowlists. See [Wiki and Memory](../knowledge/wiki_memory.md).

| Surface | Purpose | Effect |
|---|---|---|
| `GET /api/analysis/fem/jobs` | Filter background jobs by run/loop/specimen | Read-only; never starts or resumes a solve |
| `POST /api/analysis/fem/jobs/{job_id}/cancel` | Cancel the addressed computation with run scope | Computation cancellation only |
| `GET /api/cae/fields`, `/metadata`, `/section`, `/render` under that prefix | Read fields/frames and perform local section/render postprocessing | No solver invocation or device action |
| `POST /api/knowledge/markdown/query`, `/read` | Search/read scoped execution knowledge | Read-only retrieval |
| `GET /api/knowledge/workspace/summary` | Wiki, authorized memory and delivery revisions | Read-only; no scan or model call |
| `POST /api/knowledge/wiki/query`, `/read` | Checked public platform reference | Read-only |
| `POST /api/knowledge/memory/query`, `/read` | Authorized private records | Trusted server principal required |
| `POST /api/knowledge/memory/commands` | Propose, confirm, revise, dismiss, expire or forget | Private-memory state only; no execution approval |
| `POST /api/knowledge/delivery/query`, `/read` | Scoped delivery receipts | Read-only; retrieval is not proof of model use |
| `POST /api/knowledge/markdown/intake` | Import terminal archives through the preservation hook | Local deterministic intake; no agent replay |
| `GET /api/knowledge/sources/status` | Inspect the source-intake worker/catalog | Read-only |
| `POST /api/knowledge/sources/settings`, `/scan`, `/retry` | Enable/schedule or retry source intake | Local state; may schedule background LLM curation |
| `POST /api/knowledge/sources/query`, `/read` | Retrieve current source notes with applicability and citations | Read-only retrieval |
| `knowledge.sources.search`, `knowledge.sources.read` | Registered source-reference tools for agent consumers | Scoped reference evidence; no command or measurement replacement |

Source inputs are inspected page-by-page and consolidated into one curated
Markdown note per original source. Raw text and page provenance remain stored.
Legacy Knowledge graph/relation and manual-specific routes are retired (HTTP
410 compatibility handlers), not current retrieval interfaces. The executable
LangGraph and the ontology vocabulary remain in use.

## Safety and Recovery Matrix

| Agent | Main gate | Approval | Dry run/preflight | Stop owner | Unknown-effect rule |
|---|---|---|---|---|---|
| Orchestrator | required-input and Guardian route | requests/resolves through shared approval service | graph/module/run validation where applicable | operator/Guardian/controller | do not translate uncertainty into automatic continuation |
| Design | hard constraints and schema | not normally physical approval | deterministic validation | Orchestrator/Guardian | reject/repair candidate; no external effect assumed |
| Specimen Making | manufacturability, start, bed-clear, proof | required by configured live printer policy | slice/prestart/start gate | printer service/operator/Guardian | query printer and proof state before republish |
| Vision | capture quality and signal freshness | not normally required for observation | camera/runtime probe | may request/perform verified rollout stop | stale or missing observation blocks downstream handoff |
| Manipulation | profile/policy/Vision/return-to-VLA | configured live confirmation | camera/profile/bridge preflight | Guardian/operator plus rollout stop | status and visual verification before restarting motion |
| Lab Equipment | exact Flow/Skill/Profile/bridge, placement, identity and Guardian | existing live equipment action scope | live preflight and exact Skill validation | Guardian/operator/bridge stop | never replay completed work or unknown effects; one wait/exact-window focus, fresh observation and explicit safe failed-block resume only |
| Analysis | input identity/units/coverage; mesh/result and separate promotion gates | not_applicable to physical approval | registered prepare/solve with frozen evidence | scoped background-job/process cancellation | preserve raw and partial outputs; no fabricated measurement or automatic validated promotion |
| Knowledge | provenance/ontology/scope/lifecycle | operator reason for lifecycle changes | validate before note write/publication | bounded decision stop | retain original evidence; no fabricated model success |
| BO | search-space/constraint/validator gates | candidate still requires downstream governance | benchmark/dry-run where selected | Guardian/Orchestrator | reject candidate; no external physical effect |
| Guardian | safety policy, risk, budget, evidence | may require operator decision | reads device/queue health | Guardian/operator/controller | stop or review; uncertainty never becomes allow by default |

## Shared Data Flow

The shared runtime unit is `OrchestratorState`. Agent results are merged into
that state through allowlisted handlers; a module manifest does not make every
internal step an independently scheduled graph node. Checkpointed run state,
events, planning transcript, artifacts, durable knowledge, and external device
state have different lifetimes and must not be conflated.

With valid measured data, Analysis publishes its ordinary observation before
optional FEM completion. Frozen background evidence, candidate models and
promotion decisions remain separate. Knowledge source intake likewise runs
outside the experimental stage; retrieval supplies context to existing agent
decisions without changing their configured commands.

## API Collection Notes

This update inspects route declarations and the installer/retirement sequence,
not a running application's route count. `app/main.py` installs the Analysis
FEM and CAE field routers, replaces Knowledge graph routes with retirement
handlers, installs Markdown routes, retires manual-specific routes, and installs
Source Library routes. A raw prefix search would incorrectly count retired
definitions as active APIs. Use the deployed `/openapi.json` for that instance's
complete active schema; no server import or hardware initialization was needed.

## Compatibility Boundaries

- Module and handler IDs must remain allowlisted and version-compatible.
- LLM output does not bypass deterministic constraints, schemas, policy,
  ontology, or device bridges.
- UI descriptors do not grant execution authority.
- A connected service can be unavailable without changing the agent's logical
  contract; the run must expose unavailable/degraded state.
- Provider substitution creates a new evaluated configuration.
- Shared compatibility routes remain labeled compatibility routes rather than
  preferred ownership interfaces.

## Limitations and Known Gaps

The matrix does not enumerate every route payload field or provider-specific
error. It does not establish behavior across all optional combinations and
does not convert architecture inspection into runtime, browser, live, safety,
or scientific evidence.

## Verification

Updated on 2026-09-11 by source inspection at `5a190e8`: agent/decision modules,
ten manifests, the primary graph, source/API installers, Analysis job/field
interfaces, and owning References. Documentation/link checks cover this edit.
Prior API/local inference and live evidence remain attached to the individual
References; this update performs no model inference or device actuation.

## Related Documents

- [Agent Reference Index](README.md)
- [System Architecture](../paper/02_system_architecture.md)
- [Platform Architecture](../paper/04_platform_architecture.md)
- [Interfaces Appendix](../paper/appendix_a_interfaces.md)
- [Current Code Snapshot](../runtime/current_code_snapshot.md)
