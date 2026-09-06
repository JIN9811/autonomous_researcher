# UTM Clear and Two Verification Snapshots

User-approved design, 2026-09-06.

## Contract

Keep the first VLA transfer and ActiveCam ownership unchanged. After successful
UTM completion, persisted CSV handoff, and robot-entry clearance, the same
run/loop/specimen invokes Manipulation task `clear_utm_to_disposal`. That task
replays `jin/utm_clear`, episode 0, using the existing follower calibration and
recorded actions. The currently accepted dataset has 542 frames at 15 FPS.
Frame count is descriptive, never an acceptance constant.

LeRobot Bridge owns replay processes, port occupancy, status, stop, and artifacts.
Use the existing process-management boundary rather than an unmanaged shell
inside an agent. Do not change calibration, motor limits, CSV parsing, or the
dataset. No automatic retry of an effectful replay.

Route: Equipment -> Manipulation(clear) -> Vision(clear verification) -> Analysis.
Replay exit alone is insufficient: successful termination, measured robot
return/clearance, and a fresh successful UTM snapshot showing the fixture empty
are required. Missing/failed images are not absence evidence. Failed or unknown
results block Analysis and preserve the existing operator/Guardian stop path.
Equipment-only preflight remains non-actuating; fully virtual execution uses
explicit simulated evidence without opening devices.

Verification 2 must detect compressed residual specimens around 30 x 10 mm in
the visible profile. This is an approximate detection scale, not a fixed geometry
or a replacement for experiment dimensions. Inspect the existing UTM detector's
ROI, calibration, area and shape filtering; avoid reusing a full-height specimen
threshold that suppresses flattened specimens. Add positive residual tests for
compressed/lower-profile shapes and negative empty-fixture tests. Unknown or
insufficient visual evidence blocks clearance; do not equate failed detection
execution with an empty fixture.

Keep Verification 1 (pre-test placement) and Verification 2 (post-test clearance)
independent and run/loop/specimen scoped, with a distinct child execution ID for
the replay. Snapshot artifacts and decisions are archived in the existing loop
artifact layout. Preserve the first record when the second is pending or fails.

The existing UTM image card gets always-visible header-right `Verification 1`
and `Verification 2` selectors, showing `Pending` when a snapshot is unavailable.
Keep both accessible in the same session. Add one final `UTM Clear & Verification 2`
row to Manipulation's Completion Verification. English UI text only.

## Validation and operations

TDD and non-actuating boundary/route/UI tests; replay the archived successful
equipment handoff and snapshot data without executing devices. Negative tests
cover failed replay, stale/wrong identity, no image, remaining specimen, missing
return evidence, repeated calls, and next-loop reset. No live run, commit, push,
server restart, or dataset mutation is authorized by this implementation task.

Changes remain in the current checkout, preserving existing uncommitted work.
