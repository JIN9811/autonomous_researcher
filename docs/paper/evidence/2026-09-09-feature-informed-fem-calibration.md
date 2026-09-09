---
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience: [researcher, developer, reviewer]
scope: [analysis, fem, calibration, independent_validation]
summary: Feature-informed FEM workflow and a new completed sparse post-yield forward study; independent prediction remains separate.
evidence_date: 2026-09-09
method: Test-driven numerical and orchestration checks, independent code review, registered LLM decisions and isolated native FEM.
related_docs:
  - docs/agents/analysis_agent.md
  - docs/paper/evidence/2026-09-09-analysis-improvement-validation.md
  - docs/superpowers/plans/2026-09-09-feature-informed-fem-calibration.md
  - docs/superpowers/plans/2026-09-09-sparse-native-fem-improvement.md
supersedes: []
---

# Feature-informed FEM Calibration

## Evidence boundary

The measured curve is a calibration target, not a constitutive input. The study
changes parameters of an analytic material law and evaluates the resulting
forward FEM response. No force-output multiplier, fitted displacement shift,
physical device command, baseline promotion or historical BO rewrite is used.
One acquisition supports calibration research, not independent predictive
validation. Software tests do not establish material truth.

## Retained experiment and baseline

The paired physical acquisition is `run-20260907T043145Z-f6152b`, loop 1,
specimen `specimen-cand-1-01-gyroid-bce35e6a`. Its source STL SHA-256 is
`49364c80e36091768cc931c3fdd468f1d8dde6652baa9f6c0288315c1b8bec9d` and CSV
SHA-256 is `c0305780455d1ba2af0ce734ffce1fa904c5a4e8434bc73fe37ecd27e415e17e`.

This case uses the planned initial height of 30 mm and area of 900 mm², with a
15 mm comparison endpoint. These are case values, not framework constants.
The preserved contact convention subtracts the first force baseline, 1.3636 N,
and uses the first crossing of `max(2 N, 1% of raw peak force)`, at raw stroke
1.94855 mm. Both baseline and candidates use this same convention.

| Quantity | Paired experiment / retained baseline |
|---|---:|
| Measured peak force | 6,383.9004 N at contact displacement 1.820075 mm |
| Measured work, contact displacement 0–15 mm | 60.1082839245 J |
| Retained yield-35 FE peak force | 5,674.165 N at 8.109375 mm |
| Retained yield-35 FE work | 76.2796795884 J |
| Retained yield-35 FE errors | Peak −11.12%; work +26.90%; normalized force RMSE 24.84% |

The archived BO objective uses its original recorded-stroke convention and
remains 52.420871477 J. It is not replaced by the contact-referenced comparison.
The older manually specified softening table was a hypothesis, not identified
material data; its short-range fit is not full-domain validation.

## Model hypothesis and search

This pilot is retained as an unvalidated hypothesis, not the adopted model.
The subsequent mechanism-first contract below supersedes admission based only
on a paired lattice curve and bounded parameters.

The first pilot uses `q(p) = q_res + (q_peak − q_res) exp(−p / p_decay)`.
Elastic modulus and Poisson ratio remain at the existing case values, 1,800 MPa
and 0.35. Geometry, frictionless axial face constraints, isotropic surface remesh
at 0.6 mm and requested endpoint remain fixed.

| Parameter | Initial hypothesis | Study bounds |
|---|---:|---:|
| Initial true flow stress | 60 MPa | 35–80 MPa |
| Residual true flow stress | 25 MPa | 15–40 MPa |
| Equivalent plastic strain decay scale | 0.10 | 0.04–0.25 |

These values are initialization/bounds, not a material-property measurement or
a direct literature extraction. The three-evaluation pilot evaluates the seed
and residual-flow sensitivity first. It is not a converged search over all three
parameters. Every eligible candidate requires an actual full-domain native solve.
Local softening is unregularized: it can be mesh-dependent and cannot be
promoted merely because this acquisition fits.

The literature supports investigating printed-polymer yielding/post-yield
mechanisms and their dependence on manufacturing structure; it does not supply
the parameter values above. See [Scipioni and Lambiase (2023)](https://link.springer.com/article/10.1007/s00170-023-11985-y).
Inverse FE identification compares forward predictions with experimental
observables rather than converting a specimen response directly into a material
law; see [Gelin and Ghouati (1995)](https://www.sciencedirect.com/science/article/abs/pii/S000785060762304X).

## Prompt protocol

The Analysis LLM receives compact numerical features, immutable conditions,
registered action choices and past candidate evidence. The prompt distinguishes:

- calibration permission from material promotion or independent validation;
- mesh preparation/quality from three-resolution convergence;
- completion of a numerical job from acceptable physical agreement;
- material softening from geometric collapse;
- partial peak resemblance from full-domain curve/work agreement;
- retaining a research candidate from approving deployment.

The model cannot propose arbitrary material values, new tools or altered test
conditions. The deterministic search owns parameters and feature calculations;
the LLM authorizes and evaluates registered work. A hold stops further work and
does not produce an approved forward-material export.

## Initial calibration-protocol verification

Implementation checks cover exact feature units, common full-domain scoring,
equal-energy/wrong-shape rejection, bounded material generation, independent
source identity, proxy rejection, search improvement on a known synthetic
forward model, native cancellation ownership, non-terminal child progress,
hold decisions and export gating. Separate existing background/closed-loop
regressions passed without operating laboratory equipment.

Initial scoped regression: **173 passed**, 26 dependency warnings, 22.01 s,
including existing foreground/background and parallel closed-loop tests while
the isolated native study remained active. All four changed documents passed
the scoped documentation validator. These software checks do not imply zero
CPU/memory contention or a completed native calibration.

Registered API and local vLLM were tested separately, with backend fallback
disabled and no model-server lifecycle or global-configuration changes.

| Backend / registered model | Scenarios | Actual decisions | Individual response time | Full validation elapsed |
|---|---:|---:|---:|---:|
| API / `gpt-5.5` | 6/6 | 15 | 2.13–6.03 s | 51.74 s |
| Local vLLM / `gemma4:31b` | 6/6 | 15 | 3.30–19.91 s | 152.35 s |

The six scenarios cover one-acquisition calibration admission; concluding a
completed single-resolution computation without claiming agreement; holding an
equal-work/wrong-shape candidate; research retention without promotion; existing
mesh/solve dispatch using exact archived native receipts; and a two-candidate
calibration loop using a known analytic forward fixture. The last case exercises
actual calibration code and real model decisions, including final retention,
but its solver response is explicitly synthetic. Archived receipt replay is not
a fresh native solve. Neither case establishes independent physical prediction.

The compact prompt preserves quality gates, source identity, target coverage,
individual errors, best-candidate evidence and recent history; duplicated request
and field payloads remain in artifacts. Exact decisions and per-case receipts:
`artifacts/analysis_validation/20260909-calibration-dual-backend-02/`.
The reusable isolated checker is
`scripts/validation/check_analysis_calibration_backends.py`.

Native study directory:
`artifacts/runs/validation-fem-20260909-feature-calibration-01/`.
The pilot was cancelled through the existing compute owner after adopting the
mechanism-first admission requirement. Its first candidate reached 4.408996 mm
of the requested 15 mm, with 65 converged increments. Elapsed time was 2,164.29 s;
sampled peak process-tree RSS was 3,298,693,120 bytes (3.07 GiB). The partial peak
was 6,121.831 N at 2.273438 mm. The final status is `cancelled`; partial curve,
field files, native package and numbered receipts remain preserved. No second
candidate was run, no candidate was promoted, and no full-domain work or
prediction success is claimed.

## Mechanism-first revision

The ordinary remeshed baseline and measured Analysis → BO handoff remain unchanged.
`analysis_mechanism_assessment.v1` now separates numerical coverage, material-source
support and a referenced deformation comparison. LLM evidence requests are
non-actuating; partial candidates terminate parameter search even when the model
concludes the individual numerical job. Missing material evidence prevents
constitutive fitting and usable candidate export, rather than being replaced by
a guessed softening table.

Mechanism-first final regression: **196 passed**, 26 dependency warnings, 21.38 s.
This includes ordinary FEM, calibration, runtime input freezing, CLI, report
export, foreground/background and parallel software closed-loop tests. Independent
review confirmed corrections for reference forwarding, partial-result gate
propagation and geometry/measurement-copy rejection. No new native solve or
physical device operation was performed for this revision.

Final mechanism-first real-model verification:

| Backend / model | Scenarios | Actual decisions | Individual response time | Total elapsed |
|---|---:|---:|---:|---:|
| API / `gpt-5.5` | 10/10 | 19 | 2.11–11.01 s | 79.69 s |
| Local vLLM / `gemma4:31b` | 10/10 | 19 | 4.14–21.26 s | 186.18 s |

Both runs disabled fallback. Seven controlled decision scenarios covered
supported research, missing material characterization, deformation mismatch,
partial-solve diagnosis, wrong-shape rejection, research retention and numerical
completion. The remaining cases used archived native tool receipts, the actual
retained acquisition with unsupported softening (held with **zero solver calls**),
and a two-candidate analytic forward fixture. This is real model inference plus
software/archived evidence, not new physical or native-FEM validation.
Receipts: `artifacts/analysis_validation/20260909-mechanism-dual-backend-02/`.

| Research principle | Implemented boundary |
|---|---|
| Separate material and lattice response | Independent coupon identity or applicability-reviewed literature prior; source hashes and explicit characterization declarations |
| Check collapse mechanism | Referenced deformation comparison; unknown/mismatch cannot authorize material fitting |
| Diagnose numerical failure first | Incomplete native candidate stops search and requests solver diagnostics |
| Check discretization and transfer | Existing mesh study retained; unregularized softening never becomes independently validated by fit alone |
| Respect actual capabilities | Explicit, regularized damage and self-contact are not implemented by this revision |

References are frozen into each job's existing input directory. Hash identity
prevents a renamed copy of the specimen STL or known target CSV from becoming
independent material evidence. These checks validate provenance and declared
applicability, not the scientific truth of a coupon report. No independent
coupon/deformation characterization has been supplied for the retained physical
acquisition, so that acquisition cannot currently authorize the softening search.

The modeling rationale follows separate material characterization and lattice
prediction in [Abueidda et al. (2019)](https://doi.org/10.1016/j.matdes.2019.107597)
(PA2200, not PLA; a methodological reference). A PLA-family Gyroid study combines
material tests, deformation observations, contact and explicit computation:
[El-Asfoury et al. (2026)](https://www.nature.com/articles/s41598-026-35201-5).
Their material values and failure settings are not copied into ATR.
[Abaqus quasi-static explicit guidance](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEGSARefMap/simagsa-m-Quasi-sb.htm)
motivates energy/rate checks before considering a future explicit method;
[damage evolution guidance](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEMATRefMap/simamat-c-damageevolductile.htm)
motivates characteristic-length/energy regularization, not transplanting a
metal-specific damage model into PLA.

## Completed sparse post-yield forward study

The new native run `validation-fem-20260909-sparse-postyield-03` completed on
2026-09-09, separately from the cancelled exponential-law pilot and retained
yield-35 baseline. It tests the earlier manually specified post-yield hypothesis
over the **entire requested 0–15 mm domain**, not only the initial peak.
No physical device operated and the original STL/CSV hashes above remained unchanged.

### Declared model and discretization

The material fixture is
`scripts/validation/fixtures/analysis_postyield_forward_hypothesis.json`, SHA-256
`6f1191c1f9a37ebc39236b3a566f192ebd861a33dde31f214f2ea66b8b78f0e6`.
It supplies E = 1,800 MPa, ν = 0.35 and flow-stress/plastic-strain pairs
`(55, 0), (55, 0.02), (30, 0.15), (25, 0.4), (30, 1.0)`.
These values are an explicit research hypothesis, not independently measured
properties, identified calibration parameters or the experimental force curve
re-expressed as material input. Published compression work on printed PLA
supports considering processing-dependent post-yield softening, **not these
numerical values** ([PLA compression study](https://doi.org/10.1007/s00170-023-11985-y)).
Unregularized local softening remains mesh dependent. Calibration admission and
automatic-promotion gates are unchanged.

| Mesh quantity | New result |
|---|---:|
| Surface / volume nominal target | 0.8 mm |
| Local remesh-operation distance | 0.0275 mm |
| Nodes / C3D4 elements | 51,385 / 148,427; 7.10% fewer elements than baseline |
| Sampled bidirectional surface deviation | 0.095762 mm; unchanged limit 0.1 mm |
| Volume error | +0.046817% |
| Minimum / P1 / P5 corner scaled Jacobian | 0.001145 / 0.159268 / 0.209861 |
| Fraction below Jacobian 0.2 | 3.7406%; unchanged limit 5% |
| Validity | Watertight; topology preserved; no inverted/degenerate elements |

Coarser attempts with the original 0.05 mm local-operation distance were rejected
by the existing final geometry gate before solving. A 0.025 mm attempt passed
geometry but failed mesh quality. Their receipts remain in `sparse-reference-01`
through `03` and `sparse-postyield-01` through `02` under `artifacts/runs/`.
No acceptance threshold was relaxed to admit the final case. Local operation
distance is not a global final-distance guarantee
([MeshLab filter contract](https://pymeshlab.readthedocs.io/en/latest/filter_list.html#meshing-isotropic-explicit-remeshing)).

### Full-domain measured comparison

The same contact convention, planned dimensions and comparison domain apply
to both FEM runs. No extrapolation, force multiplier or fitted horizontal shift
is used. Native convergence reached 182 increments / 183 curve points.

| Quantity | Experiment | Retained completed baseline | New completed study |
|---|---:|---:|---:|
| Peak force (N) | 6,383.9004 | 5,674.165 | 6,234.689 |
| Peak location (mm) | 1.820075 | 8.109375 | 2.090625 |
| Peak error | — | −11.12% | **−2.34%** |
| Work (J) | 60.1082839245 | 76.2796795884 | 72.7801440121 |
| Work error | — | +26.90% | **+21.08%** |
| Curve RMSE (N) | — | 1,585.82 | **986.01** |
| RMSE / measured peak | — | 24.84% | **15.45%** |

Peak magnitude and location improve; full-domain RMSE decreases by 37.82%.
The post-peak response remains too stiff/high, with work overprediction of 21.08%.
This is improved same-acquisition forward agreement, **not completed physical
calibration or independent prediction**. Only one resolution was solved.
The new [comparison and final-frame contours](../../agents/analysis_agent.md#new-completed-native-result--sparse-post-yield-study)
are checked into Git; earlier baseline figures remain separately labeled.

### Execution, recovery and concurrency evidence

| Observation | Measured result |
|---|---:|
| Native start / finish (UTC) | 09:35:40 / 10:44:44, 2026-09-09 |
| Native elapsed | 4,143.96 s (69.07 min) |
| Study elapsed | 4,240.95 s (70.68 min) |
| Peak sampled process-tree RSS | 2,339,438,592 bytes (2.18 GiB) |
| Observed cumulative CPU | 4,560.21 CPU-s |
| Resource sampling | 4,189 samples at 1 s; six observed processes |
| Assembly / equation-solver threads | 4 / 1 |
| Saved-result API review | 8.06 s; no native rerun |
| Two concurrent software loops | 28.22 s; native CPU ticks 2,072 → 5,076 |

Despite fewer elements, the nonlinear hypothesis took more increments/cutbacks
than the retained baseline and increased total time/memory. Neither speedup nor
an isolated mesh-cost effect is established. Resource scope excludes external
LLM servers; summed RSS may duplicate shared pages and sampled CPU is a lower bound.

The first final API review returned an empty response **after successful native
completion**. Its failed `result.json` remains intact. The existing saved-result
review path produced `result-review/result.json` with numerical completion and
no promotion; it did not rerun FEM. A regression-tested runtime change now
preserves completed numerical evidence on review exceptions, marks the review
failed, and holds further action. Initial decision failure calls no solver;
cancellation is not swallowed.

While this exact native process was computing, the production software graph
completed two loops with non-actuating hardware/model fixtures. Native PID
3239654 and start identity 46702614 were unchanged while CPU ticks increased.
Design, Analysis, Knowledge, BO and graph transitions used production code;
this demonstrates computation/foreground overlap, not concurrent physical operation.

Final scoped regression: **245 passed**, 26 dependency warnings, 30.47 s.
Registered real inference, with fallback disabled, separately passed **10/10
scenarios and 19 decisions per backend**: `gpt-5.5` API in 77.67 s and managed
vLLM `gemma4:31b` in 192.09 s. These use controlled/archived evidence and do not
constitute a second native run or physical validation. The unsupported actual
calibration case still held with zero solver calls on both backends.

### Artifact inventory

Large files remain local under
`artifacts/runs/validation-fem-20260909-sparse-postyield-03/`:

- `001-cae-prepare_static_analysis.result.json`, `002-cae-run_static_analysis.result.json`: actual accepted preparation and completed native execution.
- `inputs/`, `evidence.json`, `run_metadata.json`: frozen acquisition and declared hypothesis, input provenance and source-hash audit.
- `cae/calculix/`: native deck/mesh, DAT/STA/FRD, full curve, fields and reusable model package.
- `result.json`, `result-review/result.json`: original review failure and successful saved-evidence review, retained separately.
- `report/metrics.json`, `report/provenance.json`, `report/shared_points.csv`: full-domain calculations and source/frame provenance; PNG/PDF exports alongside.
- `resources_summary.json`, `parallel-proof/`: process measurements and actual native/software-loop overlap receipt.
- Real-model receipts: `artifacts/analysis_validation/20260909-sparse-dual-backend-01/`.

The published figures are actual recomputed output, not renamed retained-baseline
images. Source data, original BO observations and historical reports are unchanged.
