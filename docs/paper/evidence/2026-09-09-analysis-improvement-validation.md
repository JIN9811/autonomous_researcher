---
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience: [researcher, developer, reviewer, operator]
scope: [analysis, background_improvement, solver_fields, archive_reprocessing]
summary: Non-actuating verification of Analysis decisions, background model lifecycle, saved same-STL measurements and actual field postprocessing.
evidence_date: 2026-09-09
method: Focused automated tests, independent code review, read-only archived evidence checks and isolated browser/render inspection.
related_docs:
  - docs/agents/analysis_agent.md
  - docs/device_bridges/cae_computation_bridges.md
  - docs/superpowers/specs/2026-09-09-analysis-multifidelity-decision-design.md
  - docs/paper/evidence/2026-09-07-latest-cycle-demonstration.md
supersedes: []
---

# Analysis Improvement: Non-Actuating Validation

## Summary

The working-tree change separates ordinary Analysis/BO handoff from bounded
background model studies and introduces saved-field postprocessing. This record
distinguishes software tests from measured evidence and physical model validation.
No laboratory device, new physical cycle, inference backend replacement, running
server restart, commit or push was performed for this validation.

## Preserved Complete-Cycle Evidence

### Subsequent full-endpoint native case

The later isolated study `validation-fem-20260909-long-cycle-03` completed its
full requested displacement with real CalculiX. Initial study time was 1,954.52 s;
peak sampled runner/child RSS was 1,202,032,640 bytes (external model server excluded).
Same-domain force peak error was −11.12% and work error +26.90%; full-domain
agreement is therefore not established by the earlier short-domain fit below.
The final API review was rerun from saved receipts after excluding raw field
arrays from the prompt, without repeating the native solve. It held validation
because three-resolution convergence was not assessed.

Actual contours, F-D/S-S comparisons and a reusable native model package are linked
in the [Analysis reference](../../agents/analysis_agent.md#completed-native-fem-case--2026-09-09).
A separate actual copied-deck solve overlapped two production software loops
(physical/model boundaries explicitly virtualized) in 12.72 s and was then cancelled.
Its exact PID identity and increasing CPU ticks are preserved in
`artifacts/runs/validation-fem-20260909-long-cycle-03/parallel-native-proof-02/`.
This demonstrates software concurrency, not a new physical cycle or model calibration.

### Original physical acquisition archive

The operator identified the previously preserved complete cycle as using the
same STL for the tested specimen and simulation. The corresponding saved run is
`run-20260907T043145Z-f6152b`, archived `loop-000001`, specimen
`specimen-cand-1-01-gyroid-bce35e6a`.

| Evidence | Verified fact |
|---|---|
| Specimen result | `runtime/loops/loop-000001/specimen_agent/attempt-000001/result.json` identifies the specimen STL |
| Analysis CAE request | The archived Analysis result references exactly the same resolved STL path |
| STL | `runs/run-20260907T043145Z-f6152b/specimens/specimen-cand-1-01-gyroid-bce35e6a/specimen.stl` |
| STL SHA-256 | `49364c80e36091768cc931c3fdd468f1d8dde6652baa9f6c0288315c1b8bec9d` |
| Raw CSV | `artifacts/equipment/equipment-9f72370ba826471b8f2487a225d14a51-segment-001/utm/live_run-20260907T043145Z-f6152b_specimen-cand-1-01-gyroid-bce35e6a_loop-0001_rep-0001.csv` |
| CSV SHA-256 | `c0305780455d1ba2af0ce734ffce1fa904c5a4e8434bc73fe37ecd27e415e17e` |
| Physical same-STL identity | Operator attestation on 2026-09-09; distinct from filesystem identity checks |
| Archived simulation mode | `deterministic_quasistatic_equivalent`, not a saved real CalculiX FRD |

The current parser and metric functions were called read-only, without
`AnalysisAgent.run()`, LLM, solver or device invocation. The source/result/STL/CSV
hashes were checked again afterward and remained unchanged.

| Recomputed quantity | Result |
|---|---:|
| Valid curve points | 2,113 |
| Initial apparent area | 900 mm² |
| Initial gauge length | 30 mm |
| Recorded evaluation displacement limit | 15 mm |
| Peak force inside that interval | 6,385.264 N |
| Integrated energy inside that interval | 52,420.871477 mJ |
| Engineering energy density | 1.941513759 MJ/m³ |
| Relative F-D/S-S energy identity error | < 1e-8 |

These are the saved experiment profile's values, not universal framework
defaults. The paired CSV/STL is useful input for future controlled FE comparison.
The old equivalent simulation must not be relabeled as independently validated
finite-element material calibration. One acquisition cannot supply both an
independent training set and a held-out experimental validation set.

## Verification Layers

| Layer | Checks | Evidence boundary |
|---|---|---|
| Decision protocol | Allowed options, malformed replies, forbidden parameter/tool injection, virtual labeling | Injected model replies; not fresh API/local-model inference |
| Runtime integration | Finalized Design scope, frozen registry, independent acquisition identity, blocked-next-loop handoff, store-error containment | Software/injected computation |
| Background lifecycle | Durable queue, bounded execution, model promotion gates, separate validation evidence, restart/cancellation | Synthetic numeric solver callbacks; not calibrated material truth |
| Saved project archive | Same STL reference, current CSV parsing/metrics, hashes unchanged | Real prior measurement; no new experiment |
| FRD converter | Literal tetra fields, rounding-aware identity, missing/unsupported data, mesh validity and budgets | Numerical serialization contract |
| Public real FRD | Archived CalculiX 2.22 C3D4 result, original field values | External solver output, not this project's specimen |
| Viewer | Isolated headless browser, exact scalar/range helpers, linear volume slice, read-only API limits and 4K PNG | Display/geometry correctness; not commercial parity |

Focused evidence at implementation time:

- `tests/integration/test_analysis_saved_archive.py`: 1 passed; optional local
  evidence test skips when the preserved run is not installed.
- Field converter, field-view helpers and isolated browser: 22 passed after
  the independent review fixes.
- `tests/integration/test_cae_fields_api.py`: 2 passed, including actual archived
  FRD export at 3840×2160 and 300-dpi metadata.
- `tests/unit/test_planning_analysis_curve_js.py`: 3 passed, including the
  always-accessible Live Analysis field-viewer entry.

Expanded combined regression: **213 passed, 39 warnings in 11.74 seconds**, exit 0.
Independent final review found no remaining high-severity blockers in the scoped
changes. Existing Pydantic schema-name and PyTorch warnings and upstream VTK/NumPy
and Starlette/httpx deprecations are not suppressed.

```bash
.venv/bin/python -m pytest \
  tests/unit/test_analysis_runtime.py tests/unit/test_analysis_refinement.py \
  tests/unit/test_analysis_improvement.py tests/unit/test_analysis_agent.py \
  tests/unit/test_analysis_decisions.py tests/unit/test_multifidelity_contracts.py \
  tests/unit/test_knowledge_agent.py tests/unit/test_guardian_agent.py \
  tests/unit/test_bo_agent.py tests/unit/test_calculix_fields.py \
  tests/unit/test_calculix_field_scaling.py tests/unit/test_calculix_execution_limits.py \
  tests/unit/test_calculix_quasistatic.py tests/unit/test_cae_tools.py \
  tests/unit/test_cae_field_view.py tests/unit/test_cae_fields_js.py \
  tests/unit/test_planning_analysis_curve_js.py \
  tests/integration/test_analysis_saved_archive.py \
  tests/integration/test_cae_field_browser.py tests/integration/test_cae_fields_api.py \
  tests/integration/test_objective_compiler_closed_loop.py \
  tests/integration/test_all_agent_loop_archives.py \
  -q --tb=short
```

The five changed governed documents passed focused documentation validation.
The repository-wide documentation validator still reports 27 pre-existing
contract errors in the unchanged Windows PyAutoGUI Reference and PLC design.
Those unrelated documents were not rewritten in this task. This is a focused
non-actuating regression suite, not a claim that the entire repository test
suite or a live physical graph was rerun.

The expanded compiled-objective integration initially reproduced an existing BO
metric mismatch with both current and baseline Analysis. For an active binding
from the registered ObjectiveService only, BO now matches Analysis' evaluated
`objective_score`; ordinary physical objectives and all observation gates remain
unchanged. The existing compose→Analysis→Knowledge→BO→objective-store-restart
test now passes. All ten agents' two-loop archive-entrypoint tests also pass at
their explicit non-actuating provider boundary.

## Actual Field Archive and Visual Inspection

The public [pyvista-frd-reader generated fixtures](https://github.com/pyvista/pyvista-frd-reader/tree/main/tests/fixtures/generated)
provide `src/tet4.inp` and `tet4.frd` from CalculiX 2.22. Their local validation
copies are `/tmp/atr-real-tet4.inp` and `/tmp/atr-real-tet4.frd`.

| Source | SHA-256 |
|---|---|
| INP | `11e98faa9b2e3f041e6421059b5d9c5b169a89f98f0e4ce732c563adb5a0386a` |
| FRD | `e9cbc2251b2c8882c91993f0657b998977cdcf8dcd27418264fc522ac572f600` |

Conversion retained four nodes, one tetra and three load-step frames. In the
first frame node 4 U3 is 0.00176871 mm; node 1 S_MISES is 57.1429 MPa, independently
consistent with the equal lateral normal stresses and zero shear in the source.
INP coordinates are authoritative; FRD coordinate comparison accounts for the
printed decimal precision rather than rejecting ordinary serialization rounding.

The isolated browser screenshot `/tmp/atr-cae-field-viewer-fixture.png` and
real-FRD export `/tmp/atr-analysis-real-frd-4k.png` were visually inspected.
The latter is a uniform-stress single tetra and only demonstrates the real-field
pipeline, annotation and export format. Neither image is representative lattice
contour-quality validation. Stress provenance follows CalculiX's
[element-output definition](https://www.feacluster.com/CalculiX/ccx_2.18/doc/ccx/node264.html):
FRD element variables are averaged at nodes. Named tensor components and derived
Mises are available; an ambiguous vector norm of packed tensor values is disabled.

## Limitations and Next Evidence

Fresh registered API/local-model calls, user contour approval, and independent same-STL material-model
validation remain outstanding evidence. Installing/viewing these changes does
not promote a candidate model automatically. A valid independent dataset and
explicit admissible candidate bounds are required before a background study can
justify promotion.

## Same-STL Compression Calibration Study

The subsequent study uses the operator-identified specimen and CSV above, the
registered CalculiX executable, and isolated outputs under
`artifacts/analysis_validation/20260909-specimen-1/`. Its
`study-summary/report.md`, `comparison.json`, comparison CSVs and PNG/PDF record
the actual last converged interval of each candidate. This is calibration against
one acquisition, not independent experimental validation or a promoted live model.

### Geometry and mesh checks

The optional study uses `pymeshlab==2025.7.post1` surface remeshing followed by the
existing Gmsh/CalculiX path. Source geometry is never overwritten. Surface
watertightness, Euler characteristic, volume and bidirectional vertex-to-surface
distance are checked before volume meshing. The latter is a sampled distance,
not a certified continuous Hausdorff bound.

| Mesh | Volume elements | Minimum corner-scaled Jacobian | Fraction below diagnostic 0.2 |
|---|---:|---:|---:|
| Original simplified surface | 125,334 | 0.00000196 | 7.490% |
| Accepted 0.6-mm remesh | 159,757 | 0.00186662 | 1.022% |
| 0.5-mm remesh | 231,806 | 0.00289966 | 8.248% |

The accepted 0.6-mm surface changes volume by +0.484% with maximum measured
vertex-to-surface distance 0.0865 mm, within this study's 1%/0.1-mm bounds.
Coarser 0.7/0.8-mm surface trials failed distance checks. The 0.4-mm trial exceeds
the existing field element budget and is not an accepted field dataset. Finer
mesh size alone is therefore not used as evidence of better quality or converged
response. These are geometry/quality checks, not three completed FE convergence runs.

The [CalculiX manual](https://www.dhondt.de/ccx_2.22.pdf) identifies C3D4's stiffness
limitation and recommends quadratic elements for general structural work. These
trials retain C3D4; no quadratic-element validation is claimed. The conditioning
script is an isolated research artifact, not a new automatic live remeshing stage.

### Material and computation contract

Printed-PLA compression can exhibit print- and rate-dependent post-yield behavior
([Scipioni and Lambiase, 2023](https://link.springer.com/article/10.1007/s00170-023-11985-y)).
The study tests bounded effective material hypotheses, including a post-yield
stress/plastic-strain curve; literature values are not presented as measurements
of this specimen. The explicit lattice response is not reused as a solid-PLA law.
Local softening remains mesh-sensitive without a regularization model.

The frictionless end-face approximation is retained, without new platen contact,
self-contact, damage or assumed measured fixture compliance. End-face node-band
width is recorded per trial. The original four-thread run produced a native
SPOOLES error. That error did not recur in the bounded single-equation-thread
trials, but nonlinear cutbacks and time limits remain separate issues.

The registered request now supports independent equation-solver thread limits
without changing global environment/defaults. Explicit increment settings survive
the CAE facade, and the displacement ramp spans the requested step period.
Stress/plastic-strain tables are validated and passed unchanged through bounded
candidate selection, facade normalization and deck creation. Tests cover the
real transformations with only numerical execution substituted.

Large-mesh field parsing no longer rebuilds the node-key set for each element.
Observed parse times were 0.38 seconds for the original mesh and 0.56 seconds for
the accepted remesh; these are local timings, not whole-solve speed claims.
Independent review found no critical/important defects in these scoped changes.

### Measurement coordinates

The initial force offset is 1.3636 N. An experiment-only 63.85264-N contact
threshold identifies raw stroke 1.94855 mm. On post-contact compression 0–15 mm,
measured peak force is 6,383.9004 N and loading work is 60.10828392 J. The archived
raw-stroke-window BO work remains **52.42087148 J**; it is not overwritten by
the contact-aligned diagnostic. Its matching FE endpoint would be 13.05145 mm.

Only the shared measured/computed interval is scored for partial solves. Missing
curve tails are not extrapolated, and full-target error/energy remain unavailable
until covered. Loading work is not labeled irreversible dissipation without an
unloading measurement. Original STL/CSV hashes and physical-loop configuration
remain unchanged.

### Finished bounded trials

The operator selected **Remeshed FE, yield 35 MPa** as the retained comparison
baseline on 2026-09-09. Its source is `isotropic-solve` with the `isotropic-06`
mesh in the study archive; `material_study_contract.json` records the selection.
This preserves a reference for further improvement without changing live defaults
or claiming full-range calibration.

All comparison intervals below are post-contact compression. Each row uses its
own common measured/FE interval; rows with different endpoints are not a ranking
of full-range fit quality.

| Candidate | Last converged compression | Peak error on common interval | Loading-work error on common interval | End condition |
|---|---:|---:|---:|---|
| Original mesh / material | 0.951709 mm | −13.62% | +27.42% | Native solver error |
| Remeshed / yield 35 MPa | 5.773938 mm | −12.95% | −0.22% | 600-second time budget |
| Remeshed / yield 55 MPa | 8.333314 mm | +26.82% | +63.85% | Deliberately rejected and stopped for poor agreement |
| Remeshed / post-yield curve | 2.819026 mm | −2.26% | +7.36% | 900-second time budget |

The post-yield candidate's common-interval peak is 6,239.7 N versus measured
6,383.9004 N. Work is 13.61351121 J versus 12.68000375 J; force-curve RMS error
is 587.66 N. These are partial-range calibration results, **not** 15-mm energy
validation. Repeated nonlinear cutbacks consume the time budget. This does not
establish that the remaining range is impossible to solve, or that more runtime
alone would give physical agreement.

The final converged displacement/stress frames are exported under each completed
trial's `specimen-1.fields/`, `stress.png` and `displacement.png`; the post-yield
candidate and rejected yield-55 candidate retain their raw solver histories and
receipts. No candidate reaches the full target here, so none is promoted. The
next unresolved work is full-range nonlinear calculation and mesh/increment
sensitivity before further parameter identification, followed by independent
experimental validation. Existing loop/BO behavior is not replaced by these trials.

## Reproduction

Use the project `.venv`; install `requirements-cae-viewer.txt` for native
postprocessing. Optional browser tests require the Playwright Chromium install.
Tests use isolated routes and literal fixtures; archived-evidence tests skip
when their local-only sources are absent. The original saved run must not be used
as a new Analysis output directory.

See the [implementation plan](../../superpowers/plans/2026-09-09-analysis-background-improvement.md)
and [Analysis Reference](../../agents/analysis_agent.md) for lifecycle and tool
contracts. This evidence does not supersede the prior physical-cycle record.
