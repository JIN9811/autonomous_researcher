# Isaac Pick-and-Place LeIsaac Alignment Notes

Date: 2026-06-30

## Scope

This note tracks the safe LeIsaac-inspired changes for the ROBOTIS OMX Isaac mirror. The goal is to improve pick-and-place observability and keep the live teleoperation bridge stable. Teleop input and follower/leader runtime code are out of scope for this pass.

## Implemented Now

- Added a mirror-side action processor boundary in `sim/robotis_omx/tools/isaac_omx_mirror_server.py`.
- Kept the current stable gripper drive values instead of importing LeIsaac SO101 actuator gains directly.
- Added `grasp_diagnostics` to every applied mirror sample:
  - red specimen world position
  - gripper target and raw target
  - gripper closed/open classification
  - finger collision prim distance to the object
  - contact report status, force, penetration, and matched pairs
  - lifted/not-lifted classification
- Added the same action metadata to RGB-D render `manifest.jsonl` rows so recorded Isaac sidecar frames can be audited after recording.

## Why This Is The Safe First Step

LeIsaac does not simply set a visual mesh pose and hope contact works. It has an explicit action-processing layer and uses task-level signals such as object grasped, replay/inference hooks, and dynamic gripper effort updates across teleop, replay, inference, and datagen loops.

Our current bridge is live HTTP mirror code tied to an already-running Isaac stage. Importing IsaacLab/LeIsaac control classes directly would add a second environment stack and change timing behavior. The safer move is to first make the existing bridge expose the same kind of action/debug contract, then tune physics from recorded evidence.

## LeIsaac Reference Points Checked

Local reference repository: `/tmp/leisaac_repo`, commit `24d3bcd`.

- `source/leisaac/leisaac/devices/action_process.py`
  - Defines arm and gripper action configs separately.
  - Converts leader action values into the robot action tensor.
- `source/leisaac/leisaac/utils/env_utils.py`
  - `dynamic_reset_gripper_effort_limit_sim()` updates gripper effort based on the nearest object mass.
- `scripts/environments/teleoperation/teleop_se3_agent.py`
- `scripts/environments/teleoperation/replay.py`
- `scripts/evaluation/policy_inference.py`
- `scripts/datagen/state_machine/generate.py`
  - All call the dynamic gripper effort update in their relevant loops.
- `source/leisaac/leisaac/tasks/template/single_arm_env_cfg.py`
  - Uses `decimation = 1`.
  - Sets PhysX `bounce_threshold_velocity = 0.01`.
  - Sets PhysX `friction_correlation_distance = 0.00625`.
- `source/leisaac/leisaac/tasks/lift_cube/mdp/observations.py`
  - Uses an explicit object-grasped signal instead of relying only on visual state.

## NVIDIA GR00T Blueprint Fit

The NVIDIA Isaac GR00T synthetic manipulation blueprint is useful as a later data-generation reference, not as a direct live teleop drop-in. The public blueprint describes a workflow where simulated teleoperation demonstrations are recorded first, then GR00T-Mimic generates synthetic trajectories and GR00T-Gen/Cosmos augments data. Its local deployment also assumes an Isaac Lab container stack and specific GPU/container requirements.

For this project, the practical order is:

1. Keep real teleop recording stable.
2. Record Isaac RGB-D sidecar frames and action/grasp diagnostics.
3. Convert successful real/sim episodes into a canonical episode format.
4. Add an offline synthetic trajectory branch after the real recording loop is reliable.

Sources:

- https://build.nvidia.com/nvidia/isaac-gr00t-synthetic-manipulation/blueprintcard
- https://github.com/NVIDIA-Omniverse-blueprints/synthetic-manipulation-motion-generation

## Deferred Improvements

1. Canonical episode builder
   - Merge LeRobot observations, Isaac RGB-D sidecar frames, active-cam specimen pose, and mirror action metadata into one episode index.
   - Mark missing Isaac frames explicitly instead of silently falling back.

2. Grasp event labels
   - Derive labels from `grasp_diagnostics`:
     - `not_near_object`
     - `near_closed_without_contact`
     - `grasp_candidate`
     - `lifted`
     - `released`
   - Use these as visualization overlays and later as training metadata.

3. Physics scene validator
   - Check stage settings before recording:
     - dynamic rigid body on red cube
     - box collider on cube
     - finger inner pad material friction
     - low restitution on cube/table/finger
     - PhysX timestep/solver/contact settings
   - Fail loudly in GUI if critical settings are missing.

4. Replay/inference parity hook
   - Ensure the same action processor metadata appears in teleop, recording replay, inference dry-run, and render-after-recording paths.
   - This mirrors the way LeIsaac calls its effort updater from teleop/replay/inference/datagen loops.

5. Offline synthetic branch
   - Use the NVIDIA/IsaacLab blueprint style only after recorded episodes are clean.
   - Keep it separate from live teleop because IsaacLab/GR00T-Mimic dependencies and timing assumptions differ from the current mirror server.

## Verification

Current targeted verification:

```bash
pytest -q tests/unit/test_isaac_omx_mirror_mapping.py \
  tests/unit/test_isaac_omx_mirror_server.py \
  tests/unit/test_isaac_omx_scene_physics.py
```

Result: 83 passed, 2 warnings.
