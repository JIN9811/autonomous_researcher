<!-- atr-doc
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
last_verified: 2026-09-13
verified_against: working-tree
related_docs:
  - docs/agents/agent_api_connection_matrix.md
  - docs/paper/02_system_architecture.md
  - docs/paper/appendix_a_interfaces.md
  - docs/runtime/current_code_snapshot.md
  - docs/runtime/three_level_control_model.md
  - docs/standards/documentation_standard.md
supersedes: []
-->

# Agent Reference Index

## Summary

This index is the canonical entry point for the ten executable Autonomous
Researcher (ATR) Framework agents used by AX4LAB. Each Reference explains what the agent
actually owns, what it does not own, its orchestration-plan handoffs, data contracts,
internal steps, APIs, tools and external connections, state and evidence,
runtime modes, safety gates, error recovery, operator surfaces, and current
verification boundary.

The individual agent References retain their declared verification baselines.
The shared [Loop Artifact Archiving](../runtime/loop_artifact_archiving.md)
Reference describes the newer run/loop/agent/invocation storage contract,
including failed/cancelled calls, file snapshots, and saved-loop GUI access.

## Status at a Glance

| At a glance | Details |
|---|---|
| Inventory | Ten executable agents on the existing registered graph/module path |
| Installed packages | Design, Specimen, Vision and Manipulation expose owned code, execution definitions and live reports; Manipulation and Vision share one installed LeRobot bridge, and Vision also uses Camera/Vision observation services |
| Orchestrator | Bounded `orchestrator_plan` decisions and dynamic Experimental Setup are documented against working-tree scope |
| Setup ownership | Only Orchestrator goal and BO parameter-space/acquisition adapters currently expose writable public fields; other owners remain read-only or unsupported |
| Execution authority | Agent procedures and registered tools/bridges retain execution authority; numerical values are tool-computed |
| Figures | Ten Sunburst role overviews plus editable agent figures; Orchestrator now includes Flow, Execution, and Connections views |
| Verification | A corrected aggregate passed 78 bounded cases per provider; [verification evidence](../runtime/evidence/2026-09-12-orchestrator-dynamic-setup-verification.md) retains capture/postprocessor distinction and no hardware claim is added |

## Reading the References

In IDE and document figures, **LLM** marks the High decision; **LLM call** marks
the process that sends context to it and consumes its response. See the shared
[node-label contract](../runtime/three_level_control_model.md#llm-node-labels).

The [Manipulation Reference](manipulation_agent.md#installed-package-and-executable-structure)
covers its two composite execution operations, source-bound control-area figure,
eight owner frontend cards and shared LeRobot dependency. An Agent Package is a
composition contract; the Device Bridges view shows the actual bridge components.

The [Vision Reference](vision_agent.md#installed-package-and-executable-structure)
documents the installed package, composite observation operation and shared
five-area IDE/document projection. Its new validation uses virtual equipment and
registered model calls; it does not add physical validation claims.

Start with the role overview and available status summary, then read the
responsibility map, handoffs, decision/tools, API connections, and evidence.
The [API and Connection Matrix](agent_api_connection_matrix.md) distinguishes
LLM choices, executable tools, connected services, and operator surfaces.

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

The [Design Reference](design_agent.md) establishes the role/workflow reading
order used by the restructured References. High, Middle, Low, Guardian/Safety,
and Knowledge/Evidence describe responsibility areas, not five sequential
model calls. Orchestrator and Guardian retain their control-plane layouts;
each owning Reference defines where its LLM decisions actually occur.

Each Reference opens with a representative role overview. These generated
overviews use GPT Image 2.5 Sunburst and supplement the unchanged editable
Flow, Execution, and applicable Connections figures below.
[Current generation prompts](../assets/presentation/sunburst-paper-figures.jsonl)
and [figure provenance/style](../assets/presentation/README.md) record the shared
paper-figure brief. Conceptual pictures do not replace execution evidence.

Figures are `inspection`-backed explanatory projections. The executable code,
primary graph, module manifests, imported FastAPI routes, and bridge/service
implementations remain authoritative.

## Canonical Inventory

| Agent reference | Main responsibility | Implementation |
|---|---|---|
| [Orchestrator](orchestrator_agent.md) | Bounded decisions, canonical Setup proposals, registered mission and agent handoffs | [Source](../../agents/orchestrator_agent.py) · [Module](../../graphs/modules/orchestrator/module.yaml) |
| [Design](design_agent.md) | Candidate suitability | [Source](../../agents/design/agent.py) · [Code module](../../agents/design/module.py) · [Graph module](../../graphs/modules/design/module.yaml) |
| [Specimen](specimen_agent.md) | Fabrication suitability and tools | [Owner](../../agents/specimen/agent.py) · [Code module](../../agents/specimen/module.py) · [Execution graph](../../graphs/modules/specimen/module.yaml) · [Agent Package](../../packages/agents/specimen/package.yaml) |
| [Vision](vision_agent.md) | Visual evidence | [Source](../../agents/vision_agent.py) · [Module](../../graphs/modules/vision/module.yaml) |
| [Manipulation](manipulation_agent.md) | Robot skills and completion | [Source](../../agents/manipulation/agent.py) · [Module](../../graphs/modules/manipulation/module.yaml) · [Control areas](assets/figures/manipulation_control_areas.svg) |
| [Equipment](equipment_agent.md) | Stacked Flow selection, terminal review and bounded recovery | [Owner](../../agents/equipment/agent.py) · [Code module](../../agents/equipment/module.py) · [Execution graph](../../graphs/modules/equipment/module.yaml) · [Agent Package](../../packages/agents/equipment/package.yaml) · [Control areas](assets/figures/equipment_control_areas.svg) |
| [Analysis](analysis_agent.md) | Measured objectives and independent background FEM | [Source](../../agents/analysis_agent.py) · [Module](../../graphs/modules/analysis/module.yaml) |
| [Knowledge](knowledge_agent.md) | Ontology-guided Markdown, page-wise source curation and scoped retrieval | [Source](../../agents/knowledge_agent.py) · [Module](../../graphs/modules/knowledge/module.yaml) |
| [Bayesian Optimization](bo_agent.md) | LLM strategy/review with continuous LHS/BoTorch proposals | [Source](../../agents/bo_agent.py) · [Module](../../graphs/modules/bo/module.yaml) |
| [Guardian](guardian_agent.md) | Policy gates, advisory review and continuation decisions | [Source](../../agents/guardian_agent.py) · [Module](../../graphs/modules/guardian/module.yaml) |

The [API and Connection Matrix](agent_api_connection_matrix.md) compares all ten
agents without repeating full implementation prose.

<details>
<summary>Detailed figure index</summary>

| Agent | Diagrams |
|---|---|
| Orchestrator | [Flow](assets/figures/orchestrator_01_closed_loop_handoffs.svg) · [Execution](assets/figures/orchestrator_02_execution_effect_boundary.svg) · [Connections](assets/figures/orchestrator_03_api_connection_architecture.svg) |
| Design | [Flow](assets/figures/design_01_closed_loop_handoffs.svg) · [Execution](assets/figures/design_02_execution_effect_boundary.svg) · [Connections](assets/figures/design_03_api_connection_architecture.svg) |
| Specimen Making | [Control areas](assets/figures/specimen_control_areas.svg) · [Flow](assets/figures/specimen_01_closed_loop_handoffs.svg) · [Execution](assets/figures/specimen_02_execution_effect_boundary.svg) · [Connections](assets/figures/specimen_03_api_connection_architecture.svg) |
| Vision | [Flow](assets/figures/vision_01_closed_loop_handoffs.svg) · [Execution](assets/figures/vision_02_execution_effect_boundary.svg) · [Connections](assets/figures/vision_03_api_connection_architecture.svg) |
| Manipulation | [Flow](assets/figures/manipulation_01_closed_loop_handoffs.svg) · [Execution](assets/figures/manipulation_02_execution_effect_boundary.svg) · [Connections](assets/figures/manipulation_03_api_connection_architecture.svg) |
| Lab Equipment | [Control areas](assets/figures/equipment_control_areas.svg) · [Flow](assets/figures/equipment_01_closed_loop_handoffs.svg) · [Execution](assets/figures/equipment_02_execution_effect_boundary.svg) · [Connections](assets/figures/equipment_03_api_connection_architecture.svg) |
| Analysis | [Flow](assets/figures/analysis_01_closed_loop_handoffs.svg) · [Execution](assets/figures/analysis_02_execution_effect_boundary.svg) · [Connections](assets/figures/analysis_03_api_connection_architecture.svg) |
| Knowledge | [Flow](assets/figures/knowledge_01_closed_loop_handoffs.svg) · [Execution](assets/figures/knowledge_02_execution_effect_boundary.svg) · [Connections](assets/figures/knowledge_03_api_connection_architecture.svg) |
| BO | [Flow](assets/figures/bo_01_closed_loop_handoffs.svg) · [Execution](assets/figures/bo_02_execution_effect_boundary.svg) · [API](assets/figures/bo_03_api_connection_architecture.svg) |
| Guardian | [Flow](assets/figures/guardian_01_closed_loop_handoffs.svg) · [Execution](assets/figures/guardian_02_execution_effect_boundary.svg) |

</details>

## Three-Level Control Classification

This classification applies only to the **automatic experiment loop**. Device
Workspaces are manual setup, commissioning, training, and direct-control
surfaces outside that hierarchy, even when they reuse the same services and
bridges. The complete contract and diagram are in the
[Three-Level Control Model](../runtime/three_level_control_model.md).

| Agent | High-Level Control relationship | Middle-Level Control ownership | Low-Level Control boundary |
|---|---|---|---|
| Orchestrator | LLM intent, availability and admitted action review | Existing runtime supervision, contract/plan builders and tool dispatch | No direct device execution |
| Design | LLM candidate suitability and bounded tool choice | Candidate generation, inspection, validation and handoff | No direct device execution |
| Specimen Making | LLM fabrication suitability and bounded tool choice | Geometry, manufacturing checks, existing printer API calls and handoff | Selected Printer Fleet provider and printer |
| Vision | LLM observation choice and same-frame evidence review | Task resolution, detectors, interlocks, capture/status/stop API dispatch | Selected camera and LeRobot device paths |
| Manipulation | LLM saved-skill suitability and post-Vision result review | Profile binding, API dispatch, preflight and completion supervision | LeRobot robot policy/replay execution and device lifecycle |
| Lab Equipment | LLM stacked-Flow selection and terminal evidence/recovery review | Existing exact Flow/Skill supervision, APIs, CSV checks and handoff | Selected desktop/instrument worker and device driver |
| Analysis | LLM data, simulation and model-review choices | Parsing, units, objectives, solver, postprocessing and asynchronous FEM scheduling | No direct device execution |
| Knowledge | LLM scoped retrieval and evidence curation | Provenance, ontology, Markdown/JSONL persistence and context assembly | No direct device execution |
| Bayesian Optimization | LLM strategy/tool choice and numerical result review | LHS/BoTorch, constraints, numeric recommendation and handoff | No direct device execution |
| Guardian | Existing LLM policy-evidence review | Deterministic safety/risk checks, health APIs and incident/route results | Hardware interlocks and effective stops remain in device bridges |

The control direction is `High-Level -> Middle-Level -> Low-Level`; telemetry
and evidence return upward. Recovery stays with the owner of the failed
invariant: device reconnection is Low-Level, rebuilding an agent output is
Middle-Level, and choosing retry/review/another cycle/terminal state is
High-Level only where an existing LLM decision participates. Deterministic
routing remains Middle; classification never inserts new model calls.

## Orchestration Plan Reading Map

The current experimental cycle is one configured plan, not the framework's
only possible topology. Its main reading path is:

```text
operator intent
  -> Orchestrator mission/plan/handoff
  -> Design experiment specification
  -> Specimen manufacturing digital thread
  -> Vision observation / Manipulation transfer and verification
  -> Lab Equipment stacked workflow and terminal review
  -> Manipulation post-test clearance -> fresh Vision verification
  -> Analysis measured curves and objective
  -> Knowledge provenance, patterns, and BO context
  -> BO next-candidate proposal
  -> Guardian continue / review / stop / error
  -> Orchestrator route translation
  -> next Design cycle or terminal state
```

Optional background work has a separate lifetime:

```text
Analysis frozen evidence -> FEM preparation / solve / review -> model evidence
Source inbox -> page-wise extraction / LLM curation -> Markdown -> scoped retrieval
Terminal agent archives -> deterministic evidence preservation
```

The measured handoff does not wait for optional FEM; source intake does not
insert another equipment action into the plan. Simulation-only paths still
await the solver that supplies their observations.

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
| High-Level Control | Each agent's bounded LLM reasoning and decisions |
| Middle-Level Control | Existing internal processes, APIs, tool dispatch and software computation |
| Low-Level Control | Actual device bridge/driver execution; not local computation or storage |
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
| `specimen_design_existing_runtime_guideline.txt` | [Design](design_agent.md), [Specimen](specimen_agent.md) | Runtime-consumed legacy prompt input, not a reader-facing current contract; retained in place to avoid changing execution |
| `vision_pickup_observation_runtime_guideline.txt` | [Vision](vision_agent.md) | Pickup observation detail |

## Verification Method

- Agent and step inventory: `graphs/modules/*/module.yaml`
- Executable classes: `agents/*_agent.py`
- Graph position and transitions: `graphs/configs/atr_closed_loop.yaml`
- API paths and methods: route declarations and registration/retirement hooks
  in `app/main.py`, Analysis route modules, and Knowledge API installers;
  deployed `/openapi.json` is the instance-specific schema
- Tools and connections: module manifests, `AgentContext`, registered tool and
  bridge implementations
- Separately scoped historical counts and selected responses:
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

Updated on 2026-09-11 against `5a190e8`: agent implementations and local
decision modules, ten manifests, graph handoffs, Analysis FEM/field routes,
Knowledge Markdown/source route installers, and owning References were inspected.
Documentation checks validate links and publication structure; no device,
model-inference, or new physical-cycle test was performed for this update.

## Related Documents

- [AX4LAB Wiki and Memory](../knowledge/wiki_memory.md): shared agent reference
  context, private-memory lifecycle and Workspace delivery evidence.
- [Knowledge Publication Boundary](../knowledge/publication.md): staged-file
  checks and the separation of public documentation from private context.

- [Agent API and Connection Matrix](agent_api_connection_matrix.md)
- [System Architecture](../paper/02_system_architecture.md)
- [Platform Architecture](../paper/04_platform_architecture.md)
- [Interfaces Appendix](../paper/appendix_a_interfaces.md)
- [Current Code Snapshot](../runtime/current_code_snapshot.md)
