---
doc_type: plan
subtype: implementation
status: active
authority: execution
audience: [developer, researcher]
scope: [analysis, fem]
summary: Complete new native studies with a modestly coarser geometry-checked mesh.
execution_status: completed
governing_design: docs/superpowers/specs/2026-09-09-analysis-multifidelity-decision-design.md
related_docs:
  - docs/agents/analysis_agent.md
  - docs/superpowers/specs/2026-09-09-analysis-multifidelity-decision-design.md
supersedes: []
---

# Sparse native FEM improvement implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline in the existing workspace. The user has approved implementation and commit/tag/push after verification.

**Goal:** Produce fresh full-domain native evidence, assess modest coarsening and its compute cost, and measure response improvement without relabeling the retained baseline.

**Architecture:** Use the existing Analysis FEM decisions, registered CAE tools, immutable input copies and native compute owner. Isolated study settings do not change live equipment, foreground Analysis → BO, automatic promotion or calibration admission.

**Tech Stack:** Python, pytest, MeshLab, Gmsh, CalculiX, Matplotlib, PyVista.

**Spec:** `docs/superpowers/specs/2026-09-09-analysis-multifidelity-decision-design.md`; additional user requirement: modestly sparse mesh, actual completed new result, then commit/retag/push.

## Global constraints

- Preserve the original STL/CSV, retained baseline, full requested displacement and frozen contact convention.
- No physical device calls, solver-output scaling, fitted coordinate shifts or experimental-curve substitution into material tables.
- Keep watertightness, topology, volume and surface-distance acceptance checks unchanged.
- Report hypothesized constitutive parameters as hypotheses; a completed calculation is not an independently validated material model.
- No wall-clock solver cutoff. Keep cancellation and finite action bounds owned by the existing runtime.

## Task 1: Isolated mesh controls

**Files:** `scripts/validation/run_analysis_fem_cycle.py`, `tests/unit/test_analysis_fem_validation_runner.py`.

**Interface:** `prepare_evidence(..., mesh_size_mm=.6)` sets volume and surface resolution together; all measured/loading/material fields stay fixed.

- [x] Extend the frozen-evidence test with a `.8` mesh request, asserting unchanged loading, material, boundary tolerance and observations; observe the missing-keyword failure.
- [x] Add a finite `[.05, 5]` mm size argument and `--mesh-size-mm`; run `.venv/bin/python -m pytest -q tests/unit/test_analysis_fem_validation_runner.py`.
- [x] Run `.8` with the existing registered API: geometry gate rejects sampled distance `.121004 mm`, above `.1 mm`. Preserve this result.
- [x] Check `.7` and `.65` with unchanged geometry acceptance: both fail the sampled surface-distance bound before solving. Preserved in sparse-reference-02/03.
- [x] Tighten the remesh-operation distance instead of relaxing final geometry acceptance. `.8` with `.0275` mm operation distance passes: 51,385 nodes, 148,427 elements (7.10% fewer), sampled deviation .095762 mm, volume error .046817%, poor-element fraction 3.7406%. `.025` passes geometry but fails the unchanged mesh-quality gate.

## Task 2: Full-domain response study

**Files:** same validation runner and tests; isolated study JSON under `scripts/validation/fixtures/` if constitutive inputs are needed.

**Interface:** Explicit study material configuration is passed to the existing `payload.material`; source, loading, contact convention and experiment remain immutable. No automatic material calibration or promotion.

- [x] Test that explicit material hypotheses cannot overwrite source/loading/mesh fields and retain their provenance. Reject empty laws, booleans and constants that would be silently clamped; remove shadowing material aliases. Runner: 15 tests passed.
- [x] Complete a new full-domain study using the earlier promising post-yield hypothesis on the accepted sparse mesh; 182 converged increments, 183 points, full 15 mm endpoint and final fields.
- [x] Compare native full-domain peak magnitude/location, work and curve RMSE against both retained completed baseline and measured curve. Peak error −2.34%, work error +21.08%, RMSE 986.01 N; earlier rejected/partial cases remain separate.

## Task 3: Evidence and handoff

**Files:** `docs/agents/analysis_agent.md`, `docs/paper/evidence/2026-09-09-feature-informed-fem-calibration.md`, generated figures under `docs/agents/assets/figures/`.

- [x] Run `scripts/validation/report_analysis_fem_cycle.py` on the new native result; visually inspect the full-domain comparison and both final contours; independently check full-domain metrics.
- [x] Run Analysis/CAE targeted tests plus non-actuating foreground/background closed-loop integration tests: 245 passed in 30.47 s; original hashes unchanged, no device use.
- [x] Registered API/local verification: 10/10 each, 19 decisions per backend, 77.67/192.09 s; fallback disabled. New evidence: `artifacts/analysis_validation/20260909-sparse-dual-backend-01`.
- [x] While native PID 3239654 was computing, two non-actuating production software loops completed in 28.22 s. Same PID/start identity and increasing native CPU ticks prove overlap. Evidence: `validation-fem-20260909-sparse-postyield-03/parallel-proof`.
- [x] Update current artifacts/verification with the actual new outcome, elapsed time, memory and unresolved scientific limitations.
- [x] Review the diff and prepare scoped, verified files for the requested commit and `Analysis-Agent` retag. Publication is verified from Git's main/tag refs rather than a self-referential source hash in this plan.

## Numerical execution record

`artifacts/runs/validation-fem-20260909-sparse-postyield-03` ran native FEM from 2026-09-09T09:35:40Z to 10:44:44Z. It uses the frozen post-yield hypothesis fixture and the accepted mesh above. Native elapsed was 4,143.96 s; total study elapsed 4,240.95 s and peak sampled process-tree RSS 2.18 GiB. Coarsening reduced elements by 7.10% but did not reduce cost against the baseline: the changed nonlinear model required more increments/cutbacks. Original-source reprojection and MeshLab adaptive-mode exploratory checks did not improve the sampled distance and were not added to production.

An empty final API response occurred after native completion. The existing saved-evidence review completed in 8.06 s without another solve, retaining both original and reviewed receipts. Regression-first handling now preserves numerical artifacts on ordinary review exceptions and holds further actions; initial decision failure makes zero solver calls, and cancellation still propagates. Independent review found no blocking issue and checked calibration-child failure without promotion.

The native response improves RMSE by 37.82% and peak location/magnitude, but its +21.08% work error is unresolved. Full-range forward execution is complete; physical calibration, mesh convergence and independent predictive validation are not established. The previous retained baseline and raw measured BO objective remain unchanged.

The local-operation distance and final sampled bidirectional distance are different quantities; [MeshLab's filter contract](https://pymeshlab.readthedocs.io/en/latest/filter_list.html#meshing-isotropic-explicit-remeshing) defines the former per operation. Coarsening remains subject to the existing final geometry and volume-mesh checks.
