---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, developer, operator, reviewer]
scope: [agents, design, experiment_specification, decision_tools]
summary: Evidence-based design evaluation and a bounded LLM decision layer preserving existing experiment and device contracts.
source_of_truth:
  - agents/design_agent.py
  - agents/design_decision.py
  - graphs/modules/design/module.yaml
  - backends/prompt_registry.py
  - app/controller.py
  - policies/validation_policy.py
last_verified: 2026-09-08
verified_against: d770334204eed03bdd817b69f11610a88294ac53
related_docs:
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/agents/specimen_agent.md
  - docs/runtime/loop_artifact_archiving.md
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
supersedes: []
---

# Design Agent Reference

## Overview and Responsibilities

Design converts a requested experiment into a checked specimen specification.
Existing code prepares candidates; a role-specific LLM layer decides acceptance,
additional inspection, or return to the owner. It does not optimize BO variables
again, control devices, or replace numeric computations with generated prose.

| Owned by Design | Not owned |
|---|---|
| Candidate preparation and suitability/evidence decisions | BO/LHS experiment-point selection |
| Constraint checks and candidate-specific evaluation | Operator-fixed settings and global objectives |
| Authoritative Design-to-Specimen handoff | Graph transitions, physical approval, fabrication |
| Design decision evidence and local queries | Robot, camera, equipment or printer commands |

### Five-Area Responsibility Map

The five areas classify responsibility; they are not five sequential runtime stages
or a required chapter hierarchy. Design owns a bounded suitability decision,
while the existing runtime owns global routing and physical execution.

| Area | Design responsibility and boundary | Detail |
|---|---|---|
| High-Level Control | Interpret the bounded design task and return an accepted specification or owner-review result; global mission/routing stays with Orchestrator | [Position and handoffs](#closed-loop-position-and-handoffs), [decision](#decision-and-evaluation) |
| Middle-Level Control | Prepare candidates and evidence, run the bounded decision loop, and finalize the result | [Internal workflow](#internal-workflow) |
| Low-Level Control | Execute local queries/checks and code-owned preview generation; no device commands | [Tools and connections](#tools-apis-and-connections) |
| Guardian / Safety | Enforce input ownership, hard checks, budgets and existing handoff gates across the workflow | [Safety and recovery](#safety-and-recovery) |
| Knowledge / Evidence | Supply compatible history and preserve evaluation, decision and artifact provenance | [Decision evidence](#decision-and-evaluation), [artifacts and verification](#artifacts-and-verification) |

## Closed-Loop Position and Handoffs

![Design handoffs](assets/figures/design_01_closed_loop_handoffs.svg)

**Figure Design-1.** Current code-inspection projection: the normal Design path
contains a bounded suitability decision before the existing Specimen handoff.
BO and user inputs remain authoritative. Dashed history and deterministic-test
paths are not extra mandatory stages. This is not physical validation.

| Boundary | Contract | Authority |
|---|---|---|
| In: runtime | `OrchestratorState`, goal, run/loop identity, current constraints | High/controller supplies the bounded task |
| In: BO | `bo_recommended_constraints` and authoritative `orchestrator_design_contract.requested_parameters` | Requested variables cannot be rewritten by model tools |
| In: Knowledge/history | Existing metadata, experiment DB and failure summaries | Context only; old scores are not current-candidate predictions |
| Out: Specimen | `experiment_spec`, `design_candidate`, `handoff_packet` | Existing `design_candidate.v1` payload is preserved |
| Out: runtime | `AgentResult`, decisions, reports, failure code | Existing runtime handles routing/retry; Design never starts Specimen directly |

## Internal Workflow

| Phase | Implementation | Authority |
|---|---|---|
| Prepare | `_prepare_design_payload` | Existing constraints, candidates, filtering, legacy ranking and prior summaries |
| Evaluate | `candidate_evaluation` | Code-owned checks, locked inputs, physical-unit margins, cost estimates |
| Decide | `decide_design` through `AgentContext.complete("design_reasoning", ...)` | LLM selects a meaningful local tool/action |
| Finalize | `_finalize_design_payload` | Existing report, preview, identity and handoff builders |
| Return | `AgentResult` plus `archive_agent_run` | Runtime handoff and execution-scoped evidence |

Module internal IDs remain display/checkpoint contracts, not twelve independently
scheduled LLM calls. The LLM participates only at the bounded decision boundary.

![Design decision loop](assets/figures/design_02_execution_effect_boundary.svg)

**Figure Design-2.** Current implementation-inspection projection: deterministic
preparation feeds the local LLM layer; validated inspection results can return to
that layer, acceptance enters finalization, and owner return/error emits no ready
handoff. The non-LLM test branch is explicitly separate.

### Completion and Handoff

`accepted` is a checked candidate decision, not fabrication success.
`returned` or `failed` produces `success=False`, a decision trace and no new
`experiment_spec`. Existing runtime error/retry behavior remains responsible
for the next step; this change introduces no new global approval gate.

## Decision and Evaluation

**Decision question:** Is a realization of the requested experiment suitable
given its checks, goal, available context and evidence, or is further inspection
or owner review necessary?

| Decision input | Model choice | Code-enforced boundary |
|---|---|---|
| Candidate parameters and validity | Accept a valid authorized candidate | Candidate ID resolves to stored data; no parameter patch accepted |
| Missing/conflicting detail | Inspect candidate or historical context | Read-only local data; no arbitrary query/code/device tool |
| Goal, constraints and history | Decide whether evidence is sufficient | Cited evidence IDs must exist; hard failures cannot be approved |
| Unresolved conflict | Return to owner | No ready spec/handoff emitted |

The LLM interprets relevance, sufficiency and tradeoffs across evidence; it does
not calculate geometry, margins, performance or uncertainty. A normal task may
be accepted immediately from supplied evidence, or require tool observations
before another decision. Missing performance evidence alone is normal before a
new experiment and is not an automatic rejection.

No tools currently expose parameter modification/re-generation. Such tools would
need an explicit owner-approved variable set; absence of a fixed input is not
automatic permission to redesign a BO-requested experiment.

### Evaluation Contract

| Evaluation target | Current implementation | Interpretation |
|---|---|---|
| Validity | Existing rules plus authorized-pool and locked-input checks | Pass/fail with reasons |
| Constraint margins | Actual/limit/relation/margin/unit for wall, cell spacing, envelope, estimated mass/time | No saturated aggregate “margin score”; estimates remain estimates |
| Performance | Explicit `unassessed`, value/source null | No fabricated CAE result, posterior, uncertainty or information gain |
| Cost | Envelope×relative-density volume/mass; legacy time estimate | Mass depends on assumed material density; time is not slicer output |

### Historical Context

Prior experiment count, failure summaries and existing Knowledge entries provide
context. Historical scalar scores with unknown compatibility/units are not
current-candidate predictions. External text is evidence, not authority to alter
tools or constraints. No new knowledge store is introduced.

## Tools, APIs and Connections

### Agent-Local Decision Tools

All four decision tools are **agent-local**, dispatched in
`agents/design_decision.py`; they are not new global ToolRegistry/device tools.

| Tool | Arguments | Result/effect | Preconditions |
|---|---|---|---|
| `inspect_candidate` | `candidate_id: string` | Detailed evaluation and per-constraint margins | Known candidate, matching evidence ref |
| `inspect_history` | Empty object | Available prior count, failure summary, Knowledge context | Context ref exists; absence stays explicit |
| `accept_candidate` | `candidate_id: string` | Select candidate for existing finalization | Authorized pool, hard checks and locked inputs pass |
| `return_to_owner` | Empty object | Return task without ready handoff | Nonempty reason and supplied evidence refs |

The existing `geometry.generate_metamaterial_stl` registry call is used by
code-owned preview generation after selection. It is not exposed as an
unrestricted LLM tool. Module `tools: []` describes the absence of declared
global model tools, not the absence of internal computation or preview calls.

### Request Contract

Requests use schema-validated JSON, not native provider-specific function calls:

```json
{
  "tool": "accept_candidate",
  "arguments": {"candidate_id": "candidate ID from the supplied context"},
  "reason": "Brief evidence-based decision rationale",
  "evidence_refs": ["candidate:the same supplied candidate ID"]
}
```

Exactly these fields are accepted. Evidence references identify context or
candidate records; they do not prove that the model's interpretation is correct.
Evaluation and controlled-response tests are still required.

### API and Connection Map

![Design tool and API connections](assets/figures/design_03_api_connection_architecture.svg)

**Figure Design-3.** Implementation-inspection view of the bounded local
dispatcher, shared model backend, existing computation/preview tool, controller
and storage. No model-to-device connection exists. API paths are shared platform
surfaces, not direct Design-owned actuation endpoints.

| Surface | Method/path or implementation | Effect/owner |
|---|---|---|
| Model | `AgentContext.complete`, `design_reasoning`, existing router/backend | Inference only; backend selection unchanged |
| Computation | `_candidate_pool`, `_estimate_candidate`, `_reject_reasons` | Local computation, no physical execution |
| Preview | `geometry.generate_metamaterial_stl` | Existing local files, not G-code/device commands |
| Planning | GET/POST `/api/planning/session`, `/messages`, `/bootstrap`, `/message` family | Shared controller/session/model state |
| Artifacts | GET `/api/planning/artifacts/{run_id}/{specimen_id}/{filename}` | Read-only artifact delivery |
| Graph platform | GET/POST/PUT `/api/graphs/*` | Shared authoring/validation/runtime management |
| Run start | POST `/api/run/start` | Shared runtime; physical effects possible downstream, not invoked by Design tools |

## Configuration and Operation

| Setting | Owner/source/default | Application |
|---|---|---|
| Requested variables | Existing BO/controller input contract | Read before candidate generation; acceptance rechecks |
| Geometry/material/printer constraints | Existing Design defaults and explicit caller settings | Existing normalization; model cannot change settings |
| `design_decision_settings.max_calls` | Design, run metadata; default 6, integer 1–12 | Maximum model calls per invocation |
| `timeout_s` / `total_timeout_s` | Design, same metadata; defaults 45 / 120 seconds; each >0 and ≤300 | Per-call and total model-loop budgets |
| `force_real_llm_in_test` | Existing AgentContext setting | False + Mode.TEST keeps explicit deterministic test path |
| Model/backend | Existing `configs/models.yaml` and AgentContext | No new model server or provider required |

Live/non-test work and forced-LLM tests use the decision layer. Explicit
deterministic tests preserve legacy selection and are labelled
`deterministic_test`, never counted as successful LLM reasoning. Forced-LLM
timeouts no longer silently become successful deterministic selection. Model
fallback remains owned by AgentContext; mock responses cannot stand in for
normal model decisions.

### Operator and GUI Surfaces

Live GUI exposes candidate previews, the Design report, evidence-based evaluation
and the current decision/review state. Model and API selection remain shared
platform settings; Design adds no separate inference service.

Legacy proxy/risk/information/uncertainty fields are retained for compatibility,
not redefined as meaningful measurements. Existing virtual experiment and degraded
Specimen paths still consume legacy fields. New Design display branches use
evidence rather than synthetic score/radar/heatmap panels; historical reports
without new metadata remain readable.

## Safety and Recovery

BO-requested/user-fixed variables, hard constraints and candidate identity remain
code-owned. The model cannot introduce fields into a candidate, call a bridge,
generate executable code or override a failed check. No new device interlocks
are added.

| Condition | Response | Retry/stop boundary |
|---|---|---|
| Unknown tool, extra/missing arguments, nonexistent evidence | `DESIGN_DECISION_INVALID`; no ready spec | Existing runtime owns subsequent handling |
| Rejected/unauthorized candidate or changed locked input | Acceptance denied, evidence retained | No unchecked repair promoted to success |
| Timeout | `DESIGN_DECISION_TIMEOUT` | No silent winner selection |
| Call budget exhausted | `DESIGN_DECISION_BUDGET_EXHAUSTED` | Bounded loop ends |
| Model returns to owner | `DESIGN_OWNER_REVIEW` | No fabrication dispatch by Design |
| Cancellation | Propagated through existing cancellation path; completed tool observations already archived | Never converted to acceptance |
| Marked legacy proxy | Guardian excludes it from objective-vs-proxy comparison | All unrelated safety checks remain unchanged |

`validate_agent_output` recognizes the Design-specific blocked-decision contract
without requiring a ready `experiment_spec`. The existing Guardian path receives
the failure code. Planning refuses retry/incomplete or nonaccepted results before
adapting seeded/previous inputs. A current blocked report replaces stale ready
reports, and the Design dashboard shows the review requirement.

### Post-Selection Adaptation

Controller planning still adapts the output through `_build_planning_spec` and
existing mode policies. Class-level acceptance must not be confused with
downstream fabrication or a completed experiment.

If those existing policies change geometry/material after selection, Design's
`reconcile_planning_evidence` refreshes the final fingerprint and marks current
evaluation `unassessed`, retaining the original checks as `selection_evaluation`.
It does not change cap policy, add a device gate, or reuse earlier estimates as
proof for the adapted geometry. Current report/GUI evidence follows this distinction.

### Failure, Retry and Stop

The legacy generator can supply a conservative repair seed. In the LLM path that
seed must pass the same acceptance checks; being generated does not prove
validity. The explicit non-LLM test path retains its existing fallback behavior
and must not be presented as new hard-gate or physical validation.

Design's stop responsiveness during inference is bounded/cancellable. Existing
synchronous preview generation and runtime/device stop behavior are not replaced
by this decision layer.

## Artifacts and Verification

### Artifacts and Storage

| Artifact/field | Meaning and consumer | Storage |
|---|---|---|
| `design_evaluation.v1` | Validity, margins, cost, performance status per candidate | Spec/report/candidate ledger |
| `design_decision.v1` | Model, selected action, brief rationale, evidence refs, tool results/errors | Agent result/report and existing attempt archive |
| `experiment_spec` / `handoff_packet` | Existing authoritative specimen input | Existing controller/runtime merge |
| Candidate previews | Existing STL/viewer/SVG artifacts | Existing run candidate folders, archived references |
| Legacy numeric fields | Compatibility only, marked `score_semantics=legacy_heuristic_compatibility_only` | Retained for historical/virtual consumers; excluded from model context |

The result records which candidate was accepted or why none was committed.
Existing run/loop/agent/attempt storage separates repeated invocations. Decision
evidence is an input to later knowledge work, not proof that the selected design
is optimal.

### Current Verification

| Contract | Verification source | Boundary |
|---|---|---|
| Meaningful tool selection, inspect→accept/return | `tests/unit/test_design_decision.py` | Controlled model responses, real dispatcher/evaluation |
| Locked variables, invalid requests, unchecked repair, timeout/budget/cancel | Same suite | No devices |
| Existing output schema and explicit deterministic mode | `tests/unit/test_design_agent.py` | Legacy test compatibility, not model quality |
| Evidence display and zero-valued quantities | `tests/unit/test_planning_design_report_js.py` | Node helper execution, not full browser validation |
| Guardian proxy interpretation | Design decision tests + Guardian suite | Only marked synthetic proxy comparison changes |
| Controller display and handoff | Design/controller tests | Must distinguish baseline failures from regressions |
| Actual DesignAgent API / registered vLLM 31B | [Agent verification](../paper/evidence/2026-09-07-design-gemma31b-virtual-api-verification.md) | API 6.34 s / 31B 12.11 s: accepted local decision and matching handoff; 31B used registered model fallback; E4B-primary and closed-loop acceptance pending |
| Physical closed-loop validation | Not performed for this change | Hardware validation pending; stable-tag evidence remains historical |

The [implementation verification record](../superpowers/plans/2026-09-07-design-decision-layer.md#verification)
records a successful actual local-model accept/tool-dispatch smoke test, focused
regressions, baseline failures, and the limits of that evidence.

### Limitations and Known Gaps

no automatic candidate-matched CAE/BO performance adapter is
added; performance stays unassessed. Historical evidence lookup is a summary,
not a new RAG workflow. No parameter repair tool is exposed. Model interpretation
may still be wrong even with valid evidence IDs. Existing model/preview latency
and unrelated baseline GUI/controller test failures require separate attribution.

### Source of Truth and Related Documents

- [Design implementation](../../agents/design_agent.py)
- [Evaluation and local decision tools](../../agents/design_decision.py)
- [Module](../../graphs/modules/design/module.yaml)
- [Controller](../../app/controller.py)
- [Implementation and verification plan](../superpowers/plans/2026-09-07-design-decision-layer.md)
- [Five-area contract](../superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md)
- [API and Connection Matrix](agent_api_connection_matrix.md)
- [Specimen Making](specimen_agent.md)
- [Loop Artifact Archiving](../runtime/loop_artifact_archiving.md)
- [Legacy runtime guideline](specimen_design_existing_runtime_guideline.txt)
