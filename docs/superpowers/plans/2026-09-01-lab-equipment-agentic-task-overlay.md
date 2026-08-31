# Lab Equipment Agentic Task Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `run_utm_compression_cycle` above the existing Profile-bound Equipment Skill Flow and project the same eight-step execution, equipment values, screen evidence, Raw CSV state, and next-specimen readiness in the existing Live GUI.

**Architecture:** A new pure Python contract module owns the code-defined workflow task, locked upstream handoff gate, eight canonical block roles, and additive report projection. `LabEquipmentAgent` composes that contract around its existing flow executor without changing Skill Runtime or per-block Vision semantics. Agent Manager can load the canonical eight-block draft, while the existing `/live` Equipment dashboard renders authoritative overlay fields through a small pure JavaScript projection model with legacy fallback.

**Tech Stack:** Python 3.12, pytest, FastAPI/Pydantic, plain browser JavaScript, Node `node:test`, existing Equipment Skill Flow/Runtime/PyAutoGUI bridge.

**Spec:** `docs/superpowers/specs/2026-09-01-lab-equipment-agentic-task-overlay-design.md`

## Global Constraints

- Modify Lab Equipment Agent orchestration only; do not modify Manipulation Agent source, policy, or profile behavior.
- Keep the existing Profile-bound Equipment Skill Flow as the sole editable block/Skill/Vision source.
- The upstream UTM/specimen handoff is required and has no editable ON/OFF field.
- Preserve every block's existing optional `vision.enabled` switch and bounded Vision routes.
- Use Force, Stroke, and Height without a transport label.
- Do not hardcode recorded contact, travel, return, speed, or clearance values.
- Do not add direct equipment-click controls to Live GUI.
- Preserve legacy Profile execution when no workflow-level Agentic Task is bound.
- Use `.venv/bin/python -m pytest` for Python verification.
- The current worktree already contains user-owned Equipment changes; stage or commit only new files or demonstrably task-local hunks.

---

### Task 1: Workflow-Level Contract And Canonical Draft

**Files:**
- Create: `utils/equipment_agentic_task.py`
- Create: `tests/unit/test_equipment_agentic_task.py`
- Modify: `utils/equipment_skill_flow.py`
- Test: `tests/unit/test_equipment_skill_flow.py`

**Interfaces:**
- Produces: `UTM_COMPRESSION_TASK_ID: str`.
- Produces: `list_equipment_agentic_tasks() -> list[dict[str, Any]]`.
- Produces: `build_utm_compression_flow_template(profile_id: str) -> dict[str, Any]`.
- Produces: `evaluate_equipment_entry_gate(*, run_id: str, specimen_id: str, source_stage_context: dict[str, Any], test_like: bool) -> dict[str, Any]`.
- Extends normalized flows with `agentic_task_id: str` while preserving legacy empty-string behavior.

- [ ] **Step 1: Write failing contract tests**

```python
from utils.equipment_agentic_task import (
    UTM_COMPRESSION_TASK_ID,
    build_utm_compression_flow_template,
    evaluate_equipment_entry_gate,
)


def test_utm_template_has_eight_method_driven_blocks_and_no_skill_or_vision_binding():
    flow = build_utm_compression_flow_template("utm_windows_v1")
    assert flow["agentic_task_id"] == UTM_COMPRESSION_TASK_ID
    assert [block["id"] for block in flow["blocks"]] == [
        "prepare_next_specimen", "start_test", "monitor_contact_and_run",
        "await_auto_return", "save_raw_data", "validate_raw_data",
        "advance_without_save", "restore_robot_clearance",
    ]
    assert all(block["skill"] == {"skill_id": "", "skill_version": ""} for block in flow["blocks"])
    assert all(block["vision"]["enabled"] is False for block in flow["blocks"])
    assert "5" not in repr(flow) and "21" not in repr(flow) and "120" not in repr(flow)


def test_live_entry_gate_requires_ready_for_equipment_identity():
    gate = evaluate_equipment_entry_gate(
        run_id="run-1",
        specimen_id="specimen-1",
        source_stage_context={
            "manipulation": {"handoff_status": "ready_for_equipment", "run_id": "run-1", "specimen_id": "specimen-1"},
            "specimen": {"specimen_id": "specimen-1"},
        },
        test_like=False,
    )
    assert gate["ok"] is True
    assert gate["locked"] is True
    assert "enabled" not in gate
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_equipment_agentic_task.py tests/unit/test_equipment_skill_flow.py`

Expected: collection fails because `utils.equipment_agentic_task` does not exist.

- [ ] **Step 3: Implement the pure contract and flow envelope field**

Implement immutable task metadata and a template builder in `utils/equipment_agentic_task.py`. Every template block must use its canonical ID and task label, empty exact Skill binding, disabled optional Vision, `next` success routes except the final `__complete__`, and `__blocked__` failure routes.

```python
UTM_COMPRESSION_TASK_ID = "run_utm_compression_cycle"
UTM_COMPRESSION_BLOCKS = (
    ("prepare_next_specimen", "Move Jigs for Next Specimen"),
    ("start_test", "Start Test"),
    ("monitor_contact_and_run", "Monitor contact and method-driven compression"),
    ("await_auto_return", "Wait for automatic Height return"),
    ("save_raw_data", "Save Raw Data CSV"),
    ("validate_raw_data", "Validate Raw Data CSV"),
    ("advance_without_save", "Next Test without saving current test"),
    ("restore_robot_clearance", "Restore configured robot-entry clearance"),
)
```

`evaluate_equipment_entry_gate` must accept the existing handoff only when live identity is consistent and the status is `ready_for_equipment`; test-like mode may return explicit simulated evidence. The returned schema is `atr.equipment_entry_gate.v1`, always includes `locked: True`, and never includes an enable switch.

Extend `empty_equipment_skill_flow` and `normalize_equipment_skill_flow` with `agentic_task_id`, defaulting to `""`; do not infer the overlay merely from Profile ID.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_equipment_agentic_task.py tests/unit/test_equipment_skill_flow.py`

Expected: all selected tests pass.

- [ ] **Step 5: Commit new contract files only**

```bash
git add utils/equipment_agentic_task.py tests/unit/test_equipment_agentic_task.py
git commit -m "feat: add equipment agentic task contract"
```

Leave `utils/equipment_skill_flow.py` unstaged if its pre-existing user changes cannot be isolated safely.

### Task 2: Agent Manager Canonical Task Configuration

**Files:**
- Modify: `app/main.py`
- Modify: `web/static/equipment_skill_flow_model.js`
- Modify: `web/static/equipment_agent_manager.js`
- Modify: `web/templates/equipment_agent_manager.html`
- Modify: `web/static/equipment_agent_manager.css`
- Modify: `tests/js/equipment_skill_flow_model.test.js`
- Modify: `tests/integration/test_equipment_skill_api.py`
- Modify: `tests/ui/equipment_agent_manager_browser_audit.py`

**Interfaces:**
- Consumes: `list_equipment_agentic_tasks()` and `build_utm_compression_flow_template()` from Task 1.
- Produces: GET Skill Flow payload fields `agentic_tasks` and `flow_templates`.
- Produces: `ATREquipmentSkillFlow.applyTemplate(currentFlow, template) -> flow`.

- [ ] **Step 1: Write failing API and JavaScript tests**

```javascript
test("UTM template replaces the draft while preserving Profile identity", () => {
  const current = model.empty("utm_windows_v1");
  const template = { agentic_task_id: "run_utm_compression_cycle", blocks: [{ id: "prepare_next_specimen", label: "Move Jigs", skill: { skill_id: "", skill_version: "" }, agentic: { task: "Move Jigs", completed: "__complete__", failed: "__blocked__" }, vision: { enabled: false, task_id: "", detected: "__complete__", not_detected: "__blocked__", timeout: "__blocked__", error: "__blocked__" } }] };
  const next = model.applyTemplate(current, template);
  assert.equal(next.profile_id, "utm_windows_v1");
  assert.equal(next.agentic_task_id, "run_utm_compression_cycle");
  assert.equal(next.blocks[0].id, "prepare_next_specimen");
});
```

Add an API assertion that `/api/equipment/profiles/utm_windows_v1/skill-flow` returns the code-owned task catalog and an eight-block template with no bound Skill or enabled Vision.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test tests/js/equipment_skill_flow_model.test.js && .venv/bin/python -m pytest -q tests/integration/test_equipment_skill_api.py -k 'skill_flow'`

Expected: JavaScript fails because `applyTemplate` is undefined and API assertions fail because catalogs are absent.

- [ ] **Step 3: Implement API payload and Agent Manager task panel**

Add to `_equipment_skill_flow_payload`:

```python
"agentic_tasks": list_equipment_agentic_tasks(),
"flow_templates": [build_utm_compression_flow_template(profile.profile_id)],
```

Implement `applyTemplate` as a deep-cloned replacement that preserves `schema`, `flow_id`, `profile_id`, and increments no persisted version until save.

Add a workflow-level panel above the current blocks showing:

- selected Agentic Task;
- locked `Verified specimen/UTM handoff` badge with no checkbox;
- `Load UTM Compression Cycle` draft button;
- eight logical phases;
- note that Skill binding and optional Vision remain inside each block.

Loading a template is an unsaved draft and never auto-saves or binds the only available demonstration Skill.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `node --test tests/js/equipment_skill_flow_model.test.js && .venv/bin/python -m pytest -q tests/integration/test_equipment_skill_api.py -k 'skill_flow' && .venv/bin/python -m pytest -q tests/ui/equipment_agent_manager_browser_audit.py --collect-only`

Expected: selected tests pass and browser audit collects.

- [ ] **Step 5: Commit only isolated UI/model additions where safe**

```bash
git add tests/js/equipment_skill_flow_model.test.js
git commit -m "test: cover UTM equipment task template"
```

Keep overlapping application/UI files unstaged if they contain pre-existing user edits.

### Task 3: Equipment Agent Overlay Execution And Locked Entry Gate

**Files:**
- Modify: `agents/equipment_agent.py`
- Modify: `graphs/modules/equipment/module.yaml`
- Modify: `tests/unit/test_equipment_agent.py`

**Interfaces:**
- Consumes: `evaluate_equipment_entry_gate` and the selected flow's `agentic_task_id`.
- Produces: `equipment_skill_flow_execution.workflow_agentic_task`.
- Produces: additive `equipment_report.workflow_agentic_task`, `required_entry_gate`, and `block_executions`.

- [ ] **Step 1: Write failing locked-gate and compatibility tests**

Add one live test with an overlay-bound flow and mismatched/missing handoff. Assert no `equipment.pyautogui.run` call occurs and the result contains `EQUIPMENT_HANDOFF_NOT_READY`.

Add one test-like overlay execution assertion:

```python
overlay = result.data["equipment_skill_flow_execution"]["workflow_agentic_task"]
assert overlay["schema"] == "atr.equipment_agentic_task.v1"
assert overlay["task_id"] == "run_utm_compression_cycle"
assert overlay["entry_gate"]["locked"] is True
assert overlay["block_order"] == [block["id"] for block in flow["blocks"]]
```

Add a legacy flow test asserting no required entry-gate behavior when `agentic_task_id` is empty.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_equipment_agent.py -k 'agentic_task or locked_entry or skill_flow'`

Expected: overlay fields/failure code are absent and the live tool is called.

- [ ] **Step 3: Wrap the existing flow executor**

At `_run_equipment_skill_flow` entry:

1. resolve `agentic_task_id`;
2. if it is `run_utm_compression_cycle`, build the locked entry gate from `_base_run_payload(state)["source_stage_context"]`;
3. write an execution record before device input;
4. return blocked `AgentResult` with `EQUIPMENT_HANDOFF_NOT_READY` when the gate fails;
5. otherwise execute the existing block loop unchanged.

Enhance the nested `write_execution` helper so every persisted state includes:

```python
"workflow_agentic_task": {
    "schema": "atr.equipment_agentic_task.v1",
    "task_id": agentic_task_id,
    "profile_id": profile_id,
    "flow_id": flow.get("flow_id"),
    "flow_version": flow.get("version"),
    "entry_gate": entry_gate,
    "block_order": [str(block.get("id") or "") for block in blocks],
    "status": status,
},
```

After each Skill/Vision phase, store a bounded block execution record from existing transition data. Disabled Vision must remain `outcome: "bypass"` and must not become a blocker.

Attach the same overlay projection to `equipment_report` and top-level data without removing existing report fields.

Update `graphs/modules/equipment/module.yaml` to document the workflow-level supervisor above the current Profile flow and the locked upstream handoff.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_equipment_agent.py -k 'agentic_task or locked_entry or skill_flow'`

Expected: overlay tests and existing Skill Flow tests pass.

- [ ] **Step 5: Run full Equipment Agent regression**

Run: `.venv/bin/python -m pytest -q tests/unit/test_equipment_agent.py`

Expected: all Equipment Agent tests pass.

### Task 4: Method Values, Screen/Postcondition, CSV, And Next-Specimen Projection

**Files:**
- Modify: `utils/equipment_agentic_task.py`
- Modify: `agents/equipment_agent.py`
- Modify: `tests/unit/test_equipment_agentic_task.py`
- Modify: `tests/unit/test_equipment_agent.py`

**Interfaces:**
- Produces: `project_equipment_cycle_evidence(*, transitions: list[dict[str, Any]], result_data: dict[str, Any]) -> dict[str, Any]`.
- Produces: `method_values`, `screen_transition_evidence`, `raw_data_export`, `next_specimen_readiness`, and `handoff_eligibility`.

- [ ] **Step 1: Write failing projection tests**

```python
def test_cycle_projection_uses_observed_values_and_requires_csv_before_next_test():
    projection = project_equipment_cycle_evidence(
        transitions=[
            {"block_id": "save_raw_data", "outcome": "completed", "evidence": {"result_file": "/tmp/raw.csv"}},
            {"block_id": "validate_raw_data", "outcome": "completed", "evidence": {"data_parse_probe_ok": True, "row_count_probe": 50}},
            {"block_id": "advance_without_save", "outcome": "completed"},
            {"block_id": "restore_robot_clearance", "outcome": "completed", "evidence": {"height": {"observed": 118.4, "target": 118.4}}},
        ],
        result_data={"equipment_result": {"force": 6.2, "stroke": 19.8, "height": 118.4}},
    )
    assert projection["method_values"]["Force"]["observed"] == 6.2
    assert projection["raw_data_export"]["validated"] is True
    assert projection["next_specimen_readiness"]["ready"] is True
    assert "LAN" not in repr(projection)
```

Add a test where `advance_without_save` completes without valid CSV evidence and assert `handoff_eligibility.eligible` is false with `RAW_CSV_VALIDATION_FAILED`.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_equipment_agentic_task.py tests/unit/test_equipment_agent.py -k 'cycle_projection or raw_csv or next_specimen'`

Expected: projection function and additive fields are absent.

- [ ] **Step 3: Implement bounded evidence extraction**

`project_equipment_cycle_evidence` must:

- extract Force, Stroke, and Height only from provided result/report/sensor maps;
- distinguish `observed` from `target` without supplying numeric defaults;
- retain bounded screenshot/frame, locator, icon/button/status, and postcondition references from each transition;
- derive CSV validation from concrete path plus existing parse/row/stability evidence;
- mark Next Test intent as `save_current_test: False`;
- require both validated CSV and completed clearance block for final readiness;
- return stable failure codes rather than prose inference.

In `_run_equipment_skill_flow`, enrich each Skill transition with a bounded evidence snapshot from `last_result.data`, then project the final overlay fields. If the flow reaches `__complete__` but overlay evidence is ineligible, change only the workflow-level terminal/handoff to blocked; do not replay any Skill.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_equipment_agentic_task.py tests/unit/test_equipment_agent.py -k 'cycle_projection or raw_csv or next_specimen or skill_flow'`

Expected: projection and flow tests pass.

- [ ] **Step 5: Run focused regression**

Run: `.venv/bin/python -m pytest -q tests/unit/test_equipment_skill_flow.py tests/unit/test_equipment_skill_runtime.py tests/unit/test_equipment_agent.py`

Expected: selected Equipment tests pass.

### Task 5: Pure Live GUI Projection Model

**Files:**
- Create: `web/static/equipment_agentic_task_model.js`
- Create: `tests/js/equipment_agentic_task_model.test.js`
- Modify: `web/templates/planning.html`

**Interfaces:**
- Produces: global/CommonJS `ATREquipmentAgenticTaskModel`.
- Produces: `cycleContext(ctx)`, `progressSteps(ctx)`, `methodRows(ctx)`, `rawData(ctx)`, and `readiness(ctx)`.

- [ ] **Step 1: Write failing Node tests**

```javascript
const test = require("node:test");
const assert = require("node:assert/strict");
const model = require("../../web/static/equipment_agentic_task_model.js");

test("projects canonical block progress and keeps disabled Vision optional", () => {
  const ctx = model.cycleContext({
    workflow_agentic_task: { task_id: "run_utm_compression_cycle", block_order: ["prepare_next_specimen", "start_test"] },
    block_executions: [
      { block_id: "prepare_next_specimen", status: "completed", vision: { enabled: false, outcome: "bypass" } },
      { block_id: "start_test", status: "active", vision: { enabled: true, outcome: "waiting" } },
    ],
  });
  assert.deepEqual(model.progressSteps(ctx).map((step) => step.status), ["complete", "active"]);
  assert.equal(model.progressSteps(ctx)[0].vision.optional, true);
});

test("uses legacy fallback when overlay is absent", () => {
  assert.equal(model.cycleContext({}).available, false);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test tests/js/equipment_agentic_task_model.test.js`

Expected: module-not-found failure.

- [ ] **Step 3: Implement pure browser/CommonJS model**

Use the repository UMD pattern so Node can import the module and the browser gets `window.ATREquipmentAgenticTaskModel`. The model must never fabricate numeric method values and must expose the exact eight block labels from authoritative data, falling back only to canonical labels by block ID.

Include the model before deferred `planning.js` in `planning.html`:

```html
<script src="/static/equipment_agentic_task_model.js?v=20260901-overlay-1"></script>
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `node --test tests/js/equipment_agentic_task_model.test.js`

Expected: all model tests pass.

- [ ] **Step 5: Commit new model files only**

```bash
git add web/static/equipment_agentic_task_model.js tests/js/equipment_agentic_task_model.test.js
git commit -m "feat: add live equipment cycle projection model"
```

### Task 6: Live GUI Equipment Dashboard Cards

**Files:**
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`
- Modify: `tests/unit/test_lerobot_gui_static.py`

**Interfaces:**
- Consumes: `ATREquipmentAgenticTaskModel` from Task 5 and additive Equipment report fields from Tasks 3-4.
- Produces: cycle header, eight-step rail, method-value card, screen transition card, Raw Data/next-specimen card, and overlay-aware handoff card.

- [ ] **Step 1: Write failing static/integration tests**

Assert the Live GUI template includes `equipment_agentic_task_model.js`, and `planning.js` contains stable render hooks:

```python
assert "renderEquipmentCycleHeader" in planning_js
assert "renderEquipmentMethodValues" in planning_js
assert "renderEquipmentScreenTransitions" in planning_js
assert "renderEquipmentRawDataReadiness" in planning_js
assert "workflow_agentic_task" in planning_js
assert "LAN" not in the_equipment_rendering_slice
```

Add a layout test that the Equipment dashboard retains `TEST`, `OPEN`, `REFRESH`, global runtime controls, and no direct `Start Test` action selector.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/integration/test_live_gui_runtime_layout.py tests/unit/test_lerobot_gui_static.py -k 'equipment or agentic_task'`

Expected: new renderer names/model script are absent.

- [ ] **Step 3: Extend existing Equipment dashboard**

In `equipmentRuntimeContext`, merge overlay fields from `equipment_report`, top-level report, and canonical execution without replacing current legacy fields. When the pure model reports `available: true`, render:

- cycle identity and locked entry gate;
- block rail with Skill version and inline optional Vision state;
- observed versus target Force, Stroke, and Height;
- latest before/after screen, locator, button/icon/status postcondition evidence;
- Raw CSV path/validation and Next Test `save_current_test=false` intent;
- clearance and final handoff eligibility.

When unavailable, retain `equipmentCanonicalProgressSteps` and the existing Bridge/Runtime, Active Program/Skill, Recovery, Evidence, and Handoff behavior.

Add CSS under new `.ar-equipment-cycle-*` classes using the existing responsive dashboard grid. Do not add a separate page or direct device command button.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/integration/test_live_gui_runtime_layout.py tests/unit/test_lerobot_gui_static.py -k 'equipment or agentic_task' && node --test tests/js/equipment_agentic_task_model.test.js`

Expected: selected Python and Node tests pass.

- [ ] **Step 5: Run browser-source syntax checks**

Run: `node --check web/static/equipment_agentic_task_model.js && node --check web/static/planning.js && node --check web/static/equipment_agent_manager.js`

Expected: all files parse with no syntax errors.

### Task 7: Full Verification And Documentation Sync

**Files:**
- Modify: `docs/agents/equipment_agent.md`
- Modify: `docs/runtime/runtime_ide.md`
- Test: all files changed by Tasks 1-6.

**Interfaces:**
- Documents: workflow-level overlay, locked entry condition, eight blocks, method-driven values, optional step Vision, and Live GUI projection.

- [ ] **Step 1: Update durable documentation**

Document the exact hierarchy:

```text
run_utm_compression_cycle
  -> Profile-bound Equipment Skill Flow
    -> block Agentic Task + exact Skill + optional Vision Slot
      -> Equipment Skill Runtime / PyAutoGUI bridge
```

State explicitly that Manipulation Agent is unchanged; the Equipment overlay consumes its verified handoff. Use Force, Stroke, and Height without a transport label and identify all numeric examples as method/cell settings.

- [ ] **Step 2: Run complete focused verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_equipment_agentic_task.py \
  tests/unit/test_equipment_skill_flow.py \
  tests/unit/test_equipment_skill_runtime.py \
  tests/unit/test_equipment_agent.py \
  tests/integration/test_equipment_skill_api.py \
  tests/integration/test_live_gui_runtime_layout.py \
  tests/unit/test_lerobot_gui_static.py
node --test tests/js/equipment_skill_flow_model.test.js tests/js/equipment_agentic_task_model.test.js
node --check web/static/equipment_agentic_task_model.js
node --check web/static/equipment_agent_manager.js
node --check web/static/planning.js
```

Expected: all selected tests and syntax checks pass. Existing Pydantic schema-shadowing warnings may remain; no new warning is accepted.

- [ ] **Step 3: Audit copy and constants**

Run:

```bash
rg -n "LAN|5 ?N|21 ?mm|120 ?mm" \
  utils/equipment_agentic_task.py agents/equipment_agent.py \
  web/static/equipment_agentic_task_model.js web/static/planning.js \
  web/static/equipment_agent_manager.js docs/agents/equipment_agent.md
```

Expected: no executable or UI copy in the new feature contains a transport label or recording-specific fixed values.

- [ ] **Step 4: Inspect the task-only diff**

Run: `git diff --check` and `git status --short`.

Confirm unrelated dirty files remain untouched and identify any overlapping pre-existing files that cannot be safely committed independently.

- [ ] **Step 5: Request code review and report verification evidence**

Use `superpowers:requesting-code-review`, address findings through `superpowers:receiving-code-review`, then use `superpowers:verification-before-completion` before claiming completion.
