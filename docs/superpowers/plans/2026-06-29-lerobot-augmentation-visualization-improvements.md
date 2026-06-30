# LeRobot Augmentation and Visualization Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the LeRobot + Isaac Sim post-recording pipeline so augmentation quality, synthetic RGB-D coverage, raw depth health, and training readiness can be verified before training.

**Current baseline verified on 2026-06-29:**
- GUI record produced `5` episodes, `750` original frames at `15 fps`.
- Raw depth sidecar existed for both `top` and `wrist` cameras.
- Isaac RGB-D sidecar was detected by training.
- Isaac augmentation sidecar was generated with `standard_sim2real_v2`, `sim2real`, `50` source frames, and `100` variants.
- ACT smoke training completed `2/2` steps with raw depth, Isaac RGB-D, and augmentation adapters enabled.
- Rerun distant visualization worked at `http://localhost:9092`.

**Problem:** The pipeline can now generate and consume augmented data, but it still lacks enough quality gates and visual inspection tools to know whether synthetic data is helping or poisoning training.

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

## Recommended Implementation Order

1. Manifest QA gate.
2. Side-by-side augmentation preview.
3. Visualization health dashboard.
4. Augmentation mix ratio for training.
5. D405-specific depth noise.
6. A4-bounded pose augmentation.
7. Rerun port auto-selection.
8. Unified progress UX.

This order is intentional: first make bad data visible and rejectable, then tune how much synthetic data enters training.

---

## Verification Plan

**Unit tests:**
- augmentation QA manifest checks
- D405 depth noise output constraints
- A4 pose jitter bounds
- training mix-ratio sampling
- visualization port fallback

**Integration tests:**
- GUI API preserves all augmentation and visualization options.
- Dataset inspect returns health summary for complete and partial datasets.
- Training status reports effective frame counts and augmentation adapter status.

**Manual live validation:**
1. Record `5 x 10s` episodes.
2. Build Isaac RGB-D sidecar after recording.
3. Build augmentation sidecar.
4. Open side-by-side preview and inspect at least 20 variants.
5. Confirm health dashboard has no blocking issue.
6. Run ACT smoke training.
7. Run SmolVLA/XVLA short smoke training separately.
