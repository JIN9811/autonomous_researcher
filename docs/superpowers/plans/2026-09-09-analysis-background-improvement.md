# Analysis Background Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Preserve the existing experiment/Analysis/BO loop while implementing evidence-grounded LLM decisions, bounded asynchronous model improvement, and truthful interactive solver contours.

**Architecture:** Analysis owns foreground decisions and a persistent, nonblocking improvement queue. Foreground freezes a validated model version; background uses immutable evidence and registered computation tools only. Actual CalculiX fields feed the same read-only postprocessing view in both paths.

**Tech Stack:** Existing Python/asyncio/ToolRegistry/AgentContext, CalculiX/Gmsh, existing web GUI, VTK-compatible field artifacts.

**Spec:** `docs/superpowers/specs/2026-09-09-analysis-multifidelity-decision-design.md`

## Global Constraints

- Work in the user's current checkout/path; preserve unrelated edits. No commit/push, physical equipment invocation, bridge settings changes, server restart, or inference backend replacement.
- Existing Analysis external node, physical test profile, BO handoff and registered CAE entry point remain intact.
- Model improvement never blocks valid measurement handoff. Do not fabricate calibration, uncertainty, field data, validation results or commercial-software parity.
- New models require independent validation and apply only at a subsequent loop boundary. Original observations and historical artifacts are immutable.
- Use existing registered LLM routing and ToolRegistry; no arbitrary model-written Python/decks or equipment tools.
- Tests precede production changes. Run focused tests before implementation and after, then relevant regression tests. Evidence distinguishes mocks, actual solver artifacts and real LLM calls.

## Task 1: Actual solver field conversion and mesh evidence

**Files:** Create `utils/calculix_fields.py`, `tests/unit/test_calculix_fields.py`; modify `utils/calculix_quasistatic.py`, `device_bridges/calculix_bridge.py`, `device_bridges/cae_bridge.py` only where field artifacts are exposed; corresponding existing tests.

**Interfaces:** `postprocess_fields(inp_path, frd_path, output_dir) -> dict` returns schema, field asset paths, frames, arrays with units/association, mesh evidence and explicit unsupported/error states. JSON geometry/frames are the browser contract; retain original IDs and files. Existing `calculix.postprocess` delegates conversion without changing physical solver gates.

- [x] Write failing tests using hand-derived tetra geometry and FRD values: non-contiguous IDs, field mapping, frame ordering, missing displacement, discontinuous stress semantics, invalid connectivity, unsupported topology. Expected displacement/stress values must be literal, not derived from implementation.
- [x] Run `.venv/bin/python -m pytest tests/unit/test_calculix_fields.py -q`, confirm missing behavior.
- [x] Implement strict ASCII FRD/INP supported topology parsing and unit/association metadata. Never silently linearize high-order cells; preserve connectivity. Supply derived Mises from full tensor with declared averaging provenance. Export mesh validity/quality facts; not a made-up combined score.
- [x] Request full-node U while preserving existing TOP RF history. Connect postprocess into successful/partial CalculiX jobs, field failure separate from curve success.
- [x] Run new tests plus `tests/unit/test_calculix_quasistatic.py`, `tests/unit/test_cae_tools.py`, existing CalculiX integration tests. Inspect a real archived FRD without solver/equipment execution.

```python
result = postprocess_fields(inp_path, frd_path, output_dir)
assert result['schema'] == 'cae_fields.v1'
assert result['frames'][0]['fields']['U']['values'][0] == [0.0, 0.0, -1.0]
```

## Task 2: Persistent bounded improvement queue and model versions

**Files:** Create `agents/analysis_improvement.py`, `tests/unit/test_analysis_improvement.py`; integration hooks later in Task 3.

**Interfaces:** `ImprovementStore(root)` exposes immutable evidence submission, job status, bounded claim/finish, scope-keyed candidate validation/promotion, and `pin_model(scope, loop_key, baseline)`. `AnalysisImprovementWorker` owns background lifecycle and receives narrow LLM/computation callbacks, not the live mutable OrchestratorState.

- [x] Write tests for durable deduplication, nonblocking enqueue, distinct loops, failed/cancelled jobs, restart recovery, same-loop pinning after promotion, incompatible-scope rejection, missing/overlapping holdout rejection and absent-data waiting.
- [x] Run `.venv/bin/python -m pytest tests/unit/test_analysis_improvement.py -q` and confirm missing behavior.
- [x] Implement atomic persistent records/claiming and immutable snapshots. Queue only under a run's artifacts. Bounded worker uses finite max calls/jobs/time and lowers priority; foreground solver work must have priority at admission. No unbounded retry and no retroactive measurement writes.
- [x] Implement evidence-based comparison and registered candidate generation through validated parameter bounds; use independent experiment IDs for holdout. Unknown bounds/data produce `needs_more_data`, not automatic fitting. Candidate model must pass deterministic numeric/identity criteria before promotion.
- [x] Run focused tests including a worker blocked on an Event while foreground returns, and a model promoted mid-loop remaining unapplied until another loop.

```python
first = store.pin_model(scope, 'loop-1', baseline)
# After independently validated candidate promotion:
assert store.pin_model(scope, 'loop-1', baseline) == first
assert store.pin_model(scope, 'loop-2', baseline)['version'] != first['version']
```

## Task 3: Foreground LLM decisions, minimal runtime integration and metric contracts

**Files:** Create `agents/analysis_decisions.py`, `tests/unit/test_analysis_decisions.py`; modify `agents/analysis_agent.py`, `backends/prompt_registry.py`, runtime lifecycle as necessary; add integration tests. Narrow consumers in Knowledge/Guardian only for explicit evidence contract migration.

**Interfaces:** Decision requests use the existing `analysis_reasoning` route and validated phase-specific response options. LLM selects a registered tool and evidence-backed accept/hold; deterministic execution owns the numbers. Background receives copied payload/evidence after artifacts are finalized.

- [x] Add red tests for disallowed tool/parameter mutation, malformed replies, mock mode routing, preserved real data quality gates, one CAE call, BO handoff independent of worker state.
- [x] Implement phase-constrained decision protocol, journal decisions/tools with provenance, reuse CSV normalization and `cae.run_static_analysis`.
- [x] Pin model at actual loop boundary (not only when Analysis starts), expose selected version in Analysis artifacts; enqueue completed evidence without waiting for high-cost refinement. Bind worker lifecycle to runtime shutdown and keep worker state out of physical stage completion.
- [x] Replace active arbitrary composite objective use with explicit physical/compiled objective. Introduce `not_estimated` uncertainty facts and defined quality gates; migrate consuming branches without bypassing existing equipment safety. Preserve legacy archived records.
- [x] Run Analysis/Knowledge/Guardian/BO regression tests and two-loop Analysis/runtime boundary tests including improvement failure and delayed completion. Test the compiled objective handoff and all-agent two-loop archive entrypoints without providers.

```python
result = await agent.run(state, ctx)
assert result.success
assert result.data['analysis']['improvement']['status'] in {'queued', 'needs_more_data'}
assert result.data['bo_observation']['source'] != 'calibrated_prediction'
```

## Task 4: Read-only interactive contour viewer

**Files:** Create `web/static/cae_fields.js`, companion styles/template, relevant JS/API tests; modify existing CAE page and live Analysis result entry point; reuse existing artifact routes.

**Interfaces:** Consume Task 1 `cae_fields.v1` only. Reading files, changing camera/field/frame or exporting must never execute solver/equipment. Reuse locally hosted renderer rather than relying on runtime CDN availability.

- [x] Test fixture loading, arrays/units, missing-field reporting, no execution POST, common range and frame selection.
- [x] Implement orbit/pan/zoom, deformed/undeformed, labelled scale, edges, field/components, scalar legend/range, frame playback, picking IDs/values and slice/clip where supported by actual volume data. Missing capabilities must be visible, not fake.
- [x] Add side-by-side baseline/candidate common range/camera and scientific high-resolution export; serialize render recipe. Keep original exact values when displaying reduced meshes.
- [x] Validate with actual archived tetra solver data and isolated browser geometry; inspect screenshots, labels and averaging semantics.
- [ ] Obtain representative lattice/large-mesh benchmark and user visual approval before claiming commercial-quality acceptance.

## Task 5: Documentation, evidence and review

**Files:** `docs/agents/analysis_agent.md`, existing Analysis DOT/SVG figures, governing design/DOT/SVG, CAE computation reference and test evidence.

- [x] Update status-at-a-glance and five-area role/tool tables to actual implemented facts. Separate completed features from unsupported field/validation capabilities.
- [x] Record exact tests, fixtures, actual artifact paths/hashes and model/solver execution boundaries; no physical validation claim.
- [x] Validate documentation, SVG rendering and `git diff --check`; run relevant non-actuating regressions and independent code review.
- [x] Leave changes uncommitted for user review. No remote push or running service restart.

## Completion evidence

Implementation and independent reviews are recorded in [Analysis validation](../../paper/evidence/2026-09-09-analysis-improvement-validation.md). Original same-STL closed-loop artifacts remain unchanged. No new real-model inference, physical cycle, or FE material-calibration claim is made. A narrow existing compiled-objective/BO metric-name mismatch was reproduced against the baseline Analysis and corrected only for an active registered objective binding. Current code stays uncommitted; the running server was not restarted.
