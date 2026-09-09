---
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience: [researcher, developer, reviewer]
scope: [analysis, fem, calibration, independent_validation]
summary: Feature-informed inverse FEM implementation and same-acquisition numerical study; independent prediction remains separate.
evidence_date: 2026-09-09
method: Test-driven numerical and orchestration checks, independent code review, registered LLM decisions and isolated native FEM.
related_docs:
  - docs/agents/analysis_agent.md
  - docs/paper/evidence/2026-09-09-analysis-improvement-validation.md
  - docs/superpowers/plans/2026-09-09-feature-informed-fem-calibration.md
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
