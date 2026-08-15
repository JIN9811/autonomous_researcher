---
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
  - backends
  - device_bridges
  - knowledge
last_verified: 2026-08-09
verified_against: 0b7627b
related_docs:
  - docs/agents/README.md
  - docs/runtime/three_level_control_model.md
  - docs/paper/appendix_a_interfaces.md
  - docs/runtime/current_code_snapshot.md
supersedes: []
---

# Agent API and Connection Matrix

## Summary

This Reference compares all ten ATR agents across responsibility, contracts,
API classification, connections, effects, safety, and recovery. It is the
cross-agent source; individual References own detailed behavior.

The [Agent Reference Index](README.md#visual-contract) links all 26 editable
and rendered agent figures. This matrix owns cross-agent comparison; each
figure explains one agent's position, execution, effect, and—where required—
connection boundary without duplicating the tables below.

## Scope

The matrix covers current code baseline `0b7627b`. API entries are curated
functional families over the imported OpenAPI surface. They do not replace
`/openapi.json` and do not assign exclusive ownership where services overlap.

## Source of Truth

- `agents/*_agent.py`
- `graphs/modules/*/module.yaml`
- `graphs/configs/atr_closed_loop.yaml`
- `app/main.py` and `app/controller.py`
- `backends/`, `device_bridges/`, and `knowledge/`

## Closed-Loop Responsibility Matrix

| Agent | Plane/stage | Preceding inputs | Authoritative work | Following handoff | Physical effect |
|---|---|---|---|---|---|
| Orchestrator | Control plane and Design pre-stage | Operator intent, session, graph/run state, prior decisions | Mission/plan/context/handoff/decision compilation | Active agent, Guardian route, next cycle or terminal | none; direct device execution prohibited |
| Design | `design` | Objective, constraints, prior BO/Knowledge/failure context | Deterministic constrained candidate selection and experiment specification | Specimen Making | none |
| Specimen Making | `specimen` | Approved experiment specification and fabrication intent | Manufacturing digital thread, geometry/QA/process/print handoff | Vision and Manipulation readiness | `physical_possible` through printer service |
| Vision | `vision` plus verification sidecars | Specimen/manipulation context, camera and scene state | Freshness-bounded observation and verification signals | Manipulation, Equipment, Specimen completion, Guardian | observation is read-only; verified rollout stop can affect robot process |
| Manipulation | physical transfer branch | Specimen result, fresh Vision signal, robot/profile/policy context | Bounded policy rollout, progress, verification request, transfer result | Vision verification, Equipment or Knowledge | `physical_possible` robot motion |
| Lab Equipment | `equipment` | Verified placement/specimen, protocol/profile/skill, approvals | Registered deterministic instrument/desktop protocol execution | Analysis | `physical_possible` desktop and instrument action |
| Analysis | `analysis` | Equipment artifact and measurement metadata | Canonical curve, metrics, optional CAE/FEM comparison, objective/uncertainty | Knowledge and BO handoff | none directly; optional external analysis process |
| Knowledge | `knowledge` | Accepted artifacts/reports/decisions/provenance | Durable knowledge, patterns, performance, BO/evolution context | BO, Design context, Evolution review | none; persistent local/graph state |
| BO | `bo` | Analysis handoff, prior trials, constraints, Knowledge context | Numeric acquisition and validated next-candidate recommendation | Guardian and next Design cycle | none; proposal only |
| Guardian | Safety/control plane | State, risk, failures, device health, approvals, tool records | Continue/review/stop/error safety decision | Orchestrator route translation | no direct action; can block/stop downstream action |

## Three-Level Control Matrix

The levels describe the runtime path of the automatic experiment loop, not
three separate applications. Guardian safety and Knowledge/evidence cross all
levels. Device Workspace APIs remain manual surfaces outside automatic stage
progression.

| Agent | High-Level Control | Middle-Level Control | Low-Level Control |
|---|---|---|---|
| Orchestrator | primary owner: mission, dispatch, handoff, cycle, route | intent/mission/context/follow-up/decision compilation | prohibited from direct device execution |
| Design | governed Design stage and Specimen handoff | constrained candidate generation and authoritative experiment specification | local deterministic computation; no device authority |
| Specimen Making | fabrication stage and Vision/Manipulation readiness | geometry-to-fabrication digital thread and completion conditions | geometry tools and selected printer provider bridge |
| Vision | observation stage plus verification sidecars | source/freshness/quality arbitration and verification signals | camera, ROS/UTM, LeRobot camera, verified rollout stop |
| Manipulation | governed transfer branch and post-place wait | task/policy/rollout supervision and transfer completion | LeRobot/robot/process/port/camera/Isaac boundaries |
| Lab Equipment | measurement stage after verified placement | profile/skill/protocol execution and evidence handoff | Windows PyAutoGUI and UTM/equipment bridges |
| Analysis | evaluation stage and Knowledge/BO handoff | parse, normalize, derive metrics/uncertainty/objective | bounded solver/computation bridge |
| Knowledge | durable context stage before BO | provenance, typed records, patterns, relation review, context | ledger/outbox/ontology/graph adapters |
| BO | next-candidate stage before Guardian/Design | LHS/GP/acquisition/constraints/recommendation | BoTorch and benchmark computation tools |
| Guardian | cross-level route authority | policy/risk/evidence/health/approval evaluation | read-only health/queue plus block/stop; hard interlocks remain in bridges |

See [Three-Level Control Model](../runtime/three_level_control_model.md) for
state ownership, failure propagation, and the manual Device Workspace boundary.

## Contract Matrix

| Agent | Required state | Primary output contracts | Checkpoint/evidence | Blocking condition |
|---|---|---|---|---|
| Orchestrator | Intent/session, current run/stage, accepted values | `mission_contract.v1`, `orchestration_plan.v1`, `handoff_packet.v1`, `decision_register.v1` | planning transcript, events, checkpoint/run metadata | missing required input, Guardian route, terminal state |
| Design | objective + constraint context | `experiment_spec`, design report/candidate/ledger, handoff packet | design artifacts, decisions, metrics | hard constraint failure or no valid candidate |
| Specimen Making | complete fabrication specification | STL/mesh/process/slice/fabrication result and specimen handoff | source/patched hashes, printer proof, digital thread | missing fields, QA failure, start gate, bed-clear/proof failure |
| Vision | available capture/zone/task and fresh context | `vision_report.v1`, `vision_signal.v1`, evidence refs | images, pose/event reports, timestamps/expiry | unavailable capture or stale/low-quality signal |
| Manipulation | specimen + fresh Vision + policy/profile + return-to-VLA gate | `manipulation_report.v1`, `robot_task_result.v1`, handoff packet | rollout session/log/dataset/checkpoint refs | preflight, stale Vision, policy/profile, Guardian/operator gate |
| Lab Equipment | exact profile/skill/protocol + bridge readiness | equipment result/report/handoff and proof | request log, screenshot/segment/protocol proof, completion audit | bridge/skill validation, preflight, Guardian, operator, unknown state |
| Analysis | identifiable raw equipment artifact | canonical curve, UTM metrics, CAE/FEM result, evaluation, BO handoff | input hash, parser/unit record, derived artifacts | missing/corrupt input, unresolved units, curve quality failure |
| Knowledge | accepted stage artifacts and provenance | `knowledge_context.v1`, `knowledge_report.v1`, `evolution_proposal.v1`, typed records | audit ledger, outbox, receipts, JSONL/graph records | provenance/ontology rejection or persistence failure |
| BO | valid analysis/prior evidence and bounded search space | ranked candidates, recommendation, BO artifacts, Design constraints | score table, reasoning patch, penalties, recommendation | no valid candidate, constraint/validator rejection |
| Guardian | current state, risk/device/failure/approval context | gate/decision/contract, incidents, corrective actions | Guardian events, approval and incident records | unsafe, uncertain, exhausted budget, missing approval or evidence |

## API Classification Matrix

| Agent | Owned API | Connected API | Operator/shared API | Exhaustive source |
|---|---|---|---|---|
| Orchestrator | planning message/bootstrap/session contract | runtime backend/model readiness | run lifecycle, run events/artifacts, approvals, SSE/recent events | `/openapi.json`, `/api/planning/*`, `/api/run*`, `/api/runtime/*` |
| Design | no dedicated direct execution endpoint | planning artifact/session context | `/api/graphs/*` authoring/validate/dry-run/run | `/openapi.json`, graph execution handler |
| Specimen Making | no direct agent endpoint | `/api/printer/*`, geometry/artifact tools | printer workspace and selected module management | `/openapi.json`, printer service/bridge implementations |
| Vision | specimen-pose status/snapshot/release | camera, active robot camera, UTM vision/runtime APIs | Vision/UTM workspaces and run retry | `/openapi.json`, Vision tools/bridge handlers |
| Manipulation | manipulation-agent config/test/run | `/api/lerobot/*` robotics services | LeRobot workspace configuration/training/simulation/mirror | `/openapi.json`, LeRobot bridge |
| Lab Equipment | no isolated agent endpoint | `/api/equipment/*`, `/api/bridges*` | equipment skill/profile/worker/UTM workspaces | `/openapi.json`, equipment bridge/tool registry |
| Analysis | no graph-stage direct endpoint | `/api/cae/config`, `/api/cae/run` | CAE workspace and run artifact APIs | `/openapi.json`, CAE bridge |
| Knowledge | context/report records via Knowledge service | `/api/knowledge/*` graph, ledger, reconciliation, Graphify | Knowledge workspace review/edit/sync/query | `/openapi.json`, Knowledge service/repositories |
| BO | `/api/bo/run` direct bounded workspace execution | `/api/bo/config`, `/api/bo/benchmark` | BO workspace and graph-run context | `/openapi.json`, BO agent/benchmark services |
| Guardian | `/api/guardian/status`, run-scoped status | device health and queue status tools | incidents and approval review/resolve APIs | `/openapi.json`, Guardian status/policy services |

## Connection and Effect Matrix

| Agent | LLM route | Internal services | External software/protocol | Device boundary | Highest possible effect |
|---|---|---|---|---|---|
| Orchestrator | `orchestrator_supervisor` | controller, run loop, checkpoint/event/planning services | model backend when selected | none | model/local_state |
| Design | `design_reasoning` | deterministic candidate/constraint logic | selected model backend for rationale | none | model/local_state |
| Specimen Making | `tool_formatting` | geometry, artifact, evaluation, printer manager | slicer/provider, Bambu MQTT/HTTP artifact path, Prusa bridge where selected | 3D printer | physical_possible |
| Vision | `vision_observation` | pose tracker, signal arbitration, evidence packaging | camera, LeRobot camera, ROS/UTM runtime | cameras; rollout stop process | physical_possible only for verified stop |
| Manipulation | `manipulation_plan` | policy/profile/session/SARM logic | LeRobot processes, serial/camera, Isaac services | robot/manipulator | physical_possible |
| Lab Equipment | `tool_formatting` | equipment skill runtime, profile/bridge registry | PyAutoGUI HTTP worker, desktop application, ROS/UTM runtime | UTM and registered equipment | physical_possible |
| Analysis | task-specific `analysis_reasoning`; module role empty | parsers, curve/metric logic | CAE/CalculiX through registered bridge | none directly | external_service/local process |
| Knowledge | `knowledge_synthesis`; reconciliation uses already-loaded model | Knowledge service, ontology, ledger, outbox, repositories | optional Neo4j/Graphify and selected model service | none | model/local_state/external_service |
| BO | `bo_policy` | candidate/acquisition/constraint logic | selected model backend for bounded advice | none | model/local_state |
| Guardian | `guardian_review` | policy gate, status aggregation, approval/event services | device/queue status connections and selected model | none directly | model plus downstream stop/block |

## Safety and Recovery Matrix

| Agent | Main gate | Approval | Dry run/preflight | Stop owner | Unknown-effect rule |
|---|---|---|---|---|---|
| Orchestrator | required-input and Guardian route | requests/resolves through shared approval service | graph/module/run validation where applicable | operator/Guardian/controller | do not translate uncertainty into automatic continuation |
| Design | hard constraints and schema | not normally physical approval | deterministic validation | Orchestrator/Guardian | reject/repair candidate; no external effect assumed |
| Specimen Making | manufacturability, start, bed-clear, proof | required by configured live printer policy | slice/prestart/start gate | printer service/operator/Guardian | query printer and proof state before republish |
| Vision | capture quality and signal freshness | not normally required for observation | camera/runtime probe | may request/perform verified rollout stop | stale or missing observation blocks downstream handoff |
| Manipulation | profile/policy/Vision/return-to-VLA | configured live confirmation | camera/profile/bridge preflight | Guardian/operator plus rollout stop | status and visual verification before restarting motion |
| Lab Equipment | exact skill/profile/bridge and Guardian | live equipment action scope | live preflight and skill validation | Guardian/operator/bridge stop | inspect desktop/instrument/proof before repeating segments |
| Analysis | input hash/parser/unit/curve quality | not_applicable | CAE probe and validated payload | bounded process cancellation | preserve raw input and partial outputs; no fabricated measurement |
| Knowledge | provenance/ontology/duplicate/receipt | operator review for relation edits/proposals | validate before ingest/apply | service/worker stop | retain ledger/outbox; never fabricate graph receipt |
| BO | search-space/constraint/validator gates | candidate still requires downstream governance | benchmark/dry-run where selected | Guardian/Orchestrator | reject candidate; no external physical effect |
| Guardian | safety policy, risk, budget, evidence | may require operator decision | reads device/queue health | Guardian/operator/controller | stop or review; uncertainty never becomes allow by default |

## Shared Data Flow

The shared runtime unit is `OrchestratorState`. Agent results are merged into
that state through allowlisted handlers; a module manifest does not make every
internal step an independently scheduled graph node. Checkpointed run state,
events, planning transcript, artifacts, durable knowledge, and external device
state have different lifetimes and must not be conflated.

## API Collection Notes

At baseline `0b7627b`, imported route groups include 56 routes across the broad
Orchestrator/shared prefixes, 87 under `/api/lerobot`, 57 under equipment and
bridge prefixes, 34 under `/api/knowledge`, 4 under `/api/bo`, and 3 under
`/api/cae`. Prefix totals overlap conceptually and are drift indicators only.
The agent References group these routes by functional ownership and effect.

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

Verified on 2026-08-09 by inspecting ten Python agents and manifests, the
primary graph, imported FastAPI routes, tool registries, bridges, Knowledge
services, and current runtime References at baseline `0b7627b`.

## Related Documents

- [Agent Reference Index](README.md)
- [System Architecture](../paper/02_system_architecture.md)
- [Platform Architecture](../paper/04_platform_architecture.md)
- [Interfaces Appendix](../paper/appendix_a_interfaces.md)
- [Current Code Snapshot](../runtime/current_code_snapshot.md)
