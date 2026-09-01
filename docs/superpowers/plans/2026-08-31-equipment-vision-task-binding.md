# Equipment Vision Task Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each Lab Equipment Agent Vision Slot select and execute exactly one existing Equipment-compatible Vision Agent task through the canonical `vision.equipment_cross_check` path.

**Architecture:** Add one code-owned Equipment Vision Task catalog and make it the shared source for flow validation, Agent Manager choices, Equipment Agent request construction, and runtime projection. Preserve the existing ROS and test-mode virtual bridge implementation; only replace the current free-form `condition` selector and fixed three-check dispatch with exact `task_id` binding.

**Tech Stack:** Python 3.12, FastAPI, pytest, vanilla JavaScript, Node test runner, Selenium/Firefox, existing ATR MCP tool registry and Equipment Skill Flow runtime.

**Spec:** `docs/superpowers/specs/2026-08-31-equipment-vision-task-binding-design.md`

## Global Constraints

- Reuse `vision.equipment_cross_check`; do not create a second Vision runtime or instantiate `VisionAgent` from `EquipmentAgent`.
- Preserve existing ROS observation, virtual UTM bridge, and device actuation behavior.
- An enabled Vision Slot executes exactly one selected task and never falls back to all three UTM checks.
- Agent Manager remains the only Equipment Skill Flow editor; Equipment Bridge, Live GUI, and Runtime IDE remain read-only projections.
- Unknown tasks, stale identity, malformed results, and unavailable tools fail closed before a subsequent Skill executes.
- Do not stop vLLM, LeRobot, camera, PLC, printer, or Windows bridge processes while running non-hardware tests.
- Do not modify unrelated dirty-worktree changes.

## File Structure

- Create `utils/equipment_vision_tasks.py`: code-owned task catalog, exact task resolution, and request construction.
- Create `tests/unit/test_equipment_vision_tasks.py`: catalog and request-construction contract tests.
- Modify `utils/equipment_skill_flow.py`: canonical `vision.task_id`, legacy migration, validation, and graph metadata.
- Modify `web/static/equipment_skill_flow_model.js`: browser-side default block shape and immutable task ID updates.
- Modify `tests/unit/test_equipment_skill_flow.py`: normalization, migration, invalid-task, and runtime graph tests.
- Modify `tests/js/equipment_skill_flow_model.test.js`: browser model default and task-selection tests.
- Modify `app/main.py`: include the task catalog and migration notes in the existing Skill Flow payload and readiness.
- Modify `web/static/equipment_agent_manager.js`: replace Condition input with a catalog-backed task selector and read-only task details.
- Modify `tests/integration/test_live_gui_runtime_layout.py`: API sharing, readiness, and single-editor assertions.
- Modify `tests/ui/equipment_agent_manager_browser_audit.py`: browser save/reopen and projection verification for selected tasks.
- Modify `agents/equipment_agent.py`: build and execute one selected Vision check and persist task evidence.
- Modify `utils/equipment_skill_runtime.py`: retain selected task identity in Vision transitions if the existing transition writer drops it.
- Modify `tests/unit/test_equipment_agent.py`: single-check dispatch and result-to-outcome tests.
- Modify `web/static/runtime_ide.js`: render selected task identity instead of legacy condition text.
- Modify `web/static/windows_equipment.js`: render selected task identity in the read-only Equipment Bridge projection.
- Modify `web/static/planning.js`: render selected task identity in the Live GUI Equipment projection.
- Modify `docs/agents/equipment_agent.md`: document Vision Task binding and runtime evidence.
- Modify `docs/runtime/runtime_ide.md`: document read-only task projection.
- Modify `docs/superpowers/specs/2026-08-30-equipment-skill-flow-design.md`: supersede free-form Vision condition wording with exact Task binding.

---

### Task 1: Shared Equipment Vision Task Catalog

**Files:**
- Create: `utils/equipment_vision_tasks.py`
- Create: `tests/unit/test_equipment_vision_tasks.py`
- Modify: `mcp_tools/camera_tools.py`

**Interfaces:**
- Produces: `list_equipment_vision_tasks() -> list[dict[str, Any]]`
- Produces: `get_equipment_vision_task(task_id: str) -> dict[str, Any]`
- Produces: `build_equipment_vision_check(task_id: str, *, run_id: str, loop_id: int, specimen_id: str) -> dict[str, Any]`
- Produces: `EQUIPMENT_VISION_TASK_IDS: frozenset[str]`
- Consumes: no application state and no Agent instance.

- [ ] **Step 1: Write failing catalog tests**

```python
from utils.equipment_vision_tasks import (
    EQUIPMENT_VISION_TASK_IDS,
    build_equipment_vision_check,
    get_equipment_vision_task,
    list_equipment_vision_tasks,
)


def test_catalog_exposes_existing_utm_tasks_once():
    tasks = list_equipment_vision_tasks()
    assert [item["task_id"] for item in tasks] == [
        "utm_pre_start",
        "utm_motion_confirm",
        "utm_test_complete",
    ]
    assert EQUIPMENT_VISION_TASK_IDS == frozenset(item["task_id"] for item in tasks)
    assert get_equipment_vision_task("utm_motion_confirm")["timeout_s"] == 10


def test_build_check_preserves_runtime_identity_and_selected_task_only():
    check = build_equipment_vision_check(
        "utm_pre_start",
        run_id="run-7",
        loop_id=3,
        specimen_id="specimen-4",
    )
    assert check["check_id"] == "utm_pre_start"
    assert check["run_id"] == "run-7"
    assert check["loop_id"] == 3
    assert check["specimen_id"] == "specimen-4"
    assert check["producer_agent"] == "equipment_agent"
    assert check["consumer_agent"] == "vision_agent"
    assert check["expected"]["specimen_on_utm_fixture"] is True
```

- [ ] **Step 2: Run tests and confirm the module is missing**

Run: `pytest -q tests/unit/test_equipment_vision_tasks.py`

Expected: collection fails with `ModuleNotFoundError: utils.equipment_vision_tasks`.

- [ ] **Step 3: Implement the immutable catalog and exact resolver**

```python
from copy import deepcopy
from typing import Any


_TASKS = (
    {
        "task_id": "utm_pre_start",
        "check_id": "utm_pre_start",
        "label": "Pre-UTM Fixture Check",
        "description": "Verify the fixture and workspace before UTM motion.",
        "timeout_s": 5,
        "runtime_modes": ["test", "live"],
        "expected": {
            "specimen_on_utm_fixture": True,
            "robot_clear_of_utm": True,
            "compression_flatten_occupied": True,
            "human_intrusion": False,
        },
    },
    {
        "task_id": "utm_motion_confirm",
        "check_id": "utm_motion_confirm",
        "label": "UTM Motion Confirmation",
        "description": "Verify UTM motion and specimen alignment during the test.",
        "timeout_s": 10,
        "runtime_modes": ["test", "live"],
        "expected": {
            "utm_crosshead_motion": "started_or_force_curve_active",
            "specimen_remains_aligned": True,
            "fixture_slip_detected": False,
        },
    },
    {
        "task_id": "utm_test_complete",
        "check_id": "utm_test_complete",
        "label": "Post-UTM Completion Check",
        "description": "Verify stopped motion, safe access, and completion evidence.",
        "timeout_s": 10,
        "runtime_modes": ["test", "live"],
        "expected": {
            "utm_crosshead_stopped": True,
            "fixture_safe_to_access": True,
            "specimen_tested_or_crushed": True,
        },
    },
)

EQUIPMENT_VISION_TASK_IDS = frozenset(item["task_id"] for item in _TASKS)


def list_equipment_vision_tasks() -> list[dict[str, Any]]:
    return deepcopy(list(_TASKS))


def get_equipment_vision_task(task_id: str) -> dict[str, Any]:
    clean = str(task_id or "").strip()
    for task in _TASKS:
        if task["task_id"] == clean:
            return deepcopy(task)
    raise ValueError(f"unknown Equipment Vision task: {clean or '<empty>'}")


def build_equipment_vision_check(
    task_id: str,
    *,
    run_id: str,
    loop_id: int,
    specimen_id: str,
) -> dict[str, Any]:
    task = get_equipment_vision_task(task_id)
    return {
        "agent_signal_type": "equipment_vision_check_request",
        "task_id": task["task_id"],
        "check_id": task["check_id"],
        "run_id": run_id,
        "loop_id": loop_id,
        "specimen_id": specimen_id,
        "producer_agent": "equipment_agent",
        "consumer_agent": "vision_agent",
        "expected": task["expected"],
        "timeout_s": task["timeout_s"],
    }
```

- [ ] **Step 4: Make the camera tool derive valid IDs from the shared catalog**

Replace the local literal set in `mcp_tools/camera_tools.py`:

```python
from utils.equipment_vision_tasks import EQUIPMENT_VISION_TASK_IDS

UTM_CHECK_IDS = set(EQUIPMENT_VISION_TASK_IDS)
```

Do not alter `_equipment_cross_check`, `_virtual_utm_observation`, or the ROS observer behavior.

- [ ] **Step 5: Run catalog and camera-tool tests**

Run: `pytest -q tests/unit/test_equipment_vision_tasks.py tests/unit/test_camera_tools_utm_runtime.py`

Expected: all selected tests pass.

- [ ] **Step 6: Commit the catalog boundary**

```bash
git add utils/equipment_vision_tasks.py mcp_tools/camera_tools.py tests/unit/test_equipment_vision_tasks.py
git commit -m "feat: add equipment vision task catalog"
```

---

### Task 2: Canonical Flow Task Binding And Legacy Migration

**Files:**
- Modify: `utils/equipment_skill_flow.py`
- Modify: `web/static/equipment_skill_flow_model.js`
- Modify: `tests/unit/test_equipment_skill_flow.py`
- Modify: `tests/js/equipment_skill_flow_model.test.js`

**Interfaces:**
- Consumes: `EQUIPMENT_VISION_TASK_IDS` and `get_equipment_vision_task()` from Task 1.
- Produces: normalized `block["vision"]["task_id"]`.
- Produces: `EquipmentSkillFlowStore.get_with_migration(profile_id: str) -> tuple[dict[str, Any], list[str]]`.
- Preserves: `normalize_equipment_skill_flow(profile_id, payload) -> dict[str, Any]` for existing callers.

- [ ] **Step 1: Add failing normalization and migration tests**

```python
def _flow(vision):
    return {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": "utm_windows_v1",
        "profile_id": "utm_windows_v1",
        "version": 1,
        "blocks": [
            {
                "id": "block_01",
                "label": "UTM task",
                "skill": {"skill_id": "", "skill_version": ""},
                "agentic": {"task": "UTM task", "completed": "__complete__", "failed": "__blocked__"},
                "vision": {
                    "detected": "__complete__",
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                    **vision,
                },
            }
        ],
    }


def test_enabled_vision_requires_catalog_task_id(tmp_path):
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    flow = _flow({"enabled": True, "task_id": "unknown_task"})
    with pytest.raises(EquipmentSkillFlowError, match="unknown Equipment Vision task"):
        store.save("utm_windows_v1", flow)


def test_legacy_condition_migrates_to_pre_start(tmp_path):
    store = EquipmentSkillFlowStore(tmp_path / "flows.json")
    legacy = _flow({"enabled": True, "condition": "equipment_specimen_detected"})
    store.path.write_text(json.dumps({"schema": STORE_SCHEMA, "flows": {"utm_windows_v1": legacy}}))
    flow, notes = store.get_with_migration("utm_windows_v1")
    assert flow["blocks"][0]["vision"]["task_id"] == "utm_pre_start"
    assert "block_01" in notes[0]
    assert "condition" not in flow["blocks"][0]["vision"]


def test_disabled_vision_may_remain_unbound():
    flow = normalize_equipment_skill_flow("utm_windows_v1", _flow({"enabled": False, "task_id": ""}))
    assert flow["blocks"][0]["vision"]["task_id"] == ""
```

- [ ] **Step 2: Run focused tests and verify failures**

Run: `pytest -q tests/unit/test_equipment_skill_flow.py -k 'vision or migration'`

Expected: tests fail because `task_id` and `get_with_migration` are not implemented.

- [ ] **Step 3: Add one migration helper and canonical task validation**

Implement a focused helper in `utils/equipment_skill_flow.py`:

```python
def _vision_task_id(vision: dict[str, Any], *, enabled: bool, block_id: str, notes: list[str]) -> str:
    task_id = str(vision.get("task_id") or "").strip()
    legacy = str(vision.get("condition") or "").strip()
    if not task_id and legacy in EQUIPMENT_VISION_TASK_IDS:
        task_id = legacy
        notes.append(f"{block_id}: migrated vision.condition={legacy} to vision.task_id")
    elif not task_id and enabled and legacy:
        task_id = "utm_pre_start"
        notes.append(f"{block_id}: migrated legacy Vision condition to utm_pre_start")
    if enabled and task_id not in EQUIPMENT_VISION_TASK_IDS:
        raise EquipmentSkillFlowError(f"{block_id}.vision.task_id references unknown Equipment Vision task: {task_id or '<empty>'}")
    if task_id and task_id not in EQUIPMENT_VISION_TASK_IDS:
        raise EquipmentSkillFlowError(f"{block_id}.vision.task_id references unknown Equipment Vision task: {task_id}")
    return task_id
```

Thread a caller-owned `notes: list[str]` through internal normalization without adding notes to persisted flow JSON. Implement `get_with_migration()` so API callers can retrieve notes while existing `get()` discards them.

- [ ] **Step 4: Replace Vision condition metadata in runtime graphs**

For enabled Vision nodes, resolve the task and emit:

```python
task = get_equipment_vision_task(block["vision"]["task_id"])
metadata = {
    "control_level": "middle",
    "block_id": block["id"],
    "task_id": task["task_id"],
    "check_id": task["check_id"],
    "timeout_s": task["timeout_s"],
}
```

Use `task["label"]` as the Vision node label. Keep existing detected/not-detected/timeout/error edges.

- [ ] **Step 5: Update the browser flow model**

Change new blocks to store:

```javascript
vision: {
  enabled: false,
  task_id: "",
  detected: "__complete__",
  not_detected: "__blocked__",
  timeout: "__blocked__",
  error: "__blocked__",
}
```

Add a Node test proving `updateBlock(flow, id, "vision.task_id", "utm_motion_confirm")` preserves the selected ID through `rebuildSequence()`.

- [ ] **Step 6: Run Python and JavaScript contract tests**

Run:

```bash
pytest -q tests/unit/test_equipment_skill_flow.py
node --test tests/js/equipment_skill_flow_model.test.js
```

Expected: all tests pass and no normalized flow persists `vision.condition`.

- [ ] **Step 7: Commit the flow contract**

```bash
git add utils/equipment_skill_flow.py web/static/equipment_skill_flow_model.js tests/unit/test_equipment_skill_flow.py tests/js/equipment_skill_flow_model.test.js
git commit -m "feat: bind equipment vision slots to task ids"
```

---

### Task 3: API Readiness And Agent Manager Task Selection

**Files:**
- Modify: `app/main.py`
- Modify: `web/static/equipment_agent_manager.js`
- Modify: `web/static/equipment_agent_manager.css`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`
- Modify: `tests/ui/equipment_agent_manager_browser_audit.py`

**Interfaces:**
- Consumes: `list_equipment_vision_tasks()` and `EquipmentSkillFlowStore.get_with_migration()`.
- Produces: `vision_tasks: list[dict[str, Any]]` and `migration_notes: list[str]` in the existing Skill Flow GET/PUT payload.
- Produces: block readiness fields `vision_task_id`, `vision_task_label`, and Vision-specific failure reason.

- [ ] **Step 1: Add failing API tests**

Extend `test_equipment_skill_flow_is_shared_by_workspace_and_runtime_ide`:

```python
vision = {
    "enabled": True,
    "task_id": "utm_motion_confirm",
    "detected": "__complete__",
    "not_detected": "__blocked__",
    "timeout": "__blocked__",
    "error": "__blocked__",
}
assert workspace.json()["vision_tasks"][1]["task_id"] == "utm_motion_confirm"
assert workspace.json()["readiness"]["blocks"][0]["vision_task_id"] == "utm_motion_confirm"
assert runtime.json()["flow"] == workspace.json()["flow"]
```

Add a test that PUT with `enabled=True, task_id="missing"` returns HTTP 422 and leaves the previously stored flow unchanged.

- [ ] **Step 2: Run API tests and verify the missing payload fields**

Run: `pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment_skill_flow'`

Expected: failures for missing `vision_tasks` and task-aware readiness.

- [ ] **Step 3: Extend the canonical API payload**

In `_equipment_skill_flow_payload()`:

```python
flow, migration_notes = store.get_with_migration(profile.profile_id)
vision_tasks = list_equipment_vision_tasks()
```

For every block, make readiness false when Vision is enabled and its `task_id` is absent from the catalog. Return:

```python
{
    "ok": True,
    "profile_id": profile.profile_id,
    "flow": flow,
    "graph": graph,
    "skills": skills,
    "vision_tasks": vision_tasks,
    "migration_notes": migration_notes,
    "readiness": {"ready": ready, "blocks": block_readiness},
    "execution": execution,
    "workspace_settings": _equipment_profile_workspace_settings(profile),
}
```

- [ ] **Step 4: Replace the free-form Condition field with a task selector**

In `equipment_agent_manager.js`, store `payload.vision_tasks` in one module-level array. Render:

```html
<label>Vision Task
  <select class="manager-select" data-field="vision.task_id">
    <option value="">Select Vision Task</option>
    <!-- options from payload.vision_tasks -->
  </select>
</label>
<div class="equipment-manager-task-detail" data-vision-task-detail>
  <!-- label, description, evidence summary, timeout, runtime modes -->
</div>
```

Use only the server-provided catalog. Do not duplicate task labels or timeout values in JavaScript.

- [ ] **Step 5: Update browser audit behavior**

In the Selenium audit:

```javascript
const task = current.querySelector('[data-field="vision.task_id"]');
task.value = 'utm_motion_confirm';
task.dispatchEvent(new Event('change', {bubbles: true}));
```

After refresh, assert `visionTask === "utm_motion_confirm"`, the detail panel contains `UTM Motion Confirmation`, and Runtime IDE text contains the same label.

- [ ] **Step 6: Run API and browser-model tests**

Run:

```bash
pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment_skill_flow or agent_manager'
pytest -q tests/ui/equipment_agent_manager_browser_audit.py --collect-only
```

Expected: all selected tests pass; browser audit imports and collects without errors.

- [ ] **Step 7: Commit the authoring surface**

```bash
git add app/main.py web/static/equipment_agent_manager.js web/static/equipment_agent_manager.css tests/integration/test_live_gui_runtime_layout.py tests/ui/equipment_agent_manager_browser_audit.py
git commit -m "feat: select vision tasks in equipment agent manager"
```

---

### Task 4: Equipment Agent Single-Task Runtime Dispatch

**Files:**
- Modify: `agents/equipment_agent.py`
- Modify: `utils/equipment_skill_runtime.py`
- Modify: `tests/unit/test_equipment_agent.py`
- Modify: `tests/unit/test_equipment_skill_runtime.py`

**Interfaces:**
- Consumes: `build_equipment_vision_check()` and `get_equipment_vision_task()`.
- Produces: one-item `checks` payload for each configured Vision phase.
- Produces: transition evidence fields `vision_task_id`, `check_id`, `task_label`, `observer_mode`, `outcome`, and bounded evidence references.
- Preserves: legacy non-Agent-Manager Equipment execution outside `_run_equipment_skill_flow` unless its tests explicitly require catalog reuse.

- [ ] **Step 1: Strengthen the existing composite-flow runtime test**

Capture calls to `vision.equipment_cross_check` and assert:

```python
assert len(vision_payloads) == 1
assert [item["check_id"] for item in vision_payloads[0]["checks"]] == ["utm_motion_confirm"]
assert vision_payloads[0]["checks"][0]["task_id"] == "utm_motion_confirm"
assert execution["transitions"][-1]["vision_task_id"] == "utm_motion_confirm"
```

Parameterize response failures:

```python
(
    {"ok": False, "failure_code": "TOPIC_TIMEOUT", "results": [{"ok": False}]},
    "timeout",
),
(
    {"ok": False, "failure_code": "UTM_MOTION_NOT_CONFIRMED", "results": [{"ok": False}]},
    "not_detected",
),
(
    {"ok": False, "failure_code": "UTM_OBSERVER_NOT_CONFIGURED", "results": []},
    "error",
),
```

- [ ] **Step 2: Run the runtime tests and verify they expose three-check dispatch**

Run: `pytest -q tests/unit/test_equipment_agent.py -k 'skill_flow'`

Expected: selected-task assertions fail because the current code submits all three checks.

- [ ] **Step 3: Add a singular request helper**

Replace use of `_equipment_vision_requests()` inside `_run_equipment_skill_flow` with:

```python
def _equipment_vision_request(self, *, task_id, state, source_stage_context):
    specimen = source_stage_context.get("specimen") if isinstance(source_stage_context.get("specimen"), dict) else {}
    specimen_id = str(specimen.get("specimen_id") or state.current_experiment_spec.get("specimen_id") or "")
    return build_equipment_vision_check(
        task_id,
        run_id=str(state.run_id or ""),
        loop_id=int(state.loop_count or 0),
        specimen_id=specimen_id,
    )
```

The flow execution payload must use `"checks": [request]`. Do not call `_equipment_vision_requests()` from the Profile-bound flow path.

- [ ] **Step 4: Implement explicit result-to-outcome mapping**

Add one pure helper:

```python
def _equipment_vision_outcome(response: dict[str, Any]) -> str:
    if response.get("ok") and len(response.get("results") or []) == 1 and response["results"][0].get("ok"):
        return "detected"
    code = str(response.get("failure_code") or "")
    if "TIMEOUT" in code:
        return "timeout"
    if code in {"UTM_MOTION_NOT_CONFIRMED", "UTM_TEST_COMPLETE_EVIDENCE_REQUIRED", "VISION_EQUIPMENT_CROSS_CHECK_REQUIRED"}:
        return "not_detected"
    return "error"
```

Before mapping success, preserve existing run/specimen identity and freshness checks. Identity or freshness failure maps to `error`.

- [ ] **Step 5: Persist selected task evidence**

When recording the Vision transition, include:

```python
{
    "vision_task_id": task["task_id"],
    "check_id": task["check_id"],
    "task_label": task["label"],
    "observer_mode": response.get("observer_mode"),
    "virtualized": bool(response.get("virtualized")),
    "outcome": outcome,
    "evidence": response.get("results", [{}])[0].get("evidence", {}),
    "failure_code": response.get("failure_code"),
}
```

Update `utils/equipment_skill_runtime.py` only if its transition normalization currently strips these fields; retain arbitrary bounded metadata rather than creating a second runtime file.

- [ ] **Step 6: Run Equipment Agent and runtime tests**

Run:

```bash
pytest -q tests/unit/test_equipment_agent.py -k 'skill_flow'
pytest -q tests/unit/test_equipment_skill_runtime.py
```

Expected: all selected tests pass, and captured payloads contain one check only.

- [ ] **Step 7: Commit runtime dispatch**

```bash
git add agents/equipment_agent.py utils/equipment_skill_runtime.py tests/unit/test_equipment_agent.py tests/unit/test_equipment_skill_runtime.py
git commit -m "fix: execute selected equipment vision task"
```

---

### Task 5: Read-Only Runtime Projections

**Files:**
- Modify: `web/static/runtime_ide.js`
- Modify: `web/static/windows_equipment.js`
- Modify: `web/static/planning.js`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`
- Modify: `tests/ui/equipment_agent_manager_browser_audit.py`

**Interfaces:**
- Consumes: API `flow.blocks[].vision.task_id`, `vision_tasks`, graph task metadata, and execution transitions.
- Produces: identical selected-task labels and current outcomes on Runtime IDE, Equipment Bridge, and Live GUI.
- Does not produce configuration writes.

- [ ] **Step 1: Add failing projection assertions**

Assert all three read-only surfaces contain `UTM Motion Confirmation` for a saved `utm_motion_confirm` slot and do not contain `equipment_specimen_detected` or a Vision mutation control.

```python
assert "UTM Motion Confirmation" in runtime_projection_text
assert "equipment_specimen_detected" not in runtime_projection_text
assert mutation_controls == 0
```

- [ ] **Step 2: Run focused integration tests**

Run: `pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment or runtime'`

Expected: failures where projections still render `vision.condition`.

- [ ] **Step 3: Render catalog task labels in Runtime IDE**

Build a lookup from `runtimeEquipmentFlowPayload.vision_tasks`. Replace:

```javascript
block.vision.condition || "equipment_specimen_detected"
```

with the selected catalog label. Display the canonical `task_id` in secondary metadata and the execution outcome when the matching block transition exists.

- [ ] **Step 4: Render the same label in Equipment Bridge and Live GUI**

Use each surface's already-fetched Skill Flow payload. Do not add another endpoint or task-name constant. Preserve current polling cadence and DOM containers; update only the Vision text and active outcome fields.

- [ ] **Step 5: Run integration and browser audit**

With the existing GUI server available on port 7860:

```bash
pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment or runtime'
python tests/ui/equipment_agent_manager_browser_audit.py \
  --base-url http://127.0.0.1:7860 \
  --out-dir artifacts/ui/equipment_vision_task_binding
```

Expected: Selenium audit prints `equipment_agent_manager_browser_audit: PASS` and writes manager, bridge, and Runtime IDE screenshots.

- [ ] **Step 6: Commit projection changes**

```bash
git add web/static/runtime_ide.js web/static/windows_equipment.js web/static/planning.js tests/integration/test_live_gui_runtime_layout.py tests/ui/equipment_agent_manager_browser_audit.py
git commit -m "feat: project selected equipment vision task"
```

---

### Task 6: Documentation And Full Verification

**Files:**
- Modify: `docs/agents/equipment_agent.md`
- Modify: `docs/runtime/runtime_ide.md`
- Modify: `docs/superpowers/specs/2026-08-30-equipment-skill-flow-design.md`
- Verify: all files from Tasks 1-5.

**Interfaces:**
- Consumes: final implementation and test evidence.
- Produces: operator-facing explanation of task selection, execution, evidence, and migration.

- [ ] **Step 1: Update canonical documentation**

Document:

- Agent Manager selects one existing Vision Task per enabled Vision Slot.
- The current tasks are Pre-UTM Fixture Check, UTM Motion Confirmation, and Post-UTM Completion Check.
- Equipment Agent executes the selected task through `vision.equipment_cross_check`.
- Runtime IDE and Equipment Bridge are read-only projections.
- Test-mode virtual evidence remains explicitly marked.
- Legacy condition strings migrate to canonical task IDs.

In `2026-08-30-equipment-skill-flow-design.md`, replace wording that identifies `condition` as the editable canonical selector; reference the focused 2026-08-31 design.

- [ ] **Step 2: Run static checks**

Run:

```bash
python -m py_compile utils/equipment_vision_tasks.py utils/equipment_skill_flow.py agents/equipment_agent.py app/main.py
git diff --check
rg -n 'vision\.condition|equipment_specimen_detected' \
  web/static/equipment_agent_manager.js \
  web/static/runtime_ide.js \
  web/static/windows_equipment.js \
  web/static/planning.js
```

Expected: Python compilation and `git diff --check` pass; the final `rg` command returns no UI/runtime selector references.

- [ ] **Step 3: Run the focused regression suite**

Run:

```bash
pytest -q \
  tests/unit/test_equipment_vision_tasks.py \
  tests/unit/test_equipment_skill_flow.py \
  tests/unit/test_equipment_skill_runtime.py \
  tests/unit/test_equipment_agent.py \
  tests/integration/test_live_gui_runtime_layout.py
node --test tests/js/equipment_skill_flow_model.test.js
```

Expected: all selected Python and JavaScript tests pass.

- [ ] **Step 4: Verify no physical-device behavior changed**

Run the existing test-mode Equipment flow with `utm_motion_confirm` selected and inspect captured evidence rather than actuating hardware:

```bash
python - <<'PY'
from utils.equipment_skill_flow import EquipmentSkillFlowStore
from pathlib import Path

flow = EquipmentSkillFlowStore(Path("graphs/modules/equipment/equipment_skill_flows.json")).get("utm_windows_v1")
for block in flow.get("blocks", []):
    if block.get("vision", {}).get("enabled"):
        print(block["id"], block["vision"]["task_id"])
PY
```

Expected: each enabled block prints exactly one canonical task ID. No printer, UTM, robot, camera, or PLC command is issued by this verification command.

- [ ] **Step 5: Review the complete diff for scope**

Run:

```bash
git status --short
git diff --stat
git diff -- \
  utils/equipment_vision_tasks.py \
  utils/equipment_skill_flow.py \
  agents/equipment_agent.py \
  app/main.py \
  web/static/equipment_agent_manager.js \
  web/static/runtime_ide.js \
  web/static/windows_equipment.js \
  web/static/planning.js
```

Expected: changes are limited to task catalog, task binding, single-task dispatch, projections, tests, and documentation. Existing device transport and ROS observer internals are unchanged.

- [ ] **Step 6: Commit documentation and final verification state**

```bash
git add docs/agents/equipment_agent.md docs/runtime/runtime_ide.md docs/superpowers/specs/2026-08-30-equipment-skill-flow-design.md docs/superpowers/specs/2026-08-31-equipment-vision-task-binding-design.md docs/superpowers/plans/2026-08-31-equipment-vision-task-binding.md
git commit -m "docs: describe equipment vision task binding"
```
