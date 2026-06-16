# Device Workspaces 사용법: 3DP Printer Bridge

이 문서는 Main GUI의 **Device Workspaces** 영역과 3DP Printer GUI(`/printer`)를 실제 운영자가 어떻게 쓰는지 정리한 페이지입니다. Live GUI 화면은 아직 UI 조정 대상이므로 여기서는 다루지 않습니다.

BambuLab X2D bridge의 내부 구조, MQTT/FTPS/HTTP/camera plane 분리, native G-code autoejection gate는 [../hardware/bambulab_x2d_device_bridge_runtime_guideline.md](../hardware/bambulab_x2d_device_bridge_runtime_guideline.md)에 별도로 정리되어 있습니다. 이 문서는 버튼 순서와 운영 절차를 중심으로 설명합니다.

## 1. 진입 경로

ATR 서버를 실행한 뒤 브라우저에서 Main GUI를 엽니다.

```bash
atr up
```

- 기본 접속: `http://127.0.0.1:7860/`
- 같은 내부망 장비가 서버 artifact를 가져가야 하는 경우: 서버를 `0.0.0.0`로 띄운 상태에서 LAN IP를 사용합니다.
- 3DP GUI 직접 접속: `http://127.0.0.1:7860/printer`

Main GUI의 **Device Workspaces**에서 장비별 전용 GUI로 이동합니다.

![Main GUI Device Workspaces](../assets/device_workspace_usage/01_main_device_workspaces.png)

각 카드의 의미는 다음과 같습니다.

| 카드 | 역할 |
|---|---|
| 3DP Printer Bridge | Bambu Lab 기본, Prusa 명시 선택 방식의 3D 프린터 bridge 설정/검증 |
| Windows PyAutoGUI Bridge | Windows PC의 UTM/장비 제어 macro bridge 설정/테스트 |
| LeRobot / ROBOTIS | teleoperation, recording, training, rollout, manipulation bridge 관리 |
| BO Workspace | acquisition function, BO/MBO, benchmark 설정 |
| CAE Analysis | CAE/FEM 해석 bridge, 경계조건, simulation 설정 |
| Self-Evolution Lab | trace mining, candidate gate, next-run activation 관리 |

## 2. 3DP Printer GUI 개요

`Open 3DP GUI`를 누르면 `/printer`가 새 창으로 열립니다. 현재 구조에서 Bambu Lab X2D가 기본 printer provider이며, Prusa MK4S는 fallback이 아니라 **명시적으로 선택했을 때만** active printer가 됩니다.

![3DP Printer GUI overview](../assets/device_workspace_usage/02_3dp_console_overview.png)

상단 버튼의 용도는 다음과 같습니다.

| 버튼 | 용도 | 실제 구동 여부 |
|---|---|---|
| Test Status | test mode 기준 bridge 상태 조회 | 장비 구동 없음 |
| Live Status | live mode 기준 bridge 상태 조회 | 상태 조회만 수행 |
| Video Status | Bambu MQTT/video capability 조회 | 영상/상태 조회만 수행 |
| Upload Path Probe | 업로드 경로/저장소 접근성 점검 | 파일 쓰기/접근성 확인 가능 |
| Slice Bambu Artifact | Bambu Studio CLI로 STL/3MF를 Bambu용 artifact로 slicing | slicing만 수행 |
| Prepare HTTP Artifact | 프린터가 fetch할 수 있는 HTTP artifact route 준비 | 파일 노출만 수행 |
| Pre-start Check | camera/video, slicing, HTTP route, start gate, SPC readiness 통합 점검 | MQTT start publish 없음 |
| Print Command Draft | publish 전 command payload 초안 확인 | 명령 전송 없음 |
| Start Gate Check | operator/Guardian/dry-run gate 확인 | dry-run 기본값이면 publish 없음 |
| Publish Start | 승인된 조건에서 실제 start publish | 실제 시작 가능 |
| SPC Readiness | Specimen Making Agent 관점의 printer readiness 집계 | 상태 집계만 수행 |
| Open Live GUI | Live GUI로 이동 | 별도 화면 열기 |

운영 기본값은 `dry-run / no publish`가 켜져 있습니다. 실제 publish 전에는 최소한 `operator confirmed`, `Guardian approved`, `dry-run 해제`가 의도적으로 설정되어야 합니다.

`Slice Bambu Artifact`는 원본 Bambu Studio preset을 직접 수정하지 않습니다. 명시 `load_settings`가 없으면 slicing output 폴더 아래 `_atr_no_skirt_profile/`에 X2D용 machine/process/filament 복사본을 만들고, process 복사본에서 skirt/brim/raft 관련 값을 off/zero로 고정합니다. 또한 Bambu Studio CLI에는 `--export-3mf` 절대경로가 아니라 output directory 내부 basename을 전달합니다. 이 두 조건이 깨지면 `.gcode.3mf` export 실패나 `BAMBU_AUTOEJECTION_RESIDUAL_PRIME_OR_SKIRT_RISK` blocker가 날 수 있습니다.

`Video Status`와 `Pre-start Check`는 서로 다른 정보를 갱신하지만 화면에서는 같이 보여야 합니다. 영상 probe가 실패해도 기존 MQTT/progress/material 상태가 사라지면 안 됩니다. 반대로 상태 조회가 성공해도 camera frame이 없으면 camera 영역은 명확한 blocker를 표시해야 합니다. GUI의 반복 상태 갱신은 짧은 MQTT snapshot cache를 재사용해 매 poll마다 새 MQTT client와 `pushall`을 만들지 않습니다. 단, `Publish Start` 직후의 post-publish observation은 cache를 우회해 fresh MQTT report로 실제 시작 여부를 판단합니다.

## 3. Print Defaults와 Test Options 설정

아래 영역은 Live/Test workflow에서 만든 STL을 slicing하고 출력 직전까지 검증할 때 쓰는 기본값입니다.

![Print defaults and connection](../assets/device_workspace_usage/03_3dp_print_defaults_connection.png)

주요 입력값은 다음과 같습니다.

| 항목 | 설명 |
|---|---|
| Material | 필라멘트 소재. 예: `PLA` |
| Printer Model | 화면 표시 및 profile 판별용 모델명 |
| Printer Profile | slicing/profile hint. 예: `bambulab_x2d_pla_0p4_nozzle` |
| Slicer Profile Hint | Bambu Studio/PrusaSlicer 쪽 품질 profile 힌트 |
| Nozzle Diameter mm | 노즐 직경 |
| Layer Height mm | 일반 layer 높이 |
| First Layer Height mm | 첫 레이어 높이. 일반 layer와 불일치하면 bed adhesion 문제가 생길 수 있습니다. |
| First Layer Speed mm/s | 첫 레이어 속도. TPMS bare structure는 낮게 두는 편이 안정적입니다. |
| Bed Temperature C | 일반 bed 온도 |
| First Layer Bed Temperature C | 첫 레이어 bed 온도 |
| Storage Target | Bambu는 `ftps` 또는 HTTP artifact route를 사용합니다. |
| Bambu Source STL / 3MF Path | slicing할 원본 STL/3MF 경로 |
| Bambu Sliced Artifact Path | slicing 결과 artifact 경로 |
| Public Base URL optional | 프린터가 서버 artifact를 가져갈 때 사용할 LAN URL |
| Max Print Time min | Guardian/start gate가 허용할 최대 출력 시간 |

체크박스 의미는 다음과 같습니다.

| 체크박스 | 의미 | 권장 기본값 |
|---|---|---|
| overwrite existing job artifact | 같은 artifact 이름 덮어쓰기 허용 | 켬 |
| allow live workflow to start print | Live workflow가 upload 후 start까지 진행 가능 | 실제 출력 전까지 끔 |
| enable configured autoejection routine | 출력 완료 후 Bambu G-code autoejection patch 또는 선택 provider routine 요청 | provider 검증 후 켬 |
| slow down first layer | 첫 레이어 저속 출력 | 켬 |
| generate slicer skirt/brim/raft structures | skirt/brim/raft 생성 | 필요할 때만 켬 |
| generate bottom cap skin | 바닥 adhesion용 bottom cap 생성 | 필요 시 켬 |
| generate top cap skin | 압축면 평탄화용 top cap 생성 | FDM에서는 무너질 수 있어 보통 끔 |

`Test Options`는 Device Workspace와 agent test flow에서 공통으로 참조하는 기본 시편 조건입니다.

- `Test Specimen Size mm`: 예: `30,30,30`
- `Test Unit Cell Size mm`: 예: `10`
- 저장 버튼: `Save Print Defaults & Test Options`
- 저장 파일: `memory/prusa_print_profile.json`

파일명은 legacy 이름을 유지하지만, 현재는 선택된 active printer provider에 맞춰 Bambu/Prusa profile로 adapt됩니다.

## 4. Printer Fleet과 Bambu LAN Connection

`Printer Fleet Selection`에서 active printer를 고릅니다.

- 기본값: Bambu Lab X2D
- Prusa 사용: Prusa profile을 명시 선택해야 합니다.
- 선택 저장 버튼: `Set Active Printer`
- 저장 파일: `memory/printer_fleet.json`

`Bambu LAN Connection`에는 다음 값을 저장합니다.

| 항목 | 설명 |
|---|---|
| Host / IP | 프린터의 내부망 IP. 문서/로그에는 실제 값을 넣지 않습니다. |
| Serial Number / SN | Bambu 프린터 SN |
| Printer Name | 운영자가 구분하기 쉬운 장비명 |
| Model | 예: `Bambu Lab X2D` |
| Username | Bambu LAN mode 기본 사용자. 보통 `bblp` |
| LAN Access Code | 프린터에서 확인한 LAN access code. 화면에는 저장값을 다시 표시하지 않습니다. |
| LAN-only mode confirmed | 프린터에서 LAN-only mode를 확인했는지 |
| Developer mode confirmed | local write/control 권한 확인 여부 |

저장 버튼은 `Set Bridge Connection`입니다. 저장 파일은 `memory/bambu_connection.json`이며, 이 파일은 gitignore 대상입니다. Access code는 문서, 커밋, 스크린샷에 남기지 않습니다.

## 5. Bambu pre-start check 절차

실제 출력 전에는 바로 `Publish Start`를 누르지 말고 아래 순서로 확인합니다.

1. `Live Status`로 MQTT/FTPS/connection 상태를 확인합니다.
2. `Slice Bambu Artifact`로 현재 STL/3MF를 Bambu artifact로 변환합니다.
3. `Prepare HTTP Artifact`로 프린터가 접근 가능한 artifact URL을 준비합니다.
4. autoejection이 켜져 있으면 `Generate Patched Artifact`로 `.gcode.3mf` 내부 plate G-code에 Bambu 전용 ejection tail을 삽입합니다.
5. `Start Gate Check`로 operator/Guardian/dry-run gate를 확인합니다.
6. `SPC Readiness`로 Specimen Making Agent 기준 readiness를 확인합니다.
7. `Pre-start Check`로 camera/video evidence부터 slicing/patch/route/start gate/readiness까지 한 번에 점검합니다.

정상적인 dry-run 점검 결과는 다음 원칙을 만족해야 합니다.

- `will_publish=false`
- `published=false`
- `motion_started=false`
- `ready_to_publish_not_started` 또는 이에 준하는 상태
- `camera_panel`은 최신 frame 또는 명확한 blocker를 표시
- autoejection enabled 상태에서는 `autoejection_patch`가 source artifact와 patched artifact를 구분해 표시

즉, pre-start check는 **출력 직전까지 갔는지** 확인하는 절차이지, 기본적으로 출력 시작 명령을 내리는 절차가 아닙니다.

실제 출력은 다음 조건이 의도적으로 충족된 뒤에만 진행합니다.

1. artifact가 올바른 STL/3MF에서 생성됨
2. HTTP/FTPS route가 프린터에서 접근 가능함
3. `operator confirmed` 체크
4. `Guardian approved` 체크
5. `dry-run / no publish` 해제
6. `Publish Start` 실행

## 6. Bambu G-code Autoejection

Bambu 기본 profile에서는 외부 Manipulation Agent handoff가 아니라, Bambu용 sliced artifact에 deterministic G-code tail을 삽입하는 native patch 방식을 우선합니다. Prusa bed-sweep 코드를 재사용하지 않습니다.

![Bambu native autoejection gate](../assets/device_workspace_usage/04_3dp_autoejection_handoff.png)

입력값 의미는 다음과 같습니다.

| 항목 | 설명 |
|---|---|
| request Bambu autoejection | autonomous loop에서 Bambu autoejection을 요청할지 여부 |
| Provider | Bambu native path는 `bambu_gcode_patch`를 사용합니다. Prusa나 외부 routine은 명시 선택 시에만 사용합니다. |
| Source Artifact Path | Bambu Studio/OrcaSlicer가 만든 `.gcode.3mf` 또는 검증용 `.gcode` 경로 |
| Patch Target Plate | `.gcode.3mf` 내부 `Metadata/plate_#.gcode` 대상 |
| Assumed Object Size mm | standalone ejection artifact나 validator가 쓰는 가정 시편 크기. `Apply Test Size`로 Test Options 값을 가져올 수 있습니다. |
| Push Direction | P1/P1S/X1/X1C 계열에서 left/center/right push lane을 선택합니다. A1 계열은 별도 bed-slinger generator를 써야 합니다. |
| Z Push Offset mm | 출력물 top 기준 아래쪽 어느 높이에서 밀지 정하는 값입니다. 기본은 보수적인 30 mm 계열이며 object height에 따라 validator가 줄이거나 막을 수 있습니다. API와 memory/config 모두에서 최대 200 mm로 제한됩니다. |
| Push Lane Offset mm | left/right lane을 object center에서 얼마나 띄울지 정합니다. 기본은 30 mm 계열이며 최대 120 mm로 제한됩니다. |
| Push Speed mm/min | push-off motion 속도입니다. 기본은 저속 300 mm/min 계열이며 최대 1000 mm/min으로 제한됩니다. |
| Full Bed Sweep / Sweep Z / Sweep Speed | ejection 이후 잔류물을 훑는 optional sweep입니다. 기본은 낮은 Z에서 저속 sweep으로만 사용합니다. `Sweep Z`는 최대 50 mm, `Sweep Speed`는 최대 1000 mm/min으로 제한됩니다. |
| Bed-clear Evidence | 출력/ejection 후 다음 job을 허용할지 판단하는 bed-clear 상태 |

버튼 동작은 다음과 같습니다.

| 버튼 | 의미 |
|---|---|
| Fill Native G-code Defaults | 로컬 입력칸에 Bambu native patch 기본값을 채웁니다. 저장/출력은 하지 않습니다. |
| Save Autoejection Config | `memory/bambu_autoejection.json`에 operator-verified 설정 저장 |
| Validate G-code Preview | 원본 artifact를 바꾸지 않고 patch 가능성, marker, blocker, plate path를 확인합니다. |
| Validate Left / Center / Right | 원본 artifact 입력값을 바꾸지 않고 해당 push lane 기준으로 marker, object bounds, sweep path, blocker를 검증합니다. |
| Generate Ejection Test Artifact | 현재 push direction과 assumed object size로 publish 없는 standalone ejection test artifact를 생성합니다. |
| Generate Sweep Test Artifact | full-bed sweep 전용 standalone artifact를 생성합니다. 실제 프린터 시작 명령은 보내지 않습니다. |
| Generate Patched Artifact | 원본 artifact를 덮어쓰지 않고 `.autoeject.gcode.3mf` 또는 `.autoeject.gcode`를 생성합니다. |
| Standalone Eject Artifact: Left/Center/Right | 실제 출력 없이 ejection routine만 검증할 수 있는 standalone artifact를 생성합니다. 기본적으로 publish하지 않습니다. |
| Mark Bed Clear | camera 또는 operator 확인 후 다음 job을 허용하도록 bed-clear evidence를 true로 저장합니다. 직전 `Video Status` 또는 `Pre-start Check`에서 표시된 최신 camera preview/evidence reference도 `camera_snapshot_path` evidence로 함께 저장합니다. |
| Mark Not Clear | bed에 잔류물이 있거나 확인되지 않은 상태로 저장해 다음 job을 차단합니다. |
| Build Fail-Closed Proof Template | 실제 supervised 검증 결과를 채울 JSON template을 생성합니다. 기본값은 감사 실패 상태이며 프린터를 움직이지 않습니다. |
| Run Completion Audit | proof package를 읽어 center/live/left/right ejection, bed-clear, next-job gate evidence가 모두 파일로 남았는지 확인합니다. 프린터를 움직이지 않습니다. |

`Validation Evidence` 접이식 영역은 전체 G-code 본문을 보여주지 않습니다. 대신 schema marker, source plate path, plate id, loop index, validation state, blockers, object bounds, sweep path parameters, patched artifact path, manifest path만 요약합니다. 실제 motion을 판단할 때는 이 요약과 backend manifest/hash를 같이 봅니다.

Patch/test artifact가 생성되면 같은 경로에 `.manifest.json` sidecar가 함께 기록됩니다. Patch API 또는 Pre-start Check에 `run_id`가 있으면 `runs/<run_id>/workspace/printer/bambu_autoejection_manifest.json`도 안정 manifest로 추가 기록됩니다. `.gcode.3mf` 내부 plate G-code가 수정되면 기존 `Metadata/plate_#.gcode.md5`는 갱신되고, 없던 경우에도 새 md5 sidecar가 추가됩니다. Manifest에는 source/patched sha256, internal plate path, object bounds, validation blocker, publish 차단 상태가 들어가며 실제 start evidence와 구분됩니다. HTTP artifact route를 만들 때 sidecar manifest가 있으면 export artifact 옆으로 같이 복사되어, 이후 `.autoeject` publish가 bed-clear evidence를 잠글 때 source/patched hash와 manifest reference를 재사용할 수 있습니다. `Mark Bed Clear`는 verified 상태와 camera reference를 갱신하지만, 이 artifact/publish reference를 지우지 않습니다.

2026-06-16 브라우저 QA 기준으로 `/printer` 화면은 임시 FastAPI 서버와 Selenium/Firefox headless 1920x1080 렌더링에서 Bambu Device Screen, Camera/Live View, Control Gate, autoejection panel, bed-clear controls가 표시되는 것을 확인했습니다. `Video Status` 또는 `Pre-start Check` 중에는 관련 버튼이 callback 완료 전까지 잠겨야 하며, camera panel을 갱신해도 기존 MQTT/progress/material card가 사라지면 안 됩니다. Autoejection `Validation Evidence`는 기본 접힘 상태이고 full raw G-code block을 화면에 직접 노출하지 않는 것이 정상입니다.

반복 가능한 `/printer` 브라우저 audit은 `tests/ui/printer_gui_browser_audit.py`입니다. 이 스크립트는 실제 프린터를 움직이지 않고 `Physical Proof Package` 표시, fail-closed template 생성, completion audit incomplete 표시를 검증합니다.

Bambu native autoejection이 autonomous loop ready가 되려면 다음 조건이 필요합니다.

1. active printer가 Bambu profile로 명시 선택되어 있어야 합니다.
2. source artifact가 Bambu-compatible `.gcode.3mf` 또는 검증 가능한 `.gcode`여야 합니다.
3. patcher가 marker를 정확히 1개 삽입하고 validator를 통과해야 합니다.
4. ejection tail 내부에 예상 밖 `G28`/unsafe motion이 없어야 하며, bed cooldown wait(`M190 R/S...` 또는 명시 wait policy)가 있어야 합니다.
5. MQTT/FTPS 또는 HTTP artifact route가 start gate에서 검증되어야 합니다.
6. 실제 publish 후에는 `bed_clear_required=true`가 되며, 다음 cycle은 `Mark Bed Clear` 또는 vision evidence 전까지 차단됩니다.
7. 첫 live ejection 또는 geometry가 바뀐 ejection은 supervised mode와 disposable/test object로 검증해야 합니다.
8. `.autoeject.*` artifact를 실제 publish하려면 front path/door clear, ramp/bin ready, toolhead cover secured, release surface confirmed/profile, supervised first ejection checklist가 모두 통과해야 합니다.

외부 robot/Manipulation Agent handoff는 primary ejection path가 아닙니다. Ejection 실패 후 recovery나 downstream transfer가 필요할 때 별도 provider로 사용합니다.

### 6.1 Physical Proof Package와 완료 감사

Bambu autoejection을 실제 완료로 인정하려면 proof package 감사가 통과해야 합니다. `/printer`의 `Physical Proof Package` 영역은 이 과정을 GUI에서 수행합니다.

1. `Build Fail-Closed Proof Template`을 눌러 template JSON을 만듭니다.
2. 실제 프린터 앞에서 supervised center ejection, disposable live ejection, left/right lane 검증, bed-clear, next-job gate를 수행합니다.
3. 생성된 JSON에 camera before/after 이미지, post-publish observation, remote path, publish sequence, source/patched sha256, patch manifest, bed-clear evidence를 채웁니다.
4. `Run Completion Audit`을 눌러 package를 검증합니다.

감사가 실패하면 아직 실제 완료가 아닙니다. 이 상태에서는 `published=true`, `.autoeject.*` 생성, HTTP route ready, GUI success message가 있더라도 무인 반복운전 가능 상태로 보지 않습니다.

## 7. Device Workspace에서 확인해야 하는 상태 요약

| 상태 | 의미 | 다음 조치 |
|---|---|---|
| `policy upload=false start=false` | upload/start gate가 닫혀 있음 | 실제 출력 전에는 정상. publish 전 gate 확인 필요 |
| `dry-run / no publish` checked | start publish가 차단된 검사 모드 | 실제 시작 전까지 유지 |
| `Connection Confirmation`에 warning | LAN/Developer/storage/HTTP route 중 검토 항목 존재 | 카드의 action을 따라 connection/profile 수정 |
| `SPC Readiness ready` | Specimen Making Agent 기준 handoff 가능 | live/test workflow에 넘길 수 있음 |
| `native_gcode_patch_ready` | Bambu autoejection patch artifact 생성 가능 | patched artifact validator와 start gate 확인 |
| `bed_clear_required=true` | 이전 autoejection 이후 bed-clear가 아직 증명되지 않음 | Video Status 또는 Pre-start Check로 camera preview를 갱신한 뒤 camera/operator 확인 후 Mark Bed Clear |
| `BAMBU_POST_EJECT_BED_NOT_CLEAR` | 다음 job을 시작할 수 없는 bed-clear blocker | GUI의 `Publish Start`도 비활성화됩니다. bed를 확인한 뒤 `Mark Bed Clear`로 blocker를 해제해야 합니다. |

## 8. 문제 해결

| 증상 | 가능 원인 | 확인 위치 |
|---|---|---|
| `BAMBU_HTTP_ARTIFACT_URL_NOT_PRINTER_REACHABLE` | 서버 URL이 프린터 내부망에서 접근 불가 | `Public Base URL optional`, 서버 bind 주소, 방화벽 |
| `BAMBU_LAN_MODE_NOT_CONFIRMED` | LAN-only mode 체크/저장 누락 | Bambu LAN Connection 체크박스 |
| `BAMBU_DEVELOPER_MODE_NOT_CONFIRMED` | local write/control 권한 확인 누락 | Bambu LAN Connection 체크박스 |
| `BAMBU_AUTOEJECTION_NOT_CONFIGURED` | Bambu autoejection config 미저장 또는 disabled | Bambu G-code Autoejection |
| `BAMBU_AUTOEJECTION_TAIL_MISSING` | patched artifact에 schema marker가 없음 | Generate Patched Artifact 재실행 |
| `BAMBU_AUTOEJECTION_TAIL_DUPLICATED` | 같은 artifact에 autoejection marker가 중복 삽입됨 | 원본 sliced artifact에서 다시 patch |
| `BAMBU_AUTOEJECTION_UNSAFE_MOTION` | ejection tail motion이 safe envelope를 벗어남 | object size/position, bed size, sweep setting 확인 |
| `BAMBU_AUTOEJECTION_UNSAFE_FEEDRATE` | ejection tail의 X/Y push feedrate가 안전 상한을 초과함 | Push Speed 또는 Sweep Speed를 낮춘 뒤 다시 patch/validate |
| `BAMBU_AUTOEJECTION_UNEXPECTED_HOME` | ejection tail 내부에 예상 밖 homing이 있음 | G-code tail/validator 확인 |
| `BAMBU_AUTOEJECTION_MODEL_FAMILY_UNSUPPORTED` | A1/A1 Mini 같은 bed-slinger 계열에 CoreXY X-lane tail을 적용하려고 함 | A1 전용 Y-axis/wiggle generator 구현 전까지 native autoejection off 또는 지원 profile 사용 |
| `BAMBU_AUTOEJECTION_FRONT_PATH_NOT_CONFIRMED` | ejection 진행 방향의 door/front path 확인이 누락됨 | front path/door clear 체크 |
| `BAMBU_AUTOEJECTION_RAMP_OR_BIN_NOT_CONFIRMED` | 배출 후 받을 ramp/bin 확인이 누락됨 | ramp/bin ready 체크 |
| `BAMBU_AUTOEJECTION_TOOLHEAD_COVER_NOT_CONFIRMED` | toolhead/fan cover 고정 확인이 누락됨 | toolhead cover secured 체크 |
| `BAMBU_AUTOEJECTION_RELEASE_SURFACE_NOT_CONFIRMED` | release surface 확인 또는 profile 입력이 누락됨 | release surface confirmed 체크 및 profile 입력 |
| `BAMBU_AUTOEJECTION_SUPERVISED_FIRST_RUN_NOT_CONFIRMED` | 첫 live ejection/새 geometry supervised 확인이 누락됨 | supervised first ejection 체크 |
| `BAMBU_AUTOEJECTION_OBJECT_TOO_LOW` | 시편이 너무 낮아 toolhead가 안정적으로 밀기 어려움 | autoejection off 또는 pushable edge가 있는 test part 사용 |
| `BAMBU_AUTOEJECTION_OBJECT_TOO_TALL` | 시편이 너무 높아 충돌/간섭 위험이 큼 | autoejection off 또는 supervised manual removal |
| `BAMBU_AUTOEJECTION_MULTI_OBJECT_UNSUPPORTED` | 한 plate에 여러 object가 있어 bed-clear/ejection path가 불명확 | 단일 object plate로 slicing하거나 object 선택 기능 구현 후 재시도 |
| `BAMBU_AUTOEJECTION_RESIDUAL_PRIME_OR_SKIRT_RISK` | skirt/brim/raft/purge residue가 bed에 남을 위험 | skirt/brim/raft off profile로 재슬라이싱 |
| `BAMBU_3MF_HASH_UPDATE_REQUIRED` | `.gcode.3mf` 내부 G-code 수정 후 metadata/hash 갱신 필요 | patcher가 md5 갱신 가능한 artifact인지 확인 |
| `BAMBU_PROJECT_FILE_PARAM_MISMATCH` | MQTT `project_file.param`과 artifact 내부 plate path 불일치. plain `.gcode`를 `project_file`로 시작하거나, `plate_id < 1`이거나, 로컬 `.gcode.3mf` 안에 요청한 `Metadata/plate_<id>.gcode`가 없으면 upload/export 전에 이 코드로 차단됩니다. | `.gcode.3mf` artifact, `Patch Target Plate`, start command draft 확인 |
| `BAMBU_PROJECT_FILE_SUBTASK_NAME_INVALID` | MQTT `project_file.subtask_name`에 경로/제어문자 같은 표시명으로 부적절한 값이 들어감 | specimen/job 이름을 일반 표시명으로 수정하거나 비워서 artifact 이름 자동값 사용 |
| `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED` | MQTT publish ack는 받았지만 fresh observation에서 `RUNNING`/`PRINTING`/`PREPARE` 상태가 확인되지 않음 | 프린터 화면, Bambu Studio Device 화면, `/api/printer/status` 재확인 후 필요 시 재시도 |
| `BAMBU_MQTT_PUBLISH_TIMEOUT` | start publish ack/관찰 timeout. 상태조회 timeout과 별도이며 기본 publish timeout은 180초, 최소 60초입니다. | `bambu.mqtt.publish_timeout_sec`, 네트워크, 프린터 parsing 상태 확인 |
| `BAMBU_AMS_MAPPING_REQUIRED` | AMS 사용 파일인데 `ams_mapping` 누락 | AMS slot mapping 저장 후 Print Command Draft 재생성 |
| `BAMBU_AMS_MAPPING_INVALID` | `ams_mapping` 길이/값이 Bambu command 형식과 맞지 않음 | 5개 배열, 값 `-1..3` 기준으로 수정 |
| `BAMBU_FTPS_TOO_MANY_CONNECTIONS` | 프린터 FTPS connection limit 초과 가능성 | 다른 slicer/GUI/bridge 연결 종료 후 재시도 |
| `BAMBU_POST_EJECT_BED_NOT_CLEAR` | 이전 job 이후 bed-clear가 검증되지 않음 | camera 확인 후 Mark Bed Clear 또는 Mark Not Clear |
| slicing 실패 | Bambu Studio CLI 또는 source path 문제 | `Slice Bambu Artifact`, `Bridge Evidence Log` |
| publish가 안 됨 | dry-run 유지 또는 operator/Guardian gate 미승인 | 상단 start gate controls |

## 9. 관련 API와 저장 파일

GUI 버튼은 아래 API를 호출합니다. CUI/agent 쪽에서도 같은 contract를 따라야 합니다.

| 기능 | API |
|---|---|
| printer status | `GET /api/printer/status?mode=live` |
| video status | `GET /api/printer/video-status` |
| fleet read/save | `GET/POST /api/printer/fleet` |
| connection read/save | `GET/POST /api/printer/connection` |
| upload path probe | `POST /api/printer/upload-path-probe` |
| start command draft | `POST /api/printer/start-command-draft` |
| start gate | `POST /api/printer/start-gate` |
| publish start | `POST /api/printer/start-publish` |
| SPC readiness | `POST /api/printer/spc-readiness` |
| Bambu slicing | `POST /api/printer/bambu-slice-artifact` |
| HTTP artifact route | `POST /api/printer/http-artifact-route` |
| Bambu pre-start check | `POST /api/printer/bambu-prestart-check` |
| autoejection status/config/test | `GET /api/printer/autoejection-status`, `POST /api/printer/autoejection-config`, `POST /api/printer/autoejection-test`, `POST /api/printer/bambu-autoejection-sweep-test` |
| Bambu autoejection artifact patch | `POST /api/printer/bambu-autoejection-patch` |
| bed-clear evidence | `GET/POST /api/printer/bed-clear` |

저장 파일은 모두 local runtime state이며 git에 올리지 않습니다.

| 파일 | 내용 |
|---|---|
| `memory/printer_fleet.json` | active printer 선택 |
| `memory/bambu_connection.json` | Bambu LAN connection과 access code |
| `memory/bambu_autoejection.json` | Bambu autoejection native patch/provider 설정 |
| `memory/bambu_bed_clear_evidence.json` | Bambu autoejection 이후 bed-clear evidence |
| `memory/prusa_print_profile.json` | active printer에 adapt되는 print defaults/test options |
| `memory/manipulation_agent_bridge.json` | ejection recovery 또는 downstream transfer를 받을 Manipulation Agent 설정 |

## 10. 운영 규칙

- Device Workspace에서 하는 check는 기본적으로 **확인/준비** 단계입니다.
- 실제 출력 시작은 `Publish Start`에서만 일어나야 합니다.
- Bambu autoejection patch/check는 artifact 생성/검증 단계이며, 실제 시작은 `Publish Start` gate가 통과할 때만 일어나야 합니다.
- `.autoeject` artifact를 실제 출력하면 다음 cycle은 bed-clear evidence가 verified 되기 전까지 차단되어야 합니다.
- 실제 Bambu autoejection을 완료로 인정하려면 `published=true`만으로는 부족합니다. camera/operator evidence로 물체가 배출됐고 충돌/plate shift가 없었으며, 이후 bed-clear evidence가 `remote_path`, `subtask_name`, source/patched hash, manifest path, publish sequence/topic, post-publish status, camera snapshot reference와 함께 잠겼다가 `Mark Bed Clear`로 해제되고 다음 `Pre-start Check`에서 `BAMBU_POST_EJECT_BED_NOT_CLEAR`가 사라지는 것까지 확인해야 합니다.
- Access code, API key, SN 전체값, 내부망 IP 전체값은 docs/commit/log 공유용 자료에 넣지 않습니다.
- 장비가 바뀌면 fallback에 의존하지 말고 `Printer Fleet Selection`에서 active printer를 명시 선택합니다.
- GUI와 backend가 서로 다른 상태를 보이면 `Reload Connection`, `Live Status`, `SPC Readiness` 순서로 다시 확인합니다.
