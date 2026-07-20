# Vision Specimen Operator Retry Design

## Purpose

Prevent a missing specimen from terminating an otherwise healthy physical workflow. A missing specimen is an observable workspace condition, not a camera or runtime failure. The workflow must preserve the current run, show the captured evidence, allow bounded VLA recovery at the UTM checkpoint, and request operator placement only when automatic recovery is unavailable or exhausted.

## Scope

This design covers two Vision Agent checkpoints:

1. Active Robot Cam verification after specimen autoejection.
2. UTM placement verification after Manipulation Agent execution.

It does not change printer execution, autoejection G-code, policy selection, robot motion control, camera ownership rules, E-STOP semantics, or generic Guardian hardware-failure behavior.

## Core Distinction

The runtime must distinguish these outcomes:

| Outcome | Meaning | Runtime action |
| --- | --- | --- |
| `specimen_not_detected` | A fresh frame exists, camera operation succeeded, but no specimen was found | Recover or wait for operator placement |
| `camera_capture_failed` | No valid fresh frame was produced | Preserve existing Guardian safety handling |
| `camera_port_release_failed` | Camera was not returned to the required owner | Preserve existing Guardian safety handling |
| `runtime_failed` | Vision, robot, or policy runtime failed | Preserve existing retry and safety handling |

Only `specimen_not_detected` enters the operator-placement workflow.

## Runtime State Contract

The controller stores one run-scoped intervention record under `run_metadata`:

```json
{
  "schema": "vision_operator_intervention.v1",
  "run_id": "run-...",
  "checkpoint": "active_cam_ejection | utm_post_place",
  "status": "waiting_for_specimen | retrying | resolved | expired",
  "reason": "specimen_not_detected",
  "capture_path": "...",
  "capture_url": "...",
  "camera_key": "wrist | utm",
  "requested_at": "ISO-8601",
  "retry_started_at": "ISO-8601 or empty",
  "retry_deadline_at": "ISO-8601 or empty",
  "retry_count": 0,
  "rollout_session_id": "...",
  "rollout_stopped": false
}
```

The record is authoritative for the Live GUI. Historical successful evidence is not reused to resolve a new attempt. A new failed attempt replaces the visible checkpoint frame with that attempt's fresh frame and remains attached to the active run.

## Active Cam Ejection Flow

1. Vision Agent acquires the existing Active Robot Cam path and captures one fresh frame.
2. If the specimen is detected, the existing SPC confirmation and Manipulation handoff continue unchanged.
3. If the frame is valid but the specimen is absent:
   - Do not emit `ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED` as a terminal Guardian incident.
   - Do not transition Vision to `complete` or `error`.
   - Save the frame as run evidence.
   - Set the intervention checkpoint to `active_cam_ejection` and status to `waiting_for_specimen`.
   - Keep the Vision stage resumable without rerunning Design, Specimen Making, or printer execution.
4. The Live GUI shows the captured frame and a red action button labeled `Place the specimen into the working area`.
5. Pressing the button disables it, changes the status to `retrying`, and invokes a run-scoped Vision retry endpoint.
6. The retry uses the existing Active Robot Cam capture and port-return path. It does not use a frontend-only detector or a fallback camera path.
7. Detection resolves the intervention and proceeds to Manipulation. Another valid non-detection returns to `waiting_for_specimen` with the new frame.

## UTM Post-Place Flow

1. Manipulation continues to use the measured `ungrasping -> home` gate before requesting a UTM snapshot.
2. The first fresh UTM frame that does not contain the specimen starts a five-minute recovery window:
   - `retry_started_at` is the first non-detection timestamp.
   - `retry_deadline_at` is exactly five minutes later.
   - The VLA rollout remains active during this window so the policy can recover and try the task again.
3. Each later measured `ungrasping -> home` sequence requests another fresh UTM frame through the existing Vision path.
4. If any retry detects the specimen before the deadline:
   - Resolve the intervention.
   - Authorize rollout stop.
   - Return robot and camera ports through the existing controlled stop path.
   - Continue to the next Agent handoff.
5. If the five-minute deadline expires without detection:
   - Stop the rollout through the existing controlled stop path.
   - Confirm process termination and port return.
   - Set checkpoint `utm_post_place` to `waiting_for_specimen`.
   - Keep the current run resumable at UTM verification.
   - Show the latest UTM frame and the red `Place the specimen into the working area` button.
6. Pressing the button performs a fresh UTM verification frame only. It must not restart the completed Manipulation rollout.
7. Detection resolves the checkpoint and continues the handoff. Another non-detection returns to operator waiting with the new frame.

## API Design

Add a run-scoped endpoint:

```text
POST /api/runs/{run_id}/vision/specimen-placement-retry
```

Request:

```json
{
  "checkpoint": "active_cam_ejection | utm_post_place"
}
```

The endpoint must:

- Reject stale or mismatched run IDs.
- Reject a checkpoint that does not match the active intervention.
- Be idempotent while a retry is already running.
- Reuse the current run state and the existing Vision capture functions.
- Return a compact status object instead of the complete run report.
- Never directly command printer motion or restart a completed rollout.

## Live GUI Design

Both cards retain their current layout and image area. No new page or modal is introduced.

When operator placement is required:

- Display the latest fresh frame in the existing card.
- Place a full-width, squared red action button below the frame.
- Button text: `Place the specimen into the working area`.
- Use a dark red background, red border, and white semibold text consistent with the existing E-STOP palette but visually less severe than E-STOP.
- Show a short status line: `Specimen not detected. Place it in the working area, then continue.`
- Disable the button and show `Checking specimen...` while the callback is pending.
- On success, remove the intervention button through normal state refresh.
- On another non-detection, restore the button with the newly captured frame.
- On camera/runtime failure, show the existing error state instead of the placement button.

For UTM automatic recovery, show a compact countdown and retry status without an operator button until the five-minute deadline expires.

## Guardian and Agent Semantics

- `specimen_not_detected` is a recoverable observation and does not create a terminal Guardian incident.
- Camera, ownership, process, and hardware failures retain existing Guardian decisions.
- During operator wait, the relevant Agent appears as `WAITING`, not `DONE`, `FAILED`, or `RUNNING`.
- Active Cam wait keeps SPC incomplete and Vision waiting.
- UTM automatic recovery keeps Manipulation active and Vision observing.
- UTM operator wait begins only after rollout stop and port-return confirmation.

## Persistence and Refresh

- The intervention record and current frame reference are persisted with the run artifacts.
- Refreshing or reopening the Live GUI restores the same waiting state and button.
- Restarting the GUI server restores the run-scoped intervention only when the run itself is still resumable; it must not revive a completed or reset run.
- Emergency reset clears the intervention with the rest of the run state.

## Verification

Automated tests must cover:

1. Active Cam valid non-detection creates operator wait instead of Guardian terminal failure.
2. Active Cam retry detects the specimen and resumes at Manipulation without rerunning earlier stages.
3. A second Active Cam non-detection refreshes the frame and remains waiting.
4. UTM first non-detection starts a five-minute deadline while rollout remains active.
5. A later `ungrasping -> home` event inside the window triggers another UTM frame.
6. UTM detection inside the window stops rollout and continues handoff.
7. Deadline expiry stops rollout, returns ports, and exposes the operator button.
8. UTM operator retry performs Vision verification only and does not restart rollout.
9. Camera and port failures remain safety failures rather than operator-placement waits.
10. Duplicate button clicks are idempotent.
11. Page refresh restores the current waiting state and frame.
12. Frontend static tests verify button text, checkpoint payload, disabled state, and both card locations.

Browser verification must exercise the Live GUI through its normal top-level route and confirm that the frame, red action button, countdown, retry state, and successful transition are rendered without using a backend-only shortcut.
