# Manipulation Grounded Runtime Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace conceptual Manipulation Agent report cards with eight always-visible, source-backed runtime cards and live task/grasp success metrics.

**Architecture:** Extend the existing read-only LeRobot telemetry annotation path with a deterministic task-cycle state machine. Build `manipulation_runtime_view.v1` in the backend and attach it to the existing snapshot/WebSocket payloads; the existing telemetry browser bundle patches fixed card DOM without changing rollout, camera, MotorBus, or equipment control paths.

**Tech Stack:** Python 3.12, FastAPI, existing LeRobot JSONL telemetry, vanilla JavaScript, CSS conic-gradient donuts, pytest.

## Global Constraints

- Keep all eight cards present in every runtime state; never hide or recreate cards based on data availability.
- Use only `MEASURED`, `DERIVED`, `EVENT`, `CONFIGURED`, and `ARTIFACT` evidence.
- One task is `HOME_START -> MOVING -> GRASPING -> UNGRASPING -> HOME_RETURN`.
- Task success is `completed tasks / attempted tasks`; grasp success is `successful completed grasps / completed grasp attempts`.
- Do not modify rollout commands, robot/camera ownership, MotorBus access, or device control.
- Preserve Three.js and ECharts DOM identities and update only text, classes, donut variables, and series.

---

### Task 1: Deterministic Task-Cycle Telemetry

**Files:**
- Modify: `utils/lerobot_joint_telemetry.py`
- Test: `tests/unit/test_lerobot_joint_telemetry.py`

**Interfaces:**
- Consumes: annotated `motion_state.measured`, existing `grasp_outcome`, packet sequence/time.
- Produces: `motion_state.task_cycle` containing cumulative task counts, current milestones, and task-local grasp counts.

- [x] **Step 1: Add failing tests for complete, repeated, interrupted, and multi-attempt task cycles**

```python
assert packets[-1]["motion_state"]["task_cycle"]["completed_count"] == 1
assert packets[-1]["motion_state"]["task_cycle"]["grasp"]["attempt_count"] == 2
```

- [x] **Step 2: Run the focused tests and confirm missing `task_cycle` failures**

Run: `.venv/bin/pytest -q tests/unit/test_lerobot_joint_telemetry.py -k task_cycle`

- [x] **Step 3: Implement `TaskCycleAnnotator` and attach its snapshot after motion/grasp annotation**

The state machine starts only after stable measured home, advances core milestones in order, ignores duplicate samples, and completes only on a later stable home after ungrasping.

- [x] **Step 4: Make initial tail hydration process pre-roll events without retaining them**

The observer returns only its configured tail while feeding every action row in the byte-bounded initial read through the annotators, preserving reconnect totals without an unbounded read or browser history.

- [x] **Step 5: Run telemetry unit tests**

Run: `.venv/bin/pytest -q tests/unit/test_lerobot_joint_telemetry.py`

### Task 2: Canonical Backend Runtime View

**Files:**
- Create: `utils/manipulation_runtime_view.py`
- Modify: `app/main.py`
- Create: `tests/unit/test_manipulation_runtime_view.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: controller state, manipulation report, robot task result, selected rollout session, latest telemetry packet, terminal artifacts.
- Produces: `build_manipulation_runtime_view(...) -> dict` with schema `manipulation_runtime_view.v1`.

- [x] **Step 1: Add failing pure builder tests for idle, running, verifying, terminal, missing data, and provenance**

```python
view = build_manipulation_runtime_view(session={}, state={}, packet=None, artifacts={})
assert view["schema"] == "manipulation_runtime_view.v1"
assert view["metrics"]["task_cycle"]["success_rate"] is None
```

- [x] **Step 2: Run tests and confirm the module/import is missing**

Run: `.venv/bin/pytest -q tests/unit/test_manipulation_runtime_view.py`

- [x] **Step 3: Implement the pure view builder with fixed result/metrics schemas**

Map actual execution, leases/preflight, completion steps, terminal result, task cycle, grasp summary, freshness, and provenance. Missing values remain explicit states, never synthesized numbers.

- [x] **Step 4: Attach `runtime_view` to snapshot, history, sample, state, and terminal artifact WebSocket packets**

Use the existing session/log observer and controller snapshot. No new device acquisition or background polling loop is introduced.

- [x] **Step 5: Run unit and API integration tests**

Run: `.venv/bin/pytest -q tests/unit/test_manipulation_runtime_view.py tests/integration/test_live_gui_runtime_layout.py -k 'manipulation_runtime or joint_telemetry'`

### Task 3: Fixed Runtime Cards and Donuts

**Files:**
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Modify: `web/frontend/omx_telemetry_viewer/src/index.js`
- Regenerate: `web/static/omx_telemetry_viewer.bundle.js`
- Modify: `web/templates/planning.html`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`
- Modify: `tests/unit/test_omx_telemetry_viewer_lifecycle.py`

**Interfaces:**
- Consumes: `runtime_view` from snapshot/WebSocket packets.
- Produces: fixed cards with `data-atr-runtime-*` hooks and in-place patch functions.

- [x] **Step 1: Add failing browser contract tests for all eight fixed cards and two donuts**

Assert the conceptual card titles are absent from the manipulation renderer and the runtime card hooks are always emitted.

- [x] **Step 2: Run focused tests and confirm the new hooks are absent**

Run: `.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py -k manipulation`

- [x] **Step 3: Replace both conceptual and legacy manipulation branches with one fixed renderer**

Keep `Live Robot Pose`, `Policy Tracking`, and compact `Runtime State Strip`; append `Runtime Execution`, `Runtime Interlocks`, `Completion Verification`, `Run Result`, and `Run Metrics` unconditionally.

- [x] **Step 4: Implement runtime view patching and CSS donut visuals**

Use one DOM node per card/donut. For no attempts show `—`, `Attempts 0`, and `Completed 0`; update CSS `--rate` and count labels without chart reinitialization.

- [x] **Step 5: Build the local telemetry bundle and run frontend lifecycle tests**

Run: `npm --prefix web/frontend/omx_telemetry_viewer run build`

Run: `.venv/bin/pytest -q tests/unit/test_omx_telemetry_viewer_lifecycle.py tests/integration/test_live_gui_runtime_layout.py -k manipulation`

### Task 4: Full Regression and Documentation

**Files:**
- Modify: `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`
- Modify: `docs/superpowers/specs/2026-07-20-manipulation-live-runtime-grounded-cards-design.md` only if implementation details require clarification.

**Interfaces:**
- Consumes: completed backend/frontend implementation.
- Produces: verified runtime contract and operator-facing behavior documentation.

- [x] **Step 1: Add a five-cycle replay test with grasp retry and E-stop/Resume semantics**

- [x] **Step 2: Run all focused Manipulation/LeRobot/Live GUI tests**

Run: `.venv/bin/pytest -q tests/unit/test_lerobot_joint_telemetry.py tests/unit/test_manipulation_runtime_view.py tests/unit/test_omx_telemetry_viewer_lifecycle.py tests/integration/test_live_gui_runtime_layout.py`

- [x] **Step 3: Run JavaScript syntax and diff checks**

Run: `node --check web/static/planning.js && git diff --check`

- [x] **Step 4: Update the runtime guideline with task/grasp formulas, fixed-card behavior, and evidence sources**

- [x] **Step 5: Review the final diff and report test evidence without starting or stopping physical equipment**
