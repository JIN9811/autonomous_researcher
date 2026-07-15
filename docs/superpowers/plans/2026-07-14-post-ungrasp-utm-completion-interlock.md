# Post-Ungrasp UTM Completion Interlock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete a manipulation rollout only after measured ungrasping, measured stable home, one UTM observation frame, and VisionAgent specimen confirmation.

**Architecture:** Extend the existing LeRobot status contract with a session-scoped telemetry latch, pass that gate through ManipulationAgent, and let VisionAgent own one-frame UTM specimen detection and the existing `vision_manipulation_completion.v1` signal. Persist the successful UTM frame as a run artifact and render it beside Active Cam without changing the robot control loop.

**Tech Stack:** Python 3.12, FastAPI, existing ToolRegistry/MCP contracts, ROS 2 UTM runtime bridge, OpenCV/NumPy, vanilla JavaScript/CSS, pytest.

## Global Constraints

- Measured telemetry is authoritative; policy target is diagnostic only.
- Preserve `vision_manipulation_completion.v1` and `lerobot.rollout.stop` contracts.
- Do not add direct robot or camera-device writes to agents.
- Physical routes fail closed; virtual evidence is allowed only on the explicit virtual test route.
- Artifact identity must match `run_id`, `rollout_session_id`, and `specimen_id`.
- Existing Active Cam ejection behavior must remain unchanged.

---

### Task 1: Session-Scoped Post-Place Telemetry Gate

**Files:**
- Modify: `utils/lerobot_joint_telemetry.py`
- Modify: `device_bridges/lerobot_bridge.py`
- Test: `tests/unit/test_lerobot_joint_telemetry.py`
- Test: `tests/unit/test_lerobot_bridge.py`

**Interfaces:**
- Consumes: normalized packets containing `motion_state.measured.base_state`, `motion_state.measured.gripper_state`, and `motion_state.measured.home_gate.passed`.
- Produces: `PostPlaceInterlock.observe(packet) -> dict[str, Any]` and `rollout.status.post_place_interlock`.

- [x] **Step 1: Write failing telemetry tests**

Add tests proving that home before ungrasping is not ready, ungrasping followed by stable measured home is ready, policy-only ungrasping is ignored, and a new session resets the latch.

- [x] **Step 2: Run the red tests**

Run: `.venv/bin/pytest tests/unit/test_lerobot_joint_telemetry.py -k post_place_interlock -q`

Expected: failures because `PostPlaceInterlock` and its response schema do not exist.

- [x] **Step 3: Implement the minimal latch**

Add a small dataclass that records the measured ungrasp sequence and accepts only a later measured home packet whose existing home gate passed. Keep one latch per rollout action-log path inside the LeRobot bridge and include the compact result in status responses.

- [x] **Step 4: Run telemetry and bridge tests**

Run: `.venv/bin/pytest tests/unit/test_lerobot_joint_telemetry.py tests/unit/test_lerobot_bridge.py -q`

Expected: all selected tests pass.

### Task 2: UTM One-Frame Specimen Presence Tool

**Files:**
- Create: `utils/utm_specimen_presence.py`
- Modify: `device_bridges/utm_runtime_bridge.py`
- Modify: `mcp_tools/camera_tools.py`
- Test: `tests/unit/test_utm_specimen_presence.py`
- Test: `tests/unit/test_camera_tools_utm_runtime.py`

**Interfaces:**
- Consumes: one `UTMRuntimeProcessManager.frame()` payload with `data_url`, topic, dimensions, and runtime identity.
- Produces: `vision.utm_specimen_presence.capture` with `schema=utm_specimen_presence.v1`, `detected`, `confidence`, `bbox_xyxy`, `frame_path`, and `annotated_path`.

- [x] **Step 1: Write failing detector and tool tests**

Use synthetic red-specimen and empty-frame fixtures. Assert success, absence, malformed frame, physical fail-closed, and explicit virtual-test behavior.

- [x] **Step 2: Run the red tests**

Run: `.venv/bin/pytest tests/unit/test_utm_specimen_presence.py tests/unit/test_camera_tools_utm_runtime.py -q`

Expected: failures because the detector and tool are not registered.

- [x] **Step 3: Implement deterministic one-frame detection**

Decode the captured data URL, apply the existing dual-range red HSV mask and morphology convention, reject contours below configured area, annotate a copy, and return evidence without keeping the camera open.

- [x] **Step 4: Run detector and tool tests**

Run: `.venv/bin/pytest tests/unit/test_utm_specimen_presence.py tests/unit/test_camera_tools_utm_runtime.py -q`

Expected: all selected tests pass.

### Task 3: Manipulation-to-Vision Interlock Wiring

**Files:**
- Modify: `agents/manipulation_agent.py`
- Modify: `agents/vision_agent.py`
- Modify: `orchestrator/langgraph_runtime.py`
- Test: `tests/unit/test_manipulation_lerobot_agent.py`
- Test: `tests/unit/test_vision_agent.py`
- Test: `tests/unit/test_manipulation_active_cam_loop.py`

**Interfaces:**
- Consumes: `rollout.status.post_place_interlock` and `vision.utm_specimen_presence.capture`.
- Produces: `robot_task_result.post_place_interlock`, `utm_completion_artifact_update`, and identity-bound `vision_manipulation_completion.v1`.

- [x] **Step 1: Write failing agent-loop tests**

Assert that Vision capture is not called before ungrasping/home, exactly one capture is called after the gate, no detection keeps rollout active, detection requests stop, and completion waits for `STOPPED`.

- [x] **Step 2: Run the red tests**

Run: `.venv/bin/pytest tests/unit/test_manipulation_lerobot_agent.py tests/unit/test_vision_agent.py tests/unit/test_manipulation_active_cam_loop.py -k 'post_place or ungrasp or utm_completion' -q`

Expected: failures because current code requests UTM verification from `reported_complete` alone.

- [x] **Step 3: Add the gate and one-frame handoff**

Copy the bridge gate into the manipulation response and robot-task result. Keep the rollout active while the gate is false. When true, let VisionAgent call the UTM presence tool once and emit the existing completion signal only for matching identity and positive detection.

- [x] **Step 4: Persist and merge the UTM artifact**

Write the annotated frame under the current run, emit `utm_completion_artifact_update`, and merge or clear `run_metadata.latest_utm_completion_artifact` using the same bounded update pattern as Active Cam.

- [x] **Step 5: Run the agent-loop tests**

Run: `.venv/bin/pytest tests/unit/test_manipulation_lerobot_agent.py tests/unit/test_vision_agent.py tests/unit/test_manipulation_active_cam_loop.py -q`

Expected: all selected tests pass.

### Task 4: Vision Dashboard Card and Layout

**Files:**
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Test: `tests/unit/test_planning_design_report_js.py`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: `run_metadata.latest_utm_completion_artifact`, `vision_manipulation_completion`, and `post_place_interlock`.
- Produces: the `UTM Placement Confirmation` card and balanced two-row Vision dashboard.

- [x] **Step 1: Write failing layout/static tests**

Assert the new card title, retained-artifact lookup, identity guard, inspection details, row order, and six four-column cards.

- [x] **Step 2: Run the red tests**

Run: `.venv/bin/pytest tests/unit/test_planning_design_report_js.py tests/integration/test_live_gui_runtime_layout.py -k 'vision or utm' -q`

Expected: failures because the UTM confirmation card is absent and Agentic Progress still spans eight columns.

- [x] **Step 3: Implement the card and layout**

Place Live Observation, Active Cam, and UTM confirmation in row one. Place Device Bridge, Handoff, and Agentic Progress in row two. Reuse the Active Cam card's frame/metrics/details structure while keeping distinct labels and fields.

- [x] **Step 4: Run frontend tests**

Run: `.venv/bin/pytest tests/unit/test_planning_design_report_js.py tests/integration/test_live_gui_runtime_layout.py -q`

Expected: all selected tests pass.

### Task 5: Regression and Full-Path Verification

**Files:**
- Modify only if a failing regression exposes a scoped defect.

**Interfaces:**
- Consumes: all contracts from Tasks 1-4.
- Produces: verified virtual-loop behavior without physical actuation.

- [x] **Step 1: Run focused backend regression**

Run: `.venv/bin/pytest tests/unit/test_lerobot_joint_telemetry.py tests/unit/test_lerobot_bridge.py tests/unit/test_camera_tools_utm_runtime.py tests/unit/test_manipulation_lerobot_agent.py tests/unit/test_vision_agent.py tests/unit/test_manipulation_active_cam_loop.py -q`

- [x] **Step 2: Run Live GUI integration tests**

Run: `.venv/bin/pytest tests/integration/test_live_gui_runtime_layout.py -q`

- [x] **Step 3: Run a virtual closed-loop smoke test**

Use the existing test-mode virtual bridge. Verify the recorded sequence is `ungrasping_seen -> home_after_ungrasping -> utm_frame_captured -> specimen_detected -> rollout_stopped` and that no physical device command is issued.

- [x] **Step 4: Inspect the final diff**

Run: `git diff --check && git diff --stat`

Expected: no whitespace errors and only scoped interlock, Vision artifact, UI, tests, and documentation changes.
