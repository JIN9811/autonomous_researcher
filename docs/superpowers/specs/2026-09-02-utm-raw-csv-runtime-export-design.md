# UTM Raw CSV Runtime Export Design

## 목적

TRAPEZIUM-X의 `Save Raw Data to CSV File` 흐름을 실험마다 바뀌는 식별자에 맞춰 안전하게 실행한다. 스킬은 경로를 직접 입력하지 않으며, Windows PyAutoGUI 워커가 소유한 고정 출력 루트와 구조화된 실행 변수를 조합해 파일명을 만든다. 저장 전 중복을 차단하고, 저장 후 생성된 CSV를 검증해 Linux 아티팩트로 회수한다.

## 범위

- `utm_save_raw_data` 스킬의 dry-run, test, live 실행 계약
- Windows 워커의 Raw CSV 경로 생성, 중복 검사, 예약, 클립보드 붙여넣기 및 파일 검증
- Agent Manager에서 실행 모드와 파일명 구성 변수를 확인하고 시험 실행하는 UI
- 저장된 CSV의 아티팩트 인덱싱 및 Linux 회수

시험 시작, UTM 하중 제어, `Next Test`, CSV 내용 분석은 이 변경의 범위 밖이다.

## 저장 위치

Raw CSV의 Windows 저장 루트는 AppData가 아니라 PyAutoGUI 서버 패키지 내부의 다음 고정 위치다.

```text
<pyautogui-server-package-root>\artifacts\raw_csv\
```

서버 패키지 루트는 `ATR_WINDOWS_BRIDGE_PACKAGE_ROOT`를 우선 사용하고, 없으면 실행 중인 서버 소스 또는 번들 위치에서 결정한다. 클라이언트와 에이전트는 이 루트를 변경하거나 전체 출력 경로를 전달할 수 없다.

## 실행 컨텍스트

상위 에이전트는 다음 구조화된 값만 전달한다.

```json
{
  "mode": "dry_run | test | live",
  "session_id": "session-20260902-A",
  "specimen_id": "cube-03",
  "loop_index": 2,
  "repeat_index": 4
}
```

규칙:

- `session_id`와 `specimen_id`는 필수다.
- `loop_index`와 `repeat_index`는 1 이상의 정수다.
- 문자열은 Unicode NFKC로 정규화한다.
- Windows 금지 문자, 제어 문자, 공백 및 식별자 내부의 `_`는 `-`로 치환하고 연속 `-`는 하나로 줄인다.
- 필드 사이 구분자에만 단일 `_`를 사용하므로 생성된 파일명에는 `__`가 존재하지 않는다.
- 정규화 후 빈 식별자는 거부한다.
- 전체 파일명 길이는 Windows 경로 제한을 고려해 제한하며, 임의 경로 구분자와 `..`는 거부한다.

## 파일명

파일명은 워커가 다음 규칙으로 생성한다.

```text
{mode}_{session_id}_{specimen_id}_loop-{loop_index:04d}_rep-{repeat_index:04d}.csv
```

예시:

```text
live_session-20260902-A_cube-03_loop-0002_rep-0004.csv
```

모드가 파일명에 포함되므로 테스트 데이터와 실제 실험 데이터가 섞여도 출처를 구분할 수 있다. 자동 타임스탬프나 자동 숫자 증가는 사용하지 않는다. 동일한 실험 키가 재사용되면 잘못된 실행 컨텍스트로 간주해 차단한다.

## 중복 방지와 예약

저장 버튼을 누르기 전에 다음 순서로 검사한다.

1. 최종 CSV 경로가 고정 `raw_csv` 루트 내부인지 확인한다.
2. 동일 경로의 CSV가 이미 존재하면 `UTM_RAW_CSV_ALREADY_EXISTS`로 차단한다.
3. 동일 파일명의 활성 예약이 있으면 `UTM_RAW_CSV_NAME_RESERVED`로 차단한다.
4. test/live 모드는 원자적 파일 생성 방식으로 예약 파일을 만든다.
5. 예약을 얻은 실행만 GUI 저장을 진행한다.
6. 성공 시 CSV 검증 후 예약을 제거한다.
7. 실패 시 예약을 제거하되 실패 증거와 원인을 남긴다.

`dry_run`은 존재 여부와 활성 예약 여부를 확인하지만 예약 파일은 만들지 않는다. 중복 발생 시 덮어쓰기 확인창을 처리하거나 자동으로 다른 이름을 만들지 않는다.

## 모드

### dry_run

- Windows GUI를 클릭하지 않는다.
- 파일을 생성하거나 예약하지 않는다.
- 정규화된 실행 컨텍스트, 최종 파일명, 최종 Windows 경로, 중복 여부를 반환한다.
- 충돌 또는 잘못된 입력은 실패로 반환한다.

### test

- 실제 Windows 저장창과 Raw CSV 버튼을 사용한다.
- 파일명은 `test_`로 시작한다.
- 명시적 실행 확인이 필요하다.
- live와 동일한 검증, 예약, 붙여넣기, 파일 안정화 및 아티팩트 회수를 수행한다.

### live

- 현재 실험 세션의 실행 컨텍스트를 사용한다.
- 파일명은 `live_`로 시작한다.
- 명시적 실행 확인이 필요하다.
- 기본값이나 테스트 식별자로 대체하지 않는다. 필수 컨텍스트가 없으면 저장 전에 차단한다.

## 저장 스킬 흐름

`utm_save_raw_data`의 test/live 흐름은 다음과 같다.

1. 실행 컨텍스트를 검증하고 최종 경로를 생성한다.
2. 기존 CSV 및 활성 예약을 사전 검사한다.
3. 파일명을 원자적으로 예약한다.
4. `Save Raw Data to CSV File` 버튼을 이미지로 찾아 클릭한다.
5. 저장창이 준비될 때까지 기다린다.
6. 파일명 입력란을 `Ctrl+A`로 선택한다.
7. 기존 Windows 클립보드 값을 보관한다.
8. 최종 경로를 클립보드에 기록하고 `Ctrl+V`로 붙여넣는다.
9. 기존 클립보드 값을 복원한다.
10. Enter로 저장한다.
11. 정확한 최종 경로의 CSV가 생성되고 지정 시간 동안 안정적인지 확인한다.
12. CSV 기본 파싱 검증, SHA-256, 크기 및 행·열 probe를 기록한다.
13. 전체 화면을 캡처하고 CSV를 Linux 아티팩트로 회수한다.
14. 예약을 해제하고 결과를 반환한다.

클립보드 접근 또는 붙여넣기가 실패하면 `pyautogui.write()`로 폴백하지 않는다. 저장을 중단하고 명시적인 실패를 반환한다. 이 정책은 한글을 포함한 식별자와 키보드 레이아웃 차이에서 잘못된 경로가 입력되는 것을 막는다.

## API와 Agent Manager

정확한 저장 스킬 실행 요청은 `mode`, `session_id`, `specimen_id`, `loop_index`, `repeat_index`를 받는다. Agent Manager는 다음을 표시한다.

- 선택된 실행 모드
- 입력 실행 컨텍스트
- 워커가 계산한 최종 파일명과 경로
- `available`, `already_exists`, `reserved` 상태
- 실행 후 Windows 경로, Linux 회수 경로, SHA-256 및 CSV probe

Agentic Task 실행에서는 `session_id`와 `specimen_id`를 현재 실험 상태에서 가져오고, 루프와 반복 인덱스를 현재 실행 계획에서 가져온다. 테스트 UI의 수동 입력은 test 모드에만 사용하며 live 실행의 실험 컨텍스트를 덮어쓸 수 없다.

## 아티팩트 계약

성공 결과는 최소한 다음을 포함한다.

```json
{
  "mode": "live",
  "filename": "live_session-20260902-A_cube-03_loop-0002_rep-0004.csv",
  "windows_path": "<package-root>\\artifacts\\raw_csv\\...csv",
  "linux_path": "/home/jin/autonomous_researcher/artifacts/equipment/...csv",
  "sha256": "...",
  "size_bytes": 1234,
  "row_count_probe": 100,
  "columns_probe": ["..."]
}
```

요청 로그에는 실행 컨텍스트와 최종 파일명을 남기되 클립보드의 이전 내용은 기록하지 않는다.

## 오류 처리

- 경로 이탈: `UTM_RAW_CSV_PATH_OUTSIDE_ROOT`
- 잘못된 실행 컨텍스트: `UTM_RAW_CSV_CONTEXT_INVALID`
- 기존 파일 충돌: `UTM_RAW_CSV_ALREADY_EXISTS`
- 활성 예약 충돌: `UTM_RAW_CSV_NAME_RESERVED`
- 클립보드 실패: `UTM_RAW_CSV_CLIPBOARD_FAILED`
- 저장창 또는 GUI locator 실패: 기존 시각 제어 오류 코드 사용
- 파일 미생성 또는 안정화 실패: 기존 UTM export 오류 코드 사용

실패 시 저장 이후 단계와 `Next Test`는 실행하지 않는다.

## 테스트 전략

- 파일명 정규화와 포맷 단위 테스트
- 경로 이탈, Windows 금지 문자, 빈 값, 길이 제한 테스트
- 기존 파일 및 예약 충돌 테스트
- 동시 예약 중 하나만 성공하는 테스트
- dry-run이 GUI, 파일, 예약을 변경하지 않는 테스트
- test/live가 직접 타이핑 없이 클립보드 붙여넣기를 사용하는 워커 테스트
- 클립보드 복원 및 실패 시 비폴백 테스트
- 정확한 파일 안정화, CSV probe 및 Linux 아티팩트 회수 테스트
- Agent Manager의 모드별 미리보기·충돌·결과 표시 테스트
- 실제 Windows test 실행 전에 dry-run 결과와 워커 계산 결과가 동일한지 검증

## 배포

변경된 `utm_save_raw_data`는 새 정확 버전으로 배포한다. Agent Manager 블록을 새 버전에 연결한 뒤 이전 버전은 비활성화하고 워커 및 로컬 레지스트리에서 삭제한다. Windows 워커는 원격 업데이트하되 LeRobot 훈련과 주 서버는 재시작하지 않는다. 워커 업데이트가 필요한 경우 해당 워커만 재시작한다.
