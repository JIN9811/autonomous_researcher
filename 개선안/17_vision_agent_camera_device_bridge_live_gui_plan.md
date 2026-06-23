# 17. Vision Agent Camera Device Bridge + Live GUI Inspection Dashboard Plan

작성일: 2026-06-22

대상 코드:

```text
device_bridges/utm_runtime_bridge.py
device_bridges/utm_state_observer.py
mcp_tools/camera_tools.py
agents/vision_agent.py
agents/equipment_agent.py
app/main.py
configs/devices.yaml
web/templates/index.html
web/templates/planning.html
web/static/app.js
web/static/planning.js
web/static/styles.css
docs/hardware/utm_ros_vision_runtime_bridge.md
docs/gui/gui.md
REQUIREMENTS.md
```

연결되는 기존 개선안:

```text
03_vision_agent_lab_perception_signal_loop_research.md
05_lab_equipment_agent_utm_visual_control_data_loop_research.md
11_live_gui_control_surface_upgrade_plan.md
16_utm_ros_runtime_bridge_live_gui_plan.md
```

기준 reference:

```text
사용자 제공 Vision inspection dashboard reference screenshot
/home/jin/external_repos/UTM/scripts/start_utm_vision_stack.sh
/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/camera_rect.launch.py
/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/green_dot_monitor.launch.py
```

## 0. 결론

현재 UTM ROS runtime bridge는 backend path와 RQT-like flow를 갖췄지만, Live GUI의 Vision Agent report는 아직 operator가 카메라 상태, frame, marker/YOLO evidence, handoff readiness를 한눈에 판단하기에 부족하다.

따라서 다음 단계는 Vision Agent를 새 모델로 바꾸는 것이 아니라, **Camera device bridge 설정 페이지**와 **Vision Agent Live GUI inspection dashboard**를 추가하는 것이다.

핵심 원칙:

```text
Device Bridge page = 장비/카메라 설정, mapping, probe, 저장, runtime start/stop
Live GUI Vision Agent report = 현재 loop에서 Vision evidence를 operator가 해석하는 관제 화면
Backend trace = raw graph, raw ROS diagnostics, raw tool response
```

Live GUI는 raw JSON dump가 아니라 reference screenshot처럼 card 기반으로 보여야 한다. 다만 내용은 defect inspection이 아니라 ATR UTM 실험 흐름에 맞춘다.

## 1. 현재 상태 진단

현재 구현된 것:

- `UTMRuntimeProcessManager`가 UTM clone script를 실행한다.
- RQT-like graph는 clone된 UTM program flow를 따른다.
- `/api/equipment/utm-runtime/status`, `start`, `stop`, `probe`, `graph`, `frame`이 있다.
- Main GUI Device Workspace에 `UTM ROS System` card가 있다.
- Live GUI 하단 device strip에 UTM compact card가 있다.
- Live GUI test mode `테스트 모드, 가상 브릿지`는 5-cycle closed loop를 완료했다.

현재 부족한 것:

- Camera device path, resolution, fps, brightness, exposure, gain을 GUI에서 설정/저장할 수 없다.
- UTM runtime start 시 camera 설정이 `camera_rect.launch.py`에 충분히 전달되지 않는다.
- Live GUI Vision Agent report가 reference처럼 camera health, live feed, detection/segmentation, confidence, evidence/handoff를 한 화면에서 보여주지 않는다.
- 실제 `/api/equipment/utm-runtime/frame` preview가 Vision report 본문과 강하게 연결되어 있지 않다.
- 카메라 mapping은 현재 LeRobot 쪽과 UTM runtime 쪽 개념이 섞일 위험이 있다.
- 장비 설정 page와 실험 loop report가 분리되지 않아 operator가 어디서 설정하고 어디서 관찰해야 하는지 불명확하다.

## 2. 목표

### 2.1 기능 목표

1. Main GUI Device Workspaces에 `Vision / UTM Camera Bridge` 전용 진입점을 추가한다.
2. 별도 Device Bridge page를 만든다.
   - 권장 route: `/device-bridge/vision-utm`
3. 해당 page에서 OS가 인식한 Camera 후보를 탐색하고, 선택한 device path를 mapping, 설정, probe, 저장할 수 있게 한다.
4. 저장된 설정은 UTM runtime start/probe/frame capture에 반영한다.
5. Live GUI Vision Agent report를 reference screenshot처럼 inspection dashboard 형태로 바꾼다.
6. Vision Agent report는 실제 backend payload만 표시하고 임의 숫자를 생성하지 않는다.
7. 실제 frame이 없으면 숨기지 말고 `frame unavailable`, failure code, next action을 표시한다.
8. browser screenshot 기반 육안검사를 필수 완료 조건으로 둔다.

### 2.2 비목표

이번 개선안에서 하지 않을 것:

- Vision Agent가 robot, UTM, printer를 직접 실행하지 않는다.
- YOLO/green-dot 알고리즘 자체를 대체하지 않는다.
- UTM clone flow를 ATR 임의 graph로 바꾸지 않는다.
- LeRobot top/wrist RealSense camera mapping을 UTM Camera mapping으로 덮어쓰지 않는다.
- 물리 장비 live 완료를 virtual evidence로 통과시키지 않는다.

## 3. Device Bridge Page 설계

### 3.1 Page 역할

`Vision / UTM Camera Bridge` page는 operator setup 화면이다.

```text
사용자 목적:
  1. Camera가 OS에서 잡히는지 확인한다. 제품명은 탐색 결과 label로만 표시하고, bridge 계약에는 특정 모델명을 박지 않는다.
  2. UTM runtime에서 사용할 camera path를 선택
  3. 해상도/fps/밝기/노출/gain 설정
  4. probe로 실제 frame 확인
  5. 설정을 저장
  6. UTM ROS runtime Loading/Unloading
  7. RQT-like graph와 actual ROS topic 상태 확인
```

### 3.2 권장 화면 구성

```text
Top bar
  - Vision / UTM Camera Bridge
  - Runtime status: stopped/running/error
  - Active camera: selected Camera by-id path
  - Save state: saved/dirty/error

Left column: Camera Device Mapping
  - Detected V4L devices
  - by-id path
  - model/vendor/name
  - selected role: UTM primary camera
  - Save mapping

Center column: Live Probe / Frame Preview
  - snapshot from selected camera or /image_utm
  - resolution/fps/encoding/frame age
  - brightness/exposure/gain current values
  - Probe selected camera
  - Probe ROS frame

Right column: Runtime / RQT Flow
  - Loading / Probe / Unloading
  - cloned UTM flow: usb_cam -> rectify_node -> green_dot_monitor -> yolov8
  - actual node/topic overlay
  - diagnostics and blockers

Bottom: Camera Controls
  - resolution
  - fps
  - pixel_format
  - brightness
  - exposure_auto
  - exposure_absolute
  - gain
  - checkerboard size
  - checkerboard square size
  - Calibrate
  - Reset to defaults
```

### 3.3 기본 Camera 사양

사용자-facing 명칭은 항상 `Camera`로 둔다. 특정 제품명은 `/dev/v4l/by-id` 탐색 결과의 물리 후보 label로만 표시한다. GUI 제목, agent/report 이름, runtime contract는 특정 제품명 기반 bridge처럼 노출하지 않는다.

기본값은 clone된 UTM 프로그램의 `camera_rect.launch.py`와 맞춘다.

```text
default device candidate: none until the operator selects and saves a detected Camera path
image_width: 640
image_height: 480
framerate: 30.0
pixel_format: yuyv2rgb
brightness: 128
gain: -1
```

즉 설치 직후 기본 Camera quality는 `640x480 @ 30fps`다. 사용자가 더 높은 화질을 원하면 Device Bridge page에서 resolution/fps를 바꿔 저장한다. 이때 저장값은 `memory/device_bridge/utm_camera_config.json`에만 들어가며, clone된 UTM flow 자체는 바꾸지 않는다.

### 3.4 설정 저장 위치

기본 config:

```text
configs/devices.yaml
```

operator override:

```text
memory/device_bridge/utm_camera_config.json
```

`memory/device_bridge/utm_camera_config.json`은 gitignore 대상이어야 한다. 새 PC 사용자는 GUI에서 저장하면 자동 생성된다.

예시:

```json
{
  "schema": "atr.utm_camera_config.v1",
  "updated_at": "2026-06-22T00:00:00Z",
  "active_profile_id": "camera_utm_primary",
  "profiles": {
    "camera_utm_primary": {
      "label": "Camera UTM Primary",
      "camera_role": "utm_primary",
      "device_path": "/dev/v4l/by-id/<selected-camera>",
      "fallback_device_path": "/dev/video0",
      "backend": "v4l2_usb_cam",
      "width": 640,
      "height": 480,
      "fps": 30,
      "pixel_format": "yuyv2rgb",
      "brightness": 128,
      "gain": -1,
      "exposure_auto": "",
      "exposure_absolute": null,
      "ros_image_topic": "/camera/image_raw",
      "rectified_topic": "/camera/image_rect",
      "utm_annotated_topic": "/image_utm"
    }
  }
}
```

## 4. Backend API 설계

추가 API:

```text
GET  /api/equipment/utm-runtime/camera-config
POST /api/equipment/utm-runtime/camera-config
GET  /api/equipment/utm-runtime/camera/devices
POST /api/equipment/utm-runtime/camera/probe
POST /api/equipment/utm-runtime/camera/apply
POST /api/equipment/utm-runtime/camera/calibrate/start
POST /api/equipment/utm-runtime/camera/calibrate/stop
GET  /api/equipment/utm-runtime/camera/calibrate/status
```

기존 API 확장:

```text
POST /api/equipment/utm-runtime/start
GET  /api/equipment/utm-runtime/frame
GET  /api/equipment/utm-runtime/graph
```

### 4.1 `camera/devices`

실행 명령:

```bash
v4l2-ctl --list-devices
v4l2-ctl --list-formats-ext -d <device>
v4l2-ctl --list-ctrls -d <device>
```

반환:

```json
{
  "ok": true,
  "devices": [
    {
      "label": "<OS-discovered physical camera name>",
      "device_path": "/dev/video0",
      "by_id_path": "/dev/v4l/by-id/...",
      "formats": [],
      "controls": {
        "brightness": {"min": 0, "max": 255, "default": 128},
        "gain": {"min": 0, "max": 255, "default": 0}
      },
      "recommended": true
    }
  ]
}
```

### 4.2 `camera-config`

GET은 기본 config와 memory override를 병합해서 반환한다.

POST는 user override 파일만 갱신한다. `configs/devices.yaml`은 runtime 기본값으로 유지한다.

### 4.3 `camera/probe`

probe source:

```text
source=direct_v4l2
source=ros_raw_topic
source=ros_rectified_topic
source=ros_utm_topic
```

Direct probe는 selected Camera device에서 1 frame을 캡처한다. ROS probe는 현재 `/api/equipment/utm-runtime/frame`의 ROS subscriber 경로를 재사용한다.

반환:

```json
{
  "ok": true,
  "source": "direct_v4l2",
  "device_path": "/dev/v4l/by-id/...",
  "width": 640,
  "height": 480,
  "fps_requested": 30,
  "encoding": "YUYV",
  "frame_available": true,
  "data_url": "data:image/jpeg;base64,...",
  "applied_controls": {
    "brightness": 128,
    "gain": -1
  }
}
```

### 4.4 `camera/calibrate/*`

체커보드 기반 calibration은 ROS Jazzy의 `camera_calibration` package를 기본 앱으로 사용한다.

필수 패키지:

```bash
sudo apt install -y ros-jazzy-camera-calibration ros-jazzy-camera-calibration-parsers
```

GUI 동작:

```text
Calibrate 버튼
  -> 저장된 Camera config 확인
  -> UTM runtime 또는 raw camera topic 준비
  -> camera_calibration GUI subprocess 실행
  -> browser page에는 process status, command preview, calibration file path 표시
```

기본 command 예시:

```bash
source /opt/ros/jazzy/setup.bash
source /home/jin/external_repos/UTM/install/setup.bash
ros2 run camera_calibration cameracalibrator \
  --size 8x6 \
  --square 0.024 \
  image:=/camera/image_raw \
  camera:=/camera
```

checkerboard size/square size는 GUI에서 바꿀 수 있어야 한다. 기본값은 `8x6`, `0.024 m`로 두되, 사용자가 실제 체커보드에 맞게 저장할 수 있어야 한다.

Calibration 결과는 ROS camera info YAML로 저장한다.

```text
memory/device_bridge/calibration/utm_camera_default_cam.yaml
```

저장된 calibration file은 다음 runtime start부터 `camera_rect.launch.py camera_info_url:=file://...`로 주입한다.


## 5. UTM Runtime Start에 카메라 설정 반영

현재 UTM clone script는 다음 흐름이다.

```text
start_utm_vision_stack.sh
  -> camera_rect.launch.py pixel_format:=yuyv2rgb
  -> green_dot_monitor.launch.py input_image_topic:=/camera/image_rect output_image_topic:=/image_utm
  -> yolo_bringup yolov8.launch.py input_image_topic:=/image_utm
```

`camera_rect.launch.py`는 이미 다음 launch arguments를 갖고 있다.

```text
video_device
image_width
image_height
framerate
brightness
gain
pixel_format
camera_info_url
```

따라서 권장 구현은 UTM script에 env override를 추가하는 것이다.

예시:

```bash
CAMERA_DEVICE="${UTM_CAMERA_DEVICE:-/dev/v4l/by-id/...detected-camera...}"
CAMERA_WIDTH="${UTM_CAMERA_WIDTH:-640}"
CAMERA_HEIGHT="${UTM_CAMERA_HEIGHT:-480}"
CAMERA_FPS="${UTM_CAMERA_FPS:-30.0}"
CAMERA_BRIGHTNESS="${UTM_CAMERA_BRIGHTNESS:-128}"
CAMERA_GAIN="${UTM_CAMERA_GAIN:--1}"
CAMERA_PIXEL_FORMAT="${UTM_CAMERA_PIXEL_FORMAT:-yuyv2rgb}"
CAMERA_INFO_URL="${UTM_CAMERA_INFO_URL:-file://$HOME/.ros/camera_info/default_cam.yaml}"

ros2 launch compression_tester_monitor camera_rect.launch.py \
  video_device:="$CAMERA_DEVICE" \
  image_width:="$CAMERA_WIDTH" \
  image_height:="$CAMERA_HEIGHT" \
  framerate:="$CAMERA_FPS" \
  brightness:="$CAMERA_BRIGHTNESS" \
  gain:="$CAMERA_GAIN" \
  pixel_format:="$CAMERA_PIXEL_FORMAT" \
  camera_info_url:="$CAMERA_INFO_URL"
```

ATR bridge는 memory override에서 값을 읽어 다음 env를 넘긴다.

```text
UTM_CAMERA_DEVICE
UTM_CAMERA_WIDTH
UTM_CAMERA_HEIGHT
UTM_CAMERA_FPS
UTM_CAMERA_BRIGHTNESS
UTM_CAMERA_GAIN
UTM_CAMERA_PIXEL_FORMAT
UTM_CAMERA_INFO_URL
```

Exposure는 `camera_rect.launch.py`에 현재 argument가 없으므로 두 단계로 처리한다.

1. `v4l2-ctl --set-ctrl=exposure_auto=...` / `exposure_absolute=...`가 지원되면 runtime start 전에 적용한다.
2. 지원하지 않으면 GUI에 `unsupported by selected device`로 표시하고 저장은 하되 적용 결과에 warning을 남긴다.

## 6. Live GUI Vision Agent Dashboard 설계

Reference screenshot과 유사하게 card grid를 구성하되, defect inspection 용어는 ATR UTM 실험 용어로 바꾼다.

### 6.1 상단 카드

#### Camera Health

표시 항목:

```text
camera label
device path
resolution
fps
brightness
exposure
gain
frame age
health status
```

#### Calibration / Topic Summary

표시 항목:

```text
calibration_id
/camera/image_raw
/camera/image_rect
/image_utm
/compression_tester/summary
topic age
actual ROS node count
```

#### Detection Confidence Distribution

표시 항목:

```text
green marker confidence
YOLO detection confidence
agent signal confidence histogram
stale/low-confidence count
```

#### Operator Review / Evidence

표시 항목:

```text
review status
blocking reason
key evidence frames
annotated frame path
detection json path
handoff recommendation
```

### 6.2 중앙 카드

#### Live Inspection Feed

source priority:

```text
1. /image_utm
2. /yolo/dbg_image
3. /compression_tester/debug_image
4. /camera/image_rect
5. /camera/image_raw
```

프레임이 있으면 image preview를 표시한다. 프레임이 없으면 다음처럼 표시한다.

```text
Frame unavailable
topic attempted: /image_utm -> /yolo/dbg_image -> ...
failure: ROS_IMAGE_TIMEOUT
next action: Open Vision / UTM Camera Bridge and run Probe
```

#### Detection / Segmentation

표시 항목:

```text
green marker bbox
UTM state: idle / working / complete / unknown
marker span y
working height threshold
YOLO object count
```

#### UTM State Summary

표시 항목:

```text
/compression_tester/summary latest state
stable_state
transition_count
working_duration
complete_detected
```

### 6.3 하단 카드

#### Pose / Alignment

표시 항목:

```text
fixture visible
specimen visible
alignment confidence
estimated center offset
```

#### Signal Confusion / Validation Matrix

실제 confusion matrix가 없으면 임의 matrix를 만들지 않는다. 대신 signal gate matrix를 표시한다.

```text
pre_start
motion_confirm
test_complete
frame_available
summary_fresh
confidence_ok
```

#### Quality Metrics

표시 항목:

```text
frame freshness
marker stability
topic readiness
handoff readiness
vision_gate_status
```

#### Visual Checkpoint Timeline

표시 항목:

```text
runtime loaded
camera frame received
rectified frame received
green-dot monitor active
yolo active
summary updated
equipment handoff
analysis handoff
```

#### Handoff Recommendations

표시 항목:

```text
Recommended next agent: Manipulation / Lab Equipment / Analysis / Operator Attention
confidence
rationale
required action
```

## 7. Vision Agent Payload 계약

Vision report는 기존 `vision_report.v1`을 유지하되 다음 필드를 추가한다.

```json
{
  "schema": "vision_report.v1",
  "camera_source": {
    "camera_key": "utm_primary",
    "source": "utm_ros_runtime",
    "device_path": "/dev/v4l/by-id/...",
    "frame_id": "frame-...",
    "frame_age_ms": 120,
    "resolution": "640x480",
    "fps": 30,
    "brightness": 128,
    "exposure": "",
    "gain": -1
  },
  "utm_runtime": {
    "status": "running",
    "rqt_source": "cloned_utm_repository",
    "graph_hash": "...",
    "ros2_available": true,
    "topic_seen": true,
    "camera_seen": true
  },
  "inspection_feed": {
    "frame_available": true,
    "topic": "/image_utm",
    "width": 640,
    "height": 480,
    "encoding": "bgr8",
    "failure_code": "",
    "attempts": []
  },
  "utm_state_summary": {
    "latest_state": "WORKING",
    "stable_state": "WORKING",
    "transition_count": 2,
    "summary_age_ms": 350
  },
  "agent_signals": [
    {
      "signal": "utm_motion_observed",
      "status": "ok",
      "confidence": 0.93,
      "expires_at": "..."
    }
  ],
  "handoff_recommendation": {
    "next_agent": "Lab Equipment Agent",
    "confidence": 0.87,
    "rationale": ["summary fresh", "frame available", "marker stable"]
  }
}
```

## 8. Device Bridge와 Live GUI 역할 분리

| Surface | 역할 | 들어갈 내용 | 들어가면 안 되는 내용 |
|---|---|---|---|
| Device Bridge page | 설정/진단/테스트 | camera device, fps, resolution, v4l2 controls, runtime start/stop, direct probe, ROS probe | loop report raw chat |
| Main GUI Device Workspace card | 축약 상태/진입점 | running/stopped, graph hash, frame status, open page button | 상세 report 전체 |
| Live GUI Vision Agent report | 현재 실험 loop 관제 | frame preview, topic readiness, marker/YOLO evidence, handoff recommendation | camera 설정 저장 form |
| Backend trace | 원본 진단 | raw ROS graph, raw command output, frame capture attempts | operator용 요약만 있는 card |

## 9. Test / Live / Virtual 정책

### Test mode

```text
1. 저장된 Camera config가 있으면 실제 camera probe를 먼저 시도한다.
2. ROS runtime이 가능하면 UTM runtime을 loading하고 real observer를 쓴다.
3. camera/ROS가 없으면 virtual UTM bridge로 진행한다.
4. fallback 시 chat/report/backend trace에 fallback reason을 남긴다.
5. loop는 끊지 않는다.
```

### Live mode

```text
1. 저장된 camera config가 없으면 operator attention.
2. camera probe 실패 시 operator attention.
3. frame/summary가 stale이면 Lab Equipment physical completion을 통과시키지 않는다.
4. virtual bridge는 physical completion으로 위장하지 않는다.
5. recovery action은 Device Bridge page open, re-probe, remap, restart runtime 순서로 제공한다.
```

## 10. 구현 단계

### Step 1. Backend config/service

- `UTMCameraConfig` dataclass 추가
- `memory/device_bridge/utm_camera_config.json` load/save
- v4l2 device discovery 함수 추가
- direct frame probe 추가
- UTM runtime command에 camera env injection 추가
- checkerboard calibration subprocess manager 추가
- calibration YAML 저장/로드 및 `camera_info_url` injection 추가

### Step 2. API

- `/api/equipment/utm-runtime/camera-config`
- `/api/equipment/utm-runtime/camera/devices`
- `/api/equipment/utm-runtime/camera/probe`
- `/api/equipment/utm-runtime/camera/apply`
- `/api/equipment/utm-runtime/camera/calibrate/start`
- `/api/equipment/utm-runtime/camera/calibrate/stop`
- `/api/equipment/utm-runtime/camera/calibrate/status`

### Step 3. Device Bridge page

- `/device-bridge/vision-utm` template 추가
- `vision_utm_bridge.js` 또는 기존 `app.js` 분리 module 추가
- camera mapping, controls, probe preview, runtime graph panel 구현
- Calibrate 버튼 추가
- Calibrate 버튼은 browser 안에 상태 panel을 띄우고, 실제 calibration GUI는 ROS `camera_calibration` subprocess window로 띄운다.

### Step 4. Main GUI link

- Device Workspace에 `Vision / UTM Camera Bridge` card 추가
- 기존 `UTM ROS System` card에는 runtime 상태와 open page 링크만 남긴다.

### Step 5. Live GUI Vision report

- `renderVisionDashboardCards`를 reference style grid로 강화
- `renderVisionReportDetails`는 raw table 중심에서 operator-readable summary 중심으로 정리
- `/api/equipment/utm-runtime/frame` preview를 Vision report에서 사용
- frame unavailable reason과 next action 표기

### Step 6. Agent payload

- VisionAgent output에 `camera_source`, `utm_runtime`, `inspection_feed`, `utm_state_summary`, `handoff_recommendation` 추가
- EquipmentAgent가 Vision cross-check를 받을 때 frame ids와 freshness를 보존
- KnowledgeAgent가 vision evidence summary를 memory에 남길 수 있게 handoff packet에 포함

### Step 7. Tests

단위 테스트:

```text
tests/unit/test_utm_camera_config.py
tests/unit/test_utm_camera_device_discovery.py
tests/unit/test_utm_runtime_camera_env.py
tests/unit/test_utm_camera_calibration_command.py
tests/unit/test_vision_report_utm_dashboard_payload.py
```

통합 테스트:

```text
tests/integration/test_utm_camera_bridge_api.py
tests/integration/test_utm_camera_calibration_api.py
tests/integration/test_live_gui_vision_report_utm_payload.py
```

브라우저/육안 테스트:

```text
tests/ui/vision_utm_bridge_browser_audit.py
tests/ui/live_gui_vision_dashboard_browser_audit.py
```

필수 screenshot artifact:

```text
artifacts/browser_checks/vision_utm_device_bridge_page.png
artifacts/browser_checks/live_gui_vision_agent_inspection_dashboard.png
artifacts/browser_checks/live_gui_vision_agent_frame_unavailable_state.png
```

## 11. Definition of Done

완료 조건:

1. Main GUI에서 `Vision / UTM Camera Bridge` page가 실제 링크로 열린다.
2. Camera device discovery가 `/dev/v4l/by-id` 기준으로 표시되고, 발견된 물리 카메라 이름은 후보 label로만 표시된다.
3. resolution/fps/brightness/gain 설정을 저장하고 재접속 후 유지한다.
4. 기본값은 clone된 UTM `camera_rect.launch.py`와 같은 `640x480 @ 30fps`, `yuyv2rgb`, `brightness=128`, `gain=-1`이다.
5. Calibrate 버튼이 ROS `camera_calibration` GUI를 실행하고, status panel이 command/status/calibration file path를 표시한다.
6. calibration YAML이 저장되면 다음 UTM runtime start에 `camera_info_url`로 주입된다.
7. UTM runtime start 시 저장된 camera 설정이 launch/env에 반영된다.
8. direct camera probe 또는 ROS frame probe 중 하나가 성공하면 page에 실제 이미지가 뜬다.
9. 실패 시 frame unavailable reason, attempted topics, next action이 표시된다.
10. Live GUI Vision Agent report가 reference screenshot처럼 multi-card inspection dashboard로 보인다.
11. Vision report에는 raw JSON이 아니라 operator-readable card/graph/list가 보인다.
12. Backend trace에는 raw ROS graph/frame attempts가 남는다.
13. Test mode에서 camera/ROS가 있으면 실제 observer를 쓰고, 없으면 fallback message를 남긴 뒤 virtual bridge로 loop가 계속 돈다.
14. Live mode에서 stale/missing frame을 physical completion으로 통과시키지 않는다.
15. Pytest, JS syntax check, browser screenshot audit가 통과한다.

## 12. 구현 시 주의사항

- UTM clone flow는 유지한다. `usb_cam -> rectify_node -> green_dot_monitor -> yolov8`를 다른 구조로 바꾸지 않는다.
- Camera 설정은 UTM runtime bridge에만 적용한다. LeRobot RealSense camera map과 섞지 않는다.
- GUI에서 값을 임의 생성하지 않는다. 없는 metric은 `No data yet`, `not measured`, `frame unavailable`로 표시한다.
- Live GUI report는 보기 좋게 만들되, 실제 backend source와 연결되지 않은 버튼/숫자는 넣지 않는다.
- 카메라 설정 변경은 runtime 재시작이 필요한지 명확히 표시한다.
- `v4l2-ctl`이 없으면 dependency missing으로 표시하고 `REQUIREMENTS.md`에 설치법을 넣는다.
- `ros-jazzy-camera-calibration`이 없으면 Calibrate 버튼은 disabled 상태로 두고, 설치 명령을 표시한다.
- browser screenshot으로 실제 화면을 확인하기 전에는 완료로 표시하지 않는다.
