# UTM ROS Vision Runtime Bridge

## Purpose

This runtime bridge connects the cloned UTM ROS program into ATR as a live/test device evidence provider. It does not replace the Windows PyAutoGUI UTM control path. It adds ROS camera, marker-state, and RQT-like node-flow evidence that Vision Agent and Lab Equipment Agent can use before handing UTM data to Analysis Agent.

External source-of-truth repository:

```text
/home/jin/external_repos/UTM
https://github.com/hylee12345/UTM
```

ATR integration files:

```text
device_bridges/utm_runtime_bridge.py
device_bridges/utm_state_observer.py
mcp_tools/camera_tools.py
app/bootstrap.py
app/main.py
configs/devices.yaml
web/templates/index.html
web/templates/vision_utm_device_bridge.html
web/static/app.js
web/static/planning.js
web/static/vision_utm_device_bridge.js
```

## Runtime Flow

The RQT-like internal flow must follow the cloned UTM program, not a hand-invented ATR-only diagram.

Source files used for the expected graph:

```text
/home/jin/external_repos/UTM/scripts/start_utm_vision_stack.sh
/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/camera_rect.launch.py
/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/green_dot_monitor.launch.py
/home/jin/external_repos/UTM/scripts/yolo.sh
```

Expected node/topic flow:

```text
camera/usb_cam
  -> /camera/image_raw
  -> camera/rectify_node
  -> /camera/image_rect
  -> compression_tester_monitor/green_dot_monitor
  -> /image_utm
  -> yolo_bringup/yolov8
  -> /yolo/detections
  -> /yolo/tracking
  -> /yolo/dbg_image

compression_tester_monitor/green_dot_monitor also publishes:
  -> /compression_tester/state
  -> /compression_tester/summary
  -> /compression_tester/metrics
  -> /compression_tester/green_points
  -> /compression_tester/debug_image
```

Actual graph evidence is read from ROS2 at runtime:

```bash
ros2 node list
ros2 topic list
ros2 node info <node>
```

The backend builds publisher/subscriber edges from `ros2 node info`. The expected graph is only the UTM-repo launch contract; the actual graph is the live ROS source of truth.

## Installed Local Runtime Baseline

Validated on this workstation:

```text
Ubuntu 24.04.4 LTS noble, aarch64
ROS 2 Jazzy
UTM workspace: /home/jin/external_repos/UTM
YOLO ROS workspace: /home/jin/external_repos/yolo_ros
YOLO model: /home/jin/external_repos/yolo_ros/models/yolov8m.pt
```

Validated commands:

```bash
source /opt/ros/jazzy/setup.bash
source /home/jin/external_repos/UTM/install/setup.bash
source /home/jin/external_repos/yolo_ros/install/setup.bash
ros2 pkg list | rg '^(compression_tester_monitor|roi_image_cropper|yolo_bringup|yolo_ros|yolo_msgs)$'
```

Current local preflight result:

```text
compression_tester_monitor: found
roi_image_cropper: found
yolo_bringup/yolo_ros/yolo_msgs: found
ultralytics: import ok through yolo_ros uv environment
torch: CUDA available through yolo_ros uv environment
```

If no camera is connected, `usb_cam` can fail with no `/sys/class/video4linux/`. That is a hardware visibility issue, not an ATR bridge path issue.

## Installation

### ROS 2 Jazzy

```bash
sudo apt update
sudo apt install -y software-properties-common curl ca-certificates git
sudo add-apt-repository -y universe
curl -L -o /tmp/ros2-apt-source_noble.deb \
  https://repo.ros2.org/ubuntu/main/pool/main/r/ros-apt-source/ros2-apt-source_1.2.0~noble_all.deb
sudo dpkg -i /tmp/ros2-apt-source_noble.deb
sudo apt update
sudo apt install -y \
  ros-jazzy-ros-base \
  ros-dev-tools \
  python3-colcon-common-extensions \
  python3-rosdep \
  ros-jazzy-cv-bridge \
  ros-jazzy-image-transport \
  ros-jazzy-image-proc \
  ros-jazzy-vision-msgs \
  ros-jazzy-usb-cam \
  ros-jazzy-camera-calibration \
  ros-jazzy-camera-calibration-parsers \
  ros-jazzy-rqt-gui \
  ros-jazzy-rqt-image-view \
  ros-jazzy-rqt-graph
```

Initialize rosdep once:

```bash
sudo rosdep init  # skip if /etc/ros/rosdep/sources.list.d/20-default.list exists
rosdep update
```

### Camera Device Bridge

The operator-facing bridge name is `Camera`. Physical product names are shown
only as `/dev/v4l/by-id` discovery labels. The bridge must not hard-code a
specific camera serial or product name into the runtime contract.

Device workspace route:

```text
/device-bridge/vision-utm
```

Saved operator override:

```text
memory/device_bridge/utm_camera_config.json
```

Validated ATR runtime camera settings use the fastest compatible BRIO profile
measured through the complete ROS Vision stack:

```text
640x480 @ 60fps
pixel_format=mjpeg2rgb
io_method=mmap
brightness=128
gain=-1
```

The device path is empty until an operator selects and saves an OS-discovered
Camera candidate. When saved, the bridge injects `UTM_CAMERA_*` environment
variables into the UTM runtime launch.

Runtime FPS stability rule:

- Keep ATR normal operation on `pixel_format=mjpeg2rgb` at 60 fps. On this
  workstation, `yuyv2rgb` invokes an unaccelerated YUV422-to-RGB conversion and
  produces substantially fewer frames through the complete Vision stack.
- Before starting the UTM ROS process group, the bridge runs this best-effort
  V4L2 control against the saved camera device:

```bash
v4l2-ctl --device=<saved-camera-device> --set-ctrl=exposure_dynamic_framerate=0
```

This prevents BRIO-class UVC cameras from lowering FPS dynamically under
auto-exposure. The result is returned in `startup_camera_controls` from
`POST /api/equipment/utm-runtime/start`. If a camera does not expose the control,
the bridge records a warning but continues starting the ROS runtime.

Measured local result after applying the stable profile:

```text
Before fix: 96 frames / 32.6 s over the HTTP MJPEG route
After fix: 457 frames / 30.1 s over the HTTP MJPEG route
MJPEG ROS subscriber workers: 1 shared worker for /image_utm
```

Checkerboard calibration uses ROS `camera_calibration`:

```bash
source /opt/ros/jazzy/setup.bash
ros2 run camera_calibration cameracalibrator --size 9x6 --square 0.021 image:=/camera/image_raw camera:=/camera
```

### UTM Workspace

```bash
cd /home/jin/external_repos/UTM
source /opt/ros/jazzy/setup.bash
rosdep check --from-paths src --ignore-src
colcon build --symlink-install
source install/setup.bash
ros2 pkg list | rg '^(compression_tester_monitor|roi_image_cropper)$'
```

### YOLO ROS Workspace

```bash
cd /home/jin/external_repos
git clone https://github.com/mgonzs13/yolo_ros.git yolo_ros
cd /home/jin/external_repos/yolo_ros
source /opt/ros/jazzy/setup.bash
rosdep check --from-paths . --ignore-src
colcon build --symlink-install
```

Install `uv`, then pre-sync the YOLO runtime Python environment used by `yolo_bringup`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --project /home/jin/external_repos/yolo_ros/install/yolo_ros/share/yolo_ros
```

Download the local model used by the cloned UTM start script override:

```bash
mkdir -p /home/jin/external_repos/yolo_ros/models
curl -L -o /home/jin/external_repos/yolo_ros/models/yolov8m.pt \
  https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m.pt
```

Disk note: the local `yolo_ros` workspace plus uv environment is about 5 GB on this machine because it includes PyTorch/CUDA wheels.

## ATR Configuration

`configs/devices.yaml` contains:

```yaml
utm_vision_runtime:
  workspace_root: /home/jin/external_repos/UTM
  script_path: /home/jin/external_repos/UTM/scripts/start_utm_vision_stack.sh
  log_dir: artifacts/utm_runtime
  summary_topic: /compression_tester/summary
  frame_topic: /image_utm
  ros_setup_paths:
    - /opt/ros/jazzy/setup.bash
  extra_setup_paths:
    - /home/jin/external_repos/UTM/install/setup.bash
    - /home/jin/external_repos/yolo_ros/install/setup.bash
  environment:
    YOLO_MODEL_PATH: /home/jin/external_repos/yolo_ros/models/yolov8m.pt
  allow_virtual_bridge_in_test: true
```

The runtime command always prepends:

```bash
export PATH="$HOME/.local/bin:$PATH"
source /opt/ros/jazzy/setup.bash
source /home/jin/external_repos/UTM/install/setup.bash
source /home/jin/external_repos/yolo_ros/install/setup.bash
export YOLO_MODEL_PATH=/home/jin/external_repos/yolo_ros/models/yolov8m.pt
v4l2-ctl --device=/dev/video0 --set-ctrl=exposure_dynamic_framerate=0
export UTM_VISION_ROOT=/home/jin/external_repos/UTM
export UTM_CAMERA_FPS=60.0
export UTM_CAMERA_PIXEL_FORMAT=mjpeg2rgb
bash /home/jin/external_repos/UTM/scripts/start_utm_vision_stack.sh
```

## Low-Latency Image Transport Contract

UTM camera streams are live evidence, not archival transport. The local FastDDS
path requires RELIABLE delivery for the fragmented 640x480 RGB messages. All
image endpoints use depth-one queues, and green-dot caps annotated image output
at 30 fps. The UTM launcher also applies
`config/fastdds_utm_shm.xml`: UDP remains available for discovery while local
image payloads use a 16 MiB SHM segment instead of the default 512 KiB segment.

```text
reliability: RELIABLE
history: KEEP_LAST
depth: 1
durability: VOLATILE
```

Applied locations:

- ATR snapshot subscriber in `device_bridges/utm_runtime_bridge.py`.
- ATR browser MJPEG subscriber worker in `device_bridges/utm_runtime_bridge.py`.
- UTM `green_dot_monitor` image input subscriber and debug/output image publishers.
- `yolo_ros` launch through `image_reliability:=1`, which maps to Reliable and
  uses depth 1 inside the local `yolo_ros` nodes.
- FastDDS transport profile in
  `/home/jin/external_repos/UTM/config/fastdds_utm_shm.xml`, loaded automatically
  by `scripts/start_utm_vision_stack.sh` with asynchronous publication.

Measured reason:

- BEST_EFFORT delivered only 4.69 fps from a standalone `usb_cam` while the same
  topic delivered 59.03 fps to a RELIABLE subscriber; V4L2 direct capture was
  60.0 fps. With RELIABLE delivery, camera+rectifier+green-dot produced 50.78
  fps, while the correctly typed `yolo_msgs/DetectionArray` output sustained
  about 29.8 fps. Capping only the annotated image publisher at 30 fps preserves
  the high-rate detector/state loop.

Removed optimization:

- OpenCV CUDA color conversion was tested and then removed from the ATR MJPEG
  worker. On this workstation `cv2.cuda` exists, but
  `cv2.cuda.getCudaEnabledDeviceCount()` returns `0` in the ROS Python runtime,
  so that path did not accelerate the live stream and only added fallback
  complexity.
- The worker now keeps only CPU color conversion plus explicit handling for the
  observed UVC/ROS encodings (`bgr8`, `rgb8`, `mono8`, `bgra8`, `rgba8`,
  `yuyv*`). If stream FPS is still low, investigate `/camera/image_raw` and the
  camera publisher first.

## API

```text
GET  /api/equipment/utm-runtime/status
POST /api/equipment/utm-runtime/start
POST /api/equipment/utm-runtime/stop
POST /api/equipment/utm-runtime/probe
GET  /api/equipment/utm-runtime/graph?previous_hash=...
GET  /api/equipment/utm-runtime/frame
GET  /api/equipment/utm-runtime/camera-config
POST /api/equipment/utm-runtime/camera-config
GET  /api/equipment/utm-runtime/camera/devices
POST /api/equipment/utm-runtime/camera/probe
POST /api/equipment/utm-runtime/camera/apply
POST /api/equipment/utm-runtime/camera/calibrate/start
POST /api/equipment/utm-runtime/camera/calibrate/stop
GET  /api/equipment/utm-runtime/camera/calibrate/status
```

`/graph` returns both the expected UTM repo flow and actual ROS2 nodes/topics/edges. `graph_hash` lets the browser avoid rerendering unchanged topology.

`/frame` launches a short ROS-enabled subprocess, subscribes to one image topic, and returns either:

```text
frame_available=true
data_url=data:image/jpeg;base64,...
topic=/image_utm or fallback topic
width/height/encoding/frame_age_ms
```

or structured no-frame evidence:

```text
frame_available=false
failure_code=ROS_IMAGE_FRAME_UNAVAILABLE
attempts[]=topic + returncode + failure_code + message
```

The topic priority follows the UTM runtime evidence path:

```text
/image_utm
/yolo/dbg_image
/compression_tester/debug_image
/camera/image_rect
/camera/image_raw
```

## GUI

Main GUI Device Workspace card:

```text
UTM ROS System
RQT flow from cloned UTM program
Loading / Probe / Unloading
usb_cam -> rectify_node -> green_dot_monitor -> yolov8
cloned UTM · expected N nodes · actual M nodes · ROS2 ready/missing · topic ready/waiting
image preview or image frame unavailable evidence

Vision / UTM Camera Bridge
Camera mapping · frame probe · calibration
/device-bridge/vision-utm
```

Live GUI device strip:

```text
UTM ROS Runtime · usb->rect->green->yolo
runtime status
```

The Live GUI card is intentionally compact. Full RQT-like flow is exposed in the Main GUI Device Workspace and through `/api/equipment/utm-runtime/graph`.

## Test Mode and Live Mode

Test mode:

- If ROS2/UTM camera evidence exists, use the real ROS observer.
- If ROS2/topic/camera evidence is unavailable, continue through `virtual_utm_bridge` and leave a fallback trace.
- Do not claim physical UTM completion from virtual evidence.

Live mode:

- Load the UTM runtime when the UTM stage requires camera/marker evidence.
- If `/compression_tester/summary` is stale or missing, return operator attention.
- Do not use virtual evidence to mark physical UTM motion complete.

## Verification Commands

```bash
.venv/bin/pytest tests/unit/test_utm_state_observer.py \
  tests/unit/test_utm_runtime_bridge.py \
  tests/unit/test_utm_camera_config.py \
  tests/unit/test_utm_runtime_camera_env.py \
  tests/unit/test_utm_camera_device_discovery.py \
  tests/unit/test_utm_camera_calibration_command.py \
  tests/unit/test_camera_tools_utm_runtime.py \
  tests/integration/test_utm_runtime_gui_api.py \
  tests/unit/test_utm_runtime_frontend_static.py -q
```

Browser screenshots from the latest local audit:

```text
artifacts/browser_checks/utm_runtime_main_gui_flow.png
artifacts/browser_checks/utm_runtime_main_gui_frame_probe.png
artifacts/browser_checks/utm_runtime_live_gui_flow_compact.png
artifacts/browser_checks/utm_live_gui_test_mode_fullpath_summary.json
```

The full-path summary records the Live GUI `테스트 모드, 가상 브릿지` run. A valid completed run has `workflow_complete=true`, `stage=complete`, `loop_count=5`, and one message from every agent stage from Design through Guardian.

Short runtime preflight performed on 2026-06-22:

```text
start: UTM script entered camera_rect
stop: process group stopped cleanly
graph: ROS2 ready, UTM/yolo source files found, cloned expected graph rendered
frame: ROS subscriber path executed; no image topics produced a frame in the current no-camera/no-UTM-motion environment, so frame_available=false with ROS_IMAGE_TIMEOUT attempts
observed issue: no active UTM image frame was available during this audit; physical camera/frame verification requires the UTM camera pipeline to be producing /image_utm or a fallback image topic
```

2026-06-22 live-camera stability update:

```text
symptom: /camera/image_raw fell from requested 15 fps to 1-4 fps; /image_utm fell to 1-3 fps
ROS log: /camera/image_raw and /camera/camera_info not synchronized; green_dot input_gap_ms often 2000-3000 ms
root cause: active saved profile used mjpeg2rgb while the cloned UTM BRIO path expects yuyv2rgb
accepted profile: 640x480, 15 fps, yuyv2rgb, exposure_dynamic_framerate=0 before start
verified route: /api/equipment/utm-runtime/frame-stream.mjpeg?topic=/image_utm&fps=15
result: 457 frames / 30.1 s
```

2026-09-02 BRIO raw-input benchmark update (supersedes the active profile above):

```text
device link: USB 3, 5000M; V4L2 sustains YUYV 30 fps and MJPEG 60 fps directly
usb_cam version: ROS Jazzy 0.8.1
old full stack: yuyv2rgb 640x480 requested 15 fps -> raw 2.2 fps, image_utm 1.6 fps
accepted full stack: mjpeg2rgb 640x480 requested 60 fps -> raw 9.1 fps, image_utm 8.4 fps
60-second image_utm bins: 7.1, 9.3, 6.7, 8.7, 10.4, 8.3 fps; no monotonic slowdown
rejected: userptr produced no frames; raw yuyv aborted; raw_mjpeg republish changed the topic/encoding contract
required control: exposure_dynamic_framerate=0 before start
follow-up root cause: BEST_EFFORT loses fragmented RGB samples, while uncapped all-RELIABLE fan-out eventually propagates slow-consumer backpressure
accepted QoS: RELIABLE, KEEP_LAST, depth 1 for all image endpoints; `/image_utm` annotated output capped at 30 fps
isolated rates: V4L2 60.0 fps; usb_cam BEST_EFFORT 4.69 fps vs RELIABLE 59.03 fps; RELIABLE green-dot output 50.78 fps; correctly typed YOLO detections about 29.8 fps
root cause correction: the default FastDDS SHM segment was 512 KiB, smaller than one 640x480 BGR frame (921,600 bytes), while UDP socket receive buffers were only 212,992 bytes; the all-RELIABLE path therefore collapsed to about 4 fps after roughly two minutes
accepted transport: custom UDPv4 discovery plus 16 MiB SHM segment and 1 MiB maximum SHM message; 180-second full-fanout test held JPEG and YOLO delivery at 26.5-29.1 fps without collapse
GUI pacing: `/image_utm` is capped once in green-dot; the MJPEG worker does not apply a second frame filter, which keeps jittered input from being reduced to 18-22 fps
```

## D455F Specimen Pose Tracker Separation

The UTM/BRIO bridge remains the inspection and placement-verification camera path. D455F specimen pose tracking is a separate one-shot ROS runtime used before manipulation.

The D455F tracker does not reuse `/image_utm` and does not keep a shared ROS topic open for VLA. It captures one RGB-D pose, stops ROS, confirms release, and returns the camera to VLA.

Current ROS topic contract:

```text
color: /camera/d455f/color/image_raw
depth: /camera/d455f/aligned_depth_to_color/image_raw
info:  /camera/d455f/color/camera_info
```

The Spark workstation should prefer the local RSUSB Python/librealsense build
when Python tools import `pyrealsense2`. The bridge injects
`/home/jin/librealsense-rsusb/build-rsusb-system/Release` into `PYTHONPATH` and
`LD_LIBRARY_PATH` for the one-shot tracker subprocess.

Runtime boundary:

```text
VLA route owns D455F by default
-> VisionAgent requests vision.specimen_pose_snapshot
-> D455F one-shot tracker writes specimen_pose.v1 evidence
-> vision.specimen_pose.release returns ownership to VLA
-> ManipulationAgent starts only if camera_returned_to_vla and vla_camera_precheck_ok are true
```

The post-manipulation placement check still uses the BRIO/UTM runtime path and its RQT-like graph evidence.

Observed hardware boundary on 2026-06-25: D455F initially enumerated on USB2,
then moved to USB3 during re-enumeration, but later `NVDA8000:00` reported
`xHCI host controller not responding, assume dead` and the camera disappeared
from `lsusb`. In that state, ROS can create publishers but no frames arrive.
Recover the USB controller by replug/power-cycle/reboot before live D455F
validation; test mode continues through the deterministic virtual pose path.
