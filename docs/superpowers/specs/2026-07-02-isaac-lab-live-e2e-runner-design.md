# Isaac Lab Live E2E Runner Design

## Goal

Make the Isaac Lab Mimic + IL path run as an actual live subprocess workflow from the LeRobot GUI, then verify it with a 10 second x 3 episode check. The normal LeRobot recording and teleoperation paths remain unchanged.

## Current State

The repository already has the core contracts:

- `integrations/isaac_lab_robotis_omx/` registers Robotis OMX Isaac Lab tasks.
- `device_bridges/isaac_lab_hdf5.py` exports LeRobot episodes into Isaac Lab / robomimic HDF5 shape.
- `device_bridges/isaac_lab_synthetic.py` builds synthetic summaries, HDF5 exports, Mimic runner commands, IL train commands, and IL eval commands.
- `device_bridges/lerobot_bridge.py` can launch individual Isaac Lab runner subprocesses when `mode=live` and `dry_run=false`.
- `scripts/lerobot_isaac_lab_e2e_smoke.py` can sequence build, export, annotation, Mimic, IL train, and IL eval.
- The GUI has an Isaac Lab tab, but it does not clearly expose a live 10s x 3 preset or make visual/headless behavior obvious.

The missing piece is an operator-friendly live runner that starts the E2E sequence, tracks it as a job, reports logs/artifacts, and makes visual mode a checkbox instead of a separate mental model.

## UX Contract

The Isaac Lab tab should expose one visual-mode checkbox:

- `Visualize Isaac Lab generation`

All Isaac Lab generation/eval actions must read this checkbox:

- unchecked: add `--headless` where supported
- checked: remove `--headless`, enable cameras where needed, and pass visual flags through the request

The GUI should add a focused live validation action:

- `Run 10s x 3 Live Check`

This action should set:

- `mode=live`
- `dry_run=false`
- `e2e_create_fixture=false`
- `e2e_episodes=3`
- `e2e_episode_s=10`
- `mimic_trials=3`
- `mimic_num_envs` from the GUI field
- `enable_mimic=true`
- `enable_hdf5_export=true`
- `enable_replicator=false` for this live runner
- `isaac_lab_visualize_generation` from the checkbox

The existing individual buttons should remain available for debugging:

- `Export HDF5`
- `Annotate Source`
- `Generate Mimic`
- `Train IL`
- `Eval IL`
- `Run Mimic + IL E2E`

## Backend Contract

Add a new bridge/API path for the live full check instead of overloading the dry-run E2E summary path:

- `POST /api/lerobot/isaac-lab/run-live-e2e-check`
- `POST /api/lerobot/isaac-lab/live-e2e/status`
- `POST /api/lerobot/isaac-lab/live-e2e/stop`

The start endpoint launches:

```text
<lerobot-python> scripts/lerobot_isaac_lab_e2e_smoke.py
  --mode live
  --dataset-path <dataset>
  --isaac-lab-path <IsaacLab>
  --isaac-sim-python <IsaacSim python.sh>
  --trials 3
  --num-envs <GUI value>
  --episodes 3
  --episode-s 10
  --fps 15
  --no-create-fixture
  --stage-timeout-s <timeout>
```

If visual mode is on, the payload sent to the script must cause downstream Mimic and IL eval commands to omit `--headless` and enable cameras for Mimic generation.

The job status must include:

- `job_id`
- `status`
- `pid`
- `command`
- `log_path`
- `output_root`
- `progress`
- `artifact_checks`
- `error`

## Artifact Verification

The live E2E job is not considered useful unless it can report these expected artifacts:

- `hdf5/exported_successful_real_episodes.hdf5`
- `hdf5/source_real_success_annotated.hdf5`
- `mimic/generated_dataset.hdf5`
- `mimic/successes.jsonl`
- `il/robomimic`

The bridge should verify artifact presence on status refresh and completion. Missing artifacts should be shown as `missing`, not hidden.

## Testing Contract

Automated tests should cover:

- GUI static wiring for the new live check button and visual checkbox payload.
- Request defaults for 10s x 3 live checks.
- Live E2E command construction without running Isaac Sim.
- Visual checkbox behavior:
  - visual off includes headless behavior
  - visual on removes headless behavior and enables cameras
- Artifact check logic for present/missing outputs.

Manual/live verification should run after implementation:

```bash
/home/jin/miniconda3/envs/lerobot/bin/python scripts/lerobot_isaac_lab_e2e_smoke.py \
  --mode live \
  --dataset-path <selected_dataset> \
  --isaac-lab-path /home/jin/IsaacLab \
  --isaac-sim-python /home/jin/IsaacSim/python.sh \
  --trials 3 \
  --num-envs 2 \
  --episodes 3 \
  --episode-s 10 \
  --fps 15 \
  --no-create-fixture
```

If Isaac Lab runtime fails, the result must include the exact failing command, return code, and log path.

## 2026-07-02 Live Verification Notes

Observed against:

```text
artifacts/raw_depth_adapter_live_activecam_recheck_20260702T131526/dataset/local/raw-depth-adapter-live-activecam-recheck-20260702t131526
```

The LeRobot-to-HDF5 export path is valid for the 10s x 3 preset:

- exported episodes: 3
- exported frames: 450
- `hdf5/exported_successful_real_episodes.hdf5`: present
- `hdf5/source_real_success_annotated.hdf5`: present via preannotated passthrough
- HDF5 tensor dtype: float32 for Isaac Lab Mimic pose/action tensors

Visual checkbox behavior is now explicit:

- unchecked: `isaac_lab_visualize_generation=false`, `mimic_enable_cameras=false`, `--headless`, `--robotis-camera-mode off`, no `--enable_cameras`, state-only policy task
- checked: `isaac_lab_visualize_generation=true`, `mimic_enable_cameras=false`, no `--headless`, `--viz kit`, USD viewport update enabled, `--robotis-camera-mode off`, no `--enable_cameras`, state-only policy task. This is not a separate view-only launch; it is attached to the active Isaac Lab runner path. Official Mimic shows the active Mimic process, while the joint-replay backend opens the same runner and steps the generated trajectory in the Lab env before the job completes.
- camera sensors are enabled only when `mimic_enable_cameras=true`, which switches `--robotis-camera-mode rgbd`, adds `--enable_cameras`, and uses the visual policy task.

Current live blocker:

- Official Isaac Lab Mimic starts successfully, loads the 3 demos, and creates the Robotis OMX physical env.
- The env runs with `JointPositionAction`.
- The current Mimic API still transforms target EEF poses into delta pose style actions, so official Mimic attempts do not satisfy the physical `place` success term.
- Observed result: repeated `0/N (0.0%) successful demos generated by mimic`.
- The bridge now fails fast after `0/9` attempts instead of letting the GUI wait indefinitely.

Next implementation requirement:

- Add a real Robotis OMX Mimic action adapter before claiming official Mimic generation works end to end:
  - either restore a stable IK action mode with valid limits and singularity handling,
  - or implement a joint-trajectory replay/retarget adapter that maps source HDF5 joint positions into `JointPositionAction` while preserving Mimic subtask randomization.

## 2026-07-02 Joint Replay Backend

The first working physical-action Mimic backend is `joint_replay`.

Why:

- The official Isaac Lab Mimic generator calls `target_eef_pose_to_action()` with transformed EEF poses.
- The Robotis OMX physical task uses `JointPositionAction`, so a 7-axis joint target is required.
- Without a stable IK action layer, converting arbitrary transformed EEF poses directly to joint targets is underconstrained and repeatedly produced `0/N` successful official Mimic attempts.

Implemented behavior:

- `mimic_generation_backend` defaults to `joint_replay`.
- `scripts/lerobot_isaac_lab_joint_replay_mimic.py` reads `hdf5/source_real_success_annotated.hdf5`.
- `device_bridges.isaac_lab_joint_replay_mimic.generate_joint_replay_mimic_dataset()` parses `approach`, `grasp`, `lift`, and `place` subtask termination signals.
- It stitches source subtask segments while preserving the source `actions` tensor as float32 joint-position targets.
- It first writes `mimic/generated_dataset_joint_plan.hdf5` as an intermediate segment plan, then replays that plan through the Isaac Lab environment and writes the trainable `mimic/generated_dataset.hdf5`.
- Success rows include `training.eligible=true`, `metrics.lab_step_replay=true`, and `artifacts.hdf5_path="mimic/generated_dataset.hdf5"` so the existing training import flow exposes only Lab-stepped generated data.
- A row with `metrics.joint_replay=true` and no `metrics.lab_step_replay=true` is a planning/debug row and must not enter `training_import/manifest.jsonl`.
- The official EEF-pose Mimic backend remains available by setting `mimic_generation_backend="official"`.

Live verification against:

```text
artifacts/raw_depth_adapter_live_activecam_recheck_20260702T131526/dataset/local/raw-depth-adapter-live-activecam-recheck-20260702t131526
```

Result:

- source demos loaded: 3
- generated joint replay demos: 3
- generated frames: 450
- generated HDF5 action shape: `(T, 7)`
- generated HDF5 action dtype: `float32`
- bridge Mimic job status: `COMPLETED`
- build/training import after generation: `real_lerobot=1`, `isaac_lab_synthetic=3`, `row_count=4`

Limit:

- This backend is a joint-position replay/segment-stitching adapter, not arbitrary object-pose IK retargeting.
- It makes the physical joint-action dataset trainable now; a later Isaac Sim replay validator can filter joint replay trials by actual physical success if we need stricter sim-success labels.

## 2026-07-05 GUI Path And Training Verification

Verified the GUI/API standard path against:

```text
/home/jin/.cache/huggingface/lerobot/local-pi05-v30/jin-live-10s3-viz-20260702t213455-0900
```

Domain randomization + Mimic path:

- The section 7 launcher reads the shared `Visualize Isaac Lab generation` checkbox. Unchecked runs the headless trainable-output path; checked passes `isaac_lab_visualize_generation=true` so the active Lab generation runner opens a Kit viewport instead of `--viz none`.
- The runner writes the joint-plan HDF5 first, then replays it through the Isaac Lab Robotis OMX environment and writes `mimic/generated_dataset.hdf5`.
- `build-synthetic` and `check-outputs` passed after generation.
- Training import exposed three rows: `real_lerobot=1`, `isaac_rgbd_render=1`, `isaac_lab_synthetic=1`.
- The synthetic training row pointed at the Lab-stepped HDF5, with `metrics.lab_step_replay=true`.

LeRobot training path:

- First blocker was the local v3 dataset metadata layout: `tasks.parquet` existed, but the installed LeRobot runtime still opened `meta/tasks.jsonl`, then fell back to Hub and failed.
- Second blocker was v3 `info.json` path templates using `{chunk_index}` / `{file_index}`, while the installed loader formats with `{episode_chunk}` / `{episode_index}`.
- The bridge now performs live train preflight compatibility materialization:
  - `meta/tasks.jsonl` from `meta/tasks.parquet`
  - `meta/episodes.jsonl` from `meta/episodes/**/*.parquet`
  - `meta/episodes_stats.jsonl` from per-episode parquet stats, falling back to `meta/stats.json`
  - loader-compatible `info.json` `data_path` / `video_path` templates when the referenced chunk files already exist
- Actual `lerobot-train` verification completed with `returncode=0`, `steps=1`, `dataset.num_frames=720`, and `dataset.num_episodes=3`.
- The 720 frames came from 450 original real frames plus 270 Isaac RGB-D source adapter rows. The Isaac Lab synthetic training import was available and train-exposed; the smoke used one Lab synthetic row from the current generated sidecar.

## Non-Goals

- Do not change LeRobot recording behavior.
- Do not change normal teleoperation behavior.
- Do not auto-create fake fixture data for the live check unless the user explicitly uses the existing smoke button.
- Do not merge Replicator visual mode with Mimic/IL visual mode; they share one checkbox but remain separate execution paths.
