# Analysis Stress-Strain and Energy-Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize measured UTM force-displacement data into an engineering stress-strain response, optimize 50%-strain volumetric energy absorption in BO, and render a publication-style scientific curve.

**Architecture:** Analysis keeps raw force-displacement evidence and derives one canonical engineering stress-strain series from experiment-plan geometry. Metrics and the default BO observation consume that canonical series, while the Live GUI prefers its compact shape-preserving preview and falls back to legacy force-displacement reports. The existing BO envelope, compiled-objective authority, equipment protocol, and CAE boundary model stay unchanged.

**Tech Stack:** Python 3.12, pytest, FastAPI test client, vanilla JavaScript, SVG, CSS, Node.js regression harness.

**Spec:** `docs/superpowers/specs/2026-09-02-analysis-stress-strain-energy-design.md`

## Global Constraints

- Engineering stress is `F / A0` in MPa; engineering strain is `delta / H0` and positive in compression.
- `A0` and `H0` come from the current experiment-plan/specimen geometry; no specimen dimension or endpoint is hardcoded.
- The default BO objective is `energy_density_50pct_MJ_per_m3 = integral(sigma d epsilon)` through `epsilon = 0.5`.
- `energy_absorption_50pct_mJ` and raw force-displacement evidence remain available.
- Never smooth or extrapolate the measured response.
- An activated compiled objective remains authoritative.
- Preserve all unrelated uncommitted Equipment, Windows bridge, and GUI work.

---

### Task 1: Canonical Stress-Strain Runtime Contract

**Files:**
- Modify: `agents/analysis_agent.py`
- Test: `tests/unit/test_analysis_agent.py`

**Interfaces:**
- Consumes: `_canonical_curve(curve, geometry) -> list[dict[str, Any]]` and the resolved `specimen_geometry`.
- Produces: `_stress_strain_curve(curve, geometry) -> dict[str, Any]` stored at `analysis.stress_strain_curve`.

- [ ] **Step 1: Write failing normalization and preview tests**

Add hand-derived assertions showing that 200 N on 200 mm2 is 1 MPa and 15 mm on 30 mm is 0.5 strain:

```python
def test_analysis_agent_builds_engineering_stress_strain_runtime_curve() -> None:
    payload = AnalysisAgent._stress_strain_curve(
        [
            {"time_s": 0.0, "displacement_mm": 0.0, "force_N": 0.0},
            {"time_s": 1.0, "displacement_mm": 15.0, "force_N": 200.0},
        ],
        {"cross_section_area_mm2": 200.0, "gauge_length_mm": 30.0},
    )
    assert payload["schema"] == "engineering_stress_strain_curve.v1"
    assert payload["preview"][-1]["stress_MPa"] == 1.0
    assert payload["preview"][-1]["strain"] == 0.5
    assert payload["preview"][-1]["strain_pct"] == 50.0
```

Add a 1,001-point serrated fixture and assert that the preview is at most 200 rows, remains source-index ordered, retains the first/last rows, and retains a deliberately injected local peak and local drop.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py -k 'engineering_stress_strain_runtime_curve or stress_strain_preview'
```

Expected: failure because `_stress_strain_curve` and the runtime field do not exist.

- [ ] **Step 3: Implement canonical conversion and extrema-preserving preview**

In `AnalysisAgent`, add focused static helpers:

```python
@staticmethod
def _curve_extrema_preview(rows: list[dict[str, Any]], limit: int = 200) -> list[dict[str, Any]]:
    """Keep ordered bucket minima/maxima plus global endpoints."""

@staticmethod
def _stress_strain_curve(curve: list[dict[str, float]], geometry: dict[str, Any]) -> dict[str, Any]:
    canonical = AnalysisAgent._canonical_curve(curve, geometry)
    area = float(geometry["cross_section_area_mm2"])
    gauge = float(geometry["gauge_length_mm"])
    return {
        "schema": "engineering_stress_strain_curve.v1",
        "convention": "positive_compression",
        "stress_unit": "MPa",
        "strain_unit": "1",
        "normalization": {
            "cross_section_area_mm2": area,
            "gauge_length_mm": gauge,
            "initial_volume_mm3": area * gauge,
        },
        "point_count": len(canonical),
        "preview": AnalysisAgent._curve_extrema_preview(canonical, 200),
    }
```

Return the schema, positive-compression convention, units, normalization metadata, full point count, and capped preview. Each preview row retains `source_row_index`, `time_s`, `displacement_mm`, `force_N`, `stress_MPa`, `strain`, `strain_pct`, and `segment` where available.

Build this payload once during `run()` and publish it as `analysis["stress_strain_curve"]`. Reuse the same payload for artifacts/metrics rather than independently re-normalizing in multiple consumers.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py -k 'canonical_curve or stress_strain'
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the backend curve contract**

```bash
git add agents/analysis_agent.py tests/unit/test_analysis_agent.py
git commit -m "Add engineering stress-strain analysis contract"
```

---

### Task 2: Energy-Density Metric and BO Objective

**Files:**
- Modify: `agents/analysis_agent.py`
- Modify: `objectives/metric_registry.py`
- Test: `tests/unit/test_analysis_agent.py`
- Test: `tests/unit/test_objective_metric_registry.py`

**Interfaces:**
- Consumes: full canonical stress-strain rows and existing `_curve_through_displacement`/trapezoidal integration behavior.
- Produces: `energy_density_50pct_MJ_per_m3`, energy identity diagnostics, and default BO metric selection.

- [ ] **Step 1: Write failing dimensional and BO tests**

Extend the 30 mm specimen integration test with literal expectations. For the existing `F = 10 * delta`, `A0 = 400 mm2`, `H0 = 30 mm` fixture:

```python
assert metrics["energy_absorption_50pct_mJ"] == pytest.approx(1125.0)
assert metrics["energy_density_50pct_MJ_per_m3"] == pytest.approx(1125.0 / 12000.0)
assert metrics["energy_identity_relative_error"] < 1e-8
assert observation["metric_name"] == "energy_density_50pct_MJ_per_m3"
assert observation["unit"] == "MJ/m3"
```

Add cases proving an interpolated 0.5-strain endpoint, no extrapolation below 0.5, explicit invalid geometry blocking, and preservation of a compiled objective. Add a registry assertion:

```python
metric = MetricRegistry.default().get("energy_density_50pct_mj_per_m3")
assert metric.source_path == "analysis.metrics.energy_density_50pct_MJ_per_m3"
assert metric.unit == "MJ/m3"
assert metric.dimension == "energy_density"
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_analysis_agent.py \
  tests/unit/test_objective_metric_registry.py \
  -k '50pct or energy_density or compiled_objective'
```

Expected: failures on the absent normalized metric and old default BO metric name.

- [ ] **Step 3: Implement strain-domain clipping and integration**

Add a strain-domain clipping helper equivalent to the existing displacement-domain helper:

```python
@staticmethod
def _curve_through_strain(
    points: list[dict[str, Any]], limit_strain: float
) -> tuple[list[dict[str, Any]], bool]:
    """Clip at the exact strain boundary, interpolating but never extrapolating."""
```

Integrate `stress_MPa` over dimensionless `strain` using the trapezoidal rule. Because the numerical result in MPa equals MJ/m3, do not apply an additional scale factor. Compute `energy_identity_relative_error` against `energy_absorption_50pct_mJ / (A0 * H0)`.

Change only the no-compiled-objective branch in `_handoff_payloads`:

```python
bo_metric_name = "energy_density_50pct_MJ_per_m3"
bo_metric_unit = "MJ/m3"
```

Add the registry definition and retain the previous total-energy definition.

- [ ] **Step 4: Run Analysis, BO, and registry tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_analysis_agent.py \
  tests/unit/test_bo_agent.py \
  tests/unit/test_objective_metric_registry.py
```

Expected: all tests pass; BO consumes the explicitly declared normalized metric without BO-agent code changes.

- [ ] **Step 5: Commit the normalized objective**

```bash
git add agents/analysis_agent.py objectives/metric_registry.py \
  tests/unit/test_analysis_agent.py tests/unit/test_objective_metric_registry.py
git commit -m "Optimize volumetric energy absorption at 50 percent strain"
```

---

### Task 3: Publication-Style Stress-Strain Figure

**Files:**
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Create: `tests/unit/test_planning_analysis_curve_js.py`

**Interfaces:**
- Consumes: `analysis.stress_strain_curve.preview`, with fallback to `analysis.utm_curve.preview` plus `analysis.specimen_geometry`.
- Produces: a responsive scientific SVG from `analysisStressStrainPoints(analysis)` and `renderAnalysisCurve(analysis)`.

- [ ] **Step 1: Write failing executable JavaScript behavior tests**

Use the existing Node helper-extraction pattern from `test_planning_design_report_js.py`. Execute the real new helper with a controlled server-derived payload and a legacy payload:

```python
assert server_points == [
    {"strain_pct": 0, "stress_MPa": 0},
    {"strain_pct": 50, "stress_MPa": 1},
]
assert legacy_points[-1] == {"strain_pct": 50, "stress_MPa": 1}
```

Execute `renderAnalysisCurve` with its real dependencies and assert the returned SVG has visible `Engineering compressive strain`, `Engineering stress`, numeric tick labels, and the 50% reference when reached. Assert it does not contain the former peak-dot markup.

- [ ] **Step 2: Run the frontend test and confirm RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_planning_analysis_curve_js.py
```

Expected: failure because `analysisStressStrainPoints` and the scientific SVG do not exist.

- [ ] **Step 3: Implement the stress-strain renderer**

Replace `analysisCurvePoints` with a helper that prefers server-derived rows and normalizes legacy force-displacement rows only when area and height are finite and positive. Keep strain dimensionless in the data contract and convert to percent only for display.

Render a zero-origin SVG with five or six human-readable ticks on each axis, quiet major grid lines, explicit axis titles, a 50% neutral dashed reference, and one continuous measured curve. Change the dashboard card title to `Engineering Stress-Strain Curve` and eyebrow to `normalized UTM response`.

Update only the Analysis curve CSS block:

```css
body.planning-live-body .ar-analysis-curve {
  background: #ffffff;
}

body.planning-live-body .ar-analysis-curve .curve {
  stroke: #1f77b4;
  stroke-width: 2;
  filter: none;
}
```

Add classes for grid, spines/ticks, labels, and the 50% reference. Do not modify the surrounding dashboard theme or unrelated Equipment styles.

- [ ] **Step 4: Run frontend and layout tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_planning_analysis_curve_js.py \
  tests/integration/test_live_gui_runtime_layout.py -k 'analysis or static_assets'
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit only the Analysis figure hunks**

Stage only the new Analysis-figure hunks because `planning.js` and `styles.css` already contain unrelated user work:

```bash
git add -p web/static/planning.js web/static/styles.css
git add tests/unit/test_planning_analysis_curve_js.py
git commit -m "Render publication-style stress-strain figure"
```

---

### Task 4: Documentation and End-to-End Verification

**Files:**
- Modify: `docs/agents/analysis_agent.md`
- Modify: `docs/agents/analysis_utm_runtime_guideline.txt`
- Modify: `docs/agents/cae_analysis_runtime_guideline.txt`
- Test: existing documentation and Analysis contract suites.

**Interfaces:**
- Consumes: final Analysis and BO field names from Tasks 1-3.
- Produces: current operator/developer documentation and final verification evidence.

- [ ] **Step 1: Update the Analysis documentation**

Document the engineering normalization equations, geometry precedence, positive-compression convention, 50%-strain energy-density objective, total-energy compatibility field, no-smoothing/no-extrapolation policy, curve schema, and publication-style GUI behavior. Update stale text that identifies force-displacement total energy as the default BO target.

- [ ] **Step 2: Run documentation validation**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_documentation_validation.py
```

Expected: all documentation checks pass.

- [ ] **Step 3: Run the focused regression suite**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_analysis_agent.py \
  tests/unit/test_bo_agent.py \
  tests/unit/test_objective_metric_registry.py \
  tests/unit/test_utm_csv_trapezium.py \
  tests/unit/test_planning_analysis_curve_js.py \
  tests/integration/test_live_gui_runtime_layout.py \
  tests/unit/test_documentation_validation.py
```

Expected: all tests pass. Do not run the controller integration test that launches physical UTM/ROS processes.

- [ ] **Step 4: Run static and diff checks**

Run:

```bash
.venv/bin/python -m py_compile agents/analysis_agent.py objectives/metric_registry.py
node --check web/static/planning.js
git diff --check
```

Expected: zero exit status and no output from diff check.

- [ ] **Step 5: Review workspace boundaries**

Use `git diff --name-only`, `git diff --stat`, and focused diffs to confirm that all pre-existing Equipment, Windows bridge, reference-media, and unrelated GUI changes remain intact and outside this task's final staged patch.

- [ ] **Step 6: Commit documentation and any remaining scoped hunks**

```bash
git add docs/agents/analysis_agent.md \
  docs/agents/analysis_utm_runtime_guideline.txt \
  docs/agents/cae_analysis_runtime_guideline.txt \
  docs/superpowers/plans/2026-09-02-analysis-stress-strain-energy.md
git commit -m "Document stress-strain Analysis objective"
```
