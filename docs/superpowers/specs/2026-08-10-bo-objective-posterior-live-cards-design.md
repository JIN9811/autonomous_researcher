---
doc_type: design
subtype: feature
status: approved
authority: proposal
audience:
  - researcher
  - operator
  - developer
  - maintainer
scope:
  - bo_agent
  - bo_workspace
  - live_gui
  - artifacts
summary: Shared objective-equation and live Bayesian posterior visualization for the BO Workspace and Live GUI.
decision_status: approved
related_docs:
  - docs/superpowers/specs/2026-08-10-manual-objective-builder-design.md
  - docs/superpowers/specs/2026-08-09-llm-objective-compiler-design.md
  - docs/agents/bo_agent.md
supersedes: []
---

# BO Objective And Posterior Live Cards Design

## 1. Purpose

The BO Workspace and the Live GUI BO Agent report must show the same active
objective and the same Bayesian optimization state. The operator needs to see
what equation is being optimized, what the surrogate currently predicts, how
uncertain that prediction is, which points have been measured, and which point
will be evaluated next.

The current trace uses candidate-pool indexes and scales uncertainty in the
browser for presentation. That view is useful for audit but is not a physical
design-space posterior. This feature replaces browser-derived uncertainty with
a bounded backend projection and adds a selectable one-dimensional posterior
slice while retaining the candidate-index audit view.

## 2. Confirmed Decisions

1. The feature appears in both `/bo` and the Live GUI BO Agent report.
2. Both surfaces consume one shared `bo_visualization.v1` payload.
3. The objective card is derived deterministically from the approved or
   run-bound `objective_spec.v1`; an LLM does not rewrite the equation.
4. The default graph is a one-dimensional posterior slice over a selected
   numeric design variable.
5. The operator can switch to the candidate-pool-index audit view.
6. Non-selected dimensions are fixed at the current best measured design. If
   no measured best exists, the parameter-space midpoint or first categorical
   value is used and disclosed in the payload.
7. The graph shows posterior mean, 95% confidence interval, measured points,
   current best, next selected point, and the acquisition curve.
8. The browser renders the live graph as lightweight SVG using backend values.
9. Only a completed BO step triggers a graph update. Animation-frame polling
   and repeated full-history rendering are prohibited.
10. Completion creates publication-style Matplotlib PNG and SVG figures plus a
    CSV data artifact. Runtime rendering does not depend on Matplotlib.
11. The latest completed plot remains visible until a newer valid step arrives.
    A failed update changes status metadata but does not replace valid evidence.
12. Existing BO execution, objective lifecycle, AgentResult, MCP/tool protocol,
    and downstream Design handoff behavior remain unchanged.

## 3. Selected Architecture

### 3.1 Shared Projection

Add a focused visualization projector that converts an objective binding,
parameter space, BO step, surrogate result, and selected parameter into a
serializable `bo_visualization.v1` object. The projector performs no candidate
selection and cannot alter BO decisions.

The BO benchmark/agent stores the latest projection in `bo_result.visualization`
and includes it in each BO step event. Both GUIs are read-only consumers of this
projection.

### 3.2 Runtime And Artifact Rendering

Runtime rendering uses a shared browser module so `/bo` and Live GUI have the
same axes, legend, colors, confidence interval, and point semantics. The module
returns SVG markup and does not retain old DOM plots.

After a BO run completes, a separate artifact renderer consumes the same
projection and writes Matplotlib PNG, SVG, and CSV outputs. This hybrid approach
keeps live updates lightweight while preserving reproducible publication
figures.

### 3.3 Rejected Alternatives

- Regenerating a Matplotlib PNG every step was rejected because it adds process,
  memory, I/O, and cache overhead to the live path.
- Keeping the existing candidate-index-only SVG was rejected because the x-axis
  has no direct physical parameter meaning.
- Computing confidence limits independently in each browser was rejected because
  the two surfaces could disagree with the BO backend.

## 4. Data Contract

The shared payload has this shape:

```json
{
  "schema": "bo_visualization.v1",
  "run_id": "run-...",
  "step": 3,
  "generated_at": "2026-08-10T00:00:00Z",
  "objective": {
    "objective_id": "specific-energy-objective",
    "version": 2,
    "hash": "...",
    "name": "Specific energy absorption",
    "direction": "maximize",
    "equation": "specific_energy_absorption",
    "unit": "J/g",
    "constraints": ["relative_density >= 0.20"]
  },
  "view": {
    "mode": "parameter_slice",
    "selected_parameter": "relative_density",
    "x_label": "Relative density",
    "x_unit": "1",
    "fixed_parameters": {
      "cell_size_mm": 5.0,
      "wall_thickness_mm": 1.2
    },
    "fixed_parameter_source": "current_best"
  },
  "posterior": {
    "x": [0.20, 0.22],
    "mean": [0.61, 0.67],
    "std": [0.08, 0.06],
    "lower_95": [0.4532, 0.5524],
    "upper_95": [0.7668, 0.7876]
  },
  "acquisition": {
    "name": "expected_improvement",
    "x": [0.20, 0.22],
    "value": [0.02, 0.05]
  },
  "observations": [
    {"candidate_id": "candidate-001", "x": 0.20, "score": 0.60}
  ],
  "current_best": {"candidate_id": "candidate-001", "x": 0.20, "score": 0.60},
  "next_point": {"candidate_id": "candidate-008", "x": 0.34, "mean": 0.81, "std": 0.11, "acquisition": 0.09},
  "candidate_index_view": {
    "x": [1, 2],
    "mean": [0.61, 0.67],
    "std": [0.08, 0.06],
    "acquisition": [0.02, 0.05],
    "candidate_ids": ["candidate-001", "candidate-002"]
  },
  "backend": {
    "requested": "botorch_optional",
    "active": "botorch_optional",
    "model": "single_task_gp"
  },
  "status": "complete",
  "warnings": []
}
```

All numeric arrays must have equal lengths, contain finite values, and be
ordered by x. `lower_95` and `upper_95` are computed in the backend as
`mean - 1.96 * std` and `mean + 1.96 * std`. The browser must not rescale them.

## 5. One-Dimensional Slice Semantics

The selected parameter must be numeric and registered in the active parameter
space. Selection order is:

1. an operator-selected parameter stored in BO Workspace settings;
2. the parameter changed by the latest selected candidate relative to the
   current best;
3. the numeric parameter with the largest normalized range;
4. the first numeric parameter in stable parameter-space order.

The slice samples 101 evenly spaced x values across the selected parameter's
declared bounds. Other dimensions are fixed using the current best measured
parameters. Missing values use declared midpoints for numeric parameters and
the first declared value for categorical parameters.

When the active backend can evaluate arbitrary posterior points, the projector
uses that posterior directly. When only candidate-pool scores are available,
the payload explicitly sets `backend.model=pool_projection`, samples available
points for the selected parameter, and includes a warning. It must not label a
distance heuristic as a Gaussian-process posterior.

## 6. Objective Equation Card

The card displays:

- objective name and equation;
- maximize or minimize direction;
- metric unit;
- constraints;
- objective id, immutable version, and abbreviated hash;
- lifecycle state and whether the objective is bound to the current run.

`/bo` links the card to the existing Objective Builder selection. Live GUI uses
the run binding only and is read-only. If no objective is bound, the card shows
`Objective not bound` and does not synthesize a fallback equation.

## 7. BO Graph Card

### 7.1 Visual Language

The graph follows a publication-style Matplotlib visual language:

- white plotting area;
- dark axis labels and ticks;
- light gray major grid;
- blue posterior mean line;
- translucent blue 95% confidence band;
- black measured-point markers;
- green current-best marker;
- red next-point marker and vertical guide;
- orange acquisition curve in a vertically aligned lower subplot;
- explicit x-axis parameter name and unit;
- legends that never overlap plotted data.

No decorative gradient, glow, 3D effect, or meaningless KPI is added.

### 7.2 Controls

The card includes:

- view selector: `Parameter Slice` or `Candidate Audit`;
- parameter selector containing numeric parameters only;
- step selector for completed steps;
- `Latest` action;
- PNG, SVG, and CSV artifact links after completion.

The Live GUI keeps these controls compact. The BO Workspace can show fixed
parameter values and backend warnings beside the graph.

## 8. Realtime Flow

1. BO evaluates or receives one observation.
2. The backend updates the surrogate and acquisition values.
3. The projector creates `bo_visualization.v1` for that completed step.
4. The run stores the projection and emits `bo.visualization.updated` with
   `run_id`, `step`, and the projection.
5. The existing Live GUI event stream receives the event and replaces only the
   BO equation/graph card contents.
6. `/bo` subscribes to the same event stream while a matching run is active.
7. A late subscriber loads the latest projection from persisted run state or
   the most recent BO result before subscribing.

Events with another run id, duplicate step, an older step, or an invalid schema
are ignored. A reconnect loads the latest projection once; it does not replay
and render every historical graph.

## 9. Error And Empty States

- No objective: equation card shows an explicit unbound state.
- No BO step: graph shows `Waiting for first BO observation`.
- Unsupported slice backend: candidate audit remains available and the slice
  card shows the backend warning.
- Invalid projection: retain the previous valid graph and show a small stale
  warning.
- Disconnected event stream: retain the graph and mark it `stale`; normal Live
  GUI reconnect behavior attempts recovery.
- Matplotlib artifact failure: runtime SVG remains valid and the artifact error
  is recorded without failing BO candidate selection.

## 10. Persistence And Memory Limits

- Run state persists one projection per completed BO step for audit.
- Each GUI renders one selected step only.
- Historical SVG nodes are replaced, not appended.
- The client retains at most the current projection and a small step index.
- Final PNG/SVG/CSV artifacts are stored under the existing run artifact
  hierarchy and referenced through normal artifact routes.
- No base64 figure data is stored in messages, state snapshots, or events.

## 11. Testing And Acceptance

### 11.1 Backend

- contract validation rejects non-finite or mismatched arrays;
- confidence limits use backend standard deviation without browser scaling;
- parameter selection and fixed-parameter rules are deterministic;
- current best and next point match the BO decision trace;
- pool-only fallback is honestly labeled;
- step events carry the matching run id and monotonically increasing step;
- final PNG, SVG, and CSV artifacts use the same projection values.

### 11.2 BO Workspace

- objective card matches the selected/active objective version;
- parameter and candidate views switch without another BO execution;
- changing the slice parameter requests or selects the correct projection;
- only the latest graph is mounted during live updates;
- reconnect restores the latest completed step.

### 11.3 Live GUI

- BO report uses the same objective equation and projection as `/bo`;
- cards update after each BO step without full report reconstruction;
- selecting another agent stops BO-card-specific rendering work;
- returning to BO restores the latest valid graph;
- refresh during a run restores current data and continues updates.

### 11.4 Browser And Resource QA

- verify at 1920x1080 and a narrow viewport;
- axis labels, legends, equation, and constraints do not clip or overlap;
- repeated step updates do not grow plot-node count or retained base64 data;
- Selenium/browser audit compares `/bo` and Live GUI values from one run;
- existing BO API, objective lifecycle, and closed-loop tests remain passing.

## 12. Documentation

Update the BO Agent, BO Workspace, Live GUI, artifact, and operator tutorial
documentation. Explain that the live plot is browser SVG driven by backend
posterior data, while PNG/SVG/CSV are completion artifacts generated by
Matplotlib.
