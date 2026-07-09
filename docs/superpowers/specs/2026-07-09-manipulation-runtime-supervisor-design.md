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
- LeRobot bridge status includes port lease, camera lease, policy runtime, and Rerun telemetry blocks.
- Rerun unavailable does not fail the whole manipulation workflow.

Integration tests:

- Test mode completes with fake bridge telemetry.
- Live GUI test mode renders Manipulation Agent cards without policy-specific titles.
- LeRobot GUI bridge buttons call the same backend status contract used by Live GUI.
- Stop rollout is idempotent and updates both bridge and GUI state.

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
- The GUI no longer names the card after SmolVLA, Pi0.5, or SARM.
- Current policy type remains visible as metadata.
- Rerun viewer remains openable, but its important runtime elements are represented as native cards.
- Vision Agent completion can stop active inference.
- Existing Guardian compatibility is preserved through the `sarm` alias.
