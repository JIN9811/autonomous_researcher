# Equipment Skill Sequential Workflow Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an exact-version sequential Skill Workflow Editor and make one Deploy action automatically compile, validate, and transfer the selected Skill.

**Architecture:** Keep `workflow.json` as the Linux-authoritative editable document. Add a focused workflow-contract module and registry update method, expose exact-version editor APIs and a dedicated browser page, and reuse the existing persistent deployment job for automatic compile, validate, and worker registration stages. The Windows runtime and normal Skill execution path remain unchanged.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, filesystem JSON contracts with SHA-256, vanilla HTML/CSS/JavaScript, Node test runner, pytest, Selenium browser audit.

**Spec:** `docs/superpowers/specs/2026-08-30-equipment-skill-workflow-editor-design.md`

## Global Constraints

- The editor is sequential only: no IF nodes, graph edges, loops, parallel branches, or user-authored Python.
- `workflow.json` remains authoritative; the editor never writes `programs/*.json`.
- Skill Management exposes `Refresh | Workflow Editor | Deploy`; it does not expose Compile or Validate buttons.
- One Deploy operation performs compile, validate, and transfer in that order and never executes the Skill.
- Deployed and disabled exact versions are read-only in the editor.
- Existing `/compile` and `/validate` APIs remain for CUI compatibility, but the GUI does not call them directly.
- Existing 7860 services and running model processes must not be stopped during implementation.
- Do not actuate physical UTM equipment in automated tests; use schema checks, simulator mode, and a harmless `wait` single-step test.
- Do not commit implementation changes until the user explicitly asks for a commit.

## File Structure

- Create `utils/equipment_skill_workflow.py`: editable workflow normalization, validation issues, duration estimates, and action-field contracts.
- Modify `utils/equipment_skill_runtime.py`: exact-version workflow save, hash concurrency, lifecycle invalidation, annotation synchronization, and audit events.
- Modify `app/main.py`: editor page, workflow APIs, single-step test API, and automatic compile/validate deployment stages.
- Create `web/templates/equipment_skill_workflow_editor.html`: dedicated exact-version editor window.
- Create `web/static/equipment_skill_workflow_model.js`: pure browser state operations used by UI and Node tests.
- Create `web/static/equipment_skill_workflow_editor.js`: editor rendering, field editing, drag reorder, locator replacement, save/check/test calls.
- Modify `web/templates/windows_equipment.html`: remove Compile/Validate controls and insert Workflow Editor icon before Deploy.
- Modify `web/static/windows_equipment.js`: exact-version editor launch and simplified deploy behavior.
- Modify `web/static/styles.css`: Skill Management icon and dedicated editor layout.
- Create `tests/unit/test_equipment_skill_workflow.py`: Python workflow contract tests.
- Modify `tests/unit/test_equipment_skill_runtime.py`: save, lifecycle, hash conflict, and audit tests.
- Modify `tests/integration/test_equipment_skill_api.py`: workflow API, editor route, single-step isolation, and auto-deploy tests.
- Create `tests/js/equipment_skill_workflow_model.test.js`: browser-model ordering, duplication, duration, and validation tests.
- Modify `tests/ui/windows_equipment_browser_audit.py`: icon placement, dedicated-window launch, and no standalone Compile/Validate controls.
- Modify `docs/agents/equipment_agent.md`, `docs/device_bridges/windows_pyautogui_bridge.md`, and `docs/tutorials/user_manual.ko.md`: editor and deployment operation documentation.

---

### Task 1: Editable Workflow Contract

**Files:**
- Create: `utils/equipment_skill_workflow.py`
- Test: `tests/unit/test_equipment_skill_workflow.py`

**Interfaces:**
- Consumes: existing action names emitted by `compile_recording_actions()` and accepted by `WindowsPyAutoGUIBridge.DEFAULT_ALLOWED_ACTIONS`.
- Produces: `validate_editable_workflow(workflow: dict[str, Any], *, locator_root: Path | None = None) -> dict[str, Any]`, `workflow_duration_bounds(workflow: dict[str, Any]) -> dict[str, float]`, and `WorkflowContractIssue` dictionaries with `step_id`, `field`, `code`, and `message`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_validate_editable_workflow_normalizes_sequential_steps() -> None:
    result = validate_editable_workflow({
        "schema": "atr.equipment_skill.v1",
        "skill_id": "demo",
        "version": "1.0.0",
        "steps": [
            {"step_id": "step-001", "label": "Pause", "action": {"action": "wait", "seconds": 2.0}, "checkpoint_after": False},
            {"step_id": "step-002", "label": "Ready", "action": {"action": "wait_until_image", "target": "ready", "timeout_s": 10.0, "poll_interval_s": 0.5, "required": True}, "checkpoint_after": True},
        ],
        "program_ids": [],
    })
    assert result["ok"] is True
    assert [step["step_id"] for step in result["workflow"]["steps"]] == ["step-001", "step-002"]


def test_validate_editable_workflow_rejects_duplicates_and_unbounded_waits() -> None:
    result = validate_editable_workflow(_workflow_with_duplicate_ids_and_timeout(0))
    assert result["ok"] is False
    assert {issue["code"] for issue in result["issues"]} == {"DUPLICATE_STEP_ID", "WAIT_TIMEOUT_INVALID"}


def test_workflow_duration_bounds_include_fixed_and_until_waits() -> None:
    bounds = workflow_duration_bounds(_workflow_with_waits(seconds=2, timeout_s=10))
    assert bounds == {"minimum_s": 2.0, "maximum_s": 12.0}
```

- [ ] **Step 2: Run tests and confirm the module is missing**

Run: `pytest -q tests/unit/test_equipment_skill_workflow.py`

Expected: collection fails because `utils.equipment_skill_workflow` does not exist.

- [ ] **Step 3: Implement explicit action contracts and normalization**

```python
EDITABLE_ACTIONS = frozenset({
    "move_to", "click", "double_click", "drag_to", "scroll", "hscroll",
    "press", "hotkey", "write", "wait", "wait_until", "wait_until_image",
    "wait_until_text", "wait_for_file", "screenshot",
})


def validate_editable_workflow(workflow: dict[str, Any], *, locator_root: Path | None = None) -> dict[str, Any]:
    normalized = deepcopy(dict(workflow or {}))
    issues: list[dict[str, str]] = []
    # Validate schema/identity, unique stable step IDs, action-specific fields,
    # finite bounds, embedded PNG SHA-256 values, and the 1..10000 step limit.
    return {"ok": not issues, "workflow": normalized, "issues": issues, "duration": workflow_duration_bounds(normalized)}
```

The action validators must use these exact bounds:

- fixed `wait.seconds`: `0..30` seconds;
- until/file `timeout_s`: `0.1..3600` seconds;
- `poll_interval_s`: `0.05..10` seconds and no greater than `timeout_s`;
- image candidates: one or two PNG values, each at most 256 KiB, dimensions `1..512`, matching SHA-256;
- pointer coordinates: finite integers; duration `0.05..5` seconds;
- write text: at most 512 characters;
- step label: at most 160 characters.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/unit/test_equipment_skill_workflow.py`

Expected: all workflow contract tests pass.

- [ ] **Step 5: Run a non-commit review checkpoint**

Run: `git diff --check -- utils/equipment_skill_workflow.py tests/unit/test_equipment_skill_workflow.py`

Expected: no whitespace errors. Do not commit.

### Task 2: Registry Save and Lifecycle Invalidation

**Files:**
- Modify: `utils/equipment_skill_runtime.py`
- Modify: `tests/unit/test_equipment_skill_runtime.py`

**Interfaces:**
- Consumes: `validate_editable_workflow()` from Task 1 and existing `canonical_sha256()`.
- Produces: `EquipmentSkillRegistry.update_workflow(skill_id: str, version: str, workflow: dict[str, Any], *, expected_workflow_sha256: str) -> dict[str, Any]`.

- [ ] **Step 1: Write failing registry tests**

```python
def test_update_workflow_reorders_steps_and_invalidates_build(tmp_path: Path) -> None:
    registry = _compiled_registry(tmp_path)
    before = registry.get("program1_skill", "1.0.0")
    edited = deepcopy(before["workflow"])
    edited["steps"] = list(reversed(edited["steps"]))
    result = registry.update_workflow(
        "program1_skill", "1.0.0", edited,
        expected_workflow_sha256=before["manifest"]["workflow_sha256"],
    )
    assert result["workflow"]["program_ids"] == []
    assert result["manifest"]["program_sha256"] == {}
    assert result["manifest"]["lifecycle"] == "annotated"


def test_update_workflow_rejects_stale_hash_and_deployed_version(tmp_path: Path) -> None:
    registry = _deployed_registry(tmp_path)
    with pytest.raises(SkillContractError, match="immutable"):
        registry.update_workflow("program1_skill", "1.0.0", registry.get("program1_skill", "1.0.0")["workflow"], expected_workflow_sha256="0" * 64)
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `pytest -q tests/unit/test_equipment_skill_runtime.py -k 'update_workflow'`

Expected: failure because `update_workflow` is absent.

- [ ] **Step 3: Implement save with the manifest as commit marker**

```python
def update_workflow(self, skill_id, version, workflow, *, expected_workflow_sha256):
    package = self.get(skill_id, version)
    if package["manifest"].get("lifecycle") in {"deployed", "disabled"}:
        raise SkillContractError("deployed Skill versions are immutable")
    if package["manifest"].get("workflow_sha256") != expected_workflow_sha256:
        raise SkillContractError("workflow revision conflict")
    checked = validate_editable_workflow(workflow, locator_root=self._package_dir(skill_id, version))
    if not checked["ok"]:
        raise SkillContractError(canonical_json({"failure_code": "SKILL_WORKFLOW_INVALID", "issues": checked["issues"]}))
    # Clear program_ids/compiled_at and stale program hashes, synchronize annotation
    # order, write workflow and annotations atomically, then write manifest last.
```

Remove stale `programs/*.json` only after the workflow and annotations temporary files have been prepared. Writing `manifest.json` last makes its hashes the package commit marker; an interrupted write becomes a detectable hash mismatch rather than a deployable partial package.

- [ ] **Step 4: Verify lifecycle and existing compile parity**

Run: `pytest -q tests/unit/test_equipment_skill_runtime.py -k 'update_workflow or compile_emits or deploy_lifecycle'`

Expected: all selected tests pass.

- [ ] **Step 5: Run a non-commit review checkpoint**

Run: `git diff --check -- utils/equipment_skill_runtime.py tests/unit/test_equipment_skill_runtime.py`

Expected: no whitespace errors. Do not commit.

### Task 3: Workflow Editor and Automatic Deploy APIs

**Files:**
- Modify: `app/main.py`
- Modify: `tests/integration/test_equipment_skill_api.py`

**Interfaces:**
- Consumes: `EquipmentSkillRegistry.update_workflow()`, `compile()`, `validate()`, existing `_execute_equipment_skill_deployment()`, and `WindowsPyAutoGUIBridge.run()`.
- Produces: exact-version editor page and workflow API routes, plus a deployment job that includes `COMPILING`, `VALIDATING`, `PACKAGING`, `REGISTERING`, and `VERIFYING` stages.

- [ ] **Step 1: Write failing API tests**

```python
def test_workflow_api_load_save_check_and_hash_conflict(client: TestClient) -> None:
    package = _annotated_skill(client)
    loaded = client.get("/api/equipment/skills/program1_skill/1.0.0/workflow").json()
    assert loaded["editable"] is True
    saved = client.put(
        "/api/equipment/skills/program1_skill/1.0.0/workflow",
        json={"expected_workflow_sha256": loaded["workflow_sha256"], "workflow": loaded["workflow"]},
    )
    assert saved.status_code == 200
    conflict = client.put(
        "/api/equipment/skills/program1_skill/1.0.0/workflow",
        json={"expected_workflow_sha256": loaded["workflow_sha256"], "workflow": loaded["workflow"]},
    )
    assert conflict.status_code == 409


def test_deploy_job_compiles_validates_then_registers(monkeypatch, client: TestClient) -> None:
    _annotated_skill(client)
    stages: list[str] = []
    monkeypatch.setattr(main_module, "_launch_equipment_skill_deployment_job", lambda job_id: main_module._run_equipment_skill_deployment_job(job_id))
    response = client.post("/api/equipment/skills/program1_skill/1.0.0/deploy/start", json={"bridge_id": "windows-lab-1"})
    job = client.get(f"/api/equipment/skill-deployment/jobs/{response.json()['job']['job_id']}").json()["job"]
    assert job["status"] == "COMPLETED"
    assert job["result"]["manifest"]["lifecycle"] == "deployed"


def test_single_step_test_sends_exactly_one_action(monkeypatch, client: TestClient) -> None:
    observed = _capture_bridge_run(monkeypatch)
    response = client.post(
        "/api/equipment/skills/program1_skill/1.0.0/workflow/steps/step-002/test",
        json={"bridge_id": "windows-lab-1", "confirm_execute": True},
    )
    assert response.status_code == 200
    assert len(observed["sequence"]) == 1
```

- [ ] **Step 2: Run focused API tests and confirm 404/validation failures**

Run: `pytest -q tests/integration/test_equipment_skill_api.py -k 'workflow_api or deploy_job_compiles or single_step'`

Expected: tests fail because the new routes and automatic stages do not exist.

- [ ] **Step 3: Add request models and exact-version routes**

```python
class EquipmentSkillWorkflowUpdateRequest(BaseModel):
    expected_workflow_sha256: str = Field(..., min_length=64, max_length=64)
    workflow: dict[str, Any]


class EquipmentSkillWorkflowStepTestRequest(BaseModel):
    bridge_id: str = Field(..., min_length=1, max_length=96)
    confirm_execute: bool = False
```

Add:

```text
GET  /equipment/skills/{skill_id}/{version}/workflow-editor
GET  /api/equipment/skills/{skill_id}/{version}/workflow
PUT  /api/equipment/skills/{skill_id}/{version}/workflow
POST /api/equipment/skills/{skill_id}/{version}/workflow/check
POST /api/equipment/skills/{skill_id}/{version}/workflow/steps/{step_id}/test
```

The single-step endpoint must reject missing explicit confirmation, deployed-version mutation is irrelevant because test is read-only, and the bridge payload must contain one `sequence` action only.

- [ ] **Step 4: Make Deploy compile and validate before transfer**

At the start of `_execute_equipment_skill_deployment()`:

```python
progress_callback("COMPILING", 10, "Compiling saved Skill workflow")
package = registry.compile(skill_id, version)
if stop_requested():
    raise _EquipmentSkillDeploymentStopped("Deployment stopped after compile")
progress_callback("VALIDATING", 25, "Validating exact compiled Skill package")
package = registry.validate(skill_id, version)["package"]
if stop_requested():
    raise _EquipmentSkillDeploymentStopped("Deployment stopped after validation")
```

Remove the `validated` precondition from `/deploy/start`; retain annotation-review checks through `registry.validate()`. Keep `/compile` and `/validate` routes for CUI callers.

- [ ] **Step 5: Run API tests**

Run: `pytest -q tests/integration/test_equipment_skill_api.py -k 'skill or workflow'`

Expected: all selected integration tests pass, including existing hash rollback tests.

- [ ] **Step 6: Run a non-commit review checkpoint**

Run: `git diff --check -- app/main.py tests/integration/test_equipment_skill_api.py`

Expected: no whitespace errors. Do not commit.

### Task 4: Pure Browser Workflow Model

**Files:**
- Create: `web/static/equipment_skill_workflow_model.js`
- Create: `tests/js/equipment_skill_workflow_model.test.js`

**Interfaces:**
- Consumes: workflow API JSON from Task 3.
- Produces: `normalizeWorkflowState`, `moveStep`, `duplicateStep`, `deleteStep`, `insertStep`, `durationBounds`, and `actionSummary`; exports through CommonJS for Node and `window.EquipmentSkillWorkflowModel` for browsers.

- [ ] **Step 1: Write failing Node tests**

```javascript
test("move and duplicate preserve unique stable step IDs", () => {
  const moved = moveStep(sampleWorkflow(), "step-002", 0);
  const duplicated = duplicateStep(moved, "step-002");
  assert.deepEqual(moved.steps.map((item) => item.step_id), ["step-002", "step-001"]);
  assert.equal(new Set(duplicated.steps.map((item) => item.step_id)).size, 3);
});

test("duration bounds include wait deadlines", () => {
  assert.deepEqual(durationBounds(sampleWorkflow()), {minimum_s: 2, maximum_s: 12});
});
```

- [ ] **Step 2: Run Node tests and confirm module failure**

Run: `node --test tests/js/equipment_skill_workflow_model.test.js`

Expected: failure because the model module is absent.

- [ ] **Step 3: Implement immutable pure state operations**

```javascript
function moveStep(workflow, stepId, targetIndex) {
  const next = normalizeWorkflowState(workflow);
  const source = next.steps.findIndex((step) => step.step_id === stepId);
  if (source < 0) throw new Error(`Unknown step: ${stepId}`);
  const [step] = next.steps.splice(source, 1);
  next.steps.splice(Math.max(0, Math.min(targetIndex, next.steps.length)), 0, step);
  return next;
}
```

Step IDs created by insert/duplicate must use the first unused `step-NNN` value and must not renumber existing steps.

- [ ] **Step 4: Run Node tests**

Run: `node --test tests/js/equipment_skill_workflow_model.test.js tests/js/windows_equipment_selection.test.js`

Expected: all tests pass.

- [ ] **Step 5: Run a non-commit review checkpoint**

Run: `git diff --check -- web/static/equipment_skill_workflow_model.js tests/js/equipment_skill_workflow_model.test.js`

Expected: no whitespace errors. Do not commit.

### Task 5: Dedicated Workflow Editor Window

**Files:**
- Create: `web/templates/equipment_skill_workflow_editor.html`
- Create: `web/static/equipment_skill_workflow_editor.js`
- Modify: `web/static/styles.css`
- Modify: `tests/integration/test_equipment_skill_api.py`

**Interfaces:**
- Consumes: Task 3 workflow APIs and Task 4 model helpers.
- Produces: a dedicated exact-version editor window with vertical step cards, field controls, locator preview/replacement, drag reorder, schema check, save, and single-step test.

- [ ] **Step 1: Add failing editor-page assertions**

```python
def test_workflow_editor_page_binds_exact_skill_and_assets(client: TestClient) -> None:
    response = client.get("/equipment/skills/program1_skill/1.0.0/workflow-editor")
    assert response.status_code == 200
    assert 'data-skill-id="program1_skill"' in response.text
    assert 'data-skill-version="1.0.0"' in response.text
    assert "/static/equipment_skill_workflow_editor.js" in response.text
```

- [ ] **Step 2: Create the dedicated page shell**

The page must contain these stable IDs:

```text
skill-workflow-editor
workflow-editor-title
workflow-editor-lifecycle
workflow-editor-dirty
workflow-editor-duration
workflow-editor-check
workflow-editor-save
workflow-editor-add-step
workflow-editor-step-list
workflow-editor-status
workflow-editor-close
```

- [ ] **Step 3: Implement card rendering and editing**

```javascript
function commitField(stepId, path, value) {
  editorState.workflow = model.updateStepField(editorState.workflow, stepId, path, value);
  editorState.dirty = true;
  renderEditor();
}
```

Render only fields owned by each action type. Keep one card expanded. Implement HTML5 drag/drop and keyboard Move Up/Move Down. Use a file input for Replace Locator; read PNG bytes, calculate SHA-256 through `crypto.subtle.digest`, capture dimensions with an `Image`, and replace `image_candidates` without sending a separate mutable asset request.

- [ ] **Step 4: Implement Check, Save, and single-step Test calls**

Save sends the full ordered workflow and current expected hash. A 409 conflict must preserve local edits and show a revision-conflict message. Single-step Test requires an explicit confirmation dialog and selected worker ID query parameter; it must not be enabled for an invalid step.

- [ ] **Step 5: Add responsive editor styling**

At 1920x1080 use a fixed header, a scrollable step list, cards at least 48 px high when collapsed, and a right-side Add Step palette. Below 1100 px, move the palette above the list. Do not introduce a canvas or graph layout.

- [ ] **Step 6: Run page and API tests**

Run: `pytest -q tests/integration/test_equipment_skill_api.py -k 'workflow_editor or workflow_api'`

Expected: all selected tests pass.

- [ ] **Step 7: Run a non-commit review checkpoint**

Run: `git diff --check -- web/templates/equipment_skill_workflow_editor.html web/static/equipment_skill_workflow_editor.js web/static/styles.css`

Expected: no whitespace errors. Do not commit.

### Task 6: Skill Management Integration and Browser Verification

**Files:**
- Modify: `web/templates/windows_equipment.html`
- Modify: `web/static/windows_equipment.js`
- Modify: `tests/ui/windows_equipment_browser_audit.py`
- Modify: `docs/agents/equipment_agent.md`
- Modify: `docs/device_bridges/windows_pyautogui_bridge.md`
- Modify: `docs/tutorials/user_manual.ko.md`

**Interfaces:**
- Consumes: editor route and automatic deployment job from Tasks 3 and 5.
- Produces: exact selection to editor window, one-button Deploy UX, browser evidence, and user documentation.

- [ ] **Step 1: Update browser audit expectations before UI code**

```python
assert driver.find_elements(By.ID, "btn-equipment-skill-compile") == []
assert driver.find_elements(By.ID, "btn-equipment-skill-validate") == []
editor_button = driver.find_element(By.ID, "btn-equipment-skill-workflow-editor")
assert editor_button.get_attribute("title") == "Edit selected Skill workflow"
```

- [ ] **Step 2: Replace Skill Management controls**

```html
<button id="btn-equipment-skill-refresh" class="btn">Refresh</button>
<button id="btn-equipment-skill-workflow-editor" class="btn icon-only" type="button" title="Edit selected Skill workflow" aria-label="Edit selected Skill workflow" disabled>...</button>
<button id="btn-equipment-skill-deploy" class="btn primary">Deploy</button>
```

Remove the Compile and Validate elements and their JavaScript listeners. The icon button becomes enabled only after `selectedEquipmentSkill` is assigned.

- [ ] **Step 3: Open the exact Skill in a separate window**

```javascript
function openSelectedSkillWorkflowEditor() {
  if (!selectedEquipmentSkill) throw new Error("Select an exact Skill version first.");
  const {skill_id: skillId, version} = selectedEquipmentSkill;
  const worker = String(skillWorkerIdInput?.value || selectedBridgeId || "").trim();
  const url = `/equipment/skills/${encodeURIComponent(skillId)}/${encodeURIComponent(version)}/workflow-editor?worker=${encodeURIComponent(worker)}`;
  window.open(url, `atr-skill-${skillId}-${version}`, "popup=yes,width=1440,height=920,resizable=yes,scrollbars=yes");
}
```

- [ ] **Step 4: Update deployment progress copy**

Initial copy must say `Select a Skill and Worker.` During deployment, the existing progress component must display automatic `COMPILING`, `VALIDATING`, `PACKAGING`, `REGISTERING`, and `VERIFYING` job stages.

- [ ] **Step 5: Run browser audit and inspect screenshot**

Run: `python tests/ui/windows_equipment_browser_audit.py`

Expected: audit passes, Skill Management has three actions in the required order, and the dedicated editor opens without replacing the workspace.

- [ ] **Step 6: Run complete focused regression suite**

Run:

```bash
pytest -q \
  tests/unit/test_equipment_skill_workflow.py \
  tests/unit/test_equipment_skill_runtime.py \
  tests/integration/test_equipment_skill_api.py
node --test \
  tests/js/equipment_skill_workflow_model.test.js \
  tests/js/windows_equipment_selection.test.js
python -m py_compile \
  utils/equipment_skill_workflow.py \
  utils/equipment_skill_runtime.py \
  app/main.py
git diff --check
```

Expected: all tests and syntax checks pass with no diff-check errors.

- [ ] **Step 7: Perform simulator end-to-end acceptance**

Create a harmless Skill with `wait → screenshot → wait_until_image`, open it from Skill Management, edit and save it, press Deploy once, confirm the job reports compile/validate/register stages, and execute it in simulator/test mode. Verify the exact step order and that no physical UTM command was sent.

- [ ] **Step 8: Update documentation**

Document:

- why the editor is sequential;
- how image-until and timer waits behave;
- that Save invalidates old compiled artifacts;
- that Deploy automatically compiles and validates before transfer;
- that Deploy does not execute;
- how to create a new version before editing a deployed Skill.

- [ ] **Step 9: Final non-commit review checkpoint**

Run: `git status --short && git diff --stat && git diff --check`

Expected: only intended files are changed, all verification remains green, and no commit is created.
