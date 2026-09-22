# Optional OMX MoveJ downstream control

Status: proposed design, awaiting written-spec review. Not implemented or enabled.

## Agreed intent

Add an optional ROBOTIS Cyclo MoveJ controller downstream of VLA inference.
This is not home recovery, motion planning, or a change to the trained policy.
The policy retains its original observation rate, action-chunk schedule, and
gripper timing. A separate downstream control loop targets 100 Hz.

Both the standalone Inference panel and Manipulation Agent Bridge expose one
English checkbox, `MoveJ control (100 Hz)`, and use the same execution path.
Standalone defaults to OFF; explicitly saved standalone choices survive reload.
The agent uses its selected task's saved configuration. Missing fields in old
profiles mean OFF. Changes apply only to a new session after the current one
has stopped. An ON-path failure must not silently switch to direct control.

## Current code and constraints

- Standalone API and agent tool execution converge on
  `device_bridges/lerobot/bridge.py:LeRobotBridge.rollout_start`.
- Typed transport is in `mcp_tools/lerobot_schemas.py` and `app/main.py`;
  saved profiles are normalized by `utils/lerobot_rollout_profile.py` and
  `utils/manipulation_profile.py`.
- Standalone profile loading can currently inherit a Manipulation profile.
  The new MoveJ field must be excluded from that implicit migration: an agent
  ON setting must not enable an unsaved standalone session.
- `scripts/lerobot_omx_runtime_units_patch.py` uses degrees for shoulder pan and
  wrist roll, range [-100, 100] for three arm joints, and [0, 100] for the gripper.
  These are not Cyclo/URDF joint coordinates. Conversion must use the actual
  motor calibration, robot model conventions, signs, offsets and joint names.
- `OmxFollower.get_observation` and `send_action` currently access the serial
  bus directly. Adding a second ROS hardware driver would create competing
  ownership and may change hardware configuration.
- ROS Jazzy exists on this host; the default sourced ROS environment did not
  list Cyclo or OpenManipulator packages during inspection. This is not proof
  that no other workspace exists. Dependency availability is a preflight check.
- Existing scene-pad and recording-UI changes are unrelated and must survive.
  The previously reverted automatic-recovery feature stays unapplied.

## Architecture decision

Recommended: keep the existing LeRobot hardware semantics, but give the ON path
a dedicated single-owner IO worker and an isolated native Cyclo sidecar. The
policy-facing adapter submits targets and receives measured joint snapshots;
it never opens a competing motor port. Native Cyclo handles its QP in a separate
process, without requiring ROS Python libraries inside the policy's Python 3.10
environment. OFF continues through the existing driver and wrappers unchanged.

Alternatives considered:

1. ROS/OpenManipulator becomes the entire ON-path hardware backend. This is
   possible but also changes motor-driver initialization and the observation
   source; not selected for the initial integration.
2. A Python interpolator called MoveJ. This is smaller but is not the requested
   ROBOTIS controller and does not provide its QP constraints; rejected.

Logical ON path:

`existing policy/action scheduler -> shared adapter -> Cyclo MoveJ -> IO worker -> motors`

Measured joints return through the IO worker to both the policy adapter and
Cyclo. Camera ownership remains with the existing inference process. The IO
worker must not read cameras, run policy inference, or depend on web polling.

All components belong to the existing LeRobot rollout session and bridge.
No second experiment scheduler, recovery loop, or independently admitted motor
API is introduced. Existing stop, E-stop, execution gates, task identities and
Vision-based completion/handoff remain authoritative.

## Configuration and UI contract

Canonical field: `rollout_movej_enabled: bool = false`.

- Carry the field through request validation, profile save/load, per-task
  snapshots, agent payload building, bridge admission and session metadata.
- Preserve explicit false values; do not use truthy `or` chains for precedence.
- Standalone explicit request/saved profile is separate from agent defaults.
- Agent selected-task configuration resolves before admission; freeze that
  result for the session. The LLM cannot enable this physical-control option.
- Both checkboxes have the same label and next-session semantics. Saving or
  refreshing the page never modifies an active controller.
- The initial GUI exposes no tuning sliders. Controller frequency is 100 Hz;
  technical limits and watchdog settings live in validated bridge configuration.
- Report requested backend, effective backend, readiness and actual measured
  output frequency separately. A checked box is not execution evidence.
- Initially support the commissioned OMX physical policy-rollout backend only.
  Unsupported robot/backend combinations with ON are rejected explicitly.
  OFF must not change replay, recording, teleoperation, training or Isaac paths.

## Timing and control contract

- Reuse the existing policy action scheduler. Do not drain an entire predicted
  chunk immediately and do not increase policy inference or camera FPS.
- Feed scheduled joint targets to Cyclo's streaming-target input, rather than
  restarting a long timed motion for every action. The inspected OMX node reads
  only `points.front()`, so a multi-point chunk cannot be sent as one trajectory.
- Carry session ID, increasing sequence, source-observation time, intended action
  time and expiry through the target adapter. Reject foreign, out-of-order,
  non-finite, incomplete and expired commands. Never replay a backlog on recovery.
- Fresh action chunks can cover ongoing inference latency; a repeated heartbeat
  alone cannot renew an exhausted chunk or stale observation's validity.
- Tick the low-level controller at 10 ms. Measure actual IO writes, feedback age,
  scheduling jitter and deadline misses independently of ROS publish frequency.
  Ordinary Linux scheduling is not a hard-real-time guarantee.
- Validate all arm coordinate conversions with raw encoder fixtures and FK
  comparisons. Handle extended-position joints without accidental angle wrapping.
  Handle gripper coordinates separately; do not treat percent opening as radians
  or meters. Preserve its scheduled open/close timing and existing limits.
- Preserve current clamps/backstops in their original units and meaning. Do not
  silently multiply a per-action relative limit by executing it at 100 Hz.
- Log VLA requested, controller-filtered, actually written and measured targets
  distinctly. A queued policy target is not an already applied motor command.

## Fault behavior and ownership

- Load optional controller code and launch workers only for ON. Preflight model,
  units, dependencies, configuration and ownership before admitting robot motion.
- Use private session-scoped controller transport, not an unqualified global
  `/leader/joint_trajectory` that another publisher could drive.
- One worker owns all serial reads/writes; policy/camera threads never share or
  reopen that bus. No automatic ROS hardware bringup or startup home movement.
- Seed the ON controller from fresh measured joints, without issuing a target
  jump. Validate the upstream commanded-state integration against feedback;
  excessive tracking error must stop progression, not be interpreted as arrival.
- IO and target watchdogs are independent of the web server and inference thread.
  Validate explicit timing limits in configuration and record the resolved values.
  Missing feedback, expired commands, QP failure, controller/worker death or an
  unsafe target latches a fault and cancels further progression.
- With valid communication and fresh measured state, the controlled fault path
  holds the measured pose; it does not open the gripper or command home. If IO
  itself is lost, report physical state as unknown and require intervention.
  Do not claim software can guarantee a hold after communication/power loss.
- Existing E-stop/hardware stop takes priority. No automatic restart, retry,
  direct fallback or torque-disable policy change is introduced.
- Confirm owned worker termination and port release before allowing another
  session. Refresh and status recovery must not report IDLE merely because the
  web process lost its in-memory session object.

## Modularity, records and documentation

The agent owns task intent and saved configuration; the bridge owns backend
selection, workers, admission, device IO and fault receipts. Extend the existing
module/package declarations and Runtime IDE references for actual owned symbols,
without adding an executable orchestration stage or claiming successful motion.

Archive a resolved configuration snapshot, controller/model revision, mapping
and calibration hashes, target/applied/feedback streams, timing summaries and
terminal reason under the existing rollout session/run artifact identity. Keep
buffers bounded and use existing artifact references; do not stream raw 100 Hz
records into every GUI state update.

Update the bridge/operator and Manipulation docs in English when implemented.
Explain OFF behavior, next-session switching, dependency errors, measured versus
requested frequency, and that self-collision constraints do not automatically
model the platen, bench, held specimen or human obstacles.

## Verification and release gates

1. Configuration tests: missing/false/true, save/reload, task switching, invalid
   values, explicit false precedence and no standalone inheritance from agent ON.
2. Shared-route tests: standalone API and agent tool produce the same backend
   request; current session settings remain immutable.
3. OFF regression: original command/env/driver path, camera rate, policy scheduling,
   clamps and gripper behavior unchanged; no Cyclo imports/processes/ROS traffic.
4. Non-actuating integration: fake hardware with the real controller where
   available, unit round trips, chunk timing, stop, stale targets/feedback, QP
   failures, worker death, port contention and bounded buffers.
5. Dependency isolation: missing Cyclo rejects ON with an actionable error while
   OFF remains usable; no modification to installed policy dependencies.
6. Recorded-data/shadow comparison: compare direct and filtered targets using
   saved observations/actions without connecting hardware. Report errors and
   timing rather than assuming improved smoothness or policy success.
7. Separately approved supervised commissioning: verify motor-side frequency,
   coordinate mapping, controller tracking and stop behavior before full task A/B
   tests. Do not label the controller physically validated from mocks or a 100 Hz
   timer alone. Deployment stays OFF by default until explicitly selected.

No server restart, installation, real robot execution or experiment resumption
is part of this design-review step.

## Source references

- Local base inspected: `c173fb3` plus the six unrelated pre-existing dirty files.
- ROBOTIS Cyclo reference revision: `f94efd39c64d239a47096f106ca917bea063f07d`.
- [OMX controller](https://github.com/ROBOTIS-GIT/cyclo_control/blob/f94efd39c64d239a47096f106ca917bea063f07d/cyclo_motion_controller_ros/src/nodes/omx/omx_movej_controller_node.cpp)
- [OMX configuration](https://github.com/ROBOTIS-GIT/cyclo_control/blob/f94efd39c64d239a47096f106ca917bea063f07d/cyclo_motion_controller_ros/config/omx_config.yaml)
- [Three-level ownership](../../runtime/three_level_control_model.md)
- [Manipulation agent](../../agents/manipulation_agent.md)
- [Runtime IDE](../../runtime/runtime_ide.md)
