# Post-Ungrasp UTM Completion Interlock Design

**Date:** 2026-07-14

## Objective

The transfer rollout may finish only after the measured robot state proves that an ungrasp action occurred, the measured arm subsequently returned to a stable home pose, and VisionAgent confirms the specimen on the UTM workspace from one UTM observation-camera frame.

## Existing Contracts Preserved

- `lerobot.rollout.status` remains the source of active rollout state.
- `vision_manipulation_completion.v1` remains the only Vision-to-Manipulation completion signal.
- `lerobot.rollout.stop` remains the only path that stops the rollout after completion.
- VisionAgent remains an observer and signal producer. It does not command the robot.
- ManipulationAgent remains the rollout supervisor. It does not perform image detection.
- Existing Active Cam ejection verification remains unchanged and separate from UTM placement verification.
- The new UTM presence interlock applies only to `needs_post_place_vision`. The existing post-disposal observation path remains unchanged and must not be interpreted as specimen-presence confirmation.

## Authoritative Completion Sequence

1. The LeRobot action log records measured and policy joint samples.
2. The measured channel enters `ungrasping`; the rollout-session interlock latches `ungrasping_seen=true`.
3. A later measured sample enters `home` with `home_gate.passed=true` and at least the existing home dwell requirement.
4. ManipulationAgent emits `post_place_interlock.v1` with `ready_for_utm_snapshot=true`.
5. VisionAgent captures exactly one frame from the configured UTM observation camera through the shared UTM runtime bridge.
6. The one-frame detector evaluates specimen presence and writes image and JSON evidence under the current run.
7. VisionAgent emits `vision_manipulation_completion.v1` only when specimen presence is confirmed and the evidence identity matches the current run, rollout session, and specimen.
8. ManipulationAgent calls `lerobot.rollout.stop` and reports `verified_complete` only after the stop response is `STOPPED`.

Policy-target motion remains display and diagnostic evidence. It is not authoritative for the completion interlock.

## Telemetry Interlock

The LeRobot bridge owns a session-scoped, read-only observer for `runs/lerobot_action_logs/<session_id>/motor_events.jsonl`. It consumes all newly appended action rows so a short `ungrasping` transition is not lost between agent passes.

The status response exposes:

```json
{
  "post_place_interlock": {
    "schema": "post_place_interlock.v1",
    "session_id": "...",
    "ungrasping_seen": true,
    "ungrasping_sequence": 412,
    "measured_base_state": "home",
    "measured_gripper_state": "idle",
    "home_gate_passed": true,
    "home_after_ungrasping": true,
    "ready_for_utm_snapshot": true,
    "latest_sequence": 438
  },
  "joint_telemetry": {
    "packet": {}
  }
}
```

The latch resets for a new rollout session. It is never inferred from frontend state.

## Vision One-Frame Verification

VisionAgent requests `vision.utm_specimen_presence.capture` only when `post_place_interlock.ready_for_utm_snapshot` is true. The tool:

- Uses the shared `UTMRuntimeProcessManager`; it does not open a second camera owner.
- Captures one current frame from the configured annotated UTM topic.
- Decodes the frame and performs deterministic specimen-presence detection.
- Produces a bounding box, pixel area, confidence, camera/topic identity, timestamp, and annotated evidence image.
- Returns a hard failure when the runtime, frame, or detector is unavailable in live or installed-printer operation.
- May use deterministic virtual evidence only in the existing explicit virtual-bridge test route.

The initial detector reuses the project's red-specimen contour convention. Detection thresholds are configuration values rather than hard-coded UI state.

## Completion and Retry Semantics

- Before ungrasping: rollout remains active; VisionAgent does not capture UTM evidence.
- After ungrasping but before stable home: rollout remains active; VisionAgent does not capture UTM evidence.
- Frame unavailable: no completion signal; the same stage may retry without restarting the rollout.
- Specimen absent: no completion signal; the same stage may retry without restarting the rollout.
- Specimen detected: VisionAgent emits a bounded completion signal and routes back to ManipulationAgent.
- Stop pending or failed: completion remains unverified.
- Stop confirmed: handoff changes to the next agent.

## Artifact Contract

Successful UTM verification creates `utm_completion_run_artifact.v1` under `runs/<run_id>/vision/<observation_id>/`. The metadata record includes `run_id`, `rollout_session_id`, `specimen_id`, camera/topic, dimensions, capture time, detector result, file path, and serving URL.

`run_metadata.latest_utm_completion_artifact` is displayed only when its run, session, and specimen identity match the current report. It remains visible until the next verification attempt for that identity is replaced. A new failed attempt clears the current identity's image so stale evidence cannot appear as a fresh success.

## Live GUI Layout

The Vision dashboard uses two balanced rows:

- Row 1: `Live Observation` (4 columns), `Active Cam Ejection` (4 columns), `UTM Placement Confirmation` (4 columns).
- Row 2: `Camera / Runtime` (4 columns), `Handoff Signal` (4 columns), `Agentic Progress` (4 columns).

The UTM card follows the existing Active Cam visual pattern: evidence frame, three compact metrics, and collapsible inspection details. Agentic Progress is reduced from eight columns to four. Device Bridge remains a separate card below the two visual confirmation cards.

## Safety Invariants

- No direct Dynamixel writes are introduced.
- No rollout stop occurs from policy intent alone.
- No UTM frame is captured before measured ungrasping followed by measured stable home.
- No simulator frame can complete a physical run.
- No stale artifact from another session, specimen, or run can complete the current rollout.
- Failure to capture or detect leaves the rollout active and observable.

## Verification

- Unit tests prove the latch ordering, session reset, and missed-transition resistance.
- ManipulationAgent tests prove no Vision completion request before the gate and no stop before verified evidence.
- VisionAgent tests prove one-frame capture, detection failure behavior, identity binding, and artifact persistence.
- Tool tests prove live fail-closed and explicit virtual-test behavior.
- Live GUI static and integration tests prove card order, spans, retained evidence, and detail rendering.
- Focused regression tests cover the existing Active Cam and rollout completion paths.
