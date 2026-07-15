# Grasp Outcome Observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify and persist read-only grasp outcomes, expose aggregate data through an API, and show only the latest attempt in the existing motion-state card.

**Architecture:** Extend `MotionStateAnnotator` with an observational latch fed only by existing action-log telemetry. Terminal artifact finalization replays the same log deterministically into `grasp_outcomes.json`; a FastAPI route exposes that artifact for a future aggregate card, while the current frontend hydrates only the packet-level latest result.

**Tech Stack:** Python 3.12, FastAPI, pytest, vanilla JavaScript, esbuild, CSS.

## Global Constraints

- Do not alter rollout command construction, VLA control, MotorBus/Dynamixel access, retry, stop, or Guardian behavior.
- Use `contact_gap = measured Gripper - policy target Gripper` and threshold `2.0`.
- Any measured arm movement during an active measured grasp marks transport overlap.
- Missing measured or target evidence must remain `pending`.
- Do not render aggregate success rate in the current Robot Motion State card.
- Persist derived artifacts by deterministic overwrite, never browser-driven append.

---

### Task 1: Packet-level grasp outcome state machine

**Files:**
- Modify: `utils/lerobot_joint_telemetry.py`
- Test: `tests/unit/test_lerobot_joint_telemetry.py`

**Interfaces:**
- Consumes: measured/policy outputs from `_channel_motion_state()` and packet `actual_source`/`target_source`.
- Produces: `motion_state.grasp_outcome` and `MotionStateAnnotator.grasp_attempts`.

- [ ] **Step 1: Write failing tests** for pending entry, positive-gap success, low-gap failure, transport-overlap failure, missing-target pending, and persistence through ungrasping.
- [ ] **Step 2: Run tests to verify RED** with missing `motion_state.grasp_outcome` assertions.
- [ ] **Step 3: Implement the minimal read-only latch** with attempt index, timing, evidence, and deterministic terminal records.
- [ ] **Step 4: Run the focused unit tests to verify GREEN.**

### Task 2: Deterministic artifact and aggregate API

**Files:**
- Modify: `utils/lerobot_joint_telemetry.py`
- Modify: `app/main.py`
- Test: `tests/unit/test_lerobot_joint_telemetry.py`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: `MotionStateAnnotator.grasp_attempts` from full log replay.
- Produces: `grasp_outcomes.json`, artifact metadata, and `GET /api/lerobot/grasp-outcomes`.

- [ ] **Step 1: Write failing artifact tests** asserting schema, ordered attempts, counts, `0.75` rate, idempotent overwrite, and cache invalidation by rule version.
- [ ] **Step 2: Write failing API tests** for empty idle and populated current/latest session responses.
- [ ] **Step 3: Run focused tests to verify RED.**
- [ ] **Step 4: Implement artifact aggregation and API response** without adding polling or device access.
- [ ] **Step 5: Run unit and integration tests to verify GREEN.**

### Task 3: Latest-attempt Live GUI strip

**Files:**
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Modify: `web/frontend/omx_telemetry_viewer/src/index.js`
- Generate: `web/static/omx_telemetry_viewer.bundle.js`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: packet `motion_state.grasp_outcome`.
- Produces: compact `data-atr-grasp-outcome` strip with idle/pending/success/failed tones.

- [ ] **Step 1: Write a failing static integration test** requiring the strip hooks and four visual tones while excluding aggregate success-rate copy.
- [ ] **Step 2: Run the test to verify RED.**
- [ ] **Step 3: Add markup, hydration, and CSS** for latest status/evidence only.
- [ ] **Step 4: Rebuild the frontend bundle** with `npm run build --prefix web/frontend/omx_telemetry_viewer`.
- [ ] **Step 5: Run static/integration tests to verify GREEN.**

### Task 4: Labelled-session replay and regression verification

**Files:**
- Verify: `runs/lerobot_action_logs/lr-rollout-20260714T110039768051Z-0001/motor_events.jsonl`

**Interfaces:**
- Consumes: final production annotator and artifact finalizer.
- Produces: verification evidence only; no control command.

- [ ] **Step 1: Replay the labelled log offline** and assert ordered statuses `success, failed, success, success`.
- [ ] **Step 2: Verify aggregate counts** `4/3/1/0` and success rate `0.75`.
- [ ] **Step 3: Run all telemetry unit tests, Live GUI integration tests, and frontend build.**
- [ ] **Step 4: Inspect the final diff** to confirm no rollout, MotorBus, Dynamixel, Guardian, or command-construction code changed.
