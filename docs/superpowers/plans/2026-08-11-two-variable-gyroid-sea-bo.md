# Two-Variable Gyroid SEA BO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a two-variable Gyroid optimization loop using feasible `a=L/N` cell sizes, continuous relative density, LHS initialization, ARD Matérn 5/2 GPR with noise, EI, and measured SEA.

**Architecture:** `BOParameterSpace` owns feasible mixed-space encoding and LHS. `botorch_backend` owns explicit GP construction and EI optimization. BO Agent owns initialization and proposal state, while Design and Analysis preserve requested/realized parameters and measured SEA. Existing BO visualization contracts gain two-variable metadata and transparent rendering without introducing another plotting runtime.

**Tech Stack:** Python 3.12, scipy QMC, PyTorch, GPyTorch, BoTorch, Matplotlib, FastAPI, existing Live GUI JavaScript.

## Global Constraints

- Active variables are exactly `cell_size_mm` and `relative_density`.
- `cell_size_mm` is one of `{5.0,6.0,7.5,10.0}` derived from `L=30 mm` and `N={6,5,4,3}`.
- `relative_density` is continuous on `[0.20,0.48]`.
- Inputs are normalized to `[0,1]^2`.
- Initial sampler is balanced Latin Hypercube with eight valid observations.
- GP covariance is ARD Matérn 5/2 plus Gaussian observation noise.
- Acquisition is Expected Improvement and objective direction is maximize.
- Objective data is measured `specific_energy_absorption_J_per_g` in `J/g`.
- Plot figure and axes backgrounds are transparent.
- Existing MCP and agent handoff protocol fields remain compatible.

---

### Task 1: Two-Variable Parameter Contract

**Files:**
- Modify: `learning/bo_parameter_space.py`
- Modify: `agents/bo_agent.py`
- Test: `tests/unit/test_bo_parameter_space.py`
- Test: `tests/unit/test_bo_agent.py`

**Interfaces:**
- Consumes: existing `BOParameterSpace.from_mapping()` and `lhs_points()`.
- Produces: a two-variable default mapping and LHS points containing only valid decoded cell sizes.

- [x] Write failing tests asserting exact feasible cell sizes, `[0,1]` round trips, eight balanced initial points, and rejection of invalid values.
- [x] Run the focused tests and confirm failures identify the old multi-variable defaults or unbalanced mixed LHS behavior.
- [x] Implement the minimal parameter contract and balanced mixed LHS behavior.
- [x] Run focused tests and existing BO parameter/agent tests.

### Task 2: SEA Observation Contract

**Files:**
- Modify: `agents/bo_agent.py`
- Modify: `agents/analysis_agent.py` only if the existing metric handoff lacks the authoritative field
- Modify: `objectives/presets.py`
- Test: `tests/unit/test_bo_agent.py`
- Test: `tests/unit/test_analysis_agent.py`
- Test: `tests/unit/test_objective_presets.py`

**Interfaces:**
- Consumes: `latest_analysis.utm_metrics.specific_energy_absorption_J_per_g` and persisted evaluations.
- Produces: BO observations whose `score` is physical SEA in `J/g` with provenance and uncertainty.

- [x] Write failing tests proving composite `objective_score` cannot override available SEA.
- [x] Run focused tests and confirm the old score selection fails.
- [x] Implement strict SEA extraction and validation.
- [x] Run focused objective, Analysis, and BO Agent tests.

### Task 3: Explicit GPR And EI

**Files:**
- Modify: `learning/botorch_backend.py`
- Test: `tests/unit/test_botorch_backend.py`

**Interfaces:**
- Consumes: normalized two-dimensional observations.
- Produces: `SingleTaskGP` proposal metadata identifying `MaternKernel(nu=2.5, ard_num_dims=2)`, noise mode, and `LogExpectedImprovement`.

- [x] Write failing tests for kernel class, `nu`, ARD dimensionality, noise mode, and feasible EI proposal decoding.
- [x] Run tests and confirm the default model/kernel metadata fails the new contract.
- [x] Add explicit scaled ARD Matérn 5/2 covariance and retain inferred/fixed noise modes.
- [x] Enumerate discrete cell-size fixed features while optimizing continuous relative density.
- [x] Run backend tests with real BoTorch.

### Task 4: Design Handoff And Density Realization

**Files:**
- Modify: `agents/design_agent.py`
- Modify: `mcp_tools/tpms_geometry.py`
- Modify: `mcp_tools/mock_tools.py`
- Test: `tests/unit/test_design_agent.py`
- Add or modify: focused TPMS geometry tests under `tests/unit/`

**Interfaces:**
- Consumes: `requested_parameters={cell_size_mm,relative_density}`.
- Produces: a Gyroid specimen with requested/realized parameter fields and a solved `tpms_thickness` targeting relative density.

- [x] Write failing tests that BO cell size is not ignored, unrelated shape variables remain fixed, and solved density stays within the declared numerical tolerance.
- [x] Run focused tests and confirm current constraint locking/thickness derivation fails.
- [x] Implement density-to-level-set inversion and requested/realized metadata.
- [x] Run Design and TPMS geometry tests.

### Task 5: Transparent Two-Variable BO Card

**Files:**
- Modify: `experiments/bo_visualization.py`
- Modify: `reporting/bo_visualization_artifacts.py`
- Modify: `web/static/bo_visualization.js`
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Test: `tests/unit/test_bo_visualization.py`
- Test: `tests/unit/test_bo_visualization_artifacts.py`
- Test: `tests/unit/test_bo_visualization_js.py`
- Test: `tests/unit/test_planning_bo_visualization_js.py`

**Interfaces:**
- Consumes: existing `bo_visualization.v1` plus two-variable model metadata.
- Produces: a separate two-variable LHS input-space plot and an output-only scalar-score posterior/EI plot in BO Workspace and Live GUI. The posterior/EI plot must not render input names, values, strata, slices, facets, or parameter tooltips.

- [x] Write failing tests for transparent figure/axes outputs and visible two-variable metadata.
- [x] Run focused tests and confirm old opaque or generic output fails.
- [x] Implement transparent Matplotlib and browser rendering while preserving card sizing.
- [x] Run visualization and JavaScript tests.

### Task 6: Full-Path Verification And Documentation

**Files:**
- Modify: `docs/agents/bo_agent.md`
- Modify: `docs/agents/bo_agent_runtime_guideline.txt`
- Modify: `docs/runtime/current_code_snapshot.md`
- Test: `tests/integration/test_bo_gui_api.py`
- Test: relevant Live GUI browser audit

**Interfaces:**
- Consumes: all prior task contracts.
- Produces: verified API, closed-loop, GUI, and documented two-variable BO behavior.

- [x] Add integration assertions for eight LHS points followed by GPR/EI and SEA provenance.
- [x] Run unit and integration BO suites.
- [x] Run a five-cycle compatibility smoke test and a BO-only run long enough to cross the eight-point initialization boundary.
- [x] Capture the BO card in the browser and inspect transparency, labels, clipping, and point rendering.
- [x] Update user-facing and runtime documentation with the verified behavior and limitations.
