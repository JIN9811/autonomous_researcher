# RealSense Non-Invasive Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove invasive RealSense re-enumeration and post-ActiveCam stream reacquisition from routine LeRobot execution.

**Architecture:** Use Linux sysfs as the primary physical-presence and USB-link source. Treat successful termination of the isolated ActiveCam process as OS-handle release, leaving the next rollout as the only subsequent camera opener.

**Tech Stack:** Python 3.12, pytest, Linux sysfs, LeRobot bridge.

## Global Constraints

- Do not change GUI payloads, rollout policy selection, camera identities, or inference arguments.
- Do not issue USB reset, bind/unbind, or power-policy commands.
- Do not add a fallback camera path.

---

### Task 1: Non-invasive RealSense inventory

**Files:**
- Modify: `device_bridges/lerobot_bridge.py`
- Test: `tests/unit/test_lerobot_bridge.py`

**Interfaces:**
- Consumes: `/sys/bus/usb/devices/*/{idVendor,product,serial,speed}`
- Produces: `LeRobotBridge._scan_realsense_camera_entries() -> list[dict[str, Any]]`

- [ ] Add a failing test proving a sysfs-visible RealSense is returned without constructing an SDK context.
- [ ] Run the focused test and confirm it fails because current code calls `pyrealsense2.context()`.
- [ ] Add sysfs-first enumeration and retain SDK enumeration only when sysfs returns no RealSense devices.
- [ ] Run the focused RealSense tests.

### Task 2: Process-exit camera release

**Files:**
- Modify: `device_bridges/lerobot_bridge.py`
- Test: `tests/unit/test_lerobot_bridge.py`

**Interfaces:**
- Consumes: successful `lerobot_active_robot_cam_once.py` exit and capture payload
- Produces: `release_status=process_exit_verified`, `camera_returned_to_vla=true`

- [ ] Change the existing ActiveCam test to require exactly one subprocess and no reacquire probe.
- [ ] Run the test and confirm it fails against the existing fresh-process probe.
- [ ] Remove the post-capture RGB-D reacquisition call and normalize the successful process-exit release contract.
- [ ] Run ActiveCam and rollout-profile unit tests.

### Task 3: Regression verification

**Files:**
- Verify only; no additional production changes.

**Interfaces:**
- Consumes: focused unit suite and kernel log baseline
- Produces: evidence that no routine test opens physical cameras

- [ ] Run `pytest` for RealSense, ActiveCam, rollout profile, and GUI API tests.
- [ ] Confirm no `lerobot_camera_reacquire_probe.py` process is launched by the tested path.
- [ ] Inspect new kernel messages and confirm no new periodic UVC rebinding occurred during non-hardware tests.
