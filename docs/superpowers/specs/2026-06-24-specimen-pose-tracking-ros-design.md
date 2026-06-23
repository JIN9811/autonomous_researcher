# Specimen Pose Tracking ROS Design

Date: 2026-06-24
Status: design approved for implementation planning
Scope: VisionAgent ROS one-shot specimen pose tracking before VLA manipulation

## 1. Purpose

Before using the Isaac digital twin to augment manipulation datasets, the system needs a reliable physical specimen pose. The pose must be produced after 3DP auto-ejection and before ManipulationAgent starts VLA inference.

The target state is:

```text
3DP auto-ejection complete
-> VisionAgent borrows the D455F global camera
-> one-shot ROS specimen pose tracking
-> VisionAgent releases D455F back to the VLA route
-> ManipulationAgent receives pickup pose and starts inference
-> BRIO/UTM camera verifies placement after manipulation
```

## 2. Current Project Context

Existing relevant components:

- `agents/vision_agent.py` already emits `vision_report.v1`, `vision_signal.v1`, `pose_estimate`, `pickup_ready`, and downstream handoff fields.
- `device_bridges/utm_runtime_bridge.py` already manages a ROS-backed camera/runtime bridge, RQT-like graph evidence, frame capture, MJPEG stream, and camera config.
- `docs/hardware/utm_ros_vision_runtime_bridge.md` defines the UTM/BRIO inspection bridge and topic evidence path.
- `docs/agents/vision_pickup_observation_runtime_guideline.txt` defines VisionAgent as an observer/signal bus, not a hardware executor.
- LeRobot/VLA already uses the D455F global camera as part of the robot observation route.

Gap:

- No dedicated component converts D455F RGB-D evidence into a stable physical `specimen_pose.v1` contract.
- Current `VisionAgent.pose_estimate` can accept `x_mm/y_mm/z_mm`, but those values are not produced by a live ROS specimen pose tracker.

## 3. Design Decision

Use a new one-shot ROS node rather than modifying the existing UTM/YOLO nodes.

Recommended node:

```text
atr_specimen_pose_tracker
```

It is not a continuously running daemon. It is started only when VisionAgent needs a pose snapshot, then stopped immediately after a stable pose is produced or a timeout occurs.

Reasoning:

- The D455F is already used by the VLA route, so the camera must not be shared by ROS and VLA at the same time.
- One-shot capture minimizes camera ownership time and reduces USB/RealSense collision risk.
- UTM/BRIO inspection remains separate from A4 workspace localization.
- The VisionAgent contract stays stable even if the tracker implementation changes later.

## 4. Camera Ownership Contract

The D455F global camera is an exclusive leased device.

Valid owners:

```text
free
vla_runtime
vision_ros_tracker
```

Required handoff:

```text
VLA route owns D455F by default
-> VisionAgent requests lease
-> VLA camera route pauses/stops
-> release check confirms D455F is free
-> ROS realsense2_camera starts
-> atr_specimen_pose_tracker captures one pose snapshot
-> ROS nodes stop
-> release check confirms D455F is free
-> D455F is returned to VLA route
-> VLA camera precheck passes
-> ManipulationAgent may start inference
```

ManipulationAgent must not start VLA inference unless both are true:

```json
{
  "specimen_pose_ready": true,
  "camera_returned_to_vla": true
}
```

If port return fails, the workflow must stop at operator attention with:

```text
D455F_PORT_RETURN_FAILED
```

## 5. ROS Runtime Shape

The D455F path should start a temporary ROS stack:

```text
realsense2_camera
  -> /camera/color/image_raw
  -> /camera/aligned_depth_to_color/image_raw
  -> /camera/color/camera_info

atr_specimen_pose_tracker
  <- color image
  <- aligned depth
  <- camera info
  -> /atr/specimen_pose
  -> /atr/specimen_pose/status
  -> /atr/specimen_pose/debug_image
```

The tracker should stop after one stable snapshot. Stability can mean one accepted frame at first, then later N consecutive stable frames if needed.

Initial recommended default:

```text
snapshot_count = 1
max_runtime_sec = 8
pose_confidence_threshold = 0.75
release_timeout_sec = 5
```

## 6. Pose Estimation Method

Initial method should be robust and simple:

1. Use D455F RGB to locate the red cube/specimen or the latest printed specimen in the A4 workspace.
2. Use aligned depth to estimate 3D point and reject table/A4 background.
3. Use A4 paper and blue marker calibration to convert camera coordinates to A4 workspace coordinates.
4. Convert A4 workspace coordinates to `robot_base` and optional `isaac_world` frame through saved extrinsics.

Depth makes the first implementation easier than RGB-only tracking because the specimen can be separated by height and local depth consistency.

Longer-term backends can be added without changing the contract:

- color threshold / contour tracker for red cube smoke tests
- YOLO/segmentation for printed specimens
- ArUco/A4 marker based homography
- CAD/STL pose backend for orientation refinement

## 7. Data Contract

Primary output:

```json
{
  "schema": "specimen_pose.v1",
  "stage": "post_ejection_workspace_localization",
  "camera_id": "d455f_global",
  "camera_owner_before": "vla_runtime",
  "camera_owner_after": "vla_runtime",
  "workspace": "a4_robot_workspace",
  "specimen_id": "specimen-id",
  "frame_id": "frame-id",
  "timestamp": "2026-06-24T00:00:00Z",
  "center_px": [0, 0],
  "bbox_xyxy": [0, 0, 0, 0],
  "depth_mm": 0.0,
  "position_a4_mm": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "position_robot_base_mm": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "position_isaac_world_mm": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "orientation_deg": {
    "yaw": 0.0
  },
  "confidence": 0.0,
  "stable_frames": 1,
  "freshness_ms": 0,
  "port_released": true,
  "vla_camera_precheck_ok": true,
  "debug_image_path": "runs/.../specimen_pose_debug.png",
  "raw_pose_json_path": "runs/.../specimen_pose.json"
}
```

VisionAgent must keep legacy compatibility by mapping this to:

```text
observation.pose_estimate
observation.pickup_target
observation.transfer_readiness
vision_report.detections
vision_signal.v1 pickup_ready
```

## 8. Agent Flow

### 8.1 Post-Ejection Localization

```text
SpecimenMaking/3DP Agent
  emits auto_ejection_complete and specimen_location=a4_workspace

VisionAgent
  acquires D455F lease
  runs one-shot ROS pose tracker
  writes pose evidence
  releases D455F to VLA route
  emits specimen_pose_ready + pickup_ready

ManipulationAgent
  verifies pose freshness and VLA camera precheck
  starts policy inference
```

### 8.2 Post-Manipulation Verification

After ManipulationAgent reports movement complete:

```text
VisionAgent
  uses BRIO/UTM camera path as currently configured
  detects specimen at target zone
  emits placement_verification.v1
  tells ManipulationAgent placement is complete
  hands off to Lab Equipment Agent when ready
```

Verification output:

```json
{
  "schema": "placement_verification.v1",
  "stage": "post_manipulation_place_check",
  "camera_id": "brio_or_utm_camera",
  "target_zone": "utm_platen",
  "specimen_present": true,
  "aligned": true,
  "confidence": 0.0,
  "handoff": "lab_equipment_agent"
}
```

## 9. Error Handling

Required failure codes:

```text
D455F_LEASE_ACQUIRE_FAILED
D455F_PORT_RELEASE_FAILED
REALSENSE_ROS_START_FAILED
SPECIMEN_POSE_TIMEOUT
SPECIMEN_POSE_LOW_CONFIDENCE
SPECIMEN_POSE_STALE
VLA_CAMERA_PRECHECK_FAILED
PLACEMENT_VERIFICATION_FAILED
```

Policy:

- Test mode may fall back to a virtual pose only if physical camera evidence is unavailable, and must leave a fallback trace.
- Live mode must not start VLA inference from virtual pose evidence.
- A stale pose must block ManipulationAgent.
- A failed camera return must block ManipulationAgent.

## 10. GUI / Evidence Requirements

Device workspace should expose:

```text
D455F lease owner
lease acquire/release status
one-shot pose result
debug image
pose confidence
VLA return precheck
```

Live GUI should show concise VisionAgent messages:

```text
VisionAgent: D455F snapshot pose ready
VisionAgent: D455F returned to VLA route
ManipulationAgent: inference start allowed
```

Evidence files should be stored under the run directory:

```text
runs/<run_id>/vision/<observation_id>/specimen_pose.json
runs/<run_id>/vision/<observation_id>/specimen_pose_debug.png
runs/<run_id>/vision/<observation_id>/camera_lease.json
```

## 11. Testing Strategy

Unit tests:

- lease state transitions
- release failure blocks VLA start
- `specimen_pose.v1` validation
- mapping from `specimen_pose.v1` to VisionAgent legacy fields
- stale pose rejection

Integration tests:

- virtual one-shot pose in test mode
- ROS unavailable fallback trace in test mode
- live-mode block when D455F cannot be returned
- VisionAgent to ManipulationAgent handoff includes pose and camera return status

Browser/UI tests:

- Device workspace shows pose result and lease status
- Live GUI shows VisionAgent pose-ready message
- Debug image link renders when available

## 12. Non-Goals

This design does not implement continuous tracking.

This design does not share the D455F ROS topic with VLA.

This design does not make VisionAgent start robot motion directly.

This design does not replace BRIO/UTM placement verification.

## 13. Approval Summary

Approved direction:

- D455F is already used by the VLA route.
- VisionAgent temporarily takes the D455F away from VLA only for one ROS snapshot.
- ROS must stop and release the physical camera before VLA inference starts.
- BRIO/UTM camera remains the post-manipulation placement verification camera.
- The ejection output location is the A4 robot workspace.
