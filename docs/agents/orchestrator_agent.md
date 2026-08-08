---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, operator, developer, maintainer]
scope: [agents, orchestrator, control_plane]
summary: Current contract for ATR workflow coordination, mission compilation, handoffs, run lifecycle, and Guardian route translation.
source_of_truth:
  - agents/orchestrator_agent.py
  - graphs/modules/orchestrator/module.yaml
  - graphs/configs/atr_closed_loop.yaml
  - app/controller.py
  - app/main.py
  - orchestrator/supervisor.py
last_verified: 2026-08-09
verified_against: 0b7627b
related_docs:
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/agents/design_agent.md
  - docs/agents/guardian_agent.md
  - docs/runtime/langgraph_runtime.md
supersedes: []
---

# Orchestrator Agent Reference

## Summary

`OrchestratorAgent` is ATR's workflow coordination plane. It converts accepted
operator intent into mission and orchestration contracts, prepares bounded
context for the active agent, records follow-up decisions and loop reflection,
and translates Guardian results into runtime routes. It does not execute device
tools and is not the safety authority.

## Scope

Included are pre-execution planning, handoffs, shared run lifecycle, planning
session, events, artifacts, and approval coordination. Device implementation,
domain decisions, and Guardian policy are owned elsewhere.

## Source of Truth

- Agent: `agents/orchestrator_agent.py`
- Module: `graphs/modules/orchestrator/module.yaml`
- Runtime: `app/controller.py`, `orchestrator/supervisor.py`
- Graph: `graphs/configs/atr_closed_loop.yaml`
- APIs: `app/main.py`

## Actual Role

| Does | Does not |
|---|---|
| Normalize operator intent and required inputs | Infer missing required values as accepted facts |
| Compile mission, orchestration plan, context, and handoffs | Replace domain agents' authoritative transformations |
| Coordinate read-only checks and agent follow-up | Directly invoke printer, robot, desktop, or instrument motion |
| Record ask/retry/continue/stop decisions | Override Guardian or operator safety decisions |
| Translate Guardian output into a graph route | Treat a chat response as a completed experiment |

## Closed-Loop Position and Handoffs

| Direction | Component | Contract/state | Purpose | Gate |
|---|---|---|---|---|
| In | Operator/Live GUI | message, session memory, accepted inputs | establish intent | missing-input state machine |
| In | Runtime/checkpoint | `OrchestratorState`, stage, run/cycle | resume coordination | valid run and graph state |
| In | Any agent | result, concern, evidence refs | decide follow-up | schema and result status |
| In | Guardian | gate/decision/contract | choose route | Guardian authority |
| Out | Design pre-stage | `mission_contract.v1`, context | begin a governed cycle | required inputs complete |
| Out | Active agent | `handoff_packet.v1` | bounded work request | graph-selected stage |
| Out | Runtime | route/decision register | continue, ask, retry, stop, error | checkpoint and terminal rules |

## Inputs and Outputs

Inputs include Live chat content, session memory, accepted constraints,
`OrchestratorState`, graph stage, prior handoffs, failures, Knowledge/BO context,
and Guardian results.

Declared outputs are `operator_intent.v1`, `experiment_contract.v1`,
`mission_contract.v1`, `orchestration_plan.v1`,
`orchestrator_parallel_checks.v1`, `orchestrator_followup.v1`,
`decision_register.v1`, `handoff_packet.v1`, and `loop_reflection.v1`.
They are merged into run/planning state and emitted as events/artifacts where
the controller contract requires it.

## Internal Execution

| Step | Kind | Consumes | Produces/decides | Failure boundary |
|---|---|---|---|---|
| `01_receive_operator_intent` | pre-stage | message/session | `operator_intent.v1` | malformed/empty intent |
| `02_check_missing_required_values` | pre-stage | intent/constraints | `missing_input_request.v1` | execution remains pending |
| `03_build_mission_contract` | pre-stage | accepted values | `mission_contract.v1` | invalid contract blocks handoff |
| `01_intent_state_machine` | internal | operator state | normalized intent | contradictory/missing state |
| `02_compile_orchestration_plan` | internal | mission/graph | `orchestration_plan.v1` | invalid stage/handler plan |
| `03_parallel_read_only_checks` | internal | capability/context | check report | unavailable dependency remains explicit |
| `04_build_context_pack` | internal | bounded prior state | `context_pack.v1` | context size/schema rejection |
| `05_emit_handoff_packet` | internal | plan/context | `handoff_packet.v1` | target/contract invalid |
| `06_followup_opinion` | internal | agent result | `orchestrator_followup.v1` | unresolved concern |
| `07_decision_register` | internal | result/follow-up | ask/retry/continue/stop | route not authorized |
| `08_loop_reflection` | internal | cycle evidence | `loop_reflection.v1` | incomplete evidence is recorded |
| `09_translate_guardian_result` | internal | Guardian contract | `route_decision.v1` | unknown decision routes to review/error |

These IDs describe the module's contract; they are not twelve independently
scheduled top-level graph nodes.

## API Surface

| Class | Method | Path/family | Handler/service | Effect | Notes |
|---|---|---|---|---|---|
| owned | GET/POST | `/api/planning/session`, `/messages`, `/bootstrap`, `/message` | planning/controller | local_state/model | operator intent and transcript workflow |
| connected | GET | `/api/planning/artifacts/{run_id}/{specimen_id}/{filename}` | artifact service | read_only | retrieves planning artifacts |
| shared | POST | `/api/run/start`, `/pause`, `/resume`, `/stop` | controller | local_state/physical_possible | mode and active stage determine effect |
| shared | POST | `/api/run/safe-stop`, `/emergency-*` | controller | physical_possible | stop/resume/reset control surface |
| shared | GET/POST | `/api/runs/{run_id}/*` | run service | read_only/local_state/physical_possible | state, pause/resume/stop, events, artifacts, approvals |
| shared | GET | `/api/events/recent`, `/api/events/stream` | event service | read_only | snapshot and SSE |
| shared | GET/POST | `/api/runtime/*` | runtime compatibility/model service | read_only/local_state/model | state, lifecycle, backend, model, API-key status |
| operator | POST | `/api/approvals/{approval_id}/approve`, `/api/approvals/{approval_id}/reject`, `/api/approvals/{approval_id}/revise` | approval service | local_state/physical_possible | resolution can enable/block downstream work |

The exhaustive source is `/openapi.json`. Compatibility runtime routes do not
create a second Orchestrator implementation.

## Tools and Connections

| Tool/service | Registry/implementation | Boundary | Mode | Effect | Evidence |
|---|---|---|---|---|---|
| LLM role | `orchestrator_supervisor` | selected model backend | configured | model | prompt/result metadata |
| Controller | `app/controller.py` | in-process | all | local_state/physical_possible | run state/events/artifacts |
| Supervisor | `orchestrator/supervisor.py` | in-process | all | local_state | handoff/decision records |
| Checkpoint/run loop | LangGraph runtime | in-process/file state | test/replay/live | local_state | checkpoint and stage events |
| Approval service | controller/API | in-process/operator | live where configured | physical_possible | approval request/resolution |

The module declares no direct tools; coordination occurs through runtime and
handoff contracts.

## State, Events, Artifacts, and Storage

Planning messages are file-backed for an active run. Run state contains stage,
mode, loop count, metadata, decisions, health, approvals, and artifact refs.
Events are available as recent/SSE/run-scoped streams; artifacts are retrieved
through run/planning APIs. UI session state is not a substitute for checkpoint
or file-backed run evidence.

## Modes and Fallbacks

- Test: uses bounded test providers and must remain labeled Test.
- Replay: consumes recorded trace/state; no new physical action is implied.
- Simulation: depends on selected domain adapters.
- Browser: operates shared APIs and may mutate server state.
- Live: can coordinate downstream physical effects only through agent, bridge,
  Guardian, and approval boundaries.

Model/backend fallback changes the evaluated configuration and remains recorded.

## Safety, Approval, and Effect Boundary

Orchestrator has workflow authority, not safety authority. It may request and
route approvals, but Guardian and the operator decide safety/approval outcomes.
`direct_device_execution_allowed` is false. Safe stop and emergency routes are
shared controller operations; route translation must never convert missing or
uncertain Guardian state into implicit continuation.

## Errors and Recovery

| Failure | Persisted state | Recovery | Prohibited action |
|---|---|---|---|
| Missing input | pending request/session | operator supplies bounded value | invent value and start |
| Invalid handoff | decision/error event | repair contract and retry before effect | skip target validation |
| Agent failure | result/error/checkpoint | bounded retry or route to Guardian/error | discard prior evidence |
| Unknown external effect | uncertain run state | stop, inspect device/evidence, then decide | automatic physical retry |
| Missing Guardian result | review/error | re-evaluate policy/context | implicit allow |

## Operator and GUI Surfaces

The Live GUI and planning APIs expose chat, mission, handoff, cycle, approval,
event, and artifact state. Runtime IDE and graph/module workspaces configure the
execution platform; they do not replace Orchestrator contracts. Main GUI run
controls call shared controller APIs.

## Current Verification

Verified against `OrchestratorAgent`, its 3 pre-execution and 9 internal module
entries, graph overlays, controller lifecycle, and 56 broad shared/prefix route
entries at baseline `0b7627b`. The prefix count overlaps other agents and is
not a performance metric.

## Limitations and Known Gaps

This Reference does not validate long-running recovery, concurrent operator
actions, model quality, or complete live campaigns. Some coordination behavior
is concentrated in the large controller file.

## Related Documents

- [Agent Matrix](agent_api_connection_matrix.md)
- [Design Agent](design_agent.md)
- [Guardian Agent](guardian_agent.md)
- [LangGraph Runtime](../runtime/langgraph_runtime.md)
- [Closed-Loop Method](../paper/03_closed_loop_method.md)
