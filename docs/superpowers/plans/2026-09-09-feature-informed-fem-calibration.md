---
doc_type: plan
subtype: implementation
status: active
authority: execution
audience: [developer, researcher]
scope: [analysis, fem, calibration]
summary: Feature-informed inverse FEM within the existing nonblocking computation path.
execution_status: in_progress
governing_design: docs/superpowers/specs/2026-09-09-analysis-multifidelity-decision-design.md
related_docs:
  - docs/agents/analysis_agent.md
  - docs/paper/evidence/2026-09-09-feature-informed-fem-calibration.md
supersedes: []
---

# Feature-informed FEM calibration implementation plan

> **For agentic workers:** Use test-driven implementation and scoped review. This tightly coupled numerical workflow is executed inline in the existing user workspace.

**Goal:** Identify bounded, interpretable FE material candidates from measured response features, then distinguish calibration from independent prediction.

**Architecture:** Keep the measured Analysis → BO handoff and physical routes unchanged. Add a computation-only calibration study using the existing FEM study/tool boundary. A numerical optimizer proposes parameters; LLM decisions authorize registered studies and interpret evidence, never invent force curves or override numerical gates.

**Tech Stack:** Python, NumPy/SciPy, existing CalculiX tools and Analysis decision protocol, pytest.

**Spec:** User-approved design in conversation: feature extraction → bounded model identification → frozen forward prediction → independent validation. Single-acquisition fitting is calibration only.

## Global constraints

- No physical equipment calls, server restarts, global configuration changes, commits or pushes.
- Preserve the existing foreground Analysis → BO route and stored BO objective.
- Never feed specimen engineering S–S directly into the solid material plasticity table; never multiply solver output to claim a match.
- Use one frozen contact convention and the full requested evaluation domain. Partial results are diagnostic, not eligible calibration candidates.
- Bound parameter count and solve count, not native wall-clock duration. Cancellation stays with the existing compute owner.
- Keep local-softening candidates explicitly mesh-dependent until demonstrated otherwise. No automatic promotion or independent-validation claim from one acquisition.

## Task 1: Numerical calibration contract

**Files:** `agents/analysis_calibration.py`, `tests/unit/test_analysis_calibration.py`.

**Interfaces:** `response_features(curve, target_mm) -> dict`; `compare_response(observed, predicted, target_mm) -> dict`; `material_from_parameters(parameters, base_material) -> dict`; `calibrate(evidence, choose, call_tool, emit) -> dict`.

- [x] Write failing tests for full-domain coverage, unchanged zero convention, independently checked peak/work features, and rejection of nonfinite or unconstrained material values.
- [x] Test a small interpretable exponential post-yield law: `q(p) = q_res + (q_peak - q_res) * exp(-p / p_decay)`. The law is a model hypothesis, not measured material data. Constant flow is the nested special case `q_res == q_peak`.
- [x] Implement dimensionless curve + feature residuals. Use peak force, peak position, initial secant stiffness, postpeak level/slope and work; retain each error separately so energy cancellation cannot conceal shape errors.
- [x] Fit only explicit bounded parameters by deterministic coordinate search. Every proposed candidate must be run through `run_fem_study`; solver output is the prediction. The initial coarse-to-fine search has a finite evaluation count; no interpolation of experimental forces into solver inputs.
- [x] Test numerical search against an analytic test fixture with known parameters, rejection of truncated solves and absence of model promotion.

## Task 2: Existing background integration and LLM protocol

**Files:** `agents/analysis_fem.py`, `agents/analysis_decisions.py`, Analysis tests.

- [x] Add opt-in `policy.calibration` dispatch at the existing FEM entry. Remove that policy in child FEM studies to avoid recursion; child solves retain existing tool authorization, hashes, cancellation and preparation gates.
- [x] Test that ordinary FEM behavior is unchanged, and calibration returns ordinary attempt/curve evidence plus separately labeled calibration records.
- [x] Add phase-specific instructions distinguishing material softening from geometric collapse, fit from prediction, mesh quality from convergence, and full-domain evidence from a promising partial peak. Compact all calibration evidence before LLM requests.
- [x] Run targeted existing FEM, decision, refinement and foreground/background tests.

## Task 3: Retained same-STL experiment study and documentation

**Files:** `scripts/validation/run_analysis_fem_cycle.py`, `docs/agents/analysis_agent.md`, an evidence report under `docs/`.

- [x] Expose an explicit isolated calibration option in the existing validation runner, with bounded search settings supplied as JSON and no live model promotion.
- [ ] Run actual registered LLM decisions and native CalculiX on immutable copies of the retained same-STL acquisition. Keep full requested displacement and unchanged coordinate convention.
- [ ] Save parameter law, bounds, objective components, native receipts, portable model, source hashes, elapsed time and resources. Compare against the retained full-domain yield-35 baseline.
- [ ] Report actual errors, whether improvement occurred and which mechanisms remain unresolved. Do not describe calibration success as predictive validation.
- [ ] Update Analysis documentation and run focused tests plus the existing software closed-loop regression where available. Review the complete diff before handoff.

## Task 4: Registered API and local improvement-loop execution

- [x] Preserve one phase-constrained decision contract across API and registered local vLLM.
- [x] Keep short-context prompts focused on numerical gates, source identity, best candidate and recent history; retain complete raw evidence in artifacts.
- [x] Resolve the managed local model address read-only and pin isolated validation to one backend without fallback or server changes.
- [x] Test actual API and local decisions on four behavioral cases, archived native tool dispatch, and a two-candidate analytic-fixture improvement loop.
- [x] Record real-model proof separately from native solver and independent physical validation.

## Execution rulings

- Mechanism-first revision approved: preserve the baseline; require material/deformation evidence before constitutive fitting; stop partial-candidate searches; keep unsupported solver methods explicit as future work.
- [x] Add mechanism assessment to the existing FEM result decision and persist non-actuating next-evidence requests.
- [x] Freeze declared research references in the existing runtime/CLI input path and reject geometry/target-measurement copies as material evidence.
- [x] Preserve partial pilot outputs and cancel only the isolated unsupported study through its compute owner.
- [x] Verify the revised loop using registered API and local vLLM: 10/10 scenarios each, 19 real decisions each, no fallback; real unsupported acquisition held with zero solver calls. Evidence: `artifacts/analysis_validation/20260909-mechanism-dual-backend-02/`.

- Existing-path preference: work in the user's current checkout; do not create a replacement runtime or switch physical paths.
- Existing refinement promotion path is preserved. Calibration is opt-in within the background FEM study; it does not relax independent-acquisition promotion gates.
- Material search uses declared bounds as study assumptions, with provenance; literature supports testing the mechanism, not any specific fitted parameter value.
- Registered model verification: API `gpt-5.5` and local vLLM `gemma4:31b` each passed 6/6 scenarios and 15 actual decisions without fallback. Evidence: `artifacts/analysis_validation/20260909-calibration-dual-backend-02`.
- Mechanism-first scoped regression: 196 passed, 26 dependency warnings, 21.38 s. Independent review verified reference forwarding, partial-result propagation and content-identity gates.
- Native pilot in `artifacts/runs/validation-fem-20260909-feature-calibration-01` is cancelled with partial evidence preserved. Further physical calibration requires material/deformation support; Task 3 full-domain fit and independent prediction remain unfulfilled, not background-running.
