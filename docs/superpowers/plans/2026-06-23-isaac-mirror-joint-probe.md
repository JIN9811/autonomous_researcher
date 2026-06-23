# Isaac Mirror Joint Probe Implementation Plan

> For autonomous_researcher development: implement a read-only bridge between the physical ROBOTIS OMX follower and the Isaac Sim table scene without changing motion or training behavior.

## Goal

Expose a deterministic LeRobot mirror-mode contract that maps follower Dynamixel IDs 11-16 to Isaac Sim joint paths and can read the current follower joint positions safely for real-to-sim mirroring.

## Context

- Isaac scene: `sim/robotis_omx/scene/omx_table_layout.usda`
- Robot reference: `sim/robotis_omx/omx/omx.usda`
- Isaac articulation root: `/World/Robot/Geometry/link0`
- Physical follower IDs: 11-16
- Physical leader IDs: 1-6
- Existing bridge memory: `memory/lerobot_device_ports.json`

## Tasks

1. Add unit tests for mirror joint mapping and state probe.
2. Add static Isaac joint metadata and follower motor-to-joint mapping to `LeRobotBridge`.
3. Add a test-mode mirror state probe with deterministic fake positions.
4. Add a live-mode read-only probe that reuses the saved follower port and reads motor positions without launching teleop/record/rollout.
5. Verify targeted LeRobot bridge tests.

## Safety Constraints

- Do not command robot motion.
- Do not start teleoperation, recording, rollout, or training.
- Do not change existing live gate behavior.
- If live read fails, return a clear failed/blocked tool response instead of falling back silently.
