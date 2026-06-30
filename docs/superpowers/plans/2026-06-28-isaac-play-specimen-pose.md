# Isaac Play Specimen Pose Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing ROS2 red specimen pose snapshot once before Isaac timeline play and update the simulated red cube pose when detection succeeds.

**Architecture:** Keep the ROS2 detector unchanged and call its existing shell wrapper from the Isaac extension delayed-play callback. The extension parses the one-shot JSON output, applies `pose.position_isaac_world_mm` to `/World/Workspace/RedSpecimenBlock`, and logs a visible warning if detection fails so the operator can place the cube manually.

**Tech Stack:** Isaac Sim extension Python, ROS2 wrapper shell script, USD prim attributes, pytest unit tests with fake Isaac modules.

---

### Task 1: Red Cube Pose Application Helpers

**Files:**
- Modify: `sim/robotis_omx/extensions/atr.omx.mirror/atr/omx/mirror/extension.py`
- Test: `tests/unit/test_isaac_omx_mirror_extension.py`

- [ ] **Step 1: Write failing tests**

Add tests that call helper functions directly with a fake stage. The success test passes a snapshot payload containing `pose.position_isaac_world_mm` and expects `/World/Workspace/RedSpecimenBlock` `xformOp:translate` to be set in meters. The failure test passes `{"ok": false, "failure_code": "SPECIMEN_NOT_DETECTED"}` and expects the cube translate to remain unchanged and a warning message to be returned.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_isaac_omx_mirror_extension.py::test_specimen_pose_snapshot_updates_red_cube_translate tests/unit/test_isaac_omx_mirror_extension.py::test_specimen_pose_snapshot_failure_keeps_cube_translate_and_reports_alarm -q`

Expected: fail because the helper functions do not exist.

- [ ] **Step 3: Implement helpers**

Add helper functions to parse the snapshot result, convert millimeters to meters, find the red cube prim, set or create `xformOp:translate`, and return a structured status dictionary.

- [ ] **Step 4: Run tests to verify pass**

Run the same two tests. Expected: both pass.

### Task 2: Delayed Play Integration

**Files:**
- Modify: `sim/robotis_omx/extensions/atr.omx.mirror/atr/omx/mirror/extension.py`
- Modify: `sim/robotis_omx/extensions/atr.omx.mirror/config/extension.toml`
- Test: `tests/unit/test_isaac_omx_mirror_extension.py`

- [ ] **Step 1: Write failing delayed-play tests**

Add a test where the delayed play callback runs a fake snapshot runner before `_play_timeline`, applies the cube pose, and then plays the timeline. Add a failure-path test that verifies play still happens after a warning status.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_isaac_omx_mirror_extension.py -q`

Expected: fail because delayed play does not run the snapshot path.

- [ ] **Step 3: Implement integration**

Extend `install_delayed_timeline_play_subscription` with optional specimen snapshot settings. In `on_startup`, read extension settings for enabling the one-shot, wrapper path, timeout, output dir, and red cube prim path.

- [ ] **Step 4: Run tests and restart receiver**

Run: `pytest tests/unit/test_isaac_omx_mirror_extension.py tests/unit/test_isaac_omx_mirror_server.py -q`

Expected: pass. Restart the mirror receiver only after warning the operator that teleop will briefly disconnect.
