# Native Joint Telemetry And Motion State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display LeRobot-native policy tracking over a bounded full-session timeline and visualize measured/policy robot motion states.

**Architecture:** Extend the read-only telemetry packet with native source mappings and temporal annotations while retaining the Isaac degree/radian fields. Render native values in the ECharts card, compact history across the complete time domain, and add one telemetry-driven state card in the existing Manipulation Agent dashboard.

**Tech Stack:** Python 3.12, FastAPI, pytest, JavaScript, ECharts, Three.js, esbuild.

## Global Constraints

- Do not change robot control, rollout, policy inference, serial access, or Isaac pose behavior.
- Use only existing action-log artifacts as input.
- Home dwell is 0.5 seconds.
- Measured Home ranges are `Joint1 [-15,-6.5]`, `Joint2 [-61,-53]`, `Joint3 [52,61]`, `Joint4 [43,52]`, `Joint5 [-11,-3]`, `Gripper [55,65]` in LeRobot-native units.
- Policy Home uses the same ranges except `Joint2 [-72,-65]` in requested-action space because the follower motor-2 limit shifts measured feedback away from the requested target.
- Browser display history is bounded at 1200 points and preserves the complete visible time span.

---

### Task 1: Native Telemetry Contract And State Classifier

**Files:**
- Modify: `utils/lerobot_joint_telemetry.py`
- Test: `tests/unit/test_lerobot_joint_telemetry.py`

**Interfaces:**
- Consumes: action-log events containing `latest_observation`, `requested_action`, and `sent_action`.
- Produces: `actual_source`, `target_source`, `applied_target_source`, and `motion_state` in each packet.

- [x] **Step 1: Write failing tests**

Add tests asserting native mappings are not converted and temporal sequences classify `home`, `moving`, `holding`, `grasping`, and `ungrasping` independently for measured and policy channels.

- [x] **Step 2: Verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_lerobot_joint_telemetry.py`

Expected: failures for missing source fields and motion-state annotations.

- [x] **Step 3: Implement the minimal classifier**

Add immutable home ranges, source-key mapping, a bounded temporal annotator, and packet fields without modifying existing degree/radian fields.

- [x] **Step 4: Verify GREEN**

Run: `.venv/bin/pytest -q tests/unit/test_lerobot_joint_telemetry.py`

Expected: all tests pass.

### Task 2: Native Artifact Figure

**Files:**
- Modify: `utils/lerobot_joint_telemetry.py`
- Test: `tests/unit/test_lerobot_joint_telemetry.py`

**Interfaces:**
- Consumes: packets from Task 1.
- Produces: native-value `policy_tracking.png` and source-unit metrics in `policy_tracking_summary.json` while preserving existing compatibility metrics.

- [x] **Step 1: Write a failing artifact test**

Assert the summary records `value_space=lerobot_native`, source metrics, and the expected native source range.

- [x] **Step 2: Verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_lerobot_joint_telemetry.py -k artifact`

Expected: failure because native artifact metadata is absent.

- [x] **Step 3: Implement native artifact plotting**

Plot `actual_source` and `target_source`, update axis labels, and add source metrics without removing degree metrics consumed elsewhere.

- [x] **Step 4: Verify GREEN**

Run: `.venv/bin/pytest -q tests/unit/test_lerobot_joint_telemetry.py -k artifact`

Expected: all selected tests pass.

### Task 3: Full-Timeline Chart And Motion-State Card

**Files:**
- Modify: `web/static/planning.js`
- Modify: `web/frontend/omx_telemetry_viewer/src/index.js`
- Modify: `web/static/styles.css`
- Regenerate: `web/static/omx_telemetry_viewer.bundle.js`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: native source fields and `motion_state` from Task 1.
- Produces: native ECharts series, bounded full-span compaction, stable Y domains, and the `Robot Motion State` card.

- [x] **Step 1: Write failing static/integration tests**

Require state-card hooks, native source fields, progressive history compaction, normalized X values, stable Y-domain logic, and native labels in the served assets.

- [x] **Step 2: Verify RED**

Run: `.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'pose_and_policy_tracking or joint_telemetry'`

Expected: failure for missing state card and native chart behavior.

- [x] **Step 3: Implement the card and chart behavior**

Render measured/policy state segments and Home Gate details in `planning.js`; update the source frontend to compact history across the full span, normalize X to zero, and maintain monotonic Y domains.

- [x] **Step 4: Rebuild the local bundle**

Run: `npm run build --prefix web/frontend/omx_telemetry_viewer`

Expected: `web/static/omx_telemetry_viewer.bundle.js` is regenerated successfully.

- [x] **Step 5: Verify GREEN**

Run: `.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'pose_and_policy_tracking or joint_telemetry'`

Expected: all selected tests pass.

### Task 4: Browser And Regression Verification

**Files:**
- Modify if required by observed behavior: `tests/ui/live_runtime_ide_browser_audit.py`
- Modify: `docs/superpowers/specs/2026-07-14-native-joint-telemetry-motion-state-design.md`

**Interfaces:**
- Consumes: served Live GUI and a recorded rollout action log.
- Produces: browser screenshots and test evidence without robot access.

- [x] **Step 1: Run focused regressions**

Run: `.venv/bin/pytest -q tests/unit/test_lerobot_joint_telemetry.py tests/integration/test_live_gui_runtime_layout.py -k 'joint_telemetry or pose_and_policy_tracking'`

Expected: all selected tests pass.

- [x] **Step 2: Exercise the Live GUI in a browser**

Open `/live`, select the Manipulation Agent report, verify Gripper displays approximately 60 rather than 36, confirm the chart begins at X=0, and confirm the state card contains measured, policy, and Home Gate sections.

- [x] **Step 3: Verify no control-path changes**

Run: `git diff -- device_bridges/lerobot_bridge.py mcp_tools/lerobot_tools.py`

Expected: no new changes from this implementation.

- [x] **Step 4: Update runtime documentation**

Document the native telemetry value space, state semantics, and chart compaction behavior in the design spec and relevant GUI documentation.

### Task 5: Unified Dual-Glow Motion Track

**Files:**
- Modify: `utils/lerobot_joint_telemetry.py`
- Modify: `web/static/planning.js`
- Modify: `web/frontend/omx_telemetry_viewer/src/index.js`
- Modify: `web/static/styles.css`
- Test: `tests/unit/test_lerobot_joint_telemetry.py`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: measured and policy temporal telemetry annotations.
- Produces: simultaneous `base_state` and `gripper_state` fields plus one shared white/cyan state track.

- [x] **Step 1: Add failing orthogonal-state and unified-card tests**
- [x] **Step 2: Verify failures for missing split-state fields and merged-card hooks**
- [x] **Step 3: Split arm and gripper classification while retaining legacy state fields**
- [x] **Step 4: Replace two state panels with one dual-glow five-state track**
- [x] **Step 5: Rebuild the local telemetry bundle and run focused regressions**

### Task 6: Recorded-Motion Threshold Stabilization

**Files:**
- Modify: `utils/lerobot_joint_telemetry.py`
- Modify: `tests/unit/test_lerobot_joint_telemetry.py`
- Modify: `docs/gui/gui.md`
- Modify: `docs/agents/manipulation_pi05_transfer_runtime_guideline.txt`

**Interfaces:**
- Consumes: the existing per-channel native joint history and the prior latched
  state held by `MotionStateAnnotator`.
- Produces: the existing `motion_state.measured` and `motion_state.policy`
  schemas with stable state transitions; no control-path or packet-schema
  changes.

- [x] **Step 1: Add failing tests for Joint1 Home tolerance, arm enter/exit hysteresis, and gripper enter/exit hysteresis**
- [x] **Step 2: Run the focused unit tests and confirm they fail under the single-threshold classifier**
- [x] **Step 3: Add independent measured/policy latches with arm `4.0/2.0/0.3 s`, gripper `2.0/0.5/0.2 s`, and Home `0.5 s` behavior**
- [x] **Step 4: Run focused and integration regressions**
- [x] **Step 5: Replay the recorded rollout offline and confirm one grasp, one ungrasp, stable Home, and reduced short Moving segments**
- [x] **Step 6: Record the stabilized runtime contract in the GUI and Manipulation Agent documentation**

### Task 7: Channel-Specific Motor-2 Home Criteria

**Files:**
- Modify: `utils/lerobot_joint_telemetry.py`
- Modify: `tests/unit/test_lerobot_joint_telemetry.py`
- Modify: `docs/gui/gui.md`
- Modify: `docs/agents/manipulation_pi05_transfer_runtime_guideline.txt`

**Interfaces:**
- Measured classification consumes `actual_source` with measured Home Joint2
  `[-61,-53]`.
- Policy classification consumes `target_source` with requested Home Joint2
  `[-72,-65]`.
- Other joint ranges, hysteresis, packet schema, and control paths remain
  unchanged.

- [x] **Step 1: Derive the stable policy Joint2 range from recorded rollouts**
- [x] **Step 2: Add and verify a failing test for distinct measured/policy Home poses**
- [x] **Step 3: Pass the matching range table into each channel classifier**
- [x] **Step 4: Run unit regressions and replay both recorded rollouts offline**
- [x] **Step 5: Document the channel-specific Home contract**
