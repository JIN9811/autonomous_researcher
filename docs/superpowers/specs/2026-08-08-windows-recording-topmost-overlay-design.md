# Windows Recording Topmost Overlay Design

## Goal

Windows PyAutoGUI bridge의 Skill 녹화를 5초 준비 카운트다운 뒤 시작하고, 녹화 중에는 데스크톱 최상위에 작은 상태 배너를 표시한다.

## Operator Flow

1. Program Manager의 `Record` 버튼을 누른다.
2. 같은 버튼에 `STARTING IN 5`부터 `STARTING IN 1`까지 표시된다.
3. 카운트다운이 끝나면 기존 `/recordings/start` 경로로 마우스·키보드 녹화를 시작한다.
4. 버튼은 `STOP RECORDING`으로 바뀌고 Windows 최상위 배너에 빨간 점, `RECORDING`, 경과 시간이 표시된다.
5. 같은 버튼을 다시 누르면 기존 `/recordings/stop` 경로로 녹화를 종료하고 배너를 제거한다.
6. 카운트다운 중 같은 버튼을 누르면 시작을 취소한다.

## Architecture

- 카운트다운과 단일 토글 상태는 기존 standalone console의 JavaScript가 담당한다. 카운트다운 중에는 서버 녹화 리스너가 시작되지 않는다.
- `RecordingOverlayController`는 Tkinter를 지연 로드하고 전용 daemon thread에서 borderless/topmost 배너를 관리한다.
- `RecordingManager`가 오버레이를 주입받아 녹화 시작 성공 후 `show()`하고 정지·시작 실패·서버 종료 시 `hide()` 또는 `shutdown()`한다.
- Tkinter 또는 데스크톱 표시가 불가능해도 녹화 기능 자체는 유지하고 오버레이 상태만 unavailable로 보고한다.

## UI Contract

- 녹화 시작/정지는 `recordToggle` 버튼 하나만 사용한다.
- 카운트다운 상태: `STARTING IN N`, 두 번째 클릭은 취소.
- 녹화 상태: `STOP RECORDING`, 붉은 강조.
- idle 상태: `RECORD`.
- Checkpoint, Save Recording, Refresh, 기존 이미지 추적 옵션은 유지한다.
- 새로고침 시 `/recordings/status`를 기준으로 토글 상태를 복원한다.

## Native Overlay Contract

- Windows에서만 실제 Tk 창을 생성한다.
- `overrideredirect(True)`, `-topmost`, 작은 상단 중앙 배치.
- 빨간 상태 점, `RECORDING`, `HH:MM:SS` 경과 시간.
- 오버레이는 표시 전용이며 중지는 브라우저의 동일 토글 버튼으로 수행한다.
- 녹화 종료, 실패, 서버 종료 후 남아 있는 창이나 thread가 없어야 한다.

## Non-Goals

- 녹화 이벤트 schema, image locator capture, checkpoint, Skill draft 생성 규약을 변경하지 않는다.
- 오버레이 클릭으로 녹화를 제어하지 않는다.
- 별도 TTS, 영상 녹화, LLM 추론을 추가하지 않는다.

## Verification

- 오버레이 controller의 show/hide/shutdown 수명주기를 가짜 Tk root로 단위 테스트한다.
- RecordingManager 시작 성공·실패·정지 시 오버레이 호출을 단위 테스트한다.
- HTML/JavaScript에 단일 토글, 5초 카운트다운, 상태 복원 로직이 존재하는지 테스트한다.
- source와 install 배포본의 parity, Python compile, Selenium GUI audit를 검증한다.
