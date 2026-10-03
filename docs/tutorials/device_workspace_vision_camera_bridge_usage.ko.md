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

[English](device_workspace_vision_camera_bridge_usage.en.md) · [튜토리얼 목차](first_autonomous_run.md) · [한국어 문서 목차](../README.ko.md)

## 목표와 준비

UTM 카메라의 설정이 저장되고 최신 프레임이 들어오는지 확인합니다. 기본 설정
작업은 Step 1~4에서 끝납니다. 그다음 실제 실험의 Vision 판정을 확인하거나,
문제가 있을 때만 자세(pose) 진단과 보정 절차를 선택합니다. 워크스페이스 시험에
성공했다고 실험의 검증 단계가 완료되는 것은 아닙니다.

사용할 카메라와 ROS/UTM 구성이 필요합니다. ROS를 시작·종료하거나 로봇 세션이
쓰는 카메라를 해제하기 전에 운영자와 조율합니다. 다른 세션이 장치를 사용 중이면
새 촬영을 강행하려고 해제 버튼을 누르지 말고 사용 순서를 먼저 정합니다.

**Main → Device Workspaces → Vision** 또는 `/device-bridge/vision-utm`을 엽니다.
그림은 2026-09-29의 1920 × 1080 읽기 전용 캡처입니다. 문서 촬영을 위해
카메라 촬영·ROS 명령·설정 저장은 실행하지 않았습니다.
공란은 실제 미조회 상태이며 설정 성공 예시가 아닙니다.

## Step 1 — 현재 카메라 설정 읽기

설정을 바꿀지 결정하기 전에 저장된 상태부터 읽습니다. UTM 카메라 설정은
LeRobot의 top/wrist 카메라 설정과 별개입니다.

1. **Runtime Bridge**를 선택합니다.
2. **Load Config**로 저장 설정을 읽습니다.
3. **Camera Profile**의 device path·해상도·camera FPS·pixel format을 봅니다.
4. 변경 전에 runtime/status 안내를 확인합니다.

![Runtime Bridge와 카메라 설정](../gui/assets/screenshots/2026-09-29/device-bridge-vision-utm.png)

그림에서 **Runtime Bridge**와 카메라 입력 영역을 찾습니다. 설정을 불러온 뒤
저장된 장치와 촬영 조건을 식별할 수 있어야 합니다. 빈 입력란이나 과거 이미지로
사용할 카메라를 판단하지 않습니다. 이미 올바른 설정이라면 바꾸지 말고 런타임
확인 단계로 진행합니다.

## Step 2 — 실제 장치 선택과 저장

저장 설정이 사용할 카메라와 다를 때만 변경합니다. 탐지된 장치라도 실제 설치
위치와 대조해 선택해야 합니다.

1. 설정이 필요하면 **Detect Devices**를 누릅니다.
2. **Detected Cameras**에서 의도한 장치를 선택하고 **Device path**를 봅니다.
3. 해당 장치가 지원하는 해상도·camera FPS·pixel format을 입력합니다.
4. **Apply Camera → Load Config**로 저장값을 확인합니다.

**Load Config** 후 장치·해상도·FPS·형식을 저장한 값과 대조합니다. 로컬
`memory/device_bridge/utm_camera_config.json`에 저장됩니다. 여기서는 설정
유지를 확인한 것이며 아직 프레임 수신까지 입증한 것은 아닙니다. 다른 컴퓨터의
경로나 스크린샷의 비공개 serial을 복사하지 않습니다. 탐지·저장에 실패하면
[UTM Vision Bridge](../device_bridges/utm_vision_bridge.md)의 지원 설정과 의존성을 확인합니다.

## Step 3 — UTM ROS 런타임 확인하기

이제 저장된 카메라가 필요한 실행 근거를 제공하는지 확인합니다. 설정을 읽는
것만으로 정상 스트림이 열리는 것은 아닙니다.

1. 변경하려는 런타임에 진행 중인 실험이 의존하고 있지 않은지 확인합니다.
2. 시작이 필요하면 **ROS Loading**을 사용합니다.
3. **Pre Start Check**를 누르고 **Bridge Result**를 읽습니다.
4. 선택 카메라·ROS/프레임 근거·실패 상세를 확인합니다.

![Live Frame Evidence와 ROS 그래프 영역](assets/screenshots/2026-09-29/vision-frame.png)

**Bridge Result**에서 카메라 출처, 최신 프레임·런타임 근거와 실패 상세를
읽습니다. 프로세스 로딩 표시나 ROS 그래프만으로 충분하지 않습니다. 그림에는
촬영된 프레임이 없으므로 성공 예시가 아니라 확인 영역의 위치를 찾는 데 씁니다.
**ROS Unloading**과 **Release Camera Ports**는 자원 점유를 바꾸는 기능이지
브라우저 새로고침이 아닙니다. 진행 중인 실험에서 사진 갱신만을 위해 누르지 않습니다.

## Step 4 — 프리뷰와 카메라 FPS 구분하기

저장된 정지 화면이 아니라 현재 프리뷰인지 구분할 수 있도록 스트림을 관찰합니다.

1. **Live Frame Evidence → Preview FPS**를 지정합니다.
2. **Play Live**를 누릅니다.
3. 이미지가 변하고 상태·근거가 최신인지 확인합니다.
4. 관찰이 끝나면 **Stop Live**를 누릅니다.

픽셀이 보이는지만 보지 말고 설정 topic과 프레임 시각을 확인합니다.
**Preview FPS**는 브라우저 전송 요청 속도이지 카메라 획득 속도를 높이는 값이
아닙니다. 느리면 숫자부터 올리지 말고 프레임 시각과 원본 스트림을 비교합니다.
소스 자체가 느릴 때는 [UTM ROS 브릿지](../hardware/utm_ros_vision_runtime_bridge.md)에
따라 카메라·USB·ROS를 점검합니다.

의도한 설정이 다시 읽히고 본인 환경에서 승인된 최신 프레임을 확인하면 기본
설정 작업은 끝입니다. 선택 장치, 출처·topic과 점검 결과를 남깁니다. 실험 판정을
확인하려면 [실제 실험의 검증 확인](#실제-실험의-검증-확인하기)으로 진행합니다.
카메라 설정을 끝내기 위해 자세 진단이나 보정을 반드시 수행할 필요는 없습니다.

<a id="step-5--pose-진단의-목적-구분하기"></a>

## 선택 작업: 자세 정보의 출처 진단하기

자세 정보가 어느 경로에서 잘못되는지 확인할 때 **Specimen Pose Test**를 엽니다.
통과할 때까지 모든 버튼을 누르지 말고 필요한 출처의 진단을 선택합니다.

![서로 다른 출처를 사용하는 pose 진단](assets/screenshots/2026-09-29/vision-pose.png)

1. **Load Pose Status**에서 추적기와 카메라 점유 상태를 읽습니다.
2. 아래 표에서 필요한 진단을 선택합니다.
3. **Snapshot Payload**, **Pose Summary**, **Pose API Result**를 함께 봅니다.

| 진단 | 확인하는 대상 | 입증하지 않는 것 |
|---|---|---|
| Virtual Pose Test | 실제 카메라 없이 자세 정보의 입출력 규약 확인 | 실제 장면에서의 검출 |
| Live D455F Snapshot | 감독하에 설정된 D455F topic 확인 | 별도 실험의 검증 완료 |
| D405 Smoke Snapshot | 별도의 D405 하드웨어 경로 | 루프가 선택한 카메라를 대신한 판정 |

그림에는 서로 다른 출처의 진단이 모여 있습니다. 결과의 출처·모드와 시편 ID를
읽고 해석합니다. 통과했더라도 가상 결과는 가상으로 남겨 둡니다.
**Release VLA Camera**는 사용 중인 세션을 방해할 수 있으므로 인퍼런스 중
이 화면에 결과가 없다는 이유만으로 누르지 않습니다.

<a id="step-6--실제-런의-verification-확인하기"></a>

## 실제 실험의 검증 확인하기

진행 중인 실험은 Live의 **VIS → Report**에서 확인합니다. 필요한 관측과 판정이
이번 실험에 속하는지 판단하는 곳입니다.

![Vision Agent 관측과 검증 리포트](../gui/assets/screenshots/2026-09-29/live-vision.png)

1. run/cycle을 검토 중인 실험과 대조합니다.
2. 선택 관측(**Active Cam** 또는 verification slot), 촬영 이미지와 관심 영역
   (ROI)을 확인합니다.
3. 대응하는 판정 근거를 읽습니다. 이미지 수신과 LLM 판정 완료 시점은 다르므로
   새 사진이 표시됐다는 것만으로 검증을 통과한 것은 아닙니다.

과거 화면인 그림에서 관측·검증 리포트 위치를 찾고, 본인 실험에서 필요한
단계의 현재 촬영 이미지와 대응 판정을 확인합니다. 워크스페이스 진단은 그
단계를 완료 처리하지 않습니다. 카메라가 움직였다면 기존 ROI에 실제 화면을
맞추거나 명시적으로 검토한 보정 변경 절차를 따릅니다. 통과시키려고 임계값을
바꾸지 않습니다. 관측 역할은 [Vision Agent](../agents/vision_agent.md)를 참고합니다.
판정이 실패하면 이미지·판정·정확한 사유를 남기고
[Vision 검토 복구](../gui/vision_review_recovery.md)를 읽은 뒤 실험 재개를 검토합니다.

<a id="step-7--필요할-때만-보정하기"></a>

## 유지보수 작업: 카메라 보정하기

보정은 카메라 모델을 바꾸는 작업이므로 카메라를 사용할 수 있는 점검 시간에
진행합니다. 평소 화면을 열 때마다 수행하거나 이 안내를 따라 하려고 정상
실험을 중단하지 않습니다.

1. 실제 checkerboard를 준비하고 한 칸 크기를 m로 측정합니다.
2. **Checkerboard size**, **Square size m**, 보정 파일을 입력합니다.
3. 카메라 사용 가능한 점검 시간에만 **Calibrate**를 실행합니다.
4. 보정 결과를 확인하고 **Stop Calibrate**로 해당 보정 세션을 닫습니다.

생성된 보정 근거가 실제 카메라와 보드에 해당하는지 확인합니다. 결과 파일 경로가
채워졌다는 것만으로 성공이 아닙니다. 9×6 같은 placeholder는 입력 예시이지
다른 보드를 쓰라는 지시가 아닙니다. 보정 결과를 관련 설정과 함께 보관합니다.

## 문제 해결과 완료

| 증상 | 먼저 확인 |
|---|---|
| 장치 없음 | OS/USB 연결·권한·Detect Devices 응답 |
| 프레임 공란 | 카메라 선택·runtime·topic·Pre Start Check |
| 오래된 사진 | 픽셀만 보지 말고 capture/frame 시각과 source |
| 카메라 busy | 현재 owner/lease, 해제 전 조율 |
| 느린 프리뷰 | 원본 획득/ROS 속도와 preview 전송 속도 구분 |
| Pose는 통과했지만 VIS 대기 | test mode/source와 필요한 런 검증 구분 |

실제로 수행한 작업의 결과를 남깁니다. 설정 작업은 저장값과 최신 프레임,
진단은 선택 출처의 근거, 실험 검증은 해당 실험의 이미지와 판정이 필요합니다.
문서의 캡처는 오늘의 확인을 대신하지 않습니다. 성공과 실패를 구분해 보존하고,
실험 복구나 다른 장비 작업은 [운영 안내](user_manual.ko.md)에서 선택합니다.
