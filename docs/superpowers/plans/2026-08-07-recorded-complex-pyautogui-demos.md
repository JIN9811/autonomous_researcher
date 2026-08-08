# Recorded Complex PyAutoGUI Demos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and deploy independent recorded text-editor and browser-form Equipment Skills through the existing local PyAutoGUI bridge.

**Architecture:** A repository-owned static form supplies the deterministic browser target. The existing bridge records real X11 mouse and keyboard events, captures checkpoints, and sends saved recordings through the current Skill lifecycle. No production Equipment Agent route or bridge action contract changes.

**Tech Stack:** Python HTTP bridge, PyAutoGUI, pynput, FastAPI proxy, static HTML, pytest, curl/jq.

## Global Constraints

- Use the selected `local_development` bridge at `127.0.0.1:8767`.
- Keep PyAutoGUI fail-safe enabled.
- Do not issue physical equipment commands.
- Do not modify existing user files.
- Do not commit after implementation.

---

### Task 1: Deterministic Browser Form Asset

**Files:**
- Create: `Pyautogui_server_for_window/demo/browser_form.html`
- Test: `tests/unit/test_windows_pyautogui_demo_assets.py`

**Interfaces:**
- Consumes: Firefox file URL support.
- Produces: static form with `name`, `sample_count`, `mode`, `submit`, and `result` elements.

- [ ] **Step 1: Write a failing asset contract test**

Assert that the HTML file exists, contains the five stable element IDs, has no remote resource URLs, and sets `result` text to `FORM WORKFLOW COMPLETED` on submit.

- [ ] **Step 2: Run the focused test and confirm the missing-asset failure**

Run: `pytest -q tests/unit/test_windows_pyautogui_demo_assets.py`

- [ ] **Step 3: Add the minimal self-contained HTML form**

Use inline CSS and JavaScript only. Submission must remain on the same page and render all submitted values.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run: `pytest -q tests/unit/test_windows_pyautogui_demo_assets.py`

### Task 2: Record and Deploy Text Editor Skill

**Files:**
- Create at runtime: `runs/local_pyautogui_bridge/recordings/rec-*/recording.json`
- Create at runtime: `memory/equipment_skills/text_editor_workflow/1.0.0/`
- Create at runtime: `memory/local_pyautogui_programs/text_editor_workflow_1_0_0_segment_*.json`

**Interfaces:**
- Consumes: bridge recording API and existing Skill lifecycle API.
- Produces: deployed `text_editor_workflow@1.0.0` and `/tmp/atr_pyautogui_text_demo.txt`.

- [ ] **Step 1: Start a bridge recording through the GUI proxy API**
- [ ] **Step 2: Perform the editor workflow using real desktop input events**
- [ ] **Step 3: Capture the post-save checkpoint, stop, and save the recording**
- [ ] **Step 4: Create, annotate, compile, validate, and deploy the Skill**
- [ ] **Step 5: Run Skill Test and verify the output file content and checkpoint**

### Task 3: Record and Deploy Browser Form Skill

**Files:**
- Create at runtime: `runs/local_pyautogui_bridge/recordings/rec-*/recording.json`
- Create at runtime: `memory/equipment_skills/browser_form_workflow/1.0.0/`
- Create at runtime: `memory/local_pyautogui_programs/browser_form_workflow_1_0_0_segment_*.json`

**Interfaces:**
- Consumes: Task 1 static form and existing bridge recording/Skill APIs.
- Produces: deployed `browser_form_workflow@1.0.0`.

- [ ] **Step 1: Start a separate bridge recording through the GUI proxy API**
- [ ] **Step 2: Open the local form and perform all form interactions using real desktop input events**
- [ ] **Step 3: Capture the submitted-result checkpoint, stop, and save the recording**
- [ ] **Step 4: Create, annotate, compile, validate, and deploy the Skill**
- [ ] **Step 5: Run Skill Test and verify the completed result remains visible**

### Task 4: Regression and GUI-Path Verification

**Files:**
- Test: `tests/unit/test_windows_pyautogui_demo_assets.py`
- Verify: existing Equipment Skill and bridge tests.

**Interfaces:**
- Consumes: deployed Skill and Program Manager APIs.
- Produces: evidence that both demos are independently recorded, listed, and executable.

- [ ] **Step 1: Run focused unit and integration tests**

Run: `pytest -q tests/unit/test_windows_pyautogui_demo_assets.py tests/unit/test_equipment_skill_runtime.py tests/integration/test_equipment_skill_api.py`

- [ ] **Step 2: Query bridge Health, recordings, Skills, and Programs through the GUI proxy**

Confirm HTTP 200, distinct recording IDs, deployed lifecycle, and distinct compiled program IDs.

- [ ] **Step 3: Preserve all generated evidence without committing**

Report recording IDs, Skill IDs, program IDs, checkpoint paths, and test results to the user.
