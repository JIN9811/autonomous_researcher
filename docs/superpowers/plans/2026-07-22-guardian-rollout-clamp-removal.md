# Guardian Rollout Clamp Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LeRobot rollout action clamp depend only on the GUI/profile value by removing Guardian warnings and payload overrides for this option.

**Architecture:** The GUI and Manipulation Agent continue to pass `rollout_action_clamp` to the shared LeRobot bridge. Guardian continues all other rollout safety checks but neither warns about nor mutates this field; the bridge remains the sole component that converts an enabled clamp into `--robot.max_relative_target`.

**Tech Stack:** Python, pytest, LangGraph runtime tool proxy, LeRobot device bridge

## Global Constraints

- Preserve all non-clamp Guardian safety checks.
- Do not change GUI, profile persistence, or LeRobot bridge behavior.
- Verify both explicit `false` and explicit `true` values pass through the Agent tool proxy unchanged.

---

### Task 1: Remove Guardian Ownership of Rollout Clamp

**Files:**
- Modify: `policies/guardian_gate.py`
- Test: `tests/unit/test_guardian_tool_shield.py`

**Interfaces:**
- Consumes: `ModuleToolRegistryProxy.call(name, payload)` and `guardian_gate(...)`
- Produces: An unchanged `rollout_action_clamp` value at the base LeRobot tool boundary

- [x] **Step 1: Change the regression test to require an explicit disabled clamp to pass through unchanged.**
- [x] **Step 2: Run the focused test and verify it fails against the current Guardian override.**
- [x] **Step 3: Remove `ROBOT_ACTION_CLAMP_DISABLED` alarms and the rollout clamp payload patch from Guardian.**
- [x] **Step 4: Add coverage confirming an enabled clamp also remains enabled.**
- [x] **Step 5: Run Guardian, tool-shield, Manipulation Agent, and LeRobot bridge tests.**
