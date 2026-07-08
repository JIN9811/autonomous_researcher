# LeRobot / Isaac Data Output Structure

Scope: LeRobot recording outputs and Isaac Sim / Isaac Lab sidecars used by the ROBOTIS OMX pick-and-place workflow.

This document describes the artifact layout only. Counts, latest run status, and QA results belong in each run's `summary.json`, `manifest.jsonl`, or `meta/atr_pipeline.json`.

## Current Reference Roots

Latest active robot cam recording:

```text
/home/jin/autonomous_researcher/artifacts/raw_depth_adapter_live_activecam_recheck_20260702T131526/dataset/local/raw-depth-adapter-live-activecam-recheck-20260702t131526
```

Previous 5 x 10 s recording with Isaac Lab / Mimic sidecars:

```text
/home/jin/autonomous_researcher/artifacts/raw_depth_adapter_live_5x10s/dataset
```

Short async augmentation smoke:

```text
/home/jin/autonomous_researcher/artifacts/async_aug_status_smoke
```

## Dataset Root

```text
<dataset_root>/
  meta/
    info.json
    episodes.jsonl
    episodes_stats.jsonl
    tasks.jsonl
    atr_pipeline.json
  data/
    chunk-000/
      episode_000000.parquet
      episode_000001.parquet
      ...
  videos/
    chunk-000/
      observation.images.top/
        episode_000000.mp4
        ...
      observation.images.top_depth/
        episode_000000.mp4
        ...
      observation.images.wrist/
        episode_000000.mp4
        ...
      observation.images.wrist_depth/
        episode_000000.mp4
        ...
  sidecar/
    ...
```

`meta/info.json` is the LeRobot dataset contract. It defines frame count, episode count, fps, action/state feature names, and image/video feature keys.

`meta/atr_pipeline.json` is the ATR pipeline ledger. It records selected pipeline, sidecar availability, mirror session metadata, active-cam metadata, and pointers to generated sidecars.

### LeRobot v3 Runtime Compatibility Files

Some generated or converted LeRobot v3 datasets store metadata in parquet form:

```text
meta/tasks.parquet
meta/episodes/chunk-000/file-000.parquet
data/chunk-000/file-000.parquet
videos/<video_key>/chunk-000/file-000.mp4
```

The currently installed LeRobot training runtime still opens the JSONL metadata files and formats `info.json` paths with `episode_chunk` / `episode_index`. Before launching `lerobot-train`, the bridge materializes compatibility files inside the selected local dataset when needed:

```text
meta/tasks.jsonl
meta/episodes.jsonl
meta/episodes_stats.jsonl
```

It also rewrites incompatible local v3 path templates such as `data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet` to a loader-compatible template such as `data/chunk-{episode_chunk:03d}/file-000.parquet` when the referenced chunk files already exist. This does not modify recorded frame rows, actions, videos, RGB-D renders, or Isaac Lab synthetic artifacts; it only makes the local metadata readable by the installed training command.

## Sidecar Root

```text
<dataset_root>/sidecar/
  attempts/
  isaac_mirror/
  isaac_rgbd/
  isaac_augmentation/
  depth_raw/
  isaac_lab_synthetic/
  canonical_episode_index/
```

Sidecars are optional. Training and visualization should check availability from manifests rather than assuming every directory exists.

## Recording Attempts

```text
sidecar/attempts/
  manifest.jsonl
  episode_000/
    attempt_<record_session>_ep000/
      specimen_pose.json
  episode_001/
    attempt_<record_session>_ep001/
      specimen_pose.json
  ...
```

`specimen_pose.json` is the active robot cam pose result for that recording episode. It contains A4-local pose, Isaac world pose, orientation, confidence, and RGB-D/depth alignment evidence.

## Isaac Mirror

```text
sidecar/isaac_mirror/
  <record_session_id>.jsonl
```

This file is the per-frame bridge log from LeRobot control to Isaac Sim. Rows can include joint state, render queue payloads, sync metrics, receiver state, and deferred RGB-D render requests.

## Isaac RGB-D Render

```text
sidecar/isaac_rgbd/
  episode_000/
    attempt_<record_session>_ep000/
      manifest.jsonl
      top/
        frame_000000_rgb.png
        frame_000000_depth.png
        frame_000000_depth_m.npy
        ...
      front/
        frame_000000_rgb.png
        frame_000000_depth.png
        frame_000000_depth_m.npy
        ...
      right/
        frame_000000_rgb.png
        frame_000000_depth.png
        frame_000000_depth_m.npy
        ...
  episode_001/
    ...
```

`manifest.jsonl` is the source of truth for rendered frame availability. Training adapters and augmentation jobs should read manifests, not scan images directly.

## Isaac Data Augmentation

```text
sidecar/isaac_augmentation/
  latest/
    summary.json
    qa_summary.json
    manifest.jsonl
    images/
      episode_000/
        frame_000000/
          variant_000/
            top/
              rgb.png
              depth.png
              source_depth_preview.png
              depth_preview.png
            front/
              rgb.png
              depth.png
              source_depth_preview.png
              depth_preview.png
            right/
              rgb.png
              depth.png
              source_depth_preview.png
              depth_preview.png
          variant_001/
            ...
```

`summary.json` records selected cameras, source frame count, variants per frame, QA counts, enabled augmentation families, and output paths.

`manifest.jsonl` records one row per generated variant. Each row links source frame metadata, image outputs, depth outputs, render-domain parameters, camera-pose jitter, source pose, and QA result.

## Raw Depth Sidecar

```text
sidecar/depth_raw/
  transform_manifest.json
  top/
    frame_000000.png
    frame_000001.png
    ...
  wrist/
    frame_000000.png
    frame_000001.png
    ...
```

This sidecar is present only when the raw depth writer is active. `frame_*.png` files are 16-bit depth images. `transform_manifest.json` stores depth scale, clipping range, camera keys, and alignment target.

Some recordings may instead store depth as LeRobot video features such as `observation.images.top_depth` and `observation.images.wrist_depth`. In that case `sidecar/depth_raw` can be absent.

## Isaac Lab / Mimic

```text
sidecar/isaac_lab_synthetic/
  latest/
    summary.json
    summary_e2e.json
    validation_report.json
    request.json
    compatibility.json
    source_labels.json
    canonical_episode_index/
      summary.json
      manifest.jsonl
    training_import/
      summary.json
      training_import_validation.json
      lerobot_source_config.json
      manifest.jsonl
    hdf5/
      exported_successful_real_episodes.hdf5
      export_summary.json
      hdf5_contract_report.json
      annotation_summary.json
    lab_env/
      robotis_omx_pick_place_env.json
      domain_randomization_events.json
    mimic/
      config.json
      preflight.json
      summary.json
      smoke_summary.json
      runner.json
      generation_config.json
      candidates.jsonl
      successes.jsonl
      failures.jsonl
      generated_dataset_joint_plan.hdf5
      generated_dataset.hdf5
      generated_dataset_small.hdf5
      generated_dataset_normalized.hdf5
    il/
      robomimic/
        train_job.json
      eval/
        eval_job.json
      robomimic_live/
        <task_name>/
          <run_name>/
            <timestamp>/
              config.json
              models/
                model_epoch_*.pth
    rl_teacher/
      config.json
      preflight.json
      summary.json
    runtime_smoke/
      contact_smoke.json
      dof_smoke.json
      contact_result.json
```

This branch is separate from the normal recording sidecars. It is the handoff structure for Isaac Lab / Mimic / robomimic training.

For the Robotis OMX joint-replay backend, `generated_dataset_joint_plan.hdf5` is an intermediate planning/debug artifact. It stitches randomized source segments and preserves the leader joint target tensors, but it is not considered trainable by itself. The trainable mimic artifact is `mimic/generated_dataset.hdf5`, produced by replaying that plan through the Isaac Lab environment and recording the actual Lab-stepped observations, actions, object poses, RGB-D camera tensors when enabled, and success metadata. A mimic success row is allowed into `training_import/manifest.jsonl` only when `metrics.lab_step_replay=true`; `metrics.joint_replay=true` without `lab_step_replay` is excluded from training import.

## Viewer and Debug Captures

```text
runs/specimen_pose_tracker/
  specimen_pose_lerobot_frame.json
  specimen_pose_lerobot_frame_debug.png
  specimen_pose_lerobot_frame_a4_crop.png

runs/isaac_rgbd_view_smoke/
  <timestamp>_<view_name>/
    contact_sheet_*.png
    top/frame_000000_rgb.png
    top/frame_000000_depth.png
    front/frame_000000_rgb.png
    front/frame_000000_depth.png
    right/frame_000000_rgb.png
    right/frame_000000_depth.png

runs/isaac_screenshots/
  isaac_view_<timestamp>.png
```

These are operator/debug artifacts. They should not be treated as training data unless explicitly copied into a dataset sidecar manifest.

## Consumption Order

```text
recording data:
  meta/ + data/ + videos/

real-to-sim synchronization:
  sidecar/attempts/
  sidecar/isaac_mirror/
  sidecar/isaac_rgbd/

augmentation:
  sidecar/isaac_augmentation/latest/

Isaac Lab / Mimic:
  sidecar/isaac_lab_synthetic/latest/

debug and UI evidence:
  runs/specimen_pose_tracker/
  runs/isaac_rgbd_view_smoke/
  runs/isaac_screenshots/
```

Training should consume only manifest-backed dataset or sidecar artifacts. Debug screenshots and smoke outputs are evidence unless a manifest explicitly references them.
