# BoTorch + LHS Closed-Loop BO Design

## Purpose

Replace the current default `lightweight_pool` / candidate-pool scoring path with a real sequential BoTorch optimization backend while preserving the existing BO Agent, experiment API, LangGraph handoff, Guardian constraints, and Live GUI contracts.

The operator sees one BO Agent. Internally, the BO Agent delegates numeric fitting and proposal generation to one `BoTorchBackend`; surrogate and acquisition logic do not become separate agents.

## Current-State Finding

The existing `botorch_optional` path fits `SingleTaskGP` and scores a pre-generated grid candidate pool. It does not use `optimize_acqf` or `optimize_acqf_mixed`. The current defaults in `agents/bo_agent.py`, `app/main.py`, `experiments/benchmark.py`, and the BO GUI select `lightweight_pool`.

## Runtime Contract

### Backend names

- `botorch`: default and production numeric backend.
- `lightweight_pool`: explicit operator-selected comparison/debug backend only.
- `botorch_optional`: accepted as a legacy input alias and normalized to `botorch`.

BoTorch errors do not silently switch to `lightweight_pool`. A failed import, fit, or acquisition optimization returns a typed BO failure with diagnostics. This prevents a run configured for GPR from appearing successful while using heuristic scores.

### Sequential closed loop

One physical or virtual experiment result enters the BO state per closed-loop cycle.

1. Analysis Agent produces the objective score, uncertainty, fidelity, and evaluated parameters.
2. Knowledge Agent supplies prior compatible observations and provenance.
3. BO Agent filters observations against the active parameter-space schema and objective identity.
4. When measured/accepted observations are fewer than the initial-design target, BO Agent returns the next unobserved LHS point.
5. Otherwise, `BoTorchBackend` fits the GP and optimizes the configured acquisition function for one next point.
6. Manufacturing projection and Guardian validation run before Design Agent receives the proposal.
7. The next cycle adds the new measured result and repeats.

The BO Agent must not fabricate future physical observations to fill its budget. The BO Workspace benchmark may evaluate a complete synthetic sequence because it is explicitly a non-hardware comparison workflow.

## Initial Design

- Default sampler: `latin_hypercube`.
- Default count: `max(2 * active_continuous_dimension_count, 8)`.
- Explicit `initial_design_size` overrides the automatic count.
- Existing compatible observations count toward the initial-design requirement.
- LHS is deterministic for a configured `random_seed`.
- Duplicate points are removed using normalized parameter signatures.
- Live, Test, and Virtual modes use the same LHS ordering and state transition.
- `resume` uses persisted evaluated signatures and does not restart LHS.

`scipy.stats.qmc.LatinHypercube` generates the unit-cube design. The parameter codec decodes each unit value into the declared continuous, discrete, categorical, boolean, or fixed domain.

## Parameter Codec

The backend owns a stable ordered parameter schema.

- Continuous range: optimized in normalized `[0, 1]` space.
- Numeric discrete choices such as `orientation_deg`: represented by enumerated fixed-feature combinations for `optimize_acqf_mixed`.
- Categorical and boolean choices: enumerated or fixed; never represented through Python hash values.
- Single-value dimensions: fixed and excluded from GP input dimensions.
- Manufacturing locks such as `cell_size_mm`: applied before fitting/proposal and preserved in decoded output.

The codec produces reversible `encode(parameters)` and `decode(normalized_vector, fixed_features)` operations. All persisted observations include schema hash and encoded signature.

## GPR and Acquisition

- Model: `botorch.models.SingleTaskGP`.
- Input transform: normalized dimensions supplied by the codec.
- Outcome transform: `Standardize(m=1)`.
- Known observation uncertainty: when finite positive uncertainty is available, pass variance through `train_Yvar`; otherwise use inferred homoskedastic noise.
- Objective direction: support maximize and minimize without rewriting stored measurements.
- Default acquisition: `LogExpectedImprovement`, exposed to the user as Expected Improvement.
- Other supported choices: `UpperConfidenceBound`, `ProbabilityOfImprovement`, uncertainty sampling, exploitation, and exploration.
- Optimizer: `optimize_acqf` for continuous-only spaces and `optimize_acqf_mixed` when discrete combinations exist.
- Default optimizer controls: `q=1`, `num_restarts=12`, `raw_samples=256`, configurable timeout.
- Repeated or Guardian-invalid proposals are rejected and re-optimized with bounded retries; exhaustion produces a typed failure.

## Result Schema

Every BO step records:

- requested and active backend;
- initial sampler and initial-design progress;
- model class, training count, objective direction, and noise mode;
- acquisition name and optimizer controls;
- selected decoded parameters and normalized vector;
- acquisition value, posterior mean, posterior standard deviation, and 95% confidence interval;
- evaluated observations with provenance and fidelity;
- parameter-space schema hash;
- warnings and typed failure details;
- next Design Agent request.

The existing `bo_visualization.v1` contract remains compatible and gains explicit `initial_design`, `backend`, and `optimizer` metadata.

## Visualization

All surfaces use the same posterior data:

- black or blue GP posterior mean line;
- light gray/blue 95% confidence band;
- orange LHS/observed points;
- red next acquisition point;
- optional true/synthetic benchmark function only in benchmark mode;
- separate acquisition subplot or overlay where space permits.

Matplotlib writes publication-style PNG, SVG, and CSV artifacts. The Live GUI shared renderer consumes the same arrays and matches that visual language without embedding a new plotting runtime.

The graph appears in:

- BO Workspace;
- Live GUI BO Agent report;
- Test/Virtual closed-loop reports;
- Runtime artifacts and report exports.

## Persistence and Resume

Persist under the active run:

- `runtime/bo/observations.json`;
- `runtime/bo/initial_design.json`;
- `runtime/bo/model_state.pt` when a GP is fitted;
- `runtime/bo/bo_step_<n>.json`;
- posterior PNG/SVG/CSV artifacts.

The source of truth is the typed observation and step JSON. A GP may be refit deterministically from those records; loading a model state is an optimization, not the only recovery path.

## GUI

BO Workspace exposes:

- Numeric backend, default `BoTorch`;
- Initial sampler, default `Latin Hypercube`;
- Initial design size with `Auto` default;
- Acquisition function;
- optimizer restarts, raw samples, and timeout in advanced settings;
- requested/active backend status;
- initial-design progress;
- fit/acquisition failures without silent fallback.

Saved legacy `botorch_optional` settings migrate to `botorch`. Saved `lightweight_pool` remains explicit and is not overwritten.

## Test Strategy

- Unit tests for codec round-trips, LHS determinism, duplicate exclusion, GP fitting, acquisition selection, minimize/maximize, noise handling, and strict failure behavior.
- Integration tests for BO Agent, experiment benchmark, GUI config migration, visualization payloads, and artifacts.
- Closed-loop tests proving Live/Test/Virtual consume one observation and emit one next point per cycle.
- Browser audit proving BO Workspace and Live GUI render posterior mean, confidence band, observations, and next point.
- Runtime verification requires `backend_requested=botorch`, `backend_active=botorch`, and no backend fallback warning.

## Non-Goals

- No separate Surrogate Agent or Acquisition Agent.
- No automatic hardware action inside the BO numeric backend.
- No silent downgrade to heuristic optimization.
- No replacement of Objective, Analysis, Knowledge, Guardian, or Design Agent contracts.
