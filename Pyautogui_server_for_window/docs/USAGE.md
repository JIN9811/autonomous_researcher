# Windows PyAutoGUI Bridge 상세 사용법

## 1. 설치 방식 선택

### 포터블

배포받은 폴더에서 `START_PORTABLE_BRIDGE.cmd`를 실행합니다. 첫 실행은 포함된 Python 설치 파일과 wheelhouse로 폴더 내부 런타임을 구성합니다. 시스템 Python과 전역 PATH를 변경하지 않습니다.

### 표준 설치

```text
INSTALL_WINDOWS_BRIDGE.cmd
```

설치 스크립트는 현재 패키지 폴더 안에 `.venv`를 만들고 바로가기를 생성합니다. 다른 프로그램 폴더로 복사하지 않습니다. 이후 START 버튼, supervisor와 원격 updater는 모두 현재 패키지 폴더를 사용하며, 로그·녹화·아티팩트만 `%LOCALAPPDATA%\ATR\PyAutoGUIBridge`에 저장합니다.

START 버튼과 로그온 예약 작업은 릴리스 번호가 없는 현재 폴더의 `scripts\start_supervisor.ps1`을 실행합니다. supervisor는 같은 폴더의 Worker 상태를 5초마다 경량 평문 `/ping`으로 확인하며 이 요청은 화면 및 감사 로그에 누적하지 않습니다. 버전은 소스나 시작 명령이 아니라 `release_manifest.json`에서 읽습니다. 실제 후보 검색용 `/discovery`는 supervisor가 반복 호출하지 않습니다. 이전 인자로 이미 실행 중인 supervisor의 localhost `/discovery` 요청도 버전 확인용 최소 JSON만 반환하고 감사 로그에 남기지 않습니다. 업데이트 중에는 data root의 `updates\update_in_progress.json` 잠금으로 중복 시작을 막습니다.

### 소스 개발

```powershell
cd <package-root>
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -OpenBrowser
```

사용 포트를 바꾸려면 실행 전에 환경변수를 지정합니다.

```powershell
$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765"
```

## 2. 최초 페어링

1. Windows Console의 Bridge Status에서 숫자 4자리를 확인합니다.
2. Linux ATR Main GUI에서 Device Workspace를 엽니다.
3. Lab Equipment Workspace > Windows Bridge에서 네트워크 Scan을 실행합니다.
4. 검색된 candidate를 선택하고 4자리 코드를 입력합니다.
5. `Pair & Save`를 누릅니다.
6. 저장할 장치 alias를 지정합니다.
7. Health 결과가 `paired/ready`인지 확인합니다.

코드가 만료되면 Windows Console에서 `New Code`를 누릅니다. 5회 실패 후에는 30초 뒤 새 코드를 발급합니다.

내부 인증키는 사용자가 볼 필요가 없습니다. Windows는 활성 data root의 `artifacts\pairing.json`, Linux는 기존 Windows Bridge connection memory의 보호 필드에 저장합니다. 두 파일은 Git에 포함하지 않습니다.

## 3. 재접속

페어링된 장치는 ATR Workspace의 saved devices에 나타납니다.

1. 장치 Select
2. Health
3. Programs 또는 Test selected bridge

IP가 변경되면 Scan으로 같은 Bridge를 다시 찾고 저장 설정을 갱신합니다. 내부키가 유효한 동안 새 코드는 요구하지 않습니다.

## 4. Program Manager

### 기본 데모 실행

`program1`은 설치 검증용 내장 프로그램입니다. 삭제하거나 덮어쓸 수 없습니다.

### 새 프로그램 작성

1. Add
2. Program ID, 이름, 대상 창, action 입력
3. Validate
4. Save
5. Test

### JSON 파일 불러오기

1. Browse JSON
2. 파일 선택
3. Validate
4. Save

Browse는 파일을 읽는 동작이고 Add는 새 초안을 생성하는 동작입니다.

### Template

Template 버튼은 현재 지원되는 프로그램 형식의 JSON 예제를 저장합니다. 템플릿을 수정해 Browse JSON으로 다시 불러올 수 있습니다.

### 프로그램 소유권

- `builtin`: 설치 포함, 읽기 전용
- `local_draft`: Windows에서 작성한 초안, 로컬 테스트만 가능
- `deployed`: Linux ATR이 검증·해시 확인 후 배포, 읽기 전용
- `retired`: 신규 실행 금지, 감사용 보존

실험 루프는 Linux catalog가 허용한 builtin/deployed 프로그램만 실행합니다.

## 5. Recording

### 녹화 시작

1. Name, Target app, Target window 입력
2. Image tracking 여부 선택
3. START RECORDING
4. 5초 카운트다운 동안 대상 창으로 이동
5. 상단 `REC` 오버레이가 나타난 뒤 작업 수행
6. 필요한 지점에서 Checkpoint
7. 최상위 녹화 오버레이의 `STOP` 클릭
   - 사용자 중단 조작은 오버레이 버튼 하나만 사용합니다.
   - Bounded Evidence에는 별도 Stop 버튼이 나타나지 않습니다.
   - 오버레이 버튼은 UI thread를 막지 않고 종료 저장을 background에서 수행하며 Console 상태는 자동으로 idle에 동기화됩니다.

### 저장 데이터

각 recording 폴더는 다음 자료를 포함할 수 있습니다.

- `recording.json`: 버전, 대상, 상태, timeline 정보
- `events.jsonl`: 키보드/마우스 event와 monotonic timestamp
- `frames/periodic/`: 녹화 전체 구간의 2 FPS JPEG 원본
- `timeline.jsonl`: periodic/event/boundary frame의 append-only 시간순 인덱스
- `keyframes/`, `timeline/event_keyframes/`: event/checkpoint 시점의 PNG 증거
- locator/checkpoint metadata

전체 periodic frame은 녹화 시작부터 종료까지 고정 2 FPS로 디스크에 즉시 저장됩니다. 메모리는 행동 직전 프레임 판정을 위한 작은 최근 프레임 캐시만 유지합니다. 정상 녹화 길이나 frame 수에 임의 상한을 두지 않으며, 디스크 임계 상태에서는 이미 저장한 자료를 삭제하지 않고 `evidence_complete=false`인 부분 패키지로 종료합니다.

### 녹화 이후

Preview에서 저장된 keyframe을 이전/다음으로 확인합니다. Linux Lab Equipment Workspace는 선택된 Worker의 Recording 목록을 직접 조회하며, 항목을 선택하면 Recording ID와 Worker ID를 채웁니다. 이후 `Import & Build Draft`가 인증된 package를 가져옵니다. Linux에서 다음을 수행합니다.

```text
transfer -> annotate -> build skill -> validate -> approve -> deploy
```

전송 시 Linux는 인증된 `/recordings/{id}/package`를 호출하고 각 파일의 크기와
SHA-256을 검증합니다. 검증된 파일만 Linux artifact root에 저장됩니다.

선택된 Local/API LLM은 Linux에서만 사용됩니다. Windows에는 LLM과 API key가 필요하지 않습니다.

녹화 종료 시 오버레이를 먼저 숨기고 최종 화면을 시계열 evidence에 추가합니다. Linux는 16개 frame씩 4x4 스토리보드를 만들고 선택된 multimodal backend로 모든 청크를 순서대로 분석한 후, 청크 결과와 session overview를 한 번 최종 합성합니다. 완료된 청크 분석은 디스크에 보존되며 Stop 요청은 청크 경계에서 처리됩니다. Windows worker는 이 해석을 수행하거나 저장된 Skill 의미를 임의로 변경하지 않습니다.

## 6. Linux Equipment Runtime 연동

실험 루프 실행 경로:

```text
LabEquipmentAgent
  -> EquipmentRuntimeService
  -> selected Equipment Profile / Skill
  -> Windows bridge /execute
  -> raw evidence collection
  -> one completion interpretation
  -> Analysis handoff or explicit block
```

모든 화면은 같은 `execution_id`의 기록을 읽습니다. 표시 상태는 Profile, Skill, provider 계약에 따라 달라질 수 있으며 하나의 고정 상태 순서를 모든 장비에 강제하지 않습니다.

Windows Worker는 다음 판단을 하지 않습니다.

- 다음 Agent 선택
- Guardian 승인
- 실험 완료 판정
- LLM 복구 전략
- Analysis handoff

## 7. Vision Link

Vision Link는 Equipment Profile에서 선택적으로 활성화합니다.

- 비활성: 화면 locator, 실행 결과, 파일 증거만 사용
- 활성: Linux Equipment Runtime이 Vision Agent Bridge에 관측 요청
- 기존의 신선하고 identity가 일치하는 Vision evidence가 있으면 재사용 가능
- 증거도 없고 Vision tool도 없으면 실행 전 명시적으로 차단
- Vision Agent는 관측 결과만 반환하고 Windows 입력을 직접 제어하지 않음

## 8. Diagnostics

기본 Console 아래의 Diagnostics는 필요할 때만 펼칩니다.

### 로컬 상태 확인

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_bridge.ps1
```

### 페어링 후 실행 확인

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_bridge.ps1
```

### 확인 항목

- server bind host/port
- PyAutoGUI import와 failsafe
- data root 쓰기 가능 여부
- pairing status
- program catalog
- recording manager
- request audit

## 9. 방화벽

내부망의 Linux ATR 한 대만 허용하는 구성이 권장됩니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\firewall_allow_private.ps1 -RemoteAddress <linux-private-ip>
```

사설망 전체 허용은 관리자가 명시적으로 선택한 경우에만 사용합니다.

## 10. 장애 처리

### Bridge가 검색되지 않음

- Windows에서 서버가 실행 중인지 확인
- `0.0.0.0:8765` bind 여부 확인
- Windows 방화벽 inbound rule 확인
- Linux와 Windows가 같은 내부망 경로를 사용하는지 확인

### Pairing code invalid/expired

- 숫자 4자리인지 확인
- Windows Console에서 New Code
- 5회 실패했다면 30초 대기

### PyAutoGUI unavailable

- 대화형 Windows desktop session인지 확인
- 화면 잠금/RDP 종료 상태 확인
- 의존성 설치 확인

```powershell
.\.venv\Scripts\python.exe -m pip check
```

### Program validation failed

Latest Local Result의 failure code를 확인합니다. 허용되지 않은 action, 누락된 target window, locator 경로, timeout을 수정한 뒤 다시 Validate합니다.

### Recording failed

- `pynput`, Pillow, PyAutoGUI 설치 확인
- 대상 desktop session 활성화
- Recording 중인 기존 세션을 Stop
- `recordings\` 쓰기 권한 확인

## 11. 배포 검증

릴리스 생성 전:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -InstallBuildDeps
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\native_acceptance.ps1
```

Linux 저장소에서는 packaging/unit/integration 테스트로 다음을 확인합니다.

- source/install server parity
- 긴 토큰 UI/문구 미포함
- 4자리 pairing 규칙
- Console 네 영역
- recording delete와 bounded frame buffer
- generic profile과 Vision Link
- canonical Equipment runtime projection

물리 장비 실행은 자동 검증에 포함하지 않으며 Profile별 승인된 현장 절차로 별도 수행합니다.
