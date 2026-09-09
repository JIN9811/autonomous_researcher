# Nonblocking FEM and Live Cards Implementation Plan

> **For agentic workers:** Use the approved design below, TDD and independent scoped review. Execute in the current workspace; preserve other changes. No commits, hardware execution or live-server restart.

**Goal:** Release measured Analysis/BO output without waiting for FEM; run an Analysis-owned, cancellable background FEM study with evidence-driven LLM decisions and navigable Live GUI cards.

**Architecture:** Extend the existing AnalysisRuntimeService and SQLite ImprovementStore. Preserve existing CAE/CalculiX registration, mode gates and field viewer. Background evidence is separate from immutable foreground BO artifacts.

**Tech Stack:** Python asyncio/SQLite/FastAPI, existing CalculiX/Gmsh, vanilla Live GUI JavaScript, optional existing CAE plotting dependencies.

**Spec:** User-approved execution contract in the conversation (2026-09-09), extending `../specs/2026-09-09-analysis-multifidelity-decision-design.md`.

## Global Constraints

Implementation verification (2026-09-09): native staged execution, independent
measured handoff, durable progress/cancellation, four navigable cards, API/browser
regressions and independent review completed. Subsequent user-approved scope also
includes a reusable native-model package, one full-endpoint native study and a
copied-deck concurrency proof (two virtual physical-boundary loops). Actual case,
figures, timing/resources and limits are recorded in `docs/agents/analysis_agent.md`.
The native solve completed; final real-API review held validation pending mesh
convergence. No material promotion, hardware actuation, server restart or commit.

- Existing current workspace, no hardware operations, no commit/push.
- No FEM or worker wall-clock cutoff; retain cancellation, solver numerical termination and finite action/mesh bounds.
- One native background FEM execution at a time; do not hold an LLM lease during native computation.
- Measured objectives cannot depend on optional FEM completion. Simulation-only/preflight paths keep their existing data dependencies.
- Remeshed yield-35 reference is retained for comparison, not promoted as a validated material model.
- One acquisition may run FEM; independent-acquisition promotion gates remain separate.
- Mesh quality and response convergence are distinct deterministic evidence. LLM chooses registered tools/options; it cannot invent fields or numeric results.
- Run/loop/specimen/job/attempt isolation, immutable source copies, no cross-loop overwrite.
- Cards always exist; multiple attempts/contours are navigated with previous/next buttons, not duplicated cards. English UI text.

## Shared Interfaces

- Staged tools: `cae.prepare_static_analysis(payload)` returns normalized frozen `prepared_input`, `mesh_quality` and artifact paths; `cae.run_static_analysis({...payload, prepared_input})` reuses that prepared mesh.
- Native controls: `computation_limits.timeout_s = null` explicitly removes native deadline; `_cancel_event` (threading.Event) and `_progress_callback` are in-process only, never serialized or accepted from HTTP.
- `run_fem_study(evidence, choose, call_tool, emit)` returns `{status, attempts, decisions, summary}`. `choose(phase,evidence,options)` and `call_tool(name,payload)` are async; `emit(dict)` persists progress synchronously.
- Read-only `GET /api/analysis/fem/jobs?run_id=...&loop_key=...&specimen_id=...` returns `{jobs:[...]}`. Each job has `job_id,status,run_id,loop_key,specimen_id,experiment_curve,specimen_geometry,progress,events,attempts,summary`.
- Attempt: `attempt_id,mesh_size_mm,mesh_quality,curve:[{displacement_mm,force_N}],comparison:{end_mm,peak_error_pct,work_error_pct,rmse_N},field_asset_path,solver_status,endpoint_reached`.
- Explicit `POST /api/analysis/fem/jobs/{job_id}/cancel?run_id=...` cancels only the addressed Analysis computation, never hardware.

## Task 1 — Native prepared-mesh execution and cancellation

Files: `device_bridges/calculix_bridge.py`, `device_bridges/cae_bridge.py`, `mcp_tools/cae_tools.py`, focused tests.

- [ ] Red: executable fixture remains alive beyond configured default when timeout is null; cancel stops owned child and retains receipts. Prepared mesh survives solve without remeshing; invalid mesh is not solved.
- [ ] Green: reusable native process runner with resource/progress observations; normalize unlimited timeout; staged prepare/solve and deterministic mesh evidence; preserve old APIs/mode gates.
- [ ] Verify: `pytest tests/unit/test_calculix_execution_limits.py tests/unit/test_cae_tools.py -q` plus new focused tests.

## Task 2 — Independent FEM lifecycle and agentic decisions

Files: `agents/analysis_agent.py`, `agents/analysis_runtime.py`, `agents/analysis_improvement.py`, new `agents/analysis_fem.py`, tests.

- [ ] Red: a blocked fake native solver cannot block measured BO output; one-acquisition job executes; independent jobs serialize; progress survives store reopen; cancellation terminates work.
- [ ] Green: frozen background job registration after foreground validation; separate FEM study from model promotion; nullable worker deadline; durable progress; quality/remesh/convergence/result decisions and matching-interval comparisons.
- [ ] Verify: `pytest tests/unit/test_analysis_runtime.py tests/unit/test_analysis_improvement.py tests/unit/test_analysis_fem.py -q`.

## Task 3 — Live cards and isolated read-only job lookup

Files: new `app/analysis_fem_routes.py`, router registration, `web/static/planning.js` or scoped companion module/CSS, tests.

- [ ] Red: delayed job update appears without replaying Analysis; missing/mismatched loop returns no stale result; previous/next selects attempts/contours without duplicate cards; malformed labels/paths escaped.
- [ ] Green: four always-present cards, stable identity-keyed navigation, F-D/S-S series, partial endpoints, contour selection and agentic/resource progress. Query does not start computation.
- [ ] Verify: focused API and JavaScript/browser tests, including two-loop identity and duplicate navigation behavior.

## Task 4 — Integration and documentation

- [ ] Run neighboring Analysis/BO/archive/CAE tests and inspect rendered cards using existing saved solver artifacts; no physical cycle.
- [ ] Update Analysis reference, CAE bridge reference and governing design with measured-vs-background completion, unlimited-time cancellation, baseline identity, cards and evidence limitations.
- [ ] Independent scoped review, address defects with regression tests, run `git diff --check` and documentation validator. Do not claim full physical calibration from software tests.
