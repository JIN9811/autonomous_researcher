# Windows PyAutoGUI Bridge

Windows PyAutoGUI Bridge는 Linux ATR의 `LabEquipmentAgent`가 Windows GUI 기반 장비를 제어할 때 사용하는 경량 실행기입니다. Windows에서는 판단이나 실험 완료 판정을 하지 않고, 검증된 프로그램 실행, 화면 증거 수집, 입력 녹화, 로컬 프로그램 관리만 수행합니다.

## 책임 경계

| 계층 | 소유 기능 |
|---|---|
| Linux ATR | Equipment Profile/Skill 선택, 실행 ID, 증거 검증, 복구 판단, Analysis handoff |
| Equipment Runtime Service | 실행 계약, Worker 선택, 실행 기록, 완료 판정, 화면별 상태 projection |
| Windows Bridge | PyAutoGUI 실행, 화면 캡처, locator, 프로그램 캐시, 녹화, 원시 결과 반환 |
| 브라우저 | 서버 상태 표시. 상태 원본이 아니며 새로고침 시 서버에서 다시 조회 |

UTM은 첫 번째 Equipment Profile일 뿐 Windows Bridge 자체가 UTM 전용은 아닙니다. 장비별 창 이름, 버튼 locator, 저장 절차는 Linux의 Profile/Skill과 배포 프로그램에 둡니다.

## 권장 설치

### 폴더 복사형 포터블 패키지

1. Windows PC에 패키지 폴더 전체를 복사합니다.
2. `START_PORTABLE_BRIDGE.cmd`를 실행합니다.
3. 최초 실행은 폴더 내부 Python과 오프라인 wheel을 준비한 뒤 브라우저를 엽니다.
4. Windows Console의 임시 4자리 코드를 확인합니다.
5. Linux ATR의 Device Workspace > Lab Equipment > Windows Bridge에서 Scan 후 해당 장치를 선택합니다.
6. 4자리 코드를 입력해 Pair & Save를 실행합니다.

포터블 데이터는 패키지의 `data\` 아래에 저장됩니다. 관리자 권한이 없어도 설치할 수 있도록 설계되어 있습니다.

### 표준 설치

Python 3.10 이상이 설치된 Windows에서 다음 파일을 실행합니다.

```text
INSTALL_WINDOWS_BRIDGE.cmd
```

설치 대상은 `INSTALL_WINDOWS_BRIDGE.cmd`가 들어 있는 현재 패키지 폴더입니다.

```text
<copied-package-folder>\Pyautogui_server_for_window
```

설치 후 Desktop/Start Menu 바로가기로 실행할 수 있습니다.

설치기는 다른 위치에 프로그램을 복사하지 않습니다. 패키지 폴더 안에 `.venv`를 구성하고 바로가기와 로그온 작업도 같은 폴더의 `scripts\start_supervisor.ps1`을 가리킵니다. 원격 updater는 현재 실행한 패키지 폴더에만 릴리스를 적용하고 같은 폴더에서 재시작합니다. 로그, 녹화, 프로그램과 아티팩트는 `%LOCALAPPDATA%\ATR\PyAutoGUIBridge`에 분리 저장합니다.

일반 시작은 `scripts\start_supervisor.ps1`만 사용합니다. 시작 명령과 예약 작업에는 릴리스 번호를 넣지 않으며, supervisor가 현재 패키지 폴더의 Worker를 감시하고 비정상 종료 시 다시 실행합니다. 현재 버전과 원격 업데이트 파일 목록의 단일 원본은 `release_manifest.json`입니다. 설치 시 대화형 사용자 로그온 예약 작업이 기본 등록되며 Windows 서비스는 사용하지 않습니다.

### 개발 실행

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -OpenBrowser
```

로컬 PC에서만 열려야 하는 개발 세션은 `-LocalOnly`를 사용합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -LocalOnly -OpenBrowser
```

기본 주소는 `http://127.0.0.1:8765/`입니다.

## 4자리 페어링

사용자가 장기 인증키를 입력하거나 복사하지 않습니다.

- 코드는 숫자 4자리이며 5분 동안 유효합니다.
- 최대 5회 입력할 수 있습니다.
- 성공 즉시 폐기되고 재사용할 수 없습니다.
- 5회 실패하면 30초 동안 잠깁니다.
- 성공 후 양쪽은 내부 장기키를 보호된 설정 파일에 저장합니다.
- 코드와 내부키는 URL, 브라우저 저장소, request audit에 기록하지 않습니다.
- 이후 재시작은 저장된 내부키를 사용하므로 별도 질문 없이 연결됩니다.

4자리 코드는 최초 연결 키 교환에만 사용합니다. 연결이 저장된 뒤에는 사용자가 코드를 다시 입력하지 않으며, 저장된 worker secret 또는 교환된 내부키로 자동 인증합니다. 녹화 시작·상태·미리보기·중지·저장·삭제는 pairing 상태와 무관하게 사용할 수 있지만, 녹화 package 반출과 원격 실행·업데이트는 저장된 연결 인증이 필요합니다.

## Windows Console

기본 화면은 네 영역으로 제한됩니다.

### Bridge Status

서버, PyAutoGUI, 데이터 경로, 페어링 상태를 표시합니다. `Health`, `Refresh`, `New Code`만 제공합니다.

### Program Manager

- `program1`: 삭제할 수 없는 기본 데모
- Add: 빈 편집기에서 로컬 프로그램 작성
- Browse JSON: 기존 프로그램 JSON 불러오기
- Template: 프로그램 템플릿 다운로드
- Validate: 실행 전 계약 검증
- Save: 로컬 초안 저장
- Test: 선택한 로컬 프로그램 실행
- Delete: 삭제 가능한 로컬 초안 제거

ATR이 배포한 프로그램은 읽기 전용 캐시이며 Windows에서 직접 수정하지 않습니다.

### Recording

`START RECORDING`을 누르면 5초 뒤 입력 녹화를 시작합니다. 녹화 중에는 최상위 오버레이에 경과 시간과 유일한 사용자 중단 조작인 `STOP` 버튼이 표시됩니다. Bounded Evidence 카드는 녹화 상태와 Checkpoint만 표시하고 별도 Stop 버튼을 만들지 않습니다. 오버레이 `STOP`은 즉시 UI를 닫고 백그라운드에서 `RecordingManager.stop()`을 한 번만 호출합니다. Console은 활성 녹화 중에만 `/recordings/status`를 확인하여 오버레이 종료 후 idle 상태와 목록을 자동 동기화합니다. STOP 클릭은 원시 시계열의 출처 증거로 보존하되 `recording_control=overlay_stop`으로 표시하며, Linux Skill 컴파일과 capability 집계에서는 장비 액션으로 취급하지 않습니다.

- 키보드/마우스 입력은 monotonic timestamp로 기록됩니다.
- 녹화 시작부터 종료까지 전체 화면을 고정 2 FPS로 즉시 디스크에 저장합니다.
- 주기 프레임은 `frames/periodic/frame-XXXXXXXX.jpg`, 이벤트·경계 프레임은 PNG로 저장하고 `timeline.jsonl`에서 시간순으로 연결합니다.
- RAM에는 행동 직전 증거를 찾기 위한 최근 프레임만 제한적으로 유지하며, 전체 세션 증거는 RAM 순환 버퍼가 아니라 디스크가 소유합니다.
- 디스크 경고 임계값에서는 녹화를 유지하며 상태를 표시하고, 임계 임계값이나 쓰기 실패에서는 이미 기록한 증거를 보존한 불완전 패키지로 안전 종료합니다.
- 오버레이 Stop과 Console의 Checkpoint, Preview, Export, Delete를 지원합니다. Preview는 저장된 프레임을 페이지 단위로 이전/다음 확인하며 Windows 절대경로를 브라우저에 노출하지 않습니다.

Windows는 녹화 원본만 만듭니다. Linux ATR은 16개 프레임을 4x4 시간 스토리보드로 구성하고, 선택된 multimodal 모델로 모든 청크를 순서대로 분석한 뒤 전체 흐름을 합성합니다. LLM 어노테이션, Skill 컴파일·검증·버전·배포는 Linux ATR이 수행하며 정상 Skill 실행에는 LLM을 다시 호출하지 않습니다.

### Latest Local Result

최근 Health, 프로그램 검증/테스트, 녹화 결과와 오류 코드를 표시합니다. 원시 JSON과 request log는 접힌 `Diagnostics`에서 요청할 때만 읽습니다.

## Saved Worker 원격 업데이트

Linux `Lab Equipment Workspace > Connection & Profile > Saved Worker`에서 Worker별로 다음 작업을 수행할 수 있습니다.

- `Check Update`: 현재 Worker 버전과 Linux package의 최신 버전을 비교합니다.
- `Update`: bounded release manifest의 파일만 staging한 뒤 Worker를 재시작합니다.
- `Rollback`: 가장 최근의 검증된 backup으로 복원하고 Worker를 재시작합니다.

원격 업데이트 자체를 제공하지 않는 구버전 Worker는 최초 한 번 이 package로 수동 설치하거나 폴더를 교체해야 합니다. 그 이후 버전부터 Saved Worker에서 원격 업데이트할 수 있습니다.

업데이트는 최초 연결 때 저장한 worker secret 또는 4자리 pairing으로 교환한 내부키를 자동 사용합니다. 별도 공개키 전자서명은 사용하지 않지만, 파일별 SHA-256과 package digest, 상대경로 allowlist, 크기 제한을 모두 검증합니다. 적용 대상은 canonical 설치 경로 하나이며 server, supervisor, updater, start/run launcher, installer, `requirements-windows.txt`를 함께 갱신합니다. 적용 중에는 `updates\update_in_progress.json` 잠금을 두어 supervisor가 교체 중인 Worker를 중복 실행하지 않으며, 기존 파일은 `updates\backups`에 보존합니다. 새 Worker의 경량 평문 `/ping`이 30초 안에 **manifest의 목표 릴리스 버전**을 반환하지 않으면 직전 backup을 복원합니다. updater 자체 복구가 실패해도 독립 supervisor가 잠금 해제 후 canonical Worker를 다시 실행합니다. 일반 Python 설치는 `requirements-windows.txt`가 직전 버전과 달라진 경우에만 같은 interpreter로 dependency를 동기화하고, frozen EXE 배포본은 빌드에 포함된 dependency를 사용합니다.

다음 항목은 업데이트하지 않습니다.

- pairing/internal key
- recordings, programs, locators, artifacts, UTM export
- 사용자별 data root와 runtime evidence

녹화 세션이 활성 상태이면 Update와 Rollback은 차단됩니다. 먼저 녹화를 Stop/Save한 뒤 다시 실행하십시오.

## 데이터 디렉터리

표준 설치 기본값:

```text
%LOCALAPPDATA%\ATR\PyAutoGUIBridge
  artifacts\     화면, 요청 로그, 실행 결과
  locators\      이미지 locator
  programs\      로컬 초안과 ATR 배포 캐시
  recordings\    녹화 manifest, event, keyframe
  utm_exports\   UTM Profile이 사용하는 결과 파일 영역
```

Skill의 원본은 Linux `memory/equipment_skills/`입니다. Windows `programs\`는 로컬 초안 또는 검증된 배포 캐시입니다.

## 운영 확인

Windows에서:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_bridge.ps1
```

`check_bridge.ps1`은 로컬 Health와 페어링 상태만 확인합니다. `test_bridge.ps1`은 페어링된 경우 `program1` 실행까지 확인합니다.

Linux에서는 ATR Device Workspace에서 다음 순서로 확인합니다.

1. Scan (코드 없이 후보 검색)
2. Candidate 카드에 4자리 코드를 입력해 Pair & Save 또는 저장 장치 Select
3. Health
4. Programs
5. Test selected bridge

실험 루프는 Windows Console 버튼이 아니라 `LabEquipmentAgent -> EquipmentRuntimeService -> equipment.pyautogui.run` 경로를 사용합니다. `utm.run_protocol`로 자동 전환하지 않습니다.

## 주요 API

| 메서드 | 경로 | 역할 |
|---|---|---|
| GET | `/ping` | supervisor/updater 전용 경량 평문 생존 확인, 감사 로그 미기록 |
| GET | `/discovery` | 인증 전 후보 검색용 최소 메타데이터 |
| GET | `/health` | Bridge/PyAutoGUI/경로 상태 |
| GET | `/pairing/status` | 로컬 페어링 상태 |
| POST | `/pairing/new-code` | 로컬 새 4자리 코드 |
| POST | `/pairing/complete` | Linux가 일회성 코드 교환 |
| GET | `/programs` | 프로그램 목록 |
| POST | `/programs/validate` | 프로그램 검증 |
| POST | `/programs/register` | 로컬/배포 프로그램 등록 |
| DELETE | `/programs/{id}` | 삭제 가능한 로컬 프로그램 제거 |
| POST | `/execute` | 검증된 프로그램 실행 |
| POST | `/screenshot` | 화면 증거 캡처 |
| POST | `/locators/capture` | locator 기준 이미지 저장 |
| GET/POST/DELETE | `/recordings/...` | 녹화 수명과 아티팩트 관리 |
| GET | `/recordings/{id}/package` | 인증된 녹화 증거 package 전송 |
| GET | `/artifacts` | 원시 아티팩트 목록 |
| GET | `/request-log` | 요청 감사 로그 |
| GET | `/update/status` | 현재/staging/rollback 가능 버전 상태 |
| POST | `/update/stage` | allowlist와 SHA-256 검증 후 release staging |
| POST | `/update/apply` | 별도 updater로 교체·재시작·Health 검증 |
| POST | `/update/rollback` | 최근 backup 복원·재시작 |

원격 실행·화면·아티팩트 경로는 페어링 이후 내부키 인증이 필요합니다.

## 안전 경계

- `pyautogui.FAILSAFE`를 유지합니다.
- 실행 프로그램은 허용된 bounded action만 포함해야 합니다.
- 비밀번호, API key, 페어링 코드, 내부키를 프로그램 payload에 넣지 않습니다.
- Windows Bridge는 Guardian 판정, LLM 복구, 실험 단계 전환, Analysis handoff를 수행하지 않습니다.
- 장비 물리 검증은 해당 Profile의 별도 승인 절차를 따릅니다.

상세 절차는 [docs/USAGE.md](docs/USAGE.md)를 참고하십시오.
