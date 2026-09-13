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
