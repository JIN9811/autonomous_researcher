# Manipulation Runtime Supervisor Design

## Objective

Upgrade the Manipulation Agent from a policy-specific rollout launcher into a robot execution supervisor that can safely coordinate LeRobot policy inference, robot/camera port ownership, Rerun telemetry, Vision Agent completion signals, and runtime interlocks.

The GUI must not present the current policy name, such as SmolVLA or Pi0.5, as the primary card identity. Policy type is a runtime detail. The user-facing unit is the Manipulation Agent.

## Current Constraints

- The existing LeRobot bridge already owns teleoperation, recording, rollout, status, stale process cleanup, camera preflight, saved port profiles, and Rerun viewer PID/URL detection.
- The Manipulation Agent already delegates LeRobot policies through `lerobot.rollout.start`.
- The Vision Agent already produces readiness fields such as `camera_returned_to_vla`.
- Guardian and existing tests still consume SARM-shaped fields. Removing SARM outright would break compatibility.
- Rerun viewer embedding alone is not sufficient. The operator needs Rerun-derived runtime elements as native cards in the Live GUI and LeRobot GUI.

## Scope

In scope:

- Port occupancy detection and reclaim/re-acquire attempt for follower/leader devices.
- Active camera lease state and inference collision prevention.
- Rerun telemetry summarized into cards instead of only opening the viewer.
- Manipulation Agent bridge panel aligned with actual runtime state.
- Vision Agent completion signal stops inference/rollout.
- Home pose and interlock status for standby/inference readiness.
- SARM UI removal with backend compatibility alias.

Out of scope for this pass:

- Replacing LeRobot internals.
- Replacing Rerun with a custom viewer.
- Removing the legacy `sarm` key from Guardian and historical test contracts.
- Training-policy-specific GUI branding.

## Runtime Model

The Manipulation Agent owns the high-level execution state:

```text
IDLE
  -> PREFLIGHT
  -> PORT_LEASE_READY
  -> CAMERA_LEASE_READY
  -> HOME_POSE_READY
  -> POLICY_RUNNING
  -> VISION_COMPLETION_WAIT
  -> STOPPING_POLICY
  -> COMPLETE
```

Failure states:

```text
BLOCKED_PORT
BLOCKED_CAMERA_LEASE
BLOCKED_HOME_POSE
POLICY_FAILED
VISION_TIMEOUT
STOP_FAILED
INTERLOCKED
```

## Backend Components

### LeRobot Bridge Runtime Status

Extend the existing bridge status response rather than adding a separate runner.

Required status blocks:

- `port_lease`
  - follower saved port
  - leader saved port
  - current availability
  - occupant process if discoverable
  - reclaim attempt result

- `active_camera_lease`
  - owner: `idle`, `vision`, `recording`, `rollout`, `unknown`
  - camera key and physical path/serial
  - returned to VLA: boolean
  - conflict reason if blocked

- `policy_runtime`
  - policy type
  - session id
  - pid
  - status
  - action rate if available
  - latency if available
  - log path
  - fatal marker if detected

- `rerun_telemetry`
  - viewer process pid
  - viewer URL
  - websocket URL if available
  - `.rrd` path if saved
  - stream keys observed from command/session metadata
  - latest frame artifact if extractable

- `home_pose`
  - available/unavailable
  - in home pose boolean
  - joint deltas if available
  - interlock reason

Implementation status:

- `LeRobotBridge._session_response()` now emits the runtime status blocks above for rollout-capable sessions.
- Live port preflight block responses also emit `port_lease` with blocked/missing/unavailable role details so the GUI does not lose bridge state on failure.
- `ManipulationAgent` normalizes bridge output into the same top-level `manipulation_report.v1` fields so Live GUI and LeRobot GUI consume one contract.
- `policy_runtime` is also embedded under `rollout_runtime.policy_runtime` for compatibility with existing rollout cards.
- `rerun_telemetry` is reported as `available`, `waiting`, or `disabled`; policy rollout is allowed to continue if Rerun evidence is unavailable.
- `home_pose` reads the configured Active Robot-Cam home pose target file when available. Test/virtual sessions report deterministic `ready`; live sessions report `interlock` until a measured current-pose probe supplies joint deltas.
- Direct bridge tests cover `rollout_start()` returning `port_lease`, `active_camera_lease`, `policy_runtime`, `rerun_telemetry`, and `home_pose`.

### Manipulation Agent Report

Canonical output:

- `execution_safety`
  - progress score
  - risk stage
  - precursor flag
  - recovery suggestion
  - interlock state

Compatibility output:

- `sarm`
  - alias to `execution_safety`
  - preserved until Guardian and tests are migrated

Policy naming rule:

- Card titles use neutral terms such as `Robot Policy Runtime`.
- Policy type appears only as a small metadata value.

### Manipulation Task Profile

The LeRobot GUI Manipulation Agent Bridge must not be a separate, incompatible policy form. It uses the same configuration pattern as `Inference / Rollout`:

- policy preset / existing policy selector
- policy type
- policy checkpoint or output file
- task instruction
- optional rollout duration
- safe action clamp and max relative target
- shoulder lift backstop
- ACT temporal ensemble controls
- Pi0.5 RTC controls
- observation / note JSON

The only additional operator-facing control is `Manipulation Task`. Each task owns a saved rollout-like profile under `task_profiles[task_id]`. Switching tasks loads that task profile; saving updates the selected task profile and persists it through `memory/manipulation_agent_bridge.json`.

Bridge-internal values such as source location, target location, strategy, and policy backend are derived from the selected Manipulation Task and should not clutter the visible form unless a future advanced mode explicitly exposes them.

### Vision Completion Handoff

The Vision Agent should emit a completion signal when it detects the specimen at the UTM/workholding target.

Required signal:

```json
{
  "schema": "vision_manipulation_completion.v1",
  "specimen_id": "...",
  "detected": true,
  "confidence": 0.0,
  "camera": "...",
  "timestamp": "...",
  "evidence_path": "...",
  "ready_to_stop_rollout": true
}
```

The Manipulation Agent consumes this signal and calls `lerobot.rollout.stop` idempotently. If stop fails, the report must mark `STOP_FAILED` and surface the log tail.

Implementation status:

- `ManipulationAgent` accepts the completion signal from `vision_manipulation_completion`, `manipulation_completion`, `completion_signal`, direct `vision_signal`, or `agent_signals`.
- A detected completion signal with `ready_to_stop_rollout=true` verifies the manipulation task and calls `lerobot.rollout.stop` once for the rollout session.
- Stop results are recorded in `manipulation.rollout_stop`, `robot_task_result.rollout_stop`, and `manipulation_report.rollout_stop`.
- Stop failures mark `failure_code=STOP_FAILED` and preserve `log_tail` in `rollout_runtime.log_tail`.

### Active-Cam to UTM Completion Loop

The production handoff loop is agent-driven, not a direct GUI-only sequence:

```text
Specimen Agent
  -> Vision Agent active-cam snapshot after ejection
  -> Manipulation Agent home-pose/interlock check
  -> LeRobot rollout / inference start
  -> Vision Agent UTM placement verification frame
  -> Manipulation Agent stop-only completion pass
  -> home-pose/interlock recheck
  -> Lab Equipment Agent
```

Runtime rules:

- The first Vision pass uses the active robot camera/pose snapshot to confirm the printed specimen is available for pickup and that the camera port is returned to the VLA route.
- The active robot camera check is single-shot for the post-ejection pickup pass. The post-manipulation verification pass must not reacquire the active camera because the VLA route already owns the camera for policy execution.
- When the Manipulation Agent reports `handoff_status=needs_post_place_vision` and `completion_status=reported_complete`, it also emits `requested_next_stage=vision` so the graph routes back to the Vision Agent.
- The graph keeps the default `manipulation -> equipment` path, but conditionally routes `manipulation -> vision` when `requested_next_stage=vision` is present.
- The second Vision pass captures `camera_key=utm` with `purpose=utm_placement_verification`, updates `utm_platen`, and emits `vision_manipulation_completion.v1`.
- The completion signal includes `detected`, `confidence`, `camera`, `evidence_path`, `ready_to_stop_rollout`, and `session_id` when available.
- The second Manipulation pass must not start a new rollout if an existing rollout session id is present. It performs a stop-only completion pass against the existing session and marks the task `verified_complete`.
- The stop-only completion pass promotes the stop response runtime contract, especially `home_pose`, so the final `manipulation_report.home_pose` represents the post-rollout home/interlock check rather than the pre-rollout check.
- After completion, `robot_task_result.handoff_status=ready_for_equipment` and the default graph transition moves to the Lab Equipment Agent.

Implementation status:

- `atr_closed_loop.yaml` contains a conditional logical transition for `manipulation -> vision` while preserving the default `manipulation -> equipment` transition.
- `VisionAgent` switches capture purpose from pickup verification to UTM placement verification when the previous manipulation result requests post-place vision.
- `ManipulationAgent` emits `requested_next_stage=vision` during the unverified handoff and consumes `vision_manipulation_completion.v1` without restarting inference when an existing rollout session is available.
- `tests/unit/test_manipulation_active_cam_loop.py` validates the full active-cam -> rollout -> UTM camera -> stop-only completion loop with post-stop home pose reflected in the final report.
- `LeRobotBridge` port lease diagnostics report open-file occupants from `/proc/*/fd` where the OS exposes them.

## GUI Design

### LeRobot GUI Manipulation Agent Bridge

Replace policy-specific wording with a compact bridge dashboard:

- `Bridge State`
- `Port Lease`
- `Active Camera`
- `Robot Policy Runtime`
- `Rerun Telemetry`
- `Vision Completion Gate`
- `Home Pose / Interlock`
- `Execution Safety`

Each card shows one-line status first. Details expand on click.

Configuration below the dashboard mirrors the existing `Inference / Rollout` section, with `Manipulation Task` added as the task selector. It should not use a separate `Use Rollout Settings` action because the bridge itself is the task-specific rollout configuration surface.

### Live GUI Manipulation Report

The Live GUI report card should show the same state hierarchy:

```text
Manipulation Runtime
READY / BLOCKED / RUNNING / COMPLETE

Port Lease        OK/BLOCKED
Active Camera     RETURNED/IN USE/BLOCKED
Home Pose         OK/UNKNOWN/BLOCKED
Policy Runtime    IDLE/RUNNING/FAILED
Vision Gate       WAITING/DETECTED/TIMEOUT
```

No `SARM` label appears in GUI. `Execution Safety` is used instead.

### Rerun Telemetry Cards

Rerun is treated as a telemetry source, not only as an external viewer.

Native cards:

- `Observation Preview`
  - latest RGB/depth thumbnail when available
  - if unavailable: `waiting for streamed frame`

- `Joint State`
  - current follower joint vector
  - policy action target
  - delta summary

- `Action Stream`
  - action rate
  - action queue depth
  - last action timestamp
  - clamp/filter status

- `Viewer Evidence`
  - viewer URL
  - PID
  - RRD path
  - log path
  - `Open Full Rerun Viewer` button

The GUI must not depend on DOM scraping the Rerun viewer. It should consume structured backend telemetry.

Implementation status:

- LeRobot Manipulation Agent Bridge and report rendering expose native cards for `Observation Preview`, `Joint State`, `Action Stream`, and `Viewer Evidence`.
- Cards read structured `rerun_telemetry` fields such as `latest_frame_artifact`, `joint_state`, `action_stream`, `action_rate_hz`, viewer URL, RRD path, and log path.
- Missing telemetry is rendered as `waiting` rather than blocking policy execution.

## Error Handling

- If a port is occupied, show the occupying process if available and attempt reclaim only when the workflow explicitly owns the stale session.
- If active camera is owned by Vision, block rollout until Vision returns it or marks a single-snapshot handoff complete.
- If Rerun is not available, policy execution can continue, but `Rerun Telemetry` shows degraded status.
- If home pose cannot be checked, default to warning/interlock in live mode and allow deterministic bypass only in test/virtual mode.
- Rollout stop is idempotent. Multiple stop calls should not create duplicate failures.

## Test Plan

Unit tests:

- Manipulation Agent emits `execution_safety` and legacy `sarm` alias.
- Manipulation Agent blocks when active camera lease is not returned.
- Manipulation Agent stops rollout when Vision completion signal is present.
- Manipulation Agent requests graph routing back to Vision after initial rollout completion.
- Manipulation Agent does not start a new rollout during the post-UTM Vision completion pass.
- Vision Agent emits `vision_manipulation_completion.v1` from UTM placement verification.
- LeRobot bridge status includes port lease, camera lease, policy runtime, and Rerun telemetry blocks.
- LeRobot bridge port lease reports discoverable port occupant processes.
- Rerun unavailable does not fail the whole manipulation workflow.

Integration tests:

- Test mode completes with fake bridge telemetry.
- Test mode follows the active-cam -> inference -> UTM verification -> stop-only completion route.
- Live GUI test mode renders Manipulation Agent cards without policy-specific titles.
- LeRobot GUI bridge buttons call the same backend status contract used by Live GUI.
- Stop rollout is idempotent and updates both bridge and GUI state.
- LeRobot GUI Manipulation Bridge saves and restores rollout-like settings independently per Manipulation Task.

Browser/UI tests:

- Manipulation cards expand/collapse without losing runtime state.
- Rerun telemetry card displays viewer URL/PID when available.
- Execution Safety appears, and `SARM` does not appear in visible GUI text.

## Migration Plan

1. Add backend status fields without removing old keys.
2. Add `execution_safety` while preserving `sarm` alias.
3. Update LeRobot GUI bridge panel labels and card layout.
4. Update Live GUI Manipulation Agent report cards.
5. Add tests around aliases, camera lease blocking, Vision completion stop, and Rerun telemetry.
6. After Guardian migration is complete in a later pass, remove direct `sarm` dependency.

## Acceptance Criteria

- The operator can see port lease, active camera, policy runtime, Vision gate, Rerun telemetry, home pose, and execution safety in Manipulation Agent cards.
- The Manipulation Agent Bridge configuration matches the Inference / Rollout configuration pattern, with only a Manipulation Task selector added.
- Each Manipulation Task can persist its own policy, instruction, duration, safety, RTC, and observation settings.
- The GUI no longer names the card after SmolVLA, Pi0.5, or SARM.
- Current policy type remains visible as metadata.
- Rerun viewer remains openable, but its important runtime elements are represented as native cards.
- Vision Agent completion can stop active inference.
- The graph can route from Manipulation back to Vision for UTM verification and then forward to Lab Equipment after verification.
- A verified UTM placement stops the existing rollout session without launching a duplicate rollout.
- Existing Guardian compatibility is preserved through the `sarm` alias.

## Implemented Joint Pose And Policy Tracking Extension (2026-07-13)

Two native cards now precede the existing Manipulation runtime cards:

1. `Live Robot Pose` renders the repository OMX MJCF/STL hierarchy. The measured follower is solid and the requested policy target is a translucent ghost.
2. `Policy Tracking` renders a selectable-joint measured-versus-target line plot with a white scientific figure field, explicit axis labels, and legend.

The extension is intentionally outside the execution loop. It tails `runs/lerobot_action_logs/<session_id>/motor_events.jsonl`, which is already emitted inside the established LeRobot rollout wrapper. It does not modify `lerobot.rollout.start`, policy action filtering, action rate, MotorBus ownership, Vision completion, home-pose gates, or stop semantics.

Runtime contract:

- snapshot: `GET /api/lerobot/joint-telemetry/snapshot`;
- stream: `WS /ws/lerobot/joint-telemetry`;
- model assets: `/assets/robotis-omx/omx.xml` and repository STL files;
- browser history: maximum 1200 samples;
- backend initial tail: maximum 2 MiB, with 1 MiB catch-up reads;
- terminal artifacts: `policy_tracking.png` and `policy_tracking_summary.json` beside the existing JSONL/CSV evidence.

The latest non-terminal rollout is selected before older terminal sessions. When no non-terminal rollout exists, the newest terminal session remains available so the operator can inspect the final pose, graph, and artifacts until a newer rollout begins.
