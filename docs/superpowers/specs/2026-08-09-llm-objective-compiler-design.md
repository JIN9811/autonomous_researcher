---
doc_type: design
subtype: architecture
status: review
authority: proposal
audience:
  - researcher
  - operator
  - developer
  - maintainer
scope:
  - objective_compiler
  - analysis_agent
  - knowledge_agent
  - bo_agent
  - live_gui
summary: Template-free LLM objective composition through a unit-safe declarative DSL and deterministic evaluator for closed-loop BO.
decision_status: approved
related_docs:
  - docs/agents/bo_agent.md
  - docs/agents/bo_agent_runtime_guideline.txt
  - docs/agents/analysis_utm_runtime_guideline.txt
  - docs/agents/knowledge_agent_self_evolution_runtime_guideline.md
  - docs/runtime/autonomous_experiment_runtime.md
  - docs/superpowers/specs/2026-08-09-knowledge-relation-reconciliation-design.md
supersedes: []
---

# LLM Objective Compiler Design

## 1. Purpose

ATR needs experiment-specific objective functions without adding one Python
function or selecting one fixed template for every new research question. This
design introduces a template-free Objective Compiler. An LLM composes a bounded
declarative objective from registered measurements and safe operators. A
deterministic evaluator, not the LLM, validates and calculates the score used by
Bayesian Optimization.

The compiler preserves the existing `ExperimentObjective`, `objective_score`,
Analysis-to-Knowledge observation, and BO-to-Design handoff boundaries. It does
not let an LLM execute Python, Cypher, shell commands, or arbitrary expressions.

## 2. Confirmed Decisions

1. Objective functions are generated from research intent instead of selected
   from a fixed case-template library.
2. The LLM emits only `objective_spec.v1`; it never calculates the authoritative
   score and never emits executable source code.
3. Objective expressions may be nonlinear and may include bounded piecewise
   penalties, ratios, normalization, aggregation, and hard constraints.
4. Every referenced metric must exist in the active Metric Registry.
5. Static unit, type, domain, missing-value, and numerical-stability checks are
   mandatory before preview or activation.
6. A generated objective requires an operator-reviewed preview before first
   activation.
7. An active objective version is immutable for the lifetime of a run.
8. Previously generated objectives may be explicitly reused as immutable
   versions, but they are not treated as hidden templates.
9. The same deterministic evaluator is used in test, live, replay, and BO
   ingestion paths.
10. Objective compilation failure never triggers a silent default objective.
    Analysis evidence remains available, but BO is blocked until a valid
    objective is active.
11. An already active objective continues to evaluate when the LLM is unloaded
    or unavailable.
12. Physical safety, printability, measurement trust, and Guardian authority are
    not collapsed into the scalar score. Non-negotiable conditions remain hard
    constraints or external gates.

## 3. Current Baseline and Gap

The current runtime already has:

- `ExperimentObjective` in `experiments/schemas.py`;
- `current_experiment_objective` in `OrchestratorState`;
- UTM, CAE, print, quality, and uncertainty metrics from Analysis;
- `objective_score` consumed by Knowledge, BO, Guardian, and reports;
- `next_design_request.v1` emitted by BO;
- a BO workspace, random/grid/BO benchmark, lightweight candidate-pool scorer,
  and optional BoTorch posterior scoring.

The current Analysis score is selected by metric-name keywords and fixed
weights. The BO benchmark may use a virtual proxy for unevaluated candidates.
That is useful for smoke tests but does not provide a research-defined,
versioned objective with term-level provenance. Strategy labels for constrained,
multi-objective, and multi-fidelity modes also currently map to the same base BO
path.

## 4. Architecture

```text
Research intent / experiment plan
        |
        v
Metric Registry query
        |
        v
LLM Objective Composer
        |
        v
objective_spec.v1 draft
        |
        +--> Schema + operator allowlist validation
        +--> Unit/type/domain validation
        +--> Data-readiness validation
        +--> Historical preview + sensitivity report
        |
        v
Operator approval
        |
        v
Immutable active objective version
        |
        v
Deterministic Objective Evaluator
        |
        +--> objective_score
        +--> feasible / constraint outcomes
        +--> term contributions and uncertainty
        +--> provenance and objective hash
        |
        v
Knowledge observation -> BO surrogate -> next_design_request -> Design
```

### 4.1 Metric Registry

The Metric Registry is the only source of variables available to the compiler.
Each metric definition contains:

- stable metric id and display label;
- scalar data type;
- physical unit and dimensional signature;
- producer agent/tool and source field path;
- valid range and domain restrictions;
- maximize/minimize/target interpretation hints;
- uncertainty field and quality/trust requirements;
- allowed modes and fidelity class;
- provenance requirements;
- missing-value policy options.

Initial registry entries should be generated from implemented Analysis outputs,
not invented for the composer. Examples include compressive strength, apparent
modulus, peak load, energy density, specific energy absorption, strain at peak,
mass, print time, material usage, curve quality, CAE structural score, and
measurement uncertainty.

### 4.2 Objective DSL

The DSL is a typed JSON abstract syntax tree. There is no string `eval` and no
user-provided Python.

Allowed numeric primitives:

- `literal`, `metric`, `reference`;
- `add`, `subtract`, `multiply`, `divide`;
- `weighted_sum`, `ratio`;
- `abs`, `square`, bounded constant `power`, `sqrt`, `log1p`;
- `min`, `max`, `clip`;
- `target_deviation`, `hinge_penalty`, `piecewise_penalty`;
- `normalize` using `fixed_range`, `min_max`, `robust_zscore`, or a recorded
  reference population;
- bounded scalar aggregation over repeated observations using `mean`, `median`,
  `min`, `max`, or a declared quantile.

Allowed Boolean primitives for hard constraints:

- `equal`, `not_equal`, `less`, `less_equal`, `greater`, `greater_equal`;
- `all`, `any`, `not`;
- metric quality/trust predicates.

Raw force-displacement arrays are not manipulated by the objective DSL. Analysis
first converts them to registered scalar metrics with its existing evidence and
quality pipeline.

### 4.3 Static Validator

Validation rejects a draft when any of the following is true:

- unknown metric or operator;
- incompatible units for addition, comparison, or target deviation;
- non-dimensionless logarithm or invalid root/power domain;
- possible zero denominator without an explicit epsilon policy;
- unbounded or non-finite literal;
- unsupported aggregation or missing source population;
- metric unavailable in the requested experiment mode;
- circular reference, excessive AST depth, or excessive node count;
- empty objective expression;
- constraint that cannot return a Boolean value;
- objective direction inconsistent with its final scalar contract.

Normalized values are dimensionless. Multiplication and division preserve a
derived dimensional signature so unit errors remain detectable.

### 4.4 Data-Readiness and Preview

Preview evaluates the draft against bounded historical observations selected by
the operator or retrieved by Knowledge. It reports:

- usable, missing, rejected, and fidelity-separated row counts;
- score distribution and feasible ratio;
- per-term contribution distribution;
- sensitivity to each input metric and each configurable constant;
- correlations and dominant-term warnings;
- NaN/Inf/division/domain failures;
- ranking stability under metric uncertainty;
- comparison with the currently active objective when one exists;
- exact observation and provenance references used by the preview.

Preview does not activate the objective. Insufficient data is displayed as an
explicit readiness failure rather than replaced by synthetic values.

### 4.5 Deterministic Evaluator

The evaluator receives an immutable objective spec plus one normalized metric
record and returns `objective_evaluation.v1`:

```json
{
  "schema": "objective_evaluation.v1",
  "objective_id": "objective-generated-001",
  "objective_version": 1,
  "objective_hash": "sha256:...",
  "observation_id": "observation:...",
  "score": 0.731,
  "direction": "maximize",
  "feasible": true,
  "constraint_results": [],
  "term_contributions": [],
  "uncertainty": 0.08,
  "metric_refs": [],
  "provenance_refs": []
}
```

The evaluator uses explicit decimal/float bounds and rejects non-finite output.
It records enough term-level detail to reproduce the score without an LLM.

## 5. Objective Spec Contract

`objective_spec.v1` contains:

- objective id, version, content hash, lifecycle status;
- research intent and operator-facing description;
- direction: maximize or minimize;
- typed expression AST;
- separate hard-constraint AST list;
- missing-value and uncertainty policies;
- preview dataset/query references;
- Metric Registry version;
- compiler prompt-contract version and model snapshot;
- creation, validation, approval, and activation identities/timestamps;
- parent objective reference when revised;
- run binding and activation scope.

Target objectives are represented using a target-deviation expression and a
maximize/minimize final direction. The evaluator always emits a scalar score so
the existing BO contract remains compatible.

## 6. Lifecycle and Persistence

Lifecycle:

```text
draft -> validated -> previewed -> approved -> active -> retired
             |            |
             +-> rejected +-> revision_required
```

Rules:

- drafts are mutable only by creating a new draft revision;
- approved and active versions are immutable;
- activation binds objective id/version/hash to a run or objective scope;
- changing an active formula requires a new version and affects only a later
  run;
- retiring a version does not delete its evaluations or BO observations;
- replay always resolves the historical objective hash, not the newest version.

Proposed storage:

```text
memory/objectives/registry/metrics.v1.json
memory/objectives/specs/<objective_id>/<version>.json
memory/objectives/decisions.jsonl
memory/objectives/active_bindings.json
memory/objectives/evaluations/<objective_id>.jsonl
runs/<run_id>/objective/objective_spec.json
runs/<run_id>/objective/objective_preview.json
runs/<run_id>/objective/objective_evaluations.jsonl
```

Writes use atomic replacement for mutable indexes and append-only JSONL for
decisions/evaluations. Objective hash uses canonical JSON serialization.

## 7. LLM Tool Contract

The LLM may call:

- `objective.metrics.list`: inspect available metrics and units;
- `objective.metrics.describe`: inspect one metric contract;
- `objective.compose`: generate a draft spec from research intent;
- `objective.validate`: run deterministic schema/unit/domain checks;
- `objective.preview`: evaluate bounded historical data;
- `objective.revise`: create a new draft revision from validator/operator input;
- `objective.approve`: record operator approval, not model self-approval;
- `objective.activate`: bind an approved immutable version to a future run;
- `objective.evaluate`: run deterministic evaluation;
- `objective.compare`: compare versioned objectives on the same observations;
- `objective.status`: inspect lifecycle and active binding.

The tool layer rejects arbitrary code, arbitrary field paths, unregistered
metrics, and activation without approval. LLM prose is advisory and stored
separately from the compiled AST.

## 8. Agent and Runtime Integration

### 8.1 Orchestrator

The Orchestrator obtains research intent and requests composition when no valid
objective is bound. It presents validation/preview results and waits for
approval. It stores only an objective reference plus compact display fields in
`current_experiment_objective`; the immutable spec remains authoritative.

### 8.2 Analysis Agent

Analysis continues to produce physical metrics and uncertainty. Its fixed
keyword/weight `_objective_score` path becomes a legacy compatibility path. When
an objective reference is active, Analysis calls the deterministic evaluator
and emits the resulting score, feasibility, contribution trace, and hash.

### 8.3 Knowledge Agent

Knowledge stores objective specs, decisions, evaluations, provenance, and links
between objective version, observation, specimen, analysis artifact, BO model,
and resulting design. Knowledge retrieval supplies bounded comparable
observations to preview and BO; it does not alter the formula.

### 8.4 BO Agent

BO consumes only observations with a matching objective hash. In live mode it
must not silently substitute `_candidate_proxy` for a missing measured score.
Test/virtual proxy observations remain allowed only when explicitly labeled as
synthetic fidelity and cannot be reported as live evidence.

BO receives:

- scalar score and direction;
- feasible flag and constraint outcomes;
- objective uncertainty;
- fidelity/trust and provenance;
- candidate parameters and observation id.

The next candidate remains advisory and passes through Design manufacturability
validation and Guardian/device gates.

## 9. GUI Design

The BO Workspace gains an Objective Compiler section, not a template picker.
It contains:

- research-intent editor and current objective binding;
- available Metric Registry browser;
- readable equation tree and unit annotations;
- validation results;
- preview score distribution, term contributions, sensitivity, feasible ratio,
  and uncertainty stability;
- version diff and provenance;
- Revise, Validate, Preview, Approve, and Activate controls.

Live GUI BO Report shows only the active objective name/version/hash, equation
summary, feasibility, latest score/contributions, and preview/readiness status.
Detailed composition remains in the BO Workspace. Generated objectives and
validation failures remain visible after refresh and server restart.

## 10. Error Handling

- LLM unavailable with no active spec: composition is unavailable and BO is
  blocked; no default formula is fabricated.
- LLM unavailable with an active spec: deterministic evaluation continues.
- metric missing or quality gate failed: evaluation is infeasible or blocked
  according to the declared policy; no zero fill unless explicitly declared and
  validated.
- objective hash/version mismatch: reject observation ingestion with a conflict.
- preview data unavailable: keep the draft and report readiness failure.
- numerical/domain failure: preserve the evaluation attempt as evidence and do
  not send it to the surrogate.
- Knowledge/Neo4j unavailable: file-backed objective decision/evaluation records
  remain authoritative and graph synchronization may recover later.

None of these failures should start, stop, or control physical hardware.

## 11. Verification Strategy

### Unit

- DSL parse and canonical hash stability;
- operator allowlist and AST bounds;
- unit/type/domain inference;
- divide-by-zero and non-finite rejection;
- nonlinear, target, piecewise penalty, and constraint evaluation;
- deterministic term contribution and uncertainty output;
- immutable lifecycle and revision behavior.

### Integration

- LLM tool output cannot reference unknown metrics or code;
- preview uses exact bounded Knowledge observations;
- approved spec binds only to a future/not-started run;
- Analysis emits the same score for the same spec and metrics in test/replay;
- Knowledge persists objective lineage and evaluation provenance;
- BO rejects mismatched hashes and unmeasured live proxy scores;
- server restart restores draft, approval, active binding, and evaluations.

### GUI

- Metric browser, equation tree, unit validation, preview, diff, and approval
  controls fit 1920 x 1080 without overlap;
- invalid drafts cannot activate;
- objective state survives refresh;
- Live GUI compact card matches the active binding and latest evaluation.

### End-to-end acceptance

1. Describe a compression-performance research goal in natural language.
2. Compose a nonlinear objective from registered strength, SEA, mass, and print
   time metrics without selecting a template.
3. Reject one intentionally invalid unit expression.
4. Preview the corrected objective over existing observations.
5. Approve and bind the immutable version to a new test run.
6. Produce Analysis metrics and reproduce the deterministic score from the saved
   spec without an LLM.
7. Persist the evaluation through Knowledge and update BO with matching hash,
   feasibility, uncertainty, and provenance.
8. Emit a next-design request and confirm Design validation remains authoritative.
9. Restart the server and reproduce the objective binding and score.
10. Unload the LLM and confirm active-objective evaluation still works.

## 12. Non-goals

- Executing LLM-generated Python or arbitrary expressions.
- Replacing Analysis metric extraction or raw signal processing.
- Encoding physical safety as a soft scalar reward.
- Letting the LLM self-approve or change an active objective.
- Claiming synthetic proxy observations as live experimental evidence.
- Implementing full multi-objective Pareto BO in the first compiler delivery.

## 13. Completion Criteria

The design is complete when a researcher can describe an objective in natural
language, the LLM can compile it from registered metrics into a validated
nonlinear DSL, an operator can preview and approve it, Analysis can evaluate it
deterministically without the LLM, Knowledge can preserve complete lineage, and
BO can consume only matching, feasible, provenance-backed observations.
