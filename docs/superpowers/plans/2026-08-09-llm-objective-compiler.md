# LLM Objective Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a template-free, LLM-composed, unit-safe objective DSL whose deterministic evaluations feed Analysis, Knowledge, and BO without changing existing `objective_score` and `next_design_request` contracts.

**Architecture:** Add an isolated `objectives` package containing typed schemas, a Metric Registry, a bounded compiler/evaluator, and a durable lifecycle service. Expose those operations through registered tools and bounded APIs, then connect the active immutable objective to Analysis, Knowledge, BO, BO Workspace, and Live GUI while preserving existing agent/tool boundaries.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, existing ToolRegistry/AgentContext, JSON/JSONL atomic persistence, vanilla HTML/CSS/JavaScript, pytest, Selenium/Firefox.

**Design Reference:** `docs/superpowers/specs/2026-08-09-llm-objective-compiler-design.md`

## Global Constraints

- No fixed objective-template picker and no hidden template fallback.
- No `eval`, `exec`, arbitrary Python, arbitrary field path, shell, or Cypher execution.
- LLM output is untrusted `objective_spec.v1` input; deterministic code is authoritative.
- Only Metric Registry entries and allowlisted DSL operators may be referenced.
- Generated objectives require validation, preview, and operator approval before activation.
- Active objective id/version/hash is immutable for a run.
- Existing `ExperimentObjective`, `objective_score`, `ExperimentEvaluationResult`, and `next_design_request.v1` consumers remain compatible.
- Live BO cannot silently replace missing measured scores with `_candidate_proxy`; virtual proxy observations must be explicitly marked synthetic.
- Objective failure blocks BO only; it never controls physical hardware or replaces Guardian authority.
- Do not stage or modify the pre-existing `.env.example` worktree change.

---

## File Structure

- Create `objectives/{schemas,metric_registry,compiler,evaluator,store,service,tools}.py` with one responsibility per module.
- Modify `app/bootstrap.py` and `app/main.py` for shared service/tool/API wiring.
- Modify `agents/{analysis,knowledge,bo}_agent.py` for runtime integration.
- Modify `knowledge/{schemas,stores}.py` and `experiments/{schemas,benchmark}.py` for compatible evidence contracts.
- Modify `web/templates/bo.html`, `web/static/bo.js`, `web/static/styles.css`, and `web/static/planning.js` for operator surfaces.

### Task 1: Metric Registry and Objective Contracts

**Files:**
- Create: `objectives/__init__.py`
- Create: `objectives/schemas.py`
- Create: `objectives/metric_registry.py`
- Test: `tests/unit/test_objective_metric_registry.py`

**Interfaces:**
- Produces `MetricDefinition`, `ObjectiveSpec`, `ObjectiveValidation`, `ObjectivePreview`, `ObjectiveEvaluation`, and `ObjectiveDecision`.
- Produces `MetricRegistry.get(metric_id)`, `list()`, `version_id`, and `validate_metric_value(metric_id, value)`.

- [ ] **Step 1: Write failing registry and schema tests**

```python
def test_registry_exposes_analysis_metrics_with_units():
    registry = MetricRegistry.default()
    strength = registry.get("compressive_strength_mpa")
    assert strength.unit == "MPa"
    assert strength.source_path == "analysis.metrics.compressive_strength_MPa"
    assert registry.get("specific_energy_absorption_j_per_g").unit == "J/g"

def test_objective_spec_rejects_unknown_root_operator():
    with pytest.raises(ValidationError):
        ObjectiveSpec(objective_id="x", version=1, direction="maximize", expression={"op": "unknown"})
```

- [ ] **Step 2: Run and verify missing-package failure**

Run: `.venv/bin/python -m pytest -q tests/unit/test_objective_metric_registry.py`

Expected: FAIL because `objectives` contracts do not exist.

- [ ] **Step 3: Implement typed contracts and implemented-metric registry**

Use stable snake-case ids mapped to current Analysis output paths. Include unit dimensions, type, valid range, uncertainty path, quality requirements, allowed modes, fidelity, and provenance requirements. Do not register metrics current agents cannot produce.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/python -m pytest -q tests/unit/test_objective_metric_registry.py
git add objectives/__init__.py objectives/schemas.py objectives/metric_registry.py tests/unit/test_objective_metric_registry.py
git commit -m "feat: define objective compiler contracts"
```

### Task 2: Unit-Safe DSL Compiler and Deterministic Evaluator

**Files:**
- Create: `objectives/compiler.py`
- Create: `objectives/evaluator.py`
- Test: `tests/unit/test_objective_compiler.py`
- Test: `tests/unit/test_objective_evaluator.py`

**Interfaces:**
- Consumes `ObjectiveSpec` and `MetricRegistry`.
- Produces `compile_objective(spec, registry) -> CompiledObjective`.
- Produces `evaluate_objective(compiled, metrics, observation_id, uncertainty=None) -> ObjectiveEvaluation`.

- [ ] **Step 1: Write failing compiler/evaluator tests**

```python
def test_compiler_rejects_incompatible_addition(registry):
    spec = objective({"op": "add", "args": [metric("compressive_strength_mpa"), metric("print_time_min")]})
    result = validate_objective(spec, registry)
    assert result.valid is False
    assert "incompatible units" in result.errors[0]

def test_evaluator_is_reproducible(compiled):
    first = evaluate_objective(compiled, METRICS, "obs-1")
    second = evaluate_objective(compiled, METRICS, "obs-1")
    assert first.model_dump() == second.model_dump()
    assert math.isfinite(first.score)
```

Also test zero denominator, non-dimensionless log, excessive AST depth/nodes, hard-constraint feasibility, nonlinear penalties, term contributions, uncertainty, and non-finite output rejection.

- [ ] **Step 2: Run tests and confirm failures**

Run: `.venv/bin/python -m pytest -q tests/unit/test_objective_compiler.py tests/unit/test_objective_evaluator.py`

- [ ] **Step 3: Implement compiler and evaluator**

Allow only approved operators. Enforce AST depth `16`, AST nodes `256`, finite literals, explicit epsilon for risky division, and structured errors with AST paths. Use canonical JSON for the objective hash.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/python -m pytest -q tests/unit/test_objective_compiler.py tests/unit/test_objective_evaluator.py
git add objectives/compiler.py objectives/evaluator.py tests/unit/test_objective_compiler.py tests/unit/test_objective_evaluator.py
git commit -m "feat: compile and evaluate objective dsl"
```

### Task 3: Durable Objective Lifecycle and Preview

**Files:**
- Create: `objectives/store.py`
- Create: `objectives/service.py`
- Test: `tests/unit/test_objective_store.py`
- Test: `tests/unit/test_objective_service.py`

**Interfaces:**
- Produces `ObjectiveStore(root: Path)` and `ObjectiveService.compose/validate/preview/approve/activate/evaluate/compare/status`.
- Persists under `memory/objectives/` and `runs/<run_id>/objective/`.

- [ ] **Step 1: Write failing lifecycle/restart tests**

```python
def test_active_version_is_immutable_and_run_bound(service):
    approved = service.approve(DRAFT_ID, operator="operator")
    active = service.activate(approved.objective_id, approved.version, run_id="run-2", operator="operator")
    assert active.objective_hash == approved.objective_hash
    with pytest.raises(ObjectiveConflict):
        service.activate(approved.objective_id, approved.version + 1, run_id="run-2", operator="operator")

def test_restart_preserves_binding_and_evaluation(tmp_path):
    evaluation = create_active_and_evaluate(make_service(tmp_path))
    assert make_service(tmp_path).status(run_id="run-2")["active_binding"]["objective_hash"] == evaluation.objective_hash
```

Preview tests must assert usable/missing/rejected rows, fidelity groups, score distribution, contributions, sensitivity, feasible ratio, uncertainty stability, and exact observation refs with no synthetic zero fill.

- [ ] **Step 2: Run and verify failures**

Run: `.venv/bin/python -m pytest -q tests/unit/test_objective_store.py tests/unit/test_objective_service.py`

- [ ] **Step 3: Implement persistence, LLM composition, preview, and lifecycle gates**

Use temporary-file `os.replace` for mutable indexes and append+flush+fsync for decisions/evaluations. Compose through `AgentContext.complete("objective_composition", ...)`, parse one strict JSON object, and validate before persistence. Approval records an explicit operator.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/python -m pytest -q tests/unit/test_objective_store.py tests/unit/test_objective_service.py
git add objectives/store.py objectives/service.py tests/unit/test_objective_store.py tests/unit/test_objective_service.py
git commit -m "feat: persist objective compiler lifecycle"
```

### Task 4: ToolRegistry and Bounded APIs

**Files:**
- Create: `objectives/tools.py`
- Modify: `app/bootstrap.py`
- Modify: `app/main.py`
- Test: `tests/integration/test_objective_api.py`
- Test: `tests/unit/test_tool_registry.py`

**Interfaces:**
- Registers `objective.metrics.list`, `objective.metrics.describe`, `objective.compose`, `objective.validate`, `objective.preview`, `objective.revise`, `objective.approve`, `objective.activate`, `objective.evaluate`, `objective.compare`, and `objective.status`.
- Adds `GET /api/objectives/metrics`, `GET /api/objectives/metrics/{metric_id}`,
  `POST /api/objectives/compose`, `POST /api/objectives/validate`,
  `POST /api/objectives/preview`, `POST /api/objectives/revise`,
  `POST /api/objectives/approve`, `POST /api/objectives/activate`,
  `POST /api/objectives/evaluate`, `POST /api/objectives/compare`, and
  `GET /api/objectives/status`.

- [ ] **Step 1: Write failing tool/API tests**

Assert unknown metrics and code payloads are rejected, unapproved drafts return `409` on activation, validation errors return `422`, unknown ids return `404`, and API responses never expose arbitrary filesystem roots.

- [ ] **Step 2: Run tests and confirm missing registrations/routes**

Run: `.venv/bin/python -m pytest -q tests/integration/test_objective_api.py tests/unit/test_tool_registry.py`

- [ ] **Step 3: Register one shared ObjectiveService and request models/routes**

Do not permit request-supplied Python, source paths, registry roots, or activation without the recorded approval/version/hash.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/python -m pytest -q tests/integration/test_objective_api.py tests/unit/test_tool_registry.py
git add objectives/tools.py app/bootstrap.py app/main.py tests/integration/test_objective_api.py tests/unit/test_tool_registry.py
git commit -m "feat: expose objective compiler tools and api"
```

### Task 5: Analysis and Knowledge Evidence Integration

**Files:**
- Modify: `agents/analysis_agent.py`
- Modify: `agents/knowledge_agent.py`
- Modify: `knowledge/schemas.py`
- Modify: `knowledge/stores.py`
- Test: `tests/unit/test_analysis_agent.py`
- Test: `tests/unit/test_knowledge_agent.py`
- Test: `tests/integration/test_knowledge_api.py`

**Interfaces:**
- Analysis emits `objective_evaluation` while preserving top-level `objective_score` and `uncertainty`.
- Knowledge stores objective id/version/hash, metrics, contributions, feasibility, uncertainty, and provenance.

- [ ] **Step 1: Write failing Analysis and Knowledge tests**

```python
assert analysis["objective_score"] == analysis["objective_evaluation"]["score"]
assert analysis["objective_evaluation"]["objective_hash"] == ACTIVE_HASH
assert knowledge_record.objective_evaluation["provenance_refs"]
```

Assert a requested invalid/missing binding blocks objective evaluation instead of using the legacy keyword score. Preserve the legacy path only when no compiler binding was requested.

- [ ] **Step 2: Run tests and verify failures**

Run: `.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py tests/unit/test_knowledge_agent.py tests/integration/test_knowledge_api.py`

- [ ] **Step 3: Implement deterministic evaluation and graph/memory lineage**

Link objective version, observation, specimen, Analysis artifact, evaluation, and provenance without replacing existing Knowledge/evolution records.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py tests/unit/test_knowledge_agent.py tests/integration/test_knowledge_api.py
git add agents/analysis_agent.py agents/knowledge_agent.py knowledge/schemas.py knowledge/stores.py tests/unit/test_analysis_agent.py tests/unit/test_knowledge_agent.py tests/integration/test_knowledge_api.py
git commit -m "feat: record compiled objective evaluations"
```

### Task 6: BO Observation Integrity and Objective Binding

**Files:**
- Modify: `agents/bo_agent.py`
- Modify: `experiments/benchmark.py`
- Modify: `experiments/schemas.py`
- Test: `tests/unit/test_bo_agent.py`
- Test: `tests/unit/test_experiment_runtime.py`
- Test: `tests/integration/test_controller_run.py`

**Interfaces:**
- BO accepts only hash-matched finite observations with feasibility, fidelity/trust, parameters, observation id, and provenance.
- `next_design_request.v1` retains existing fields and adds objective id/version/hash metadata.

- [ ] **Step 1: Write failing observation integrity tests**

```python
def test_live_bo_rejects_proxy_and_hash_mismatch():
    accepted, rejected = BOAgent.objective_observations(
        [measured(HASH_A), measured(HASH_B), synthetic_proxy(HASH_A)],
        objective_hash=HASH_A,
        mode=Mode.LIVE,
    )
    assert [item["observation_id"] for item in accepted] == ["measured-a"]
    assert {item["reason"] for item in rejected} == {"objective_hash_mismatch", "synthetic_live_proxy"}
```

Assert live BO blocks with no valid measured observation; test mode accepts only explicitly labeled `fidelity="synthetic"` records; Design receives the active objective hash.

- [ ] **Step 2: Run tests and verify failures**

Run: `.venv/bin/python -m pytest -q tests/unit/test_bo_agent.py tests/unit/test_experiment_runtime.py tests/integration/test_controller_run.py`

- [ ] **Step 3: Implement strict filtering and separate synthetic benchmark evidence**

Keep benchmark smoke support, but expose accepted/rejected observation counts and reasons. Do not pass proxy scores into the live surrogate.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/python -m pytest -q tests/unit/test_bo_agent.py tests/unit/test_experiment_runtime.py tests/integration/test_controller_run.py
git add agents/bo_agent.py experiments/benchmark.py experiments/schemas.py tests/unit/test_bo_agent.py tests/unit/test_experiment_runtime.py tests/integration/test_controller_run.py
git commit -m "feat: bind bo observations to compiled objectives"
```

### Task 7: BO Workspace and Live GUI Objective State

**Files:**
- Modify: `web/templates/bo.html`
- Modify: `web/static/bo.js`
- Modify: `web/static/styles.css`
- Modify: `app/main.py`
- Modify: `web/static/planning.js`
- Test: `tests/integration/test_bo_gui_api.py`
- Test: `tests/integration/test_live_gui_runtime_layout.py`
- Create: `tests/ui/bo_objective_compiler_browser_audit.py`

**Interfaces:**
- BO Workspace renders intent, Metric Registry, equation tree, validation, preview, version diff, approval, and activation.
- Live GUI renders compact active objective/evaluation state without invoking the LLM.

- [ ] **Step 1: Write failing static/API UI tests**

Assert stable ids for the intent editor, metric browser, equation tree, validation, preview plots, diff, and lifecycle controls. Assert there is no fixed objective-template selector.

- [ ] **Step 2: Run tests and verify missing surfaces**

Run: `.venv/bin/python -m pytest -q tests/integration/test_bo_gui_api.py tests/integration/test_live_gui_runtime_layout.py`

- [ ] **Step 3: Implement the persisted Objective Compiler workspace**

Disable Approve until validation and preview succeed; disable Activate until approval. Render score distribution, contributions, sensitivity, feasible ratio, and uncertainty with lightweight SVG/canvas. Persist drafts through backend storage, not browser-only state.

- [ ] **Step 4: Implement compact Live card and browser audit**

Show id/version/hash, equation summary, latest score, feasibility, contributions, and readiness. Refresh status without rerendering the whole report or occupying the LLM.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest -q tests/integration/test_bo_gui_api.py tests/integration/test_live_gui_runtime_layout.py
.venv/bin/python tests/ui/bo_objective_compiler_browser_audit.py --base-url http://127.0.0.1:7860 --screenshot artifacts/ui/bo_objective_compiler_1920x1080.png
git add web/templates/bo.html web/static/bo.js web/static/styles.css app/main.py web/static/planning.js tests/integration/test_bo_gui_api.py tests/integration/test_live_gui_runtime_layout.py tests/ui/bo_objective_compiler_browser_audit.py
git commit -m "feat: add objective compiler workspace"
```

### Task 8: End-to-End Verification and Documentation

**Files:**
- Create: `tests/integration/test_objective_compiler_closed_loop.py`
- Modify: `docs/agents/bo_agent.md`
- Modify: `docs/agents/bo_agent_runtime_guideline.txt`
- Modify: `docs/agents/analysis_utm_runtime_guideline.txt`
- Modify: `docs/agents/knowledge_agent_self_evolution_runtime_guideline.md`
- Modify: `docs/runtime/autonomous_experiment_runtime.md`
- Modify: `docs/runtime/current_code_snapshot.md`
- Modify: `docs/knowledge/knowledge_graph_operations.ko.md`
- Modify: `docs/document_manifest.yaml` if route counts change
- Test: `tests/unit/test_documentation_validation.py`

- [ ] **Step 1: Add end-to-end compiler-to-BO regression**

The test uses a deterministic fake LLM response, rejects one unit-invalid draft, previews/approves/activates the corrected nonlinear objective, evaluates Analysis metrics, persists Knowledge evidence, verifies a hash-matched BO handoff, restarts services, and reproduces the score without an LLM.

- [ ] **Step 2: Run objective and agent suites**

```bash
.venv/bin/python -m pytest -q tests/unit/test_objective_*.py tests/integration/test_objective_*.py
.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py tests/unit/test_knowledge_agent.py tests/unit/test_bo_agent.py tests/unit/test_experiment_runtime.py
```

- [ ] **Step 3: Run closed-loop/routing/GUI regressions**

```bash
.venv/bin/python -m pytest -q tests/unit/test_model_router.py tests/unit/test_langgraph_runtime.py tests/integration/test_controller_run.py tests/integration/test_live_gui_runtime_layout.py tests/integration/test_bo_gui_api.py
```

- [ ] **Step 4: Update current-state docs and validate**

Document exact DSL, lifecycle, persistence, APIs/tools, GUI, no-live-proxy rule, recovery, and operator workflow only after implementation exists.

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python -m pytest -q tests/unit/test_documentation_validation.py
```

- [ ] **Step 5: Run and inspect browser evidence**

```bash
.venv/bin/python tests/ui/bo_objective_compiler_browser_audit.py --base-url http://127.0.0.1:7860 --screenshot artifacts/ui/bo_objective_compiler_1920x1080.png
```

- [ ] **Step 6: Verify scope and commit**

```bash
git diff --check
git status --short
git add tests/integration/test_objective_compiler_closed_loop.py docs/agents/bo_agent.md docs/agents/bo_agent_runtime_guideline.txt docs/agents/analysis_utm_runtime_guideline.txt docs/agents/knowledge_agent_self_evolution_runtime_guideline.md docs/runtime/autonomous_experiment_runtime.md docs/runtime/current_code_snapshot.md docs/knowledge/knowledge_graph_operations.ko.md docs/document_manifest.yaml
git commit -m "docs: document objective compiler runtime"
```
