# LeRobot bridge

This installed bridge packages ATR's existing LeRobot runtime under one
`lerobot@1.0.0` identity. It owns profile and port handling, ActiveCam,
teleoperation, recording, training, policy rollout, managed replay, dataset and
policy operations, visualization, and the existing Isaac sidecars. These are
internal capabilities of one bridge, not separate packages or agent stages.

`register_lerobot_tools` constructs one `LeRobotBridge`, stores it as the
`lerobot.bridge` registry resource, and registers the existing `lerobot.*` tool
IDs. Both Manipulation and Vision declare the same bridge dependency; package
inspection only reads metadata and never creates a bridge or connects a device.

The `/lerobot` workspace and `/api/lerobot/*` routes remain hosted by the
application. Configuration remains in `configs/lerobot.yaml`; mutable device and
session state remains under `memory/`, with datasets, checkpoints, logs, and run
evidence in their existing configured artifact, output, and run roots. Schemas,
workspace assets, managed replay, background training, and Isaac helper scripts
stay at their existing repository paths and are referenced rather than copied.

Installing this source package does not install or configure robot, camera,
LeRobot CLI, Isaac, or W&B integrations. The requirements file only declares
Python dependencies; live execution still requires the existing configuration,
environment, approval, and safety gates.

## Default Isaac environment

The mirror receiver and synthetic-stage defaults load
[`omx_table_layout_20260915.usda`](../../sim/robotis_omx/scene/omx_table_layout_20260915.usda).
Explicitly selected scene paths still take precedence. This overlay retains the
original robot transform and joints, aligns the 175 mm tray midpoint with the
robot, and rotates the environment clockwise by 90 degrees. The upper platform
matches the 395 mm lower assembly width; the lower working surface remains at
Z=0 with its underside extended to the robot anchor at Z=-20 mm.
Live Robot Pose uses the matching web manifest. The original USD is retained as
the overlay's sublayer, not replaced. These geometry changes do not recalibrate
camera poses or robot control targets.
