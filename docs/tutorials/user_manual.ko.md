<!-- atr-doc
doc_type: guide
subtype: tutorial
status: active
authority: procedural
audience: [user, operator, researcher]
scope: [gui_tutorial, operator_workflow]
summary: Practical operator exercises for devices, evidence, recovery and read-only replay.
source_of_truth:
  - web/templates
  - web/static
  - app/main.py
  - app/run_review_routes.py
last_verified: 2026-09-29
verified_against: fcfba9f
related_docs:
  - docs/gui/visual_structure.md
  - docs/runtime/test_mode.md
supersedes: []
-->

<a id="운영자-실습-가이드"></a>

# AX4LAB 운영 안내

[English](user_manual.en.md) · [첫 실행](first_autonomous_run.ko.md) · [한국어 문서 목차](../README.ko.md)

## 시작 전

다음 실험을 준비하거나, 감독하에 장비를 사용하거나, 기존 실험의 결과와
오류를 확인할 때 필요한 절을 골라 읽습니다. 모든 절을 순서대로 수행할 필요는
없습니다. 계획에서 결과 파일까지 한 후보를 따라가 본 적이 없다면
[첫 가상 실험](first_autonomous_run.ko.md)을 먼저 진행합니다.

새 워크스테이션은 [설치 안내](../../install/README.md)부터 시작합니다.
설치된 Linux/WSL에서는 `atr up` 후 `http://localhost:7860`에 접속하고,
네이티브 Windows에서는 준비된 환경에서 `python -m app.serve`를 사용합니다.
실험이 진행 중이면 기존 서버를 사용합니다. 처음 장비를 설정할 때는 숙련된
운영자가 함께해야 하며, 이 문서가 무인 로봇·UTM 동작을 승인하지는 않습니다.

그림은 2026-09-29의 1920 × 1080 캡처이며 과거 런이나 idle 상태도 포함합니다.
새 물리 실험 증거가 아닙니다. 연결 정보·로컬 경로는 마스킹했고 화면의
숫자를 모든 장비에 적용할 기본값으로 사용하지 않습니다.

<a id="exercise-1--올바른-워크스페이스-찾기"></a>

## 작업에 맞는 워크스페이스 선택하기

워크스페이스에서는 장비와 기본값을 준비하고, Live에서는 특정 실험의 지시·승인·
리포트를 다룹니다. 어디에서 작업할지 결정할 때 이 차이를 먼저 확인합니다.
단독 장비 작업이 성공해도 대기 중인 Live 단계가 자동으로 완료되지는 않습니다.

1. Main에서 **Device Workspaces**로 스크롤합니다.
2. 설정하려는 장비를 고릅니다.
3. 런의 지시·승인·리포트는 Live GUI에서 처리합니다.

![메인 워크스페이스 목록](../gui/assets/screenshots/2026-09-29/main-workspaces.png)

| 작업 | 워크스페이스 | 따라 할 문서 |
|---|---|---|
| 출력 설정·슬라이싱·전송 | 3D Printer, `/printer` | [프린터 실습](device_workspace_3dp_usage.ko.md) |
| 포트와 데모 녹화 | Manipulation, `/lerobot` | [로봇 데모 녹화](#로봇-데모-한-편-녹화하기) |
| 정책 롤아웃·실험 태스크 설정 | Manipulation, `/lerobot` | [실행 경로별 정책 설정](#단독-실행과-실험용-정책을-각각-설정하기) |
| UTM 카메라·ROS | Vision, `/device-bridge/vision-utm` | [비전 실습](device_workspace_vision_camera_bridge_usage.ko.md) |
| Windows 브릿지·Skills | Windows Automation, `/equipment/windows` | [장비 자동화 준비](#windowsutm-자동화-준비하기) |
| BO 설정 | Bayesian Optimization, `/bo` | [후보 결과 추적](#설계부터-최적화까지-결과-추적하기) |
| 장비 인터록 | PLC Safety, `/plc` | [PLC 브릿지](../device_bridges/plc_safety_bridge.md) |
| 축적 지식 | Knowledge, `/knowledge` | [지식 출처 확인](#축적-지식의-출처-확인하기) |
| 멈춘 실험 | Live | [진단과 재개](#같은-실험을-진단하고-재개하기) |
| 저장된 세션 | Main → replay | [읽기 전용 다시보기](#장비-동작-없이-저장된-세션-다시보기) |
| 실험 흐름과 실행 근거 | Runtime IDE, `/ide` | [흐름 살펴보기](#runtime-ide에서-실험-흐름-살펴보기) |

Main 그림에서 워크스페이스 진입 위치를 찾습니다. 설정을 확인한 뒤에는 같은
Live 실험으로 돌아가 ID를 확인하고 지시합니다. 페이지를 열었다는 사실은
에이전트 단계의 시작이나 완료를 뜻하지 않습니다.

<a id="exercise-2--가상-테스트에서-실제-장비로-전환하기"></a>

## 새 실험에서 실제 장비를 사용하도록 준비하기

장비 설치·점검과 작업 공간 준비가 끝나고 운영자가 감독할 수 있을 때 가상
실험에서 실제 장비로 전환합니다. **Test**라는 이름 자체는 안전 경계가 아닙니다.
새 요청을 보내기 전에 허용할 실제 동작을 선택합니다.

1. Main의 **Test Mode Settings**를 엽니다.
2. **Installed Printer**, **Physical Print**를 비교합니다.
3. 각 에이전트 경계, 출력 본문·냉각, 자동 배출을 확인합니다.
4. 사용할 프로필만 저장하고 다시 읽어 확인합니다.
5. Live에 `테스트 모드, 실제 프린터` 또는 `테스트 모드, 실제 출력`으로
   선택한 경로를 명시합니다.

![출력 본문 없이 배출 경로를 사용하는 Installed Printer](assets/screenshots/2026-09-29/profile-installed.png)

![출력과 냉각을 수행하는 Physical Print](assets/screenshots/2026-09-29/profile-physical.png)

두 그림에서 출력 본문과 냉각 선택의 차이를 확인하되 저장값을 그대로 복사하지
않습니다. 검토한 실험 계약과 선택 프로필이 일치해야 합니다. **Installed Printer**는
출력 본문·냉각을 생략하지만 배출 전용 파일을 보내고 이후 실제 장비를 작동시킬
수 있습니다. **Physical Print**는 전체 출력 경로를 사용합니다. 시편을 직접
공급한다면 현재 요청에 맞춰 실제로 놓거나 치운 것을 확인한 뒤 응답합니다.

실제 프린터 경로 통과만으로 첫 층 접착·전체 출력 시간·노즐 정리가 검증되지는
않습니다. 실제 출력은 별도 현장 감독하에 검증합니다. 프로필 변경은 다음
승인 런부터 적용됩니다. 상세는 [Test Mode](../runtime/test_mode.md)를 봅니다.

<a id="exercise-3--로봇-포트-설정과-데모-한-편-녹화하기"></a>

## 로봇 데모 한 편 녹화하기

데모에는 이후 학습에 사용할 카메라와 관절·동작 데이터가 기록됩니다. 녹화는
감독이 필요한 로봇 작업이며 학습이나 자율 실험 실행과는 다릅니다. 시작 전에
보정된 장치, 사용할 수 있는 카메라, 새 로컬 데이터셋 이름을 준비합니다.
다른 세션이 같은 장비를 사용 중이면 먼저 점유 관계를 해결합니다.

1. **Manipulation → Profile**에서 사용할 로봇 프로필을 선택합니다.
2. **2. Device Port Setup**을 펼쳐 follower·leader·카메라 저장값을 확인합니다.
3. 설정이 필요하면 대상 장치에서 **Baseline → ID Detect & Save** 순으로 화면
   안내를 따릅니다. 수동 설정은 **Manual Port Override**의 역할/카메라 key를
   고른 뒤 **Save Manual Port**를 사용합니다. 저장·장치 탐색 작업입니다.
4. 동작 전에 [LeRobot 브릿지](../device_bridges/lerobot_bridge.md)에 따라
   캘리브레이션과 카메라 점유 상태를 확인합니다.

![펼친 로봇 포트와 카메라 설정](assets/screenshots/2026-09-29/robot-devices.png)

5. **4. Local Paths**에 dataset root와 dataset repo ID/local name을 지정합니다.
   새 녹화는 새 데이터셋 이름을 사용합니다. **Resume dataset**은 호환되는
   기존 데이터셋에만 사용하며, 폴더 삭제가 resume 방법은 아닙니다.
6. **6. Recording**에서 **Task Instruction**, **Episodes**,
   **Episode Time (s)**, **Reset Time (s)**를 입력합니다.
   첫 감독 실습은 한 에피소드로 진행합니다.
7. 로봇 동작 범위를 비운 뒤 **Start Record**를 누릅니다.

![녹화 입력과 에피소드 조작 버튼](assets/screenshots/2026-09-29/robot-recording.png)

8. **Save / Next →**는 수락, **Retry Current ←**는 현재 에피소드 재시도,
   **Finish Gracefully (Esc)**는 정상 종료입니다.
   **Force Stop**은 비상 정리이며 일반 저장 버튼이 아닙니다.
9. 학습 전에 동작 상태·로그와 데이터셋 저장 결과를 확인합니다.

그림에서 포트 설정과 에피소드 조작 영역이 분리되어 있음을 확인합니다. 정상
종료 후 지정한 데이터셋을 열어 수락한 에피소드의 카메라 프레임과 관절·동작
채널이 저장됐는지 확인합니다. 데이터셋 ID와 세션 로그도 함께 남깁니다.
프로세스가 시작됐지만 데이터가 없다면 녹화에 성공한 것이 아닙니다.

시작에 실패하면 로그에서 포트·보정·카메라 점유·데이터셋 호환성 중 어느
문제인지 구분한 뒤 재시도합니다. 보정 파일 삭제나 다른 세션이 점유한 장치의
재연결을 일반적인 해결법으로 사용하지 않습니다. 프로필별 준비와 녹화 조건은
[LeRobot 브릿지](../device_bridges/lerobot_bridge.md)를 참고합니다.

<a id="exercise-4--단독-인퍼런스와-에이전트-설정-구분하기"></a>

## 단독 실행과 실험용 정책을 각각 설정하기

단독 롤아웃은 정책을 직접 시험하고, 실험 루프는 별도의 태스크 설정을 읽습니다.
어느 경로를 준비하는지 정한 뒤 해당 영역에서 저장합니다. 둘 다 로봇을 움직일
수 있으므로 실행 전에 보정·장비 점유 상태와 주변 안전을 확인합니다.

1. 감독하의 단독 시험은 **10. Inference / Rollout**에서 설정합니다.
2. 체크포인트·task·action rate를 확인합니다.
3. 선형 보간과 RTC 사용 여부를 명시합니다. 보간 출력 Hz는 정책/action FPS와
   별개이며 입력 rate보다 낮으면 안 됩니다. GUI 상한은 100 Hz입니다.
4. **Save Rollout Defaults**로 저장합니다. 주변이 안전할 때만 실행합니다.

![단독 롤아웃 설정](../gui/assets/screenshots/2026-09-29/lerobot-inference.png)

5. 루프에 사용할 값은 **11. Manipulation Agent Bridge**에서 설정합니다.
6. 해당 task를 선택하고 그 task의 정책·rate·옵션을 확인한 뒤
   **Save Task Defaults**를 누릅니다. 단독 설정 저장을 에이전트 task 저장과
   동일하게 취급하지 않습니다.

![태스크별 에이전트 브릿지 설정](../gui/assets/screenshots/2026-09-29/lerobot-agent-bridge.png)

첫 그림은 단독 롤아웃, 둘째 그림은 태스크별 브릿지 설정입니다. 실제 사용할
영역에서 정책·태스크·속도·옵션의 저장값을 다시 확인합니다.
**Save Rollout Defaults**와 **Save Task Defaults**는 서로의 설정을 바꾸지
않습니다. 실험 중에는 MAN의 측정 상태, 정책 추종 상태와 산출물을 확인합니다.
3D 로봇 표시만으로 파지·배치 성공을 판단하지 않습니다. 루프가 조작 장비를
사용 중이면 단독 롤아웃을 시작하지 않습니다.

<a id="exercise-5--windowsutm-자동화-준비하기"></a>

## Windows/UTM 자동화 준비하기

worker가 연결되어 있어도 잘못된 앱이나 시험 메소드가 열려 있을 수 있습니다.
실행 승인 전에 장비 운영자와 함께 대상 화면과 수행 순서를 확인합니다.
새 worker는 먼저 [브릿지 설치와 페어링](../../Pyautogui_server_for_window/README.md)을
완료합니다.

1. **Windows Automation**에서 브릿지·worker 연결을 확인합니다.
2. 수신 화면이 로그인·업데이트·다른 창이 아닌 의도한 UTM 앱인지 확인합니다.
   장비 운영자와 조율합니다.
3. 사용할 Skills와 증거를 읽습니다. 화면을 채우려는 목적으로 실행하지 않습니다.

![Windows 자동화 워크스페이스](../gui/assets/screenshots/2026-09-29/equipment-windows.png)

4. `/equipment/agent-manager`에서 **Equipment Flow**와 프로필을 확인합니다.
5. Skill 순서·Vision slot을 사용할 메소드와 대조합니다.
   [Equipment Agent](../agents/equipment_agent.md),
   [Windows 브릿지](../device_bridges/windows_pyautogui_bridge.md)를 따릅니다.
   실패한 동작을 건너뛰려고 실행 중 flow를 편집하지 않습니다.

![Equipment Agent Manager의 흐름 구성](../gui/assets/screenshots/2026-09-29/equipment-agent-manager.png)

워크스페이스 그림에서는 대상 화면을, Agent Manager 그림에서는 순서가 있는
flow를 찾습니다. worker·앱·메소드·Skills가 함께 맞아야 합니다. EQP 실행 전
필요한 현재 관측 근거가 이번 실험에 연결되어야 합니다. 연결 표시만으로 압축이나
높이 복귀가 완료됐다고 판단할 수는 없습니다. 화면이나 메소드가 다르면 장비
운영자와 원인을 해결하고, 실행 중 flow에서 실패 단계를 빼는 식으로 우회하지 않습니다.

<a id="exercise-6--한-후보를-설계부터-bo까지-추적하기"></a>

## 설계부터 최적화까지 결과 추적하기

결과를 해석하거나 공유하기 전에 어떤 측정값이 어떤 최적화 관측값으로 사용됐는지
확인합니다. 기본 화면 이동은 [첫 실험의 결과 읽기](first_autonomous_run.ko.md#step-7--분석과-bo-결과-읽기)를
참고하고, 여기서는 하나의 실험·사이클·후보 ID를 끝까지 추적합니다.

1. Live의 **DSN → Report**에서 후보 ID, cell size, wall thickness,
   형상 파일, 제약 결과를 기록합니다.
2. **ANL → Report**에서 선택 사이클, 응력–변형률(SS)·힘–변위(FD)의 축과
   단위, 원본 CSV, 비에너지흡수량(SEA)에 사용한 질량 출처와 적분·변형률
   근거를 확인합니다.
3. **BO → Report**에서 목적함수·최대화/최소화·관측 개수를 확인합니다.
4. 가우시안 프로세스(GP) 모델이 있으면 2D/3D 평균·불확실성·획득함수·다음
   후보를 봅니다. 과거 1D 표시만으로 cell size와 wall thickness의 전체
   탐색 공간을 해석하지 않습니다.

![ANL 곡선과 물성 근거](../gui/assets/screenshots/2026-09-29/live-analysis.png)

![BO 포스테리어와 추천](../gui/assets/screenshots/2026-09-29/live-bo.png)

후보 ID와 형상 경로, 원본 CSV, 단위·질량 출처가 있는 분석값, 이를 사용한
BO 관측을 묶어서 보관합니다. 슬라이싱 전 질량 공란은 미확인이며 이후에는
분석에 사용된 기록값을 확인합니다. 다른 형상 추정치로 대체하지 않습니다.
ID나 출처가 맞지 않으면 값들을 하나의 실험 결과로 합치지 않습니다.

그림은 과거 분석·최적화 결과이지 새 측정이 아닙니다. BO 추천 후보는 아직
실험하지 않은 후보입니다. 초기 라틴 하이퍼큐브 표본 추출(LHS) 단계에는 GP가
없을 수 있습니다. [ANL](../agents/analysis_agent.md)과 [BO](../agents/bo_agent.md)에서
해석 조건을, [산출물 보관](../gui/artifact_preservation.md)에서 원본까지 함께
보관하는 방법을 확인합니다.

<a id="exercise-7--축적-지식의-출처-확인하기"></a>

## 축적 지식의 출처 확인하기

Knowledge에서는 이전 절차와 관측을 이해하고 현재 작업에 적용할 수 있는지
판단합니다. 오늘 촬영한 이미지나 장비 완료 기록을 대신하는 화면은 아닙니다.

1. **Knowledge → Wiki**를 엽니다.
2. 글을 선택하고 출처·적용 범위를 읽습니다.
3. **Source Library**로 원문 출처를 봅니다.
   Memory·Agent Delivery는 별도 조회 화면이지 추가 물리 센서가 아닙니다.

![출처가 연결된 Knowledge Wiki](../gui/assets/screenshots/2026-09-29/knowledge-wiki.png)

그림의 글 보기에서 원문 출처와 적용 범위를 찾아봅니다. 내용을 사용하기 전에
과거 근거·절차 설명·현재 실험 근거를 구분합니다. 비공개 화면에서 401 응답이
나오면 우회하지 말고 접근 권한을 요청합니다. 출처와 메모리를 다루는 방법은
[Knowledge 운영](../knowledge/markdown_memory_operations.ko.md)을 참고합니다.

<a id="exercise-8--같은-런을-진단하고-재개하기"></a>

## 같은 실험을 진단하고 재개하기

실험이 멈추면 설정을 바꾸기 전에 실험 ID와 근거를 남깁니다. Timeline 그림에서
어느 단계에서 멈췄는지 설명하는 이벤트를 찾습니다. 장비 경고가 사라졌다고
실험도 자동으로 재개됐다고 가정하지 않습니다.

1. run ID·cycle·agent와 정확한 미해결 사유를 기록합니다.
2. 해당 에이전트의 **Timeline**, **Artifacts**, 필요시 **Backend**를 봅니다.
3. 실제 원인인 연결·입력·물리 상태를 수정하며 현재 근거를 보존합니다.
4. 런타임이 복구를 제공하면 기존 **Resume**을 사용합니다.
5. 같은 run ID·의도한 재개 지점·새 근거를 확인합니다.

![멈춘 단계를 찾는 Timeline](../gui/assets/screenshots/2026-09-29/live-timeline.png)

복구 결과는 같은 실험에 새 근거로 남아야 합니다. **Resume**은 복구 가능한
단계를 반복할 수 있으므로 물리 동작이 반드시 한 번만 실행된다고 보장하지
않습니다. 승인 전에 재개 지점과 실제 장비 상태를 확인합니다. 완료 플래그를
새 실험에 복사하거나, 실패 기록을 지우거나, PLC 잠금을 무조건 해제하거나,
**Start**를 Resume 대신 사용하지 않습니다.

재개 조건은 [Resume](../gui/run_resume.md), 출력 대기는
[프린터 대기 복구](../gui/printer_wait_recovery.md), 비전 판정 실패는
[Vision 검토 복구](../gui/vision_review_recovery.md)를 확인합니다.
재개 가능한 Resume이 표시되지 않으면 관리자용 체크포인트 조작을 임의로
시도하지 말고 실험 ID와 실패 상세를 보존해 지원을 요청합니다.

<a id="exercise-9--읽기-전용-다시보기-열기"></a>

## 장비 동작 없이 저장된 세션 다시보기

실험 종료 후 검토하거나 작업을 인계할 때 Main의 Replay를 사용합니다.
보관된 기록을 읽는 기능이며 LeRobot 동작 재생이 아닙니다. 누락된 관측을
채우기 위해 실제 장비를 새로 조회하지 않습니다.

1. Main에서 **Mode = replay**를 고릅니다.
2. **Experiment session → Start**로 새 창을 엽니다.
3. Contract 영역의 시점 선택을 사용합니다.
4. 좌우 키는 저장 시점, 상하 키는 존재하는 사이클 사이를 이동합니다.
   텍스트/select 입력 중에는 방향키를 가로채지 않습니다.

![Main의 Replay 세션 선택](assets/screenshots/2026-09-29/main-replay.png)

![기존 Live 구조를 사용하는 Replay](../gui/assets/screenshots/2026-09-29/replay.png)

상단의 **REPLAY** 표시를 확인하고 이동할 때 선택 run/cycle/point가 바뀌는지
봅니다. 첫 그림은 Main의 세션 선택, 둘째는 읽기 전용 결과 창입니다. 없는
스냅샷은 누락 상태로 구분해야 합니다. 파일은 남아 있지만 대응하는 저장 시점은
없을 수도 있으므로 특정 시점의 근거와 일반 보관 파일을 구분합니다.
자세한 동작은 [Replay](../gui/run_replay.md)를 참고합니다.

<a id="exercise-10--루프를-바꾸지-않고-런타임-구조-살펴보기"></a>

## Runtime IDE에서 실험 흐름 살펴보기

Runtime IDE는 운영 중 관찰에도 사용합니다. 다음에 어떤 모듈이 실행되는지,
연결이 어떻게 정의되어 있는지, 실행 근거가 어디에 있는지 살펴볼 수 있습니다.
이 확인을 위해 흐름을 편집하거나 활성화할 필요는 없습니다.

1. `/ide`에서 graph와 node/module 설정을 읽습니다.
2. 연결 계약과 관련 실행 근거를 찾아봅니다.
3. 별도의 개발 작업에서만 draft validation/compile/dry-run 후 저장 버전 적용을
   진행합니다. 이 실습에서는 편집본을 활성화하지 않습니다.

![Runtime IDE 그래프와 검사 영역](../gui/assets/screenshots/2026-09-29/ide-graph.png)

그림의 그래프와 검사 영역에서 화면 리포트, 모듈 구현, 연결 계약과 실행 그래프의
관계를 찾아봅니다. 표시 정보를 바꿔도 장비 권한이 생기지는 않습니다.
관찰 절차는 [Runtime IDE](../runtime/runtime_ide.md)를 참고합니다.
기능을 확장하려면 별도의 개발 작업으로 다룹니다. [모듈화](../modularity.md),
[Module Management 화면](../gui/visual_structure.md),
[CONTRIBUTING](../../CONTRIBUTING.md)을 읽고 편집본의 검증·컴파일·dry-run을
거친 뒤 저장 버전의 활성화를 검토합니다.

## 완료 체크와 추가 문서

- 새 런 전에 물리 실행 범위를 선택할 수 있습니다.
- 프린터·단독 롤아웃·에이전트 task별 저장 버튼을 구분합니다.
- 한 후보의 원본 근거와 보관 파일을 찾을 수 있습니다.
- Resume, 새 Start, 읽기 전용 Replay를 구분합니다.
- 과거 스크린샷을 현재 물리 증거로 사용하지 않았습니다.

보관할 때 `runs/<run-id>/`와 참조 산출물을 함께 유지합니다.
`memory/`의 연결·설정에는 비밀정보가 있을 수 있으므로 공개 첨부하지 않습니다.

개발 환경·테스트·기여 절차는 [CONTRIBUTING](../../CONTRIBUTING.md),
전체 화면 지도는 [GUI 구조](../gui/visual_structure.md)를 참고합니다.
