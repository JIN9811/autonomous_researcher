# Isaac Data Augmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a LeRobot GUI/API pipeline that creates Isaac Sim augmentation sidecars from recorded dataset metadata and RGB-D render outputs.

**Architecture:** Keep the original LeRobot dataset immutable. A focused Python runner reads `sidecar/attempts`, `sidecar/isaac_rgbd`, and `meta/atr_pipeline.json`, then writes `sidecar/isaac_augmentation/latest` with JSONL manifests plus optional augmented RGB/depth files. The LeRobot bridge exposes this as a dataset action and the GUI inserts it as section 7 before visualization/training.

**Tech Stack:** Python, Pillow/numpy for image sidecar transforms, FastAPI route, LeRobot bridge request models, Isaac render-request metadata, pytest.

---

### Task 1: Augmentation Runner

**Files:**
- Create: `scripts/lerobot_isaac_data_augmentation.py`
- Test: `tests/unit/test_lerobot_isaac_data_augmentation.py`

- [ ] Write tests that build a tiny dataset with an Isaac RGBD render manifest, one RGB PNG, one 16-bit depth PNG, and `meta/atr_pipeline.json`.
- [ ] Verify the runner writes `manifest.jsonl`, `summary.json`, augmented image files, common photometric/noise/depth augmentation fields, and camera-pose render metadata when source metadata exists.
- [ ] Implement deterministic variant generation with seed, `variants_per_frame`, `max_source_frames`, camera filtering, overwrite of `latest`, and safe behavior when render files are missing.

### Task 2: Bridge/API Wiring

**Files:**
- Modify: `mcp_tools/lerobot_schemas.py`
- Modify: `app/main.py`
- Modify: `device_bridges/lerobot_bridge.py`
- Test: `tests/unit/test_lerobot_bridge.py`
- Test: `tests/integration/test_lerobot_gui_api.py`

- [ ] Add request fields for Isaac augmentation output dir, variants, max frames, seed, cameras, image augmentation, and camera-pose augmentation.
- [ ] Add `/api/lerobot/augment/isaac` route and bridge method that resolves the selected dataset, runs the local runner, and returns the sidecar summary.
- [ ] Attach the latest augmentation summary to training sessions so training readiness can see whether synthetic sidecars exist.

### Task 3: GUI Section 7

**Files:**
- Modify: `web/templates/lerobot.html`
- Modify: `web/static/lerobot.js`
- Test: `tests/integration/test_lerobot_gui_api.py`

- [ ] Insert `7. Isaac Sim Data Augmentation`.
- [ ] Shift Dataset Visualization, Training, Rollout, Manipulation Agent, and Session Output section numbers back by one.
- [ ] Add controls for variants, max source frames, cameras, image augmentation, camera-pose augmentation, and output dir.
- [ ] Add a run button that calls `/api/lerobot/augment/isaac` and renders the summary.

### Task 4: Isaac Camera Spec Support

**Files:**
- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`
- Test: `tests/unit/test_isaac_omx_mirror_server.py`

- [ ] Let render requests include `camera_specs` per camera.
- [ ] Include the camera spec in the render resource cache key so different camera-pose variants do not reuse the base camera product.
- [ ] Preserve existing camera path behavior when no camera spec is supplied.

### Task 5: Verification

**Commands:**
- `.venv/bin/pytest -q tests/unit/test_lerobot_isaac_data_augmentation.py`
- `.venv/bin/pytest -q tests/unit/test_lerobot_bridge.py tests/unit/test_isaac_omx_mirror_server.py tests/integration/test_lerobot_gui_api.py`
- `git diff --check`
