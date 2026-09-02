# Equipment CSV to BO Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse native Lab Equipment TRAPEZIUMX CSV data, compute a full Analysis metric set, and send only the energy integrated to 50% of the planned initial specimen height to BO.

**Architecture:** Extend the existing shared UTM parser with a row-returning API while preserving its compact probe API. Analysis uses canonical rows to calculate a boundary-interpolated 50% energy metric and emits a narrow BO objective contract; BO reads the declared objective while retaining legacy SEA compatibility.

**Tech Stack:** Python 3.12, standard-library CSV and trapezoidal integration, pytest, existing Analysis/BO handoff schemas.

**Spec:** `docs/superpowers/specs/2026-09-02-analysis-equipment-csv-to-bo-design.md`

## Global Constraints

- Preserve the vendor CSV bytes exactly.
- Resolve specimen geometry from the current experiment plan/specimen result.
- Use 50% of the resolved `gauge_length_mm`; 30 mm mapping to 15 mm is an example, not a constant.
- Derive the measured displacement extent from the CSV; never hardcode a 21 mm endpoint.
- Never extrapolate an energy value when the curve does not reach the boundary.
- Keep `bo_observation.v1` and `analysis_bo_handoff_v2` envelope versions.
- Preserve legacy UTF-8 and SEA ingestion compatibility.
- Preserve explicitly activated compiled objectives; the fixed 50%-height energy metric is the default when no custom objective is bound.
- Do not modify unrelated Equipment/UI worktree changes.

---

### Task 1: Shared canonical row parser

**Files:**
- Modify: `utils/utm_csv.py`
- Test: `tests/unit/test_utm_csv_trapezium.py`

**Interfaces:**
- Produces: `parse_utm_csv_bytes(data: bytes) -> tuple[list[dict[str, float]], dict[str, Any]]`
- Produces: `parse_utm_csv(path: Path) -> tuple[list[dict[str, float]], dict[str, Any]]`
- Preserves: `probe_utm_csv_bytes` and `probe_utm_csv` result shape without numeric row payloads.

- [ ] **Step 1: Add a failing native-row extraction test**

```python
rows, probe = parse_utm_csv_bytes(_trapezium_csv_bytes())
assert probe["source_format"] == "trapeziumx_raw"
assert rows[1] == {
    "time_s": 0.01,
    "force_N": -0.201,
    "displacement_mm": 0.001191667,
    "height_mm": 30.49879,
}
assert "canonical_rows" not in probe_utm_csv_bytes(_trapezium_csv_bytes())
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_utm_csv_trapezium.py`

Expected: import or attribute failure because the parse API does not exist.

- [ ] **Step 3: Extract shared parsing internals and add the two parse APIs**

Return the canonical numeric rows and the existing metadata separately. Make `probe_utm_csv_bytes` call the same parser and discard only the row list.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_utm_csv_trapezium.py`

### Task 2: Analysis ingestion and 50% energy

**Files:**
- Modify: `agents/analysis_agent.py`
- Modify: `objectives/metric_registry.py`
- Test: `tests/unit/test_analysis_agent.py`

**Interfaces:**
- Consumes: `parse_utm_csv(path)` canonical rows and probe metadata.
- Produces metric: `energy_absorption_50pct_mJ: float`.
- Produces boundary metadata: `energy_absorption_limit_mm`, `energy_absorption_limit_strain`, and `energy_absorption_limit_reached`.

- [ ] **Step 1: Add a failing CP949 Lab Equipment end-to-end test**

Use literal points `(0 mm, 0 N)`, `(10 mm, 100 N)`, and `(20 mm, 200 N)` with a 30 mm initial height supplied by the experiment plan. Assert the derived boundary is 15 mm, the CSV-derived extent is 20 mm, the interpolated area is `1125.0 mJ`, the complete Analysis metrics remain present, and source metadata identifies the shared Lab Equipment parser.

- [ ] **Step 2: Add a failing insufficient-range test**

Supply a different planned initial height and a curve whose CSV-derived extent ends below its calculated 50% boundary. Assert `energy_absorption_limit_reached` is false and the result is not BO-ready, proving neither the boundary nor the endpoint is fixed.

- [ ] **Step 3: Run both tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py -k 'trapezium_50pct or below_50pct'`

Expected: the current UTF-8 parser yields no native curve or the new metric is absent.

- [ ] **Step 4: Implement shared-parser ingestion and boundary interpolation**

Use the shared parser first for CSV input. Convert compression force to its magnitude, retain the existing legacy CSV fallback for unknown formats, resolve `gauge_length_mm` from experiment/specimen geometry, derive the measured extent from parsed CSV rows, clip exactly at `0.5 * gauge_length_mm`, interpolate the final point, and integrate the clipped curve with the existing trapezoidal rule.

- [ ] **Step 5: Prevent synthetic fallback after a real artifact parse failure**

Synthetic data remains allowed only when no equipment file candidate was supplied in non-live test mode.

- [ ] **Step 6: Register the metric and run Analysis tests**

Add `energy_absorption_50pct_mJ` with unit `mJ` to the objective metric registry, then run:

`.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py tests/unit/test_utm_csv_trapezium.py`

### Task 3: Narrow BO objective handoff

**Files:**
- Modify: `agents/analysis_agent.py`
- Modify: `agents/bo_agent.py`
- Test: `tests/unit/test_analysis_agent.py`
- Test: `tests/unit/test_bo_agent.py`

**Interfaces:**
- Analysis produces `metric_name=energy_absorption_50pct_mJ`, `unit=mJ`, and one-entry BO metric maps.
- BO consumes the declared objective metric and retains legacy SEA aliases.

- [ ] **Step 1: Add failing Analysis handoff assertions**

```python
assert observation["metric_name"] == "energy_absorption_50pct_mJ"
assert observation["unit"] == "mJ"
assert observation["observed_metrics"] == {"energy_absorption_50pct_mJ": 1125.0}
```

- [ ] **Step 2: Add a failing BO ingestion test**

Give BO an Analysis handoff with `objective.metric_name=energy_absorption_50pct_mJ`, `objective.unit=mJ`, and `objective.score=1125.0`. Assert its measured prior has that score, name, and unit.

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py tests/unit/test_bo_agent.py -k '50pct'`

- [ ] **Step 4: Implement declared-objective extraction and narrow handoff maps**

Read `objective.score` with its declared metric and unit for new records. Fall back to legacy SEA fields only when no declared measured objective is present.

- [ ] **Step 5: Run Analysis and BO suites and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py tests/unit/test_bo_agent.py`

### Task 4: Real artifact and regression verification

**Files:**
- Verify all files above.

**Interfaces:**
- Consumes the observed 63,005-row CP949 artifact outside the test suite.
- Produces an inspectable 15 mm energy value and BO payload summary.

- [ ] **Step 1: Run the parser and metric calculation against the latest real CSV**

Verify 63,005 parsed rows, a 15 mm integration boundary, and a finite non-negative `energy_absorption_50pct_mJ` without modifying the source file.

- [ ] **Step 2: Run focused regressions**

Run: `.venv/bin/python -m pytest -q tests/unit/test_utm_csv_trapezium.py tests/unit/test_analysis_agent.py tests/unit/test_bo_agent.py tests/integration/test_objective_compiler_closed_loop.py`

- [ ] **Step 3: Check repository hygiene**

Run: `git diff --check` and inspect `git diff --` for only the intended Analysis/BO/parser/test/spec/plan files.
