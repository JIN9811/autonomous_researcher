<!-- atr-doc
doc_type: reference
subtype: system
status: review
authority: descriptive
audience:
  - researcher
  - reviewer
  - developer
scope:
  - paper
  - system_architecture
  - runtime_graph
summary: Describes the current ATR system layers, executable graph, stage contracts, and control boundaries.
source_of_truth:
  - graphs/configs/atr_closed_loop.yaml
  - orchestrator/graph.py
  - orchestrator/langgraph_runtime.py
  - orchestrator/supervisor.py
  - app/controller.py
  - policies/guardian_gate.py
  - agents/knowledge_agent.py
  - knowledge/markdown_runtime.py
  - knowledge/source_api.py
last_verified: 2026-09-12
verified_against: 5542ef2
paper_section: system_architecture
research_questions:
  - RQ1
  - RQ2
  - RQ3
claim_ids:
  - C-SYS-ARCH-01
  - C-TRACE-DOC-01
  - C-SAFE-LIVE-01
related_docs:
  - docs/paper/README.md
  - docs/runtime/current_code_snapshot.md
  - docs/runtime/langgraph_runtime.md
  - docs/paper/03_closed_loop_method.md
supersedes: []
-->

# System Architecture

| At a glance | Details |
|---|---|
| Topic | Control areas, executable graph and evidence ownership |
| Evidence boundary | Static code/configuration inspection; not deployment certification |
| Recorded basis | 2026-09-12 · [Scope and verification](#verification) |

## Summary

ATR separates control, agent work, physical integration, evidence, and
operator interaction into explicit layers. At code baseline `5542ef2`, the
checked-in graph contains 19 nodes, 74 declared edges, and 12 stage-dispatch
entries. The reader-facing runtime map displays 50 connections after internal
dispatch/step-return edges are filtered. These are architecture observations, not stability or
performance guarantees.

## Scope

This chapter covers the primary closed-loop graph, runtime state movement,
agents and sidecars, Guardian and operator boundaries, and evidence planes. It
does not certify every optional backend or physical device.

## Source of Truth

- `graphs/configs/atr_closed_loop.yaml` declares nodes, edges, dispatch,
  transitions, terminal stages, and safety metadata.
- `orchestrator/langgraph_runtime.py` compiles and executes the declared graph.
- `orchestrator/supervisor.py` coordinates handoffs and runtime decisions.
- `app/controller.py` owns run lifecycle and operator-facing orchestration.
- `policies/guardian_gate.py` implements Guardian policy evaluation.

## Layered Architecture

### Structured intelligence over existing hardware

The architecture places integration complexity in software rather than in a
purpose-built laboratory. High-level decisions, middle-level procedures, and
low-level execution are supported by Guardian/Safety and Knowledge/Evidence.
The [control model](../runtime/three_level_control_model.md) and individual
agent responsibility maps define these boundaries in detail.

| Mechanism | Existing-laboratory role | Current implementation reference |
|---|---|---|
| VLA-enabled manipulation | Connect physical stages using a robot arm rather than making dedicated transfer fixtures the default | [Manipulation](../agents/manipulation_agent.md) |
| Robot integration boundary | Permit supported robot substitutions with calibration and policy validation | [LeRobot bridge](../device_bridges/lerobot_bridge.md) |
| API integration | Reuse programmatically controllable equipment | [Printer fleet](../device_bridges/printer_fleet_bridge.md) |
| Desktop workflow integration | Reuse equipment operated through PC software | [Lab Equipment](../agents/equipment_agent.md) |

These mechanisms explain the hardware-reuse strategy; measured cost savings
and cross-robot transfer performance are separate evaluation questions.

![Layered system architecture](assets/figures/02_layered_architecture.svg)

**Figure 2 — Layered architecture.** The primary system path runs from
operator/research intent through orchestration, typed agent stages, device and
model adapters, and durable evidence. Dashed platform paths indicate extension
surfaces. The diagram is derived from code and configuration inspection; it is
not a deployment reliability result.

The layers have different authorities:

| Layer | Responsibility | Failure boundary | Evidence surface |
|---|---|---|---|
| Research and operator | Objective, approval, intervention, stop | Missing approval or explicit stop | Approval/event records |
| Orchestration | Stage dispatch, transition, checkpoint, resume | Invalid state, handler failure, terminal error | Runtime state and checkpoint artifacts |
| Agent and sidecar | Domain reasoning and typed outputs | Schema/policy rejection, bounded agent error | Stage artifacts and handoff packets |
| Guardian | Route, allow, deny, or require review | Unsafe/uncertain decision | Guardian decision record |
| Device/model adapter | External execution behind stable contracts | Unavailable capability, dry-run failure, bridge error | Request, response, proof artifact |
| Evidence and knowledge | Ontology-guided Markdown, JSONL, local audit, reports and provenance | Missing evidence, scope/validation rejection, storage failure | Source citations, durable records and receipts |
| Platform workspace | Inspect, configure, review, and operate | Authorization/UI/API error | API response and browser evidence |

## Executable Graph

The graph has runtime nodes, domain-agent nodes, sidecars, and terminal nodes.
Dispatch maps the current stage to one of 12 entries: `idle`, `design`,
`specimen`, `vision`, `manipulation`, `equipment`, `analysis`, `knowledge`,
`bo`, `guardian`, `complete`, and `error`.

Declared edges include logical transitions, supervisor overlays, evidence
flows, and runtime-sidecar relations. Counting all 74 edges therefore describes
the configuration surface; it does not imply 74 sequential physical actions.

## Stage Contracts

| Stage or component | Primary input | Primary output | Gate or recovery boundary |
|---|---|---|---|
| Dispatch | Current orchestrator state | Selected executable node | Unknown stage routes to error handling |
| Design | Objective and prior evidence | Design artifact and next-stage handoff | Schema and policy checks |
| Specimen | Approved design/specimen request | Manufacturing or preparation artifact | Equipment capability and dry-run boundary |
| Vision | Image/measurement context | Observation and verification artifact | Quality/availability checks; may redirect |
| Manipulation | Placement or motion intent | Manipulation result and proof | Device bridge and physical-action gate |
| Equipment | Typed instrument action | Measurement/execution artifact | Guardian, operator approval, dry run, timeout |
| Analysis | Validated observations | Analysis artifact | Input/schema validity and bounded failure |
| Knowledge | Accepted cycle artifacts and scoped source evidence | Context, report, Markdown notes and typed memory | Ontology, provenance, scope and local audit validation |
| Bayesian optimization | Prior trials and constraints | Next candidate | Candidate remains a proposal until governed handoff |
| Guardian | Risk/evidence/context packet | Continue, stop, review, or error decision | Policy and operator boundary |
| Complete | Terminal success state | Final run state | No implicit next action |
| Error | Terminal or recoverable failure state | Diagnosable failure state | Explicit retry/resume policy |

The table states responsibilities rather than a universal payload schema. The
interface appendix records concrete contracts and source paths.

## State, Checkpoints, and Resume

Runtime state carries run/cycle identity, current stage, domain artifacts,
decisions, error context, and transition information. Checkpointing makes a
resumed run an explicit continuation rather than an unrecorded restart.
Resume safety depends on stage semantics: a software-only analysis may be
replayed, whereas a physical action requires evidence that it did not already
complete and may require operator review.

## Safety and Control Planes

Guardian is a control-plane component, not a scientific-analysis stage.
Operator approvals are first-class transitions where configured. Dry-run and
capability checks reduce accidental invocation risk but do not replace
laboratory-specific hazard assessment.

The graph exposes `complete` and `error` terminal states and Guardian routes
for continue, stop, and error. A system claim about safe behavior must examine
whether these paths activate under representative hazards; their presence in
configuration is only architecture evidence.

## Evidence Plane

The evidence plane receives validated artifacts from execution and analysis,
persists knowledge records, and returns context to later design decisions.
The Knowledge Agent uses ontology-guided Markdown, typed JSONL records and a
local audit ledger. Its LLM inspects evidence, selects scoped retrieval and
publishes cited context without rewriting measured values. Source Library
separately preserves submitted originals and curates page-wise input into one
published note per source. Active graph storage and reconciliation are retired;
the ontology vocabulary remains in use.

See the [Knowledge Agent](../agents/knowledge_agent.md) for the decision tools,
storage contracts and source-intake boundary. Provenance is part of execution,
while scientific correctness remains an evaluation question.

## Compatibility Boundaries

- Modules and handlers must match declared identifiers and schemas.
- Raw model output does not bypass policy, ontology, or device contracts.
- Knowledge writes and retrieval remain bounded by source identity, ontology and caller scope.
- A remote worker remains behind an authenticated, allowlisted bridge.
- Presentation metadata does not become executable plugin code.

## Limitations and Known Gaps

The architecture inspection does not exercise concurrency, crash consistency,
long-running physical state, timing-sensitive hazards, or every optional
backend. Counts can change as routes and overlays evolve. Evaluation must use
behavioral evidence rather than treating diagram completeness as correctness.

## Verification

Current graph counts and Knowledge ownership were checked by static inspection
on 2026-09-12 against `5542ef2`. No hardware or model was invoked for this refresh.
The earlier application-import measurements below remain historical evidence.

On 2026-08-09, importing the FastAPI application produced 346 `APIRoute`
entries and 353 total route entries. Parsing the graph configuration produced
19 nodes, 68 edges, and 12 `stage_dispatch` mappings. The evidence record
captures commands and output boundaries.

## Related Documents

- [Problem and contributions](01_problem_and_contributions.md)
- [Closed-loop method](03_closed_loop_method.md)
- [Current code snapshot](../runtime/current_code_snapshot.md)
- [LangGraph runtime Reference](../runtime/langgraph_runtime.md)
