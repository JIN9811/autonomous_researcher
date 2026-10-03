<!-- atr-doc
doc_type: guide
subtype: tutorial
status: active
authority: procedural
audience: [user, operator, researcher]
scope: [gui_tutorial, operator_workflow]
summary: Screenshot-led first virtual run, evidence inspection and recovery checkpoints.
source_of_truth:
  - web/templates/index.html
  - web/static/app.js
  - web/templates/planning.html
  - web/static/planning.js
  - utils/test_mode_execution_profiles.py
last_verified: 2026-09-29
verified_against: fcfba9f
related_docs:
  - docs/gui/visual_structure.md
  - docs/runtime/test_mode.md
supersedes: []
-->

# 첫 자율 실험 — 단계별 따라 하기

[English](first_autonomous_run.en.md) · [전체 튜토리얼](first_autonomous_run.md)

## 목표와 준비물

Live 대화로 **가상 실험 1회**를 수행하고 설계·분석·최적화 근거를 찾습니다.
프린터와 로봇은 필요하지 않으며, 가상 결과는 실제 실험 결과가 아닙니다.

- 설치된 AX4LAB, 사용 가능한 LLM 백엔드, 브라우저가 필요합니다.
- 설치 전이라면 [Requirements](../../REQUIREMENTS.md)를 먼저 읽습니다.
- 화면은 1920 × 1080 기준입니다. 캡처의 숫자와 저장값은 해당 환경의 예시이며 권장 설정이 아닙니다.

## Step 1 — 서버와 메인 화면 열기

설치된 워크스테이션의 터미널에서 실행합니다.

```bash
atr up
```

`http://localhost:7860`에 접속합니다. 이미 서버가 실행 중이면 그 서버를
사용합니다. 이 실습 때문에 진행 중인 실험을 재시작하지 않습니다.

![모델 설정과 Run Control이 있는 메인 화면](../gui/assets/screenshots/2026-09-29/main-dashboard.png)

**확인:** Main에 모델·백엔드 설정과 **Run Control**이 보입니다.
모델 로딩과 실험 실행 표시는 다릅니다.
접속되지 않으면 장비 버튼을 누르기 전에 실행 터미널과 서버 상태를 확인합니다.

## Step 2 — 가상 실행 프로필 선택하기

1. **Run Control → Test Mode Settings**를 누릅니다.
2. **Virtual Bridge**를 선택합니다.
3. 에이전트별 물리 실행 경계를 확인합니다. 첫 실습에서는 가상/preflight
   설정을 유지하고 **Real device**로 바꾸지 않습니다.
4. **Total Cycles**를 `1`로 입력하고 **Save profile**을 누릅니다.
5. **Reload**로 다시 읽어 저장값을 확인합니다. 새 런에 적용되는 설정이며
   이미 실행 중이거나 복구한 런의 사이클 수를 바꾸지 않습니다.

![가상 프로필과 장비 실행 경계](../gui/assets/screenshots/2026-09-29/test-mode-settings.png)

**확인:** 저장된 리비전과 가상 실행 범위가 의도한 설정과 일치합니다.
그림의 사이클 수는 캡처 당시 값이며 이 실습의 목표값이 아닙니다.

‘테스트’라는 이름만 보고 다른 프로필을 선택하면 안 됩니다.

| 프로필 | 프린터 경로 | 나머지 장비 |
|---|---|---|
| Virtual Bridge | 가상/preflight 경로 | 가상 프로필에서는 실제 장비 호출 없음 |
| Installed Printer | 슬라이싱 후 배출 전용 파일 전송, 출력 본문·냉각 생략 | 비전·로봇·UTM은 실제 동작 가능 |
| Physical Print | 전체 출력·냉각·설정된 자동 배출 | 비전·로봇·UTM은 실제 동작 가능 |

저장된 에이전트별 개별 설정도 확인합니다. 자세한 실행 규칙은
[Test Mode](../runtime/test_mode.md)에 있습니다.

## Step 3 — Live 대화창 열기

1. Main으로 돌아갑니다.
2. 준비된 **Inference** 백엔드를 고르고 모델/API 연결을 확인합니다.
3. **Mode = live**로 바꾼 뒤 **Start**를 누릅니다.
4. 창이 안 뜨면 로컬 사이트의 팝업 허용을 확인합니다.

![에이전트 목록·리포트·대화가 있는 Live GUI](../gui/assets/screenshots/2026-09-29/live-overview.png)

**확인:** 별도 Live 창과 초기 대화가 열립니다.
이 실습은 대화 기반 진입 경로입니다. Main의 **test → Start**는 직접
run-start 경로를 호출하므로 같은 버튼 순서가 아닙니다.

그림은 과거 런입니다. Live 창이 열렸다고 새 실험이 승인·시작된 것은 아닙니다.

## Step 4 — 테스트 요청과 실험 계획 검토하기

Live 채팅에 아래 예시를 입력합니다.

```text
테스트 모드, 가상 브릿지
```

시나리오 입력기가 기존 Orchestrator 대화 경로로 계획 질문에 응답합니다.
환영 메시지만 보지 말고 **Experiment Contract**와 **Experimental Setup**을
읽습니다.

- 목표·단위, 시편 크기·재료, 설계변수·범위, 실행 프로필, 사이클 수를 확인합니다.
- Gyroid 경로의 설계변수는 **cell size와 wall thickness**입니다. 과거의 상대 밀도 탐색 범위를 그대로 사용하지 않습니다.
- 의도와 다르면 채팅으로 정정합니다.

![실험 계약과 결정 내역](../gui/assets/screenshots/2026-09-29/live-orchestrator.png)

**확인:** 검토된 계약과 이번 런의 실행 승인·인계 기록이 남습니다.
계획 동의와 실행 동의는 다릅니다. 테스트 입력기가 정상 검토 응답을 제공할
수 있지만, 누락된 연결 정보 제공과 물리 동작 확인은 운영자 책임입니다.

- 하지 않은 물리 동작을 했다고 답하지 않습니다.
- 가상 실습에서 물리 확인을 요구하면 실행 프로필을 다시 확인합니다.

## Step 5 — 설계와 시편 준비 확인하기

왼쪽 **DSN → Report**를 선택합니다.

![생성 시편·설계 공간·후보 비교](../gui/assets/screenshots/2026-09-29/live-design.png)

1. 선택 후보가 이번 런·사이클에 속하는지 확인합니다.
2. **Generated Specimens**, **Design Space**, **Candidate Comparison**,
   **Constraint Check**를 읽습니다.
3. **Artifacts**에서 STL을 열어 후보와 연결되는지 확인합니다.
4. **SPC**로 이동해 슬라이싱·준비 근거를 확인합니다.

**확인:** 후보 ID, 현재 제약 검사 결과, 해당 산출물(artifact)이 서로 연결됩니다.
썸네일이 있다는 것만으로 통과가 아닙니다. 슬라이싱 전 질량·시간 공란은
측정값이 아니며, 나중에 기록된 실제 슬라이서/분석 출처를 사용합니다.

## Step 6 — 장비를 따로 실행하지 않고 흐름 관찰하기

![SPC의 준비 상태와 프린터 근거](../gui/assets/screenshots/2026-09-29/live-specimen.png)

왼쪽 목록으로 VIS·MAN·EQP 리포트를 확인합니다. 가상/preflight 결과와
실제 장비의 작업 완료를 구분합니다. 카드가 대기 상태(pending)라고 워크스페이스에서 별도
출력이나 롤아웃을 시작하지 않습니다.

**확인:** 이번 런의 단계별 근거가 쌓이고 ANL로 이어집니다.
멈추면 해당 에이전트의 **Timeline**, **Artifacts**부터 보고 Step 9를 따릅니다.

## Step 7 — 분석과 BO 결과 읽기

**ANL → Report**에서 SS/FD, 단위, 선택 시편, 질량 출처, 물성값을 확인합니다.
이후 **BO → Report**를 선택합니다.

![ANL의 곡선과 응답 근거](../gui/assets/screenshots/2026-09-29/live-analysis.png)

![BO의 포스테리어와 후보 근거](../gui/assets/screenshots/2026-09-29/live-bo.png)

**확인:** 분석 결과가 해당 후보와 연결됩니다.

- GP에는 충분한 관측값이 필요합니다. 초기 LHS만 있는 상태는 그래프 오류가 아닐 수 있습니다.
- 1사이클 실습에서는 새 BO 추천이 생성되지 않을 수 있습니다. 생성되면 2D/3D 평균·불확실성·획득함수와 후보 좌표를 함께 확인합니다.
- 가상 결과를 실측 SEA로 사용하지 않습니다.

그림은 과거 다중 사이클 런이며, 한 사이클의 예상 결과가 아닙니다.

## Step 8 — 산출물과 다시보기 찾기

1. 해당 에이전트의 **Artifacts**를 선택합니다.
2. **All files** 또는 이미지 필터를 선택합니다. 필터 결과가 비었다고 파일이
   사라졌다고 단정하지 않습니다.
3. 실제 존재하는 STL, 곡선 이미지·데이터, BO 파일을 엽니다.
4. 파일 경로와 함께 run ID, cycle, candidate ID를 기록합니다.

![Artifacts의 파일과 그림 미리보기](../gui/assets/screenshots/2026-09-29/live-artifacts.png)

런 기록은 `runs/<run-id>/`, 산출물은 별도 `artifacts/`에도 있습니다.
모든 파일이 런 폴더 안에 있다고 가정하지 말고 기록된 참조를 따릅니다.
Main에서 **replay → Experiment session 선택 → Start**로 다시보기를 엽니다.

![메인의 Replay 모드와 세션 선택](assets/screenshots/2026-09-29/main-replay.png)

**확인:** 장비 실행이 없는 별도 Replay 창이 열립니다.
저장된 시점만 선택 가능하고 오래된 세션은 모든 사이클이 남아 있지 않을 수
있습니다. 자세한 동작은 [Replay](../gui/run_replay.md)를 봅니다.

## Step 9 — 완료 확인 또는 오류 진단하기

수행한 단계의 산출물과 런 종료 결과를 확인하면 실습이 완료됩니다.
화면에 오류가 없다는 것만으로 완료를 판단하지 않습니다.

| 증상 | 먼저 볼 것 | 하지 말 것 |
|---|---|---|
| Live 창이 안 열림 | 팝업 허용, Main의 live 모드 | Start 연타로 새 런 만들기 |
| LLM 응답 대기 | 선택 백엔드·모델·API 오류/할당량 | API 오류를 피해 실험 목표 바꾸기 |
| 물리 확인 요청 | 저장 프로필과 에이전트별 실행 경계 | 하지 않은 동작 확인하기 |
| 카드 공란/pending | 현재 run/cycle, Timeline, 파일 필터·출처 | 과거 성공 결과를 이번 근거로 재사용 |
| 일시정지/오류 | 미해결 원인 수정 후 기존 Resume | 새 Start로 이전 런을 이어가려 하기 |
| 복구 중 물리 동작 필요 | 현장 감독과 실제 장비 상태 | 가상 실습 승인을 장비 승인으로 간주 |

시스템이 유휴 상태이고 종료하려는 경우 `atr down`을 실행합니다.
`atr restart`를 런 복구의 대체 수단으로 사용하지 않습니다.

## 다음 실습

향후 사용할 사이클 수로 설정을 되돌립니다.
실제 장비를 선택하기 전 [운영자 실습](user_manual.ko.md)과
[프린터 설정](device_workspace_3dp_usage.ko.md)을 진행합니다.

## 검증 범위

`fcfba9f`의 템플릿·브라우저 핸들러·런타임 문서와 절차를 대조했습니다.
2026-09-29 화면은 읽기 전용으로 촬영했으며 문서 작성을 위해 새 실험을 실행하지
않았습니다. 화면과 절차를 검증한 것이며, 캡처 속 장비 상태를 새로 물리 검증한 것은 아닙니다.
