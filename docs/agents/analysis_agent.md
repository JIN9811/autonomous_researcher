---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, developer, reviewer, operator]
scope: [agents, analysis, experimental_data, cae, model_improvement]
summary: Measured BO handoff independent of cancellable background FEM, bounded evidence-driven decisions, immutable model improvement, and read-only Live result cards.
source_of_truth:
  - agents/analysis_agent.py
  - agents/analysis_decisions.py
  - agents/analysis_improvement.py
  - agents/analysis_refinement.py
  - agents/analysis_runtime.py
  - agents/analysis_fem.py
  - app/analysis_fem_routes.py
  - utils/cae_model_package.py
  - web/static/analysis_fem_live.js
  - graphs/modules/analysis/module.yaml
  - utils/calculix_fields.py
  - utils/cae_field_view.py
  - app/cae_fields_routes.py
  - orchestrator/langgraph_runtime.py
last_verified: 2026-09-09
verified_against: working-tree-2026-09-09-nonblocking-fem-live-cards
related_docs:
  - docs/agents/README.md
  - docs/agents/equipment_agent.md
  - docs/agents/bo_agent.md
  - docs/agents/knowledge_agent.md
  - docs/device_bridges/cae_computation_bridges.md
  - docs/superpowers/specs/2026-09-09-analysis-multifidelity-decision-design.md
  - docs/paper/evidence/2026-09-09-analysis-improvement-validation.md
supersedes: []
---

# Analysis Agent Reference

## Status at a Glance

- Runtime status: Measured handoff and independent background FEM implemented / non-actuating regression verified
- LLM decision layer: Bounded roles / real API mesh preparation, quality assessment and saved-result review verified
- Physical effect: None; registered solver computation only
- Primary handoff: Measured objective and evidence → Knowledge / BO
- Live hardware validation: Prior complete cycle preserved; no new hardware execution
- Known gap: Full-range FE completed; agreement and mesh convergence remain unvalidated (work error +26.9% in the case below)

## Overview and Responsibilities

Analysis processes Equipment measurements and returns an evidence-bearing BO
observation without waiting for optional FEM. The next physical loop may proceed
while an Analysis-owned worker prepares, assesses and solves the frozen specimen
model. Simulation-only/preflight paths still wait for the simulation that supplies
their data. Three internal LLM roles choose actions; deterministic tools calculate
values. Running FEM and promoting a material model are separate operations.

| Area | Responsibility | Detail |
|---|---|---|
| High-Level Control | Assess measurement admissibility, simulation action, and candidate promotion within the assigned task | [Decision and evaluation](#decision-and-evaluation) |
| Middle-Level Control | Order measurement parsing/validation and handoff; independently schedule staged FEM and optional model studies | [Internal workflow](#internal-workflow) |
| Low-Level Control | Existing parser, numeric tools, registered CAE prepare/solve, and field postprocessing | [Tools and connections](#tools-apis-and-connections) |
| Guardian / Safety | Identity, units, curve coverage, numerical and budget gates; immutable loop model | [Safety and recovery](#safety-and-recovery) |
| Knowledge / Evidence | Raw hashes, decisions, acquisition lineage, jobs, candidate versions and validation records | [Artifacts and verification](#artifacts-and-verification) |

These are responsibility areas, not five sequential graph nodes. Analysis does
not redesign specimens, operate laboratory equipment, or replace BO's candidate
selection. Its external graph node and existing device connections are unchanged.

## Closed-Loop Position and Handoffs

![Analysis closed-loop position and handoffs](assets/figures/analysis_01_closed_loop_handoffs.svg)

**Figure Analysis-1.** Current implementation `inspection`: the foreground
measurement path returns to Knowledge/BO, while frozen evidence feeds a separate
background FEM study. A separately validated model candidate affects a later loop, not the
measurement that trained it. Dashed edges denote conditional background work.

| Boundary | Contract | Authority |
|---|---|---|
| Equipment → Analysis | Raw file, source hash, specimen/acquisition context, completed handoff | Equipment owns acquisition and completion |
| Design/runtime → Analysis | Geometry, initial dimensions, loading, material and bound objective | Analysis cannot rewrite the experiment |
| Analysis → CAE | Existing registered payload with frozen model version and resource limits | Computation bridge owns processes |
| Analysis → BO | Explicit physical/compiled objective, measured source, validity and artifact references | Improvement failure is not a substitute observation |
| Analysis → background FEM | Frozen CSV/STL hashes, run/loop/specimen/job, fixed loading/material, finite mesh candidates | No mutable live state or device tools; no material promotion |
| Analysis → optional refinement | Admissible parameter candidates, independent acquisition evidence and validation scope | Independent-validation gates remain separate from FEM execution |
| Background → later loop | Validated immutable model version | Registry selection is frozen at loop boundary |

## Internal Workflow

### Foreground

1. Freeze the available model registry at the loop boundary; resolve the
   completed Design's model scope when Analysis starts.
2. Receive Equipment evidence; verify source, parsing, units, geometry and
   existing completion gates.
3. With valid Equipment measurements, skip optional foreground CAE. Only a
   simulation-only/preflight branch selects and awaits its required CAE data source.
4. Data-role LLM selects analysis or holds. Existing numeric routines construct
   canonical force-displacement and engineering stress-strain curves and metrics.
5. Data-role LLM assesses the supplied quality evidence. Code-owned checks
   constrain acceptance; a blocked result clears current BO eligibility.
6. Persist the ordinary Analysis result and measured handoff, then register the
   frozen background FEM job without awaiting preparation or solving. A queued,
   partial, failed or cancelled FEM job does not revise that measured BO result.

The module's 22 internal entries remain a descriptive execution inventory, not
22 independently scheduled agents. Its legacy labels referring to uncertainty
or refinement do not imply a statistical estimator or a synchronous optimization
loop. The Python handler is authoritative.

![Analysis execution and effect boundary](assets/figures/analysis_02_execution_effect_boundary.svg)

**Figure Analysis-2.** Current `inspection` projection separates LLM choices
from numeric execution and foreground handoff from asynchronous improvement.
Hard gates surround both paths. Effects are local artifacts and registered
computation, not laboratory actuation.

### Background FEM: one acquisition is sufficient to execute

`run_fem_study(evidence, choose, call_tool, emit)` uses only injected registered
tools and bounded decisions. No independent holdout is required to inspect or
solve one acquired specimen; it is required for a separate material promotion.

1. Verify frozen input hashes before every native call. `fem_mesh` selects
   `cae.prepare_static_analysis` or holds. Each attempt gets a job-derived unique
   output identity while retaining the original specimen identity.
2. Preparation returns a reusable `prepared_input` receipt and deterministic
   mesh validity/quality evidence. `fem_mesh_assessment` selects solve, remesh,
   convergence study or hold only from the currently permitted options. An invalid
   mesh cannot run. Poor/unknown quality requires remesh or hold and requests
   convergence evidence; model prose cannot waive these gates.
3. `cae.run_static_analysis` reuses the assessed prepared mesh. Material, loading,
   objective and source geometry stay fixed. Refinement changes the declared
   volume and surface-remesh resolutions together, not the specimen identity.
4. Retain the actual force-displacement history, field artifacts and endpoint
   status, including a partial history from an unsuccessful solve. Calculate
   comparison metrics over the measured/solved overlap; never extend a partial tail.
5. `fem_result` supplies those actual curves, comparisons and available field/image
   evidence to the LLM, which selects further convergence work, conclude or hold.
   Summary numbers are code-calculated, not generated by the narrative.

Mesh quality is not response convergence. The current convergence check requires
at least three distinct resolutions reaching the same complete planned target.
Both successive refinement comparisons must meet the declared tolerance for peak,
work and peak-normalized force RMSE. Missing/partial results yield insufficient
evidence, not convergence; this check is not GCI or physical model validation.

The study has no wall-clock deadline. The application serializes native FEM
execution and releases the LLM lease during native computation. Cancellation,
finite mesh/action/job counts, solver increment/termination rules, mesh-element
limits and thread limits remain active. A request that itself needs simulation
can still wait for computation admission; the measured CSV-to-BO path does not.

### Optional material improvement: separate promotion gates

| Phase | Work | Acceptance boundary |
|---|---|---|
| Intake | Preserve immutable inputs and independent acquisition identities | Same CSV does not become a new experiment when reanalyzed |
| Assess | LLM selects from registered, bounded candidates | Missing paired data or bounds → `needs_more_data` |
| Study | Existing solver runs candidate/mesh studies under finite budgets | Converged real-solver curves required; proxy output is insufficient |
| Select | Compare candidates using training measurements | Common measured domain; no extrapolation |
| Validate | Evaluate the selected candidate on separate experimental evidence | Training and validation acquisitions must be distinct |
| Promote / hold | LLM recommendation plus deterministic validation gates | Immutable version; tested parameters/mesh; next-loop application only |

The initial method supports bounded material-parameter candidates and a
three-resolution mesh study. It does not autonomously invent constitutive
equations, add contact models, train a PINN, or write solver code.

This refinement path remains available for admissible candidate/holdout studies.
The background FEM job does not calibrate or promote material, even if its
comparison improves. CPU/memory contention is still possible despite dependency
separation; concurrency control does not promise zero resource contention.

## Decision and Evaluation

### LLM role fit and tool authority

| Role / phase | Model decides | Code executes / forbids |
|---|---|---|
| Simulation analyst / `simulation` | Run required simulation-only/preflight CAE or hold | Not an optional FEM dependency of measured BO |
| Simulation analyst / `fem_mesh`, `fem_mesh_assessment`, `fem_result` | Prepare, assess actual mesh evidence, solve/remesh, request convergence or conclude | Registered prepare/solve only; invalid mesh and undeclared parameter changes forbidden |
| Measurement analyst / `data_processing` | Analyze the identified measurement or hold | Existing parser/normalization/metrics |
| Measurement analyst / `data_validation` | Accept or hold the computed evidence | Quality and handoff checks remain mandatory |
| Model/method analyst / improvement phases | Candidate study order, evidence assessment, promote/hold recommendation | Bounded numeric study and independent-validation gates |

Every request uses the existing `analysis_reasoning` model route. The response
is exactly `{"option_id": "...", "reason": "..."}`; options and associated tool
names are provided by code. Unknown actions, extra parameters, malformed output
and missing reasons are rejected. Artifact text is evidence, not instructions.
Explicit virtual-test mode labels its deterministic selection `virtual_test`,
not an LLM verification.

### Quantities and consumers

| Quantity | Definition / domain | Consumer |
|---|---|---|
| Engineering stress | `sigma = F / A0`, MPa for N and mm² | Curve display, objective calculation |
| Engineering strain | `epsilon = displacement / H0` | Comparison axis and bound evaluation domain |
| Absorbed energy | `W = integral F d(displacement)`, mJ | Physical report and dimensional check |
| Energy density | `U = integral sigma d(epsilon)`, MJ/m³ | Current compression profile's BO objective |
| Peak force | Maximum inside the profile's evaluation displacement interval | Measurement/CAE comparison |
| Initial stiffness / apparent modulus | Existing initial-region regression / `E_app = k H0/A0` | Descriptive metrics; not certified elastic identification |
| Curve residual | Piecewise-linear common-domain RMS force difference, N | Background fitting and convergence checks |
| Statistical uncertainty | `null`, `uncertainty_status.status=not_estimated` without an estimator | Knowledge/Guardian do not interpret absence as zero error |
| Admissibility | `analysis_admissibility.v1`: gate plus explicit reasons | BO handoff eligibility |

Initial area and height come from the current specimen specification. The
existing compression profile retains its legacy half-height metric names;
those constants are not injected into generic LLM prompts. A compiled objective,
when bound, takes precedence. The uncompiled path uses its physical energy
density rather than mixing unrelated metrics into an arbitrary score.

`W = A0 H0 U` checks the two energy representations. A missing evaluation
interval is not extrapolated. Simulation residuals, mesh convergence, data
quality and measurement uncertainty remain different facts. Historical weighted
trust/uncertainty records stay readable but are not recalculated as new evidence.

Background overlays state their coordinate convention. The runtime declares
contact-threshold alignment: use the full measured curve, subtract its initial
force baseline, and identify the first force crossing above
`max(2 N, 0.01 × raw peak force)`. Subtract that crossing displacement from the
comparison curve; do not optimize a shift to minimize residual. Raw measured
objectives remain unchanged. A direct study without a declared alignment uses
explicit raw displacement. The planned FE target is never shortened to the
measurement or a failed solver endpoint. Comparisons expose `end_mm`, signed
`peak_error_pct`/`work_error_pct` and `rmse_N`; unavailable quantities are null.

## Tools, APIs and Connections

![Analysis API and connection architecture](assets/figures/analysis_03_api_connection_architecture.svg)

**Figure Analysis-3.** `inspection` of existing model/tool routing and new
read-only postprocessing. The field viewer consumes saved arrays; it has no
solver execution or device command connection.

| Interface | Purpose | Effect |
|---|---|---|
| `AgentContext.complete("analysis_reasoning", ...)` | Role-specific bounded decision | Existing registered API/local model route |
| `cae.prepare_static_analysis` | Prepare and assess an isolated mesh/deck | Registered computation; returns reusable receipt and mesh evidence |
| `cae.run_static_analysis` | Solve the prepared mesh, or existing explicit simulation request | Registered computation with preserved mode/runtime gates |
| `GET /api/analysis/fem/jobs?run_id=…&loop_key=…&specimen_id=…` | Read current matching background jobs, progress, curves and attempts | Read-only SQLite lookup; never starts/resumes computation |
| `POST /api/analysis/fem/jobs/{job_id}/cancel?run_id=…` | Explicitly cancel the addressed Analysis computation | Job-specific computation cancellation, never hardware control |
| `GET/POST /api/cae/config` | Existing CAE workspace settings | Read / local settings |
| `POST /api/cae/run` | Existing explicit workspace computation | Solver/proxy according to configured mode |
| `GET /cae/results` | Field-result workspace | Read-only page |
| `GET /api/cae/fields` | Load `cae_fields.v1` inside artifact roots | Read-only |
| `GET /api/cae/fields/metadata` | Read lightweight field/frame metadata for Live navigation | Read-only; no solver |
| `GET /api/cae/fields/section` | Slice the actual tetra volume | Local numeric postprocessing |
| `GET /api/cae/fields/render` | High-resolution PNG | Local rendering; no solve |
| `GET /api/runs/{run_id}/artifacts` | Existing evidence retrieval | Read-only |

### Four persistent Live cards

The Live Analysis area always contains **Experiment vs FEM**, **FEM Response**,
**Solver Contour**, and **Agentic Progress**. Empty/pending/partial/failed states
are explicit. Previous/Next selects attempts inside the existing response and
overlay cards, and available attempt/frame contours inside the existing contour
card; new attempts do not create duplicate cards. Field controls select available
von Mises stress or displacement, with a link to the full field viewer. F-D/S-S
selection uses the declared specimen area/height, not fitted normalization.

Polling is bound to run/loop/specimen/job identity. Switching loops resets the
selection and rejects stale previous-loop results. Viewing, navigating, rendering
and retrying a contour never invoke Analysis or a solver. Progress records phase,
reason, quality, convergence and available resource observations. Native
`elapsed_s` is phase elapsed time; Linux `cpu_time_s` and `rss_bytes` are sampled
for the owned subprocess PID, not total-host or whole-descendant-tree usage.
CPU percentage is not inferred from CPU time; absent telemetry stays unavailable.

### Solver fields and visual semantics

The new viewer uses the original nodes, C3D4 connectivity and actual FRD arrays.
It supports orbit/pan/zoom, preset views, frames/playback, field components,
deformation scale, undeformed overlay, edges, probes, volume sections,
side-by-side comparison, shared/manual color ranges, saved view recipe and
3840×2160 PNG with 300-dpi metadata. Exports retain the selected camera, section,
field, scale and range; the output aspect ratio is fixed.

Available fields depend on the file: U, S, E, PEEQ and derived S_MISES are mapped.
Stress is explicitly **solver-extrapolated and nodally averaged**; Mises is
computed from that complete averaged tensor, not raw integration-point values.
A section probe is interpolated, whereas surface probes retain original node IDs.

Supported input is ASCII FRD with C3D4 topology under the bridge's mm/N/MPa unit
convention. Missing full-node displacement, unsupported topology, missing fields
and incomplete output produce explicit states. Old proxy SVGs are preserved as
historical artifacts and are not promoted to actual field results.

## Configuration and Operation

The existing experiment specification and selected CAE runtime own fixed physical
inputs. Background FEM uses `analysis_improvement.mesh_size_factors` (default
`[1, 0.75, 0.5]`), `max_mesh_actions` (default candidate count), `max_fem_jobs`
(default 3), `convergence_tolerance_pct` (default 5),
`mesh_quality_min_percentile_5` (default 0.1), and
`mesh_quality_max_bad_fraction` (default 0.05). These quality thresholds are
declared application policy for the reported corner-scaled-Jacobian diagnostic,
not universal element-quality or accuracy guarantees. `timeout_s: null` removes
the native deadline; no worker wall-clock cutoff replaces it.

The retained background reference uses explicit isotropic surface remeshing
(`edge_length_mm: 0.6`, `iterations: 8`, `max_surface_distance_mm: 0.05`) unless
the policy supplies another supported profile. Declared material remains intact.
The remeshed yield-35 MPa FE reference is a comparison baseline, not a promoted
or independently validated material model.

For the separate refinement path, optional `analysis_improvement` policy supplies
material `candidates`, per-parameter `bounds`, `max_solver_jobs`,
`max_wall_time_s`, `max_mesh_elements` and
`convergence_relative_tolerance`. No supplied bounds means no automatic fitting.
The supported material keys are `elastic_modulus_mpa`, `poisson_ratio`,
`yield_strength_mpa` and `plastic_curve`. The curve is a list of
`[true_flow_stress_MPa, equivalent_plastic_strain]` pairs, starting at zero
plastic strain with strictly increasing strain and positive finite stress.
Curve candidates additionally require explicit `flow_stress_mpa` and
`plastic_strain` bounds; every point is checked before registration. A supplied
curve takes precedence over the single-value perfect-plastic yield model.
The measured lattice S-S response is a calibration target, not a solid-material
input curve: copying it into an explicit lattice mesh would count the structural
compliance twice. A single paired test can support an isolated calibration study,
but cannot satisfy the background worker's independent-validation promotion gate.

Studies reuse the configured CAE mode and existing `runtime_solver_enabled`
gate; this change does not enable a real solver through a proxy/test-mode request.
Only actual converged solver results qualify for promotion. Optional
`solver_identity` enables durable cross-job result reuse; without an explicit
solver/build identity, reuse is limited to the current study.

Install `requirements-cae-viewer.txt` in the project environment for server-side
volume sections/rendering. The browser renderer is locally vendored. Open
**Solver Field Results** from the Live Analysis page or the CAE workspace;
the entry remains visible even when an old result has no field file.

## Safety and Recovery

- Preserve Equipment completion, source identity, unit and curve gates.
- Do not let LLMs mutate experiment geometry/loading, issue arbitrary commands,
  relax hard gates, or operate devices.
- Bound candidate/job counts and solver numerical/resources limits, not background
  FEM wall-clock duration; serialize native ownership. Interrupted
  jobs retain a distinct state instead of silently repeating successful work.
- Keep raw measurement and historical reports immutable. Failed improvement
  retains the baseline; promotion does not rewrite previous BO observations.
- Restrict field paths to artifact roots and reject unavailable/nonfinite values.
  Display or export operations never invoke a solver.

## Artifacts and Verification

| Record | Location / content |
|---|---|
| Existing Analysis artifacts | Run Analysis directory plus existing per-loop/attempt archive |
| Foreground decision evidence | Analysis report: decisions, model pin, source, metrics, handoff |
| Background evidence/jobs/models | Run-owned improvement store; frozen inputs, job receipts, candidate/validation versions |
| Background FEM attempts | Unique job/attempt IDs, mesh size/quality, real curve, overlap comparison, field path, solver status and endpoint flag |
| Solver evidence | INP, DAT, FRD, request and process logs |
| Reusable native model | `artifacts.model_package_path` and `model_package_manifest_path`; standalone deck, optional mesh/source/preparation copies, relative-file hashes and conditions |
| Field evidence | `<frd-stem>.fields/manifest.fields.json`, geometry/frames, source hashes and mesh diagnostics |
| Render evidence | Downloaded PNG and `cae_render_recipe.v1` |

### Reusable model artifact

Successful native preparation exports a self-contained model package before
solving; export errors are reported separately. `model.inp` is the executable
deck; `mesh.inp`, `source.stl` and `preparation.json` are included when available.
`model.json` (`cae_reusable_model.v1`) records units, supplied ownership/parameters
and a relative-file SHA-256 inventory. The README explains how to copy the entire
folder and run `ccx -i model` with CalculiX, without an ATR server or access to
the original absolute input path. Unresolved external `*INCLUDE` dependencies
are rejected during export.

This is the actual prepared finite-element model, not only a plot or parameter
description. It is marked `validation_status: not_promoted`; export does not prove
successful solving, calibration, mesh convergence or physical validity. Actual
results, fields and experiment comparisons belong to its owning FEM job. Solver
version/thread settings still matter for reproducibility; another FE package's
element/material/boundary compatibility requires separate checking.

The earlier combined non-actuating baseline recorded 188 passing tests. The
[validation record](../paper/evidence/2026-09-09-analysis-improvement-validation.md)
separates injected decision tests, numerical fixtures, an archived real FRD and
the preserved same-STL experiment. Fresh registered API/local-model calls and a
new physical cycle were not performed in this change.

The [preserved complete cycle](../paper/evidence/2026-09-07-latest-cycle-demonstration.md)
uses the same STL path for fabrication and CAE; the operator additionally
confirmed physical specimen identity. Its original measured curve is suitable
paired input for future controlled comparison. Its archived CAE mode is
`deterministic_quasistatic_equivalent`, so that record alone does not validate
a finite-element material model.

The newer `tests/integration/test_analysis_background_cycle.py` exercises the
real Analysis agent, runtime, bounded virtual decisions, FEM study and durable
store through injected staged tools. It checks measured BO return while a fixture
solver remains blocked, one-acquisition execution, aligned full-curve comparison,
and unchanged foreground values/artifact bytes. This is non-actuating software
evidence, not a native solver or physical calibration run.

### Completed native FEM case — 2026-09-09

The preserved same-STL acquisition was replayed computationally in
`artifacts/runs/validation-fem-20260909-long-cycle-03`. No physical device was
operated. Native FEM reached the requested endpoint with **79 converged increments**.
This is solver execution evidence, not independently validated material behavior.

| Case quantity | Recorded result |
|---|---|
| Initial dimensions used for normalization | Height 30 mm; area 900 mm² |
| Comparison interval | Contact-referenced compression 0–15 mm; no extrapolation |
| Mesh | 55,026 nodes; 159,772 C3D4 elements; no inverted/degenerate elements |
| Minimum / fifth-percentile corner scaled Jacobian | 0.001867 / 0.2437 |
| Material | E = 1,800 MPa; ν = 0.35; yield = 35 MPa; retained comparison baseline |
| Measured / FEM peak force | 6,383.90 / 5,674.17 N (**−11.12%**) |
| Measured / FEM integrated work | 60.108 / 76.280 J (**+26.90%**) |
| Curve RMS residual | 1,585.82 N; 24.84% of measured peak |
| Initial study elapsed time | 1,954.52 s (**32.58 min**), including preparation, solve, postprocessing and initial result-review request |
| Corrected saved-result LLM review | 5.06 s; no repeated FEM computation |
| Peak sampled process-tree RSS | 1,202,032,640 bytes (**1.12 GiB**) |
| Observed cumulative CPU time | 2,078.92 CPU-s; assembly threads 4, equation-solver threads 1 |
| Resource sampling | 1 s; 1,923 samples; runner and child processes only, external LLM servers excluded |
| Validation decision | LLM held validation: only one resolution solved; no three-resolution convergence claim or material promotion |

Summed RSS can count shared pages more than once; sampled CPU can miss short-lived
children. These are measured process-scope observations, not total host requirements.
Initial result review exceeded the request budget because raw field arrays were
included. The corrected decision boundary sends compact evidence; the real API
review used saved complete results and did not rerun the solver. Original and
corrected receipts remain separate (`result.json`, `result-review/result.json`).

![Paired experimental and FEM force-displacement and engineering stress-strain curves](assets/figures/analysis_04_native_comparison.png)

**Figure Analysis-4.** Full computed-domain comparison. Measurement contact offset
is 1.94855 mm and force baseline is 1.3636 N; no force scaling or fitted horizontal
shift is used. The original raw-coordinate BO work (52.420871 J) remains unchanged.
The earlier short-domain agreement does not establish full-range accuracy.

![Actual final-frame von Mises stress](assets/figures/analysis_05_native_stress.png)

**Figure Analysis-5.** Actual final completed solver frame, physical deformation
scale 1×. Stress is solver-extrapolated/nodally averaged, not raw integration-point stress.

![Actual final-frame displacement magnitude](assets/figures/analysis_06_native_displacement.png)

**Figure Analysis-6.** Actual displacement magnitude at the requested endpoint.
Large FRD history remains preserved; visualization uses the last complete frame
with its source hash and explicit selection receipt.

The prepared attempt also contains `*.model_package/` with the complete native
deck, mesh, original STL, preparation record, units, hashes and offline execution
instructions. Copy that directory and run `ccx -i model`; model portability is
separate from predictive validation. Machine-readable calculations and image
provenance are in the run's `report/metrics.json` and `report/provenance.json`.

### Parallel closed-loop verification

Final focused regression verification: **230 Python tests passed**, **11 JavaScript
tests passed**, and all four updated reference/design/evidence documents passed
scoped documentation validation. Existing schema/dependency deprecation warnings
remain. This is targeted regression coverage, not the entire repository suite.

The two-loop production software path completed in **12.72 s** while an actual
CalculiX process was computing a copied instance of the exported deck. PID 1371222
retained the same process start identity across the test; CPU ticks increased
from 122 to 1,449 (03:21:32–03:21:45 UTC, 2026-09-09).
Design → CSV acquisition fixture → Analysis → Knowledge → BO → next Design →
second Analysis completed while the Analysis compute lock remained occupied.
The terminal loop correctly does not request another unused BO proposal.

Physical boundaries and model responses were explicit fixtures; Design, Analysis,
Knowledge, BO and graph transitions were production implementations. This verifies
software concurrency, not simultaneous physical equipment operation or live-model
latency. The copied native solve was explicitly cancelled after the test; the
completed long-run solution above was not modified. Evidence is retained under
`parallel-native-proof-02/parallel_closed_loop_receipt.json`, `verification.json`
and `native_result.json`. Measured objectives remain independent of late FEM output.

### Limitations and known gaps

Independent specimen-matched FE validation needs additional held-out evidence
and explicit admissible parameter bounds. One complete cycle is not an
independent training-and-validation set. General method discovery, calibrated
statistical uncertainty, high-order/mixed element rendering, raw integration-point
stress, principal-field views and representative commercial-postprocessor
visual approval remain outside the completed evidence.

## Related Documents

- [Five-area restructuring contract](../superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md)
- [Analysis model-improvement design](../superpowers/specs/2026-09-09-analysis-multifidelity-decision-design.md)
- [CAE computation bridges](../device_bridges/cae_computation_bridges.md)
- [Equipment](equipment_agent.md), [Knowledge](knowledge_agent.md), [BO](bo_agent.md)
