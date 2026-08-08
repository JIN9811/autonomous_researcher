---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, reviewer, developer, operator]
scope: [agents, bayesian_optimization, next_candidate]
summary: Current contract for evidence-filtered candidate generation, numeric acquisition, bounded LLM advice, and next-Design recommendation.
source_of_truth:
  - agents/bo_agent.py
  - graphs/modules/bo/module.yaml
  - app/main.py
  - experiments
last_verified: 2026-08-09
verified_against: 0b7627b
related_docs:
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/agents/analysis_agent.md
  - docs/agents/knowledge_agent.md
  - docs/agents/design_agent.md
  - docs/agents/bo_agent_runtime_guideline.txt
supersedes: []
---

# Bayesian Optimization Agent Reference

## Summary

`BOAgent` converts valid analysis/prior evidence and a bounded search space into
a ranked next-candidate recommendation. Numeric acquisition, constraints,
failure penalties, and validators are authoritative; LLM hypothesis/preference
and top-k critique are advisory. The recommendation returns through Guardian
and Design before any physical action.

## Scope

Included are priors, evidence table, search-space update, candidate pool,
acquisition/preference scoring, penalties, ranking, critique, recommendation,
artifacts, and Design handoff. BO does not command devices or certify scientific
improvement.

## Source of Truth

BO agent/module, experiment benchmark/evaluation services, BO routes, and
Analysis/Knowledge/Design handoff state.

## Actual Role

| Does | Does not |
|---|---|
| Filter valid prior observations | Use invalid/missing trials as measured facts |
| Generate and numerically score candidates | Let LLM preference override hard constraints |
| Apply failure/constraint penalties | Treat a recommendation as approval |
| Select and explain one bounded recommendation | Start Design, printing, robot, or equipment directly |
| Emit artifacts and Design constraints | Prove optimization benefit without comparison evidence |

## Closed-Loop Position and Handoffs

| Direction | Component | Contract/state | Purpose | Gate |
|---|---|---|---|---|
| In | Analysis | objective/uncertainty/evaluation | current trial | valid evidence |
| In | Knowledge | BO context/prior trials/patterns | historical context | provenance/compatibility |
| In | Constraints/failures | bounded search/safety limits | exclude/penalize | schema and domain rules |
| Out | Guardian | recommendation/risk/evidence | continuation review | policy/budget |
| Out | Design | candidate/parameters/constraints | next experiment spec | Design hard constraints |

## Inputs and Outputs

Inputs include analysis handoff, objective score, uncertainty, valid prior
observations, Knowledge BO context, search-space constraints, failure memory,
strategy, acquisition, and budget. Outputs include reasoning hypothesis/patch,
candidate pool, numeric and LLM scores, penalties, ranked top-k, critique,
recommendation, artifacts, metrics, decisions, and Design constraints.

## Internal Execution

| Step ID | Work | Boundary/output |
|---|---|---|
| `01_load_analysis_handoff` | current result | invalid handoff blocks |
| `02_filter_valid_priors` | evidence filtering | accepted prior set |
| `03_summarize_evidence_table` | bounded table | provenance summary |
| `04_llm_reasoning_hypothesis_pass` | advisory hypothesis | no authority |
| `05_validate_reasoning_patch` | schema/allowlist | accepted/rejected patch |
| `06_update_search_space` | bounded variables | valid space |
| `07_generate_candidate_pool` | candidates | reproducible pool |
| `08_score_numeric_acquisition` | acquisition score | numeric authority |
| `09_score_llm_preference` | advisory preference | separate score |
| `10_apply_constraint_and_failure_penalties` | exclusions/penalties | safe ranked inputs |
| `11_rank_top_k_candidates` | numeric combined ranking | top-k |
| `12_llm_top_k_critique` | bounded critique | advisory notes |
| `13_select_recommendation` | validated selection | candidate/parameters |
| `14_write_bo_artifacts` | score/reasoning records | evidence artifacts |
| `15_handoff_design_constraints` | next-cycle packet | Design context |

## API Surface

| Class | Method | Path | Service | Effect | Notes |
|---|---|---|---|---|---|
| connected | GET | `/api/bo/config` | BO workspace config | read_only | strategy/search settings |
| operator | POST | `/api/bo/config` | BO workspace config | local_state | validated save |
| connected | POST | `/api/bo/benchmark` | experiment benchmark | local_state/model | bounded comparative tooling, not live loop |
| owned | POST | `/api/bo/run` | BO agent workspace execution | local_state/model | direct bounded recommendation and node event |
| shared | POST | `/api/run/start` | graph/controller | physical_possible | closed-loop execution, not BO alone |

## Tools and Connections

| Tool/service | Boundary | Effect | Evidence |
|---|---|---|---|
| `experiment.benchmark` | experiment service | local_state/model | benchmark result/config |
| Numeric acquisition | in-process/lightweight or configured backend | local_state | score table |
| LLM `bo_policy` | selected model backend | model | hypothesis/preference/critique |
| Knowledge context | runtime/service output | read_only | trial/provenance refs |
| Design handoff | Orchestrator state | local_state | candidate/constraints |

## State, Events, Artifacts, and Storage

BO state records strategy, acquisition, budget, priors, evidence summary,
search-space version, pool, scores, penalties, top-k, recommendation, rationale,
and handoff. Direct workspace execution emits a BO node-completion/result event;
graph execution merges through normal stage state.

## Modes and Fallbacks

Test uses bounded synthetic/fixture observations. Replay reuses recorded trials.
Benchmark is a separate evaluation path. Live-loop recommendation remains a
software proposal until downstream governance. Optional BoTorch/lightweight or
model backend changes are recorded as different configurations.

## Safety, Approval, and Effect Boundary

BO has no direct physical authority. Numeric acquisition and validators remain
authoritative over model advice. Constraints and failure penalties precede
selection. Guardian and Design re-evaluate the recommendation; downstream
Specimen/Manipulation/Equipment gates still apply.

## Errors and Recovery

Invalid analysis or priors are excluded with reason. Empty search space or no
valid candidate yields stop/revise, not an unconstrained suggestion. Invalid
LLM patch/critique is ignored or recorded as rejected. Backend failure can use
an explicitly configured deterministic path; configuration change remains
visible.

## Operator and GUI Surfaces

BO workspace exposes configuration, benchmark, and direct run. Live GUI shows
surrogate/acquisition, candidate ranking, uncertainty, recommendation, and
artifacts. Workspace run does not prove graph or physical execution.

## Current Verification

Verified against all 15 internal steps, `experiment.benchmark`, four BO API
routes, and Analysis/Knowledge/Design handoffs at baseline `0b7627b`. No
comparative optimization benefit is claimed.

## Limitations and Known Gaps

No paper-scoped evidence establishes sample efficiency, convergence,
calibration, superiority, or physical improvement. Behavior depends on valid
priors, selected backend, constraints, and model configuration.

## Related Documents

- [Agent Matrix](agent_api_connection_matrix.md)
- [Analysis](analysis_agent.md)
- [Knowledge](knowledge_agent.md)
- [Design](design_agent.md)
- [Legacy BO Guideline](bo_agent_runtime_guideline.txt)
- [Evaluation and Results](../paper/06_evaluation_and_results.md)
