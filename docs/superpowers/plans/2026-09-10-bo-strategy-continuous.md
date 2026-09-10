---
doc_type: plan
subtype: implementation
status: active
authority: execution
audience: [developer, reviewer]
scope: [bo, design, continuous_parameters, verification]
summary: 승인된 BO 전략 판단과 연속 변수 경로를 기존 실행·문서 계약 안에서 구현한다.
execution_status: completed
governing_design: [docs/superpowers/specs/2026-09-10-bo-strategy-continuous-design.md]
related_docs:
  - docs/agents/bo_agent.md
  - docs/agents/design_agent.md
supersedes: []
---

# BO Strategy and Continuous Variables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect BO-owned LLM strategy decisions to the existing optimizer and preserve continuous numeric variables through Design.

**Architecture:** Bounded local decisions wrap the existing numeric tool once; LHS/BoTorch retain coordinate authority. Existing handoffs gain domain metadata without replacing graph or bridge routes.

**Tech Stack:** Python, AgentContext, BoTorch/SciPy, vanilla JavaScript/SVG, pytest, Graphviz.

**Spec:** `docs/superpowers/specs/2026-09-10-bo-strategy-continuous-design.md`

## Global Constraints

- No improvement-target achievement judgement, automatic stopping, repeat-experiment execution, objective mutation or device actuation.
- Preserve graph routes, registered bridges, Analysis values, existing LHS count/seed policy and prior artifacts.
- Numerical coordinates come from LHS/BoTorch; no LLM reranking or coordinate generation.
- English public references/UI; Korean design rationale. Commit/tag/push require the separate user approval recorded below.
- Work in the user's current checkout; no new operational execution path or live-server restart.
- Use `.venv/bin/python`, existing dependencies, TDD and bounded offline fixtures. Distinguish API/local inference from virtual tests.

## Task 1: Continuous domain and Design handoff

**Files:** `agents/bo_agent.py` (domain/initial request only), `agents/design_agent.py`, `agents/design_decision.py` if precision checks require it, `app/controller.py` (existing design-contract metadata only), optional shared `learning/bo_design_space.py`; tests in `tests/unit/test_bo_agent.py`, `tests/unit/test_design_agent.py`, `tests/unit/test_bo_parameter_space.py`, `tests/unit/test_botorch_backend.py` and new focused handoff tests.

**Interfaces:** Preserve `BOAgent.normalize_settings`, `initial_design_request`, `_two_variable_parameter_space` and existing Design methods. Add `parameter_space` metadata to current requests if necessary; no schema replacement. A shared helper may normalize numeric domains and validate requested coordinates, but generic `BOParameterSpace` keeps mixed-space support.

- [x] Write failing behavior tests: default/new LHS has two continuous dimensions; old `[5,6,7.5,10]` maps to `[5,10]`; `[7.13789]` remains fixed; custom bounds drive first and subsequent requests; nonfinite/reversed domains fail; Design preserves `7.13789` / `0.32123456` through generated geometry arguments; existing valid discrete history remains usable.

```python
settings, _ = BOAgent.normalize_settings({"parameter_space": {"cell_size_mm": [6.2, 9.1]}})
space = BOParameterSpace.from_mapping(settings["parameter_space"])
assert space.continuous_dimension_count == 2
assert space.decode(space.encode({**space.fixed_parameters, "cell_size_mm": 7.13789,
                                 "relative_density": .32123456}))["cell_size_mm"] == pytest.approx(7.13789)
```

- [x] Run focused tests and record expected RED failures before production edits.
- [x] Normalize only active numeric variables to finite ordered ranges; default cell bounds `[5.0,10.0]`; preserve fixed manufacturing settings. Replace exact-table Design membership checks with contract-domain validation. Preserve authoritative requested coordinates instead of display rounding.
- [x] Run focused tests plus one real two-continuous-dimension `propose_next` test asserting `optimizer.function == "optimize_acqf"`, finite bounded coordinates, no device effects.
- [x] Review task diff; leave changes uncommitted.

## Task 2: BO-owned strategy decision and execution

**Files:** new `agents/bo_decision.py`; `agents/bo_agent.py` run/packaging; existing `backends/prompt_registry.py` BO entry if conflicting; new `tests/unit/test_bo_decision.py`; existing BO and software-loop tests; optional `scripts/verify_bo_decisions.py`.

**Interfaces:** A bounded async helper receives frozen context and callbacks for `run_optimizer` and knowledge retrieval, and returns decision trace plus the one optimizer result. Keep `AgentResult.data["bo_result"]`, `next_design_request.v1`, objective identity and numeric recommendation fields. Add `decision`/`bo_decision.v1` evidence; provider is existing `bo_policy`.

- [x] Write strict fake-response tests with real dispatch. One response selects a permitted acquisition; inspect the actual numeric tool payload and resulting handoff. Two responses accept or hold the identical solver candidate and must produce different readiness. Malformed JSON, unknown tools, unknown evidence/candidate IDs, arbitrary coordinates, objective/bounds edits and second optimizer requests must not dispatch.

```python
# Request shape accepted by the local decision boundary; no arbitrary kwargs.
request = {"tool": "run_optimizer", "arguments": {},
           "reason": "Use the configured numeric policy for this observation set.",
           "evidence_refs": ["context:request", "context:observations"]}
```

- [x] Observe RED, then implement finite call/time budgets, exact schemas and evidence IDs; code-owned diagnostics; read-only bounded Knowledge retrieval; optimize once and post-result accept/hold. Preserve CancelledError and archive invalid attempts.
- [x] Remove active LLM soft-preference reranking. Legacy UI keys may remain compatibility fields with inactive semantics. Explicit `force_real_llm_in_test=False` uses the same dispatcher with `virtual_test` provenance; missing/failed inference must not silently become a successful normal decision.
- [x] Existing settings are retained unless bounded automatic strategy control explicitly permits the acquisition change. Respect fixed LHS phase and user locks; reject model output that attempts to bypass them.
- [x] Run BO unit, API route fixture, actual BoTorch, and two-loop non-actuating regression. Add registered API/local verification only through existing AgentContext configuration, never alternative model servers or live devices.
- [x] Review task diff; leave changes uncommitted.

## Task 3: Visualization, references and combined verification

**Files:** `experiments/bo_visualization.py`, `experiments/lhs_design_visualization.py`, `web/static/bo_visualization.js`, relevant planning/LHS display metadata; corresponding tests; `docs/agents/bo_agent.md`, `docs/agents/design_agent.md`, `docs/agents/bo_agent_runtime_guideline.txt`, common 5-area design and API matrix if changed; BO DOT/SVG assets.

**Interfaces:** Existing visualization schema and renderer remain. Continuous cell size uses `kind: continuous`, bounds and no integer cell-count claim; archived discrete records still display their actual types. One existing visualization card per artifact, existing controls, no new dashboard or server dependency.

- [x] Add numerical and JS behavior tests for continuous bounds/labels and old discrete artifacts; observe RED before implementation.
- [x] Correct metadata and labels without changing optimized coordinates or recomputing observations; verify desktop/mobile through an isolated static fixture using the actual renderer (no production app startup).
- [x] Update BO documentation to actual five-area roles, exact implemented tools, exclusions and observed tests; remove obsolete advisory-authority claims. Update Design's domain/precision sections, retaining unrelated validated design content.
- [x] Regenerate source-backed BO handoff and internal decision SVGs with readable labels, roles, gates and evidence branches; inspect rendered figures.
- [x] Run all changed-path regression tests, scoped doc validation and `git diff --check`. Record exact results, test mode and remaining scope; no unsupported physical or model-backend success claims.
- [x] Final code review and corrective focused tests; report changed files and verification, leave commit/tag/push to a separate user instruction.

## Verification Record

Date: 2026-09-10. Worktree base: `e731a72`; verification involved no hardware
actuation, native FEM, application restart or model-service startup. Publication
was authorized separately after implementation review.

### Combined software regression

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_bo_agent.py tests/unit/test_bo_decision.py \
  tests/unit/test_bo_parameter_space.py tests/unit/test_botorch_backend.py \
  tests/unit/test_design_agent.py tests/unit/test_design_decision.py \
  tests/integration/test_objective_compiler_closed_loop.py \
  tests/integration/test_analysis_parallel_closed_loop.py \
  tests/unit/test_bo_continuous_visualization.py tests/unit/test_bo_visualization.py \
  tests/unit/test_bo_visualization_js.py tests/unit/test_bo_visualization_artifacts.py \
  tests/unit/test_lhs_design_visualization.py tests/unit/test_lhs_design_visualization_js.py \
  tests/unit/test_planning_bo_visualization_js.py tests/unit/test_bo_strategy_controls_js.py \
  tests/integration/test_bo_gui_api.py \
  tests/unit/test_controller_planning.py::test_test_mode_initial_design_is_published_as_orchestrator_json_contract \
  tests/unit/test_controller_planning.py::test_first_controller_lhs_uses_current_run_bo_domain \
  tests/unit/test_controller_planning.py::test_next_cycle_contract_republishes_bo_next_design_request \
  tests/unit/test_controller_planning.py::test_live_contract_attaches_current_bo_domain_without_replacing_requested_coordinates \
  --tb=short
```

Final observed result: **194 passed, 12 existing warnings, 22.78 s**. The integration set exercises compiled-objective restart and two
non-actuating graph loops with fabrication/acquisition fixtures. It does not
claim a physical closed-loop demonstration or a native FEM rerun.

### Registered inference and UI

`scripts/verify_bo_decisions.py --execute` passed four registered-provider
cases with real LHS/BoTorch numerics: API `gpt-5.5` and local vLLM
`gemma4:31b`, each at initial-design and acquisition phases. All used
`strategy_control=configured`, synthetic observations and exactly one
optimizer call. Timings and exact candidate coordinates are retained in the
[redacted record](../../agents/assets/verification/bo_decisions_2026-09-10.json).
Adaptive tool arguments are covered by controlled-response dispatch tests;
these probes do not establish optimization gain.

Static Playwright inspected actual production BO/LHS renderers at 1400×1000
and 390×844, including tab switching and long decision evidence IDs. All four
view/viewport checks passed with no page errors, network requests or clipped
decision text. This is an isolated renderer fixture, not a live-server test.
Seven changed Markdown documents and three BO SVGs passed scoped validation.

### Review corrections

- First LHS now reads the current run's domain before legacy defaults.
- BO retains current-run settings across registry invocations.
- Synchronous numeric/Knowledge callbacks no longer block the event loop;
  coordinator deadlines do not imply native-worker termination.
- Nonaccepted attempts clear stale BO control caches without deleting history.
- Pre-optimization owner return is intentionally allowed by the approved design.
- Configured operator settings retain their supported finite values; bounded
  adaptive limits apply only to model-selected arguments.
- Legacy surface display preserves signed acquisition values for both interpolated
  curves and the selected point. Final scoped re-review approved both fixes.

### Publication Approval

Following implementation review, the user authorized commit, tag and push.
Publish the verified implementation on `main` with the annotated `BO-Agent`
tag. Existing agent tags and `closed-loop-stable` remain unchanged.
