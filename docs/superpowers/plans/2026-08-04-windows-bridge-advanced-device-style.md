# Windows Bridge Full Device Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the complete standalone Windows bridge with ATR Device Bridge visual rules and eliminate clipped operational text.

**Architecture:** Keep the single-file Windows server and its embedded HTML/CSS architecture. Apply a root Device Bridge shell theme to the header, Essential Console, Program Manager, and Advanced Tools while preserving the existing DOM and JavaScript, then extend the Selenium audit to validate the full shell and opened Advanced layout.

**Tech Stack:** Python embedded HTML, CSS Grid/Flexbox, Selenium Firefox audit, pytest

## Global Constraints

- Do not change DOM IDs, request payloads, API routes, or execution behavior.
- Keep the Windows GUI independently deployable without Linux-hosted CSS.
- Keep `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py` and `install/windows_pyautogui_bridge_server.py` byte-identical.
- Preserve unrelated dirty-worktree changes.

---

### Task 1: Advanced overflow regression audit

**Files:**
- Modify: `tests/ui/windows_bridge_gui_browser_audit.py`

**Interfaces:**
- Consumes: existing Selenium driver and Windows bridge page.
- Produces: Advanced-open layout metrics and screenshots at desktop and compact desktop sizes.

- [ ] **Step 1: Add a failing Advanced overflow assertion**

Open `#advancedToolsPanel`, collect visible buttons and operational text whose `scrollWidth` exceeds `clientWidth`, and assert that the result is empty.

- [ ] **Step 2: Run the audit and verify the current CSS fails**

Run the Windows bridge server and execute `python tests/ui/windows_bridge_gui_browser_audit.py --base-url http://127.0.0.1:<port> --out-dir <dir>`.

- [ ] **Step 3: Preserve failure evidence**

Save the Advanced-open screenshot and overflow element list in the audit result.

### Task 2: Advanced Device Bridge styling

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Consumes: current Advanced DOM and Device Bridge visual tokens.
- Produces: self-contained, responsive Advanced workspace CSS with non-clipping operational text.

- [ ] **Step 1: Add Advanced-scoped visual tokens and surface styles**

Apply pale blue-gray workspace background, white cards, blue headings/actions, compact borders, and consistent shadows under `#advancedToolsPanel`.

- [ ] **Step 2: Replace clipping layouts with responsive grids**

Use `minmax(0, 1fr)`, adaptive action grids, wrapping buttons, and safe long-value handling.

- [ ] **Step 3: Remove Advanced operational ellipsis**

Allow guidance, status, next-action, and control labels to wrap while retaining contained scrolling for code/JSON/path values.

- [ ] **Step 4: Synchronize the packaged server copy**

Copy the primary server file to `install/windows_pyautogui_bridge_server.py` and verify byte equality.

### Task 3: Verification and visual QA

**Files:**
- Verify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Verify: `tests/ui/windows_bridge_gui_browser_audit.py`

**Interfaces:**
- Consumes: final embedded HTML/CSS and browser audit.
- Produces: passing automated checks and inspected screenshots.

- [ ] **Step 1: Run syntax and helper tests**

Run `python -m py_compile` for both server copies and the focused pytest suite.

- [ ] **Step 2: Run browser audit at 1920x1080**

Open Advanced Tools, verify no clipped operational text, and save a screenshot.

- [ ] **Step 3: Run browser audit at 1366x768**

Verify responsive grids, readable buttons, and no page-level horizontal overflow.

- [ ] **Step 4: Inspect screenshots**

Confirm Device Bridge visual consistency, card alignment, readable labels, and contained path/JSON fields.

- [ ] **Step 5: Run the full Windows bridge helper suite**

Run the complete helper test module and package smoke test without modifying runtime behavior.
