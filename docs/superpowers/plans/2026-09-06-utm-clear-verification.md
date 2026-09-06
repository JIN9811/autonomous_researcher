# UTM Clear Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Run the accepted UTM-clear replay after testing, verify the empty fixture, and retain two switchable verification snapshots before Analysis.

**Architecture:** Managed LeRobot replay is a second Manipulation task, with a scoped cycle state and a separate Vision verification result. Existing graph and controller paths consume the same handoff; the GUI projects both snapshots without overwriting either.

**Tech Stack:** Python, FastAPI, LeRobot, existing LangGraph routing, vanilla JavaScript, pytest and Node tests.

**Spec:** `docs/superpowers/specs/2026-09-06-utm-clear-verification-design.md`

## Global Constraints

- No hardware execution, dataset/calibration/CSV changes, server restart, commits, or push during implementation.
- Preserve the current checkout and all unrelated uncommitted changes.
- Keep first VLA transfer unchanged. Replay uses `jin/utm_clear`, episode 0, without hard-coded frame count.
- Same run/loop/specimen, distinct replay execution identity; no blind effectful retries.
- Bridge owns processes/ports/stop; Vision requires a valid fresh image for absence evidence.
- English UI text. Verification 1 and 2 stay independent and archived.
- Verification 2 must detect compressed residual specimens around 30 x 10 mm; approximate scale only, no fixed experimental geometry or false-clear on unavailable visual evidence.

### Task 1: Managed replay boundary

**Files:** `device_bridges/lerobot_bridge.py`, `mcp_tools/lerobot_tools.py`, the request model containing `LeRobotSessionRequest`, `app/main.py` replay routes only; create `scripts/lerobot_managed_replay.py` if required for bounded cleanup and measured end-pose evidence. Tests: `tests/unit/test_lerobot_replay.py`.

**Interfaces:** `LeRobotBridge.replay_start/status/stop(payload: dict) -> dict`; tools `lerobot.replay.start/status/stop`; payload carries existing session/profile/mode/confirm fields plus `dataset_repo_id`, `dataset_path`, `replay_episode` (default 0), `run_id`, `loop_id`, `specimen_id`. Status includes session_id, workflow=replay, status, ok, exit_code, dataset identity, log_path, and measured return evidence `replay_home_verified` (not inferred from exit code).

- [x] Write failing tests using a fake subprocess/device boundary and real bridge session machinery:

```python
assert bridge.replay_start(test_payload)["workflow"] == "replay"
assert bridge.replay_status({"session_id": sid})["session_id"] == sid
assert bridge.replay_stop({"session_id": sid})["status"] == "STOPPED"
```

- [x] Run `.venv/bin/pytest tests/unit/test_lerobot_replay.py -q`; confirm missing behavior fails.
- [x] Implement replay registration and request validation. Resolve local episode metadata; reject missing/incomplete dataset, invalid episode, active port occupant, missing live confirmation. Generate an argv list, never a shell string. Share existing session tracking, bounded process polling, stop/escalation, and global stop integration.
- [x] Ensure normal/failed/interrupted replay cleanup closes the follower; never rewrite calibration or limits. Read measured end position and compare against the recorded end observation with the existing home-tolerance policy. Unknown/missing evidence remains unverified.
- [x] Test nonzero exit, duplicate session start, active recording/rollout collision, explicit stop and global stop; inspect-only dataset reads. Re-run focused tests and existing affected bridge tests. Write a task report; no commit.

### Task 2: Same-cycle clear and Vision handoff

**Files:** `utils/utm_clear_cycle.py` (new scoped state/evidence helper), `agents/manipulation_agent.py`, `agents/vision_agent.py`, `graphs/configs/atr_closed_loop.yaml`, `graphs/schema.py` only if required, `app/controller.py`, `orchestrator/langgraph_runtime.py`, `utils/manipulation_execution.py`, `utils/utm_specimen_presence.py`, `mcp_tools/camera_tools.py`. Tests: `tests/unit/test_utm_clear_cycle.py` and focused presence/capture tests.

**Interfaces:** `run_metadata.utm_clear_execution` holds run_id, loop_id, specimen_id, session_id, state, success, task_id. `run_metadata.utm_verifications` holds current scope plus `verification_1` and `verification_2` records. Each record holds verification_index, status, confirmed, captured_at, artifact, and evidence; compact snapshots preserve both. Manipulation calls Task 1 replay tools; Vision calls existing `vision.utm_specimen_presence.capture` only after replay completion/return.

- [x] Write route tests with injected tools and real merge functions:

```python
assert next_after_successful_equipment == "manipulation"
assert task_id == "clear_utm_to_disposal"
assert next_after_clear_launch == "vision"
assert next_after_verified_empty_fixture == "analysis"
```

- [x] Run `.venv/bin/pytest tests/unit/test_utm_clear_cycle.py -q`; capture RED.
- [x] Add identity-scoped clear state on successful verified equipment handoff; do not key solely off an old equipment status or an agent return. Preserve preflight behavior and existing first-transfer routing. Use deterministic per-cycle child session ID to prevent repeated actuation.
- [x] Add the replay task branch without policy loading or grasp requirements (accepted motion is a sweep). Poll replay from Vision without blocking the GUI event loop. Require exit success and measured return before a fresh UTM snapshot; valid explicit absence confirms Verification 2. Capture failure/unknown/stale/present leaves it blocked/pending, never Analysis.
- [x] Inspect the existing UTM presence detector and calibrate/parameterize post-test residual detection for roughly 30 x 10 mm compressed profiles; test compressed-present and empty fixtures. Keep first placement detection unchanged; missing image/ROI/calibration evidence is not a confirmed clear.
- [x] Persist first and second image/decision records independently; reset by scope, preserve initial transfer execution evidence when clearing. Add normal-runtime and controller-tail route parity tests, stop/failure tests, and simulated non-actuating cycle tests. Write report; no commit.

### Task 3: Two-snapshot card and completion row

**Files:** `web/static/planning.js`, `web/static/styles.css`, `web/templates/planning.html`, `tests/js/utm_verification_tabs.test.cjs`, and relevant agent/bridge docs.

**Interfaces:** Consume `run_metadata.utm_verifications` from Task 2. Selector state is keyed by run/loop/specimen; selected record supplies image, status, and title. `verification_1` remains the existing placement image; `verification_2` is the new clearance image. Missing data yields Pending, not a fallback to the other image.

- [x] Write failing renderer/interaction tests:

```javascript
assert.match(rendered, /Verification 1/);
assert.match(rendered, /Verification 2/);
assert.equal(selectVerification(scope, 2).status, "pending");
```

- [x] Run `node --test tests/js/utm_verification_tabs.test.cjs`; capture RED.
- [x] Add header-right selectors with accessible selected state, fixed card layout, and retained selection on polling. New run/loop resets selection. Add exactly one final Completion Verification row, derived from the clear execution and Verification 2, never raw process exit.
- [x] Re-run JS lifecycle suites, backend cycle tests, `node --check`, `git diff --check`. Document route, replay stop ownership, artifacts and verification meanings. Review all changes; no device run or commit.

## Integration validation

- [x] Non-actuating composed fixtures verify initial transfer separately, then current Equipment → clear → empty-fixture Vision → Analysis routing with recorded Verification 1; no second Equipment execution. This is software boundary/route coverage, not one physical end-to-end run.
- [x] Preserve CSV bytes/hash and original recording. Review exact changed files against the approved spec.
- [x] Report fresh test counts and server-restart requirement separately from code completion.
