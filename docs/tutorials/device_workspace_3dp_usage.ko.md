<!-- atr-doc
doc_type: guide
subtype: tutorial
status: active
authority: procedural
audience: [user, operator, researcher]
scope: [gui_tutorial, operator_workflow]
summary: Printer profile persistence, slicing-only verification and guarded physical execution.
source_of_truth:
  - web/templates/printer.html
  - web/static/printer.js
  - device_bridges/printer_fleet/bridge.py
last_verified: 2026-09-29
verified_against: fcfba9f
related_docs:
  - docs/gui/visual_structure.md
  - docs/runtime/test_mode.md
supersedes: []
-->

# 3D 프린터 실습 — 저장·슬라이싱·확인 후 출력하기

[English](device_workspace_3dp_usage.en.md) · [튜토리얼 목차](first_autonomous_run.md) · [한국어 문서 목차](../README.ko.md)

## 목표와 준비

이 안내는 두 작업으로 나뉩니다. 먼저 출력 설정을 저장하고 **출력을 시작하지
않은 채** 슬라이싱 파일을 만듭니다. 이후 선택 절차는 실제 장비를 감독하에
사용할 때만 진행합니다. 기본값 저장, 파일 생성, 실제 출력 완료는 서로 다른
결과입니다.

사용할 프린터·슬라이서 프로필과 서버가 읽을 수 있는 STL 또는 지원되는 3MF를
준비합니다. 브라우저를 연 컴퓨터의 경로가 서버에도 존재하는 것은 아닙니다.
장비를 사용하려면 올바른 연결 정보, 정리된 동작 범위와 출력·배출 순서에 대한
승인도 필요합니다. 진행 중인 실험이 프린터를 사용한다면 워크스페이스에서 별도
작업을 시작하지 말고 해당 실험의 리포트를 확인합니다.

**Main → Device Workspaces → 3D Printer** 또는 `/printer`를 엽니다.
그림은 2026-09-29의 1920 × 1080 캡처입니다. 저장값 예시이지 권장 프로필이
아닙니다. 촬영 때문에 슬라이싱·전송·출력·설정 저장을 실행하지 않았습니다.

## 설정을 저장하고 슬라이싱 파일 만들기

### Step 1 — 사용할 프린터 선택하기

**Bridge Connection**에서 시작합니다. 선택한 프린터 제공자(provider)에 따라
연결과 슬라이싱 경로가 달라집니다. 다른 프린터가 자동 대체 경로라고 가정하지
않습니다.

1. **Printer Fleet Selection → Active Printer Profile**을 확인합니다.
2. 변경할 때만 대상 프린터 선택 후 **Set Active Printer**를 누릅니다.
3. Bambu는 **Bambu LAN Connection**에서 실제 host·serial·access code를
   비공개 설치 환경에 입력합니다.
4. LAN-only/developer-mode 확인란은 프린터 설정을 확인한 후에만 체크합니다.
5. **Set Bridge Connection → Reload Connection**으로 저장을 확인합니다.

![프린터 선택과 연결 설정](assets/screenshots/2026-09-29/printer-connection.png)

그림에서 프린터 선택과 비공개 연결 입력의 위치를 찾습니다. 다시 읽은 뒤에도
대상 프린터와 연결 정보가 맞아야 합니다. access code 공란은 기존 코드를
유지한다는 뜻이지 비밀번호가 없다는 뜻이 아닙니다. 기본 provider는 Bambu이며
아래 슬라이싱 버튼도 Bambu 경로입니다. Prusa 등 다른 프린터를 명시적으로
선택했다면 [프린터 fleet 안내](../device_bridges/printer_fleet_bridge.md)를 따릅니다.
연결 JSON과 비밀번호가 나온 스크린샷은 공개하지 않습니다.

### Step 2 — 배치와 기본 출력 설정하기

**Print Defaults**에서 다음 슬라이싱에 사용할 값을 준비합니다. 그림의 숫자를
복사하지 말고 실험에서 검토한 재료와 형상 조건을 적용합니다.

1. 재료·프린터/노즐 프로필·layer height·bed temperature를 실제 구성과
   검증한 실험에 맞춥니다.
2. **Specimen placement**를 고릅니다. **Custom center X / Y**는 시편 중심을
   mm로 입력합니다. 모서리 좌표와 혼동하지 않습니다.
3. skirt/brim/raft와 cap skin을 시편 설계에 맞게 확인합니다.
4. **Bambu Source STL / 3MF Path**에 슬라이싱할 모델 경로를 넣습니다.

![Print Defaults와 시편 중심 좌표](assets/screenshots/2026-09-29/printer-defaults.png)

그림에서 **Specimen placement**의 위치를 찾습니다. mm 단위 중심 좌표를
기준으로 시편이 베드와 의도한 이송 경로 안에 들어가는지 확인합니다. X/Y가
바뀌면 원본 모델을 다시 슬라이싱해야 합니다. 새 배치값을 저장해도 기존
G-code에 기록된 이동 경로가 바뀌지는 않습니다.

### Step 3 — 시작·속도·보정 옵션 저장하기

**Print Start & Early Layers**에서 새 파일에 적용할 시작·초반 레이어 옵션을
정합니다. 숫자 저장과 옵션 활성화는 별개이므로 적용하려는 항목은 둘 다
확인합니다.

![독립적인 시작 옵션과 저장 버튼](assets/screenshots/2026-09-29/printer-start-options.png)

| 항목 | 확인할 의미 |
|---|---|
| First-layer override | 첫 층 높이·속도·베드 온도는 별도 입력 |
| XYZ speed scale (%) | 1~100% 범위이며, 100%는 감속하지 않음 |
| Start-point prime | 독립 체크박스와 mm 단위 토출량; Z 상승량 아님 |
| Layer 2–5 speed cap | 별도 활성화와 mm/s 속도 |
| Early-layer Z cap | 설정된 초반 레이어 구간에 대한 독립 활성화 |
| Bed leveling / flow calibration | 요청 옵션이며 실제 보정 수행 증거와 별개 |

공통 비율은 XY만이 아니라 **XYZ 이동**에 적용합니다. 과거 이름을 유지한
저장 키 `xy_speed_scale_percent`를 비롯한 필드 의미는
[Bambu 제어 항목 설명](../device_bridges/bambu_x2d_bridge.md#control-semantics)을 참고합니다.

1. 체크박스가 꺼져 있어도 원하는 숫자를 입력할 수 있습니다.
2. 적용할 옵션만 체크합니다.
3. **Save Print Defaults**를 누릅니다.
4. 새로고침 후 숫자와 체크 상태가 유지되는지 확인합니다.

다시 표시된 숫자와 체크 상태를 선택한 값과 대조합니다. 비활성 옵션은 숫자를
보관하더라도 적용하지 않습니다. 기본값 저장으로 기존 파일이나 진행 중 출력이
바뀌지는 않으며 다음 단계에서 새 파일을 만듭니다. **Test Specimen Defaults**는
기본 시편을 제공하는 fallback 설정이지 BO 탐색 범위가 아닙니다.

### Step 4 — 출력하지 않고 슬라이싱하기

슬라이싱은 원본 모델과 저장 설정을 특정 결과 파일로 만듭니다. 이후 검사가
그 파일을 대상으로 하는지 확인할 수 있도록 반환된 경로와 hash를 남깁니다.

1. source path가 원하는 시편인지 확인합니다.
2. 상단 **Slice Bambu Artifact**를 누릅니다.
3. **Bridge Evidence Log**의 응답을 기다립니다.
4. 결과 파일 경로·hash·배치 검증을 봅니다. 성공하면
   **Bambu Sliced Artifact Path**에 결과가 들어갑니다.
5. 생성 프로젝트/G-code와 제공된 슬라이서 질량·시간 근거를 확인합니다.

![상단 준비·실행 버튼](../gui/assets/screenshots/2026-09-29/printer.png)

그림의 상단에는 준비와 실행 버튼이 함께 있습니다. 이 단계에서는 시작 버튼이
아니라 **Slice Bambu Artifact**를 사용합니다. upload/MQTT publish 없이
sliced artifact ready 결과가 남아야 합니다. 경로만 채워지고 응답이 실패했다면
완료가 아닙니다. 재시도 전 실패 코드와 서버 로컬 입력, 슬라이서 실행파일,
프로필을 확인합니다.

설정이 다시 읽히고 결과 경로·hash·배치 및 제공되는 질량·시간 근거를 확인하면
슬라이싱 작업은 끝입니다. 원본 경로와 함께 기록하고 슬라이싱만 수행했다고
명시합니다. 별도의 감독 장비 작업이 없다면 여기서 멈춥니다.

## 선택 작업: 실제 출력을 준비하고 감독하기

다음 단계는 슬라이싱 성공의 필수 조건이 아닙니다. 실제 장비 사용을 준비하거나
그 결과를 확인하는 절차입니다. 배출 파일을 실행하면 장비가 움직일 수 있고
**Publish Start**는 프린터를 시작할 수 있습니다. 실제 베드 상태, 이동 공간,
현재 승인과 장비 점유를 확인한 뒤 진행합니다. 실험이 관리하는 작업이라면
수동 시작을 병행하지 말고 Live/SPC 순서를 따릅니다.

### Step 5 — 자동 배출을 별도로 검토하기

승인된 출력에 자동 배출이 포함된다면 **Bambu G-code Autoejection**을 엽니다.
슬라이싱의 부수적인 값으로 보지 말고 하나의 장비 동작 프로그램으로 검토합니다.

1. provider·방향·push offset/lane·sweep 설정을 확인합니다.
2. 변경하면 **Save Autoejection Config**로 저장합니다.
3. **Validate G-code Preview**로 루틴을 검토합니다.
4. 배출이 포함된 파일을 만들 때 **Generate Patched Artifact**를 사용하고
   결과 경로와 검증 근거를 확인합니다.

![자동 배출 구성과 파일 생성](assets/screenshots/2026-09-29/printer-ejection.png)

그림에서 설정, 미리보기와 파일 생성 버튼을 구분합니다. 생성 파일과 검증 근거는
준비한 내용을 설명할 뿐 실제 배출을 증명하지 않습니다.
**Fill Native G-code Defaults**는 로컬 입력란만 채우므로 별도 저장·생성이
필요합니다. 배출이나 sweep 시험 파일을 단순한 버튼 확인 목적으로 실행하지 않습니다.

### Step 6 — 실제 완료 증거와 시작 게이트 구분하기

![Physical Proof Package와 완료 감사](assets/screenshots/2026-09-29/printer-proof.png)

그림의 **Physical Proof Package**에서 증거 준비와 실제 완료를 구분합니다.
**Build Fail-Closed Proof Template**는 채울 양식을 만들고,
**Run Completion Audit**는 그 근거를 검사합니다. 어느 버튼도 단독으로 배출을
수행하거나 입증하지 않습니다. **Mark Bed Clear**는 실제 베드 상태를 확인한
뒤에만 사용합니다. 물리 상태를 선언하는 버튼이지 오류 해제 버튼이 아닙니다.

실제 감독 출력은 기존 Live 루프의 SPC handoff 경로를 우선 사용합니다.
단독 준비의 **Pre-start Check**, **Print Command Draft**,
**Start Gate Check**, **Publish Start**는 서로 다릅니다.

| 제어 또는 작업 | 결과가 뜻하는 것 |
|---|---|
| Pre-start Check | 현재 준비 상태와 차단 사유 확인 |
| Print Command Draft | 명령 준비이며 실행은 아님 |
| Start Gate Check | 시작 조건 검사이며 출력 완료는 아님 |
| Publish Start | 실제 시작 명령 가능; 의도한 파일과 현재 승인 필요 |
| Upload-path probing / transfer | 출력 전에도 프린터에 접속하거나 쓸 수 있음 |

현재 준비된 파일·승인을 사용하고 과거 성공 근거로 대체하지 않습니다.
전송·정리·완료 계약은 [Bambu 브릿지](../device_bridges/bambu_x2d_bridge.md)를 봅니다.

### Step 7 — 런 소유 SPC 근거 확인하기

승인한 실험이 시작되면 Live의 **SPC → Report**를 엽니다. job ID와 파일을
준비한 대상과 대조한 뒤 전송·시작 결과, 장비 상태의 최신성, 남은 시간, 카메라와
출력 이후 인계 근거를 확인합니다. 그림은 확인 위치를 보여 주는 과거 리포트이지
현재 프린터의 증거가 아닙니다.

![런에 속한 SPC 모니터링](../gui/assets/screenshots/2026-09-29/live-specimen.png)

완료 근거는 이번 실험과 파일에 속해야 합니다. idle 프린터나 과거의 finished
job만으로 이번 작업의 완료를 판단하지 않습니다. 정지된 영상도 프린터가
멈췄다는 증거는 아니므로 장비 상태와 프레임 시각을 따로 봅니다. 대기가
계속되면 근거를 보존하고 [프린터 대기 복구](../gui/printer_wait_recovery.md)를
읽은 뒤 Resume을 검토합니다.

## 문제 해결과 완료

| 증상 | 먼저 확인 |
|---|---|
| 저장 후 체크 상태가 달라짐 | Save Print Defaults 응답·재로딩, 기존 파일과 구분 |
| 위치·속도가 안 바뀜 | 원본 재슬라이싱 및 새 파일/hash 사용 여부 |
| 슬라이서 입력 없음 | 서버 로컬 경로와 선택 프로필 |
| 업로드만 되고 시작 안 함 | 현재 start gate 사유와 명시적 실행 승인 |
| FTPS·영상·MQTT 상태가 다름 | 채널별 상태와 최신성, 서로 대체 증거가 아님 |
| 배출 configured만 표시 | 설정·검증·실제 완료는 별개 |
| 문서 그림과 숫자가 다름 | 그림 대신 저장된 검증 프로필 사용 |

슬라이싱만 했다면 원본 경로, 저장 설정, 결과 경로·hash와 검증 결과를 보관합니다.
실제 출력까지 했다면 실험·job ID, 시작과 실제 완료 근거, 필요한 출력 이후
인계 기록도 남깁니다. 두 결과를 명확히 구분합니다.
[산출물 보관](../gui/artifact_preservation.md)에서 참조 파일의 보존 방법을
확인합니다. 실제 상태가 불명확할 때 필요한 것은 운영자의 확인이지 반복 전송이 아닙니다.

## 다음 문서

- [Printer fleet](../device_bridges/printer_fleet_bridge.md)
- [Bambu 설정과 구현](../device_bridges/bambu_x2d_bridge.md)
- [SPC 근거](../agents/specimen_agent.md)
- [실행 프로필](../runtime/test_mode.md)
- [운영자 실습](user_manual.ko.md)
