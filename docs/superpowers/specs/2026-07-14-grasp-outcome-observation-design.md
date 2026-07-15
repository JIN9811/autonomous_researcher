# Grasp Outcome Observation Design

## Goal

Classify each physical grasp attempt as `pending`, `success`, or `failed` from
the existing LeRobot action log, show the result in the Manipulation Agent
telemetry card, and persist deterministic per-attempt evidence for later
success-rate analysis without changing the VLA control loop.

## Constraints

- Read only `actual_source`, `target_source`, and the existing measured motion
  annotation.
- Do not stop, pause, retry, or modify rollout execution.
- Do not send MotorBus, Dynamixel, camera, or policy commands.
- Do not promote this observational result into a Guardian blocker.
- Preserve the current measured/policy Home ranges and state hysteresis.
- Keep the packet additive so existing telemetry consumers remain compatible.

## Evidence Basis

Session `lr-rollout-20260714T110039768051Z-0001` contains four
operator-labelled attempts: success, failure, success, success.

During carry, policy Gripper targets were nearly identical at approximately
`50.0`. Successful attempts retained a positive measured-minus-policy contact
gap of `3.162` through `3.887`, while the failed attempt reached the target and
had a gap of `-0.118`. The failed attempt also began arm transport `0.803 s`
before measured grasp completion; the successful attempts began transport
`0.068` through `1.787 s` after completion.

These observations define a provisional, apparatus-specific threshold. They
do not establish a universal grasp metric for other grippers or specimens.

## State Contract

Each telemetry packet adds `motion_state.grasp_outcome`:

```json
{
  "status": "idle | pending | success | failed",
  "reason": "operator-facing explanation",
  "attempt_index": 4,
  "observation_only": true,
  "contact_gap": 3.42,
  "contact_gap_threshold": 2.0,
  "measured_gripper": 53.55,
  "policy_target_gripper": 50.13,
  "transport_overlap": false,
  "started_s": 138.58,
  "completed_s": 140.11
}
```

The values are LeRobot-native values. `contact_gap` is always:

```text
measured follower Gripper - policy target Gripper
```

## Transition Rules

1. Start a new attempt when measured `gripper_state` enters `grasping`.
2. Set the result to `pending` and clear evidence from the previous attempt.
3. While the attempt is active, record `transport_overlap=true` if measured
   arm `base_state` becomes `moving` before measured grasping has completed.
4. Finalize when measured `gripper_state` transitions from `grasping` to
   `idle`. Existing gripper hysteresis already requires a stable exit dwell.
5. Set `success` only when `contact_gap >= 2.0` and no transport overlap was
   observed.
6. Set `failed` when `contact_gap < 2.0` or transport overlap was observed.
7. Keep the finalized result visible until the next measured grasp attempt.
8. `ungrasping` does not erase the last result.
9. Missing measured or policy Gripper values keep the attempt `pending`; they
   do not fabricate a failure.

The outcome is descriptive. No branch in the rollout control path may consume
it as an execution gate.

## Persisted Outcome Artifact

When a rollout reaches a terminal status, artifact finalization replays the
existing `motor_events.jsonl` once and writes
`runs/lerobot_action_logs/<session_id>/grasp_outcomes.json`.

The artifact uses schema `atr.grasp_outcomes.v1` and contains:

- session id, mode, profile id, source log path, and source log size/mtime;
- the contact-gap threshold and transition-rule version;
- one ordered record per grasp attempt with start/completion time, status,
  reason, measured value, policy target, contact gap, and transport overlap;
- `total_attempts`, `completed_attempts`, `success_count`, `failed_count`, and
  `pending_count`;
- `success_rate`, calculated as
  `success_count / (success_count + failed_count)`.

`pending` attempts are excluded from the success-rate denominator. If no
attempt is complete, `success_rate` is `null` rather than zero.

The same aggregate is referenced from `policy_tracking_summary.json`, while
the dedicated artifact preserves the attempt-level evidence. Artifact
generation is deterministic and overwrites the derived file for the same
source log instead of appending from every browser/WebSocket consumer; this
prevents duplicate attempts during replay or page refresh.

## Runtime Placement

`MotionStateAnnotator` owns one grasp-attempt latch in addition to the existing
measured and policy motion latches. It computes the outcome after both channel
annotations for the current packet are available.

During a live stream the frontend reads `motion_state.grasp_outcome`. A
terminal `telemetry_artifacts` packet also carries `latest_grasp_outcome` so a
page refresh can restore the last result without replaying the entire raw log
in the browser. No additional polling loop or device connection is introduced.

## Aggregate API Contract

Expose `GET /api/lerobot/grasp-outcomes` as the read-only boundary for a later,
separate success-rate card. The route selects the same current/latest rollout
session as joint telemetry, finalizes the deterministic artifact when possible,
and returns:

```json
{
  "ok": true,
  "schema": "atr.grasp_outcomes.v1",
  "status": "idle | live | complete | failed",
  "session": {},
  "attempts": [],
  "summary": {
    "total_attempts": 0,
    "completed_attempts": 0,
    "success_count": 0,
    "failed_count": 0,
    "pending_count": 0,
    "success_rate": null
  },
  "artifact_path": "",
  "artifact_url": ""
}
```

An absent rollout is a successful `idle` response with empty attempts, not an
HTTP error. This task only establishes the API and persisted aggregate. It does
not add a success-rate card or show aggregate success rate in the existing
Robot Motion State card.

## Live GUI

Add a compact `Grasp Result` strip inside the existing `Robot Motion State`
card:

- `idle`: muted gray
- `pending`: amber
- `success`: green
- `failed`: red

The strip shows the status, measured Gripper, policy target, contact gap,
required gap, and whether arm transport overlapped the grasp. It must remain a
single compact section rather than a new dashboard card.

The strip shows only the current/latest attempt. Aggregate counts and success
rate are intentionally reserved for a separate future card consuming
`GET /api/lerobot/grasp-outcomes`.

## Verification

- Unit tests cover pending, contact-gap success, low-gap failure, transport
  overlap failure, missing target data, and persistence through ungrasping.
- Offline replay of the labelled session must produce, in order:
  `success`, `failed`, `success`, `success`.
- The persisted artifact for that replay must report four completed attempts,
  three successes, one failure, zero pending attempts, and success rate `0.75`.
- Integration/static tests require the compact result strip and all four
  status tones.
- Existing telemetry and Live GUI tests must remain green.
- Verification must confirm there are no changes to rollout, MotorBus, or
  LeRobot command construction.
