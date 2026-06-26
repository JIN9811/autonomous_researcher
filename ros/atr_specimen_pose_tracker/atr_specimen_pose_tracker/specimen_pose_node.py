from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import cv2
    import numpy as np
    import rclpy
    from cv_bridge import CvBridge
    from rclpy.node import Node
    from sensor_msgs.msg import CameraInfo, Image
except Exception as import_error:  # pragma: no cover - exercised in unsourced ROS shells.
    cv2 = None
    np = None
    rclpy = None
    CvBridge = None
    Node = object
    CameraInfo = object
    Image = object
    _IMPORT_ERROR = import_error
else:
    _IMPORT_ERROR = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _failure(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"ok": False, "failure_code": code, "message": message, "timestamp": _now_iso()}
    payload.update(extra)
    return payload


@dataclass
class OneShotConfig:
    specimen_id: str
    camera_id: str
    workspace: str
    color_topic: str
    depth_topic: str
    info_topic: str
    output_dir: Path
    timeout_sec: float
    confidence_threshold: float
    min_contour_area_px: float
    camera_to_robot_x_mm: float
    camera_to_robot_y_mm: float
    camera_to_robot_z_mm: float


class SpecimenPoseNode(Node):
    def __init__(self, cfg: OneShotConfig) -> None:
        super().__init__("atr_specimen_pose_tracker")
        self.cfg = cfg
        self.bridge = CvBridge()
        self.color: Any | None = None
        self.depth: Any | None = None
        self.info: Any | None = None
        self.color_stamp = ""
        self.depth_stamp = ""
        self.create_subscription(Image, cfg.color_topic, self._on_color, 5)
        self.create_subscription(Image, cfg.depth_topic, self._on_depth, 5)
        self.create_subscription(CameraInfo, cfg.info_topic, self._on_info, 5)

    def _stamp(self, msg: Any) -> str:
        stamp = getattr(getattr(msg, "header", None), "stamp", None)
        if stamp is None:
            return _now_iso()
        return f"{getattr(stamp, 'sec', 0)}.{getattr(stamp, 'nanosec', 0):09d}"

    def _on_color(self, msg: Any) -> None:
        self.color = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        self.color_stamp = self._stamp(msg)

    def _on_depth(self, msg: Any) -> None:
        self.depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        self.depth_stamp = self._stamp(msg)

    def _on_info(self, msg: Any) -> None:
        self.info = msg

    def ready(self) -> bool:
        return self.color is not None and self.depth is not None and self.info is not None

    def estimate_pose(self) -> dict[str, Any]:
        if self.color is None or self.depth is None or self.info is None:
            return _failure("SPECIMEN_POSE_FRAME_INCOMPLETE", "Color, depth, or camera_info frame is missing.")

        hsv = cv2.cvtColor(self.color, cv2.COLOR_BGR2HSV)
        red_mask = cv2.inRange(hsv, np.array([0, 70, 35], dtype=np.uint8), np.array([12, 255, 255], dtype=np.uint8))
        red_mask |= cv2.inRange(hsv, np.array([168, 70, 35], dtype=np.uint8), np.array([180, 255, 255], dtype=np.uint8))
        kernel = np.ones((5, 5), np.uint8)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return _failure(
                "SPECIMEN_NOT_DETECTED",
                f"No red specimen contour was detected in {self.cfg.camera_id} color frame.",
            )

        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        if area < self.cfg.min_contour_area_px:
            return _failure(
                "SPECIMEN_CONTOUR_TOO_SMALL",
                f"Detected contour area {area:.1f}px is below {self.cfg.min_contour_area_px:.1f}px.",
                contour_area_px=area,
            )

        x, y, w, h = cv2.boundingRect(contour)
        cx = int(x + w / 2)
        cy = int(y + h / 2)
        depth = np.asarray(self.depth)
        y0, y1 = max(cy - 4, 0), min(cy + 5, depth.shape[0])
        x0, x1 = max(cx - 4, 0), min(cx + 5, depth.shape[1])
        depth_window = depth[y0:y1, x0:x1].astype(np.float64)
        valid_depth = depth_window[np.isfinite(depth_window) & (depth_window > 0)]
        if valid_depth.size == 0:
            return _failure("SPECIMEN_DEPTH_MISSING", "No valid depth samples were available at the detected specimen center.")
        depth_mm = float(np.median(valid_depth))
        if depth_mm < 10.0:
            depth_mm *= 1000.0

        k_raw = getattr(self.info, "k", [])
        k = list(k_raw) if k_raw is not None else []
        fx = float(k[0]) if len(k) > 0 and k[0] else 1.0
        fy = float(k[4]) if len(k) > 4 and k[4] else 1.0
        ppx = float(k[2]) if len(k) > 2 else depth.shape[1] / 2.0
        ppy = float(k[5]) if len(k) > 5 else depth.shape[0] / 2.0
        camera_x_mm = (cx - ppx) * depth_mm / fx
        camera_y_mm = (cy - ppy) * depth_mm / fy
        camera_z_mm = depth_mm
        robot_x_mm = camera_x_mm + self.cfg.camera_to_robot_x_mm
        robot_y_mm = camera_y_mm + self.cfg.camera_to_robot_y_mm
        robot_z_mm = camera_z_mm + self.cfg.camera_to_robot_z_mm

        debug = self.color.copy()
        cv2.rectangle(debug, (x, y), (x + w, y + h), (20, 220, 130), 2)
        cv2.circle(debug, (cx, cy), 5, (255, 255, 0), -1)
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)
        debug_path = self.cfg.output_dir / "specimen_pose_debug.png"
        pose_path = self.cfg.output_dir / "specimen_pose.json"
        cv2.imwrite(str(debug_path), debug)

        image_area = float(max(1, self.color.shape[0] * self.color.shape[1]))
        confidence = min(0.99, max(0.0, (area / image_area) * 18.0))
        pose = {
            "schema": "specimen_pose.v1",
            "stage": "post_ejection_workspace_localization",
            "camera_id": self.cfg.camera_id,
            "camera_owner_before": "vla_runtime",
            "camera_owner_after": "vla_runtime",
            "workspace": self.cfg.workspace,
            "specimen_id": self.cfg.specimen_id,
            "frame_id": f"{self.cfg.camera_id}-{int(time.time() * 1000)}",
            "timestamp": _now_iso(),
            "color_stamp": self.color_stamp,
            "depth_stamp": self.depth_stamp,
            "center_px": [cx, cy],
            "bbox_xyxy": [int(x), int(y), int(x + w), int(y + h)],
            "contour_area_px": round(area, 3),
            "depth_mm": round(depth_mm, 3),
            "position_camera_mm": {
                "x": round(camera_x_mm, 3),
                "y": round(camera_y_mm, 3),
                "z": round(camera_z_mm, 3),
            },
            "position_robot_base_mm": {
                "x": round(robot_x_mm, 3),
                "y": round(robot_y_mm, 3),
                "z": round(robot_z_mm, 3),
            },
            "position_a4_mm": {
                "x": round(148.5 + robot_x_mm, 3),
                "y": round(105.0 + robot_y_mm, 3),
                "z": round(max(0.0, robot_z_mm), 3),
            },
            "position_isaac_world_mm": {
                "x": round(robot_x_mm, 3),
                "y": round(robot_y_mm, 3),
                "z": round(robot_z_mm, 3),
            },
            "orientation_deg": {"yaw": 0.0},
            "confidence": round(confidence, 3),
            "stable_frames": 1,
            "freshness_ms": 0,
            "port_released": True,
            "vla_camera_precheck_ok": True,
            "debug_image_path": str(debug_path),
            "raw_pose_json_path": str(pose_path),
        }
        pose_path.write_text(json.dumps(pose, ensure_ascii=True, indent=2), encoding="utf-8")
        return {
            "ok": confidence >= self.cfg.confidence_threshold,
            "pose": pose,
            "failure_code": "" if confidence >= self.cfg.confidence_threshold else "SPECIMEN_POSE_LOW_CONFIDENCE",
            "message": "" if confidence >= self.cfg.confidence_threshold else f"confidence={confidence:.3f} below threshold={self.cfg.confidence_threshold:.3f}",
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ATR one-shot RGB-D specimen pose tracker")
    parser.add_argument("--specimen-id", default="specimen-live")
    parser.add_argument("--camera-id", default="d455f_global")
    parser.add_argument("--workspace", default="a4_robot_workspace")
    parser.add_argument("--color-topic", default="/camera/d455f/color/image_raw")
    parser.add_argument("--depth-topic", default="/camera/d455f/aligned_depth_to_color/image_raw")
    parser.add_argument("--info-topic", default="/camera/d455f/color/camera_info")
    parser.add_argument("--output-dir", default="runs/specimen_pose_tracker")
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    parser.add_argument("--confidence-threshold", type=float, default=0.75)
    parser.add_argument("--min-contour-area-px", type=float, default=20.0)
    parser.add_argument("--camera-to-robot-x-mm", type=float, default=0.0)
    parser.add_argument("--camera-to-robot-y-mm", type=float, default=0.0)
    parser.add_argument("--camera-to-robot-z-mm", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if _IMPORT_ERROR is not None:
        print(json.dumps(_failure("ROS_IMPORT_FAILED", f"{_IMPORT_ERROR.__class__.__name__}: {_IMPORT_ERROR}"), ensure_ascii=True), flush=True)
        raise SystemExit(2)

    cfg = OneShotConfig(
        specimen_id=args.specimen_id,
        camera_id=args.camera_id,
        workspace=args.workspace,
        color_topic=args.color_topic,
        depth_topic=args.depth_topic,
        info_topic=args.info_topic,
        output_dir=Path(args.output_dir).expanduser(),
        timeout_sec=max(float(args.timeout_sec), 0.5),
        confidence_threshold=max(0.0, min(1.0, float(args.confidence_threshold))),
        min_contour_area_px=max(float(args.min_contour_area_px), 1.0),
        camera_to_robot_x_mm=float(args.camera_to_robot_x_mm),
        camera_to_robot_y_mm=float(args.camera_to_robot_y_mm),
        camera_to_robot_z_mm=float(args.camera_to_robot_z_mm),
    )
    rclpy.init()
    node = SpecimenPoseNode(cfg)
    deadline = time.monotonic() + cfg.timeout_sec
    result: dict[str, Any] = _failure("SPECIMEN_POSE_TIMEOUT", "No RGB-D snapshot arrived before timeout.")
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.ready():
                result = node.estimate_pose()
                break
        print(json.dumps(result, ensure_ascii=True), flush=True)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
