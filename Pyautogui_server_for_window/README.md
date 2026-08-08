# Windows PyAutoGUI Bridge

Windows PC에서 PyAutoGUI를 인증된 HTTP bridge로 노출하고 Linux ATR
Equipment Agent가 내부망에서 제어하도록 만든 독립 배포 패키지입니다.

## 표준 설치

release ZIP을 풀고 `INSTALL_WINDOWS_BRIDGE.cmd`를 더블클릭합니다. 압축을
푼 위치가 어디든 런처가 자기 경로를 자동으로 인식하므로 `cd`나 폴더 경로
입력이 필요 없습니다. 설치 완료 후 브리지가 별도 창에서 시작되고 Web GUI가
열립니다. 오류가 발생하면 설치 창이 닫히지 않고 원인을 표시합니다.

PowerShell로 직접 설치해야 할 때만 아래 명령을 사용합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -OpenBrowser -ShowToken
```

- 프로그램: `%LOCALAPPDATA%\Programs\ATR\PyAutoGUIBridge`
- 사용자 데이터: `%LOCALAPPDATA%\ATR\PyAutoGUIBridge`
- Python: 패키지 전용 `.venv`와 `requirements-windows.txt`
- 자동 시작: 설치 시 `-RegisterLogonTask`를 명시한 경우에만 대화형 사용자 로그온 작업으로 등록
- 제거: `scripts\uninstall_bridge.ps1`; 데이터도 지우려면 `-RemoveData`
- 클릭 시작: 바탕화면 `ATR Windows Bridge`
- 클릭 제거: 바탕화면 `Uninstall ATR Windows Bridge`; 사용자 데이터는 기본 보존

Windows 서비스로 실행하면 대화형 데스크톱을 제어할 수 없으므로 지원하지
않습니다. Linux/Xvfb 검증은 프로토콜 검증이며 실제 Windows 수락은
`scripts\native_acceptance.ps1`로 별도 수행합니다.

## 현재 구조

```text
.
├─ bridge/                  # 실제 Python bridge 서버
├─ demo/                    # capability lab과 안전 예제
├─ scripts/                 # 실행, 테스트, 빌드, 방화벽 helper
├─ examples/                # Windows/Linux 환경변수 샘플
├─ tests/                   # 로컬 smoke test
├─ docs/                    # 자세한 사용법
├─ artifacts/               # 실행 중 생성되는 로그/스크린샷/payload
├─ reference_images/        # locate_image용 기준 이미지
├─ run_bridge.ps1           # 루트 호환 wrapper
├─ local_e2e_test.ps1       # 루트 호환 wrapper
├─ requirements.txt
├─ requirements-windows.txt # Windows 전용 고정 런타임
└─ README.md
```

## 빠른 확인

PowerShell에서:

```powershell
cd "C:\ATR\Pyautogui_server_for_window"
powershell -NoProfile -ExecutionPolicy Bypass -File .\local_e2e_test.ps1
```

정상이면 다음 줄이 보입니다.

```text
GET / Web GUI
Web GUI HTML served with Run Timeline / Live Proof Checklist
```

`PYAUTOGUI_NOT_INSTALLED`는 통신 실패가 아니라 PyAutoGUI 미설치 상태입니다.

## 실행

`run_bridge.ps1`는 artifact, locator, UTM export, program, recording을 단일
사용자 데이터 루트에 연결하고 demo 자산 경로까지 서버에 전달합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_bridge.ps1
```

출력 예:

```text
Generated a saved bridge token.
Windows PyAutoGUI bridge listening on 0.0.0.0:8765
Web GUI: http://127.0.0.1:8765/
```

브라우저에서:

```text
http://127.0.0.1:8765/
```

`Program Manager > RECORD`는 5초 카운트다운 후 녹화를 시작합니다. 녹화
중에는 Windows 최상위에 빨간 점과 경과 시간이 있는 작은 배너가 표시되고,
같은 `STOP RECORDING` 버튼을 누르면 녹화와 배너가 함께 종료됩니다.

상태 확인:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\check_bridge.ps1
```

중지:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop_bridge.ps1
```

초기 연결 시 `-ShowToken`으로 한 번 확인한 토큰을 넣고 `Health`, `Programs`, `Run program1`을
누르면 됩니다. Web GUI는 현장 운용용으로 다음 정보를 바로 보여줍니다.

- Auth, GUI Driver, Program, Evidence, Artifact workflow 상태
- Last Run Summary: program/run id, CSV artifact, 다음 gate
- Step Trace와 Artifacts table: macro 진행 단계와 screenshot/CSV 회수 상태
- Program Registry cards: allowlisted Windows macro/UTM protocol을 카드로 보여주고 `Load`/`Simulate`로 바로 검증
- Live UTM situation matrix: Bridge, Locators, Request Audit, Export, Live Gate 상태를 한눈에 표시
- Readiness locator shortcuts: missing/captured locator를 캡처 폼과 연결
- UTM Simulation/Live UTM, locator capture, advanced JSON execute

브라우저는 Token 칸 값을 로컬 저장소에 기억합니다. 토큰 없이 되는 것처럼
보이면 저장된 값이 남아있는 경우이니 Web GUI의 `Clear Token`을 누르고 다시
확인하세요.

## 5번 개선안 smoke 검증 범위

`tests/smoke_test.py`와 `local_e2e_test.ps1`은 Windows 서버 배포 폴더가 현재 Lab Equipment Agent 계약을 만족하는지 확인합니다. 최소 검증 범위는 다음입니다.

- Web GUI가 `Run Timeline`, `Live Proof Checklist`, `Operator runtime status`, `Live UTM situation matrix`, `Readiness locator shortcuts`, `Program registry`를 렌더링합니다.
- 토큰 없는 `/health`는 `PYAUTOGUI_AUTH_FAILED`로 막힙니다.
- `/programs`에 `program1`과 UTM 프로토콜 4종이 표시됩니다.
- `/readiness`, `/request-log`, `/artifacts`가 정상 응답합니다.
- PyAutoGUI 미설치 환경에서는 실행 요청이 성공으로 위장되지 않고 `PYAUTOGUI_NOT_INSTALLED` 또는 allowlist 실패로 명확히 차단됩니다.

## Windows 런타임 설치

실제 마우스 제어까지 하려면:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
```

`py`가 없으면:

```powershell
python -m pip install pyautogui
```

## Linux에서 붙기

```bash
export WINDOWS_PYAUTOGUI_BRIDGE_URL="http://<windows-private-ip>:8765"
export WINDOWS_PYAUTOGUI_BRIDGE_TOKEN="<saved-token>"

curl -s -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/health"
```

자세한 사용법은 [docs/USAGE.md](docs/USAGE.md)를 보세요.


## UTM 프로토콜 / 5번 개선안 대응

이 배포 폴더의 Windows 서버는 Linux `LabEquipmentAgent`가 요구하는 UTM visual-control/data-loop API를 포함합니다.

지원 endpoint:

- `GET /health`: PyAutoGUI, 화면 크기, artifact/locator/export root readiness 확인
- `GET /programs`: `program1`, `utm_compression_start_v1`, `utm_export_csv_v1`, `utm_manual_save_csv_v1`, `utm_stop_or_abort_v1` 목록
- `POST /execute`: 등록 macro 또는 allowlisted sequence 실행
- `POST /screenshot`: Windows 화면 evidence artifact 생성
- `GET /locators`, `POST /locators/capture`: UTM 버튼/상태 이미지 locator calibration
- `GET /artifacts`, `GET /artifacts/<artifact_id>`: CSV/screenshot artifact metadata 및 base64 회수
- `GET /request-log`: 최근 100개 request audit event 조회

감사 로그:

- 모든 인증 대상 요청은 artifact root의 `bridge_requests.jsonl`에 append-only로 기록됩니다.
- 로그에는 timestamp, client, method, path, token header 존재 여부, auth 성공/실패만 남깁니다.
- Web GUI의 `Request Log` 버튼과 `Bridge Files` 패널에서 audit log 위치와 최근 요청을 바로 확인할 수 있습니다.
- 토큰 값 자체는 기록하지 않습니다.
- 기본 위치는 `C:\ATR\bridge_artifacts\bridge_requests.jsonl`입니다.

실 UTM 실행 원칙:

- `utm_compression_start_v1`은 UTM GUI를 클릭한 뒤 export folder에서 CSV가 생성되고 안정화될 때까지 감시합니다.
- CSV에는 최소 `time_s`, `displacement_mm`, `force_N` 열이 있어야 합니다.
- 실사용 live 성공은 synthetic CSV를 만들지 않습니다. 파일이 없거나 parse probe가 실패하면 `UTM_EXPORT_FILE_MISSING` 또는 `UTM_DATA_PARSE_FAILED`로 차단됩니다.
- bench/demo 확인만 필요하면 요청 payload에 `simulate_utm_protocol: true`를 명시하거나 `WINDOWS_PYAUTOGUI_ALLOW_SIMULATED_UTM=1`을 설정합니다.

주요 환경변수:

```powershell
$env:WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR = "C:\ATR\utm_exports"
$env:WINDOWS_PYAUTOGUI_UTM_EXPORT_GLOB = "*.csv"
$env:WINDOWS_PYAUTOGUI_UTM_FILE_STABLE_SEC = "2.0"
$env:WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS = "0"
$env:WINDOWS_PYAUTOGUI_ALLOW_SIMULATED_UTM = "0"
```
Manual save/export fallback:

- If the first export-folder watch does not find a stable parseable CSV, `utm_compression_start_v1` now runs the `utm_manual_save_csv_v1` sequence automatically unless the request sets `manual_save_required_if_no_artifact: false`.
- The fallback sends `Ctrl+S`, types `WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR\<run_id>\<specimen_id>.csv`, presses Enter, then repeats the stable-file and parse-probe gate.
- A fallback success is reported with `data_acquisition.save_method = manual_save_dialog`; a fallback failure remains blocked and is not converted to synthetic data.


## Linux pull ledger contract

After a real or explicitly simulated UTM run, the Windows server should expose the CSV through `output_artifacts` and `GET /artifacts/<artifact_id>`. The Linux autonomous researcher bridge pulls that artifact and writes a Linux-local CSV path into `data_acquisition.linux_path` and `data_acquisition.local_path` with `status=pulled_to_linux`.

The Windows server only owns Windows-side execution, export watching, manual save fallback, and artifact serving. The Analysis stage must consume the Linux-local pulled CSV, not the Windows path.

## Required screen assertions

When `WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS=1`, the packaged server now runs the registered locator sequence directly instead of requiring an external `screen_assertions_verified` flag. Valid locators allow the protocol to continue; missing locators block with `UI_LOCATOR_NOT_FOUND`.

## Screen-state evidence artifacts

The packaged server links `screen_png` artifacts to `screen_checks` for `before_start`, `after_start`, and `after_complete`. The running-state screenshot is captured when `wait_until running_state` succeeds, so the Linux Equipment report can show GUI state evidence instead of only a command-success string.

## Failure evidence retention

Blocked UTM runs now return `screen_checks` and `screen_png` artifacts as failure evidence. Sequence failures include `before_start` and `failure`; export failures also preserve any running/complete screenshots captured before the missing-data gate blocked the run.

## Operator Web GUI update

The packaged Windows server Web GUI is now an operator panel instead of a raw JSON-only test page.

Main controls:

- `Connection`: token entry, health check, and token clearing.
- `Quick Actions`: program registry, program1 demo, screenshot, locator list, and artifact list.
- `UTM Protocol`: run/specimen IDs, target window title or regex, required focus gate, screen-assertion option, manual-save fallback option, simulation run, and guarded live UTM run.
- `Locator Capture`: capture `ready_state`, `start_button`, `running_state`, or `complete_state` regions from the Windows screen.
- `Result`, `Step Trace`, and `Artifacts`: inspect the latest response, transition steps, screenshots, and CSV artifacts from the same browser page.
- `Program Registry`: auto-loads `/programs` into operator cards. `Load` places the selected macro/protocol into the payload preview; `Simulate` runs the selected allowlisted path in non-live mode where supported.
- `Focus Mode`: hides secondary diagnostics, locator capture, and raw Result JSON so the operator can keep the live command rail, timeline, proof checklist, evidence, and log visible during UTM operation.
- Sticky sidebar and command rail: connection/UTM settings and the critical Preflight/Simulate/Live/Abort buttons stay reachable while reviewing evidence.

`Run Live UTM` requires the `Live UTM setup is physically safe` checkbox. This is a UI-level operator confirmation only; the Linux Lab Equipment Agent and Guardian checks still own the autonomous workflow safety gates.

## Target window focus

`focus_window` now attempts to activate the actual UTM software window before clicking or locating images. The bridge checks request/program fields such as `target_window`, `target_window_regex`, `window_title`, `title`, and `target_app` and uses PyAutoGUI window APIs when available:

```json
{
  "program_id": "utm_compression_start_v1",
  "target_window": "Instron UTM Software",
  "require_window_focus": true
}
```

Regex selectors can be supplied with `target_window_regex` or `target_window: "regex:.*UTM.*"`. Generic placeholders such as `main` and `main_window_title_or_regex` are ignored as real titles. If `require_window_focus=true` or the action has `required=true`, a missing window blocks with `PYAUTOGUI_WINDOW_NOT_FOUND` instead of silently assuming focus.

## 2026-05-30 GUI 개선 사항

Windows 브릿지 Web GUI는 토큰이 없는 첫 접속에서 `/health`를 자동 호출하지 않고 `Enter bridge token` 상태로 대기합니다. PowerShell에 출력된 토큰을 넣은 뒤 `Health`를 눌러 인증 세션을 확인하세요.

Connection 패널의 `Bridge Command Kit`에서 다음 명령을 바로 복사할 수 있습니다.

- `Copy curl Health`: Linux 쪽에서 Windows bridge health를 확인하는 curl 명령
- `Copy PowerShell Health`: Windows PowerShell에서 같은 health를 확인하는 명령
- `Copy curl Execute`: 현재 Payload Preview 기준 `/execute` 명령

상단 critical command rail은 1920x1080 현장 화면에서 버튼 폭이 좁아지지 않도록 조정했습니다. `Step Trace`는 상태별 색 배경으로 표시되어 blocked/warn/ok 단계를 빠르게 구분할 수 있습니다.

`Recommended next action` 버튼은 현재 proof gate에서 가장 먼저 막힌 항목을 기준으로 다음 조작을 제안합니다. 토큰 미입력 시 토큰 칸으로 포커스하고, Health/Readiness/Evidence/Live UTM 단계에서는 해당 버튼을 바로 실행하거나 안전 체크박스로 이동합니다.

## Strict proof handoff contract

A Windows-side `verified_complete` response is only the first half of the Lab Equipment proof. The Linux bridge must still pull every referenced artifact through `GET /artifacts/<artifact_id>` and rewrite the response with Linux-local evidence paths. Current Linux versions mirror pulled records into both `output_artifacts[]` and `artifact_records[]` so the live validation runner, proof package verifier, Equipment report, and Analysis handoff resolve the same files.

Physical UTM completion requires all of the following evidence before Analysis handoff:

- request-log `/execute` identity matching `run_id`, `sequence_id`, `specimen_id`, and `program_id`;
- three file-backed screen checkpoints: `before_start`, `after_start`, and `after_complete`;
- explicit save/export responsibility using `windows_export_watch`, `manual_save_dialog`, or `export_menu`;
- a Linux-local CSV pulled from the Windows artifact endpoint;
- CSV signal quality with `time_s`, `displacement_mm`, and `force_N`, monotonic time, changing displacement, and nonzero changing force;
- matching Vision proof for UTM pre-start, motion confirmation, and test-complete observations.

Windows-only paths such as `C:\ATR\utm_exports\...` are provenance. They are not Analysis-ready paths by themselves.

## Physical dispatch proof boundary

Linux completion audit requires a physical live dispatch record. The Windows bridge may show healthy request logs, screenshots, and CSV artifacts, but the final proof package still needs `manifest.physical_execution.ok=true` from a guarded physical validation run. Non-actuating preflight, UTM simulation, and manually copied artifacts are intentionally blocked from completion.

## Unique evidence requirement

When Linux verifies a proof package, it expects three distinct screenshot files for before/start/complete states and a physical-validation source packet matching the manifest. The source packet and manifest must both carry matching `run_id`, `sequence_id`, `specimen_id`, and `program_id`. Screenshot refs must resolve to Linux-local files with a recognized image signature. Reusing one screenshot, editing only the manifest, omitting the original `last_windows_utm_physical_validation` source packet, or pointing to a non-image placeholder is not accepted as completion evidence.

## 2026-05-30 UTM screenshot source-evidence gate

`utm_compression_start_v1` now validates screenshot file signatures on the Windows bridge before returning `verified_complete`. A physical compression run needs distinct valid screen artifacts for `before_start`, `after_start`, and `after_complete`; placeholder `.png` files or metadata-only screenshot ids are rejected with `UTM_SCREEN_EVIDENCE_FILES_REQUIRED`.

`utm_export_csv_v1` remains an export/save-only macro. It does not replace the physical compression-run proof package required by the Linux Completion Audit.
