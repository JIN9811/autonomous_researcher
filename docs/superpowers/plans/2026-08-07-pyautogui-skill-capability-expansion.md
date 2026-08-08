# PyAutoGUI Skill Capability Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe core PyAutoGUI capability coverage, deterministic examples, recording normalization, and GUI visibility to the existing Equipment Skill pipeline.

**Architecture:** Extend the standalone bridge action contract and recorder, then compile the richer recording events through the Linux-authoritative Skill registry. A local capability lab and Program Manager example catalog exercise the same validated program schema; tests enforce parity between the packaged and install bridge copies.

**Tech Stack:** Python 3.12, PyAutoGUI, pynput, FastAPI, vanilla HTML/CSS/JavaScript, pytest, Selenium/Firefox.

## Global Constraints

- Preserve `atr.pyautogui_program.v1` and the current Skill lifecycle.
- Keep PyAutoGUI fail-safe enabled.
- Do not expose shell execution, arbitrary Python, file deletion, password entry, window close, or process termination.
- Bound all coordinates, repeats, text, scrolling, regions, drag duration, and visual-result counts.
- Release held mouse buttons and keyboard keys after both success and failure.
- Keep `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py` and `install/windows_pyautogui_bridge_server.py` byte-identical.
- Do not commit the implementation; the operator will review it first.

---

### Task 1: Extended Action Contract And Validation

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `tests/unit/test_equipment_pyautogui_bridge.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Modify: `device_bridges/windows_pyautogui_bridge.py`

**Interfaces:**
- Consumes: existing `atr.pyautogui_program.v1` definitions and bridge limits.
- Produces: validation for `move_rel`, click variants, button lifecycle, drag, scroll, key lifecycle, visual query/assertion, window control, and manual dialogs.

- [ ] Write failing tests that register valid bounded actions and reject invalid coordinates, counts, scroll values, regions, and manual dialogs in unattended tests.
- [ ] Run the focused validation tests and confirm failures are caused by missing actions.
- [ ] Add action names, per-action normalization, limits, and stable failure codes to both bridge layers.
- [ ] Run the focused tests and copy the packaged server to the install server.

### Task 2: Safe Executor Coverage

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Consumes: validated action dictionaries from Task 1.
- Produces: `_execute_protocol_sequence()` support with trace evidence and guaranteed held-input cleanup.

- [ ] Extend `_FakePyAutoGUI` and write failing tests for every action family, including cleanup after an injected exception.
- [ ] Run the executor tests and confirm the expected missing branch failures.
- [ ] Implement mouse, keyboard, screen/pixel, window, and manual-dialog branches with bounded values and execution traces.
- [ ] Add one cleanup context that releases tracked keys/buttons in `finally`.
- [ ] Run focused executor and existing UTM sequence tests.

### Task 3: Recorder And Skill Compiler Normalization

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `tests/unit/test_equipment_skill_runtime.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Modify: `utils/equipment_skill_runtime.py`

**Interfaces:**
- Consumes: pynput mouse/key callbacks and `atr.equipment_recording.v1` events.
- Produces: `mouse_drag`, `mouse_scroll`, compact `write`, `drag_to`, scroll actions, and workflow capability coverage.

- [ ] Write failing recorder tests for click-versus-drag classification, scroll capture, and suppression of intermediate drag moves.
- [ ] Write failing compiler tests for printable-key compaction, drag/scroll compilation, and unsupported-event rejection.
- [ ] Implement `_RecordingMouseCapture` and extend `RecordingManager.record_event()`.
- [ ] Implement deterministic recording normalization and capability coverage generation.
- [ ] Run recorder, compiler, segmentation, and Skill lifecycle tests.

### Task 4: Capability Lab And Example Catalog

**Files:**
- Create: `Pyautogui_server_for_window/demo/pyautogui_capability_lab.html`
- Create: `Pyautogui_server_for_window/demo/examples/pointer_click.json`
- Create: `Pyautogui_server_for_window/demo/examples/drag_scroll.json`
- Create: `Pyautogui_server_for_window/demo/examples/keyboard_shortcuts.json`
- Create: `Pyautogui_server_for_window/demo/examples/visual_assertions.json`
- Create: `Pyautogui_server_for_window/demo/examples/window_control.json`
- Create: `Pyautogui_server_for_window/demo/examples/manual_dialogs.json`
- Create: `Pyautogui_server_for_window/demo/examples/image_location.json`
- Create: `Pyautogui_server_for_window/demo/examples/file_wait.json`
- Modify: `tests/unit/test_windows_pyautogui_demo_assets.py`
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Consumes: the validated action contract.
- Produces: `GET /capabilities`, `GET /examples`, deterministic local targets, and exact example program JSON.

- [x] Write failing asset and endpoint tests for eight examples, safe/manual flags, required controls, schema validity, and full safe-core action coverage.
- [x] Run the tests and confirm missing assets/endpoints.
- [x] Implement the capability lab, example files, catalog loader, and read-only endpoints.
- [x] Run Selenium against the local lab and validate every JSON example through `/programs/validate`.

### Task 5: Program Manager Examples And Recording Coverage UI

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Consumes: `/capabilities`, `/examples`, recording details, and Skill summaries.
- Produces: `EXAMPLES` tab, load-only example editor, safe test action, and recording/Skill coverage badges.

- [ ] Write failing HTML contract tests for the tab, buttons, coverage summary, and no implicit registration.
- [ ] Run the HTML tests and confirm missing elements.
- [ ] Add compact responsive cards and JavaScript loading/testing handlers.
- [ ] Verify the bridge console through the ATR proxy at 1920x1080 and inspect screenshots.

### Task 6: Documentation And End-To-End Verification

**Files:**
- Modify: `REQUIREMENTS.md`
- Modify: `docs/hardware/windows_pyautogui_bridge_windows_setup.md`
- Modify: `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`
- Modify: `docs/tutorials/user_manual.ko.md`

**Interfaces:**
- Consumes: final action catalog, GUI routes, examples, and runtime evidence.
- Produces: installation, authoring, safety, and troubleshooting instructions.

- [ ] Document all supported and excluded capabilities with example usage.
- [ ] Start/reuse the local bridge and validate health through the ATR GUI proxy.
- [ ] Run every safe example and capture postcondition screenshots.
- [ ] Record one drag/scroll workflow, create an exact Skill, deploy it, and replay it twice.
- [ ] Run all Equipment Skill, bridge, agent, Guardian, and GUI regression tests.
- [ ] Run `git diff --check`, server-copy parity, and inspect the final browser layout.
