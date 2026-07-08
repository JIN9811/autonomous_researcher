# Official Isaac Lab Mimic Integration Design

## Goal

Replace the current default `joint_replay`-first Isaac Lab pipeline with an official Isaac Lab Mimic path for data generation.

The official path should:

1. Export successful LeRobot/Isaac mirror teleop demos to Isaac Lab HDF5.
2. Automatically annotate those demos with Mimic `datagen_info`.
3. Segment the task into object-centric subtasks.
4. Run Isaac Lab's official `scripts/imitation_learning/isaaclab_mimic/generate_dataset.py`.
5. Keep only successful generated rollouts.
6. Feed generated HDF5 rows into the existing VLA training import.

The existing `joint_replay` path should become a fallback/debug backend, not the default path that is presented as Mimic.

## Official Code Baseline

Reference code was copied without runtime linkage to:

```text
references/official_isaac_lab_mimic/
```

Source checkout:

```text
/home/jin/IsaacLab
branch: release/3.0.0-beta2
commit: ffff603eafc6b74264a5261cc0183d6a65390d78
```

Import verification:

```text
/home/jin/IsaacLab/isaaclab.sh -p
isaaclab_mimic -> /home/jin/IsaacLab/source/isaaclab_mimic/isaaclab_mimic
isaaclab -> /home/jin/IsaacLab/source/isaaclab/isaaclab
```

Primary official files:

- `annotate_demos.py`: replays source demos and records `obs/datagen_info`.
- `generate_dataset.py`: loads annotated demos into `DataGenInfoPool`, creates `DataGenerator`, and runs async generation.
- `replay_demos.py`: replays source or generated HDF5 episodes and can validate task success/state replay.
- `mimic_env_cfg.py`: defines `DataGenConfig` and `SubTaskConfig`.
- `manager_based_rl_mimic_env.py`: defines required Mimic env APIs.
- `data_generator.py`: transforms object-centric source subtask segments into new end-effector target trajectories.

## Current Mismatch

The current GUI label says `Domain randomization + mimic`, but the default backend is:

```text
joint_replay -> Lab step replay -> optional mirror RGB-D render
```

That path preserves recorded joint action segments and can produce trainable Lab-stepped data, but it is not the same as official Mimic trajectory recomposition. Official Mimic expects:

- object-centric subtask segments,
- `target_eef_pose_to_action()`,
- `action_to_target_eef_pose()`,
- `actions_to_gripper_actions()`,
- `get_object_poses()`,
- `get_subtask_term_signals()` for auto annotation,
- `SubTaskConfig` matching the task.

Therefore the improvement must center on subtask segmentation and annotation first, then the action adapter.

## Proposed Subtasks

Use a 3-subtask pick-place-retract structure first. This is simpler than the earlier 5-signal structure and matches the physical task better.

```text
Subtask 0: pick
motion: approach + grasp + lift
object_ref: red_cube
term signal: cube_lifted
```

```text
Subtask 1: place
motion: move_to_place + release
object_ref: target
term signal: released_at_target
```

```text
Subtask 2: retract
motion: retract / clear / final hold
object_ref: None
term signal: None
```

Rationale:

- `pick` should transform around the cube pose.
- `place` should transform around the target pose or place zone.
- `retract` should not transform around the cube or target because it is a safety exit motion.

If success is too low, split `pick` into `approach_to_cube` and `grasp_and_lift`. Do not start with that unless the 3-subtask path fails annotation or generation.

## Auto Annotation Contract

The source HDF5 must contain:

```text
data/demo_xxxxxx/obs/datagen_info/object_pose
data/demo_xxxxxx/obs/datagen_info/eef_pose
data/demo_xxxxxx/obs/datagen_info/target_eef_pose
data/demo_xxxxxx/obs/datagen_info/subtask_term_signals/cube_lifted
data/demo_xxxxxx/obs/datagen_info/subtask_term_signals/released_at_target
```

The final retract subtask does not need a term signal in official Mimic; the official examples use `subtask_term_signal=None` for the final subtask.

Auto annotation functions:

- `cube_lifted`: true once cube z rises above initial cube z by a tuned threshold while gripper is closed or object remains grasped.
- `released_at_target`: true once cube xy/yaw is inside the target tolerance and gripper transitions to open/released.
- `episode_success`: existing success flag remains required.

The official `annotate_demos.py --auto` path can be used if our Robotis OMX Mimic env implements `get_subtask_term_signals()`. Alternatively, a direct HDF5 preannotation tool can write the same fields, but the output must pass the official `DataGenInfoPool.load_from_dataset_file()` path.

## Robotis OMX Mimic Env Requirements

The Robotis OMX Mimic environment should be made compatible with official Mimic instead of relying on joint replay.

Required APIs:

```text
get_robot_eef_pose(eef_name, env_ids)
target_eef_pose_to_action(target_eef_pose_dict, gripper_action_dict, action_noise_dict, env_id)
action_to_target_eef_pose(action)
actions_to_gripper_actions(actions)
get_object_poses(env_ids)
get_subtask_term_signals(env_ids)
```

The current risk is action representation. Official Mimic composes end-effector trajectories; our physical env currently uses joint-position actions. That means one of these must be true:

1. Preferred: add a stable IK or pose-action adapter so official Mimic target EEF poses become valid Robotis OMX actions.
2. Alternative: define the Mimic action space as absolute EEF pose + gripper, then convert to joint targets inside the Lab action term.
3. Fallback: keep `joint_replay` as debug only, clearly labeled as replay, not official Mimic.

The official examples show both relative IK-style Franka Mimic and absolute pose-style GR1T2 pick-place Mimic. Our path should follow the GR1T2 shape more closely if we can expose stable absolute EEF targets.

## Domain Randomization Scope

For official Mimic generation, keep physics and object pose randomization conservative until the action adapter works.

Initial default:

- cube pose: use recorded active-cam/Isaac mirror initial pose
- target pose: fixed or recorded target
- cube mass/friction: fixed
- gripper friction: fixed
- lighting/background/sensor noise: allowed after trajectory generation or through camera rendering

This avoids generating trajectories for object poses the small Robotis OMX gripper cannot actually grasp yet.

## Pipeline Design

New default flow:

```text
Build canonical successful episodes
  -> export source HDF5
  -> replay source HDF5 with official replay_demos.py
  -> official/manual or auto annotation
  -> validate annotated HDF5 with DataGenInfoPool
  -> official Isaac Lab Mimic generate_dataset.py
  -> replay generated HDF5 with official replay_demos.py
  -> output success/failure manifests
  -> optional RGB-D render for generated demos
  -> refresh training_import
```

Backend naming:

- `official_mimic`: uses Isaac Lab `generate_dataset.py`.
- `joint_replay`: fallback/debug replay backend.

GUI should not label `joint_replay` as Mimic without a qualifier.

## Validation Routine

Before generation:

- confirm Isaac Lab import works through `/home/jin/IsaacLab/isaaclab.sh -p`
- confirm official scripts exist
- confirm task registration callback imports Robotis OMX tasks
- confirm source HDF5 has successful demos
- replay the source HDF5 with `scripts/tools/replay_demos.py --validate_success_rate`
  - visible/operator replay must omit `--headless`
  - Robotis physical Mimic replay must include `--enable_cameras` because the env spawns RTX cameras
- confirm annotated HDF5 has `datagen_info`
- confirm required subtask signals exist and each signal has at least one true frame
- load annotated HDF5 through Isaac Lab Mimic `DataGenInfoPool`

During generation:

- run official `generate_dataset.py`
- parse generated success/failure count from log and HDF5
- fail with structured blocker on zero success

After generation:

- verify generated HDF5 has `data/demo_*`
- verify `env_args.env_name` matches the Robotis OMX Mimic task
- verify generated demos include actions, states, obs, initial_state
- replay generated HDF5 with `scripts/tools/replay_demos.py --validate_success_rate`
- verify training import contains generated rows only when generation succeeded
- optionally render first/middle/last RGB-D preview frames

## 2026-07-08 Runtime Findings

The exported source HDF5 is structurally valid but does not make every real episode a valid official Mimic source episode.

Important contract distinction:

```text
source HDF5 datagen labels: advisory/export labels
official annotation result: authoritative Lab physics replay gate
official generation result: authoritative synthetic rollout gate
replay promotion result: authoritative training eligibility gate
```

Observed exporter limitation:

```text
obs/datagen_info/object_pose/red_cube is currently the initial cube pose repeated across frames.
place/released_at_target labels are generated from frame fractions.
```

That is acceptable for structural handoff, but official `annotate_demos.py --auto` must replay the source action sequence and recompute physical task success. Episodes that fail physical replay must be excluded from the official Mimic source pool, while the original real LeRobot episode remains preserved for real-data training.

The official per-episode wrapper must pass the recorded cube reset pose to both stages:

```text
annotate_demos.py:
  --robotis-cube-reset-xyz <episode initial cube xyz>
  --robotis-cube-reset-yaw <episode initial cube yaw>

generate_dataset.py:
  --robotis-cube-reset-xyz <episode initial cube xyz>
  --robotis-cube-reset-yaw <episode initial cube yaw>
```

Isaac/Kit process stability also matters. Running annotation and generation as separate Isaac Python processes back-to-back can hit a startup-time segmentation fault. The wrapper now applies a subprocess cooldown:

```text
--process-cooldown-sec 3.0
```

Recommended full-run behavior:

```text
for each source episode:
  1. shard one source demo
  2. auto-annotate by physical replay
  3. if annotation_count == 0, mark annotation_failed and continue
  4. generate N trials through official Mimic
  5. if success_count == 0, mark generation failed and continue
  6. merge only generated successes
  7. keep failure manifest for operator review
```

Training import must include:

```text
real LeRobot rows: retained according to normal real-data policy
Isaac RGB-D render rows: retained unless contact audit excludes them
official Mimic synthetic rows: only after generated success and replay promotion
```

Do not use the prefilled source HDF5 `place` or `released_at_target` labels as a substitute for official Lab replay success.

## Implementation Steps

1. Keep reference code folder as read-only baseline.
2. Phase 1: validate local Isaac Lab Mimic install, official scripts, and Robotis OMX task registry.
3. Phase 2: export one successful source HDF5 and replay it through official `replay_demos.py`.
4. Phase 3: rename current user-facing backend labels so `joint_replay` is not presented as official Mimic.
5. Phase 4: change Robotis OMX official Mimic config to the 3-subtask layout:
   - `cube_lifted`
   - `released_at_target`
   - final retract with `None`
6. Phase 5: implement or repair `get_subtask_term_signals()` against the physical scene signals.
7. Phase 6: replace preannotated passthrough with an annotation gate:
   - if exported HDF5 already has valid `datagen_info`, pass through
   - otherwise run official `annotate_demos.py --auto`
   - first 3-5 source episodes can be manually annotated or visually checked to verify boundary quality
8. Phase 7: validate annotated HDF5 through `DataGenInfoPool.load_from_dataset_file()`.
9. Phase 8: make `mimic_generation_backend="official"` available as the standard path once annotation passes.
10. Phase 9: implement action adapter for official Mimic target EEF poses.
11. Phase 10: run a one-episode smoke:
   - annotate only
   - generate 1 trial
   - inspect generated HDF5
12. Phase 11: generate `generated_dataset_small.hdf5` with 10-30 trials.
13. Phase 12: replay generated small HDF5 and tune interpolation, action noise, and subtask offsets.
14. Phase 13: keep object pose randomization disabled until generated replay succeeds; then introduce object randomization only if grasp success stays stable.
15. Phase 14: generate large `generated_dataset.hdf5`.
16. Phase 15: convert/import official Isaac HDF5 into the LeRobot/VLA training manifest.

## Phase 2 Status

Phase 2 exported the current physical source session to HDF5 and ran an official visible replay gate.

```text
dataset: /home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1
source HDF5: /home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1/sidecar/isaac_lab_synthetic/latest/hdf5/exported_successful_real_episodes.hdf5
episode count: 50
frame count: 23658
HDF5 contract: PASS
official visible replay startup: PASS with --enable_cameras
official success replay: FAIL, episode 0 produced Successfully replayed: 0/1
```

Episode 0 diagnostic after replay:

```text
first cube: [0.3492, 0.3019, 0.0152]
final cube: [0.5869, 0.0795, 0.1190]
place target: [0.52, 0.30], radius 0.035, max z 0.055
lift: true
place: false
success: false
final contact force: 0.0 / 0.0
```

This means the Phase 2 blocker is not HDF5 schema or action dimension. The blocker is source replay fidelity against the physical success term:

```text
SOURCE_REPLAY_SUCCESS_FAILED
```

Do not advance to large official Mimic generation until either the official source replay succeeds or the pipeline intentionally changes the source validation contract.

### 2026-07-07 Revalidation

The Phase 2 source replay blocker was rechecked after the Robotis OMX physical target was aligned to the right cylinder stage target:

```text
PLACE_TARGET_XY_M = (0.590, 0.078)
PLACE_TARGET_CUBE_CENTER_Z_M = 0.119
PLACE_RADIUS_M = 0.050
PLACE_HEIGHT_RANGE_M = [0.095, 0.145]
```

The previously failing final cube pose `[0.5869, 0.0795, 0.1190]` is inside this updated target tolerance. A fresh official replay gate was run on:

```text
/home/jin/.cache/huggingface/lerobot/jin/20260703_1/sidecar/isaac_lab_synthetic/latest/hdf5/exported_successful_real_episodes.hdf5
```

Observed command result:

```text
official replay startup: PASS
official replay execution: PASS
official success replay: PASS, Successfully replayed: 1/1
log: runs/isaac_lab_official_replay/replay_demo0_20260707_004524.log
```

Current status:

```text
SOURCE_REPLAY_SUCCESS_FAILED is resolved for demo_000000 under the current stage target.
Phase 3 user-facing backend separation is partially implemented:
- section 7 launcher sends mimic_generation_backend="joint_replay"
- Isaac Lab tab exposes Mimic Backend: joint_replay or official
- runner/generation_config summary records backend_contract
```

Next active work is Phase 4/5: convert the physical Mimic task to the documented 3-subtask contract and repair the term-signal API before trusting official generation.

### 2026-07-07 Phase 4/5 Implementation Status

The physical Robotis OMX Mimic task now exposes the documented 3-subtask official contract while retaining the old replay/debug signal names.

Implemented contract:

```text
official subtask 0: cube_lifted
official subtask 1: released_at_target
official subtask 2: None
```

Implementation details:

```text
physical_observations.cube_lifted(env) delegates to lift(env)
physical_observations.released_at_target(env) delegates to release(env)
PhysicalEnvCfg.SubtaskTermsCfg exposes both alias terms
PhysicalMimicEnvCfg.subtask_configs["omx"] references cube_lifted/released_at_target/None
RobotisOmxPickPlaceMimicEnv.get_subtask_term_signals() returns:
  approach, grasp, lift, place, release, retract,
  cube_lifted, released_at_target
```

Export/manifest alignment:

```text
device_bridges.isaac_lab_hdf5 writes datagen_info/subtask_term_signals with:
  approach, grasp, lift, place, cube_lifted, released_at_target

device_bridges.isaac_lab_synthetic MIMIC_REQUIRED_SUBTASKS is now:
  approach, grasp, lift, place, cube_lifted, released_at_target
```

Verification commands:

```text
/home/jin/IsaacLab/_isaac_sim/python.sh -m pytest -q \
  tests/unit/test_isaac_lab_robotis_omx_registration.py::test_physical_mimic_subtasks_match_successful_replay_boundaries \
  tests/unit/test_isaac_lab_robotis_omx_registration.py::test_physical_mimic_adapter_preserves_successful_joint_replay_contract

/home/jin/IsaacLab/_isaac_sim/python.sh -m pytest -q \
  tests/unit/test_lerobot_isaac_lab_synthetic.py::test_isaac_lab_export_hdf5_writes_successful_real_episode_in_frame_order \
  tests/unit/test_lerobot_isaac_lab_synthetic.py::test_isaac_lab_mimic_and_rl_smoke_actions_write_launch_artifacts

python3 -m py_compile \
  integrations/isaac_lab_robotis_omx/mdp/physical_observations.py \
  integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_mimic_env.py \
  integrations/isaac_lab_robotis_omx/robotis_omx_physical_mimic_env_cfg.py \
  integrations/isaac_lab_robotis_omx/robotis_omx_physical_env_cfg.py \
  device_bridges/isaac_lab_hdf5.py \
  device_bridges/isaac_lab_synthetic.py
```

Observed result:

```text
registration tests: 2 passed
synthetic/export tests: 2 passed
py_compile: PASS
```

Current status:

```text
Phase 4: implemented and verified for signal naming/config.
Phase 5: implemented and verified for env API compatibility.
Next phase: annotation gate and DataGenInfoPool.load_from_dataset_file() validation.
```

### 2026-07-07 Phase 6/7 Implementation Status

The preannotated physical HDF5 path now validates against the official Isaac Lab Mimic `DataGenInfoPool` contract.

Compatibility issue found:

```text
Current real source HDF5:
/home/jin/.cache/huggingface/lerobot/jin/20260703_1/sidecar/isaac_lab_synthetic/latest/hdf5/exported_successful_real_episodes.hdf5

Existing signal keys:
approach, grasp, lift, place

Official physical Mimic subtask config requires:
cube_lifted, released_at_target, None
```

Implemented normalization:

```text
ensure_isaac_lab_mimic_signal_aliases(path)

Adds missing aliases only to the annotated HDF5 copy:
lift -> cube_lifted
release -> released_at_target
place -> released_at_target when release is absent
```

Annotation passthrough gate now performs:

```text
1. copy source HDF5 to hdf5/source_real_success_annotated.hdf5
2. normalize official signal aliases on the annotated copy
3. run validate_isaac_lab_hdf5_contract()
4. run validate_isaac_lab_datagen_pool_contract()
5. mark annotation blocked if alias, HDF5 contract, or DataGenInfoPool validation fails
```

New report artifacts:

```text
hdf5/annotation_signal_alias_report.json
hdf5/annotation_contract_report.json
hdf5/annotation_datagen_pool_report.json
hdf5/annotation_summary.json
```

Real current-session result:

```text
annotation_status: completed
signal_alias_ok: true
signal_alias_added_count: 100
contract_ok: true
datagen_pool_ok: true
datagen_pool_num_infos: 50
output_file:
/home/jin/.cache/huggingface/lerobot/jin/20260703_1/sidecar/isaac_lab_synthetic/latest/hdf5/source_real_success_annotated.hdf5
```

Verification commands:

```text
/home/jin/IsaacLab/_isaac_sim/python.sh -m pytest -q \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_preannotated_hdf5_passthrough_completes_without_runner \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_hdf5_contract_loads_into_official_datagen_info_pool

python3 -m py_compile \
  device_bridges/isaac_lab_hdf5.py \
  device_bridges/isaac_lab_synthetic.py \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py
```

Observed result:

```text
annotation/DataGenInfoPool tests: 2 passed
py_compile: PASS
```

Current status:

```text
Phase 6: implemented for preannotated passthrough normalization and blocking validation.
Phase 7: implemented and validated on the 50-episode current source HDF5.
Next phase: official generate_dataset one-episode smoke using the annotated HDF5.
```

### 2026-07-07 Phase 8/10 Implementation Status

The official Isaac Lab Mimic generation smoke has been run with demo 0.

What works:

```text
official annotate_demos.py --auto can annotate a real Robotis OMX demo.
official DataGenInfoPool can load the annotated demo.
official generate_dataset.py can produce a successful generated demo when the env reset cube pose matches the source demo cube pose.
```

Observed successful smoke:

```text
input:
runs/isaac_lab_official_mimic_smoke/source_demo0_auto_annotated.hdf5

output:
runs/isaac_lab_official_mimic_smoke/generated_dataset_demo0_auto_reset_debug.hdf5

generate_dataset result:
1/1 successful demos generated by mimic

generated demo metrics:
num_samples: 491
success: True
first_obj_xyz: [0.349205, 0.301937, 0.015200]
final_obj_xyz: [0.587523, 0.080777, 0.119000]
max_obj_z: 0.181551
min_place_xy_dist: 0.003719 m
min_eef_obj_dist: 0.034371 m
action_shape: [491, 7]
```

Root-cause note:

```text
Generation failed before reset alignment because the generated env reset cube pose defaulted near [0.400, 0.300, 0.015] while the source demo started near [0.349205, 0.301937, 0.015200].
The generated EEF path then missed the cube even though gripper close/open actions were present.
```

Required standardization before scaling:

```text
1. The official backend must derive the source episode initial red_cube pose from the input HDF5.
2. For deterministic small-generation smoke, it must pass that pose through --robotis-cube-reset-xyz and --robotis-cube-reset-yaw.
3. Only after replay validation passes should object pose randomization be reintroduced.
4. Environment/background domain randomization may remain enabled because it does not change the grasp geometry.
```

Updated phase status:

```text
Phase 8: official backend path is executable, but GUI/runner must standardize source-pose reset arguments.
Phase 9: action adapter passes deterministic source-pose smoke; general object-retargeting remains an open tuning item.
Phase 10: one-episode official generation smoke passed with source-pose reset override.
Next phase: generate 10-30 official Mimic trials, replay generated HDF5, then connect successful generated HDF5 to LeRobot/VLA training import.
```

### 2026-07-07 Phase 11 Implementation Status

The runner path now standardizes the source-pose reset that was proven necessary in Phase 10.

Implemented runner contract:

```text
For official Mimic generation, read source red_cube pose from the input HDF5:
data/demo_xxxxxx/initial_state/rigid_object/red_cube/root_pose

Pass it to Isaac Lab generate_dataset.py:
--robotis-cube-reset-xyz <x,y,z>
--robotis-cube-reset-yaw <yaw>

Expose it in generation_config:
source_object_reset.enabled = true
source_object_reset.policy = lock_generation_reset_to_source_demo_initial_pose
source_object_reset.object_name = red_cube
```

Official trajectory generation profile:

```text
--robotis-domain-randomization-profile off
```

Reason:

```text
A 10-trial test with standard profile produced 0/5 successes before timeout.
Failed demos had correct starting xy/z but the cube fell through the scene to approximately z=-327 m.
The standard profile is therefore not safe for physics trajectory generation.
```

Design consequence:

```text
Official Mimic generation must keep object pose, object material, object mass, gripper physics, and contact offsets locked.
Visual/environment domain randomization should be applied in the post-generation RGB-D render stage.
```

Verified result with corrected off-profile path:

```text
generated file:
runs/isaac_lab_official_mimic_smoke/generated_dataset_demo0_auto_reset_3_off.hdf5

generation result:
3/3 successful demos generated by mimic

generated HDF5:
demo_count = 3
num_samples = 491 per demo
success attr = True for all demos
final object placement = within 0.001-0.005 m of target xy
```

Replay verification:

```text
combined replay:
demo_0 PASS
demo_1 PASS
demo_2 timed out during combined camera-enabled replay

single replay:
demo_2 PASS, Successfully replayed: 1/1
```

Current scaling limitation:

```text
The source-pose reset override is one pose per generate_dataset.py process.
It is correct for one selected source demo, but not yet correct for all 50 episodes in one command if each episode has a different active-cam cube pose.
```

Required next implementation:

```text
Split official generation by source episode:
1. create an annotated one-demo HDF5 shard per source episode
2. read that demo's red_cube initial pose
3. launch generate_dataset.py for that shard with its pose override
4. collect successes/failures into a merged manifest
5. optionally merge successful HDF5 demos into generated_dataset.hdf5
6. run replay validation on generated successes
7. expose only successful generated demos to LeRobot/VLA training import
```

### 2026-07-07 Per-Episode Official Generation Split

The source-pose reset limitation is now handled by a wrapper around the official Isaac Lab generator instead of by changing the source dataset format.

Implementation:

```text
scripts/lerobot_isaac_lab_official_mimic_generate.py
```

The wrapper is intentionally thin:

```text
1. read selected demo keys from the annotated source HDF5
2. copy each selected demo into a one-demo shard HDF5
3. read that demo's red_cube reset pose from initial_state/rigid_object/red_cube/root_pose
4. call Isaac Lab's official generate_dataset.py for that shard
5. pass --robotis-cube-reset-xyz and --robotis-cube-reset-yaw for that source demo
6. append one JSONL row to successes.jsonl or failures.jsonl
7. merge successful generated HDF5 demos into the requested generated_dataset.hdf5
```

This keeps the official generator as the trajectory-generation engine while solving the per-episode initial object pose problem that caused generated trajectories to miss the cube.

The bridge official backend now launches:

```text
scripts/lerobot_isaac_lab_official_mimic_generate.py
```

instead of launching:

```text
/home/jin/IsaacLab/scripts/imitation_learning/isaaclab_mimic/generate_dataset.py
```

directly. The wrapper then launches the official script once per source episode.

Runner contract:

```text
mimic/generated_dataset.hdf5
mimic/official_per_episode/<demo_name>/source.hdf5
mimic/official_per_episode/<demo_name>/generated_dataset.hdf5
mimic/official_per_episode/<demo_name>/generated_dataset_failed.hdf5
mimic/official_per_episode/<demo_name>/generate.log
mimic/successes.jsonl
mimic/failures.jsonl
mimic/official_mimic_summary.json
```

Manifest contract:

```text
per_episode_generation.enabled = true
per_episode_generation.shard_policy = one_demo_hdf5_per_source_episode
per_episode_generation.source_object_reset_policy = per_episode_initial_red_cube_pose
per_episode_generation.success_manifest = mimic/successes.jsonl
per_episode_generation.failure_manifest = mimic/failures.jsonl
per_episode_generation.summary_file = mimic/official_mimic_summary.json
```

Default generation physics policy:

```text
robotis-domain-randomization-profile = off
robotis-camera-mode = off
```

Rationale:

```text
Official Mimic trajectory generation must first preserve the recorded grasp geometry.
Lighting/background/camera perturbation belongs in the later RGB-D render stage.
Object pose, object mass, friction, contact offsets, and gripper physics should stay locked until generated replay success is stable.
```

Current validation:

```text
Dry-run on current 20260703_1 source episodes 0, 1, 2:
selected_demo_count = 3
success manifest rows = 3
failure manifest rows = 0
all one-demo shard files exist = true
demo_000000 reset = [0.349205, 0.301937, 0.0152], yaw 0.000000
demo_000001 reset = [0.340588, 0.319838, 0.0152], yaw 0.593272
demo_000002 reset = [0.335597, 0.308643, 0.0152], yaw -0.251886
```

Verification:

```text
4 targeted tests passed:
- bridge official backend launches the wrapper, not generate_dataset.py directly
- wrapper dry-run creates one shard per source demo
- preannotated HDF5 passthrough still completes
- official DataGenInfoPool still loads the annotated source

py_compile passed for the bridge, wrapper, and updated tests.
```

Open next gate:

```text
Run live non-dry-run wrapper generation for a small selected subset, e.g. episodes 0,1,2 with one trial per episode.
Replay generated successes through official replay_demos.py.
Only after that should the GUI all-episode button launch the full 50-episode generation.
```

### 2026-07-07 Official Auto-Annotation Generation Contract

The wrapper must not trust an existing `datagen_info/target_eef_pose` dataset unless it was produced by Isaac Lab's official annotation path for the same environment.

Observed failure:

```text
The current source_real_success_annotated.hdf5 loaded into DataGenInfoPool, but its target_eef_pose translation values were not true end-effector workspace poses.
Shape-level contract checks passed, but official Mimic generated incorrect trajectories.
```

Required official backend flow:

```text
source session HDF5
  -> one-demo source.hdf5 shard
  -> official annotate_demos.py --auto
  -> one-demo annotated.hdf5
  -> official generate_dataset.py
  -> one-demo generated_dataset.hdf5 or generated_dataset_failed.hdf5
  -> successes.jsonl / failures.jsonl
  -> merged generated_dataset.hdf5 containing successful generated demos only
```

Annotation command policy:

```text
Use:
  isaaclab.sh -p annotate_demos.py ...
  --annotation-mode auto
  --headless

Do not use:
  --robotis-cube-reset-xyz
  --robotis-cube-reset-yaw

Reason:
  Annotation is a replay of the source demo. It must not reset the object differently from the recorded source trajectory.
```

Generation command policy:

```text
Use:
  isaaclab.sh -p generate_dataset.py ...
  --robotis-cube-reset-xyz <source episode cube xyz>
  --robotis-cube-reset-yaw <source episode cube yaw>
  --robotis-domain-randomization-profile off
  --robotis-camera-mode off

Reason:
  Generation is the rollout stage. It must start from the per-source object pose, but it must not randomize physics/camera while validating grasp geometry.
```

Retry and manifest policy:

```text
annotation-retries default = 2
generation-retries default = 1

summary.ok = true if at least one generated success is merged
summary.status =
  success          when every selected source episode yields at least one success
  partial_success  when at least one source succeeds and at least one source fails
  failed           when no successful generated demo is produced

failures.jsonl must keep annotation_failed rows separate from generation_failed rows.
Training import must consume generated successes only unless the user explicitly opts into failed generated data.
Real robot source episodes remain preserved even when their Isaac Lab synthetic generation fails.
```

Training readiness policy:

```text
Official Mimic generated rows are candidates until official replay validation passes.
Generation-time success means the rollout reached the task success condition during generate_dataset.py.
Replay-time success means the saved actions can be replayed from the HDF5 into the environment and still satisfy the task success condition.

Required generated success row fields:
  schema = atr.lerobot.isaac_lab_mimic.success.v1
  source_type = isaac_lab_mimic
  trajectory_id
  generated_demo
  local_generated_demo
  source_episode_index
  frame_count
  metrics.success = true
  metrics.official_mimic = true
  metrics.replay_required = true
  metrics.lab_step_replay = false until replay validation passes
  artifacts.hdf5_path
  artifacts.per_episode_hdf5_path
  training.eligible = false until replay validation passes
  training.exclusion_reason = official_replay_validation_required until replay validation passes
```

Replay validation promotion:

```text
For every generated candidate demo:
  1. run official replay_demos.py with --validate_success_rate
  2. if replay passes, promote that row:
       metrics.lab_step_replay = true
       metrics.replay_required = false
       training.eligible = true
       training.exclusion_reason = ""
  3. if replay fails, keep it excluded:
       metrics.lab_step_replay = false
       training.eligible = false
       training.exclusion_reason = official_replay_validation_failed

LeRobot/VLA training import must use only promoted official Mimic demos.
```

Implemented replay promotion contract:

```text
script:
scripts/lerobot_isaac_lab_official_mimic_replay_promote.py

required inputs:
--isaac-python
--replay-script
--task
--dataset-file
--success-manifest
--replay-success-manifest
--replay-failure-manifest
--summary-file
--log-dir

official runner post-run:
generation command -> replay promoter command -> training import refresh
```

Replay output contract:

```text
mimic/replay_successes.jsonl
  rows promoted to training.eligible=true

mimic/replay_failures.jsonl
  rows kept as training.eligible=false
  training.exclusion_reason=official_replay_validation_failed

mimic/replay_validation_summary.json
  candidate_count
  replay_success_count
  replay_failure_count
  promoted_count
  training_eligible_count
```

Output check contract:

```text
validate_mimic_replay:
  passed when there are no replay failures and no official replay-required pending rows
  blocked with MIMIC_REPLAY_FAILURES_PRESENT when replay_failures.jsonl has rows
  blocked with MIMIC_REPLAY_VALIDATION_PENDING when official candidate rows still require replay
```

Current live subset evidence:

```text
run:
runs/isaac_lab_official_mimic_split_live_auto_subset_retry_20260707/

selected source demos:
demo_000000, demo_000001, demo_000002

result:
2 generated successes merged
1 annotation failure
0 generation failures
official replay validation: 1/2 passed
```

This means the next product-facing behavior should be:

```text
GUI shows per-episode official Mimic status:
  annotation success/failure
  generation success/failure
  retry count
  reset xyz/yaw
  generated demo path
  replay validation status

GUI allows:
  generate all selected source episodes
  continue on per-episode failure
  exclude failed synthetic demos from training
  rerun failed episodes only
  replay-audit generated candidate demos
  promote replay-passed demos into training import
```

## Open Technical Risk

Official Mimic will still fail if `target_eef_pose_to_action()` cannot map generated EEF target poses into stable Robotis OMX movement. This is the core gap. The subtask and annotation work is necessary but not sufficient; the action adapter is the make-or-break piece.

The current `joint_replay` path can remain useful for verifying HDF5 export, RGB-D render, and training import, but it should not be used to claim official Mimic generation.

## Current Section 7 Contract

As of the 2026-07-08 live validation, Section 7 is wired to the official Mimic path by default:

```text
mimic_generation_backend = official
mimic_annotation_mode = auto
mimic_trials = 3
mimic_num_envs = 3
domain_randomization_profile = standard
object pose randomization = locked to recorded specimen pose
physics randomization = locked
environment randomization = lighting/material/camera sensor only
```

The live endpoint must launch even when `annotate_source()` reports only a ready-to-launch annotation summary. For the official backend, the wrapper owns per-episode auto annotation before generation. The separate annotation summary is retained as a command/contract artifact, not a launch blocker.

Validated minimal run:

```text
run root:
/home/jin/autonomous_researcher/runs/isaac_lab_official_mimic_gui_path_20260708T144404

source:
dataset local-pi05-v30/jin-20260703-1 episode 0

result:
official generation 1/1 source episode success
official replay validation 1/1 success
Check Lab Outputs PASSED
training import refreshed with real + Isaac RGB-D + official Mimic synthetic rows
```

## GUI/API Launcher Contract Update

The Section 7 GUI/API path must support both Python launch styles:

```text
plain Python or Isaac Sim python.sh:
  <python> <script.py> ...

Isaac Lab launcher:
  /home/jin/IsaacLab/isaaclab.sh -p <script.py> ...
```

Any code that validates or displays `script_path` must resolve the real script
with this rule:

```text
if command[1] == "-p":
  script_path = command[2]
else:
  script_path = command[1]
```

This applies to:

```text
primary official Mimic wrapper
official replay-promotion post-run
joint-replay RGB-D post-run
annotation summary
IL train/eval summaries
live runner preflight
post-run preflight
```

Latest smoke evidence:

```text
run root:
/home/jin/autonomous_researcher/runs/isaac_lab_gui_api_smoke_20260708_191502

result:
official generation 1/1 source episode success
official replay validation 1/1 success
training_eligible_count 1

command shape:
/home/jin/IsaacLab/isaaclab.sh -p \
  /home/jin/autonomous_researcher/scripts/lerobot_isaac_lab_official_mimic_generate.py \
  --isaac-python /home/jin/IsaacLab/isaaclab.sh \
  --episode-indices 0 \
  --process-cooldown-sec 3.0 \
  --robotis-domain-randomization-profile off
```
