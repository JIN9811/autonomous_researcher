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
- D455F/top and D405/wrist serial-role mixups should fail closed.
- CLI discovery/recording paths expose the RealSense fields ATR needs.

If the patch no longer applies, first confirm the LeRobot branch/version. Do not
silently rewrite ATR to use `/dev/video*` fallback for D405.
