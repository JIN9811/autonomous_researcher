# BO Objective And Posterior Live Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one shared objective-equation and Bayesian posterior visualization contract, render it live in both the BO Workspace and Live GUI, and persist publication-style completion artifacts.

**Architecture:** A focused Python projector owns all visualization numbers and emits `bo_visualization.v1`; BO execution remains the sole owner of candidate selection. A shared dependency-free browser module renders one current projection as SVG in both GUIs. The controller writes Matplotlib PNG/SVG and CSV artifacts only after completed workspace/agent results.

**Tech Stack:** Python 3.12, FastAPI, Pydantic-compatible dictionaries, existing BO/BoTorch adapters, vanilla JavaScript/SVG, Matplotlib, pytest, Node helper tests, Selenium/Firefox browser audit.

## Global Constraints

- Existing BO candidate selection, Objective Service lifecycle, AgentResult, MCP/tool protocol, and Design handoff behavior must not change.
- Both `/bo` and Live GUI must consume `bo_visualization.v1`; neither browser may derive or rescale uncertainty.
- Runtime rendering uses one replace-in-place SVG and stores no base64 figure data.
- The default view is a selected numeric parameter slice; candidate-pool-index audit remains selectable.
- A completed BO step is the only normal live-update trigger.
- Matplotlib is completion-artifact-only and must not block BO selection when rendering fails.
- Do not modify, stage, or revert the user-owned `.env.example` change.

---

### Task 1: Validate And Project BO Visualization Data

**Files:**
- Create: `experiments/bo_visualization.py`
- Create: `tests/unit/test_bo_visualization.py`

**Interfaces:**
- Consumes: objective dictionaries, BO parameter space, one surrogate trace item, optional selected parameter, and run id.
- Produces: `build_bo_visualization(*, run_id: str, objective: dict[str, Any], parameter_space: dict[str, Any], trace: dict[str, Any], selected_parameter: str = "") -> dict[str, Any]`.
- Produces: `validate_bo_visualization(payload: dict[str, Any]) -> dict[str, Any]`, returning the normalized payload or raising `ValueError`.

- [ ] **Step 1: Write failing projection tests**

```python
def test_build_bo_visualization_emits_finite_equal_length_arrays():
    payload = build_bo_visualization(
        run_id="run-bo-1",
        objective={"objective_id": "sea", "version": 2, "direction": "maximize", "expression": {"op": "metric", "metric_id": "specific_energy_absorption"}},
        parameter_space={"relative_density": [0.2, 0.4], "cell_size_mm": [5.0, 10.0]},
        trace=sample_trace(),
        selected_parameter="relative_density",
    )
    assert payload["schema"] == "bo_visualization.v1"
    assert payload["view"]["selected_parameter"] == "relative_density"
    assert len(payload["posterior"]["x"]) == len(payload["posterior"]["mean"]) == len(payload["posterior"]["std"])
    assert payload["posterior"]["lower_95"][0] == pytest.approx(payload["posterior"]["mean"][0] - 1.96 * payload["posterior"]["std"][0])


def test_validate_bo_visualization_rejects_mismatched_and_non_finite_arrays():
    payload = valid_visualization()
    payload["posterior"]["std"] = [float("nan")]
    with pytest.raises(ValueError, match="posterior arrays"):
        validate_bo_visualization(payload)
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `pytest -q tests/unit/test_bo_visualization.py`

Expected: FAIL because `experiments.bo_visualization` does not exist.

- [ ] **Step 3: Implement deterministic projection and validation**

Implement these focused helpers in `experiments/bo_visualization.py`:

```python
def numeric_parameter_names(parameter_space: dict[str, Any]) -> list[str]: ...
def select_slice_parameter(parameter_space: dict[str, Any], trace: dict[str, Any], requested: str = "") -> str: ...
def objective_display(objective: dict[str, Any]) -> dict[str, Any]: ...
def build_bo_visualization(*, run_id: str, objective: dict[str, Any], parameter_space: dict[str, Any], trace: dict[str, Any], selected_parameter: str = "") -> dict[str, Any]: ...
def validate_bo_visualization(payload: dict[str, Any]) -> dict[str, Any]: ...
```

Use stable parameter ordering. Build the candidate audit arrays directly from
`trace["candidates"]`. For the parameter slice, group candidate values by the
selected parameter and preserve backend values. Mark this representation
`pool_projection` until an arbitrary-point posterior evaluator is available;
do not interpolate a fake Gaussian process.

- [ ] **Step 4: Run projection tests**

Run: `pytest -q tests/unit/test_bo_visualization.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add experiments/bo_visualization.py tests/unit/test_bo_visualization.py
git commit -m "feat: project BO visualization data"
```

### Task 2: Attach Visualization To Every BO Step And Agent Result

**Files:**
- Modify: `experiments/benchmark.py`
- Modify: `agents/bo_agent.py`
- Modify: `tests/unit/test_experiment_runtime.py`
- Modify: `tests/unit/test_bo_agent.py`

**Interfaces:**
- Consumes: `build_bo_visualization` from Task 1.
- Produces: each `surrogate_trace` item includes `visualization`.
- Produces: `bo_result.visualization` contains the latest valid projection and `bo_result.visualization_steps` contains compact step identities.

- [ ] **Step 1: Add failing benchmark assertions**

```python
visualization = result["strategies"]["bo"]["surrogate_trace"][0]["visualization"]
assert visualization["schema"] == "bo_visualization.v1"
assert visualization["step"] == 1
assert visualization["next_point"]["candidate_id"]
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `pytest -q tests/unit/test_experiment_runtime.py tests/unit/test_bo_agent.py`

Expected: FAIL because the visualization projection is absent.

- [ ] **Step 3: Build the projection after each completed BO evaluation**

In `run_benchmark`, call `build_bo_visualization` only after `selected_trace`
and observed records are final. Pass the request run id, objective, parameter
space, trace item, and optional `visualization_parameter` setting. Store the
returned object under `trace_item["visualization"]`.

- [ ] **Step 4: Expose the latest projection through BO Agent output**

In `BOAgent.run_with_settings`, copy the last valid trace visualization to:

```python
bo_result["visualization"] = latest_visualization
bo_result["visualization_steps"] = [
    {"step": item["step"], "selected_parameter": item["view"]["selected_parameter"]}
    for item in visualizations
]
```

Do not modify candidate ranking or recommendation selection.

- [ ] **Step 5: Run focused BO tests**

Run: `pytest -q tests/unit/test_experiment_runtime.py tests/unit/test_bo_agent.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add experiments/benchmark.py agents/bo_agent.py tests/unit/test_experiment_runtime.py tests/unit/test_bo_agent.py
git commit -m "feat: attach visualization to BO results"
```

### Task 3: Emit Step Updates And Persist The Latest Projection

**Files:**
- Modify: `app/main.py`
- Modify: `app/controller.py`
- Modify: `tests/integration/test_bo_gui_api.py`
- Modify: `tests/unit/test_controller_planning.py`

**Interfaces:**
- Consumes: trace item `visualization` values from Task 2.
- Produces: runtime event `bo.visualization.updated` with `run_id`, `step`, and `visualization`.
- Produces: `/api/bo/config` returns `recent_visualization` and available `visualization_steps`.

- [ ] **Step 1: Add failing API and event assertions**

```python
visualization = payload["benchmark"]["strategies"]["bo"]["surrogate_trace"][-1]["visualization"]
assert visualization["schema"] == "bo_visualization.v1"
events = app_main.controller.recent_events()
assert any(event.get("event_type") == "bo.visualization.updated" and event.get("payload", {}).get("step") == 3 for event in events)
assert client.get("/api/bo/config").json()["recent_visualization"]["step"] == 3
```

- [ ] **Step 2: Run integration test and confirm failure**

Run: `pytest -q tests/integration/test_bo_gui_api.py`

Expected: FAIL because step events and recent projection are absent.

- [ ] **Step 3: Emit monotonically ordered visualization events**

Add a controller helper:

```python
async def emit_bo_visualization(self, visualization: dict[str, Any], *, source: str) -> dict[str, Any]: ...
```

Validate the payload, ignore duplicate/older steps for the same run, store the
latest projection in `state.run_metadata["bo_visualization"]`, and broadcast
`event_type="bo.visualization.updated"`. The benchmark route emits each
completed trace projection in order after the tool returns. The BO Agent route
emits the latest projection without replaying duplicates.

- [ ] **Step 4: Expose persisted state in BO config**

Return:

```python
"recent_visualization": metadata.get("bo_visualization", {}),
"visualization_steps": metadata.get("bo_visualization_steps", []),
```

- [ ] **Step 5: Run API/controller tests**

Run: `pytest -q tests/integration/test_bo_gui_api.py tests/unit/test_controller_planning.py -k 'bo or visualization'`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/controller.py tests/integration/test_bo_gui_api.py tests/unit/test_controller_planning.py
git commit -m "feat: stream BO visualization steps"
```

### Task 4: Build One Shared Browser Renderer

**Files:**
- Create: `web/static/bo_visualization.js`
- Create: `tests/unit/test_bo_visualization_js.py`
- Modify: `web/static/styles.css`

**Interfaces:**
- Consumes: validated `bo_visualization.v1` objects.
- Produces: global `window.BOVisualization` with `renderEquationCard(payload)`, `renderPlot(payload, options)`, `availableParameters(payload)`, and `artifactLinks(payload)`.

- [ ] **Step 1: Write failing Node-driven renderer tests**

```python
assert result["hasEquation"] is True
assert result["hasConfidenceBand"] is True
assert result["hasMeasuredLegend"] is True
assert result["hasNextPoint"] is True
assert result["candidateModeLabel"] == "Candidate pool index"
assert result["forbiddenScale"] is False
```

The test loads the shared script in Node, calls pure string-returning renderer
functions, and asserts no `uncertainty * 0.12` or equivalent scaling exists.

- [ ] **Step 2: Run the JS test and confirm failure**

Run: `pytest -q tests/unit/test_bo_visualization_js.py`

Expected: FAIL because the shared renderer is absent.

- [ ] **Step 3: Implement pure SVG/equation renderers**

Use two vertically aligned plot regions in one responsive SVG. Render the
confidence band from `lower_95`/`upper_95` exactly. Use the selected view to
choose either posterior slice arrays or `candidate_index_view`. Escape all text
and reject invalid arrays with a visible stale-state message.

- [ ] **Step 4: Add shared publication-style CSS**

Add scoped classes for a white plotting area, dark axes, gray grid, blue mean,
blue confidence fill, black observations, green best point, red next point, and
orange acquisition. Ensure the SVG uses `width: 100%`, a stable aspect ratio,
and no horizontal overflow.

- [ ] **Step 5: Run shared renderer tests**

Run: `pytest -q tests/unit/test_bo_visualization_js.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/static/bo_visualization.js web/static/styles.css tests/unit/test_bo_visualization_js.py
git commit -m "feat: add shared BO plot renderer"
```

### Task 5: Integrate The BO Workspace Cards

**Files:**
- Modify: `web/templates/bo.html`
- Modify: `web/static/bo.js`
- Modify: `tests/integration/test_bo_gui_api.py`
- Modify: `tests/ui/bo_objective_compiler_browser_audit.py`

**Interfaces:**
- Consumes: `window.BOVisualization`, `/api/bo/config`, `/api/bo/benchmark`, `/api/bo/run`, and `/api/events/stream`.
- Produces: `#bo-objective-equation-card`, `#bo-posterior-card`, view/parameter/step selectors, and artifact links.

- [ ] **Step 1: Add failing DOM contract assertions**

Assert the page contains:

```text
bo-objective-equation-card
bo-posterior-card
bo-posterior-view
bo-posterior-parameter
bo-posterior-step
bo-posterior-latest
```

Also assert `bo_visualization.js` loads before `bo.js`.

- [ ] **Step 2: Run BO GUI integration tests and confirm failure**

Run: `pytest -q tests/integration/test_bo_gui_api.py`

Expected: FAIL because the card DOM is absent.

- [ ] **Step 3: Replace the old trace stack with two cards**

Keep the existing Objective Builder. Add the read-only active equation card and
one plot card. Retain selected-point audit below the plot, but stop appending up
to 20 complete SVGs.

- [ ] **Step 4: Connect state, selectors, and events**

`bo.js` stores one current projection plus a compact map keyed by step. On
`bo.visualization.updated`, accept only the matching/newer run and replace the
card body. Parameter/view changes rerender from the current projection without
running BO. EventSource reconnect first calls `/api/bo/config`.

- [ ] **Step 5: Extend Selenium audit**

Run a three-step virtual BO benchmark, verify equation text, confidence band,
measured points, next point, view switching, no horizontal overflow at
1920x1080 and 390x844, and exactly one mounted plot SVG.

- [ ] **Step 6: Run BO API and browser audit**

Run: `pytest -q tests/integration/test_bo_gui_api.py`

Run with server active: `python tests/ui/bo_objective_compiler_browser_audit.py --base-url http://127.0.0.1:7860`

Expected: PASS and screenshots under `artifacts/ui/objective_compiler/`.

- [ ] **Step 7: Commit**

```bash
git add web/templates/bo.html web/static/bo.js tests/integration/test_bo_gui_api.py tests/ui/bo_objective_compiler_browser_audit.py
git commit -m "feat: add BO workspace live posterior cards"
```

### Task 6: Integrate The Live GUI BO Agent Cards

**Files:**
- Modify: `web/templates/planning.html`
- Modify: `web/static/planning.js`
- Create: `tests/unit/test_planning_bo_visualization_js.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: `window.BOVisualization` and `latestReportBoResult(report).visualization`.
- Produces: always-visible BO Objective Equation and Live Posterior cards in `renderBoDashboardCards`.

- [ ] **Step 1: Add failing Live GUI renderer tests**

Verify `renderBoDashboardCards` renders both cards when BO data exists and
explicit waiting cards when it does not. Verify the graph markup comes from
`BOVisualization.renderPlot`, not a duplicate formula in `planning.js`.

- [ ] **Step 2: Run tests and confirm failure**

Run: `pytest -q tests/unit/test_planning_bo_visualization_js.py tests/integration/test_live_gui_runtime_layout.py -k 'bo'`

Expected: FAIL because the shared cards are not wired.

- [ ] **Step 3: Load the shared module before planning.js**

Add a cache-versioned `bo_visualization.js` script in `planning.html`. Keep the
existing planning script and report shell unchanged.

- [ ] **Step 4: Add the two BO cards**

Place Objective Equation and Live Posterior first in the BO dashboard. Use a
wide plot card and a compact equation card. Keep Ranking, Recommendation,
Parameters, Strategy, Memory, Audit, and Next Design Request cards. Remove only
the duplicate legacy BO trace renderer from the BO report path.

- [ ] **Step 5: Perform partial live updates**

When a `bo.visualization.updated` event arrives and BO is selected, update the
two card bodies without rebuilding the full report. When another agent is
selected, cache only the latest projection and do no plot rendering. Returning
to BO renders that projection once.

- [ ] **Step 6: Run Live GUI tests**

Run: `pytest -q tests/unit/test_planning_bo_visualization_js.py tests/integration/test_live_gui_runtime_layout.py -k 'bo or visualization'`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/templates/planning.html web/static/planning.js tests/unit/test_planning_bo_visualization_js.py tests/integration/test_live_gui_runtime_layout.py
git commit -m "feat: add Live GUI BO posterior cards"
```

### Task 7: Generate Matplotlib Completion Artifacts And Documentation

**Files:**
- Create: `reporting/bo_visualization_artifacts.py`
- Create: `tests/unit/test_bo_visualization_artifacts.py`
- Modify: `app/controller.py`
- Modify: `tests/integration/test_bo_gui_api.py`
- Modify: `requirements.txt`
- Modify: `docs/agents/bo_agent.md`
- Modify: `docs/gui/README.md`
- Modify: `docs/tutorials/first_autonomous_run.md`

**Interfaces:**
- Consumes: one validated `bo_visualization.v1` payload and output directory.
- Produces: `write_bo_visualization_artifacts(payload, output_dir) -> list[dict[str, Any]]` with PNG, SVG, and CSV records.

- [ ] **Step 1: Write failing artifact tests**

```python
records = write_bo_visualization_artifacts(valid_visualization(), tmp_path)
paths = {Path(item["path"]).suffix for item in records}
assert paths == {".png", ".svg", ".csv"}
assert "lower_95" in (tmp_path / next(item["name"] for item in records if item["name"].endswith(".csv"))).read_text()
```

- [ ] **Step 2: Run artifact tests and confirm failure**

Run: `pytest -q tests/unit/test_bo_visualization_artifacts.py`

Expected: FAIL because the artifact renderer is absent.

- [ ] **Step 3: Implement publication artifact rendering**

Use Matplotlib `Agg`, a 7.2 by 5.2 inch figure, 150 DPI PNG, white background,
shared x-axis posterior/acquisition subplots, constrained layout, and the exact
payload colors/values. Write CSV columns `x,mean,std,lower_95,upper_95,acquisition`.

- [ ] **Step 4: Register artifacts without making BO fail**

Replace or augment `_write_bo_plot_artifact` so a valid latest visualization
creates the three files. Catch renderer exceptions, return an artifact warning,
and preserve the existing compact progress SVG only for legacy results without
`bo_visualization.v1`.

- [ ] **Step 5: Add dependency and documentation**

Pin Matplotlib using the repository's existing requirement style. Document the
equation card, plot semantics, parameter/candidate views, live-update trigger,
artifact downloads, stale state, and the fact that pool projection is not a GP
posterior.

- [ ] **Step 6: Run focused and regression tests**

Run: `pytest -q tests/unit/test_bo_visualization.py tests/unit/test_bo_visualization_artifacts.py tests/unit/test_experiment_runtime.py tests/unit/test_bo_agent.py tests/integration/test_bo_gui_api.py tests/unit/test_planning_bo_visualization_js.py tests/integration/test_live_gui_runtime_layout.py -k 'bo or visualization'`

Expected: PASS.

- [ ] **Step 7: Run browser/resource verification**

Start the existing GUI server without changing model processes, run the BO
browser audit at 1920x1080 and mobile widths, inspect screenshots, run one
five-step BO workflow, and confirm process RSS and mounted plot-node count stay
stable across repeated updates.

- [ ] **Step 8: Commit**

```bash
git add reporting/bo_visualization_artifacts.py tests/unit/test_bo_visualization_artifacts.py app/controller.py tests/integration/test_bo_gui_api.py requirements.txt docs/agents/bo_agent.md docs/gui/README.md docs/tutorials/first_autonomous_run.md
git commit -m "feat: publish BO posterior artifacts"
```

## Final Verification

- [ ] Run `git diff --check`.
- [ ] Confirm `git status --short` contains only the pre-existing `.env.example` change.
- [ ] Run all targeted Python, Node-driven, integration, and Selenium tests listed above.
- [ ] Compare `/bo` and Live GUI values for one run id and confirm equation,
      step, current best, next point, mean, confidence bounds, and acquisition
      match exactly.
- [ ] Confirm one plot SVG is mounted after at least 20 synthetic step events.
- [ ] Confirm PNG, SVG, and CSV artifacts open and contain the same values.
- [ ] Record unrelated full-suite failures separately; do not alter unrelated
      LeRobot, printer, camera, Guardian, or user configuration code.
