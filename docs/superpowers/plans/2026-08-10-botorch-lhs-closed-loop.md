# BoTorch + LHS Closed-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BoTorch the real default BO backend, use LHS for sequential initial design, optimize acquisition functions over the declared mixed parameter space, and expose the resulting posterior consistently across BO Workspace and closed-loop Live GUI.

**Architecture:** `BOAgent` remains the single agent-facing entry point and calls a focused `BoTorchBackend`. A parameter codec handles continuous, discrete, categorical, boolean, and fixed domains; a persisted sequential state chooses either the next LHS point or one BoTorch acquisition-optimized point. Existing Objective, Analysis, Knowledge, Guardian, Design, LangGraph, and visualization contracts remain authoritative.

**Tech Stack:** Python 3.12, PyTorch, BoTorch 0.18+, GPyTorch, SciPy QMC, FastAPI, vanilla JavaScript, Matplotlib, pytest, Node tests, raw WebDriver browser audit.

## Global Constraints

- Default numeric backend is `botorch`; `botorch_optional` is a legacy alias and `lightweight_pool` runs only when explicitly selected.
- A BoTorch failure is typed and visible; it never silently falls back to `lightweight_pool`.
- Live/Test/Virtual closed loops consume one real or virtual observation and emit one proposal per cycle.
- Default initial sampler is `latin_hypercube`; automatic initial count is `max(2 * active_continuous_dimension_count, 8)`.
- Default acquisition is `LogExpectedImprovement`, displayed as Expected Improvement.
- Existing MCP tool names, LangGraph stage names, and agent handoff schemas remain compatible.
- Existing unrelated dirty worktree changes must not be reverted or included in task-specific commits.

---

### Task 1: Mixed Parameter Codec and LHS Initial Design

**Files:**
- Create: `learning/bo_parameter_space.py`
- Create: `tests/unit/test_bo_parameter_space.py`
- Modify: `requirements.txt`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `BOParameterSpace.from_mapping(mapping)`, `encode(parameters)`, `decode(vector, fixed_features=None)`, `lhs_points(count, seed, excluded_signatures=())`, `continuous_dimension_count`, `schema_hash`, and `mixed_fixed_features()`.
- Consumes: repository parameter mappings where two numeric values denote a continuous bound and longer lists denote discrete choices.

- [ ] **Step 1: Write failing codec and LHS tests**

Test deterministic LHS generation, reversible encode/decode, fixed `cell_size_mm`, discrete `orientation_deg`, categorical `geometry_type`, boolean settings, automatic count, and duplicate exclusion.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `.venv/bin/pytest -q tests/unit/test_bo_parameter_space.py`

Expected: collection or assertion failure because `learning.bo_parameter_space` does not exist.

- [ ] **Step 3: Implement the minimal codec and LHS generator**

Use `scipy.stats.qmc.LatinHypercube(d=continuous_dimension_count, seed=seed)` and deterministic decode rules. Use canonical JSON plus SHA-256 for `schema_hash`; do not use Python `hash()` for categorical values.

- [ ] **Step 4: Run focused tests and dependency checks**

Run: `.venv/bin/pytest -q tests/unit/test_bo_parameter_space.py && .venv/bin/python -c "from scipy.stats import qmc; print(qmc.LatinHypercube)"`

Expected: PASS and a resolvable `LatinHypercube` class.

### Task 2: Real BoTorch Backend

**Files:**
- Replace implementation: `learning/botorch_backend.py`
- Create: `tests/unit/test_botorch_backend.py`

**Interfaces:**
- Consumes: `BOParameterSpace`, accepted observations, acquisition settings, objective direction, optimizer controls, and exclusion signatures.
- Produces: `BoTorchProposal` serialized by `to_dict()` with `backend_active`, `model`, `noise_mode`, `candidate`, `posterior`, `acquisition`, `optimizer`, and plot projection arrays.
- Preserves: `is_available()` and a compatibility `score_candidate_pool()` wrapper for explicit legacy tests only.

- [ ] **Step 1: Write failing real-backend tests**

Tests must assert `SingleTaskGP`, `optimize_acqf`/`optimize_acqf_mixed` proposal provenance, finite posterior values, deterministic seed behavior, maximize/minimize direction, `train_Yvar` handling, discrete orientation validity, and typed failure without fallback.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/bin/pytest -q tests/unit/test_botorch_backend.py`

Expected: FAIL because the current backend only scores an existing candidate pool.

- [ ] **Step 3: Implement GP fit and acquisition optimization**

Fit `SingleTaskGP` with `Standardize(m=1)`. Use `LogExpectedImprovement`, `UpperConfidenceBound`, or `ProbabilityOfImprovement`. Call `optimize_acqf` for continuous-only spaces and `optimize_acqf_mixed` for enumerated discrete combinations with `q=1`, `num_restarts=12`, and `raw_samples=256` defaults.

- [ ] **Step 4: Run focused tests and a real local backend smoke test**

Run: `.venv/bin/pytest -q tests/unit/test_botorch_backend.py`

Then execute one local proposal and assert `backend_active == "botorch"`, finite acquisition, and a decoded candidate within all bounds.

### Task 3: Sequential BO Runtime and Strict Backend Policy

**Files:**
- Modify: `experiments/benchmark.py`
- Modify: `agents/bo_agent.py`
- Modify: `tests/unit/test_experiment_runtime.py`
- Modify: `tests/unit/test_bo_agent.py`

**Interfaces:**
- Consumes: Analysis/Knowledge prior observations and `BoTorchBackend`.
- Produces: one `phase=initial_design` LHS point or one `phase=acquisition` BoTorch point per BO Agent call, plus existing `next_design_request` and `experiment_spec_update` contracts.

- [ ] **Step 1: Add failing sequential-runtime tests**

Assert that insufficient observations yield the next LHS point, sufficient observations yield one BoTorch proposal, repeated calls exclude observed signatures, resume preserves LHS progress, and BoTorch exceptions fail rather than switch backend.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv/bin/pytest -q tests/unit/test_experiment_runtime.py tests/unit/test_bo_agent.py`

- [ ] **Step 3: Integrate the sequential state machine**

Keep complete random/grid/BO synthetic comparisons in `experiment.benchmark`, but make closed-loop `BOAgent` proposal generation observation-driven. Normalize `botorch_optional` to `botorch`; preserve explicit `lightweight_pool` behavior.

- [ ] **Step 4: Verify BO Agent handoff contracts**

Run focused tests and inspect one `BOAgent.run_with_settings()` result for exactly one next proposal, backend identity, initial-design progress, and Design Agent-compatible parameters.

### Task 4: Defaults, API, Saved Settings, and GUI Controls

**Files:**
- Modify: `app/main.py`
- Modify: `web/templates/bo.html`
- Modify: `web/static/bo.js`
- Modify: `tests/integration/test_bo_gui_api.py`
- Modify: `tests/js/bo_workspace.test.js` if present; otherwise create it.

**Interfaces:**
- Produces API fields: `bo_backend`, `initial_sampler`, `initial_design_size`, `num_restarts`, `raw_samples`, `optimizer_timeout_s`.
- Migrates saved `botorch_optional` to `botorch` while preserving explicit `lightweight_pool`.

- [ ] **Step 1: Write failing API and JavaScript tests**

Assert BoTorch defaults, legacy migration, LHS Auto display, optimizer advanced controls, and requested/active backend status.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/bin/pytest -q tests/integration/test_bo_gui_api.py` and the repository Node test command for the BO workspace.

- [ ] **Step 3: Implement defaults and controls**

Use `botorch` as the visible default. Keep `lightweight_pool` selectable. Do not label the production path optional.

- [ ] **Step 4: Verify saved settings across server refresh**

Save a BoTorch/LHS configuration, fetch `/api/bo/config`, and assert the same normalized values return.

### Task 5: Posterior Visualization and Artifacts

**Files:**
- Modify: `experiments/bo_visualization.py`
- Modify: `reporting/bo_visualization_artifacts.py`
- Modify: `web/static/bo_visualization.js`
- Modify: `web/static/styles.css`
- Modify: `tests/unit/test_bo_visualization.py`
- Modify: `tests/unit/test_bo_visualization_artifacts.py`
- Modify: `tests/unit/test_bo_visualization_js.py`

**Interfaces:**
- Consumes: actual BoTorch posterior/acquisition projection arrays.
- Produces: `bo_visualization.v1`, Matplotlib PNG/SVG/CSV, and matching browser SVG.

- [ ] **Step 1: Write failing visual-contract tests**

Assert posterior mean, 95% CI, LHS observations, later BO observations, next point, backend `botorch`, and acquisition metadata are preserved.

- [ ] **Step 2: Run tests and confirm RED**

Run the three visualization unit suites.

- [ ] **Step 3: Implement publication-style artifacts and shared browser styling**

Use a white plotting surface, mean line, translucent 95% band, orange observations, red next point, readable axes/legend, and no synthetic true-function line outside benchmark mode.

- [ ] **Step 4: Run visual tests and inspect generated PNG**

Generate a representative artifact, open it with the image viewer, and check labels, clipping, and legend placement at 1920x1080 Live GUI scale.

### Task 6: LangGraph Closed-Loop Integration

**Files:**
- Modify: `orchestrator/langgraph_runtime.py`
- Modify: `app/controller.py`
- Modify: `tests/unit/test_langgraph_runtime.py`
- Modify: `tests/unit/test_controller_planning.py`

**Interfaces:**
- Consumes: one BO Agent next-point result per cycle.
- Produces: persisted BO state, visualization metadata, Knowledge/Guardian provenance, and the existing BO-to-Design handoff.

- [ ] **Step 1: Write failing Live/Test/Virtual loop tests**

Assert each cycle consumes one completed observation, emits one proposal, preserves LHS progress, transitions BO to Guardian and then Design only after approval, and never reports `lightweight_pool` when `botorch` was requested.

- [ ] **Step 2: Run tests and confirm RED**

Run the focused LangGraph/controller tests.

- [ ] **Step 3: Integrate persisted BO state and strict backend gates**

Store compact latest visualization plus bounded step summaries. Keep model/training artifacts under the active run and avoid repeated in-memory posterior histories.

- [ ] **Step 4: Run five-cycle virtual closed-loop verification**

Use the normal Live GUI input path for `테스트 모드, 가상 브릿지`. Verify five cycles, sequential LHS/BoTorch phase progression, BO-to-Guardian handoff, and no blocked/error events.

### Task 7: Documentation and End-to-End Verification

**Files:**
- Modify: `docs/agents/bo_agent_runtime_guideline.txt`
- Modify: `docs/gui/gui.md`
- Modify: `docs/runtime/current_code_snapshot.md`
- Modify: `requirements-bo.txt`
- Modify: install/requirements documentation that lists BO dependencies.

**Interfaces:**
- Documents exact defaults, strict failure policy, LHS behavior, resume semantics, GUI controls, artifact paths, and CLI/API verification commands.

- [ ] **Step 1: Update documentation from verified runtime behavior**

Remove statements that call `lightweight_pool` the default or claim BoTorch only scores a candidate pool.

- [ ] **Step 2: Run requirement and documentation searches**

Run: `rg -n 'botorch_optional|lightweight_pool.*Default|Does not run.*optimize_acqf' docs requirements*.txt pyproject.toml`

Expected: only migration/explicit compatibility references remain.

- [ ] **Step 3: Run the complete focused regression matrix**

Run all BO, Objective, LangGraph, controller, visualization, API, and JavaScript suites. Record unrelated pre-existing failures separately; do not mask new failures.

- [ ] **Step 4: Perform live API and browser audit**

Verify `/api/bo/config`, `/api/bo/run`, the BO Workspace plot, and the Live GUI BO Agent report. Required evidence: `backend_requested=botorch`, `backend_active=botorch`, posterior SVG present, no waiting placeholder, and publication artifacts created.

- [ ] **Step 5: Review diff scope**

Run `git diff --check` and inspect only BO-related files. Do not revert or commit unrelated user changes.
