# Windows PyAutoGUI Bridge 사용법

## 0. 최초 설치

release ZIP을 푼 다음 `INSTALL_WINDOWS_BRIDGE.cmd`를 더블클릭합니다. 설치
파일은 현재 폴더를 자동 감지하고 설치 후 브리지와 브라우저를 시작합니다.
이후에는 바탕화면의 `ATR Windows Bridge`로 실행하고
`Uninstall ATR Windows Bridge`로 제거할 수 있습니다.

명령행 설치가 필요한 경우:

```powershell
cd "C:\path\to\Pyautogui_server_for_window"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
```

설치기는 `%LOCALAPPDATA%\Programs\ATR\PyAutoGUIBridge`에 프로그램을,
`%LOCALAPPDATA%\ATR\PyAutoGUIBridge`에 변경 가능한 데이터와 토큰을 두고
전용 `.venv`에 `requirements-windows.txt`를 설치합니다. 로그온 자동 시작은
`-RegisterLogonTask`를 명시할 때만 등록됩니다.

더블클릭 제거는 사용자 데이터와 토큰을 보존합니다. 데이터까지 제거하려면
PowerShell에서 `scripts\uninstall_bridge.ps1 -RemoveData`를 실행합니다.

## 1. 로컬 E2E 테스트

먼저 Web GUI와 API가 뜨는지만 확인합니다.

```powershell
cd "C:\ATR\Pyautogui_server_for_window"
powershell -NoProfile -ExecutionPolicy Bypass -File .\local_e2e_test.ps1
```

성공 기준:

```text
GET / Web GUI
Web GUI HTML served with Run Timeline / Live Proof Checklist
GET /health
GET /programs
GET /readiness
GET /request-log
POST /execute guarded sequence or install-required block
GET /artifacts
POST /execute program1
Local E2E completed.
```

PyAutoGUI 설치 전이면 `program1`은 아래처럼 막히는 게 정상입니다.

```json
{
  "ok": false,
  "status": "blocked",
  "failure_code": "PYAUTOGUI_NOT_INSTALLED"
}
```

## 1.1 현재 smoke test 검증 항목

현재 `tests/smoke_test.py`는 packaged server의 compatibility API로 임시 서버를 띄워 다음을 확인합니다.

- `/` Web GUI가 `Run Timeline`, `Live Proof Checklist`, `Operator runtime status`, `Live UTM situation matrix`, `Readiness locator shortcuts`, `Program registry`를 포함합니다.
- 인증 없는 `/health`는 차단되고, 토큰이 있으면 bridge/artifact 경로가 반환됩니다.
- `/programs`에는 `program1`, `utm_compression_start_v1`, `utm_export_csv_v1`, `utm_manual_save_csv_v1`, `utm_stop_or_abort_v1`가 포함됩니다.
- `/readiness`, `/request-log`, `/artifacts`가 응답합니다.
- PyAutoGUI가 설치되지 않은 PC에서도 실행 성공으로 위장하지 않고 명확한 block 결과를 반환합니다.

## 2. Windows 런타임 설치 확인

실제 GUI 제어가 필요하면 Windows PC에서 설치합니다.

```powershell
& "$env:LOCALAPPDATA\Programs\ATR\PyAutoGUIBridge\.venv\Scripts\python.exe" -m pip check
```

설치 확인:

```powershell
& "$env:LOCALAPPDATA\Programs\ATR\PyAutoGUIBridge\.venv\Scripts\python.exe" -c "import pyautogui, pynput, cv2; print(pyautogui.size()); print(pyautogui.FAILSAFE)"
```

`True`가 출력되어야 fail-safe가 켜진 상태입니다.

## 3. Bridge 실행

Linux에서 붙을 수 있게 LAN 바인딩으로 실행합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_bridge.ps1
```

옵션:

```powershell
# 브라우저도 같이 열기
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_bridge.ps1 -OpenBrowser

# 로컬 PC에서만 테스트
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_bridge.ps1 -LocalOnly

# 포트 변경
$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8766"
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_bridge.ps1

# 새 토큰을 화면에 한 번 표시, 기본 길이는 32
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_bridge.ps1 -ResetToken -ShowToken

# Python 경로 직접 지정
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_bridge.ps1 -Python "C:\Path\To\python.exe"
```

실행 후 PowerShell 창은 닫지 마세요. 이 프로세스가 bridge 서버입니다.

이미 백그라운드에서 떠 있는 bridge를 확인하려면:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\check_bridge.ps1
```

bridge만 골라서 중지하려면:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop_bridge.ps1
```

## 4. Web GUI 사용

브라우저에서 엽니다.

```text
http://127.0.0.1:8765/
```

순서:

1. `run_bridge.ps1 -ShowToken`으로 확인한 저장 토큰을 Token 칸에 입력
2. `Health` 클릭 후 상단 `Auth`, `GUI Driver` 상태 확인
3. `Programs` 또는 자동 로드된 `Program registry` 카드로 등록 macro/protocol 목록 확인
4. `Program registry`에서 `Load`로 payload preview를 확인하거나 `Simulate`로 비구동 검증
5. PyAutoGUI 설치 후 `Run program1`로 마우스 이동 데모 확인
6. UTM은 먼저 `Run UTM Simulation` 또는 locator capture로 screen evidence 경로를 점검
6. 실제 장비 제어는 `Live UTM setup is physically safe`를 체크한 뒤 `Run Live UTM` 실행
7. 실행 후 `Last Run Summary`, `Step Trace`, `Artifacts`에서 CSV와 screenshot evidence 확인
8. 통신 문제가 있으면 `Request Log`와 `Bridge Files`의 `bridge_requests.jsonl` 경로를 확인

Web GUI는 다음 운영자용 패널을 제공합니다.

- `Workflow`: Auth, GUI Driver, Program, Evidence, Artifact 단계별 상태
- `Last Run Summary`: program/run id, CSV 또는 artifact reference, 다음 gate
- `Step Trace`: macro step별 ok/warning/blocked 기록
- `Artifacts`: screenshot, locator, UTM CSV artifact 조회 버튼
- `Bridge Files`: artifact root, request audit log, locator root, UTM export root 표시
- `Request Log`: 최근 API/auth 요청 audit event 조회
- `Program Registry`: allowlisted macro/protocol 카드, Load, Simulate 바로가기
- `Live UTM Situation Matrix`: Bridge, Locators, Request Audit, Export, Live Gate를 한 줄로 표시
- `Readiness Locator Shortcuts`: Readiness 결과의 missing/captured locator를 클릭해 캡처 폼에 바로 반영
- `Recent Live Execute Identity`: 최근 `/execute`의 run/specimen/program id와 timestamp 표시
- `Operator Log`: 최근 버튼 실행과 HTTP 결과

Token 칸은 브라우저 `localStorage`에 저장됩니다. 토큰 없이 되는 것처럼 보이면
이전에 저장된 토큰이 남아있는 상태일 수 있습니다. Web GUI의 `Clear Token`을
누르면 저장된 토큰이 지워집니다.

`program1`은 마우스를 짧게 움직였다가 되돌리는 연결 확인용 매크로입니다.
클릭, 입력, 파일 변경은 하지 않습니다.

요청 감사 로그는 Windows bridge artifact root의 `bridge_requests.jsonl`에 저장됩니다.
이 파일은 path/auth 성공 여부를 재구성하기 위한 용도이며 토큰 문자열은 저장하지 않습니다.

## 5. Linux에서 확인

Windows PC의 내부망 IP를 확인한 뒤 Linux에서:

```bash
export WINDOWS_PYAUTOGUI_BRIDGE_URL="http://<windows-private-ip>:8765"
export WINDOWS_PYAUTOGUI_BRIDGE_TOKEN="<saved-token>"
```

Health:

```bash
curl -s \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/health"
```

Programs:

```bash
curl -s \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/programs"
```

program1:

```bash
curl -s \
  -X POST \
  -H "Content-Type: application/json" \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  -d '{"sequence_id":"program1-check-001","program_id":"program1","command":"program1"}' \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/execute"
```

## 6. 방화벽

Linux에서 Windows bridge에 접속이 안 되면 Windows 방화벽이 막고 있을 수 있습니다.
관리자 PowerShell에서 Linux 서버 IP만 허용하는 식으로 여는 걸 권장합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\firewall_allow_private.ps1 -Port 8765 -RemoteAddress "<linux-server-private-ip>"
```

## 7. 패키징

소스 ZIP:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -Version "0.1.0"
```

데모 자산을 포함한 `.exe`로 묶을 때:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -InstallBuildDeps
```

결과:

```text
dist\WindowsPyAutoGUIBridge.exe
```

실행:

```powershell
$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = "<saved-token>"
$env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "0.0.0.0"
$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765"
.\dist\WindowsPyAutoGUIBridge.exe
```

## 8. 주요 파일

- `bridge/windows_pyautogui_bridge_server.py`: 서버와 내장 Web GUI
- `scripts/run_bridge.ps1`: 실행 helper
- `scripts/local_e2e_test.ps1`: 로컬 API/Web GUI 검증
- `scripts/test_bridge.ps1`: 이미 실행 중인 bridge에 대한 수동 테스트
- `scripts/build_exe.ps1`: PyInstaller 빌드
- `scripts/build_release.ps1`: 전체 자산을 포함한 source ZIP 빌드
- `scripts/native_acceptance.ps1`: 실제 Windows 데스크톱 수락 증거 생성
- `scripts/firewall_allow_private.ps1`: Private profile 방화벽 룰 생성
- `examples/windows_bridge.env.example.ps1`: Windows 환경변수 예시
- `examples/linux_env.example.sh`: Linux 환경변수 예시


## 9. UTM Visual-Control / Data Handoff

`utm_compression_start_v1`은 UTM 소프트웨어 GUI를 제어하고, export folder에 생성된 CSV를 Linux 쪽으로 전달하기 위한 등록 프로그램입니다. `program1`은 연결 데모이고 분석 handoff용 데이터 생성 프로그램이 아닙니다.

### 프로그램 확인

```bash
curl -s -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/programs"
```

목록에 다음이 있어야 합니다.

- `utm_compression_start_v1`: UTM 압축시험 시작, 완료 대기, CSV export 감시
- `utm_export_csv_v1`: 완료 후 CSV 저장 보조
- `utm_manual_save_csv_v1`: 수동 저장 fallback
- `utm_stop_or_abort_v1`: 중단/복구용 stop macro

### 실 UTM export folder 설정

Windows PowerShell에서 필요에 맞게 지정합니다.

```powershell
$env:WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR = "C:\ATR\utm_exports"
$env:WINDOWS_PYAUTOGUI_UTM_EXPORT_GLOB = "*.csv"
$env:WINDOWS_PYAUTOGUI_UTM_FILE_STABLE_SEC = "2.0"
```

실 live mode에서는 이 폴더에 UTM 장비 소프트웨어가 만든 CSV가 있어야 성공합니다. 서버가 live 성공을 위해 임의 데이터를 생성하지 않습니다.

### Locator calibration

UTM UI가 이미지 기반으로 확인되어야 하면 다음 endpoint를 사용합니다.

```bash
# 현재 화면 캡처
curl -s -X POST -H "Content-Type: application/json" \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  -d '{"run_id":"locator-calibration","checkpoint":"manual"}' \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/screenshot"

# locator 저장
curl -s -X POST -H "Content-Type: application/json" \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  -d '{"program_id":"utm_compression_start_v1","name":"start_button","region":[100,100,120,60],"confidence":0.8}' \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/locators/capture"
```

저장된 locator는 Linux `/equipment/windows` GUI의 UTM profile JSON에 반영해서 autonomous Equipment Agent가 같은 설정을 사용하게 해야 합니다.

### Bench/demo simulated UTM

Windows 서버 자체 API와 artifact pull 계약만 확인하려면 다음처럼 명시적으로 simulation을 요청합니다.

```bash
curl -s -X POST -H "Content-Type: application/json" \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  -d '{"sequence_id":"utm-sim-check-001","program_id":"utm_compression_start_v1","run_id":"utm-sim-check-001","specimen_id":"specimen-demo-001","simulate_utm_protocol":true}' \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/execute"
```

반환값의 `output_artifacts[0].kind`가 `utm_csv`이고 `row_count_probe`, `columns_probe`, `sha256`가 있어야 합니다.

### Manual save/export fallback

When `utm_compression_start_v1` finishes its start/complete sequence, the server first watches the configured export folder. If no stable parseable CSV appears, it automatically executes `utm_manual_save_csv_v1` unless the request payload contains `manual_save_required_if_no_artifact: false`.

Fallback sequence:

1. create `WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR\<run_id>` if needed;
2. send `Ctrl+S`;
3. type `<export_dir>\<run_id>\<specimen_id>.csv`;
4. press Enter;
5. wait again for the file to become stable;
6. parse-probe `time_s`, `displacement_mm`, and `force_N`.

If this path succeeds, `data_acquisition.save_method` is `manual_save_dialog`. If it fails, the response stays blocked with `UTM_EXPORT_FILE_MISSING`, `UTM_DATA_PARSE_FAILED`, `UTM_SAVE_DIALOG_TIMEOUT`, or `UTM_SAVE_CONFIRMATION_FAILED`; live mode still never fabricates data.


### Linux pull ledger after export

A valid Windows UTM response is not the final Analysis input by itself. The Linux bridge must pull the CSV through `GET /artifacts/<artifact_id>` and write a local file under `artifacts/equipment/<run_id>/utm/`.

The final handoff ledger should contain:

- `data_acquisition.status = pulled_to_linux`
- `data_acquisition.windows_path` for provenance
- `data_acquisition.linux_path` and `data_acquisition.local_path` for Analysis
- `data_acquisition.sha256`, `row_count_probe`, and `columns_probe`
- top-level `result_file` / `utm_csv_path` aliases pointing to the same Linux-local CSV

If these Linux-local fields are absent, treat the run as incomplete even if the Windows export folder contains a file.

### Required screen assertions

If `WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS=1` is enabled, the Windows server performs the locator checks itself during `utm_compression_start_v1`:

- `assert_visible` for the ready state;
- image-located click of the start button;
- `wait_until` for running and complete states;
- block with `UI_LOCATOR_NOT_FOUND` if a required locator is absent.

The bridge also supports optional OCR/text primitives for UTM status labels and dialogs:

- `assert_text`: one-shot text assertion against a screen region or full screenshot.
- `wait_until_text`: wait-budget text assertion for delayed status/dialog changes.

These actions use `pytesseract` when it is installed on the Windows PC. If OCR is unavailable and the action is required, the protocol blocks instead of treating the text check as successful.

Do not use a separate caller flag as proof that the screen was checked. The bridge must observe the actual Windows screen before the protocol can move to export watching or manual save fallback.

### Screen-state evidence artifacts

During `utm_compression_start_v1`, the Windows server now links screen evidence to the state transition checks:

- `before_start` screenshot before protocol execution;
- `after_start` screenshot when `running_state` is observed;
- `after_complete` screenshot when `complete_state` is observed.

Check the response `screen_checks` and `output_artifacts` together. A valid report should show `screen_png` artifacts for the running and complete states in addition to the `utm_csv` data artifact.

### Failure evidence retention

When `utm_compression_start_v1` blocks, inspect `screen_checks` and `output_artifacts` before retrying. The server keeps the pre-start screenshot, captures a `failure` screenshot, and preserves any running/complete screenshots that were already observed before the data export failed.

These artifacts are evidence for debugging and failure memory. They are not a substitute for the `utm_csv` artifact required by the Linux Analysis handoff.

## 10. Operator Web GUI for UTM setup

Open the packaged server GUI on the Windows workstation:

```text
http://127.0.0.1:8765/
```

The GUI is intended for local Windows-side setup before Linux autonomous execution:

1. Enter the bridge token and run `Health`.
2. Use `Programs` to confirm `utm_compression_start_v1` is registered.
3. Use `Capture Screen` to create a full-screen evidence artifact when calibrating.
4. Use `Locator Capture` to save `ready_state`, `start_button`, `running_state`, and `complete_state` image regions.
5. Use `Run UTM Simulation` to verify the endpoint/artifact contract without touching real equipment.
6. Use `Run Live UTM` only after the physical UTM setup is safe and the confirmation checkbox is enabled.

The page shows the latest raw response, step trace, and artifact ledger. Artifact rows can be opened through `GET /artifacts/<artifact_id>` from the same panel.

## 11. Target window focus contract

The registered UTM sequence begins with `focus_window`. The Windows bridge now resolves real window selectors before running image assertions or clicks.

Supported selector fields:

- `target_window`
- `target_window_regex`
- `window_title`
- `title`
- `target_app`
- `app_title`
- action-level `title`, `window_title`, `target_window`, or `title_regex`

Examples:

```json
{
  "sequence_id": "utm-live-001",
  "program_id": "utm_compression_start_v1",
  "run_id": "utm-live-001",
  "specimen_id": "specimen-001",
  "target_window": "Instron UTM Software",
  "require_window_focus": true
}
```

```json
{
  "sequence_id": "utm-live-002",
  "program_id": "utm_compression_start_v1",
  "target_window_regex": "UTM Controller",
  "require_window_focus": true
}
```

If PyAutoGUI can enumerate and activate a matching window, the step trace records `SEQ_2_FOCUS_WINDOW: ok`. If no matching window is found and focus is required, the bridge blocks with `PYAUTOGUI_WINDOW_NOT_FOUND`. If focus is not required, it records a warning and continues for legacy/manual operator workflows.

## 12. Linux handoff gate after Windows GUI execution

The Windows page can prove that the UTM GUI ran and that a Windows-side artifact exists. The autonomous Linux workflow still requires the Linux bridge to pull the CSV before Analysis can run.

For a live Windows UTM run, the Linux-side `equipment_report.v1.live_evidence_audit` must show:

- `screen_evidence.ok=true` with `before_start`, `after_start`, and `after_complete` checkpoints;
- `linux_artifact_pull.ok=true` with `data_acquisition.status=pulled_to_linux`;
- `vision_evidence.ok=true` with Vision evidence frame IDs.

`exported_on_windows` means the Windows workstation created or saw a file. It is not equivalent to Linux Analysis readiness.


### 10.1 Safe Preflight UI update

The Windows GUI now separates safe diagnostics from live execution.

- `Safe Preflight` calls `GET /health`, `GET /readiness`, and `GET /request-log` only. It does not call `POST /execute` and must not move the UTM software.
- `Preflight + Run Live UTM` first runs the same local preflight. If PyAutoGUI is unavailable, required locators are missing, or readiness has not been checked, the page blocks with `LOCAL_LIVE_PREFLIGHT_BLOCKED` and no live `/execute` request is sent.
- `Safe Diagnostics` contains non-actuating checks: Health, Readiness, Request Log, Capture Screen, Locators, and Artifacts.
- `Artifact Preview` can display image artifacts loaded from `GET /artifacts/<artifact_id>` after pressing `View` in the artifact table.
- This local page helps the Windows operator avoid accidental live execution, but Linux-side Analysis handoff still requires request-log `/execute`, screen evidence, Linux CSV pull, parse probe, and Vision evidence.

## 13. Windows Web GUI usability update

The local Windows bridge page now includes an operator-focused layout:

- Sticky navigation: `Overview`, `UTM Control`, `Evidence`, `Result JSON`, and `Operator Log`.
- Sticky sidebar and command rail keep token/UTM settings plus Preflight, Evidence, Simulate, Live UTM, and Abort reachable while scrolling.
- `Focus Mode` hides secondary diagnostics, locator capture, and raw Result JSON for live-operation monitoring; `Full View` restores every panel.
- `Bridge URL` readout in the Connection card.
- `Copy Linux Env` copies Linux controller variables:
  - `WINDOWS_PYAUTOGUI_BRIDGE_URL`
  - `WINDOWS_PYAUTOGUI_BRIDGE_TOKEN`
- `Refresh All` runs Health, Readiness, Request Log, and Artifacts without calling `/execute`.
- `Live interlock` shows why live UTM execution is currently blocked or allowed.
- `Live Proof Checklist` shows a progress bar and the next missing proof item.
- Operator Log is scrollable and appends new events at the bottom.
- The workspace now places `Overview` and live proof status before the payload console/timeline, so the operator sees blockers and proof gates immediately after the command rail.
- Overview cards use a two-column layout on wide monitors, while the proof and bridge-file cards stay full-width to avoid clipped evidence text.
- Connection, Safe Diagnostics, UTM Protocol, Locator Capture, and Operator Log sections can be collapsed/expanded; the collapsed state is saved in browser local storage.

These controls are only Windows-side usability gates. The Linux Equipment Agent and `/equipment/windows` GUI still enforce the hard handoff rules before Analysis can consume UTM data.

## 2026-05-30 GUI Update: Command Banner and Proof Flow

The Windows local bridge page now has a command banner above the main overview. It reports the active request, completion state, or blocker state for each GUI command. This is operator-facing status only; the detailed proof still comes from Result JSON, Step Trace, Artifacts, and Operator Log.

The Linux `/equipment/windows` page now separates proof package creation from proof package verification:

- `Build Proof Package` writes the current UTM proof JSON artifact.
- `Verify Proof Package` checks the persisted proof artifact and local Linux-side UTM CSV parse probe before Analysis handoff.
- If verification is blocked, resolve the listed blockers and rebuild the package.

For live UTM evidence, the required order remains: Safe Preflight -> Live UTM run -> Evidence Audit -> Build Proof Package -> Verify Proof Package.

## 10. Operator HUD GUI

The Web GUI includes an `Operator runtime status` HUD above the Overview section. It is intended for the Windows PC operator during UTM control.

- `Safety`: Safe Preflight/proof-gate status.
- `Command`: last command state and whether it is running, complete, or blocked.
- `Evidence`: required screen evidence status.
- `Data`: UTM CSV/parse-probe status.
- `Next`: the next required action before Linux analysis handoff.

The `UTM Protocol` card shows the required order: Safe Preflight -> live execute -> screen evidence -> CSV artifact -> Linux audit. The Run ID and Specimen ID fields are copied into the `/execute` payload, so set them before a live UTM run if you need traceable evidence.

## 11. Request-log Identity Audit

Every `/execute` request is recorded with non-secret identity fields so Linux can prove which experiment command actually ran.

Recorded fields include:

- `run_id`
- `sequence_id`
- `specimen_id`
- `program_id`
- `payload_sha256` of a token-stripped payload
- result status and failure code for the paired execute result event

Do not put passwords or tokens inside execute payloads. The bridge strips token/password/secret/auth/credential-like keys before audit hashing, but connection secrets should still be supplied through the bridge token header or environment variables.

After a live UTM run, use `Request Log` in the Web GUI or `GET /request-log` to confirm that the latest `/execute` identity matches the Linux run/specimen/program before relying on the CSV artifact. A matching proof must include the same `run_id`, `sequence_id`, `specimen_id`, and `program_id`.

## Restart-Tolerant Artifact List

`GET /artifacts` rebuilds the in-memory artifact list from the configured bridge artifact directory and UTM export directory. This means a bridge restart does not hide previously exported UTM CSV files or screenshot evidence from the operator page.

The endpoint indexes `.csv`, `.json`, `.txt`, and `.png` files, adds checksum/size metadata, and probes CSV column/row information when possible. `GET /artifacts/{artifact_id}` also retries this rebuild before reporting that an artifact is missing.

## 2026-05-30 GUI Proof Checklist Update

The Windows bridge web GUI now treats UTM save/export responsibility as a visible live-proof gate.

- `Live Proof Checklist` contains 7 checks, including `Save/Export Responsibility`.
- A verified UTM run should return `cross_checks.save_export_responsibility_ok=true` and `data_acquisition.save_method` such as `windows_export_watch` or `manual_save_dialog`.
- If export fails, the GUI keeps the proof item open and the Linux proof verifier will block Analysis handoff with `UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED`.

## 2026-05-30 Windows GUI Operator Console Update

The Windows bridge Web GUI now exposes a compact operator console for live UTM work.

- Header proof status: the top bar shows both bridge authentication and live proof completion, for example `proof 5/7`.
- Critical command rail: `Preflight`, `Evidence`, `Simulate`, and `Live UTM` are grouped above the runtime HUD so the operator does not need to hunt through the sidebar during a run.
- Persistent run fields: Run ID, Specimen ID, target window selector, export glob, artifact timeout, stable-file time, and expected export path are stored in browser local storage. Refreshing the Windows page keeps non-safety setup values, but physical safety confirmation is never persisted.
- Payload export: `Copy Payload` copies the exact UTM `/execute` JSON that the Windows page would send. Use this for debugging Linux-to-Windows command parity.
- The GUI remains a usability layer only. Linux Equipment Agent gates, proof package verification, screen evidence, CSV parse probe, and save/export responsibility checks remain authoritative.

### Safety note for persisted GUI fields

The GUI persists setup fields such as Run ID, Specimen ID, target window selector, export glob, and artifact timing values. It intentionally does not persist the `Live UTM setup is physically safe` checkbox. The operator must confirm physical safety for each browser session/run before the page can send a live UTM `/execute` request.

The command rail buttons are proxies to the same underlying handlers as the sidebar controls. Unit tests execute those proxy buttons to confirm that Preflight remains non-actuating and Live UTM still performs local preflight before `/execute`.

## 2026-05-30 Linux Operator Rail Compatibility

The Linux `/equipment/windows` page now has a five-step operator rail: Scan, Readiness, Preflight, UTM Run, and Evidence. These buttons call the same Linux backend endpoints as the detailed controls, so Windows bridge behavior does not change.

The Windows bridge `/programs` and Linux `equipment.pyautogui.list_programs` views should both show the registered UTM protocol contract: preconditions, expected screen states, save policy, output artifact patterns, and safe-abort metadata. If these differ, update the packaged Windows bridge and the Linux controller together before running live UTM automation.

## 2026-05-30 UTM Stop/Abort Recovery Path

The Linux Equipment workspace can dispatch `utm_stop_or_abort_v1` from its `Abort` rail card. This path is different from a normal UTM compression protocol:

- It is for recovery and safe stopping only.
- It does not require complete ready/running/complete locators before dispatch.
- It still requires explicit confirmation and a configured bridge token.
- The Linux side records it as `recovery_macro=true`, not as a successful UTM data run.

After using it, open Request Log or Evidence Audit and confirm that the `/execute` request is present before deciding the UTM state is safe to continue.

## Windows GUI Recovery Control

The local bridge page includes `Stop / Abort` in the UTM protocol row and top command rail.

- It dispatches `program_id=utm_stop_or_abort_v1` to `/execute`.
- It intentionally skips normal live UTM preflight so recovery remains available when the UTM GUI is stuck.
- It is not proof of a completed UTM test. After running it, use `Request Log` and `Refresh Evidence` before retrying a normal run.

The Linux ATR Equipment workspace can open this page with `Open Windows GUI` after a bridge candidate is saved and selected.

## 2026-05-30 Local Operator Console and Payload Preview

The packaged Windows bridge Web GUI includes a `Local Operator Console` for UTM operation.

What changed:
- `Payload Preview` shows the exact payload envelope for simulation, live UTM execution, or stop/abort recovery.
- `Preview Sim`, `Preview Live`, `Preview Abort`, and `Copy Preview` are available before sending commands.
- Live UTM input fields are validated in the browser before non-actuating preflight starts.
- Invalid `Run ID`, `Specimen ID`, `Artifact Timeout Sec`, or `Stable File Sec` returns `WINDOWS_GUI_INPUT_INVALID` locally and sends no bridge API request for that action.
- `Stop / Abort` remains available as a recovery path and dispatches `utm_stop_or_abort_v1` directly.

Use this page as the Windows-side operator console. The Linux ATR GUI remains the source of record for saved bridge candidates, autonomous workflow state, and final equipment handoff audit.

## 2026-05-30 Health Version Metadata

`GET /health` includes explicit bridge version metadata for Linux-side audit:

- `server_version`: HTTP bridge server version.
- `script_version`: Windows helper script/runtime contract label.
- `pyautogui.available`: actual PyAutoGUI import status.
- `pyautogui.failsafe`: actual fail-safe state.
- `pyautogui.pause`: actual PyAutoGUI pause setting.

The Linux client records this together with `bridge_url`, `bridge_host`, and `client_latency_ms` in the Lab Equipment report so operators can identify stale scripts, wrong Windows hosts, or PyAutoGUI import failures before trusting a live UTM handoff.

## 10. Bridge Command Kit

Web GUI의 Connection 패널에는 `Bridge Command Kit`이 있습니다. 같은 동작을 브라우저, Linux curl, Windows PowerShell에서 비교할 때 사용합니다.

- `Copy curl Health`: Linux controller 또는 다른 내부망 Linux 터미널에서 bridge 인증과 health를 확인합니다.
- `Copy PowerShell Health`: Windows 장비 PC에서 로컬 PowerShell로 같은 health endpoint를 확인합니다.
- `Copy curl Execute`: 현재 Payload Preview의 `/execute` 요청을 curl 명령으로 복사합니다. 실 UTM payload라면 safety/preflight 조건을 먼저 확인해야 합니다.

토큰이 비어 있는 상태에서는 GUI가 자동으로 `/health`를 호출하지 않습니다. 이 동작은 첫 화면에서 불필요한 auth error를 없애기 위한 UI 개선이며, 실제 endpoint 인증은 기존과 동일하게 `X-Bridge-Token`으로 강제됩니다.

상단 명령 배너의 `Recommended next action`은 Live Proof Checklist의 첫 미충족 gate를 보고 다음 조작을 제안합니다. 이 버튼은 토큰 입력, Health, Readiness, screenshot/evidence refresh, Live UTM 안전 확인처럼 현장 오퍼레이터가 다음에 수행할 작업으로 바로 이동합니다.

## 2026-05-30 Strict Linux handoff compatibility

The Windows bridge and Linux Equipment Agent use the same strict proof model. After `/execute` returns `output_artifacts[]`, Linux pulls each artifact through `/artifacts/<artifact_id>`, writes the bytes under `artifacts/equipment/<run_id>/...`, and mirrors the resolved records into both `output_artifacts[]` and `artifact_records[]`. Any downstream proof verifier should resolve evidence from either field, but it must require existing Linux-local files.

Required physical UTM proof before Analysis handoff:

- request audit: `/request-log` must contain a live `/execute` with matching `run_id`, `sequence_id`, `specimen_id`, and `program_id`;
- screen evidence: `screen_checks` must include unique, file-backed `before_start`, `after_start`, and `after_complete` screenshot refs;
- save/export responsibility: `data_acquisition.save_method` must be one of `windows_export_watch`, `manual_save_dialog`, or `export_menu`, with save attempted/observed and confirmation evidence;
- data artifact: the UTM CSV must be pulled to Linux and exposed as `result_file`, `utm_csv_path`, `data_acquisition.linux_path`, or `data_acquisition.local_path`;
- data quality: Linux re-parses the actual CSV bytes and rejects missing columns, non-monotonic time, flat displacement, all-zero force, or flat force;
- Vision evidence: Linux must attach matching pre-start, motion, and complete observations with distinct frame/observation ids.

Do not treat `exported_on_windows`, a visible CSV filename, or `cross_checks.*=true` alone as sufficient. Those values are useful diagnostics, but the Linux proof package and completion audit remain authoritative.

## Physical dispatch proof boundary

The Windows operator page can prepare evidence, but Linux completion verification requires an explicit physical live dispatch record: `requested_physical_execute=true`, `execute_sent=true`, `non_actuating=false`, and `status=verified_complete`. If this record is absent, the proof verifier returns `UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED` even when screen artifacts and CSV files exist.

## Unique evidence requirement

Linux-side verification requires distinct screen evidence files and a physical-validation source packet. Keep the original `last_windows_utm_physical_validation` packet, screen artifacts, and pulled CSV together in the run artifacts. The source packet and manifest must both carry matching `run_id`, `sequence_id`, `specimen_id`, and `program_id`. Each screenshot ref must resolve to a Linux-local image file with a recognized image signature. Do not reuse a single screenshot for multiple checkpoints, and do not substitute placeholder text files for screen evidence.

## 2026-05-30 Windows-side screen artifact validity gate

For `utm_compression_start_v1`, the Windows bridge now checks screenshot file signatures before it can return `status=verified_complete`. The bridge must capture distinct valid PNG/JPEG/GIF image artifacts for `before_start`, `after_start`, and `after_complete`. Placeholder text files, empty `.png` files, or metadata-only screenshot ids are rejected before Linux receives a physical-completion packet.

`utm_export_csv_v1` remains an export/save macro and is not treated as physical compression proof by this gate. It can export a CSV from an already-completed UTM screen, but the full Analysis handoff still requires the physical compression run proof package and Linux completion audit.
