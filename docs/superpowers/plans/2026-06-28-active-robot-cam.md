# Active Robot-Cam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Active Robot-Cam specimen tracking that moves the real OMX follower to a saved D405 capture pose, captures RGB + 16-bit depth, estimates specimen pose, and resumes safely.

**Architecture:** Keep LeRobot core untouched. Add request fields and environment plumbing in `device_bridges/lerobot_bridge.py`, run the real motion/capture inside `scripts/lerobot_isaac_mirror_runtime_wrapper.py` while LeRobot owns the robot/cameras, and expose GUI checkboxes in `web/templates/lerobot.html` plus `web/static/lerobot.js`. D405 wrist camera is primary; existing D455F/top latest-frame tracking remains fallback.

**Tech Stack:** Python, LeRobot OMX wrapper monkey patches, RealSense RGB-D sidecar PNG16, Isaac mirror HTTP endpoint, FastAPI GUI payloads, pytest.

---

### Task 1: Active Robot-Cam Runtime Wrapper

**Files:**
- Modify: `scripts/lerobot_isaac_mirror_runtime_wrapper.py`
- Test: `tests/unit/test_lerobot_isaac_mirror_runtime_wrapper.py`

- [ ] Write failing tests for D405 priority, D455F fallback, and teleop-vs-standalone resume policy.
- [ ] Implement `ActiveRobotCamTracker` with saved capture/home pose loading, slow interpolation, one-frame capture, specimen pose update, and JSON result sidecar.
- [ ] Patch `OmxFollower.send_action` so in-process teleop/record can run the capture once without opening a second Dynamixel connection.

### Task 2: LeRobot Bridge API and Env Plumbing

**Files:**
- Modify: `mcp_tools/lerobot_schemas.py`
- Modify: `device_bridges/lerobot_bridge.py`
- Test: `tests/unit/test_lerobot_bridge.py`

- [ ] Add request fields for Active Robot-Cam enablement, D405/D455F switching, capture/home pose paths, and resume mode.
- [ ] Pass env vars into live teleop/record wrapper.
- [ ] Record session metadata that Active Robot-Cam was enabled.

### Task 3: GUI Controls

**Files:**
- Modify: `web/templates/lerobot.html`
- Modify: `web/static/lerobot.js`
- Test: `tests/integration/test_lerobot_gui_api.py`

- [ ] Add checkbox controls for Active Robot-Cam specimen tracking and record-start usage.
- [ ] Send payload fields from teleop and record starts.
- [ ] Keep D405 primary / D455F fallback visible in operator-facing labels.

### Task 4: Verification

**Files:**
- Run focused pytest suites.
- Run a live dry check against saved pose files before commanding motion.
- Execute a slow real follower move only after pose files, ports, and camera availability are confirmed.
