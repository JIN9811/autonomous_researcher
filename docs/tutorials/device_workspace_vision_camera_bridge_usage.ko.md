# Vision / UTM Camera Bridge 사용법

이 페이지는 Vision Agent가 UTM ROS runtime에서 사용할 Camera를 설정하고 검증하는 운영자 화면입니다. 특정 카메라 제품명을 bridge 이름으로 쓰지 않습니다. 실제 물리 장치명은 `/dev/v4l/by-id` 탐색 결과 label로만 표시됩니다.

## 접속

Main GUI의 `Device Workspaces`에서 `Vision / UTM Camera Bridge`를 누르거나 아래 주소로 직접 접속합니다.

```text
/device-bridge/vision-utm
```

## 기본 동작

- 기본 영상 설정은 UTM clone flow 기준 `640x480 @ 15fps`, `yuyv2rgb`, `brightness=128`, `gain=-1`입니다.
- 장치 path는 기본으로 고정하지 않습니다.
- `Detect Devices`를 눌러 OS가 인식한 Camera 후보를 확인합니다.
- 후보를 클릭하면 `Device path` 입력칸에 들어갑니다.
- `Apply Camera`를 누르면 `memory/device_bridge/utm_camera_config.json`에 저장됩니다.
- 이후 `ROS Loading` 또는 Live/Test loop가 UTM runtime을 시작할 때 저장된 `UTM_CAMERA_*` 환경변수가 주입됩니다.
- `ROS Loading`은 runtime 시작 직전에 `v4l2-ctl --set-ctrl=exposure_dynamic_framerate=0`을 best-effort로 적용합니다. 카메라가 해당 컨트롤을 지원하지 않으면 경고만 남기고 시작은 계속됩니다.

## 프레임 속도 기준

- 정상 기준은 `/image_utm` MJPEG route에서 약 15fps입니다.
- 프레임이 느려지면 먼저 `/camera/image_raw` FPS를 확인합니다. 여기서 이미 낮으면 GUI 렌더링 문제가 아니라 카메라/V4L2/USB 입력 문제입니다.
- 이 워크스테이션에서는 `mjpeg2rgb` 경로가 장시간 스트리밍 중 1-4fps로 떨어졌고, `yuyv2rgb`로 복구한 뒤 `457 frames / 30.1 s` 수준으로 회복됐습니다.
- saved profile에서 `pixel_format=mjpeg2rgb`가 보이면 일반 운용 전 `yuyv2rgb`로 되돌립니다.

## 버튼 의미

| 버튼 | 의미 |
|---|---|
| `Load Config` | 저장된 Camera 설정을 다시 읽습니다. |
| `Detect Devices` | `/dev/v4l/by-id` 기준으로 V4L2 Camera 후보를 나열합니다. |
| `Apply Camera` | 현재 입력값을 `memory/device_bridge/utm_camera_config.json`에 저장합니다. |
| `Pre Start Check` | 설정, 장치 탐색, ROS graph, direct camera/ROS frame evidence를 한 번에 확인합니다. 통신 중에는 버튼이 잠깁니다. |
| `ROS Loading` | UTM ROS runtime을 시작합니다. |
| `ROS Unloading` | UTM ROS runtime을 종료합니다. |
| `Calibrate` | ROS `camera_calibration` checkerboard GUI를 실행합니다. |
| `Stop Calibrate` | 실행 중인 calibration GUI를 종료합니다. |

## 캘리브레이션

필수 패키지:

```bash
sudo apt install -y ros-jazzy-camera-calibration ros-jazzy-camera-calibration-parsers
```

GUI의 `Calibrate` 버튼은 아래 형식의 ROS 명령을 backend에서 실행합니다.

```bash
ros2 run camera_calibration cameracalibrator --size 9x6 --square 0.021 image:=/camera/image_raw camera:=/camera
```

저장된 calibration YAML은 다음 UTM runtime start 때 `UTM_CAMERA_INFO_URL=file://...`로 주입됩니다.

## 검증 기준

- Main GUI에서 `Open Camera Bridge`가 실제로 열려야 합니다.
- Camera Bridge 페이지는 저장된 설정과 runtime/calibration 상태를 표시해야 합니다.
- `Pre Start Check` 중 버튼이 비활성화되고, callback 후 다시 활성화되어야 합니다.
- 물리 Camera가 없으면 `frame unavailable` 계열 failure code를 표시해야 하며, 성공으로 위장하지 않습니다.
- 물리 Camera가 있으면 direct V4L2 frame 또는 ROS image topic frame 중 하나가 evidence로 표시되어야 합니다.

## 관련 문서

- `docs/hardware/utm_ros_vision_runtime_bridge.md`
- `개선안/16_utm_ros_runtime_bridge_live_gui_plan.md`
- `개선안/17_vision_agent_camera_device_bridge_live_gui_plan.md`
