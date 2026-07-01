# LeRobot Augmentation and Visualization Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the LeRobot + Isaac Sim post-recording pipeline so augmentation quality, synthetic RGB-D coverage, raw depth health, and training readiness can be verified before training, then migrate high-volume synthetic data generation into an Isaac Lab synthetic intelligence branch.

**Architecture:** Keep live LeRobot teleoperation/recording as the real data authority, keep Isaac Sim mirror/rendering as the digital-twin and RGB-D evidence layer, and move high-volume synthetic trajectory generation plus domain randomization into Isaac Lab. The bridge owns validation, manifests, source labels, GUI orchestration, and training import; Isaac Lab/Replicator own generated trajectories and synthetic render products.

**Tech Stack:** FastAPI GUI backend, `web/templates/lerobot.html`, `device_bridges/lerobot_bridge.py`, Isaac Sim Replicator, Isaac Lab Mimic/RL, LeRobot dataset/training commands, raw 16-bit RealSense depth sidecars, JSON/JSONL manifests, HDF5 for Isaac Lab/robomimic interchange.

**Current baseline verified on 2026-06-29:**
- GUI record produced `5` episodes, `750` original frames at `15 fps`.
- Raw depth sidecar existed for both `top` and `wrist` cameras.
- Isaac RGB-D sidecar was detected by training.
- Isaac augmentation sidecar was generated with `standard_sim2real_v2`, `sim2real`, `50` source frames, and `100` variants.
- ACT smoke training completed `2/2` steps with raw depth, Isaac RGB-D, and augmentation adapters enabled.
- Rerun distant visualization worked at `http://localhost:9092`.

**Problem:** The pipeline can now generate and consume augmented data, but it still lacks enough quality gates and visual inspection tools to know whether synthetic data is helping or poisoning training.

**Current code-map checked on 2026-07-01:**
- `scripts/lerobot_isaac_data_augmentation.py` builds immutable `sidecar/isaac_augmentation` variants from Isaac RGB-D render manifests. It changes RGB/depth, render-domain parameters, camera-pose metadata, and bounded object pose metadata, but it does not regenerate the recorded robot action trajectory.
- `web/templates/lerobot.html` exposes section 7 augmentation controls and section 9 dataset mix / Sim2Real fidelity controls. Current defaults keep real data dominant while adding Isaac RGB-D and augmentation sources conservatively.
- `device_bridges/lerobot_bridge.py` wires training readiness, QA preflight, dataset mix summaries, fidelity weights, raw-depth adapter env, Isaac RGB-D env, and Isaac augmentation env into LeRobot training sessions.
- `sim/robotis_omx/tools/isaac_omx_mirror_server.py` now emits `grasp_diagnostics` and action-processing metadata that can become success labels or subtask boundaries for a later trajectory-generation branch.
- `/home/jin/IsaacLab` exists locally at `v3.0.0-beta2`. The synthetic branch must treat Isaac Lab as a pinned external runtime with explicit Isaac Sim compatibility checks, not as an unversioned helper script directory.

**Important limitation:** The current augmentation is observation/domain augmentation. It improves camera, RGB-D, render, and sim-to-real robustness, but large object pose changes can create action-label mismatch because the original LeRobot action sequence still points to the original pick path. Any object XY/yaw augmentation must stay small unless a separate trajectory generator creates a new action sequence.

**Isaac Lab and Isaac Sim documentation checked on 2026-07-01:**
- Isaac Lab local installation docs recommend using compatible Isaac Sim releases and currently point users toward Isaac Sim `5.1.0` for the latest stable feature set.
- Isaac Lab GitHub compatibility notes list `main` / `v2.3.X` support across Isaac Sim `4.5`, `5.0`, and `5.1`.
- Isaac Lab `v3.0.0-beta2` is a beta line compatible with Isaac Sim `6.0`; use it only when the local Isaac Sim runtime is intentionally on that beta stack.
- Isaac Lab imitation-learning docs cover HDF5 teleop demonstrations, Mimic dataset generation, robomimic training, and visual augmentation workflows.
- Isaac Lab reinforcement-learning docs expose `rsl_rl`, `skrl`, `rl_games`, and Stable-Baselines3 training/play scripts.
- Isaac Lab manager APIs and `EventTermCfg` are the right place to move reset-time domain randomization for cube pose, physics, materials, lighting, and camera perturbations.
- Isaac Sim `docs.isaacsim.omniverse.nvidia.com` must be checked alongside Isaac Lab because it owns Replicator, sensor simulation, SDG writers/annotators, physics materials, contact offsets, colliders, filtered pairs, and release-specific extension availability.
- Isaac Sim `6.0.0` release notes are now published, while some `5.1.0` docs pages identify that version as unsupported in the latest docs view. The compatibility gate must therefore record the exact Isaac Sim docs/runtime version used for every synthetic branch run.
- Isaac Sim Replicator docs describe perception data generation with domain randomization, sensor simulation, annotators, and writers; this maps directly to the rendering and RGB-D branch of synthetic generation.
- Isaac Sim data augmentation docs show RGB/depth augmentations on annotators and writers, including GPU/CPU kernels. This should inform the Lab branch's image/depth augmentation implementation instead of relying only on the current Pillow/numpy sidecar script.
- Isaac Sim scene-based SDG docs include offline dataset generation, scene randomization, and capture loops. This is the right pattern for batch generation after LeRobot recording, not for blocking live teleop.
- Isaac Sim teleoperation SDG docs cover simulation teleop data generation; use this only for sim-only data collection, not as the primary real-robot teleop path.
- Isaac Sim teleoperation SDG records HDF5 episodes from simulation state and optional teleop input channels. Its replay path is pure USD pose playback: no physics step, no DOF command, no IK solve, and no trigger/gripper command is re-dispatched. This is useful for offline rendering and inspection, but it is not a physics-validation replay of a grasp.
- Isaac Sim teleoperation profiles are YAML mappings for Floating, IK, Grasp, and Locomotion controllers. The official structure is useful as a reference for our Isaac-side mirror profile, but our real robot command source should remain the LeRobot live bridge unless a separate sim-only teleop session is intentionally launched.
- Isaac Lab teleoperation supports SE(2)/SE(3) command devices, HDF5 demo recording, replay, Isaac Lab Mimic generation, and robomimic training. The docs explicitly favor short, direct, smooth demonstrations without pauses, because jerky or long demonstrations degrade imitation learning.
- Isaac Lab Mimic requires task-specific subtask boundaries, object poses, end-effector pose/action conversion helpers, gripper-action extraction, and success criteria. This matches the planned `RobotisOMXPickPlaceLabEnv` wrapper better than a generic image-only augmentation script.
- Isaac Sim Digital Twin docs in `6.0.0` focus on warehouse/logistics, mapping, live camera streaming, and troubleshooting. Cortex is marked deprecated there, so do not build new behavior logic on Cortex.
- Isaac Sim Digital Twin live camera streaming can publish camera render products over RTSP through `isaacsim.streaming.rtsp`, either as an OmniGraph node or a Replicator writer. This is appropriate for simulated camera feeds into perception/QA tools, but it does not replace real D405/D455 raw-depth capture.
- Isaac Sim robot setup docs call out the exact failure modes we have seen: nonzero drive targets causing first-frame jumps, incorrect mimic gear/direction, overlapping collision meshes causing unstable forces, overly high gains/torque causing shake after motion, unrealistic mass/inertia, and timestep/solver/contact-offset issues.
- Isaac Sim physics docs must be used as the authority for contact/friction/material/collider settings and for validating gripper/cube physical realism before generated trajectories are trusted.

---

## Improvement 1: Augmentation Mix Ratio

**Need:** Training should not blindly include every generated synthetic frame. The original real data distribution must stay dominant unless the operator intentionally changes it.

**Design:**
- Add GUI/API controls for dataset mixing:
  - `real_original_weight`
  - `isaac_rgbd_weight`
  - `isaac_augmentation_weight`
  - optional max samples per source
- Default to a conservative ratio such as:
  - real original: `1.0`
  - Isaac RGB-D: `0.5`
  - augmented variants: `0.5`
- Pass these values into train env or dataset adapter config.
- Report the effective sampled frame count in train status.

**Tasks:**
- [x] Add request fields in LeRobot GUI/API schema.
- [x] Add train env/config for adapter sampling weights.
- [x] Update the training dataset adapter to apply deterministic weighted sampling.
- [x] Show effective frame counts in `train_start` and `train_status`.
- [x] Add tests for default conservative mix and operator override.

---

## Improvement 2: Manifest QA Gate

**Need:** Augmentation must produce valid RGB/depth files and reasonable metadata. Bad variants should be excluded before training.

**QA checks:**
- RGB file exists and can be decoded.
- Depth file exists, is 16-bit when expected, and has valid nonzero pixels.
- Depth valid ratio is above a threshold.
- Source frame id, episode index, camera id, and variant id are present.
- Camera pose perturbation stays within configured bounds.
- Object XY/yaw jitter stays within A4 workspace bounds.
- Source Isaac RGB-D frame exists when a variant references it.

**Output contract:**
- Write `sidecar/isaac_augmentation/latest/qa_summary.json`.
- Add per-row QA fields to manifest:
  - `qa_ok`
  - `qa_failure_code`
  - `depth_valid_ratio`
  - `rgb_exists`
  - `depth_exists`
- Training should include only `qa_ok=true` rows by default.

**Tasks:**
- [x] Add `scripts/lerobot_isaac_augmentation_qa.py` or integrate QA into the augmentation builder.
- [x] Add GUI summary for total, passed, failed, and failure-code counts.
- [x] Block or warn before training when valid variant count is below threshold.
- [x] Add tests with missing RGB, missing depth, invalid depth, and out-of-bounds pose.

---

## Improvement 3: D405 Realistic Depth Noise

**Need:** Current depth augmentation is generic. D405 depth should model actual sensor artifacts better.

**Depth effects to add:**
- edge holes around object boundaries
- invalid-pixel dropout
- quantization and scale drift
- small bias in millimeters
- reflective or dark surface dropout
- short-range instability profile for D405

**Design:**
- Keep the current `depth_strength` control.
- Add a camera-specific profile:
  - `d405_close_range`
  - `d455f_fallback`
  - `generic_realsense`
- Use sidecar raw depth metadata to choose the profile automatically when possible.

**Tasks:**
- [x] Add camera-specific depth profile selection in augmentation summary.
- [x] Implement D405 edge/dropout/scale noise.
- [x] Add preview images for depth before/after.
- [x] Add tests that check 16-bit output stays valid and bounded.

---

## Improvement 4: A4-Bounded Object Pose Augmentation

**Need:** Object pose augmentation must stay inside the real A4 workspace and respect active robot-cam calibration. Unbounded yaw/XY jitter can train the policy on impossible or mismatched pick positions.

**Design:**
- Treat active robot-cam specimen pose as the base pose.
- Apply bounded jitter in A4 coordinates only.
- Store both camera-space and Isaac-space pose in each variant.
- Include object yaw only when the vision tracker has a reliable orientation estimate.

**Tasks:**
- [x] Add A4 boundary checks for synthetic XY/yaw.
- [x] Add `source_pose_confidence` and `orientation_source` fields.
- [x] Disable yaw augmentation when orientation confidence is low.
- [x] Add tests for boundary clipping and no-yaw fallback.

---

## Improvement 5: Side-by-Side Preview

**Need:** Operators need to inspect the same source frame across real RGB, raw depth, Isaac RGB-D, and augmented variants.

**GUI preview layout:**
- Source RGB camera frame.
- Source raw 16-bit depth visualization.
- Isaac RGB-D render for the same frame.
- Augmented RGB/depth variant.
- Metadata panel:
  - episode/frame/camera
  - source pose
  - augmentation parameters
  - QA result

**Tasks:**
- [x] Add `/api/lerobot/augment/preview` endpoint.
- [x] Sample deterministic preview rows from the manifest.
- [x] Generate compact PNG previews for depth using a consistent colormap.
- [x] Add GUI panel under section 7 for before/after inspection.
- [x] Add tests for preview endpoint with minimal fixture data.

---

## Improvement 6: Visualization Health Dashboard

**Need:** Visualization should show dataset readiness before opening Rerun. The operator should immediately see whether training inputs are complete.

**Metrics to show:**
- episodes
- original frames
- raw depth counts per camera
- Isaac RGB-D manifest count and rendered/failed/skipped counts
- augmentation source frames and valid variants
- active robot-cam attempt count
- missing sidecar warnings
- train-effective frame count after mix ratio

**Tasks:**
- [x] Add dataset health summary to `/api/lerobot/dataset/inspect`.
- [x] Render a compact health card in the GUI.
- [x] Add severity levels: ok, warning, blocking.
- [x] Add tests for complete, partial, and missing sidecar datasets.

---

## Improvement 7: Persistent Visualization Port Management

**Need:** Rerun distant works, but port conflicts are currently handled manually.

**Design:**
- GUI/backend should auto-select available ports for Rerun distant.
- Preserve explicit port override for debugging.
- Store viewer URL in session metadata.
- Restarting the app should not leave stale viewer status in the GUI.

**Tasks:**
- [x] Add free-port selection for visualization web/ws ports.
- [x] Return selected ports in `visualize.start`.
- [x] Add stale process detection to `visualize.status`.
- [x] Add tests for occupied default ports and auto fallback.

---

## Improvement 8: Unified Progress UX

**Need:** RGB-D render progress smoothing is implemented, but augmentation build, visualization load, and training dataset loading still report progress unevenly.

**Design:**
- Use the same progress state model across:
  - post-record Isaac RGB-D render
  - augmentation builder
  - visualization loader
  - training preflight/dataset loading
- Keep backend status factual; smooth only the frontend display.

**Tasks:**
- [x] Reuse the current RGB-D render progress smoothing helper for augmentation and visualization.
- [x] Add backend progress counters for augmentation manifest generation.
- [x] Surface training preflight stages before process start.
- [x] Add static GUI tests for progress components.

---

## Improvement 9: Isaac Lab Synthetic Intelligence Branch

**Need:** Current Isaac augmentation increases what the policy sees, not how the robot moves. For larger cube XY/yaw changes, training needs new action trajectories that actually reach, grasp, lift, and place the object in the changed scene. The long-term owner for domain randomization, imitation-learning generation, RL teacher/evaluator rollouts, and synthetic trajectory filtering should be Isaac Lab, not the current LeRobot sidecar augmentation script.

**Design:**
- Keep the existing LeRobot recording path as the source of truth.
- Define the digital-twin boundary explicitly:
  - Isaac Sim mirrors the robot, cube, A4 workspace, cameras, contacts, materials, and render sensors.
  - Real LeRobot teleoperation remains the live command/recording path.
  - Isaac Sim Teleop SDG is allowed only for sim-only demonstrations, replay inspection, and offline SDG experiments.
  - Isaac Lab is the owner for generated trajectories, domain randomization, Mimic, and RL teacher/evaluator loops.
  - Digital-twin camera outputs may be exposed through Isaac Sim RTSP streams or Replicator writers for perception QA, but real raw-depth files remain the authority for real-world D405/D455 observations.
- Add an Isaac Lab upgrade/compatibility gate before building the branch:
  - detect local Isaac Lab git tag/commit and Isaac Sim version
  - decide between a stable stack (`v2.3.X` + Isaac Sim `5.1`) and beta stack (`v3.0.0-beta2` + Isaac Sim `6.0`)
  - check the matching `docs.isaacsim.omniverse.nvidia.com` version for release notes, Replicator, sensor, and physics extension availability
  - refuse to run generation when Isaac Lab and Isaac Sim are on unsupported combinations
  - write the selected Lab version, Sim version, Isaac Sim docs version, branch, commit, and Python environment into every synthetic run manifest
- Add a digital-twin stage preflight before exporting or generating any synthetic data:
  - robot USD joint zero pose and LeRobot/Dynamixel joint-name mapping are present
  - articulation root, solver iterations, sleep/stabilization thresholds, mass, inertia, and D405 mount mass are recorded
  - active robot-cam and Isaac sidecar cameras have explicit poses, intrinsics, resolution, stream/render source, and depth units
  - optional Isaac RTSP streams have unique ports, lifecycle status, render-product resolution, and frame metadata
  - every stage or recording run can export a `stage_snapshot.usd` equivalent for replay and debugging
- Add a canonical episode builder that aligns:
  - LeRobot observations and actions
  - raw 16-bit depth sidecars
  - Isaac RGB-D sidecars
  - active robot-cam specimen pose
  - mirror action metadata and `grasp_diagnostics`
- Export successful episodes to an Isaac Lab / robomimic-compatible HDF5 dataset.
- Implement a small `RobotisOMXPickPlaceLabEnv` around the OMX Isaac scene instead of modifying live teleop:
  - action space: end-effector delta pose or joint targets plus gripper command
  - observations: robot state, gripper state, cube pose, optional RGB-D camera tensors
  - object poses: red cube pose in robot-base frame
  - subtask signals: approach, grasp, lift, place, release
- Move domain randomization into Isaac Lab env reset/events:
  - A4-bounded cube XY/yaw
  - cube mass, friction, restitution, and material variation
  - table / paper material variation
  - gripper inner-pad friction variation
  - camera pose, intrinsics, exposure, lighting, and RGB-D sensor noise profiles
  - D405 close-range depth artifacts where render/depth export supports them
- Use Isaac Sim Replicator for perception-side output inside or adjacent to the Lab branch:
  - RGB, depth, segmentation, and metadata writers where needed
  - annotator-level RGB/depth augmentation when operating on rendered buffers
  - offline scene-based SDG loops for batch data generation
  - teleoperation SDG only for sim-only demonstration capture
- Use Isaac Sim Teleop SDG replay only as a render/inspection input:
  - HDF5 replay applies recorded world poses through USD and timeline seeking
  - replay does not step physics or re-run IK/gripper trigger logic
  - if grasp physics must be validated, replay must be converted into an Isaac Lab rollout or a separate physics simulation, not treated as proof of contact realism
  - programmatic camera recordables are useful for preserving wrist/top/side camera paths and intrinsics during offline Replicator rendering
- Use Isaac Sim physics documentation as preflight criteria before accepting generated trajectories:
  - collider visualization must show object and gripper contact geometry matching intended contact patches
  - fingertip contact colliders should prefer convex decomposition or simple base geometry where appropriate
  - nonessential self-collisions should be filtered through documented filtered-pair workflows
  - contact offset, rest offset, physics material friction/restitution, and combine modes must be included in the run manifest
  - SDF/custom geometry limitations must be handled explicitly when using GPU/contact-heavy generation
  - joint drive targets, max force/torque, max velocity, stiffness, damping, and mimic gear/direction must be checked per gripper and arm joint
  - first-frame target jumps must be prevented by matching initial joint positions and drive targets before the timeline starts
  - solver/timestep/mass/inertia changes must be recorded because they can make replay and grasp stability differ from the live mirror
- Run Isaac Lab Mimic on randomized cube poses inside the A4 workspace.
- Add an RL teacher/evaluator branch after the Lab env is reliable:
  - state-based reach/grasp/lift/place rewards first
  - use RL rollouts for success-rate evaluation and trajectory discovery
  - do not deploy RL policy directly to the real robot by default
- Import only success-filtered generated trajectories back into a separate source such as `sidecar/isaac_lab_synthetic/latest`.
- Add separate training controls:
  - `isaac_lab_synthetic_weight`
  - `isaac_lab_synthetic_max_samples`
  - `isaac_lab_source_filter` with values such as `mimic`, `rl_teacher`, `domain_randomized_render`
  - success-only default inclusion
- Keep the default weight low until sim-to-real quality is proven. A starting range is `0.2` to `0.4`, with real data fixed at `1.0`.

**Migration of the current augmentation pipeline:**
- Move the current augmentation feature itself into the Isaac Lab / Isaac Sim Replicator path. Section 7 should no longer treat `scripts/lerobot_isaac_data_augmentation.py` as the primary implementation once the Lab branch is available.
- Keep `scripts/lerobot_isaac_data_augmentation.py` only as a fallback, preview, and backward-compatible sidecar builder.
- The default GUI action should be "Build Synthetic Dataset", not "Build Isaac Augmentation". It should prefer Isaac Lab + Replicator and only use the legacy script when the operator explicitly enables fallback mode or the compatibility gate reports that Lab/Replicator cannot run.
- Move large object pose changes out of sidecar-only augmentation and into Isaac Lab trajectory generation.
- Move perception randomization from ad hoc sidecar fields into a split Lab/Replicator contract:
  - Lab reset/events own physics and task-state randomization
  - Isaac Sim Replicator owns render products, annotators, writers, synthetic data recorder outputs, and RGB/depth post-render augmentation
  - LeRobot bridge owns only import, mix, fidelity weighting, and health reporting
- Map the existing GUI controls into Lab configs:
  - `RGB Strength` -> Lab visual/material/lighting randomization strength
  - `Depth Strength` -> Lab camera/depth sensor noise profile strength
  - `Render Strength` -> Lab scene/material/lighting randomization strength
  - `Camera Pose Strength` -> Lab camera transform randomization strength
  - `Variants Per Source Frame` -> Lab generated rollouts per canonical source episode
  - `Max Source Frames` -> canonical episode sampling limit
- Rename section 7 from "Isaac Sim Data Augmentation" to "Isaac Lab Synthetic Intelligence" once the Lab branch is wired.
- Training should eventually consume `real_original`, `isaac_rgbd`, and `isaac_lab_synthetic`; the older `isaac_augmentation` source remains a compatibility source.

**End-to-end pipeline target:**

The target system is not "generate a few augmented images and hope training improves." The target system is a complete recording-to-training pipeline where every frame, action, synthetic image, generated trajectory, and simulator assumption has a source label and a QA decision before it reaches LeRobot training.

At a high level, the operator flow should become:

1. Record real episodes with LeRobot.
2. Capture raw depth and active robot-cam evidence during each recording cycle.
3. Mirror the episode into Isaac Sim and render missing Isaac RGB-D after recording, not during live teleop.
4. Press section `7. Isaac Lab Synthetic Intelligence` -> `Build Synthetic Dataset`.
5. The GUI runs version checks, digital-twin checks, canonical indexing, Replicator augmentation, Lab trajectory generation, and QA in a single staged workflow.
6. The GUI shows which sources are ready for training and which are blocked.
7. Training consumes real data, Isaac RGB-D render data, and success-filtered Isaac Lab synthetic data with explicit source weights.
8. Visualization can open the real recording, Isaac RGB-D sidecars, Replicator outputs, Mimic trajectories, failed candidates, and training mix summary without guessing folder names.

The standard path must be deterministic, resumable, and inspectable. Any stage that fails must write a structured partial result under the dataset sidecar so the GUI can say what is missing instead of silently falling back to lower-fidelity data.

### Section 7 GUI Contract

Section `7` should be renamed from `Isaac Sim Data Augmentation` to `Isaac Lab Synthetic Intelligence`. It should still expose the existing augmentation controls, but those controls now feed the Lab/Replicator config first.

The panel should have these visible groups:

**A. Pipeline Mode**
- `Synthetic Pipeline`: select, default `isaac_lab_replicator`.
  - `isaac_lab_replicator`: primary standard path.
  - `replicator_render_only`: render and image/depth augmentation only, no new action trajectory.
  - `legacy_sidecar`: old `scripts/lerobot_isaac_data_augmentation.py` compatibility mode.
- `Fallback policy`: select, default `block_on_primary_failure`.
  - `block_on_primary_failure`: if Lab/Replicator fails, stop and show the blocker.
  - `allow_legacy_fallback`: use the old script only after writing a fallback reason.
  - `legacy_only`: explicit debugging mode.
- `Synthetic source intent`: select, default `train_ready_success_only`.
  - `preview_only`: generate data for inspection, do not expose to train.
  - `train_ready_success_only`: expose only rows that pass QA and trajectory success.
  - `debug_include_failed`: expose failed rows only to visualization, not training.

**B. Current Controls Reinterpreted**
- `Augmentation Profile` maps to a synthetic recipe:
  - `conservative`: small lighting/material/sensor perturbations and small camera pose jitter.
  - `sim2real`: stronger material, lighting, depth-noise, and camera noise while keeping action consistency.
  - `stress`: offline QA/stress only by default; training inclusion requires explicit override.
- `Variants Per Source Frame` becomes `Generated Attempts Per Source Frame`.
  - For render-only data it means Replicator variants.
  - For trajectory data it means candidate Mimic/RL rollouts per canonical source frame/episode segment.
- `Max Source Frames` becomes the canonical frame sampling limit.
- `Cameras` becomes the render/record camera set, default `top,front,right`.
- `RGB Strength`, `Depth Strength`, `Render Strength`, and `Camera Pose Strength` map to Replicator/Lab config values, not Pillow/numpy augmentation values.
- `Camera Pose Strength` must never move a camera without updating the output manifest with old pose, new pose, intrinsics, source camera, and whether the trajectory remains action-consistent.

**C. New Buttons**
- `Check Digital Twin`
  - Runs Lab/Sim version detection, robot stage preflight, camera preflight, physics preflight, and source-label preview.
  - Does not create synthetic training rows.
- `Build Synthetic Dataset`
  - Runs the full standard path through canonical index, Replicator, Lab trajectory generation where configured, QA, and import manifest.
  - This replaces the old default `Build Isaac Augmentation` button.
- `Preview Synthetic Sources`
  - Shows real frames, Isaac RGB-D renders, Replicator variants, Mimic candidates, failed candidates, and source labels.
  - This replaces and expands `Preview Variants`.
- `Export HDF5`
  - Converts success-filtered canonical episodes or generated trajectories to Isaac Lab / robomimic-compatible HDF5.
- `Run Mimic Small Batch`
  - Runs a bounded smoke generation batch using the current recipe, useful before committing to full generation.
- `Run RL Teacher Smoke`
  - Optional, hidden under an advanced disclosure. It runs only in simulation and never changes real teleop behavior.
- `Use Legacy Sidecar Builder`
  - Advanced fallback button that calls the current `/api/lerobot/augment/isaac` endpoint and writes `source_type=legacy_sidecar`.

**D. Status Cards**
- `Compatibility`: Lab version, Sim version, docs version, selected stack, Python path, import status.
- `Digital Twin`: stage path, stage snapshot, robot mapping, joint zero pose, D405 mount mass, camera prims, cube/table/gripper physics materials.
- `Source Labels`: counts by `real_lerobot`, `isaac_rgbd_render`, `replicator_render_only`, `isaac_lab_mimic`, `isaac_lab_rl_teacher`, `legacy_sidecar`.
- `Canonical Index`: episode count, frame count, missing source counts, active robot-cam pose coverage, raw depth coverage.
- `Synthetic Generation`: attempts, successes, failures, success rate, failure-code counts.
- `Training Exposure`: eligible rows, blocked rows, effective sample counts, source weights, fidelity weights.

The operator should be able to understand from section `7` whether the pipeline is ready for training without opening a terminal.

### API Contract

The GUI should call new endpoints rather than stretching the legacy augmentation endpoint:

```text
POST /api/lerobot/isaac-lab/prepare
POST /api/lerobot/isaac-lab/build-synthetic
POST /api/lerobot/isaac-lab/preview
POST /api/lerobot/isaac-lab/export-hdf5
POST /api/lerobot/isaac-lab/mimic/start
POST /api/lerobot/isaac-lab/mimic/status
POST /api/lerobot/isaac-lab/mimic/stop
POST /api/lerobot/isaac-lab/rl-teacher/start
POST /api/lerobot/isaac-lab/rl-teacher/status
POST /api/lerobot/isaac-lab/rl-teacher/stop
```

The existing endpoint remains:

```text
POST /api/lerobot/augment/isaac
POST /api/lerobot/augment/preview
```

but these become legacy compatibility endpoints. The GUI should not call them by default once `isaac_lab_replicator` mode is active.

The primary build response should use this shape:

```json
{
  "ok": true,
  "tool": "lerobot.isaac_lab.build_synthetic",
  "schema": "atr.lerobot.isaac_lab_synthetic.response.v1",
  "status": "READY_FOR_TRAINING",
  "dataset_path": "...",
  "output_root": ".../sidecar/isaac_lab_synthetic/latest",
  "pipeline_mode": "isaac_lab_replicator",
  "fallback_used": false,
  "compatibility": {},
  "digital_twin": {},
  "canonical_episode_index": {},
  "replicator": {},
  "mimic": {},
  "rl_teacher": {},
  "source_labels": {},
  "training_exposure": {},
  "progress": {},
  "step_trace": [],
  "error": null
}
```

Every response must include `step_trace`. The GUI should render it as a checklist so a failed run shows exactly which stage blocked the build.

### Storage Layout

The new standard output root is:

```text
<dataset>/sidecar/isaac_lab_synthetic/latest/
```

Recommended layout:

```text
sidecar/
  isaac_lab_synthetic/
    latest/
      summary.json
      source_labels.json
      compatibility.json
      digital_twin_preflight.json
      canonical_episode_index/
        manifest.jsonl
        summary.json
      replicator/
        manifest.jsonl
        summary.json
        rgb/
        depth/
        segmentation/
        metadata/
      hdf5/
        exported_successful_real_episodes.hdf5
        exported_generated_trajectories.hdf5
        export_summary.json
      mimic/
        generated_dataset_small.hdf5
        generated_dataset.hdf5
        candidates.jsonl
        successes.jsonl
        failures.jsonl
        summary.json
      rl_teacher/
        rollouts.jsonl
        successes.jsonl
        failures.jsonl
        checkpoints/
        summary.json
      training_import/
        manifest.jsonl
        summary.json
        lerobot_source_config.json
      previews/
        index.html
        cards.jsonl
```

The legacy path stays:

```text
sidecar/isaac_augmentation/latest/
```

but it should be treated as `source_type=legacy_sidecar`, not as the standard synthetic branch.

### Source Label Contract

Every training-visible row must have a source label. The minimum label set is:

```text
real_lerobot
isaac_rgbd_render
replicator_render_only
isaac_teleop_replay_render
isaac_lab_mimic
isaac_lab_rl_teacher
legacy_sidecar
```

Training defaults:

- `real_lerobot`: enabled, weight `1.0`
- `isaac_rgbd_render`: enabled when QA passes, conservative weight
- `replicator_render_only`: enabled only when action-consistency is true or when it is attached to the original action sequence without object pose mismatch
- `isaac_teleop_replay_render`: disabled for physics-validated trajectory training unless converted to a real Lab rollout
- `isaac_lab_mimic`: enabled only for success-filtered generated trajectories
- `isaac_lab_rl_teacher`: disabled by default until the operator enables a teacher source
- `legacy_sidecar`: disabled by default after the Lab branch is active, unless fallback mode explicitly exposes it

This label contract is the guardrail that prevents image-only augmentation from being confused with a trajectory that actually solves a changed cube pose.

### Detailed Implementation Specification

This section is the contract for implementation. Code, GUI, CLI, manifests, tests, and training import should use the same names. Do not introduce alternate field names in one layer and translate them silently in another layer.

#### Canonical Enums

Create these enums in `mcp_tools/lerobot_schemas.py` or a new adjacent schema module that is imported by `app/main.py` and `device_bridges/lerobot_bridge.py`.

```python
from enum import Enum


class IsaacSyntheticPipelineMode(str, Enum):
    ISAAC_LAB_REPLICATOR = "isaac_lab_replicator"
    REPLICATOR_RENDER_ONLY = "replicator_render_only"
    LEGACY_SIDECAR = "legacy_sidecar"


class IsaacSyntheticFallbackPolicy(str, Enum):
    BLOCK_ON_PRIMARY_FAILURE = "block_on_primary_failure"
    ALLOW_LEGACY_FALLBACK = "allow_legacy_fallback"
    LEGACY_ONLY = "legacy_only"


class IsaacSyntheticSourceIntent(str, Enum):
    PREVIEW_ONLY = "preview_only"
    TRAIN_READY_SUCCESS_ONLY = "train_ready_success_only"
    DEBUG_INCLUDE_FAILED = "debug_include_failed"


class IsaacSyntheticSourceType(str, Enum):
    REAL_LEROBOT = "real_lerobot"
    ISAAC_RGBD_RENDER = "isaac_rgbd_render"
    REPLICATOR_RENDER_ONLY = "replicator_render_only"
    ISAAC_TELEOP_REPLAY_RENDER = "isaac_teleop_replay_render"
    ISAAC_LAB_MIMIC = "isaac_lab_mimic"
    ISAAC_LAB_RL_TEACHER = "isaac_lab_rl_teacher"
    LEGACY_SIDECAR = "legacy_sidecar"


class IsaacSyntheticRunStatus(str, Enum):
    IDLE = "IDLE"
    VALIDATING = "VALIDATING"
    BLOCKED = "BLOCKED"
    READY_TO_BUILD = "READY_TO_BUILD"
    BUILDING = "BUILDING"
    READY_FOR_PREVIEW = "READY_FOR_PREVIEW"
    READY_FOR_HDF5 = "READY_FOR_HDF5"
    READY_FOR_TRAINING = "READY_FOR_TRAINING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IsaacSyntheticStage(str, Enum):
    REQUEST = "request"
    RUNTIME = "runtime"
    DIGITAL_TWIN = "digital_twin"
    DEPTH = "depth"
    CANONICAL_INDEX = "canonical_index"
    PHYSICS = "physics"
    ARTICULATION = "articulation"
    REPLICATOR = "replicator"
    HDF5 = "hdf5"
    MIMIC = "mimic"
    RL_TEACHER = "rl_teacher"
    TRAINING = "training"
    LEGACY = "legacy"
```

Rules:

- GUI values must exactly match these enum values.
- API request models should reject unknown enum values with a normal FastAPI validation error.
- The bridge should store enum string values in JSON, not Python enum object names.
- Existing GUI fields may map into these enums only in one compatibility mapper.

#### Request Schema

Create one primary request model. The same model should feed `/validate`, `/prepare`, `/build-synthetic`, `/preview`, and `/export-hdf5`; each endpoint may use only the fields it needs.

```python
from pydantic import BaseModel, Field


class IsaacLabSyntheticRequest(BaseModel):
    dataset_path: str = Field(min_length=1)
    repo_id: str | None = None
    profile_name: str | None = None

    pipeline_mode: IsaacSyntheticPipelineMode = IsaacSyntheticPipelineMode.ISAAC_LAB_REPLICATOR
    fallback_policy: IsaacSyntheticFallbackPolicy = IsaacSyntheticFallbackPolicy.BLOCK_ON_PRIMARY_FAILURE
    source_intent: IsaacSyntheticSourceIntent = IsaacSyntheticSourceIntent.TRAIN_READY_SUCCESS_ONLY

    output_root: str | None = None
    force_rebuild: bool = False
    resume: bool = True
    overwrite_latest: bool = True
    dry_run: bool = False

    cameras: list[str] = Field(default_factory=lambda: ["top", "front", "right"])
    max_source_frames: int = Field(default=150, ge=1, le=5000)
    attempts_per_source_frame: int = Field(default=1, ge=1, le=100)
    seed: int = Field(default=42, ge=0)

    augmentation_profile: str = "conservative"
    rgb_strength: float = Field(default=0.15, ge=0.0, le=1.0)
    depth_strength: float = Field(default=0.15, ge=0.0, le=1.0)
    render_strength: float = Field(default=0.15, ge=0.0, le=1.0)
    camera_pose_strength: float = Field(default=0.05, ge=0.0, le=1.0)

    enable_replicator: bool = True
    enable_hdf5_export: bool = True
    enable_mimic: bool = False
    enable_rl_teacher: bool = False
    enable_legacy_fallback: bool = False

    mimic_trials: int = Field(default=20, ge=1, le=5000)
    mimic_num_envs: int = Field(default=1, ge=1, le=256)
    rl_teacher_steps: int = Field(default=0, ge=0)

    require_digital_twin_pass: bool = True
    require_physics_pass: bool = True
    require_depth_pass: bool = True
    require_articulation_pass: bool = True

    real_weight: float = Field(default=1.0, ge=0.0, le=2.0)
    isaac_rgbd_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    isaac_lab_synthetic_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    legacy_sidecar_weight: float = Field(default=0.0, ge=0.0, le=1.0)
```

Normalization rules:

- If `output_root` is absent, use `<dataset_path>/sidecar/isaac_lab_synthetic/latest`.
- If `pipeline_mode=legacy_sidecar`, set `enable_replicator=false`, `enable_mimic=false`, and `enable_rl_teacher=false`.
- If `fallback_policy=legacy_only`, set `pipeline_mode=legacy_sidecar`.
- If `source_intent=preview_only`, build preview artifacts but do not write `training_import/manifest.jsonl`.
- If `source_intent=train_ready_success_only`, write training import only for rows with `success=true`.
- If `source_intent=debug_include_failed`, failed rows may be visible in preview but still require an explicit `train_failed_rows=true` field before they can enter training. Do not add that field in the first slice.

#### Response Schema

All endpoints should return one response envelope:

```python
class IsaacLabStepTraceItem(BaseModel):
    stage: IsaacSyntheticStage
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    progress_start: float
    progress_end: float
    message: str
    artifact: str | None = None
    blocker_code: str | None = None


class IsaacLabSyntheticResponse(BaseModel):
    ok: bool
    tool: str
    schema: str = "atr.lerobot.isaac_lab_synthetic.response.v1"
    status: IsaacSyntheticRunStatus
    dataset_path: str
    output_root: str
    run_id: str
    job_id: str | None = None
    pipeline_mode: IsaacSyntheticPipelineMode
    fallback_policy: IsaacSyntheticFallbackPolicy
    source_intent: IsaacSyntheticSourceIntent
    fallback_used: bool = False
    validation_report: dict
    compatibility: dict
    digital_twin: dict
    canonical_episode_index: dict
    replicator: dict
    hdf5: dict
    mimic: dict
    rl_teacher: dict
    source_labels: dict
    training_exposure: dict
    progress: dict
    step_trace: list[IsaacLabStepTraceItem]
    error: dict | None = None
```

Response rules:

- `ok=false` whenever `status` is `BLOCKED`, `FAILED`, or `CANCELLED`.
- `ok=true` only when the requested endpoint completed its requested scope.
- `/prepare` may return `status=READY_TO_BUILD` without training artifacts.
- `/build-synthetic` may return `status=READY_FOR_PREVIEW`, `READY_FOR_HDF5`, or `READY_FOR_TRAINING` depending on enabled stages and `source_intent`.
- `error` must include `code`, `message`, `stage`, and `evidence` when `ok=false`.
- `step_trace` must include skipped stages with `status=skipped` so the GUI can explain why Mimic/RL did not run.

#### Job State Machine

The bridge should run synthetic work as a job with a deterministic state machine.

```text
IDLE
  -> VALIDATING
VALIDATING
  -> BLOCKED
  -> READY_TO_BUILD
READY_TO_BUILD
  -> BUILDING
BUILDING
  -> FAILED
  -> CANCELLED
  -> READY_FOR_PREVIEW
READY_FOR_PREVIEW
  -> READY_FOR_HDF5
READY_FOR_HDF5
  -> READY_FOR_TRAINING
READY_FOR_TRAINING
  -> IDLE for a new request
BLOCKED
  -> VALIDATING after config/dataset/stage changes
FAILED
  -> BUILDING when resume=true and the failed stage is resumable
CANCELLED
  -> BUILDING when resume=true
```

Transition rules:

- `BLOCKED` means a validator found a known, structured blocker.
- `FAILED` means an unexpected exception, process error, timeout, or invalid artifact happened.
- `CANCELLED` means the operator stopped a running job.
- Only one build job may run per dataset output root at a time.
- `/status` must not launch Isaac Sim, Isaac Lab, or camera access.
- `/mimic/stop` and `/rl-teacher/stop` must cancel only the relevant job, not live teleop.
- If a job is cancelled, write `summary.json` with `status=CANCELLED` and the last completed stage.

#### Atomic File Write Policy

Every JSON/JSONL artifact should be written atomically:

```text
<artifact>.tmp.<pid>
fsync temp file
rename temp file to final artifact path
```

Rules:

- Never expose partially written `manifest.jsonl` as train-ready.
- A stage is considered complete only when its `summary.json` exists and has `status=passed`.
- If `overwrite_latest=true`, move the previous `latest` to `runs/<run_id>` or write the new run under `runs/<run_id>` and update `latest` as a pointer file.
- Do not delete a previous successful `latest` until the new run has written a complete `summary.json`.
- If `resume=true`, use existing completed stage summaries and re-run only missing or failed stages.

#### Output Run Layout

The preferred concrete layout is:

```text
sidecar/isaac_lab_synthetic/
  latest -> runs/20260701_120000_a1b2c3
  runs/
    20260701_120000_a1b2c3/
      request.json
      summary.json
      validation_report.json
      progress.jsonl
      compatibility.json
      digital_twin_preflight.json
      depth_preflight.json
      physics_preflight.json
      articulation_preflight.json
      source_labels.json
      canonical_episode_index/
        manifest.jsonl
        summary.json
      replicator/
        request.json
        manifest.jsonl
        summary.json
        rgb/
        depth/
        segmentation/
        metadata/
      hdf5/
        export_request.json
        exported_successful_real_episodes.hdf5
        exported_generated_trajectories.hdf5
        export_summary.json
        validation.json
      mimic/
        request.json
        candidates.jsonl
        successes.jsonl
        failures.jsonl
        generated_dataset_small.hdf5
        generated_dataset.hdf5
        summary.json
      rl_teacher/
        request.json
        rollouts.jsonl
        successes.jsonl
        failures.jsonl
        checkpoints/
        summary.json
      training_import/
        manifest.jsonl
        summary.json
        lerobot_source_config.json
      previews/
        cards.jsonl
        index.html
```

The GUI may display `latest`, but backend code should store `run_id` in every response so logs can be traced to a fixed run directory.

#### `summary.json` Schema

```json
{
  "schema": "atr.lerobot.isaac_lab_synthetic.summary.v1",
  "run_id": "20260701_120000_a1b2c3",
  "status": "READY_FOR_TRAINING",
  "dataset_path": "/home/jin/autonomous_researcher/data/example",
  "output_root": "/home/jin/autonomous_researcher/data/example/sidecar/isaac_lab_synthetic/runs/20260701_120000_a1b2c3",
  "pipeline_mode": "isaac_lab_replicator",
  "fallback_policy": "block_on_primary_failure",
  "source_intent": "train_ready_success_only",
  "fallback_used": false,
  "started_at": "2026-07-01T12:00:00+09:00",
  "finished_at": "2026-07-01T12:05:00+09:00",
  "counts": {
    "real_frames": 750,
    "canonical_frames": 750,
    "replicator_rows": 2250,
    "mimic_candidates": 20,
    "mimic_successes": 12,
    "training_rows": 12
  },
  "artifacts": {
    "validation_report": "validation_report.json",
    "canonical_index": "canonical_episode_index/manifest.jsonl",
    "training_import": "training_import/manifest.jsonl"
  },
  "blockers": [],
  "warnings": []
}
```

Rules:

- Counts should be integers, never strings.
- Paths should be relative to the run directory unless the artifact is outside the run directory.
- `status` must match the API response status.
- `blockers` and `warnings` must use the same shape as validation report entries.

#### Canonical Episode Index Row Schema

Each `canonical_episode_index/manifest.jsonl` row should use:

```json
{
  "schema": "atr.lerobot.canonical_episode_frame.v1",
  "dataset_id": "robotis_omx_red_cube",
  "episode_index": 0,
  "frame_index": 42,
  "timestamp_s": 2.8,
  "lerobot": {
    "observation_path": "data/chunk-000/episode_000000.parquet",
    "action_index": 42,
    "action_valid": true
  },
  "real_rgb": {
    "path": "videos/chunk-000/observation.images.cam_high/episode_000000.mp4",
    "frame_index": 42,
    "available": true
  },
  "raw_depth": {
    "path": "sidecar/raw_depth/episode_000000/frame_000042.png",
    "available": true,
    "dtype": "uint16",
    "depth_units": "millimeter",
    "scale_m_per_unit": 0.001
  },
  "isaac_rgbd": {
    "available": true,
    "camera_names": ["top", "front", "right"],
    "manifest_row": 42
  },
  "active_robot_cam": {
    "available": true,
    "camera_model": "D405",
    "cube_pose_base": {
      "x_m": 0.12,
      "y_m": -0.04,
      "z_m": 0.02,
      "yaw_rad": 0.0
    }
  },
  "grasp_diagnostics": {
    "available": true,
    "state": "not_near_object",
    "left_contact_n": 0.0,
    "right_contact_n": 0.0
  },
  "source_completeness": {
    "required_missing": [],
    "optional_missing": []
  }
}
```

Rules:

- `episode_index`, `frame_index`, and `timestamp_s` are the primary ordering keys.
- Missing optional data should be marked with `available=false`; do not omit the whole object.
- Missing action or corrupted action must put a code in `required_missing`.
- `scale_m_per_unit` must reflect the actual depth source profile.
- `cube_pose_base` must always be robot-base frame when available.

#### Replicator Manifest Row Schema

Each `replicator/manifest.jsonl` row should use:

```json
{
  "schema": "atr.lerobot.replicator_frame.v1",
  "source_type": "replicator_render_only",
  "canonical_episode_index": 0,
  "canonical_frame_index": 42,
  "variant_index": 0,
  "camera_name": "top",
  "rgb_path": "replicator/rgb/top/e000000_f000042_v000.png",
  "depth_path": "replicator/depth/top/e000000_f000042_v000.png",
  "segmentation_path": "replicator/segmentation/top/e000000_f000042_v000.png",
  "metadata_path": "replicator/metadata/top/e000000_f000042_v000.json",
  "camera_pose_base": {
    "x_m": 0.0,
    "y_m": 0.0,
    "z_m": 0.7,
    "roll_rad": 0.0,
    "pitch_rad": -1.57,
    "yaw_rad": 0.0
  },
  "randomization": {
    "profile": "conservative",
    "rgb_strength": 0.15,
    "depth_strength": 0.15,
    "render_strength": 0.15,
    "camera_pose_strength": 0.05
  },
  "action_consistency": {
    "uses_original_action": true,
    "object_pose_changed": false,
    "trainable": true,
    "reason": "render_only_same_pose"
  }
}
```

Rules:

- If object pose changes beyond sidecar-only bounds, `action_consistency.trainable=false` unless a generated trajectory row exists.
- If a render-only row is marked trainable while exceeding sidecar-only XY/yaw bounds and no matching generated trajectory success row exists, build blocks with `ACTION_LABEL_MISMATCH_RISK`.
- Render-only rows can be previewed even when not trainable.
- Camera pose randomization must record the final camera pose, not only the strength.

#### Generated Trajectory Row Schema

Each Mimic or RL teacher success row should use:

```json
{
  "schema": "atr.lerobot.generated_trajectory.v1",
  "source_type": "isaac_lab_mimic",
  "trajectory_id": "mimic_000012",
  "source_episode_index": 0,
  "source_frame_index": 42,
  "generator": {
    "name": "isaac_lab_mimic",
    "seed": 42,
    "trial_index": 12
  },
  "object_pose_base": {
    "x_m": 0.12,
    "y_m": -0.04,
    "z_m": 0.02,
    "yaw_rad": 0.26
  },
  "subtasks": {
    "approach": {"start_frame": 0, "end_frame": 24},
    "grasp": {"start_frame": 25, "end_frame": 38},
    "lift": {"start_frame": 39, "end_frame": 62},
    "place": {"start_frame": 63, "end_frame": 92},
    "release": {"start_frame": 93, "end_frame": 110}
  },
  "metrics": {
    "success": true,
    "lift_height_m": 0.05,
    "final_place_error_m": 0.01,
    "max_penetration_m": 0.002,
    "left_contact_peak_n": 0.35,
    "right_contact_peak_n": 0.33
  },
  "artifacts": {
    "hdf5_path": "mimic/generated_dataset.hdf5",
    "preview_path": "previews/mimic_000012.html"
  },
  "training": {
    "eligible": true,
    "fidelity_weight": 0.25,
    "exclusion_reason": null
  }
}
```

Rules:

- Training import reads only generated rows where `metrics.success=true` and `training.eligible=true`.
- `max_penetration_m` should become a warning if it exceeds the physics profile threshold.
- Contact force metrics are diagnostics, not a replacement for collision geometry validation.
- RL teacher rows must use the same schema with `source_type=isaac_lab_rl_teacher`.

#### Training Import Row Schema

Each `training_import/manifest.jsonl` row should use:

```json
{
  "schema": "atr.lerobot.training_import_row.v1",
  "source_type": "isaac_lab_mimic",
  "source_id": "mimic_000012",
  "dataset_path": "/home/jin/autonomous_researcher/data/example",
  "artifact_path": "mimic/generated_dataset.hdf5",
  "episode_index": 0,
  "frame_start": 0,
  "frame_end": 110,
  "success": true,
  "source_weight": 0.25,
  "fidelity_weight": 0.25,
  "effective_weight": 0.0625,
  "validation_report": "../validation_report.json",
  "generation_manifest": "../mimic/successes.jsonl"
}
```

Effective weight rule:

```text
effective_weight = source_weight * fidelity_weight
```

Default weights:

- `real_lerobot`: `source_weight=1.0`, `fidelity_weight=1.0`.
- `isaac_rgbd_render`: `source_weight=0.35`, `fidelity_weight=0.5`.
- `replicator_render_only`: `source_weight=0.25`, `fidelity_weight=0.4`.
- `isaac_lab_mimic`: `source_weight=0.25`, `fidelity_weight=0.5`.
- `isaac_lab_rl_teacher`: `source_weight=0.1`, `fidelity_weight=0.3`, disabled by default.
- `legacy_sidecar`: `source_weight=0.0`, `fidelity_weight=0.2`, disabled by default.

Rules:

- `effective_weight` must be computed and stored; training code should not recompute it differently.
- A GUI change to fidelity weights must rewrite `lerobot_source_config.json`, not the original manifests.
- If a row has `success=false`, it cannot appear in `training_import/manifest.jsonl` in the first slice.

#### Progress Event Schema

Write progress to `progress.jsonl` so the GUI can reconnect after refresh:

```json
{
  "schema": "atr.lerobot.isaac_lab.progress.v1",
  "run_id": "20260701_120000_a1b2c3",
  "stage": "replicator",
  "status": "running",
  "percent": 47.5,
  "message": "Rendering top/front/right RGB-D variants.",
  "timestamp": "2026-07-01T12:03:30+09:00"
}
```

Progress allocation:

```text
request normalization: 0-3
runtime validation: 3-12
digital twin/depth/physics/articulation preflight: 12-30
canonical index: 30-40
replicator render: 40-62
hdf5 export: 62-72
mimic generation: 72-88
rl teacher smoke: 88-94
training import and summary: 94-100
```

Rules:

- The GUI progress bar should ease toward the latest reported percent and must not jump from a low value directly to `100` unless the job actually finished.
- A stage may emit repeated progress events with the same percent and a new message.
- A blocked job must leave progress below `100` and show the blocker code.

#### Domain Randomization Recipe Schema

Write the selected recipe to `request.json` and include it in Replicator/Lab configs:

```json
{
  "schema": "atr.lerobot.domain_randomization_recipe.v1",
  "profile": "conservative",
  "seed": 42,
  "workspace": {
    "name": "a4",
    "width_m": 0.210,
    "height_m": 0.297,
    "frame": "robot_base"
  },
  "object_pose": {
    "xy_jitter_m": 0.005,
    "yaw_jitter_rad": 0.087,
    "requires_generated_trajectory_above_xy_m": 0.01,
    "requires_generated_trajectory_above_yaw_rad": 0.174
  },
  "materials": {
    "paper_static_friction_range": [0.6, 1.0],
    "pla_static_friction_range": [0.4, 0.9],
    "gripper_inner_pad_static_friction_range": [1.0, 1.8]
  },
  "camera": {
    "pose_jitter_xyz_m": [0.003, 0.003, 0.003],
    "pose_jitter_rpy_rad": [0.035, 0.035, 0.035],
    "intrinsics_jitter_fraction": 0.01
  },
  "depth": {
    "dropout_probability": 0.01,
    "noise_std_m": 0.001,
    "scale_jitter_fraction": 0.005
  },
  "lighting": {
    "intensity_jitter_fraction": 0.15,
    "color_temperature_jitter_k": 300
  }
}
```

Rules:

- If object pose perturbation exceeds the `requires_generated_trajectory` thresholds, render-only rows are not trainable.
- D405 and D455f depth profiles must have separate noise parameters.
- Real raw depth data is never overwritten by randomized depth output.

#### GUI Element IDs

Use stable IDs so Playwright tests and future automation can drive the exact GUI path:

```text
isaac-synthetic-panel
isaac-synthetic-pipeline-mode
isaac-synthetic-fallback-policy
isaac-synthetic-source-intent
isaac-synthetic-profile
isaac-synthetic-cameras
isaac-synthetic-max-source-frames
isaac-synthetic-attempts-per-frame
isaac-synthetic-seed
isaac-synthetic-rgb-strength
isaac-synthetic-depth-strength
isaac-synthetic-render-strength
isaac-synthetic-camera-pose-strength
isaac-synthetic-enable-replicator
isaac-synthetic-enable-hdf5-export
isaac-synthetic-enable-mimic
isaac-synthetic-enable-rl-teacher
isaac-synthetic-check-digital-twin
isaac-synthetic-build
isaac-synthetic-preview
isaac-synthetic-export-hdf5
isaac-synthetic-run-mimic-smoke
isaac-synthetic-run-rl-teacher-smoke
isaac-synthetic-use-legacy-sidecar
isaac-synthetic-status-compatibility
isaac-synthetic-status-digital-twin
isaac-synthetic-status-source-labels
isaac-synthetic-status-canonical-index
isaac-synthetic-status-generation
isaac-synthetic-status-training-exposure
isaac-synthetic-progress
isaac-synthetic-step-trace
```

Rules:

- Buttons that can move the robot or start Isaac jobs must be disabled while another synthetic job is running.
- `Use Legacy Sidecar Builder` must be visually secondary and hidden behind an advanced disclosure.
- `Build Synthetic Dataset` must call the primary endpoint by default.
- Changing a GUI option after startup must affect the next request payload; do not cache section `7` settings only at first page load.

#### Backend File Responsibilities

Use these boundaries:

```text
app/main.py
  FastAPI request parsing and endpoint routing only.

mcp_tools/lerobot_schemas.py
  Shared enums, request models, response models, manifest helper types.

device_bridges/lerobot_bridge.py
  Public bridge methods called by FastAPI and training orchestration.

device_bridges/isaac_lab_runtime.py
  Isaac Lab/Sim runtime discovery and compatibility report.

device_bridges/isaac_digital_twin_preflight.py
  USD stage, prim, camera, depth, stage snapshot, and RTSP checks.

device_bridges/depth_profile_validation.py
  D405/D455f profile, raw 16-bit depth, scale, range, alignment checks.

device_bridges/isaac_physics_preflight.py
  Rigid body, collider, material, contact report, filtered pair checks.

device_bridges/isaac_articulation_preflight.py
  Joint mapping, zero-pose policy, drive target, command mode, mimic checks.

device_bridges/isaac_replicator_jobs.py
  Replicator dry run, render product creation, manifest collection.

device_bridges/isaac_lab_dataset_export.py
  Canonical LeRobot/sidecar to HDF5 export.

device_bridges/isaac_lab_mimic_jobs.py
  Mimic process launch, status, cancel, success/failure manifests.

device_bridges/isaac_lab_rl_jobs.py
  RL teacher smoke/evaluator launch, status, cancel, summary.

scripts/lerobot_isaac_lab_validate.py
  CLI wrapper over the same validation service used by GUI/API.

scripts/lerobot_canonical_episode_index.py
  Build and validate canonical episode index.

scripts/lerobot_isaac_replicator_build.py
  CLI wrapper for Replicator dry run and generation.

scripts/lerobot_isaac_lab_export_hdf5.py
  CLI wrapper for HDF5 export and validation.
```

Rules:

- FastAPI must not contain Isaac Sim-specific logic.
- CLI and GUI must call the same bridge/service methods, not separate implementations.
- Isaac runtime subprocess failures should return structured validation errors, not raw stack traces.
- Live teleop code should not be modified by this pipeline except for reading existing dataset/sidecar outputs.

#### Endpoint-Specific Behavior

`POST /api/lerobot/isaac-lab/validate`

- Runs selected validation groups.
- Writes `validation_report.json`.
- Does not create synthetic samples.
- Does not call legacy fallback.

`POST /api/lerobot/isaac-lab/prepare`

- Runs runtime, digital twin, depth, physics, and articulation validation.
- Writes preflight artifacts.
- Returns `READY_TO_BUILD` when no required group is blocked.

`POST /api/lerobot/isaac-lab/build-synthetic`

- Runs prepare if the latest prepare artifact is missing or stale.
- Builds canonical index.
- Runs Replicator when enabled.
- Exports HDF5 when enabled.
- Runs Mimic when enabled.
- Runs RL teacher smoke when enabled.
- Writes training import only when `source_intent=train_ready_success_only` and generated rows pass success filtering.

`POST /api/lerobot/isaac-lab/preview`

- Reads existing manifests only.
- Returns preview card metadata.
- Does not launch Isaac Sim.
- May return `BLOCKED` if no previewable artifacts exist.

`POST /api/lerobot/isaac-lab/export-hdf5`

- Requires canonical index.
- Exports success-filtered real episodes and generated trajectories.
- Writes HDF5 validation summary.

`GET /api/lerobot/isaac-lab/status`

- Reads latest `summary.json`, `validation_report.json`, and `progress.jsonl`.
- Never changes files except optional access logs.
- Never starts a long-running process.

#### Staleness Rules

A prepared artifact is stale when any of these changed:

- request `dataset_path`
- request `pipeline_mode`
- request `cameras`
- request `augmentation_profile`
- request strength values
- Isaac Lab tag/commit
- Isaac Sim version
- stage path or stage modified time
- LeRobot dataset modified time
- raw depth sidecar modified time
- active robot-cam cube pose result
- physics profile config
- source weight/fidelity config when validating training import

Stale behavior:

- `/status` reports stale artifacts but does not rebuild.
- `/prepare` rebuilds stale preflight artifacts.
- `/build-synthetic` rebuilds stale prerequisite stages when `resume=true`.
- If `resume=false`, the job starts a new run directory.

#### Timeout and Process Policy

Default timeouts:

```text
runtime import smoke: 60s
digital twin preflight: 120s
replicator dry run: 180s
replicator build: 1800s
hdf5 export: 600s
mimic small batch: 1800s
rl teacher smoke: 1800s
training import validation: 120s
```

Rules:

- Timeout produces `FAILED`, not `BLOCKED`, unless it maps to a known blocker.
- Long-running Isaac jobs should stream progress and stderr tail into `progress.jsonl`.
- GUI should show the last 50 log lines for a failed job.
- A timeout must not kill live teleop.

### Stage 0: Operator Intent and Dataset Selection

Inputs:

- selected LeRobot profile
- dataset root
- dataset repo id
- observation pipeline
- section `7` synthetic pipeline mode
- selected cameras
- augmentation profile
- source frame limit
- generated attempts per frame
- fallback policy

Outputs:

- normalized request payload
- selected dataset path
- selected synthetic output root
- intended source exposure policy

Rules:

- The build must not run without a concrete dataset path.
- The output root must remain under allowed roots.
- The request must record whether the operator intended preview-only or train-ready output.
- The request must record whether legacy fallback is allowed.

### Stage 1: Real Recording Remains the Source of Truth

The LeRobot live recording path remains unchanged. A successful real recording is the root input to all downstream synthetic work.

Required real recording outputs:

- LeRobot episode data
- action sequence
- observation metadata
- raw depth sidecar when the selected observation pipeline uses it
- active robot-cam result when enabled
- Isaac RGB-D render request metadata when Isaac mirror/render was active
- `meta/atr_pipeline.json` or equivalent dataset-level metadata

Do not run heavy Replicator, Mimic, or RL generation during live teleop or live recording. Recording must not be blocked by synthetic rendering except for the active robot-cam preflight gates that the operator intentionally enabled.

### Stage 2: Post-Recording Isaac RGB-D Render

After a recording episode succeeds, the Isaac RGB-D sidecar may render missing frames. This stage remains post-recording.

Inputs:

- LeRobot dataset path
- Isaac mirror stage
- selected render cameras, default `top,front,right`
- active robot-cam cube pose result
- frame sampling policy

Outputs:

- `sidecar/isaac_rgbd/**/manifest.jsonl`
- RGB images
- depth images
- camera pose metadata
- render status summary

Rules:

- Isaac RGB-D rendering should not slow the live teleop loop.
- Render FPS can be lower than control FPS, but the manifest must record source episode/frame/time.
- Depth units and camera intrinsics must be explicit.
- If render output is missing, the synthetic branch can still build a canonical index but must mark render sources as missing.

### Stage 3: Isaac Lab and Isaac Sim Compatibility Gate

The first action under `Build Synthetic Dataset` is compatibility checking.

Checks:

- local Isaac Lab path exists
- Isaac Lab git tag/commit can be read
- Isaac Sim runtime version can be read
- selected docs/runtime stack is compatible
- required Python environment is known
- Replicator imports are available
- Isaac Lab Mimic scripts are available
- robomimic import or install status is known
- RL wrapper availability is known
- A configured Isaac Sim Python path is not the same as a verified Replicator import. If the bridge does not launch the Isaac Sim worker in the current action, write `runtime_probe.status=pending`, `runtime_probe.import_checked=false`, and `runtime_probe.required_modules=["omni.replicator.core"]` into both `replicator/summary.json` and `replicator/build_plan.json`.

Outputs:

- `compatibility.json`
- status card in the GUI
- blocked state if the stack is unsupported

Blocked examples:

- Isaac Lab beta branch with non-beta Isaac Sim runtime
- Isaac Sim installed but Replicator extension cannot be imported
- Mimic scripts missing
- Python path points to the wrong environment

The operator may still run `legacy_sidecar` mode if the fallback policy allows it, but the fallback reason must be written into `summary.json`.

### Stage 4: Digital Twin Stage Preflight

This stage verifies that Isaac Sim represents the real setup well enough for synthetic generation.

Robot checks:

- robot prim exists
- articulation root exists
- expected joint names exist
- LeRobot/Dynamixel joint-name mapping exists
- zero pose definition exists
- current USD joint zero does not conflict with the bridge's real zero basis
- drive target, initial joint position, and first-frame target jump are checked
- max force/torque and max velocity are recorded
- stiffness/damping are recorded
- mimic joints have expected gear ratio and direction
- solver position and velocity iteration counts are recorded
- sleep and stabilization thresholds are recorded
- PLA link mass assumptions and D405 mount mass are recorded

Object and workspace checks:

- red cube prim exists
- cube collider type is known
- cube rigid body status is known
- cube mass/inertia are recorded
- A4 workspace transform is known
- table/paper material is assigned
- cube material and friction/restitution are assigned
- gripper inner-pad material is assigned separately from non-contact outer surfaces

Camera checks:

- real camera keys are known
- active robot-cam D405 priority is recorded
- D455 fallback status is recorded
- Isaac render cameras exist
- camera poses and intrinsics are explicit
- depth unit and scale are explicit
- RTSP stream config is optional and non-blocking unless the operator requested it

Outputs:

- `digital_twin_preflight.json`
- stage snapshot path
- preflight warning/failure codes

Failure policy:

- missing robot/cube/camera prims block Lab/Replicator generation
- missing RTSP stream does not block unless RTSP is selected as required
- friction/material warnings can allow preview but should block train-ready output if contact realism is required
- joint mapping mismatch blocks trajectory generation

### Stage 5: Canonical Episode Index

This is the central alignment layer. It replaces ad hoc lookup between real frames, raw depth, Isaac renders, and active robot-cam pose data.

Each row should represent one canonical frame or frame segment.

Required row fields:

```json
{
  "schema": "atr.lerobot.canonical_episode_frame.v1",
  "dataset_id": "...",
  "episode_index": 0,
  "frame_index": 123,
  "timestamp_s": 8.2,
  "action_ref": "...",
  "observation_ref": "...",
  "raw_depth_refs": {},
  "isaac_rgbd_refs": {},
  "active_robot_cam_pose_ref": "...",
  "cube_pose_real": {},
  "cube_pose_sim": {},
  "grasp_diagnostics_ref": "...",
  "source_availability": {},
  "missing_sources": [],
  "qa": {}
}
```

Outputs:

- `canonical_episode_index/manifest.jsonl`
- `canonical_episode_index/summary.json`

Rules:

- Missing sources are allowed but must be explicit.
- Active robot-cam pose can update the cube pose for the synthetic scene.
- The canonical index must keep original LeRobot action ordering untouched.
- The canonical index is the only accepted input to Lab HDF5 export and synthetic source import.

### Stage 6: Synthetic Build Plan

Before generating data, the pipeline writes a build plan.

The build plan resolves:

- selected frames/episodes
- selected cameras
- whether each frame gets render-only augmentation
- whether each frame gets trajectory generation
- number of candidate attempts
- object pose jitter bounds
- camera pose jitter bounds
- material/friction randomization bounds
- depth sensor profile
- source exposure policy
- expected output counts

This plan should be deterministic for a given seed. The GUI should show the plan before long jobs start.

### Stage 7: Replicator Perception Augmentation

This stage takes over the old RGB/depth/image/render-domain augmentation role.

Inputs:

- canonical episode index
- Isaac stage
- camera set
- Replicator writer config
- domain randomization config
- D405/D455 sensor profile config

Outputs:

- RGB images
- depth images
- segmentation masks when enabled
- normals or motion vectors when enabled
- per-frame camera metadata
- per-frame augmentation metadata
- `replicator/manifest.jsonl`
- `replicator/summary.json`

What moves from the legacy script:

- photometric jitter becomes Replicator image augmentation or writer augmentation
- sensor noise becomes depth/RGB render postprocessing or sensor profile
- render-domain randomization becomes Replicator material/light/camera randomization
- camera pose augmentation becomes camera transform randomization with manifest-backed action-consistency checks

Rules:

- Render-only variants that keep the original object pose can stay tied to the original action.
- Render-only variants that change cube XY/yaw beyond the sidecar-safe bound must not be exposed as action-consistent training rows.
- Every render variant must point back to a canonical row.
- Every render variant must record whether it is train-eligible.

### Stage 8: Isaac Lab HDF5 Export

This stage converts aligned real episodes into a format Isaac Lab and robomimic can consume.

Inputs:

- canonical episode index
- LeRobot actions
- robot state
- cube pose
- gripper state
- optional RGB-D tensors or file refs
- subtask labels where available

Outputs:

- `hdf5/exported_successful_real_episodes.hdf5`
- `hdf5/export_summary.json`

Rules:

- HDF5 export must preserve episode/action/frame ordering.
- Failed or aborted real episodes must not be exported as successful demonstrations unless explicitly marked as debug data.
- The export summary must list skipped episodes and skip reasons.
- If an episode has no valid cube pose or no matching action stream, it is not train-ready for Mimic.

### Stage 9: Isaac Lab Mimic Trajectory Generation

Mimic is the primary path for generating new trajectories for randomized cube poses.

Inputs:

- exported HDF5 demonstrations
- OMX Isaac Lab environment
- subtask definitions
- object pose randomization bounds
- action-to-target and target-to-action conversion helpers
- gripper-action extraction
- success criteria

Required environment helpers:

- `get_robot_eef_pose`
- `target_eef_pose_to_action`
- `action_to_target_eef_pose`
- `actions_to_gripper_actions`
- `get_object_poses`
- `get_subtask_term_signals`

Outputs:

- `mimic/candidates.jsonl`
- `mimic/successes.jsonl`
- `mimic/failures.jsonl`
- `mimic/generated_dataset_small.hdf5`
- `mimic/generated_dataset.hdf5`
- `mimic/summary.json`

Success criteria:

- approach reached
- gripper contact or grasp candidate detected
- cube lifted above threshold
- cube remained stable long enough
- placement or task completion condition satisfied
- no invalid penetration or solver explosion
- robot remained within joint/velocity/torque safety limits

Failure labels:

- `missing_object_pose`
- `ik_unreachable`
- `grasp_missed`
- `object_slipped`
- `object_tunneled`
- `joint_limit_violation`
- `solver_instability`
- `collision_invalid`
- `timeout`

Only rows in `mimic/successes.jsonl` may become `isaac_lab_mimic` training rows by default.

Current implementation status:

- dry-run smoke writes manifest-shaped `mimic/candidates.jsonl`, `mimic/successes.jsonl`, and `mimic/failures.jsonl`
- dry-run rows include A4-bounded cube pose perturbation metadata, subtask windows, success/failure labels, fidelity weight, and traceable artifact paths
- the training import path consumes only `mimic/successes.jsonl` by default
- actual Isaac Lab Mimic process execution remains the next runner step

### Stage 10: Optional RL Teacher / Evaluator

RL is not the default training source. It is a simulation-only teacher/evaluator branch.

Allowed uses:

- discover recovery trajectories
- evaluate randomized scene difficulty
- estimate task success under varied physics parameters
- create candidate trajectories that still require success filtering

Disallowed by default:

- direct deployment to the real robot
- replacing real teleop demonstrations
- mixing unverified RL failures into policy training

Outputs:

- `rl_teacher/rollouts.jsonl`
- `rl_teacher/successes.jsonl`
- `rl_teacher/failures.jsonl`
- `rl_teacher/summary.json`

Training inclusion must default to disabled until success filtering and source weights are explicitly configured.

Current implementation status:

- dry-run smoke writes manifest-shaped `rl_teacher/candidates.jsonl`, `rl_teacher/successes.jsonl`, and `rl_teacher/failures.jsonl`
- generated RL teacher rows remain simulation-only and are imported only when `enable_rl_teacher` is true
- actual RL teacher/evaluator process execution remains the next runner step

### Stage 11: Synthetic QA and Training Import

This stage decides what training can see.

QA inputs:

- canonical index
- Replicator manifest
- Mimic successes/failures
- RL teacher successes/failures
- digital twin preflight
- physics preflight
- action-consistency flags

Output:

- `training_import/manifest.jsonl`
- `training_import/summary.json`
- `training_import/lerobot_source_config.json`

Each training row must include:

```json
{
  "schema": "atr.lerobot.synthetic_training_row.v1",
  "source_type": "isaac_lab_mimic",
  "canonical_row_id": "...",
  "episode_index": 0,
  "frame_index": 123,
  "action_ref": "...",
  "observation_refs": {},
  "trajectory_ref": "...",
  "qa_ok": true,
  "train_eligible": true,
  "fidelity_weight": 0.3,
  "failure_code": null
}
```

Blocked rows should still be visible in QA summaries but must have `train_eligible=false`.

### Stage 12: LeRobot Training Integration

Training source order:

1. `real_original`
2. `isaac_rgbd_render`
3. `replicator_render_only`
4. `isaac_lab_mimic`
5. `isaac_lab_rl_teacher`
6. `legacy_sidecar`

Default training weights:

- real original: `1.0`
- Isaac RGB-D render: `0.5`
- Replicator render-only: `0.3`
- Isaac Lab Mimic: `0.2` to `0.4`
- Isaac Lab RL teacher: `0.0` until enabled
- legacy sidecar: `0.0` unless fallback mode enabled

Training must report:

- effective sample count per source
- source weight per source
- fidelity weight per source
- number of skipped rows
- skip/failure-code counts
- exact synthetic manifest path

Pi0.5, SmolVLA, and XVLA must all read the same source contract. Policy-specific conversions may differ, but they must not drop sidecar provenance.

### Stage 13: Visualization and Review

The GUI and visualization should show:

- original real frame
- raw depth preview
- Isaac RGB-D render
- Replicator render variant
- generated Mimic trajectory preview
- source label
- QA result
- training eligibility
- action-consistency status
- failure reason if not eligible

The viewer should support multiple episode indices, not only one episode at a time. For Isaac Lab synthetic data, the viewer should allow filtering by:

- source type
- success/failure
- failure code
- camera
- augmentation profile
- generated attempt id
- train eligibility

### Stage 14: Re-Recording and Resume Behavior

Re-recording must not corrupt prior synthetic outputs.

Rules:

- A newly recorded episode should invalidate only dependent synthetic rows.
- Synthetic build should overwrite `latest` but keep timestamped run folders where practical.
- If the operator reruns only Replicator, Mimic outputs should be marked stale if they depended on changed camera/object pose inputs.
- If the operator reruns Mimic only, Replicator outputs can remain valid if the canonical index did not change.
- Resume should read `summary.json` and continue from the first incomplete stage.

The GUI should show stale status explicitly:

- `fresh`
- `stale_due_to_recording_change`
- `stale_due_to_stage_change`
- `partial`
- `blocked`

### Stage 15: Legacy Fallback Behavior

The old augmentation builder remains useful but is no longer the standard path.

Allowed fallback cases:

- Isaac Lab missing
- Isaac Sim headless unavailable
- Replicator unavailable
- operator wants quick preview only
- CI test needs deterministic fast synthetic sidecars

Fallback requirements:

- write `fallback_used=true`
- write `fallback_reason`
- write `source_type=legacy_sidecar`
- write `train_eligible=false` by default unless operator explicitly enables legacy training exposure
- show a GUI warning that legacy sidecar variants do not generate new action trajectories

The legacy script must not silently handle large cube XY/yaw changes as if they are valid trajectory data.

### Stage 16: Error Handling Policy

The pipeline should never fail as a generic "augmentation failed" unless the process crashed before a stage could be identified.

Every blocker should map to a stage and code:

- `COMPAT_LAB_MISSING`
- `COMPAT_SIM_VERSION_UNSUPPORTED`
- `DIGITAL_TWIN_STAGE_MISSING`
- `DIGITAL_TWIN_JOINT_MAP_MISSING`
- `DIGITAL_TWIN_CAMERA_MISSING`
- `CANONICAL_INDEX_EMPTY`
- `REPLICATOR_IMPORT_FAILED`
- `REPLICATOR_RENDER_FAILED`
- `HDF5_EXPORT_FAILED`
- `MIMIC_ENV_MISSING`
- `MIMIC_NO_SUCCESSFUL_TRAJECTORIES`
- `RL_TEACHER_DISABLED`
- `TRAINING_IMPORT_EMPTY`
- `LEGACY_FALLBACK_NOT_ALLOWED`

The GUI should render:

- blocking stage
- human-readable message
- path to partial output
- recommended next action

### Stage 17: Minimum Implementation Slice

The first implementation slice should not try to complete full Mimic/RL generation.

Minimum useful slice:

1. Rename section `7` to `Isaac Lab Synthetic Intelligence`.
2. Add pipeline mode and fallback policy controls.
3. Add `Check Digital Twin`.
4. Add `Build Synthetic Dataset` wired to a new endpoint.
5. Implement compatibility detection and source-label summary.
6. Implement canonical episode index.
7. Implement Replicator/legacy selection but allow legacy only when requested.
8. Write `sidecar/isaac_lab_synthetic/latest/summary.json`.
9. Show status cards and training exposure summary.

Second slice:

1. Add HDF5 export.
2. Add Mimic small batch.
3. Add success/failure import manifest.
4. Add training source weights for `isaac_lab_mimic`.

Third slice:

1. Add full Replicator writer branch.
2. Add full Mimic generation.
3. Add optional RL teacher/evaluator.
4. Add rich viewer filtering.

## Implementation-Ready Work Breakdown

This section translates the end-to-end target into concrete implementation work. The first implementation pass should produce a usable GUI/API/data-contract skeleton even if full Isaac Lab Mimic generation is still stubbed behind a blocked status. Do not leave ambiguous "wire later" gaps; every control should either call a working implementation or return a structured blocked response with a concrete blocker code.

### Work Package 1: Request Schema and API Surface

**Files to edit:**

- `app/main.py`
- `mcp_tools/lerobot_schemas.py`
- `tests/integration/test_lerobot_gui_api.py`
- `tests/unit/test_lerobot_gui_static.py`

**Add request fields to `LeRobotAPIRequest` and `LeRobotSessionRequest`:**

```python
isaac_synthetic_pipeline_mode: Literal[
    "isaac_lab_replicator",
    "replicator_render_only",
    "legacy_sidecar",
] = "isaac_lab_replicator"
isaac_synthetic_fallback_policy: Literal[
    "block_on_primary_failure",
    "allow_legacy_fallback",
    "legacy_only",
] = "block_on_primary_failure"
isaac_synthetic_source_intent: Literal[
    "preview_only",
    "train_ready_success_only",
    "debug_include_failed",
] = "train_ready_success_only"
isaac_lab_output_dir: str = ""
isaac_lab_generated_attempts_per_frame: int = 8
isaac_lab_max_source_frames: int = 200
isaac_lab_seed: int | None = 0
isaac_lab_cameras: str = "top,front,right"
isaac_lab_enable_replicator: bool = True
isaac_lab_enable_hdf5_export: bool = True
isaac_lab_enable_mimic: bool = False
isaac_lab_enable_rl_teacher: bool = False
isaac_lab_mimic_trials: int = 10
isaac_lab_mimic_num_envs: int = 1
isaac_lab_replicator_variants: int = 8
isaac_lab_force_rebuild: bool = False
isaac_lab_resume: bool = True
isaac_lab_require_digital_twin_pass: bool = True
isaac_lab_require_physics_pass: bool = True
isaac_lab_legacy_train_exposure: bool = False
```

**Compatibility mapping from old fields:**

- `isaac_data_augmentation_profile` remains accepted and maps to synthetic recipe profile.
- `isaac_data_augmentation_variants` maps to `isaac_lab_generated_attempts_per_frame` if the new field is absent.
- `isaac_data_augmentation_max_frames` maps to `isaac_lab_max_source_frames` if the new field is absent.
- `isaac_data_augmentation_cameras` maps to `isaac_lab_cameras` if the new field is absent.
- `isaac_data_augmentation_*_strength` values remain accepted and map to Lab/Replicator config.

**Add FastAPI routes in `app/main.py`:**

```python
@app.post("/api/lerobot/isaac-lab/prepare")
async def post_lerobot_isaac_lab_prepare(req: LeRobotAPIRequest) -> dict[str, object]:
    result = _lerobot_bridge().isaac_lab_prepare(req.model_dump())
    return _json_safe(result)

@app.post("/api/lerobot/isaac-lab/build-synthetic")
async def post_lerobot_isaac_lab_build_synthetic(req: LeRobotAPIRequest) -> dict[str, object]:
    result = _lerobot_bridge().isaac_lab_build_synthetic(req.model_dump())
    return _json_safe(result)

@app.post("/api/lerobot/isaac-lab/preview")
async def post_lerobot_isaac_lab_preview(req: LeRobotAPIRequest) -> dict[str, object]:
    result = _lerobot_bridge().isaac_lab_preview(req.model_dump())
    return _json_safe(result)

@app.post("/api/lerobot/isaac-lab/export-hdf5")
async def post_lerobot_isaac_lab_export_hdf5(req: LeRobotAPIRequest) -> dict[str, object]:
    result = _lerobot_bridge().isaac_lab_export_hdf5(req.model_dump())
    return _json_safe(result)
```

Mimic/RL long jobs should follow the existing start/status/stop pattern:

```python
@app.post("/api/lerobot/isaac-lab/mimic/start")
@app.post("/api/lerobot/isaac-lab/mimic/status")
@app.post("/api/lerobot/isaac-lab/mimic/stop")
@app.post("/api/lerobot/isaac-lab/rl-teacher/start")
@app.post("/api/lerobot/isaac-lab/rl-teacher/status")
@app.post("/api/lerobot/isaac-lab/rl-teacher/stop")
```

**Acceptance criteria:**

- Posting default JSON to `/api/lerobot/isaac-lab/prepare` returns a JSON object, not a validation error.
- Old augmentation requests still validate.
- Integration tests confirm the new routes exist and return tool names when the bridge is mocked.
- Static tests confirm new GUI controls are present and payload fields are emitted.

### Work Package 2: GUI Markup for Section 7

**Files to edit:**

- `web/templates/lerobot.html`
- `tests/unit/test_lerobot_gui_static.py`

**Rename section:**

```html
<h2>7. Isaac Lab Synthetic Intelligence</h2>
<span class="hint">Synthetic trajectories + Replicator + legacy fallback</span>
```

**Replace the current note with explicit source language:**

```html
Build trainable synthetic sources from the selected real LeRobot dataset. The standard path uses Isaac Lab and Isaac Sim Replicator; the legacy sidecar builder is available only as an explicit fallback.
```

**Add controls before the existing augmentation profile controls:**

```html
<label>
  Synthetic Pipeline
  <select id="lerobot-isaac-synthetic-pipeline-mode-input">
    <option value="isaac_lab_replicator" selected>Isaac Lab + Replicator</option>
    <option value="replicator_render_only">Replicator render only</option>
    <option value="legacy_sidecar">Legacy sidecar only</option>
  </select>
</label>
<label>
  Fallback Policy
  <select id="lerobot-isaac-synthetic-fallback-policy-input">
    <option value="block_on_primary_failure" selected>Block on primary failure</option>
    <option value="allow_legacy_fallback">Allow legacy fallback</option>
    <option value="legacy_only">Legacy only</option>
  </select>
</label>
<label>
  Source Intent
  <select id="lerobot-isaac-synthetic-source-intent-input">
    <option value="train_ready_success_only" selected>Train-ready success only</option>
    <option value="preview_only">Preview only</option>
    <option value="debug_include_failed">Debug include failed</option>
  </select>
</label>
```

**Add advanced controls near the current numeric controls:**

```html
<label>
  Mimic Trials
  <input id="lerobot-isaac-lab-mimic-trials-input" type="number" min="1" max="100000" value="10" />
</label>
<label>
  Mimic Envs
  <input id="lerobot-isaac-lab-mimic-envs-input" type="number" min="1" max="256" value="1" />
</label>
```

**Add checkboxes:**

```html
<label class="checkbox-line"><input id="lerobot-isaac-lab-replicator-input" type="checkbox" checked /> Replicator perception branch</label>
<label class="checkbox-line"><input id="lerobot-isaac-lab-hdf5-input" type="checkbox" checked /> HDF5 export branch</label>
<label class="checkbox-line"><input id="lerobot-isaac-lab-mimic-input" type="checkbox" /> Mimic trajectory branch</label>
<label class="checkbox-line"><input id="lerobot-isaac-lab-rl-teacher-input" type="checkbox" /> RL teacher branch</label>
<label class="checkbox-line"><input id="lerobot-isaac-lab-legacy-train-exposure-input" type="checkbox" /> Allow legacy sidecar in training</label>
```

**Replace button row:**

```html
<button id="btn-isaac-synthetic-preflight" class="btn">Check Digital Twin</button>
<button id="btn-isaac-synthetic-build" class="btn primary">Build Synthetic Dataset</button>
<button id="btn-isaac-synthetic-preview" class="btn">Preview Synthetic Sources</button>
<button id="btn-isaac-synthetic-export-hdf5" class="btn">Export HDF5</button>
<button id="btn-isaac-synthetic-mimic-start" class="btn">Run Mimic Small Batch</button>
<button id="btn-isaac-augment-run" class="btn warning">Use Legacy Sidecar Builder</button>
```

The existing legacy `btn-isaac-augment-run` can remain but should be visually demoted. Do not remove it in the first pass because tests and operators may still depend on it.

**Add output containers:**

```html
<div id="lerobot-isaac-synthetic-action-status" class="lerobot-action-status idle">Waiting for synthetic pipeline action.</div>
<div id="lerobot-isaac-synthetic-progress" class="lerobot-training-progress hidden">...</div>
<div id="lerobot-isaac-synthetic-summary" class="lerobot-visualization"></div>
<div id="lerobot-isaac-synthetic-preview" class="lerobot-visualization"></div>
```

**Acceptance criteria:**

- Section title changed.
- Existing controls still exist for compatibility.
- New controls and buttons have stable IDs.
- Static tests assert every new ID exists.

### Work Package 3: Frontend Runtime Wiring

**Files to edit:**

- `web/static/lerobot.js`
- `tests/unit/test_lerobot_gui_static.py`

**Add constants near existing `isaacAugment*` constants:**

```javascript
const isaacSyntheticPipelineModeInput = $("lerobot-isaac-synthetic-pipeline-mode-input");
const isaacSyntheticFallbackPolicyInput = $("lerobot-isaac-synthetic-fallback-policy-input");
const isaacSyntheticSourceIntentInput = $("lerobot-isaac-synthetic-source-intent-input");
const isaacLabMimicTrialsInput = $("lerobot-isaac-lab-mimic-trials-input");
const isaacLabMimicEnvsInput = $("lerobot-isaac-lab-mimic-envs-input");
const isaacLabReplicatorInput = $("lerobot-isaac-lab-replicator-input");
const isaacLabHdf5Input = $("lerobot-isaac-lab-hdf5-input");
const isaacLabMimicInput = $("lerobot-isaac-lab-mimic-input");
const isaacLabRlTeacherInput = $("lerobot-isaac-lab-rl-teacher-input");
const isaacLabLegacyTrainExposureInput = $("lerobot-isaac-lab-legacy-train-exposure-input");
const isaacSyntheticProgressEl = $("lerobot-isaac-synthetic-progress");
const isaacSyntheticProgressLabelEl = $("lerobot-isaac-synthetic-progress-label");
const isaacSyntheticProgressBarEl = $("lerobot-isaac-synthetic-progress-bar");
const isaacSyntheticSummaryEl = $("lerobot-isaac-synthetic-summary");
const isaacSyntheticPreviewEl = $("lerobot-isaac-synthetic-preview");
```

**Add payload helper:**

```javascript
function isaacSyntheticPayload() {
  const payload = isaacAugmentationPayload();
  return {
    ...payload,
    isaac_synthetic_pipeline_mode: isaacSyntheticPipelineModeInput ? isaacSyntheticPipelineModeInput.value : "isaac_lab_replicator",
    isaac_synthetic_fallback_policy: isaacSyntheticFallbackPolicyInput ? isaacSyntheticFallbackPolicyInput.value : "block_on_primary_failure",
    isaac_synthetic_source_intent: isaacSyntheticSourceIntentInput ? isaacSyntheticSourceIntentInput.value : "train_ready_success_only",
    isaac_lab_generated_attempts_per_frame: numberValue(isaacAugmentVariantsInput, 8),
    isaac_lab_max_source_frames: numberValue(isaacAugmentMaxFramesInput, 200),
    isaac_lab_seed: numberValue(isaacAugmentSeedInput, 0),
    isaac_lab_cameras: isaacAugmentCamerasInput ? isaacAugmentCamerasInput.value.trim() || "top,front,right" : "top,front,right",
    isaac_lab_enable_replicator: boolValue(isaacLabReplicatorInput),
    isaac_lab_enable_hdf5_export: boolValue(isaacLabHdf5Input),
    isaac_lab_enable_mimic: boolValue(isaacLabMimicInput),
    isaac_lab_enable_rl_teacher: boolValue(isaacLabRlTeacherInput),
    isaac_lab_mimic_trials: numberValue(isaacLabMimicTrialsInput, 10),
    isaac_lab_mimic_num_envs: numberValue(isaacLabMimicEnvsInput, 1),
    isaac_lab_replicator_variants: numberValue(isaacAugmentVariantsInput, 8),
    isaac_lab_legacy_train_exposure: boolValue(isaacLabLegacyTrainExposureInput),
  };
}
```

**Add action functions:**

```javascript
async function prepareIsaacSynthetic(statusTarget = null) {
  return runIsaacSyntheticAction(
    "/api/lerobot/isaac-lab/prepare",
    "Isaac synthetic preflight",
    renderIsaacSyntheticSummary,
    statusTarget,
    120000,
  );
}

async function buildIsaacSynthetic(statusTarget = null) {
  return runIsaacSyntheticAction(
    "/api/lerobot/isaac-lab/build-synthetic",
    "Isaac synthetic dataset",
    renderIsaacSyntheticSummary,
    statusTarget,
    600000,
  );
}

async function previewIsaacSynthetic(statusTarget = null) {
  return runIsaacSyntheticAction(
    "/api/lerobot/isaac-lab/preview",
    "Isaac synthetic preview",
    renderIsaacSyntheticPreview,
    statusTarget,
    120000,
  );
}
```

`runIsaacSyntheticAction` should mirror `runIsaacAugmentation`, using `postJson`, `setActionStatus`, `renderResult`, and `renderUnifiedProgress`.

**Render summary cards:**

`renderIsaacSyntheticSummary(data)` should render:

- top status pill: `READY_FOR_TRAINING`, `PREVIEW_READY`, `BLOCKED`, `PARTIAL`, `FAILED`
- output root
- compatibility rows
- digital twin rows
- source label counts
- canonical index summary
- training exposure summary
- step trace details
- fallback warning if `fallback_used=true`

**Bind buttons near existing button bindings:**

```javascript
$("btn-isaac-synthetic-preflight")?.addEventListener("click", () => prepareIsaacSynthetic($("lerobot-isaac-synthetic-action-status")));
$("btn-isaac-synthetic-build")?.addEventListener("click", () => buildIsaacSynthetic($("lerobot-isaac-synthetic-action-status")));
$("btn-isaac-synthetic-preview")?.addEventListener("click", () => previewIsaacSynthetic($("lerobot-isaac-synthetic-action-status")));
$("btn-isaac-synthetic-export-hdf5")?.addEventListener("click", () => exportIsaacSyntheticHdf5($("lerobot-isaac-synthetic-action-status")));
$("btn-isaac-synthetic-mimic-start")?.addEventListener("click", () => startIsaacSyntheticMimic($("lerobot-isaac-synthetic-action-status")));
```

**Acceptance criteria:**

- New buttons call new endpoints, not legacy endpoints.
- Legacy button still calls `/api/lerobot/augment/isaac`.
- Progress bar works for synthetic pipeline and does not reuse the same DOM IDs as legacy augmentation.
- Static tests assert endpoint strings exist in JS.

### Work Package 4: Bridge Public Methods

**Files to edit:**

- `device_bridges/lerobot_bridge.py`
- `tests/unit/test_lerobot_bridge.py`
- `tests/integration/test_lerobot_gui_api.py`

**Add public methods next to `augment_isaac_dataset`:**

```python
def isaac_lab_prepare(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ...

def isaac_lab_build_synthetic(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ...

def isaac_lab_preview(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ...

def isaac_lab_export_hdf5(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ...

def isaac_lab_mimic_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ...

def isaac_lab_mimic_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ...

def isaac_lab_mimic_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
```

**Common helper:**

```python
def _isaac_lab_context(self, payload: dict[str, Any] | None, *, tool: str) -> tuple[LeRobotSessionRequest, str, str, Path, Path] | dict[str, Any]:
    request = LeRobotSessionRequest.model_validate(payload or {})
    mode = request.runtime_mode or request.mode
    profile_id = request.profile_id or self._selected_profile_id
    dataset_path = Path(self._dataset_path_for(request)).expanduser().resolve()
    if not self._is_under_allowed_roots(dataset_path):
        return self._error(tool, mode, profile_id, "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS", ...)
    output_root = self._isaac_lab_output_root(dataset_path, request)
    if not self._is_under_allowed_roots(output_root):
        return self._error(tool, mode, profile_id, "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS", ...)
    return request, mode, profile_id, dataset_path, output_root
```

**Output root helper:**

```python
def _isaac_lab_output_root(self, dataset_path: Path, request: LeRobotSessionRequest) -> Path:
    raw = str(getattr(request, "isaac_lab_output_dir", "") or "").strip()
    if raw:
        return _resolve_path(self.config.repo_root, raw).expanduser().resolve()
    return dataset_path / "sidecar" / "isaac_lab_synthetic" / "latest"
```

**`isaac_lab_prepare` must run:**

1. request context
2. output directory creation
3. compatibility check
4. digital-twin preflight
5. source-label preview
6. optional canonical index preview count
7. write `summary.json` with `status=PREPARED` or `BLOCKED`

**`isaac_lab_build_synthetic` must run:**

1. request context
2. compatibility check
3. digital-twin preflight
4. canonical index build
5. synthetic build plan
6. Replicator branch or structured blocked/fallback result
7. optional HDF5 export
8. optional Mimic small batch if enabled
9. training import manifest
10. write final `summary.json`

**Fallback logic:**

```python
if pipeline_mode == "legacy_sidecar" or (primary_blocked and fallback_policy == "allow_legacy_fallback"):
    legacy = self.augment_isaac_dataset(payload)
    return self._isaac_lab_wrap_legacy_result(...)
if primary_blocked and fallback_policy == "block_on_primary_failure":
    return blocked_response
```

**Acceptance criteria:**

- `isaac_lab_prepare` writes `sidecar/isaac_lab_synthetic/latest/summary.json`.
- `isaac_lab_build_synthetic` returns `fallback_used=false` by default.
- If Isaac Lab is unavailable and fallback is blocked, response is `ok=false`, `status=BLOCKED`, `error_code=COMPAT_LAB_MISSING` or equivalent.
- If `legacy_sidecar` mode is selected, response wraps legacy output and sets `fallback_used=true`, `source_type=legacy_sidecar`.

### Work Package 5: Compatibility Detector

**Files to edit/create:**

- `device_bridges/lerobot_bridge.py`
- optionally `scripts/lerobot_isaac_lab_synthetic.py`
- `tests/unit/test_lerobot_bridge.py`

**Helper signature:**

```python
def _isaac_lab_compatibility(self, output_root: Path) -> dict[str, Any]:
    ...
```

**Detection logic:**

- Candidate Isaac Lab paths:
  - `/home/jin/IsaacLab`
  - `self.config.repo_root.parent / "IsaacLab"`
  - env `ISAACLAB_PATH`
- Read git commit:
  - `git -C <path> rev-parse HEAD`
- Read git tag:
  - `git -C <path> describe --tags --always --dirty`
- Detect Isaac Sim:
  - env `ISAACSIM_PATH`
  - common local paths if already used in project config
  - Python import smoke when available
- Detect Replicator:
  - command preview for `python -c "import omni.replicator.core"`
  - if not runnable outside Isaac Sim, return `status=unknown_requires_isaac_python`, not generic failure
- Detect Mimic files:
  - `<IsaacLab>/scripts/imitation_learning/isaaclab_mimic/generate_dataset.py`
  - `<IsaacLab>/scripts/imitation_learning/isaaclab_mimic/annotate_demos.py`
  - `<IsaacLab>/scripts/tools/record_demos.py`
  - `<IsaacLab>/scripts/imitation_learning/robomimic/train.py`

**Output shape:**

```json
{
  "schema": "atr.isaac_lab.compatibility.v1",
  "status": "ok|warning|blocked",
  "lab": {
    "path": "/home/jin/IsaacLab",
    "exists": true,
    "git_tag": "v3.0.0-beta2",
    "git_commit": "...",
    "is_beta": true
  },
  "sim": {
    "path": "",
    "version": "",
    "docs_version": "6.0.0",
    "status": "unknown|ok|blocked"
  },
  "replicator": {
    "available": false,
    "reason": "requires_isaac_python"
  },
  "mimic": {
    "scripts_present": true
  },
  "blockers": [],
  "warnings": []
}
```

**Acceptance criteria:**

- Missing Isaac Lab path produces `status=blocked`, not exception.
- Local `/home/jin/IsaacLab` is reported when present.
- Beta Lab stack requires compatible Sim docs/runtime version marker.
- Result is written to `compatibility.json`.

### Work Package 6: Digital Twin Preflight

**Files to edit/create:**

- `device_bridges/lerobot_bridge.py`
- later optional `sim/robotis_omx/tools/isaac_stage_preflight.py`
- `tests/unit/test_lerobot_bridge.py`

**Helper signature:**

```python
def _isaac_lab_digital_twin_preflight(
    self,
    dataset_path: Path,
    output_root: Path,
    request: LeRobotSessionRequest,
) -> dict[str, Any]:
    ...
```

**Minimum first implementation:**

The first pass can be metadata-based and not require Isaac Sim running.

Read/check:

- dataset path exists
- `sidecar/isaac_rgbd` exists and manifest count
- `sidecar/depth_raw` or `sidecar/raw_depth` exists
- active robot-cam result file exists when configured
- mirror config fields from request:
  - `isaac_mirror_enabled`
  - `isaac_mirror_endpoint`
  - `isaac_mirror_sample_hz`
- selected cameras from request
- D405/D455 priority fields from request
- latest augmentation summary if legacy exists

Output:

```json
{
  "schema": "atr.isaac_lab.digital_twin_preflight.v1",
  "status": "ok|warning|blocked",
  "dataset_path": "...",
  "stage": {
    "path": "",
    "snapshot_path": "",
    "available": false,
    "status": "metadata_only"
  },
  "robot": {
    "joint_mapping_available": "unknown",
    "zero_pose_available": "unknown",
    "d405_mount_mass_recorded": false
  },
  "cameras": {
    "requested": ["top", "front", "right"],
    "isaac_rgbd_manifest_count": 0,
    "raw_depth_available": true,
    "active_robot_cam_available": true
  },
  "physics": {
    "status": "not_checked_without_isaac_runtime",
    "block_training_if_required": true
  },
  "warnings": [],
  "blockers": []
}
```

**Later Isaac runtime implementation:**

- Query USD stage prims.
- Confirm robot prim, cube prim, A4/table prim, cameras.
- Query collider approximations.
- Query physics materials.
- Query articulation root and solver settings.
- Query joint drive gains and mimic config.
- Export `stage_snapshot.usd`.

**Acceptance criteria:**

- Metadata-only preflight works in normal FastAPI tests.
- Missing dataset path blocks.
- Missing raw depth warns when observation pipeline does not require it, blocks when raw-depth adapter is selected.
- Missing Isaac RGB-D render warns but does not block canonical index.

### Work Package 7: Source Label Summary

**Files to edit:**

- `device_bridges/lerobot_bridge.py`
- `tests/unit/test_lerobot_bridge.py`

**Helper signature:**

```python
def _isaac_lab_source_labels(
    self,
    dataset_path: Path,
    output_root: Path,
    request: LeRobotSessionRequest,
    *,
    canonical_summary: dict[str, Any] | None = None,
    replicator_summary: dict[str, Any] | None = None,
    mimic_summary: dict[str, Any] | None = None,
    legacy_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ...
```

**Write `source_labels.json`:**

```json
{
  "schema": "atr.lerobot.synthetic_source_labels.v1",
  "sources": {
    "real_lerobot": {"available": true, "train_default": true, "weight": 1.0},
    "isaac_rgbd_render": {"available": false, "train_default": false, "weight": 0.5},
    "replicator_render_only": {"available": false, "train_default": false, "weight": 0.3},
    "isaac_teleop_replay_render": {"available": false, "train_default": false, "render_only": true},
    "isaac_lab_mimic": {"available": false, "train_default": false, "success_only": true},
    "isaac_lab_rl_teacher": {"available": false, "train_default": false},
    "legacy_sidecar": {"available": false, "train_default": false}
  },
  "counts": {},
  "warnings": []
}
```

**Acceptance criteria:**

- Real source always exists if dataset path exists.
- Legacy source becomes available when `sidecar/isaac_augmentation/latest/summary.json` exists.
- Isaac RGB-D source becomes available when manifests exist.
- Mimic source is train-default only when success count > 0 and source intent allows training.

### Work Package 8: Canonical Episode Index Builder

**Files to create/edit:**

- `scripts/lerobot_canonical_episode_index.py`
- `device_bridges/lerobot_bridge.py`
- `tests/unit/test_lerobot_canonical_episode_index.py`
- `tests/unit/test_lerobot_bridge.py`

**Script entrypoint:**

```bash
python scripts/lerobot_canonical_episode_index.py \
  --dataset-path <dataset> \
  --output-dir <dataset>/sidecar/isaac_lab_synthetic/latest/canonical_episode_index \
  --max-source-frames 200 \
  --cameras top,front,right
```

**Python function:**

```python
def build_canonical_episode_index(
    *,
    dataset_path: Path,
    output_dir: Path,
    max_source_frames: int,
    cameras: list[str],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    ...
```

**Minimum first-pass data sources:**

- read LeRobot metadata enough to list episodes/frames when available
- read `sidecar/isaac_rgbd/**/manifest.jsonl`
- read `sidecar/depth_raw/transform_manifest.json` if present
- read active robot-cam result JSON if present
- read `sidecar/attempts` metadata when available
- when real frame enumeration is hard, build from Isaac RGB-D manifests and dataset metadata, but mark missing real frame refs explicitly

**Row ID:**

```text
episode_{episode_index:06d}:frame_{frame_index:08d}
```

**Summary fields:**

```json
{
  "schema": "atr.lerobot.canonical_episode_index.summary.v1",
  "ok": true,
  "row_count": 0,
  "episode_count": 0,
  "raw_depth_rows": 0,
  "isaac_rgbd_rows": 0,
  "active_robot_cam_rows": 0,
  "missing_source_counts": {},
  "manifest_path": "...",
  "output_dir": "..."
}
```

**Acceptance criteria:**

- Produces valid JSONL even with only a minimal fake dataset.
- Missing optional sidecars do not crash.
- Summary counts match manifest rows.
- Bridge calls this builder from `isaac_lab_build_synthetic`.

### Work Package 9: Synthetic Build Plan Writer

**Files to edit/create:**

- `device_bridges/lerobot_bridge.py`
- optionally `scripts/lerobot_isaac_lab_synthetic.py`
- `tests/unit/test_lerobot_bridge.py`

**Helper signature:**

```python
def _isaac_lab_write_build_plan(
    self,
    output_root: Path,
    request: LeRobotSessionRequest,
    canonical_summary: dict[str, Any],
) -> dict[str, Any]:
    ...
```

**Output `build_plan.json`:**

```json
{
  "schema": "atr.lerobot.isaac_lab_synthetic.build_plan.v1",
  "seed": 0,
  "pipeline_mode": "isaac_lab_replicator",
  "fallback_policy": "block_on_primary_failure",
  "source_intent": "train_ready_success_only",
  "selected_cameras": ["top", "front", "right"],
  "source_frame_limit": 200,
  "generated_attempts_per_frame": 8,
  "branches": {
    "replicator": {"enabled": true, "variants": 8},
    "hdf5_export": {"enabled": true},
    "mimic": {"enabled": false, "trials": 10, "num_envs": 1},
    "rl_teacher": {"enabled": false}
  },
  "strengths": {
    "rgb": 1.0,
    "depth": 1.0,
    "render": 1.0,
    "camera_pose": 1.0
  },
  "expected_outputs": {}
}
```

**Acceptance criteria:**

- Build plan is deterministic for same request.
- Build plan is included in main summary.
- GUI summary renders plan branch status.

### Work Package 10: Replicator Branch Wrapper

**Files to create/edit:**

- `scripts/lerobot_isaac_replicator_synthetic.py`
- `device_bridges/lerobot_bridge.py`
- `tests/unit/test_lerobot_bridge.py`

**First-pass behavior:**

If Isaac Sim runtime is not available, do not pretend Replicator ran. Write a structured blocked summary:

```json
{
  "schema": "atr.lerobot.replicator_synthetic.summary.v1",
  "ok": false,
  "status": "blocked",
  "blocker": "REPLICATOR_REQUIRES_ISAAC_RUNTIME",
  "rendered_count": 0,
  "train_eligible_count": 0
}
```

If Isaac Sim Python is configured but the current bridge action only prepares a worker plan, return `status=ready` for the worker plan but keep the import check explicit:

```json
{
  "schema": "atr.lerobot.replicator_synthetic.summary.v1",
  "status": "ready",
  "rendered_count": 0,
  "runtime_probe": {
    "status": "pending",
    "import_checked": false,
    "required_modules": ["omni.replicator.core"],
    "reason": "Runtime path is configured, but Replicator import is deferred to the Isaac Sim worker."
  },
  "checks": [
    {"id": "replicator_runtime", "status": "passed"},
    {"id": "replicator_import_probe", "status": "pending", "required_modules": ["omni.replicator.core"]}
  ]
}
```

If `pipeline_mode=legacy_sidecar` or fallback is allowed, call legacy only through explicit fallback path.

**Future real implementation CLI:**

```bash
./python.sh scripts/lerobot_isaac_replicator_synthetic.py \
  --canonical-index <.../canonical_episode_index/manifest.jsonl> \
  --stage-url <stage.usd> \
  --output-dir <.../replicator> \
  --cameras top,front,right \
  --variants 8 \
  --rgb-strength 1.0 \
  --depth-strength 1.0 \
  --render-strength 1.0 \
  --camera-pose-strength 1.0
```

**Acceptance criteria:**

- First pass returns blocked summary if runtime missing.
- Path-only Replicator readiness records `runtime_probe.status=pending`; the GUI must not present it as a completed import probe.
- No silent fallback unless fallback policy allows it.
- Summary is written to `replicator/summary.json`.

### Work Package 11: HDF5 Export Wrapper

**Files to create/edit:**

- `scripts/lerobot_isaac_lab_hdf5_export.py`
- `device_bridges/lerobot_bridge.py`
- `tests/unit/test_lerobot_isaac_lab_hdf5_export.py`

**First-pass function:**

```python
def export_canonical_to_isaac_lab_hdf5(
    *,
    dataset_path: Path,
    canonical_manifest_path: Path,
    output_path: Path,
    success_only: bool = True,
) -> dict[str, Any]:
    ...
```

**First-pass acceptable output:**

If full LeRobot action parsing is not ready, write `export_summary.json` with:

- `ok=false`
- `status=blocked`
- `blocker=HDF5_EXPORT_ACTION_PARSER_NOT_READY`
- canonical manifest path
- required next parser fields

Do not write a fake `.hdf5` that looks usable.

**Acceptance criteria:**

- Export endpoint returns structured blocked status instead of crashing.
- When later implemented, HDF5 export must include frame/action ordering tests.

### Work Package 12: Mimic Job Manager

**Files to create/edit:**

- `device_bridges/lerobot_bridge.py`
- possibly `scripts/lerobot_isaac_lab_mimic_runner.py`
- `tests/unit/test_lerobot_bridge.py`

**State fields:**

```python
self._isaac_lab_mimic_jobs: dict[str, dict[str, Any]] = {}
self._isaac_lab_mimic_threads: dict[str, threading.Thread] = {}
self._isaac_lab_mimic_lock = threading.Lock()
```

**Job id:**

```text
isaac_lab_mimic_<timestamp>_<short_uuid>
```

**Start behavior:**

- validate request
- verify HDF5 export exists
- if missing, return blocked unless export is enabled and can be run first
- create job record
- spawn thread only for real long work
- first pass may complete immediately with `blocked=MIMIC_ENV_NOT_READY`

**Status response:**

```json
{
  "ok": true,
  "tool": "lerobot.isaac_lab.mimic.status",
  "status": "BLOCKED|RUNNING|COMPLETED|FAILED|STOPPED",
  "job_id": "...",
  "progress": {},
  "summary": {},
  "error": null
}
```

**Acceptance criteria:**

- Start/status/stop endpoints are stable.
- Missing Isaac Lab Mimic environment returns blocked, not 500.
- Job state is visible in GUI.

### Work Package 13: Training Import and Environment Overrides

**Files to edit:**

- `device_bridges/lerobot_bridge.py`
- training adapter files if present
- `tests/unit/test_lerobot_bridge.py`

**Add reader:**

```python
def _read_latest_isaac_lab_synthetic_summary(self, dataset_path: Path) -> dict[str, Any]:
    summary_path = dataset_path / "sidecar" / "isaac_lab_synthetic" / "latest" / "summary.json"
    ...
```

**Add env overrides:**

```python
def _isaac_lab_synthetic_train_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
    dataset_path = Path(self._dataset_path_for(request)).expanduser()
    summary = self._read_latest_isaac_lab_synthetic_summary(dataset_path)
    import_manifest = summary.get("training_import", {}).get("manifest_path")
    if not import_manifest:
        return {}
    return {
        "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_ENABLED": "1",
        "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_MANIFEST": str(import_manifest),
        "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_SUMMARY": str(summary.get("summary_path") or ""),
    }
```

Call this from `_workflow_env_overrides` for training, after existing Isaac RGB-D and legacy augmentation env overrides.

**Dataset mix updates:**

- Add `isaac_lab_synthetic` to dataset mix summary.
- Add `ATR_LEROBOT_DATA_MIX_ISAAC_LAB_SYNTHETIC_WEIGHT`.
- Add `ATR_LEROBOT_DATA_MIX_ISAAC_LAB_SYNTHETIC_MAX_SAMPLES`.
- Add fidelity weight for `isaac_lab_synthetic`.

**Acceptance criteria:**

- Train status reports Isaac Lab synthetic summary when present.
- Missing synthetic summary does not alter existing training.
- Existing ACT/Pi0.5/SmolVLA/XVLA behavior remains compatible.

### Work Package 14: Preview and Visualization

**Files to edit:**

- `device_bridges/lerobot_bridge.py`
- `web/static/lerobot.js`
- `tests/unit/test_lerobot_bridge.py`

**Preview endpoint behavior:**

`isaac_lab_preview` should read:

- `summary.json`
- `canonical_episode_index/manifest.jsonl`
- `replicator/manifest.jsonl`
- `mimic/successes.jsonl`
- `mimic/failures.jsonl`
- `training_import/manifest.jsonl`

Return at most `isaac_data_augmentation_preview_count` rows unless specific filter fields are added later.

**Preview row shape:**

```json
{
  "row_id": "...",
  "source_type": "replicator_render_only",
  "episode_index": 0,
  "frame_index": 10,
  "camera": "top",
  "train_eligible": true,
  "qa": {},
  "media": {
    "real_rgb": {},
    "raw_depth_preview": {},
    "isaac_rgbd": {},
    "replicator_rgb": {},
    "replicator_depth_preview": {}
  },
  "trajectory": {
    "available": false,
    "source": ""
  }
}
```

Use existing `_serve_file_ref` or equivalent file URL helper so images can render in the GUI.

**Acceptance criteria:**

- Preview works when only summary exists.
- Preview works when canonical index exists but Replicator/Mimic do not.
- Preview rows clearly show source type and train eligibility.

### Work Package 15: Tests to Add Before Implementation Is Considered Usable

**Static GUI tests:**

- Section title is `Isaac Lab Synthetic Intelligence`.
- New input IDs exist.
- New button IDs exist.
- JS sends `/api/lerobot/isaac-lab/prepare`.
- JS sends `/api/lerobot/isaac-lab/build-synthetic`.
- JS sends `/api/lerobot/isaac-lab/preview`.
- Legacy endpoint still exists but is tied to legacy button.

**Bridge unit tests:**

- `isaac_lab_prepare` writes summary and compatibility JSON.
- Missing Isaac Lab with `block_on_primary_failure` returns blocked and does not call legacy.
- Missing Isaac Lab with `allow_legacy_fallback` calls legacy wrapper and marks `fallback_used=true`.
- `legacy_sidecar` mode marks source type as `legacy_sidecar`.
- Canonical index builder handles missing sidecars.
- Source labels include all required source types.
- Training env overrides include Isaac Lab synthetic manifest only when train import exists.

**Integration tests:**

- New API endpoints validate request model.
- Mocked bridge methods return through FastAPI.
- GUI API preserves new synthetic fields.

**Regression tests:**

- Existing `/api/lerobot/augment/isaac` still works.
- Existing augmentation preview still works.
- Existing train start does not require Isaac Lab synthetic summary.
- Existing dataset visualization still works.

### Work Package 16: Definition of Done for First Slice

The first slice is complete only when all of these are true:

- Section `7` is renamed and shows the new pipeline controls.
- `Build Synthetic Dataset` calls `/api/lerobot/isaac-lab/build-synthetic`.
- `Check Digital Twin` calls `/api/lerobot/isaac-lab/prepare`.
- Backend writes `sidecar/isaac_lab_synthetic/latest/summary.json`.
- Backend writes `compatibility.json`, `digital_twin_preflight.json`, and `source_labels.json`.
- Backend either writes `canonical_episode_index/manifest.jsonl` or returns a structured blocker explaining why it cannot.
- Legacy builder is no longer the default path.
- If legacy fallback runs, the response and summary both say `fallback_used=true`.
- Training remains unaffected unless `training_import/manifest.jsonl` exists.
- Unit/static/integration tests cover the new API and GUI wiring.

**Why this is different from current augmentation:**
- Current augmentation keeps the original action sequence and changes observations or render metadata.
- Isaac Lab Mimic and RL teacher rollouts create new action sequences for the changed object pose.
- Current augmentation is good for perception robustness.
- Isaac Lab domain randomization plus generated trajectories is good for behavior coverage across pick positions, object orientations, materials, cameras, and contact conditions.

**Non-goals for this phase:**
- Do not replace real teleoperation data.
- Do not train a pure Isaac Lab RL policy for direct real-robot deployment.
- Do not include failed generated episodes by default.
- Do not run synthetic generation during live teleop or live recording; keep it as an offline branch after recording.

**Tasks:**
- [x] Add an Isaac Lab version manager that reports local tag/commit, selected Isaac Sim version, Python path, and compatibility status.
- [x] Add an Isaac Sim docs/runtime detector that records Isaac Sim version, selected docs version, Replicator availability, physics backend, and sensor extension availability.
- [x] Add an upgrade task that can pin or update Isaac Lab to the selected stack and record the result in a manifest. Default target should be chosen from Isaac Lab compatibility plus Isaac Sim official docs, not from GitHub notes alone. Candidate stacks are stable `v2.3.X` with Isaac Sim `5.1` or local beta `v3.0.0-beta2` with Isaac Sim `6.0`, pending local runtime compatibility.
- [x] Add a smoke check for Isaac Lab import, task registry, `record_demos.py`, `generate_dataset.py`, robomimic train import, and one RL train wrapper.
- [x] Add an Isaac Sim smoke check for Replicator RGB/depth render product creation, annotator writer output, scene-based randomization, and physics/collider debug availability.
- [x] Add a digital-twin stage preflight that validates robot joint zero pose, LeRobot joint-name mapping, camera prims, active robot-cam pose, stage units, D405 mount mass, cube/table/gripper physics materials, and optional RTSP stream health.
- [x] Add a teleop/replay boundary check that labels each synthetic source as `real_lerobot`, `isaac_rgbd_render`, `isaac_teleop_replay_render`, `isaac_lab_mimic`, or `isaac_lab_rl_teacher` so replay-rendered data cannot be mistaken for physics-validated rollout data.
- [x] Add `sidecar/canonical_episode_index/latest` with one row per aligned frame and explicit missing-source markers.
- [x] Derive grasp event labels from mirror `grasp_diagnostics`: `not_near_object`, `near_closed_without_contact`, `grasp_candidate`, `lifted`, `released`.
- [x] Add LeRobot/sidecar to Isaac Lab HDF5 export for successful episodes.
- [x] Add an OMX Isaac Lab environment wrapper with object poses, action-to-target pose conversion, target-pose-to-action conversion, gripper action extraction, subtask termination signals, reset events, and reward terms.
- [x] Migrate domain randomization controls from sidecar metadata into Isaac Lab env reset/event configs.
- [x] Migrate RGB-D rendering and post-render image/depth augmentation into Isaac Sim Replicator writers/annotators where possible.
- [x] Add a physics preflight validator based on Isaac Sim docs for collider type, contact offsets, friction/restitution materials, self-collision filtered pairs, and SDF/custom-geometry limitations.
- [x] Add an articulation-drive preflight based on Isaac Sim robot setup docs for initial target position, command mode exclusivity, max force/torque, max velocity, stiffness, damping, mimic direction/gear, and solver settings.
- [x] Add dry-run runtime smoke launch artifacts for Isaac contact and DOF checks under `sidecar/isaac_lab_synthetic/latest/runtime_smoke/`, referenced by Mimic and RL smoke summaries.
- [x] Add manifest-backed dry-run Mimic/RL trajectory generation outputs (`candidates.jsonl`, `successes.jsonl`, `failures.jsonl`) so success-filtered generated rows can flow into the LeRobot training import path.
- [x] Add optional Isaac Sim RTSP stream registration for digital-twin cameras with unique port allocation, first-frame/startup diagnostics, and SEI/frame metadata capture.
- [x] Add Mimic generation runner with A4-bounded cube pose randomization and success filtering.
- [x] Add RL teacher/evaluator runner with conservative state observations and explicit success metrics.
- [x] Add GUI/API `run-mimic` and `run-rl-teacher` runner endpoints that separate generation execution from smoke readiness checks while preserving dry-run deterministic outputs.
- [x] Add live Isaac Lab Mimic/RL subprocess runner contract with live-control session guards, command manifests, file-backed `RUNNING` jobs, stop handling, and process-poll completion updates.
- [x] Add file-backed Mimic/RL runner job manifests so GUI status/stop can recover latest runner state after a bridge process restart.
- [x] Add HDF5/import adapter that exposes generated trajectories as a separate LeRobot training source.
- [x] Add GUI controls and dataset health metrics for Isaac Lab synthetic trajectory count, success count, failure count, Lab version, Sim version, source type, and effective training samples.
- [x] Add GUI/status synthetic trajectory metrics for Mimic/RL candidate count, success count, failure count, training row count, and effective training samples.
- [x] Add tests for action-label mismatch protection: object pose jitter beyond the current sidecar-only bound must require an Isaac Lab generated trajectory source.

---

## Documentation Traceability Matrix

This section is the implementation map from official documentation to code behavior. Every item below should either become a validator, a manifest field, or a runtime guard. The purpose is to prevent "it worked in one GUI run" from becoming an untraceable training data source.

### Isaac Lab Runtime and Compatibility Docs

**Official docs:**
- Isaac Lab installation and Isaac Sim compatibility.
- Isaac Lab release notes.
- Isaac Lab `v3.0.0-beta2` / Isaac Sim `6.0` beta announcement.

**Implementation owner:**
- New helper: `device_bridges/isaac_lab_runtime.py`.
- New script: `scripts/lerobot_isaac_lab_validate.py`.
- GUI entry: section `7` -> `Check Digital Twin`.
- API entry: `POST /api/lerobot/isaac-lab/validate`.

**Required manifest fields:**
- `isaac_lab_path`
- `isaac_lab_git_commit`
- `isaac_lab_git_tag`
- `isaac_lab_version_family`
- `isaac_sim_version`
- `isaac_sim_python`
- `isaac_sim_docs_version`
- `compatibility_stack`
- `compatibility_status`
- `compatibility_reason`

**Validator checks:**
- `validate_isaac_lab_import` imports Isaac Lab from the selected Python runtime.
- `validate_isaac_lab_git_state` records tag/commit and refuses unknown dirty runtime only when `require_pinned_runtime=true`.
- `validate_isaac_sim_version` records Isaac Sim version from the runtime, not from a hard-coded config.
- `validate_lab_sim_compatibility` accepts only explicit stack decisions:
  - `stable_lab_2_3_sim_5_1`
  - `beta_lab_3_0_sim_6_0`
  - `manual_override_recorded`
- `validate_docs_runtime_version` records when the selected docs version differs from the runtime version and marks it as `warning` unless the mismatch affects a required extension.

**Blocking failures:**
- `COMPAT_LAB_MISSING`
- `COMPAT_SIM_MISSING`
- `COMPAT_SIM_VERSION_UNSUPPORTED`
- `DOCS_RUNTIME_VERSION_MISMATCH_BLOCKING`
- `PYTHON_RUNTIME_MISMATCH`

### Isaac Lab Teleop, Imitation, Mimic, and Robomimic Docs

**Official docs:**
- Imitation learning, teleop demonstrations, HDF5, Mimic, robomimic.
- Isaac Lab Mimic environment APIs.
- Augmented imitation / visual augmentation.

**Implementation owner:**
- New helper: `device_bridges/isaac_lab_dataset_export.py`.
- New helper: `device_bridges/isaac_lab_mimic_jobs.py`.
- New script: `scripts/lerobot_isaac_lab_export_hdf5.py`.
- New script: `scripts/lerobot_isaac_lab_mimic.py`.

**Required manifest fields:**
- `hdf5_path`
- `hdf5_schema`
- `episode_count`
- `frame_count`
- `action_key`
- `observation_keys`
- `subtask_labels`
- `mimic_trials`
- `mimic_success_count`
- `mimic_failure_count`
- `robomimic_train_ready`

**Validator checks:**
- `validate_hdf5_episode_order` verifies episode/frame/action order matches the canonical index.
- `validate_hdf5_observation_keys` verifies real RGB, raw depth, Isaac RGB-D, robot state, and gripper state keys are present or explicitly marked missing.
- `validate_mimic_subtasks` verifies approach, grasp, lift, place, and release boundaries exist before Mimic generation starts.
- `validate_mimic_success_filter` prevents failed generated trajectories from being exposed to training unless `source_intent=debug_include_failed`.
- `validate_visual_aug_boundary` verifies image/depth-only augmentation does not claim to contain newly generated actions.

**Blocking failures:**
- `HDF5_EXPORT_MISSING`
- `HDF5_SCHEMA_INVALID`
- `MIMIC_SUBTASKS_MISSING`
- `MIMIC_NO_SUCCESSFUL_TRAJECTORIES`
- `VISUAL_AUG_ACTION_MISMATCH`

### Isaac Lab RL and Manager/Event Docs

**Official docs:**
- Reinforcement learning scripts and supported libraries.
- Manager-based RL environment tutorial.
- Manager and event APIs, including `EventTermCfg`.

**Implementation owner:**
- New helper: `device_bridges/isaac_lab_rl_jobs.py`.
- New config directory: `configs/isaac_lab/robotis_omx_pick_place/`.
- New smoke script: `scripts/lerobot_isaac_lab_rl_smoke.py`.

**Required manifest fields:**
- `rl_backend`
- `rl_task_name`
- `rl_num_envs`
- `rl_seed`
- `rl_reward_terms`
- `rl_observation_terms`
- `event_randomization_terms`
- `teacher_policy_path`
- `teacher_eval_success_rate`

**Validator checks:**
- `validate_manager_env_config` verifies the configured task imports and registers.
- `validate_event_randomization_bounds` verifies cube XY/yaw, camera pose, lighting, mass, friction, and material randomization are bounded by A4/workcell limits.
- `validate_rl_teacher_scope` verifies RL teacher output is simulation-only and cannot be selected as a direct real-robot runtime policy.
- `validate_rl_smoke_episode` runs a short simulation-only rollout and records reset, step, reward, done, and success metrics.

**Blocking failures:**
- `RL_TASK_IMPORT_FAILED`
- `RL_RANDOMIZATION_OUT_OF_BOUNDS`
- `RL_TEACHER_SCOPE_UNSAFE`
- `RL_SMOKE_FAILED`

### Isaac Sim Replicator, Scene SDG, and Augmentation Docs

**Official docs:**
- Isaac Sim Replicator overview.
- Isaac Sim scene-based SDG and randomization.
- Isaac Sim data augmentation for RGB/depth annotators and writers.
- Isaac Sim teleoperation SDG.

**Implementation owner:**
- New helper: `device_bridges/isaac_replicator_jobs.py`.
- New script: `scripts/lerobot_isaac_replicator_build.py`.
- Legacy bridge: `scripts/lerobot_isaac_data_augmentation.py` remains fallback only.

**Required manifest fields:**
- `replicator_available`
- `writer_type`
- `annotators`
- `render_products`
- `camera_names`
- `rgb_output_count`
- `depth_output_count`
- `segmentation_output_count`
- `augmentation_kernels`
- `teleop_sdg_replay_used`
- `teleop_sdg_replay_boundary`

**Validator checks:**
- `validate_replicator_import` verifies Replicator imports inside the Isaac Sim Python runtime. When the non-actuating bridge only creates a worker plan, this check must be represented as a pending `replicator_import_probe`, not as an already completed import.
- `validate_render_products` verifies `top`, `front`, and `right` cameras have render products at the requested resolution.
- `validate_rgb_depth_pairs` verifies RGB and depth files are one-to-one and frame-index aligned.
- `validate_depth_units_replicator` records whether depth is meters, millimeters, or normalized and writes a conversion rule.
- `validate_teleop_sdg_boundary` marks Teleop SDG replay rows as `render_only` because pose replay does not re-run grasp physics.
- `validate_legacy_fallback_reason` requires a written reason before the old sidecar builder can run.

**Blocking failures:**
- `REPLICATOR_UNAVAILABLE`
- `RENDER_PRODUCT_MISSING`
- `RGB_DEPTH_PAIR_MISMATCH`
- `DEPTH_UNITS_UNKNOWN`
- `TELEOP_REPLAY_RENDER_ONLY`
- `LEGACY_FALLBACK_NOT_ALLOWED`

### Isaac Sim Digital Twin and Camera Streaming Docs

**Official docs:**
- Isaac Sim Digital Twin overview.
- Isaac Sim Digital Twin live camera streaming over RTSP.
- Isaac Sim Digital Twin mapping.
- Isaac Sim Digital Twin troubleshooting.

**Implementation owner:**
- Existing mirror: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`.
- New helper: `device_bridges/isaac_digital_twin_preflight.py`.
- New optional helper: `device_bridges/isaac_rtsp_streams.py`.

**Required manifest fields:**
- `stage_path`
- `stage_units_meters_per_unit`
- `robot_root_prim`
- `workspace_root_prim`
- `cube_prim`
- `camera_prims`
- `camera_intrinsics`
- `camera_extrinsics_base_frame`
- `rtsp_streams`
- `stage_snapshot_path`
- `active_robot_cam_pose`
- `raw_depth_source`

**Validator checks:**
- `validate_stage_loads` opens the configured USD and verifies required prims exist.
- `validate_stage_units` blocks if stage units are not known or not convertible to meters.
- `validate_camera_pose_contract` verifies camera pose is expressed in robot-base frame and records whether it is real D405, D455 fallback, Isaac render, or RTSP.
- `validate_rtsp_streams` verifies optional RTSP streams have unique ports, first-frame metadata, and lifecycle status.
- `validate_stage_snapshot_written` verifies every generation run can emit a stage snapshot for debugging.

**Blocking failures:**
- `DIGITAL_TWIN_STAGE_MISSING`
- `DIGITAL_TWIN_PRIM_MISSING`
- `DIGITAL_TWIN_UNITS_UNKNOWN`
- `DIGITAL_TWIN_CAMERA_MISSING`
- `RTSP_PORT_COLLISION`
- `STAGE_SNAPSHOT_MISSING`

### Isaac Sim Camera, Depth Sensor, and Structured Light Docs

**Official docs:**
- Isaac Sim camera and depth sensors.
- Isaac Sim structured light cameras.

**Implementation owner:**
- Existing raw-depth bridge and GUI defaults.
- New helper: `device_bridges/depth_profile_validation.py`.
- New script mode: `scripts/lerobot_canonical_episode_index.py --validate-depth`.

**Required manifest fields:**
- `camera_model`
- `depth_encoding`
- `depth_dtype`
- `depth_units`
- `depth_scale_m_per_unit`
- `depth_min_m`
- `depth_max_m`
- `raw_depth_png_bit_depth`
- `depth_valid_pixel_ratio`
- `depth_profile_source`

**Validator checks:**
- `validate_d405_depth_profile` verifies D405 is preferred when present and D455f remains fallback.
- `validate_raw_depth_png_16bit` verifies raw depth files are 16-bit PNG when the raw-depth adapter is selected.
- `validate_depth_scale` verifies the D405 scale conversion is used everywhere depth is consumed.
- `validate_depth_range_reasonable` warns when the measured distance is outside the expected workcell distance, such as the earlier `3009 mm` symptom.
- `validate_depth_alignment_contract` records whether RGB/depth are aligned by the RealSense pipeline, Isaac render, or postprocess mapping.

**Blocking failures:**
- `DEPTH_SCALE_UNKNOWN`
- `DEPTH_NOT_16BIT`
- `DEPTH_CAMERA_UNAVAILABLE`
- `DEPTH_RANGE_IMPLAUSIBLE`
- `DEPTH_ALIGNMENT_UNKNOWN`

### Isaac Sim Physics, Materials, Colliders, and PhysX Limitations Docs

**Official docs:**
- Isaac Sim physics simulation fundamentals.
- Isaac Sim asset inspection and collider verification.
- Isaac Sim filtered collision pairs and self-collision detector.
- Isaac Sim physics / PhysX limitations.

**Implementation owner:**
- Existing mirror physics settings.
- Current static helper methods: `device_bridges/isaac_lab_synthetic.py`.
- Future runtime contact smoke helper: `device_bridges/isaac_physics_preflight.py`.
- New script: `scripts/lerobot_isaac_physics_contact_smoke.py`.

**Required manifest fields:**
- `physics_time_steps_per_second`
- `solver_position_iterations`
- `solver_velocity_iterations`
- `gpu_dynamics_enabled`
- `ccd_enabled`
- `cube_collider_type`
- `gripper_collider_type`
- `contact_offset_m`
- `rest_offset_m`
- `physics_materials`
- `filtered_collision_pairs`
- `contact_report_enabled`
- `contact_threshold_n`

**Validator checks:**
- `validate_cube_rigid_body` verifies the cube is a dynamic rigid body with a collider and mass.
- `validate_gripper_collision_geometry` verifies fingertip contact colliders match the intended inner-pad contact area and are not oversized planes.
- `validate_collision_skin` verifies contact offset and rest offset are proportional to object size and do not prevent closing before visual contact.
- `validate_material_assignment` verifies cube, A4/paper, table, and gripper inner pads have separate physics materials.
- `validate_filtered_pairs` verifies only nonessential self-collision pairs are filtered and finger-to-object contact is never filtered.
- `validate_contact_reporting` verifies both fingers can produce contact reports against the cube.
- `validate_physx_limitations` blocks SDF/custom-geometry paths when the selected backend/version cannot support the configured collider workflow.

**Blocking failures:**
- `CUBE_RIGID_BODY_MISSING`
- `COLLIDER_PRECHECK_FAILED`
- `PHYSICS_MATERIAL_MISSING`
- `CONTACT_REPORT_MISSING`
- `FILTERED_PAIR_UNSAFE`
- `SDF_UNSUPPORTED_FOR_BACKEND`

### Isaac Sim Robot Setup, Articulation Controller, and Joint Drive Docs

**Official docs:**
- Isaac Sim robot setup troubleshooting.
- Isaac Sim manipulator configuration / articulation settings.
- Isaac Sim articulation controller.
- Isaac Sim joint drive tuning.
- Isaac Sim joint gains tuning.

**Implementation owner:**
- Existing mirror: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`.
- Current static helper methods: `device_bridges/isaac_lab_synthetic.py`.
- Future runtime DOF helper: `device_bridges/isaac_articulation_preflight.py`.
- New runtime diagnostic output: `sidecar/isaac_lab_synthetic/latest/articulation_preflight.json`.

**Required manifest fields:**
- `joint_names`
- `lerobot_joint_source`
- `leader_joint_source`
- `follower_joint_source`
- `joint_zero_pose_policy`
- `drive_targets_initialized_from_current_pose`
- `drive_mode_per_joint`
- `stiffness_per_joint`
- `damping_per_joint`
- `max_force_per_joint`
- `max_velocity_per_joint`
- `mimic_joints`
- `mimic_gear_ratio`
- `mimic_direction`

**Validator checks:**
- `validate_joint_name_mapping` verifies LeRobot action keys map to Isaac DOF names exactly once.
- `validate_joint_zero_policy` verifies USD joint zero is a reference frame, not a command that overwrites the live teleop pose.
- `validate_initial_drive_targets` verifies drive targets are initialized from current joint positions before timeline start to avoid first-frame jumps.
- `validate_command_mode_exclusivity` verifies no joint receives position, velocity, and direct teleport commands at the same time.
- `validate_drive_gain_bounds` warns on overly stiff joints and blocks extreme gains that previously caused shaking.
- `validate_mimic_gripper_mapping` verifies gripper mimic direction and gear are consistent with actual finger closure.
- `validate_leader_vs_follower_source` records whether Isaac mirror uses leader, follower, or fused joint source and blocks unknown source mixing.

**Blocking failures:**
- `JOINT_MAP_MISSING`
- `JOINT_ZERO_USED_AS_COMMAND`
- `DRIVE_TARGET_JUMP_RISK`
- `COMMAND_MODE_CONFLICT`
- `DRIVE_GAIN_UNSTABLE`
- `MIMIC_MAPPING_INVALID`
- `JOINT_SOURCE_UNKNOWN`

---

## Programmatic Validation Routines

The validation layer must be callable from GUI, CLI, tests, and future background jobs. It should not depend on screenshots or manual inspection except where a manual live test is explicitly requested.

### Umbrella CLI

Create one umbrella CLI:

```bash
python scripts/lerobot_isaac_lab_validate.py \
  --dataset /path/to/lerobot_dataset \
  --stage /path/to/robotis_omx_scene.usd \
  --output sidecar/isaac_lab_synthetic/latest/validation_report.json \
  --checks all \
  --fail-on blocker
```

The CLI should support these check groups:

- `runtime`: Isaac Lab, Isaac Sim, Python, docs/runtime compatibility.
- `digital_twin`: USD stage, prims, units, cameras, RTSP, stage snapshot.
- `depth`: D405/D455f source, raw 16-bit depth, units, scale, alignment.
- `canonical_index`: frame/action/sidecar alignment.
- `physics`: cube/gripper rigid bodies, colliders, materials, contacts, solver.
- `articulation`: joint mapping, zero-pose policy, drive targets, mimic mapping.
- `replicator`: render products, RGB/depth pairing, writers, annotators.
- `hdf5`: Isaac Lab/robomimic export schema.
- `mimic`: subtask labels, generated trajectories, success filtering.
- `training`: source labels, fidelity weights, effective sample count.
- `legacy`: explicit fallback reason and legacy-source isolation.
- `all`: every group above.

### Standard Validation Response Schema

Every validation entry point should return this shape:

```json
{
  "schema": "atr.lerobot.isaac_lab.validation.v1",
  "ok": false,
  "status": "blocked",
  "stage": "digital_twin",
  "dataset": "/abs/path/to/dataset",
  "generated_at": "2026-07-01T12:00:00+09:00",
  "checks": [
    {
      "id": "validate_stage_loads",
      "group": "digital_twin",
      "status": "blocked",
      "severity": "blocker",
      "message": "Configured stage path does not exist.",
      "evidence": {
        "stage_path": "/abs/path/to/robotis_omx_scene.usd"
      },
      "docs": [
        "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/digital_twin/index.html"
      ],
      "artifacts": {}
    }
  ],
  "blockers": [
    {
      "code": "DIGITAL_TWIN_STAGE_MISSING",
      "check": "validate_stage_loads",
      "message": "Configured stage path does not exist."
    }
  ],
  "warnings": [],
  "artifacts": {
    "compatibility": "sidecar/isaac_lab_synthetic/latest/compatibility.json",
    "digital_twin_preflight": "sidecar/isaac_lab_synthetic/latest/digital_twin_preflight.json"
  }
}
```

`status` may be:

- `passed`
- `warning`
- `blocked`
- `skipped`

`severity` may be:

- `info`
- `warning`
- `blocker`

The GUI should show `blocked` first, then `warning`, then `passed`. The training pipeline should read the same JSON and refuse to include synthetic rows when a required validation group is blocked.

### API Entry Points

Add:

```text
POST /api/lerobot/isaac-lab/validate
POST /api/lerobot/isaac-lab/prepare
POST /api/lerobot/isaac-lab/build-synthetic
POST /api/lerobot/isaac-lab/preview
POST /api/lerobot/isaac-lab/export-hdf5
GET  /api/lerobot/isaac-lab/status
```

`/validate` runs only validators and writes no synthetic samples.

`/prepare` runs `runtime`, `digital_twin`, `depth`, `physics`, and `articulation`, then writes:

```text
sidecar/isaac_lab_synthetic/latest/compatibility.json
sidecar/isaac_lab_synthetic/latest/digital_twin_preflight.json
sidecar/isaac_lab_synthetic/latest/depth_preflight.json
sidecar/isaac_lab_synthetic/latest/physics_preflight.json
sidecar/isaac_lab_synthetic/latest/articulation_preflight.json
sidecar/isaac_lab_synthetic/latest/validation_report.json
```

`/build-synthetic` must internally call `/validate` or the same validation service before it writes any training-importable data.

`/status` returns the latest run manifest and validation report without starting Isaac Sim or Isaac Lab.

### Validation Execution Points

Run validators at these points:

1. GUI page load:
   - lightweight `status` only.
   - no Isaac Sim launch.
   - no robot motion.
2. `Check Digital Twin` button:
   - `runtime`, `digital_twin`, `depth`, `physics`, `articulation`.
   - blocks synthetic generation if required fields are missing.
3. `Build Synthetic Dataset` button:
   - full preflight.
   - canonical index validation.
   - Replicator validation before capture.
   - HDF5/Mimic validation before training import.
4. Recording completion:
   - canonical index and depth validation for the new recording.
   - no RGB render required during live recording.
5. RGB render after recording:
   - Replicator/render-product validation.
   - RGB/depth pair validation.
6. Training start:
   - source labels.
   - fidelity weights.
   - effective sample count.
   - blocked synthetic source exclusion.
7. Visualization open:
   - dataset manifest existence.
   - requested episode/index range.
   - media path existence.
8. CI/unit tests:
   - pure Python validation with mocked Isaac runtimes.
   - no hardware requirement.

### Blocking Code Catalog

Use stable blocker codes so GUI, logs, tests, and docs agree.

| Code | Group | Meaning | Default action |
|---|---|---|---|
| `REQ_INVALID_DATASET` | request | Dataset path or required dataset metadata is invalid. | Block. |
| `PATH_OUTSIDE_ALLOWED_ROOTS` | request | Requested path escapes allowed roots. | Block. |
| `COMPAT_LAB_MISSING` | runtime | Isaac Lab cannot be found or imported. | Block primary path. |
| `COMPAT_SIM_MISSING` | runtime | Isaac Sim runtime cannot be found. | Block primary path. |
| `COMPAT_SIM_VERSION_UNSUPPORTED` | runtime | Lab/Sim version pair is unsupported. | Block unless manual override. |
| `DOCS_RUNTIME_VERSION_MISMATCH_BLOCKING` | runtime | Docs/runtime mismatch affects a required feature. | Block. |
| `REPLICATOR_UNAVAILABLE` | replicator | Replicator cannot import or create render products. | Block Replicator path. |
| `DIGITAL_TWIN_STAGE_MISSING` | digital_twin | Stage file is missing. | Block. |
| `DIGITAL_TWIN_PRIM_MISSING` | digital_twin | Required robot/cube/camera prim is missing. | Block. |
| `DIGITAL_TWIN_CAMERA_MISSING` | digital_twin | Required `top/front/right` camera is missing. | Block render. |
| `DIGITAL_TWIN_UNITS_UNKNOWN` | digital_twin | Stage units are unknown. | Block. |
| `DEPTH_SCALE_UNKNOWN` | depth | Depth units or scale cannot be determined. | Block raw-depth training source. |
| `DEPTH_NOT_16BIT` | depth | Raw depth file is not 16-bit PNG where required. | Block raw-depth adapter. |
| `DEPTH_RANGE_IMPLAUSIBLE` | depth | Depth values are outside expected workcell range. | Warning or block by profile. |
| `CANONICAL_INDEX_EMPTY` | canonical_index | No aligned frames found. | Block. |
| `CANONICAL_INDEX_SOURCE_MISMATCH` | canonical_index | Frame/action/source alignment is inconsistent. | Block. |
| `CUBE_RIGID_BODY_MISSING` | physics | Cube is not a dynamic rigid body with collider and mass. | Block physics trajectories. |
| `COLLIDER_PRECHECK_FAILED` | physics | Collider geometry is missing, oversized, or unsafe. | Block. |
| `PHYSICS_MATERIAL_MISSING` | physics | Required cube/table/gripper material is missing. | Block or warning by mode. |
| `CONTACT_REPORT_MISSING` | physics | Required contact report cannot be collected. | Block contact-based gripper guard. |
| `FILTERED_PAIR_UNSAFE` | physics | Finger-to-object or required contact is filtered. | Block. |
| `SDF_UNSUPPORTED_FOR_BACKEND` | physics | SDF/custom collider path is unsupported in selected backend. | Block. |
| `JOINT_MAP_MISSING` | articulation | LeRobot action keys do not map to Isaac DOF names. | Block. |
| `JOINT_ZERO_USED_AS_COMMAND` | articulation | Zero pose is being applied as a command instead of reference. | Block. |
| `DRIVE_TARGET_JUMP_RISK` | articulation | Initial drive target differs from current pose at timeline start. | Block or warning by mode. |
| `COMMAND_MODE_CONFLICT` | articulation | A joint receives conflicting command modes. | Block. |
| `DRIVE_GAIN_UNSTABLE` | articulation | Drive gain, force, velocity, damping, or solver settings are outside the stable preflight envelope. | Block. |
| `MIMIC_MAPPING_INVALID` | articulation | Gripper mimic direction/gear is invalid. | Block. |
| `TELEOP_REPLAY_RENDER_ONLY` | source_label | Teleop SDG replay is being treated as physics rollout. | Block training import. |
| `HDF5_EXPORT_MISSING` | hdf5 | Expected HDF5 export is missing. | Block Mimic/robomimic path. |
| `HDF5_SCHEMA_INVALID` | hdf5 | HDF5 schema is incompatible with Isaac Lab/robomimic. | Block. |
| `MIMIC_SUBTASKS_MISSING` | mimic | Required subtask signals are missing. | Block Mimic. |
| `MIMIC_NO_SUCCESSFUL_TRAJECTORIES` | mimic | Generation produced no successful trajectories. | Block training import. |
| `TRAINING_IMPORT_EMPTY` | training | No trainable synthetic rows after filtering. | Warning or block by mode. |
| `FIDELITY_WEIGHT_INVALID` | training | Fidelity/source weights are outside allowed ranges. | Block training start. |
| `LEGACY_FALLBACK_NOT_ALLOWED` | legacy | Legacy builder would run without explicit permission. | Block. |

### Validator Implementation Contracts

**`validate_request_schema(payload)`**

Input:

```python
{
    "dataset_path": "/abs/path",
    "pipeline_mode": "isaac_lab_replicator",
    "fallback_policy": "block_on_primary_failure",
    "source_intent": "train_ready_success_only",
}
```

Output:

```python
ValidationCheck(
    id="validate_request_schema",
    group="request",
    status="passed",
    severity="info",
    message="Request schema accepted.",
    evidence={"pipeline_mode": "isaac_lab_replicator"},
)
```

Test cases:
- valid payload passes.
- missing dataset path blocks with `REQ_INVALID_DATASET`.
- relative path outside allowed roots blocks with `PATH_OUTSIDE_ALLOWED_ROOTS`.
- old GUI fields are accepted only through the compatibility mapper.

**`validate_runtime_compatibility(config)`**

Reads:
- `/home/jin/IsaacLab/.git`
- Isaac Sim Python executable from config or environment.
- imported Isaac Sim version.

Writes:
- `compatibility.json`.

Test cases:
- missing Isaac Lab blocks primary path.
- `v2.3.X` + Isaac Sim `5.1` passes stable stack.
- `v3.0.0-beta2` + Isaac Sim `6.0` passes beta stack.
- unknown pair blocks unless `manual_override_recorded=true`.

**`validate_digital_twin_stage(config)`**

Reads:
- USD stage path.
- expected prim map.
- camera map.

Writes:
- `digital_twin_preflight.json`.
- optional `stage_snapshot.usd`.

Test cases:
- missing stage blocks.
- missing cube prim blocks.
- missing `top/front/right` camera blocks render path.
- unknown stage units blocks.

**`validate_depth_pipeline(dataset)`**

Reads:
- raw 16-bit PNG sidecars.
- RealSense profile metadata.
- active robot-cam capture metadata.

Writes:
- `depth_preflight.json`.

Test cases:
- D405 raw depth with known scale passes.
- D455f fallback records fallback status.
- 8-bit depth file blocks raw-depth adapter.
- `3009 mm`-like implausible depth creates a warning or blocker depending on profile.

**`validate_canonical_episode_index(dataset)`**

Reads:
- LeRobot episodes.
- action records.
- RGB frames.
- raw depth sidecars.
- Isaac RGB-D sidecars.
- active robot-cam pose metadata.
- grasp diagnostics.

Writes:
- `canonical_episode_index/latest/manifest.jsonl`.
- `canonical_episode_index/latest/summary.json`.

Test cases:
- fully aligned dataset passes.
- missing optional Isaac RGB-D sidecar produces missing marker, not a crash.
- missing action frame blocks.
- frame count mismatch blocks when action/source alignment cannot be resolved.

**`validate_physics_preflight(stage)`**

Reads:
- cube rigid body attributes.
- gripper collider attributes.
- physics materials.
- contact report settings.
- filtered-pair rules.

Writes:
- `physics_preflight.json`.
- optional `contact_smoke.json`.
- current dry-run launch contract: `runtime_smoke/contact_smoke.json`.

Test cases:
- cube without rigid body blocks.
- gripper plane collider that extends beyond inner pad blocks.
- finger-to-object filtered pair blocks.
- contact report from both fingers to cube passes.
- unsupported SDF path blocks on unsupported backend.

**`validate_articulation_preflight(stage, joint_map)`**

Reads:
- Isaac articulation DOF names.
- LeRobot action key map.
- drive settings.
- mimic joint config.
- current pose snapshot.

Writes:
- `articulation_preflight.json`.
- current dry-run launch contract: `runtime_smoke/dof_smoke.json`.

Test cases:
- one-to-one joint mapping passes.
- USD zero pose used as command blocks.
- initial drive target jump blocks.
- gripper mimic reverse direction blocks.
- leader/follower source mixing without explicit policy blocks.

**`validate_replicator_build(run_dir)`**

Reads:
- Replicator config.
- output RGB/depth files.
- writer metadata.

Writes:
- `replicator_preflight.json`.
- `replicator_output_manifest.jsonl`.

Test cases:
- missing writer blocks.
- RGB/depth count mismatch blocks.
- missing camera render product blocks.
- Teleop SDG replay output is labeled render-only.

**`validate_hdf5_export(hdf5_path, canonical_index)`**

Reads:
- exported HDF5.
- canonical index summary.

Writes:
- `hdf5_validation.json`.

Test cases:
- episode order preserved.
- frame/action count preserved.
- missing observation key blocks.
- failed-only export blocks training import.

**`validate_training_import(summary)`**

Reads:
- `training_import/manifest.jsonl`.
- source labels.
- fidelity weights.
- dataset mix config.

Writes:
- `training_import_validation.json`.

Test cases:
- `real_original` remains weight `1.0`.
- `isaac_lab_synthetic` default weight is bounded.
- failed episodes excluded by default.
- empty training import creates `TRAINING_IMPORT_EMPTY`.

### CLI Smoke Commands

Runtime only:

```bash
python scripts/lerobot_isaac_lab_validate.py \
  --dataset "$DATASET" \
  --checks runtime \
  --fail-on blocker
```

Expected:

```text
status: passed
compatibility_stack: stable_lab_2_3_sim_5_1 or beta_lab_3_0_sim_6_0
blockers: 0
```

Digital-twin preflight:

```bash
python scripts/lerobot_isaac_lab_validate.py \
  --dataset "$DATASET" \
  --stage "$ISAAC_STAGE" \
  --checks digital_twin,physics,articulation \
  --fail-on blocker
```

Expected:

```text
stage: passed
required_prims: passed
physics: passed
articulation: passed
blockers: 0
```

Canonical index:

```bash
python scripts/lerobot_canonical_episode_index.py \
  --dataset "$DATASET" \
  --output "$DATASET/sidecar/canonical_episode_index/latest" \
  --validate
```

Expected:

```text
episodes_indexed: >= 1
aligned_frames: > 0
missing_required_sources: 0
```

Synthetic build dry run:

```bash
python scripts/lerobot_isaac_lab_synthetic.py \
  build \
  --dataset "$DATASET" \
  --stage "$ISAAC_STAGE" \
  --profile conservative \
  --max-source-frames 30 \
  --attempts-per-frame 1 \
  --dry-run
```

Expected:

```text
plan_written: true
synthetic_rows_written: 0
blockers: 0
```

Training import validation:

```bash
python scripts/lerobot_isaac_lab_validate.py \
  --dataset "$DATASET" \
  --checks training \
  --fail-on blocker
```

Expected:

```text
real_original_samples: > 0
blocked_sources: []
effective_training_samples: > 0
```

### GUI Validation Behavior

Section `7` should show three layers of validation:

1. **Preflight summary**
   - Runtime stack.
   - Stage/camera/depth status.
   - Physics/articulation status.
   - Most recent blocker.
2. **Synthetic build summary**
   - planned samples.
   - generated samples.
   - successful trajectories.
   - failed trajectories.
   - render-only rows.
   - train-ready rows.
3. **Training readiness summary**
   - source weights.
   - fidelity weights.
   - effective samples.
   - excluded sources with reasons.

The GUI must not silently switch from Isaac Lab/Replicator to the legacy sidecar script. If fallback is enabled, it must show:

```text
Fallback used: legacy_sidecar
Reason: <structured reason from validation_report.json>
Training exposure: disabled by default
```

### Test Matrix for Validators

Add these tests before implementation is considered complete:

```text
tests/test_isaac_lab_validation_request.py
tests/test_isaac_lab_runtime_compatibility.py
tests/test_isaac_digital_twin_preflight.py
tests/test_isaac_depth_profile_validation.py
tests/test_isaac_canonical_episode_index.py
tests/test_isaac_physics_preflight.py
tests/test_isaac_articulation_preflight.py
tests/test_isaac_replicator_manifest.py
tests/test_isaac_hdf5_export_validation.py
tests/test_isaac_training_import_validation.py
tests/test_lerobot_gui_isaac_lab_controls.py
```

Each test file should use fixtures under:

```text
tests/fixtures/isaac_lab_validation/
```

Minimum fixtures:

```text
valid_dataset/
missing_actions_dataset/
missing_depth_dataset/
bad_depth_scale_dataset/
valid_stage_manifest.json
missing_camera_stage_manifest.json
bad_collider_stage_manifest.json
bad_mimic_mapping_stage_manifest.json
valid_replicator_manifest.json
bad_replicator_depth_pair_manifest.json
valid_hdf5_summary.json
failed_only_mimic_summary.json
```

Mock Isaac Sim and Isaac Lab imports in unit tests. Real Isaac Sim startup belongs only in manual/live validation.

### Programmatic Definition of Ready

The synthetic pipeline is ready to run when:

- `runtime` checks pass.
- `digital_twin` checks pass.
- `depth` checks pass or raw-depth source is explicitly disabled.
- `canonical_index` has at least one aligned episode.
- `physics` checks pass for physics trajectory generation.
- `articulation` checks pass for any simulated rollout.
- `replicator` checks pass for RGB-D output.
- fallback policy is explicit.

The training pipeline is ready to include Isaac Lab synthetic rows when:

- `training_import/manifest.jsonl` exists.
- all imported rows have `source_type=isaac_lab_synthetic`.
- every imported row has `success=true`.
- every imported row has `source_label`, `fidelity_weight`, and `generation_manifest`.
- failed/debug rows are absent from training import.
- `validation_report.json` has no blockers in `runtime`, `canonical_index`, `training`.

---

## Recommended Implementation Order

1. Manifest QA gate for current sidecars.
2. Side-by-side augmentation preview.
3. Visualization health dashboard.
4. Augmentation mix ratio for training.
5. D405-specific depth noise.
6. A4-bounded pose augmentation for small sidecar-only changes.
7. Rerun port auto-selection.
8. Unified progress UX.
9. Isaac Lab and Isaac Sim docs/runtime version upgrade/compatibility gate.
10. Digital-twin stage and camera/RTSP preflight.
11. Teleop/replay source boundary labeling.
12. Canonical episode builder for aligned real/sim/action evidence.
13. Isaac Sim physics/Replicator/articulation-drive preflight validator.
14. Isaac Lab OMX PickPlace env with reset-time domain randomization.
15. Isaac Sim Replicator RGB-D writer/annotator branch.
16. Isaac Lab HDF5 export for successful LeRobot episodes.
17. Isaac Lab Mimic trajectory generation and success filtering.
18. Isaac Lab RL teacher/evaluator runner.
19. LeRobot training import/mix controls for Isaac Lab synthetic trajectories.
20. GUI rename from "Isaac Sim Data Augmentation" to "Isaac Lab Synthetic Intelligence" after the Lab branch is active.

This order is intentional: first make bad observation data visible and rejectable, then establish the Isaac Sim/Isaac Lab runtime boundary, then move high-volume synthetic generation into Lab and Replicator. Lab synthetic trajectories should not be mixed into policy training until canonical episode alignment, version compatibility, physics preflight, and success filtering are reliable.

---

## Isaac Lab and Isaac Sim Reference Links

- Local installation and Isaac Sim compatibility: https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/index.html
- Isaac Lab release notes: https://isaac-sim.github.io/IsaacLab/main/source/refs/release_notes.html
- Imitation learning, teleop demonstrations, HDF5, Mimic, robomimic: https://isaac-sim.github.io/IsaacLab/main/source/overview/imitation-learning/teleop_imitation.html
- Augmented imitation / visual augmentation: https://isaac-sim.github.io/IsaacLab/main/source/overview/imitation-learning/augmented_imitation.html
- Reinforcement learning scripts and supported libraries: https://isaac-sim.github.io/IsaacLab/main/source/overview/reinforcement-learning/rl_existing_scripts.html
- Manager-based RL environment tutorial: https://isaac-sim.github.io/IsaacLab/main/source/tutorials/03_envs/create_manager_rl_env.html
- Manager and event APIs, including `EventTermCfg`: https://isaac-sim.github.io/IsaacLab/main/source/api/lab/isaaclab.managers.html
- Isaac Lab Mimic env APIs: https://isaac-sim.github.io/IsaacLab/main/source/api/lab_mimic/isaaclab_mimic.envs.html
- Isaac Lab `v3.0.0-beta2` / Isaac Sim `6.0` beta announcement: https://github.com/isaac-sim/IsaacLab/discussions/6249
- Isaac Sim release notes: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/overview/release_notes.html
- Isaac Sim Digital Twin overview: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/digital_twin/index.html
- Isaac Sim Digital Twin live camera streaming over RTSP: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/digital_twin/rtsp_camera_streaming.html
- Isaac Sim Digital Twin mapping: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/digital_twin/ext_isaacsim_asset_generator_occupancy_map.html
- Isaac Sim Digital Twin troubleshooting: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/digital_twin/troubleshooting.html
- Isaac Sim Replicator overview: https://docs.isaacsim.omniverse.nvidia.com/5.0.0/replicator_tutorials/index.html
- Isaac Sim scene-based SDG and randomization: https://docs.isaacsim.omniverse.nvidia.com/5.1.0/replicator_tutorials/tutorial_replicator_scene_based_sdg.html
- Isaac Sim data augmentation for RGB/depth annotators and writers: https://docs.isaacsim.omniverse.nvidia.com/4.2.0/replicator_tutorials/tutorial_replicator_augmentation.html
- Isaac Sim teleoperation SDG: https://docs.isaacsim.omniverse.nvidia.com/latest/synthetic_data_generation/tutorial_replicator_teleop_sdg.html
- Isaac Sim camera and depth sensors: https://docs.isaacsim.omniverse.nvidia.com/5.1.0/assets/usd_assets_camera_depth_sensors.html
- Isaac Sim structured light cameras: https://docs.isaacsim.omniverse.nvidia.com/latest/sensors/isaacsim_sensors_camera_structured_light.html
- Isaac Sim robot setup troubleshooting: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/robot_setup/troubleshooting.html
- Isaac Sim manipulator configuration / articulation settings: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/robot_setup_tutorials/tutorial_configure_manipulator.html
- Isaac Sim articulation controller: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/robot_simulation/articulation_controller.html
- Isaac Sim joint drive tuning: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/openusd_tuning_tutorials/tutorial_05_joint_drive_tuning.html
- Isaac Sim joint gains tuning: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/openusd_tuning_tutorials/tutorial_06_joint_gains_tuning.html
- Isaac Sim physics simulation fundamentals: https://docs.isaacsim.omniverse.nvidia.com/6.0.1/physics/simulation_fundamentals.html
- Isaac Sim asset inspection and collider verification: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/openusd_tuning_tutorials/tutorial_03_inspect_asset.html
- Isaac Sim filtered collision pairs and self-collision detector: https://docs.isaacsim.omniverse.nvidia.com/6.0.0/openusd_tuning_tutorials/tutorial_04_collider_pairs.html
- Isaac Sim physics / PhysX limitations: https://docs.isaacsim.omniverse.nvidia.com/5.1.0/physics/physics_resources.html

---

## Verification Plan

The verification plan has two layers:

1. Pure programmatic validation that can run without Isaac Sim, Isaac Lab, cameras, or the robot.
2. Live validation that proves the actual GUI, Isaac runtime, sidecars, and training commands work together.

No synthetic source should be considered train-ready until the programmatic report has no blockers for its required groups.

### Static and Unit Verification

Run:

```bash
pytest \
  tests/test_isaac_lab_validation_request.py \
  tests/test_isaac_lab_runtime_compatibility.py \
  tests/test_isaac_digital_twin_preflight.py \
  tests/test_isaac_depth_profile_validation.py \
  tests/test_isaac_canonical_episode_index.py \
  tests/test_isaac_physics_preflight.py \
  tests/test_isaac_articulation_preflight.py \
  tests/test_isaac_replicator_manifest.py \
  tests/test_isaac_hdf5_export_validation.py \
  tests/test_isaac_training_import_validation.py \
  -v
```

Expected:

```text
all selected tests pass
no network required
no Isaac Sim startup required
no hardware required
```

Must cover:

- request schema validation and old GUI field compatibility.
- allowed path checks.
- Isaac Lab/Isaac Sim compatibility parser and blocked-state behavior.
- docs/runtime version mismatch behavior.
- D405 depth scale, 16-bit PNG validation, and D455f fallback markers.
- canonical episode alignment with missing-source markers.
- A4 pose jitter bounds and trajectory-generation requirement for large object-pose changes.
- physics preflight for cube rigid body, gripper collider shape, filtered pairs, contact offsets, and materials.
- articulation preflight for joint mapping, zero-pose policy, target jump prevention, command mode exclusivity, gains, max force/torque, max velocity, and mimic gear/direction.
- Replicator writer/annotator configuration validation.
- Teleop SDG replay source label guard.
- HDF5 schema/order validation.
- success-only training import and failed/debug exclusion.
- fidelity weight range validation.
- legacy fallback isolation.

### GUI and API Verification

Run:

```bash
pytest \
  tests/test_lerobot_gui_isaac_lab_controls.py \
  tests/test_lerobot_api_isaac_lab_validate.py \
  tests/test_lerobot_api_isaac_lab_prepare.py \
  tests/test_lerobot_api_isaac_lab_build_synthetic.py \
  tests/test_lerobot_training_mix_sources.py \
  -v
```

Expected:

```text
section 7 title: Isaac Lab Synthetic Intelligence
default pipeline mode: isaac_lab_replicator
default fallback policy: block_on_primary_failure
legacy builder is not called unless explicitly selected
```

Must cover:

- section `7` exposes the new pipeline, fallback, source-intent, camera, and strength controls.
- section `7` default profile uses raw-depth adapter where applicable.
- `Check Digital Twin` calls `/api/lerobot/isaac-lab/prepare`.
- `Build Synthetic Dataset` calls `/api/lerobot/isaac-lab/build-synthetic`.
- `Preview Synthetic Sources` calls `/api/lerobot/isaac-lab/preview`.
- `Export HDF5` calls `/api/lerobot/isaac-lab/export-hdf5`.
- API response uses `atr.lerobot.isaac_lab.validation.v1`.
- blocked validation responses render blocker code, message, evidence, docs, and artifacts.
- training source mix shows `real_original`, `isaac_rgbd`, `isaac_lab_synthetic`, and `legacy_sidecar` separately.
- `isaac_lab_synthetic` is not trainable without `training_import/manifest.jsonl`.

### Programmatic CLI Verification

Runtime:

```bash
python scripts/lerobot_isaac_lab_validate.py \
  --dataset "$DATASET" \
  --checks runtime \
  --fail-on blocker
```

Expected:

```text
status: passed
blockers: 0
compatibility_stack: stable_lab_2_3_sim_5_1 or beta_lab_3_0_sim_6_0 or manual_override_recorded
```

Digital twin:

```bash
python scripts/lerobot_isaac_lab_validate.py \
  --dataset "$DATASET" \
  --stage "$ISAAC_STAGE" \
  --checks digital_twin,depth,physics,articulation \
  --fail-on blocker
```

Expected:

```text
stage_loads: passed
stage_units: passed
camera_pose_contract: passed
depth_scale: passed
cube_rigid_body: passed
gripper_collision_geometry: passed
joint_name_mapping: passed
initial_drive_targets: passed
blockers: 0
```

Canonical index:

```bash
python scripts/lerobot_canonical_episode_index.py \
  --dataset "$DATASET" \
  --output "$DATASET/sidecar/canonical_episode_index/latest" \
  --validate
```

Expected:

```text
episodes_indexed: >= 1
aligned_frames: > 0
missing_required_sources: 0
manifest: written
summary: written
```

Replicator dry run:

```bash
python scripts/lerobot_isaac_replicator_build.py \
  --dataset "$DATASET" \
  --stage "$ISAAC_STAGE" \
  --cameras top,front,right \
  --max-frames 30 \
  --dry-run
```

Expected:

```text
render_products: 3
writer_config_valid: true
rgb_depth_pairing_planned: true
synthetic_rows_written: 0
```

HDF5 export validation:

```bash
python scripts/lerobot_isaac_lab_export_hdf5.py \
  --dataset "$DATASET" \
  --canonical-index "$DATASET/sidecar/canonical_episode_index/latest/manifest.jsonl" \
  --output "$DATASET/sidecar/isaac_lab_synthetic/latest/hdf5/episodes.hdf5" \
  --validate-only
```

Expected:

```text
hdf5_schema: valid
episode_order: preserved
frame_action_alignment: preserved
```

Training import:

```bash
python scripts/lerobot_isaac_lab_validate.py \
  --dataset "$DATASET" \
  --checks training \
  --fail-on blocker
```

Expected:

```text
real_original_samples: > 0
failed_synthetic_training_rows: 0
blocked_sources: []
effective_training_samples: > 0
```

### Live GUI Validation

Use the GUI path because this is the operator path that will be used during experiments.

1. Open LeRobot GUI.
2. Confirm section `7` default is `Isaac Lab Synthetic Intelligence`.
3. Confirm `Synthetic Pipeline=isaac_lab_replicator`.
4. Confirm `Fallback policy=block_on_primary_failure`.
5. Record `5 x 10s` episodes.
6. Confirm recording completion does not start Isaac RGB-D rendering during live robot recording.
7. Confirm active robot-cam update runs once per recording/re-recording cycle when enabled.
8. Press `Check Digital Twin`.
9. Confirm GUI shows runtime, stage, camera, depth, physics, and articulation status.
10. Press `Build Synthetic Dataset`.
11. Confirm the GUI writes `sidecar/isaac_lab_synthetic/latest/summary.json`.
12. Confirm the progress bar advances smoothly and does not jump directly from low percent to complete.
13. Press `Preview Synthetic Sources`.
14. Confirm real frames, Isaac RGB-D frames, Replicator variants, and generated trajectory previews are separated by source label.
15. Press `Export HDF5`.
16. Confirm HDF5 summary reports preserved episode/action/frame ordering.
17. Start ACT smoke training from GUI.
18. Confirm training status reports effective frame count and source weights.
19. Start SmolVLA/XVLA smoke training separately if model dependencies are present.
20. Confirm `isaac_lab_synthetic` rows are included only when `training_import/manifest.jsonl` exists and success filtering passed.

Expected live artifacts:

```text
sidecar/isaac_lab_synthetic/latest/summary.json
sidecar/isaac_lab_synthetic/latest/validation_report.json
sidecar/isaac_lab_synthetic/latest/compatibility.json
sidecar/isaac_lab_synthetic/latest/digital_twin_preflight.json
sidecar/isaac_lab_synthetic/latest/depth_preflight.json
sidecar/isaac_lab_synthetic/latest/physics_preflight.json
sidecar/isaac_lab_synthetic/latest/articulation_preflight.json
sidecar/canonical_episode_index/latest/manifest.jsonl
sidecar/canonical_episode_index/latest/summary.json
sidecar/isaac_lab_synthetic/latest/training_import/manifest.jsonl
```

### Live Isaac Sim / Isaac Lab Validation

Run only after the static and API tests pass.

1. Start Isaac Sim with the OMX digital-twin stage.
2. Run `Check Digital Twin`.
3. Confirm `stage_snapshot.usd` is written.
4. Confirm `top`, `front`, and `right` cameras render frames.
5. Confirm active robot-cam raw depth uses the D405 scale and 16-bit PNG path.
6. Confirm cube contact reports are visible when gripper fingers touch the cube.
7. Confirm both fingers must report contact before a contact-based gripper guard is considered active.
8. Confirm finger-to-object collision is not filtered.
9. Confirm cube rigid body, cube collider, gripper inner-pad collider, and physics materials match the preflight report.
10. Generate a small Mimic batch with A4-bounded cube poses.
11. Confirm failed Mimic candidates remain visible in preview but are absent from training import.
12. Run a short RL teacher/evaluator smoke only in simulation.
13. Confirm RL teacher output cannot be selected as a real robot runtime policy.

Expected:

```text
Isaac runtime does not block LeRobot GUI status polling
live teleop/recording path is not modified
synthetic generation runs offline after recording
training import contains only success-filtered rows
```

### Regression Validation

Run:

```bash
pytest \
  tests/test_lerobot_existing_augmentation_endpoint.py \
  tests/test_lerobot_existing_preview_endpoint.py \
  tests/test_lerobot_existing_training_start.py \
  tests/test_lerobot_existing_dataset_visualization.py \
  -v
```

Expected:

```text
legacy /api/lerobot/augment/isaac still works when explicitly selected
existing dataset visualization still works
training start does not require Isaac Lab synthetic summary
```

Manual regressions:

1. Start normal LeRobot teleop without Isaac Sim and confirm it still starts.
2. Start Isaac Sim mirror after teleop and confirm it attaches in either order.
3. Toggle active robot-cam option, restart mirror, and confirm the new option value applies.
4. Stop/start Isaac Sim timeline and confirm active cam action runs on start only, not stop.
5. Re-record one episode and confirm active cam and canonical index update for the new episode.
6. Render Isaac RGB-D after recording and confirm GUI remains responsive.
7. Open viewer from GUI and confirm it shows the selected dataset, not a stale run folder.

### Acceptance Gate

The implementation can be marked ready only when:

- all static/unit tests pass.
- GUI/API tests pass.
- CLI validation produces `blockers: 0` for the selected dataset/stage.
- `5 x 10s` GUI recording completes.
- post-recording render completes without slowing live teleop.
- section `7` synthetic build writes validation and summary artifacts.
- training smoke starts with real data plus the selected synthetic sources.
- legacy fallback is explicit and never silent.
- the final validation report contains stable docs links for every blocked or warning check.
