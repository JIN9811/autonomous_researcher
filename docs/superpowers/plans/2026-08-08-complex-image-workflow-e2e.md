# Complex Image Workflow E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a saved multi-window image-first Equipment Skill.

**Architecture:** A deterministic Tk application supplies multiple windows and durable file artifacts. The existing bridge records real OS input, compiles it through `EquipmentSkillRegistry`, and replays the registered program after the UI layout shifts.

**Tech Stack:** Python 3.12, Tkinter, PyAutoGUI, pynput, Xvfb, ATR Equipment Skill runtime

## Global Constraints

- Do not modify the existing control or bridge implementation.
- Image-first replay is required and coordinate fallback remains disabled.
- Do not commit before user review.

---

### Task 1: Deterministic Multi-Window Target

**Files:**
- Create: `runs/equipment_skill_complex_e2e/complex_workflow_demo.py`
- Create: `runs/equipment_skill_complex_e2e/input/specimen.csv`

- [ ] Implement file-browser, main form, analysis result, and save-dialog states.
- [ ] Add initial, shifted, and reset layouts controlled through a command file.
- [ ] Persist status and saved output for external assertions.

### Task 2: Real Recording and Skill Creation

**Files:**
- Create: `memory/equipment_skills/complex_image_workflow_demo/1.0.0/*`

- [ ] Start the existing bridge on an isolated X11 display.
- [ ] Record real click and keyboard events through the bridge API.
- [ ] Save, annotate, compile, and validate the exact recording.
- [ ] Assert every compiled click has PNG candidates and no coordinates.

### Task 3: Shifted Replay and Failure Test

**Files:**
- Create: `runs/equipment_skill_complex_e2e/evidence/*`
- Create: `runs/equipment_skill_complex_e2e/e2e_summary.json`

- [ ] Shift the full application layout and reset its state.
- [ ] Register and execute the compiled program through `/execute`.
- [ ] Assert completed UI state and validate the saved JSON output.
- [ ] Close the target application and assert replay blocks with `UI_LOCATOR_NOT_FOUND`.
- [ ] Record both outcomes in the Skill manifest without marking it deployed.
