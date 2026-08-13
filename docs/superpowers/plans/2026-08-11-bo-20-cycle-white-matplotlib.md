# BO 20-Cycle White Matplotlib Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run both virtual-bridge and installed-printer test workflows for 20 cycles, using eight measured Latin Hypercube observations followed by twelve BoTorch GP/EI iterations, and display the BO result as a white-background Matplotlib figure.

**Architecture:** The controller owns the 20-cycle mission budget and Guardian reads the same constant rather than maintaining a separate five-cycle cap. The existing `bo_visualization.v1` projection remains the numeric contract; `reporting/bo_visualization_artifacts.py` becomes the visual source of truth and the Live GUI displays its PNG artifact instead of independently restyling the same data with JavaScript SVG.

**Tech Stack:** Python 3.12, FastAPI, Matplotlib Agg, BoTorch, Pytest, existing Live GUI JavaScript.

## Global Constraints

- Both virtual bridge and installed printer test routes use 20 cycles.
- Cycles 1 through 8 are valid measured LHS observations.
- Cycles 9 through 20 use `SingleTaskGP` and Expected Improvement.
- Failed, rejected, or proxy-only results do not count as measured LHS observations.
- Matplotlib figure and axes backgrounds are opaque white.
- Posterior mean is black, 95% confidence interval is light gray, observations are blue, and the next point/acquisition are orange.
- Expected Improvement is clipped to a non-negative display range.
- Existing device-control commands, MCP fields, and agent handoff order are unchanged.

---

### Task 1: Twenty-Cycle Mission Contract

**Files:**
- Modify: `app/controller.py`
- Modify: `agents/guardian_agent.py`
- Modify: `app/main.py`
- Modify: `configs/test_modes.yaml`
- Test: `tests/unit/test_controller_planning.py`
- Test: `tests/integration/test_controller_run.py`

**Interfaces:**
- Consumes: test-mode planning payload and bridge route selection.
- Produces: `total_cycles=20`, cycle status `1/20` through `20/20`, and Guardian completion only after cycle 20.

- [ ] Add failing tests for virtual and installed-printer cycle budgets and Guardian cap behavior.
- [ ] Run focused tests and confirm the old five-cycle defaults fail.
- [ ] Replace duplicated five-cycle defaults with the shared 20-cycle contract.
- [ ] Run focused controller, Guardian, and API-state tests.

### Task 2: White Matplotlib Figure Contract

**Files:**
- Modify: `reporting/bo_visualization_artifacts.py`
- Test: `tests/unit/test_bo_visualization_artifacts.py`

**Interfaces:**
- Consumes: validated `bo_visualization.v1` posterior/acquisition arrays.
- Produces: opaque white PNG, SVG, and numeric CSV artifacts with publication-style colors and non-negative EI display bounds.

- [ ] Add failing image/SVG assertions for opaque white backgrounds, required colors, and non-negative acquisition limits.
- [ ] Run the artifact test and confirm transparent rendering fails.
- [ ] Implement the white Matplotlib style and robust axis limits.
- [ ] Run artifact tests and inspect a generated PNG.

### Task 3: Live GUI Matplotlib Artifact Display

**Files:**
- Modify: `orchestrator/langgraph_runtime.py`
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Test: `tests/unit/test_planning_bo_visualization_js.py`
- Test: `tests/ui/bo_objective_compiler_browser_audit.py`

**Interfaces:**
- Consumes: BO report artifact records where `media_type=image/png` and `source=bo_visualization.v1`.
- Produces: one responsive white Matplotlib image in the BO report card, with the JavaScript renderer retained only for pre-artifact LHS progress.

- [ ] Add failing renderer tests proving a PNG artifact is preferred over SVG reconstruction.
- [ ] Run tests and confirm the current JavaScript plot path fails.
- [ ] Expose the PNG reference in the report payload and render it without clipping.
- [ ] Run JavaScript and browser audit tests.

### Task 4: Twenty-Cycle BO Transition Verification

**Files:**
- Modify: `docs/agents/bo_agent.md`
- Modify: `docs/agents/bo_agent_runtime_guideline.txt`
- Modify: `docs/runtime/test_mode.md`
- Test: `tests/unit/test_bo_agent.py`
- Test: `tests/integration/test_bo_gui_api.py`

**Interfaces:**
- Consumes: the completed 20-cycle runtime and visualization contracts.
- Produces: evidence that cycles 1-8 are LHS, cycles 9-20 are GP/EI, and both test printer routes use the same budget.

- [ ] Add a deterministic 20-step test asserting exactly eight LHS and twelve acquisition phases.
- [ ] Run the focused BO suite and integration tests.
- [ ] Update runtime documentation with the verified cycle and graph behavior.
- [ ] Run the complete affected test set and record any hardware-only verification gap.
