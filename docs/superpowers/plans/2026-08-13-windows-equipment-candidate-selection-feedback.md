# Windows Equipment Candidate Selection Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Windows Equipment saved-candidate selection visibly and accessibly reliable while preserving the existing non-actuating backend selection contract.

**Architecture:** Keep `POST /api/equipment/windows/select` and connection memory authoritative. Add deterministic browser rendering and error handling around the existing API, then refetch `/api/equipment/windows/config` without introducing any live bridge or physical call.

**Tech Stack:** Vanilla JavaScript, DOM/CSS, Node VM frontend tests, pytest, Selenium/Firefox.

## Global Constraints

- Preserve all existing API schemas, token handling, candidate memory, and execution gates.
- Selection MUST NOT automatically call `/health`, `/programs`, `/execute`, or physical-equipment endpoints.
- Do not modify unrelated user changes.

---

### Task 1: Protect Candidate Selection Behavior

**Files:**
- Create: `tests/js/windows_equipment_selection.test.js`
- Modify: `web/static/windows_equipment.js`
- Modify: `web/templates/windows_equipment.html`

**Interfaces:**
- Consumes: `POST /api/equipment/windows/select`, `GET /api/equipment/windows/config`, `setConnectionStatus(connection)`, and `renderSavedCandidates(candidates)`.
- Produces: confirmed selected-card state, in-flight state, application-failure handling, and derived profile connection status.

- [ ] **Step 1: Write a failing browser-script test**

Execute the real `windows_equipment.js` in a controlled DOM/fetch harness and
assert that selecting `windows_192.168.50.40_Nextpc` disables the in-flight
button, confirms the exact returned alias, refetches config, renders one
selected card with accessible state, and never calls live bridge endpoints.
Add a failure case for `ok=false` and a display case for selected profile state
without `connection.status`.

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
node --test tests/js/windows_equipment_selection.test.js
```

Expected: failure because selected cards and application-level errors are not
yet represented.

- [ ] **Step 3: Implement the minimal UI fix**

Update saved-card rendering, selection request handling, config refresh, and
profile status fallback. Add only scoped selected/busy styles to the Windows
Equipment template or existing scoped stylesheet area.

- [ ] **Step 4: Run focused and existing tests**

```bash
node --test tests/js/windows_equipment_selection.test.js
node --check web/static/windows_equipment.js
.venv/bin/pytest -q tests/unit/test_equipment_pyautogui_bridge.py -k 'save_connection or candidate or live_health'
```

- [ ] **Step 5: Run browser and live non-actuating verification**

Run `tests/ui/windows_equipment_browser_audit.py`, then select
`windows_192.168.50.40_Nextpc` in the browser and confirm the selected-card DOM.
Call only the existing non-actuating `/api/equipment/windows/test` health and
program-registry check; do not execute a program.
