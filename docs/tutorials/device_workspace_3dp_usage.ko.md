<!-- atr-doc
doc_type: guide
subtype: tutorial
status: active
authority: procedural
audience: [user, operator, researcher]
scope: [gui_tutorial, operator_workflow]
summary: Printer profile persistence, slicing-only verification and guarded physical execution.
source_of_truth:
  - runtime/web/templates/printer.html
  - runtime/web/static/printer.js
  - runtime/device_bridges/printer_fleet/bridge.py
last_verified: 2026-09-29
verified_against: fcfba9f
related_docs:
  - system/runtime/gui/visual_structure.md
  - system/runtime/test_mode.md
supersedes: []
-->

# 3D 프린터 실습 — 저장·슬라이싱·확인 후 출력하기

[English](device_workspace_3dp_usage.en.md) · [튜토리얼 목차](first_autonomous_run.md)

## 목표와 준비

의도한 출력 설정을 저장하고 **출력 시작 없이** 확인 가능한 슬라이싱 파일을
만듭니다. 실제 출력은 마지막의 별도 단계입니다.
사용할 프린터·슬라이서 프로필과 로컬 STL 또는 지원되는 3MF 입력이 필요합니다.
장비 작업에는 올바른 연결 정보와 현장 감독·정리된 동작 범위도 필요합니다.

**Main → Device Workspaces → 3D Printer** 또는 `/printer`를 엽니다.
그림은 2026-09-29의 1920 × 1080 캡처입니다. 저장값 예시이지 권장 프로필이
아닙니다. 촬영 때문에 슬라이싱·전송·출력·설정 저장을 실행하지 않았습니다.

## Step 1 — 사용할 프린터 선택하기

**Bridge Connection**으로 스크롤합니다.

1. **Printer Fleet Selection → Active Printer Profile**을 확인합니다.
2. 변경할 때만 대상 프린터 선택 후 **Set Active Printer**를 누릅니다.
3. Bambu는 **Bambu LAN Connection**에서 실제 host·serial·access code를
   비공개 설치 환경에 입력합니다.
4. LAN-only/developer-mode 확인란은 프린터 설정을 확인한 후에만 체크합니다.
5. **Set Bridge Connection → Reload Connection**으로 저장을 확인합니다.

![프린터 선택과 연결 설정](assets/screenshots/2026-09-29/printer-connection.png)

**확인:** 실제 대상과 선택 프린터·연결 정보가 일치합니다.
access code 공란은 기존 코드를 유지한다는 뜻이지 비밀번호가 없다는 뜻이
아닙니다. 기본 provider는 Bambu이며 다른 프린터는 명시 선택합니다.
연결 JSON이나 비밀번호가 나온 스크린샷은 공개하지 않습니다.

## Step 2 — 배치와 기본 출력 설정하기

**Print Defaults**로 이동합니다.

1. 재료·프린터/노즐 프로필·layer height·bed temperature를 실제 구성과
   검증한 실험에 맞춥니다.
2. **Specimen placement**를 고릅니다. **Custom center X / Y**는 시편 중심을
   mm로 입력합니다. 모서리 좌표와 혼동하지 않습니다.
3. skirt/brim/raft와 cap skin을 시편 설계에 맞게 확인합니다.
4. **Bambu Source STL / 3MF Path**에 슬라이싱할 모델 경로를 넣습니다.

![Print Defaults와 시편 중심 좌표](assets/screenshots/2026-09-29/printer-defaults.png)

**확인:** 단위·프로필·배치가 의도와 맞고 베드 및 이송 경로 안에 들어갑니다.
X/Y를 바꾸면 원본 모델을 다시 슬라이싱해야 합니다.
기본값 저장만으로 기존 G-code 위치가 바뀌지 않습니다.

## Step 3 — 시작·속도·보정 옵션 저장하기

**Print Start & Early Layers**에서 필요한 항목만 조정합니다.

![독립적인 시작 옵션과 저장 버튼](assets/screenshots/2026-09-29/printer-start-options.png)

| 항목 | 확인할 의미 |
|---|---|
| First-layer override | 첫 층 높이·속도·베드 온도는 별도 입력 |
| XYZ speed scale (%) | 1–100 포함, 100은 scale 감속 없음 |
| Start-point prime | 독립 체크박스와 mm 단위 토출량; Z 상승량 아님 |
| Layer 2–5 speed cap | 별도 활성화와 mm/s 속도 |
| Early-layer Z cap | 설정된 초반 레이어 구간에 대한 독립 활성화 |
| Bed leveling / flow calibration | 요청 옵션이며 실제 보정 수행 증거와 별개 |

공통 비율은 **XYZ 이동**에 적용합니다.
저장 key는 호환성을 위해 `xy_speed_scale_percent`를 사용합니다.

1. 체크박스가 꺼져 있어도 원하는 숫자를 입력할 수 있습니다.
2. 적용할 옵션만 체크합니다.
3. **Save Print Defaults**를 누릅니다.
4. 새로고침 후 숫자와 체크 상태가 유지되는지 확인합니다.

**확인:** 저장값이 다시 표시됩니다. 비활성 옵션도 숫자는 보관할 수 있지만
적용하지 않습니다. 기존 파일·진행 중 출력은 바뀌지 않습니다.
**Test Specimen Defaults**는 시편 fallback 설정이지 BO 탐색 범위 편집기가 아닙니다.

## Step 4 — 출력하지 않고 슬라이싱하기

1. source path가 원하는 시편인지 확인합니다.
2. 상단 **Slice Bambu Artifact**를 누릅니다.
3. **Bridge Evidence Log**의 응답을 기다립니다.
4. 결과 파일 경로·hash·배치 검증을 봅니다. 성공하면
   **Bambu Sliced Artifact Path**에 결과가 들어갑니다.
5. 생성 프로젝트/G-code와 제공된 슬라이서 질량·시간 근거를 확인합니다.

![상단 준비·실행 버튼](../gui/assets/screenshots/2026-09-29/printer.png)

**확인:** upload/MQTT publish 없이 sliced artifact ready 결과가 남습니다.
슬라이싱만 검증하려면 여기서 끝냅니다. 경로만 적혀 있고 응답이 실패했다면
완료가 아닙니다. 원본 경로·슬라이서 실행파일/프로필·failure code를 확인합니다.

## Step 5 — 자동 배출을 별도로 검토하기

승인된 자동 배출 구성을 준비할 때 **Bambu G-code Autoejection**을 봅니다.

1. provider·방향·push offset/lane·sweep 설정을 확인합니다.
2. 변경하면 **Save Autoejection Config**로 저장합니다.
3. **Validate G-code Preview**로 루틴을 검토합니다.
4. 배출이 포함된 파일을 만들 때 **Generate Patched Artifact**를 사용하고
   결과 경로와 검증 근거를 확인합니다.

![자동 배출 구성과 파일 생성](assets/screenshots/2026-09-29/printer-ejection.png)

**확인:** 파일 생성·검증 근거이며 실제 배출 완료가 아닙니다.
**Fill Native G-code Defaults**는 로컬 입력을 채우므로 별도 저장·생성이 필요합니다.
배출/sweep test artifact도 실행하면 장비를 움직이는 프로그램입니다.
버튼 확인 목적으로 실행하지 않습니다.

## Step 6 — 실제 완료 증거와 시작 게이트 구분하기

![Physical Proof Package와 완료 감사](assets/screenshots/2026-09-29/printer-proof.png)

**Build Fail-Closed Proof Template**는 채울 증거 양식을 만들고,
**Run Completion Audit**는 그것을 검사합니다. 둘 다 실제 배출 자체가 아닙니다.
**Mark Bed Clear**는 베드 상태에 대한 진술이지 오류 해제 버튼이 아닙니다.
관련 물리 확인 후에만 사용합니다.

실제 감독 출력은 기존 Live 루프의 SPC handoff 경로를 우선 사용합니다.
단독 준비의 **Pre-start Check**, **Print Command Draft**,
**Start Gate Check**, **Publish Start**는 서로 다릅니다.

- draft는 실행 명령이 아닙니다.
- gate 통과는 출력이 아닙니다.
- **Publish Start**는 실제 장비를 시작할 수 있어 슬라이싱 실습 범위 밖입니다.
- upload probe·전송도 프린터 접속/쓰기를 수행할 수 있습니다.

현재 준비된 파일·승인을 사용하고 과거 성공 근거로 대체하지 않습니다.
전송·정리·완료 계약은 [Bambu 브릿지](../../system/device_bridges/bambu_x2d_bridge.md)를 봅니다.

## Step 7 — 런 소유 SPC 근거 확인하기

Live의 **SPC → Report**에서 이번 job ID, 전송/시작 결과, telemetry 시각,
남은 시간, 카메라, 출력 이후 handoff를 봅니다.

![런에 속한 SPC 모니터링](../gui/assets/screenshots/2026-09-29/live-specimen.png)

**확인:** 이번 런·파일의 근거입니다. 프린터가 idle이거나 옛 job이 finished인
것만으로 이번 완료를 판단하지 않습니다. 영상이 멈췄다고 출력이 멈춘 것은
아니므로 telemetry와 frame 시각을 따로 확인합니다.

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

원본 경로·저장 설정·결과 경로/hash·검증 결과를 기록하면 끝입니다.
슬라이싱만 한 실습은 그렇게 명시합니다.

## 다음 문서

- [Printer fleet](../../system/device_bridges/printer_fleet_bridge.md)
- [Bambu 설정과 구현](../../system/device_bridges/bambu_x2d_bridge.md)
- [SPC 근거](../../system/agents/specimen_agent.md)
- [실행 프로필](../../system/runtime/test_mode.md)
- [운영자 실습](user_manual.ko.md)
