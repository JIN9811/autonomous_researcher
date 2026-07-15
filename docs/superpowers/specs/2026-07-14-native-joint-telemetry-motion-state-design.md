# Native Joint Telemetry And Motion State Design

## Goal

Make the Manipulation Agent telemetry use the same LeRobot-native values recorded in `motor_events.jsonl`, preserve the full visible time range without an empty left side, and expose measured and policy motion-state annotations in a dedicated card.

## Constraints

- Do not change the rollout control loop, motor commands, policy inference, or Isaac pose rendering.
- Read only the existing action-log artifact.
- Keep `actual_deg`, `target_deg`, `actual_rad`, and `target_rad` for the 3D OMX viewer.
- Add native-value fields instead of changing the existing Isaac-facing fields.
- Keep browser memory bounded while retaining the beginning and end of the displayed timeline.

## Telemetry Contract

Each `joint_sample` adds:

- `actual_source`: `latest_observation` mapped to `Joint1` through `Gripper` without unit conversion.
- `target_source`: `requested_action` mapped without unit conversion.
- `applied_target_source`: `sent_action` mapped without unit conversion.
- `motion_state.measured`: annotation derived from recent `actual_source` samples.
- `motion_state.policy`: annotation derived from recent `target_source` samples.

Each annotation exposes a mutually exclusive arm `base_state` (`home`, `moving`,
or `holding`) and an orthogonal `gripper_state` (`grasping`, `ungrasping`, or
`idle`). The legacy `state`, `confidence`, and `reason` fields remain available
for existing consumers.

The existing degree/radian fields remain unchanged and continue driving the Three.js robot pose.

## State Model

The classifier has two simultaneous axes:

1. Arm base state: `moving` when any non-gripper joint exceeds the arm-motion
   threshold, `home` when J1-J5 remain inside their home ranges for 0.5 seconds,
   otherwise `holding`.
2. Gripper state: `grasping` while closing, `ungrasping` while opening, otherwise
   `idle`.

This permits combinations such as `moving + grasping`, `holding + ungrasping`,
and `home + grasping`. The six-axis Home Gate remains stricter than the arm
base-state indicator: it includes Gripper range and full arm/gripper stability.

Measured follower Home ranges use LeRobot-native feedback values:

| Joint | Minimum | Maximum |
|---|---:|---:|
| shoulder_pan / Joint1 | -15 | -6.5 |
| shoulder_lift / Joint2 | -61 | -53 |
| elbow_flex / Joint3 | 52 | 61 |
| wrist_flex / Joint4 | 43 | 52 |
| wrist_roll / Joint5 | -11 | -3 |
| gripper / Gripper | 55 | 65 |

Policy target Home uses the same ranges except for shoulder lift / Joint2,
which uses `[-72,-65]` in requested-action space. The physical follower's
motor-2 limit makes its measured Home settle around `-57`, while the policy
requests approximately `-69`; applying one range to both channels therefore
misclassifies a stable policy Home as `holding`. The two range tables are used
only by their matching telemetry channels.

The classifier uses a 0.5-second speed window and stateful hysteresis derived from
the recorded `lr-rollout-20260714T102459335287Z-0001` motion sequence:

- Arm motion enters `moving` at `4.0` native units/second.
- A moving arm exits only after remaining at or below `2.0` native units/second
  for `0.3` seconds.
- Gripper motion enters `grasping` or `ungrasping` at `2.0` native
  units/second in the corresponding direction.
- An active gripper state exits only after absolute speed remains at or below
  `0.5` native units/second for `0.2` seconds.
- Home entry requires the arm to remain inside its home ranges and at or below
  the arm exit speed for `0.5` seconds.

Joint1's measured Home upper bound is `-6.5`, widened from `-7.0` because the
recorded home pose repeatedly quantized between approximately `-7.08` and
`-6.90` while arm speed remained below `0.5`. Other measured bounds remain
unchanged. Policy Joint2 `[-72,-65]` was derived from 963 stable requested
targets across two recorded rollouts; the observed range was
`-71.3049` through `-65.4009`. A latched Home state remains Home through speeds below the `4.0`
motion-entry threshold while its joint positions remain in range. The strict
six-axis Home Gate still reports stability separately and includes the Gripper
range.

The classifier reports state, confidence, reason, arm speed, gripper speed,
stability duration, and per-joint home-gate results. Terminal workflow gating
remains based on measured evidence, not policy annotation.

## Chart Behavior

- Plot `actual_source` and `target_source`.
- Label the Y axis `LeRobot joint value`; use `%` in Gripper tooltips.
- Normalize the first visible sample to X=0.
- Preserve the first and latest samples when compacting history.
- Progressively decimate the complete visible history to at most 1200 points instead of deleting the oldest points.
- Set X minimum to 0 and maximum to the latest normalized elapsed time, so the full trajectory compresses as time grows.
- Keep a session-stable Y domain with padding. It may expand for a new extreme but never shrink during the session.
- Generate the saved policy-tracking PNG from the same native values.

## Motion State Card

Add a full-width `Robot Motion State` card after the Live Robot Pose and Policy Tracking cards. It contains:

- One shared five-segment state track instead of separate Measured and Policy panels.
- Measured activation uses the same white glow as the measured robot pose.
- Policy activation uses the same cyan glow as the policy-target ghost.
- If both channels occupy one state, white outer glow and cyan inner glow are shown together.
- The arm base state and an active gripper state can illuminate simultaneously.
- Compact Measured and Policy summaries retain current states, confidence, and reasons.
- A Home Gate section populated with all six configured ranges, current measured value, and pass/fail state.
- A stability indicator showing whether the 0.5-second dwell requirement is satisfied.

The card consumes only the telemetry packet and does not issue device commands.

## Verification

- Unit tests prove native values are preserved and state precedence is correct.
- Integration/static tests prove the card and native chart contract are present in the served bundle.
- Browser audit verifies no empty left-side gap, bounded history, fixed Y behavior, state-card rendering, and no JavaScript errors.

Recorded-rollout browser evidence (`lr-rollout-20260714T085420619465Z-0001`):

- Joint2 plotted 300 representative points from X `0` through `20.97896 s` with measured last value `-57.11844` and policy last value `-67.74633`.
- The stable Joint2 Y domain was `-71.6` through `-55.0`; labels remained inside the publication-style chart.
- Channel-specific replay kept measured Home counts unchanged at `1944` and `236` samples for `lr-rollout-20260714T102459335287Z-0001` and `lr-rollout-20260714T110039768051Z-0001`, while detecting `238` and `24` policy Home samples respectively. No policy Home sample occurred at or above the `4.0` arm motion-entry threshold.
- A two-sample browser fixture rendered measured `moving + grasping` as two white-glow segments and policy `holding + ungrasping` as two cyan-glow segments in one unified track; no legacy channel panels remained.
- Browser screenshots were generated at `/tmp/atr_policy_tracking_chart.png` and `/tmp/atr_motion_state_card.png`; these are verification outputs and are not repository artifacts.
