# LeRobot Isaac RGBD Attempts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add attempt-aware recording sidecars and a 15fps Isaac RGBD render request lane that can run in parallel with LeRobot recording.

**Architecture:** Recording owns the primary timing path and never waits for rendering. The LeRobot wrapper creates a per-attempt sidecar, stores active-cam/specimen metadata, and attaches a render request to each Isaac mirror joint sample. The Isaac receiver records render request manifests under the same attempt path; a later backend can replace the metadata writer with real RGB/depth annotator capture without changing dataset contracts.

**Tech Stack:** Python, LeRobot wrapper monkeypatches, Isaac mirror HTTP receiver, JSONL sidecars, pytest.

---

### Task 1: Attempt Sidecar Contract

**Files:**
- Modify: `scripts/lerobot_isaac_mirror_runtime_wrapper.py`
- Test: `tests/unit/test_lerobot_isaac_mirror_runtime_wrapper.py`

- [x] Add `RecordAttemptSidecar` that reads `ATR_RECORD_ATTEMPT_*` env vars and writes:
  - `dataset/sidecar/attempts/episode_000/<attempt_id>/status.json`
  - `dataset/sidecar/attempts/manifest.jsonl`
  - `active_cam_result.json`
  - `specimen_pose.json` when available.

- [x] Verify it does not create directories unless enabled and a dataset path exists.

### Task 2: 15fps Render Request Payload

**Files:**
- Modify: `scripts/lerobot_isaac_mirror_runtime_wrapper.py`
- Test: `tests/unit/test_lerobot_isaac_mirror_runtime_wrapper.py`

- [x] Add render request context to `IsaacMirrorPublisher`.
- [x] Attach `render_request` to every posted mirror payload when `ATR_ISAAC_RGBD_RENDER_ENABLED=1`.
- [x] Include `attempt_id`, `episode_index`, `frame_index`, `record_timestamp`, `target_fps`, `output_dir`, and requested cameras.

### Task 3: Isaac Receiver Render Manifest

**Files:**
- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`
- Test: `tests/unit/test_isaac_omx_mirror_server.py`

- [x] Add render request handling inside `IsaacMirrorState.receive/apply`.
- [x] Write one JSONL row per accepted request to `output_dir/manifest.jsonl`.
- [x] Report `last_render_request_result` in `/health` and `/state`.

### Task 4: Bridge Wiring

**Files:**
- Modify: `device_bridges/lerobot_bridge.py`
- Test: `tests/unit/test_lerobot_bridge.py`

- [x] For live record sessions with Isaac mirror enabled, inject attempt/render env:
  - `ATR_RECORD_ATTEMPT_ENABLED=1`
  - `ATR_RECORD_ATTEMPT_DATASET_PATH=<dataset>`
  - `ATR_RECORD_ATTEMPT_SESSION_ID=<record session>`
  - `ATR_RECORD_ATTEMPT_TARGET_FPS=15`
  - `ATR_ISAAC_RGBD_RENDER_ENABLED=1`
  - `ATR_ISAAC_RGBD_RENDER_TARGET_FPS=15`
- [x] Add attempt/render summary to session metadata.
- [x] Keep teleop unchanged unless explicitly configured later.

### Task 5: Training Readiness Metadata

**Files:**
- Modify: `device_bridges/lerobot_bridge.py`
- Test: `tests/unit/test_lerobot_bridge.py`

- [x] In `train_start`, read dataset attempt manifest.
- [x] Attach latest committed/available attempt summary to train session.
- [x] Do not block training yet unless no committed attempt exists; emit metadata for partial coverage.

### Task 6: Verification

**Commands:**
- `conda run --no-capture-output -n lerobot python -m pytest tests/unit/test_lerobot_isaac_mirror_runtime_wrapper.py tests/unit/test_isaac_omx_mirror_server.py tests/unit/test_lerobot_bridge.py -q`
- `.venv/bin/python -m pytest tests/integration/test_lerobot_gui_api.py -q`
- `git diff --check`
