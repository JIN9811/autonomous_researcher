# Manipulation Bridge Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the LeRobot GUI Manipulation Agent Bridge so it matches the current Manipulation runtime supervisor contract without policy-name or SARM-first presentation.

**Architecture:** Keep existing backend endpoints and payload wiring. Update the bridge panel shell, report renderer, and static tests so the GUI presents runtime cards for bridge state, port/camera lease, policy runtime, Rerun telemetry, Vision gate, home pose/interlock, and execution safety. Preserve existing run/test/preview/stop/status behavior.

**Tech Stack:** FastAPI templates, vanilla JavaScript, pytest static tests.

## Global Constraints

- Do not remove legacy `sarm` backend fields in this pass; GUI must use `Execution Safety`.
- Do not title cards with SmolVLA, Pi0.5, or SARM.
- Do not change LeRobot rollout execution commands in this pass.
- Preserve existing Manipulation Agent bridge buttons and endpoint contracts.
- Write tests before production code.

---

### Task 1: Static Contract Test

**Files:**
- Modify: `tests/unit/test_lerobot_gui_static.py`

**Interfaces:**
- Consumes: `web/templates/lerobot.html`, `web/static/lerobot.js`
- Produces: failing test that requires runtime-supervisor bridge labels and renderer fields

- [ ] **Step 1: Write the failing test**

```python
def test_manipulation_bridge_runtime_supervisor_cards_are_wired() -> None:
    template = Path("web/templates/lerobot.html").read_text(encoding="utf-8")
    script = Path("web/static/lerobot.js").read_text(encoding="utf-8")

    assert "Bridge State" in template
    assert "Port Lease" in template
    assert "Active Camera" in template
    assert "Robot Policy Runtime" in template
    assert "Rerun Telemetry" in template
    assert "Vision Completion Gate" in template
    assert "Home Pose / Interlock" in template
    assert "Execution Safety" in template
    assert "Pi0.5/SARM state" not in template
    assert "Pi0.5 / Policy Runtime" not in script
    assert "SARM Stage Progress" not in script
    assert "executionSafetyFromReport" in script
    assert "rerunTelemetryFromReport" in script
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_lerobot_gui_static.py::test_manipulation_bridge_runtime_supervisor_cards_are_wired -q`

Expected: FAIL because the current template and renderer still use old labels.

- [ ] **Step 3: Implement minimal GUI update**

Modify `web/templates/lerobot.html` bridge copy and static card shell. Modify `web/static/lerobot.js` renderer to use `Execution Safety`, `Robot Policy Runtime`, and `Rerun Telemetry`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_lerobot_gui_static.py::test_manipulation_bridge_runtime_supervisor_cards_are_wired -q`

Expected: PASS.

### Task 2: Existing Static Regression

**Files:**
- Test: `tests/unit/test_lerobot_gui_static.py`

**Interfaces:**
- Consumes: all LeRobot GUI static tests
- Produces: assurance that existing wiring remains intact

- [ ] **Step 1: Run static GUI test file**

Run: `pytest tests/unit/test_lerobot_gui_static.py -q`

Expected: PASS.
