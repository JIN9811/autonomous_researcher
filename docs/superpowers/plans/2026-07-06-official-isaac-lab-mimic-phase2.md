# Official Isaac Lab Mimic Phase 2 Visible Replay Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this plan task-by-task. This phase is a validation gate, not the final Mimic generator implementation.

**Goal:** Export a successful real LeRobot session into the official Isaac Lab/robomimic HDF5 shape and replay one source episode through Isaac Lab's official `scripts/tools/replay_demos.py` with the simulator window visible to the operator.

**Selected source dataset:**

```text
/home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1
```

**Selected source HDF5:**

```text
/home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1/sidecar/isaac_lab_synthetic/latest/hdf5/exported_successful_real_episodes.hdf5
```

## Tasks

- [x] Locate latest physical LeRobot dataset and sidecar.
- [x] Build canonical index at the standard 7번 sidecar location without truncating source frames.
- [x] Export source HDF5 from canonical successful real episodes.
- [x] Inspect HDF5 schema, env args, episode count, action/state shapes, initial state, and datagen fields.
- [x] Replay one source episode using official Isaac Lab `replay_demos.py` in visible mode, not headless.
- [x] Record whether replay starts, robot motion appears, and success validation result.

## Commands Used So Far

```bash
PYTHONPATH=/home/jin/autonomous_researcher \
/home/jin/miniconda3/envs/lerobot/bin/python \
/home/jin/autonomous_researcher/scripts/lerobot_isaac_lab_validate.py \
  --action build-synthetic \
  --dataset /home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1 \
  --mode test \
  --max-source-frames 0 \
  --no-enable-replicator \
  --no-enable-mimic \
  --no-enable-rl-teacher \
  --no-require-digital-twin-pass \
  --no-require-physics-pass \
  --no-require-depth-pass \
  --no-require-articulation-pass \
  --fail-on never
```

```bash
PYTHONPATH=/home/jin/autonomous_researcher \
/home/jin/miniconda3/envs/lerobot/bin/python \
/home/jin/autonomous_researcher/scripts/lerobot_isaac_lab_validate.py \
  --action export-hdf5 \
  --dataset /home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1 \
  --mode test \
  --max-source-frames 0 \
  --no-enable-replicator \
  --no-enable-mimic \
  --no-enable-rl-teacher \
  --no-require-digital-twin-pass \
  --no-require-physics-pass \
  --no-require-depth-pass \
  --no-require-articulation-pass \
  --fail-on never
```

## Current Observations

```text
canonical episode count: 50
canonical frame count: 23658
exported HDF5 episode count: 50
exported HDF5 frame count: 23658
RGB-D HDF5 embedding: disabled automatically because frame count exceeds 1000
HDF5 size: 49.27 MiB
env_args.env_name: ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0
demo_000000 actions shape: (473, 7)
demo_000000 action source: isaac_mirror_target for all 473 frames
initial_state: robot root/joints and red_cube root pose are present
datagen_info: object_pose/red_cube, eef_pose/omx, target_eef_pose/omx, and approach/grasp/lift/place signals are present
```

## Replay Gate Command Shape

Visible replay must omit `--headless` and must include `--enable_cameras`, because the Robotis Mimic env spawns RTX cameras:

```bash
PYTHONPATH=/home/jin/autonomous_researcher \
/home/jin/IsaacLab/isaaclab.sh -p /home/jin/IsaacLab/scripts/tools/replay_demos.py \
  --task ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0 \
  --dataset_file <source_hdf5> \
  --select_episodes 0 \
  --validate_success_rate \
  --reset_sim_buffer_each_episode \
  --enable_cameras \
  --external_callback integrations.isaac_lab_robotis_omx.external_callback.register
```

## Phase 2 Result

```text
HDF5 export: PASS
official visible replay startup: PASS after adding --enable_cameras
official visible replay execution: PASS, episode 0 ran to completion
official task success validation: FAIL, Successfully replayed: 0/1
```

The first visible replay attempt failed during env creation because `--enable_cameras` was missing:

```text
RuntimeError: A camera was spawned without the --enable_cameras flag.
```

After adding `--enable_cameras`, the replay launched visibly, loaded `demo_000000`, and completed.

The official success check failed because the replayed live cube state did not satisfy the physical place condition. A follow-up diagnostic on the same episode reported:

```text
action_count: 473
first_cube_pos_w:  [0.3492, 0.3019, 0.0152]
final_cube_pos_w:  [0.5869, 0.0795, 0.1190]
final_eef_pos_w:   [0.3178, 0.1063, 0.0595]
final_gripper:     0.6155
approach: false
grasp: false
lift: true
place: false
success: false
left/right contact force: 0.0 / 0.0
```

The task success term is `physical_observations.place()`, which requires the cube to be within 3.5 cm of `(x=0.52, y=0.30)` and below `z=0.055`. The replayed cube was lifted but ended far from that target and above the height threshold.

## Next Blocker

Phase 3 must make the source replay gate pass before official Mimic generation is trusted. The current blocker is not HDF5 schema or action dimensionality. The blocker is replay fidelity against the physical success condition:

```text
SOURCE_REPLAY_SUCCESS_FAILED
```

Likely next checks:

- Compare the original Isaac mirror replay route against official Lab replay for the same `demo_000000`.
- Verify the physical place target used during recording/rendering matches `PLACE_TARGET_XY_M = (0.52, 0.30)`.
- Decide whether the source success gate should use recorded episode completion metadata first, or require physics replay success before official Mimic annotation.
- Increase/repair contact report capacity separately; replay emitted repeated `maxContactDataCount = 32` warnings, so contact auditing is currently lossy during grasp/contact-heavy frames.

## 2026-07-07 Progress Update

Current code has since aligned the physical place target with the right cylinder target in the stage:

```text
PLACE_TARGET_XY_M = (0.590, 0.078)
PLACE_TARGET_CUBE_CENTER_Z_M = 0.119
PLACE_RADIUS_M = 0.050
PLACE_HEIGHT_RANGE_M = [0.095, 0.145]
stage target: /World/Workspace/RightDiskAluminumTop at (0.590, 0.078, 0.052)
```

The previous diagnostic final cube pose:

```text
final_cube_pos_w = [0.5869, 0.0795, 0.1190]
```

is inside the current place target tolerance. A fresh official replay gate was rerun against the current source HDF5:

```text
source HDF5:
/home/jin/.cache/huggingface/lerobot/jin/20260703_1/sidecar/isaac_lab_synthetic/latest/hdf5/exported_successful_real_episodes.hdf5

command:
PYTHONPATH=/home/jin/autonomous_researcher \
/home/jin/IsaacLab/isaaclab.sh -p /home/jin/IsaacLab/scripts/tools/replay_demos.py \
  --task ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0 \
  --dataset_file /home/jin/.cache/huggingface/lerobot/jin/20260703_1/sidecar/isaac_lab_synthetic/latest/hdf5/exported_successful_real_episodes.hdf5 \
  --select_episodes 0 \
  --validate_success_rate \
  --reset_sim_buffer_each_episode \
  --enable_cameras \
  --headless \
  --rendering_mode performance \
  --external_callback integrations.isaac_lab_robotis_omx.external_callback.register

log:
runs/isaac_lab_official_replay/replay_demo0_20260707_004524.log
```

Observed result:

```text
official replay startup: PASS
official replay execution: PASS
official task success validation: PASS, Successfully replayed: 1/1
action term: ContactLimitedJointPositionAction, shape 7
policy RGB-D observations: top/front/right RGB-D present
subtask_terms exposed: approach, grasp, lift, place, release, retract
```

Updated Phase 2 blocker status:

```text
SOURCE_REPLAY_SUCCESS_FAILED: RESOLVED for demo_000000 under the current right-cylinder place target.
```

Next pipeline stage is no longer source replay repair. Continue to the official Mimic compatibility work:

1. Rename/contract current GUI and summaries so `joint_replay` is explicitly a replay/debug backend.
2. Change the physical Mimic config to the 3-subtask contract:
   - `cube_lifted`
   - `released_at_target`
   - final retract with `None`
3. Repair `get_subtask_term_signals()` so official annotation can read those term names.
4. Validate annotated HDF5 through `DataGenInfoPool.load_from_dataset_file()`.
5. Run the first official `generate_dataset.py` one-episode smoke.

## 2026-07-08 Official Mimic Gate Update

The official per-episode wrapper now passes the recorded red cube reset pose to both the annotation command and the generation command:

```text
--robotis-cube-reset-xyz <recorded initial cube xyz>
--robotis-cube-reset-yaw <recorded initial cube yaw>
```

This fixed a command-contract gap, but it did not make every source episode valid for official Mimic. Official `annotate_demos.py --auto` ignores the exported source HDF5's time-based success labels and replays the action sequence in the Lab physics scene. A source episode is usable for official Mimic only if that physical replay satisfies the current `task_success = place(env)` condition.

Key diagnostic results:

```text
demo_000000 debug replay:
  success: true
  final cube: [0.5889, 0.0821, 0.1190]
  max signals: approach=1, grasp=1, lift=1, place=1, released_at_target=1

demo_000001 debug replay:
  success: false
  final cube: [0.3498, 0.3183, 0.0151]
  max signals: approach=0, grasp=0, lift=0, place=0, released_at_target=0

demo_000001 with demo_000000 cube initial pose:
  success: false
  max signals: approach=1, grasp=1, lift=0, place=0
```

Exporter note:

```text
obs/datagen_info/object_pose/red_cube is currently constant at the recorded initial cube pose.
obs/datagen_info/subtask_term_signals/place and released_at_target are generated from frame fractions.
```

Therefore the source HDF5 is a valid structural export, but its prefilled subtask signals are not proof that official Lab physics replay succeeded. The official path must treat annotation/generation success manifests as the trust gate.

Small official wrapper gate, episodes 0-4, 1 trial each:

```text
selected source episodes: 5
success source episodes: 2
failed source episodes: 3
merged generated demos: 2

demo_000000: annotation pass, generation initially hit Kit startup segfault without cooldown
demo_000001: annotation failed, physical replay never reached cube
demo_000002: annotation pass, generation produced 0/1 success
demo_000003: annotation pass, generation produced 1/1 success
demo_000004: annotation pass, generation produced 1/1 success
```

The wrapper now sleeps after each Isaac subprocess:

```text
--process-cooldown-sec 3.0
```

A rerun of demo_000000 with the cooldown produced:

```text
status: success
annotation_count: 1
success_count: 1
merged_success_count: 1
```

Current conclusion:

```text
official Mimic is working, but only for source episodes that pass physical replay and generated rollout success.
The pipeline must not assume 50 source episodes => 50 official Mimic source episodes.
Real LeRobot data remains preserved; only Lab synthetic/Mimic training rows should use replay-promoted successes.
```

## 2026-07-07 Phase 4/5 Progress Update

Implemented and verified the official term-signal contract for the physical Robotis OMX Mimic task.

Current 3-subtask config:

```text
Subtask 0: object_ref=red_cube, subtask_term_signal=cube_lifted
Subtask 1: object_ref=place_target, subtask_term_signal=released_at_target
Subtask 2: object_ref=place_target, subtask_term_signal=None
```

Compatibility behavior:

```text
old signals retained: approach, grasp, lift, place, release, retract
official aliases added: cube_lifted, released_at_target
cube_lifted source: lift(env)
released_at_target source: release(env)
```

HDF5/export behavior:

```text
datagen_info/subtask_term_signals now includes:
approach, grasp, lift, place, cube_lifted, released_at_target

GUI/runner manifest required_subtasks now uses:
approach, grasp, lift, place, cube_lifted, released_at_target
```

Verification:

```text
/home/jin/IsaacLab/_isaac_sim/python.sh -m pytest -q \
  tests/unit/test_isaac_lab_robotis_omx_registration.py::test_physical_mimic_subtasks_match_successful_replay_boundaries \
  tests/unit/test_isaac_lab_robotis_omx_registration.py::test_physical_mimic_adapter_preserves_successful_joint_replay_contract

result: 2 passed

/home/jin/IsaacLab/_isaac_sim/python.sh -m pytest -q \
  tests/unit/test_lerobot_isaac_lab_synthetic.py::test_isaac_lab_export_hdf5_writes_successful_real_episode_in_frame_order \
  tests/unit/test_lerobot_isaac_lab_synthetic.py::test_isaac_lab_mimic_and_rl_smoke_actions_write_launch_artifacts

result: 2 passed

python3 -m py_compile \
  integrations/isaac_lab_robotis_omx/mdp/physical_observations.py \
  integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_mimic_env.py \
  integrations/isaac_lab_robotis_omx/robotis_omx_physical_mimic_env_cfg.py \
  integrations/isaac_lab_robotis_omx/robotis_omx_physical_env_cfg.py \
  device_bridges/isaac_lab_hdf5.py \
  device_bridges/isaac_lab_synthetic.py

result: PASS
```

Updated status:

```text
Phase 4: DONE for physical Mimic 3-subtask signal names.
Phase 5: DONE for env API signal alias exposure.
Next: Phase 6/7 annotation gate and DataGenInfoPool validation.
```

## 2026-07-07 Phase 6/7 Progress Update

Implemented the official annotation gate validation for the preannotated physical HDF5 path.

Why this was needed:

```text
Existing 20260703_1 source HDF5 used legacy subtask signals:
approach, grasp, lift, place

The official physical Mimic config now requires:
cube_lifted, released_at_target, None
```

New behavior:

```text
source HDF5: preserved unchanged
annotated HDF5 copy: normalized for official Mimic

legacy alias repair:
lift -> cube_lifted
release -> released_at_target
fallback when release is absent:
place -> released_at_target
```

The annotation passthrough step now writes these reports:

```text
hdf5/annotation_signal_alias_report.json
hdf5/annotation_contract_report.json
hdf5/annotation_datagen_pool_report.json
hdf5/annotation_summary.json
```

Real current-session validation:

```text
dataset:
/home/jin/.cache/huggingface/lerobot/jin/20260703_1

source:
sidecar/isaac_lab_synthetic/latest/hdf5/exported_successful_real_episodes.hdf5

annotated output:
sidecar/isaac_lab_synthetic/latest/hdf5/source_real_success_annotated.hdf5

annotation status: completed
signal_alias_ok: true
signal_alias_added_count: 100
contract_ok: true
datagen_pool_ok: true
datagen_pool_num_infos: 50
```

Verification:

```text
/home/jin/IsaacLab/_isaac_sim/python.sh -m pytest -q \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_preannotated_hdf5_passthrough_completes_without_runner \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_hdf5_contract_loads_into_official_datagen_info_pool

result: 2 passed

python3 -m py_compile \
  device_bridges/isaac_lab_hdf5.py \
  device_bridges/isaac_lab_synthetic.py \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py

result: PASS
```

Updated status:

```text
Phase 6: DONE for preannotated passthrough normalization and annotation gate reports.
Phase 7: DONE for official DataGenInfoPool.load_from_dataset_file() validation on the 50-episode current source.
Next: Phase 8/10 official generate_dataset one-episode smoke.
```

## 2026-07-07 Phase 8/10 Progress Update

Official Isaac Lab Mimic one-episode generation has now been tested against demo 0.

Key findings:

```text
official annotate_demos.py --auto: PASS for demo 0
auto annotated file:
runs/isaac_lab_official_mimic_smoke/source_demo0_auto_annotated.hdf5

DataGenInfoPool validation: PASS
subtask boundaries:
  [0, 241] cube_lifted
  [241, 298] released_at_target
  [298, 473] final retract
object refs:
  red_cube
  place_target
```

The first official `generate_dataset.py` attempt using the auto-annotated demo ran, but the generated trajectory missed the cube:

```text
generated success: 0/1
generated initial cube pose: approximately [0.400, 0.300, 0.015]
source initial cube pose: [0.349205, 0.301937, 0.015200]
generated min eef-object distance: approximately 0.073 m
```

Root cause:

```text
OFFICIAL_MIMIC_GENERATION_GRASP_MISS was caused by source/object reset mismatch.
The generated env reset cube pose did not match the source demo cube pose, so the generated EEF path was valid in shape but aimed at the wrong cube location.
```

After adding a generation debug reset override and setting the cube reset to the source demo 0 initial pose, the same official generation smoke passed:

```text
command output: 1/1 successful demos generated by mimic
output:
runs/isaac_lab_official_mimic_smoke/generated_dataset_demo0_auto_reset_debug.hdf5

success demos: demo_0
num_samples: 491
success attr: True
first_obj_xyz: [0.349205, 0.301937, 0.015200]
final_obj_xyz: [0.587523, 0.080777, 0.119000]
max_obj_z: 0.181551
min_place_xy_dist: 0.003719 m
min_eef_obj_dist: 0.034371 m
action_shape: [491, 7]
gripper action range: [0.002302, 0.628319]
```

Implementation notes already in code:

```text
external_callback.py accepts:
  --robotis-mimic-generation-guarantee
  --robotis-mimic-keep-failed
  --robotis-cube-reset-xyz
  --robotis-cube-reset-yaw

mdp/events.py applies ROBOTIS_OMX_CUBE_RESET_XYZ/YAW during cube reset and suppresses xy randomization when an explicit pose is provided.
```

Updated status:

```text
Phase 8: PARTIAL. Official backend can run through generate_dataset.py, but the standard GUI/runner path must auto-pass source cube reset pose.
Phase 9: PARTIAL. Current action adapter is sufficient for deterministic source-pose smoke; broader retargeting/randomization is still not proven.
Phase 10: PASS for demo 0 with source-pose reset override.
Next: standardize source-pose reset in the official backend, then run Phase 11 small generated_dataset_small.hdf5 with 10-30 trials and replay validation.
```

## 2026-07-07 Phase 11 Progress Update

The standard runner path was updated after the Phase 10 smoke result.

Code behavior now:

```text
Official Mimic runner command reads the first source demo red_cube pose from:
data/demo_xxxxxx/initial_state/rigid_object/red_cube/root_pose

It passes that pose to generate_dataset.py as:
--robotis-cube-reset-xyz
--robotis-cube-reset-yaw

The generation_config now exposes:
source_object_reset.enabled = true
source_object_reset.policy = lock_generation_reset_to_source_demo_initial_pose
```

The official Mimic trajectory-generation profile was also changed:

```text
generate_dataset.py trajectory generation: --robotis-domain-randomization-profile off
requested GUI profile, e.g. standard: retained in generation_config.environment_randomization
visual/environment domain randomization: should be applied during RGB-D render, not during physics trajectory generation
```

Why this change was needed:

```text
10-trial test with profile=standard timed out after 5 failed attempts.
Failed HDF5 showed cube z falling to approximately -327 m.
All failed attempts had correct initial cube pose, but the cube never lifted:
  max_obj_z: 0.0152
  min_eef_obj_dist: approximately 0.179 m
  min_place_xy_dist: approximately 0.329 m

Conclusion:
standard profile is unsafe for the physics trajectory generation stage. Keep physics/object/material reset locked/off there, then apply visual domain randomization during render.
```

Verified small generation with the corrected off-profile path:

```text
input:
runs/isaac_lab_official_mimic_smoke/source_demo0_auto_annotated.hdf5

output:
runs/isaac_lab_official_mimic_smoke/generated_dataset_demo0_auto_reset_3_off.hdf5

generate_dataset result:
3/3 successful demos generated by mimic
exit status: 0
log:
runs/isaac_lab_official_mimic_smoke/generate_demo0_auto_reset_3_off_20260707_015811.log
```

Generated HDF5 metrics:

```text
demo_count: 3
num_samples per demo: 491
success attr: True for demo_0, demo_1, demo_2
final_obj_xyz:
  demo_0: [0.586348, 0.080325, 0.119000]
  demo_1: [0.589135, 0.081132, 0.119000]
  demo_2: [0.587537, 0.080732, 0.119000]
min_place_xy_dist:
  demo_0: 0.004326 m
  demo_1: 0.000960 m
  demo_2: 0.003678 m
min_eef_obj_dist:
  demo_0: 0.033747 m
  demo_1: 0.036888 m
  demo_2: 0.035028 m
```

Replay validation:

```text
Replay demo_0 and demo_1 together:
  Successfully replayed 1 episode out of 1 demos.
  Successfully replayed 2 episodes out of 2 demos.
  Full 3-demo replay hit timeout while loading demo_2 because camera-enabled replay is slow.

Replay demo_2 separately:
  Successfully replayed: 1/1
  exit status: 0
  log:
  runs/isaac_lab_official_mimic_smoke/replay_generated_demo2_reset_3_off_20260707_021418.log
```

Verification:

```text
/home/jin/IsaacLab/_isaac_sim/python.sh -m pytest -q \
  tests/unit/test_lerobot_bridge.py::test_live_isaac_lab_mimic_runner_launches_file_backed_job \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_preannotated_hdf5_passthrough_completes_without_runner \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_hdf5_contract_loads_into_official_datagen_info_pool \
  tests/unit/test_isaac_lab_robotis_omx_registration.py::test_external_callback_consumes_robotis_mimic_generation_debug_args \
  tests/unit/test_isaac_lab_robotis_omx_registration.py::test_physical_mimic_generation_debug_env_can_disable_guarantee

result: 5 passed

python3 -m py_compile device_bridges/isaac_lab_synthetic.py tests/unit/test_lerobot_bridge.py

result: PASS
```

Updated status:

```text
Phase 11: PASS for demo 0 small official Mimic generation with 3 successful trials.
Replay validation: PASS for all 3 generated demos, with demo_2 validated separately due camera-enabled replay timeout in the combined run.
Next: implement per-episode official generation splitting before scaling to all 50 episodes, because the current reset override is one pose per generate_dataset.py process.
```

## 2026-07-07 Phase 12 Progress Update

Implemented the per-episode official Mimic generation split needed before scaling to all 50 recorded source episodes.

Why this was needed:

```text
generate_dataset.py accepts one cube reset override per process.
The current real dataset has per-episode active-cam cube poses.
Running all source demos in one process would apply one reset pose to every demo and recreate the previous grasp-miss failure.
```

New standard official generation path:

```text
source_real_success_annotated.hdf5
  -> one-demo shard per selected source episode
  -> read that shard's initial_state/rigid_object/red_cube/root_pose
  -> launch official generate_dataset.py for that one shard
  -> pass --robotis-cube-reset-xyz and --robotis-cube-reset-yaw for that source episode
  -> collect successes.jsonl and failures.jsonl
  -> merge successful generated HDF5 demos into generated_dataset.hdf5
```

New script:

```text
scripts/lerobot_isaac_lab_official_mimic_generate.py
```

Bridge behavior:

```text
device_bridges/isaac_lab_synthetic.py official backend now launches the wrapper script.
The wrapper script launches Isaac Lab's official scripts/imitation_learning/isaaclab_mimic/generate_dataset.py per source episode.
trajectory-generation domain randomization remains off.
visual/environment randomization remains a later RGB-D render concern.
```

The runner manifest now exposes:

```text
per_episode_generation.enabled = true
per_episode_generation.shard_policy = one_demo_hdf5_per_source_episode
per_episode_generation.source_object_reset_policy = per_episode_initial_red_cube_pose
per_episode_generation.success_manifest = mimic/successes.jsonl
per_episode_generation.failure_manifest = mimic/failures.jsonl
per_episode_generation.summary_file = mimic/official_mimic_summary.json
```

Real current-session dry-run validation on the 20260703_1 annotated source:

```text
input:
/home/jin/.cache/huggingface/lerobot/jin/20260703_1/sidecar/isaac_lab_synthetic/latest/hdf5/source_real_success_annotated.hdf5

selected episodes:
0, 1, 2

output:
runs/isaac_lab_official_mimic_split_dry_run/

selected_demo_count: 3
success manifest rows: 3
failure manifest rows: 0
all one-demo shard files exist: true
row status: dry_run_ready
```

The dry-run confirmed per-demo cube resets are being read from the source HDF5, not reused globally:

```text
demo_000000 reset xyz/yaw: [0.349205, 0.301937, 0.0152] / 0.000000
demo_000001 reset xyz/yaw: [0.340588, 0.319838, 0.0152] / 0.593272
demo_000002 reset xyz/yaw: [0.335597, 0.308643, 0.0152] / -0.251886
```

Verification:

```text
/home/jin/IsaacLab/_isaac_sim/python.sh -m pytest -q \
  tests/unit/test_lerobot_bridge.py::test_live_isaac_lab_mimic_runner_launches_file_backed_job \
  tests/unit/test_lerobot_isaac_lab_official_mimic_wrapper.py::test_official_mimic_wrapper_dry_run_creates_one_shard_per_source_demo \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_preannotated_hdf5_passthrough_completes_without_runner \
  tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_hdf5_contract_loads_into_official_datagen_info_pool

result: 4 passed, 39 warnings

python3 -m py_compile \
  device_bridges/isaac_lab_synthetic.py \
  scripts/lerobot_isaac_lab_official_mimic_generate.py \
  tests/unit/test_lerobot_bridge.py \
  tests/unit/test_lerobot_isaac_lab_official_mimic_wrapper.py

result: PASS
```

Current status:

```text
Phase 12: implemented and dry-run verified for per-episode command/shard/reset wiring.
Not yet completed: live non-dry-run per-episode official generation across multiple source episodes.
Next: run a live small subset through the wrapper, e.g. episodes 0,1,2 with one trial each, then replay generated successes before enabling all-episode generation from GUI.
```

## 2026-07-07 Phase 13 Progress Update

Ran the live per-episode official Mimic subset and found the real blocker in the earlier failed generation path.

Root cause:

```text
source_real_success_annotated.hdf5 contained a datagen_info/target_eef_pose dataset with the correct shape but the wrong semantics.
The matrix translation entries were effectively joint/action values, not real end-effector workspace poses.
Isaac Lab DataGenInfoPool validates shape and loads the file, but that does not prove the recorded target_eef_pose is physically meaningful.
That is why direct generate_dataset.py calls produced trajectories that missed the cube even though the HDF5 contract test passed.
```

Fix implemented:

```text
scripts/lerobot_isaac_lab_official_mimic_generate.py now treats the source HDF5 as the raw demo carrier.
For each selected source demo:
  1. copy one source demo into source.hdf5
  2. run official annotate_demos.py --auto on that one-demo shard
  3. use the official annotated.hdf5 as generate_dataset.py input
  4. pass that source episode's red_cube reset pose only to generation
  5. retry annotation/generation according to wrapper retry settings
  6. merge successful generated demos only
```

Important correction:

```text
Do not pass --robotis-cube-reset-xyz/yaw to annotation.
Annotation must replay the recorded source demo as-is.
The cube reset override belongs only to generation, where Mimic rolls out a new generated trajectory from the recorded object pose.
```

Wrapper/bridge updates:

```text
device_bridges/isaac_lab_synthetic.py official backend now passes:
  --annotate-script /home/jin/IsaacLab/scripts/imitation_learning/isaaclab_mimic/annotate_demos.py
  --annotation-mode auto
  --generate-script /home/jin/IsaacLab/scripts/imitation_learning/isaaclab_mimic/generate_dataset.py

The wrapper also handles isaaclab.sh correctly by launching:
  isaaclab.sh -p <official_script.py> ...

Retry defaults:
  annotation-retries = 2
  generation-retries = 1
```

Live validation command:

```text
input:
/home/jin/.cache/huggingface/lerobot/jin/20260703_1/sidecar/isaac_lab_synthetic/latest/hdf5/source_real_success_annotated.hdf5

selected episodes:
0, 1, 2

trials per episode:
1

output:
runs/isaac_lab_official_mimic_split_live_auto_subset_retry_20260707/
```

Live validation result:

```text
summary.status = partial_success
summary.ok = true
selected_demo_count = 3
success_source_episode_count = 2
failed_source_episode_count = 1
annotation_failure_count = 1
generation_failure_count = 0
merged_success_count = 2
```

Per-source result:

```text
demo_000000:
  annotation 1/1 succeeded
  generation 1/1 succeeded

demo_000001:
  annotation failed after 3 attempts
  official log reason: final task was not completed; skipped exporting the episode due to incomplete subtask annotations
  generation was not attempted

demo_000002:
  annotation 1/1 succeeded
  generation 1/1 succeeded
```

Merged generated HDF5 check:

```text
generated_dataset.hdf5 exists
merged demos: demo_0, demo_1

demo_0:
  num_samples = 491
  initial cube xyz = [0.349205, 0.301937, 0.015200]
  final cube xyz = [0.586767, 0.081277, 0.119000]
  max cube z = 0.181268

demo_1:
  num_samples = 368
  initial cube xyz = [0.335597, 0.308643, 0.015200]
  final cube xyz = [0.585810, 0.080596, 0.119000]
  max cube z = 0.211477
```

Replay gate result:

```text
command:
/home/jin/IsaacLab/isaaclab.sh -p /home/jin/IsaacLab/scripts/tools/replay_demos.py \
  --task ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0 \
  --dataset_file runs/isaac_lab_official_mimic_split_live_auto_subset_retry_20260707/generated_dataset.hdf5 \
  --select_episodes 0 1 \
  --validate_success_rate \
  --reset_sim_buffer_each_episode \
  --enable_cameras \
  --headless \
  --rendering_mode performance

log:
runs/isaac_lab_official_mimic_split_live_auto_subset_retry_20260707/replay/replay_generated_0_1_20260707_122152.log

result:
Successfully replayed: 1/2
failed demo ids: [1]
```

The failed generated demo was replayed again by itself:

```text
log:
runs/isaac_lab_official_mimic_split_live_auto_subset_retry_20260707/replay/replay_generated_1_only_20260707_122643.log

result:
Successfully replayed: 0/1
failed demo ids: [1]
```

Code policy update:

```text
Official Mimic generation success is now treated as a candidate, not immediately train-ready.
The wrapper writes per-generated-demo success rows with:
  metrics.official_mimic = true
  metrics.replay_required = true
  metrics.lab_step_replay = false
  training.eligible = false
  training.exclusion_reason = official_replay_validation_required

device_bridges/isaac_lab_synthetic.py excludes official Mimic rows from training import until a later replay-validation step promotes them.
```

Updated gate:

```text
Phase 13 confirms the official auto-annotation + per-episode generation path can produce successful generated demos.
Replay validation showed that not every generated success is replay-stable.
The next implementation gate is a replay-validation/promote step:
  1. replay generated candidate demos
  2. mark replay-passed demos as training.eligible=true and lab_step_replay=true
  3. keep replay-failed demos out of synthetic training
  4. expose annotation failures and replay failures separately in the GUI
```

## 2026-07-07 Phase 14 Progress Update

Implemented the official Mimic replay validator/promoter gate.

New script:

```text
scripts/lerobot_isaac_lab_official_mimic_replay_promote.py
```

Behavior:

```text
Input:
  mimic/generated_dataset.hdf5
  mimic/successes.jsonl

For each official Mimic generated candidate row:
  1. parse generated_demo, e.g. demo_0 -> select episode 0
  2. run official Isaac Lab scripts/tools/replay_demos.py
  3. require --validate_success_rate to report Successfully replayed: 1/1
  4. rewrite mimic/successes.jsonl with replay_validation metadata
  5. write mimic/replay_successes.jsonl
  6. write mimic/replay_failures.jsonl
  7. write mimic/replay_validation_summary.json
```

Promotion rule:

```text
Replay passed:
  metrics.replay_validated = true
  metrics.replay_required = false
  metrics.lab_step_replay = true
  training.eligible = true
  training.exclusion_reason = ""

Replay failed:
  metrics.replay_validated = true
  metrics.replay_required = false
  metrics.lab_step_replay = false
  training.eligible = false
  training.exclusion_reason = official_replay_validation_failed
```

Runner integration:

```text
Official Mimic runner post_run now launches the replay promoter automatically after successful generation.

post_run.stage = replay_validate_after_generation
post_run.summary_file = mimic/replay_validation_summary.json
post_run.replay_success_manifest_path = mimic/replay_successes.jsonl
post_run.replay_failure_manifest_path = mimic/replay_failures.jsonl
```

Output check integration:

```text
Check Lab Outputs now includes validate_mimic_replay.

Blocked conditions:
  MIMIC_REPLAY_FAILURES_PRESENT
  MIMIC_REPLAY_VALIDATION_PENDING
```

GUI integration:

```text
The existing Check Lab Outputs failure list now labels replay issues as:
  Mimic replay failed
  Mimic replay pending
```

## 2026-07-08 Phase 15 Progress Update

Validated the product-facing Section 7/API path for the official Mimic branch.

Code path:

```text
POST /api/lerobot/isaac-lab/domain-mimic/run
  -> build_synthetic
  -> export_hdf5
  -> annotate_source launch summary
  -> official Mimic wrapper launch
  -> post_run replay_validate_after_generation
  -> build_synthetic training import refresh
  -> check_outputs
```

Fixes made during validation:

```text
1. Section 7 default backend is now official Isaac Lab Mimic, not joint_replay.
2. Section 7 uses mimic_annotation_mode=auto.
3. Section 7 explicitly disables static marker-only physics/articulation gates for this live pipeline,
   matching the existing successful latest run contract.
4. Live e2e launch no longer requires a separately completed annotation artifact for official Mimic,
   because the official wrapper runs per-episode auto annotation before generation.
5. Browser cachebuster was updated so the GUI loads the new Section 7 payload.
```

Live validation evidence:

```text
run:
/home/jin/autonomous_researcher/runs/isaac_lab_official_mimic_gui_path_20260708T144404

dataset:
/home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1

source episode:
0

request:
mimic_generation_backend=official
mimic_trials=1
mimic_num_envs=1
mimic_annotation_mode=auto
isaac_lab_episode_indices=0

result:
initial endpoint status=RUNNING
official generation completed
post_run replay validation completed
Check Lab Outputs PASSED
```

Output check summary:

```text
episode_count: 1
canonical_frame_count: 473
expected_mimic_candidates: 3
mimic_candidate_count: 3
mimic_success_count: 1
mimic_failure_count: 0
mimic_replay_success_count: 1
mimic_replay_failure_count: 0
mimic_replay_pending_count: 0
training_row_count: 3
training_candidate_row_count: 3
```

Generated artifacts:

```text
mimic/generated_dataset.hdf5
mimic/official_mimic_summary.json
mimic/successes.jsonl
mimic/replay_successes.jsonl
mimic/replay_failures.jsonl
mimic/replay_validation_summary.json
training_import/manifest.jsonl
training_import/summary.json
```

Confirmed replay promotion:

```text
official_mimic_demo_000000_demo_0
metrics.official_mimic = true
metrics.lab_step_replay = true
metrics.replay_validated = true
metrics.replay_required = false
training.eligible = true
```

Next gate:

```text
Run the same Section 7 official Mimic path over multiple source episodes.
Use overwrite-all only after validating disk budget because the per-episode source shard can be hundreds of MB.
Then verify generated RGB-D render and training ingestion for the expanded official Mimic dataset.
```

## 2026-07-08 Phase 16 Progress Update

Ran the multi-source official Mimic gate over three recorded episodes and fixed the training-import handoff found by that gate.

Live validation evidence:

```text
run:
/home/jin/autonomous_researcher/runs/isaac_lab_official_mimic_multi_ep_gate_20260708T150338

dataset:
/home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1

source episodes:
0, 1, 2

request:
mimic_generation_backend=official
mimic_trials=1
mimic_num_envs=1
mimic_annotation_mode=auto
isaac_lab_episode_indices=0,1,2
attempts_per_source_frame=3
```

Observed result:

```text
official generation completed
post_run replay validation completed
2 source episodes generated replay-passed official Mimic demos
1 source episode failed auto annotation and stayed excluded from training
Check Lab Outputs PASSED after training import refresh
```

Output check summary after fix:

```text
episode_count: 3
canonical_frame_count: 1211
expected_mimic_candidates: 9
mimic_candidate_count: 9
mimic_success_count: 2
mimic_failure_count: 1
mimic_replay_success_count: 2
mimic_replay_failure_count: 0
mimic_replay_pending_count: 0
training_row_count: 8
training_candidate_row_count: 8
training source counts:
  real_lerobot: 3
  isaac_rgbd_render: 3
  isaac_lab_synthetic: 2
```

Fixes made during this gate:

```text
1. Official Mimic partial success is accepted when failed source episodes remain excluded
   and replay-passed generated demos are present.
2. Check Lab Outputs now verifies actual training_import/manifest.jsonl rows with
   source_type=isaac_lab_synthetic and source_label=isaac_lab_mimic instead of relying on
   total training row count.
3. Official Mimic summary checks use manifest rows as authoritative for final success/failure
   counts so stale runner hook counts do not mask the real replay promotion state.
4. The live mimic runner stores its request payload and, after replay_validate_after_generation
   post-run completes, automatically refreshes build_synthetic with:
   force_rebuild=false, overwrite_latest=false, resume=true.
5. RGB-D render post-runs are not forced through this training refresh path; the refresh is
   limited to official replay promotion.
```

Next gate:

```text
Use the GUI Section 7 path on a larger episode set with the same official backend.
Verify:
  - status progress moves through generation -> replay validation -> completed
  - training_import source_counts includes isaac_lab_synthetic rows
  - Check Lab Outputs passes without a manual refresh
  - generated official Mimic rows can be selected by the training dataset mix
```

## 2026-07-08 Phase 17 Progress Update

Completed the official Mimic RGB-D post-render gate on the same multi-episode run.

Live validation evidence:

```text
run:
/home/jin/autonomous_researcher/runs/isaac_lab_official_mimic_multi_ep_gate_20260708T150338

dataset:
/home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1

source episodes:
0, 1, 2

official Mimic RGB-D job:
isaac_lab_mimic_20260708T062819809169Z_9558b41e

post-render command:
scripts/lerobot_isaac_lab_joint_replay_mimic.py
  --backend joint_replay
  --rgbd-render-only
  --rgbd-render-backend mirror_http
  --mirror-endpoint http://127.0.0.1:8766/render
  --input-file mimic/generated_dataset.hdf5
  --output-file mimic_rgbd/generated_dataset_rgbd.hdf5
```

RGB-D render result:

```text
status: completed
returncode: 0
success_count: 2
failure_count: 0
visual_demo_count: 2
visual_total_demo_count: 2
replayed_frames: 859
rendered_frames: 859
camera_frame_count:
  front: 859
  right: 859
  top: 859
frame_source_count:
  isaac_sim_mirror_http: 859
rgb/depth png files: 5154
artifact size: 162M
```

Training import after RGB-D refresh:

```text
Check Lab Outputs: PASSED
training_row_count: 10
training_candidate_row_count: 10
training source counts:
  real_lerobot: 3
  isaac_rgbd_render: 3
  isaac_lab_synthetic: 4

isaac_lab_synthetic breakdown:
  source_label=isaac_lab_mimic: 2
  source_label=isaac_lab_mimic_rgbd: 2
```

The two RGB-D rows are train-exposed as `source_type=isaac_lab_synthetic` with
`source_label=isaac_lab_mimic_rgbd`, `generator_source_type=isaac_lab_mimic_rgbd`,
`artifact_path=mimic_rgbd/generated_dataset_rgbd.hdf5`, and
`generation_manifest=../mimic_rgbd/successes.jsonl`.

Visual spot check:

```text
mimic_rgbd/renders/demo_0/front/frame_000000_rgb.png
mimic_rgbd/renders/demo_0/front/frame_000244_rgb.png
mimic_rgbd/renders/demo_0/front/frame_000490_rgb.png
```

These frames show the cube on the A4 sheet, the arm moving into the grasp, and
the cube placed on the cylinder. The RGB-D motion audit also passed for both
generated demos with all three cameras changing across sampled frames.

Fixes made during this gate:

```text
1. The official backend Render Missing Mimic RGB-D path now launches the joint-replay
   RGB-D render command instead of incorrectly reusing the official replay promoter.
2. Section 7 now auto-runs Render Mimic RGB-D after a completed official Mimic
   pipeline when both "Render Mimic RGB-D after generation" and "RGB-D cameras"
   are enabled.
3. The follow-up render uses the same GUI payload/run root instead of falling back
   to an implicit latest run.
4. Static GUI tests now cover the Section 7 auto-render handoff and explicit render
   missing action.
```

Verification:

```text
pytest focused gate:
9 passed in 2.36s

API checks:
/api/lerobot/isaac-lab/build-synthetic -> READY_FOR_TRAINING
/api/lerobot/isaac-lab/check-outputs -> PASSED
```

Next gate:

```text
Run the same official Mimic + post-render path from the GUI Section 7 button.
Verify that the browser progress panel stays attached to the live job, auto-runs
RGB-D post-render when the checkbox is enabled, refreshes training import, and
then shows Check Lab Outputs as PASSED without manual API calls.
```

## 2026-07-08 Phase 18 Progress Update

Completed a GUI/API-path regression pass for Section 7 official Mimic + Mimic
RGB-D post-render on the live `jin-20260703-1` dataset, and fixed the runtime
failure modes found during the pass.

Live validation evidence:

```text
dataset:
/home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-20260703-1

canonical output root:
/home/jin/.cache/huggingface/lerobot/jin/20260703_1/sidecar/isaac_lab_synthetic/latest

GUI Section 7 official Mimic job:
isaac_lab_mimic_20260708T071019188059Z_48a2e868

Mimic generation:
--trials-per-episode 9
--num-envs 1
generation success_count: 9
generation failure_count: 0
replay success_count: 9
replay failure_count: 0

Mimic RGB-D post-render repair job:
isaac_lab_mimic_20260708T075354941241Z_2d01006b
status: completed
returncode: 0
success_count: 9
failure_count: 0
replayed_frames: 4419
rendered_frames: 4419
visual_demo_count: 9
visual_total_demo_count: 9
```

Root causes fixed:

```text
1. Official Mimic generation failed with 3 domain variants x 3 Mimic trials when
   launched as --generation_num_trials 3 --num_envs 3. The Robotis scene is now
   serialized for this path as --generation_num_trials 9 --num_envs 1.

2. Section 7 auto-started Mimic RGB-D a second time after the first RGB-D render
   completed. The poller now detects rgbd_render_after_generation and does not
   recursively launch another render.

3. A stopped/failed Mimic RGB-D render could destroy the previous successful
   output because the renderer emptied mimic_rgbd/renders and root manifests at
   startup. The renderer now writes to mimic_rgbd/.render_staging and commits to
   the final output only after success.

4. Progress reporting initially only counted final render folders. It now also
   counts staging manifests while a render is active, and prefers staging over
   stale final folders.

5. RGB-D success rows used generated demo index as source_episode_index when the
   official HDF5 lacked provenance attrs. This made demo_4/demo_7 look like real
   episodes 4/7 and contact-audit exclusion removed them from training. The RGB-D
   renderer now reads mimic/successes.jsonl for generated_demo -> source episode
   mapping and falls back to 0 instead of demo index.

6. Training import refresh after post-run only ran for replay validation. It now
   also runs after rgbd_render_after_generation, with physics/articulation
   preflight disabled for this metadata refresh step.
```

Current artifact state after repair:

```text
mimic/successes.jsonl: 9 rows
mimic/failures.jsonl: 0 rows
mimic/replay_successes.jsonl: 9 rows
mimic/replay_failures.jsonl: 0 rows

mimic_rgbd/successes.jsonl: 9 rows
mimic_rgbd/failures.jsonl: 0 rows
mimic_rgbd/manifest.jsonl: 4419 rows
mimic_rgbd/renders/demo_*: 9 demo folders

training_import/summary.json:
  status: passed
  row_count: 114
  source_counts:
    real_lerobot: 50
    isaac_rgbd_render: 46
    isaac_lab_synthetic: 18
  synthetic breakdown:
    isaac_lab_mimic: 9
    isaac_lab_mimic_rgbd: 9
```

Visual spot check:

```text
mimic_rgbd/renders/demo_0/front/frame_000000_rgb.png
  cube starts on the A4 sheet.

mimic_rgbd/renders/demo_0/front/frame_000245_rgb.png
  robot is grasping/moving the cube.

mimic_rgbd/renders/demo_0/front/frame_000490_rgb.png
  cube is on top of the cylinder.
```

Strict Check Lab Outputs status:

```text
validate_canonical_episode_index: passed
validate_hdf5_export: passed after re-exporting all 50 successful real episodes
validate_mimic_replay: passed
validate_training_import: passed

remaining blocker:
validate_mimic_generation -> MIMIC_CANDIDATE_COUNT_MISMATCH

reason:
The current latest dataset has 50 real episodes, but the repaired official Mimic
artifact is a 9-candidate run from the existing generated Mimic set. Training can
consume the 18 synthetic rows now, but a full strict dataset-level pass requires
generating Mimic candidates for all selected source episodes.
```

Verification:

```text
pytest focused regression:
16 passed in 4.56s

live API:
/api/lerobot/isaac-lab/mimic-rgbd/render-missing
  -> completed, returncode 0, success_count 9, failure_count 0

/api/lerobot/isaac-lab/build-synthetic
  -> READY_FOR_TRAINING, training_import row_count 114

/api/lerobot/isaac-lab/export-hdf5
  -> READY_FOR_HDF5, exported_episode_count 50, exported_frame_count 23658
```

Next gate:

```text
Decide whether Section 7 should run official Mimic over all 50 episodes by
default, or expose a bounded episode selector for incremental full-coverage
generation. Full 50 x 3 x 3 plus RGB-D render is much larger than the repaired
9-candidate smoke set and should be run as a planned batch, not as an implicit
quick check.
```

## 2026-07-08 GUI/API Official Mimic Smoke

Validated the actual Section 7 API path with a non-destructive output root:

```text
endpoint:
/api/lerobot/isaac-lab/run-mimic

dataset:
/home/jin/.cache/huggingface/lerobot/jin/20260703_1

output root:
/home/jin/autonomous_researcher/runs/isaac_lab_gui_api_smoke_20260708_191502

request:
mode=live
mimic_generation_backend=official
mimic_annotation_mode=auto
isaac_lab_episode_indices=0
mimic_trials=1
attempts_per_source_frame=1
mimic_num_envs=1
mimic_enable_cameras=false
isaac_sim_python=/home/jin/IsaacLab/isaaclab.sh
```

Two GUI/launcher path bugs were found and fixed:

```text
1. isaaclab.sh launch syntax
   The bridge generated:
     isaaclab.sh <wrapper.py> ...
   but Isaac Lab requires:
     isaaclab.sh -p <wrapper.py> ...

2. script_path preflight
   After adding -p, runner preflight still treated command[1] as the script,
   so it checked "-p" as a file and blocked the job. Script path resolution now
   skips -p and uses command[2].
```

Validated result:

```text
official annotation: pass, annotation_count=1
official generation: pass, merged_success_count=1
official replay validation: pass, Successfully replayed 1/1
training import refresh: pass

mimic/generated_dataset.hdf5:
  demos: demo_0
  num_samples: 491
  success: true
  actions: (491, 7)

mimic/replay_validation_summary.json:
  candidate_count: 1
  replay_success_count: 1
  replay_failure_count: 0
  promoted_count: 1
  training_eligible_count: 1

training_import/summary.json:
  status: passed
  row_count: 3
  source_counts:
    real_lerobot: 1
    isaac_rgbd_render: 1
    isaac_lab_synthetic: 1
```

Regression coverage added:

```text
test_official_mimic_runner_uses_isaaclab_dash_p_launcher
test_mimic_generation_never_applies_stress_profile_to_generated_data
test_official_mimic_wrapper_run_command_applies_process_cooldown
test_official_mimic_wrapper_dry_run_creates_one_shard_per_source_demo

result:
4 passed
```
