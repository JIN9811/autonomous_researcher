# LeRobot Local Patches

This directory stores reproducible patches for the external LeRobot checkout.
The patches are not applied to this repository. They are applied to a separate
LeRobot source tree, usually `~/lerobot`, when real ROBOTIS/RealSense workflows
are needed.

## Spark RealSense D405 / RSUSB Patch

Patch file:

```text
patches/lerobot/spark_realsense_d405_rsusb.patch
```

Apply it with:

```bash
bash install/apply_lerobot_d405_patch.sh ~/lerobot
```

The patch captures the local D405/RSUSB fixes required by ATR's LeRobot bridge:

- RealSense D405 must remain an Intel RealSense SDK camera, not OpenCV fallback.
- D405 uses `color_format=bgr8`, `use_depth=true`, and warmup.
- OMX follower observations expose depth as LeRobot visual keys such as
  `observation.images.top_depth` and `observation.images.wrist_depth`, encoded
  as 8-bit 3-channel depth images for the current LeRobot video writer.
- When ATR passes `ATR_LEROBOT_RAW_DEPTH_DIR`, the OMX follower also writes
  16-bit raw RealSense Z16 depth PNG sidecars under
  `sidecar/depth_raw/<camera_key>/frame_*.png` without replacing the 8-bit
  policy-compatible video features.
- When ATR passes `ATR_LEROBOT_RAW_DEPTH_ADAPTER=1` for training, the patched
  `LeRobotDataset` reads `ATR_LEROBOT_RAW_DEPTH_SOURCE_DIR` or
  `<dataset>/sidecar/depth_raw`, loads `transform_manifest.json`, and replaces
  existing `observation.images.<camera>_depth` tensors with normalized tensors
  reconstructed from the 16-bit raw PNG frames. This makes `raw_depth_adapter`
  an actual training input path, not just a manifest/env placeholder.
- RealSense RGB-D recording uses the practical production contract:
  depth is aligned to each camera's color stream, metric scale is recorded as
  `depth_scale_m_per_unit`, and visual depth conversion uses a fixed
  millimeter clipping range. The OMX follower writes this contract to
  `sidecar/depth_raw/transform_manifest.json`.
- OMX follower connection retries Dynamixel calibration writes and torque
  disable commands. This keeps transient `There is no status packet` failures
  from aborting a live recording/rollout when the motor can still ping/read.
- D455F/top and D405/wrist serial-role mixups should fail closed.
- CLI discovery/recording paths expose the RealSense fields ATR needs.

If the patch no longer applies, first confirm the LeRobot branch/version. Do not
silently rewrite ATR to use `/dev/video*` fallback for D405.

## Optional SmolVLA Extra

SmolVLA support does not require a repository patch, but the external LeRobot
checkout must be installed with its `smolvla` extra in the `lerobot` conda
environment:

```bash
cd ~/lerobot
conda run --no-capture-output -n lerobot python -m pip install -e ".[smolvla]"
conda run --no-capture-output -n lerobot hf download lerobot/smolvla_base --max-workers 1
conda run --no-capture-output -n lerobot hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct --exclude "onnx/*" --max-workers 1
```
