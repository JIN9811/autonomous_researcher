# Lab Equipment Live GUI Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Lab Equipment Live GUI report's report-heavy card set with a compact operational view of bridge readiness, exact program/skill execution, bounded recovery, evidence, progress, and handoff.

**Architecture:** Keep run events and existing Equipment report payloads as the source of truth. Add one Equipment-only frontend cache that passively reads the existing Windows config endpoint and expose three non-actuating header actions; compose all output through the existing Live GUI card, metric, row, details, and progress styles.

**Tech Stack:** Vanilla JavaScript, existing FastAPI routes, existing Live GUI CSS, pytest static/integration tests.

## Global Constraints

- Modify only the Lab Equipment Live GUI report and its passive frontend status wiring.
- Do not change Equipment Agent execution, bridge execution/recording/recovery, Guardian rules, `/equipment/windows`, or another agent report.
- Do not create a new backend route.
- Do not render bridge tokens or secrets.
- `TEST` may call health/program discovery but must never call `/execute`.
- Use existing card styles; do not introduce a new visual theme or global style override.
- Preserve the latest successful supplemental snapshot when refresh fails.
- Do not commit during implementation; the user will inspect the result first.

---

## File Map

- Modify `web/static/planning.js`: Equipment-only passive state, actions, card derivation, and card composition.
- Modify `tests/integration/test_live_gui_runtime_layout.py`: static frontend contract and existing-route safety assertions.
- Modify `tests/ui/equipment_report_browser_audit.py`: 1920x1080 operational-card browser audit.
- Do not modify `app/main.py`, `agents/equipment_agent.py`, `device_bridges/windows_pyautogui_bridge.py`, `policies/guardian_gate.py`, or `web/static/styles.css` unless a failing browser audit proves an existing style cannot express the approved layout.

### Task 1: Lock the Equipment-only scope with failing tests

**Files:**
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: `/static/planning.js` returned by the existing test client.
- Produces: regression assertions for the approved six-card layout and three actions.

- [x] **Step 1: Add a failing Live GUI card contract test**

Add a test that requests `/static/planning.js` and asserts all approved card calls and spans are present:

```python
def test_live_gui_equipment_dashboard_uses_operational_card_layout() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text
    assert 'renderDashboardCard("Bridge / Runtime"' in script
    assert 'renderDashboardCard("Active Program / Skill"' in script
    assert 'renderDashboardCard("Recovery Boundary"' in script
    assert 'renderDashboardCard("Agentic Progress"' in script
    assert 'renderDashboardCard("Execution Evidence"' in script
    assert 'renderDashboardCard("Handoff"' in script
    assert '"Bridge / Runtime", renderEquipmentBridgeRuntime' in script
    assert '"Agentic Progress", renderEquipmentAgenticProgress' in script
    assert '{ span: 12, tone:' in script
```

- [x] **Step 2: Add a failing action and safety contract test**

Assert the frontend exposes only the approved action endpoints:

```python
def test_live_gui_equipment_actions_are_passive_and_reuse_existing_routes() -> None:
    client = TestClient(app)
    script = client.get("/static/planning.js").text
    assert 'data-equipment-live-action="test"' in script
    assert 'data-equipment-live-action="open"' in script
    assert 'data-equipment-live-action="refresh"' in script
    assert '"/api/equipment/windows/config"' in script
    assert '"/api/equipment/windows/test"' in script
    assert 'window.open("/equipment/windows", "_blank"' in script
    equipment_action_block = script.split("async function runEquipmentLiveAction", 1)[1].split("\n}\n", 1)[0]
    assert "/execute" not in equipment_action_block
```

- [x] **Step 3: Run the focused tests and verify they fail**

Run:

```bash
pytest -q \
  tests/integration/test_live_gui_runtime_layout.py::test_live_gui_equipment_dashboard_uses_operational_card_layout \
  tests/integration/test_live_gui_runtime_layout.py::test_live_gui_equipment_actions_are_passive_and_reuse_existing_routes
```

Expected: both tests fail because the new render helpers and action attributes do not exist.

### Task 2: Add passive Equipment runtime state and actions

**Files:**
- Modify: `web/static/planning.js`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: `fetchJsonOrThrow`, `liveLastSession`, `liveSelectedAgent`, `renderLiveRuntime`, `setChatStatus`.
- Produces:
  - `liveEquipmentRuntimeSnapshot: object | null`
  - `liveEquipmentRuntimeError: string`
  - `liveEquipmentRuntimeActionInFlight: string`
  - `refreshEquipmentRuntimeSnapshot(options?: {render?: boolean, test?: boolean, force?: boolean}): Promise<object | null>`
  - `runEquipmentLiveAction(action: string, button?: HTMLElement | null): Promise<object | null>`
  - `renderEquipmentLiveHeaderActions(): string`

- [x] **Step 1: Add Equipment-only frontend state beside the existing UTM runtime state**

Add:

```javascript
let liveEquipmentRuntimeSnapshot = null;
let liveEquipmentRuntimeError = "";
let liveEquipmentRuntimeActionInFlight = "";
let liveEquipmentRuntimeRefreshInFlight = null;
let liveEquipmentRuntimeRefreshedAt = 0;
```

Do not add a timer or global polling loop.

- [x] **Step 2: Implement a passive snapshot refresh**

Implement `refreshEquipmentRuntimeSnapshot` so normal refresh reads `GET /api/equipment/windows/config`, test mode first calls `POST /api/equipment/windows/test`, and a failed request leaves the prior snapshot intact:

```javascript
async function refreshEquipmentRuntimeSnapshot(options = {}) {
  if (!options.force && liveEquipmentRuntimeRefreshInFlight) return liveEquipmentRuntimeRefreshInFlight;
  liveEquipmentRuntimeRefreshInFlight = (async () => {
    try {
      if (options.test) {
        await fetchJsonOrThrow("/api/equipment/windows/test", { method: "POST" });
      }
      const payload = await fetchJsonOrThrow("/api/equipment/windows/config");
      liveEquipmentRuntimeSnapshot = payload;
      liveEquipmentRuntimeError = "";
      liveEquipmentRuntimeRefreshedAt = Date.now();
      return payload;
    } catch (err) {
      liveEquipmentRuntimeError = String(err);
      return liveEquipmentRuntimeSnapshot;
    } finally {
      liveEquipmentRuntimeRefreshInFlight = null;
      if (options.render && liveLastSession) renderLiveRuntime(liveLastSession);
    }
  })();
  return liveEquipmentRuntimeRefreshInFlight;
}
```

- [x] **Step 3: Implement the three header actions**

`runEquipmentLiveAction` must:

- `open`: call `window.open("/equipment/windows", "_blank", "noopener,noreferrer")` and perform no fetch.
- `refresh`: call `refreshEquipmentRuntimeSnapshot({render: true, force: true})`.
- `test`: call `refreshEquipmentRuntimeSnapshot({render: true, test: true, force: true})`.
- Disable only the pressed action while it runs.
- Report status via `setChatStatus` without creating agent completion/handoff events.

- [x] **Step 4: Add delegated click and keyboard handlers**

Use the current report-panel delegation pattern:

```javascript
const equipmentAction = event.target.closest("[data-equipment-live-action]");
if (equipmentAction && liveReportPanel && liveReportPanel.contains(equipmentAction)) {
  event.preventDefault();
  event.stopPropagation();
  runEquipmentLiveAction(equipmentAction.dataset.equipmentLiveAction || "", equipmentAction).catch(() => {});
  return;
}
```

Add the equivalent Enter/Space keyboard branch next to `data-vision-runtime-action`.

- [x] **Step 5: Load the passive snapshot only when Equipment is selected**

In the Agent Binder selection handler, after assigning `liveSelectedAgent`, call:

```javascript
if (liveSelectedAgent === "equipment" && !liveEquipmentRuntimeSnapshot && !liveEquipmentRuntimeRefreshInFlight) {
  refreshEquipmentRuntimeSnapshot({ render: true }).catch(() => {});
}
```

Do not poll and do not fetch while another agent is selected.

- [x] **Step 6: Run the focused action test**

Run:

```bash
pytest -q tests/integration/test_live_gui_runtime_layout.py::test_live_gui_equipment_actions_are_passive_and_reuse_existing_routes
```

Expected: PASS.

### Task 3: Recompose the Equipment report with existing renderers

**Files:**
- Modify: `web/static/planning.js`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: current `latestEquipment*` extractors, `renderDashboardCard`, `renderDashboardRows`, `renderDashboardMetric`, `renderVisionCardDetails`, `renderEquipmentGatePanel`, `renderEquipmentEventLog`.
- Produces:
  - `equipmentRuntimeView(equipment, result): object`
  - `equipmentProgressSteps(equipment, result, skillExecution, handoff): Array<{id,label,status,detail}>`
  - `renderEquipmentBridgeRuntime(...): string`
  - `renderEquipmentActiveExecution(...): string`
  - `renderEquipmentRecoveryBoundary(...): string`
  - `renderEquipmentAgenticProgress(...): string`
  - `renderEquipmentExecutionEvidence(...): string`
  - updated `renderEquipmentDashboardCards(...): string`

- [x] **Step 1: Add a normalized passive/runtime view helper**

Merge only display fields, with run-report fields taking precedence over the supplemental snapshot. Return normalized fields for connection status, target alias, desktop size, dependency counts, versions, refresh age, and stale error. Never copy token-like keys into the returned view.

- [x] **Step 2: Derive five progress nodes from recorded evidence**

Use these rules:

```javascript
const hasProfile = Boolean(controlPlan.program_id || skillExecution.skill_id);
const bridgeReady = /connected|ready|ok/i.test(String(bridge.connection_status || runtime.connectionStatus));
const executionComplete = /completed|verified_complete|ok|success/i.test(String(skillExecution.state || result.status));
const executionActive = Boolean(skillExecution.current_segment) || /running|active|executing/i.test(String(skillExecution.state || result.status));
const evidenceVerified = screenChecks.length > 0
  && screenChecks.every((item) => item && item.ok)
  && (cross.data_parse_probe_ok === true || data.status === "ready");
const handoffReady = /ready_for_analysis|ready/i.test(String(decision.handoff_status || handoff.status));
```

Later nodes must not be marked complete if their own evidence is absent. A failure code marks the current recorded node blocked; missing values remain waiting.

- [x] **Step 3: Render Bridge / Runtime and its actions**

Use existing `ar-report-metrics`, `renderDashboardMetric`, and `renderVisionCardDetails`. Show bridge, desktop, core dependency count, selected target, versions, optional dependencies, refresh time, and stale error. Pass `action: renderEquipmentLiveHeaderActions()` to `renderDashboardCard`.

- [x] **Step 4: Render Active Program / Skill and Recovery Boundary**

Use `renderDashboardRows` for exact IDs and versions. Render model provider/model only when present in `model_snapshot`. Keep recovery history in an existing expandable details block.

- [x] **Step 5: Render full-width Agentic Progress**

Reuse the existing Vision progress markup/classes `ar-vis-agentic-progress`, `ar-vis-agentic-step`, `is-complete`, `is-active`, and `is-blocked`. Put Gate Matrix and recent Equipment events inside `renderVisionCardDetails("Runtime details", ...)`.

- [x] **Step 6: Render Execution Evidence and Handoff**

Execution Evidence uses four existing dashboard metrics for screen checks, rows, parse state, and last event. Its expandable details contain paths, checksum, screenshot refs, request-audit refs, and the existing sensor table. Handoff uses existing rows for status, failure, next agent, schema, and Guardian requirement.

- [x] **Step 7: Replace only `renderEquipmentDashboardCards` composition**

The resulting card spans must be:

```javascript
Bridge / Runtime        span 4
Active Program / Skill span 4
Recovery Boundary      span 4
Agentic Progress       span 12
Execution Evidence     span 8
Handoff                span 4
```

Remove the old top-level Equipment Readiness, Live Test Status, Control Profile, Gate Matrix, Sensor Channels, UTM Data Ledger, and Analysis Handoff cards only after their non-duplicate data is preserved in the new cards or details.

- [x] **Step 8: Run the focused layout and existing Equipment report tests**

Run:

```bash
pytest -q \
  tests/integration/test_live_gui_runtime_layout.py::test_live_gui_equipment_dashboard_uses_operational_card_layout \
  tests/integration/test_live_gui_runtime_layout.py::test_live_gui_equipment_report_recovers_incident_from_hardware_alert \
  tests/integration/test_live_gui_runtime_layout.py::test_live_gui_equipment_report_exposes_utm_visual_control_contract
```

Expected: PASS.

### Task 4: Verify visual parity and regression boundaries

**Files:**
- Modify only if verification finds a scoped defect: `web/static/planning.js`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: running FastAPI Live GUI and existing browser audit tooling.
- Produces: verified 1920x1080 Equipment report with no changes to other agent reports.

- [x] **Step 1: Run the full Live GUI layout test file**

Run:

```bash
pytest -q tests/integration/test_live_gui_runtime_layout.py
```

Expected: PASS.

- [x] **Step 2: Run focused Equipment and bridge regressions**

Run:

```bash
pytest -q \
  tests/unit/test_equipment_agent.py \
  tests/unit/test_equipment_pyautogui_bridge.py \
  tests/integration/test_equipment_skill_api.py
```

Expected: PASS without modifying their implementation files.

- [x] **Step 3: Perform browser verification at 1920x1080**

Start the existing server without altering its runtime configuration, open `/live`, select the Equipment report, and verify:

- all six cards fit the existing report grid;
- three top cards align with Vision's top row;
- Agentic Progress uses the full width and existing node style;
- details expand without closing on report scroll;
- `OPEN` reaches `/equipment/windows` in a new tab;
- `REFRESH` preserves the report if the bridge is offline;
- `TEST` reports health failure locally and does not run a program;
- switching to Vision, Specimen, and Manipulation shows no visual change.

- [x] **Step 4: Inspect the final diff boundary**

Run:

```bash
git diff -- web/static/planning.js tests/integration/test_live_gui_runtime_layout.py docs/superpowers/specs/2026-08-08-lab-equipment-live-gui-operations-design.md docs/superpowers/plans/2026-08-08-lab-equipment-live-gui-operations.md
git status --short
```

Expected: implementation changes are limited to the planned frontend/test files plus the approved spec and plan. Do not commit.
