"""Describe installed observation components without importing their runtimes."""
import json

from device_bridges.module_contract import BridgeModule


MODULE = BridgeModule("camera_vision", "1.0.0", json.dumps({
    "label": "Camera / Vision",
    "root": "device_bridges/camera_vision",
    "requirements": "device_bridges/camera_vision/requirements.txt",
    "registration": "device_bridges.camera_vision.tools.register_camera_tools",
    "runtime_bridge_ids": ["camera_utm_bridge"],
    "tools": [
        "camera.capture", "vision.utm_runtime.start", "vision.utm_runtime.status",
        "vision.utm_runtime.stop", "vision.utm_specimen_presence.capture",
        "vision.specimen_pose_snapshot", "vision.specimen_pose.release",
        "vision.equipment_cross_check",
    ],
    "providers": [
        {"id": "utm_runtime", "label": "UTM Runtime", "version": "1.0.0",
         "component": "device_bridges.camera_vision.utm_runtime_bridge"},
        {"id": "utm_state_observer", "label": "UTM State Observer", "version": "1.0.0",
         "component": "device_bridges.camera_vision.utm_state_observer"},
        {"id": "specimen_pose_tracker", "label": "Specimen Pose Tracker", "version": "1.0.0",
         "component": "device_bridges.camera_vision.specimen_pose_tracker"},
        {"id": "realsense", "label": "RealSense", "version": "1.0.0",
         "component": "device_bridges.camera_vision.realsense_bridge", "optional": True},
    ],
    "ui": {"workspace": "/device-bridge/vision-utm", "api": "/api/equipment/utm-runtime",
           "assets": "web/static/vision_utm_device_bridge.js"},
    "apis": ["/api/equipment/utm-runtime", "/api/vision/specimen-pose"],
    "storage": {
        "camera_config": "memory/device_bridge/utm_camera_config.json",
        "calibration": "memory/device_bridge/calibration/utm_camera_default_cam.yaml",
        "pose_artifacts": "artifacts/specimen_pose_tracker",
        "run_artifacts": "runs",
    },
    "shared_dependencies": {
        "runtime_bridge_ids": ["lerobot_bridge"],
        "bridge_sources": ["device_bridges/lerobot/bridge.py"],
        "tools": ["lerobot.camera.test", "lerobot.active_robot_cam.capture", "utm.run_protocol"],
        "apis": ["/api/lerobot/config", "/api/lerobot/camera/test"],
        "ownership": "LeRobot owns robot camera motion; Equipment owns protocol execution",
    },
    "documentation": "docs/device_bridges/utm_vision_bridge.md",
}, allow_nan=False))
