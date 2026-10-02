"""Read-only ROI contract published by the Live Observation ROS monitor."""
import json
import math


ROI_CAPTURE_SCRIPT = r'''
import json, sys, time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String
rclpy.init()
node = Node("atr_read_observation_roi")
received = []
def callback(message):
    try:
        roi = json.loads(message.data).get("x_roi")
        if isinstance(roi, dict): received.append(roi)
    except (ValueError, TypeError): pass
subscription = node.create_subscription(String, sys.argv[1], callback, qos_profile_sensor_data)
deadline = time.monotonic() + 1.5
while not received and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.1)
print(json.dumps(received[-1] if received else {}))
node.destroy_node()
rclpy.shutdown()
'''


def observation_roi(manager, width, height):
    """No full-frame fallback: disabled/missing/out-of-frame bounds are unresolved."""
    runner = getattr(manager, "_run_ros_frame_command", None)
    if not callable(runner):
        raise ValueError("Live Observation ROI reader unavailable")
    topic = getattr(getattr(manager, "config", None), "summary_topic", "/compression_tester/summary")
    code, stdout, _ = runner(["python3", "-c", ROI_CAPTURE_SCRIPT, topic], timeout_sec=4.0)
    if code:
        raise ValueError("Live Observation ROI capture failed")
    try:
        roi = json.loads(stdout.strip().splitlines()[-1])
        bounds = [float(roi[k]) for k in ("x_min", "y_min", "x_max", "y_max")]
        valid = (roi.get("enabled") is True and all(math.isfinite(v) and v.is_integer() for v in bounds)
            and 0 <= bounds[0] < bounds[2] <= width and 0 <= bounds[1] < bounds[3] <= height)
        if not valid: raise ValueError("Live Observation ROI is invalid or disabled")
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Live Observation ROI unavailable") from exc
    return tuple(v / (width if i % 2 == 0 else height) for i, v in enumerate(bounds))
