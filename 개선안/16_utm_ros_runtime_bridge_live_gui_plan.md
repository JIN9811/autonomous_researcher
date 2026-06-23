# 16. UTM ROS Vision Runtime Bridge + Live GUI Card Upgrade Plan

작성일: 2026-06-22
대상 코드: `device_bridges/`, `mcp_tools/camera_tools.py`, `app/bootstrap.py`, `app/main.py`, `configs/devices.yaml`, `web/templates/*`, `web/static/*`, `agents/equipment_agent.py`, `agents/vision_agent.py`, `docs/hardware/*`, `REQUIREMENTS.md`
외부 기준 repo: `/home/jin/external_repos/UTM` (`https://github.com/hylee12345/UTM`)

## 0. 현재 구현 상태

이 문서는 계획 문서이면서 현재 구현 기준을 같이 고정한다. 2026-06-22 기준으로 ATR backend에는 UTM ROS runtime bridge가 추가되어 있고, RQT-like 내부 흐름은 임의 그림이 아니라 클론해 둔 UTM 프로그램의 실제 launch/script 흐름을 따른다.

expected graph 기준 파일:

```text
/home/jin/external_repos/UTM/scripts/start_utm_vision_stack.sh
/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/camera_rect.launch.py
/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/green_dot_monitor.launch.py
/home/jin/external_repos/UTM/scripts/yolo.sh
```

현재 구현된 expected RQT-like flow:

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

compression_tester_monitor/green_dot_monitor
  -> /compression_tester/state
  -> /compression_tester/summary
  -> /compression_tester/metrics
  -> /compression_tester/green_points
  -> /compression_tester/debug_image
```

actual graph는 runtime에서 다음 명령으로 읽는다.

```bash
ros2 node list
ros2 topic list
ros2 node info <node>
```

따라서 UTM repo의 launch/topic/remap이 바뀌면 expected graph는 위 파일 기준으로 갱신하고, 실제 실행 중인 node/topic 차이는 `/api/equipment/utm-runtime/graph`의 actual graph와 diagnostics로 표시한다.

구현 파일:

```text
device_bridges/utm_runtime_bridge.py
device_bridges/utm_state_observer.py
mcp_tools/camera_tools.py
app/bootstrap.py
app/main.py
configs/devices.yaml
web/templates/index.html
web/static/app.js
web/static/planning.js
```

검증 artifact:

```text
artifacts/browser_checks/utm_runtime_main_gui_flow.png
artifacts/browser_checks/utm_runtime_main_gui_frame_probe.png
artifacts/browser_checks/utm_runtime_live_gui_flow_compact.png
artifacts/browser_checks/utm_live_gui_test_mode_fullpath_summary.json
```

`utm_live_gui_test_mode_fullpath_summary.json`은 Live GUI `테스트 모드, 가상 브릿지` 경로가 5-cycle closed loop를 끝까지 돈 결과를 저장한다. 이 artifact의 기준 성공 조건은 `workflow_complete=true`, `stage=complete`, `loop_count=5`, 그리고 Design/Specimen/Vision/Manipulation/Lab Equipment/Analysis/Knowledge/BO/Guardian 메시지가 모두 존재하는 것이다.

현재 제한:

- `/api/equipment/utm-runtime/frame`은 실제 ROS image topic subscriber를 subprocess로 띄워 `/image_utm`, `/yolo/dbg_image`, `/compression_tester/debug_image`, `/camera/image_rect`, `/camera/image_raw` 순서로 1프레임을 캡처한다. frame이 있으면 JPEG data URL을 반환하고, 없으면 topic별 timeout/import/encoding failure evidence를 반환한다.
- local preflight 당시 `/dev/video*`가 없어 `usb_cam`이 물리 카메라를 열지 못했다. ROS/Jazzy/yolo_ros/UTM workspace 경로 자체는 연결되어 있다.
- Live GUI는 status/graph/frame state를 compact card로 표시한다. 실제 이미지 preview는 Main Device Workspace의 UTM ROS System card에서 Probe/Loading 후 확인한다.

## 1. 결론

UTM repo는 ATR에 그대로 덮어쓰는 패키지가 아니라, ATR의 existing device bridge / MCP tool / EquipmentAgent / Live GUI 구조에 맞춰 병합해야 하는 ROS Vision Runtime provider다.

핵심 방향은 다음이다.

```text
Device Workspace UTM ROS Runtime
  -> ROS2 Jazzy stack loading/unloading
  -> UTM start_utm_vision_stack.sh
  -> usb_cam + image_proc/rectify_node + green_dot_monitor + yolo_bringup/yolov8
  -> /compression_tester/summary time-window observer
  -> vision.equipment_cross_check
  -> EquipmentAgent UTM pre-start/motion/complete evidence
  -> AnalysisAgent UTM CSV / CalculiX / BO loop
```

중요한 정책 변경:

```text
기존 UTM package 문구: insufficient evidence -> fail closed
ATR 적용 정책: try-to-work first
  1. ROS runtime이 꺼져 있으면 자동 Loading
  2. topic/camera가 없으면 dependency/port/workspace 진단
  3. test mode에서는 실제 카메라가 있으면 실제 ROS observer로 test
  4. test mode에서 카메라/ROS가 없으면 improved virtual UTM bridge로 진행
  5. live mode에서는 virtual completion을 물리 완료로 위장하지 않고 operator attention + recovery action으로 표기
```

즉 `fail closed`라는 사용자 경험을 없애되, live 물리 완료를 가짜로 통과시키지는 않는다. Live에서는 자동 로딩, 재시도, 진단, operator attention으로 해결 경로를 제시하고, Test에서는 virtual bridge까지 내려가서 loop가 계속 돈다.

## 2. 현재 ATR과 맞는 부분

UTM repo의 핵심 계약은 현재 ATR과 잘 맞는다.

| UTM repo 요소 | ATR 기존 요소 | 판단 |
|---|---|---|
| `vision.equipment_cross_check` | 현재 `mcp_tools/camera_tools.py`에 이미 등록됨 | 이름/호출 위치 일치 |
| `utm_pre_start` | EquipmentAgent의 UTM precondition | 일치 |
| `utm_motion_confirm` | EquipmentAgent의 physical motion cross-check | 일치 |
| `utm_test_complete` | UTM CSV/export handoff gate | 일치 |
| `/compression_tester/summary` time-window sampling | Vision/equipment evidence gate | 적합 |
| `UTMRuntimeProcessManager` | ATR device bridge process manager 패턴 | 적합 |
| `GET/POST /api/equipment/utm-runtime/*` | Device Workspace card/API 패턴 | 적합 |

따라서 구현은 agent 본체를 크게 갈아엎지 않고, bridge/tool/runtime API/UI를 추가하는 방식이 맞다.

## 3. 그대로 쓰면 안 되는 부분

1. `autonomous_researcher_required_files/app/bootstrap.py`, `app/main.py`는 과거 ATR snapshot이다. 현재 ATR의 OpenAI fallback, vLLM/NemoClaw, Bambu, LeRobot, Runtime IDE, CalculiX/PINN 구조를 덮어쓸 수 있으므로 절대 wholesale copy 금지.
2. UTM repo 기본 경로는 `/home/lee-junyoung/yolo_ros_ws/UTM_VISION`이다. ATR에서는 `configs/devices.yaml` + environment override 방식으로 바꿔야 한다.
3. UTM repo는 `fail closed` 용어를 사용하지만, ATR UX에서는 `auto-start`, `diagnose`, `virtual test fallback`, `operator attention`으로 표기해야 한다.
4. UTM repo의 web template은 현재 ATR main GUI/Device Workspace 구조와 다르다. 버튼과 상태 카드만 현재 UI로 흡수해야 한다.
5. `camera.capture`는 ATR의 RealSense/LeRobot camera path를 대체하지 않는다. UTM runtime은 UTM 장비 상태 cross-check provider로만 붙인다.

## 4. Runtime 정책

### 4.1 Loading

Device Workspace에 `UTM ROS System` bridge card를 추가한다.

필수 버튼:

```text
Loading    -> POST /api/equipment/utm-runtime/start
Unloading  -> POST /api/equipment/utm-runtime/stop
Status     -> GET  /api/equipment/utm-runtime/status
Probe      -> POST /api/equipment/utm-runtime/probe
```

Loading 동작:

```text
1. 이미 실행 중인지 확인
2. ROS2/Jazzy command 존재 확인
3. UTM workspace/script 존재 확인
4. start_utm_vision_stack.sh process group 실행
5. log file 생성
6. topic readiness probe
7. Live GUI/Device Workspace에 camera/topic/observer 상태 반영
```

Unloading 동작:

```text
1. managed process group SIGTERM
2. timeout 후 SIGKILL
3. camera/topic probe 중지
4. status stopped 기록
5. log tail 표시
```

### 4.2 자동 기동

다음 상황에서는 runtime을 자동 Loading한다.

```text
- Main GUI test mode에서 UTM 관련 loop가 시작됨
- Live GUI test mode에서 UTM/equipment 단계 진입
- Live mode에서 UTM equipment protocol preflight 진입
- 사용자가 `UTM 모니터링`, `UTM 테스트`, `장비 상태 확인` 등 UTM check를 요청
```

자동 Loading은 idempotent해야 한다. 이미 running이면 재시작하지 않고 status/probe만 갱신한다.

### 4.3 Test mode fallback

Test mode 우선순위:

```text
1. ROS runtime already running or startable + camera/topic valid
   -> real ROS observer test
2. ROS startable but no valid markers/topic timeout
   -> virtual UTM bridge with explicit source=`virtual_utm_bridge`
3. ROS not installed/workspace missing
   -> virtual UTM bridge + dependency action hint
```

이 정책은 test loop가 끊기지 않게 한다. 단, 결과 payload에는 반드시 `source`, `runtime_mode`, `observer_mode`, `virtualized=true/false`를 남겨야 한다.

Fallback이 발생하면 조용히 넘어가지 않는다. 모든 fallback은 operator-visible message와 backend event를 남겨야 한다.

필수 fallback trace:

```text
event_type: utm.runtime.fallback
severity: info | warning
from_observer_mode: ros_topic
to_observer_mode: virtual_utm_bridge
reason_code: ROS2_NOT_INSTALLED | UTM_WORKSPACE_MISSING | TOPIC_TIMEOUT | MARKER_EVIDENCE_STALE | CAMERA_FRAME_UNAVAILABLE
message: human-readable one-line message shown in Live GUI chat/report
diagnostics_ref: path or id for full probe result
```

Live GUI 표기 예:

```text
Lab Equipment Agent
UTM ROS topic evidence was not available within 5.0 s, so this test-mode loop is continuing with the virtual UTM bridge. Live physical completion is not claimed.
```

### 4.4 Live mode behavior

Live mode에서는 카메라/ROS가 없을 때 virtual bridge로 물리 완료를 만들면 안 된다.

Live 우선순위:

```text
1. ROS runtime 자동 Loading
2. topic/camera/marker probe
3. valid evidence가 있으면 EquipmentAgent에 verified evidence 전달
4. evidence가 부족하면 operator attention card에 원인과 복구 버튼 제공
5. 사용자가 명시적으로 simulator/test transport를 선택하지 않는 한 live physical completion은 보류
```

표기는 `failed closed`가 아니라 다음처럼 한다.

```text
status: attention_required
message: UTM ROS runtime started, but marker/topic evidence is not yet valid.
actions: [Retry probe, Open log, Unload ROS, Use virtual bridge in test mode]
```

## 5. MCP tool 계약

`vision.equipment_cross_check`는 현재 이름을 유지한다.

추가 payload field:

```json
{
  "runtime_mode": "test | live",
  "checks": [{"check_id": "utm_pre_start", "device": "utm"}],
  "auto_start_runtime": true,
  "allow_virtual_bridge_in_test": true,
  "duration_sec": 5.0,
  "sample_interval_sec": 0.2,
  "minimum_samples": 8,
  "required_topic": "/compression_tester/summary"
}
```

추가 response field:

```json
{
  "ok": true,
  "tool": "vision.equipment_cross_check",
  "runtime_mode": "test",
  "observer_mode": "ros_topic | virtual_utm_bridge",
  "runtime_status": {"status": "running", "pid": 1234},
  "results": [],
  "operator_attention": null,
  "diagnostics": {
    "ros2_available": true,
    "workspace_found": true,
    "script_found": true,
    "topic_seen": true,
    "camera_seen": true
  }
}
```

## 6. Improved virtual UTM bridge

현재 test UTM CSV 생성은 유지하되, Vision/equipment cross-check용 virtual bridge를 더 구체화한다.

Virtual bridge가 생성해야 하는 evidence:

```text
- virtual camera frame id
- marker point count >= 2
- span_y time sequence
- NOT_WORKING -> WORKING transition for start/motion
- WORKING -> NOT_WORKING or stable complete for finish
- synthetic UTM CSV path
- source=`virtual_utm_bridge`
```

이렇게 하면 test loop에서 Design -> Specimen -> Vision -> Manipulation -> Equipment -> Analysis -> BO가 끊기지 않는다.

## 7. Ubuntu 24.04 설치 기준

현재 PC는 Ubuntu 24.04.4 LTS (`noble`)다. 공식 ROS 문서 기준으로 ROS 2 Jazzy가 대상이다.

권장 설치 항목:

```bash
sudo apt update
sudo apt install -y software-properties-common curl git
sudo add-apt-repository universe
sudo apt update
sudo apt install -y ros2-apt-source
sudo apt update
sudo apt install -y \
  ros-jazzy-ros-base \
  ros-dev-tools \
  python3-colcon-common-extensions \
  python3-rosdep \
  ros-jazzy-cv-bridge \
  ros-jazzy-image-transport \
  ros-jazzy-vision-msgs \
  ros-jazzy-usb-cam
```

주의:

- 실제 apt package availability는 `atr doctor --utm` 또는 install script에서 `apt-cache policy`로 확인한다.
- `rosdep init`은 이미 설정되어 있으면 재실행하지 않는다.
- UTM workspace는 repo 내부가 아니라 외부 workspace로 둘 수 있게 한다.
- 기본 후보 경로:

```text
/home/jin/external_repos/UTM
/home/jin/yolo_ros_ws/UTM_VISION
~/yolo_ros_ws/UTM_VISION
```

## 8. Device Workspace UI 개선안

### 8.1 Main Device Workspace card

`Device Workspaces`에 새 카드:

```text
UTM ROS System
- status pill: stopped / loading / running / attention / virtual-test
- Loading button
- Unloading button
- Probe button
- Open logs
- Open UTM runtime panel
```

카드는 단순 start/stop이 아니라 다음을 보여준다.

```text
ROS2        installed / missing
Workspace   found / missing
Script      found / missing
Runtime     running pid / stopped
Camera      frame ok / no frame
Topic       /compression_tester/summary fresh / stale
Observer    ros_topic / virtual bridge
```

### 8.2 UTM Runtime panel

전용 panel 또는 Device Workspace 내부 section:

```text
Left: Runtime Control
  - Loading / Unloading
  - Auto-load in test mode toggle
  - Auto-load in live mode toggle
  - Allow virtual bridge in test mode toggle

Center: Live Evidence
  - latest state WORKING/NOT_WORKING
  - span_y trend mini chart
  - marker count
  - topic freshness
  - latest frame/debug image if available

Right: Diagnostics
  - ros2 command
  - script path
  - log tail
  - recovery actions
```

### 8.2.1 RQT-like runtime panel

UTM Runtime panel은 RQT에서 확인하던 화면을 GUI 내부로 끌어와야 한다. 목표는 별도 `rqt_image_view`/`rqt_graph` 창을 사용자가 수동으로 보지 않아도, Device Workspace와 Live GUI에서 같은 camera/debug evidence와 ROS node/topic 흐름을 보는 것이다.

Image panel 권장 구현:

```text
ROS image topics
  /camera/image_rect
  /image_utm
  /yolo/dbg_image
    -> backend topic frame grabber
    -> /api/equipment/utm-runtime/frame?topic=...
    -> browser image/video panel
```

Node-flow panel 권장 구현:

```text
ros2 node list
ros2 topic list
ros2 node info <node>
ros2 topic info <topic>
  -> backend graph snapshot builder
  -> /api/equipment/utm-runtime/graph
  -> browser node/topic graph panel
```

그래프는 장식용 정적 그림이면 안 된다. 실제 runtime 상태를 반영해야 한다. 나중에 UTM ROS stack의 node/topic 이름이나 연결이 바뀌어도 GUI가 고정된 예전 그림을 계속 보여주면 안 된다.

Expected UTM graph 기본값은 클론해 둔 UTM repo의 실제 launch/script 흐름을 따른다. 기준 파일:

```text
/home/jin/external_repos/UTM/scripts/start_utm_vision_stack.sh
/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/camera_rect.launch.py
/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/green_dot_monitor.launch.py
/home/jin/external_repos/UTM/scripts/yolo.sh
/home/jin/external_repos/UTM/src/compression_tester_monitor/README.md
```

Expected UTM graph는 위 파일을 기준으로 한다:

```text
usb_cam_node_exe namespace=/camera name=usb_cam
  -> /camera/image_raw
  -> /camera/camera_info
  -> /camera/set_camera_info

image_proc/rectify_node namespace=/camera name=rectify_node
  /camera/image_raw + /camera/camera_info
  -> /camera/image_rect

compression_tester_monitor/green_dot_monitor name=green_dot_monitor
  /camera/image_rect
  -> /image_utm
  -> /compression_tester/summary
  -> /compression_tester/state
  -> /compression_tester/metrics
  -> /compression_tester/green_points
  -> /compression_tester/debug_image

yolo_bringup/yolov8.launch.py input_image_topic:=/image_utm classes:=0 threshold:=0.7
  /image_utm
  -> /yolo/detections
  -> /yolo/tracking
  -> /yolo/dbg_image
```

`camera_rect`, `green_dot_monitoring`, `utm`, `yolo` 같은 alias 이름은 operator command label로만 표시하고, 실제 graph node는 `ros2 node list`/`ros2 node info`에서 확인된 node name을 우선한다.

실제 graph snapshot에서 누락된 node/topic은 숨기지 말고 `missing`, `stale`, `not_publishing`, `not_subscribed` 같은 상태 badge로 표시한다. 반대로 expected graph에 없던 새 node/topic이 실제 ROS graph에 나타나면 `new_runtime_node`, `new_runtime_topic` badge로 표시하고 그래프에 포함한다. Test mode virtual bridge에서는 실제 ROS graph 대신 `virtual_utm_bridge` node와 synthetic topics를 점선/virtual style로 표시한다.

Graph refresh 규칙:

```text
- `/api/equipment/utm-runtime/graph`는 매 호출마다 `ros2 node/topic` introspection을 다시 수행한다.
- 프론트엔드는 static expected graph만 렌더링하지 않고, backend graph snapshot의 `actual_nodes`, `actual_topics`, `actual_edges`를 source of truth로 사용한다.
- expected graph는 health/diff 기준일 뿐이며 actual graph를 덮어쓰지 않는다.
- expected graph는 반드시 `/home/jin/external_repos/UTM`의 current launch/script/docs에서 유도한다. UTM repo가 업데이트되어 launch topic/remapping이 바뀌면 expected graph도 그 파일을 다시 읽어 갱신한다.
- runtime 중 node/topic 변화가 감지되면 graph revision과 timestamp를 갱신한다.
- node/topic/edge/diff 내용이 이전 snapshot과 같으면 `graph_hash`와 `graph_revision`을 유지하고, 프론트엔드는 그래프를 재렌더링하지 않는다.
- 변경사항이 없을 때는 status text, captured_at, last_checked_at 같은 lightweight field만 갱신한다.
- Live GUI는 active UTM check 중 주기적으로 graph snapshot을 갱신한다.
- 사용자가 Refresh Graph를 누르면 즉시 최신 ROS graph를 다시 조회한다.
- graph snapshot은 run artifact에 저장해 나중에 실제 UTM runtime topology evidence로 재현 가능해야 한다.
```

Graph response 최소 schema:

```json
{
  "ok": true,
  "source": "ros2_introspection",
  "graph_revision": 7,
  "graph_hash": "sha256-of-actual-nodes-topics-edges-and-diff",
  "captured_at": "2026-06-22T00:00:00Z",
  "last_checked_at": "2026-06-22T00:00:05Z",
  "changed": false,
  "actual_nodes": [],
  "actual_topics": [],
  "actual_edges": [],
  "expected_nodes": [],
  "expected_topics": [],
  "diff": {
    "missing_nodes": [],
    "new_nodes": [],
    "missing_topics": [],
    "new_topics": [],
    "stale_topics": []
  }
}
```

GUI 요구사항:

```text
- Topic selector: /camera/image_rect, /image_utm, /yolo/dbg_image
- Refresh snapshot button
- Live polling toggle, default off in idle and on during UTM probe/test
- Frame timestamp, topic name, frame age, resolution 표시
- Node-flow graph: usb_cam -> image_proc/rectify_node -> green_dot_monitor -> yolo_bringup/yolov8 -> ATR observer 흐름 표시
- Graph snapshot timestamp와 stale 여부 표시
- 실제 ROS graph와 expected UTM graph의 차이를 diff badge로 표시
- 새 node/topic이 생기면 자동으로 그래프에 추가하고 `new` badge 표시
- 실제 graph가 바뀌면 graph revision/timestamp 갱신
- `changed=false`이면 기존 graph DOM/canvas/SVG를 유지하고 재렌더링하지 않음
- No frame이면 빈 카드가 아니라 원인 메시지와 recovery action 표시
- Optional external rqt_image_view launch command 표시: rqt_image_view /image_utm
- Optional external rqt_graph launch command 표시: rqt_graph
```

`rqt_image_view`나 `rqt_graph` 자체를 iframe처럼 임베드하는 방식은 X11/Wayland/desktop session 의존성이 크므로 기본 경로로 두지 않는다. 기본은 ROS image topic과 node/topic graph를 backend에서 snapshot으로 변환해 브라우저에 표시하는 RQT-like panel이다. 실제 RQT 명령은 현장 디버깅용 보조 버튼/명령으로 남긴다.

### 8.3 Live GUI card 개선

Live GUI에서 Lab Equipment/UTM 단계는 raw JSON 대신 다음 카드로 표시한다.

```text
UTM Runtime Evidence
- ROS runtime: running/stopped/attention
- Observer mode: ROS topic / virtual test bridge
- Check list: pre-start / motion / completion
- Motion plot: span_y over time
- Marker reliability: valid samples / total samples
- Data handoff: CSV parse / force-displacement ready
- Vision camera: latest /image_utm or /yolo/dbg_image frame, frame age, topic
- Next action: Retry probe / Continue virtual test / Operator attention
```

Report card는 compact 기본값, 펼치면 evidence detail을 보여준다.

Live GUI에서 비전 카메라는 항상 장비 증거와 같은 카드에 들어가야 한다. Lab Equipment Agent가 `utm_pre_start`, `utm_motion_confirm`, `utm_test_complete`를 수행하는 동안, 해당 check의 최신 camera frame 또는 debug frame을 report panel에 표시한다.

표시 규칙:

```text
- ROS observer 사용: /image_utm 우선, 없으면 /camera/image_rect, YOLO check면 /yolo/dbg_image
- virtual bridge 사용: virtual frame placeholder와 `source=virtual_utm_bridge` label 표시
- live mode에서 frame 없음: operator attention으로 표시하고 physical completion은 보류
- test mode에서 frame 없음: fallback message를 남기고 virtual bridge frame으로 계속 진행
```

접힌 상태 예시:

```text
Lab Equipment Agent
UTM motion verified by ROS topic, 24 samples, transition NOT_WORKING_TO_WORKING
```

Attention 상태 예시:

```text
Lab Equipment Agent
UTM ROS runtime loaded, but /compression_tester/summary has no fresh marker evidence. Retry probe or switch test loop to virtual bridge.
```

## 9. 구현 순서

1. `device_bridges/utm_runtime_bridge.py` 추가
2. `device_bridges/utm_state_observer.py` 추가
3. `configs/devices.yaml`에 `utm_vision_runtime` 추가
4. `mcp_tools/camera_tools.py`를 optional observer/virtual bridge aware로 확장
5. `app/bootstrap.py`에서 observer와 runtime manager 주입
6. `app/main.py`에 UTM runtime status/start/stop/probe API 추가
7. Main GUI Device Workspace card 추가
8. Live GUI Lab Equipment/UTM report card 개선
9. `REQUIREMENTS.md`, `docs/hardware/utm_vision_runtime_gui.md`, `docs/runtime/closed_loop_and_pages_reference.md`, `docs/gui/gui.md` 갱신
10. 테스트 추가 및 실행

## 10. 검증 계획

### Unit tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/unit/test_utm_state_observer.py \
  tests/unit/test_camera_tools_utm_runtime.py \
  tests/unit/test_utm_runtime_bridge.py \
  tests/unit/test_utm_runtime_stack_script.py
```

### Integration tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/integration/test_utm_runtime_gui_api.py \
  tests/unit/test_equipment_agent.py \
  tests/unit/test_vision_agent.py
```

### Runtime smoke tests

```bash
curl http://127.0.0.1:7860/api/equipment/utm-runtime/status
curl -X POST http://127.0.0.1:7860/api/equipment/utm-runtime/start
curl -X POST http://127.0.0.1:7860/api/equipment/utm-runtime/probe
curl -X POST http://127.0.0.1:7860/api/equipment/utm-runtime/stop
```

### Browser visual audit

```bash
.venv/bin/python tests/ui/device_workspace_browser_audit.py --target utm-runtime
.venv/bin/python tests/ui/live_gui_runtime_audit.py --scenario test-mode-utm
```

### Full-path browser verification

테스트 모드는 backend unit test로 끝내면 안 된다. 반드시 실제 브라우저를 띄워 백엔드 -> 프론트엔드 -> 브라우저 조작 -> 스크린샷까지 이어지는 full-path 검증을 수행한다.

필수 검증 순서:

```text
1. test server boot
2. browser opens Main GUI
3. Device Workspace에서 UTM ROS System card 확인
4. Loading 클릭
5. backend status/probe API 응답을 프론트엔드가 반영하는지 확인
6. RQT-like image panel과 node-flow graph 또는 virtual frame/virtual graph panel 표시 확인
7. Live GUI로 이동
8. `테스트 모드, 가상 브릿지` 입력 또는 버튼 실행
9. fallback message가 chat/report/event에 남는지 확인
10. Lab Equipment/UTM card에 observer_mode, vision camera, span_y/marker evidence 표시 확인
11. loop가 Equipment -> Analysis -> BO까지 진행되는지 확인
12. browser screenshot 저장
13. DOM assertion + screenshot audit 통과
```

검증 산출물:

```text
artifacts/ui/utm_runtime_device_workspace.png
artifacts/ui/utm_runtime_live_gui_test_mode.png
artifacts/ui/utm_runtime_full_path_audit.json
runs/<run_id>/live_planning_transcript.jsonl
```

### Closed-loop test

```text
Live GUI: "테스트 모드, 가상 브릿지"
Expected:
  - ROS runtime auto-load attempted
  - if camera/topic unavailable, virtual UTM bridge selected
  - fallback message is visible in chat/report and persisted in backend events
  - Live GUI shows virtual frame or latest vision camera panel
  - loop continues through Equipment -> Analysis -> BO
  - Live GUI shows observer_mode=virtual_utm_bridge
```

```text
Live GUI: real/test camera connected
Expected:
  - ROS runtime auto-load
  - topic probe succeeds
  - Live GUI shows real /image_utm or /yolo/dbg_image frame
  - vision.equipment_cross_check uses ros_topic evidence
  - no virtual fallback used
```

## 11. 완료 기준

완료 조건:

```text
1. Device Workspace에서 UTM ROS System Loading/Unloading 가능
2. test/live 진입 시 자동 Loading 동작
3. test mode에서 camera/topic이 있으면 ROS observer 사용
4. test mode에서 camera/topic이 없으면 virtual UTM bridge 사용
5. fallback 시 Live GUI message, backend event, persisted transcript를 남김
6. live mode에서 evidence 부족 시 operator attention + recovery action 표시
7. EquipmentAgent가 같은 `vision.equipment_cross_check` 계약으로 UTM evidence 소비
8. Device Workspace와 Live GUI에 실제 ROS graph 기반 RQT-like node-flow panel 표시
9. Device Workspace와 Live GUI에 RQT-like image panel 또는 virtual frame panel 표시
10. Live GUI에 UTM runtime/evidence card 표시
11. Test mode full-path browser verification이 스크린샷/DOM assertion까지 통과
12. Requirements와 hardware/runtime/gui docs 갱신
13. 기존 Equipment/Vision/UTM 관련 tests 통과
```

## 12. 참고 자료

- ROS 2 Jazzy Ubuntu install: https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html
- ROS 2 Jazzy platform support: https://docs.ros.org/en/jazzy/Installation.html
- yolo_ros Jazzy support and lifecycle nodes: https://github.com/mgonzs13/yolo_ros
- UTM integration repo: https://github.com/hylee12345/UTM
