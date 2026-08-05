# Windows PyAutoGUI Macro Registry and Setup Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Windows bridge root into a real JSON macro setup console with a persistent validated registry and non-overlapping Advanced diagnostics.

**Architecture:** Built-in programs remain immutable in Python. Custom macros are validated JSON files loaded from a dedicated Windows program directory and merged into the public registry at read/execute time. The default GUI owns connection and macro management; Advanced Tools owns only calibration, UTM configuration, evidence, and raw diagnostics.

**Tech Stack:** Python `ThreadingHTTPServer`, embedded HTML/CSS/JavaScript, JSON files, pytest, Selenium/Firefox.

## Global Constraints

- Keep PyAutoGUI fail-safe enabled.
- Accept only `atr.pyautogui_program.v1` JSON macros using existing bounded actions.
- Never register arbitrary Python, PowerShell, BAT, CMD, or EXE files.
- Built-in program IDs are immutable.
- Keep packaged and install server copies identical.
- Do not change Linux Equipment Agent contracts.

---

## Tasks

### Task 1: Persistent bounded macro registry

- [ ] Add failing tests for validation, persistence, built-in protection, path safety, and reload.
- [ ] Add `WINDOWS_PYAUTOGUI_PROGRAM_DIR` and atomic JSON storage helpers.
- [ ] Add authenticated validate/register/delete endpoints.
- [ ] Merge custom macros into `GET /programs` and bounded `/execute` resolution.
- [ ] Run focused API and helper tests.

### Task 2: Non-overlapping setup GUI

- [ ] Add failing HTML tests requiring Program1 only in Program Manager and distinct New/Browse/Template/Add controls.
- [ ] Remove default UTM/program quick-action and runtime-monitoring cards.
- [ ] Replace browser-local shortcut persistence with server API calls.
- [ ] Keep Program Manager on the default surface and keep Advanced closed.
- [ ] Remove duplicated token, Health, Program1, and generic program-test controls from Advanced.

### Task 3: Browser and package verification

- [ ] Synchronize both server copies.
- [ ] Verify template download, Browse without registration, Add with registration, Test, and Delete in Selenium.
- [ ] Run the full Windows bridge helper suite and packaged smoke tests.
- [ ] Inspect the 1920x1080 screenshot for clipping and duplicated controls.
- [ ] Update setup and runtime documentation.
