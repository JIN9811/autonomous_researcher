# Windows Recording Topmost Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a five-second recording countdown, one start/stop toggle, and a Windows Tkinter always-on-top recording timer without changing recorded Skill data.

**Architecture:** The browser owns countdown and toggle presentation, while the existing recording HTTP endpoints remain authoritative. A thread-confined Tkinter controller is injected into `RecordingManager`, which owns native overlay lifecycle together with listener lifecycle.

**Tech Stack:** Python 3 standard library (`tkinter`, `threading`, `queue`), embedded HTML/CSS/JavaScript, pytest, Selenium.

## Global Constraints

- Preserve `atr.equipment_recording.v1/v2`, image locator, checkpoint, and Skill draft payloads.
- Do not add a runtime dependency outside the Python standard library.
- Tkinter failure must not block recording.
- Keep source and install bridge scripts byte-identical.
- Do not commit or push until the user inspects the result.

---

### Task 1: Overlay Lifecycle Contract

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Produces: `RecordingOverlayController.show(recording_id: str, started_monotonic: float)`, `hide()`, `shutdown()`, and `status()`.
- Consumes: an injectable Tk root factory and monotonic clock for deterministic tests.

- [ ] **Step 1: Write failing controller tests**

Test that `show()` creates one topmost borderless banner, elapsed time updates, `hide()` destroys it, repeated `show()` is idempotent, and `shutdown()` terminates the controller.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'recording_overlay'`

Expected: failure because `RecordingOverlayController` does not exist.

- [ ] **Step 3: Implement the minimal controller**

Use a daemon thread and command queue so all Tk calls happen on one thread. Lazily import Tkinter inside the thread, render the red dot, label, and elapsed timer, and report unavailable rather than raising when no display exists.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'recording_overlay'`

Expected: all selected tests pass.

### Task 2: Recording Manager Integration

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Consumes: `RecordingOverlayController` from Task 1.
- Produces: `RecordingManager(..., overlay_controller=...)` and `RecordingManager.shutdown()`.

- [ ] **Step 1: Write failing manager tests**

Test that a successful start shows the overlay, stop hides it, listener-start failure hides it, and shutdown stops an active recording then shuts down the overlay.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'recording_manager_overlay or recording_manager_shutdown'`

Expected: failure because the manager has no overlay integration.

- [ ] **Step 3: Implement manager ownership**

Inject the controller, call `show()` only after all listeners start, call `hide()` on stop and failure, expose overlay information in status, and call `shutdown()` from the server `finally` block.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'recording_manager'`

Expected: existing and new manager tests pass.

### Task 3: Single Toggle and Countdown

**Files:**
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `tests/ui/windows_bridge_gui_browser_audit.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Produces: DOM element `recordToggle`, `RECORDING_COUNTDOWN_SECONDS = 5`, `beginRecordingCountdown()`, `stopActiveRecording()`, and `syncRecordingToggle()`.
- Consumes: unchanged `/recordings/start`, `/recordings/status`, and `/recordings/stop` routes.

- [ ] **Step 1: Write failing static and browser tests**

Assert that only `recordToggle` exists, the countdown constant is five, a second click cancels countdown or stops active recording, and status refresh restores `STOP RECORDING` for an active server recording.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'recording_console_toggle'`

Expected: failure because the old separate buttons remain.

- [ ] **Step 3: Implement the browser state machine**

Replace Record/Stop with one button, run the countdown before POST start, cancel safely during countdown, stop on active click, and synchronize status text/button state after every request.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'recording_console_toggle or program_manager_exposes'`

Expected: all selected tests pass.

### Task 4: Packaging and End-to-End Verification

**Files:**
- Modify: `install/windows_pyautogui_bridge_server.py`
- Modify: `tests/ui/windows_bridge_gui_browser_audit.py`

**Interfaces:**
- Consumes: completed source bridge implementation.
- Produces: byte-identical install bridge and browser audit evidence.

- [ ] **Step 1: Synchronize the install copy**

Copy the verified source script to `install/windows_pyautogui_bridge_server.py` only after confirming the two files were identical before this feature.

- [ ] **Step 2: Run focused and regression tests**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py tests/unit/test_install_packaging.py`

- [ ] **Step 3: Run syntax and parity checks**

Run: `python -m py_compile Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py && cmp Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py && git diff --check`

- [ ] **Step 4: Run the Selenium browser audit**

Start the local bridge with a temporary root and token, run `tests/ui/windows_bridge_gui_browser_audit.py`, and verify the Record page shows one idle toggle with image tracking enabled.

- [ ] **Step 5: Report without committing**

List changed files, test evidence, and the Windows-only native-overlay verification limitation. Do not commit or push.
