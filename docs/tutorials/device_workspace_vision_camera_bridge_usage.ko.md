<!-- atr-doc
doc_type: guide
subtype: tutorial
status: active
authority: procedural
audience: [user, operator, researcher]
scope: [gui_tutorial, operator_workflow]
summary: Camera configuration, frame freshness, pose diagnostics and run-bound verification walkthrough.
source_of_truth:
  - web/templates/vision_utm_device_bridge.html
  - web/static/vision_utm_device_bridge.js
  - app/main.py
last_verified: 2026-09-29
verified_against: fcfba9f
related_docs:
  - docs/gui/visual_structure.md
  - docs/runtime/test_mode.md
supersedes: []
-->

# 비전 실습 — 카메라 설정과 근거 확인

[English](device_workspace_vision_camera_bridge_usage.en.md) · [튜토리얼 목차](first_autonomous_run.md)

## 목표와 준비

UTM 카메라를 설정하고 최신 프레임을 확인한 뒤, 워크스페이스의 pose test와
런의 Vision 판정을 구분하는 실습입니다. ROS/UTM 구성과 올바른 카메라가
필요합니다. ROS 시작·종료나 카메라 해제 전에는 사용 중인 운영자와 조율합니다.

**Main → Device Workspaces → Vision** 또는 `/device-bridge/vision-utm`을 엽니다.
그림은 2026-09-29의 1920 × 1080 읽기 전용 캡처입니다. 문서 촬영을 위해
카메라 촬영·ROS 명령·설정 저장은 실행하지 않았습니다.
공란은 실제 미조회 상태이며 설정 성공 예시가 아닙니다.

## Step 1 — 현재 카메라 설정 읽기

1. **Runtime Bridge**를 선택합니다.
2. **Load Config**로 저장 설정을 읽습니다.
3. **Camera Profile**의 device path·해상도·camera FPS·pixel format을 봅니다.
4. 변경 전에 runtime/status 안내를 확인합니다.

![Runtime Bridge와 카메라 설정](../gui/assets/screenshots/2026-09-29/device-bridge-vision-utm.png)

**확인:** 저장된 프로필이 표시됩니다. 빈 입력란이나 예전에 찍힌 그림만 보고
장치가 맞다고 판단하지 않습니다.
UTM 카메라 설정은 LeRobot top/wrist 카메라 설정과 별개입니다.

## Step 2 — 실제 장치 선택과 저장

1. 설정이 필요하면 **Detect Devices**를 누릅니다.
2. **Detected Cameras**에서 의도한 장치를 선택하고 **Device path**를 봅니다.
3. 해당 장치가 지원하는 해상도·camera FPS·pixel format을 입력합니다.
4. **Apply Camera → Load Config**로 저장값을 확인합니다.

**확인:** 다시 읽어도 같은 장치·프로필입니다.
저장 위치는 로컬 `memory/device_bridge/utm_camera_config.json`입니다.
다른 컴퓨터 경로나 스크린샷의 serial을 복사하지 않습니다.
지원 설정·의존성은 [UTM Vision Bridge](../device_bridges/utm_vision_bridge.md)를 봅니다.

## Step 3 — UTM ROS 런타임 확인하기

1. 변경하려는 런타임에 진행 중인 실험이 의존하고 있지 않은지 확인합니다.
2. 시작이 필요하면 **ROS Loading**을 사용합니다.
3. **Pre Start Check**를 누르고 **Bridge Result**를 읽습니다.
4. 선택 카메라·ROS/프레임 근거·실패 상세를 확인합니다.

![Live Frame Evidence와 ROS 그래프 영역](assets/screenshots/2026-09-29/vision-frame.png)

**확인:** 맞는 출처의 최신 프레임과 사용할 수 있는 런타임 근거가 나옵니다.
이 캡처는 일부러 미촬영 상태를 유지했으므로 ROS/카메라 성공 증거가 아닙니다.
그래프 이미지나 프로세스 로딩 표시만으로 충분하지 않습니다.
**ROS Unloading**, **Release Camera Ports**는 자원 점유를 바꾸는 기능입니다.
실행 중인 런에서 화면 갱신 목적으로 누르지 않습니다.

## Step 4 — 프리뷰와 카메라 FPS 구분하기

1. **Live Frame Evidence → Preview FPS**를 지정합니다.
2. **Play Live**를 누릅니다.
3. 이미지가 변하고 상태·근거가 최신인지 확인합니다.
4. 관찰이 끝나면 **Stop Live**를 누릅니다.

**확인:** 설정 topic의 최신 프리뷰입니다.
Preview FPS는 브라우저 전송 요청 속도이지 카메라 획득 속도를 올리는 설정이
아닙니다. 느리면 preview 숫자부터 올리지 말고 원본/frame 최신성을 비교합니다.
소스 자체가 느리면 카메라·USB·ROS를 확인합니다.
[UTM ROS 브릿지](../hardware/utm_ros_vision_runtime_bridge.md)를 참고합니다.

## Step 5 — Pose 진단의 목적 구분하기

**Specimen Pose Test** 탭을 선택합니다.

![서로 다른 출처를 사용하는 pose 진단](assets/screenshots/2026-09-29/vision-pose.png)

1. **Load Pose Status**로 tracker/camera lease 상태를 읽습니다.
2. 카메라 없는 계약 검사는 **Virtual Pose Test**를 사용합니다.
3. 감독하의 **Live D455F Snapshot**은 설정된 D455F topic을 사용합니다.
4. **D405 Smoke Snapshot**은 별도의 하드웨어 경로 진단입니다.
5. **Snapshot Payload**, **Pose Summary**, **Pose API Result**를 함께 봅니다.

**확인:** 결과의 source/mode와 specimen이 식별됩니다.
가상 통과는 실제 장면 검출 증거가 아닙니다. D405 smoke test도 루프가 정한
카메라의 대체 판정이 아닙니다.
**Release VLA Camera**는 소유 세션을 방해할 수 있으므로 인퍼런스 중 단순히
이 화면에 결과가 없다는 이유로 누르지 않습니다.

## Step 6 — 실제 런의 verification 확인하기

Live의 **VIS → Report**로 돌아갑니다.

![Vision Agent 관측과 검증 리포트](../gui/assets/screenshots/2026-09-29/live-vision.png)

run/cycle, Active Cam 또는 verification slot, 촬영 이미지, ROI, 판정 근거를
확인합니다. 이미지 수신과 LLM 판정 완료 시점은 다릅니다.
사진이 표시됐다고 verification 통과는 아닙니다.

**확인:** 필요한 단계의 최신 런 귀속 사진과 대응 판정이 있습니다.
워크스페이스 진단이 그 단계를 완료 처리하지 않습니다.
카메라가 움직였다면 기존 ROI에 물리 화면을 다시 맞추거나 검토된 보정 변경
절차를 따릅니다. 통과시키려고 임계값만 바꾸지 않습니다.
[Vision Agent](../agents/vision_agent.md)를 참고합니다.

## Step 7 — 필요할 때만 보정하기

1. 실제 checkerboard를 준비하고 한 칸 크기를 m로 측정합니다.
2. **Checkerboard size**, **Square size m**, 보정 파일을 입력합니다.
3. 카메라 사용 가능한 점검 시간에만 **Calibrate**를 실행합니다.
4. 보정 결과를 확인하고 **Stop Calibrate**로 해당 보정 세션을 닫습니다.

**확인:** 그 카메라·보드의 보정 근거가 생성됩니다. 파일 경로만 적혀 있는
것으로 충분하지 않습니다. 9×6 같은 placeholder를 실제 보드 규격으로
오해하지 않습니다. 평소 페이지를 열 때마다 정상 실험을 재보정하지 않습니다.

## 문제 해결과 완료

| 증상 | 먼저 확인 |
|---|---|
| 장치 없음 | OS/USB 연결·권한·Detect Devices 응답 |
| 프레임 공란 | 카메라 선택·runtime·topic·Pre Start Check |
| 오래된 사진 | 픽셀만 보지 말고 capture/frame 시각과 source |
| 카메라 busy | 현재 owner/lease, 해제 전 조율 |
| 느린 프리뷰 | 원본 획득/ROS 속도와 preview 전송 속도 구분 |
| Pose는 통과했지만 VIS 대기 | test mode/source와 필요한 런 검증 구분 |

본인 환경에서 설정 저장과 승인된 최신 프레임을 확인해야 실습 완료입니다.
이 문서의 캡처가 그 확인을 대신하지 않습니다.
이후 [운영자 실습](user_manual.ko.md)으로 이어갑니다.
