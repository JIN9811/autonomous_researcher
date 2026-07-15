# Manipulation Live Pose And Policy Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a low-latency OMX pose viewer and scientific actual-versus-policy tracking card to the Live GUI without changing the robot control loop.

**Architecture:** A read-only backend observer tails the existing OMX action JSONL, converts existing normalized motor values with the shared OMX mapping, and streams compact packets over a dedicated WebSocket. A locally bundled Three.js viewer loads the existing MJCF/STL assets, while an ECharts scientific plot displays bounded live history and Matplotlib writes terminal evidence.

**Tech Stack:** Python 3.12, FastAPI WebSocket, Matplotlib, vanilla JavaScript, ECharts 5.6, Three.js 0.177, STLLoader, pytest.

## Global Constraints

- Do not alter LeRobot command/control flow or open another MotorBus connection.
- Read only existing `motor_events.jsonl` telemetry.
- Use repository-local OMX MJCF/STL assets.
- Live plot uses a white publication-style layout with labeled axes and legend.
- Persist terminal PNG and JSON evidence while retaining existing CSV/JSONL raw evidence.
- Preserve all pre-existing dirty-worktree changes.

---

### Task 1: Joint Telemetry Parser And Artifact Writer

**Files:**
- Create: `utils/lerobot_joint_telemetry.py`
- Create: `tests/unit/test_lerobot_joint_telemetry.py`

**Interfaces:**
- Produces: `normalize_action_event(event, calibration=None) -> dict[str, Any] | None`
- Produces: `JointTelemetryFileObserver.poll(path, session) -> list[dict[str, Any]]`
- Produces: `finalize_policy_tracking_artifacts(path, session) -> dict[str, Any]`

- [x] Write parser tests for actual, requested target, sent target, elapsed time, malformed rows, and shared OMX conversion.
- [x] Run `pytest -q tests/unit/test_lerobot_joint_telemetry.py` and confirm the missing-module failure.
- [x] Implement minimal parser and bounded incremental observer.
- [x] Add artifact tests for a six-joint Matplotlib PNG and metric summary JSON.
- [x] Implement idempotent artifact generation.
- [x] Run `pytest -q tests/unit/test_lerobot_joint_telemetry.py` and confirm all tests pass.

### Task 2: Read-Only WebSocket And Model Asset Route

**Files:**
- Modify: `app/main.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Produces: `GET /api/lerobot/joint-telemetry/snapshot`
- Produces: `WS /ws/lerobot/joint-telemetry`
- Produces: static `/assets/robotis-omx/*`

- [x] Add failing tests for model XML access, idle snapshot, and test-injected telemetry packet shape.
- [x] Run the targeted integration tests and confirm failures.
- [x] Add the OMX static mount and a singleton read-only observer.
- [x] Implement session selection across backend-owned and registered LeRobot bridges.
- [x] Implement snapshot and WebSocket routes with 50 ms polling, latest-only delivery, stale state, and terminal finalization.
- [x] Run the targeted integration tests and confirm they pass.

### Task 3: Local OMX Viewer Bundle

**Files:**
- Create: `web/frontend/omx_telemetry_viewer/package.json`
- Create: `web/frontend/omx_telemetry_viewer/package-lock.json`
- Create: `web/frontend/omx_telemetry_viewer/src/index.js`
- Create: `web/static/omx_telemetry_viewer.bundle.js`
- Modify: `web/templates/planning.html`

**Interfaces:**
- Produces: `window.ATRRobotTelemetryCards.hydrate()`
- Consumes: `/assets/robotis-omx/omx.xml`, STL assets, and `/ws/lerobot/joint-telemetry`

- [x] Add a failing static test for the local bundle, viewer mount, WebSocket URL, MJCF path, actual model, and target ghost.
- [x] Run the static test and confirm failure.
- [x] Implement MJCF parsing, STL preload, body hierarchy, joint-axis application, gripper mimic, camera fit, and measured/ghost materials.
- [x] Implement bounded reconnect, latest-sample interpolation, visibility pause, and WebGL disposal.
- [x] Build the IIFE bundle with local npm dependencies and retain license metadata.
- [x] Run `node --check` on source and bundle, then rerun the static test.

### Task 4: Two Manipulation Agent Cards

**Files:**
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: `window.ATRRobotTelemetryCards.hydrate()`
- Produces: `[data-atr-robot-pose]` and `[data-atr-policy-tracking]` mounts.

- [x] Add failing assertions for `Live Robot Pose`, `Policy Tracking`, joint selector, measured/target legend, and artifact footer.
- [x] Run the targeted test and confirm failure.
- [x] Add the two cards to both canonical and fallback manipulation-report branches.
- [x] Add restrained card styling; keep the plot region white and all labels readable.
- [x] Trigger idempotent hydration after report rerenders.
- [x] Run `node --check web/static/planning.js` and the targeted tests.

### Task 5: Live Scientific Plot And Artifact Links

**Files:**
- Modify: `web/frontend/omx_telemetry_viewer/src/index.js`
- Regenerate: `web/static/omx_telemetry_viewer.bundle.js`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: joint-sample and terminal-artifact packets.
- Produces: selected-joint ECharts series and artifact links.

- [x] Add failing source assertions for white background, axis names, legend labels, bounded history, and terminal artifact handling.
- [x] Implement a plain scientific ECharts line chart with elapsed seconds and joint degrees.
- [x] Preserve history across report DOM replacement and reset only when `session_id` changes.
- [x] Expose PNG, CSV, JSONL, and summary JSON links after terminal finalization.
- [x] Rebuild and rerun static tests.

### Task 6: Verification And Documentation

**Files:**
- Modify: `docs/gui/gui.md`
- Modify: `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`
- Modify: `docs/superpowers/specs/2026-07-09-manipulation-runtime-supervisor-design.md`

**Interfaces:**
- Documents the two cards, source semantics, artifact locations, and no-second-serial rule.

- [x] Run all new unit/integration tests plus existing manipulation and LeRobot static tests.
- [x] Run `node --check` for changed JavaScript sources.
- [x] Start an isolated GUI server, load the Live GUI, select Manipulation Agent, and inspect browser console/network.
- [x] Inject a recorded action-log fixture and capture a browser screenshot showing both cards.
- [x] Verify the plot is white, axes/legend are legible, model geometry loads, and target ghost is distinct.
- [x] Verify backend RSS and browser history remain bounded over a repeated telemetry replay.
- [x] Update the three runtime documents with verified behavior and artifact paths.


## Verification Record

- New/targeted telemetry tests: 14 passed.
- Browser audit: repository OMX XML and all eight STL assets loaded; 205 measured and 205 target samples rendered; terminal PNG and summary links enabled.
- Browser captures: `runs/ui_audit/manipulation_live_robot_pose_terminal.png` and `runs/ui_audit/manipulation_policy_tracking_terminal.png`.
- Terminal evidence: `runs/lerobot_action_logs/<session_id>/policy_tracking.png` and `policy_tracking_summary.json`.
- 128 MiB sparse-log probe: 20 retained samples, latest sequence 30, 2.01 MiB Python allocation peak with a 1 MiB initial-tail limit.
- Broader related suite: 331 passed and 10 pre-existing dirty-worktree failures outside this extension. The unrelated Active Cam, training/Isaac defaults, event-helper extraction, and historical cache-buster assertions were not changed as part of this implementation.
