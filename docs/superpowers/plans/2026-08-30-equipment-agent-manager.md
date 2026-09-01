# Lab Equipment Agent Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Move Profile-bound Lab Equipment Skill composition into one Agent Manager while Equipment Bridge, Live GUI, and Runtime IDE consume the same read-only execution projection.

**Architecture:** The canonical store persists an ordered `blocks` contract. Each block owns an exact Skill, its agentic routing metadata, and an optional embedded Vision gate; the Equipment Agent executes those phases sequentially and writes one shared runtime projection. A dedicated Agent Manager is the only authoring surface, while Equipment Bridge, Live GUI, and Runtime IDE link to it and render the same state.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, vanilla JavaScript, CSS, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-08-30-equipment-skill-flow-design.md`

## Global Constraints

- Preserve the existing single-Skill/Profile execution path when a Profile flow is empty.
- Do not add a standalone Vision block or a separate `+ Vision` action.
- Equipment Bridge, Live GUI, and Runtime IDE must not persist flow edits.
- Persist empty authoring blocks independently from Skill availability; enforce exact deployed Skill versions only after a Skill Slot is bound.
- Keep the existing device command path and Equipment Skill execution implementation unchanged outside flow orchestration.
- Do not restart or stop vLLM, device services, or physical equipment processes during UI verification.
- Do not commit these changes until the operator reviews them.

---

### Task 1: Composite Flow Contract and Migration

**Files:**
- Modify: `utils/equipment_skill_flow.py`
- Modify: `tests/unit/test_equipment_skill_flow.py`
- Modify: `tests/js/equipment_skill_flow_model.test.js`
- Modify: `web/static/equipment_skill_flow_model.js`

**Interfaces:**
- Produces: `normalize_equipment_skill_flow(profile_id, payload) -> dict` with ordered `blocks`.
- Produces: `EquipmentSkillFlowStore.as_runtime_graph(profile_id) -> dict` with supervisor, per-block Skill/Vision phase nodes, and terminal nodes.
- Produces: browser model functions `empty`, `addBlock`, `removeBlock`, `moveBlock`, and `updateBlock`.

- [x] **Step 1: Write failing Python tests for block normalization and legacy migration**

Add assertions that a composite block round-trips, a legacy Skill followed by Vision migrates into one block, and standalone Vision is rejected.

- [x] **Step 2: Run the focused Python tests and confirm RED**

Run: `pytest -q tests/unit/test_equipment_skill_flow.py`

Expected: failures because the store still returns `nodes` and permits standalone Vision nodes.

- [x] **Step 3: Write failing JavaScript model tests**

Assert that `addBlock()` creates one object containing `skill`, `agentic`, and `vision`, and that no `addVisionGate` export exists.

- [x] **Step 4: Run the Node tests and confirm RED**

Run: `node --test tests/js/equipment_skill_flow_model.test.js`

Expected: failures because `addBlock` is not defined.

- [x] **Step 5: Implement the composite contract and migration**

Normalize `blocks`, derive sequential routes, migrate only legacy Skill-plus-following-Vision pairs, reject standalone Vision, and project Skill/Vision phase nodes for Runtime IDE.

- [x] **Step 6: Run focused Python and Node tests**

Run: `pytest -q tests/unit/test_equipment_skill_flow.py && node --test tests/js/equipment_skill_flow_model.test.js`

Expected: all tests pass.

### Task 2: Sequential Equipment Agent Execution

**Files:**
- Modify: `agents/equipment_agent.py`
- Modify: `tests/unit/test_equipment_agent.py`

**Interfaces:**
- Consumes: normalized `flow["blocks"]` from Task 1.
- Produces: `atr.equipment_skill_flow_execution.v1` with `active_block`, `active_phase`, and phase transitions containing `block_id`.

- [x] **Step 1: Write failing execution tests**

Cover Skill-only completion, Skill-plus-Vision completion, Vision failure blocking, and empty-flow legacy fallback.

- [x] **Step 2: Run focused tests and confirm RED**

Run: `pytest -q tests/unit/test_equipment_agent.py -k 'skill_flow or legacy'`

Expected: failures because the agent still traverses flattened nodes.

- [x] **Step 3: Implement block execution**

Execute each exact Skill, record its phase transition, conditionally invoke the deterministic Vision cross-check, record its transition, and stop immediately on blocked outcomes.

- [x] **Step 4: Run focused tests**

Run: `pytest -q tests/unit/test_equipment_agent.py -k 'skill_flow or legacy'`

Expected: all selected tests pass.

### Task 3: Canonical API and Agent Manager Page

**Files:**
- Create: `web/templates/equipment_agent_manager.html`
- Create: `web/static/equipment_agent_manager.js`
- Create: `web/static/equipment_agent_manager.css`
- Modify: `app/main.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: `/api/equipment/profiles/{profile_id}/skill-flow` GET/PUT.
- Produces: `/equipment/agent-manager?profile_id=<id>`.
- Produces: one DOM composite per block with `.equipment-manager-skill-slot`, `.equipment-manager-agentic-slot`, and `.equipment-manager-vision-slot`.

- [x] **Step 1: Write failing route and DOM tests**

Assert the Agent Manager route exists, exposes one `+ Block` action, contains no standalone Vision action, and references the canonical API.

- [x] **Step 2: Run the focused integration tests and confirm RED**

Run: `pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment_skill_flow or agent_manager'`

Expected: failures because the page and route do not exist.

- [x] **Step 3: Add the Agent Manager route and page**

Render Profile selection, an always-available empty block action, exact deployed Skill options inside Skill Slot, an independent Agentic Task name, bounded agentic outcomes, embedded Vision enable/condition, block reorder/delete, atomic save, dirty-state polling guard, and unsaved-close confirmation.

- [x] **Step 4: Enforce exact-version readiness in the API payload**

Return per-block readiness. Save fully unbound Skill Slots as drafts, reject partial bindings, and reject a bound exact Skill that is not deployed, enabled, and assigned to the selected Profile.

- [x] **Step 5: Run focused integration and model tests**

Run: `pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment_skill_flow or agent_manager' && node --test tests/js/equipment_skill_flow_model.test.js`

Expected: all selected tests pass.

### Task 4: Read-Only Runtime Surfaces

**Files:**
- Modify: `web/templates/windows_equipment.html`
- Modify: `web/static/windows_equipment.js`
- Modify: `web/static/styles.css`
- Modify: `web/templates/runtime_ide.html`
- Modify: `web/static/runtime_ide.js`
- Modify: `web/static/runtime_ide.css`
- Modify: `web/static/planning.js`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: canonical flow/API execution projection from Tasks 1-3.
- Produces: `Open Agent Manager` actions from Equipment Bridge and Runtime IDE.
- Produces: read-only Agentic Progress cards in Equipment Bridge and Live GUI.

- [x] **Step 1: Write failing surface ownership tests**

Assert Equipment Bridge and Runtime IDE contain no flow mutation controls, both contain Agent Manager links, and Live GUI consumes the canonical flow endpoint for Lab Equipment progress.

- [x] **Step 2: Run focused integration tests and confirm RED**

Run: `pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment_skill_flow or equipment_dashboard'`

Expected: failures because both legacy editors remain and Live GUI does not yet load the canonical execution projection.

- [x] **Step 3: Replace Equipment Bridge editor with runtime projection**

Keep the progress card, remove Skill/Vision inputs, add the Agent Manager link, and render block/phase state from the shared payload.

- [x] **Step 4: Replace Runtime IDE editor with a manager launcher**

Keep graph refresh and runtime status, remove inline mutation handlers, and open the same Profile-bound Agent Manager.

- [x] **Step 5: Connect Live GUI Agentic Progress to canonical execution state**

Fetch the selected/default Profile flow through the existing bounded refresh path, merge its execution projection into `equipmentProgressSteps`, and preserve the existing report fallback when no configured flow exists.

- [x] **Step 6: Run focused integration and static tests**

Run: `pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment_skill_flow or equipment_dashboard' tests/unit/test_utm_runtime_frontend_static.py`

Expected: all selected tests pass.

### Task 5: Browser Verification and Documentation

**Files:**
- Create: `tests/ui/equipment_agent_manager_browser_audit.py`
- Modify: `tests/ui/windows_equipment_browser_audit.py`
- Modify: `docs/agents/equipment_agent.md`
- Modify: `docs/runtime/runtime_ide.md`
- Modify: `docs/strategy/2026-08-27-windows-lab-equipment-consolidation-report.md`

**Interfaces:**
- Consumes: completed Agent Manager and read-only projections.
- Produces: browser evidence that one saved block reopens and projects identically in Equipment Bridge and Runtime IDE.

- [x] **Step 1: Add a browser audit**

Use the running GUI to add one block, select an exact Skill, enable Vision, save, reopen, verify Equipment Bridge progress and Runtime IDE graph projection, then restore the flow store to its original bytes.

- [x] **Step 2: Run browser verification**

Run: `python tests/ui/equipment_agent_manager_browser_audit.py`

Expected: PASS and no persistent test data remains.

- [x] **Step 3: Update operator and architecture documentation**

Document the Agent Manager as the sole authoring surface, explain the composite block, and identify Equipment Bridge, Live GUI, and Runtime IDE as read-only projections.

- [x] **Step 4: Run the full affected verification set**

Run: `pytest -q tests/unit/test_equipment_skill_flow.py tests/unit/test_equipment_agent.py tests/integration/test_live_gui_runtime_layout.py tests/unit/test_utm_runtime_frontend_static.py`

Run: `node --test tests/js/equipment_skill_flow_model.test.js`

Run: `python -m py_compile utils/equipment_skill_flow.py agents/equipment_agent.py app/main.py`

Expected: all tests and compilation checks pass.


## Verification Record (2026-08-31)

- Composite flow, Equipment Agent execution, Agent Manager API/DOM, and read-only projection tests passed.
- Firefox audit passed for save, reopen, Equipment Bridge projection, Runtime IDE projection, and byte-for-byte flow-store restoration.
- Affected suite result: 142 passed, with one unrelated pre-existing failure in `tests/unit/test_utm_runtime_frontend_static.py` caused by its stale `planning.html` CSS cache-version expectation.
- Documentation changes in `docs/agents/equipment_agent.md` pass the repository validator requirements. The global validator still reports pre-existing structure gaps in `docs/device_bridges/windows_pyautogui_bridge.md` and missing YAML front matter in `docs/superpowers/specs/2026-08-24-plc-safety-bridge-design.md`.
- No physical equipment command was issued by browser verification.
