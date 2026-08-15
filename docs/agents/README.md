---
doc_type: index
subtype: index
status: active
authority: navigation
audience:
  - researcher
  - reviewer
  - operator
  - developer
  - maintainer
scope:
  - agents
  - runtime_contracts
  - api_connections
summary: Canonical entry point for ATR agent roles, contracts, APIs, connections, evidence, and safety boundaries.
related_docs:
  - docs/agents/agent_api_connection_matrix.md
  - docs/paper/02_system_architecture.md
  - docs/paper/appendix_a_interfaces.md
  - docs/runtime/current_code_snapshot.md
  - docs/runtime/three_level_control_model.md
  - docs/standards/documentation_standard.md
supersedes: []
---

# Agent Reference Index

## Summary

This index is the canonical entry point for the ten executable Autonomous
Researcher Framework (ATR) agents. Each Reference explains what the agent
actually owns, what it does not own, its closed-loop handoffs, data contracts,
internal steps, APIs, tools and external connections, state and evidence,
runtime modes, safety gates, error recovery, operator surfaces, and current
verification boundary.

The implementation baseline is `0b7627b`. Later commits through the agent
documentation work change documents and document validators, not the agent
runtime described here.

## 한국어 안내

에이전트별 상세 문서는 영문이 기준입니다. 아래 표에서 원하는 에이전트를
선택하고 `Actual Role`, `API Surface`, `Tools and Connections`, `Safety,
Approval, and Effect Boundary`, `Errors and Recovery` 순서로 읽으면 실제 역할,
API, 외부 연결, 물리 효과와 복구 경계를 빠르게 확인할 수 있습니다.

## Scope

Included:

- ten Python agent implementations and module manifests;
- the primary graph and handoff order;
- owned, connected, operator, and shared APIs;
- registered tools, services, bridges, providers, devices, and model routes;
- state, events, artifacts, storage, modes, safety, and recovery contracts.

Excluded:

- a duplicate of the complete OpenAPI schema;
- hardware-specific operating procedures already maintained elsewhere;
- unsupported scientific, safety-effectiveness, or live-reliability claims;
- legacy guideline files as current authority.

## Visual Contract

Every Reference includes `Flow` and `Execution` figures. Specimen, Vision,
Manipulation, Equipment, Analysis, and Knowledge also include a `Connections`
figure because their bridge, external-service, device, or persistence boundary
needs a separate view. Each checked-in SVG has an editable same-stem Graphviz
source under `assets/figures/`.

Figures are `inspection`-backed explanatory projections. The executable code,
primary graph, module manifests, imported FastAPI routes, and bridge/service
implementations remain authoritative.

## Canonical Inventory

| Plane/order | Agent | Python implementation | Module manifest | Canonical Reference | Figures |
|---|---|---|---|---|---|
| Control plane | Orchestrator | `agents/orchestrator_agent.py` | `graphs/modules/orchestrator/module.yaml` | [Orchestrator](orchestrator_agent.md) | [Flow](assets/figures/orchestrator_01_closed_loop_handoffs.svg) · [Execution](assets/figures/orchestrator_02_execution_effect_boundary.svg) |
| 1 | Design | `agents/design_agent.py` | `graphs/modules/design/module.yaml` | [Design](design_agent.md) | [Flow](assets/figures/design_01_closed_loop_handoffs.svg) · [Execution](assets/figures/design_02_execution_effect_boundary.svg) |
| 2 | Specimen Making | `agents/specimen_agent.py` | `graphs/modules/specimen/module.yaml` | [Specimen Making](specimen_agent.md) | [Flow](assets/figures/specimen_01_closed_loop_handoffs.svg) · [Execution](assets/figures/specimen_02_execution_effect_boundary.svg) · [Connections](assets/figures/specimen_03_api_connection_architecture.svg) |
| 3 + verification sidecars | Vision | `agents/vision_agent.py` | `graphs/modules/vision/module.yaml` | [Vision](vision_agent.md) | [Flow](assets/figures/vision_01_closed_loop_handoffs.svg) · [Execution](assets/figures/vision_02_execution_effect_boundary.svg) · [Connections](assets/figures/vision_03_api_connection_architecture.svg) |
| Physical transfer branch | Manipulation | `agents/manipulation_agent.py` | `graphs/modules/manipulation/module.yaml` | [Manipulation](manipulation_agent.md) | [Flow](assets/figures/manipulation_01_closed_loop_handoffs.svg) · [Execution](assets/figures/manipulation_02_execution_effect_boundary.svg) · [Connections](assets/figures/manipulation_03_api_connection_architecture.svg) |
| 4 | Lab Equipment | `agents/equipment_agent.py` | `graphs/modules/equipment/module.yaml` | [Lab Equipment](equipment_agent.md) | [Flow](assets/figures/equipment_01_closed_loop_handoffs.svg) · [Execution](assets/figures/equipment_02_execution_effect_boundary.svg) · [Connections](assets/figures/equipment_03_api_connection_architecture.svg) |
| 5 | Analysis | `agents/analysis_agent.py` | `graphs/modules/analysis/module.yaml` | [Analysis](analysis_agent.md) | [Flow](assets/figures/analysis_01_closed_loop_handoffs.svg) · [Execution](assets/figures/analysis_02_execution_effect_boundary.svg) · [Connections](assets/figures/analysis_03_api_connection_architecture.svg) |
| 6 | Knowledge | `agents/knowledge_agent.py` | `graphs/modules/knowledge/module.yaml` | [Knowledge](knowledge_agent.md) | [Flow](assets/figures/knowledge_01_closed_loop_handoffs.svg) · [Execution](assets/figures/knowledge_02_execution_effect_boundary.svg) · [Connections](assets/figures/knowledge_03_api_connection_architecture.svg) |
| 7 | BO | `agents/bo_agent.py` | `graphs/modules/bo/module.yaml` | [Bayesian Optimization](bo_agent.md) | [Flow](assets/figures/bo_01_closed_loop_handoffs.svg) · [Execution](assets/figures/bo_02_execution_effect_boundary.svg) |
| Safety/control plane | Guardian | `agents/guardian_agent.py` | `graphs/modules/guardian/module.yaml` | [Guardian](guardian_agent.md) | [Flow](assets/figures/guardian_01_closed_loop_handoffs.svg) · [Execution](assets/figures/guardian_02_execution_effect_boundary.svg) |

The [API and Connection Matrix](agent_api_connection_matrix.md) compares all ten
agents without repeating full implementation prose.

## Three-Level Control Classification

This classification applies only to the **automatic experiment loop**. Device
Workspaces are manual setup, commissioning, training, and direct-control
surfaces outside that hierarchy, even when they reuse the same services and
bridges. The complete contract and diagram are in the
[Three-Level Control Model](../runtime/three_level_control_model.md).

| Agent | High-Level Control relationship | Middle-Level Control ownership | Low-Level Control boundary |
|---|---|---|---|
| Orchestrator | Owns mission, dispatch, handoff, cycle, retry/review, and route translation | Normalizes intent and compiles mission, context, follow-up, decision, and reflection contracts | No direct device tools; delegates bounded work to graph-selected agents |
| Design | Receives the governed Design stage and emits the Specimen handoff | Normalizes objectives, builds/validates candidate space, scores, selects, and emits the experiment specification | Deterministic local computation and bounded model advice; no device authority |
| Specimen Making | Converts a selected design into a fabrication result requiring Vision verification | Owns geometry, QA, slicing plan, start/monitor/ejection evidence, and fabrication handoff | Geometry/artifact tools plus the selected printer fleet/provider bridge |
| Vision | Supplies stage observations and verification sidecars used by High-Level routing | Owns source selection, freshness/quality, active-camera and UTM verification signals | Camera, LeRobot camera, ROS/UTM runtime, and verified rollout-stop tools |
| Manipulation | Owns the governed physical-transfer branch and waits for post-place Vision evidence | Owns task/policy choice, preflight, rollout supervision, motion-state and completion contracts | LeRobot rollout/process, robot, serial/camera lease, and optional Isaac sidecars |
| Lab Equipment | Runs after verified placement and hands measurement proof to Analysis | Owns profile/skill/protocol selection, preflight, execution proof, export, and handoff | Windows PyAutoGUI and UTM/equipment bridges |
| Analysis | Converts identified measurement evidence into an accepted evaluation handoff | Owns parsing, units, curves, metrics, uncertainty, CAE comparison, and objective evaluation | Bounded CAE/CalculiX or computation bridge; no direct physical actuator |
| Knowledge | Supplies durable evidence and bounded context for BO and later cycles | Owns provenance/schema validation, typed records, patterns, relation review, and context assembly | Ledger, outbox, ontology, and graph repository adapters; no physical actuator |
| BO | Proposes the next governed candidate after accepted Analysis/Knowledge evidence | Owns prior filtering, LHS/GP/acquisition, constraints, recommendation, and Design handoff | BoTorch/benchmark computation tools; proposal only |
| Guardian | Cross-level authority for continue, review, stop, or error | Owns risk/evidence/health/approval evaluation and corrective-action records | Read-only health/queue tools and stop/block authority; bridge hard interlocks remain authoritative |

The control direction is `High-Level -> Middle-Level -> Low-Level`; telemetry
and evidence return upward. Recovery stays with the owner of the failed
invariant: device reconnection is Low-Level, rebuilding an agent output is
Middle-Level, and choosing retry/review/another cycle/terminal state is
High-Level.

## Closed-Loop Reading Map

```text
operator intent
  -> Orchestrator mission/plan/handoff
  -> Design experiment specification
  -> Specimen manufacturing digital thread
  -> Vision observation / Manipulation transfer and verification
  -> Lab Equipment protocol execution
  -> Analysis metrics and objective
  -> Knowledge provenance, patterns, and BO context
  -> BO next-candidate proposal
  -> Guardian continue / review / stop / error
  -> Orchestrator route translation
  -> next Design cycle or terminal state
```

This is a reading projection, not a replacement for
`graphs/configs/atr_closed_loop.yaml`. The executable graph also contains
runtime dispatch, supervisor overlays, evidence flows, conditional branches,
sidecars, and explicit `complete` and `error` nodes.

## Reader Paths

| Reader | Start here | Then read |
|---|---|---|
| Paper reviewer | [Matrix](agent_api_connection_matrix.md) | System, platform, and interface paper chapters |
| Operator | Relevant physical agent | Safety/effect, errors/recovery, GUI, then hardware Guide |
| Agent developer | Relevant agent Reference | Python class, module manifest, adjacent handoff owner |
| API integrator | Matrix API view | Relevant Reference API and connection tables, then OpenAPI |
| Maintainer | Matrix + all changed References | source paths, verification, limitations, legacy notes |
| Safety reviewer | [Guardian](guardian_agent.md) and physical agents | approval, stop, uncertain-effect, evidence sections |

## Terminology

| Term | Meaning in these References |
|---|---|
| Agent | Python component responsible for a bounded reasoning, transformation, control, or review role |
| Stage | Runtime state value dispatched to a graph node; not every agent is only a linear stage |
| Module | Versioned manifest binding ID, handler, tools, safety metadata, and descriptive internal graph |
| Handler | Allowlisted runtime function that invokes the Python agent implementation |
| Tool | Registered bounded callable available through `AgentContext`; not unrestricted shell authority |
| Bridge | Adapter between ATR contracts and external software, desktop, provider, robot, or device behavior |
| Service | In-process or external subsystem owning state, validation, persistence, or a specialized API |
| `owned` API | Directly exposes an agent's execution, configuration, status, or result contract |
| `connected` API | Exposes a service or bridge used by the agent |
| `operator` API | Supports configuration, review, evidence inspection, or manual invocation |
| `shared` API | Serves multiple agents, such as run, event, approval, graph, module, or runtime APIs |
| `physical_possible` | May produce a physical or desktop effect after mode, policy, approval, and bridge gates |
| High-Level Control | Experiment mission, active agent, stage, cycle, retry/review, and terminal-route control |
| Middle-Level Control | Bounded internal procedure owned by the active agent |
| Low-Level Control | Registered tool, service, bridge, process, solver, or physical-device execution |
| Device Workspace | Explicit manual control surface outside automatic-loop progression |

## API and Effect Rules

An API path is not assigned to an agent only because its URL contains an agent
or workspace name. Ownership follows the route handler and service boundary.
For example:

- `/api/approvals/*` is shared by Orchestrator and Guardian workflows;
- `/api/lerobot/camera/test` connects both Vision and Manipulation;
- `/api/graphs/*` configures the runtime platform and is not a Design execution
  API;
- `/api/printer/*` is a connected printer service surface for Specimen Making;
- `/api/knowledge/*` contains both Knowledge Agent result surfaces and Knowledge
  service/operator review surfaces.

Effect labels are conservative. A route that can eventually cause physical or
desktop action is `physical_possible` even when the common example uses Test
mode.

## Authority and Conflict Resolution

Use this order for current behavior:

```text
executable code and checked-in configuration
-> active Documentation/Paper Standard
-> these active agent References and the matrix
-> active runtime/hardware Guides
-> approved Designs
-> Plans and time-bounded Evidence
-> legacy agent guidelines
```

The References describe current contracts; they do not prove correctness or
scientific value. If a Reference conflicts with code, code is current and the
document must be corrected.

## Legacy and Domain-Specific Detail

The files below remain useful background but are not the canonical current
agent contract:

| Existing file | Canonical owner | Use |
|---|---|---|
| `analysis_utm_runtime_guideline.txt` | [Analysis](analysis_agent.md) | UTM analysis detail |
| `cae_analysis_runtime_guideline.txt` | [Analysis](analysis_agent.md) | CAE detail |
| `bo_agent_runtime_guideline.txt` | [BO](bo_agent.md) | BO algorithm/runtime detail |
| `knowledge_agent_self_evolution_runtime_guideline.md` | [Knowledge](knowledge_agent.md) | Knowledge/self-evolution detail |
| `manipulation_pi05_transfer_runtime_guideline.txt` | [Manipulation](manipulation_agent.md) | Pi0.5 transfer detail |
| `specimen_design_existing_runtime_guideline.txt` | [Design](design_agent.md), [Specimen](specimen_agent.md) | Older combined design/specimen context |
| `vision_pickup_observation_runtime_guideline.txt` | [Vision](vision_agent.md) | Pickup observation detail |

## Verification Method

- Agent and step inventory: `graphs/modules/*/module.yaml`
- Executable classes: `agents/*_agent.py`
- Graph position and transitions: `graphs/configs/atr_closed_loop.yaml`
- API paths and methods: imported FastAPI `APIRoute` objects from `app.main.app`
- Tools and connections: module manifests, `AgentContext`, registered tool and
  bridge implementations
- Current counts and selected responses:
  [Current Code Snapshot](../runtime/current_code_snapshot.md)

Route, step, and tool counts are drift indicators, not performance metrics.

## Update Checklist

When an agent contract changes:

1. update its Python implementation and manifest as required;
2. update the owning Reference;
3. update the matrix if handoff, API, connection, effect, or safety boundaries
   change;
4. update adjacent References only for their handoff summary;
5. run documentation and paper publication validators;
6. do not promote a new route or tool to live evidence without a qualifying
   evidence record.

## Limitations and Known Gaps

These References do not validate model quality, scientific quality, operator
usability, safety effectiveness, or every optional provider/device combination.
Large controller and route files contain some cross-cutting behavior; the
documents identify ownership boundaries without refactoring the implementation.

## Index Verification

Verified on 2026-08-09 against runtime baseline `0b7627b`, ten Python agent
classes, ten module manifests, the primary graph, and imported FastAPI routes.

## Related Documents

- [Agent API and Connection Matrix](agent_api_connection_matrix.md)
- [System Architecture](../paper/02_system_architecture.md)
- [Platform Architecture](../paper/04_platform_architecture.md)
- [Interfaces Appendix](../paper/appendix_a_interfaces.md)
- [Current Code Snapshot](../runtime/current_code_snapshot.md)
