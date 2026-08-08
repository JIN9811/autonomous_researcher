---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, reviewer, operator, developer, safety_reviewer]
scope: [agents, guardian, safety_control_plane]
summary: Current contract for graph-wide risk review, incidents, approvals, safety budgets, and continue/stop/error routing.
source_of_truth:
  - agents/guardian_agent.py
  - graphs/modules/guardian/module.yaml
  - policies/guardian_gate.py
  - app/controller.py
  - app/main.py
last_verified: 2026-08-09
verified_against: 0b7627b
related_docs:
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/agents/orchestrator_agent.md
  - docs/paper/08_safety_ethics_and_limitations.md
  - docs/runtime/guardian_graphwide_safety.md
supersedes: []
---

# Guardian Agent Reference

## Summary

`GuardianAgent` is ATR's graph-wide safety review and continuation control
plane. It evaluates current gates and recent failures, incorporates device and
queue health, records risk/incident/approval evidence, and returns continue,
review, stop, or error state. Orchestrator translates that state into graph
routing; Guardian does not coordinate the full workflow or execute devices.

## Scope

Included are Guardian decisions, status aggregation, incidents, alerts, tool
records, approvals, corrective actions, safety budgets, and stop authority.
This Reference does not claim that control presence proves safety effectiveness.

## Source of Truth

- Agent: `agents/guardian_agent.py`
- Module: `graphs/modules/guardian/module.yaml`
- Policy: `policies/guardian_gate.py`
- State/API aggregation: `app/controller.py`, `app/main.py`

## Actual Role

| Does | Does not |
|---|---|
| Evaluate policy, risk, evidence, failures, and health | Replace equipment-specific physical interlocks |
| Return continue/review/stop/error decisions | Directly execute a device or recovery command |
| Produce incidents, alerts, records, and corrective actions | Own general workflow planning |
| Request or require operator approval | Resolve approval on behalf of the operator |
| Enforce safety budgets and stop authority | Prove generalized laboratory safety |

## Closed-Loop Position and Handoffs

| Direction | Component | Contract/state | Purpose | Gate |
|---|---|---|---|---|
| In | All stages | current state, decisions, failures, evidence | graph-wide review | evidence completeness |
| In | Device/queue services | health/status | external readiness | stale/unavailable health remains explicit |
| In | Approval service | pending/resolved approvals | human authority | scope and expiry |
| Out | Orchestrator | Guardian decision/contract | route translation | decision schema |
| Out | Operator | incident, alert, approval, corrective action | review/intervention | operator authority |
| Out | Runtime | continue, review, stop, error | cycle or terminal route | safety budget/policy |

## Inputs and Outputs

Inputs include `OrchestratorState`, latest stage reports, device health, recent
failures, tool-call records, approval queue, experiment constraints, loop count,
safe-stop state, and evidence context.

Outputs include Guardian gate results/decisions/contracts, risk vectors,
incident and hardware-alert records, blocked tool-call records, corrective
actions, approval requests, safety-budget state, and a route decision consumed
by Orchestrator.

## Internal Execution

| Step | Kind | Consumes | Produces/decides | Failure boundary |
|---|---|---|---|---|
| `01_check_safety_gates` | internal | stage/risk/evidence/health | pass/block/review facts | unknown or failed gate is not allow |
| `02_review_recent_failures` | internal | errors/incidents/retries | failure context/corrective action | repeated/major failure escalates |
| `03_decide_continue_stop_error` | internal | gate + failure + budget | continue/stop/error/review | invalid decision routes to error/review |

## API Surface

| Class | Method | Path/family | Handler/service | Effect | Notes |
|---|---|---|---|---|---|
| owned | GET | `/api/guardian/status` | Guardian status aggregation | read_only | current graph-wide report |
| owned | GET | `/api/runs/{run_id}/guardian/status` | run Guardian report | read_only | run-scoped evidence |
| operator | POST | `/api/guardian/incidents/{incident_id}/notes` | incident service | local_state | appends operator note |
| operator | POST | `/api/runs/{run_id}/guardian/incidents/{incident_id}/notes` | run incident service | local_state | run-scoped note |
| shared | GET/POST | `/api/runs/{run_id}/approvals*` | approval service | read_only/local_state/physical_possible | request/list/resolve |
| operator | POST | `/api/approvals/{approval_id}/approve`, `/api/approvals/{approval_id}/reject`, `/api/approvals/{approval_id}/revise` | compatibility approval service | local_state/physical_possible | explicit human resolution |

## Tools and Connections

| Tool/service | Registry/implementation | Boundary | Mode | Effect | Evidence |
|---|---|---|---|---|---|
| `device.health` | registered tool/bridge registry | in-process to device status | all | read_only | health snapshot |
| `experiment.queue.status` | experiment queue tool | in-process | all | read_only | queue status |
| LLM role | `guardian_review` | selected model backend | configured | model | advisory review metadata |
| Policy gate | `policies/guardian_gate.py` | deterministic/in-process | all | local_state | gate decision |
| Approval service | controller/API | human boundary | live/configured | physical_possible | request and resolution |

Guardian LLM work has the highest shared lease priority (`0`) relative to active
workflow (`10`), operator chat (`20`), and background reconciliation (`30`).

## State, Events, Artifacts, and Storage

Guardian state is stored in run metadata and events: gate history, contracts,
latest decision, incidents, alerts, tool-call records, approvals, corrective
actions, safety budgets, and handoff status. Run-scoped APIs provide status and
notes. A GUI card is a view over server state, not the source of authority.

## Modes and Fallbacks

Policy review applies to Test, Replay, Simulation, and Live with environment-
appropriate evidence. Test/simulation decisions do not validate Live safety.
Unavailable model advice cannot bypass deterministic policy. Unavailable
device health is degraded/uncertain state, not healthy state.

## Safety, Approval, and Effect Boundary

Guardian can block or stop downstream effects but does not operate equipment.
Approvals bind to action, run/cycle, parameters, device, scope, and validity;
approval resolution remains human/operator authority. Safety-budget exhaustion,
missing evidence, stale health, or unknown effect routes to review/stop/error.

## Errors and Recovery

| Failure | Result | Recovery | Prohibited action |
|---|---|---|---|
| Missing/stale health | uncertain/review | refresh bounded health evidence | assume healthy |
| Policy/schema failure | block/error | correct input and re-evaluate | bypass gate |
| Pending/expired approval | wait/review | obtain current scoped decision | reuse stale approval |
| Repeated major incident | stop/error | operator review and corrective action | unbounded retry |
| Unknown external effect | stop/review | independently inspect state/proof | automatic allow/repeat |

## Operator and GUI Surfaces

Live GUI exposes Guardian report, risk, incidents, approvals, tool records,
hardware alerts, corrective actions, and budget state. Approval panels resolve
server-side requests. Incident-note APIs append operator context without
rewriting the original incident.

## Current Verification

Verified against `GuardianAgent`, all three module internal steps, two declared
tools, policy gate, status aggregation, incident and approval endpoints at
baseline `0b7627b`. No paper-scoped live safety-effectiveness record exists.

## Limitations and Known Gaps

Hazard coverage, calibration, operator workload, adversarial robustness, and
physical stop latency are not established by this Reference. Domain interlocks
remain external requirements.

## Related Documents

- [Agent Matrix](agent_api_connection_matrix.md)
- [Orchestrator Agent](orchestrator_agent.md)
- [Safety, Ethics, and Limitations](../paper/08_safety_ethics_and_limitations.md)
- [Guardian Graph-wide Safety](../runtime/guardian_graphwide_safety.md)
- [Security Policy](../../SECURITY.md)
